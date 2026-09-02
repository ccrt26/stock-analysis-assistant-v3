"""Small deterministic helpers for the preregistered indicator experiment.

This module evaluates research evidence only.  It does not select securities or
turn model probabilities into production scores, gates, or trading actions.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import date

import numpy as np
import pandas as pd


BASELINE_RETURN_HORIZONS = (1, 3, 5, 10, 20, 60)


def build_baseline_panel(
    equity_daily: pd.DataFrame,
    benchmark_daily: pd.DataFrame,
    *,
    formation_dates: Iterable[date],
) -> pd.DataFrame:
    """Build the frozen existing-price-information comparison surface."""

    equity_required = {
        "trade_date",
        "ts_code",
        "open",
        "high",
        "low",
        "close",
        "adj_factor",
        "amount",
        "up_limit",
    }
    benchmark_required = {"trade_date", "close"}
    missing_equity = sorted(equity_required - set(equity_daily.columns))
    missing_benchmark = sorted(benchmark_required - set(benchmark_daily.columns))
    if missing_equity:
        raise ValueError(f"equity daily lacks required fields: {', '.join(missing_equity)}")
    if missing_benchmark:
        raise ValueError(
            f"benchmark daily lacks required fields: {', '.join(missing_benchmark)}"
        )
    requested_dates = tuple(sorted({_as_date(value) for value in formation_dates}))
    if not requested_dates:
        return pd.DataFrame()
    through = requested_dates[-1]
    equity = equity_daily.copy()
    equity["trade_date"] = pd.to_datetime(equity["trade_date"], errors="raise").dt.date
    equity = equity[equity["trade_date"] <= through].copy()
    if equity.duplicated(["trade_date", "ts_code"]).any():
        raise ValueError("duplicate business fact in equity daily input")
    for field in ("open", "high", "low", "close", "adj_factor", "amount", "up_limit"):
        equity[field] = pd.to_numeric(equity[field], errors="coerce")
    benchmark = benchmark_daily.copy()
    benchmark["trade_date"] = pd.to_datetime(
        benchmark["trade_date"], errors="raise"
    ).dt.date
    benchmark = benchmark[benchmark["trade_date"] <= through].copy()
    if benchmark.duplicated(["trade_date"]).any():
        raise ValueError("duplicate business fact in benchmark daily input")
    benchmark["close"] = pd.to_numeric(benchmark["close"], errors="coerce")
    session_index = pd.Index(
        sorted(set(equity["trade_date"]) | set(benchmark["trade_date"])),
        name="trade_date",
    )
    broad_close = benchmark.set_index("trade_date")["close"].reindex(session_index)
    broad_return = broad_close.pct_change(fill_method=None).replace(
        [np.inf, -np.inf], np.nan
    )
    broad_horizon_returns = {
        horizon: broad_close / broad_close.shift(horizon) - 1.0
        for horizon in BASELINE_RETURN_HORIZONS
    }
    rows: list[dict[str, object]] = []
    for code, values in equity.groupby("ts_code", sort=True):
        observed_dates = set(values["trade_date"].tolist())
        stock = values.set_index("trade_date").reindex(session_index)
        adjustment = stock["adj_factor"].astype(float)
        valid_adjustment = np.isfinite(adjustment) & (adjustment > 0.0)
        adjusted = pd.DataFrame(index=session_index)
        for field in ("open", "high", "low", "close"):
            adjusted[field] = stock[field].astype(float) * adjustment
            adjusted.loc[~valid_adjustment, field] = np.nan
        close = adjusted["close"]
        daily_return = close.pct_change(fill_method=None).replace(
            [np.inf, -np.inf], np.nan
        )
        relative_daily = daily_return - broad_return
        largest_day_observations = _largest_positive_day_observations(
            daily_return,
            broad_return,
        )
        relative_valid = relative_daily.notna().rolling(5, min_periods=5).sum() == 5
        relative_continuity = (relative_daily > 0.0).rolling(5, min_periods=5).mean()
        relative_continuity = relative_continuity.where(relative_valid)
        relative_slope = relative_daily.rolling(5, min_periods=5).apply(
            _relative_path_slope,
            raw=True,
        )
        up_days = (daily_return > 0.0).rolling(5, min_periods=5).sum().where(
            daily_return.notna().rolling(5, min_periods=5).sum() == 5
        )
        price_range = adjusted["high"] - adjusted["low"]
        valid_range = np.isfinite(price_range) & (price_range > 0.0)
        close_position = ((close - adjusted["low"]) / price_range).where(valid_range)
        upper_shadow = (
            (adjusted["high"] - pd.concat([adjusted["open"], close], axis=1).max(axis=1))
            / price_range
        ).where(valid_range)
        fade_day = ((adjusted["high"] > adjusted["open"]) & (close_position < 0.5)).where(
            valid_range
        )
        amount = stock["amount"].astype(float).where(
            np.isfinite(stock["amount"].astype(float)) & (stock["amount"].astype(float) >= 0)
        )
        prior_average_amount = amount.shift(1).rolling(20, min_periods=20).mean()
        amplified = (amount > prior_average_amount).where(
            amount.notna() & prior_average_amount.notna()
        )
        weighted_return = daily_return * amount
        weighted_abs_return = daily_return.abs() * amount
        volume_price_efficiency = weighted_return.rolling(5, min_periods=5).sum() / (
            weighted_abs_return.rolling(5, min_periods=5).sum().replace(0.0, np.nan)
        )
        valid_limit = (
            np.isfinite(stock["up_limit"].astype(float))
            & (stock["up_limit"].astype(float) > 0.0)
            & np.isfinite(stock["close"].astype(float))
            & (stock["close"].astype(float) > 0.0)
        )
        limit_hit = (
            stock["close"].astype(float)
            >= stock["up_limit"].astype(float) * (1.0 - 1e-8)
        ).where(valid_limit)
        positive_return = daily_return.clip(lower=0.0)
        limit_positive_return = positive_return.where(limit_hit == True, 0.0)  # noqa: E712
        limit_contribution = limit_positive_return.rolling(5, min_periods=5).sum() / (
            positive_return.rolling(5, min_periods=5).sum().replace(0.0, np.nan)
        )
        prior_60_high = adjusted["high"].shift(1).rolling(60, min_periods=60).max()
        realized_volatility = daily_return.rolling(20, min_periods=20).std(ddof=1) * np.sqrt(
            252.0
        )
        previous_close = close.shift(1)
        true_range = pd.concat(
            [
                adjusted["high"] - adjusted["low"],
                (adjusted["high"] - previous_close).abs(),
                (adjusted["low"] - previous_close).abs(),
            ],
            axis=1,
        ).max(axis=1, skipna=False)
        atr_ratio = true_range.rolling(20, min_periods=20).mean() / close
        calculated: dict[str, pd.Series] = {}
        for horizon in BASELINE_RETURN_HORIZONS:
            stock_return = close / close.shift(horizon) - 1.0
            calculated[f"return_{horizon}d"] = stock_return
            calculated[f"relative_market_{horizon}d"] = (
                stock_return - broad_horizon_returns[horizon]
            )
        calculated.update(
            {
                "relative_continuity_5d": relative_continuity,
                "relative_strength_slope_5d": relative_slope,
                "up_days_5d": up_days,
                "mean_close_position_5d": close_position.rolling(5, min_periods=5).mean(),
                "upper_shadow_frequency_5d": (upper_shadow >= 0.25)
                .where(upper_shadow.notna())
                .rolling(5, min_periods=5)
                .mean(),
                "fade_frequency_5d": fade_day.rolling(5, min_periods=5).mean(),
                "volume_amplification_days_5d": amplified.rolling(5, min_periods=5).sum(),
                "volume_price_efficiency_5d": volume_price_efficiency,
                "limit_up_return_contribution_5d": limit_contribution,
                "largest_positive_day_contribution_5d": largest_day_observations[
                    "largest_positive_day_contribution_5d"
                ],
                "sessions_since_largest_positive_day_5d": largest_day_observations[
                    "sessions_since_largest_positive_day_5d"
                ],
                "return_ex_largest_positive_day_5d": largest_day_observations[
                    "return_ex_largest_positive_day_5d"
                ],
                "return_after_largest_positive_day_5d": largest_day_observations[
                    "return_after_largest_positive_day_5d"
                ],
                "relative_market_after_largest_positive_day_5d": (
                    largest_day_observations[
                        "relative_market_after_largest_positive_day_5d"
                    ]
                ),
                "breakout_vs_prior60": close / prior_60_high - 1.0,
                "price_location_60d": _rolling_location(close, 60),
                "price_location_82d": _rolling_location(close, 82),
                "realized_volatility_20d_annualized": realized_volatility,
                "atr_ratio_20d": atr_ratio,
                "liquidity_log10_amount": np.log10(amount.where(amount > 0.0)),
                "amount_ratio_last_20d": amount
                / amount.rolling(20, min_periods=20).mean().replace(0.0, np.nan),
                "vol_adjusted_relative_strength_5d": calculated["relative_market_5d"]
                / realized_volatility.replace(0.0, np.nan),
            }
        )
        for formation_date in requested_dates:
            if formation_date not in observed_dates:
                continue
            row: dict[str, object] = {
                "analysis_date": formation_date,
                "ts_code": str(code),
            }
            for field, series in calculated.items():
                value = series.loc[formation_date]
                row[field] = float(value) if np.isfinite(value) else np.nan
            rows.append(row)
    if not rows:
        return pd.DataFrame()
    return (
        pd.DataFrame(rows)
        .sort_values(["analysis_date", "ts_code"])
        .reset_index(drop=True)
    )


def _largest_positive_day_observations(
    daily_return: pd.Series,
    broad_return: pd.Series,
) -> pd.DataFrame:
    """Describe how much of a complete five-session path came from one day."""

    stock_windows = pd.concat(
        [daily_return.shift(offset) for offset in range(4, -1, -1)],
        axis=1,
    ).to_numpy(dtype=float)
    market_windows = pd.concat(
        [broad_return.shift(offset) for offset in range(4, -1, -1)],
        axis=1,
    ).to_numpy(dtype=float)
    complete = np.isfinite(stock_windows).all(axis=1) & np.isfinite(
        market_windows
    ).all(axis=1)
    finite_stock = np.where(np.isfinite(stock_windows), stock_windows, -np.inf)
    largest_positions = 4 - np.argmax(finite_stock[:, ::-1], axis=1)
    row_positions = np.arange(len(daily_return))
    largest_returns = finite_stock[row_positions, largest_positions]
    positive_sums = np.where(stock_windows > 0.0, stock_windows, 0.0).sum(axis=1)
    valid = complete & (largest_returns > 0.0) & (positive_sums > 0.0)

    columns = (
        "largest_positive_day_contribution_5d",
        "sessions_since_largest_positive_day_5d",
        "return_ex_largest_positive_day_5d",
        "return_after_largest_positive_day_5d",
        "relative_market_after_largest_positive_day_5d",
    )
    result = pd.DataFrame(np.nan, index=daily_return.index, columns=columns)
    if not valid.any():
        return result

    result.loc[valid, "largest_positive_day_contribution_5d"] = (
        largest_returns[valid] / positive_sums[valid]
    )
    sessions_after = 4 - largest_positions
    result.loc[valid, "sessions_since_largest_positive_day_5d"] = sessions_after[
        valid
    ].astype(float)

    window_positions = np.arange(5)[None, :]
    largest_masks = window_positions == largest_positions[:, None]
    ex_largest_returns = (
        np.prod(np.where(largest_masks, 1.0, 1.0 + stock_windows), axis=1) - 1.0
    )
    result.loc[valid, "return_ex_largest_positive_day_5d"] = ex_largest_returns[
        valid
    ]

    has_after = valid & (sessions_after > 0)
    after_masks = window_positions > largest_positions[:, None]
    stock_after = (
        np.prod(np.where(after_masks, 1.0 + stock_windows, 1.0), axis=1) - 1.0
    )
    market_after = (
        np.prod(np.where(after_masks, 1.0 + market_windows, 1.0), axis=1) - 1.0
    )
    result.loc[has_after, "return_after_largest_positive_day_5d"] = stock_after[
        has_after
    ]
    result.loc[has_after, "relative_market_after_largest_positive_day_5d"] = (
        stock_after[has_after] - market_after[has_after]
    )
    return result


def build_outcome_panel(
    equity_daily: pd.DataFrame,
    *,
    formation_dates: Iterable[date],
    horizon: int = 20,
    hit_threshold: float = 0.20,
) -> pd.DataFrame:
    """Build action-open D1--D20 labels after formation dates are fixed."""

    required = {
        "trade_date",
        "ts_code",
        "open",
        "high",
        "low",
        "close",
        "adj_factor",
        "amount",
        "volume",
    }
    missing = sorted(required - set(equity_daily.columns))
    if missing:
        raise ValueError(f"equity daily lacks required fields: {', '.join(missing)}")
    requested_dates = tuple(sorted({_as_date(value) for value in formation_dates}))
    if not requested_dates:
        return pd.DataFrame()
    frame = equity_daily.copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="raise").dt.date
    if frame.duplicated(["trade_date", "ts_code"]).any():
        raise ValueError("duplicate business fact in equity daily input")
    for field in ("open", "high", "low", "close", "adj_factor", "amount", "volume"):
        frame[field] = pd.to_numeric(frame[field], errors="coerce")
    session_dates = sorted(frame["trade_date"].unique())
    session_index = pd.Index(session_dates, name="trade_date")
    session_positions = {value: offset for offset, value in enumerate(session_dates)}
    rows: list[dict[str, object]] = []
    for code, values in frame.groupby("ts_code", sort=True):
        observed_dates = set(values["trade_date"].tolist())
        stock = values.set_index("trade_date").reindex(session_index)
        adjustment = stock["adj_factor"].astype(float)
        valid_adjustment = np.isfinite(adjustment) & (adjustment > 0)
        adjusted = pd.DataFrame(index=session_index)
        for field in ("open", "high", "low", "close"):
            adjusted[field] = stock[field].astype(float) * adjustment
            adjusted.loc[~valid_adjustment, field] = np.nan
        for formation_date in requested_dates:
            formation_position = session_positions.get(formation_date)
            if formation_position is None or formation_date not in observed_dates:
                continue
            action_position = formation_position + 1
            end_position = action_position + horizon
            if end_position > len(session_dates):
                continue
            action_date = session_dates[action_position]
            action_row = stock.iloc[action_position]
            entry = adjusted.iloc[action_position]["open"]
            if not (
                _finite_positive(entry)
                and _finite_positive(action_row["amount"])
                and _finite_positive(action_row["volume"])
            ):
                continue
            path = adjusted.iloc[action_position:end_position]
            if len(path) != horizon or not np.isfinite(
                path[["high", "low", "close"]]
            ).all().all():
                continue
            high_returns = path["high"].to_numpy(dtype=float) / float(entry) - 1.0
            low_returns = path["low"].to_numpy(dtype=float) / float(entry) - 1.0
            hit_positions = np.flatnonzero(
                path["high"].to_numpy(dtype=float)
                >= float(entry) * (1.0 + hit_threshold) * (1.0 - 1e-12)
            )
            rows.append(
                {
                    "analysis_date": formation_date,
                    "action_date": action_date,
                    "ts_code": str(code),
                    "entry_adjusted_open": float(entry),
                    "hit_20pct_d20": int(len(hit_positions) > 0),
                    "mfe_20d": float(np.max(high_returns)),
                    "mae_20d": float(np.min(low_returns)),
                    "time_to_hit_20pct": (
                        int(hit_positions[0] + 1) if len(hit_positions) else np.nan
                    ),
                    "return_close_d20": float(path.iloc[-1]["close"] / entry - 1.0),
                }
            )
    if not rows:
        return pd.DataFrame()
    return (
        pd.DataFrame(rows)
        .sort_values(["analysis_date", "ts_code"])
        .reset_index(drop=True)
    )


def cross_sectional_transform(
    frame: pd.DataFrame,
    feature_columns: Sequence[str],
) -> tuple[pd.DataFrame, list[str]]:
    """Winsorize then convert features to date-wise centered percentile ranks."""

    missing = sorted(set(feature_columns) - set(frame.columns))
    if missing:
        raise ValueError(f"missing feature columns: {', '.join(missing)}")
    if "analysis_date" not in frame.columns:
        raise ValueError("analysis_date is required")
    output = pd.DataFrame(index=frame.index)
    output_columns: list[str] = []
    for field in feature_columns:
        numeric = pd.to_numeric(frame[field], errors="coerce")
        transformed = pd.Series(0.0, index=frame.index, dtype=float)
        for _, indices in frame.groupby("analysis_date", sort=False).groups.items():
            values = numeric.loc[indices]
            valid = values[np.isfinite(values)]
            if valid.empty:
                continue
            lower = float(valid.quantile(0.01))
            upper = float(valid.quantile(0.99))
            clipped = valid.clip(lower, upper)
            ranks = clipped.rank(method="average")
            if len(ranks) == 1:
                centered = pd.Series(0.0, index=ranks.index)
            else:
                centered = (ranks - 1.0) / (len(ranks) - 1.0) - 0.5
            transformed.loc[centered.index] = centered.astype(float)
        missing_field = f"{field}__missing"
        output[field] = transformed
        output[missing_field] = (~np.isfinite(numeric)).astype(float)
        output_columns.extend([field, missing_field])
    return output, output_columns


def fit_ridge_logistic(
    features: np.ndarray,
    target: np.ndarray,
    *,
    penalty: float = 1.0,
    max_passes: int = 40,
    tolerance: float = 1e-8,
) -> np.ndarray:
    """Fit fixed-L2 logistic regression using deterministic coordinate Newton."""

    x = np.asarray(features, dtype=float)
    y = np.asarray(target, dtype=float)
    if x.ndim != 2 or y.ndim != 1 or len(x) != len(y):
        raise ValueError("features and target have incompatible shapes")
    if len(y) == 0 or not set(np.unique(y)).issubset({0.0, 1.0}):
        raise ValueError("target must be a non-empty binary vector")
    design = np.column_stack([np.ones(len(x), dtype=float), x])
    coefficients = np.zeros(design.shape[1], dtype=float)
    prevalence = float(np.clip(y.mean(), 1e-6, 1.0 - 1e-6))
    coefficients[0] = float(np.log(prevalence / (1.0 - prevalence)))
    linear = design @ coefficients
    for _ in range(max_passes):
        largest_change = 0.0
        for column in range(design.shape[1]):
            values = design[:, column]
            probability = _sigmoid(linear)
            ridge = 0.0 if column == 0 else penalty
            gradient = float(values @ (probability - y) + ridge * coefficients[column])
            curvature = float(
                (values * values) @ (probability * (1.0 - probability)) + ridge
            )
            if curvature <= 0 or not np.isfinite(curvature):
                continue
            change = -gradient / curvature
            coefficients[column] += change
            linear += change * values
            largest_change = max(largest_change, abs(change))
        if largest_change < tolerance:
            break
    return coefficients


def predict_logistic(features: np.ndarray, coefficients: np.ndarray) -> np.ndarray:
    x = np.asarray(features, dtype=float)
    beta = np.asarray(coefficients, dtype=float)
    if x.ndim != 2 or beta.shape != (x.shape[1] + 1,):
        raise ValueError("features and coefficients have incompatible shapes")
    return _sigmoid(beta[0] + x @ beta[1:])


def binary_auc(target: np.ndarray, probability: np.ndarray) -> float:
    y = np.asarray(target, dtype=float)
    score = np.asarray(probability, dtype=float)
    positive = y == 1.0
    negative = y == 0.0
    positive_count = int(positive.sum())
    negative_count = int(negative.sum())
    if positive_count == 0 or negative_count == 0:
        return np.nan
    ranks = pd.Series(score).rank(method="average").to_numpy(dtype=float)
    return float(
        (ranks[positive].sum() - positive_count * (positive_count + 1) / 2.0)
        / (positive_count * negative_count)
    )


def evaluate_predictions(
    frame: pd.DataFrame,
    *,
    probability_column: str,
    top_count: int = 20,
) -> dict[str, float | int]:
    required = {
        "analysis_date",
        "ts_code",
        "hit_20pct_d20",
        "mfe_20d",
        "mae_20d",
        "time_to_hit_20pct",
        probability_column,
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"evaluation frame lacks: {', '.join(missing)}")
    probability = np.clip(
        pd.to_numeric(frame[probability_column], errors="coerce").to_numpy(dtype=float),
        1e-9,
        1.0 - 1e-9,
    )
    target = pd.to_numeric(frame["hit_20pct_d20"], errors="raise").to_numpy(
        dtype=float
    )
    log_loss = -float(
        np.mean(target * np.log(probability) + (1.0 - target) * np.log(1.0 - probability))
    )
    selected_rows: list[pd.DataFrame] = []
    for _, group in frame.groupby("analysis_date", sort=True):
        selected_rows.append(
            group.sort_values(
                [probability_column, "ts_code"],
                ascending=[False, True],
            ).head(top_count)
        )
    selected = pd.concat(selected_rows, ignore_index=True)
    daily = selected.groupby("analysis_date", sort=True)
    return {
        "observation_count": int(len(frame)),
        "date_count": int(frame["analysis_date"].nunique()),
        "auc": binary_auc(target, probability),
        "log_loss": log_loss,
        "top_count": int(top_count),
        "top_date_equal_hit_rate": float(daily["hit_20pct_d20"].mean().mean()),
        "top_date_equal_mfe": float(daily["mfe_20d"].mean().mean()),
        "top_date_equal_mae": float(daily["mae_20d"].mean().mean()),
        "top_mean_time_to_hit": float(selected["time_to_hit_20pct"].mean()),
    }


def admission_decision(metrics: Mapping[str, float | int]) -> dict[str, object]:
    """Apply all preregistered family-admission thresholds conjunctively."""

    tolerance = 1e-12
    checks = {
        "auc_increment": float(metrics["auc_increment"]) >= 0.01 - tolerance,
        "relative_log_loss_improvement": float(
            metrics["relative_log_loss_improvement"]
        )
        >= 0.01 - tolerance,
        "top_hit_rate_increment": float(metrics["top_hit_rate_increment"])
        >= 0.03 - tolerance,
        "bootstrap_ci_low": float(metrics["bootstrap_ci_low"]) > 0.0,
        "holm_p_value": float(metrics["holm_p_value"]) < 0.05,
        "positive_stability_periods": int(metrics["positive_stability_periods"]) >= 3,
        "top_mae_change": float(metrics["top_mae_change"]) >= -0.02 - tolerance,
        "coverage": float(metrics["coverage"]) >= 0.95 - tolerance,
    }
    failed = [name for name, passed in checks.items() if not passed]
    return {
        "passed": not failed,
        "failed_conditions": failed,
        "condition_results": checks,
    }


def _sigmoid(values: np.ndarray) -> np.ndarray:
    clipped = np.clip(np.asarray(values, dtype=float), -35.0, 35.0)
    return 1.0 / (1.0 + np.exp(-clipped))


def _relative_path_slope(values: np.ndarray) -> float:
    if len(values) != 5 or not np.isfinite(values).all():
        return np.nan
    cumulative = np.cumsum(values)
    x = np.arange(5, dtype=float)
    centered = x - x.mean()
    return float(centered @ cumulative / (centered @ centered))


def _rolling_location(close: pd.Series, window: int) -> pd.Series:
    low = close.rolling(window, min_periods=window).min()
    high = close.rolling(window, min_periods=window).max()
    return (close - low) / (high - low).replace(0.0, np.nan)


def _finite_positive(value: object) -> bool:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return False
    return bool(np.isfinite(numeric) and numeric > 0.0)


def _as_date(value: date) -> date:
    if isinstance(value, date):
        return value
    return pd.Timestamp(value).date()


__all__ = [
    "admission_decision",
    "binary_auc",
    "build_baseline_panel",
    "build_outcome_panel",
    "cross_sectional_transform",
    "evaluate_predictions",
    "fit_ridge_logistic",
    "predict_logistic",
]
