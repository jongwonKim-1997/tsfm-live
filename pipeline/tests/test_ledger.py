import copy
import hashlib
from datetime import timedelta

import pytest

from tsfm_live.immutability import hash_append_only
from tsfm_live.ledger import (append_json, canonical_bytes, iso, lock_in, locked_forecasts,
                              materialize, validate_ledger)
from tsfm_live.metrics import score_forecast
from tsfm_live.schemas import ForecastFile
from test_integrity import DAY, DEADLINE, RUN, build, model, output


def fixture_doc(tmp_path):
    return build(tmp_path / "private", [model("a")], lambda *args, **kwargs: output())


def append_fixture(root, document):
    path = root / "ledger" / "forecasts" / "2026" / f"{DAY}.json"
    digest = append_json(path, document, "forecasts")
    manifest = {"run_id": "receipt", "run_date": DAY, "run_ts_utc": iso(RUN), "scheduled_ts": iso(RUN),
                "actual_start_ts": iso(RUN), "uv_lock_sha256": "a" * 64, "python_version": "fixture",
                "hardware": "cpu", "entrants": [], "sources": [], "steps": [], "counts": {},
                "lockin_ts_utc": iso(RUN + timedelta(minutes=1)), "deadline_met": True,
                "forecasts_sha256": digest, "forecasts_commit": "a" * 40, "mode": "live"}
    append_json(root / "ledger/manifests/2026/receipt.json", manifest, "manifests")
    return path, digest


def correction(root, kind, filename, selector, replacement=None, suffix="one"):
    c = {"id": suffix, "created_ts_utc": "2026-10-10T00:00:00Z", "type": kind,
         "affects": [{"file": filename, "record_selector": selector}], "reason": "Verified fixture correction",
         "replacement": replacement, "author": "test"}
    append_json(root / f"ledger/corrections/2026/{suffix}.json", c, "corrections")


def test_canonical_six_decimals_order_utf8_and_nonfinite():
    assert canonical_bytes({"b": 1.12345678, "a": "한글"}) == '{"a":"한글","b":1.123457}'.encode()
    assert canonical_bytes({"x": [1.2345674]}) == canonical_bytes({"x": [1.23456739]})
    with pytest.raises(ValueError):
        canonical_bytes({"x": float("nan")})
    with pytest.raises(TypeError):
        canonical_bytes({1: "not a string key"})


def test_pydantic_timestamps_normalize_to_utc(tmp_path):
    doc = fixture_doc(tmp_path)
    changed = copy.deepcopy(doc)
    changed["run_ts_utc"] = "2026-10-08T08:10:00+09:00"
    assert canonical_bytes(ForecastFile.model_validate(changed)) == canonical_bytes(ForecastFile.model_validate(doc))


def test_append_refuses_overwrite_and_hash_matches_bytes(tmp_path):
    target = tmp_path / "ledger.json"
    digest = append_json(target, {"score": 1.23456789})
    original = target.read_bytes()
    assert digest == hashlib.sha256(original).hexdigest()
    with pytest.raises(FileExistsError):
        append_json(target, {"score": 100})
    assert target.read_bytes() == original
    assert hash_append_only(b"old\n", b"old\nnew\n")
    assert not hash_append_only(b"old\n", b"changed\nnew\n")
    assert not hash_append_only(b"old", b"older\n")


@pytest.mark.parametrize("when,met", [(RUN + timedelta(minutes=2), True), (DEADLINE, False)])
def test_publication_receipt_deadline_hash_and_append_only(tmp_path, monkeypatch, when, met):
    monkeypatch.setattr("tsfm_live.ledger.commit_paths", lambda *a, **k: "a" * 40)
    class Publisher:
        def publish(self, paths, message, deadline):
            return {"published_ts": iso(when), "commit": "b" * 40}
    doc = fixture_doc(tmp_path)
    receipt = lock_in(tmp_path, doc, Publisher(), now=lambda: RUN + timedelta(minutes=1))
    forecast = tmp_path / f"ledger/forecasts/2026/{DAY}.json"
    original = forecast.read_bytes()
    assert receipt["deadline_met"] == met
    assert receipt["forecasts_sha256"] == hashlib.sha256(original).hexdigest()
    assert receipt["forecasts_sha256"] in (tmp_path / "ledger/HASHES.md").read_text()
    if not met:
        assert (tmp_path / f"ledger/corrections/2026/{DAY}-void.json").exists()
    with pytest.raises(FileExistsError):
        lock_in(tmp_path, doc, Publisher(), now=lambda: RUN)
    assert forecast.read_bytes() == original


def test_publication_failure_voids_and_never_becomes_scoreable(tmp_path, monkeypatch):
    monkeypatch.setattr("tsfm_live.ledger.commit_paths", lambda *a, **k: "a" * 40)
    class Publisher:
        def publish(self, *args):
            raise RuntimeError("push failed")
    with pytest.raises(RuntimeError):
        lock_in(tmp_path, fixture_doc(tmp_path), Publisher(), now=lambda: RUN)
    assert (tmp_path / f"ledger/corrections/2026/{DAY}-void.json").exists()
    assert locked_forecasts(tmp_path) == []


def test_receipt_after_target_is_not_valid_even_before_deadline(tmp_path, monkeypatch):
    monkeypatch.setattr("tsfm_live.ledger.commit_paths", lambda *a, **k: "a" * 40)
    doc = fixture_doc(tmp_path)
    doc["records"][0]["next_close_ts"] = iso(RUN + timedelta(minutes=3))
    class Publisher:
        def publish(self, paths, message, deadline):
            assert deadline == RUN + timedelta(minutes=3)
            return {"published_ts": iso(RUN + timedelta(minutes=4))}
    assert not lock_in(tmp_path, doc, Publisher(), now=lambda: RUN)["deadline_met"]


def populated(root, *, public_anchor=True):
    doc = fixture_doc(root)
    record = doc["records"][0]
    if not public_anchor:
        record["last_close_value"] = None
    path, _ = append_fixture(root, doc)
    actual = {"indicator_id": "fixture", "close_ts": record["next_close_ts"], "value": 110. if public_anchor else None,
              "y": 1., "source_id": "fixture", "source_fingerprint": "a" * 64,
              "published_ts": None, "fetched_ts_utc": "2026-10-09T00:00:00Z"}
    append_json(root / "ledger/actuals/2026/2026-10-09.json", {"run_date": "2026-10-09", "records": [actual]}, "actuals")
    score = {"forecast_run_date": DAY, "indicator_id": "fixture", "entrant_id": "a", "regime": "normal",
             "scored_ts_utc": "2026-10-09T01:00:00Z", "unscorable": None,
             **score_forecast(1., record["q"], "log_return_pct")}
    append_json(root / "ledger/scores/2026/2026-10-09.json", {"run_date": "2026-10-09", "records": [score]}, "scores")
    return path, record


def test_actual_level_revision_recomputes_target_and_scores_without_editing(tmp_path):
    path, issued = populated(tmp_path)
    originals = {p: p.read_bytes() for p in (tmp_path / "ledger").rglob("*.json")}
    correction(tmp_path, "actual_revision", "ledger/actuals/2026/2026-10-09.json",
               {"indicator_id": "fixture", "close_ts": issued["next_close_ts"].replace("Z", "+00:00")}, {"value": 120.})
    state = materialize(tmp_path)
    actual = next(iter(state["actuals"].values()))
    import math
    expected = 100 * math.log(120 / issued["last_close_value"])
    assert actual["y"] == pytest.approx(expected)
    assert state["scores"][0]["y"] == pytest.approx(expected)
    assert state["scores"][0]["corrected"]
    assert all(p.read_bytes() == body for p, body in originals.items())


def test_return_only_revision_requires_explicit_transformed_actual(tmp_path):
    _, issued = populated(tmp_path, public_anchor=False)
    correction(tmp_path, "actual_revision", "ledger/actuals/2026/2026-10-09.json",
               {"indicator_id": "fixture"}, {"value": None, "y": 2.})
    assert materialize(tmp_path)["scores"][0]["y"] == 2.


def test_void_correction_removes_already_recorded_scores(tmp_path):
    path, _ = populated(tmp_path)
    correction(tmp_path, "void", str(path.relative_to(tmp_path)).replace("\\", "/"), {})
    assert materialize(tmp_path)["scores"] == []


def test_correction_cannot_rewrite_forecast_or_silently_miss(tmp_path):
    path, _ = populated(tmp_path)
    correction(tmp_path, "other", str(path.relative_to(tmp_path)).replace("\\", "/"), {}, {"q": {"0.5": 999}})
    with pytest.raises(ValueError, match="cannot be replaced"):
        materialize(tmp_path)


def test_duplicate_actual_aliases_rejected(tmp_path):
    _, issued = populated(tmp_path)
    actual = next(iter(materialize(tmp_path)["actuals"].values()))
    actual["close_ts"] = actual["close_ts"].replace("Z", "+00:00")
    append_json(tmp_path / "ledger/actuals/2026/2026-10-10.json", {"run_date": "2026-10-10", "records": [actual]}, "actuals")
    with pytest.raises(ValueError, match="Duplicate actual"):
        validate_ledger(tmp_path)


def test_prospective_correction_is_validated_before_any_append(tmp_path):
    path, _ = populated(tmp_path)
    proposed = {"id": "miss", "created_ts_utc": "2026-10-10T00:00:00Z", "type": "actual_revision",
                "affects": [{"file": "ledger/actuals/2026/2026-10-09.json",
                             "record_selector": {"indicator_id": "does-not-exist"}}],
                "reason": "Invalid selector fixture", "replacement": {"y": 2.}, "author": "test"}
    before = {p: p.read_bytes() for p in (tmp_path / "ledger").rglob("*.json")}
    with pytest.raises(ValueError, match="matched no records"):
        materialize(tmp_path, extra_corrections=[proposed])
    assert all(p.read_bytes() == body for p, body in before.items())
    assert not (tmp_path / "ledger/corrections").exists()
