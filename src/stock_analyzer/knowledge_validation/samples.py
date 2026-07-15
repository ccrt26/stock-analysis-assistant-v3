from __future__ import annotations

from datetime import date, datetime, time
from typing import Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from stock_analyzer.data.research_contracts import ResearchDatasetId
from stock_analyzer.knowledge_validation.models import StudySample, ValidationSpec
from stock_analyzer.knowledge_validation.signals import map_announcement_sessions
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

_PRICE_STUDIES = {
    "a_share_size_value",
    "a_share_momentum_reversal",
    "price_limit_t_plus_one",
    "a_share_factor_industry_momentum",
    "overseas_industry_momentum_method",
    "formal_announcement_price_reaction",
}

_HISTORICAL_DATE_DATASETS = {
    ResearchDatasetId.EQUITY_DAILY,
    ResearchDatasetId.ADJ_FACTOR,
    ResearchDatasetId.INDEX_DAILY,
    ResearchDatasetId.INDUSTRY_DAILY,
}

_CURRENT_DATE_DATASETS = {
    ResearchDatasetId.DAILY_BASIC,
    ResearchDatasetId.STOCK_LIMIT,
    ResearchDatasetId.SUSPENSION,
}


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
    for auxiliary_horizon in (1, 5):
        labels[f"close_return_{auxiliary_horizon}d"] = (
            None
            if len(future_close) < auxiliary_horizon or closes is None
            else closes[auxiliary_horizon - 1] / float(base_close) - 1
        )
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
    analysis_timestamp = pd.Timestamp(analysis_date)
    frame["list_date"] = pd.to_datetime(frame["list_date"], errors="coerce")
    delist = pd.to_datetime(frame.get("delist_date"), errors="coerce")
    active = (frame["list_date"] <= analysis_timestamp) & (
        delist.isna() | (delist > analysis_timestamp)
    )
    if "valid_from" in frame:
        valid_from = pd.to_datetime(frame["valid_from"], errors="coerce")
        active &= valid_from.isna() | (valid_from <= analysis_timestamp)
    if "valid_to" in frame:
        valid_to = pd.to_datetime(frame["valid_to"], errors="coerce")
        active &= valid_to.isna() | (valid_to >= analysis_timestamp)
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


def _manifest_partitions(
    query: ResearchQuery,
    dataset_id: ResearchDatasetId,
) -> tuple[str, ...]:
    manifest = query.warehouse.partition_manifest(dataset_id)
    if manifest.empty or "partition_value" not in manifest:
        return ()
    return tuple(sorted(set(manifest["partition_value"].astype(str))))


def _requested_signal_partitions(
    spec: ValidationSpec,
    query: ResearchQuery,
    *,
    history_dates: tuple[date, ...],
    analysis_date: date,
) -> dict[ResearchDatasetId, tuple[str, ...]]:
    requested: dict[ResearchDatasetId, tuple[str, ...]] = {}
    history_values = tuple(item.isoformat() for item in history_dates)
    for raw_dataset in spec.required_datasets:
        dataset = ResearchDatasetId(raw_dataset)
        available = set(_manifest_partitions(query, dataset))
        if dataset in _HISTORICAL_DATE_DATASETS:
            selected = tuple(item for item in history_values if item in available)
        elif dataset in _CURRENT_DATE_DATASETS:
            selected = (
                (analysis_date.isoformat(),)
                if analysis_date.isoformat() in available
                else ()
            )
        else:
            selected = tuple(sorted(available))
        if selected:
            requested[dataset] = selected
    return requested


def _requested_label_partitions(
    query: ResearchQuery,
    future_dates: tuple[date, ...],
    *,
    include_industry: bool,
) -> dict[ResearchDatasetId, tuple[str, ...]]:
    datasets = [
        ResearchDatasetId.EQUITY_DAILY,
        ResearchDatasetId.ADJ_FACTOR,
        ResearchDatasetId.INDEX_DAILY,
    ]
    if include_industry:
        datasets.append(ResearchDatasetId.INDUSTRY_DAILY)
    values = tuple(item.isoformat() for item in future_dates)
    requested: dict[ResearchDatasetId, tuple[str, ...]] = {}
    for dataset in datasets:
        available = set(_manifest_partitions(query, dataset))
        selected = tuple(item for item in values if item in available)
        if selected:
            requested[dataset] = selected
    return requested


def _merge_current_facts(
    eligible: pd.DataFrame,
    snapshot: MaterializedResearchSnapshot,
    requested: Mapping[ResearchDatasetId, tuple[str, ...]],
    analysis_date: date,
) -> pd.DataFrame:
    out = eligible.copy()
    for dataset, value_column in (
        (ResearchDatasetId.ADJ_FACTOR, "adj_factor"),
        (ResearchDatasetId.DAILY_BASIC, None),
        (ResearchDatasetId.STOCK_LIMIT, None),
    ):
        if dataset not in requested:
            continue
        frame = snapshot.frame(dataset)
        if frame.empty:
            continue
        if "trade_date" in frame:
            dates = pd.to_datetime(frame["trade_date"], errors="raise").dt.date
            frame = frame.loc[dates == analysis_date].copy()
        keep = [
            column
            for column in frame.columns
            if column == "ts_code"
            or (value_column is not None and column == value_column)
            or (
                value_column is None
                and column
                not in {
                    "trade_date",
                    "close",
                    "source_name",
                    "source_endpoint",
                    "source_record_id",
                    "source_updated_at",
                    "available_at",
                    "availability_precision",
                    "ingested_at",
                    "ingestion_run_id",
                    "payload_hash",
                    "business_key_hash",
                    "quality_status",
                    "revision_no",
                }
            )
        ]
        out = out.merge(frame[keep], on="ts_code", how="left", validate="one_to_one")
    return out


def _add_prior_return(
    current: pd.DataFrame,
    snapshot: MaterializedResearchSnapshot,
    requested: Mapping[ResearchDatasetId, tuple[str, ...]],
    history_dates: tuple[date, ...],
) -> pd.DataFrame:
    out = current.copy()
    out["prior_return_20d"] = np.nan
    if (
        ResearchDatasetId.EQUITY_DAILY not in requested
        or ResearchDatasetId.ADJ_FACTOR not in requested
        or len(history_dates) < 21
    ):
        return out
    prices = snapshot.frame(ResearchDatasetId.EQUITY_DAILY)
    factors = snapshot.frame(ResearchDatasetId.ADJ_FACTOR)
    history = prices.merge(
        factors[["trade_date", "ts_code", "adj_factor"]],
        on=["trade_date", "ts_code"],
        how="inner",
        validate="one_to_one",
    )
    history["trade_date"] = pd.to_datetime(history["trade_date"], errors="raise").dt.date
    first_date = history_dates[0]
    current_date = history_dates[-1]
    first = history[history["trade_date"] == first_date][
        ["ts_code", "close", "adj_factor"]
    ].rename(columns={"close": "prior_close", "adj_factor": "prior_factor"})
    last = history[history["trade_date"] == current_date][
        ["ts_code", "close", "adj_factor"]
    ].rename(columns={"close": "current_close", "adj_factor": "current_factor"})
    comparison = first.merge(last, on="ts_code", how="inner", validate="one_to_one")
    comparison["prior_return_20d"] = (
        comparison["current_close"]
        / (
            comparison["prior_close"]
            * comparison["prior_factor"]
            / comparison["current_factor"]
        )
        - 1
    )
    return out.merge(
        comparison[["ts_code", "prior_return_20d"]],
        on="ts_code",
        how="left",
        suffixes=("", "_computed"),
        validate="one_to_one",
    ).assign(
        prior_return_20d=lambda frame: frame.pop("prior_return_20d_computed").combine_first(
            frame["prior_return_20d"]
        )
    )


def _future_stock_labels(
    current: pd.DataFrame,
    snapshot: MaterializedResearchSnapshot,
    requested: Mapping[ResearchDatasetId, tuple[str, ...]],
    analysis_date: date,
) -> pd.DataFrame:
    identity = current[["ts_code"]].copy()
    identity.insert(0, "analysis_date", analysis_date)
    if (
        ResearchDatasetId.EQUITY_DAILY not in requested
        or ResearchDatasetId.ADJ_FACTOR not in requested
    ):
        return identity
    prices = snapshot.frame(ResearchDatasetId.EQUITY_DAILY)
    factors = snapshot.frame(ResearchDatasetId.ADJ_FACTOR)
    future = prices.merge(
        factors[["trade_date", "ts_code", "adj_factor"]],
        on=["trade_date", "ts_code"],
        how="inner",
        validate="one_to_one",
    )
    future["trade_date"] = pd.to_datetime(future["trade_date"], errors="raise")
    future = future.sort_values(["ts_code", "trade_date"], kind="mergesort")
    indexes = (
        snapshot.frame(ResearchDatasetId.INDEX_DAILY)
        if ResearchDatasetId.INDEX_DAILY in requested
        else pd.DataFrame()
    )
    if not indexes.empty:
        indexes["trade_date"] = pd.to_datetime(indexes["trade_date"], errors="raise")
        indexes = indexes.sort_values(["index_code", "trade_date"], kind="mergesort")
    base = current.set_index("ts_code")
    rows: list[dict[str, object]] = []
    for ts_code in identity["ts_code"]:
        path = future[future["ts_code"].astype(str) == str(ts_code)]
        base_factor = base.loc[ts_code, "adj_factor"] if "adj_factor" in base else 1.0
        labels = label_path(
            base_close=float(base.loc[ts_code, "close"]),
            future_high=path["high"].tolist(),
            future_close=path["close"].tolist(),
            future_low=path["low"].tolist() if "low" in path else None,
            future_factors=path["adj_factor"].tolist(),
            base_factor=float(base_factor),
        )
        index_code = (
            base.loc[ts_code, "market_index_code"]
            if "market_index_code" in base
            else None
        )
        market_path = (
            indexes[indexes["index_code"].astype(str) == str(index_code)]
            if index_code is not None and not indexes.empty
            else pd.DataFrame()
        )
        market_base = (
            float(base.loc[ts_code, "market_base_close"])
            if "market_base_close" in base and pd.notna(base.loc[ts_code, "market_base_close"])
            else None
        )
        for horizon in (1, 5, 10, 20, 30):
            market_return = (
                None
                if market_base is None or len(market_path) < horizon
                else float(market_path.iloc[horizon - 1]["close"]) / market_base - 1
            )
            labels[f"market_return_{horizon}d"] = market_return
            close_return = labels.get(f"close_return_{horizon}d")
            labels[f"market_excess_return_{horizon}d"] = (
                None
                if close_return is None or market_return is None
                else float(close_return) - market_return
            )
        rows.append({"analysis_date": analysis_date, "ts_code": ts_code, **labels})
    return pd.DataFrame(rows)


def _attach_market_benchmark(
    current: pd.DataFrame,
    snapshot: MaterializedResearchSnapshot,
    analysis_date: date,
) -> pd.DataFrame:
    out = current.copy()

    def benchmark(row: pd.Series) -> str:
        exchange = str(row.get("exchange", ""))
        market = str(row.get("market", ""))
        if exchange == "BSE":
            return "899050.BJ"
        if exchange == "SSE" and market == "科创板":
            return "000688.SH"
        if exchange == "SSE":
            return "000001.SH"
        if exchange == "SZSE" and market == "创业板":
            return "399006.SZ"
        return "399001.SZ"

    out["market_index_code"] = out.apply(benchmark, axis=1)
    indexes = snapshot.frame(ResearchDatasetId.INDEX_DAILY)
    if indexes.empty:
        out["market_base_close"] = np.nan
        return out
    dates = pd.to_datetime(indexes["trade_date"], errors="raise").dt.date
    base = indexes.loc[dates == analysis_date, ["index_code", "close"]].rename(
        columns={"index_code": "market_index_code", "close": "market_base_close"}
    )
    return out.merge(base, on="market_index_code", how="left", validate="many_to_one")


def _active_level_one_members(
    members: pd.DataFrame,
    analysis_date: date,
) -> pd.DataFrame:
    if members.empty:
        return members
    required = {"ts_code", "industry_code", "level"}
    missing = required - set(members.columns)
    if missing:
        raise ValueError(f"industry membership missing columns: {sorted(missing)}")
    out = members[members["level"].astype(str) == "L1"].copy()
    point = pd.Timestamp(analysis_date)
    if "valid_from" in out:
        valid_from = pd.to_datetime(out["valid_from"], errors="coerce")
        out = out[valid_from.isna() | (valid_from <= point)]
    if "valid_to" in out:
        valid_to = pd.to_datetime(out["valid_to"], errors="coerce")
        out = out[valid_to.isna() | (valid_to >= point)]
    return out.sort_values(["ts_code", "industry_code"], kind="mergesort").drop_duplicates(
        "ts_code", keep="last"
    )


def _industry_context_inputs(
    current: pd.DataFrame,
    snapshot: MaterializedResearchSnapshot,
    history_dates: tuple[date, ...],
    analysis_date: date,
    *,
    industry_units: bool,
) -> pd.DataFrame:
    members = _active_level_one_members(
        snapshot.frame(ResearchDatasetId.INDUSTRY_MEMBER), analysis_date
    )
    industry = snapshot.frame(ResearchDatasetId.INDUSTRY_DAILY)
    industry["trade_date"] = pd.to_datetime(industry["trade_date"], errors="raise").dt.date
    first = industry[industry["trade_date"] == history_dates[0]][
        ["industry_code", "close"]
    ].rename(columns={"close": "industry_prior_close"})
    last = industry[industry["trade_date"] == history_dates[-1]][
        ["industry_code", "close"]
    ].rename(columns={"close": "industry_close"})
    returns = first.merge(last, on="industry_code", how="inner", validate="one_to_one")
    returns["industry_return_20d"] = (
        returns["industry_close"] / returns["industry_prior_close"] - 1
    )
    stock = current.merge(
        members[["ts_code", "industry_code"]],
        on="ts_code",
        how="inner",
        validate="one_to_one",
    ).merge(
        returns[["industry_code", "industry_return_20d"]],
        on="industry_code",
        how="inner",
        validate="many_to_one",
    )
    if not industry_units:
        return stock

    def concentration(values: pd.Series) -> float:
        positive = pd.to_numeric(values, errors="coerce").dropna()
        positive = positive[positive > 0].sort_values(ascending=False)
        if positive.empty or float(positive.sum()) <= 0:
            return 0.0
        return float(positive.head(5).sum() / positive.sum())

    breadth = (
        stock.groupby("industry_code", sort=True)["prior_return_20d"]
        .agg(
            breadth_20d=lambda values: float(
                (pd.to_numeric(values, errors="coerce") > 0).mean()
            ),
            top_contribution_share_20d=concentration,
        )
        .reset_index()
    )
    market_return = float(returns["industry_return_20d"].mean())
    panel = returns.merge(breadth, on="industry_code", how="left", validate="one_to_one")
    panel.insert(0, "analysis_date", analysis_date)
    panel["market_return_20d"] = market_return
    return panel


def _future_industry_labels(
    current: pd.DataFrame,
    snapshot: MaterializedResearchSnapshot,
    analysis_date: date,
) -> pd.DataFrame:
    future = snapshot.frame(ResearchDatasetId.INDUSTRY_DAILY)
    future["trade_date"] = pd.to_datetime(future["trade_date"], errors="raise")
    future = future.sort_values(["industry_code", "trade_date"], kind="mergesort")
    base = current.set_index("industry_code")
    rows: list[dict[str, object]] = []
    for industry_code in current["industry_code"]:
        path = future[future["industry_code"].astype(str) == str(industry_code)]
        labels = label_path(
            base_close=float(base.loc[industry_code, "industry_close"]),
            future_high=path["high"].tolist(),
            future_close=path["close"].tolist(),
            future_low=path["low"].tolist() if "low" in path else None,
        )
        rows.append(
            {
                "analysis_date": analysis_date,
                "industry_code": industry_code,
                **labels,
            }
        )
    return pd.DataFrame(rows)


def _build_price_study_sample(
    spec: ValidationSpec,
    query: ResearchQuery,
) -> StudySample:
    equity_partitions = _manifest_partitions(query, ResearchDatasetId.EQUITY_DAILY)
    sessions = tuple(date.fromisoformat(value) for value in equity_partitions)
    if spec.study_id in {
        "a_share_factor_industry_momentum",
        "overseas_industry_momentum_method",
    }:
        industry_dates = set(
            _manifest_partitions(query, ResearchDatasetId.INDUSTRY_DAILY)
        )
        sessions = tuple(item for item in sessions if item.isoformat() in industry_dates)
    analysis_dates = sessions[20:-30] if len(sessions) >= 51 else ()
    announcement_partitions = (
        _manifest_partitions(query, ResearchDatasetId.ANNOUNCEMENT)
        if spec.study_id == "formal_announcement_price_reaction"
        else ()
    )
    if announcement_partitions:
        analysis_dates = tuple(
            item for item in analysis_dates if item.strftime("%Y-%m") in announcement_partitions
        )
    signal_frames: list[pd.DataFrame] = []
    label_frames: list[pd.DataFrame] = []
    input_hashes: list[str] = []
    label_hashes: list[str] = []
    exclusions = {"not_eligible_on_analysis_date": 0}

    for analysis_date in analysis_dates:
        position = sessions.index(analysis_date)
        history_dates = sessions[position - 20 : position + 1]
        future_dates = sessions[position + 1 : position + 31]
        signal_request = _requested_signal_partitions(
            spec,
            query,
            history_dates=history_dates,
            analysis_date=analysis_date,
        )
        if spec.study_id == "formal_announcement_price_reaction":
            signal_request[ResearchDatasetId.ANNOUNCEMENT] = (
                analysis_date.strftime("%Y-%m"),
            )
        signal_snapshot = materialize_signal_snapshot(
            query,
            signal_request,
            analysis_date=analysis_date,
        )
        input_hashes.append(signal_snapshot.input_manifest["input_manifest_hash"])
        daily = signal_snapshot.frame(ResearchDatasetId.EQUITY_DAILY)
        securities = signal_snapshot.frame(ResearchDatasetId.SECURITY_MASTER)
        suspensions = (
            signal_snapshot.frame(ResearchDatasetId.SUSPENSION)
            if ResearchDatasetId.SUSPENSION in signal_request
            else pd.DataFrame()
        )
        current_daily = daily[
            pd.to_datetime(daily["trade_date"], errors="raise").dt.date
            == analysis_date
        ].copy()
        eligible = eligible_stock_rows(
            securities,
            current_daily,
            suspensions,
            analysis_date=analysis_date,
        )
        if "volume" in eligible:
            volume = pd.to_numeric(eligible["volume"], errors="coerce")
            eligible = eligible[volume.notna() & (volume > 0)].copy()
        exclusions["not_eligible_on_analysis_date"] += max(
            0, len(current_daily) - len(eligible)
        )
        current = _merge_current_facts(
            eligible,
            signal_snapshot,
            signal_request,
            analysis_date,
        )
        current.insert(0, "analysis_date", analysis_date)
        current = _add_prior_return(
            current,
            signal_snapshot,
            signal_request,
            history_dates,
        )
        current = _attach_market_benchmark(current, signal_snapshot, analysis_date)
        if spec.study_id == "formal_announcement_price_reaction":
            factors = signal_snapshot.frame(ResearchDatasetId.ADJ_FACTOR)
            indexes = signal_snapshot.frame(ResearchDatasetId.INDEX_DAILY)
            previous_date = history_dates[-2]
            current["stock_return_0"] = current["ts_code"].map(
                lambda code: _return_between_sessions(
                    daily,
                    factors,
                    code_column="ts_code",
                    code=str(code),
                    previous_date=previous_date,
                    current_date=analysis_date,
                )
            )
            current["market_return_0"] = current["market_index_code"].map(
                lambda code: _return_between_sessions(
                    indexes,
                    pd.DataFrame(),
                    code_column="index_code",
                    code=str(code),
                    previous_date=previous_date,
                    current_date=analysis_date,
                )
            )
            current["market_adjusted_return"] = (
                current["stock_return_0"] - current["market_return_0"]
            )
            calendar = pd.DataFrame({"cal_date": sessions, "is_open": True})
            announcements = map_announcement_sessions(
                signal_snapshot.frame(ResearchDatasetId.ANNOUNCEMENT), calendar
            )
            matched = set(
                announcements.loc[
                    announcements["event_date"] == analysis_date, "ts_code"
                ].astype(str)
            )
            current["local_formal_announcement_match"] = current[
                "ts_code"
            ].astype(str).isin(matched)
        industry_units = spec.study_id == "a_share_factor_industry_momentum"
        if spec.study_id in {
            "a_share_factor_industry_momentum",
            "overseas_industry_momentum_method",
        }:
            current = _industry_context_inputs(
                current,
                signal_snapshot,
                history_dates,
                analysis_date,
                industry_units=industry_units,
            )

        label_request = _requested_label_partitions(
            query,
            future_dates,
            include_industry=(ResearchDatasetId.INDUSTRY_DAILY in signal_request),
        )
        label_snapshot = query.materialize_snapshot(
            label_request,
            as_of=analysis_close_as_of(future_dates[-1]),
        )
        label_hashes.append(label_snapshot.input_manifest["input_manifest_hash"])
        labels = (
            _future_industry_labels(current, label_snapshot, analysis_date)
            if industry_units
            else _future_stock_labels(
                current,
                label_snapshot,
                label_request,
                analysis_date,
            )
        )
        signal_frames.append(current)
        label_frames.append(labels)

    signal_inputs = (
        pd.concat(signal_frames, ignore_index=True) if signal_frames else pd.DataFrame()
    )
    future_labels = (
        pd.concat(label_frames, ignore_index=True) if label_frames else pd.DataFrame()
    )
    return StudySample(
        study_id=spec.study_id,
        input_manifest_hashes=tuple(input_hashes),
        label_manifest_hashes=tuple(label_hashes),
        analysis_dates=tuple(analysis_dates),
        panel_row_count=len(signal_inputs),
        exclusion_counts=exclusions,
        signal_inputs=signal_inputs,
        future_labels=future_labels,
    )


def _return_between_sessions(
    frame: pd.DataFrame,
    factors: pd.DataFrame,
    *,
    code_column: str,
    code: str,
    previous_date: date,
    current_date: date,
) -> float | None:
    selected = frame[frame[code_column].astype(str) == str(code)].copy()
    selected["trade_date"] = pd.to_datetime(selected["trade_date"], errors="raise").dt.date
    previous = selected[selected["trade_date"] == previous_date]
    current = selected[selected["trade_date"] == current_date]
    if previous.empty or current.empty:
        return None
    if code_column == "ts_code":
        adjusted = factors[factors["ts_code"].astype(str) == str(code)].copy()
        adjusted["trade_date"] = pd.to_datetime(
            adjusted["trade_date"], errors="raise"
        ).dt.date
        prior_factor = adjusted.loc[
            adjusted["trade_date"] == previous_date, "adj_factor"
        ]
        current_factor = adjusted.loc[
            adjusted["trade_date"] == current_date, "adj_factor"
        ]
        if prior_factor.empty or current_factor.empty:
            return None
        comparable_previous = (
            float(previous.iloc[0]["close"])
            * float(prior_factor.iloc[0])
            / float(current_factor.iloc[0])
        )
    else:
        comparable_previous = float(previous.iloc[0]["close"])
    return float(current.iloc[0]["close"]) / comparable_previous - 1


def _normalized_event_facts(
    snapshot: MaterializedResearchSnapshot,
    spec: ValidationSpec,
    calendar: pd.DataFrame,
) -> pd.DataFrame:
    if spec.study_id == "daily_event_study":
        frame = snapshot.frame(ResearchDatasetId.ANNOUNCEMENT).copy()
        frame = frame.rename(columns={"announcement_id": "event_id"})
        return map_announcement_sessions(frame, calendar)
    rows: list[pd.DataFrame] = []
    for dataset, prefix in (
        (ResearchDatasetId.EARNINGS_FORECAST, "forecast"),
        (ResearchDatasetId.EARNINGS_EXPRESS, "express"),
    ):
        try:
            frame = snapshot.frame(dataset)
        except KeyError:
            continue
        if frame.empty:
            continue
        out = frame.copy()
        available = pd.to_datetime(out["available_at"], utc=True, errors="coerce")
        fallback = pd.to_datetime(out["ann_date"], errors="coerce").dt.tz_localize(
            "Asia/Shanghai"
        )
        out["announcement_time"] = available.combine_first(fallback)
        identifiers = (
            out["source_record_id"].astype(str)
            if "source_record_id" in out
            else (
                out["ts_code"].astype(str)
                + ":"
                + out["report_period"].astype(str)
                + ":"
                + out["ann_date"].astype(str)
            )
        )
        out["event_id"] = prefix + ":" + identifiers
        rows.append(out)
    if not rows:
        return pd.DataFrame(columns=["event_id", "ts_code", "announcement_time", "event_date"])
    return map_announcement_sessions(pd.concat(rows, ignore_index=True), calendar)


def _build_daily_event_sample(
    spec: ValidationSpec,
    query: ResearchQuery,
) -> StudySample:
    sessions = tuple(
        date.fromisoformat(value)
        for value in _manifest_partitions(query, ResearchDatasetId.EQUITY_DAILY)
    )
    if len(sessions) < 32:
        return StudySample(
            study_id=spec.study_id,
            input_manifest_hashes=(),
            label_manifest_hashes=(),
            analysis_dates=(),
            panel_row_count=0,
            exclusion_counts={"insufficient_calendar": 1},
            signal_inputs=pd.DataFrame(),
            future_labels=pd.DataFrame(),
        )
    event_datasets = (
        (ResearchDatasetId.ANNOUNCEMENT,)
        if spec.study_id == "daily_event_study"
        else (ResearchDatasetId.EARNINGS_FORECAST, ResearchDatasetId.EARNINGS_EXPRESS)
    )
    event_partitions = {
        dataset: _manifest_partitions(query, dataset) for dataset in event_datasets
    }
    final_snapshot = query.materialize_snapshot(
        event_partitions,
        as_of=analysis_close_as_of(sessions[-1]),
    )
    calendar = pd.DataFrame({"cal_date": sessions, "is_open": True})
    announcements = _normalized_event_facts(final_snapshot, spec, calendar)
    session_index = {session: index for index, session in enumerate(sessions)}
    announcements["event_session_index"] = announcements["event_date"].map(
        session_index
    )
    announcements = announcements.dropna(subset=["event_session_index"]).copy()
    announcements["event_session_index"] = announcements["event_session_index"].astype(int)
    announcements = announcements[
        (announcements["event_session_index"] >= 1)
        & (announcements["event_session_index"] <= len(sessions) - 31)
    ].sort_values(["ts_code", "event_session_index", "event_id"], kind="mergesort")
    kept: list[object] = []
    for _, company in announcements.groupby("ts_code", sort=True):
        last: int | None = None
        for row_index, row in company.iterrows():
            position = int(row["event_session_index"])
            if last is None or position - last > 30:
                kept.append(row_index)
                last = position
    announcements = announcements.loc[kept].sort_values(
        ["event_date", "ts_code", "event_id"], kind="mergesort"
    )
    announcements["is_pseudo_event"] = False
    pseudo_rows: list[dict[str, object]] = []
    for _, event in (
        announcements.iterrows()
        if spec.study_id == "daily_event_study"
        else []
    ):
        pseudo_position = int(event["event_session_index"]) - 35
        if pseudo_position < 1 or pseudo_position > len(sessions) - 31:
            continue
        company_positions = announcements.loc[
            announcements["ts_code"].astype(str) == str(event["ts_code"]),
            "event_session_index",
        ].astype(int)
        if ((company_positions - pseudo_position).abs() <= 30).any():
            continue
        pseudo_rows.append(
            {
                "event_id": f"PSEUDO-{event['event_id']}",
                "ts_code": event["ts_code"],
                "event_date": sessions[pseudo_position],
                "event_session_index": pseudo_position,
                "is_pseudo_event": True,
            }
        )
    candidates_all = pd.concat(
        [announcements, pd.DataFrame(pseudo_rows)], ignore_index=True, sort=False
    ).sort_values(["event_date", "ts_code", "event_id"], kind="mergesort")

    signals: list[pd.DataFrame] = []
    labels: list[pd.DataFrame] = []
    input_hashes: list[str] = [final_snapshot.input_manifest["input_manifest_hash"]]
    label_hashes: list[str] = []
    analysis_dates: list[date] = []
    exclusions = {"event_stock_not_eligible": 0}
    for event_date, candidates in candidates_all.groupby("event_date", sort=True):
        position = session_index[event_date]
        history_dates = sessions[position - 1 : position + 1]
        future_dates = sessions[position + 1 : position + 31]
        request = _requested_signal_partitions(
            spec,
            query,
            history_dates=history_dates,
            analysis_date=event_date,
        )
        event_month = event_date.strftime("%Y-%m")
        for dataset, partitions in event_partitions.items():
            if event_month in partitions:
                request[dataset] = (event_month,)
        snapshot = materialize_signal_snapshot(
            query, request, analysis_date=event_date
        )
        input_hashes.append(snapshot.input_manifest["input_manifest_hash"])
        as_of_events = _normalized_event_facts(snapshot, spec, calendar)
        official_candidates = candidates[~candidates["is_pseudo_event"].astype(bool)]
        pseudo_candidates = candidates[candidates["is_pseudo_event"].astype(bool)]
        event_ids = set(official_candidates["event_id"].astype(str))
        as_of_events = as_of_events[
            as_of_events["event_id"].astype(str).isin(event_ids)
        ][["event_id", "ts_code", "event_date"]]
        candidate_events = pd.concat(
            [
                as_of_events.assign(is_pseudo_event=False),
                pseudo_candidates[
                    ["event_id", "ts_code", "event_date", "is_pseudo_event"]
                ],
            ],
            ignore_index=True,
        )
        daily = snapshot.frame(ResearchDatasetId.EQUITY_DAILY)
        current_daily = daily[
            pd.to_datetime(daily["trade_date"], errors="raise").dt.date == event_date
        ]
        eligible = eligible_stock_rows(
            snapshot.frame(ResearchDatasetId.SECURITY_MASTER),
            current_daily,
            snapshot.frame(ResearchDatasetId.SUSPENSION),
            analysis_date=event_date,
        )
        eligible = _merge_current_facts(eligible, snapshot, request, event_date)
        eligible = _attach_market_benchmark(eligible, snapshot, event_date)
        event_rows = candidate_events.merge(
            eligible,
            on="ts_code",
            how="inner",
            validate="many_to_one",
        )
        exclusions["event_stock_not_eligible"] += len(candidate_events) - len(event_rows)
        label_request = _requested_label_partitions(
            query, future_dates, include_industry=False
        )
        label_snapshot = query.materialize_snapshot(
            label_request, as_of=analysis_close_as_of(future_dates[-1])
        )
        label_hashes.append(label_snapshot.input_manifest["input_manifest_hash"])
        stock_labels = _future_stock_labels(
            eligible[eligible["ts_code"].isin(event_rows["ts_code"])],
            label_snapshot,
            label_request,
            event_date,
        )
        factors = snapshot.frame(ResearchDatasetId.ADJ_FACTOR)
        indexes = snapshot.frame(ResearchDatasetId.INDEX_DAILY)
        event_rows["stock_return_0"] = event_rows["ts_code"].map(
            lambda code: _return_between_sessions(
                daily,
                factors,
                code_column="ts_code",
                code=str(code),
                previous_date=history_dates[0],
                current_date=event_date,
            )
        )
        event_rows["market_return_0"] = event_rows["market_index_code"].map(
            lambda code: _return_between_sessions(
                indexes,
                pd.DataFrame(),
                code_column="index_code",
                code=str(code),
                previous_date=history_dates[0],
                current_date=event_date,
            )
        )
        next_returns = stock_labels[
            ["ts_code", "close_return_1d", "market_return_1d"]
        ].drop_duplicates("ts_code")
        event_rows = event_rows.merge(
            next_returns, on="ts_code", how="left", validate="many_to_one"
        ).rename(
            columns={
                "close_return_1d": "stock_return_1",
                "market_return_1d": "market_return_1",
            }
        )
        event_rows["local_formal_announcement_match"] = ~event_rows[
            "is_pseudo_event"
        ].astype(bool)
        event_rows["event_session_index"] = position
        if spec.study_id == "a_share_earnings_announcement_drift":
            event_rows["event_car_0_1"] = (
                event_rows["stock_return_0"]
                - event_rows["market_return_0"]
                + event_rows["stock_return_1"]
                - event_rows["market_return_1"]
            )
            signal_columns = [
                "event_id",
                "ts_code",
                "event_date",
                "event_session_index",
                "event_car_0_1",
            ]
        else:
            signal_columns = [
                "event_id",
                "ts_code",
                "event_date",
                "event_session_index",
                "stock_return_0",
                "stock_return_1",
                "market_return_0",
                "market_return_1",
                "local_formal_announcement_match",
                "is_pseudo_event",
            ]
        signals.append(event_rows[signal_columns])
        labels.append(
            event_rows[["event_id", "ts_code", "event_date"]].merge(
                stock_labels,
                left_on=["ts_code", "event_date"],
                right_on=["ts_code", "analysis_date"],
                how="left",
            ).drop(columns=["analysis_date"])
        )
        analysis_dates.append(event_date)
    signal_inputs = pd.concat(signals, ignore_index=True) if signals else pd.DataFrame()
    future_labels = pd.concat(labels, ignore_index=True) if labels else pd.DataFrame()
    return StudySample(
        study_id=spec.study_id,
        input_manifest_hashes=tuple(input_hashes),
        label_manifest_hashes=tuple(label_hashes),
        analysis_dates=tuple(sorted(set(analysis_dates))),
        panel_row_count=len(signal_inputs),
        exclusion_counts=exclusions,
        signal_inputs=signal_inputs,
        future_labels=future_labels,
    )


def build_study_sample(
    spec: ValidationSpec,
    query: ResearchQuery,
) -> StudySample:
    if spec.study_id in _PRICE_STUDIES:
        return _build_price_study_sample(spec, query)
    if spec.study_id == "daily_event_study":
        return _build_daily_event_sample(spec, query)
    if spec.study_id == "a_share_earnings_announcement_drift":
        return _build_daily_event_sample(spec, query)
    raise ValueError(f"sample builder is not implemented for {spec.study_id}")


__all__ = [
    "adjusted_future_price",
    "analysis_close_as_of",
    "build_study_sample",
    "eligible_stock_rows",
    "label_path",
    "materialize_signal_snapshot",
    "next_trading_sessions",
    "split_signal_and_label_columns",
]
