"""Identical contexts, isolated model workers, and a hard publication budget."""
from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import asdict
from pathlib import Path

from .config.settings import CONTEXT_LEN, MODEL_TIMEOUT_S, QUANTILES, SEED
from .eligibility import confirmed_history, evaluate_eligibility
from .ledger import canonical_bytes, iso, parse_ts, sha256, utcnow
from .models import create_entrant
from .models.base import derive_seed
from .models.baselines import ewma_sigma, regime_flag
from .models.ensemble import ensemble
from .schemas import ForecastFile, ForecastRecord
from .transforms import transform


def model_predict(cfg, context, *, timeout=MODEL_TIMEOUT_S, seed=SEED):
    if cfg["kind"] == "baseline":
        return create_entrant(cfg).predict(context.copy(), QUANTILES, seed)
    interpreter = os.environ.get(cfg.get("worker_env", ""))
    if not interpreter:
        raise RuntimeError("runtime_not_configured")
    env = os.environ.copy()
    env.update(PYTHONPATH=str(Path(__file__).resolve().parents[1]), PYTHONIOENCODING="utf-8",
               HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", TOKENIZERS_PARALLELISM="false",
               CUBLAS_WORKSPACE_CONFIG=":4096:8")
    request = {"config": cfg, "context": context.tolist(), "quantiles": QUANTILES, "seed": seed}
    result = subprocess.run([interpreter, "-m", "tsfm_live.models.worker"],
                            input=json.dumps(request), text=True, encoding="utf-8", capture_output=True,
                            timeout=timeout, env=env)
    if result.returncode:
        raise RuntimeError("worker_failed")
    response = json.loads(result.stdout)
    if not response.get("ok"):
        raise RuntimeError(response.get("error_type", "worker_failed"))
    from .models.base import ForecastOutput
    return ForecastOutput(**response["output"])


def build_forecasts(indicators, models, histories, run_ts, deadline, run_date, run_id, cache_dir,
                    *, predict=model_predict, now=utcnow, dry_run=False):
    records = []
    for cfg in indicators:
        history = histories.get(cfg["id"])
        state = evaluate_eligibility(cfg, history, run_ts)
        context = None
        last = None
        if state["eligible"]:
            valid = confirmed_history(history, run_ts)
            context = transform(valid["value"].to_numpy(), cfg["target_transform"])[-CONTEXT_LEN:]
            last = float(valid.iloc[-1]["value"])
            # Private level anchor is necessary for return_only actuals and source revisions.
            private = Path(cache_dir) / "contexts" / run_date / f"{cfg['id']}.json"
            private.parent.mkdir(parents=True, exist_ok=True)
            payload = {"last_close_value": last, "last_close_ts": state["last_close_ts"],
                       "context": context.tolist(), "context_hash": sha256(context.tolist())}
            expected = canonical_bytes(payload)
            try:
                with private.open("xb") as handle:
                    handle.write(expected)
            except FileExistsError:
                if private.read_bytes() != expected:
                    # Never associate a newly calculated context with a different
                    # already-persisted level anchor for the same run.
                    state.update(eligible=False, skip_reason="context_cache_conflict")
                    context = None
        outputs = {}
        for m in models:
            rec = {"indicator_id": cfg["id"], "entrant_id": m["id"],
                   "entrant_version": m.get("version", m.get("package", "builtin")) +
                       (";hf=" + m["hf_repo"] + "@" + m["hf_revision"] if m.get("hf_revision") else ""),
                   "target_transform": cfg["target_transform"],
                   "seed": derive_seed(run_date, cfg["id"], m["id"], SEED),
                   "last_close_ts": state.get("last_close_ts"), "next_close_ts": state.get("next_close_ts"),
                   "status": "skipped", "skip_reason": state.get("skip_reason") or "entrant_disabled",
                   "q": {}, "inference_seconds": 0}
            if context is not None:
                rec.update(context_len=len(context), context_hash=sha256(context.tolist()),
                           last_close_value=last if cfg["display_policy"] == "level" else None,
                           sigma_ewma=float(ewma_sigma(context)), regime=regime_flag(context))
            if not state["eligible"] or not m.get("enabled", False):
                records.append(rec)
                continue
            # Leave two minutes for the two-commit publication + CI. Never start work
            # that is certain to exceed the current critical-path budget.
            boundary = min(deadline, parse_ts(state["next_close_ts"]))
            remaining = (boundary - now()).total_seconds() - 120
            if not dry_run and remaining <= 0:
                reason = "deadline_missed" if now() >= deadline else "publication_budget_exhausted"
                rec.update(status="void" if reason == "deadline_missed" else "skipped", skip_reason=reason)
                records.append(rec)
                continue
            start = time.monotonic()
            try:
                if m["kind"] == "ensemble":
                    output = ensemble(outputs)
                    rec["contributors"] = sorted(outputs)
                else:
                    output = predict(m, context.copy(), seed=rec["seed"],
                                     timeout=MODEL_TIMEOUT_S if dry_run else min(MODEL_TIMEOUT_S, remaining))
                value = asdict(output)
                candidate = {**rec, "status": "ok", "skip_reason": None, "q": value["quantiles"],
                             "mean": value.get("mean"), "quantile_method": value["quantile_method"],
                             "n_samples": value.get("n_samples")}
                # Validate the complete 13-quantile record before accepting it
                # or letting it contribute to the ensemble. One bad adapter is
                # an isolated failure, not a failed whole-run serialization.
                ForecastRecord.model_validate(candidate)
                if not dry_run and now() >= boundary:
                    rec.update(status="void", skip_reason="deadline_missed" if now() >= deadline
                               else "target_already_closed")
                    rec["inference_seconds"] = time.monotonic() - start
                    records.append(rec)
                    continue
                rec.update(candidate)
                if m["kind"] == "tsfm":
                    outputs[m["id"]] = output
            except subprocess.TimeoutExpired:
                rec.update(status="failed", skip_reason="model_timeout")
            except Exception as exc:
                reason = "insufficient_models" if "insufficient_models" in str(exc) else type(exc).__name__
                rec.update(status="skipped" if reason == "insufficient_models" else "failed", skip_reason=reason)
            rec["inference_seconds"] = time.monotonic() - start
            records.append(rec)
    if not dry_run:
        completed_at = now()
        for record in records:
            if completed_at >= deadline:
                record.update(status="void", skip_reason="deadline_missed", q={}, mean=None,
                              quantile_method=None, n_samples=None, contributors=[])
            elif record["status"] == "ok" and completed_at >= parse_ts(record["next_close_ts"]):
                record.update(status="void", skip_reason="target_already_closed", q={}, mean=None,
                              quantile_method=None, n_samples=None, contributors=[])
    f = ForecastFile.model_validate({"run_id": run_id, "run_date": run_date, "run_ts_utc": iso(run_ts),
                                    "lockin_deadline_utc": iso(deadline), "records": records})
    return json.loads(canonical_bytes(f))
