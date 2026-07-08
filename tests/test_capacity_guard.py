from datetime import date

import pytest

from stock_analyzer.data.models import DailyBar, SourceGrade
from stock_analyzer.storage.capacity_guard import (
    SupabaseCapacityGuard,
    SupabaseCapacityLimitExceeded,
    SupabaseWriteScopeError,
    ensure_selected_market_window_scope,
)


class FakeRpcResult:
    def __init__(self, data):
        self.data = data


class FakeCapacityClient:
    def __init__(self, size_mb):
        self.size_mb = size_mb

    def rpc(self, name):
        assert name == "database_size_mb"
        return self

    def execute(self):
        return FakeRpcResult(self.size_mb)


def _bar(ts_code):
    return DailyBar(
        trade_date=date(2026, 7, 8),
        ts_code=ts_code,
        close=10.0,
        source_name="tushare",
        source_grade=SourceGrade.PRIMARY,
    )


def test_capacity_guard_allows_normal_size_and_flags_warning():
    normal = SupabaseCapacityGuard(FakeCapacityClient(349), warn_mb=350, stop_mb=400).check()
    warning = SupabaseCapacityGuard(FakeCapacityClient(350), warn_mb=350, stop_mb=400).check()

    assert normal.warn is False
    assert normal.stop_large_writes is False
    assert warning.warn is True
    assert warning.stop_large_writes is False


def test_capacity_guard_stops_large_writes_at_stop_threshold():
    guard = SupabaseCapacityGuard(FakeCapacityClient(400), warn_mb=350, stop_mb=400)

    with pytest.raises(SupabaseCapacityLimitExceeded):
        guard.ensure_large_writes_allowed()


def test_selected_market_window_scope_rejects_full_market_shape():
    rows = [_bar(f"600{i:03d}.SH") for i in range(41)]

    with pytest.raises(SupabaseWriteScopeError):
        ensure_selected_market_window_scope(rows)


def test_selected_market_window_scope_rejects_more_than_5000_rows():
    rows = [_bar(f"600{i % 40:03d}.SH") for i in range(5001)]

    with pytest.raises(SupabaseWriteScopeError):
        ensure_selected_market_window_scope(rows)
