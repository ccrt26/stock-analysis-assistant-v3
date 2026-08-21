"""Formation-date-safe price and turnover observations around selected events.

The caller chooses which event is economically relevant.  This module only
aligns its availability time to full trading sessions and computes reproducible
relative-price and turnover facts; it does not classify event semantics or make
selection decisions.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd


EVENT_REACTION_EVIDENCE_ID = "event_price_reaction"
EVENT_REACTION_FORMULA_VERSION = "event-price-reaction-v1"
EVENT_REACTION_HORIZONS = (1, 3, 5)
MINIMUM_INDUSTRY_MEMBER_COVERAGE = 0.80
SHANGHAI = ZoneInfo("Asia/Shanghai")
MARKET_OPEN = time(9, 30)


def compute_event_reaction_features(
    events: pd.DataFrame,
    equity_daily: pd.DataFrame,
    benchmark_daily: pd.DataFrame,
    *,
    analysis_date: date,
    as_of: datetime,
    trading_sessions: Sequence[date],
    industry_memberships: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Return one deterministic event-reaction row per caller-selected event.

    An event available before the market open is aligned to that session.  All
    other events are aligned to the next full session.  Price observations are
    always truncated at ``analysis_date`` even when future rows are present in
    an input frame.
    """

    cutoff = _aware_timestamp(as_of, "as_of").tz_convert(SHANGHAI)
    if analysis_date > cutoff.date():
        raise ValueError("analysis_date_after_as_of")
    _require_fields(events, {"event_id", "ts_code", "available_at"}, "events")
    _require_fields(
        equity_daily,
        {"trade_date", "ts_code", "close", "adj_factor", "amount"},
        "equity_daily",
    )
    _require_fields(benchmark_daily, {"trade_date", "close"}, "benchmark_daily")
    if events["event_id"].astype(str).duplicated().any():
        raise ValueError("duplicate_event_ids")

    sessions = sorted({_as_date(value) for value in trading_sessions})
    if not sessions:
        raise ValueError("trading_sessions_empty")
    equity = _prepare_equity(equity_daily, analysis_date)
    benchmark = _prepare_benchmark(benchmark_daily, analysis_date)
    memberships = _prepare_memberships(industry_memberships)

    rows = [
        _event_row(
            event,
            cutoff=cutoff,
            analysis_date=analysis_date,
            sessions=sessions,
            equity=equity,
            benchmark=benchmark,
            memberships=memberships,
        )
        for _, event in events.iterrows()
    ]
    if not rows:
        return pd.DataFrame(columns=_output_columns())
    return (
        pd.DataFrame(rows, columns=_output_columns())
        .sort_values(["event_id", "ts_code"])
        .reset_index(drop=True)
    )


def _event_row(
    event: pd.Series,
    *,
    cutoff: pd.Timestamp,
    analysis_date: date,
    sessions: list[date],
    equity: pd.DataFrame,
    benchmark: pd.Series,
    memberships: pd.DataFrame,
) -> dict[str, object]:
    event_time = _aware_timestamp(event["available_at"], "event available_at")
    event_local = event_time.tz_convert(SHANGHAI)
    if event_local > cutoff:
        raise ValueError("event_available_after_as_of")
    event_id = str(event["event_id"]).strip()
    ts_code = str(event["ts_code"]).strip()
    if not event_id or not ts_code:
        raise ValueError("event_identity_missing")

    reaction_start = _reaction_start(event_local, sessions)
    observed = (
        []
        if reaction_start is None
        else [
            session
            for session in sessions
            if reaction_start <= session <= analysis_date
        ][: max(EVENT_REACTION_HORIZONS)]
    )
    window_status = (
        "awaiting_first_session"
        if not observed
        else "complete"
        if len(observed) >= max(EVENT_REACTION_HORIZONS)
        else "partial"
    )
    row: dict[str, object] = {
        "analysis_date": analysis_date,
        "event_id": event_id,
        "ts_code": ts_code,
        "evidence_id": EVENT_REACTION_EVIDENCE_ID,
        "formula_version": EVENT_REACTION_FORMULA_VERSION,
        "event_available_at": event_local.isoformat(),
        "reaction_start_date": reaction_start,
        "observed_reaction_sessions": len(observed),
        "reaction_window_status": window_status,
        "industry_code": None,
        "industry_comparison_status": "limited",
        "coverage_status": "limited",
        "limitation_notes": "",
    }
    for field in _metric_columns():
        row[field] = np.nan

    notes: list[str] = []
    if reaction_start is None:
        notes.append("next full trading session is absent from the supplied calendar")
        row["limitation_notes"] = "; ".join(notes)
        return row
    start_position = sessions.index(reaction_start)
    if start_position == 0:
        notes.append("pre-event session is unavailable")
        row["limitation_notes"] = "; ".join(notes)
        return row
    prior_date = sessions[start_position - 1]

    stock = equity[equity["ts_code"].eq(ts_code)].set_index("trade_date")
    candidate_industry, members = _industry_members(
        memberships,
        ts_code=ts_code,
        on_date=reaction_start,
    )
    if candidate_industry is not None:
        row["industry_code"] = candidate_industry

    if start_position >= 6:
        pre_start = sessions[start_position - 6]
        row["pre_event_return_5d"] = _return(stock["adjusted_close"], pre_start, prior_date)
        row["pre_event_relative_market_5d"] = _relative_return(
            row["pre_event_return_5d"],
            _return(benchmark, pre_start, prior_date),
        )
        industry_pre, industry_pre_complete = _industry_return(
            equity,
            members,
            pre_start,
            prior_date,
        )
        row["pre_event_relative_industry_5d"] = _relative_return(
            row["pre_event_return_5d"],
            industry_pre,
        )
    else:
        industry_pre_complete = False
        notes.append("fewer than five pre-event sessions")

    prior_amount_dates = sessions[max(0, start_position - 20) : start_position]
    prior_amount = _mean_amount(stock, prior_amount_dates)
    industry_complete: list[bool] = [industry_pre_complete]
    for horizon in EVENT_REACTION_HORIZONS:
        if len(observed) < horizon:
            continue
        target_date = observed[horizon - 1]
        absolute = _return(stock["adjusted_close"], prior_date, target_date)
        row[f"event_return_{horizon}d"] = absolute
        row[f"relative_market_return_{horizon}d"] = _relative_return(
            absolute,
            _return(benchmark, prior_date, target_date),
        )
        industry_return, complete = _industry_return(
            equity,
            members,
            prior_date,
            target_date,
        )
        industry_complete.append(complete)
        row[f"relative_industry_return_{horizon}d"] = _relative_return(
            absolute,
            industry_return,
        )
        reaction_dates = observed[:horizon]
        reaction_amount = _mean_amount(stock, reaction_dates)
        if _finite(prior_amount) and prior_amount > 0.0 and _finite(reaction_amount):
            row[f"amount_ratio_{horizon}d"] = reaction_amount / prior_amount

    if members and all(industry_complete):
        row["industry_comparison_status"] = "complete"
    else:
        notes.append("event-window industry comparison is incomplete")
    core_fields = [
        "event_return_5d",
        "relative_market_return_5d",
        "relative_industry_return_5d",
        "amount_ratio_5d",
    ]
    if window_status == "complete" and all(_finite(row[field]) for field in core_fields):
        row["coverage_status"] = "complete"
    elif window_status == "partial":
        notes.append("fewer than five post-event sessions are observable")
    elif window_status == "awaiting_first_session":
        notes.append("event is known but no full reaction session is observable")
    row["limitation_notes"] = "; ".join(dict.fromkeys(notes))
    return row


def _prepare_equity(frame: pd.DataFrame, analysis_date: date) -> pd.DataFrame:
    output = frame.copy()
    output["trade_date"] = pd.to_datetime(output["trade_date"], errors="raise").dt.date
    output = output[output["trade_date"] <= analysis_date].copy()
    output["ts_code"] = output["ts_code"].astype(str)
    output["adjusted_close"] = (
        pd.to_numeric(output["close"], errors="coerce")
        * pd.to_numeric(output["adj_factor"], errors="coerce")
    )
    output["amount"] = pd.to_numeric(output["amount"], errors="coerce")
    if output.duplicated(["trade_date", "ts_code"]).any():
        raise ValueError("duplicate_equity_rows")
    return output


def _prepare_benchmark(frame: pd.DataFrame, analysis_date: date) -> pd.Series:
    output = frame.copy()
    output["trade_date"] = pd.to_datetime(output["trade_date"], errors="raise").dt.date
    output = output[output["trade_date"] <= analysis_date].copy()
    if output["trade_date"].duplicated().any():
        raise ValueError("duplicate_benchmark_rows")
    return pd.Series(
        pd.to_numeric(output["close"], errors="coerce").to_numpy(),
        index=output["trade_date"],
        dtype=float,
    )


def _prepare_memberships(frame: pd.DataFrame | None) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    _require_fields(
        frame,
        {"industry_system", "level", "industry_code", "ts_code", "valid_from", "valid_to"},
        "industry_memberships",
    )
    output = frame.copy()
    output["valid_from"] = pd.to_datetime(output["valid_from"], errors="raise").dt.normalize()
    output["valid_to"] = pd.to_datetime(output["valid_to"], errors="coerce").dt.normalize()
    return output


def _industry_members(
    memberships: pd.DataFrame,
    *,
    ts_code: str,
    on_date: date,
) -> tuple[str | None, tuple[str, ...]]:
    if memberships.empty:
        return None, ()
    boundary = pd.Timestamp(on_date)
    active = memberships[
        memberships["industry_system"].astype(str).eq("SW2021")
        & memberships["level"].astype(str).str.upper().eq("L2")
        & (memberships["valid_from"] <= boundary)
        & (memberships["valid_to"].isna() | (memberships["valid_to"] >= boundary))
    ].copy()
    codes = (
        active.loc[
            active["ts_code"].astype(str).eq(ts_code),
            "industry_code",
        ]
        .astype(str)
        .unique()
    )
    if len(codes) != 1:
        return None, ()
    industry_code = str(codes[0])
    member_codes = active.loc[
        active["industry_code"].astype(str).eq(industry_code),
        "ts_code",
    ]
    members = tuple(
        sorted(member_codes.astype(str).unique())
    )
    return industry_code, members


def _industry_return(
    equity: pd.DataFrame,
    members: tuple[str, ...],
    start: date,
    end: date,
) -> tuple[float, bool]:
    if not members:
        return np.nan, False
    selected = equity[
        equity["ts_code"].isin(members)
        & equity["trade_date"].isin((start, end))
    ]
    pivot = selected.pivot(index="ts_code", columns="trade_date", values="adjusted_close")
    if start not in pivot or end not in pivot:
        return np.nan, False
    returns = pivot[end] / pivot[start] - 1.0
    returns = returns[np.isfinite(returns)]
    coverage = len(returns) / len(members)
    if returns.empty or coverage < MINIMUM_INDUSTRY_MEMBER_COVERAGE:
        return np.nan, False
    return float(returns.mean()), True


def _reaction_start(event_time: pd.Timestamp, sessions: list[date]) -> date | None:
    event_date = event_time.date()
    if event_date in sessions and event_time.time() < MARKET_OPEN:
        return event_date
    return next((session for session in sessions if session > event_date), None)


def _return(values: pd.Series, start: date, end: date) -> float:
    if start not in values.index or end not in values.index:
        return np.nan
    first = float(values.loc[start])
    last = float(values.loc[end])
    if not (_finite(first) and _finite(last) and first > 0.0):
        return np.nan
    return last / first - 1.0


def _relative_return(stock_return: object, reference_return: object) -> float:
    if not (_finite(stock_return) and _finite(reference_return)):
        return np.nan
    return float(stock_return) - float(reference_return)


def _mean_amount(stock: pd.DataFrame, sessions: Sequence[date]) -> float:
    if not sessions:
        return np.nan
    values = pd.to_numeric(
        stock.loc[stock.index.intersection(sessions), "amount"],
        errors="coerce",
    )
    values = values[np.isfinite(values) & (values > 0.0)]
    return float(values.mean()) if len(values) == len(sessions) else np.nan


def _aware_timestamp(value: object, label: str) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        raise ValueError(f"{label} must be timezone-aware")
    return timestamp


def _as_date(value: object) -> date:
    return pd.Timestamp(value).date()


def _finite(value: object) -> bool:
    try:
        return bool(np.isfinite(float(value)))
    except (TypeError, ValueError):
        return False


def _require_fields(frame: pd.DataFrame, required: set[str], label: str) -> None:
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"{label} lacks required fields: {', '.join(missing)}")


def _metric_columns() -> tuple[str, ...]:
    return (
        "pre_event_return_5d",
        "pre_event_relative_market_5d",
        "pre_event_relative_industry_5d",
        *(f"event_return_{horizon}d" for horizon in EVENT_REACTION_HORIZONS),
        *(f"relative_market_return_{horizon}d" for horizon in EVENT_REACTION_HORIZONS),
        *(f"relative_industry_return_{horizon}d" for horizon in EVENT_REACTION_HORIZONS),
        *(f"amount_ratio_{horizon}d" for horizon in EVENT_REACTION_HORIZONS),
    )


def _output_columns() -> tuple[str, ...]:
    return (
        "analysis_date",
        "event_id",
        "ts_code",
        "evidence_id",
        "formula_version",
        "event_available_at",
        "reaction_start_date",
        "observed_reaction_sessions",
        "reaction_window_status",
        "industry_code",
        "industry_comparison_status",
        *_metric_columns(),
        "coverage_status",
        "limitation_notes",
    )


__all__ = [
    "EVENT_REACTION_EVIDENCE_ID",
    "EVENT_REACTION_FORMULA_VERSION",
    "EVENT_REACTION_HORIZONS",
    "compute_event_reaction_features",
]
