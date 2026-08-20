from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from stock_analyzer.analysis.market_skill_validation import (
    assign_market_hypotheses,
    build_market_formation_panel,
    evaluate_market_hypotheses,
    fit_market_thresholds,
)


def _stock_sample() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for formation, action, scale in (
        (date(2024, 12, 20), date(2024, 12, 23), 1.0),
        (date(2025, 1, 10), date(2025, 1, 13), 2.0),
    ):
        for offset in range(1, 6):
            current_amount = 100.0 * offset
            rows.append(
                {
                    "analysis_date": formation,
                    "action_date": action,
                    "ts_code": f"{offset:06d}.SZ",
                    "return_1d": scale * offset / 100.0,
                    "return_5d": scale * (offset - 3) / 100.0,
                    "return_20d": scale * (offset - 2) / 100.0,
                    "relative_market_20d": float(offset),
                    "liquidity_log10_amount": np.log10(current_amount),
                    "amount_ratio_last_20d": 2.0,
                    "hit_20pct_d20": int(offset >= 4),
                    "return_close_d20": scale * offset / 100.0,
                }
            )
    return pd.DataFrame(rows)


def _indexes(formations: list[date]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for formation in formations:
        dates = pd.bdate_range(end=formation, periods=6)
        for code, finish in (
            ("000001.SH", 105.0),
            ("399001.SZ", 110.0),
            ("399006.SZ", 95.0),
        ):
            values = np.linspace(100.0, finish, 6)
            rows.extend(
                {
                    "trade_date": trading_day.date(),
                    "index_code": code,
                    "close": close,
                }
                for trading_day, close in zip(dates, values, strict=True)
            )
    return pd.DataFrame(rows).drop_duplicates(["trade_date", "index_code"])


def test_formation_panel_aggregates_stocks_before_market_inference() -> None:
    sample = _stock_sample()
    formations = sorted(sample["analysis_date"].unique())
    market_dates = pd.bdate_range(start=date(2024, 12, 23), periods=20)
    market_daily = pd.DataFrame(
        {
            "trade_date": market_dates.date,
            "equal_weight_return_1d": np.linspace(-0.01, 0.01, 20),
        }
    )

    panel = build_market_formation_panel(
        sample,
        _indexes(formations),
        market_daily,
        future_volatility_window=3,
    )

    assert len(panel) == 2
    first = panel.iloc[0]
    assert first["stock_count"] == 5
    assert first["equal_weight_return_5d"] == pytest.approx(0.0)
    assert first["median_return_5d"] == pytest.approx(0.0)
    assert first["breadth_5d"] == pytest.approx(2 / 5)
    assert first["return_dispersion_1d"] == pytest.approx(
        np.std([0.01, 0.02, 0.03, 0.04, 0.05], ddof=0)
    )
    assert first["turnover_coverage_ratio"] == pytest.approx(1.0)
    assert first["turnover_ratio_20d"] == pytest.approx(2.0)
    assert first["opportunity_hit_rate_20d"] == pytest.approx(2 / 5)
    assert first["equal_weight_return_close_20d"] == pytest.approx(0.03)
    assert first["trend_spread_return_20d"] == pytest.approx(0.04)
    assert first["scope_anchor_return_5d"] == pytest.approx(
        np.mean([0.05, 0.10, -0.05])
    )
    expected_volatility = (
        market_daily["equal_weight_return_1d"].iloc[:3].std(ddof=1)
        * np.sqrt(252.0)
    )
    assert first["future_market_volatility_20d"] == pytest.approx(
        expected_volatility
    )


def test_thresholds_use_development_dates_only() -> None:
    panel = pd.DataFrame(
        {
            "analysis_date": [date(2024, 1, 1), date(2024, 2, 1), date(2025, 1, 1)],
            "breadth_5d": [0.2, 0.8, 999.0],
            "breadth_20d": [0.3, 0.7, 999.0],
            "turnover_ratio_20d": [0.5, 1.5, 999.0],
            "equal_weight_return_5d": [-0.1, 0.1, 999.0],
        }
    )

    thresholds = fit_market_thresholds(panel, development_end=date(2024, 12, 31))

    assert thresholds["breadth_5d"]["q40"] == pytest.approx(0.44)
    assert thresholds["breadth_5d"]["q60"] == pytest.approx(0.56)
    assert thresholds["abs_equal_weight_return_5d"]["q40"] == pytest.approx(0.1)


def test_scope_anchor_return_does_not_compress_a_missing_index_session() -> None:
    sample = _stock_sample().iloc[:5].copy()
    formation = sample["analysis_date"].iloc[0]
    indexes = _indexes([formation])
    earliest = min(indexes["trade_date"])
    prior = (pd.Timestamp(earliest) - pd.offsets.BDay(1)).date()
    indexes = pd.concat(
        [
            pd.DataFrame(
                {
                    "trade_date": [prior] * 3,
                    "index_code": ["000001.SH", "399001.SZ", "399006.SZ"],
                    "close": [99.0, 99.0, 99.0],
                }
            ),
            indexes,
        ],
        ignore_index=True,
    )
    missing_date = sorted(indexes["trade_date"].unique())[-3]
    indexes = indexes[
        ~(
            (indexes["index_code"] == "399001.SZ")
            & (indexes["trade_date"] == missing_date)
        )
    ]
    market_daily = pd.DataFrame(
        {
            "trade_date": pd.bdate_range(sample["action_date"].iloc[0], periods=20).date,
            "equal_weight_return_1d": np.linspace(-0.01, 0.01, 20),
        }
    )

    panel = build_market_formation_panel(
        sample,
        indexes,
        market_daily,
        future_volatility_window=3,
    )

    assert np.isnan(panel.iloc[0]["scope_anchor_return_5d"])


def test_future_volatility_does_not_skip_a_missing_action_date() -> None:
    sample = _stock_sample().iloc[:5].copy()
    formation = sample["analysis_date"].iloc[0]
    action = sample["action_date"].iloc[0]
    market_daily = pd.DataFrame(
        {
            "trade_date": pd.bdate_range(
                pd.Timestamp(action) + pd.offsets.BDay(1), periods=20
            ).date,
            "equal_weight_return_1d": np.linspace(-0.01, 0.01, 20),
        }
    )

    panel = build_market_formation_panel(
        sample,
        _indexes([formation]),
        market_daily,
        future_volatility_window=3,
    )

    assert np.isnan(panel.iloc[0]["future_market_volatility_20d"])


def test_assignment_never_reads_future_outcomes() -> None:
    panel = _synthetic_market_panel()
    thresholds = _fixed_thresholds()

    first = assign_market_hypotheses(panel, thresholds)
    changed = panel.copy()
    for field in (
        "opportunity_hit_rate_20d",
        "future_market_volatility_20d",
        "trend_spread_return_20d",
    ):
        changed[field] = changed[field] * -1000.0 + 7.0
    second = assign_market_hypotheses(changed, thresholds)

    for hypothesis_id in first:
        for group in first[hypothesis_id]:
            pd.testing.assert_series_equal(
                first[hypothesis_id][group], second[hypothesis_id][group]
            )


def test_evaluation_uses_formation_dates_and_admits_strong_stable_relations() -> None:
    panel = _synthetic_market_panel()

    result = evaluate_market_hypotheses(
        panel,
        _fixed_thresholds(),
        bootstrap_repetitions=200,
        permutation_repetitions=200,
        random_seed=20260819,
    )

    assert result["unit_of_analysis"] == "formation_date"
    assert result["formation_date_count"] == len(panel)
    for hypothesis_id in (
        "market_h1_breadth_index_alignment",
        "market_h2_turnover_price_progress",
        "market_h3_dispersion_future_volatility",
        "market_h4_state_changes_trend_reliability",
    ):
        assert result["hypotheses"][hypothesis_id]["maturity"] == "level_2_direct"
        assert result["hypotheses"][hypothesis_id]["admission_passed"] is True


def _fixed_thresholds() -> dict[str, dict[str, float]]:
    return {
        "breadth_5d": {"q40": 0.45, "q60": 0.55},
        "breadth_20d": {"q40": 0.45, "q60": 0.55},
        "turnover_ratio_20d": {"q40": 0.9, "q60": 1.1},
        "equal_weight_return_5d": {"q40": 0.005, "q60": 0.015},
        "abs_equal_weight_return_5d": {"q40": 0.005, "q60": 0.015},
    }


def _synthetic_market_panel() -> pd.DataFrame:
    dates = list(pd.bdate_range("2025-01-02", periods=390).date)
    rows: list[dict[str, object]] = []
    for offset, formation in enumerate(dates):
        strong = offset % 2 == 0
        dispersion = 0.01 + offset / 10000.0
        rows.append(
            {
                "analysis_date": formation,
                "scope_anchor_return_5d": 0.02,
                "equal_weight_return_5d": 0.03 if strong else 0.0,
                "median_return_5d": 0.02 if strong else -0.01,
                "breadth_5d": 0.70 if strong else 0.30,
                "breadth_20d": 0.70 if strong else 0.30,
                "turnover_ratio_20d": 1.5,
                "equal_weight_return_20d": 0.05 if strong else -0.02,
                "return_dispersion_1d": dispersion,
                "opportunity_hit_rate_20d": 0.15 if strong else 0.05,
                "equal_weight_return_close_20d": 0.04 if strong else -0.01,
                "future_market_volatility_20d": 0.10 + dispersion * 2.0,
                "trend_spread_return_20d": 0.04 if strong else -0.02,
            }
        )
    return pd.DataFrame(rows)
