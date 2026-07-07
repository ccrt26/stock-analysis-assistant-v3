from datetime import date

from stock_analyzer.analysis.focus import update_focus_watchlist
from stock_analyzer.domain.models import ActionLabel, FocusState, Recommendation


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
