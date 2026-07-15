from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

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


__all__ = [
    "SOURCE_REFS",
    "SUPPLEMENT_CLAIMS",
    "SupplementClaim",
    "SupplementEvidence",
]
