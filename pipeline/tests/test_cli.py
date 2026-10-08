"""Command-boundary checks for irreversible live ledger writes."""
import json

from tsfm_live.cli import main
from test_ledger import append_fixture, fixture_doc


def test_historical_live_run_rejected_before_io(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TSFM_LIVE_ENABLED", "1")
    assert main(["--root", str(tmp_path), "run", "--date", "2020-01-01"]) == 1
    assert "cannot be backfilled" in capsys.readouterr().out
    assert not (tmp_path / "ledger").exists()


def test_invalid_correction_selector_never_creates_immutable_record(tmp_path):
    document = fixture_doc(tmp_path)
    path, _ = append_fixture(tmp_path, document)
    original = path.read_bytes()
    correction = {"id": "no-match", "created_ts_utc": "2026-10-10T00:00:00Z", "type": "void",
                  "reason": "CLI test must reject unmatched selector", "author": "test",
                  "affects": [{"file": path.relative_to(tmp_path).as_posix(),
                               "record_selector": {"entrant_id": "does-not-exist"}}]}
    request = tmp_path / "request.json"
    request.write_text(json.dumps(correction))
    assert main(["--root", str(tmp_path), "correction", str(request)]) == 1
    assert not list((tmp_path / "ledger/corrections").rglob("*.json"))
    assert path.read_bytes() == original
