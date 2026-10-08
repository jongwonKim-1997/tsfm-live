"""Official daily ECB reference rates and an explicitly derived cross rate."""
from __future__ import annotations

from datetime import date
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

from .base import BaseSource, SourceError, normalized
from ..calendars import as_dict, session_closes


class ECBSource(BaseSource):
    id = "ecb"
    endpoint = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.xml"
    response_schema = ("Cube@time", "Cube@currency", "Cube@rate")

    def parse(self, body: bytes, cfg, start: date, fetched_ts=None):
        cfg = as_dict(cfg)
        try:
            root = ET.fromstring(body)
        except ET.ParseError as exc:
            raise SourceError("ECB XML is invalid") from exc
        dated = [node for node in root.iter() if "time" in node.attrib]
        if not dated:
            raise SourceError("ECB schema changed: dated Cube nodes absent")
        dates = [date.fromisoformat(node.attrib["time"]) for node in dated]
        closes = {ts.astimezone(ZoneInfo("Europe/Berlin")).date(): ts
                  for ts in session_closes(cfg, min(dates), max(dates))}
        pair = cfg["source"]["params"]["pair"]
        if pair not in {"EURUSD", "USDJPY"}:
            raise SourceError("unsupported ECB pair")
        rows = []
        for node, day in zip(dated, dates):
            if day < start:
                continue
            rates = {child.attrib["currency"]: float(child.attrib["rate"])
                     for child in node if "currency" in child.attrib and "rate" in child.attrib}
            if "USD" not in rates or (pair == "USDJPY" and "JPY" not in rates):
                raise SourceError("ECB required currency missing")
            if rates["USD"] <= 0 or (pair == "USDJPY" and rates["JPY"] <= 0):
                raise SourceError("ECB rate must be positive")
            if day not in closes:
                raise SourceError("ECB date does not match TARGET calendar")
            value = rates["USD"] if pair == "EURUSD" else rates["JPY"] / rates["USD"]
            rows.append({"close_ts": closes[day], "value": value, "published_ts": None})
        return normalized(rows, fetched_ts)

    def fetch_history(self, cfg, start: date):
        self.begin_fetch()
        body = self._get(self.endpoint)
        return self.parse(body, cfg, start, self.last_fetched_ts)
