from datetime import timedelta

from .config.settings import ACTUAL_GRACE_DAYS
from .ledger import iso, parse_ts
from .metrics import score_forecast


def score_pending(forecasts, actuals, previous_scores, run_ts):
    run_ts = parse_ts(run_ts)
    actuals = {(indicator, iso(parse_ts(close))): actual for (indicator, close), actual in actuals.items()}
    done = {(s["forecast_run_date"], s["indicator_id"], s["entrant_id"]) for s in previous_scores}
    out = []
    for _, doc in forecasts:
        for f in doc["records"]:
            key = (doc["run_date"], f["indicator_id"], f["entrant_id"])
            if key in done or f["status"] != "ok" or parse_ts(f["next_close_ts"]) >= run_ts:
                continue
            s = {"forecast_run_date": doc["run_date"], "indicator_id": f["indicator_id"],
                 "entrant_id": f["entrant_id"], "regime": f["regime"], "scored_ts_utc": iso(run_ts)}
            actual = actuals.get((f["indicator_id"], iso(parse_ts(f["next_close_ts"]))))
            available = (actual and actual.get("status") != "void"
                         and (not actual.get("published_ts") or parse_ts(actual["published_ts"]) <= run_ts)
                         and parse_ts(actual["fetched_ts_utc"]) <= run_ts)
            if available:
                s.update(score_forecast(actual["y"], f["q"], f["target_transform"]))
                s["unscorable"] = None
            elif run_ts >= parse_ts(f["next_close_ts"]) + timedelta(days=ACTUAL_GRACE_DAYS):
                s["unscorable"] = "actual_unavailable"
            else:
                continue
            out.append(s)
            done.add(key)
    return out
