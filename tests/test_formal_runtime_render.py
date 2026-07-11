from __future__ import annotations

import json
from datetime import date

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
from stock_analyzer.ops.formal_narrative import NarrativePoint, validate_formal_narrative
from stock_analyzer.ops.verify import verify_production_result
from tests.test_formal_narrative import _valid_narrative


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
    narrative = _valid_narrative(output.value)

    render_formal_report(tmp_path, receipt, output.value, narrative=narrative)

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
    narrative = _valid_narrative(output.value)
    render_formal_report(tmp_path, receipt, output.value, narrative=narrative)
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

    render_formal_report(tmp_path, receipt, output.value, narrative=narrative)
    manifest_path = tmp_path / "data/formal-run.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["input_set_id"] = "wrong-input"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert verify_staged_formal_report(
        tmp_path,
        hash_artifact_tree(tmp_path),
        verify_receipt,
    ) is False


def test_staged_verifier_rejects_json_only_narrative(tmp_path):
    output = analysis_output()
    receipt = rendering_receipt(output)
    narrative = _valid_narrative(output.value)
    render_formal_report(tmp_path, receipt, output.value, narrative=narrative)
    stock_path = (
        tmp_path
        / "daily"
        / output.value.trade_date.isoformat()
        / "stocks"
        / f"{narrative.stocks[0].ts_code}.html"
    )
    stock_path.write_text(
        stock_path.read_text(encoding="utf-8").replace(
            narrative.stocks[0].narrative_marker,
            "",
        ),
        encoding="utf-8",
    )
    verify_receipt = receipt.model_copy(update={"state": FormalRunState.VERIFYING})

    assert verify_staged_formal_report(
        tmp_path,
        hash_artifact_tree(tmp_path),
        verify_receipt,
    ) is False


def test_staged_verifier_rejects_internal_terms_in_main_view(tmp_path):
    output = analysis_output()
    receipt = rendering_receipt(output)
    narrative = _valid_narrative(output.value)
    render_formal_report(tmp_path, receipt, output.value, narrative=narrative)
    home = tmp_path / "index.html"
    home.write_text(
        home.read_text(encoding="utf-8").replace(
            "市场总体结论",
            "Gate receipt input set",
        ),
        encoding="utf-8",
    )
    verify_receipt = receipt.model_copy(update={"state": FormalRunState.VERIFYING})

    assert verify_staged_formal_report(
        tmp_path,
        hash_artifact_tree(tmp_path),
        verify_receipt,
    ) is False


def test_production_verifier_repeats_readability_gate_after_activation(tmp_path):
    output = analysis_output()
    receipt = rendering_receipt(output)
    narrative = _valid_narrative(output.value)
    reports = tmp_path / "reports"
    render_formal_report(reports, receipt, output.value, narrative=narrative)

    class Repository:
        def load_daily_recommendations(self, trade_date):
            return output.value.recommendations

        def load_evidence_packages(self, trade_date):
            return output.value.evidence_packages

        def load_evaluation_tasks(self, trade_date):
            return output.value.evaluation_tasks

    activated = receipt.model_copy(
        update={
            "state": FormalRunState.REPORT_GENERATED,
            "artifact_hashes": hash_artifact_tree(reports),
            "local_activation_id": "activation-1",
            "ledger_activation_id": "activation-1",
        }
    )
    accepted = verify_production_result(
        tmp_path,
        Repository(),
        output.value.trade_date,
        receipt=activated,
    )
    assert accepted.passed is True

    home = reports / "index.html"
    home.write_text(
        home.read_text(encoding="utf-8").replace(
            "市场总体结论",
            "Gate receipt input set",
        ),
        encoding="utf-8",
    )
    rejected = verify_production_result(
        tmp_path,
        Repository(),
        output.value.trade_date,
        receipt=activated,
    )
    assert rejected.passed is False
    assert any(
        failure.code == "report_readability_invalid"
        for failure in rejected.failures
    )


def test_expression_client_receives_structured_payload_and_returns_validated_narrative():
    output = analysis_output()
    expected = _valid_narrative(output.value)

    class ExpressionClient:
        def __init__(self, result):
            self.result = result
            self.received = None

        def express(self, payload):
            self.received = payload
            return self.result

    accepted = ExpressionClient(expected)
    narrative = express_formal_analysis(ready_receipt(), output.value, accepted)
    assert accepted.received is output.value
    assert narrative == expected

    rejected_stock = expected.stocks[0].model_copy(update={"action": "小仓试探"})
    rejected = ExpressionClient(
        expected.model_copy(update={"stocks": [rejected_stock]})
    )
    with pytest.raises(ValueError, match="decision lock"):
        express_formal_analysis(ready_receipt(), output.value, rejected)


def test_no_llm_configuration_fails_closed_before_render(tmp_path):
    output = analysis_output()

    with pytest.raises(ValueError, match="expression client is required"):
        express_formal_analysis(ready_receipt(), output.value, client=None)
    assert list(tmp_path.iterdir()) == []


def test_validated_narrative_is_visible_on_home_and_stock_pages(tmp_path):
    output = analysis_output()
    receipt = rendering_receipt(output)
    narrative = _valid_narrative(output.value)
    marker = narrative.stocks[0].narrative_marker

    render_formal_report(tmp_path, receipt, output.value, narrative=narrative)

    home = (tmp_path / "index.html").read_text(encoding="utf-8")
    stock = (
        tmp_path
        / "daily"
        / output.value.trade_date.isoformat()
        / "stocks"
        / f"{narrative.stocks[0].ts_code}.html"
    ).read_text(encoding="utf-8")
    for html in (home, stock):
        assert marker in html
        assert narrative.stocks[0].analysis_summary.text in html
        assert "三条核心理由" in html
        assert "买入或继续观察的条件" in html
        assert "失效和退出条件" in html


def test_user_view_precedes_collapsed_audit_details(tmp_path):
    output = analysis_output()
    receipt = rendering_receipt(output)
    narrative = _valid_narrative(output.value)

    render_formal_report(tmp_path, receipt, output.value, narrative=narrative)

    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    main_view = html.split('<details class="audit-details">', 1)[0]
    assert main_view.index("市场总体结论") < main_view.index("推荐股票排序")
    assert "Gate" not in main_view
    assert "input set" not in main_view.lower()
    assert "receipt" not in main_view.lower()
    assert '<details class="audit-details">' in html
    assert '<details class="audit-details" open>' not in html


def test_focus_stock_page_displays_exact_five_session_progress(tmp_path):
    output = analysis_output()
    code = output.value.strategy_snapshots[0].ts_code
    dates = [
        date(2026, 7, 3),
        date(2026, 7, 6),
        date(2026, 7, 7),
        date(2026, 7, 8),
        date(2026, 7, 9),
    ]
    history = [
        output.value.strategy_snapshots[0].model_copy(
            update={
                "trade_date": trade_date,
                "evidence_id": f"history-{trade_date.isoformat()}",
            }
        )
        for trade_date in dates
    ]
    payload = output.value.model_copy(
        update={"focus_history_by_code": {code: history}}
    )
    narrative = _valid_narrative(payload)
    progress = [
        NarrativePoint(
            text=f"{item.trade_date.isoformat()}：按既定条件观察。",
            evidence_ids=[item.evidence_id],
        )
        for item in history
    ]
    focus_stock = narrative.stocks[0].model_copy(
        update={"five_day_progress": progress}
    )
    narrative = narrative.model_copy(update={"stocks": [focus_stock]})
    validate_formal_narrative(payload, narrative)

    render_formal_report(
        tmp_path,
        rendering_receipt(output),
        payload,
        narrative=narrative,
    )

    html = (
        tmp_path / "daily/2026-07-10/stocks" / f"{code}.html"
    ).read_text(encoding="utf-8")
    assert "重点股票五日进展" in html
    for trade_date in dates:
        assert trade_date.isoformat() in html


def test_production_renderer_rejects_missing_validated_narrative(tmp_path):
    output = analysis_output()

    with pytest.raises(ValueError, match="validated formal narrative is required"):
        render_formal_report(
            tmp_path,
            rendering_receipt(output),
            output.value,
            narrative=None,
        )
