from __future__ import annotations

import pytest

from stock_analyzer.analysis.action_policy import (
    ActionPolicyInput,
    build_action_recommendation,
)
from stock_analyzer.domain.models import ActionDecision, ManualHolding


def _holding(position_pct: float) -> ManualHolding:
    return ManualHolding(
        ts_code="600000.SH",
        name="浦发银行",
        position_pct=position_pct,
        cost_price=10.0,
        quantity=1000,
        thesis_id="2026-07-10-600000.SH",
        notes="人工导入底仓",
    )


def _policy_text(result) -> str:
    return " ".join(
        [
            result.decision.value,
            *result.reasoning,
            *result.required_confirmation,
            *result.invalidation_conditions,
            result.risk_if_wrong,
            *result.staging_plan,
            result.holding_adjustment or "",
        ]
    )


def _assert_no_broker_order_language(result) -> None:
    text = _policy_text(result).lower()
    for forbidden in ("broker", "order", "券商", "下单", "订单", "委托"):
        assert forbidden not in text


def test_action_policy_waits_when_confirmation_is_missing():
    result = build_action_recommendation(
        ActionPolicyInput(
            market_support=0.4,
            thesis_quality=0.65,
            risk_reward=1.7,
            volatility_20d=0.24,
            liquidity_score=0.8,
            current_holding=None,
            technical_invalidation="跌破 20 日均线且放量",
            catalyst_freshness="none",
        )
    )

    assert result.decision == ActionDecision.WAIT_FOR_CONFIRMATION
    assert result.position_min_pct == 0.0
    assert result.position_max_pct <= 3.0
    assert result.required_confirmation
    assert result.invalidation_conditions == ["跌破 20 日均线且放量"]
    assert result.reasoning
    assert result.risk_if_wrong
    assert result.staging_plan
    _assert_no_broker_order_language(result)


def test_action_policy_allows_small_exploratory_position_when_evidence_is_strong():
    result = build_action_recommendation(
        ActionPolicyInput(
            market_support=0.78,
            thesis_quality=0.82,
            risk_reward=1.9,
            volatility_20d=0.22,
            liquidity_score=0.9,
            current_holding=None,
            technical_invalidation="跌破突破平台下沿",
            catalyst_freshness="fresh_official",
        )
    )

    assert result.decision == ActionDecision.SMALL_EXPLORATORY
    assert result.position_min_pct == 2.0
    assert result.position_max_pct == 5.0
    assert "分批" in "；".join(result.staging_plan)
    _assert_no_broker_order_language(result)


def test_action_policy_adds_conditionally_for_strong_setup_with_small_holding():
    result = build_action_recommendation(
        ActionPolicyInput(
            market_support=0.7,
            thesis_quality=0.75,
            risk_reward=1.5,
            volatility_20d=0.35,
            liquidity_score=0.6,
            current_holding=_holding(6.0),
            technical_invalidation="跌破 20 日均线",
            catalyst_freshness="fresh_official",
        )
    )

    assert result.decision == ActionDecision.CONDITIONAL_ADD
    assert result.position_min_pct == 6.0
    assert result.position_max_pct == 11.0
    assert result.holding_adjustment
    _assert_no_broker_order_language(result)


def test_action_policy_reduces_suggestion_for_existing_high_position():
    result = build_action_recommendation(
        ActionPolicyInput(
            market_support=0.8,
            thesis_quality=0.82,
            risk_reward=1.8,
            volatility_20d=0.25,
            liquidity_score=0.9,
            current_holding=_holding(18.0),
            technical_invalidation="跌破 20 日均线",
            catalyst_freshness="fresh_official",
        )
    )

    assert result.decision in {
        ActionDecision.CONTINUE_WATCHING,
        ActionDecision.REDUCE_OR_AVOID,
        ActionDecision.WAIT_FOR_CONFIRMATION,
    }
    assert result.position_max_pct <= 18.0
    assert result.holding_adjustment
    _assert_no_broker_order_language(result)


@pytest.mark.parametrize(
    "overrides",
    [
        {"hard_risk": True},
        {"liquidity_score": 0.24},
        {"risk_reward": 0.99},
        {"volatility_20d": 0.46},
    ],
)
def test_action_policy_blocks_participation_for_hard_risk(overrides):
    params = {
        "market_support": 0.8,
        "thesis_quality": 0.82,
        "risk_reward": 1.8,
        "volatility_20d": 0.25,
        "liquidity_score": 0.9,
        "current_holding": None,
        "technical_invalidation": "跌破风控线",
        "catalyst_freshness": "fresh_official",
    }
    params.update(overrides)

    result = build_action_recommendation(ActionPolicyInput(**params))

    assert result.decision == ActionDecision.NO_PARTICIPATION
    assert result.position_min_pct == 0.0
    assert result.position_max_pct == 0.0
    assert result.required_confirmation
    _assert_no_broker_order_language(result)


def test_action_policy_avoids_chasing_when_setup_is_extended():
    result = build_action_recommendation(
        ActionPolicyInput(
            market_support=0.8,
            thesis_quality=0.82,
            risk_reward=1.2,
            volatility_20d=0.36,
            liquidity_score=0.9,
            current_holding=None,
            technical_invalidation="跌破突破平台下沿",
            catalyst_freshness="fresh_official",
        )
    )

    assert result.decision == ActionDecision.AVOID_CHASING
    assert result.position_min_pct == 0.0
    assert result.position_max_pct == 0.0
    _assert_no_broker_order_language(result)


def test_action_policy_is_deterministic_for_identical_inputs():
    policy_input = ActionPolicyInput(
        market_support=0.78,
        thesis_quality=0.82,
        risk_reward=1.9,
        volatility_20d=0.22,
        liquidity_score=0.9,
        current_holding=None,
        technical_invalidation="跌破突破平台下沿",
        catalyst_freshness="fresh_official",
    )

    first = build_action_recommendation(policy_input)
    second = build_action_recommendation(policy_input)

    assert first == second
