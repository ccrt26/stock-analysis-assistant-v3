from __future__ import annotations

import hashlib
import json
from datetime import date

import numpy as np
import pandas as pd
import pytest

import stock_analyzer.analysis.price_scenario_validation as scenario_validation

from stock_analyzer.analysis.price_scenario_validation import (
    SCENARIO_SPECS,
    assign_price_scenarios,
    compare_scenario_groups,
    describe_scenario_evidence,
    fit_scenario_thresholds,
    holm_adjust,
)


def test_development_thresholds_ignore_validation_period_values() -> None:
    frame = pd.DataFrame(
        {
            "analysis_date": [
                date(2024, 12, 30),
                date(2024, 12, 31),
                date(2025, 1, 2),
            ],
            "return_5d": [1.0, 3.0, 10_000.0],
            "relative_market_5d": [-2.0, 2.0, -10_000.0],
        }
    )

    observed = fit_scenario_thresholds(
        frame,
        fields=("return_5d", "relative_market_5d"),
        development_end=date(2024, 12, 31),
    )

    assert observed["return_5d"] == {
        "q20": 1.4,
        "q40": 1.8,
        "q60": 2.2,
        "q80": 2.6,
    }
    assert observed["relative_market_5d"] == pytest.approx({
        "q20": -1.2,
        "q40": -0.4,
        "q60": 0.4,
        "q80": 1.2,
    })


def test_frozen_price_scenario_thresholds_preserve_the_development_values() -> None:
    loader = getattr(
        scenario_validation,
        "load_frozen_price_scenario_thresholds",
        None,
    )
    assert callable(loader), "the production frozen-threshold loader is missing"

    document = loader()
    thresholds = document["thresholds"]
    digest = hashlib.sha256(
        json.dumps(
            thresholds,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    assert document["threshold_version"] == "price-scenario-thresholds-2026-08-19-v3"
    assert document["source_run_id"] == "2026-08-19-price-scenario-validation-v3"
    assert document["development_end"] == "2024-12-31"
    assert document["scenario_formula_source"] == (
        "stock_analyzer.analysis.price_scenario_validation.assign_price_scenarios"
    )
    assert len(thresholds) == 29
    assert digest == "c519d822671f5b0dcefa4145ca03cc46a1a018d9d7ac67c77bfb3be29a3787b8"


def test_indicator_cross_without_price_relative_and_volume_context_matches_nothing() -> None:
    frame = _scenario_frame(1)
    frame.loc[0, "macd_bullish_cross_last_5d"] = True
    frame.loc[0, [
        "return_20d",
        "relative_market_20d",
        "mean_close_position_5d",
        "volume_price_efficiency_5d",
    ]] = np.nan

    assignments = assign_price_scenarios(frame, _literal_thresholds())

    assert not any(
        bool(groups["case"].iloc[0]) or bool(groups["control"].iloc[0])
        for groups in assignments.values()
    )


def test_trend_continuation_requires_price_relative_close_and_volume_confirmation() -> None:
    frame = _scenario_frame(2)
    common = {
        "return_20d": 0.20,
        "relative_market_20d": 0.12,
        "ema_distance_20d": 0.04,
        "dmi_directional_spread_14d": 8.0,
        "efficiency_ratio_20d": 0.50,
        "up_days_5d": 4.0,
        "mean_close_position_5d": 0.80,
        "volume_price_efficiency_5d": 0.60,
        "signed_amount_balance_20d": 0.20,
        "price_amount_efficiency_20d": 0.30,
        "limit_up_return_contribution_5d": 0.10,
    }
    for field, value in common.items():
        frame[field] = value
    frame.loc[1, "volume_price_efficiency_5d"] = -0.20

    trend = assign_price_scenarios(frame, _literal_thresholds())[
        "trend_continuation"
    ]

    assert trend["case"].tolist() == [True, False]
    assert trend["control"].tolist() == [False, True]


def test_scenario_assignment_never_reads_future_outcomes() -> None:
    frame = _scenario_frame(2)
    frame["hit_20pct_d20"] = [0, 1]
    before = assign_price_scenarios(frame, _literal_thresholds())
    frame["hit_20pct_d20"] = [1, 0]
    frame["return_close_d20"] = [9.0, -9.0]
    after = assign_price_scenarios(frame, _literal_thresholds())

    for scenario in SCENARIO_SPECS:
        assert before[scenario]["case"].equals(after[scenario]["case"])
        assert before[scenario]["control"].equals(after[scenario]["control"])


def test_group_comparison_weights_formation_dates_not_row_counts() -> None:
    rows: list[dict[str, object]] = []
    for position in range(100):
        rows.append(_outcome_row(date(2025, 1, 2), f"A{position:03d}", 1, "case"))
        rows.append(_outcome_row(date(2025, 1, 7), f"D{position:03d}", 1, "control"))
    rows.append(_outcome_row(date(2025, 1, 2), "C000", 0, "control"))
    rows.append(_outcome_row(date(2025, 1, 7), "B000", 0, "case"))
    frame = pd.DataFrame(rows)

    observed = compare_scenario_groups(
        frame,
        case_mask=frame["group"] == "case",
        control_mask=frame["group"] == "control",
        bootstrap_repetitions=20,
        random_seed=7,
    )

    assert observed["common_date_count"] == 2
    assert observed["hit_rate_delta_date_equal"] == 0.0


def test_evidence_profile_reports_effect_without_three_percent_gate() -> None:
    evidence = _decision_metrics(
        primary_delta=0.029,
        primary_ci_low=0.01,
        primary_ci_high=0.05,
        expected_holm_p=0.01,
        opposite_holm_p=0.99,
        year_deltas={"2025": 0.02, "2026": 0.04},
        mfe_delta=0.02,
    )
    observed = describe_scenario_evidence(evidence, expected="positive_hit")

    assert observed["effect_direction"] == "expected"
    assert observed["interval_relation"] == "above_zero"
    assert observed["year_directions"] == {"2025": "expected", "2026": "expected"}
    assert observed["automatic_scene_decision"] is None

    opposite = _decision_metrics(
        primary_delta=-0.04,
        primary_ci_low=-0.07,
        primary_ci_high=-0.01,
        expected_holm_p=0.99,
        opposite_holm_p=0.01,
        year_deltas={"2025": -0.03, "2026": -0.05},
        mfe_delta=-0.02,
    )
    assert describe_scenario_evidence(
        opposite,
        expected="positive_hit",
    )["effect_direction"] == "opposite"


def test_holm_adjust_is_monotone_in_ordered_p_values() -> None:
    observed = holm_adjust({"a": 0.001, "b": 0.02, "c": 0.20})

    assert observed == {"a": 0.003, "b": 0.04, "c": 0.20}


def test_zero_inflated_limit_contribution_uses_positive_only_quantiles() -> None:
    frame = pd.DataFrame(
        {
            "analysis_date": [date(2024, 12, 31)] * 6,
            "limit_up_return_contribution_5d": [0.0, 0.0, 0.0, 0.2, 0.6, 1.0],
        }
    )

    observed = fit_scenario_thresholds(
        frame,
        fields=("limit_up_return_contribution_5d",),
        development_end=date(2024, 12, 31),
    )

    assert observed["limit_up_return_contribution_5d"]["q80"] == pytest.approx(0.6)
    assert observed["positive_limit_up_return_contribution_5d"] == pytest.approx(
        {"q20": 0.36, "q40": 0.52, "q60": 0.68, "q80": 0.84}
    )


def test_holm_adjust_keeps_missing_hypotheses_as_one_without_poisoning_valid_values() -> None:
    observed = holm_adjust({"clear": 0.001, "missing": np.nan, "weak": 0.20})

    assert observed == {"clear": 0.003, "weak": 0.4, "missing": 1.0}


def _scenario_frame(rows: int) -> pd.DataFrame:
    fields = {
        "analysis_date": [date(2025, 1, 2)] * rows,
        "ts_code": [f"{index:06d}.SZ" for index in range(rows)],
    }
    for field in _literal_thresholds():
        fields[field] = [0.0] * rows
    fields.update(
        {
            "breakout_prior_250d_high": [False] * rows,
            "macd_bullish_cross_last_5d": [False] * rows,
            "macd_bearish_cross_last_5d": [False] * rows,
            "stochastic_bullish_cross_last_5d": [False] * rows,
        }
    )
    return pd.DataFrame(fields)


def _literal_thresholds() -> dict[str, dict[str, float]]:
    fields = (
        "return_5d",
        "return_20d",
        "relative_market_5d",
        "relative_market_20d",
        "up_days_5d",
        "mean_close_position_5d",
        "upper_shadow_frequency_5d",
        "fade_frequency_5d",
        "volume_amplification_days_5d",
        "volume_price_efficiency_5d",
        "limit_up_return_contribution_5d",
        "amount_ratio_last_20d",
        "breakout_vs_prior60",
        "ema_distance_20d",
        "macd_histogram_ratio_change_5d",
        "efficiency_ratio_20d",
        "adx_14d",
        "dmi_directional_spread_14d",
        "rsi_14d",
        "stochastic_k_9_3",
        "bollinger_percent_b_20_2",
        "bollinger_bandwidth_change_5d",
        "signed_amount_balance_20d",
        "price_amount_efficiency_20d",
    )
    return {
        field: {"q20": -0.5, "q40": -0.1, "q60": 0.1, "q80": 0.5}
        for field in fields
    } | {
        "abs_return_20d": {"q20": 0.02, "q40": 0.05, "q60": 0.10, "q80": 0.20},
        "abs_relative_market_20d": {
            "q20": 0.01,
            "q40": 0.03,
            "q60": 0.06,
            "q80": 0.12,
        },
        "abs_dmi_directional_spread_14d": {
            "q20": 2.0,
            "q40": 5.0,
            "q60": 10.0,
            "q80": 20.0,
        },
        "abs_volume_price_efficiency_5d": {
            "q20": 0.1,
            "q40": 0.2,
            "q60": 0.4,
            "q80": 0.7,
        },
        "positive_limit_up_return_contribution_5d": {
            "q20": 0.2,
            "q40": 0.4,
            "q60": 0.6,
            "q80": 0.8,
        },
    }


def _outcome_row(day: date, code: str, hit: int, group: str) -> dict[str, object]:
    return {
        "analysis_date": day,
        "ts_code": code,
        "hit_20pct_d20": hit,
        "mfe_20d": 0.25 if hit else 0.05,
        "mae_20d": -0.04,
        "return_close_d20": 0.03,
        "group": group,
    }


def _decision_metrics(
    *,
    primary_delta: float,
    primary_ci_low: float,
    primary_ci_high: float,
    expected_holm_p: float,
    opposite_holm_p: float,
    year_deltas: dict[str, float],
    mfe_delta: float,
) -> dict[str, object]:
    return {
        "case_row_count": 500,
        "control_row_count": 500,
        "case_stock_count": 100,
        "control_stock_count": 100,
        "common_date_count": 40,
        "year_coverage": {
            "2025": {"case_rows": 100, "control_rows": 100, "common_dates": 20},
            "2026": {"case_rows": 100, "control_rows": 100, "common_dates": 20},
        },
        "primary_delta": primary_delta,
        "primary_ci_low": primary_ci_low,
        "primary_ci_high": primary_ci_high,
        "expected_holm_p": expected_holm_p,
        "opposite_holm_p": opposite_holm_p,
        "year_primary_deltas": year_deltas,
        "mfe_delta_date_equal": mfe_delta,
        "mae_delta_date_equal": -0.01,
        "hit_rate_delta_date_equal": primary_delta,
    }
