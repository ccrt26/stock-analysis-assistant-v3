from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from stock_analyzer.knowledge_validation.direct_validation import (
    CALCULATION_NAMES,
    CLAIMS,
    adjusted_return,
    chronological_views,
    describe_ordered_groups,
    financial_improvement_observations,
    map_announcement_sessions,
    market_adjusted_event_observations,
    size_value_observations,
)


LEGACY_IDS = (
    "src_fama_french_1992",
    "src_liu_stambaugh_yuan_2019",
    "src_jegadeesh_titman_1993",
    "src_ball_brown_1968",
    "src_dechow_ge_schrand_2010",
    "src_sloan_1996",
    "src_piotroski_2000",
    "src_novy_marx_2013",
    "src_fama_fisher_jensen_roll_1969",
    "src_brown_warner_1985",
    "src_mackinlay_1997",
    "src_bernard_thomas_1989",
    "src_chan_2003",
)


THEORY_ANCHORS = {
    "src_fama_french_1992": ("规模", "账面市值比", "平均收益", "美国"),
    "src_liu_stambaugh_yuan_2019": ("A股", "最小市值", "壳价值", "盈利市值比"),
    "src_jegadeesh_titman_1993": ("过去赢家", "过去输家", "3至12个月", "随后两年"),
    "src_ball_brown_1968": ("会计盈余", "非预期", "异常收益", "公告"),
    "src_dechow_ge_schrand_2010": ("盈余质量", "决策情境", "基本经营表现", "单一指标"),
    "src_sloan_1996": ("应计", "现金流", "持续性", "未来盈余"),
    "src_piotroski_2000": ("高账面市值比", "财务信号", "赢家", "美国"),
    "src_novy_marx_2013": ("毛利润", "总资产", "平均收益", "估值"),
    "src_fama_fisher_jensen_roll_1969": ("拆股", "市场共同变化", "残差", "事件"),
    "src_brown_warner_1985": ("日收益", "事件研究", "自相关", "方差"),
    "src_mackinlay_1997": ("特定事件", "公司价值", "正常收益", "事件窗口"),
    "src_bernard_thomas_1989": ("盈余意外", "公告后", "同方向", "延迟反应"),
    "src_chan_2003": ("公开新闻", "无可识别新闻", "延续", "反转"),
}


def test_claims_cover_exact_thirteen_and_preserve_theory_elements():
    assert tuple(claim.legacy_id for claim in CLAIMS) == LEGACY_IDS
    assert len(set(LEGACY_IDS)) == len(CLAIMS)
    for claim in CLAIMS:
        assert claim.calculations
        assert set(claim.calculations) <= set(CALCULATION_NAMES)
        for anchor in THEORY_ANCHORS[claim.legacy_id]:
            assert anchor in claim.core_theory, (claim.legacy_id, anchor)


def test_adjusted_return_uses_both_base_and_future_factors():
    assert adjusted_return(10.0, 2.0, 6.0, 4.0) == pytest.approx(0.2)


def test_chronological_views_splits_sorted_dates_not_input_order():
    frame = pd.DataFrame(
        {
            "date": [date(2026, 1, 3), date(2026, 1, 1), date(2026, 1, 4), date(2026, 1, 2)],
            "value": [3.0, 1.0, 4.0, 2.0],
        }
    )

    views = chronological_views(frame, date_col="date", value="value")

    assert views == {"overall": 2.5, "earlier": 1.5, "later": 3.5}


def test_describe_ordered_groups_keeps_each_group_mean():
    frame = pd.DataFrame({"group": [1, 1, 2, 2, 3, 3], "value": [1, 3, 2, 4, 5, 7]})

    assert describe_ordered_groups(frame, "group", "value") == "1:2; 2:3; 3:6"


def test_size_value_observation_compares_value_within_size_group():
    frame = pd.DataFrame(
        {
            "date": [date(2026, 1, 1)] * 6,
            "ts_code": list("ABCDEF"),
            "total_mv": [10, 10, 10, 100, 100, 100],
            "pe_ttm": [20, 10, 5, 20, 10, 5],
            "future_excess_return": [0.01, 0.02, 0.04, 0.00, 0.03, 0.05],
        }
    )

    out = size_value_observations(frame)

    assert out.groupby("size_group")["value_spread"].first().tolist() == pytest.approx([0.03, 0.05])


def test_market_adjusted_event_observation_subtracts_market_return():
    frame = pd.DataFrame(
        {
            "event_id": ["E1"],
            "stock_return_0": [0.03],
            "stock_return_1": [0.02],
            "market_return_0": [0.01],
            "market_return_1": [0.005],
        }
    )

    out = market_adjusted_event_observations(frame)

    assert out.loc[0, "car_0_1"] == pytest.approx(0.035)


def test_after_close_announcement_maps_to_next_open_session():
    announcements = pd.DataFrame(
        {
            "announcement_id": ["BEFORE", "AFTER"],
            "announcement_time": ["2026-07-10 14:00:00+08:00", "2026-07-10 16:00:00+08:00"],
        }
    )
    calendar = pd.DataFrame(
        {
            "cal_date": ["2026-07-10", "2026-07-11", "2026-07-12", "2026-07-13"],
            "is_open": [True, False, False, True],
        }
    )

    out = map_announcement_sessions(announcements, calendar).set_index("announcement_id")

    assert out.loc["BEFORE", "event_date"] == date(2026, 7, 10)
    assert out.loc["AFTER", "event_date"] == date(2026, 7, 13)


def test_financial_improvement_keeps_six_directions_separate():
    frame = pd.DataFrame(
        {
            "roe": [12.0],
            "prior_roe": [10.0],
            "operating_cash_flow": [120.0],
            "prior_operating_cash_flow": [100.0],
            "leverage": [0.4],
            "prior_leverage": [0.5],
            "current_ratio": [1.5],
            "prior_current_ratio": [1.2],
            "gross_profitability": [0.12],
            "prior_gross_profitability": [0.10],
            "asset_turnover": [0.8],
            "prior_asset_turnover": [0.7],
        }
    )

    out = financial_improvement_observations(frame)

    assert out.loc[0, "improvement_count"] == 6
    assert [column for column in out if column.endswith("_improved")] == [
        "roe_improved",
        "cash_flow_improved",
        "leverage_improved",
        "liquidity_improved",
        "gross_profitability_improved",
        "asset_turnover_improved",
    ]
