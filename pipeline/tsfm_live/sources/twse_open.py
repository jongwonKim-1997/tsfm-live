"""TAIEX daily closes from the specifically licensed government open dataset.

Only the dataset 11755 CSV resource is used. This is not permission to scrape
TWSE's other data products or to redistribute an intraday index feed.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import time
from datetime import date
from zoneinfo import ZoneInfo

from .base import BaseSource, SourceError, normalized
from ..calendars import session_closes
from ..ledger import parse_ts, utcnow


class TWSEOpenSource(BaseSource):
    id = "twse_open"
    endpoint = "https://www.twse.com.tw/indicesReport/MI_5MINS_HIST"
    response_schema = ("日期", "開盤指數", "最高指數", "最低指數", "收盤指數")

    def parse(self, body, cfg, start, fetched_ts=None):
        reader = csv.DictReader(io.StringIO(body.decode("utf-8-sig")))
        if tuple(reader.fieldnames or []) != self.response_schema:
            raise SourceError("TWSE open-data CSV schema changed")
        values = []
        for item in reader:
            raw = item["日期"]
            if not raw.isdigit() or len(raw) != 7:
                raise SourceError("TWSE invalid ROC date")
            day = date(int(raw[:3]) + 1911, int(raw[3:5]), int(raw[5:7]))
            value = float(item["收盤指數"].replace(",", ""))
            if value <= 0:
                raise SourceError("TWSE index must be positive")
            if day >= start:
                values.append((day, value))
        if not values:
            return normalized([], fetched_ts)
        closes = {
            t.astimezone(ZoneInfo("Asia/Taipei")).date(): t
            for t in session_closes(cfg, min(d for d, _ in values), max(d for d, _ in values))
        }
        if any(d not in closes for d, _ in values):
            raise SourceError("TWSE observation disagrees with exchange calendar")
        return normalized(
            [{"close_ts": closes[d], "value": v, "published_ts": None} for d, v in values], fetched_ts
        )

    def fetch_history(self, cfg, start):
        self.begin_fetch()
        today = utcnow().astimezone(ZoneInfo("Asia/Taipei")).date()
        month = start.replace(day=1)
        parts, fetched = [], None
        cache = self.cache_dir / "monthly" / self.id
        cache.mkdir(parents=True, exist_ok=True)
        last_request = None
        while month <= today:
            path = cache / (month.strftime("%Y%m") + ".json")
            if month < today.replace(day=1) and path.exists():
                item = json.loads(path.read_bytes())
                body = item["csv"].encode("utf-8")
                if hashlib.sha256(body).hexdigest() != item["sha256"]:
                    raise SourceError("TWSE monthly cache integrity failure")
                fetched = parse_ts(item["fetched_at"])
                if fetched > utcnow():
                    raise SourceError("TWSE future cache timestamp")
            else:
                if last_request is not None:
                    time.sleep(max(0, 3 - (time.monotonic() - last_request)))
                last_request = time.monotonic()
                body = self._get(self.endpoint + "?response=open_data&date=" + month.strftime("%Y%m%d"))
                fetched = self.last_fetched_ts
                # Validate before persisting a complete historical month.
                parsed = self.parse(body, cfg, month, fetched)
                if month < today.replace(day=1) and parsed.empty:
                    raise SourceError("TWSE historical month has no observations")
                if any(d.year != month.year or d.month != month.month for d in parsed.close_ts.dt.date):
                    raise SourceError("TWSE response month mismatch")
                if month < today.replace(day=1):
                    with path.open("x", encoding="utf-8") as handle:
                        json.dump(
                            {
                                "csv": body.decode("utf-8"),
                                "fetched_at": fetched.isoformat(),
                                "sha256": hashlib.sha256(body).hexdigest(),
                            },
                            handle,
                        )
            parsed = self.parse(body, cfg, month, fetched)
            if any(d.year != month.year or d.month != month.month for d in parsed.close_ts.dt.date):
                raise SourceError("TWSE response month mismatch")
            parts.extend(parsed.to_dict("records"))
            month = date(month.year + month.month // 12, month.month % 12 + 1, 1)
        # The current month was freshly fetched last, so this is a real receipt.
        frame = normalized(parts, fetched)
        return frame.loc[frame.close_ts.dt.date >= start].copy()
