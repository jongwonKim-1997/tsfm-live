"""Configured source registry. Disabled sources never make network requests."""
from __future__ import annotations

from pathlib import Path

import yaml

from .base import SourceError
from ..calendars import as_dict


def load_indicators(path=None) -> list[dict]:
    path = Path(path) if path else Path(__file__).resolve().parents[1] / "config" / "indicators.yaml"
    with path.open(encoding="utf-8") as handle:
        rows = yaml.safe_load(handle)
    if not isinstance(rows, list) or len({row["id"] for row in rows}) != len(rows):
        raise ValueError("indicator configuration must be a list with unique IDs")
    return rows


def get_source(cfg, cache_dir):
    cfg = as_dict(cfg)
    if not cfg.get("enabled", True):
        raise SourceError(f"indicator disabled: {cfg.get('disabled_reason', 'unverified source')}")
    from .binance import BinanceSource
    from .cboe import CboeSource
    from .ecb import ECBSource
    from .ecos import ECOSSource
    from .ustreasury import USTreasurySource

    registry = {cls.id: cls for cls in (BinanceSource, CboeSource, ECBSource, ECOSSource, USTreasurySource)}
    adapter = cfg["source"]["adapter"]
    if adapter not in registry:
        raise SourceError(f"no verified adapter for {adapter}")
    return registry[adapter](cfg, cache_dir)
