from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from stock_analyzer.analysis.price_indicator_validation import (
    admission_decision,
    binary_auc,
    build_baseline_panel,
    build_outcome_panel,
    cross_sectional_transform,
    evaluate_predictions,
    fit_ridge_logistic,
    predict_logistic,
)


def _outcome_prices() -> tuple[pd.DataFrame, list[date]]:
    dates = pd.bdate_range("2026-01-05", periods=30)
    close = [10.0] * 30
    frame = pd.DataFrame(
        {
            "trade_date": dates.date,
            "ts_code": "A.SZ",
            "open": close,
            "high": [10.5] * 30,
            "low": [9.5] * 30,
            "close": close,
            "adj_factor": 1.0,
            "amount": 100.0,
            "volume": 100.0,
        }
    )
    formation = dates[4].date()
    frame.loc[5, "open"] = 10.0
    frame.loc[5:24, "low"] = 9.0
    frame.loc[7, "high"] = 12.0
    return frame, [formation]


def test_outcome_uses_action_open_and_exact_twenty_session_path() -> None:
    frame, formation_dates = _outcome_prices()

    row = build_outcome_panel(frame, formation_dates=formation_dates).iloc[0]

    assert row["action_date"] == date(2026, 1, 12)
    assert row["hit_20pct_d20"] == 1
    assert row["mfe_20d"] == pytest.approx(0.20)
    assert row["mae_20d"] == pytest.approx(-0.10)
    assert row["time_to_hit_20pct"] == 3


def test_outcome_is_split_adjusted_and_ignores_days_after_d20() -> None:
    frame, formation_dates = _outcome_prices()
    expected = build_outcome_panel(frame, formation_dates=formation_dates)
    split = frame.copy()
    split.loc[split.index >= 10, ["open", "high", "low", "close"]] /= 2.0
    split.loc[split.index >= 10, "adj_factor"] = 2.0
    split.loc[25:, "high"] = 1_000.0

    observed = build_outcome_panel(split, formation_dates=formation_dates)

    for field in ("hit_20pct_d20", "mfe_20d", "mae_20d", "time_to_hit_20pct"):
        assert observed.iloc[0][field] == pytest.approx(expected.iloc[0][field])


def test_baseline_contains_existing_price_information_before_new_indicators() -> None:
    dates = pd.bdate_range(end="2026-07-10", periods=83)
    closes = np.arange(1.0, 84.0)
    amounts = np.asarray([100.0] * 78 + [300.0] * 5)
    equity = pd.DataFrame(
        {
            "trade_date": dates.date,
            "ts_code": "A.SZ",
            "open": closes - 0.1,
            "high": closes + 0.2,
            "low": closes - 0.2,
            "close": closes,
            "adj_factor": 1.0,
            "amount": amounts,
            "up_limit": closes + 100.0,
        }
    )
    benchmark = pd.DataFrame({"trade_date": dates.date, "close": 100.0})

    row = build_baseline_panel(
        equity,
        benchmark,
        formation_dates=[dates[-1].date()],
    ).iloc[0]

    assert row["return_5d"] == pytest.approx(83.0 / 78.0 - 1.0)
    assert row["relative_market_5d"] == pytest.approx(row["return_5d"])
    assert row["relative_continuity_5d"] == pytest.approx(1.0)
    assert row["up_days_5d"] == pytest.approx(5.0)
    assert row["mean_close_position_5d"] == pytest.approx(0.5)
    assert row["upper_shadow_frequency_5d"] == pytest.approx(1.0)
    assert row["fade_frequency_5d"] == pytest.approx(0.0)
    assert row["volume_amplification_days_5d"] == pytest.approx(5.0)
    assert row["breakout_vs_prior60"] == pytest.approx(83.0 / 82.2 - 1.0)
    assert row["price_location_60d"] == pytest.approx(1.0)
    assert row["price_location_82d"] == pytest.approx(1.0)


def test_baseline_snapshot_ignores_appended_future_rows() -> None:
    frame, formation_dates = _outcome_prices()
    frame["up_limit"] = 100.0
    benchmark = frame[["trade_date"]].drop_duplicates().assign(close=100.0)
    formation_date = formation_dates[0]
    expected = build_baseline_panel(
        frame,
        benchmark,
        formation_dates=[formation_date],
    )
    future = frame.tail(2).copy()
    future["trade_date"] = [date(2026, 3, 2), date(2026, 3, 3)]
    future[["open", "high", "low", "close"]] = 1_000.0

    observed = build_baseline_panel(
        pd.concat([frame, future], ignore_index=True),
        pd.concat(
            [
                benchmark,
                pd.DataFrame(
                    {"trade_date": future["trade_date"], "close": [1.0, 1.0]}
                ),
            ],
            ignore_index=True,
        ),
        formation_dates=[formation_date],
    )

    pd.testing.assert_frame_equal(observed, expected)


def test_cross_sectional_transform_ranks_values_and_declares_missingness() -> None:
    frame = pd.DataFrame(
        {
            "analysis_date": [date(2026, 1, 5)] * 4,
            "ts_code": ["A", "B", "C", "D"],
            "feature": [1.0, 2.0, 100.0, np.nan],
        }
    )

    transformed, columns = cross_sectional_transform(frame, ["feature"])

    assert columns == ["feature", "feature__missing"]
    assert transformed["feature"].tolist() == pytest.approx([-0.5, 0.0, 0.5, 0.0])
    assert transformed["feature__missing"].tolist() == [0.0, 0.0, 0.0, 1.0]


def test_fixed_ridge_logistic_learns_a_literal_monotone_pattern() -> None:
    x = np.asarray([[-2.0], [-1.0], [-0.5], [0.5], [1.0], [2.0]])
    y = np.asarray([0, 0, 0, 1, 1, 1], dtype=float)

    coefficients = fit_ridge_logistic(x, y, penalty=1.0)
    probability = predict_logistic(x, coefficients)

    assert coefficients.shape == (2,)
    assert coefficients[1] > 0
    assert np.all(np.diff(probability) > 0)
    assert binary_auc(y, probability) == pytest.approx(1.0)


def test_prediction_evaluation_is_date_equal_for_top_twenty() -> None:
    rows: list[dict[str, object]] = []
    for day in (date(2026, 1, 5), date(2026, 1, 6)):
        for offset in range(25):
            rows.append(
                {
                    "analysis_date": day,
                    "ts_code": f"{offset:02d}",
                    "hit_20pct_d20": 1 if offset < (2 if day.day == 5 else 4) else 0,
                    "mae_20d": -0.01 * offset,
                    "mfe_20d": 0.01 * offset,
                    "time_to_hit_20pct": 5.0 if offset < 4 else np.nan,
                    "probability": float(25 - offset),
                }
            )
    frame = pd.DataFrame(rows)

    metrics = evaluate_predictions(frame, probability_column="probability", top_count=20)

    assert metrics["top_count"] == 20
    assert metrics["top_date_equal_hit_rate"] == pytest.approx((2 / 20 + 4 / 20) / 2)
    assert metrics["observation_count"] == 50


def test_admission_requires_every_preregistered_condition() -> None:
    passing = {
        "auc_increment": 0.011,
        "relative_log_loss_improvement": 0.011,
        "top_hit_rate_increment": 0.031,
        "bootstrap_ci_low": 0.001,
        "holm_p_value": 0.04,
        "positive_stability_periods": 3,
        "top_mae_change": -0.01,
        "coverage": 0.96,
    }

    assert admission_decision(passing)["passed"] is True
    failing = dict(passing, auc_increment=0.009)
    decision = admission_decision(failing)
    assert decision["passed"] is False
    assert "auc_increment" in decision["failed_conditions"]


def test_admission_treats_decimal_thresholds_as_inclusive() -> None:
    exact_thresholds = {
        "auc_increment": 0.01,
        "relative_log_loss_improvement": 0.01,
        "top_hit_rate_increment": 0.029999999999999916,
        "bootstrap_ci_low": 1e-12,
        "holm_p_value": 0.049999999999,
        "positive_stability_periods": 3,
        "top_mae_change": -0.02,
        "coverage": 0.95,
    }

    assert admission_decision(exact_thresholds)["passed"] is True
