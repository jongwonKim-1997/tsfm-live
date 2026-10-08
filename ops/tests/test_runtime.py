"""Infrastructure integrity tests; all network interactions are mocked."""
import hashlib
import importlib.util
import io
import os
from pathlib import Path
import tarfile

import pytest


def load_runtime():
    path = Path(__file__).resolve().parents[1] / "runtime.py"
    spec = importlib.util.spec_from_file_location("ops_runtime", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_preserve_raw_evidence_and_skip_runtime_locks(tmp_path):
    runtime = load_runtime()
    source, dest = tmp_path / "cache", tmp_path / "durable"
    (source / "raw").mkdir(parents=True)
    (source / "raw/body.response").write_bytes(b"source response")
    (source / "pipeline.lock").touch()
    runtime.persist_cache(source, dest)
    target = dest / "raw/body.response"
    os.utime(target, (1000000000, 1000000000))
    runtime.persist_cache(source, dest)
    assert target.stat().st_mtime == 1000000000
    assert not (dest / "pipeline.lock").exists()
    (source / "raw/body.response").write_bytes(b"changed response")
    with pytest.raises(ValueError, match="collision"):
        runtime.persist_cache(source, dest)
    assert target.read_bytes() == b"source response"


def test_gcs_lease_creation_and_release_use_generation_preconditions(monkeypatch):
    runtime = load_runtime()
    monkeypatch.setenv("TSFM_DATA_BUCKET", "private-raw-bucket")
    monkeypatch.setattr(runtime, "metadata_token", lambda: "test-token")
    calls = []

    class Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"generation": "123"}

    def request(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    monkeypatch.setattr(runtime.requests, "post", request)
    monkeypatch.setattr(runtime.requests, "delete", request)
    assert runtime.lease(True) == "123"
    runtime.lease(False, "123")
    assert calls[0][1]["params"]["ifGenerationMatch"] == "0"
    assert calls[1][1]["params"]["ifGenerationMatch"] == "123"
    assert calls[0][1]["params"]["name"] == "locks/active.json"


def test_existing_lease_cannot_be_stolen(monkeypatch):
    runtime = load_runtime()
    monkeypatch.setenv("TSFM_DATA_BUCKET", "private-raw-bucket")
    monkeypatch.setattr(runtime, "metadata_token", lambda: "test-token")
    monkeypatch.setattr(runtime.requests, "post", lambda *args, **kwargs: type("R", (), {"status_code": 412})())
    with pytest.raises(RuntimeError, match="stale lease"):
        runtime.lease(True)


def test_model_bundle_sha_and_safe_extraction(tmp_path, monkeypatch):
    runtime = load_runtime()
    durable = tmp_path / "durable"
    scratch = tmp_path / "scratch"
    durable.mkdir()
    scratch.mkdir()
    bundle = durable / "approved.tar.gz"
    with tarfile.open(bundle, "w:gz") as archive:
        info = tarfile.TarInfo("hub/weights.bin")
        info.size = 3
        archive.addfile(info, io.BytesIO(b"abc"))
    expected = hashlib.sha256(bundle.read_bytes()).hexdigest()
    real_path = runtime.Path

    def mapped_path(value):
        if value == "/durable-models":
            return durable
        if value == "/scratch/model-cache.tar.gz":
            return scratch / "archive.tar.gz"
        return real_path(value)

    monkeypatch.setattr(runtime, "Path", mapped_path)
    monkeypatch.setenv("TSFM_CACHE_BUNDLE_OBJECT", "approved.tar.gz")
    monkeypatch.setenv("TSFM_CACHE_BUNDLE_SHA256", "0" * 64)
    with pytest.raises(ValueError, match="checksum"):
        runtime.restore_models(scratch / "models")
    assert not (scratch / "models").exists()
    monkeypatch.setenv("TSFM_CACHE_BUNDLE_SHA256", expected)
    runtime.restore_models(scratch / "models")
    assert (scratch / "models/hub/weights.bin").read_bytes() == b"abc"


def test_disabled_runtime_never_touches_network(monkeypatch):
    runtime = load_runtime()
    monkeypatch.setenv("TSFM_LIVE_ENABLED", "0")
    monkeypatch.setattr(runtime, "lease", lambda *args: pytest.fail("unexpected lease/network access"))
    with pytest.raises(RuntimeError, match="disabled"):
        runtime.main()


def test_lockin_receipts_reach_durable_storage_without_final_copy(tmp_path):
    runtime = load_runtime()
    durable, cache = tmp_path / "durable", tmp_path / "scratch"
    (durable / "raw").mkdir(parents=True)
    (durable / "raw/source.response").write_bytes(b"original raw evidence")
    (durable / "lockin-receipts").mkdir()
    (durable / "lockin-receipts/prior.json").write_bytes(b"existing receipt")
    try:
        runtime.prepare_runtime_cache(cache, durable)
    except OSError as error:
        if getattr(error, "winerror", None) == 1314:
            pytest.skip("Windows symlink privilege unavailable; exercised in Linux CI")
        raise
    assert (cache / "raw/source.response").read_bytes() == b"original raw evidence"
    assert (cache / "lockin-receipts").is_symlink()
    assert (cache / "lockin-receipts/prior.json").read_bytes() == b"existing receipt"
    (cache / "lockin-receipts/new.json").write_bytes(b"closed new receipt")
    # Simulate termination before persist_cache/finally: receipt already exists.
    assert (durable / "lockin-receipts/new.json").read_bytes() == b"closed new receipt"
    with pytest.raises(RuntimeError, match="fresh local receipt"):
        runtime.prepare_runtime_cache(cache, durable)
