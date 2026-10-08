"""Treasury's official XML feed; not the lagged FRED mirror."""
from __future__ import annotations

from datetime import date, datetime
from urllib.parse import urlencode
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

import pandas as pd

from .base import BaseSource, SourceError, UTC, normalized
from ..calendars import as_dict, session_closes


class USTreasurySource(BaseSource):
    id = "ustreasury"
    endpoint = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
    response_schema = ("entry/content/properties/NEW_DATE", "entry/content/properties/BC_10YEAR")

    def parse(self, body: bytes, cfg, start: date, fetched_ts=None):
        cfg = as_dict(cfg)
        try:
            root = ET.fromstring(body)
        except ET.ParseError as exc:
            raise SourceError("Treasury XML is invalid") from exc
        entries = [node for node in root.iter() if node.tag.split("}")[-1] == "entry"]
        if not entries:
            # Valid empty Atom feed is allowed for a year without observations.
            if root.tag.split("}")[-1] == "feed":
                return normalized([], fetched_ts)
            raise SourceError("Treasury schema changed: Atom feed absent")
        observations = []
        field = cfg["source"].get("params", {}).get("field", "BC_10YEAR")
        for entry in entries:
            values = {node.tag.split("}")[-1]: node.text for node in entry.iter()}
            if "NEW_DATE" not in values or field not in values:
                raise SourceError("Treasury required XML fields missing")
            if not values[field] or values[field].strip() in {"N/A", "ND"}:
                continue
            day = date.fromisoformat(values["NEW_DATE"][:10])
            if day >= start:
                observations.append((day, float(values[field])))
        if not observations:
            return normalized([], fetched_ts)
        dates = [day for day, _ in observations]
        closes = {ts.astimezone(ZoneInfo("America/New_York")).date(): ts
                  for ts in session_closes(cfg, min(dates), max(dates))}
        rows = []
        for day, value in observations:
            if day not in closes:
                raise SourceError("Treasury observation date disagrees with SIFMA calendar")
            rows.append({"close_ts": closes[day], "value": value, "published_ts": None})
        return normalized(rows, fetched_ts)

    def fetch_history(self, cfg, start: date):
        self.begin_fetch()
        frames = []
        for year in range(start.year, datetime.now(UTC).year + 1):
            query = urlencode({"data": "daily_treasury_yield_curve", "field_tdr_date_value": year})
            body = self._get(self.endpoint + "?" + query)
            frames.append(self.parse(body, cfg, start, self.last_fetched_ts))
        if not frames:
            return normalized([], self.last_fetched_ts)
        frame = pd.concat(frames, ignore_index=True)
        return normalized(frame.to_dict("records"), self.last_fetched_ts)
