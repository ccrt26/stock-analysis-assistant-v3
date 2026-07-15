from __future__ import annotations

from datetime import date, datetime, time
from typing import Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

import pandas as pd

from stock_analyzer.data.research_contracts import ResearchDatasetId
from stock_analyzer.storage.research_query import (
    MaterializedResearchSnapshot,
    ResearchQuery,
)


_HORIZONS = (10, 20, 30)
_LABEL_PREFIXES = (
    "future_",
    "close_return_",
    "market_excess_return_",
    "industry_excess_return_",
    "favorable_excursion_",
    "adverse_excursion_",
    "touch_20pct_",
    "first_touch_20pct_",
    "pre_touch_drawdown_",
)


def adjusted_future_price(
    raw_price: float,
    future_factor: float,
    base_factor: float,
) -> float:
    values = (float(raw_price), float(future_factor), float(base_factor))
    if any(not pd.notna(value) or value <= 0 for value in values):
        raise ValueError("raw price and adjustment factors must be positive")
    return values[0] * values[1] / values[2]


def _normalized_path(
    prices: Sequence[float],
    factors: Sequence[float],
    base_factor: float,
) -> list[float] | None:
    if len(prices) != len(factors):
        raise ValueError("future prices and adjustment factors must have equal length")
    result: list[float] = []
    for raw_price, factor in zip(prices, factors, strict=True):
        try:
            result.append(adjusted_future_price(raw_price, factor, base_factor))
        except (TypeError, ValueError):
            return None
    return result


def label_path(
    *,
    base_close: float,
    future_high: Sequence[float],
    future_close: Sequence[float],
    future_low: Sequence[float] | None = None,
    future_factors: Sequence[float] | None = None,
    base_factor: float = 1.0,
) -> dict[str, float | int | bool | None]:
    if float(base_close) <= 0 or not pd.notna(base_close):
        raise ValueError("base close must be positive")
    if len(future_high) != len(future_close):
        raise ValueError("future high and close paths must have equal length")
    if future_low is not None and len(future_low) != len(future_close):
        raise ValueError("future low and close paths must have equal length")

    factors = (
        [1.0] * len(future_close)
        if future_factors is None
        else list(future_factors)
    )
    highs = _normalized_path(future_high, factors, base_factor)
    closes = _normalized_path(future_close, factors, base_factor)
    lows = (
        None
        if future_low is None
        else _normalized_path(future_low, factors, base_factor)
    )

    labels: dict[str, float | int | bool | None] = {}
    for horizon in _HORIZONS:
        suffix = f"{horizon}d"
        if len(future_close) < horizon or highs is None or closes is None:
            labels[f"close_return_{suffix}"] = None
            labels[f"favorable_excursion_{suffix}"] = None
            labels[f"adverse_excursion_{suffix}"] = None
            labels[f"touch_20pct_{suffix}"] = None
            labels[f"first_touch_20pct_session_{suffix}"] = None
            labels[f"pre_touch_drawdown_{suffix}"] = None
            continue

        horizon_highs = highs[:horizon]
        target = float(base_close) * 1.20
        touch_positions = [
            index + 1
            for index, high in enumerate(horizon_highs)
            if high >= target
        ]
        first_touch = touch_positions[0] if touch_positions else None
        labels[f"close_return_{suffix}"] = (
            closes[horizon - 1] / float(base_close) - 1
        )
        labels[f"favorable_excursion_{suffix}"] = (
            max(horizon_highs) / float(base_close) - 1
        )
        labels[f"adverse_excursion_{suffix}"] = (
            None
            if lows is None
            else min(lows[:horizon]) / float(base_close) - 1
        )
        labels[f"touch_20pct_{suffix}"] = bool(touch_positions)
        labels[f"first_touch_20pct_session_{suffix}"] = first_touch
        labels[f"pre_touch_drawdown_{suffix}"] = (
            None
            if lows is None or first_touch is None
            else min(lows[:first_touch]) / float(base_close) - 1
        )
    return labels


def next_trading_sessions(
    calendar: pd.DataFrame,
    analysis_date: date,
    *,
    count: int,
) -> tuple[date, ...]:
    if count < 0:
        raise ValueError("count must be nonnegative")
    required = {"cal_date", "is_open"}
    missing = required - set(calendar.columns)
    if missing:
        raise ValueError(f"trade calendar missing columns: {sorted(missing)}")
    frame = calendar.copy()
    frame["cal_date"] = pd.to_datetime(frame["cal_date"], errors="raise").dt.date
    opened = frame[frame["is_open"].astype(bool)]
    dates = sorted(set(opened.loc[opened["cal_date"] > analysis_date, "cal_date"]))
    return tuple(dates[:count])


def _active_security_rows(
    securities: pd.DataFrame,
    analysis_date: date,
) -> pd.DataFrame:
    required = {"ts_code", "list_date"}
    missing = required - set(securities.columns)
    if missing:
        raise ValueError(f"security master missing columns: {sorted(missing)}")
    frame = securities.copy()
    frame["list_date"] = pd.to_datetime(frame["list_date"], errors="coerce").dt.date
    delist = pd.to_datetime(frame.get("delist_date"), errors="coerce").dt.date
    active = (frame["list_date"] <= analysis_date) & (
        delist.isna() | (delist > analysis_date)
    )
    if "valid_from" in frame:
        valid_from = pd.to_datetime(frame["valid_from"], errors="coerce").dt.date
        active &= valid_from.isna() | (valid_from <= analysis_date)
    if "valid_to" in frame:
        valid_to = pd.to_datetime(frame["valid_to"], errors="coerce").dt.date
        active &= valid_to.isna() | (valid_to >= analysis_date)
    frame = frame.loc[active].copy()
    sort_columns = ["ts_code"] + (["valid_from"] if "valid_from" in frame else [])
    return frame.sort_values(sort_columns, kind="mergesort").drop_duplicates(
        "ts_code", keep="last"
    )


def eligible_stock_rows(
    securities: pd.DataFrame,
    daily: pd.DataFrame,
    suspensions: pd.DataFrame,
    *,
    analysis_date: date,
) -> pd.DataFrame:
    required = {"ts_code", "trade_date", "close"}
    missing = required - set(daily.columns)
    if missing:
        raise ValueError(f"equity daily missing columns: {sorted(missing)}")
    prices = daily.copy()
    prices["trade_date"] = pd.to_datetime(prices["trade_date"], errors="raise").dt.date
    prices["close"] = pd.to_numeric(prices["close"], errors="coerce")
    prices = prices[
        (prices["trade_date"] == analysis_date)
        & prices["close"].notna()
        & (prices["close"] > 0)
    ]

    active = _active_security_rows(securities, analysis_date)
    result = prices.merge(active, on="ts_code", how="inner", suffixes=("", "_security"))
    if not suspensions.empty:
        if "ts_code" not in suspensions:
            raise ValueError("suspension facts missing ts_code")
        suspended = suspensions.copy()
        if "trade_date" in suspended:
            suspended["trade_date"] = pd.to_datetime(
                suspended["trade_date"], errors="raise"
            ).dt.date
            suspended = suspended[suspended["trade_date"] == analysis_date]
        result = result[~result["ts_code"].isin(set(suspended["ts_code"].astype(str)))]
    return result.sort_values("ts_code", kind="mergesort").reset_index(drop=True)


def analysis_close_as_of(analysis_date: date) -> datetime:
    local = datetime.combine(
        analysis_date,
        time(15, 1),
        tzinfo=ZoneInfo("Asia/Shanghai"),
    )
    return local.astimezone(ZoneInfo("UTC"))


def materialize_signal_snapshot(
    query: ResearchQuery,
    dataset_partitions: Mapping[
        ResearchDatasetId | str,
        Iterable[str] | str,
    ],
    *,
    analysis_date: date,
) -> MaterializedResearchSnapshot:
    return query.materialize_snapshot(
        dataset_partitions,
        as_of=analysis_close_as_of(analysis_date),
    )


def _is_label_column(column: str) -> bool:
    return any(column.startswith(prefix) for prefix in _LABEL_PREFIXES)


def split_signal_and_label_columns(
    panel: pd.DataFrame,
    *,
    identity_columns: tuple[str, ...] = ("ts_code", "analysis_date", "event_date"),
) -> tuple[pd.DataFrame, pd.DataFrame]:
    labels = [column for column in panel if _is_label_column(str(column))]
    identities = [column for column in identity_columns if column in panel]
    signal = panel.drop(columns=labels).copy()
    label_frame = panel.loc[:, identities + labels].copy()
    return signal, label_frame


__all__ = [
    "adjusted_future_price",
    "analysis_close_as_of",
    "eligible_stock_rows",
    "label_path",
    "materialize_signal_snapshot",
    "next_trading_sessions",
    "split_signal_and_label_columns",
]
