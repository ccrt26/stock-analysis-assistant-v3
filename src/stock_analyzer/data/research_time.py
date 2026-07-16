from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Mapping
from zoneinfo import ZoneInfo

import pandas as pd
from pydantic import BaseModel, ConfigDict

from stock_analyzer.data.research_contracts import (
    AvailabilityPolicy,
    AvailabilityPrecision,
    DatasetContract,
    ResearchDatasetId,
    RevisionAvailabilityPolicy,
    research_contract,
)


_MARKET_TIMEZONE = ZoneInfo("Asia/Shanghai")
_POST_CLOSE = time(15, 1)
_NEXT_MORNING = time(8, 0)


class ResolvedAvailability(BaseModel):
    model_config = ConfigDict(frozen=True)

    available_at: datetime
    precision: AvailabilityPrecision


def resolve_initial_availability(
    dataset_id: ResearchDatasetId | str,
    record: Mapping[str, Any],
    *,
    batch_ingested_at: datetime,
    explicit_available_at: Any | None,
) -> ResolvedAvailability:
    contract = research_contract(dataset_id)
    policy = contract.availability_policy

    if policy is AvailabilityPolicy.INGESTION_CUTOFF:
        return ResolvedAvailability(
            available_at=_as_utc(batch_ingested_at),
            precision=AvailabilityPrecision.INGESTION_CUTOFF,
        )
    if policy is AvailabilityPolicy.SOURCE_PUBLISHED:
        if _is_missing(explicit_available_at):
            raise ValueError(
                f"{contract.dataset_id.value} requires row-level publication time"
            )
        return ResolvedAvailability(
            available_at=_as_utc(explicit_available_at),
            precision=_record_precision(record),
        )
    if not _is_missing(explicit_available_at):
        return ResolvedAvailability(
            available_at=_as_utc(explicit_available_at),
            precision=_record_precision(
                record,
                default=AvailabilityPrecision.INFERRED_FROM_ENDPOINT_POLICY,
            ),
        )
    if not contract.business_time_field:
        raise ValueError(f"{contract.dataset_id.value} has no business time field")

    business_date = _as_date(record.get(contract.business_time_field))
    if policy in {
        AvailabilityPolicy.BUSINESS_CLOSE,
        AvailabilityPolicy.VALID_FROM_CLOSE,
    }:
        available_at = _at_market_time(business_date, _POST_CLOSE)
    elif policy is AvailabilityPolicy.NEXT_MORNING:
        available_at = _at_market_time(business_date + timedelta(days=1), _NEXT_MORNING)
    else:
        raise AssertionError(f"unhandled availability policy: {policy.value}")
    return ResolvedAvailability(
        available_at=available_at,
        precision=AvailabilityPrecision.INFERRED_FROM_ENDPOINT_POLICY,
    )


def resolve_revision_availability(
    contract: DatasetContract,
    normalized_row: Mapping[str, Any],
    *,
    batch_ingested_at: datetime,
    old_available_at: Any,
) -> ResolvedAvailability:
    previous = _as_utc(old_available_at)
    ingested = max(_as_utc(batch_ingested_at), previous)

    if (
        contract.revision_availability_policy
        is RevisionAvailabilityPolicy.SOURCE_PUBLISHED
    ):
        published = normalized_row.get("available_at")
        if _is_missing(published):
            raise ValueError(
                f"{contract.dataset_id.value} revision requires row-level publication time"
            )
        published_at = _as_utc(published)
        if published_at < previous:
            raise ValueError(
                f"{contract.dataset_id.value} revision publication precedes prior version"
            )
        return ResolvedAvailability(
            available_at=published_at,
            precision=_record_precision(normalized_row),
        )

    source_updated = normalized_row.get("source_updated_at")
    if not _is_missing(source_updated):
        source_updated_at = _as_utc(source_updated)
        if source_updated_at >= previous:
            return ResolvedAvailability(
                available_at=source_updated_at,
                precision=_record_precision(normalized_row),
            )
    return ResolvedAvailability(
        available_at=ingested,
        precision=AvailabilityPrecision.INGESTION_CUTOFF,
    )


def _record_precision(
    record: Mapping[str, Any],
    *,
    default: AvailabilityPrecision = AvailabilityPrecision.EXACT,
) -> AvailabilityPrecision:
    value = record.get("availability_precision")
    if _is_missing(value):
        return default
    return AvailabilityPrecision(str(value.value if isinstance(value, AvailabilityPrecision) else value))


def _as_date(value: Any) -> date:
    if _is_missing(value):
        raise ValueError("business time field is required")
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if len(text) == 8 and text.isdigit():
        return datetime.strptime(text, "%Y%m%d").date()
    return date.fromisoformat(text[:10])


def _at_market_time(value: date, clock: time) -> datetime:
    return datetime.combine(value, clock, tzinfo=_MARKET_TIMEZONE).astimezone(
        timezone.utc
    )


def _as_utc(value: Any) -> datetime:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp.to_pydatetime()


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


__all__ = [
    "ResolvedAvailability",
    "resolve_initial_availability",
    "resolve_revision_availability",
]
