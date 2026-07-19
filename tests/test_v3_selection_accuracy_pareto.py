from __future__ import annotations

from pathlib import Path

import pandas as pd

from stock_analyzer.evaluation.v3_selection_accuracy_pareto import (
    baseline_action_mask,
    build_development_projects,
    generate_report,
    pareto_status,
    summarize_rule,
)


def _feature_row(day: str, code: str, block: str = "A") -> dict[str, object]:
    return {
        "formation_date": pd.Timestamp(day),
        "ts_code": code,
        "block": block,
        "user_layer": "关注",
        "hard_invalid": False,
        "return_5d": 0.05,
        "return_20d": 0.10,
        "relative_return_20d": 0.03,
        "current_amount_ratio_20d": 1.2,
        "price_location_60d": 0.8,
        "tr_yoy": 10.0,
        "netprofit_yoy": 20.0,
        "dt_netprofit_yoy": 15.0,
        "ocf_yoy": 12.0,
        "n_cashflow_act": 100.0,
        "routes": "hotspot",
        "hotspot_support": 3,
        "company_driver_state": "partial",
        "executable_entry": True,
        "complete_horizon": True,
        "entry_date": pd.Timestamp(day) + pd.Timedelta(days=1),
        "formation_to_entry_gap": 0.0,
        "window_min_return": -0.05,
        "target_touched": True,
        "close_confirmed": True,
        "retain_3": True,
        "policy": "v3_recompressed",
        "layer": "关注",
    }


def test_baseline_action_requires_all_three_confirmations() -> None:
    frame = pd.DataFrame([_feature_row("2025-01-02", "000001.SZ")])
    assert baseline_action_mask(frame).tolist() == [True]
    frame.loc[0, "current_amount_ratio_20d"] = 0.99
    assert baseline_action_mask(frame).tolist() == [False]


def test_build_development_projects_keeps_first_action_per_stock_and_block(
    tmp_path: Path,
) -> None:
    abc = tmp_path / "abc" / "tables"
    d = tmp_path / "d" / "tables"
    abc.mkdir(parents=True)
    d.mkdir(parents=True)

    rows: list[dict[str, object]] = []
    for block, code in (("A", "000001.SZ"), ("B", "000002.SZ"), ("C", "000003.SZ")):
        for day in ("2025-01-02", "2025-01-03"):
            for horizon in (20, 30):
                row = _feature_row(day, code, block)
                row["horizon"] = horizon
                rows.append(row)
    pd.DataFrame(rows).to_parquet(abc / "recompressed_action_outcomes.parquet")

    pd.DataFrame([_feature_row("2025-01-06", "000004.SZ", "D")]).drop(
        columns=[
            "executable_entry",
            "complete_horizon",
            "entry_date",
            "formation_to_entry_gap",
            "window_min_return",
            "target_touched",
            "close_confirmed",
            "retain_3",
            "policy",
            "layer",
        ]
    ).to_parquet(d / "daily_attention.parquet")
    pd.DataFrame(
        [
            {
                "project_id": "d-1",
                "ts_code": "000004.SZ",
                "plan_date": pd.Timestamp("2025-01-06"),
                "entry_date": pd.Timestamp("2025-01-07"),
                "executable_entry": True,
                "action_price": 10.0,
            }
        ]
    ).to_parquet(d / "project_actions.parquet")
    d_paths = []
    for horizon in (20, 30):
        d_paths.append(
            {
                "project_id": "d-1",
                "ts_code": "000004.SZ",
                "formation_date": pd.Timestamp("2025-01-06"),
                "policy": "project_action",
                "horizon": horizon,
                "complete_horizon": True,
                "executable_entry": True,
                "entry_date": pd.Timestamp("2025-01-07"),
                "formation_to_entry_gap": 0.0,
                "window_min_return": -0.02,
                "target_touched": True,
                "close_confirmed": True,
                "retain_3": True,
            }
        )
    pd.DataFrame(d_paths).to_parquet(d / "action_paths.parquet")

    projects = build_development_projects(abc.parent, d.parent)
    assert projects.groupby(["block", "ts_code"]).size().max() == 1
    assert set(projects["block"]) == {"A", "B", "C", "D"}
    assert projects["action_date"].gt(projects["formation_date"]).all()


def _project_outcomes() -> pd.DataFrame:
    rows = []
    for index, success in enumerate((True, True, False, False)):
        row = _feature_row("2025-01-02", f"00000{index}.SZ")
        row.update(
            {
                "close_confirmed_20": success,
                "close_confirmed_30": success,
                "target_touched_20": success,
                "target_touched_30": success,
                "retain_3_20": success,
                "retain_3_30": success,
                "window_min_return_20": -0.05,
                "window_min_return_30": -0.06,
                "formation_to_entry_gap_20": 0.0,
                "formation_to_entry_gap_30": 0.0,
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def test_summarize_rule_reports_precision_and_winner_count() -> None:
    projects = _project_outcomes()
    metrics = summarize_rule(
        projects,
        pd.Series([True, True, True, False]),
        rule_id="candidate",
    )
    row = metrics[metrics["horizon"].eq(30)].iloc[0]
    assert row["precision_close"] == 2 / 3
    assert row["winner_count_close"] == 2
    assert row["baseline_winner_recall_close"] == 1.0


def test_pareto_status_rejects_accuracy_bought_by_missing_winners() -> None:
    projects = _project_outcomes()
    baseline = summarize_rule(
        projects, pd.Series(True, index=projects.index), rule_id="baseline"
    )
    better = summarize_rule(
        projects,
        pd.Series([True, True, False, False]),
        rule_id="better",
    )
    tradeoff = summarize_rule(
        projects,
        pd.Series([True, False, False, False]),
        rule_id="tradeoff",
    )
    assert pareto_status(better, baseline) == "pareto_improvement"
    assert pareto_status(tradeoff, baseline) == "tradeoff_only"


def test_candidate_masks_use_only_formation_features() -> None:
    from stock_analyzer.evaluation.v3_selection_accuracy_pareto import (
        candidate_keep_masks,
        run_diagnostics,
    )

    projects = _project_outcomes()
    projects.loc[0, "return_5d"] = 0.35
    projects.loc[1, "n_cashflow_act"] = -1.0
    feature_only = projects.drop(
        columns=[column for column in projects.columns if column.endswith(("_20", "_30"))]
    )
    masks = candidate_keep_masks(feature_only)
    assert "baseline" in masks
    assert "exclude_profit_cash_negative" in masks
    assert all(mask.index.equals(projects.index) for mask in masks.values())
    results = run_diagnostics(projects)
    assert {
        "diagnostic_bins",
        "rule_metrics",
        "pareto_frontier",
        "attempt_registry",
        "case_examples",
    } == set(results)
    assert set(results["attempt_registry"]["status"]).issubset(
        {"baseline", "pareto_improvement", "tradeoff_only", "dominated"}
    )


def test_report_states_development_only_and_honest_outcome(tmp_path: Path) -> None:
    metrics = summarize_rule(
        _project_outcomes(),
        pd.Series([True, True, False, False]),
        rule_id="candidate",
    )
    frontier = pd.DataFrame(
        [{"rule_id": "candidate", "status": "pareto_improvement"}]
    )
    registry = pd.DataFrame(
        [
            {
                "rule_id": "baseline",
                "status": "baseline",
                "kept_projects": 4,
                "excluded_projects": 0,
                "excluded_close_winners_20": 0,
                "excluded_close_winners_30": 0,
            },
            {
                "rule_id": "exclude_return_5d_top20pct",
                "status": "dominated",
                "kept_projects": 3,
                "excluded_projects": 1,
                "excluded_close_winners_20": 1,
                "excluded_close_winners_30": 1,
            },
        ]
    )
    report = generate_report(
        metrics, frontier, tmp_path / "report.md", registry=registry
    )
    text = report.read_text(encoding="utf-8")
    assert "A/B/C/D都是已揭示开发样本" in text
    assert "帕累托改进" in text
    assert "错过的后来赢家" in text
    assert "不是独立验证" in text
    assert "当前三项行动基线" in text
    assert "不能一刀切" in text
    assert "可以使用什么" in text
    assert "分时期稳定性" in text
