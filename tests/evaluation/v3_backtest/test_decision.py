from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

import stock_analyzer.evaluation.v3_backtest.capability as capability_module
from stock_analyzer.evaluation.v3_backtest.capability import (
    CapabilityReceipt,
    RouteCapability,
)
from stock_analyzer.evaluation.v3_backtest.contracts import (
    CandidateLayer,
    CandidateProject,
    ComparisonStage,
    DiscoveryRoute,
    EvidenceCardStatus,
    EvidenceKind,
    EvidenceRef,
    OpportunityType,
    PriceRole,
    ProjectState,
    SelectionProposition,
)
from stock_analyzer.evaluation.v3_backtest.decision import (
    DecisionError,
    _resolve_attention_capacity,
    compress_research_pool,
    compress_research_pool_for_test,
)
from stock_analyzer.evaluation.v3_backtest.judge import (
    CandidateJudgment,
    DailyJudgeOutput,
)


_DAY = date(2026, 1, 8)
_TZ = timezone(timedelta(hours=8))
_CUTOFF = datetime(2026, 1, 8, 23, 59, 59, tzinfo=_TZ)
_HASH = hashlib.sha256(b"decision-test").hexdigest()
_OPPORTUNITIES = tuple(OpportunityType)
_PRIMARY_ROUTE = {
    OpportunityType.INDUSTRY_TREND: DiscoveryRoute.INDUSTRY_CYCLE,
    OpportunityType.EARNINGS_REVALUATION: DiscoveryRoute.EARNINGS,
    OpportunityType.SUPPLY_DEMAND_CYCLE: DiscoveryRoute.INDUSTRY_CYCLE,
    OpportunityType.COMPANY_EVENT_REVALUATION: DiscoveryRoute.COMPANY_EVENT,
    OpportunityType.DISTRESS_REVERSAL: DiscoveryRoute.DISTRESS_REPAIR,
}


def _text(security_id: str, suffix: str = "fact") -> dict[str, object]:
    return {
        "text": f"{security_id} has a cited formation-time {suffix}",
        "evidence_ids": [f"e:{security_id}"],
    }


def _context(security_id: str, *, focus_eligible: bool = True) -> dict[str, object]:
    return {
        "effect": "supports_current_opportunity" if focus_eligible else "limits_focus",
        "source_section": "market_constraints",
        "section_availability": "evidence_ready_for_judgment",
        "source_section_hash": _HASH,
        "judgment": _text(security_id, "market context"),
        "consequence_evidence_ids": [f"e:{security_id}"],
        "company_evidence_bar": "standard",
        "company_evidence_bar_satisfied": True,
        "focus_eligible": focus_eligible,
        "invalidation_check": "normal",
        "causal_chain": "supported" if focus_eligible else "neutral",
    }


def _hotspot_context(security_id: str, *, focus_eligible: bool = True) -> dict[str, object]:
    value = _context(security_id, focus_eligible=focus_eligible)
    value["source_section"] = "hotspot_panorama"
    return value


def _judgment(
    security_id: str,
    opportunity: OpportunityType,
    *,
    layer: CandidateLayer = CandidateLayer.EARLY_VALIDATION,
    ready: bool = True,
    tied: bool = False,
    new_driver: bool = True,
    focus_context: bool = True,
) -> CandidateJudgment:
    status = "ready" if ready else "insufficient_as_of_cutoff"
    card_source: dict[str, object] = {
        "opportunity": opportunity.value,
        "status": status,
        "upstream_status": "evidence_ready_for_judgment" if ready else "incomplete",
        "missing_requirements": [] if ready else ["formal disclosure hierarchy"],
        "coverage_statuses": [],
        "requirement_gap_sources": [],
        "source_card_hash": _HASH,
    }
    if not ready:
        card_source["coverage_statuses"] = ["not_available_as_of"]
        card_source["requirement_gap_sources"] = [
            {
                "opportunity": opportunity.value,
                "requirement": "formal disclosure hierarchy",
                "governed_datasets": ["earnings_forecast", "earnings_express", "income_statement"],
                "coverage_causes": [
                    {
                        "dataset": dataset,
                        "status": "not_available_as_of",
                        "coverage_hash": _HASH,
                    }
                    for dataset in ("earnings_forecast", "earnings_express", "income_statement")
                ],
                "mapping_hash": hashlib.sha256(
                    (
                        '{"datasets":["earnings_forecast","earnings_express","income_statement"],'
                        f'"opportunity":"{opportunity.value}",'
                        '"requirement":"formal disclosure hierarchy"}'
                    ).encode()
                ).hexdigest(),
            }
        ]
    proposition = {
        "primary_opportunity": opportunity.value,
        "why_now": _text(security_id, "why-now fact"),
        "next_validation": _text(security_id, "next validation"),
        "post_fact_price_response": _text(security_id, "price response"),
        "price_confirmation": _text(security_id, "price confirmation"),
        "target_conditions": _text(security_id, "conditional target path"),
        "invalidation_condition": _text(security_id, "invalidation"),
    }
    return CandidateJudgment.model_validate(
        {
            "security_id": security_id,
            "judgment_kind": "model_judgment",
            "primary_opportunity": opportunity.value,
            "overall_disposition": "supportive" if ready else "unknown",
            "supporting_factors": [],
            "market_effect": _context(security_id, focus_eligible=focus_context),
            "hotspot_effect": _hotspot_context(security_id, focus_eligible=focus_context),
            "hotspot_memberships": [],
            "card_status": status,
            "card_status_source": card_source,
            "price_role": {
                "role": "other_tradable",
                "source_section": "price_volume_liquidity",
                "section_availability": "evidence_ready_for_judgment",
                "source_section_hash": _HASH,
                "judgment": _text(security_id, "price role"),
            },
            "next_validation_state": {
                "disposition": "satisfied",
                "next_check": "day_5",
                "judgment": _text(security_id, "validation state"),
            },
            "proposition": proposition,
            "directional_thesis": _text(security_id, "directional thesis"),
            "new_driver_evidence_ids": [f"e:{security_id}"] if new_driver else [],
            "requirement_dispositions": [
                {
                    "requirement": "formation-time operating evidence",
                    "disposition": "supportive" if ready else "unknown",
                    "judgment": _text(security_id, "requirement"),
                }
            ],
            "prepared_knowledge_ids": [],
            "actually_used_knowledge": [],
            "unused_prepared_knowledge": [],
            "decisive_advantages": [_text(security_id, "decisive advantage")],
            "decisive_comparison": {
                "comparator_security_ids": [],
                "comparison_role": "no_same_opportunity_peer",
                "judgment": _text(security_id, "comparison"),
                "reversal_fact": _text(security_id, "comparison reversal"),
            },
            "capacity_tie_abstention": tied,
            "counterevidence": [
                {
                    "disposition": "none_supported_as_of_cutoff",
                    "source_section": "counterevidence",
                    "judgment": {"text": "no adverse fact as of cutoff", "evidence_ids": []},
                }
            ],
            "unknowns": [
                {
                    "disposition": "unknown",
                    "source_section": "unknowns",
                    "judgment": {"text": "no unresolved input as of cutoff", "evidence_ids": []},
                }
            ],
            "next_fact": _text(security_id, "next fact"),
            "invalidation": proposition["invalidation_condition"],
            "suggested_layer": layer.value,
            "evidence_refs": [f"e:{security_id}"],
        }
    )


def _cohort(
    stage: ComparisonStage,
    security_ids: tuple[str, ...],
    *,
    edges: tuple[tuple[str, str], ...] = (),
    ties: tuple[tuple[str, ...], ...] = (),
    suffix: str = "cohort",
) -> dict[str, object]:
    first = security_ids[0]
    return {
        "cohort_id": f"{stage.value}:{suffix}",
        "security_ids": list(security_ids),
        "decisive_edges": [
            {
                "winner_security_id": winner,
                "dominated_security_id": loser,
                "stage": stage.value,
                "judgment": _text(winner, "decisive edge"),
                "reversal_fact": _text(loser, "edge reversal"),
            }
            for winner, loser in edges
        ],
        "indistinguishable_groups": [list(group) for group in ties],
        "judgment": _text(first, "cohort judgment"),
        "reversal_fact": _text(first, "cohort reversal"),
        "completed": True,
    }


def _output(
    candidates: tuple[CandidateJudgment, ...],
    *,
    stage_two_edges: tuple[tuple[str, str], ...] = (),
    stage_two_ties: tuple[tuple[str, ...], ...] = (),
    stage_three_edges: tuple[tuple[str, str], ...] = (),
    exposure: dict[frozenset[str], tuple[str, bool]] | None = None,
) -> DailyJudgeOutput:
    ready = tuple(item for item in candidates if item.card_status is EvidenceCardStatus.READY)
    stage_one = {
        "stage": ComparisonStage.SAME_HOTSPOT_OPPORTUNITY_ROLE.value,
        "eligible_security_ids": [item.security_id for item in ready],
        "cohorts": [
            _cohort(
                ComparisonStage.SAME_HOTSPOT_OPPORTUNITY_ROLE,
                (item.security_id,),
                suffix=item.security_id,
            )
            for item in ready
        ],
    }
    by_opportunity: dict[OpportunityType, list[str]] = {}
    for item in ready:
        by_opportunity.setdefault(item.primary_opportunity, []).append(item.security_id)
    stage_two = {
        "stage": ComparisonStage.SAME_OPPORTUNITY_CROSS_CONTEXT.value,
        "eligible_security_ids": [item.security_id for item in ready],
        "cohorts": [
            _cohort(
                ComparisonStage.SAME_OPPORTUNITY_CROSS_CONTEXT,
                tuple(ids),
                edges=tuple(edge for edge in stage_two_edges if set(edge).issubset(ids)),
                ties=tuple(group for group in stage_two_ties if set(group).issubset(ids)),
                suffix=opportunity.value,
            )
            for opportunity, ids in by_opportunity.items()
        ],
    }
    removed = {loser for _, loser in stage_two_edges}
    removed.update(security_id for group in stage_two_ties for security_id in group)
    survivors = tuple(item for item in ready if item.security_id not in removed)
    survivor_ids = tuple(item.security_id for item in survivors)
    canonical_survivor_ids = tuple(sorted(survivor_ids))
    pairs = tuple(
        (left, right)
        for index, left in enumerate(canonical_survivor_ids)
        for right in canonical_survivor_ids[index + 1 :]
    )
    exposure = exposure or {}
    stage_three = {
        "stage": ComparisonStage.CROSS_OPPORTUNITY.value,
        "eligible_security_ids": list(survivor_ids),
        "cohorts": (
            [
                _cohort(
                    ComparisonStage.CROSS_OPPORTUNITY,
                    canonical_survivor_ids,
                    edges=stage_three_edges,
                    suffix="all",
                )
            ]
            if survivor_ids
            else []
        ),
        "cross_opportunity_assessments": [
            {
                "security_id": item.security_id,
                "current_action_eligible": item.suggested_layer is not CandidateLayer.INTERNAL,
                "independent_role_supported": item.suggested_layer is not CandidateLayer.INTERNAL,
                "independent_role": _text(item.security_id, "independent role"),
                "reversal_fact": _text(item.security_id, "role reversal"),
            }
            for item in survivors
        ],
        "exposure_pair_receipts": [
            {
                "left_security_id": left,
                "right_security_id": right,
                "relationship": exposure.get(frozenset((left, right)), ("independent", True))[0],
                "capacity_compatible": exposure.get(frozenset((left, right)), ("independent", True))[1],
                "judgment": _text(left, "exposure"),
                "reversal_fact": _text(right, "exposure reversal"),
            }
            for left, right in pairs
        ],
    }
    tie_receipts = [
        {
            "source_stage": ComparisonStage.SAME_OPPORTUNITY_CROSS_CONTEXT.value,
            "security_ids": list(group),
            "judgment": _text(group[0], "capacity tie"),
            "reversal_fact": _text(group[-1], "tie reversal"),
        }
        for group in stage_two_ties
    ]
    return DailyJudgeOutput.model_validate(
        {
            "formation_date": _DAY.isoformat(),
            "candidates": [item.model_dump(mode="json") for item in candidates],
            "comparison_stage_receipts": [stage_one, stage_two, stage_three],
            "capacity_tie_abstentions": tie_receipts,
        }
    )


def _project(
    judgment: CandidateJudgment,
    *,
    formed_on: date = _DAY,
    state: ProjectState = ProjectState.ACTIVE,
    routes: tuple[DiscoveryRoute, ...] | None = None,
) -> CandidateProject:
    cutoff = datetime.combine(formed_on, datetime.max.time().replace(microsecond=0), tzinfo=_TZ)
    route = _PRIMARY_ROUTE[judgment.primary_opportunity]
    evidence_id = f"e:{judgment.security_id}"
    return CandidateProject(
        project_id=f"p:{judgment.security_id}",
        security_id=judgment.security_id,
        company_name=f"Company {judgment.security_id}",
        formation_date=formed_on,
        formation_cutoff=cutoff,
        discovery_baseline=Decimal("10"),
        discovery_routes=routes or (route,),
        primary_opportunity=judgment.primary_opportunity,
        layer=judgment.suggested_layer,
        state=state,
        invalidation_condition="cited invalidation",
        evidence_refs=(
            EvidenceRef(
                evidence_id=evidence_id,
                kind=EvidenceKind.API_FACT,
                dataset="synthetic_formation_fact",
                business_time=cutoff,
                available_at=cutoff,
                input_hash=_HASH,
            ),
        ),
        proposition=SelectionProposition(
            primary_opportunity=judgment.primary_opportunity,
            why_now="cited why now",
            next_validation="cited next validation",
            post_fact_price_response="cited price response",
            price_confirmation="cited price confirmation",
            target_conditions="cited target conditions",
            invalidation_condition="cited invalidation",
            evidence_ids=(evidence_id,),
        ),
        action_baseline=Decimal("10") if judgment.suggested_layer is CandidateLayer.FOCUS else None,
    )


def _capability(*, blocked: DiscoveryRoute | None = None) -> CapabilityReceipt:
    routes: dict[str, RouteCapability] = {}
    for route in DiscoveryRoute:
        allowed = route is not blocked
        routes[route.value] = RouteCapability(
            route=route,
            can_enumerate_all=True,
            can_form_ready_card=allowed,
            can_enter_ten=allowed,
            missing_fields=() if allowed else (f"{route.value}.missing",),
            coverage_start=date(2025, 10, 30),
            coverage_end=date(2026, 6, 4),
            covers_required_formations=True,
            coverage_semantics={f"{route.value}_dataset": "formation_sessions"},
            internal_recall_only=False,
            evidence_hashes=(_HASH,),
        )
    full = blocked is None
    payload = capability_module._capability_receipt_payload(
        "full" if full else "partial",
        "executable" if full else "not_executable",
        routes,
        _HASH,
    )
    return CapabilityReceipt(
        experiment_scope="full" if full else "partial",
        full_v3_status="executable" if full else "not_executable",
        routes=routes,
        audit_hash=_HASH,
        receipt_hash=capability_module._canonical_hash(payload),
        _token=capability_module._RECEIPT_TOKEN,
    )


def _compress(
    output: DailyJudgeOutput,
    *,
    incumbent_project_ids: tuple[str, ...] = (),
    capability: CapabilityReceipt | None = None,
):
    projects = {item.security_id: _project(item) for item in output.candidates}
    return compress_research_pool_for_test(
        output,
        projects,
        capability or _capability(),
        judgment_batch_hash="a" * 64,
        incumbent_project_ids=incumbent_project_ids,
    )


def test_public_entry_rejects_forged_verified_batch_and_capability_receipt():
    with pytest.raises(DecisionError, match="judgment batch"):
        compress_research_pool(object(), {}, _capability())
    candidate = _judgment("A", _OPPORTUNITIES[0])
    with pytest.raises(DecisionError, match="capability"):
        compress_research_pool_for_test(
            _output((candidate,)),
            {"A": _project(candidate)},
            object(),
            judgment_batch_hash="a" * 64,
        )


def test_seven_qualified_objects_are_all_kept_without_filling_or_ranking():
    resolution = _resolve_attention_capacity(
        eligible_security_ids=tuple(f"S{index}" for index in range(7)),
        focus_security_ids=(),
        incumbent_security_ids=(),
        decisive_replacement_winners=(),
    )
    assert set(resolution.selected_security_ids) == {f"S{index}" for index in range(7)}
    assert resolution.boundary_abstentions == ()


def test_only_two_focus_qualified_objects_produce_two_focus_objects():
    candidates = (
        _judgment("A", _OPPORTUNITIES[0], layer=CandidateLayer.FOCUS),
        _judgment("B", _OPPORTUNITIES[1], layer=CandidateLayer.FOCUS),
        _judgment("C", _OPPORTUNITIES[2], layer=CandidateLayer.EARLY_VALIDATION),
        _judgment("D", _OPPORTUNITIES[3], layer=CandidateLayer.HIGH_ELASTICITY),
    )
    receipt = _compress(_output(candidates))
    assert sum(item.layer is CandidateLayer.FOCUS for item in receipt.daily_decision.candidates) == 2
    assert len(receipt.daily_decision.candidates) == 4


def test_nonready_internal_dominated_and_tied_objects_never_occupy_capacity():
    ready = _judgment("A", OpportunityType.EARNINGS_REVALUATION)
    nonready = _judgment(
        "B",
        OpportunityType.INDUSTRY_TREND,
        ready=False,
        layer=CandidateLayer.INTERNAL,
    )
    dominated = _judgment(
        "C",
        OpportunityType.EARNINGS_REVALUATION,
        layer=CandidateLayer.INTERNAL,
    )
    output = _output((ready, nonready, dominated), stage_two_edges=(("A", "C"),))
    receipt = _compress(output)
    assert [item.security_id for item in receipt.daily_decision.candidates] == ["A"]
    reasons = {item.security_id: set(item.reasons) for item in receipt.object_decisions}
    assert "nonready_card" in reasons["B"]
    assert "dominated_by_verified_graph" in reasons["C"]

    tied_a = _judgment(
        "T1", OpportunityType.COMPANY_EVENT_REVALUATION, layer=CandidateLayer.INTERNAL, tied=True
    )
    tied_b = _judgment(
        "T2", OpportunityType.COMPANY_EVENT_REVALUATION, layer=CandidateLayer.INTERNAL, tied=True
    )
    tie_receipt = _compress(_output((tied_a, tied_b), stage_two_ties=(("T1", "T2"),)))
    assert tie_receipt.daily_decision.candidates == ()
    assert set(tie_receipt.capacity_tied_security_ids) == {"T1", "T2"}


def test_one_empty_seat_with_two_unresolved_challengers_abstains_from_whole_group():
    incumbents = tuple(f"I{index}" for index in range(9))
    resolution = _resolve_attention_capacity(
        eligible_security_ids=(*incumbents, "C1", "C2"),
        focus_security_ids=(),
        incumbent_security_ids=incumbents,
        decisive_replacement_winners=(),
    )
    assert set(resolution.selected_security_ids) == set(incumbents)
    assert resolution.boundary_abstentions == (("C1", "C2"),)


def test_eleven_unordered_new_objects_are_not_truncated_by_code_or_input_order():
    first = tuple(f"S{index:02d}" for index in range(11))
    left = _resolve_attention_capacity(
        eligible_security_ids=first,
        focus_security_ids=(),
        incumbent_security_ids=(),
        decisive_replacement_winners=(),
    )
    right = _resolve_attention_capacity(
        eligible_security_ids=tuple(reversed(first)),
        focus_security_ids=(),
        incumbent_security_ids=(),
        decisive_replacement_winners=(),
    )
    assert left.selected_security_ids == right.selected_security_ids == ()
    assert {frozenset(group) for group in left.boundary_abstentions} == {frozenset(first)}


def test_primary_route_capability_cannot_be_borrowed_from_another_discovery_route():
    candidate = _judgment("A", OpportunityType.COMPANY_EVENT_REVALUATION)
    project = _project(
        candidate,
        routes=(DiscoveryRoute.COMPANY_EVENT, DiscoveryRoute.EARNINGS),
    )
    receipt = compress_research_pool_for_test(
        _output((candidate,)),
        {"A": project},
        _capability(blocked=DiscoveryRoute.COMPANY_EVENT),
        judgment_batch_hash="a" * 64,
    )
    assert receipt.daily_decision.candidates == ()
    assert "primary_route_not_executable" in receipt.object_decisions[0].reasons


def test_shared_risk_incompatible_pair_cannot_both_enter_but_independent_pair_can():
    left = _judgment("A", _OPPORTUNITIES[0])
    blocked = _judgment("B", _OPPORTUNITIES[1], layer=CandidateLayer.INTERNAL)
    shared = _output(
        (left, blocked),
        stage_three_edges=(("A", "B"),),
        exposure={frozenset(("A", "B")): ("shared_risk", False)},
    )
    receipt = _compress(shared)
    assert [item.security_id for item in receipt.daily_decision.candidates] == ["A"]
    assert "shared_exposure_incompatible" in {
        reason
        for item in receipt.object_decisions
        if item.security_id == "B"
        for reason in item.reasons
    }

    independent = _judgment("B", _OPPORTUNITIES[1])
    independent_receipt = _compress(_output((left, independent)))
    assert {item.security_id for item in independent_receipt.daily_decision.candidates} == {"A", "B"}


def test_focus_requires_new_driver_and_focus_permitted_context():
    missing_driver = _judgment(
        "A", _OPPORTUNITIES[0], layer=CandidateLayer.FOCUS, new_driver=False
    )
    limited_context = _judgment(
        "B",
        _OPPORTUNITIES[1],
        layer=CandidateLayer.EARLY_VALIDATION,
        focus_context=False,
    )
    receipt = _compress(_output((missing_driver, limited_context)))
    assert {item.security_id for item in receipt.daily_decision.candidates} == {"B"}
    assert "focus_contract_incomplete" in receipt.object_decisions[0].reasons


def test_challenger_requires_direct_decisive_edge_to_replace_active_incumbent():
    incumbents = tuple(f"I{index}" for index in range(10))
    unresolved = _resolve_attention_capacity(
        eligible_security_ids=(*incumbents, "C"),
        focus_security_ids=(),
        incumbent_security_ids=incumbents,
        decisive_replacement_winners=(),
    )
    assert set(unresolved.selected_security_ids) == set(incumbents)
    decisive = _resolve_attention_capacity(
        eligible_security_ids=(*incumbents[1:], "C"),
        focus_security_ids=(),
        incumbent_security_ids=incumbents[1:],
        decisive_replacement_winners=("C",),
    )
    assert set(decisive.selected_security_ids) == {*incumbents[1:], "C"}

    incumbent = _judgment("OLD", OpportunityType.EARNINGS_REVALUATION, layer=CandidateLayer.INTERNAL)
    challenger = _judgment("NEW", OpportunityType.EARNINGS_REVALUATION)
    output = _output((incumbent, challenger), stage_two_edges=(("NEW", "OLD"),))
    projects = {
        "OLD": _project(incumbent, formed_on=_DAY - timedelta(days=7)),
        "NEW": _project(challenger),
    }
    receipt = compress_research_pool_for_test(
        output,
        projects,
        _capability(),
        judgment_batch_hash="a" * 64,
        incumbent_project_ids=("p:OLD",),
    )
    assert [(item.challenger_security_id, item.incumbent_security_id) for item in receipt.replacement_suggestions] == [("NEW", "OLD")]


def test_decisive_focus_challenger_is_kept_before_unresolved_focus_peer():
    incumbents = tuple(f"I{index}" for index in range(4))
    resolution = _resolve_attention_capacity(
        eligible_security_ids=(*incumbents, "DECISIVE", "UNRESOLVED"),
        focus_security_ids=(*incumbents, "DECISIVE", "UNRESOLVED"),
        incumbent_security_ids=incumbents,
        decisive_replacement_winners=("DECISIVE",),
    )
    assert set(resolution.selected_security_ids) == {*incumbents, "DECISIVE"}
    assert resolution.boundary_abstentions == (("UNRESOLVED",),)


def test_inactive_or_not_rejudged_incumbent_identity_fails_closed():
    candidate = _judgment("A", _OPPORTUNITIES[0])
    project = _project(
        candidate,
        formed_on=_DAY - timedelta(days=7),
        state=ProjectState.INVALIDATED,
    )
    with pytest.raises(DecisionError, match="active"):
        compress_research_pool_for_test(
            _output((candidate,)),
            {"A": project},
            _capability(),
            judgment_batch_hash="a" * 64,
            incumbent_project_ids=(project.project_id,),
        )
    with pytest.raises(DecisionError, match="rejudged"):
        compress_research_pool_for_test(
            _output((candidate,)),
            {"A": _project(candidate)},
            _capability(),
            judgment_batch_hash="a" * 64,
            incumbent_project_ids=("p:MISSING",),
        )


def test_older_project_must_be_declared_incumbent_and_same_day_project_cannot_be_one():
    candidate = _judgment("A", _OPPORTUNITIES[0])
    old_project = _project(candidate, formed_on=_DAY - timedelta(days=7))
    with pytest.raises(DecisionError, match="older project"):
        compress_research_pool_for_test(
            _output((candidate,)),
            {"A": old_project},
            _capability(),
            judgment_batch_hash="a" * 64,
        )
    same_day = _project(candidate)
    with pytest.raises(DecisionError, match="predate"):
        compress_research_pool_for_test(
            _output((candidate,)),
            {"A": same_day},
            _capability(),
            judgment_batch_hash="a" * 64,
            incumbent_project_ids=(same_day.project_id,),
        )


def test_object_and_judgment_identity_mismatch_and_future_fields_fail_closed():
    candidate = _judgment("A", _OPPORTUNITIES[0])
    mismatched = _project(
        _judgment("A", OpportunityType.EARNINGS_REVALUATION)
    )
    with pytest.raises(DecisionError, match="opportunity"):
        compress_research_pool_for_test(
            _output((candidate,)),
            {"A": mismatched},
            _capability(),
            judgment_batch_hash="a" * 64,
        )
    with pytest.raises(DecisionError, match="future"):
        compress_research_pool_for_test(
            _output((candidate,)),
            {"A": {"project": _project(candidate), "future_return": "known"}},
            _capability(),
            judgment_batch_hash="a" * 64,
        )


def test_input_order_changes_neither_membership_nor_content_hash():
    candidates = (
        _judgment("B", _OPPORTUNITIES[0], layer=CandidateLayer.FOCUS),
        _judgment("A", _OPPORTUNITIES[1]),
        _judgment("C", _OPPORTUNITIES[2], layer=CandidateLayer.HIGH_ELASTICITY),
    )
    first_output = _output(candidates)
    second_output = _output(tuple(reversed(candidates)))
    first = _compress(first_output)
    second = compress_research_pool_for_test(
        second_output,
        {item.security_id: _project(item) for item in reversed(candidates)},
        _capability(),
        judgment_batch_hash="a" * 64,
    )
    assert [item.security_id for item in first.daily_decision.candidates] == ["A", "B", "C"]
    assert first.daily_decision == second.daily_decision
    assert first.content_hash == second.content_hash


def test_symmetric_tie_and_exposure_endpoint_order_is_only_serialization():
    tied = (
        _judgment(
            "T1", OpportunityType.COMPANY_EVENT_REVALUATION, layer=CandidateLayer.INTERNAL, tied=True
        ),
        _judgment(
            "T2", OpportunityType.COMPANY_EVENT_REVALUATION, layer=CandidateLayer.INTERNAL, tied=True
        ),
    )
    tie_output = _output(tied, stage_two_ties=(("T1", "T2"),))
    reversed_tie_raw = json.loads(tie_output.model_dump_json())
    reversed_tie_raw["comparison_stage_receipts"][1]["cohorts"][0][
        "indistinguishable_groups"
    ][0].reverse()
    reversed_tie_raw["capacity_tie_abstentions"][0]["security_ids"].reverse()
    reversed_tie = DailyJudgeOutput.model_validate(reversed_tie_raw)
    assert _compress(tie_output).content_hash == _compress(reversed_tie).content_hash

    pair = (
        _judgment("A", _OPPORTUNITIES[0]),
        _judgment("B", _OPPORTUNITIES[1]),
    )
    exposure_output = _output(pair)
    reversed_exposure_raw = json.loads(exposure_output.model_dump_json())
    exposure_receipt = reversed_exposure_raw["comparison_stage_receipts"][2][
        "exposure_pair_receipts"
    ][0]
    exposure_receipt["left_security_id"], exposure_receipt["right_security_id"] = (
        exposure_receipt["right_security_id"],
        exposure_receipt["left_security_id"],
    )
    reversed_exposure = DailyJudgeOutput.model_validate(reversed_exposure_raw)
    assert _compress(exposure_output).content_hash == _compress(reversed_exposure).content_hash


def test_decision_schema_contains_no_score_probability_or_future_result_fields():
    candidate = _judgment("A", _OPPORTUNITIES[0])
    receipt = _compress(_output((candidate,)))
    schema = type(receipt).model_json_schema()

    def property_names(value):
        if isinstance(value, dict):
            names = set(value.get("properties", {}))
            for item in value.values():
                names.update(property_names(item))
            return names
        if isinstance(value, list):
            names = set()
            for item in value:
                names.update(property_names(item))
            return names
        return set()

    names = {name.lower() for name in property_names(schema)}
    for forbidden in (
        "score",
        "weight",
        "probability",
        "confidence",
        "future_return",
        "target_touched",
        "terminal_return",
    ):
        assert forbidden not in names
