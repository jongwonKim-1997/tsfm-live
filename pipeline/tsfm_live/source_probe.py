"""Read-only source readiness inventory; never enables a benchmark or writes its ledger.

Only the already-reviewed ECB and US Treasury feeds are downloaded. Reports contain
dates, counts and response digests, never market levels or credential values.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import socket
import ssl
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

import certifi

from .calendars import as_utc, session_bounds, session_closes
from .sources import load_indicators
from .sources.base import REPO_ROOT, SourceError
from .sources.ecb import ECBSource
from .sources.ustreasury import USTreasurySource

UTC = timezone.utc
MAX_BYTES = 16 * 1024 * 1024
TIMEOUT_SECONDS = 12
ECBS = {
    "eurusd": ("USD",), "usdjpy": ("USD", "JPY"),
    "gbpusd_ecb": ("USD", "GBP"), "audusd_ecb": ("USD", "AUD"),
    "usdcad_ecb": ("USD", "CAD"), "usdchf_ecb": ("USD", "CHF"),
    "usdkrw_ecb": ("USD", "KRW"),
}
USTS = {"ust10y": "BC_10YEAR", "ust2y": "BC_2YEAR", "ust5y": "BC_5YEAR", "ust30y": "BC_30YEAR"}
REQUIREMENTS = {
    "kospi": ("ECOS_API_KEY", "Verify ECOS series metadata, KRX origin rights and final publication time."),
    "kosdaq": ("ECOS_API_KEY", "Resolve exact ECOS series, KRX origin rights and final publication time."),
    "usdkrw": ("ECOS_API_KEY", "Identify the Seoul-close series; base rates and ECB crosses are different targets."),
    "ktb3y": ("ECOS_API_KEY", "Verify ECOS maturity, yield definition, publication lag and originating-provider rights."),
    "ktb10y": ("ECOS_API_KEY", "Verify ECOS maturity, yield definition, publication lag and originating-provider rights."),
    "spx": ("FRED_API_KEY", "FRED SP500 requires S&P redistribution permission; a FRED key does not grant it."),
    "ndq": ("FRED_API_KEY", "FRED NASDAQCOM is copyrighted; obtain Nasdaq public/derived-use permission."),
    "wti": (None, "Obtain an entitled front-month settlement feed and define rolls; EIA RWTC is spot, not this target."),
    "gold": (None, "Choose the gold benchmark; LBMA/IBA historical acquisition and public use require a licence."),
    "vix": (None, "Obtain Cboe permission for storage/public derived use and verify daily final publication timing."),
    "btcusd": (None, "Confirm Binance Vision noncommercial CC BY-NC-SA obligations and API scope; BTCUSDT remains a USD proxy."),
}


def _iso(ts):
    return as_utc(ts).isoformat().replace("+00:00", "Z")


def _download(url: str) -> bytes:
    """Two bounded attempts, TLS verification, no credential-bearing URLs."""
    context = ssl.create_default_context()
    context.load_verify_locations(cafile=certifi.where())
    for attempt in range(2):
        try:
            request = Request(url, headers={"User-Agent": "TSFM-Live/0.1 source-availability-probe",
                                           "Accept": "application/xml"})
            with urlopen(request, timeout=TIMEOUT_SECONDS, context=context) as response:
                body = response.read(MAX_BYTES + 1)
            if len(body) > MAX_BYTES:
                raise SourceError("response_size_limit")
            return body
        except HTTPError as exc:
            if exc.code < 500 and exc.code != 429 or attempt == 1:
                raise SourceError(f"http_{exc.code}") from None
        except (URLError, TimeoutError, socket.timeout, ConnectionError):
            if attempt == 1:
                raise SourceError("network_error") from None
        time.sleep(0.5)
    raise SourceError("network_error")


def _read_endpoint(endpoint_id, url, endpoints):
    row = {"id": endpoint_id, "url": url, "status": "not_checked"}
    endpoints.append(row)
    try:
        body = _download(url)
        row.update(status="ok", fetched_ts_utc=_iso(datetime.now(UTC)),
                   body_sha256=hashlib.sha256(body).hexdigest(), bytes=len(body))
        return body
    except Exception as exc:
        # Even custom HTTP/proxy errors can contain credentials. Never serialize them.
        row.update(status="error", error_type=type(exc).__name__)
        if isinstance(exc, SourceError) and re.fullmatch(r"http_[0-9]{3}|network_error|response_size_limit", str(exc)):
            row["error_code"] = str(exc)
        return None


def _ecb_dates(body, now):
    root = ET.fromstring(body)
    nodes = [node for node in root.iter() if "time" in node.attrib]
    if not nodes:
        raise SourceError("ECB dated Cube absent")
    start = now.date() - timedelta(days=730)
    cfg = {"calendar": "ECB", "close_time_local": "16:00"}
    closes = {ts.astimezone(ZoneInfo("Europe/Berlin")).date(): ts
              for ts in session_closes(cfg, start, now.date())}
    result = {key: [] for key in ECBS}
    seen = set()
    for node in nodes:
        day = date.fromisoformat(node.attrib["time"])
        if day < start or day > now.date():
            continue
        if day in seen or day not in closes:
            raise SourceError("ECB duplicate or non-session date")
        seen.add(day)
        if closes[day] >= now:
            continue
        rates = {child.attrib["currency"]: float(child.attrib["rate"])
                 for child in node if "currency" in child.attrib and "rate" in child.attrib}
        for key, currencies in ECBS.items():
            if all(currency in rates and math.isfinite(rates[currency]) and rates[currency] > 0
                   for currency in currencies):
                result[key].append(closes[day])
    return result


def _network_observations(now, output_dir, endpoints):
    dates, failed = {}, set()
    body = _read_endpoint("ecb_reference", ECBSource.endpoint, endpoints)
    if body is not None:
        try:
            dates.update(_ecb_dates(body, now))
        except (ValueError, TypeError, KeyError, OverflowError, ET.ParseError, SourceError):
            endpoints[-1]["status"] = "invalid_payload"
            failed.update(ECBS)
    else:
        failed.update(ECBS)
    treasury = []
    for year in (now.year - 1, now.year):
        url = USTreasurySource.endpoint + "?" + urlencode({"data": "daily_treasury_yield_curve", "field_tdr_date_value": year})
        body = _read_endpoint(f"treasury_par_{year}", url, endpoints)
        if body is None:
            failed.update(USTS)
        else:
            treasury.append((body, endpoints[-1]))
    for key, field in USTS.items():
        cfg = {"id": key, "calendar": "UST", "source": {"params": {"field": field}}}
        observations = []
        for body, endpoint in treasury:
            try:
                frame = USTreasurySource(cfg, output_dir).parse(body, cfg, date(now.year - 1, 1, 1), now)
                observations.extend(as_utc(ts) for ts in frame.close_ts if as_utc(ts) < now)
            except (ValueError, TypeError, KeyError, OverflowError, ET.ParseError, SourceError):
                endpoint["status"] = "invalid_payload"
                failed.add(key)
        if len(observations) != len(set(observations)):
            failed.add(key)
        dates[key] = sorted(set(observations))
    return dates, failed


def _availability(key, calendar, now, network, dates, failed):
    cfg = {"calendar": calendar, "close_time_local": "16:00"}
    expected, next_close = session_bounds(cfg, now)
    available = sorted(dates.get(key, []))
    latest = available[-1] if available else None
    expected_span = session_closes(cfg, available[0].date(), expected.date()) if available else []
    if not network:
        status = "not_checked"
    elif key in failed:
        status = "source_error"
    elif latest is None:
        status = "no_observations"
    else:
        status = "fresh" if latest == expected else "lagging"
    return {"collection_status": status, "latest_close_ts": _iso(latest) if latest else None,
            "expected_close_ts": _iso(expected), "next_close_ts": _iso(next_close),
            "history_observations_checked": len(available),
            "history_start_ts": _iso(available[0]) if available else None,
            "minimum_301_levels_present": len(available) >= 301,
            "missing_sessions_in_checked_span": len(set(expected_span) - set(available)) if available else None,
            "publication_timestamp_available": False,
            "publication_note": "Scheduled observation boundary only; feed receipt proves availability at fetch time, not historical publication time."}


def run_probe(output_dir, network=False, now=None):
    """Write a private report and return it. Missing sources do not stop the inventory."""
    output_dir = Path(output_dir).expanduser().resolve()
    roots = {REPO_ROOT, Path(os.environ.get("TSFM_REPO_ROOT", REPO_ROOT)).resolve()}
    if any(output_dir == root or root in output_dir.parents for root in roots):
        raise ValueError("Probe reports must be outside the public repository")
    now = as_utc(now or datetime.now(UTC))
    output_dir.mkdir(parents=True, exist_ok=True)
    report = {"schema_version": "1.0", "checked_at_utc": _iso(now),
              "network_performed": bool(network), "auto_enabled": False,
              "scope": "read_only_source_availability_not_forecast_readiness",
              "indicators": [], "candidates": [], "endpoints": []}
    dates, failed = _network_observations(now, output_dir, report["endpoints"]) if network else ({}, set())
    for cfg in load_indicators():
        key = cfg["id"]
        row = {"id": key, "name": cfg["name"], "enabled": bool(cfg["enabled"]),
               "source": cfg["source"]["adapter"], "required_credentials": [], "blockers": []}
        if key in {"eurusd", "usdjpy", "ust10y"}:
            row.update(_availability(key, "ECB" if key in ECBS else "UST", now, network, dates, failed))
            row["rights_status"] = "reviewed_attribution_required"
            if row["collection_status"] not in {"fresh", "not_checked"}:
                row["blockers"].append(row["collection_status"])
        else:
            credential, reason = REQUIREMENTS.get(key, (None, "Manual source review required."))
            row.update(collection_status="blocked_not_requested", rights_status="requirements_pending",
                       latest_close_ts=None, expected_close_ts=None, publication_timestamp_available=False)
            row["blockers"].append(reason)
            if credential:
                row["required_credentials"] = [{"name": credential, "present": bool(os.environ.get(credential)),
                                                "sufficient_to_enable": False}]
        report["indicators"].append(row)
    formulas = {"gbpusd_ecb": "EURUSD / EURGBP", "audusd_ecb": "EURUSD / EURAUD",
                "usdcad_ecb": "EURCAD / EURUSD", "usdchf_ecb": "EURCHF / EURUSD",
                "usdkrw_ecb": "EURKRW / EURUSD"}
    for key in [*formulas, "ust2y", "ust5y", "ust30y"]:
        is_ecb = key in formulas
        row = {"id": key, "source": "ecb" if is_ecb else "ustreasury", "enabled": False,
               "exact_existing_target": False, "series": formulas[key] if is_ecb else USTS[key],
               "rights_status": "reviewed_attribution_required", "required_credentials": [],
               "unit": "quote_currency_per_base_currency" if is_ecb else "annual_yield_percent",
               "readiness": "candidate_requires_explicit_new_indicator",
               "blockers": ["Add a distinct indicator identity, validate adapter and context continuity, then review before enabling."]}
        row.update(_availability(key, "ECB" if is_ecb else "UST", now, network, dates, failed))
        if key == "usdkrw_ecb":
            row["blockers"].append("ECB reference cross is not the configured Seoul-close USDKRW target.")
        report["candidates"].append(row)
    # Exclusive immutable report plus atomic mutable pointer, all outside the repo.
    filename = now.strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid.uuid4().hex[:8] + ".json"
    report["report_path"] = str(output_dir / filename)
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with (output_dir / filename).open("x", encoding="utf-8") as handle:
        handle.write(payload)
    temporary = output_dir / (".latest-" + uuid.uuid4().hex + ".tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(output_dir / "latest.json")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--network", action="store_true", help="Read the approved ECB and Treasury feeds; disabled providers are never queried")
    args = parser.parse_args(argv)
    report = run_probe(args.output_dir, network=args.network)
    print(json.dumps({"report_path": report["report_path"], "network_performed": report["network_performed"],
                      "auto_enabled": False, "collection_status": {row["id"]: row["collection_status"] for row in report["indicators"]}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
