"""Deterministic, decision-free observations of the broad A-share market.

The caller is responsible for supplying facts that are already bounded by the
research ``as_of`` cutoff.  This module still removes dates after the requested
analysis date so an accidental future row cannot affect a snapshot.
"""

from __future__ import annotations

from datetime import date
from math import sqrt

import numpy as np
import pandas as pd


MARKET_CONTEXT_FORMULA_VERSION = "market-context-v1"
BROAD_INDEX_CODES = (
    "000001.SH",
    "399001.SZ",
    "399006.SZ",
    "000688.SH",
    "000300.SH",
    "000905.SH",
    "000852.SH",
    "899050.BJ",
)
RETURN_HORIZONS = (1, 3, 5, 20)
LONG_WINDOWS = (20, 60)
MINIMUM_CURRENT_COVERAGE = 0.95
NEAR_LIMIT_DISTANCE = 0.02


def compute_market_context_features(
    equity_daily: pd.DataFrame,
    index_daily: pd.DataFrame,
    stock_limits: pd.DataFrame,
    *,
    analysis_date: date,
    expected_current_rows: int,
) -> pd.DataFrame:
    """Return one row of observable market facts for ``analysis_date``.

    Returns use the close ``h`` market sessions before the current close.  The
    equal-weight return, median and breadth therefore use only securities with
    both endpoints.  Turnover ratios divide current total amount by the trailing
    5/20-session average including the current session.  Realized volatility is
    the sample standard deviation of the last 20 equal-weight daily returns,
    annualized with :math:`sqrt(252)`.

    Actual limit-price facts are required to count limit hits.  A near hit is
    exclusive of an actual hit and lies within 2% of the supplied daily limit.
    The function describes price and turnover only; it does not label a market
    regime, infer a trader identity, or recommend an action.
    """

    if (
        not isinstance(expected_current_rows, (int, np.integer))
        or expected_current_rows <= 0
    ):
        raise ValueError("expected_current_rows must be a positive integer")
    analysis_date = _as_date(analysis_date)
    equity = _prepare_frame(
        equity_daily,
        required={"trade_date", "ts_code", "close", "amount"},
        key=("trade_date", "ts_code"),
        analysis_date=analysis_date,
        label="equity daily",
        numeric=("close", "amount"),
    )
    indexes = _prepare_frame(
        index_daily,
        required={"trade_date", "index_code", "close"},
        key=("trade_date", "index_code"),
        analysis_date=analysis_date,
        label="index daily",
        numeric=("close",),
    )
    limits = _prepare_frame(
        stock_limits,
        required={"trade_date", "ts_code", "up_limit", "down_limit"},
        key=("trade_date", "ts_code"),
        analysis_date=analysis_date,
        label="stock limit",
        numeric=("up_limit", "down_limit"),
    )

    current = equity[equity["trade_date"] == analysis_date].copy()
    current_core_valid = current[
        _finite_positive(current["close"]) & _finite_nonnegative(current["amount"])
    ].copy()
    observed_current_rows = int(current_core_valid["ts_code"].nunique())
    coverage_ratio = observed_current_rows / int(expected_current_rows)
    equity_coverage_complete = coverage_ratio >= MINIMUM_CURRENT_COVERAGE
    limitation_notes: list[str] = []
    if not equity_coverage_complete:
        limitation_notes.append(
            f"current equity coverage {coverage_ratio:.2%} is below required 95%"
        )

    market_dates = sorted(equity["trade_date"].unique())
    eligible_codes = set(current_core_valid["ts_code"].astype(str))
    price_equity = equity[equity["ts_code"].astype(str).isin(eligible_codes)].copy()
    price_equity.loc[~_finite_positive(price_equity["close"]), "close"] = np.nan
    pivot = _close_pivot(price_equity) if observed_current_rows else pd.DataFrame()
    row: dict[str, object] = {
        "analysis_date": analysis_date,
        "formula_version": MARKET_CONTEXT_FORMULA_VERSION,
        "observed_current_rows": observed_current_rows,
        "expected_current_rows": int(expected_current_rows),
        "coverage_ratio": float(coverage_ratio),
        "interpretation_limit": "observable market facts only",
    }

    for horizon in RETURN_HORIZONS:
        returns = _cross_section_returns(pivot, horizon)
        row[f"equal_weight_return_{horizon}d"] = _mean_or_nan(returns)
        row[f"median_return_{horizon}d"] = _median_or_nan(returns)
        row[f"breadth_{horizon}d"] = _positive_share(returns)

    current_indexes = indexes[indexes["trade_date"] == analysis_date].copy()
    current_indexes = current_indexes[
        current_indexes["index_code"].astype(str).isin(BROAD_INDEX_CODES)
        & _finite_positive(current_indexes["close"])
    ]
    index_current_count = int(current_indexes["index_code"].nunique())
    index_coverage_ratio = index_current_count / len(BROAD_INDEX_CODES)
    index_coverage_complete = index_current_count == len(BROAD_INDEX_CODES)
    row["broad_index_current_count"] = index_current_count
    row["broad_index_current_coverage_ratio"] = float(index_coverage_ratio)
    if not index_coverage_complete:
        limitation_notes.append(
            "broad index current coverage "
            f"{index_current_count}/{len(BROAD_INDEX_CODES)} is incomplete"
        )

    for code in BROAD_INDEX_CODES:
        code_rows = indexes[indexes["index_code"].astype(str) == code].sort_values(
            "trade_date"
        )
        code_series = (
            code_rows.set_index("trade_date")["close"].reindex(market_dates)
            if market_dates
            else pd.Series(dtype=float)
        )
        for horizon in RETURN_HORIZONS:
            row[f"index_{_code_slug(code)}_return_{horizon}d"] = _dated_series_return(
                code_series, horizon, analysis_date
            )

    turnover_by_date = _strict_turnover_by_date(equity)
    current_turnover = (
        float(turnover_by_date.loc[analysis_date])
        if equity_coverage_complete
        and analysis_date in turnover_by_date.index
        and pd.notna(turnover_by_date.loc[analysis_date])
        else np.nan
    )
    row["market_turnover_amount"] = current_turnover
    for window in (5, 20):
        row[f"turnover_ratio_{window}d"] = _trailing_ratio(
            turnover_by_date, current_turnover, window
        )

    for window in LONG_WINDOWS:
        row[f"above_ma_{window}d_share"] = _above_moving_average_share(pivot, window)
        row[f"new_high_{window}d_share"] = _new_extreme_share(pivot, window, "high")
        row[f"new_low_{window}d_share"] = _new_extreme_share(pivot, window, "low")

    one_day_returns = _cross_section_returns(pivot, 1)
    row["return_dispersion_1d"] = (
        float(one_day_returns.std(ddof=0)) if not one_day_returns.empty else np.nan
    )
    row["realized_volatility_20d_annualized"] = _realized_market_volatility(pivot)
    limit_observations, limit_coverage_complete = _limit_observations(
        current_core_valid,
        limits,
        analysis_date,
        expected_current_rows=int(expected_current_rows),
    )
    row.update(limit_observations)
    if not limit_coverage_complete:
        limit_ratio = limit_observations["limit_price_coverage_ratio"]
        limitation_notes.append(
            f"stock limit coverage {limit_ratio:.2%} is below required 95%"
            if pd.notna(limit_ratio)
            else "stock limit coverage is unavailable"
        )
    row["coverage_status"] = (
        "complete"
        if equity_coverage_complete
        and index_coverage_complete
        and limit_coverage_complete
        else "limited"
    )
    row["limitation_notes"] = "; ".join(limitation_notes)
    return pd.DataFrame([row])


def _prepare_frame(
    frame: pd.DataFrame,
    *,
    required: set[str],
    key: tuple[str, ...],
    analysis_date: date,
    label: str,
    numeric: tuple[str, ...],
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


def _close_pivot(equity: pd.DataFrame) -> pd.DataFrame:
    return (
        equity.pivot(index="trade_date", columns="ts_code", values="close")
        .sort_index()
        .astype(float)
    )


def _cross_section_returns(pivot: pd.DataFrame, horizon: int) -> pd.Series:
    if pivot.empty or len(pivot) <= horizon:
        return pd.Series(dtype=float)
    returns = pivot.iloc[-1] / pivot.iloc[-horizon - 1] - 1.0
    return returns.replace([np.inf, -np.inf], np.nan).dropna()


def _series_return(series: pd.Series, horizon: int) -> float:
    values = pd.to_numeric(series, errors="coerce")
    if len(values) <= horizon:
        return np.nan
    window = values.iloc[-horizon - 1 :]
    if len(window) != horizon + 1 or not _finite_positive(window).all():
        return np.nan
    return float(window.iloc[-1] / window.iloc[0] - 1.0)


def _dated_series_return(
    series: pd.Series, horizon: int, analysis_date: date
) -> float:
    if series.empty or series.index[-1] != analysis_date:
        return np.nan
    return _series_return(series, horizon)


def _mean_or_nan(values: pd.Series) -> float:
    return float(values.mean()) if not values.empty else np.nan


def _median_or_nan(values: pd.Series) -> float:
    return float(values.median()) if not values.empty else np.nan


def _positive_share(values: pd.Series) -> float:
    return float((values > 0).mean()) if not values.empty else np.nan


def _trailing_ratio(series: pd.Series, current: float, window: int) -> float:
    values = pd.to_numeric(series, errors="coerce")
    if len(values) < window or not np.isfinite(current):
        return np.nan
    trailing = values.tail(window)
    if len(trailing) != window or not _finite_nonnegative(trailing).all():
        return np.nan
    average = float(trailing.mean())
    if average == 0:
        return np.nan
    return float(current / average)


def _eligible_window(pivot: pd.DataFrame, window: int) -> pd.DataFrame:
    if pivot.empty or len(pivot) < window:
        return pd.DataFrame()
    sample = pivot.tail(window)
    eligible = sample.columns[sample.notna().sum(axis=0) == window]
    return sample.loc[:, eligible]


def _above_moving_average_share(pivot: pd.DataFrame, window: int) -> float:
    sample = _eligible_window(pivot, window)
    if sample.empty or len(sample.columns) == 0:
        return np.nan
    return float((sample.iloc[-1] > sample.mean(axis=0)).mean())


def _new_extreme_share(pivot: pd.DataFrame, window: int, extreme: str) -> float:
    sample = _eligible_window(pivot, window)
    if sample.empty or len(sample.columns) == 0:
        return np.nan
    latest = sample.iloc[-1]
    if extreme == "high":
        return float((latest >= sample.max(axis=0)).mean())
    return float((latest <= sample.min(axis=0)).mean())


def _realized_market_volatility(pivot: pd.DataFrame) -> float:
    if pivot.empty:
        return np.nan
    equal_weight_daily = (
        pivot.pct_change(fill_method=None)
        .replace([np.inf, -np.inf], np.nan)
        .mean(axis=1)
        .dropna()
    )
    if len(equal_weight_daily) < 20:
        return np.nan
    return float(equal_weight_daily.tail(20).std(ddof=1) * sqrt(252.0))


def _limit_observations(
    current: pd.DataFrame,
    limits: pd.DataFrame,
    analysis_date: date,
    *,
    expected_current_rows: int,
) -> tuple[dict[str, object], bool]:
    current_limits = limits[limits["trade_date"] == analysis_date]
    merged = current[["ts_code", "close"]].merge(
        current_limits[["ts_code", "up_limit", "down_limit"]],
        on="ts_code",
        how="inner",
        validate="one_to_one",
    )
    valid = merged[
        _finite_positive(merged["close"])
        & _finite_positive(merged["up_limit"])
        & _finite_positive(merged["down_limit"])
    ].copy()
    observed = int(len(valid))
    market_denominator = expected_current_rows
    limit_coverage_ratio = observed / market_denominator
    coverage_complete = bool(
        pd.notna(limit_coverage_ratio)
        and limit_coverage_ratio >= MINIMUM_CURRENT_COVERAGE
    )
    if not coverage_complete:
        return {
            "limit_observed_count": observed,
            "limit_price_coverage_ratio": limit_coverage_ratio,
            "limit_up_count": np.nan,
            "near_limit_up_count": np.nan,
            "limit_down_count": np.nan,
            "near_limit_down_count": np.nan,
            "limit_up_share": np.nan,
            "near_limit_up_share": np.nan,
            "limit_down_share": np.nan,
            "near_limit_down_share": np.nan,
        }, False

    limit_up = pd.Series(
        np.isclose(valid["close"], valid["up_limit"], rtol=1e-6, atol=1e-8),
        index=valid.index,
    )
    limit_down = pd.Series(
        np.isclose(valid["close"], valid["down_limit"], rtol=1e-6, atol=1e-8),
        index=valid.index,
    )
    near_up = (
        ~limit_up
        & (valid["close"] < valid["up_limit"])
        & (valid["close"] >= valid["up_limit"] * (1.0 - NEAR_LIMIT_DISTANCE))
    )
    near_down = (
        ~limit_down
        & (valid["close"] > valid["down_limit"])
        & (valid["close"] <= valid["down_limit"] * (1.0 + NEAR_LIMIT_DISTANCE))
    )
    counts = {
        "limit_up": int(limit_up.sum()),
        "near_limit_up": int(near_up.sum()),
        "limit_down": int(limit_down.sum()),
        "near_limit_down": int(near_down.sum()),
    }
    output: dict[str, object] = {
        "limit_observed_count": observed,
        "limit_price_coverage_ratio": (
            observed / market_denominator if market_denominator else np.nan
        ),
    }
    for name, count in counts.items():
        output[f"{name}_count"] = count
        output[f"{name}_share"] = (
            count / market_denominator if market_denominator else np.nan
        )
    return output, True


def _strict_turnover_by_date(equity: pd.DataFrame) -> pd.Series:
    totals: dict[date, float] = {}
    for trading_day, group in equity.groupby("trade_date", sort=True):
        amounts = pd.to_numeric(group["amount"], errors="coerce")
        totals[trading_day] = (
            float(amounts.sum()) if _finite_nonnegative(amounts).all() else np.nan
        )
    return pd.Series(totals, dtype=float).sort_index()


def _finite_positive(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    return pd.Series(np.isfinite(numeric) & (numeric > 0), index=values.index)


def _finite_nonnegative(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    return pd.Series(np.isfinite(numeric) & (numeric >= 0), index=values.index)


def _code_slug(code: str) -> str:
    return code.lower().replace(".", "_")


def _as_date(value: date) -> date:
    return pd.Timestamp(value).date()


__all__ = [
    "BROAD_INDEX_CODES",
    "MARKET_CONTEXT_FORMULA_VERSION",
    "compute_market_context_features",
]
