"""Integration checks through immutable fixtures, scoring, correction and export."""
import copy
import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest

from fixture_ledger import REPOSITORY, export_fixture, generate_fixture
from tsfm_live.ledger import append_json, canonical_bytes, iso, materialize, parse_ts, read_files
from tsfm_live.metrics import score_forecast

UTC = timezone.utc
NOW = datetime(2026, 10, 20, tzinfo=UTC)


def read_api(root, relative):
    return json.loads((root / "site/public/api/v1" / relative).read_bytes())


@pytest.fixture(scope="module")
def exported(tmp_path_factory):
    root = tmp_path_factory.mktemp("private-export-fixture")
    marker = generate_fixture(root, days=90)
    result = export_fixture(root, now=NOW, write_snapshot=True)
    return root, marker, result


def append_correction(root, *, kind, file, selector, replacement=None, identifier="fixture-correction"):
    correction = {"id": identifier, "created_ts_utc": "2026-10-19T00:00:00Z", "type": kind,
                  "affects": [{"file": file, "record_selector": selector}], "reason": "Synthetic test correction",
                  "replacement": replacement, "author": "fixture-only"}
    append_json(root / f"ledger/corrections/2026/{identifier}.json", correction, "corrections")


def test_fixture_refuses_real_repository_and_nonempty_roots(tmp_path):
    with pytest.raises(ValueError, match="outside"):
        generate_fixture(REPOSITORY / "danger-fixture")
    (tmp_path / "keep.txt").write_text("user-owned")
    with pytest.raises(FileExistsError):
        generate_fixture(tmp_path)
    assert (tmp_path / "keep.txt").read_text() == "user-owned"


def test_export_matrix_model_details_keep_logical_n_and_calibration_units(exported):
    root, marker, result = exported
    assert len(marker["entrants"]) == 11
    matrix = read_api(root, "matrix/90d.json")
    eid = "chronos-2"
    for iid in marker["indicators"]:
        cell = matrix["regimes"]["all"][iid][eid]
        count = len(marker["eligible_dates"][iid])
        assert cell["n"] == cell["paired_n"] == cell["observed_n"] == count
        assert 60 <= count < 90  # real market calendars, not calendar-day padding
        assert 0 <= cell["cov80"] <= cell["cov95"] <= 1
        detail = read_api(root, f"indicators/{iid}.json")
        assert detail["windows"]["90d"][eid] == cell
        assert detail["windows"]["7d"][eid] is None
        assert detail["window_counts"]["7d"][eid] == {"n": 7, "observed_n": 7}
        assert len(detail["series"]) == count * 11
    fx = matrix["regimes"]["all"]["eurusd"][eid]
    rates = matrix["regimes"]["all"]["ust10y"][eid]
    assert rates["width80_mean"] == pytest.approx(20 * fx["width80_mean"], abs=2e-5)
    model = read_api(root, f"models/{eid}.json")
    assert model["windows"]["90d"]["ust10y"] == rates
    assert model["windows"]["7d"]["ust10y"] is None
    assert model["window_counts"]["7d"]["ust10y"] == {"n": 7, "observed_n": 7}
    assert {r["entrant_id"] for r in model["series"]} == {eid, "volnaive"}
    leaderboard = read_api(root, "leaderboard/90d.json")
    row = next(r for r in leaderboard["entrants"] if r["id"] == eid)
    expected_n = sum(len(v) for v in marker["eligible_dates"].values())
    assert row["n"] == expected_n
    assert row["scored_live_days"] == len(set().union(*map(set, marker["eligible_dates"].values())))
    assert row["n_cells"] == row["rank_eligible_cells"] == 3
    assert row["status"] == "ranked" and row["rank"] is not None
    assert result["scored_records"] == expected_n * 11
    assert result["unscorable_records"] == 0
    assert read_api(root, "meta.json")["mode"] == "fixture"
    skipped = read_api(root, "status.json")["skipped"]
    assert skipped and all("2026-09-08" <= r["run_date"] <= "2026-10-07" for r in skipped)


def test_distribution_intervals_join_the_same_target_actual_and_units(exported):
    root, marker, _ = exported
    for iid, unit in (("eurusd", "%"), ("ust10y", "bp")):
        detail = read_api(root, f"indicators/{iid}.json")
        distributions = detail["distributions"]
        assert len(distributions) == len(marker["eligible_dates"][iid]) * 11
        point = next(r for r in distributions if r["entrant_id"] == "chronos-2")
        source = json.loads((root / f"ledger/forecasts/2026/{point['run_date']}.json").read_bytes())
        issued = next(r for r in source["records"] if r["indicator_id"] == iid and r["entrant_id"] == "chronos-2")
        actual = materialize(root)["actuals"][iid, point["next_close_ts"]]
        assert point["q10"] == issued["q"]["0.1"]
        assert point["q50"] == issued["q"]["0.5"]
        assert point["q90"] == issued["q"]["0.9"]
        assert point["actual_y"] == actual["y"] and point["actual_value"] == actual["value"]
        assert point["unit"] == unit
        assert point["display_q10"] <= point["display_q50"] <= point["display_q90"]


def test_unscorable_outcomes_do_not_inflate_matrix_or_leaderboard(tmp_path):
    missing = ("2026-09-21", "eurusd")
    marker = generate_fixture(tmp_path, days=30, unscorable=[missing])
    result = export_fixture(tmp_path, now=NOW)
    matrix = read_api(tmp_path, "matrix/all.json")
    count = len(marker["eligible_dates"]["eurusd"]) - 1
    assert matrix["regimes"]["all"]["eurusd"]["chronos-2"]["n"] == count
    assert result["unscorable_records"] == 11
    assert len(read_api(tmp_path, "status.json")["unscorable"]) == 11
    rows = read_api(tmp_path, "indicators/eurusd.json")["distributions"]
    assert all(r["actual_y"] is None for r in rows if r["run_date"] == missing[0])


def test_corrected_view_rescores_but_hash_verified_forecast_and_snapshot_stay_original(tmp_path):
    generate_fixture(tmp_path, days=20)
    export_fixture(tmp_path, now=NOW, write_snapshot=True)
    snapshot = tmp_path / "ledger/snapshots/2026/2026-10-07.json"
    original_snapshot = snapshot.read_bytes()
    file, actual_doc = next((p, d) for p, d in read_files(tmp_path, "actuals")
                            if any(a["indicator_id"] == "eurusd" for a in d["records"]))
    actual = next(a for a in actual_doc["records"] if a["indicator_id"] == "eurusd")
    before = materialize(tmp_path)
    (day, _, eid), issued = next((key, f) for key, f in before["forecasts"].items()
                                if f["indicator_id"] == "eurusd" and f["entrant_id"] == "chronos-2"
                                and f["next_close_ts"] == actual["close_ts"] and f["status"] == "ok")
    source_path = tmp_path / f"ledger/forecasts/2026/{day}.json"
    source_bytes = source_path.read_bytes()
    source_hash = hashlib.sha256(source_bytes).hexdigest()
    old_api_forecast = read_api(tmp_path, f"forecasts/{day}.json")
    revised_level = actual["value"] * 1.02
    append_correction(tmp_path, kind="actual_revision", file=str(file.relative_to(tmp_path)).replace("\\", "/"),
                      selector={"indicator_id": "eurusd", "close_ts": actual["close_ts"].replace("Z", "+00:00")},
                      replacement={"value": revised_level})
    export_fixture(tmp_path, now=NOW, write_snapshot=True)
    assert snapshot.read_bytes() == original_snapshot
    assert len(list((tmp_path / "ledger/snapshots/2026").glob("*.json"))) == 1
    assert source_path.read_bytes() == source_bytes
    public_forecast = read_api(tmp_path, f"forecasts/{day}.json")
    assert public_forecast == old_api_forecast and public_forecast["hash"] == source_hash
    card = read_api(tmp_path, f"scorecards/{day}.json")
    corrected = next(s for s in card["scores"] if s["indicator_id"] == "eurusd" and s["entrant_id"] == eid)
    effective_actual = next(a for a in card["actuals"] if a["indicator_id"] == "eurusd")
    expected = score_forecast(effective_actual["y"], issued["q"], "log_return_pct")
    assert corrected["crps"] == pytest.approx(expected["crps"], abs=2e-6)
    assert corrected["corrected"] and effective_actual["corrected"]
    points = read_api(tmp_path, "indicators/eurusd.json")["distributions"]
    point = next(r for r in points if r["run_date"] == day and r["entrant_id"] == eid)
    assert point["corrected"] and point["actual_value"] == pytest.approx(revised_level, abs=1e-6)


def test_current_void_is_not_presented_as_locked_and_prior_success_is_explicit(tmp_path):
    generate_fixture(tmp_path, days=3)
    append_correction(tmp_path, kind="void", file="ledger/forecasts/2026/2026-10-07.json", selector={})
    export_fixture(tmp_path, now=NOW)
    latest = read_api(tmp_path, "latest.json")
    assert latest["as_of"] == latest["run_date"] == "2026-10-07"
    assert latest["state"] == "void"
    assert latest["last_successful_lockin"]["run_date"] == "2026-10-06"
    assert all(r["status"] == "void" for r in latest["records"])
    assert read_api(tmp_path, "scorecards/2026-10-07.json")["scores"] == []
    assert read_api(tmp_path, "status.json")["state"] == "void"


@pytest.mark.parametrize("with_late_receipt", [False, True])
def test_newer_failed_or_late_run_never_relabels_previous_forecast_as_current(tmp_path, with_late_receipt):
    generate_fixture(tmp_path, days=3)
    previous = read_files(tmp_path, "manifests")[-1][1]
    day = "2026-10-08"
    run = parse_ts(previous["run_ts_utc"]) + timedelta(days=1)
    failed = {**previous, "run_id": "fixture-next-failed", "run_date": day, "run_ts_utc": iso(run),
              "scheduled_ts": iso(run), "actual_start_ts": iso(run), "deadline_met": False,
              "lockin_ts_utc": None, "forecasts_sha256": None, "forecasts_commit": None}
    if with_late_receipt:
        prior_forecast = read_files(tmp_path, "forecasts")[-1][1]
        document = copy.deepcopy(prior_forecast)
        document.update(run_id="fixture-next-late", run_date=day, run_ts_utc=iso(run),
                        lockin_deadline_utc=iso(run + timedelta(minutes=40)))
        for record in document["records"]:
            record["last_close_ts"] = iso(parse_ts(record["last_close_ts"]) + timedelta(days=1))
            record["next_close_ts"] = iso(parse_ts(record["next_close_ts"]) + timedelta(days=1))
        digest = append_json(tmp_path / f"ledger/forecasts/2026/{day}.json", document, "forecasts")
        failed.update(forecasts_sha256=digest, forecasts_commit="f" * 40,
                      lockin_ts_utc=iso(run + timedelta(minutes=41)))
    append_json(tmp_path / "ledger/manifests/2026/fixture-next-failed.json", failed, "manifests")
    # A repeated post-run manifest must not duplicate the date in misses/index.
    append_json(tmp_path / "ledger/manifests/2026/fixture-next-failed-post.json",
                {**failed, "run_id": "fixture-next-failed-post"}, "manifests")
    export_fixture(tmp_path, now=NOW)
    latest = read_api(tmp_path, "latest.json")
    assert latest["as_of"] == latest["run_date"] == day
    assert latest["state"] == ("deadline_missed" if with_late_receipt else "failed")
    assert not latest["deadline_met"]
    assert latest["last_successful_lockin"]["run_date"] == "2026-10-07"
    assert not any(r["status"] == "ok" for r in latest["records"])
    status = read_api(tmp_path, "status.json")
    assert status["state"] == latest["state"]
    assert len(status["deadline_misses"]) == 1


def test_hash_tamper_refuses_export_and_does_not_refresh_public_files(tmp_path):
    generate_fixture(tmp_path, days=2)
    export_fixture(tmp_path, now=NOW)
    latest_path = tmp_path / "site/public/api/v1/latest.json"
    before = latest_path.read_bytes()
    path = tmp_path / "ledger/forecasts/2026/2026-10-07.json"
    document = json.loads(path.read_bytes())
    document["records"][0]["inference_seconds"] += 0.001
    path.write_bytes(canonical_bytes(document))
    with pytest.raises(ValueError, match="hash mismatch"):
        export_fixture(tmp_path, now=NOW)
    assert latest_path.read_bytes() == before


def test_return_only_api_never_reconstructs_or_exposes_source_levels(tmp_path):
    generate_fixture(tmp_path, days=3, return_only=["usdjpy"])
    export_fixture(tmp_path, now=NOW)
    detail = read_api(tmp_path, "indicators/usdjpy.json")
    assert detail["indicator"]["display_policy"] == "return_only"
    assert detail["distributions"]
    for point in detail["distributions"]:
        assert point["unit"] == "%" and point["actual_y"] is not None
        assert point["display_q10"] is point["display_q50"] is point["display_q90"] is point["actual_value"] is None
    for record in detail["forecasts"]:
        assert record["last_close_value"] is None and record["display_q"] is None
    for day in ("2026-10-05", "2026-10-06", "2026-10-07"):
        card = read_api(tmp_path, f"scorecards/{day}.json")
        assert all(a["value"] is None for a in card["actuals"] if a["indicator_id"] == "usdjpy")
        source = read_api(tmp_path, f"forecasts/{day}.json")
        assert all(r["last_close_value"] is None for r in source["records"] if r["indicator_id"] == "usdjpy")
