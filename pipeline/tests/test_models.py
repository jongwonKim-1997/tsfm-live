import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest
from scipy.stats import norm

from tsfm_live.models import create_entrant, derive_seed, ensemble, ewma_sigma, load_models, regime_flag
from tsfm_live.models.base import ForecastOutput, output_from_quantiles, output_from_samples
from tsfm_live.config.settings import QUANTILES


def test_ewma_matches_independent_fixed_reference():
    values = np.asarray([(-1)**i * i / 10 for i in range(1, 41)])
    mean = sum(values[:20]) / 20
    reference = sum((x - mean)**2 for x in values[:20]) / 19
    for x in values[20:]:
        reference = 0.94 * reference + 0.06 * x * x
    assert ewma_sigma(values) == pytest.approx(reference**0.5)


def test_baselines_zero_and_symmetric():
    context = np.linspace(-3, 3, 40)
    zero = create_entrant("rw0").predict(context, QUANTILES, 7)
    assert set(zero.quantiles.values()) == {0.0}
    normal = create_entrant("volnaive").predict(context, QUANTILES, 7)
    assert normal.quantiles["0.025"] == pytest.approx(-normal.quantiles["0.975"])
    assert normal.quantiles["0.5"] == 0.0
    assert normal.quantiles["0.9"] == pytest.approx(norm.ppf(.9) * ewma_sigma(context))


def test_invalid_context_cannot_generate_synthetic_replacement():
    with pytest.raises(ValueError, match="finite_univariate"):
        create_entrant("rw0").predict([1, np.nan], QUANTILES, 1)
    with pytest.raises(ValueError, match="20"):
        ewma_sigma(np.ones(19))


def test_tail_extrapolation_not_endpoint_clamping():
    result = output_from_quantiles([.1, .5, .9], [-4, 0, 4], QUANTILES)
    assert result.quantile_method == "interpolated"
    assert result.quantiles["0.025"] == pytest.approx(-4.75)
    assert result.quantiles["0.975"] == pytest.approx(4.75)
    assert result.mean is None


def test_crossing_repair_and_native_grid():
    result = output_from_quantiles([.1, .5, .9], [4, -4, 0], [.1, .5, .9])
    assert list(result.quantiles.values()) == [-4, 0, 4]
    assert result.quantile_method == "native"


def test_samples_require_1000_and_preserve_empirical_mean():
    with pytest.raises(ValueError, match="1000"):
        output_from_samples(np.arange(999), QUANTILES)
    result = output_from_samples(np.arange(1000), QUANTILES)
    assert result.n_samples == 1000 and result.mean == 499.5
    assert result.quantile_method == "sampled"
    assert result.quantiles["0.025"] == pytest.approx(24.975)


def test_ensemble_excludes_baselines_and_requires_three_unique_models():
    outputs = {x: output_from_quantiles(QUANTILES, np.ones(13) * y, QUANTILES)
               for x, y in [("a", 1), ("b", 4), ("c", 7), ("rw0", -100), ("volnaive", -100)]}
    result = ensemble(outputs)
    assert set(result.quantiles.values()) == {4.0}
    with pytest.raises(ValueError, match="insufficient_models"):
        ensemble({key: outputs[key] for key in ["a", "b", "rw0", "volnaive"]})


def test_ensemble_rejects_failed_or_custom_baseline_records():
    q = dict(zip(map(str, QUANTILES), range(13)))
    rows = [{"entrant_id": name, "kind": kind, "status": status, "q": q}
            for name, kind, status in [("a", "tsfm", "ok"), ("b", "tsfm", "ok"),
                                       ("c", "tsfm", "failed"), ("custom", "baseline", "ok")]]
    with pytest.raises(ValueError, match="insufficient_models"):
        ensemble(rows)


def test_bad_forecast_is_rejected():
    with pytest.raises(ValueError, match="nonmonotone"):
        ForecastOutput({"0.1": 2, "0.9": 1}, None, "native", None)
    with pytest.raises(ValueError, match="nonfinite"):
        ForecastOutput({"0.5": 0}, float("nan"), "native", None)


def test_regime_uses_only_trailing_observed_sigma():
    context = np.tile([-1., 1.], 256)
    assert regime_flag(np.r_[context[:-10], np.ones(10)*20]) == "high_vol"
    assert regime_flag(np.r_[context[:300], np.zeros(212)]) == "normal"


def test_seed_is_stable_and_isolated():
    a = derive_seed("2026-10-08", "kospi", "chronos-2")
    assert a == derive_seed("2026-10-08", "kospi", "chronos-2")
    assert a != derive_seed("2026-10-09", "kospi", "chronos-2")


def test_catalog_has_exact_revisions_and_distinguishes_runtime_validation():
    models = load_models()
    tsfms = [x for x in models if x["kind"] == "tsfm"]
    assert len(tsfms) == 8
    for model in tsfms:
        assert len(model["hf_revision"]) == 40 and "==" in model["package"]
        assert model["api_verified"] is True
        assert "runtime_verified" in model and "launch_ready" in model
    assert not next(x for x in tsfms if x["id"] == "tabpfn-ts")["enabled"]


def test_remote_code_requires_exact_audited_commit_before_import():
    cfg = next(x for x in load_models() if x["id"] == "sundial-base-128m")
    cfg["hf_revision"] = "0" * 40
    with pytest.raises(RuntimeError, match="not_audited"):
        create_entrant(cfg).predict(np.ones(512), QUANTILES, 1)


def test_mutable_weight_revision_is_rejected():
    cfg = next(x for x in load_models() if x["id"] == "chronos-2")
    cfg["hf_revision"] = "main"
    with pytest.raises(ValueError, match="pinned_hf_revision"):
        create_entrant(cfg)


def test_worker_real_baseline_roundtrip_and_error_protocol():
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).parents[1]))
    request = {"config": {"id": "rw0"}, "context": list(range(30)), "quantiles": QUANTILES, "seed": 7}
    proc = subprocess.run([sys.executable, "-m", "tsfm_live.models.worker"],
                          input=json.dumps(request), text=True, capture_output=True, env=env, timeout=20)
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)
    assert result["ok"] and set(result["output"]["quantiles"].values()) == {0.0}
    request["context"] = []
    proc = subprocess.run([sys.executable, "-m", "tsfm_live.models.worker"],
                          input=json.dumps(request), text=True, capture_output=True, env=env, timeout=20)
    assert proc.returncode == 1 and json.loads(proc.stdout)["ok"] is False
