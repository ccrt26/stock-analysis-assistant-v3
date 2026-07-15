from __future__ import annotations

from datetime import date, time
from typing import Callable
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd


def _reject_future_labels(frame: pd.DataFrame) -> None:
    leaked = [
        str(column)
        for column in frame.columns
        if str(column).startswith("future_") or "touch_20pct" in str(column)
    ]
    if leaked:
        raise ValueError(f"future label columns are forbidden in signal inputs: {leaked}")


def _require(frame: pd.DataFrame, columns: set[str]) -> None:
    missing = columns - set(frame.columns)
    if missing:
        raise ValueError(f"signal input missing columns: {sorted(missing)}")


def _stable_groups(
    frame: pd.DataFrame,
    *,
    value_column: str,
    group_columns: tuple[str, ...],
    bins: int,
) -> pd.Series:
    result = pd.Series(pd.NA, index=frame.index, dtype="Int64")
    valid = frame[value_column].notna()
    if not valid.any():
        return result
    grouper: str | list[str] = (
        group_columns[0] if len(group_columns) == 1 else list(group_columns)
    )
    for _, group in frame.loc[valid].groupby(grouper, dropna=False, sort=True):
        tie_columns = [value_column]
        if "ts_code" in group:
            tie_columns.append("ts_code")
        elif "industry_code" in group:
            tie_columns.append("industry_code")
        ordered = group.sort_values(tie_columns, kind="mergesort")
        assignments = np.floor(np.arange(len(ordered)) * bins / len(ordered)).astype(int) + 1
        result.loc[ordered.index] = assignments
    return result


def size_value_signal(frame: pd.DataFrame) -> pd.DataFrame:
    _reject_future_labels(frame)
    _require(frame, {"analysis_date", "ts_code", "pe_ttm", "circ_mv"})
    out = frame.copy()
    pe = pd.to_numeric(out["pe_ttm"], errors="coerce")
    out["signal_value"] = np.where(pe > 0, 1.0 / pe, np.nan)
    out["cap_tercile"] = _stable_groups(
        out,
        value_column="circ_mv",
        group_columns=("analysis_date",),
        bins=3,
    )
    cap_rank = out.groupby("analysis_date", dropna=False)["circ_mv"].rank(
        method="first", pct=True
    )
    out["smallest_30pct"] = cap_rank <= 0.30
    out["signal_quintile"] = _stable_groups(
        out,
        value_column="signal_value",
        group_columns=("analysis_date", "cap_tercile"),
        bins=5,
    )
    return out


def reversal_signal(frame: pd.DataFrame) -> pd.DataFrame:
    _reject_future_labels(frame)
    _require(frame, {"analysis_date", "ts_code", "prior_return_20d"})
    out = frame.copy()
    out["signal_quintile"] = _stable_groups(
        out,
        value_column="prior_return_20d",
        group_columns=("analysis_date",),
        bins=5,
    )
    return out


def limit_signal(frame: pd.DataFrame) -> pd.DataFrame:
    _reject_future_labels(frame)
    _require(
        frame,
        {
            "analysis_date",
            "ts_code",
            "high",
            "close",
            "up_limit",
            "circ_mv",
            "prior_return_20d",
        },
    )
    out = frame.copy()
    high = pd.to_numeric(out["high"], errors="coerce")
    close = pd.to_numeric(out["close"], errors="coerce")
    upper = pd.to_numeric(out["up_limit"], errors="coerce")
    out["limit_touched"] = high.notna() & upper.notna() & (high >= upper)
    out["closed_at_limit"] = close.notna() & upper.notna() & (close >= upper)
    out["cap_tercile"] = _stable_groups(
        out,
        value_column="circ_mv",
        group_columns=("analysis_date",),
        bins=3,
    )
    out["prior_return_quintile"] = _stable_groups(
        out,
        value_column="prior_return_20d",
        group_columns=("analysis_date",),
        bins=5,
    )
    return out


def industry_momentum_signal(frame: pd.DataFrame) -> pd.DataFrame:
    _reject_future_labels(frame)
    _require(
        frame,
        {
            "analysis_date",
            "industry_code",
            "industry_return_20d",
            "market_return_20d",
            "breadth_20d",
            "top_contribution_share_20d",
        },
    )
    out = frame.copy()
    out["relative_return_20d"] = (
        pd.to_numeric(out["industry_return_20d"], errors="coerce")
        - pd.to_numeric(out["market_return_20d"], errors="coerce")
    )
    out["signal_quintile"] = _stable_groups(
        out,
        value_column="relative_return_20d",
        group_columns=("analysis_date",),
        bins=5,
    )
    return out


def industry_component_signal(frame: pd.DataFrame) -> pd.DataFrame:
    _reject_future_labels(frame)
    _require(
        frame,
        {"analysis_date", "ts_code", "prior_return_20d", "industry_return_20d"},
    )
    out = frame.copy()
    out["industry_subtracted_return_20d"] = (
        pd.to_numeric(out["prior_return_20d"], errors="coerce")
        - pd.to_numeric(out["industry_return_20d"], errors="coerce")
    )
    out["individual_return_quintile"] = _stable_groups(
        out,
        value_column="prior_return_20d",
        group_columns=("analysis_date",),
        bins=5,
    )
    out["industry_subtracted_quintile"] = _stable_groups(
        out,
        value_column="industry_subtracted_return_20d",
        group_columns=("analysis_date",),
        bins=5,
    )
    return out


def map_announcement_sessions(
    announcements: pd.DataFrame,
    calendar: pd.DataFrame,
) -> pd.DataFrame:
    _require(announcements, {"announcement_time"})
    _require(calendar, {"cal_date", "is_open"})
    out = announcements.copy()
    opened = pd.to_datetime(
        calendar.loc[calendar["is_open"].astype(bool), "cal_date"], errors="raise"
    ).dt.date
    open_dates = tuple(sorted(set(opened)))

    def map_one(value: object) -> date | None:
        timestamp = pd.Timestamp(value)
        if timestamp.tzinfo is None:
            timestamp = timestamp.tz_localize("Asia/Shanghai")
        else:
            timestamp = timestamp.tz_convert(ZoneInfo("Asia/Shanghai"))
        local_date = timestamp.date()
        if local_date in open_dates and timestamp.time() <= time(15, 0):
            return local_date
        return next((item for item in open_dates if item > local_date), None)

    out["event_date"] = out["announcement_time"].map(map_one)
    return out


def _deduplicate_company_events(frame: pd.DataFrame) -> pd.DataFrame:
    if "event_session_index" not in frame or frame.empty:
        return frame
    keep: list[object] = []
    ordered = frame.sort_values(
        ["ts_code", "event_session_index", "event_id"], kind="mergesort"
    )
    for _, company in ordered.groupby("ts_code", sort=True):
        last_kept: int | None = None
        for index, row in company.iterrows():
            session = int(row["event_session_index"])
            if last_kept is None or session - last_kept > 30:
                keep.append(index)
                last_kept = session
    return frame.loc[keep].sort_index().copy()


def daily_event_signal(frame: pd.DataFrame) -> pd.DataFrame:
    _reject_future_labels(frame)
    _require(
        frame,
        {
            "event_id",
            "ts_code",
            "event_date",
            "stock_return_0",
            "stock_return_1",
            "market_return_0",
            "market_return_1",
            "local_formal_announcement_match",
        },
    )
    out = _deduplicate_company_events(frame.copy())
    out["car_0_1"] = (
        pd.to_numeric(out["stock_return_0"], errors="coerce")
        - pd.to_numeric(out["market_return_0"], errors="coerce")
        + pd.to_numeric(out["stock_return_1"], errors="coerce")
        - pd.to_numeric(out["market_return_1"], errors="coerce")
    )
    out["information_match_status"] = np.where(
        out["local_formal_announcement_match"].astype(bool),
        "local_formal_announcement_match",
        "no_local_formal_announcement_match",
    )
    return out


def earnings_drift_signal(frame: pd.DataFrame) -> pd.DataFrame:
    _reject_future_labels(frame)
    _require(frame, {"event_date", "ts_code", "event_car_0_1"})
    out = frame.copy()
    out["car_quintile"] = _stable_groups(
        out,
        value_column="event_car_0_1",
        group_columns=("event_date",),
        bins=5,
    )
    return out


def announcement_reaction_signal(frame: pd.DataFrame) -> pd.DataFrame:
    _reject_future_labels(frame)
    _require(
        frame,
        {
            "analysis_date",
            "ts_code",
            "market_adjusted_return",
            "local_formal_announcement_match",
        },
    )
    out = frame.copy()
    out["information_match_status"] = np.where(
        out["local_formal_announcement_match"].astype(bool),
        "local_formal_announcement_match",
        "no_local_formal_announcement_match",
    )
    return out


def financial_turnaround_signal(frame: pd.DataFrame) -> pd.DataFrame:
    _reject_future_labels(frame)
    pairs = (
        ("roe_up", "roe", "prior_roe", "up"),
        (
            "operating_cash_flow_up",
            "operating_cash_flow",
            "prior_operating_cash_flow",
            "up",
        ),
        ("leverage_down", "leverage", "prior_leverage", "down"),
        ("current_ratio_up", "current_ratio", "prior_current_ratio", "up"),
        ("profit_margin_up", "profit_margin", "prior_profit_margin", "up"),
        ("asset_turnover_up", "asset_turnover", "prior_asset_turnover", "up"),
    )
    _require(
        frame,
        {"ts_code", "report_period"}
        | {column for _, current, prior, _ in pairs for column in (current, prior)},
    )
    out = frame.copy()
    direction_columns: list[str] = []
    for output, current, prior, direction in pairs:
        current_value = pd.to_numeric(out[current], errors="coerce")
        prior_value = pd.to_numeric(out[prior], errors="coerce")
        comparable = current_value.notna() & prior_value.notna()
        improved = current_value > prior_value if direction == "up" else current_value < prior_value
        out[output] = comparable & improved
        direction_columns.append(output)
    out["improvement_count"] = out[direction_columns].sum(axis=1).astype(int)
    return out


_SIGNAL_DISPATCH: dict[str, Callable[[pd.DataFrame], pd.DataFrame]] = {
    "a_share_size_value": size_value_signal,
    "a_share_momentum_reversal": reversal_signal,
    "price_limit_t_plus_one": limit_signal,
    "a_share_factor_industry_momentum": industry_momentum_signal,
    "overseas_industry_momentum_method": industry_component_signal,
    "daily_event_study": daily_event_signal,
    "a_share_earnings_announcement_drift": earnings_drift_signal,
    "formal_announcement_price_reaction": announcement_reaction_signal,
    "financial_quality_turnaround": financial_turnaround_signal,
}


def compute_study_signal(study_id: str, frame: pd.DataFrame) -> pd.DataFrame:
    try:
        function = _SIGNAL_DISPATCH[study_id]
    except KeyError as exc:
        raise ValueError(f"unsupported validation study: {study_id}") from exc
    return function(frame)


__all__ = [
    "announcement_reaction_signal",
    "compute_study_signal",
    "daily_event_signal",
    "earnings_drift_signal",
    "financial_turnaround_signal",
    "industry_component_signal",
    "industry_momentum_signal",
    "limit_signal",
    "map_announcement_sessions",
    "reversal_signal",
    "size_value_signal",
]
