"""Read-only helpers for historical candidate-framework validation.

These functions evaluate already frozen research selections.  They do not
produce recommendations, scores, portfolio returns, or trading instructions.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date

import pandas as pd


def select_spaced_origins(
    open_sessions: Sequence[date],
    *,
    start: date,
    end: date,
    step: int,
) -> tuple[date, ...]:
    """Return every ``step``-th eligible open session in chronological order."""

    if step <= 0:
        raise ValueError("step must be positive")
    eligible = sorted({value for value in open_sessions if start <= value <= end})
    return tuple(eligible[::step])


def validate_formation_cutoff(
    evidence: pd.DataFrame,
    *,
    cutoff: str | pd.Timestamp,
    available_column: str = "available_at",
) -> pd.DataFrame:
    """Fail closed when a formation evidence row is visible only after cutoff."""

    if available_column not in evidence:
        raise ValueError(f"evidence lacks {available_column}")
    prepared = evidence.copy()
    available = pd.to_datetime(prepared[available_column], utc=True, errors="raise")
    boundary = pd.to_datetime(cutoff, utc=True, errors="raise")
    if available.isna().any():
        raise ValueError("formation evidence has missing available_at")
    if (available > boundary).any():
        raise ValueError("future evidence exceeds the formation cutoff")
    prepared[available_column] = available
    return prepared


def round_robin_union(
    route_lists: Mapping[str, Sequence[str]],
    *,
    limit: int,
) -> tuple[str, ...]:
    """Interleave route-native lists without scores and without duplicates."""

    if limit < 0:
        raise ValueError("limit must be non-negative")
    routes = list(route_lists)
    positions = {route: 0 for route in routes}
    selected: list[str] = []
    seen: set[str] = set()
    round_index = 0

    while len(selected) < limit and routes:
        added_this_round = False
        offset = round_index % len(routes)
        ordered_routes = routes[offset:] + routes[:offset]
        for route in ordered_routes:
            values = route_lists[route]
            while positions[route] < len(values):
                value = str(values[positions[route]])
                positions[route] += 1
                if value in seen:
                    continue
                seen.add(value)
                selected.append(value)
                added_this_round = True
                break
            if len(selected) >= limit:
                break
        if not added_this_round:
            break
        round_index += 1
    return tuple(selected)


def compute_forward_outcomes(
    prices: pd.DataFrame,
    selections: pd.DataFrame,
    *,
    horizons: tuple[int, ...] = (10, 20, 30),
    target_return: float = 0.20,
) -> pd.DataFrame:
    """Evaluate adjusted future paths for already frozen selections."""

    price_fields = {"trade_date", "ts_code", "adj_close", "adj_high", "adj_low"}
    selection_fields = {"formation_date", "ts_code", "policy", "layer"}
    missing_prices = sorted(price_fields - set(prices.columns))
    missing_selections = sorted(selection_fields - set(selections.columns))
    if missing_prices:
        raise ValueError(f"prices lack required fields: {', '.join(missing_prices)}")
    if missing_selections:
        raise ValueError(
            f"selections lack required fields: {', '.join(missing_selections)}"
        )
    if not horizons or any(value <= 0 for value in horizons):
        raise ValueError("horizons must contain positive session counts")
    if target_return <= 0:
        raise ValueError("target_return must be positive")

    prepared_prices = prices.copy()
    prepared_prices["trade_date"] = pd.to_datetime(
        prepared_prices["trade_date"], errors="raise"
    ).dt.normalize()
    prepared_prices["ts_code"] = prepared_prices["ts_code"].astype(str)
    prepared_prices = prepared_prices.sort_values(["ts_code", "trade_date"])
    if prepared_prices.duplicated(["trade_date", "ts_code"]).any():
        raise ValueError("prices contain duplicate stock-date rows")
    market_sessions = pd.Index(
        sorted(prepared_prices["trade_date"].dropna().unique()),
        name="trade_date",
    )

    prepared_selections = selections.copy()
    prepared_selections["formation_date"] = pd.to_datetime(
        prepared_selections["formation_date"], errors="raise"
    ).dt.normalize()
    prepared_selections["ts_code"] = prepared_selections["ts_code"].astype(str)

    rows: list[dict[str, object]] = []
    for selection in prepared_selections.itertuples(index=False):
        stock_prices = prepared_prices[
            prepared_prices["ts_code"] == selection.ts_code
        ]
        formation = stock_prices[
            stock_prices["trade_date"] == selection.formation_date
        ]
        if len(formation) != 1:
            raise ValueError(
                "formation adjusted close is not unique for "
                f"{selection.ts_code} on {selection.formation_date.date()}"
            )
        formation_close = float(formation.iloc[0]["adj_close"])
        if formation_close <= 0:
            raise ValueError("formation adjusted close must be positive")
        future_sessions = market_sessions[market_sessions > selection.formation_date]
        stock_by_date = stock_prices.set_index("trade_date")

        for horizon in horizons:
            window_dates = future_sessions[:horizon]
            window = stock_by_date.reindex(window_dates).copy()
            observed = len(window_dates)
            quoted_sessions = int(window["adj_close"].notna().sum())
            complete = (
                observed == horizon
                and not window.empty
                and pd.notna(window.iloc[-1]["adj_close"])
            )
            carried_close = (
                pd.to_numeric(window["adj_close"], errors="raise")
                .ffill()
                .fillna(formation_close)
            )
            for column in ("adj_high", "adj_low"):
                values = pd.to_numeric(window[column], errors="raise")
                window[column] = values.where(values.notna(), carried_close)
            window["adj_close"] = carried_close
            target_mask = (window["adj_high"] / formation_close - 1.0) >= target_return
            target_positions = [
                index + 1 for index, touched in enumerate(target_mask.tolist()) if touched
            ]
            first_target = target_positions[0] if target_positions else None
            adverse = window["adj_low"] / formation_close - 1.0

            rows.append(
                {
                    "formation_date": selection.formation_date,
                    "ts_code": selection.ts_code,
                    "policy": selection.policy,
                    "layer": selection.layer,
                    "horizon": horizon,
                    "formation_close": formation_close,
                    "observed_sessions": observed,
                    "quoted_sessions": quoted_sessions,
                    "complete_horizon": complete,
                    "target_touched": bool(first_target is not None),
                    "first_target_session": first_target,
                    "max_favorable_return": _window_return(
                        window, "adj_high", formation_close, "max"
                    ),
                    "max_adverse_return": _window_return(
                        window, "adj_low", formation_close, "min"
                    ),
                    "terminal_return": _terminal_return(window, formation_close),
                    "target_before_drawdown_5": _target_before_drawdown(
                        first_target, adverse, -0.05
                    ),
                    "target_before_drawdown_10": _target_before_drawdown(
                        first_target, adverse, -0.10
                    ),
                }
            )
    return pd.DataFrame(rows)


def summarize_outcomes(outcomes: pd.DataFrame) -> pd.DataFrame:
    """Aggregate complete-horizon outcomes without a composite score."""

    required = {
        "policy",
        "horizon",
        "complete_horizon",
        "target_touched",
        "first_target_session",
        "terminal_return",
        "max_adverse_return",
    }
    missing = sorted(required - set(outcomes.columns))
    if missing:
        raise ValueError(f"outcomes lack required fields: {', '.join(missing)}")

    summaries: list[dict[str, object]] = []
    for (policy, horizon), group in outcomes.groupby(
        ["policy", "horizon"], sort=True, dropna=False
    ):
        complete = group[group["complete_horizon"].astype(bool)]
        hits = complete[complete["target_touched"].astype(bool)]
        summaries.append(
            {
                "policy": policy,
                "horizon": horizon,
                "selections": len(group),
                "complete": len(complete),
                "hits": len(hits),
                "precision": len(hits) / len(complete) if len(complete) else None,
                "median_lead_session": hits["first_target_session"].median()
                if len(hits)
                else None,
                "mean_terminal_return": complete["terminal_return"].mean()
                if len(complete)
                else None,
                "mean_max_adverse_return": complete["max_adverse_return"].mean()
                if len(complete)
                else None,
            }
        )
    return pd.DataFrame(summaries)


def _window_return(
    window: pd.DataFrame,
    column: str,
    formation_close: float,
    operation: str,
) -> float | None:
    if window.empty:
        return None
    values = pd.to_numeric(window[column], errors="raise") / formation_close - 1.0
    return float(values.max() if operation == "max" else values.min())


def _terminal_return(window: pd.DataFrame, formation_close: float) -> float | None:
    if window.empty:
        return None
    return float(window.iloc[-1]["adj_close"] / formation_close - 1.0)


def _target_before_drawdown(
    first_target_session: int | None,
    adverse_returns: pd.Series,
    threshold: float,
) -> bool | None:
    if first_target_session is None:
        return False
    drawdown_positions = [
        index + 1
        for index, value in enumerate(adverse_returns.tolist())
        if value <= threshold
    ]
    if not drawdown_positions:
        return True
    first_drawdown = drawdown_positions[0]
    if first_target_session == first_drawdown:
        return None
    return first_target_session < first_drawdown


__all__ = [
    "compute_forward_outcomes",
    "round_robin_union",
    "select_spaced_origins",
    "summarize_outcomes",
    "validate_formation_cutoff",
]
