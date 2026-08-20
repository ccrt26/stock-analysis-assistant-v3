"""Point-in-time technical observations derived from local daily facts.

The indicators in this module are research candidates, not trading signals.
They use adjusted OHLC prices, preserve missing market sessions, and never read
past the requested formation date.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

import numpy as np
import pandas as pd


PRICE_INDICATOR_FORMULA_VERSION = "price-indicator-conditional-states-v2"

_REQUIRED_COLUMNS = {
    "trade_date",
    "ts_code",
    "open",
    "high",
    "low",
    "close",
    "adj_factor",
    "amount",
}
_NUMERIC_COLUMNS = ("open", "high", "low", "close", "adj_factor", "amount")
_NUMERIC_FEATURES = (
    "ema_distance_20d",
    "macd_dif_12_26",
    "macd_dea_9",
    "macd_histogram_12_26_9",
    "macd_histogram_ratio_12_26_9",
    "macd_histogram_ratio_change_5d",
    "efficiency_ratio_20d",
    "adx_14d",
    "dmi_plus_14d",
    "dmi_minus_14d",
    "dmi_directional_spread_14d",
    "rsi_14d",
    "stochastic_k_9_3",
    "stochastic_d_9_3",
    "stochastic_k_minus_d",
    "bollinger_percent_b_20_2",
    "bollinger_bandwidth_20_2",
    "bollinger_bandwidth_change_5d",
    "distance_to_prior_250d_high",
    "signed_amount_balance_20d",
    "price_amount_efficiency_20d",
)
_BOOLEAN_FEATURES = (
    "macd_bullish_cross_last_5d",
    "macd_bearish_cross_last_5d",
    "stochastic_bullish_cross_last_5d",
    "stochastic_bearish_cross_last_5d",
)


def compute_price_indicator_features(
    equity_daily: pd.DataFrame,
    *,
    analysis_date: date,
) -> pd.DataFrame:
    """Return one research-indicator row per stock present on ``analysis_date``."""

    return compute_price_indicator_panel(
        equity_daily,
        formation_dates=(_as_date(analysis_date),),
    )


def compute_price_indicator_panel(
    equity_daily: pd.DataFrame,
    *,
    formation_dates: Iterable[date],
) -> pd.DataFrame:
    """Return point-in-time rows for a fixed collection of formation dates.

    The input is truncated at the latest requested date before duplicate checks
    and calculation.  Each stock is reindexed to the union of market sessions,
    so a missing stock row remains a gap instead of compressing a rolling window.
    """

    requested_dates = tuple(sorted({_as_date(value) for value in formation_dates}))
    if not requested_dates:
        return _empty_result()
    frame = _prepare_equity(equity_daily, through=requested_dates[-1])
    if frame.empty:
        return _empty_result()
    session_index = pd.Index(
        sorted(frame["trade_date"].unique()),
        name="trade_date",
    )
    requested = set(requested_dates)
    rows: list[dict[str, object]] = []
    for code, values in frame.groupby("ts_code", sort=True):
        stock = values.set_index("trade_date").reindex(session_index)
        observed_dates = set(values["trade_date"].tolist())
        output_dates = [
            formation_date
            for formation_date in requested_dates
            if formation_date in observed_dates
        ]
        if not output_dates:
            continue
        calculated = _calculate_stock_panel(stock)
        for formation_date in output_dates:
            rows.append(
                _output_row(
                    str(code),
                    formation_date,
                    stock,
                    calculated,
                    requested,
                )
            )
    if not rows:
        return _empty_result()
    return (
        pd.DataFrame(rows)
        .sort_values(["analysis_date", "ts_code"])
        .reset_index(drop=True)
    )


def _prepare_equity(frame: pd.DataFrame, *, through: date) -> pd.DataFrame:
    missing = sorted(_REQUIRED_COLUMNS - set(frame.columns))
    if missing:
        raise ValueError(f"equity daily lacks required fields: {', '.join(missing)}")
    prepared = frame.copy()
    prepared["trade_date"] = pd.to_datetime(
        prepared["trade_date"], errors="raise"
    ).dt.date
    prepared = prepared[prepared["trade_date"] <= through].copy()
    if prepared.duplicated(["trade_date", "ts_code"]).any():
        raise ValueError("duplicate business fact in equity daily input")
    for column in _NUMERIC_COLUMNS:
        prepared[column] = pd.to_numeric(prepared[column], errors="coerce")
    return prepared.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)


def _calculate_stock_panel(stock: pd.DataFrame) -> pd.DataFrame:
    adjustment = stock["adj_factor"].astype(float)
    valid_adjustment = np.isfinite(adjustment) & (adjustment > 0)
    adjusted = pd.DataFrame(index=stock.index)
    for field in ("open", "high", "low", "close"):
        adjusted[field] = stock[field].astype(float) * adjustment
        adjusted.loc[~valid_adjustment, field] = np.nan
    close = adjusted["close"]
    high = adjusted["high"]
    low = adjusted["low"]
    amount = stock["amount"].astype(float)
    daily_return = close.pct_change(fill_method=None).replace(
        [np.inf, -np.inf], np.nan
    )

    ema20 = close.ewm(span=20, adjust=False, min_periods=20).mean()
    ema12 = close.ewm(span=12, adjust=False, min_periods=12).mean()
    ema26 = close.ewm(span=26, adjust=False, min_periods=26).mean()
    macd_dif = ema12 - ema26
    macd_dea = macd_dif.ewm(span=9, adjust=False, min_periods=9).mean()
    macd_histogram = 2.0 * (macd_dif - macd_dea)
    macd_histogram_ratio = macd_histogram / close.replace(0.0, np.nan)
    macd_bullish_cross = _recent_cross(macd_histogram, positive=True)
    macd_bearish_cross = _recent_cross(macd_histogram, positive=False)

    net_change = (close - close.shift(20)).abs()
    path_length = close.diff().abs().rolling(20, min_periods=20).sum()
    efficiency_ratio = net_change / path_length.replace(0.0, np.nan)

    dmi_plus, dmi_minus, adx = _dmi(high, low, close, window=14)
    rsi = _rsi(close, window=14)
    stochastic_k, stochastic_d = _stochastic_kd(high, low, close, window=9)
    stochastic_spread = stochastic_k - stochastic_d
    stochastic_bullish_cross = _recent_cross(stochastic_spread, positive=True)
    stochastic_bearish_cross = _recent_cross(stochastic_spread, positive=False)

    middle = close.rolling(20, min_periods=20).mean()
    deviation = close.rolling(20, min_periods=20).std(ddof=0)
    upper = middle + 2.0 * deviation
    lower = middle - 2.0 * deviation
    band_range = upper - lower
    bandwidth = band_range / middle.replace(0.0, np.nan)

    prior_high = high.shift(1).rolling(250, min_periods=250).max()
    distance_to_prior_high = close / prior_high - 1.0
    breakout_prior_high = close >= prior_high
    breakout_prior_high = breakout_prior_high.where(prior_high.notna())

    valid_amount = amount.where(np.isfinite(amount) & (amount >= 0))
    signed_amount = np.sign(daily_return) * valid_amount
    signed_amount_sum = signed_amount.rolling(20, min_periods=20).sum()
    amount_sum = valid_amount.rolling(20, min_periods=20).sum()
    weighted_return = daily_return * valid_amount
    weighted_absolute_return = daily_return.abs() * valid_amount
    price_amount_numerator = weighted_return.rolling(20, min_periods=20).sum()
    price_amount_denominator = weighted_absolute_return.rolling(
        20, min_periods=20
    ).sum()

    return pd.DataFrame(
        {
            "ema_distance_20d": close / ema20 - 1.0,
            "macd_dif_12_26": macd_dif,
            "macd_dea_9": macd_dea,
            "macd_histogram_12_26_9": macd_histogram,
            "macd_histogram_ratio_12_26_9": macd_histogram_ratio,
            "macd_histogram_ratio_change_5d": macd_histogram_ratio
            - macd_histogram_ratio.shift(5),
            "macd_bullish_cross_last_5d": macd_bullish_cross,
            "macd_bearish_cross_last_5d": macd_bearish_cross,
            "efficiency_ratio_20d": efficiency_ratio,
            "adx_14d": adx,
            "dmi_plus_14d": dmi_plus,
            "dmi_minus_14d": dmi_minus,
            "dmi_directional_spread_14d": dmi_plus - dmi_minus,
            "rsi_14d": rsi,
            "stochastic_k_9_3": stochastic_k,
            "stochastic_d_9_3": stochastic_d,
            "stochastic_k_minus_d": stochastic_spread,
            "stochastic_bullish_cross_last_5d": stochastic_bullish_cross,
            "stochastic_bearish_cross_last_5d": stochastic_bearish_cross,
            "bollinger_percent_b_20_2": close / band_range
            - lower / band_range,
            "bollinger_bandwidth_20_2": bandwidth,
            "bollinger_bandwidth_change_5d": bandwidth - bandwidth.shift(5),
            "distance_to_prior_250d_high": distance_to_prior_high,
            "breakout_prior_250d_high": breakout_prior_high,
            "signed_amount_balance_20d": signed_amount_sum
            / amount_sum.replace(0.0, np.nan),
            "price_amount_efficiency_20d": price_amount_numerator
            / price_amount_denominator.replace(0.0, np.nan),
        },
        index=stock.index,
    ).replace([np.inf, -np.inf], np.nan)


def _rsi(close: pd.Series, *, window: int) -> pd.Series:
    delta = close.diff()
    gains = delta.clip(lower=0.0)
    losses = -delta.clip(upper=0.0)
    average_gain = gains.ewm(
        alpha=1.0 / window,
        adjust=False,
        min_periods=window,
    ).mean()
    average_loss = losses.ewm(
        alpha=1.0 / window,
        adjust=False,
        min_periods=window,
    ).mean()
    relative_strength = average_gain / average_loss.replace(0.0, np.nan)
    result = 100.0 - 100.0 / (1.0 + relative_strength)
    result = result.where(~((average_gain > 0) & (average_loss == 0)), 100.0)
    result = result.where(~((average_gain == 0) & (average_loss > 0)), 0.0)
    result = result.where(~((average_gain == 0) & (average_loss == 0)), 50.0)
    return result


def _dmi(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    *,
    window: int,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    previous_close = close.shift(1)
    true_range = pd.concat(
        [
            high - low,
            (high - previous_close).abs(),
            (low - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1, skipna=False)
    upward_move = high.diff()
    downward_move = -low.diff()
    plus_dm = upward_move.where(
        (upward_move > downward_move) & (upward_move > 0.0),
        0.0,
    )
    minus_dm = downward_move.where(
        (downward_move > upward_move) & (downward_move > 0.0),
        0.0,
    )
    plus_dm = plus_dm.where(upward_move.notna() & downward_move.notna())
    minus_dm = minus_dm.where(upward_move.notna() & downward_move.notna())
    average_true_range = true_range.ewm(
        alpha=1.0 / window,
        adjust=False,
        min_periods=window,
    ).mean()
    smoothed_plus = plus_dm.ewm(
        alpha=1.0 / window,
        adjust=False,
        min_periods=window,
    ).mean()
    smoothed_minus = minus_dm.ewm(
        alpha=1.0 / window,
        adjust=False,
        min_periods=window,
    ).mean()
    plus_di = 100.0 * smoothed_plus / average_true_range.replace(0.0, np.nan)
    minus_di = 100.0 * smoothed_minus / average_true_range.replace(0.0, np.nan)
    denominator = plus_di + minus_di
    dx = 100.0 * (plus_di - minus_di).abs() / denominator.replace(0.0, np.nan)
    adx = dx.ewm(
        alpha=1.0 / window,
        adjust=False,
        min_periods=window,
    ).mean()
    return plus_di, minus_di, adx


def _recent_cross(series: pd.Series, *, positive: bool) -> pd.Series:
    previous = series.shift(1)
    valid = series.notna() & previous.notna()
    if positive:
        event = (series > 0.0) & (previous <= 0.0)
    else:
        event = (series < 0.0) & (previous >= 0.0)
    event = event.astype(float).where(valid)
    return event.rolling(5, min_periods=5).max()


def _stochastic_kd(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    *,
    window: int,
) -> tuple[pd.Series, pd.Series]:
    rolling_low = low.rolling(window, min_periods=window).min()
    rolling_high = high.rolling(window, min_periods=window).max()
    price_range = rolling_high - rolling_low
    rsv = 100.0 * (close - rolling_low) / price_range.replace(0.0, np.nan)
    k_values = np.full(len(close), np.nan, dtype=float)
    d_values = np.full(len(close), np.nan, dtype=float)
    previous_k = 50.0
    previous_d = 50.0
    for position, value in enumerate(rsv.to_numpy(dtype=float)):
        if not np.isfinite(value):
            continue
        previous_k = (2.0 / 3.0) * previous_k + (1.0 / 3.0) * value
        previous_d = (2.0 / 3.0) * previous_d + (1.0 / 3.0) * previous_k
        k_values[position] = previous_k
        d_values[position] = previous_d
    return (
        pd.Series(k_values, index=close.index),
        pd.Series(d_values, index=close.index),
    )


def _output_row(
    code: str,
    formation_date: date,
    stock: pd.DataFrame,
    calculated: pd.DataFrame,
    requested: set[date],
) -> dict[str, object]:
    del requested
    values = calculated.loc[formation_date]
    history = stock.loc[:formation_date, "close"].tail(251)
    adjusted_history = history * stock.loc[history.index, "adj_factor"]
    available_sessions = int(
        (np.isfinite(adjusted_history) & (adjusted_history > 0)).sum()
    )
    result: dict[str, object] = {
        "analysis_date": formation_date,
        "ts_code": code,
        "formula_version": PRICE_INDICATOR_FORMULA_VERSION,
        "price_basis": "ohlc_times_adj_factor",
        "available_price_sessions": available_sessions,
    }
    for field in _NUMERIC_FEATURES:
        result[field] = float(values[field]) if np.isfinite(values[field]) else np.nan
    for field in _BOOLEAN_FEATURES:
        value = values[field]
        result[field] = bool(value) if pd.notna(value) else np.nan
    breakout = values["breakout_prior_250d_high"]
    result["breakout_prior_250d_high"] = (
        bool(breakout) if pd.notna(breakout) else np.nan
    )
    complete = (
        all(np.isfinite(result[field]) for field in _NUMERIC_FEATURES)
        and all(pd.notna(result[field]) for field in _BOOLEAN_FEATURES)
        and pd.notna(result["breakout_prior_250d_high"])
    )
    result["coverage_status"] = "complete" if complete else "limited"
    limitations: list[str] = []
    if available_sessions < 251:
        limitations.append(
            f"short history: {available_sessions}/251 adjusted price sessions available"
        )
    missing_features = [
        field
        for field in (*_NUMERIC_FEATURES, *_BOOLEAN_FEATURES, "breakout_prior_250d_high")
        if pd.isna(result[field])
    ]
    if missing_features:
        limitations.append("unavailable fields: " + ", ".join(missing_features))
    result["limitation_notes"] = "; ".join(limitations)
    return result


def _empty_result() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "analysis_date",
            "ts_code",
            "formula_version",
            "price_basis",
            "available_price_sessions",
            *_NUMERIC_FEATURES,
            *_BOOLEAN_FEATURES,
            "breakout_prior_250d_high",
            "coverage_status",
            "limitation_notes",
        ]
    )


def _as_date(value: date) -> date:
    if isinstance(value, date):
        return value
    return pd.Timestamp(value).date()


__all__ = [
    "PRICE_INDICATOR_FORMULA_VERSION",
    "compute_price_indicator_features",
    "compute_price_indicator_panel",
]
