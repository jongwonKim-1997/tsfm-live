"""Cloud Run wrapper: persistent data, exclusive lease, pinned code and cache.

Does not install packages or download model weights. Cloud resources and secrets
must be provisioned explicitly before use. The pipeline owns lock-in deadlines.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
from urllib.parse import quote
from zoneinfo import ZoneInfo

import requests


def run(*args, cwd=None):
    subprocess.run(list(args), cwd=cwd, check=True)


def log(event, **fields):
    print(json.dumps({"event": event, "timestamp": datetime.now(timezone.utc).isoformat(), **fields}), flush=True)


def metadata_token():
    response = requests.get(
        "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",
        headers={"Metadata-Flavor": "Google"}, timeout=10,
    )
    response.raise_for_status()
    return response.json()["access_token"]


def lease(acquire, generation=None):
    bucket = os.environ["TSFM_DATA_BUCKET"]
    token = metadata_token()
    headers = {"Authorization": f"Bearer {token}"}
    if acquire:
        response = requests.post(
            f"https://storage.googleapis.com/upload/storage/v1/b/{quote(bucket, safe='')}/o",
            params={"uploadType": "media", "name": "locks/active.json", "ifGenerationMatch": "0"},
            headers={**headers, "Content-Type": "application/json"},
            data=json.dumps({"execution": os.environ.get("CLOUD_RUN_EXECUTION"),
                             "created_utc": datetime.now(timezone.utc).isoformat()}), timeout=30,
        )
        if response.status_code == 412:
            raise RuntimeError("Another run or a stale lease exists; inspect the execution before releasing it")
        response.raise_for_status()
        return response.json()["generation"]
    response = requests.delete(
        f"https://storage.googleapis.com/storage/v1/b/{quote(bucket, safe='')}/o/locks%2Factive.json",
        params={"ifGenerationMatch": generation}, headers=headers, timeout=30,
    )
    response.raise_for_status()


def restore_models(destination):
    relative = Path(os.environ["TSFM_CACHE_BUNDLE_OBJECT"])
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("cache bundle must be a relative object name")
    source = Path("/durable-models") / relative
    expected = os.environ["TSFM_CACHE_BUNDLE_SHA256"]
    if not re.fullmatch(r"[a-f0-9]{64}", expected):
        raise ValueError("cache bundle requires a pinned SHA-256")
    local = Path("/scratch/model-cache.tar.gz")
    digest = hashlib.sha256()
    with source.open("rb") as src, local.open("wb") as dst:
        for chunk in iter(lambda: src.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
            dst.write(chunk)
    if digest.hexdigest() != expected:
        raise ValueError("model cache bundle checksum mismatch")
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(local, "r:gz") as archive:
        members = archive.getmembers()
        if sum(member.size for member in members) > 22 * 1024 ** 3:
            raise ValueError("model bundle exceeds the reviewed 22GiB extraction budget")
        archive.extractall(destination, members=members, filter="data")
    local.unlink()


def persist_cache(source, destination):
    """Copy completed cache files without rewriting identical raw evidence."""
    for path in source.rglob("*"):
        if not path.is_file() or path.is_symlink() or path.suffix in {".lock", ".tmp"}:
            continue
        relative = path.relative_to(source)
        if relative.parts[0] == "lockin-receipts":
            # This subtree writes directly to durable storage during publication.
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            with path.open("rb") as left, target.open("rb") as right:
                same = hashlib.file_digest(left, "sha256").digest() == hashlib.file_digest(right, "sha256").digest()
            if same:
                continue
            if relative.parts[0] == "raw":
                raise ValueError("private raw evidence collision")
        shutil.copyfile(path, target)


def prepare_runtime_cache(cache, durable):
    """Restore ordinary cache; receipts reach the private mount immediately.

    Called only while holding the exclusive GCS object-generation lease. No
    user-supplied receipt path/import is accepted. A closed receipt write no
    longer depends on the wrapper's finally block running after publication.
    """
    if durable.exists():
        shutil.copytree(durable, cache, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("lockin-receipts"))
    cache.mkdir(parents=True, exist_ok=True)
    destination = durable / "lockin-receipts"
    destination.mkdir(parents=True, exist_ok=True)
    link = cache / "lockin-receipts"
    if link.exists() or link.is_symlink():
        raise RuntimeError("fresh local receipt link required")
    link.symlink_to(destination.resolve(), target_is_directory=True)


def main():
    if os.environ.get("TSFM_LIVE_ENABLED") != "1":
        raise RuntimeError("Live execution is disabled; complete staging and enable it explicitly")
    repository = os.environ["TSFM_REPOSITORY_URL"].removesuffix(".git")
    if not re.fullmatch(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("TSFM_REPOSITORY_URL must be a public GitHub HTTPS repository URL")
    expected_revision = os.environ["TSFM_CODE_REVISION"]
    if not re.fullmatch(r"[a-f0-9]{40}", expected_revision):
        raise ValueError("container must record its full source commit")
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    log("job_start", run_date=now.date().isoformat(), actual_start_ts=now.isoformat(),
        scheduled_ts=now.replace(hour=8, minute=10, second=0, microsecond=0).isoformat())
    generation = lease(True)
    worktree = Path("/scratch/repo")
    cache = Path(os.environ["TSFM_CACHE_DIR"])
    durable = Path("/durable-raw/cache")
    try:
        if worktree.exists():
            raise RuntimeError("fresh ephemeral checkout required")
        run("git", "clone", "--branch", "main", repository, str(worktree))
        run("git", "merge-base", "--is-ancestor", expected_revision, "HEAD", cwd=worktree)
        run("git", "diff", "--exit-code", expected_revision, "HEAD", "--", "pipeline", "model_envs",
            "ops", "site/package.json", "site/package-lock.json", cwd=worktree)
        os.environ["TSFM_REPO_ROOT"] = str(worktree)
        # Authentication stays in environment/credential helper, never in a remote URL.
        os.environ["GH_TOKEN"] = os.environ["GIT_PUSH_TOKEN"]
        run("gh", "auth", "setup-git")
        run("git", "config", "user.name", "tsfm-live-bot", cwd=worktree)
        run("git", "config", "user.email", "tsfm-live-bot@users.noreply.github.com", cwd=worktree)
        prepare_runtime_cache(cache, durable)
        restore_models(Path(os.environ["HF_HOME"]))
        # Runtime packages and card renderer were installed in the immutable image.
        (worktree / "site/node_modules").symlink_to("/app/site/node_modules", target_is_directory=True)
        run("tsfm-live", "doctor", cwd=worktree)
        run("tsfm-live", "run", "--date", now.date().isoformat(), cwd=worktree)
        log("job_complete", run_date=now.date().isoformat())
    except Exception as exc:
        log("job_failure", severity="ERROR", error_type=type(exc).__name__)
        if (worktree / "ledger").exists():
            execution = os.environ.get("CLOUD_RUN_EXECUTION", now.strftime("%Y%m%dT%H%M%S"))
            if not re.fullmatch(r"[A-Za-z0-9_-]+", execution):
                execution = now.strftime("%Y%m%dT%H%M%S")
            recovery = Path("/durable-raw/recovery") / execution
            shutil.copytree(worktree / "ledger", recovery / "ledger", dirs_exist_ok=False)
            log("private_recovery_saved", execution=execution)
        raise
    finally:
        try:
            if cache.exists():
                persist_cache(cache, durable)
        finally:
            lease(False, generation)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - redact credential-bearing startup exceptions at the process boundary.
        log("job_failure", severity="ERROR", error_type=type(exc).__name__)
        raise SystemExit(1) from None
