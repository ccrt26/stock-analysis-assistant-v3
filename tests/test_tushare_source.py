from datetime import date

import pandas as pd
import pytest

from stock_analyzer.data.models import SourceGrade
from stock_analyzer.data.tushare_source import MissingTushareField, TushareMarketDataSource


class FakeTusharePro:
    def stock_basic(self, **kwargs):
        return pd.DataFrame(
            [{"ts_code": "600000.SH", "name": "浦发银行", "exchange": "SSE", "list_date": "19991110"}]
        )

    def trade_cal(self, **kwargs):
        return pd.DataFrame(
            [{"cal_date": "20260708", "is_open": 1}, {"cal_date": "20260709", "is_open": 0}]
        )

    def daily(self, **kwargs):
        return pd.DataFrame(
            [{
                "ts_code": "600000.SH",
                "trade_date": "20260708",
                "open": 10.0,
                "high": 10.5,
                "low": 9.9,
                "close": 10.2,
                "pre_close": 10.0,
                "pct_chg": 2.0,
                "vol": 100000.0,
                "amount": 102000.0,
            }]
        )

    def daily_basic(self, **kwargs):
        return pd.DataFrame(
            [{
                "ts_code": "600000.SH",
                "trade_date": "20260708",
                "turnover_rate": 1.1,
                "total_mv": 1000000.0,
                "circ_mv": 900000.0,
                "pe_ttm": 6.5,
                "pb": 0.7,
            }]
        )


def test_tushare_maps_stock_daily_and_basic_rows():
    source = TushareMarketDataSource(token="secret", pro=FakeTusharePro())

    stock = source.fetch_stock_basic()[0]
    daily = source.fetch_daily(date(2026, 7, 8))[0]
    daily_basic = source.fetch_daily_basic(date(2026, 7, 8))[0]

    assert stock.ts_code == "600000.SH"
    assert stock.list_date == date(1999, 11, 10)
    assert daily.trade_date == date(2026, 7, 8)
    assert daily.source_name == "tushare"
    assert daily.source_grade == SourceGrade.PRIMARY
    assert daily_basic.turnover_rate == 1.1


def test_tushare_missing_required_field_fails_clearly():
    class BadPro(FakeTusharePro):
        def daily(self, **kwargs):
            return pd.DataFrame([{"ts_code": "600000.SH", "trade_date": "20260708"}])

    source = TushareMarketDataSource(token="secret", pro=BadPro())

    with pytest.raises(MissingTushareField) as excinfo:
        source.fetch_daily(date(2026, 7, 8))

    assert "close" in str(excinfo.value)
    assert "secret" not in str(excinfo.value)
