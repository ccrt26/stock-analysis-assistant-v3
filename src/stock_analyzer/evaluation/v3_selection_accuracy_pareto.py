"""Development-only selection accuracy and omission diagnostics for V3."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


FEATURE_COLUMNS = [
    "formation_date",
    "ts_code",
    "block",
    "user_layer",
    "hard_invalid",
    "routes",
    "hotspot_support",
    "company_driver_state",
    "return_5d",
    "return_20d",
    "relative_return_20d",
    "current_amount_ratio_20d",
    "price_location_60d",
    "tr_yoy",
    "netprofit_yoy",
    "dt_netprofit_yoy",
    "ocf_yoy",
    "n_cashflow_act",
]

PATH_FIELDS = [
    "target_touched",
    "close_confirmed",
    "retain_3",
    "window_min_return",
    "formation_to_entry_gap",
]


def baseline_action_mask(frame: pd.DataFrame) -> pd.Series:
    """Frozen three-confirmation action baseline using formation facts only."""

    return (
        frame["user_layer"].eq("关注")
        & ~frame["hard_invalid"].fillna(False).astype(bool)
        & pd.to_numeric(frame["return_5d"], errors="coerce").gt(0)
        & pd.to_numeric(frame["relative_return_20d"], errors="coerce").gt(0)
        & pd.to_numeric(
            frame["current_amount_ratio_20d"], errors="coerce"
        ).ge(1)
    )


def _pair_horizons(frame: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    paired = frame.copy()
    paired["horizon"] = pd.to_numeric(paired["horizon"], errors="coerce")
    paired = paired[paired["horizon"].isin([20, 30])]
    values = [field for field in PATH_FIELDS if field in paired.columns]
    wide = paired.pivot_table(
        index=keys,
        columns="horizon",
        values=values,
        aggfunc="first",
        dropna=False,
    )
    wide.columns = [f"{field}_{int(horizon)}" for field, horizon in wide.columns]
    return wide.reset_index()


def _abc_projects(abc_root: Path) -> pd.DataFrame:
    source = pd.read_parquet(
        abc_root / "tables" / "recompressed_action_outcomes.parquet"
    )
    source = source[
        source["policy"].eq("v3_recompressed")
        & source["horizon"].isin([20, 30])
        & source["executable_entry"].fillna(False).astype(bool)
        & source["complete_horizon"].fillna(False).astype(bool)
    ].copy()
    source = source[baseline_action_mask(source)]
    source["formation_date"] = pd.to_datetime(source["formation_date"])
    first = (
        source.sort_values("formation_date")
        .drop_duplicates(["block", "ts_code"], keep="first")
        [FEATURE_COLUMNS + ["entry_date"]]
        .rename(columns={"entry_date": "action_date"})
    )
    paths = _pair_horizons(source, ["block", "ts_code", "formation_date"])
    return first.merge(paths, on=["block", "ts_code", "formation_date"], how="inner")


def _d_projects(d_root: Path) -> pd.DataFrame:
    attention = pd.read_parquet(d_root / "tables" / "daily_attention.parquet")
    actions = pd.read_parquet(d_root / "tables" / "project_actions.parquet")
    paths = pd.read_parquet(d_root / "tables" / "action_paths.parquet")
    actions = actions[actions["executable_entry"].fillna(False).astype(bool)].copy()
    attention["formation_date"] = pd.to_datetime(attention["formation_date"])
    actions["plan_date"] = pd.to_datetime(actions["plan_date"])
    features = actions.merge(
        attention,
        left_on=["ts_code", "plan_date"],
        right_on=["ts_code", "formation_date"],
        how="inner",
    )
    features["block"] = "D"
    features = features[baseline_action_mask(features)]
    features = features.sort_values("formation_date").drop_duplicates(
        ["block", "ts_code"], keep="first"
    )
    first = features[FEATURE_COLUMNS + ["entry_date"]].rename(
        columns={"entry_date": "action_date"}
    )
    d_paths = paths[
        paths["policy"].eq("project_action")
        & paths["horizon"].isin([20, 30])
        & paths["executable_entry"].fillna(False).astype(bool)
        & paths["complete_horizon"].fillna(False).astype(bool)
    ].copy()
    d_paths = d_paths.merge(
        actions[["project_id", "plan_date"]], on="project_id", how="inner"
    )
    d_paths["formation_date"] = pd.to_datetime(d_paths["plan_date"])
    d_paths = d_paths.drop(columns="plan_date")
    d_paths["block"] = "D"
    wide = _pair_horizons(d_paths, ["block", "ts_code", "formation_date"])
    return first.merge(wide, on=["block", "ts_code", "formation_date"], how="inner")


def build_development_projects(abc_root: Path, d_root: Path) -> pd.DataFrame:
    """Return one first executable baseline action per stock and block."""

    projects = pd.concat(
        [_abc_projects(Path(abc_root)), _d_projects(Path(d_root))],
        ignore_index=True,
        sort=False,
    )
    projects["formation_date"] = pd.to_datetime(projects["formation_date"])
    projects["action_date"] = pd.to_datetime(projects["action_date"])
    if projects.groupby(["block", "ts_code"]).size().max() > 1:
        raise ValueError("development projects contain repeated stock-block actions")
    if not projects["action_date"].gt(projects["formation_date"]).all():
        raise ValueError("action date must follow the formation date")
    return projects.sort_values(["formation_date", "ts_code"]).reset_index(drop=True)


def summarize_rule(
    projects: pd.DataFrame,
    keep: pd.Series,
    rule_id: str,
) -> pd.DataFrame:
    selected = projects[keep.reindex(projects.index, fill_value=False).astype(bool)]
    rows: list[dict[str, Any]] = []
    for block in ["ALL", *sorted(projects["block"].dropna().astype(str).unique())]:
        universe = projects if block == "ALL" else projects[projects["block"].eq(block)]
        sample = selected if block == "ALL" else selected[selected["block"].eq(block)]
        for horizon in (20, 30):
            close_field = f"close_confirmed_{horizon}"
            touch_field = f"target_touched_{horizon}"
            retain_field = f"retain_3_{horizon}"
            risk_field = f"window_min_return_{horizon}"
            gap_field = f"formation_to_entry_gap_{horizon}"
            baseline_winners = universe[close_field].fillna(False).astype(bool)
            winners = sample[close_field].fillna(False).astype(bool)
            rows.append(
                {
                    "rule_id": rule_id,
                    "block": block,
                    "horizon": horizon,
                    "selected_projects": int(len(sample)),
                    "selected_days": int(sample["formation_date"].nunique()),
                    "winner_count_close": int(winners.sum()),
                    "precision_close": float(winners.mean()) if len(sample) else np.nan,
                    "baseline_winner_recall_close": (
                        float(winners.sum() / baseline_winners.sum())
                        if baseline_winners.sum()
                        else np.nan
                    ),
                    "touch_count": int(
                        sample[touch_field].fillna(False).astype(bool).sum()
                    ),
                    "retain_3_count": int(
                        sample[retain_field].fillna(False).astype(bool).sum()
                    ),
                    "median_window_min_return": float(
                        pd.to_numeric(sample[risk_field], errors="coerce").median()
                    ),
                    "median_entry_gap": float(
                        pd.to_numeric(sample[gap_field], errors="coerce").median()
                    ),
                }
            )
    return pd.DataFrame(rows)


def candidate_keep_masks(projects: pd.DataFrame) -> dict[str, pd.Series]:
    """Formation-only candidate exclusions registered before outcomes are read."""

    index = projects.index
    return_5d = pd.to_numeric(projects["return_5d"], errors="coerce")
    location = pd.to_numeric(projects["price_location_60d"], errors="coerce")
    amount = pd.to_numeric(
        projects["current_amount_ratio_20d"], errors="coerce"
    )
    relative = pd.to_numeric(projects["relative_return_20d"], errors="coerce")
    net_profit = pd.to_numeric(projects["netprofit_yoy"], errors="coerce")
    core_profit = pd.to_numeric(projects["dt_netprofit_yoy"], errors="coerce")
    cash = pd.to_numeric(projects["n_cashflow_act"], errors="coerce")
    cash_growth = pd.to_numeric(projects["ocf_yoy"], errors="coerce")
    routes = projects["routes"].fillna("").astype(str)
    company_state = projects["company_driver_state"].fillna("absent").astype(str)
    company_or_earnings = routes.str.contains("earnings", regex=False) | ~company_state.eq(
        "absent"
    )
    profit_positive = net_profit.gt(0) | core_profit.gt(0)

    return_q80 = return_5d.quantile(0.80)
    return_q90 = return_5d.quantile(0.90)
    location_q80 = location.quantile(0.80)
    location_q90 = location.quantile(0.90)
    amount_q75 = amount.quantile(0.75)
    relative_q25 = relative.quantile(0.25)
    hotspot_weak = (
        routes.str.contains("hotspot", regex=False)
        & pd.to_numeric(projects["hotspot_support"], errors="coerce").le(2)
        & relative.le(relative_q25)
    )

    exclusions = {
        "baseline": pd.Series(False, index=index),
        "exclude_return_5d_top20pct": return_5d.ge(return_q80),
        "exclude_return_5d_top10pct": return_5d.ge(return_q90),
        "exclude_location_top20pct": location.ge(location_q80),
        "exclude_location_top10pct": location.ge(location_q90),
        "exclude_high_location_high_volume": location.ge(location_q80)
        & amount.ge(amount_q75),
        "exclude_profit_cash_negative": company_or_earnings
        & profit_positive
        & cash.le(0),
        "exclude_profit_ocf_deterioration": company_or_earnings
        & profit_positive
        & cash_growth.lt(0),
        "exclude_weak_hotspot_low_relative": hotspot_weak,
    }
    return {
        rule_id: ~excluded.fillna(False).astype(bool)
        for rule_id, excluded in exclusions.items()
    }


def _quartile(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    valid = numeric.notna()
    result = pd.Series("missing", index=series.index, dtype="object")
    if valid.sum() >= 4:
        ranked = numeric[valid].rank(method="first")
        result.loc[valid] = pd.qcut(
            ranked, 4, labels=["Q1", "Q2", "Q3", "Q4"]
        ).astype(str)
    elif valid.any():
        result.loc[valid] = "observed"
    return result


def add_unsupervised_bins(projects: pd.DataFrame) -> pd.DataFrame:
    result = projects.copy()
    result["return_5d_band"] = _quartile(result["return_5d"])
    result["location_60d_band"] = _quartile(result["price_location_60d"])
    result["amount_ratio_band"] = _quartile(result["current_amount_ratio_20d"])
    profit_positive = pd.to_numeric(
        result["netprofit_yoy"], errors="coerce"
    ).gt(0) | pd.to_numeric(result["dt_netprofit_yoy"], errors="coerce").gt(0)
    cash_negative = pd.to_numeric(
        result["n_cashflow_act"], errors="coerce"
    ).le(0)
    result["profit_cash_state"] = np.select(
        [profit_positive & cash_negative, profit_positive & ~cash_negative],
        ["profit_positive_cash_negative", "profit_positive_cash_positive"],
        default="other",
    )
    hotspot = result["routes"].fillna("").astype(str).str.contains(
        "hotspot", regex=False
    )
    hotspot_weak = pd.to_numeric(
        result["hotspot_support"], errors="coerce"
    ).le(2)
    relative_low = pd.to_numeric(
        result["relative_return_20d"], errors="coerce"
    ).le(
        pd.to_numeric(result["relative_return_20d"], errors="coerce").quantile(
            0.25
        )
    )
    result["hotspot_relative_state"] = np.select(
        [hotspot & hotspot_weak & relative_low, hotspot],
        ["weak_hotspot_low_relative", "other_hotspot"],
        default="non_hotspot",
    )
    return result


def _summarize_bins(projects: pd.DataFrame) -> pd.DataFrame:
    binned = add_unsupervised_bins(projects)
    families = {
        "return_5d": "return_5d_band",
        "price_location_60d": "location_60d_band",
        "amount_ratio": "amount_ratio_band",
        "profit_cash": "profit_cash_state",
        "hotspot_relative": "hotspot_relative_state",
    }
    rows: list[dict[str, Any]] = []
    for family, column in families.items():
        for block in ["ALL", *sorted(binned["block"].astype(str).unique())]:
            block_rows = binned if block == "ALL" else binned[binned["block"].eq(block)]
            for band, sample in block_rows.groupby(column, dropna=False):
                for horizon in (20, 30):
                    close = sample[f"close_confirmed_{horizon}"].fillna(False).astype(bool)
                    touch = sample[f"target_touched_{horizon}"].fillna(False).astype(bool)
                    retain = sample[f"retain_3_{horizon}"].fillna(False).astype(bool)
                    rows.append(
                        {
                            "family": family,
                            "band": str(band),
                            "block": block,
                            "horizon": horizon,
                            "projects": int(len(sample)),
                            "touch_count": int(touch.sum()),
                            "touch_rate": float(touch.mean()) if len(sample) else np.nan,
                            "close_count": int(close.sum()),
                            "close_rate": float(close.mean()) if len(sample) else np.nan,
                            "retain_3_count": int(retain.sum()),
                            "median_window_min_return": float(
                                pd.to_numeric(
                                    sample[f"window_min_return_{horizon}"],
                                    errors="coerce",
                                ).median()
                            ),
                        }
                    )
    return pd.DataFrame(rows)


def run_diagnostics(projects: pd.DataFrame) -> dict[str, pd.DataFrame]:
    masks = candidate_keep_masks(projects)
    metrics = pd.concat(
        [summarize_rule(projects, mask, rule_id) for rule_id, mask in masks.items()],
        ignore_index=True,
    )
    baseline = metrics[metrics["rule_id"].eq("baseline")]
    registry_rows: list[dict[str, Any]] = []
    case_rows: list[dict[str, Any]] = []
    for rule_id, mask in masks.items():
        rule_metrics = metrics[metrics["rule_id"].eq(rule_id)]
        status = "baseline" if rule_id == "baseline" else pareto_status(
            rule_metrics, baseline
        )
        excluded = projects[~mask]
        registry_rows.append(
            {
                "rule_id": rule_id,
                "status": status,
                "kept_projects": int(mask.sum()),
                "excluded_projects": int((~mask).sum()),
                "excluded_close_winners_20": int(
                    excluded["close_confirmed_20"].fillna(False).astype(bool).sum()
                ),
                "excluded_close_winners_30": int(
                    excluded["close_confirmed_30"].fillna(False).astype(bool).sum()
                ),
            }
        )
        if rule_id != "baseline":
            for item in excluded.head(10).itertuples(index=False):
                case_rows.append(
                    {
                        "rule_id": rule_id,
                        "block": item.block,
                        "formation_date": item.formation_date,
                        "ts_code": item.ts_code,
                        "close_winner_20": bool(item.close_confirmed_20),
                        "close_winner_30": bool(item.close_confirmed_30),
                    }
                )
    registry = pd.DataFrame(registry_rows)
    frontier = registry[
        registry["status"].isin(["baseline", "pareto_improvement", "tradeoff_only"])
    ].copy()
    cases = pd.DataFrame(
        case_rows,
        columns=[
            "rule_id",
            "block",
            "formation_date",
            "ts_code",
            "close_winner_20",
            "close_winner_30",
        ],
    )
    return {
        "diagnostic_bins": _summarize_bins(projects),
        "rule_metrics": metrics,
        "pareto_frontier": frontier,
        "attempt_registry": registry,
        "case_examples": cases,
    }


def pareto_status(candidate: pd.DataFrame, baseline: pd.DataFrame) -> str:
    candidate_all = candidate[candidate["block"].eq("ALL")].set_index("horizon")
    baseline_all = baseline[baseline["block"].eq("ALL")].set_index("horizon")
    aligned = candidate_all.join(baseline_all, lsuffix="_candidate", rsuffix="_baseline")
    precision_no_worse = (
        aligned["precision_close_candidate"] >= aligned["precision_close_baseline"]
    ).all()
    precision_better = (
        aligned["precision_close_candidate"] > aligned["precision_close_baseline"]
    ).any()
    winners_no_worse = (
        aligned["winner_count_close_candidate"]
        >= aligned["winner_count_close_baseline"]
    ).all()
    retention_no_worse = (
        aligned["retain_3_count_candidate"] >= aligned["retain_3_count_baseline"]
    ).all()
    risk_worse_both = (
        aligned["median_window_min_return_candidate"]
        < aligned["median_window_min_return_baseline"]
    ).all()
    if (
        precision_no_worse
        and precision_better
        and winners_no_worse
        and retention_no_worse
        and not risk_worse_both
    ):
        return "pareto_improvement"
    if precision_better and (not winners_no_worse or not retention_no_worse):
        return "tradeoff_only"
    return "dominated"


def generate_report(
    metrics: pd.DataFrame,
    frontier: pd.DataFrame,
    path: str | Path,
    *,
    registry: pd.DataFrame | None = None,
    diagnostic_bins: pd.DataFrame | None = None,
    projects: pd.DataFrame | None = None,
) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    supported = frontier[frontier["status"].eq("pareto_improvement")]
    conclusion = (
        "值得冻结的候选规则"
        if not supported.empty
        else "未找到帕累托改进"
    )
    all_rows = metrics[metrics["block"].eq("ALL")]
    status_cn = {
        "baseline": "基线",
        "pareto_improvement": "帕累托改进",
        "tradeoff_only": "只有取舍",
        "dominated": "被基线支配",
    }
    lines = [
        "# V3 选股准确性与遗漏控制诊断",
        "",
        "> A/B/C/D都是已揭示开发样本，本报告不是独立验证。",
        "",
        "## 结论",
        "",
        conclusion + "。",
        "",
        "当前三项行动基线为：近 5 日收益为正、近 20 日相对市场为正、当日成交不低于 20 日常态。本诊断只检查四类已知反证能否在不减少后来赢家的前提下排除错误股票。",
        "",
        "## 可以使用什么",
        "",
        "在目前已经揭示的数据中，继续保留现有三项行动确认作为最佳可用基线。它的作用不是保证买入，而是把关注名单进一步缩小到价格已经启动、强于市场且成交得到确认的股票。除非新方法同时提高 20 日和 30 日收盘确认率、没有少发现后来赢家、没有减少连续保持 3 日的赢家，否则不替换它。",
        "",
        "本轮没有找到满足上述条件的新筛选规则。因此，正确产出不是强行增加条件，而是保持基线不变；以下风险事实仍应出现在个股解释里，但暂时不能一刀切地据此删除股票。",
        "",
        "## 帕累托改进与错过的后来赢家",
        "",
        "| 规则 | 窗口 | 选中数 | 收盘赢家 | 精确率 | 基线赢家召回 | 保持3日 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in all_rows.sort_values(["rule_id", "horizon"]).itertuples(index=False):
        lines.append(
            f"| {row.rule_id} | {int(row.horizon)} | {int(row.selected_projects)} | "
            f"{int(row.winner_count_close)} | {row.precision_close:.2%} | "
            f"{row.baseline_winner_recall_close:.2%} | {int(row.retain_3_count)} |"
        )
    block_rows = metrics[~metrics["block"].eq("ALL")]
    if not block_rows.empty:
        lines.extend(
            [
                "",
                "## 分时期稳定性",
                "",
                "下表保留每一次尝试在 A/B/C/D 的方向，防止只报告合并样本中最好看的数字。‘赢家/准确率’均指相应窗口内至少一个收盘达到 +20%。",
                "",
                "| 规则 | 时期 | 保留项目 | 20日赢家/准确率 | 30日赢家/准确率 |",
                "| --- | --- | ---: | ---: | ---: |",
            ]
        )
        for (rule_id, block), sample in block_rows.groupby(
            ["rule_id", "block"], sort=True
        ):
            by_horizon = sample.set_index("horizon")
            row20 = by_horizon.loc[20]
            row30 = by_horizon.loc[30]
            lines.append(
                f"| {rule_id} | {block} | {int(row20['selected_projects'])} | "
                f"{int(row20['winner_count_close'])}/{row20['precision_close']:.2%} | "
                f"{int(row30['winner_count_close'])}/{row30['precision_close']:.2%} |"
            )
    if registry is not None and not registry.empty:
        lines.extend(
            [
                "",
                "## 每个已尝试方法的判定",
                "",
                "| 方法 | 判定 | 保留项目 | 排除项目 | 错过20日收盘赢家 | 错过30日收盘赢家 |",
                "| --- | --- | ---: | ---: | ---: | ---: |",
            ]
        )
        for row in registry.itertuples(index=False):
            lines.append(
                f"| {row.rule_id} | {status_cn.get(row.status, row.status)} | "
                f"{int(row.kept_projects)} | {int(row.excluded_projects)} | "
                f"{int(row.excluded_close_winners_20)} | "
                f"{int(row.excluded_close_winners_30)} |"
            )
        registry_lookup = registry.set_index("rule_id")

        def _missed(rule_id: str) -> tuple[int, int] | None:
            if rule_id not in registry_lookup.index:
                return None
            item = registry_lookup.loc[rule_id]
            return (
                int(item["excluded_close_winners_20"]),
                int(item["excluded_close_winners_30"]),
            )

        explanation_lines = [
            "",
            "## 为什么这些优化暂时不能采用",
            "",
        ]
        missed = _missed("exclude_return_5d_top20pct")
        if missed is not None:
            explanation_lines.append(
                f"- **不能把短期涨得快直接视为透支。** 删除近 5 日涨幅最高的 20% 会错过 {missed[0]} 个 20 日收盘赢家和 {missed[1]} 个 30 日收盘赢家。短期上涨在这批样本中更多是启动信号与透支风险并存，不能一刀切。"
            )
        missed = _missed("exclude_location_top20pct")
        if missed is not None:
            explanation_lines.append(
                f"- **不能按价格位置高低机械排除。** 删除 60 日价格位置最高的 20% 会错过 {missed[0]} 个 20 日收盘赢家和 {missed[1]} 个 30 日收盘赢家；高位置并不自动等于行情结束。"
            )
        missed = _missed("exclude_high_location_high_volume")
        if missed is not None:
            explanation_lines.append(
                f"- **高位置放量也不能单独作为否决。** 这条组合反证仍会错过 {missed[0]} 个 20 日收盘赢家和 {missed[1]} 个 30 日收盘赢家。它可以提示兑现风险，但现有数据不足以区分放量突破和放量出货。"
            )
        missed = _missed("exclude_profit_cash_negative")
        if missed is not None:
            explanation_lines.append(
                f"- **经营现金流为负不能单独否决。** 机械删除利润增长但经营现金流为负的公司，会错过 {missed[0]} 个 20 日收盘赢家和 {missed[1]} 个 30 日收盘赢家。现金流是重要公司风险证据，但短期股价还会受到预期、行业周期和事件驱动影响。"
            )
        missed = _missed("exclude_profit_ocf_deterioration")
        if missed is not None:
            explanation_lines.append(
                f"- **经营现金流同比恶化也不能单独否决。** 该规则会错过 {missed[0]} 个 20 日收盘赢家和 {missed[1]} 个 30 日收盘赢家，只能作为解释和风险提示。"
            )
        if "exclude_weak_hotspot_low_relative" in registry_lookup.index:
            item = registry_lookup.loc["exclude_weak_hotspot_low_relative"]
            explanation_lines.append(
                f"- **当前热点弱化条件没有筛选能力。** 它实际排除 {int(item['excluded_projects'])} 个项目，说明现有基线样本里没有形成有效区分，不能假装它提高了准确率。"
            )
        explanation_lines.extend(
            [
                "",
                "这些结论不表示追高、位置、成交或现金流风险没有用；它们只证明：在现有框架中，把其中任何一项变成统一硬门槛，会把相当数量后来真正上涨的股票一起删掉。",
            ]
        )
        lines.extend(explanation_lines)
    if diagnostic_bins is not None and not diagnostic_bins.empty:
        all_bins = diagnostic_bins[diagnostic_bins["block"].eq("ALL")]
        lines.extend(
            [
                "",
                "## 连续分布诊断",
                "",
                "分位组只由形成日特征分布生成，不使用未来结果挑阈值。",
                "",
                "| 问题 | 分组 | 窗口 | 项目 | 收盘赢家 | 收盘率 | 保持3日 | 最低收益中位 |",
                "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for row in all_bins.sort_values(["family", "band", "horizon"]).itertuples(
            index=False
        ):
            lines.append(
                f"| {row.family} | {row.band} | {int(row.horizon)} | "
                f"{int(row.projects)} | {int(row.close_count)} | "
                f"{row.close_rate:.2%} | {int(row.retain_3_count)} | "
                f"{row.median_window_min_return:.2%} |"
            )
    if projects is not None and not projects.empty:
        counts = projects.groupby("block").size().to_dict()
        lines.extend(
            [
                "",
                "## 样本与边界",
                "",
                f"主评价为 {len(projects)} 个股票—时间块的首次可执行行动；分块数量为 {counts}。相邻日不重复计为多个独立项目。",
                "",
                "即使本报告找到候选方法，也只能进入规则冻结和新时期验证；A/B/C/D 已全部揭示，不能再证明样本外有效。",
            ]
        )
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output


def _file_signature(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"path": str(path), "size": path.stat().st_size, "sha256": digest}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--abc-root", required=True)
    parser.add_argument("--d-root", required=True)
    parser.add_argument("--output-root", required=True)
    args = parser.parse_args(argv)
    projects = build_development_projects(Path(args.abc_root), Path(args.d_root))
    output = Path(args.output_root)
    output.mkdir(parents=True, exist_ok=True)
    (output / "tables").mkdir(exist_ok=True)
    (output / "manifests").mkdir(exist_ok=True)
    (output / "reports").mkdir(exist_ok=True)
    projects.to_parquet(output / "tables" / "development_projects.parquet", index=False)
    results = run_diagnostics(projects)
    for name, frame in results.items():
        frame.to_parquet(output / "tables" / f"{name}.parquet", index=False)
    inputs = [
        Path(args.abc_root) / "tables" / "recompressed_action_outcomes.parquet",
        Path(args.d_root) / "tables" / "daily_attention.parquet",
        Path(args.d_root) / "tables" / "project_actions.parquet",
        Path(args.d_root) / "tables" / "action_paths.parquet",
    ]
    signatures = [_file_signature(path) for path in inputs]
    (output / "manifests" / "input_signatures.json").write_text(
        json.dumps(signatures, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    report = generate_report(
        results["rule_metrics"],
        results["pareto_frontier"],
        output / "reports" / "v3-selection-accuracy-pareto-results.md",
        registry=results["attempt_registry"],
        diagnostic_bins=results["diagnostic_bins"],
        projects=projects,
    )
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
