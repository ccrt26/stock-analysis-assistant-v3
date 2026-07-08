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


def _stock_rows(count):
    return [
        StockBasicRow(
            ts_code=f"600{i:03d}.SH",
            name=f"股票{i}",
            exchange="SSE",
            list_date=date(2000, 1, 1),
        )
        for i in range(count)
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


def test_current_trade_date_bar_is_required_for_each_requested_stock():
    trade_date = date(2026, 6, 9)
    current_bars = _bars("600000.SH")
    stale_bars = _bars("000001.SZ")[:-1]

    with pytest.raises(InsufficientFeatureCoverage) as excinfo:
        build_market_bundle(
            trade_date=trade_date,
            stock_basic=[
                StockBasicRow(ts_code="600000.SH", name="浦发银行", exchange="SSE"),
                StockBasicRow(ts_code="000001.SZ", name="平安银行", exchange="SZSE"),
            ],
            daily_bars=current_bars + stale_bars,
            daily_basic=[],
            data_status=DataStatus.COMPLETE_PRIMARY,
            source_grade=SourceGrade.PRIMARY,
            source_versions={"tushare": "daily:2026-06-09"},
            source_runs=[],
        )

    assert "000001.SZ" in str(excinfo.value)
    assert "current trade date" in str(excinfo.value)


def test_sparse_missing_current_bars_are_excluded_when_market_coverage_is_high():
    trade_date = date(2026, 6, 9)
    stocks = _stock_rows(20)
    traded_stocks = stocks[:-1]

    bundle = build_market_bundle(
        trade_date=trade_date,
        stock_basic=stocks,
        daily_bars=[
            bar for stock in traded_stocks for bar in _bars(stock.ts_code)
        ],
        daily_basic=[
            DailyBasicRow(
                trade_date=trade_date,
                ts_code=stock.ts_code,
                turnover_rate=1.2,
                total_mv=1000000,
                source_name="tushare",
                source_grade=SourceGrade.PRIMARY,
            )
            for stock in traded_stocks
        ],
        data_status=DataStatus.COMPLETE_PRIMARY,
        source_grade=SourceGrade.PRIMARY,
        source_versions={"tushare": "daily:2026-06-09"},
        source_runs=[],
    )

    stock_snapshots, _, features = bundle.to_pipeline_inputs()

    assert stocks[-1].ts_code not in {stock.ts_code for stock in stock_snapshots}
    assert stocks[-1].ts_code not in features
    assert len(stock_snapshots) == 19
    assert all(feature.data_quality == "ok" for feature in features.values())


def test_later_dated_bars_do_not_influence_current_trade_date_features():
    trade_date = date(2026, 6, 9)
    bars = _bars()
    current_amount = bars[-1].amount
    bars.append(
        DailyBar(
            trade_date=date(2026, 6, 10),
            ts_code="600000.SH",
            close=1.0,
            amount=999999999.0,
            source_name="tushare",
            source_grade=SourceGrade.PRIMARY,
        )
    )

    bundle = build_market_bundle(
        trade_date=trade_date,
        stock_basic=[StockBasicRow(ts_code="600000.SH", name="浦发银行", exchange="SSE")],
        daily_bars=bars,
        daily_basic=[],
        data_status=DataStatus.COMPLETE_PRIMARY,
        source_grade=SourceGrade.PRIMARY,
        source_versions={"tushare": "daily:2026-06-09"},
        source_runs=[],
    )

    stocks, _, features = bundle.to_pipeline_inputs()

    assert stocks[0].amount == current_amount
    assert features["600000.SH"].trend_20d > 0
