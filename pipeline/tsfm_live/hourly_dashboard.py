"""Genuine hourly level forecasts from finalized, contiguous 24/7 observations.

This is separate from the daily change-based benchmark. Every model forecasts
levels directly, so per-hour quantiles are marginal level distributions rather
than mathematically invalid sums of marginal return quantiles.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import time
from datetime import timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .config.settings import MODEL_TIMEOUT_S, QUANTILES, SEED
from .forecast import model_predict
from .ledger import canonical_bytes, iso, parse_ts, sha256, utcnow
from .models.base import ForecastPathOutput, derive_seed


HORIZON = 24
INTERVAL_SECONDS = 3600
TOTAL_INFERENCE_BUDGET_SECONDS = 600
KST = ZoneInfo("Asia/Seoul")


def hour_floor(value):
    return parse_ts(value).replace(minute=0, second=0, microsecond=0)


def hourly_history(cfg, history, *, now, source_status=None):
    """Return (confirmed frame, eligibility); unavailable calendars stay hidden."""
    now = parse_ts(now)
    expected = hour_floor(now)
    state = {"eligible": False, "reason": None, "status": "unavailable", "frequency": "1h",
             "expected_latest_close_ts": iso(expected), "fetched_ts_utc": None,
             "last_close_ts": None, "next_update_due_ts_utc": None}
    if not cfg.get("enabled", False):
        state["reason"] = "disabled"
        return None, state
    if cfg.get("calendar") != "24/7" or cfg.get("frequency") != "1h":
        state["reason"] = "calendar_unverified"
        return None, state
    if cfg.get("market_status", "open") != "open":
        state["reason"] = "market_closed_or_unknown"
        return None, state
    if cfg.get("display_policy") != "level":
        state["reason"] = "level_display_not_authorized"
        return None, state
    if source_status and source_status.get("status") != "ok":
        state["reason"] = "source_error"
        return None, state
    if history is None:
        state["reason"] = "source_error"
        return None, state
    try:
        fetched = parse_ts(history.attrs["fetched_ts_utc"])
        if fetched > now:
            raise ValueError("future_fetch")
        state["fetched_ts_utc"] = iso(fetched)
        data = history.copy()
        for column in ("close_ts", "value", "published_ts"):
            if column not in data:
                raise ValueError("missing_column")
        for timestamp in list(data["close_ts"]) + list(data["published_ts"].dropna()):
            if pd.isna(timestamp) or pd.Timestamp(timestamp).tzinfo is None:
                raise ValueError("naive_timestamp")
        data["close_ts"] = pd.to_datetime(data["close_ts"], utc=True)
        data["published_ts"] = pd.to_datetime(data["published_ts"], utc=True)
        data["value"] = pd.to_numeric(data["value"], errors="raise").astype(float)
        if data["close_ts"].duplicated().any() or not data["close_ts"].is_monotonic_increasing:
            raise ValueError("duplicate_or_unsorted")
        # Source APIs may include their currently forming candle. It must not
        # influence either the input context or the actual-value line.
        mask = (data["close_ts"] <= min(now, fetched)) & (
            data["published_ts"].isna() | (data["published_ts"] <= min(now, fetched)))
        if "is_final" in data:
            mask &= data["is_final"].eq(True)
        data = data.loc[mask].copy()
        if (not np.isfinite(data["value"].to_numpy()).all() or (data["value"] <= 0).any()
                or (data["published_ts"].notna() & (data["published_ts"] < data["close_ts"])).any()
                or not data["close_ts"].eq(data["close_ts"].dt.floor("h")).all()):
            raise ValueError("invalid_hourly_values")
    except (ValueError, TypeError, KeyError, OverflowError):
        state["reason"] = "source_invalid"
        return None, state
    if data.empty:
        state["reason"] = "source_lag"
        return data, state
    last = parse_ts(data.iloc[-1]["close_ts"])
    state.update(last_close_ts=iso(last), next_update_due_ts_utc=iso(last + timedelta(hours=1)))
    if last != expected:
        state["reason"] = "source_lag"
        return data, state
    context_length = cfg.get("context_length", 512)
    if not isinstance(context_length, int) or not 300 <= context_length <= 512:
        state["reason"] = "invalid_context_length"
        return data, state
    minimum = max(300, cfg.get("min_history", 300))
    if len(data) < minimum:
        state["reason"] = "insufficient_history"
        return data, state
    needed = data.tail(context_length)
    if not needed["close_ts"].diff().dropna().eq(pd.Timedelta(hours=1)).all():
        state["reason"] = "history_gap"
        return data, state
    state.update(eligible=True, reason=None, status="fresh")
    return data, state


def build_hourly_dashboard(indicators, models, histories, *, now, cache_dir, predict=model_predict,
                           clock=utcnow, source_statuses=None, inference_enabled=True,
                           disabled_reason="inference_disabled"):
    """Return a chart projection and private raw envelope without ledger claims."""
    now = parse_ts(now)
    started = parse_ts(clock())
    if not 0 <= (started - now).total_seconds() <= 30:
        raise ValueError("hourly issue time must match the current clock")
    health = source_statuses or {}
    if not isinstance(health, dict):
        health = {row["id"]: row for row in health}
    entrants = [model for model in models if model.get("enabled") and model["kind"] == "tsfm"]
    run_id = "hourly-" + now.strftime("%Y%m%dT%H%M%S%fZ")
    run_day = now.astimezone(KST).date().isoformat()
    budget_end = now + timedelta(seconds=TOTAL_INFERENCE_BUDGET_SECONDS)
    states, observed, records = {}, {}, []
    for cfg in indicators:
        iid = cfg["id"]
        data, state = hourly_history(cfg, histories.get(iid), now=now, source_status=health.get(iid))
        states[iid], observed[iid] = state, data
        context = None
        if state["eligible"]:
            context = data["value"].to_numpy(dtype=float)[-cfg.get("context_length", 512):]
            private = Path(cache_dir) / run_id / "contexts" / f"{iid}.json"
            private.parent.mkdir(parents=True, exist_ok=True)
            context_bytes = canonical_bytes({"frequency": "1h", "forecast_basis": "direct_level",
                                            "last_close_ts": state["last_close_ts"],
                                            "context": context.tolist(), "context_hash": sha256(context.tolist())})
            try:
                with private.open("xb") as handle:
                    handle.write(context_bytes)
            except FileExistsError:
                if private.read_bytes() != context_bytes:
                    raise ValueError("hourly_context_cache_conflict")
        for model in entrants:
            rec = {"indicator_id": iid, "entrant_id": model["id"], "status": "skipped", "path": [],
                   "skip_reason": state["reason"] or disabled_reason, "inference_seconds": 0,
                   "seed": derive_seed(iso(now), iid, model["id"], SEED),
                   "entrant_version": model.get("version", model.get("package", "unknown")),
                   "hf_repo": model.get("hf_repo"), "hf_revision": model.get("hf_revision"),
                   "frequency": "1h", "forecast_basis": "direct_level", "horizon_steps": HORIZON,
                   "last_close_ts": state["last_close_ts"], "context_len": len(context) if context is not None else 0,
                   "context_hash": sha256(context.tolist()) if context is not None else None}
            if context is None or not inference_enabled:
                records.append(rec)
                continue
            remaining = (budget_end - parse_ts(clock())).total_seconds()
            if remaining <= 0:
                rec["skip_reason"] = "inference_budget_exhausted"
                records.append(rec)
                continue
            tick = time.monotonic()
            try:
                output = predict(model, context.copy(), seed=rec["seed"], horizon=HORIZON,
                                 interval_seconds=INTERVAL_SECONDS, timeout=min(MODEL_TIMEOUT_S, remaining))
                if not isinstance(output, ForecastPathOutput) or len(output.steps) != HORIZON:
                    raise ValueError("forecast_requires_24_native_steps")
                points = []
                anchor = parse_ts(state["last_close_ts"])
                for step, value in enumerate(output.steps, 1):
                    if set(value.quantiles) != {str(q) for q in QUANTILES}:
                        raise ValueError("incomplete_quantile_grid")
                    if any(number <= 0 for number in value.quantiles.values()):
                        raise ValueError("nonpositive_level_forecast")
                    points.append({"step": step, "close_ts": iso(anchor + timedelta(hours=step)),
                                   "median": value.quantiles["0.5"], "lower": value.quantiles["0.1"],
                                   "upper": value.quantiles["0.9"], "quantiles": value.quantiles,
                                   "quantile_method": value.quantile_method, "n_samples": value.n_samples})
                rec.update(status="ok", skip_reason=None, path=points,
                           completed_ts_utc=iso(parse_ts(clock())))
            except subprocess.TimeoutExpired:
                rec.update(status="failed", skip_reason="model_timeout")
            except Exception as exc:
                rec.update(status="failed", skip_reason=type(exc).__name__)
            rec["inference_seconds"] = time.monotonic() - tick
            records.append(rec)
    completed = parse_ts(clock())
    if completed < started:
        raise ValueError("hourly clock moved backwards")
    for record in records:
        if record["status"] != "ok":
            continue
        # Do not present an already observed time as a newly issued prediction,
        # even if the inference batch crossed an hourly boundary.
        record["path"] = [point for point in record["path"] if parse_ts(point["close_ts"]) > completed]
        record["displayed_horizon_steps"] = len(record["path"])
        if not record["path"]:
            record.update(status="void", skip_reason="forecast_horizon_elapsed")
    by_key = {(row["indicator_id"], row["entrant_id"]): row for row in records}
    rows = []
    for cfg in indicators:
        iid, state, data = cfg["id"], states[cfg["id"]], observed[cfg["id"]]
        fresh = state["eligible"] and parse_ts(state["last_close_ts"]) == hour_floor(completed)
        reason = state["reason"] or (None if fresh else "source_lag")
        points = []
        if data is not None:
            for observation in data.tail(168).itertuples(index=False):
                timestamp = parse_ts(observation.close_ts)
                if timestamp <= completed - timedelta(hours=168):
                    continue
                points.append({"close_ts": iso(timestamp), "session_date": timestamp.astimezone(KST).date().isoformat(),
                               "value": float(observation.value), "origin": "collected_actual", "corrected": False,
                               "fetched_ts_utc": state["fetched_ts_utc"],
                               "published_ts": None if pd.isna(observation.published_ts) else iso(observation.published_ts)})
        latest = points[-1] if points else None
        forecast_rows = []
        for model in entrants:
            rec = by_key[iid, model["id"]]
            path = rec["path"] if fresh and rec["status"] == "ok" else []
            first = path[0] if path else {}
            forecast_rows.append({"id": model["id"], "name": model.get("name", model["id"]), "kind": "tsfm",
                                  "status": rec["status"], "reason": reason or rec["skip_reason"],
                                  "availability": "available" if path else "unavailable", "path": path,
                                  "median": first.get("median"), "lower": first.get("lower"), "upper": first.get("upper"),
                                  "quantiles": first.get("quantiles"), "next_close_ts": first.get("close_ts"),
                                  "unit": cfg.get("unit", "level"), "inference_mode": "zero_shot"})
        available = any(row["path"] for row in forecast_rows)
        targets = [row["next_close_ts"] for row in forecast_rows if row["next_close_ts"]]
        target = min(targets) if targets else None
        rows.append({"id": iid, "name": cfg["name"], "group": cfg.get("group", "crypto"),
                     "enabled": cfg.get("enabled", False), "visible": bool(fresh), "frequency": "1h",
                     "market_status": "open" if fresh else "unavailable", "market_calendar": cfg.get("calendar"),
                     "status": "available" if available else "unavailable", "reason": reason or (
                         None if available else disabled_reason if not inference_enabled else "forecast_unavailable"),
                     "unit": cfg.get("unit", "level"), "unit_label": cfg.get("unit", "level"),
                     "decimals": cfg.get("decimals", 2), "display_policy": cfg.get("display_policy"),
                     "value_kind": "level", "forecast_basis": "direct_level", "public_export": cfg.get("public_export", False),
                     "next_close_ts": target, "next_session_date": parse_ts(target).astimezone(KST).date().isoformat() if target else None,
                     "next_session_timezone": "Asia/Seoul", "last_observation": latest,
                     "forecast_anchor": latest if available else None,
                     "history": {"today": [point for point in points if point["session_date"] == completed.astimezone(KST).date().isoformat()],
                                 "last7days": points}, "entrants": forecast_rows,
                     "collection_ts_utc": state["fetched_ts_utc"],
                     "forecast_generated_ts_utc": iso(completed) if available else None,
                     "attribution": cfg.get("attribution", ""), "source_status": {
                         "status": "ok" if fresh else "unavailable", "freshness": "fresh" if fresh else reason,
                         "source_id": cfg.get("source", {}).get("adapter"), "fetched_ts_utc": state["fetched_ts_utc"],
                         "expected_latest_close_ts": iso(hour_floor(completed)),
                         "next_update_due_ts_utc": state["next_update_due_ts_utc"]}})
    fetches = [state["fetched_ts_utc"] for state in states.values() if state["fetched_ts_utc"]]
    metadata = {"schema_version": "1.0", "mode": "local_zero_shot", "inference_mode": "zero_shot",
                "public_ledger_eligible": False, "frequency": "1h", "interval_seconds": INTERVAL_SECONDS,
                "horizon_steps": HORIZON, "forecast_basis": "direct_level", "interval_basis": "pointwise_marginal",
                "interval_probability": 0.8, "run_id": run_id, "run_date": run_day, "run_ts_utc": iso(now),
                "generated_ts_utc": iso(completed), "collection_ts_utc": max(fetches) if fetches else None,
                "timezone": "Asia/Seoul", "history_calendar_days": 7, "history_basis": "confirmed_hourly_bars"}
    envelope = {**metadata, "inference_enabled": inference_enabled, "completed_ts_utc": iso(completed), "records": records}
    payload = {**metadata, "run_state": "local_zero_shot", "indicators": rows,
               "forecast_generated_ts_utc": iso(completed) if any(row["status"] == "available" for row in rows) else None}
    return json.loads(canonical_bytes(payload)), json.loads(canonical_bytes(envelope))
