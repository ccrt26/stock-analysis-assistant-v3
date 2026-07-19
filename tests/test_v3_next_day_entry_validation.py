from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from stock_analyzer.evaluation.v3_next_day_entry_validation import (
    build_comparisons,
    compute_action_path,
    generate_report_from_frames,
    load_config,
    prepare_output_root,
    summarize_actions,
    validate_action_contracts,
)


CONFIG_PATH = Path(
    "docs/superpowers/specs/2026-07-19-v3-next-day-entry-validation-config.yaml"
)


def _prices(
    *,
    opens: list[float | None],
    highs: list[float | None],
    lows: list[float | None],
    closes: list[float | None],
    up_limits: list[float | None] | None = None,
) -> pd.DataFrame:
    count = len(opens)
    up_limits = up_limits or [None] * count
    return pd.DataFrame(
        {
            "trade_date": pd.bdate_range("2026-01-05", periods=count),
            "ts_code": ["A"] * count,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "adj_factor": [1.0] * count,
            "up_limit": up_limits,
        }
    )


def test_config_freezes_next_open_and_90_formation_days():
    config = load_config(CONFIG_PATH)

    assert config.horizons == (20, 30)
    assert config.entry_delay_market_sessions == 1
    assert config.entry_price_field == "open"
    assert config.entry_day_counts_as_session_one is True
    assert [block.id for block in config.blocks] == ["A", "B", "C"]
    assert config.rule_optimization_allowed is False


def test_output_root_must_be_frozen_usb_directory(tmp_path: Path):
    config = load_config(CONFIG_PATH)

    with pytest.raises(ValueError, match="U盘专用目录"):
        prepare_output_root(config, output_override=tmp_path / "wrong")


def test_next_market_session_open_is_action_price_and_entry_day_counts():
    prices = _prices(
        opens=[10.0, 10.5, 10.6],
        highs=[10.1, 12.7, 10.8],
        lows=[9.9, 10.4, 10.5],
        closes=[10.0, 12.5, 10.7],
        up_limits=[11.0, 13.0, 13.0],
    )

    row = compute_action_path(prices, "2026-01-05", "A", 1, 0.20, (1, 3, 5))

    assert row["entry_delay_sessions"] == 1
    assert row["entry_date"] == pd.Timestamp("2026-01-06")
    assert row["action_price"] == pytest.approx(10.5)
    assert row["first_touch_session"] == 1
    assert row["target_touched"] is True
    assert row["close_confirmed"] is False


def test_one_price_limit_up_is_not_executable_but_keeps_mechanical_path():
    prices = _prices(
        opens=[10.0, 11.0, 11.1],
        highs=[10.0, 11.0, 13.3],
        lows=[10.0, 11.0, 11.0],
        closes=[10.0, 11.0, 13.2],
        up_limits=[11.0, 11.0, 13.3],
    )

    row = compute_action_path(prices, "2026-01-05", "A", 2, 0.20, (1, 3, 5))

    assert row["entry_status"] == "one_price_limit_up"
    assert row["executable_entry"] is False
    assert pd.isna(row["target_touched"])
    assert row["mechanical_target_touched"] is True


def test_no_quote_on_next_market_session_does_not_roll_forward():
    prices = _prices(
        opens=[10.0, None, 10.5],
        highs=[10.0, None, 13.0],
        lows=[10.0, None, 10.4],
        closes=[10.0, None, 12.8],
        up_limits=[11.0, None, 13.0],
    )

    row = compute_action_path(prices, "2026-01-05", "A", 2, 0.20, (1, 3, 5))

    assert row["entry_date"] == pd.Timestamp("2026-01-06")
    assert row["entry_status"] == "no_quote_or_suspended"
    assert row["executable_entry"] is False
    assert pd.isna(row["action_price"])


def test_open_at_limit_but_intraday_open_is_flagged_not_excluded():
    prices = _prices(
        opens=[10.0, 11.0],
        highs=[10.0, 11.0],
        lows=[10.0, 10.5],
        closes=[10.0, 10.8],
        up_limits=[11.0, 11.0],
    )

    row = compute_action_path(prices, "2026-01-05", "A", 1, 0.20, (1, 3, 5))

    assert row["entry_status"] == "open_at_limit_not_one_price"
    assert row["executable_entry"] is True


def test_retention_is_measured_from_action_target_and_right_censored():
    prices = _prices(
        opens=[10.0, 10.0, 12.1, 12.2, 12.3],
        highs=[10.0, 10.2, 12.2, 12.3, 12.4],
        lows=[10.0, 9.9, 12.0, 12.1, 12.2],
        closes=[10.0, 10.1, 12.1, 12.2, 12.3],
        up_limits=[11.0, 11.0, 13.0, 13.0, 13.0],
    )

    row = compute_action_path(prices, "2026-01-05", "A", 2, 0.20, (1, 3, 5))

    assert row["close_confirmed"] is True
    assert row["retain_1_observable"] is True
    assert row["retain_1"] is True
    assert row["retain_3_observable"] is False
    assert pd.isna(row["retain_3"])


def test_summary_keeps_unexecutable_in_all_plan_yield_but_not_executable_rate():
    outcomes = pd.DataFrame(
        {
            "block": ["A", "A"],
            "policy": ["research_union", "research_union"],
            "layer": ["research", "research"],
            "formation_date": pd.to_datetime(["2026-01-05", "2026-01-06"]),
            "ts_code": ["A", "B"],
            "horizon": [20, 20],
            "complete_horizon": [True, True],
            "executable_entry": [True, False],
            "target_touched": pd.array([True, pd.NA], dtype="boolean"),
            "close_confirmed": pd.array([True, pd.NA], dtype="boolean"),
            "retain_1_observable": [True, False],
            "retain_1": pd.array([True, pd.NA], dtype="boolean"),
            "retain_3_observable": [False, False],
            "retain_3": pd.array([pd.NA, pd.NA], dtype="boolean"),
            "retain_5_observable": [False, False],
            "retain_5": pd.array([pd.NA, pd.NA], dtype="boolean"),
            "first_touch_session": [2, pd.NA],
            "formation_to_entry_gap": [0.01, pd.NA],
            "pre_touch_min_return": [-0.02, pd.NA],
            "window_min_return": [-0.02, pd.NA],
            "terminal_return": [0.22, pd.NA],
        }
    )

    row = summarize_actions(outcomes).query("block == 'ALL' and layer == 'all'").iloc[0]

    assert row["planned_actions"] == 2
    assert row["executable_entries"] == 1
    assert row["touch_rate_given_executable"] == pytest.approx(1.0)
    assert row["touch_yield_all_plans"] == pytest.approx(0.5)


def test_contracts_enforce_20_day_subset_and_next_market_session():
    valid = pd.DataFrame(
        {
            "block": ["A", "A"],
            "formation_date": pd.to_datetime(["2026-01-05", "2026-01-05"]),
            "ts_code": ["A", "A"],
            "horizon": [20, 30],
            "entry_delay_sessions": [1, 1],
            "complete_horizon": [True, True],
            "executable_entry": [True, True],
            "target_touched": pd.array([True, True], dtype="boolean"),
            "close_confirmed": pd.array([False, False], dtype="boolean"),
            "retain_1_observable": [False, False],
            "retain_1": pd.array([pd.NA, pd.NA], dtype="boolean"),
            "retain_3_observable": [False, False],
            "retain_3": pd.array([pd.NA, pd.NA], dtype="boolean"),
            "retain_5_observable": [False, False],
            "retain_5": pd.array([pd.NA, pd.NA], dtype="boolean"),
            "entry_status": ["executable_entry", "executable_entry"],
        }
    )

    checks = validate_action_contracts(valid)
    assert checks["touch_20_subset_30"] is True

    wrong = valid.copy()
    wrong.loc[:, "entry_delay_sessions"] = 2
    with pytest.raises(ValueError, match="下一市场交易日"):
        validate_action_contracts(wrong)


def test_contract_rejects_close_without_touch():
    invalid = pd.DataFrame(
        {
            "block": ["A"],
            "formation_date": pd.to_datetime(["2026-01-05"]),
            "ts_code": ["A"],
            "horizon": [20],
            "entry_delay_sessions": [1],
            "complete_horizon": [True],
            "executable_entry": [True],
            "target_touched": pd.array([False], dtype="boolean"),
            "close_confirmed": pd.array([True], dtype="boolean"),
            "retain_1_observable": [False],
            "retain_1": pd.array([pd.NA], dtype="boolean"),
            "retain_3_observable": [False],
            "retain_3": pd.array([pd.NA], dtype="boolean"),
            "retain_5_observable": [False],
            "retain_5": pd.array([pd.NA], dtype="boolean"),
            "entry_status": ["executable_entry"],
        }
    )

    with pytest.raises(ValueError, match="收盘确认"):
        validate_action_contracts(invalid)


def test_window_end_is_not_a_core_comparison_metric():
    rows = []
    for block in ("A", "B", "C", "ALL"):
        for policy, value in (("research_union", 0.3), ("matched_research_control", 0.2)):
            rows.append(
                {
                    "block": block,
                    "policy": policy,
                    "layer": "all",
                    "horizon": 20,
                    "touch_rate_given_executable": value,
                    "touch_yield_all_plans": value,
                    "close_rate_given_executable": value,
                    "close_yield_all_plans": value,
                    "retain_3_yield_all_plans": value,
                    "median_terminal_return": value,
                }
            )

    comparisons = build_comparisons(pd.DataFrame(rows))

    assert "median_terminal_return" not in set(comparisons["metric"])


def test_report_answers_action_question_without_claiming_realized_return(tmp_path: Path):
    report = generate_report_from_frames(
        {
            "summary": pd.DataFrame(),
            "comparisons": pd.DataFrame(),
            "cases": pd.DataFrame(),
            "quality": {},
        },
        tmp_path / "report.md",
    )
    text = report.read_text(encoding="utf-8")

    assert "次日开盘行动价" in text
    assert "20日机会窗口" in text
    assert "30日机会窗口" in text
    assert "哪些保留" in text
    assert "哪些需要优化" in text
    assert "不是固定卖出日" in text
    assert "保证实现收益" not in text
