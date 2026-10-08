"""Session boundaries, with exchange holidays and timezone-aware closes.

Calendar releases are pinned by the application lockfile. A missing calendar or
out-of-range schedule raises; there is deliberately no weekday-only fallback.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pandas as pd
from dateutil.easter import easter

UTC = timezone.utc


def as_dict(cfg) -> dict:
    return cfg.model_dump() if hasattr(cfg, "model_dump") else dict(cfg)


def as_utc(value) -> datetime:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        raise ValueError("a timezone-aware timestamp is required")
    return ts.tz_convert("UTC").to_pydatetime()


def _local_close(day: date, hhmm: str, tz: str) -> datetime:
    return datetime.combine(day, time.fromisoformat(hhmm), ZoneInfo(tz)).astimezone(UTC)


@lru_cache(maxsize=128)
def _exchange_year(name: str, year: int) -> pd.DataFrame:
    start, end = date(year, 1, 1), date(year, 12, 31)
    calendar = xcals.get_calendar(name, start=start - timedelta(days=7), end=end + timedelta(days=7))
    frame = calendar.schedule.loc[str(start):str(end)]
    # exchange_calendars 4.x names this column 'close'.
    column = "close" if "close" in frame else "market_close"
    return pd.DataFrame({"close": pd.to_datetime(frame[column], utc=True)})


def _exchange_schedule(name: str, start: date, end: date) -> pd.DataFrame:
    frame = pd.concat([_exchange_year(name, year) for year in range(start.year, end.year + 1)])
    return frame.loc[str(start):str(end)]


@lru_cache(maxsize=64)
def _ust_year(year: int) -> pd.DataFrame:
    import pandas_market_calendars as mcal

    frame = mcal.get_calendar("SIFMA_US").schedule(start_date=date(year, 1, 1), end_date=date(year, 12, 31))
    # Treasury's normal observation is approximately 15:30 ET. On shortened
    # sessions the SIFMA market boundary is the conservative target timestamp.
    closes = []
    for day, row in frame.iterrows():
        normal = _local_close(day.date(), "15:30", "America/New_York")
        closes.append(min(normal, as_utc(row["market_close"])))
    return pd.DataFrame({"close": pd.to_datetime(closes, utc=True)}, index=frame.index)


def _ust_schedule(start: date, end: date) -> pd.DataFrame:
    frame = pd.concat([_ust_year(year) for year in range(start.year, end.year + 1)])
    return frame.loc[str(start):str(end)]


def is_target_day(day: date) -> bool:
    if day.weekday() >= 5:
        return False
    holidays = {(1, 1), (5, 1), (12, 25), (12, 26)}
    return (day.month, day.day) not in holidays and day not in {
        easter(day.year) - timedelta(days=2), easter(day.year) + timedelta(days=1)
    }


def session_closes(cfg, start: date, end: date) -> list[datetime]:
    cfg = as_dict(cfg)
    name = cfg["calendar"]
    if end < start:
        return []
    if name == "CRYPTO_UTC23":
        return [_local_close(ts.date(), "23:00", "UTC") for ts in pd.date_range(start, end)]
    if name == "ECB":
        return [_local_close(ts.date(), cfg.get("close_time_local", "16:00"), "Europe/Berlin")
                for ts in pd.date_range(start, end) if is_target_day(ts.date())]
    if name == "UST":
        return [as_utc(ts) for ts in _ust_schedule(start, end)["close"]]
    frame = _exchange_schedule(name, start, end)
    # Preserve real early/late closes. VIX uses the equity calendar plus 15 min.
    offset = timedelta(minutes=int(cfg.get("calendar_close_offset_minutes", 0)))
    return [as_utc(ts) + offset for ts in frame["close"]]


def session_close_on_date(cfg, day: date) -> datetime | None:
    values = session_closes(cfg, day, day)
    return values[0] if values else None


def session_bounds(cfg, run_ts) -> tuple[datetime, datetime]:
    run = as_utc(run_ts)
    # Wide enough for exchange holiday clusters; fail closed if none are found.
    closes = session_closes(cfg, run.date() - timedelta(days=32), run.date() + timedelta(days=32))
    before = [close for close in closes if close < run]
    after = [close for close in closes if close > run]
    if not before or not after:
        raise ValueError("calendar has no session boundary in search interval")
    return before[-1], after[0]
