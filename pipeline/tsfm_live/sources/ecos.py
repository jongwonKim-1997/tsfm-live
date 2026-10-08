"""ECOS daily API adapter. Enabling requires independently verified series metadata."""
from __future__ import annotations

import json
import os
from datetime import date, datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo

from .base import BaseSource, SourceError, UTC, normalized
from ..calendars import as_dict, session_closes


class ECOSSource(BaseSource):
    id = "ecos"
    endpoint = "https://ecos.bok.or.kr/api/StatisticSearch"
    response_schema = ("StatisticSearch.list_total_count", "StatisticSearch.row[].TIME",
                       "StatisticSearch.row[].DATA_VALUE", "StatisticSearch.row[].STAT_CODE",
                       "StatisticSearch.row[].ITEM_CODE1", "StatisticSearch.row[].UNIT_NAME")

    def parse(self, body: bytes, cfg, start: date, fetched_ts=None):
        cfg = as_dict(cfg)
        params = cfg["source"]["params"]
        payload = json.loads(body)
        if "StatisticSearch" not in payload:
            # Do not echo provider messages, which may include the key URL.
            raise SourceError("ECOS error response or missing StatisticSearch")
        observations = payload["StatisticSearch"].get("row", [])
        dates = [datetime.strptime(row["TIME"], "%Y%m%d").date() for row in observations]
        closes = {ts.astimezone(ZoneInfo(cfg["tz"])).date(): ts
                  for ts in session_closes(cfg, min(dates), max(dates))} if dates else {}
        rows = []
        for obs, day in zip(observations, dates):
            if day < start:
                continue
            if obs.get("STAT_CODE") != params["stat_code"] or obs.get("ITEM_CODE1") != params["item_code"]:
                raise SourceError("ECOS series identity mismatch")
            if params.get("unit") and obs.get("UNIT_NAME") != params["unit"]:
                raise SourceError("ECOS unit mismatch")
            if obs.get("DATA_VALUE") in {None, "", "-", ".."}:
                continue
            if day not in closes:
                raise SourceError("ECOS observation date disagrees with configured calendar")
            rows.append({"close_ts": closes[day], "value": float(obs["DATA_VALUE"]), "published_ts": None})
        return normalized(rows, fetched_ts)

    def fetch_history(self, cfg, start: date):
        cfg = as_dict(cfg)
        params = cfg["source"]["params"]
        key = os.environ.get("ECOS_API_KEY")
        if not key:
            raise SourceError("ECOS_API_KEY is not configured")
        if not params.get("series_verified", False):
            raise SourceError("ECOS series metadata, finality and timing are unverified")
        self.begin_fetch()
        rows, first = [], 1
        while True:
            suffix = "/".join(["json", "en", str(first), str(first + 999),
                               quote(params["stat_code"], safe=""), "D", start.strftime("%Y%m%d"),
                               datetime.now(UTC).strftime("%Y%m%d"), quote(params["item_code"], safe="")])
            url = self.endpoint + "/" + quote(key, safe="") + "/" + suffix
            public_url = self.endpoint + "/REDACTED/" + suffix
            body = self._get(url, public_url=public_url)
            frame = self.parse(body, cfg, start, self.last_fetched_ts)
            rows.extend(frame.to_dict("records"))
            total = int(json.loads(body)["StatisticSearch"]["list_total_count"])
            if first + 999 >= total:
                break
            first += 1000
        return normalized(rows, self.last_fetched_ts)
