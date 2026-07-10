from datetime import date, timedelta

from stock_analyzer.analysis.evidence import (
    build_evidence_package,
    build_evidence_package_from_strategy_snapshot,
)
from stock_analyzer.data.models import DailyBar, SourceGrade
from stock_analyzer.domain.models import (
    ActionDecision,
    ActionRecommendation,
    DataAvailability,
    DataRequirementLevel,
    DataRequirementStatus,
    ActionLabel,
    EvidenceAtom,
    EvidenceModule,
    EvidencePolarity,
    ModuleEvidence,
    Recommendation,
    StrategyEvidenceSnapshot,
)
from stock_analyzer.evaluation.replay import evaluate_strategy_snapshot
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


def test_strategy_v2_replay_marks_invalidation_when_support_breaks():
    snapshot = _strategy_snapshot_with_action(
        trade_date=date(2026, 7, 10),
        ts_code="600000.SH",
        invalidation="跌破 20 日均线且放量",
    )
    future_bars = [
        DailyBar(
            trade_date=date(2026, 7, 13),
            ts_code="600000.SH",
            close=9.4,
            pre_close=10.0,
            pct_chg=-6.0,
            amount=900000000,
            source_name="fixture",
            source_grade=SourceGrade.PRIMARY,
        )
    ]

    result = evaluate_strategy_snapshot(snapshot, future_bars)

    assert result.invalidation_occurred is True
    assert result.action_useful in {False, None}
    assert "跌破" in "；".join(result.notes)
    assert set(result.outcome_inputs) == {5, 20, 40}


def test_strategy_v2_replay_marks_participation_useful_on_favorable_excursion():
    snapshot = _strategy_snapshot_with_action(
        trade_date=date(2026, 7, 10),
        ts_code="600000.SH",
        decision=ActionDecision.SMALL_EXPLORATORY,
        position_min_pct=3.0,
        position_max_pct=8.0,
        invalidation="跌破 10 日均线",
    )
    future_bars = [
        DailyBar(
            trade_date=date(2026, 7, 13),
            ts_code="600000.SH",
            close=10.2,
            pre_close=10.0,
            high=10.5,
            low=9.9,
            pct_chg=2.0,
            source_name="fixture",
            source_grade=SourceGrade.PRIMARY,
        ),
        DailyBar(
            trade_date=date(2026, 7, 14),
            ts_code="600000.SH",
            close=11.2,
            pre_close=10.2,
            high=11.4,
            low=10.1,
            pct_chg=9.8,
            source_name="fixture",
            source_grade=SourceGrade.PRIMARY,
        ),
        DailyBar(
            trade_date=date(2026, 7, 15),
            ts_code="600000.SH",
            close=10.9,
            pre_close=11.2,
            high=11.0,
            low=10.6,
            pct_chg=-2.7,
            source_name="fixture",
            source_grade=SourceGrade.PRIMARY,
        ),
    ]

    result = evaluate_strategy_snapshot(snapshot, future_bars)

    assert result.invalidation_occurred is False
    assert result.action_useful is True
    assert result.position_aggressiveness == "reasonable"
    assert result.outcome_inputs[5].max_favorable_excursion_pct >= 14.0
    assert any(
        effect.rule_id == "RULE_TREND"
        and effect.module == EvidenceModule.TREND_VOLUME.value
        and effect.observed_alignment == "support_aligned"
        for effect in result.knowledge_rule_effect
    )


def test_strategy_v2_replay_top_level_verdict_uses_structured_40_day_horizon():
    snapshot = _strategy_snapshot_with_action(
        trade_date=date(2026, 7, 10),
        ts_code="600000.SH",
        decision=ActionDecision.SMALL_EXPLORATORY,
        position_min_pct=5.0,
        position_max_pct=10.0,
        invalidation="跌破 20 日均线",
    )
    future_bars = [
        DailyBar(
            trade_date=snapshot.trade_date + timedelta(days=offset),
            ts_code=snapshot.ts_code,
            close=9.4 if offset == 41 else 10.2,
            pre_close=10.0,
            high=9.6 if offset == 41 else (10.6 if offset == 10 else 10.25),
            low=9.3 if offset == 41 else 10.0,
            pct_chg=-6.0 if offset == 41 else 2.0,
            source_name="fixture",
            source_grade=SourceGrade.PRIMARY,
        )
        for offset in range(1, 42)
    ]

    result = evaluate_strategy_snapshot(snapshot, future_bars)

    assert result.future_bar_count == 41
    assert result.outcome_inputs[40].bars_observed == 40
    assert result.outcome_inputs[40].invalidation_occurred is False
    assert result.invalidation_occurred is False
    assert result.action_useful is True
    assert result.position_aggressiveness == "reasonable"


def test_strategy_v2_replay_does_not_count_neutral_evidence_as_support():
    trade_date = date(2026, 7, 10)
    ts_code = "600000.SH"
    neutral_atom = EvidenceAtom(
        id=f"{trade_date}-{ts_code}-market-neutral",
        module=EvidenceModule.MARKET_BOARD,
        polarity=EvidencePolarity.NEUTRAL,
        headline="板块信息仅作背景",
        detail="板块热度一般，不形成支持或反证。",
        source_grade="B",
        source_name="strategy_v2.market",
        data_fields=["industry_rank"],
        knowledge_rule_ids=["RULE_NEUTRAL"],
        strength=0.4,
        as_of_date=trade_date,
    )
    snapshot = _strategy_snapshot_with_action(
        trade_date=trade_date,
        ts_code=ts_code,
        modules=[
            ModuleEvidence(
                module=EvidenceModule.MARKET_BOARD,
                summary="板块信息中性。",
                support=[neutral_atom],
                counter=[],
                conclusion="仅作为背景信息。",
            )
        ],
    )
    future_bars = [
        DailyBar(
            trade_date=date(2026, 7, 13),
            ts_code=ts_code,
            close=10.6,
            pre_close=10.0,
            high=10.8,
            low=10.0,
            pct_chg=6.0,
            source_name="fixture",
            source_grade=SourceGrade.PRIMARY,
        )
    ]

    result = evaluate_strategy_snapshot(snapshot, future_bars)

    effect = next(
        effect
        for effect in result.knowledge_rule_effect
        if effect.rule_id == "RULE_NEUTRAL"
    )
    assert effect.support_count == 0
    assert effect.counter_count == 0
    assert effect.neutral_count == 1
    assert effect.neutral_evidence_ids == [neutral_atom.id]
    assert effect.observed_alignment == "mixed_unresolved"


def test_strategy_v2_replay_missing_data_effect_ignores_day_41_ohlc_gaps():
    snapshot = _strategy_snapshot_with_action(
        trade_date=date(2026, 7, 10),
        ts_code="600000.SH",
        decision=ActionDecision.SMALL_EXPLORATORY,
        position_min_pct=5.0,
        position_max_pct=10.0,
    )
    future_bars = [
        DailyBar(
            trade_date=snapshot.trade_date + timedelta(days=offset),
            ts_code=snapshot.ts_code,
            close=10.2,
            pre_close=None if offset == 41 else 10.0,
            high=None if offset == 41 else 10.4,
            low=None if offset == 41 else 9.9,
            pct_chg=2.0,
            source_name="fixture",
            source_grade=SourceGrade.PRIMARY,
        )
        for offset in range(1, 42)
    ]

    result = evaluate_strategy_snapshot(snapshot, future_bars)

    assert result.future_bar_count == 41
    assert result.outcome_inputs[40].bars_observed == 40
    assert result.missing_data_effect.bars_observed == 40
    assert result.missing_data_effect.missing_ohlc_fields == []
    assert "Missing replay fields" not in "；".join(result.missing_data_effect.notes)
    assert "Missing replay fields" not in "；".join(result.notes)


def test_strategy_v2_replay_reports_snapshot_level_data_insufficiency():
    requirement = DataRequirementStatus(
        family="daily_ohlcv",
        level=DataRequirementLevel.REQUIRED,
        availability=DataAvailability.UNAVAILABLE_AFTER_RECOVERY,
        missing_fields=["close", "amount"],
        blocks_complete_analysis=True,
    )
    snapshot = _strategy_snapshot_with_action(
        trade_date=date(2026, 7, 10),
        ts_code="600000.SH",
        modules=[
            ModuleEvidence(
                module=EvidenceModule.TREND_VOLUME,
                summary="行情数据不足。",
                support=[],
                counter=[],
                data_requirements=[requirement],
                conclusion="数据不足，不形成正向结论。",
            )
        ],
    ).model_copy(
        update={
            "data_insufficient": True,
            "data_insufficient_reason": "行情数据缺失",
        }
    )
    future_bars = [
        DailyBar(
            trade_date=date(2026, 7, 13),
            ts_code=snapshot.ts_code,
            close=10.1,
            pre_close=10.0,
            high=10.2,
            low=10.0,
            pct_chg=1.0,
            source_name="fixture",
            source_grade=SourceGrade.PRIMARY,
        )
    ]

    result = evaluate_strategy_snapshot(snapshot, future_bars)

    assert result.missing_data_effect.snapshot_data_insufficient is True
    assert (
        result.missing_data_effect.snapshot_data_insufficient_reason
        == "行情数据缺失"
    )
    assert len(result.missing_data_effect.data_requirement_issues) == 1
    issue = result.missing_data_effect.data_requirement_issues[0]
    assert issue.module == EvidenceModule.TREND_VOLUME.value
    assert issue.family == "daily_ohlcv"
    assert issue.availability == DataAvailability.UNAVAILABLE_AFTER_RECOVERY.value
    assert issue.missing_fields == ["close", "amount"]
    assert issue.blocks_complete_analysis is True
    assert "行情数据缺失" in "；".join(result.missing_data_effect.notes)


def test_strategy_v2_replay_reports_missing_data_effect_and_unchecked_claims():
    snapshot = _strategy_snapshot_with_action(
        trade_date=date(2026, 7, 10),
        ts_code="600000.SH",
        thesis="AI 算力突破推动 2-8 周修复观察。",
        modules=[],
    )
    future_bars = [
        DailyBar(
            trade_date=date(2026, 7, 13),
            ts_code="600000.SH",
            close=10.1,
            source_name="fixture",
            source_grade=SourceGrade.PRIMARY,
        ),
        DailyBar(
            trade_date=date(2026, 7, 14),
            ts_code="000001.SZ",
            close=11.0,
            high=11.2,
            low=10.8,
            pre_close=10.9,
            source_name="fixture",
            source_grade=SourceGrade.PRIMARY,
        ),
    ]

    result = evaluate_strategy_snapshot(snapshot, future_bars)

    assert result.missing_data_effect.insufficient_future_bars is True
    assert result.missing_data_effect.missing_ohlc_fields == ["high", "low", "pre_close"]
    assert result.outcome_inputs[20].insufficient_data is True
    assert result.action_useful is None
    assert result.unsupported_narrative_flags


def _strategy_snapshot_with_action(
    trade_date: date,
    ts_code: str,
    invalidation: str = "跌破 20 日均线",
    decision: ActionDecision = ActionDecision.SMALL_EXPLORATORY,
    position_min_pct: float = 5.0,
    position_max_pct: float = 10.0,
    thesis: str = "银行板块企稳下的 2-8 周修复观察。",
    modules: list[ModuleEvidence] | None = None,
) -> StrategyEvidenceSnapshot:
    support_atom = EvidenceAtom(
        id=f"{trade_date}-{ts_code}-trend-support",
        module=EvidenceModule.TREND_VOLUME,
        polarity=EvidencePolarity.SUPPORT,
        headline="20 日趋势改善",
        detail="趋势斜率和相对强度同步改善。",
        source_grade="A",
        source_name="local_warehouse.market_daily",
        data_fields=["trend_20d", "relative_strength"],
        knowledge_rule_ids=["RULE_TREND"],
        strength=0.78,
        as_of_date=trade_date,
    )
    counter_atom = EvidenceAtom(
        id=f"{trade_date}-{ts_code}-risk-counter",
        module=EvidenceModule.RISK_COUNTER,
        polarity=EvidencePolarity.COUNTER,
        headline="波动仍需控制",
        detail=f"若{invalidation}，观察 thesis 失效。",
        source_grade="B",
        source_name="strategy_v2.policy",
        data_fields=["volatility_20d"],
        knowledge_rule_ids=["RULE_RISK"],
        strength=0.52,
        as_of_date=trade_date,
    )
    snapshot_modules = modules
    if snapshot_modules is None:
        snapshot_modules = [
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
        ]
    return StrategyEvidenceSnapshot(
        evidence_id=f"{trade_date}-{ts_code}",
        trade_date=trade_date,
        ts_code=ts_code,
        name="浦发银行",
        modules=snapshot_modules,
        action=ActionRecommendation(
            decision=decision,
            position_min_pct=position_min_pct,
            position_max_pct=position_max_pct,
            reasoning=["趋势证据偏积极，但仍需确认。"],
            required_confirmation=["板块继续确认", "量能不萎缩"],
            invalidation_conditions=[invalidation],
            risk_if_wrong="若趋势为假突破，回撤可能扩大。",
            staging_plan=["等待确认后再进入观察仓位。"],
        ),
        thesis=thesis,
        risk_reward=1.6,
        focus_entry_progress="观察第 1/5 个交易日，最近 5 日支持 1 日。",
        display_rank_bucket="重点观察",
        internal_score=86.0,
        source_versions={"market_daily": str(trade_date)},
    )
