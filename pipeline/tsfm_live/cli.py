"""Operational entrypoints. Historical dates can never create live forecasts."""
from __future__ import annotations

import argparse
import json
import os
import uuid
from datetime import date, datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from filelock import FileLock

from .config.settings import LOCKIN_DEADLINE_LOCAL, RUN_TIME_LOCAL, TZ
from .ledger import (GitPublisher, append_json, canonical_bytes, iso, lock_in, locked_forecasts,
                     read_files, utcnow, validate_ledger, void_forecast)


def project_root():
    return Path(os.environ.get("TSFM_REPO_ROOT", Path(__file__).resolve().parents[2])).resolve()


def log(event, **kwargs):
    print(json.dumps({"ts": iso(utcnow()), "event": event, **kwargs}, default=str), flush=True)


def cache_directory(root):
    path = Path(os.environ.get("TSFM_CACHE_DIR") or root.parents[1] / "work" / "tsfm-live-cache").resolve()
    if path == root or root in path.parents:
        raise ValueError("Raw/model cache must be outside the public repository")
    path.mkdir(parents=True, exist_ok=True)
    return path


def schedule(day):
    tz = ZoneInfo(TZ)
    return tuple(datetime.combine(day, time.fromisoformat(t), tz).astimezone(timezone.utc)
                 for t in (RUN_TIME_LOCAL, LOCKIN_DEADLINE_LOCAL))


def doctor(root):
    from .models import load_models
    from .sources import load_indicators

    models, indicators = load_models(), load_indicators()
    blockers = []
    site_config = json.loads((Path(__file__).parent / "config" / "site.json").read_text(encoding="utf-8"))
    if not (os.environ.get("TSFM_REPOSITORY_URL") or site_config.get("repository_url")):
        blockers.append("public_repository_not_configured")
    if not (os.environ.get("TSFM_CONTACT_EMAIL") or site_config.get("contact")):
        blockers.append("operator_contact_not_configured")
    if not os.environ.get("TSFM_PUBLIC_ORIGIN"):
        blockers.append("site_origin_not_configured")
    ready = []
    for m in models:
        if m["kind"] == "tsfm" and m.get("enabled") and m.get("runtime_verified") and os.environ.get(m.get("worker_env", "")):
            ready.append(m["id"])
    if len(ready) < 6:
        blockers.append("fewer_than_six_validated_tsfm_runtimes")
    return {"launch_ready": not blockers, "blockers": blockers, "enabled_indicators": sum(i["enabled"] for i in indicators),
            "configured_indicators": len(indicators), "validated_runtimes": ready,
            "public_origin": os.environ.get("TSFM_PUBLIC_ORIGIN"), "repo": str(root)}


def run(args, root):
    from .actuals import resolve_actuals
    from .export import export_site
    from .forecast import build_forecasts
    from .ingest import ingest
    from .ledger import materialize
    from .manifest import make_manifest
    from .models import load_models
    from .notify import alert_reasons, notify
    from .receipts import load_receipt, recover_other_receipts, save_receipt
    from .score import score_pending
    from .sources import load_indicators

    actual_start = utcnow()
    today = actual_start.astimezone(ZoneInfo(TZ)).date()
    day = date.fromisoformat(args.as_of or args.date) if (args.as_of or args.date) else today
    scheduled, deadline = schedule(day)
    dry = args.dry_run
    if args.as_of and not dry:
        raise ValueError("--as-of is permitted only with --dry-run")
    if not dry and day != today:
        raise ValueError("Live forecasts cannot be backfilled or future-dated")
    if not dry and os.environ.get("TSFM_LIVE_ENABLED") != "1":
        raise ValueError("Live publication is disabled. Use --dry-run; configure deployment and readiness first.")
    if not dry and doctor(root)["blockers"]:
        raise ValueError("Readiness checks failed: " + ", ".join(doctor(root)["blockers"]))
    if not dry and actual_start < scheduled:
        raise ValueError("Live runs cannot start before the scheduled issue time")
    steps_requested = set(args.step.split(",")) if args.step else None
    valid_steps = {"ingest", "forecast", "lockin", "actuals", "score", "aggregate", "cards"}
    if steps_requested and not steps_requested <= valid_steps:
        raise ValueError("Unknown step")
    if not dry and steps_requested and steps_requested & {"ingest", "forecast", "lockin"}:
        raise ValueError("Critical-path steps run together; omit --step")
    cache = cache_directory(root)
    run_id = actual_start.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    logical_ts = scheduled if dry else actual_start
    run_date = day.isoformat()
    lock_path = cache / "pipeline.lock"
    # A local lock protects this checkout; Cloud Run additionally uses a GCS lease.
    with FileLock(str(lock_path), timeout=0):
        models = load_models()
        # Ensemble must follow all contributing models independent of config order.
        models.sort(key=lambda m: m["kind"] == "ensemble")
        indicators = load_indicators()
        if args.baselines_only:
            if not dry:
                raise ValueError("--baselines-only is a dry-run diagnostic")
            models = [m for m in models if m["kind"] != "tsfm"]
        histories, health = {}, []
        steps, receipt = [], {}

        def stage(name, function):
            began = utcnow()
            log("step_started", step=name, run_id=run_id)
            try:
                result = function()
                steps.append({"name": name, "started": iso(began), "ended": iso(utcnow()), "status": "ok"})
                return result
            except Exception as exc:
                steps.append({"name": name, "started": iso(began), "ended": iso(utcnow()), "status": "failed", "error_type": type(exc).__name__})
                raise

        history_result = stage("ingest", lambda: ingest(indicators, logical_ts, cache))
        histories, health = history_result
        existing = root / "ledger" / "forecasts" / str(day.year) / f"{run_date}.json"
        forecasts = None
        publisher = None if dry else GitPublisher(root)

        def effective_counts_document():
            if not existing.exists():
                return forecasts
            return materialize(root)["documents"][existing.relative_to(root).as_posix()]

        if existing.exists() and not dry:
            forecasts = json.loads(existing.read_bytes())
            receipts = [m for _, m in read_files(root, "manifests") if m["run_date"] == run_date and m.get("lockin_ts_utc")]
            if not receipts:
                recovered = load_receipt(root, cache, existing)
                if recovered is not None:
                    append_json(root / "ledger" / "manifests" / str(day.year) / f"{run_id}-recovered.json",
                                recovered, "manifests")
                    receipts = [recovered]
                    if not recovered["deadline_met"]:
                        void_forecast(root, run_date, "Recovered confirmed publication was late; retain the void outcome.")
                    log("confirmed_receipt_recovered", run_date=run_date)
            if not receipts:
                # A crash with an unconfirmed push cannot safely be promoted by guessing.
                void_forecast(root, run_date, "Existing forecast has no confirmed publication receipt; manual reconciliation required.")
                raise ValueError("Unconfirmed prior lock-in: no new forecasts allowed; reconciliation required")
            receipt = receipts[-1]
            log("resuming_after_lockin", run_date=run_date)
        elif steps_requested and not dry:
            raise ValueError("Post-lockin steps require an existing confirmed lock-in")
        else:
            forecasts = stage("forecast", lambda: build_forecasts(indicators, models, histories, logical_ts,
                       deadline, run_date, run_id, cache, dry_run=dry))
            if not dry:
                try:
                    receipt = stage("lockin", lambda: lock_in(root, forecasts, publisher))
                except Exception:
                    if existing.exists():
                        void_forecast(root, run_date, "Publication failed or no timely receipt was obtained. Fail-closed void.")
                    manifest = make_manifest(root, run_id, run_date, actual_start, scheduled, models, health, steps,
                                             {}, effective_counts_document(), alerts=["LOCKIN_PUBLICATION_FAILED"])
                    append_json(root / "ledger" / "manifests" / str(day.year) / f"{run_id}.json", manifest, "manifests")
                    notify(manifest, (os.environ.get("TSFM_PUBLIC_ORIGIN") or "") + "/status",
                           delivery_dir=cache / "notifications")
                    raise
                # Persist receipt immediately: subsequent retries never reproduce forecasts.
                forecasts = json.loads(existing.read_bytes())
                first_manifest = make_manifest(root, run_id, run_date, actual_start, scheduled, models, health,
                                                steps, receipt, effective_counts_document())
                save_receipt(root, cache, first_manifest)
                append_json(root / "ledger" / "manifests" / str(day.year) / f"{run_id}-lockin.json", first_manifest, "manifests")
        if dry:
            destination = root.parents[1] / "work" / "tsfm-live-dry-run" / run_id
            destination.mkdir(parents=True, exist_ok=False)
            (destination / "forecasts.json").write_bytes(canonical_bytes(forecasts))
            (destination / "manifest.json").write_bytes(canonical_bytes(make_manifest(root, run_id, run_date,
                actual_start, scheduled, models, health, steps, {}, forecasts, dry_run=True)))
            log("dry_run_complete", output=str(destination), live_ledger_written=False,
                counts={s: sum(r["status"] == s for r in forecasts["records"]) for s in ("ok", "skipped", "failed")})
            return

        # Recover earlier dates only after today's critical lock-in path. These
        # are previously published bytes with authenticated receipts, not backfills.
        recovered_days = recover_other_receipts(root, cache, run_id, run_date)
        if recovered_days:
            log("earlier_receipts_recovered", run_dates=recovered_days)
        # Read the effective forecast statuses (including void/disqualification overlays).
        state = materialize(root)
        effective = [(p, state["documents"][str(p.relative_to(root)).replace("\\", "/")]) for p, _ in locked_forecasts(root)]
        actual_path = root / "ledger" / "actuals" / str(day.year) / f"{run_date}.json"
        if not actual_path.exists() and (not steps_requested or "actuals" in steps_requested or "score" in steps_requested):
            actuals = stage("actuals", lambda: resolve_actuals(effective, state["actuals"], histories,
                indicators, health, cache, utcnow()))
            stage("actuals_write", lambda: append_json(actual_path, {"run_date": run_date, "records": actuals}, "actuals"))
        state = materialize(root)
        score_path = root / "ledger" / "scores" / str(day.year) / f"{run_date}.json"
        if not score_path.exists() and (not steps_requested or "score" in steps_requested):
            previous = [r for _, d in read_files(root, "scores") for r in d["records"]]
            scored = stage("score", lambda: score_pending(effective, state["actuals"], previous, utcnow()))
            append_json(score_path, {"run_date": run_date, "records": scored}, "scores")
        # External timestamp evidence is optional and strictly after lock-in.
        # Missing calendars, Bitcoin RPC or native libraries cannot discard a
        # timely forecast receipt or prevent scoring/publishing its results.
        from .ots import process_ots
        ots_started = utcnow()
        try:
            ots_report = process_ots(root, cache, timeout_seconds=90)
        except Exception as error:
            ots_report = {"status": "failed", "records": [], "reason": type(error).__name__}
        steps.append({"name": "ots", "started": iso(ots_started), "ended": iso(utcnow()),
                      "status": ots_report["status"], "details": ots_report})
        current_ots = next((r for r in ots_report["records"] if r["run_date"] == run_date),
                           {"status": "not_eligible" if ots_report["records"] else ots_report["status"]})
        if not steps_requested or "aggregate" in steps_requested:
            stage("aggregate", lambda: export_site(root, write_snapshot=True))
        if not steps_requested or "cards" in steps_requested:
            from .cards import generate_cards
            stage("cards", lambda: generate_cards(root))
        manifest = make_manifest(root, run_id + "-post", run_date, actual_start, scheduled, models, health,
                                 steps, receipt, effective_counts_document())
        manifest["ots_status"] = current_ots["status"]
        manifest["ots_file"] = current_ots.get("ots_file")
        manifest["alerts"] = alert_reasons(manifest, [m for _, m in read_files(root, "manifests")],
            [s for s in state["scores"] if s.get("unscorable")])
        append_json(root / "ledger" / "manifests" / str(day.year) / f"{run_id}-post.json", manifest, "manifests")
        export_site(root)
        validate_ledger(root)
        paths = [p for p in (root / "ledger").rglob("*") if p.is_file()] + [p for p in (root / "site" / "public").rglob("*") if p.is_file()]
        try:
            stage("publish_results", lambda: publisher.publish(paths, f"results({run_date}): append scores and generated views"))
        except Exception:
            failed = make_manifest(root, run_id + "-publication-failed", run_date, actual_start, scheduled,
                                   models, health, steps, receipt, effective_counts_document(),
                                   alerts=["PUBLICATION_FAILED"])
            failed.update(ots_status=current_ots["status"], ots_file=current_ots.get("ots_file"))
            append_json(root / "ledger" / "manifests" / str(day.year) / f"{run_id}-publication-failed.json",
                        failed, "manifests")
            try:
                notify(failed, os.environ["TSFM_PUBLIC_ORIGIN"] + "/status", delivery_dir=cache / "notifications")
            except Exception as notification_error:
                log("notification_failed", error_type=type(notification_error).__name__)
            raise
        notify(manifest, os.environ["TSFM_PUBLIC_ORIGIN"] + "/status", delivery_dir=cache / "notifications")
        log("run_complete", run_date=run_date, deadline_met=receipt.get("deadline_met"))


def main(argv=None):
    parser = argparse.ArgumentParser(prog="tsfm-live")
    parser.add_argument("--root", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("run")
    p.add_argument("--date")
    p.add_argument("--as-of")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--baselines-only", action="store_true")
    p.add_argument("--step")
    sub.add_parser("doctor")
    sub.add_parser("schema")
    sub.add_parser("validate")
    sub.add_parser("export-site")
    sub.add_parser("cards")
    p = sub.add_parser("check-immutability")
    p.add_argument("base")
    p = sub.add_parser("correction")
    p.add_argument("file", type=Path)
    p = sub.add_parser("shadow")
    p.add_argument("--end-date", default=date.today().isoformat())
    p.add_argument("--days", type=int, default=365)
    p = sub.add_parser("ots")
    p.add_argument("--date", help="Eligible live run date; omit to stamp or upgrade all eligible runs")
    args = parser.parse_args(argv)
    root = args.root.resolve() if args.root else project_root()
    try:
        if args.command == "run":
            run(args, root)
        elif args.command == "doctor":
            log("doctor", **doctor(root))
        elif args.command == "schema":
            from .schemas import export_schemas
            export_schemas(root / "ledger" / "schema")
        elif args.command == "validate":
            log("ledger_validated", documents=validate_ledger(root))
        elif args.command == "export-site":
            from .export import export_site
            log("site_exported", **export_site(root))
        elif args.command == "cards":
            from .cards import generate_cards
            generate_cards(root)
        elif args.command == "check-immutability":
            from .immutability import check_diff
            check_diff(root, args.base)
        elif args.command == "correction":
            from .ledger import materialize
            from .schemas import CorrectionFile
            c = CorrectionFile.model_validate_json(args.file.read_bytes())
            if any(s in c.id for s in ("..", "/", "\\")):
                raise ValueError("Unsafe correction id")
            path = root / "ledger" / "corrections" / str(c.created_ts_utc.year) / f"{c.id}.json"
            materialize(root, extra_corrections=[c.model_dump(mode="json")])
            append_json(path, c, "corrections")
            log("correction_appended", path=str(path), publication="pending_review")
        elif args.command == "shadow":
            from .shadow import run_shadow
            report = run_shadow(root, cache_directory(root), date.fromisoformat(args.end_date), args.days)
            log("shadow_completed", days=args.days, mode=report.get("mode", "baseline_calendar_validation"))
        elif args.command == "ots":
            from .ots import process_ots
            report = process_ots(root, cache_directory(root), args.date)
            log("ots_completed", **report)
            if report["status"] == "failed":
                return 1
    except Exception as exc:
        log("error", error_type=type(exc).__name__, message=str(exc) if isinstance(exc, ValueError) else "See local structured step log; no credentials are emitted.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
