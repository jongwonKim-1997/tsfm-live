"""Temporal evidence must distinguish a forecast, an execution and a publication."""
from copy import deepcopy
from datetime import timedelta

import pytest
from pydantic import ValidationError

from tsfm_live.ledger import iso
from tsfm_live.manifest import make_manifest
from tsfm_live.schemas import ActualRecord, ForecastFile, ManifestFile
from test_integrity import DAY, DEADLINE, RUN, build, model, output


def forecast(tmp_path):
    return build(tmp_path / "private", [model("a")], lambda *args, **kwargs: output())


def manifest(**changes):
    value = {"run_id": "receipt", "run_date": DAY, "run_ts_utc": iso(RUN),
             "scheduled_ts": iso(RUN), "actual_start_ts": iso(RUN),
             "uv_lock_sha256": "a" * 64, "python_version": "test", "hardware": "cpu",
             "entrants": [], "sources": [], "steps": [], "counts": {},
             "deadline_met": False, "mode": "live"}
    value.update(changes)
    return value


def receipt(**changes):
    return manifest(lockin_ts_utc=iso(RUN + timedelta(minutes=1)), forecasts_sha256="a" * 64,
                    forecasts_commit="b" * 40, deadline_met=True, **changes)


def test_forecast_date_uses_kst_not_utc(tmp_path):
    doc = forecast(tmp_path)
    assert RUN.date().isoformat() != DAY
    ForecastFile.model_validate(doc)
    doc["run_date"] = RUN.date().isoformat()
    with pytest.raises(ValidationError, match="Asia/Seoul date"):
        ForecastFile.model_validate(doc)


@pytest.mark.parametrize("delta", [-1, 1, 60])
def test_forecast_cannot_move_deadline(tmp_path, delta):
    doc = forecast(tmp_path)
    doc["lockin_deadline_utc"] = iso(DEADLINE + timedelta(seconds=delta))
    with pytest.raises(ValidationError, match="08:50"):
        ForecastFile.model_validate(doc)


def test_late_run_is_retained_only_as_all_void(tmp_path):
    doc = forecast(tmp_path)
    doc["run_ts_utc"] = iso(DEADLINE)
    with pytest.raises(ValidationError, match="only void"):
        ForecastFile.model_validate(doc)
    for record in doc["records"]:
        record.update(status="void", skip_reason="deadline_missed")
    ForecastFile.model_validate(doc)
    doc["records"][0].update(status="skipped", skip_reason="source_disabled")
    with pytest.raises(ValidationError, match="only void"):
        ForecastFile.model_validate(doc)


def actual(**changes):
    value = {"indicator_id": "fixture", "close_ts": iso(RUN), "value": 1., "y": 0.,
             "source_id": "fixture", "source_fingerprint": "a" * 64,
             "published_ts": iso(RUN + timedelta(minutes=1)),
             "fetched_ts_utc": iso(RUN + timedelta(minutes=2))}
    value.update(changes)
    return value


@pytest.mark.parametrize("field", ["close_ts", "published_ts", "fetched_ts_utc"])
def test_actual_naive_timestamp_rejected(field):
    with pytest.raises(ValidationError, match="timezones"):
        ActualRecord.model_validate(actual(**{field: RUN.replace(tzinfo=None).isoformat()}))


@pytest.mark.parametrize("changes", [
    {"fetched_ts_utc": iso(RUN - timedelta(seconds=1))},
    {"published_ts": iso(RUN - timedelta(seconds=1))},
    {"published_ts": iso(RUN + timedelta(minutes=3))},
])
def test_actual_evidence_must_follow_close_in_order(changes):
    with pytest.raises(ValidationError):
        ActualRecord.model_validate(actual(**changes))


def test_actual_unknown_publication_does_not_invent_a_time():
    assert ActualRecord.model_validate(actual(published_ts=None)).published_ts is None


@pytest.mark.parametrize("field", ["lockin_ts_utc", "forecasts_sha256", "forecasts_commit"])
def test_claimed_deadline_needs_complete_receipt(field):
    doc = receipt()
    doc[field] = None
    with pytest.raises(ValidationError, match="receipt"):
        ManifestFile.model_validate(doc)


def test_no_receipt_cannot_claim_deadline():
    with pytest.raises(ValidationError, match="complete live publication receipt"):
        ManifestFile.model_validate(manifest(deadline_met=True))


@pytest.mark.parametrize("field", ["run_ts_utc", "scheduled_ts", "actual_start_ts", "lockin_ts_utc"])
def test_manifest_naive_timestamp_rejected(field):
    doc = receipt()
    doc[field] = RUN.replace(tzinfo=None).isoformat()
    with pytest.raises(ValidationError, match="timezones"):
        ManifestFile.model_validate(doc)


def test_receipt_before_execution_requires_explicit_resume():
    doc = receipt()
    doc.update(run_ts_utc=iso(RUN + timedelta(minutes=5)), actual_start_ts=iso(RUN + timedelta(minutes=5)))
    with pytest.raises(ValidationError, match="resume marker"):
        ManifestFile.model_validate(doc)
    doc["resumed_after_lockin"] = True
    ManifestFile.model_validate(doc)
    doc["lockin_ts_utc"] = iso(RUN - timedelta(seconds=1))
    with pytest.raises(ValidationError, match="scheduled issue time"):
        ManifestFile.model_validate(doc)


def test_historical_dryrun_execution_date_is_not_forecast_date():
    later = iso(RUN + timedelta(days=25))
    doc = manifest(mode="dry-run", run_ts_utc=later, actual_start_ts=later)
    ManifestFile.model_validate(doc)
    doc["deadline_met"] = True
    with pytest.raises(ValidationError):
        ManifestFile.model_validate(doc)


def test_deadline_boundary_and_dryrun_no_publication_evidence():
    doc = receipt()
    doc["lockin_ts_utc"] = iso(DEADLINE)
    with pytest.raises(ValidationError, match="08:50"):
        ManifestFile.model_validate(doc)
    doc["deadline_met"] = False
    ManifestFile.model_validate(doc)
    doc["mode"] = "dry-run"
    with pytest.raises(ValidationError, match="cannot claim publication"):
        ManifestFile.model_validate(doc)


def test_manifests_need_fixed_schedule_and_consistent_execution_time():
    for changes in [{"scheduled_ts": iso(RUN + timedelta(minutes=1))},
                    {"run_ts_utc": iso(RUN + timedelta(seconds=1))}]:
        with pytest.raises(ValidationError):
            ManifestFile.model_validate(manifest(**changes))


def test_receipt_hash_and_ots_evidence_cannot_be_empty_labels():
    for changes in [{"forecasts_sha256": "digest"}, {"forecasts_commit": "unknown"},
                    {"ots_status": "anchored"}, {"ots_status": "pending", "ots_file": "ledger/ots/x.ots"}]:
        doc = receipt()
        doc.update(changes)
        with pytest.raises(ValidationError):
            ManifestFile.model_validate(doc)


def test_generated_entrant_counts_and_resume_marker(tmp_path, monkeypatch):
    (tmp_path / "pipeline").mkdir()
    (tmp_path / "pipeline/uv.lock").write_text("fixture", encoding="utf-8")
    monkeypatch.setattr("tsfm_live.manifest.git_head", lambda _: None)
    document = {"records": [{"entrant_id": "a", "status": "ok"},
                            {"entrant_id": "a", "status": "skipped"},
                            {"entrant_id": "b", "status": "failed"}]}
    value = make_manifest(tmp_path, "retry", DAY, RUN + timedelta(minutes=5), RUN,
                          [{"id": "a"}, {"id": "b"}, {"id": "c"}], [], [], receipt(), document)
    result = ManifestFile.model_validate(value)
    assert result.resumed_after_lockin
    assert result.entrant_counts["a"] == {"ok": 1, "failed": 0, "skipped": 1, "void": 0}
    assert result.entrant_counts["c"] == dict.fromkeys(("ok", "failed", "skipped", "void"), 0)
    wrong = deepcopy(value)
    wrong["entrant_counts"]["a"]["ok"] = 99
    with pytest.raises(ValidationError, match="sum"):
        ManifestFile.model_validate(wrong)


def test_manifest_surfaces_source_lag_even_after_successful_http_fetch(tmp_path, monkeypatch):
    (tmp_path / "pipeline").mkdir()
    (tmp_path / "pipeline/uv.lock").write_text("fixture", encoding="utf-8")
    monkeypatch.setattr("tsfm_live.manifest.git_head", lambda _: None)
    document = {"records": [{"indicator_id": "lagging", "entrant_id": "a", "status": "skipped",
                             "skip_reason": "source_lag"}]}
    sources = [{"id": "lagging", "status": "ok"}]
    value = make_manifest(tmp_path, "dry", DAY, RUN, RUN, [{"id": "a"}], sources, [], {}, document,
                          dry_run=True)
    ManifestFile.model_validate(value)
    assert value["sources"][0]["forecast_skip_reason"] == "source_lag"
    assert "forecast_skip_reason" not in sources[0]
