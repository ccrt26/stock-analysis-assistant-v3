import pandas as pd

from stock_analyzer.selection_lab.evaluation import (
    bootstrap_date_mean,
    evaluate_rankings,
)


def test_evaluation_equal_weights_dates_not_rows():
    rows = [
        {"formation_date": "A", "score": 1.0, "hit": True, "executable": True},
        {"formation_date": "A", "score": 0.0, "hit": False, "executable": True},
    ]
    rows.extend(
        {"formation_date": "B", "score": float(20 - i), "hit": False, "executable": True}
        for i in range(20)
    )

    result = evaluate_rankings(pd.DataFrame(rows), ks=(1,))

    assert result["policy_precision_at_1"] == 0.5


def test_effective_k_uses_available_candidate_count():
    frame = pd.DataFrame(
        [
            {"formation_date": "A", "score": 2.0, "hit": True, "executable": True},
            {"formation_date": "A", "score": 1.0, "hit": False, "executable": True},
        ]
    )

    result = evaluate_rankings(frame, ks=(5,))

    assert result["policy_precision_at_5"] == 0.5


def test_policy_does_not_replace_non_executable_top_candidate():
    frame = pd.DataFrame(
        [
            {"formation_date": "A", "score": 2.0, "hit": False, "executable": False},
            {"formation_date": "A", "score": 1.0, "hit": True, "executable": True},
        ]
    )

    result = evaluate_rankings(frame, ks=(1,))

    assert result["policy_precision_at_1"] == 0.0
    assert result["executable_precision_at_1"] is None


def test_policy_counts_non_executable_top_candidate_as_unmet():
    frame = pd.DataFrame(
        [
            {"formation_date": "A", "score": 2.0, "hit": True, "executable": False},
        ]
    )

    result = evaluate_rankings(frame, ks=(1,))

    assert result["policy_precision_at_1"] == 0.0


def test_empty_frame_returns_null_metrics_with_reason():
    result = evaluate_rankings(
        pd.DataFrame(columns=["formation_date", "score", "hit", "executable"]),
        ks=(1, 3, 5),
    )

    assert result["policy_precision_at_5"] is None
    assert result["reason_code"] == "no_evaluable_rows"


def test_bootstrap_is_deterministic_and_samples_dates():
    values = {"A": 0.1, "B": 0.2, "C": 0.3}

    first = bootstrap_date_mean(values, iterations=1000)
    second = bootstrap_date_mean(values, iterations=1000)

    assert first == second
    assert first[0] <= 0.2 <= first[1]
