from __future__ import annotations

from datetime import date, datetime
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


class EvidenceModule(str, Enum):
    TREND_VOLUME = "趋势量价"
    MARKET_REGIME = "市场环境"
    INDUSTRY_POLICY = "行业政策"
    FUNDAMENTAL_QUALITY = "基本面质量"
    CATALYST_EVENT = "事件催化"
    RISK_VALUATION = "风险估值"


class EvidencePolarity(str, Enum):
    SUPPORT = "支持"
    COUNTER = "反证"
    NEUTRAL = "中性"


class DataRequirementLevel(str, Enum):
    REQUIRED = "必需"
    RECOMMENDED = "建议"
    OPTIONAL = "可选"


class DataAvailability(str, Enum):
    AVAILABLE_PRIMARY = "主源可用"
    AVAILABLE_BACKUP = "备源可用"
    AVAILABLE_CACHE = "本地缓存可用"
    MISSING = "缺失"
    PARTIAL = "部分可用"


class ActionDecision(str, Enum):
    FOCUS_ENTRY = "进入重点观察"
    WAIT_FOR_CONFIRMATION = "等待确认"
    HOLD = "持有"
    ADD = "加仓"
    REDUCE = "减仓"
    EXIT = "退出"
    AVOID = "回避"
    INSUFFICIENT_DATA = "数据不足，不形成结论"


class DataRecoveryAttempt(BaseModel):
    source: str
    attempted_at: Optional[datetime] = None
    succeeded: bool = False
    recovered_fields: List[str] = Field(default_factory=list)
    error: Optional[str] = None


class DataRequirementStatus(BaseModel):
    family: str
    level: DataRequirementLevel
    availability: DataAvailability
    primary_source: Optional[str] = None
    backup_source: Optional[str] = None
    local_cache_path: Optional[str] = None
    missing_fields: List[str] = Field(default_factory=list)
    recovery_attempts: List[DataRecoveryAttempt] = Field(default_factory=list)
    blocks_complete_analysis: bool = False


class EvidenceAtom(BaseModel):
    id: str
    module: EvidenceModule
    polarity: EvidencePolarity
    headline: str
    detail: str
    source_grade: str
    source_name: str
    source_url: Optional[str] = None
    data_fields: List[str] = Field(default_factory=list)
    knowledge_rule_ids: List[str] = Field(default_factory=list)
    strength: float
    as_of_date: date


class ModuleEvidence(BaseModel):
    module: EvidenceModule
    summary: str
    support: List[EvidenceAtom] = Field(default_factory=list)
    counter: List[EvidenceAtom] = Field(default_factory=list)
    data_requirements: List[DataRequirementStatus] = Field(default_factory=list)
    conclusion: str


class ActionRecommendation(BaseModel):
    decision: ActionDecision
    position_min_pct: float
    position_max_pct: float
    reasoning: List[str] = Field(default_factory=list)
    required_confirmation: List[str] = Field(default_factory=list)
    invalidation_conditions: List[str] = Field(default_factory=list)
    risk_if_wrong: str
    staging_plan: List[str] = Field(default_factory=list)
    holding_adjustment: Optional[str] = None


class StrategyEvidenceSnapshot(BaseModel):
    evidence_id: str
    trade_date: date
    ts_code: str
    name: str
    modules: List[ModuleEvidence] = Field(default_factory=list)
    action: ActionRecommendation
    thesis: str
    expected_upside_pct: Optional[float] = None
    expected_downside_pct: Optional[float] = None
    risk_reward: Optional[float] = None
    focus_entry_progress: Optional[str] = None
    display_rank_bucket: str
    internal_score: Optional[float] = None
    data_insufficient: bool = False
    data_insufficient_reason: Optional[str] = None
    source_versions: Dict[str, str] = Field(default_factory=dict)


class RecommendationCard(BaseModel):
    trade_date: date
    ts_code: str
    name: str
    display_rank_bucket: str
    action: str
    what_happened: str
    why_it_may_have_happened: str
    what_it_may_mean: str
    main_risk: str
    focus_entry_progress: Optional[str] = None
    needed_before_focus_entry: List[str] = Field(default_factory=list)
    evidence_id: str


class FocusEntryThesis(BaseModel):
    evidence_id: str
    trade_date: date
    ts_code: str
    name: str
    thesis: str
    action: ActionRecommendation
    expected_upside_pct: Optional[float] = None
    expected_downside_pct: Optional[float] = None
    risk_reward: Optional[float] = None
    required_confirmation: List[str] = Field(default_factory=list)
    invalidation_conditions: List[str] = Field(default_factory=list)
    supporting_evidence_ids: List[str] = Field(default_factory=list)


class FocusDailyUpdate(BaseModel):
    trade_date: date
    ts_code: str
    name: str
    evidence_id: str
    thesis: str
    action: ActionRecommendation
    focus_entry_progress: str
    new_support: List[EvidenceAtom] = Field(default_factory=list)
    new_counter: List[EvidenceAtom] = Field(default_factory=list)
    required_confirmation: List[str] = Field(default_factory=list)
    invalidation_conditions: List[str] = Field(default_factory=list)
    data_insufficient: bool = False
    data_insufficient_reason: Optional[str] = None


class ManualHolding(BaseModel):
    ts_code: str
    name: str
    position_pct: float
    cost_price: Optional[float] = None
    quantity: Optional[float] = None
    entry_date: Optional[date] = None
    thesis_id: Optional[str] = None
    notes: Optional[str] = None


class ManualActionRecord(BaseModel):
    action_date: date
    ts_code: str
    name: str
    decision: ActionDecision
    position_pct: float
    reason: str
    evidence_id: Optional[str] = None
    notes: Optional[str] = None


class OperationalDailyStatus(BaseModel):
    trade_date: date
    data_requirements: List[DataRequirementStatus] = Field(default_factory=list)
    recovery_attempts: List[DataRecoveryAttempt] = Field(default_factory=list)
    blocked_families: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    ready_for_analysis: bool
