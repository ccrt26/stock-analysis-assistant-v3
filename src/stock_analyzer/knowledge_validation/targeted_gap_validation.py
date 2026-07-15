from __future__ import annotations

from dataclasses import dataclass

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


__all__ = [
    "TARGETED_GAP_CLAIMS",
    "TARGETED_SOURCE_REFS",
    "TargetedGapClaim",
    "TargetedGapEvidence",
]
