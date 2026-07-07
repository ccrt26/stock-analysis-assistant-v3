from datetime import date

from stock_analyzer.analysis.evidence import build_evidence_package
from stock_analyzer.domain.models import ActionLabel, Recommendation
from stock_analyzer.evaluation.tasks import create_evaluation_tasks


def test_evidence_package_freezes_original_reasoning():
    rec = Recommendation(
        trade_date=date(2026, 7, 7),
        ts_code="600000.SH",
        name="浦发银行",
        action=ActionLabel.ENTER_OBSERVATION,
        score=83,
        reasons=["趋势改善"],
        risks=["银行板块弹性有限"],
    )
    package = build_evidence_package(rec, matched_rules=["RESEARCH_TREND_CONFIRMATION"])
    assert package.evidence_id == "2026-07-07-600000.SH"
    assert package.thesis.startswith("浦发银行")
    assert package.support == ["趋势改善"]
    assert package.counter_evidence == ["银行板块弹性有限"]
    assert package.matched_rules == ["RESEARCH_TREND_CONFIRMATION"]


def test_create_evaluation_tasks_has_three_layers_and_three_windows():
    package = build_evidence_package(
        Recommendation(
            trade_date=date(2026, 7, 7),
            ts_code="600000.SH",
            name="浦发银行",
            action=ActionLabel.ENTER_OBSERVATION,
            score=83,
            reasons=["趋势改善"],
            risks=["银行板块弹性有限"],
        ),
        matched_rules=["RESEARCH_TREND_CONFIRMATION"],
    )
    tasks = create_evaluation_tasks(package)
    assert {(task.checkpoint_days, task.evaluation_layer) for task in tasks} == {
        (5, "result"),
        (20, "result"),
        (40, "result"),
        (20, "method"),
        (40, "method"),
        (40, "knowledge"),
    }
