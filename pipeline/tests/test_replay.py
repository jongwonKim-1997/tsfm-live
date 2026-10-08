"""Two-day offline baseline replay: no model downloads or prospective ledger."""
import copy
import json
from datetime import date

import numpy as np
import pandas as pd
import pytest

from tsfm_live.calendars import session_closes
from tsfm_live.eligibility import confirmed_history
from tsfm_live.ledger import canonical_bytes, parse_ts
from tsfm_live.models.baselines import Baseline
from tsfm_live.replay import APPLICATION_ROOT, load_runtime_env, run_replay
from tsfm_live.transforms import transform


def inputs(tmp_path):
    cfg = {"id": "fixture", "enabled": True, "calendar": "CRYPTO_UTC23",
           "target_transform": "log_return_pct", "min_history": 30, "display_policy": "return_only"}
    closes = session_closes(cfg, date(2025, 1, 1), date(2026, 10, 8))
    history = pd.DataFrame({"close_ts": closes, "value": 100 * np.exp(np.sin(np.arange(len(closes)) / 20) / 10),
                            "published_ts": None})
    models = [{"id": eid, "kind": "baseline", "enabled": True, "version": "fixture-baseline"}
              for eid in ("rw0", "volnaive")]
    return {"root": tmp_path / "application", "cache_dir": tmp_path / "unused-source-cache",
            "output_dir": tmp_path / "private-replay", "end_date": "2026-10-08", "days": 2,
            "baselines_only": True, "indicators": [cfg], "models": models, "histories": {"fixture": history}}


def baseline(cfg, context, *, seed, timeout):
    assert timeout > 0
    from tsfm_live.config.settings import QUANTILES
    return Baseline(cfg["id"]).predict(context, QUANTILES, seed)


def test_two_day_checkpoint_resume_is_idempotent_and_keeps_future_out_of_inputs(tmp_path):
    args = inputs(tmp_path)
    calls = []
    def predict(cfg, context, *, seed, timeout):
        calls.append((cfg["id"], context.copy(), seed))
        return baseline(cfg, context, seed=seed, timeout=timeout)
    first = run_replay(**args, max_new_days=1, predict=predict)
    assert first["completed_days"] == 1 and not first["replay_finished"]
    assert len(calls) == 2
    expected = transform(confirmed_history(args["histories"]["fixture"], parse_ts("2026-10-06T23:10:00Z"))["value"],
                         "log_return_pct")[-512:]
    np.testing.assert_array_equal(calls[0][1], expected)
    saved_day = args["output_dir"] / "days/2026-10-07.json"
    original = saved_day.read_bytes()
    finished = run_replay(**args, predict=predict)
    assert len(calls) == 4 and finished["completed_days"] == 2
    assert finished["replay_finished"] and finished["scored_outputs"] == 4
    assert finished["counts"] == {"ok": 4}
    assert saved_day.read_bytes() == original
    assert (args["output_dir"] / "aggregates.json").exists()
    assert not finished["is_live"] and not finished["ledger_written"] and finished["synthetic_inputs"]
    assert not finished["full_spec_completed"] and not finished["pi_scale_validated"]
    assert not args["root"].exists() and not args["cache_dir"].exists()
    def forbidden(*a, **kw):
        raise AssertionError("Completed replay must not invoke inference")
    replayed = run_replay(**args, predict=forbidden)
    assert replayed["scored_outputs"] == 4 and saved_day.read_bytes() == original


def test_interrupted_day_reuses_completed_model_prediction(tmp_path):
    args = inputs(tmp_path)
    first_calls = []
    def interrupted(cfg, context, **kw):
        first_calls.append(cfg["id"])
        if cfg["id"] == "volnaive":
            raise KeyboardInterrupt("controlled fixture interruption")
        return baseline(cfg, context, **kw)
    with pytest.raises(KeyboardInterrupt):
        run_replay(**args, predict=interrupted)
    output = args["output_dir"]
    assert not (output / "days/2026-10-07.json").exists()
    prediction = output / "predictions/2026-10-07/fixture/rw0.json"
    original = prediction.read_bytes()
    resumed_calls = []
    def resumed(cfg, context, **kw):
        resumed_calls.append(cfg["id"])
        return baseline(cfg, context, **kw)
    result = run_replay(**args, predict=resumed)
    assert resumed_calls == ["volnaive", "rw0", "volnaive"]
    assert result["scored_outputs"] == 4 and prediction.read_bytes() == original


def test_changed_frozen_data_and_tampered_checkpoint_are_refused(tmp_path):
    args = inputs(tmp_path)
    run_replay(**args, max_new_days=1, predict=baseline)
    revised = copy.deepcopy(args)
    revised["histories"]["fixture"].loc[0, "value"] += 1
    with pytest.raises(ValueError, match="changed"):
        run_replay(**revised, predict=baseline)
    checkpoint = args["output_dir"] / "predictions/2026-10-07/fixture/rw0.json"
    record = json.loads(checkpoint.read_bytes())
    record["payload"]["output"]["quantiles"]["0.5"] = 1.
    checkpoint.write_bytes(canonical_bytes(record))
    with pytest.raises(ValueError, match="checkpoint hash mismatch"):
        run_replay(**args, predict=baseline)


def test_replay_refuses_public_paths_and_nonempty_private_folder(tmp_path):
    args = inputs(tmp_path)
    with pytest.raises(ValueError, match="outside"):
        run_replay(**{**args, "output_dir": APPLICATION_ROOT / "replay-results"}, predict=baseline)
    with pytest.raises(ValueError, match="ledger"):
        run_replay(**{**args, "output_dir": tmp_path / "ledger/replay"}, predict=baseline)
    args["output_dir"].mkdir()
    owned = args["output_dir"] / "owned.txt"
    owned.write_text("keep")
    with pytest.raises(ValueError, match="empty"):
        run_replay(**args, predict=baseline)
    assert owned.read_text() == "keep"


def test_runtime_env_is_literal_and_rejects_unrelated_settings(tmp_path, monkeypatch):
    monkeypatch.delenv("TSFM_PYTHON_FIXTURE", raising=False)
    path = tmp_path / "runtime.env"
    path.write_text('TSFM_PYTHON_FIXTURE="C:/literal/$(never_execute)/python.exe"\n')
    load_runtime_env(path)
    import os
    assert os.environ["TSFM_PYTHON_FIXTURE"] == "C:/literal/$(never_execute)/python.exe"
    path.write_text("UNRELATED_SECRET=not-loaded\n")
    with pytest.raises(ValueError, match="only worker paths"):
        load_runtime_env(path)
