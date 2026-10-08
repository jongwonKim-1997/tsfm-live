import copy
import json
from argparse import Namespace
from datetime import timedelta

import pandas as pd
import pytest

from tsfm_live.actuals import resolve_actuals
from tsfm_live.ingest import ingest
from tsfm_live.ledger import iso, parse_ts
from tsfm_live.score import score_pending
from tsfm_live.schemas import ScoreRecord
from tsfm_live.transforms import transform
from test_integrity import DAY, RUN, build, history, indicator, model, output
from test_ledger import append_fixture


def outcome_fixture(tmp_path, display="level"):
    cfg = indicator(display)
    doc = build(tmp_path, [model("a")], lambda *a, **kw: output(), cfg=cfg)
    record = doc["records"][0]
    close = parse_ts(record["next_close_ts"])
    run = close + timedelta(minutes=10)
    data = pd.concat([history(), pd.DataFrame({"close_ts": [close], "value": [120.], "published_ts": [None]})],
                     ignore_index=True)
    data.attrs["fetched_ts_utc"] = iso(run + timedelta(seconds=1))
    health = [{"id": "fixture", "source_id": "fixture-source", "fingerprint": "a" * 64}]
    return cfg, doc, data, health, run


def test_actual_keeps_issued_anchor_and_true_fetch_receipt(tmp_path):
    cfg, doc, data, health, run = outcome_fixture(tmp_path)
    issued = doc["records"][0]
    data.loc[data.index[-2], "value"] = 9999.  # Later source revision of context must not alter the issued anchor.
    actual = resolve_actuals([(None, doc)], {}, {"fixture": data}, [cfg], health, tmp_path, run)[0]
    assert actual["y"] == pytest.approx(transform([issued["last_close_value"], 120.], "log_return_pct")[0])
    assert actual["fetched_ts_utc"] == iso(run + timedelta(seconds=1))
    assert actual["fetched_ts_utc"] != iso(run)
    assert actual["published_ts"] is None
    # The literal offset representation cannot cause duplicate observations.
    alias = ("fixture", actual["close_ts"].replace("Z", "+00:00"))
    assert resolve_actuals([(None, doc)], {alias: actual}, {"fixture": data}, [cfg], health, tmp_path, run) == []


def test_actual_cannot_invent_missing_fetch_receipt_or_fingerprint(tmp_path):
    cfg, doc, data, health, run = outcome_fixture(tmp_path)
    data.attrs.clear()
    assert resolve_actuals([(None, doc)], {}, {"fixture": data}, [cfg], health, tmp_path, run) == []
    data.attrs["fetched_ts_utc"] = iso(run)
    assert resolve_actuals([(None, doc)], {}, {"fixture": data}, [cfg], [], tmp_path, run) == []


def test_return_only_private_anchor_and_hash_validation(tmp_path):
    cfg, doc, data, health, run = outcome_fixture(tmp_path, "return_only")
    actual = resolve_actuals([(None, doc)], {}, {"fixture": data}, [cfg], health, tmp_path, run)[0]
    assert actual["value"] is None and actual["y"] is not None
    path = tmp_path / "contexts" / DAY / "fixture.json"
    original = path.read_bytes()
    private = json.loads(original)
    private["context"][0] += 1  # A copied hash string alone cannot validate changed context bytes.
    path.write_text(json.dumps(private))
    with pytest.raises(ValueError, match="does not match"):
        resolve_actuals([(None, doc)], {}, {"fixture": data}, [cfg], health, tmp_path, run)


def test_scoring_requires_availability_after_close_and_excludes_void(tmp_path):
    cfg, doc, data, health, run = outcome_fixture(tmp_path)
    actual = resolve_actuals([(None, doc)], {}, {"fixture": data}, [cfg], health, tmp_path, run)[0]
    alias = ("fixture", actual["close_ts"].replace("Z", "+00:00"))
    assert score_pending([(None, doc)], {alias: actual}, [], run) == []  # Not fetched at this cutoff.
    scores = score_pending([(None, doc)], {alias: actual}, [], run + timedelta(seconds=2))
    assert len(scores) == 1 and scores[0]["unscorable"] is None
    assert score_pending([(None, doc)], {alias: actual}, scores, run + timedelta(days=1)) == []
    void = copy.deepcopy(doc)
    void["records"][0]["status"] = "void"
    assert score_pending([(None, void)], {alias: actual}, [], run + timedelta(days=1)) == []
    assert score_pending([(None, doc)], {alias: actual}, [], parse_ts(actual["close_ts"])) == []


def test_unavailable_actual_gets_null_metrics_exactly_at_grace(tmp_path):
    _, doc, _, _, run = outcome_fixture(tmp_path)
    close = parse_ts(doc["records"][0]["next_close_ts"])
    assert score_pending([(None, doc)], {}, [], close + timedelta(days=5, seconds=-1)) == []
    score = ScoreRecord.model_validate(score_pending([(None, doc)], {}, [], close + timedelta(days=5))[0])
    assert score.unscorable == "actual_unavailable" and score.crps is None and score.y is None


def test_ingest_preserves_raw_evidence_but_omits_local_paths(tmp_path, monkeypatch):
    data = history()
    data.attrs["fetched_ts_utc"] = iso(RUN)
    class Source:
        id = "fixture"
        raw_evidence = [{"body_sha256": "b" * 64, "url": "https://source.test/public",
                         "fetched_ts_utc": iso(RUN), "raw_file": "private-machine-path"}]
        def fingerprint(self):
            return "a" * 64
        def fetch_history(self, cfg, start):
            return data
    monkeypatch.setattr("tsfm_live.ingest.get_source", lambda *a: Source())
    histories, health = ingest([indicator()], RUN, tmp_path)
    assert health[0]["fetched_ts_utc"] == iso(RUN)
    assert health[0]["raw_evidence"][0]["body_sha256"] == "b" * 64
    assert "private-machine-path" not in json.dumps(health)
    assert len(histories["fixture"]) == len(data)


def test_confirmed_same_day_rerun_never_repeats_inference(tmp_path, monkeypatch):
    import tsfm_live.cli as cli
    root = tmp_path / "repo"
    private = tmp_path / "private"
    doc = build(private, [model("a")], lambda *a, **kw: output())
    append_fixture(root, doc)
    forecast_path = root / f"ledger/forecasts/2026/{DAY}.json"
    original = forecast_path.read_bytes()
    (root / "pipeline").mkdir()
    (root / "pipeline/uv.lock").write_text("fixture")
    monkeypatch.setenv("TSFM_LIVE_ENABLED", "1")
    monkeypatch.setenv("TSFM_PUBLIC_ORIGIN", "https://fixture.invalid")
    monkeypatch.setattr(cli, "utcnow", lambda: RUN + timedelta(minutes=5))
    monkeypatch.setattr(cli, "doctor", lambda root: {"blockers": []})
    monkeypatch.setattr(cli, "cache_directory", lambda root: private)
    monkeypatch.setattr("tsfm_live.models.load_models", lambda: [model("a")])
    monkeypatch.setattr("tsfm_live.sources.load_indicators", lambda: [indicator()])
    monkeypatch.setattr("tsfm_live.ingest.ingest", lambda *a: ({}, []))
    monkeypatch.setattr("tsfm_live.forecast.build_forecasts", lambda *a, **kw: pytest.fail("must not repeat inference"))
    monkeypatch.setattr("tsfm_live.export.export_site", lambda *a, **kw: {})
    monkeypatch.setattr("tsfm_live.notify.notify", lambda *a, **kw: None)
    monkeypatch.setattr("tsfm_live.notify.alert_reasons", lambda *a, **kw: [])
    monkeypatch.setattr("tsfm_live.manifest.git_head", lambda *a: None)
    class Publisher:
        def __init__(self, root):
            pass
        def publish(self, *a, **kw):
            return {"published_ts": iso(RUN + timedelta(minutes=5))}
    monkeypatch.setattr(cli, "GitPublisher", Publisher)
    args = Namespace(as_of=None, date=DAY, dry_run=False, baselines_only=False, step="score")
    cli.run(args, root)
    assert forecast_path.read_bytes() == original
    assert (root / f"ledger/scores/2026/{DAY}.json").exists()
