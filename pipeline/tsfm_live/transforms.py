"""Protocol transformations. Yields are quoted in percent, changes in basis points."""
from __future__ import annotations

import numpy as np


def transform(values, kind: str) -> np.ndarray:
    x = np.asarray(values, dtype=np.float64)
    if x.ndim != 1 or not np.all(np.isfinite(x)):
        raise ValueError("history must be one-dimensional and finite")
    if kind == "log_return_pct":
        if np.any(x <= 0):
            raise ValueError("log returns require strictly positive levels")
        return 100.0 * np.diff(np.log(x))
    if kind == "diff_bp":
        return 100.0 * np.diff(x)
    raise ValueError(f"unknown transform: {kind}")


def inverse_transform(last: float, y: float, kind: str) -> float:
    if not np.isfinite(last) or not np.isfinite(y):
        raise ValueError("non-finite input")
    if kind == "log_return_pct":
        if last <= 0:
            raise ValueError("log returns require a positive level")
        result = last * np.exp(y / 100.0)
    elif kind == "diff_bp":
        result = last + y / 100.0
    else:
        raise ValueError(f"unknown transform: {kind}")
    if not np.isfinite(result):
        raise ValueError("non-finite inverse transform")
    return float(result)
