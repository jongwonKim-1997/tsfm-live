"""Collected actuals and genuine local zero-shot forecasts, outside the ledger.

The chart projection deliberately does not call ``forecast_view`` with a fake
locked run. Actuals come directly from timestamped source observations; the
separate forecast envelope never claims public lock-in or benchmark eligibility.
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from .eligibility import confirmed_history, evaluate_eligibility
from .forecast import build_local_forecasts, model_predict
from .ledger import canonical_bytes, iso, parse_ts, utcnow
from .transforms import inverse_transform


def _source_metadata(cfg, history, health, now):
    """Allowlist source evidence; never copy request URLs, credentials or paths."""
    status = health.get("status", "ok" if history is not None else "source_error")
    if status not in {"ok", "source_error", "disabled"}:
        status = "source_error"
    result = {"status": status, "source_id": cfg.get("source", {}).get("adapter"),
              "fetched_ts_utc": None}
    if re.fullmatch(r"[0-9a-f]{64}", str(health.get("fingerprint", ""))):
        result["fingerprint"] = health["fingerprint"]
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,79}", str(health.get("error_type", ""))):
        result["error_type"] = health["error_type"]
    fetched = history.attrs.get("fetched_ts_utc") if history is not None else health.get("fetched_ts_utc")
    if fetched:
        try:
            fetched_time = parse_ts(fetched)
            if fetched_time > now:
                result.update(status="source_error", reason="future_fetch_timestamp")
            else:
                result["fetched_ts_utc"] = iso(fetched_time)
        except (TypeError, ValueError):
            result.update(status="source_error", reason="invalid_fetch_timestamp")
    elif history is not None:
        result.update(status="source_error", reason="missing_fetch_timestamp")
    return result


def build_dashboard(indicators, models, histories, *, now, cache_dir, predict=model_predict,
                    clock=utcnow, source_statuses=None, inference_enabled=True,
                    disabled_reason="inference_disabled"):
    """Return ``(chart_payload, private_forecast_envelope)`` for the real clock.

    ``today`` means the newest confirmed daily observation, whose actual session
    date is retained even on a weekend. ``last7days`` means seven calendar days
    ending on that observation. No synthetic point fills a closed market day.
    Inference uses enabled TSFMs only; each successful transformed output is
    converted back to the authorized level unit for its own next market close.
    ``inference_enabled=False`` still exports collected actual observations.
    """
    now = parse_ts(now)
    health = source_statuses or {}
    if not isinstance(health, dict):
        health = {row["id"]: row for row in health}
    entrants = [model for model in models if model["kind"] == "tsfm" and model.get("enabled", False)]
    sources, observed, infer_history = {}, {}, {}
    for cfg in indicators:
        iid = cfg["id"]
        history = histories.get(iid)
        source = _source_metadata(cfg, history, health.get(iid, {}), now)
        sources[iid] = source
        if not cfg.get("enabled", True) or cfg["display_policy"] != "level":
            source.update(status="disabled", reason="disabled" if not cfg.get("enabled", True)
                          else "level_display_not_authorized")
            continue
        # A fetch receipt is required to call these values collected actuals.
        if history is None or source["fetched_ts_utc"] is None:
            continue
        try:
            fetched = parse_ts(source["fetched_ts_utc"])
            data = confirmed_history(history, now)
            # An observation cannot have been acquired before its own close or
            # known publication. Filter it rather than invent acquisition proof.
            data = data.loc[(data["close_ts"] <= fetched) &
                            (data["published_ts"].isna() | (data["published_ts"] <= fetched))].copy()
            if (data["published_ts"].notna() & (data["published_ts"] < data["close_ts"])).any():
                raise ValueError("publication_precedes_close")
            if cfg["target_transform"] == "log_return_pct" and (data["value"] <= 0).any():
                raise ValueError("invalid_log_level")
            observed[iid] = data
            if source["status"] == "ok":
                infer_history[iid] = data
        except (ValueError, TypeError, KeyError):
            source.update(status="source_error", reason="source_invalid")
    envelope = build_local_forecasts(indicators, entrants if inference_enabled else [], infer_history,
                                    run_ts=now, cache_dir=cache_dir, predict=predict, now=clock)
    envelope.update(inference_enabled=bool(inference_enabled),
                    inference_reason=None if inference_enabled else disabled_reason)
    completed = parse_ts(envelope["completed_ts_utc"])
    by_key = {(record["indicator_id"], record["entrant_id"]): record for record in envelope["records"]}
    units = {"eurusd": "USD/EUR", "usdjpy": "JPY/USD", "usdkrw": "KRW/USD"}
    rows = []
    for cfg in indicators:
        iid, timezone = cfg["id"], ZoneInfo(cfg["tz"])
        source = sources[iid]
        permitted = cfg.get("enabled", True) and cfg["display_policy"] == "level"
        state = evaluate_eligibility(cfg, infer_history.get(iid), now, enforce_benchmark_window=False)
        source["freshness"] = "fresh" if state["eligible"] else state["skip_reason"]
        source["latest_expected_close_ts"] = state.get("last_close_ts")
        target = state.get("next_close_ts") if permitted else None
        def local_date(timestamp):
            return parse_ts(timestamp).astimezone(timezone).date().isoformat()
        points = []
        data = observed.get(iid)
        if data is not None:
            for observation in data.itertuples(index=False):
                points.append({"close_ts": iso(observation.close_ts),
                               "session_date": local_date(observation.close_ts),
                               "value": float(observation.value), "origin": "collected_actual", "corrected": False,
                               "published_ts": None if pd.isna(observation.published_ts) else iso(observation.published_ts),
                               "fetched_ts_utc": source["fetched_ts_utc"]})
        latest = points[-1] if points else None
        recent = []
        if latest:
            since = (date.fromisoformat(latest["session_date"]) - timedelta(days=6)).isoformat()
            recent = [point for point in points if point["session_date"] >= since]
        unit = cfg.get("unit") or ("%" if cfg["target_transform"] == "diff_bp" else units.get(iid, "level"))
        forecasts, anchor = [], None
        for model in entrants:
            record = by_key.get((iid, model["id"]))
            status = record["status"] if record else "skipped"
            quantiles = None
            reason = (record.get("skip_reason") if record else None) or (
                "disabled" if not permitted else disabled_reason if not inference_enabled else "forecast_unavailable")
            availability = "unavailable" if permitted else "disabled"
            if permitted and record and status == "ok":
                try:
                    quantiles = {q: inverse_transform(record["last_close_value"], value, cfg["target_transform"])
                                 for q, value in record["q"].items()}
                    availability = "available" if parse_ts(record["next_close_ts"]) > completed else "expired"
                    reason = None if availability == "available" else "target_already_closed"
                    anchor = next((point for point in points if
                                   parse_ts(point["close_ts"]) == parse_ts(record["last_close_ts"])), None)
                except (ValueError, TypeError, OverflowError):
                    status, reason, quantiles = "failed", "invalid_level_forecast", None
            forecasts.append({"id": model["id"], "name": model.get("name", model["id"]), "kind": "tsfm",
                              "status": status, "availability": availability, "reason": reason,
                              "median": quantiles["0.5"] if quantiles else None,
                              "lower": quantiles["0.1"] if quantiles else None,
                              "upper": quantiles["0.9"] if quantiles else None, "quantiles": quantiles,
                              "next_close_ts": target, "next_session_date": local_date(target) if target else None,
                              "unit": unit, "inference_mode": "zero_shot"})
        available = any(item["availability"] == "available" for item in forecasts)
        reason = None if available else next((item["reason"] for item in forecasts if item["reason"]),
                                            source.get("reason") or "forecast_unavailable")
        rows.append({"id": iid, "name": cfg["name"], "group": cfg["group"], "enabled": cfg.get("enabled", True),
                     "status": "available" if available else "unavailable" if permitted else "disabled",
                     "reason": reason, "unit": unit,
                     "unit_label": "yield (%)" if cfg["target_transform"] == "diff_bp" else unit,
                     "display_policy": cfg["display_policy"], "value_kind": "level",
                     "target_transform": cfg["target_transform"], "decimals": cfg.get("decimals", 2),
                     "next_close_ts": target, "next_session_date": local_date(target) if target else None,
                     "next_session_timezone": cfg["tz"], "last_observation": latest, "forecast_anchor": anchor,
                     "history": {"today": [latest] if latest else [], "last7days": recent}, "entrants": forecasts,
                     "source_status": source, "source_fetched_ts_utc": source["fetched_ts_utc"],
                     "attribution": cfg.get("attribution", ""),
                     "collection_ts_utc": source["fetched_ts_utc"],
                     "forecast_generated_ts_utc": iso(completed) if available else None})
    fetches = [source["fetched_ts_utc"] for source in sources.values() if source["fetched_ts_utc"]]
    payload = {"schema_version": "1.0", "mode": "local_zero_shot", "inference_mode": "zero_shot",
               "public_ledger_eligible": False, "run_id": envelope["run_id"], "run_date": envelope["run_date"],
               "run_state": "local_zero_shot", "run_ts_utc": iso(now), "generated_ts_utc": iso(completed),
               "forecast_generated_ts_utc": iso(completed) if inference_enabled else None,
               "collection_ts_utc": max(fetches) if fetches else None, "collected_ts_utc": max(fetches) if fetches else None,
               "evaluated_at_utc": iso(completed), "timezone": "Asia/Seoul", "horizon_sessions": 1,
               "history_basis": "latest_available_daily_observation", "history_calendar_days": 7,
               "interval_probability": 0.8, "indicators": rows}
    return json.loads(canonical_bytes(payload)), envelope
