from datetime import date

from stock_analyzer.data.cache import CachePolicy
from stock_analyzer.data.free_sources import LiveBackupDailySource, LiveBackupSource
from stock_analyzer.data.models import DailyBar, SourceGrade


class FakeBackupClient:
    def fetch_rows(self, trade_date):
        return [
            {
                "ts_code": "600000.SH",
                "close": 10.2,
                "amount": 102000.0,
                "vol": 100000.0,
            }
        ]


def test_cache_allows_past_window_but_forbids_current_decision():
    policy = CachePolicy()

    assert policy.can_use_for_historical_window(date(2026, 7, 7), date(2026, 7, 8)) is True
    assert policy.can_use_for_current_decision(date(2026, 7, 8), date(2026, 7, 8)) is False


def test_live_backup_daily_source_marks_rows_as_live_backup():
    source = LiveBackupDailySource(name="akshare", client=FakeBackupClient())

    rows = source.fetch_daily(date(2026, 7, 8))

    assert rows == [
        DailyBar(
            trade_date=date(2026, 7, 8),
            ts_code="600000.SH",
            close=10.2,
            vol=100000.0,
            amount=102000.0,
            source_name="akshare",
            source_grade=SourceGrade.LIVE_BACKUP,
        )
    ]


def test_live_backup_source_alias_matches_daily_source():
    assert LiveBackupSource is LiveBackupDailySource
