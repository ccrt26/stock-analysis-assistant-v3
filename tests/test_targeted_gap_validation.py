from stock_analyzer.data.research_contracts import ResearchDatasetId
from stock_analyzer.knowledge_validation.targeted_gap_validation import (
    TARGETED_GAP_CLAIMS,
    TARGETED_SOURCE_REFS,
)


EXPECTED_IDS = (
    "src_cn_business_segment_materiality",
    "src_cn_earnings_growth_persistence",
    "src_cn_relative_valuation_context",
    "src_cn_turnaround_financial_consistency",
)

EXPECTED_SOURCE_REFS = frozenset(
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


def test_targeted_contract_is_exactly_four_complete_theories():
    assert tuple(item.knowledge_id for item in TARGETED_GAP_CLAIMS) == EXPECTED_IDS
    assert len(TARGETED_GAP_CLAIMS) == 4
    assert TARGETED_SOURCE_REFS == EXPECTED_SOURCE_REFS
    assert all(len(item.core_theory) >= 60 for item in TARGETED_GAP_CLAIMS)
    assert all(item.source_refs for item in TARGETED_GAP_CLAIMS)
    assert all(item.required_facts for item in TARGETED_GAP_CLAIMS)
    assert all(
        isinstance(dataset, ResearchDatasetId)
        for item in TARGETED_GAP_CLAIMS
        for dataset in item.required_facts
    )


def test_targeted_contract_does_not_expand_the_data_foundation():
    permitted = {
        ResearchDatasetId.COMPANY_PROFILE,
        ResearchDatasetId.MAIN_BUSINESS,
        ResearchDatasetId.ANNOUNCEMENT,
        ResearchDatasetId.INCOME_STATEMENT,
        ResearchDatasetId.BALANCE_SHEET,
        ResearchDatasetId.CASH_FLOW,
        ResearchDatasetId.FINANCIAL_INDICATOR,
        ResearchDatasetId.INDUSTRY_MEMBER,
        ResearchDatasetId.DAILY_BASIC,
    }

    assert {
        dataset
        for item in TARGETED_GAP_CLAIMS
        for dataset in item.required_facts
    } <= permitted
