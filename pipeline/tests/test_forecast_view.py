"""Homepage observations and next-session forecasts retain temporal/unit meaning."""
from datetime import datetime, timezone

import pytest

from fixture_ledger import export_fixture, generate_fixture
from test_export import read_api
from tsfm_live.export import forecast_view
from tsfm_live.ledger import materialize
from tsfm_live.models import load_models
from tsfm_live.sources import load_indicators
from tsfm_live.transforms import inverse_transform

UTC = timezone.utc
NOW = datetime(2026, 10, 6, 23, 20, tzinfo=UTC)


def config(policy="level", kind="log_return_pct"):
    return {"id": "fixture", "name": "Fixture", "group": "rates" if kind == "diff_bp" else "fx",
            "enabled": True, "tz": "Europe/Berlin", "target_transform": kind,
            "display_policy": policy, "decimals": 4, "unit": "USD/EUR" if kind == "log_return_pct" else "%"}


def latest_record(kind="log_return_pct", anchor=1.1):
    from tsfm_live.config.settings import QUANTILES
    return {"indicator_id": "fixture", "entrant_id": "model", "status": "ok", "skip_reason": None,
            "target_transform": kind, "last_close_ts": "2026-10-06T14:00:00Z", "last_close_value": anchor,
            "next_close_ts": "2026-10-07T14:00:00Z", "q": {str(q): float(q - 0.5) for q in QUANTILES}}


def latest(records=None):
    return {"run_date": "2026-10-07", "run_ts_utc": "2026-10-06T23:10:00Z", "state": "locked",
            "deadline_met": True, "records": records if records is not None else [latest_record()]}


def actual(day, value, y=0.2, **extra):
    return {"indicator_id": "fixture", "close_ts": f"2026-10-{day:02d}T14:00:00Z", "value": value, "y": y,
            "fetched_ts_utc": f"2026-10-{day:02d}T15:00:00Z", "published_ts": None, **extra}


MODELS = [{"id": "model", "name": "Fixture model", "kind": "tsfm", "enabled": True},
          {"id": "missing", "name": "Missing model", "kind": "tsfm", "enabled": True},
          {"id": "disabled", "name": "Disabled model", "kind": "tsfm", "enabled": False}]


def test_today_latest_daily_and_seven_calendar_days_do_not_include_target_outcome():
    observations = {("fixture", a["close_ts"]): a for a in [actual(1, 1.01), actual(2, 1.02), actual(5, 1.05),
                                                           actual(6, 1.06), actual(7, 999.)]}
    view = forecast_view([config()], MODELS, latest(), observations, now=NOW)
    row = view["indicators"][0]
    assert row["history"]["today"] == [row["last_observation"]]
    assert row["last_observation"]["value"] == 1.06
    assert [r["session_date"] for r in row["history"]["last7days"]] == ["2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06"]
    assert all(p["value"] != 999. for p in row["history"]["last7days"])
    assert row["next_session_date"] == "2026-10-07" and row["next_session_timezone"] == "Europe/Berlin"
    assert row["status"] == "available" and row["entrants"][0]["availability"] == "available"
    assert row["entrants"][0]["median"] == 1.1
    assert row["entrants"][0]["lower"] == pytest.approx(inverse_transform(1.1, -.4, "log_return_pct"))
    assert row["entrants"][1]["median"] is None and row["entrants"][1]["status"] == "missing"
    assert row["entrants"][2]["availability"] == "disabled"


def test_only_observations_known_by_export_and_before_target_are_charted():
    actuals = {("fixture", a["close_ts"]): a for a in [actual(5, 1.05), actual(6, 1.06, fetched_ts_utc="2026-10-07T00:00:00Z")]}
    row = forecast_view([config()], MODELS, latest(), actuals, now=NOW)["indicators"][0]
    assert row["last_observation"]["origin"] == "issued_context_anchor"
    assert row["last_observation"]["value"] == 1.1
    assert [p["value"] for p in row["history"]["last7days"]] == [1.05, 1.1]
    # At a much later export, historical target actuals still cannot enter the
    # pre-forecast history or make an expired prediction look upcoming.
    later = forecast_view([config()], MODELS, latest(), actuals, now=datetime(2026, 10, 20, tzinfo=UTC))["indicators"][0]
    assert later["status"] == "expired" and later["entrants"][0]["reason"] == "target_already_closed"
    assert later["entrants"][0]["median"] == 1.1


@pytest.mark.parametrize("transform_kind,anchor,unit,median", [("log_return_pct", None, "%", 0.), ("diff_bp", None, "bp", 0.)])
def test_return_only_uses_daily_changes_without_private_level_reconstruction(transform_kind, anchor, unit, median):
    cfg = config("return_only", transform_kind)
    record = latest_record(transform_kind, anchor)
    a = actual(6, None, y=2.5)
    row = forecast_view([cfg], MODELS, latest([record]), {("fixture", a["close_ts"]): a}, now=NOW)["indicators"][0]
    assert row["value_kind"] == "change" and row["unit"] == unit
    assert row["forecast_anchor"] is None
    assert row["last_observation"]["value"] == 2.5
    assert row["entrants"][0]["median"] == median
    assert row["entrants"][0]["lower"] == -.4


def test_treasury_level_is_yield_percent_not_basis_points():
    cfg = config(kind="diff_bp")
    record = latest_record("diff_bp", 4.0)
    record["q"] = {q: value * 10 + 5 for q, value in record["q"].items()}
    row = forecast_view([cfg], MODELS, latest([record]), {}, now=NOW)["indicators"][0]
    assert row["unit"] == "%" and row["unit_label"] == "yield (%)"
    assert row["last_observation"]["value"] == 4.0
    assert row["entrants"][0]["median"] == 4.05
    assert row["entrants"][0]["lower"] == 4.01


@pytest.mark.parametrize("status", ["failed", "void", "deadline_missed"])
def test_failed_or_void_current_run_has_no_displayable_predictions(status):
    document = latest()
    document.update(state=status, deadline_met=False)
    row = forecast_view([config()], MODELS, document, {}, now=NOW)["indicators"][0]
    assert row["status"] == "unavailable"
    assert row["last_observation"] is None
    assert all(r["median"] is None and r["quantiles"] is None for r in row["entrants"])


def test_future_issue_and_holiday_target_dates_are_not_called_tomorrow():
    record = latest_record()
    record["next_close_ts"] = "2026-10-12T14:00:00Z"
    row = forecast_view([config()], MODELS, latest([record]), {}, now=NOW)["indicators"][0]
    assert row["next_session_date"] == "2026-10-12"
    before_issue = forecast_view([config()], MODELS, latest(), {}, now=datetime(2026, 10, 6, 23, tzinfo=UTC))["indicators"][0]
    assert before_issue["entrants"][0]["reason"] == "run_not_yet_issued"
    assert before_issue["entrants"][0]["median"] is None and before_issue["last_observation"] is None


def test_empty_production_shape_retains_every_indicator_and_model_without_fallback():
    empty = {"run_date": None, "records": [], "state": "awaiting_first_lockin", "deadline_met": False}
    indicators, models = load_indicators(), load_models()
    view = forecast_view(indicators, models, empty, {}, now=NOW)
    assert len(view["indicators"]) == 14
    assert all(len(r["entrants"]) == len(models) for r in view["indicators"])
    assert all(r["history"] == {"today": [], "last7days": []} for r in view["indicators"])
    assert all(m["median"] is None for r in view["indicators"] for m in r["entrants"])
    assert {r["status"] for r in view["indicators"]} == {"unavailable", "disabled"}


def test_real_export_endpoint_has_same_source_values_and_does_not_modify_ledger(tmp_path):
    generate_fixture(tmp_path, days=10, return_only=["usdjpy"])
    before = {str(p): p.read_bytes() for p in (tmp_path / "ledger").rglob("*") if p.is_file()}
    export_fixture(tmp_path, now=NOW)
    view = read_api(tmp_path, "forecast_view.json")
    assert view["fixture"] and view["run_date"] == "2026-10-07"
    assert view["interval_probability"] == .8
    fx = next(r for r in view["indicators"] if r["id"] == "eurusd")
    assert fx["unit"] == "USD/EUR" and fx["status"] == "available"
    rates = next(r for r in view["indicators"] if r["id"] == "ust10y")
    assert rates["unit"] == "%" and rates["next_session_timezone"] == "America/New_York"
    return_only = next(r for r in view["indicators"] if r["id"] == "usdjpy")
    assert return_only["unit"] == "%" and return_only["value_kind"] == "change"
    actuals = materialize(tmp_path)["actuals"]
    for row in view["indicators"]:
        for point in row["history"]["last7days"]:
            if point["origin"] == "actual":
                actual_value = actuals[row["id"], point["close_ts"]]
                expected = actual_value["value"] if row["display_policy"] == "level" else actual_value["y"]
                assert point["value"] == expected
    assert before == {str(p): p.read_bytes() for p in (tmp_path / "ledger").rglob("*") if p.is_file()}
