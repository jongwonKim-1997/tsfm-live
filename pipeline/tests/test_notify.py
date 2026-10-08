from datetime import datetime, timedelta, timezone
import json

import pytest
import requests

from tsfm_live.notify import alert_reasons, notify, notify_build_failure


def manifest(day="2026-10-08", *, deadline=True, delay=0, suffix=""):
    scheduled = datetime.fromisoformat(day).replace(tzinfo=timezone.utc) - timedelta(minutes=50)
    return {"run_id": day + suffix, "run_date": day, "deadline_met": deadline,
            "scheduled_ts": scheduled.isoformat(), "actual_start_ts": (scheduled + timedelta(minutes=delay)).isoformat(),
            "sources": [], "entrants": [], "steps": [], "counts": {}, "mode": "live", "alerts": []}


def test_deadline_frequency_deduplicates_dates_and_excludes_old_future_diagnostics():
    current = manifest(deadline=False)
    history = [manifest("2026-10-07", deadline=False, suffix="-post"), manifest("2026-10-07", deadline=False),
               manifest("2026-09-08", deadline=False), manifest("2026-10-09", deadline=False),
               {**manifest("2026-10-06", deadline=False), "mode": "dry-run"}]
    reasons = alert_reasons(current, history)
    assert "DEADLINE_MISSED_OR_UNCONFIRMED" in reasons
    assert "THREE_DEADLINE_MISSES_IN_30_DAYS" not in reasons
    assert "THREE_DEADLINE_MISSES_IN_30_DAYS" in alert_reasons(current, [*history, manifest("2026-09-09", deadline=False)])


def test_lateness_strictly_over_15_minutes_twice_in_14_distinct_days():
    current = manifest(delay=16)
    duplicate = manifest("2026-10-08", delay=16, suffix="-post")
    assert "SCHEDULER_LATE_TWICE_IN_14_DAYS" not in alert_reasons(current, [duplicate, manifest("2026-10-07", delay=15)])
    assert "SCHEDULER_LATE_TWICE_IN_14_DAYS" not in alert_reasons(current, [manifest("2026-09-24", delay=20)])
    assert "SCHEDULER_LATE_TWICE_IN_14_DAYS" in alert_reasons(current, [manifest("2026-09-25", delay=16)])


def test_latest_post_manifest_wins_over_incomplete_same_date():
    current = manifest()
    early = manifest("2026-10-07", deadline=False)
    final = manifest("2026-10-07", deadline=True, suffix="-post")
    other = [manifest("2026-10-06", deadline=False), manifest("2026-10-05", deadline=False)]
    assert "THREE_DEADLINE_MISSES_IN_30_DAYS" not in alert_reasons(current, [final, early, *other])


def test_source_alert_counts_indicators_not_repeated_source_entries():
    current = manifest()
    current["sources"] = [{"indicator_id": "a", "status": "source_lag"}] * 3
    assert "THREE_SOURCES_UNAVAILABLE" not in alert_reasons(current)
    current["sources"] += [{"indicator_id": "b", "status": "source_error"}, {"indicator_id": "c", "status": "source_lag"}]
    assert "THREE_SOURCES_UNAVAILABLE" in alert_reasons(current)


def test_successful_download_with_stale_observation_still_alerts():
    current = manifest()
    current["sources"] = [{"id": iid, "status": "ok", "forecast_skip_reason": "source_lag"} for iid in "abc"]
    assert "THREE_SOURCES_UNAVAILABLE" in alert_reasons(current)


def test_manual_post_lockin_retries_do_not_count_as_scheduler_lateness():
    current = {**manifest(delay=300), "resumed_after_lockin": True}
    prior = {**manifest("2026-10-07", delay=300), "resumed_after_lockin": True}
    assert "SCHEDULER_LATE_TWICE_IN_14_DAYS" not in alert_reasons(current, [prior])
    # Preserve genuine original starts even when later resume manifests exist.
    history = [prior, manifest("2026-10-07", delay=16), manifest(delay=16)]
    assert "SCHEDULER_LATE_TWICE_IN_14_DAYS" in alert_reasons(current, history)


def test_entrant_all_attempts_fail_while_source_skips_are_excluded():
    current = manifest()
    current["entrants"] = [{"id": "m1"}, {"id": "m2"}, {"id": "m3"}]
    current["entrant_counts"] = {"m1": {"failed": 2, "skipped": 12}, "m2": {"failed": 1, "ok": 1}, "m3": {"skipped": 14}}
    assert alert_reasons(current) == ["ENTRANT_FAILED_ALL_INDICATORS:m1"]


def test_publication_and_build_failures_preserve_explicit_alerts():
    current = manifest()
    current["alerts"] = ["LOCKIN_PUBLICATION_FAILED"]
    current["steps"] = [{"name": "lockin", "status": "failed"}, {"name": "publish_results", "status": "failed"},
                        {"name": "site_build", "status": "failed"}]
    assert alert_reasons(current) == ["LOCKIN_PUBLICATION_FAILED", "PUBLICATION_FAILED", "SITE_BUILD_FAILED"]


def test_unscorable_alert_uses_event_week_kst_and_distinct_indicators():
    current = manifest()
    def record(iid, timestamp):
        return {"indicator_id": iid, "unscorable": "actual_unavailable", "scored_ts_utc": timestamp}
    events = [record("a", "2026-10-01T23:30:00Z"), record("a", "2026-10-07T23:30:00Z"),
              record("b", "2026-10-01T00:00:00Z")]
    assert "ACTUAL_GRACE_EXCEEDED" not in alert_reasons(current, unscorable=events)
    events.append(record("b", "2026-10-01T23:30:00Z"))
    assert "ACTUAL_GRACE_EXCEEDED" in alert_reasons(current, unscorable=events)


def test_no_webhook_or_dry_run_sends_nothing(monkeypatch, tmp_path):
    monkeypatch.delenv("WEBHOOK_URL", raising=False)
    monkeypatch.setattr(requests, "post", lambda *a, **kw: pytest.fail("unexpected external send"))
    assert notify(manifest(), "https://example.test/status", delivery_dir=tmp_path)["sent"] is False
    monkeypatch.setenv("WEBHOOK_URL", "https://hooks.slack.com/services/test")
    assert notify({**manifest(), "mode": "dry-run"}, "https://example.test/status", delivery_dir=tmp_path)["reason"] == "diagnostic_run"


def test_notification_is_once_per_run_and_discord_mentions_disabled(monkeypatch, tmp_path):
    monkeypatch.setenv("WEBHOOK_URL", "https://discord.com/api/webhooks/test")
    calls = []
    class Response:
        def raise_for_status(self):
            pass
    monkeypatch.setattr(requests, "post", lambda *a, **kw: calls.append(kw) or Response())
    current = manifest()
    current["alerts"] = ["SITE_BUILD_FAILED"]
    assert notify(current, "https://example.test/status", delivery_dir=tmp_path)["sent"]
    assert notify({**current, "run_id": current["run_id"] + "-post"}, "https://example.test/status", delivery_dir=tmp_path)["reason"] == "already_attempted"
    assert len(calls) == 1
    assert calls[0]["json"]["content"].startswith("🔴")
    assert calls[0]["json"]["allowed_mentions"] == {"parse": []}


def test_timeout_is_retained_and_not_retried_automatically(monkeypatch, tmp_path):
    monkeypatch.setenv("WEBHOOK_URL", "https://hooks.slack.com/services/test")
    def failed(*args, **kwargs):
        raise requests.Timeout("secret URL must not enter the raised message")
    monkeypatch.setattr(requests, "post", failed)
    with pytest.raises(RuntimeError, match="unconfirmed") as exc:
        notify(manifest(), "https://example.test/status", delivery_dir=tmp_path)
    assert "secret URL" not in str(exc.value)
    result = notify(manifest(), "https://example.test/status", delivery_dir=tmp_path)
    assert result["delivery_status"] == "unconfirmed"
    receipt = json.loads(next(tmp_path.glob("*.json")).read_text())
    assert "test-token" not in str(receipt)


def test_site_build_callback_has_independent_stable_event_id(monkeypatch, tmp_path):
    monkeypatch.setenv("WEBHOOK_URL", "https://hooks.slack.com/services/test")
    calls = []
    class Response:
        def raise_for_status(self):
            pass
    monkeypatch.setattr(requests, "post", lambda *a, **kw: calls.append(kw) or Response())
    assert notify_build_failure("2026-10-08", "build123", "https://pages.example/build123", "https://example.test/status", delivery_dir=tmp_path)["sent"]
    assert not notify_build_failure("2026-10-08", "build123", "https://pages.example/build123", "https://example.test/status", delivery_dir=tmp_path)["sent"]
    assert calls[0]["json"]["text"].startswith("🔴")
    assert "SITE_BUILD_FAILED" in calls[0]["json"]["text"]


def test_unexpected_webhook_host_and_naive_timestamps_rejected(monkeypatch, tmp_path):
    monkeypatch.setenv("WEBHOOK_URL", "https://discord.com.evil.test/webhook")
    with pytest.raises(ValueError, match="official Discord or Slack"):
        notify(manifest(), "https://example.test/status", delivery_dir=tmp_path)
    current = manifest()
    current["actual_start_ts"] = "2026-10-08T00:00:00"
    with pytest.raises(ValueError, match="timezone-aware"):
        alert_reasons(current)
