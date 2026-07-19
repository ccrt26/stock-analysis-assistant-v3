from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from stock_analyzer.evaluation.v3_forward.dossiers import (
    DOSSIER_SCHEMA_VERSION,
    build_research_dossiers,
    render_research_dossiers,
)
from stock_analyzer.evaluation.v3_forward.inputs import FormationInputs


FORMATION_DATE = date(2026, 7, 17)
CUTOFF = datetime(2026, 7, 17, 23, 59, 59, tzinfo=ZoneInfo("Asia/Shanghai"))


def _inputs() -> FormationInputs:
    financial_rows: list[dict[str, object]] = []
    for code, offset in (("301257.SZ", 0.0), ("002603.SZ", 10.0)):
        for index, period in enumerate(
            (
                "2024-12-31",
                "2025-03-31",
                "2025-06-30",
                "2025-09-30",
                "2025-12-31",
                "2026-03-31",
            )
        ):
            financial_rows.append(
                {
                    "ts_code": code,
                    "report_period": period,
                    "available_at": f"2026-04-{20 + index:02d}T16:00:00Z",
                    "revision_no": 1,
                    "tr_yoy": offset + index,
                    "netprofit_yoy": offset + index + 1,
                    "dt_netprofit_yoy": offset + index + 2,
                    "ocf_yoy": offset + index + 3,
                    "eps": 0.10 + index / 100,
                    "grossprofit_margin": 20.0 + index,
                    "netprofit_margin": 5.0 + index,
                    "roe": 3.0 + index,
                    "debt_to_assets": 30.0 + index,
                    "current_ratio": 1.0 + index / 10,
                    "ocfps": 0.20 + index / 100,
                }
            )
    # A legal later revision for the latest period must win.
    financial_rows.append(
        {
            **financial_rows[5],
            "available_at": "2026-04-30T16:00:00Z",
            "revision_no": 2,
            "tr_yoy": 9.95,
        }
    )
    cashflow_rows = [
        {
            "ts_code": row["ts_code"],
            "report_period": row["report_period"],
            "available_at": row["available_at"],
            "revision_no": row["revision_no"],
            "n_cashflow_act": -31_000_000.0
            if row["ts_code"] == "301257.SZ"
            else 610_000_000.0,
        }
        for row in financial_rows
    ]
    return FormationInputs(
        formation_date=FORMATION_DATE,
        cutoff=CUTOFF,
        market=pd.DataFrame(),
        stocks=pd.DataFrame(
            {
                "analysis_date": [FORMATION_DATE, FORMATION_DATE],
                "ts_code": ["301257.SZ", "002603.SZ"],
                "return_1d": [-0.10, -0.05],
                "relative_return_1d": [-0.07, -0.01],
                "return_5d": [0.085, 0.064],
                "relative_return_5d": [0.138, 0.116],
                "return_10d": [0.044, 0.056],
                "relative_return_10d": [0.109, 0.121],
                "return_20d": [0.351, 0.099],
                "relative_return_20d": [0.434, 0.182],
                "return_60d": [-0.063, 0.031],
                "relative_return_60d": [-0.015, 0.079],
                "realized_volatility_20d_annualized": [1.037, 0.484],
                "atr_ratio_20d": [0.103, 0.046],
                "price_location_60d": [0.691, 0.666],
                "average_amount_20d": [395_622_000.0, 461_431_100.0],
                "current_amount_ratio_20d": [1.820, 1.674],
                "recent_limit_up_count_5d": [0, 0],
                "pe_ttm": [37.659, 20.131],
                "pb": [3.357, 2.419],
                "pe_ttm_percentile_250d": [0.764, 0.745],
                "pb_percentile_250d": [0.704, 0.204],
                "valuation_observations_250d": [250, 55],
                "coverage_status": ["complete_with_declared_gaps", "limited"],
                "valuation_data_status": ["complete", "limited"],
                "pe_percentile_status": ["available", "available"],
                "limitation_notes": [
                    "trader identity unavailable",
                    "250-session valuation observations are incomplete: 55/250",
                ],
            }
        ),
        hotspots=pd.DataFrame(),
        memberships=pd.DataFrame(
            {
                "group_type": ["industry", "industry", "theme", "theme", "theme"],
                "group_code": [
                    "801150.SI",
                    "801150.SI",
                    "000814.SH",
                    "399394.SZ",
                    "399999.SZ",
                ],
                "ts_code": [
                    "301257.SZ",
                    "002603.SZ",
                    "002603.SZ",
                    "002603.SZ",
                    "002603.SZ",
                ],
                "valid_from": ["2020-01-01", "2020-01-01", "2026-06-30", "2026-06-30", "2025-01-01"],
                "valid_to": [None, None, None, None, "2025-12-31"],
            }
        ),
        company_facts=pd.DataFrame(),
        names={"301257.SZ": "普蕊斯", "002603.SZ": "以岭药业"},
        health_report={},
        input_manifest={"facts": {"identity": "same-as-formation"}},
        sector_catalogs=pd.DataFrame(
            {
                "group_type": ["industry", "theme", "theme", "theme"],
                "group_code": ["801150.SI", "000814.SH", "399394.SZ", "399999.SZ"],
                "group_name": ["医药生物", "细分医药", "国证医药", "过期概念"],
                "level": ["L1", "主题指数", "主题指数", "主题指数"],
            }
        ),
        company_profiles=pd.DataFrame(
            {
                "ts_code": ["301257.SZ", "002603.SZ"],
                "com_name": [
                    "普蕊斯(上海)医药科技开发股份有限公司",
                    "石家庄以岭药业股份有限公司",
                ],
                "main_business": ["临床试验现场管理服务", "药品的研发、生产和销售"],
                "introduction": [
                    "为制药和医疗器械企业提供临床试验项目执行与现场管理服务。",
                    "围绕药品开展研发、生产和销售。",
                ],
                "valid_from": ["2026-07-01", "2026-07-01"],
                "available_at": ["2026-07-01T16:00:00Z"] * 2,
            }
        ),
        announcements=pd.DataFrame(
            {
                "ts_code": ["301257.SZ", "002603.SZ"],
                "title": ["关于股东减持计划的公告", "关于产品进入国家基本药物目录的公告"],
                "url": ["https://example.test/a.pdf", "https://example.test/b.pdf"],
                "candidate_event_types": ["[\"shareholder_reduction\"]", "[]"],
                "available_at": ["2026-06-01T16:00:00Z", "2026-07-09T16:00:00Z"],
            }
        ),
        financial_history=pd.DataFrame(financial_rows),
        cashflow_history=pd.DataFrame(cashflow_rows),
    )


def _candidates() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "formation_date": [FORMATION_DATE] * 3,
            "ts_code": ["301257.SZ", "002603.SZ", "603757.SH"],
            "stock_name": ["普蕊斯", "以岭药业", "大元泵业"],
            "routes": ["price", "hotspot", "price"],
            "hotspot_group_name": [None, "细分医药", None],
            "company_driver_state": ["partial", "confirmed", "absent"],
            "action_confirmed": [True, True, False],
            "confirm_return_5d_positive": [True, True, False],
            "confirm_relative_return_20d_positive": [True, True, True],
            "confirm_amount_ratio_20d": [True, True, True],
            "return_5d": [0.085, 0.064, -0.015],
            "return_20d": [0.351, 0.099, 0.10],
            "relative_return_20d": [0.434, 0.182, 0.20],
            "current_amount_ratio_20d": [1.820, 1.674, 1.10],
            "price_location_60d": [0.691, 0.666, 0.50],
            "market_breadth_20d": [0.215] * 3,
            "report_period": ["2026-03-31"] * 3,
            "tr_yoy": [9.95, 3.46, -4.2],
            "netprofit_yoy": [61.80, 25.43, -70.0],
            "dt_netprofit_yoy": [110.15, 25.19, -69.0],
            "ocf_yoy": [12.41, 79.57, -20.0],
            "n_cashflow_act": [-31_000_000.0, 610_000_000.0, -30_000_000.0],
            "pe_ttm": [37.659, 20.131, 30.0],
            "pb": [3.357, 2.419, 3.0],
            "risk_notes": ["经营活动现金流为负；成交明显放大", "成交明显放大", ""],
        }
    )


def _payload() -> dict[str, object]:
    return {
        "formation_date": FORMATION_DATE.isoformat(),
        "rule_version": "v3-forward-baseline-01",
        "data_cutoff_at": CUTOFF.isoformat(),
    }


def test_dossiers_only_include_confirmed_stocks_and_onboard_new_reader():
    dossiers = build_research_dossiers(_payload(), _candidates(), _inputs())

    assert DOSSIER_SCHEMA_VERSION == "v3-forward-research-dossier-01"
    assert dossiers["ts_code"].tolist() == ["301257.SZ", "002603.SZ"]
    puruisi = dossiers[dossiers["ts_code"].eq("301257.SZ")].iloc[0]
    assert puruisi["company_name"] == "普蕊斯(上海)医药科技开发股份有限公司"
    assert puruisi["main_business"] == "临床试验现场管理服务"
    assert puruisi["industry_l1_name"] == "医药生物"
    assert "30秒读懂" in puruisi["summary_json"]
    assert "本次不是因热点入选" in puruisi["industry_and_themes_json"]
    assert "不编写业务占比" in puruisi["business_composition_status"]


def test_dossier_theme_memberships_are_active_and_not_business_proof():
    dossiers = build_research_dossiers(_payload(), _candidates(), _inputs())
    yiling = dossiers[dossiers["ts_code"].eq("002603.SZ")].iloc[0]
    themes = json.loads(yiling["industry_and_themes_json"])

    assert themes["selection_hotspot"] == "细分医药"
    assert themes["selection_hotspot_evidence"] == "selection_relevant"
    assert [item["name"] for item in themes["formal_theme_memberships"]] == [
        "细分医药",
        "国证医药",
    ]
    assert all(
        item["evidence_role"] in {"selection_relevant", "index_membership_only"}
        for item in themes["formal_theme_memberships"]
    )
    assert "指数或主题成员不等于业务收入证据" in themes["boundary"]


def test_dossier_financial_history_deduplicates_and_keeps_latest_five_periods():
    dossiers = build_research_dossiers(_payload(), _candidates(), _inputs())
    puruisi = dossiers[dossiers["ts_code"].eq("301257.SZ")].iloc[0]
    history = json.loads(puruisi["financial_history_json"])

    assert len(history) == 5
    assert history[0]["report_period"] == "2026-03-31"
    assert history[0]["tr_yoy"] == pytest.approx(9.95)
    assert history[-1]["report_period"] == "2025-03-31"
    for field in (
        "netprofit_yoy",
        "dt_netprofit_yoy",
        "ocf_yoy",
        "eps",
        "grossprofit_margin",
        "netprofit_margin",
        "roe",
        "debt_to_assets",
        "current_ratio",
        "ocfps",
        "n_cashflow_act",
    ):
        assert field in history[0]


def test_dossier_rejects_future_financial_history():
    inputs = _inputs()
    future = inputs.financial_history.iloc[[0]].copy()
    future["available_at"] = "2026-07-18T16:00:00Z"
    inputs.financial_history.loc[len(inputs.financial_history)] = future.iloc[0]

    with pytest.raises(ValueError, match="financial history exceeds"):
        build_research_dossiers(_payload(), _candidates(), inputs)


def test_dossier_contains_trading_metrics_glossary_and_evidence_boundaries():
    dossiers = build_research_dossiers(_payload(), _candidates(), _inputs())
    puruisi = dossiers[dossiers["ts_code"].eq("301257.SZ")].iloc[0]
    metrics = json.loads(puruisi["trading_metrics_json"])
    for field in (
        "return_1d",
        "return_5d",
        "return_10d",
        "return_20d",
        "return_60d",
        "realized_volatility_20d_annualized",
        "atr_ratio_20d",
        "price_location_60d",
        "average_amount_20d",
        "current_amount_ratio_20d",
        "recent_limit_up_count_5d",
        "pe_ttm",
        "pb",
        "pe_ttm_percentile_250d",
        "pb_percentile_250d",
        "valuation_observations_250d",
    ):
        assert field in metrics

    combined, per_stock = render_research_dossiers(_payload(), dossiers)
    assert set(per_stock) == {"301257.SZ", "002603.SZ"}
    for phrase in (
        "成交比率",
        "三项确认",
        "ATR",
        "PE-TTM",
        "PB",
        "ROE",
        "资产负债率",
        "已确认事实",
        "谨慎解释",
        "当前未知",
    ):
        assert phrase in combined
    for prohibited in ("目标价", "仓位建议", "止损", "止盈", "自动买入", "自动交易"):
        assert prohibited not in combined

