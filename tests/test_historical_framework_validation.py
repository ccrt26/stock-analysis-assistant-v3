from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from stock_analyzer.evaluation.historical_framework_validation import (
    compute_forward_outcomes,
    round_robin_union,
    select_spaced_origins,
    summarize_outcomes,
    validate_formation_cutoff,
)


def test_select_spaced_origins_uses_first_eligible_then_fixed_session_step():
    sessions = pd.date_range("2025-08-11", periods=9, freq="B").date.tolist()

    selected = select_spaced_origins(
        sessions,
        start=date(2025, 8, 12),
        end=date(2025, 8, 21),
        step=3,
    )

    assert selected == (
        date(2025, 8, 12),
        date(2025, 8, 15),
        date(2025, 8, 20),
    )


def test_validate_formation_cutoff_rejects_future_evidence():
    evidence = pd.DataFrame(
        {
            "ts_code": ["000001.SZ", "000002.SZ"],
            "available_at": [
                "2025-08-15T14:00:00+08:00",
                "2025-08-16T09:00:00+08:00",
            ],
        }
    )

    with pytest.raises(ValueError, match="future evidence"):
        validate_formation_cutoff(
            evidence,
            cutoff="2025-08-15T23:59:59+08:00",
        )


def test_validate_formation_cutoff_accepts_evidence_at_or_before_cutoff():
    evidence = pd.DataFrame(
        {
            "available_at": [
                "2025-08-14T18:00:00+08:00",
                "2025-08-15T15:00:00+08:00",
            ]
        }
    )

    validated = validate_formation_cutoff(
        evidence,
        cutoff="2025-08-15T23:59:59+08:00",
    )

    assert len(validated) == 2


def test_round_robin_union_deduplicates_and_preserves_route_order():
    selected = round_robin_union(
        {
            "earnings": ["A", "B", "C"],
            "hotspot": ["B", "D", "E"],
            "price": ["F", "A", "G"],
        },
        limit=6,
    )

    assert selected == ("A", "B", "F", "D", "G", "C")


def test_compute_forward_outcomes_separates_touch_terminal_and_adverse_path():
    prices = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(
                [
                    "2025-08-15",
                    "2025-08-18",
                    "2025-08-19",
                    "2025-08-20",
                    "2025-08-21",
                ]
            ),
            "ts_code": ["A"] * 5,
            "adj_close": [100.0, 105.0, 112.0, 118.0, 110.0],
            "adj_high": [101.0, 108.0, 121.0, 123.0, 112.0],
            "adj_low": [99.0, 94.0, 108.0, 115.0, 107.0],
        }
    )
    selections = pd.DataFrame(
        {
            "formation_date": [pd.Timestamp("2025-08-15")],
            "ts_code": ["A"],
            "policy": ["parallel_probe"],
            "layer": ["candidate"],
        }
    )

    outcomes = compute_forward_outcomes(
        prices,
        selections,
        horizons=(3,),
        target_return=0.20,
    )

    row = outcomes.iloc[0]
    assert bool(row["complete_horizon"]) is True
    assert bool(row["target_touched"]) is True
    assert row["first_target_session"] == 2
    assert row["max_favorable_return"] == pytest.approx(0.23)
    assert row["max_adverse_return"] == pytest.approx(-0.06)
    assert row["terminal_return"] == pytest.approx(0.18)
    assert bool(row["target_before_drawdown_5"]) is False
    assert bool(row["target_before_drawdown_10"]) is True


def test_compute_forward_outcomes_marks_incomplete_horizon_without_dropping_row():
    prices = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(
                ["2025-08-15", "2025-08-18", "2025-08-19"]
            ),
            "ts_code": ["A"] * 3,
            "adj_close": [100.0, 101.0, 102.0],
            "adj_high": [100.0, 102.0, 103.0],
            "adj_low": [100.0, 99.0, 100.0],
        }
    )
    selections = pd.DataFrame(
        {
            "formation_date": [pd.Timestamp("2025-08-15")],
            "ts_code": ["A"],
            "policy": ["price_probe"],
            "layer": ["candidate"],
        }
    )

    outcomes = compute_forward_outcomes(
        prices,
        selections,
        horizons=(3,),
        target_return=0.20,
    )

    assert len(outcomes) == 1
    assert bool(outcomes.iloc[0]["complete_horizon"]) is False
    assert outcomes.iloc[0]["observed_sessions"] == 2


def test_compute_forward_outcomes_counts_market_sessions_not_stock_quotes():
    prices = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(
                [
                    "2025-08-15",
                    "2025-08-18",
                    "2025-08-20",
                    "2025-08-15",
                    "2025-08-18",
                    "2025-08-19",
                    "2025-08-20",
                ]
            ),
            "ts_code": ["A", "A", "A", "B", "B", "B", "B"],
            "adj_close": [100.0, 101.0, 121.0, 10.0, 10.0, 10.0, 10.0],
            "adj_high": [100.0, 102.0, 121.0, 10.0, 10.0, 10.0, 10.0],
            "adj_low": [100.0, 99.0, 120.0, 10.0, 10.0, 10.0, 10.0],
        }
    )
    selections = pd.DataFrame(
        {
            "formation_date": [pd.Timestamp("2025-08-15")],
            "ts_code": ["A"],
            "policy": ["price_probe"],
            "layer": ["candidate"],
        }
    )

    outcomes = compute_forward_outcomes(
        prices,
        selections,
        horizons=(3,),
        target_return=0.20,
    )

    row = outcomes.iloc[0]
    assert bool(row["complete_horizon"]) is True
    assert row["observed_sessions"] == 3
    assert row["quoted_sessions"] == 2
    assert row["first_target_session"] == 3


def test_summarize_outcomes_keeps_metrics_separate():
    outcomes = pd.DataFrame(
        {
            "policy": ["parallel_probe"] * 3,
            "horizon": [20, 20, 20],
            "complete_horizon": [True, True, False],
            "target_touched": [True, False, False],
            "first_target_session": [7.0, float("nan"), float("nan")],
            "terminal_return": [0.10, -0.05, 0.02],
            "max_adverse_return": [-0.04, -0.12, -0.03],
        }
    )

    summary = summarize_outcomes(outcomes)

    row = summary.iloc[0]
    assert row["selections"] == 3
    assert row["complete"] == 2
    assert row["hits"] == 1
    assert row["precision"] == pytest.approx(0.5)
    assert row["median_lead_session"] == pytest.approx(7.0)
    assert row["mean_terminal_return"] == pytest.approx(0.025)
    assert row["mean_max_adverse_return"] == pytest.approx(-0.08)
