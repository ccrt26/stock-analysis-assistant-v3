import math

import pandas as pd

from stock_analyzer.data.research_contracts import ResearchDatasetId
from stock_analyzer.knowledge_validation.targeted_gap_validation import (
    TARGETED_GAP_CLAIMS,
    TARGETED_SOURCE_REFS,
    business_segment_materiality_observations,
    earnings_growth_persistence_observations,
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


def test_business_segment_materiality_keeps_classifications_separate():
    frame = pd.DataFrame(
        [
            {
                "ts_code": "000001.SZ",
                "report_period": "2025-12-31",
                "classification": "industry",
                "item_name": "机器人",
                "curr_type": "CNY",
                "company_curr_type": "CNY",
                "bz_sales": 60.0,
                "bz_cost": 42.0,
                "bz_profit": 18.0,
                "company_revenue": 100.0,
                "company_operating_profit": 20.0,
            },
            {
                "ts_code": "000001.SZ",
                "report_period": "2025-12-31",
                "classification": "product",
                "item_name": "机器人本体",
                "curr_type": "CNY",
                "company_curr_type": "CNY",
                "bz_sales": 40.0,
                "bz_cost": 30.0,
                "bz_profit": 10.0,
                "company_revenue": 100.0,
                "company_operating_profit": 20.0,
            },
            {
                "ts_code": "000001.SZ",
                "report_period": "2025-12-31",
                "classification": "region",
                "item_name": "中国大陆",
                "curr_type": "CNY",
                "company_curr_type": "CNY",
                "bz_sales": 100.0,
                "bz_cost": 72.0,
                "bz_profit": 28.0,
                "company_revenue": 100.0,
                "company_operating_profit": 20.0,
            },
        ]
    )

    result = business_segment_materiality_observations(frame)

    assert result["classification"].tolist() == ["industry", "product", "region"]
    assert result["sales_share"].tolist() == [0.6, 0.4, 1.0]
    assert result["profit_share"].tolist() == [0.9, 0.5, 1.4]
    assert result["gross_margin"].tolist() == [0.3, 0.25, 0.28]
    assert set(result["ratio_status"]) == {"comparable"}
    assert not ({"score", "rank", "prediction", "institution"} & set(result.columns))


def test_business_segment_materiality_rejects_incomparable_or_zero_denominators():
    frame = pd.DataFrame(
        [
            {
                "ts_code": "000002.SZ",
                "report_period": "2025-12-31",
                "classification": "product",
                "item_name": "海外产品",
                "curr_type": "USD",
                "company_curr_type": "CNY",
                "bz_sales": 10.0,
                "bz_cost": 8.0,
                "bz_profit": 2.0,
                "company_revenue": 100.0,
                "company_operating_profit": 0.0,
            },
            {
                "ts_code": "000003.SZ",
                "report_period": "2025-12-31",
                "classification": "product",
                "item_name": "无收入业务",
                "curr_type": "CNY",
                "company_curr_type": "CNY",
                "bz_sales": 0.0,
                "bz_cost": 0.0,
                "bz_profit": 0.0,
                "company_revenue": 0.0,
                "company_operating_profit": 0.0,
            },
        ]
    )

    result = business_segment_materiality_observations(frame)

    assert result["ratio_status"].tolist() == ["currency_mismatch", "invalid_denominator"]
    assert result[["sales_share", "profit_share", "gross_margin"]].isna().all().all()


def _earnings_fixture() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    periods = pd.date_range("2023-03-31", periods=9, freq="QE")
    for company, revenue_step, industry in (
        ("000001.SZ", 12.0, "801010"),
        ("000002.SZ", 4.0, "801010"),
    ):
        for index, period in enumerate(periods):
            base = index * revenue_step
            rows.append(
                {
                    "ts_code": company,
                    "report_period": period,
                    "industry_code": industry,
                    "revenue": 100.0 + base,
                    "operate_profit": 10.0 + base * 0.2,
                    "n_income_attr_p": -2.0 + base * 0.15,
                    "n_cashflow_act": 5.0 + base * 0.12,
                    "total_assets": 200.0 + index * 5.0,
                    "grossprofit_margin": 20.0 + index * 0.25,
                    "expense_rate": 12.0 - index * 0.1,
                }
            )
    return pd.DataFrame(rows)


def test_earnings_growth_uses_same_quarter_asset_scaled_changes_and_industry_context():
    result = earnings_growth_persistence_observations(_earnings_fixture())
    row = result.loc[
        (result["ts_code"] == "000001.SZ")
        & (result["report_period"] == pd.Timestamp("2024-03-31"))
    ].iloc[0]

    assert math.isclose(row["revenue_change_scaled"], 48.0 / 200.0)
    assert math.isclose(row["operating_profit_change_scaled"], 9.6 / 200.0)
    assert math.isclose(row["net_income_change_scaled"], 7.2 / 200.0)
    assert math.isclose(row["operating_cash_change_scaled"], 5.76 / 200.0)
    assert math.isclose(row["gross_margin_change"], 1.0)
    assert math.isclose(row["expense_rate_change"], -0.4)
    assert row["revenue_change_scaled"] > row["industry_revenue_change_median"]
    assert math.isclose(
        row["relative_revenue_change"],
        row["revenue_change_scaled"] - row["industry_revenue_change_median"],
    )


def test_earnings_growth_preserves_components_and_future_label_without_score():
    result = earnings_growth_persistence_observations(_earnings_fixture())
    columns = set(result.columns)

    assert {
        "revenue_change_scaled",
        "operating_profit_change_scaled",
        "net_income_change_scaled",
        "operating_cash_change_scaled",
        "gross_margin_change",
        "expense_rate_change",
        "next_year_net_income_change_scaled",
    } <= columns
    assert "score" not in columns
    assert "prediction" not in columns
    assert "surprise" not in columns
    early = result.loc[
        (result["ts_code"] == "000001.SZ")
        & (result["report_period"] == pd.Timestamp("2023-03-31")),
        "net_income_change_scaled",
    ].iloc[0]
    assert math.isnan(early)
