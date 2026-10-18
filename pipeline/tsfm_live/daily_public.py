"""Commercial-source daily projection, with immutable, genuinely issued forecasts.

Only the indicator's own daily levels enter each model. Source session dates and
Korean issue dates are separate. This is not the prospective benchmark ledger.
"""

from __future__ import annotations

from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

from .calendars import session_closes
from .eligibility import confirmed_history
from .forecast import model_predict
from .ledger import canonical_bytes, iso, parse_ts, utcnow
from .models.base import derive_seed

KST = ZoneInfo("Asia/Seoul")
MODEL_IDS = {"chronos-2", "chronos-bolt-base"}
ECB_TERMS = "https://www.ecb.europa.eu/services/using-our-site/disclaimer/html/index.en.html"
TREASURY_TERMS = "https://www.copyright.gov/title17/92chap1.html#105"


def indicator_configs():
    rows = []
    for iid, pair, name, unit in [
        ("eurusd", "EURUSD", "EUR/USD · ECB reference", "USD/EUR"),
        ("usdjpy", "USDJPY", "USD/JPY · ECB derived cross", "JPY/USD"),
        ("ecb-usdkrw", "USDKRW", "USD/KRW · ECB derived cross", "KRW/USD"),
    ]:
        rows.append(
            dict(
                id=iid,
                name=name,
                unit=unit,
                group="fx",
                calendar="ECB",
                close_time_local="16:00",
                tz="Europe/Berlin",
                enabled=True,
                source={"adapter": "ecb", "params": {"pair": pair}},
                license_id="ECB-reuse",
                license_url=ECB_TERMS,
                attribution="Source: European Central Bank. Source data is available free from the ECB. "
                + ("Cross rate calculated by TSFM Live. " if pair != "EURUSD" else "")
                + "Forecasts calculated by TSFM Live; not ECB forecasts.",
            )
        )
    for years in (2, 10):
        rows.append(
            dict(
                id=f"ust{years}y",
                name=f"US Treasury {years}Y · par yield",
                unit="%",
                group="rates",
                calendar="UST",
                close_time_local="15:30",
                tz="America/New_York",
                enabled=True,
                source={"adapter": "ustreasury", "params": {"field": f"BC_{years}YEAR"}},
                license_id="US-government-work",
                license_url=TREASURY_TERMS,
                attribution="Source: U.S. Department of the Treasury. Official fitted par yield, "
                "not an individual bond closing yield. Forecasts calculated by TSFM Live.",
            )
        )
    return rows


def public_models(models):
    result = [
        dict(m, device="cuda", worker_env="TSFM_PYTHON_DAILY_GPU") for m in models if m["id"] in MODEL_IDS
    ]
    if {m["id"] for m in result} != MODEL_IDS or any(m["license"] != "apache-2.0" for m in result):
        raise ValueError("commercial_model_configuration_mismatch")
    return result


def dated_points(cfg, frame, now):
    data = confirmed_history(frame, now)
    fetched = parse_ts(frame.attrs["fetched_ts_utc"])
    if fetched > now:
        raise ValueError("future_source_fetch")
    data = data.loc[data["close_ts"] <= fetched]
    return [
        {
            "date": p.close_ts.tz_convert(cfg["tz"]).date().isoformat(),
            "close_ts": iso(p.close_ts),
            "value": float(p.value),
        }
        for p in data.itertuples()
    ]


def forecast_targets(cfg, last_date, issue_day):
    """All source sessions through tomorrow (or the first subsequent open day)."""
    next_day = issue_day + timedelta(days=1)
    candidates = session_closes(cfg, next_day, next_day + timedelta(days=14))
    if not candidates:
        raise ValueError("target_calendar_unavailable")
    end = candidates[0].astimezone(ZoneInfo(cfg["tz"])).date()
    targets = session_closes(cfg, last_date + timedelta(days=1), end)
    if not 1 <= len(targets) <= 10:
        raise ValueError("source_too_stale")
    return targets


def read_issues(state, now):
    issues = []
    for path in sorted((Path(state) / "issued").glob("*/*.json")):
        envelope = json.loads(path.read_bytes())
        item = envelope["forecast"]
        if hashlib.sha256(canonical_bytes(item)).hexdigest() != envelope["sha256"]:
            raise ValueError("forecast_archive_integrity_failure")
        issued = parse_ts(item["issued_at"])
        if issued > now or item["issue_date"] != issued.astimezone(KST).date().isoformat():
            raise ValueError("forecast_archive_invalid_issue_time")
        if (
            path.parent.name != item["issue_date"]
            or path.stem != f"{item['indicator_id']}--{item['model_id']}"
        ):
            raise ValueError("forecast_archive_identity_mismatch")
        if item["model_id"] not in MODEL_IDS or item["input_basis"] != "own_daily_levels_only":
            raise ValueError("forecast_archive_invalid_model")
        if not item["points"] or any(parse_ts(p["close_ts"]) <= issued for p in item["points"]):
            raise ValueError("forecast_archive_backdated_target")
        issues.append(item)
    return issues


def build_daily(configs, models, histories, state, *, now, save, clock=utcnow, predict=model_predict):
    now = parse_ts(now)
    day = now.astimezone(KST).date()
    previous_day = (day - timedelta(days=1)).isoformat()
    issues = read_issues(state, now)
    rows, failures = [], []
    for cfg in configs:
        iid = cfg["id"]
        points, error = [], None
        try:
            if iid not in histories:
                raise ValueError("source_unavailable")
            points = dated_points(cfg, histories[iid], now)
            if len(points) < 128:
                raise ValueError("insufficient_history")
            last = points[-1]
            expected = [t for t in session_closes(cfg, day - timedelta(days=15), day) if t < now]
            # Allow publication latency, but never advance forecasts on a missing
            # completed source session or fill holidays with invented levels.
            if expected and parse_ts(last["close_ts"]) < expected[-1]:
                raise ValueError("awaiting_latest_source_release")
            context = np.array([p["value"] for p in points[-512:]])
            dates = [p["date"] for p in points[-512:]]
            expected_context = session_closes(
                cfg, date.fromisoformat(dates[0]), date.fromisoformat(dates[-1])
            )
            if len(expected_context) != len(dates):
                raise ValueError("source_history_gap")
            targets = forecast_targets(cfg, date.fromisoformat(last["date"]), day)
            for model in models:
                if any(
                    p["indicator_id"] == iid
                    and p["model_id"] == model["id"]
                    and p["issue_date"] == day.isoformat()
                    for p in issues
                ):
                    continue
                try:
                    output = predict(
                        model,
                        context.copy(),
                        horizon=len(targets),
                        seed=derive_seed(day.isoformat(), iid, model["id"]),
                        timeout=240,
                    )
                    finished = parse_ts(clock())
                    if finished.astimezone(KST).date() != day:
                        raise ValueError("issue_date_changed_during_inference")
                    steps = [output] if len(targets) == 1 else output.steps
                    forecast = [
                        {
                            "date": t.astimezone(ZoneInfo(cfg["tz"])).date().isoformat(),
                            "close_ts": iso(t),
                            "median": float(v.quantiles["0.5"]),
                            "lower": float(v.quantiles["0.1"]),
                            "upper": float(v.quantiles["0.9"]),
                        }
                        for t, v in zip(targets, steps)
                        if t > finished
                    ]
                    if not forecast:
                        raise ValueError("target_closed_during_inference")
                    item = {
                        "indicator_id": iid,
                        "model_id": model["id"],
                        "model_name": model["name"],
                        "model_revision": model["hf_revision"],
                        "model_license": "apache-2.0",
                        "issue_date": day.isoformat(),
                        "issued_at": iso(finished),
                        "device": "cuda",
                        "input_basis": "own_daily_levels_only",
                        "input_count": len(context),
                        "input_sha256": hashlib.sha256(canonical_bytes(context.tolist())).hexdigest(),
                        "anchor": last,
                        "points": forecast,
                    }
                    save(
                        Path(state) / "issued" / day.isoformat() / f"{iid}--{model['id']}.json",
                        {"forecast": item, "sha256": hashlib.sha256(canonical_bytes(item)).hexdigest()},
                    )
                    issues.append(item)
                except Exception as exc:
                    failures.append(
                        {"indicator_id": iid, "model_id": model["id"], "error_type": type(exc).__name__}
                    )
        except Exception as exc:
            error = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
            failures.append({"indicator_id": iid, "error_type": type(exc).__name__, "reason": error})
        relevant = [p for p in issues if p["indicator_id"] == iid]
        current = [p for p in relevant if p["issue_date"] == day.isoformat()]
        previous = [p for p in relevant if p["issue_date"] == previous_day]
        archive = [p for p in relevant if p["issue_date"] >= (day - timedelta(days=30)).isoformat()]
        actual = next((p for p in points if p["date"] == day.isoformat()), None)
        closed = not session_closes(cfg, day, day)
        rows.append(
            {
                "id": iid,
                "name": cfg["name"],
                "group": cfg["group"],
                "unit": cfg["unit"],
                "source_timezone": cfg["tz"],
                "source_id": cfg["source"]["adapter"],
                "license_id": cfg["license_id"],
                "license_url": cfg["license_url"],
                "attribution": cfg["attribution"],
                "public_export": True,
                "actual_status": "available" if actual else "market_closed" if closed else "awaiting_release",
                "source_error": error,
                "latest_actual": points[-1] if points else None,
                "today_actual": actual,
                "history": points[-32:],
                "forecasts": current,
                "previous_forecasts": previous,
                "forecast_history": archive,
            }
        )
    return {
        "schema_version": "daily-public-v1",
        "frequency": "1d",
        "run_id": "daily-" + now.strftime("%Y%m%dT%H%M%S%fZ"),
        "generated_ts_utc": iso(clock()),
        "date": day.isoformat(),
        "timezone": "Asia/Seoul",
        "inference_mode": "zero_shot",
        "input_basis": "own_daily_levels_only",
        "device": "cuda",
        "public_ledger_eligible": False,
        "indicators": rows,
        "pending_indicators": ["KOSPI", "S&P 500", "NASDAQ Composite"],
        "pending_reason": "Commercial public-display data licence not yet obtained.",
    }, failures
