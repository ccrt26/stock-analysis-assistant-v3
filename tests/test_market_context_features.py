from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from stock_analyzer.analysis.market_context_features import (
    BROAD_INDEX_CODES,
    MARKET_CONTEXT_FORMULA_VERSION,
    compute_market_context_features,
)


ANALYSIS_DATE = date(2026, 7, 10)


def _equity_frame(
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
                    "close": close,
                    "amount": amounts[code][offset] if amounts else 100.0,
                }
            )
    return pd.DataFrame(rows)


def _empty_limits() -> pd.DataFrame:
    return pd.DataFrame(columns=["trade_date", "ts_code", "up_limit", "down_limit"])


def _index_frame(dates: pd.DatetimeIndex) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "trade_date": trading_day.date(),
                "index_code": code,
                "close": 100.0,
            }
            for code in BROAD_INDEX_CODES
            for trading_day in dates
        ]
    )


def _limits_for(equity: pd.DataFrame, *, take: int | None = None) -> pd.DataFrame:
    codes = equity.loc[equity["trade_date"] == ANALYSIS_DATE, "ts_code"].tolist()
    if take is not None:
        codes = codes[:take]
    return pd.DataFrame(
        [
            {
                "trade_date": ANALYSIS_DATE,
                "ts_code": code,
                "up_limit": 11.0,
                "down_limit": 9.0,
            }
            for code in codes
        ]
    )


def test_returns_indexes_and_turnover_are_hand_calculated() -> None:
    dates = pd.bdate_range(end=ANALYSIS_DATE, periods=21)
    closes = {code: [100.0] * 21 for code in ("A.SZ", "B.SZ", "C.SZ")}
    closes["A.SZ"][0], closes["A.SZ"][15], closes["A.SZ"][17] = 40.0, 60.0, 80.0
    closes["A.SZ"][19], closes["A.SZ"][20] = 100.0, 120.0
    closes["B.SZ"][0], closes["B.SZ"][15], closes["B.SZ"][17] = 100.0, 60.0, 90.0
    closes["B.SZ"][19], closes["B.SZ"][20] = 100.0, 90.0
    closes["C.SZ"][0], closes["C.SZ"][15], closes["C.SZ"][17] = 80.0, 200.0, 125.0
    closes["C.SZ"][19], closes["C.SZ"][20] = 100.0, 100.0
    amounts = {
        "A.SZ": [100.0] * 20 + [200.0],
        "B.SZ": [200.0] * 20 + [400.0],
        "C.SZ": [700.0] * 20 + [1_400.0],
    }
    equity = _equity_frame(dates, closes, amounts=amounts)

    index_rows: list[dict[str, object]] = []
    expected_index_returns: dict[str, dict[int, float]] = {}
    for offset, code in enumerate(BROAD_INDEX_CODES, start=1):
        values = [100.0] * 21
        values[0], values[15], values[17] = 90.0, 96.0, 98.0
        values[19], values[20] = 100.0, 100.0 + offset
        expected_index_returns[code] = {
            1: values[20] / values[19] - 1.0,
            3: values[20] / values[17] - 1.0,
            5: values[20] / values[15] - 1.0,
            20: values[20] / values[0] - 1.0,
        }
        for trading_day, close in zip(dates, values, strict=True):
            index_rows.append(
                {
                    "trade_date": trading_day.date(),
                    "index_code": code,
                    "close": close,
                }
            )

    result = compute_market_context_features(
        equity,
        pd.DataFrame(index_rows),
        _limits_for(equity),
        analysis_date=ANALYSIS_DATE,
        expected_current_rows=3,
    )

    assert len(result) == 1
    row = result.iloc[0]
    assert row["formula_version"] == MARKET_CONTEXT_FORMULA_VERSION
    assert row["analysis_date"] == ANALYSIS_DATE
    expected_market = {
        1: ((0.2 - 0.1 + 0.0) / 3, 0.0, 1 / 3),
        3: ((0.5 + 0.0 - 0.2) / 3, 0.0, 1 / 3),
        5: ((1.0 + 0.5 - 0.5) / 3, 0.5, 2 / 3),
        20: ((2.0 - 0.1 + 0.25) / 3, 0.25, 2 / 3),
    }
    for horizon, (mean, median, breadth) in expected_market.items():
        assert row[f"equal_weight_return_{horizon}d"] == pytest.approx(mean)
        assert row[f"median_return_{horizon}d"] == pytest.approx(median)
        assert row[f"breadth_{horizon}d"] == pytest.approx(breadth)

    for code, expected_by_horizon in expected_index_returns.items():
        slug = code.lower().replace(".", "_")
        for horizon, expected in expected_by_horizon.items():
            assert row[f"index_{slug}_return_{horizon}d"] == pytest.approx(expected)

    assert row["market_turnover_amount"] == pytest.approx(2_000.0)
    assert row["turnover_ratio_5d"] == pytest.approx(2_000.0 / 1_200.0)
    assert row["turnover_ratio_20d"] == pytest.approx(2_000.0 / 1_050.0)
    assert row["coverage_status"] == "complete"
    assert row["coverage_ratio"] == pytest.approx(1.0)


def test_long_window_breadth_extremes_dispersion_and_realized_volatility() -> None:
    dates = pd.bdate_range(end=ANALYSIS_DATE, periods=61)
    increasing = np.arange(1.0, 62.0)
    decreasing = increasing[::-1]
    equity = _equity_frame(
        dates,
        {"A.SZ": increasing.tolist(), "B.SZ": decreasing.tolist()},
    )

    row = compute_market_context_features(
        equity,
        pd.DataFrame(columns=["trade_date", "index_code", "close"]),
        _empty_limits(),
        analysis_date=ANALYSIS_DATE,
        expected_current_rows=2,
    ).iloc[0]

    for window in (20, 60):
        assert row[f"above_ma_{window}d_share"] == pytest.approx(0.5)
        assert row[f"new_high_{window}d_share"] == pytest.approx(0.5)
        assert row[f"new_low_{window}d_share"] == pytest.approx(0.5)

    latest_returns = np.array([61.0 / 60.0 - 1.0, 1.0 / 2.0 - 1.0])
    assert row["return_dispersion_1d"] == pytest.approx(
        np.std(latest_returns, ddof=0)
    )
    daily_market_returns = pd.DataFrame(
        {"A.SZ": increasing, "B.SZ": decreasing}, index=dates
    ).pct_change(fill_method=None).mean(axis=1).dropna().tail(20)
    expected_realized_volatility = daily_market_returns.std(ddof=1) * np.sqrt(252.0)
    assert row["realized_volatility_20d_annualized"] == pytest.approx(
        expected_realized_volatility
    )


def test_actual_limit_prices_and_incomplete_market_coverage_are_explicit() -> None:
    dates = pd.bdate_range(end=ANALYSIS_DATE, periods=2)
    equity = _equity_frame(
        dates,
        {
            "LIMIT_UP.SZ": [10.0, 11.0],
            "NEAR_UP.SZ": [10.0, 10.8],
            "LIMIT_DOWN.SZ": [10.0, 9.0],
            "NEAR_DOWN.SZ": [10.0, 9.1],
            "NORMAL.SZ": [10.0, 10.0],
        },
    )
    limits = pd.DataFrame(
        [
            {
                "trade_date": ANALYSIS_DATE,
                "ts_code": code,
                "up_limit": 11.0,
                "down_limit": 9.0,
            }
            for code in (
                "LIMIT_UP.SZ",
                "NEAR_UP.SZ",
                "LIMIT_DOWN.SZ",
                "NEAR_DOWN.SZ",
                "NORMAL.SZ",
            )
        ]
    )

    row = compute_market_context_features(
        equity,
        pd.DataFrame(columns=["trade_date", "index_code", "close"]),
        limits,
        analysis_date=ANALYSIS_DATE,
        expected_current_rows=5,
    ).iloc[0]

    assert row["observed_current_rows"] == 5
    assert row["expected_current_rows"] == 5
    assert row["coverage_ratio"] == pytest.approx(1.0)
    assert row["coverage_status"] == "limited"
    assert "broad index current coverage" in row["limitation_notes"]
    assert row["limit_observed_count"] == 5
    assert row["limit_up_count"] == 1
    assert row["near_limit_up_count"] == 1
    assert row["limit_down_count"] == 1
    assert row["near_limit_down_count"] == 1
    assert row["limit_up_share"] == pytest.approx(1 / 5)
    assert row["near_limit_up_share"] == pytest.approx(1 / 5)
    assert row["limit_down_share"] == pytest.approx(1 / 5)
    assert row["near_limit_down_share"] == pytest.approx(1 / 5)
    assert np.isnan(row["equal_weight_return_3d"])


def test_invalid_current_price_or_amount_is_not_counted_as_market_coverage() -> None:
    dates = pd.bdate_range(end=ANALYSIS_DATE, periods=2)
    equity = _equity_frame(
        dates,
        {
            "VALID.SZ": [10.0, 10.1],
            "NAN_CLOSE.SZ": [10.0, np.nan],
            "ZERO_CLOSE.SZ": [10.0, 0.0],
            "NEG_AMOUNT.SZ": [10.0, 10.1],
            "INF_AMOUNT.SZ": [10.0, 10.1],
        },
    )
    equity.loc[
        (equity["trade_date"] == ANALYSIS_DATE)
        & (equity["ts_code"] == "NEG_AMOUNT.SZ"),
        "amount",
    ] = -1.0
    equity.loc[
        (equity["trade_date"] == ANALYSIS_DATE)
        & (equity["ts_code"] == "INF_AMOUNT.SZ"),
        "amount",
    ] = np.inf

    row = compute_market_context_features(
        equity,
        _index_frame(dates),
        _limits_for(equity),
        analysis_date=ANALYSIS_DATE,
        expected_current_rows=5,
    ).iloc[0]

    assert row["observed_current_rows"] == 1
    assert row["coverage_ratio"] == pytest.approx(0.2)
    assert row["coverage_status"] == "limited"
    assert "current equity coverage" in row["limitation_notes"]
    assert np.isnan(row["market_turnover_amount"])
    assert row["limit_price_coverage_ratio"] == pytest.approx(0.2)
    assert np.isnan(row["limit_up_count"])


def test_turnover_windows_do_not_compress_across_a_missing_amount() -> None:
    dates = pd.bdate_range(end=ANALYSIS_DATE, periods=21)
    equity = _equity_frame(
        dates,
        {"A.SZ": [10.0] * 21, "B.SZ": [20.0] * 21},
    )
    equity.loc[
        (equity["trade_date"] == dates[-10].date())
        & (equity["ts_code"] == "A.SZ"),
        "amount",
    ] = np.nan

    row = compute_market_context_features(
        equity,
        _index_frame(dates),
        _limits_for(equity),
        analysis_date=ANALYSIS_DATE,
        expected_current_rows=2,
    ).iloc[0]

    assert row["market_turnover_amount"] == pytest.approx(200.0)
    assert row["turnover_ratio_5d"] == pytest.approx(1.0)
    assert np.isnan(row["turnover_ratio_20d"])


def test_index_current_and_middle_gaps_are_not_compressed() -> None:
    dates = pd.bdate_range(end=ANALYSIS_DATE, periods=21)
    equity = _equity_frame(dates, {"A.SZ": [10.0] * 21})
    indexes = _index_frame(dates)
    indexes.loc[
        (indexes["index_code"] == "000001.SH")
        & (indexes["trade_date"] == ANALYSIS_DATE),
        "close",
    ] = np.nan
    indexes.loc[
        (indexes["index_code"] == "399001.SZ")
        & (indexes["trade_date"] == dates[-3].date()),
        "close",
    ] = np.nan

    row = compute_market_context_features(
        equity,
        indexes,
        _limits_for(equity),
        analysis_date=ANALYSIS_DATE,
        expected_current_rows=1,
    ).iloc[0]

    assert row["coverage_status"] == "limited"
    assert "broad index current coverage" in row["limitation_notes"]
    assert np.isnan(row["index_000001_sh_return_1d"])
    assert row["index_399001_sz_return_1d"] == pytest.approx(0.0)
    assert np.isnan(row["index_399001_sz_return_3d"])


def test_incomplete_current_limit_prices_hide_all_limit_event_results() -> None:
    dates = pd.bdate_range(end=ANALYSIS_DATE, periods=2)
    equity = _equity_frame(
        dates,
        {f"{offset}.SZ": [10.0, 10.0] for offset in range(5)},
    )

    row = compute_market_context_features(
        equity,
        _index_frame(dates),
        _limits_for(equity, take=4),
        analysis_date=ANALYSIS_DATE,
        expected_current_rows=5,
    ).iloc[0]

    assert row["limit_observed_count"] == 4
    assert row["limit_price_coverage_ratio"] == pytest.approx(0.8)
    assert row["coverage_status"] == "limited"
    assert "stock limit coverage" in row["limitation_notes"]
    for field in (
        "limit_up_count",
        "near_limit_up_count",
        "limit_down_count",
        "near_limit_down_count",
        "limit_up_share",
        "near_limit_up_share",
        "limit_down_share",
        "near_limit_down_share",
    ):
        assert np.isnan(row[field])


def test_output_is_observational_and_never_assigns_identity_or_action() -> None:
    dates = pd.bdate_range(end=ANALYSIS_DATE, periods=2)
    equity = _equity_frame(dates, {"A.SZ": [10.0, 10.2]})

    row = compute_market_context_features(
        equity,
        pd.DataFrame(columns=["trade_date", "index_code", "close"]),
        _empty_limits(),
        analysis_date=ANALYSIS_DATE,
        expected_current_rows=1,
    ).iloc[0]

    forbidden_field_fragments = {
        "institution",
        "main_force",
        "accumulation",
        "distribution",
        "manipulation",
        "recommend",
        "action",
        "bull",
        "bear",
        "regime",
    }
    assert not any(
        fragment in str(column).lower()
        for column in row.index
        for fragment in forbidden_field_fragments
    )
    assert row["interpretation_limit"] == "observable market facts only"
    assert row["coverage_status"] == "limited"
    assert "broad index current coverage" in row["limitation_notes"]
    assert "stock limit coverage" in row["limitation_notes"]


def test_stale_index_history_does_not_masquerade_as_analysis_date_return() -> None:
    dates = pd.bdate_range(end=ANALYSIS_DATE, periods=3)
    equity = _equity_frame(dates, {"A.SZ": [10.0, 10.1, 10.2]})
    stale_index = pd.DataFrame(
        [
            {
                "trade_date": trading_day.date(),
                "index_code": "000001.SH",
                "close": close,
            }
            for trading_day, close in zip(dates[:-1], [100.0, 101.0], strict=True)
        ]
    )

    row = compute_market_context_features(
        equity,
        stale_index,
        _empty_limits(),
        analysis_date=ANALYSIS_DATE,
        expected_current_rows=1,
    ).iloc[0]

    assert np.isnan(row["index_000001_sh_return_1d"])


def test_duplicate_business_facts_fail_before_calculation() -> None:
    dates = pd.bdate_range(end=ANALYSIS_DATE, periods=2)
    equity = _equity_frame(dates, {"A.SZ": [10.0, 10.2]})
    equity = pd.concat([equity, equity.tail(1)], ignore_index=True)

    with pytest.raises(ValueError, match="duplicate business fact"):
        compute_market_context_features(
            equity,
            pd.DataFrame(columns=["trade_date", "index_code", "close"]),
            _empty_limits(),
            analysis_date=ANALYSIS_DATE,
            expected_current_rows=1,
        )


def test_duplicate_index_and_limit_facts_fail_before_calculation() -> None:
    dates = pd.bdate_range(end=ANALYSIS_DATE, periods=2)
    equity = _equity_frame(dates, {"A.SZ": [10.0, 10.2]})
    indexes = _index_frame(dates)
    duplicate_indexes = pd.concat([indexes, indexes.tail(1)], ignore_index=True)
    limits = _limits_for(equity)
    duplicate_limits = pd.concat([limits, limits.tail(1)], ignore_index=True)

    with pytest.raises(ValueError, match="duplicate business fact in index daily"):
        compute_market_context_features(
            equity,
            duplicate_indexes,
            limits,
            analysis_date=ANALYSIS_DATE,
            expected_current_rows=1,
        )
    with pytest.raises(ValueError, match="duplicate business fact in stock limit"):
        compute_market_context_features(
            equity,
            indexes,
            duplicate_limits,
            analysis_date=ANALYSIS_DATE,
            expected_current_rows=1,
        )
