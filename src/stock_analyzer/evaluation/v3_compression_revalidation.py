"""Revalidate a simplified V3 research-pool compression policy.

The user sees one unranked ``关注`` list. Research roles and comparison
controls remain internal audit fields.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import shutil
import sys
import time

import numpy as np
import pandas as pd
import yaml

from stock_analyzer.evaluation.v3_next_day_entry_validation import (
    summarize_actions,
    validate_action_contracts,
)
from stock_analyzer.evaluation.v3_target_retention_diagnostic import (
    _file_manifest,
    _tree_signature,
    _write_json,
    _write_parquet,
)


FINANCIAL_FIELDS = (
    "tr_yoy",
    "netprofit_yoy",
    "dt_netprofit_yoy",
    "n_cashflow_act",
)

LANE_DIMENSIONS = {
    "focus_candidate": (
        "evidence_freshness",
        "earnings_cash_consistency",
        "hotspot_support",
        "price_consumption_safety",
        "liquidity",
    ),
    "company_observation": (
        "evidence_freshness",
        "earnings_cash_consistency",
        "hotspot_support",
        "price_consumption_safety",
        "liquidity",
    ),
    "elasticity_observation": (
        "hotspot_support",
        "price_consumption_safety",
        "liquidity",
    ),
}

USER_LAYERS = ("关注",)
DEFAULT_ALLOWED_VOLUME_ROOT = Path("/Volumes/ZHUTONG")


@dataclass(frozen=True)
class CompressionConfig:
    experiment_id: str
    source_layered_root: Path
    source_action_root: Path
    output_root: Path
    blocks: tuple[str, ...]
    horizons: tuple[int, ...]
    candidate_cap: int
    focus_cap: int
    user_layers: tuple[str, ...]
    runtime_stop_minutes: int


def load_config(path: str | Path) -> CompressionConfig:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("compression config must be a mapping")
    config = CompressionConfig(
        experiment_id=str(payload["experiment_id"]),
        source_layered_root=Path(payload["source_layered_root"]),
        source_action_root=Path(payload["source_action_root"]),
        output_root=Path(payload["output_root"]),
        blocks=tuple(str(value) for value in payload["blocks"]),
        horizons=tuple(int(value) for value in payload["horizons"]),
        candidate_cap=int(payload["candidate_cap"]),
        focus_cap=int(payload["focus_cap"]),
        user_layers=tuple(str(value) for value in payload["user_layers"]),
        runtime_stop_minutes=int(payload["runtime_stop_minutes"]),
    )
    if config.blocks != ("A", "B", "C") or config.horizons != (20, 30):
        raise ValueError("必须保留冻结的A/B/C区间和20/30日窗口")
    if config.candidate_cap != 10 or config.focus_cap != 5:
        raise ValueError("名单上限必须保持10只；历史重点上限字段保持5以便对照")
    if config.user_layers != USER_LAYERS:
        raise ValueError("用户输出只能是一个关注名单")
    if config.runtime_stop_minutes <= 0:
        raise ValueError("运行时间上限必须为正")
    return config


def prepare_output_root(
    config: CompressionConfig,
    *,
    output_override: str | Path | None = None,
    allowed_volume_root: str | Path = DEFAULT_ALLOWED_VOLUME_ROOT,
) -> Path:
    output = Path(output_override) if output_override is not None else config.output_root
    expected = Path(allowed_volume_root) / "股票分析助手-V3回测" / config.experiment_id
    if output.resolve(strict=False) != expected.resolve(strict=False):
        raise ValueError("输出路径必须是冻结的U盘专用目录")
    if output.resolve(strict=False) in {
        config.source_layered_root.resolve(strict=False),
        config.source_action_root.resolve(strict=False),
    }:
        raise ValueError("输出目录不得覆盖来源实验")
    for child in ("manifests", "tables", "reports"):
        (output / child).mkdir(parents=True, exist_ok=True)
    return output


def derive_company_driver_state(row: pd.Series) -> str:
    """Derive an auditable company-evidence state from frozen formation facts."""

    if bool(row.get("hard_invalid", False)):
        return "excluded"
    if bool(row.get("company_evidence", False)):
        return "confirmed"
    has_report = pd.notna(row.get("report_period"))
    has_directional_support = any(
        pd.notna(row.get(field)) and float(row.get(field)) > 0
        for field in FINANCIAL_FIELDS
    )
    if has_report and has_directional_support:
        return "partial"
    return "absent"


def _pareto_order(frame: pd.DataFrame, dimensions: tuple[str, ...]) -> list[int]:
    """Return successive Pareto fronts while preserving frozen upstream order."""

    remaining = list(frame.index)
    ordered: list[int] = []
    while remaining:
        frontier: list[int] = []
        for index in remaining:
            values = frame.loc[index, list(dimensions)].astype(float)
            dominated = any(
                bool(
                    (
                        frame.loc[other, list(dimensions)].astype(float)
                        >= values
                    ).all()
                )
                and bool(
                    (
                        frame.loc[other, list(dimensions)].astype(float)
                        > values
                    ).any()
                )
                for other in remaining
                if other != index
            )
            if not dominated:
                frontier.append(index)
        frontier.sort()
        ordered.extend(frontier)
        remaining = [item for item in remaining if item not in frontier]
    return ordered


def _pareto_front(frame: pd.DataFrame, dimensions: tuple[str, ...]) -> list[int]:
    """Return only the first non-dominated front; lower fronts are not fillers."""

    if frame.empty:
        return []
    ordered = _pareto_order(frame, dimensions)
    frontier: list[int] = []
    for index in ordered:
        values = frame.loc[index, list(dimensions)].astype(float)
        dominated = any(
            bool((frame.loc[other, list(dimensions)].astype(float) >= values).all())
            and bool((frame.loc[other, list(dimensions)].astype(float) > values).any())
            for other in frame.index
            if other != index
        )
        if not dominated:
            frontier.append(index)
    return frontier


def compress_decision_list(
    evidence: pd.DataFrame,
    *,
    candidate_cap: int = 10,
    focus_cap: int = 5,
) -> pd.DataFrame:
    """Compress one formation day's research evidence into two user layers."""

    if candidate_cap <= 0 or focus_cap < 0 or focus_cap > candidate_cap:
        raise ValueError("invalid capacity relationship")
    required = {
        "formation_date",
        "ts_code",
        "routes",
        "company_evidence",
        "hard_invalid",
        "report_period",
        *FINANCIAL_FIELDS,
        *{column for dimensions in LANE_DIMENSIONS.values() for column in dimensions},
    }
    missing = sorted(required - set(evidence.columns))
    if missing:
        raise ValueError(f"candidate evidence lacks fields: {', '.join(missing)}")

    prepared = evidence.copy().reset_index(drop=True)
    if prepared.duplicated(["formation_date", "ts_code"]).any():
        raise ValueError("candidate evidence contains duplicate stock-date rows")
    for column in {item for values in LANE_DIMENSIONS.values() for item in values}:
        prepared[column] = pd.to_numeric(prepared[column], errors="raise")

    prepared["company_driver_state"] = prepared.apply(
        derive_company_driver_state,
        axis=1,
    )
    prepared["internal_lane"] = np.select(
        [
            prepared["company_driver_state"].eq("confirmed"),
            prepared["company_driver_state"].eq("partial"),
        ],
        ["focus_candidate", "company_observation"],
        default="elasticity_observation",
    )
    prepared["user_layer"] = "不展示"
    prepared["decision_reason"] = "capacity_or_evidence_not_selected"
    prepared.loc[
        prepared["hard_invalid"].astype(bool),
        "decision_reason",
    ] = "hard_invalidation"

    eligible = prepared[~prepared["hard_invalid"].astype(bool)]
    confirmed_front = _pareto_front(
        eligible[eligible["internal_lane"].eq("focus_candidate")],
        LANE_DIMENSIONS["focus_candidate"],
    )
    partial = eligible[eligible["internal_lane"].eq("company_observation")]
    partial_front = _pareto_front(
        partial,
        LANE_DIMENSIONS["company_observation"],
    )
    absent = eligible[eligible["internal_lane"].eq("elasticity_observation")]
    overconsumed = absent["price_consumption_safety"].lt(2)
    prepared.loc[
        absent.index[overconsumed],
        "decision_reason",
    ] = "insufficient_current_action_value"
    safe_absent = absent[~overconsumed]
    elasticity_front = _pareto_front(
        safe_absent,
        LANE_DIMENSIONS["elasticity_observation"],
    )
    attention_pool = sorted(
        set(confirmed_front + partial_front + elasticity_front)
    )
    attention = attention_pool[:candidate_cap]
    prepared.loc[attention, "user_layer"] = "关注"
    prepared.loc[
        attention,
        "decision_reason",
    ] = "non_dominated_attention_candidate"
    return prepared


def validate_decision_contracts(
    decisions: pd.DataFrame,
    *,
    candidate_cap: int,
    focus_cap: int,
    user_layers: tuple[str, ...] = USER_LAYERS,
) -> dict[str, bool]:
    selected = decisions[decisions["user_layer"].isin(user_layers)].copy()
    daily_total = selected.groupby("formation_date").size()
    checks = {
        "daily_candidate_cap": bool(daily_total.empty or daily_total.max() <= candidate_cap),
        "single_user_layer": bool(set(selected["user_layer"].unique()) <= set(user_layers)),
        "selected_layers_only": bool(set(selected["user_layer"].unique()) <= set(user_layers)),
        "no_hard_invalid_selected": bool(
            selected.empty or not selected["hard_invalid"].astype(bool).any()
        ),
        "no_duplicate_stock_date": bool(
            not decisions.duplicated(["formation_date", "ts_code"]).any()
        ),
    }
    if not all(checks.values()):
        raise ValueError("recompressed decisions violate frozen contracts")
    return checks


def build_recompressed_outcomes(
    config: CompressionConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, list[Path]]:
    """Join recompressed daily decisions to frozen next-open action paths."""

    evidence_files = sorted(
        config.source_layered_root.glob(
            "tables/formations/block=*/formation_date=*/evidence.parquet"
        )
    )
    if len(evidence_files) != 90:
        raise ValueError("必须读取冻结的90个形成日证据")
    decision_frames: list[pd.DataFrame] = []
    for path in evidence_files:
        frame = compress_decision_list(
            pd.read_parquet(path),
            candidate_cap=config.candidate_cap,
            focus_cap=config.focus_cap,
        )
        frame["block"] = path.parent.parent.name.split("=", maxsplit=1)[1]
        decision_frames.append(frame)
    decisions = pd.concat(decision_frames, ignore_index=True)
    decisions["formation_date"] = pd.to_datetime(
        decisions["formation_date"], errors="raise"
    ).dt.normalize()

    selected = decisions[decisions["user_layer"].isin(config.user_layers)].copy()
    selected["policy"] = "v3_recompressed"
    paths_file = config.source_action_root / "tables" / "unique_action_paths.parquet"
    paths = pd.read_parquet(paths_file)
    paths["formation_date"] = pd.to_datetime(
        paths["formation_date"], errors="raise"
    ).dt.normalize()
    paths = paths[paths["horizon"].isin(config.horizons)].copy()
    outcomes = selected.merge(
        paths,
        on=["block", "formation_date", "ts_code"],
        how="left",
        validate="one_to_many",
    )
    outcomes["layer"] = outcomes["user_layer"]
    if outcomes.empty or outcomes["horizon"].isna().any():
        raise ValueError("新名单未完整连接到次日行动路径")
    return decisions, outcomes, [*evidence_files, paths_file]


COMPARISON_METRICS = (
    "touch_yield_all_plans",
    "close_yield_all_plans",
    "retain_3_yield_all_plans",
    "median_window_min_return",
)


def _summary_value(
    summary: pd.DataFrame,
    *,
    block: str,
    policy: str,
    layer: str,
    horizon: int,
    metric: str,
) -> float:
    found = summary[
        summary["block"].eq(block)
        & summary["policy"].eq(policy)
        & summary["layer"].eq(layer)
        & summary["horizon"].eq(horizon)
    ]
    if len(found) != 1:
        return np.nan
    return float(found.iloc[0][metric])


def build_comparison_metrics(summary: pd.DataFrame) -> pd.DataFrame:
    """Build new/old/research comparisons without combining them into a score."""

    rows: list[dict[str, object]] = []
    for block in ("A", "B", "C", "ALL"):
        for horizon in (20, 30):
            for metric in COMPARISON_METRICS:
                rows.append(
                    {
                        "block": block,
                        "horizon": horizon,
                        "metric": metric,
                        "new": _summary_value(
                            summary,
                            block=block,
                            policy="v3_recompressed",
                            layer="all",
                            horizon=horizon,
                            metric=metric,
                        ),
                        "old": _summary_value(
                            summary,
                            block=block,
                            policy="v3_partial_candidate",
                            layer="all",
                            horizon=horizon,
                            metric=metric,
                        ),
                        "research": _summary_value(
                            summary,
                            block=block,
                            policy="research_union",
                            layer="all",
                            horizon=horizon,
                            metric=metric,
                        ),
                    }
                )
    return pd.DataFrame(rows)


def evaluate_acceptance(
    comparisons: pd.DataFrame,
) -> dict[str, bool]:
    """Evaluate frozen business checks separately from technical quality checks."""

    core_metrics = ("touch_yield_all_plans", "close_yield_all_plans")
    core_all = comparisons[
        comparisons["block"].eq("ALL")
        & comparisons["metric"].isin(core_metrics)
    ].copy()
    expected_pairs = {
        (horizon, metric)
        for horizon in (20, 30)
        for metric in core_metrics
    }
    actual_pairs = set(zip(core_all["horizon"], core_all["metric"], strict=False))
    core_complete = actual_pairs == expected_pairs and core_all[
        ["new", "old", "research"]
    ].notna().all().all()
    new_not_below_old = bool(
        core_complete and (core_all["new"] >= core_all["old"]).all()
    )
    compression_loss_shrunk = bool(
        core_complete
        and (
            (core_all["research"] - core_all["new"])
            < (core_all["research"] - core_all["old"])
        ).all()
    )

    retain = comparisons[
        comparisons["block"].eq("ALL")
        & comparisons["metric"].eq("retain_3_yield_all_plans")
    ]
    risk = comparisons[
        comparisons["block"].eq("ALL")
        & comparisons["metric"].eq("median_window_min_return")
    ]
    retention_not_worse = bool(
        len(retain) == 2 and not (retain["new"] < retain["old"]).all()
    )
    path_risk_not_worse = bool(
        len(risk) == 2 and not (risk["new"] < risk["old"]).all()
    )

    block_core = comparisons[
        comparisons["block"].isin(["A", "B", "C"])
        & comparisons["metric"].isin(core_metrics)
    ].copy()
    all_block_losses = block_core.groupby(["horizon", "metric"]).apply(
        lambda frame: bool((frame["new"] < frame["research"]).all()),
        include_groups=False,
    )
    not_all_blocks_lose = bool(
        len(all_block_losses) == 4 and not all_block_losses.any()
    )
    checks = {
        "both_horizons_and_core_metrics_present": bool(core_complete),
        "new_not_below_old_touch_and_close": new_not_below_old,
        "research_compression_loss_shrunk": compression_loss_shrunk,
        "retention_not_worse_both_horizons": retention_not_worse,
        "path_risk_not_worse_both_horizons": path_risk_not_worse,
        "not_all_blocks_lose_to_research": not_all_blocks_lose,
    }
    checks["all_acceptance_passed"] = all(checks.values())
    return checks


def _fmt_pct(value: object) -> str:
    return "—" if pd.isna(value) else f"{float(value) * 100:.2f}%"


def generate_report(
    summary: pd.DataFrame,
    comparisons: pd.DataFrame,
    acceptance: dict[str, bool],
    path: str | Path,
) -> Path:
    """Write a decision-first report with controls confined to the appendix."""

    report_path = Path(path)
    outcome = "通过本轮压缩验收" if acceptance.get("all_acceptance_passed") else "未通过本轮压缩验收"
    lines = [
        "# V3 压缩优化重算报告",
        "",
        "## 给用户的直接结论",
        "",
        f"- **结论：{outcome}。** 每日只显示一个“关注名单”，最多 10 只，不排名、不凑数。",
        "- 每只股票只回答三个决策问题：为什么现在关注、还缺什么确认、什么事实出现就不再关注。",
        "",
        "| 名单 | 窗口 | 计划数 | 盘中达到 | 收盘确认 | 严格保持3日 | 窗口最低收益中位 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    user_rows = summary[
        summary["block"].eq("ALL")
        & summary["policy"].eq("v3_recompressed")
        & summary["layer"].eq("all")
    ].sort_values(["horizon", "layer"])
    labels = {"all": "关注名单"}
    for row in user_rows.itertuples(index=False):
        lines.append(
            "| "
            + " | ".join(
                [
                    labels[str(row.layer)],
                    str(int(row.horizon)),
                    str(int(row.planned_actions)),
                    f"{int(row.touch_successes)}（{_fmt_pct(row.touch_yield_all_plans)}）",
                    f"{int(row.close_successes)}（{_fmt_pct(row.close_yield_all_plans)}）",
                    f"{int(row.retain_3_successes)}（{_fmt_pct(row.retain_3_yield_all_plans)}）",
                    _fmt_pct(row.median_window_min_return),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## 为什么发生变化",
            "",
            "- 五项财务事实全满足不再是进入每日十只的统一硬门。",
            "- 部分公司依据和只有市场价格弹性的对象都必须通过各自同类比较；符合条件时进入同一个关注名单。",
            "- 现有证据不能稳定证明额外优先分层有效，因此按框架预登记边界取消该分类。",
            "- 财务事实继续用于解释经营质量和风险，不按满足数量打分。",
            "",
            "## 验收结果",
            "",
        ]
    )
    for name, passed in acceptance.items():
        lines.append(f"- `{name}`：{'通过' if passed else '未通过'}")
    lines.extend(
        [
            "",
            "## 技术附录",
            "",
            "研究池和比对组只在本节出现，用于检验压缩是否真正改善，不属于用户候选名单。",
            "",
            "| 区段 | 窗口 | 指标 | 新压缩 | 旧压缩 | 研究池 |",
            "| --- | ---: | --- | ---: | ---: | ---: |",
        ]
    )
    for row in comparisons.itertuples(index=False):
        lines.append(
            f"| {row.block} | {int(row.horizon)} | {row.metric} | "
            f"{_fmt_pct(row.new)} | {_fmt_pct(row.old)} | {_fmt_pct(row.research)} |"
        )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path


def _decision_examples(
    decisions: pd.DataFrame,
    outcomes: pd.DataFrame,
) -> pd.DataFrame:
    columns = [
        "block",
        "formation_date",
        "ts_code",
        "user_layer",
        "company_driver_state",
        "internal_lane",
        "routes",
        "decision_reason",
    ]
    selected = decisions[decisions["user_layer"].isin(USER_LAYERS)][columns]
    action = outcomes[
        outcomes["horizon"].eq(30)
    ][
        [
            "block",
            "formation_date",
            "ts_code",
            "target_touched",
            "close_confirmed",
            "retain_3",
            "window_min_return",
        ]
    ]
    merged = selected.merge(
        action,
        on=["block", "formation_date", "ts_code"],
        how="left",
        validate="one_to_one",
    )
    return merged.sort_values(
        ["user_layer", "close_confirmed", "window_min_return"],
        ascending=[True, False, True],
        na_position="last",
    ).groupby("user_layer", group_keys=False).head(20).reset_index(drop=True)


def run_revalidation(config: CompressionConfig) -> Path:
    started = time.perf_counter()
    output = prepare_output_root(config)
    source_layered_before = _tree_signature(config.source_layered_root)
    source_action_before = _tree_signature(config.source_action_root)

    decisions, new_outcomes, input_paths = build_recompressed_outcomes(config)
    decision_contracts = validate_decision_contracts(
        decisions,
        candidate_cap=config.candidate_cap,
        focus_cap=config.focus_cap,
        user_layers=config.user_layers,
    )
    action_contracts = validate_action_contracts(new_outcomes)

    source_actions_path = (
        config.source_action_root / "tables" / "selection_action_outcomes.parquet"
    )
    source_actions = pd.read_parquet(source_actions_path)
    old_and_research = source_actions[
        source_actions["policy"].isin(
            ["v3_partial_candidate", "research_union"]
        )
    ].copy()
    combined = pd.concat([new_outcomes, old_and_research], ignore_index=True)
    summary = summarize_actions(
        combined,
        supported_policies=(
            "v3_recompressed",
            "v3_partial_candidate",
            "research_union",
        ),
    )
    comparisons = build_comparison_metrics(summary)
    acceptance = evaluate_acceptance(
        comparisons,
    )
    examples = _decision_examples(decisions, new_outcomes)

    _write_parquet(decisions, output / "tables" / "recompressed_decisions.parquet")
    _write_parquet(
        new_outcomes,
        output / "tables" / "recompressed_action_outcomes.parquet",
    )
    _write_parquet(summary, output / "tables" / "summary_metrics.parquet")
    _write_parquet(comparisons, output / "tables" / "comparison_metrics.parquet")
    _write_parquet(examples, output / "tables" / "decision_examples.parquet")
    _write_parquet(
        pd.DataFrame(
            [{"check": name, "passed": passed} for name, passed in acceptance.items()]
        ),
        output / "tables" / "acceptance_checks.parquet",
    )

    report_path = generate_report(
        summary,
        comparisons,
        acceptance,
        output / "reports" / "v3-compression-revalidation-results.md",
    )
    source_layered_after = _tree_signature(config.source_layered_root)
    source_action_after = _tree_signature(config.source_action_root)
    runtime_seconds = time.perf_counter() - started
    selected = decisions[decisions["user_layer"].isin(config.user_layers)]
    formation_counts = {
        block: int(
            decisions.loc[decisions["block"].eq(block), "formation_date"].nunique()
        )
        for block in config.blocks
    }
    quality: dict[str, object] = {
        "formation_dates_90": int(decisions["formation_date"].nunique()) == 90,
        "blocks_30_each": formation_counts == {"A": 30, "B": 30, "C": 30},
        **decision_contracts,
        **action_contracts,
        "selected_user_layers_exact": set(selected["user_layer"].unique())
        == set(config.user_layers),
        "summary_nonempty": not summary.empty,
        "comparisons_complete": bool(
            len(comparisons) == 4 * 2 * len(COMPARISON_METRICS)
            and comparisons[["new", "old", "research"]].notna().all().all()
        ),
        "source_layered_unchanged": source_layered_before["signature_sha256"]
        == source_layered_after["signature_sha256"],
        "source_action_unchanged": source_action_before["signature_sha256"]
        == source_action_after["signature_sha256"],
        "runtime_within_limit": runtime_seconds
        <= config.runtime_stop_minutes * 60,
        "runtime_seconds": runtime_seconds,
        "formation_date_counts": formation_counts,
        "research_evidence_rows": int(len(decisions)),
        "selected_stock_date_rows": int(len(selected)),
        "action_outcome_rows": int(len(new_outcomes)),
        "max_daily_candidates": int(selected.groupby("formation_date").size().max()),
        "source_layered_signature_before": source_layered_before,
        "source_layered_signature_after": source_layered_after,
        "source_action_signature_before": source_action_before,
        "source_action_signature_after": source_action_after,
    }
    boolean_checks = [value for value in quality.values() if isinstance(value, bool)]
    quality["all_passed"] = bool(boolean_checks and all(boolean_checks))
    quality["business_acceptance_passed"] = acceptance["all_acceptance_passed"]

    _write_json(
        {
            "experiment_id": config.experiment_id,
            "goal": "reduce known research-pool compression loss while showing users one attention list",
            "source_layered_root": str(config.source_layered_root),
            "source_action_root": str(config.source_action_root),
            "output_root": str(config.output_root),
            "blocks": list(config.blocks),
            "horizons": list(config.horizons),
            "candidate_cap": config.candidate_cap,
            "focus_cap": config.focus_cap,
            "user_layers": list(config.user_layers),
            "runtime_stop_minutes": config.runtime_stop_minutes,
            "usb_free_bytes_after": shutil.disk_usage(output).free,
        },
        output / "manifests" / "config_snapshot.json",
    )
    _write_json(quality, output / "manifests" / "quality_checks.json")
    _write_json(
        {"acceptance": acceptance},
        output / "manifests" / "acceptance_checks.json",
    )
    _write_json(
        {"inputs": _file_manifest([*input_paths, source_actions_path])},
        output / "manifests" / "input_manifest.json",
    )
    _write_json(
        {
            "status": "completed"
            if quality["all_passed"]
            else "failed_quality_checks",
            "business_acceptance": "passed"
            if acceptance["all_acceptance_passed"]
            else "failed",
            "report": str(report_path),
            "runtime_seconds": runtime_seconds,
        },
        output / "manifests" / "run_status.json",
    )
    if not quality["all_passed"]:
        raise RuntimeError("compression revalidation failed technical quality checks")
    return report_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    args = parser.parse_args(argv)
    report = run_revalidation(load_config(args.config))
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
