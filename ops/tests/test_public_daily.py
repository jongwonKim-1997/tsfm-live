import copy
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest
from tsfm_live.calendars import session_closes
from tsfm_live.daily_public import (
    build_daily,
    indicator_configs,
    public_models,
    read_issues,
)
from tsfm_live.ledger import parse_ts
from tsfm_live.models import load_models
from tsfm_live.models.base import ForecastOutput, ForecastPathOutput
from tsfm_live.sources.ecb import ECBSource
from tsfm_live.sources.twse_open import TWSEOpenSource
from tsfm_live.sources.base import SourceError

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))
from daily_local import atomic_json  # noqa: E402
from publish_daily import publish_daily, validate  # noqa: E402


def frame(cfg, now):
    closes = [t for t in session_closes(cfg, date(2025, 1, 1), now.date()) if t < now]
    data = pd.DataFrame(
        {
            "close_ts": pd.to_datetime(closes, utc=True),
            "value": [1.0 + i / 10000 for i in range(len(closes))],
            "published_ts": pd.NaT,
        }
    )
    data.attrs["fetched_ts_utc"] = now.isoformat()
    return data


def fake_predict(config, context, *, horizon, **kwargs):
    assert context.ndim == 1
    assert config["device"] == "cuda"
    values = [
        ForecastOutput(
            {
                "0.1": float(context[-1] - 0.01),
                "0.5": float(context[-1] + i * 0.001),
                "0.9": float(context[-1] + 0.02),
            },
            None,
            "native",
            None,
        )
        for i in range(horizon)
    ]
    return values[0] if horizon == 1 else ForecastPathOutput(values)


def build(tmp_path, now, predict=fake_predict, histories=None, **kwargs):
    configs = indicator_configs()
    histories = (
        histories
        if histories is not None
        else {c["id"]: frame(c, now) for c in configs}
    )
    return build_daily(
        configs,
        public_models(load_models()),
        histories,
        tmp_path,
        now=now,
        clock=lambda: now,
        predict=predict,
        save=atomic_json,
        **kwargs,
    )


def test_freezes_once_without_recomputing_after_actual_changes(tmp_path):
    now = parse_ts("2026-10-19T00:00:00Z")
    first, errors = build(tmp_path, now)
    assert not errors
    before = {p: p.read_bytes() for p in tmp_path.glob("issued/*/*.json")}

    def forbidden(*a, **kw):
        pytest.fail("immutable daily forecast was recomputed")

    second, errors = build(tmp_path, now + timedelta(hours=1), predict=forbidden)
    assert not errors
    assert first["indicators"][0]["forecasts"] == second["indicators"][0]["forecasts"]
    assert before == {p: p.read_bytes() for p in before}


def test_hourly_issue_freezes_each_hour_and_preserves_daily_comparison(tmp_path):
    now = parse_ts("2026-10-18T09:10:00Z")
    daily, _ = build(tmp_path, now)
    before = {p: p.read_bytes() for p in tmp_path.glob("issued/*/*.json")}
    first, errors = build(tmp_path, now + timedelta(hours=1), issue_hourly=True)
    assert not errors and first["issue_frequency"] == "1h"
    assert first["frequency"] == "1d"
    hourly_before = {p: p.read_bytes() for p in tmp_path.glob("issued-hourly/*/*.json")}
    assert len(hourly_before) == 12

    def forbidden(*a, **kw):
        pytest.fail("same-hour issue was recomputed")

    again, errors = build(
        tmp_path,
        now + timedelta(hours=1, minutes=10),
        issue_hourly=True,
        predict=forbidden,
    )
    assert (
        not errors
        and again["indicators"][0]["forecasts"] == first["indicators"][0]["forecasts"]
    )
    second, errors = build(tmp_path, now + timedelta(hours=2), issue_hourly=True)
    assert not errors and len(list(tmp_path.glob("issued-hourly/*/*.json"))) == 24
    assert second["indicators"][0]["forecasts"][0]["issue_slot"] == "2026-10-18T20"
    assert before == {p: p.read_bytes() for p in before}
    assert hourly_before == {p: p.read_bytes() for p in hourly_before}
    tomorrow, errors = build(tmp_path, now + timedelta(days=1), issue_hourly=True)
    assert not errors
    assert (
        tomorrow["indicators"][0]["previous_forecasts"]
        == daily["indicators"][0]["forecasts"]
    )


def test_hourly_issue_cannot_be_backdated_across_hour_boundary(tmp_path):
    now = parse_ts("2026-10-18T09:59:59Z")
    configs = indicator_configs()[:1]
    view, errors = build_daily(
        configs,
        public_models(load_models()),
        {configs[0]["id"]: frame(configs[0], now)},
        tmp_path,
        now=now,
        clock=lambda: now + timedelta(seconds=2),
        predict=fake_predict,
        save=atomic_json,
        issue_hourly=True,
    )
    assert errors and not view["indicators"][0]["forecasts"]
    assert not list(tmp_path.glob("issued-hourly/*/*.json"))


def test_yesterday_matches_target_date_and_real_actual(tmp_path):
    first = parse_ts("2026-10-19T00:00:00Z")
    build(tmp_path, first)
    view, _errors = build(tmp_path / "separate", parse_ts("2026-10-20T16:30:00Z"))
    # KST is already October 21: do not call October 19 "yesterday".
    assert view["date"] == "2026-10-21"
    assert not view["indicators"][0]["previous_forecasts"]
    view, _errors = build(tmp_path, parse_ts("2026-10-20T14:30:00Z"))
    row = view["indicators"][0]
    assert row["today_actual"]["date"] == "2026-10-20"
    assert row["previous_forecasts"][0]["issue_date"] == "2026-10-19"
    assert row["previous_forecasts"][0]["points"][-1]["date"] == "2026-10-20"


def test_weekend_no_fake_actual_and_next_session(tmp_path):
    view, errors = build(tmp_path, parse_ts("2026-10-18T09:00:00Z"))
    assert not errors
    for row in view["indicators"]:
        assert row["actual_status"] == "market_closed"
        assert row["today_actual"] is None
        assert row["forecasts"][0]["points"][-1]["date"] == "2026-10-19"


def test_missing_latest_source_prevents_new_forecast(tmp_path):
    now = parse_ts("2026-10-19T14:30:00Z")
    histories = {c["id"]: frame(c, now).iloc[:-2].copy() for c in indicator_configs()}
    view, errors = build(tmp_path, now, histories=histories)
    assert errors
    assert all(not r["forecasts"] for r in view["indicators"])


def test_archive_tampering_fails_closed(tmp_path):
    now = parse_ts("2026-10-18T09:00:00Z")
    build(tmp_path, now)
    path = next(tmp_path.glob("issued/*/*.json"))
    item = json.loads(path.read_bytes())
    item["forecast"]["points"][0]["median"] += 1
    path.write_text(json.dumps(item))
    with pytest.raises(ValueError, match="integrity"):
        read_issues(tmp_path, now)


def test_public_gate_rejects_nc_and_secret_and_unapproved_model(tmp_path):
    view, _ = build(tmp_path, parse_ts("2026-10-18T09:00:00Z"))
    validate(view)
    for mutation in ("license", "secret", "model"):
        invalid = copy.deepcopy(view)
        if mutation == "license":
            invalid["indicators"][0]["license_id"] = "CC-BY-NC-4.0"
        elif mutation == "secret":
            invalid["indicators"][0]["api_token"] = "test"
        else:
            invalid["indicators"][0]["forecasts"][0]["model_id"] = "moirai"
        with pytest.raises(ValueError):
            validate(invalid)


def test_ecb_krw_cross_uses_same_dated_cube(tmp_path):
    cfg = indicator_configs()[2]
    source = ECBSource(cfg, tmp_path)
    body = b'<root><Cube time="2026-10-16"><Cube currency="USD" rate="1.2"/><Cube currency="KRW" rate="1800"/></Cube></root>'
    data = source.parse(body, cfg, date(2026, 10, 16), parse_ts("2026-10-18T00:00:00Z"))
    assert data.iloc[0]["value"] == 1500


def test_twse_open_dataset_roc_date_daily_close_and_schema(tmp_path):
    cfg = next(c for c in indicator_configs() if c["id"] == "taiex")
    assert not session_closes(cfg, date(2024, 10, 31), date(2024, 10, 31))
    assert not session_closes(cfg, date(2026, 7, 10), date(2026, 7, 10))
    source = TWSEOpenSource(cfg, tmp_path)
    header = "日期,開盤指數,最高指數,最低指數,收盤指數\r\n"
    body = (
        header + '"1151016","46995.03","47520.60","46995.03","47111.26"\r\n'
    ).encode("utf-8-sig")
    frame = source.parse(body, cfg, date(2026, 10, 1), parse_ts("2026-10-18T00:00:00Z"))
    assert frame.iloc[0].value == 47111.26
    assert frame.iloc[0].close_ts == pd.Timestamp("2026-10-16T05:30:00Z")
    assert source.parse(
        header.encode(), cfg, date(2026, 11, 1), parse_ts("2026-11-01T00:00:00Z")
    ).empty
    assert source.parse(
        body, cfg, date(2026, 10, 1), parse_ts("2026-10-16T05:00:00Z")
    ).empty
    with pytest.raises(SourceError, match="schema"):
        source.parse(b"<html>error</html>", cfg, date(2026, 10, 1))
    with pytest.raises(SourceError, match="calendar"):
        source.parse(body.replace(b"1151016", b"1151018"), cfg, date(2026, 10, 1))


def test_uploaded_is_not_published_without_matching_readback(tmp_path):
    view, _ = build(tmp_path / "state", parse_ts("2026-10-18T09:00:00Z"))
    env = tmp_path / "publish.env"
    env.write_text(
        "CLOUDFLARE_ACCOUNT_ID="
        + "a" * 32
        + "\nCLOUDFLARE_KV_NAMESPACE_ID="
        + "b" * 32
        + "\nCLOUDFLARE_API_TOKEN=test-token"
    )

    class Response:
        status = 200

        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def read(self, n):
            return self.body

    def opener(request, timeout):
        if request.get_method() == "PUT":
            return Response(b'{"success":true}')
        assert not request.has_header("Authorization")
        assert request.get_header("User-agent").startswith("TSFM-Live-DailyPublisher/")
        return Response(b'{"run_id":"old"}')

    result = publish_daily(
        view, root=tmp_path / "repo", env_file=env, opener=opener, sleep=lambda _: None
    )
    assert result["uploaded"] and not result["readback_verified"]
