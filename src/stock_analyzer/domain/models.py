from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class ActionLabel(str, Enum):
    ENTER_OBSERVATION = "进入观察"
    CONTINUE_OBSERVATION = "继续观察"
    HIGH_RISK_OBSERVATION = "高风险观察"
    DOWNGRADE_OBSERVATION = "降级观察"
    EXIT_OBSERVATION = "剔除观察"
    INSUFFICIENT_DATA = "数据不足，不形成结论"


class StockSnapshot(BaseModel):
    trade_date: date
    ts_code: str
    name: str
    is_st: bool = False
    is_suspended: bool = False
    has_delisting_risk: bool = False
    listing_days: int
    turnover_rate: Optional[float] = None
    amount: Optional[float] = None
    official_risk_events: List[str] = Field(default_factory=list)

    @property
    def is_hard_excluded(self) -> bool:
        low_liquidity = (self.turnover_rate is not None and self.turnover_rate < 0.2) or (
            self.amount is not None and self.amount < 50_000_000
        )
        return any(
            [
                self.is_st,
                self.is_suspended,
                self.has_delisting_risk,
                self.listing_days < 120,
                low_liquidity,
                bool(self.official_risk_events),
            ]
        )


class FeatureSnapshot(BaseModel):
    trade_date: date
    ts_code: str
    trend_20d: float
    trend_60d: float
    relative_strength: float
    volatility_20d: float
    liquidity_score: float
    quality_score: float
    market_regime: str
    industry: Optional[str] = None
    data_quality: str = "ok"


class Recommendation(BaseModel):
    trade_date: date
    ts_code: str
    name: str
    action: ActionLabel
    score: float
    reasons: List[str]
    risks: List[str]
    evidence_id: Optional[str] = None


class FocusState(BaseModel):
    trade_date: date
    ts_code: str
    state: ActionLabel
    entry_date: Optional[date] = None
    entry_reason: Optional[str] = None
    invalidation_conditions: List[str] = Field(default_factory=list)
    exit_reason: Optional[str] = None


class EvidencePackage(BaseModel):
    evidence_id: str
    trade_date: date
    ts_code: str
    thesis: str
    support: List[str]
    counter_evidence: List[str]
    matched_rules: List[str]
    confidence_level: str
    expected_confirmation_path: List[str]
    invalidation_conditions: List[str]
    source_versions: Dict[str, str]


class EvaluationTask(BaseModel):
    trade_date: date
    ts_code: str
    evidence_id: str
    checkpoint_days: int
    due_date: date
    evaluation_layer: str
