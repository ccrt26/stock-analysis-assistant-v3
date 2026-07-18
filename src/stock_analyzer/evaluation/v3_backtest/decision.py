"""Non-scoring research-pool compression for the isolated V3 backtest."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Literal, Self
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

import stock_analyzer.evaluation.v3_backtest.capability as capability_module
from stock_analyzer.evaluation.v3_backtest.capability import CapabilityReceipt
from stock_analyzer.evaluation.v3_backtest.contracts import (
    CandidateLayer,
    CandidateProject,
    ComparisonStage,
    DailyDecision,
    DiscoveryRoute,
    EvidenceCardStatus,
    OpportunityType,
    PriceRole,
    ProjectState,
)
from stock_analyzer.evaluation.v3_backtest.judge import (
    CandidateJudgment,
    CapacityTieAbstention,
    DailyJudgeOutput,
    ExposurePairReceipt,
    ExposureRelationship,
    JudgeError,
    RequirementDispositionType,
    VerifiedJudgmentBatch,
    require_verified_judgment_batch,
)


_SHANGHAI = ZoneInfo("Asia/Shanghai")
_FORBIDDEN_FORMATION_FIELDS = (
    "outcome",
    "future_price",
    "future_return",
    "future_high",
    "future_low",
    "future_close",
    "known_winner",
    "target_touched",
    "terminal_return",
)
_PRIMARY_ROUTE: Mapping[OpportunityType, DiscoveryRoute] = {
    OpportunityType.INDUSTRY_TREND: DiscoveryRoute.INDUSTRY_CYCLE,
    OpportunityType.EARNINGS_REVALUATION: DiscoveryRoute.EARNINGS,
    OpportunityType.SUPPLY_DEMAND_CYCLE: DiscoveryRoute.INDUSTRY_CYCLE,
    OpportunityType.COMPANY_EVENT_REVALUATION: DiscoveryRoute.COMPANY_EVENT,
    OpportunityType.DISTRESS_REVERSAL: DiscoveryRoute.DISTRESS_REPAIR,
}

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class DecisionError(RuntimeError):
    """A fail-closed violation of the frozen decision contract."""


class DecisionReason(StrEnum):
    NONREADY_CARD = "nonready_card"
    INTERNAL_SUGGESTED = "internal_suggested"
    INACTIVE_PROJECT = "inactive_project"
    DOMINATED = "dominated_by_verified_graph"
    CAPACITY_TIE = "capacity_tie_abstention"
    PRIMARY_ROUTE_MISSING = "primary_route_missing_from_project"
    PRIMARY_ROUTE_BLOCKED = "primary_route_not_executable"
    FINAL_GRAPH_NOT_ACTIONABLE = "final_graph_not_action_eligible"
    SHARED_EXPOSURE = "shared_exposure_incompatible"
    FOCUS_INCOMPLETE = "focus_contract_incomplete"
    UNRESOLVED_CAPACITY = "unresolved_capacity_boundary"
    SELECTED_FOCUS = "selected_focus"
    SELECTED_CANDIDATE = "selected_valid_candidate"
    RETAINED_INCUMBENT = "retained_active_incumbent"
    DECISIVE_CHALLENGER = "selected_decisive_challenger"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)


class ObjectDecision(_FrozenModel):
    project: CandidateProject
    security_id: NonEmptyStr
    judgment_layer: CandidateLayer
    decision_layer: CandidateLayer
    occupies_attention_capacity: bool
    is_incumbent: bool
    reasons: Annotated[tuple[DecisionReason, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def bind_identity_and_capacity(self) -> Self:
        if self.project.security_id != self.security_id:
            raise ValueError("object decision security identity differs from project")
        if self.occupies_attention_capacity != (
            self.decision_layer is not CandidateLayer.INTERNAL
        ):
            raise ValueError("object decision capacity differs from final layer")
        return self


class StageGraphHash(_FrozenModel):
    stage: ComparisonStage
    graph_hash: Sha256


class CapacityBoundaryAbstention(_FrozenModel):
    security_ids: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]
    reason: Literal["unresolved_capacity_boundary"]
    source_graph_hash: Sha256

    @model_validator(mode="after")
    def require_unique_group(self) -> Self:
        if len(self.security_ids) != len(set(self.security_ids)):
            raise ValueError("capacity boundary group must contain unique identities")
        return self


class ReplacementSuggestion(_FrozenModel):
    challenger_security_id: NonEmptyStr
    incumbent_security_id: NonEmptyStr
    source_stage: ComparisonStage
    decisive_evidence_ids: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]
    reversal_evidence_ids: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]
    actual_state_change_deferred_to_lifecycle: Literal[True] = True

    @model_validator(mode="after")
    def require_distinct_pair(self) -> Self:
        if self.challenger_security_id == self.incumbent_security_id:
            raise ValueError("replacement endpoints must differ")
        return self


class UpstreamInternalExclusion(_FrozenModel):
    security_id: NonEmptyStr
    reason: NonEmptyStr


class DecisionReceipt(_FrozenModel):
    daily_decision: DailyDecision
    object_decisions: tuple[ObjectDecision, ...]
    internal_research_pool: tuple[NonEmptyStr, ...]
    judgment_batch_hash: Sha256
    capability_receipt_hash: Sha256
    comparison_graph_hashes: Annotated[
        tuple[StageGraphHash, ...], Field(min_length=3, max_length=3)
    ]
    exposure_receipts: tuple[ExposurePairReceipt, ...]
    verified_capacity_ties: tuple[CapacityTieAbstention, ...]
    capacity_tied_security_ids: tuple[NonEmptyStr, ...]
    capacity_boundary_abstentions: tuple[CapacityBoundaryAbstention, ...]
    unselected_challengers: tuple[NonEmptyStr, ...]
    replacement_suggestions: tuple[ReplacementSuggestion, ...]
    upstream_internal_exclusions: tuple[UpstreamInternalExclusion, ...]
    order_is_canonical_not_ranked: Literal[True]
    source_attestation: Literal["verified_judgment_batch", "explicit_test_only"]
    content_hash: Sha256

    @model_validator(mode="after")
    def validate_receipt(self) -> Self:
        object_ids = tuple(item.security_id for item in self.object_decisions)
        if object_ids != tuple(sorted(object_ids)) or len(object_ids) != len(set(object_ids)):
            raise ValueError("object decisions must use unique canonical serialization order")
        selected = tuple(item.security_id for item in self.daily_decision.candidates)
        if selected != tuple(sorted(selected)):
            raise ValueError("daily decision order is canonical serialization, not ranking")
        expected_internal = tuple(
            item.security_id
            for item in self.object_decisions
            if item.decision_layer is CandidateLayer.INTERNAL
        )
        if self.internal_research_pool != expected_internal:
            raise ValueError("internal research pool differs from per-object decisions")
        expected = _stable_hash(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash != expected:
            raise ValueError("decision receipt content hash differs")
        return self


@dataclass(frozen=True, slots=True)
class _CapacityResolution:
    selected_security_ids: tuple[str, ...]
    boundary_abstentions: tuple[tuple[str, ...], ...]


def _resolve_attention_capacity(
    *,
    eligible_security_ids: Sequence[str],
    focus_security_ids: Sequence[str],
    incumbent_security_ids: Sequence[str],
    decisive_replacement_winners: Sequence[str],
) -> _CapacityResolution:
    """Apply only tier qualification, lifecycle continuity and all-or-none abstention.

    Sorting below is solely a canonical serialization step after membership is decided.
    No security identifier is used to choose a member of a capacity-contested group.
    """

    eligible = set(eligible_security_ids)
    focus = set(focus_security_ids)
    incumbents = set(incumbent_security_ids)
    replacement_winners = set(decisive_replacement_winners)
    if len(eligible) != len(tuple(eligible_security_ids)):
        raise DecisionError("eligible capacity identities must be unique")
    if not focus.issubset(eligible):
        raise DecisionError("focus identities must be eligible")
    if not incumbents.issubset(eligible):
        raise DecisionError("incumbent capacity identities must be eligible")
    if not replacement_winners.issubset(eligible.difference(incumbents)):
        raise DecisionError("decisive replacement winners must be eligible challengers")

    selected: set[str] = set()
    abstentions: list[tuple[str, ...]] = []

    focus_incumbents = focus.intersection(incumbents)
    if len(focus_incumbents) > 5:
        raise DecisionError("active focus incumbents exceed the frozen focus capacity")
    selected.update(focus_incumbents)
    focus_challengers = focus.difference(incumbents)
    focus_slots = 5 - len(focus_incumbents)
    decisive_focus = focus_challengers.intersection(replacement_winners)
    if len(decisive_focus) > focus_slots:
        abstentions.append(tuple(sorted(decisive_focus)))
        unresolved_focus = focus_challengers.difference(decisive_focus)
        if unresolved_focus:
            abstentions.append(tuple(sorted(unresolved_focus)))
        focus_boundary_blocked = True
    else:
        selected.update(decisive_focus)
        unresolved_focus = focus_challengers.difference(decisive_focus)
        focus_slots -= len(decisive_focus)
        focus_boundary_blocked = len(unresolved_focus) > focus_slots
        if focus_boundary_blocked:
            abstentions.append(tuple(sorted(unresolved_focus)))
        else:
            selected.update(unresolved_focus)

    selected.update(incumbents.difference(focus))
    if len(selected) > 10:
        raise DecisionError("active incumbents exceed the frozen candidate capacity")

    remaining = eligible.difference(selected)
    if focus_boundary_blocked:
        lower = remaining.difference(focus_challengers)
        if lower:
            abstentions.append(tuple(sorted(lower)))
        return _CapacityResolution(
            selected_security_ids=tuple(sorted(selected)),
            boundary_abstentions=tuple(abstentions),
        )

    slots = 10 - len(selected)
    decisive = replacement_winners.intersection(remaining)
    if len(decisive) > slots:
        abstentions.append(tuple(sorted(decisive)))
        unresolved = remaining.difference(decisive)
        if unresolved:
            abstentions.append(tuple(sorted(unresolved)))
        return _CapacityResolution(tuple(sorted(selected)), tuple(abstentions))
    selected.update(decisive)
    remaining.difference_update(decisive)
    slots = 10 - len(selected)
    if len(remaining) <= slots:
        selected.update(remaining)
    elif remaining:
        abstentions.append(tuple(sorted(remaining)))
    return _CapacityResolution(tuple(sorted(selected)), tuple(abstentions))


def compress_research_pool(
    judgment_batch: VerifiedJudgmentBatch,
    projects: Mapping[str, CandidateProject],
    capability_receipt: CapabilityReceipt,
    *,
    incumbent_project_ids: Sequence[str] = (),
) -> DecisionReceipt:
    """Compress a production-attested judgment batch; test-only batches are rejected."""

    try:
        verified = require_verified_judgment_batch(judgment_batch)
    except (JudgeError, TypeError, ValueError) as exc:
        raise DecisionError("judgment batch lacks production verified provenance") from exc
    capability = _require_capability_receipt(capability_receipt)
    exclusions = tuple(
        UpstreamInternalExclusion(security_id=item.security_id, reason=item.reason)
        for item in verified.exclusions
    )
    return _compress(
        verified.output,
        projects,
        capability,
        judgment_batch_hash=verified.batch_hash,
        incumbent_project_ids=incumbent_project_ids,
        upstream_exclusions=exclusions,
        source_attestation="verified_judgment_batch",
    )


def compress_research_pool_for_test(
    output: DailyJudgeOutput,
    projects: Mapping[str, CandidateProject],
    capability_receipt: CapabilityReceipt,
    *,
    judgment_batch_hash: str,
    incumbent_project_ids: Sequence[str] = (),
) -> DecisionReceipt:
    """Explicit synthetic-only seam; it cannot be enabled through the public entry."""

    if type(output) is not DailyJudgeOutput:
        raise DecisionError("test-only decision input must be a DailyJudgeOutput")
    try:
        validated_output = DailyJudgeOutput.model_validate(output.model_dump(mode="json"))
    except (TypeError, ValueError) as exc:
        raise DecisionError("test-only judgment output failed contract validation") from exc
    if not _is_sha256(judgment_batch_hash):
        raise DecisionError("test-only judgment batch hash must be SHA-256")
    capability = _require_capability_receipt(capability_receipt)
    return _compress(
        validated_output,
        projects,
        capability,
        judgment_batch_hash=judgment_batch_hash,
        incumbent_project_ids=incumbent_project_ids,
        upstream_exclusions=(),
        source_attestation="explicit_test_only",
    )


def _compress(
    output: DailyJudgeOutput,
    projects: Mapping[str, CandidateProject],
    capability: CapabilityReceipt,
    *,
    judgment_batch_hash: str,
    incumbent_project_ids: Sequence[str],
    upstream_exclusions: tuple[UpstreamInternalExclusion, ...],
    source_attestation: Literal["verified_judgment_batch", "explicit_test_only"],
) -> DecisionReceipt:
    _reject_future_fields(projects)
    project_by = _validate_projects(output, projects)
    incumbent_ids = tuple(incumbent_project_ids)
    if len(incumbent_ids) != len(set(incumbent_ids)):
        raise DecisionError("incumbent project identities must be unique")
    project_id_to_security = {item.project_id: item.security_id for item in project_by.values()}
    unknown_incumbents = set(incumbent_ids).difference(project_id_to_security)
    if unknown_incumbents:
        raise DecisionError("every incumbent must be rejudged in the current batch")
    incumbent_security_ids = {
        project_id_to_security[project_id] for project_id in incumbent_ids
    }
    older_projects = {
        security_id
        for security_id, project in project_by.items()
        if project.formation_date < output.formation_date
    }
    if not older_projects.issubset(incumbent_security_ids):
        raise DecisionError("every older project must be declared as an incumbent")
    if any(
        project_by[security_id].formation_date >= output.formation_date
        for security_id in incumbent_security_ids
    ):
        raise DecisionError("an incumbent project must predate the current judgment")
    for security_id in incumbent_security_ids:
        if project_by[security_id].state is not ProjectState.ACTIVE:
            raise DecisionError("an incumbent must remain active before it can be retained")

    candidates = {item.security_id: item for item in output.candidates}
    stages = output.comparison_stage_receipts
    graph_hashes = tuple(
        StageGraphHash(
            stage=stage.stage,
            graph_hash=_stable_hash(_canonical_stage_record(stage.model_dump(mode="json"))),
        )
        for stage in stages
    )
    stage_hash_by = {item.stage: item.graph_hash for item in graph_hashes}
    edges = tuple(
        edge
        for stage in stages
        for cohort in stage.cohorts
        for edge in cohort.decisive_edges
    )
    dominated = {edge.dominated_security_id for edge in edges}
    tied = {
        security_id
        for tie in output.capacity_tie_abstentions
        for security_id in tie.security_ids
    }
    final_stage = stages[-1]
    action_by = {
        item.security_id: item.current_action_eligible
        for item in final_stage.cross_opportunity_assessments
    }
    shared_incompatible: set[str] = set()
    for receipt in final_stage.exposure_pair_receipts:
        if (
            receipt.relationship is ExposureRelationship.SHARED_RISK
            and not receipt.capacity_compatible
        ):
            for security_id in (receipt.left_security_id, receipt.right_security_id):
                if not action_by.get(security_id, False):
                    shared_incompatible.add(security_id)

    reasons_by: dict[str, list[DecisionReason]] = {
        security_id: [] for security_id in candidates
    }
    eligible: set[str] = set()
    for security_id, judgment in candidates.items():
        project = project_by[security_id]
        reasons = reasons_by[security_id]
        if judgment.card_status is not EvidenceCardStatus.READY:
            reasons.append(DecisionReason.NONREADY_CARD)
        if judgment.suggested_layer is CandidateLayer.INTERNAL:
            reasons.append(DecisionReason.INTERNAL_SUGGESTED)
        if project.state is not ProjectState.ACTIVE:
            reasons.append(DecisionReason.INACTIVE_PROJECT)
        if security_id in dominated:
            reasons.append(DecisionReason.DOMINATED)
        if security_id in tied:
            reasons.append(DecisionReason.CAPACITY_TIE)
        primary_route = _PRIMARY_ROUTE[judgment.primary_opportunity]
        if primary_route not in project.discovery_routes:
            reasons.append(DecisionReason.PRIMARY_ROUTE_MISSING)
        elif not capability.routes[primary_route.value].can_enter_ten:
            reasons.append(DecisionReason.PRIMARY_ROUTE_BLOCKED)
        if not action_by.get(security_id, False):
            reasons.append(DecisionReason.FINAL_GRAPH_NOT_ACTIONABLE)
        if security_id in shared_incompatible:
            reasons.append(DecisionReason.SHARED_EXPOSURE)
        if (
            judgment.suggested_layer is CandidateLayer.FOCUS
            and not _focus_contract_complete(judgment)
        ):
            reasons.append(DecisionReason.FOCUS_INCOMPLETE)
        if not reasons:
            eligible.add(security_id)

    replacement_edges = tuple(
        edge
        for edge in edges
        if edge.winner_security_id not in incumbent_security_ids
        and edge.dominated_security_id in incumbent_security_ids
        and edge.winner_security_id in eligible
    )
    decisive_winners = {edge.winner_security_id for edge in replacement_edges}
    eligible_incumbents = incumbent_security_ids.intersection(eligible)
    resolution = _resolve_attention_capacity(
        eligible_security_ids=tuple(eligible),
        focus_security_ids=tuple(
            security_id
            for security_id in eligible
            if candidates[security_id].suggested_layer is CandidateLayer.FOCUS
        ),
        incumbent_security_ids=tuple(eligible_incumbents),
        decisive_replacement_winners=tuple(decisive_winners),
    )
    selected = set(resolution.selected_security_ids)
    boundary_ids = {
        security_id
        for group in resolution.boundary_abstentions
        for security_id in group
    }
    for security_id in boundary_ids:
        reasons_by[security_id].append(DecisionReason.UNRESOLVED_CAPACITY)
    for security_id in selected:
        judgment = candidates[security_id]
        reasons_by[security_id].append(
            DecisionReason.SELECTED_FOCUS
            if judgment.suggested_layer is CandidateLayer.FOCUS
            else DecisionReason.SELECTED_CANDIDATE
        )
        if security_id in eligible_incumbents:
            reasons_by[security_id].append(DecisionReason.RETAINED_INCUMBENT)
        if security_id in decisive_winners:
            reasons_by[security_id].append(DecisionReason.DECISIVE_CHALLENGER)

    _assert_exposure_capacity(selected, final_stage.exposure_pair_receipts)
    selected_projects = tuple(project_by[security_id] for security_id in sorted(selected))
    cutoff = datetime.combine(output.formation_date, time(23, 59, 59), tzinfo=_SHANGHAI)
    daily = DailyDecision(
        formation_date=output.formation_date,
        cutoff=cutoff,
        candidates=selected_projects,
    )
    object_decisions = tuple(
        ObjectDecision(
            project=project_by[security_id],
            security_id=security_id,
            judgment_layer=candidates[security_id].suggested_layer,
            decision_layer=(
                candidates[security_id].suggested_layer
                if security_id in selected
                else CandidateLayer.INTERNAL
            ),
            occupies_attention_capacity=security_id in selected,
            is_incumbent=security_id in incumbent_security_ids,
            reasons=tuple(dict.fromkeys(reasons_by[security_id])),
        )
        for security_id in sorted(candidates)
    )
    replacement_suggestions = tuple(
        ReplacementSuggestion(
            challenger_security_id=edge.winner_security_id,
            incumbent_security_id=edge.dominated_security_id,
            source_stage=edge.stage,
            decisive_evidence_ids=tuple(edge.judgment.evidence_ids),
            reversal_evidence_ids=tuple(edge.reversal_fact.evidence_ids),
        )
        for edge in sorted(
            replacement_edges,
            key=lambda value: (
                value.winner_security_id,
                value.dominated_security_id,
                value.stage.value,
            ),
        )
        if edge.winner_security_id in selected
    )
    exposure_receipts = tuple(
        sorted(
            (
                ExposurePairReceipt(
                    left_security_id=min(item.left_security_id, item.right_security_id),
                    right_security_id=max(item.left_security_id, item.right_security_id),
                    relationship=item.relationship,
                    capacity_compatible=item.capacity_compatible,
                    judgment=item.judgment,
                    reversal_fact=item.reversal_fact,
                )
                for item in final_stage.exposure_pair_receipts
            ),
            key=lambda item: (item.left_security_id, item.right_security_id),
        )
    )
    verified_ties = tuple(
        sorted(
            (
                CapacityTieAbstention(
                    source_stage=item.source_stage,
                    security_ids=tuple(sorted(item.security_ids)),
                    judgment=item.judgment,
                    reversal_fact=item.reversal_fact,
                )
                for item in output.capacity_tie_abstentions
            ),
            key=lambda item: (item.source_stage.value, item.security_ids),
        )
    )
    boundary_receipts = tuple(
        CapacityBoundaryAbstention(
            security_ids=tuple(sorted(group)),
            reason="unresolved_capacity_boundary",
            source_graph_hash=stage_hash_by[ComparisonStage.CROSS_OPPORTUNITY],
        )
        for group in resolution.boundary_abstentions
    )
    values: dict[str, Any] = {
        "daily_decision": daily,
        "object_decisions": object_decisions,
        "internal_research_pool": tuple(
            item.security_id
            for item in object_decisions
            if item.decision_layer is CandidateLayer.INTERNAL
        ),
        "judgment_batch_hash": judgment_batch_hash,
        "capability_receipt_hash": capability.receipt_hash,
        "comparison_graph_hashes": graph_hashes,
        "exposure_receipts": exposure_receipts,
        "verified_capacity_ties": verified_ties,
        "capacity_tied_security_ids": tuple(sorted(tied)),
        "capacity_boundary_abstentions": boundary_receipts,
        "unselected_challengers": tuple(
            sorted(eligible.difference(incumbent_security_ids, selected))
        ),
        "replacement_suggestions": replacement_suggestions,
        "upstream_internal_exclusions": tuple(
            sorted(upstream_exclusions, key=lambda item: item.security_id)
        ),
        "order_is_canonical_not_ranked": True,
        "source_attestation": source_attestation,
    }
    return DecisionReceipt(**values, content_hash=_stable_hash(_jsonable(values)))


def _validate_projects(
    output: DailyJudgeOutput,
    projects: Mapping[str, CandidateProject],
) -> dict[str, CandidateProject]:
    if not isinstance(projects, Mapping):
        raise DecisionError("projects must be a security-keyed mapping")
    expected = {item.security_id for item in output.candidates}
    if set(projects) != expected:
        raise DecisionError("project identities must exactly match current judgments")
    candidate_by = {item.security_id: item for item in output.candidates}
    normalized: dict[str, CandidateProject] = {}
    for security_id, project in projects.items():
        if type(project) is not CandidateProject:
            raise DecisionError("every decision object must be a CandidateProject")
        try:
            validated = CandidateProject.model_validate(project.model_dump(mode="json"))
        except (TypeError, ValueError) as exc:
            raise DecisionError("candidate project failed closed validation") from exc
        judgment = candidate_by[security_id]
        if validated.security_id != security_id:
            raise DecisionError("project and judgment security identity mismatch")
        if validated.primary_opportunity is not judgment.primary_opportunity:
            raise DecisionError("project and judgment opportunity identity mismatch")
        if validated.layer is not judgment.suggested_layer:
            raise DecisionError("project and judgment layer identity mismatch")
        if validated.formation_date > output.formation_date:
            raise DecisionError("project was formed after the daily judgment")
        normalized[security_id] = validated
    return normalized


def _focus_contract_complete(judgment: CandidateJudgment) -> bool:
    return bool(
        judgment.card_status is EvidenceCardStatus.READY
        and judgment.overall_disposition is RequirementDispositionType.SUPPORTIVE
        and judgment.new_driver_evidence_ids
        and judgment.market_effect.focus_eligible
        and judgment.hotspot_effect.focus_eligible
        and isinstance(judgment.price_role.role, PriceRole)
        and judgment.next_validation_state.judgment.evidence_ids
        and judgment.proposition.target_conditions.evidence_ids
        and judgment.invalidation.evidence_ids
        and judgment.next_fact.evidence_ids
    )


def _require_capability_receipt(value: Any) -> CapabilityReceipt:
    if (
        type(value) is not CapabilityReceipt
        or getattr(value, "_token", None) is not capability_module._RECEIPT_TOKEN
    ):
        raise DecisionError("capability receipt lacks audited frozen provenance")
    try:
        rebuilt = CapabilityReceipt(
            experiment_scope=value.experiment_scope,
            full_v3_status=value.full_v3_status,
            routes=value.routes,
            audit_hash=value.audit_hash,
            receipt_hash=value.receipt_hash,
            _token=capability_module._RECEIPT_TOKEN,
        )
    except (TypeError, ValueError) as exc:
        raise DecisionError("capability receipt failed content validation") from exc
    if rebuilt.to_record() != value.to_record():
        raise DecisionError("capability receipt content changed after freeze")
    return value


def _assert_exposure_capacity(
    selected: set[str], exposure_receipts: Sequence[ExposurePairReceipt]
) -> None:
    for receipt in exposure_receipts:
        if (
            receipt.relationship is ExposureRelationship.SHARED_RISK
            and not receipt.capacity_compatible
            and {receipt.left_security_id, receipt.right_security_id}.issubset(selected)
        ):
            raise DecisionError("shared-risk incompatible objects cannot both occupy capacity")


def _reject_future_fields(value: Any, path: str = "projects") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).lower()
            if any(marker in normalized for marker in _FORBIDDEN_FORMATION_FIELDS):
                raise DecisionError(f"future or outcome field is forbidden: {path}.{key}")
            _reject_future_fields(item, f"{path}.{key}")
    elif isinstance(value, (tuple, list)):
        for index, item in enumerate(value):
            _reject_future_fields(item, f"{path}[{index}]")
    elif isinstance(value, BaseModel):
        _reject_future_fields(value.model_dump(mode="json"), path)


def _canonical_stage_record(record: Mapping[str, Any]) -> dict[str, Any]:
    value = _jsonable(record)
    value["eligible_security_ids"] = sorted(value["eligible_security_ids"])
    cohorts = []
    for raw in value["cohorts"]:
        cohort = dict(raw)
        cohort["security_ids"] = sorted(cohort["security_ids"])
        cohort["decisive_edges"] = sorted(
            cohort["decisive_edges"],
            key=lambda item: (
                item["winner_security_id"],
                item["dominated_security_id"],
            ),
        )
        cohort["indistinguishable_groups"] = sorted(
            (sorted(group) for group in cohort["indistinguishable_groups"]),
            key=tuple,
        )
        cohorts.append(cohort)
    value["cohorts"] = sorted(cohorts, key=lambda item: item["cohort_id"])
    value["cross_opportunity_assessments"] = sorted(
        value.get("cross_opportunity_assessments", []),
        key=lambda item: item["security_id"],
    )
    normalized_exposure = []
    for raw in value.get("exposure_pair_receipts", []):
        item = dict(raw)
        item["left_security_id"], item["right_security_id"] = sorted(
            (item["left_security_id"], item["right_security_id"])
        )
        normalized_exposure.append(item)
    value["exposure_pair_receipts"] = sorted(
        normalized_exposure,
        key=lambda item: (item["left_security_id"], item["right_security_id"]),
    )
    return value


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            _jsonable(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, StrEnum):
        return value.value
    return value


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


__all__ = [
    "CapacityBoundaryAbstention",
    "DecisionError",
    "DecisionReceipt",
    "ObjectDecision",
    "ReplacementSuggestion",
    "compress_research_pool",
    "compress_research_pool_for_test",
]
