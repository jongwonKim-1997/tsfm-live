"""Refresh official daily actuals, freeze one GPU forecast per Korean day, publish.

With --issue-hourly, inference issues every hour; observations and targets stay daily.
Private model inputs, source receipts and credentials never enter the projection.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

from filelock import FileLock, Timeout

sys.path.insert(0, str(Path(__file__).resolve().parent))
from daily_local import atomic_json
from local_run import private_path, read_runtime_env
from tsfm_live.daily_public import KST, build_daily, indicator_configs, public_models
from tsfm_live.ledger import iso, utcnow
from tsfm_live.models import load_models
from tsfm_live.processes import background_process_options
from tsfm_live.sources import get_source
from tsfm_live.sources.twse_open import TWSEOpenSource


def configure_gpu(root, runtime_file):
    allowed = {"TSFM_PYTHON_DAILY_GPU", "TSFM_PYTHON_TIMER_GPU", "HF_HOME", "HF_HUB_CACHE", "TSFM_TORCH_THREADS"}
    values = read_runtime_env(private_path(runtime_file, root), allowed)
    for key in ("TSFM_PYTHON_DAILY_GPU", "HF_HOME"):
        if key not in values:
            raise ValueError("incomplete_gpu_runtime")
        private_path(Path(values[key]), root)
    # A dedicated runtime never inherits source/publication tokens or CPU profile overrides.
    for key in list(os.environ):
        if any(
            word in key.upper() for word in ("TOKEN", "SECRET", "PASSWORD", "API_KEY")
        ) or key.startswith("TSFM_PYTHON_"):
            del os.environ[key]
    os.environ.update(values)
    os.environ.update(
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
        HF_HUB_DISABLE_IMPLICIT_TOKEN="1",
        HF_HUB_DISABLE_TELEMETRY="1",
        TSFM_DEVICE="cuda",
        TSFM_LIVE_ENABLED="0",
        TSFM_OTS_ENABLED="0",
    )
    script = "import torch,json; assert torch.cuda.is_available(), 'cuda_required'; x=torch.ones(32,device='cuda'); print(json.dumps({'torch':torch.__version__,'device':torch.cuda.get_device_name(0),'cuda_test':float((x*x).sum().cpu())}))"
    result = subprocess.run(
        [values["TSFM_PYTHON_DAILY_GPU"], "-c", script],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
        **background_process_options(),
    )
    return json.loads(result.stdout)


def run(args):
    root = Path(__file__).resolve().parents[1]
    state = private_path(
        args.state_dir or root.parents[1] / "work/tsfm-daily-public", root
    )
    state.mkdir(parents=True, exist_ok=True)
    report = {"started_at": iso(utcnow()), "status": "failed", "published": False}
    try:
        with FileLock(state / ".lock", timeout=0):
            gpu = configure_gpu(root, args.runtime_env_file)
            if args.check_only:
                report.update(status="ok", gpu=gpu)
                print(json.dumps({"event": "gpu_preflight_ok", **gpu}))
                return 0
            configs = indicator_configs()
            histories, source_errors = {}, []
            for cfg in configs:
                try:
                    source = (
                        TWSEOpenSource(cfg, state / "cache")
                        if cfg["source"]["adapter"] == "twse_open"
                        else get_source(cfg, state / "cache")
                    )
                    histories[cfg["id"]] = source.fetch_history(
                        cfg,
                        (
                            utcnow() - timedelta(days=cfg.get("history_days", 3 * 366))
                        ).date(),
                    )
                except Exception as exc:  # noqa: BLE001 -- isolate provider failures; never log response secrets
                    source_errors.append(
                        {"id": cfg["id"], "error_type": type(exc).__name__}
                    )
            now = utcnow()
            models = public_models(
                load_models(root / "pipeline/tsfm_live/config/models.yaml")
            )
            local = now.astimezone(KST)
            if not args.issue_hourly and (local.hour, local.minute) < (8, 10):
                models = []
            view, failures = build_daily(
                configs,
                models,
                histories,
                state,
                now=now,
                save=atomic_json,
                issue_hourly=args.issue_hourly,
            )
            view["runtime"] = gpu
            atomic_json(state / "snapshots" / (view["run_id"] + ".json"), view)
            atomic_json(state / "latest.json", view, replace=True)
            if not args.no_site:
                atomic_json(
                    root / "site/public/api/v1/daily_dashboard.json", view, replace=True
                )
            report.update(
                run_id=view["run_id"],
                issue_frequency=view["issue_frequency"],
                gpu=gpu,
                source_errors=source_errors,
                failures=failures,
                forecast_count=sum(len(r["forecasts"]) for r in view["indicators"]),
                observation_count=sum(len(r["history"]) for r in view["indicators"]),
                status="partial" if failures or source_errors else "ok",
            )
            if args.publish_env_file:
                from publish_daily import publish_daily

                report["publication"] = publish_daily(
                    view, root=root, env_file=args.publish_env_file
                )
                report["published"] = report["publication"]["readback_verified"]
                if not report["published"]:
                    report["status"] = "partial"
    except Timeout:
        report["status"] = "skipped_running"
        return 0
    except Exception as exc:  # noqa: BLE001 -- scheduled runner records a safe failure receipt
        report.update(status="failed", error_type=type(exc).__name__)
    finally:
        report["finished_at"] = iso(utcnow())
        if not args.check_only and report["status"] != "skipped_running":
            atomic_json(state / "latest-run.json", report, replace=True)
        print(json.dumps(report, ensure_ascii=False), flush=True)
    return 0 if report["status"] == "ok" else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-env-file", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--publish-env-file", type=Path)
    parser.add_argument("--no-site", action="store_true")
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument(
        "--issue-hourly",
        action="store_true",
        help="Issue each hour; source observations and prediction targets remain daily",
    )
    args = parser.parse_args(argv)
    original = dict(os.environ)
    try:
        return run(args)
    finally:
        os.environ.clear()
        os.environ.update(original)


if __name__ == "__main__":
    raise SystemExit(main())
