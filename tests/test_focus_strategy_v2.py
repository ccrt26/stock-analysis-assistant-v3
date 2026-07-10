from datetime import date, timedelta

from stock_analyzer.analysis.focus import update_focus_watchlist_v2
from stock_analyzer.analysis.strategy_v2 import generate_strategy_v2_recommendations
from stock_analyzer.domain.models import FocusSource
from tests.test_strategy_v2_recommendation import _feature


def _snapshot(trade_date: date, code: str = "600000.SH"):
    return generate_strategy_v2_recommendations(
        features=[_feature(code)],
        stock_names={code: "浦发银行"},
        trade_date=trade_date,
    ).snapshots[0]


def _supporting_history(code: str, start: date = date(2026, 7, 6)):
    return [_snapshot(start + timedelta(days=offset), code) for offset in range(5)]


def test_system_focus_enters_after_three_supporting_days_in_last_five():
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


def test_system_focus_requires_three_supporting_days_in_last_five():
    start = date(2026, 7, 6)
    history = [
        _snapshot(start, "600000.SH"),
        _snapshot(start + timedelta(days=1), "600000.SH"),
    ]

    result = update_focus_watchlist_v2(
        existing=[],
        recommendation_snapshots=history,
        manual_entries=[],
        trade_date=date(2026, 7, 10),
    )

    assert result.focus_states == []
    assert result.entry_theses == []


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
