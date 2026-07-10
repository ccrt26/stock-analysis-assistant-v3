from __future__ import annotations

import re
from datetime import date, datetime
from enum import Enum
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

RecoveryStatus = Literal["success", "failed", "skipped"]

_SENSITIVE_PAIR_RE = re.compile(
    r"""
    \b
    (?P<key>
        [a-z0-9_.-]*
        (?:
            token
            | secret
            | password
            | authorization
            | api[\s_.-]?key
        )
        [a-z0-9_.-]*
    )
    \b
    (?P<separator>\s*[:=]\s*)
    (?P<value>
        (?:Bearer\s+)?
        (?:
            "[^"]*"
            | '[^']*'
            | [^\s,;&]+
        )
    )
    """,
    flags=re.IGNORECASE | re.VERBOSE,
)
_BEARER_VALUE_RE = re.compile(
    r"""\bBearer\s+(?:"[^"]*"|'[^']*'|[^\s,;&]+)""",
    flags=re.IGNORECASE | re.VERBOSE,
)


def _redact_sensitive_text(value: str) -> str:
    def redact_pair(match: re.Match[str]) -> str:
        return f"{match.group('key')}{match.group('separator')}[redacted]"

    value = _SENSITIVE_PAIR_RE.sub(redact_pair, value)
    return _BEARER_VALUE_RE.sub("Bearer [redacted]", value)


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
    COMPANY_BUSINESS = "company_business"
    FUNDAMENTALS_VALUATION = "fundamentals_valuation"
    MARKET_BOARD = "market_board"
    TREND_VOLUME = "trend_volume"
    EVENTS_CATALYSTS = "events_catalysts"
    RISK_COUNTER = "risk_counter"


class EvidencePolarity(str, Enum):
    SUPPORT = "support"
    COUNTER = "counter"
    NEUTRAL = "neutral"


class DataRequirementLevel(str, Enum):
    REQUIRED = "required"
    ENHANCED = "enhanced"
    OBSERVATION = "observation"


class DataAvailability(str, Enum):
    AVAILABLE_PRIMARY = "available_primary"
    AVAILABLE_BACKUP = "available_backup"
    AVAILABLE_LOCAL_CACHE = "available_local_cache"
    UNAVAILABLE_AFTER_RECOVERY = "unavailable_after_recovery"


class ActionDecision(str, Enum):
    NO_PARTICIPATION = "暂不参与"
    CONTINUE_WATCHING = "继续观察"
    WAIT_FOR_CONFIRMATION = "等待确认"
    AVOID_CHASING = "避免追高"
    SMALL_EXPLORATORY = "小仓试探"
    INCREASE_ATTENTION = "提高关注"
    CONDITIONAL_ADD = "确认后考虑提高仓位"
    REDUCE_OR_AVOID = "风险上升，降低或避免新增"
    CONFIRM_REMOVAL = "建议确认是否移出重点"


class FocusSource(str, Enum):
    SYSTEM = "system"
    MANUAL = "manual"


class OperationalReportState(str, Enum):
    GENERATED = "generated"
    DATA_INSUFFICIENT = "data_insufficient"
    SKIPPED_NON_TRADING_DAY = "skipped_non_trading_day"


class DataRecoveryAttempt(BaseModel):
    source: Optional[str] = None
    family: Optional[str] = None
    source_name: Optional[str] = None
    status: Optional[RecoveryStatus] = None
    message: Optional[str] = None
    trade_date: Optional[date] = None
    attempted_at: Optional[datetime] = None
    succeeded: bool = False
    recovered_fields: List[str] = Field(default_factory=list)
    error: Optional[str] = None

    @field_validator("message", "error")
    @classmethod
    def _redact_sensitive_terms(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        return _redact_sensitive_text(value)

    @model_validator(mode="after")
    def _backfill_source_contract_fields(self) -> "DataRecoveryAttempt":
        if self.source is None and self.source_name is not None:
            self.source = self.source_name
        if self.source_name is None and self.source is not None:
            self.source_name = self.source
        if self.status is None:
            self.status = "success" if self.succeeded else "failed"
        if self.message is None and self.error is not None:
            self.message = self.error
        return self


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
    position_min_pct: float = Field(ge=0)
    position_max_pct: float = Field(ge=0)
    reasoning: List[str] = Field(min_length=1)
    required_confirmation: List[str] = Field(min_length=1)
    invalidation_conditions: List[str] = Field(min_length=1)
    risk_if_wrong: str = Field(min_length=1)
    staging_plan: List[str] = Field(min_length=1)
    holding_adjustment: Optional[str] = None

    @field_validator(
        "reasoning",
        "required_confirmation",
        "invalidation_conditions",
        "staging_plan",
    )
    @classmethod
    def _require_non_empty_items(cls, values: List[str]) -> List[str]:
        if any(not item.strip() for item in values):
            raise ValueError("must contain only non-empty items")
        return values

    @field_validator("risk_if_wrong")
    @classmethod
    def _require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must be non-empty")
        return value

    @model_validator(mode="after")
    def _position_range_is_ordered(self) -> "ActionRecommendation":
        if self.position_min_pct > self.position_max_pct:
            raise ValueError("position_min_pct must be less than or equal to position_max_pct")
        return self


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
    internal_score: float
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
    source: FocusSource
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
    is_trading_day: bool
    recommendation_state: OperationalReportState
    focus_state: OperationalReportState
    recommendation_count: int = Field(ge=0)
    focus_count: int = Field(ge=0)
    data_recovery_attempts: List[DataRecoveryAttempt] = Field(default_factory=list)
    blocking_missing_fields: List[str] = Field(default_factory=list)
    message: str = Field(min_length=1)

    @field_validator("message")
    @classmethod
    def _require_message(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must be non-empty")
        return value
