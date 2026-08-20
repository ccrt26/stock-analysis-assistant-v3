from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from stock_analyzer.analysis.price_scenario_validation import (
    SCENARIO_THRESHOLD_FIELDS,
)


ANALYSIS_DATE = date(2026, 8, 19)


def _facts(*, periods: int = 260) -> tuple[pd.DataFrame, pd.DataFrame]:
    dates = pd.bdate_range(end=ANALYSIS_DATE, periods=periods)
    closes = 20.0 + np.arange(periods, dtype=float) * 0.08
    equity = pd.DataFrame(
        {
            "trade_date": dates.date,
            "ts_code": "000001.SZ",
            "open": closes - 0.03,
            "high": closes + 0.12,
            "low": closes - 0.10,
            "close": closes,
            "adj_factor": 1.0,
            "amount": 1_000_000.0 + np.arange(periods) * 10_000.0,
            "up_limit": closes * 1.10,
        }
    )
    benchmark = pd.DataFrame(
        {
            "trade_date": dates.date,
            "close": 3_000.0 + np.arange(periods, dtype=float) * 2.0,
        }
    )
    return equity, benchmark


def test_daily_price_context_covers_every_declared_scenario_input() -> None:
    from stock_analyzer.analysis.price_analysis_features import (
        PRICE_ANALYSIS_FORMULA_VERSION,
        PRICE_SCENARIO_EVENT_FIELDS,
        compute_price_analysis_features,
    )

    equity, benchmark = _facts()

    result = compute_price_analysis_features(
        equity,
        benchmark,
        analysis_date=ANALYSIS_DATE,
    )

    assert len(result) == 1
    row = result.iloc[0]
    assert set(SCENARIO_THRESHOLD_FIELDS).issubset(result.columns)
    assert set(PRICE_SCENARIO_EVENT_FIELDS).issubset(result.columns)
    assert row["price_analysis_formula_version"] == PRICE_ANALYSIS_FORMULA_VERSION
    assert row["price_indicator_formula_version"] == (
        "price-indicator-conditional-states-v2"
    )
    assert row["coverage_status"] == "complete"
    assert not any(column.startswith("scenario_") for column in result.columns)


def test_daily_price_context_is_formation_date_safe() -> None:
    from stock_analyzer.analysis.price_analysis_features import (
        compute_price_analysis_features,
    )

    equity, benchmark = _facts()
    expected = compute_price_analysis_features(
        equity,
        benchmark,
        analysis_date=ANALYSIS_DATE,
    )
    future_dates = pd.bdate_range(start="2026-08-20", periods=2)
    future_equity = pd.DataFrame(
        {
            "trade_date": future_dates.date,
            "ts_code": "000001.SZ",
            "open": [1_000.0, 2_000.0],
            "high": [1_100.0, 2_200.0],
            "low": [900.0, 1_800.0],
            "close": [1_050.0, 2_100.0],
            "adj_factor": [1.0, 1.0],
            "amount": [1e10, 2e10],
            "up_limit": [1_100.0, 2_200.0],
        }
    )
    future_benchmark = pd.DataFrame(
        {"trade_date": future_dates.date, "close": [9_000.0, 10_000.0]}
    )

    observed = compute_price_analysis_features(
        pd.concat([equity, future_equity], ignore_index=True),
        pd.concat([benchmark, future_benchmark], ignore_index=True),
        analysis_date=ANALYSIS_DATE,
    )

    pd.testing.assert_frame_equal(observed, expected)


def test_short_history_remains_limited_without_filling_long_anchor() -> None:
    from stock_analyzer.analysis.price_analysis_features import (
        compute_price_analysis_features,
    )

    equity, benchmark = _facts(periods=40)

    row = compute_price_analysis_features(
        equity,
        benchmark,
        analysis_date=ANALYSIS_DATE,
    ).iloc[0]

    assert row["coverage_status"] == "limited"
    assert pd.isna(row["distance_to_prior_250d_high"])
    assert pd.isna(row["breakout_prior_250d_high"])
    assert "short history" in row["limitation_notes"]
