"""Tamper-evident structured judgment for the isolated V3 backtest."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import subprocess
import tempfile
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Literal, Self
from weakref import WeakKeyDictionary

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, field_validator, model_validator

from stock_analyzer.evaluation.v3_backtest.contracts import (
    CandidateLayer,
    ComparisonStage,
    ContextEffect,
    DiscoveryRoute,
    EvidenceCardStatus as JudgmentCardStatus,
    OpportunityType,
    PriceRole,
    ProjectDayCheckpoint,
    ValidationDisposition,
)
from stock_analyzer.evaluation.v3_backtest.evidence import (
    CandidateEvidencePacket,
    EvidenceAvailability,
    EvidenceCardStatus,
    EvidenceInputStatus,
    EvidenceSectionName,
    KnowledgeRoutingStatus,
    VerifiedEvidenceSnapshotBundle,
    build_candidate_packet,
    require_verified_evidence_snapshot_bundle,
)
from stock_analyzer.evaluation.v3_backtest.routes import VerifiedRouteScanBatch, require_verified_route_scan_batch
from stock_analyzer.knowledge.governance_models import KnowledgeEffect
from stock_analyzer.knowledge.registry import load_knowledge_registry


_BINARY = "/Applications/ChatGPT.app/Contents/Resources/codex"
_CLI_VERSION = "codex-cli 0.144.0-alpha.4"
_MODEL = "gpt-5.6-sol"
_REASONING = "high"
_PROMPT_PATH = Path(__file__).with_name("prompts") / "v3_backtest_judge_v1.txt"
_REGISTRY_PATH = Path(__file__).resolve().parents[2] / "knowledge" / "research_registry.yaml"
_SMOKE_DATES = (date(2025, 10, 30), date(2026, 1, 8), date(2026, 6, 3))
_COMMAND_TEMPLATE = (
    "exec", "--ephemeral", "--ignore-user-config", "--skip-git-repo-check",
    "--sandbox", "read-only", "--model", _MODEL, "-c",
    f'model_reasoning_effort="{_REASONING}"', "--disable", "fast_mode",
    "--output-schema", "<schema>", "--output-last-message", "<output>", "-",
)
_FORBIDDEN_INPUT_FIELD_PARTS = (
    "outcome", "future_price", "future_return", "future_high", "future_low",
    "future_close", "known_winner", "target_touched", "user_expression",
)
_FORBIDDEN_INPUT_TEXT = ("后来", "known winner", "known_winner")
_FORBIDDEN_LANGUAGE = (
    r"\bscore(?:d|s|ing)?\b", r"\brating\b", r"\bpoints?\b",
    r"\bprobabilit(?:y|ies)\b", r"\bodds?\b", r"\bconfidence\b",
    r"\bwin\s*rate\b", r"\binstitutional(?:\s+(?:buying|selling|flow|money))?\b",
    r"\bmain\s*force\b", r"\bsmart\s*money\b", r"\baccumulation\b",
    r"\bfund(?:s)?\s+(?:buying|selling|flow|inflow|outflow)\b",
    r"\bdistribution\b", r"主力", r"庄家", r"游资", r"吸筹", r"出货",
    r"机构", r"大资金", r"资金(?:净流入|净流出|介入|流入|流出|买入|卖出)",
    r"\b(?:twofold|threefold|double|triple)\b",
    r"\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|hundred)\s+(?:percent|percentage\s+points?|fold|times?)\b",
    r"概率", r"几率", r"胜率", r"胜算", r"置信度", r"评分", r"评级", r"打分", r"分值",
)
_CHINESE_QUANTITY = re.compile(
    r"(?:百分之|千分之)?[零〇一二两三四五六七八九十百千万亿]+(?:成|倍|比|分之|个?百分点|个点)"
)
_ASCII_NUMBER = re.compile(r"(?<![A-Za-z_])[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")
_RATIO = re.compile(r"\d+(?:\.\d+)?\s*[:：比]\s*\d+(?:\.\d+)?")
_EMPTY_COUNTEREVIDENCE_TEXT = "no counterevidence was available as of the formation cutoff"
_EMPTY_UNKNOWNS_TEXT = "no unknown-section evidence was available as of the formation cutoff"

_CARD_REQUIREMENT_DATASETS: dict[str | tuple[OpportunityType, str], tuple[str, ...]] = {
    "complete related hotspot input": ("sector_hotspot",),
    "effective company membership": ("industry_member", "theme_member"),
    "business contribution numerator and company denominator inputs": ("main_business", "income_statement"),
    "two formation-time industry demand or adoption input periods": ("industry_daily",),
    "formal disclosure hierarchy": ("earnings_forecast", "earnings_express", "income_statement"),
    "aligned profit inputs": ("income_statement",),
    "aligned cash inputs": ("income_statement", "cash_flow"),
    "own-history and peer valuation inputs": ("daily_basic",),
    (OpportunityType.EARNINGS_REVALUATION, "event-aligned relative price response"): ("earnings_forecast", "earnings_express", "event_price_response"),
    "two-period industry supply demand price and inventory inputs": ("industry_daily",),
    "company sensitivity inputs": ("main_business", "income_statement"),
    "two-period profit inputs": ("income_statement",),
    "two-period cash inputs": ("cash_flow",),
    "auditable event body amount subject stage conditions and failure inputs": ("announcement",),
    "business transmission inputs": ("company_profile", "main_business"),
    (OpportunityType.COMPANY_EVENT_REVALUATION, "event-aligned relative price response"): ("announcement", "event_price_response"),
    "raw distress and financing-risk inputs": ("security_master", "repurchase", "holder_trade", "share_float", "pledge"),
    "two aligned multi-statement periods": ("income_statement", "balance_sheet", "cash_flow", "financial_indicator"),
    "event-aligned relative price response input": ("repurchase", "holder_trade", "share_float", "pledge", "event_price_response"),
}

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


@dataclass(frozen=True)
class JudgmentCacheKey:
    """Complete context identity for a reusable structured judgment."""

    origin: date
    cutoff: str
    fact_manifest_hash: str
    formula_version: str
    knowledge_version: str
    prompt_version: str
    project_state_hash: str
    checkpoint: ProjectDayCheckpoint
    comparator_cohort_hash: str
    portfolio_exposure_hash: str
    previous_judgment_hash: str

    def __post_init__(self) -> None:
        if type(self.checkpoint) is not ProjectDayCheckpoint:
            raise TypeError("judgment cache checkpoint must use ProjectDayCheckpoint")
        for name, value in asdict(self).items():
            if name in {"origin", "checkpoint"}:
                continue
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"judgment cache key {name} must be non-empty")

    @property
    def cache_hash(self) -> str:
        return _stable_hash(asdict(self))

    @property
    def force_rejudgment(self) -> bool:
        return self.checkpoint is not ProjectDayCheckpoint.ORDINARY

    def is_reusable_with(self, other: "JudgmentCacheKey") -> bool:
        return self == other and not other.force_rejudgment


def lookup_judgment_cache(
    cache: Mapping[JudgmentCacheKey, Any], key: JudgmentCacheKey
) -> Any | None:
    """The only supported cache lookup; fixed project days always require a new judgment."""

    if key.force_rejudgment:
        raise JudgeError("checkpoint requires fresh rejudgment; cache reuse is forbidden")
    return cache.get(key)


class JudgeError(RuntimeError):
    pass


class JudgeInstabilityError(JudgeError):
    def __init__(self, audit: "JudgeConsistencyAudit") -> None:
        super().__init__("structured judge is unstable; stop the backtest")
        self.audit = audit


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)


class RequirementDispositionType(StrEnum):
    SUPPORTIVE = "supportive"
    COUNTEREVIDENCE = "counterevidence"
    UNKNOWN = "unknown"


class ConsideredDispositionType(StrEnum):
    PRESENT = "present"
    NONE_SUPPORTED = "none_supported_as_of_cutoff"
    UNKNOWN = "unknown"


class KnowledgeApplicationField(StrEnum):
    WHY_NOW = "why_now"
    DECISIVE_ADVANTAGES = "decisive_advantages"
    TARGET_CONDITIONS = "target_conditions"
    COUNTEREVIDENCE = "counterevidence"
    INVALIDATION = "invalidation"
    METHOD = "method"


class KnowledgeNonUseReason(StrEnum):
    NOT_DECISIVE = "not_decisive_for_this_judgment"
    CONFLICTED = "conflicted_by_counterevidence"
    METHOD_NOT_NEEDED = "method_not_needed"


class ComparisonRole(StrEnum):
    SAME_OPPORTUNITY_PEER = "same_opportunity_peer"
    NO_SAME_OPPORTUNITY_PEER = "no_same_opportunity_peer"


class JudgmentKind(StrEnum):
    MODEL_JUDGMENT = "model_judgment"


class CompanyEvidenceBar(StrEnum):
    STANDARD = "standard"
    RAISED = "raised"


class InvalidationCheck(StrEnum):
    NORMAL = "normal"
    ACCELERATED = "accelerated"


class CausalChainState(StrEnum):
    SUPPORTED = "supported"
    NEUTRAL = "neutral"
    OPPOSED = "opposed"


class CitedJudgmentText(_FrozenModel):
    text: NonEmptyStr
    evidence_ids: tuple[NonEmptyStr, ...] = ()

    @field_validator("evidence_ids")
    @classmethod
    def unique(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("evidence ids must be unique")
        return value


class CitedContextEffect(_FrozenModel):
    effect: ContextEffect
    source_section: EvidenceSectionName
    section_availability: EvidenceAvailability
    source_section_hash: Sha256
    judgment: CitedJudgmentText
    consequence_evidence_ids: tuple[NonEmptyStr, ...] = ()
    company_evidence_bar: CompanyEvidenceBar
    company_evidence_bar_satisfied: bool
    focus_eligible: bool
    invalidation_check: InvalidationCheck
    causal_chain: CausalChainState

    @model_validator(mode="after")
    def enforce_structured_consequence(self) -> Self:
        expected = {
            ContextEffect.SUPPORTS_CURRENT_OPPORTUNITY: (
                CompanyEvidenceBar.STANDARD, True, True,
                InvalidationCheck.NORMAL, CausalChainState.SUPPORTED,
            ),
            ContextEffect.LIMITS_FOCUS: (
                CompanyEvidenceBar.STANDARD, True, False,
                InvalidationCheck.NORMAL, CausalChainState.NEUTRAL,
            ),
            ContextEffect.ACCELERATES_INVALIDATION_CHECK: (
                CompanyEvidenceBar.STANDARD, True, True,
                InvalidationCheck.ACCELERATED, CausalChainState.NEUTRAL,
            ),
            ContextEffect.NOT_APPLICABLE: (
                CompanyEvidenceBar.STANDARD, True, True,
                InvalidationCheck.NORMAL, CausalChainState.NEUTRAL,
            ),
            ContextEffect.OPPOSES_CAUSAL_CHAIN: (
                CompanyEvidenceBar.STANDARD, True, False,
                InvalidationCheck.ACCELERATED, CausalChainState.OPPOSED,
            ),
        }
        actual = (
            self.company_evidence_bar,
            self.company_evidence_bar_satisfied,
            self.focus_eligible,
            self.invalidation_check,
            self.causal_chain,
        )
        if self.effect is ContextEffect.RAISES_COMPANY_EVIDENCE_BAR:
            if (
                self.company_evidence_bar is not CompanyEvidenceBar.RAISED
                or self.focus_eligible is not self.company_evidence_bar_satisfied
                or self.invalidation_check is not InvalidationCheck.NORMAL
                or self.causal_chain is not CausalChainState.NEUTRAL
            ):
                raise ValueError("raised evidence-bar effect has inconsistent consequences")
        elif actual != expected[self.effect]:
            raise ValueError("context effect has inconsistent structured consequences")
        if self.effect is not ContextEffect.NOT_APPLICABLE and not self.consequence_evidence_ids:
            raise ValueError("context consequence requires cited evidence")
        if self.section_availability is EvidenceAvailability.EVIDENCE_READY_FOR_JUDGMENT:
            if not self.judgment.evidence_ids:
                raise ValueError("available context section requires cited evidence")
        elif (
            self.effect is not ContextEffect.NOT_APPLICABLE
            or self.judgment.evidence_ids
            or self.consequence_evidence_ids
        ):
            raise ValueError("unavailable context must be not-applicable without directional evidence")
        return self


class CitedPriceRole(_FrozenModel):
    role: PriceRole
    source_section: EvidenceSectionName
    section_availability: EvidenceAvailability
    source_section_hash: Sha256
    judgment: CitedJudgmentText

    @model_validator(mode="after")
    def require_evidence(self) -> Self:
        if self.source_section is not EvidenceSectionName.PRICE_VOLUME_LIQUIDITY:
            raise ValueError("price role must use the dedicated price section")
        if (
            self.section_availability is EvidenceAvailability.EVIDENCE_READY_FOR_JUDGMENT
            and not self.judgment.evidence_ids
        ):
            raise ValueError("price role requires evidence")
        if self.section_availability is EvidenceAvailability.NOT_AVAILABLE_AS_OF and (
            self.role is not PriceRole.OTHER_TRADABLE or self.judgment.evidence_ids
        ):
            raise ValueError("unavailable price section permits only an uncited other-tradable role")
        return self


class CitedValidationState(_FrozenModel):
    disposition: ValidationDisposition
    next_check: ProjectDayCheckpoint
    judgment: CitedJudgmentText

    @model_validator(mode="after")
    def require_evidence(self) -> Self:
        if not self.judgment.evidence_ids:
            raise ValueError("next validation state requires evidence")
        return self


class SelectionPropositionJudgment(_FrozenModel):
    primary_opportunity: OpportunityType
    why_now: CitedJudgmentText
    next_validation: CitedJudgmentText
    post_fact_price_response: CitedJudgmentText
    price_confirmation: CitedJudgmentText
    target_conditions: CitedJudgmentText
    invalidation_condition: CitedJudgmentText


class RequirementDisposition(_FrozenModel):
    requirement: NonEmptyStr
    disposition: RequirementDispositionType
    judgment: CitedJudgmentText


class ConsideredEvidence(_FrozenModel):
    disposition: ConsideredDispositionType
    source_section: EvidenceSectionName
    judgment: CitedJudgmentText


class DecisiveEdge(_FrozenModel):
    winner_security_id: NonEmptyStr
    dominated_security_id: NonEmptyStr
    stage: ComparisonStage
    judgment: CitedJudgmentText
    reversal_fact: CitedJudgmentText

    @model_validator(mode="after")
    def require_distinct_cited_endpoints(self) -> Self:
        if self.winner_security_id == self.dominated_security_id:
            raise ValueError("comparison edge endpoints must differ")
        if not self.judgment.evidence_ids or not self.reversal_fact.evidence_ids:
            raise ValueError("decisive edge judgment and reversal fact require evidence")
        return self


class DecisiveComparison(_FrozenModel):
    comparator_security_ids: tuple[NonEmptyStr, ...]
    comparison_role: ComparisonRole
    judgment: CitedJudgmentText
    reversal_fact: CitedJudgmentText

    @model_validator(mode="after")
    def enforce_frozen_comparison_contract(self) -> Self:
        if len(self.comparator_security_ids) != len(set(self.comparator_security_ids)):
            raise ValueError("comparison cohort identities must be unique")
        if not self.judgment.evidence_ids or not self.reversal_fact.evidence_ids:
            raise ValueError("decisive comparison and reversal fact require evidence")
        return self


class HotspotCohortIdentity(_FrozenModel):
    group_type: Literal["industry", "theme"]
    group_code: NonEmptyStr


class ComparisonCohortReceipt(_FrozenModel):
    cohort_id: NonEmptyStr
    security_ids: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]
    hotspot_identity: HotspotCohortIdentity | None = None
    decisive_edges: tuple[DecisiveEdge, ...] = ()
    indistinguishable_groups: tuple[tuple[NonEmptyStr, ...], ...] = ()
    judgment: CitedJudgmentText
    reversal_fact: CitedJudgmentText
    completed: Literal[True]

    @model_validator(mode="after")
    def require_complete_acyclic_pair_outcomes(self) -> Self:
        members = set(self.security_ids)
        if len(members) != len(self.security_ids):
            raise ValueError("comparison cohort identities must be unique")
        if not self.judgment.evidence_ids or not self.reversal_fact.evidence_ids:
            raise ValueError("comparison cohort judgment and reversal require evidence")
        pairs: dict[frozenset[str], str] = {}
        adjacency = {security_id: set() for security_id in members}
        for edge in self.decisive_edges:
            endpoints = frozenset((edge.winner_security_id, edge.dominated_security_id))
            if not endpoints.issubset(members):
                raise ValueError("dominance edge lies outside its comparison cohort")
            if endpoints in pairs:
                raise ValueError("contradictory or duplicate dominance pair outcome")
            pairs[endpoints] = "edge"
            adjacency[edge.winner_security_id].add(edge.dominated_security_id)
        grouped: set[str] = set()
        for group in self.indistinguishable_groups:
            group_members = set(group)
            if len(group) < 2 or len(group_members) != len(group):
                raise ValueError("indistinguishable group requires unique peers")
            if not group_members.issubset(members) or grouped.intersection(group_members):
                raise ValueError("indistinguishable groups must be disjoint and in-cohort")
            grouped.update(group_members)
            ordered = tuple(group)
            for index, left in enumerate(ordered):
                for right in ordered[index + 1:]:
                    pair = frozenset((left, right))
                    if pair in pairs:
                        raise ValueError("comparison pair cannot be both tied and dominated")
                    pairs[pair] = "tie"
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node: str) -> None:
            if node in visiting:
                raise ValueError("dominance graph contains a cycle")
            if node in visited:
                return
            visiting.add(node)
            for child in adjacency[node]:
                visit(child)
            visiting.remove(node)
            visited.add(node)

        for member in members:
            visit(member)
        return self


class CrossOpportunityAssessment(_FrozenModel):
    security_id: NonEmptyStr
    current_action_eligible: bool
    independent_role_supported: bool
    independent_role: CitedJudgmentText
    reversal_fact: CitedJudgmentText

    @model_validator(mode="after")
    def require_cited_independent_role(self) -> Self:
        if not self.independent_role.evidence_ids or not self.reversal_fact.evidence_ids:
            raise ValueError("cross-opportunity role and reversal require evidence")
        if self.current_action_eligible and not self.independent_role_supported:
            raise ValueError("action eligibility requires a cited independent role")
        return self


class ExposureRelationship(StrEnum):
    SHARED_RISK = "shared_risk"
    INDEPENDENT = "independent"


class ExposurePairReceipt(_FrozenModel):
    left_security_id: NonEmptyStr
    right_security_id: NonEmptyStr
    relationship: ExposureRelationship
    capacity_compatible: bool
    judgment: CitedJudgmentText
    reversal_fact: CitedJudgmentText

    @model_validator(mode="after")
    def require_distinct_cited_pair(self) -> Self:
        if self.left_security_id == self.right_security_id:
            raise ValueError("exposure pair endpoints must differ")
        if not self.judgment.evidence_ids or not self.reversal_fact.evidence_ids:
            raise ValueError("exposure pair judgment and reversal require evidence")
        if self.relationship is ExposureRelationship.INDEPENDENT and not self.capacity_compatible:
            raise ValueError("an independent exposure pair must be capacity compatible")
        return self


class ComparisonStageReceipt(_FrozenModel):
    stage: ComparisonStage
    eligible_security_ids: tuple[NonEmptyStr, ...]
    cohorts: tuple[ComparisonCohortReceipt, ...]
    cross_opportunity_assessments: tuple[CrossOpportunityAssessment, ...] = ()
    exposure_pair_receipts: tuple[ExposurePairReceipt, ...] = ()

    @model_validator(mode="after")
    def require_exact_eligible_partition(self) -> Self:
        eligible = set(self.eligible_security_ids)
        if len(eligible) != len(self.eligible_security_ids):
            raise ValueError("stage eligibility identities must be unique")
        cohort_ids = tuple(item.cohort_id for item in self.cohorts)
        if len(cohort_ids) != len(set(cohort_ids)):
            raise ValueError("comparison cohort receipt ids must be unique")
        flattened = tuple(
            security_id for cohort in self.cohorts for security_id in cohort.security_ids
        )
        if self.stage is ComparisonStage.SAME_HOTSPOT_OPPORTUNITY_ROLE:
            if set(flattened) != eligible:
                raise ValueError("stage-one hotspot cohorts must cover every eligible candidate")
            if any(
                cohort.hotspot_identity is None and len(cohort.security_ids) != 1
                for cohort in self.cohorts
            ):
                raise ValueError("only a no-hotspot singleton may omit stage-one hotspot identity")
        elif len(flattened) != len(set(flattened)) or set(flattened) != eligible:
            raise ValueError("comparison cohorts must exactly partition stage eligibility")
        if self.stage is not ComparisonStage.SAME_HOTSPOT_OPPORTUNITY_ROLE and any(
            cohort.hotspot_identity is not None for cohort in self.cohorts
        ):
            raise ValueError("hotspot cohort identity belongs only to stage one")
        if any(edge.stage is not self.stage for cohort in self.cohorts for edge in cohort.decisive_edges):
            raise ValueError("dominance edge stage differs from its receipt stage")
        assessment_ids = tuple(
            item.security_id for item in self.cross_opportunity_assessments
        )
        if self.stage is ComparisonStage.CROSS_OPPORTUNITY:
            if len(assessment_ids) != len(set(assessment_ids)) or set(assessment_ids) != eligible:
                raise ValueError("cross-opportunity stage must assess every eligible candidate")
            exposure_pairs = tuple(
                frozenset((item.left_security_id, item.right_security_id))
                for item in self.exposure_pair_receipts
            )
            expected_pairs = {
                frozenset((left, right))
                for index, left in enumerate(self.eligible_security_ids)
                for right in self.eligible_security_ids[index + 1:]
            }
            if (
                len(exposure_pairs) != len(set(exposure_pairs))
                or set(exposure_pairs) != expected_pairs
            ):
                raise ValueError("stage-three exposure disposition must cover every eligible pair")
        elif (
            self.cross_opportunity_assessments
            or self.exposure_pair_receipts
        ):
            raise ValueError("cross-opportunity role/risk receipts belong only to stage three")
        exposure_by_pair = {
            frozenset((item.left_security_id, item.right_security_id)): item
            for item in self.exposure_pair_receipts
        }
        for cohort in self.cohorts:
            expected_cohort_pairs = {
                frozenset((left, right))
                for index, left in enumerate(cohort.security_ids)
                for right in cohort.security_ids[index + 1:]
            }
            decided_pairs = {
                frozenset((edge.winner_security_id, edge.dominated_security_id))
                for edge in cohort.decisive_edges
            }
            decided_pairs.update(
                frozenset((left, right))
                for group in cohort.indistinguishable_groups
                for index, left in enumerate(group)
                for right in group[index + 1:]
            )
            unresolved = expected_cohort_pairs.difference(decided_pairs)
            if self.stage is not ComparisonStage.CROSS_OPPORTUNITY and unresolved:
                raise ValueError("comparison cohort is incomplete; every pair needs one outcome")
            if self.stage is ComparisonStage.CROSS_OPPORTUNITY and any(
                pair not in exposure_by_pair
                or not exposure_by_pair[pair].capacity_compatible
                for pair in unresolved
            ):
                raise ValueError("cross-stage unresolved pairs require capacity-compatible exposure independence")
        return self


class CapacityTieAbstention(_FrozenModel):
    source_stage: ComparisonStage
    security_ids: Annotated[tuple[NonEmptyStr, ...], Field(min_length=2)]
    judgment: CitedJudgmentText
    reversal_fact: CitedJudgmentText

    @model_validator(mode="after")
    def require_unique_cited_group(self) -> Self:
        if len(self.security_ids) != len(set(self.security_ids)):
            raise ValueError("capacity tie group identities must be unique")
        if not self.judgment.evidence_ids or not self.reversal_fact.evidence_ids:
            raise ValueError("capacity tie judgment and reversal require evidence")
        return self


class KnowledgeUseReceipt(_FrozenModel):
    knowledge_id: NonEmptyStr
    entry_content_hash: Sha256
    effect: KnowledgeEffect
    prepared_purpose: NonEmptyStr
    allowed_use_hash: Sha256
    selected_allowed_use: NonEmptyStr
    applied_to_fields: Annotated[tuple[KnowledgeApplicationField, ...], Field(min_length=1)]
    satisfied_prerequisites: tuple[NonEmptyStr, ...]
    considered_counterevidence: tuple[NonEmptyStr, ...]
    use_summary: CitedJudgmentText


class KnowledgeNonUseReceipt(_FrozenModel):
    knowledge_id: NonEmptyStr
    entry_content_hash: Sha256
    effect: KnowledgeEffect
    reason: KnowledgeNonUseReason
    evidence_ids: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]


class PreparedKnowledgeInput(_FrozenModel):
    knowledge_id: NonEmptyStr
    title: NonEmptyStr
    effect: KnowledgeEffect
    claim_summary: NonEmptyStr
    prepared_purpose: NonEmptyStr
    allowed_use_hash: Sha256
    selected_allowed_use: NonEmptyStr
    forbidden_uses: tuple[NonEmptyStr, ...]
    prerequisites: tuple[NonEmptyStr, ...]
    counter_evidence: tuple[NonEmptyStr, ...]
    entry_content_hash: Sha256
    evidence_ids: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]


class CoverageCauseReceipt(_FrozenModel):
    dataset: NonEmptyStr
    status: EvidenceInputStatus
    coverage_hash: Sha256


class RequirementGapSourceReceipt(_FrozenModel):
    opportunity: OpportunityType
    requirement: NonEmptyStr
    governed_datasets: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]
    coverage_causes: Annotated[tuple[CoverageCauseReceipt, ...], Field(min_length=1)]
    mapping_hash: Sha256

    @model_validator(mode="after")
    def validate_gap_mapping(self) -> Self:
        if tuple(item.dataset for item in self.coverage_causes) != self.governed_datasets:
            raise ValueError("requirement gap causes must cover every governed dataset")
        if self.mapping_hash != _stable_hash(
            {
                "opportunity": self.opportunity,
                "requirement": self.requirement,
                "datasets": self.governed_datasets,
            }
        ):
            raise ValueError("requirement gap mapping hash differs")
        return self


class CardStatusSourceReceipt(_FrozenModel):
    opportunity: OpportunityType
    status: JudgmentCardStatus
    upstream_status: EvidenceCardStatus
    missing_requirements: tuple[NonEmptyStr, ...] = ()
    coverage_statuses: tuple[EvidenceInputStatus, ...] = ()
    requirement_gap_sources: tuple[RequirementGapSourceReceipt, ...] = ()
    source_card_hash: Sha256

    @model_validator(mode="after")
    def bind_status_to_upstream_source(self) -> Self:
        if self.status is JudgmentCardStatus.READY:
            if (
                self.upstream_status is not EvidenceCardStatus.EVIDENCE_READY_FOR_JUDGMENT
                or self.missing_requirements
                or self.coverage_statuses
                or self.requirement_gap_sources
            ):
                raise ValueError("ready card status source differs from upstream card")
        elif (
            self.upstream_status is not EvidenceCardStatus.INCOMPLETE
            or not self.missing_requirements
            or tuple(item.requirement for item in self.requirement_gap_sources)
            != self.missing_requirements
        ):
            raise ValueError("nonready card status source requires upstream gaps")
        if self.status is not JudgmentCardStatus.READY:
            if any(item.opportunity is not self.opportunity for item in self.requirement_gap_sources):
                raise ValueError("requirement gap source belongs to another opportunity")
            expected_statuses = tuple(dict.fromkeys(
                cause.status
                for gap in self.requirement_gap_sources
                for cause in gap.coverage_causes
                if cause.status is not EvidenceInputStatus.READY
            ))
            if self.coverage_statuses != expected_statuses:
                raise ValueError("card coverage statuses differ from requirement-specific causes")
            local_failure = any(
                status in {EvidenceInputStatus.NOT_MATERIALIZED, EvidenceInputStatus.INVALID_SCHEMA}
                for status in expected_statuses
            )
            expected = (
                JudgmentCardStatus.NOT_EXECUTABLE_WITH_LOCAL_DATA
                if local_failure
                else JudgmentCardStatus.INSUFFICIENT_AS_OF_CUTOFF
            )
            if self.status is not expected:
                raise ValueError("card status differs from its opportunity-specific gap causes")
        return self


class HotspotGroupType(StrEnum):
    INDUSTRY = "industry"
    THEME = "theme"


class HotspotMembershipReceipt(_FrozenModel):
    group_type: HotspotGroupType
    group_code: NonEmptyStr
    membership_evidence_ids: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]
    hotspot_evidence_ids: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]
    source_identity_hash: Sha256

    @model_validator(mode="after")
    def require_distinct_evidence_receipts(self) -> Self:
        for evidence_ids in (
            self.membership_evidence_ids,
            self.hotspot_evidence_ids,
        ):
            if len(evidence_ids) != len(set(evidence_ids)):
                raise ValueError("hotspot identity evidence receipts must be unique")
        return self


class CandidateJudgment(_FrozenModel):
    security_id: NonEmptyStr
    judgment_kind: JudgmentKind
    primary_opportunity: OpportunityType
    overall_disposition: RequirementDispositionType
    supporting_factors: Annotated[tuple[DiscoveryRoute, ...], Field(max_length=1)] = ()
    market_effect: CitedContextEffect
    hotspot_effect: CitedContextEffect
    hotspot_memberships: tuple[HotspotMembershipReceipt, ...] = ()
    card_status: JudgmentCardStatus
    card_status_source: CardStatusSourceReceipt
    price_role: CitedPriceRole
    next_validation_state: CitedValidationState
    proposition: SelectionPropositionJudgment
    directional_thesis: CitedJudgmentText
    new_driver_evidence_ids: tuple[NonEmptyStr, ...] = ()
    requirement_dispositions: Annotated[tuple[RequirementDisposition, ...], Field(min_length=1)]
    prepared_knowledge_ids: tuple[NonEmptyStr, ...]
    actually_used_knowledge: tuple[KnowledgeUseReceipt, ...] = ()
    unused_prepared_knowledge: tuple[KnowledgeNonUseReceipt, ...] = ()
    decisive_advantages: tuple[CitedJudgmentText, ...]
    decisive_comparison: DecisiveComparison
    capacity_tie_abstention: bool
    counterevidence: Annotated[tuple[ConsideredEvidence, ...], Field(min_length=1)]
    unknowns: Annotated[tuple[ConsideredEvidence, ...], Field(min_length=1)]
    next_fact: CitedJudgmentText
    invalidation: CitedJudgmentText
    suggested_layer: CandidateLayer
    evidence_refs: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def integrity(self) -> Self:
        if self.proposition.primary_opportunity is not self.primary_opportunity:
            raise ValueError("primary opportunity differs from proposition")
        if self.invalidation != self.proposition.invalidation_condition:
            raise ValueError("invalidation differs from proposition")
        for values in (
            self.prepared_knowledge_ids,
            tuple(item.knowledge_id for item in self.actually_used_knowledge),
            tuple(item.knowledge_id for item in self.unused_prepared_knowledge),
            self.new_driver_evidence_ids,
            self.evidence_refs,
            self.decisive_comparison.comparator_security_ids,
            tuple(
                (item.group_type, item.group_code)
                for item in self.hotspot_memberships
            ),
        ):
            if len(values) != len(set(values)):
                raise ValueError("receipt identities must be unique")
        used = {item.knowledge_id for item in self.actually_used_knowledge}
        unused = {item.knowledge_id for item in self.unused_prepared_knowledge}
        if used.intersection(unused):
            raise ValueError("prepared knowledge cannot be both used and unused")
        if (
            self.card_status is not JudgmentCardStatus.READY
            and self.suggested_layer is not CandidateLayer.INTERNAL
        ):
            raise ValueError("only a ready card may enter a ten-candidate layer")
        if (
            self.card_status_source.opportunity is not self.primary_opportunity
            or self.card_status_source.status is not self.card_status
        ):
            raise ValueError("card status differs from its provenance receipt")
        context_effects = {self.market_effect.effect, self.hotspot_effect.effect}
        if self.suggested_layer is CandidateLayer.FOCUS and any(
            not receipt.focus_eligible
            for receipt in (self.market_effect, self.hotspot_effect)
        ):
            raise ValueError("context consequence forbids the focus layer")
        if self.suggested_layer is not CandidateLayer.INTERNAL and any(
            receipt.company_evidence_bar is CompanyEvidenceBar.RAISED
            and not receipt.company_evidence_bar_satisfied
            for receipt in (self.market_effect, self.hotspot_effect)
        ):
            raise ValueError("unsatisfied raised evidence bar requires internal research")
        if (
            ContextEffect.OPPOSES_CAUSAL_CHAIN in context_effects
            and self.suggested_layer is not CandidateLayer.INTERNAL
        ):
            raise ValueError("a context effect that opposes the causal chain requires internal research")
        context_ids = {
            evidence_id
            for receipt in (self.market_effect, self.hotspot_effect)
            if receipt.effect is not ContextEffect.NOT_APPLICABLE
            for evidence_id in (
                *receipt.judgment.evidence_ids,
                *receipt.consequence_evidence_ids,
            )
        }
        if (
            self.suggested_layer is not CandidateLayer.INTERNAL
            and not context_ids.issubset(self.directional_thesis.evidence_ids)
        ):
            raise ValueError("non-internal direction must cite both context effects")
        accelerated_ids = {
            evidence_id
            for receipt in (self.market_effect, self.hotspot_effect)
            if receipt.invalidation_check is InvalidationCheck.ACCELERATED
            for evidence_id in receipt.consequence_evidence_ids
        }
        if not accelerated_ids.issubset(self.invalidation.evidence_ids):
            raise ValueError("accelerated invalidation must cite the triggering context effect")
        if any(
            receipt.invalidation_check is InvalidationCheck.ACCELERATED
            for receipt in (self.market_effect, self.hotspot_effect)
        ) and self.next_validation_state.next_check is ProjectDayCheckpoint.ORDINARY:
            raise ValueError("accelerated invalidation requires an accelerated next checkpoint")
        if self.security_id in self.decisive_comparison.comparator_security_ids:
            raise ValueError("comparison cohort cannot include the candidate itself")
        return self


class DailyJudgeOutput(_FrozenModel):
    formation_date: date
    candidates: tuple[CandidateJudgment, ...]
    comparison_stage_receipts: Annotated[
        tuple[ComparisonStageReceipt, ...], Field(min_length=3, max_length=3)
    ]
    capacity_tie_abstentions: tuple[CapacityTieAbstention, ...] = ()

    @model_validator(mode="after")
    def validate_global_comparison_graph(self) -> Self:
        ids = tuple(item.security_id for item in self.candidates)
        if len(ids) != len(set(ids)):
            raise ValueError("candidate set must be unique")
        expected_stages = (
            ComparisonStage.SAME_HOTSPOT_OPPORTUNITY_ROLE,
            ComparisonStage.SAME_OPPORTUNITY_CROSS_CONTEXT,
            ComparisonStage.CROSS_OPPORTUNITY,
        )
        if tuple(item.stage for item in self.comparison_stage_receipts) != expected_stages:
            raise ValueError("comparison stages must use the frozen three-stage order")
        candidate_by = {item.security_id: item for item in self.candidates}
        eligible = {
            item.security_id
            for item in self.candidates
            if item.card_status is JudgmentCardStatus.READY
        }
        dominated_all: set[str] = set()
        observed_ties: set[tuple[ComparisonStage, frozenset[str]]] = set()
        for index, receipt in enumerate(self.comparison_stage_receipts):
            if set(receipt.eligible_security_ids) != eligible:
                raise ValueError("stage eligibility must equal nondominated prior-stage survivors")
            grouped: dict[Any, set[str]] = {}
            if index == 0:
                for security_id in eligible:
                    candidate = candidate_by[security_id]
                    if not candidate.hotspot_memberships:
                        grouped[("no_verified_hotspot", security_id)] = {security_id}
                        continue
                    for membership in candidate.hotspot_memberships:
                        key = (
                            membership.group_type,
                            membership.group_code,
                            candidate.primary_opportunity,
                            candidate.price_role.role,
                        )
                        grouped.setdefault(key, set()).add(security_id)
            elif index == 1:
                for security_id in eligible:
                    candidate = candidate_by[security_id]
                    grouped.setdefault(candidate.primary_opportunity, set()).add(security_id)
            elif eligible:
                grouped["all_remaining_candidates"] = set(eligible)
            if index == 0:
                observed_groups = {
                    (
                        (
                            cohort.hotspot_identity.group_type,
                            cohort.hotspot_identity.group_code,
                            candidate_by[cohort.security_ids[0]].primary_opportunity,
                            candidate_by[cohort.security_ids[0]].price_role.role,
                        )
                        if cohort.hotspot_identity is not None
                        else ("no_verified_hotspot", cohort.security_ids[0])
                    ): frozenset(cohort.security_ids)
                    for cohort in receipt.cohorts
                }
                expected_groups = {
                    key: frozenset(members) for key, members in grouped.items()
                }
                uniform = all(
                    all(
                        candidate_by[security_id].primary_opportunity
                        is candidate_by[cohort.security_ids[0]].primary_opportunity
                        and candidate_by[security_id].price_role.role
                        is candidate_by[cohort.security_ids[0]].price_role.role
                        for security_id in cohort.security_ids
                    )
                    for cohort in receipt.cohorts
                )
            else:
                observed_groups = {frozenset(item.security_ids) for item in receipt.cohorts}
                expected_groups = {frozenset(item) for item in grouped.values()}
                uniform = True
            if (
                not uniform
                or (index == 0 and len(observed_groups) != len(receipt.cohorts))
                or observed_groups != expected_groups
            ):
                raise ValueError("stage cohorts do not expose the complete eligible grouping")
            pair_outcomes: dict[
                frozenset[str], tuple[str, str | None, str | None]
            ] = {}
            stage_adjacency = {
                security_id: set() for security_id in receipt.eligible_security_ids
            }
            for cohort in receipt.cohorts:
                for edge in cohort.decisive_edges:
                    pair = frozenset(
                        (edge.winner_security_id, edge.dominated_security_id)
                    )
                    outcome = (
                        "edge",
                        edge.winner_security_id,
                        edge.dominated_security_id,
                    )
                    existing = pair_outcomes.get(pair)
                    if existing is not None and existing != outcome:
                        raise ValueError(
                            "stage-wide contradictory comparison pair outcome"
                        )
                    pair_outcomes[pair] = outcome
                for group in cohort.indistinguishable_groups:
                    for group_index, left in enumerate(group):
                        for right in group[group_index + 1:]:
                            pair = frozenset((left, right))
                            outcome = ("tie", None, None)
                            existing = pair_outcomes.get(pair)
                            if existing is not None and existing != outcome:
                                raise ValueError(
                                    "stage-wide comparison pair cannot be both tied and dominated"
                                )
                            pair_outcomes[pair] = outcome
                    observed_ties.add((receipt.stage, frozenset(group)))
            for outcome in pair_outcomes.values():
                if outcome[0] == "edge":
                    stage_adjacency[outcome[1]].add(outcome[2])
            visiting: set[str] = set()
            visited: set[str] = set()

            def visit_stage(node: str) -> None:
                if node in visiting:
                    raise ValueError("stage-wide dominance graph contains a cycle")
                if node in visited:
                    return
                visiting.add(node)
                for child in stage_adjacency[node]:
                    visit_stage(child)
                visiting.remove(node)
                visited.add(node)

            for security_id in receipt.eligible_security_ids:
                visit_stage(security_id)
            dominated = {
                outcome[2]
                for outcome in pair_outcomes.values()
                if outcome[0] == "edge"
            }
            tied = {
                security_id
                for pair, outcome in pair_outcomes.items()
                if outcome[0] == "tie"
                for security_id in pair
            }
            dominated_all.update(dominated)
            eligible.difference_update(dominated | tied)
        cross_stage = self.comparison_stage_receipts[-1]
        for assessment in cross_stage.cross_opportunity_assessments:
            candidate = candidate_by[assessment.security_id]
            expected_action_eligible = (
                assessment.security_id in eligible
                and candidate.suggested_layer is not CandidateLayer.INTERNAL
            )
            if assessment.current_action_eligible is not expected_action_eligible:
                raise ValueError("cross-opportunity action eligibility must come from final survivors")
        assessments = {
            item.security_id: item for item in cross_stage.cross_opportunity_assessments
        }
        for pair in cross_stage.exposure_pair_receipts:
            if not pair.capacity_compatible:
                pair_actions = sum(
                    assessments[security_id].current_action_eligible
                    for security_id in (pair.left_security_id, pair.right_security_id)
                )
                if pair_actions > 1:
                    raise ValueError("shared-risk exposure pair cannot consume duplicate action capacity")
        declared_ties = {
            (item.source_stage, frozenset(item.security_ids))
            for item in self.capacity_tie_abstentions
        }
        if len(declared_ties) != len(self.capacity_tie_abstentions) or declared_ties != observed_ties:
            raise ValueError("capacity tie abstentions must exactly match indistinguishable groups")
        tied_ids = {security_id for _, group in declared_ties for security_id in group}
        for candidate in self.candidates:
            expected_tie = candidate.security_id in tied_ids
            if candidate.capacity_tie_abstention is not expected_tie:
                raise ValueError("candidate capacity-tie flag differs from the daily graph")
            if expected_tie and candidate.suggested_layer is not CandidateLayer.INTERNAL:
                raise ValueError("a whole capacity tie group must remain internal")
            if candidate.security_id in dominated_all and candidate.suggested_layer is not CandidateLayer.INTERNAL:
                raise ValueError("every dominated candidate must return to internal research")
            if (
                candidate.card_status is not JudgmentCardStatus.READY
                and candidate.security_id in {
                    security_id
                    for stage in self.comparison_stage_receipts
                    for security_id in stage.eligible_security_ids
                }
            ):
                raise ValueError("nonready card cannot enter comparison eligibility")
            if (
                candidate.suggested_layer is not CandidateLayer.INTERNAL
                and candidate.security_id not in eligible
            ):
                raise ValueError("only final nondominated survivors may retain an action layer")
        return self


class JudgeInputExclusion(_FrozenModel):
    security_id: NonEmptyStr
    reason: NonEmptyStr


class FrozenJudgeConfig(_FrozenModel):
    run_id: NonEmptyStr
    binary_path: NonEmptyStr
    binary_sha256: Sha256
    cli_version: NonEmptyStr
    model: NonEmptyStr
    reasoning_effort: NonEmptyStr
    prompt_sha256: Sha256
    schema_sha256: Sha256
    command_sha256: Sha256
    environment_sha256: Sha256
    max_request_bytes: Annotated[int, Field(gt=0)]
    runtime_attestation: Annotated[str, StringConstraints(pattern=r"^(?:production|test_only)$")]
    config_hash: Sha256

    @model_validator(mode="after")
    def validate_config_hash(self) -> Self:
        expected = _stable_hash(self.model_dump(mode="json", exclude={"config_hash"}))
        if self.config_hash != expected:
            raise ValueError("frozen judge config hash differs")
        return self


class JudgeRunConfigCommitment(_FrozenModel):
    commitment_version: Annotated[str, StringConstraints(pattern=r"^v3-judge-run-config-v1$")]
    committed_at: datetime
    experiment_config_sha256: Sha256
    config: FrozenJudgeConfig
    commitment_hash: Sha256

    @model_validator(mode="after")
    def validate_commitment(self) -> Self:
        if self.committed_at.utcoffset() is None:
            raise ValueError("run-config commitment time must be timezone-aware")
        expected = _stable_hash(
            self.model_dump(mode="json", exclude={"commitment_hash"})
        )
        if self.commitment_hash != expected:
            raise ValueError("run-config commitment hash differs")
        if self.config.runtime_attestation != "production":
            raise ValueError("persistent run-config commitment must be production")
        return self


class JudgePreflightReceipt(_FrozenModel):
    formation_date: date
    day_packet_receipt_hash: Sha256
    run_config_hash: Sha256
    run_commitment_hash: Sha256
    binary_sha256: Sha256
    command_sha256: Sha256
    environment_sha256: Sha256
    request_bytes: Annotated[int, Field(ge=0)]
    correction_worst_case_bytes: Annotated[int, Field(ge=0)]
    max_request_bytes: Annotated[int, Field(gt=0)]
    schema_compatible: bool
    probe_output_sha256: Sha256
    receipt_hash: Sha256


class JudgeAttemptReceipt(_FrozenModel):
    attempt: Annotated[int, Field(ge=1, le=2)]
    request_sha256: Sha256
    raw_output_sha256: Sha256
    returncode: int
    stdout_sha256: Sha256
    stderr_sha256: Sha256
    accepted: bool
    validation_code_sha256: Sha256 | None = None


class JudgeReceipt(_FrozenModel):
    formation_date: date
    role: NonEmptyStr
    day_packet_receipt_hash: Sha256
    run_config_hash: Sha256
    run_commitment_hash: Sha256
    preflight_receipt_hash: Sha256
    binary_path: NonEmptyStr
    binary_sha256: Sha256
    cli_version: NonEmptyStr
    model: NonEmptyStr
    reasoning_effort: NonEmptyStr
    prompt_sha256: Sha256
    schema_sha256: Sha256
    input_sha256: Sha256
    output_sha256: Sha256
    knowledge_usage_sha256: Sha256
    command_sha256: Sha256
    environment_sha256: Sha256
    runtime_attestation: Annotated[str, StringConstraints(pattern=r"^(?:production|test_only)$")]
    attempts: Annotated[tuple[JudgeAttemptReceipt, ...], Field(min_length=1, max_length=2)]


class _DayRegistration:
    __slots__ = (
        "batch_id", "bundle_id", "receipt_hash", "candidate_ids", "knowledge_ids",
        "card_status_ids", "hotspot_membership_ids",
    )
    def __init__(self, batch_id, bundle_id, receipt_hash, candidate_ids, knowledge_ids, card_status_ids, hotspot_membership_ids):
        self.batch_id = batch_id; self.bundle_id = bundle_id; self.receipt_hash = receipt_hash
        self.candidate_ids = candidate_ids; self.knowledge_ids = knowledge_ids
        self.card_status_ids = card_status_ids
        self.hotspot_membership_ids = hotspot_membership_ids


_DAY_REGISTRY: WeakKeyDictionary["JudgeDayPacket", _DayRegistration] = WeakKeyDictionary()


class JudgeDayPacket:
    __slots__ = (
        "__batch", "__bundle", "formation_date", "cutoff", "route_batch_hash",
        "evidence_bundle_hash", "candidates", "exclusions", "__knowledge",
        "__card_statuses", "__hotspot_memberships",
        "__receipt_preimage", "__receipt_hash", "__weakref__",
    )

    def __init__(self, *args, **kwargs):
        raise TypeError("JudgeDayPacket is created only by build_judge_day_packet")

    @property
    def receipt_hash(self): return self.__receipt_hash
    @property
    def receipt_preimage(self): return dict(self.__receipt_preimage)
    def prepared_knowledge_for(self, security_id): return self.__knowledge[security_id]
    def card_statuses_for(self, security_id): return self.__card_statuses[security_id]
    def hotspot_memberships_for(self, security_id): return self.__hotspot_memberships[security_id]


def _bundle_hash(bundle: Any) -> str:
    value = getattr(bundle, "_VerifiedEvidenceSnapshotBundle__bundle_hash", None)
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise JudgeError("verified evidence bundle lacks canonical hash")
    return value


def _derive_card_status_source(packet, card) -> CardStatusSourceReceipt:
    """Lift the legacy two-state Task5 card into the closed judgment status taxonomy."""

    if card.status is EvidenceCardStatus.EVIDENCE_READY_FOR_JUDGMENT:
        status = JudgmentCardStatus.READY
        coverage_statuses: tuple[EvidenceInputStatus, ...] = ()
        gap_sources: tuple[RequirementGapSourceReceipt, ...] = ()
    else:
        coverage_by = {item.dataset: item for item in packet.input_coverage}
        gaps: list[RequirementGapSourceReceipt] = []
        for requirement in card.missing_requirements:
            datasets = _CARD_REQUIREMENT_DATASETS.get(
                (card.opportunity, requirement),
                _CARD_REQUIREMENT_DATASETS.get(requirement),
            )
            if not datasets:
                raise JudgeError("incomplete card has an unmapped governed requirement")
            try:
                causes = tuple(
                    CoverageCauseReceipt(
                        dataset=dataset,
                        status=coverage_by[dataset].status,
                        coverage_hash=_stable_hash(coverage_by[dataset].model_dump(mode="json")),
                    )
                    for dataset in datasets
                )
            except KeyError as exc:
                raise JudgeError("card gap lacks a governed coverage record") from exc
            gaps.append(RequirementGapSourceReceipt(
                opportunity=card.opportunity,
                requirement=requirement,
                governed_datasets=datasets,
                coverage_causes=causes,
                mapping_hash=_stable_hash({
                    "opportunity": card.opportunity,
                    "requirement": requirement,
                    "datasets": datasets,
                }),
            ))
        gap_sources = tuple(gaps)
        coverage_statuses = tuple(
            dict.fromkeys(
                cause.status
                for gap in gap_sources
                for cause in gap.coverage_causes
                if cause.status is not EvidenceInputStatus.READY
            )
        )
        local_execution_failures = {
            EvidenceInputStatus.NOT_MATERIALIZED,
            EvidenceInputStatus.INVALID_SCHEMA,
        }
        status = (
            JudgmentCardStatus.NOT_EXECUTABLE_WITH_LOCAL_DATA
            if local_execution_failures.intersection(coverage_statuses)
            else JudgmentCardStatus.INSUFFICIENT_AS_OF_CUTOFF
        )
    return CardStatusSourceReceipt(
        opportunity=card.opportunity,
        status=status,
        upstream_status=card.status,
        missing_requirements=card.missing_requirements,
        coverage_statuses=coverage_statuses,
        requirement_gap_sources=gap_sources,
        source_card_hash=_stable_hash(card.model_dump(mode="json")),
    )


def _derive_hotspot_memberships(packet) -> tuple[HotspotMembershipReceipt, ...]:
    membership_sources: dict[tuple[HotspotGroupType, str], list[Any]] = {}
    data = (*packet.api_facts, *packet.local_observations)
    for item in data:
        if item.dataset == "industry_member" and item.field == "industry_code":
            key = (HotspotGroupType.INDUSTRY, str(item.value))
        elif item.dataset == "theme_member" and item.field == "theme_code":
            key = (HotspotGroupType.THEME, str(item.value))
        else:
            continue
        membership_sources.setdefault(key, []).append(item)
    sector_rows: dict[str, dict[str, Any]] = {}
    for item in data:
        if item.dataset == "sector_hotspot" and item.field in {"group_type", "group_code"}:
            sector_rows.setdefault(item.row_key, {})[item.field] = item
    hotspot_sources: dict[tuple[HotspotGroupType, str], list[Any]] = {}
    for row in sector_rows.values():
        if set(row) != {"group_type", "group_code"}:
            continue
        try:
            group_type = HotspotGroupType(str(row["group_type"].value))
        except ValueError:
            continue
        key = (group_type, str(row["group_code"].value))
        hotspot_sources.setdefault(key, []).extend(
            (row["group_type"], row["group_code"])
        )
    return tuple(
        HotspotMembershipReceipt(
            group_type=group_type,
            group_code=group_code,
            membership_evidence_ids=tuple(
                sorted({item.evidence_id for item in membership_sources[key]})
            ),
            hotspot_evidence_ids=tuple(
                sorted({item.evidence_id for item in hotspot_sources[key]})
            ),
            source_identity_hash=_stable_hash(
                {
                    "group_type": group_type,
                    "group_code": group_code,
                    "membership_evidence": [
                        item.model_dump(mode="json")
                        for item in sorted(
                            membership_sources[key],
                            key=lambda value: value.evidence_id,
                        )
                    ],
                    "hotspot_evidence": [
                        item.model_dump(mode="json")
                        for item in sorted(
                            hotspot_sources[key],
                            key=lambda value: value.evidence_id,
                        )
                    ],
                }
            ),
        )
        for key in sorted(
            set(membership_sources).intersection(hotspot_sources),
            key=lambda value: (value[0].value, value[1]),
        )
        for group_type, group_code in (key,)
    )


def _build_day_components(batch, bundle):
    _, hypotheses = tuple(batch)
    candidates = []
    exclusions = []
    knowledge = {}
    card_statuses = {}
    hotspot_memberships = {}
    for hypothesis in sorted(hypotheses, key=lambda item: item.security_id):
        packet = build_candidate_packet(batch, bundle, hypothesis.security_id)
        receipts = tuple(
            _derive_card_status_source(packet, card) for card in packet.opportunity_cards
        )
        card_statuses[packet.security_id] = receipts
        hotspot_memberships[packet.security_id] = _derive_hotspot_memberships(packet)
        if not any(item.status is JudgmentCardStatus.READY for item in receipts):
            exclusions.append(JudgeInputExclusion(
                security_id=packet.security_id,
                reason="no opportunity card is ready for judgment",
            ))
            continue
        candidates.append(packet)
        knowledge[packet.security_id] = _prepared_knowledge_inputs(packet)
    return tuple(candidates), tuple(exclusions), knowledge, card_statuses, hotspot_memberships


def build_judge_day_packet(route_scan_batch: VerifiedRouteScanBatch, evidence_snapshot_bundle: VerifiedEvidenceSnapshotBundle) -> JudgeDayPacket:
    batch = require_verified_route_scan_batch(route_scan_batch)
    bundle = require_verified_evidence_snapshot_bundle(evidence_snapshot_bundle, batch)
    candidates, exclusions, knowledge, card_statuses, hotspot_memberships = _build_day_components(batch, bundle)
    value = object.__new__(JudgeDayPacket)
    object.__setattr__(value, "_JudgeDayPacket__batch", batch)
    object.__setattr__(value, "_JudgeDayPacket__bundle", bundle)
    object.__setattr__(value, "formation_date", batch.window_policy.formation_date)
    object.__setattr__(value, "cutoff", batch.snapshot.as_of)
    object.__setattr__(value, "route_batch_hash", batch.batch_hash)
    object.__setattr__(value, "evidence_bundle_hash", _bundle_hash(bundle))
    object.__setattr__(value, "candidates", candidates)
    object.__setattr__(value, "exclusions", exclusions)
    object.__setattr__(value, "_JudgeDayPacket__knowledge", knowledge)
    object.__setattr__(value, "_JudgeDayPacket__card_statuses", card_statuses)
    object.__setattr__(value, "_JudgeDayPacket__hotspot_memberships", hotspot_memberships)
    preimage = _day_receipt_preimage(value)
    receipt_hash = _stable_hash(preimage)
    object.__setattr__(value, "_JudgeDayPacket__receipt_preimage", preimage)
    object.__setattr__(value, "_JudgeDayPacket__receipt_hash", receipt_hash)
    _DAY_REGISTRY[value] = _DayRegistration(
        id(batch), id(bundle), receipt_hash, tuple(id(item) for item in candidates),
        tuple((key, tuple(id(item) for item in values)) for key, values in sorted(knowledge.items())),
        tuple((key, tuple(id(item) for item in values)) for key, values in sorted(card_statuses.items())),
        tuple((key, tuple(id(item) for item in values)) for key, values in sorted(hotspot_memberships.items())),
    )
    return value


def _day_input(value: JudgeDayPacket) -> dict[str, Any]:
    return {
        "formation_date": value.formation_date,
        "cutoff": value.cutoff,
        "route_batch_hash": value.route_batch_hash,
        "evidence_bundle_hash": value.evidence_bundle_hash,
        "candidates": [
            {
                "evidence_packet": packet.model_dump(mode="json"),
                "prepared_knowledge": [item.model_dump(mode="json") for item in value.prepared_knowledge_for(packet.security_id)],
                "card_status_sources": [item.model_dump(mode="json") for item in value.card_statuses_for(packet.security_id)],
                "hotspot_memberships": [item.model_dump(mode="json") for item in value.hotspot_memberships_for(packet.security_id)],
            }
            for packet in value.candidates
        ],
        "exclusions": [item.model_dump(mode="json") for item in value.exclusions],
        "excluded_card_status_sources": {
            item.security_id: [
                source.model_dump(mode="json")
                for source in value.card_statuses_for(item.security_id)
            ]
            for item in value.exclusions
        },
    }


def _day_receipt_preimage(value):
    return {"schema": "v3-judge-day-v2", "input": _day_input(value)}


def require_verified_judge_day_packet(value: Any) -> JudgeDayPacket:
    if type(value) is not JudgeDayPacket or value not in _DAY_REGISTRY:
        raise JudgeError("judge day packet lacks verified provenance")
    reg = _DAY_REGISTRY[value]
    batch = getattr(value, "_JudgeDayPacket__batch", None)
    bundle = getattr(value, "_JudgeDayPacket__bundle", None)
    try:
        verified_batch = require_verified_route_scan_batch(batch)
        verified_bundle = require_verified_evidence_snapshot_bundle(bundle, verified_batch)
    except Exception as exc:
        raise JudgeError("judge day packet upstream bundle provenance failed") from exc
    if id(batch) != reg.batch_id or id(bundle) != reg.bundle_id:
        raise JudgeError("judge day packet upstream identity changed")
    candidates, exclusions, knowledge, card_statuses, hotspot_memberships = _build_day_components(verified_batch, verified_bundle)
    if tuple(id(item) for item in value.candidates) != reg.candidate_ids:
        raise JudgeError("judge day packet candidate identity changed")
    if tuple(_stable_hash(item.model_dump(mode="json")) for item in candidates) != tuple(_stable_hash(item.model_dump(mode="json")) for item in value.candidates):
        raise JudgeError("judge day packet candidate content differs from upstream")
    if tuple(item.model_dump(mode="json") for item in exclusions) != tuple(item.model_dump(mode="json") for item in value.exclusions):
        raise JudgeError("judge day packet exclusions differ from upstream")
    observed_knowledge = tuple((key, tuple(id(item) for item in value.prepared_knowledge_for(key))) for key in sorted(knowledge))
    if observed_knowledge != reg.knowledge_ids:
        raise JudgeError("judge day packet knowledge identity changed")
    for security_id, rebuilt in knowledge.items():
        current = value.prepared_knowledge_for(security_id)
        if tuple(item.model_dump(mode="json") for item in rebuilt) != tuple(
            item.model_dump(mode="json") for item in current
        ):
            raise JudgeError("judge day packet knowledge content differs from registry")
    observed_card_statuses = tuple(
        (key, tuple(id(item) for item in value.card_statuses_for(key)))
        for key in sorted(card_statuses)
    )
    if observed_card_statuses != reg.card_status_ids:
        raise JudgeError("judge day packet card-status identity changed")
    for security_id, rebuilt in card_statuses.items():
        current = value.card_statuses_for(security_id)
        if tuple(item.model_dump(mode="json") for item in rebuilt) != tuple(
            item.model_dump(mode="json") for item in current
        ):
            raise JudgeError("judge day packet card-status content differs from upstream")
    observed_hotspots = tuple(
        (key, tuple(id(item) for item in value.hotspot_memberships_for(key)))
        for key in sorted(hotspot_memberships)
    )
    if observed_hotspots != reg.hotspot_membership_ids:
        raise JudgeError("judge day packet hotspot-membership identity changed")
    for security_id, rebuilt in hotspot_memberships.items():
        current = value.hotspot_memberships_for(security_id)
        if tuple(item.model_dump(mode="json") for item in rebuilt) != tuple(
            item.model_dump(mode="json") for item in current
        ):
            raise JudgeError("judge day packet hotspot membership differs from evidence")
    preimage = _day_receipt_preimage(value)
    if preimage != getattr(value, "_JudgeDayPacket__receipt_preimage", None) or _stable_hash(preimage) != reg.receipt_hash or value.receipt_hash != reg.receipt_hash:
        raise JudgeError("judge day packet receipt hash mismatch")
    _validate_closed_formation_input(_day_input(value), value.cutoff)
    return value


def _prepared_knowledge_inputs(packet):
    registry = load_knowledge_registry(_REGISTRY_PATH)
    entries = {item.knowledge_id: item for item in registry.entries}
    audits = {item.knowledge_id: item for item in packet.registry_audit.prepared_entries}
    records = {item.knowledge_id: item for item in packet.knowledge_routing if item.status is KnowledgeRoutingStatus.PREPARED_FOR_JUDGMENT}
    if set(audits) != set(records):
        raise JudgeError("prepared knowledge audits differ from routing")
    result = []
    for knowledge_id in sorted(records):
        entry, audit, record = entries[knowledge_id], audits[knowledge_id], records[knowledge_id]
        entry_hash = _stable_hash(entry.model_dump(mode="json"))
        if entry.version_status != "current" or entry_hash != audit.entry_content_hash:
            raise JudgeError("prepared knowledge version/content mismatch")
        if entry.effective_from and packet.formation_date < entry.effective_from or entry.effective_to and packet.formation_date > entry.effective_to:
            raise JudgeError("prepared knowledge is not effective")
        selected_allowed_use = entry.allowed_uses[0]
        allowed_hash = _stable_hash(selected_allowed_use)
        if record.claim_summary_hash != _stable_hash(entry.claim_summary) or record.allowed_use_hash != allowed_hash or record.use_purpose != audit.use_purpose:
            raise JudgeError("prepared knowledge routing/content mismatch")
        result.append(PreparedKnowledgeInput(
            knowledge_id=knowledge_id, title=entry.title, effect=entry.effect,
            claim_summary=entry.claim_summary, prepared_purpose=record.use_purpose,
            allowed_use_hash=allowed_hash, selected_allowed_use=selected_allowed_use,
            forbidden_uses=entry.forbidden_uses, prerequisites=entry.prerequisites,
            counter_evidence=entry.counter_evidence, entry_content_hash=entry_hash,
            evidence_ids=record.evidence_ids,
        ))
    return tuple(result)


def _validate_closed_formation_input(value: Any, cutoff: datetime, path="input"):
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).lower()
            if any(marker in normalized for marker in _FORBIDDEN_INPUT_FIELD_PARTS):
                raise JudgeError(f"outcome/future-result field is forbidden: {path}.{key}")
            _validate_closed_formation_input(item, cutoff, f"{path}.{key}")
    elif isinstance(value, (tuple, list)):
        for index, item in enumerate(value): _validate_closed_formation_input(item, cutoff, f"{path}[{index}]")
    elif isinstance(value, str) and any(marker.lower() in value.lower() for marker in _FORBIDDEN_INPUT_TEXT):
        raise JudgeError(f"outcome language is forbidden: {path}")


class _BatchRegistration:
    __slots__ = ("day_id", "output_id", "receipt_id", "batch_hash")
    def __init__(self, day_id, output_id, receipt_id, batch_hash):
        self.day_id = day_id; self.output_id = output_id; self.receipt_id = receipt_id; self.batch_hash = batch_hash


_BATCH_REGISTRY: WeakKeyDictionary["VerifiedJudgmentBatch", _BatchRegistration] = WeakKeyDictionary()


class VerifiedJudgmentBatch:
    __slots__ = ("__day", "__output", "__exclusions", "__receipt", "__preimage", "__batch_hash", "__weakref__")
    def __init__(self, *args, **kwargs): raise TypeError("VerifiedJudgmentBatch is produced only by FrozenDecisionJudge")
    @property
    def output(self): return self.__output
    @property
    def exclusions(self): return self.__exclusions
    @property
    def receipt(self): return self.__receipt
    @property
    def batch_hash(self): return self.__batch_hash
    @property
    def receipt_preimage(self): return dict(self.__preimage)


def _make_verified_batch(day, output, receipt):
    value = object.__new__(VerifiedJudgmentBatch)
    object.__setattr__(value, "_VerifiedJudgmentBatch__day", day)
    object.__setattr__(value, "_VerifiedJudgmentBatch__output", output)
    object.__setattr__(value, "_VerifiedJudgmentBatch__exclusions", day.exclusions)
    object.__setattr__(value, "_VerifiedJudgmentBatch__receipt", receipt)
    preimage = {
        "schema": "v3-verified-judgment-v2", "day_packet_receipt_hash": day.receipt_hash,
        "output": output.model_dump(mode="json"), "exclusions": [item.model_dump(mode="json") for item in day.exclusions],
        "receipt": receipt.model_dump(mode="json"),
    }
    batch_hash = _stable_hash(preimage)
    object.__setattr__(value, "_VerifiedJudgmentBatch__preimage", preimage)
    object.__setattr__(value, "_VerifiedJudgmentBatch__batch_hash", batch_hash)
    _BATCH_REGISTRY[value] = _BatchRegistration(id(day), id(output), id(receipt), batch_hash)
    return value


def canonical_judgment_batch_receipt_hash(record: Mapping[str, Any]) -> str:
    """Recompute a persisted Task6 batch hash without trusting process registries."""
    required = {
        "schema", "day_packet_receipt_hash", "output", "exclusions", "receipt"
    }
    if set(record) != required or record.get("schema") != "v3-verified-judgment-v2":
        raise JudgeError("persisted judgment receipt has an unknown schema")
    output = DailyJudgeOutput.model_validate(record["output"])
    exclusions = tuple(JudgeInputExclusion.model_validate(item) for item in record["exclusions"])
    receipt = JudgeReceipt.model_validate(record["receipt"])
    day_hash = record["day_packet_receipt_hash"]
    if not isinstance(day_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", day_hash):
        raise JudgeError("persisted judgment day receipt hash is invalid")
    output_hash = _stable_hash(output.model_dump(mode="json"))
    knowledge_hash = _stable_hash({
        item.security_id: {
            "used": [use.model_dump(mode="json") for use in item.actually_used_knowledge],
            "unused": [use.model_dump(mode="json") for use in item.unused_prepared_knowledge],
        }
        for item in output.candidates
    })
    if (
        receipt.day_packet_receipt_hash != day_hash
        or receipt.formation_date != output.formation_date
        or receipt.output_sha256 != output_hash
        or receipt.knowledge_usage_sha256 != knowledge_hash
    ):
        raise JudgeError("persisted judgment receipt bindings differ")
    canonical = {
        "schema": "v3-verified-judgment-v2",
        "day_packet_receipt_hash": day_hash,
        "output": output.model_dump(mode="json"),
        "exclusions": [item.model_dump(mode="json") for item in exclusions],
        "receipt": receipt.model_dump(mode="json"),
    }
    return _stable_hash(canonical)


def require_verified_judgment_batch(
    value: Any, *, allow_test_only: bool = False
) -> VerifiedJudgmentBatch:
    if type(value) is not VerifiedJudgmentBatch or value not in _BATCH_REGISTRY:
        raise JudgeError("judgment batch lacks verified provenance")
    reg = _BATCH_REGISTRY[value]
    day = getattr(value, "_VerifiedJudgmentBatch__day", None)
    require_verified_judge_day_packet(day)
    output, receipt = value.output, value.receipt
    if receipt.runtime_attestation == "test_only" and not allow_test_only:
        raise JudgeError("test-only judgment batch is not valid for downstream use")
    if id(day) != reg.day_id or id(output) != reg.output_id or id(receipt) != reg.receipt_id:
        raise JudgeError("judgment batch component identity mismatch")
    if receipt.day_packet_receipt_hash != day.receipt_hash or receipt.output_sha256 != _stable_hash(output.model_dump(mode="json")):
        raise JudgeError("judgment receipt binding mismatch")
    preimage = {
        "schema": "v3-verified-judgment-v2", "day_packet_receipt_hash": day.receipt_hash,
        "output": output.model_dump(mode="json"), "exclusions": [item.model_dump(mode="json") for item in day.exclusions],
        "receipt": receipt.model_dump(mode="json"),
    }
    if preimage != value.receipt_preimage or _stable_hash(preimage) != reg.batch_hash or value.batch_hash != reg.batch_hash:
        raise JudgeError("judgment batch canonical hash mismatch")
    return value


_PREFLIGHT_REGISTRY: WeakKeyDictionary[JudgePreflightReceipt, tuple[int, int, str]] = WeakKeyDictionary()


Runner = Callable[..., subprocess.CompletedProcess[str]]


def load_judge_run_config_commitment(path: Path) -> JudgeRunConfigCommitment:
    """Load the authority-owned commitment frozen before any model invocation."""
    source = Path(path)
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise JudgeError("persistent judge run-config commitment is unavailable") from exc
    try:
        return JudgeRunConfigCommitment.model_validate(raw)
    except ValidationError as exc:
        raise JudgeError("persistent judge run-config commitment is invalid") from exc


def _subprocess_runner(command, *, cwd, input_text, env, timeout):
    return subprocess.run(command, cwd=cwd, input=input_text, env=env, text=True, capture_output=True, timeout=timeout, check=False)


class FrozenDecisionJudge:
    def __init__(
        self, *, run_config_commitment_path: Path, ledger_path: Path,
        temp_root: Path | None = None, timeout_seconds: float = 900.0,
    ):
        commitment = load_judge_run_config_commitment(run_config_commitment_path)
        self._initialize(
            run_id=commitment.config.run_id,
            ledger_path=ledger_path,
            runner=_subprocess_runner,
            binary_reader=lambda path: path.read_bytes(),
            runtime_attestation="production",
            expected_config=commitment.config,
            run_commitment_hash=commitment.commitment_hash,
            temp_root=temp_root,
            timeout_seconds=timeout_seconds,
            max_request_bytes=commitment.config.max_request_bytes,
        )

    @classmethod
    def for_test(
        cls, *, run_id: str, ledger_path: Path, runner: Runner,
        binary_reader: Callable[[Path], bytes], temp_root: Path | None = None,
        timeout_seconds: float = 900.0, max_request_bytes: int = 5_000_000,
    ) -> "FrozenDecisionJudge":
        """Construct an explicitly non-production judge for deterministic contract tests."""
        value = object.__new__(cls)
        value._initialize(
            run_id=run_id,
            ledger_path=ledger_path,
            runner=runner,
            binary_reader=binary_reader,
            runtime_attestation="test_only",
            expected_config=None,
            run_commitment_hash=None,
            temp_root=temp_root,
            timeout_seconds=timeout_seconds,
            max_request_bytes=max_request_bytes,
        )
        return value

    def _initialize(
        self, *, run_id, ledger_path, runner, binary_reader, runtime_attestation,
        expected_config, run_commitment_hash,
        temp_root, timeout_seconds, max_request_bytes,
    ):
        self._runner = runner; self._ledger_path = Path(ledger_path); self._temp_root = Path(temp_root) if temp_root else None
        self._timeout = timeout_seconds; self._binary_reader = binary_reader
        self._prompt = _PROMPT_PATH.read_text(encoding="utf-8")
        self._schema = DailyJudgeOutput.model_json_schema()
        self._env = _codex_environment()
        binary_hash = hashlib.sha256(self._binary_reader(Path(_BINARY))).hexdigest()
        prompt_hash = _sha256_text(self._prompt)
        schema_hash = _stable_hash(self._schema)
        base = {
            "run_id": run_id, "binary_path": _BINARY, "binary_sha256": binary_hash,
            "cli_version": _CLI_VERSION, "model": _MODEL, "reasoning_effort": _REASONING,
            "prompt_sha256": prompt_hash, "schema_sha256": schema_hash,
            "command_sha256": _stable_hash(_COMMAND_TEMPLATE), "environment_sha256": _stable_hash(self._env),
            "max_request_bytes": max_request_bytes, "runtime_attestation": runtime_attestation,
        }
        self.config = FrozenJudgeConfig(**base, config_hash=_stable_hash(base))
        if runtime_attestation == "production" and self.config != expected_config:
            raise JudgeError("production judge differs from persistent preregistered config")
        self._run_commitment_hash = run_commitment_hash or _stable_hash({
            "runtime_attestation": "test_only", "config_hash": self.config.config_hash
        })
        self._initialize_ledger()

    def _initialize_ledger(self):
        self._ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with self._locked_ledger() as ledger:
            existing = ledger.get("run_config_hash")
            if existing and existing != self.config.config_hash:
                raise JudgeError("run-level frozen judge config changed")
            existing_commitment = ledger.get("run_commitment_hash")
            if existing_commitment and existing_commitment != self._run_commitment_hash:
                raise JudgeError("run-level judge commitment changed")
            ledger.setdefault("run_config_hash", self.config.config_hash)
            ledger.setdefault("run_commitment_hash", self._run_commitment_hash)
            ledger.setdefault("sequence", 0)
            ledger.setdefault("entries", {})

    def _locked_ledger(self):
        return _Ledger(self._ledger_path)

    def _verify_runtime(self):
        if hashlib.sha256(self._binary_reader(Path(_BINARY))).hexdigest() != self.config.binary_sha256:
            raise JudgeError("fixed Codex binary hash changed")
        completed = self._runner([_BINARY, "--version"], cwd=self._temp_root or Path(tempfile.gettempdir()), input_text="", env=self._env, timeout=self._timeout)
        if completed.returncode != 0 or completed.stdout.strip() != _CLI_VERSION:
            raise JudgeError("fixed Codex CLI version unavailable")

    def preflight(self, day_packet):
        day = require_verified_judge_day_packet(day_packet)
        payload = _day_input(day)
        original_request = {"instructions": self._prompt, "formation_input": payload}
        correction_request = {
            "instructions": self._prompt,
            "formation_input": payload,
            "correction": {"kind": "structure_only", "codes": ["schema:" + "x" * 256]},
        }
        request_bytes = len(_canonical_json(original_request).encode())
        correction_bytes = len(_canonical_json(correction_request).encode())
        if max(request_bytes, correction_bytes) > self.config.max_request_bytes:
            raise JudgeError("daily full-batch context capacity exceeded")
        self._verify_runtime()
        probe_request = _canonical_json({
            "instructions": (
                "Context-capacity and JSON-schema preflight only. Read the complete "
                "formation_input, make no candidate judgment, and return its formation "
                "date with an empty candidates array."
            ),
            "formation_input": payload,
        })
        raw, process = self._invoke(probe_request)
        try:
            probe_date = date.fromisoformat(raw["formation_date"])
            probe_candidates = raw["candidates"]
        except (KeyError, TypeError, ValueError) as exc:
            raise JudgeError("frozen CLI output schema preflight failed") from exc
        if probe_date != day.formation_date or probe_candidates != []:
            raise JudgeError("frozen CLI output schema preflight failed")
        values = {
            "formation_date": day.formation_date, "day_packet_receipt_hash": day.receipt_hash,
            "run_config_hash": self.config.config_hash, "binary_sha256": self.config.binary_sha256,
            "run_commitment_hash": self._run_commitment_hash,
            "command_sha256": self.config.command_sha256, "environment_sha256": self.config.environment_sha256,
            "request_bytes": request_bytes, "correction_worst_case_bytes": correction_bytes,
            "max_request_bytes": self.config.max_request_bytes, "schema_compatible": True,
            "probe_output_sha256": process["raw_output_sha256"],
        }
        receipt = JudgePreflightReceipt(**values, receipt_hash=_stable_hash(values))
        _PREFLIGHT_REGISTRY[receipt] = (id(receipt), id(day), self.config.config_hash)
        return receipt

    def _require_preflight(self, receipt, day):
        registration = _PREFLIGHT_REGISTRY.get(receipt)
        if registration != (id(receipt), id(day), self.config.config_hash) or receipt.receipt_hash != _stable_hash(receipt.model_dump(mode="json", exclude={"receipt_hash"})):
            raise JudgeError("preflight receipt lacks verified provenance")
        if (
            not receipt.schema_compatible
            or receipt.day_packet_receipt_hash != day.receipt_hash
            or receipt.run_commitment_hash != self._run_commitment_hash
        ):
            raise JudgeError("preflight receipt belongs to another day")

    def judge(self, day_packet, preflight_receipt):
        day = require_verified_judge_day_packet(day_packet); self._require_preflight(preflight_receipt, day)
        self._reserve(day, "primary")
        batch = self._run_once(day, preflight_receipt, "primary")
        self._complete(day, "primary", batch.batch_hash)
        return batch

    def audit_consistency(self, day_packet, preflight_receipt):
        day = require_verified_judge_day_packet(day_packet); self._require_preflight(preflight_receipt, day)
        self._reserve(day, "primary"); first = self._run_once(day, preflight_receipt, "primary"); self._complete(day, "primary", first.batch_hash)
        self._reserve(day, "consistency_repeat"); second = self._run_once(day, preflight_receipt, "consistency_repeat"); self._complete(day, "consistency_repeat", second.batch_hash)
        mismatches = _consistency_mismatches(first.output, second.output)
        audit = _make_consistency_audit(day, first, second, mismatches)
        if mismatches: raise JudgeInstabilityError(audit)
        return audit

    def _reserve(self, day, role):
        key = f"{day.formation_date.isoformat()}:{role}"
        with self._locked_ledger() as ledger:
            if key in ledger["entries"]:
                raise JudgeError(f"{role} batch already reserved for formation day")
            ledger["sequence"] += 1
            ledger["entries"][key] = {
                "sequence": ledger["sequence"],
                "input_hash": _stable_hash(_day_input(day)),
                "status": "reserved",
            }

    def _complete(self, day, role, batch_hash):
        key = f"{day.formation_date.isoformat()}:{role}"
        with self._locked_ledger() as ledger:
            ledger["entries"][key].update(status="complete", batch_hash=batch_hash)

    def _run_once(self, day, preflight, role):
        self._verify_runtime()
        original = {"instructions": self._prompt, "formation_input": _day_input(day)}
        request = original; attempts = []
        for attempt in (1, 2):
            request_text = _canonical_json(request)
            raw, process = self._invoke(request_text)
            raw_hash = process["raw_output_sha256"]
            try:
                output = DailyJudgeOutput.model_validate(raw); _validate_output(output, day)
            except (ValidationError, ValueError, TypeError) as exc:
                code = _validation_code(exc)
                attempts.append(JudgeAttemptReceipt(
                    attempt=attempt, request_sha256=_sha256_text(request_text),
                    raw_output_sha256=raw_hash, returncode=process["returncode"],
                    stdout_sha256=process["stdout_sha256"], stderr_sha256=process["stderr_sha256"],
                    accepted=False, validation_code_sha256=_sha256_text(code),
                ))
                if attempt == 2: raise JudgeError("structured judgment failed validation and must fail closed") from exc
                request = {"instructions": self._prompt, "formation_input": _day_input(day), "correction": {"kind": "structure_only", "codes": [code]}}
                continue
            attempts.append(JudgeAttemptReceipt(
                attempt=attempt, request_sha256=_sha256_text(request_text),
                raw_output_sha256=raw_hash, returncode=process["returncode"],
                stdout_sha256=process["stdout_sha256"], stderr_sha256=process["stderr_sha256"],
                accepted=True,
            ))
            output_hash = _stable_hash(output.model_dump(mode="json"))
            knowledge_hash = _stable_hash({
                item.security_id: {
                    "used": [use.model_dump(mode="json") for use in item.actually_used_knowledge],
                    "unused": [use.model_dump(mode="json") for use in item.unused_prepared_knowledge],
                }
                for item in output.candidates
            })
            receipt = JudgeReceipt(
                formation_date=day.formation_date, role=role, day_packet_receipt_hash=day.receipt_hash,
                run_config_hash=self.config.config_hash, preflight_receipt_hash=preflight.receipt_hash,
                run_commitment_hash=self._run_commitment_hash,
                binary_path=self.config.binary_path, binary_sha256=self.config.binary_sha256,
                cli_version=self.config.cli_version, model=self.config.model, reasoning_effort=self.config.reasoning_effort,
                prompt_sha256=self.config.prompt_sha256, schema_sha256=self.config.schema_sha256,
                input_sha256=_stable_hash(_day_input(day)), output_sha256=output_hash,
                knowledge_usage_sha256=knowledge_hash, command_sha256=self.config.command_sha256,
                environment_sha256=self.config.environment_sha256,
                runtime_attestation=self.config.runtime_attestation, attempts=tuple(attempts),
            )
            return _make_verified_batch(day, output, receipt)
        raise JudgeError("unreachable judgment failure")

    def _invoke(self, request_text):
        try:
            with tempfile.TemporaryDirectory(prefix="v3-backtest-judge-", dir=self._temp_root) as temporary:
                root = Path(temporary); schema_path = root / "response.schema.json"; output_path = root / "response.json"
                schema_path.write_text(_canonical_json(self._schema), encoding="utf-8")
                command = [_BINARY, *_COMMAND_TEMPLATE]
                command[command.index("<schema>")] = str(schema_path); command[command.index("<output>")] = str(output_path)
                completed = self._runner(command, cwd=root, input_text=request_text, env=self._env, timeout=self._timeout)
                if completed.returncode != 0: raise JudgeError("fixed Codex model failed; fallback is forbidden")
                if not output_path.is_file(): raise JudgeError("fixed Codex model produced no output")
                raw_bytes = output_path.read_bytes()
                value = json.loads(raw_bytes)
                if not isinstance(value, dict): raise JudgeError("structured output must be an object")
                return value, {
                    "raw_output_sha256": hashlib.sha256(raw_bytes).hexdigest(),
                    "returncode": completed.returncode,
                    "stdout_sha256": _sha256_text(completed.stdout),
                    "stderr_sha256": _sha256_text(completed.stderr),
                }
        except subprocess.TimeoutExpired as exc: raise JudgeError("fixed Codex model timed out; fallback is forbidden") from exc
        except json.JSONDecodeError as exc: raise JudgeError("fixed Codex output is invalid JSON") from exc


class _Ledger:
    def __init__(self, path):
        self.path = path
        self.lock_path = path.with_name(path.name + ".lock")
        self.handle = None
        self.data = None
    def __enter__(self):
        self.handle = self.lock_path.open("a+", encoding="utf-8")
        fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX)
        text = self.path.read_text(encoding="utf-8") if self.path.exists() else ""
        self.data = json.loads(text) if text else {}
        return self.data
    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            fd, temporary_name = tempfile.mkstemp(
                prefix=self.path.name + ".", suffix=".tmp", dir=self.path.parent
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as temporary:
                    temporary.write(_canonical_json(self.data))
                    temporary.flush()
                    os.fsync(temporary.fileno())
                os.replace(temporary_name, self.path)
                directory_fd = os.open(self.path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            finally:
                if os.path.exists(temporary_name):
                    os.unlink(temporary_name)
        fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        self.handle.close()


class _AuditRegistration:
    __slots__ = ("day_id", "first_id", "second_id", "hash")
    def __init__(self, day_id, first_id, second_id, hash): self.day_id=day_id; self.first_id=first_id; self.second_id=second_id; self.hash=hash


_AUDIT_REGISTRY: WeakKeyDictionary["JudgeConsistencyAudit", _AuditRegistration] = WeakKeyDictionary()


class JudgeConsistencyAudit:
    __slots__ = ("formation_date", "stable", "mismatches", "primary_batch", "repeat_batch", "__hash", "__weakref__")
    def __init__(self, *args, **kwargs): raise TypeError("consistency audit is produced by the judge")
    @property
    def audit_hash(self): return self.__hash


def _make_consistency_audit(day, first, second, mismatches):
    value = object.__new__(JudgeConsistencyAudit)
    object.__setattr__(value, "formation_date", day.formation_date); object.__setattr__(value, "stable", not mismatches)
    object.__setattr__(value, "mismatches", mismatches); object.__setattr__(value, "primary_batch", first); object.__setattr__(value, "repeat_batch", second)
    digest = _stable_hash({
        "date": day.formation_date, "first": first.batch_hash, "second": second.batch_hash,
        "mismatches": mismatches, "stable": not mismatches,
    })
    object.__setattr__(value, "_JudgeConsistencyAudit__hash", digest)
    _AUDIT_REGISTRY[value] = _AuditRegistration(id(day), id(first), id(second), digest)
    return value


def _require_audit(value, *, allow_test_only=False):
    if type(value) is not JudgeConsistencyAudit or value not in _AUDIT_REGISTRY: raise JudgeError("consistency audit lacks verified provenance")
    reg = _AUDIT_REGISTRY[value]
    require_verified_judgment_batch(value.primary_batch, allow_test_only=allow_test_only)
    require_verified_judgment_batch(value.repeat_batch, allow_test_only=allow_test_only)
    first_day = getattr(value.primary_batch, "_VerifiedJudgmentBatch__day", None)
    second_day = getattr(value.repeat_batch, "_VerifiedJudgmentBatch__day", None)
    if id(first_day) != reg.day_id or first_day is not second_day:
        raise JudgeError("consistency audit mixes day packets")
    if (
        value.primary_batch.receipt.role != "primary"
        or value.repeat_batch.receipt.role != "consistency_repeat"
        or value.primary_batch.receipt.input_sha256 != value.repeat_batch.receipt.input_sha256
        or value.primary_batch.receipt.run_config_hash != value.repeat_batch.receipt.run_config_hash
        or value.primary_batch.receipt.run_commitment_hash != value.repeat_batch.receipt.run_commitment_hash
    ):
        raise JudgeError("consistency audit mixes run/input roles")
    expected_mismatches = _consistency_mismatches(
        value.primary_batch.output, value.repeat_batch.output
    )
    if tuple(value.mismatches) != expected_mismatches or value.stable != (not expected_mismatches):
        raise JudgeError("consistency audit semantic state mismatch")
    digest = _stable_hash({
        "date": value.formation_date, "first": value.primary_batch.batch_hash,
        "second": value.repeat_batch.batch_hash, "mismatches": value.mismatches,
        "stable": value.stable,
    })
    if id(value.primary_batch) != reg.first_id or id(value.repeat_batch) != reg.second_id or digest != reg.hash or value.audit_hash != reg.hash: raise JudgeError("consistency audit hash mismatch")
    return value


class ThreeDateConsistencyGate:
    __slots__ = ("audits", "gate_hash", "__preimage", "__weakref__")
    def __init__(self, *args, **kwargs): raise TypeError("gate is produced by its builder")
    @property
    def receipt_preimage(self): return json.loads(_canonical_json(self.__preimage))


_GATE_REGISTRY: WeakKeyDictionary[ThreeDateConsistencyGate, tuple[tuple[int, ...], str]] = WeakKeyDictionary()


def build_three_date_consistency_gate(audits):
    values = tuple(audits)
    if len(values) != 3: raise JudgeError("three fixed smoke dates are required")
    verified = tuple(_require_audit(item) for item in values)
    if tuple(sorted(item.formation_date for item in verified)) != _SMOKE_DATES: raise JudgeError("three fixed smoke dates are required")
    if any(not item.stable for item in verified): raise JudgeError("three-date consistency gate is unstable")
    if len({item.primary_batch.receipt.run_config_hash for item in verified}) != 1:
        raise JudgeError("three-date consistency gate mixes frozen judge runs")
    if len({item.primary_batch.receipt.run_commitment_hash for item in verified}) != 1:
        raise JudgeError("three-date consistency gate mixes run commitments")
    preimage = {
        "schema": "v3-three-date-consistency-gate-v1",
        "smoke_dates": _SMOKE_DATES,
        "audit_hashes": tuple(item.audit_hash for item in verified),
    }
    gate = object.__new__(ThreeDateConsistencyGate); object.__setattr__(gate, "audits", verified)
    object.__setattr__(gate, "_ThreeDateConsistencyGate__preimage", preimage)
    object.__setattr__(gate, "gate_hash", _stable_hash(preimage))
    _GATE_REGISTRY[gate] = (tuple(id(item) for item in verified), gate.gate_hash)
    return gate


def require_verified_three_date_consistency_gate(value):
    if type(value) is not ThreeDateConsistencyGate or value not in _GATE_REGISTRY:
        raise JudgeError("three-date gate lacks verified provenance")
    identities, digest = _GATE_REGISTRY[value]
    if tuple(id(item) for item in value.audits) != identities:
        raise JudgeError("three-date gate audit identity changed")
    verified = tuple(_require_audit(item) for item in value.audits)
    if len({item.primary_batch.receipt.run_config_hash for item in verified}) != 1:
        raise JudgeError("three-date consistency gate mixes frozen judge runs")
    if len({item.primary_batch.receipt.run_commitment_hash for item in verified}) != 1:
        raise JudgeError("three-date consistency gate mixes run commitments")
    preimage = {
        "schema": "v3-three-date-consistency-gate-v1",
        "smoke_dates": _SMOKE_DATES,
        "audit_hashes": tuple(item.audit_hash for item in verified),
    }
    stored = getattr(value, "_ThreeDateConsistencyGate__preimage", None)
    if preimage != stored or _stable_hash(preimage) != digest or value.gate_hash != digest:
        raise JudgeError("three-date gate hash mismatch")
    return value


def _validate_output(output, day):
    if output.formation_date != day.formation_date: raise ValueError("formation date differs")
    expected = {item.security_id for item in day.candidates}; observed = {item.security_id for item in output.candidates}
    if expected != observed: raise ValueError("candidate set differs from formation input")
    packets = {item.security_id: item for item in day.candidates}
    outputs = {item.security_id: item for item in output.candidates}
    _validate_daily_comparison_evidence(output, packets)
    for security_id, candidate in outputs.items():
        _validate_candidate(candidate, packets[security_id], outputs, day, packets)


def _validate_daily_comparison_evidence(output, packets):
    evidence_by = {
        security_id: {
            item.evidence_id: item
            for item in (*packet.api_facts, *packet.local_observations)
        }
        for security_id, packet in packets.items()
    }
    for stage in output.comparison_stage_receipts:
        for cohort in stage.cohorts:
            evidence = {
                evidence_id: datum
                for security_id in cohort.security_ids
                for evidence_id, datum in evidence_by[security_id].items()
            }
            texts = [cohort.judgment, cohort.reversal_fact]
            texts.extend(
                text
                for edge in cohort.decisive_edges
                for text in (edge.judgment, edge.reversal_fact)
            )
            for item in texts:
                _validate_judgment_language(item.text)
                if not set(item.evidence_ids).issubset(evidence):
                    raise ValueError("comparison receipt cites evidence outside its full cohort")
                _validate_numeric_text(item, evidence)
        for assessment in stage.cross_opportunity_assessments:
            evidence = evidence_by[assessment.security_id]
            for item in (assessment.independent_role, assessment.reversal_fact):
                _validate_judgment_language(item.text)
                if not set(item.evidence_ids).issubset(evidence):
                    raise ValueError("independent-role receipt cites another candidate's evidence")
                _validate_numeric_text(item, evidence)
        for pair in stage.exposure_pair_receipts:
            evidence = {
                **evidence_by[pair.left_security_id],
                **evidence_by[pair.right_security_id],
            }
            for item in (pair.judgment, pair.reversal_fact):
                _validate_judgment_language(item.text)
                if not set(item.evidence_ids).issubset(evidence):
                    raise ValueError("exposure-pair receipt cites evidence outside its pair")
                _validate_numeric_text(item, evidence)
    for tie in output.capacity_tie_abstentions:
        evidence = {
            evidence_id: datum
            for security_id in tie.security_ids
            for evidence_id, datum in evidence_by[security_id].items()
        }
        for item in (tie.judgment, tie.reversal_fact):
            _validate_judgment_language(item.text)
            if not set(item.evidence_ids).issubset(evidence):
                raise ValueError("capacity tie receipt cites evidence outside its group")
            _validate_numeric_text(item, evidence)


def _validate_candidate(candidate, packet, outputs, day, packets=None):
    packets = packets or {candidate.security_id: packet}
    evidence = {item.evidence_id: item for item in (*packet.api_facts, *packet.local_observations)}
    card = next((item for item in packet.opportunity_cards if item.opportunity is candidate.primary_opportunity), None)
    if card is None:
        raise ValueError("primary opportunity lacks an upstream evidence card")
    source = next(
        (
            item for item in day.card_statuses_for(packet.security_id)
            if item.opportunity is candidate.primary_opportunity
        ),
        None,
    )
    if source is None or candidate.card_status_source != source or candidate.card_status is not source.status:
        raise ValueError("judgment card status provenance differs from the verified formation input")
    if candidate.hotspot_memberships != day.hotspot_memberships_for(packet.security_id):
        raise ValueError("candidate hotspot identity differs from verified membership evidence")
    bindings = dict(card.requirement_evidence_ids)
    dispositions = {item.requirement: item for item in candidate.requirement_dispositions}
    if candidate.card_status is JudgmentCardStatus.READY:
        if set(bindings) != set(dispositions):
            raise ValueError("selected opportunity requirement bindings are incomplete")
    else:
        if (
            set(dispositions) != set(card.missing_requirements)
            or candidate.overall_disposition is not RequirementDispositionType.UNKNOWN
            or candidate.decisive_advantages
            or any(
                item.disposition is not RequirementDispositionType.UNKNOWN
                or item.judgment.evidence_ids
                for item in dispositions.values()
            )
        ):
            raise ValueError("nonready card must preserve every missing requirement as unknown")
    all_bound = set()
    for requirement, ids in bindings.items():
        if set(dispositions[requirement].judgment.evidence_ids) != set(ids): raise ValueError("requirement bindings differ from selected card")
        all_bound.update(ids)
    core = (candidate.proposition.why_now, candidate.proposition.target_conditions, candidate.decisive_comparison.judgment)
    if candidate.card_status is JudgmentCardStatus.READY and any(
        not all_bound.issubset(item.evidence_ids) for item in core
    ):
        raise ValueError("primary/decisive judgment must cite every selected-card binding")
    if candidate.suggested_layer in (CandidateLayer.FOCUS, CandidateLayer.HIGH_ELASTICITY):
        if not candidate.decisive_advantages or any(item.disposition is not RequirementDispositionType.SUPPORTIVE for item in dispositions.values()):
            raise ValueError("action-oriented layer requires supportive bindings and decisive advantage")
        if candidate.overall_disposition is not RequirementDispositionType.SUPPORTIVE:
            raise ValueError("action-oriented layer requires a supportive overall disposition")
    elif candidate.suggested_layer is CandidateLayer.EARLY_VALIDATION:
        if candidate.overall_disposition is not RequirementDispositionType.SUPPORTIVE:
            raise ValueError("early-validation layer requires a supportive directional thesis")
        if not any(item.disposition is RequirementDispositionType.SUPPORTIVE for item in dispositions.values()):
            raise ValueError("early-validation layer requires at least one supportive requirement")
    if candidate.primary_opportunity is not candidate.proposition.primary_opportunity: raise ValueError("primary opportunity differs")
    for factor in candidate.supporting_factors:
        if factor not in (DiscoveryRoute.HOTSPOT, DiscoveryRoute.PRICE_ANOMALY) or factor not in packet.discovery_routes: raise ValueError("invalid supporting factor")
    comparator_ids = set(candidate.decisive_comparison.comparator_security_ids)
    ready_comparator_ids = {
        security_id
        for security_id, other in outputs.items()
        if security_id != candidate.security_id
        and other.card_status is JudgmentCardStatus.READY
    }
    if not comparator_ids.issubset(ready_comparator_ids):
        raise ValueError("comparison cites an unknown or nonready candidate")
    same_opportunity = {
        security_id
        for security_id, other in outputs.items()
        if security_id != candidate.security_id
        and other.card_status is JudgmentCardStatus.READY
        and other.primary_opportunity is candidate.primary_opportunity
    }
    comparison_evidence = dict(evidence)
    comparator_bound = set()
    for security_id in comparator_ids:
        comparator_packet = packets.get(security_id)
        if comparator_packet is None:
            raise ValueError("comparison lacks the comparator evidence packet")
        comparison_evidence.update({
            item.evidence_id: item
            for item in (*comparator_packet.api_facts, *comparator_packet.local_observations)
        })
        comparator_card = next(
            (
                item
                for item in comparator_packet.opportunity_cards
                if item.opportunity is outputs[security_id].primary_opportunity
                and item.status is EvidenceCardStatus.EVIDENCE_READY_FOR_JUDGMENT
            ),
            None,
        )
        if comparator_card is None:
            raise ValueError("comparison candidate lacks its selected ready opportunity card")
        comparator_bound.update(
            evidence_id
            for _, evidence_ids in comparator_card.requirement_evidence_ids
            for evidence_id in evidence_ids
        )
    if same_opportunity and candidate.suggested_layer in (
        CandidateLayer.FOCUS, CandidateLayer.HIGH_ELASTICITY
    ):
        if not same_opportunity.issubset(comparator_ids):
            raise ValueError("comparison must include the full same-opportunity cohort")
        if candidate.decisive_comparison.comparison_role is not ComparisonRole.SAME_OPPORTUNITY_PEER:
            raise ValueError("comparison role differs from same-opportunity cohort")
    elif not same_opportunity and candidate.decisive_comparison.comparison_role is not ComparisonRole.NO_SAME_OPPORTUNITY_PEER:
            raise ValueError("comparison role must state that no same-opportunity peer exists")
    if comparator_ids and not comparator_bound.issubset(
        candidate.decisive_comparison.judgment.evidence_ids
    ):
        raise ValueError("decisive comparison omits comparator-side evidence")
    sections = {item.name: item for item in packet.sections}
    for receipt, expected_name in (
        (candidate.market_effect, EvidenceSectionName.MARKET_CONSTRAINTS),
        (candidate.hotspot_effect, EvidenceSectionName.HOTSPOT_PANORAMA),
    ):
        section = sections[expected_name]
        if (
            receipt.source_section is not expected_name
            or receipt.section_availability is not section.availability
            or receipt.source_section_hash != _stable_hash(section.model_dump(mode="json"))
        ):
            raise ValueError("market/hotspot context receipt differs from its dedicated section")
        if section.availability is EvidenceAvailability.EVIDENCE_READY_FOR_JUDGMENT:
            if not set(receipt.judgment.evidence_ids).issubset(section.evidence_ids):
                raise ValueError("context judgment cites evidence outside its dedicated section")
        elif receipt.judgment.evidence_ids:
            raise ValueError("unavailable context section cannot cite evidence")
        if not set(receipt.consequence_evidence_ids).issubset(evidence):
            raise ValueError("context consequence cites unknown company evidence")
    price_section = sections[EvidenceSectionName.PRICE_VOLUME_LIQUIDITY]
    if (
        candidate.price_role.source_section is not EvidenceSectionName.PRICE_VOLUME_LIQUIDITY
        or candidate.price_role.section_availability is not price_section.availability
        or candidate.price_role.source_section_hash
        != _stable_hash(price_section.model_dump(mode="json"))
    ):
        raise ValueError("price role differs from the dedicated price section")
    if not set(candidate.price_role.judgment.evidence_ids).issubset(
        price_section.evidence_ids
    ):
        raise ValueError("price role cites evidence outside the dedicated price section")
    if any(item.source_section is not EvidenceSectionName.COUNTEREVIDENCE for item in candidate.counterevidence):
        raise ValueError("counterevidence must identify the counterevidence section")
    if any(item.source_section is not EvidenceSectionName.UNKNOWNS for item in candidate.unknowns):
        raise ValueError("unknowns must identify the unknowns section")
    if any(
        item.disposition is ConsideredDispositionType.PRESENT
        and not item.judgment.evidence_ids
        for item in candidate.counterevidence
    ):
        raise ValueError("present counterevidence requires evidence ids")
    expected_counterevidence = set(
        sections[EvidenceSectionName.COUNTEREVIDENCE].evidence_ids
    )
    observed_counterevidence = {
        evidence_id
        for item in candidate.counterevidence
        for evidence_id in item.judgment.evidence_ids
    }
    if observed_counterevidence != expected_counterevidence:
        raise ValueError("counterevidence section receipt differs from Task5")
    if expected_counterevidence and (
        len(candidate.counterevidence) != len(expected_counterevidence)
        or any(len(item.judgment.evidence_ids) != 1 for item in candidate.counterevidence)
    ):
        raise ValueError("counterevidence section requires one disposition per evidence id")
    if not expected_counterevidence and (
        len(candidate.counterevidence) != 1
        or candidate.counterevidence[0].disposition is not ConsideredDispositionType.NONE_SUPPORTED
        or candidate.counterevidence[0].judgment.evidence_ids
        or candidate.counterevidence[0].judgment.text != _EMPTY_COUNTEREVIDENCE_TEXT
    ):
        raise ValueError("empty counterevidence section requires one none-supported placeholder")
    expected_unknowns = set(sections[EvidenceSectionName.UNKNOWNS].evidence_ids)
    expected_unknowns.update(
        evidence_id for item in packet.unknowns for evidence_id in item.evidence_ids
    )
    observed_unknowns = {
        evidence_id
        for item in candidate.unknowns
        for evidence_id in item.judgment.evidence_ids
    }
    if observed_unknowns != expected_unknowns:
        raise ValueError("unknown section receipt differs from Task5")
    if expected_unknowns and (
        len(candidate.unknowns) != len(expected_unknowns)
        or any(len(item.judgment.evidence_ids) != 1 for item in candidate.unknowns)
    ):
        raise ValueError("unknown section requires one disposition per evidence id")
    if not expected_unknowns and (
        len(candidate.unknowns) != 1
        or candidate.unknowns[0].disposition is not ConsideredDispositionType.UNKNOWN
        or candidate.unknowns[0].judgment.evidence_ids
        or candidate.unknowns[0].judgment.text != _EMPTY_UNKNOWNS_TEXT
    ):
        raise ValueError("empty unknown section requires one unknown placeholder")
    if candidate.suggested_layer is not CandidateLayer.INTERNAL:
        if not candidate.new_driver_evidence_ids:
            raise ValueError("non-internal judgment requires explicit new-driver evidence ids")
        drivers = set(candidate.new_driver_evidence_ids)
        supportive_bound = set()
        non_supportive_bound = set()
        for requirement, disposition in dispositions.items():
            target = (
                supportive_bound
                if disposition.disposition is RequirementDispositionType.SUPPORTIVE
                else non_supportive_bound
            )
            target.update(bindings[requirement])
        if not drivers.issubset(supportive_bound) or drivers.intersection(non_supportive_bound):
            raise ValueError("new-driver evidence must come only from supportive requirements")
        adverse_disposition_ids = {
            evidence_id
            for item in (*candidate.counterevidence, *candidate.unknowns)
            if item.disposition in (
                ConsideredDispositionType.PRESENT,
                ConsideredDispositionType.UNKNOWN,
            )
            for evidence_id in item.judgment.evidence_ids
        }
        if drivers.intersection(adverse_disposition_ids):
            raise ValueError("new-driver evidence conflicts with counterevidence or unknown disposition")
        directional_inputs = all_bound | expected_counterevidence | expected_unknowns
        if not directional_inputs.issubset(candidate.directional_thesis.evidence_ids):
            raise ValueError("directional thesis omits selected bindings, counterevidence, or unknowns")
        for judgment in (
            candidate.proposition.why_now,
            candidate.proposition.target_conditions,
            candidate.proposition.invalidation_condition,
        ):
            if not set(candidate.new_driver_evidence_ids).issubset(judgment.evidence_ids):
                raise ValueError("non-internal thesis does not bind driver, target, and invalidation")
    _validate_knowledge(candidate, packet, day)
    _validate_judgment_language(candidate.decisive_comparison.comparison_role)
    _validate_judgment_language(candidate.price_role.role)
    texts = _all_texts(candidate); cited = set()
    comparison_texts = {
        id(candidate.decisive_comparison.judgment),
        id(candidate.decisive_comparison.reversal_fact),
    }
    for item in texts:
        _validate_judgment_language(item.text)
        allowed_evidence = comparison_evidence if id(item) in comparison_texts else evidence
        unknown = set(item.evidence_ids).difference(allowed_evidence)
        if unknown: raise ValueError("judgment cites unknown evidence")
        _validate_numeric_text(item, allowed_evidence); cited.update(item.evidence_ids)
    cited.update(
        evidence_id
        for receipt in (candidate.market_effect, candidate.hotspot_effect)
        for evidence_id in receipt.consequence_evidence_ids
    )
    for item in candidate.unused_prepared_knowledge:
        cited.update(item.evidence_ids)
    if set(candidate.evidence_refs) != cited: raise ValueError("evidence receipt does not equal cited evidence")


def _validate_knowledge(candidate, packet, day):
    prepared = {item.knowledge_id: item for item in day.prepared_knowledge_for(packet.security_id)}
    if set(candidate.prepared_knowledge_ids) != set(prepared): raise ValueError("prepared knowledge receipt differs")
    used = {item.knowledge_id: item for item in candidate.actually_used_knowledge}
    unused = {item.knowledge_id: item for item in candidate.unused_prepared_knowledge}
    if set(prepared) != set(used).union(unused) or set(used).intersection(unused):
        raise ValueError("prepared knowledge must be partitioned into used and explicitly unused")
    positive_fields = {
        KnowledgeApplicationField.WHY_NOW,
        KnowledgeApplicationField.DECISIVE_ADVANTAGES,
        KnowledgeApplicationField.TARGET_CONDITIONS,
    }
    applied_field_evidence = {
        KnowledgeApplicationField.WHY_NOW: set(candidate.proposition.why_now.evidence_ids),
        KnowledgeApplicationField.DECISIVE_ADVANTAGES: {
            evidence_id for item in candidate.decisive_advantages for evidence_id in item.evidence_ids
        },
        KnowledgeApplicationField.TARGET_CONDITIONS: set(candidate.proposition.target_conditions.evidence_ids),
        KnowledgeApplicationField.COUNTEREVIDENCE: {
            evidence_id for item in candidate.counterevidence for evidence_id in item.judgment.evidence_ids
        },
        KnowledgeApplicationField.INVALIDATION: set(candidate.invalidation.evidence_ids),
    }
    for use in candidate.actually_used_knowledge:
        source = prepared.get(use.knowledge_id)
        if source is None: raise ValueError("knowledge use was not prepared")
        exact = (
            use.entry_content_hash == source.entry_content_hash and use.effect is source.effect
            and use.prepared_purpose == source.prepared_purpose and use.allowed_use_hash == source.allowed_use_hash
            and use.selected_allowed_use == source.selected_allowed_use
            and set(use.satisfied_prerequisites) == set(source.prerequisites)
            and set(use.considered_counterevidence) == set(source.counter_evidence)
            and set(use.use_summary.evidence_ids).issubset(source.evidence_ids)
        )
        if not exact: raise ValueError("knowledge use receipt differs from prepared knowledge")
        if source.effect is not KnowledgeEffect.ANALYSIS_EVIDENCE and positive_fields.intersection(use.applied_to_fields):
            raise ValueError("non-analysis knowledge cannot create a positive opportunity")
        used_evidence = set(use.use_summary.evidence_ids)
        for field in use.applied_to_fields:
            if field is KnowledgeApplicationField.METHOD:
                continue
            if not used_evidence or not used_evidence.issubset(applied_field_evidence[field]):
                raise ValueError("knowledge applied-to field lacks the same evidence binding")
    for nonuse in candidate.unused_prepared_knowledge:
        source = prepared.get(nonuse.knowledge_id)
        if source is None:
            raise ValueError("unused knowledge was not prepared")
        if source.effect is KnowledgeEffect.HARD_BOUNDARY:
            raise ValueError("hard-boundary knowledge must be actually used")
        if (
            nonuse.entry_content_hash != source.entry_content_hash
            or nonuse.effect is not source.effect
            or set(nonuse.evidence_ids) != set(source.evidence_ids)
        ):
            raise ValueError("unused knowledge receipt differs from prepared knowledge")


def _all_texts(candidate):
    proposition = candidate.proposition
    return (
        candidate.market_effect.judgment, candidate.hotspot_effect.judgment,
        candidate.price_role.judgment, candidate.next_validation_state.judgment,
        proposition.why_now, proposition.next_validation, proposition.post_fact_price_response,
        proposition.price_confirmation, proposition.target_conditions, proposition.invalidation_condition,
        *(item.judgment for item in candidate.requirement_dispositions), *candidate.decisive_advantages,
        candidate.decisive_comparison.judgment, candidate.decisive_comparison.reversal_fact,
        *(item.judgment for item in candidate.counterevidence), *(item.judgment for item in candidate.unknowns),
        candidate.directional_thesis, candidate.next_fact, candidate.invalidation,
        *(item.use_summary for item in candidate.actually_used_knowledge),
    )


def _validate_judgment_language(text):
    normalized = unicodedata.normalize("NFKC", text)
    if "%" in normalized or _RATIO.search(normalized) or _CHINESE_QUANTITY.search(normalized): raise ValueError("unsupported quantity expression")
    if any(re.search(pattern, normalized, flags=re.IGNORECASE) for pattern in _FORBIDDEN_LANGUAGE): raise ValueError("forbidden predictive, scoring, or trader-identity language")


def _validate_numeric_text(item, evidence):
    normalized = unicodedata.normalize("NFKC", item.text)
    tokens = _ASCII_NUMBER.findall(normalized)
    allowed = {str(evidence[eid].value) for eid in item.evidence_ids if isinstance(evidence[eid].value, (int, float, Decimal)) and not isinstance(evidence[eid].value, bool)}
    if any(token not in allowed for token in tokens): raise ValueError("unsupported numeric value")


def _consistency_mismatches(first, second):
    first_by = {item.security_id: item for item in first.candidates}; second_by = {item.security_id: item for item in second.candidates}; mismatches=[]
    if set(first_by) != set(second_by): return (f"candidate_set:{sorted(first_by)}->{sorted(second_by)}",)
    if first.comparison_stage_receipts != second.comparison_stage_receipts:
        mismatches.append("daily:comparison_stage_receipts")
    if first.capacity_tie_abstentions != second.capacity_tie_abstentions:
        mismatches.append("daily:capacity_tie_abstentions")
    for security_id in sorted(first_by):
        left, right = first_by[security_id], second_by[security_id]
        if left.primary_opportunity is not right.primary_opportunity: mismatches.append(f"{security_id}:primary_opportunity:{left.primary_opportunity.value}->{right.primary_opportunity.value}")
        if left.suggested_layer is not right.suggested_layer: mismatches.append(f"{security_id}:suggested_layer:{left.suggested_layer.value}->{right.suggested_layer.value}")
        if (
            left.overall_disposition is not right.overall_disposition
            or left.requirement_dispositions != right.requirement_dispositions
            or left.directional_thesis != right.directional_thesis
            or left.new_driver_evidence_ids != right.new_driver_evidence_ids
            or left.counterevidence != right.counterevidence
            or left.unknowns != right.unknowns
            or left.actually_used_knowledge != right.actually_used_knowledge
            or left.unused_prepared_knowledge != right.unused_prepared_knowledge
            or left.proposition.target_conditions != right.proposition.target_conditions
            or left.proposition.invalidation_condition != right.proposition.invalidation_condition
            or left.market_effect != right.market_effect
            or left.hotspot_effect != right.hotspot_effect
            or left.hotspot_memberships != right.hotspot_memberships
            or left.card_status != right.card_status
            or left.card_status_source != right.card_status_source
            or left.price_role != right.price_role
            or left.next_validation_state != right.next_validation_state
            or left.capacity_tie_abstention is not right.capacity_tie_abstention
        ):
            mismatches.append(f"{security_id}:directional_signature")
        if (
            left.decisive_advantages != right.decisive_advantages
            or left.decisive_comparison != right.decisive_comparison
        ):
            mismatches.append(f"{security_id}:decisive_comparison")
    return tuple(mismatches)


def _validation_code(exc):
    if isinstance(exc, ValidationError):
        first = exc.errors(include_input=False, include_url=False)[0]
        path = ".".join(str(part) for part in first["loc"][:8])[:256]
        return "schema:" + (path or "root")
    message = str(exc).lower()
    controlled = (
        ("formation date", "formation_date"),
        ("candidate set", "candidate_set"),
        ("primary opportunity", "primary_opportunity"),
        ("requirement", "requirement_bindings"),
        ("directional thesis", "directional_thesis"),
        ("new-driver", "new_driver"),
        ("action-oriented", "candidate_layer"),
        ("early-validation", "candidate_layer"),
        ("comparison", "comparison"),
        ("counterevidence", "counterevidence_section"),
        ("unknown", "unknowns_section"),
        ("knowledge", "knowledge_use"),
        ("evidence receipt", "evidence_receipt"),
        ("language", "language_policy"),
        ("numeric", "numeric_policy"),
        ("quantity", "numeric_policy"),
    )
    code = next((code for marker, code in controlled if marker in message), "unclassified")
    return "semantic:" + code


def _codex_environment():
    allowed = ("HOME", "PATH", "TMPDIR", "CODEX_HOME", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "all_proxy", "no_proxy")
    return {key: os.environ[key] for key in allowed if os.environ.get(key)}


def _canonical_json(value): return json.dumps(_jsonable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
def _stable_hash(value): return _sha256_text(_canonical_json(value))
def _sha256_text(value): return hashlib.sha256(value.encode()).hexdigest()
def _jsonable(value):
    if isinstance(value, Mapping): return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)): return [_jsonable(item) for item in value]
    if isinstance(value, (date, datetime)): return value.isoformat()
    if isinstance(value, Decimal): return str(value)
    if isinstance(value, StrEnum): return value.value
    if hasattr(value, "value") and isinstance(value.value, str): return value.value
    return value


__all__ = [
    "CandidateJudgment", "CapacityTieAbstention", "CardStatusSourceReceipt",
    "CoverageCauseReceipt", "RequirementGapSourceReceipt",
    "CitedContextEffect", "CitedPriceRole", "CitedValidationState",
    "ComparisonCohortReceipt", "ComparisonStageReceipt",
    "CrossOpportunityAssessment", "ExposurePairReceipt", "HotspotMembershipReceipt",
    "DailyJudgeOutput",
    "DecisiveComparison", "DecisiveEdge",
    "FrozenDecisionJudge", "FrozenJudgeConfig", "JudgmentCacheKey",
    "JudgeConsistencyAudit", "JudgeDayPacket", "JudgeError", "JudgeInstabilityError",
    "JudgePreflightReceipt", "PreparedKnowledgeInput", "SelectionPropositionJudgment",
    "ThreeDateConsistencyGate", "VerifiedJudgmentBatch", "build_judge_day_packet",
    "build_three_date_consistency_gate", "lookup_judgment_cache",
    "require_verified_judge_day_packet",
    "require_verified_judgment_batch", "require_verified_three_date_consistency_gate",
]
