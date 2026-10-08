"""Paired, session-window aggregation and reproducible joint date bootstrap.

This module accepts corrected, scorable records from the ledger reader. It
does not read or mutate the ledger and never manufactures observations.
"""
from __future__ import annotations

from datetime import date, timedelta
import math
from collections import defaultdict
from collections.abc import Mapping

import numpy as np
from scipy.stats import binomtest

from .config import settings

REFERENCE = "volnaive"
ENSEMBLE = "ensemble-median"
REGIMES = ("all", "normal", "high_vol")


def _dict(value):
    return value.model_dump() if hasattr(value, "model_dump") else dict(value)


def _ratio(numerator, denominator):
    return float(numerator / denominator) if denominator > 0 else None


def geometric_mean(values):
    """A true zero loss remains zero; undefined ratios never become epsilon."""
    values = list(values)
    if not values or any(v is None or not math.isfinite(v) or v < 0 for v in values):
        return None
    if any(v == 0 for v in values):
        return 0.0
    return math.exp(math.fsum(math.log(v) for v in values) / len(values))


def _mean(records, field):
    return float(np.mean([record[field] for record in records])) if records else None


def _cell(pairs, observed_n):
    if len(pairs) < settings.MIN_N_CELL:
        return None
    entrants = [pair[0] for pair in pairs]
    references = [pair[1] for pair in pairs]
    n = len(pairs)
    calls = [record["hit"] for record in entrants if record.get("hit") is not None]
    rmse = math.sqrt(_mean(entrants, "se"))
    ref_rmse = math.sqrt(_mean(references, "se"))
    crps = _mean(entrants, "crps")
    ref_crps = _mean(references, "crps")
    rel_crps = _ratio(crps, ref_crps)
    rel_rmse = _ratio(rmse, ref_rmse)
    return {
        "n": n, "paired_n": n, "observed_n": observed_n,
        "rmse": rmse, "mae": _mean(entrants, "ae"), "crps_mean": crps,
        "reference_crps_mean": ref_crps, "reference_rmse": ref_rmse,
        "hit_rate": float(np.mean(calls)) if calls else None,
        "hit_n": len(calls), "call_rate": len(calls) / n,
        "hit_p": float(binomtest(sum(calls), len(calls), 0.5).pvalue) if calls else None,
        "cov80": _mean(entrants, "covered80"), "cov95": _mean(entrants, "covered95"),
        "width80_mean": _mean(entrants, "width80"), "width95_mean": _mean(entrants, "width95"),
        "rel_crps": rel_crps, "skill_crps": None if rel_crps is None else 1 - rel_crps,
        "rel_rmse": rel_rmse, "skill_rmse": None if rel_rmse is None else 1 - rel_rmse,
        "win_rate": sum(a["crps"] < b["crps"] for a, b in pairs) / n,
        "undefined_crps_reason": "zero_reference_loss" if rel_crps is None else None,
        "undefined_rmse_reason": "zero_reference_loss" if rel_rmse is None else None,
    }


def block_bootstrap_weights(n_dates, *, seed=None, repetitions=None, block=None):
    """Circular moving blocks on the sorted observed date axis.

    A row is one multiplicity vector shared by *all* indicators/entrants.
    Missing observations stay missing. Calendar gaps never become zero loss.
    """
    b = settings.BOOT_B if repetitions is None else repetitions
    length = settings.BOOT_BLOCK if block is None else block
    if n_dates < 1 or b < 1 or length < 1:
        raise ValueError("positive date count, repetitions and block length required")
    rng = np.random.default_rng(settings.BOOT_SEED if seed is None else seed)
    starts = rng.integers(0, n_dates, size=(b, math.ceil(n_dates / length)))
    indices = ((starts[:, :, None] + np.arange(length)) % n_dates).reshape(b, -1)[:, :n_dates]
    weights = np.zeros((b, n_dates), dtype=np.int32)
    np.add.at(weights, (np.repeat(np.arange(b), n_dates), indices.ravel()), 1)
    return weights


def _interval(values):
    values = np.asarray(values, dtype=float)
    valid = values[np.isfinite(values)]
    result = {"ci_low": None, "ci_high": None,
              "bootstrap_valid": int(len(valid)), "bootstrap_requested": int(len(values))}
    # Discarding many undefined replicates would condition away genuine failure.
    if len(values) and len(valid) >= math.ceil(0.95 * len(values)):
        low, high = np.quantile(valid, [0.025, 0.975])
        result.update(ci_low=float(low), ci_high=float(high))
    return result


def _bootstrap_ratios(pairs, date_index, weights):
    indexes = [date_index[a["forecast_run_date"]] for a, _ in pairs]
    selected = weights[:, indexes]
    numerator = selected @ np.asarray([a["crps"] for a, _ in pairs])
    denominator = selected @ np.asarray([b["crps"] for _, b in pairs])
    result = np.full(len(weights), np.nan)
    np.divide(numerator, denominator, out=result, where=denominator > 0)
    return result


def _geometric_bootstrap(ratios):
    matrix = np.asarray(ratios, dtype=float)
    if matrix.size == 0:
        return np.empty(0)
    good = np.all(np.isfinite(matrix) & (matrix >= 0), axis=0)
    zero = np.any(matrix == 0, axis=0) & good
    result = np.full(matrix.shape[1], np.nan)
    result[zero] = 0
    positive = good & ~zero
    result[positive] = np.exp(np.mean(np.log(matrix[:, positive]), axis=0))
    return result


def _pi(skill):
    # Stabilize published label boundaries against arithmetic such as
    # 100 * ((1 - 0.9) / 0.2) == 49.999999999999986.
    return None if skill is None else round(float(100 * min(1, max(0, skill / settings.PI_SCALE))), 12)


def pi_label(pi, n):
    if n < settings.MIN_N_PI or pi is None:
        return "insufficient data"
    if pi < 5:
        return "unpredictable"
    if pi < 20:
        return "weak"
    if pi < 50:
        return "moderate"
    return "strong"


def _previous_entries(snapshot, window):
    entry = snapshot.get("windows", {}).get(window, {})
    if not entry:
        entry = snapshot.get("leaderboards", {}).get(window, {})
    entries = entry.get("entrants", []) if isinstance(entry, Mapping) else entry
    if isinstance(entries, Mapping):
        return entries
    return {item["id"]: item for item in entries}


def _snapshot_indicators(snapshot):
    entries = snapshot.get("predictability", {}).get("indicators", [])
    if not entries:
        entries = snapshot.get("windows", {}).get("90d", {}).get("indicators", [])
    if not entries:
        entries = snapshot.get("indicators", [])
    if isinstance(entries, Mapping):
        return entries
    return {item["id"]: item for item in entries}


def _leaderboard(catalog, enabled_indicators, cells, counts, pairs_by_cell, boots, window,
                 prior, all_scores, as_of):
    rows = []
    for entrant in catalog:
        eid = entrant["id"]
        ecells = [(iid, cells[iid][eid]) for iid in enabled_indicators
                  if cells[iid][eid] is not None and cells[iid][eid]["rel_crps"] is not None]
        relative = geometric_mean(c["rel_crps"] for _, c in ecells)
        enough = sum(c["n"] >= settings.MIN_N_RANK for _, c in ecells)
        ranked = (window not in {"7d", "30d"} and bool(enabled_indicators)
                  and enough >= math.ceil(settings.RANK_COVERAGE * len(enabled_indicators)))
        selected = [a for iid, _ in ecells for a, _ in pairs_by_cell[iid, eid]]
        calls = [a["hit"] for a in selected if a.get("hit") is not None]
        n = len(selected)
        paired_n_total = sum(len(pairs_by_cell[iid, eid]) for iid in enabled_indicators)
        observed_n_total = sum(counts[iid][eid]["observed_n"] for iid in enabled_indicators)
        interval = _interval(1 - _geometric_bootstrap([boots[iid, eid] for iid, _ in ecells]))
        low, high = interval["ci_low"], interval["ci_high"]
        rmse_relative = geometric_mean(c["rel_rmse"] for _, c in ecells
                                       if c["rel_rmse"] is not None)
        score_dates = sorted({s["forecast_run_date"] for s in all_scores if s["entrant_id"] == eid})
        first_ok = entrant.get("first_ok_run_date")
        live_days = entrant.get("live_days")
        if live_days is None and first_ok is not None and entrant.get("run_dates") is not None:
            live_days = len({str(d) for d in entrant["run_dates"] if first_ok <= str(d) <= as_of})
        best = sorted(ecells, key=lambda item: (-item[1]["skill_crps"], item[0]))
        row = {
            "id": eid, "name": entrant.get("name", eid), "kind": entrant.get("kind", "tsfm"),
            "enabled": entrant.get("enabled", True), "status": "ranked" if ranked else "probation",
            "status_reason": None if ranked else ("short_window" if window in {"7d", "30d"}
                                                    else "insufficient_scored_days_or_coverage"),
            "rank": None, "rank_change": None,
            "tier": None if low is None else ("A" if low > 0 else "C" if high < 0 else "B"),
            "skill_overall": None if relative is None else 1 - relative,
            "rel_overall": relative, **interval,
            "sig_vs_volnaive": None if low is None else low > 0,
            "skill_rmse_overall": None if rmse_relative is None else 1 - rmse_relative,
            "hit_rate": float(np.mean(calls)) if calls else None, "hit_n": len(calls),
            "hit_rate_overall": float(np.mean(calls)) if calls else None,
            "call_rate": len(calls) / n if n else None,
            "cov80": _mean(selected, "covered80"), "cov95": _mean(selected, "covered95"),
            "live_days": live_days, "scored_live_days": len(score_dates),
            "n": n, "n_eligible": n, "paired_n_total": paired_n_total,
            "observed_n_total": observed_n_total,
            "n_cells": len(ecells), "rank_eligible_cells": enough,
            "enabled_indicator_count": len(enabled_indicators),
            "coverage": len(ecells) / len(enabled_indicators) if enabled_indicators else 0,
            "min_cell_n": min((c["n"] for _, c in ecells), default=0),
            "best_indicator": best[0][0] if best else None,
            "worst_indicator": best[-1][0] if best else None,
            "win_rate": sum(c["win_rate"] * c["n"] for _, c in ecells) / n if n else None,
        }
        rows.append(row)
    rows.sort(key=lambda row: (row["status"] != "ranked", row["skill_overall"] is None,
                               -(row["skill_overall"] or 0), -(row["win_rate"] or 0), row["id"]))
    for rank, row in enumerate((row for row in rows if row["status"] == "ranked"), 1):
        row["rank"] = rank
        old_rank = prior.get(row["id"], {}).get("rank")
        if old_rank is not None:
            row["rank_change"] = rank - old_rank
    return rows


def build_aggregates(scores, indicators, entrants, as_of, snapshots=None):
    """Return generated documents without filesystem access.

    Window selection precedes regime filtering. Each indicator's most recent
    N distinct scored run dates is shared across entrants. Each cell then uses
    only observations paired to the reference on those dates. ``n`` always
    means paired observations; ``observed_n`` also exposes lost reference pairs.
    Duplicate score keys and conflicting regimes are errors, never last-write wins.
    """
    as_of = str(as_of)
    date.fromisoformat(as_of)
    indicators = [_dict(value) for value in indicators]
    catalog = [_dict(value) for value in entrants]
    known = {entry["id"] for entry in catalog}
    for eid, kind in (("rw0", "baseline"), (REFERENCE, "baseline"), (ENSEMBLE, "ensemble")):
        if eid not in known:
            catalog.append({"id": eid, "kind": kind, "name": eid, "enabled": True})
    if len({entry["id"] for entry in catalog}) != len(catalog):
        raise ValueError("duplicate entrant ids")
    if len({entry["id"] for entry in indicators}) != len(indicators):
        raise ValueError("duplicate indicator ids")
    enabled = [entry["id"] for entry in indicators if entry.get("enabled", True)]
    indicator_ids = [entry["id"] for entry in indicators]
    entrant_ids = {entry["id"] for entry in catalog}
    by_key, by_indicator, regime_for = {}, defaultdict(set), {}
    valid_scores = []
    for raw in scores:
        record = _dict(raw)
        if record.get("unscorable") or record.get("status", "ok") != "ok":
            continue
        day, iid, eid = record["forecast_run_date"], record["indicator_id"], record["entrant_id"]
        if day > as_of:
            continue
        if iid not in indicator_ids or eid not in entrant_ids:
            raise ValueError(f"unknown score identity: {iid}/{eid}")
        key = (day, iid, eid)
        if key in by_key:
            raise ValueError(f"duplicate score key: {key}")
        for field in ("se", "ae", "crps", "width80", "width95"):
            if not math.isfinite(record[field]) or record[field] < 0:
                raise ValueError(f"invalid {field} for {key}")
        if any(record[field] not in (0, 1) for field in ("covered80", "covered95")):
            raise ValueError(f"invalid coverage for {key}")
        if record.get("hit") not in (None, 0, 1):
            raise ValueError(f"invalid hit for {key}")
        regime = record.get("regime", "normal")
        if regime not in REGIMES[1:]:
            raise ValueError(f"invalid regime for {key}")
        if (day, iid) in regime_for and regime_for[day, iid] != regime:
            raise ValueError(f"conflicting stored regimes: {day}/{iid}")
        regime_for[day, iid] = regime
        by_key[key] = record
        by_indicator[iid].add(day)
        valid_scores.append(record)
    history_by_date = {}
    for item in snapshots or []:
        snapshot = _dict(item)
        day = str(snapshot.get("as_of", snapshot.get("run_date", "")))
        if day and day < as_of:
            if day in history_by_date:
                raise ValueError(f"duplicate aggregate snapshot date: {day}")
            history_by_date[day] = snapshot
    previous = [history_by_date[day] for day in sorted(history_by_date)]
    prior = previous[-7] if len(previous) >= 7 else {}
    matrices, leaderboards = {}, {}
    all_counts = {}
    for window, size in settings.WINDOWS.items():
        selected_dates = {iid: sorted(by_indicator[iid])[-size:] if size is not None
                          else sorted(by_indicator[iid]) for iid in indicator_ids}
        matrix = {"schema_version": "1.0", "window": window, "as_of": as_of,
                  "reference": REFERENCE, "regimes": {}, "counts": {}, "window_dates": selected_dates}
        leaderboard = {"schema_version": "1.0", "window": window, "as_of": as_of,
                       "reference": REFERENCE, "entrants": [], "regimes": {}}
        for regime in REGIMES:
            cells, counts, pairs_by_cell, boots = {}, {}, {}, {}
            dates = sorted({day for iid in enabled for day in selected_dates[iid]
                            if regime == "all" or regime_for[day, iid] == regime})
            date_index = {day: i for i, day in enumerate(dates)}
            weights = block_bootstrap_weights(len(dates)) if dates else None
            for iid in indicator_ids:
                cells[iid], counts[iid] = {}, {}
                days = [day for day in selected_dates[iid]
                        if regime == "all" or regime_for[day, iid] == regime]
                for eid in sorted(entrant_ids):
                    observations = [by_key[day, iid, eid] for day in days if (day, iid, eid) in by_key]
                    pairs = [(a, by_key[a["forecast_run_date"], iid, REFERENCE]) for a in observations
                             if (a["forecast_run_date"], iid, REFERENCE) in by_key]
                    pairs_by_cell[iid, eid] = pairs
                    counts[iid][eid] = {"n": len(pairs), "observed_n": len(observations)}
                    cell = _cell(pairs, len(observations))
                    cells[iid][eid] = cell
                    if cell is not None:
                        # Disabled indicators retain inspectable raw stats, without a rank contribution.
                        local_dates = sorted({a["forecast_run_date"] for a, _ in pairs})
                        if iid in enabled:
                            boot = _bootstrap_ratios(pairs, date_index, weights)
                        else:
                            boot = _bootstrap_ratios(pairs, {d: i for i, d in enumerate(local_dates)},
                                                     block_bootstrap_weights(len(local_dates)))
                        boots[iid, eid] = boot
                        cell.update(_interval(1 - boot))
                        cell["sig_vs_volnaive"] = None if cell["ci_low"] is None else cell["ci_low"] > 0
            matrix["regimes"][regime], matrix["counts"][regime] = cells, counts
            rows = _leaderboard(catalog, enabled, cells, counts, pairs_by_cell, boots, window,
                                _previous_entries(prior, window) if regime == "all" else {},
                                valid_scores, as_of)
            leaderboard["regimes"][regime] = rows
            if regime == "all":
                leaderboard["entrants"] = rows
            all_counts[window, regime] = counts
        matrices[window], leaderboards[window] = matrix, leaderboard
    predictions = []
    tsfm_ids = {entry["id"] for entry in catalog if entry.get("kind") == "tsfm"}
    previous_30 = history_by_date.get(str(date.fromisoformat(as_of) - timedelta(days=30)), {})
    for indicator in indicators:
        iid = indicator["id"]
        cell = matrices["90d"]["regimes"]["all"][iid][ENSEMBLE]
        n = all_counts["90d", "all"][iid][ENSEMBLE]["n"]
        skill = cell["skill_crps"] if cell else None
        pi = _pi(skill)
        history = []
        for snapshot in previous:
            item = _snapshot_indicators(snapshot).get(iid)
            if item is not None:
                history.append({"as_of": snapshot.get("as_of", snapshot.get("run_date")),
                                "PI": item.get("PI"), "n": item.get("n")})
        history.append({"as_of": as_of, "PI": pi, "n": n})
        old_pi = _snapshot_indicators(previous_30).get(iid, {}).get("PI")
        best = [(eid, c) for eid, c in matrices["90d"]["regimes"]["all"][iid].items()
                if eid in tsfm_ids and c and c["n"] >= settings.MIN_N_RANK and c["skill_crps"] is not None]
        best.sort(key=lambda item: (-item[1]["skill_crps"], item[0]))
        regime_pi, regime_n = {}, {}
        for regime in REGIMES[1:]:
            rcell = matrices["90d"]["regimes"][regime][iid][ENSEMBLE]
            rn = all_counts["90d", regime][iid][ENSEMBLE]["n"]
            regime_n[regime] = rn
            regime_pi[regime] = _pi(rcell["skill_crps"]) if rcell and rn >= settings.MIN_N_PI else None
        predictions.append({
            "id": iid, "name": indicator.get("name", iid), "group": indicator.get("group"),
            "enabled": indicator.get("enabled", True), "n": n, "PI": pi,
            "label": pi_label(pi, n), "skill_crps_ens": skill,
            **{key: cell.get(key) if cell else None
               for key in ("win_rate", "hit_rate", "hit_n", "hit_p", "cov80", "cov95",
                           "ci_low", "ci_high", "bootstrap_valid", "bootstrap_requested")},
            "sig": None if not cell or cell.get("ci_low") is None else cell["ci_low"] > 0,
            "best_entrant": best[0][0] if best else None, "best_entrant_post_hoc": True,
            "pi_history": history[-180:],
            "pi_change_30d": pi - old_pi if pi is not None and old_pi is not None else None,
            "regime_pi": regime_pi, "regime_n": regime_n,
        })
    predictions.sort(key=lambda item: (item["PI"] is None, -(item["PI"] or 0), item["id"]))
    predictability = {"schema_version": "1.0", "as_of": as_of, "window": "90d",
                      "reference": REFERENCE, "entrant": ENSEMBLE, "pi_scale": settings.PI_SCALE,
                      "indicators": predictions}
    snapshot = {"schema_version": "1.0", "as_of": as_of, "windows": {},
                "predictability": {"indicators": [{key: row[key] for key in
                  ("id", "n", "PI", "label", "skill_crps_ens")} for row in predictions]}}
    for window in settings.WINDOWS:
        snapshot["windows"][window] = {
            "entrants": [{key: row[key] for key in ("id", "n", "paired_n_total", "observed_n_total", "skill_overall", "rank", "tier")}
                         for row in leaderboards[window]["entrants"]],
            "indicators": snapshot["predictability"]["indicators"] if window == "90d" else [],
        }
    return {"matrices": matrices, "leaderboards": leaderboards,
            "predictability": predictability, "snapshot": snapshot}
