"""Quantile-wise median of successful foundation-model distributions."""
from collections.abc import Mapping
import numpy as np
from .base import ForecastOutput


def ensemble(outputs) -> ForecastOutput:
    """Accept id -> ForecastOutput, or records with entrant_id/kind/status/q.

    Caller-supplied baseline IDs are always excluded, even without kind metadata.
    Unknown entrants must have kind='tsfm' when using record form.
    """
    excluded = {"rw0", "volnaive", "ensemble-median"}
    selected = {}
    iterable = outputs.items() if isinstance(outputs, Mapping) else ((x.get("entrant_id"), x) for x in outputs)
    for entrant_id, item in iterable:
        if entrant_id in excluded:
            continue
        if isinstance(item, ForecastOutput):
            selected[entrant_id] = item.quantiles
        elif item.get("kind") == "tsfm" and item.get("status") == "ok":
            selected[entrant_id] = item.get("q", item.get("quantiles"))
    if len(selected) < 3:
        raise ValueError("insufficient_models")
    rows = list(selected.values())
    keys = sorted(rows[0], key=float)
    if any(set(row) != set(keys) for row in rows):
        raise ValueError("ensemble_quantile_grid_mismatch")
    values = np.asarray([[row[k] for k in keys] for row in rows], dtype=float)
    if not np.all(np.isfinite(values)):
        raise ValueError("invalid_ensemble_input")
    result = np.sort(np.median(values, axis=0))
    return ForecastOutput(dict(zip(keys, map(float, result))), None, "native", None)
