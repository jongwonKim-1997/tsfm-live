"""Identical, finite-quantile scoring for every entrant.

CRPS here is the protocol's equal-weight quantile approximation, not the
analytical continuous-distribution CRPS.
"""
from __future__ import annotations

import math
from collections.abc import Mapping

from .config.settings import CALL_EPS, QUANTILES


def pinball_loss(y: float, q: float, tau: float) -> float:
    """Quantile loss with an inclusive zero-residual boundary."""
    if not all(math.isfinite(v) for v in (y, q, tau)) or not 0 < tau < 1:
        raise ValueError("finite inputs and 0 < tau < 1 are required")
    residual = y - q
    return float(tau * residual if residual >= 0 else (tau - 1) * residual)


def score_forecast(
    y: float,
    q: Mapping[str | float, float],
    target_transform: str = "log_return_pct",
) -> dict:
    """Score all 13 protocol quantiles; reject nonfinite or crossing inputs.

    CALL_EPS is 0.01 percentage points of log return, equivalently one basis
    point. A yield-change target is already in basis points, so its epsilon
    is 1.0. Exactly-at-threshold medians make a call.
    """
    if target_transform not in {"log_return_pct", "diff_bp"}:
        raise ValueError(f"unsupported target transform: {target_transform}")
    y = float(y)
    if not math.isfinite(y):
        raise ValueError("actual must be finite")
    quantiles = {float(tau): float(value) for tau, value in q.items()}
    if len(quantiles) != len(q) or set(quantiles) != set(QUANTILES):
        raise ValueError("quantiles must contain exactly the protocol grid")
    values = [quantiles[tau] for tau in QUANTILES]
    if not all(math.isfinite(value) for value in values):
        raise ValueError("quantiles must be finite")
    if any(a > b for a, b in zip(values, values[1:])):
        raise ValueError("quantiles must be nondecreasing")
    losses = {str(tau): pinball_loss(y, quantiles[tau], tau) for tau in QUANTILES}
    q50 = quantiles[0.5]
    error = q50 - y
    threshold = CALL_EPS * (100 if target_transform == "diff_bp" else 1)
    def sign(value):
        return (value > 0) - (value < 0)

    result = {
        "y": y,
        "q50": q50,
        "se": error * error,
        "ae": abs(error),
        "crps": 2 * math.fsum(losses.values()) / len(QUANTILES),
        "pinball": losses,
        "hit": None if abs(q50) < threshold else int(sign(q50) == sign(y)),
        "covered80": int(quantiles[0.1] <= y <= quantiles[0.9]),
        "covered95": int(quantiles[0.025] <= y <= quantiles[0.975]),
        "width80": quantiles[0.9] - quantiles[0.1],
        "width95": quantiles[0.975] - quantiles[0.025],
    }
    if not all(math.isfinite(value) for value in result.values() if isinstance(value, (int, float))):
        raise ValueError("metric overflow")
    return result
