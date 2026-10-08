"""Fail-closed eligibility checks made at the logical start of a run."""
from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .calendars import as_dict, as_utc, session_bounds, session_closes
from .config import settings


def confirmed_history(history: pd.DataFrame, run_ts) -> pd.DataFrame:
    """Only observations closed and, when known, published before the run.

    Unknown publication times remain unknown. Historical downloads do not turn
    into point-in-time evidence; simulated runs are explicitly shadow-only.
    """
    run = pd.Timestamp(as_utc(run_ts))
    data = history.copy()
    for column in ("close_ts", "value", "published_ts"):
        if column not in data:
            raise ValueError(f"missing source column: {column}")
    # pd.to_datetime(..., utc=True) silently localizes naive values: reject those.
    for value in data["close_ts"]:
        if pd.isna(value) or pd.Timestamp(value).tzinfo is None:
            raise ValueError("invalid or naive close timestamp")
    for value in data["published_ts"].dropna():
        if pd.Timestamp(value).tzinfo is None:
            raise ValueError("naive publication timestamp")
    data["close_ts"] = pd.to_datetime(data["close_ts"], utc=True)
    data["published_ts"] = pd.to_datetime(data["published_ts"], utc=True)
    data["value"] = pd.to_numeric(data["value"], errors="raise")
    if data["close_ts"].duplicated().any() or not data["close_ts"].is_monotonic_increasing:
        raise ValueError("source timestamps must be sorted and unique")
    if not np.isfinite(data["value"].to_numpy(dtype=float)).all():
        raise ValueError("non-finite source value")
    if "is_final" in data and not data["is_final"].eq(True).all():
        raise ValueError("preliminary source observations")
    return data.loc[(data["close_ts"] < run) &
                    (data["published_ts"].isna() | (data["published_ts"] <= run))].copy()


def evaluate_eligibility(cfg, history: pd.DataFrame, run_ts) -> dict:
    cfg = as_dict(cfg)
    run = as_utc(run_ts)
    result = {"eligible": False, "skip_reason": None, "last_close_ts": None, "next_close_ts": None}
    if not cfg.get("enabled", True):
        result["skip_reason"] = "disabled"
        return result
    try:
        previous, following = session_bounds(cfg, run)
        result.update(last_close_ts=previous.isoformat(), next_close_ts=following.isoformat())
    except (ValueError, KeyError, ImportError):
        result["skip_reason"] = "calendar_error"
        return result
    local_run = run.astimezone(ZoneInfo(settings.TZ))
    deadline = datetime.combine(local_run.date(), time.fromisoformat(settings.LOCKIN_DEADLINE_LOCAL),
                                ZoneInfo(settings.TZ))
    if local_run >= deadline:
        result["skip_reason"] = "deadline_missed"
        return result
    if following - run > timedelta(hours=24):
        result["skip_reason"] = "outside_horizon"
        return result
    if run in session_closes(cfg, run.date() - timedelta(days=1), run.date() + timedelta(days=1)):
        # At the exact close instant the strict past/future bounds straddle an
        # intervening session. Do not silently turn a one-session forecast into
        # a two-session change while that just-closed observation is unconfirmed.
        result["skip_reason"] = "source_lag"
        return result
    if history is None:
        result["skip_reason"] = "source_error"
        return result
    try:
        data = confirmed_history(history, run)
    except (ValueError, TypeError, KeyError):
        result["skip_reason"] = "source_invalid"
        return result
    if data.empty or as_utc(data.iloc[-1]["close_ts"]) != previous:
        result["skip_reason"] = "source_lag"
        return result
    if cfg["target_transform"] == "log_return_pct" and (data["value"] <= 0).any():
        result["skip_reason"] = "source_invalid"
        return result
    # min_history refers to model inputs, i.e. changes, requiring N+1 levels.
    if len(data) - 1 < cfg.get("min_history", 300):
        result["skip_reason"] = "insufficient_history"
        return result
    needed = data.tail(settings.CONTEXT_LEN + 1)
    expected = session_closes(cfg, needed.iloc[0]["close_ts"].date(), previous.date())
    expected = [ts for ts in expected if as_utc(needed.iloc[0]["close_ts"]) <= ts <= previous]
    if list(pd.to_datetime(needed["close_ts"], utc=True)) != list(pd.to_datetime(expected, utc=True)):
        result["skip_reason"] = "history_gap"
        return result
    result["eligible"] = True
    return result
