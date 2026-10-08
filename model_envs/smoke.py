"""Reproducible adapter validation on synthetic context, never live ledger data.

Run using the chosen model profile's Python. Cached/offline by default; add
--warm-cache to download only the exact configured model repository revision.
"""
import argparse
import hashlib
import json
import os
import platform
import sys
import time
import traceback
from contextlib import redirect_stdout
from dataclasses import asdict
from datetime import datetime, timezone
from importlib.metadata import distributions
from pathlib import Path


def peak_rss_mib():
    if os.name != "nt":
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    import ctypes
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in ["PeakWorkingSetSize", "WorkingSetSize",
            "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
            "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage"]]
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    process = ctypes.windll.kernel32.GetCurrentProcess
    process.restype = wintypes.HANDLE
    get_info = ctypes.windll.psapi.GetProcessMemoryInfo
    get_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    get_info.restype = wintypes.BOOL
    return counters.PeakWorkingSetSize / 1024**2 if get_info(process(), ctypes.byref(counters), counters.cb) else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model")
    parser.add_argument("--cache-dir", required=True, type=Path)
    parser.add_argument("--report-dir", required=True, type=Path)
    parser.add_argument("--warm-cache", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.report_dir.resolve() == (root / "ledger").resolve() or (root / "ledger").resolve() in args.report_dir.resolve().parents:
        parser.error("Synthetic validation reports must never be written to ledger/.")
    sys.path.insert(0, str(root / "pipeline"))
    os.environ["HF_HOME"] = str(args.cache_dir.resolve())
    os.environ["HF_HUB_DISABLE_XET"] = "1"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    os.environ["TSFM_TORCH_THREADS"] = "4"
    os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"
    if args.warm_cache:
        os.environ.pop("HF_HUB_OFFLINE", None)
        os.environ.pop("TRANSFORMERS_OFFLINE", None)
    else:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
    import numpy as np
    from tsfm_live.config.settings import QUANTILES, SEED
    from tsfm_live.models import create_entrant, load_models
    cfg = next(x for x in load_models() if x["id"] == args.model)
    result = {"model": args.model, "runtime_verified": False,
              "purpose": "synthetic-context validation, not live or financial evaluation",
              "executed_at_utc": datetime.now(timezone.utc).isoformat(),
              "package": cfg["package"], "hf_repo": cfg["hf_repo"], "hf_revision": cfg["hf_revision"],
              "python": platform.python_version(), "platform": platform.platform(),
              "device": "cpu", "threads": 4, "context_len": 512, "seed": SEED,
              "installed_packages": sorted(f"{x.metadata['Name']}=={x.version}" for x in distributions())}
    try:
        if args.warm_cache:
            from huggingface_hub import snapshot_download
            t = time.perf_counter()
            snapshot_download(repo_id=cfg["hf_repo"], revision=cfg["hf_revision"],
                              allow_patterns=["*.safetensors", "*.json", "*.py", "model.ckpt"], max_workers=1)
            result["warmup_download_seconds"] = time.perf_counter() - t
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        cfg = dict(cfg, device="cpu", local_files_only=True)
        rng = np.random.default_rng(SEED)
        context = rng.normal(0, .8, 512) + .2 * np.sin(np.arange(512) / 9)
        result["context_sha256"] = hashlib.sha256(context.astype("<f8").tobytes()).hexdigest()
        with redirect_stdout(sys.stderr):
            adapter = create_entrant(cfg)
            import torch
            torch.set_num_threads(4)
            t = time.perf_counter()
            first = adapter.predict(context, QUANTILES, SEED)
            result["cold_adapter_seconds"] = time.perf_counter() - t
            t = time.perf_counter()
            second = adapter.predict(context, QUANTILES, SEED)
            result["warm_adapter_seconds"] = time.perf_counter() - t
        result["deterministic_replay_exact"] = asdict(first) == asdict(second)
        if not result["deterministic_replay_exact"] or len(first.quantiles) != 13:
            raise AssertionError("Output grid/replay validation failed")
        result["output"] = asdict(first)
        result["peak_process_rss_mb"] = peak_rss_mib()
        result["runtime_verified"] = True
    except Exception as exc:  # noqa: BLE001 - report model failures without fabricated replacement
        result["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc(file=sys.stderr)
    args.report_dir.mkdir(parents=True, exist_ok=True)
    report = args.report_dir / f"{args.model}.json"
    report.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"ok": result["runtime_verified"], "report": str(report.resolve())}))
    return 0 if result["runtime_verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
