"""Cboe VIX history parser; disabled until public redistribution is cleared."""
from __future__ import annotations

from datetime import date
from io import BytesIO
from zoneinfo import ZoneInfo

import pandas as pd

from .base import BaseSource, SourceError, normalized
from ..calendars import session_closes


class CboeSource(BaseSource):
    id = "cboe"
    endpoint = "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"
    response_schema = ("DATE", "OPEN", "HIGH", "LOW", "CLOSE")

    def parse(self, body: bytes, cfg, start: date, fetched_ts=None):
        frame = pd.read_csv(BytesIO(body))
        if not set(self.response_schema).issubset(frame.columns):
            raise SourceError("Cboe CSV schema changed")
        dates = pd.to_datetime(frame["DATE"], format="%m/%d/%Y").dt.date
        if frame.empty:
            return normalized([], fetched_ts)
        closes = {ts.astimezone(ZoneInfo("America/New_York")).date(): ts
                  for ts in session_closes(cfg, min(dates), max(dates))}
        rows = []
        for day, value in zip(dates, frame["CLOSE"]):
            if day < start:
                continue
            if day not in closes:
                raise SourceError("Cboe date disagrees with calendar")
            if float(value) <= 0:
                raise SourceError("VIX must be positive")
            rows.append({"close_ts": closes[day], "value": float(value), "published_ts": None})
        return normalized(rows, fetched_ts)

    def fetch_history(self, cfg, start: date):
        self.begin_fetch()
        body = self._get(self.endpoint)
        return self.parse(body, cfg, start, self.last_fetched_ts)
