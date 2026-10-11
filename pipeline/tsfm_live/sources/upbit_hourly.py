"""Completed Upbit hourly candles for personal local analysis only."""
from __future__ import annotations

from datetime import datetime, timedelta
import json
import math
import time
from urllib.parse import urlencode

from .base import BaseSource, SourceError, UTC, normalized
from ..ledger import parse_ts


class UpbitHourlySource(BaseSource):
    id = "upbit_hourly"
    endpoint = "https://api.upbit.com/v1/candles/minutes/60"
    response_schema = ("array", "market", "candle_date_time_utc", "trade_price", "unit=60")

    def parse(self, body, cfg, start, fetched_ts=None):
        try:
            payload = json.loads(body)
            if not isinstance(payload, list):
                raise ValueError("not_list")
            market = cfg["source"]["params"]["market"]
            received = fetched_ts or datetime.now(UTC)
            rows = []
            for bar in payload:
                if bar["market"] != market or bar["unit"] != 60:
                    raise ValueError("wrong_market_or_interval")
                opening = parse_ts(bar["candle_date_time_utc"] + "Z")
                if opening.minute or opening.second or opening.microsecond:
                    raise ValueError("unaligned_hour")
                closing = opening + timedelta(hours=1)
                value = float(bar["trade_price"])
                if not math.isfinite(value) or value <= 0:
                    raise ValueError("invalid_price")
                # This is an update timestamp, not a bar-close/publication time.
                # Real responses include updates milliseconds after the boundary.
                tick = datetime.fromtimestamp(int(bar["timestamp"]) / 1000, UTC)
                if not opening <= tick <= received:
                    raise ValueError("invalid_update_timestamp")
                if opening.date() >= start and closing <= received:
                    rows.append({"close_ts": closing, "value": value, "published_ts": None})
            return normalized(rows, received)
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            raise SourceError("invalid hourly candle response") from exc

    def fetch_history(self, cfg, start):
        if cfg["source"]["params"].get("market") not in {"KRW-BTC", "KRW-ETH"}:
            raise SourceError("unsupported hourly market")
        self.begin_fetch()
        boundary = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
        cursor, rows = boundary, []
        # Three small pages cover 512-hour model context, without scanning years.
        for page in range(3):
            if page:
                time.sleep(0.15)  # below the documented 10 requests/s candle limit
            query = urlencode({"market": cfg["source"]["params"]["market"],
                               "to": cursor.isoformat(), "count": 200})
            body = self._get(self.endpoint + "?" + query)
            parsed = self.parse(body, cfg, start, self.last_fetched_ts)
            # Freeze the selection at collection start if a request crosses an hour.
            rows.extend(parsed.loc[parsed["close_ts"] <= boundary].to_dict("records"))
            raw = json.loads(body)
            if not raw:
                break
            next_cursor = min(parse_ts(bar["candle_date_time_utc"] + "Z") for bar in raw)
            if next_cursor >= cursor:
                raise SourceError("hourly pagination did not advance")
            cursor = next_cursor
            if cursor.date() < start:
                break
        return normalized(rows, self.last_fetched_ts)
