import copy
from datetime import timedelta
import json
import subprocess

import numpy as np
import pandas as pd
import pytest

from tsfm_live.config.settings import QUANTILES
from tsfm_live.forecast import model_predict
from tsfm_live.hourly_dashboard import build_hourly_dashboard, hourly_history
from tsfm_live.ledger import iso, parse_ts
from tsfm_live.models.base import ForecastOutput, ForecastPathOutput, path_output


NOW = parse_ts("2026-10-13T03:05:00Z")
CFG = {"id": "btckrw", "name": "Bitcoin / KRW", "calendar": "24/7", "frequency": "1h", "enabled": True,
       "tz": "Asia/Seoul", "unit": "KRW", "display_policy": "level", "min_history": 300,
       "context_length": 512, "public_export": False, "source": {"adapter": "upbit_hourly"}}
MODEL = {"id": "test-tsfm", "name": "Test model", "kind": "tsfm", "enabled": True, "version": "test"}


def history(now=NOW):
    frame = pd.DataFrame({"close_ts": pd.date_range(end=now.replace(minute=0), periods=600, freq="h"),
                          "value": np.linspace(90, 100, 600), "published_ts": None})
    frame.attrs["fetched_ts_utc"] = iso(now - timedelta(seconds=1))
    return frame


def output(*args, **kwargs):
    return ForecastPathOutput([ForecastOutput({str(q): 100 + step + q for q in QUANTILES},
                                              100.5 + step, "native", None) for step in range(24)])


def build(tmp_path, *, cfg=None, data=None, models=None, predict=output, clock=lambda: NOW, **kwargs):
    cfg = cfg or CFG
    return build_hourly_dashboard([cfg], models or [MODEL], {cfg["id"]: history() if data is None else data},
                                  now=NOW, cache_dir=tmp_path, clock=clock, predict=predict, **kwargs)


def test_24_native_hourly_levels_and_real_kst_history(tmp_path):
    calls = []
    def predict(model, context, **kwargs):
        calls.append((context.copy(), kwargs))
        return output()
    view, raw = build(tmp_path, predict=predict)
    row = view["indicators"][0]
    path = row["entrants"][0]["path"]
    assert view["frequency"] == "1h" and view["horizon_steps"] == 24
    assert view["forecast_basis"] == "direct_level" and view["interval_basis"] == "pointwise_marginal"
    assert row["visible"] is True and row["public_export"] is False
    assert len(path) == 24
    assert path[0]["close_ts"] == "2026-10-13T04:00:00Z"
    assert path[-1]["close_ts"] == "2026-10-14T03:00:00Z"
    assert path[0]["median"] == 100.5 and path[1]["median"] == 101.5  # Never accumulate marginal returns.
    assert row["last_observation"]["close_ts"] == "2026-10-13T03:00:00Z"
    assert len(row["history"]["last7days"]) == 168
    assert row["history"]["today"][0]["close_ts"] == "2026-10-12T15:00:00Z"  # 00:00 KST.
    assert {point["session_date"] for point in row["history"]["today"]} == {"2026-10-13"}
    np.testing.assert_array_equal(calls[0][0], history()["value"].to_numpy()[-512:])
    assert calls[0][1]["horizon"] == 24 and calls[0][1]["interval_seconds"] == 3600
    assert calls[0][1]["timeout"] == 120
    assert raw["public_ledger_eligible"] is False and "lockin_deadline_utc" not in raw


@pytest.mark.parametrize("updates,reason", [({"calendar": "unknown"}, "calendar_unverified"),
    ({"calendar": "XKRX"}, "calendar_unverified"), ({"market_status": "closed"}, "market_closed_or_unknown"),
    ({"market_status": "unknown"}, "market_closed_or_unknown"), ({"frequency": "1d"}, "calendar_unverified"),
    ({"display_policy": "return_only"}, "level_display_not_authorized"), ({"enabled": False}, "disabled")])
def test_unverified_closed_or_disallowed_markets_are_hidden(tmp_path, updates, reason):
    view, raw = build(tmp_path, cfg={**CFG, **updates}, predict=lambda *a, **kw: pytest.fail("hidden market"))
    assert view["indicators"][0]["visible"] is False
    assert view["indicators"][0]["reason"] == reason
    assert raw["records"][0]["path"] == []


@pytest.mark.parametrize("mutation,reason", [("old", "source_lag"), ("gap", "history_gap"),
    ("few", "insufficient_history"), ("duplicate", "source_invalid"), ("naive", "source_invalid"),
    ("unaligned", "source_invalid"), ("negative", "source_invalid"), ("nonfinite", "source_invalid")])
def test_stale_gapped_invalid_data_are_hidden(tmp_path, mutation, reason):
    frame = history()
    if mutation == "old":
        frame = frame.iloc[:-1]
    elif mutation == "gap":
        frame = frame.drop(frame.index[-25])
    elif mutation == "few":
        frame = frame.tail(299)
    elif mutation == "duplicate":
        frame.loc[frame.index[-1], "close_ts"] = frame.iloc[-2]["close_ts"]
    elif mutation == "naive":
        frame["close_ts"] = frame["close_ts"].dt.tz_localize(None)
    elif mutation == "unaligned":
        frame.loc[frame.index[-2], "close_ts"] += timedelta(minutes=1)
    elif mutation == "negative":
        frame.loc[frame.index[-2], "value"] = -1
    elif mutation == "nonfinite":
        frame.loc[frame.index[-2], "value"] = np.inf
    view, _ = build(tmp_path, data=frame, predict=lambda *a, **kw: pytest.fail("invalid source"))
    assert view["indicators"][0]["visible"] is False
    assert view["indicators"][0]["reason"] == reason


def test_incomplete_future_candle_is_excluded_without_interpolation(tmp_path):
    frame = history()
    receipt = frame.attrs.copy()
    frame = pd.concat([frame, pd.DataFrame({"close_ts": [NOW.replace(minute=0) + timedelta(hours=1)],
                                           "value": [999999], "published_ts": [None]})], ignore_index=True)
    frame.attrs.update(receipt)
    view, raw = build(tmp_path, data=frame)
    assert view["indicators"][0]["last_observation"]["value"] == 100
    assert raw["records"][0]["context_len"] == 512


def test_known_unpublished_and_preliminary_bar_cannot_be_latest(tmp_path):
    frame = history()
    frame.loc[frame.index[-1], "published_ts"] = NOW + timedelta(seconds=1)
    view, _ = build(tmp_path, data=frame)
    assert view["indicators"][0]["reason"] == "source_lag"
    frame = history()
    frame["is_final"] = True
    frame.loc[frame.index[-1], "is_final"] = False
    view, _ = build(tmp_path, data=frame)
    assert view["indicators"][0]["reason"] == "source_lag"


def test_runtime_failure_preserves_actuals_for_open_fresh_market(tmp_path):
    def failed(*args, **kwargs):
        raise RuntimeError("failure")
    view, _ = build(tmp_path, predict=failed)
    row = view["indicators"][0]
    assert row["visible"] is True and row["last_observation"]
    assert row["entrants"][0]["status"] == "failed" and row["entrants"][0]["path"] == []


def test_observations_only_and_enabled_tsfm_filter(tmp_path):
    models = [MODEL, {**MODEL, "id": "baseline", "kind": "baseline"},
              {**MODEL, "id": "disabled", "enabled": False}]
    view, raw = build(tmp_path, models=models, inference_enabled=False,
                      predict=lambda *a, **kw: pytest.fail("disabled inference"))
    assert len(raw["records"]) == 1 and raw["records"][0]["status"] == "skipped"
    assert view["indicators"][0]["visible"] is True
    assert view["forecast_generated_ts_utc"] is None


def test_batch_crossing_hour_removes_past_targets_and_hides_lagged_source(tmp_path):
    clock = [NOW]
    def predict(*args, **kwargs):
        clock[0] = NOW.replace(hour=4, minute=1)
        return output()
    view, raw = build(tmp_path, clock=lambda: clock[0], predict=predict)
    assert len(raw["records"][0]["path"]) == 23
    assert raw["records"][0]["path"][0]["close_ts"] == "2026-10-13T05:00:00Z"
    assert view["indicators"][0]["visible"] is False
    assert view["indicators"][0]["reason"] == "source_lag"


def test_no_backdating_or_future_issue_time(tmp_path):
    with pytest.raises(ValueError, match="current clock"):
        build(tmp_path, clock=lambda: NOW + timedelta(minutes=1))
    with pytest.raises(ValueError, match="current clock"):
        build(tmp_path, clock=lambda: NOW - timedelta(seconds=1))


def test_global_inference_budget_and_timeout_are_bounded(tmp_path):
    clock, calls = [NOW], []
    def slow(model, context, **kwargs):
        calls.append(model["id"])
        clock[0] += timedelta(seconds=601)
        raise subprocess.TimeoutExpired("fixture", kwargs["timeout"])
    view, raw = build(tmp_path, models=[MODEL, {**MODEL, "id": "second"}], clock=lambda: clock[0], predict=slow)
    assert calls == ["test-tsfm"]
    assert raw["records"][0]["skip_reason"] == "model_timeout"
    assert raw["records"][1]["skip_reason"] == "inference_budget_exhausted"
    assert view["indicators"][0]["visible"] is True


def test_worker_request_and_response_preserve_24_steps(monkeypatch):
    from dataclasses import asdict
    monkeypatch.setenv("TEST_WORKER", "python")
    cfg = {**MODEL, "worker_env": "TEST_WORKER"}
    def run(command, **kwargs):
        request = json.loads(kwargs["input"])
        assert request["horizon"] == 24 and request["interval_seconds"] == 3600
        return subprocess.CompletedProcess(command, 0, json.dumps({"ok": True, "output": asdict(output())}))
    monkeypatch.setattr("tsfm_live.forecast.subprocess.run", run)
    result = model_predict(cfg, np.ones(512), horizon=24, interval_seconds=3600)
    assert isinstance(result, ForecastPathOutput) and len(result.steps) == 24


def test_hourly_model_outputs_must_be_native_complete_horizon(tmp_path):
    incomplete = ForecastPathOutput(output().steps[:1])
    view, raw = build(tmp_path, predict=lambda *args, **kwargs: incomplete)
    assert raw["records"][0]["status"] == "failed"
    assert view["indicators"][0]["entrants"][0]["path"] == []


def test_default_one_step_return_contract_is_unchanged():
    first = copy.deepcopy(output().steps[0])
    assert path_output([first], 1) == first
    assert isinstance(path_output(output().steps, 24), ForecastPathOutput)
    with pytest.raises(ValueError):
        path_output(output().steps, True)
    _, state = hourly_history(CFG, history(), now=NOW)
    assert state["eligible"]


def test_short_free_hourly_history_uses_only_real_available_context(tmp_path):
    cfg = {**CFG, "min_history": 128, "context_length": 512,
           "observation_kind": "reference_rate", "license_id": "CC-BY-NC-4.0",
           "license_url": "https://creativecommons.org/licenses/by-nc/4.0/",
           "source_url": "https://docs.coinmetrics.io/packages/coin-metrics-community-data"}
    frame = history().tail(169)
    calls = []
    def predict(model, context, **kwargs):
        calls.append(context)
        return output()
    view, raw = build(tmp_path, cfg=cfg, data=frame, predict=predict)
    assert len(calls[0]) == 169
    assert raw["records"][0]["context_len"] == 169
    row = view["indicators"][0]
    assert row["context_length"] == 169 and row["visible"]
    assert row["observation_kind"] == "reference_rate" and row["license_id"] == "CC-BY-NC-4.0"
    _, state = hourly_history(cfg, frame.tail(127), now=NOW)
    assert state["reason"] == "insufficient_history"


@pytest.mark.parametrize("minimum", [0, 127, 513, True, "128"])
def test_invalid_short_history_minimum_is_rejected(minimum):
    _, state = hourly_history({**CFG, "min_history": minimum}, history(), now=NOW)
    assert state["reason"] == "invalid_min_history"
