from __future__ import annotations

import pandas as pd
import pytest

from stock_analyzer.evaluation.v3_backtest.statistics import (
    STATIONARY_BLOCK_LENGTHS,
    STATIONARY_BOOTSTRAP_SEEDS,
    audit_representative_misses,
    compare_layers,
    compare_replacements,
    stationary_block_interval,
    summarize_occupancy,
)


def _outcome(
    project_id: str,
    layer: str,
    baseline_type: str,
    touched: bool,
    *,
    cohort: str = "complete_mechanism",
    first_target: float | None = None,
    terminal: float = 0.0,
    adverse: float = -0.05,
) -> dict[str, object]:
    return {
        "project_id": project_id,
        "cohort": cohort,
        "layer": layer,
        "baseline_type": baseline_type,
        "horizon": 20,
        "complete_horizon": True,
        "target_touched": touched,
        "first_target_session": first_target,
        "terminal_return": terminal,
        "max_adverse_return": adverse,
        "target_before_drawdown_5": touched,
        "target_before_drawdown_10": touched,
    }


def test_compare_layers_uses_focus_action_baseline_and_backup_discovery_baseline():
    outcomes = pd.DataFrame(
        [
            _outcome("F", "focus", "discovery", True, first_target=4),
            _outcome("F", "focus", "action", False, terminal=-0.10),
            _outcome(
                "E", "early_validation", "discovery", True, first_target=8
            ),
            _outcome(
                "H", "high_elasticity_tracking", "discovery", False, terminal=0.03
            ),
            _outcome(
                "M",
                "baseline",
                "discovery",
                True,
                cohort="matched_market",
                first_target=12,
            ),
            _outcome(
                "U",
                "baseline",
                "discovery",
                False,
                cohort="all_market",
            ),
            _outcome(
                "T",
                "baseline",
                "discovery",
                True,
                cohort="hotspot_baseline",
                first_target=10,
            ),
            _outcome(
                "G",
                "baseline",
                "discovery",
                False,
                cohort="earnings_baseline",
            ),
            _outcome(
                "P",
                "baseline",
                "discovery",
                True,
                cohort="price_baseline",
                first_target=9,
            ),
        ]
    )

    summary = compare_layers(outcomes)

    focus = summary.query("group == 'focus'").iloc[0]
    early = summary.query("group == 'early_validation'").iloc[0]
    matched = summary.query("group == 'matched_market'").iloc[0]
    assert focus["hits"] == 0
    assert focus["touch_rate"] == pytest.approx(0.0)
    assert early["touch_rate"] == pytest.approx(1.0)
    assert matched["touch_rate"] == pytest.approx(1.0)
    assert set(summary["group"]) == {
        "focus",
        "early_validation",
        "high_elasticity_tracking",
        "matched_market",
        "all_market",
        "hotspot_baseline",
        "earnings_baseline",
        "price_baseline",
    }


def test_compare_replacements_requires_pair_and_reports_paired_increments():
    paired = pd.DataFrame(
        {
            "replacement_id": ["R1", "R1"],
            "replacement_role": ["challenger", "replaced"],
            "baseline_type": ["replacement", "replacement"],
            "baseline_date": pd.to_datetime(["2026-02-02", "2026-02-02"]),
            "horizon": [20, 20],
            "complete_horizon": [True, True],
            "target_touched": [True, True],
            "first_target_session": [7, 12],
            "terminal_return": [0.18, 0.10],
            "max_adverse_return": [-0.06, -0.11],
        }
    )

    result = compare_replacements(paired)

    row = result.iloc[0]
    assert row["touch_delta"] == 0
    assert row["lead_session_advantage"] == pytest.approx(5.0)
    assert row["terminal_return_delta"] == pytest.approx(0.08)
    assert row["drawdown_return_delta"] == pytest.approx(0.05)
    assert bool(row["replacement_success"]) is True

    with pytest.raises(ValueError, match="challenger and replaced"):
        compare_replacements(paired.iloc[[0]])


def test_challenger_rising_alone_is_not_counted_as_replacement_success():
    paired = pd.DataFrame(
        {
            "replacement_id": ["R2", "R2"],
            "replacement_role": ["challenger", "replaced"],
            "baseline_type": ["replacement", "replacement"],
            "baseline_date": pd.to_datetime(["2026-02-02", "2026-02-02"]),
            "horizon": [20, 20],
            "complete_horizon": [True, True],
            "target_touched": [False, False],
            "first_target_session": [None, None],
            "terminal_return": [0.19, -0.08],
            "max_adverse_return": [-0.04, -0.09],
        }
    )

    result = compare_replacements(paired)

    assert result.iloc[0]["terminal_return_delta"] == pytest.approx(0.27)
    assert bool(result.iloc[0]["replacement_success"]) is False


def test_summarize_occupancy_reports_delay_churn_retention_and_common_exposure():
    statuses = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(
                [
                    "2026-02-02",
                    "2026-02-02",
                    "2026-02-03",
                    "2026-02-03",
                    "2026-02-04",
                    "2026-02-04",
                ]
            ),
            "project_id": ["A", "B", "A", "B", "A", "B"],
            "policy": ["rolling"] * 6,
            "active": [True, True, True, True, False, True],
            "layer": ["early_validation", "focus", "focus", "focus", None, "early_validation"],
            "transition": ["new", "new", "upgraded", "retained", "exited", "downgraded"],
            "invalidated": [False, False, True, False, True, False],
            "target_touched": [False, False, False, True, True, True],
            "industry": ["I", "I", "I", "I", "I", "I"],
            "theme": ["T", "T", "T", "T", "T", "T"],
        }
    )

    result = summarize_occupancy(statuses)

    project_a = result["projects"].query("project_id == 'A'").iloc[0]
    day_two = result["daily"].loc[
        result["daily"]["trade_date"] == pd.Timestamp("2026-02-03")
    ].iloc[0]
    exposure = result["exposure"].loc[
        result["exposure"]["trade_date"] == pd.Timestamp("2026-02-03")
    ].iloc[0]
    assert project_a["invalidated_occupancy_days"] == 0
    assert bool(project_a["premature_exit"]) is True
    assert day_two["upgraded"] == 1
    assert day_two["retention_rate"] == pytest.approx(1.0)
    assert exposure["max_industry_share"] == pytest.approx(1.0)
    assert exposure["max_theme_share"] == pytest.approx(1.0)


def test_occupancy_exit_inference_uses_trade_dates_not_input_index_order():
    statuses = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(
                ["2026-02-04", "2026-02-02", "2026-02-03"]
            ),
            "project_id": ["A", "A", "A"],
            "policy": ["rolling"] * 3,
            "active": [False, True, True],
            "layer": [None, "early_validation", "focus"],
            "transition": ["retained", "new", "upgraded"],
            "invalidated": [False, False, False],
            "target_touched": [True, False, False],
            "industry": ["I"] * 3,
            "theme": ["T"] * 3,
        }
    )

    summary = summarize_occupancy(statuses)

    project = summary["projects"].iloc[0]
    assert project["exit_date"] == pd.Timestamp("2026-02-04")
    assert bool(project["premature_exit"]) is True


def test_stationary_interval_uses_all_frozen_lengths_and_excludes_extension():
    values = pd.DataFrame(
        {
            "formation_date": pd.to_datetime(
                [
                    "2025-10-30",
                    "2025-10-31",
                    "2026-01-08",
                    "2026-01-09",
                    "2026-03-25",
                    "2026-03-26",
                    "2025-08-15",
                ]
            ),
            "sample": ["primary"] * 6 + ["extension"],
            "time_block": ["A", "A", "B", "B", "C", "C", "extension"],
            "metric": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 999.0],
        }
    )

    first = stationary_block_interval(values, value_column="metric", repetitions=80)
    second = stationary_block_interval(values, value_column="metric", repetitions=80)

    pd.testing.assert_frame_equal(first, second)
    intervals = first.query("scope == 'primary_interval'")
    blocks = first.query("scope == 'primary_time_block'")
    extension = first.query("scope == 'extension_sample'")
    assert tuple(intervals["mean_block_length"]) == STATIONARY_BLOCK_LENGTHS
    assert all(intervals["seeds"].map(tuple) == STATIONARY_BOOTSTRAP_SEEDS)
    assert intervals["estimate"].tolist() == pytest.approx([3.5, 3.5, 3.5])
    assert blocks.set_index("time_block")["estimate"].to_dict() == {
        "A": 1.5,
        "B": 3.5,
        "C": 5.5,
    }
    assert extension.iloc[0]["estimate"] == pytest.approx(999.0)

    with pytest.raises(ValueError, match="5, 10, and 20"):
        stationary_block_interval(
            values,
            value_column="metric",
            block_lengths=(5,),
            repetitions=20,
        )


def test_stationary_interval_requires_all_three_preregistered_primary_blocks():
    incomplete = pd.DataFrame(
        {
            "formation_date": pd.to_datetime(["2025-10-30", "2026-01-08"]),
            "sample": ["primary", "primary"],
            "time_block": ["A", "B"],
            "metric": [1.0, 2.0],
        }
    )

    with pytest.raises(ValueError, match="blocks A, B, and C"):
        stationary_block_interval(
            incomplete,
            value_column="metric",
            repetitions=20,
        )


def test_representative_misses_filter_tradeability_then_use_frozen_reason_order():
    candidates = pd.DataFrame(
        {
            "formation_date": pd.to_datetime(["2026-03-02"] * 6),
            "ts_code": list("ABCDEF"),
            "representative": [True] * 6,
            "target_touched": [True, True, True, True, True, False],
            "basically_tradable": [True, True, True, True, False, True],
            "selected": [False, False, False, False, False, False],
            "route_scanned": [False, True, True, True, False, False],
            "evidence_complete": [False, False, True, True, False, False],
            "comparison_passed": [False, False, False, True, False, False],
        }
    )

    misses = audit_representative_misses(candidates)

    assert misses.set_index("ts_code")["miss_reason"].to_dict() == {
        "A": "route_miss",
        "B": "evidence_missing",
        "C": "comparison_failure",
        "D": "capacity_limit",
    }
