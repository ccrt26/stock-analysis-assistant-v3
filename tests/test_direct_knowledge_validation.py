from __future__ import annotations

from datetime import date
import hashlib
from pathlib import Path

import pandas as pd
import pytest

from stock_analyzer.knowledge_validation.direct_validation import (
    CALCULATION_NAMES,
    CLAIMS,
    adjusted_return,
    chronological_views,
    describe_ordered_groups,
    financial_improvement_observations,
    formal_announcement_shock_observations,
    momentum_observations,
    map_announcement_sessions,
    market_adjusted_event_observations,
    earnings_reaction_observations,
    size_value_observations,
    validate_common_factor_momentum,
    validate_daily_event_method,
    validate_earnings_reaction,
    validate_financial_improvement,
    validate_formal_announcement_shocks,
    validate_short_reversal,
    validate_size_value,
    validate_all_claims,
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
            "pb": [5, 2, 1, 5, 2, 1],
            "future_excess_return": [0.01, 0.02, 0.04, 0.00, 0.03, 0.05],
        }
    )

    out = size_value_observations(frame)

    assert out.groupby("size_group")["value_spread"].first().tolist() == pytest.approx([0.03, 0.05])
    assert out.groupby("size_group")["book_value_spread"].first().tolist() == pytest.approx([0.03, 0.05])


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
            "gross_margin": [0.12],
            "prior_gross_margin": [0.10],
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
        "gross_margin_improved",
        "asset_turnover_improved",
    ]


def test_momentum_observation_keeps_industry_component_separate():
    frame = pd.DataFrame(
        {
            "date": [date(2026, 1, 1)] * 5,
            "ts_code": list("ABCDE"),
            "prior_return": [-0.2, -0.1, 0.0, 0.1, 0.2],
            "industry_prior_return": [-0.1, -0.05, 0.0, 0.05, 0.1],
            "future_excess_return": [-0.1, -0.05, 0.0, 0.05, 0.1],
        }
    )

    out = momentum_observations(frame)

    assert out.loc[out["ts_code"] == "A", "prior_group"].iat[0] == 1
    assert out.loc[out["ts_code"] == "E", "prior_group"].iat[0] == 5
    assert out["industry_subtracted_prior"].tolist() == pytest.approx(
        [-0.1, -0.05, 0.0, 0.05, 0.1]
    )


def test_earnings_reaction_orders_actual_surprise_not_announcement_day_return():
    frame = pd.DataFrame(
        {
            "event_date": [date(2026, 1, 1)] * 5,
            "ts_code": list("ABCDE"),
            "earnings_surprise": [-2, -1, 0, 1, 2],
            "event_car": [2, 1, 0, -1, -2],
            "future_excess_return": [-0.2, -0.1, 0.0, 0.1, 0.2],
        }
    )

    out = earnings_reaction_observations(frame)

    assert out.set_index("ts_code").loc["A", "surprise_group"] == 1
    assert out.set_index("ts_code").loc["E", "surprise_group"] == 5


def test_formal_announcement_shock_uses_narrow_no_match_wording():
    frame = pd.DataFrame(
        {
            "market_adjusted_return": [0.08, -0.08],
            "future_excess_return": [0.02, 0.02],
            "local_formal_announcement_match": [True, False],
        }
    )

    out = formal_announcement_shock_observations(frame)

    assert out["information_match_status"].tolist() == [
        "local_formal_announcement_match",
        "no_local_formal_announcement_match",
    ]
    assert out["directional_follow_through"].tolist() == pytest.approx([0.02, -0.02])
    assert "no_public" not in " ".join(out["information_match_status"])


def test_seven_validations_return_descriptive_relationships_without_pass_line():
    price = pd.DataFrame(
        {
            "date": [date(2025, 1, 1)] * 5 + [date(2026, 1, 1)] * 5,
            "ts_code": list("ABCDE") * 2,
            "prior_return": [-2, -1, 0, 1, 2] * 2,
            "industry_prior_return": [-1, -0.5, 0, 0.5, 1] * 2,
            "future_excess_return": [-0.2, -0.1, 0, 0.1, 0.2] * 2,
            "total_mv": [10, 20, 30, 40, 50] * 2,
            "pe_ttm": [20, 15, 10, 8, 5] * 2,
            "pb": [5, 4, 3, 2, 1] * 2,
        }
    )
    events = pd.DataFrame(
        {
            "event_date": [date(2025, 1, 1), date(2026, 1, 1)],
            "car_0_1": [0.04, -0.02],
            "is_event": [True, False],
        }
    )
    earnings = pd.DataFrame(
        {
            "event_date": [date(2025, 1, 1)] * 5,
            "earnings_surprise": [-2, -1, 0, 1, 2],
            "event_car": [-0.2, -0.1, 0, 0.1, 0.2],
            "future_excess_return": [-0.1, -0.05, 0, 0.05, 0.1],
        }
    )
    shocks = pd.DataFrame(
        {
            "date": [date(2025, 1, 1), date(2026, 1, 1)],
            "market_adjusted_return": [0.08, -0.08],
            "future_excess_return": [0.02, 0.02],
            "local_formal_announcement_match": [True, False],
        }
    )
    financial = pd.DataFrame(
        {
            "report_period": [date(2025, 3, 31), date(2026, 3, 31)],
            "improvement_count": [1, 6],
            "future_excess_return": [-0.1, 0.1],
            "cash_component": [0.1, 0.2],
            "accrual_component": [0.2, 0.1],
            "future_profitability": [0.1, 0.2],
            "gross_profitability": [0.1, 0.2],
        }
    )

    results = (
        validate_size_value(size_value_observations(price.rename(columns={"date": "date"}))),
        validate_short_reversal(momentum_observations(price)),
        validate_common_factor_momentum(momentum_observations(price)),
        validate_daily_event_method(events),
        validate_earnings_reaction(earnings_reaction_observations(earnings)),
        validate_formal_announcement_shocks(formal_announcement_shock_observations(shocks)),
        validate_financial_improvement(financial),
    )

    for result in results:
        assert result
        assert not ({"pass", "score", "weight", "recommend"} & set(result))


def test_current_warehouse_validation_returns_thirteen_and_is_read_only():
    root = Path(__file__).parents[1] / "local_warehouse"
    database = root / "research.duckdb"
    before = hashlib.sha256(database.read_bytes()).hexdigest()

    evidence = validate_all_claims(root)

    after = hashlib.sha256(database.read_bytes()).hexdigest()
    assert tuple(item.legacy_id for item in evidence) == LEGACY_IDS
    assert all(isinstance(item.data_usable, bool) for item in evidence)
    assert not next(item for item in evidence if item.legacy_id == "src_ball_brown_1968").data_usable
    assert not next(item for item in evidence if item.legacy_id == "src_bernard_thomas_1989").data_usable
    assert not next(item for item in evidence if item.legacy_id == "src_chan_2003").data_usable
    assert before == after
