from __future__ import annotations

import pandas as pd

from stock_analyzer.evaluation.v3_forward.inputs import FormationInputs
from stock_analyzer.evaluation.v3_forward.v2_routes import V2RouteEvidence
from stock_analyzer.evaluation.v3_forward.v2_selection import (
    V2_RULE_VERSION,
    compress_v2_attention,
    form_attention_list_v2,
    v2_rule_manifest,
    v2_rule_manifest_hash,
)


def _row(code: str, route: str, **overrides):
    row = {
        "formation_date": pd.Timestamp("2026-07-20"),
        "ts_code": code,
        "routes": route,
        "company_evidence": True,
        "hard_invalid": False,
        "report_period": pd.Timestamp("2026-03-31"),
        "tr_yoy": 10.0,
        "netprofit_yoy": 10.0,
        "dt_netprofit_yoy": 10.0,
        "n_cashflow_act": 100.0,
        "evidence_freshness": 2,
        "earnings_cash_consistency": 3,
        "hotspot_support": 0,
        "price_consumption_safety": 3,
        "liquidity": 3,
    }
    row.update(overrides)
    return row


def test_cross_route_hotspot_support_cannot_delete_earnings_candidate():
    evidence = pd.DataFrame(
        [
            _row("EARNINGS", "earnings"),
            _row("HOTSPOT", "hotspot", hotspot_support=3),
        ]
    )

    decisions, audit = compress_v2_attention(evidence)

    assert set(
        decisions.loc[decisions["user_layer"].eq("关注"), "ts_code"]
    ) == {"EARNINGS", "HOTSPOT"}
    assert audit.set_index("route").loc["earnings", "selected_count"] == 1
    assert audit.set_index("route").loc["hotspot", "selected_count"] == 1


def test_same_route_dominance_still_excludes_strictly_weaker_candidate():
    evidence = pd.DataFrame(
        [
            _row("STRONG", "earnings"),
            _row(
                "WEAK",
                "earnings",
                evidence_freshness=1,
                earnings_cash_consistency=2,
                price_consumption_safety=2,
                liquidity=2,
            ),
        ]
    )

    decisions, _ = compress_v2_attention(evidence)

    assert decisions.loc[decisions["user_layer"].eq("关注"), "ts_code"].tolist() == [
        "STRONG"
    ]
    assert decisions.set_index("ts_code").loc["WEAK", "decision_reason"] == (
        "route_local_pareto_dominated"
    )


def test_route_round_robin_caps_without_padding_or_duplicates():
    eleven = pd.DataFrame(
        [_row(f"S{index}", ("hotspot", "earnings", "price")[index % 3]) for index in range(11)]
    )

    decisions, _ = compress_v2_attention(eleven, candidate_cap=10)

    selected = decisions[decisions["user_layer"].eq("关注")]
    assert len(selected) == 10
    assert selected["ts_code"].nunique() == 10

    four = eleven.head(4)
    small, _ = compress_v2_attention(four, candidate_cap=10)
    assert len(small[small["user_layer"].eq("关注")]) == 4


def test_v2_rule_manifest_is_explicit_and_hashed():
    manifest = v2_rule_manifest()

    assert V2_RULE_VERSION == "v3-forward-baseline-02"
    assert manifest["minimum_formation_date"] == "2026-07-20"
    assert manifest["pareto_scope"] == "same_route_and_internal_lane"
    assert manifest["industry_quota"] is None
    assert len(v2_rule_manifest_hash()) == 64


def test_form_v2_adds_action_confirmations_names_and_industry_audit(monkeypatch):
    evidence = pd.DataFrame(
        [
            _row(
                "A",
                "earnings",
                return_5d=0.05,
                return_20d=0.10,
                relative_return_20d=0.08,
                current_amount_ratio_20d=1.2,
                price_location_60d=0.7,
                average_amount_20d=100000.0,
                pe_ttm=20.0,
                pb=2.0,
                market_breadth_20d=0.6,
                hotspot_group_name=None,
                report_available_at="2026-04-30T08:00:00Z",
                ocf_yoy=5.0,
            ),
            _row(
                "B",
                "hotspot",
                hotspot_support=3,
                return_5d=0.04,
                return_20d=0.09,
                relative_return_20d=0.07,
                current_amount_ratio_20d=1.1,
                price_location_60d=0.7,
                average_amount_20d=90000.0,
                pe_ttm=21.0,
                pb=2.1,
                market_breadth_20d=0.6,
                hotspot_group_name="测试热点",
                report_available_at="2026-04-30T08:00:00Z",
                ocf_yoy=4.0,
            ),
        ]
    )
    monkeypatch.setattr(
        "stock_analyzer.evaluation.v3_forward.v2_selection.build_v2_route_evidence",
        lambda **_kwargs: V2RouteEvidence(
            route_rows=pd.DataFrame(),
            evidence=evidence,
            top_hotspot_groups=pd.DataFrame(),
            hotspot_overlap=pd.DataFrame(),
        ),
    )
    inputs = FormationInputs(
        formation_date=pd.Timestamp("2026-07-20").date(),
        cutoff=pd.Timestamp("2026-07-20T23:59:59+08:00").to_pydatetime(),
        market=pd.DataFrame(),
        stocks=pd.DataFrame(),
        hotspots=pd.DataFrame(),
        memberships=pd.DataFrame(
            {
                "group_type": ["industry", "industry"],
                "group_code": ["I1", "I1"],
                "ts_code": ["A", "B"],
                "valid_from": ["2020-01-01", "2020-01-01"],
                "valid_to": [None, None],
            }
        ),
        company_facts=pd.DataFrame(),
        names={"A": "甲公司", "B": "乙公司"},
        health_report={},
        input_manifest={},
        sector_catalogs=pd.DataFrame(
            {
                "group_type": ["industry"],
                "group_code": ["I1"],
                "group_name": ["同一行业"],
                "level": ["L1"],
            }
        ),
        company_profiles=pd.DataFrame(),
        announcements=pd.DataFrame(),
    )

    result = form_attention_list_v2(inputs)

    assert result.candidates["stock_name"].tolist() == ["甲公司", "乙公司"]
    assert result.candidates["action_confirmed"].tolist() == [True, True]
    assert result.candidates["industry_l1_name"].tolist() == ["同一行业", "同一行业"]
    total = result.industry_concentration[
        result.industry_concentration["scope"].eq("attention")
    ].iloc[0]
    assert total["count"] == 2
    assert total["ratio"] == 1.0
    assert result.candidates["formation_item_id"].str.startswith(
        "v3-forward-baseline-02|2026-07-20|"
    ).all()
