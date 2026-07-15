from __future__ import annotations

from stock_analyzer.knowledge_validation.supplement_validation import (
    SOURCE_REFS,
    SUPPLEMENT_CLAIMS,
)


EXPECTED_ACTIONS = {
    "src_cn_factor_momentum_2023": "enhance",
    "src_cn_return_dispersion_risk": "new",
    "src_cn_turnover_momentum_boundary": "new",
    "src_cn_profitability_valuation_support": "new",
    "src_cn_cash_accrual_quality": "new",
    "src_cn_illiquidity_operability": "new",
    "src_cn_max_overextension": "new",
    "src_cn_earnings_disclosure_hierarchy": "new",
    "src_cn_margin_semantics": "new",
    "src_cn_share_reduction_rules_2024": "enhance",
    "src_cn_pledge_conditional_risk": "new",
    "src_cn_disclosed_holder_trade": "new",
    "src_cn_buyback_rules_2023": "enhance",
    "src_csrc_disclosure_rules_2025": "enhance",
    "src_portfolio_common_exposure": "new",
}


def test_contract_is_exactly_eleven_new_four_enhance():
    assert {
        item.knowledge_id: item.action for item in SUPPLEMENT_CLAIMS
    } == EXPECTED_ACTIONS
    assert sum(item.action == "new" for item in SUPPLEMENT_CLAIMS) == 11
    assert sum(item.action == "enhance" for item in SUPPLEMENT_CLAIMS) == 4
    assert len(SUPPLEMENT_CLAIMS) == 15
    assert all(
        item.source_refs and item.core_theory and item.required_facts
        for item in SUPPLEMENT_CLAIMS
    )


def test_source_floor_contains_the_frozen_endpoints():
    assert "10.1016/j.iref.2017.04.003" in SOURCE_REFS
    assert "10.1007/s11156-025-01419-z" in SOURCE_REFS
    assert "10.1093/rfs/hhm075" in SOURCE_REFS
    assert (
        "https://www.sse.com.cn/lawandrules/sselawsrules2025/"
        "trade/specific/repo/c/c_20250617_10782110.shtml"
    ) in SOURCE_REFS


def test_each_claim_preserves_a_nontrivial_theory_and_known_data_contract():
    for claim in SUPPLEMENT_CLAIMS:
        assert len(claim.core_theory) >= 40, claim.knowledge_id
        assert len(set(claim.required_facts)) == len(claim.required_facts)
