from __future__ import annotations

from datetime import date

from stock_analyzer.data.readiness import (
    AcquisitionGroupContract,
    AcquisitionGroupId,
    RecordTypeContract,
)
from stock_analyzer.data.formal_policy import FORMAL_SCREENING_SESSION_COUNT


FORMAL_CONTRACT_VERSION = "formal-v2"


def _record_type(
    record_type: str,
    required_fields: tuple[str, ...],
    unique_key_fields: tuple[str, ...],
    *,
    legitimate_null_fields: dict[str, str] | None = None,
    current_fact_fields: tuple[str, ...] = (),
) -> RecordTypeContract:
    return RecordTypeContract(
        record_type=record_type,
        required_fields=("record_type", *required_fields),
        legitimate_null_fields=legitimate_null_fields or {},
        unique_key_fields=("record_type", *unique_key_fields),
        current_fact_fields=current_fact_fields,
    )


CALENDAR = _record_type(
    "calendar",
    ("trade_date", "is_open", "source_name"),
    ("trade_date",),
)
SECURITY = _record_type(
    "security",
    (
        "trade_date",
        "ts_code",
        "name",
        "exchange",
        "list_date",
        "status_verified",
        "is_suspended",
        "hard_excluded",
        "source_name",
    ),
    ("trade_date", "ts_code"),
    current_fact_fields=(
        "name",
        "exchange",
        "status_verified",
        "is_suspended",
        "hard_excluded",
    ),
)
EQUITY_BAR = _record_type(
    "equity_bar",
    (
        "trade_date",
        "ts_code",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "source_name",
    ),
    ("trade_date", "ts_code"),
    current_fact_fields=("open", "high", "low", "close", "volume", "amount"),
)
DAILY_BASIC = _record_type(
    "daily_basic",
    (
        "trade_date",
        "ts_code",
        "turnover_rate",
        "total_mv",
        "circ_mv",
        "pe_ttm",
        "pb",
        "source_name",
    ),
    ("trade_date", "ts_code"),
    legitimate_null_fields={
        "pe_ttm": "valuation_null_reason",
        "pb": "valuation_null_reason",
    },
    current_fact_fields=("turnover_rate", "total_mv", "circ_mv"),
)
INDEX_BAR = _record_type(
    "index_bar",
    (
        "trade_date",
        "ts_code",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "source_name",
    ),
    ("trade_date", "ts_code"),
)
INDUSTRY_MAPPING = _record_type(
    "industry_mapping",
    ("trade_date", "ts_code", "industry_code", "industry_name", "source_name"),
    ("trade_date", "ts_code"),
    current_fact_fields=("industry_code", "industry_name"),
)
BOARD_BAR = _record_type(
    "board_bar",
    (
        "trade_date",
        "board_code",
        "board_name",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "source_name",
    ),
    ("trade_date", "board_code"),
)
COMPANY_PROFILE = _record_type(
    "company_profile",
    ("trade_date", "ts_code", "business_summary", "source_name"),
    ("trade_date", "ts_code"),
    current_fact_fields=("business_summary",),
)
FINANCIAL_SUMMARY = _record_type(
    "financial_summary",
    (
        "trade_date",
        "ts_code",
        "period_end",
        "announcement_time",
        "revenue_yoy",
        "profit_yoy",
        "gross_margin",
        "operating_cashflow",
        "source_name",
    ),
    ("trade_date", "ts_code", "period_end"),
    legitimate_null_fields={
        "revenue_yoy": "fundamental_null_reason",
        "profit_yoy": "fundamental_null_reason",
        "gross_margin": "fundamental_null_reason",
        "operating_cashflow": "fundamental_null_reason",
    },
    current_fact_fields=("period_end", "announcement_time"),
)
MAIN_BUSINESS = _record_type(
    "main_business",
    (
        "trade_date",
        "ts_code",
        "period_end",
        "business_line",
        "revenue_share",
        "source_name",
    ),
    ("trade_date", "ts_code", "period_end", "business_line"),
)
FORECAST = _record_type(
    "forecast",
    (
        "trade_date",
        "ts_code",
        "announcement_time",
        "forecast_type",
        "min_change",
        "max_change",
        "source_name",
    ),
    ("trade_date", "ts_code", "announcement_time", "forecast_type"),
)
EXPRESS = _record_type(
    "express",
    (
        "trade_date",
        "ts_code",
        "announcement_time",
        "revenue",
        "profit",
        "source_name",
    ),
    ("trade_date", "ts_code", "announcement_time"),
)
OFFICIAL_EVENT = _record_type(
    "official_event",
    (
        "trade_date",
        "ts_code",
        "event_id",
        "event_type",
        "title",
        "publication_time",
        "source_reliability",
        "is_new_information",
        "hard_risk",
        "source_name",
    ),
    ("event_id",),
)
CONCEPT_MAPPING = _record_type(
    "concept_mapping",
    ("trade_date", "ts_code", "concept_code", "concept_name", "source_name"),
    ("trade_date", "ts_code", "concept_code"),
    current_fact_fields=("concept_code", "concept_name"),
)
MANUAL_HOLDING = _record_type(
    "manual_holding",
    ("trade_date", "ts_code", "name", "position_pct", "source_name"),
    ("trade_date", "ts_code"),
)


def _group(
    group_id: AcquisitionGroupId,
    record_types: tuple[RecordTypeContract, ...],
    expected_codes: tuple[str, ...],
    *,
    minimum_history_sessions: int = 0,
    include_request_target_codes: bool = True,
) -> AcquisitionGroupContract:
    return AcquisitionGroupContract(
        group_id=group_id,
        contract_version=FORMAL_CONTRACT_VERSION,
        required_fields=(),
        unique_key_fields=(),
        minimum_history_sessions=minimum_history_sessions,
        require_target_date=True,
        expected_codes=tuple(dict.fromkeys(expected_codes)),
        include_request_target_codes=include_request_target_codes,
        record_types=record_types,
    )


def build_screening_contracts(
    trade_date: date,
    expected_codes: tuple[str, ...],
) -> dict[AcquisitionGroupId, AcquisitionGroupContract]:
    del trade_date
    return {
        AcquisitionGroupId.CALENDAR_UNIVERSE: _group(
            AcquisitionGroupId.CALENDAR_UNIVERSE,
            (CALENDAR, SECURITY),
            expected_codes,
            minimum_history_sessions=FORMAL_SCREENING_SESSION_COUNT,
        ),
        AcquisitionGroupId.MARKET_DECISION: _group(
            AcquisitionGroupId.MARKET_DECISION,
            (EQUITY_BAR, DAILY_BASIC, INDEX_BAR),
            expected_codes,
            minimum_history_sessions=FORMAL_SCREENING_SESSION_COUNT,
        ),
    }


def build_target_contracts(
    trade_date: date,
    target_codes: tuple[str, ...],
    include_concepts: bool = False,
) -> dict[AcquisitionGroupId, AcquisitionGroupContract]:
    del trade_date
    contracts = {
        AcquisitionGroupId.BOARD_INDUSTRY: _group(
            AcquisitionGroupId.BOARD_INDUSTRY,
            (INDUSTRY_MAPPING, BOARD_BAR),
            target_codes,
        ),
        AcquisitionGroupId.CANDIDATE_FUNDAMENTAL: _group(
            AcquisitionGroupId.CANDIDATE_FUNDAMENTAL,
            (COMPANY_PROFILE, FINANCIAL_SUMMARY, MAIN_BUSINESS, FORECAST, EXPRESS),
            target_codes,
        ),
        AcquisitionGroupId.OFFICIAL_EVENTS_RISK: _group(
            AcquisitionGroupId.OFFICIAL_EVENTS_RISK,
            (OFFICIAL_EVENT,),
            target_codes,
        ),
        AcquisitionGroupId.MANUAL_HOLDINGS: _group(
            AcquisitionGroupId.MANUAL_HOLDINGS,
            (MANUAL_HOLDING,),
            (),
            include_request_target_codes=False,
        ),
    }
    if include_concepts:
        contracts[AcquisitionGroupId.CONCEPT_THEME] = _group(
            AcquisitionGroupId.CONCEPT_THEME,
            (CONCEPT_MAPPING,),
            target_codes,
        )
    return contracts


__all__ = [
    "FORMAL_CONTRACT_VERSION",
    "build_screening_contracts",
    "build_target_contracts",
]
