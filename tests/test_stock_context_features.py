from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from stock_analyzer.analysis.stock_context_features import (
    STOCK_CONTEXT_FORMULA_VERSION,
    compute_stock_context_features,
)


ANALYSIS_DATE = date(2026, 7, 10)


def _equity_rows(
    dates: pd.DatetimeIndex,
    closes: dict[str, list[float]],
    *,
    amounts: dict[str, list[float]] | None = None,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for code, values in closes.items():
        for offset, (trading_day, close) in enumerate(zip(dates, values, strict=True)):
            rows.append(
                {
                    "trade_date": trading_day.date(),
                    "ts_code": code,
                    "open": close,
                    "high": close + 1.0,
                    "low": close - 1.0,
                    "close": close,
                    "adj_factor": 1.0,
                    "amount": amounts[code][offset] if amounts else 100.0,
                }
            )
    return pd.DataFrame(rows)


def _benchmark(dates: pd.DatetimeIndex, closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {"trade_date": dates.date, "close": closes, "index_code": "000300.SH"}
    )


def _empty_limits() -> pd.DataFrame:
    return pd.DataFrame(
        columns=["trade_date", "ts_code", "up_limit", "down_limit"]
    )


def _empty_valuations() -> pd.DataFrame:
    return pd.DataFrame(columns=["trade_date", "ts_code", "pe_ttm", "pb"])


def _all_limits(equity: pd.DataFrame) -> pd.DataFrame:
    return equity[["trade_date", "ts_code", "close"]].assign(
        up_limit=lambda frame: frame["close"] + 100.0,
        down_limit=0.01,
    )[["trade_date", "ts_code", "up_limit", "down_limit"]]


def _current_valuations(equity: pd.DataFrame) -> pd.DataFrame:
    return equity.loc[
        equity["trade_date"] == ANALYSIS_DATE, ["trade_date", "ts_code"]
    ].assign(pe_ttm=20.0, pb=2.0)


def _compute(
    equity: pd.DataFrame,
    benchmark: pd.DataFrame,
    *,
    limits: pd.DataFrame | None = None,
    valuations: pd.DataFrame | None = None,
) -> pd.DataFrame:
    return compute_stock_context_features(
        equity,
        benchmark,
        _all_limits(equity) if limits is None else limits,
        _current_valuations(equity) if valuations is None else valuations,
        analysis_date=ANALYSIS_DATE,
    )


def test_returns_and_relative_returns_use_exact_market_sessions() -> None:
    dates = pd.bdate_range(end=ANALYSIS_DATE, periods=61)
    stock = [100.0] * 61
    stock[0], stock[40], stock[50], stock[55], stock[59], stock[60] = (
        55.0,
        100.0,
        80.0,
        100.0,
        100.0,
        110.0,
    )
    broad = [100.0] * 61
    broad[0], broad[40], broad[50], broad[55], broad[59], broad[60] = (
        80.0,
        100.0,
        100.0,
        100.0,
        100.0,
        105.0,
    )

    row = _compute(
        _equity_rows(dates, {"A.SZ": stock}), _benchmark(dates, broad)
    ).iloc[0]

    expected_stock = {1: 0.10, 5: 0.10, 10: 0.375, 20: 0.10, 60: 1.0}
    expected_broad = {1: 0.05, 5: 0.05, 10: 0.05, 20: 0.05, 60: 0.3125}
    assert row["formula_version"] == STOCK_CONTEXT_FORMULA_VERSION
    assert row["analysis_date"] == ANALYSIS_DATE
    for horizon in (1, 5, 10, 20, 60):
        assert row[f"return_{horizon}d"] == pytest.approx(expected_stock[horizon])
        assert row[f"relative_return_{horizon}d"] == pytest.approx(
            expected_stock[horizon] - expected_broad[horizon]
        )

    missing_session = _equity_rows(dates, {"A.SZ": stock})
    missing_session.loc[
        missing_session["trade_date"] == dates[-6].date(), "close"
    ] = np.nan
    missing_row = _compute(missing_session, _benchmark(dates, broad)).iloc[0]
    assert np.isnan(missing_row["return_5d"])


def test_stock_returns_and_cross_day_risk_use_adjusted_prices() -> None:
    dates = pd.bdate_range(end=ANALYSIS_DATE, periods=2)
    equity = _equity_rows(dates, {"A.SZ": [10.0, 5.0]})
    equity.loc[:, "adj_factor"] = [1.0, 2.0]

    row = _compute(equity, _benchmark(dates, [100.0, 100.0])).iloc[0]

    assert row["return_1d"] == pytest.approx(0.0)
    assert row["relative_return_1d"] == pytest.approx(0.0)
    assert row["equity_return_price_basis"] == "close_times_adj_factor"


def test_post_limit_return_is_limited_when_adjustment_factor_is_missing() -> None:
    dates = pd.bdate_range(end=ANALYSIS_DATE, periods=3)
    equity = _equity_rows(dates, {"A.SZ": [10.0, 11.0, 10.5]})
    equity.loc[equity["trade_date"] == dates[-2].date(), "adj_factor"] = np.nan
    limits = _all_limits(equity)
    limits.loc[limits["trade_date"] == dates[-2].date(), "up_limit"] = 11.0

    row = _compute(
        equity,
        _benchmark(dates, [100.0, 100.0, 100.0]),
        limits=limits,
    ).iloc[0]

    assert row["latest_limit_up_date"] == dates[-2].date()
    assert row["post_limit_behavior_status"] == "limited"
    assert np.isnan(row["post_limit_next_return"])


def test_beta_correlation_volatility_and_atr_are_hand_calculated() -> None:
    dates = pd.bdate_range(end=ANALYSIS_DATE, periods=61)
    benchmark_returns = np.array(
        [0.01 if i % 2 == 0 else -(0.005 + 0.001 * (i % 5)) for i in range(60)]
    )
    stock_returns = 2.0 * benchmark_returns
    broad = [100.0]
    stock = [50.0]
    for broad_return, stock_return in zip(
        benchmark_returns, stock_returns, strict=True
    ):
        broad.append(broad[-1] * (1.0 + broad_return))
        stock.append(stock[-1] * (1.0 + stock_return))
    equity = _equity_rows(dates, {"A.SZ": stock})
    equity["open"] = equity["close"] * 0.995
    equity["high"] = equity["close"] * 1.01
    equity["low"] = equity["close"] * 0.99

    row = _compute(equity, _benchmark(dates, broad)).iloc[0]

    assert row["beta_60d"] == pytest.approx(2.0)
    assert row["downside_beta_60d"] == pytest.approx(2.0)
    assert row["benchmark_correlation_60d"] == pytest.approx(1.0)
    assert row["risk_observation_count_60d"] == 60
    assert row["downside_risk_observation_count_60d"] == 30
    assert row["risk_status"] == "complete"
    assert row["realized_volatility_20d_annualized"] == pytest.approx(
        pd.Series(stock_returns[-20:]).std(ddof=1) * np.sqrt(252.0)
    )
    previous_close = equity["close"].shift(1)
    true_range = pd.concat(
        [
            equity["high"] - equity["low"],
            (equity["high"] - previous_close).abs(),
            (equity["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    expected_atr_ratio = true_range.tail(20).mean() / equity.iloc[-1]["close"]
    assert row["atr_ratio_20d"] == pytest.approx(expected_atr_ratio)


def test_price_location_amount_ratios_and_high_volume_extreme_remain_visible() -> None:
    dates = pd.bdate_range(end=ANALYSIS_DATE, periods=82)
    closes = np.arange(1.0, 83.0).tolist()
    amounts = [100.0] * 81 + [200.0]
    equity = _equity_rows(dates, {"A.SZ": closes}, amounts={"A.SZ": amounts})

    row = _compute(equity, _benchmark(dates, [100.0] * 82)).iloc[0]

    assert row["price_location_60d"] == pytest.approx(1.0)
    assert row["price_location_82d"] == pytest.approx(1.0)
    assert row["average_amount_20d"] == pytest.approx(105.0)
    assert row["current_amount_ratio_20d"] == pytest.approx(200.0 / 105.0)

    short_dates = pd.bdate_range(end=ANALYSIS_DATE, periods=10)
    short_closes = [10.0, 11.0, 10.0, 11.0, 10.0, 11.0, 10.0, 10.0, 20.0, 15.0]
    short_amounts = [1.0] * 8 + [100.0, 90.0]
    high_volume = _equity_rows(
        short_dates,
        {"A.SZ": short_closes},
        amounts={"A.SZ": short_amounts},
    )
    high_volume.loc[high_volume.index[-2], ["open", "high", "low", "close"]] = [
        15.0,
        25.0,
        15.0,
        20.0,
    ]
    high_volume.loc[high_volume.index[-1], ["open", "high", "low", "close"]] = [
        15.1,
        20.0,
        10.0,
        15.0,
    ]
    high_row = _compute(
        high_volume, _benchmark(short_dates, [100.0] * 10)
    ).iloc[0]

    assert high_row["high_volume_up_count_60d"] == 1
    assert high_row["high_volume_down_count_60d"] == 1
    assert high_row["high_volume_amount_observation_count_60d"] == 10
    assert high_row["high_volume_selected_count_60d"] == 2
    assert high_row["high_volume_status"] == "limited"
    assert high_row["high_volume_body_efficiency_median_60d"] == pytest.approx(0.255)
    assert high_row["high_volume_body_efficiency_min_60d"] == pytest.approx(0.01)
    assert high_row["high_volume_body_efficiency_min_date_60d"] == ANALYSIS_DATE


def test_amount_direction_and_countertrend_weights_ignore_future_rows() -> None:
    dates = pd.bdate_range(end=ANALYSIS_DATE, periods=8)
    broad_returns = [0.01, -0.01, 0.01, -0.02, 0.01, -0.01, 0.01]
    stock_returns = [-0.01, 0.02, -0.01, 0.03, -0.01, -0.02, 0.01]
    broad = [100.0]
    stock = [100.0]
    for broad_return, stock_return in zip(broad_returns, stock_returns, strict=True):
        broad.append(broad[-1] * (1 + broad_return))
        stock.append(stock[-1] * (1 + stock_return))
    amounts = [100.0, 200.0, 100.0, 300.0, 100.0, 150.0, 100.0, 250.0]
    equity = _equity_rows(
        dates, {"A.SZ": stock}, amounts={"A.SZ": amounts}
    )
    benchmark = _benchmark(dates, broad)
    future_date = pd.Timestamp("2026-07-13")
    future_equity = _equity_rows(
        pd.DatetimeIndex([future_date]),
        {"A.SZ": [stock[-1] * 2]},
        amounts={"A.SZ": [10_000.0]},
    )
    future_benchmark = _benchmark(
        pd.DatetimeIndex([future_date]), [broad[-1] * 0.5]
    )

    row = _compute(
        pd.concat([equity, future_equity], ignore_index=True),
        pd.concat([benchmark, future_benchmark], ignore_index=True),
    ).iloc[0]

    up_amounts = np.array([100.0, 100.0, 250.0])
    down_amounts = np.array([200.0, 300.0, 150.0, 100.0])
    assert row["up_down_amount_ratio_60d"] == pytest.approx(
        up_amounts.mean() / down_amounts.mean()
    )
    assert row["amount_direction_observation_count_60d"] == 7
    assert row["amount_up_observation_count_60d"] == 3
    assert row["amount_down_observation_count_60d"] == 4
    assert row["amount_direction_status"] == "limited"
    assert row["countertrend_up_count_60d"] == 2
    assert row["countertrend_observation_count_60d"] == 7
    assert row["countertrend_status"] == "limited"
    expected_weight = 0.5 ** (5 / 20) + 0.5 ** (3 / 20)
    assert row["countertrend_up_recency_weighted_60d"] == pytest.approx(
        expected_weight
    )
    assert row["return_1d"] == pytest.approx(0.01)


def test_recent_limit_hits_and_post_limit_behavior_use_supplied_limit_prices() -> None:
    dates = pd.bdate_range(end=ANALYSIS_DATE, periods=6)
    equity = _equity_rows(
        dates,
        {
            "A.SZ": [10.0, 10.0, 10.0, 11.0, 10.45, 10.60],
            "B.SZ": [10.0, 10.0, 10.0, 11.0, 11.10, 11.20],
        },
        amounts={
            "A.SZ": [100.0, 100.0, 100.0, 500.0, 250.0, 200.0],
            "B.SZ": [100.0] * 6,
        },
    )
    equity.loc[
        (equity["ts_code"] == "A.SZ")
        & (equity["trade_date"] == dates[-2].date()),
        ["high", "low"],
    ] = [11.0, 10.2]
    limits = _all_limits(equity)
    limits.loc[limits["ts_code"] == "A.SZ", "up_limit"] = [
        11.0,
        11.0,
        11.0,
        11.0,
        12.1,
        11.5,
    ]
    limits.loc[limits["ts_code"] == "B.SZ", "up_limit"] = 12.0

    result = _compute(
        equity, _benchmark(dates, [100.0] * 6), limits=limits
    ).set_index("ts_code")

    a = result.loc["A.SZ"]
    b = result.loc["B.SZ"]
    assert a["recent_limit_up_count_5d"] == 1
    assert a["latest_limit_up_date"] == dates[-3].date()
    assert a["post_limit_next_return"] == pytest.approx(10.45 / 11.0 - 1.0)
    assert a["post_limit_next_amount_ratio"] == pytest.approx(250.0 / 500.0)
    assert a["post_limit_next_high_to_close_pullback"] == pytest.approx(
        11.0 / 10.45 - 1.0
    )
    assert a["post_limit_behavior_status"] == "complete"
    assert b["recent_limit_up_count_5d"] == 0
    assert pd.isna(b["latest_limit_up_date"])
    assert b["post_limit_behavior_status"] == "not_applicable"


def test_current_limit_hit_is_pending_and_incomplete_next_day_is_limited() -> None:
    dates = pd.bdate_range(end=ANALYSIS_DATE, periods=6)
    current_hit = _equity_rows(dates, {"NOW.SZ": [10.0] * 5 + [11.0]})
    current_limits = _all_limits(current_hit)
    current_limits.loc[
        current_limits["trade_date"] == ANALYSIS_DATE, "up_limit"
    ] = 11.0
    current_row = _compute(
        current_hit,
        _benchmark(dates, [100.0] * 6),
        limits=current_limits,
    ).iloc[0]
    assert current_row["post_limit_behavior_status"] == "pending"

    prior_hit = _equity_rows(dates, {"OLD.SZ": [10.0, 10.0, 10.0, 11.0, 10.5, 10.6]})
    prior_hit.loc[prior_hit["trade_date"] == dates[-2].date(), "amount"] = np.nan
    prior_limits = _all_limits(prior_hit)
    prior_limits.loc[
        prior_limits["trade_date"] == dates[-3].date(), "up_limit"
    ] = 11.0
    prior_row = _compute(
        prior_hit,
        _benchmark(dates, [100.0] * 6),
        limits=prior_limits,
    ).iloc[0]
    assert prior_row["post_limit_behavior_status"] == "limited"
    assert "post-limit" in prior_row["limitation_notes"]


def test_missing_limit_history_is_not_reported_as_zero_hits() -> None:
    dates = pd.bdate_range(end=ANALYSIS_DATE, periods=6)
    equity = _equity_rows(dates, {"A.SZ": [10.0] * 6})
    limits = _all_limits(equity).iloc[:-1].copy()

    row = _compute(
        equity, _benchmark(dates, [100.0] * 6), limits=limits
    ).iloc[0]

    assert row["limit_data_status"] == "limited"
    assert np.isnan(row["recent_limit_up_count_5d"])
    assert row["coverage_status"] == "limited"


def test_valuation_percentiles_and_non_positive_pe_are_explicit() -> None:
    dates = pd.bdate_range(end=ANALYSIS_DATE, periods=300)
    equity = _equity_rows(dates[-2:], {"POS.SZ": [10.0, 10.0], "NEG.SZ": [8.0, 8.0]})
    valuation_rows: list[dict[str, object]] = []
    for offset, trading_day in enumerate(dates, start=1):
        valuation_rows.extend(
            [
                {
                    "trade_date": trading_day.date(),
                    "ts_code": "POS.SZ",
                    "pe_ttm": 150.0 if trading_day == dates[-1] else float(offset),
                    "pb": 100.0 if trading_day == dates[-1] else float(offset),
                },
                {
                    "trade_date": trading_day.date(),
                    "ts_code": "NEG.SZ",
                    "pe_ttm": -5.0 if trading_day == dates[-1] else float(offset),
                    "pb": 2.0,
                },
            ]
        )

    result = _compute(
        equity,
        _benchmark(dates, [100.0] * len(dates)),
        valuations=pd.DataFrame(valuation_rows),
    ).set_index("ts_code")

    pos = result.loc["POS.SZ"]
    assert pos["pe_ttm"] == pytest.approx(150.0)
    assert pos["pb"] == pytest.approx(100.0)
    assert pos["pe_ttm_percentile_250d"] == pytest.approx(101 / 250)
    assert pos["pb_percentile_250d"] == pytest.approx(51 / 250)
    assert pos["pe_ttm_percentile_5y_available"] == pytest.approx(151 / 300)
    assert pos["pb_percentile_5y_available"] == pytest.approx(101 / 300)
    assert pos["valuation_observations_250d"] == 250
    assert pos["valuation_observations_5y"] == 300
    neg = result.loc["NEG.SZ"]
    assert neg["pe_ttm"] == pytest.approx(-5.0)
    assert np.isnan(neg["pe_ttm_percentile_250d"])
    assert np.isnan(neg["pe_ttm_percentile_5y_available"])
    assert neg["pe_percentile_status"] == "unavailable_non_positive"
    assert "non-positive PE" in neg["limitation_notes"]


def test_250_session_valuation_window_never_backfills_a_missing_day_with_old_data() -> None:
    dates = pd.bdate_range(end=ANALYSIS_DATE, periods=260)
    equity = _equity_rows(dates[-82:], {"A.SZ": np.arange(1.0, 83.0).tolist()})
    rows: list[dict[str, object]] = []
    missing_inside_window = dates[20].date()
    for trading_day in dates:
        if trading_day.date() == missing_inside_window:
            continue
        outside_window = trading_day < dates[10]
        rows.append(
            {
                "trade_date": trading_day.date(),
                "ts_code": "A.SZ",
                "pe_ttm": (
                    50.0
                    if trading_day == dates[-1]
                    else 1.0
                    if outside_window
                    else 100.0
                ),
                "pb": (
                    5.0
                    if trading_day == dates[-1]
                    else 1.0
                    if outside_window
                    else 10.0
                ),
            }
        )
    benchmark = _benchmark(dates, np.linspace(100.0, 200.0, len(dates)).tolist())

    row = _compute(equity, benchmark, valuations=pd.DataFrame(rows)).iloc[0]

    assert row["valuation_observations_250d"] == 249
    assert row["pe_ttm_percentile_250d"] == pytest.approx(1 / 249)
    assert row["pb_percentile_250d"] == pytest.approx(1 / 249)
    assert row["valuation_data_status"] == "limited"
    assert "249/250" in row["limitation_notes"]

    current_only = _compute(
        equity,
        benchmark,
        valuations=pd.DataFrame(
            [
                {
                    "trade_date": ANALYSIS_DATE,
                    "ts_code": "A.SZ",
                    "pe_ttm": 50.0,
                    "pb": 5.0,
                }
            ]
        ),
    ).iloc[0]
    assert current_only["valuation_observations_250d"] == 1
    assert current_only["valuation_data_status"] == "limited"


def test_short_history_keeps_available_windows_and_declares_limits() -> None:
    dates = pd.bdate_range(end=ANALYSIS_DATE, periods=6)
    equity = _equity_rows(dates, {"NEW.SZ": [10.0, 11.0, 12.0, 13.0, 14.0, 15.0]})

    row = _compute(equity, _benchmark(dates, [100.0] * 6)).iloc[0]

    assert row["available_price_sessions"] == 6
    assert row["return_5d"] == pytest.approx(0.5)
    assert np.isnan(row["return_10d"])
    assert np.isnan(row["beta_60d"])
    assert np.isnan(row["price_location_60d"])
    assert row["coverage_status"] == "limited"
    assert "short price history" in row["limitation_notes"]
    assert row["trader_identity_status"] == "unavailable"


def test_missing_current_core_or_benchmark_is_fail_closed_and_output_is_decision_free() -> None:
    dates = pd.bdate_range(end=ANALYSIS_DATE, periods=61)
    equity = _equity_rows(dates, {"A.SZ": [10.0] * 61})
    equity.loc[equity["trade_date"] == ANALYSIS_DATE, "amount"] = np.nan
    benchmark = _benchmark(dates, [100.0] * 61)
    benchmark.loc[benchmark["trade_date"] == ANALYSIS_DATE, "close"] = np.nan

    row = _compute(equity, benchmark).iloc[0]

    assert np.isnan(row["current_amount_ratio_20d"])
    assert np.isnan(row["relative_return_1d"])
    assert np.isnan(row["beta_60d"])
    assert np.isnan(row["countertrend_up_count_60d"])
    assert row["risk_status"] == "limited"
    assert row["countertrend_status"] == "limited"
    assert row["coverage_status"] == "limited"
    assert "benchmark" in row["limitation_notes"]
    rendered = " ".join(str(value) for value in row.index) + " " + " ".join(
        str(value) for value in row.dropna().tolist()
    )
    for prohibited in (
        "institution",
        "main_force",
        "recommend",
        "action",
        "ranking",
        "score",
        "机构",
        "主力",
        "买入",
        "出货",
    ):
        assert prohibited not in rendered.lower()


def test_duplicate_business_facts_fail_before_calculation() -> None:
    dates = pd.bdate_range(end=ANALYSIS_DATE, periods=2)
    equity = _equity_rows(dates, {"A.SZ": [10.0, 11.0]})
    duplicate = pd.concat([equity, equity.iloc[[-1]]], ignore_index=True)

    with pytest.raises(ValueError, match="duplicate business fact"):
        _compute(duplicate, _benchmark(dates, [100.0, 101.0]))


def test_high_volume_threshold_includes_every_observation_tied_at_quantile() -> None:
    dates = pd.bdate_range(end=ANALYSIS_DATE, periods=61)
    returns = [0.01 if offset % 2 == 0 else -0.01 for offset in range(60)]
    closes = [100.0]
    for daily_return in returns:
        closes.append(closes[-1] * (1.0 + daily_return))
    equity = _equity_rows(
        dates,
        {"TIE.SZ": closes},
        amounts={"TIE.SZ": [100.0] * 61},
    )

    row = _compute(equity, _benchmark(dates, closes)).iloc[0]

    assert row["high_volume_amount_observation_count_60d"] == 60
    assert row["high_volume_selected_count_60d"] == 60
    assert row["high_volume_status"] == "complete"


def test_complete_row_has_all_required_observations_and_declared_limitation() -> None:
    dates = pd.bdate_range(end=ANALYSIS_DATE, periods=300)
    benchmark_returns = np.array(
        [0.012 if offset % 2 == 0 else -(0.006 + 0.001 * (offset % 5)) for offset in range(299)]
    )
    stock_returns = benchmark_returns * 1.5
    broad = [100.0]
    closes = [50.0]
    for broad_return, stock_return in zip(
        benchmark_returns, stock_returns, strict=True
    ):
        broad.append(broad[-1] * (1.0 + broad_return))
        closes.append(closes[-1] * (1.0 + stock_return))
    amounts = [100.0] + [200.0 if value > 0 else 100.0 for value in stock_returns]
    equity = _equity_rows(
        dates, {"FULL.SZ": closes}, amounts={"FULL.SZ": amounts}
    )
    valuations = pd.DataFrame(
        {
            "trade_date": dates.date,
            "ts_code": "FULL.SZ",
            "pe_ttm": np.linspace(10.0, 20.0, len(dates)),
            "pb": np.linspace(1.0, 2.0, len(dates)),
        }
    )

    row = _compute(
        equity, _benchmark(dates, broad), valuations=valuations
    ).iloc[0]

    assert row["return_status"] == "complete"
    assert row["risk_status"] == "complete"
    assert row["amount_direction_status"] == "complete"
    assert row["high_volume_status"] == "complete"
    assert row["countertrend_status"] == "complete"
    assert row["valuation_data_status"] == "complete"
    assert row["post_limit_behavior_status"] == "not_applicable"
    assert row["coverage_status"] == "complete_with_declared_gaps"
    assert "trader identity" in row["limitation_notes"]


def test_full_universe_calculation_groups_each_input_once_by_stock(monkeypatch) -> None:
    dates = pd.bdate_range(end=ANALYSIS_DATE, periods=82)
    codes = [f"{value:06d}.SZ" for value in range(20)]
    closes = {
        code: (100.0 + np.arange(len(dates)) * 0.1).tolist()
        for code in codes
    }
    equity = _equity_rows(dates, closes)
    valuations = pd.DataFrame(
        [
            {
                "trade_date": trading_day.date(),
                "ts_code": code,
                "pe_ttm": 10.0 + offset / 100,
                "pb": 1.0 + offset / 1000,
            }
            for code in codes
            for offset, trading_day in enumerate(dates)
        ]
    )
    comparisons = 0
    original_eq = pd.Series.__eq__

    def count_code_comparison(series, other):
        nonlocal comparisons
        if series.name == "ts_code" and isinstance(other, str):
            comparisons += 1
        return original_eq(series, other)

    monkeypatch.setattr(pd.Series, "__eq__", count_code_comparison)

    result = _compute(
        equity,
        _benchmark(dates, (100.0 + np.arange(len(dates)) * 0.1).tolist()),
        valuations=valuations,
    )

    assert len(result) == len(codes)
    assert comparisons <= 1
