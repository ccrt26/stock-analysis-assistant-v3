from __future__ import annotations

import json

import pytest

from stock_analyzer.data.readiness import FormalRunState
from stock_analyzer.ops.activation import hash_artifact_tree
from stock_analyzer.ops.formal_strategy_runtime import (
    analyze_formal_inputs,
    express_formal_analysis,
    render_formal_report,
    verify_staged_formal_report,
)
from stock_analyzer.storage.repositories import InMemoryAnalysisRepository
from tests.test_formal_strategy_runtime import (
    CODES,
    candidate_set,
    complete_payloads,
    ready_receipt,
)


def analysis_output():
    return analyze_formal_inputs(
        ready_receipt(),
        candidate_set(ordered=(CODES[-1],), active=()),
        complete_payloads((CODES[-1],)),
        InMemoryAnalysisRepository(),
    )


def rendering_receipt(output):
    return ready_receipt().model_copy(
        update={
            "state": FormalRunState.RENDERING,
            "evidence_hashes": output.evidence_hashes,
        }
    )


def test_formal_renderer_writes_production_report_and_receipt_manifest(tmp_path):
    output = analysis_output()
    receipt = rendering_receipt(output)

    render_formal_report(tmp_path, receipt, output.value, narrative=None)

    latest = json.loads((tmp_path / "data/latest.json").read_text(encoding="utf-8"))
    manifest = json.loads((tmp_path / "data/formal-run.json").read_text(encoding="utf-8"))
    assert latest["report_mode"] == "production"
    assert latest["is_fixture"] is False
    assert manifest == {
        "acquisition_contract_version": "formal-v2",
        "candidate_set_id": "candidate-set-1",
        "evidence_hashes": output.evidence_hashes,
        "input_set_id": "input-set-1",
        "report_cutoff": receipt.report_cutoff.isoformat(),
        "run_id": "formal-2026-07-10",
    }


def test_staged_verifier_rejects_fixture_text_hash_mismatch_or_wrong_input_set(tmp_path):
    output = analysis_output()
    receipt = rendering_receipt(output)
    render_formal_report(tmp_path, receipt, output.value, narrative=None)
    hashes = hash_artifact_tree(tmp_path)
    verify_receipt = receipt.model_copy(update={"state": FormalRunState.VERIFYING})
    assert verify_staged_formal_report(tmp_path, hashes, verify_receipt) is True

    latest_path = tmp_path / "data/latest.json"
    latest = json.loads(latest_path.read_text(encoding="utf-8"))
    latest["report_mode"] = "fixture"
    latest_path.write_text(json.dumps(latest, ensure_ascii=False), encoding="utf-8")
    assert verify_staged_formal_report(
        tmp_path,
        hash_artifact_tree(tmp_path),
        verify_receipt,
    ) is False
    assert verify_staged_formal_report(tmp_path, hashes, verify_receipt) is False

    render_formal_report(tmp_path, receipt, output.value, narrative=None)
    manifest_path = tmp_path / "data/formal-run.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["input_set_id"] = "wrong-input"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert verify_staged_formal_report(
        tmp_path,
        hash_artifact_tree(tmp_path),
        verify_receipt,
    ) is False


def test_expression_client_receives_structured_payload_only_and_cannot_add_ledger_facts():
    output = analysis_output()
    evidence_id = output.value.evidence_packages[0].evidence_id

    class ExpressionClient:
        def __init__(self, result):
            self.result = result
            self.received = None

        def express(self, payload):
            self.received = payload
            return self.result

    accepted = ExpressionClient({evidence_id: "基于既有证据的表达"})
    narrative = express_formal_analysis(ready_receipt(), output.value, accepted)
    assert accepted.received is output.value
    assert narrative == {evidence_id: "基于既有证据的表达"}
    assert all("kind" not in value for value in narrative.values())

    rejected = ExpressionClient({"new-ledger-fact": "未经证据支持的新事实"})
    with pytest.raises(ValueError, match="unknown evidence id"):
        express_formal_analysis(ready_receipt(), output.value, rejected)


def test_no_llm_configuration_renders_deterministic_formal_report(tmp_path):
    output = analysis_output()
    receipt = rendering_receipt(output)

    assert express_formal_analysis(ready_receipt(), output.value, client=None) is None
    render_formal_report(tmp_path, receipt, output.value, narrative=None)
    first = hash_artifact_tree(tmp_path)
    render_formal_report(tmp_path, receipt, output.value, narrative=None)

    assert hash_artifact_tree(tmp_path) == first
