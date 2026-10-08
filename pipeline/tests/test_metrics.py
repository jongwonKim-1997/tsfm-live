import math

import pytest
from scipy.stats import norm

from tsfm_live.config.settings import QUANTILES
from tsfm_live.metrics import pinball_loss, score_forecast


def quantiles(value):
    return {str(tau): value for tau in QUANTILES}


def test_hand_computed_pinball_and_degenerate_crps():
    assert pinball_loss(3, 1, 0.2) == pytest.approx(0.4)
    assert pinball_loss(1, 3, 0.2) == pytest.approx(1.6)
    result = score_forecast(3, quantiles(1))
    assert result["se"] == 4
    assert result["ae"] == 2
    assert result["pinball"]["0.5"] == 1
    assert result["crps"] == pytest.approx(2)
    assert result["width80"] == result["width95"] == 0
    assert result["hit"] == 1
    assert score_forecast(-1, quantiles(1))["hit"] == 0


def test_normal_quantile_approximation_expected_value():
    q = {str(tau): float(norm.ppf(tau)) for tau in QUANTILES}
    result = score_forecast(0, q)
    assert result["crps"] == pytest.approx(0.21119390132210775, abs=1e-13)
    assert result["crps"] == pytest.approx(0.211194, abs=5e-7)
    analytical = (math.sqrt(2) - 1) / math.sqrt(math.pi)
    assert analytical == pytest.approx(0.23369497725510913)
    assert result["crps"] != pytest.approx(analytical)
    assert result["hit"] is None


@pytest.mark.parametrize("target,epsilon", [("log_return_pct", 0.01), ("diff_bp", 1.0)])
def test_no_call_threshold_has_correct_units(target, epsilon):
    assert score_forecast(2, quantiles(epsilon * 0.999), target)["hit"] is None
    assert score_forecast(2, quantiles(epsilon), target)["hit"] == 1
    assert score_forecast(-2, quantiles(-epsilon), target)["hit"] == 1
    assert score_forecast(0, quantiles(epsilon), target)["hit"] == 0
    assert score_forecast(0, quantiles(0), target)["hit"] is None


def test_coverage_boundaries_inclusive_and_widths():
    q = {str(tau): tau * 40 - 20 for tau in QUANTILES}
    for tau, key in [(0.1, "covered80"), (0.9, "covered80"),
                     (0.025, "covered95"), (0.975, "covered95")]:
        assert score_forecast(q[str(tau)], q)[key] == 1
    result = score_forecast(17, q)
    assert result["covered80"] == 0
    assert result["covered95"] == 1
    assert result["width80"] == 32
    assert result["width95"] == 38


@pytest.mark.parametrize("actual,q", [(float("nan"), quantiles(0)),
                                     (0, quantiles(float("inf"))),
                                     (0, {"0.5": 0})])
def test_invalid_inputs_rejected(actual, q):
    with pytest.raises(ValueError):
        score_forecast(actual, q)


def test_crossing_quantiles_rejected():
    q = quantiles(0)
    q["0.5"] = 1
    with pytest.raises(ValueError, match="nondecreasing"):
        score_forecast(0, q)
