from datetime import date, timedelta

import pytest

from stock_analyzer.data.feature_builder import (
    InsufficientFeatureCoverage,
    build_market_bundle,
)
from stock_analyzer.data.models import (
    DailyBar,
    DailyBasicRow,
    DataStatus,
    SourceGrade,
    StockBasicRow,
)


def _bars(ts_code="600000.SH"):
    start = date(2026, 4, 1)
    return [
        DailyBar(
            trade_date=start + timedelta(days=i),
            ts_code=ts_code,
            close=10.0 + i * 0.1,
            amount=100000000.0 + i,
            source_name="tushare",
            source_grade=SourceGrade.PRIMARY,
        )
        for i in range(70)
    ]


def test_build_market_bundle_creates_stock_and_feature_profiles():
    trade_date = date(2026, 6, 9)
    bundle = build_market_bundle(
        trade_date=trade_date,
        stock_basic=[
            StockBasicRow(
                ts_code="600000.SH",
                name="浦发银行",
                exchange="SSE",
                list_date=date(1999, 11, 10),
            )
        ],
        daily_bars=_bars(),
        daily_basic=[
            DailyBasicRow(
                trade_date=trade_date,
                ts_code="600000.SH",
                turnover_rate=1.2,
                total_mv=1000000,
                source_name="tushare",
                source_grade=SourceGrade.PRIMARY,
            )
        ],
        data_status=DataStatus.COMPLETE_PRIMARY,
        source_grade=SourceGrade.PRIMARY,
        source_versions={"tushare": "daily:2026-06-09"},
        source_runs=[],
    )

    stocks, stock_names, features = bundle.to_pipeline_inputs()

    assert stocks[0].ts_code == "600000.SH"
    assert stocks[0].listing_days > 120
    assert stock_names["600000.SH"] == "浦发银行"
    assert features["600000.SH"].trend_20d > 0
    assert features["600000.SH"].trend_60d > 0
    assert features["600000.SH"].data_quality == "ok"


def test_current_trade_date_bar_is_required_for_decisions():
    with pytest.raises(InsufficientFeatureCoverage) as excinfo:
        build_market_bundle(
            trade_date=date(2026, 7, 8),
            stock_basic=[
                StockBasicRow(ts_code="600000.SH", name="浦发银行", exchange="SSE")
            ],
            daily_bars=_bars(),
            daily_basic=[],
            data_status=DataStatus.COMPLETE_PRIMARY,
            source_grade=SourceGrade.PRIMARY,
            source_versions={"tushare": "daily:2026-07-07"},
            source_runs=[],
        )

    assert "current trade date" in str(excinfo.value)
