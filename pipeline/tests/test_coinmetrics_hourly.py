"""Free hourly reference-rate parser, pagination, and truthful local accumulation."""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import json
from urllib.parse import parse_qs, urlencode, urlsplit

import pandas as pd
import pytest

from tsfm_live.sources import coinmetrics_hourly as hourly
from tsfm_live.sources import get_source, load_indicators
from tsfm_live.sources.base import BaseSource, SourceError


UTC = timezone.utc
NOW = datetime(2026, 10, 11, 10, 10, tzinfo=UTC)
BOUNDARY = NOW.replace(minute=0)
START = date(2026, 9, 1)


def row(at=BOUNDARY, value="100.125", asset="btc"):
    return {"asset": asset, "time": at.strftime("%Y-%m-%dT%H:%M:%S.000000000Z"),
            "ReferenceRateUSD": value}


def body(rows, **kwargs):
    return json.dumps({"data": rows, **kwargs}).encode()


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def blocked(*args, **kwargs):
        pytest.fail("unit tests must not perform live HTTP requests")
    monkeypatch.setattr(BaseSource, "_get", blocked)
    monkeypatch.setattr(hourly.time, "sleep", lambda _: None)


@pytest.fixture
def cfg():
    return {"id": "btcusd", "enabled": True, "source": {"adapter": "coinmetrics_hourly",
            "params": {"asset": "btc", "metric": "ReferenceRateUSD", "frequency": "1h"}}}


@pytest.fixture
def source(cfg, tmp_path):
    return hourly.CoinMetricsHourlySource(cfg, tmp_path / "private-cache")


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)
    monkeypatch.setattr(hourly, "datetime", FixedDatetime)


def fake_responses(source, monkeypatch, replies, fetched=NOW):
    responses = iter(replies)
    calls = []
    def get(url):
        calls.append(url)
        source.last_fetched_ts = fetched
        reply = next(responses)
        if isinstance(reply, Exception):
            raise reply
        return reply
    monkeypatch.setattr(source, "_get", get)
    return calls


def test_rate_time_is_preserved_not_shifted_to_candle_close(source, cfg):
    frame = source.parse(body([row()]), cfg, START, NOW)
    assert frame["close_ts"].tolist() == [pd.Timestamp(BOUNDARY)]
    assert frame["value"].tolist() == [100.125]
    assert frame["published_ts"].isna().all()
    assert frame.attrs["fetched_ts_utc"] == NOW.isoformat()


def test_ethereum_supported(source, cfg):
    cfg["source"]["params"]["asset"] = "eth"
    assert len(source.parse(body([row(asset="eth")]), cfg, START, NOW)) == 1


@pytest.mark.parametrize("value", [None, True, False, "NaN", "Infinity", "-Infinity", 0, -1, {}, []])
def test_nonpositive_nonfinite_and_invalid_prices_fail(source, cfg, value):
    with pytest.raises(SourceError, match="invalid Community hourly"):
        source.parse(body([row(value=value)]), cfg, START, NOW)


@pytest.mark.parametrize("patch", [
    {"asset": "eth"}, {"time": "2026-10-11T10:00:00.000000001Z"},
    {"time": "2026-10-11T10:01:00Z"}, {"time": "2026-10-11T11:00:00Z"},
    {"time": "2026-10-11T10:00:00"}, {"time": "2026-02-30T10:00:00Z"},
    {"time": None}, {"time": "NaT"},
])
def test_asset_and_timestamp_schema_fail_closed(source, cfg, patch):
    record = row()
    record.update(patch)
    with pytest.raises(SourceError, match="invalid Community hourly"):
        source.parse(body([record]), cfg, START, NOW)


@pytest.mark.parametrize("payload", [b"[]", b"{}", b"broken", b'{"data":{}}', body([None]), body([{}])])
def test_invalid_response_schema(source, cfg, payload):
    with pytest.raises(SourceError, match="invalid Community hourly"):
        source.parse(payload, cfg, START, NOW)


def test_duplicate_timestamps_fail_instead_of_silently_dropping(source, cfg):
    with pytest.raises(SourceError, match="invalid Community hourly"):
        source.parse(body([row(), row(value=101)]), cfg, START, NOW)


def test_rate_cannot_be_observed_before_61_minute_window_finishes(source, cfg):
    with pytest.raises(SourceError, match="invalid Community hourly"):
        source.parse(body([row()]), cfg, START, BOUNDARY + timedelta(seconds=59))


def test_missing_hour_not_interpolated_and_start_date_respected(source, cfg):
    frame = source.parse(body([row(), row(BOUNDARY - timedelta(hours=2))]), cfg, START, NOW)
    assert frame["close_ts"].diff().dropna().tolist() == [timedelta(hours=2)]
    assert source.parse(body([row()]), cfg, date(2026, 10, 12), NOW).empty


def test_free_no_key_request_is_bounded_and_cache_provenance_is_real(source, cfg, monkeypatch):
    calls = fake_responses(source, monkeypatch, [body([row()])])
    frame = source.fetch_history(cfg, START)
    query = parse_qs(urlsplit(calls[0]).query)
    assert query["assets"] == ["btc"]
    assert query["metrics"] == ["ReferenceRateUSD"]
    assert query["frequency"] == ["1h"]
    assert query["page_size"] == ["1000"]
    assert query["end_time"] == ["2026-10-11T10:00:00Z"]
    assert not any("key" in key for key in query)
    assert len(frame) == 1
    assert frame.attrs["fetched_ts_utc"] == NOW.isoformat()
    assert frame.attrs["cache_status"] == "empty"
    cached = json.loads(source.history_path.read_text())
    assert cached["rows"][0]["fetched_ts_utc"] == "2026-10-11T10:10:00Z"
    assert not list(source.history_path.parent.glob("*.tmp"))


def test_accumulates_only_real_points_and_latest_response_revisions_win(source, cfg, monkeypatch):
    fake_responses(source, monkeypatch, [body([row(BOUNDARY - timedelta(hours=2), "90"),
                                             row(BOUNDARY - timedelta(hours=1), "95")])])
    source.fetch_history(cfg, START)
    fake_responses(source, monkeypatch, [body([row(BOUNDARY - timedelta(hours=1), "96"), row()])])
    frame = source.fetch_history(cfg, START)
    assert frame["value"].tolist() == [90, 96, 100.125]
    assert frame.attrs["cache_status"] == "validated"


def test_cache_cannot_mask_missing_hour_within_new_source_response(source, cfg, monkeypatch):
    fake_responses(source, monkeypatch, [body([row(BOUNDARY - timedelta(hours=i)) for i in range(3)])])
    source.fetch_history(cfg, START)
    fake_responses(source, monkeypatch, [body([row(BOUNDARY - timedelta(hours=2)), row()])])
    frame = source.fetch_history(cfg, START)
    assert len(frame) == 2
    assert frame["close_ts"].diff().dropna().tolist() == [timedelta(hours=2)]


def test_cache_cannot_mask_rollback_or_source_lag(source, cfg, monkeypatch):
    fake_responses(source, monkeypatch, [body([row(BOUNDARY - timedelta(hours=1)), row()])])
    source.fetch_history(cfg, START)
    fake_responses(source, monkeypatch, [body([row(BOUNDARY - timedelta(hours=1))])])
    frame = source.fetch_history(cfg, START)
    assert frame["close_ts"].max() == pd.Timestamp(BOUNDARY - timedelta(hours=1))


def test_api_failure_never_falls_back_to_cache(source, cfg, monkeypatch):
    fake_responses(source, monkeypatch, [body([row()])])
    source.fetch_history(cfg, START)
    before = source.history_path.read_bytes()
    fake_responses(source, monkeypatch, [SourceError("source HTTP 429")])
    with pytest.raises(SourceError, match="HTTP 429"):
        source.fetch_history(cfg, START)
    assert source.history_path.read_bytes() == before


def test_empty_response_never_returns_cached_actuals(source, cfg, monkeypatch):
    fake_responses(source, monkeypatch, [body([row()])])
    source.fetch_history(cfg, START)
    before = source.history_path.read_bytes()
    fake_responses(source, monkeypatch, [body([])])
    assert source.fetch_history(cfg, START).empty
    assert source.history_path.read_bytes() == before


@pytest.mark.parametrize("corruption", ["digest", "fingerprint", "schema", "future", "duplicate", "negative"])
def test_invalid_cache_ignored_and_repaired_from_real_response(source, cfg, monkeypatch, corruption):
    fake_responses(source, monkeypatch, [body([row(BOUNDARY - timedelta(hours=1)), row()])])
    source.fetch_history(cfg, START)
    cached = json.loads(source.history_path.read_text())
    if corruption == "digest":
        cached["rows_sha256"] = "0" * 64
    elif corruption == "fingerprint":
        cached["source_fingerprint"] = "different"
    elif corruption == "schema":
        cached["schema_version"] = 2
    elif corruption == "future":
        cached["rows"][0]["fetched_ts_utc"] = "2026-10-12T00:00:00Z"
    elif corruption == "duplicate":
        cached["rows"] = [cached["rows"][0]] * 2
    elif corruption == "negative":
        cached["rows"][0]["value"] = -1
    if corruption != "digest":
        cached["rows_sha256"] = hourly._digest(cached["rows"])
    source.history_path.write_text(json.dumps(cached))
    fake_responses(source, monkeypatch, [body([row()])])
    frame = source.fetch_history(cfg, START)
    assert len(frame) == 1 and frame.attrs["cache_status"] == "invalid_ignored"


def test_history_is_bounded_to_latest_600_real_observations(source, cfg, monkeypatch):
    fake_responses(source, monkeypatch, [body([row(BOUNDARY - timedelta(hours=i)) for i in range(605)])])
    frame = source.fetch_history(cfg, START)
    assert len(frame) == 600
    assert frame["close_ts"].min() == pd.Timestamp(BOUNDARY - timedelta(hours=599))
    assert len(json.loads(source.history_path.read_text())["rows"]) == 600


def next_url(**kwargs):
    return hourly.CoinMetricsHourlySource.endpoint + "?" + urlencode({
        "assets": "btc", "metrics": "ReferenceRateUSD", "frequency": "1h", "next_page_token": "next",
        **kwargs})


def test_same_origin_bounded_pagination_and_duplicate_detection(source, cfg, monkeypatch):
    calls = fake_responses(source, monkeypatch, [body([row(BOUNDARY - timedelta(hours=1))],
                next_page_url=next_url()), body([row()])])
    assert len(source.fetch_history(cfg, START)) == 2
    assert len(calls) == 2
    fake_responses(source, monkeypatch, [body([row()], next_page_url=next_url()), body([row()])])
    with pytest.raises(SourceError, match="duplicate Community"):
        source.fetch_history(cfg, START)


@pytest.mark.parametrize("url", [
    "https://evil.example/", next_url().replace("https:", "http:"),
    next_url().replace("community-api.coinmetrics.io", "user@community-api.coinmetrics.io"),
    next_url().replace("/timeseries/asset-metrics", "/other"),
    next_url(assets="eth"), next_url(metrics="PriceUSD"), next_url(api_key="secret"),
    next_url(frequency="1d"), next_url() + "#fragment", 123,
])
def test_unsafe_pagination_rejected_before_second_request(source, cfg, monkeypatch, url):
    calls = fake_responses(source, monkeypatch, [body([row()], next_page_url=url)])
    with pytest.raises(SourceError, match="pagination URL"):
        source.fetch_history(cfg, START)
    assert len(calls) == 1


def test_pagination_cycle_and_limit_fail(source, cfg, monkeypatch):
    fake_responses(source, monkeypatch, [body([], next_page_url=next_url()),
                                        body([], next_page_url=next_url())])
    with pytest.raises(SourceError, match="did not advance"):
        source.fetch_history(cfg, START)
    fake_responses(source, monkeypatch, [body([], next_page_url=next_url(next_page_token=str(i)))
                                        for i in range(hourly.MAX_PAGES)])
    with pytest.raises(SourceError, match="page limit"):
        source.fetch_history(cfg, START)


def test_changed_unsupported_configuration_is_rejected_before_request(source, cfg):
    changed = deepcopy(cfg)
    changed["source"]["params"]["asset"] = "doge"
    with pytest.raises(SourceError, match="unsupported Community"):
        source.fetch_history(changed, START)


def test_actual_config_only_exports_enabled_free_noncommercial_sources(tmp_path):
    config_path = hourly.__file__.replace("sources\\coinmetrics_hourly.py", "config\\hourly_indicators.yaml")
    config_path = config_path.replace("sources/coinmetrics_hourly.py", "config/hourly_indicators.yaml")
    rows = load_indicators(config_path)
    public = [cfg for cfg in rows if cfg["enabled"]]
    assert {cfg["id"] for cfg in public} == {"btcusd", "ethusd"}
    for cfg in public:
        assert isinstance(get_source(cfg, tmp_path / cfg["id"]), hourly.CoinMetricsHourlySource)
        assert cfg["public_export"] and cfg["min_history"] == 128
        assert cfg["context_length"] == 512 and cfg["license_id"] == "CC-BY-NC-4.0"
        assert cfg["observation_kind"] == "reference_rate"
    assert all(not cfg["public_export"] for cfg in rows if not cfg["enabled"])
