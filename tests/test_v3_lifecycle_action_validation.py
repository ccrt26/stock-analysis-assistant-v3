from pathlib import Path

import pandas as pd
import pytest

from stock_analyzer.evaluation.v3_lifecycle_action_validation import (
    action_condition,
    apply_post_run_safety_audit,
    build_action_paths_for_signals,
    build_daily_attention,
    evaluate_acceptance,
    generate_report,
    load_config,
    prepare_output_root,
    simulate_lifecycle,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = (
    REPO_ROOT
    / "docs/superpowers/specs/2026-07-19-v3-lifecycle-action-validation-config.yaml"
)


def _action_row(**overrides: object) -> pd.Series:
    values: dict[str, object] = {
        "return_5d": 0.01,
        "relative_return_20d": 0.02,
        "current_amount_ratio_20d": 1.0,
        "hard_invalid": False,
        "user_layer": "关注",
    }
    values.update(overrides)
    return pd.Series(values)


def test_action_condition_requires_all_three_observable_confirmations() -> None:
    assert action_condition(_action_row())
    assert not action_condition(_action_row(return_5d=0.0))
    assert not action_condition(_action_row(relative_return_20d=0.0))
    assert not action_condition(_action_row(current_amount_ratio_20d=0.99))


def test_action_condition_rejects_invalid_non_attention_and_missing_values() -> None:
    assert not action_condition(_action_row(hard_invalid=True))
    assert not action_condition(_action_row(user_layer="不展示"))
    assert not action_condition(_action_row(return_5d=pd.NA))


def test_config_freezes_holdout_rule_and_usb_root() -> None:
    config = load_config(CONFIG_PATH)
    assert config.holdout.id == "D"
    assert config.holdout.start.isoformat() == "2025-12-11"
    assert config.holdout.end.isoformat() == "2026-01-23"
    assert config.formation_sessions == 30
    assert config.horizons == (20, 30)
    assert config.action_fields == (
        "return_5d",
        "relative_return_20d",
        "current_amount_ratio_20d",
    )
    assert str(config.output_root).startswith("/Volumes/ZHUTONG/")


def test_output_guard_rejects_non_usb_or_wrong_experiment_path(tmp_path: Path) -> None:
    config = load_config(CONFIG_PATH)
    with pytest.raises(ValueError, match="U盘"):
        prepare_output_root(config, output_override=tmp_path)


def _attention_row(day: pd.Timestamp, code: str = "000001.SZ", **overrides: object) -> dict[str, object]:
    row = _action_row(**overrides).to_dict()
    row.update({"formation_date": day, "ts_code": code})
    return row


def _execution(
    plan_day: pd.Timestamp,
    entry_day: pd.Timestamp,
    code: str = "000001.SZ",
    *,
    executable: bool = True,
    price: float = 10.0,
) -> dict[str, object]:
    return {
        "plan_date": plan_day,
        "entry_date": entry_day,
        "ts_code": code,
        "executable_entry": executable,
        "action_price": price if executable else pd.NA,
    }


def _run_lifecycle(
    attention: list[dict[str, object]],
    *,
    executions: list[dict[str, object]] | None = None,
    invalid: list[tuple[pd.Timestamp, str]] | None = None,
    highs: list[tuple[pd.Timestamp, str, float]] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    config = load_config(CONFIG_PATH)
    sessions = pd.bdate_range("2025-01-02", periods=36)
    facts = pd.DataFrame(
        [
            {"formation_date": day, "ts_code": code, "hard_invalid": True}
            for day, code in (invalid or [])
        ],
        columns=["formation_date", "ts_code", "hard_invalid"],
    )
    prices = pd.DataFrame(
        [
            {"trade_date": day, "ts_code": code, "adj_high": high}
            for day, code, high in (highs or [])
        ],
        columns=["trade_date", "ts_code", "adj_high"],
    )
    return simulate_lifecycle(
        pd.DataFrame(attention),
        facts,
        pd.DataFrame(
            executions or [],
            columns=[
                "plan_date",
                "entry_date",
                "ts_code",
                "executable_entry",
                "action_price",
            ],
        ),
        prices,
        sessions,
        config,
    )


def test_soft_absence_does_not_exit_and_daily_cap_remains_ten() -> None:
    sessions = pd.bdate_range("2025-01-02", periods=36)
    attention = [_attention_row(sessions[0], f"{index:06d}.SZ", return_5d=-0.01) for index in range(12)]
    snapshots, _, exclusions = _run_lifecycle(attention)
    day_one = snapshots[snapshots["formation_date"].eq(sessions[1])]
    assert int(day_one["active"].sum()) == 10
    assert not day_one["exit_reason"].eq("no_longer_qualified").any()
    assert len(exclusions) == 2
    assert snapshots.groupby("formation_date")["active"].sum().max() <= 10


def test_never_confirmed_project_exits_at_day_ten() -> None:
    sessions = pd.bdate_range("2025-01-02", periods=36)
    snapshots, actions, _ = _run_lifecycle(
        [_attention_row(sessions[0], return_5d=-0.01)]
    )
    terminal = snapshots[snapshots["exit_reason"].eq("not_confirmed_by_day_10")]
    assert terminal["age_sessions"].tolist() == [10]
    assert actions.empty


def test_confirmed_project_requires_second_wave_at_day_twenty() -> None:
    sessions = pd.bdate_range("2025-01-02", periods=36)
    snapshots, actions, _ = _run_lifecycle(
        [_attention_row(sessions[0])],
        executions=[_execution(sessions[0], sessions[1])],
    )
    terminal = snapshots[
        snapshots["exit_reason"].eq("no_second_wave_confirmation")
    ]
    assert terminal["age_sessions"].tolist() == [20]
    assert len(actions) == 1


def test_second_wave_survives_to_day_thirty_and_one_project_has_one_action() -> None:
    sessions = pd.bdate_range("2025-01-02", periods=36)
    snapshots, actions, _ = _run_lifecycle(
        [_attention_row(sessions[0]), _attention_row(sessions[18])],
        executions=[_execution(sessions[0], sessions[1])],
    )
    terminal = snapshots[snapshots["exit_reason"].eq("day_30_expiry")]
    assert terminal["age_sessions"].tolist() == [30]
    assert actions.groupby("project_id").size().max() == 1


def test_hard_invalidation_ends_project_immediately() -> None:
    sessions = pd.bdate_range("2025-01-02", periods=36)
    snapshots, _, _ = _run_lifecycle(
        [_attention_row(sessions[0], return_5d=-0.01)],
        invalid=[(sessions[3], "000001.SZ")],
    )
    terminal = snapshots[snapshots["exit_reason"].eq("hard_invalidation")]
    assert terminal["age_sessions"].tolist() == [3]


def test_unexecutable_plan_can_retry_but_only_first_executable_action_is_kept() -> None:
    sessions = pd.bdate_range("2025-01-02", periods=36)
    attention = [
        _attention_row(sessions[0]),
        _attention_row(sessions[2]),
        _attention_row(sessions[4]),
    ]
    executions = [
        _execution(sessions[0], sessions[1], executable=False),
        _execution(sessions[2], sessions[3], executable=True, price=11.0),
        _execution(sessions[4], sessions[5], executable=True, price=12.0),
    ]
    _, actions, _ = _run_lifecycle(attention, executions=executions)
    assert len(actions) == 1
    assert actions.iloc[0]["plan_date"] == sessions[2]
    assert actions.iloc[0]["action_price"] == 11.0


def _evidence_row(day: str, code: str, **overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "formation_date": pd.Timestamp(day),
        "ts_code": code,
        "routes": "hotspot",
        "company_evidence": False,
        "hard_invalid": False,
        "evidence_freshness": 2,
        "earnings_cash_consistency": 2,
        "hotspot_support": 3,
        "price_consumption_safety": 3,
        "liquidity": 3,
        "market_breadth_20d": 0.6,
        "hotspot_group_name": "测试行业",
        "report_period": pd.Timestamp("2025-09-30"),
        "report_available_at": pd.Timestamp("2025-10-30", tz="UTC"),
        "tr_yoy": 1.0,
        "netprofit_yoy": -1.0,
        "dt_netprofit_yoy": -1.0,
        "ocf_yoy": 1.0,
        "n_cashflow_act": 1.0,
        "return_5d": 0.01,
        "return_20d": 0.05,
        "relative_return_20d": 0.02,
        "price_location_60d": 0.7,
        "current_amount_ratio_20d": 1.2,
        "average_amount_20d": 100000.0,
        "pe_ttm": 20.0,
        "pb": 2.0,
    }
    row.update(overrides)
    return row


def test_build_daily_attention_reuses_single_list_compression(tmp_path: Path) -> None:
    root = tmp_path / "tables/formations/block=D/formation_date=2025-12-11"
    root.mkdir(parents=True)
    pd.DataFrame(
        [
            _evidence_row("2025-12-11", "000001.SZ"),
            _evidence_row(
                "2025-12-11",
                "000002.SZ",
                hard_invalid=True,
            ),
        ]
    ).to_parquet(root / "evidence.parquet", index=False)
    attention = build_daily_attention(tmp_path, candidate_cap=10)
    assert attention[["formation_date", "ts_code", "user_layer"]].to_dict(
        orient="records"
    ) == [
        {
            "formation_date": pd.Timestamp("2025-12-11"),
            "ts_code": "000001.SZ",
            "user_layer": "关注",
        }
    ]


def test_action_paths_use_next_open_and_preserve_outcome_nesting() -> None:
    config = load_config(CONFIG_PATH)
    sessions = pd.bdate_range("2025-12-11", periods=36)
    prices = pd.DataFrame(
        {
            "trade_date": sessions,
            "ts_code": "000001.SZ",
            "open": [10.0] * len(sessions),
            "high": [10.0] * len(sessions),
            "low": [9.0] * len(sessions),
            "close": [10.0] * len(sessions),
            "adj_factor": [1.0] * len(sessions),
            "up_limit": [11.0] * len(sessions),
        }
    )
    prices.loc[prices["trade_date"].eq(sessions[6]), ["high", "close"]] = 12.1
    signals = pd.DataFrame(
        [{"formation_date": sessions[0], "ts_code": "000001.SZ"}]
    )
    paths = build_action_paths_for_signals(signals, prices, config, policy="test")
    assert set(paths["horizon"]) == {20, 30}
    assert paths["entry_date"].drop_duplicates().tolist() == [sessions[1]]
    assert paths.loc[paths["horizon"].eq(20), "target_touched"].item()
    assert paths.loc[paths["horizon"].eq(30), "target_touched"].item()
    assert (
        paths["close_confirmed"].fillna(False).astype(bool)
        <= paths["target_touched"].fillna(False).astype(bool)
    ).all()


def _summary_fixture(action_n: int = 24) -> pd.DataFrame:
    rows = []
    for horizon, baseline_touch, baseline_close, action_touch, action_close in (
        (20, 0.30, 0.25, 0.38, 0.33),
        (30, 0.40, 0.35, 0.48, 0.43),
    ):
        rows.extend(
            [
                {
                    "policy": "project_entry",
                    "horizon": horizon,
                    "planned_actions": 30,
                    "executable_entries": 30,
                    "touch_yield_all_plans": baseline_touch,
                    "close_yield_all_plans": baseline_close,
                    "retain_3_yield_all_plans": 0.15,
                    "median_window_min_return": -0.12,
                },
                {
                    "policy": "project_action",
                    "horizon": horizon,
                    "planned_actions": action_n,
                    "executable_entries": action_n,
                    "touch_yield_all_plans": action_touch,
                    "close_yield_all_plans": action_close,
                    "retain_3_yield_all_plans": 0.18,
                    "median_window_min_return": -0.11,
                },
            ]
        )
    return pd.DataFrame(rows)


def _lifecycle_fixture() -> dict[str, float]:
    return {
        "median_duration_sessions": 8.0,
        "mature_projects_5": 20.0,
        "survived_5_projects": 12.0,
        "rolling_retention_rate": 0.80,
        "reset_retention_rate": 0.45,
        "rolling_churn_intensity": 0.40,
        "reset_churn_intensity": 0.80,
        "admitted_touch_30": 0.40,
        "capacity_excluded_touch_30": 0.42,
        "day_10_exit_touch_30": 0.43,
    }


def test_acceptance_keeps_technical_lifecycle_and_action_results_separate() -> None:
    config = load_config(CONFIG_PATH)
    result = evaluate_acceptance(
        _summary_fixture(),
        _lifecycle_fixture(),
        {"dates_30": True, "daily_cap": True, "source_unchanged": True},
        config,
        largest_stock_success_share=0.20,
    )
    assert result["technical_passed"]
    assert result["lifecycle_feasibility"] == "supported"
    assert result["action_feasibility"] == "supported"


def test_acceptance_reports_insufficient_action_sample_without_relabeling_lifecycle() -> None:
    config = load_config(CONFIG_PATH)
    result = evaluate_acceptance(
        _summary_fixture(action_n=10),
        _lifecycle_fixture(),
        {"dates_30": True, "daily_cap": True, "source_unchanged": True},
        config,
        largest_stock_success_share=0.20,
    )
    assert result["lifecycle_feasibility"] == "supported"
    assert result["action_feasibility"] == "insufficient_evidence"


def test_acceptance_rejects_stability_that_blocks_better_later_winners() -> None:
    config = load_config(CONFIG_PATH)
    lifecycle = _lifecycle_fixture()
    lifecycle["capacity_excluded_touch_30"] = 0.60
    result = evaluate_acceptance(
        _summary_fixture(),
        lifecycle,
        {"dates_30": True, "daily_cap": True, "source_unchanged": True},
        config,
        largest_stock_success_share=0.20,
    )
    assert result["lifecycle_feasibility"] == "stable_but_unusable"


def test_report_explains_results_in_plain_chinese_and_keeps_buy_sell_boundary(
    tmp_path: Path,
) -> None:
    report = generate_report(
        _summary_fixture(),
        _lifecycle_fixture(),
        {
            "technical_passed": True,
            "lifecycle_feasibility": "supported",
            "action_feasibility": "supported",
            "lifecycle_checks": {},
        },
        {"dates_30": True},
        pd.DataFrame(
            [
                {
                    "case_type": "day_10_early_exit_winner",
                    "ts_code": "000001.SZ",
                    "formation_date": pd.Timestamp("2025-12-11"),
                    "detail": "退出后达到目标",
                }
            ]
        ),
        tmp_path / "report.md",
    )
    text = report.read_text(encoding="utf-8")
    assert "2025-12-11 至 2026-01-23" in text
    assert "20个交易日内" in text
    assert "第20个交易日当天" in text
    assert "退出后达到目标" in text
    assert "不能证明正式买入或卖出能力" in text


def test_post_run_safety_audit_vetoes_hard_exits_that_later_hit_target() -> None:
    acceptance = {
        "technical_passed": True,
        "lifecycle_feasibility": "supported",
        "action_feasibility": "supported",
    }
    snapshots = pd.DataFrame(
        [
            {
                "project_id": f"p{index}",
                "ts_code": f"{index:06d}.SZ",
                "formation_date": pd.Timestamp("2025-12-15"),
                "exit_reason": "hard_invalidation",
            }
            for index in range(5)
        ]
    )
    entry_paths = pd.DataFrame(
        [
            {
                "project_id": f"p{index}",
                "ts_code": f"{index:06d}.SZ",
                "horizon": 30,
                "target_touched": index < 3,
                "first_touch_date": pd.Timestamp("2025-12-20")
                if index < 3
                else pd.NaT,
            }
            for index in range(5)
        ]
    )
    audited = apply_post_run_safety_audit(acceptance, snapshots, entry_paths)
    assert audited["pre_registered_lifecycle_feasibility"] == "supported"
    assert audited["lifecycle_feasibility"] == "rejected"
    assert audited["post_run_safety_audit"]["hard_exit_later_touch_count"] == 3
