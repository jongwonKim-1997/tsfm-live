"""The dashboard runner archives raw results privately and exports only its view."""
import importlib.util
import json
from pathlib import Path

from filelock import FileLock
import pytest

from tsfm_live.ledger import parse_ts


@pytest.fixture
def dashboard(tmp_path):
    path = Path(__file__).resolve().parents[1] / "update_dashboard.py"
    spec = importlib.util.spec_from_file_location("update_dashboard", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    root = tmp_path / "repo"
    config = root / "pipeline/tsfm_live/config"
    config.mkdir(parents=True)
    (config / "indicators.yaml").write_text("[]")
    (config / "models.yaml").write_text("[]")
    state = tmp_path / "private"
    now = parse_ts("2026-10-11T09:00:00Z")
    calls = {"fetch": 0, "inference_enabled": None}

    def fetch(*args):
        calls["fetch"] += 1
        return {}, [{"id": "eurusd", "status": "ok", "fetched_ts_utc": now.isoformat()}]

    def build(indicators, models, histories, **kwargs):
        calls["inference_enabled"] = kwargs["inference_enabled"]
        assert kwargs["now"] == now
        assert kwargs["source_statuses"][0]["id"] == "eurusd"
        view = {"mode": "local_zero_shot", "public_ledger_eligible": False,
                "indicators": [{"id": "eurusd", "history": {"last7days": [{"value": 1.1}]},
                    "entrants": [{"availability": "available" if kwargs["inference_enabled"] else "unavailable"}]}]}
        return view, {"private_context": [1.0, 1.1]}

    def render(root, input_path, output_path):
        assert json.loads(input_path.read_bytes())["mode"] == "local_zero_shot"
        output_path.write_text("<html>line chart</html>")

    def run(**kwargs):
        return module.update_dashboard(root, state, clock=lambda: now, fetch=fetch,
                                       build=build, render=render, **kwargs)
    return module, root, state, calls, run


def test_archives_private_result_and_exports_only_chart_projection(dashboard):
    _, root, state, calls, run = dashboard
    result, code = run()
    assert code == 0 and result["status"] == "ok"
    assert calls["inference_enabled"] is True
    view = root / "site/public/api/v1/local_dashboard.json"
    assert "private_context" not in view.read_text()
    assert json.loads(next((state / "runs").glob("*/forecast.json")).read_bytes())["private_context"]
    assert (state / "reports/index.html").exists()
    assert result["published"] is False
    assert not (root / "ledger").exists()


def test_observations_only_has_no_inference_and_no_site_option(dashboard):
    _, root, state, calls, run = dashboard
    result, code = run(observations_only=True, write_site=False)
    assert code == 0 and calls["inference_enabled"] is False
    assert result["observation_count"] == 1
    assert result["forecast_reason"] == "observations_only"
    assert not (root / "site").exists()
    assert (state / "reports/latest.json").exists()


def test_missing_model_runtime_keeps_actual_chart_and_reports_partial(dashboard):
    _, root, _, calls, run = dashboard

    def missing():
        raise RuntimeError("sensitive diagnostic must not leak")

    result, code = run(runtime_check=missing)
    assert code == 1 and result["status"] == "partial"
    assert calls["inference_enabled"] is False
    assert result["runtime_error_type"] == "RuntimeError"
    assert "sensitive" not in json.dumps(result)
    assert (root / "site/public/api/v1/local_dashboard.json").exists()


def test_running_process_prevents_duplicate_collection(dashboard):
    _, _, state, calls, run = dashboard
    state.mkdir()
    with FileLock(state / ".dashboard.lock"):
        result, code = run()
    assert code == 0 and result["reason"] == "already_running"
    assert calls["fetch"] == 0


def test_state_directory_inside_repo_is_rejected(dashboard):
    module, root, _, _, _ = dashboard
    with pytest.raises(ValueError):
        module.update_dashboard(root, root / "private")


def test_observations_only_cli_does_not_require_model_environment(dashboard, monkeypatch, tmp_path):
    module, _, _, _, _ = dashboard
    monkeypatch.setenv("GITHUB_TOKEN", "not-a-real-token")
    reached = []

    def fake_update(root, state_dir, **kwargs):
        reached.append(True)
        assert kwargs["observations_only"] is True
        assert "GITHUB_TOKEN" not in module.os.environ
        assert module.os.environ["TSFM_LIVE_ENABLED"] == "0"
        return {"status": "ok"}, 0

    monkeypatch.setattr(module, "update_dashboard", fake_update)
    assert module.main(["--runtime-env-file", str(tmp_path / "missing.env"),
                        "--state-dir", str(tmp_path / "private"), "--observations-only"]) == 0
    assert reached == [True]
    assert module.os.environ["GITHUB_TOKEN"] == "not-a-real-token"
