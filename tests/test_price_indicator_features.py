from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from stock_analyzer.analysis.price_indicator_features import (
    PRICE_INDICATOR_FORMULA_VERSION,
    compute_price_indicator_features,
    compute_price_indicator_panel,
)


ANALYSIS_DATE = date(2026, 7, 10)


def _prices(
    closes: list[float],
    *,
    end: date = ANALYSIS_DATE,
    code: str = "A.SZ",
    amounts: list[float] | None = None,
) -> pd.DataFrame:
    dates = pd.bdate_range(end=end, periods=len(closes))
    amount_values = amounts or [100.0] * len(closes)
    return pd.DataFrame(
        {
            "trade_date": dates.date,
            "ts_code": code,
            "open": closes,
            "high": np.asarray(closes, dtype=float) + 1.0,
            "low": np.asarray(closes, dtype=float) - 1.0,
            "close": closes,
            "adj_factor": 1.0,
            "amount": amount_values,
        }
    )


def _row(frame: pd.DataFrame, *, analysis_date: date = ANALYSIS_DATE) -> pd.Series:
    return compute_price_indicator_features(
        frame,
        analysis_date=analysis_date,
    ).iloc[0]


def test_fixed_formulas_match_hand_calculated_trend_and_range_cases() -> None:
    steadily_rising = _prices(np.arange(1.0, 61.0).tolist())

    row = _row(steadily_rising)

    assert row["formula_version"] == PRICE_INDICATOR_FORMULA_VERSION
    assert row["price_basis"] == "ohlc_times_adj_factor"
    assert row["efficiency_ratio_20d"] == pytest.approx(1.0)
    assert row["rsi_14d"] == pytest.approx(100.0)
    assert row["adx_14d"] == pytest.approx(100.0)
    assert row["macd_dif_12_26"] > 0
    assert row["macd_histogram_12_26_9"] > 0

    exactly_twenty = _prices(np.arange(1.0, 21.0).tolist())
    bollinger = _row(exactly_twenty)
    middle = 10.5
    deviation = np.sqrt(33.25)
    lower = middle - 2.0 * deviation
    upper = middle + 2.0 * deviation
    assert bollinger["bollinger_percent_b_20_2"] == pytest.approx(
        (20.0 - lower) / (upper - lower)
    )
    assert bollinger["bollinger_bandwidth_20_2"] == pytest.approx(
        (upper - lower) / middle
    )


def test_k_and_d_use_nine_day_rsv_and_fifty_initial_values() -> None:
    frame = _prices(np.arange(1.0, 10.0).tolist())

    row = _row(frame)

    # Rolling low is 0, rolling high is 10 and current close is 9: RSV=90.
    expected_k = (2.0 / 3.0) * 50.0 + (1.0 / 3.0) * 90.0
    expected_d = (2.0 / 3.0) * 50.0 + (1.0 / 3.0) * expected_k
    assert row["stochastic_k_9_3"] == pytest.approx(expected_k)
    assert row["stochastic_d_9_3"] == pytest.approx(expected_d)


def test_price_amount_fields_have_bounded_literal_meaning() -> None:
    closes = [100.0]
    amounts = [1.0]
    signed_amount_numerator = 0.0
    efficiency_numerator = 0.0
    efficiency_denominator = 0.0
    for offset in range(1, 21):
        move = 0.01 if offset % 2 else -0.005
        closes.append(closes[-1] * (1.0 + move))
        amount = float(offset)
        amounts.append(amount)
        signed_amount_numerator += np.sign(move) * amount
        efficiency_numerator += move * amount
        efficiency_denominator += abs(move) * amount

    row = _row(_prices(closes, amounts=amounts))

    assert row["signed_amount_balance_20d"] == pytest.approx(
        signed_amount_numerator / sum(amounts[-20:])
    )
    assert row["price_amount_efficiency_20d"] == pytest.approx(
        efficiency_numerator / efficiency_denominator
    )
    assert -1.0 <= row["signed_amount_balance_20d"] <= 1.0
    assert -1.0 <= row["price_amount_efficiency_20d"] <= 1.0


def test_long_anchor_excludes_current_day_from_prior_high() -> None:
    frame = _prices(np.arange(1.0, 252.0).tolist())
    frame.loc[frame.index[:-1], "high"] = np.arange(1.0, 251.0)
    frame.loc[frame.index[-1], ["open", "high", "low", "close"]] = [
        251.0,
        252.0,
        250.0,
        251.0,
    ]

    row = _row(frame)

    assert row["distance_to_prior_250d_high"] == pytest.approx(251.0 / 250.0 - 1.0)
    assert bool(row["breakout_prior_250d_high"])


def test_adjusted_prices_remove_a_mechanical_split_from_indicators() -> None:
    closes = np.linspace(80.0, 100.0, 60).tolist()
    continuous = _prices(closes)
    split = continuous.copy()
    split.loc[split.index[-20:], ["open", "high", "low", "close"]] /= 2.0
    split.loc[split.index[-20:], "adj_factor"] = 2.0

    expected = _row(continuous)
    observed = _row(split)

    for field in (
        "ema_distance_20d",
        "macd_dif_12_26",
        "macd_dea_9",
        "macd_histogram_12_26_9",
        "efficiency_ratio_20d",
        "adx_14d",
        "rsi_14d",
        "stochastic_k_9_3",
        "stochastic_d_9_3",
        "bollinger_percent_b_20_2",
        "bollinger_bandwidth_20_2",
    ):
        assert observed[field] == pytest.approx(expected[field])


def test_future_rows_cannot_change_a_historical_snapshot() -> None:
    frame = _prices(np.linspace(50.0, 100.0, 251).tolist())
    future = _prices(
        [1_000.0, 2_000.0],
        end=date(2026, 7, 14),
        amounts=[1_000_000.0, 2_000_000.0],
    )
    future = future[future["trade_date"] > ANALYSIS_DATE]

    expected = compute_price_indicator_features(
        frame,
        analysis_date=ANALYSIS_DATE,
    )
    observed = compute_price_indicator_features(
        pd.concat([frame, future], ignore_index=True),
        analysis_date=ANALYSIS_DATE,
    )

    pd.testing.assert_frame_equal(observed, expected)


def test_short_history_is_declared_limited_instead_of_filled() -> None:
    row = _row(_prices(np.arange(10.0, 20.0).tolist()))

    assert row["coverage_status"] == "limited"
    assert row["available_price_sessions"] == 10
    assert np.isnan(row["ema_distance_20d"])
    assert np.isnan(row["macd_dif_12_26"])
    assert np.isnan(row["efficiency_ratio_20d"])
    assert np.isnan(row["rsi_14d"])
    assert np.isnan(row["bollinger_percent_b_20_2"])
    assert np.isnan(row["distance_to_prior_250d_high"])
    assert "short history" in row["limitation_notes"]


def test_panel_matches_independent_point_in_time_snapshots() -> None:
    frame = _prices(np.linspace(10.0, 100.0, 260).tolist())
    dates = frame["trade_date"].tolist()
    formation_dates = [dates[-6], dates[-1]]

    panel = compute_price_indicator_panel(frame, formation_dates=formation_dates)

    expected = pd.concat(
        [
            compute_price_indicator_features(frame, analysis_date=formation_date)
            for formation_date in formation_dates
        ],
        ignore_index=True,
    )
    pd.testing.assert_frame_equal(
        panel.reset_index(drop=True),
        expected.reset_index(drop=True),
    )


def test_duplicate_business_rows_are_rejected() -> None:
    frame = _prices(np.arange(1.0, 31.0).tolist())
    duplicate = pd.concat([frame, frame.iloc[[-1]]], ignore_index=True)

    with pytest.raises(ValueError, match="duplicate business fact"):
        compute_price_indicator_features(duplicate, analysis_date=ANALYSIS_DATE)


def test_direction_and_state_change_fields_preserve_their_literal_meaning() -> None:
    closes = np.r_[np.linspace(120.0, 80.0, 50), np.linspace(80.0, 120.0, 30)]
    frame = _prices(closes.tolist())
    dates = frame["trade_date"].tolist()
    analysis_date = dates[-1]
    five_sessions_earlier = dates[-6]

    panel = compute_price_indicator_panel(
        frame,
        formation_dates=[five_sessions_earlier, analysis_date],
    ).set_index("analysis_date")
    earlier = panel.loc[five_sessions_earlier]
    current = panel.loc[analysis_date]

    adjusted_close = float(frame.loc[frame["trade_date"] == analysis_date, "close"].iloc[0])
    assert current["macd_histogram_ratio_12_26_9"] == pytest.approx(
        current["macd_histogram_12_26_9"] / adjusted_close
    )
    assert current["macd_histogram_ratio_change_5d"] == pytest.approx(
        current["macd_histogram_ratio_12_26_9"]
        - earlier["macd_histogram_ratio_12_26_9"]
    )
    assert current["bollinger_bandwidth_change_5d"] == pytest.approx(
        current["bollinger_bandwidth_20_2"]
        - earlier["bollinger_bandwidth_20_2"]
    )
    assert current["stochastic_k_minus_d"] == pytest.approx(
        current["stochastic_k_9_3"] - current["stochastic_d_9_3"]
    )
    assert current["dmi_directional_spread_14d"] == pytest.approx(
        current["dmi_plus_14d"] - current["dmi_minus_14d"]
    )
    assert current["dmi_directional_spread_14d"] > 0.0


def test_recent_cross_flags_cover_the_last_five_sessions_only() -> None:
    closes = np.r_[np.linspace(120.0, 80.0, 50), np.linspace(80.0, 120.0, 30)]
    frame = _prices(closes.tolist())
    dates = frame["trade_date"].tolist()
    recent_cross_date = date(2026, 6, 5)

    panel = compute_price_indicator_panel(
        frame,
        formation_dates=[recent_cross_date, dates[-1]],
    ).set_index("analysis_date")

    assert bool(panel.loc[recent_cross_date, "macd_bullish_cross_last_5d"])
    assert bool(panel.loc[recent_cross_date, "stochastic_bullish_cross_last_5d"])
    assert not bool(panel.loc[dates[-1], "macd_bullish_cross_last_5d"])
    assert not bool(panel.loc[dates[-1], "stochastic_bullish_cross_last_5d"])


def test_dmi_direction_distinguishes_rising_from_falling_trends() -> None:
    rising = _row(_prices(np.arange(1.0, 81.0).tolist()))
    falling = _row(_prices(np.arange(80.0, 0.0, -1.0).tolist()))

    assert rising["dmi_plus_14d"] > rising["dmi_minus_14d"]
    assert rising["dmi_directional_spread_14d"] > 0.0
    assert falling["dmi_minus_14d"] > falling["dmi_plus_14d"]
    assert falling["dmi_directional_spread_14d"] < 0.0
