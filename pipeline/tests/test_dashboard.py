from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from tsfm_live.calendars import session_bounds, session_closes
from tsfm_live.config.settings import QUANTILES
from tsfm_live.dashboard import build_dashboard
from tsfm_live.eligibility import evaluate_eligibility
from tsfm_live.forecast import build_forecasts
from tsfm_live.ledger import iso, parse_ts
from tsfm_live.models.base import ForecastOutput
from tsfm_live.transforms import inverse_transform


RUN = datetime.fromisoformat("2026-10-11T07:00:00+00:00")  # Sunday afternoon in Seoul.
CFG = {"id": "eurusd", "name": "EUR/USD", "group": "fx", "enabled": True, "calendar": "ECB",
       "tz": "Europe/Berlin", "close_time_local": "16:00", "target_transform": "log_return_pct",
       "display_policy": "level", "min_history": 30, "source": {"adapter": "ecb"}, "decimals": 4}
MODEL = {"id": "test-tsfm", "name": "Test TSFM", "kind": "tsfm", "enabled": True, "version": "test"}


def history(cfg=CFG, now=RUN):
    prior, _ = session_bounds(cfg, now)
    closes = session_closes(cfg, prior.date() - timedelta(days=100), prior.date())[-50:]
    data = pd.DataFrame({"close_ts": closes, "value": 1.0 + np.arange(len(closes)) / 1000,
                         "published_ts": None})
    data.attrs["fetched_ts_utc"] = iso(now - timedelta(seconds=1))
    return data


def output(*args, **kwargs):
    return ForecastOutput({str(q): float(q - 0.5) for q in QUANTILES}, 0.0, "native", None)


def build(tmp_path, *, cfg=CFG, data=None, models=None, now=RUN, predict=output, clock=None, **kwargs):
    return build_dashboard([cfg], models if models is not None else [MODEL],
                           {cfg["id"]: history(cfg, now) if data is None else data},
                           now=now, cache_dir=tmp_path, predict=predict, clock=clock or (lambda: now), **kwargs)


def test_weekend_actuals_and_next_market_session_are_honest(tmp_path):
    view, envelope = build(tmp_path)
    row = view["indicators"][0]
    assert view["mode"] == envelope["mode"] == "local_zero_shot"
    assert view["public_ledger_eligible"] is envelope["public_ledger_eligible"] is False
    assert view["run_date"] == "2026-10-11"
    assert row["last_observation"]["session_date"] == "2026-10-09"
    assert row["next_session_date"] == "2026-10-12"
    assert parse_ts(row["next_close_ts"]) - RUN > timedelta(hours=24)
    assert row["forecast_anchor"] == row["last_observation"]
    assert {point["session_date"] for point in row["history"]["last7days"]} == {
        "2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09"}
    assert row["history"]["today"] == [row["last_observation"]]
    entrant = row["entrants"][0]
    assert entrant["median"] == row["last_observation"]["value"]
    assert entrant["upper"] == pytest.approx(inverse_transform(1.049, 0.4, "log_return_pct"), abs=1e-6)
    assert row["source_status"]["freshness"] == "fresh"
    assert view["collection_ts_utc"] == iso(RUN - timedelta(seconds=1))
    assert "lockin_deadline_utc" not in envelope and "deadline_met" not in envelope


def test_treasury_holiday_target_and_percentage_level_units(tmp_path):
    cfg = {**CFG, "id": "ust10y", "calendar": "UST", "tz": "America/New_York", "group": "rates",
           "source": {"adapter": "ustreasury"}, "target_transform": "diff_bp"}
    view, envelope = build(tmp_path, cfg=cfg)
    row = view["indicators"][0]
    assert row["next_session_date"] == "2026-10-13"  # Columbus Day closure is not replaced by a weekday.
    assert row["unit"] == "%" and row["unit_label"] == "yield (%)"
    assert row["entrants"][0]["upper"] == pytest.approx(row["last_observation"]["value"] + .004)
    assert envelope["records"][0]["target_transform"] == "diff_bp"


def test_public_benchmark_deadline_and_horizon_remain_unchanged(tmp_path):
    state = evaluate_eligibility(CFG, history(), RUN)
    assert not state["eligible"] and state["skip_reason"] == "deadline_missed"
    early_weekend = RUN.replace(hour=23) - timedelta(days=1)
    assert evaluate_eligibility(CFG, history(now=early_weekend), early_weekend)["skip_reason"] == "outside_horizon"
    with pytest.raises(ValueError, match="Lock-in deadline"):
        build_forecasts([CFG], [MODEL], {"eurusd": history()}, RUN, RUN + timedelta(hours=1),
                        "2026-10-11", "not-public", tmp_path, predict=output, now=lambda: RUN)


def test_only_enabled_tsfms_are_called_and_history_is_shared(tmp_path):
    called = []
    def predict(cfg, context, **kwargs):
        called.append((cfg["id"], context.copy(), kwargs["seed"]))
        context[0] = 99999
        return output()
    models = [MODEL, {**MODEL, "id": "another"}, {**MODEL, "id": "off", "enabled": False},
              {**MODEL, "id": "rw0", "kind": "baseline"}, {**MODEL, "id": "ensemble", "kind": "ensemble"}]
    view, envelope = build(tmp_path, models=models, predict=predict)
    assert [row[0] for row in called] == ["test-tsfm", "another"]
    np.testing.assert_array_equal(called[0][1], called[1][1])
    assert called[0][2] != called[1][2]
    assert len(view["indicators"][0]["entrants"]) == len(envelope["records"]) == 2


def test_model_failure_keeps_collected_actual_line(tmp_path):
    def broken(*args, **kwargs):
        raise RuntimeError("test failure")
    view, envelope = build(tmp_path, predict=broken)
    row = view["indicators"][0]
    assert row["last_observation"] and len(row["history"]["last7days"]) == 5
    assert row["entrants"][0]["status"] == "failed"
    assert row["entrants"][0]["median"] is None
    assert envelope["records"][0]["status"] == "failed"


def test_observations_only_exports_without_inference(tmp_path):
    view, envelope = build(tmp_path, inference_enabled=False, disabled_reason="runtime_unavailable",
                           predict=lambda *args, **kwargs: pytest.fail("must not invoke a model"))
    assert view["indicators"][0]["last_observation"]
    assert view["indicators"][0]["entrants"][0]["reason"] == "runtime_unavailable"
    assert envelope["records"] == [] and envelope["inference_enabled"] is False
    assert view["forecast_generated_ts_utc"] is None


def test_source_lag_preserves_actuals_but_skips_next_prediction(tmp_path):
    data = history().iloc[:-1].copy()
    view, envelope = build(tmp_path, data=data, predict=lambda *args, **kwargs: pytest.fail("stale source"))
    row = view["indicators"][0]
    assert row["last_observation"]["session_date"] == "2026-10-08"
    assert row["entrants"][0]["reason"] == "source_lag"
    assert row["source_status"]["freshness"] == "source_lag"
    assert envelope["records"][0]["q"] == {}


def test_future_and_unpublished_observations_never_appear(tmp_path):
    data = history()
    fetched = data.attrs["fetched_ts_utc"]
    data.loc[data.index[-1], "published_ts"] = RUN + timedelta(seconds=1)
    data = pd.concat([data, pd.DataFrame({"close_ts": [RUN + timedelta(days=1)], "value": [99999],
                                        "published_ts": [None]})], ignore_index=True)
    data.attrs["fetched_ts_utc"] = fetched
    view, _ = build(tmp_path, data=data)
    row = view["indicators"][0]
    assert row["last_observation"]["session_date"] == "2026-10-08"
    assert all(point["value"] < 2 for point in row["history"]["last7days"])
    assert row["entrants"][0]["reason"] == "source_lag"


@pytest.mark.parametrize("receipt", [None, "2026-10-11T08:00:00Z", "2026-10-11T06:00:00", "bad"])
def test_missing_future_or_naive_acquisition_evidence_is_not_displayed(tmp_path, receipt):
    data = history()
    data.attrs["fetched_ts_utc"] = receipt
    view, _ = build(tmp_path, data=data, predict=lambda *args, **kwargs: pytest.fail("invalid receipt"))
    row = view["indicators"][0]
    assert row["last_observation"] is None and row["history"]["last7days"] == []
    assert row["source_status"]["status"] == "source_error"


def test_publication_after_fetch_is_not_treated_as_observed(tmp_path):
    data = history()
    data.loc[data.index[-1], "published_ts"] = RUN - timedelta(microseconds=1)
    view, _ = build(tmp_path, data=data)
    assert view["indicators"][0]["last_observation"]["session_date"] == "2026-10-08"


def test_impossible_early_publication_invalidates_source(tmp_path):
    data = history()
    data.loc[data.index[-1], "published_ts"] = data.iloc[-1]["close_ts"] - timedelta(seconds=1)
    view, _ = build(tmp_path, data=data, predict=lambda *args, **kwargs: pytest.fail("invalid source"))
    assert view["indicators"][0]["last_observation"] is None
    assert view["indicators"][0]["source_status"]["reason"] == "source_invalid"


@pytest.mark.parametrize("override", [{"enabled": False}, {"display_policy": "return_only"}])
def test_disabled_and_return_only_indicators_never_leak_levels(tmp_path, override):
    view, envelope = build(tmp_path, cfg={**CFG, **override},
                           predict=lambda *args, **kwargs: pytest.fail("not authorized"))
    row = view["indicators"][0]
    assert row["status"] == "disabled" and row["last_observation"] is None
    assert row["history"] == {"today": [], "last7days": []}
    assert envelope["records"] == []


def test_metadata_does_not_export_urls_paths_or_secrets(tmp_path):
    health = [{"id": "eurusd", "status": "ok", "fingerprint": "a" * 64,
               "url": "https://example.test/secret", "raw_file": "private-path", "token": "sensitive-token",
               "raw_evidence": [{"url": "secret-url"}], "error_type": "https://secret-url"}]
    view, _ = build(tmp_path, source_statuses=health, cfg={**CFG, "attribution": "Source: ECB"})
    assert view["indicators"][0]["source_status"]["fingerprint"] == "a" * 64
    assert view["indicators"][0]["attribution"] == "Source: ECB"
    assert "secret" not in str(view) and "private-path" not in str(view)


def test_completion_at_target_voids_forecast_but_keeps_actuals(tmp_path):
    clock = [RUN]
    target = session_bounds(CFG, RUN)[1]
    def predict(*args, **kwargs):
        clock[0] = target
        return output()
    view, envelope = build(tmp_path, predict=predict, clock=lambda: clock[0])
    assert envelope["records"][0]["status"] == "void" and envelope["records"][0]["q"] == {}
    assert view["indicators"][0]["last_observation"]
    assert view["indicators"][0]["entrants"][0]["median"] is None


@pytest.mark.parametrize("clock_value", [RUN - timedelta(seconds=1), RUN + timedelta(minutes=1)])
def test_local_issue_timestamp_cannot_be_backdated_or_future(tmp_path, clock_value):
    with pytest.raises(ValueError, match="current clock"):
        build(tmp_path, clock=lambda: clock_value)
