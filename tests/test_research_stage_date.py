from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd

from stock_analyzer.cli import _resolve_research_stage_date


class CalendarClient:
    def fetch_trade_calendar(self, start, through):
        return pd.DataFrame({
            "cal_date": [date(2026, 7, 13), date(2026, 7, 14)],
            "is_open": [True, True],
        })


def test_delayed_evening_stage_after_midnight_uses_previous_trading_day():
    now = datetime(2026, 7, 14, 0, 30, tzinfo=ZoneInfo("Asia/Shanghai"))

    assert _resolve_research_stage_date(CalendarClient(), "evening", now) == date(
        2026, 7, 13
    )


def test_close_stage_uses_today_only_after_its_expected_cutoff():
    before = datetime(2026, 7, 14, 17, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    after = datetime(2026, 7, 14, 18, 31, tzinfo=ZoneInfo("Asia/Shanghai"))

    assert _resolve_research_stage_date(CalendarClient(), "close", before) == date(
        2026, 7, 13
    )
    assert _resolve_research_stage_date(CalendarClient(), "close", after) == date(
        2026, 7, 14
    )


def test_next_morning_never_selects_the_current_trading_day():
    now = datetime(2026, 7, 14, 8, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

    assert _resolve_research_stage_date(
        CalendarClient(), "next-morning", now
    ) == date(2026, 7, 13)
