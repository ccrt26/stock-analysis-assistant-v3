from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, ValidationInfo, field_validator, model_validator

from stock_analyzer.data.research_contracts import ResearchDatasetId


class SourceGrade(str, Enum):
    S = "S"
    A = "A"
    B = "B"


class KnowledgeEffect(str, Enum):
    HARD_BOUNDARY = "hard_boundary"
    ANALYSIS_EVIDENCE = "analysis_evidence"
    OBSERVATION_ONLY = "observation_only"
    METHOD_ONLY = "method_only"


class AnalysisModule(str, Enum):
    MARKET_ENVIRONMENT = "market_environment"
    SECTOR_THEME = "sector_theme"
    COMPANY_BUSINESS = "company_business"
    FUNDAMENTALS = "fundamentals"
    VALUATION = "valuation"
    PRICE_TRADING = "price_trading"
    EVENTS = "events"
    RISK = "risk"
    PORTFOLIO = "portfolio"
    TARGET_CONDITIONS = "target_conditions"


class OpportunityType(str, Enum):
    GENERAL = "general"
    INDUSTRY_TREND = "industry_trend"
    EARNINGS_RERATING = "earnings_rerating"
    CYCLE_INFLECTION = "cycle_inflection"
    COMPANY_EVENT = "company_event"
    TURNAROUND = "turnaround"


class KnowledgeTopic(str, Enum):
    TRADER_IDENTITY_BOUNDARY = "trader_identity_boundary"
    EXCHANGE_CONSTRAINTS = "exchange_constraints"
    BUSINESS_TRANSMISSION = "business_transmission"
    OFFICIAL_PUBLICATION_TIMING = "official_publication_timing"
    DELISTING_RISK = "delisting_risk"
    SHARE_REDUCTION = "share_reduction"
    BUYBACK_STAGE = "buyback_stage"
    RESTRUCTURING_STAGE = "restructuring_stage"
    MARKET_PRICE_PERSISTENCE = "market_price_persistence"
    SECTOR_PRICE_PERSISTENCE = "sector_price_persistence"
    VALUATION_METHOD = "valuation_method"
    EVENT_PRICE_REACTION = "event_price_reaction"
    EARNINGS_DRIFT = "earnings_drift"
    FINANCIAL_TURNAROUND = "financial_turnaround"
    CYCLE_SUPPLY_DEMAND = "cycle_supply_demand"
    MARKET_STATE_RELIABILITY = "market_state_reliability"
    RETURN_DISPERSION = "return_dispersion"
    LIQUIDITY_TRADING_ACTIVITY = "liquidity_trading_activity"
    PROFITABILITY_QUALITY = "profitability_quality"
    RISK_OVEREXTENSION = "risk_overextension"
    EARNINGS_DISCLOSURE_HIERARCHY = "earnings_disclosure_hierarchy"
    MARGIN_FINANCING = "margin_financing"
    PLEDGE_CONDITIONAL_RISK = "pledge_conditional_risk"
    DISCLOSED_HOLDER_TRADE = "disclosed_holder_trade"
    PORTFOLIO_RELATIONSHIP = "portfolio_relationship"


class KnowledgeUseStatus(str, Enum):
    CORRECT = "correct_execution"
    LIMITED = "limited_execution"
    INSUFFICIENT = "insufficient_execution"
    DATA_INSUFFICIENT_OR_NOT_APPLICABLE = "data_insufficient_or_not_applicable"


class CapabilityStatus(str, Enum):
    COMPLETE = "complete"
    LIMITED = "limited"
    BLOCKED = "blocked"
    NOT_APPLICABLE = "not_applicable"


class MigrationAction(str, Enum):
    RETAIN = "retain"
    UPDATE = "update"
    REVALIDATE = "revalidate"
    DEFER = "defer"
    RETIRE = "retire"


class SourceKind(str, Enum):
    OFFICIAL_RULE = "official_rule"
    OFFICIAL_DISCLOSURE = "official_disclosure"
    OFFICIAL_RESEARCH = "official_research"
    PEER_REVIEWED_PAPER = "peer_reviewed_paper"
    WORKING_PAPER = "working_paper"
    INDUSTRY_RESEARCH = "industry_research"


class ResearchDesign(str, Enum):
    EMPIRICAL = "empirical"
    THEORETICAL = "theoretical"
    METHODOLOGICAL = "methodological"


OFFICIAL_HOSTS = frozenset(
    {
        "www.csrc.gov.cn",
        "neris.csrc.gov.cn",
        "www.sse.com.cn",
        "www.szse.cn",
        "docs.static.szse.cn",
        "www.bse.cn",
        "www.gov.cn",
        "big5.www.gov.cn",
        "www.miit.gov.cn",
        "kjs.mof.gov.cn",
    }
)


class _FrozenGovernanceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)

    @field_validator("*", mode="before")
    @classmethod
    def _reject_blank_text_and_tuple_items(
        cls, value: Any, info: ValidationInfo
    ) -> Any:
        if isinstance(value, str):
            cleaned = value.strip()
            if not cleaned and info.field_name != "registry_hash":
                raise ValueError(f"{info.field_name} must not be blank")
            return cleaned
        if isinstance(value, (tuple, list)):
            for item in value:
                if isinstance(item, str) and not item.strip():
                    raise ValueError(f"{info.field_name} contains a blank item")
        return value


class SourceRecord(_FrozenGovernanceModel):
    source_id: str
    grade: SourceGrade
    kind: SourceKind
    research_design: ResearchDesign = ResearchDesign.EMPIRICAL
    title: str
    publisher: str
    authors: tuple[str, ...] = ()
    journal_or_series: str | None = None
    url: HttpUrl
    doi: str | None = None
    document_number: str | None = None
    publication_date: date
    effective_from: date | None = None
    effective_to: date | None = None
    last_verified_on: date
    jurisdiction: str
    market_scope: tuple[str, ...]
    sample_start: date | None = None
    sample_end: date | None = None
    method_summary: str
    limitations: tuple[str, ...]

    @model_validator(mode="after")
    def _validate_source_grade(self) -> SourceRecord:
        if self.grade is SourceGrade.S:
            if self.url.host not in OFFICIAL_HOSTS:
                raise ValueError("S source URL must use an approved official host")
            if self.kind is SourceKind.OFFICIAL_RULE and self.effective_from is None:
                raise ValueError("an S official rule requires effective_from")

        empirical_kinds = {
            SourceKind.PEER_REVIEWED_PAPER,
            SourceKind.WORKING_PAPER,
            SourceKind.INDUSTRY_RESEARCH,
        }
        if self.grade is SourceGrade.A and self.kind in empirical_kinds:
            if not self.authors:
                raise ValueError("an A paper requires authors")
            if not self.market_scope:
                raise ValueError("an A paper requires market metadata")
            if (
                self.research_design is ResearchDesign.EMPIRICAL
                and (self.sample_start is None or self.sample_end is None)
            ):
                raise ValueError("an A paper requires sample metadata")
            if self.doi is None and self.url is None:
                raise ValueError("an A paper requires a DOI or original publisher URL")

        if (
            self.effective_from is not None
            and self.effective_to is not None
            and self.effective_to < self.effective_from
        ):
            raise ValueError("effective_to cannot precede effective_from")
        if (
            self.sample_start is not None
            and self.sample_end is not None
            and self.sample_end < self.sample_start
        ):
            raise ValueError("sample_end cannot precede sample_start")
        return self


class DataRequirement(_FrozenGovernanceModel):
    kind: Literal["fact", "derived"]
    name: str
    required_fields: tuple[str, ...]
    minimum_rows: int = Field(default=1, ge=1)
    require_as_of: bool = True

    @model_validator(mode="after")
    def _validate_requirement(self) -> DataRequirement:
        if not self.required_fields:
            raise ValueError("required_fields must not be empty")
        if self.kind == "fact":
            try:
                ResearchDatasetId(self.name)
            except ValueError as exc:
                raise ValueError(
                    f"unknown governed fact dataset: {self.name}"
                ) from exc
        return self


class LocalValidation(_FrozenGovernanceModel):
    status: Literal["not_required", "required_before_threshold", "validated"]
    reason: str
    validation_reference: str | None = None

    @model_validator(mode="after")
    def _validate_reference(self) -> LocalValidation:
        if self.status == "validated" and self.validation_reference is None:
            raise ValueError("validated local validation requires validation_reference")
        return self


class _ApprovedHorizonModel(_FrozenGovernanceModel):
    @model_validator(mode="after")
    def _validate_approved_horizon(self) -> _ApprovedHorizonModel:
        horizon = (
            getattr(self, "horizon_min_sessions"),
            getattr(self, "horizon_center_sessions"),
            getattr(self, "horizon_max_sessions"),
        )
        if horizon != (10, 20, 30):
            raise ValueError("approved horizon must be exactly 10/20/30 sessions")
        return self


class KnowledgeEntry(_ApprovedHorizonModel):
    knowledge_id: str
    title: str
    primary_source_id: str
    supporting_source_ids: tuple[str, ...] = ()
    source_grade: SourceGrade
    version_status: Literal["current", "superseded", "historical_only"]
    supersedes: tuple[str, ...] = ()
    effective_from: date | None = None
    effective_to: date | None = None
    effect: KnowledgeEffect
    modules: tuple[AnalysisModule, ...]
    opportunity_types: tuple[OpportunityType, ...]
    topics: tuple[KnowledgeTopic, ...]
    horizon_min_sessions: int = 10
    horizon_center_sessions: int = 20
    horizon_max_sessions: int = 30
    claim_summary: str
    allowed_uses: tuple[str, ...]
    forbidden_uses: tuple[str, ...]
    prerequisites: tuple[str, ...]
    counter_evidence: tuple[str, ...]
    data_requirements: tuple[DataRequirement, ...]
    local_validation: LocalValidation

    @model_validator(mode="after")
    def _validate_entry_policy(self) -> KnowledgeEntry:
        if self.source_grade is SourceGrade.B and self.effect in {
            KnowledgeEffect.HARD_BOUNDARY,
            KnowledgeEffect.ANALYSIS_EVIDENCE,
        }:
            raise ValueError("a B source cannot create a hard boundary or analysis evidence")
        if (
            self.effect is KnowledgeEffect.ANALYSIS_EVIDENCE
            and self.local_validation.status == "required_before_threshold"
        ):
            raise ValueError(
                "empirical analysis evidence requires completed local validation"
            )
        if self.version_status == "current" and not self.data_requirements:
            raise ValueError("a current entry requires nonempty data_requirements")
        if not self.modules or not self.opportunity_types or not self.topics:
            raise ValueError("modules, opportunity_types and topics must not be empty")
        if (
            self.effective_from is not None
            and self.effective_to is not None
            and self.effective_to < self.effective_from
        ):
            raise ValueError("effective_to cannot precede effective_from")
        return self


class AnalysisContext(_ApprovedHorizonModel):
    analysis_date: date
    module: AnalysisModule
    opportunity_type: OpportunityType
    required_topics: tuple[KnowledgeTopic, ...]
    market: Literal["A股"] = "A股"
    board: str | None = None
    question: str
    horizon_min_sessions: int = 10
    horizon_center_sessions: int = 20
    horizon_max_sessions: int = 30

    @model_validator(mode="after")
    def _require_topics(self) -> AnalysisContext:
        if not self.required_topics:
            raise ValueError("required_topics must not be empty")
        return self


class LegacyMigrationRecord(_FrozenGovernanceModel):
    legacy_knowledge_id: str
    action: MigrationAction
    target_knowledge_ids: tuple[str, ...]
    source_verified: bool
    current_a_share_applicability: Literal["direct", "method_only", "unsupported"]
    data_gate: Literal["complete", "blocked", "not_applicable"]
    local_validation_required: bool
    reason: str


class KnowledgeRegistry(_FrozenGovernanceModel):
    schema_version: Literal["v3-knowledge-governance-v1"]
    generated_on: date
    sources: tuple[SourceRecord, ...]
    entries: tuple[KnowledgeEntry, ...]
    registry_hash: str = ""

    @model_validator(mode="after")
    def _validate_current_official_rule_ranges(self) -> KnowledgeRegistry:
        sources_by_id = {source.source_id: source for source in self.sources}
        for entry in self.entries:
            source = sources_by_id.get(entry.primary_source_id)
            if (
                entry.version_status == "current"
                and source is not None
                and source.kind is SourceKind.OFFICIAL_RULE
            ):
                if entry.effective_from is None or source.effective_from is None:
                    raise ValueError("a current official rule requires effective_from")
                if (
                    entry.effective_to is not None
                    and entry.effective_to < self.generated_on
                ) or (
                    source.effective_to is not None
                    and source.effective_to < self.generated_on
                ):
                    raise ValueError("a current official rule cannot have a past effective_to")
        return self


class LegacyMigrationRegistry(_FrozenGovernanceModel):
    schema_version: Literal["v3-legacy-migration-v1"]
    entries: tuple[LegacyMigrationRecord, ...]


class KnowledgeUseRecord(_FrozenGovernanceModel):
    knowledge_id: str
    source_grade: SourceGrade
    registry_hash: str
    analysis_date: date
    status: KnowledgeUseStatus
    status_reason: str
    selection_reason: str
    api_fact_refs: tuple[str, ...]
    local_observation_refs: tuple[str, ...]
    model_judgment: str
    user_expression: str
    limitations: tuple[str, ...] = ()
    missing_data: tuple[str, ...] = ()
    omitted_steps: tuple[str, ...] = ()
    conflicts_with: tuple[str, ...] = ()
    hard_boundary_triggered: bool = False

    @model_validator(mode="after")
    def _validate_execution_status(self) -> KnowledgeUseRecord:
        if self.status is KnowledgeUseStatus.CORRECT and (
            self.missing_data or self.omitted_steps
        ):
            raise ValueError(
                "correct_execution cannot contain missing_data or omitted_steps"
            )
        if self.status is KnowledgeUseStatus.LIMITED and not self.limitations:
            raise ValueError("limited_execution requires a concrete limitation")
        if self.status is KnowledgeUseStatus.INSUFFICIENT and not self.omitted_steps:
            raise ValueError("insufficient_execution requires an omitted required step")
        return self


__all__ = [
    "AnalysisContext",
    "AnalysisModule",
    "CapabilityStatus",
    "DataRequirement",
    "KnowledgeEffect",
    "KnowledgeEntry",
    "KnowledgeRegistry",
    "KnowledgeTopic",
    "KnowledgeUseRecord",
    "KnowledgeUseStatus",
    "LegacyMigrationRecord",
    "LegacyMigrationRegistry",
    "LocalValidation",
    "MigrationAction",
    "OFFICIAL_HOSTS",
    "OpportunityType",
    "SourceGrade",
    "SourceKind",
    "SourceRecord",
]
