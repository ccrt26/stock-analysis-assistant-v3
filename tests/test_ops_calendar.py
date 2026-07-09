from datetime import date

from stock_analyzer.ops.calendar import decide_trading_day


class FakeCalendarRepository:
    def __init__(self, rows=None):
        self.rows = dict(rows or {})
        self.load_calls = []
        self.saved_rows = []

    def load_market_calendar_day(self, trade_date):
        self.load_calls.append(trade_date)
        return self.rows.get(trade_date)

    def save_market_calendar_day(self, trade_date, is_trading_day, market="CN_A"):
        self.saved_rows.append((trade_date, is_trading_day, market))
        self.rows[trade_date] = is_trading_day


class FakeTushareCalendarLoader:
    def __init__(self, calendar=None, error=None):
        self.calendar = dict(calendar or {})
        self.error = error
        self.calls = []

    def fetch_trade_calendar(self, start_date, end_date):
        self.calls.append((start_date, end_date))
        if self.error is not None:
            raise self.error
        return dict(self.calendar)


def test_supabase_calendar_trading_day_wins_without_tushare():
    trade_date = date(2026, 7, 8)
    repository = FakeCalendarRepository({trade_date: True})
    tushare_loader = FakeTushareCalendarLoader({trade_date: False})

    decision = decide_trading_day(trade_date, repository, tushare_loader)

    assert decision.status == "trading_day"
    assert decision.source == "supabase"
    assert repository.load_calls == [trade_date]
    assert repository.saved_rows == []
    assert tushare_loader.calls == []


def test_supabase_calendar_non_trading_day_wins_without_tushare():
    trade_date = date(2026, 7, 9)
    repository = FakeCalendarRepository({trade_date: False})
    tushare_loader = FakeTushareCalendarLoader({trade_date: True})

    decision = decide_trading_day(trade_date, repository, tushare_loader)

    assert decision.status == "non_trading_day"
    assert decision.source == "supabase"
    assert repository.load_calls == [trade_date]
    assert repository.saved_rows == []
    assert tushare_loader.calls == []


def test_missing_supabase_calendar_uses_tushare_and_writes_back():
    trade_date = date(2026, 7, 8)
    repository = FakeCalendarRepository()
    tushare_loader = FakeTushareCalendarLoader({trade_date: True})

    decision = decide_trading_day(trade_date, repository, tushare_loader)

    assert decision.status == "trading_day"
    assert decision.source == "tushare"
    assert tushare_loader.calls == [(trade_date, trade_date)]
    assert repository.saved_rows == [(trade_date, True, "CN_A")]


def test_missing_supabase_calendar_and_tushare_failure_returns_unknown():
    trade_date = date(2026, 7, 9)
    repository = FakeCalendarRepository()
    tushare_loader = FakeTushareCalendarLoader(
        error=RuntimeError("temporary Tushare failure"),
    )

    decision = decide_trading_day(trade_date, repository, tushare_loader)

    assert decision.status == "calendar_unknown"
    assert decision.source == "unknown"
    assert tushare_loader.calls == [(trade_date, trade_date)]
    assert repository.saved_rows == []
