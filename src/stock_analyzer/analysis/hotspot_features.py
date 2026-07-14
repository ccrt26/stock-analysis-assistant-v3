"""Reproducible sector observations built from governed market facts.

The formula intentionally exposes separate price, participation, turnover and
crowding observations.  It does not combine them into a hidden hotness value or
infer who traded.  Membership is evaluated on every market session so today's
constituents are never backfilled into history.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd


HOTSPOT_FORMULA_VERSION = "sector-hotspot-v2"
HORIZONS = (1, 3, 5, 20)
NEW_HIGH_WINDOWS = (20, 60)
MINIMUM_MEMBER_COVERAGE = 0.80
NEAR_LIMIT_DISTANCE = 0.02


def compute_hotspot_features(
    equity_daily: pd.DataFrame,
    catalogs: pd.DataFrame,
    memberships: pd.DataFrame,
    benchmark_daily: pd.DataFrame,
    stock_limits: pd.DataFrame,
    official_daily: pd.DataFrame,
    minute_bars: pd.DataFrame,
    *,
    analysis_date: date,
) -> pd.DataFrame:
    """Return one observation row for every governed industry or theme.

    Horizon returns compound the daily cross-sectional mean/median stock
    returns.  Breadth is the mean daily positive-return share.  Each day's
    cross-section uses the membership effective on that day.  Turnover-share
    change is the current share minus the share exactly 3/5 sessions earlier.
    Missing sessions are never removed to make a window appear complete.
    """

    analysis_date = pd.Timestamp(analysis_date).date()
    equity = _prepare(
        equity_daily,
        {"trade_date", "ts_code", "open", "high", "low", "close", "amount"},
        ("trade_date", "ts_code"),
        ("open", "high", "low", "close", "amount"),
        "equity daily",
        analysis_date,
    )
    catalog = _prepare_catalog(catalogs)
    members = _prepare_memberships(memberships, analysis_date)
    benchmark = _prepare(
        benchmark_daily,
        {"trade_date", "close"},
        ("trade_date",),
        ("close",),
        "benchmark daily",
        analysis_date,
    )
    limits = _prepare(
        stock_limits,
        {"trade_date", "ts_code", "up_limit", "down_limit"},
        ("trade_date", "ts_code"),
        ("up_limit", "down_limit"),
        "stock limit",
        analysis_date,
    )
    official = _prepare(
        official_daily,
        {"trade_date", "index_code", "close"},
        ("trade_date", "index_code"),
        ("close",),
        "official sector daily",
        analysis_date,
    )
    minutes = _prepare_minutes(minute_bars, analysis_date)

    session_dates = sorted(benchmark["trade_date"].unique())
    if not session_dates:
        session_dates = sorted(equity["trade_date"].unique())
    sessions = pd.Index(session_dates, name="trade_date")
    equity_close = equity.pivot(index="trade_date", columns="ts_code", values="close").reindex(sessions)
    equity_returns = equity_close.pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan)
    benchmark_close = benchmark.set_index("trade_date")["close"].reindex(sessions)
    market_amount = _strict_market_amount(equity, sessions)

    rows = [
        _group_row(
            item,
            equity,
            equity_close,
            equity_returns,
            market_amount,
            benchmark_close,
            limits,
            official,
            minutes,
            members,
            sessions,
            analysis_date,
        )
        for item in catalog.to_dict(orient="records")
    ]
    return pd.DataFrame(rows).sort_values(["group_type", "level", "group_code"]).reset_index(drop=True)


def _group_row(
    item: dict[str, object],
    equity: pd.DataFrame,
    equity_close: pd.DataFrame,
    equity_returns: pd.DataFrame,
    market_amount: pd.Series,
    benchmark_close: pd.Series,
    limits: pd.DataFrame,
    official: pd.DataFrame,
    minutes: pd.DataFrame,
    memberships: pd.DataFrame,
    sessions: pd.Index,
    analysis_date: date,
) -> dict[str, object]:
    group_type = str(item["group_type"])
    group_code = str(item["group_code"])
    group_members = memberships[
        (memberships["group_type"].astype(str) == group_type)
        & (memberships["group_code"].astype(str) == group_code)
    ]
    current_codes = _effective_codes(group_members, analysis_date)
    base = {
        "analysis_date": analysis_date,
        "formula_version": HOTSPOT_FORMULA_VERSION,
        "group_type": group_type,
        "group_code": group_code,
        "group_name": item.get("group_name"),
        "level": item.get("level"),
        "official_index_code": item.get("official_index_code"),
        "member_count": len(current_codes),
        "interpretation_limit": "observable sector price, participation and turnover facts only",
    }
    base.update(_blank_observations())
    if not current_codes:
        base.update(
            {
                "observed_member_count": 0,
                "member_coverage_ratio": np.nan,
                "coverage_status": "limited_no_membership",
                "limitation_notes": "the governed catalog has no public constituent membership",
                "intraday_status": "limited",
            }
        )
        return base

    current = equity[equity["trade_date"] == analysis_date]
    current = current[current["ts_code"].astype(str).isin(current_codes)].copy()
    current_valid = current[_valid_ohlc_amount(current)]
    observed = int(current_valid["ts_code"].nunique())
    coverage_ratio = observed / len(current_codes)
    limitations: list[str] = []
    member_complete = coverage_ratio >= MINIMUM_MEMBER_COVERAGE
    if not member_complete:
        limitations.append(f"current member coverage {coverage_ratio:.2%} is below required 80%")

    daily = _daily_group_series(
        group_members, equity, equity_returns, market_amount, sessions
    )
    base["observed_member_count"] = observed
    base["member_coverage_ratio"] = coverage_ratio
    for horizon in HORIZONS:
        mean_return = _compound_exact(daily["equal_weight_return"], horizon)
        median_return = _compound_exact(daily["median_return"], horizon)
        breadth = _mean_exact(daily["breadth"], horizon)
        benchmark_return = _endpoint_return(benchmark_close, horizon, analysis_date)
        base[f"equal_weight_return_{horizon}d"] = mean_return
        base[f"median_return_{horizon}d"] = median_return
        base[f"breadth_{horizon}d"] = breadth
        base[f"relative_return_{horizon}d"] = (
            mean_return - benchmark_return
            if np.isfinite(mean_return) and np.isfinite(benchmark_return)
            else np.nan
        )
        base[f"turnover_share_average_{horizon}d"] = _mean_exact(
            daily["turnover_share"], horizon
        )
    for horizon in (3, 5):
        base[f"turnover_share_change_{horizon}d"] = _exact_change(
            daily["turnover_share"], horizon
        )

    current_returns = equity_returns.loc[analysis_date].reindex(current_codes).dropna()
    base["return_dispersion_1d"] = (
        float(current_returns.std(ddof=0)) if not current_returns.empty else np.nan
    )
    base["top3_positive_contribution_1d"] = _top_positive_contribution(current_returns)
    for window in NEW_HIGH_WINDOWS:
        base[f"new_high_{window}d_share"] = _new_high_share(
            equity_close, current_codes, window
        )

    limit_values, limit_complete = _current_limit_observations(
        current_valid, limits, current_codes, analysis_date
    )
    base.update(limit_values)
    if not limit_complete:
        limitations.append("current stock-limit coverage is below required 80%")

    official_code = item.get("official_index_code")
    if pd.notna(official_code) and str(official_code):
        official_series = (
            official[official["index_code"].astype(str) == str(official_code)]
            .set_index("trade_date")["close"]
            .reindex(sessions)
        )
        for horizon in HORIZONS:
            official_return = _endpoint_return(official_series, horizon, analysis_date)
            base[f"official_index_return_{horizon}d"] = official_return
            bottom_up = base[f"equal_weight_return_{horizon}d"]
            base[f"official_bottom_up_discrepancy_{horizon}d"] = (
                official_return - bottom_up
                if np.isfinite(official_return) and np.isfinite(bottom_up)
                else np.nan
            )

    base.update(_crowding_observations(base, current_valid, daily))
    minute_values = _minute_observations(minutes, current_codes, analysis_date)
    base.update(minute_values)
    if minute_values["intraday_status"] == "limited":
        limitations.append("intraday path is unavailable or covers fewer than 80% of members")

    core_horizons = all(
        np.isfinite(base[f"equal_weight_return_{horizon}d"])
        for horizon in HORIZONS
    )
    if not core_horizons:
        limitations.append("one or more 1/3/5/20-session sector windows are incomplete")
    base["coverage_status"] = (
        "complete_with_declared_gaps"
        if member_complete and limit_complete and core_horizons
        else "limited"
    )
    base["limitation_notes"] = "; ".join(limitations)
    return base


def _daily_group_series(
    group_members: pd.DataFrame,
    equity: pd.DataFrame,
    equity_returns: pd.DataFrame,
    market_amount: pd.Series,
    sessions: pd.Index,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for trading_day in sessions:
        codes = _effective_codes(group_members, trading_day)
        returns = equity_returns.loc[trading_day].reindex(codes) if codes else pd.Series(dtype=float)
        valid_returns = returns[np.isfinite(returns)]
        breadth = float((valid_returns > 0).mean()) if not valid_returns.empty else np.nan
        mean_return = float(valid_returns.mean()) if not valid_returns.empty else np.nan
        median_return = float(valid_returns.median()) if not valid_returns.empty else np.nan
        day_rows = equity[
            (equity["trade_date"] == trading_day)
            & equity["ts_code"].astype(str).isin(codes)
        ]
        valid_amounts = pd.to_numeric(day_rows["amount"], errors="coerce")
        group_amount = (
            float(valid_amounts.sum())
            if codes
            and len(day_rows) == len(codes)
            and np.isfinite(valid_amounts).all()
            and (valid_amounts >= 0).all()
            else np.nan
        )
        total = market_amount.get(trading_day, np.nan)
        turnover_share = (
            group_amount / total
            if np.isfinite(group_amount) and np.isfinite(total) and total > 0
            else np.nan
        )
        rows.append(
            {
                "trade_date": trading_day,
                "equal_weight_return": mean_return,
                "median_return": median_return,
                "breadth": breadth,
                "turnover_share": turnover_share,
            }
        )
    return pd.DataFrame(rows).set_index("trade_date")


def _current_limit_observations(
    current: pd.DataFrame,
    limits: pd.DataFrame,
    codes: list[str],
    analysis_date: date,
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
    ]
    coverage = len(valid) / len(codes)
    empty = {
        "limit_observed_member_count": len(valid),
        "limit_coverage_ratio": coverage,
        "limit_up_count": np.nan,
        "near_limit_up_count": np.nan,
        "limit_up_share": np.nan,
        "near_limit_up_share": np.nan,
    }
    if coverage < MINIMUM_MEMBER_COVERAGE:
        return empty, False
    up = np.isclose(valid["close"], valid["up_limit"], rtol=1e-6, atol=1e-8)
    near = (~up) & (valid["close"] < valid["up_limit"]) & (
        valid["close"] >= valid["up_limit"] * (1 - NEAR_LIMIT_DISTANCE)
    )
    empty.update(
        {
            "limit_up_count": int(up.sum()),
            "near_limit_up_count": int(near.sum()),
            "limit_up_share": int(up.sum()) / len(codes),
            "near_limit_up_share": int(near.sum()) / len(codes),
        }
    )
    return empty, True


def _crowding_observations(
    row: dict[str, object], current: pd.DataFrame, daily: pd.DataFrame
) -> dict[str, object]:
    turnover_now = daily["turnover_share"].iloc[-1] if not daily.empty else np.nan
    turnover_20 = row["turnover_share_average_20d"]
    return_1d = row["equal_weight_return_1d"]
    high_volume_low_progress = bool(
        np.isfinite(turnover_now)
        and np.isfinite(turnover_20)
        and turnover_20 > 0
        and turnover_now >= turnover_20 * 1.25
        and np.isfinite(return_1d)
        and abs(return_1d) <= 0.005
    )
    price_range = current["high"] - current["low"]
    reversal = (
        np.isfinite(price_range)
        & (price_range > 0)
        & (((current["high"] - current["close"]) / price_range) >= 0.60)
        & (current["close"] <= current["open"])
    )
    upper_wick = bool(len(current) and float(reversal.mean()) >= 0.30)
    narrow = bool(
        np.isfinite(return_1d)
        and return_1d > 0
        and (
            (np.isfinite(row["breadth_1d"]) and row["breadth_1d"] < 0.40)
            or (
                np.isfinite(row["top3_positive_contribution_1d"])
                and row["top3_positive_contribution_1d"] >= 0.70
            )
        )
    )
    divergence = bool(
        np.isfinite(row["turnover_share_change_5d"])
        and row["turnover_share_change_5d"] > 0
        and np.isfinite(row["equal_weight_return_5d"])
        and row["equal_weight_return_5d"] < 0
    )
    return {
        "high_volume_low_progress_flag": high_volume_low_progress,
        "upper_wick_reversal_flag": upper_wick,
        "narrow_participation_flag": narrow,
        "turnover_return_divergence_flag": divergence,
    }


def _minute_observations(
    minutes: pd.DataFrame, codes: list[str], analysis_date: date
) -> dict[str, object]:
    empty = {
        "intraday_status": "limited",
        "intraday_member_coverage_ratio": 0.0,
        "intraday_up_minute_share": np.nan,
        "intraday_open_phase_contribution": np.nan,
        "intraday_late_phase_contribution": np.nan,
        "intraday_max_drawdown": np.nan,
        "intraday_high_to_close_pullback": np.nan,
    }
    current = minutes[
        (minutes["trade_date"] == analysis_date)
        & minutes["ts_code"].astype(str).isin(codes)
    ]
    observed = int(current["ts_code"].nunique())
    coverage = observed / len(codes)
    empty["intraday_member_coverage_ratio"] = coverage
    if coverage < MINIMUM_MEMBER_COVERAGE:
        return empty
    pivot = current.pivot(index="minute", columns="ts_code", values="close").sort_index()
    pivot = pivot.reindex(columns=codes)
    if pivot.empty or pivot.isna().any().any() or len(pivot) < 2:
        return empty
    normalized = pivot / pivot.iloc[0]
    path = normalized.mean(axis=1)
    changes = path.pct_change(fill_method=None).dropna()
    empty.update(
        {
            "intraday_status": "complete",
            "intraday_up_minute_share": float((changes > 0).mean()),
            "intraday_open_phase_contribution": float(path.iloc[min(29, len(path) - 1)] / path.iloc[0] - 1),
            "intraday_late_phase_contribution": float(path.iloc[-1] / path.iloc[max(0, len(path) - 31)] - 1),
            "intraday_max_drawdown": float((path / path.cummax() - 1).min()),
            "intraday_high_to_close_pullback": float(path.max() / path.iloc[-1] - 1),
        }
    )
    return empty


def _blank_observations() -> dict[str, object]:
    row: dict[str, object] = {
        "observed_member_count": 0,
        "member_coverage_ratio": np.nan,
        "coverage_status": "limited",
        "limitation_notes": "",
        "return_dispersion_1d": np.nan,
        "top3_positive_contribution_1d": np.nan,
        "limit_observed_member_count": 0,
        "limit_coverage_ratio": np.nan,
        "limit_up_count": np.nan,
        "near_limit_up_count": np.nan,
        "limit_up_share": np.nan,
        "near_limit_up_share": np.nan,
        "high_volume_low_progress_flag": pd.NA,
        "upper_wick_reversal_flag": pd.NA,
        "narrow_participation_flag": pd.NA,
        "turnover_return_divergence_flag": pd.NA,
    }
    for horizon in HORIZONS:
        for prefix in (
            "equal_weight_return",
            "median_return",
            "breadth",
            "relative_return",
            "turnover_share_average",
            "official_index_return",
            "official_bottom_up_discrepancy",
        ):
            row[f"{prefix}_{horizon}d"] = np.nan
    for horizon in (3, 5):
        row[f"turnover_share_change_{horizon}d"] = np.nan
    for window in NEW_HIGH_WINDOWS:
        row[f"new_high_{window}d_share"] = np.nan
    row.update(_minute_observations(pd.DataFrame(columns=["trade_date", "ts_code", "minute", "close", "amount"]), ["_"], date.min))
    return row


def _prepare(
    frame: pd.DataFrame,
    required: set[str],
    key: tuple[str, ...],
    numeric: tuple[str, ...],
    label: str,
    analysis_date: date,
) -> pd.DataFrame:
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"{label} lacks required fields: {', '.join(missing)}")
    result = frame.copy()
    result["trade_date"] = pd.to_datetime(result["trade_date"], errors="raise").dt.date
    result = result[result["trade_date"] <= analysis_date].copy()
    if result.duplicated(list(key)).any():
        raise ValueError(f"duplicate business fact in {label} input")
    for column in numeric:
        result[column] = pd.to_numeric(result[column], errors="coerce")
    return result


def _prepare_catalog(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"group_type", "group_code", "group_name", "level", "official_index_code"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"sector catalog lacks required fields: {', '.join(missing)}")
    if frame.duplicated(["group_type", "group_code"]).any():
        raise ValueError("duplicate business fact in sector catalog input")
    return frame.copy()


def _prepare_memberships(frame: pd.DataFrame, analysis_date: date) -> pd.DataFrame:
    required = {"group_type", "group_code", "ts_code", "valid_from", "valid_to"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"sector membership lacks required fields: {', '.join(missing)}")
    result = frame.copy()
    valid_from = pd.to_datetime(result["valid_from"], errors="raise")
    valid_to = pd.to_datetime(result["valid_to"], errors="coerce")
    result["valid_from"] = pd.Series(
        [value.date() for value in valid_from], index=result.index, dtype=object
    )
    result["valid_to"] = pd.Series(
        [value.date() if pd.notna(value) else None for value in valid_to],
        index=result.index,
        dtype=object,
    )
    result = result[result["valid_from"] <= analysis_date].copy()
    if result.duplicated(["group_type", "group_code", "ts_code", "valid_from"]).any():
        raise ValueError("duplicate business fact in sector membership input")
    return result


def _prepare_minutes(frame: pd.DataFrame, analysis_date: date) -> pd.DataFrame:
    return _prepare(
        frame,
        {"trade_date", "ts_code", "minute", "close", "amount"},
        ("trade_date", "ts_code", "minute"),
        ("close", "amount"),
        "minute bar",
        analysis_date,
    )


def _effective_codes(members: pd.DataFrame, trading_day: date) -> list[str]:
    if members.empty:
        return []
    valid_to = members["valid_to"]
    active = members[
        (members["valid_from"] <= trading_day)
        & (valid_to.isna() | (valid_to >= trading_day))
    ]
    return sorted(active["ts_code"].astype(str).unique())


def _strict_market_amount(equity: pd.DataFrame, sessions: pd.Index) -> pd.Series:
    totals: dict[date, float] = {}
    for trading_day in sessions:
        values = pd.to_numeric(
            equity.loc[equity["trade_date"] == trading_day, "amount"], errors="coerce"
        )
        totals[trading_day] = (
            float(values.sum())
            if len(values) and np.isfinite(values).all() and (values >= 0).all()
            else np.nan
        )
    return pd.Series(totals, dtype=float)


def _valid_ohlc_amount(frame: pd.DataFrame) -> pd.Series:
    numeric = frame[["open", "high", "low", "close", "amount"]].apply(
        pd.to_numeric, errors="coerce"
    )
    return (
        np.isfinite(numeric).all(axis=1)
        & (numeric[["open", "high", "low", "close"]] > 0).all(axis=1)
        & (numeric["amount"] >= 0)
        & (numeric["high"] >= numeric[["open", "close", "low"]].max(axis=1))
        & (numeric["low"] <= numeric[["open", "close", "high"]].min(axis=1))
    )


def _finite_positive(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    return np.isfinite(numeric) & (numeric > 0)


def _compound_exact(series: pd.Series, horizon: int) -> float:
    sample = pd.to_numeric(series, errors="coerce").tail(horizon)
    if len(sample) != horizon or not np.isfinite(sample).all():
        return np.nan
    return float((1 + sample).prod() - 1)


def _mean_exact(series: pd.Series, horizon: int) -> float:
    sample = pd.to_numeric(series, errors="coerce").tail(horizon)
    if len(sample) != horizon or not np.isfinite(sample).all():
        return np.nan
    return float(sample.mean())


def _exact_change(series: pd.Series, horizon: int) -> float:
    values = pd.to_numeric(series, errors="coerce")
    if len(values) <= horizon:
        return np.nan
    current, prior = values.iloc[-1], values.iloc[-horizon - 1]
    if not np.isfinite(current) or not np.isfinite(prior):
        return np.nan
    return float(current - prior)


def _endpoint_return(series: pd.Series, horizon: int, analysis_date: date) -> float:
    values = pd.to_numeric(series, errors="coerce")
    if len(values) <= horizon or series.index[-1] != analysis_date:
        return np.nan
    sample = values.iloc[-horizon - 1 :]
    if len(sample) != horizon + 1 or not np.isfinite(sample).all() or (sample <= 0).any():
        return np.nan
    return float(sample.iloc[-1] / sample.iloc[0] - 1)


def _new_high_share(close: pd.DataFrame, codes: list[str], window: int) -> float:
    sample = close.reindex(columns=codes).tail(window)
    if len(sample) != window:
        return np.nan
    eligible = sample.columns[sample.notna().sum(axis=0) == window]
    if not len(eligible):
        return np.nan
    sample = sample[eligible]
    return float((sample.iloc[-1] >= sample.max(axis=0)).mean())


def _top_positive_contribution(returns: pd.Series) -> float:
    positive = returns[returns > 0].sort_values(ascending=False)
    total = float(positive.sum())
    return float(positive.head(3).sum() / total) if total > 0 else np.nan


__all__ = ["HOTSPOT_FORMULA_VERSION", "compute_hotspot_features"]
