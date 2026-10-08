"""Bounded ingestion and private reproducibility cache outside the public repository."""
from datetime import timedelta
from pathlib import Path

from .sources import get_source


def ingest(indicators, run_ts, cache_dir: Path):
    histories, health = {}, []
    for cfg in indicators:
        if not cfg["enabled"]:
            health.append({"id": cfg["id"], "status": "disabled", "reason": cfg.get("disabled_reason")})
            continue
        source = None
        try:
            source = get_source(cfg, cache_dir)
            history = source.fetch_history(cfg, (run_ts - timedelta(days=6 * 366)).date())
            histories[cfg["id"]] = history
            health.append({"id": cfg["id"], "source_id": source.id, "status": "ok",
                           "fingerprint": source.fingerprint(), "rows": len(history),
                           "fetched_ts_utc": history.attrs.get("fetched_ts_utc"),
                           "raw_evidence": [{key: value for key, value in item.items() if key != "raw_file"}
                                            for item in source.raw_evidence]})
        except Exception as exc:
            # Do not echo exception URLs: vendor keys can be embedded in request paths.
            failure = {"id": cfg["id"], "status": "source_error", "error_type": type(exc).__name__}
            if source is not None:
                failure.update(source_id=source.id, fingerprint=source.fingerprint(),
                               raw_evidence=[{key: value for key, value in item.items() if key != "raw_file"}
                                             for item in source.raw_evidence])
            health.append(failure)
    return histories, health
