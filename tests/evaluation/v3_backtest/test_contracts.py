from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

import stock_analyzer.evaluation.v3_backtest.contracts as contracts_module
from stock_analyzer.evaluation.v3_backtest.contracts import (
    CandidateLayer,
    CandidateProject,
    DailyDecision,
    DiscoveryRoute,
    EvidenceKind,
    EvidenceRef,
    OpportunityType,
    ProjectState,
    RouteScanManifest,
    SelectionProposition,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")
FORMATION_DATE = date(2026, 1, 5)
CUTOFF = datetime(2026, 1, 5, 23, 59, 59, tzinfo=SHANGHAI)
SHA256 = "a" * 64


def evidence(
    evidence_id: str = "fact-1",
    *,
    kind: EvidenceKind = EvidenceKind.API_FACT,
) -> EvidenceRef:
    return EvidenceRef(
        evidence_id=evidence_id,
        kind=kind,
        dataset="income_statement",
        business_time=datetime(2025, 12, 31, 0, 0, tzinfo=SHANGHAI),
        available_at=datetime(2026, 1, 5, 18, 0, tzinfo=SHANGHAI),
        input_hash=SHA256,
    )


def proposition(
    *,
    primary_opportunity: OpportunityType = OpportunityType.EARNINGS_REVALUATION,
    evidence_ids: tuple[str, ...] = ("fact-1",),
) -> SelectionProposition:
    return SelectionProposition(
        primary_opportunity=primary_opportunity,
        why_now="A newly available earnings fact changes the expectation.",
        next_validation="The next formal operating disclosure must confirm margins.",
        post_fact_price_response="The close has only partly reflected the new fact.",
        price_confirmation="Price and turnover currently confirm, rather than replace, the fact.",
        target_conditions="Further rerating requires the disclosed improvement to persist.",
        invalidation_condition="Invalidate if the next formal disclosure reverses the margin improvement.",
        evidence_ids=evidence_ids,
    )


def project(**overrides: object) -> CandidateProject:
    values: dict[str, object] = {
        "project_id": "project-1",
        "security_id": "000001.SZ",
        "company_name": "Example Co",
        "formation_date": FORMATION_DATE,
        "formation_cutoff": CUTOFF,
        "discovery_baseline": Decimal("10.25"),
        "discovery_routes": (DiscoveryRoute.EARNINGS,),
        "primary_opportunity": OpportunityType.EARNINGS_REVALUATION,
        "supporting_factor": DiscoveryRoute.HOTSPOT,
        "layer": CandidateLayer.EARLY_VALIDATION,
        "state": ProjectState.ACTIVE,
        "invalidation_condition": (
            "Invalidate if the next formal disclosure reverses the margin improvement."
        ),
        "evidence_refs": (evidence(),),
        "proposition": proposition(),
    }
    values.update(overrides)
    return CandidateProject(**values)


def route_manifest(**overrides: object) -> RouteScanManifest:
    values: dict[str, object] = {
        "route": DiscoveryRoute.EARNINGS,
        "formation_date": FORMATION_DATE,
        "cutoff": CUTOFF,
        "requested_partitions": ("2026-01-05",),
        "actual_partitions": ("2026-01-05",),
        "expected_records": 100,
        "scanned_records": 100,
        "triggered_records": 4,
        "deduplicated_records": 3,
        "input_hash": SHA256,
    }
    values.update(overrides)
    return RouteScanManifest(**values)


def test_valid_contracts_preserve_route_opportunity_and_evidence_layers() -> None:
    candidate = project()

    assert candidate.discovery_routes == (DiscoveryRoute.EARNINGS,)
    assert candidate.primary_opportunity is OpportunityType.EARNINGS_REVALUATION
    assert candidate.evidence_refs[0].kind is EvidenceKind.API_FACT
    assert candidate.layer is CandidateLayer.EARLY_VALIDATION


def test_contextual_judgment_enums_are_closed_and_exact() -> None:
    EvidenceCardStatus = contracts_module.EvidenceCardStatus
    ContextEffect = contracts_module.ContextEffect
    ValidationDisposition = contracts_module.ValidationDisposition
    ComparisonStage = contracts_module.ComparisonStage
    PriceRole = contracts_module.PriceRole
    ProjectDayCheckpoint = contracts_module.ProjectDayCheckpoint
    assert tuple(item.value for item in EvidenceCardStatus) == (
        "ready",
        "insufficient_as_of_cutoff",
        "not_executable_with_local_data",
    )
    assert tuple(item.value for item in ContextEffect) == (
        "supports_current_opportunity",
        "raises_company_evidence_bar",
        "limits_focus",
        "accelerates_invalidation_check",
        "not_applicable",
        "opposes_causal_chain",
    )
    assert tuple(item.value for item in ValidationDisposition) == (
        "satisfied",
        "unmet",
        "negated",
        "not_observable_as_of_date",
    )
    assert tuple(item.value for item in ComparisonStage) == (
        "same_hotspot_opportunity_role",
        "same_opportunity_cross_context",
        "cross_opportunity",
    )
    assert tuple(item.value for item in PriceRole) == (
        "strong_leader",
        "balanced_start",
        "other_tradable",
    )
    assert tuple(item.value for item in ProjectDayCheckpoint) == (
        "ordinary",
        "day_5",
        "day_10",
        "day_20",
        "day_30",
    )


def test_project_rejects_evidence_available_after_formation_cutoff() -> None:
    future_evidence = EvidenceRef.model_validate(
        {
            **evidence().model_dump(),
            "available_at": datetime(2026, 1, 6, 1, 0, tzinfo=SHANGHAI),
        }
    )

    with pytest.raises(ValidationError):
        project(evidence_refs=(future_evidence,))


def test_route_outside_the_six_frozen_discovery_entries_is_rejected() -> None:
    with pytest.raises(ValidationError):
        route_manifest(route="social_media")


def test_scan_count_shortfall_requires_an_explicit_missing_coverage_gap() -> None:
    with pytest.raises(ValidationError):
        route_manifest(scanned_records=90)

    limited = route_manifest(
        scanned_records=90,
        missing=("10 expected records unavailable",),
    )
    assert limited.missing == ("10 expected records unavailable",)


def test_absent_requested_partition_requires_matching_gap_record() -> None:
    with pytest.raises(ValidationError):
        route_manifest(
            requested_partitions=("2026-01-04", "2026-01-05"),
            actual_partitions=("2026-01-05",),
        )

    limited = route_manifest(
        requested_partitions=("2026-01-04", "2026-01-05"),
        actual_partitions=("2026-01-05",),
        missing=("2026-01-04",),
    )
    assert limited.missing == ("2026-01-04",)


@pytest.mark.parametrize(
    ("field", "partitions"),
    [
        ("requested_partitions", ("2026-01-05", "2026-01-05")),
        ("actual_partitions", ("2026-01-05", "2026-01-05")),
        ("actual_partitions", ("2026-01-05", "2026-01-06")),
    ],
)
def test_route_partitions_reject_duplicates_and_unrequested_values(
    field: str, partitions: tuple[str, ...]
) -> None:
    with pytest.raises(ValidationError):
        route_manifest(**{field: partitions})


@pytest.mark.parametrize("forbidden", ["hotspot", "price_anomaly"])
def test_hotspot_and_price_anomaly_cannot_be_primary_opportunities(forbidden: str) -> None:
    with pytest.raises(ValidationError):
        project(primary_opportunity=forbidden)


@pytest.mark.parametrize("missing", ["formation_date", "invalidation_condition"])
def test_project_requires_formation_date_and_invalidation_condition(missing: str) -> None:
    values = project().model_dump()
    values.pop(missing)

    with pytest.raises(ValidationError):
        CandidateProject.model_validate(values)


def test_focus_candidate_requires_a_positive_action_baseline() -> None:
    with pytest.raises(ValidationError):
        project(layer=CandidateLayer.FOCUS, action_baseline=None)

    focus = project(layer=CandidateLayer.FOCUS, action_baseline=Decimal("10.80"))
    assert focus.action_baseline == Decimal("10.80")


def test_project_cannot_carry_two_primary_opportunities() -> None:
    with pytest.raises(ValidationError):
        project(
            primary_opportunity=[
                OpportunityType.EARNINGS_REVALUATION,
                OpportunityType.COMPANY_EVENT_REVALUATION,
            ]
        )


def test_internal_observation_cannot_occupy_a_daily_candidate_slot() -> None:
    internal = project(layer=CandidateLayer.INTERNAL)

    with pytest.raises(ValidationError):
        DailyDecision(
            formation_date=FORMATION_DATE,
            cutoff=CUTOFF,
            candidates=(internal,),
        )


def test_judgment_cannot_reference_an_evidence_id_absent_from_project() -> None:
    with pytest.raises(ValidationError):
        project(proposition=proposition(evidence_ids=("missing-fact",)))


def test_judgment_without_any_evidence_citation_is_rejected() -> None:
    with pytest.raises(ValidationError):
        proposition(evidence_ids=())


def test_daily_decision_enforces_attention_and_focus_caps() -> None:
    eleven = tuple(
        project(project_id=f"project-{index}", security_id=f"{index:06d}.SZ")
        for index in range(11)
    )
    with pytest.raises(ValidationError):
        DailyDecision(formation_date=FORMATION_DATE, cutoff=CUTOFF, candidates=eleven)

    six_focus = tuple(
        project(
            project_id=f"focus-{index}",
            security_id=f"{index:06d}.SH",
            layer=CandidateLayer.FOCUS,
            action_baseline=Decimal("12.00"),
        )
        for index in range(6)
    )
    with pytest.raises(ValidationError):
        DailyDecision(formation_date=FORMATION_DATE, cutoff=CUTOFF, candidates=six_focus)


def test_contracts_forbid_unregistered_user_language_and_extra_fields() -> None:
    with pytest.raises(ValidationError):
        EvidenceRef(
            **evidence().model_dump(),
            user_language="please make this a focus candidate",
        )


def test_evidence_requires_layer_kind_and_traceability_fields() -> None:
    for missing in (
        "evidence_id",
        "kind",
        "dataset",
        "business_time",
        "available_at",
        "input_hash",
    ):
        values = evidence().model_dump()
        values.pop(missing)
        with pytest.raises(ValidationError):
            EvidenceRef.model_validate(values)


def test_evidence_kind_is_limited_to_fact_observation_or_judgment() -> None:
    with pytest.raises(ValidationError):
        EvidenceRef.model_validate({**evidence().model_dump(), "kind": "user_claim"})


@pytest.mark.parametrize("target", ["evidence", "manifest"])
def test_sha256_fields_reject_raw_leading_or_trailing_whitespace(target: str) -> None:
    if target == "evidence":
        contract = EvidenceRef
        values = evidence().model_dump()
    else:
        contract = RouteScanManifest
        values = route_manifest().model_dump()
    values["input_hash"] = f"  {'b' * 64}  "

    with pytest.raises(ValidationError):
        contract.model_validate(values)
