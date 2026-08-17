from datetime import date

import pytest
from pydantic import ValidationError

from stock_analyzer.selection_lab.schemas import (
    CapabilityResult,
    FormationSample,
)


def _sample(**overrides):
    values = {
        "research_track": "frozen_candidate_chain",
        "eligibility_status": "eligible",
        "formation_date": date(2026, 1, 5),
        "formation_as_of": "2026-01-05T23:59:59+08:00",
        "action_date": date(2026, 1, 6),
        "ts_code": "000001.SZ",
        "candidate_status": "selected",
    }
    values.update(overrides)
    return FormationSample(**values)


def test_surface_sample_cannot_claim_eligible():
    with pytest.raises(ValidationError, match="unknown_identity_history"):
        _sample(
            research_track="deterministic_research_surface",
            eligibility_status="eligible",
            candidate_status="non_candidate",
        )


def test_surface_sample_accepts_unknown_identity_history():
    sample = _sample(
        research_track="deterministic_research_surface",
        eligibility_status="unknown_identity_history",
        candidate_status="non_candidate",
    )

    assert sample.opportunity_type is None
    assert sample.opportunity_type_status == "not_assignable"


def test_null_type_preserves_missing_evidence_status():
    sample = _sample(opportunity_type_status="missing_evidence")

    assert sample.opportunity_type is None
    assert sample.opportunity_type_status == "missing_evidence"


def test_rejection_reason_uses_registered_vocabulary():
    with pytest.raises(ValidationError):
        _sample(rejection_reason_code="made_up_reason")


def test_assignment_metadata_is_serialized_on_sample():
    sample = _sample(
        opportunity_type="company_catalyst",
        opportunity_type_status="assigned",
        opportunity_type_confidence="high",
        opportunity_type_as_of="2026-01-05T23:59:59+08:00",
        opportunity_type_assignment_reason="direct company event",
    )

    payload = sample.model_dump(mode="json")
    assert payload["opportunity_type_as_of"].endswith("+08:00")
    assert payload["opportunity_type_assignment_reason"] == "direct company event"


def test_formation_as_of_requires_timezone():
    with pytest.raises(ValidationError):
        _sample(formation_as_of="2026-01-05T23:59:59")


def test_action_date_must_follow_formation_date():
    with pytest.raises(ValidationError, match="action_date"):
        _sample(action_date=date(2026, 1, 5))


def test_capability_result_requires_reason_when_unavailable():
    with pytest.raises(ValidationError, match="reason_code"):
        CapabilityResult(status="unavailable")


def test_capability_result_allows_available_without_reason():
    result = CapabilityResult(status="available")

    assert result.reason_code is None
