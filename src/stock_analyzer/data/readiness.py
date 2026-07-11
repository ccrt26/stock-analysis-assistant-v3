from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AcquisitionGroupId(str, Enum):
    CALENDAR_UNIVERSE = "calendar_universe"
    MARKET_DECISION = "market_decision"
    BOARD_INDUSTRY = "board_industry"
    CANDIDATE_FUNDAMENTAL = "candidate_fundamental"
    OFFICIAL_EVENTS_RISK = "official_events_risk"
    CONCEPT_THEME = "concept_theme"
    MANUAL_HOLDINGS = "manual_holdings"


class RouteKind(str, Enum):
    PRIMARY = "primary"
    BACKUP = "backup"
    LOCAL = "local"


class FormalRunState(str, Enum):
    PENDING = "pending"
    ACQUIRING_SCREENING_PRIMARY = "acquiring_screening_primary"
    ACQUIRING_SCREENING_BACKUP = "acquiring_screening_backup"
    VALIDATING_SCREENING = "validating_screening"
    READY_TO_SCREEN = "ready_to_screen"
    SCREENING = "screening"
    TARGET_SET_FROZEN = "target_set_frozen"
    ACQUIRING_TARGET_PRIMARY = "acquiring_target_primary"
    ACQUIRING_TARGET_BACKUP = "acquiring_target_backup"
    VALIDATING_TARGET = "validating_target"
    READY_TO_ANALYZE = "ready_to_analyze"
    ANALYZING = "analyzing"
    RENDERING = "rendering"
    VERIFYING = "verifying"
    COMMITTING = "committing"
    ANALYSIS_COMPLETE_NO_RECOMMENDATIONS = "analysis_complete_no_recommendations"
    REPORT_GENERATED = "report_generated"
    BLOCKED_NEEDS_HUMAN = "blocked_needs_human"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_NEEDS_HUMAN = "failed_needs_human"


class FailureClassification(str, Enum):
    PERMISSION = "permission"
    TRANSPORT = "transport"
    RATE_LIMIT = "rate_limit"
    SCHEMA = "schema"
    MISSING_FIELDS = "missing_fields"
    INCOMPLETE_UNIVERSE = "incomplete_universe"
    STALE_DATA = "stale_data"
    INVALID_SEMANTICS = "invalid_semantics"
    STORAGE = "storage"
    UNKNOWN = "unknown"


class CapabilityEvidenceKind(str, Enum):
    RECORDED = "recorded"
    LIVE = "live"


class RouteCapabilityEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    route_id: str
    group_id: AcquisitionGroupId
    contract_version: str
    full_contract_tested: bool
    field_semantics_verified: bool
    full_universe_verified: bool
    post_close_verified: bool
    tested_at: datetime
    evidence_kind: CapabilityEvidenceKind = CapabilityEvidenceKind.RECORDED
    response_hash: str = "0" * 64
    tested_library_versions: dict[str, str] = Field(default_factory=dict)
    semantic_probe_hashes: dict[str, str] = Field(default_factory=dict)

    @property
    def approved(self) -> bool:
        return all(
            (
                self.full_contract_tested,
                self.field_semantics_verified,
                self.full_universe_verified,
                self.post_close_verified,
                self._event_semantics_approved(),
            )
        )

    def _event_semantics_approved(self) -> bool:
        if self.group_id is not AcquisitionGroupId.OFFICIAL_EVENTS_RISK:
            return True
        required = {"populated_precise_time", "empty_coverage"}
        if set(self.semantic_probe_hashes) != required:
            return False
        values = {self.semantic_probe_hashes[key] for key in required}
        return len(values) == 2

    @property
    def approved_for_live(self) -> bool:
        return self.approved and self.evidence_kind is CapabilityEvidenceKind.LIVE


class RecordTypeContract(BaseModel):
    model_config = ConfigDict(frozen=True)

    record_type: str
    required_fields: tuple[str, ...]
    legitimate_null_fields: dict[str, str] = Field(default_factory=dict)
    unique_key_fields: tuple[str, ...]
    current_fact_fields: tuple[str, ...] = ()


class AcquisitionGroupContract(BaseModel):
    model_config = ConfigDict(frozen=True)

    group_id: AcquisitionGroupId
    contract_version: str
    required_fields: tuple[str, ...]
    legitimate_null_fields: dict[str, str] = Field(default_factory=dict)
    unique_key_fields: tuple[str, ...]
    current_fact_fields: tuple[str, ...] = ()
    minimum_history_sessions: int = Field(default=0, ge=0)
    require_target_date: bool = True
    expected_codes: tuple[str, ...] = ()
    include_request_target_codes: bool = True
    record_type_field: str = "record_type"
    record_types: tuple[RecordTypeContract, ...] = ()


class AcquisitionRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    trade_date: date
    report_cutoff: datetime
    target_codes: tuple[str, ...] = ()
    contract_version: str

    @field_validator("report_cutoff")
    @classmethod
    def _require_aware_cutoff(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("report_cutoff must be timezone-aware")
        return value


class AcquisitionPayload(BaseModel):
    model_config = ConfigDict(frozen=True)

    group_id: AcquisitionGroupId
    route_id: str
    route_kind: RouteKind
    trade_date: date
    fetched_at: datetime
    source_names: tuple[str, ...]
    records: tuple[dict[str, Any], ...]
    covered_dates: tuple[date, ...]
    coverage_codes: tuple[str, ...] = ()
    coverage_proven: bool = False
    field_coverage: dict[str, bool]
    unit_metadata: dict[str, str] = Field(default_factory=dict)
    adjustment_basis: str | None = None
    publication_times: dict[str, datetime] = Field(default_factory=dict)
    contract_version: str = "formal-v1"

    @field_validator("fetched_at")
    @classmethod
    def _require_aware_fetch_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("fetched_at must be timezone-aware")
        return value

    @property
    def content_hash(self) -> str:
        records = sorted(
            (_canonical_json(record) for record in self.records),
        )
        payload = {
            "group_id": self.group_id.value,
            "route_id": self.route_id,
            "route_kind": self.route_kind.value,
            "trade_date": self.trade_date.isoformat(),
            "fetched_at": self.fetched_at.isoformat(),
            "source_names": sorted(self.source_names),
            "records": records,
            "covered_dates": sorted(value.isoformat() for value in self.covered_dates),
            "coverage_codes": sorted(self.coverage_codes),
            "coverage_proven": self.coverage_proven,
            "field_coverage": self.field_coverage,
            "unit_metadata": self.unit_metadata,
            "adjustment_basis": self.adjustment_basis,
            "publication_times": {
                key: value.isoformat()
                for key, value in sorted(self.publication_times.items())
            },
            "contract_version": self.contract_version,
        }
        return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


class GroupValidation(BaseModel):
    model_config = ConfigDict(frozen=True)

    complete: bool
    reasons: tuple[str, ...] = ()
    covered_codes: tuple[str, ...] = ()
    covered_dates: tuple[date, ...] = ()


def validate_group_payload(
    contract: AcquisitionGroupContract,
    request: AcquisitionRequest,
    payload: AcquisitionPayload,
) -> GroupValidation:
    reasons: list[str] = []
    if payload.group_id != contract.group_id:
        reasons.append(
            f"group_mismatch:{payload.group_id.value}:{contract.group_id.value}"
        )
    if payload.trade_date != request.trade_date:
        reasons.append(
            f"trade_date_mismatch:{payload.trade_date.isoformat()}:{request.trade_date.isoformat()}"
        )
    if payload.contract_version != contract.contract_version:
        reasons.append(
            f"contract_mismatch:{payload.contract_version}:{contract.contract_version}"
        )
    if request.contract_version != contract.contract_version:
        reasons.append(
            f"request_contract_mismatch:{request.contract_version}:{contract.contract_version}"
        )

    keys_seen: set[tuple[str, ...]] = set()
    covered_codes: set[str] = set()
    covered_dates: set[date] = set(payload.covered_dates)
    target_rows: dict[str, dict[str, Any]] = {}
    typed_target_rows: dict[tuple[str, str], dict[str, Any]] = {}
    record_contracts = {item.record_type: item for item in contract.record_types}
    coverage_fields = set(contract.required_fields)
    for item in contract.record_types:
        coverage_fields.update(item.required_fields)

    for index, record in enumerate(payload.records):
        selected: RecordTypeContract | None = None
        if record_contracts:
            record_type = str(record.get(contract.record_type_field))
            selected = record_contracts.get(record_type)
            if selected is None:
                reasons.append(f"unknown_record_type:{record_type}:row={index}")
                continue
        required_fields = selected.required_fields if selected else contract.required_fields
        legitimate_null_fields = (
            selected.legitimate_null_fields
            if selected
            else contract.legitimate_null_fields
        )
        unique_key_fields = (
            selected.unique_key_fields if selected else contract.unique_key_fields
        )
        reason_fields = set(legitimate_null_fields.values())

        for field in required_fields:
            if field not in record:
                reasons.append(f"missing_field:{field}:row={index}")
                continue
            value = record[field]
            if value is None and field not in reason_fields:
                null_reason_field = legitimate_null_fields.get(field)
                if not null_reason_field or not _non_empty(record.get(null_reason_field)):
                    reasons.append(f"unclassified_null:{field}:row={index}")

        if unique_key_fields:
            key = tuple(
                _canonical_scalar(record.get(field)) for field in unique_key_fields
            )
            if key in keys_seen:
                reasons.append(f"duplicate_key:{'|'.join(key)}")
            keys_seen.add(key)

        record_date = _as_date(record.get("trade_date"))
        if record_date is not None:
            covered_dates.add(record_date)
        code = record.get("ts_code")
        if isinstance(code, str) and code:
            covered_codes.add(code)
            if record_date == request.trade_date:
                target_rows[code] = record
                if selected is not None:
                    typed_target_rows[(selected.record_type, code)] = record

        for field, value in record.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                if not math.isfinite(float(value)):
                    reasons.append(f"nonfinite_value:{field}:row={index}")
                if field in {"vol", "volume", "amount"} and float(value) < 0:
                    reasons.append(f"negative_value:{field}:row={index}")
        _append_ohlc_reason(record, index, reasons)

    if contract.require_target_date and request.trade_date not in covered_dates:
        reasons.append(f"missing_target_date:{request.trade_date.isoformat()}")
    if len(covered_dates) < contract.minimum_history_sessions:
        reasons.append(
            f"insufficient_history:{len(covered_dates)}:{contract.minimum_history_sessions}"
        )

    expected_codes = tuple(
        dict.fromkeys(
            (
                *contract.expected_codes,
                *(request.target_codes if contract.include_request_target_codes else ()),
            )
        )
    )
    required_target_types = tuple(
        item for item in contract.record_types if item.current_fact_fields
    )
    for code in expected_codes:
        if required_target_types:
            for item in required_target_types:
                target = typed_target_rows.get((item.record_type, code))
                if target is None:
                    reasons.append(
                        "missing_record_type:"
                        f"{item.record_type}:{code}:{request.trade_date.isoformat()}"
                    )
                    continue
                _append_current_fact_reasons(
                    code,
                    target,
                    item.current_fact_fields,
                    reasons,
                )
            continue

        target = target_rows.get(code)
        if target is None:
            if (
                not contract.current_fact_fields
                and payload.coverage_proven
                and code in payload.coverage_codes
            ):
                continue
            reasons.append(f"missing_code:{code}:{request.trade_date.isoformat()}")
            continue
        _append_current_fact_reasons(
            code,
            target,
            contract.current_fact_fields,
            reasons,
        )

    for identifier, publication_time in payload.publication_times.items():
        if publication_time > request.report_cutoff:
            reasons.append(f"look_ahead:{identifier}")

    for field in sorted(coverage_fields):
        if payload.field_coverage.get(field) is not True:
            reasons.append(f"field_coverage_incomplete:{field}")

    unique_reasons = tuple(dict.fromkeys(reasons))
    return GroupValidation(
        complete=not unique_reasons,
        reasons=unique_reasons,
        covered_codes=tuple(sorted(covered_codes)),
        covered_dates=tuple(sorted(covered_dates)),
    )


def _append_current_fact_reasons(
    code: str,
    target: dict[str, Any],
    fields: tuple[str, ...],
    reasons: list[str],
) -> None:
    for field in fields:
        if field not in target or target[field] is None:
            reasons.append(f"missing_current_fact:{code}:{field}")
        elif isinstance(target[field], str) and not target[field].strip():
            reasons.append(f"invalid_current_fact:{code}:{field}")
        elif isinstance(target[field], (int, float)) and not math.isfinite(
            float(target[field])
        ):
            reasons.append(f"invalid_current_fact:{code}:{field}")


def _append_ohlc_reason(
    record: dict[str, Any],
    index: int,
    reasons: list[str],
) -> None:
    values = [record.get(field) for field in ("open", "high", "low", "close")]
    if any(value is None for value in values):
        return
    if not all(
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        for value in values
    ):
        reasons.append(f"invalid_ohlc:row={index}")
        return
    open_value, high, low, close = (float(value) for value in values)
    if low > high or not (low <= open_value <= high) or not (low <= close <= high):
        reasons.append(f"invalid_ohlc:row={index}")


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    )


def _json_default(value: Any) -> str:
    if isinstance(value, (date, datetime, Enum)):
        return value.value if isinstance(value, Enum) else value.isoformat()
    raise TypeError(f"Unsupported canonical JSON value: {type(value).__name__}")


def _canonical_scalar(value: Any) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def _as_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _non_empty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _july_10_official_sessions() -> tuple[date, ...]:
    closed = {
        date(2026, 4, 6),
        date(2026, 5, 1),
        date(2026, 5, 4),
        date(2026, 5, 5),
        date(2026, 6, 19),
    }
    current = date(2026, 3, 12)
    end = date(2026, 7, 10)
    sessions: list[date] = []
    while current <= end:
        if current.weekday() < 5 and current not in closed:
            sessions.append(current)
        current += timedelta(days=1)
    return tuple(sessions)


JULY_10_OFFICIAL_SESSIONS = _july_10_official_sessions()
assert len(JULY_10_OFFICIAL_SESSIONS) == 82
assert JULY_10_OFFICIAL_SESSIONS[0] == date(2026, 3, 12)
assert JULY_10_OFFICIAL_SESSIONS[-1] == date(2026, 7, 10)


__all__ = [
    "AcquisitionGroupContract",
    "AcquisitionGroupId",
    "AcquisitionPayload",
    "AcquisitionRequest",
    "CapabilityEvidenceKind",
    "FailureClassification",
    "FormalRunState",
    "GroupValidation",
    "JULY_10_OFFICIAL_SESSIONS",
    "RecordTypeContract",
    "RouteCapabilityEvidence",
    "RouteKind",
    "validate_group_payload",
]
