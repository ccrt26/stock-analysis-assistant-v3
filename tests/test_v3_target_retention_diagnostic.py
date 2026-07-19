from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from stock_analyzer.evaluation.v3_target_retention_diagnostic import (
    build_comparisons,
    compute_retention_path,
    generate_report_from_frames,
    load_config,
    prepare_output_root,
    summarize_retention,
    validate_outcome_contracts,
)


CONFIG_PATH = Path(
    "docs/superpowers/specs/2026-07-19-v3-target-retention-diagnostic-config.yaml"
)


def test_config_freezes_scope_and_forbids_rule_optimization():
    config = load_config(CONFIG_PATH)

    assert [block.id for block in config.blocks] == ["A", "B", "C"]
    assert config.horizons == (10, 20, 30)
    assert config.retention_windows == (1, 2, 3, 5)
    assert config.target_return == pytest.approx(0.20)
    assert config.primary_horizon == 20
    assert config.rule_optimization_allowed is False


def test_output_root_must_be_exact_frozen_usb_directory(tmp_path: Path):
    config = load_config(CONFIG_PATH)

    with pytest.raises(ValueError, match="U盘专用目录"):
        prepare_output_root(config, output_override=tmp_path / "wrong")


def test_output_root_creates_only_fixed_children(tmp_path: Path):
    config = load_config(CONFIG_PATH)
    volume = tmp_path / "ZHUTONG"
    output = volume / "股票分析助手-V3回测" / config.experiment_id

    prepared = prepare_output_root(
        config,
        output_override=output,
        allowed_volume_root=volume,
    )

    assert prepared == output
    assert {path.name for path in output.iterdir()} == {
        "manifests",
        "tables",
        "reports",
    }


def test_touch_without_close_is_not_confirmed_or_retained():
    prices = _prices([10.0, 11.8, 11.4], highs=[10.0, 12.1, 11.5])

    row = compute_retention_path(
        prices,
        formation_date="2026-01-05",
        ts_code="A",
        horizon=2,
        target_return=0.20,
        retention_windows=(1, 2, 3, 5),
    )

    assert row["target_touched"] is True
    assert row["close_confirmed"] is False
    assert pd.isna(row["retain_1"])
    assert row["retain_1_observable"] is False


def test_exact_float_boundary_matches_source_return_formula():
    prices = _prices(
        [101.2624, 101.2624],
        highs=[101.2624, 121.51488],
    )

    row = compute_retention_path(
        prices,
        formation_date="2026-01-05",
        ts_code="A",
        horizon=1,
        target_return=0.20,
        retention_windows=(1, 2, 3, 5),
    )

    assert 121.51488 / 101.2624 - 1.0 < 0.20
    assert row["target_touched"] is False


def test_close_confirmation_and_strict_retention_are_nested():
    prices = _prices([10.0, 12.01, 12.1, 12.2, 11.9, 12.4])

    row = compute_retention_path(
        prices,
        formation_date="2026-01-05",
        ts_code="A",
        horizon=1,
        target_return=0.20,
        retention_windows=(1, 2, 3, 5),
    )

    assert row["close_confirmed"] is True
    assert row["retain_1"] is True
    assert row["retain_2"] is True
    assert row["retain_3"] is False
    assert row["first_close_loss_sessions"] == 3
    assert row["first_close_loss_return"] == pytest.approx(0.19)


def test_incomplete_post_confirmation_window_is_not_failure():
    prices = _prices([10.0, 12.01, 12.1])

    row = compute_retention_path(
        prices,
        formation_date="2026-01-05",
        ts_code="A",
        horizon=1,
        target_return=0.20,
        retention_windows=(1, 2, 3, 5),
    )

    assert row["retain_1_observable"] is True
    assert row["retain_1"] is True
    assert row["retain_2_observable"] is False
    assert pd.isna(row["retain_2"])


def test_continue_rising_requires_retention_and_later_higher_close():
    prices = _prices([10.0, 12.01, 12.2, 12.1])

    row = compute_retention_path(
        prices,
        formation_date="2026-01-05",
        ts_code="A",
        horizon=1,
        target_return=0.20,
        retention_windows=(1, 2),
    )

    assert row["retain_2"] is True
    assert row["advance_2"] is True


def test_summary_excludes_unobservable_retention_from_denominator():
    outcomes = pd.DataFrame(
        {
            "formation_date": ["2026-01-05", "2026-01-06"],
            "ts_code": ["A", "B"],
            "block": ["A", "A"],
            "policy": ["research_union", "research_union"],
            "layer": ["research", "research"],
            "horizon": [20, 20],
            "complete_horizon": [True, True],
            "target_touched": [True, True],
            "close_confirmed": [True, True],
            "retain_1_observable": [True, True],
            "retain_1": [True, False],
            "advance_1": [True, False],
            "retain_2_observable": [True, False],
            "retain_2": [True, pd.NA],
            "advance_2": [True, pd.NA],
            "retain_3_observable": [True, False],
            "retain_3": [True, pd.NA],
            "advance_3": [True, pd.NA],
            "retain_5_observable": [False, False],
            "retain_5": [pd.NA, pd.NA],
            "advance_5": [pd.NA, pd.NA],
            "first_close_loss_sessions": [pd.NA, 1],
            "terminal_above_target": [True, False],
            "terminal_return": [0.25, 0.05],
        }
    )

    summary = summarize_retention(outcomes, retention_windows=(1, 2, 3, 5))
    row = summary[(summary["block"] == "A") & (summary["layer"] == "research")].iloc[0]

    assert row["retain_3_observations"] == 1
    assert row["retain_3_successes"] == 1
    assert row["retain_3_all_denominator"] == 1
    assert row["retain_3_rate_all"] == pytest.approx(1.0)
    assert row["retain_3_rate_given_close"] == pytest.approx(1.0)
    assert row["right_censored_3"] == 1


def test_close_confirmation_is_always_subset_of_touch():
    invalid = pd.DataFrame(
        {
            "target_touched": [False],
            "close_confirmed": [True],
            "retain_1_observable": [False],
            "retain_1": [pd.NA],
            "retain_2_observable": [False],
            "retain_2": [pd.NA],
            "retain_3_observable": [False],
            "retain_3": [pd.NA],
            "retain_5_observable": [False],
            "retain_5": [pd.NA],
        }
    )

    with pytest.raises(ValueError, match="收盘确认必须是盘中触及子集"):
        validate_outcome_contracts(invalid, retention_windows=(1, 2, 3, 5))


def test_report_preserves_research_boundary(tmp_path: Path):
    summary = pd.DataFrame(
        [
            {
                "block": "ALL",
                "policy": "research_union",
                "layer": "all",
                "horizon": 20,
                "observations": 10,
                "touch_rate": 0.4,
                "close_confirm_rate": 0.3,
                "touch_to_close_rate": 0.75,
                "retain_1_observations": 3,
                "retain_1_rate_all": 0.2,
                "retain_1_rate_given_close": 2 / 3,
                "retain_2_observations": 3,
                "retain_2_rate_all": 0.2,
                "retain_2_rate_given_close": 2 / 3,
                "retain_3_observations": 3,
                "retain_3_rate_all": 0.1,
                "retain_3_rate_given_close": 1 / 3,
                "retain_5_observations": 2,
                "retain_5_rate_all": 0.1,
                "retain_5_rate_given_close": 0.5,
                "right_censored_5": 1,
                "terminal_above_target_rate": 0.2,
                "median_terminal_return": 0.02,
            }
        ]
    )
    frames = {
        "summary": summary,
        "comparisons": pd.DataFrame(),
        "route_combinations": pd.DataFrame(),
        "feature_diagnostics": pd.DataFrame(),
        "cases": pd.DataFrame(),
        "coverage": pd.DataFrame(),
    }

    report = generate_report_from_frames(frames, tmp_path / "report.md")
    text = report.read_text(encoding="utf-8")

    assert "盘中触及率" in text
    assert "收盘确认率" in text
    assert "严格保持" in text
    assert "不能作为全新样本外证明" in text
    assert "不是固定持有期或卖出日" in text
    assert "真实策略收益率" not in text


def test_window_end_snapshot_is_not_a_core_comparison_metric():
    rows = []
    for block in ("A", "B", "C", "ALL"):
        for policy, value in (("research_union", 0.3), ("matched_research_control", 0.2)):
            rows.append(
                {
                    "block": block,
                    "policy": policy,
                    "layer": "all",
                    "horizon": 20,
                    "touch_rate": value,
                    "close_confirm_rate": value,
                    "retain_1_rate_all": value,
                    "retain_2_rate_all": value,
                    "retain_3_rate_all": value,
                    "retain_5_rate_all": value,
                    "terminal_above_target_rate": value,
                }
            )

    comparisons = build_comparisons(pd.DataFrame(rows))

    assert "terminal_above_target_rate" not in set(comparisons["metric"])


def _prices(closes: list[float], *, highs: list[float] | None = None) -> pd.DataFrame:
    dates = pd.bdate_range("2026-01-05", periods=len(closes))
    highs = highs or closes
    return pd.DataFrame(
        {
            "trade_date": dates,
            "ts_code": ["A"] * len(closes),
            "adj_close": closes,
            "adj_high": highs,
            "adj_low": [value * 0.99 for value in closes],
            "quoted": [True] * len(closes),
        }
    )
