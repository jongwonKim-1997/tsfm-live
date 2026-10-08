"""Private lock-in recovery never invents or promotes publication evidence."""
import hashlib
import json
import subprocess
from types import SimpleNamespace

import pytest

from tsfm_live.ledger import append_json, read_files
from tsfm_live.receipts import load_receipt, recover_other_receipts, save_receipt
from test_integrity import DAY
from test_ledger import append_fixture, fixture_doc


@pytest.fixture
def checkpoint(tmp_path):
    root, cache = tmp_path / "repository", tmp_path / "private"
    path, _ = append_fixture(root, fixture_doc(root))
    manifest = read_files(root, "manifests")[0][1]
    saved = save_receipt(root, cache, manifest)
    return root, cache, path, manifest, saved


def test_recovery_requires_authentication_remote_ancestry_and_exact_blob(checkpoint, monkeypatch):
    root, cache, path, manifest, saved = checkpoint
    calls = []
    monkeypatch.setattr("tsfm_live.receipts._git", lambda *args, **kwargs: calls.append(args))
    monkeypatch.setattr("tsfm_live.receipts.subprocess.run", lambda *args, **kwargs:
                        SimpleNamespace(stdout=path.read_bytes()))
    recovered = load_receipt(root, cache, path)
    assert recovered["forecasts_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert recovered["deadline_met"] is True
    assert calls[0][1:] == ("fetch", "origin", "main")
    assert calls[1][1:] == ("merge-base", "--is-ancestor", manifest["forecasts_commit"], "origin/main")
    assert save_receipt(root, cache, manifest) == saved


def test_altered_checkpoint_is_rejected_before_network(checkpoint, monkeypatch):
    root, cache, path, manifest, saved = checkpoint
    envelope = json.loads(saved.read_bytes())
    envelope["manifest"]["lockin_ts_utc"] = "2026-10-07T23:20:00Z"
    saved.write_text(json.dumps(envelope), encoding="utf-8")
    monkeypatch.setattr("tsfm_live.receipts._git", lambda *args, **kwargs: pytest.fail("Tampered receipt"))
    with pytest.raises(ValueError, match="authentication"):
        load_receipt(root, cache, path)


def test_partial_checkpoint_and_missing_key_fail_closed(checkpoint):
    root, cache, path, manifest, saved = checkpoint
    original = saved.read_bytes()
    saved.write_bytes(original[:20])
    with pytest.raises(ValueError):
        load_receipt(root, cache, path)
    saved.write_bytes(original)
    (saved.parent / "authentication.key").unlink()
    with pytest.raises(FileNotFoundError):
        load_receipt(root, cache, path)


def test_changed_forecast_rejected_even_with_authentic_receipt(checkpoint, monkeypatch):
    root, cache, path, manifest, saved = checkpoint
    body = json.loads(path.read_bytes())
    body["run_id"] = "different-forecast"
    path.write_text(json.dumps(body), encoding="utf-8")
    monkeypatch.setattr("tsfm_live.receipts._git", lambda *args, **kwargs: pytest.fail("Hash mismatch"))
    with pytest.raises(ValueError, match="bind"):
        load_receipt(root, cache, path)


def test_local_only_commit_or_wrong_committed_bytes_cannot_recover(checkpoint, monkeypatch):
    root, cache, path, manifest, saved = checkpoint

    def unreachable(*args, **kwargs):
        raise subprocess.CalledProcessError(1, ["git", "merge-base"])

    monkeypatch.setattr("tsfm_live.receipts._git", unreachable)
    with pytest.raises(subprocess.CalledProcessError):
        load_receipt(root, cache, path)
    monkeypatch.setattr("tsfm_live.receipts._git", lambda *args, **kwargs: None)
    monkeypatch.setattr("tsfm_live.receipts.subprocess.run", lambda *args, **kwargs:
                        SimpleNamespace(stdout=b"different blob"))
    with pytest.raises(ValueError, match="exact forecast bytes"):
        load_receipt(root, cache, path)


def test_no_checkpoint_is_not_a_receipt_and_public_cache_is_forbidden(tmp_path):
    root, cache = tmp_path / "repository", tmp_path / "private"
    path = root / f"ledger/forecasts/2026/{DAY}.json"
    append_json(path, fixture_doc(root), "forecasts")
    assert load_receipt(root, cache, path) is None
    with pytest.raises(ValueError, match="outside"):
        load_receipt(root, root / "cache", path)


def test_next_day_recovers_original_receipt_without_backfilling(checkpoint, monkeypatch):
    root, cache, path, manifest, saved = checkpoint
    original = path.read_bytes()
    for manifest_path, _ in read_files(root, "manifests"):
        manifest_path.unlink()
    monkeypatch.setattr("tsfm_live.receipts._git", lambda *args, **kwargs: None)
    monkeypatch.setattr("tsfm_live.receipts.subprocess.run", lambda *args, **kwargs:
                        SimpleNamespace(stdout=original))
    assert recover_other_receipts(root, cache, "next-day-run", "2026-10-09") == [DAY]
    assert recover_other_receipts(root, cache, "second-attempt", "2026-10-09") == []
    recovered = read_files(root, "manifests")[0][1]
    assert recovered["run_date"] == DAY
    assert recovered["lockin_ts_utc"] == manifest["lockin_ts_utc"]
    assert path.read_bytes() == original
