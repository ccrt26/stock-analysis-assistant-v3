from datetime import date, datetime

import pytest

from stock_analyzer.domain.models import (
    ActionDecision,
    ActionRecommendation,
    DataAvailability,
    DataRequirementLevel,
    DataRequirementStatus,
    DataRecoveryAttempt,
    EvidenceAtom,
    EvidenceModule,
    EvidencePolarity,
    FocusDailyUpdate,
    FocusEntryThesis,
    FocusSource,
    ManualActionRecord,
    ManualHolding,
    ModuleEvidence,
    OperationalDailyStatus,
    OperationalReportState,
    RecommendationCard,
    StrategyEvidenceSnapshot,
)


def _atom() -> EvidenceAtom:
    return EvidenceAtom(
        id="2026-07-10-600000.SH-trend",
        module=EvidenceModule.TREND_VOLUME,
        polarity=EvidencePolarity.SUPPORT,
        headline="20 日趋势改善",
        detail="收盘价高于 20 日均线且 20 日收益强于市场中位数。",
        source_grade="A",
        source_name="local_warehouse.market_daily",
        source_url=None,
        data_fields=["trend_20d", "relative_strength"],
        knowledge_rule_ids=["RESEARCH_TREND_CONFIRMATION"],
        strength=0.72,
        as_of_date=date(2026, 7, 10),
    )


def _action(**overrides) -> ActionRecommendation:
    params = {
        "decision": ActionDecision.WAIT_FOR_CONFIRMATION,
        "position_min_pct": 0.0,
        "position_max_pct": 3.0,
        "reasoning": ["趋势改善但板块确认不足"],
        "required_confirmation": ["板块相对强度继续改善"],
        "invalidation_conditions": ["跌破 20 日均线且放量"],
        "risk_if_wrong": "若是假突破，短线回撤可能扩大。",
        "staging_plan": ["未持有时等待确认后再小仓试探"],
        "holding_adjustment": None,
    }
    params.update(overrides)
    return ActionRecommendation(**params)


def test_evidence_module_uses_approved_six_module_keys_exactly():
    assert {module.value for module in EvidenceModule} == {
        "company_business",
        "fundamentals_valuation",
        "market_board",
        "trend_volume",
        "events_catalysts",
        "risk_counter",
    }


def test_data_requirement_levels_use_approved_contract_values_exactly():
    assert {level.value for level in DataRequirementLevel} == {
        "required",
        "enhanced",
        "observation",
    }


def test_evidence_polarity_uses_approved_contract_values_exactly():
    assert {polarity.value for polarity in EvidencePolarity} == {
        "support",
        "counter",
        "neutral",
    }


def test_data_availability_uses_approved_contract_values_exactly():
    assert {availability.value for availability in DataAvailability} == {
        "available_primary",
        "available_backup",
        "available_local_cache",
        "unavailable_after_recovery",
    }


def test_action_decision_uses_approved_display_values_exactly():
    assert {decision.value for decision in ActionDecision} == {
        "暂不参与",
        "继续观察",
        "等待确认",
        "避免追高",
        "小仓试探",
        "提高关注",
        "确认后考虑提高仓位",
        "风险上升，降低或避免新增",
        "建议确认是否移出重点",
    }


def test_focus_source_uses_approved_contract_values_exactly():
    assert {source.value for source in FocusSource} == {
        "system",
        "manual",
    }


def test_strategy_snapshot_serializes_six_module_evidence_and_action():
    atom = _atom()
    status = DataRequirementStatus(
        family="daily_ohlcv",
        level=DataRequirementLevel.REQUIRED,
        availability=DataAvailability.AVAILABLE_PRIMARY,
        primary_source="tushare.daily",
        backup_source="akshare.stock_zh_a_hist",
        local_cache_path="local_warehouse/parquet/market_daily/trade_date=2026-07-10/data.parquet",
        missing_fields=[],
        recovery_attempts=[],
        blocks_complete_analysis=False,
    )
    module = ModuleEvidence(
        module=EvidenceModule.TREND_VOLUME,
        summary="趋势和量价支持观察，但不能单独构成买入依据。",
        support=[atom],
        counter=[],
        data_requirements=[status],
        conclusion="趋势证据偏积极。",
    )
    snapshot = StrategyEvidenceSnapshot(
        evidence_id="2026-07-10-600000.SH",
        trade_date=date(2026, 7, 10),
        ts_code="600000.SH",
        name="浦发银行",
        modules=[module],
        action=_action(),
        thesis="银行板块企稳下的 2-8 周修复观察。",
        expected_upside_pct=10.0,
        expected_downside_pct=6.0,
        risk_reward=1.67,
        focus_entry_progress="观察第 2/5 个交易日，最近 5 日支持 2 日。",
        display_rank_bucket="强观察",
        internal_score=83.25,
        data_insufficient=False,
        data_insufficient_reason=None,
        source_versions={"market_daily": "2026-07-10"},
    )

    payload = snapshot.model_dump(mode="json")

    assert payload["action"]["decision"] == "等待确认"
    assert payload["modules"][0]["support"][0]["knowledge_rule_ids"] == [
        "RESEARCH_TREND_CONFIRMATION"
    ]
    assert payload["risk_reward"] == 1.67


def test_strategy_snapshot_requires_internal_score():
    with pytest.raises(ValueError):
        StrategyEvidenceSnapshot(
            evidence_id="2026-07-10-600000.SH",
            trade_date=date(2026, 7, 10),
            ts_code="600000.SH",
            name="浦发银行",
            modules=[],
            action=_action(),
            thesis="银行板块企稳下的 2-8 周修复观察。",
            display_rank_bucket="强观察",
            data_insufficient=False,
            data_insufficient_reason=None,
            source_versions={"market_daily": "2026-07-10"},
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("reasoning", []),
        ("required_confirmation", []),
        ("invalidation_conditions", []),
        ("risk_if_wrong", ""),
        ("staging_plan", []),
    ],
)
def test_action_recommendation_requires_non_empty_risk_controls(field, value):
    with pytest.raises(ValueError):
        _action(**{field: value})


@pytest.mark.parametrize(
    "overrides",
    [
        {"position_min_pct": -0.1},
        {"position_max_pct": -0.1},
        {"position_min_pct": 5.0, "position_max_pct": 3.0},
    ],
)
def test_action_recommendation_rejects_invalid_position_ranges(overrides):
    with pytest.raises(ValueError):
        _action(**overrides)


def test_recommendation_card_has_no_total_numeric_score():
    action = _action()
    card = RecommendationCard(
        trade_date=date(2026, 7, 10),
        ts_code="600000.SH",
        name="浦发银行",
        display_rank_bucket="强观察",
        action=action.decision.value,
        position_min_pct=action.position_min_pct,
        position_max_pct=action.position_max_pct,
        action_reasoning=action.reasoning,
        required_confirmation=action.required_confirmation,
        invalidation_conditions=action.invalidation_conditions,
        risk_if_wrong=action.risk_if_wrong,
        staging_plan=action.staging_plan,
        holding_adjustment=action.holding_adjustment,
        what_happened="趋势改善且成交额维持。",
        why_it_may_have_happened="板块企稳带动修复。",
        what_it_may_mean="进入重点观察候选，但仍需板块确认。",
        main_risk="银行板块弹性不足。",
        focus_entry_progress="观察第 2/5 个交易日，最近 5 日支持 2 日。",
        needed_before_focus_entry=["板块确认", "风险收益确认"],
        evidence_id="2026-07-10-600000.SH",
    )

    payload = card.model_dump(mode="json")

    assert "score" not in payload
    assert "internal_score" not in payload
    assert payload["display_rank_bucket"] == "强观察"
    assert payload["position_min_pct"] == action.position_min_pct
    assert payload["position_max_pct"] == action.position_max_pct
    assert payload["action_reasoning"] == action.reasoning
    assert payload["required_confirmation"] == action.required_confirmation
    assert payload["invalidation_conditions"] == action.invalidation_conditions
    assert payload["risk_if_wrong"] == action.risk_if_wrong
    assert payload["staging_plan"] == action.staging_plan


def test_focus_manual_recovery_and_operational_contracts_serialize():
    action = _action()
    atom = _atom()
    recovery = DataRecoveryAttempt(
        source="akshare.stock_zh_a_hist",
        attempted_at=datetime(2026, 7, 10, 15, 30),
        succeeded=True,
        recovered_fields=["close", "amount"],
        error=None,
    )

    thesis = FocusEntryThesis(
        evidence_id="2026-07-10-600000.SH",
        trade_date=date(2026, 7, 10),
        ts_code="600000.SH",
        name="浦发银行",
        source=FocusSource.SYSTEM,
        thesis="银行板块企稳下的 2-8 周修复观察。",
        action=action,
        expected_upside_pct=10.0,
        expected_downside_pct=6.0,
        risk_reward=1.67,
        required_confirmation=["板块确认"],
        invalidation_conditions=["跌破 20 日均线且放量"],
        supporting_evidence_ids=[atom.id],
    )
    update = FocusDailyUpdate(
        trade_date=date(2026, 7, 10),
        ts_code="600000.SH",
        name="浦发银行",
        evidence_id="2026-07-10-600000.SH",
        thesis="银行板块企稳下的 2-8 周修复观察。",
        action=action,
        focus_entry_progress="观察第 2/5 个交易日，最近 5 日支持 2 日。",
        new_support=[atom],
        new_counter=[],
        required_confirmation=["板块确认"],
        invalidation_conditions=["跌破 20 日均线且放量"],
        data_insufficient=False,
        data_insufficient_reason=None,
    )
    holding = ManualHolding(
        ts_code="600000.SH",
        name="浦发银行",
        position_pct=2.5,
        cost_price=9.8,
        quantity=1000,
        entry_date=date(2026, 7, 8),
        thesis_id=thesis.evidence_id,
        notes="人工导入底仓",
    )
    action_record = ManualActionRecord(
        action_date=date(2026, 7, 10),
        ts_code="600000.SH",
        name="浦发银行",
        decision=ActionDecision.WAIT_FOR_CONFIRMATION,
        position_pct=2.5,
        reason="等待板块确认",
        evidence_id=thesis.evidence_id,
        notes=None,
    )
    operational = OperationalDailyStatus(
        trade_date=date(2026, 7, 10),
        is_trading_day=True,
        recommendation_state=OperationalReportState.GENERATED,
        focus_state=OperationalReportState.DATA_INSUFFICIENT,
        recommendation_count=5,
        focus_count=0,
        data_recovery_attempts=[recovery],
        blocking_missing_fields=["focus_state.latest_update"],
        message="日推荐已生成，重点跟踪数据不足。",
    )

    assert thesis.model_dump(mode="json")["action"]["decision"] == "等待确认"
    assert update.model_dump(mode="json")["new_support"][0]["module"] == "trend_volume"
    assert holding.model_dump(mode="json")["entry_date"] == "2026-07-08"
    assert action_record.model_dump(mode="json")["decision"] == "等待确认"

    operational_payload = operational.model_dump(mode="json")
    assert set(operational_payload) == {
        "trade_date",
        "is_trading_day",
        "recommendation_state",
        "focus_state",
        "recommendation_count",
        "focus_count",
        "data_recovery_attempts",
        "blocking_missing_fields",
        "message",
    }
    assert operational_payload["is_trading_day"] is True
    assert operational_payload["recommendation_state"] == "generated"
    assert operational_payload["focus_state"] == "data_insufficient"
    assert operational_payload["recommendation_count"] == 5
    assert operational_payload["focus_count"] == 0
    assert operational_payload["data_recovery_attempts"][0]["recovered_fields"] == [
        "close",
        "amount",
    ]
    assert operational_payload["blocking_missing_fields"] == ["focus_state.latest_update"]
