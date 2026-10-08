"""Honest baselines sharing the exact forecast-time context."""
import numpy as np
from scipy.stats import norm
from .base import ForecastOutput, checked_context, checked_levels
from tsfm_live.config.settings import EWMA_LAMBDA, REGIME_LOOKBACK, REGIME_PCTL


def ewma_path(context, decay=EWMA_LAMBDA) -> np.ndarray:
    """RiskMetrics zero-mean recursion, initial sample variance at observation 20."""
    x = checked_context(context)
    if len(x) < 20:
        raise ValueError("ewma_requires_20_observations")
    variance = float(np.var(x[:20], ddof=1))
    result = [variance**0.5]
    for value in x[20:]:
        variance = decay * variance + (1 - decay) * float(value)**2
        result.append(variance**0.5)
    return np.asarray(result)


def ewma_sigma(context) -> float:
    return float(ewma_path(context)[-1])


def regime_flag(context) -> str:
    sigmas = ewma_path(context)
    threshold = np.quantile(sigmas[-REGIME_LOOKBACK:], REGIME_PCTL, method="linear")
    return "high_vol" if sigmas[-1] >= threshold else "normal"


class Baseline:
    kind = "baseline"
    version = "builtin:1.0.0"

    def __init__(self, entrant_id):
        if entrant_id not in {"rw0", "volnaive"}:
            raise ValueError("unknown_baseline")
        self.id = entrant_id

    def predict(self, context, quantiles, seed):
        x = checked_context(context)
        levels = checked_levels(quantiles)
        sigma = 0.0 if self.id == "rw0" else ewma_sigma(x)
        return ForecastOutput(
            {str(float(q)): float(sigma * norm.ppf(q)) for q in levels},
            0.0, "native", None,
        )
