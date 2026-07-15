from datetime import date

import numpy as np
import pandas as pd
import pytest

from stock_analyzer.knowledge_validation.signals import (
    announcement_reaction_signal,
    daily_event_signal,
    earnings_drift_signal,
    financial_turnaround_signal,
    industry_component_signal,
    industry_momentum_signal,
    limit_signal,
    map_announcement_sessions,
    reversal_signal,
    size_value_signal,
    compute_study_signal,
)


def test_ep_only_for_positive_pe():
    out = size_value_signal(
        pd.DataFrame(
            {
                "analysis_date": [date(2026, 7, 10)] * 3,
                "ts_code": ["A", "B", "C"],
                "pe_ttm": [10.0, -5.0, np.nan],
                "circ_mv": [100.0, 200.0, 300.0],
            }
        )
    )

    assert out.loc[0, "signal_value"] == pytest.approx(0.1)
    assert out.loc[1:, "signal_value"].isna().all()


def test_reversal_signal_uses_prior_twenty_session_return_and_stable_tie_break():
    frame = pd.DataFrame(
        {
            "analysis_date": [date(2026, 7, 10)] * 5,
            "ts_code": ["E", "D", "C", "B", "A"],
            "prior_return_20d": [0.1] * 5,
        }
    )

    out = reversal_signal(frame).set_index("ts_code")

    assert out.loc["A", "signal_quintile"] == 1
    assert out.loc["E", "signal_quintile"] == 5


def test_limit_touch_uses_high_and_up_limit():
    out = limit_signal(
        pd.DataFrame(
            {
                "analysis_date": [date(2026, 7, 10)],
                "ts_code": ["A"],
                "high": [10.0],
                "close": [9.8],
                "up_limit": [10.0],
            }
        )
    )

    assert bool(out.loc[0, "limit_touched"])
    assert not bool(out.loc[0, "closed_at_limit"])


def test_industry_momentum_keeps_breadth_and_concentration_as_separate_conditions():
    out = industry_momentum_signal(
        pd.DataFrame(
            {
                "analysis_date": [date(2026, 7, 10)] * 5,
                "industry_code": list("ABCDE"),
                "industry_return_20d": [0.01, 0.02, 0.03, 0.04, 0.05],
                "market_return_20d": [0.01] * 5,
                "breadth_20d": [0.4, 0.5, 0.6, 0.7, 0.8],
                "top_contribution_share_20d": [0.5, 0.4, 0.3, 0.2, 0.1],
            }
        )
    )

    assert out.loc[4, "relative_return_20d"] == pytest.approx(0.04)
    assert "breadth_20d" in out
    assert "top_contribution_share_20d" in out
    assert not any("combined" in column or "weight" in column for column in out)


def test_overseas_industry_method_only_subtracts_industry_component():
    out = industry_component_signal(
        pd.DataFrame(
            {
                "analysis_date": [date(2026, 7, 10)],
                "ts_code": ["A"],
                "prior_return_20d": [0.15],
                "industry_return_20d": [0.10],
            }
        )
    )

    assert out.loc[0, "industry_subtracted_return_20d"] == pytest.approx(0.05)


def test_daily_event_car_is_market_adjusted_and_uses_narrow_no_match_wording():
    out = daily_event_signal(
        pd.DataFrame(
            {
                "event_id": ["E1"],
                "ts_code": ["A"],
                "event_date": [date(2026, 7, 10)],
                "stock_return_0": [0.03],
                "stock_return_1": [0.02],
                "market_return_0": [0.01],
                "market_return_1": [0.005],
                "local_formal_announcement_match": [False],
            }
        )
    )

    assert out.loc[0, "car_0_1"] == pytest.approx(0.035)
    assert out.loc[0, "information_match_status"] == "no_local_formal_announcement_match"


def test_same_company_events_within_thirty_sessions_keep_earliest_event():
    frame = pd.DataFrame(
        {
            "event_id": ["E1", "E2", "E3"],
            "ts_code": ["A", "A", "A"],
            "event_date": [date(2026, 1, 1), date(2026, 1, 2), date(2026, 3, 1)],
            "event_session_index": [10, 40, 41],
            "stock_return_0": [0.01] * 3,
            "stock_return_1": [0.01] * 3,
            "market_return_0": [0.0] * 3,
            "market_return_1": [0.0] * 3,
            "local_formal_announcement_match": [True] * 3,
        }
    )

    out = daily_event_signal(frame)

    assert out["event_id"].tolist() == ["E1", "E3"]


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


def test_earnings_drift_ranks_event_car_within_event_date():
    out = earnings_drift_signal(
        pd.DataFrame(
            {
                "event_date": [date(2026, 7, 10)] * 5,
                "ts_code": list("ABCDE"),
                "event_car_0_1": [-0.05, -0.02, 0.0, 0.02, 0.05],
            }
        )
    ).set_index("ts_code")

    assert out.loc["A", "car_quintile"] == 1
    assert out.loc["E", "car_quintile"] == 5


def test_announcement_reaction_does_not_claim_no_public_information():
    out = announcement_reaction_signal(
        pd.DataFrame(
            {
                "analysis_date": [date(2026, 7, 10)],
                "ts_code": ["A"],
                "market_adjusted_return": [0.08],
                "local_formal_announcement_match": [False],
            }
        )
    )

    assert out.loc[0, "information_match_status"] == "no_local_formal_announcement_match"
    assert "no_public" not in " ".join(map(str, out.iloc[0].tolist()))


def test_financial_turnaround_counts_exactly_six_improvement_directions():
    out = financial_turnaround_signal(
        pd.DataFrame(
            {
                "ts_code": ["A"],
                "report_period": ["2026-03-31"],
                "roe": [12.0],
                "prior_roe": [10.0],
                "operating_cash_flow": [120.0],
                "prior_operating_cash_flow": [100.0],
                "leverage": [0.4],
                "prior_leverage": [0.5],
                "current_ratio": [1.5],
                "prior_current_ratio": [1.2],
                "profit_margin": [0.12],
                "prior_profit_margin": [0.10],
                "asset_turnover": [0.8],
                "prior_asset_turnover": [0.7],
            }
        )
    )

    assert out.loc[0, "improvement_count"] == 6
    assert "f_score" not in out


@pytest.mark.parametrize("column", ["future_close", "touch_20pct_10d"])
def test_every_signal_rejects_future_label_columns(column: str):
    frame = pd.DataFrame(
        {
            "analysis_date": [date(2026, 7, 10)],
            "ts_code": ["A"],
            "prior_return_20d": [0.1],
            column: [1.0],
        }
    )

    with pytest.raises(ValueError, match="future label"):
        reversal_signal(frame)


def test_signal_dispatch_is_closed_to_the_frozen_study_set():
    with pytest.raises(ValueError, match="unsupported validation study"):
        compute_study_signal("invented_method", pd.DataFrame())
