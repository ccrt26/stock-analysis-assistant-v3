from __future__ import annotations

import importlib.util
import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass, fields, replace
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

import stock_analyzer.evaluation.v3_backtest.judge as judge_module
import stock_analyzer.evaluation.v3_backtest.contracts as contracts_module
from stock_analyzer.evaluation.v3_backtest.contracts import CandidateLayer, OpportunityType
from stock_analyzer.evaluation.v3_backtest.judge import (
    CandidateJudgment,
    DailyJudgeOutput,
    FrozenDecisionJudge,
    JudgeError,
    JudgeInstabilityError,
    VerifiedJudgmentBatch,
    build_judge_day_packet,
    build_three_date_consistency_gate,
    canonical_judgment_batch_receipt_hash,
    require_verified_judge_day_packet,
    require_verified_judgment_batch,
)


@dataclass(frozen=True)
class TrustedChain:
    batch: object
    bundle: object
    day_packet: object


_ACTIVE_HOTSPOT_IDENTITY = None


@pytest.fixture(scope="module")
def trusted_chain(tmp_path_factory) -> TrustedChain:
    path = Path("tests/evaluation/v3_backtest/test_evidence.py")
    spec = importlib.util.spec_from_file_location("task6_real_task5_chain", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    captured = {}
    original = module.build_candidate_packet

    def capture(batch, bundle, security_id):
        packet = original(batch, bundle, security_id)
        captured.update(batch=batch, bundle=bundle, packet=packet)
        return packet

    module.build_candidate_packet = capture
    module.test_actual_task3_materialization_can_feed_current_task4_and_task5(
        tmp_path_factory.mktemp("task6-real-chain")
    )
    day_packet = build_judge_day_packet(captured["batch"], captured["bundle"])
    assert day_packet.candidates
    return TrustedChain(captured["batch"], captured["bundle"], day_packet)


def _selected_packet(day_packet):
    return day_packet.candidates[0]


def _selected_card(packet, opportunity=OpportunityType.EARNINGS_REVALUATION):
    return next(card for card in packet.opportunity_cards if card.opportunity is opportunity)


def _all_binding_ids(card):
    return tuple(dict.fromkeys(eid for _, ids in card.requirement_evidence_ids for eid in ids))


def _text(text, ids):
    return {"text": text, "evidence_ids": list(ids)}


def _context_effect(section, effect, *, consequence_ids=()):
    source_ids = tuple(section.evidence_ids[:1])
    consequences = {
        "company_evidence_bar": "standard",
        "company_evidence_bar_satisfied": True,
        "focus_eligible": True,
        "invalidation_check": "normal",
        "causal_chain": "neutral",
    }
    if effect == "supports_current_opportunity":
        consequences["causal_chain"] = "supported"
    elif effect == "raises_company_evidence_bar":
        consequences["company_evidence_bar"] = "raised"
    elif effect == "limits_focus":
        consequences["focus_eligible"] = False
    elif effect == "accelerates_invalidation_check":
        consequences["invalidation_check"] = "accelerated"
    elif effect == "opposes_causal_chain":
        consequences.update(
            focus_eligible=False,
            invalidation_check="accelerated",
            causal_chain="opposed",
        )
    if section.availability.value == "not_available_as_of":
        effect = "not_applicable"
        consequence_ids = ()
        consequences = {
            "company_evidence_bar": "standard",
            "company_evidence_bar_satisfied": True,
            "focus_eligible": True,
            "invalidation_check": "normal",
            "causal_chain": "neutral",
        }
    return {
        "effect": effect,
        "source_section": section.name.value,
        "section_availability": section.availability.value,
        "source_section_hash": judge_module._stable_hash(section.model_dump(mode="json")),
        "judgment": _text("the dedicated context section changes the decision gate", source_ids),
        "consequence_evidence_ids": list(consequence_ids),
        **consequences,
    }


def _singleton_stage_receipts(candidate):
    security_id = candidate["security_id"]
    cited = candidate["decisive_comparison"]["judgment"]
    reversal = candidate["decisive_comparison"]["reversal_fact"]
    eligible = [security_id] if candidate["card_status"] == "ready" else []
    receipts = []
    for stage in (
            "same_hotspot_opportunity_role",
            "same_opportunity_cross_context",
            "cross_opportunity",
    ):
        identities = (
            candidate["hotspot_memberships"]
            if stage == "same_hotspot_opportunity_role"
            else (None,)
        ) or (None,)
        cohorts = [
            {
                "cohort_id": f"{stage}:singleton:{index}",
                "security_ids": [security_id],
                **(
                    {"hotspot_identity": {
                        "group_type": identity["group_type"],
                        "group_code": identity["group_code"],
                    }}
                    if identity is not None else {}
                ),
                "decisive_edges": [],
                "indistinguishable_groups": [],
                "judgment": cited,
                "reversal_fact": reversal,
                "completed": True,
            }
            for index, identity in enumerate(identities)
        ] if eligible else []
        receipts.append({
            "stage": stage,
            "eligible_security_ids": eligible,
            "cohorts": cohorts,
        })
    receipts[-1]["cross_opportunity_assessments"] = ([
        {
            "security_id": security_id,
            "current_action_eligible": candidate["suggested_layer"] != "internal",
            "independent_role_supported": candidate["suggested_layer"] != "internal",
            "independent_role": cited,
            "reversal_fact": reversal,
        }
    ] if eligible else [])
    receipts[-1]["exposure_pair_receipts"] = []
    return receipts


def _edge(winner, dominated, stage, cited, reversal=None):
    return {
        "winner_security_id": winner,
        "dominated_security_id": dominated,
        "stage": stage,
        "judgment": cited,
        "reversal_fact": reversal or cited,
    }


def _cohort(stage, security_ids, cited, *, edges=(), groups=(), cohort_id="cohort", hotspot_identity=None):
    identity = hotspot_identity
    if stage == "same_hotspot_opportunity_role" and identity is None:
        identity = _ACTIVE_HOTSPOT_IDENTITY
    return {
        "cohort_id": f"{stage}:{cohort_id}",
        "security_ids": list(security_ids),
        **({"hotspot_identity": identity} if identity is not None else {}),
        "decisive_edges": list(edges),
        "indistinguishable_groups": [list(group) for group in groups],
        "judgment": cited,
        "reversal_fact": cited,
        "completed": True,
    }


def _stage(stage, eligible, cohorts):
    receipt = {
        "stage": stage,
        "eligible_security_ids": list(eligible),
        "cohorts": list(cohorts),
    }
    if stage == "cross_opportunity":
        cited = cohorts[0]["judgment"] if cohorts else _text("no cross-stage candidate remains", ())
        receipt["cross_opportunity_assessments"] = [
            {
                "security_id": security_id,
                "current_action_eligible": False,
                "independent_role_supported": False,
                "independent_role": cited,
                "reversal_fact": cited,
            }
            for security_id in eligible
        ]
        receipt["exposure_pair_receipts"] = [
            {
                "left_security_id": left,
                "right_security_id": right,
                "relationship": "independent",
                "capacity_compatible": True,
                "judgment": cited,
                "reversal_fact": cited,
            }
            for index, left in enumerate(eligible)
            for right in eligible[index + 1:]
        ]
    return receipt


def _copy_candidate(candidate, security_id):
    copied = json.loads(json.dumps(candidate))
    copied["security_id"] = security_id
    return copied


def _set_hotspot_memberships(candidate, memberships):
    evidence_id = candidate["evidence_refs"][0]
    candidate["hotspot_memberships"] = [
        {
            "group_type": group_type,
            "group_code": group_code,
            "membership_evidence_ids": [evidence_id],
            "hotspot_evidence_ids": [evidence_id],
            "source_identity_hash": judge_module._stable_hash(
                (group_type, group_code, evidence_id)
            ),
        }
        for group_type, group_code in memberships
    ]


def _valid_candidate(day_packet, *, layer=CandidateLayer.INTERNAL.value):
    global _ACTIVE_HOTSPOT_IDENTITY
    packet = _selected_packet(day_packet)
    card = _selected_card(packet)
    ids = _all_binding_ids(card)
    sections = {item.name.value: item for item in packet.sections}
    counter_ids = tuple(sections["counterevidence"].evidence_ids)
    unknown_ids = tuple(sections["unknowns"].evidence_ids)
    unknown_ids = tuple(
        dict.fromkeys(
            (*unknown_ids, *(eid for item in packet.unknowns for eid in item.evidence_ids))
        )
    )
    dispositions = [
        {
            "requirement": requirement,
            "disposition": "counterevidence",
            "judgment": _text("the supplied input does not support a positive driver", evidence_ids),
        }
        for requirement, evidence_ids in card.requirement_evidence_ids
    ]
    prepared = [
        value.knowledge_id
        for value in packet.knowledge_routing
        if value.status.value == "prepared_for_judgment"
    ]
    prepared_inputs = day_packet.prepared_knowledge_for(packet.security_id)
    proposition = {
        "primary_opportunity": card.opportunity.value,
        "why_now": _text("the complete inputs require an adverse judgment rather than a positive inference", ids),
        "next_validation": _text("wait for a new operating fact that reverses the adverse evidence", ids),
        "post_fact_price_response": _text("the observed response does not establish a new value source", ids),
        "price_confirmation": _text("price behavior is only an observed result", ids),
        "target_conditions": _text("a new supportive operating fact remains necessary", ids),
        "invalidation_condition": _text("invalidate the adverse reading only if the bound facts reverse", ids),
    }
    cited = set(ids)
    cited.update(counter_ids)
    cited.update(unknown_ids)
    cited.update(evidence_id for item in prepared_inputs for evidence_id in item.evidence_ids)
    market = sections["market_constraints"]
    hotspot = sections["hotspot_panorama"]
    price = sections["price_volume_liquidity"]
    hotspot_ids = tuple(hotspot.evidence_ids[:1])
    price_ids = tuple(price.evidence_ids[:1])
    cited.update(hotspot_ids)
    cited.update(price_ids)
    card_source = next(
        item
        for item in day_packet.card_statuses_for(packet.security_id)
        if item.opportunity is card.opportunity
    )
    memberships = [
        item.model_dump(mode="json")
        for item in day_packet.hotspot_memberships_for(packet.security_id)
    ]
    _ACTIVE_HOTSPOT_IDENTITY = (
        {
            "group_type": memberships[0]["group_type"],
            "group_code": memberships[0]["group_code"],
        }
        if memberships else None
    )
    return {
        "security_id": packet.security_id,
        "judgment_kind": "model_judgment",
        "primary_opportunity": card.opportunity.value,
        "overall_disposition": "counterevidence",
        "supporting_factors": [],
        "market_effect": _context_effect(
            market, "raises_company_evidence_bar", consequence_ids=ids
        ),
        "hotspot_effect": _context_effect(hotspot, "not_applicable"),
        "hotspot_memberships": memberships,
        "card_status": "ready",
        "card_status_source": card_source.model_dump(mode="json"),
        "price_role": {
            "role": "other_tradable",
            "source_section": "price_volume_liquidity",
            "section_availability": price.availability.value,
            "source_section_hash": judge_module._stable_hash(price.model_dump(mode="json")),
            "judgment": _text("price is an observed role rather than the opportunity source", price_ids),
        },
        "next_validation_state": {
            "disposition": "not_observable_as_of_date",
            "next_check": "ordinary",
            "judgment": _text("the next formal validation is not observable as of this date", ids),
        },
        "proposition": proposition,
        "directional_thesis": _text(
            "the complete evidence currently supports only an internal research judgment",
            ids,
        ),
        "new_driver_evidence_ids": [],
        "requirement_dispositions": dispositions,
        "prepared_knowledge_ids": prepared,
        "actually_used_knowledge": [],
        "unused_prepared_knowledge": [
            {
                "knowledge_id": item.knowledge_id,
                "entry_content_hash": item.entry_content_hash,
                "effect": item.effect.value,
                "reason": "not_decisive_for_this_judgment",
                "evidence_ids": list(item.evidence_ids),
            }
            for item in prepared_inputs
        ],
        "decisive_advantages": [],
        "decisive_comparison": {
            "comparator_security_ids": [],
            "comparison_role": "no_same_opportunity_peer",
            "judgment": _text("there is no decisive positive advantage", ids),
            "reversal_fact": _text("a new supportive operating disclosure would reverse this comparison", ids),
        },
        "capacity_tie_abstention": False,
        "counterevidence": [
            {
                "disposition": "present",
                "source_section": "counterevidence",
                "judgment": _text("this Task5 counterevidence input was considered", (evidence_id,)),
            }
            for evidence_id in counter_ids
        ] or [{
            "disposition": "none_supported_as_of_cutoff",
            "source_section": "counterevidence",
            "judgment": _text("no counterevidence was available as of the formation cutoff", ()),
        }],
        "unknowns": [
            {
                "disposition": "unknown",
                "source_section": "unknowns",
                "judgment": _text("this Task5 unknown input remains unresolved", (evidence_id,)),
            }
            for evidence_id in unknown_ids
        ] or [{
            "disposition": "unknown",
            "source_section": "unknowns",
            "judgment": _text("no unknown-section evidence was available as of the formation cutoff", ()),
        }],
        "next_fact": _text("the next formal operating disclosure is required", ids),
        "invalidation": proposition["invalidation_condition"],
        "suggested_layer": layer,
        "evidence_refs": sorted(cited),
    }


def _output(day_packet, candidate=None, *, stage_receipts=None, capacity_ties=()):
    selected = candidate or _valid_candidate(day_packet)
    return {
        "formation_date": day_packet.formation_date.isoformat(),
        "candidates": [selected],
        "comparison_stage_receipts": stage_receipts or _singleton_stage_receipts(selected),
        "capacity_tie_abstentions": list(capacity_ties),
    }


def _multi_output(day_packet, candidates, stage_receipts, capacity_ties=()):
    return {
        "formation_date": day_packet.formation_date.isoformat(),
        "candidates": list(candidates),
        "comparison_stage_receipts": list(stage_receipts),
        "capacity_tie_abstentions": list(capacity_ties),
    }


def _runner(outputs, *, version="codex-cli 0.144.0-alpha.4", returncode=0):
    queue = list(outputs)
    calls = []

    def run(command, *, cwd, input_text, env, timeout):
        calls.append((command, input_text, dict(env)))
        if command[-1] == "--version":
            return subprocess.CompletedProcess(command, 0, stdout=version, stderr="")
        if returncode:
            return subprocess.CompletedProcess(command, returncode, stdout="", stderr="unavailable")
        output_path = Path(command[command.index("--output-last-message") + 1])
        output_path.write_text(json.dumps(queue.pop(0)), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    return run, calls


def _judge(tmp_path, runner, *, run_id="task6-test", max_bytes=5_000_000):
    return FrozenDecisionJudge.for_test(
        run_id=run_id,
        ledger_path=tmp_path / "judge-ledger.json",
        runner=runner,
        binary_reader=lambda _: b"fixed-codex-binary",
        temp_root=tmp_path,
        max_request_bytes=max_bytes,
    )


def _preflight_and_judge(tmp_path, day_packet, outputs):
    runner, calls = _runner([{"formation_date": day_packet.formation_date.isoformat(), "candidates": []}, *outputs])
    judge = _judge(tmp_path, runner)
    preflight = judge.preflight(day_packet)
    return judge, preflight, calls


def test_day_packet_only_exists_from_real_verified_task4_task5_chain(trusted_chain):
    packet = require_verified_judge_day_packet(trusted_chain.day_packet)
    assert packet.route_batch_hash == trusted_chain.batch.batch_hash
    assert len(packet.receipt_hash) == 64
    with pytest.raises(TypeError):
        type(packet)()
    copied = object.__new__(type(packet))
    with pytest.raises(JudgeError, match="provenance"):
        require_verified_judge_day_packet(copied)


def test_day_packet_rechecks_upstream_identities_and_rejects_cross_bundle(trusted_chain):
    other = build_judge_day_packet(trusted_chain.batch, trusted_chain.bundle)
    assert other.receipt_hash == trusted_chain.day_packet.receipt_hash
    object.__setattr__(other, "_JudgeDayPacket__bundle", object())
    with pytest.raises((JudgeError, ValueError), match="bundle|provenance"):
        require_verified_judge_day_packet(other)


def test_future_semantic_dates_are_allowed_but_future_availability_is_not(trusted_chain):
    packet = _selected_packet(trusted_chain.day_packet)
    assert any(
        getattr(item, "field", "") in {"report_period", "valid_to", "execution_conditions"}
        or "2099-" in str(getattr(item, "value", ""))
        for item in (*packet.api_facts, *packet.local_observations)
    )
    require_verified_judge_day_packet(trusted_chain.day_packet)
    with pytest.raises(JudgeError, match="outcome"):
        judge_module._validate_closed_formation_input({"future_price_outcome": 1}, packet.cutoff)


def test_output_schema_has_no_score_probability_or_confidence_fields():
    schema = json.dumps(DailyJudgeOutput.model_json_schema()).lower()
    assert "overall_disposition" in schema
    for forbidden in ("score", "rating", "points", "probability", "odds", "confidence"):
        assert forbidden not in schema


def test_candidate_accepts_closed_context_card_price_and_validation_receipts(trusted_chain):
    candidate = CandidateJudgment.model_validate(_valid_candidate(trusted_chain.day_packet))
    assert candidate.price_role.role.value == "other_tradable"
    assert candidate.card_status_source.status.value == "ready"
    assert candidate.market_effect.source_section.value == "market_constraints"


@pytest.mark.parametrize("missing", ["market_effect", "hotspot_effect"])
def test_candidate_requires_cited_market_and_hotspot_effects(trusted_chain, missing):
    candidate = _valid_candidate(trusted_chain.day_packet)
    candidate.pop(missing)

    with pytest.raises(ValidationError):
        CandidateJudgment.model_validate(candidate)


@pytest.mark.parametrize(
    "card_status",
    ["insufficient_as_of_cutoff", "not_executable_with_local_data"],
)
def test_nonready_card_cannot_enter_an_action_layer(trusted_chain, card_status):
    candidate = _valid_candidate(
        trusted_chain.day_packet, layer=CandidateLayer.EARLY_VALIDATION.value
    )
    candidate["card_status"] = card_status

    with pytest.raises(ValidationError, match="ready|ten|layer"):
        CandidateJudgment.model_validate(candidate)


@pytest.mark.parametrize(
    ("effect", "layer"),
    [
        ("limits_focus", CandidateLayer.FOCUS.value),
        ("opposes_causal_chain", CandidateLayer.EARLY_VALIDATION.value),
    ],
)
def test_context_effect_changes_layer_eligibility(trusted_chain, effect, layer):
    candidate = _valid_candidate(trusted_chain.day_packet, layer=layer)
    candidate["market_effect"]["effect"] = effect

    with pytest.raises(ValidationError, match="context|focus|causal"):
        CandidateJudgment.model_validate(candidate)


def test_context_effect_evidence_is_bound_to_direction_and_accelerated_invalidation(
    trusted_chain,
):
    directional = _valid_candidate(
        trusted_chain.day_packet, layer=CandidateLayer.EARLY_VALIDATION.value
    )
    directional["market_effect"]["judgment"]["evidence_ids"] = ["context-only"]
    with pytest.raises(ValidationError, match="context|direction"):
        CandidateJudgment.model_validate(directional)

    accelerated = _valid_candidate(trusted_chain.day_packet)
    accelerated["market_effect"]["effect"] = "accelerates_invalidation_check"
    accelerated["market_effect"]["judgment"]["evidence_ids"] = ["context-only"]
    with pytest.raises(ValidationError, match="context|invalidation"):
        CandidateJudgment.model_validate(accelerated)


def test_market_and_hotspot_effects_are_bound_to_their_dedicated_sections(trusted_chain):
    candidate = _valid_candidate(trusted_chain.day_packet)
    hotspot_ids = candidate["hotspot_effect"]["judgment"]["evidence_ids"]
    assert hotspot_ids
    candidate["market_effect"]["judgment"]["evidence_ids"] = hotspot_ids
    with pytest.raises(ValueError, match="market|section|context"):
        judge_module._validate_output(
            DailyJudgeOutput.model_validate(_output(trusted_chain.day_packet, candidate)),
            trusted_chain.day_packet,
        )


@pytest.mark.parametrize(
    "mutation",
    [
        {"effect": "limits_focus"},
        {"effect": "raises_company_evidence_bar", "company_evidence_bar_satisfied": False},
        {"effect": "accelerates_invalidation_check", "invalidation_check": "normal"},
    ],
)
def test_every_context_effect_has_the_matching_structured_consequence(
    trusted_chain, mutation
):
    candidate = _valid_candidate(trusted_chain.day_packet)
    candidate["market_effect"].update(mutation)
    with pytest.raises(ValidationError, match="effect|consequence|evidence bar|invalidation"):
        CandidateJudgment.model_validate(candidate)


def test_price_role_is_closed_and_cannot_be_free_text(trusted_chain):
    candidate = _valid_candidate(trusted_chain.day_packet)
    candidate["price_role"]["role"] = "custom_momentum_label"
    with pytest.raises(ValidationError, match="price_role|role"):
        CandidateJudgment.model_validate(candidate)


def test_price_role_is_bound_to_the_dedicated_price_section(trusted_chain):
    candidate = _valid_candidate(trusted_chain.day_packet)
    packet = _selected_packet(trusted_chain.day_packet)
    sections = {item.name.value: item for item in packet.sections}
    price = sections["price_volume_liquidity"]
    assert candidate["price_role"]["source_section"] == "price_volume_liquidity"
    assert candidate["price_role"]["source_section_hash"] == judge_module._stable_hash(
        price.model_dump(mode="json")
    )
    candidate["price_role"]["judgment"]["evidence_ids"] = candidate[
        "proposition"
    ]["why_now"]["evidence_ids"]
    with pytest.raises(ValueError, match="price|section"):
        judge_module._validate_output(
            DailyJudgeOutput.model_validate(_output(trusted_chain.day_packet, candidate)),
            trusted_chain.day_packet,
        )


def test_verified_day_preserves_three_state_card_status_sources(trusted_chain):
    packet = _selected_packet(trusted_chain.day_packet)
    receipts = trusted_chain.day_packet.card_statuses_for(packet.security_id)
    assert {item.status.value for item in receipts}.issuperset(
        {"ready", "not_executable_with_local_data"}
    )
    assert all(item.source_card_hash and item.upstream_status for item in receipts)
    verified = require_verified_judge_day_packet(trusted_chain.day_packet)
    all_security_ids = (
        *(item.security_id for item in verified.candidates),
        *(item.security_id for item in verified.exclusions),
    )
    all_sources = tuple(
        source
        for security_id in all_security_ids
        for source in verified.card_statuses_for(security_id)
    )
    insufficient = next(
        item
        for item in all_sources
        if item.status.value == "insufficient_as_of_cutoff"
    )
    assert insufficient.missing_requirements
    assert insufficient.requirement_gap_sources


def test_verified_hotspot_identity_uses_membership_codes_not_candidate_section_hash(
    trusted_chain,
):
    packet = _selected_packet(trusted_chain.day_packet)
    memberships = trusted_chain.day_packet.hotspot_memberships_for(packet.security_id)
    section = next(item for item in packet.sections if item.name.value == "hotspot_panorama")
    assert memberships
    assert all(item.group_code and item.source_identity_hash for item in memberships)
    assert all(item.membership_evidence_ids for item in memberships)
    assert all(item.hotspot_evidence_ids for item in memberships)
    assert all(
        item.source_identity_hash
        != judge_module._stable_hash(section.model_dump(mode="json"))
        for item in memberships
    )


def test_hotspot_identity_requires_matching_membership_and_hotspot_rows(trusted_chain):
    packet = _selected_packet(trusted_chain.day_packet)
    joined = judge_module._derive_hotspot_memberships(packet)
    assert joined
    without_hotspot = packet.model_copy(
        update={
            "local_observations": tuple(
                item for item in packet.local_observations if item.dataset != "sector_hotspot"
            )
        }
    )
    assert judge_module._derive_hotspot_memberships(without_hotspot) == ()
    without_membership = packet.model_copy(
        update={
            "api_facts": tuple(
                item
                for item in packet.api_facts
                if item.dataset not in {"industry_member", "theme_member"}
            )
        }
    )
    assert judge_module._derive_hotspot_memberships(without_membership) == ()


def test_unavailable_context_cannot_assert_a_directional_effect(trusted_chain):
    candidate = _valid_candidate(trusted_chain.day_packet)
    unavailable = next(
        item
        for item in (candidate["market_effect"], candidate["hotspot_effect"])
        if item["section_availability"] == "not_available_as_of"
    )
    unavailable.update(
        effect="supports_current_opportunity",
        company_evidence_bar="standard",
        company_evidence_bar_satisfied=True,
        focus_eligible=True,
        invalidation_check="normal",
        causal_chain="supported",
        consequence_evidence_ids=candidate["proposition"]["why_now"]["evidence_ids"],
    )
    with pytest.raises(ValidationError, match="unavailable|not.applicable|context"):
        CandidateJudgment.model_validate(candidate)


def test_card_status_sources_are_opportunity_specific_and_ignore_unrelated_failures(
    trusted_chain,
):
    packet = _selected_packet(trusted_chain.day_packet)
    incomplete = next(card for card in packet.opportunity_cards if card.missing_requirements)
    source = judge_module._derive_card_status_source(packet, incomplete)
    assert {item.requirement for item in source.requirement_gap_sources} == set(
        incomplete.missing_requirements
    )
    related = {
        cause.dataset
        for gap in source.requirement_gap_sources
        for cause in gap.coverage_causes
    }
    unrelated = next(
        item
        for item in packet.input_coverage
        if item.status.value in {"not_materialized", "invalid_schema"}
        and item.dataset not in related
    )
    without_unrelated = packet.model_copy(
        update={
            "input_coverage": tuple(
                item for item in packet.input_coverage if item.dataset != unrelated.dataset
            )
        }
    )
    assert (
        judge_module._derive_card_status_source(without_unrelated, incomplete).status
        is source.status
    )


def test_verified_internal_judgment_can_preserve_a_nonexecutable_card(trusted_chain):
    packet = _selected_packet(trusted_chain.day_packet)
    card = next(card for card in packet.opportunity_cards if card.missing_requirements)
    source = next(
        item
        for item in trusted_chain.day_packet.card_statuses_for(packet.security_id)
        if item.opportunity is card.opportunity
    )
    assert source.status.value == "not_executable_with_local_data"
    candidate = _valid_candidate(trusted_chain.day_packet)
    candidate["primary_opportunity"] = card.opportunity.value
    candidate["proposition"]["primary_opportunity"] = card.opportunity.value
    candidate["card_status"] = source.status.value
    candidate["card_status_source"] = source.model_dump(mode="json")
    candidate["overall_disposition"] = "unknown"
    candidate["requirement_dispositions"] = [
        {
            "requirement": requirement,
            "disposition": "unknown",
            "judgment": _text(
                "the required input is unavailable in the verified local evidence path",
                (),
            ),
        }
        for requirement in card.missing_requirements
    ]
    output = DailyJudgeOutput.model_validate(
        _output(trusted_chain.day_packet, candidate)
    )
    judge_module._validate_output(output, trusted_chain.day_packet)
    assert output.candidates[0].suggested_layer is CandidateLayer.INTERNAL


def test_three_stage_receipts_are_complete_and_only_advance_nondominated_candidates(
    trusted_chain,
):
    left = _valid_candidate(trusted_chain.day_packet)
    right = _copy_candidate(left, "peer-a")
    right["hotspot_effect"]["source_section_hash"] = "f" * 64
    assert (
        left["hotspot_effect"]["source_section_hash"]
        != right["hotspot_effect"]["source_section_hash"]
    )
    cited = left["decisive_comparison"]["judgment"]
    first_stage = "same_hotspot_opportunity_role"
    stages = [
        _stage(
            first_stage,
            (left["security_id"], right["security_id"]),
            (
                _cohort(
                    first_stage,
                    (left["security_id"], right["security_id"]),
                    cited,
                    edges=(
                        _edge(left["security_id"], right["security_id"], first_stage, cited),
                    ),
                ),
            ),
        ),
        _stage(
            "same_opportunity_cross_context",
            (left["security_id"],),
            (_cohort("same_opportunity_cross_context", (left["security_id"],), cited),),
        ),
        _stage(
            "cross_opportunity",
            (left["security_id"],),
            (_cohort("cross_opportunity", (left["security_id"],), cited),),
        ),
    ]
    output = DailyJudgeOutput.model_validate(
        _multi_output(trusted_chain.day_packet, (left, right), stages)
    )
    assert output.comparison_stage_receipts[1].eligible_security_ids == (
        left["security_id"],
    )


@pytest.mark.parametrize("failure", ["incomplete", "opposite_edges", "cycle"])
def test_daily_dominance_graph_rejects_incomplete_contradictory_or_cyclic_receipts(
    trusted_chain, failure
):
    first = _valid_candidate(trusted_chain.day_packet)
    second = _copy_candidate(first, "peer-a")
    third = _copy_candidate(first, "peer-b")
    candidates = (first, second) if failure != "cycle" else (first, second, third)
    ids = tuple(item["security_id"] for item in candidates)
    cited = first["decisive_comparison"]["judgment"]
    stage = "same_hotspot_opportunity_role"
    if failure == "incomplete":
        edges = ()
    elif failure == "opposite_edges":
        edges = (
            _edge(ids[0], ids[1], stage, cited),
            _edge(ids[1], ids[0], stage, cited),
        )
    else:
        edges = (
            _edge(ids[0], ids[1], stage, cited),
            _edge(ids[1], ids[2], stage, cited),
            _edge(ids[2], ids[0], stage, cited),
        )
    receipts = (
        _stage(stage, ids, (_cohort(stage, ids, cited, edges=edges),)),
        _stage("same_opportunity_cross_context", (), ()),
        _stage("cross_opportunity", (), ()),
    )
    with pytest.raises(ValidationError, match="complete|contradict|cycle|dominance"):
        DailyJudgeOutput.model_validate(
            _multi_output(trusted_chain.day_packet, candidates, receipts)
        )


@pytest.mark.parametrize("failure", ["opposite", "edge_tie", "global_cycle"])
def test_overlapping_hotspot_cohorts_share_one_stage_wide_pair_dag(
    trusted_chain, failure
):
    first = _valid_candidate(trusted_chain.day_packet)
    second = _copy_candidate(first, "peer-a")
    candidates = [first, second]
    cited = first["decisive_comparison"]["judgment"]
    stage = "same_hotspot_opportunity_role"
    capacity_ties = ()
    if failure in {"opposite", "edge_tie"}:
        for candidate in candidates:
            _set_hotspot_memberships(
                candidate, (("industry", "I-shared"), ("theme", "T-shared"))
            )
        ids = tuple(item["security_id"] for item in candidates)
        first_outcome = _cohort(
            stage,
            ids,
            cited,
            edges=(_edge(ids[0], ids[1], stage, cited),),
            cohort_id="industry",
            hotspot_identity={"group_type": "industry", "group_code": "I-shared"},
        )
        second_outcome = _cohort(
            stage,
            ids,
            cited,
            edges=(
                (_edge(ids[1], ids[0], stage, cited),)
                if failure == "opposite" else ()
            ),
            groups=((ids,) if failure == "edge_tie" else ()),
            cohort_id="theme",
            hotspot_identity={"group_type": "theme", "group_code": "T-shared"},
        )
        if failure == "edge_tie":
            for candidate in candidates:
                candidate["capacity_tie_abstention"] = True
            capacity_ties = ({
                "source_stage": stage,
                "security_ids": list(ids),
                "judgment": cited,
                "reversal_fact": cited,
            },)
        cohorts = (first_outcome, second_outcome)
    else:
        third = _copy_candidate(first, "peer-b")
        candidates.append(third)
        _set_hotspot_memberships(first, (("industry", "I-one"), ("industry", "I-two")))
        _set_hotspot_memberships(second, (("industry", "I-one"), ("theme", "T-one")))
        _set_hotspot_memberships(third, (("theme", "T-one"), ("industry", "I-two")))
        ids = tuple(item["security_id"] for item in candidates)
        cohorts = (
            _cohort(stage, (ids[0], ids[1]), cited, edges=(_edge(ids[0], ids[1], stage, cited),), cohort_id="i1", hotspot_identity={"group_type": "industry", "group_code": "I-one"}),
            _cohort(stage, (ids[1], ids[2]), cited, edges=(_edge(ids[1], ids[2], stage, cited),), cohort_id="t1", hotspot_identity={"group_type": "theme", "group_code": "T-one"}),
            _cohort(stage, (ids[2], ids[0]), cited, edges=(_edge(ids[2], ids[0], stage, cited),), cohort_id="i2", hotspot_identity={"group_type": "industry", "group_code": "I-two"}),
        )
    receipts = (
        _stage(stage, ids, cohorts),
        _stage("same_opportunity_cross_context", (), ()),
        _stage("cross_opportunity", (), ()),
    )
    with pytest.raises(ValidationError, match="stage-wide|contradict|cycle|outcome"):
        DailyJudgeOutput.model_validate(
            _multi_output(
                trusted_chain.day_packet,
                tuple(candidates),
                receipts,
                capacity_ties,
            )
        )


def test_cross_stage_receipt_rejects_a_previously_dominated_entrant(trusted_chain):
    left = _valid_candidate(trusted_chain.day_packet)
    right = _copy_candidate(left, "peer-a")
    cited = left["decisive_comparison"]["judgment"]
    first = "same_hotspot_opportunity_role"
    receipts = (
        _stage(
            first,
            (left["security_id"], right["security_id"]),
            (
                _cohort(
                    first,
                    (left["security_id"], right["security_id"]),
                    cited,
                    edges=(_edge(left["security_id"], right["security_id"], first, cited),),
                ),
            ),
        ),
        _stage(
            "same_opportunity_cross_context",
            (left["security_id"], right["security_id"]),
            (
                _cohort(
                    "same_opportunity_cross_context",
                    (left["security_id"], right["security_id"]),
                    cited,
                    edges=(
                        _edge(
                            left["security_id"],
                            right["security_id"],
                            "same_opportunity_cross_context",
                            cited,
                        ),
                    ),
                ),
            ),
        ),
        _stage("cross_opportunity", (left["security_id"],), (_cohort("cross_opportunity", (left["security_id"],), cited),)),
    )
    with pytest.raises(ValidationError, match="eligible|dominated|prior stage"):
        DailyJudgeOutput.model_validate(
            _multi_output(trusted_chain.day_packet, (left, right), receipts)
        )


def test_every_dominated_candidate_is_internal_and_final_survivors_control_action(
    trusted_chain,
):
    winner = _valid_candidate(
        trusted_chain.day_packet, layer=CandidateLayer.EARLY_VALIDATION.value
    )
    loser = _copy_candidate(winner, "peer-a")
    cited = winner["decisive_comparison"]["judgment"]
    ids = (winner["security_id"], loser["security_id"])
    first = "same_hotspot_opportunity_role"
    receipts = (
        _stage(
            first,
            ids,
            (
                _cohort(
                    first,
                    ids,
                    cited,
                    edges=(_edge(ids[0], ids[1], first, cited),),
                ),
            ),
        ),
        _stage(
            "same_opportunity_cross_context",
            (ids[0],),
            (_cohort("same_opportunity_cross_context", (ids[0],), cited),),
        ),
        _stage(
            "cross_opportunity",
            (ids[0],),
            (_cohort("cross_opportunity", (ids[0],), cited),),
        ),
    )
    receipts[-1]["cross_opportunity_assessments"][0].update(
        current_action_eligible=True,
        independent_role_supported=True,
    )
    with pytest.raises(ValidationError, match="dominated|internal|survivor"):
        DailyJudgeOutput.model_validate(
            _multi_output(trusted_chain.day_packet, (winner, loser), receipts)
        )


def test_nonready_card_is_outside_every_dominance_stage(trusted_chain):
    packet = _selected_packet(trusted_chain.day_packet)
    card = next(card for card in packet.opportunity_cards if card.missing_requirements)
    source = next(
        item
        for item in trusted_chain.day_packet.card_statuses_for(packet.security_id)
        if item.opportunity is card.opportunity
    )
    candidate = _valid_candidate(trusted_chain.day_packet)
    candidate.update(
        primary_opportunity=card.opportunity.value,
        card_status=source.status.value,
        card_status_source=source.model_dump(mode="json"),
        overall_disposition="unknown",
    )
    candidate["proposition"]["primary_opportunity"] = card.opportunity.value
    candidate["requirement_dispositions"] = [
        {
            "requirement": requirement,
            "disposition": "unknown",
            "judgment": _text("the selected card requirement is unavailable", ()),
        }
        for requirement in card.missing_requirements
    ]
    raw = _output(trusted_chain.day_packet, candidate)
    output = DailyJudgeOutput.model_validate(raw)
    assert all(not stage.eligible_security_ids for stage in output.comparison_stage_receipts)


def test_ready_action_candidate_accepts_same_opportunity_nonready_internal_peer(
    trusted_chain,
):
    raw = _valid_candidate(
        trusted_chain.day_packet, layer=CandidateLayer.FOCUS.value
    )
    raw["overall_disposition"] = "supportive"
    raw["requirement_dispositions"] = [
        {**item, "disposition": "supportive"}
        for item in raw["requirement_dispositions"]
    ]
    driver = raw["requirement_dispositions"][0]["judgment"]["evidence_ids"][0]
    raw["new_driver_evidence_ids"] = [driver]
    raw["decisive_advantages"] = [raw["proposition"]["why_now"]]
    for item in raw["counterevidence"]:
        if driver in item["judgment"]["evidence_ids"]:
            item["disposition"] = "none_supported_as_of_cutoff"
    complete = set(raw["proposition"]["why_now"]["evidence_ids"])
    complete.update(
        evidence_id
        for item in raw["counterevidence"]
        if item["disposition"] == "present"
        for evidence_id in item["judgment"]["evidence_ids"]
    )
    complete.update(
        evidence_id
        for item in raw["unknowns"]
        for evidence_id in item["judgment"]["evidence_ids"]
    )
    raw["directional_thesis"] = _text(
        "the ready candidate remains actionable after the nonready peer is excluded",
        sorted(complete),
    )
    ready = CandidateJudgment.model_validate(raw)
    nonready = ready.model_copy(update={
        "security_id": "peer-nonready",
        "card_status": contracts_module.EvidenceCardStatus.INSUFFICIENT_AS_OF_CUTOFF,
        "suggested_layer": CandidateLayer.INTERNAL,
    })
    packet = _selected_packet(trusted_chain.day_packet)
    judge_module._validate_candidate(
        ready,
        packet,
        {ready.security_id: ready, nonready.security_id: nonready},
        trusted_chain.day_packet,
        {ready.security_id: packet, nonready.security_id: packet},
    )


def test_cross_opportunity_stage_requires_action_role_and_risk_receipts(trusted_chain):
    candidate = _valid_candidate(
        trusted_chain.day_packet, layer=CandidateLayer.EARLY_VALIDATION.value
    )
    complete = _output(trusted_chain.day_packet, candidate)
    DailyJudgeOutput.model_validate(complete)

    missing_role = json.loads(json.dumps(complete))
    missing_role["comparison_stage_receipts"][-1][
        "cross_opportunity_assessments"
    ] = []
    with pytest.raises(ValidationError, match="cross-opportunity|assess|eligible"):
        DailyJudgeOutput.model_validate(missing_role)

    unsupported_role = json.loads(json.dumps(complete))
    unsupported_role["comparison_stage_receipts"][-1][
        "cross_opportunity_assessments"
    ][0]["independent_role_supported"] = False
    with pytest.raises(ValidationError, match="action|independent role"):
        DailyJudgeOutput.model_validate(unsupported_role)


def test_stage_three_requires_one_exposure_disposition_for_every_pair(trusted_chain):
    left = _valid_candidate(trusted_chain.day_packet)
    right = _copy_candidate(left, "peer-a")
    packet = _selected_packet(trusted_chain.day_packet)
    other_source = next(
        item
        for item in trusted_chain.day_packet.card_statuses_for(packet.security_id)
        if item.status.value == "ready" and item.opportunity.value != left["primary_opportunity"]
    )
    right["primary_opportunity"] = other_source.opportunity.value
    right["proposition"]["primary_opportunity"] = other_source.opportunity.value
    right["card_status_source"] = other_source.model_dump(mode="json")
    ids = (left["security_id"], right["security_id"])
    cited = left["decisive_comparison"]["judgment"]
    first = "same_hotspot_opportunity_role"
    receipts = (
        _stage(
            first,
            ids,
            (
                _cohort(first, (ids[0],), cited, cohort_id="left"),
                _cohort(first, (ids[1],), cited, cohort_id="right"),
            ),
        ),
        _stage(
            "same_opportunity_cross_context",
            ids,
            (
                _cohort("same_opportunity_cross_context", (ids[0],), cited, cohort_id="left"),
                _cohort("same_opportunity_cross_context", (ids[1],), cited, cohort_id="right"),
            ),
        ),
        _stage(
            "cross_opportunity",
            ids,
            (
                _cohort(
                    "cross_opportunity",
                    ids,
                    cited,
                    edges=(_edge(ids[0], ids[1], "cross_opportunity", cited),),
                ),
            ),
        ),
    )
    receipts[-1]["exposure_pair_receipts"] = []
    with pytest.raises(ValidationError, match="exposure|independent|risk|pair"):
        DailyJudgeOutput.model_validate(
            _multi_output(trusted_chain.day_packet, (left, right), receipts)
        )


def test_independent_stage_three_pair_can_share_action_capacity(trusted_chain):
    left = _valid_candidate(
        trusted_chain.day_packet, layer=CandidateLayer.EARLY_VALIDATION.value
    )
    right = _copy_candidate(left, "peer-a")
    packet = _selected_packet(trusted_chain.day_packet)
    other_source = next(
        item
        for item in trusted_chain.day_packet.card_statuses_for(packet.security_id)
        if item.status.value == "ready" and item.opportunity.value != left["primary_opportunity"]
    )
    right["primary_opportunity"] = other_source.opportunity.value
    right["proposition"]["primary_opportunity"] = other_source.opportunity.value
    right["card_status_source"] = other_source.model_dump(mode="json")
    ids = (left["security_id"], right["security_id"])
    cited = left["decisive_comparison"]["judgment"]
    receipts = (
        _stage(
            "same_hotspot_opportunity_role",
            ids,
            (
                _cohort("same_hotspot_opportunity_role", (ids[0],), cited, cohort_id="left"),
                _cohort("same_hotspot_opportunity_role", (ids[1],), cited, cohort_id="right"),
            ),
        ),
        _stage(
            "same_opportunity_cross_context",
            ids,
            (
                _cohort("same_opportunity_cross_context", (ids[0],), cited, cohort_id="left"),
                _cohort("same_opportunity_cross_context", (ids[1],), cited, cohort_id="right"),
            ),
        ),
        _stage(
            "cross_opportunity",
            ids,
            (_cohort("cross_opportunity", ids, cited),),
        ),
    )
    for assessment in receipts[-1]["cross_opportunity_assessments"]:
        assessment.update(
            current_action_eligible=True,
            independent_role_supported=True,
        )
    output = DailyJudgeOutput.model_validate(
        _multi_output(trusted_chain.day_packet, (left, right), receipts)
    )
    assert all(
        item.current_action_eligible
        for item in output.comparison_stage_receipts[-1].cross_opportunity_assessments
    )
    incompatible = _multi_output(trusted_chain.day_packet, (left, right), receipts)
    incompatible["comparison_stage_receipts"][-1]["exposure_pair_receipts"][0].update(
        relationship="shared_risk",
        capacity_compatible=False,
    )
    with pytest.raises(ValidationError, match="risk|capacity|action"):
        DailyJudgeOutput.model_validate(incompatible)


def test_capacity_tie_is_cross_candidate_and_returns_the_whole_group_internal(trusted_chain):
    left = _valid_candidate(trusted_chain.day_packet)
    right = _copy_candidate(left, "peer-a")
    left["capacity_tie_abstention"] = True
    right["capacity_tie_abstention"] = True
    ids = (left["security_id"], right["security_id"])
    cited = left["decisive_comparison"]["judgment"]
    first = "same_hotspot_opportunity_role"
    receipts = (
        _stage(first, ids, (_cohort(first, ids, cited, groups=(ids,)),)),
        _stage("same_opportunity_cross_context", (), ()),
        _stage("cross_opportunity", (), ()),
    )
    tie = {
        "source_stage": first,
        "security_ids": list(ids),
        "judgment": cited,
        "reversal_fact": cited,
    }
    DailyJudgeOutput.model_validate(
        _multi_output(trusted_chain.day_packet, (left, right), receipts, (tie,))
    )
    right["suggested_layer"] = CandidateLayer.FOCUS.value
    with pytest.raises(ValidationError, match="capacity|internal|tie"):
        DailyJudgeOutput.model_validate(
            _multi_output(trusted_chain.day_packet, (left, right), receipts, (tie,))
        )


def test_judgment_cache_key_binds_every_context_and_forces_checkpoints():
    JudgmentCacheKey = judge_module.JudgmentCacheKey
    Checkpoint = contracts_module.ProjectDayCheckpoint
    values = {
        "origin": date(2026, 1, 8),
        "cutoff": "2026-01-08T23:59:59+08:00",
        "fact_manifest_hash": "1" * 64,
        "formula_version": "formula-v1",
        "knowledge_version": "knowledge-v1",
        "prompt_version": "prompt-v1",
        "project_state_hash": "2" * 64,
        "checkpoint": Checkpoint.ORDINARY,
        "comparator_cohort_hash": "3" * 64,
        "portfolio_exposure_hash": "4" * 64,
        "previous_judgment_hash": "5" * 64,
    }
    key = JudgmentCacheKey(**values)
    assert tuple(item.name for item in fields(JudgmentCacheKey)) == tuple(values)
    for name in values:
        if name == "checkpoint":
            continue
        replacement = date(2026, 1, 9) if name == "origin" else f"changed-{name}"
        assert replace(key, **{name: replacement}).cache_hash != key.cache_hash
    for checkpoint in (
        Checkpoint.DAY_5,
        Checkpoint.DAY_10,
        Checkpoint.DAY_20,
        Checkpoint.DAY_30,
    ):
        forced = replace(key, checkpoint=checkpoint)
        assert forced.force_rejudgment is True
        with pytest.raises(JudgeError, match="checkpoint|rejudgment|reuse"):
            judge_module.lookup_judgment_cache({forced: "stale"}, forced)
    assert key.force_rejudgment is False
    assert judge_module.lookup_judgment_cache({key: "cached"}, key) == "cached"
    with pytest.raises((TypeError, ValueError), match="checkpoint"):
        replace(key, checkpoint="project_day_5")


def test_prompt_freezes_three_stage_order_and_context_boundaries():
    prompt = judge_module._PROMPT_PATH.read_text(encoding="utf-8")
    ordered = (
        "same_hotspot_opportunity_role",
        "same_opportunity_cross_context",
        "cross_opportunity",
    )
    positions = tuple(prompt.index(value) for value in ordered)
    assert positions == tuple(sorted(positions))
    for required in (
        "capacity_tie_abstention",
        "hotspot_memberships",
        "exposure_pair_receipts",
        "requirement_gap_sources",
        "market_effect",
        "hotspot_effect",
        "card_status",
        "price_role",
        "next_validation_state",
    ):
        assert required in prompt
    assert "价格异常" in prompt and "产业趋势" in prompt
    assert "业绩质量" in prompt and "主要机会来源" in prompt


def test_ready_card_alone_cannot_create_a_noninternal_layer(trusted_chain):
    candidate = _valid_candidate(trusted_chain.day_packet, layer=CandidateLayer.FOCUS.value)
    candidate["requirement_dispositions"] = [
        {**item, "disposition": "supportive"} for item in candidate["requirement_dispositions"]
    ]
    candidate["decisive_advantages"] = [candidate["proposition"]["why_now"]]
    with pytest.raises(ValueError, match="action-oriented|supportive|layer"):
        judge_module._validate_output(
            DailyJudgeOutput.model_validate(_output(trusted_chain.day_packet, candidate)),
            trusted_chain.day_packet,
        )
    early = _valid_candidate(trusted_chain.day_packet, layer=CandidateLayer.EARLY_VALIDATION.value)
    with pytest.raises(ValueError, match="supportive directional thesis"):
        judge_module._validate_output(
            DailyJudgeOutput.model_validate(_output(trusted_chain.day_packet, early)),
            trusted_chain.day_packet,
        )


def test_selected_card_requires_every_requirement_binding(trusted_chain):
    candidate = _valid_candidate(trusted_chain.day_packet)
    candidate["requirement_dispositions"] = candidate["requirement_dispositions"][:-1]
    with pytest.raises(ValueError, match="requirement bindings"):
        judge_module._validate_output(
            DailyJudgeOutput.model_validate(_output(trusted_chain.day_packet, candidate)),
            trusted_chain.day_packet,
        )


def test_counterevidence_and_unknown_sections_are_exactly_reconciled(trusted_chain):
    candidate = _valid_candidate(trusted_chain.day_packet)
    if candidate["counterevidence"][0]["judgment"]["evidence_ids"]:
        candidate["counterevidence"][0]["judgment"]["evidence_ids"].pop()
        candidate["counterevidence"][0]["disposition"] = "none_supported_as_of_cutoff"
    else:
        candidate["unknowns"][0]["judgment"]["evidence_ids"] = [
            candidate["evidence_refs"][0]
        ]
    with pytest.raises(ValueError, match="section receipt"):
        judge_module._validate_output(
            DailyJudgeOutput.model_validate(_output(trusted_chain.day_packet, candidate)),
            trusted_chain.day_packet,
        )


def test_noninternal_model_judgment_requires_and_accepts_complete_directional_receipt(trusted_chain):
    candidate = _valid_candidate(
        trusted_chain.day_packet, layer=CandidateLayer.EARLY_VALIDATION.value
    )
    candidate["overall_disposition"] = "supportive"
    candidate["requirement_dispositions"] = [
        {**item, "disposition": "supportive"}
        for item in candidate["requirement_dispositions"]
    ]
    driver = candidate["requirement_dispositions"][0]["judgment"]["evidence_ids"][0]
    candidate["new_driver_evidence_ids"] = [driver]
    for item in candidate["counterevidence"]:
        if driver in item["judgment"]["evidence_ids"]:
            item["disposition"] = "none_supported_as_of_cutoff"
    complete = set(candidate["proposition"]["why_now"]["evidence_ids"])
    complete.update(
        evidence_id
        for item in candidate["counterevidence"]
        if item["disposition"] == "present"
        for evidence_id in item["judgment"]["evidence_ids"]
    )
    complete.update(
        evidence_id
        for item in candidate["unknowns"]
        for evidence_id in item["judgment"]["evidence_ids"]
    )
    candidate["directional_thesis"] = _text(
        "the cited driver remains supportive after every counterevidence and unknown input is handled",
        sorted(complete),
    )
    judge_module._validate_output(
        DailyJudgeOutput.model_validate(_output(trusted_chain.day_packet, candidate)),
        trusted_chain.day_packet,
    )
    conflicting = next(
        (
            item
            for item in candidate["counterevidence"]
            if driver in item["judgment"]["evidence_ids"]
        ),
        None,
    )
    if conflicting is not None:
        conflicting["disposition"] = "present"
        with pytest.raises(ValueError, match="conflicts with counterevidence"):
            judge_module._validate_output(
                DailyJudgeOutput.model_validate(_output(trusted_chain.day_packet, candidate)),
                trusted_chain.day_packet,
            )
        conflicting["disposition"] = "none_supported_as_of_cutoff"
    candidate["requirement_dispositions"][0]["disposition"] = "counterevidence"
    with pytest.raises(ValueError, match="supportive requirements"):
        judge_module._validate_output(
            DailyJudgeOutput.model_validate(_output(trusted_chain.day_packet, candidate)),
            trusted_chain.day_packet,
        )
    candidate["requirement_dispositions"][0]["disposition"] = "supportive"
    omitted = next(
        (
            item["judgment"]["evidence_ids"][0]
            for item in candidate["counterevidence"]
            if item["disposition"] == "present" and item["judgment"]["evidence_ids"]
        ),
        candidate["directional_thesis"]["evidence_ids"][-1],
    )
    candidate["directional_thesis"]["evidence_ids"].remove(omitted)
    with pytest.raises(ValueError, match="directional thesis omits"):
        judge_module._validate_output(
            DailyJudgeOutput.model_validate(_output(trusted_chain.day_packet, candidate)),
            trusted_chain.day_packet,
        )


def test_focus_comparison_cannot_select_only_a_favorable_subset(trusted_chain):
    raw = _valid_candidate(trusted_chain.day_packet, layer=CandidateLayer.FOCUS.value)
    raw["overall_disposition"] = "supportive"
    raw["requirement_dispositions"] = [
        {**item, "disposition": "supportive"} for item in raw["requirement_dispositions"]
    ]
    raw["decisive_advantages"] = [raw["proposition"]["why_now"]]
    raw["decisive_comparison"]["comparator_security_ids"] = ["peer-a"]
    raw["decisive_comparison"]["comparison_role"] = "same_opportunity_peer"
    candidate = CandidateJudgment.model_validate(raw)
    packet = _selected_packet(trusted_chain.day_packet)
    outputs = {candidate.security_id: candidate, "peer-a": candidate, "peer-b": candidate}
    with pytest.raises(ValueError, match="full same-opportunity cohort"):
        judge_module._validate_candidate(
            candidate,
            packet,
            outputs,
            trusted_chain.day_packet,
            {candidate.security_id: packet, "peer-a": packet, "peer-b": packet},
        )


@pytest.mark.parametrize(
    "forbidden",
    [
        "high probability",
        "confidence is high",
        "institutional buying",
        "smart money accumulation",
        "主力资金介入",
        "机构席位买入",
        "胜算较高",
        "两成空间",
        "翻一倍",
        "１２．５",
        "1e2",
        "2:1",
        "20%",
        "二十个百分点",
        "机构净流入",
        "大资金介入",
        "twenty percent",
        "twofold increase",
        "fund buying",
    ],
)
def test_recursive_text_guard_rejects_predictive_identity_and_unsupported_quantity(
    trusted_chain, forbidden
):
    candidate = _valid_candidate(trusted_chain.day_packet)
    candidate["unknowns"][0]["judgment"]["text"] = forbidden
    with pytest.raises(ValueError):
        judge_module._validate_output(
            DailyJudgeOutput.model_validate(_output(trusted_chain.day_packet, candidate)),
            trusted_chain.day_packet,
        )


@pytest.mark.parametrize(
    "forbidden",
    ["high score", "high probability", "institutional buying", "unsupported 12.5"],
)
def test_context_effect_text_uses_the_same_language_and_numeric_gate(
    trusted_chain, forbidden
):
    candidate = _valid_candidate(trusted_chain.day_packet)
    candidate["market_effect"]["judgment"]["text"] = forbidden

    with pytest.raises(ValueError):
        judge_module._validate_output(
            DailyJudgeOutput.model_validate(_output(trusted_chain.day_packet, candidate)),
            trusted_chain.day_packet,
        )


def test_knowledge_use_receipt_binds_content_effect_purpose_and_output_fields(trusted_chain):
    packet = _selected_packet(trusted_chain.day_packet)
    prepared = trusted_chain.day_packet.prepared_knowledge_for(packet.security_id)
    if not prepared:
        pytest.skip("real adverse fixture has no effective prepared knowledge")
    candidate = _valid_candidate(trusted_chain.day_packet)
    item = prepared[0]
    candidate["actually_used_knowledge"] = [
        {
            "knowledge_id": item.knowledge_id,
            "entry_content_hash": item.entry_content_hash,
            "effect": item.effect.value,
            "prepared_purpose": item.prepared_purpose,
            "allowed_use_hash": item.allowed_use_hash,
            "selected_allowed_use": item.selected_allowed_use,
            "applied_to_fields": ["invalidation"],
            "satisfied_prerequisites": list(item.prerequisites),
            "considered_counterevidence": list(item.counter_evidence),
            "use_summary": _text("the governed boundary limits interpretation", item.evidence_ids),
        }
    ]
    candidate["unused_prepared_knowledge"] = [
        value
        for value in candidate["unused_prepared_knowledge"]
        if value["knowledge_id"] != item.knowledge_id
    ]
    candidate["proposition"]["invalidation_condition"]["evidence_ids"] = sorted(
        set(candidate["proposition"]["invalidation_condition"]["evidence_ids"])
        | set(item.evidence_ids)
    )
    candidate["invalidation"] = candidate["proposition"]["invalidation_condition"]
    candidate["evidence_refs"] = sorted(set(candidate["evidence_refs"]) | set(item.evidence_ids))
    output = DailyJudgeOutput.model_validate(_output(trusted_chain.day_packet, candidate))
    judge_module._validate_output(output, trusted_chain.day_packet)
    candidate["actually_used_knowledge"][0]["applied_to_fields"] = ["why_now"]
    with pytest.raises(ValueError, match="applied-to field"):
        judge_module._validate_output(
            DailyJudgeOutput.model_validate(_output(trusted_chain.day_packet, candidate)),
            trusted_chain.day_packet,
        )
    candidate["actually_used_knowledge"][0]["applied_to_fields"] = ["invalidation"]
    candidate["actually_used_knowledge"][0]["entry_content_hash"] = "0" * 64
    with pytest.raises(ValueError, match="knowledge"):
        judge_module._validate_output(
            DailyJudgeOutput.model_validate(_output(trusted_chain.day_packet, candidate)),
            trusted_chain.day_packet,
        )


def test_preflight_locks_binary_prompt_schema_command_environment_and_capacity(tmp_path, trusted_chain):
    judge, preflight, calls = _preflight_and_judge(tmp_path, trusted_chain.day_packet, [_output(trusted_chain.day_packet)])
    assert preflight.schema_compatible is True
    assert preflight.request_bytes <= preflight.max_request_bytes
    assert len(preflight.binary_sha256) == len(preflight.command_sha256) == 64
    batch = judge.judge(trusted_chain.day_packet, preflight)
    with pytest.raises(JudgeError, match="test-only"):
        require_verified_judgment_batch(batch)
    assert require_verified_judgment_batch(batch, allow_test_only=True) is batch
    assert batch.receipt.run_config_hash == preflight.run_config_hash
    expected_raw = json.dumps(_output(trusted_chain.day_packet)).encode()
    assert batch.receipt.attempts[-1].raw_output_sha256 == hashlib.sha256(expected_raw).hexdigest()
    assert batch.receipt.attempts[-1].returncode == 0
    assert "--output-schema" in calls[1][0]
    assert "formation_input" in json.loads(calls[1][1])
    assert json.loads(calls[1][1])["formation_input"]["candidates"]


def test_persistent_production_commitment_is_content_addressed(tmp_path):
    config_values = {
        "run_id": "committed-run",
        "binary_path": "/fixed/codex",
        "binary_sha256": "1" * 64,
        "cli_version": "fixed-version",
        "model": "fixed-model",
        "reasoning_effort": "high",
        "prompt_sha256": "2" * 64,
        "schema_sha256": "3" * 64,
        "command_sha256": "4" * 64,
        "environment_sha256": "5" * 64,
        "max_request_bytes": 1000,
        "runtime_attestation": "production",
    }
    config_values["config_hash"] = judge_module._stable_hash(config_values)
    commitment = {
        "commitment_version": "v3-judge-run-config-v1",
        "committed_at": "2026-07-17T00:00:00+08:00",
        "experiment_config_sha256": "6" * 64,
        "config": config_values,
    }
    commitment["commitment_hash"] = judge_module._stable_hash(commitment)
    path = tmp_path / "judge-run-commitment.json"
    path.write_text(json.dumps(commitment), encoding="utf-8")
    loaded = judge_module.load_judge_run_config_commitment(path)
    assert loaded.commitment_hash == commitment["commitment_hash"]
    commitment["config"]["model"] = "changed-model"
    path.write_text(json.dumps(commitment), encoding="utf-8")
    with pytest.raises(JudgeError, match="commitment"):
        judge_module.load_judge_run_config_commitment(path)


def test_preflight_fails_closed_on_context_capacity(tmp_path, trusted_chain):
    runner, _ = _runner([])
    judge = _judge(tmp_path, runner, max_bytes=10)
    with pytest.raises(JudgeError, match="capacity"):
        judge.preflight(trusted_chain.day_packet)


def test_process_failure_is_not_a_validation_retry(tmp_path, trusted_chain):
    runner, calls = _runner([], returncode=2)
    judge = _judge(tmp_path, runner)
    with pytest.raises(JudgeError, match="fallback"):
        judge.preflight(trusted_chain.day_packet)
    assert len(calls) == 2


def test_correction_contains_no_previous_output(tmp_path, trusted_chain):
    invalid = _valid_candidate(trusted_chain.day_packet)
    invalid["prepared_knowledge_ids"] = ["invented"]
    judge, preflight, calls = _preflight_and_judge(
        tmp_path,
        trusted_chain.day_packet,
        [_output(trusted_chain.day_packet, invalid), _output(trusted_chain.day_packet)],
    )
    batch = judge.judge(trusted_chain.day_packet, preflight)
    assert require_verified_judgment_batch(batch, allow_test_only=True)
    correction = json.loads(calls[-1][1])
    assert "previous_output" not in correction
    assert "validation_failure" not in correction
    assert correction["correction"]["kind"] == "structure_only"


def test_verified_output_is_opaque_content_addressed_and_tamper_evident(tmp_path, trusted_chain):
    judge, preflight, _ = _preflight_and_judge(tmp_path, trusted_chain.day_packet, [_output(trusted_chain.day_packet)])
    batch = judge.judge(trusted_chain.day_packet, preflight)
    assert isinstance(batch, VerifiedJudgmentBatch)
    assert len(batch.batch_hash) == 64
    assert canonical_judgment_batch_receipt_hash(batch.receipt_preimage) == batch.batch_hash
    with pytest.raises(TypeError):
        VerifiedJudgmentBatch()
    with pytest.raises(JudgeError, match="test-only"):
        require_verified_judgment_batch(batch)
    assert require_verified_judgment_batch(batch, allow_test_only=True) is batch
    object.__setattr__(batch, "_VerifiedJudgmentBatch__batch_hash", "0" * 64)
    with pytest.raises(JudgeError, match="hash"):
        require_verified_judgment_batch(batch, allow_test_only=True)


def test_primary_day_is_persistent_across_judge_instances(tmp_path, trusted_chain):
    runner, _ = _runner([
        {"formation_date": trusted_chain.day_packet.formation_date.isoformat(), "candidates": []},
        _output(trusted_chain.day_packet),
    ])
    first = _judge(tmp_path, runner, run_id="persistent")
    preflight = first.preflight(trusted_chain.day_packet)
    first.judge(trusted_chain.day_packet, preflight)
    second = _judge(tmp_path, runner, run_id="persistent")
    with pytest.raises(JudgeError, match="primary"):
        second.judge(trusted_chain.day_packet, preflight)
    ledger = json.loads((tmp_path / "judge-ledger.json").read_text(encoding="utf-8"))
    assert ledger["sequence"] == 1
    assert (tmp_path / "judge-ledger.json.lock").exists()


def test_consistency_audit_keeps_both_verified_outputs_and_security_diagnostics(tmp_path, trusted_chain):
    changed = _valid_candidate(trusted_chain.day_packet)
    changed["directional_thesis"]["text"] = (
        "the complete evidence still supports only a changed internal research judgment"
    )
    runner, _ = _runner([
        {"formation_date": trusted_chain.day_packet.formation_date.isoformat(), "candidates": []},
        _output(trusted_chain.day_packet),
        _output(trusted_chain.day_packet, changed),
    ])
    judge = _judge(tmp_path, runner, run_id="audit")
    preflight = judge.preflight(trusted_chain.day_packet)
    with pytest.raises(JudgeInstabilityError) as error:
        judge.audit_consistency(trusted_chain.day_packet, preflight)
    audit = error.value.audit
    assert require_verified_judgment_batch(audit.primary_batch, allow_test_only=True)
    assert require_verified_judgment_batch(audit.repeat_batch, allow_test_only=True)
    assert _selected_packet(trusted_chain.day_packet).security_id in audit.mismatches[0]
    assert any("directional_signature" in item for item in audit.mismatches)
    object.__setattr__(audit, "stable", True)
    with pytest.raises(JudgeError, match="audit"):
        judge_module._require_audit(audit, allow_test_only=True)


def test_consistency_signature_covers_stage_receipts_and_new_candidate_contracts(trusted_chain):
    base = _valid_candidate(trusted_chain.day_packet)
    first_raw = _output(trusted_chain.day_packet, base)
    first = DailyJudgeOutput.model_validate(first_raw)

    stage_changed = json.loads(json.dumps(first_raw))
    stage_changed["comparison_stage_receipts"][0]["cohorts"][0]["judgment"]["text"] = (
        "the complete stage receipt has a changed auditable judgment"
    )
    stage_mismatches = judge_module._consistency_mismatches(
        first, DailyJudgeOutput.model_validate(stage_changed)
    )
    assert "daily:comparison_stage_receipts" in stage_mismatches

    candidate_changed = json.loads(json.dumps(base))
    candidate_changed["market_effect"]["source_section_hash"] = "0" * 64
    candidate_changed["hotspot_effect"]["source_section_hash"] = "1" * 64
    candidate_changed["card_status_source"]["source_card_hash"] = "2" * 64
    candidate_changed["price_role"]["judgment"]["text"] = (
        "the price-role receipt has a changed auditable judgment"
    )
    candidate_changed["next_validation_state"]["next_check"] = "day_5"
    candidate_mismatches = judge_module._consistency_mismatches(
        first,
        DailyJudgeOutput.model_validate(
            _output(trusted_chain.day_packet, candidate_changed)
        ),
    )
    assert any("directional_signature" in item for item in candidate_mismatches)


def test_three_date_gate_rejects_missing_or_forged_audits():
    with pytest.raises(JudgeError, match="three fixed smoke dates"):
        build_three_date_consistency_gate(())
    with pytest.raises(JudgeError, match="provenance"):
        build_three_date_consistency_gate((object(), object(), object()))


def test_required_collections_cannot_be_silently_empty(trusted_chain):
    candidate = _valid_candidate(trusted_chain.day_packet)
    candidate["counterevidence"] = []
    with pytest.raises(ValidationError):
        CandidateJudgment.model_validate(candidate)
    candidate = _valid_candidate(trusted_chain.day_packet)
    candidate["unknowns"] = []
    with pytest.raises(ValidationError):
        CandidateJudgment.model_validate(candidate)
