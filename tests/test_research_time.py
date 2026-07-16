from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from stock_analyzer.data.research_contracts import (
    AvailabilityPrecision,
    ResearchDatasetId,
    research_contract,
)
from stock_analyzer.data.research_time import (
    resolve_initial_availability,
    resolve_revision_availability,
)


def test_calendar_initial_fact_uses_its_own_calendar_date_not_batch_through():
    resolved = resolve_initial_availability(
        ResearchDatasetId.TRADE_CALENDAR,
        {"cal_date": date(2025, 8, 15)},
        batch_ingested_at=datetime(2026, 7, 13, 16, tzinfo=timezone.utc),
        explicit_available_at=None,
    )

    assert resolved.available_at.astimezone(ZoneInfo("Asia/Shanghai")) == datetime(
        2025, 8, 15, 15, 1, tzinfo=ZoneInfo("Asia/Shanghai")
    )
    assert (
        resolved.precision
        is AvailabilityPrecision.INFERRED_FROM_ENDPOINT_POLICY
    )


def test_ingestion_only_fact_cannot_backdate_to_snapshot_date():
    ingested = datetime(2026, 7, 14, 1, 15, tzinfo=timezone.utc)
    resolved = resolve_initial_availability(
        ResearchDatasetId.COMPANY_PROFILE,
        {"valid_from": date(2026, 7, 13)},
        batch_ingested_at=ingested,
        explicit_available_at=datetime(2026, 7, 13, 16, tzinfo=timezone.utc),
    )

    assert resolved.available_at == ingested
    assert resolved.precision is AvailabilityPrecision.INGESTION_CUTOFF


def test_source_published_fact_requires_row_level_evidence():
    with pytest.raises(ValueError, match="row-level publication time"):
        resolve_initial_availability(
            ResearchDatasetId.ANNOUNCEMENT,
            {"announcement_id": "A1"},
            batch_ingested_at=datetime(2026, 7, 14, tzinfo=timezone.utc),
            explicit_available_at=None,
        )


def test_source_published_date_can_declare_conservative_precision():
    published = datetime(2025, 4, 30, 15, 59, 59, tzinfo=timezone.utc)
    resolved = resolve_initial_availability(
        ResearchDatasetId.INCOME_STATEMENT,
        {
            "available_at": published,
            "availability_precision": AvailabilityPrecision.DATE_CONSERVATIVE.value,
        },
        batch_ingested_at=datetime(2026, 7, 14, tzinfo=timezone.utc),
        explicit_available_at=published,
    )

    assert resolved.available_at == published
    assert resolved.precision is AvailabilityPrecision.DATE_CONSERVATIVE


def test_later_market_change_uses_ingestion_time_not_business_date():
    ingested = datetime(2026, 7, 12, 3, tzinfo=timezone.utc)
    resolved = resolve_revision_availability(
        research_contract(ResearchDatasetId.EQUITY_DAILY),
        {
            "trade_date": date(2026, 7, 10),
            "available_at": datetime(2026, 7, 10, 7, 1, tzinfo=timezone.utc),
        },
        batch_ingested_at=ingested,
        old_available_at=datetime(2026, 7, 10, 7, 1, tzinfo=timezone.utc),
    )

    assert resolved.available_at == ingested
    assert resolved.precision is AvailabilityPrecision.INGESTION_CUTOFF


def test_revision_rejects_source_update_before_previous_version():
    ingested = datetime(2026, 7, 12, 3, tzinfo=timezone.utc)
    resolved = resolve_revision_availability(
        research_contract(ResearchDatasetId.EQUITY_DAILY),
        {
            "source_updated_at": datetime(2026, 7, 9, 7, 1, tzinfo=timezone.utc),
        },
        batch_ingested_at=ingested,
        old_available_at=datetime(2026, 7, 10, 7, 1, tzinfo=timezone.utc),
    )

    assert resolved.available_at == ingested
    assert resolved.precision is AvailabilityPrecision.INGESTION_CUTOFF
