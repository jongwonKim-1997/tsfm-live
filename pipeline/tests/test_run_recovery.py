"""Exercise live control flow using isolated documents and mocked external I/O."""
import copy
from datetime import timedelta
from types import SimpleNamespace

import pytest

from tsfm_live import cli
from tsfm_live.ledger import append_json, iso, read_files, void_forecast
from test_integrity import DAY, RUN, model
from test_ledger import fixture_doc


def prepare(tmp_path, monkeypatch, *, publication_failure=False, void_at_lockin=False, void_by_correction=False):
    root, cache = tmp_path / "repository", tmp_path / "private"
    (root / "pipeline").mkdir(parents=True)
    (root / "pipeline/uv.lock").write_text("fixture", encoding="utf-8")
    document = fixture_doc(root)
    notifications = []
    monkeypatch.setenv("TSFM_LIVE_ENABLED", "1")
    monkeypatch.setenv("TSFM_CACHE_DIR", str(cache))
    monkeypatch.setenv("TSFM_PUBLIC_ORIGIN", "https://example.test")
    monkeypatch.setattr(cli, "utcnow", lambda: RUN)
    monkeypatch.setattr(cli, "doctor", lambda _: {"blockers": []})
    monkeypatch.setattr("tsfm_live.models.load_models", lambda: [model("a")])
    monkeypatch.setattr("tsfm_live.sources.load_indicators", lambda: [])
    monkeypatch.setattr("tsfm_live.ingest.ingest", lambda *args: ({}, []))
    monkeypatch.setattr("tsfm_live.forecast.build_forecasts", lambda *a, **k: copy.deepcopy(document))
    monkeypatch.setattr("tsfm_live.actuals.resolve_actuals", lambda *args: [])
    monkeypatch.setattr("tsfm_live.score.score_pending", lambda *args: [])
    monkeypatch.setattr("tsfm_live.export.export_site", lambda *a, **k: {})
    monkeypatch.setattr("tsfm_live.cards.generate_cards", lambda *args: None)
    monkeypatch.setattr("tsfm_live.ots.process_ots", lambda *a, **k: {"status": "unavailable", "records": []})
    monkeypatch.setattr("tsfm_live.manifest.git_head", lambda _: None)
    monkeypatch.setattr("tsfm_live.notify.notify", lambda m, *a, **k: notifications.append(copy.deepcopy(m)))

    class Publisher:
        def __init__(self, root):
            pass

        def publish(self, *args):
            if publication_failure:
                raise RuntimeError("simulated results publication failure")
            return {}

    monkeypatch.setattr(cli, "GitPublisher", Publisher)

    def lock(root, forecasts, publisher):
        issued = copy.deepcopy(forecasts)
        if void_at_lockin:
            for record in issued["records"]:
                record.update(status="void", skip_reason="deadline_missed")
        digest = append_json(root / f"ledger/forecasts/2026/{DAY}.json", issued, "forecasts")
        if void_by_correction:
            void_forecast(root, DAY, "Publication became late after the forecast file was committed.")
        late = void_at_lockin or void_by_correction
        return {"forecasts_sha256": digest, "forecasts_commit": "a" * 40,
                "lockin_ts_utc": iso(RUN + timedelta(minutes=41 if late else 1)),
                "deadline_met": not late}

    monkeypatch.setattr(cli, "lock_in", lock)
    args = SimpleNamespace(as_of=None, date=DAY, dry_run=False, step=None, baselines_only=False)
    return root, cache, args, notifications


def test_late_lockin_counts_match_void_document(tmp_path, monkeypatch):
    root, cache, args, notifications = prepare(tmp_path, monkeypatch, void_at_lockin=True)
    cli.run(args, root)
    for _, manifest in read_files(root, "manifests"):
        assert manifest["counts"] == {"void": 1}
        assert manifest["entrant_counts"]["a"]["void"] == 1
        assert manifest["entrant_counts"]["a"]["ok"] == 0
    assert (cache / f"lockin-receipts/{DAY}.json").is_file()


def test_results_failure_preserves_receipt_records_failure_and_notifies(tmp_path, monkeypatch):
    root, cache, args, notifications = prepare(tmp_path, monkeypatch, publication_failure=True)
    with pytest.raises(RuntimeError, match="results publication"):
        cli.run(args, root)
    failure = next(m for _, m in read_files(root, "manifests") if m["run_id"].endswith("publication-failed"))
    assert failure["deadline_met"] is True
    assert failure["steps"][-1]["name"] == "publish_results"
    assert failure["steps"][-1]["status"] == "failed"
    assert notifications[-1]["alerts"] == ["PUBLICATION_FAILED"]
    assert (cache / f"lockin-receipts/{DAY}.json").is_file()
    assert read_files(root, "corrections") == []


def test_late_publication_overlay_is_reflected_in_manifest_counts(tmp_path, monkeypatch):
    root, cache, args, notifications = prepare(tmp_path, monkeypatch, void_by_correction=True)
    cli.run(args, root)
    assert read_files(root, "forecasts")[0][1]["records"][0]["status"] == "ok"
    assert read_files(root, "corrections")
    assert all(m["counts"] == {"void": 1} for _, m in read_files(root, "manifests"))


def test_new_execution_recovers_checkpoint_without_reforecasting(tmp_path, monkeypatch):
    root, cache, args, notifications = prepare(tmp_path, monkeypatch, publication_failure=True)
    with pytest.raises(RuntimeError):
        cli.run(args, root)
    # A fresh Cloud Run clone can contain the public forecast while its earlier
    # receipt manifest remains only in the private, authenticated checkpoint.
    for path, _ in read_files(root, "manifests"):
        path.unlink()
    path = root / f"ledger/forecasts/2026/{DAY}.json"
    monkeypatch.setattr("tsfm_live.receipts._git", lambda *a, **k: None)
    monkeypatch.setattr("tsfm_live.receipts.subprocess.run", lambda *a, **k: SimpleNamespace(stdout=path.read_bytes()))
    monkeypatch.setattr(cli, "utcnow", lambda: RUN + timedelta(minutes=5))
    monkeypatch.setattr("tsfm_live.forecast.build_forecasts", lambda *a, **k: pytest.fail("Must not regenerate"))
    monkeypatch.setattr(cli, "lock_in", lambda *a, **k: pytest.fail("Must not lock in twice"))
    with pytest.raises(RuntimeError, match="results publication"):
        cli.run(args, root)
    assert any("recovered" in p.name for p, _ in read_files(root, "manifests"))
    assert all(m["deadline_met"] for _, m in read_files(root, "manifests"))
    assert read_files(root, "corrections") == []
