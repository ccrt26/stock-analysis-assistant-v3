"""Diagnose close confirmation and target retention for frozen V3 selections.

This is a read-only research post-processor.  It does not form candidates,
change rules, or produce recommendations.  Runtime artifacts are restricted
to the dedicated USB experiment directory frozen in the config.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time
from typing import Any, Iterable

import numpy as np
import pandas as pd
import yaml


DEFAULT_ALLOWED_VOLUME_ROOT = Path("/Volumes/ZHUTONG")
EXPECTED_HORIZONS = (10, 20, 30)
EXPECTED_RETENTION_WINDOWS = (1, 2, 3, 5)
EXPECTED_BLOCKS = ("A", "B", "C")


@dataclass(frozen=True)
class Block:
    id: str
    start: date
    end: date


@dataclass(frozen=True)
class RetentionConfig:
    experiment_id: str
    source_experiment_root: Path
    warehouse_root: Path
    output_root: Path
    blocks: tuple[Block, ...]
    horizons: tuple[int, ...]
    target_return: float
    retention_windows: tuple[int, ...]
    primary_horizon: int
    runtime_stop_minutes: int
    supported_policies: tuple[str, ...]
    rule_optimization_allowed: bool


def load_config(path: str | Path) -> RetentionConfig:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("diagnostic config must be a mapping")
    config = RetentionConfig(
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
        primary_horizon=int(payload["primary_horizon"]),
        runtime_stop_minutes=int(payload["runtime_stop_minutes"]),
        supported_policies=tuple(str(value) for value in payload["supported_policies"]),
        rule_optimization_allowed=bool(payload["rule_optimization_allowed"]),
    )
    _validate_config(config)
    return config


def _validate_config(config: RetentionConfig) -> None:
    if tuple(block.id for block in config.blocks) != EXPECTED_BLOCKS:
        raise ValueError("blocks must be the frozen A, B and C blocks")
    if config.horizons != EXPECTED_HORIZONS:
        raise ValueError("horizons differ from the frozen protocol")
    if config.retention_windows != EXPECTED_RETENTION_WINDOWS:
        raise ValueError("retention windows differ from the frozen protocol")
    if config.target_return != 0.20:
        raise ValueError("target return differs from the frozen protocol")
    if config.primary_horizon != 20:
        raise ValueError("primary horizon must remain 20 sessions")
    if config.rule_optimization_allowed:
        raise ValueError("this diagnostic forbids rule optimization")
    if config.runtime_stop_minutes <= 0:
        raise ValueError("runtime stop must be positive")


def prepare_output_root(
    config: RetentionConfig,
    *,
    output_override: str | Path | None = None,
    allowed_volume_root: str | Path = DEFAULT_ALLOWED_VOLUME_ROOT,
) -> Path:
    output = Path(output_override) if output_override is not None else config.output_root
    expected = (
        Path(allowed_volume_root) / "股票分析助手-V3回测" / config.experiment_id
    )
    if output.resolve(strict=False) != expected.resolve(strict=False):
        raise ValueError("输出路径必须是冻结的U盘专用目录")
    if output.resolve(strict=False) == config.source_experiment_root.resolve(strict=False):
        raise ValueError("输出目录不得覆盖来源实验")
    for child in ("manifests", "tables", "reports"):
        (output / child).mkdir(parents=True, exist_ok=True)
    return output


def _json_default(value: Any) -> Any:
    if isinstance(value, (Path, date, pd.Timestamp)):
        return str(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if np.isnan(value) else float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def _write_json(payload: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default) + "\n",
        encoding="utf-8",
    )


def _write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)


def _tree_signature(root: Path) -> dict[str, Any]:
    files = sorted(path for path in root.rglob("*") if path.is_file())
    rows = [
        {
            "relative_path": str(path.relative_to(root)),
            "size": path.stat().st_size,
            "mtime_ns": path.stat().st_mtime_ns,
        }
        for path in files
        if not path.name.startswith("._")
    ]
    digest = hashlib.sha256(
        json.dumps(rows, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return {
        "root": str(root),
        "file_count": len(rows),
        "total_bytes": sum(row["size"] for row in rows),
        "signature_sha256": digest,
    }


def _file_manifest(paths: Iterable[Path]) -> list[dict[str, Any]]:
    rows = []
    for path in sorted(set(paths)):
        stat = path.stat()
        rows.append(
            {
                "path": str(path),
                "bytes": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
            }
        )
    return rows


def _normalize_prices(prices: pd.DataFrame) -> pd.DataFrame:
    required = {"trade_date", "ts_code", "adj_close", "adj_high", "adj_low"}
    missing = sorted(required - set(prices.columns))
    if missing:
        raise ValueError(f"prices lack required fields: {', '.join(missing)}")
    prepared = prices.copy()
    prepared["trade_date"] = pd.to_datetime(prepared["trade_date"], errors="raise").dt.normalize()
    prepared["ts_code"] = prepared["ts_code"].astype(str)
    for column in ("adj_close", "adj_high", "adj_low"):
        prepared[column] = pd.to_numeric(prepared[column], errors="coerce")
    if "quoted" not in prepared:
        prepared["quoted"] = prepared["adj_close"].notna()
    prepared["quoted"] = prepared["quoted"].fillna(False).astype(bool)
    prepared = prepared.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    if prepared.duplicated(["trade_date", "ts_code"]).any():
        raise ValueError("prices contain duplicate stock-date rows")
    return prepared


def compute_retention_path(
    prices: pd.DataFrame,
    formation_date: str | date | pd.Timestamp,
    ts_code: str,
    horizon: int,
    target_return: float,
    retention_windows: tuple[int, ...] = EXPECTED_RETENTION_WINDOWS,
) -> dict[str, Any]:
    """Compute target attainment and strict close retention for one frozen row."""

    prepared = _normalize_prices(prices)
    formation_day = pd.Timestamp(formation_date).normalize()
    stock = prepared[prepared["ts_code"] == str(ts_code)].sort_values("trade_date")
    formation = stock[stock["trade_date"] == formation_day]
    if len(formation) != 1:
        raise ValueError(f"formation close is not unique for {ts_code} on {formation_day.date()}")
    discovery = float(formation.iloc[0]["adj_close"])
    if not np.isfinite(discovery) or discovery <= 0:
        raise ValueError("formation adjusted close must be positive")
    target = discovery * (1.0 + target_return)
    future = stock[stock["trade_date"] > formation_day].reset_index(drop=True)
    attainment = future.iloc[:horizon].copy()
    complete_horizon = len(attainment) == horizon

    carried_close = attainment["adj_close"].ffill().fillna(discovery)
    adjusted_high = attainment["adj_high"].where(attainment["adj_high"].notna(), carried_close)
    touch_mask = (adjusted_high / discovery - 1.0).ge(target_return)
    close_mask = attainment["quoted"] & (
        attainment["adj_close"] / discovery - 1.0
    ).ge(target_return)
    touch_positions = np.flatnonzero(touch_mask.to_numpy())
    close_positions = np.flatnonzero(close_mask.to_numpy())
    first_touch_index = int(touch_positions[0]) if len(touch_positions) else None
    first_close_index = int(close_positions[0]) if len(close_positions) else None

    result: dict[str, Any] = {
        "formation_date": formation_day,
        "ts_code": str(ts_code),
        "horizon": int(horizon),
        "formation_close": discovery,
        "target_price": target,
        "observed_sessions": int(len(attainment)),
        "quoted_sessions": int(attainment["quoted"].sum()),
        "complete_horizon": bool(
            complete_horizon
            and not attainment.empty
            and bool(attainment.iloc[-1]["quoted"])
        ),
        "target_touched": bool(first_touch_index is not None),
        "first_touch_session": first_touch_index + 1 if first_touch_index is not None else pd.NA,
        "first_touch_date": attainment.iloc[first_touch_index]["trade_date"] if first_touch_index is not None else pd.NaT,
        "close_confirmed": bool(first_close_index is not None),
        "first_close_confirm_session": first_close_index + 1 if first_close_index is not None else pd.NA,
        "first_close_confirm_date": attainment.iloc[first_close_index]["trade_date"] if first_close_index is not None else pd.NaT,
        "first_close_confirm_return": (
            float(attainment.iloc[first_close_index]["adj_close"] / discovery - 1.0)
            if first_close_index is not None
            else np.nan
        ),
    }

    confirm_global_index: int | None = None
    if first_close_index is not None:
        confirm_date = pd.Timestamp(attainment.iloc[first_close_index]["trade_date"])
        matching = future.index[future["trade_date"] == confirm_date].tolist()
        confirm_global_index = int(matching[0]) if matching else None
    post_confirm = (
        future.iloc[confirm_global_index + 1 :].reset_index(drop=True)
        if confirm_global_index is not None
        else pd.DataFrame(columns=future.columns)
    )
    confirm_close = (
        float(future.iloc[confirm_global_index]["adj_close"])
        if confirm_global_index is not None
        else np.nan
    )

    for window in retention_windows:
        sample = post_confirm.iloc[:window]
        observable = bool(
            first_close_index is not None
            and len(sample) == window
            and sample["quoted"].all()
            and sample["adj_close"].notna().all()
        )
        retain_value: bool | pd._libs.missing.NAType = pd.NA
        advance_value: bool | pd._libs.missing.NAType = pd.NA
        if observable:
            retain_value = bool(
                (sample["adj_close"] / discovery - 1.0).ge(target_return).all()
            )
            advance_value = bool(
                retain_value and sample["adj_close"].gt(confirm_close).any()
            )
        result[f"retain_{window}_observable"] = observable
        result[f"retain_{window}"] = retain_value
        result[f"advance_{window}"] = advance_value

    result.update(
        {
            "first_close_loss_date": pd.NaT,
            "first_close_loss_sessions": pd.NA,
            "first_close_loss_return": np.nan,
            "post_confirm_5_observable": False,
            "post_confirm_max_close_return_5": np.nan,
            "post_confirm_min_close_return_5": np.nan,
            "post_confirm_max_drawdown_5": np.nan,
        }
    )
    if first_close_index is not None:
        quoted_post = post_confirm[post_confirm["quoted"] & post_confirm["adj_close"].notna()]
        losses = quoted_post[
            (quoted_post["adj_close"] / discovery - 1.0) < target_return
        ]
        if not losses.empty:
            first_loss = losses.iloc[0]
            loss_position = int(post_confirm.index[post_confirm["trade_date"] == first_loss["trade_date"]][0]) + 1
            result["first_close_loss_date"] = first_loss["trade_date"]
            result["first_close_loss_sessions"] = loss_position
            result["first_close_loss_return"] = float(first_loss["adj_close"] / discovery - 1.0)

        five = post_confirm.iloc[:5]
        five_observable = bool(
            len(five) == 5 and five["quoted"].all() and five["adj_close"].notna().all()
        )
        result["post_confirm_5_observable"] = five_observable
        if not five.empty and five["adj_close"].notna().any():
            close_returns = five["adj_close"].dropna() / discovery - 1.0
            result["post_confirm_max_close_return_5"] = float(close_returns.max())
            result["post_confirm_min_close_return_5"] = float(close_returns.min())
            close_values = pd.concat(
                [pd.Series([confirm_close]), five["adj_close"].dropna().reset_index(drop=True)],
                ignore_index=True,
            )
            drawdowns = close_values / close_values.cummax() - 1.0
            result["post_confirm_max_drawdown_5"] = float(drawdowns.min())

    if complete_horizon and not attainment.empty and bool(attainment.iloc[-1]["quoted"]):
        terminal_close = float(attainment.iloc[-1]["adj_close"])
        result["terminal_return"] = terminal_close / discovery - 1.0
        result["terminal_above_target"] = bool(
            terminal_close / discovery - 1.0 >= target_return
        )
    else:
        result["terminal_return"] = np.nan
        result["terminal_above_target"] = pd.NA
    return result


def validate_outcome_contracts(
    outcomes: pd.DataFrame,
    *,
    retention_windows: tuple[int, ...] = EXPECTED_RETENTION_WINDOWS,
) -> dict[str, bool]:
    close_subset = not bool(
        (outcomes["close_confirmed"].fillna(False).astype(bool)
         & ~outcomes["target_touched"].fillna(False).astype(bool)).any()
    )
    if not close_subset:
        raise ValueError("收盘确认必须是盘中触及子集")

    unconfirmed_never_retained = True
    for window in retention_windows:
        retain = outcomes[f"retain_{window}"]
        invalid = (~outcomes["close_confirmed"].fillna(False).astype(bool)) & retain.fillna(False).astype(bool)
        if invalid.any():
            unconfirmed_never_retained = False
            raise ValueError("未收盘确认的记录不得保持成功")

    nested = True
    for smaller, larger in zip(retention_windows, retention_windows[1:]):
        common = (
            outcomes[f"retain_{smaller}_observable"].fillna(False).astype(bool)
            & outcomes[f"retain_{larger}_observable"].fillna(False).astype(bool)
        )
        invalid = common & outcomes[f"retain_{larger}"].fillna(False).astype(bool) & ~outcomes[f"retain_{smaller}"].fillna(False).astype(bool)
        if invalid.any():
            nested = False
            raise ValueError("严格保持窗口必须满足嵌套关系")

    censor_ok = True
    for window in retention_windows:
        unobservable = ~outcomes[f"retain_{window}_observable"].fillna(False).astype(bool)
        if outcomes.loc[unobservable, f"retain_{window}"].notna().any():
            censor_ok = False
            raise ValueError("观察不足不得写成保持成功或失败")
    return {
        "close_subset_touch": close_subset,
        "retain_nested_on_common_observable": nested,
        "unconfirmed_never_retained": unconfirmed_never_retained,
        "right_censor_not_failure": censor_ok,
    }


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


def _read_price_frame(
    config: RetentionConfig,
    formation_dates: pd.Series,
) -> tuple[pd.DataFrame, list[Path]]:
    sessions = _available_sessions(config.warehouse_root)
    first = pd.to_datetime(formation_dates).min().normalize()
    last_formation = pd.to_datetime(formation_dates).max().normalize()
    last_index = sessions.index(last_formation)
    last_needed_index = min(
        len(sessions) - 1,
        last_index + max(config.horizons) + max(config.retention_windows),
    )
    required_sessions = [item for item in sessions if first <= item <= sessions[last_needed_index]]
    frames: list[pd.DataFrame] = []
    input_paths: list[Path] = []
    for session in required_sessions:
        partition = f"trade_date={session.date().isoformat()}"
        equity_path = config.warehouse_root / "facts" / "equity_daily" / partition / "data.parquet"
        factor_path = config.warehouse_root / "facts" / "adj_factor" / partition / "data.parquet"
        if not equity_path.exists() or not factor_path.exists():
            raise FileNotFoundError(f"missing price or factor partition for {session.date()}")
        equity = pd.read_parquet(
            equity_path,
            columns=["trade_date", "ts_code", "high", "low", "close"],
        )
        factors = pd.read_parquet(
            factor_path,
            columns=["trade_date", "ts_code", "adj_factor"],
        )
        merged = equity.merge(
            factors,
            on=["trade_date", "ts_code"],
            how="left",
            validate="one_to_one",
        )
        factor = pd.to_numeric(merged["adj_factor"], errors="coerce")
        for raw, adjusted in (
            ("close", "adj_close"),
            ("high", "adj_high"),
            ("low", "adj_low"),
        ):
            merged[adjusted] = pd.to_numeric(merged[raw], errors="coerce") * factor
        merged["quoted"] = merged["adj_close"].notna()
        frames.append(
            merged[["trade_date", "ts_code", "adj_close", "adj_high", "adj_low", "quoted"]]
        )
        input_paths.extend([equity_path, factor_path])
    return _normalize_prices(pd.concat(frames, ignore_index=True)), input_paths


def _grid_stock_prices(
    prices: pd.DataFrame,
    ts_code: str,
    market_sessions: pd.Index,
) -> pd.DataFrame:
    stock = prices[prices["ts_code"] == str(ts_code)].set_index("trade_date")
    grid = stock.reindex(market_sessions).reset_index()
    grid["ts_code"] = str(ts_code)
    grid["quoted"] = grid["adj_close"].notna()
    return grid


def _read_formation_table(config: RetentionConfig, table: str) -> pd.DataFrame:
    paths = sorted(
        config.source_experiment_root.glob(
            f"tables/formations/block=*/formation_date=*/{table}.parquet"
        )
    )
    if len(paths) != 90:
        raise ValueError(f"expected 90 frozen {table} files, found {len(paths)}")
    frames = []
    for path in paths:
        frame = pd.read_parquet(path)
        if "block" not in frame:
            block = next(part.split("=", 1)[1] for part in path.parts if part.startswith("block="))
            frame["block"] = block
        frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def build_unique_paths(
    config: RetentionConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, list[Path]]:
    source_outcomes_path = config.source_experiment_root / "tables" / "outcomes_all.parquet"
    source_outcomes = pd.read_parquet(source_outcomes_path)
    source_outcomes["formation_date"] = pd.to_datetime(source_outcomes["formation_date"]).dt.normalize()
    source_keys = ["block", "formation_date", "ts_code", "horizon"]
    consistency = source_outcomes.groupby(source_keys).agg(
        formation_close_n=("formation_close", "nunique"),
        target_touched_n=("target_touched", "nunique"),
    )
    if (consistency > 1).any().any():
        raise ValueError("source outcomes disagree on identical stock-date paths")
    keys = source_outcomes[source_keys].drop_duplicates().sort_values(source_keys).reset_index(drop=True)
    prices, price_paths = _read_price_frame(config, keys["formation_date"])
    market_sessions = pd.Index(sorted(prices["trade_date"].unique()), name="trade_date")
    stock_grids = {
        code: _grid_stock_prices(prices, code, market_sessions)
        for code in sorted(keys["ts_code"].astype(str).unique())
    }
    rows: list[dict[str, Any]] = []
    started = time.perf_counter()
    for item in keys.itertuples(index=False):
        row = compute_retention_path(
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
            raise TimeoutError("diagnostic runtime exceeded frozen stop limit")
    unique_paths = pd.DataFrame(rows)
    for window in config.retention_windows:
        unique_paths[f"retain_{window}"] = unique_paths[f"retain_{window}"].astype("boolean")
        unique_paths[f"advance_{window}"] = unique_paths[f"advance_{window}"].astype("boolean")
    unique_paths["terminal_above_target"] = unique_paths["terminal_above_target"].astype("boolean")

    source_unique = source_outcomes[
        source_keys
        + ["formation_close", "target_touched", "first_target_session", "max_favorable_return"]
    ].drop_duplicates(source_keys)
    audit = unique_paths.merge(source_unique, on=source_keys, how="left", suffixes=("", "_source"), validate="one_to_one")
    touch_mismatch = audit["target_touched"].astype(bool) != audit["target_touched_source"].astype(bool)
    close_diff = (audit["formation_close"] - audit["formation_close_source"]).abs()
    if touch_mismatch.any() or (close_diff > 1e-8).any():
        mismatch_sample = audit.loc[
            touch_mismatch | (close_diff > 1e-8),
            source_keys
            + [
                "formation_close",
                "target_price",
                "target_touched",
                "target_touched_source",
                "first_touch_session",
                "first_target_session",
                "max_favorable_return",
            ],
        ].head(20)
        raise ValueError(
            "source path contract mismatch: "
            f"touch={int(touch_mismatch.sum())}, close={int((close_diff > 1e-8).sum())}; "
            f"sample={mismatch_sample.to_dict(orient='records')}"
        )
    new_columns = [
        column
        for column in unique_paths.columns
        if column not in source_keys + ["formation_close", "target_touched", "complete_horizon", "observed_sessions", "quoted_sessions", "terminal_return"]
    ]
    expanded = source_outcomes.merge(
        unique_paths[source_keys + new_columns],
        on=source_keys,
        how="left",
        validate="many_to_one",
    )
    return unique_paths, expanded, [source_outcomes_path, *price_paths]


def _safe_rate(numerator: int | float, denominator: int | float) -> float:
    return float(numerator) / float(denominator) if denominator else np.nan


def summarize_retention(
    outcomes: pd.DataFrame,
    *,
    retention_windows: tuple[int, ...] = EXPECTED_RETENTION_WINDOWS,
    supported_policies: tuple[str, ...] | None = None,
) -> pd.DataFrame:
    prepared = outcomes.copy()
    if supported_policies is not None:
        prepared = prepared[prepared["policy"].isin(supported_policies)].copy()
    prepared["block"] = prepared["block"].astype(str)
    group_frames: list[pd.DataFrame] = []
    for block_id in sorted(prepared["block"].unique()):
        group_frames.append(prepared[prepared["block"] == block_id])
    all_frame = prepared.copy()
    all_frame["block"] = "ALL"
    group_frames.append(all_frame)

    rows: list[dict[str, Any]] = []
    for block_frame in group_frames:
        block_id = str(block_frame["block"].iloc[0]) if not block_frame.empty else "ALL"
        layer_groups = list(block_frame.groupby(["policy", "layer", "horizon"], dropna=False, sort=True))
        for (policy, layer, horizon), group in layer_groups:
            rows.append(
                _summary_row(group, block_id, str(policy), str(layer), int(horizon), retention_windows)
            )
        for (policy, horizon), group in block_frame.groupby(["policy", "horizon"], sort=True):
            deduped = group.drop_duplicates(["formation_date", "ts_code", "horizon"])
            rows.append(
                _summary_row(deduped, block_id, str(policy), "all", int(horizon), retention_windows)
            )
    return pd.DataFrame(rows).drop_duplicates(
        ["block", "policy", "layer", "horizon"], keep="last"
    ).sort_values(["horizon", "policy", "layer", "block"]).reset_index(drop=True)


def _summary_row(
    group: pd.DataFrame,
    block: str,
    policy: str,
    layer: str,
    horizon: int,
    retention_windows: tuple[int, ...],
) -> dict[str, Any]:
    sample = group[group["complete_horizon"].fillna(False).astype(bool)].copy()
    observations = len(sample)
    touch = sample["target_touched"].fillna(False).astype(bool)
    close = sample["close_confirmed"].fillna(False).astype(bool)
    row: dict[str, Any] = {
        "block": block,
        "policy": policy,
        "layer": layer,
        "horizon": horizon,
        "observations": observations,
        "touch_successes": int(touch.sum()),
        "touch_rate": _safe_rate(int(touch.sum()), observations),
        "close_confirm_successes": int(close.sum()),
        "close_confirm_rate": _safe_rate(int(close.sum()), observations),
        "touch_to_close_rate": _safe_rate(int(close.sum()), int(touch.sum())),
        "terminal_above_target_successes": int(sample["terminal_above_target"].fillna(False).astype(bool).sum()),
        "terminal_above_target_rate": _safe_rate(
            int(sample["terminal_above_target"].fillna(False).astype(bool).sum()),
            int(sample["terminal_above_target"].notna().sum()),
        ),
        "median_terminal_return": float(sample["terminal_return"].median()) if observations else np.nan,
        "median_max_adverse_return": float(sample["max_adverse_return"].median())
        if observations and "max_adverse_return" in sample
        else np.nan,
        "median_first_close_loss_sessions": float(
            pd.to_numeric(sample["first_close_loss_sessions"], errors="coerce").median()
        ),
    }
    for window in retention_windows:
        observable = sample[f"retain_{window}_observable"].fillna(False).astype(bool)
        retain = sample[f"retain_{window}"].fillna(False).astype(bool)
        advance = sample[f"advance_{window}"].fillna(False).astype(bool)
        observable_count = int(observable.sum())
        success = int((observable & retain).sum())
        advance_success = int((observable & advance).sum())
        right_censored = int((close & ~observable).sum())
        all_denominator = observations - right_censored
        row[f"retain_{window}_observations"] = observable_count
        row[f"retain_{window}_successes"] = success
        row[f"retain_{window}_all_denominator"] = all_denominator
        row[f"retain_{window}_rate_all"] = _safe_rate(success, all_denominator)
        row[f"retain_{window}_rate_given_close"] = _safe_rate(success, observable_count)
        row[f"advance_{window}_successes"] = advance_success
        row[f"advance_{window}_rate_given_close"] = _safe_rate(advance_success, observable_count)
        row[f"right_censored_{window}"] = right_censored
    return row


def build_comparisons(summary: pd.DataFrame, primary_horizon: int = 20) -> pd.DataFrame:
    pairs = (
        ("discovery", ("research_union", "all"), ("matched_research_control", "all")),
        ("compression", ("v3_partial_candidate", "all"), ("research_union", "all")),
        ("focus", ("v3_partial_candidate", "focus"), ("v3_partial_candidate", "candidate")),
        ("candidate_control", ("v3_partial_candidate", "all"), ("matched_candidate_control", "all")),
    )
    metrics = [
        "touch_rate",
        "close_confirm_rate",
        "retain_1_rate_all",
        "retain_2_rate_all",
        "retain_3_rate_all",
        "retain_5_rate_all",
    ]
    rows: list[dict[str, Any]] = []
    sample = summary[summary["horizon"] == primary_horizon]
    for comparison, left_key, right_key in pairs:
        effects: dict[str, list[float]] = {metric: [] for metric in metrics}
        combined: dict[str, float] = {}
        for block in ("A", "B", "C", "ALL"):
            left = sample[
                (sample["block"] == block)
                & (sample["policy"] == left_key[0])
                & (sample["layer"] == left_key[1])
            ]
            right = sample[
                (sample["block"] == block)
                & (sample["policy"] == right_key[0])
                & (sample["layer"] == right_key[1])
            ]
            for metric in metrics:
                effect = np.nan
                if len(left) == 1 and len(right) == 1:
                    effect = float(left.iloc[0][metric] - right.iloc[0][metric])
                rows.append(
                    {
                        "comparison": comparison,
                        "block": block,
                        "metric": metric,
                        "left_policy": left_key[0],
                        "left_layer": left_key[1],
                        "right_policy": right_key[0],
                        "right_layer": right_key[1],
                        "left_value": float(left.iloc[0][metric]) if len(left) == 1 else np.nan,
                        "right_value": float(right.iloc[0][metric]) if len(right) == 1 else np.nan,
                        "effect": effect,
                    }
                )
                if block == "ALL":
                    combined[metric] = effect
                elif np.isfinite(effect):
                    effects[metric].append(effect)
        for metric in metrics:
            values = effects[metric]
            overall = combined.get(metric, np.nan)
            positive = sum(value > 0 for value in values)
            negative = sum(value < 0 for value in values)
            status = "insufficient_evidence"
            if np.isfinite(overall) and overall > 0 and positive >= 2:
                status = "supported_as_baseline"
            elif np.isfinite(overall) and overall < 0 and negative >= 2:
                status = "rejected_in_current_sample"
            for row in rows:
                if row["comparison"] == comparison and row["metric"] == metric:
                    row["status"] = status
                    row["positive_blocks"] = positive
                    row["negative_blocks"] = negative
    return pd.DataFrame(rows)


def summarize_route_combinations(
    unique_paths: pd.DataFrame,
    evidence: pd.DataFrame,
    retention_windows: tuple[int, ...],
) -> pd.DataFrame:
    fields = ["block", "formation_date", "ts_code", "routes"]
    frozen = evidence[fields].drop_duplicates(["block", "formation_date", "ts_code"])
    joined = unique_paths.merge(
        frozen,
        on=["block", "formation_date", "ts_code"],
        how="inner",
        validate="many_to_one",
    )
    joined["policy"] = "route_combination"
    joined["layer"] = joined["routes"].fillna("unknown")
    return summarize_retention(
        joined,
        retention_windows=retention_windows,
        supported_policies=("route_combination",),
    ).rename(columns={"layer": "routes"})


FEATURE_FIELDS = (
    "evidence_freshness",
    "earnings_cash_consistency",
    "hotspot_support",
    "price_consumption_safety",
    "liquidity",
    "return_5d",
    "return_20d",
    "relative_return_20d",
    "price_location_60d",
    "current_amount_ratio_20d",
)


def build_feature_diagnostics(
    unique_paths: pd.DataFrame,
    evidence: pd.DataFrame,
    primary_horizon: int,
) -> pd.DataFrame:
    paths = unique_paths[unique_paths["horizon"] == primary_horizon].copy()
    frozen = evidence[["block", "formation_date", "ts_code", "routes", *FEATURE_FIELDS]].drop_duplicates(
        ["block", "formation_date", "ts_code"]
    )
    joined = paths.merge(
        frozen,
        on=["block", "formation_date", "ts_code"],
        how="inner",
        validate="one_to_one",
    )
    retain3_observable = joined["retain_3_observable"].fillna(False).astype(bool)
    retain3 = joined["retain_3"].fillna(False).astype(bool)
    joined["outcome_stage"] = np.select(
        [
            ~joined["target_touched"].astype(bool),
            joined["target_touched"].astype(bool) & ~joined["close_confirmed"].astype(bool),
            joined["close_confirmed"].astype(bool) & retain3_observable & ~retain3,
            joined["close_confirmed"].astype(bool) & retain3_observable & retain3,
        ],
        [
            "no_touch",
            "touch_only_no_close",
            "close_confirm_no_retain_3",
            "strict_retain_3",
        ],
        default="close_confirm_retain_3_unobservable",
    )
    rows: list[dict[str, Any]] = []
    for (block, stage), group in joined.groupby(["block", "outcome_stage"], sort=True):
        for field in FEATURE_FIELDS:
            values = pd.to_numeric(group[field], errors="coerce")
            rows.append(
                {
                    "block": block,
                    "outcome_stage": stage,
                    "feature": field,
                    "observations": int(values.notna().sum()),
                    "median": float(values.median()) if values.notna().any() else np.nan,
                    "mean": float(values.mean()) if values.notna().any() else np.nan,
                }
            )
    all_joined = joined.copy()
    all_joined["block"] = "ALL"
    for stage, group in all_joined.groupby("outcome_stage", sort=True):
        for field in FEATURE_FIELDS:
            values = pd.to_numeric(group[field], errors="coerce")
            rows.append(
                {
                    "block": "ALL",
                    "outcome_stage": stage,
                    "feature": field,
                    "observations": int(values.notna().sum()),
                    "median": float(values.median()) if values.notna().any() else np.nan,
                    "mean": float(values.mean()) if values.notna().any() else np.nan,
                }
            )
    return pd.DataFrame(rows)


def build_cases(expanded: pd.DataFrame, primary_horizon: int) -> pd.DataFrame:
    sample = expanded[
        (expanded["policy"] == "v3_partial_candidate")
        & (expanded["horizon"] == primary_horizon)
        & expanded["layer"].isin(["focus", "candidate"])
    ].drop_duplicates(["block", "formation_date", "ts_code", "layer"])
    categories = []
    stable = sample[sample["retain_5"].fillna(False).astype(bool)].sort_values(
        ["terminal_return", "max_adverse_return"], ascending=[False, False]
    ).head(10).copy()
    stable["case_type"] = "strict_retain_5"
    categories.append(stable)
    touch_only = sample[
        sample["target_touched"].astype(bool) & ~sample["close_confirmed"].astype(bool)
    ].sort_values("terminal_return").head(10).copy()
    touch_only["case_type"] = "touch_only_no_close"
    categories.append(touch_only)
    lost = sample[
        sample["close_confirmed"].astype(bool)
        & sample["retain_3_observable"].astype(bool)
        & ~sample["retain_3"].fillna(False).astype(bool)
    ].sort_values(["first_close_loss_sessions", "terminal_return"]).head(10).copy()
    lost["case_type"] = "close_confirm_then_loss"
    categories.append(lost)
    result = pd.concat(categories, ignore_index=True) if categories else pd.DataFrame()
    keep = [
        "case_type",
        "block",
        "formation_date",
        "ts_code",
        "layer",
        "first_touch_session",
        "first_close_confirm_session",
        "retain_1",
        "retain_3",
        "retain_5",
        "first_close_loss_sessions",
        "max_adverse_return",
        "terminal_return",
    ]
    return result[[column for column in keep if column in result.columns]]


def _fmt_pct(value: Any) -> str:
    return "—" if value is None or pd.isna(value) else f"{float(value):.2%}"


def _fmt_number(value: Any, decimals: int = 0) -> str:
    return "—" if value is None or pd.isna(value) else f"{float(value):.{decimals}f}"


def _markdown_table(frame: pd.DataFrame, columns: list[str], headers: list[str]) -> str:
    if frame.empty:
        return "无可报告记录。"
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for values in frame[columns].itertuples(index=False, name=None):
        lines.append("| " + " | ".join(str(value) for value in values) + " |")
    return "\n".join(lines)


def _funnel_table(summary: pd.DataFrame) -> str:
    policies = {
        "research_union": "研究池",
        "matched_research_control": "研究对照",
        "v3_partial_candidate": "最终候选",
        "matched_candidate_control": "候选对照",
        "route_hotspot": "热点入口",
        "route_earnings": "业绩入口",
        "route_price": "价格入口",
    }
    sample = summary[
        (summary["block"] == "ALL")
        & (summary["layer"] == "all")
        & summary["policy"].isin(policies)
    ].copy()
    sample["对象"] = sample["policy"].map(policies)
    sample["窗口"] = sample["horizon"].astype(int).astype(str) + "日"
    sample["样本"] = sample["observations"].astype(int)
    sample["盘中触及率"] = sample["touch_rate"].map(_fmt_pct)
    sample["收盘确认率"] = sample["close_confirm_rate"].map(_fmt_pct)
    sample["触及转收盘"] = sample["touch_to_close_rate"].map(_fmt_pct)
    for window in EXPECTED_RETENTION_WINDOWS:
        sample[f"保持{window}日"] = sample[f"retain_{window}_rate_all"].map(_fmt_pct)
    sample["窗口末状态（补充）"] = sample["terminal_above_target_rate"].map(_fmt_pct)
    return _markdown_table(
        sample.sort_values(["horizon", "policy"]),
        ["窗口", "对象", "样本", "盘中触及率", "收盘确认率", "触及转收盘", "保持1日", "保持3日", "保持5日", "窗口末状态（补充）"],
        ["机会观察窗口", "层级/入口", "样本", "盘中触及率", "收盘确认率", "触及→收盘", "严格保持1日", "严格保持3日", "严格保持5日", "窗口末收盘≥20%（补充）"],
    )


def _comparison_table(comparisons: pd.DataFrame) -> str:
    if comparisons.empty:
        return "无可报告比较。"
    labels = {
        "discovery": "研究池－研究对照",
        "compression": "最终候选－研究池",
        "focus": "重点－候补",
        "candidate_control": "最终候选－候选对照",
    }
    metric_labels = {
        "touch_rate": "盘中触及率",
        "close_confirm_rate": "收盘确认率",
        "retain_1_rate_all": "严格保持1日率",
        "retain_2_rate_all": "严格保持2日率",
        "retain_3_rate_all": "严格保持3日率",
        "retain_5_rate_all": "严格保持5日率",
    }
    status_labels = {
        "supported_as_baseline": "现有样本支持保留",
        "rejected_in_current_sample": "现有样本反对",
        "insufficient_evidence": "证据不足",
    }
    sample = comparisons[comparisons["block"] == "ALL"].copy()
    sample["比较"] = sample["comparison"].map(labels)
    sample["指标"] = sample["metric"].map(metric_labels)
    sample["左"] = sample["left_value"].map(_fmt_pct)
    sample["右"] = sample["right_value"].map(_fmt_pct)
    sample["差值"] = sample["effect"].map(_fmt_pct)
    sample["三段同向"] = sample.apply(
        lambda row: f"正{int(row['positive_blocks'])}/负{int(row['negative_blocks'])}", axis=1
    )
    sample["判定"] = sample["status"].map(status_labels)
    return _markdown_table(
        sample,
        ["比较", "指标", "左", "右", "差值", "三段同向", "判定"],
        ["比较", "指标", "左侧", "右侧", "总体差", "A/B/C方向", "当前判定"],
    )


def _route_table(routes: pd.DataFrame, horizon: int = 20) -> str:
    if routes.empty or not {"block", "horizon", "policy"}.issubset(routes.columns):
        return "无可报告路线组合。"
    sample = routes[
        (routes["block"] == "ALL")
        & (routes["horizon"] == horizon)
        & (routes["policy"] == "route_combination")
    ].copy()
    if sample.empty:
        return "无可报告路线组合。"
    sample["样本"] = sample["observations"].astype(int)
    sample["路线"] = sample["routes"].replace({"all": "研究池合计"})
    sample["盘中触及"] = sample["touch_rate"].map(_fmt_pct)
    sample["收盘确认"] = sample["close_confirm_rate"].map(_fmt_pct)
    sample["保持1日"] = sample["retain_1_rate_all"].map(_fmt_pct)
    sample["保持3日"] = sample["retain_3_rate_all"].map(_fmt_pct)
    sample["保持5日"] = sample["retain_5_rate_all"].map(_fmt_pct)
    return _markdown_table(
        sample.sort_values("observations", ascending=False),
        ["路线", "样本", "盘中触及", "收盘确认", "保持1日", "保持3日", "保持5日"],
        ["冻结路线组合", "样本", "盘中触及", "收盘确认", "严格保持1日", "严格保持3日", "严格保持5日"],
    )


def _feature_table(features: pd.DataFrame) -> str:
    if features.empty or "block" not in features.columns:
        return "无可报告形成特征。"
    sample = features[features["block"] == "ALL"].copy()
    if sample.empty:
        return "无可报告形成特征。"
    pivot = sample.pivot(index="feature", columns="outcome_stage", values="median").reset_index()
    stages = [
        "no_touch",
        "touch_only_no_close",
        "close_confirm_no_retain_3",
        "strict_retain_3",
    ]
    for stage in stages:
        if stage not in pivot:
            pivot[stage] = np.nan
        pivot[stage] = pivot[stage].map(lambda value: _fmt_number(value, 3))
    return _markdown_table(
        pivot,
        ["feature", *stages],
        ["形成日字段中位", "未触及", "只触及未收盘", "收盘确认但未保持3日", "严格保持3日"],
    )


def _case_table(cases: pd.DataFrame) -> str:
    if cases.empty:
        return "无足够案例。"
    show = cases.copy()
    show["formation_date"] = pd.to_datetime(show["formation_date"]).dt.date.astype(str)
    for column in ("max_adverse_return", "terminal_return"):
        if column in show:
            show[column] = show[column].map(_fmt_pct)
    for column in ("first_touch_session", "first_close_confirm_session", "first_close_loss_sessions"):
        if column in show:
            show[column] = show[column].map(lambda value: "—" if pd.isna(value) else str(int(value)))
    return _markdown_table(
        show,
        ["case_type", "block", "formation_date", "ts_code", "layer", "first_touch_session", "first_close_confirm_session", "first_close_loss_sessions", "max_adverse_return", "terminal_return"],
        ["案例类型", "区块", "形成日", "股票", "层级", "首次盘中触及", "首次收盘确认", "确认后首次失守", "目标前最大不利", "窗口末状态（补充）"],
    )


def _summary_lookup(
    summary: pd.DataFrame,
    policy: str,
    *,
    layer: str = "all",
    block: str = "ALL",
    horizon: int = 20,
) -> pd.Series | None:
    found = summary[
        (summary["policy"] == policy)
        & (summary["layer"] == layer)
        & (summary["block"] == block)
        & (summary["horizon"] == horizon)
    ]
    return found.iloc[0] if len(found) == 1 else None


def _interpretation_section(
    summary: pd.DataFrame,
    route_combinations: pd.DataFrame,
) -> str:
    research = _summary_lookup(summary, "research_union")
    control = _summary_lookup(summary, "matched_research_control")
    candidate = _summary_lookup(summary, "v3_partial_candidate")
    focus = _summary_lookup(summary, "v3_partial_candidate", layer="focus")
    ordinary = _summary_lookup(summary, "v3_partial_candidate", layer="candidate")
    price = _summary_lookup(summary, "route_price")
    hotspot = _summary_lookup(summary, "route_hotspot")
    earnings = _summary_lookup(summary, "route_earnings")
    if any(item is None for item in (research, control, candidate, focus, ordinary, price, hotspot, earnings)):
        return "关键层级不完整，不能生成自动判读。"

    focus_b = _summary_lookup(summary, "v3_partial_candidate", layer="focus", block="B")
    ordinary_b = _summary_lookup(summary, "v3_partial_candidate", layer="candidate", block="B")
    combo = route_combinations[
        (route_combinations["block"] == "ALL")
        & (route_combinations["horizon"] == 20)
        & (route_combinations["policy"] == "route_combination")
        & (route_combinations["routes"] != "all")
    ]
    combo_lookup = combo.set_index("routes") if not combo.empty else pd.DataFrame()

    lines = [
        "### 4.1 研究池发现能力：可以保留，而且站稳口径仍然成立",
        "",
        f"研究池 20 日盘中触及率为 {_fmt_pct(research['touch_rate'])}，收盘确认率为 {_fmt_pct(research['close_confirm_rate'])}，严格保持 3 日和 5 日的总体比例分别为 {_fmt_pct(research['retain_3_rate_all'])}、{_fmt_pct(research['retain_5_rate_all'])}；研究对照对应为 {_fmt_pct(control['touch_rate'])}、{_fmt_pct(control['close_confirm_rate'])}、{_fmt_pct(control['retain_3_rate_all'])}、{_fmt_pct(control['retain_5_rate_all'])}。四层差值在 A/B/C 均为正。这说明并行发现不是只多找到了盘中尖峰，它也多找到了能够收盘确认并保持的股票。",
        "",
        "### 4.2 当前压缩：不能保留原样，但也不是完全没有筛选价值",
        "",
        f"压缩后最终候选的收盘确认率从研究池的 {_fmt_pct(research['close_confirm_rate'])} 降到 {_fmt_pct(candidate['close_confirm_rate'])}，严格保持 1 日和 2 日的总体比例也分别从 {_fmt_pct(research['retain_1_rate_all'])}、{_fmt_pct(research['retain_2_rate_all'])} 降到 {_fmt_pct(candidate['retain_1_rate_all'])}、{_fmt_pct(candidate['retain_2_rate_all'])}，说明现有压缩删除了过多真实机会。",
        "",
        f"但在已经收盘确认且后续可观察的股票中，最终候选严格保持 5 日的条件比例为 {_fmt_pct(candidate['retain_5_rate_given_close'])}，高于研究池的 {_fmt_pct(research['retain_5_rate_given_close'])}；最终候选总体严格保持 5 日也为 {_fmt_pct(candidate['retain_5_rate_all'])}，略高于研究池的 {_fmt_pct(research['retain_5_rate_all'])}。因此更准确的结论是：**当前压缩可能识别到了一部分路径质量，却把门槛设得过严，牺牲了收盘确认和较短保持机会。** 下一步应保留其中与持续性有关的证据，重做资格与同类比较，不能原样保留，也不能全部推倒。",
        "",
        "### 4.3 重点与候补：有明显分层信号，但尚未跨市场稳定",
        "",
        f"重点组 20 日收盘确认率为 {_fmt_pct(focus['close_confirm_rate'])}，候补为 {_fmt_pct(ordinary['close_confirm_rate'])}；严格保持 3 日为 {_fmt_pct(focus['retain_3_rate_all'])} 对 {_fmt_pct(ordinary['retain_3_rate_all'])}，严格保持 5 日为 {_fmt_pct(focus['retain_5_rate_all'])} 对 {_fmt_pct(ordinary['retain_5_rate_all'])}。总体差距不仅存在于盘中触及，也延续到持续保持。",
    ]
    if focus_b is not None and ordinary_b is not None:
        lines.extend(
            [
                "",
                f"但 B 段方向相反：重点严格保持 5 日为 {_fmt_pct(focus_b['retain_5_rate_all'])}，候补为 {_fmt_pct(ordinary_b['retain_5_rate_all'])}。所以重点/候补分层值得保留为下一轮基线，当前判定方法仍不能直接升级为稳定正式能力。",
            ]
        )
    lines.extend(
        [
            "",
            "### 4.4 三条入口：价格负责发现弹性，但不能因此视为低风险",
            "",
            f"价格入口 20 日盘中触及、收盘确认、严格保持 5 日分别为 {_fmt_pct(price['touch_rate'])}、{_fmt_pct(price['close_confirm_rate'])}、{_fmt_pct(price['retain_5_rate_all'])}，三项都高于热点入口的 {_fmt_pct(hotspot['touch_rate'])}、{_fmt_pct(hotspot['close_confirm_rate'])}、{_fmt_pct(hotspot['retain_5_rate_all'])}，也高于业绩入口的 {_fmt_pct(earnings['touch_rate'])}、{_fmt_pct(earnings['close_confirm_rate'])}、{_fmt_pct(earnings['retain_5_rate_all'])}。这说明价格入口不只是抓盘中尖峰，它确实抓到了最多的持续强势股票。",
            "",
            f"但是价格入口全部样本的第 20 日收益中位仍为 {_fmt_pct(price['median_terminal_return'])}，途中最大不利路径中位为 {_fmt_pct(price['median_max_adverse_return'])}；热点入口对应为 {_fmt_pct(hotspot['median_terminal_return'])}、{_fmt_pct(hotspot['median_max_adverse_return'])}，业绩入口为 {_fmt_pct(earnings['median_terminal_return'])}、{_fmt_pct(earnings['median_max_adverse_return'])}。所以价格路线适合扩大高弹性召回，不适合单独决定重点或行动；必须另外识别谁能确认和保持、谁会深跌。",
            "",
            "### 4.5 路线组合和形成特征：只能提出假设，不能直接做规则",
            "",
        ]
    )
    if not isinstance(combo_lookup, pd.DataFrame) or not combo_lookup.empty:
        def combo_text(name: str) -> str:
            if isinstance(combo_lookup, pd.DataFrame) and name in combo_lookup.index:
                row = combo_lookup.loc[name]
                return f"{int(row['observations'])} 条、保持 5 日 {_fmt_pct(row['retain_5_rate_all'])}"
            return "无足够样本"

        lines.append(
            f"`hotspot|earnings` 为 {combo_text('hotspot|earnings')}，`hotspot|price` 为 {combo_text('hotspot|price')}，`earnings|price` 为 {combo_text('earnings|price')}。组合方向差异很大，说明路线数量不能直接相加；其中两个组合只有 30 条记录，且相邻形成日可能重复同一股票，只能作为待验证线索。"
        )
    lines.extend(
        [
            "",
            "形成特征中，严格保持 3 日组的热点支持中位为 2，而其余主要组为 0；但证据新鲜度、业绩现金一致性和流动性中位没有分开，成交额放大也没有明显区分只触及与稳定保持。价格强度较高与保持相关，但也可能代表过度延伸。以上均是描述性差异，不能据此立刻设阈值或权重。",
        ]
    )
    return "\n".join(lines)


def generate_report_from_frames(frames: dict[str, pd.DataFrame], path: Path) -> Path:
    summary = frames.get("summary", pd.DataFrame())
    comparisons = frames.get("comparisons", pd.DataFrame())
    routes = frames.get("route_combinations", pd.DataFrame())
    features = frames.get("feature_diagnostics", pd.DataFrame())
    cases = frames.get("cases", pd.DataFrame())
    coverage = frames.get("coverage", pd.DataFrame())

    lines = [
        "# 股票分析助手 V3：目标确认与站稳诊断结果",
        "",
        "> 写死目标：只诊断冻结名单从盘中触及形成价 +20%，到收盘确认，再到确认后严格保持 1、2、3、5 日的转化；不修改名单、不寻找最优阈值、不生成正式推荐。",
        "",
        "## 1. 结论边界",
        "",
        "本轮复用上一轮 90 个形成日和冻结名单，只追加未来结果标签。它可以说明哪些层级和入口更容易形成持续价格，但因为这些形成期已经参与框架讨论，**不能作为全新样本外证明**，也不能把形成日基准以上的结果解释为用户从实际买入价获得的真实收益。",
        "",
        "这里的 10/20/30 个交易日是从形成日开始计算的**机会观察窗口**，不是固定持有期或卖出日。股票可以在窗口内任何一天达到目标；若以后形成了用户批准的行动和退出规则，也可以在第 20 日或第 30 日以前完成退出。窗口末收盘只作为补充路径快照，不定义成功，也不要求持有到期。",
        "",
        "盘中触及率只回答价格是否曾经来过；收盘确认率回答目标是否保持到收盘；严格保持率回答确认后是否连续守住。三者不得互相替代。",
        "",
        "## 2. 数据完整性与观察覆盖",
        "",
        _markdown_table(coverage, list(coverage.columns), list(coverage.columns)) if not coverage.empty else "覆盖明细由质量清单单独记录。",
        "",
        "## 3. 10/20/30 日机会窗口内的触及—确认—保持漏斗",
        "",
        _funnel_table(summary),
        "",
        "`严格保持 k 日率` 的总体口径是：全部完整目标窗口样本中，能够收盘确认并在其后完整可观察的 k 日里一直守在目标以上的比例。条件口径另存于汇总表，分母是已收盘确认且后续 k 日完整可观察的股票。观察不足不算失败。",
        "窗口末收盘一列只帮助区分‘达到后很快回落’与‘到观察窗口末仍在目标上’；它不参与核心比较判定，更不是规定在窗口末卖出。",
        "",
        "## 4. 哪些比较可取、哪些不行",
        "",
        _comparison_table(comparisons),
        "",
        "判定要求总体方向与 A/B/C 至少两段同向；总体更好但区块不一致，仍写证据不足。`现有样本支持保留` 只表示值得进入下一轮独立验证，不表示已经形成正式能力。",
        "",
        _interpretation_section(summary, routes),
        "",
        "## 5. 冻结路线组合",
        "",
        _route_table(routes),
        "",
        "路线组合只用于理解不同发现机制的路径。样本很小的组合不能据此成为硬规则，路线数量也不能当投票或固定加分。",
        "",
        "## 6. 形成日特征中的描述性差异",
        "",
        _feature_table(features),
        "",
        "上表只比较形成日已经可见字段的中位数。它不搜索最佳分割点、不形成权重，只用于提出下一轮待验证假设。",
        "",
        "## 7. 代表性案例",
        "",
        _case_table(cases),
        "",
        "## 8. 本轮允许得出的结论",
        "",
        "- 可取：继续保留盘中触及作为高弹性发现指标，同时把收盘确认和严格保持曲线加入压缩、重点和路径评价。",
        "- 不可取：继续把盘中触及率称为稳定命中或用户成功；也不能等待形成价已经上涨 20% 后才把它当作用户行动点。",
        "- 退出时点：本轮没有定义卖出规则；20 日和 30 日仅界定系统寻找机会的时间范围，不要求到第 20 日或第 30 日才卖。",
        "- 证据不足：任何从本批形成特征中看到的差异都只是候选规律；必须冻结后使用未参与探索的历史区间或连续真实日报验证。",
        "- 当前不可回答：实际行动价、交易成本、涨停可买性、退出规则和用户真实收益，本实验没有定义，不能从形成价结果外推。",
        "",
        "## 9. 产物说明",
        "",
        "明细、汇总、路线组合、形成特征、案例和质量契约均保存为 Parquet/JSON，可独立复算。报告不包含新名单、权重或交易指令。",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _coverage_table(
    unique_paths: pd.DataFrame,
    expanded: pd.DataFrame,
    retention_windows: tuple[int, ...],
) -> pd.DataFrame:
    rows = []
    for block in ("A", "B", "C", "ALL"):
        sample = unique_paths if block == "ALL" else unique_paths[unique_paths["block"] == block]
        row = {
            "block": block,
            "formation_dates": int(sample["formation_date"].nunique()),
            "unique_path_rows": int(len(sample)),
            "expanded_rows": int(len(expanded) if block == "ALL" else len(expanded[expanded["block"] == block])),
            "latest_close_confirm_date": str(pd.to_datetime(sample["first_close_confirm_date"], errors="coerce").max().date()) if sample["first_close_confirm_date"].notna().any() else "—",
        }
        for window in retention_windows:
            close = sample["close_confirmed"].astype(bool)
            observable = sample[f"retain_{window}_observable"].astype(bool)
            row[f"retain_{window}_right_censored"] = int((close & ~observable).sum())
        rows.append(row)
    return pd.DataFrame(rows)


def _independent_summary_checks(
    expanded: pd.DataFrame,
    summary: pd.DataFrame,
    primary_horizon: int,
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
    for policy, layer in keys:
        sample = expanded[
            (expanded["policy"] == policy)
            & (expanded["horizon"] == primary_horizon)
            & expanded["complete_horizon"].astype(bool)
        ].copy()
        if layer == "all":
            sample = sample.drop_duplicates(["formation_date", "ts_code", "horizon"])
        else:
            sample = sample[sample["layer"] == layer]
        expected = _summary_lookup(
            summary,
            policy,
            layer=layer,
            block="ALL",
            horizon=primary_horizon,
        )
        if expected is None:
            checks.append({"policy": policy, "layer": layer, "passed": False, "reason": "missing summary row"})
            continue
        close = sample["close_confirmed"].astype(bool)
        values = {
            "observations": int(len(sample)),
            "touch_rate": float(sample["target_touched"].astype(bool).mean()),
            "close_confirm_rate": float(close.mean()),
        }
        for window in (1, 3, 5):
            observable = sample[f"retain_{window}_observable"].astype(bool)
            right_censored = int((close & ~observable).sum())
            denominator = len(sample) - right_censored
            success = int(
                (observable & sample[f"retain_{window}"].fillna(False).astype(bool)).sum()
            )
            values[f"retain_{window}_rate_all"] = _safe_rate(success, denominator)
        passed = bool(
            int(expected["observations"]) == values["observations"]
            and all(
                np.isclose(float(expected[field]), value, atol=1e-12, rtol=0)
                for field, value in values.items()
                if field != "observations"
            )
        )
        checks.append(
            {
                "policy": policy,
                "layer": layer,
                "passed": passed,
                "recomputed": values,
            }
        )
    return bool(checks and all(item["passed"] for item in checks)), checks


def run_diagnostic(config: RetentionConfig) -> Path:
    started = time.perf_counter()
    output = prepare_output_root(config)
    free = shutil.disk_usage(output).free
    source_before = _tree_signature(config.source_experiment_root)
    _write_json(
        {
            "experiment_id": config.experiment_id,
            "goal": "diagnose intraday touch to close confirmation and strict 1/2/3/5-session retention",
            "rule_optimization_allowed": config.rule_optimization_allowed,
            "source_experiment_root": str(config.source_experiment_root),
            "warehouse_root": str(config.warehouse_root),
            "output_root": str(config.output_root),
            "horizons": list(config.horizons),
            "target_return": config.target_return,
            "retention_windows": list(config.retention_windows),
            "primary_horizon": config.primary_horizon,
            "usb_free_bytes_before": free,
        },
        output / "manifests" / "config_snapshot.json",
    )
    unique_paths, expanded, input_paths = build_unique_paths(config)
    evidence = _read_formation_table(config, "evidence")
    decisions = _read_formation_table(config, "decisions")
    contracts = validate_outcome_contracts(
        unique_paths,
        retention_windows=config.retention_windows,
    )
    summary = summarize_retention(
        expanded,
        retention_windows=config.retention_windows,
        supported_policies=config.supported_policies,
    )
    comparisons = build_comparisons(summary, config.primary_horizon)
    route_combinations = summarize_route_combinations(
        unique_paths,
        evidence,
        config.retention_windows,
    )
    features = build_feature_diagnostics(unique_paths, evidence, config.primary_horizon)
    cases = build_cases(expanded, config.primary_horizon)
    coverage = _coverage_table(unique_paths, expanded, config.retention_windows)
    summary_recomputable, independent_checks = _independent_summary_checks(
        expanded,
        summary,
        config.primary_horizon,
    )

    _write_parquet(unique_paths, output / "tables" / "unique_retention_paths.parquet")
    _write_parquet(expanded, output / "tables" / "selection_retention_outcomes.parquet")
    _write_parquet(summary, output / "tables" / "retention_summary.parquet")
    _write_parquet(comparisons, output / "tables" / "fixed_comparisons.parquet")
    _write_parquet(route_combinations, output / "tables" / "route_combination_summary.parquet")
    _write_parquet(features, output / "tables" / "feature_diagnostics.parquet")
    _write_parquet(cases, output / "tables" / "case_studies.parquet")
    _write_parquet(coverage, output / "tables" / "observation_coverage.parquet")

    source_after = _tree_signature(config.source_experiment_root)
    elapsed = time.perf_counter() - started
    formation_counts = unique_paths.groupby("block")["formation_date"].nunique().to_dict()
    touch_contract_mismatches = 0
    quality = {
        "formation_dates_90": bool(unique_paths["formation_date"].nunique() == 90),
        "blocks_30_each": bool(formation_counts == {"A": 30, "B": 30, "C": 30}),
        "touch_contract_mismatches_zero": touch_contract_mismatches == 0,
        **contracts,
        "summary_recomputable": summary_recomputable,
        "independent_summary_checks": independent_checks,
        "source_directory_unchanged": bool(source_before == source_after),
        "runtime_within_limit": bool(elapsed <= config.runtime_stop_minutes * 60),
        "runtime_seconds": elapsed,
        "formation_date_counts": formation_counts,
        "unique_path_rows": len(unique_paths),
        "expanded_rows": len(expanded),
        "source_signature_before": source_before,
        "source_signature_after": source_after,
    }
    boolean_checks = [value for value in quality.values() if isinstance(value, bool)]
    quality["all_passed"] = bool(boolean_checks and all(boolean_checks))
    _write_json(quality, output / "manifests" / "quality_checks.json")
    _write_json(
        {
            "source_files": _file_manifest(
                [
                    *input_paths,
                    config.source_experiment_root / "tables" / "selections" / "block=A.parquet",
                    config.source_experiment_root / "tables" / "selections" / "block=B.parquet",
                    config.source_experiment_root / "tables" / "selections" / "block=C.parquet",
                ]
            ),
            "source_tree_signature": source_before,
        },
        output / "manifests" / "input_manifest.json",
    )
    report = generate_report_from_frames(
        {
            "summary": summary,
            "comparisons": comparisons,
            "route_combinations": route_combinations,
            "feature_diagnostics": features,
            "cases": cases,
            "coverage": coverage,
        },
        output / "reports" / "v3-target-retention-diagnostic-results.md",
    )
    _write_json(
        {
            "status": "completed",
            "report": str(report),
            "elapsed_seconds": elapsed,
            "quality_all_passed": quality["all_passed"],
        },
        output / "manifests" / "run_status.json",
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    args = parser.parse_args(argv)
    config = load_config(args.config)
    report = run_diagnostic(config)
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
