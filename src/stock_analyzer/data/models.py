from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from stock_analyzer.domain.models import FeatureSnapshot, StockSnapshot


class SourceGrade(str, Enum):
    PRIMARY = "primary"
    LIVE_BACKUP = "live_backup"
    HISTORICAL_CACHE = "historical_cache"


class SourceStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class DataStatus(str, Enum):
    COMPLETE_PRIMARY = "complete_primary"
    COMPLETE_LIVE_BACKUP = "complete_live_backup"
    INSUFFICIENT_LIVE_DATA = "insufficient_live_data"
    CACHE_ONLY_CURRENT_DATE = "cache_only_current_date"


class SourceRunRecord(BaseModel):
    trade_date: date
    source_name: str
    stage: str
    status: SourceStatus
    message: str
    attempt: int = 1
    source_grade: SourceGrade
    data_status: DataStatus
    record_count: int = 0
    field_coverage: dict[str, bool] = Field(default_factory=dict)
    payload: dict[str, object] = Field(default_factory=dict)


class StockBasicRow(BaseModel):
    ts_code: str
    name: str
    exchange: str
    list_date: Optional[date] = None


class DailyBar(BaseModel):
    trade_date: date
    ts_code: str
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: float
    pre_close: Optional[float] = None
    pct_chg: Optional[float] = None
    vol: Optional[float] = None
    amount: Optional[float] = None
    source_name: str
    source_grade: SourceGrade
    fetched_at: Optional[datetime] = None


class DailyBasicRow(BaseModel):
    trade_date: date
    ts_code: str
    turnover_rate: Optional[float] = None
    total_mv: Optional[float] = None
    circ_mv: Optional[float] = None
    pe_ttm: Optional[float] = None
    pb: Optional[float] = None
    source_name: str
    source_grade: SourceGrade
    fetched_at: Optional[datetime] = None


class CompanyProfileRow(BaseModel):
    trade_date: date
    ts_code: str
    business_summary: Optional[str] = None
    main_business_lines: list[str] = Field(default_factory=list)
    source_name: str
    source_grade: SourceGrade


class FundamentalSummaryRow(BaseModel):
    trade_date: date
    ts_code: str
    revenue_yoy: Optional[float] = None
    profit_yoy: Optional[float] = None
    gross_margin: Optional[float] = None
    operating_cashflow: Optional[float] = None
    source_name: str
    source_grade: SourceGrade


class BoardContextRow(BaseModel):
    trade_date: date
    board_name: str
    board_type: str
    relative_strength_20d: Optional[float] = None
    breadth: Optional[float] = None
    turnover_change: Optional[float] = None
    source_name: str
    source_grade: SourceGrade


class ConceptTagRow(BaseModel):
    trade_date: date
    ts_code: str
    concept_name: str
    source_name: str
    source_grade: SourceGrade


class EventCatalystRow(BaseModel):
    trade_date: date
    ts_code: str
    event_type: str
    title: str
    source_reliability: str
    is_new_information: bool
    source_name: str
    source_grade: SourceGrade


class OfficialRiskEventRow(BaseModel):
    trade_date: date
    ts_code: str
    risk_type: str
    description: str
    source_name: str
    source_grade: SourceGrade


class DataUnavailableNotice(BaseModel):
    trade_date: date
    reason: str
    last_successful_trade_date: Optional[date] = None
    source_runs: list[SourceRunRecord] = Field(default_factory=list)


class MarketDataBundle(BaseModel):
    trade_date: date
    data_status: DataStatus
    source_grade: SourceGrade
    source_versions: dict[str, str]
    stock_basic: list[StockBasicRow]
    daily_bars: list[DailyBar]
    daily_basic: list[DailyBasicRow]
    source_runs: list[SourceRunRecord] = Field(default_factory=list)
    stocks: list[StockSnapshot] = Field(default_factory=list)
    stock_names: dict[str, str] = Field(default_factory=dict)
    feature_profiles: dict[str, FeatureSnapshot] = Field(default_factory=dict)

    @property
    def can_generate_decisions(self) -> bool:
        return self.data_status in {
            DataStatus.COMPLETE_PRIMARY,
            DataStatus.COMPLETE_LIVE_BACKUP,
        }

    def to_pipeline_inputs(
        self,
    ) -> tuple[list[StockSnapshot], dict[str, str], dict[str, FeatureSnapshot]]:
        if not self.can_generate_decisions:
            return [], {}, {}
        return self.stocks, self.stock_names, self.feature_profiles
