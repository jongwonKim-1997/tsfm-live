"""Private daily collection, forward inference, outcome scoring and local export.

This journal is never a public lock-in ledger. There is deliberately no historical
date flag, credential loader, Git command or publication mode in this runner.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, time, timedelta
import hashlib
import html
import json
import math
import os
from pathlib import Path
import sys
import time as clock
import uuid
from zoneinfo import ZoneInfo

from filelock import FileLock, Timeout

# Supports direct execution, module execution and importlib-based tests.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from local_run import prepare, private_path

from tsfm_live.actuals import resolve_actuals
from tsfm_live.eligibility import confirmed_history
from tsfm_live.forecast import build_forecasts
from tsfm_live.ingest import ingest
from tsfm_live.ledger import canonical_bytes, iso, parse_ts, utcnow
from tsfm_live.models import load_models
from tsfm_live.schemas import ActualRecord, ForecastFile, ScoreRecord
from tsfm_live.score import score_pending
from tsfm_live.sources import load_indicators
from tsfm_live.transforms import inverse_transform, transform

KST = ZoneInfo("Asia/Seoul")
MODE = "private_local_daily"
MAX_INFERENCE_ATTEMPTS = 2


def atomic_json(path: Path, value, *, replace=False):
    """Flush before atomic rename. Immutable journal files never get overwritten."""
    data = canonical_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if not replace and path.exists():
            raise FileExistsError(path.name)
        # Every journal reader/writer holds the same FileLock. os.replace also
        # works atomically on Windows; interrupted temporary files are ignored.
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def bounds(now):
    local = parse_ts(now).astimezone(KST)
    scheduled = datetime.combine(local.date(), time(8, 10), KST)
    deadline = datetime.combine(local.date(), time(8, 50), KST)
    return scheduled, deadline


def forecast_window(now):
    scheduled, deadline = bounds(now)
    if now < scheduled:
        return "before_schedule"
    if now >= deadline - timedelta(minutes=2):
        return "forecast_window_closed"
    return None


def read_journal(state_dir: Path, *, current_ts=None):
    """Reject corrupt, imported/backdated, incomplete or future-created records."""
    forecasts, envelopes, actuals, scores = [], [], {}, []
    for path in sorted((state_dir / "days").glob("*/forecast.json")):
        item = json.loads(path.read_bytes())
        if item.get("mode") != MODE or item.get("public_ledger_eligible") is not False:
            raise ValueError("invalid_local_forecast_mode")
        document = item["forecast"]
        ForecastFile.model_validate(document)
        digest = hashlib.sha256(canonical_bytes(document)).hexdigest()
        if digest != item["forecast_sha256"] or path.parent.name != document["run_date"]:
            raise ValueError("local_forecast_integrity_failure")
        issued, finished = parse_ts(document["run_ts_utc"]), parse_ts(item["generated_ts_utc"])
        if current_ts is not None and finished > current_ts:
            raise ValueError("journal_clock_ahead")
        scheduled, deadline = bounds(issued)
        if not scheduled <= issued <= finished or document["run_date"] != issued.astimezone(KST).date().isoformat():
            raise ValueError("invalid_local_forecast_clock")
        for record in document["records"]:
            if record["status"] == "ok" and not finished < min(deadline, parse_ts(record["next_close_ts"])):
                raise ValueError("late_local_forecast_not_admissible")
            if record["status"] == "ok":
                context_path = state_dir / "cache/contexts" / document["run_date"] / f"{record['indicator_id']}.json"
                private = json.loads(context_path.read_bytes())
                digest = hashlib.sha256(canonical_bytes(private["context"])).hexdigest()
                if (digest != record["context_hash"] or digest != private["context_hash"]
                        or len(private["context"]) != record["context_len"]
                        or parse_ts(private["last_close_ts"]) != parse_ts(record["last_close_ts"])
                        or (record.get("last_close_value") is not None
                            and canonical_bytes(record["last_close_value"]) != canonical_bytes(private["last_close_value"]))):
                    raise ValueError("local_context_integrity_failure")
        forecasts.append((document["run_date"], document))
        envelopes.append(item)
    for path in sorted((state_dir / "batches").glob("*.json")):
        batch = json.loads(path.read_bytes())
        if batch.get("mode") != MODE:
            raise ValueError("invalid_local_batch_mode")
        for actual in batch["actuals"]:
            ActualRecord.model_validate(actual)
            key = (actual["indicator_id"], iso(parse_ts(actual["close_ts"])))
            if key in actuals:
                raise ValueError("duplicate_local_actual")
            actuals[key] = actual
        for score in batch["scores"]:
            ScoreRecord.model_validate(score)
            scores.append(score)
    keys = [(s["forecast_run_date"], s["indicator_id"], s["entrant_id"]) for s in scores]
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate_local_score")
    return forecasts, envelopes, actuals, scores


def collect(indicators, cache_dir, *, now=utcnow, fetch=ingest, attempts=2, sleep=clock.sleep):
    """Retry only failed providers; keep each successful first response frozen."""
    histories, health, tries = {}, {}, Counter()
    pending = list(indicators)
    for attempt in range(attempts):
        received, statuses = fetch(pending, now(), cache_dir)
        histories.update(received)
        for row in statuses:
            tries[row["id"]] += 1
            health[row["id"]] = {**row, "attempts": tries[row["id"]]}
        pending = [cfg for cfg in pending if health.get(cfg["id"], {}).get("status") == "source_error"]
        if not pending:
            break
        if attempt + 1 < attempts:
            sleep(min(2 ** attempt, 4))
    return histories, list(health.values())


def summary_scores(scores):
    """Keep different indicator units separate; no mixed-unit leaderboard."""
    grouped = defaultdict(list)
    for record in scores:
        if not record.get("unscorable"):
            grouped[(record["indicator_id"], record["entrant_id"])].append(record)
    return [{"indicator_id": indicator, "entrant_id": entrant, "n": len(rows),
             "mae": sum(r["ae"] for r in rows) / len(rows),
             "rmse": math.sqrt(sum(r["se"] for r in rows) / len(rows)),
             "crps": sum(r["crps"] for r in rows) / len(rows),
             "coverage80": sum(r["covered80"] for r in rows) / len(rows)}
            for (indicator, entrant), rows in sorted(grouped.items())]


def export_private(state_dir, indicators, histories, forecasts, scores, report, *, now):
    """Daily values respect display_policy; no private context is exported."""
    latest = forecasts[-1][1] if forecasts else None
    configs = {cfg["id"]: cfg for cfg in indicators}
    observations = []
    for cfg in indicators:
        history = histories.get(cfg["id"])
        rows = []
        if history is not None:
            valid = confirmed_history(history, now)
            if not valid.empty:
                zone = ZoneInfo(cfg["tz"])
                end = valid.iloc[-1]["close_ts"].tz_convert(zone).date()
                for index in range(len(valid)):
                    row = valid.iloc[index]
                    local_day = row["close_ts"].tz_convert(zone).date()
                    if local_day < end - timedelta(days=6):
                        continue
                    value = float(row["value"])
                    if cfg["display_policy"] != "level":
                        if index == 0:
                            continue
                        value = float(transform([float(valid.iloc[index - 1]["value"]), value],
                                                cfg["target_transform"])[0])
                    rows.append({"date": local_day.isoformat(), "close_ts": iso(row["close_ts"]), "value": value})
        unit = cfg.get("unit", "level") if cfg["display_policy"] == "level" else (
            "bp" if cfg["target_transform"] == "diff_bp" else "log return (%)")
        observations.append({"id": cfg["id"], "enabled": cfg["enabled"], "unit": unit,
                             "attribution": cfg.get("attribution"),
                             "value_kind": "level" if cfg["display_policy"] == "level" else "change",
                             "today": rows[-1:] if rows else [], "last7days": rows})
    displayed = []
    for record in latest["records"] if latest else []:
        cfg = configs[record["indicator_id"]]
        item = {k: record.get(k) for k in ("indicator_id", "entrant_id", "status", "skip_reason", "next_close_ts")}
        item["availability"] = "unavailable"
        if record["status"] == "ok":
            item["availability"] = "expired" if parse_ts(record["next_close_ts"]) <= now else "available"
            q = record["q"]
            if cfg["display_policy"] == "level":
                q = {key: inverse_transform(record["last_close_value"], value, record["target_transform"])
                     for key, value in q.items()}
            item.update(lower=q["0.1"], median=q["0.5"], upper=q["0.9"],
                        next_session_date=parse_ts(record["next_close_ts"]).astimezone(
                            ZoneInfo(cfg["tz"])).date().isoformat())
        displayed.append(item)
    payload = {"schema_version": 1, "mode": MODE, "public_ledger_eligible": False,
               "external_timestamp_proof": False, "generated_ts_utc": iso(now),
               "forecast_run_date": latest["run_date"] if latest else None,
               "history_basis": "latest_available_daily_observation", "history_calendar_days": 7,
               "report": report, "observations": observations, "forecasts": displayed,
               "metrics": summary_scores(scores), "score_count": len(scores)}
    folder = state_dir / "reports"
    atomic_json(folder / "latest.json", payload, replace=True)
    license_file = Path(__file__).resolve().parents[1] / "site/public/licenses/tirex.txt"
    if license_file.is_file():
        (folder / "tirex-license.txt").write_bytes(license_file.read_bytes())
    def cell(value):
        return html.escape(str(value))
    rows = "".join("<tr>" + "".join(f"<td>{cell(row.get(k, '—'))}</td>" for k in
                   ("indicator_id", "entrant_id", "status", "availability", "next_session_date", "lower", "median", "upper"))
                   + "</tr>" for row in displayed)
    values = "".join(f"<li>{cell(row['id'])} ({cell(row['unit'])}): " +
                     cell(row["today"][0]["value"] if row["today"] else "관측값 없음") +
                     " — " + cell(row.get("attribution") or "") + "</li>" for row in observations)
    metric_rows = "".join("<tr>" + "".join(f"<td>{cell(row[k])}</td>" for k in
                          ("indicator_id", "entrant_id", "n", "mae", "rmse", "crps", "coverage80")) + "</tr>"
                          for row in payload["metrics"])
    page = f'''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>TSFM 로컬 일일 기록</title><style>body{{font:16px system-ui;background:#101827;color:#e4eaf4;margin:2rem}}
table{{border-collapse:collapse;width:100%;font-size:14px}}td,th{{padding:.5rem;border:1px solid #45546b;text-align:left}}
.scroll{{overflow:auto}}.notice{{border:1px solid #f4b35e;padding:1rem}}a{{color:#86c4ff}}</style>
<h1>TSFM 로컬 일일 기록</h1><p class="notice">개인 진단 기록입니다. 공개 확정 예측·외부 타임스탬프·공식 순위가 아닙니다.
예측은 실제 실행 시각을 사용합니다. 만료된 예측은 내일의 예측이 아닙니다. 과거 다운로드는 당시 이용 가능성을 증명하지 않습니다.</p>
<p>갱신: {cell(iso(now))} · 실행일(KST): {cell(report['run_date'])} · 상태: {cell(report['status'])}
 · 예측 기준일: {cell(payload['forecast_run_date'])}</p><p><a href="latest.json">전체 상태·최근 7일 관측값·평가 JSON</a></p>
<h2>최근 일별 실제 관측값</h2><p>오늘은 최신 이용 가능한 일별 관측값입니다. 장중 현재값이 아닙니다.</p><ul>{values}</ul>
<h2>모델별 예측</h2><div class="scroll"><table><tr><th>지표</th><th>모델</th><th>상태</th><th>유효성</th>
<th>목표일(지표 현지)</th><th>하위 10%</th><th>중앙값</th><th>상위 90%</th></tr>{rows}</table></div>
<h2>누적 로컬 평가</h2><p>지표별 목표 단위로 계산하며 지표 간 통합 순위를 만들지 않습니다.</p><div class="scroll"><table>
<tr><th>지표</th><th>모델</th><th>표본</th><th>MAE</th><th>RMSE</th><th>CRPS</th><th>80% 포함률</th></tr>{metric_rows}</table></div>
<p>Built with technology from NXAI · <a href="tirex-license.txt">TiRex license</a></p></html>'''
    temporary = folder / f".index.{uuid.uuid4().hex}.tmp"
    temporary.write_text(page, encoding="utf-8")
    os.replace(temporary, folder / "index.html")
    return {"path": "reports/index.html", "forecasts": len(displayed), "scores": len(scores)}


def run_daily(root, state_dir, *, now=utcnow, evaluate_only=False, fetch=ingest,
              predict=build_forecasts, runtime_check=lambda: None, probe=None, retries=2, sleep=clock.sleep):
    root, state_dir = Path(root).resolve(), private_path(Path(state_dir), Path(root).resolve())
    started = now()
    day = started.astimezone(KST).date().isoformat()
    attempt_id = started.strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid.uuid4().hex[:8]
    report = {"schema_version": 1, "mode": MODE, "run_date": day, "timezone": "Asia/Seoul",
              "attempt_id": attempt_id, "started_ts_utc": iso(started), "public_ledger_eligible": False,
              "live_publication": False, "status": "running", "stages": {}, "forecast_counts": {}}
    state_dir.mkdir(parents=True, exist_ok=True)
    lock = FileLock(state_dir / "daily.lock", timeout=0)
    try:
        lock.acquire()
    except Timeout:
        return {**report, "status": "skipped", "reason": "already_running"}, 0
    def stage(name, action, attempts=1):
        for attempt in range(1, attempts + 1):
            stage_start = now()
            try:
                result = action()
                report["stages"][name] = {"status": "ok", "attempts": attempt,
                                          "started_ts_utc": iso(stage_start), "finished_ts_utc": iso(now())}
                return result
            except Exception as exc:
                # Error text/tracebacks may contain provider credentials or URLs.
                report["stages"][name] = {"status": "failed", "attempts": attempt,
                    "started_ts_utc": iso(stage_start), "finished_ts_utc": iso(now()),
                    "error_type": type(exc).__name__}
                if attempt < attempts:
                    sleep(min(2 ** (attempt - 1), 4))
        return None
    try:
        indicators = load_indicators(root / "pipeline/tsfm_live/config/indicators.yaml")
        models = sorted(load_models(root / "pipeline/tsfm_live/config/models.yaml"), key=lambda m: m["kind"] == "ensemble")
        journal = stage("journal", lambda: read_journal(state_dir, current_ts=now()))
        if journal is None:
            report["status"] = "failed"
            return report, 1
        forecasts, envelopes, actuals, scores = journal
        collection = stage("collect", lambda: collect(indicators, state_dir / "cache", now=now,
                                                       fetch=fetch, attempts=retries, sleep=sleep))
        histories, health = collection if collection else ({}, [])
        report["sources"] = health
        if any(row["status"] == "source_error" for row in health):
            report["stages"]["collect"]["status"] = "partial"
        existing = next((doc for date, doc in forecasts if date == day), None)
        reason = "already_recorded" if existing else "evaluate_only" if evaluate_only else forecast_window(now())
        if now().astimezone(KST).date().isoformat() != day:
            reason = "kst_date_changed"
        day_dir = state_dir / "days" / day
        if not reason and len(list(day_dir.glob("inference-attempt-*.json"))) >= MAX_INFERENCE_ATTEMPTS:
            reason = "inference_attempt_limit"
        if reason:
            report["stages"]["forecast"] = {"status": "skipped", "reason": reason}
        elif not collection:
            report["stages"]["forecast"] = {"status": "skipped", "reason": "collection_failed"}
        else:
            def make_forecast():
                runtime_check()
                issued = now()
                if forecast_window(issued) or issued.astimezone(KST).date().isoformat() != day:
                    report["forecast_window_elapsed"] = True
                    return None
                atomic_json(day_dir / f"inference-attempt-{attempt_id}.json",
                            {"attempt_id": attempt_id, "started_ts_utc": iso(issued), "mode": MODE})
                _, deadline = bounds(issued)
                document = predict(indicators, models, histories, issued, deadline, day,
                                   "local-" + attempt_id, state_dir / "cache", now=now, dry_run=False)
                finished = now()
                # Time can advance between the builder's final check and return.
                for record in document["records"]:
                    if record["status"] == "ok" and finished >= min(deadline, parse_ts(record["next_close_ts"])):
                        record.update(status="void", skip_reason="local_completion_late", q={}, mean=None,
                                      quantile_method=None, n_samples=None, contributors=[])
                ForecastFile.model_validate(document)
                envelope = {"mode": MODE, "public_ledger_eligible": False, "generated_ts_utc": iso(finished),
                            "forecast_sha256": hashlib.sha256(canonical_bytes(document)).hexdigest(),
                            "forecast": document, "indicators": indicators, "sources": health}
                atomic_json(day_dir / "forecast.json", envelope)
                return document
            document = stage("forecast", make_forecast)
            if document:
                forecasts, envelopes, actuals, scores = read_journal(state_dir, current_ts=now())
                existing = document
            elif report.get("forecast_window_elapsed"):
                report["stages"]["forecast"] = {"status": "skipped", "reason": "forecast_window_closed"}
        if existing:
            report["forecast_counts"] = dict(Counter(r["status"] for r in existing["records"]))
            report["forecast_skip_reasons"] = dict(Counter(r["skip_reason"] for r in existing["records"]
                                                           if r.get("skip_reason")))
        # Probe is off the inference critical path; default probe never networks.
        if probe:
            probe_result = stage("source_audit", lambda: probe(state_dir / "source-audit", now=now()))
            if probe_result:
                report["source_audit"] = {"network_performed": probe_result.get("network_performed"),
                    "auto_enabled": probe_result.get("auto_enabled", False),
                    "active_status_counts": dict(Counter(row.get("collection_status", "unknown")
                        for row in probe_result.get("indicators", []) if row.get("enabled"))),
                    "candidate_status_counts": dict(Counter(row.get("collection_status", "unknown")
                        for row in probe_result.get("candidates", [])))}
                bad = [row["id"] for row in probe_result.get("indicators", [])
                       if row.get("enabled") and row.get("collection_status") in {"source_error", "lagging", "no_observations"}]
                if bad:
                    report["stages"]["source_audit"]["status"] = "partial"
                    report["source_audit"]["unhealthy_indicators"] = bad
        else:
            report["stages"]["source_audit"] = {"status": "skipped", "reason": "probe_unavailable"}
        def evaluate():
            evaluated = now()
            fresh, revisions = [], []
            all_actuals = dict(actuals)
            for envelope in envelopes:
                doc = envelope["forecast"]
                if parse_ts(envelope["generated_ts_utc"]) > evaluated:
                    raise ValueError("journal_clock_ahead")
                # Changing a configured source never silently grades an old
                # forecast against a different series or target definition.
                old = {c["id"]: c for c in envelope["indicators"]}
                safe_history = {cfg["id"]: histories[cfg["id"]] for cfg in indicators if cfg["id"] in histories
                                and cfg["id"] in old and all(cfg.get(k) == old[cfg["id"]].get(k)
                                for k in ("source", "target_transform", "display_policy", "tz", "calendar",
                                          "close_time_local", "unit", "min_history"))}
                records = resolve_actuals([(doc["run_date"], doc)], {}, safe_history,
                                          envelope["indicators"], health, state_dir / "cache", evaluated)
                for actual in records:
                    ActualRecord.model_validate(actual)
                    key = (actual["indicator_id"], iso(parse_ts(actual["close_ts"])))
                    old_actual = all_actuals.get(key)
                    if old_actual:
                        if canonical_bytes({k: old_actual[k] for k in ("value", "y")}) != canonical_bytes(
                                {k: actual[k] for k in ("value", "y")}):
                            revisions.append({"indicator_id": key[0], "close_ts": key[1],
                                "status": "revision_observed_not_applied", "original": old_actual,
                                "observed": actual})
                    else:
                        all_actuals[key] = actual
                        fresh.append(actual)
            scored = score_pending(forecasts, all_actuals, scores, evaluated)
            # Empty batches are valid evidence for this attempt; later attempts
            # append new batches and therefore can collect after-close outcomes.
            atomic_json(state_dir / "batches" / f"{attempt_id}.json", {"mode": MODE,
                        "evaluated_ts_utc": iso(evaluated), "actuals": fresh, "scores": scored,
                        "revision_observations": revisions})
            report["evaluation"] = {"new_actuals": len(fresh), "new_scores": len(scored),
                "unscorable": sum(bool(s.get("unscorable")) for s in scored),
                "total_scores": len(scores) + len(scored), "revisions_observed": len(revisions)}
            return scored
        stage("evaluate", evaluate)
        # A successful batch persists even if export crashes; replay reads it and
        # score_pending deduplicates without rerunning inference.
        _, _, _, scores = read_journal(state_dir, current_ts=now())
        report["status"] = "partial" if any(s["status"] in {"failed", "partial"} for s in report["stages"].values()) else "ok"
        if report["forecast_counts"].get("failed") or report["forecast_counts"].get("void"):
            report["status"] = "partial"
        if report.get("evaluation", {}).get("revisions_observed"):
            report["status"] = "partial"
        export_result = stage("export", lambda: export_private(state_dir, indicators, histories, forecasts,
                                                               scores, report, now=now()), attempts=retries)
        if export_result:
            report["export"] = export_result
        else:
            report["status"] = "partial"
        return report, 1 if report["status"] in {"failed", "partial"} else 0
    except Exception as exc:
        report["status"] = "failed"
        report["error_type"] = type(exc).__name__
        return report, 1
    finally:
        report["finished_ts_utc"] = iso(now())
        try:
            atomic_json(state_dir / "attempts" / f"{attempt_id}.json", report)
            atomic_json(state_dir / "latest-run.json", report, replace=True)
            exported = state_dir / "reports/latest.json"
            if report["stages"].get("export", {}).get("status") == "ok" and exported.is_file():
                payload = json.loads(exported.read_bytes())
                payload["report"] = report
                atomic_json(exported, payload, replace=True)
        finally:
            lock.release()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-env-file", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--evaluate-only", action="store_true")
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--source-probe-network", action="store_true")
    parser.add_argument("--retries", type=int, choices=range(1, 4), default=2)
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    state_dir = args.state_dir or root.parents[1] / "work/tsfm-local-daily"
    old_env = dict(os.environ)
    try:
        state_dir = private_path(state_dir, root)
        preflight, safe_env = prepare(root, args.runtime_env_file, state_dir / "cache",
                                      verify_models=args.check_only)
        if args.check_only:
            print(json.dumps({"event": "daily_preflight_ok", **preflight, "mode": MODE,
                              "state_dir": str(state_dir), "forecast_window": forecast_window(utcnow())}))
            return 0
        os.environ.clear()
        os.environ.update(safe_env)
        try:
            from tsfm_live.source_probe import run_probe
            def probe(path, now):
                return run_probe(path, network=args.source_probe_network, now=now)
        except ImportError:
            probe = None
        def runtime_check():
            _, validated_env = prepare(root, args.runtime_env_file, state_dir / "cache")
            os.environ.clear()
            os.environ.update(validated_env)
        report, code = run_daily(root, state_dir, evaluate_only=args.evaluate_only, retries=args.retries,
                                runtime_check=runtime_check, probe=probe)
        print(json.dumps({"event": "daily_local_complete", **report}, ensure_ascii=False), flush=True)
        return code
    except Exception as exc:
        print(json.dumps({"event": "daily_local_failed", "error_type": type(exc).__name__}), file=sys.stderr)
        return 1
    finally:
        os.environ.clear()
        os.environ.update(old_env)


if __name__ == "__main__":
    raise SystemExit(main())
