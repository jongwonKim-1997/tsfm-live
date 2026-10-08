"""Validated, credential-free local dry-run launcher used by run-local.ps1."""
from __future__ import annotations

import argparse
from datetime import date, datetime
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from zoneinfo import ZoneInfo

import yaml


MODEL_PYTHON = "3.11.17"
CREDENTIAL_KEYS = {
    "GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN",
    "GIT_PUSH_TOKEN", "WEBHOOK_URL", "ECOS_API_KEY", "HF_TOKEN", "HUGGING_FACE_HUB_TOKEN",
}


def private_path(path: Path, root: Path) -> Path:
    resolved = path.expanduser().resolve()
    if resolved == root or root in resolved.parents:
        raise ValueError("Runtime environment and caches must be outside the public repository")
    return resolved


def read_runtime_env(path: Path, allowed: set[str]) -> dict[str, str]:
    """Read literal KEY=VALUE assignments; never source or interpolate shell code."""
    values = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"Invalid runtime assignment at line {number}")
        key, value = (part.strip() for part in line.split("=", 1))
        if key not in allowed:
            raise ValueError(f"Unsupported runtime key at line {number}; only runtime paths/settings are allowed")
        if key in values:
            raise ValueError(f"Duplicate runtime key at line {number}")
        if value[:1] in {"'", '"'}:
            if len(value) < 2 or value[-1] != value[0]:
                raise ValueError(f"Unclosed quote at line {number}")
            value = value[1:-1]
        if not value or "\x00" in value:
            raise ValueError(f"Empty or invalid runtime value at line {number}")
        values[key] = value
    return values


def prepare(root: Path, env_file: Path, cache_dir: Path | None = None,
            as_of: str | None = None, *, today: date | None = None) -> tuple[dict, dict[str, str]]:
    root = root.resolve()
    today = today or datetime.now(ZoneInfo("Asia/Seoul")).date()
    if as_of is not None and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", as_of):
        raise ValueError("--as-of must use YYYY-MM-DD")
    day = date.fromisoformat(as_of) if as_of else today
    if day > today:
        raise ValueError("--as-of must be today or a historical date")
    models = yaml.safe_load((root / "pipeline/tsfm_live/config/models.yaml").read_text(encoding="utf-8"))
    enabled = [model for model in models if model.get("enabled") and model["kind"] == "tsfm"]
    workers = {model["worker_env"] for model in enabled}
    allowed = workers | {"HF_HOME", "HF_HUB_CACHE", "TSFM_TORCH_THREADS", "TSFM_DEVICE"}
    values = read_runtime_env(private_path(env_file, root), allowed)
    if "HF_HOME" not in values:
        raise ValueError("Runtime environment must define HF_HOME for the existing model cache")
    hf_home = private_path(Path(values["HF_HOME"]), root)
    hub = private_path(Path(values.get("HF_HUB_CACHE", str(hf_home / "hub"))), root)
    if not hf_home.is_dir() or not hub.is_dir():
        raise ValueError("HF_HOME/HF_HUB_CACHE does not contain an existing model cache")
    threads = values.get("TSFM_TORCH_THREADS", "4")
    if not threads.isdigit() or not 1 <= int(threads) <= 64:
        raise ValueError("TSFM_TORCH_THREADS must be an integer from 1 through 64")
    if values.get("TSFM_DEVICE", "cpu") != "cpu":
        raise ValueError("The local launcher supports the verified CPU profile only")
    for key in sorted(workers):
        if key not in values:
            raise ValueError(f"Missing enabled model runtime: {key}")
        interpreter = Path(values[key]).expanduser().resolve()
        if not interpreter.is_file():
            raise ValueError(f"Model runtime does not exist: {key}")
        completed = subprocess.run(
            [str(interpreter), "-I", "-c", "import platform; print(platform.python_version())"],
            capture_output=True, text=True, check=True, timeout=30,
        )
        if completed.stdout.strip() != MODEL_PYTHON:
            raise ValueError(f"Model runtime {key} must use Python {MODEL_PYTHON}")
        values[key] = str(interpreter)
    snapshots = []
    for model in enabled:
        if not model.get("runtime_verified"):
            raise ValueError(f"Enabled model lacks recorded runtime verification: {model['id']}")
        revision = model["hf_revision"]
        if not re.fullmatch(r"[a-f0-9]{40}", revision):
            raise ValueError(f"Model revision must be a pinned commit: {model['id']}")
        snapshot = hub / ("models--" + model["hf_repo"].replace("/", "--")) / "snapshots" / revision
        if not snapshot.is_dir():
            raise ValueError(f"Pinned model snapshot missing: {model['id']}@{revision}")
        weights = []
        for path in snapshot.rglob("*"):
            if path.is_symlink() and not path.exists():
                raise ValueError(f"Broken cached model file: {model['id']}")
            if not path.is_file():
                continue
            target = path.resolve(strict=True)
            if not target.is_relative_to(hub):
                raise ValueError(f"Cached model file escapes the private HF hub: {model['id']}")
            if target.stat().st_size == 0:
                raise ValueError(f"Empty cached model file: {model['id']}")
            if path.suffix in {".safetensors", ".bin", ".ckpt", ".pt", ".pth"}:
                weights.append(path)
        if not weights:
            raise ValueError(f"No cached weight files for pinned model: {model['id']}")
        snapshots.append({"id": model["id"], "revision": revision, "weight_files": len(weights)})
    cache = private_path(cache_dir or root.parents[1] / "work/tsfm-live-cache", root)
    child_env = {key: value for key, value in os.environ.items()
                 if key.upper() not in CREDENTIAL_KEYS and not key.upper().startswith("TSFM_PYTHON_")}
    child_env.update(values)
    child_env.update({
        "TSFM_REPO_ROOT": str(root), "TSFM_CACHE_DIR": str(cache), "TSFM_DEVICE": "cpu",
        "TSFM_LIVE_ENABLED": "0", "TSFM_OTS_ENABLED": "0", "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1", "HF_HOME": str(hf_home), "HF_HUB_CACHE": str(hub),
        "TSFM_TORCH_THREADS": threads, "OMP_NUM_THREADS": threads, "MKL_NUM_THREADS": threads,
        "HF_HUB_DISABLE_TELEMETRY": "1", "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1",
    })
    report = {"mode": "local_dry_run", "run_date": day.isoformat(), "timezone": "Asia/Seoul",
              "device": "cpu", "threads": int(threads), "worker_profiles": len(workers),
              "models": snapshots, "cache_dir": str(cache), "live_publication": False}
    return report, child_env


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-env-file", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--as-of")
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    try:
        report, child_env = prepare(root, args.runtime_env_file, args.cache_dir, args.as_of)
        print(json.dumps({"event": "local_preflight_ok", **report}), flush=True)
        if args.check_only:
            return 0
        command = [sys.executable, "-m", "tsfm_live.cli", "--root", str(root),
                   "run", "--dry-run", "--as-of", report["run_date"]]
        return subprocess.run(command, cwd=root, env=child_env, check=False).returncode
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(json.dumps({"event": "local_run_failed", "error_type": type(error).__name__,
                          "message": str(error)}), file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
