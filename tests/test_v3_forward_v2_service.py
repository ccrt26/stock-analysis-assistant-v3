from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from stock_analyzer.evaluation.v3_forward.__main__ import build_parser
from stock_analyzer.evaluation.v3_forward.inputs import FormationInputs
from stock_analyzer.evaluation.v3_forward.v2_selection import V2FormationEvidence
from stock_analyzer.evaluation.v3_forward.v2_service import form_observation_v2


CUTOFF = datetime(2026, 7, 20, 23, 59, 59, tzinfo=ZoneInfo("Asia/Shanghai"))


def _inputs() -> FormationInputs:
    return FormationInputs(
        formation_date=date(2026, 7, 20),
        cutoff=CUTOFF,
        market=pd.DataFrame({"breadth_20d": [0.55]}),
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
        input_manifest={"facts": {"hash": "facts"}},
        sector_catalogs=pd.DataFrame(
            {
                "group_type": ["industry"],
                "group_code": ["I1"],
                "group_name": ["医药生物"],
                "level": ["L1"],
            }
        ),
        company_profiles=pd.DataFrame(
            {
                "ts_code": ["A", "B"],
                "com_name": ["甲股份有限公司", "乙股份有限公司"],
                "main_business": ["临床服务", "药品研发生产"],
                "introduction": ["甲公司介绍", "乙公司介绍"],
                "valid_from": ["2026-07-13", "2026-07-13"],
                "available_at": ["2026-07-13T08:00:00Z"] * 2,
            }
        ),
        announcements=pd.DataFrame(
            {
                "ts_code": ["A"],
                "title": ["关于产品获得注册证的公告"],
                "url": ["https://example.test/a.pdf"],
                "candidate_event_types": ["[]"],
                "available_at": ["2026-07-15T08:00:00Z"],
            }
        ),
    )


def _candidates() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "formation_date": [date(2026, 7, 20)] * 2,
            "formation_item_id": [
                "v3-forward-baseline-02|2026-07-20|A",
                "v3-forward-baseline-02|2026-07-20|B",
            ],
            "ts_code": ["A", "B"],
            "stock_name": ["甲公司", "乙公司"],
            "routes": ["earnings|price", "hotspot"],
            "hotspot_group_name": [None, "测试热点"],
            "company_driver_state": ["confirmed", "confirmed"],
            "user_layer": ["关注", "关注"],
            "hard_invalid": [False, False],
            "action_confirmed": [True, False],
            "confirm_return_5d_positive": [True, False],
            "confirm_relative_return_20d_positive": [True, True],
            "confirm_amount_ratio_20d": [True, True],
            "return_5d": [0.05, -0.01],
            "return_20d": [0.10, 0.08],
            "relative_return_20d": [0.08, 0.07],
            "current_amount_ratio_20d": [1.2, 1.1],
            "price_location_60d": [0.7, 0.7],
            "market_breadth_20d": [0.55, 0.55],
            "report_period": ["2026-03-31", "2026-03-31"],
            "tr_yoy": [10.0, 9.0],
            "netprofit_yoy": [20.0, 19.0],
            "dt_netprofit_yoy": [30.0, 29.0],
            "ocf_yoy": [5.0, 4.0],
            "n_cashflow_act": [100.0, 90.0],
            "pe_ttm": [20.0, 21.0],
            "pb": [2.0, 2.1],
            "risk_notes": ["仍需验证", "短期未启动"],
            "industry_l1_name": ["医药生物", "医药生物"],
            "entry_state": ["waiting", "waiting"],
        }
    )


def _formation_evidence() -> V2FormationEvidence:
    return V2FormationEvidence(
        candidates=_candidates(),
        route_audit=pd.DataFrame(
            {
                "route": ["hotspot", "earnings", "price"],
                "recalled_count": [30, 30, 30],
                "eligible_count": [28, 29, 30],
                "frontier_count": [4, 3, 5],
                "selected_count": [1, 1, 1],
            }
        ),
        top_hotspot_groups=pd.DataFrame(
            {
                "group_name": ["测试热点"],
                "breadth_5d": [0.7],
                "relative_return_20d": [0.2],
            }
        ),
        hotspot_overlap=pd.DataFrame(
            {
                "left_group_name": ["测试热点"],
                "right_group_name": ["相似热点"],
                "jaccard_overlap": [0.8],
                "intersection_count": [8],
                "union_count": [10],
            }
        ),
        industry_concentration=pd.DataFrame(
            {
                "scope": ["attention", "action_confirmed"],
                "industry_l1_name": ["医药生物", "医药生物"],
                "count": [2, 1],
                "ratio": [1.0, 1.0],
            }
        ),
    )


def test_v2_rejects_dates_that_would_rewrite_v01(tmp_path: Path):
    with pytest.raises(ValueError, match="2026-07-20"):
        form_observation_v2(
            warehouse_root=tmp_path / "warehouse",
            archive_root=tmp_path / "archive",
            output_root=tmp_path / "forward",
            formation_date=date(2026, 7, 17),
            enforce_real_root=False,
        )


def test_v2_writes_audited_formation_cards_and_is_idempotent(
    tmp_path: Path, monkeypatch
):
    inputs = _inputs()
    monkeypatch.setattr(
        "stock_analyzer.evaluation.v3_forward.v2_service.load_formation_inputs",
        lambda *_args, **_kwargs: inputs,
    )
    monkeypatch.setattr(
        "stock_analyzer.evaluation.v3_forward.v2_service.form_attention_list_v2",
        lambda _inputs: _formation_evidence(),
    )
    monkeypatch.setattr(
        "stock_analyzer.evaluation.v3_forward.explanation_service.load_formation_inputs",
        lambda *_args, **_kwargs: inputs,
    )
    output = tmp_path / "forward"

    first = form_observation_v2(
        warehouse_root=tmp_path / "warehouse",
        archive_root=tmp_path / "archive",
        output_root=output,
        formation_date=date(2026, 7, 20),
        now=CUTOFF,
        enforce_real_root=False,
    )
    second = form_observation_v2(
        warehouse_root=tmp_path / "warehouse",
        archive_root=tmp_path / "archive",
        output_root=output,
        formation_date=date(2026, 7, 20),
        now=CUTOFF,
        enforce_real_root=False,
    )

    payload = json.loads(
        (first.bundle.path / "formation.json").read_text(encoding="utf-8")
    )
    assert payload["rule_version"] == "v3-forward-baseline-02"
    assert payload["attention_count"] == 2
    assert payload["action_count"] == 1
    assert payload["route_audit"][0]["route"] == "hotspot"
    assert payload["industry_concentration"][0]["ratio"] == 1.0
    report = (first.bundle.path / "report.md").read_text(encoding="utf-8")
    assert "路线召回与压缩审计" in report
    assert "行业风险簇集中" in report
    assert "热点成员重叠" in report
    assert "详细决策卡" in report
    assert first.cards.card_count == 1
    assert second.bundle.idempotent is True
    assert second.cards.bundle.idempotent is True


def test_form_v2_cli_is_explicit():
    args = build_parser().parse_args(
        ["form-v2", "--formation-date", "2026-07-20"]
    )

    assert args.command == "form-v2"
    assert args.formation_date == "2026-07-20"

