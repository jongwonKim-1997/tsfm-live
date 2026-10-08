"""Optional OpenTimestamps evidence; a calendar receipt is never called anchored.

Pending proofs and all upgrade attempts live in a private cache. Only a proof
independently verified by the pinned CLI against Bitcoin and the forecast bytes
is appended to the public ledger. This module never publishes Git commits.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import time
import uuid
from datetime import date
from pathlib import Path

from filelock import FileLock

from .ledger import locked_forecasts, validate_ledger

CLIENT_VERSION = "0.7.2"
MAX_PROOF_BYTES = 16 * 1024 * 1024


def _invoke(client, *args, runner=subprocess.run):
    # No shell, no wallet, no indefinite --wait, and no default home-directory cache.
    return runner([str(client), "--no-cache", *map(str, args)], capture_output=True,
                  text=True, timeout=45, check=False)


def _proof_info(client, proof, digest, runner):
    if not proof.is_file() or not 0 < proof.stat().st_size <= MAX_PROOF_BYTES:
        raise ValueError("Missing, empty, or oversized OTS proof")
    info = _invoke(client, "info", proof, runner=runner)
    found = re.search(r"^File sha256 hash: ([0-9a-f]{64})$", info.stdout, re.MULTILINE)
    if info.returncode or not found or found.group(1) != digest:
        raise ValueError("OTS proof does not parse or does not bind the forecast SHA-256")


def _one(root, cache, day, forecast_path, client, runner):
    digest = hashlib.sha256(forecast_path.read_bytes()).hexdigest()
    result = {"run_date": day, "forecasts_sha256": digest, "status": "pending",
              "ots_file": None, "client_version": CLIENT_VERSION}
    state = cache / "ots" / day
    state.mkdir(parents=True, exist_ok=True)
    public = root / "ledger" / "ots" / f"{day}.ots"
    pending = state / "pending.ots"
    # New attempt directories avoid the CLI's .bak overwrite restriction and
    # preserve the last known good proof if a later upgrade is interrupted.
    attempt = state / "attempts" / uuid.uuid4().hex
    attempt.mkdir(parents=True)
    target = attempt / "forecast.json"
    target.write_bytes(forecast_path.read_bytes())
    proof = target.with_suffix(".json.ots")
    if public.exists():
        proof.write_bytes(public.read_bytes())
    elif pending.exists():
        proof.write_bytes(pending.read_bytes())
    else:
        stamped = _invoke(client, "stamp", "--timeout", "10", target, runner=runner)
        if stamped.returncode:
            return {**result, "status": "failed", "reason": "stamp_failed",
                    "returncode": stamped.returncode}
    _proof_info(client, proof, digest, runner)
    if not public.exists():
        # Upgrade can return 1 for an ordinary pending calendar attestation.
        # Neither its exit status nor a block-header label is verification.
        upgraded = _invoke(client, "upgrade", proof, runner=runner)
        result["upgrade_returncode"] = upgraded.returncode
        _proof_info(client, proof, digest, runner)
        temporary = state / f"pending-{uuid.uuid4().hex}.tmp"
        temporary.write_bytes(proof.read_bytes())
        temporary.replace(pending)
    # Disable implicit calendar upgrades during verification: the *saved*
    # proof must suffice. Default mainnet Bitcoin verification remains enabled.
    verified = _invoke(client, "--no-default-whitelist", "verify", "-f", forecast_path,
                       proof, runner=runner)
    if verified.returncode:
        return {**result, "reason": "bitcoin_verification_not_confirmed",
                "verify_returncode": verified.returncode,
                "existing_public_proof": public.exists()}
    if hashlib.sha256(forecast_path.read_bytes()).hexdigest() != digest:
        raise ValueError("Forecast changed during OTS verification")
    if not public.exists():
        public.parent.mkdir(parents=True, exist_ok=True)
        with public.open("xb") as output:
            output.write(proof.read_bytes())
            output.flush()
            os.fsync(output.fileno())
    return {**result, "status": "anchored", "ots_file": public.relative_to(root).as_posix(),
            "proof_sha256": hashlib.sha256(public.read_bytes()).hexdigest(),
            "publication": "local_append_pending_git_publication"}


def process_ots(root: Path, cache: Path, run_date: str | None = None, *, client=None,
                runner=subprocess.run, timeout_seconds=90):
    """Stamp/upgrade eligible live files only; return explicit per-file evidence.

    The caller may invoke this after lock-in or on later runs. Pending/unavailable
    OTS does not replace or change the forecast publication receipt or deadline.
    No synthetic, historical dry-run, all-void, or unreceipted input is stamped.
    """
    root, cache = Path(root).resolve(), Path(cache).resolve()
    if os.environ.get("TSFM_OTS_ENABLED", "1") == "0":
        return {"status": "disabled", "records": []}
    if timeout_seconds <= 0:
        raise ValueError("OTS timeout must be positive")
    deadline = time.monotonic() + timeout_seconds

    def bounded_runner(command, **kwargs):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(command, timeout_seconds)
        kwargs["timeout"] = min(kwargs.get("timeout", 45), remaining)
        return runner(command, **kwargs)
    if cache == root or root in cache.parents:
        raise ValueError("OTS pending cache must be outside the public repository")
    selected_day = date.fromisoformat(run_date).isoformat() if run_date else None
    validate_ledger(root)
    eligible = [(p, f) for p, f in locked_forecasts(root)
                if (selected_day is None or f["run_date"] == selected_day)
                and any(r["status"] == "ok" for r in f["records"])]
    eligible.sort(key=lambda item: item[1]["run_date"], reverse=True)
    if not eligible:
        return {"status": "not_eligible", "records": [], "reason": "no_timely_live_receipt"}
    client = client or os.environ.get("TSFM_OTS_EXECUTABLE") or shutil.which("ots")
    if not client:
        return {"status": "unavailable", "records": [], "reason": "ots_client_not_installed"}
    try:
        version = _invoke(client, "--version", runner=bounded_runner)
        if version.returncode:
            return {"status": "unavailable", "records": [], "reason": "ots_client_start_failed"}
        if version.stdout.strip() != f"v{CLIENT_VERSION}":
            return {"status": "unavailable", "records": [], "reason": "ots_client_version_mismatch",
                    "required_version": CLIENT_VERSION}
    except (OSError, subprocess.TimeoutExpired):
        return {"status": "unavailable", "records": [], "reason": "ots_client_unavailable"}
    cache.mkdir(parents=True, exist_ok=True)
    records = []
    with FileLock(str(cache / "ots.lock"), timeout=0):
        for path, document in eligible:
            if time.monotonic() >= deadline:
                records.append({"run_date": document["run_date"], "status": "pending",
                                "ots_file": None, "reason": "deferred_by_time_budget"})
                continue
            try:
                records.append(_one(root, cache, document["run_date"], path, client, bounded_runner))
            except (OSError, subprocess.TimeoutExpired, ValueError) as error:
                # Do not emit RPC credentials or other CLI output into public logs.
                records.append({"run_date": document["run_date"], "status": "failed",
                                "ots_file": None, "reason": type(error).__name__})
    status = ("anchored" if all(r["status"] == "anchored" for r in records)
              else "failed" if any(r["status"] == "failed" for r in records) else "pending")
    return {"status": status, "records": records}
