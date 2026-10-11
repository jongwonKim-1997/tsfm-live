import json
from datetime import datetime, timezone
from io import BytesIO
from urllib.error import HTTPError, URLError

import pytest

from tsfm_live import source_probe as probe

NOW = datetime(2026, 10, 11, 6, tzinfo=timezone.utc)
ECB = b'''<Envelope><Cube><Cube time="2026-10-09">
<Cube currency="USD" rate="1.12"/><Cube currency="JPY" rate="170"/>
<Cube currency="GBP" rate="0.8"/><Cube currency="AUD" rate="1.6"/>
<Cube currency="CAD" rate="1.5"/><Cube currency="CHF" rate="0.9"/>
<Cube currency="KRW" rate="1500"/></Cube></Cube></Envelope>'''
TREASURY = b'''<feed><entry><content><properties><NEW_DATE>2026-10-09T00:00:00</NEW_DATE>
<BC_2YEAR>3.2</BC_2YEAR><BC_5YEAR>3.5</BC_5YEAR><BC_10YEAR>4.1</BC_10YEAR>
<BC_30YEAR>4.7</BC_30YEAR></properties></content></entry></feed>'''


def fake_feeds(url):
    if "ecb.europa.eu" in url:
        return ECB
    return TREASURY if "2026" in url else b"<feed/>"


def test_offline_is_private_metadata_only_and_never_enables(tmp_path, monkeypatch):
    monkeypatch.setattr(probe, "_download", lambda _: pytest.fail("offline must not request"))
    monkeypatch.setenv("ECOS_API_KEY", "secret-to-never-serialize")
    first = probe.run_probe(tmp_path, now=NOW)
    second = probe.run_probe(tmp_path, now=NOW)
    assert first["report_path"] != second["report_path"]
    assert not first["network_performed"] and not first["auto_enabled"]
    assert len(first["indicators"]) == 14 and len(first["candidates"]) == 8
    assert sum(row["enabled"] for row in first["indicators"]) == 3
    assert all(not row["enabled"] for row in first["candidates"])
    assert first["endpoints"] == []
    assert "secret-to-never-serialize" not in (tmp_path / "latest.json").read_text()
    assert json.loads((tmp_path / "latest.json").read_text())["report_path"] == second["report_path"]
    assert all(row["collection_status"] == "not_checked" for row in first["indicators"] if row["enabled"])
    assert next(row for row in first["indicators"] if row["id"] == "kospi")["required_credentials"][0]["present"]


def test_approved_feeds_shared_and_holiday_aware(tmp_path, monkeypatch):
    calls = []
    def download(url):
        calls.append(url)
        return fake_feeds(url)
    monkeypatch.setattr(probe, "_download", download)
    report = probe.run_probe(tmp_path, network=True, now=NOW)
    assert len(calls) == 3  # one ECB + previous/current Treasury years
    assert all(row["status"] == "ok" and len(row["body_sha256"]) == 64 for row in report["endpoints"])
    active = {row["id"]: row for row in report["indicators"] if row["enabled"]}
    assert {row["collection_status"] for row in active.values()} == {"fresh"}
    assert active["eurusd"]["next_close_ts"] == "2026-10-12T14:00:00Z"
    assert active["ust10y"]["next_close_ts"] == "2026-10-13T19:30:00Z"  # Columbus Day
    assert all(not row["minimum_301_levels_present"] for row in active.values())
    assert all(row["missing_sessions_in_checked_span"] == 0 for row in active.values())
    krw = next(row for row in report["candidates"] if row["id"] == "usdkrw_ecb")
    assert krw["collection_status"] == "fresh" and krw["exact_existing_target"] is False
    assert "Seoul-close" in krw["blockers"][-1]
    assert all(row["collection_status"] == "blocked_not_requested" for row in report["indicators"] if not row["enabled"])
    assert all(not row["publication_timestamp_available"] for row in active.values())
    assert "1500" not in (tmp_path / "latest.json").read_text()
    assert not list(tmp_path.rglob("*.response"))


def test_stale_and_invalid_payloads_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(probe, "_download", lambda url: ECB.replace(b"2026-10-09", b"2026-10-08") if "ecb" in url else b"<broken")
    report = probe.run_probe(tmp_path, network=True, now=NOW)
    active = {row["id"]: row for row in report["indicators"] if row["enabled"]}
    assert active["eurusd"]["collection_status"] == "lagging"
    assert active["ust10y"]["collection_status"] == "source_error"
    assert report["endpoints"][-1]["status"] == "invalid_payload"


def test_missing_latest_currency_does_not_reuse_other_dates(tmp_path, monkeypatch):
    monkeypatch.setattr(probe, "_download", lambda url: ECB.replace(b'currency="KRW"', b'currency="OTHER"') if "ecb" in url else fake_feeds(url))
    report = probe.run_probe(tmp_path, network=True, now=NOW)
    assert next(row for row in report["candidates"] if row["id"] == "usdkrw_ecb")["collection_status"] == "no_observations"


def test_source_errors_do_not_leak_raw_exception_urls(tmp_path, monkeypatch):
    monkeypatch.setattr(probe, "_download", lambda _: (_ for _ in ()).throw(RuntimeError("https://private/key-secret")))
    report = probe.run_probe(tmp_path, network=True, now=NOW)
    assert "key-secret" not in json.dumps(report)
    assert all(row["collection_status"] == "source_error" for row in report["indicators"] if row["enabled"])


def test_exact_close_is_not_yet_a_confirmed_observation():
    dates = probe._ecb_dates(ECB, datetime(2026, 10, 9, 14, tzinfo=timezone.utc))
    assert not dates["eurusd"]
    assert probe._ecb_dates(ECB, datetime(2026, 10, 9, 14, 0, 1, tzinfo=timezone.utc))["eurusd"]


def test_duplicate_ecb_dates_rejected():
    with pytest.raises(Exception, match="duplicate"):
        probe._ecb_dates(ECB.replace(b"</Cube></Envelope>", ECB.split(b"<Envelope><Cube>")[1]), NOW)


def test_repository_output_rejected_even_when_offline(monkeypatch, tmp_path):
    with pytest.raises(ValueError, match="outside"):
        probe.run_probe(probe.REPO_ROOT / "work" / "probe", now=NOW)
    monkeypatch.setenv("TSFM_REPO_ROOT", str(tmp_path))
    with pytest.raises(ValueError, match="outside"):
        probe.run_probe(tmp_path / "probe", now=NOW)


def test_http_bounded_retries_and_permanent_failure(monkeypatch):
    attempts, waits = [], []
    def transient(*args, **kwargs):
        attempts.append(kwargs["timeout"])
        if len(attempts) == 1:
            raise URLError("secret")
        return BytesIO(ECB)
    monkeypatch.setattr(probe, "urlopen", transient)
    monkeypatch.setattr(probe.time, "sleep", waits.append)
    assert probe._download(probe.ECBSource.endpoint) == ECB
    assert attempts == [12, 12] and waits == [0.5]
    def permanent(*args, **kwargs):
        raise HTTPError("secret", 403, "private", None, None)
    monkeypatch.setattr(probe, "urlopen", permanent)
    with pytest.raises(probe.SourceError, match="http_403"):
        probe._download(probe.ECBSource.endpoint)
    assert waits == [0.5]
