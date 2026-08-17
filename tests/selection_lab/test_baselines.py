import pandas as pd

from stock_analyzer.selection_lab.baselines import rank_by_column, rank_random


def _frame():
    return pd.DataFrame(
        {
            "formation_date": ["2026-01-05"] * 3,
            "ts_code": ["000003.SZ", "000001.SZ", "000002.SZ"],
            "score": [1.0, 1.0, 0.5],
        }
    )


def test_ties_do_not_use_stock_code_lexical_order():
    forward = rank_by_column(_frame(), "score", dataset_version="v1")
    reverse = rank_by_column(
        _frame().iloc[::-1].reset_index(drop=True), "score", dataset_version="v1"
    )

    assert forward.set_index("ts_code")["rank"].to_dict() == reverse.set_index(
        "ts_code"
    )["rank"].to_dict()
    tied = forward.loc[forward["score"] == 1.0].sort_values("rank")
    assert tied["ts_code"].tolist() != ["000001.SZ", "000003.SZ"]


def test_random_ranking_is_deterministic_for_seed_and_draw():
    first = rank_random(_frame(), draw=17)
    second = rank_random(_frame(), draw=17)

    assert first[["ts_code", "rank", "score"]].to_dict("records") == second[
        ["ts_code", "rank", "score"]
    ].to_dict("records")


def test_random_ranking_changes_across_draws():
    first = rank_random(_frame(), draw=1)
    second = rank_random(_frame(), draw=2)

    assert first.set_index("ts_code")["score"].to_dict() != second.set_index(
        "ts_code"
    )["score"].to_dict()
