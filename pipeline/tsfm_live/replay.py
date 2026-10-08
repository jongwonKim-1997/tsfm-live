"""Resumable historical model replay; never a prospective/public ledger writer."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import time as timer
import uuid
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from filelock import FileLock

from .config.settings import LOCKIN_DEADLINE_LOCAL, QUANTILES, RUN_TIME_LOCAL, SEED, TZ
from .eligibility import confirmed_history
from .forecast import build_forecasts, model_predict
from .ledger import canonical_bytes, iso, parse_ts, sha256, utcnow
from .metrics import score_forecast
from .models import ForecastOutput, load_models
from .shadow import load_cached_histories
from .sources import load_indicators
from .transforms import transform

APPLICATION_ROOT = Path(__file__).resolve().parents[2]
WARNING = (
    "HINDSIGHT REPLAY / NON-LIVE RESEARCH FIXTURE. These are later-retrieved historical observations, "
    "possibly revised; past publication availability is unknown. Forecast timestamps are simulated. "
    "No public lock-in, live score, launch qualification, or PI-scale validation is established."
)


def private_output_path(root: Path, output: Path) -> Path:
    output, root = Path(output).resolve(), Path(root).resolve()
    for repository in (root, APPLICATION_ROOT):
        if output == repository or repository in output.parents or output in repository.parents:
            raise ValueError("Replay output must be a private directory outside the application repository")
    if "ledger" in {part.lower() for part in output.parts}:
        raise ValueError("Replay output cannot be a ledger directory")
    return output


def load_runtime_env(path: Path):
    """Read local worker paths/cache settings only; never shell-evaluate an env file."""
    allowed = {"HF_HOME", "HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE", "TRANSFORMERS_CACHE",
               "TSFM_TORCH_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"}
    for raw in Path(path).read_text(encoding="utf-8-sig").splitlines():
        text = raw.strip()
        if not text or text.startswith("#"):
            continue
        key, separator, value = text.partition("=")
        key, value = key.strip(), value.strip()
        if not separator or not (key.startswith("TSFM_PYTHON_") or key in allowed):
            raise ValueError("Runtime env file may contain only worker paths and local cache/thread settings")
        if value[:1] in {"'", '"'} and value[-1:] == value[:1]:
            value = value[1:-1]
        os.environ[key] = value


def _write_new(path, payload):
    """Atomic checkpoint creation under the run lock, with a self-checking digest."""
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    envelope = {"payload": payload, "payload_sha256": sha256(payload)}
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.partial")
    with temporary.open("xb") as stream:
        stream.write(canonical_bytes(envelope))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _read_checkpoint(path):
    envelope = json.loads(path.read_bytes())
    if sha256(envelope["payload"]) != envelope.get("payload_sha256"):
        raise ValueError(f"Replay checkpoint hash mismatch: {path.name}")
    return envelope["payload"]


def _history_fingerprints(histories):
    result = {}
    for iid, frame in sorted(histories.items()):
        rows = [{"close_ts": iso(parse_ts(r["close_ts"])), "value": float(r["value"]),
                 "published_ts": None if pd.isna(r["published_ts"])
                 else iso(parse_ts(r["published_ts"]))}
                for r in frame.to_dict("records")]
        result[iid] = {"rows": len(rows), "sha256": sha256(rows)}
    return result


def _software_fingerprint(root, models):
    code = hashlib.sha256()
    for path in sorted(Path(__file__).parent.rglob("*.py")):
        code.update(str(path.relative_to(Path(__file__).parent)).replace("\\", "/").encode())
        code.update(path.read_bytes())
    lock = Path(root) / "pipeline/uv.lock"
    workers = {}
    for model in models:
        key = model.get("worker_env")
        if model["kind"] != "tsfm" or not key:
            continue
        value = os.environ.get(key)
        if not value or not Path(value).is_file():
            raise ValueError(f"Missing configured local model worker: {model['id']}")
        executable = Path(value).resolve()
        profile_lock = executable.parents[2] / "uv.lock"
        workers[key] = {"interpreter": str(executable),
                        "profile_lock_sha256": hashlib.sha256(profile_lock.read_bytes()).hexdigest() if profile_lock.exists() else None}
    return {"code_sha256": code.hexdigest(),
            "core_lock_sha256": hashlib.sha256(lock.read_bytes()).hexdigest() if lock.exists() else None,
            "workers": workers}


def _summary(plan, completed):
    counts = Counter()
    grouped = defaultdict(list)
    for day in completed:
        counts.update(r["status"] for r in day["forecasts"]["records"])
        for score in day["scores"]:
            grouped[score["indicator_id"], score["entrant_id"]].append(score)
    metrics = []
    for (iid, eid), records in sorted(grouped.items()):
        metrics.append({"indicator_id": iid, "entrant_id": eid, "n": len(records),
                        "mean_crps": float(np.mean([r["crps"] for r in records])),
                        "rmse": float(np.sqrt(np.mean([r["se"] for r in records]))),
                        "coverage80": float(np.mean([r["covered80"] for r in records])),
                        "coverage95": float(np.mean([r["covered95"] for r in records]))})
    return {"kind": "historical_model_replay_hindsight_fixture", "warning": WARNING,
            "is_live": False, "ledger_written": False, "synthetic_inputs": plan["synthetic_inputs"],
            "plan_sha256": sha256(plan), "start_date": plan["start_date"], "end_date": plan["end_date"],
            "planned_days": plan["days"], "completed_days": len(completed),
            "replay_finished": len(completed) == plan["days"], "full_spec_completed": False,
            "pi_scale_validated": False, "models_requested": [m["id"] for m in plan["models"]],
            "counts": dict(counts), "scored_outputs": sum(len(d["scores"]) for d in completed),
            "outcomes_missing_from_snapshot": sum(len(d["unavailable_actuals"]) for d in completed),
            "metrics": metrics, "source_evidence": plan["source_evidence"],
            "generated_ts_utc": iso(utcnow())}


def run_replay(root, cache_dir, output_dir, end_date, *, days=365, baselines_only=False,
               max_new_days=None, indicators=None, models=None, histories=None,
               predict=model_predict, progress=None):
    """Resume identical frozen inputs; checkpoint every successful model triple.

    A completed day is never inferred again. On interruption, individual saved
    successful predictions are reused. Failed day outputs remain an honest
    recorded failure; use a new output directory for a deliberately new attempt.
    Injected histories exist for offline unit tests and are labeled synthetic.
    """
    if not 1 <= days <= 3660 or (max_new_days is not None and max_new_days < 1):
        raise ValueError("days/max_new_days must be positive (days <= 3660)")
    root = Path(root).resolve()
    destination = private_output_path(root, output_dir)
    end = date.fromisoformat(end_date) if isinstance(end_date, str) else end_date
    beginning = end - timedelta(days=days - 1)
    indicators = copy.deepcopy(load_indicators() if indicators is None else indicators)
    models = copy.deepcopy(load_models() if models is None else models)
    models = [m for m in models if m.get("enabled") and (not baselines_only or m["kind"] == "baseline")]
    if not models:
        raise ValueError("No enabled replay entrants")
    synthetic = histories is not None
    evidence = []
    if histories is None:
        histories, evidence = load_cached_histories(indicators, Path(cache_dir), beginning - timedelta(days=800))
    plan = {"kind": "historical_model_replay_plan", "warning": WARNING, "schema_version": "1.0",
            "is_live": False, "synthetic_inputs": synthetic, "days": days,
            "start_date": beginning.isoformat(), "end_date": end.isoformat(),
            "indicators": indicators, "models": models, "source_evidence": evidence,
            "histories": _history_fingerprints(histories), "seed": SEED,
            "software": _software_fingerprint(root, models)}
    destination.mkdir(parents=True, exist_ok=True)
    with FileLock(str(destination / ".replay.lock"), timeout=1):
        plan_path = destination / "plan.json"
        if plan_path.exists():
            if canonical_bytes(_read_checkpoint(plan_path)) != canonical_bytes(plan):
                raise ValueError("Replay inputs/config/software changed; use a new private output directory")
        else:
            if any(p.name != ".replay.lock" and not (p.name.startswith(".plan.json.") and p.name.endswith(".partial"))
                   for p in destination.iterdir()):
                raise ValueError("New replay output directory must be empty")
            _write_new(plan_path, plan)
        plan_hash = sha256(plan)
        for path in (destination / "predictions").glob("*/*/*.json"):
            saved = _read_checkpoint(path)
            if saved["binding"]["plan_sha256"] != plan_hash:
                raise ValueError("Model checkpoint belongs to a different replay plan")
        completed, new_days = [], 0
        for offset in range(days):
            day = beginning + timedelta(days=offset)
            day_text = day.isoformat()
            checkpoint = destination / "days" / f"{day_text}.json"
            if checkpoint.exists():
                saved = _read_checkpoint(checkpoint)
                if saved["plan_sha256"] != plan_hash or saved["run_date"] != day_text:
                    raise ValueError("Day checkpoint belongs to a different replay plan")
                completed.append(saved)
                continue
            if max_new_days is not None and new_days >= max_new_days:
                continue
            run, deadline = (datetime.combine(day, time.fromisoformat(t), ZoneInfo(TZ)).astimezone(timezone.utc)
                             for t in (RUN_TIME_LOCAL, LOCKIN_DEADLINE_LOCAL))
            records, scored, unavailable = [], [], []
            for cfg in indicators:
                iid = cfg["id"]
                integrity_errors = []

                def checkpoint_predict(model, context, *, seed, timeout):
                    path = destination / "predictions" / day_text / iid / f"{model['id']}.json"
                    binding = {"plan_sha256": plan_hash, "run_date": day_text, "indicator_id": iid,
                               "entrant_id": model["id"], "seed": seed, "context_hash": sha256(context.tolist())}
                    if path.exists():
                        try:
                            saved = _read_checkpoint(path)
                            if saved["binding"] != binding:
                                raise ValueError("Model checkpoint context/config mismatch")
                        except (KeyError, ValueError) as exc:
                            integrity_errors.append(str(exc))
                            raise
                    else:
                        began = timer.monotonic()
                        result = predict(model, context.copy(), seed=seed, timeout=timeout)
                        if set(result.quantiles) != {str(q) for q in QUANTILES}:
                            raise ValueError("Replay model output must use the protocol quantile grid")
                        saved = {"binding": binding, "output": asdict(result),
                                 "inference_seconds": timer.monotonic() - began}
                        # Validate construction before checkpointing a malformed result.
                        ForecastOutput(**saved["output"])
                        _write_new(path, saved)
                        saved = _read_checkpoint(path)
                    return ForecastOutput(**saved["output"])

                document = build_forecasts([cfg], models, histories, run, deadline, day_text,
                                          f"hindsight-replay-{day_text}", destination / "private",
                                          predict=checkpoint_predict, now=lambda: run, dry_run=True)
                if integrity_errors:
                    raise ValueError(integrity_errors[0])
                records.extend(document["records"])
                valid_records = [r for r in document["records"] if r["status"] == "ok"]
                if not valid_records:
                    continue
                past = confirmed_history(histories[iid], run)
                target = parse_ts(valid_records[0]["next_close_ts"])
                outcome = histories[iid].loc[histories[iid]["close_ts"] == target]
                if outcome.empty:
                    unavailable.append({"indicator_id": iid, "close_ts": iso(target)})
                    continue
                # The realized future is read only after all forecasts for this
                # indicator have completed; it never enters adapter inputs.
                actual = float(transform([past.iloc[-1]["value"], outcome.iloc[0]["value"]], cfg["target_transform"])[0])
                for record in valid_records:
                    scored.append({"forecast_run_date": day_text, "indicator_id": iid,
                        "entrant_id": record["entrant_id"], "regime": record["regime"],
                        "unscorable": None, **score_forecast(actual, record["q"], cfg["target_transform"])})
            payload = {"kind": "historical_replay_day_hindsight_fixture", "warning": WARNING,
                       "is_live": False, "plan_sha256": plan_hash, "run_date": day_text,
                       "forecasts": {"run_id": f"hindsight-replay-{day_text}", "run_date": day_text,
                                     "run_ts_utc": iso(run), "lockin_deadline_utc": iso(deadline), "records": records},
                       "scores": scored, "unavailable_actuals": unavailable}
            _write_new(checkpoint, payload)
            completed.append(_read_checkpoint(checkpoint))
            new_days += 1
            if progress:
                progress({"event": "replay_day_complete", "run_date": day_text,
                          "completed_days": len(completed), "planned_days": days, "is_live": False})
        summary = _summary(plan, completed)
        temporary = destination / ".summary.partial"
        temporary.write_bytes(canonical_bytes(summary))
        os.replace(temporary, destination / "summary.json")
        if summary["replay_finished"] and not (destination / "aggregates.json").exists():
            from .aggregate import build_aggregates
            aggregate = build_aggregates([s for d in completed for s in d["scores"]], indicators, models, end.isoformat())
            _write_new(destination / "aggregates.json", {"warning": WARNING, "is_live": False,
                       "plan_sha256": plan_hash, "data": aggregate})
        return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=WARNING)
    parser.add_argument("--root", type=Path, default=APPLICATION_ROOT)
    parser.add_argument("--cache-dir", type=Path, required=True, help="Existing frozen raw-source evidence; no download")
    parser.add_argument("--output-dir", type=Path, required=True, help="Private directory outside the repository")
    parser.add_argument("--runtime-env", type=Path, help="Existing local worker paths and cache settings")
    parser.add_argument("--end-date", type=date.fromisoformat, required=True)
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--baselines-only", action="store_true")
    parser.add_argument("--max-new-days", type=int, help="Bound work now; identical later commands resume checkpoints")
    args = parser.parse_args(argv)
    if args.runtime_env:
        load_runtime_env(args.runtime_env)
    summary = run_replay(args.root, args.cache_dir, args.output_dir, args.end_date,
                         days=args.days, baselines_only=args.baselines_only, max_new_days=args.max_new_days,
                         progress=lambda event: print(json.dumps(event), flush=True))
    print(json.dumps({k: v for k, v in summary.items() if k not in {"metrics", "source_evidence"}}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
