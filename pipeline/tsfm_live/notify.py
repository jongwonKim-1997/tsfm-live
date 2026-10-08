"""Configured operations alerts with bounded, at-most-once delivery attempts.

No destination is invented. HTTP delivery ambiguity is retained for manual
reconciliation rather than automatically sending a possible duplicate.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from filelock import FileLock
import requests

from .config.settings import TZ


def _timestamp(value):
    if not value:
        return None
    result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("notification event timestamps must be timezone-aware")
    return result.astimezone(timezone.utc)


def _day(value):
    return value if isinstance(value, date) and not isinstance(value, datetime) else date.fromisoformat(str(value))


def _manifest_order(manifest):
    times = [_timestamp(manifest.get(field)) for field in ("actual_start_ts", "run_ts_utc", "lockin_ts_utc")]
    times.extend(_timestamp(step.get("ended")) for step in manifest.get("steps", []))
    return (max((value for value in times if value is not None), default=datetime.min.replace(tzinfo=timezone.utc)),
            len(manifest.get("steps", [])), str(manifest.get("run_id", "")).endswith("-post"))


def _daily_manifests(manifest, previous):
    """Latest completed evidence per calendar run date, excluding diagnostics."""
    today = _day(manifest["run_date"])
    grouped = {}
    for item in [*previous, manifest]:
        if item.get("mode", "live") != "live":
            continue
        day = _day(item["run_date"])
        if day > today:
            continue
        if day not in grouped or _manifest_order(item) >= _manifest_order(grouped[day]):
            grouped[day] = item
    return grouped


def alert_reasons(manifest, previous_manifests=(), unscorable=()):
    """Derive run alerts from dated evidence, counting each run date once."""
    if manifest.get("mode", "live") != "live":
        return []
    previous_manifests = list(previous_manifests)
    alerts = list(manifest.get("alerts", []))
    today = _day(manifest["run_date"])
    daily = _daily_manifests(manifest, previous_manifests)
    if manifest.get("deadline_met") is not True:
        alerts.append("DEADLINE_MISSED_OR_UNCONFIRMED")
    misses = sum(item.get("deadline_met") is False for day, item in daily.items()
                 if today - timedelta(days=29) <= day <= today)
    if misses >= 3:
        alerts.append("THREE_DEADLINE_MISSES_IN_30_DAYS")
    first_starts = {}
    for item in [*previous_manifests, manifest]:
        if item.get("mode", "live") != "live" or item.get("resumed_after_lockin"):
            continue
        day = _day(item["run_date"])
        if not today - timedelta(days=13) <= day <= today:
            continue
        start, scheduled = _timestamp(item.get("actual_start_ts")), _timestamp(item.get("scheduled_ts"))
        if start is not None and scheduled is not None and (day not in first_starts or start < first_starts[day][0]):
            first_starts[day] = (start, scheduled)
    late_days = sum((start - scheduled).total_seconds() > 15 * 60 for start, scheduled in first_starts.values())
    if late_days >= 2:
        alerts.append("SCHEDULER_LATE_TWICE_IN_14_DAYS")
    bad_sources = {source.get("indicator_id", source.get("id")) for source in manifest.get("sources", [])
                   if source.get("status") in {"source_lag", "source_error"}
                   or source.get("forecast_skip_reason") in {"source_lag", "source_error"}}
    bad_sources.discard(None)
    if len(bad_sources) >= 3:
        alerts.append("THREE_SOURCES_UNAVAILABLE")
    for entrant in manifest.get("entrants", []):
        counts = entrant.get("counts") or manifest.get("entrant_counts", {}).get(entrant["id"], {})
        if counts.get("failed", 0) > 0 and counts.get("ok", 0) == 0:
            alerts.append(f"ENTRANT_FAILED_ALL_INDICATORS:{entrant['id']}")
    for step in manifest.get("steps", []):
        if step.get("status") not in {"failed", "error"}:
            continue
        if step.get("name") in {"lockin", "publish_results", "push", "publish"}:
            alerts.append("PUBLICATION_FAILED")
        if step.get("name") in {"site_build", "site_deploy"}:
            alerts.append("SITE_BUILD_FAILED")
    if manifest.get("site_build_status") in {"failed", "failure", "error"}:
        alerts.append("SITE_BUILD_FAILED")
    missing = set()
    for record in unscorable:
        if record.get("unscorable") != "actual_unavailable":
            continue
        event = _timestamp(record.get("scored_ts_utc"))
        if event and today - timedelta(days=6) <= event.astimezone(ZoneInfo(TZ)).date() <= today:
            missing.add(record["indicator_id"])
    if len(missing) >= 2:
        alerts.append("ACTUAL_GRACE_EXCEEDED")
    return list(dict.fromkeys(alerts))


def _write_receipt(path, document):
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(document, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _deliver(text, event_id, *, delivery_dir=None):
    url = os.environ.get("WEBHOOK_URL")
    if not url:
        return {"sent": False, "reason": "webhook_not_configured"}
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.username or parsed.password:
        raise ValueError("operations webhook must use HTTPS without URL user credentials")
    discord = parsed.hostname in {"discord.com", "discordapp.com", "canary.discord.com", "ptb.discord.com"}
    slack = parsed.hostname == "hooks.slack.com"
    if not discord and not slack:
        raise ValueError("configured webhook must be an official Discord or Slack endpoint")
    payload = {"content": text[:1900], "allowed_mentions": {"parse": []}} if discord else {"text": text}
    if delivery_dir is None:
        cache = os.environ.get("TSFM_CACHE_DIR")
        delivery_dir = Path(cache) / "notifications" if cache else Path(tempfile.gettempdir()) / "tsfm-live-notifications"
    directory = Path(delivery_dir)
    directory.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(event_id.encode()).hexdigest()
    receipt_path = directory / f"{key}.json"
    with FileLock(str(directory / "delivery.lock"), timeout=5):
        if receipt_path.exists():
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            return {"sent": False, "reason": "already_attempted", "delivery_status": receipt["status"]}
        receipt = {"event_id": event_id, "status": "pending",
                   "created_ts_utc": datetime.now(timezone.utc).isoformat(),
                   "payload_sha256": hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()}
        _write_receipt(receipt_path, receipt)
        try:
            response = requests.post(url, json=payload, timeout=15)
            response.raise_for_status()
        except requests.RequestException:
            receipt["status"] = "unconfirmed"
            _write_receipt(receipt_path, receipt)
            raise RuntimeError("Operations webhook delivery failed or is unconfirmed; inspect before retrying") from None
        receipt["status"] = "sent"
        _write_receipt(receipt_path, receipt)
    return {"sent": True}


def notify(manifest, status_url, *, delivery_dir=None):
    if manifest.get("mode", "live") != "live":
        return {"sent": False, "reason": "diagnostic_run"}
    alerts = manifest.get("alerts", [])
    prefix = "🔴 " if alerts else ""
    text = (f"{prefix}TSFM Live {manifest['run_date']} | deadline met: {manifest.get('deadline_met')} | "
            f"counts: {manifest.get('counts', {})} | hash: {manifest.get('forecasts_sha256')} | "
            f"{', '.join(alerts)} | {status_url}")
    run_id = str(manifest.get("run_id", manifest["run_date"])).removesuffix("-post")
    return _deliver(text, f"run:{run_id}", delivery_dir=delivery_dir)


def notify_build_failure(run_date, build_id, build_url, status_url, *, delivery_dir=None):
    """Authenticated deployment integrations call this with a verified event.

    The caller authenticates/provider-verifies the event before invoking this
    function. This is not an unauthenticated public HTTP endpoint.
    """
    _day(run_date)
    if not build_id:
        raise ValueError("a stable provider build id is required for deduplication")
    text = f"🔴 TSFM Live {run_date} | SITE_BUILD_FAILED | build: {build_id} | {build_url} | {status_url}"
    return _deliver(text, f"site-build:{build_id}", delivery_dir=delivery_dir)
