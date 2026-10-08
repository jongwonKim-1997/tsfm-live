"""Generate all public API views from verified immutable records, never synthetic history."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
from pathlib import Path

from .aggregate import build_aggregates
from .config.settings import constants
from .ledger import append_json, canonical_bytes, iso, locked_forecasts, materialize, parse_ts, read_files, utcnow
from .models import load_models
from .sources import load_indicators
from .transforms import inverse_transform


def export_site(root: Path, *, now=None, write_snapshot=False):
    now = now or utcnow()
    indicators, models = load_indicators(), load_models()
    site_config = json.loads((Path(__file__).parent / "config" / "site.json").read_text(encoding="utf-8"))
    state = materialize(root)
    locked = locked_forecasts(root)
    manifests = [m for _, m in read_files(root, "manifests") if m.get("mode") == "live"]
    manifests.sort(key=lambda m: (parse_ts(m["actual_start_ts"]), m["run_id"]))
    days = sorted({m["run_date"] for m in manifests})
    daily_manifests = {m["run_date"]: m for m in manifests}
    # A failed current attempt must remain visible instead of making yesterday's
    # successful predictions look like today's run.
    as_of = days[-1] if days else None
    snapshots = [s for _, s in read_files(root, "snapshots")]
    for m in models:
        first = next((doc["run_date"] for _, doc in locked
                      if any(r["entrant_id"] == m["id"] and r["status"] == "ok" for r in doc["records"])), None)
        m["live_days"] = sum(d >= first for d in days) if first else 0
    data = build_aggregates(state["scores"], indicators, models, as_of or now.date().isoformat(), snapshots=snapshots)
    public = root / "site" / "public" / "api" / "v1"
    written = []

    def emit(name, body):
        path = public / name
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {**body, "schema_version": "1.0", "as_of": as_of,
                   "generated_ts_utc": iso(now), "licence": "CC BY 4.0"}
        path.write_bytes(canonical_bytes(payload))
        written.append(path)

    configs = {i["id"]: i for i in indicators}
    docs = state["documents"]
    originals = read_files(root, "forecasts")
    for _, document in originals:
        for record in document["records"]:
            if configs[record["indicator_id"]]["display_policy"] == "return_only" and record.get("last_close_value") is not None:
                raise ValueError("Return-only forecast contains a forbidden public level anchor")
    for (iid, _), actual in state["actuals"].items():
        if configs[iid]["display_policy"] == "return_only" and actual.get("value") is not None:
            raise ValueError("Return-only actual contains a forbidden public level")
    latest = {"run_date": None, "records": [], "state": "awaiting_first_lockin", "hash": None,
              "commit": None, "lockin_ts_utc": None, "deadline_met": False, "last_successful_lockin": None}
    locked_days = {doc["run_date"] for _, doc in locked}
    last_successful = None
    distributions = {cfg["id"]: [] for cfg in indicators}
    for path, original in originals:
        doc = docs[str(path.relative_to(root)).replace("\\", "/")]
        day = doc["run_date"]
        candidates = [m for m in manifests if m["run_date"] == day and m.get("forecasts_sha256")]
        if not candidates:
            # An unconfirmed/unindexed local file is not a public lock-in.
            continue
        meta = candidates[-1]
        if hashlib.sha256(path.read_bytes()).hexdigest() != meta["forecasts_sha256"]:
            raise ValueError(f"Ledger hash mismatch: {path}")
        is_locked = day in locked_days
        effective_void = all(r["status"] == "void" for r in doc["records"])
        day_state = "void" if effective_void else "locked" if is_locked else "deadline_missed"
        records = []
        for r in doc["records"]:
            rec = dict(r)
            cfg = configs[r["indicator_id"]]
            if not is_locked and rec["status"] == "ok":
                rec.update(status="void", skip_reason="unconfirmed_or_late_lockin", q={}, mean=None,
                           quantile_method=None, n_samples=None, contributors=[])
            rec["display_policy"] = cfg["display_policy"]
            rec["display_unit"] = "bp" if cfg["target_transform"] == "diff_bp" else "%"
            rec["display_q"] = None
            if cfg["display_policy"] == "level" and r.get("last_close_value") is not None and rec["status"] == "ok":
                rec["display_q"] = {k: inverse_transform(r["last_close_value"], v, r["target_transform"])
                                    for k, v in r["q"].items()}
            records.append(rec)
            if is_locked and rec["status"] == "ok":
                key = (r["indicator_id"], iso(parse_ts(r["next_close_ts"])))
                actual = state["actuals"].get(key)
                levels = rec["display_q"]
                distributions[r["indicator_id"]].append({"run_date": day, "entrant_id": r["entrant_id"],
                    "next_close_ts": iso(parse_ts(r["next_close_ts"])), "target_transform": r["target_transform"],
                    "unit": rec["display_unit"], "q10": r["q"]["0.1"], "q50": r["q"]["0.5"], "q90": r["q"]["0.9"],
                    "actual_y": actual["y"] if actual else None, "display_policy": cfg["display_policy"],
                    "display_unit": cfg.get("unit", "level") if levels else rec["display_unit"],
                    "display_q10": levels["0.1"] if levels else None,
                    "display_q50": levels["0.5"] if levels else None,
                    "display_q90": levels["0.9"] if levels else None,
                    "actual_value": actual.get("value") if levels and actual else None,
                    "corrected": bool(r.get("corrected") or (actual and actual.get("corrected")))})
        enriched = {**doc, "records": records, "state": day_state, "hash": meta["forecasts_sha256"],
                    "commit": meta["forecasts_commit"], "lockin_ts_utc": meta["lockin_ts_utc"], "deadline_met": is_locked,
                    "last_successful_lockin": last_successful}
        emit(f"forecasts/{doc['run_date']}.json", {**original, "hash": meta["forecasts_sha256"]})
        day_scores = [s for s in state["scores"] if s["forecast_run_date"] == doc["run_date"]]
        emit(f"scorecards/{doc['run_date']}.json", {**enriched, "scores": day_scores,
             "actuals": [a for (i, ts), a in state["actuals"].items()
                         if any(r["indicator_id"] == i and r.get("next_close_ts") and
                                iso(parse_ts(r["next_close_ts"])) == ts for r in doc["records"])]})
        if day_state == "locked":
            last_successful = {k: enriched[k] for k in ("run_date", "hash", "commit", "lockin_ts_utc", "deadline_met")}
        if day == as_of:
            latest = enriched
    if as_of and latest["run_date"] != as_of:
        meta = daily_manifests[as_of]
        latest = {"run_date": as_of, "records": [], "state": "failed", "hash": None, "commit": None,
                  "lockin_ts_utc": None, "deadline_met": False, "last_successful_lockin": last_successful}
    emit("latest.json", latest)
    # CSV is another representation of the same committed outputs.
    buffer = io.StringIO(newline="")
    fields = ["indicator_id", "entrant_id", "status", "skip_reason", "target_transform", "next_close_ts"] + [str(q) for q in constants()["QUANTILES"]]
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    for r in latest["records"]:
        writer.writerow({**{k: r.get(k) for k in fields[:6]}, **r.get("q", {})})
    public.mkdir(parents=True, exist_ok=True)
    (public / "latest.csv").write_text(buffer.getvalue(), encoding="utf-8", newline="")
    for window in constants()["WINDOWS"]:
        emit(f"matrix/{window}.json", data["matrices"][window])
        emit(f"leaderboard/{window}.json", data["leaderboards"][window])
    emit("predictability.json", data["predictability"])
    pi = {i["id"] if "id" in i else i["indicator_id"]: i for i in data["predictability"]["indicators"]}
    for cfg in indicators:
        records = [s for s in state["scores"] if s["indicator_id"] == cfg["id"]]
        # Retain all entrants on each of the last 400 distinct indicator sessions.
        keep = set(sorted({s["forecast_run_date"] for s in records})[-400:])
        series = [s for s in records if s["forecast_run_date"] in keep]
        distribution_days = set(sorted({r["run_date"] for r in distributions[cfg["id"]]})[-400:])
        emit(f"indicators/{cfg['id']}.json", {"indicator": cfg, "predictability": pi.get(cfg["id"]),
             "windows": {w: d["regimes"]["all"].get(cfg["id"], {}) for w, d in data["matrices"].items()},
             "window_counts": {w: d["counts"]["all"].get(cfg["id"], {}) for w, d in data["matrices"].items()},
             "series": series, "distributions": [r for r in distributions[cfg["id"]] if r["run_date"] in distribution_days],
             "forecasts": [r for r in latest["records"] if r["indicator_id"] == cfg["id"]]})
    for m in models:
        records = [s for s in state["scores"] if s["entrant_id"] in (m["id"], "volnaive")]
        keep = set(sorted({s["forecast_run_date"] for s in records})[-400:])
        emit(f"models/{m['id']}.json", {"model": m,
             "windows": {w: {i["id"]: d["regimes"]["all"].get(i["id"], {}).get(m["id"]) for i in indicators}
                         for w, d in data["matrices"].items()},
             "window_counts": {w: {i["id"]: d["counts"]["all"].get(i["id"], {}).get(m["id"]) for i in indicators}
                               for w, d in data["matrices"].items()},
             "series": [s for s in records if s["forecast_run_date"] in keep],
             "versions": sorted({r["entrant_version"] for _, doc in locked for r in doc["records"] if r["entrant_id"] == m["id"]})})
    index = [{"date": m["run_date"], "hash": m.get("forecasts_sha256"), "commit": m.get("forecasts_commit"),
              "deadline_met": m["deadline_met"], "lockin_ts_utc": m.get("lockin_ts_utc"), "ots": m.get("ots_file")}
             for m in manifests if m.get("forecasts_sha256")]
    # Repeated post-lockin runs do not duplicate lock-in rows.
    index = list({row["date"]: row for row in index}.values())
    for row in index:
        proof = root / "ledger" / "ots" / f"{row['date']}.ots"
        if proof.is_file():
            # The OTS module appends a public proof only after verification.
            row["ots"] = str(proof.relative_to(root)).replace("\\", "/")
    emit("ledger_index.json", {"lockins": index, "corrections": state["corrections"],
                              "repository_url": os.environ.get("TSFM_REPOSITORY_URL") or site_config.get("repository_url")})
    all_forecasts = [r | {"run_date": doc["run_date"]} for path, doc in docs.items() if "/forecasts/" in path for r in doc["records"]]
    status_dates = set(days[-30:])
    status = {"state": latest["state"] if latest["state"] in {"failed", "void", "deadline_missed"} else "shadow" if manifests else "not_started",
              "latest_state": latest["state"], "last_run": daily_manifests.get(as_of),
              "last_successful_lockin": last_successful,
              "deadline_misses": [daily_manifests[d] for d in days[-90:] if d not in locked_days],
              "skipped": [r for r in all_forecasts if r["run_date"] in status_dates and r["status"] == "skipped"],
              "failed": [r for r in all_forecasts if r["run_date"] in status_dates and r["status"] == "failed"],
              "unscorable": [s for s in state["scores"] if s.get("unscorable")],
              "sources": manifests[-1]["sources"] if manifests else [{"id": i["id"], "status": "configured" if i["enabled"] else "disabled"} for i in indicators],
              "corrections": state["corrections"], "launch_ready": False,
              "requirements": {"required_live_days": 90, "required_consecutive_timely_runs": 14,
                               "observed_live_runs": len(days), "runtime_verified_models": sum(bool(m.get("runtime_verified")) for m in models if m["kind"] == "tsfm")}}
    emit("status.json", status)
    emit("meta.json", {"indicators": indicators, "entrants": models, "constants": constants(),
         "brand_name": site_config["brand_name"], "operator": site_config["operator"],
         "contact": os.environ.get("TSFM_CONTACT_EMAIL") or site_config["contact"],
         "repository_url": os.environ.get("TSFM_REPOSITORY_URL") or site_config.get("repository_url"),
         "public_origin": os.environ.get("TSFM_PUBLIC_ORIGIN") or site_config.get("public_origin"), "code_licence": "Apache-2.0",
         "mode": "shadow", "launch_ready": False})
    if write_snapshot and as_of:
        snapshot_path = root / "ledger" / "snapshots" / as_of[:4] / f"{as_of}.json"
        if not snapshot_path.exists():
            append_json(snapshot_path, {**data["snapshot"], "schema_version": "1.0"}, "snapshots")
    return {"files": len(written), "as_of": as_of,
            "scored_records": sum(not bool(s.get("unscorable")) for s in state["scores"]),
            "unscorable_records": sum(bool(s.get("unscorable")) for s in state["scores"])}
