from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from stock_analyzer.domain.models import (
    ActionDecision,
    ActionRecommendation,
    ManualHolding,
)


class ActionPolicyInput(BaseModel):
    market_support: float = Field(ge=0.0, le=1.0)
    thesis_quality: float = Field(ge=0.0, le=1.0)
    risk_reward: float = Field(ge=0.0)
    volatility_20d: float = Field(ge=0.0)
    liquidity_score: float = Field(ge=0.0, le=1.0)
    current_holding: ManualHolding | None = None
    technical_invalidation: str = Field(min_length=1)
    catalyst_freshness: str = Field(min_length=1)
    hard_risk: bool = False

    @field_validator("technical_invalidation", "catalyst_freshness")
    @classmethod
    def _strip_non_empty_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must be non-empty")
        return stripped


def build_action_recommendation(
    snapshot_inputs: ActionPolicyInput,
) -> ActionRecommendation:
    inputs = snapshot_inputs
    current_position = _current_position(inputs.current_holding)
    invalidation_conditions = [inputs.technical_invalidation]

    risk_flags = _hard_risk_flags(inputs)
    if risk_flags:
        decision = (
            ActionDecision.REDUCE_OR_AVOID
            if inputs.current_holding is not None
            else ActionDecision.NO_PARTICIPATION
        )
        position_max = current_position if inputs.current_holding is not None else 0.0
        return ActionRecommendation(
            decision=decision,
            position_min_pct=0.0,
            position_max_pct=_pct(position_max),
            reasoning=[
                "；".join(risk_flags),
                _score_summary(inputs),
            ],
            required_confirmation=[f"{flag}解除" for flag in risk_flags],
            invalidation_conditions=invalidation_conditions,
            risk_if_wrong="若忽视硬风险，仓位暴露可能在流动性或波动冲击下被动放大。",
            staging_plan=[
                "不建立新增仓位暴露，等待硬风险解除后再评估。",
                "若已有持仓，优先把风险暴露压回可承受区间。",
            ],
            holding_adjustment=_holding_adjustment(
                inputs.current_holding,
                "硬风险已触发，不提高目标上限。",
            ),
        )

    if current_position >= 15.0:
        return ActionRecommendation(
            decision=ActionDecision.CONTINUE_WATCHING,
            position_min_pct=_pct(current_position),
            position_max_pct=_pct(current_position),
            reasoning=[
                "现有仓位已达到 15% 以上，规则要求不再提高目标上限。",
                _score_summary(inputs),
            ],
            required_confirmation=[
                "强势证据继续维持且未触发失效条件",
                "仓位风险仍处在可承受范围内",
            ],
            invalidation_conditions=invalidation_conditions,
            risk_if_wrong="若高仓位判断错误，单一标的回撤会对组合造成过度拖累。",
            staging_plan=[
                "现有仓位不提高目标上限，维持观察并等待确认。",
                "触发失效条件时降低风险暴露。",
            ],
            holding_adjustment=_holding_adjustment(
                inputs.current_holding,
                "现有仓位已在 15% 以上，不提高目标上限。",
            ),
        )

    if _is_strong_setup(inputs):
        if inputs.current_holding is None:
            return ActionRecommendation(
                decision=ActionDecision.SMALL_EXPLORATORY,
                position_min_pct=2.0,
                position_max_pct=5.0,
                reasoning=[
                    "市场支持、thesis 质量、风险收益、波动和流动性均达到强设置阈值。",
                    _score_summary(inputs),
                ],
                required_confirmation=[
                    "突破或趋势确认继续有效",
                    "催化与量价证据未明显转弱",
                ],
                invalidation_conditions=invalidation_conditions,
                risk_if_wrong="若强设置是假突破，2%-5% 观察仓位仍可能承受短线回撤。",
                staging_plan=[
                    "先以 2%-3% 观察仓位分批试探。",
                    "确认延续后上限不超过 5%。",
                ],
            )

        if current_position < 8.0:
            target_max = min(current_position + 5.0, 12.0)
            return ActionRecommendation(
                decision=ActionDecision.CONDITIONAL_ADD,
                position_min_pct=_pct(current_position),
                position_max_pct=_pct(target_max),
                reasoning=[
                    "强设置成立，且现有仓位低于 8%，允许在确认后提高仓位上限。",
                    _score_summary(inputs),
                ],
                required_confirmation=[
                    "强设置阈值继续满足",
                    "失效条件未触发且催化证据未转弱",
                ],
                invalidation_conditions=invalidation_conditions,
                risk_if_wrong="若追加判断错误，组合会在回撤前增加单一标的暴露。",
                staging_plan=[
                    (
                        f"以现有 {_pct(current_position):.1f}% 作为下限，"
                        f"确认延续后分批提高至不超过 {_pct(target_max):.1f}%。"
                    ),
                    "若触发失效条件则回到观察状态。",
                ],
                holding_adjustment=_holding_adjustment(
                    inputs.current_holding,
                    "现有仓位低于 8%，确认后目标上限最多提高 5 个百分点且不超过 12%。",
                ),
            )

        return ActionRecommendation(
            decision=ActionDecision.CONTINUE_WATCHING,
            position_min_pct=_pct(current_position),
            position_max_pct=_pct(current_position),
            reasoning=[
                "强设置成立，但已有仓位不再属于低仓位加仓区间。",
                _score_summary(inputs),
            ],
            required_confirmation=[
                "强设置阈值继续满足",
                "仓位风险未接近 15% 高仓位约束",
            ],
            invalidation_conditions=invalidation_conditions,
            risk_if_wrong="若继续持有判断错误，既有仓位仍会承受趋势反转风险。",
            staging_plan=[
                "保持现有目标上限，等待新确认信号。",
                "触发失效条件时降低风险暴露。",
            ],
            holding_adjustment=_holding_adjustment(
                inputs.current_holding,
                "已有仓位不低于 8%，本轮不提高目标上限。",
            ),
        )

    if _is_extended_setup(inputs):
        return ActionRecommendation(
            decision=ActionDecision.AVOID_CHASING,
            position_min_pct=0.0,
            position_max_pct=0.0,
            reasoning=[
                "市场和 thesis 较强，但风险收益或波动已经不支持追高。",
                _score_summary(inputs),
            ],
            required_confirmation=[
                "风险收益比重新回到 1.5 以上",
                "20 日波动率回落至 0.35 以下",
            ],
            invalidation_conditions=invalidation_conditions,
            risk_if_wrong="若在扩张波动中追高，回撤会先于基本面确认出现。",
            staging_plan=[
                "不建立观察仓位，等待风险收益重新打开。",
                "若已有持仓，避免提高风险暴露。",
            ],
            holding_adjustment=_holding_adjustment(
                inputs.current_holding,
                "设置已偏扩张，本轮不提高目标上限。",
            ),
        )

    return ActionRecommendation(
        decision=ActionDecision.WAIT_FOR_CONFIRMATION,
        position_min_pct=0.0,
        position_max_pct=3.0,
        reasoning=[
            "证据尚未同时满足强设置阈值，适合等待确认。",
            _score_summary(inputs),
        ],
        required_confirmation=_missing_confirmations(inputs),
        invalidation_conditions=invalidation_conditions,
        risk_if_wrong="若过早参与，可能在确认不足时承担无效波动。",
        staging_plan=[
            "未持有时保持 0%-3% 观察区间。",
            "确认补足前不提高仓位暴露。",
        ],
        holding_adjustment=_holding_adjustment(
            inputs.current_holding,
            "确认不足，本轮不提高目标上限。",
        ),
    )


def _current_position(holding: ManualHolding | None) -> float:
    if holding is None:
        return 0.0
    return max(holding.position_pct, 0.0)


def _pct(value: float) -> float:
    return round(max(value, 0.0), 2)


def _score_summary(inputs: ActionPolicyInput) -> str:
    return (
        f"市场支持 {inputs.market_support:.2f}，"
        f"thesis 质量 {inputs.thesis_quality:.2f}，"
        f"风险收益比 {inputs.risk_reward:.2f}，"
        f"20 日波动率 {inputs.volatility_20d:.2f}，"
        f"流动性 {inputs.liquidity_score:.2f}。"
    )


def _hard_risk_flags(inputs: ActionPolicyInput) -> list[str]:
    flags: list[str] = []
    if inputs.hard_risk:
        flags.append("硬风险标记已触发")
    if inputs.liquidity_score < 0.25:
        flags.append("流动性评分低于 0.25")
    if inputs.risk_reward < 1.0:
        flags.append("风险收益比低于 1.0")
    if inputs.volatility_20d > 0.45:
        flags.append("20 日波动率高于 0.45")
    return flags


def _is_strong_setup(inputs: ActionPolicyInput) -> bool:
    return (
        inputs.market_support >= 0.70
        and inputs.thesis_quality >= 0.75
        and inputs.risk_reward >= 1.5
        and inputs.volatility_20d <= 0.35
        and inputs.liquidity_score >= 0.60
    )


def _is_extended_setup(inputs: ActionPolicyInput) -> bool:
    return (
        inputs.market_support >= 0.70
        and inputs.thesis_quality >= 0.75
        and (inputs.risk_reward < 1.5 or inputs.volatility_20d > 0.35)
    )


def _missing_confirmations(inputs: ActionPolicyInput) -> list[str]:
    confirmations: list[str] = []
    if inputs.market_support < 0.70:
        confirmations.append("市场或板块支持提升至 0.70 以上")
    if inputs.thesis_quality < 0.75:
        confirmations.append("thesis 质量补足至 0.75 以上")
    if inputs.risk_reward < 1.5:
        confirmations.append("风险收益比修复至 1.5 以上")
    if inputs.volatility_20d > 0.35:
        confirmations.append("20 日波动率回落至 0.35 以下")
    if inputs.liquidity_score < 0.60:
        confirmations.append("流动性评分恢复至 0.60 以上")
    if inputs.catalyst_freshness == "none":
        confirmations.append("催化证据需要更新或得到官方确认")
    if confirmations:
        return confirmations
    return ["关键证据继续维持，且失效条件未触发"]


def _holding_adjustment(holding: ManualHolding | None, message: str) -> str | None:
    if holding is None:
        return None
    return f"当前持仓 {holding.position_pct:.1f}%；{message}"
