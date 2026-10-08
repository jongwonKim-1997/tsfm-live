"""Resolve only already-published outcomes, retaining the issued context's anchor."""
import json
import re
from pathlib import Path

from .eligibility import confirmed_history
from .ledger import iso, parse_ts, sha256
from .transforms import transform


def resolve_actuals(forecasts, existing_actuals, histories, indicators, health, cache_dir: Path, run_ts):
    configs = {i["id"]: i for i in indicators}
    fingerprints = {h["id"]: h for h in health}
    results = []
    run_ts = parse_ts(run_ts)
    seen = {(indicator, iso(parse_ts(close))) for indicator, close in existing_actuals}
    for day, doc in forecasts:
        for f in doc["records"]:
            if f["status"] != "ok" or parse_ts(f["next_close_ts"]) >= run_ts:
                continue
            key = (f["indicator_id"], iso(parse_ts(f["next_close_ts"])))
            if key in seen:
                continue
            history = histories.get(f["indicator_id"])
            if history is None:
                continue
            valid = confirmed_history(history, run_ts)
            row = valid[valid["close_ts"] == parse_ts(f["next_close_ts"])]
            if row.empty:
                continue
            row = row.iloc[-1]
            base = f.get("last_close_value")
            if base is None:
                cache = cache_dir / "contexts" / doc["run_date"] / f"{f['indicator_id']}.json"
                if not cache.exists():
                    continue
                private = json.loads(cache.read_bytes())
                if (private["context_hash"] != f["context_hash"]
                        or sha256(private["context"]) != f["context_hash"]
                        or parse_ts(private["last_close_ts"]) != parse_ts(f["last_close_ts"])):
                    raise ValueError("Private context does not match the issued forecast")
                base = private["last_close_value"]
            cfg = configs[f["indicator_id"]]
            source = fingerprints.get(cfg["id"], {})
            if not re.fullmatch(r"[0-9a-f]{64}", source.get("fingerprint", "")):
                continue
            fetched = history.attrs.get("fetched_ts_utc") or source.get("fetched_ts_utc")
            if not fetched:
                # A logical run clock is not source-retrieval evidence.
                continue
            publication = row.get("published_ts")
            import pandas as pd
            publication = None if pd.isna(publication) else iso(publication.to_pydatetime())
            results.append({"indicator_id": f["indicator_id"], "close_ts": key[1],
                            "value": float(row["value"]) if cfg["display_policy"] == "level" else None,
                            "y": float(transform([base, float(row["value"])], cfg["target_transform"])[0]),
                            "source_id": source.get("source_id", cfg["source"]["adapter"]),
                            "source_fingerprint": source["fingerprint"],
                            "published_ts": publication, "fetched_ts_utc": iso(parse_ts(fetched))})
            seen.add(key)
    return results
