import pytest
from pydantic import ValidationError

from stock_analyzer.selection_lab.opportunity_types import (
    OpportunityEvidence,
    assign_opportunity_type,
    audit_sole_company_gate,
)


def _price_evidence(**overrides):
    values = {
        "proposed_type": "independent_price_anomaly",
        "causal_thesis": "company-specific relative price and volume anomaly",
        "relative_market_checked": True,
        "relative_peer_checked": True,
        "volume_progress_checked": True,
        "liquidity_checked": True,
        "overextension_checked": True,
    }
    values.update(overrides)
    return OpportunityEvidence(**values)


def test_company_catalyst_requires_direct_company_fact():
    evidence = OpportunityEvidence(
        proposed_type="company_catalyst",
        causal_thesis="new company event",
        direct_company_fact=False,
    )

    with pytest.raises(ValueError, match="direct company fact"):
        assign_opportunity_type(evidence)


def test_sector_diffusion_does_not_require_new_company_announcement():
    evidence = OpportunityEvidence(
        proposed_type="sector_diffusion",
        causal_thesis="broad sector diffusion",
        historical_membership_confirmed=True,
        sector_diffusion_confirmed=True,
        peer_advantage_confirmed=True,
        new_company_announcement=False,
    )

    assignment = assign_opportunity_type(evidence)

    assert assignment.primary_type == "sector_diffusion"


def test_price_anomaly_without_company_catalyst_remains_assignable():
    assignment = assign_opportunity_type(_price_evidence(direct_company_fact=False))

    assert assignment.primary_type == "independent_price_anomaly"


def test_price_anomaly_requires_all_strict_checks():
    with pytest.raises(ValueError, match="relative_peer_checked"):
        assign_opportunity_type(_price_evidence(relative_peer_checked=False))


def test_assignment_rejects_future_label_fields():
    with pytest.raises(ValidationError, match="future_labels"):
        OpportunityEvidence(
            proposed_type="company_catalyst",
            causal_thesis="event",
            direct_company_fact=True,
            future_labels={"hit_20pct_close_within_20d": True},
        )


def test_missing_causal_thesis_returns_null_type():
    assignment = assign_opportunity_type(OpportunityEvidence())

    assert assignment.primary_type is None
    assert assignment.status == "not_assignable"


def test_primary_and_secondary_types_are_preserved_without_duplicates():
    assignment = assign_opportunity_type(
        _price_evidence(secondary_types=["sector_diffusion"])
    )

    assert assignment.secondary_types == ["sector_diffusion"]


def test_primary_type_cannot_repeat_as_secondary():
    with pytest.raises(ValueError, match="secondary"):
        assign_opportunity_type(
            _price_evidence(secondary_types=["independent_price_anomaly"])
        )


def test_missing_company_catalyst_can_be_the_sole_gate_for_non_company_type():
    assignment = assign_opportunity_type(_price_evidence())

    assert audit_sole_company_gate(
        assignment,
        rejection_reason="no_direct_company_catalyst",
        blockers=[],
        candidate_chain_available=True,
    ) is True


def test_sole_gate_is_null_without_machine_candidate_chain():
    assignment = assign_opportunity_type(_price_evidence())

    assert audit_sole_company_gate(
        assignment,
        rejection_reason="no_direct_company_catalyst",
        blockers=[],
        candidate_chain_available=False,
    ) is None


def test_other_blockers_prevent_sole_company_gate_classification():
    assignment = assign_opportunity_type(_price_evidence())

    assert audit_sole_company_gate(
        assignment,
        rejection_reason="no_direct_company_catalyst",
        blockers=["liquidity_or_tradability"],
        candidate_chain_available=True,
    ) is False
