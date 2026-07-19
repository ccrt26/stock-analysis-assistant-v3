from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd

from stock_analyzer.evaluation.v3_forward.explanations import (
    build_decision_cards,
    render_decision_cards,
)
from stock_analyzer.evaluation.v3_forward.inputs import FormationInputs


FORMATION_DATE = date(2026, 7, 17)
CUTOFF = datetime(2026, 7, 17, 23, 59, 59, tzinfo=ZoneInfo("Asia/Shanghai"))


def test_formation_inputs_exposes_strict_explanation_frames():
    profiles = pd.DataFrame(
        {
            "ts_code": ["301257.SZ"],
            "available_at": ["2026-07-13T17:15:56Z"],
        }
    )
    announcements = pd.DataFrame(
        {
            "ts_code": ["301257.SZ"],
            "available_at": ["2026-07-01T16:00:00Z"],
        }
    )
    inputs = FormationInputs(
        formation_date=FORMATION_DATE,
        cutoff=CUTOFF,
        market=pd.DataFrame(),
        stocks=pd.DataFrame(),
        hotspots=pd.DataFrame(),
        memberships=pd.DataFrame(),
        company_facts=pd.DataFrame(),
        names={"301257.SZ": "普蕊斯"},
        health_report={},
        input_manifest={},
        sector_catalogs=pd.DataFrame(),
        company_profiles=profiles,
        announcements=announcements,
    )

    assert inputs.company_profiles.equals(profiles)
    assert inputs.announcements.equals(announcements)
    for frame in (inputs.company_profiles, inputs.announcements):
        visible = pd.to_datetime(frame["available_at"], utc=True)
        assert (visible <= pd.Timestamp(inputs.cutoff).tz_convert("UTC")).all()


def _explanation_inputs() -> FormationInputs:
    return FormationInputs(
        formation_date=FORMATION_DATE,
        cutoff=CUTOFF,
        market=pd.DataFrame(),
        stocks=pd.DataFrame(),
        hotspots=pd.DataFrame(),
        memberships=pd.DataFrame(
            {
                "group_type": ["industry", "industry", "industry"],
                "group_code": ["医药生物", "医药生物", "机械设备"],
                "ts_code": ["301257.SZ", "002603.SZ", "603757.SH"],
                "valid_from": ["2020-01-01"] * 3,
                "valid_to": [None] * 3,
            }
        ),
        company_facts=pd.DataFrame(),
        names={
            "301257.SZ": "普蕊斯",
            "002603.SZ": "以岭药业",
            "603757.SH": "大元泵业",
        },
        health_report={},
        input_manifest={},
        sector_catalogs=pd.DataFrame(
            {
                "group_type": ["industry", "industry"],
                "group_code": ["医药生物", "机械设备"],
                "group_name": ["医药生物", "机械设备"],
                "level": ["L1", "L1"],
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
                    "为制药及医疗器械企业提供临床试验 SMO 服务。",
                    "围绕中药、化学药和生物药开展研发、生产与销售。",
                ],
                "valid_from": ["2026-07-13", "2026-07-13"],
                "available_at": [
                    "2026-07-13T17:15:56Z",
                    "2026-07-13T17:15:56Z",
                ],
            }
        ),
        announcements=pd.DataFrame(
            {
                "ts_code": ["301257.SZ", "002603.SZ"],
                "title": [
                    "关于公司股东减持计划实施完成的公告",
                    "关于专利产品进入国家基本药物目录的公告",
                ],
                "url": ["https://example.test/reduction.pdf", "https://example.test/catalog.pdf"],
                "candidate_event_types": ["[\"shareholder_reduction\"]", "[]"],
                "available_at": ["2026-06-26T13:04:26Z", "2026-07-09T16:00:00Z"],
            }
        ),
    )


def _explanation_candidates() -> pd.DataFrame:
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
            "return_5d": [0.0851, 0.0638, -0.0152],
            "return_20d": [0.42, 0.17, 0.43],
            "relative_return_20d": [0.4343, 0.1820, 0.4454],
            "current_amount_ratio_20d": [1.8197, 1.6745, 1.3838],
            "price_location_60d": [0.88, 0.81, 0.95],
            "market_breadth_20d": [0.215] * 3,
            "report_period": ["2026-03-31"] * 3,
            "tr_yoy": [9.9524, 3.4581, -4.2657],
            "netprofit_yoy": [61.7978, 25.4316, -70.7778],
            "dt_netprofit_yoy": [110.15, 25.19, -69.08],
            "ocf_yoy": [-50.0, 12.0, -20.0],
            "n_cashflow_act": [-31587210.93, 610709814.53, -33557883.79],
            "pe_ttm": [44.0, 26.0, 50.0],
            "pb": [4.0, 3.0, 5.0],
            "risk_notes": [
                "经营活动现金流为负；成交明显放大",
                "成交明显放大",
                "价格位置较高",
            ],
        }
    )


def test_build_decision_cards_includes_only_confirmed_stocks_and_full_context():
    payload = {
        "formation_date": FORMATION_DATE.isoformat(),
        "rule_version": "v3-forward-baseline-01",
        "data_cutoff_at": CUTOFF.isoformat(),
    }

    cards = build_decision_cards(
        payload, _explanation_candidates(), _explanation_inputs()
    )

    assert cards["ts_code"].tolist() == ["301257.SZ", "002603.SZ"]
    puruisi = cards[cards["ts_code"].eq("301257.SZ")].iloc[0]
    assert puruisi["company_name"] == "普蕊斯(上海)医药科技开发股份有限公司"
    assert puruisi["main_business"] == "临床试验现场管理服务"
    assert puruisi["industry_l1_name"] == "医药生物"
    assert "shareholder_reduction" in puruisi["recent_announcements_json"]
    assert "价格" in puruisi["selection_explanation"]
    assert "经营活动现金流为负" in puruisi["opposition_evidence"]

    report = render_decision_cards(payload, cards)
    for heading in (
        "这是什么公司",
        "为什么进入关注名单",
        "为什么现在被动作确认",
        "经营与财务",
        "估值与交易阶段",
        "正式公告",
        "反对证据与不确定性",
        "还缺什么确认",
        "结论边界",
    ):
        assert heading in report
    assert "动作确认不是自动买入" in report
