import pandas as pd

from stock_analyzer.selection_lab.ranker import (
    choose_c,
    choose_model_variant,
    fit_ranker,
    select_probability_threshold,
)


def test_one_class_training_is_not_trainable():
    frame = pd.DataFrame({"x": [1.0, 2.0], "hit": [False, False]})

    result = fit_ranker(
        frame,
        label_column="hit",
        numeric_columns=["x"],
        categorical_columns=[],
        C=1.0,
    )

    assert result.status == "not_trainable"


def test_imputer_fits_training_data_only():
    train = pd.DataFrame({"x": [0.0, 2.0, None], "hit": [False, True, False]})

    result = fit_ranker(
        train,
        label_column="hit",
        numeric_columns=["x"],
        categorical_columns=[],
        C=1.0,
    )

    imputer = result.pipeline.named_steps["preprocess"].named_transformers_[
        "numeric"
    ].named_steps["imputer"]
    assert imputer.statistics_[0] == 1.0


def test_c_selection_uses_precision_then_brier_then_smaller_c():
    selected = choose_c(
        {
            0.1: {"policy_precision_at_5": 0.4, "brier": 0.2},
            1.0: {"policy_precision_at_5": 0.4, "brier": 0.2},
            10.0: {"policy_precision_at_5": 0.4, "brier": 0.3},
        }
    )

    assert selected == 0.1


def test_typed_model_needs_two_point_gain_and_no_worse_brier():
    assert choose_model_variant(
        plain={"policy_precision_at_5": 0.40, "brier": 0.20},
        typed={"policy_precision_at_5": 0.42, "brier": 0.20},
    ) == "with_opportunity_type"
    assert choose_model_variant(
        plain={"policy_precision_at_5": 0.40, "brier": 0.20},
        typed={"policy_precision_at_5": 0.42, "brier": 0.21},
    ) == "without_opportunity_type"


def _threshold_rows(date_count=10, stocks_per_date=3):
    rows = []
    for day in range(date_count):
        candidates = [(0.9, True), (0.7, False), (0.1, False)]
        for probability, hit in candidates[:stocks_per_date]:
            rows.append(
                {
                    "formation_date": f"D{day}",
                    "probability": probability,
                    "hit": hit,
                }
            )
    return pd.DataFrame(rows)


def test_threshold_requires_coverage_and_freezes_best_candidate():
    result = select_probability_threshold(_threshold_rows())

    assert result.status == "supported"
    assert result.threshold == 0.7
    assert result.nonempty_dates == 10
    assert result.total_selections == 20


def test_threshold_is_not_supported_with_too_few_dates():
    result = select_probability_threshold(_threshold_rows(date_count=5))

    assert result.status == "not_supported"
    assert result.threshold is None


def test_threshold_never_selects_more_than_five_per_date():
    frame = pd.DataFrame(
        {
            "formation_date": ["A"] * 10,
            "probability": [0.9] * 10,
            "hit": [True] * 10,
        }
    )

    result = select_probability_threshold(
        frame,
        minimum_nonempty_dates=1,
        minimum_total_selections=1,
    )

    assert result.max_daily_selections == 5


def test_threshold_scores_empty_dates_as_zero_before_tiebreaks():
    frame = pd.DataFrame(
        [
            {"formation_date": "A", "probability": 0.9, "hit": True},
            {"formation_date": "B", "probability": 0.6, "hit": True},
        ]
    )

    result = select_probability_threshold(
        frame,
        minimum_nonempty_dates=1,
        minimum_total_selections=1,
    )

    assert result.threshold == 0.6
