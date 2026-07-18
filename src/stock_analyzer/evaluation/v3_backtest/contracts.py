"""Strict formation-time contracts for the isolated V3 backtest."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)


NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
PositiveDecimal = Annotated[Decimal, Field(gt=0, allow_inf_nan=False)]


class DiscoveryRoute(StrEnum):
    """The six frozen, high-recall discovery entries."""

    HOTSPOT = "hotspot"
    EARNINGS = "earnings"
    COMPANY_EVENT = "company_event"
    INDUSTRY_CYCLE = "industry_cycle"
    DISTRESS_REPAIR = "distress_repair"
    PRICE_ANOMALY = "price_anomaly"


class OpportunityType(StrEnum):
    """Real repricing sources; attention and price moves are deliberately absent."""

    INDUSTRY_TREND = "industry_trend"
    EARNINGS_REVALUATION = "earnings_revaluation"
    SUPPLY_DEMAND_CYCLE = "supply_demand_cycle"
    COMPANY_EVENT_REVALUATION = "company_event_revaluation"
    DISTRESS_REVERSAL = "distress_reversal"


class CandidateLayer(StrEnum):
    INTERNAL = "internal"
    EARLY_VALIDATION = "early_validation"
    HIGH_ELASTICITY = "high_elasticity_tracking"
    FOCUS = "focus"


class ProjectState(StrEnum):
    ACTIVE = "active"
    TARGET_TOUCHED = "target_touched"
    INVALIDATED = "invalidated"
    REPLACED = "replaced"
    EXPIRED = "expired"


class EvidenceKind(StrEnum):
    API_FACT = "api_fact"
    LOCAL_OBSERVATION = "local_observation"
    MODEL_JUDGMENT = "model_judgment"


class EvidenceCardStatus(StrEnum):
    """Formation-date executability of an opportunity evidence card."""

    READY = "ready"
    INSUFFICIENT_AS_OF_CUTOFF = "insufficient_as_of_cutoff"
    NOT_EXECUTABLE_WITH_LOCAL_DATA = "not_executable_with_local_data"


class ContextEffect(StrEnum):
    """How market or hotspot context changes a candidate judgment."""

    SUPPORTS_CURRENT_OPPORTUNITY = "supports_current_opportunity"
    RAISES_COMPANY_EVIDENCE_BAR = "raises_company_evidence_bar"
    LIMITS_FOCUS = "limits_focus"
    ACCELERATES_INVALIDATION_CHECK = "accelerates_invalidation_check"
    NOT_APPLICABLE = "not_applicable"
    OPPOSES_CAUSAL_CHAIN = "opposes_causal_chain"


class ValidationDisposition(StrEnum):
    """As-of-date state of the project's preregistered next validation."""

    SATISFIED = "satisfied"
    UNMET = "unmet"
    NEGATED = "negated"
    NOT_OBSERVABLE_AS_OF_DATE = "not_observable_as_of_date"


class ComparisonStage(StrEnum):
    """Frozen order for non-scoring candidate comparisons."""

    SAME_HOTSPOT_OPPORTUNITY_ROLE = "same_hotspot_opportunity_role"
    SAME_OPPORTUNITY_CROSS_CONTEXT = "same_opportunity_cross_context"
    CROSS_OPPORTUNITY = "cross_opportunity"


class PriceRole(StrEnum):
    """Closed formation-date price roles used by stage-one comparison."""

    STRONG_LEADER = "strong_leader"
    BALANCED_START = "balanced_start"
    OTHER_TRADABLE = "other_tradable"


class ProjectDayCheckpoint(StrEnum):
    """Closed cache/lifecycle checkpoint vocabulary; arbitrary spellings are invalid."""

    ORDINARY = "ordinary"
    DAY_5 = "day_5"
    DAY_10 = "day_10"
    DAY_20 = "day_20"
    DAY_30 = "day_30"


class _FrozenContract(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_default=True,
    )


def _validate_formation_cutoff(value: datetime, formation_date: date) -> None:
    if value.utcoffset() is None:
        raise ValueError("formation cutoff must be timezone-aware")
    if value.utcoffset() != timedelta(hours=8):
        raise ValueError("formation cutoff must use the Asia/Shanghai UTC+08:00 offset")
    if value.date() != formation_date or value.timetz().replace(tzinfo=None) != time(23, 59, 59):
        raise ValueError("formation cutoff must be 23:59:59 on the formation date")


class EvidenceRef(_FrozenContract):
    """A traceable fact, deterministic observation, or model judgment reference."""

    evidence_id: NonEmptyStr
    kind: EvidenceKind
    dataset: NonEmptyStr
    business_time: datetime
    available_at: datetime
    input_hash: Sha256

    @field_validator("business_time", "available_at")
    @classmethod
    def require_aware_time(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("evidence timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def availability_cannot_precede_business_time(self) -> Self:
        if self.available_at < self.business_time:
            raise ValueError("available_at cannot precede business_time")
        return self


class SelectionProposition(_FrozenContract):
    """The seven-part, evidence-cited judgment used to compete for attention."""

    primary_opportunity: OpportunityType
    why_now: NonEmptyStr
    next_validation: NonEmptyStr
    post_fact_price_response: NonEmptyStr
    price_confirmation: NonEmptyStr
    target_conditions: NonEmptyStr
    invalidation_condition: NonEmptyStr
    evidence_ids: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]

    @field_validator("evidence_ids")
    @classmethod
    def evidence_ids_must_be_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("evidence_ids must be unique")
        return value


class CandidateProject(_FrozenContract):
    """An immutable project identity plus its current formation-time classification."""

    project_id: NonEmptyStr
    security_id: NonEmptyStr
    company_name: NonEmptyStr
    formation_date: date
    formation_cutoff: datetime
    discovery_baseline: PositiveDecimal
    discovery_routes: Annotated[tuple[DiscoveryRoute, ...], Field(min_length=1, max_length=6)]
    primary_opportunity: OpportunityType
    supporting_factor: DiscoveryRoute | None = None
    layer: CandidateLayer
    state: ProjectState = ProjectState.ACTIVE
    invalidation_condition: NonEmptyStr
    evidence_refs: Annotated[tuple[EvidenceRef, ...], Field(min_length=1)]
    proposition: SelectionProposition
    action_baseline: PositiveDecimal | None = None

    @field_validator("discovery_routes")
    @classmethod
    def discovery_routes_must_be_unique(
        cls, value: tuple[DiscoveryRoute, ...]
    ) -> tuple[DiscoveryRoute, ...]:
        if len(value) != len(set(value)):
            raise ValueError("discovery routes must be unique and do not constitute votes")
        return value

    @field_validator("supporting_factor")
    @classmethod
    def supporting_factor_is_not_a_second_opportunity(
        cls, value: DiscoveryRoute | None
    ) -> DiscoveryRoute | None:
        if value not in (None, DiscoveryRoute.HOTSPOT, DiscoveryRoute.PRICE_ANOMALY):
            raise ValueError("supporting factor may only describe hotspot attention or price response")
        return value

    @model_validator(mode="after")
    def enforce_project_invariants(self) -> Self:
        _validate_formation_cutoff(self.formation_cutoff, self.formation_date)

        if self.layer is CandidateLayer.FOCUS and self.action_baseline is None:
            raise ValueError("focus candidates require an action baseline")

        if self.proposition.primary_opportunity is not self.primary_opportunity:
            raise ValueError("proposition and project must use the same sole primary opportunity")

        if self.proposition.invalidation_condition != self.invalidation_condition:
            raise ValueError("project and proposition invalidation conditions must match")

        available_ids = [ref.evidence_id for ref in self.evidence_refs]
        if len(available_ids) != len(set(available_ids)):
            raise ValueError("evidence_id values must be unique within a project")

        future_ids = [
            ref.evidence_id
            for ref in self.evidence_refs
            if ref.available_at > self.formation_cutoff
        ]
        if future_ids:
            future = ", ".join(sorted(future_ids))
            raise ValueError(f"evidence became available after formation cutoff: {future}")

        missing_ids = set(self.proposition.evidence_ids).difference(available_ids)
        if missing_ids:
            missing = ", ".join(sorted(missing_ids))
            raise ValueError(f"judgment cites evidence_id values absent from project: {missing}")
        return self


class DailyDecision(_FrozenContract):
    """The zero-to-ten active candidate attention set for one formation day."""

    formation_date: date
    cutoff: datetime
    candidates: Annotated[tuple[CandidateProject, ...], Field(max_length=10)] = ()

    @model_validator(mode="after")
    def enforce_attention_limits(self) -> Self:
        _validate_formation_cutoff(self.cutoff, self.formation_date)

        project_ids = [candidate.project_id for candidate in self.candidates]
        if len(project_ids) != len(set(project_ids)):
            raise ValueError("daily candidates must have unique project_id values")

        security_ids = [candidate.security_id for candidate in self.candidates]
        if len(security_ids) != len(set(security_ids)):
            raise ValueError("a security may occupy at most one daily candidate slot")

        if any(candidate.layer is CandidateLayer.INTERNAL for candidate in self.candidates):
            raise ValueError("internal observations cannot occupy the ten candidate slots")

        if sum(candidate.layer is CandidateLayer.FOCUS for candidate in self.candidates) > 5:
            raise ValueError("a daily decision may contain at most five focus candidates")

        if any(candidate.state is not ProjectState.ACTIVE for candidate in self.candidates):
            raise ValueError("only active projects may occupy current candidate slots")

        if any(candidate.formation_date > self.formation_date for candidate in self.candidates):
            raise ValueError("a daily decision cannot contain a project formed in the future")
        return self


class RouteScanManifest(_FrozenContract):
    """Auditable coverage and result counts for one route on one formation day."""

    route: DiscoveryRoute
    formation_date: date
    cutoff: datetime
    requested_partitions: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]
    actual_partitions: tuple[NonEmptyStr, ...]
    expected_records: Annotated[int, Field(ge=0)]
    scanned_records: Annotated[int, Field(ge=0)]
    triggered_records: Annotated[int, Field(ge=0)]
    deduplicated_records: Annotated[int, Field(ge=0)]
    missing: tuple[NonEmptyStr, ...] = ()
    exclusions: tuple[NonEmptyStr, ...] = ()
    manual_boundaries: tuple[NonEmptyStr, ...] = ()
    deep_read_required: Annotated[int, Field(ge=0)] = 0
    deep_read_completed: Annotated[int, Field(ge=0)] = 0
    input_hash: Sha256

    @model_validator(mode="after")
    def counts_and_cutoff_must_be_consistent(self) -> Self:
        _validate_formation_cutoff(self.cutoff, self.formation_date)
        if len(self.requested_partitions) != len(set(self.requested_partitions)):
            raise ValueError("requested_partitions must be unique")
        if len(self.actual_partitions) != len(set(self.actual_partitions)):
            raise ValueError("actual_partitions must be unique")

        requested = set(self.requested_partitions)
        actual = set(self.actual_partitions)
        unrequested = actual.difference(requested)
        if unrequested:
            partitions = ", ".join(sorted(unrequested))
            raise ValueError(f"actual partitions were not requested: {partitions}")

        explained_partition_gaps = set(self.missing).union(self.exclusions)
        unexplained = requested.difference(actual, explained_partition_gaps)
        if unexplained:
            partitions = ", ".join(sorted(unexplained))
            raise ValueError(f"requested partitions lack coverage records: {partitions}")

        if self.scanned_records > self.expected_records:
            raise ValueError("scanned_records cannot exceed expected_records")
        if self.scanned_records < self.expected_records and not self.missing:
            raise ValueError("scan count shortfall requires an explicit missing coverage record")
        if self.triggered_records > self.scanned_records:
            raise ValueError("triggered_records cannot exceed scanned_records")
        if self.deduplicated_records > self.triggered_records:
            raise ValueError("deduplicated_records cannot exceed triggered_records")
        if self.deep_read_completed > self.deep_read_required:
            raise ValueError("deep_read_completed cannot exceed deep_read_required")
        return self


__all__ = [
    "CandidateLayer",
    "CandidateProject",
    "DailyDecision",
    "DiscoveryRoute",
    "EvidenceKind",
    "EvidenceRef",
    "OpportunityType",
    "ProjectState",
    "RouteScanManifest",
    "SelectionProposition",
]
