"""Validate frozen V3 selections from the next market session's open.

This module is a read-only historical action-value post-processor.  It never
forms or reranks candidates and writes runtime artifacts only to the frozen
USB experiment directory.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path
import shutil
import sys
import time
from typing import Any, Iterable

import numpy as np
import pandas as pd
import yaml

from stock_analyzer.evaluation.v3_target_retention_diagnostic import (
    Block,
    _file_manifest,
    _tree_signature,
    _write_json,
    _write_parquet,
)


DEFAULT_ALLOWED_VOLUME_ROOT = Path("/Volumes/ZHUTONG")
EXPECTED_BLOCKS = ("A", "B", "C")
EXPECTED_HORIZONS = (20, 30)
EXPECTED_RETENTION_WINDOWS = (1, 3, 5)


@dataclass(frozen=True)
class ActionConfig:
    experiment_id: str
    source_experiment_root: Path
    warehouse_root: Path
    output_root: Path
    blocks: tuple[Block, ...]
    horizons: tuple[int, ...]
    target_return: float
    retention_windows: tuple[int, ...]
    entry_delay_market_sessions: int
    entry_price_field: str
    entry_day_counts_as_session_one: bool
    exclude_one_price_limit_up: bool
    runtime_stop_minutes: int
    supported_policies: tuple[str, ...]
    rule_optimization_allowed: bool


def load_config(path: str | Path) -> ActionConfig:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("action validation config must be a mapping")
    config = ActionConfig(
        experiment_id=str(payload["experiment_id"]),
        source_experiment_root=Path(payload["source_experiment_root"]),
        warehouse_root=Path(payload["warehouse_root"]),
        output_root=Path(payload["output_root"]),
        blocks=tuple(
            Block(
                id=str(item["id"]),
                start=date.fromisoformat(str(item["start"])),
                end=date.fromisoformat(str(item["end"])),
            )
            for item in payload["blocks"]
        ),
        horizons=tuple(int(value) for value in payload["horizons"]),
        target_return=float(payload["target_return"]),
        retention_windows=tuple(int(value) for value in payload["retention_windows"]),
        entry_delay_market_sessions=int(payload["entry_delay_market_sessions"]),
        entry_price_field=str(payload["entry_price_field"]),
        entry_day_counts_as_session_one=bool(payload["entry_day_counts_as_session_one"]),
        exclude_one_price_limit_up=bool(payload["exclude_one_price_limit_up"]),
        runtime_stop_minutes=int(payload["runtime_stop_minutes"]),
        supported_policies=tuple(str(value) for value in payload["supported_policies"]),
        rule_optimization_allowed=bool(payload["rule_optimization_allowed"]),
    )
    _validate_config(config)
    return config


def _validate_config(config: ActionConfig) -> None:
    if tuple(block.id for block in config.blocks) != EXPECTED_BLOCKS:
        raise ValueError("blocks must remain the frozen A/B/C blocks")
    if config.horizons != EXPECTED_HORIZONS:
        raise ValueError("action horizons must remain 20 and 30")
    if config.retention_windows != EXPECTED_RETENTION_WINDOWS:
        raise ValueError("retention windows must remain 1/3/5")
    if not np.isclose(config.target_return, 0.20):
        raise ValueError("target return must remain 20%")
    if config.entry_delay_market_sessions != 1:
        raise ValueError("entry must be the next market session")
    if config.entry_price_field != "open":
        raise ValueError("entry price must be the next session open")
    if not config.entry_day_counts_as_session_one:
        raise ValueError("entry day must count as opportunity session one")
    if not config.exclude_one_price_limit_up:
        raise ValueError("one-price limit-up entries must be excluded")
    if config.rule_optimization_allowed:
        raise ValueError("rule optimization is forbidden")
    if config.runtime_stop_minutes <= 0:
        raise ValueError("runtime stop must be positive")


def prepare_output_root(
    config: ActionConfig,
    *,
    output_override: str | Path | None = None,
    allowed_volume_root: str | Path = DEFAULT_ALLOWED_VOLUME_ROOT,
) -> Path:
    output = Path(output_override) if output_override is not None else config.output_root
    expected = Path(allowed_volume_root) / "股票分析助手-V3回测" / config.experiment_id
    if output.resolve(strict=False) != expected.resolve(strict=False):
        raise ValueError("输出路径必须是冻结的U盘专用目录")
    if output.resolve(strict=False) == config.source_experiment_root.resolve(strict=False):
        raise ValueError("输出目录不得覆盖来源实验")
    for child in ("manifests", "tables", "reports"):
        (output / child).mkdir(parents=True, exist_ok=True)
    return output


def _normalize_action_prices(prices: pd.DataFrame) -> pd.DataFrame:
    required = {
        "trade_date", "ts_code", "open", "high", "low", "close", "adj_factor", "up_limit"
    }
    missing = sorted(required - set(prices.columns))
    if missing:
        raise ValueError(f"prices lack required fields: {', '.join(missing)}")
    frame = prices.copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="raise").dt.normalize()
    frame["ts_code"] = frame["ts_code"].astype(str)
    for column in ("open", "high", "low", "close", "adj_factor", "up_limit"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    for raw in ("open", "high", "low", "close"):
        frame[f"adj_{raw}"] = frame[raw] * frame["adj_factor"]
    frame["quoted"] = frame[["open", "high", "low", "close", "adj_factor"]].notna().all(axis=1)
    frame = frame.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    if frame.duplicated(["trade_date", "ts_code"]).any():
        raise ValueError("prices contain duplicate stock-date rows")
    return frame


def _is_close(left: float, right: float) -> bool:
    return bool(np.isfinite(left) and np.isfinite(right) and np.isclose(left, right, rtol=1e-6, atol=1e-8))


def compute_action_path(
    prices: pd.DataFrame,
    formation_date: str | date | pd.Timestamp,
    ts_code: str,
    horizon: int,
    target_return: float,
    retention_windows: tuple[int, ...] = EXPECTED_RETENTION_WINDOWS,
) -> dict[str, Any]:
    """Compute a frozen next-session-open opportunity path for one stock."""

    prepared = _normalize_action_prices(prices)
    formation_day = pd.Timestamp(formation_date).normalize()
    stock = prepared[prepared["ts_code"] == str(ts_code)].sort_values("trade_date").reset_index(drop=True)
    formation_positions = stock.index[stock["trade_date"] == formation_day].tolist()
    if len(formation_positions) != 1:
        raise ValueError(f"formation row is not unique for {ts_code} on {formation_day.date()}")
    formation_index = int(formation_positions[0])
    if formation_index + 1 >= len(stock):
        raise ValueError("next market session is unavailable")
    formation = stock.iloc[formation_index]
    future = stock.iloc[formation_index + 1 :].reset_index(drop=True)
    entry = future.iloc[0]
    formation_close = float(formation["adj_close"]) if np.isfinite(formation["adj_close"]) else np.nan
    quote_valid = bool(entry["quoted"] and np.isfinite(entry["adj_open"]) and entry["adj_open"] > 0)
    open_at_limit = bool(
        quote_valid and np.isfinite(entry["up_limit"]) and _is_close(float(entry["open"]), float(entry["up_limit"]))
    )
    one_price_limit_up = bool(
        open_at_limit
        and _is_close(float(entry["high"]), float(entry["up_limit"]))
        and _is_close(float(entry["low"]), float(entry["up_limit"]))
    )
    if not quote_valid:
        entry_status = "no_quote_or_suspended"
    elif one_price_limit_up:
        entry_status = "one_price_limit_up"
    elif open_at_limit:
        entry_status = "open_at_limit_not_one_price"
    else:
        entry_status = "executable_entry"
    executable = bool(quote_valid and not one_price_limit_up)
    action_price = float(entry["adj_open"]) if quote_valid else np.nan
    target_price = action_price * (1.0 + target_return) if quote_valid else np.nan
    attainment = future.iloc[:horizon].copy()
    complete_horizon = bool(len(attainment) == horizon)

    mechanical_touch = pd.NA
    mechanical_close = pd.NA
    mechanical_touch_index: int | None = None
    mechanical_close_index: int | None = None
    if quote_valid:
        touch_mask = (attainment["adj_high"] / action_price - 1.0).ge(target_return)
        close_mask = attainment["quoted"] & (attainment["adj_close"] / action_price - 1.0).ge(target_return)
        touch_positions = np.flatnonzero(touch_mask.fillna(False).to_numpy())
        close_positions = np.flatnonzero(close_mask.fillna(False).to_numpy())
        mechanical_touch_index = int(touch_positions[0]) if len(touch_positions) else None
        mechanical_close_index = int(close_positions[0]) if len(close_positions) else None
        mechanical_touch = bool(mechanical_touch_index is not None)
        mechanical_close = bool(mechanical_close_index is not None)

    first_touch_index = mechanical_touch_index if executable else None
    first_close_index = mechanical_close_index if executable else None
    target_touched: bool | pd._libs.missing.NAType = (
        bool(mechanical_touch) if executable else pd.NA
    )
    close_confirmed: bool | pd._libs.missing.NAType = (
        bool(mechanical_close) if executable else pd.NA
    )
    row: dict[str, Any] = {
        "formation_date": formation_day,
        "ts_code": str(ts_code),
        "horizon": int(horizon),
        "entry_delay_sessions": 1,
        "entry_date": pd.Timestamp(entry["trade_date"]),
        "entry_status": entry_status,
        "executable_entry": executable,
        "raw_entry_open": float(entry["open"]) if quote_valid else np.nan,
        "entry_adj_factor": float(entry["adj_factor"]) if quote_valid else np.nan,
        "formation_close": formation_close,
        "action_price": action_price,
        "target_price": target_price,
        "formation_to_entry_gap": (
            action_price / formation_close - 1.0
            if quote_valid and np.isfinite(formation_close) and formation_close > 0
            else np.nan
        ),
        "complete_horizon": complete_horizon,
        "observed_market_sessions": int(len(attainment)),
        "quoted_stock_sessions": int(attainment["quoted"].sum()),
        "target_touched": target_touched,
        "close_confirmed": close_confirmed,
        "mechanical_target_touched": mechanical_touch,
        "mechanical_close_confirmed": mechanical_close,
        "first_touch_session": first_touch_index + 1 if first_touch_index is not None else pd.NA,
        "first_touch_date": attainment.iloc[first_touch_index]["trade_date"] if first_touch_index is not None else pd.NaT,
        "first_close_confirm_session": first_close_index + 1 if first_close_index is not None else pd.NA,
        "first_close_confirm_date": attainment.iloc[first_close_index]["trade_date"] if first_close_index is not None else pd.NaT,
    }

    if quote_valid and not attainment.empty:
        valid_lows = attainment["adj_low"].dropna()
        row["window_min_return"] = float(valid_lows.min() / action_price - 1.0) if not valid_lows.empty else np.nan
        if mechanical_touch_index is None:
            pre = valid_lows
        elif mechanical_touch_index == 0:
            pre = pd.Series(dtype=float)
        else:
            pre = attainment.iloc[:mechanical_touch_index]["adj_low"].dropna()
        row["pre_touch_min_return"] = min(0.0, float(pre.min() / action_price - 1.0)) if not pre.empty else 0.0
    else:
        row["window_min_return"] = np.nan
        row["pre_touch_min_return"] = np.nan

    for window in retention_windows:
        observable = False
        retained: bool | pd._libs.missing.NAType = pd.NA
        if executable and first_close_index is not None:
            post = future.iloc[first_close_index + 1 : first_close_index + 1 + window]
            observable = bool(len(post) == window and post["quoted"].all() and post["adj_close"].notna().all())
            if observable:
                retained = bool((post["adj_close"] / action_price - 1.0).ge(target_return).all())
        row[f"retain_{window}_observable"] = observable
        row[f"retain_{window}"] = retained

    if quote_valid and complete_horizon and not attainment.empty and np.isfinite(attainment.iloc[-1]["adj_close"]):
        row["terminal_return"] = float(attainment.iloc[-1]["adj_close"] / action_price - 1.0)
    else:
        row["terminal_return"] = np.nan
    return row


def _available_sessions(warehouse_root: Path) -> list[pd.Timestamp]:
    sessions: list[pd.Timestamp] = []
    for path in (warehouse_root / "facts" / "equity_daily").glob("trade_date=*"):
        if not path.is_dir():
            continue
        try:
            sessions.append(pd.Timestamp(path.name.split("=", 1)[1]).normalize())
        except (IndexError, ValueError):
            continue
    return sorted(set(sessions))


def _read_action_price_frame(
    config: ActionConfig,
    formation_dates: pd.Series,
) -> tuple[pd.DataFrame, list[Path]]:
    sessions = _available_sessions(config.warehouse_root)
    first = pd.to_datetime(formation_dates).min().normalize()
    last_formation = pd.to_datetime(formation_dates).max().normalize()
    last_index = sessions.index(last_formation)
    last_needed = min(
        len(sessions) - 1,
        last_index + config.entry_delay_market_sessions + max(config.horizons) + max(config.retention_windows),
    )
    required_sessions = [session for session in sessions if first <= session <= sessions[last_needed]]
    frames: list[pd.DataFrame] = []
    input_paths: list[Path] = []
    for session in required_sessions:
        partition = f"trade_date={session.date().isoformat()}"
        equity_path = config.warehouse_root / "facts" / "equity_daily" / partition / "data.parquet"
        factor_path = config.warehouse_root / "facts" / "adj_factor" / partition / "data.parquet"
        limit_path = config.warehouse_root / "facts" / "stock_limit" / partition / "data.parquet"
        if not equity_path.exists() or not factor_path.exists():
            raise FileNotFoundError(f"missing equity or factor partition for {session.date()}")
        equity = pd.read_parquet(
            equity_path,
            columns=["trade_date", "ts_code", "open", "high", "low", "close"],
        )
        factor = pd.read_parquet(
            factor_path,
            columns=["trade_date", "ts_code", "adj_factor"],
        )
        merged = equity.merge(factor, on=["trade_date", "ts_code"], how="left", validate="one_to_one")
        if limit_path.exists():
            limits = pd.read_parquet(limit_path, columns=["trade_date", "ts_code", "up_limit"])
            merged = merged.merge(limits, on=["trade_date", "ts_code"], how="left", validate="one_to_one")
            input_paths.append(limit_path)
        else:
            merged["up_limit"] = np.nan
        frames.append(merged)
        input_paths.extend([equity_path, factor_path])
    return _normalize_action_prices(pd.concat(frames, ignore_index=True)), input_paths


def _grid_stock_prices(
    prices: pd.DataFrame,
    ts_code: str,
    market_sessions: pd.Index,
) -> pd.DataFrame:
    stock = prices[prices["ts_code"] == str(ts_code)].set_index("trade_date")
    grid = stock.reindex(market_sessions).reset_index()
    grid["ts_code"] = str(ts_code)
    return grid


def build_action_paths(
    config: ActionConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, list[Path]]:
    source_path = config.source_experiment_root / "tables" / "outcomes_all.parquet"
    source = pd.read_parquet(source_path)
    source["formation_date"] = pd.to_datetime(source["formation_date"]).dt.normalize()
    source = source[source["horizon"].isin(config.horizons)].copy()
    source_keys = ["block", "formation_date", "ts_code", "horizon"]
    keys = source[source_keys].drop_duplicates().sort_values(source_keys).reset_index(drop=True)
    prices, price_paths = _read_action_price_frame(config, keys["formation_date"])
    market_sessions = pd.Index(sorted(prices["trade_date"].unique()), name="trade_date")
    stock_grids = {
        code: _grid_stock_prices(prices, code, market_sessions)
        for code in sorted(keys["ts_code"].astype(str).unique())
    }
    rows: list[dict[str, Any]] = []
    started = time.perf_counter()
    for item in keys.itertuples(index=False):
        row = compute_action_path(
            stock_grids[str(item.ts_code)],
            formation_date=item.formation_date,
            ts_code=str(item.ts_code),
            horizon=int(item.horizon),
            target_return=config.target_return,
            retention_windows=config.retention_windows,
        )
        row["block"] = str(item.block)
        rows.append(row)
        if time.perf_counter() - started > config.runtime_stop_minutes * 60:
            raise TimeoutError("action validation runtime exceeded frozen stop limit")
    unique = pd.DataFrame(rows)
    for column in ("target_touched", "close_confirmed", "mechanical_target_touched", "mechanical_close_confirmed"):
        unique[column] = unique[column].astype("boolean")
    for window in config.retention_windows:
        unique[f"retain_{window}"] = unique[f"retain_{window}"].astype("boolean")
    overlap = set(source.columns) & set(unique.columns) - set(source_keys)
    new_columns = [column for column in unique.columns if column not in source_keys and column not in overlap]
    replace_columns = [
        "formation_close", "complete_horizon", "target_touched", "terminal_return"
    ]
    source_without_replaced = source.drop(columns=[column for column in replace_columns if column in source.columns])
    merge_columns = source_keys + [column for column in unique.columns if column not in source_keys]
    expanded = source_without_replaced.merge(
        unique[merge_columns],
        on=source_keys,
        how="left",
        validate="many_to_one",
    )
    if len(expanded) != len(source):
        raise ValueError("expanded action outcomes changed frozen source row count")
    return unique, expanded, [source_path, *price_paths]


def _safe_rate(numerator: int | float, denominator: int | float) -> float:
    return float(numerator) / float(denominator) if denominator else np.nan


def summarize_actions(
    outcomes: pd.DataFrame,
    *,
    retention_windows: tuple[int, ...] = EXPECTED_RETENTION_WINDOWS,
    supported_policies: tuple[str, ...] | None = None,
) -> pd.DataFrame:
    prepared = outcomes.copy()
    if supported_policies is not None:
        prepared = prepared[prepared["policy"].isin(supported_policies)].copy()
    frames = [prepared[prepared["block"].astype(str) == block].copy() for block in sorted(prepared["block"].astype(str).unique())]
    all_frame = prepared.copy()
    all_frame["block"] = "ALL"
    frames.append(all_frame)
    rows: list[dict[str, Any]] = []
    for frame in frames:
        if frame.empty:
            continue
        block = str(frame["block"].iloc[0])
        for (policy, layer, horizon), group in frame.groupby(["policy", "layer", "horizon"], dropna=False, sort=True):
            rows.append(_action_summary_row(group, block, str(policy), str(layer), int(horizon), retention_windows))
        for (policy, horizon), group in frame.groupby(["policy", "horizon"], sort=True):
            deduped = group.drop_duplicates(["formation_date", "ts_code", "horizon"])
            rows.append(_action_summary_row(deduped, block, str(policy), "all", int(horizon), retention_windows))
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).drop_duplicates(["block", "policy", "layer", "horizon"], keep="last").sort_values(["horizon", "policy", "layer", "block"]).reset_index(drop=True)


def _action_summary_row(
    group: pd.DataFrame,
    block: str,
    policy: str,
    layer: str,
    horizon: int,
    retention_windows: tuple[int, ...],
) -> dict[str, Any]:
    sample = group[group["complete_horizon"].fillna(False).astype(bool)].copy()
    planned = len(sample)
    executable = sample["executable_entry"].fillna(False).astype(bool)
    touch = sample["target_touched"].fillna(False).astype(bool)
    close = sample["close_confirmed"].fillna(False).astype(bool)
    executable_count = int(executable.sum())
    touch_successes = int((executable & touch).sum())
    close_successes = int((executable & close).sum())
    row: dict[str, Any] = {
        "block": block,
        "policy": policy,
        "layer": layer,
        "horizon": horizon,
        "planned_actions": planned,
        "executable_entries": executable_count,
        "unexecutable_entries": int(planned - executable_count),
        "entry_execution_rate": _safe_rate(executable_count, planned),
        "touch_successes": touch_successes,
        "touch_rate_given_executable": _safe_rate(touch_successes, executable_count),
        "touch_yield_all_plans": _safe_rate(touch_successes, planned),
        "close_successes": close_successes,
        "close_rate_given_executable": _safe_rate(close_successes, executable_count),
        "close_yield_all_plans": _safe_rate(close_successes, planned),
        "median_first_touch_session": float(pd.to_numeric(sample.loc[executable & touch, "first_touch_session"], errors="coerce").median()),
        "median_formation_to_entry_gap": float(pd.to_numeric(sample.loc[executable, "formation_to_entry_gap"], errors="coerce").median()),
        "median_pre_touch_min_return": float(pd.to_numeric(sample.loc[executable, "pre_touch_min_return"], errors="coerce").median()),
        "median_window_min_return": float(pd.to_numeric(sample.loc[executable, "window_min_return"], errors="coerce").median()),
        "median_terminal_return": float(pd.to_numeric(sample.loc[executable, "terminal_return"], errors="coerce").median()),
    }
    for window in retention_windows:
        observable = sample[f"retain_{window}_observable"].fillna(False).astype(bool)
        retained = sample[f"retain_{window}"].fillna(False).astype(bool)
        successes = int((observable & retained).sum())
        row[f"retain_{window}_successes"] = successes
        row[f"retain_{window}_yield_all_plans"] = _safe_rate(successes, planned)
        row[f"retain_{window}_rate_given_executable"] = _safe_rate(successes, executable_count)
    return row


def validate_action_contracts(
    outcomes: pd.DataFrame,
    *,
    retention_windows: tuple[int, ...] = EXPECTED_RETENTION_WINDOWS,
) -> dict[str, bool]:
    if not outcomes["entry_delay_sessions"].eq(1).all():
        raise ValueError("行动价必须来自形成日后的下一市场交易日")
    if {"raw_entry_open", "entry_adj_factor", "action_price"}.issubset(outcomes.columns):
        quoted = outcomes["action_price"].notna()
        reconstructed = outcomes.loc[quoted, "raw_entry_open"] * outcomes.loc[quoted, "entry_adj_factor"]
        if not np.allclose(reconstructed, outcomes.loc[quoted, "action_price"], rtol=0, atol=1e-10):
            raise ValueError("行动价必须等于次日开盘价乘复权因子")
    executable = outcomes["executable_entry"].fillna(False).astype(bool)
    if outcomes.loc[~executable & outcomes["entry_status"].isin(["one_price_limit_up", "no_quote_or_suspended"]), "target_touched"].notna().any():
        raise ValueError("不可执行行动不得进入主命中标签")
    touch = outcomes["target_touched"].fillna(False).astype(bool)
    close = outcomes["close_confirmed"].fillna(False).astype(bool)
    if (close & ~touch).any():
        raise ValueError("收盘确认必须是盘中达到的子集")
    for smaller, larger in zip(retention_windows, retention_windows[1:]):
        common = outcomes[f"retain_{smaller}_observable"].astype(bool) & outcomes[f"retain_{larger}_observable"].astype(bool)
        invalid = common & outcomes[f"retain_{larger}"].fillna(False).astype(bool) & ~outcomes[f"retain_{smaller}"].fillna(False).astype(bool)
        if invalid.any():
            raise ValueError("保持窗口必须满足嵌套关系")
    nested = True
    common_keys = ["block", "formation_date", "ts_code"]
    complete = outcomes[outcomes["complete_horizon"].fillna(False).astype(bool) & executable].copy()
    pivot = complete.pivot_table(index=common_keys, columns="horizon", values="target_touched", aggfunc="first")
    if 20 in pivot and 30 in pivot:
        common = pivot[[20, 30]].dropna()
        if (common[20].astype(bool) & ~common[30].astype(bool)).any():
            nested = False
            raise ValueError("20日达到必须是30日达到的子集")
    return {
        "entry_is_next_market_session": True,
        "action_price_recomputable": True,
        "unexecutable_excluded_from_primary": True,
        "close_subset_touch": True,
        "retention_nested": True,
        "touch_20_subset_30": nested,
    }


def build_comparisons(summary: pd.DataFrame) -> pd.DataFrame:
    pairs = (
        ("discovery", ("research_union", "all"), ("matched_research_control", "all")),
        ("compression", ("v3_partial_candidate", "all"), ("research_union", "all")),
        ("focus", ("v3_partial_candidate", "focus"), ("v3_partial_candidate", "candidate")),
        ("candidate_control", ("v3_partial_candidate", "all"), ("matched_candidate_control", "all")),
    )
    metrics = (
        "touch_rate_given_executable",
        "touch_yield_all_plans",
        "close_rate_given_executable",
        "close_yield_all_plans",
        "retain_3_yield_all_plans",
    )
    rows: list[dict[str, Any]] = []
    if summary.empty:
        return pd.DataFrame()
    for horizon in sorted(summary["horizon"].unique()):
        sample = summary[summary["horizon"] == horizon]
        for name, left_key, right_key in pairs:
            effects: dict[str, list[float]] = {metric: [] for metric in metrics}
            combined: dict[str, float] = {}
            start = len(rows)
            for block in ("A", "B", "C", "ALL"):
                left = sample[(sample["block"] == block) & (sample["policy"] == left_key[0]) & (sample["layer"] == left_key[1])]
                right = sample[(sample["block"] == block) & (sample["policy"] == right_key[0]) & (sample["layer"] == right_key[1])]
                for metric in metrics:
                    left_value = float(left.iloc[0][metric]) if len(left) == 1 else np.nan
                    right_value = float(right.iloc[0][metric]) if len(right) == 1 else np.nan
                    effect = left_value - right_value if np.isfinite(left_value) and np.isfinite(right_value) else np.nan
                    rows.append({
                        "comparison": name, "horizon": int(horizon), "block": block,
                        "metric": metric, "left_value": left_value, "right_value": right_value,
                        "effect": effect,
                    })
                    if block == "ALL":
                        combined[metric] = effect
                    elif np.isfinite(effect):
                        effects[metric].append(effect)
            for row in rows[start:]:
                values = effects[row["metric"]]
                overall = combined.get(row["metric"], np.nan)
                positive = sum(value > 0 for value in values)
                negative = sum(value < 0 for value in values)
                status = "insufficient_evidence"
                if np.isfinite(overall) and overall > 0 and positive >= 2:
                    status = "supported_as_baseline"
                elif np.isfinite(overall) and overall < 0 and negative >= 2:
                    status = "needs_optimization"
                row["positive_blocks"] = positive
                row["negative_blocks"] = negative
                row["status"] = status
    return pd.DataFrame(rows)


def build_cases(expanded: pd.DataFrame) -> pd.DataFrame:
    sample = expanded[
        (expanded["policy"] == "v3_partial_candidate")
        & (expanded["horizon"] == 30)
        & expanded["complete_horizon"].fillna(False).astype(bool)
    ].drop_duplicates(["block", "formation_date", "ts_code", "horizon"]).copy()
    if sample.empty:
        return pd.DataFrame()
    executable = sample["executable_entry"].astype(bool)
    touch = sample["target_touched"].fillna(False).astype(bool)
    close = sample["close_confirmed"].fillna(False).astype(bool)
    groups: list[pd.DataFrame] = []
    definitions = (
        ("close_confirmed_success", sample[executable & close].sort_values("first_touch_session").head(8)),
        ("intraday_touch_without_close", sample[executable & touch & ~close].sort_values("window_min_return").head(8)),
        ("no_target_deep_path", sample[executable & ~touch].sort_values("window_min_return").head(8)),
        ("unexecutable_next_day", sample[~executable].sort_values("entry_status").head(8)),
    )
    for case_type, frame in definitions:
        if frame.empty:
            continue
        chosen = frame.copy()
        chosen.insert(0, "case_type", case_type)
        groups.append(chosen)
    if not groups:
        return pd.DataFrame()
    columns = [
        "case_type", "block", "formation_date", "ts_code", "layer", "entry_date",
        "entry_status", "formation_to_entry_gap", "first_touch_session",
        "first_close_confirm_session", "pre_touch_min_return", "window_min_return",
        "terminal_return",
    ]
    return pd.concat(groups, ignore_index=True)[columns]


def _summary_lookup(
    summary: pd.DataFrame,
    policy: str,
    horizon: int,
    *,
    layer: str = "all",
    block: str = "ALL",
) -> pd.Series | None:
    found = summary[
        (summary["policy"] == policy)
        & (summary["layer"] == layer)
        & (summary["block"] == block)
        & (summary["horizon"] == horizon)
    ]
    return found.iloc[0] if len(found) == 1 else None


def _comparison_status(
    comparisons: pd.DataFrame,
    comparison: str,
    horizon: int,
    metric: str = "touch_yield_all_plans",
) -> str:
    found = comparisons[
        (comparisons["comparison"] == comparison)
        & (comparisons["horizon"] == horizon)
        & (comparisons["block"] == "ALL")
        & (comparisons["metric"] == metric)
    ]
    return str(found.iloc[0]["status"]) if len(found) == 1 else "insufficient_evidence"


def _pair_sentence(
    summary: pd.DataFrame,
    left_policy: str,
    right_policy: str,
    left_label: str,
    right_label: str,
    *,
    left_layer: str = "all",
    right_layer: str = "all",
) -> str:
    parts = []
    for horizon in (20, 30):
        left = _summary_lookup(summary, left_policy, horizon, layer=left_layer)
        right = _summary_lookup(summary, right_policy, horizon, layer=right_layer)
        if left is None or right is None:
            continue
        parts.append(
            f"{horizon}日全部计划产出率 {_fmt_pct(left['touch_yield_all_plans'])} 对 {_fmt_pct(right['touch_yield_all_plans'])}，"
            f"可执行中盘中达到率 {_fmt_pct(left['touch_rate_given_executable'])} 对 {_fmt_pct(right['touch_rate_given_executable'])}，"
            f"收盘确认率 {_fmt_pct(left['close_rate_given_executable'])} 对 {_fmt_pct(right['close_rate_given_executable'])}"
        )
    return f"{left_label}与{right_label}：" + "；".join(parts) + "。"


def _decision_sections(summary: pd.DataFrame, comparisons: pd.DataFrame) -> tuple[str, str]:
    preserve: list[str] = []
    optimize: list[str] = []
    for name, title, explanation in (
        ("discovery", "三条可执行入口合并研究池", "它只验证六入口架构中当前可历史复算的热点、业绩和价格三条入口，回答这部分发现层在用户次日行动后是否仍比匹配研究对象多找到真实机会；不能外推另外三条暂不可测入口已经有效。"),
        ("candidate_control", "最终候选相对候选对照", "它回答当前完整筛选是否提供了可辨认的次日行动增量。"),
        ("focus", "重点与候补分层", "它回答重点层是否真正比普通候补更值得优先关注。"),
    ):
        statuses = [_comparison_status(comparisons, name, horizon) for horizon in (20, 30)]
        if statuses == ["supported_as_baseline", "supported_as_baseline"]:
            preserve.append(f"- **{title}：保留为下一轮基线。** 20日和30日全部计划产出率均为正向比较，且各自至少两个区块同向。{explanation}")
        elif statuses == ["needs_optimization", "needs_optimization"]:
            optimize.append(f"- **{title}：需要优化。** 20日和30日均落后于合法比较对象，且各自至少两个区块同向为差。{explanation}")
        else:
            preserve.append(f"- **{title}：结构可暂留，但证据不足。** 20日与30日或 A/B/C 方向没有同时满足稳定保留标准，不能升级为正式能力。{explanation}")

    compression_statuses = [_comparison_status(comparisons, "compression", horizon) for horizon in (20, 30)]
    if "needs_optimization" in compression_statuses:
        optimize.append("- **研究池到最终候选的压缩：需要优化。** 至少一个核心机会窗口的全部计划产出率相对研究池稳定下降；应重做资格门、同类比较和多样性保留，不能用现有压缩原样缩到十只。")
    elif compression_statuses == ["supported_as_baseline", "supported_as_baseline"]:
        preserve.append("- **研究池到最终候选的压缩：可保留为基线。** 20日和30日均提高全部计划产出率，且至少两个区块同向；仍需观察它是否牺牲过多收盘确认机会。")
    else:
        optimize.append("- **研究池到最终候选的压缩：证据不足，仍需优化验证。** 20日、30日或 A/B/C 方向不一致，不能证明现行压缩可靠地保留次日剩余空间。")

    focus_b_effects = comparisons[
        (comparisons["comparison"] == "focus")
        & (comparisons["block"] == "B")
        & (comparisons["metric"] == "touch_yield_all_plans")
    ]
    if not focus_b_effects.empty and (focus_b_effects["effect"] < 0).all():
        optimize.append("- **重点层的跨市场稳定性：需要优化。** 重点总体明显优于候补，但 B 段在 20日和30日盘中产出率都低于候补；应保留重点/候补结构，同时重做不同市场状态下的重点升级条件，不能机械沿用当前判定。")

    route_rows = []
    for horizon in (20, 30):
        values = []
        for policy, label in (("route_hotspot", "热点"), ("route_earnings", "业绩"), ("route_price", "价格")):
            row = _summary_lookup(summary, policy, horizon)
            if row is not None:
                values.append((label, float(row["touch_yield_all_plans"]), float(row["close_yield_all_plans"]), float(row["median_window_min_return"])))
        if values:
            route_rows.append(
                f"{horizon}日：" + "，".join(
                    f"{label}盘中产出 {_fmt_pct(touch)}, 收盘产出 {_fmt_pct(close)}, 窗口最低中位 {_fmt_pct(adverse)}"
                    for label, touch, close, adverse in values
                )
            )
    preserve.append("- **入口分工：保留并行、禁止按入口直接买入。** " + "；".join(route_rows) + "。入口结果用于理解发现来源和路径风险，不能恢复固定加分或投票。")
    optimize.append("- **行动价与退出评价：继续优化。** 本轮已经把形成价改为次日开盘行动价，但仍没有成交队列、滑点、止损和趋势退出规则；盘中达到不能直接写成已兑现收益。")
    return "\n".join(preserve), "\n".join(optimize)


def _headline_section(summary: pd.DataFrame, expanded: pd.DataFrame) -> str:
    if summary.empty:
        return "完整运行后填充。"
    candidate20 = _summary_lookup(summary, "v3_partial_candidate", 20)
    candidate30 = _summary_lookup(summary, "v3_partial_candidate", 30)
    focus20 = _summary_lookup(summary, "v3_partial_candidate", 20, layer="focus")
    focus30 = _summary_lookup(summary, "v3_partial_candidate", 30, layer="focus")
    if any(item is None for item in (candidate20, candidate30, focus20, focus30)):
        return "缺少核心汇总行。"
    lines = [
        f"- **最终候选直接答案：** 20日为 {int(candidate20['touch_successes'])}/{int(candidate20['planned_actions'])}（{_fmt_pct(candidate20['touch_yield_all_plans'])}），30日为 {int(candidate30['touch_successes'])}/{int(candidate30['planned_actions'])}（{_fmt_pct(candidate30['touch_yield_all_plans'])}）。从20日延长到30日多发现 {int(candidate30['touch_successes'] - candidate20['touch_successes'])} 条达到记录；这说明30日仍提供实质机会，不是要求等到第30日卖。",
        f"- **重点组直接答案：** 20日为 {int(focus20['touch_successes'])}/{int(focus20['planned_actions'])}（{_fmt_pct(focus20['touch_yield_all_plans'])}），30日为 {int(focus30['touch_successes'])}/{int(focus30['planned_actions'])}（{_fmt_pct(focus30['touch_yield_all_plans'])}）。",
        f"- **路径质量：** 最终候选20日收盘确认 {int(candidate20['close_successes'])}/{int(candidate20['planned_actions'])}（{_fmt_pct(candidate20['close_yield_all_plans'])}），严格保持3日 {int(candidate20['retain_3_successes'])}/{int(candidate20['planned_actions'])}（{_fmt_pct(candidate20['retain_3_yield_all_plans'])}）；30日对应为 {int(candidate30['close_successes'])}/{int(candidate30['planned_actions'])}（{_fmt_pct(candidate30['close_yield_all_plans'])}）和 {int(candidate30['retain_3_successes'])}/{int(candidate30['planned_actions'])}（{_fmt_pct(candidate30['retain_3_yield_all_plans'])}）。",
        f"- **次日可执行性：** 最终候选20/30日样本均为 {int(candidate20['executable_entries'])}/{int(candidate20['planned_actions'])} 可执行；在这批最终名单中，次日一字涨停或停牌不是主要损失来源。形成日至次日开盘跳空中位为 {_fmt_pct(candidate20['median_formation_to_entry_gap'])}。",
        f"- **风险不能省略：** 最终候选20日窗口最低收益中位为 {_fmt_pct(candidate20['median_window_min_return'])}，30日为 {_fmt_pct(candidate30['median_window_min_return'])}。命中率不能替代回撤和退出规则。",
    ]
    if isinstance(expanded, pd.DataFrame) and not expanded.empty:
        sample = expanded[
            (expanded["policy"] == "v3_partial_candidate")
            & (expanded["horizon"] == 30)
            & expanded["complete_horizon"].fillna(False).astype(bool)
        ].drop_duplicates(["block", "formation_date", "ts_code", "horizon"])
        hits = sample[sample["target_touched"].fillna(False).astype(bool)]
        top_two_hits = int(hits["ts_code"].value_counts().head(2).sum()) if not hits.empty else 0
        lines.append(
            f"- **非独立性：** 322 条最终候选记录来自 {sample['ts_code'].nunique()} 只不同股票和 {sample['formation_date'].nunique()} 个形成日；相邻日期会重复同一股票，命中最多的两只股票合计贡献 {top_two_hits}/{len(hits)} 条30日命中。因此这些比例是开发样本描述，不是322次独立试验。"
        )
    return "\n".join(lines)


def _fmt_pct(value: Any) -> str:
    return "—" if pd.isna(value) else f"{float(value) * 100:.2f}%"


def _markdown_table(frame: pd.DataFrame, columns: list[str], headers: list[str]) -> str:
    if frame.empty:
        return "暂无可报告数据。"
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for item in frame[columns].itertuples(index=False, name=None):
        lines.append("| " + " | ".join("—" if pd.isna(value) else str(value) for value in item) + " |")
    return "\n".join(lines)


def _summary_report_table(summary: pd.DataFrame) -> str:
    if summary.empty:
        return "暂无可报告数据。"
    policies = {
        "research_union": "研究池", "matched_research_control": "研究对照",
        "v3_partial_candidate": "最终候选", "matched_candidate_control": "候选对照",
        "route_hotspot": "热点入口", "route_earnings": "业绩入口", "route_price": "价格入口",
    }
    sample = summary[(summary["block"] == "ALL") & (summary["layer"] == "all") & summary["policy"].isin(policies)].copy()
    sample["对象"] = sample["policy"].map(policies)
    sample["窗口"] = sample["horizon"].astype(int).astype(str) + "日"
    sample["计划"] = sample["planned_actions"].astype(int)
    sample["可执行"] = sample["entry_execution_rate"].map(_fmt_pct)
    sample["盘中达到"] = sample["touch_rate_given_executable"].map(_fmt_pct)
    sample["全部计划产出"] = sample["touch_yield_all_plans"].map(_fmt_pct)
    sample["收盘确认"] = sample["close_rate_given_executable"].map(_fmt_pct)
    sample["保持3日"] = sample["retain_3_rate_given_executable"].map(_fmt_pct)
    sample["次日跳空"] = sample["median_formation_to_entry_gap"].map(_fmt_pct)
    sample["窗口最低"] = sample["median_window_min_return"].map(_fmt_pct)
    return _markdown_table(
        sample.sort_values(["horizon", "policy"]),
        ["窗口", "对象", "计划", "可执行", "盘中达到", "全部计划产出", "收盘确认", "保持3日", "次日跳空", "窗口最低"],
        ["机会窗口", "层级/入口", "计划数", "次日可执行率", "可执行中盘中+20%", "全部计划产出率", "可执行中收盘+20%", "可执行中保持3日", "形成日至次日跳空中位", "窗口最低收益中位"],
    )


def _comparison_report_table(comparisons: pd.DataFrame) -> str:
    if comparisons.empty:
        return "暂无可报告比较。"
    labels = {"discovery": "研究池－研究对照", "compression": "最终候选－研究池", "focus": "重点－候补", "candidate_control": "最终候选－候选对照"}
    metrics = {"touch_rate_given_executable": "可执行中盘中+20%", "touch_yield_all_plans": "全部计划产出率", "close_rate_given_executable": "可执行中收盘+20%", "close_yield_all_plans": "全部计划收盘产出", "retain_3_yield_all_plans": "全部计划保持3日产出"}
    status = {"supported_as_baseline": "支持保留", "needs_optimization": "需要优化", "insufficient_evidence": "证据不足"}
    sample = comparisons[comparisons["block"] == "ALL"].copy()
    sample["窗口"] = sample["horizon"].astype(int).astype(str) + "日"
    sample["比较"] = sample["comparison"].map(labels)
    sample["指标"] = sample["metric"].map(metrics)
    sample["左"] = sample["left_value"].map(_fmt_pct)
    sample["右"] = sample["right_value"].map(_fmt_pct)
    sample["差值"] = sample["effect"].map(_fmt_pct)
    sample["分段"] = sample.apply(lambda row: f"正{int(row['positive_blocks'])}/负{int(row['negative_blocks'])}", axis=1)
    sample["判定"] = sample["status"].map(status)
    return _markdown_table(sample, ["窗口", "比较", "指标", "左", "右", "差值", "分段", "判定"], ["机会窗口", "比较", "指标", "左侧", "右侧", "总体差", "A/B/C", "当前判定"])


def _block_report_table(summary: pd.DataFrame) -> str:
    if summary.empty:
        return "暂无可报告分段。"
    objects = [
        ("research_union", "all", "研究池"),
        ("matched_research_control", "all", "研究对照"),
        ("v3_partial_candidate", "all", "最终候选"),
        ("v3_partial_candidate", "focus", "重点"),
        ("v3_partial_candidate", "candidate", "候补"),
        ("matched_candidate_control", "all", "候选对照"),
    ]
    rows = []
    for policy, layer, label in objects:
        sample = summary[(summary["policy"] == policy) & (summary["layer"] == layer)]
        for item in sample.itertuples(index=False):
            rows.append({
                "窗口": f"{int(item.horizon)}日", "区块": str(item.block), "对象": label,
                "计划": int(item.planned_actions), "可执行": _fmt_pct(item.entry_execution_rate),
                "盘中": _fmt_pct(item.touch_yield_all_plans), "收盘": _fmt_pct(item.close_yield_all_plans),
                "保持3日": _fmt_pct(item.retain_3_yield_all_plans),
            })
    frame = pd.DataFrame(rows).sort_values(["窗口", "对象", "区块"])
    return _markdown_table(frame, list(frame.columns), list(frame.columns))


def _case_report_table(cases: pd.DataFrame) -> str:
    if cases.empty:
        return "无可报告案例。"
    sample = cases.copy()
    for column in ("formation_date", "entry_date"):
        sample[column] = pd.to_datetime(sample[column]).dt.date.astype(str)
    for column in ("formation_to_entry_gap", "pre_touch_min_return", "window_min_return", "terminal_return"):
        sample[column] = sample[column].map(_fmt_pct)
    for column in ("first_touch_session", "first_close_confirm_session"):
        sample[column] = sample[column].map(lambda value: "—" if pd.isna(value) else str(int(value)))
    return _markdown_table(
        sample,
        list(sample.columns),
        ["案例类型", "区块", "形成日", "股票", "层级", "买入日", "买入状态", "次日跳空", "首次盘中+20%", "首次收盘+20%", "目标前最低", "窗口最低", "窗口末快照"],
    )


def generate_report_from_frames(frames: dict[str, Any], path: Path) -> Path:
    summary = frames.get("summary", pd.DataFrame())
    comparisons = frames.get("comparisons", pd.DataFrame())
    cases = frames.get("cases", pd.DataFrame())
    expanded = frames.get("expanded", pd.DataFrame())
    preserve, optimize = _decision_sections(summary, comparisons) if not summary.empty else (
        "完整运行后按冻结比较填充。", "完整运行后按冻结比较填充。"
    )
    lines = [
        "# 股票分析助手 V3：次日开盘行动价值回测结果",
        "",
        "> 写死目标：按冻结名单形成后的下一市场交易日开盘价建立行动基准，检查从该价格起在 20/30 个交易日机会窗口内是否上涨至少 20%。不重选股票、不优化规则。",
        "",
        "## 1. 口径边界",
        "",
        "本报告的行动基准是**次日开盘行动价**。20日机会窗口和30日机会窗口都从买入日开始，买入日计第1日；它们不是固定卖出日。盘中达到 +20% 是主要发现结果，收盘确认和保持曲线用于判断路径质量。",
        "",
        "一字涨停和停牌/无报价不进入可执行条件分母，但仍保留在全部计划行动分母。盘中最高价被触及不代表普通用户一定能够兑现；本轮没有止损、趋势退出、仓位、成本和滑点规则。",
        "",
        "## 2. 直接回答",
        "",
        _headline_section(summary, expanded),
        "",
        "## 3. 总体结果",
        "",
        _summary_report_table(summary),
        "",
        "`可执行中盘中+20%` 回答成功买入后是否曾达到目标；`全部计划产出率` 还把一字涨停和停牌等无法按计划买入的记录留在分母，更接近系统实际交付。",
        "",
        "## 4. 固定比较",
        "",
        _comparison_report_table(comparisons),
        "",
        "## 5. A/B/C 分段明细",
        "",
        _block_report_table(summary),
        "",
        "## 6. 哪些保留",
        "",
        preserve,
        "",
        "支持保留只表示值得进入下一轮基线，不表示已经成为正式推荐能力。",
        "",
        "## 7. 哪些需要优化",
        "",
        optimize,
        "",
        "窗口末收盘只作补充，不参与成功判定。目标日内高低价的先后顺序无法由日线确定，因此目标前最低收益不把首次触及当日的最低价冒充为触及前回撤。",
        "",
        "## 8. 四组核心关系的原始数字",
        "",
        _pair_sentence(summary, "research_union", "matched_research_control", "研究池", "研究对照") if not summary.empty else "—",
        "",
        _pair_sentence(summary, "v3_partial_candidate", "research_union", "最终候选", "研究池") if not summary.empty else "—",
        "",
        _pair_sentence(summary, "v3_partial_candidate", "matched_candidate_control", "最终候选", "候选对照") if not summary.empty else "—",
        "",
        _pair_sentence(summary, "v3_partial_candidate", "v3_partial_candidate", "重点", "候补", left_layer="focus", right_layer="candidate") if not summary.empty else "—",
        "",
        "## 9. 代表性案例",
        "",
        _case_report_table(cases) if isinstance(cases, pd.DataFrame) and not cases.empty else "完整运行后列示成功、冲高回落、深回撤和不可执行案例。",
        "",
        "## 10. 当前不能回答",
        "",
        "没有冻结退出和成本规则，因此不能计算策略净值，也不能把盘中最高价命中率写成用户实际兑现收益率。现有形成日已参与框架讨论，本轮是开发样本行动价值诊断，不是全新样本外证明。",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _independent_summary_checks(
    expanded: pd.DataFrame,
    summary: pd.DataFrame,
) -> tuple[bool, list[dict[str, Any]]]:
    checks: list[dict[str, Any]] = []
    keys = (
        ("research_union", "all"),
        ("matched_research_control", "all"),
        ("v3_partial_candidate", "all"),
        ("v3_partial_candidate", "focus"),
        ("v3_partial_candidate", "candidate"),
        ("matched_candidate_control", "all"),
    )
    for horizon in (20, 30):
        for policy, layer in keys:
            sample = expanded[
                (expanded["policy"] == policy)
                & (expanded["horizon"] == horizon)
                & expanded["complete_horizon"].fillna(False).astype(bool)
            ].copy()
            if layer == "all":
                sample = sample.drop_duplicates(["formation_date", "ts_code", "horizon"])
            else:
                sample = sample[sample["layer"] == layer]
            expected = _summary_lookup(summary, policy, horizon, layer=layer)
            if expected is None:
                checks.append({"policy": policy, "layer": layer, "horizon": horizon, "passed": False, "reason": "missing summary"})
                continue
            executable = sample["executable_entry"].astype(bool)
            touch = sample["target_touched"].fillna(False).astype(bool)
            close = sample["close_confirmed"].fillna(False).astype(bool)
            values = {
                "planned_actions": int(len(sample)),
                "executable_entries": int(executable.sum()),
                "touch_successes": int((executable & touch).sum()),
                "close_successes": int((executable & close).sum()),
                "retain_3_successes": int((sample["retain_3_observable"].astype(bool) & sample["retain_3"].fillna(False).astype(bool)).sum()),
            }
            passed = all(int(expected[field]) == value for field, value in values.items())
            checks.append({
                "policy": policy, "layer": layer, "horizon": horizon,
                "passed": bool(passed), "recomputed": values,
            })
    return bool(checks and all(item["passed"] for item in checks)), checks


def run_validation(config: ActionConfig) -> Path:
    started = time.perf_counter()
    output = prepare_output_root(config)
    source_before = _tree_signature(config.source_experiment_root)
    _write_json(
        {
            "experiment_id": config.experiment_id,
            "goal": "validate frozen selections from next-market-session adjusted open over 20/30-session opportunity windows",
            "source_experiment_root": str(config.source_experiment_root),
            "warehouse_root": str(config.warehouse_root),
            "output_root": str(config.output_root),
            "horizons": list(config.horizons),
            "target_return": config.target_return,
            "retention_windows": list(config.retention_windows),
            "entry_delay_market_sessions": config.entry_delay_market_sessions,
            "entry_price_field": config.entry_price_field,
            "entry_day_counts_as_session_one": config.entry_day_counts_as_session_one,
            "exclude_one_price_limit_up": config.exclude_one_price_limit_up,
            "rule_optimization_allowed": config.rule_optimization_allowed,
            "usb_free_bytes_before": shutil.disk_usage(output).free,
        },
        output / "manifests" / "config_snapshot.json",
    )

    unique, expanded, input_paths = build_action_paths(config)
    contracts = validate_action_contracts(unique, retention_windows=config.retention_windows)
    summary = summarize_actions(
        expanded,
        retention_windows=config.retention_windows,
        supported_policies=config.supported_policies,
    )
    comparisons = build_comparisons(summary)
    cases = build_cases(expanded)
    summary_recomputable, independent_checks = _independent_summary_checks(expanded, summary)

    _write_parquet(unique, output / "tables" / "unique_action_paths.parquet")
    _write_parquet(expanded, output / "tables" / "selection_action_outcomes.parquet")
    _write_parquet(summary, output / "tables" / "action_summary.parquet")
    _write_parquet(comparisons, output / "tables" / "fixed_comparisons.parquet")
    _write_parquet(cases, output / "tables" / "case_studies.parquet")

    report_path = output / "reports" / "v3-next-day-entry-validation-results.md"
    generate_report_from_frames(
        {"summary": summary, "comparisons": comparisons, "cases": cases, "expanded": expanded},
        report_path,
    )
    source_after = _tree_signature(config.source_experiment_root)
    runtime_seconds = time.perf_counter() - started
    formation_counts = {
        block: int(unique.loc[unique["block"] == block, "formation_date"].nunique())
        for block in EXPECTED_BLOCKS
    }
    status_counts = {
        str(key): int(value) for key, value in unique.drop_duplicates(
            ["block", "formation_date", "ts_code"]
        )["entry_status"].value_counts(dropna=False).items()
    }
    complete_counts = {
        str(int(horizon)): int(
            unique.loc[unique["horizon"] == horizon, "complete_horizon"].astype(bool).sum()
        )
        for horizon in config.horizons
    }
    quality: dict[str, Any] = {
        "formation_dates_90": int(unique["formation_date"].nunique()) == 90,
        "blocks_30_each": formation_counts == {"A": 30, "B": 30, "C": 30},
        **contracts,
        "summary_recomputable": summary_recomputable,
        "independent_summary_checks": independent_checks,
        "source_directory_unchanged": source_before["signature_sha256"] == source_after["signature_sha256"],
        "runtime_within_limit": runtime_seconds <= config.runtime_stop_minutes * 60,
        "runtime_seconds": runtime_seconds,
        "formation_date_counts": formation_counts,
        "unique_path_rows": int(len(unique)),
        "expanded_rows": int(len(expanded)),
        "entry_status_counts_unique_actions": status_counts,
        "complete_horizon_counts": complete_counts,
        "source_signature_before": source_before,
        "source_signature_after": source_after,
    }
    boolean_checks = [value for value in quality.values() if isinstance(value, bool)]
    quality["all_passed"] = bool(boolean_checks and all(boolean_checks))
    _write_json(quality, output / "manifests" / "quality_checks.json")
    _write_json(
        {"inputs": _file_manifest(input_paths)},
        output / "manifests" / "input_manifest.json",
    )
    _write_json(
        {
            "status": "completed" if quality["all_passed"] else "failed_quality_checks",
            "report": str(report_path),
            "runtime_seconds": runtime_seconds,
            "all_quality_checks_passed": quality["all_passed"],
        },
        output / "manifests" / "run_status.json",
    )
    if not quality["all_passed"]:
        raise RuntimeError("action validation completed with failed quality checks")
    return report_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    args = parser.parse_args(argv)
    config = load_config(args.config)
    report = run_validation(config)
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
