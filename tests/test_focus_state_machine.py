from datetime import date

from stock_analyzer.analysis.focus import update_focus_watchlist, update_focus_watchlist_v2
from stock_analyzer.analysis.strategy_v2 import generate_strategy_v2_recommendations
from stock_analyzer.domain.models import ActionLabel, FocusState, Recommendation
from tests.test_strategy_v2_recommendation import _feature


def rec(code: str, score: float = 82.0) -> Recommendation:
    return Recommendation(
        trade_date=date(2026, 7, 7),
        ts_code=code,
        name=code,
        action=ActionLabel.ENTER_OBSERVATION,
        score=score,
        reasons=["趋势持续", "行业支持"],
        risks=["需要确认"],
    )


def test_recommendation_enters_focus_only_when_score_strong():
    result = update_focus_watchlist(
        existing=[],
        recommendations=[rec("600000.SH", 82)],
        invalidated_codes=set(),
    )
    assert len(result) == 1
    assert result[0].state == ActionLabel.ENTER_OBSERVATION
    assert result[0].entry_date == date(2026, 7, 7)


def test_existing_focus_continues_when_not_recommended_today():
    existing = [
        FocusState(
            trade_date=date(2026, 7, 6),
            ts_code="600000.SH",
            state=ActionLabel.ENTER_OBSERVATION,
            entry_date=date(2026, 7, 6),
            entry_reason="原始证据成立",
            invalidation_conditions=["跌破关键支撑"],
        )
    ]
    result = update_focus_watchlist(existing=existing, recommendations=[], invalidated_codes=set())
    assert result[0].state == ActionLabel.CONTINUE_OBSERVATION


def test_existing_focus_exits_when_invalidated():
    existing = [
        FocusState(
            trade_date=date(2026, 7, 6),
            ts_code="600000.SH",
            state=ActionLabel.ENTER_OBSERVATION,
            entry_date=date(2026, 7, 6),
            entry_reason="原始证据成立",
            invalidation_conditions=["跌破关键支撑"],
        )
    ]
    result = update_focus_watchlist(
        existing=existing,
        recommendations=[],
        invalidated_codes={"600000.SH"},
    )
    assert result[0].state == ActionLabel.EXIT_OBSERVATION
    assert result[0].exit_reason == "触发预设失效条件"


def test_invalidated_recommendation_does_not_reenter_focus():
    result = update_focus_watchlist(
        existing=[],
        recommendations=[rec("600000.SH", 99)],
        invalidated_codes={"600000.SH"},
    )
    assert result == []


def test_low_score_recommendation_does_not_enter_focus():
    result = update_focus_watchlist(
        existing=[],
        recommendations=[rec("600000.SH", 79.9)],
        invalidated_codes=set(),
    )
    assert result == []


def test_v2_existing_focus_continues_and_receives_daily_update():
    existing = [
        FocusState(
            trade_date=date(2026, 7, 9),
            ts_code="600000.SH",
            state=ActionLabel.ENTER_OBSERVATION,
            entry_date=date(2026, 7, 8),
            entry_reason="原始证据成立",
            invalidation_conditions=["跌破关键支撑"],
        )
    ]
    snapshot = generate_strategy_v2_recommendations(
        features=[_feature("600000.SH")],
        stock_names={"600000.SH": "浦发银行"},
        trade_date=date(2026, 7, 10),
    ).snapshots[0]

    result = update_focus_watchlist_v2(
        existing=existing,
        recommendation_snapshots=[snapshot],
        manual_entries=[],
        trade_date=date(2026, 7, 10),
    )

    assert result.focus_states[0].state == ActionLabel.CONTINUE_OBSERVATION
    assert result.focus_states[0].entry_date == date(2026, 7, 8)
    assert result.daily_updates[0].ts_code == "600000.SH"
    assert result.daily_updates[0].focus_entry_progress
    assert result.daily_updates[0].invalidation_conditions
