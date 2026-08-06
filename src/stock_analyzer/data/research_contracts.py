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
    INGESTION_CUTOFF = "ingestion_cutoff"


class AvailabilityPolicy(str, Enum):
    BUSINESS_CLOSE = "business_close"
    VALID_FROM_CLOSE = "valid_from_close"
    NEXT_MORNING = "next_morning"
    SOURCE_PUBLISHED = "source_published"
    INGESTION_CUTOFF = "ingestion_cutoff"


class RevisionAvailabilityPolicy(str, Enum):
    OBSERVED_CHANGE = "observed_change"
    SOURCE_PUBLISHED = "source_published"


class StrictReplayLevel(str, Enum):
    STRICT = "strict"
    RECONSTRUCTED_CONSERVATIVE = "reconstructed_conservative"
    INGESTION_ONLY = "ingestion_only"


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
    required_columns: tuple[str, ...] = ()
    coverage_columns: tuple[str, ...] = ()
    minimum_required_field_coverage: float = Field(default=0.0, ge=0.0, le=1.0)
    business_time_field: str | None
    availability_policy: AvailabilityPolicy
    revision_availability_policy: RevisionAvailabilityPolicy
    strict_replay_level: StrictReplayLevel
    source_published_fields: tuple[str, ...] = ()
    mask_future_valid_to: bool = False


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
    reconstruct_source_revisions: bool = False
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


_BUSINESS_CLOSE_DATASETS = {
    ResearchDatasetId.TRADE_CALENDAR: "cal_date",
    ResearchDatasetId.EQUITY_DAILY: "trade_date",
    ResearchDatasetId.ADJ_FACTOR: "trade_date",
    ResearchDatasetId.DAILY_BASIC: "trade_date",
    ResearchDatasetId.STOCK_LIMIT: "trade_date",
    ResearchDatasetId.INDEX_DAILY: "trade_date",
    ResearchDatasetId.INDUSTRY_DAILY: "trade_date",
    ResearchDatasetId.THEME_DAILY: "trade_date",
    ResearchDatasetId.SUSPENSION: "trade_date",
    ResearchDatasetId.MINUTE_BAR: "trade_date",
}

_VALID_FROM_DATASETS = {
    ResearchDatasetId.INDUSTRY_CATALOG,
    ResearchDatasetId.INDUSTRY_MEMBER,
    ResearchDatasetId.THEME_CATALOG,
    ResearchDatasetId.THEME_MEMBER,
}

_INGESTION_ONLY_DATASETS = {
    ResearchDatasetId.SECURITY_MASTER,
    ResearchDatasetId.COMPANY_PROFILE,
    ResearchDatasetId.PLEDGE,
}

_SOURCE_PUBLISHED_FIELDS = {
    ResearchDatasetId.INCOME_STATEMENT: ("f_ann_date", "ann_date", "available_at"),
    ResearchDatasetId.BALANCE_SHEET: ("f_ann_date", "ann_date", "available_at"),
    ResearchDatasetId.CASH_FLOW: ("f_ann_date", "ann_date", "available_at"),
    ResearchDatasetId.FINANCIAL_INDICATOR: ("ann_date", "available_at"),
    ResearchDatasetId.MAIN_BUSINESS: ("ann_date", "available_at"),
    ResearchDatasetId.EARNINGS_FORECAST: ("ann_date", "available_at"),
    ResearchDatasetId.EARNINGS_EXPRESS: ("ann_date", "available_at"),
    ResearchDatasetId.ANNOUNCEMENT: ("available_at",),
    ResearchDatasetId.HOLDER_TRADE: ("ann_date", "available_at"),
    ResearchDatasetId.SHARE_FLOAT: ("ann_date", "available_at"),
    ResearchDatasetId.REPURCHASE: ("ann_date", "available_at"),
}


def _temporal_contract(dataset_id: ResearchDatasetId) -> dict[str, Any]:
    if dataset_id in _BUSINESS_CLOSE_DATASETS:
        return {
            "business_time_field": _BUSINESS_CLOSE_DATASETS[dataset_id],
            "availability_policy": AvailabilityPolicy.BUSINESS_CLOSE,
            "revision_availability_policy": RevisionAvailabilityPolicy.OBSERVED_CHANGE,
            "strict_replay_level": StrictReplayLevel.RECONSTRUCTED_CONSERVATIVE,
        }
    if dataset_id in _VALID_FROM_DATASETS:
        return {
            "business_time_field": "valid_from",
            "availability_policy": AvailabilityPolicy.VALID_FROM_CLOSE,
            "revision_availability_policy": RevisionAvailabilityPolicy.OBSERVED_CHANGE,
            "strict_replay_level": StrictReplayLevel.RECONSTRUCTED_CONSERVATIVE,
            "mask_future_valid_to": dataset_id in {
                ResearchDatasetId.INDUSTRY_MEMBER,
                ResearchDatasetId.THEME_MEMBER,
            },
        }
    if dataset_id in _INGESTION_ONLY_DATASETS:
        return {
            "business_time_field": None,
            "availability_policy": AvailabilityPolicy.INGESTION_CUTOFF,
            "revision_availability_policy": RevisionAvailabilityPolicy.OBSERVED_CHANGE,
            "strict_replay_level": StrictReplayLevel.INGESTION_ONLY,
        }
    if dataset_id is ResearchDatasetId.MARGIN_DETAIL:
        return {
            "business_time_field": "trade_date",
            "availability_policy": AvailabilityPolicy.NEXT_MORNING,
            "revision_availability_policy": RevisionAvailabilityPolicy.OBSERVED_CHANGE,
            "strict_replay_level": StrictReplayLevel.RECONSTRUCTED_CONSERVATIVE,
        }
    if dataset_id in _SOURCE_PUBLISHED_FIELDS:
        return {
            "business_time_field": None,
            "availability_policy": AvailabilityPolicy.SOURCE_PUBLISHED,
            "revision_availability_policy": RevisionAvailabilityPolicy.SOURCE_PUBLISHED,
            "strict_replay_level": (
                StrictReplayLevel.STRICT
                if dataset_id is ResearchDatasetId.ANNOUNCEMENT
                else StrictReplayLevel.RECONSTRUCTED_CONSERVATIVE
            ),
            "source_published_fields": _SOURCE_PUBLISHED_FIELDS[dataset_id],
        }
    raise AssertionError(f"missing temporal contract for {dataset_id.value}")


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
    required_columns: tuple[str, ...] | None = None,
    coverage_columns: tuple[str, ...] = (),
    minimum_coverage: float = 0.0,
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
        required_columns=required_columns or key,
        coverage_columns=coverage_columns,
        minimum_required_field_coverage=minimum_coverage,
        **_temporal_contract(dataset_id),
    )


@lru_cache(maxsize=1)
def research_contract_registry() -> dict[ResearchDatasetId, DatasetContract]:
    items = (
        _contract(ResearchDatasetId.TRADE_CALENDAR, ("exchange", "cal_date"), "cal_year", required=True, window="five_years_plus_buffer"),
        _contract(ResearchDatasetId.SECURITY_MASTER, ("ts_code", "valid_from"), "catalog_version", required=True, window="all_effective_securities"),
        _contract(
            ResearchDatasetId.EQUITY_DAILY,
            ("trade_date", "ts_code"),
            "trade_date",
            required=True,
            window="five_years",
            required_columns=(
                "trade_date", "ts_code", "open", "high", "low", "close",
                "pre_close", "change", "pct_chg", "volume", "amount",
            ),
            coverage_columns=("pre_close", "change", "pct_chg"),
            minimum_coverage=0.99,
        ),
        _contract(
            ResearchDatasetId.ADJ_FACTOR,
            ("trade_date", "ts_code"),
            "trade_date",
            required=True,
            window="five_years",
            required_columns=("trade_date", "ts_code", "adj_factor"),
            coverage_columns=("adj_factor",),
            minimum_coverage=0.99,
        ),
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
        _contract(
            ResearchDatasetId.CASH_FLOW,
            ("ts_code", "report_period", "report_type", "statement_type"),
            "report_period",
            window="12_quarters_and_5_years",
            availability="announcement time, never report-period end",
            required_columns=(
                "ts_code", "report_period", "report_type", "statement_type",
                "comp_type", "end_type", "ann_date", "f_ann_date", "update_flag",
            ),
        ),
        _contract(
            ResearchDatasetId.FINANCIAL_INDICATOR,
            ("ts_code", "report_period", "report_type"),
            "report_period",
            window="12_quarters_and_5_years",
            availability="announcement time, never report-period end",
            required_columns=("ts_code", "report_period", "report_type", "ann_date"),
        ),
        _contract(ResearchDatasetId.MAIN_BUSINESS, ("ts_code", "report_period", "classification", "item_name"), "report_period", window="12_quarters_and_5_years"),
        _contract(ResearchDatasetId.EARNINGS_FORECAST, ("ts_code", "report_period", "announcement_type", "ann_date"), "ann_month", lagged=True, window="five_years"),
        _contract(ResearchDatasetId.EARNINGS_EXPRESS, ("ts_code", "report_period", "announcement_type", "ann_date"), "ann_month", lagged=True, window="five_years"),
        _contract(ResearchDatasetId.ANNOUNCEMENT, ("announcement_id",), "announcement_month", sources=_OFFICIAL_DISCLOSURE, lagged=True, window="one_year_metadata_candidate_full_text", availability="official publication timestamp"),
        _contract(ResearchDatasetId.HOLDER_TRADE, ("provider_record_id",), "announcement_month", lagged=True, window="five_years"),
        _contract(ResearchDatasetId.SHARE_FLOAT, ("variant_group_id",), "float_month", lagged=True, window="one_year_history_and_three_year_known_future_schedule"),
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
    "AvailabilityPolicy",
    "AvailabilityPrecision",
    "BatchQualityResult",
    "CompletenessStatus",
    "DatasetContract",
    "FactBatch",
    "ResearchDatasetId",
    "RevisionAvailabilityPolicy",
    "SourcePolicy",
    "StrictReplayLevel",
    "research_contract",
    "research_contract_registry",
]
