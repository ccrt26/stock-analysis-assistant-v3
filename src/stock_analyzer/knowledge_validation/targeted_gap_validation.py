from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from stock_analyzer.data.research_contracts import ResearchDatasetId


@dataclass(frozen=True)
class TargetedGapClaim:
    knowledge_id: str
    core_theory: str
    source_refs: tuple[str, ...]
    required_facts: tuple[ResearchDatasetId, ...]


@dataclass(frozen=True)
class TargetedGapEvidence:
    knowledge_id: str
    data_usable: bool
    overall_direction: str
    earlier_direction: str
    later_direction: str
    counter_evidence: str
    observations: dict[str, int | float | str]


TARGETED_SOURCE_REFS = frozenset(
    {
        "https://kjs.mof.gov.cn/zt/kjzzss/kuaijizhunzeshishi/200806/"
        "t20080618_46246.htm",
        "10.1016/j.pacfin.2018.10.017",
        "10.1016/j.pacfin.2021.101607",
        "10.1287/mnsc.2023.4904",
        "10.1016/j.irfa.2023.102770",
        "10.1016/j.jacceco.2010.09.001",
    }
)


TARGETED_GAP_CLAIMS = (
    TargetedGapClaim(
        knowledge_id="src_cn_business_segment_materiality",
        core_theory=(
            "公司与热点存在真实联系，不仅需要正式资料证明业务存在，还要核对相关产品或业务分部对收入、成本、"
            "利润和整体经营的实际贡献；概念名称、规划、研发或小额业务不能自动推导为公司整体明显受益。"
        ),
        source_refs=(
            "https://kjs.mof.gov.cn/zt/kjzzss/kuaijizhunzeshishi/200806/"
            "t20080618_46246.htm",
        ),
        required_facts=(
            ResearchDatasetId.COMPANY_PROFILE,
            ResearchDatasetId.MAIN_BUSINESS,
            ResearchDatasetId.INCOME_STATEMENT,
            ResearchDatasetId.ANNOUNCEMENT,
        ),
    ),
    TargetedGapClaim(
        knowledge_id="src_cn_earnings_growth_persistence",
        core_theory=(
            "单期净利润增长不能证明经营趋势成立，需要把总收入、营业利润、归母净利润、经营现金流、毛利率和费用"
            "变化放在连续可比报告期中观察，并区分行业共同变化和公司特有变化，不能把同比增长写成超预期。"
        ),
        source_refs=("10.1016/j.pacfin.2018.10.017",),
        required_facts=(
            ResearchDatasetId.INCOME_STATEMENT,
            ResearchDatasetId.BALANCE_SHEET,
            ResearchDatasetId.CASH_FLOW,
            ResearchDatasetId.FINANCIAL_INDICATOR,
            ResearchDatasetId.INDUSTRY_MEMBER,
        ),
    ),
    TargetedGapClaim(
        knowledge_id="src_cn_relative_valuation_context",
        core_theory=(
            "市盈率、市净率和市销率只有在盈利状态、行业、规模和公司自身历史可比时才有解释意义；估值用于判断市场"
            "已经反映了多少预期和候选承担多高兑现要求，低估值或高估值都不能单独预测未来收益。"
        ),
        source_refs=(
            "10.1016/j.pacfin.2021.101607",
            "10.1287/mnsc.2023.4904",
        ),
        required_facts=(
            ResearchDatasetId.DAILY_BASIC,
            ResearchDatasetId.INDUSTRY_MEMBER,
            ResearchDatasetId.INCOME_STATEMENT,
            ResearchDatasetId.BALANCE_SHEET,
            ResearchDatasetId.CASH_FLOW,
            ResearchDatasetId.FINANCIAL_INDICATOR,
        ),
    ),
    TargetedGapClaim(
        knowledge_id="src_cn_turnaround_financial_consistency",
        core_theory=(
            "困境反转不能只看利润转正，需要同时检查经营结果、经营现金、短期流动性、偿债压力、应收存货、资产减值"
            "和一次性损益；某一维度改善而其他关键维度继续恶化，只能说明局部改善而非反转完成。"
        ),
        source_refs=(
            "10.1016/j.irfa.2023.102770",
            "10.1016/j.jacceco.2010.09.001",
        ),
        required_facts=(
            ResearchDatasetId.INCOME_STATEMENT,
            ResearchDatasetId.BALANCE_SHEET,
            ResearchDatasetId.CASH_FLOW,
            ResearchDatasetId.FINANCIAL_INDICATOR,
        ),
    ),
)


def business_segment_materiality_observations(
    frame: pd.DataFrame,
) -> pd.DataFrame:
    required = {
        "ts_code",
        "report_period",
        "classification",
        "item_name",
        "curr_type",
        "company_curr_type",
        "bz_sales",
        "bz_cost",
        "bz_profit",
        "company_revenue",
        "company_operating_profit",
    }
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"missing business segment columns: {', '.join(missing)}")

    result = frame.copy()
    result["report_period"] = pd.to_datetime(result["report_period"])
    numeric = (
        "bz_sales",
        "bz_cost",
        "bz_profit",
        "company_revenue",
        "company_operating_profit",
    )
    for column in numeric:
        result[column] = pd.to_numeric(result[column], errors="coerce")

    currency_comparable = (
        result["curr_type"].notna()
        & result["company_curr_type"].notna()
        & result["curr_type"].eq(result["company_curr_type"])
    )
    valid_sales = currency_comparable & result["company_revenue"].gt(0)
    valid_profit = currency_comparable & result["company_operating_profit"].ne(0)
    valid_margin = currency_comparable & result["bz_sales"].gt(0)

    result["sales_share"] = np.where(
        valid_sales,
        result["bz_sales"] / result["company_revenue"],
        np.nan,
    )
    result["profit_share"] = np.where(
        valid_profit,
        result["bz_profit"] / result["company_operating_profit"],
        np.nan,
    )
    result["gross_margin"] = np.where(
        valid_margin,
        (result["bz_sales"] - result["bz_cost"]) / result["bz_sales"],
        np.nan,
    )
    result["ratio_status"] = np.select(
        [~currency_comparable, valid_sales & valid_profit & valid_margin],
        ["currency_mismatch", "comparable"],
        default="invalid_denominator",
    )
    return result.sort_values(
        ["ts_code", "report_period", "classification", "item_name"],
        kind="mergesort",
    ).reset_index(drop=True)


def earnings_growth_persistence_observations(
    frame: pd.DataFrame,
) -> pd.DataFrame:
    required = {
        "ts_code",
        "report_period",
        "industry_code",
        "revenue",
        "operate_profit",
        "n_income_attr_p",
        "n_cashflow_act",
        "total_assets",
        "grossprofit_margin",
        "expense_rate",
    }
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"missing earnings history columns: {', '.join(missing)}")

    result = frame.copy()
    result["report_period"] = pd.to_datetime(result["report_period"])
    numeric = required.difference(
        {"ts_code", "report_period", "industry_code"}
    )
    for column in numeric:
        result[column] = pd.to_numeric(result[column], errors="coerce")
    result = result.sort_values(
        ["ts_code", "report_period"], kind="mergesort"
    ).reset_index(drop=True)
    company = result.groupby("ts_code", sort=False)
    prior_assets = company["total_assets"].shift(4)

    component_map = {
        "revenue": "revenue_change_scaled",
        "operate_profit": "operating_profit_change_scaled",
        "n_income_attr_p": "net_income_change_scaled",
        "n_cashflow_act": "operating_cash_change_scaled",
    }
    for source, target in component_map.items():
        prior = company[source].shift(4)
        result[target] = (result[source] - prior) / prior_assets.where(
            prior_assets.gt(0)
        )
    result["gross_margin_change"] = (
        result["grossprofit_margin"] - company["grossprofit_margin"].shift(4)
    )
    result["expense_rate_change"] = (
        result["expense_rate"] - company["expense_rate"].shift(4)
    )
    future_income = company["n_income_attr_p"].shift(-4)
    result["next_year_net_income_change_scaled"] = (
        future_income - result["n_income_attr_p"]
    ) / result["total_assets"].where(result["total_assets"].gt(0))

    comparison_columns = tuple(component_map.values()) + (
        "gross_margin_change",
        "expense_rate_change",
    )
    industry_groups = result.groupby(
        ["report_period", "industry_code"], dropna=False, sort=False
    )
    for column in comparison_columns:
        median_name = f"industry_{column.removesuffix('_scaled')}_median"
        result[median_name] = industry_groups[column].transform("median")
        relative_name = f"relative_{column.removesuffix('_scaled')}"
        result[relative_name] = result[column] - result[median_name]

    return result.replace([np.inf, -np.inf], np.nan)


__all__ = [
    "TARGETED_GAP_CLAIMS",
    "TARGETED_SOURCE_REFS",
    "TargetedGapClaim",
    "TargetedGapEvidence",
    "business_segment_materiality_observations",
    "earnings_growth_persistence_observations",
]
