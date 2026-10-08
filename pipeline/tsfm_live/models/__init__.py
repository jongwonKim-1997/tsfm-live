"""Entrant registry. Importing this package never imports a TSFM framework."""
import json
from pathlib import Path

from .base import ForecastOutput, derive_seed
from .baselines import Baseline, ewma_sigma, regime_flag
from .ensemble import ensemble


def load_models(path=None):
    path = Path(path) if path else Path(__file__).parents[1] / "config" / "models.yaml"
    text = path.read_text(encoding="utf-8")
    try:
        models = json.loads(text)
    except json.JSONDecodeError:
        import yaml
        models = yaml.safe_load(text)
    if not isinstance(models, list) or len({x["id"] for x in models}) != len(models):
        raise ValueError("model_config_must_have_unique_ids")
    return models


def create_entrant(config):
    if hasattr(config, "model_dump"):
        config = config.model_dump()
    if isinstance(config, str):
        config = next(m for m in load_models() if m["id"] == config)
    name = config["id"]
    if name in {"rw0", "volnaive"}:
        return Baseline(name)
    if name == "ensemble-median":
        raise ValueError("ensemble_requires_other_model_outputs")
    from importlib import import_module
    adapters = {
        "chronos-2": ("chronos2", "Chronos2Adapter"),
        "chronos-bolt-base": ("chronos_bolt", "ChronosBoltAdapter"),
        "timesfm-2.5-200m": ("timesfm25", "TimesFMAdapter"),
        "moirai-2.0-r-small": ("moirai2", "Moirai2Adapter"),
        "toto-open-base-1.0": ("toto", "TotoAdapter"),
        "tirex": ("tirex", "TiRexAdapter"),
        "sundial-base-128m": ("sundial", "SundialAdapter"),
    }
    if name not in adapters:
        raise ValueError(f"unsupported_entrant:{name}")
    module, cls = adapters[name]
    return getattr(import_module(f"{__name__}.{module}"), cls)(config)


__all__ = ["ForecastOutput", "load_models", "create_entrant", "derive_seed", "ewma_sigma", "regime_flag", "ensemble"]
