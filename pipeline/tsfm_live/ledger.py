"""Canonical immutable files, public publication receipts, and correction overlays."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import subprocess
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .schemas import SCHEMAS, CorrectionFile

UTC = timezone.utc


def utcnow():
    return datetime.now(UTC)


def iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("Naive timestamps are prohibited")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse_ts(value: str | datetime) -> datetime:
    result = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Naive timestamp")
    return result.astimezone(UTC)


def _normalise(value: Any):
    if hasattr(value, "model_dump"):
        return _normalise(value.model_dump(mode="python"))
    if isinstance(value, datetime):
        return iso(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        if any(not isinstance(k, str) for k in value):
            raise TypeError("Canonical object keys must be strings")
        return {k: _normalise(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalise(v) for v in value]
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Non-finite ledger value")
        # Python JSON uses the shortest round-trip repr of this rounded float.
        return round(value, 6)
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if hasattr(value, "item"):
        return _normalise(value.item())
    raise TypeError(f"Unsupported canonical type: {type(value)}")


def canonical_bytes(obj: Any) -> bytes:
    return json.dumps(_normalise(obj), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha256(obj: Any) -> str:
    return hashlib.sha256(canonical_bytes(obj)).hexdigest()


def append_json(path: Path, obj: Any, kind: str | None = None):
    """Exclusive creation with fsync; existing bytes are never replaced."""
    if kind:
        obj = SCHEMAS[kind].model_validate(obj)
    data = canonical_bytes(obj)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    return hashlib.sha256(data).hexdigest()


def read_files(root: Path, kind: str):
    return [(p, json.loads(p.read_bytes())) for p in sorted((root / "ledger" / kind).glob("*/*.json"))]


def _git(root: Path, *args, timeout=120):
    return subprocess.run(["git", "-C", str(root), *args], check=True, text=True,
                          capture_output=True, timeout=timeout).stdout.strip()


def git_head(root: Path):
    try:
        return _git(root, "rev-parse", "HEAD")
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def commit_paths(root: Path, paths: list[Path], message: str):
    relative = [str(p.relative_to(root)).replace("\\", "/") for p in paths]
    _git(root, "add", "--", *relative)
    # Commit explicitly named paths: never include unrelated staged user changes.
    _git(root, "-c", "user.name=tsfm-live-bot", "-c", "user.email=tsfm-live-bot@users.noreply.github.com",
         "commit", "-m", message, "--", *relative)
    return _git(root, "rev-parse", "HEAD")


class GitPublisher:
    """Publish through required checks using a PR; never bypass branch protection.

    A forecast commit is followed by a hash-index commit referencing its SHA.
    Both reach main via a merge PR. The receipt observes confirmed remote reachability,
    not the author-controlled Git timestamp. Public external timestamps remain separate.
    """

    def __init__(self, root: Path):
        self.root = root.resolve()
        remote = _git(root, "remote", "get-url", "origin")
        if not (remote.startswith("https://github.com/") or remote.startswith("git@github.com:")):
            raise ValueError("A configured GitHub public ledger remote is required")

    def publish(self, paths: list[Path], message: str, deadline: datetime | None = None):
        boundary = deadline if deadline is not None else utcnow() + timedelta(seconds=300)
        publication_timeout(boundary)
        commit = commit_paths(self.root, paths, message)
        branch = f"ledger/{commit[:16]}"
        _git(self.root, "push", "origin", f"HEAD:refs/heads/{branch}", timeout=publication_timeout(boundary))
        body = self.root / ".cache" / f"pr-{commit}.txt"
        body.parent.mkdir(exist_ok=True)
        body.write_text("Append-only scheduled ledger publication. Required integrity and test checks must pass.\n",
                        encoding="utf-8")
        pr = subprocess.run(["gh", "pr", "create", "--base", "main", "--head", branch,
                             "--title", message, "--body-file", str(body)], cwd=self.root,
                            check=True, capture_output=True, text=True,
                            timeout=publication_timeout(boundary)).stdout.strip()
        wait_required_checks(self.root, pr, boundary)
        # Matching HEAD prevents a concurrently changed PR from being merged accidentally.
        subprocess.run(["gh", "pr", "merge", pr, "--merge", "--match-head-commit", commit],
                       cwd=self.root, check=True, capture_output=True, text=True,
                       timeout=publication_timeout(boundary))
        _git(self.root, "fetch", "origin", "main", timeout=publication_timeout(boundary))
        _git(self.root, "merge-base", "--is-ancestor", commit, "origin/main",
             timeout=publication_timeout(boundary))
        # Receipt is deliberately conservative: confirmation can only be later than publication.
        return {"commit": commit, "published_ts": iso(utcnow()), "pull_request": pr}


def publication_timeout(deadline: datetime, maximum=60):
    remaining = (deadline - utcnow()).total_seconds()
    if remaining <= 0:
        raise TimeoutError("Public publication deadline elapsed")
    return min(maximum, remaining)


def wait_required_checks(root: Path, pull_request: str, deadline: datetime):
    """Require both benchmark CI jobs, including during check-registration lag.

    gh --watch exits immediately if the new PR has no checks yet. JSON polling
    distinguishes that ordinary registration delay from a terminal failure and
    refuses to treat absent branch-protection requirements as successful checks.
    """
    expected = {"pipeline", "site"}
    registration_errors = ("no checks reported", "no required checks reported", "no commit found")
    while True:
        command = ["gh", "pr", "checks", pull_request, "--required", "--json", "name,bucket"]
        result = subprocess.run(command, cwd=root, check=False, capture_output=True, text=True,
                                timeout=publication_timeout(deadline))
        if result.returncode:
            if not any(message in result.stderr.lower() for message in registration_errors):
                raise subprocess.CalledProcessError(result.returncode, command)
        else:
            checks = json.loads(result.stdout)
            if not isinstance(checks, list) or any(not isinstance(c, dict) for c in checks):
                raise ValueError("Malformed required-check evidence")
            buckets = {c.get("bucket") for c in checks}
            if buckets - {"pass", "pending"}:
                raise ValueError("A required CI check failed, was cancelled, skipped, or has unknown status")
            if expected <= {c.get("name") for c in checks} and buckets == {"pass"}:
                return
        time.sleep(publication_timeout(deadline, maximum=10))


def lock_in(root: Path, forecasts: dict, publisher: GitPublisher, now=utcnow):
    day = forecasts["run_date"]
    if isinstance(day, date):
        day = day.isoformat()
    # Validate both the date/path and document before creating immutable files.
    day = date.fromisoformat(day).isoformat()
    forecasts = json.loads(canonical_bytes(SCHEMAS["forecasts"].model_validate(forecasts)))
    deadline = parse_ts(forecasts["lockin_deadline_utc"])
    target_closes = [parse_ts(r["next_close_ts"]) for r in forecasts["records"] if r["status"] == "ok"]
    boundary = min([deadline, *target_closes])
    started_at = now()
    initially_void = started_at >= boundary
    if initially_void:
        forecasts = copy.deepcopy(forecasts)
        for r in forecasts["records"]:
            r.update(status="void", skip_reason="deadline_missed" if started_at >= deadline
                     else "target_already_closed")
    path = root / "ledger" / "forecasts" / day[:4] / f"{day}.json"
    hashes = root / "ledger" / "HASHES.md"
    prior = hashes.read_text(encoding="utf-8") if hashes.exists() else "| Date | SHA-256 | Forecast commit | OTS |\n|---|---|---|---|\n"
    if any(line.startswith(f"| {day} |") for line in prior.splitlines()):
        raise FileExistsError(f"Lock-in already indexed: {day}")
    if prior and not prior.endswith("\n"):
        raise ValueError("Hash index must end with a newline before an append")
    if path.exists():
        raise FileExistsError(f"Forecast file already exists: {day}")
    digest = append_json(path, forecasts, "forecasts")
    forecast_commit = commit_paths(root, [path], f"lockin({day}): {digest}")
    # Caller holds the run-level file lock. Prefix preservation is verified in CI.
    with hashes.open("a", encoding="utf-8", newline="\n") as f:
        if not hashes.stat().st_size:
            f.write(prior)
        f.write(f"| {day} | {digest} | {forecast_commit} | pending |\n")
        f.flush()
        os.fsync(f.fileno())
    try:
        receipt = publisher.publish([hashes], f"index({day}): {digest}", boundary)
    except Exception:
        void_forecast(root, day, "Publication failed or its completion could not be confirmed.")
        raise
    timestamp = parse_ts(receipt["published_ts"])
    met = not initially_void and started_at <= timestamp < boundary
    if not met:
        void_forecast(root, day, "Publication was late, after an outcome, or lacks a consistent completion time.")
    return {"forecasts_sha256": digest, "forecasts_commit": forecast_commit,
            "lockin_ts_utc": iso(timestamp), "deadline_met": met, "pull_request": receipt.get("pull_request")}


def void_forecast(root: Path, day: str, reason: str):
    correction_id = f"{day}-void"
    path = root / "ledger" / "corrections" / day[:4] / f"{correction_id}.json"
    correction = {"id": correction_id, "created_ts_utc": iso(utcnow()), "type": "void",
                  "affects": [{"file": f"ledger/forecasts/{day[:4]}/{day}.json", "record_selector": {}}],
                  "reason": reason, "replacement": None, "author": "tsfm-live-bot"}
    if not path.exists():
        append_json(path, correction, "corrections")
    return path


def locked_forecasts(root: Path):
    receipts = {}
    for _, m in read_files(root, "manifests"):
        if m.get("mode") == "live" and m.get("lockin_ts_utc"):
            receipts[m["run_date"]] = m
    out = []
    for path, f in read_files(root, "forecasts"):
        m = receipts.get(f["run_date"])
        if not m or not m.get("deadline_met"):
            continue
        if m["forecasts_sha256"] != hashlib.sha256(path.read_bytes()).hexdigest():
            raise ValueError(f"Ledger hash mismatch: {path}")
        if parse_ts(m["lockin_ts_utc"]) >= parse_ts(f["lockin_deadline_utc"]):
            continue
        published = parse_ts(m["lockin_ts_utc"])
        if published < parse_ts(f["run_ts_utc"]):
            continue
        if any(r["status"] == "ok" and published >= parse_ts(r["next_close_ts"]) for r in f["records"]):
            continue
        out.append((path, f))
    return out


def materialize(root: Path, extra_corrections=None):
    """Read immutable originals and apply appended corrections in chronological order."""
    from .metrics import score_forecast

    documents = {str(p.relative_to(root)).replace("\\", "/"): copy.deepcopy(d)
                 for kind in ("forecasts", "actuals", "scores") for p, d in read_files(root, kind)}
    corrections = [c for _, c in read_files(root, "corrections")] + list(extra_corrections or [])
    if len({c["id"] for c in corrections}) != len(corrections):
        raise ValueError("Duplicate correction id")
    corrections.sort(key=lambda c: (parse_ts(c["created_ts_utc"]), c["id"]))
    corrected_actuals = set()
    level_revisions = set()
    for c in corrections:
        CorrectionFile.model_validate(c)
        for affected in c["affects"]:
            file = affected["file"]
            if file not in documents:
                raise ValueError(f"Correction targets missing ledger document: {file}")
            if "/forecasts/" in file and c["type"] not in ("void", "entrant_disqualified"):
                raise ValueError("Issued model outputs cannot be replaced; void or disqualify them")
            if c["type"] == "actual_revision" and "/actuals/" not in file:
                raise ValueError("actual_revision must target actual records")
            matched = False
            for r in documents[file].get("records", []):
                def equal(key, left, right):
                    return parse_ts(left) == parse_ts(right) if key.endswith("_ts") and left and right else left == right
                if not all(equal(k, r.get(k), v) for k, v in affected["record_selector"].items()):
                    continue
                matched = True
                if c["type"] in ("void", "entrant_disqualified"):
                    r["status"] = "void"
                    r["skip_reason"] = c["type"]
                elif c["replacement"]:
                    # Identity is immutable even through a correction overlay.
                    for key in ("indicator_id", "entrant_id", "forecast_run_date", "close_ts"):
                        if key in c["replacement"] and not equal(key, c["replacement"][key], r.get(key)):
                            raise ValueError("Corrections cannot change record identity")
                    r.update(c["replacement"])
                r["corrected"] = True
                r.setdefault("corrections", []).append(c["id"])
                if "/actuals/" in file:
                    key = (r["indicator_id"], iso(parse_ts(r["close_ts"])))
                    corrected_actuals.add(key)
                    if c.get("replacement") and c["replacement"].get("value") is not None:
                        level_revisions.add(key)
                    elif c.get("replacement") and "y" in c["replacement"]:
                        # A later explicitly supplied transformed actual wins.
                        level_revisions.discard(key)
            if not matched:
                raise ValueError(f"Correction selector matched no records: {c['id']}")
    forecasts = {(d["run_date"], r["indicator_id"], r["entrant_id"]): r
                 for p, d in documents.items() if "/forecasts/" in p for r in d["records"]}
    actuals = {}
    for path, document in documents.items():
        if "/actuals/" not in path:
            continue
        for actual in document["records"]:
            key = (actual["indicator_id"], iso(parse_ts(actual["close_ts"])))
            if key in actuals:
                raise ValueError("Duplicate actual observation across ledger files")
            if actual.get("status") != "void":
                actuals[key] = actual
    # Recompute transformed targets from the originally issued anchor when a
    # public level is revised. A return-only actual needs an explicit y because
    # its level anchor is intentionally absent from the public ledger.
    from .transforms import transform
    for key in level_revisions:
        actual = actuals.get(key)
        if actual is None:
            continue
        matching = [f for f in forecasts.values() if f.get("next_close_ts") and
                    (f["indicator_id"], iso(parse_ts(f["next_close_ts"]))) == key]
        anchors = {(f.get("last_close_value"), f["target_transform"]) for f in matching}
        if actual.get("value") is None or not anchors or any(anchor is None for anchor, _ in anchors):
            raise ValueError("Level revision needs an issued public anchor; supply explicit y for return-only data")
        if len(anchors) != 1:
            raise ValueError("Actual revision has conflicting issued anchors")
        anchor, transform_kind = next(iter(anchors))
        actual["y"] = float(transform([anchor, actual["value"]], transform_kind)[0])
    # Prospective corrections can be validated without appending a bad immutable
    # record. Effective views retain correction metadata outside record schemas.
    from .schemas import ActualRecord, ForecastRecord, ScoreRecord
    record_schemas = {"forecasts": ForecastRecord, "actuals": ActualRecord, "scores": ScoreRecord}
    for document_path, document in documents.items():
        kind = document_path.split("/")[1]
        for record in document["records"]:
            clean = {key: value for key, value in record.items() if key not in {"corrected", "corrections"}}
            if kind != "forecasts":
                clean.pop("status", None)
                clean.pop("skip_reason", None)
            record_schemas[kind].model_validate(clean)
    allowed_days = {f["run_date"] for _, f in locked_forecasts(root)}
    scores = []
    for p, d in documents.items():
        if "/scores/" not in p:
            continue
        for s in d["records"]:
            f = forecasts.get((s["forecast_run_date"], s["indicator_id"], s["entrant_id"]))
            if not f or f["status"] != "ok" or s["forecast_run_date"] not in allowed_days:
                continue
            key = (f["indicator_id"], iso(parse_ts(f["next_close_ts"])))
            if s.get("status") == "void" or (key in corrected_actuals and key not in actuals):
                continue
            if key in corrected_actuals and s.get("unscorable") is None:
                a = actuals[key]
                s.update(score_forecast(a["y"], f["q"], f["target_transform"]))
                s.update(corrected=True, corrections=a["corrections"])
            scores.append(s)
    return {"documents": documents, "forecasts": forecasts, "actuals": actuals,
            "scores": scores, "corrections": corrections}


def validate_ledger(root: Path):
    from jsonschema import validate

    count = 0
    scored = set()
    actual_keys = set()
    for kind, cls in SCHEMAS.items():
        schema = cls.model_json_schema()
        for path, data in read_files(root, kind):
            cls.model_validate(data)
            validate(data, schema)
            if path.read_bytes() != canonical_bytes(data):
                raise ValueError(f"Noncanonical bytes: {path}")
            if kind == "scores":
                for r in data["records"]:
                    key = (r["forecast_run_date"], r["indicator_id"], r["entrant_id"])
                    if key in scored:
                        raise ValueError(f"Duplicate score {key}")
                    scored.add(key)
            if kind == "actuals":
                for r in data["records"]:
                    key = (r["indicator_id"], iso(parse_ts(r["close_ts"])))
                    if key in actual_keys:
                        raise ValueError(f"Duplicate actual {key}")
                    actual_keys.add(key)
            count += 1
    hashes = root / "ledger" / "HASHES.md"
    indexed = set()
    if hashes.exists():
        for line in hashes.read_text(encoding="utf-8").splitlines():
            fields = [s.strip() for s in line.split("|")]
            if len(fields) < 5 or not fields[1][:4].isdigit():
                continue
            day, digest = fields[1:3]
            if day in indexed:
                raise ValueError(f"Duplicate hash date {day}")
            indexed.add(day)
            path = root / "ledger" / "forecasts" / day[:4] / f"{day}.json"
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise ValueError(f"Hash index mismatch {day}")
    return count
