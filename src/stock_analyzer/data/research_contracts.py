from __future__ import annotations

from datetime import datetime
from enum import Enum
from functools import lru_cache
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ResearchDatasetId(str, Enum):
    TRADE_CALENDAR = "trade_calendar"
    SECURITY_MASTER = "security_master"
    EQUITY_DAILY = "equity_daily"
    ADJ_FACTOR = "adj_factor"
    DAILY_BASIC = "daily_basic"
    STOCK_LIMIT = "stock_limit"
    INDEX_DAILY = "index_daily"
    INDUSTRY_CATALOG = "industry_catalog"
    INDUSTRY_MEMBER = "industry_member"
    INDUSTRY_DAILY = "industry_daily"
    THEME_CATALOG = "theme_catalog"
    THEME_MEMBER = "theme_member"
    THEME_DAILY = "theme_daily"
    COMPANY_PROFILE = "company_profile"
    INCOME_STATEMENT = "income_statement"
    BALANCE_SHEET = "balance_sheet"
    CASH_FLOW = "cash_flow"
    FINANCIAL_INDICATOR = "financial_indicator"
    MAIN_BUSINESS = "main_business"
    EARNINGS_FORECAST = "earnings_forecast"
    EARNINGS_EXPRESS = "earnings_express"
    ANNOUNCEMENT = "announcement"
    HOLDER_TRADE = "holder_trade"
    SHARE_FLOAT = "share_float"
    REPURCHASE = "repurchase"
    PLEDGE = "pledge"
    SUSPENSION = "suspension"
    MARGIN_DETAIL = "margin_detail"
    MINUTE_BAR = "minute_bar"


class CompletenessStatus(str, Enum):
    COMPLETE = "complete"
    COMPLETE_WITH_DECLARED_GAPS = "complete_with_declared_gaps"
    WAITING_UPSTREAM = "waiting_upstream"
    FAILED = "failed"
    QUARANTINED = "quarantined"


class AvailabilityPrecision(str, Enum):
    EXACT = "exact"
    MINUTE = "minute"
    DATE_CONSERVATIVE = "date_conservative"
    INFERRED_FROM_ENDPOINT_POLICY = "inferred_from_endpoint_policy"


class SourcePolicy(BaseModel):
    approved_sources: tuple[str, ...]
    fail_closed: bool = True
    notes: str = ""


class DatasetContract(BaseModel):
    dataset_id: ResearchDatasetId
    business_key: tuple[str, ...]
    partition_field: str
    source_policy: SourcePolicy
    required_for_close_screen: bool = False
    lagged: bool = False
    history_window: str
    availability_notes: str


class FactBatch(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    dataset_id: ResearchDatasetId
    partition_value: str = Field(min_length=1)
    source_name: str = Field(min_length=1)
    source_endpoint: str = Field(min_length=1)
    ingestion_run_id: str = Field(min_length=1)
    ingested_at: datetime
    default_available_at: datetime | None = None
    availability_precision: AvailabilityPrecision = AvailabilityPrecision.EXACT
    records: list[dict[str, Any]]

    @field_validator("partition_value", "source_name", "source_endpoint", "ingestion_run_id")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be blank")
        return cleaned


class BatchQualityResult(BaseModel):
    complete: bool
    status: CompletenessStatus
    row_count: int = Field(ge=0)
    checks: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


_TUSHARE = ("tushare",)
_OFFICIAL_DISCLOSURE = ("cninfo", "sse", "szse", "bse", "csrc")


def _contract(
    dataset_id: ResearchDatasetId,
    key: tuple[str, ...],
    partition: str,
    *,
    sources: tuple[str, ...] = _TUSHARE,
    required: bool = False,
    lagged: bool = False,
    window: str = "incremental",
    availability: str = "use provider publication semantics",
) -> DatasetContract:
    return DatasetContract(
        dataset_id=dataset_id,
        business_key=key,
        partition_field=partition,
        source_policy=SourcePolicy(approved_sources=sources),
        required_for_close_screen=required,
        lagged=lagged,
        history_window=window,
        availability_notes=availability,
    )


@lru_cache(maxsize=1)
def research_contract_registry() -> dict[ResearchDatasetId, DatasetContract]:
    items = (
        _contract(ResearchDatasetId.TRADE_CALENDAR, ("exchange", "cal_date"), "cal_year", required=True, window="five_years_plus_buffer"),
        _contract(ResearchDatasetId.SECURITY_MASTER, ("ts_code", "valid_from"), "catalog_version", required=True, window="all_effective_securities"),
        _contract(ResearchDatasetId.EQUITY_DAILY, ("trade_date", "ts_code"), "trade_date", required=True, window="five_years"),
        _contract(ResearchDatasetId.ADJ_FACTOR, ("trade_date", "ts_code"), "trade_date", required=True, window="five_years"),
        _contract(ResearchDatasetId.DAILY_BASIC, ("trade_date", "ts_code"), "trade_date", required=True, window="five_years"),
        _contract(ResearchDatasetId.STOCK_LIMIT, ("trade_date", "ts_code"), "trade_date", required=True, window="five_years"),
        _contract(ResearchDatasetId.INDEX_DAILY, ("trade_date", "index_code"), "trade_date", required=True, window="five_years"),
        _contract(ResearchDatasetId.INDUSTRY_CATALOG, ("industry_system", "level", "industry_code", "valid_from"), "classification_version", required=True, window="sw2021_full_hierarchy"),
        _contract(ResearchDatasetId.INDUSTRY_MEMBER, ("ts_code", "industry_system", "level", "valid_from"), "classification_version", required=True, window="available_effective_history"),
        _contract(ResearchDatasetId.INDUSTRY_DAILY, ("trade_date", "industry_code"), "trade_date", required=True, window="250_sessions"),
        _contract(ResearchDatasetId.THEME_CATALOG, ("publisher", "theme_code", "valid_from"), "catalog_version", required=True, window="controlled_catalog"),
        _contract(ResearchDatasetId.THEME_MEMBER, ("theme_code", "ts_code", "valid_from"), "catalog_version", required=True, window="available_effective_history"),
        _contract(ResearchDatasetId.THEME_DAILY, ("trade_date", "theme_code"), "trade_date", required=True, window="250_sessions"),
        _contract(ResearchDatasetId.COMPANY_PROFILE, ("ts_code", "valid_from"), "catalog_version", window="all_listed_companies"),
        _contract(ResearchDatasetId.INCOME_STATEMENT, ("ts_code", "report_period", "report_type", "statement_type"), "report_period", window="12_quarters_and_5_years", availability="announcement time, never report-period end"),
        _contract(ResearchDatasetId.BALANCE_SHEET, ("ts_code", "report_period", "report_type", "statement_type"), "report_period", window="12_quarters_and_5_years", availability="announcement time, never report-period end"),
        _contract(ResearchDatasetId.CASH_FLOW, ("ts_code", "report_period", "report_type", "statement_type"), "report_period", window="12_quarters_and_5_years", availability="announcement time, never report-period end"),
        _contract(ResearchDatasetId.FINANCIAL_INDICATOR, ("ts_code", "report_period", "report_type"), "report_period", window="12_quarters_and_5_years", availability="announcement time, never report-period end"),
        _contract(ResearchDatasetId.MAIN_BUSINESS, ("ts_code", "report_period", "classification", "item_name"), "report_period", window="12_quarters_and_5_years"),
        _contract(ResearchDatasetId.EARNINGS_FORECAST, ("ts_code", "report_period", "announcement_type", "ann_date"), "ann_month", lagged=True, window="five_years"),
        _contract(ResearchDatasetId.EARNINGS_EXPRESS, ("ts_code", "report_period", "announcement_type", "ann_date"), "ann_month", lagged=True, window="five_years"),
        _contract(ResearchDatasetId.ANNOUNCEMENT, ("announcement_id",), "announcement_month", sources=_OFFICIAL_DISCLOSURE, lagged=True, window="one_year_metadata_candidate_full_text", availability="official publication timestamp"),
        _contract(ResearchDatasetId.HOLDER_TRADE, ("provider_record_id",), "announcement_month", lagged=True, window="five_years"),
        _contract(ResearchDatasetId.SHARE_FLOAT, ("provider_record_id",), "float_month", lagged=True, window="five_years"),
        _contract(ResearchDatasetId.REPURCHASE, ("provider_record_id",), "announcement_month", lagged=True, window="five_years"),
        _contract(ResearchDatasetId.PLEDGE, ("ts_code", "end_date"), "end_month", lagged=True, window="five_years_quarterly_snapshots"),
        _contract(ResearchDatasetId.SUSPENSION, ("ts_code", "trade_date", "suspend_type"), "trade_date", lagged=True, window="one_year"),
        _contract(ResearchDatasetId.MARGIN_DETAIL, ("trade_date", "ts_code", "exchange"), "trade_date", lagged=True, window="250_sessions", availability="T+1 or actual provider publication time"),
        _contract(ResearchDatasetId.MINUTE_BAR, ("trade_date", "instrument_code", "minute", "frequency"), "trade_date", window="20_sessions_for_indexes_and_frozen_candidates", availability="after each minute; daily research uses post-close availability"),
    )
    return {item.dataset_id: item for item in items}


def research_contract(dataset_id: ResearchDatasetId | str) -> DatasetContract:
    return research_contract_registry()[ResearchDatasetId(dataset_id)]


__all__ = [
    "AvailabilityPrecision",
    "BatchQualityResult",
    "CompletenessStatus",
    "DatasetContract",
    "FactBatch",
    "ResearchDatasetId",
    "SourcePolicy",
    "research_contract",
    "research_contract_registry",
]
