"""Publication must wait for registered CI and preserve its original deadline."""
import json
import subprocess
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from tsfm_live.ledger import GitPublisher, wait_required_checks


def check(name, bucket="pass"):
    return {"name": name, "bucket": bucket}


@pytest.fixture
def clock(monkeypatch):
    value = [datetime(2026, 10, 7, 23, 40, tzinfo=timezone.utc)]
    monkeypatch.setattr("tsfm_live.ledger.utcnow", lambda: value[0])
    monkeypatch.setattr("tsfm_live.ledger.time.sleep", lambda seconds: value.__setitem__(0, value[0] + timedelta(seconds=seconds)))
    return value


def test_checks_registration_then_pending_then_pass_before_merge(tmp_path, monkeypatch, clock):
    publisher = GitPublisher.__new__(GitPublisher)
    publisher.root = tmp_path
    monkeypatch.setattr("tsfm_live.ledger.commit_paths", lambda *args: "a" * 40)
    git_calls, gh_calls = [], []
    monkeypatch.setattr("tsfm_live.ledger._git", lambda *args, **kwargs: git_calls.append(args))
    states = [None, [check("pipeline"), check("site", "pending")], [check("pipeline"), check("site")]]
    boundary = clock[0] + timedelta(seconds=45)

    def run(args, **kwargs):
        gh_calls.append(args)
        assert 0 < kwargs["timeout"] <= (boundary - clock[0]).total_seconds()
        if args[2] == "create":
            return SimpleNamespace(stdout="https://github.com/example/repo/pull/1\n")
        if args[2] == "checks":
            assert "--required" in args and "--watch" not in args
            state = states.pop(0)
            return SimpleNamespace(returncode=1 if state is None else 0,
                                   stdout=json.dumps(state), stderr="no checks reported" if state is None else "")
        assert args[2] == "merge" and args[-2:] == ["--match-head-commit", "a" * 40]
        assert states == []
        return SimpleNamespace(stdout="", returncode=0)

    monkeypatch.setattr("tsfm_live.ledger.subprocess.run", run)
    receipt = publisher.publish([], "test", boundary)
    assert receipt["commit"] == "a" * 40
    assert sum(c[2] == "checks" for c in gh_calls) == 3
    assert git_calls[-1][-3:] == ("--is-ancestor", "a" * 40, "origin/main")


@pytest.mark.parametrize("state", [[], [check("pipeline")], [check("site")], [check("unrelated")]])
def test_missing_required_names_never_pass_even_if_reported_checks_green(tmp_path, monkeypatch, clock, state):
    boundary = clock[0] + timedelta(seconds=12)
    monkeypatch.setattr("tsfm_live.ledger.subprocess.run", lambda *a, **k:
                        SimpleNamespace(returncode=0, stdout=json.dumps(state), stderr=""))
    with pytest.raises(TimeoutError):
        wait_required_checks(tmp_path, "pr", boundary)
    assert clock[0] == boundary


def test_no_branch_requirements_waits_only_until_absolute_deadline(tmp_path, monkeypatch, clock):
    boundary = clock[0] + timedelta(seconds=7)
    monkeypatch.setattr("tsfm_live.ledger.subprocess.run", lambda *a, **k:
                        SimpleNamespace(returncode=1, stdout="", stderr="no required checks reported on branch"))
    with pytest.raises(TimeoutError):
        wait_required_checks(tmp_path, "pr", boundary)
    assert clock[0] == boundary


@pytest.mark.parametrize("bucket", ["fail", "cancel", "skipping", "unknown"])
def test_required_terminal_failure_is_immediate(tmp_path, monkeypatch, clock, bucket):
    start = clock[0]
    monkeypatch.setattr("tsfm_live.ledger.subprocess.run", lambda *a, **k:
                        SimpleNamespace(returncode=0, stdout=json.dumps([check("pipeline"), check("site", bucket)]), stderr=""))
    with pytest.raises(ValueError, match="required CI check"):
        wait_required_checks(tmp_path, "pr", start + timedelta(seconds=60))
    assert clock[0] == start


def test_auth_error_is_not_mistaken_for_registration_lag(tmp_path, monkeypatch, clock):
    monkeypatch.setattr("tsfm_live.ledger.subprocess.run", lambda *a, **k:
                        SimpleNamespace(returncode=1, stdout="", stderr="HTTP 401: bad credentials"))
    with pytest.raises(subprocess.CalledProcessError):
        wait_required_checks(tmp_path, "pr", clock[0] + timedelta(seconds=60))
