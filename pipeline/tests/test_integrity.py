import json
import subprocess
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from tsfm_live.config.settings import QUANTILES
from tsfm_live.forecast import build_forecasts, model_predict
from tsfm_live.models.base import ForecastOutput, derive_seed

RUN = datetime.fromisoformat("2026-10-07T23:10:00+00:00")
DEADLINE = RUN.replace(minute=50)
DAY = "2026-10-08"


def indicator(display="level"):
    return {"id": "fixture", "calendar": "CRYPTO_UTC23", "enabled": True,
            "target_transform": "log_return_pct", "min_history": 30,
            "display_policy": display, "source": {"adapter": "fixture"}}


def history():
    closes = pd.date_range(end=RUN.replace(minute=0), periods=70, freq="D", tz="UTC")
    return pd.DataFrame({"close_ts": closes, "value": 100 * np.exp(np.sin(np.arange(70) / 7) / 10),
                         "published_ts": None})


def model(name, kind="tsfm"):
    return {"id": name, "kind": kind, "enabled": True, "version": "fixture"}


def output():
    return ForecastOutput({str(q): float(q - .5) for q in QUANTILES}, 0., "native", None)


def build(tmp_path, models, predict, *, data=None, cfg=None, dry=True, now=lambda: RUN):
    return build_forecasts([cfg or indicator()], models, {"fixture": history() if data is None else data},
                           RUN, DEADLINE, DAY, "fixture-run", tmp_path,
                           predict=predict, now=now, dry_run=dry)


def test_malformed_adapter_isolated_before_ensemble(tmp_path):
    def predict(config, context, **kwargs):
        if config["id"] == "bad":
            return ForecastOutput({"0.5": 0.}, None, "native", None)
        return output()
    result = build(tmp_path, [model("bad"), model("a"), model("b"), model("c"),
                              model("ensemble-median", "ensemble")], predict)
    records = {r["entrant_id"]: r for r in result["records"]}
    assert records["bad"]["status"] == "failed" and records["bad"]["q"] == {}
    assert records["ensemble-median"]["status"] == "ok"
    assert records["ensemble-median"]["contributors"] == ["a", "b", "c"]


def test_identical_private_contexts_and_per_triple_seeds(tmp_path):
    calls = []
    def predict(config, context, *, seed, timeout):
        calls.append((config["id"], context.copy(), seed))
        context[0] = 999999  # A badly behaved adapter cannot mutate the next model's input.
        return output()
    result = build(tmp_path, [model("a"), model("b")], predict)
    np.testing.assert_array_equal(calls[0][1], calls[1][1])
    assert calls[0][2] != calls[1][2]
    for rec, call in zip(result["records"], calls):
        assert rec["seed"] == call[2] == derive_seed(DAY, "fixture", call[0])
        assert rec["context_hash"] == result["records"][0]["context_hash"]


def test_return_only_hides_level_and_private_context_refuses_conflict(tmp_path):
    result = build(tmp_path, [model("a")], lambda *a, **kw: output(), cfg=indicator("return_only"))
    assert result["records"][0]["last_close_value"] is None
    private_path = tmp_path / "contexts" / DAY / "fixture.json"
    private = json.loads(private_path.read_bytes())
    assert private["last_close_value"] > 0 and private["context_hash"]
    original = private_path.read_bytes()
    revised = history()
    revised.loc[revised.index[-1], "value"] *= 1.1
    conflict = build(tmp_path, [model("a")], lambda *a, **kw: pytest.fail("must not infer on conflicting anchor"),
                     data=revised, cfg=indicator("return_only"))
    assert conflict["records"][0]["skip_reason"] == "context_cache_conflict"
    assert private_path.read_bytes() == original


def test_whole_run_void_when_inference_crosses_deadline(tmp_path):
    clock = [RUN]
    calls = []
    def predict(config, context, **kwargs):
        calls.append(config["id"])
        clock[0] = DEADLINE
        return output()
    result = build(tmp_path, [model("a"), model("b")], predict, dry=False, now=lambda: clock[0])
    assert calls == ["a"]
    assert all(r["status"] == "void" and not r["q"] for r in result["records"])


def test_no_model_starts_after_deadline(tmp_path):
    result = build(tmp_path, [model("a")], lambda *a, **kw: pytest.fail("late inference"),
                   dry=False, now=lambda: DEADLINE + timedelta(seconds=1))
    assert result["records"][0]["status"] == "void"


def test_timeout_is_per_model_and_subprocess_request_carries_seed(tmp_path, monkeypatch):
    monkeypatch.setenv("FIXTURE_WORKER", "fixture-python")
    requests = []
    def timeout(command, **kwargs):
        requests.append(json.loads(kwargs["input"]))
        assert kwargs["timeout"] == 0.5
        raise subprocess.TimeoutExpired(command, .5)
    monkeypatch.setattr("tsfm_live.forecast.subprocess.run", timeout)
    with pytest.raises(subprocess.TimeoutExpired):
        model_predict({**model("worker"), "worker_env": "FIXTURE_WORKER"}, np.ones(30), timeout=.5, seed=123)
    assert requests[0]["seed"] == 123
    def predict(config, context, **kwargs):
        if config["id"] == "slow":
            raise subprocess.TimeoutExpired("fixture", 1)
        return output()
    result = build(tmp_path, [model("slow"), model("good")], predict)
    assert result["records"][0]["skip_reason"] == "model_timeout"
    assert result["records"][1]["status"] == "ok"
