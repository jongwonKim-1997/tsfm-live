"""Free Community hourly USD reference rates, licensed CC BY-NC 4.0.

The API timestamp is the rate's calculation time, not an exchange candle close
or publication time. Its observation window ends one minute after that time.
Only successful HTTP collections can extend the bounded, private local history.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
import math
import os
import re
import tempfile
import time
from urllib.parse import parse_qs, urlencode, urlsplit

from .base import BaseSource, SourceError, UTC, normalized
from ..ledger import iso, parse_ts


MAX_HISTORY = 600
MAX_PAGES = 4
MAX_CACHE_BYTES = 256 * 1024
HOUR_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:00:00(?:\.0{1,9})?Z\Z")


def _digest(rows):
    encoded = json.dumps(rows, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


class CoinMetricsHourlySource(BaseSource):
    id = "coinmetrics_hourly"
    endpoint = "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
    response_schema = ("object.data[]", "asset", "time=UTC-hour-calculation-time",
                       "ReferenceRateUSD=positive-finite", "frequency=1h", "cache-v1")

    @staticmethod
    def _asset(cfg):
        params = cfg["source"].get("params", {})
        if (params.get("asset") not in {"btc", "eth"}
                or params.get("metric", "ReferenceRateUSD") != "ReferenceRateUSD"
                or params.get("frequency", "1h") != "1h"):
            raise SourceError("unsupported Community hourly series")
        return params["asset"]

    @staticmethod
    def _row(observed, value, fetched):
        if not isinstance(observed, str) or not HOUR_TIME.fullmatch(observed):
            raise ValueError("unaligned hourly calculation time")
        point = parse_ts(observed)
        # The hourly reference window includes the minute AFTER its timestamp.
        # A response cannot substantiate that complete window before it ends.
        if point + timedelta(minutes=1) > fetched:
            raise ValueError("future or unfinished reference rate")
        if isinstance(value, bool):
            raise ValueError("boolean price")
        price = float(value)
        if not math.isfinite(price) or price <= 0:
            raise ValueError("invalid reference rate")
        return {"close_ts": point, "value": price, "published_ts": None}

    def parse(self, body, cfg, start, fetched_ts=None):
        asset = self._asset(cfg)
        received = fetched_ts or datetime.now(UTC)
        try:
            payload = json.loads(body)
            if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
                raise ValueError("invalid response schema")
            rows = []
            seen = set()
            for record in payload["data"]:
                if not isinstance(record, dict) or record["asset"] != asset:
                    raise ValueError("wrong reference-rate asset")
                row = self._row(record["time"], record["ReferenceRateUSD"], received)
                if row["close_ts"] in seen:
                    raise ValueError("duplicate hourly rate")
                seen.add(row["close_ts"])
                if row["close_ts"].date() >= start:
                    rows.append(row)
            return normalized(rows, received)
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            raise SourceError("invalid Community hourly reference response") from exc

    def _next_page(self, payload, asset):
        following = payload.get("next_page_url")
        if following is None:
            return None
        if not isinstance(following, str) or len(following) > 8192:
            raise SourceError("invalid Community pagination URL")
        parsed, expected = urlsplit(following), urlsplit(self.endpoint)
        query = parse_qs(parsed.query)
        if (parsed.scheme != expected.scheme or parsed.netloc != expected.netloc
                or parsed.path != expected.path or parsed.fragment
                or query.get("assets") != [asset]
                or query.get("metrics") != ["ReferenceRateUSD"]
                or query.get("frequency") != ["1h"]
                or any(key.lower() in {"api_key", "key", "access_token", "secret"} for key in query)):
            raise SourceError("unsafe Community pagination URL")
        return following

    @property
    def history_path(self):
        return self.cache_dir / "history" / self.id / (self.fingerprint() + ".json")

    def _read_cache(self, fetched):
        path = self.history_path
        if not path.exists():
            return [], "empty"
        try:
            if path.stat().st_size > MAX_CACHE_BYTES:
                raise ValueError("oversized cache")
            payload = json.loads(path.read_bytes())
            rows = payload["rows"]
            if (payload["schema_version"] != 1
                    or payload["source_fingerprint"] != self.fingerprint()
                    or payload["indicator_id"] != self.cfg["id"]
                    or not isinstance(rows, list) or len(rows) > MAX_HISTORY
                    or payload["rows_sha256"] != _digest(rows)):
                raise ValueError("incompatible cache")
            previous = None
            for row in rows:
                if set(row) != {"close_ts", "value", "fetched_ts_utc"}:
                    raise ValueError("invalid cache schema")
                retrieved = parse_ts(row["fetched_ts_utc"])
                if retrieved > fetched:
                    raise ValueError("future cached provenance")
                point = self._row(row["close_ts"], row["value"], retrieved)["close_ts"]
                if previous is not None and point <= previous:
                    raise ValueError("unsorted or duplicate cache")
                previous = point
            return rows, "validated"
        except (ValueError, TypeError, KeyError, OSError, OverflowError):
            # Invalid history is never trusted. A fresh successful response is
            # still usable and repairs the cache, with its status in provenance.
            return [], "invalid_ignored"

    def _write_cache(self, rows):
        path = self.history_path
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"schema_version": 1, "source_fingerprint": self.fingerprint(),
                   "indicator_id": self.cfg["id"], "rows": rows, "rows_sha256": _digest(rows)}
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                             prefix=path.stem + "-", suffix=".tmp", delete=False) as handle:
                temporary = handle.name
                json.dump(payload, handle, sort_keys=True, separators=(",", ":"), allow_nan=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if temporary is not None and os.path.exists(temporary):
                os.unlink(temporary)

    def fetch_history(self, cfg, start):
        asset = self._asset(cfg)
        self.begin_fetch()
        boundary = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
        query = urlencode({"assets": asset, "metrics": "ReferenceRateUSD", "frequency": "1h",
                           "start_time": max(start.isoformat(), iso(boundary - timedelta(hours=MAX_HISTORY))),
                           "end_time": iso(boundary), "page_size": 1000})
        url = self.endpoint + "?" + query
        visited, fresh = set(), []
        for page in range(MAX_PAGES):
            if url in visited:
                raise SourceError("Community pagination did not advance")
            visited.add(url)
            if page:
                time.sleep(0.65)  # Community: at most 10 requests per 6 seconds.
            body = self._get(url)
            if self.last_fetched_ts is None:
                raise SourceError("missing HTTP collection timestamp")
            frame = self.parse(body, cfg, start, self.last_fetched_ts)
            for row in frame.to_dict("records"):
                if row["close_ts"] > boundary:
                    raise SourceError("reference rate exceeds frozen request boundary")
                fresh.append({"close_ts": iso(row["close_ts"]), "value": row["value"],
                              "fetched_ts_utc": iso(self.last_fetched_ts)})
            url = self._next_page(json.loads(body), asset)
            if not url:
                break
        else:
            raise SourceError("Community pagination exceeds page limit")
        if len({row["close_ts"] for row in fresh}) != len(fresh):
            raise SourceError("duplicate Community hours across pages")
        fresh.sort(key=lambda row: row["close_ts"])
        if not fresh:
            # Empty successful responses also cannot turn old history into a
            # fresh source. Do not overwrite useful provenance with emptiness.
            return normalized([], self.last_fetched_ts)
        cached, cache_status = self._read_cache(self.last_fetched_ts)
        # Only keep cache preceding this response's covered window. This both
        # applies source revisions and prevents cache from masking a new hole,
        # a source rollback, or a lagging latest source observation.
        rows = [row for row in cached if row["close_ts"] < fresh[0]["close_ts"]]
        rows = (rows + fresh)[-MAX_HISTORY:]
        self._write_cache(rows)
        result = normalized([{"close_ts": row["close_ts"], "value": row["value"], "published_ts": None}
                             for row in rows if parse_ts(row["close_ts"]).date() >= start],
                            self.last_fetched_ts)
        result.attrs.update(cache_status=cache_status, observation_kind="reference_rate",
                            earliest_collection_ts_utc=min(row["fetched_ts_utc"] for row in rows))
        return result
