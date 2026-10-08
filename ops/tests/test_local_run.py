"""Local execution is reproducible, credential-free and always diagnostic."""
from datetime import date
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

import pytest


def load_launcher():
    path = Path(__file__).resolve().parents[1] / "local_run.py"
    spec = importlib.util.spec_from_file_location("local_run", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def local_fixture(tmp_path, monkeypatch):
    module = load_launcher()
    root = tmp_path / "outputs/repo"
    config = root / "pipeline/tsfm_live/config"
    config.mkdir(parents=True)
    revision = "a" * 40
    model = {"id": "model", "kind": "tsfm", "enabled": True, "runtime_verified": True,
             "worker_env": "TSFM_PYTHON_TEST", "hf_repo": "vendor/model", "hf_revision": revision}
    (config / "models.yaml").write_text(json.dumps([model]))
    snapshot = tmp_path / f"private/hf/hub/models--vendor--model/snapshots/{revision}"
    snapshot.mkdir(parents=True)
    weight = snapshot / "model.safetensors"
    weight.write_bytes(b"test weights")
    worker = tmp_path / "worker.exe"
    worker.touch()
    env = tmp_path / "private/runtime.env"
    env.write_text(f"TSFM_PYTHON_TEST={worker}\nHF_HOME={tmp_path / 'private/hf'}\n")
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs:
                        subprocess.CompletedProcess(args[0], 0, "3.11.17\n", ""))
    return module, root, env, weight


def test_pinned_cpu_cache_and_kst_day_strip_publication_credentials(local_fixture, monkeypatch):
    module, root, env, weight = local_fixture
    for key in module.CREDENTIAL_KEYS:
        monkeypatch.setenv(key, "must-not-reach-child")
    monkeypatch.setenv("TSFM_LIVE_ENABLED", "1")
    monkeypatch.setenv("TSFM_PYTHON_UNCONFIGURED", "must-not-reach-child")
    report, child = module.prepare(root, env, today=date(2026, 10, 8))
    assert report["run_date"] == "2026-10-08"
    assert report["worker_profiles"] == 1 and len(report["models"]) == 1
    assert report["live_publication"] is False
    assert child["TSFM_DEVICE"] == "cpu" and child["HF_HUB_OFFLINE"] == "1"
    assert child["TSFM_LIVE_ENABLED"] == "0" and child["TSFM_OTS_ENABLED"] == "0"
    assert not (module.CREDENTIAL_KEYS & child.keys())
    assert "TSFM_PYTHON_UNCONFIGURED" not in child
    assert root not in Path(report["cache_dir"]).parents


def test_missing_or_empty_cached_weights_fail_before_run(local_fixture):
    module, root, env, weight = local_fixture
    weight.write_bytes(b"")
    with pytest.raises(ValueError, match="Empty cached"):
        module.prepare(root, env)
    weight.unlink()
    with pytest.raises(ValueError, match="No cached weight"):
        module.prepare(root, env)


def test_private_paths_reject_public_checkout(local_fixture):
    module, root, env, weight = local_fixture
    public_env = root / "runtime.env"
    public_env.write_text(env.read_text())
    with pytest.raises(ValueError, match="outside the public"):
        module.prepare(root, public_env)
    with pytest.raises(ValueError, match="outside the public"):
        module.prepare(root, env, root / "cache")


def test_runtime_file_is_literal_and_rejects_credentials(tmp_path):
    module = load_launcher()
    path = tmp_path / "runtime.env"
    path.write_text('HF_HOME="$(Write-Output accidental)"\n')
    assert module.read_runtime_env(path, {"HF_HOME"}) == {"HF_HOME": "$(Write-Output accidental)"}
    path.write_text("GH_TOKEN=private-value\n")
    with pytest.raises(ValueError, match="only runtime paths/settings") as error:
        module.read_runtime_env(path, {"HF_HOME"})
    assert "private-value" not in str(error.value)


def test_historical_date_requires_exact_format_and_never_future(local_fixture):
    module, root, env, weight = local_fixture
    report, _ = module.prepare(root, env, as_of="2026-10-07", today=date(2026, 10, 8))
    assert report["run_date"] == "2026-10-07"
    for value in ("20261007", "2026-10-09"):
        with pytest.raises(ValueError):
            module.prepare(root, env, as_of=value, today=date(2026, 10, 8))


def test_child_always_receives_dry_run_and_exit_code_is_preserved(monkeypatch):
    module = load_launcher()
    monkeypatch.setattr(module, "prepare", lambda *args:
                        ({"run_date": "2026-10-08"}, {"TSFM_LIVE_ENABLED": "0"}))
    calls = []

    def child(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 23)

    monkeypatch.setattr(module.subprocess, "run", child)
    assert module.main(["--runtime-env-file", "private.env", "--check-only"]) == 0
    assert calls == []
    assert module.main(["--runtime-env-file", "private.env"]) == 23
    assert calls[0][0][-4:] == ["run", "--dry-run", "--as-of", "2026-10-08"]
    assert calls[0][1]["env"]["TSFM_LIVE_ENABLED"] == "0"


def test_image_model_installation_stops_on_first_failed_profile():
    """Execute the Dockerfile's actual loop with a failing fake installer."""
    shell = shutil.which("sh")
    if not shell:
        candidate = Path("C:/Program Files/Git/bin/sh.exe")
        shell = str(candidate) if candidate.is_file() else None
    if not shell:
        pytest.skip("POSIX shell unavailable; CI executes this test on Linux")
    dockerfile = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text()
    start = dockerfile.index("for profile in ")
    end = dockerfile.index("done", start) + len("done")
    loop = dockerfile[start:end].replace("\\\n", "\n")
    script = 'uv() { echo "$*"; return 7; }; ' + loop + '\necho "MASKED_FAILURE"\n'
    result = subprocess.run([shell, "-c", script], capture_output=True, text=True, check=False)
    assert result.returncode == 7
    assert result.stdout.count("sync --project") == 1
    assert "MASKED_FAILURE" not in result.stdout
