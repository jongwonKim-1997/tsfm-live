"""Internal authenticated checkpoints for a confirmed public lock-in.

This is not a receipt-import interface. Only this process creates envelopes in
its private cache; recovery requires authentication, exact forecast bytes, and
the original forecast commit still reachable from the public main branch.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
import subprocess
import uuid

from .ledger import _git, append_json, canonical_bytes, read_files, void_forecast
from .schemas import ForecastFile, ManifestFile


def _directory(root: Path, cache: Path):
    directory = (cache / "lockin-receipts").resolve()
    if directory == root.resolve() or root.resolve() in directory.parents:
        raise ValueError("Receipt checkpoints must remain outside the public repository")
    return directory


def _key(directory: Path, *, create=False):
    path = directory / "authentication.key"
    if create and not path.exists():
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(os.urandom(32))
            stream.flush()
            os.fsync(stream.fileno())
    key = path.read_bytes()
    if len(key) != 32:
        raise ValueError("Invalid private receipt authentication key")
    return key


def save_receipt(root: Path, cache: Path, manifest: dict):
    validated = ManifestFile.model_validate(manifest)
    if validated.mode != "live" or validated.lockin_ts_utc is None:
        raise ValueError("Only confirmed live publication receipts may be checkpointed")
    directory = _directory(root, cache)
    directory.mkdir(parents=True, exist_ok=True)
    key = _key(directory, create=True)
    payload = validated.model_dump(mode="json")
    envelope = {"version": 1, "manifest": payload,
                "hmac_sha256": hmac.digest(key, canonical_bytes(payload), "sha256").hex()}
    encoded = canonical_bytes(envelope)
    destination = directory / f"{validated.run_date.isoformat()}.json"
    if destination.exists():
        if destination.read_bytes() != encoded:
            raise FileExistsError("A different receipt checkpoint already exists")
        return destination
    temporary = directory / f".{uuid.uuid4().hex}.tmp"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    # The caller's pipeline lock/GCS lease serializes receipt creation. Rename
    # publishes only a closed complete envelope; interrupted copies fail HMAC.
    temporary.replace(destination)
    return destination


def load_receipt(root: Path, cache: Path, forecast_path: Path):
    forecast = ForecastFile.model_validate_json(forecast_path.read_bytes())
    directory = _directory(root, cache)
    path = directory / f"{forecast.run_date.isoformat()}.json"
    if not path.exists():
        return None
    if path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError("Oversized receipt checkpoint")
    envelope = json.loads(path.read_bytes())
    if set(envelope) != {"version", "manifest", "hmac_sha256"} or envelope["version"] != 1:
        raise ValueError("Invalid internal receipt envelope")
    expected = hmac.digest(_key(directory), canonical_bytes(envelope["manifest"]), "sha256").hex()
    if not hmac.compare_digest(expected, envelope["hmac_sha256"]):
        raise ValueError("Receipt checkpoint authentication failed")
    manifest = ManifestFile.model_validate(envelope["manifest"])
    digest = hashlib.sha256(forecast_path.read_bytes()).hexdigest()
    if (manifest.mode != "live" or manifest.lockin_ts_utc is None
            or manifest.run_date != forecast.run_date or manifest.forecasts_sha256 != digest
            or manifest.lockin_ts_utc < forecast.run_ts_utc):
        raise ValueError("Receipt checkpoint does not bind the issued forecast")
    # A private checkpoint cannot promote a local-only forecast: independently
    # recheck remote ancestry and the original committed blob before reuse.
    _git(root, "fetch", "origin", "main", timeout=60)
    _git(root, "merge-base", "--is-ancestor", manifest.forecasts_commit, "origin/main", timeout=60)
    relative = forecast_path.relative_to(root).as_posix()
    blob = subprocess.run(["git", "-C", str(root), "show", f"{manifest.forecasts_commit}:{relative}"],
                          check=True, capture_output=True, timeout=60).stdout
    if hashlib.sha256(blob).hexdigest() != digest:
        raise ValueError("Receipt commit does not contain the exact forecast bytes")
    return manifest.model_dump(mode="json")


def recover_other_receipts(root: Path, cache: Path, recovery_id: str, current_day: str):
    """Restore earlier confirmed runs after today's lock-in, never reforecast.

    A crash may last beyond midnight, when live backfill is correctly forbidden.
    Recover only cached receipts for already public forecast files so those runs
    can enter subsequent actual resolution and scoring without a backfill.
    """
    if any(part in recovery_id for part in ("/", "\\", "..")):
        raise ValueError("Unsafe internal recovery identifier")
    confirmed = {m["run_date"] for _, m in read_files(root, "manifests")
                 if m.get("mode") == "live" and m.get("lockin_ts_utc")}
    recovered = []
    for path, forecast in read_files(root, "forecasts"):
        day = forecast["run_date"]
        if day == current_day or day in confirmed:
            continue
        receipt = load_receipt(root, cache, path)
        if receipt is None:
            continue
        append_json(root / "ledger" / "manifests" / day[:4] / f"{recovery_id}-recovered-{day}.json",
                    receipt, "manifests")
        if not receipt["deadline_met"]:
            void_forecast(root, day, "Recovered confirmed publication was late; retain the void outcome.")
        recovered.append(day)
    return recovered
