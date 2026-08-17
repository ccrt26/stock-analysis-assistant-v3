from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Any

from pydantic import AwareDatetime, BaseModel, Field, model_validator


class ResearchTrack(StrEnum):
    FROZEN_CANDIDATE_CHAIN = "frozen_candidate_chain"
    DETERMINISTIC_RESEARCH_SURFACE = "deterministic_research_surface"
    FULL_UNIVERSE = "full_universe"


class EligibilityStatus(StrEnum):
    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"
    UNKNOWN_IDENTITY_HISTORY = "unknown_identity_history"


class CandidateStatus(StrEnum):
    SELECTED = "selected"
    REJECTED = "rejected"
    UNRESOLVED = "unresolved"
    NON_CANDIDATE = "non_candidate"


class RejectionReasonCode(StrEnum):
    NO_DIRECT_COMPANY_CATALYST = "no_direct_company_catalyst"
    COMPANY_TRANSMISSION_WEAK = "company_transmission_weak"
    SECTOR_DIFFUSION_WEAK = "sector_diffusion_weak"
    PEER_ADVANTAGE_MISSING = "peer_advantage_missing"
    PRICE_NOT_INDEPENDENT = "price_not_independent"
    PRICE_OVEREXTENDED = "price_overextended"
    VOLUME_PRICE_DIVERGENCE = "volume_price_divergence"
    LIQUIDITY_OR_TRADABILITY = "liquidity_or_tradability"
    DATA_QUALITY_BLOCK = "data_quality_block"
    MAJOR_COUNTEREVIDENCE = "major_counterevidence"
    OTHER = "other"


class OpportunityType(StrEnum):
    COMPANY_CATALYST = "company_catalyst"
    SECTOR_DIFFUSION = "sector_diffusion"
    INDEPENDENT_PRICE_ANOMALY = "independent_price_anomaly"


class OpportunityTypeStatus(StrEnum):
    ASSIGNED = "assigned"
    NOT_ASSIGNABLE = "not_assignable"
    MISSING_EVIDENCE = "missing_evidence"


class CapabilityStatus(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    BLOCKED = "blocked"


class LabelRevealState(StrEnum):
    FEATURES_FROZEN = "features_frozen"
    DEVELOPMENT_LABELS_OPENED = "development_labels_opened"
    VALIDATION_LABELS_OPENED = "validation_labels_opened"
    FINAL_TEST_LABELS_OPENED = "final_test_labels_opened"


class CapabilityResult(BaseModel):
    status: CapabilityStatus
    reason_code: str | None = None
    details: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_reason_for_failure(self) -> "CapabilityResult":
        if self.status is not CapabilityStatus.AVAILABLE and not self.reason_code:
            raise ValueError("reason_code is required when capability is unavailable")
        return self


class FormationSample(BaseModel):
    research_track: ResearchTrack
    eligibility_status: EligibilityStatus
    formation_date: date
    formation_as_of: AwareDatetime
    action_date: date
    ts_code: str
    candidate_status: CandidateStatus
    rejection_reason_code: RejectionReasonCode | None = None
    opportunity_type: OpportunityType | None = None
    opportunity_type_status: OpportunityTypeStatus = (
        OpportunityTypeStatus.NOT_ASSIGNABLE
    )
    secondary_opportunity_types: list[OpportunityType] = Field(default_factory=list)
    opportunity_type_confidence: str | None = None
    opportunity_type_as_of: AwareDatetime | None = None
    opportunity_type_evidence: list[dict[str, Any]] = Field(default_factory=list)
    opportunity_type_assignment_reason: str = ""
    features: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_time_and_track(self) -> "FormationSample":
        if self.action_date <= self.formation_date:
            raise ValueError("action_date must follow formation_date")
        if (
            self.research_track is ResearchTrack.DETERMINISTIC_RESEARCH_SURFACE
            and self.eligibility_status
            is not EligibilityStatus.UNKNOWN_IDENTITY_HISTORY
        ):
            raise ValueError(
                "deterministic research surface requires unknown_identity_history"
            )
        if (
            self.opportunity_type is None
            and self.opportunity_type_status is OpportunityTypeStatus.ASSIGNED
        ):
            raise ValueError("null opportunity_type cannot have assigned status")
        elif (
            self.opportunity_type is not None
            and self.opportunity_type_status is not OpportunityTypeStatus.ASSIGNED
        ):
            raise ValueError("assigned opportunity_type requires assigned status")
        return self


class FutureLabels(BaseModel):
    executable_on_action_date: bool | None
    hit_20pct_close_within_20d: bool | None
    first_hit_day: int | None = Field(default=None, ge=1, le=20)
    max_close_return_20d: float | None = None
    terminal_return_20d: float | None = None
    terminal_relative_market_20d: float | None = None
    max_adverse_move_before_hit_or_end: float | None = None
    giveback_from_max_close_to_terminal: float | None = None
