"""Explicitly synthetic, private ledger fixtures for integration and UI tests.

This module never downloads data, executes models, publishes, or writes the
application repository. Its generated scores exercise the real metric/export
code, but are invented test observations and cannot establish live performance.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from scipy.stats import norm

from tsfm_live.calendars import session_bounds
from tsfm_live.config.settings import QUANTILES, SEED
from tsfm_live.ledger import append_json, canonical_bytes, iso
from tsfm_live.metrics import score_forecast
from tsfm_live.models import derive_seed, load_models
from tsfm_live.sources import load_indicators
from tsfm_live.transforms import inverse_transform

UTC = timezone.utc
REPOSITORY = Path(__file__).resolve().parents[2]
FIXTURE_NOTICE = "SYNTHETIC TEST FIXTURE. No real model execution, market observation, or live lock-in."


def fixture_catalogs():
    indicators = []
    for original in load_indicators():
        if original["id"] not in {"eurusd", "usdjpy", "ust10y"}:
            continue
        cfg = copy.deepcopy(original)
        cfg.update(name=f"Fixture {cfg['id']}", enabled=True, disabled_reason=None,
                   source={"adapter": "fixture", "params": {}}, fixture=True,
                   license_note=FIXTURE_NOTICE)
        indicators.append(cfg)
    models = []
    for original in load_models():
        model = copy.deepcopy(original)
        model.update(name=f"Fixture {model['id']}", enabled=True, fixture=True,
                     runtime_verified=False, launch_ready=False, package="fixture-only",
                     hf_repo=None, hf_revision=None, notes=FIXTURE_NOTICE,
                     disabled_reason=None, validation_status="synthetic_fixture_only")
        models.append(model)
    return indicators, models


def generate_fixture(root: Path, *, days=90, end_date="2026-10-07", unscorable=(), return_only=()):
    """Create a new isolated fixture root; refuse any repository descendant.

    ``unscorable`` contains (forecast date, indicator id) pairs. Those outcomes
    are deliberately absent, with null-metric records after the five-day grace.
    Three genuine calendar schedules and all eleven catalog identities are used;
    all numeric observations and predictions are plainly synthetic.
    """
    root = Path(root).resolve()
    if root == REPOSITORY or REPOSITORY in root.parents or root in REPOSITORY.parents:
        raise ValueError("Fixture output must be outside the application repository")
    if root.exists() and any(root.iterdir()):
        raise FileExistsError("Fixture root must be empty to preserve isolation")
    if days < 1:
        raise ValueError("positive fixture day count required")
    root.mkdir(parents=True, exist_ok=True)
    end = date.fromisoformat(str(end_date))
    beginning = end - timedelta(days=days - 1)
    indicators, models = fixture_catalogs()
    for cfg in indicators:
        if cfg["id"] in return_only:
            cfg["display_policy"] = "return_only"
    missing = set(unscorable)
    manifest_paths, hashes, actuals, scores = [], [], defaultdict(list), defaultdict(list)
    eligible_dates = defaultdict(list)
    for offset in range(days):
        day = beginning + timedelta(days=offset)
        day_text = day.isoformat()
        run = datetime.combine(day, time(8, 10), ZoneInfo("Asia/Seoul")).astimezone(UTC)
        deadline = run + timedelta(minutes=40)
        records = []
        for indicator_number, cfg in enumerate(indicators):
            iid = cfg["id"]
            last, target = session_bounds(cfg, run)
            eligible = target - run <= timedelta(hours=24)
            scale = 6.0 if cfg["target_transform"] == "diff_bp" else 0.30
            anchor = {"eurusd": 1.10, "usdjpy": 145., "ust10y": 4.}[iid]
            y = scale * (0.75 * math.sin(offset / 3 + indicator_number) + 0.25 * math.cos(offset / 7))
            regime = "high_vol" if offset % 4 == 0 else "normal"
            if eligible:
                eligible_dates[iid].append(day_text)
                fetched = target + timedelta(hours=4)
                actual_date = fetched.astimezone(ZoneInfo("Asia/Seoul")).date().isoformat()
                if (day_text, iid) not in missing:
                    actuals[actual_date].append({"indicator_id": iid, "close_ts": iso(target),
                        "value": inverse_transform(anchor, y, cfg["target_transform"]) if cfg["display_policy"] == "level" else None, "y": y,
                        "source_id": "fixture-not-a-source",
                        "source_fingerprint": hashlib.sha256(f"fixture|{iid}".encode()).hexdigest(),
                        "published_ts": iso(target + timedelta(minutes=30)), "fetched_ts_utc": iso(fetched)})
            for entrant_number, model in enumerate(models):
                eid = model["id"]
                mu = 0. if model["kind"] == "baseline" else scale * 0.4 * math.sin((offset - 1) / 3 + indicator_number)
                spread = scale * (1.2 if eid == "volnaive" else 0.65 + entrant_number / 40)
                quantiles = {str(q): (0. if eid == "rw0" else mu + spread * float(norm.ppf(q))) for q in QUANTILES}
                record = {"indicator_id": iid, "entrant_id": eid,
                    "entrant_version": "fixture-not-executed", "status": "ok" if eligible else "skipped",
                    "skip_reason": None if eligible else "outside_horizon",
                    "target_transform": cfg["target_transform"], "last_close_ts": iso(last),
                    "last_close_value": anchor if cfg["display_policy"] == "level" else None,
                    "next_close_ts": iso(target), "context_len": 512,
                    "context_hash": hashlib.sha256(f"fixture|{day_text}|{iid}".encode()).hexdigest(),
                    "regime": regime, "sigma_ewma": scale, "q": quantiles if eligible else {},
                    "mean": mu if eligible else None, "quantile_method": "native" if eligible else None,
                    "n_samples": None, "seed": derive_seed(day_text, iid, eid, SEED),
                    "inference_seconds": 0., "contributors": []}
                records.append(record)
                if not eligible:
                    continue
                unresolved = (day_text, iid) in missing
                scored_at = target + (timedelta(days=5, minutes=1) if unresolved else timedelta(hours=5))
                score_date = scored_at.astimezone(ZoneInfo("Asia/Seoul")).date().isoformat()
                score = {"forecast_run_date": day_text, "indicator_id": iid, "entrant_id": eid,
                         "regime": regime, "scored_ts_utc": iso(scored_at),
                         "unscorable": "actual_unavailable" if unresolved else None}
                if not unresolved:
                    # Quantiles are rounded exactly as issued before scoring.
                    issued_q = json.loads(canonical_bytes(quantiles))
                    score.update(score_forecast(round(y, 6), issued_q, cfg["target_transform"]))
                scores[score_date].append(score)
        doc = {"run_id": f"fixture-{day_text}", "run_date": day_text, "run_ts_utc": iso(run),
               "lockin_deadline_utc": iso(deadline), "records": records}
        path = root / f"ledger/forecasts/{day.year}/{day_text}.json"
        digest = append_json(path, doc, "forecasts")
        hashes.append((day_text, digest))
        manifest = {"run_id": f"fixture-{day_text}", "run_date": day_text, "run_ts_utc": iso(run),
                    "scheduled_ts": iso(run), "actual_start_ts": iso(run), "uv_lock_sha256": "f" * 64,
                    "python_version": "fixture", "hardware": "fixture-no-model-executed", "entrants": [],
                    "sources": [{"id": cfg["id"], "fixture": True, "status": "fixture"} for cfg in indicators],
                    "steps": [{"name": "fixture_generator", "notice": FIXTURE_NOTICE}],
                    "lockin_ts_utc": iso(run + timedelta(minutes=2)), "deadline_met": True,
                    "forecasts_sha256": digest, "forecasts_commit": "f" * 40,
                    "counts": {"ok": sum(r["status"] == "ok" for r in records)}, "mode": "live"}
        manifest_path = root / f"ledger/manifests/{day.year}/fixture-{day_text}.json"
        append_json(manifest_path, manifest, "manifests")
        manifest_paths.append(manifest_path)
    for kind, grouped in (("actuals", actuals), ("scores", scores)):
        for day_text, records in sorted(grouped.items()):
            append_json(root / f"ledger/{kind}/{day_text[:4]}/{day_text}.json",
                        {"run_date": day_text, "records": records}, kind)
    (root / "ledger/HASHES.md").write_text("| Date | SHA-256 | Forecast commit | OTS |\n|---|---|---|---|\n" +
        "".join(f"| {day} | {digest} | {'f' * 40} | fixture |\n" for day, digest in hashes), encoding="utf-8")
    marker = {"fixture": True, "notice": FIXTURE_NOTICE, "from": beginning.isoformat(), "to": end.isoformat(),
              "days": days, "indicators": [i["id"] for i in indicators], "entrants": [m["id"] for m in models],
              "eligible_dates": dict(eligible_dates), "return_only": list(return_only),
              "network_requests": 0, "model_executions": 0}
    (root / "FIXTURE_ONLY.json").write_bytes(canonical_bytes(marker))
    return marker


def export_fixture(root: Path, *, now=None, write_snapshot=False):
    """Run real export code with fixture catalogs, then label every API document."""
    from tsfm_live.export import export_site
    if not (root / "FIXTURE_ONLY.json").exists():
        raise ValueError("Missing fixture isolation marker")
    indicators, models = fixture_catalogs()
    marker = json.loads((root / "FIXTURE_ONLY.json").read_bytes())
    for cfg in indicators:
        if cfg["id"] in marker.get("return_only", []):
            cfg["display_policy"] = "return_only"
    with patch("tsfm_live.export.load_indicators", return_value=indicators), \
            patch("tsfm_live.export.load_models", return_value=models):
        result = export_site(root, now=now, write_snapshot=write_snapshot)
    for path in (root / "site/public/api/v1").rglob("*.json"):
        data = json.loads(path.read_bytes())
        data.update(fixture=True, fixture_notice=FIXTURE_NOTICE)
        if path.name == "meta.json":
            data.update(mode="fixture", brand_name="TSFM FIXTURE — synthetic test data", operator="Local fixture test")
        path.write_bytes(canonical_bytes(data))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--end-date", default="2026-10-07")
    args = parser.parse_args()
    marker = generate_fixture(args.root, days=args.days, end_date=args.end_date)
    summary = export_fixture(args.root)
    print(json.dumps({"fixture": True, "root": str(args.root.resolve()), "generated": summary,
                      "days": marker["days"], "notice": FIXTURE_NOTICE}, indent=2))
