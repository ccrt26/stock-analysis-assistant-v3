"""Reproducible sector observations built from governed market facts.

The formula intentionally exposes separate price, participation, turnover and
crowding observations.  It does not combine them into a hidden hotness value or
infer who traded.  Membership is evaluated on every market session so today's
constituents are never backfilled into history.
"""

from __future__ import annotations

from datetime import date
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd


HOTSPOT_FORMULA_VERSION = "sector-hotspot-v2"
HORIZONS = (1, 3, 5, 20)
NEW_HIGH_WINDOWS = (20, 60)
MINIMUM_MEMBER_COVERAGE = 0.80
NEAR_LIMIT_DISTANCE = 0.02
EXPECTED_MINUTE_POINTS = 240
MINIMUM_MINUTE_TIME_COVERAGE = 0.95


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

    Horizon mean, median and breadth use each continuously eligible member's
    exact endpoint return.  Daily turnover uses the membership effective on
    that session.  Turnover-share change is the current share minus the share
    exactly 3/5 sessions earlier.  Missing sessions are never removed to make a
    window appear complete.
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
                "intraday_member_coverage_ratio": np.nan,
                "intraday_time_coverage_ratio": np.nan,
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

    daily = _daily_group_series(group_members, equity, market_amount, sessions)
    base["observed_member_count"] = observed
    base["member_coverage_ratio"] = coverage_ratio
    for horizon in HORIZONS:
        horizon_values = _horizon_observations(
            group_members,
            equity_close,
            current_codes,
            sessions,
            horizon,
        )
        mean_return = horizon_values["mean_return"]
        median_return = horizon_values["median_return"]
        breadth = horizon_values["breadth"]
        base[f"horizon_observed_member_count_{horizon}d"] = horizon_values[
            "observed_count"
        ]
        base[f"horizon_member_coverage_ratio_{horizon}d"] = horizon_values[
            "coverage_ratio"
        ]
        if horizon == 1:
            base["positive_contributor_count_1d"] = horizon_values[
                "positive_count"
            ]
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
        new_high = _new_high_observations(
            group_members, equity_close, current_codes, sessions, window
        )
        base[f"new_high_{window}d_share"] = new_high["share"]
        base[f"new_high_observed_member_count_{window}d"] = new_high[
            "observed_count"
        ]
        base[f"new_high_member_coverage_ratio_{window}d"] = new_high[
            "coverage_ratio"
        ]

    limit_values, limit_complete = _current_limit_observations(
        current_valid, limits, current_codes, analysis_date
    )
    base.update(limit_values)
    if not limit_complete:
        limitations.append("current stock-limit coverage is below required 80%")

    official_code = item.get("official_index_code")
    official_status = "not_applicable"
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
        official_status = (
            "complete"
            if all(
                np.isfinite(base[f"official_index_return_{horizon}d"])
                for horizon in HORIZONS
            )
            else "limited"
        )
        if official_status == "limited":
            limitations.append("official index history is incomplete")
    base["official_index_status"] = official_status

    base.update(
        _crowding_observations(
            base,
            current_valid,
            daily,
            comparable=member_complete,
        )
    )
    minute_values = _minute_observations(minutes, current_codes, analysis_date)
    base.update(minute_values)
    if minute_values["intraday_status"] == "limited":
        limitations.append(
            "intraday member, time-point, open/close-anchor, or price coverage is incomplete"
        )

    core_horizons = all(
        np.isfinite(base[f"equal_weight_return_{horizon}d"])
        and base[f"horizon_member_coverage_ratio_{horizon}d"]
        >= MINIMUM_MEMBER_COVERAGE
        for horizon in HORIZONS
    )
    if not core_horizons:
        limitations.append("one or more 1/3/5/20-session sector windows are incomplete")
    new_high_complete = all(
        np.isfinite(base[f"new_high_{window}d_share"])
        for window in NEW_HIGH_WINDOWS
    )
    if not new_high_complete:
        limitations.append("20/60-session new-high member coverage is incomplete")
    official_complete = official_status in ("complete", "not_applicable")
    core_complete = (
        member_complete
        and limit_complete
        and core_horizons
        and new_high_complete
        and official_complete
    )
    base["coverage_status"] = (
        "complete"
        if core_complete and minute_values["intraday_status"] == "complete"
        else "complete_with_declared_gaps"
        if core_complete
        else "limited"
    )
    base["limitation_notes"] = "; ".join(limitations)
    return base


def _daily_group_series(
    group_members: pd.DataFrame,
    equity: pd.DataFrame,
    market_amount: pd.Series,
    sessions: pd.Index,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for trading_day in sessions:
        codes = _effective_codes(group_members, trading_day)
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
                "group_amount": group_amount,
                "turnover_share": turnover_share,
            }
        )
    return pd.DataFrame(rows).set_index("trade_date")


def _horizon_observations(
    group_members: pd.DataFrame,
    equity_close: pd.DataFrame,
    current_codes: list[str],
    sessions: pd.Index,
    horizon: int,
) -> dict[str, object]:
    """Calculate stock endpoint returns without backfilling current members."""

    empty = {
        "mean_return": np.nan,
        "median_return": np.nan,
        "breadth": np.nan,
        "observed_count": 0,
        "coverage_ratio": 0.0,
        "positive_count": 0,
    }
    window_dates = list(sessions[-horizon - 1 :])
    if len(window_dates) != horizon + 1 or not current_codes:
        return empty
    continuous = set(current_codes)
    for trading_day in window_dates:
        continuous &= set(_effective_codes(group_members, trading_day))
    if not continuous:
        return empty
    sample = equity_close.reindex(index=window_dates, columns=sorted(continuous))
    valid_columns = sample.columns[
        sample.apply(lambda values: bool(_finite_positive(values).all()), axis=0)
    ]
    if not len(valid_columns):
        return empty
    returns = sample.loc[window_dates[-1], valid_columns] / sample.loc[
        window_dates[0], valid_columns
    ] - 1.0
    returns = returns.replace([np.inf, -np.inf], np.nan).dropna()
    observed = int(len(returns))
    coverage = observed / len(current_codes)
    positive_count = int((returns > 0).sum())
    result = {
        **empty,
        "observed_count": observed,
        "coverage_ratio": coverage,
        "positive_count": positive_count,
    }
    if coverage < MINIMUM_MEMBER_COVERAGE:
        return result
    result.update(
        {
            "mean_return": float(returns.mean()),
            "median_return": float(returns.median()),
            "breadth": float((returns > 0).mean()),
        }
    )
    return result


def _new_high_observations(
    group_members: pd.DataFrame,
    equity_close: pd.DataFrame,
    current_codes: list[str],
    sessions: pd.Index,
    window: int,
) -> dict[str, object]:
    window_dates = list(sessions[-window:])
    empty = {"share": np.nan, "observed_count": 0, "coverage_ratio": 0.0}
    if len(window_dates) != window or not current_codes:
        return empty
    continuous = set(current_codes)
    for trading_day in window_dates:
        continuous &= set(_effective_codes(group_members, trading_day))
    sample = equity_close.reindex(index=window_dates, columns=sorted(continuous))
    valid_columns = sample.columns[
        sample.apply(lambda values: bool(_finite_positive(values).all()), axis=0)
    ]
    observed = int(len(valid_columns))
    coverage = observed / len(current_codes)
    if coverage < MINIMUM_MEMBER_COVERAGE or not observed:
        return {"share": np.nan, "observed_count": observed, "coverage_ratio": coverage}
    observed_sample = sample[valid_columns]
    return {
        "share": float(
            (observed_sample.iloc[-1] >= observed_sample.max(axis=0)).mean()
        ),
        "observed_count": observed,
        "coverage_ratio": coverage,
    }


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
            "limit_up_share": int(up.sum()) / len(valid),
            "near_limit_up_share": int(near.sum()) / len(valid),
        }
    )
    return empty, True


def _crowding_observations(
    row: dict[str, object],
    current: pd.DataFrame,
    daily: pd.DataFrame,
    *,
    comparable: bool,
) -> dict[str, object]:
    group_amount = pd.to_numeric(daily["group_amount"], errors="coerce")
    current_amount = group_amount.iloc[-1] if not group_amount.empty else np.nan
    trailing_amount = group_amount.tail(20)
    average_amount = (
        float(trailing_amount.mean())
        if len(trailing_amount) == 20 and np.isfinite(trailing_amount).all()
        else np.nan
    )
    amount_ratio = (
        current_amount / average_amount
        if np.isfinite(current_amount)
        and np.isfinite(average_amount)
        and average_amount > 0
        else np.nan
    )
    return_1d = row["equal_weight_return_1d"]
    high_volume_low_progress = (
        bool(amount_ratio >= 1.25 and abs(return_1d) <= 0.005 + 1e-12)
        if comparable and np.isfinite(amount_ratio) and np.isfinite(return_1d)
        else pd.NA
    )
    price_range = current["high"] - current["low"]
    reversal = (
        np.isfinite(price_range)
        & (price_range > 0)
        & (((current["high"] - current["close"]) / price_range) >= 0.60)
        & (current["close"] <= current["open"])
    )
    reversal_share = float(reversal.mean()) if len(current) else np.nan
    upper_wick = (
        bool(reversal_share >= 0.30)
        if comparable and np.isfinite(reversal_share)
        else pd.NA
    )
    breadth = row["breadth_1d"]
    positive_count = row["positive_contributor_count_1d"]
    concentration = row["top3_positive_contribution_1d"]
    narrow = (
        bool(
            return_1d > 0
            and (
                breadth < 0.40
                or (
                    positive_count >= 5
                    and np.isfinite(concentration)
                    and concentration >= 0.80
                )
            )
        )
        if comparable
        and np.isfinite(return_1d)
        and np.isfinite(breadth)
        else pd.NA
    )
    divergence = (
        bool(
            row["turnover_share_change_5d"] > 0
            and row["equal_weight_return_5d"] < 0
        )
        if comparable
        and np.isfinite(row["turnover_share_change_5d"])
        and np.isfinite(row["equal_weight_return_5d"])
        else pd.NA
    )
    return {
        "group_amount_vs_20d_average": amount_ratio,
        "upper_wick_reversal_share": reversal_share,
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
        "intraday_time_coverage_ratio": 0.0,
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
    qualified_codes: list[str] = []
    for code in codes:
        code_rows = current[current["ts_code"].astype(str) == code].sort_values(
            "minute"
        )
        prices = pd.to_numeric(code_rows["close"], errors="coerce")
        if (
            len(code_rows) / EXPECTED_MINUTE_POINTS
            >= MINIMUM_MINUTE_TIME_COVERAGE
            and _has_minute_session_anchors(code_rows["minute"])
            and len(prices)
            and bool(np.isfinite(prices).all())
            and bool((prices > 0).all())
        ):
            qualified_codes.append(code)
    member_coverage = len(qualified_codes) / len(codes)
    empty["intraday_member_coverage_ratio"] = member_coverage
    if member_coverage < MINIMUM_MEMBER_COVERAGE:
        return empty
    pivot = (
        current[current["ts_code"].astype(str).isin(qualified_codes)]
        .pivot(index="minute", columns="ts_code", values="close")
        .sort_index()
        .reindex(columns=qualified_codes)
        .dropna(axis=0, how="any")
    )
    time_coverage = len(pivot) / EXPECTED_MINUTE_POINTS
    empty["intraday_time_coverage_ratio"] = time_coverage
    if (
        pivot.empty
        or time_coverage < MINIMUM_MINUTE_TIME_COVERAGE
        or not _has_minute_session_anchors(pd.Series(pivot.index))
    ):
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


def _has_minute_session_anchors(values: pd.Series) -> bool:
    raw = values.dropna()
    labels = sorted(str(value) for value in raw.tolist())
    if not labels:
        return False
    if labels[0].startswith("m"):
        return labels[0] == "m000" and labels[-1] == "m239"
    parsed = pd.to_datetime(raw, errors="coerce", utc=True)
    if parsed.isna().any():
        return False
    local = parsed.sort_values().dt.tz_convert(ZoneInfo("Asia/Shanghai"))
    first = local.iloc[0]
    last = local.iloc[-1]
    return (first.hour, first.minute) in {(9, 30), (9, 31)} and (
        last.hour,
        last.minute,
    ) == (15, 0)


def _blank_observations() -> dict[str, object]:
    row: dict[str, object] = {
        "observed_member_count": 0,
        "member_coverage_ratio": np.nan,
        "coverage_status": "limited",
        "limitation_notes": "",
        "return_dispersion_1d": np.nan,
        "top3_positive_contribution_1d": np.nan,
        "positive_contributor_count_1d": 0,
        "official_index_status": "not_applicable",
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
        "group_amount_vs_20d_average": np.nan,
        "upper_wick_reversal_share": np.nan,
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
        row[f"horizon_observed_member_count_{horizon}d"] = 0
        row[f"horizon_member_coverage_ratio_{horizon}d"] = np.nan
    for horizon in (3, 5):
        row[f"turnover_share_change_{horizon}d"] = np.nan
    for window in NEW_HIGH_WINDOWS:
        row[f"new_high_{window}d_share"] = np.nan
        row[f"new_high_observed_member_count_{window}d"] = 0
        row[f"new_high_member_coverage_ratio_{window}d"] = np.nan
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
    for _, group in result.groupby(
        ["group_type", "group_code", "ts_code"], sort=False
    ):
        ordered = group.sort_values("valid_from")
        previous_end: date | None = None
        seen = False
        for row in ordered.to_dict(orient="records"):
            current_start = row["valid_from"]
            if seen and (previous_end is None or current_start <= previous_end):
                raise ValueError("overlapping effective periods in sector membership input")
            previous_end = row["valid_to"]
            seen = True
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


def _top_positive_contribution(returns: pd.Series) -> float:
    positive = returns[returns > 0].sort_values(ascending=False)
    total = float(positive.sum())
    return float(positive.head(3).sum() / total) if total > 0 else np.nan


__all__ = ["HOTSPOT_FORMULA_VERSION", "compute_hotspot_features"]
