import hashlib
import platform
from collections import Counter

from .ledger import git_head, iso, parse_ts


def make_manifest(root, run_id, run_date, started, scheduled, models, sources, steps, receipt, forecasts,
                  *, dry_run=False, alerts=None):
    entrant_counts = {m["id"]: dict.fromkeys(("ok", "failed", "skipped", "void"), 0) for m in models}
    for record in forecasts.get("records", []):
        counts = entrant_counts.setdefault(record["entrant_id"], dict.fromkeys(("ok", "failed", "skipped", "void"), 0))
        counts[record["status"]] += 1
    reasons = {r["indicator_id"]: r["skip_reason"] for r in forecasts.get("records", [])
               if r.get("skip_reason") in ("source_lag", "source_error")}
    sources = [{**source, **({"forecast_skip_reason": reasons[source["id"]]}
                            if source.get("id") in reasons else {})} for source in sources]
    return {"run_id": run_id, "run_date": run_date, "run_ts_utc": iso(started),
            "scheduled_ts": iso(scheduled), "actual_start_ts": iso(started),
            "code_commit": git_head(root),
            "uv_lock_sha256": hashlib.sha256((root / "pipeline" / "uv.lock").read_bytes()).hexdigest(),
            "python_version": platform.python_version(), "hardware": "cpu (workers report device separately)",
            "entrants": [{"id": m["id"], "version": m.get("package", "builtin"),
                          "hf_revision": m.get("hf_revision"), "device": m.get("device", "cpu")} for m in models],
            "sources": sources, "steps": steps, "lockin_ts_utc": receipt.get("lockin_ts_utc"),
            "deadline_met": receipt.get("deadline_met", False),
            "forecasts_sha256": receipt.get("forecasts_sha256"),
            "forecasts_commit": receipt.get("forecasts_commit"), "ots_file": None,
            "counts": dict(Counter(r["status"] for r in forecasts.get("records", []))),
            "entrant_counts": entrant_counts,
            "resumed_after_lockin": bool(not dry_run and receipt.get("lockin_ts_utc")
                                         and parse_ts(receipt["lockin_ts_utc"]) < started),
            "alerts": alerts or [], "mode": "dry-run" if dry_run else "live"}
