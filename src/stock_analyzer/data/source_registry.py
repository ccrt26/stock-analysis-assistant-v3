from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict

from stock_analyzer.data.models import SourceStatus
from stock_analyzer.data.readiness import AcquisitionGroupId
from stock_analyzer.domain.models import DataRecoveryAttempt, DataRequirementLevel


class DataFamilySourcePlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    family: str
    level: DataRequirementLevel
    primary_path: str
    backup_path: str
    local_cache_path: str
    formal_group_id: AcquisitionGroupId | None = None
    primary_route_id: str | None = None
    backup_route_id: str | None = None
    approved_single_source: bool = False


_SOURCE_REGISTRY = {
    "stock_identity": DataFamilySourcePlan(
        family="stock_identity",
        level=DataRequirementLevel.REQUIRED,
        primary_path="TushareMarketDataSource.fetch_stock_basic",
        backup_path="akshare.stock_info_a_code_name",
        local_cache_path=(
            "local_warehouse/parquet/stock_basic/"
            "snapshot_date=<date>/data.parquet"
        ),
    ),
    "daily_ohlcv": DataFamilySourcePlan(
        family="daily_ohlcv",
        level=DataRequirementLevel.REQUIRED,
        primary_path="TushareMarketDataSource.fetch_daily",
        backup_path="akshare.stock_zh_a_hist",
        local_cache_path=(
            "local_warehouse/parquet/market_daily/"
            "trade_date=<date>/data.parquet"
        ),
    ),
    "daily_basic_valuation": DataFamilySourcePlan(
        family="daily_basic_valuation",
        level=DataRequirementLevel.REQUIRED,
        primary_path="TushareMarketDataSource.fetch_daily_basic",
        backup_path="akshare.eastmoney_valuation",
        local_cache_path=(
            "local_warehouse/parquet/daily_basic/"
            "trade_date=<date>/data.parquet"
        ),
    ),
    "company_profile": DataFamilySourcePlan(
        family="company_profile",
        level=DataRequirementLevel.REQUIRED,
        primary_path="tushare.stock_company",
        backup_path="akshare.stock_individual_info_em|eastmoney.f10_profile",
        local_cache_path=(
            "local_warehouse/parquet/company_profile/"
            "snapshot_date=<date>/data.parquet"
        ),
    ),
    "industry_board": DataFamilySourcePlan(
        family="industry_board",
        level=DataRequirementLevel.REQUIRED,
        primary_path="tushare.stock_basic.industry|tushare.index_classify",
        backup_path="akshare.eastmoney_industry_board",
        local_cache_path=(
            "local_warehouse/parquet/industry_board/"
            "trade_date=<date>/data.parquet"
        ),
    ),
    "concept_tags": DataFamilySourcePlan(
        family="concept_tags",
        level=DataRequirementLevel.ENHANCED,
        primary_path="tushare.concept|concept_detail",
        backup_path="akshare.eastmoney_concept_board",
        local_cache_path=(
            "local_warehouse/parquet/concept_tags/"
            "trade_date=<date>/data.parquet"
        ),
    ),
    "fundamentals_summary": DataFamilySourcePlan(
        family="fundamentals_summary",
        level=DataRequirementLevel.ENHANCED,
        primary_path=(
            "tushare.income|balancesheet|cashflow|fina_indicator|forecast|express"
        ),
        backup_path="akshare.financial_abstract|eastmoney.f10_financial_summary",
        local_cache_path=(
            "local_warehouse/parquet/fundamental_summary/"
            "snapshot_date=<date>/data.parquet"
        ),
    ),
    "market_board_context": DataFamilySourcePlan(
        family="market_board_context",
        level=DataRequirementLevel.REQUIRED,
        primary_path="tushare.index_daily|local_warehouse.market_breadth",
        backup_path="akshare.index_zh_a_hist|akshare.board_history",
        local_cache_path=(
            "local_warehouse/parquet/market_context/"
            "trade_date=<date>/data.parquet"
        ),
    ),
    "events_catalysts": DataFamilySourcePlan(
        family="events_catalysts",
        level=DataRequirementLevel.REQUIRED,
        primary_path="OfficialDisclosureClient.fetch_official_events_risk",
        backup_path="CninfoDisclosureClient.fetch_official_events_risk",
        local_cache_path=(
            "local_warehouse/parquet/event_catalysts/"
            "trade_date=<date>/data.parquet"
        ),
    ),
    "official_hard_risk": DataFamilySourcePlan(
        family="official_hard_risk",
        level=DataRequirementLevel.REQUIRED,
        primary_path="tushare.stock_basic|tushare.suspend_d|official_exchange_risk_cache",
        backup_path="sse.risk_cache|szse.risk_cache|csrc.risk_cache",
        local_cache_path=(
            "local_warehouse/parquet/risk_events/"
            "trade_date=<date>/data.parquet"
        ),
    ),
    "manual_holdings": DataFamilySourcePlan(
        family="manual_holdings",
        level=DataRequirementLevel.REQUIRED,
        primary_path="local_warehouse.manual_holdings",
        backup_path="",
        local_cache_path=(
            "local_warehouse/manual/holdings.json|"
            "local_warehouse/manual/actions.jsonl"
        ),
    ),
}


_FORMAL_ROUTE_BINDINGS = {
    "stock_identity": (
        AcquisitionGroupId.CALENDAR_UNIVERSE,
        "tushare.calendar_universe.v1",
        "official_exchange.calendar_universe.v1",
    ),
    "daily_ohlcv": (
        AcquisitionGroupId.MARKET_DECISION,
        "tushare.market_decision.v1",
        "eastmoney.market_decision.v1",
    ),
    "daily_basic_valuation": (
        AcquisitionGroupId.MARKET_DECISION,
        "tushare.market_decision.v1",
        "eastmoney.market_decision.v1",
    ),
    "company_profile": (
        AcquisitionGroupId.CANDIDATE_FUNDAMENTAL,
        "tushare.candidate_fundamental.v1",
        "eastmoney.candidate_fundamental.v1",
    ),
    "industry_board": (
        AcquisitionGroupId.BOARD_INDUSTRY,
        "tushare.board_industry.v1",
        "eastmoney.board_industry.v1",
    ),
    "concept_tags": (
        AcquisitionGroupId.CONCEPT_THEME,
        "tushare.concept_theme.v1",
        "eastmoney.concept_theme.v1",
    ),
    "fundamentals_summary": (
        AcquisitionGroupId.CANDIDATE_FUNDAMENTAL,
        "tushare.candidate_fundamental.v1",
        "eastmoney.candidate_fundamental.v1",
    ),
    "market_board_context": (
        AcquisitionGroupId.MARKET_DECISION,
        "tushare.market_decision.v1",
        "eastmoney.market_decision.v1",
    ),
    "events_catalysts": (
        AcquisitionGroupId.OFFICIAL_EVENTS_RISK,
        "official.events_risk.v1",
        "cninfo.direct.events_risk.v2",
    ),
    "official_hard_risk": (
        AcquisitionGroupId.OFFICIAL_EVENTS_RISK,
        "official.events_risk.v1",
        "cninfo.direct.events_risk.v2",
    ),
    "manual_holdings": (
        AcquisitionGroupId.MANUAL_HOLDINGS,
        "local.manual_holdings.v1",
        None,
    ),
}


def strategy_v2_source_registry() -> dict[str, DataFamilySourcePlan]:
    return {
        family: plan.model_copy(
            update={
                "formal_group_id": binding[0],
                "primary_route_id": binding[1],
                "backup_route_id": binding[2],
                "approved_single_source": family == "manual_holdings",
            }
        )
        for family, plan in _SOURCE_REGISTRY.items()
        for binding in (_FORMAL_ROUTE_BINDINGS[family],)
    }


def record_recovery_attempt(
    family: str,
    source_name: str,
    status: SourceStatus,
    message: str,
    trade_date: date,
) -> DataRecoveryAttempt:
    return DataRecoveryAttempt(
        family=family,
        source_name=source_name,
        source=source_name,
        status=status.value,
        message=message,
        trade_date=trade_date,
        succeeded=status == SourceStatus.SUCCESS,
        error=None if status == SourceStatus.SUCCESS else message,
    )


__all__ = [
    "DataFamilySourcePlan",
    "record_recovery_attempt",
    "strategy_v2_source_registry",
]
