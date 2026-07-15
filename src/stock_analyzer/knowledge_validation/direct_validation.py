from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
import json
from pathlib import Path

import duckdb
import pandas as pd

from stock_analyzer.data.research_contracts import ResearchDatasetId


CALCULATION_NAMES = (
    "size_value",
    "short_reversal",
    "common_factor_momentum",
    "daily_event_method",
    "earnings_reaction",
    "formal_announcement_shocks",
    "financial_improvement",
)


@dataclass(frozen=True)
class KnowledgeClaim:
    legacy_id: str
    target_ids: tuple[str, ...]
    calculations: tuple[str, ...]
    core_theory: str
    required_facts: tuple[ResearchDatasetId, ...]


@dataclass(frozen=True)
class HistoricalEvidence:
    legacy_id: str
    calculations: tuple[str, ...]
    data_usable: bool
    overall_direction: str
    earlier_direction: str
    later_direction: str
    relationship_shape: str
    main_drivers: str
    counter_evidence: str
    observations: dict[str, int | float | str]


_PRICE_FACTS = (
    ResearchDatasetId.EQUITY_DAILY,
    ResearchDatasetId.ADJ_FACTOR,
    ResearchDatasetId.INDEX_DAILY,
)
_EVENT_FACTS = (ResearchDatasetId.ANNOUNCEMENT,) + _PRICE_FACTS
_FINANCIAL_FACTS = (
    ResearchDatasetId.INCOME_STATEMENT,
    ResearchDatasetId.BALANCE_SHEET,
    ResearchDatasetId.CASH_FLOW,
    ResearchDatasetId.FINANCIAL_INDICATOR,
) + _PRICE_FACTS


CLAIMS = (
    KnowledgeClaim(
        "src_fama_french_1992",
        ("src_liu_stambaugh_yuan_2019",),
        ("size_value",),
        "在美国股票样本中，公司规模与账面市值比共同解释平均收益的横截面差异；控制规模后市场贝塔与平均收益的关系很弱。这是特定市场和样本期的经验关系，不能把美国分组、幅度或低估值直接当成A股上涨保证。",
        _PRICE_FACTS + (ResearchDatasetId.DAILY_BASIC,),
    ),
    KnowledgeClaim(
        "src_liu_stambaugh_yuan_2019",
        ("src_liu_stambaugh_yuan_2019",),
        ("size_value",),
        "在论文所研究的A股时期，规模和价值与平均收益差异有关；但最小市值股票受到壳价值影响，剔除这部分后，盈利市值比比账面市值比更适合表达本地价值关系。该结论要求盈利可比，不能继承论文的固定剔除比例和收益幅度。",
        _PRICE_FACTS + (ResearchDatasetId.DAILY_BASIC,),
    ),
    KnowledgeClaim(
        "src_jegadeesh_titman_1993",
        ("src_cn_t1_contrarian_2024", "src_cn_factor_momentum_2023"),
        ("short_reversal", "common_factor_momentum"),
        "在美国样本中，买入过去赢家并卖出过去输家的组合在随后3至12个月取得正收益，且论文认为该结果不能由系统性风险或对共同因子的延迟反应解释；组合形成后第一年的部分收益在随后两年回吐。该期限与方向不能直接移植到A股。",
        _PRICE_FACTS + (ResearchDatasetId.INDUSTRY_MEMBER,),
    ),
    KnowledgeClaim(
        "src_ball_brown_1968",
        ("src_sun_wen_earnings_car_2023",),
        ("earnings_reaction",),
        "年度会计盈余包含与公司价值有关的信息：非预期盈余方向与市场调整后的异常收益方向相关，且大量信息在正式公告前已进入价格，公告附近仍有反应。该研究说明会计盈余具有信息含量，并不等于公告后价格必然继续上涨。",
        _EVENT_FACTS + (ResearchDatasetId.FINANCIAL_INDICATOR,),
    ),
    KnowledgeClaim(
        "src_dechow_ge_schrand_2010",
        ("src_piotroski_2000",),
        ("financial_improvement",),
        "盈余质量没有脱离用途的单一指标；持续性、应计、平滑、及时性和外部重述等代理各自回答不同问题，质量还取决于决策情境与公司的基本经营表现。因此分析必须拆看现金实现和持续性，不能用一个总分替代。",
        _FINANCIAL_FACTS,
    ),
    KnowledgeClaim(
        "src_sloan_1996",
        ("src_piotroski_2000",),
        ("financial_improvement",),
        "当前盈余中现金流成分通常比应计成分具有更高的未来盈余持续性，而股票价格可能没有及时区分二者，直到其对未来盈余的影响出现。核心是应计与现金流的相对持续性，不是现金流单独增长就保证股价上涨。",
        _FINANCIAL_FACTS,
    ),
    KnowledgeClaim(
        "src_piotroski_2000",
        ("src_piotroski_2000",),
        ("financial_improvement",),
        "在美国高账面市值比公司这一特定价值股范围内，利用盈利、现金流、杠杆、流动性和经营效率等历史财务信号，可以在统计意义上区分后续赢家与输家。原始九项财务信号和价值股前提不能直接变成A股固定评分。",
        _FINANCIAL_FACTS,
    ),
    KnowledgeClaim(
        "src_novy_marx_2013",
        ("src_liu_stambaugh_yuan_2019", "src_piotroski_2000"),
        ("size_value", "financial_improvement"),
        "在美国样本中，以毛利润除以总资产衡量的毛利能力，对平均收益横截面的预测力可与账面市值比相比；在控制估值后，毛利能力仍能补充价值判断。该关系不是毛利率越高股价就必涨，也不能脱离估值和行业可比性。",
        _FINANCIAL_FACTS + (ResearchDatasetId.DAILY_BASIC,),
    ),
    KnowledgeClaim(
        "src_fama_fisher_jensen_roll_1969",
        ("src_brown_warner_1985",),
        ("daily_event_method",),
        "以拆股为特定事件，先扣除市场共同变化得到残差收益，再把不同公司的事件时间对齐，可以观察价格对新信息的调整过程。该事件研究方法分离市场背景，但拆股样本结论不能证明其他事件具有同样反应或因果效果。",
        _EVENT_FACTS,
    ),
    KnowledgeClaim(
        "src_brown_warner_1985",
        ("src_brown_warner_1985",),
        ("daily_event_method",),
        "日收益通常可以用于事件研究，常见方法在许多情形下具有良好设定；但日度异常收益的自相关、事件发生时方差变化和事件横截面相关可能影响检验。它提供的是事件研究方法边界，不是任何公告的收益方向。",
        _EVENT_FACTS,
    ),
    KnowledgeClaim(
        "src_mackinlay_1997",
        ("src_brown_warner_1985",),
        ("daily_event_method",),
        "事件研究用特定事件附近的实际收益减去没有该事件时的正常收益，在较短事件窗口中衡量事件与公司价值变化的联系。有效使用要求明确事件时点、正常收益模型和重叠事件，不自动给出因果结论或未来收益保证。",
        _EVENT_FACTS,
    ),
    KnowledgeClaim(
        "src_bernard_thomas_1989",
        ("src_sun_wen_earnings_car_2023",),
        ("earnings_reaction",),
        "按盈余意外区分好消息与坏消息后，公告后异常收益仍可能沿盈余意外的同方向延续；论文研究这种公告后漂移究竟来自价格延迟反应还是风险补偿。使用时必须有可比的盈余意外，不能只拿公告日上涨替代。",
        _EVENT_FACTS + (ResearchDatasetId.FINANCIAL_INDICATOR,),
    ),
    KnowledgeClaim(
        "src_chan_2003",
        ("src_chan_2003",),
        ("formal_announcement_shocks",),
        "在具有完整公开新闻标题的美国样本中，相似价格冲击在有公开新闻与无可识别新闻时后续路径不同：坏消息后更常见延续，无新闻的极端波动更常见反转，而且结果主要集中于较小、流动性较弱股票。本地正式公告并不等于完整新闻。",
        _EVENT_FACTS + (ResearchDatasetId.DAILY_BASIC,),
    ),
)


def adjusted_return(base_close: float, base_factor: float, future_close: float, future_factor: float) -> float:
    values = tuple(float(value) for value in (base_close, base_factor, future_close, future_factor))
    if any(value <= 0 for value in values):
        raise ValueError("prices and adjustment factors must be positive")
    return (values[2] * values[3] / values[1]) / values[0] - 1.0


def chronological_views(frame: pd.DataFrame, *, date_col: str, value: str) -> dict[str, float]:
    ordered = frame[[date_col, value]].dropna().sort_values(date_col, kind="mergesort")
    if ordered.empty:
        return {"overall": float("nan"), "earlier": float("nan"), "later": float("nan")}
    split = (len(ordered) + 1) // 2
    return {
        "overall": float(ordered[value].mean()),
        "earlier": float(ordered.iloc[:split][value].mean()),
        "later": float(ordered.iloc[split:][value].mean()),
    }


def describe_ordered_groups(frame: pd.DataFrame, group: str, value: str) -> str:
    means = frame.groupby(group, sort=True)[value].mean()
    return "; ".join(f"{key}:{mean:g}" for key, mean in means.items())


def size_value_observations(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"date", "ts_code", "total_mv", "pe_ttm", "pb", "future_excess_return"}
    missing = required - set(frame)
    if missing:
        raise ValueError(f"size/value frame missing columns: {sorted(missing)}")
    out = frame[(frame["total_mv"] > 0) & (frame["pe_ttm"] > 0) & (frame["pb"] > 0)].copy()
    out["earnings_price"] = 1.0 / out["pe_ttm"]
    out["book_to_market"] = 1.0 / out["pb"]
    out["size_group"] = out.groupby("date", group_keys=False)["total_mv"].transform(
        lambda values: pd.qcut(values.rank(method="first"), 2, labels=[1, 2])
    )

    def spread(group: pd.DataFrame, signal: str, outcome: str) -> float:
        ordered = group.sort_values([signal, "ts_code"], kind="mergesort")
        return float(ordered.iloc[-1][outcome] - ordered.iloc[0][outcome])

    groups = out.groupby(["date", "size_group"], observed=True)
    spreads = groups.apply(
        lambda group: spread(group, "earnings_price", "future_excess_return"),
        include_groups=False,
    )
    book_spreads = groups.apply(
        lambda group: spread(group, "book_to_market", "future_excess_return"),
        include_groups=False,
    )
    out["value_spread"] = [spreads.loc[(row.date, row.size_group)] for row in out.itertuples()]
    out["book_value_spread"] = [
        book_spreads.loc[(row.date, row.size_group)] for row in out.itertuples()
    ]
    if "future_excess_return_60" in out:
        sixty = groups.apply(
            lambda group: spread(group, "earnings_price", "future_excess_return_60"),
            include_groups=False,
        )
        book_sixty = groups.apply(
            lambda group: spread(group, "book_to_market", "future_excess_return_60"),
            include_groups=False,
        )
        out["value_spread_60"] = [sixty.loc[(row.date, row.size_group)] for row in out.itertuples()]
        out["book_value_spread_60"] = [
            book_sixty.loc[(row.date, row.size_group)] for row in out.itertuples()
        ]
    return out.reset_index(drop=True)


def market_adjusted_event_observations(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["car_0_1"] = out["stock_return_0"] - out["market_return_0"] + out["stock_return_1"] - out["market_return_1"]
    return out


def map_announcement_sessions(announcements: pd.DataFrame, calendar: pd.DataFrame) -> pd.DataFrame:
    opened = calendar.loc[calendar["is_open"].astype(bool), "cal_date"]
    open_dates = sorted(pd.to_datetime(opened).dt.date.unique())
    out = announcements.copy()
    published = pd.to_datetime(out["announcement_time"], utc=True).dt.tz_convert("Asia/Shanghai")

    def event_date(timestamp: pd.Timestamp) -> date:
        if timestamp.date() in open_dates and timestamp.time() <= time(15, 0):
            return timestamp.date()
        return next(item for item in open_dates if item > timestamp.date())

    out["event_date"] = [event_date(timestamp) for timestamp in published]
    return out


def financial_improvement_observations(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    comparisons = (
        ("roe_improved", "roe", "prior_roe", "up"),
        ("cash_flow_improved", "operating_cash_flow", "prior_operating_cash_flow", "up"),
        ("leverage_improved", "leverage", "prior_leverage", "down"),
        ("liquidity_improved", "current_ratio", "prior_current_ratio", "up"),
        ("gross_margin_improved", "gross_margin", "prior_gross_margin", "up"),
        ("asset_turnover_improved", "asset_turnover", "prior_asset_turnover", "up"),
    )
    for result, current, prior, direction in comparisons:
        out[result] = out[current] > out[prior] if direction == "up" else out[current] < out[prior]
    columns = [item[0] for item in comparisons]
    out["improvement_count"] = out[columns].sum(axis=1)
    return out


def momentum_observations(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["prior_group"] = out.groupby("date", group_keys=False)["prior_return"].transform(
        lambda values: pd.qcut(values.rank(method="first"), 5, labels=[1, 2, 3, 4, 5])
    )
    out["industry_subtracted_prior"] = out["prior_return"] - out["industry_prior_return"]
    return out


def earnings_reaction_observations(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["surprise_group"] = pd.qcut(
        out["earnings_surprise"].rank(method="first"),
        5,
        labels=[1, 2, 3, 4, 5],
    )
    return out


def formal_announcement_shock_observations(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["information_match_status"] = out["local_formal_announcement_match"].map(
        {
            True: "local_formal_announcement_match",
            False: "no_local_formal_announcement_match",
        }
    )
    direction = out["market_adjusted_return"].map(lambda value: 1.0 if value >= 0 else -1.0)
    out["directional_follow_through"] = direction * out["future_excess_return"]
    return out


def _dated_spread(
    frame: pd.DataFrame,
    *,
    date_col: str,
    group_col: str,
    value_col: str,
) -> pd.DataFrame:
    means = frame.groupby([date_col, group_col], observed=True)[value_col].mean().unstack()
    return pd.DataFrame(
        {
            date_col: means.index,
            "spread": means.iloc[:, -1].to_numpy() - means.iloc[:, 0].to_numpy(),
        }
    )


def validate_size_value(frame: pd.DataFrame) -> dict[str, int | float | str]:
    unique = frame[["date", "size_group", "value_spread"]].drop_duplicates()
    views = chronological_views(unique, date_col="date", value="value_spread")
    book = frame[["date", "size_group", "book_value_spread"]].drop_duplicates()
    book_views = chronological_views(book, date_col="date", value="book_value_spread")
    size_rank = frame.groupby("date")["total_mv"].rank(pct=True, method="first")
    smallest = frame.assign(_smallest=size_rank <= 0.30).groupby(["date", "_smallest"])[
        "future_excess_return"
    ].mean().unstack()
    result: dict[str, int | float | str] = {
        "stock_observations": int(len(frame)),
        "formation_dates": int(frame["date"].nunique()),
        "earnings_price_spread_overall": views["overall"],
        "earnings_price_spread_earlier": views["earlier"],
        "earnings_price_spread_later": views["later"],
        "book_to_market_spread_overall": book_views["overall"],
        "book_to_market_spread_earlier": book_views["earlier"],
        "book_to_market_spread_later": book_views["later"],
        "smallest_30_minus_others": float((smallest[True] - smallest[False]).mean()),
    }
    if "value_spread_60" in frame:
        ep60 = frame[["date", "size_group", "value_spread_60"]].drop_duplicates()
        bm60 = frame[["date", "size_group", "book_value_spread_60"]].drop_duplicates()
        result["earnings_price_spread_60"] = chronological_views(
            ep60, date_col="date", value="value_spread_60"
        )["overall"]
        result["book_to_market_spread_60"] = chronological_views(
            bm60, date_col="date", value="book_value_spread_60"
        )["overall"]
    return result


def validate_short_reversal(frame: pd.DataFrame) -> dict[str, int | float | str]:
    spreads = _dated_spread(
        frame, date_col="date", group_col="prior_group", value_col="future_excess_return"
    )
    views = chronological_views(spreads, date_col="date", value="spread")
    result: dict[str, int | float | str] = {
        "stock_observations": int(len(frame)),
        "winner_minus_loser_overall": views["overall"],
        "winner_minus_loser_earlier": views["earlier"],
        "winner_minus_loser_later": views["later"],
    }
    if "future_excess_return_60" in frame:
        sixty = _dated_spread(
            frame,
            date_col="date",
            group_col="prior_group",
            value_col="future_excess_return_60",
        )
        result["winner_minus_loser_60"] = float(sixty["spread"].mean())
    return result


def validate_common_factor_momentum(frame: pd.DataFrame) -> dict[str, int | float | str]:
    out = frame.copy()
    out["residual_group"] = out.groupby("date", group_keys=False)[
        "industry_subtracted_prior"
    ].transform(
        lambda values: pd.qcut(values.rank(method="first"), 5, labels=[1, 2, 3, 4, 5])
    )
    raw = _dated_spread(
        out, date_col="date", group_col="prior_group", value_col="future_excess_return"
    )
    residual = _dated_spread(
        out, date_col="date", group_col="residual_group", value_col="future_excess_return"
    )
    result: dict[str, int | float | str] = {
        "formation_dates": int(out["date"].nunique()),
        "raw_winner_minus_loser": float(raw["spread"].mean()),
        "industry_subtracted_winner_minus_loser": float(residual["spread"].mean()),
    }
    if "future_excess_return_60" in out:
        residual60 = _dated_spread(
            out,
            date_col="date",
            group_col="residual_group",
            value_col="future_excess_return_60",
        )
        result["industry_subtracted_winner_minus_loser_60"] = float(
            residual60["spread"].mean()
        )
    return result


def validate_daily_event_method(frame: pd.DataFrame) -> dict[str, int | float | str]:
    events = frame[frame["is_event"].astype(bool)]["car_0_1"]
    pseudo = frame[~frame["is_event"].astype(bool)]["car_0_1"]
    return {
        "event_observations": int(events.count()),
        "pseudo_observations": int(pseudo.count()),
        "event_mean_absolute_car": float(events.abs().mean()),
        "pseudo_mean_car": float(pseudo.mean()),
        "pseudo_mean_absolute_car": float(pseudo.abs().mean()),
    }


def validate_earnings_reaction(frame: pd.DataFrame) -> dict[str, int | float | str]:
    ordered = frame.sort_values("event_date", kind="mergesort")
    split = (len(ordered) + 1) // 2

    def spread(part: pd.DataFrame, value: str) -> float:
        means = part.groupby("surprise_group", observed=True)[value].mean()
        return float(means.iloc[-1] - means.iloc[0])

    return {
        "events": int(len(frame)),
        "surprise_event_car_top_minus_bottom": spread(ordered, "event_car"),
        "surprise_future_return_top_minus_bottom": spread(ordered, "future_excess_return"),
        "future_spread_earlier": spread(ordered.iloc[:split], "future_excess_return"),
        "future_spread_later": spread(ordered.iloc[split:], "future_excess_return"),
    }


def validate_formal_announcement_shocks(frame: pd.DataFrame) -> dict[str, int | float | str]:
    grouped = frame.groupby("information_match_status")["directional_follow_through"].agg(
        ["count", "mean"]
    )
    matched = grouped.loc["local_formal_announcement_match"]
    unmatched = grouped.loc["no_local_formal_announcement_match"]
    return {
        "matched_shocks": int(matched["count"]),
        "locally_unmatched_shocks": int(unmatched["count"]),
        "matched_directional_follow_through": float(matched["mean"]),
        "locally_unmatched_directional_follow_through": float(unmatched["mean"]),
    }


def validate_financial_improvement(frame: pd.DataFrame) -> dict[str, int | float | str]:
    usable = frame.dropna(
        subset=[
            "improvement_count",
            "future_excess_return",
            "cash_component",
            "accrual_component",
            "future_profitability",
            "gross_profitability",
        ]
    )
    periods = sorted(usable["report_period"].unique())
    midpoint = periods[(len(periods) - 1) // 2]
    earlier = usable[usable["report_period"] <= midpoint]
    later = usable[usable["report_period"] > midpoint]

    def rank_correlation(part: pd.DataFrame, signal: str) -> float:
        if len(part) < 2:
            return float("nan")
        return float(part[signal].rank().corr(part["future_excess_return"].rank()))

    result: dict[str, int | float | str] = {
        "company_periods": int(len(usable)),
        "improvement_return_rank_correlation": rank_correlation(usable, "improvement_count"),
        "improvement_return_correlation_earlier": rank_correlation(earlier, "improvement_count"),
        "improvement_return_correlation_later": rank_correlation(later, "improvement_count"),
        "improvement_group_returns": describe_ordered_groups(
            usable, "improvement_count", "future_excess_return"
        ),
        "cash_future_profitability_correlation": float(
            usable["cash_component"].corr(usable["future_profitability"])
        ),
        "accrual_future_profitability_correlation": float(
            usable["accrual_component"].corr(usable["future_profitability"])
        ),
        "gross_profitability_return_rank_correlation": rank_correlation(
            usable, "gross_profitability"
        ),
        "gross_profitability_correlation_earlier": rank_correlation(
            earlier, "gross_profitability"
        ),
        "gross_profitability_correlation_later": rank_correlation(
            later, "gross_profitability"
        ),
        "report_periods": int(usable["report_period"].nunique()),
    }
    return result


def _fact_paths(root: Path, name: str) -> list[str]:
    paths = [str(path) for path in sorted((root / "facts" / name).glob("*/data.parquet"))]
    if not paths:
        raise ValueError(f"no current fact partitions for {name}")
    return paths


def _query_frame(sql: str, parameters: list[object]) -> pd.DataFrame:
    with duckdb.connect() as connection:
        return connection.execute(sql, parameters).fetchdf()


def _load_price_panel(root: Path) -> pd.DataFrame:
    sql = """
        with market as (
            select trade_date, close,
                   row_number() over (order by trade_date) as session_no,
                   count(*) over () as session_count
            from read_parquet(?, union_by_name=true, hive_partitioning=false)
            where index_code = '000300.SH'
        ), formation as (
            select * from market
            where session_no > 60 and session_no + 60 <= session_count
              and session_no % 20 = 0
        ), members as (
            select ts_code, industry_code, valid_from, valid_to
            from read_parquet(?, union_by_name=true, hive_partitioning=false)
            where level = 'L1'
        )
        select f.trade_date as date, e.ts_code, b.total_mv, b.pe_ttm, b.pb,
               (e.close * a.adj_factor) / (prior.close * prior_a.adj_factor) - 1
                   as prior_return,
               (future.close * future_a.adj_factor) / (e.close * a.adj_factor) - 1
                   - (future_market.close / f.close - 1) as future_excess_return,
               (future60.close * future60_a.adj_factor) / (e.close * a.adj_factor) - 1
                   - (future_market60.close / f.close - 1) as future_excess_return_60,
               members.industry_code
        from formation f
        join market prior_market on prior_market.session_no = f.session_no - 60
        join market future_market on future_market.session_no = f.session_no + 20
        join market future_market60 on future_market60.session_no = f.session_no + 60
        join read_parquet(?, union_by_name=true, hive_partitioning=false) e
          on e.trade_date = f.trade_date
        join read_parquet(?, union_by_name=true, hive_partitioning=false) a
          on a.trade_date = e.trade_date and a.ts_code = e.ts_code
        join read_parquet(?, union_by_name=true, hive_partitioning=false) b
          on b.trade_date = e.trade_date and b.ts_code = e.ts_code
        join read_parquet(?, union_by_name=true, hive_partitioning=false) prior
          on prior.trade_date = prior_market.trade_date and prior.ts_code = e.ts_code
        join read_parquet(?, union_by_name=true, hive_partitioning=false) prior_a
          on prior_a.trade_date = prior.trade_date and prior_a.ts_code = e.ts_code
        join read_parquet(?, union_by_name=true, hive_partitioning=false) future
          on future.trade_date = future_market.trade_date and future.ts_code = e.ts_code
        join read_parquet(?, union_by_name=true, hive_partitioning=false) future_a
          on future_a.trade_date = future.trade_date and future_a.ts_code = e.ts_code
        join read_parquet(?, union_by_name=true, hive_partitioning=false) future60
          on future60.trade_date = future_market60.trade_date and future60.ts_code = e.ts_code
        join read_parquet(?, union_by_name=true, hive_partitioning=false) future60_a
          on future60_a.trade_date = future60.trade_date and future60_a.ts_code = e.ts_code
        left join members
          on members.ts_code = e.ts_code
         and cast(members.valid_from as date) <= cast(e.trade_date as date)
         and (members.valid_to is null or cast(members.valid_to as date) >= cast(e.trade_date as date))
        where e.close > 0 and prior.close > 0 and future.close > 0 and future60.close > 0
          and a.adj_factor > 0 and prior_a.adj_factor > 0 and future_a.adj_factor > 0
          and future60_a.adj_factor > 0
          and b.total_mv > 0
    """
    index_paths = _fact_paths(root, "index_daily")
    equity_paths = _fact_paths(root, "equity_daily")
    factor_paths = _fact_paths(root, "adj_factor")
    frame = _query_frame(
        sql,
        [
            index_paths,
            _fact_paths(root, "industry_member"),
            equity_paths,
            factor_paths,
            _fact_paths(root, "daily_basic"),
            equity_paths,
            factor_paths,
            equity_paths,
            factor_paths,
            equity_paths,
            factor_paths,
        ],
    )
    frame["date"] = pd.to_datetime(frame["date"]).dt.date
    frame["industry_prior_return"] = frame.groupby(
        ["date", "industry_code"], dropna=False
    )["prior_return"].transform("mean")
    return frame.dropna(subset=["future_excess_return", "prior_return"])


def _announcement_events_sql(candidate_only: bool) -> str:
    predicate = "and cast(candidate_event_types as varchar) <> '[]'" if candidate_only else ""
    return f"""
        select distinct a.ts_code,
          case
            when same_day.trade_date is not null and a.ann_time <= '15:00:00'
              then a.ann_date
            else (select min(c2.trade_date) from calendar c2 where c2.trade_date > a.ann_date)
          end as event_date
        from (
          select ts_code,
                 cast(substr(cast(announcement_time as varchar), 1, 10) as date) ann_date,
                 substr(cast(announcement_time as varchar), 12, 8) ann_time
          from announcements
          where ts_code is not null {predicate}
        ) a
        left join calendar same_day on same_day.trade_date = a.ann_date
    """


def _load_event_panel(root: Path) -> pd.DataFrame:
    event_sql = _announcement_events_sql(candidate_only=True)
    sql = f"""
        with calendar as (
          select trade_date, row_number() over (order by trade_date) session_no
          from read_parquet(?, union_by_name=true, hive_partitioning=false)
          where index_code = '000300.SH'
        ), announcements as (
          select * from read_parquet(?, union_by_name=true, hive_partitioning=false)
        ), event_dates as ({event_sql}), stock_returns as (
          select ts_code, trade_date, pct_chg / 100.0 stock_return
          from read_parquet(?, union_by_name=true, hive_partitioning=false)
          where pct_chg is not null
        ), market_returns as (
          select trade_date, avg(stock_return) market_return
          from stock_returns group by trade_date
        ), daily as (
          select s.ts_code, c.trade_date, c.session_no,
                 s.stock_return - m.market_return abnormal_return
          from calendar c
          join stock_returns s on s.trade_date = c.trade_date
          join market_returns m on m.trade_date = c.trade_date
        ), event_rows as (
          select d.ts_code, d.trade_date event_date,
                 d.abnormal_return + next_day.abnormal_return car_0_1,
                 true is_event
          from event_dates ev
          join daily d on d.ts_code = ev.ts_code and d.trade_date = ev.event_date
          join daily next_day on next_day.ts_code = d.ts_code
                             and next_day.session_no = d.session_no + 1
        ), pseudo_rows as (
          select d.ts_code, d.trade_date event_date,
                 d.abnormal_return + next_day.abnormal_return car_0_1,
                 false is_event
          from daily d
          join daily next_day on next_day.ts_code = d.ts_code
                             and next_day.session_no = d.session_no + 1
          where d.session_no % 20 = 7
            and d.trade_date >= (select min(event_date) from event_dates)
            and not exists (
              select 1 from event_dates ev
              where ev.ts_code = d.ts_code and ev.event_date = d.trade_date
            )
        )
        select * from event_rows
        union all
        select * from pseudo_rows
    """
    frame = _query_frame(
        sql,
        [
            _fact_paths(root, "index_daily"),
            _fact_paths(root, "announcement"),
            _fact_paths(root, "equity_daily"),
        ],
    )
    frame["event_date"] = pd.to_datetime(frame["event_date"]).dt.date
    return frame.dropna(subset=["car_0_1"])


def _load_earnings_panel(root: Path) -> pd.DataFrame:
    sql = """
        with calendar as (
          select trade_date, pct_chg / 100.0 market_return, close market_close,
                 row_number() over (order by trade_date) session_no
          from read_parquet(?, union_by_name=true, hive_partitioning=false)
          where index_code = '000300.SH'
        ), raw_events as (
          select ts_code, ann_date,
                 (coalesce(p_change_min, p_change_max) + coalesce(p_change_max, p_change_min)) / 2.0
                   earnings_surprise
          from read_parquet(?, union_by_name=true, hive_partitioning=false)
          where coalesce(p_change_min, p_change_max) is not null
          union all
          select ts_code, ann_date, yoy_net_profit earnings_surprise
          from read_parquet(?, union_by_name=true, hive_partitioning=false)
          where yoy_net_profit is not null
        ), event_day_map as (
          select dates.ann_date, min(c.trade_date) event_date
          from (select distinct ann_date from raw_events) dates
          join calendar c on c.trade_date > dates.ann_date
          group by dates.ann_date
        ), events as (
          select r.ts_code, r.ann_date, avg(r.earnings_surprise) earnings_surprise,
                 max(m.event_date) event_date
          from raw_events r join event_day_map m on m.ann_date = r.ann_date
          group by r.ts_code, r.ann_date
        )
        select ev.event_date, ev.ts_code, ev.earnings_surprise,
               (day0.pct_chg / 100.0 - c0.market_return)
                 + (day1.pct_chg / 100.0 - c1.market_return) event_car,
               (future.close * future_a.adj_factor) / (day0.close * day0_a.adj_factor) - 1
                 - (c20.market_close / c0.market_close - 1) future_excess_return
        from events ev
        join calendar c0 on c0.trade_date = ev.event_date
        join calendar c1 on c1.session_no = c0.session_no + 1
        join calendar c20 on c20.session_no = c0.session_no + 20
        join read_parquet(?, union_by_name=true, hive_partitioning=false) day0
          on day0.ts_code = ev.ts_code and day0.trade_date = c0.trade_date
        join read_parquet(?, union_by_name=true, hive_partitioning=false) day1
          on day1.ts_code = ev.ts_code and day1.trade_date = c1.trade_date
        join read_parquet(?, union_by_name=true, hive_partitioning=false) future
          on future.ts_code = ev.ts_code and future.trade_date = c20.trade_date
        join read_parquet(?, union_by_name=true, hive_partitioning=false) day0_a
          on day0_a.ts_code = ev.ts_code and day0_a.trade_date = c0.trade_date
        join read_parquet(?, union_by_name=true, hive_partitioning=false) future_a
          on future_a.ts_code = ev.ts_code and future_a.trade_date = c20.trade_date
        where day0.close > 0 and future.close > 0
          and day0_a.adj_factor > 0 and future_a.adj_factor > 0
    """
    equity = _fact_paths(root, "equity_daily")
    factor = _fact_paths(root, "adj_factor")
    frame = _query_frame(
        sql,
        [
            _fact_paths(root, "index_daily"),
            _fact_paths(root, "earnings_forecast"),
            _fact_paths(root, "earnings_express"),
            equity,
            equity,
            equity,
            factor,
            factor,
        ],
    )
    frame["event_date"] = pd.to_datetime(frame["event_date"]).dt.date
    return frame.dropna()


def _load_shock_panel(root: Path) -> pd.DataFrame:
    event_sql = _announcement_events_sql(candidate_only=False)
    sql = f"""
        with calendar as (
          select trade_date, pct_chg / 100.0 market_return, close market_close,
                 row_number() over (order by trade_date) session_no
          from read_parquet(?, union_by_name=true, hive_partitioning=false)
          where index_code = '000300.SH'
        ), announcements as (
          select * from read_parquet(?, union_by_name=true, hive_partitioning=false)
        ), event_dates as ({event_sql}), daily as (
          select c.trade_date date, c.session_no, e.ts_code,
                 e.pct_chg / 100.0 - c.market_return market_adjusted_return,
                 (future.close * future_a.adj_factor) / (e.close * base_a.adj_factor) - 1
                   - (future_market.market_close / c.market_close - 1) future_excess_return
          from calendar c
          join calendar future_market on future_market.session_no = c.session_no + 20
          join read_parquet(?, union_by_name=true, hive_partitioning=false) e
            on e.trade_date = c.trade_date
          join read_parquet(?, union_by_name=true, hive_partitioning=false) future
            on future.trade_date = future_market.trade_date and future.ts_code = e.ts_code
          join read_parquet(?, union_by_name=true, hive_partitioning=false) base_a
            on base_a.trade_date = e.trade_date and base_a.ts_code = e.ts_code
          join read_parquet(?, union_by_name=true, hive_partitioning=false) future_a
            on future_a.trade_date = future.trade_date and future_a.ts_code = e.ts_code
          where c.trade_date >= (select min(event_date) from event_dates)
            and e.close > 0 and future.close > 0 and base_a.adj_factor > 0 and future_a.adj_factor > 0
        ), ranked as (
          select *, percent_rank() over (
            partition by date order by abs(market_adjusted_return) desc
          ) move_rank
          from daily
        )
        select r.date, r.market_adjusted_return, r.future_excess_return,
               ev.ts_code is not null local_formal_announcement_match
        from ranked r
        left join event_dates ev on ev.ts_code = r.ts_code and ev.event_date = r.date
        where r.move_rank <= 0.05
    """
    equity = _fact_paths(root, "equity_daily")
    factor = _fact_paths(root, "adj_factor")
    frame = _query_frame(
        sql,
        [
            _fact_paths(root, "index_daily"),
            _fact_paths(root, "announcement"),
            equity,
            equity,
            factor,
            factor,
        ],
    )
    frame["date"] = pd.to_datetime(frame["date"]).dt.date
    return frame.dropna(subset=["market_adjusted_return", "future_excess_return"])


def _load_financial_panel(root: Path) -> pd.DataFrame:
    sql = """
        with calendar as (
          select trade_date, close market_close,
                 row_number() over (order by trade_date) session_no
          from read_parquet(?, union_by_name=true, hive_partitioning=false)
          where index_code = '000300.SH'
        ), income as (
          select ts_code, report_period,
                 coalesce(
                   try_cast(ann_date as date),
                   cast(try_strptime(cast(ann_date as varchar), '%Y%m%d') as date)
                 ) ann_date,
                 revenue, oper_cost, n_income_attr_p
          from read_parquet(?, union_by_name=true, hive_partitioning=false)
        ), balance as (
          select ts_code, report_period, total_assets
          from read_parquet(?, union_by_name=true, hive_partitioning=false)
        ), cash as (
          select ts_code, report_period, n_cashflow_act
          from read_parquet(?, union_by_name=true, hive_partitioning=false)
        ), indicators as (
          select ts_code, report_period, roe, current_ratio, debt_to_assets,
                 grossprofit_margin, assets_turn
          from read_parquet(?, union_by_name=true, hive_partitioning=false)
        ), combined as (
          select i.ts_code, i.report_period, i.ann_date, i.n_income_attr_p,
                 i.revenue, i.oper_cost, b.total_assets, cf.n_cashflow_act,
                 fi.roe, fi.current_ratio, fi.debt_to_assets,
                 fi.grossprofit_margin, fi.assets_turn
          from income i
          join balance b using (ts_code, report_period)
          join cash cf using (ts_code, report_period)
          join indicators fi using (ts_code, report_period)
          where b.total_assets > 0
        ), compared as (
          select *,
            lag(roe, 4) over company as prior_roe,
            lag(n_cashflow_act, 4) over company as prior_operating_cash_flow,
            lag(debt_to_assets, 4) over company as prior_leverage,
            lag(current_ratio, 4) over company as prior_current_ratio,
            lag(grossprofit_margin, 4) over company as prior_gross_margin,
            lag(assets_turn, 4) over company as prior_asset_turnover,
            lead(n_income_attr_p / total_assets, 4) over company as future_profitability
          from combined
          window company as (partition by ts_code order by report_period)
        ), event_day_map as (
          select dates.ann_date, min(c.trade_date) event_date
          from (select distinct ann_date from compared where ann_date is not null) dates
          join calendar c on c.trade_date > dates.ann_date
          group by dates.ann_date
        ), dated as (
          select compared.*, event_day_map.event_date
          from compared join event_day_map using (ann_date)
        )
        select d.report_period, d.roe, d.prior_roe,
               d.n_cashflow_act operating_cash_flow,
               d.prior_operating_cash_flow,
               d.debt_to_assets leverage, d.prior_leverage,
               d.current_ratio, d.prior_current_ratio,
               d.grossprofit_margin gross_margin, d.prior_gross_margin,
               (d.revenue - d.oper_cost) / d.total_assets gross_profitability,
               d.assets_turn asset_turnover, d.prior_asset_turnover,
               d.n_cashflow_act / d.total_assets cash_component,
               (d.n_income_attr_p - d.n_cashflow_act) / d.total_assets accrual_component,
               d.future_profitability,
               (future.close * future_a.adj_factor) / (base.close * base_a.adj_factor) - 1
                 - (future_market.market_close / base_market.market_close - 1) future_excess_return
        from dated d
        join calendar base_market on base_market.trade_date = d.event_date
        join calendar future_market on future_market.session_no = base_market.session_no + 20
        join read_parquet(?, union_by_name=true, hive_partitioning=false) base
          on base.ts_code = d.ts_code and base.trade_date = base_market.trade_date
        join read_parquet(?, union_by_name=true, hive_partitioning=false) future
          on future.ts_code = d.ts_code and future.trade_date = future_market.trade_date
        join read_parquet(?, union_by_name=true, hive_partitioning=false) base_a
          on base_a.ts_code = d.ts_code and base_a.trade_date = base_market.trade_date
        join read_parquet(?, union_by_name=true, hive_partitioning=false) future_a
          on future_a.ts_code = d.ts_code and future_a.trade_date = future_market.trade_date
        where base.close > 0 and future.close > 0 and base_a.adj_factor > 0 and future_a.adj_factor > 0
    """
    equity = _fact_paths(root, "equity_daily")
    factor = _fact_paths(root, "adj_factor")
    frame = _query_frame(
        sql,
        [
            _fact_paths(root, "index_daily"),
            _fact_paths(root, "income_statement"),
            _fact_paths(root, "balance_sheet"),
            _fact_paths(root, "cash_flow"),
            _fact_paths(root, "financial_indicator"),
            equity,
            equity,
            factor,
            factor,
        ],
    )
    frame["report_period"] = pd.to_datetime(frame["report_period"]).dt.date
    frame = financial_improvement_observations(frame)
    return frame.dropna(
        subset=[
            "prior_roe",
            "prior_operating_cash_flow",
            "prior_leverage",
            "prior_current_ratio",
            "prior_gross_margin",
            "prior_asset_turnover",
            "future_profitability",
            "future_excess_return",
        ]
    )


def validate_all_claims(warehouse_root: Path) -> tuple[HistoricalEvidence, ...]:
    root = Path(warehouse_root)
    price = _load_price_panel(root)
    size = validate_size_value(size_value_observations(price))
    momentum = momentum_observations(price.dropna(subset=["industry_prior_return"]))
    reversal = validate_short_reversal(momentum)
    common = validate_common_factor_momentum(momentum)
    event = validate_daily_event_method(_load_event_panel(root))
    earnings = validate_earnings_reaction(
        earnings_reaction_observations(_load_earnings_panel(root))
    )
    shocks = validate_formal_announcement_shocks(
        formal_announcement_shock_observations(_load_shock_panel(root))
    )
    financial = validate_financial_improvement(_load_financial_panel(root))
    calculations = {
        "size_value": size,
        "short_reversal": reversal,
        "common_factor_momentum": common,
        "daily_event_method": event,
        "earnings_reaction": earnings,
        "formal_announcement_shocks": shocks,
        "financial_improvement": financial,
    }
    unavailable_core_variable = {
        "src_ball_brown_1968": "现有数据没有可与市场预期比较的非预期盈余。",
        "src_bernard_thomas_1989": "现有数据没有标准化非预期盈余，不能用同比增长替代。",
        "src_chan_2003": "现有数据只覆盖本地正式公告，不是论文所需的完整公开新闻标题库。",
    }
    evidence: list[HistoricalEvidence] = []
    for claim in CLAIMS:
        combined = {name: calculations[name] for name in claim.calculations}
        flattened = {
            f"{name}.{key}": value
            for name, metrics in combined.items()
            for key, value in metrics.items()
        }
        serialized = json.dumps(flattened, ensure_ascii=False, sort_keys=True)
        evidence.append(
            HistoricalEvidence(
                legacy_id=claim.legacy_id,
                calculations=claim.calculations,
                data_usable=claim.legacy_id not in unavailable_core_variable,
                overall_direction=serialized,
                earlier_direction=str(
                    {key: value for key, value in flattened.items() if "earlier" in key}
                ),
                later_direction=str(
                    {key: value for key, value in flattened.items() if "later" in key}
                ),
                relationship_shape=serialized,
                main_drivers=str(
                    {key: value for key, value in flattened.items() if "observ" in key or "dates" in key or "period" in key}
                ),
                counter_evidence=unavailable_core_variable.get(
                    claim.legacy_id,
                    "由逐项复核根据相反方向、时期变化和数据边界填写。",
                ),
                observations=flattened,
            )
        )
    return tuple(evidence)
