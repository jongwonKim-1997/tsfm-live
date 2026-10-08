"""Protocol boundary tests; all proof bytes below are isolated test doubles.

These tests do not contact a calendar, emulate Bitcoin, or produce public proof
evidence. The external client's cryptographic verification is never reimplemented.
"""
import hashlib
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from tsfm_live.ots import process_ots
from test_integrity import DAY
from test_ledger import append_fixture, fixture_doc


@pytest.fixture
def ledger(tmp_path):
    root = tmp_path / "repository"
    path, _ = append_fixture(root, fixture_doc(root))
    return root, tmp_path / "private", path


class ClientDouble:
    def __init__(self, forecast, *, version="v0.7.2", verify=1, wrong_hash=False, stamp_failure=False):
        self.digest = hashlib.sha256(forecast.read_bytes()).hexdigest()
        self.version, self.verify = version, verify
        self.wrong_hash, self.stamp_failure = wrong_hash, stamp_failure
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append(args)
        assert args[:2] == ["test-client", "--no-cache"]
        assert 0 < kwargs["timeout"] <= 45
        assert kwargs["check"] is False
        code, output = 0, ""
        if "--version" in args:
            output = self.version
        elif "stamp" in args:
            if self.stamp_failure:
                code = 1
            else:
                Path(args[-1] + ".ots").write_bytes(b"TEST DOUBLE ONLY; NOT AN OTS PROOF")
        elif "info" in args:
            output = f"File sha256 hash: {'0' * 64 if self.wrong_hash else self.digest}\nTimestamp:\n"
        elif "upgrade" in args:
            code = 0  # A successful upgrade does not independently prove anchoring.
        elif "verify" in args:
            assert "--no-default-whitelist" in args
            assert args[-3] == "-f"
            code = self.verify
        else:
            raise AssertionError(args)
        return SimpleNamespace(returncode=code, stdout=output, stderr="")


def test_unreceipted_or_empty_ledger_never_contacts_client(tmp_path):
    report = process_ots(tmp_path / "repository", tmp_path / "private", client="test-client",
                         runner=lambda *args, **kwargs: pytest.fail("Must not launch client"))
    assert report["status"] == "not_eligible"


def test_missing_client_and_wrong_version_do_not_stamp(ledger, monkeypatch):
    root, cache, path = ledger
    monkeypatch.delenv("TSFM_OTS_EXECUTABLE", raising=False)
    monkeypatch.setattr("tsfm_live.ots.shutil.which", lambda _: None)
    assert process_ots(root, cache)["status"] == "unavailable"
    double = ClientDouble(path, version="v0.7.1")
    report = process_ots(root, cache, client="test-client", runner=double)
    assert report["reason"] == "ots_client_version_mismatch"
    assert len(double.calls) == 1


def test_successful_stamp_and_upgrade_still_pending_without_verification(ledger):
    root, cache, path = ledger
    original = path.read_bytes()
    double = ClientDouble(path)
    report = process_ots(root, cache, client="test-client", runner=double)
    assert report["status"] == "pending"
    assert report["records"][0]["ots_file"] is None
    assert (cache / "ots" / DAY / "pending.ots").exists()
    assert not (root / "ledger/ots").exists()
    assert path.read_bytes() == original


def test_bad_digest_or_failed_stamp_never_creates_public_proof(ledger):
    root, cache, path = ledger
    for kwargs in [{"wrong_hash": True}, {"stamp_failure": True}]:
        double = ClientDouble(path, **kwargs)
        report = process_ots(root, cache, client="test-client", runner=double)
        assert report["status"] == "failed"
        assert not (root / "ledger/ots").exists()
        assert not any("verify" in c for c in double.calls)


def test_verified_proof_is_append_only_and_repeat_verifies_saved_bytes(ledger):
    root, cache, path = ledger
    double = ClientDouble(path, verify=0)
    report = process_ots(root, cache, client="test-client", runner=double)
    assert report["status"] == "anchored"
    public = root / report["records"][0]["ots_file"]
    original, modified = public.read_bytes(), public.stat().st_mtime_ns
    again = ClientDouble(path, verify=0)
    assert process_ots(root, cache, client="test-client", runner=again)["status"] == "anchored"
    assert public.read_bytes() == original and public.stat().st_mtime_ns == modified
    assert not any("stamp" in c or "upgrade" in c for c in again.calls)
    assert report["records"][0]["publication"] == "local_append_pending_git_publication"


def test_pending_retry_upgrades_without_resubmitting(ledger):
    root, cache, path = ledger
    process_ots(root, cache, client="test-client", runner=ClientDouble(path))
    double = ClientDouble(path, verify=0)
    assert process_ots(root, cache, client="test-client", runner=double)["status"] == "anchored"
    assert any("upgrade" in c for c in double.calls)
    assert not any("stamp" in c for c in double.calls)


def test_timeout_is_reported_without_claiming_proof(ledger):
    root, cache, path = ledger
    double = ClientDouble(path)

    def timeout(args, **kwargs):
        if "--version" in args:
            return double(args, **kwargs)
        raise subprocess.TimeoutExpired(args, kwargs["timeout"])

    report = process_ots(root, cache, client="test-client", runner=timeout)
    assert report["status"] == "failed"
    assert report["records"][0]["reason"] == "TimeoutExpired"
    assert not (root / "ledger/ots").exists()


def test_cache_cannot_be_public_and_disabled_never_runs(ledger, monkeypatch):
    root, cache, path = ledger
    with pytest.raises(ValueError, match="outside"):
        process_ots(root, root / "cache")
    monkeypatch.setenv("TSFM_OTS_ENABLED", "0")
    assert process_ots(root, cache, runner=lambda *a, **k: pytest.fail("Disabled"))["status"] == "disabled"
