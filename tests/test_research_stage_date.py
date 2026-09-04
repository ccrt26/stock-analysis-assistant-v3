from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

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
    after = datetime(2026, 7, 14, 17, 30, tzinfo=ZoneInfo("Asia/Shanghai"))

    assert _resolve_research_stage_date(CalendarClient(), "close", before) is None
    assert _resolve_research_stage_date(CalendarClient(), "close", after) == date(
        2026, 7, 14
    )


def test_pre_research_uses_latest_closed_day_before_tomorrow():
    now = datetime(2026, 7, 13, 18, 30, tzinfo=ZoneInfo("Asia/Shanghai"))

    assert _resolve_research_stage_date(
        CalendarClient(), "pre-research", now
    ) == date(2026, 7, 13)


class WeekendCalendar:
    def fetch_trade_calendar(self, start, through):
        return pd.DataFrame({
            "cal_date": [date(2026, 9, day) for day in range(4, 8)],
            "is_open": [True, False, False, True],
        })


def test_sunday_pre_research_and_evening_use_friday_prices():
    now = datetime(2026, 9, 6, 18, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    for stage in ("pre-research", "evening"):
        assert _resolve_research_stage_date(WeekendCalendar(), stage, now) == date(2026, 9, 4)
    assert _resolve_research_stage_date(WeekendCalendar(), "close", now) is None


def test_friday_before_non_trading_day_skips_pre_research():
    now = datetime(2026, 9, 4, 18, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    assert _resolve_research_stage_date(WeekendCalendar(), "pre-research", now) is None


def test_missing_calendar_is_not_assumed_a_closed_day():
    class MissingCalendar:
        def fetch_trade_calendar(self, start, through):
            return pd.DataFrame({"cal_date": [date(2026, 9, 3)], "is_open": [True]})
    with pytest.raises(Exception):
        _resolve_research_stage_date(MissingCalendar(), "close",
            datetime(2026, 9, 4, 17, 30, tzinfo=ZoneInfo("Asia/Shanghai")))


@pytest.mark.parametrize("at,expected", [
    ("2026-09-04T18:00:00+08:00", date(2026, 9, 4)),
    ("2026-09-05T18:00:00+08:00", None),
    ("2026-09-05T21:30:00+08:00", None),
    ("2026-09-06T18:00:00+08:00", date(2026, 9, 4)),
    ("2026-09-06T21:30:00+08:00", date(2026, 9, 4)),
    ("2026-10-03T18:00:00+08:00", None),
    ("2026-10-03T21:30:00+08:00", None),
    ("2026-10-08T18:00:00+08:00", date(2026, 9, 30)),
    ("2026-10-08T21:30:00+08:00", date(2026, 9, 30)),
])
def test_evening_runs_only_when_today_or_tomorrow_trades(at, expected):
    class Calendar:
        def fetch_trade_calendar(self, start, through):
            days = list(pd.date_range(start, through).date)
            open_days = {date(2026, 9, 4), date(2026, 9, 7),
                         date(2026, 9, 30), date(2026, 10, 9)}
            return pd.DataFrame({"cal_date": days, "is_open": [day in open_days for day in days]})
    assert _resolve_research_stage_date(Calendar(), "evening", datetime.fromisoformat(at)) == expected


@pytest.mark.parametrize("missing_day", [date(2026, 9, 5), date(2026, 9, 6)])
def test_evening_missing_required_calendar_is_not_a_no_action_day(missing_day):
    class Calendar(WeekendCalendar):
        def fetch_trade_calendar(self, start, through):
            frame = super().fetch_trade_calendar(start, through)
            return frame.loc[frame["cal_date"] != missing_day]
    with pytest.raises(Exception):
        _resolve_research_stage_date(Calendar(), "evening",
            datetime.fromisoformat("2026-09-05T18:00:00+08:00"))
