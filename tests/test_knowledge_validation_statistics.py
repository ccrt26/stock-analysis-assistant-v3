from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from stock_analyzer.knowledge_validation.models import MethodStatus, RelevanceStatus
from stock_analyzer.knowledge_validation.statistics import (
    aggregate_independent_units,
    benjamini_hochberg,
    classify_layers,
    moving_block_bootstrap,
)


def test_moving_block_bootstrap_is_deterministic():
    values = np.linspace(-0.02, 0.03, 120)

    first = moving_block_bootstrap(values)
    second = moving_block_bootstrap(values)

    assert first == second
    assert first["repetitions"] == 2_000
    assert first["block_length"] == 30


def test_benjamini_hochberg_matches_hand_calculation_for_nine_hypotheses():
    p_values = {
        f"h{i}": value
        for i, value in enumerate(
            [0.001, 0.01, 0.02, 0.04, 0.05, 0.2, 0.4, 0.8, 0.9],
            start=1,
        )
    }

    adjusted = benjamini_hochberg(p_values)

    assert adjusted["h1"] == pytest.approx(0.009)
    assert adjusted["h2"] == pytest.approx(0.045)
    assert adjusted["h3"] == pytest.approx(0.06)
    assert adjusted["h4"] == pytest.approx(0.09)
    assert adjusted["h5"] == pytest.approx(0.09)
    assert adjusted["h9"] == pytest.approx(0.9)


def test_duplicating_a_stock_row_does_not_change_date_level_aggregate():
    frame = pd.DataFrame(
        {
            "analysis_date": [date(2026, 7, 10)] * 2,
            "ts_code": ["A", "B"],
            "spread": [0.01, 0.03],
        }
    )
    duplicated = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)

    first = aggregate_independent_units(
        frame,
        value_column="spread",
        unit_columns=("analysis_date",),
        observation_columns=("analysis_date", "ts_code"),
    )
    second = aggregate_independent_units(
        duplicated,
        value_column="spread",
        unit_columns=("analysis_date",),
        observation_columns=("analysis_date", "ts_code"),
    )

    pd.testing.assert_frame_equal(first, second)
    assert first.loc[0, "spread"] == pytest.approx(0.02)


def test_target_success_cannot_upgrade_failed_method():
    result = classify_layers(
        sufficient=True,
        direction_ok=False,
        confirmation_direction_ok=False,
        q_value=0.001,
        stable_blocks_ratio=1.0,
        trend_supported=False,
        target_supported=True,
    )

    assert result.method.status is MethodStatus.NOT_VALIDATED
    assert result.target.status is RelevanceStatus.STRONG_SUPPORT


def test_confirmation_reversal_prevents_general_validation():
    result = classify_layers(
        sufficient=True,
        direction_ok=True,
        confirmation_direction_ok=False,
        q_value=0.001,
        stable_blocks_ratio=1.0,
        trend_supported=True,
        target_supported=False,
    )

    assert result.method.status is MethodStatus.NOT_VALIDATED


def test_predeclared_stable_condition_can_validate_conditionally():
    result = classify_layers(
        sufficient=True,
        direction_ok=True,
        confirmation_direction_ok=True,
        q_value=0.20,
        stable_blocks_ratio=0.60,
        predeclared_condition_only=True,
        conditional_q_value=0.01,
        conditional_stable_blocks_ratio=0.80,
        trend_supported=True,
        target_supported=False,
    )

    assert result.method.status is MethodStatus.VALIDATED_CONDITIONAL


def test_insufficient_sample_cannot_become_negative_or_positive_validation():
    result = classify_layers(
        sufficient=False,
        direction_ok=True,
        confirmation_direction_ok=True,
        q_value=0.001,
        stable_blocks_ratio=1.0,
        trend_supported=True,
        target_supported=True,
    )

    assert result.method.status is MethodStatus.INSUFFICIENT_SAMPLE
    assert result.trend.status is RelevanceStatus.INSUFFICIENT_SAMPLE
    assert result.target.status is RelevanceStatus.INSUFFICIENT_SAMPLE


def test_block_bootstrap_uses_contiguous_thirty_session_blocks():
    start = date(2026, 1, 1)
    frame = pd.DataFrame(
        {
            "analysis_date": [start + timedelta(days=index) for index in range(90)],
            "value": np.arange(90, dtype=float),
        }
    )

    result = moving_block_bootstrap(frame["value"].to_numpy())

    assert result["sample_size"] == 90
    assert result["block_length"] == 30
