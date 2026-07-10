from datetime import date

from stock_analyzer.analysis.evidence import (
    build_evidence_package,
    build_evidence_package_from_strategy_snapshot,
)
from stock_analyzer.domain.models import (
    ActionDecision,
    ActionRecommendation,
    ActionLabel,
    EvidenceAtom,
    EvidenceModule,
    EvidencePolarity,
    ModuleEvidence,
    Recommendation,
    StrategyEvidenceSnapshot,
)
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
    assert package.confidence_level
    assert package.expected_confirmation_path


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
    assert {task.due_date for task in tasks if task.checkpoint_days == 5} == {
        date(2026, 7, 14)
    }
    assert {task.due_date for task in tasks if task.checkpoint_days == 20} == {
        date(2026, 8, 4)
    }
    assert {task.due_date for task in tasks if task.checkpoint_days == 40} == {
        date(2026, 9, 1)
    }


def test_five_trading_day_checkpoint_skips_weekends():
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

    five_day_task = [
        task
        for task in create_evaluation_tasks(package)
        if task.checkpoint_days == 5 and task.evaluation_layer == "result"
    ][0]

    assert five_day_task.due_date == date(2026, 7, 14)
    assert five_day_task.due_date.weekday() == 1


def test_strategy_snapshot_evidence_package_flattens_atoms_and_policy_controls():
    support_atom = EvidenceAtom(
        id="2026-07-10-600000.SH-trend-support",
        module=EvidenceModule.TREND_VOLUME,
        polarity=EvidencePolarity.SUPPORT,
        headline="20 日趋势改善",
        detail="趋势斜率和相对强度同步改善。",
        source_grade="A",
        source_name="local_warehouse.market_daily",
        data_fields=["trend_20d", "relative_strength"],
        knowledge_rule_ids=["RULE_B", "RULE_A"],
        strength=0.78,
        as_of_date=date(2026, 7, 10),
    )
    counter_atom = EvidenceAtom(
        id="2026-07-10-600000.SH-risk-counter",
        module=EvidenceModule.RISK_COUNTER,
        polarity=EvidencePolarity.COUNTER,
        headline="波动仍需控制",
        detail="若跌破 20 日均线，观察 thesis 失效。",
        source_grade="B",
        source_name="strategy_v2.policy",
        data_fields=["volatility_20d"],
        knowledge_rule_ids=["RULE_A", "RULE_C"],
        strength=0.52,
        as_of_date=date(2026, 7, 10),
    )
    action = ActionRecommendation(
        decision=ActionDecision.WAIT_FOR_CONFIRMATION,
        position_min_pct=0.0,
        position_max_pct=3.0,
        reasoning=["趋势证据偏积极，但仍需确认。"],
        required_confirmation=["板块继续确认", "量能不萎缩"],
        invalidation_conditions=["跌破 20 日均线", "出现官方重大风险"],
        risk_if_wrong="若趋势为假突破，回撤可能扩大。",
        staging_plan=["等待确认后再进入观察仓位。"],
    )
    snapshot = StrategyEvidenceSnapshot(
        evidence_id="2026-07-10-600000.SH",
        trade_date=date(2026, 7, 10),
        ts_code="600000.SH",
        name="浦发银行",
        modules=[
            ModuleEvidence(
                module=EvidenceModule.TREND_VOLUME,
                summary="趋势模块支持观察。",
                support=[support_atom],
                counter=[],
                conclusion="趋势支持。",
            ),
            ModuleEvidence(
                module=EvidenceModule.RISK_COUNTER,
                summary="风险模块给出反证。",
                support=[],
                counter=[counter_atom],
                conclusion="需要风控。",
            ),
        ],
        action=action,
        thesis="银行板块企稳下的 2-8 周修复观察。",
        risk_reward=1.6,
        focus_entry_progress="观察第 1/5 个交易日，最近 5 日支持 1 日。",
        display_rank_bucket="重点观察",
        internal_score=86.0,
        source_versions={"market_daily": "2026-07-10"},
    )

    package = build_evidence_package_from_strategy_snapshot(snapshot)

    assert package.evidence_id == "2026-07-10-600000.SH"
    assert package.thesis == snapshot.thesis
    assert package.support == ["20 日趋势改善：趋势斜率和相对强度同步改善。"]
    assert package.counter_evidence == ["波动仍需控制：若跌破 20 日均线，观察 thesis 失效。"]
    assert package.matched_rules == ["RULE_A", "RULE_B", "RULE_C"]
    assert package.expected_confirmation_path == ["板块继续确认", "量能不萎缩"]
    assert package.invalidation_conditions == ["跌破 20 日均线", "出现官方重大风险"]
