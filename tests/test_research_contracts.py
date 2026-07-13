from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from stock_analyzer.data.research_contracts import (
    CompletenessStatus,
    FactBatch,
    ResearchDatasetId,
    research_contract_registry,
)


def test_registry_covers_the_approved_research_scope_without_web_wrapper_fallbacks():
    registry = research_contract_registry()

    required = {
        ResearchDatasetId.TRADE_CALENDAR,
        ResearchDatasetId.SECURITY_MASTER,
        ResearchDatasetId.EQUITY_DAILY,
        ResearchDatasetId.ADJ_FACTOR,
        ResearchDatasetId.DAILY_BASIC,
        ResearchDatasetId.STOCK_LIMIT,
        ResearchDatasetId.INDEX_DAILY,
        ResearchDatasetId.INDUSTRY_CATALOG,
        ResearchDatasetId.INDUSTRY_MEMBER,
        ResearchDatasetId.INDUSTRY_DAILY,
        ResearchDatasetId.THEME_CATALOG,
        ResearchDatasetId.THEME_MEMBER,
        ResearchDatasetId.THEME_DAILY,
        ResearchDatasetId.COMPANY_PROFILE,
        ResearchDatasetId.INCOME_STATEMENT,
        ResearchDatasetId.BALANCE_SHEET,
        ResearchDatasetId.CASH_FLOW,
        ResearchDatasetId.FINANCIAL_INDICATOR,
        ResearchDatasetId.MAIN_BUSINESS,
        ResearchDatasetId.EARNINGS_FORECAST,
        ResearchDatasetId.EARNINGS_EXPRESS,
        ResearchDatasetId.ANNOUNCEMENT,
        ResearchDatasetId.HOLDER_TRADE,
        ResearchDatasetId.SHARE_FLOAT,
        ResearchDatasetId.REPURCHASE,
        ResearchDatasetId.PLEDGE,
        ResearchDatasetId.SUSPENSION,
        ResearchDatasetId.MARGIN_DETAIL,
        ResearchDatasetId.MINUTE_BAR,
    }
    assert required <= set(registry)
    assert all(contract.business_key for contract in registry.values())
    assert all(contract.partition_field for contract in registry.values())
    assert {
        source.lower()
        for contract in registry.values()
        for source in contract.source_policy.approved_sources
    }.isdisjoint({"akshare", "baostock"})


def test_fact_batch_requires_one_partition_and_governance_metadata():
    batch = FactBatch(
        dataset_id=ResearchDatasetId.EQUITY_DAILY,
        partition_value="2026-07-10",
        source_name="tushare",
        source_endpoint="daily",
        ingestion_run_id="run-1",
        ingested_at=datetime(2026, 7, 10, 10, tzinfo=timezone.utc),
        default_available_at=datetime(2026, 7, 10, 7, 1, tzinfo=timezone.utc),
        records=[
            {
                "trade_date": date(2026, 7, 10),
                "ts_code": "000001.SZ",
                "open": 10.0,
                "high": 10.5,
                "low": 9.8,
                "close": 10.2,
                "vol": 100.0,
                "amount": 1000.0,
            }
        ],
    )
    assert batch.partition_value == "2026-07-10"

    with pytest.raises(ValidationError):
        FactBatch(
            dataset_id=ResearchDatasetId.EQUITY_DAILY,
            partition_value="",
            source_name="tushare",
            source_endpoint="daily",
            ingestion_run_id="run-2",
            ingested_at=datetime.now(timezone.utc),
            records=[],
        )


def test_completeness_status_distinguishes_waiting_from_empty_success():
    assert CompletenessStatus.WAITING_UPSTREAM != CompletenessStatus.COMPLETE
    assert CompletenessStatus.COMPLETE_WITH_DECLARED_GAPS.value == (
        "complete_with_declared_gaps"
    )
