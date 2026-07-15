from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from stock_analyzer.knowledge_validation.supplement_validation import (
    SOURCE_REFS,
    SUPPLEMENT_CLAIMS,
    chronological_relation,
    cash_accrual_observations,
    buyback_stage_observations,
    check_official_semantic_fields,
    dispersion_observations,
    illiquidity_observations,
    holder_trade_observations,
    margin_observations,
    market_state_observations,
    max_overextension_observations,
    profitability_valuation_observations,
    pledge_observations,
    turnover_observations,
    validate_cash_accrual,
    validate_profitability_valuation,
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


def test_illiquidity_is_absolute_adjusted_return_per_amount():
    frame = pd.DataFrame(
        {
            "adjusted_return_1d": [-0.02, 0.03],
            "amount": [2e8, 1e8],
        }
    )

    out = illiquidity_observations(frame)

    assert out["amihud_illiquidity"].tolist() == pytest.approx([0.01, 0.03])


def test_market_state_uses_prior_and_current_windows_only():
    frame = pd.DataFrame(
        {
            "formation_date": [date(2026, 1, 20)] * 5,
            "prior_market_return_20d": [-0.03] * 5,
            "market_return_20d": [0.05] * 5,
            "prior_relative_return_20d": [-2, -1, 0, 1, 2],
            "future_excess_return_20d": [-0.02, -0.01, 0, 0.02, 0.04],
        }
    )

    out = market_state_observations(frame)

    assert set(out["market_state"]) == {"down_to_up"}
    assert out["relative_strength_group"].tolist() == [1, 2, 3, 4, 5]


def test_dispersion_uses_sample_standard_deviation_by_date_and_industry():
    frame = pd.DataFrame(
        {
            "formation_date": [date(2026, 1, 20)] * 4,
            "industry_code": ["I1", "I1", "I2", "I2"],
            "adjusted_return_1d": [0.01, 0.03, -0.02, 0.02],
        }
    )

    out = dispersion_observations(frame)

    assert out["return_dispersion"].tolist() == pytest.approx(
        [0.0141421356, 0.0282842712]
    )
    assert out["member_count"].tolist() == [2, 2]


def test_turnover_groups_are_within_date_and_keep_return_groups_separate():
    frame = pd.DataFrame(
        {
            "formation_date": [date(2026, 1, 20)] * 15,
            "turnover_rate_f_20d": list(range(1, 16)),
            "prior_relative_return_20d": list(range(15)),
        }
    )

    out = turnover_observations(frame)

    assert sorted(out["turnover_group"].unique().tolist()) == [1, 2, 3]
    assert sorted(out["prior_return_group"].unique().tolist()) == [1, 2, 3, 4, 5]


def test_max_overextension_keeps_signal_and_outcomes_separate():
    frame = pd.DataFrame(
        {
            "max_return_20d": [0.1],
            "future_excess_return_20d": [0.03],
            "future_max_drawdown_20d": [-0.08],
        }
    )

    out = max_overextension_observations(frame)

    assert out.loc[0, "max_return_20d"] == pytest.approx(0.1)
    assert out.loc[0, "future_excess_return_20d"] == pytest.approx(0.03)
    assert out.loc[0, "future_max_drawdown_20d"] == pytest.approx(-0.08)
    assert "overextension_score" not in out


def test_chronological_relation_splits_sorted_dates_not_row_order():
    frame = pd.DataFrame(
        {
            "formation_date": [
                date(2026, 1, 4),
                date(2026, 1, 1),
                date(2026, 1, 3),
                date(2026, 1, 2),
            ],
            "signal": [4, 1, 3, 2],
            "outcome": [4, 1, 1, 2],
        }
    )

    result = chronological_relation(
        frame,
        signal="signal",
        outcome="outcome",
        date_col="formation_date",
    )

    assert set(result) == {"overall", "earlier", "later", "observations"}
    assert result["earlier"] == pytest.approx(1.0)
    assert result["later"] == pytest.approx(1.0)
    assert result["observations"] == 4


def test_price_formulas_create_no_score_or_identity():
    forbidden = {"score", "weight", "rank_total", "institution", "main_force"}
    frame = pd.DataFrame(
        {"adjusted_return_1d": [0.01], "amount": [1e8]}
    )

    assert not (forbidden & set(illiquidity_observations(frame).columns))


def test_profitability_dimensions_remain_separate():
    frame = pd.DataFrame(
        {
            "n_income_attr_p": [12.0],
            "total_hldr_eqy_exc_min_int": [100.0],
            "total_assets": [200.0],
            "revenue": [120.0],
            "oper_cost": [80.0],
            "assets_turn": [0.6],
            "pe_ttm": [20.0],
            "pb": [2.0],
            "ps_ttm": [3.0],
        }
    )

    out = profitability_valuation_observations(frame)

    assert out.loc[0, "roe_recomputed"] == pytest.approx(0.12)
    assert out.loc[0, "roa_recomputed"] == pytest.approx(0.06)
    assert out.loc[0, "gross_profitability"] == pytest.approx(0.20)
    assert out.loc[0, "asset_turnover"] == pytest.approx(0.6)
    assert "profitability_score" not in out


def test_cash_and_accrual_use_prior_assets():
    frame = pd.DataFrame(
        {
            "n_income_attr_p": [30.0],
            "n_cashflow_act": [18.0],
            "prior_total_assets": [120.0],
        }
    )

    out = cash_accrual_observations(frame)

    assert out.loc[0, "cash_component"] == pytest.approx(0.15)
    assert out.loc[0, "accrual_component"] == pytest.approx(0.10)


def test_financial_validators_report_separate_relations_without_decisions():
    frame = pd.DataFrame(
        {
            "formation_date": [
                date(2025, 1, 1),
                date(2025, 1, 1),
                date(2026, 1, 1),
                date(2026, 1, 1),
            ],
            "n_income_attr_p": [10.0, 20.0, 30.0, 40.0],
            "n_cashflow_act": [8.0, 14.0, 20.0, 22.0],
            "prior_total_assets": [100.0] * 4,
            "total_hldr_eqy_exc_min_int": [100.0] * 4,
            "total_assets": [200.0] * 4,
            "revenue": [100.0, 110.0, 120.0, 130.0],
            "oper_cost": [80.0] * 4,
            "assets_turn": [0.4, 0.5, 0.6, 0.7],
            "pe_ttm": [30.0, 25.0, 20.0, 15.0],
            "pb": [3.0, 2.5, 2.0, 1.5],
            "ps_ttm": [4.0, 3.5, 3.0, 2.5],
            "future_profitability": [0.1, 0.2, 0.3, 0.4],
            "future_excess_return_20d": [0.01, 0.02, 0.03, 0.04],
        }
    )

    profitability = validate_profitability_valuation(frame)
    cash_accrual = validate_cash_accrual(frame)

    assert set(profitability) == {
        "roe_recomputed",
        "roa_recomputed",
        "gross_profitability",
        "asset_turnover",
        "pe_ttm",
        "pb",
        "ps_ttm",
    }
    assert set(cash_accrual) == {
        "cash_to_future_profitability",
        "accrual_to_future_profitability",
        "cash_to_future_excess_return",
        "accrual_to_future_excess_return",
    }
    assert not ({"pass", "score", "weight", "recommend"} & set(profitability))
    assert not ({"pass", "score", "weight", "recommend"} & set(cash_accrual))


def test_margin_net_flow_has_no_identity_claim():
    out = margin_observations(
        pd.DataFrame(
            {
                "rzmre": [100.0],
                "rzche": [70.0],
                "rzye": [500.0],
                "rqye": [5.0],
                "rqyl": [2.0],
            }
        )
    )

    assert out.loc[0, "financing_net_flow"] == pytest.approx(30.0)
    assert not ({"institutional_buy", "main_force"} & set(out.columns))


def test_holder_trade_uses_disclosed_direction():
    out = holder_trade_observations(
        pd.DataFrame(
            {
                "in_de": ["IN", "DE"],
                "change_vol": [100.0, 40.0],
            }
        )
    )

    assert out["signed_change_vol"].tolist() == [100.0, -40.0]


def test_holder_trade_rejects_unknown_disclosed_direction():
    with pytest.raises(ValueError, match="unknown holder trade directions"):
        holder_trade_observations(
            pd.DataFrame({"in_de": ["UNKNOWN"], "change_vol": [10.0]})
        )


def test_buyback_preserves_provider_stages():
    stages = ["提议", "预案", "股东大会通过", "实施", "完成", "停止", "未通过"]

    out = buyback_stage_observations(pd.DataFrame({"process": stages}))

    assert out["buyback_stage"].tolist() == stages
    assert out["actual_execution"].tolist() == [
        False,
        False,
        False,
        True,
        True,
        False,
        False,
    ]


def test_pledge_never_calculates_liquidation_price_or_total_score():
    out = pledge_observations(
        pd.DataFrame(
            {
                "pledge_ratio": [0.4],
                "return_20d": [-0.2],
                "amount_20d": [2e9],
                "debt_to_assets": [0.6],
                "n_cashflow_act": [-10.0],
            }
        )
    )

    assert out.loc[0, "pledge_ratio"] == pytest.approx(0.4)
    assert "liquidation_price" not in out
    assert "pledge_risk_score" not in out


def test_official_semantic_field_check_uses_only_existing_fact_fields():
    field_map = {
        "earnings_forecast": (
            "available_at",
            "p_change_max",
            "p_change_min",
            "type",
        ),
        "earnings_express": (
            "announcement_type",
            "available_at",
            "yoy_net_profit",
        ),
        "income_statement": ("ann_date", "available_at", "report_type"),
        "announcement": ("announcement_time", "title"),
        "share_float": ("float_date",),
        "holder_trade": ("change_vol", "in_de"),
        "company_profile": ("business_scope", "main_business"),
        "main_business": (
            "bz_profit",
            "bz_sales",
            "classification",
            "item_name",
        ),
    }

    result = check_official_semantic_fields(field_map)

    assert result == {
        "src_cn_earnings_disclosure_hierarchy": True,
        "src_cn_share_reduction_rules_2024": True,
        "src_csrc_disclosure_rules_2025": True,
    }


def test_official_semantic_field_check_names_missing_field():
    field_map = {
        "earnings_forecast": ("available_at",),
        "earnings_express": (),
        "income_statement": (),
        "announcement": (),
        "share_float": (),
        "holder_trade": (),
        "company_profile": (),
        "main_business": (),
    }

    with pytest.raises(ValueError, match="earnings_forecast.p_change_min"):
        check_official_semantic_fields(field_map)
