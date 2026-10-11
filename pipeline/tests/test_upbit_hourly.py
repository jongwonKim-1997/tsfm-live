"""Hourly candle integrity and pagination, without live provider requests."""
import json
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

import pandas as pd
import pytest

from tsfm_live.sources import upbit_hourly as hourly
from tsfm_live.sources.base import BaseSource, SourceError


UTC = timezone.utc
NOW = datetime(2026, 10, 11, 10, 5, tzinfo=UTC)
BOUNDARY = NOW.replace(minute=0)
START = date(2026, 9, 1)


def candle(opening, *, market="KRW-BTC", price=100.0):
    return {
        "market": market,
        "unit": 60,
        "candle_date_time_utc": opening.strftime("%Y-%m-%dT%H:%M:%S"),
        "trade_price": price,
        "timestamp": int((opening + timedelta(minutes=59)).timestamp() * 1000),
    }


def body(rows):
    return json.dumps(rows).encode()


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def blocked(*args, **kwargs):
        pytest.fail("hourly unit tests must not perform live API requests")

    monkeypatch.setattr(BaseSource, "_get", blocked)


@pytest.fixture
def cfg():
    return {"id": "btc_krw_hourly", "source": {"params": {"market": "KRW-BTC"}}}


@pytest.fixture
def source(cfg, tmp_path):
    return hourly.UpbitHourlySource(cfg, tmp_path / "private-cache")


@pytest.fixture
def clock(monkeypatch):
    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz) if tz is not None else NOW.replace(tzinfo=None)

    monkeypatch.setattr(hourly, "datetime", FixedDatetime)
    sleeps = []
    monkeypatch.setattr(hourly.time, "sleep", sleeps.append)
    return sleeps


def test_candle_close_is_interval_end_not_last_tick(source, cfg):
    opening = BOUNDARY - timedelta(hours=1)
    frame = source.parse(body([candle(opening)]), cfg, START, NOW)
    assert frame["close_ts"].tolist() == [pd.Timestamp(BOUNDARY)]
    assert frame["value"].tolist() == [100.0]
    assert frame["published_ts"].isna().all()
    assert frame.attrs["fetched_ts_utc"] == NOW.isoformat()


def test_post_boundary_storage_timestamp_does_not_shift_candle_close(source, cfg):
    row = candle(BOUNDARY - timedelta(hours=1))
    row["timestamp"] = int(BOUNDARY.timestamp() * 1000) + 25
    frame = source.parse(body([row]), cfg, START, NOW)
    assert frame["close_ts"].tolist() == [pd.Timestamp(BOUNDARY)]


def test_unfinished_candle_excluded_even_when_last_tick_already_arrived(source, cfg):
    current = candle(BOUNDARY)
    current["timestamp"] = int((BOUNDARY + timedelta(minutes=1)).timestamp() * 1000)
    completed = candle(BOUNDARY - timedelta(hours=1))
    frame = source.parse(body([current, completed]), cfg, START, NOW)
    assert frame["close_ts"].tolist() == [pd.Timestamp(BOUNDARY)]


def test_exact_interval_end_is_eligible(source, cfg):
    frame = source.parse(body([candle(BOUNDARY - timedelta(hours=1))]), cfg, START, BOUNDARY)
    assert len(frame) == 1


def test_implicit_fetch_time_uses_actual_clock(source, cfg, clock):
    frame = source.parse(body([candle(BOUNDARY - timedelta(hours=1))]), cfg, START)
    assert frame.attrs["fetched_ts_utc"] == NOW.isoformat()


@pytest.mark.parametrize("patch", [
    {"market": "KRW-ETH"},
    {"unit": 30},
    {"candle_date_time_utc": "2026-10-11T09:01:00"},
    {"candle_date_time_utc": "not-a-time"},
    {"timestamp": int((BOUNDARY - timedelta(hours=1, seconds=1)).timestamp() * 1000)},
    {"timestamp": int(NOW.timestamp() * 1000) + 1},
    {"timestamp": "not-a-timestamp"},
])
def test_invalid_candle_identity_or_time_rejected(source, cfg, patch):
    row = candle(BOUNDARY - timedelta(hours=1))
    row.update(patch)
    with pytest.raises(SourceError, match="invalid hourly candle response"):
        source.parse(body([row]), cfg, START, NOW)


@pytest.mark.parametrize("value", [0, -1, "NaN", "Infinity", "-Infinity", None])
def test_invalid_prices_rejected(source, cfg, value):
    with pytest.raises(SourceError, match="invalid hourly candle response"):
        source.parse(body([candle(BOUNDARY - timedelta(hours=1), price=value)]), cfg, START, NOW)


@pytest.mark.parametrize("payload", [b"broken-json", b"{}", b"[{}]", b"[null]"])
def test_invalid_payload_rejected(source, cfg, payload):
    with pytest.raises(SourceError, match="invalid hourly candle response"):
        source.parse(payload, cfg, START, NOW)


def test_duplicate_completed_candles_rejected(source, cfg):
    row = candle(BOUNDARY - timedelta(hours=1))
    with pytest.raises(SourceError, match="duplicate"):
        source.parse(body([row, deepcopy(row)]), cfg, START, NOW)


def test_missing_hour_is_not_filled_and_rows_are_sorted(source, cfg):
    rows = [candle(BOUNDARY - timedelta(hours=1), price=110),
            candle(BOUNDARY - timedelta(hours=3), price=90)]
    frame = source.parse(body(rows), cfg, START, NOW)
    assert frame["close_ts"].tolist() == [pd.Timestamp(BOUNDARY - timedelta(hours=2)),
                                        pd.Timestamp(BOUNDARY)]
    assert frame["value"].tolist() == [90, 110]


def test_requested_start_date_filters_older_openings(source, cfg):
    rows = [candle(datetime(2026, 10, 10, 23, tzinfo=UTC)),
            candle(datetime(2026, 10, 11, 0, tzinfo=UTC))]
    frame = source.parse(body(rows), cfg, date(2026, 10, 11), NOW)
    assert frame["close_ts"].tolist() == [pd.Timestamp("2026-10-11T01:00:00Z")]


def test_fetch_uses_three_exclusive_pages_and_preserves_600_unique_hours(source, cfg, clock, monkeypatch):
    calls = []

    def fake_get(url):
        parsed = urlsplit(url)
        query = parse_qs(parsed.query)
        assert parsed.scheme == "https" and parsed.netloc == "api.upbit.com"
        assert parsed.path == "/v1/candles/minutes/60"
        assert query["market"] == ["KRW-BTC"] and query["count"] == ["200"]
        cursor = datetime.fromisoformat(query["to"][0])
        calls.append(cursor)
        source.last_fetched_ts = NOW + timedelta(seconds=len(calls))
        return body([candle(cursor - timedelta(hours=i + 1), price=100 + i)
                     for i in range(200)])

    monkeypatch.setattr(source, "_get", fake_get)
    frame = source.fetch_history(cfg, START)
    assert calls == [BOUNDARY - timedelta(hours=200 * i) for i in range(3)]
    assert clock == [0.15, 0.15]
    assert len(frame) == 600 and frame["close_ts"].is_unique
    assert frame["close_ts"].iloc[-1] == pd.Timestamp(BOUNDARY)
    assert frame["close_ts"].iloc[0] == pd.Timestamp(BOUNDARY - timedelta(hours=599))
    assert frame["close_ts"].diff().dropna().eq(timedelta(hours=1)).all()


def test_fetch_freezes_cutoff_when_collection_crosses_hour(source, cfg, clock, monkeypatch):
    replies = iter([
        body([candle(BOUNDARY), candle(BOUNDARY - timedelta(hours=1))]),
        body([]),
    ])

    def fake_get(url):
        source.last_fetched_ts = NOW + timedelta(hours=1)
        return next(replies)

    monkeypatch.setattr(source, "_get", fake_get)
    frame = source.fetch_history(cfg, START)
    assert frame["close_ts"].tolist() == [pd.Timestamp(BOUNDARY)]


def test_fetch_stops_on_empty_page(source, cfg, clock, monkeypatch):
    calls = []

    def fake_get(url):
        calls.append(url)
        source.last_fetched_ts = NOW
        return body([])

    monkeypatch.setattr(source, "_get", fake_get)
    assert source.fetch_history(cfg, START).empty
    assert len(calls) == 1 and clock == []


def test_fetch_rejects_nonadvancing_cursor(source, cfg, clock, monkeypatch):
    def fake_get(url):
        source.last_fetched_ts = NOW + timedelta(hours=1)
        return body([candle(BOUNDARY)])

    monkeypatch.setattr(source, "_get", fake_get)
    with pytest.raises(SourceError, match="pagination did not advance"):
        source.fetch_history(cfg, START)


def test_fetch_rejects_duplicates_across_pages(source, cfg, clock, monkeypatch):
    recent = candle(BOUNDARY - timedelta(hours=1))
    replies = iter([body([recent]),
                    body([recent, candle(BOUNDARY - timedelta(hours=2))]),
                    body([])])

    def fake_get(url):
        source.last_fetched_ts = NOW
        return next(replies)

    monkeypatch.setattr(source, "_get", fake_get)
    with pytest.raises(SourceError, match="duplicate"):
        source.fetch_history(cfg, START)


def test_fetch_rejects_unsupported_market_before_request(source, cfg, clock):
    cfg["source"]["params"]["market"] = "KRW-XRP"
    with pytest.raises(SourceError, match="unsupported hourly market"):
        source.fetch_history(cfg, START)


def test_eth_market_is_accepted(source, cfg):
    cfg["source"]["params"]["market"] = "KRW-ETH"
    frame = source.parse(body([candle(BOUNDARY - timedelta(hours=1), market="KRW-ETH")]), cfg, START, NOW)
    assert len(frame) == 1
