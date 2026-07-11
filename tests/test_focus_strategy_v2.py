from datetime import date, timedelta

from stock_analyzer.analysis.focus import (
    FormalFocusDay,
    contiguous_focus_window,
    update_focus_watchlist_v2,
)
from stock_analyzer.analysis.strategy_v2 import generate_strategy_v2_recommendations
from stock_analyzer.domain.models import (
    ActionDecision,
    ActionLabel,
    FocusSource,
    FocusState,
)
from tests.test_strategy_v2_recommendation import _feature


def _snapshot(
    trade_date: date,
    code: str = "600000.SH",
    feature_updates: dict | None = None,
):
    feature = _feature(code).model_copy(update=feature_updates or {})
    return generate_strategy_v2_recommendations(
        features=[feature],
        stock_names={code: "浦发银行"},
        trade_date=trade_date,
    ).snapshots[0]


def _supporting_history(
    code: str,
    start: date = date(2026, 7, 6),
    feature_updates: dict | None = None,
    transform=None,
):
    history = [
        _snapshot(start + timedelta(days=offset), code, feature_updates)
        for offset in range(5)
    ]
    if transform is None:
        return history
    return [transform(snapshot) for snapshot in history]


def _without_support(snapshot):
    return snapshot.model_copy(
        update={
            "modules": [
                module.model_copy(update={"support": []})
                for module in snapshot.modules
            ]
        }
    )


def _with_ranking_fields(
    snapshot,
    *,
    internal_score: float,
    risk_reward: float,
    thesis_strength: float,
    liquidity_strength: float,
):
    modules = []
    for module in snapshot.modules:
        support = []
        for atom in module.support:
            strength = (
                liquidity_strength
                if "liquidity_score" in atom.data_fields
                else thesis_strength
            )
            support.append(atom.model_copy(update={"strength": strength}))
        modules.append(module.model_copy(update={"support": support}))
    return snapshot.model_copy(
        update={
            "internal_score": internal_score,
            "risk_reward": risk_reward,
            "modules": modules,
        }
    )


def _existing_focus(code: str, trade_date: date = date(2026, 7, 9)) -> FocusState:
    return FocusState(
        trade_date=trade_date,
        ts_code=code,
        state=ActionLabel.ENTER_OBSERVATION,
        entry_date=trade_date,
        entry_reason="系统证据成立",
        invalidation_conditions=["跌破关键支撑"],
    )


def test_system_focus_enters_after_full_five_observation_window_with_support():
    history = _supporting_history("600000.SH")

    result = update_focus_watchlist_v2(
        existing=[],
        recommendation_snapshots=history,
        manual_entries=[],
        trade_date=date(2026, 7, 10),
    )

    assert len(result.focus_states) == 1
    assert result.focus_states[0].ts_code == "600000.SH"
    assert result.focus_states[0].state.value == "进入观察"
    assert result.entry_theses[0].source == FocusSource.SYSTEM
    assert result.entry_theses[0].expected_upside_pct >= 10.0
    assert result.entry_theses[0].risk_reward >= 1.5
    assert result.entry_theses[0].action.invalidation_conditions


def test_system_focus_requires_full_five_observation_window_before_entry():
    start = date(2026, 7, 6)
    history = [
        _snapshot(start + timedelta(days=offset), "600000.SH")
        for offset in range(3)
    ]

    result = update_focus_watchlist_v2(
        existing=[],
        recommendation_snapshots=history,
        manual_entries=[],
        trade_date=date(2026, 7, 10),
    )

    assert result.focus_states == []
    assert result.entry_theses == []


def test_existing_system_focus_count_consumes_system_cap():
    existing = [_existing_focus(f"300{index:03d}.SZ") for index in range(5)]
    snapshots = [
        snapshot
        for index in range(5)
        for snapshot in _supporting_history(f"600{index:03d}.SH")
    ]

    result = update_focus_watchlist_v2(
        existing=existing,
        recommendation_snapshots=snapshots,
        manual_entries=[],
        trade_date=date(2026, 7, 10),
    )

    assert {state.ts_code for state in result.focus_states} == {
        focus.ts_code for focus in existing
    }
    assert [
        thesis for thesis in result.entry_theses if thesis.source == FocusSource.SYSTEM
    ] == []


def test_system_focus_is_capped_at_five_but_manual_entries_are_not_counted():
    snapshots = [
        snapshot
        for index in range(8)
        for snapshot in _supporting_history(f"600{index:03d}.SH")
    ]
    manual_entries = [("000001.SZ", "已有持仓，需要验证外部推荐")]

    result = update_focus_watchlist_v2(
        existing=[],
        recommendation_snapshots=snapshots,
        manual_entries=manual_entries,
        trade_date=date(2026, 7, 10),
    )

    system_count = sum(
        1 for thesis in result.entry_theses if thesis.source == FocusSource.SYSTEM
    )
    manual_count = sum(
        1 for thesis in result.entry_theses if thesis.source == FocusSource.MANUAL
    )

    assert system_count == 5
    assert manual_count == 1
    assert len(result.focus_states) == 6


def test_system_focus_rejects_low_liquidity_and_wait_for_confirmation_candidates():
    low_liquidity_history = _supporting_history(
        "600010.SH",
        feature_updates={"liquidity_score": 0.3},
    )
    wait_for_confirmation_history = _supporting_history(
        "600011.SH",
        feature_updates={"quality_score": 0.2},
    )

    assert (
        low_liquidity_history[-1].action.decision
        == ActionDecision.WAIT_FOR_CONFIRMATION
    )
    assert (
        wait_for_confirmation_history[-1].action.decision
        == ActionDecision.WAIT_FOR_CONFIRMATION
    )

    result = update_focus_watchlist_v2(
        existing=[],
        recommendation_snapshots=low_liquidity_history + wait_for_confirmation_history,
        manual_entries=[],
        trade_date=date(2026, 7, 10),
    )

    assert result.focus_states == []
    assert result.entry_theses == []


def test_system_focus_rejects_candidate_without_actual_supporting_evidence():
    history = _supporting_history("600012.SH", transform=_without_support)

    assert history[-1].action.decision == ActionDecision.SMALL_EXPLORATORY
    assert all(not module.support for module in history[-1].modules)

    result = update_focus_watchlist_v2(
        existing=[],
        recommendation_snapshots=history,
        manual_entries=[],
        trade_date=date(2026, 7, 10),
    )

    assert result.focus_states == []
    assert result.entry_theses == []


def test_system_focus_ranks_by_internal_score_thesis_quality_then_liquidity():
    ranking_specs = {
        "600100.SH": (100.0, 9.0, 0.40, 0.95),
        "600101.SH": (100.0, 1.5, 0.95, 0.60),
        "600102.SH": (100.0, 1.6, 0.90, 0.70),
        "600103.SH": (100.0, 1.7, 0.85, 0.80),
        "600104.SH": (100.0, 1.8, 0.80, 0.90),
        "600105.SH": (100.0, 1.9, 0.75, 0.95),
    }
    snapshots = []
    for code, (internal_score, risk_reward, thesis_strength, liquidity_strength) in (
        ranking_specs.items()
    ):
        snapshots.extend(
            _supporting_history(
                code,
                transform=lambda snapshot,
                internal_score=internal_score,
                risk_reward=risk_reward,
                thesis_strength=thesis_strength,
                liquidity_strength=liquidity_strength: _with_ranking_fields(
                    snapshot,
                    internal_score=internal_score,
                    risk_reward=risk_reward,
                    thesis_strength=thesis_strength,
                    liquidity_strength=liquidity_strength,
                ),
            )
        )

    result = update_focus_watchlist_v2(
        existing=[],
        recommendation_snapshots=snapshots,
        manual_entries=[],
        trade_date=date(2026, 7, 10),
    )

    selected_codes = {
        thesis.ts_code
        for thesis in result.entry_theses
        if thesis.source == FocusSource.SYSTEM
    }
    assert selected_codes == {
        "600101.SH",
        "600102.SH",
        "600103.SH",
        "600104.SH",
        "600105.SH",
    }


def test_manual_focus_analysis_does_not_praise_missing_evidence():
    result = update_focus_watchlist_v2(
        existing=[],
        recommendation_snapshots=[],
        manual_entries=[("000001.SZ", "外部推荐说有重大题材")],
        trade_date=date(2026, 7, 10),
    )

    thesis = result.entry_theses[0]

    assert thesis.source == FocusSource.MANUAL
    assert thesis.validation_result == "证据不足"
    assert "证据不足" in "；".join(thesis.risk_notes)
    assert "支持 2-8 周观察" not in thesis.thesis


def test_existing_focus_with_stale_history_without_today_snapshot_gets_data_insufficient_update():
    stale_history = _supporting_history("600000.SH", start=date(2026, 7, 5))
    existing = [_existing_focus("600000.SH", trade_date=date(2026, 7, 9))]

    assert stale_history[-1].trade_date == date(2026, 7, 9)
    assert stale_history[-1].action.decision != ActionDecision.CONFIRM_REMOVAL

    result = update_focus_watchlist_v2(
        existing=existing,
        recommendation_snapshots=stale_history,
        manual_entries=[],
        trade_date=date(2026, 7, 10),
    )

    update = result.daily_updates[0]
    assert update.trade_date == date(2026, 7, 10)
    assert update.evidence_id != stale_history[-1].evidence_id
    assert update.data_insufficient is True
    assert update.new_support == []
    assert update.action.decision == ActionDecision.CONFIRM_REMOVAL
    assert "数据不足" in update.thesis
    assert "支持 2-8 周观察" not in update.thesis


def _formal_previous_days(**overrides):
    dates = [
        date(2026, 7, 3),
        date(2026, 7, 6),
        date(2026, 7, 7),
        date(2026, 7, 8),
        date(2026, 7, 9),
    ]
    days = [
        FormalFocusDay(trade_date=value, formally_committed=True)
        for value in dates
    ]
    for index, update in overrides.items():
        days[int(index)] = days[int(index)].model_copy(update=update)
    return days


def _formal_history(code="600000.SH"):
    prior_dates = [day.trade_date for day in _formal_previous_days()]
    return [_snapshot(value, code) for value in prior_dates] + [_snapshot(date(2026, 7, 10), code)]


def test_focus_uses_five_immediately_preceding_eligible_dates():
    history = _formal_history()
    window = contiguous_focus_window(
        history,
        _formal_previous_days(),
        date(2026, 7, 10),
    )

    result = update_focus_watchlist_v2(
        existing=[],
        recommendation_snapshots=history,
        manual_entries=[],
        trade_date=date(2026, 7, 10),
        eligible_focus_days=_formal_previous_days(),
    )

    assert [item.trade_date for item in window] == [
        date(2026, 7, 3),
        date(2026, 7, 6),
        date(2026, 7, 7),
        date(2026, 7, 8),
        date(2026, 7, 9),
    ]
    assert [state.ts_code for state in result.focus_states] == ["600000.SH"]


def test_blocked_middle_day_breaks_window_instead_of_using_older_snapshot():
    older = _snapshot(date(2026, 7, 2))
    history = [older, *_formal_history()]
    days = _formal_previous_days(**{"2": {"formally_committed": False, "blocked": True}})

    result = update_focus_watchlist_v2(
        existing=[],
        recommendation_snapshots=history,
        manual_entries=[],
        trade_date=date(2026, 7, 10),
        eligible_focus_days=days,
    )

    assert result.focus_states == []
    assert contiguous_focus_window(history, days, date(2026, 7, 10)) == []


def test_fixture_incomplete_and_backfill_only_days_do_not_count():
    history = _formal_history()
    invalid_days = (
        _formal_previous_days(**{"1": {"fixture": True}}),
        _formal_previous_days(**{"1": {"formally_committed": False}}),
        _formal_previous_days(**{"1": {"backfill_only": True}}),
    )

    for days in invalid_days:
        assert contiguous_focus_window(history, days, date(2026, 7, 10)) == []


def test_formally_committed_zero_recommendation_focus_day_counts():
    history = _formal_history()
    days = _formal_previous_days()

    window = contiguous_focus_window(history, days, date(2026, 7, 10))

    assert len(window) == 5
    assert all(day.formally_committed for day in days)


def test_reconciled_primary_does_not_retroactively_create_focus_observation():
    history = _formal_history()
    days = _formal_previous_days(
        **{"0": {"formally_committed": False, "backfill_only": True}}
    )

    assert contiguous_focus_window(history, days, date(2026, 7, 10)) == []
