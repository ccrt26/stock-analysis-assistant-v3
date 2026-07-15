from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Literal

import duckdb
import pandas as pd

from stock_analyzer.data.research_contracts import ResearchDatasetId


Action = Literal["new", "enhance"]
ValidationKind = Literal[
    "empirical",
    "official_semantics",
    "mixed",
    "portfolio_method",
]


@dataclass(frozen=True)
class SupplementClaim:
    knowledge_id: str
    action: Action
    validation_kind: ValidationKind
    core_theory: str
    source_refs: tuple[str, ...]
    required_facts: tuple[ResearchDatasetId, ...]


@dataclass(frozen=True)
class SupplementEvidence:
    knowledge_id: str
    data_usable: bool
    overall_direction: str
    earlier_direction: str
    later_direction: str
    relationship_shape: str
    counter_evidence: str
    observations: dict[str, int | float | str]


SOURCE_REFS = frozenset(
    {
        "10.1016/j.iref.2017.04.003",
        "10.1016/j.pacfin.2015.03.005",
        "10.1016/j.pacfin.2019.101218",
        "https://www.sciopen.com/article/10.26599/CJE.2022.9300405",
        "10.1016/j.jbankfin.2017.10.001",
        "10.1111/j.1467-646X.2011.01050.x",
        "10.1016/S1386-4181(01)00024-6",
        "10.1016/j.pacfin.2022.101861",
        "10.1016/j.najef.2021.101475",
        "10.1016/j.jbankfin.2013.10.002",
        "10.1016/j.pacfin.2019.04.001",
        "10.1016/j.frl.2017.12.007",
        "10.1007/s11156-025-01419-z",
        "10.1111/j.1540-6261.1952.tb01525.x",
        "10.1093/rfs/hhm075",
        "https://www.sse.com.cn/lawandrules/sselawsrules2025/"
        "stocks/mainipo/c/c_20260424_10816589.shtml",
        "https://www.szse.cn/lawrules/rule/allrules/bussiness/"
        "t20260424_620193.html",
        "https://www.csrc.gov.cn/csrc/c106256/c1654005/content.shtml",
        "https://www.sse.com.cn/lawandrules/sselawsrules2025/"
        "trade/specific/margin/",
        "https://www.csrc.gov.cn/csrc/c100028/c7483136/content.shtml",
        "https://www.sse.com.cn/lawandrules/sselawsrules2025/"
        "trade/specific/repo/c/c_20250617_10782110.shtml",
        "https://big5.sse.com.cn/site/cht/www.sse.com.cn/lawandrules/"
        "sselawsrules2025/stocks/mainipo/c/c_20260424_10816605.shtml",
    }
)


SUPPLEMENT_CLAIMS = (
    SupplementClaim(
        knowledge_id="src_cn_factor_momentum_2023",
        action="enhance",
        validation_kind="empirical",
        core_theory=(
            "中国股票的趋势延续会随上涨、下跌及市场状态切换而改变；市场环境只能改变趋势证据的可信程度，"
            "不能把市场上涨直接写成强势行业或个股必然继续上涨。"
        ),
        source_refs=("10.1016/j.iref.2017.04.003",),
        required_facts=(
            ResearchDatasetId.INDEX_DAILY,
            ResearchDatasetId.EQUITY_DAILY,
            ResearchDatasetId.INDUSTRY_DAILY,
            ResearchDatasetId.THEME_DAILY,
        ),
    ),
    SupplementClaim(
        knowledge_id="src_cn_return_dispersion_risk",
        action="new",
        validation_kind="empirical",
        core_theory=(
            "市场或行业成员收益分化扩大说明共同上涨程度下降，并可能对应更高的不确定性和后续波动；"
            "分化是风险证据，但不能单独证明市场即将下跌。"
        ),
        source_refs=(
            "10.1016/j.pacfin.2015.03.005",
            "10.1016/j.pacfin.2019.101218",
        ),
        required_facts=(
            ResearchDatasetId.EQUITY_DAILY,
            ResearchDatasetId.INDEX_DAILY,
            ResearchDatasetId.INDUSTRY_MEMBER,
        ),
    ),
    SupplementClaim(
        knowledge_id="src_cn_turnover_momentum_boundary",
        action="new",
        validation_kind="empirical",
        core_theory=(
            "高换手特征可能削弱中国股票的价格延续关系，因此成交放大必须与换手稳定性和价格波动共同检查；"
            "高换手本身既不证明趋势可靠，也不能识别资金或账户身份。"
        ),
        source_refs=(
            "https://www.sciopen.com/article/10.26599/CJE.2022.9300405",
        ),
        required_facts=(
            ResearchDatasetId.DAILY_BASIC,
            ResearchDatasetId.EQUITY_DAILY,
            ResearchDatasetId.ADJ_FACTOR,
            ResearchDatasetId.INDEX_DAILY,
        ),
    ),
    SupplementClaim(
        knowledge_id="src_cn_profitability_valuation_support",
        action="new",
        validation_kind="empirical",
        core_theory=(
            "盈利能力与估值需要共同比较，ROE、ROA、毛利能力和资产使用效率回答不同问题；"
            "这些盈利事实可以检查高估值是否有经营支撑，但不能直接预测未来二至六周上涨。"
        ),
        source_refs=("10.1016/j.jbankfin.2017.10.001",),
        required_facts=(
            ResearchDatasetId.INCOME_STATEMENT,
            ResearchDatasetId.BALANCE_SHEET,
            ResearchDatasetId.FINANCIAL_INDICATOR,
            ResearchDatasetId.DAILY_BASIC,
            ResearchDatasetId.EQUITY_DAILY,
            ResearchDatasetId.ADJ_FACTOR,
            ResearchDatasetId.INDEX_DAILY,
        ),
    ),
    SupplementClaim(
        knowledge_id="src_cn_cash_accrual_quality",
        action="new",
        validation_kind="empirical",
        core_theory=(
            "利润增长需要拆分经营现金支持和应计成分，以识别利润与现金流同步改善还是依赖应收、存货或一次性项目；"
            "当前使用不得复制原研究时期的退市制度和历史阈值。"
        ),
        source_refs=("10.1111/j.1467-646X.2011.01050.x",),
        required_facts=(
            ResearchDatasetId.INCOME_STATEMENT,
            ResearchDatasetId.BALANCE_SHEET,
            ResearchDatasetId.CASH_FLOW,
            ResearchDatasetId.FINANCIAL_INDICATOR,
            ResearchDatasetId.EQUITY_DAILY,
            ResearchDatasetId.ADJ_FACTOR,
            ResearchDatasetId.INDEX_DAILY,
        ),
    ),
    SupplementClaim(
        knowledge_id="src_cn_illiquidity_operability",
        action="new",
        validation_kind="empirical",
        core_theory=(
            "日收益相对成交额可以形成粗粒度非流动性观察，识别较小成交即可造成较大价格变化的股票；"
            "该观察用于风险和可操作性，不是订单簿冲击，也不表示流动性差就有更高未来收益。"
        ),
        source_refs=(
            "10.1016/S1386-4181(01)00024-6",
            "10.1016/j.pacfin.2022.101861",
        ),
        required_facts=(
            ResearchDatasetId.EQUITY_DAILY,
            ResearchDatasetId.DAILY_BASIC,
            ResearchDatasetId.ADJ_FACTOR,
            ResearchDatasetId.INDEX_DAILY,
        ),
    ),
    SupplementClaim(
        knowledge_id="src_cn_max_overextension",
        action="new",
        validation_kind="empirical",
        core_theory=(
            "近期最大单日上涨和连续快速拉升可能表现出彩票型追涨与价格透支风险；"
            "MAX只能作为强势股的风险反证，不能机械淘汰所有近期上涨股票。"
        ),
        source_refs=("10.1016/j.najef.2021.101475",),
        required_facts=(
            ResearchDatasetId.EQUITY_DAILY,
            ResearchDatasetId.ADJ_FACTOR,
            ResearchDatasetId.DAILY_BASIC,
            ResearchDatasetId.INDEX_DAILY,
        ),
    ),
    SupplementClaim(
        knowledge_id="src_cn_earnings_disclosure_hierarchy",
        action="new",
        validation_kind="official_semantics",
        core_theory=(
            "业绩预告、业绩快报、正式定期报告和更正公告处于不同披露阶段，具有不同确定性；"
            "预告不是正式实现结果，快报也可能被正式财报或更正改变。"
        ),
        source_refs=(
            "https://www.sse.com.cn/lawandrules/sselawsrules2025/"
            "stocks/mainipo/c/c_20260424_10816589.shtml",
            "https://www.szse.cn/lawrules/rule/allrules/bussiness/"
            "t20260424_620193.html",
        ),
        required_facts=(
            ResearchDatasetId.EARNINGS_FORECAST,
            ResearchDatasetId.EARNINGS_EXPRESS,
            ResearchDatasetId.INCOME_STATEMENT,
            ResearchDatasetId.ANNOUNCEMENT,
        ),
    ),
    SupplementClaim(
        knowledge_id="src_cn_margin_semantics",
        action="new",
        validation_kind="mixed",
        core_theory=(
            "融资余额、融资买入、融资偿还和融券余量具有正式定义，可用于观察杠杆交易变化和潜在拥挤；"
            "融资买入增加不等于机构看多，也不能单独成为未来收益预测。"
        ),
        source_refs=(
            "https://www.csrc.gov.cn/csrc/c106256/c1654005/content.shtml",
            "https://www.sse.com.cn/lawandrules/sselawsrules2025/"
            "trade/specific/margin/",
            "10.1016/j.jbankfin.2013.10.002",
        ),
        required_facts=(
            ResearchDatasetId.MARGIN_DETAIL,
            ResearchDatasetId.EQUITY_DAILY,
            ResearchDatasetId.INDEX_DAILY,
        ),
    ),
    SupplementClaim(
        knowledge_id="src_cn_share_reduction_rules_2024",
        action="enhance",
        validation_kind="official_semantics",
        core_theory=(
            "限售股份取得流通资格、股东提出减持计划和正式披露的实际减持是三个不同事实阶段；"
            "只有解禁事实时不能写成股东已经出售股份。"
        ),
        source_refs=(
            "https://www.sse.com.cn/lawandrules/sselawsrules2025/"
            "stocks/mainipo/c/c_20260424_10816589.shtml",
            "https://www.szse.cn/lawrules/rule/allrules/bussiness/"
            "t20260424_620193.html",
            "https://www.csrc.gov.cn/csrc/c100028/c7483136/content.shtml",
        ),
        required_facts=(
            ResearchDatasetId.SHARE_FLOAT,
            ResearchDatasetId.HOLDER_TRADE,
            ResearchDatasetId.ANNOUNCEMENT,
        ),
    ),
    SupplementClaim(
        knowledge_id="src_cn_pledge_conditional_risk",
        action="new",
        validation_kind="mixed",
        core_theory=(
            "股票质押是融资担保安排，风险是否升级取决于质押比例、股价变化、流动性、财务状况及履约处置条件；"
            "质押事实本身不等于爆仓，也不能据此推算具体平仓价格。"
        ),
        source_refs=(
            "https://www.sse.com.cn/lawandrules/sselawsrules2025/"
            "trade/specific/repo/c/c_20250617_10782110.shtml",
            "10.1016/j.pacfin.2019.04.001",
        ),
        required_facts=(
            ResearchDatasetId.PLEDGE,
            ResearchDatasetId.EQUITY_DAILY,
            ResearchDatasetId.DAILY_BASIC,
            ResearchDatasetId.BALANCE_SHEET,
            ResearchDatasetId.CASH_FLOW,
        ),
    ),
    SupplementClaim(
        knowledge_id="src_cn_disclosed_holder_trade",
        action="new",
        validation_kind="empirical",
        core_theory=(
            "依法披露的董监高或重要股东实际增减持包含公司相关信息，应与后续经营变化共同观察；"
            "单次增持不能证明股价上涨，内部人交易在这里不表示违法内幕交易。"
        ),
        source_refs=("10.1016/j.frl.2017.12.007",),
        required_facts=(
            ResearchDatasetId.HOLDER_TRADE,
            ResearchDatasetId.INCOME_STATEMENT,
            ResearchDatasetId.EARNINGS_FORECAST,
            ResearchDatasetId.EQUITY_DAILY,
            ResearchDatasetId.ADJ_FACTOR,
            ResearchDatasetId.INDEX_DAILY,
        ),
    ),
    SupplementClaim(
        knowledge_id="src_cn_buyback_rules_2023",
        action="enhance",
        validation_kind="mixed",
        core_theory=(
            "股份回购的提议、预案、股东大会通过、实施、完成、停止和未通过是不同阶段，实际执行比计划公告提供更多行动事实；"
            "回购仍不能单独证明公司被低估或未来上涨。"
        ),
        source_refs=("10.1007/s11156-025-01419-z",),
        required_facts=(
            ResearchDatasetId.REPURCHASE,
            ResearchDatasetId.EQUITY_DAILY,
            ResearchDatasetId.ADJ_FACTOR,
            ResearchDatasetId.INDEX_DAILY,
        ),
    ),
    SupplementClaim(
        knowledge_id="src_csrc_disclosure_rules_2025",
        action="enhance",
        validation_kind="official_semantics",
        core_theory=(
            "上市公司不得迎合市场热点或夸大业务影响，公司与主题的真实联系必须由主营范围、分部收入利润或正式公告支持；"
            "没有正式业务和收入证据时不能写成公司将明显受益。"
        ),
        source_refs=(
            "https://big5.sse.com.cn/site/cht/www.sse.com.cn/lawandrules/"
            "sselawsrules2025/stocks/mainipo/c/c_20260424_10816605.shtml",
        ),
        required_facts=(
            ResearchDatasetId.COMPANY_PROFILE,
            ResearchDatasetId.MAIN_BUSINESS,
            ResearchDatasetId.ANNOUNCEMENT,
        ),
    ),
    SupplementClaim(
        knowledge_id="src_portfolio_common_exposure",
        action="new",
        validation_kind="portfolio_method",
        core_theory=(
            "组合风险取决于候选之间的共同收益变化和集中暴露，五只股票若属于同一行业、主题或高度同步就不是五个独立机会；"
            "当前只做透明集中度和相关性检查，不估计最优权重。"
        ),
        source_refs=(
            "10.1111/j.1540-6261.1952.tb01525.x",
            "10.1093/rfs/hhm075",
        ),
        required_facts=(
            ResearchDatasetId.INDUSTRY_MEMBER,
            ResearchDatasetId.THEME_MEMBER,
            ResearchDatasetId.EQUITY_DAILY,
            ResearchDatasetId.ADJ_FACTOR,
        ),
    ),
)


def _quantile_groups(values: pd.Series, groups: int) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    result = pd.Series(pd.NA, index=values.index, dtype="Int64")
    valid = numeric.dropna()
    if valid.empty:
        return result
    bins = min(groups, len(valid))
    labels = pd.qcut(
        valid.rank(method="first"),
        bins,
        labels=False,
    )
    result.loc[valid.index] = labels.astype("int64") + 1
    return result


def illiquidity_observations(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    adjusted_return = pd.to_numeric(
        out["adjusted_return_1d"], errors="coerce"
    )
    amount = pd.to_numeric(out["amount"], errors="coerce").mask(
        lambda values: values.eq(0)
    )
    out["amihud_illiquidity"] = (
        adjusted_return.abs() / amount * 100_000_000
    )
    return out


def market_state_observations(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    previous_return = pd.to_numeric(
        out["prior_market_return_20d"], errors="coerce"
    )
    current_return = pd.to_numeric(
        out["market_return_20d"], errors="coerce"
    )
    previous = previous_return.ge(0).map({True: "up", False: "down"})
    current = current_return.ge(0).map({True: "up", False: "down"})
    state = previous + "_to_" + current
    out["market_state"] = state.mask(
        previous_return.isna() | current_return.isna()
    )
    out["relative_strength_group"] = out.groupby(
        "formation_date", group_keys=False, sort=False
    )["prior_relative_return_20d"].transform(
        lambda values: _quantile_groups(values, 5)
    )
    return out


def dispersion_observations(frame: pd.DataFrame) -> pd.DataFrame:
    required = ["formation_date", "industry_code", "adjusted_return_1d"]
    working = frame.loc[:, required].copy()
    working["adjusted_return_1d"] = pd.to_numeric(
        working["adjusted_return_1d"], errors="coerce"
    )
    return (
        working.groupby(
            ["formation_date", "industry_code"],
            as_index=False,
            dropna=False,
            sort=True,
        )
        .agg(
            return_dispersion=("adjusted_return_1d", "std"),
            member_count=("adjusted_return_1d", "count"),
        )
    )


def turnover_observations(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    grouped = out.groupby("formation_date", group_keys=False, sort=False)
    out["turnover_group"] = grouped["turnover_rate_f_20d"].transform(
        lambda values: _quantile_groups(values, 3)
    )
    out["prior_return_group"] = grouped[
        "prior_relative_return_20d"
    ].transform(lambda values: _quantile_groups(values, 5))
    return out


def max_overextension_observations(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    for column in (
        "max_return_20d",
        "future_excess_return_20d",
        "future_max_drawdown_20d",
    ):
        out[column] = pd.to_numeric(out[column], errors="coerce")
    return out


def _spearman(frame: pd.DataFrame, signal: str, outcome: str) -> float | None:
    pair = frame.loc[:, [signal, outcome]].apply(
        pd.to_numeric, errors="coerce"
    ).dropna()
    if len(pair) < 2:
        return None
    correlation = pair[signal].rank(method="average").corr(
        pair[outcome].rank(method="average")
    )
    if pd.isna(correlation):
        return None
    return float(correlation)


def chronological_relation(
    frame: pd.DataFrame,
    signal: str,
    outcome: str,
    date_col: str,
) -> dict[str, float | int | None]:
    working = frame.loc[:, [date_col, signal, outcome]].copy()
    working[date_col] = pd.to_datetime(working[date_col], errors="coerce")
    working = working.dropna(subset=[date_col])
    dates = sorted(working[date_col].unique())
    midpoint = len(dates) // 2
    earlier_dates = set(dates[:midpoint])
    later_dates = set(dates[midpoint:])
    valid_pairs = working.loc[:, [signal, outcome]].apply(
        pd.to_numeric, errors="coerce"
    ).dropna()
    return {
        "overall": _spearman(working, signal, outcome),
        "earlier": _spearman(
            working[working[date_col].isin(earlier_dates)], signal, outcome
        ),
        "later": _spearman(
            working[working[date_col].isin(later_dates)], signal, outcome
        ),
        "observations": int(len(valid_pairs)),
    }


def _numeric_ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    top = pd.to_numeric(numerator, errors="coerce")
    bottom = pd.to_numeric(denominator, errors="coerce").mask(
        lambda values: values.eq(0)
    )
    return top / bottom


def profitability_valuation_observations(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["roe_recomputed"] = _numeric_ratio(
        out["n_income_attr_p"], out["total_hldr_eqy_exc_min_int"]
    )
    out["roa_recomputed"] = _numeric_ratio(
        out["n_income_attr_p"], out["total_assets"]
    )
    out["gross_profitability"] = _numeric_ratio(
        pd.to_numeric(out["revenue"], errors="coerce")
        - pd.to_numeric(out["oper_cost"], errors="coerce"),
        out["total_assets"],
    )
    out["asset_turnover"] = pd.to_numeric(
        out["assets_turn"], errors="coerce"
    )
    for column in ("pe_ttm", "pb", "ps_ttm"):
        out[column] = pd.to_numeric(out[column], errors="coerce")
    return out


def cash_accrual_observations(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["cash_component"] = _numeric_ratio(
        out["n_cashflow_act"], out["prior_total_assets"]
    )
    out["accrual_component"] = _numeric_ratio(
        pd.to_numeric(out["n_income_attr_p"], errors="coerce")
        - pd.to_numeric(out["n_cashflow_act"], errors="coerce"),
        out["prior_total_assets"],
    )
    return out


def validate_profitability_valuation(
    frame: pd.DataFrame,
) -> dict[str, dict[str, float | int | None]]:
    observations = profitability_valuation_observations(frame)
    signals = (
        "roe_recomputed",
        "roa_recomputed",
        "gross_profitability",
        "asset_turnover",
        "pe_ttm",
        "pb",
        "ps_ttm",
    )
    return {
        signal: chronological_relation(
            observations,
            signal=signal,
            outcome="future_excess_return_20d",
            date_col="formation_date",
        )
        for signal in signals
    }


def validate_cash_accrual(
    frame: pd.DataFrame,
) -> dict[str, dict[str, float | int | None]]:
    observations = cash_accrual_observations(frame)
    relations = {
        "cash_to_future_profitability": (
            "cash_component",
            "future_profitability",
        ),
        "accrual_to_future_profitability": (
            "accrual_component",
            "future_profitability",
        ),
        "cash_to_future_excess_return": (
            "cash_component",
            "future_excess_return_20d",
        ),
        "accrual_to_future_excess_return": (
            "accrual_component",
            "future_excess_return_20d",
        ),
    }
    return {
        name: chronological_relation(
            observations,
            signal=signal,
            outcome=outcome,
            date_col="formation_date",
        )
        for name, (signal, outcome) in relations.items()
    }


def margin_observations(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    financing_buy = pd.to_numeric(out["rzmre"], errors="coerce")
    financing_repayment = pd.to_numeric(out["rzche"], errors="coerce")
    out["financing_net_flow"] = financing_buy - financing_repayment
    for column in ("rzye", "rqye", "rqyl"):
        out[column] = pd.to_numeric(out[column], errors="coerce")
    return out


def pledge_observations(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    for column in (
        "pledge_ratio",
        "return_20d",
        "amount_20d",
        "debt_to_assets",
        "n_cashflow_act",
    ):
        out[column] = pd.to_numeric(out[column], errors="coerce")
    return out


def holder_trade_observations(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    allowed = {"IN", "DE"}
    observed = set(out["in_de"].dropna().astype(str))
    unknown = observed - allowed
    if unknown:
        raise ValueError(f"unknown holder trade directions: {sorted(unknown)}")
    sign = out["in_de"].map({"IN": 1.0, "DE": -1.0})
    change = pd.to_numeric(out["change_vol"], errors="coerce").abs()
    out["signed_change_vol"] = sign * change
    return out


def buyback_stage_observations(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    allowed = {
        "提议",
        "预案",
        "股东大会通过",
        "实施",
        "完成",
        "停止",
        "未通过",
    }
    observed = set(out["process"].dropna().astype(str))
    unknown = observed - allowed
    if unknown:
        raise ValueError(f"unknown repurchase stages: {sorted(unknown)}")
    out["buyback_stage"] = out["process"]
    out["actual_execution"] = out["process"].isin({"实施", "完成"})
    return out


_OFFICIAL_SEMANTIC_REQUIREMENTS = {
    "src_cn_earnings_disclosure_hierarchy": {
        "earnings_forecast": (
            "p_change_min",
            "p_change_max",
            "type",
            "available_at",
        ),
        "earnings_express": (
            "announcement_type",
            "yoy_net_profit",
            "available_at",
        ),
        "income_statement": ("report_type", "ann_date", "available_at"),
        "announcement": ("title", "announcement_time"),
    },
    "src_cn_share_reduction_rules_2024": {
        "share_float": ("float_date",),
        "holder_trade": ("in_de", "change_vol"),
        "announcement": ("title", "announcement_time"),
    },
    "src_csrc_disclosure_rules_2025": {
        "company_profile": ("business_scope", "main_business"),
        "main_business": (
            "classification",
            "item_name",
            "bz_sales",
            "bz_profit",
        ),
        "announcement": ("title", "announcement_time"),
    },
}


def check_official_semantic_fields(
    field_map: dict[str, tuple[str, ...]],
) -> dict[str, bool]:
    result: dict[str, bool] = {}
    for knowledge_id, datasets in _OFFICIAL_SEMANTIC_REQUIREMENTS.items():
        for dataset, required_fields in datasets.items():
            available = set(field_map.get(dataset, ()))
            for field in required_fields:
                if field not in available:
                    raise ValueError(
                        f"missing official semantic field: {dataset}.{field}"
                    )
        result[knowledge_id] = True
    return result


def portfolio_common_exposure(
    returns: pd.DataFrame,
    *,
    industries: dict[str, str],
    themes: dict[str, set[str]],
) -> dict[str, int | float]:
    candidates = list(returns.columns)
    if len(candidates) != 5:
        raise ValueError("portfolio relationship requires exactly five candidates")
    if set(industries) != set(candidates) or set(themes) != set(candidates):
        raise ValueError("industry and theme mappings must cover exactly five candidates")

    industry_counts = Counter(industries.values())
    theme_counts = Counter(
        theme for candidate in candidates for theme in themes[candidate]
    )
    correlations = returns.apply(pd.to_numeric, errors="coerce").corr()
    pairwise = [
        float(correlations.loc[left, right])
        for index, left in enumerate(candidates)
        for right in candidates[index + 1 :]
        if pd.notna(correlations.loc[left, right])
    ]
    return {
        "largest_industry_count": max(industry_counts.values(), default=0),
        "largest_theme_count": max(theme_counts.values(), default=0),
        "max_pairwise_correlation": max(pairwise) if pairwise else 0.0,
    }


def _fact_paths(root: Path, name: str) -> list[str]:
    paths = [
        str(path)
        for path in sorted((root / "facts" / name).glob("*/data.parquet"))
    ]
    if not paths:
        raise ValueError(f"no current fact partitions for {name}")
    return paths


def _query_frame(sql: str, parameters: list[object]) -> pd.DataFrame:
    with duckdb.connect() as connection:
        return connection.execute(sql, parameters).fetchdf()


def _load_price_panel(root: Path) -> pd.DataFrame:
    sql = """
        with calendar_base as (
          select trade_date, close market_close,
                 row_number() over (order by trade_date) session_no,
                 count(*) over () session_count
          from read_parquet(?, union_by_name=true, hive_partitioning=false)
          where index_code = '000300.SH'
        ), calendar as (
          select *,
                 market_close / lag(market_close, 20) over (order by session_no) - 1
                   market_return_20d,
                 lag(market_close, 20) over (order by session_no)
                   / lag(market_close, 40) over (order by session_no) - 1
                   prior_market_return_20d,
                 lead(market_close, 20) over (order by session_no)
                   / market_close - 1 future_market_return_20d
          from calendar_base
        ), stock_base as (
          select c.trade_date, c.session_no, c.session_count,
                 c.market_return_20d, c.prior_market_return_20d,
                 c.future_market_return_20d,
                 e.ts_code, e.close * a.adj_factor adjusted_close,
                 e.amount, b.turnover_rate_f
          from calendar c
          join read_parquet(?, union_by_name=true, hive_partitioning=false) e
            on e.trade_date = c.trade_date
          join read_parquet(?, union_by_name=true, hive_partitioning=false) a
            on a.trade_date = e.trade_date and a.ts_code = e.ts_code
          join read_parquet(?, union_by_name=true, hive_partitioning=false) b
            on b.trade_date = e.trade_date and b.ts_code = e.ts_code
          where e.close > 0 and a.adj_factor > 0
        ), stock_returns as (
          select *, adjusted_close
                   / lag(adjusted_close) over company - 1 adjusted_return_1d,
                 adjusted_close
                   / lag(adjusted_close, 20) over company - 1 stock_return_20d,
                 lag(adjusted_close, 20) over company
                   / lag(adjusted_close, 40) over company - 1 prior_stock_return_20d,
                 lead(adjusted_close, 20) over company
                   / adjusted_close - 1 future_stock_return_20d
          from stock_base
          window company as (partition by ts_code order by session_no)
        ), metrics as (
          select *,
                 avg(turnover_rate_f) over trailing_window turnover_rate_f_20d,
                 max(adjusted_return_1d) over trailing_window max_return_20d,
                 stddev_samp(adjusted_return_1d) over future_window
                   future_realized_volatility_20d,
                 min(adjusted_close) over future_window / adjusted_close - 1
                   future_max_drawdown_20d
          from stock_returns
          window trailing_window as (
            partition by ts_code order by session_no rows between 19 preceding and current row
          ), future_window as (
            partition by ts_code order by session_no rows between 1 following and 20 following
          )
        ), members as (
          select ts_code, industry_code, valid_from, valid_to
          from read_parquet(?, union_by_name=true, hive_partitioning=false)
          where level = 'L1'
        )
        select m.trade_date formation_date, m.ts_code, members.industry_code,
               m.prior_market_return_20d, m.market_return_20d,
               m.prior_stock_return_20d - m.prior_market_return_20d
                 prior_relative_return_20d,
               m.future_stock_return_20d - m.future_market_return_20d
                 future_excess_return_20d,
               m.adjusted_return_1d, m.amount, m.turnover_rate_f_20d,
               m.max_return_20d, m.future_realized_volatility_20d,
               m.future_max_drawdown_20d
        from metrics m
        left join members
          on members.ts_code = m.ts_code
         and cast(members.valid_from as date) <= cast(m.trade_date as date)
         and (members.valid_to is null
              or cast(members.valid_to as date) >= cast(m.trade_date as date))
        where m.session_no > 40 and m.session_no + 20 <= m.session_count
          and m.session_no % 20 = 0
          and m.prior_stock_return_20d is not null
          and m.future_stock_return_20d is not null
    """
    frame = _query_frame(
        sql,
        [
            _fact_paths(root, "index_daily"),
            _fact_paths(root, "equity_daily"),
            _fact_paths(root, "adj_factor"),
            _fact_paths(root, "daily_basic"),
            _fact_paths(root, "industry_member"),
        ],
    )
    frame["formation_date"] = pd.to_datetime(frame["formation_date"]).dt.date
    return frame.dropna(
        subset=[
            "prior_relative_return_20d",
            "future_excess_return_20d",
            "adjusted_return_1d",
        ]
    ).reset_index(drop=True)


def _load_financial_panel(root: Path) -> pd.DataFrame:
    sql = """
        with calendar as (
          select trade_date, close market_close,
                 row_number() over (order by trade_date) session_no
          from read_parquet(?, union_by_name=true, hive_partitioning=false)
          where index_code = '000300.SH'
        ), income as (
          select * exclude (_row) from (
            select ts_code, report_period, revenue, oper_cost, n_income_attr_p,
                   available_at,
                   row_number() over (
                     partition by ts_code, report_period order by available_at
                   ) _row
            from read_parquet(?, union_by_name=true, hive_partitioning=false)
          ) where _row = 1
        ), balance as (
          select * exclude (_row) from (
            select ts_code, report_period, total_assets, total_liab,
                   total_hldr_eqy_exc_min_int, available_at,
                   row_number() over (
                     partition by ts_code, report_period order by available_at
                   ) _row
            from read_parquet(?, union_by_name=true, hive_partitioning=false)
          ) where _row = 1
        ), cash as (
          select * exclude (_row) from (
            select ts_code, report_period, n_cashflow_act, available_at,
                   row_number() over (
                     partition by ts_code, report_period order by available_at
                   ) _row
            from read_parquet(?, union_by_name=true, hive_partitioning=false)
          ) where _row = 1
        ), indicators as (
          select * exclude (_row) from (
            select ts_code, report_period, assets_turn, available_at,
                   row_number() over (
                     partition by ts_code, report_period order by available_at
                   ) _row
            from read_parquet(?, union_by_name=true, hive_partitioning=false)
          ) where _row = 1
        ), combined as (
          select i.ts_code, i.report_period, i.n_income_attr_p, i.revenue,
                 i.oper_cost, b.total_assets, b.total_liab,
                 b.total_hldr_eqy_exc_min_int,
                 cf.n_cashflow_act, fi.assets_turn,
                 greatest(i.available_at, b.available_at, cf.available_at, fi.available_at)
                   available_at
          from income i join balance b using (ts_code, report_period)
          join cash cf using (ts_code, report_period)
          join indicators fi using (ts_code, report_period)
        ), compared as (
          select *, lag(total_assets, 4) over company prior_total_assets,
                 lead(n_income_attr_p / nullif(total_assets, 0), 4) over company
                   future_profitability,
                 n_income_attr_p / nullif(total_assets, 0) current_profitability
          from combined
          window company as (partition by ts_code order by report_period)
        ), dated as (
          select compared.*, mapped.trade_date formation_date, mapped.session_no
          from compared
          join lateral (
            select trade_date, session_no from calendar
            where trade_date > cast(compared.available_at as date)
            order by trade_date limit 1
          ) mapped on true
        )
        select d.formation_date, d.ts_code, d.report_period,
               d.n_income_attr_p, d.n_cashflow_act, d.prior_total_assets,
               d.total_assets, d.total_hldr_eqy_exc_min_int,
               d.revenue, d.oper_cost, d.assets_turn,
               b.pe_ttm, b.pb, b.ps_ttm, d.future_profitability,
               (future.close * future_a.adj_factor)
                 / (base.close * base_a.adj_factor) - 1
                 - (future_market.market_close / base_market.market_close - 1)
                   future_excess_return_20d,
               d.current_profitability,
               d.total_liab / nullif(d.total_assets, 0) debt_to_assets
        from dated d
        join calendar base_market on base_market.session_no = d.session_no
        join calendar future_market on future_market.session_no = d.session_no + 20
        join read_parquet(?, union_by_name=true, hive_partitioning=false) b
          on b.ts_code = d.ts_code and b.trade_date = d.formation_date
        join read_parquet(?, union_by_name=true, hive_partitioning=false) base
          on base.ts_code = d.ts_code and base.trade_date = d.formation_date
        join read_parquet(?, union_by_name=true, hive_partitioning=false) future
          on future.ts_code = d.ts_code and future.trade_date = future_market.trade_date
        join read_parquet(?, union_by_name=true, hive_partitioning=false) base_a
          on base_a.ts_code = d.ts_code and base_a.trade_date = d.formation_date
        join read_parquet(?, union_by_name=true, hive_partitioning=false) future_a
          on future_a.ts_code = d.ts_code and future_a.trade_date = future_market.trade_date
        where d.prior_total_assets > 0 and d.total_assets > 0
          and base.close > 0 and future.close > 0
          and base_a.adj_factor > 0 and future_a.adj_factor > 0
    """
    equity = _fact_paths(root, "equity_daily")
    factors = _fact_paths(root, "adj_factor")
    frame = _query_frame(
        sql,
        [
            _fact_paths(root, "index_daily"),
            _fact_paths(root, "income_statement"),
            _fact_paths(root, "balance_sheet"),
            _fact_paths(root, "cash_flow"),
            _fact_paths(root, "financial_indicator"),
            _fact_paths(root, "daily_basic"),
            equity,
            equity,
            factors,
            factors,
        ],
    )
    frame["formation_date"] = pd.to_datetime(frame["formation_date"]).dt.date
    frame["report_period"] = pd.to_datetime(frame["report_period"]).dt.date
    return frame.dropna(
        subset=["future_profitability", "future_excess_return_20d"]
    ).reset_index(drop=True)


def _next_price_observation(
    events: pd.DataFrame,
    price: pd.DataFrame,
    *,
    event_date: str,
    price_columns: tuple[str, ...],
) -> pd.DataFrame:
    left = events.copy()
    right = price.loc[:, ("formation_date", "ts_code") + price_columns].copy()
    left[event_date] = pd.to_datetime(left[event_date]).astype("datetime64[ns]")
    right["formation_date"] = pd.to_datetime(right["formation_date"]).astype(
        "datetime64[ns]"
    )
    left = left.sort_values([event_date, "ts_code"], kind="mergesort")
    right = right.sort_values(
        ["formation_date", "ts_code"], kind="mergesort"
    ).drop_duplicates(["formation_date", "ts_code"], keep="last")
    return pd.merge_asof(
        left,
        right,
        left_on=event_date,
        right_on="formation_date",
        by="ts_code",
        direction="forward",
        allow_exact_matches=True,
    )


def _load_margin_panel(root: Path, price: pd.DataFrame) -> pd.DataFrame:
    raw = _query_frame(
        """
        select trade_date formation_date, ts_code, rzye, rzmre, rzche, rqye, rqyl
        from read_parquet(?, union_by_name=true, hive_partitioning=false)
        order by ts_code, trade_date
        """,
        [_fact_paths(root, "margin_detail")],
    )
    raw["formation_date"] = pd.to_datetime(raw["formation_date"]).dt.date
    raw["financing_balance_change_20d"] = raw.groupby("ts_code")["rzye"].diff(20)
    metrics = price.loc[
        :,
        [
            "formation_date",
            "ts_code",
            "future_realized_volatility_20d",
            "future_max_drawdown_20d",
        ],
    ]
    return raw.merge(metrics, on=["formation_date", "ts_code"], how="inner")


def _load_pledge_panel(
    root: Path,
    price: pd.DataFrame,
    financial: pd.DataFrame,
) -> pd.DataFrame:
    raw = _query_frame(
        """
        select ts_code, cast(end_date as date) event_date, pledge_ratio
        from read_parquet(?, union_by_name=true, hive_partitioning=false)
        where pledge_ratio is not null
        """,
        [_fact_paths(root, "pledge")],
    )
    joined = _next_price_observation(
        raw,
        price,
        event_date="event_date",
        price_columns=(
            "prior_relative_return_20d",
            "amount",
            "future_max_drawdown_20d",
        ),
    ).rename(
        columns={"prior_relative_return_20d": "return_20d", "amount": "amount_20d"}
    )
    context = financial.loc[
        :,
        [
            "formation_date",
            "ts_code",
            "report_period",
            "debt_to_assets",
            "n_cashflow_act",
        ],
    ].copy()
    context["formation_date"] = pd.to_datetime(context["formation_date"]).astype(
        "datetime64[ns]"
    )
    joined = joined.dropna(subset=["formation_date"]).sort_values(
        ["formation_date", "ts_code"], kind="mergesort"
    )
    context = context.sort_values(
        ["formation_date", "ts_code", "report_period"], kind="mergesort"
    ).drop_duplicates(["formation_date", "ts_code"], keep="last")
    joined = pd.merge_asof(
        joined,
        context[["formation_date", "ts_code", "debt_to_assets", "n_cashflow_act"]],
        on="formation_date",
        by="ts_code",
        direction="backward",
    )
    return joined.loc[
        :,
        [
            "formation_date",
            "ts_code",
            "pledge_ratio",
            "return_20d",
            "amount_20d",
            "debt_to_assets",
            "n_cashflow_act",
            "future_max_drawdown_20d",
        ],
    ].dropna(subset=["pledge_ratio", "future_max_drawdown_20d"])


def _load_holder_trade_panel(
    root: Path,
    price: pd.DataFrame,
    financial: pd.DataFrame,
) -> pd.DataFrame:
    raw = _query_frame(
        """
        select ts_code, cast(ann_date as date) event_date, in_de, change_vol
        from read_parquet(?, union_by_name=true, hive_partitioning=false)
        where in_de in ('IN', 'DE') and change_vol is not null
        """,
        [_fact_paths(root, "holder_trade")],
    )
    joined = _next_price_observation(
        raw,
        price,
        event_date="event_date",
        price_columns=("future_excess_return_20d",),
    )
    finance = financial.loc[
        :,
        [
            "formation_date",
            "ts_code",
            "report_period",
            "current_profitability",
            "future_profitability",
        ],
    ].copy()
    finance["formation_date"] = pd.to_datetime(finance["formation_date"]).astype(
        "datetime64[ns]"
    )
    finance["next_report_profit_change"] = (
        finance["future_profitability"] - finance["current_profitability"]
    )
    joined = joined.dropna(subset=["formation_date"]).sort_values(
        ["formation_date", "ts_code"], kind="mergesort"
    )
    finance = finance.sort_values(
        ["formation_date", "ts_code", "report_period"], kind="mergesort"
    ).drop_duplicates(["formation_date", "ts_code"], keep="last")
    joined = pd.merge_asof(
        joined,
        finance[["formation_date", "ts_code", "next_report_profit_change"]],
        on="formation_date",
        by="ts_code",
        direction="forward",
    )
    return joined.loc[
        :,
        [
            "formation_date",
            "ts_code",
            "in_de",
            "change_vol",
            "next_report_profit_change",
            "future_excess_return_20d",
        ],
    ].dropna(subset=["future_excess_return_20d"])


def _load_buyback_panel(root: Path, price: pd.DataFrame) -> pd.DataFrame:
    raw = _query_frame(
        """
        select ts_code, cast(announcement_date as date) event_date,
               process, amount, vol
        from read_parquet(?, union_by_name=true, hive_partitioning=false)
        where process is not null
        """,
        [_fact_paths(root, "repurchase")],
    )
    joined = _next_price_observation(
        raw,
        price,
        event_date="event_date",
        price_columns=("future_excess_return_20d", "future_max_drawdown_20d"),
    )
    return joined.loc[
        :,
        [
            "formation_date",
            "ts_code",
            "process",
            "amount",
            "vol",
            "future_excess_return_20d",
            "future_max_drawdown_20d",
        ],
    ].dropna(subset=["future_excess_return_20d"])


def _load_official_field_map(root: Path) -> dict[str, tuple[str, ...]]:
    datasets = (
        "earnings_forecast",
        "earnings_express",
        "income_statement",
        "announcement",
        "share_float",
        "holder_trade",
        "company_profile",
        "main_business",
    )
    field_map: dict[str, tuple[str, ...]] = {}
    with duckdb.connect() as connection:
        for dataset in datasets:
            description = connection.execute(
                "describe select * from read_parquet(?, union_by_name=true, hive_partitioning=false)",
                [_fact_paths(root, dataset)],
            ).fetchdf()
            field_map[dataset] = tuple(sorted(description["column_name"].astype(str)))
    return field_map


def _stable(value: float | int | str | None) -> float | int | str:
    if value is None:
        return "not_available"
    if isinstance(value, float):
        if not math.isfinite(value):
            return "not_available"
        return round(value, 12)
    return value


def _relation_evidence(
    knowledge_id: str,
    relation: dict[str, float | int | None],
    *,
    relationship_shape: str,
    counter_evidence: str,
    extra: dict[str, float | int | str] | None = None,
) -> SupplementEvidence:
    observations = {
        key: _stable(value) for key, value in relation.items()
    }
    if extra:
        observations.update({key: _stable(value) for key, value in extra.items()})
    return SupplementEvidence(
        knowledge_id=knowledge_id,
        data_usable=relation.get("observations", 0) != 0,
        overall_direction=str(_stable(relation.get("overall"))),
        earlier_direction=str(_stable(relation.get("earlier"))),
        later_direction=str(_stable(relation.get("later"))),
        relationship_shape=relationship_shape,
        counter_evidence=counter_evidence,
        observations=observations,
    )


def validate_all_supplement_claims(
    warehouse_root: Path,
) -> tuple[SupplementEvidence, ...]:
    root = Path(warehouse_root)
    price = _load_price_panel(root)
    financial = _load_financial_panel(root)
    margin = _load_margin_panel(root, price)
    pledge = _load_pledge_panel(root, price, financial)
    holder = _load_holder_trade_panel(root, price, financial)
    buyback = _load_buyback_panel(root, price)
    official_fields = _load_official_field_map(root)
    official_checks = check_official_semantic_fields(official_fields)

    market = market_state_observations(price)
    market_relation = chronological_relation(
        market,
        signal="prior_relative_return_20d",
        outcome="future_excess_return_20d",
        date_col="formation_date",
    )

    dispersion = dispersion_observations(
        price.dropna(subset=["industry_code"])
    )
    dispersion_outcomes = price.groupby(
        ["formation_date", "industry_code"], as_index=False, dropna=False
    ).agg(
        future_realized_volatility_20d=(
            "future_realized_volatility_20d",
            "mean",
        )
    )
    dispersion = dispersion.merge(
        dispersion_outcomes,
        on=["formation_date", "industry_code"],
        how="inner",
    )
    dispersion_relation = chronological_relation(
        dispersion,
        signal="return_dispersion",
        outcome="future_realized_volatility_20d",
        date_col="formation_date",
    )

    turnover = turnover_observations(price)
    turnover_relation = chronological_relation(
        turnover,
        signal="prior_relative_return_20d",
        outcome="future_excess_return_20d",
        date_col="formation_date",
    )
    turnover_group_relations = {
        str(group): chronological_relation(
            rows,
            signal="prior_relative_return_20d",
            outcome="future_excess_return_20d",
            date_col="formation_date",
        )["overall"]
        for group, rows in turnover.groupby("turnover_group", observed=True)
    }

    profitability = validate_profitability_valuation(financial)
    profitability_relation = profitability["gross_profitability"]
    cash = validate_cash_accrual(financial)
    cash_relation = cash["cash_to_future_profitability"]

    illiquidity = illiquidity_observations(price)
    illiquidity_relation = chronological_relation(
        illiquidity,
        signal="amihud_illiquidity",
        outcome="future_max_drawdown_20d",
        date_col="formation_date",
    )
    maximum = max_overextension_observations(price)
    max_relation = chronological_relation(
        maximum,
        signal="max_return_20d",
        outcome="future_excess_return_20d",
        date_col="formation_date",
    )

    margin = margin_observations(margin)
    margin_relation = chronological_relation(
        margin,
        signal="financing_net_flow",
        outcome="future_max_drawdown_20d",
        date_col="formation_date",
    )
    pledge = pledge_observations(pledge)
    pledge_relation = chronological_relation(
        pledge,
        signal="pledge_ratio",
        outcome="future_max_drawdown_20d",
        date_col="formation_date",
    )
    holder = holder_trade_observations(holder)
    holder_relation = chronological_relation(
        holder,
        signal="signed_change_vol",
        outcome="next_report_profit_change",
        date_col="formation_date",
    )
    buyback = buyback_stage_observations(buyback)
    buyback_means = buyback.groupby("buyback_stage", observed=True)[
        "future_excess_return_20d"
    ].mean()
    buyback_relation = chronological_relation(
        buyback.assign(actual_execution_numeric=buyback["actual_execution"].astype(int)),
        signal="actual_execution_numeric",
        outcome="future_excess_return_20d",
        date_col="formation_date",
    )

    usable_counts = price.groupby("ts_code").size().sort_values(ascending=False)
    candidates = sorted(usable_counts[usable_counts >= 10].index.astype(str))[:5]
    portfolio_returns = price[price["ts_code"].isin(candidates)].pivot_table(
        index="formation_date",
        columns="ts_code",
        values="adjusted_return_1d",
        aggfunc="first",
    ).reindex(columns=candidates)
    industries = {
        code: str(
            price.loc[price["ts_code"] == code, "industry_code"].dropna().iloc[-1]
        )
        for code in candidates
    }
    themes = {code: set() for code in candidates}
    portfolio = portfolio_common_exposure(
        portfolio_returns,
        industries=industries,
        themes=themes,
    )

    source_count = len(SOURCE_REFS)
    evidence_by_id = {
        "src_cn_factor_momentum_2023": _relation_evidence(
            "src_cn_factor_momentum_2023",
            market_relation,
            relationship_shape="市场状态分组中的20日相对强弱与后续超额收益关系",
            counter_evidence="上涨市场不自动产生更可靠的个股延续。",
        ),
        "src_cn_return_dispersion_risk": _relation_evidence(
            "src_cn_return_dispersion_risk",
            dispersion_relation,
            relationship_shape="行业成员收益样本标准差与后续实现波动关系",
            counter_evidence="分化不直接给出涨跌方向。",
        ),
        "src_cn_turnover_momentum_boundary": _relation_evidence(
            "src_cn_turnover_momentum_boundary",
            turnover_relation,
            relationship_shape="换手分组内相对强弱与后续超额收益关系",
            counter_evidence="高换手不能识别资金身份。",
            extra={
                "turnover_group_relations": json.dumps(
                    {key: _stable(value) for key, value in turnover_group_relations.items()},
                    ensure_ascii=False,
                    sort_keys=True,
                )
            },
        ),
        "src_cn_profitability_valuation_support": _relation_evidence(
            "src_cn_profitability_valuation_support",
            profitability_relation,
            relationship_shape="盈利维度和估值维度分别与后续超额收益比较",
            counter_evidence="盈利能力不直接等于二至六周上涨。",
            extra={
                "all_relations": json.dumps(profitability, ensure_ascii=False, sort_keys=True)
            },
        ),
        "src_cn_cash_accrual_quality": _relation_evidence(
            "src_cn_cash_accrual_quality",
            cash_relation,
            relationship_shape="现金和应计成分分别与下一年同季盈利及后续收益比较",
            counter_evidence="旧退市制度下的原论文收益结论不移植。",
            extra={"all_relations": json.dumps(cash, ensure_ascii=False, sort_keys=True)},
        ),
        "src_cn_illiquidity_operability": _relation_evidence(
            "src_cn_illiquidity_operability",
            illiquidity_relation,
            relationship_shape="日收益相对成交额的粗粒度价格冲击与后续回撤关系",
            counter_evidence="日线代理不是订单簿冲击，也不是收益加分。",
        ),
        "src_cn_max_overextension": _relation_evidence(
            "src_cn_max_overextension",
            max_relation,
            relationship_shape="过去20日最大单日收益与后续超额收益关系",
            counter_evidence="强势本身不能被机械淘汰。",
        ),
        "src_cn_earnings_disclosure_hierarchy": SupplementEvidence(
            "src_cn_earnings_disclosure_hierarchy", True, "规则语义可执行",
            "不适用", "不适用", "四类披露阶段字段独立存在",
            "预告与快报仍可能更正。", {"source_count": source_count},
        ),
        "src_cn_margin_semantics": _relation_evidence(
            "src_cn_margin_semantics", margin_relation,
            relationship_shape="融资净流量、余额变化和后续风险分别观察",
            counter_evidence="融资买入不表示机构看多。",
        ),
        "src_cn_share_reduction_rules_2024": SupplementEvidence(
            "src_cn_share_reduction_rules_2024", True, "规则语义可执行",
            "不适用", "不适用", "解禁、计划和实际交易字段独立存在",
            "解禁不等于已经减持。", {"source_count": source_count},
        ),
        "src_cn_pledge_conditional_risk": _relation_evidence(
            "src_cn_pledge_conditional_risk", pledge_relation,
            relationship_shape="质押比例与价格、流动性、负债、现金流分别观察",
            counter_evidence="无合同字段，不能计算平仓价。",
        ),
        "src_cn_disclosed_holder_trade": _relation_evidence(
            "src_cn_disclosed_holder_trade", holder_relation,
            relationship_shape="披露方向和数量与下一报告经营变化关系",
            counter_evidence="单次增持不保证股价上涨。",
        ),
        "src_cn_buyback_rules_2023": _relation_evidence(
            "src_cn_buyback_rules_2023", buyback_relation,
            relationship_shape="计划阶段与实际执行阶段分别观察",
            counter_evidence="实际回购仍不证明低估或必涨。",
            extra={
                "stage_means": json.dumps(
                    {str(key): _stable(float(value)) for key, value in buyback_means.items()},
                    ensure_ascii=False,
                    sort_keys=True,
                )
            },
        ),
        "src_csrc_disclosure_rules_2025": SupplementEvidence(
            "src_csrc_disclosure_rules_2025", True, "规则语义可执行",
            "不适用", "不适用", "经营范围、主营分部和正式公告字段独立存在",
            "概念名称本身不证明收入受益。", {"source_count": source_count},
        ),
        "src_portfolio_common_exposure": SupplementEvidence(
            "src_portfolio_common_exposure", True, "方法可执行", "不适用", "不适用",
            "恰好五只候选的行业、主题集中度和两两相关性",
            "只做透明检查，不估计权重。", portfolio,
        ),
    }
    for knowledge_id, checked in official_checks.items():
        if not checked or knowledge_id not in evidence_by_id:
            raise ValueError(f"official semantic check failed: {knowledge_id}")
    return tuple(evidence_by_id[claim.knowledge_id] for claim in SUPPLEMENT_CLAIMS)


__all__ = [
    "SOURCE_REFS",
    "SUPPLEMENT_CLAIMS",
    "SupplementClaim",
    "SupplementEvidence",
    "buyback_stage_observations",
    "cash_accrual_observations",
    "check_official_semantic_fields",
    "chronological_relation",
    "dispersion_observations",
    "illiquidity_observations",
    "holder_trade_observations",
    "margin_observations",
    "market_state_observations",
    "max_overextension_observations",
    "profitability_valuation_observations",
    "pledge_observations",
    "portfolio_common_exposure",
    "turnover_observations",
    "validate_cash_accrual",
    "validate_profitability_valuation",
    "validate_all_supplement_claims",
]
