"""Collect completed hourly observations and render local zero-shot trajectories.

This dashboard is separate from the fixed-time public benchmark ledger. The
clock is always real; a weekend forecast targets the next actual market session.
Only the chart projection may be copied into the website source directory.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

from filelock import FileLock, Timeout

sys.path.insert(0, str(Path(__file__).resolve().parent))
from daily_local import atomic_json, collect
from local_run import CREDENTIAL_KEYS, prepare, private_path

from tsfm_live.dashboard import build_dashboard
from tsfm_live.ledger import iso, utcnow
from tsfm_live.models import load_models
from tsfm_live.processes import background_process_options
from tsfm_live.sources import load_indicators


def render_report(root, payload_path, output_path):
    node = shutil.which("node")
    if not node:
        raise RuntimeError("node_runtime_missing")
    command = [node, str(root / "site/scripts/render-local-dashboard.mjs"),
               "--input", str(payload_path), "--output", str(output_path)]
    subprocess.run(command, cwd=root / "site", check=True, capture_output=True,
                   text=True, timeout=60, stdin=subprocess.DEVNULL,
                   **background_process_options())


def public_projection(view, indicators):
    """Never export personal-use source values or derived forecasts to the site."""
    if view.get("frequency") != "1h":
        return view
    allowed = {cfg["id"] for cfg in indicators if cfg.get("public_export") is True}
    public = {key: value for key, value in view.items() if key != "indicators"}
    public["indicators"] = [row for row in view["indicators"] if row["id"] in allowed]
    if not public["indicators"]:
        public.update(collection_ts_utc=None, collected_ts_utc=None, forecast_generated_ts_utc=None,
                      empty_reason="public_hourly_source_pending")
    return public


def update_dashboard(root, state_dir, *, clock=utcnow, fetch=None, build=None,
                     runtime_check=lambda: None, render=render_report,
                     observations_only=False, write_site=True, retries=2, frequency="1h",
                     report_output=None, publish=None):
    """Keep an immutable private run and atomically replace the current projection."""
    root, state_dir = Path(root).resolve(), private_path(Path(state_dir), Path(root).resolve())
    if frequency not in {"1h", "1d"}:
        raise ValueError("unsupported_frequency")
    if report_output is not None:
        report_output = private_path(Path(report_output), root)
    state_dir.mkdir(parents=True, exist_ok=True)
    lock = FileLock(state_dir / ".dashboard.lock")
    try:
        lock.acquire(timeout=0)
    except Timeout:
        return {"status": "skipped", "reason": "already_running"}, 0
    started = clock()
    run_id = started.strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid.uuid4().hex[:8]
    report = {"mode": "local_zero_shot", "run_id": run_id,
              "started_ts_utc": iso(started), "public_ledger_eligible": False,
              "published": False, "stages": {}}
    try:
        config_dir = root / "pipeline/tsfm_live/config"
        indicators = load_indicators(config_dir / ("hourly_indicators.yaml" if frequency == "1h" else "indicators.yaml"))
        models = load_models(config_dir / "models.yaml")
        if build is None:
            if frequency == "1h":
                from tsfm_live.hourly_dashboard import build_hourly_dashboard
                build = build_hourly_dashboard
            else:
                build = build_dashboard
        report["frequency"] = frequency
        options = {"now": clock, "attempts": retries}
        if fetch is not None:
            options["fetch"] = fetch
        histories, health = collect(indicators, state_dir / "cache", **options)
        report["sources"] = health
        report["stages"]["collect"] = "partial" if any(
            item["status"] == "source_error" for item in health) else "ok"
        inference_enabled = not observations_only
        if inference_enabled:
            try:
                runtime_check()
            except Exception as exc:
                inference_enabled = False
                report["runtime_error_type"] = type(exc).__name__
        run_dir = state_dir / "runs" / run_id
        view, envelope = build(indicators, models, histories, now=clock(),
                               cache_dir=run_dir / "cache", clock=clock,
                               source_statuses=health, inference_enabled=inference_enabled,
                               disabled_reason="observations_only" if observations_only else "runtime_unavailable")
        if view.get("mode") != "local_zero_shot" or view.get("public_ledger_eligible") is not False:
            raise ValueError("invalid_dashboard_projection")
        report["forecast_counts"] = dict(Counter(
            entrant["availability"] for row in view["indicators"] for entrant in row["entrants"]))
        report["observation_count"] = sum(len(row["history"]["last7days"]) for row in view["indicators"])
        report["stages"]["forecast"] = "ok" if report["forecast_counts"].get("available") else "skipped"
        if any(entrant.get("status") in {"failed", "void"}
               for row in view["indicators"] if row.get("enabled", True)
               for entrant in row["entrants"]):
            report["stages"]["forecast"] = "partial"
        if "runtime_error_type" in report:
            report["stages"]["forecast"] = "failed"
        elif observations_only:
            report["forecast_reason"] = "observations_only"
        if any(row.get("enabled") and row.get("source_status", {}).get("freshness") in {
            "source_lag", "source_error", "source_invalid", "history_gap"} for row in view["indicators"]):
            report["stages"]["collect"] = "partial"
        atomic_json(run_dir / "forecast.json", envelope)
        atomic_json(run_dir / "dashboard.json", view)
        output = state_dir / "reports"
        atomic_json(output / "latest.json", view, replace=True)
        render(root, output / "latest.json", output / "index.html")
        report["stages"]["render"] = "ok"
        if report_output is not None:
            report_output.parent.mkdir(parents=True, exist_ok=True)
            temporary = report_output.with_name(report_output.name + "." + uuid.uuid4().hex + ".tmp")
            temporary.write_bytes((output / "index.html").read_bytes())
            temporary.replace(report_output)
            report["exported_report_path"] = str(report_output)
        if write_site:
            public = public_projection(view, indicators)
            atomic_json(root / "site/public/api/v1/local_dashboard.json", public, replace=True)
            report["site_snapshot_written"] = True
            report["public_indicator_count"] = len(public["indicators"])
        if publish is not None:
            try:
                report["publication"] = publish(public_projection(view, indicators))
                report["published"] = True
                report["stages"]["publish"] = "ok"
            except Exception as exc:
                report["stages"]["publish"] = "failed"
                report["publish_error_type"] = type(exc).__name__
        report["report_path"] = str(output / "index.html")
        report["snapshot_path"] = str(output / "latest.json")
        report["status"] = "partial" if any(value in {"partial", "failed"}
            for value in report["stages"].values()) else "ok"
        return report, 0 if report["status"] == "ok" else 1
    except Exception as exc:
        report.update(status="failed", error_type=type(exc).__name__)
        return report, 1
    finally:
        report["finished_ts_utc"] = iso(clock())
        try:
            atomic_json(state_dir / "attempts" / (run_id + ".json"), report)
            atomic_json(state_dir / "latest-run.json", report, replace=True)
        finally:
            lock.release()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-env-file", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--observations-only", action="store_true")
    parser.add_argument("--no-site", action="store_true")
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--frequency", choices=("1h", "1d"), default="1h")
    parser.add_argument("--report-output", type=Path)
    parser.add_argument("--publish-env-file", type=Path,
                        help="Optional private Cloudflare KV configuration; publishes cleared hourly data only")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    state_dir = args.state_dir or root.parents[1] / ("work/tsfm-hourly-dashboard" if args.frequency == "1h"
                                                  else "work/tsfm-local-dashboard")
    report_output = args.report_output or root.parent / "tsfm-live-dashboard.html"
    original_env = dict(os.environ)
    try:
        state_dir = private_path(state_dir, root)
        if args.check_only:
            preflight, _ = prepare(root, args.runtime_env_file, state_dir / "cache")
            print(json.dumps({"event": "dashboard_preflight_ok", **preflight,
                              "mode": "local_zero_shot", "fixed_benchmark_window": False}))
            return 0
        # Keyless source collection does not depend on model files. A missing
        # model environment is handled after collection, retaining actuals.
        safe_env = {key: value for key, value in original_env.items()
                    if key.upper() not in CREDENTIAL_KEYS and not key.upper().startswith("TSFM_PYTHON_")}
        safe_env.update(TSFM_LIVE_ENABLED="0", TSFM_OTS_ENABLED="0",
                        HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
        os.environ.clear()
        os.environ.update(safe_env)

        def runtime_check():
            _, verified = prepare(root, args.runtime_env_file, state_dir / "cache")
            os.environ.clear()
            os.environ.update(verified)

        print(json.dumps({"event": "dashboard_started", "mode": "local_zero_shot",
                          "observations_only": args.observations_only}), flush=True)
        publisher = None
        if args.publish_env_file:
            from publish_dashboard import publish_dashboard
            publish_file = private_path(args.publish_env_file, root)
            def publisher(view):
                return publish_dashboard(view, root=root, env_file=publish_file)
        report, code = update_dashboard(root, state_dir, runtime_check=runtime_check,
            observations_only=args.observations_only, write_site=not args.no_site,
            frequency=args.frequency, report_output=report_output, publish=publisher)
        print(json.dumps({"event": "dashboard_complete", **report}, ensure_ascii=False), flush=True)
        return code
    except Exception as exc:
        print(json.dumps({"event": "dashboard_failed", "error_type": type(exc).__name__}), flush=True)
        return 1
    finally:
        os.environ.clear()
        os.environ.update(original_env)


if __name__ == "__main__":
    raise SystemExit(main())
