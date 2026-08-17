from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from stock_analyzer.selection_lab.schemas import (
    OpportunityType,
    OpportunityTypeStatus,
)


class OpportunityEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposed_type: OpportunityType | None = None
    causal_thesis: str | None = None
    direct_company_fact: bool = False
    historical_membership_confirmed: bool = False
    sector_diffusion_confirmed: bool = False
    peer_advantage_confirmed: bool = False
    new_company_announcement: bool = False
    relative_market_checked: bool = False
    relative_peer_checked: bool = False
    volume_progress_checked: bool = False
    liquidity_checked: bool = False
    overextension_checked: bool = False
    secondary_types: list[OpportunityType] = Field(default_factory=list)
    confidence: str = "medium"
    evidence_items: list[dict[str, Any]] = Field(default_factory=list)


class OpportunityAssignment(BaseModel):
    primary_type: OpportunityType | None
    status: OpportunityTypeStatus
    secondary_types: list[OpportunityType] = Field(default_factory=list)
    confidence: str | None = None
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    assignment_reason: str = ""
    core_evidence_complete: bool = False


def assign_opportunity_type(
    evidence: OpportunityEvidence,
) -> OpportunityAssignment:
    if evidence.proposed_type is None or not (evidence.causal_thesis or "").strip():
        return OpportunityAssignment(
            primary_type=None,
            status=OpportunityTypeStatus.NOT_ASSIGNABLE,
            assignment_reason="no formation-date causal thesis",
        )

    proposed = evidence.proposed_type
    if proposed is OpportunityType.COMPANY_CATALYST:
        if not evidence.direct_company_fact:
            raise ValueError("company_catalyst requires a direct company fact")
    elif proposed is OpportunityType.SECTOR_DIFFUSION:
        _require_checks(
            evidence,
            (
                "historical_membership_confirmed",
                "sector_diffusion_confirmed",
                "peer_advantage_confirmed",
            ),
        )
    elif proposed is OpportunityType.INDEPENDENT_PRICE_ANOMALY:
        _require_checks(
            evidence,
            (
                "relative_market_checked",
                "relative_peer_checked",
                "volume_progress_checked",
                "liquidity_checked",
                "overextension_checked",
            ),
        )

    if proposed in evidence.secondary_types:
        raise ValueError("primary opportunity type cannot repeat as secondary")
    if len(set(evidence.secondary_types)) != len(evidence.secondary_types):
        raise ValueError("secondary opportunity types must be unique")
    return OpportunityAssignment(
        primary_type=proposed,
        status=OpportunityTypeStatus.ASSIGNED,
        secondary_types=evidence.secondary_types,
        confidence=evidence.confidence,
        evidence=evidence.evidence_items,
        assignment_reason=evidence.causal_thesis,
        core_evidence_complete=True,
    )


def audit_sole_company_gate(
    assignment: OpportunityAssignment,
    *,
    rejection_reason: str,
    blockers: list[str],
    candidate_chain_available: bool,
) -> bool | None:
    if not candidate_chain_available:
        return None
    non_company_type = assignment.primary_type in {
        OpportunityType.SECTOR_DIFFUSION,
        OpportunityType.INDEPENDENT_PRICE_ANOMALY,
    }
    return bool(
        non_company_type
        and assignment.core_evidence_complete
        and rejection_reason == "no_direct_company_catalyst"
        and not blockers
    )


def _require_checks(evidence: OpportunityEvidence, names: tuple[str, ...]) -> None:
    missing = [name for name in names if not getattr(evidence, name)]
    if missing:
        raise ValueError("missing required opportunity evidence: " + ", ".join(missing))
