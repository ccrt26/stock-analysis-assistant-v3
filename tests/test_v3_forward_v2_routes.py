from __future__ import annotations

import pandas as pd
import pytest

from stock_analyzer.evaluation.v3_forward.v2_routes import (
    build_v2_route_evidence,
    hotspot_overlap_audit,
    round_robin_hotspot_codes,
)


def test_hotspot_round_robin_prevents_first_group_monopoly():
    codes = round_robin_hotspot_codes(
        {
            "g1": [f"A{index}" for index in range(40)],
            "g2": ["B1", "B2", "B3"],
        },
        limit=6,
    )

    assert codes == ("A0", "B1", "B2", "A1", "A2", "B3")
    assert any(code.startswith("B") for code in codes)
    assert len(codes) == len(set(codes)) == 6


def test_hotspot_round_robin_deduplicates_overlapping_members():
    codes = round_robin_hotspot_codes(
        {"g1": ["A", "B"], "g2": ["A", "C"]}, limit=4
    )

    assert set(codes) == {"A", "B", "C"}
    assert len(codes) == 3


def test_hotspot_overlap_audit_reports_exact_jaccard_without_filtering():
    groups = pd.DataFrame(
        {
            "group_type": ["theme", "theme"],
            "group_code": ["g1", "g2"],
            "group_name": ["主题一", "主题二"],
        }
    )
    memberships = pd.DataFrame(
        {
            "group_type": ["theme"] * 4,
            "group_code": ["g1", "g1", "g2", "g2"],
            "ts_code": ["A", "B", "B", "C"],
        }
    )

    audit = hotspot_overlap_audit(groups, memberships)

    assert len(audit) == 1
    assert audit.iloc[0]["left_group_name"] == "主题一"
    assert audit.iloc[0]["right_group_name"] == "主题二"
    assert audit.iloc[0]["intersection_count"] == 1
    assert audit.iloc[0]["union_count"] == 3
    assert audit.iloc[0]["jaccard_overlap"] == pytest.approx(1 / 3)


def test_build_v2_route_evidence_keeps_independent_routes_and_groups():
    formation_date = pd.Timestamp("2026-07-20")
    stocks = pd.DataFrame(
        {
            "ts_code": ["A", "B", "C", "D"],
            "relative_return_20d": [0.40, 0.30, 0.20, 0.10],
            "current_amount_ratio_20d": [1.4, 1.3, 1.2, 1.1],
            "average_amount_20d": [90000.0, 80000.0, 70000.0, 60000.0],
            "return_5d": [0.05, 0.04, 0.03, 0.02],
            "return_20d": [0.15, 0.14, 0.13, 0.12],
            "price_location_60d": [0.7, 0.7, 0.7, 0.7],
            "pe_ttm": [20.0, 21.0, 22.0, 23.0],
            "pb": [2.0, 2.1, 2.2, 2.3],
        }
    )
    hotspots = pd.DataFrame(
        {
            "group_type": ["theme", "theme"],
            "group_code": ["g1", "g2"],
            "group_name": ["第一主题", "第二主题"],
            "coverage_status": ["complete", "complete"],
            "breadth_5d": [0.7, 0.6],
            "relative_return_5d": [0.08, 0.07],
            "relative_return_20d": [0.30, 0.20],
            "turnover_share_change_5d": [0.03, 0.02],
        }
    )
    memberships = pd.DataFrame(
        {
            "group_type": ["theme"] * 4,
            "group_code": ["g1", "g1", "g2", "g2"],
            "ts_code": ["A", "B", "C", "D"],
            "valid_from": ["2020-01-01"] * 4,
            "valid_to": [None] * 4,
        }
    )
    company_facts = pd.DataFrame(
        {
            "ts_code": ["A", "B", "C", "D"],
            "report_period": ["2026-03-31"] * 4,
            "available_at": ["2026-04-30T08:00:00Z"] * 4,
            "tr_yoy": [10.0, 9.0, 8.0, 7.0],
            "netprofit_yoy": [20.0, 19.0, 18.0, 17.0],
            "dt_netprofit_yoy": [30.0, 29.0, 28.0, 27.0],
            "ocf_yoy": [5.0, 4.0, 3.0, 2.0],
            "ocfps": [1.0] * 4,
            "n_cashflow_act": [100.0] * 4,
        }
    )

    result = build_v2_route_evidence(
        formation_date=formation_date,
        market=pd.DataFrame({"breadth_20d": [0.6]}),
        stocks=stocks,
        hotspots=hotspots,
        memberships=memberships,
        company_facts=company_facts,
        route_recall_cap=4,
    )

    assert set(result.route_rows["route"]) == {"hotspot", "earnings", "price"}
    hotspot_codes = result.route_rows.loc[
        result.route_rows["route"].eq("hotspot"), "ts_code"
    ].tolist()
    assert any(code in {"C", "D"} for code in hotspot_codes)
    assert not result.evidence.duplicated(["formation_date", "ts_code"]).any()
    assert {
        "company_evidence",
        "hard_invalid",
        "hotspot_support",
        "price_consumption_safety",
        "liquidity",
    } <= set(result.evidence)
