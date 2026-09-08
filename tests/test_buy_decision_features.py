from datetime import date

import pytest

from stock_analyzer.analysis.buy_decision_features import (
    atr20_from_sessions,
    compute_buy_geometry,
    holding_window_end,
    normalize_price_history,
)


def test_price_distances_are_not_twenty_percent_targets():
    value = compute_buy_geometry(
        entry_price=8.0,
        upside_levels={"first_observation_area": 8.41},
        invalidation_price=7.8,
        atr=0.2,
        round_trip_cost_bps=None,
    )
    level = value["levels"]["first_observation_area"]
    assert level["gross_return_fraction"] == pytest.approx(0.05125)
    assert level["approx_net_return_fraction"] is None
    assert value["invalidation"]["gross_return_fraction"] == pytest.approx(-0.025)
    assert value["invalidation"]["distance_in_atr"] == pytest.approx(1.0)
    assert "buy_allowed" not in value
    assert "target_return" not in value


def test_cost_is_explicit_and_only_approximate():
    value = compute_buy_geometry(
        entry_price=8.0,
        upside_levels={"first_observation_area": 8.41},
        invalidation_price=None,
        round_trip_cost_bps=20,
    )
    assert value["levels"]["first_observation_area"][
        "approx_net_return_fraction"
    ] == pytest.approx(0.04925)
    assert value["invalidation"] is None


def test_first_session_is_entry_day():
    sessions = [date(2026, 9, 4), date(2026, 9, 7), date(2026, 9, 8)]
    assert holding_window_end(
        entry_session=sessions[0],
        horizon_sessions=2,
        trading_sessions=sessions,
    ) == date(2026, 9, 7)


def test_horizon_one_returns_entry_session_itself():
    sessions = [date(2026, 9, 4), date(2026, 9, 7)]
    assert holding_window_end(
        entry_session=date(2026, 9, 7),
        horizon_sessions=1,
        trading_sessions=sessions,
    ) == date(2026, 9, 7)


def test_non_trading_entry_session_is_rejected():
    sessions = [date(2026, 9, 4), date(2026, 9, 7)]
    with pytest.raises(ValueError, match="entry session"):
        holding_window_end(
            entry_session=date(2026, 9, 6),
            horizon_sessions=1,
            trading_sessions=sessions,
        )


def test_insufficient_trading_sessions_is_rejected():
    sessions = [date(2026, 9, 4), date(2026, 9, 7)]
    with pytest.raises(ValueError, match="trading sessions"):
        holding_window_end(
            entry_session=date(2026, 9, 7),
            horizon_sessions=3,
            trading_sessions=sessions,
        )


@pytest.mark.parametrize(
    "entry_price",
    [0.0, -1.0, float("nan"), float("inf"), float("-inf")],
)
def test_invalid_entry_price_is_rejected(entry_price):
    with pytest.raises(ValueError, match="entry_price"):
        compute_buy_geometry(
            entry_price=entry_price,
            upside_levels={"level": 8.41},
            invalidation_price=7.8,
        )


def test_invalid_level_price_is_rejected():
    with pytest.raises(ValueError, match="upside_levels"):
        compute_buy_geometry(
            entry_price=8.0,
            upside_levels={"level": float("nan")},
            invalidation_price=None,
        )


def test_negative_cost_is_rejected():
    with pytest.raises(ValueError, match="round_trip_cost_bps"):
        compute_buy_geometry(
            entry_price=8.0,
            upside_levels={"level": 8.41},
            invalidation_price=None,
            round_trip_cost_bps=-1,
        )


@pytest.mark.parametrize("atr", [0.0, -0.2, float("nan"), float("inf")])
def test_invalid_atr_is_rejected(atr):
    with pytest.raises(ValueError, match="atr"):
        compute_buy_geometry(
            entry_price=8.0,
            upside_levels={"level": 8.41},
            invalidation_price=7.8,
            atr=atr,
        )


def test_invalid_invalidation_price_is_rejected():
    with pytest.raises(ValueError, match="invalidation_price"):
        compute_buy_geometry(
            entry_price=8.0,
            upside_levels={"level": 8.41},
            invalidation_price=0.0,
        )


def test_missing_cost_keeps_net_return_unknown():
    value = compute_buy_geometry(
        entry_price=8.0,
        upside_levels={"level": 8.41},
        invalidation_price=7.8,
        atr=0.2,
        round_trip_cost_bps=None,
    )
    assert value["levels"]["level"]["approx_net_return_fraction"] is None
    assert value["invalidation"]["approx_net_return_fraction"] is None
    assert value["round_trip_cost_bps"] is None


def test_missing_atr_keeps_invalidation_distance_unknown():
    value = compute_buy_geometry(
        entry_price=8.0,
        upside_levels={"level": 8.41},
        invalidation_price=7.8,
        atr=None,
    )
    assert value["invalidation"]["distance_in_atr"] is None


def test_historical_level_below_entry_keeps_signed_distance():
    value = compute_buy_geometry(
        entry_price=8.0,
        upside_levels={"observed_history": 7.5},
        invalidation_price=None,
    )
    level = value["levels"]["observed_history"]
    assert level["gross_return_fraction"] == pytest.approx(-0.0625)
    assert level["approx_net_return_fraction"] is None


def test_invalidation_not_below_entry_is_flagged_not_converted():
    value = compute_buy_geometry(
        entry_price=8.0,
        upside_levels={"level": 8.41},
        invalidation_price=8.0,
        atr=0.2,
    )
    assert value["invalidation"]["below_entry"] is False
    assert value["invalidation"]["gross_return_fraction"] == pytest.approx(0.0)


def test_invalidation_below_entry_is_marked_suitable():
    value = compute_buy_geometry(
        entry_price=8.0,
        upside_levels={"level": 8.41},
        invalidation_price=7.8,
    )
    assert value["invalidation"]["below_entry"] is True


def test_atr20_is_simple_mean_true_range():
    # 21 行：首行只提供前收盘，其后每行真实波幅均为 0.5。
    base_rows = [
        {
            "date": date(2026, 7, 1 + index),
            "open": 10.2,
            "high": 10.5,
            "low": 10.0,
            "close": 10.2,
        }
        for index in range(21)
    ]
    value = atr20_from_sessions(base_rows)
    assert value == pytest.approx(0.5)


def test_atr20_requires_twenty_one_sessions():
    rows = [
        {"date": date(2026, 7, 1 + index), "open": 10.0, "high": 10.5, "low": 9.9, "close": 10.2}
        for index in range(20)
    ]
    assert atr20_from_sessions(rows) is None


def test_normalize_price_history_keeps_caliber_across_ex_dividend():
    # 除权日原始价跳低、复权因子跳高：归一口径应保持连续。
    rows = [
        {
            "date": date(2026, 6, 30),
            "open": 9.0,
            "high": 9.2,
            "low": 8.9,
            "close": 9.1,
            "amount": 1000.0,
            "factor": 4.0,
        },
        {
            "date": date(2026, 7, 1),
            "open": 8.2,
            "high": 8.4,
            "low": 8.1,
            "close": 8.3,
            "amount": 1100.0,
            "factor": 4.4,
        },
    ]
    normalized = normalize_price_history(rows, normalization_factor=4.4)
    assert normalized[0]["close"] == pytest.approx(9.1 * 4.0 / 4.4)
    assert normalized[1]["close"] == pytest.approx(8.3)
    # 归一后跨除权日收益是含分红再投资的连续口径，而不是把除权缺口当亏损。
    normalized_change = normalized[1]["close"] / normalized[0]["close"] - 1.0
    assert normalized_change == pytest.approx(
        (8.3 * 4.4) / (9.1 * 4.0) - 1.0
    )
    assert normalized_change != pytest.approx(8.3 / 9.1 - 1.0)


def test_normalize_price_history_requires_positive_normalization_factor():
    rows = [
        {
            "date": date(2026, 7, 1),
            "open": 8.2,
            "high": 8.4,
            "low": 8.1,
            "close": 8.3,
            "amount": 1100.0,
            "factor": 4.4,
        }
    ]
    assert normalize_price_history(rows, normalization_factor=None) == []
    assert normalize_price_history(rows, normalization_factor=0.0) == []
