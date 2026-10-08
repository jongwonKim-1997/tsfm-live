from datetime import date, timedelta
import json

import numpy as np
import pytest

from tsfm_live.aggregate import block_bootstrap_weights, build_aggregates, geometric_mean, pi_label
from tsfm_live.config import settings


INDICATORS = [{"id": "x", "enabled": True}, {"id": "z", "enabled": True}]
ENTRANTS = [{"id": "m", "kind": "tsfm"}]


def score(day, iid="x", eid="m", loss=1, regime="normal", hit=1):
    return {"forecast_run_date": str(day), "indicator_id": iid, "entrant_id": eid,
            "crps": loss, "se": loss ** 2, "ae": loss, "hit": hit,
            "covered80": 1, "covered95": 1, "width80": 2, "width95": 4,
            "regime": regime, "unscorable": None}


def records(n=60, ratios=None, spacing=1):
    ratios = ratios or {"x": 0.5, "z": 2}
    result = []
    for i in range(n):
        day = date(2026, 1, 1) + timedelta(days=i * spacing)
        for iid, ratio in ratios.items():
            result.extend([score(day, iid, "volnaive", 2, hit=None),
                           score(day, iid, "m", 2 * ratio),
                           score(day, iid, "ensemble-median", 1.8)])
    return result


@pytest.fixture(autouse=True)
def small_bootstrap(monkeypatch):
    # Separate test below validates all 1,000 production replicates.
    monkeypatch.setattr(settings, "BOOT_B", 100)


def row(result, eid="m", window="90d", regime="all"):
    return next(r for r in result["leaderboards"][window]["regimes"][regime] if r["id"] == eid)


def test_geometric_mean_hand_computed_zero_and_undefined():
    assert geometric_mean([0.5, 2]) == pytest.approx(1)
    assert geometric_mean([0.25, 1]) == pytest.approx(0.5)
    assert geometric_mean([0, 2]) == 0
    assert geometric_mean([None, 2]) is None
    assert geometric_mean([]) is None


def test_toy_matrix_ranking_tiers_and_paired_baseline():
    result = build_aggregates(records(), INDICATORS, ENTRANTS, "2026-04-01")
    m = row(result)
    assert m["skill_overall"] == pytest.approx(0)
    assert m["status"] == "ranked"
    assert m["n"] == 120
    assert m["tier"] == "B"
    assert m["best_indicator"] == "x"
    assert m["worst_indicator"] == "z"
    assert row(result, "ensemble-median")["tier"] == "A"
    assert row(result, "volnaive")["skill_overall"] == 0
    assert row(result, "volnaive")["hit_rate"] is None
    assert row(result, "volnaive")["hit_n"] == 0
    assert row(result, window="30d")["rank"] is None
    assert row(result, window="30d")["tier"] == "B"
    assert row(result, window="7d")["skill_overall"] is None
    assert result["matrices"]["7d"]["counts"]["all"]["x"]["m"]["n"] == 7


def test_window_last_scored_sessions_and_common_dates_not_calendar_days():
    data = records(40, {"x": 0.5}, spacing=2)
    # Entrant is missing the latest 5 sessions. Its window must NOT roll farther back.
    cutoff = "2026-03-12"
    data = [s for s in data if s["entrant_id"] != "m" or s["forecast_run_date"] < cutoff]
    result = build_aggregates(data, INDICATORS[:1], ENTRANTS, "2026-04-01")
    cell = result["matrices"]["30d"]["regimes"]["all"]["x"]["m"]
    assert cell["n"] == 25
    assert result["matrices"]["30d"]["window_dates"]["x"][0] == "2026-01-21"
    assert result["matrices"]["7d"]["regimes"]["all"]["x"]["m"] is None


def test_seven_session_leaderboard_retains_total_counts_below_cell_threshold():
    indicators = [{"id": iid} for iid in "abc"]
    result = build_aggregates(records(12, {iid: 0.9 for iid in "abc"}), indicators, ENTRANTS, "2026-04-01")
    entrant = row(result, window="7d")
    assert entrant["skill_overall"] is None
    assert entrant["n"] == entrant["n_eligible"] == 0
    assert entrant["paired_n_total"] == 21
    assert entrant["observed_n_total"] == 21


def test_pairing_uses_same_days_and_exposes_missing_reference_count():
    data = records(12, {"x": 0.5})
    data = [s for s in data if not (s["entrant_id"] == "volnaive" and s["forecast_run_date"] == "2026-01-01")]
    next(s for s in data if s["entrant_id"] == "m" and s["forecast_run_date"] == "2026-01-01")["crps"] = 900
    result = build_aggregates(data, INDICATORS[:1], ENTRANTS, "2026-02-01")
    c = result["matrices"]["90d"]["regimes"]["all"]["x"]["m"]
    assert c["n"] == 11
    assert c["observed_n"] == 12
    assert c["skill_crps"] == pytest.approx(0.5)
    assert c["crps_mean"] == 1


def test_regime_filter_follows_window_selection():
    data = records(60, {"x": 0.5})
    for record in data:
        record["regime"] = "high_vol" if record["forecast_run_date"] >= "2026-02-20" else "normal"
    result = build_aggregates(data, INDICATORS[:1], ENTRANTS, "2026-04-01")
    assert result["matrices"]["30d"]["regimes"]["normal"]["x"]["m"]["n"] == 20
    assert result["matrices"]["30d"]["regimes"]["high_vol"]["x"]["m"]["n"] == 10
    assert row(result, regime="high_vol")["status"] == "probation"
    assert result["predictability"]["indicators"][0]["regime_pi"]["high_vol"] is None


def test_rank_needs_75_percent_with_60_paired_each():
    indicators = [{"id": key} for key in "abcd"]
    data = records(60, {key: 0.9 for key in "abc"})
    result = build_aggregates(data, indicators, ENTRANTS, "2026-04-01")
    assert row(result)["status"] == "ranked"
    assert row(result)["coverage"] == 0.75
    data = [s for s in data if s["indicator_id"] != "c" or s["forecast_run_date"] != "2026-01-01"]
    result = build_aggregates(data, indicators, ENTRANTS, "2026-04-01")
    assert row(result)["status"] == "probation"
    assert row(result)["rank"] is None


def test_zero_reference_loss_undefined_and_zero_entrant_loss_perfect():
    data = records(30, {"x": 0})
    result = build_aggregates(data, INDICATORS[:1], ENTRANTS, "2026-04-01")
    assert row(result)["skill_overall"] == 1
    assert row(result)["ci_low"] == 1
    for record in data:
        record["crps"] = 0
        record["se"] = 0
    result = build_aggregates(data, INDICATORS[:1], ENTRANTS, "2026-04-01")
    c = result["matrices"]["90d"]["regimes"]["all"]["x"]["m"]
    assert c["n"] == 30
    assert c["rel_crps"] is None
    assert c["undefined_crps_reason"] == "zero_reference_loss"
    assert row(result)["skill_overall"] is None
    json.dumps(result, allow_nan=False)


def test_pi_thresholds_clipping_and_minimum_n():
    assert [pi_label(p, 30) for p in [0, 4.999, 5, 19.999, 20, 49.999, 50, 100]] == [
        "unpredictable", "unpredictable", "weak", "weak", "moderate", "moderate", "strong", "strong"]
    assert pi_label(90, 29) == "insufficient data"
    for loss, expected in [(0, 100), (3, 0), (1.9, 25), (1.8, 50)]:
        data = records(30, {"x": 1})
        for record in data:
            if record["entrant_id"] == "ensemble-median":
                record["crps"] = loss
        result = build_aggregates(data, INDICATORS[:1], ENTRANTS, "2026-04-01")
        p = result["predictability"]["indicators"][0]
        assert p["PI"] == pytest.approx(expected)
        assert p["n"] == 30
        assert p["ci_low"] is not None
        if expected == 50:
            assert p["label"] == "strong"


def test_bootstrap_reproducibility_full_1000_and_joint_date_vectors(monkeypatch):
    monkeypatch.setattr(settings, "BOOT_B", 1000)
    weights = block_bootstrap_weights(13)
    assert weights.shape == (1000, 13)
    assert np.all(weights.sum(axis=1) == 13)
    assert np.array_equal(weights, block_bootstrap_weights(13))
    # Opposite losses whose sum is constant expose accidentally independent resampling.
    data = records(30)
    for record in data:
        index = date.fromisoformat(record["forecast_run_date"]).day
        if record["entrant_id"] == "m":
            record["crps"] = (1 if index % 2 else 3) if record["indicator_id"] == "x" else (3 if index % 2 else 1)
    first = build_aggregates(data, INDICATORS, ENTRANTS, "2026-04-01")
    second = build_aggregates(data, INDICATORS, ENTRANTS, "2026-04-01")
    assert first == second
    assert row(first)["bootstrap_valid"] == 1000
    assert row(first)["ci_low"] >= -1e-12


def test_null_safe_empty_initial_data_includes_all_rows():
    result = build_aggregates([], INDICATORS, ENTRANTS, "2026-01-01")
    assert {r["id"] for r in result["leaderboards"]["90d"]["entrants"]} == {"m", "rw0", "volnaive", "ensemble-median"}
    assert all(r["n"] == 0 and r["rank"] is None and r["tier"] is None
               for r in result["leaderboards"]["90d"]["entrants"])
    assert all(p["PI"] is None and p["label"] == "insufficient data"
               for p in result["predictability"]["indicators"])
    json.dumps(result, allow_nan=False)


def test_snapshot_rank_change_history_and_exact_30_day_difference():
    snapshots = []
    for offset in range(30, 0, -1):
        day = str(date(2026, 4, 1) - timedelta(days=offset))
        snapshots.append({"as_of": day, "windows": {"90d": {"entrants": [{"id": "m", "rank": 5}]}},
                          "predictability": {"indicators": [{"id": "x", "PI": 20, "n": 50}]}})
    result = build_aggregates(records(), INDICATORS, ENTRANTS, "2026-04-01", snapshots)
    m = row(result)
    assert m["rank_change"] == m["rank"] - 5
    p = next(p for p in result["predictability"]["indicators"] if p["id"] == "x")
    assert p["pi_change_30d"] == pytest.approx(30)
    assert len(p["pi_history"]) == 31
    assert p["pi_history"][-1]["as_of"] == "2026-04-01"
    assert p["best_entrant"] == "m"


def test_duplicate_keys_rejected_and_unscorable_excluded():
    record = score("2026-01-01")
    with pytest.raises(ValueError, match="duplicate score key"):
        build_aggregates([record, record], INDICATORS, ENTRANTS, "2026-02-01")
    result = build_aggregates([{**record, "unscorable": "actual_unavailable", "crps": None}],
                              INDICATORS, ENTRANTS, "2026-02-01")
    assert row(result)["n"] == 0


def test_conflicting_regimes_rejected():
    with pytest.raises(ValueError, match="conflicting stored regimes"):
        build_aggregates([score("2026-01-01"), score("2026-01-01", eid="volnaive", regime="high_vol")],
                         INDICATORS, ENTRANTS, "2026-02-01")
