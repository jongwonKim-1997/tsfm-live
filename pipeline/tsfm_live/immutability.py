"""CI guard: old ledger files and hash-index prefixes cannot change."""
from __future__ import annotations

import subprocess
from pathlib import Path

PROTECTED = ("forecasts/", "actuals/", "scores/", "manifests/", "corrections/", "snapshots/", "ots/")


def hash_append_only(old: bytes, new: bytes):
    return new.startswith(old) and (not old or old.endswith(b"\n") or new == old)


def check_diff(root: Path, base: str, head="HEAD"):
    def git(*args):
        return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True).stdout
    names = git("diff", "--no-renames", "--diff-filter=MD", "--name-only", base, head, "--", "ledger/")
    errors = [name for name in names.decode().splitlines()
              if name.removeprefix("ledger/").startswith(PROTECTED)]
    try:
        old = git("show", f"{base}:ledger/HASHES.md")
    except subprocess.CalledProcessError:
        old = b""
    try:
        new = git("show", f"{head}:ledger/HASHES.md")
    except subprocess.CalledProcessError:
        new = b""
    if not hash_append_only(old, new):
        errors.append("ledger/HASHES.md: existing bytes changed")
    if errors:
        raise ValueError("Immutable ledger changed: " + ", ".join(errors))
    return True
