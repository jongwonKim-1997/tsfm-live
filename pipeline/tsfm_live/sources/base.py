"""Bounded HTTP downloads with immutable, external raw-response evidence."""
from __future__ import annotations

import hashlib
import json
import socket
import ssl
import time as clock
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd
import certifi

from ..calendars import as_dict

UTC = timezone.utc
REPO_ROOT = Path(__file__).resolve().parents[3]
MAX_RESPONSE_BYTES = 32 * 1024 * 1024


class SourceError(RuntimeError):
    """Safe error text suitable for manifests, without credentials or raw URLs."""


class Source(Protocol):
    id: str
    def fetch_history(self, cfg, start: date) -> pd.DataFrame: ...
    def fetch_latest(self, cfg) -> pd.DataFrame: ...
    def fingerprint(self) -> str: ...


def normalized(rows: list[dict], fetched_ts: datetime | None = None) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=["close_ts", "value", "published_ts"])
    frame["close_ts"] = pd.to_datetime(frame["close_ts"], utc=True)
    frame["published_ts"] = pd.to_datetime(frame["published_ts"], utc=True)
    frame["value"] = pd.to_numeric(frame["value"], errors="raise").astype(float)
    frame = frame.sort_values("close_ts").reset_index(drop=True)
    if frame["close_ts"].isna().any() or frame["close_ts"].duplicated().any():
        raise SourceError("invalid or duplicate source dates")
    if not np.isfinite(frame["value"].to_numpy()).all():
        raise SourceError("non-finite source value")
    if fetched_ts is not None:
        frame = frame.loc[frame["close_ts"] <= pd.Timestamp(fetched_ts)].copy()
        frame.attrs["fetched_ts_utc"] = fetched_ts.isoformat()
    return frame


class BaseSource:
    id = "base"
    endpoint = ""
    response_schema: tuple[str, ...] = ()

    def __init__(self, cfg, cache_dir):
        self.cfg = as_dict(cfg)
        self.cache_dir = Path(cache_dir).expanduser().resolve()
        if self.cache_dir == REPO_ROOT or REPO_ROOT in self.cache_dir.parents:
            raise ValueError("raw source cache must be outside the repository")
        self._deadline = 0.0
        self.last_fetched_ts: datetime | None = None
        self.raw_evidence: list[dict] = []

    def fingerprint(self) -> str:
        params = {key: value for key, value in self.cfg["source"].get("params", {}).items()
                  if not any(secret in key.lower() for secret in ("key", "token", "secret"))}
        payload = {"source": self.id, "endpoint": self.endpoint, "params": params,
                   "schema": self.response_schema, "parser_version": 1}
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def begin_fetch(self):
        self._deadline = clock.monotonic() + 180.0
        self.raw_evidence = []

    def fetch_latest(self, cfg) -> pd.DataFrame:
        return self.fetch_history(cfg, datetime.now(UTC).date() - timedelta(days=32))

    def _get(self, url: str, *, public_url: str | None = None) -> bytes:
        if not self._deadline:
            self.begin_fetch()
        errors = (URLError, TimeoutError, socket.timeout, ConnectionError)
        for attempt, delay in enumerate((0, 2, 8, 30)):
            remaining = self._deadline - clock.monotonic()
            if remaining <= delay:
                raise SourceError("source request exceeded 180-second budget")
            if delay:
                clock.sleep(delay)
            try:
                timeout = min(25.0, self._deadline - clock.monotonic())
                request = Request(url, headers={"User-Agent": "TSFM-Live/0.1 research-benchmark",
                                                "Accept": "application/xml,application/json,text/csv,*/*"})
                tls = ssl.create_default_context()
                tls.load_verify_locations(cafile=certifi.where())
                with urlopen(request, timeout=timeout, context=tls) as response:
                    body = response.read(MAX_RESPONSE_BYTES + 1)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise SourceError("source response exceeds size limit")
                if clock.monotonic() > self._deadline:
                    raise SourceError("source request exceeded 180-second budget")
                fetched = datetime.now(UTC)
                digest = hashlib.sha256(body).hexdigest()
                folder = self.cache_dir / "raw" / self.id / self.cfg["id"] / fetched.date().isoformat()
                folder.mkdir(parents=True, exist_ok=True)
                stem = fetched.strftime("%H%M%S%f") + "-" + digest[:16]
                raw_file = folder / f"{stem}.response"
                with raw_file.open("xb") as handle:
                    handle.write(body)
                evidence = {"schema_version": "1.0", "source_id": self.id,
                            "indicator_id": self.cfg["id"], "source_fingerprint": self.fingerprint(),
                            "url": public_url or url, "fetched_ts_utc": fetched.isoformat(),
                            "body_sha256": digest, "raw_file": str(raw_file)}
                with (folder / f"{stem}.json").open("x", encoding="utf-8") as handle:
                    json.dump(evidence, handle, sort_keys=True, indent=2)
                self.raw_evidence.append(evidence)
                self.last_fetched_ts = fetched
                return body
            except HTTPError as exc:
                if exc.code < 500 and exc.code != 429:
                    raise SourceError(f"source HTTP {exc.code}") from None
                if attempt == 3:
                    raise SourceError(f"source HTTP {exc.code} after retries") from None
            except errors:
                if attempt == 3:
                    raise SourceError("source network failure after retries") from None
        raise SourceError("source network failure")
