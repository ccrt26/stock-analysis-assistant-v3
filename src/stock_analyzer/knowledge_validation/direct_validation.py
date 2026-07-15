from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time

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
    required = {"date", "ts_code", "total_mv", "pe_ttm", "future_excess_return"}
    missing = required - set(frame)
    if missing:
        raise ValueError(f"size/value frame missing columns: {sorted(missing)}")
    out = frame[(frame["total_mv"] > 0) & (frame["pe_ttm"] > 0)].copy()
    out["earnings_price"] = 1.0 / out["pe_ttm"]
    out["size_group"] = out.groupby("date", group_keys=False)["total_mv"].transform(
        lambda values: pd.qcut(values.rank(method="first"), 2, labels=[1, 2])
    )

    def spread(group: pd.DataFrame) -> float:
        ordered = group.sort_values(["earnings_price", "ts_code"], kind="mergesort")
        return float(ordered.iloc[-1]["future_excess_return"] - ordered.iloc[0]["future_excess_return"])

    spreads = out.groupby(["date", "size_group"], observed=True).apply(spread, include_groups=False)
    out["value_spread"] = [spreads.loc[(row.date, row.size_group)] for row in out.itertuples()]
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
        ("gross_profitability_improved", "gross_profitability", "prior_gross_profitability", "up"),
        ("asset_turnover_improved", "asset_turnover", "prior_asset_turnover", "up"),
    )
    for result, current, prior, direction in comparisons:
        out[result] = out[current] > out[prior] if direction == "up" else out[current] < out[prior]
    columns = [item[0] for item in comparisons]
    out["improvement_count"] = out[columns].sum(axis=1)
    return out


def validate_all_claims(*_args: object, **_kwargs: object) -> tuple[HistoricalEvidence, ...]:
    raise NotImplementedError("historical warehouse execution is added after formula tests")
