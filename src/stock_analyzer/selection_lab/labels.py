from __future__ import annotations

from datetime import date
from typing import Iterable

import pandas as pd

from stock_analyzer.selection_lab.schemas import FutureLabels


def build_future_labels(
    prices: pd.DataFrame,
    trading_sessions: Iterable[date],
    formation_date: date,
    benchmark: pd.DataFrame | None = None,
) -> FutureLabels:
    sessions = sorted(set(trading_sessions))
    if formation_date not in sessions:
        raise ValueError("formation date is not an open trading session")
    formation_position = sessions.index(formation_date)
    if formation_position + 1 >= len(sessions):
        return _null_labels(None)
    action_date = sessions[formation_position + 1]

    frame = prices.copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.date
    by_date = frame.set_index("trade_date", drop=False)
    if action_date not in by_date.index:
        return _null_labels(None)
    action = by_date.loc[action_date]
    if isinstance(action, pd.DataFrame):
        raise ValueError("duplicate action-date price rows")
    executable = _is_executable(action)
    if not executable:
        return FutureLabels(
            executable_on_action_date=False,
            hit_20pct_close_within_20d=False,
        )

    window_dates = sessions[formation_position + 1 : formation_position + 21]
    if len(window_dates) < 20 or any(day not in by_date.index for day in window_dates):
        return _null_labels(True)
    window = by_date.loc[window_dates].copy()
    if window.index.duplicated().any():
        raise ValueError("duplicate price rows in label window")

    entrance_factor = _positive_float(action["adj_factor"], "action adj_factor")
    entrance_open = (
        _positive_float(action["open"], "action open")
        * entrance_factor
        / entrance_factor
    )
    factors = pd.to_numeric(window["adj_factor"], errors="coerce")
    if factors.isna().any() or (factors <= 0).any():
        raise ValueError("label window has invalid adjustment factor")
    close_returns = (
        pd.to_numeric(window["close"], errors="coerce")
        * factors
        / entrance_factor
        / entrance_open
        - 1.0
    )
    low_returns = (
        pd.to_numeric(window["low"], errors="coerce")
        * factors
        / entrance_factor
        / entrance_open
        - 1.0
    )
    if close_returns.isna().any() or low_returns.isna().any():
        raise ValueError("label window has invalid price")

    hit_positions = [
        index + 1 for index, value in enumerate(close_returns) if value >= 0.20 - 1e-12
    ]
    first_hit_day = hit_positions[0] if hit_positions else None
    adverse_end = first_hit_day if first_hit_day is not None else 20
    max_close = float(close_returns.max())
    terminal = float(close_returns.iloc[-1])
    market_relative = _terminal_relative_market(
        benchmark,
        window_dates,
        entrance_factor=entrance_factor,
        stock_terminal=terminal,
    )
    return FutureLabels(
        executable_on_action_date=True,
        hit_20pct_close_within_20d=bool(hit_positions),
        first_hit_day=first_hit_day,
        max_close_return_20d=_rounded(max_close),
        terminal_return_20d=_rounded(terminal),
        terminal_relative_market_20d=market_relative,
        max_adverse_move_before_hit_or_end=_rounded(
            float(low_returns.iloc[:adverse_end].min())
        ),
        giveback_from_max_close_to_terminal=_rounded(max_close - terminal),
    )


def _is_executable(action: pd.Series) -> bool:
    return bool(
        not bool(action.get("suspended", False))
        and bool(action.get("reliable_quote", True))
        and not bool(action.get("one_price_limit", False))
        and pd.notna(action.get("open"))
        and float(action["open"]) > 0
    )


def _positive_float(value: object, name: str) -> float:
    parsed = float(value)
    if not pd.notna(parsed) or parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


def _null_labels(executable: bool | None) -> FutureLabels:
    return FutureLabels(
        executable_on_action_date=executable,
        hit_20pct_close_within_20d=None,
    )


def _terminal_relative_market(
    benchmark: pd.DataFrame | None,
    window_dates: list[date],
    *,
    entrance_factor: float,
    stock_terminal: float,
) -> float | None:
    del entrance_factor
    if benchmark is None or benchmark.empty:
        return None
    frame = benchmark.copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.date
    indexed = frame.set_index("trade_date")
    if any(day not in indexed.index for day in window_dates):
        return None
    entrance = float(indexed.loc[window_dates[0], "open"])
    terminal = float(indexed.loc[window_dates[-1], "close"])
    if entrance <= 0:
        return None
    return _rounded(stock_terminal - (terminal / entrance - 1.0))


def _rounded(value: float) -> float:
    return round(value, 12)
