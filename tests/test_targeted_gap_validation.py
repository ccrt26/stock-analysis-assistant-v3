from datetime import date
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path

import pandas as pd

from stock_analyzer.data.research_contracts import ResearchDatasetId
from stock_analyzer.knowledge_validation.targeted_gap_validation import (
    TARGETED_GAP_CLAIMS,
    TARGETED_SOURCE_REFS,
    business_segment_materiality_observations,
    earnings_growth_persistence_observations,
    load_business_segment_panel,
    load_financial_history_panel,
    load_valuation_history_panel,
    relative_valuation_context_observations,
    turnaround_financial_consistency_observations,
    validate_targeted_gap_claims,
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


def _valuation_fixture() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for date_index, formation_date in enumerate(
        pd.to_datetime(["2025-01-31", "2025-02-28", "2025-03-31"])
    ):
        for company_index, ts_code in enumerate(
            ("000001.SZ", "000002.SZ", "000003.SZ")
        ):
            rows.append(
                {
                    "formation_date": formation_date,
                    "ts_code": ts_code,
                    "industry_code": "801010",
                    "pe_ttm": 10.0 + company_index * 10.0 + date_index * 5.0,
                    "pb": 1.0 + company_index + date_index * 0.2,
                    "ps_ttm": 0.8 + company_index * 0.5 + date_index * 0.1,
                    "total_mv": 100.0 + company_index * 100.0,
                    "n_income_attr_p": 5.0 + company_index,
                    "roe": 8.0 + company_index,
                    "revenue_growth": 5.0 + company_index,
                    "cash_quality": 0.8 + company_index * 0.1,
                }
            )
    return pd.DataFrame(rows)


def test_relative_valuation_uses_comparable_peers_and_marks_invalid_values():
    frame = _valuation_fixture()
    invalid = frame.iloc[[0]].copy()
    invalid["ts_code"] = "000004.SZ"
    invalid["pe_ttm"] = -5.0
    invalid["pb"] = -1.0
    invalid["ps_ttm"] = 0.0
    invalid["n_income_attr_p"] = -3.0

    result = relative_valuation_context_observations(
        pd.concat([frame, invalid], ignore_index=True)
    )
    first = result.loc[
        (result["formation_date"] == pd.Timestamp("2025-01-31"))
        & (result["ts_code"] == "000001.SZ")
    ].iloc[0]
    loss = result.loc[result["ts_code"] == "000004.SZ"].iloc[0]

    assert math.isclose(first["peer_pe_percentile"], 1.0 / 3.0)
    assert first["peer_group_size"] == 3
    assert first["profitability_state"] == "profitable"
    assert loss["profitability_state"] == "loss"
    assert loss["pe_status"] == "invalid_nonpositive"
    assert loss["pb_status"] == "invalid_nonpositive"
    assert loss["ps_status"] == "invalid_nonpositive"
    assert math.isnan(loss["peer_pe_percentile"])


def test_relative_valuation_history_is_point_in_time_and_has_no_total_score():
    frame = _valuation_fixture()
    before = relative_valuation_context_observations(frame)
    target_before = before.loc[
        (before["formation_date"] == pd.Timestamp("2025-02-28"))
        & (before["ts_code"] == "000001.SZ"),
        "history_pe_percentile",
    ].iloc[0]
    future = frame.iloc[[0]].copy()
    future["formation_date"] = pd.Timestamp("2026-01-31")
    future["pe_ttm"] = 1.0
    after = relative_valuation_context_observations(
        pd.concat([frame, future], ignore_index=True)
    )
    target_after = after.loc[
        (after["formation_date"] == pd.Timestamp("2025-02-28"))
        & (after["ts_code"] == "000001.SZ"),
        "history_pe_percentile",
    ].iloc[0]

    assert target_before == target_after == 1.0
    assert not (
        {"score", "rank", "buy_probability", "prediction"} & set(before.columns)
    )
    assert {
        "roe",
        "revenue_growth",
        "cash_quality",
        "market_cap_percentile",
    } <= set(before.columns)


def _turnaround_fixture() -> pd.DataFrame:
    periods = pd.date_range("2024-03-31", periods=5, freq="QE")
    rows: list[dict[str, object]] = []
    for ts_code, consistent in (("000001.SZ", False), ("000002.SZ", True)):
        for index, period in enumerate(periods):
            final = index == 4
            row = {
                "ts_code": ts_code,
                "report_period": period,
                "revenue": 100.0 + (20.0 if final else 0.0),
                "operate_profit": 5.0 + (5.0 if final else 0.0),
                "n_income_attr_p": -2.0 + (5.0 if final else 0.0),
                "n_cashflow_act": 8.0,
                "total_assets": 200.0,
                "total_cur_assets": 100.0,
                "total_cur_liab": 50.0,
                "total_liab": 90.0,
                "money_cap": 30.0,
                "st_borr": 20.0,
                "non_cur_liab_due_1y": 5.0,
                "accounts_receiv": 20.0,
                "inventories": 25.0,
                "assets_impair_loss": 2.0,
                "non_oper_income": 1.0,
            }
            if final and consistent:
                row.update(
                    {
                        "n_cashflow_act": 15.0,
                        "total_cur_assets": 120.0,
                        "total_cur_liab": 45.0,
                        "money_cap": 40.0,
                        "st_borr": 12.0,
                        "non_cur_liab_due_1y": 2.0,
                        "accounts_receiv": 15.0,
                        "inventories": 20.0,
                        "assets_impair_loss": 1.0,
                        "non_oper_income": 0.5,
                    }
                )
            elif final:
                row.update(
                    {
                        "n_cashflow_act": 3.0,
                        "total_cur_assets": 85.0,
                        "total_cur_liab": 60.0,
                        "money_cap": 15.0,
                        "st_borr": 35.0,
                        "non_cur_liab_due_1y": 10.0,
                        "accounts_receiv": 35.0,
                        "inventories": 40.0,
                        "assets_impair_loss": 6.0,
                        "non_oper_income": 4.0,
                    }
                )
            rows.append(row)
    return pd.DataFrame(rows)


def test_turnaround_financial_consistency_exposes_cross_statement_contradictions():
    result = turnaround_financial_consistency_observations(_turnaround_fixture())
    final = result.loc[result["report_period"] == pd.Timestamp("2025-03-31")]
    inconsistent = final.loc[final["ts_code"] == "000001.SZ"].iloc[0]
    consistent = final.loc[final["ts_code"] == "000002.SZ"].iloc[0]

    assert inconsistent["operating_result_change"] > 0
    assert inconsistent["operating_cash_change"] < 0
    assert inconsistent["liquidity_change"] < 0
    assert inconsistent["debt_pressure_change"] > 0
    assert inconsistent["receivable_inventory_pressure_change"] > 0
    assert inconsistent["contradiction_count"] >= 4
    assert consistent["operating_result_change"] > 0
    assert consistent["operating_cash_change"] > 0
    assert consistent["liquidity_change"] > 0
    assert consistent["debt_pressure_change"] < 0
    assert consistent["receivable_inventory_pressure_change"] < 0
    assert consistent["contradiction_count"] == 0


def test_turnaround_observations_are_not_a_score_or_distress_probability():
    result = turnaround_financial_consistency_observations(_turnaround_fixture())

    assert {
        "operating_result_change",
        "operating_cash_change",
        "liquidity_change",
        "debt_pressure_change",
        "receivable_inventory_pressure_change",
        "impairment_nonoperating_change",
        "contradiction_count",
    } <= set(result.columns)
    assert not ({"score", "distress_probability", "prediction"} & set(result.columns))


def _write_fact(root: Path, name: str, rows: list[dict[str, object]]) -> None:
    target = root / "facts" / name / "fixture=data" / "data.parquet"
    target.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(rows)
    if "available_at" in frame:
        frame["available_at"] = pd.to_datetime(frame["available_at"])
    if "report_period" in frame:
        frame["report_period"] = pd.to_datetime(frame["report_period"])
    if "trade_date" in frame:
        frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    if "valid_from" in frame:
        frame["valid_from"] = pd.to_datetime(frame["valid_from"])
    if "valid_to" in frame:
        frame["valid_to"] = pd.to_datetime(frame["valid_to"])
    frame.to_parquet(target, index=False)


def _warehouse_fixture(root: Path) -> Path:
    periods = pd.date_range("2024-03-31", periods=5, freq="QE")
    income: list[dict[str, object]] = []
    balance: list[dict[str, object]] = []
    cash: list[dict[str, object]] = []
    indicators: list[dict[str, object]] = []
    for company_index, ts_code in enumerate(
        ("000001.SZ", "000002.SZ", "000003.SZ")
    ):
        for period_index, period in enumerate(periods):
            available_at = period + pd.Timedelta(days=30)
            revenue = 100.0 + company_index * 10.0 + period_index * 8.0
            income.append(
                {
                    "ts_code": ts_code,
                    "report_period": period,
                    "report_type": "1",
                    "statement_type": "comp=1;end=1",
                    "revenue": revenue,
                    "total_revenue": revenue,
                    "operate_profit": 10.0 + period_index,
                    "n_income_attr_p": 5.0 + period_index,
                    "sell_exp": 2.0,
                    "admin_exp": 3.0,
                    "fin_exp": 1.0,
                    "assets_impair_loss": 1.0,
                    "non_oper_income": 0.5,
                    "available_at": available_at,
                    "revision_no": 1,
                }
            )
            balance.append(
                {
                    "ts_code": ts_code,
                    "report_period": period,
                    "report_type": "1",
                    "statement_type": "comp=1;end=1",
                    "total_assets": 200.0 + period_index * 5.0,
                    "total_cur_assets": 100.0,
                    "total_cur_liab": 50.0,
                    "total_liab": 90.0,
                    "money_cap": 30.0,
                    "st_borr": 20.0,
                    "non_cur_liab_due_1y": 5.0,
                    "accounts_receiv": 20.0,
                    "acc_receivable": None,
                    "inventories": 25.0,
                    "available_at": available_at,
                    "revision_no": 1,
                }
            )
            cash.append(
                {
                    "ts_code": ts_code,
                    "report_period": period,
                    "report_type": "1",
                    "statement_type": "comp=1;end=1",
                    "n_cashflow_act": 7.0 + period_index,
                    "available_at": available_at,
                    "revision_no": 1,
                }
            )
            indicators.append(
                {
                    "ts_code": ts_code,
                    "report_period": period,
                    "report_type": "1",
                    "grossprofit_margin": 20.0 + period_index,
                    "roe": 8.0 + company_index,
                    "or_yoy": 5.0 + period_index,
                    "available_at": available_at,
                    "revision_no": 1,
                }
            )
    income.append(
        {
            **income[-15],
            "revenue": 9999.0,
            "total_revenue": 9999.0,
            "available_at": pd.Timestamp("2026-01-01"),
            "revision_no": 2,
        }
    )
    _write_fact(root, "income_statement", income)
    _write_fact(root, "balance_sheet", balance)
    _write_fact(root, "cash_flow", cash)
    _write_fact(root, "financial_indicator", indicators)
    _write_fact(
        root,
        "industry_member",
        [
            {
                "ts_code": ts_code,
                "industry_system": "SW2021",
                "level": "L1",
                "industry_code": "801010",
                "valid_from": "2021-01-01",
                "valid_to": None,
                "available_at": "2021-01-01",
                "revision_no": 1,
            }
            for ts_code in ("000001.SZ", "000002.SZ", "000003.SZ")
        ],
    )
    main_rows = [
        {
            "ts_code": "000001.SZ",
            "report_period": "2024-03-31",
            "classification": "product",
            "item_name": "机器人",
            "bz_sales": 40.0,
            "bz_cost": 30.0,
            "bz_profit": 10.0,
            "curr_type": "CNY",
            "available_at": "2024-04-30",
            "revision_no": 1,
        },
        {
            "ts_code": "000001.SZ",
            "report_period": "2024-03-31",
            "classification": "product",
            "item_name": "机器人",
            "bz_sales": 45.0,
            "bz_cost": 32.0,
            "bz_profit": 13.0,
            "curr_type": "CNY",
            "available_at": "2024-05-15",
            "revision_no": 2,
        },
        {
            "ts_code": "000001.SZ",
            "report_period": "2024-03-31",
            "classification": "product",
            "item_name": "机器人",
            "bz_sales": 90.0,
            "bz_cost": 50.0,
            "bz_profit": 40.0,
            "curr_type": "CNY",
            "available_at": "2026-01-01",
            "revision_no": 3,
        },
    ]
    _write_fact(root, "main_business", main_rows)
    daily_rows: list[dict[str, object]] = []
    for trade_date in pd.date_range("2024-06-03", periods=41, freq="B"):
        for company_index, ts_code in enumerate(
            ("000001.SZ", "000002.SZ", "000003.SZ")
        ):
            daily_rows.append(
                {
                    "trade_date": trade_date,
                    "ts_code": ts_code,
                    "pe_ttm": 10.0 + company_index,
                    "pb": 1.0 + company_index,
                    "ps_ttm": 0.8 + company_index,
                    "total_mv": 100.0 + company_index * 100.0,
                    "available_at": trade_date + pd.Timedelta(days=1),
                    "revision_no": 1,
                }
            )
    _write_fact(root, "daily_basic", daily_rows)
    return root


def test_read_only_loaders_apply_as_of_and_latest_revision(tmp_path):
    root = _warehouse_fixture(tmp_path / "warehouse")
    analysis_date = date(2025, 6, 30)

    business = load_business_segment_panel(root, analysis_date)
    financial = load_financial_history_panel(root, analysis_date)
    valuation = load_valuation_history_panel(root, analysis_date)

    assert business.loc[0, "bz_sales"] == 45.0
    assert business.loc[0, "company_revenue"] == 100.0
    assert 9999.0 not in set(financial["revenue"])
    assert set(financial["industry_code"]) == {"801010"}
    assert valuation["formation_date"].nunique() == 3
    assert set(valuation["industry_code"]) == {"801010"}
    assert valuation["available_at"].max().date() <= analysis_date


def _file_hashes(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_targeted_validation_is_deterministic_exactly_four_and_read_only(tmp_path):
    root = _warehouse_fixture(tmp_path / "warehouse")
    before = _file_hashes(root)

    first = validate_targeted_gap_claims(root, analysis_date=date(2025, 6, 30))
    second = validate_targeted_gap_claims(root, analysis_date=date(2025, 6, 30))

    assert tuple(item.knowledge_id for item in first) == EXPECTED_IDS
    assert first == second
    json.dumps([asdict(item) for item in first], ensure_ascii=False)
    assert _file_hashes(root) == before
