"""Deterministic observations of each stock's daily trading context.

The module describes daily prices, turnover, limits and valuation.  It does
not rank securities, infer who traded, or recommend an action.  Every input is
bounded again by ``analysis_date`` so an accidental future row cannot alter a
historical snapshot.
"""

from __future__ import annotations

from datetime import date
from math import sqrt

import numpy as np
import pandas as pd


STOCK_CONTEXT_FORMULA_VERSION = "stock-trading-context-v1"
RETURN_HORIZONS = (1, 5, 10, 20, 60)
RISK_WINDOW = 60
VOLATILITY_WINDOW = 20
PRICE_LOCATION_WINDOWS = (60, 82)
HIGH_VOLUME_WINDOW = 60
HIGH_VOLUME_QUANTILE = 0.80
COUNTERTREND_WINDOW = 60
COUNTERTREND_MARKET_THRESHOLD = -0.005
COUNTERTREND_HALF_LIFE = 20.0
LIMIT_WINDOW = 5
VALUATION_WINDOW = 250


def compute_stock_context_features(
    equity_daily: pd.DataFrame,
    benchmark_daily: pd.DataFrame,
    stock_limits: pd.DataFrame,
    valuations: pd.DataFrame,
    *,
    analysis_date: date,
) -> pd.DataFrame:
    """Return one decision-free observation row per stock present today.

    Returns use exact market-session offsets rather than compressing missing
    dates.  Beta is covariance divided by benchmark variance over 60 complete
    paired daily returns.  Realized volatility is the sample standard
    deviation of 20 daily returns annualized by ``sqrt(252)``.  ATR is the
    20-session mean true range divided by the current close.

    A high-volume day is in the top 20 percent of valid amounts in the most
    recent 60 sessions (at least five observations).  Close location is
    ``(close-low)/(high-low)`` and body efficiency is
    ``abs(close-open)/(high-low)``; zero-range days remain unavailable.
    """

    analysis_date = _as_date(analysis_date)
    equity = _prepare_frame(
        equity_daily,
        required={"trade_date", "ts_code", "open", "high", "low", "close", "amount"},
        key=("trade_date", "ts_code"),
        numeric=("open", "high", "low", "close", "amount"),
        label="equity daily",
        analysis_date=analysis_date,
    )
    benchmark = _prepare_frame(
        benchmark_daily,
        required={"trade_date", "close"},
        key=("trade_date",),
        numeric=("close",),
        label="benchmark daily",
        analysis_date=analysis_date,
    )
    limits = _prepare_frame(
        stock_limits,
        required={"trade_date", "ts_code", "up_limit", "down_limit"},
        key=("trade_date", "ts_code"),
        numeric=("up_limit", "down_limit"),
        label="stock limit",
        analysis_date=analysis_date,
    )
    valuation = _prepare_frame(
        valuations,
        required={"trade_date", "ts_code", "pe_ttm", "pb"},
        key=("trade_date", "ts_code"),
        numeric=("pe_ttm", "pb"),
        label="valuation",
        analysis_date=analysis_date,
    )

    current_codes = sorted(
        equity.loc[equity["trade_date"] == analysis_date, "ts_code"]
        .astype(str)
        .unique()
    )
    if not current_codes:
        return pd.DataFrame()

    session_dates = sorted(
        set(equity["trade_date"].tolist()) | set(benchmark["trade_date"].tolist())
    )
    session_index = pd.Index(session_dates, name="trade_date")
    benchmark_series = (
        benchmark.set_index("trade_date")["close"].reindex(session_index).astype(float)
    )
    rows = [
        _compute_stock_row(
            code,
            equity,
            benchmark_series,
            limits,
            valuation,
            session_index,
            analysis_date,
        )
        for code in current_codes
    ]
    return pd.DataFrame(rows).sort_values("ts_code").reset_index(drop=True)


def _compute_stock_row(
    code: str,
    equity: pd.DataFrame,
    benchmark: pd.Series,
    limits: pd.DataFrame,
    valuations: pd.DataFrame,
    session_index: pd.Index,
    analysis_date: date,
) -> dict[str, object]:
    stock = (
        equity[equity["ts_code"].astype(str) == code]
        .set_index("trade_date")
        .reindex(session_index)
    )
    closes = stock["close"].astype(float)
    amounts = stock["amount"].astype(float)
    benchmark = benchmark.reindex(session_index)
    stock_returns = closes.pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan)
    benchmark_returns = benchmark.pct_change(fill_method=None).replace(
        [np.inf, -np.inf], np.nan
    )
    current = stock.loc[analysis_date]
    current_core_valid = _valid_ohlc_amount(current)
    benchmark_current_valid = _finite_positive_scalar(benchmark.loc[analysis_date])
    trailing_price = closes.tail(82)
    available_price_sessions = int(_finite_positive(trailing_price).sum())
    limitations: list[str] = ["trader identity unavailable from daily facts"]
    if not current_core_valid:
        limitations.append("current price or amount fact is incomplete")
    if not benchmark_current_valid:
        limitations.append("current benchmark close is incomplete")
    if len(trailing_price) < 82 or available_price_sessions < len(trailing_price):
        limitations.append(
            f"short price history: {available_price_sessions}/82 sessions available"
        )

    row: dict[str, object] = {
        "analysis_date": analysis_date,
        "ts_code": code,
        "formula_version": STOCK_CONTEXT_FORMULA_VERSION,
        "available_price_sessions": available_price_sessions,
        "trader_identity_status": "unavailable",
        "interpretation_limit": "observable daily price, turnover and valuation facts only",
    }
    for horizon in RETURN_HORIZONS:
        stock_return = _exact_return(closes, horizon, analysis_date)
        benchmark_return = _exact_return(benchmark, horizon, analysis_date)
        row[f"return_{horizon}d"] = stock_return
        row[f"relative_return_{horizon}d"] = (
            stock_return - benchmark_return
            if np.isfinite(stock_return) and np.isfinite(benchmark_return)
            else np.nan
        )
    return_available = sum(
        np.isfinite(row[f"return_{horizon}d"])
        and np.isfinite(row[f"relative_return_{horizon}d"])
        for horizon in RETURN_HORIZONS
    )
    row["return_available_horizon_count"] = int(return_available)
    row["return_status"] = (
        "complete" if return_available == len(RETURN_HORIZONS) else "limited"
    )
    if row["return_status"] == "limited":
        limitations.append(
            f"return observations available for {return_available}/{len(RETURN_HORIZONS)} horizons"
        )

    risk_observations = _risk_observations(stock_returns, benchmark_returns)
    row.update(risk_observations)
    if risk_observations["risk_status"] == "limited":
        limitations.append(
            "risk observations are limited: "
            f"{risk_observations['risk_observation_count_60d']}/60 exact stock-benchmark return pairs, "
            f"{risk_observations['downside_risk_observation_count_60d']} downside pairs"
        )
    row["realized_volatility_20d_annualized"] = _realized_volatility(stock_returns)
    row["atr_ratio_20d"] = _atr_ratio(stock)
    for window in PRICE_LOCATION_WINDOWS:
        row[f"price_location_{window}d"] = _price_location(closes, window)
    price_required = (
        "realized_volatility_20d_annualized",
        "atr_ratio_20d",
        "price_location_60d",
        "price_location_82d",
    )
    row["price_observation_status"] = (
        "complete"
        if all(np.isfinite(row[field]) for field in price_required)
        else "limited"
    )
    if row["price_observation_status"] == "limited":
        limitations.append("volatility, ATR, or price-location history is incomplete")

    amount_observations = _amount_observations(amounts)
    row.update(amount_observations)
    if amount_observations["amount_status"] == "limited":
        limitations.append(
            "20-session amount observations are incomplete: "
            f"{amount_observations['amount_observation_count_20d']}/20"
        )
    direction_observations = _up_down_amount_observations(amounts, stock_returns)
    row.update(direction_observations)
    if direction_observations["amount_direction_status"] == "limited":
        limitations.append(
            "amount-direction observations are limited: "
            f"{direction_observations['amount_direction_observation_count_60d']}/60 exact sessions"
        )
    high_volume_observations = _high_volume_observations(stock, stock_returns)
    row.update(high_volume_observations)
    if high_volume_observations["high_volume_status"] == "limited":
        limitations.append(
            "high-volume observations are limited: "
            f"{high_volume_observations['high_volume_amount_observation_count_60d']}/60 amounts, "
            f"{high_volume_observations['high_volume_selected_count_60d']} selected"
        )
    countertrend_observations = _countertrend_observations(
        stock_returns, benchmark_returns
    )
    row.update(countertrend_observations)
    if countertrend_observations["countertrend_status"] == "limited":
        limitations.append(
            "countertrend observations are limited by incomplete stock or benchmark returns: "
            f"{countertrend_observations['countertrend_observation_count_60d']}/60"
        )

    limit_observations, limit_complete = _limit_observations(
        code, stock, limits, session_index
    )
    row.update(limit_observations)
    if not limit_complete:
        limitations.append("recent stock-limit facts are incomplete")
    if limit_observations["post_limit_behavior_status"] == "limited":
        limitations.append("post-limit next-session facts are incomplete")

    valuation_observations, valuation_complete = _valuation_observations(
        code, valuations, session_index, analysis_date
    )
    row.update(valuation_observations)
    if not valuation_complete:
        limitations.append(
            "250-session valuation observations are incomplete: "
            f"{valuation_observations['valuation_observations_250d']}/250"
        )
    if valuation_observations["pe_percentile_status"] == "unavailable_non_positive":
        limitations.append("PE percentiles are unavailable because the current valuation has a non-positive PE")

    history_complete = (
        len(trailing_price) >= 82 and bool(_finite_positive(trailing_price).all())
    )
    feature_statuses = (
        row["return_status"],
        row["risk_status"],
        row["price_observation_status"],
        row["amount_status"],
        row["amount_direction_status"],
        row["high_volume_status"],
        row["countertrend_status"],
        row["limit_data_status"],
        row["valuation_data_status"],
    )
    post_limit_usable = row["post_limit_behavior_status"] != "limited"
    row["coverage_status"] = (
        "complete_with_declared_gaps"
        if current_core_valid
        and benchmark_current_valid
        and history_complete
        and limit_complete
        and post_limit_usable
        and all(status == "complete" for status in feature_statuses)
        else "limited"
    )
    row["limitation_notes"] = "; ".join(limitations)
    return row


def _prepare_frame(
    frame: pd.DataFrame,
    *,
    required: set[str],
    key: tuple[str, ...],
    numeric: tuple[str, ...],
    label: str,
    analysis_date: date,
) -> pd.DataFrame:
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"{label} lacks required fields: {', '.join(missing)}")
    prepared = frame.copy()
    prepared["trade_date"] = pd.to_datetime(
        prepared["trade_date"], errors="raise"
    ).dt.date
    prepared = prepared[prepared["trade_date"] <= analysis_date].copy()
    if prepared.duplicated(list(key)).any():
        raise ValueError(f"duplicate business fact in {label} input")
    for column in numeric:
        prepared[column] = pd.to_numeric(prepared[column], errors="coerce")
    return prepared


def _exact_return(series: pd.Series, horizon: int, analysis_date: date) -> float:
    """Return the exact h-session endpoint return without dropping gaps."""

    if len(series) <= horizon or series.index[-1] != analysis_date:
        return np.nan
    current = series.iloc[-1]
    base = series.iloc[-horizon - 1]
    if not _finite_positive_scalar(current) or not _finite_positive_scalar(base):
        return np.nan
    return float(current / base - 1.0)


def _risk_observations(
    stock_returns: pd.Series, benchmark_returns: pd.Series
) -> dict[str, object]:
    """Compute 60-session beta, downside-day beta and correlation."""

    paired = pd.concat(
        [stock_returns.rename("stock"), benchmark_returns.rename("benchmark")], axis=1
    ).tail(RISK_WINDOW)
    valid = np.isfinite(paired["stock"]) & np.isfinite(paired["benchmark"])
    observation_count = int(valid.sum())
    complete = len(paired) == RISK_WINDOW and observation_count == RISK_WINDOW
    usable = paired[valid]
    downside = usable[usable["benchmark"] < 0]
    downside_count = int(len(downside))
    variance = float(usable["benchmark"].var(ddof=1)) if len(usable) >= 2 else np.nan
    beta = (
        float(usable["stock"].cov(usable["benchmark"]) / variance)
        if complete and variance > 0
        else np.nan
    )
    stock_deviation = float(usable["stock"].std(ddof=1)) if len(usable) >= 2 else np.nan
    benchmark_deviation = (
        float(usable["benchmark"].std(ddof=1)) if len(usable) >= 2 else np.nan
    )
    correlation = (
        float(usable["stock"].corr(usable["benchmark"]))
        if complete and stock_deviation > 0 and benchmark_deviation > 0
        else np.nan
    )
    downside_variance = float(downside["benchmark"].var(ddof=1))
    downside_beta = (
        float(downside["stock"].cov(downside["benchmark"]) / downside_variance)
        if complete and downside_count >= 2 and downside_variance > 0
        else np.nan
    )
    status = (
        "complete"
        if complete
        and np.isfinite(beta)
        and np.isfinite(downside_beta)
        and np.isfinite(correlation)
        else "limited"
    )
    return {
        "beta_60d": beta,
        "downside_beta_60d": downside_beta,
        "benchmark_correlation_60d": correlation,
        "risk_observation_count_60d": observation_count,
        "downside_risk_observation_count_60d": downside_count,
        "risk_status": status,
    }


def _realized_volatility(stock_returns: pd.Series) -> float:
    """Annualize the sample standard deviation of 20 exact daily returns."""

    sample = stock_returns.tail(VOLATILITY_WINDOW)
    if len(sample) != VOLATILITY_WINDOW or not np.isfinite(sample).all():
        return np.nan
    return float(sample.std(ddof=1) * sqrt(252.0))


def _atr_ratio(stock: pd.DataFrame) -> float:
    """Return 20-session average true range divided by current close."""

    previous_close = stock["close"].shift(1)
    true_range = pd.concat(
        [
            stock["high"] - stock["low"],
            (stock["high"] - previous_close).abs(),
            (stock["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1, skipna=False)
    sample = true_range.tail(VOLATILITY_WINDOW)
    current_close = stock["close"].iloc[-1]
    if (
        len(sample) != VOLATILITY_WINDOW
        or not np.isfinite(sample).all()
        or not _finite_positive_scalar(current_close)
    ):
        return np.nan
    return float(sample.mean() / current_close)


def _price_location(closes: pd.Series, window: int) -> float:
    """Locate the current close within the exact trailing close range."""

    sample = closes.tail(window)
    if len(sample) != window or not _finite_positive(sample).all():
        return np.nan
    low = float(sample.min())
    high = float(sample.max())
    if high == low:
        return np.nan
    return float((sample.iloc[-1] - low) / (high - low))


def _amount_observations(amounts: pd.Series) -> dict[str, object]:
    """Return exact 20-session average amount and current/average ratio."""

    sample = amounts.tail(20)
    current = amounts.iloc[-1]
    valid_count = int(_finite_nonnegative(sample).sum())
    complete = len(sample) == 20 and valid_count == 20
    average = float(sample.mean()) if complete else np.nan
    ratio = (
        float(current / average)
        if complete
        and average > 0
        and _finite_nonnegative_scalar(current)
        else np.nan
    )
    return {
        "average_amount_20d": average,
        "current_amount_ratio_20d": ratio,
        "amount_observation_count_20d": valid_count,
        "amount_status": (
            "complete" if np.isfinite(average) and np.isfinite(ratio) else "limited"
        ),
    }


def _up_down_amount_observations(
    amounts: pd.Series, returns: pd.Series
) -> dict[str, object]:
    """Compare mean amount on observed up days with observed down days."""

    sample = pd.concat(
        [amounts.rename("amount"), returns.rename("return")], axis=1
    ).tail(60)
    valid = _finite_nonnegative(sample["amount"]) & np.isfinite(sample["return"])
    sample = sample[valid]
    up = sample.loc[sample["return"] > 0, "amount"]
    down = sample.loc[sample["return"] < 0, "amount"]
    ratio = (
        float(up.mean() / down.mean())
        if not up.empty and not down.empty and float(down.mean()) > 0
        else np.nan
    )
    observation_count = int(len(sample))
    return {
        "up_down_amount_ratio_60d": ratio,
        "amount_direction_observation_count_60d": observation_count,
        "amount_up_observation_count_60d": int(len(up)),
        "amount_down_observation_count_60d": int(len(down)),
        "amount_direction_status": (
            "complete"
            if observation_count == 60 and np.isfinite(ratio)
            else "limited"
        ),
    }


def _daily_efficiency(stock: pd.DataFrame) -> pd.DataFrame:
    """Calculate descriptive close-location and body-efficiency observations."""

    price_range = stock["high"] - stock["low"]
    valid = np.isfinite(price_range) & (price_range > 0)
    close_location = pd.Series(np.nan, index=stock.index, dtype=float)
    body_efficiency = pd.Series(np.nan, index=stock.index, dtype=float)
    close_location.loc[valid] = (
        (stock.loc[valid, "close"] - stock.loc[valid, "low"]) / price_range.loc[valid]
    )
    body_efficiency.loc[valid] = (
        (stock.loc[valid, "close"] - stock.loc[valid, "open"]).abs()
        / price_range.loc[valid]
    )
    return pd.DataFrame(
        {"close_location": close_location, "body_efficiency": body_efficiency}
    )


def _high_volume_observations(
    stock: pd.DataFrame, stock_returns: pd.Series
) -> dict[str, object]:
    """Summarize top-20-percent amount days without hiding the minimum."""

    sample = stock.tail(HIGH_VOLUME_WINDOW).copy()
    valid_amount = sample.loc[_finite_nonnegative(sample["amount"]), "amount"]
    empty = {
        "high_volume_definition": "amount >= trailing-60-session 80th percentile; all ties included",
        "high_volume_amount_observation_count_60d": int(len(valid_amount)),
        "high_volume_selected_count_60d": 0,
        "high_volume_status": "limited",
        "high_volume_up_count_60d": np.nan,
        "high_volume_down_count_60d": np.nan,
        "high_volume_close_location_median_60d": np.nan,
        "high_volume_body_efficiency_median_60d": np.nan,
        "high_volume_body_efficiency_min_60d": np.nan,
        "high_volume_body_efficiency_min_date_60d": pd.NaT,
    }
    if len(valid_amount) < 5:
        return empty
    threshold = float(valid_amount.quantile(HIGH_VOLUME_QUANTILE))
    selected = sample[_finite_nonnegative(sample["amount"]) & (sample["amount"] >= threshold)]
    if selected.empty:
        return empty
    efficiencies = _daily_efficiency(sample).loc[selected.index]
    selected_returns = stock_returns.reindex(selected.index)
    body = efficiencies["body_efficiency"].dropna()
    minimum_date = body.idxmin() if not body.empty else pd.NaT
    directions_complete = bool(np.isfinite(selected_returns).all())
    selected_complete = bool(
        len(valid_amount) == HIGH_VOLUME_WINDOW
        and directions_complete
        and np.isfinite(efficiencies["close_location"]).all()
        and np.isfinite(efficiencies["body_efficiency"]).all()
    )
    return {
        "high_volume_definition": empty["high_volume_definition"],
        "high_volume_amount_observation_count_60d": int(len(valid_amount)),
        "high_volume_selected_count_60d": int(len(selected)),
        "high_volume_status": "complete" if selected_complete else "limited",
        "high_volume_up_count_60d": (
            int((selected_returns > 0).sum()) if directions_complete else np.nan
        ),
        "high_volume_down_count_60d": (
            int((selected_returns < 0).sum()) if directions_complete else np.nan
        ),
        "high_volume_close_location_median_60d": _median_or_nan(
            efficiencies["close_location"]
        ),
        "high_volume_body_efficiency_median_60d": _median_or_nan(body),
        "high_volume_body_efficiency_min_60d": (
            float(body.min()) if not body.empty else np.nan
        ),
        "high_volume_body_efficiency_min_date_60d": minimum_date,
    }


def _countertrend_observations(
    stock_returns: pd.Series, benchmark_returns: pd.Series
) -> dict[str, object]:
    """Count relative-strength days and apply a 20-session half-life."""

    paired = pd.concat(
        [stock_returns.rename("stock"), benchmark_returns.rename("benchmark")], axis=1
    ).tail(COUNTERTREND_WINDOW)
    valid_pairs = np.isfinite(paired["stock"]) & np.isfinite(paired["benchmark"])
    observation_count = int(valid_pairs.sum())
    expected_pairs = min(COUNTERTREND_WINDOW, max(len(stock_returns) - 1, 0))
    complete = expected_pairs == COUNTERTREND_WINDOW and observation_count == COUNTERTREND_WINDOW
    if expected_pairs == 0 or observation_count != expected_pairs:
        return {
            "countertrend_up_count_60d": np.nan,
            "countertrend_up_recency_weighted_60d": np.nan,
            "countertrend_observation_count_60d": observation_count,
            "countertrend_status": "limited",
        }
    signal = (paired["benchmark"] < COUNTERTREND_MARKET_THRESHOLD) & (
        paired["stock"] > 0
    )
    ages = np.arange(len(paired) - 1, -1, -1, dtype=float)
    weights = np.power(0.5, ages / COUNTERTREND_HALF_LIFE)
    return {
        "countertrend_up_count_60d": int((signal & valid_pairs).sum()),
        "countertrend_up_recency_weighted_60d": float(
            weights[(signal & valid_pairs).to_numpy()].sum()
        ),
        "countertrend_observation_count_60d": observation_count,
        "countertrend_status": "complete" if complete else "limited",
    }


def _limit_observations(
    code: str,
    stock: pd.DataFrame,
    limits: pd.DataFrame,
    session_index: pd.Index,
) -> tuple[dict[str, object], bool]:
    """Use supplied daily limit prices for hits and next-session behavior."""

    recent_dates = list(session_index[-LIMIT_WINDOW:])
    code_limits = (
        limits[limits["ts_code"].astype(str) == code]
        .set_index("trade_date")
        .reindex(recent_dates)
    )
    recent_stock = stock.reindex(recent_dates)
    valid = (
        _finite_positive(code_limits["up_limit"])
        & _finite_positive(code_limits["down_limit"])
        & _finite_positive(recent_stock["close"])
    )
    complete = len(recent_dates) > 0 and bool(valid.all())
    empty = {
        "limit_data_status": "limited",
        "post_limit_behavior_status": "limited",
        "limit_observation_count_5d": int(valid.sum()),
        "recent_limit_up_count_5d": np.nan,
        "recent_limit_down_count_5d": np.nan,
        "latest_limit_up_date": pd.NaT,
        "post_limit_next_return": np.nan,
        "post_limit_next_amount_ratio": np.nan,
        "post_limit_next_high_to_close_pullback": np.nan,
    }
    if not complete:
        return empty, False
    up_hits = recent_stock["close"] >= code_limits["up_limit"] * (1.0 - 1e-8)
    down_hits = recent_stock["close"] <= code_limits["down_limit"] * (1.0 + 1e-8)
    hit_dates = list(code_limits.index[up_hits])
    result = dict(empty)
    result.update(
        {
            "limit_data_status": "complete",
            "recent_limit_up_count_5d": int(up_hits.sum()),
            "recent_limit_down_count_5d": int(down_hits.sum()),
        }
    )
    if not hit_dates:
        result["post_limit_behavior_status"] = "not_applicable"
        return result, True
    latest = hit_dates[-1]
    result["latest_limit_up_date"] = latest
    latest_position = list(session_index).index(latest)
    if latest_position >= len(session_index) - 1:
        result["post_limit_behavior_status"] = "pending"
        return result, True
    next_date = session_index[latest_position + 1]
    hit_row = stock.loc[latest]
    next_row = stock.loc[next_date]
    behavior_complete = bool(
        _finite_positive_scalar(hit_row["close"])
        and _finite_positive_scalar(hit_row["amount"])
        and _finite_positive_scalar(next_row["close"])
        and _finite_nonnegative_scalar(next_row["amount"])
        and _finite_positive_scalar(next_row["high"])
    )
    result["post_limit_behavior_status"] = (
        "complete" if behavior_complete else "limited"
    )
    if _finite_positive_scalar(hit_row["close"]) and _finite_positive_scalar(
        next_row["close"]
    ):
        result["post_limit_next_return"] = float(
            next_row["close"] / hit_row["close"] - 1.0
        )
    if _finite_positive_scalar(hit_row["amount"]) and _finite_nonnegative_scalar(
        next_row["amount"]
    ):
        result["post_limit_next_amount_ratio"] = float(
            next_row["amount"] / hit_row["amount"]
        )
    if _finite_positive_scalar(next_row["high"]) and _finite_positive_scalar(
        next_row["close"]
    ):
        result["post_limit_next_high_to_close_pullback"] = float(
            next_row["high"] / next_row["close"] - 1.0
        )
    return result, True


def _valuation_observations(
    code: str,
    valuations: pd.DataFrame,
    session_index: pd.Index,
    analysis_date: date,
) -> tuple[dict[str, object], bool]:
    """Calculate 250-session and available-five-year valuation percentiles."""

    code_values = valuations[valuations["ts_code"].astype(str) == code].sort_values(
        "trade_date"
    )
    current_rows = code_values[code_values["trade_date"] == analysis_date]
    current_pe = float(current_rows.iloc[0]["pe_ttm"]) if not current_rows.empty else np.nan
    current_pb = float(current_rows.iloc[0]["pb"]) if not current_rows.empty else np.nan
    current_complete = bool(np.isfinite(current_pe) and np.isfinite(current_pb))
    five_year_start = (pd.Timestamp(analysis_date) - pd.DateOffset(years=5)).date()
    available_five_year = code_values[code_values["trade_date"] >= five_year_start]
    canonical_dates = list(session_index[-VALUATION_WINDOW:])
    trailing_250 = code_values.set_index("trade_date").reindex(canonical_dates)
    raw_250_valid = np.isfinite(trailing_250["pe_ttm"]) & np.isfinite(
        trailing_250["pb"]
    )
    raw_5y_valid = np.isfinite(available_five_year["pe_ttm"]) & np.isfinite(
        available_five_year["pb"]
    )
    valuation_observations_250d = int(raw_250_valid.sum())
    valuation_observations_5y = int(raw_5y_valid.sum())
    valuation_complete = bool(
        current_complete
        and len(canonical_dates) == VALUATION_WINDOW
        and valuation_observations_250d == VALUATION_WINDOW
    )
    positive_pe_250 = trailing_250.loc[trailing_250["pe_ttm"] > 0, "pe_ttm"]
    positive_pe_5y = available_five_year.loc[
        available_five_year["pe_ttm"] > 0, "pe_ttm"
    ]
    positive_pb_250 = trailing_250.loc[trailing_250["pb"] > 0, "pb"]
    positive_pb_5y = available_five_year.loc[
        available_five_year["pb"] > 0, "pb"
    ]
    pe_status = (
        "unavailable"
        if not np.isfinite(current_pe)
        else "unavailable_non_positive"
        if current_pe <= 0
        else "available"
    )
    return {
        "valuation_data_status": "complete" if valuation_complete else "limited",
        "pe_ttm": current_pe,
        "pb": current_pb,
        "pe_ttm_percentile_250d": _percentile_or_nan(
            current_pe, positive_pe_250, positive_required=True
        ),
        "pb_percentile_250d": _percentile_or_nan(
            current_pb, positive_pb_250, positive_required=True
        ),
        "pe_ttm_percentile_5y_available": _percentile_or_nan(
            current_pe, positive_pe_5y, positive_required=True
        ),
        "pb_percentile_5y_available": _percentile_or_nan(
            current_pb, positive_pb_5y, positive_required=True
        ),
        "valuation_observations_250d": valuation_observations_250d,
        "valuation_observations_5y": valuation_observations_5y,
        "pe_percentile_status": pe_status,
    }, valuation_complete


def _percentile_or_nan(
    current: float, history: pd.Series, *, positive_required: bool
) -> float:
    if not np.isfinite(current) or (positive_required and current <= 0) or history.empty:
        return np.nan
    values = pd.to_numeric(history, errors="coerce")
    values = values[np.isfinite(values)]
    if values.empty:
        return np.nan
    return float((values <= current).mean())


def _valid_ohlc_amount(row: pd.Series) -> bool:
    ohlc = pd.to_numeric(row[["open", "high", "low", "close"]], errors="coerce")
    return bool(
        np.isfinite(ohlc).all()
        and (ohlc > 0).all()
        and ohlc["high"] >= ohlc["low"]
        and _finite_nonnegative_scalar(row["amount"])
    )


def _median_or_nan(values: pd.Series) -> float:
    finite = pd.to_numeric(values, errors="coerce")
    finite = finite[np.isfinite(finite)]
    return float(finite.median()) if not finite.empty else np.nan


def _finite_positive(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    return np.isfinite(numeric) & (numeric > 0)


def _finite_nonnegative(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    return np.isfinite(numeric) & (numeric >= 0)


def _finite_positive_scalar(value: object) -> bool:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return False
    return bool(np.isfinite(numeric) and numeric > 0)


def _finite_nonnegative_scalar(value: object) -> bool:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return False
    return bool(np.isfinite(numeric) and numeric >= 0)


def _as_date(value: date) -> date:
    if isinstance(value, date):
        return value
    return pd.Timestamp(value).date()


__all__ = ["STOCK_CONTEXT_FORMULA_VERSION", "compute_stock_context_features"]
