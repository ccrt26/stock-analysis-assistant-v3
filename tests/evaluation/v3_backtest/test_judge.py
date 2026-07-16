from __future__ import annotations

import importlib.util
import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

import stock_analyzer.evaluation.v3_backtest.judge as judge_module
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


def _valid_candidate(day_packet, *, layer=CandidateLayer.INTERNAL.value):
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
    return {
        "security_id": packet.security_id,
        "judgment_kind": "model_judgment",
        "primary_opportunity": card.opportunity.value,
        "overall_disposition": "counterevidence",
        "supporting_factors": [],
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


def _output(day_packet, candidate=None):
    return {
        "formation_date": day_packet.formation_date.isoformat(),
        "candidates": [candidate or _valid_candidate(day_packet)],
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
