"""Uniform, finite one-session distributions; no package imports at module load."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from importlib.metadata import version as package_version
import os
import random
import re
from typing import Literal, Protocol

import numpy as np


@dataclass(frozen=True)
class ForecastOutput:
    quantiles: dict[str, float]
    mean: float | None
    quantile_method: Literal["native", "sampled", "interpolated"]
    n_samples: int | None

    def __post_init__(self):
        levels = np.asarray([float(k) for k in self.quantiles])
        values = np.asarray(list(self.quantiles.values()), dtype=float)
        if not len(levels) or np.any((levels <= 0) | (levels >= 1)):
            raise ValueError("invalid_quantile_levels")
        if len(set(levels)) != len(levels) or not np.all(np.isfinite(values)):
            raise ValueError("invalid_quantile_values")
        if np.any(np.diff(values[np.argsort(levels)]) < 0):
            raise ValueError("nonmonotone_quantiles")
        if self.mean is not None and not np.isfinite(self.mean):
            raise ValueError("nonfinite_mean")
        if self.quantile_method not in {"native", "sampled", "interpolated"}:
            raise ValueError("invalid_quantile_method")
        if self.quantile_method == "sampled" and (self.n_samples or 0) < 1000:
            raise ValueError("insufficient_samples")


class Entrant(Protocol):
    id: str
    kind: Literal["baseline", "tsfm", "ensemble"]
    version: str

    def predict(self, context: np.ndarray, quantiles: list[float], seed: int) -> ForecastOutput: ...


def checked_context(context) -> np.ndarray:
    result = np.asarray(context, dtype=np.float64)
    if result.ndim != 1 or not len(result) or not np.all(np.isfinite(result)):
        raise ValueError("context_must_be_finite_univariate")
    return result.copy()


def checked_levels(levels) -> np.ndarray:
    result = np.asarray(levels, dtype=float)
    if (result.ndim != 1 or not len(result) or not np.all(np.isfinite(result))
            or np.any((result <= 0) | (result >= 1))
            or len(set(result)) != len(result)):
        raise ValueError("invalid_quantile_levels")
    return np.sort(result)


def as_numpy(value) -> np.ndarray:
    if hasattr(value, "detach"):
        value = value.detach().cpu().numpy()
    return np.asarray(value, dtype=float)


def output_from_quantiles(levels, values, requested, *, mean=None) -> ForecastOutput:
    """Sort crossings and interpolate with linear (not flat) endpoint tails."""
    x = np.asarray(levels, dtype=float)
    y = as_numpy(values).reshape(-1)
    if len(x) != len(y) or not np.all(np.isfinite(y)):
        raise ValueError("invalid_native_quantiles")
    checked_levels(x)
    order = np.argsort(x)
    x, y = x[order], np.sort(y[order])
    target = checked_levels(requested)
    native = all(np.any(np.isclose(q, x, rtol=0, atol=1e-12)) for q in target)
    if not native and len(x) < 2:
        raise ValueError("insufficient_quantiles_for_interpolation")
    result = np.interp(target, x, y)
    if len(x) >= 2:
        lower, upper = target < x[0], target > x[-1]
        result[lower] = y[0] + (target[lower] - x[0]) * (y[1] - y[0]) / (x[1] - x[0])
        result[upper] = y[-1] + (target[upper] - x[-1]) * (y[-1] - y[-2]) / (x[-1] - x[-2])
    return ForecastOutput(
        {str(float(q)): float(v) for q, v in zip(target, np.sort(result))},
        None if mean is None else float(mean), "native" if native else "interpolated", None,
    )


def output_from_samples(samples, requested) -> ForecastOutput:
    values = as_numpy(samples).reshape(-1)
    if len(values) < 1000 or not np.all(np.isfinite(values)):
        raise ValueError("samples_must_be_finite_and_at_least_1000")
    levels = checked_levels(requested)
    result = np.quantile(values, levels, method="linear")
    return ForecastOutput(
        {str(float(q)): float(v) for q, v in zip(levels, result)},
        float(np.mean(values)), "sampled", len(values),
    )


def derive_seed(run_date: str, indicator_id: str, entrant_id: str, base_seed: int = 20261008) -> int:
    payload = f"{base_seed}|{run_date}|{indicator_id}|{entrant_id}".encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:4], "big")


def seed_torch(seed: int):
    # Set before a CUDA context is created. Failure of deterministic operations
    # remains a model failure; there is no silent nondeterministic retry.
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    import torch
    torch.set_num_threads(max(1, int(os.environ.get("TSFM_TORCH_THREADS", "4"))))
    random.seed(seed)
    np.random.seed(seed % (2**32))
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.use_deterministic_algorithms(True)
    torch.backends.cudnn.benchmark = False
    return torch


class ModelAdapter:
    kind = "tsfm"

    def __init__(self, config):
        self.config = dict(config)
        self.id = config["id"]
        self.version = f"{config['package']};hf={config['hf_repo']}@{config['hf_revision']}"
        self._model = None
        revision = config.get("hf_revision", "")
        if not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise ValueError("model_requires_pinned_hf_revision")

    def check_package(self):
        name, pinned = self.config["package"].split("==", 1)
        installed = package_version(name)
        if installed != pinned:
            raise RuntimeError(f"package_version_mismatch:{name}:{installed}!={pinned}")

    def hf_kwargs(self):
        return {
            "revision": self.config["hf_revision"],
            "local_files_only": self.config.get("local_files_only", True),
        }

    def device(self, torch):
        requested = self.config.get("device", "cpu")
        return ("cuda" if torch.cuda.is_available() else "cpu") if requested == "auto" else requested
