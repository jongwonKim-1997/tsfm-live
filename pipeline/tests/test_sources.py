import json
from datetime import date, datetime, timezone
from io import BytesIO
from urllib.error import HTTPError, URLError

import pytest

from tsfm_live.sources import get_source, load_indicators
from tsfm_live.sources.base import BaseSource, REPO_ROOT, SourceError
from tsfm_live.sources.binance import BinanceSource
from tsfm_live.sources.ecb import ECBSource
from tsfm_live.sources.ecos import ECOSSource
from tsfm_live.sources.ustreasury import USTreasurySource


def cfg(indicator):
    return next(c for c in load_indicators() if c["id"] == indicator)


ECB_XML = b'''<gesmes:Envelope xmlns:gesmes="urn:gesmes" xmlns="urn:ecb"><Cube>
<Cube time="2026-10-07"><Cube currency="USD" rate="1.25"/><Cube currency="JPY" rate="150"/></Cube>
<Cube time="2026-10-06"><Cube currency="USD" rate="1.20"/><Cube currency="JPY" rate="144"/></Cube>
</Cube></gesmes:Envelope>'''
UST_XML = b'''<feed xmlns="http://www.w3.org/2005/Atom" xmlns:m="urn:metadata" xmlns:d="urn:data">
<entry><content><m:properties><d:NEW_DATE>2026-11-27T00:00:00</d:NEW_DATE><d:BC_10YEAR>4.25</d:BC_10YEAR></m:properties></content></entry>
<entry><content><m:properties><d:NEW_DATE>2026-11-25T00:00:00</d:NEW_DATE><d:BC_10YEAR m:null="true" /></m:properties></content></entry></feed>'''


def test_all_14_configured_and_unverified_disabled(tmp_path):
    configs = load_indicators()
    assert len(configs) == 14
    assert {c["id"] for c in configs if c["enabled"]} == {"eurusd", "usdjpy", "ust10y"}
    for c in configs:
        if not c["enabled"]:
            assert c["disabled_reason"]
            with pytest.raises(SourceError, match="disabled"):
                get_source(c, tmp_path)
    assert "USDT" in cfg("btcusd")["name"]


def test_ecb_reference_and_derived_cross(tmp_path):
    source = ECBSource(cfg("eurusd"), tmp_path)
    frame = source.parse(ECB_XML, cfg("eurusd"), date(2026, 10, 1))
    assert frame["value"].tolist() == [1.20, 1.25]
    assert frame.iloc[-1].close_ts.isoformat() == "2026-10-07T14:00:00+00:00"
    assert frame["published_ts"].isna().all()
    cross = source.parse(ECB_XML, cfg("usdjpy"), date(2026, 10, 1))
    assert cross["value"].tolist() == [120, 120]
    with pytest.raises(SourceError):
        source.parse(ECB_XML.replace(b'currency="USD"', b'currency="CHF"'), cfg("eurusd"), date(2026, 10, 1))


def test_treasury_namespaces_missing_values_and_early_boundary(tmp_path):
    source = USTreasurySource(cfg("ust10y"), tmp_path)
    frame = source.parse(UST_XML, cfg("ust10y"), date(2026, 1, 1))
    assert len(frame) == 1 and frame.iloc[0].value == 4.25
    assert frame.iloc[0].close_ts.isoformat() == "2026-11-27T19:00:00+00:00"
    assert frame["published_ts"].isna().all()
    with pytest.raises(SourceError):
        source.parse(UST_XML.replace(b"BC_10YEAR", b"BC_30YEAR"), cfg("ust10y"), date(2026, 1, 1))


def bar(day, hour, value=100):
    opening = datetime.fromisoformat(day).replace(hour=hour, tzinfo=timezone.utc)
    ms = int(opening.timestamp() * 1000)
    return [ms, "1", "2", "1", str(value), "0", ms + 3_600_000 - 1, "0", 1, "0", "0", "0"]


def test_binance_22_hour_not_23_hour_and_no_unclosed_candles(tmp_path):
    source = BinanceSource(cfg("btcusd"), tmp_path)
    body = json.dumps([bar("2026-10-06", 21, 90), bar("2026-10-06", 22, 100),
                       bar("2026-10-06", 23, 900), bar("2026-10-07", 22, 999)]).encode()
    frame = source.parse(body, cfg("btcusd"), date(2026, 10, 6),
                         datetime.fromisoformat("2026-10-07T22:59:59+00:00"))
    assert frame["value"].tolist() == [100]
    assert frame.iloc[0].close_ts.isoformat() == "2026-10-06T23:00:00+00:00"
    exact = source.parse(json.dumps([bar("2026-10-07", 22)]).encode(), cfg("btcusd"), date(2026, 10, 7),
                         datetime.fromisoformat("2026-10-07T23:00:00+00:00"))
    assert len(exact) == 1
    broken = bar("2026-10-06", 22)
    broken[6] += 1
    with pytest.raises(SourceError, match="boundary"):
        source.parse(json.dumps([broken]).encode(), cfg("btcusd"), date(2026, 10, 6))


def test_ecos_no_key_and_metadata_mismatch(tmp_path, monkeypatch):
    monkeypatch.delenv("ECOS_API_KEY", raising=False)
    source = ECOSSource(cfg("kospi"), tmp_path)
    with pytest.raises(SourceError, match="ECOS_API_KEY"):
        source.fetch_history(cfg("kospi"), date(2026, 1, 1))
    row = {"TIME": "20261007", "DATA_VALUE": "1", "STAT_CODE": "wrong", "ITEM_CODE1": "wrong"}
    with pytest.raises(SourceError, match="identity"):
        source.parse(json.dumps({"StatisticSearch": {"row": [row]}}).encode(), cfg("kospi"), date(2026, 1, 1))


def test_raw_cache_external_and_fingerprint_stable(tmp_path):
    with pytest.raises(ValueError, match="outside"):
        ECBSource(cfg("eurusd"), REPO_ROOT / "data")
    first = ECBSource(cfg("eurusd"), tmp_path)
    second = ECBSource(cfg("eurusd"), tmp_path)
    assert first.fingerprint() == second.fingerprint()
    assert first.fingerprint() != ECBSource(cfg("usdjpy"), tmp_path).fingerprint()


def test_http_retries_raw_evidence_and_secret_redaction(tmp_path, monkeypatch):
    import tsfm_live.sources.base as base

    attempts, waits = [], []
    def fake_open(request, **kwargs):
        attempts.append(request.full_url)
        if len(attempts) < 4:
            raise URLError("private URL must not appear in manifest")
        return BytesIO(b"confirmed-data")
    monkeypatch.setattr(base, "urlopen", fake_open)
    monkeypatch.setattr(base.clock, "sleep", waits.append)
    source = BaseSource({"id": "fixture", "source": {"params": {}}}, tmp_path)
    body = source._get("https://example.test/secret", public_url="https://example.test/REDACTED")
    assert body == b"confirmed-data" and waits == [2, 8, 30]
    assert len(attempts) == 4
    evidence = list(tmp_path.rglob("*.json"))
    assert len(evidence) == 1 and "secret" not in evidence[0].read_text()
    assert source.raw_evidence[0]["body_sha256"]


def test_permanent_http_failure_does_not_retry(tmp_path, monkeypatch):
    import tsfm_live.sources.base as base

    def forbidden(request, **kwargs):
        raise HTTPError("https://private.test/secret", 403, "forbidden", None, None)
    monkeypatch.setattr(base, "urlopen", forbidden)
    monkeypatch.setattr(base.clock, "sleep", lambda _: pytest.fail("must not retry 403"))
    source = BaseSource({"id": "fixture", "source": {"params": {}}}, tmp_path)
    with pytest.raises(SourceError, match="HTTP 403") as err:
        source._get("https://private.test/secret")
    assert "secret" not in str(err.value)
