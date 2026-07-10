from __future__ import annotations

import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from stock_analyzer.data.models import DailyBar
from stock_analyzer.domain.models import (
    ActionDecision,
    EvidenceAtom,
    EvidencePolarity,
    StrategyEvidenceSnapshot,
)

PositionAggressiveness = Literal["too_aggressive", "reasonable", "too_conservative"]
ObservedAlignment = Literal[
    "support_aligned",
    "support_countered",
    "support_unresolved",
    "counter_aligned",
    "counter_countered",
    "counter_unresolved",
    "mixed_support_aligned",
    "mixed_counter_aligned",
    "mixed_unresolved",
]

OUTCOME_CHECKPOINT_DAYS = (5, 20, 40)

_BREAK_KEYWORDS = ("跌破", "下破", "失守", "破位", "break", "below")
_PARTICIPATION_DECISIONS = {
    ActionDecision.SMALL_EXPLORATORY,
    ActionDecision.INCREASE_ATTENTION,
    ActionDecision.CONDITIONAL_ADD,
}
_PROTECTIVE_DECISIONS = {
    ActionDecision.NO_PARTICIPATION,
    ActionDecision.CONTINUE_WATCHING,
    ActionDecision.WAIT_FOR_CONFIRMATION,
    ActionDecision.AVOID_CHASING,
    ActionDecision.REDUCE_OR_AVOID,
    ActionDecision.CONFIRM_REMOVAL,
}
_THESIS_KEYWORDS_TO_CHECK = (
    "AI",
    "算力",
    "政策",
    "监管",
    "业绩",
    "重组",
    "订单",
    "分红",
    "减持",
    "增持",
)


class OutcomeWindowInput(BaseModel):
    checkpoint_days: int
    bars_observed: int
    insufficient_data: bool
    first_trade_date: date | None = None
    last_trade_date: date | None = None
    entry_close_used: float | None = None
    max_favorable_excursion_pct: float | None = None
    max_close_return_pct: float | None = None
    min_close_return_pct: float | None = None
    max_drawdown_pct: float | None = None
    final_close_return_pct: float | None = None
    invalidation_occurred: bool = False


class KnowledgeRuleEffect(BaseModel):
    rule_id: str | None = None
    module: str
    support_count: int = 0
    counter_count: int = 0
    neutral_count: int = 0
    support_evidence_ids: list[str] = Field(default_factory=list)
    counter_evidence_ids: list[str] = Field(default_factory=list)
    neutral_evidence_ids: list[str] = Field(default_factory=list)
    observed_alignment: ObservedAlignment


class DataRequirementIssue(BaseModel):
    module: str
    family: str
    level: str
    availability: str
    missing_fields: list[str] = Field(default_factory=list)
    blocks_complete_analysis: bool = False


class MissingDataEffect(BaseModel):
    insufficient_future_bars: bool
    bars_observed: int
    expected_checkpoints: list[int] = Field(default_factory=lambda: list(OUTCOME_CHECKPOINT_DAYS))
    missing_ohlc_fields: list[str] = Field(default_factory=list)
    ignored_bar_count: int = 0
    snapshot_data_insufficient: bool = False
    snapshot_data_insufficient_reason: str | None = None
    data_requirement_issues: list[DataRequirementIssue] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class EvaluationResultPayload(BaseModel):
    evidence_id: str
    trade_date: date
    ts_code: str
    entry_close_used: float | None = None
    future_bar_count: int
    outcome_inputs: dict[int, OutcomeWindowInput]
    invalidation_occurred: bool
    action_useful: bool | None
    position_aggressiveness: PositionAggressiveness
    knowledge_rule_effect: list[KnowledgeRuleEffect] = Field(default_factory=list)
    missing_data_effect: MissingDataEffect
    unsupported_narrative_flags: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


def evaluate_strategy_snapshot(
    snapshot: StrategyEvidenceSnapshot,
    future_bars: list[DailyBar],
) -> EvaluationResultPayload:
    matched_bars, ignored_bar_count = _future_bars_for_snapshot(snapshot, future_bars)
    horizon_bars = matched_bars[: OUTCOME_CHECKPOINT_DAYS[-1]]
    entry_close, baseline_notes = _entry_close(matched_bars)
    missing_data_effect = _missing_data_effect(snapshot, horizon_bars, ignored_bar_count)
    missing_data_effect.notes.extend(baseline_notes)

    invalidation_threshold = _invalidation_threshold_pct(snapshot)
    outcome_inputs = {
        days: _outcome_window(days, matched_bars, entry_close, invalidation_threshold)
        for days in OUTCOME_CHECKPOINT_DAYS
    }
    full_window = outcome_inputs[OUTCOME_CHECKPOINT_DAYS[-1]]
    invalidation_occurred = full_window.invalidation_occurred
    successful_favorable_excursion = _successful_favorable_excursion(full_window, snapshot)

    action_useful = _action_usefulness(
        snapshot.action.decision,
        invalidation_occurred,
        successful_favorable_excursion,
        missing_data_effect,
    )
    position_aggressiveness = _position_aggressiveness(
        snapshot,
        full_window,
        invalidation_occurred,
    )
    knowledge_rule_effect = _knowledge_rule_effect(
        snapshot,
        invalidation_occurred,
        successful_favorable_excursion,
        full_window,
    )
    unsupported_narrative_flags = _unsupported_narrative_flags(snapshot, matched_bars)

    notes = _result_notes(
        snapshot,
        full_window,
        invalidation_threshold,
        invalidation_occurred,
        action_useful,
        position_aggressiveness,
        missing_data_effect,
    )

    return EvaluationResultPayload(
        evidence_id=snapshot.evidence_id,
        trade_date=snapshot.trade_date,
        ts_code=snapshot.ts_code,
        entry_close_used=entry_close,
        future_bar_count=len(matched_bars),
        outcome_inputs=outcome_inputs,
        invalidation_occurred=invalidation_occurred,
        action_useful=action_useful,
        position_aggressiveness=position_aggressiveness,
        knowledge_rule_effect=knowledge_rule_effect,
        missing_data_effect=missing_data_effect,
        unsupported_narrative_flags=unsupported_narrative_flags,
        notes=notes,
    )


def _future_bars_for_snapshot(
    snapshot: StrategyEvidenceSnapshot,
    future_bars: list[DailyBar],
) -> tuple[list[DailyBar], int]:
    matched = [
        bar
        for bar in future_bars
        if bar.ts_code == snapshot.ts_code and bar.trade_date > snapshot.trade_date
    ]
    ignored = len(future_bars) - len(matched)
    return sorted(matched, key=lambda bar: bar.trade_date), ignored


def _entry_close(bars: list[DailyBar]) -> tuple[float | None, list[str]]:
    if not bars:
        return None, ["No future bars are available to infer an entry close."]

    first_bar = bars[0]
    if first_bar.pre_close is not None and first_bar.pre_close > 0:
        return first_bar.pre_close, []
    if first_bar.close > 0:
        return first_bar.close, [
            "First future bar is missing pre_close; used first future close as a conservative baseline."
        ]
    return None, ["First future bar has no usable pre_close or close baseline."]


def _missing_data_effect(
    snapshot: StrategyEvidenceSnapshot,
    bars: list[DailyBar],
    ignored_bar_count: int,
) -> MissingDataEffect:
    missing_fields = [
        field
        for field in ("high", "low", "pre_close")
        if any(getattr(bar, field) is None for bar in bars)
    ]
    data_requirement_issues = _data_requirement_issues(snapshot)
    notes: list[str] = []
    if len(bars) < OUTCOME_CHECKPOINT_DAYS[0]:
        notes.append("Fewer than 5 future bars; all 5/20/40 outcomes remain partial.")
    elif len(bars) < OUTCOME_CHECKPOINT_DAYS[-1]:
        notes.append("Fewer than 40 future bars; longer horizon outcomes remain partial.")
    if missing_fields:
        notes.append(f"Missing replay fields: {', '.join(missing_fields)}.")
    if ignored_bar_count:
        notes.append(f"Ignored {ignored_bar_count} bar(s) outside the snapshot code/date window.")
    if snapshot.data_insufficient:
        reason = snapshot.data_insufficient_reason or "reason not provided"
        notes.append(f"Snapshot marked data insufficient: {reason}.")
    if data_requirement_issues:
        issue_summaries = [
            f"{issue.module}/{issue.family}={issue.availability}"
            for issue in data_requirement_issues
        ]
        notes.append(f"Snapshot data requirement issues: {', '.join(issue_summaries)}.")

    return MissingDataEffect(
        insufficient_future_bars=len(bars) < OUTCOME_CHECKPOINT_DAYS[-1],
        bars_observed=len(bars),
        missing_ohlc_fields=missing_fields,
        ignored_bar_count=ignored_bar_count,
        snapshot_data_insufficient=snapshot.data_insufficient,
        snapshot_data_insufficient_reason=snapshot.data_insufficient_reason,
        data_requirement_issues=data_requirement_issues,
        notes=notes,
    )


def _data_requirement_issues(snapshot: StrategyEvidenceSnapshot) -> list[DataRequirementIssue]:
    issues: list[DataRequirementIssue] = []
    for module in snapshot.modules:
        for requirement in module.data_requirements:
            availability = requirement.availability.value
            if (
                not requirement.missing_fields
                and not requirement.blocks_complete_analysis
                and "unavailable" not in availability
            ):
                continue
            issues.append(
                DataRequirementIssue(
                    module=module.module.value,
                    family=requirement.family,
                    level=requirement.level.value,
                    availability=availability,
                    missing_fields=list(requirement.missing_fields),
                    blocks_complete_analysis=requirement.blocks_complete_analysis,
                )
            )
    return issues


def _outcome_window(
    checkpoint_days: int,
    bars: list[DailyBar],
    entry_close: float | None,
    invalidation_threshold_pct: float,
) -> OutcomeWindowInput:
    window_bars = bars[:checkpoint_days]
    if not window_bars or entry_close is None or entry_close <= 0:
        return OutcomeWindowInput(
            checkpoint_days=checkpoint_days,
            bars_observed=len(window_bars),
            insufficient_data=len(bars) < checkpoint_days,
            entry_close_used=entry_close,
        )

    high_returns = [
        _pct_change(bar.high if bar.high is not None else bar.close, entry_close)
        for bar in window_bars
    ]
    close_returns = [_pct_change(bar.close, entry_close) for bar in window_bars]
    low_returns = [
        _pct_change(bar.low if bar.low is not None else bar.close, entry_close)
        for bar in window_bars
    ]
    high_returns = [value for value in high_returns if value is not None]
    close_returns = [value for value in close_returns if value is not None]
    low_returns = [value for value in low_returns if value is not None]

    max_drawdown_pct = min(low_returns) if low_returns else None
    min_close_return_pct = min(close_returns) if close_returns else None
    invalidation_occurred = _window_invalidated(
        max_drawdown_pct,
        min_close_return_pct,
        invalidation_threshold_pct,
    )

    return OutcomeWindowInput(
        checkpoint_days=checkpoint_days,
        bars_observed=len(window_bars),
        insufficient_data=len(bars) < checkpoint_days,
        first_trade_date=window_bars[0].trade_date,
        last_trade_date=window_bars[-1].trade_date,
        entry_close_used=entry_close,
        max_favorable_excursion_pct=round(max(high_returns), 4) if high_returns else None,
        max_close_return_pct=round(max(close_returns), 4) if close_returns else None,
        min_close_return_pct=round(min_close_return_pct, 4)
        if min_close_return_pct is not None
        else None,
        max_drawdown_pct=round(max_drawdown_pct, 4) if max_drawdown_pct is not None else None,
        final_close_return_pct=round(close_returns[-1], 4) if close_returns else None,
        invalidation_occurred=invalidation_occurred,
    )


def _pct_change(value: float | None, baseline: float) -> float | None:
    if value is None or baseline <= 0:
        return None
    return (value - baseline) / baseline * 100


def _window_invalidated(
    max_drawdown_pct: float | None,
    min_close_return_pct: float | None,
    invalidation_threshold_pct: float,
) -> bool:
    return any(
        value is not None and value <= invalidation_threshold_pct
        for value in (max_drawdown_pct, min_close_return_pct)
    )


def _invalidation_threshold_pct(snapshot: StrategyEvidenceSnapshot) -> float:
    if snapshot.expected_downside_pct is not None and snapshot.expected_downside_pct > 0:
        return -abs(snapshot.expected_downside_pct)

    condition_text = " ".join(snapshot.action.invalidation_conditions)
    explicit_pct = re.search(r"(-?\d+(?:\.\d+)?)\s*%", condition_text)
    if explicit_pct is not None:
        return -abs(float(explicit_pct.group(1)))
    if any(keyword in condition_text for keyword in _BREAK_KEYWORDS):
        return -5.0
    return -8.0


def _successful_favorable_excursion(
    outcome: OutcomeWindowInput,
    snapshot: StrategyEvidenceSnapshot,
) -> bool:
    if outcome.max_favorable_excursion_pct is None:
        return False
    if snapshot.expected_upside_pct is not None and snapshot.expected_upside_pct > 0:
        return outcome.max_favorable_excursion_pct >= min(5.0, snapshot.expected_upside_pct)
    return outcome.max_favorable_excursion_pct >= 5.0


def _action_usefulness(
    decision: ActionDecision,
    invalidation_occurred: bool,
    successful_favorable_excursion: bool,
    missing_data_effect: MissingDataEffect,
) -> bool | None:
    if not missing_data_effect.bars_observed:
        return None
    if invalidation_occurred:
        if decision in _PROTECTIVE_DECISIONS:
            return True
        if decision in _PARTICIPATION_DECISIONS:
            return False
        return None
    if successful_favorable_excursion and decision in _PARTICIPATION_DECISIONS:
        return True
    if successful_favorable_excursion and decision in {
        ActionDecision.NO_PARTICIPATION,
        ActionDecision.AVOID_CHASING,
        ActionDecision.REDUCE_OR_AVOID,
        ActionDecision.CONFIRM_REMOVAL,
    }:
        return False
    return None


def _position_aggressiveness(
    snapshot: StrategyEvidenceSnapshot,
    outcome: OutcomeWindowInput,
    invalidation_occurred: bool,
) -> PositionAggressiveness:
    position_max = snapshot.action.position_max_pct
    position_min = snapshot.action.position_min_pct
    drawdown = outcome.max_drawdown_pct
    favorable = outcome.max_favorable_excursion_pct

    if invalidation_occurred and position_max >= 5:
        return "too_aggressive"
    if drawdown is not None and drawdown <= -8 and position_max > 5:
        return "too_aggressive"
    if (
        favorable is not None
        and favorable >= 8
        and not invalidation_occurred
        and position_max <= 3
    ):
        return "too_conservative"
    if (
        favorable is not None
        and favorable < 3
        and drawdown is not None
        and drawdown <= -3
        and position_min > 5
    ):
        return "too_aggressive"
    return "reasonable"


def _knowledge_rule_effect(
    snapshot: StrategyEvidenceSnapshot,
    invalidation_occurred: bool,
    successful_favorable_excursion: bool,
    outcome: OutcomeWindowInput,
) -> list[KnowledgeRuleEffect]:
    buckets: dict[tuple[str | None, str], dict[str, list[str]]] = {}
    for atom in _all_atoms(snapshot):
        rule_ids = atom.knowledge_rule_ids or [None]
        for rule_id in rule_ids:
            key = (rule_id, atom.module.value)
            bucket = buckets.setdefault(
                key, {"support": [], "counter": [], "neutral": []}
            )
            if atom.polarity == EvidencePolarity.SUPPORT:
                bucket["support"].append(atom.id)
            elif atom.polarity == EvidencePolarity.COUNTER:
                bucket["counter"].append(atom.id)
            elif atom.polarity == EvidencePolarity.NEUTRAL:
                bucket["neutral"].append(atom.id)

    effects = []
    for (rule_id, module), bucket in sorted(
        buckets.items(), key=lambda item: ((item[0][0] or ""), item[0][1])
    ):
        support_ids = bucket["support"]
        counter_ids = bucket["counter"]
        neutral_ids = bucket["neutral"]
        effects.append(
            KnowledgeRuleEffect(
                rule_id=rule_id,
                module=module,
                support_count=len(support_ids),
                counter_count=len(counter_ids),
                neutral_count=len(neutral_ids),
                support_evidence_ids=support_ids,
                counter_evidence_ids=counter_ids,
                neutral_evidence_ids=neutral_ids,
                observed_alignment=_observed_alignment(
                    len(support_ids),
                    len(counter_ids),
                    invalidation_occurred,
                    successful_favorable_excursion,
                    outcome.max_drawdown_pct,
                ),
            )
        )
    return effects


def _observed_alignment(
    support_count: int,
    counter_count: int,
    invalidation_occurred: bool,
    successful_favorable_excursion: bool,
    max_drawdown_pct: float | None,
) -> ObservedAlignment:
    meaningful_drawdown = max_drawdown_pct is not None and max_drawdown_pct <= -5
    if support_count == 0 and counter_count == 0:
        return "mixed_unresolved"
    if support_count and not counter_count:
        if invalidation_occurred or meaningful_drawdown:
            return "support_countered"
        if successful_favorable_excursion:
            return "support_aligned"
        return "support_unresolved"
    if counter_count and not support_count:
        if invalidation_occurred or meaningful_drawdown:
            return "counter_aligned"
        if successful_favorable_excursion:
            return "counter_countered"
        return "counter_unresolved"
    if successful_favorable_excursion and support_count >= counter_count:
        return "mixed_support_aligned"
    if (invalidation_occurred or meaningful_drawdown) and counter_count >= support_count:
        return "mixed_counter_aligned"
    return "mixed_unresolved"


def _all_atoms(snapshot: StrategyEvidenceSnapshot) -> list[EvidenceAtom]:
    atoms: list[EvidenceAtom] = []
    for module in snapshot.modules:
        atoms.extend(module.support)
        atoms.extend(module.counter)
    return atoms


def _unsupported_narrative_flags(
    snapshot: StrategyEvidenceSnapshot,
    bars: list[DailyBar],
) -> list[str]:
    atoms = _all_atoms(snapshot)
    flags: list[str] = []
    if not snapshot.modules:
        flags.append("Snapshot has no evidence modules supporting its thesis/action narrative.")
    if not atoms:
        flags.append("Snapshot has no evidence atoms for structured replay attribution.")
    if len(bars) < OUTCOME_CHECKPOINT_DAYS[0]:
        flags.append("Future bars are insufficient to check 5/20/40 outcome claims.")

    evidence_text = " ".join(
        [atom.headline + " " + atom.detail for atom in atoms]
        + [module.summary + " " + module.conclusion for module in snapshot.modules]
    )
    for keyword in _THESIS_KEYWORDS_TO_CHECK:
        if keyword in snapshot.thesis and keyword not in evidence_text:
            flags.append(f"Thesis mentions {keyword} without matching evidence atoms/modules.")
    return flags


def _result_notes(
    snapshot: StrategyEvidenceSnapshot,
    outcome: OutcomeWindowInput,
    invalidation_threshold: float,
    invalidation_occurred: bool,
    action_useful: bool | None,
    position_aggressiveness: PositionAggressiveness,
    missing_data_effect: MissingDataEffect,
) -> list[str]:
    notes = list(missing_data_effect.notes)
    if invalidation_occurred:
        condition_text = "；".join(snapshot.action.invalidation_conditions)
        notes.append(
            "Invalidation proxy matched "
            f"({condition_text}) at threshold {invalidation_threshold:.2f}%."
        )
    elif outcome.max_favorable_excursion_pct is not None:
        notes.append(
            "Replay favorable excursion "
            f"{outcome.max_favorable_excursion_pct:.2f}% with max drawdown "
            f"{_format_optional_pct(outcome.max_drawdown_pct)}."
        )

    if action_useful is True:
        notes.append("Action was useful under replay rules.")
    elif action_useful is False:
        notes.append("Action was not useful under replay rules.")
    else:
        notes.append("Action usefulness is unresolved from available replay inputs.")
    notes.append(f"Position aggressiveness classified as {position_aggressiveness}.")
    return notes


def _format_optional_pct(value: float | None) -> str:
    if value is None:
        return "unknown"
    return f"{value:.2f}%"


__all__ = [
    "DataRequirementIssue",
    "EvaluationResultPayload",
    "KnowledgeRuleEffect",
    "MissingDataEffect",
    "OutcomeWindowInput",
    "evaluate_strategy_snapshot",
]
