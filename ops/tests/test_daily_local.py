"""Real scoring/serialization with fake sources and inference; no weight downloads."""
from datetime import timedelta
import hashlib
import importlib.util
import json
from pathlib import Path

from filelock import FileLock
import pandas as pd
import pytest

from tsfm_live.config.settings import QUANTILES
from tsfm_live.ledger import canonical_bytes, iso, parse_ts, sha256


def load_daily():
    path = Path(__file__).resolve().parents[1] / "daily_local.py"
    spec = importlib.util.spec_from_file_location("daily_local", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def daily(tmp_path):
    module = load_daily()
    root = tmp_path / "repo"
    config = root / "pipeline/tsfm_live/config"
    config.mkdir(parents=True)
    cfg = {"id": "eurusd", "name": "EUR/USD", "enabled": True, "source": {"adapter": "ecb", "params": {}},
           "tz": "Europe/Berlin", "target_transform": "log_return_pct", "display_policy": "level", "unit": "USD/EUR"}
    models = [{"id": "rw0", "kind": "baseline", "enabled": True}]
    (config / "indicators.yaml").write_text(json.dumps([cfg]))
    (config / "models.yaml").write_text(json.dumps(models))
    state = tmp_path / "private/daily"
    clock = {"now": parse_ts("2026-10-11T23:12:00Z"), "value": 1.101, "infer": 0, "fetch": 0}
    target = parse_ts("2026-10-12T14:00:00Z")

    def now():
        return clock["now"]

    def fetch(configs, run_ts, cache):
        clock["fetch"] += 1
        data = [("2026-10-09T14:00:00Z", 1.10)]
        if run_ts > target:
            data.append((iso(target), clock["value"]))
        history = pd.DataFrame({"close_ts": pd.to_datetime([d[0] for d in data], utc=True),
                                "value": [d[1] for d in data], "published_ts": [None] * len(data)})
        history.attrs["fetched_ts_utc"] = iso(run_ts)
        return {"eurusd": history}, [{"id": "eurusd", "status": "ok", "source_id": "ecb",
            "fingerprint": "f" * 64, "fetched_ts_utc": iso(run_ts)}]

    def predict(indicators, models, histories, issued, deadline, day, run_id, cache, **kwargs):
        assert kwargs["dry_run"] is False
        assert issued == clock["now"]
        clock["infer"] += 1
        context = [0.01] * 512
        private = {"last_close_value": 1.1, "last_close_ts": "2026-10-09T14:00:00Z",
                   "context": context, "context_hash": sha256(context)}
        module.atomic_json(cache / "contexts" / day / "eurusd.json", private)
        record = {"indicator_id": "eurusd", "entrant_id": "rw0", "entrant_version": "builtin",
            "status": "ok", "skip_reason": None, "target_transform": "log_return_pct",
            "last_close_ts": private["last_close_ts"], "next_close_ts": iso(target),
            "last_close_value": 1.1 if cfg["display_policy"] == "level" else None,
            "context_len": 512, "context_hash": sha256(context), "regime": "normal", "sigma_ewma": 0.1,
            "q": {str(q): (q - .5) * .2 for q in QUANTILES}, "mean": 0., "quantile_method": "native",
            "n_samples": None, "seed": 42, "inference_seconds": 0., "contributors": []}
        return {"run_id": run_id, "run_date": day, "run_ts_utc": iso(issued),
                "lockin_deadline_utc": iso(deadline), "records": [record]}

    def run(**kwargs):
        return module.run_daily(root, state, now=now, fetch=fetch, predict=predict,
                                sleep=lambda seconds: None, **kwargs)
    return module, root, state, clock, cfg, run, fetch, predict


def test_today_forward_forecast_frozen_and_same_day_resume_deduplicates(daily):
    module, root, state, clock, cfg, run, fetch, predict = daily
    report, code = run()
    assert code == 0 and report["forecast_counts"] == {"ok": 1}
    assert report["run_date"] == "2026-10-12"  # UTC date is still Oct 11.
    path = state / "days/2026-10-12/forecast.json"
    original = path.read_bytes()
    assert report["evaluation"]["new_scores"] == 0
    report2, code = run()
    assert code == 0 and report2["stages"]["forecast"]["reason"] == "already_recorded"
    assert clock["infer"] == 1 and path.read_bytes() == original
    payload = json.loads((state / "reports/latest.json").read_bytes())
    assert payload["public_ledger_eligible"] is False and payload["external_timestamp_proof"] is False
    assert payload["forecasts"][0]["availability"] == "available"
    assert payload["report"]["finished_ts_utc"] == report2["finished_ts_utc"]
    assert not (root / "ledger").exists() and not (root / "site").exists()


def test_after_close_same_day_collects_and_scores_once_with_real_metric_code(daily):
    module, root, state, clock, cfg, run, fetch, predict = daily
    run()
    clock["now"] = parse_ts("2026-10-12T14:10:00Z")
    report, code = run()
    assert code == 0 and report["evaluation"]["new_actuals"] == 1
    assert report["evaluation"]["new_scores"] == 1 and clock["infer"] == 1
    report2, code = run()
    assert code == 0 and report2["evaluation"]["new_scores"] == 0
    forecasts, envelopes, actuals, scores = module.read_journal(state)
    assert len(actuals) == len(scores) == 1
    assert scores[0]["crps"] > 0 and scores[0]["y"] > 0
    payload = json.loads((state / "reports/latest.json").read_bytes())
    assert payload["forecasts"][0]["availability"] == "expired"
    assert payload["metrics"][0]["n"] == 1


def test_late_first_launch_does_not_backdate_or_touch_model_runtimes(daily):
    module, root, state, clock, cfg, run, fetch, predict = daily
    clock["now"] = parse_ts("2026-10-12T04:00:00Z")
    def forbidden():
        raise AssertionError("Models must not be loaded on a late launch")
    report, code = run(runtime_check=forbidden)
    assert code == 0 and clock["infer"] == 0 and clock["fetch"] == 1
    assert report["stages"]["forecast"]["reason"] == "forecast_window_closed"
    assert not list((state / "days").glob("*/forecast.json"))
    assert (state / "reports/index.html").exists()


@pytest.mark.parametrize("when,reason", [("2026-10-11T23:09:59Z", "before_schedule"),
                                        ("2026-10-11T23:48:00Z", "forecast_window_closed")])
def test_forecast_start_boundaries(daily, when, reason):
    module, root, state, clock, cfg, run, fetch, predict = daily
    clock["now"] = parse_ts(when)
    report, code = run()
    assert code == 0 and report["stages"]["forecast"]["reason"] == reason and clock["infer"] == 0


def test_completion_past_deadline_voids_and_never_scores(daily):
    module, root, state, clock, cfg, run, fetch, predict = daily
    def late(*args, **kwargs):
        result = predict(*args, **kwargs)
        clock["now"] = parse_ts("2026-10-11T23:50:00Z")
        return result
    report, code = module.run_daily(root, state, now=lambda: clock["now"], fetch=fetch, predict=late)
    assert code == 1 and report["forecast_counts"] == {"void": 1}
    clock["now"] = parse_ts("2026-10-12T14:10:00Z")
    report, code = run()
    assert report["evaluation"]["total_scores"] == 0
    assert module.read_journal(state)[0][0][1]["records"][0]["q"] == {}


def test_private_return_only_export_never_discloses_levels(daily):
    module, root, state, clock, cfg, run, fetch, predict = daily
    cfg["display_policy"] = "return_only"
    (root / "pipeline/tsfm_live/config/indicators.yaml").write_text(json.dumps([cfg]))
    run()
    clock["now"] = parse_ts("2026-10-12T14:10:00Z")
    report, code = run()
    payload = json.loads((state / "reports/latest.json").read_bytes())
    assert code == 0 and report["evaluation"]["new_scores"] == 1
    assert payload["observations"][0]["value_kind"] == "change"
    assert payload["observations"][0]["today"][0]["value"] < .1
    assert payload["forecasts"][0]["median"] == 0
    assert "last_close_value" not in (state / "reports/latest.json").read_text()


def test_return_only_forecast_keeps_issued_policy_after_current_level_approval(daily):
    module, root, state, clock, cfg, run, fetch, predict = daily
    config_path = root / "pipeline/tsfm_live/config/indicators.yaml"
    cfg["display_policy"] = "return_only"
    config_path.write_text(json.dumps([cfg]))
    run()
    original = (state / "days/2026-10-12/forecast.json").read_bytes()
    cfg["display_policy"] = "level"
    config_path.write_text(json.dumps([cfg]))
    report, code = run()
    payload = json.loads((state / "reports/latest.json").read_bytes())
    assert code == 0 and report["stages"]["export"]["status"] == "ok"
    assert payload["observations"][0]["value_kind"] == "level"
    forecast = payload["forecasts"][0]
    assert forecast["value_kind"] == "change" and forecast["unit"] == "log return (%)"
    assert forecast["median"] == 0 and forecast["metadata_basis"] == "issued_forecast"
    assert (state / "days/2026-10-12/forecast.json").read_bytes() == original


def test_removed_current_indicator_does_not_break_archived_forecast_export(daily):
    module, root, state, clock, cfg, run, fetch, predict = daily
    run()
    (root / "pipeline/tsfm_live/config/indicators.yaml").write_text("[]")
    report, code = run()
    payload = json.loads((state / "reports/latest.json").read_bytes())
    assert code == 0 and report["stages"]["export"]["status"] == "ok"
    assert payload["observations"] == []
    assert payload["forecasts"][0]["indicator_id"] == "eurusd"
    assert payload["forecasts"][0]["median"] == 1.1
    assert payload["forecasts"][0]["unit"] == "USD/EUR"


def test_archived_target_date_keeps_issued_timezone_after_current_zone_changes(daily):
    module, root, state, clock, cfg, run, fetch, predict = daily
    config_path = root / "pipeline/tsfm_live/config/indicators.yaml"
    cfg["tz"] = "Pacific/Kiritimati"
    config_path.write_text(json.dumps([cfg]))
    run()
    cfg["tz"] = "America/New_York"
    config_path.write_text(json.dumps([cfg]))
    report, code = run()
    payload = json.loads((state / "reports/latest.json").read_bytes())
    assert code == 0 and report["stages"]["export"]["status"] == "ok"
    assert payload["observations"][0]["today"][0]["date"] == "2026-10-09"
    assert payload["forecasts"][0]["next_session_date"] == "2026-10-13"
    assert payload["forecasts"][0]["next_session_timezone"] == "Pacific/Kiritimati"


def test_revised_observation_is_flagged_without_changing_existing_score(daily):
    module, root, state, clock, cfg, run, fetch, predict = daily
    run()
    clock["now"] = parse_ts("2026-10-12T14:10:00Z")
    run()
    original = canonical_bytes(module.read_journal(state)[3])
    clock["value"] = 1.2
    clock["now"] += timedelta(minutes=1)
    report, code = run()
    assert code == 1 and report["evaluation"]["revisions_observed"] == 1
    assert canonical_bytes(module.read_journal(state)[3]) == original


def test_corrupt_journal_fails_before_fetch_or_inference(daily):
    module, root, state, clock, cfg, run, fetch, predict = daily
    run()
    path = state / "days/2026-10-12/forecast.json"
    document = json.loads(path.read_bytes())
    document["forecast"]["records"][0]["q"]["0.5"] = .001
    path.write_bytes(canonical_bytes(document))
    before = clock["fetch"]
    report, code = run()
    assert code == 1 and report["stages"]["journal"]["status"] == "failed"
    assert clock["fetch"] == before and clock["infer"] == 1


@pytest.mark.parametrize("damage", ["missing", "changed"])
def test_missing_or_changed_frozen_context_fails_closed(daily, damage):
    module, root, state, clock, cfg, run, fetch, predict = daily
    run()
    path = state / "cache/contexts/2026-10-12/eurusd.json"
    if damage == "missing":
        path.unlink()
    else:
        private = json.loads(path.read_bytes())
        private["context"][0] = 100
        path.write_bytes(canonical_bytes(private))
    report, code = run()
    assert code == 1 and report["stages"]["journal"]["status"] == "failed"
    assert clock["infer"] == 1


def test_changed_unit_does_not_silently_grade_old_forecast(daily):
    module, root, state, clock, cfg, run, fetch, predict = daily
    run()
    cfg["unit"] = "different units"
    (root / "pipeline/tsfm_live/config/indicators.yaml").write_text(json.dumps([cfg]))
    clock["now"] = parse_ts("2026-10-12T14:10:00Z")
    report, code = run()
    assert report["evaluation"]["new_actuals"] == report["evaluation"]["new_scores"] == 0


def test_future_created_or_backdated_forecasts_are_rejected(daily):
    module, root, state, clock, cfg, run, fetch, predict = daily
    run()
    clock["now"] -= timedelta(seconds=1)
    report, code = run()
    assert code == 1 and report["stages"]["journal"]["status"] == "failed"


def test_lock_prevents_concurrent_collection(daily):
    module, root, state, clock, cfg, run, fetch, predict = daily
    state.mkdir(parents=True)
    with FileLock(state / "daily.lock"):
        report, code = run()
    assert code == 0 and report["reason"] == "already_running" and clock["fetch"] == 0


def test_collection_retries_only_failed_sources_and_has_finite_limit(daily):
    module = daily[0]
    calls = []
    def fetch(configs, now, cache):
        ids = [c["id"] for c in configs]
        calls.append(ids)
        return {}, [{"id": value, "status": "ok" if value == "ok" else "source_error"} for value in ids]
    _, health = module.collect([{"id": "ok"}, {"id": "bad"}], Path("unused"), fetch=fetch,
                               attempts=3, sleep=lambda _: None)
    assert calls == [["ok", "bad"], ["bad"], ["bad"]]
    assert {r["id"]: r["attempts"] for r in health} == {"ok": 1, "bad": 3}


def test_interrupted_inference_has_finite_same_day_retry_limit(daily):
    module, root, state, clock, cfg, run, fetch, predict = daily
    def crash(*args, **kwargs):
        raise RuntimeError("credential=must-not-be-logged")
    for _ in range(2):
        report, code = module.run_daily(root, state, now=lambda: clock["now"], fetch=fetch, predict=crash)
        assert code == 1 and report["stages"]["forecast"]["error_type"] == "RuntimeError"
    report, code = run()
    assert report["stages"]["forecast"]["reason"] == "inference_attempt_limit"
    assert clock["infer"] == 0
    assert "must-not-be-logged" not in "".join(p.read_text() for p in (state / "attempts").glob("*.json"))


def test_export_failure_preserves_batch_and_resumes_without_rescoring(daily, monkeypatch):
    module, root, state, clock, cfg, run, fetch, predict = daily
    run()
    clock["now"] = parse_ts("2026-10-12T14:10:00Z")
    export = module.export_private
    def fail(*args, **kwargs):
        raise OSError("broken disk")
    monkeypatch.setattr(module, "export_private", fail)
    report, code = run()
    assert code == 1 and report["evaluation"]["new_scores"] == 1
    assert report["stages"]["export"]["attempts"] == 2
    monkeypatch.setattr(module, "export_private", export)
    report, code = run()
    assert code == 0 and report["evaluation"]["new_scores"] == 0 and clock["infer"] == 1


def test_evaluate_only_bypasses_runtime_and_source_probe_runs_after_forecast(daily):
    module, root, state, clock, cfg, run, fetch, predict = daily
    called = []
    def probe(path, now):
        called.append(path)
        return {"network_performed": False, "auto_enabled": False}
    report, code = run(evaluate_only=True, probe=probe)
    assert code == 0 and clock["infer"] == 0 and called == [state / "source-audit"]
    assert report["source_audit"] == {"network_performed": False, "auto_enabled": False,
                                      "active_status_counts": {}, "candidate_status_counts": {}}


def test_enabled_probe_failure_marks_run_partial_and_keeps_audit_counts(daily):
    module, root, state, clock, cfg, run, fetch, predict = daily
    def probe(path, now):
        return {"network_performed": True, "auto_enabled": False,
                "indicators": [{"id": "eurusd", "enabled": True, "collection_status": "source_error"}],
                "candidates": [{"id": "candidate", "collection_status": "fresh"}]}
    report, code = run(evaluate_only=True, probe=probe)
    assert code == 1 and report["stages"]["source_audit"]["status"] == "partial"
    assert report["source_audit"]["active_status_counts"] == {"source_error": 1}
    assert report["source_audit"]["candidate_status_counts"] == {"fresh": 1}


def test_atomic_write_collision_preserves_original(tmp_path):
    module = load_daily()
    path = tmp_path / "immutable.json"
    module.atomic_json(path, {"a": 1})
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(FileExistsError):
        module.atomic_json(path, {"a": 2})
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert not list(tmp_path.glob("*.tmp"))


def test_state_cannot_be_written_under_public_repository(daily):
    module, root, state, clock, cfg, run, fetch, predict = daily
    with pytest.raises(ValueError, match="outside the public"):
        module.run_daily(root, root / "private")
