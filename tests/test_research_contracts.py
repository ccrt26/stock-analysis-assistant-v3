from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from stock_analyzer.data.research_contracts import (
    AvailabilityPolicy,
    CompletenessStatus,
    FactBatch,
    ResearchDatasetId,
    RevisionAvailabilityPolicy,
    StrictReplayLevel,
    research_contract,
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


def test_every_research_dataset_has_an_explicit_temporal_contract():
    registry = research_contract_registry()

    assert set(registry) == set(ResearchDatasetId)
    for dataset, contract in registry.items():
        assert contract.availability_policy is not None, dataset.value
        assert contract.revision_availability_policy is not None, dataset.value
        assert contract.strict_replay_level is not None, dataset.value


def test_temporal_contract_separates_reconstructible_and_disclosure_facts():
    assert research_contract(ResearchDatasetId.TRADE_CALENDAR).availability_policy == (
        AvailabilityPolicy.BUSINESS_CLOSE
    )
    assert (
        research_contract(ResearchDatasetId.TRADE_CALENDAR).business_time_field
        == "cal_date"
    )
    assert (
        research_contract(ResearchDatasetId.INDUSTRY_DAILY).business_time_field
        == "trade_date"
    )
    assert research_contract(ResearchDatasetId.ANNOUNCEMENT).availability_policy == (
        AvailabilityPolicy.SOURCE_PUBLISHED
    )
    assert (
        research_contract(ResearchDatasetId.ANNOUNCEMENT).revision_availability_policy
        == RevisionAvailabilityPolicy.SOURCE_PUBLISHED
    )
    assert research_contract(ResearchDatasetId.COMPANY_PROFILE).availability_policy == (
        AvailabilityPolicy.INGESTION_CUTOFF
    )
    assert research_contract(ResearchDatasetId.PLEDGE).strict_replay_level == (
        StrictReplayLevel.INGESTION_ONLY
    )


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


def test_history_windows_are_tiered_by_business_value():
    registry = research_contract_registry()

    assert registry[ResearchDatasetId.EQUITY_DAILY].history_window == "five_years"
    assert registry[ResearchDatasetId.INDUSTRY_DAILY].history_window == "250_sessions"
    assert registry[ResearchDatasetId.THEME_DAILY].history_window == "250_sessions"
    assert registry[ResearchDatasetId.SUSPENSION].history_window == "one_year"
    assert registry[ResearchDatasetId.MARGIN_DETAIL].history_window == "250_sessions"
    assert registry[ResearchDatasetId.MINUTE_BAR].history_window.startswith("20_sessions")


def test_equity_daily_contract_requires_complete_vendor_daily_schema_without_mixing_returns():
    contract = research_contract_registry()[ResearchDatasetId.EQUITY_DAILY]

    assert {
        "trade_date",
        "ts_code",
        "open",
        "high",
        "low",
        "close",
        "pre_close",
        "change",
        "pct_chg",
        "volume",
        "amount",
    } <= set(contract.required_columns)
    assert contract.minimum_required_field_coverage == 0.99


def test_adjustment_factor_contract_requires_the_factor_used_by_derived_returns():
    contract = research_contract_registry()[ResearchDatasetId.ADJ_FACTOR]

    assert {"trade_date", "ts_code", "adj_factor"} <= set(
        contract.required_columns
    )
    assert contract.coverage_columns == ("adj_factor",)
    assert contract.minimum_required_field_coverage == 0.99


def test_financial_indicator_contract_does_not_invent_cash_flow_update_flag():
    registry = research_contract_registry()

    assert registry[ResearchDatasetId.FINANCIAL_INDICATOR].business_key == (
        "ts_code",
        "report_period",
        "report_type",
    )
    assert "update_flag" not in registry[
        ResearchDatasetId.FINANCIAL_INDICATOR
    ].required_columns
    assert registry[ResearchDatasetId.CASH_FLOW].business_key == (
        "ts_code",
        "report_period",
        "report_type",
        "statement_type",
    )
