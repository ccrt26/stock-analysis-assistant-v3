"""Reveal future price paths for already frozen backtest projects.

This module deliberately accepts frozen membership as input.  It never scans,
ranks, or chooses a security from its future return.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd

from stock_analyzer.evaluation.historical_framework_validation import (
    compute_forward_outcomes,
)


_BASELINE_COLUMNS = {
    "discovery": "discovery_date",
    "action": "action_date",
    "replacement": "replacement_date",
}
_CONTROL_COHORTS = {
    "all_market",
    "matched_market",
    "hotspot_baseline",
    "earnings_baseline",
    "price_baseline",
}
_FUTURE_OUTCOME_FIELDS = {
    "complete_horizon",
    "first_target_date",
    "first_target_session",
    "future_return",
    "max_adverse_return",
    "max_favorable_return",
    "target_touched",
    "terminal_return",
}
_FUTURE_OUTCOME_TOKENS = (
    "future",
    "outcome",
    "target_touched",
    "terminal_return",
    "max_favorable",
    "max_adverse",
    "first_target",
)


def evaluate_frozen_projects(
    prices: pd.DataFrame,
    projects: pd.DataFrame | Sequence[Any],
    *,
    controls: pd.DataFrame | Sequence[Any] | None = None,
    market_prices: pd.DataFrame | None = None,
    industry_prices: pd.DataFrame | None = None,
    horizons: tuple[int, ...] = (10, 20, 30),
    target_return: float = 0.20,
) -> pd.DataFrame:
    """Evaluate discovery, action, and replacement paths after formation freeze.

    ``controls`` are precomputed membership rows.  In particular, a
    ``matched_market`` row is accepted only when its discovery date and listed
    board match an actual frozen project.  Outcome fields are forbidden in the
    control input so this reveal step cannot silently select winners.
    """

    frozen_projects = _normalise_members(projects, controls=False)
    frozen_controls = (
        _normalise_members(controls, controls=True)
        if controls is not None
        else pd.DataFrame()
    )
    _validate_controls(frozen_projects, frozen_controls)

    members = pd.concat([frozen_projects, frozen_controls], ignore_index=True)
    evaluations = _expand_baselines(members)
    if evaluations.empty:
        return pd.DataFrame()

    prepared_prices = _prepare_prices(prices)
    prepared_market = _prepare_benchmark(market_prices, key_column=None)
    prepared_industry = _prepare_benchmark(
        industry_prices, key_column="industry"
    )
    calendar_prices = _add_calendar_carrier(prepared_prices, prepared_market)

    selections = evaluations[
        ["baseline_date", "ts_code", "_evaluation_id", "layer"]
    ].rename(
        columns={
            "baseline_date": "formation_date",
            "_evaluation_id": "policy",
        }
    )
    raw = compute_forward_outcomes(
        calendar_prices,
        selections,
        horizons=horizons,
        target_return=target_return,
    ).rename(
        columns={
            "policy": "_evaluation_id",
            "formation_close": "baseline_close",
        }
    )
    evaluation_metadata = evaluations.drop(columns=["ts_code"])
    raw = raw.drop(columns=["layer"]).merge(
        evaluation_metadata,
        on="_evaluation_id",
        how="left",
        validate="many_to_one",
    )

    sessions = pd.Index(
        sorted(calendar_prices["trade_date"].dropna().unique()),
        name="trade_date",
    )
    stock_quotes = prepared_prices.set_index(["ts_code", "trade_date"])
    rows: list[dict[str, object]] = []
    for record in raw.to_dict("records"):
        baseline_date = pd.Timestamp(record["baseline_date"])
        future = sessions[sessions > baseline_date]
        horizon = int(record["horizon"])
        endpoint = pd.Timestamp(future[horizon - 1]) if len(future) >= horizon else None
        record["endpoint_date"] = endpoint
        first_session = record.get("first_target_session")
        record["first_target_date"] = (
            pd.Timestamp(future[int(first_session) - 1])
            if pd.notna(first_session) and int(first_session) <= len(future)
            else pd.NaT
        )

        endpoint_quoted = False
        if endpoint is not None and (record["ts_code"], endpoint) in stock_quotes.index:
            endpoint_close = stock_quotes.loc[(record["ts_code"], endpoint), "adj_close"]
            if isinstance(endpoint_close, pd.Series):
                raise ValueError("prices contain duplicate stock-date rows")
            endpoint_quoted = pd.notna(endpoint_close)
        complete = bool(record["complete_horizon"]) and endpoint_quoted
        record["complete_horizon"] = complete
        if not complete:
            record["terminal_return"] = None
            record["market_relative_return"] = None
            record["industry_relative_return"] = None
        else:
            terminal = float(record["terminal_return"])
            market_return = _benchmark_return(
                prepared_market,
                baseline_date=baseline_date,
                endpoint_date=endpoint,
                key_column=None,
                key=None,
            )
            industry_return = _benchmark_return(
                prepared_industry,
                baseline_date=baseline_date,
                endpoint_date=endpoint,
                key_column="industry",
                key=record.get("industry"),
            )
            record["market_relative_return"] = (
                terminal - market_return if market_return is not None else None
            )
            record["industry_relative_return"] = (
                terminal - industry_return if industry_return is not None else None
            )
        rows.append(record)

    result = pd.DataFrame(rows)
    preferred = [
        "project_id",
        "ts_code",
        "policy",
        "cohort",
        "layer",
        "industry",
        "listing_board",
        "baseline_type",
        "baseline_date",
        "baseline_close",
        "horizon",
        "endpoint_date",
        "complete_horizon",
        "observed_sessions",
        "quoted_sessions",
        "target_touched",
        "first_target_session",
        "first_target_date",
        "max_favorable_return",
        "max_adverse_return",
        "terminal_return",
        "target_before_drawdown_5",
        "target_before_drawdown_10",
        "market_relative_return",
        "industry_relative_return",
    ]
    return result[[column for column in preferred if column in result.columns]]


def _normalise_members(
    values: pd.DataFrame | Sequence[Any] | None,
    *,
    controls: bool,
) -> pd.DataFrame:
    if isinstance(values, pd.DataFrame):
        frame = values.copy()
    else:
        records = []
        for value in values or ():
            if hasattr(value, "model_dump"):
                records.append(value.model_dump(mode="python"))
            elif isinstance(value, dict):
                records.append(value)
            else:
                raise TypeError("frozen members must be a DataFrame, mapping, or model")
        frame = pd.DataFrame(records)
    if frame.empty:
        return frame

    aliases = {"security_id": "ts_code", "formation_date": "discovery_date"}
    for source, target in aliases.items():
        if target not in frame and source in frame:
            frame[target] = frame[source]
    required = {"project_id", "ts_code", "discovery_date"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"frozen members lack required fields: {', '.join(missing)}")
    if frame["project_id"].astype(str).duplicated().any():
        raise ValueError("frozen project_id values must be unique")
    frame["project_id"] = frame["project_id"].astype(str)
    frame["ts_code"] = frame["ts_code"].astype(str)
    for column in _BASELINE_COLUMNS.values():
        if column in frame:
            frame[column] = pd.to_datetime(frame[column], errors="raise").dt.normalize()
    defaults: dict[str, object] = {
        "policy": "frozen_control" if controls else "frozen_project",
        "cohort": "all_market" if controls else "complete_mechanism",
        "layer": "baseline" if controls else "candidate",
        "industry": None,
        "listing_board": None,
    }
    for column, default in defaults.items():
        if column not in frame:
            frame[column] = default
    return frame


def _validate_controls(projects: pd.DataFrame, controls: pd.DataFrame) -> None:
    if controls.empty:
        return
    leaked = sorted(
        column
        for column in controls.columns
        if column in _FUTURE_OUTCOME_FIELDS
        or any(token in column.lower() for token in _FUTURE_OUTCOME_TOKENS)
    )
    if leaked:
        raise ValueError(
            "frozen controls contain future outcome fields: " + ", ".join(leaked)
        )
    unknown = sorted(set(controls["cohort"].astype(str)) - _CONTROL_COHORTS)
    if unknown:
        raise ValueError("unknown frozen control cohort: " + ", ".join(unknown))
    if "eligible" not in controls:
        raise ValueError("control eligibility must be literal boolean true")
    eligibility = controls["eligible"]
    literal_booleans = eligibility.map(
        lambda value: isinstance(value, (bool, np.bool_))
    )
    if not literal_booleans.all() or not eligibility.map(bool).all():
        raise ValueError("control eligibility must be literal boolean true")

    matched = controls[controls["cohort"].astype(str) == "matched_market"]
    if matched.empty:
        matched_keys: set[tuple[object, ...]] = set()
    else:
        if projects["listing_board"].isna().any() or matched[
            "listing_board"
        ].isna().any():
            raise ValueError("matched controls require listing_board")
        project_keys = set(
            zip(projects["discovery_date"], projects["listing_board"], strict=False)
        )
        matched_board_keys = set(
            zip(matched["discovery_date"], matched["listing_board"], strict=False)
        )
        if not matched_board_keys.issubset(project_keys):
            raise ValueError(
                "matched controls must use same-date and same-board membership"
            )
        matched_keys = _scope_keys(matched)

    all_market = controls[controls["cohort"].astype(str) == "all_market"]
    scoped = controls[
        controls["cohort"].astype(str).isin(
            {
                "matched_market",
                "hotspot_baseline",
                "earnings_baseline",
                "price_baseline",
            }
        )
    ]
    scoped_keys = _scope_keys(scoped) | matched_keys
    if not scoped_keys.issubset(_scope_keys(all_market)):
        raise ValueError(
            "matched and transparent baselines must belong to the eligible all-market scope"
        )


def _scope_keys(frame: pd.DataFrame) -> set[tuple[object, ...]]:
    return set(
        zip(
            frame["discovery_date"],
            frame["ts_code"],
            frame["listing_board"],
            strict=False,
        )
    )


def _expand_baselines(members: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for member in members.to_dict("records"):
        is_control = str(member.get("cohort")) in _CONTROL_COHORTS
        for baseline_type, column in _BASELINE_COLUMNS.items():
            if is_control and baseline_type != "discovery":
                continue
            value = member.get(column)
            if value is None or pd.isna(value):
                continue
            row = dict(member)
            row["baseline_type"] = baseline_type
            row["baseline_date"] = pd.Timestamp(value).normalize()
            row["_evaluation_id"] = f"{member['project_id']}::{baseline_type}"
            rows.append(row)
    return pd.DataFrame(rows)


def _prepare_prices(prices: pd.DataFrame) -> pd.DataFrame:
    required = {"trade_date", "ts_code", "adj_close", "adj_high", "adj_low"}
    missing = sorted(required - set(prices.columns))
    if missing:
        raise ValueError(f"prices lack required fields: {', '.join(missing)}")
    prepared = prices.copy()
    prepared["trade_date"] = pd.to_datetime(
        prepared["trade_date"], errors="raise"
    ).dt.normalize()
    prepared["ts_code"] = prepared["ts_code"].astype(str)
    if prepared.duplicated(["trade_date", "ts_code"]).any():
        raise ValueError("prices contain duplicate stock-date rows")
    return prepared


def _prepare_benchmark(
    values: pd.DataFrame | None,
    *,
    key_column: str | None,
) -> pd.DataFrame | None:
    if values is None:
        return None
    required = {"trade_date", "adj_close"}
    if key_column:
        required.add(key_column)
    missing = sorted(required - set(values.columns))
    if missing:
        raise ValueError(f"benchmark lacks required fields: {', '.join(missing)}")
    prepared = values.copy()
    prepared["trade_date"] = pd.to_datetime(
        prepared["trade_date"], errors="raise"
    ).dt.normalize()
    keys = ["trade_date"] if key_column is None else [key_column, "trade_date"]
    if prepared.duplicated(keys).any():
        raise ValueError("benchmark contains duplicate key-date rows")
    prepared["adj_close"] = pd.to_numeric(prepared["adj_close"], errors="raise")
    return prepared


def _add_calendar_carrier(
    prices: pd.DataFrame,
    market_prices: pd.DataFrame | None,
) -> pd.DataFrame:
    if market_prices is None:
        return prices
    carrier = pd.DataFrame(
        {
            "trade_date": market_prices["trade_date"],
            "ts_code": "__MARKET_CALENDAR__",
            "adj_close": 1.0,
            "adj_high": 1.0,
            "adj_low": 1.0,
        }
    )
    return pd.concat([prices, carrier], ignore_index=True)


def _benchmark_return(
    values: pd.DataFrame | None,
    *,
    baseline_date: pd.Timestamp,
    endpoint_date: pd.Timestamp | None,
    key_column: str | None,
    key: object,
) -> float | None:
    if values is None or endpoint_date is None:
        return None
    subset = values
    if key_column is not None:
        if key is None or pd.isna(key):
            return None
        subset = subset[subset[key_column] == key]
    indexed = subset.set_index("trade_date")["adj_close"]
    if baseline_date not in indexed.index or endpoint_date not in indexed.index:
        return None
    start = indexed.loc[baseline_date]
    end = indexed.loc[endpoint_date]
    if pd.isna(start) or pd.isna(end) or float(start) <= 0:
        return None
    return float(end) / float(start) - 1.0


__all__ = ["evaluate_frozen_projects"]
