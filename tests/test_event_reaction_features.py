from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest


SHANGHAI = ZoneInfo("Asia/Shanghai")


def _inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, list]:
    dates = [value.date() for value in pd.bdate_range("2026-07-20", periods=26)]
    rows: list[dict[str, object]] = []
    for position, day in enumerate(dates):
        rows.append(
            {
                "trade_date": day,
                "ts_code": "000001.SZ",
                "close": 100.0 + position,
                "adj_factor": 1.0,
                "amount": 100.0 * (position - 19) if position >= 21 else 100.0,
            }
        )
        rows.append(
            {
                "trade_date": day,
                "ts_code": "000002.SZ",
                "close": 50.0,
                "adj_factor": 1.0,
                "amount": 100.0,
            }
        )
    benchmark = pd.DataFrame(
        {
            "trade_date": dates,
            "close": [200.0 + position * 2.0 for position in range(len(dates))],
        }
    )
    memberships = pd.DataFrame(
        [
            {
                "industry_system": "SW2021",
                "level": "L2",
                "industry_code": "801010.SI",
                "ts_code": code,
                "valid_from": dates[0],
                "valid_to": None,
            }
            for code in ("000001.SZ", "000002.SZ")
        ]
    )
    return pd.DataFrame(rows), benchmark, memberships, dates


def test_after_close_event_uses_next_full_session_and_reports_partial_reaction() -> None:
    from stock_analyzer.analysis.event_reaction_features import (
        EVENT_REACTION_EVIDENCE_ID,
        EVENT_REACTION_FORMULA_VERSION,
        compute_event_reaction_features,
    )

    equity, benchmark, memberships, dates = _inputs()
    events = pd.DataFrame(
        [
            {
                "event_id": "ANN-1",
                "ts_code": "000001.SZ",
                "available_at": datetime.combine(
                    dates[20],
                    datetime.min.time(),
                    SHANGHAI,
                ).replace(hour=15, minute=30),
            }
        ]
    )

    row = compute_event_reaction_features(
        events,
        equity,
        benchmark,
        analysis_date=dates[23],
        as_of=datetime.combine(
            dates[24], datetime.min.time(), SHANGHAI
        ).replace(hour=9, minute=10),
        trading_sessions=dates,
        industry_memberships=memberships,
    ).iloc[0]

    one_day = 121.0 / 120.0 - 1.0
    three_day = 123.0 / 120.0 - 1.0
    benchmark_one_day = 242.0 / 240.0 - 1.0
    industry_one_day = (one_day + 0.0) / 2.0
    assert row["evidence_id"] == EVENT_REACTION_EVIDENCE_ID
    assert row["formula_version"] == EVENT_REACTION_FORMULA_VERSION
    assert row["reaction_start_date"] == dates[21]
    assert row["observed_reaction_sessions"] == 3
    assert row["reaction_window_status"] == "partial"
    assert row["coverage_status"] == "limited"
    assert row["pre_event_return_5d"] == pytest.approx(120.0 / 115.0 - 1.0)
    assert row["event_return_1d"] == pytest.approx(one_day)
    assert row["event_return_3d"] == pytest.approx(three_day)
    assert np.isnan(row["event_return_5d"])
    assert row["relative_market_return_1d"] == pytest.approx(
        one_day - benchmark_one_day
    )
    assert row["relative_industry_return_1d"] == pytest.approx(
        one_day - industry_one_day
    )
    assert row["amount_ratio_1d"] == pytest.approx(2.0)
    assert row["amount_ratio_3d"] == pytest.approx(3.0)
    assert row["industry_comparison_status"] == "complete"


def test_preopen_event_uses_same_session_and_future_prices_do_not_change_result() -> None:
    from stock_analyzer.analysis.event_reaction_features import (
        compute_event_reaction_features,
    )

    equity, benchmark, memberships, dates = _inputs()
    events = pd.DataFrame(
        [
            {
                "event_id": "ANN-2",
                "ts_code": "000001.SZ",
                "available_at": datetime.combine(
                    dates[20], datetime.min.time(), SHANGHAI
                ).replace(hour=9),
            }
        ]
    )
    kwargs = {
        "analysis_date": dates[20],
        "as_of": datetime.combine(
            dates[21], datetime.min.time(), SHANGHAI
        ).replace(hour=9, minute=10),
        "trading_sessions": dates,
        "industry_memberships": memberships,
    }

    expected = compute_event_reaction_features(
        events,
        equity,
        benchmark,
        **kwargs,
    )
    changed = equity.copy()
    changed.loc[changed["trade_date"] > dates[20], "close"] = 10_000.0
    observed = compute_event_reaction_features(
        events,
        changed,
        benchmark.assign(
            close=lambda frame: frame["close"].where(
                frame["trade_date"] <= dates[20], 20_000.0
            )
        ),
        **kwargs,
    )

    assert expected.iloc[0]["reaction_start_date"] == dates[20]
    assert expected.iloc[0]["event_return_1d"] == pytest.approx(
        120.0 / 119.0 - 1.0
    )
    pd.testing.assert_frame_equal(observed, expected)


def test_event_known_after_close_can_be_awaiting_first_reaction_session() -> None:
    from stock_analyzer.analysis.event_reaction_features import (
        compute_event_reaction_features,
    )

    equity, benchmark, memberships, dates = _inputs()
    events = pd.DataFrame(
        [
            {
                "event_id": "ANN-3",
                "ts_code": "000001.SZ",
                "available_at": datetime.combine(
                    dates[23], datetime.min.time(), SHANGHAI
                ).replace(hour=20),
            }
        ]
    )

    row = compute_event_reaction_features(
        events,
        equity,
        benchmark,
        analysis_date=dates[23],
        as_of=datetime.combine(
            dates[24], datetime.min.time(), SHANGHAI
        ).replace(hour=9, minute=10),
        trading_sessions=dates,
        industry_memberships=memberships,
    ).iloc[0]

    assert row["reaction_start_date"] == dates[24]
    assert row["observed_reaction_sessions"] == 0
    assert row["reaction_window_status"] == "awaiting_first_session"
    assert np.isnan(row["event_return_1d"])


def test_event_available_after_as_of_is_rejected() -> None:
    from stock_analyzer.analysis.event_reaction_features import (
        compute_event_reaction_features,
    )

    equity, benchmark, memberships, dates = _inputs()
    cutoff = datetime.combine(
        dates[23], datetime.min.time(), SHANGHAI
    ).replace(hour=9, minute=10)
    events = pd.DataFrame(
        [
            {
                "event_id": "FUTURE",
                "ts_code": "000001.SZ",
                "available_at": cutoff.replace(hour=10),
            }
        ]
    )

    with pytest.raises(ValueError, match="event_available_after_as_of"):
        compute_event_reaction_features(
            events,
            equity,
            benchmark,
            analysis_date=dates[22],
            as_of=cutoff,
            trading_sessions=dates,
            industry_memberships=memberships,
        )
