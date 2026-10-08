"""Hindsight-only baseline/calendar validation. This module never writes a ledger."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import numpy as np

from .config.settings import CONTEXT_LEN, QUANTILES, RUN_TIME_LOCAL, SEED, TZ
from .eligibility import confirmed_history, evaluate_eligibility
from .metrics import score_forecast
from .models.baselines import Baseline
from .sources import load_indicators
from .sources.base import SourceError, normalized
from .sources.ecb import ECBSource
from .sources.ustreasury import USTreasurySource
from .transforms import transform

WARNING = ("NOT A LIVE RECORD. Historical observations were retrieved later and may include revisions; "
           "past publication availability is unverified. This validates calendars, eligibility, "
           "transforms and two baselines only, not TSFM models or the full MVP Definition of Done.")


def load_cached_histories(indicators, cache_dir: Path, start: date):
    """Parse one frozen evidence bundle; verify every downloaded body's SHA-256.

    Reuse the same ECB response for its two pair definitions. No request is made
    here: live retrieval remains separate and cannot be replaced by stale cache.
    """
    cache_dir = Path(cache_dir).resolve()
    latest = {}
    for sidecar in (cache_dir / "raw").glob("*/*/*/*.json"):
        meta = json.loads(sidecar.read_text(encoding="utf-8"))
        source = meta.get("source_id")
        url = meta.get("url", "")
        if source == "ecb" and url == ECBSource.endpoint:
            key = (source, "full")
        elif source == "ustreasury" and url.startswith(USTreasurySource.endpoint + "?"):
            params = parse_qs(urlparse(url).query)
            if params.get("data") != ["daily_treasury_yield_curve"]:
                continue
            key = (source, params.get("field_tdr_date_value", [""])[0])
        else:
            continue
        if key not in latest or meta["fetched_ts_utc"] > latest[key][0]["fetched_ts_utc"]:
            latest[key] = (meta, sidecar.with_suffix(".response"))
    payloads, evidence = {}, []
    for key, (meta, raw) in latest.items():
        body = raw.read_bytes()
        if hashlib.sha256(body).hexdigest() != meta["body_sha256"]:
            raise ValueError("cached source evidence hash mismatch")
        payloads[key] = (body, datetime.fromisoformat(meta["fetched_ts_utc"].replace("Z", "+00:00")))
        evidence.append({k: meta[k] for k in ("source_id", "url", "fetched_ts_utc", "body_sha256")})
    histories = {}
    for cfg in indicators:
        if not cfg.get("enabled"):
            continue
        adapter = cfg["source"]["adapter"]
        if adapter == "ecb" and ("ecb", "full") in payloads:
            source = ECBSource(cfg, cache_dir)
            body, fetched = payloads[("ecb", "full")]
            histories[cfg["id"]] = source.parse(body, cfg, start, fetched)
        elif adapter == "ustreasury":
            source = USTreasurySource(cfg, cache_dir)
            rows, fetched_times = [], []
            for (provider, year), (body, fetched) in payloads.items():
                if provider == "ustreasury" and year.isdigit() and int(year) >= start.year:
                    rows.extend(source.parse(body, cfg, start, fetched).to_dict("records"))
                    fetched_times.append(fetched)
            if rows:
                histories[cfg["id"]] = normalized(rows, max(fetched_times))
    if not histories:
        raise SourceError("No verified ECB/Treasury source evidence exists in the selected external cache")
    return histories, sorted(evidence, key=lambda item: item["url"])


def simulate(indicators, histories, end_date: date, days: int = 365):
    if not 1 <= days <= 3660:
        raise ValueError("days must be between 1 and 3660")
    start = end_date - timedelta(days=days - 1)
    counts = {cfg["id"]: Counter() for cfg in indicators}
    losses = {cfg["id"]: {name: [] for name in ("rw0", "volnaive")} for cfg in indicators}
    daily = []
    entrants = {name: Baseline(name) for name in ("rw0", "volnaive")}
    for day_offset in range(days):
        day = start + timedelta(days=day_offset)
        run = datetime.combine(day, time.fromisoformat(RUN_TIME_LOCAL), ZoneInfo(TZ)).astimezone(timezone.utc)
        states = {}
        for cfg in indicators:
            indicator = cfg["id"]
            history = histories.get(indicator)
            state = evaluate_eligibility(cfg, history, run)
            status = "eligible" if state["eligible"] else state["skip_reason"]
            counts[indicator][status] += 1
            states[indicator] = status
            if not state["eligible"]:
                continue
            valid = confirmed_history(history, run)
            context = transform(valid["value"].to_numpy(), cfg["target_transform"])[-CONTEXT_LEN:]
            # This future outcome is used only for retrospective scoring. It is
            # never passed to a forecast adapter or used for regime selection.
            following = datetime.fromisoformat(state["next_close_ts"])
            outcome = history.loc[history["close_ts"] == following]
            predictions = {name: entrant.predict(context.copy(), QUANTILES, SEED)
                           for name, entrant in entrants.items()}
            if outcome.empty:
                counts[indicator]["actual_unavailable_in_snapshot"] += 1
                continue
            y = float(transform([valid.iloc[-1]["value"], outcome.iloc[0]["value"]],
                                cfg["target_transform"])[0])
            for name, prediction in predictions.items():
                losses[indicator][name].append(score_forecast(y, prediction.quantiles, cfg["target_transform"]))
            counts[indicator]["scored"] += 1
        daily.append({"run_date": day.isoformat(), "states": states})
    summaries = []
    for cfg in indicators:
        indicator = cfg["id"]
        metrics = {}
        for name, scores in losses[indicator].items():
            metrics[name] = {
                "n": len(scores),
                "mean_crps": float(np.mean([s["crps"] for s in scores])) if scores else None,
                "rmse": float(np.sqrt(np.mean([s["se"] for s in scores]))) if scores else None,
                "mean_coverage80": float(np.mean([s["covered80"] for s in scores])) if scores else None,
            }
        summaries.append({"id": indicator, "enabled": cfg["enabled"],
                          "counts": dict(counts[indicator]), "baseline_metrics": metrics})
    return {"schema_version": "1.0", "kind": "partial_baseline_calendar_shadow_validation",
            "warning": WARNING, "is_live": False, "ledger_written": False,
            "start_date": start.isoformat(), "end_date": end_date.isoformat(), "run_count": days,
            "as_of": end_date.isoformat(), "generated_ts_utc": datetime.now(timezone.utc).isoformat(),
            "seed": SEED, "models_executed": ["rw0", "volnaive"], "tsfm_models_executed": [],
            "pi_scale_validated": False, "indicators": summaries, "daily": daily}


def run_shadow(root, cache_dir, end_date, days=365):
    root, cache_dir = Path(root).resolve(), Path(cache_dir).resolve()
    end_date = date.fromisoformat(end_date) if isinstance(end_date, str) else end_date
    indicators = load_indicators()
    # 800 prior calendar days permit the full 512-change context where available.
    earliest = end_date - timedelta(days=days - 1 + 800)
    histories, evidence = load_cached_histories(indicators, cache_dir, earliest)
    report = simulate(indicators, histories, end_date, days)
    report["source_evidence"] = evidence
    report["history_rows"] = {key: len(value) for key, value in histories.items()}
    destination = root / "docs" / "shadow-backtest-results.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return {"output": str(destination), "run_count": days, "is_live": False,
            "indicators_scored": sum(bool(item["counts"].get("scored")) for item in report["indicators"])}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=WARNING)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--end-date", type=date.fromisoformat, required=True)
    parser.add_argument("--days", type=int, default=365)
    arguments = parser.parse_args()
    print(json.dumps(run_shadow(arguments.root, arguments.cache_dir, arguments.end_date, arguments.days)))
