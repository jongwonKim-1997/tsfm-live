"""Closed 22:00–23:00 UTC hourly BTCUSDT bars, explicitly a USDT proxy."""
from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from urllib.parse import urlencode

from .base import BaseSource, SourceError, UTC, normalized
from ..calendars import as_dict


class BinanceSource(BaseSource):
    id = "binance"
    endpoint = "https://data-api.binance.vision/api/v3/klines"
    response_schema = ("array[12]", "open_time_ms[0]", "close[4]", "close_time_ms[6]")

    def parse(self, body: bytes, cfg, start: date, fetched_ts=None):
        cfg = as_dict(cfg)
        if cfg["source"]["params"].get("symbol") != "BTCUSDT":
            raise SourceError("only the documented BTCUSDT proxy is supported")
        try:
            payload = json.loads(body)
        except (ValueError, UnicodeDecodeError) as exc:
            raise SourceError("Binance JSON is invalid") from exc
        if not isinstance(payload, list):
            raise SourceError("Binance error response or schema change")
        confirmed_at = fetched_ts or datetime.now(UTC)
        rows = []
        for bar in payload:
            if not isinstance(bar, list) or len(bar) != 12:
                raise SourceError("Binance kline schema changed")
            opening = datetime.fromtimestamp(int(bar[0]) / 1000.0, UTC)
            if opening.hour != 22 or opening.minute != 0 or opening.second != 0 or opening.microsecond:
                continue
            closing = opening + timedelta(hours=1)
            # API stores inclusive last millisecond (22:59:59.999), while our
            # canonical event timestamp is the boundary at exactly 23:00:00.
            if int(bar[6]) != int(closing.timestamp() * 1000) - 1:
                raise SourceError("Binance hourly close boundary is invalid")
            if opening.date() < start or closing > confirmed_at:
                continue
            value = float(bar[4])
            if value <= 0:
                raise SourceError("Binance price must be positive")
            rows.append({"close_ts": closing, "value": value, "published_ts": None})
        return normalized(rows, confirmed_at)

    def fetch_history(self, cfg, start: date):
        cfg = as_dict(cfg)
        self.begin_fetch()
        cursor = int(datetime.combine(start, time(0), UTC).timestamp() * 1000)
        stop = int(datetime.now(UTC).timestamp() * 1000)
        rows = []
        while cursor < stop:
            query = urlencode({"symbol": cfg["source"]["params"]["symbol"], "interval": "1h",
                               "timeZone": "0", "startTime": cursor, "endTime": stop, "limit": 1000})
            body = self._get(self.endpoint + "?" + query)
            parsed = self.parse(body, cfg, start, self.last_fetched_ts)
            rows.extend(parsed.to_dict("records"))
            bars = json.loads(body)
            if not bars:
                break
            following = int(bars[-1][0]) + 3_600_000
            if following <= cursor:
                raise SourceError("Binance pagination did not advance")
            cursor = following
        return normalized(rows, self.last_fetched_ts)
