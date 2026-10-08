"""Authoritative typed ledger schema; exported schemas are generated from these classes."""
from __future__ import annotations

import json
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .config.settings import LOCKIN_DEADLINE_LOCAL, QUANTILES, RUN_TIME_LOCAL, TZ


def protocol_time(day: date, clock: str) -> datetime:
    return datetime.combine(day, time.fromisoformat(clock), ZoneInfo(TZ))


def require_aware(*values: datetime | None):
    if any(value is not None and value.utcoffset() is None for value in values):
        raise ValueError("Timestamps must have timezones")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class SourceConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    adapter: str
    params: dict[str, Any] = Field(default_factory=dict)


class IndicatorConfig(BaseModel):
    model_config = ConfigDict(extra="allow", allow_inf_nan=False)
    id: str = Field(pattern=r"^[a-z0-9_]+$")
    name: str
    group: str
    source: SourceConfig
    calendar: str
    close_time_local: str
    tz: str
    target_transform: Literal["log_return_pct", "diff_bp"]
    display_policy: Literal["level", "return_only"]
    decimals: int = 2
    min_history: int = 300
    license_note: str = ""
    enabled: bool = False
    disabled_reason: str | None = None


class ForecastRecord(StrictModel):
    indicator_id: str
    entrant_id: str
    entrant_version: str
    status: Literal["ok", "skipped", "failed", "void"]
    skip_reason: str | None = None
    target_transform: Literal["log_return_pct", "diff_bp"]
    last_close_ts: datetime | None = None
    last_close_value: float | None = None
    next_close_ts: datetime | None = None
    context_len: int = 0
    context_hash: str | None = None
    regime: Literal["normal", "high_vol"] | None = None
    sigma_ewma: float | None = None
    q: dict[str, float] = Field(default_factory=dict)
    mean: float | None = None
    quantile_method: Literal["native", "sampled", "interpolated"] | None = None
    n_samples: int | None = None
    seed: int
    inference_seconds: float = 0
    contributors: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_output(self):
        for ts in (self.last_close_ts, self.next_close_ts):
            if ts is not None and ts.utcoffset() is None:
                raise ValueError("Timestamps must have timezones")
        if self.status == "ok":
            if set(self.q) != {str(q) for q in QUANTILES}:
                raise ValueError("An ok forecast needs the exact 13-quantile grid")
            values = [self.q[str(q)] for q in QUANTILES]
            if values != sorted(values):
                raise ValueError("Quantiles must be nondecreasing")
            if self.last_close_ts is None or self.next_close_ts is None:
                raise ValueError("An ok forecast needs both closes")
            if self.next_close_ts <= self.last_close_ts:
                raise ValueError("Target must follow the context")
            if self.context_hash is None or self.context_len < 1:
                raise ValueError("Missing context provenance")
            if self.quantile_method == "sampled" and (self.n_samples or 0) < 1000:
                raise ValueError("Sampled output requires at least 1000 samples")
        elif not self.skip_reason:
            raise ValueError("Non-ok records must explain why")
        return self


class ForecastFile(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    run_id: str
    run_date: date
    run_ts_utc: datetime
    lockin_deadline_utc: datetime
    horizon_sessions: Literal[1] = 1
    quantiles: list[float] = Field(default_factory=lambda: QUANTILES.copy())
    records: list[ForecastRecord]

    @model_validator(mode="after")
    def check_run(self):
        if self.quantiles != QUANTILES:
            raise ValueError("Protocol quantile grid changed")
        keys = [(r.indicator_id, r.entrant_id) for r in self.records]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate entrant/indicator pair")
        if self.run_ts_utc.utcoffset() is None or self.lockin_deadline_utc.utcoffset() is None:
            raise ValueError("Run timestamps must have timezones")
        if self.run_ts_utc.astimezone(ZoneInfo(TZ)).date() != self.run_date:
            raise ValueError("run_date must equal the issue timestamp's Asia/Seoul date")
        if self.lockin_deadline_utc != protocol_time(self.run_date, LOCKIN_DEADLINE_LOCAL):
            raise ValueError("Lock-in deadline must be 08:50 Asia/Seoul on run_date")
        if self.run_ts_utc >= self.lockin_deadline_utc and any(r.status != "void" for r in self.records):
            raise ValueError("A run issued at or after the deadline must contain only void records")
        for r in self.records:
            if r.status == "ok" and not (r.last_close_ts < self.run_ts_utc < r.next_close_ts):
                raise ValueError("Forecast must target a future close using a past close")
        return self


class ActualRecord(StrictModel):
    indicator_id: str
    close_ts: datetime
    value: float | None
    y: float
    source_id: str
    source_fingerprint: str
    published_ts: datetime | None = None
    fetched_ts_utc: datetime

    @model_validator(mode="after")
    def actual_time_evidence(self):
        require_aware(self.close_ts, self.published_ts, self.fetched_ts_utc)
        if self.fetched_ts_utc < self.close_ts:
            raise ValueError("Actual cannot be fetched before its close")
        if self.published_ts is not None and not self.close_ts <= self.published_ts <= self.fetched_ts_utc:
            raise ValueError("Actual publication must be between close and fetch")
        return self


class ActualFile(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    run_date: date
    records: list[ActualRecord]


class ScoreRecord(StrictModel):
    forecast_run_date: date
    indicator_id: str
    entrant_id: str
    y: float | None = None
    q50: float | None = None
    se: float | None = None
    ae: float | None = None
    crps: float | None = None
    pinball: dict[str, float] | None = None
    hit: Literal[0, 1] | None = None
    covered80: Literal[0, 1] | None = None
    covered95: Literal[0, 1] | None = None
    width80: float | None = None
    width95: float | None = None
    regime: Literal["normal", "high_vol"] | None = None
    scored_ts_utc: datetime
    unscorable: Literal["actual_unavailable"] | None = None

    @model_validator(mode="after")
    def check_metrics(self):
        names = ("y", "q50", "se", "ae", "crps", "pinball", "covered80", "covered95", "width80", "width95")
        if self.unscorable is None and any(getattr(self, k) is None for k in names):
            raise ValueError("Scorable records require complete metrics")
        if self.unscorable is not None and any(getattr(self, k) is not None for k in names):
            raise ValueError("Unscorable records must have null metrics")
        return self


class ScoreFile(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    run_date: date
    records: list[ScoreRecord]


class ManifestFile(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    run_id: str
    run_date: date
    run_ts_utc: datetime
    scheduled_ts: datetime
    actual_start_ts: datetime
    code_commit: str | None = None
    uv_lock_sha256: str
    python_version: str
    hardware: str
    entrants: list[dict[str, Any]]
    sources: list[dict[str, Any]]
    steps: list[dict[str, Any]]
    lockin_ts_utc: datetime | None = None
    deadline_met: bool
    forecasts_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    forecasts_commit: str | None = Field(default=None, pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
    ots_file: str | None = None
    ots_status: Literal["disabled", "not_eligible", "unavailable", "pending", "anchored", "failed"] | None = None
    counts: dict[str, int]
    entrant_counts: dict[str, dict[str, int]] = Field(default_factory=dict)
    alerts: list[str] = Field(default_factory=list)
    mode: Literal["live", "dry-run"] = "live"
    resumed_after_lockin: bool = False

    @model_validator(mode="after")
    def receipt_evidence(self):
        require_aware(self.run_ts_utc, self.scheduled_ts, self.actual_start_ts, self.lockin_ts_utc)
        if self.scheduled_ts != protocol_time(self.run_date, RUN_TIME_LOCAL):
            raise ValueError("Scheduled timestamp must be 08:10 Asia/Seoul on run_date")
        if self.run_ts_utc != self.actual_start_ts:
            raise ValueError("Manifest run timestamp must match actual execution start")
        if self.mode == "live" and self.actual_start_ts.astimezone(ZoneInfo(TZ)).date() != self.run_date:
            raise ValueError("Live execution must belong to its Asia/Seoul run_date")
        receipt = (self.lockin_ts_utc, self.forecasts_sha256, self.forecasts_commit)
        has_receipt = all(value is not None and value != "" for value in receipt)
        if any(value is not None for value in receipt) and not has_receipt:
            raise ValueError("Publication receipt requires timestamp, forecast hash and commit together")
        if self.deadline_met and (self.mode != "live" or not has_receipt):
            raise ValueError("deadline_met requires a complete live publication receipt")
        if self.mode == "dry-run" and (has_receipt or self.ots_file or self.resumed_after_lockin):
            raise ValueError("Dry-run manifests cannot claim publication evidence")
        if self.resumed_after_lockin:
            if not has_receipt or self.lockin_ts_utc >= self.actual_start_ts:
                raise ValueError("A resumed manifest needs an earlier complete lock-in receipt")
        elif has_receipt and self.lockin_ts_utc < self.actual_start_ts:
            raise ValueError("Receipt precedes execution without an explicit resume marker")
        if has_receipt and self.lockin_ts_utc < self.scheduled_ts:
            raise ValueError("Receipt cannot precede the scheduled issue time")
        if self.deadline_met and self.lockin_ts_utc >= protocol_time(self.run_date, LOCKIN_DEADLINE_LOCAL):
            raise ValueError("A receipt at or after 08:50 cannot meet the deadline")
        if self.ots_file and not has_receipt:
            raise ValueError("OTS evidence requires an underlying publication receipt")
        if self.ots_file and self.ots_status != "anchored":
            raise ValueError("Public OTS file requires verified anchored status")
        if self.ots_status == "anchored" and not self.ots_file:
            raise ValueError("Anchored OTS status requires a public proof file")
        statuses = {"ok", "failed", "skipped", "void"}
        if set(self.counts) - statuses or any(value < 0 for value in self.counts.values()):
            raise ValueError("Manifest counts must be nonnegative protocol statuses")
        if self.entrant_counts:
            totals = dict.fromkeys(statuses, 0)
            for counts in self.entrant_counts.values():
                if set(counts) != statuses or any(value < 0 for value in counts.values()):
                    raise ValueError("Each entrant needs nonnegative counts for all four statuses")
                for status, value in counts.items():
                    totals[status] += value
            if any(totals[status] != self.counts.get(status, 0) for status in statuses):
                raise ValueError("Entrant counts must sum to manifest totals")
        return self


class CorrectionAffect(StrictModel):
    file: str
    record_selector: dict[str, Any]


class CorrectionFile(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    id: str
    created_ts_utc: datetime
    type: Literal["actual_revision", "void", "entrant_disqualified", "other"]
    affects: list[CorrectionAffect]
    reason: str = Field(min_length=5)
    replacement: dict[str, Any] | None = None
    author: str


class SnapshotFile(BaseModel):
    model_config = ConfigDict(extra="allow", allow_inf_nan=False)
    schema_version: Literal["1.0"] = "1.0"
    as_of: date


SCHEMAS = {
    "forecasts": ForecastFile, "actuals": ActualFile, "scores": ScoreFile,
    "manifests": ManifestFile, "corrections": CorrectionFile, "snapshots": SnapshotFile,
}


def export_schemas(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    for name, cls in SCHEMAS.items():
        (directory / f"{name}.json").write_text(
            json.dumps(cls.model_json_schema(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
