"""Minimal, auditable historical validation for the temporary V3 framework.

This module is an experiment runner, not a production recommendation service.
Runtime artifacts are restricted to the dedicated USB experiment directory.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time
from typing import Any

import numpy as np
import pandas as pd
import yaml

from stock_analyzer.analysis.hotspot_features import compute_hotspot_features
from stock_analyzer.analysis.market_context_features import compute_market_context_features
from stock_analyzer.analysis.stock_context_features import compute_stock_context_features
from stock_analyzer.evaluation.historical_framework_validation import (
    compute_forward_outcomes,
    round_robin_union,
)


EXPECTED_SUPPORTED_ROUTES = ("hotspot", "earnings", "price")
EXPECTED_NOT_TESTABLE_ROUTES = (
    "company_event",
    "industry_cycle",
    "distress_repair",
)
DEFAULT_ALLOWED_VOLUME_ROOT = Path("/Volumes/ZHUTONG")


@dataclass(frozen=True)
class Block:
    id: str
    start: date
    end: date


@dataclass(frozen=True)
class ValidationConfig:
    experiment_id: str
    warehouse_root: Path
    output_root: Path
    blocks: tuple[Block, ...]
    horizons: tuple[int, ...]
    target_return: float
    candidate_cap: int
    focus_cap: int
    route_recall_cap: int
    supported_routes: tuple[str, ...]
    not_testable_routes: tuple[str, ...]
    runtime_soft_hours: float
    runtime_stop_hours: float
    usb_soft_bytes: int


def load_config(path: str | Path) -> ValidationConfig:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("validation config must be a mapping")
    blocks = tuple(
        Block(
            id=str(item["id"]),
            start=date.fromisoformat(str(item["start"])),
            end=date.fromisoformat(str(item["end"])),
        )
        for item in payload["blocks"]
    )
    config = ValidationConfig(
        experiment_id=str(payload["experiment_id"]),
        warehouse_root=Path(payload["warehouse_root"]),
        output_root=Path(payload["output_root"]),
        blocks=blocks,
        horizons=tuple(int(value) for value in payload["horizons"]),
        target_return=float(payload["target_return"]),
        candidate_cap=int(payload["candidate_cap"]),
        focus_cap=int(payload["focus_cap"]),
        route_recall_cap=int(payload["route_recall_cap"]),
        supported_routes=tuple(str(value) for value in payload["supported_routes"]),
        not_testable_routes=tuple(
            str(value) for value in payload["not_testable_routes"]
        ),
        runtime_soft_hours=float(payload["runtime_soft_hours"]),
        runtime_stop_hours=float(payload["runtime_stop_hours"]),
        usb_soft_bytes=int(payload["usb_soft_bytes"]),
    )
    _validate_config(config)
    return config


def _validate_config(config: ValidationConfig) -> None:
    if config.supported_routes != EXPECTED_SUPPORTED_ROUTES:
        raise ValueError("supported routes differ from the frozen protocol")
    if config.not_testable_routes != EXPECTED_NOT_TESTABLE_ROUTES:
        raise ValueError("not-testable routes differ from the frozen protocol")
    if tuple(block.id for block in config.blocks) != ("A", "B", "C"):
        raise ValueError("blocks must be A, B and C")
    if config.horizons != (10, 20, 30):
        raise ValueError("horizons differ from the frozen protocol")
    if config.target_return != 0.20:
        raise ValueError("target return differs from the frozen protocol")
    if config.candidate_cap != 10 or config.focus_cap != 5:
        raise ValueError("candidate capacities differ from the frozen protocol")


def prepare_output_root(
    config: ValidationConfig,
    *,
    output_override: str | Path | None = None,
    allowed_volume_root: str | Path = DEFAULT_ALLOWED_VOLUME_ROOT,
) -> Path:
    output = Path(output_override) if output_override is not None else config.output_root
    volume_root = Path(allowed_volume_root)
    expected_parent = volume_root / "股票分析助手-V3回测"
    try:
        relative = output.resolve(strict=False).relative_to(expected_parent.resolve(strict=False))
    except ValueError as exc:
        raise ValueError("输出路径必须位于U盘专用目录") from exc
    if relative.parts != (config.experiment_id,):
        raise ValueError("输出路径必须是冻结的U盘专用实验目录")
    for child in ("manifests", "tables", "reports"):
        (output / child).mkdir(parents=True, exist_ok=True)
    return output


def _as_jsonable_config(config: ValidationConfig) -> dict[str, Any]:
    return {
        "experiment_id": config.experiment_id,
        "warehouse_root": str(config.warehouse_root),
        "output_root": str(config.output_root),
        "blocks": [
            {"id": item.id, "start": item.start.isoformat(), "end": item.end.isoformat()}
            for item in config.blocks
        ],
        "horizons": list(config.horizons),
        "target_return": config.target_return,
    }


def _formation_boundary(formation_date: str | date | pd.Timestamp) -> pd.Timestamp:
    day = pd.Timestamp(formation_date).normalize()
    if day.tzinfo is None:
        day = day.tz_localize("Asia/Shanghai")
    else:
        day = day.tz_convert("Asia/Shanghai")
    return day + pd.Timedelta(hours=23, minutes=59, seconds=59)


def bound_as_of(
    facts: pd.DataFrame,
    *,
    formation_date: str | date | pd.Timestamp,
    fact_date_column: str,
    available_column: str = "available_at",
) -> pd.DataFrame:
    """Return only facts whose business date and public availability are legal."""

    required = {fact_date_column, available_column}
    missing = sorted(required - set(facts.columns))
    if missing:
        raise ValueError(f"facts lack required fields: {', '.join(missing)}")
    prepared = facts.copy()
    fact_dates = pd.to_datetime(prepared[fact_date_column], errors="raise").dt.normalize()
    boundary = _formation_boundary(formation_date)
    available = pd.to_datetime(prepared[available_column], utc=True, errors="coerce")
    if available.isna().any():
        raise ValueError("formation evidence has missing available_at")
    legal = (fact_dates <= boundary.tz_localize(None).normalize()) & (
        available <= boundary.tz_convert("UTC")
    )
    prepared[fact_date_column] = fact_dates
    prepared[available_column] = available
    return prepared.loc[legal].copy()


def select_latest_available_financials(
    facts: pd.DataFrame,
    *,
    formation_date: str | date | pd.Timestamp,
) -> pd.DataFrame:
    """Select the latest public report and revision per security as of formation."""

    required = {"ts_code", "report_period", "available_at"}
    missing = sorted(required - set(facts.columns))
    if missing:
        raise ValueError(f"financial facts lack required fields: {', '.join(missing)}")
    prepared = facts.copy()
    prepared["available_at"] = pd.to_datetime(
        prepared["available_at"], utc=True, errors="coerce"
    )
    if prepared["available_at"].isna().any():
        raise ValueError("financial facts have missing available_at")
    prepared["report_period"] = pd.to_datetime(
        prepared["report_period"], errors="raise"
    ).dt.normalize()
    boundary = _formation_boundary(formation_date).tz_convert("UTC")
    prepared = prepared[prepared["available_at"] <= boundary].copy()
    if prepared.empty:
        return prepared
    if "revision_no" not in prepared:
        prepared["revision_no"] = 0
    prepared["revision_no"] = pd.to_numeric(
        prepared["revision_no"], errors="coerce"
    ).fillna(0)
    return (
        prepared.sort_values(
            ["ts_code", "report_period", "available_at", "revision_no"]
        )
        .drop_duplicates("ts_code", keep="last")
        .reset_index(drop=True)
    )


def add_recomputed_pct_chg(prices: pd.DataFrame) -> pd.DataFrame:
    """Add one uniform close-to-close percentage-change observation."""

    required = {"trade_date", "ts_code", "close"}
    missing = sorted(required - set(prices.columns))
    if missing:
        raise ValueError(f"prices lack required fields: {', '.join(missing)}")
    prepared = prices.copy()
    prepared["trade_date"] = pd.to_datetime(
        prepared["trade_date"], errors="raise"
    ).dt.normalize()
    prepared["close"] = pd.to_numeric(prepared["close"], errors="coerce")
    prepared = prepared.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    prepared["recomputed_pct_chg"] = (
        prepared.groupby("ts_code", sort=False)["close"].pct_change(fill_method=None)
        * 100.0
    )
    return prepared


DECISION_DIMENSIONS = (
    "evidence_freshness",
    "earnings_cash_consistency",
    "hotspot_support",
    "price_consumption_safety",
    "liquidity",
)


def compress_candidates(
    evidence: pd.DataFrame,
    *,
    candidate_cap: int,
    focus_cap: int,
) -> pd.DataFrame:
    """Apply hard gates, Pareto dominance and non-arbitrary capacity handling."""

    required = {
        "formation_date",
        "ts_code",
        "routes",
        "company_evidence",
        "hard_invalid",
        *DECISION_DIMENSIONS,
    }
    missing = sorted(required - set(evidence.columns))
    if missing:
        raise ValueError(f"candidate evidence lacks fields: {', '.join(missing)}")
    if candidate_cap <= 0 or focus_cap < 0 or focus_cap > candidate_cap:
        raise ValueError("invalid candidate capacities")
    prepared = evidence.copy().reset_index(drop=True)
    if prepared.duplicated(["formation_date", "ts_code"]).any():
        raise ValueError("candidate evidence contains duplicate stock-date rows")
    for column in DECISION_DIMENSIONS:
        prepared[column] = pd.to_numeric(prepared[column], errors="raise")
    prepared["layer"] = "research_only"
    prepared["decision_reason"] = "missing_company_opportunity_evidence"
    prepared["dominated_by"] = None

    hard_invalid = prepared["hard_invalid"].astype(bool)
    prepared.loc[hard_invalid, "layer"] = "invalid"
    prepared.loc[hard_invalid, "decision_reason"] = "hard_invalidation"
    eligible_mask = prepared["company_evidence"].astype(bool) & ~hard_invalid
    eligible = prepared.loc[eligible_mask].copy()

    dominated: dict[int, int] = {}
    for index, row in eligible.iterrows():
        row_values = row.loc[list(DECISION_DIMENSIONS)].astype(float)
        dominators: list[int] = []
        for other_index, other in eligible.iterrows():
            if other_index == index:
                continue
            other_values = other.loc[list(DECISION_DIMENSIONS)].astype(float)
            if bool((other_values >= row_values).all()) and bool(
                (other_values > row_values).any()
            ):
                dominators.append(other_index)
        if dominators:
            dominated[index] = max(
                dominators,
                key=lambda item: tuple(
                    eligible.loc[item, column] for column in DECISION_DIMENSIONS
                ),
            )

    for index, dominator in dominated.items():
        prepared.loc[index, "layer"] = "dominated"
        prepared.loc[index, "decision_reason"] = "pareto_dominated"
        prepared.loc[index, "dominated_by"] = str(prepared.loc[dominator, "ts_code"])

    frontier_indexes = [index for index in eligible.index if index not in dominated]
    selected, boundary_ties, below_capacity = _select_by_lexicographic_groups(
        prepared.loc[frontier_indexes], candidate_cap
    )
    for index in below_capacity:
        prepared.loc[index, "layer"] = "capacity_excluded"
        prepared.loc[index, "decision_reason"] = "lower_evidence_tier"
    for index in boundary_ties:
        prepared.loc[index, "layer"] = "abstain_capacity_tie"
        prepared.loc[index, "decision_reason"] = "indistinguishable_at_candidate_boundary"
    for index in selected:
        prepared.loc[index, "layer"] = "candidate"
        prepared.loc[index, "decision_reason"] = "non_dominated_candidate"

    selected_frame = prepared.loc[selected]
    focus, focus_ties, _ = _select_by_lexicographic_groups(selected_frame, focus_cap)
    for index in focus:
        prepared.loc[index, "layer"] = "focus"
        prepared.loc[index, "decision_reason"] = "stronger_non_dominated_evidence"
    for index in focus_ties:
        prepared.loc[index, "decision_reason"] = "indistinguishable_at_focus_boundary"
    return prepared


def _select_by_lexicographic_groups(
    eligible: pd.DataFrame, cap: int
) -> tuple[list[int], list[int], list[int]]:
    if cap == 0 or eligible.empty:
        return [], [], list(eligible.index)
    groups: dict[tuple[float, ...], list[int]] = {}
    for index, row in eligible.iterrows():
        key = tuple(float(row[column]) for column in DECISION_DIMENSIONS)
        groups.setdefault(key, []).append(index)
    selected: list[int] = []
    ties: list[int] = []
    excluded: list[int] = []
    boundary_reached = False
    for key in sorted(groups, reverse=True):
        indexes = groups[key]
        if boundary_reached:
            excluded.extend(indexes)
        elif len(selected) + len(indexes) <= cap:
            selected.extend(indexes)
        else:
            ties.extend(indexes)
            boundary_reached = True
    return selected, ties, excluded


def challenger_can_replace(
    challenger: pd.Series,
    incumbent: pd.Series,
    *,
    incumbent_invalid: bool = False,
) -> bool:
    """Allow replacement only for invalidation or observable Pareto dominance."""

    if incumbent_invalid:
        return True
    challenger_values = pd.to_numeric(
        challenger.loc[list(DECISION_DIMENSIONS)], errors="raise"
    )
    incumbent_values = pd.to_numeric(
        incumbent.loc[list(DECISION_DIMENSIONS)], errors="raise"
    )
    return bool((challenger_values >= incumbent_values).all()) and bool(
        (challenger_values > incumbent_values).any()
    )


def update_project_states(
    previous: pd.DataFrame,
    current_candidates: pd.DataFrame,
    *,
    formation_date: str | date | pd.Timestamp,
    session_increment: int | None = None,
) -> pd.DataFrame:
    """Advance the minimal 1--6 week project state using observable evidence only."""

    current_day = pd.Timestamp(formation_date).normalize()
    current = current_candidates[
        current_candidates["layer"].isin(["focus", "candidate"])
    ].copy()
    current["ts_code"] = current["ts_code"].astype(str)
    current_by_code = current.set_index("ts_code", drop=False)
    rows: list[dict[str, Any]] = []
    handled: set[str] = set()

    if not previous.empty:
        active_previous = previous[
            ~previous["project_status"].isin(["exit"])
        ].copy()
        active_previous = active_previous.sort_values("formation_date").drop_duplicates(
            "ts_code", keep="last"
        )
        for old in active_previous.to_dict(orient="records"):
            code = str(old["ts_code"])
            handled.add(code)
            old_day = pd.Timestamp(old["formation_date"]).normalize()
            elapsed = (
                int(session_increment)
                if session_increment is not None
                else len(pd.bdate_range(old_day + pd.Timedelta(days=1), current_day))
            )
            age = int(old.get("age_sessions", 0)) + max(1, elapsed)
            if age > 30 or int(old.get("age_sessions", 0)) >= 30:
                row = dict(old)
                row.update(
                    {
                        "formation_date": current_day,
                        "age_sessions": age,
                        "project_status": "exit",
                        "checkpoint": "day_30",
                        "exit_reason": "requires_new_project_after_day_30",
                    }
                )
                rows.append(row)
                continue
            if code not in current_by_code.index:
                row = dict(old)
                row.update(
                    {
                        "formation_date": current_day,
                        "age_sessions": age,
                        "project_status": "exit",
                        "checkpoint": _checkpoint(age),
                        "exit_reason": "no_longer_qualified",
                    }
                )
                rows.append(row)
                continue
            new = current_by_code.loc[code]
            if isinstance(new, pd.DataFrame):
                raise ValueError("current candidates contain duplicate securities")
            new_values = pd.to_numeric(new.loc[list(DECISION_DIMENSIONS)])
            old_values = pd.to_numeric(
                pd.Series(old).loc[list(DECISION_DIMENSIONS)]
            )
            if bool((new_values >= old_values).all()) and bool(
                (new_values > old_values).any()
            ):
                status = "confirmed"
            elif bool((old_values >= new_values).all()) and bool(
                (old_values > new_values).any()
            ):
                status = "watch_only"
            else:
                status = "tracking"
            row = new.to_dict()
            row.update(
                {
                    "project_id": old["project_id"],
                    "entry_date": old["entry_date"],
                    "formation_date": current_day,
                    "age_sessions": age,
                    "project_status": status,
                    "checkpoint": _checkpoint(age),
                    "exit_reason": None,
                }
            )
            rows.append(row)

    for code, candidate in current_by_code.iterrows():
        if code in handled:
            continue
        row = candidate.to_dict()
        row.update(
            {
                "project_id": f"{code}:{current_day.date().isoformat()}",
                "entry_date": current_day,
                "formation_date": current_day,
                "age_sessions": 0,
                "project_status": "new",
                "checkpoint": "entry",
                "exit_reason": None,
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def _checkpoint(age: int) -> str | None:
    if age >= 30:
        return "day_30"
    if age >= 20:
        return "day_20"
    if age >= 10:
        return "day_10"
    if age >= 5:
        return "day_5"
    return None


MODULE_STATUSES = (
    "accuracy_supported",
    "inaccuracy_supported",
    "insufficient_evidence",
    "not_testable",
)


def classify_module(
    *,
    block_effects: list[float],
    combined_effect: float | None,
    observations: int,
    concentration_ok: bool,
    path_ok: bool,
    testable: bool = True,
    operational_failure: bool = False,
) -> str:
    """Apply the frozen direction, block-consistency and path-quality rule."""

    if not testable:
        return "not_testable"
    if operational_failure:
        return "inaccuracy_supported"
    if observations < 10 or len(block_effects) < 3 or combined_effect is None:
        return "insufficient_evidence"
    positive = sum(value > 0 for value in block_effects)
    negative = sum(value < 0 for value in block_effects)
    if combined_effect > 0 and positive >= 2 and concentration_ok and path_ok:
        return "accuracy_supported"
    if combined_effect <= 0 and negative >= 2:
        return "inaccuracy_supported"
    return "insufficient_evidence"


def available_sessions(warehouse_root: Path) -> list[pd.Timestamp]:
    root = warehouse_root / "facts" / "equity_daily"
    sessions = []
    for path in root.glob("trade_date=*"):
        try:
            sessions.append(pd.Timestamp(path.name.split("=", 1)[1]).normalize())
        except (IndexError, ValueError):
            continue
    return sorted(set(sessions))


def block_sessions(config: ValidationConfig, block: Block) -> list[pd.Timestamp]:
    sessions = [
        item
        for item in available_sessions(config.warehouse_root)
        if pd.Timestamp(block.start) <= item <= pd.Timestamp(block.end)
    ]
    if len(sessions) != 30:
        raise ValueError(
            f"block {block.id} must contain exactly 30 sessions, found {len(sessions)}"
        )
    if sessions[0].date() != block.start or sessions[-1].date() != block.end:
        raise ValueError(f"block {block.id} endpoints are not local open sessions")
    return sessions


def _read_daily_partitions(
    warehouse_root: Path,
    table: str,
    sessions: list[pd.Timestamp],
    columns: list[str],
    *,
    allow_missing: bool = False,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for session in sessions:
        path = (
            warehouse_root
            / "facts"
            / table
            / f"trade_date={session.date().isoformat()}"
            / "data.parquet"
        )
        if not path.exists():
            if allow_missing:
                continue
            raise FileNotFoundError(f"missing {table} partition: {path}")
        frames.append(pd.read_parquet(path, columns=columns))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=columns)


def _read_all_parquet(
    warehouse_root: Path, table: str, columns: list[str] | None = None
) -> pd.DataFrame:
    paths = sorted((warehouse_root / "facts" / table).rglob("*.parquet"))
    if not paths:
        raise FileNotFoundError(f"no parquet facts for {table}")
    return pd.concat(
        [pd.read_parquet(path, columns=columns) for path in paths], ignore_index=True
    )


def _load_block_inputs(
    config: ValidationConfig, block: Block
) -> dict[str, pd.DataFrame | list[pd.Timestamp]]:
    all_sessions = available_sessions(config.warehouse_root)
    formation = block_sessions(config, block)
    first_index = all_sessions.index(formation[0])
    history_sessions = all_sessions[max(0, first_index - 260) : all_sessions.index(formation[-1]) + 1]
    equity = _read_daily_partitions(
        config.warehouse_root,
        "equity_daily",
        history_sessions,
        ["trade_date", "ts_code", "open", "high", "low", "close", "amount", "available_at"],
    )
    factors = _read_daily_partitions(
        config.warehouse_root,
        "adj_factor",
        history_sessions,
        ["trade_date", "ts_code", "adj_factor", "available_at"],
    ).rename(columns={"available_at": "adj_available_at"})
    equity = equity.merge(factors, on=["trade_date", "ts_code"], how="left", validate="one_to_one")
    limits = _read_daily_partitions(
        config.warehouse_root,
        "stock_limit",
        history_sessions,
        ["trade_date", "ts_code", "up_limit", "down_limit", "available_at"],
    )
    valuations = _read_daily_partitions(
        config.warehouse_root,
        "daily_basic",
        history_sessions,
        ["trade_date", "ts_code", "pe_ttm", "pb", "circ_mv", "turnover_rate_f", "available_at"],
    )
    indexes = _read_daily_partitions(
        config.warehouse_root,
        "index_daily",
        history_sessions,
        ["trade_date", "index_code", "close", "available_at"],
    )
    industry_daily = _read_daily_partitions(
        config.warehouse_root,
        "industry_daily",
        history_sessions,
        ["trade_date", "industry_code", "close"],
        allow_missing=True,
    ).rename(columns={"industry_code": "index_code"})
    theme_daily = _read_daily_partitions(
        config.warehouse_root,
        "theme_daily",
        history_sessions,
        ["trade_date", "theme_code", "close"],
        allow_missing=True,
    ).rename(columns={"theme_code": "index_code"})
    financial_columns = [
        "ts_code", "report_period", "available_at", "revision_no", "tr_yoy",
        "netprofit_yoy", "dt_netprofit_yoy", "ocf_yoy", "ocfps",
    ]
    cash_columns = [
        "ts_code", "report_period", "available_at", "revision_no", "n_cashflow_act",
    ]
    return {
        "formation_sessions": formation,
        "history_sessions": history_sessions,
        "equity": equity,
        "limits": limits,
        "valuations": valuations,
        "indexes": indexes,
        "official": pd.concat([industry_daily, theme_daily], ignore_index=True),
        "financials": _read_all_parquet(config.warehouse_root, "financial_indicator", financial_columns),
        "cash_flow": _read_all_parquet(config.warehouse_root, "cash_flow", cash_columns),
        "industry_catalog": _read_all_parquet(config.warehouse_root, "industry_catalog"),
        "industry_member": _read_all_parquet(config.warehouse_root, "industry_member"),
        "theme_catalog": _read_all_parquet(config.warehouse_root, "theme_catalog"),
        "theme_member": _read_all_parquet(config.warehouse_root, "theme_member"),
    }


def _as_of_sector_inputs(
    data: dict[str, Any], formation_date: pd.Timestamp
) -> tuple[pd.DataFrame, pd.DataFrame]:
    boundary = _formation_boundary(formation_date).tz_convert("UTC")
    industry_catalog = data["industry_catalog"].copy()
    industry_member = data["industry_member"].copy()
    theme_catalog = data["theme_catalog"].copy()
    theme_member = data["theme_member"].copy()
    for frame in (industry_catalog, industry_member, theme_catalog, theme_member):
        available = pd.to_datetime(frame["available_at"], utc=True, errors="coerce")
        frame.drop(frame.index[available.isna() | (available > boundary)], inplace=True)
    catalogs = pd.concat(
        [
            pd.DataFrame(
                {
                    "group_type": "industry",
                    "group_code": industry_catalog["industry_code"].astype(str),
                    "group_name": industry_catalog["industry_name"],
                    "level": industry_catalog["level"],
                    "official_index_code": industry_catalog["industry_code"].astype(str),
                }
            ),
            pd.DataFrame(
                {
                    "group_type": "theme",
                    "group_code": theme_catalog["theme_code"].astype(str),
                    "group_name": theme_catalog["theme_name"],
                    "level": theme_catalog["category"],
                    "official_index_code": theme_catalog["theme_code"].astype(str),
                }
            ),
        ],
        ignore_index=True,
    ).drop_duplicates(["group_type", "group_code"], keep="last")
    memberships = pd.concat(
        [
            pd.DataFrame(
                {
                    "group_type": "industry",
                    "group_code": industry_member["industry_code"].astype(str),
                    "ts_code": industry_member["ts_code"].astype(str),
                    "valid_from": industry_member["valid_from"],
                    "valid_to": industry_member["valid_to"],
                }
            ),
            pd.DataFrame(
                {
                    "group_type": "theme",
                    "group_code": theme_member["theme_code"].astype(str),
                    "ts_code": theme_member["ts_code"].astype(str),
                    "valid_from": theme_member["valid_from"],
                    "valid_to": theme_member["valid_to"],
                }
            ),
        ],
        ignore_index=True,
    )
    return catalogs, memberships


STOCK_COMPACT_COLUMNS = [
    "analysis_date", "ts_code", "return_1d", "return_5d", "return_10d",
    "return_20d", "return_60d", "relative_return_20d", "price_location_60d",
    "price_location_82d", "realized_volatility_20d_annualized", "atr_ratio_20d",
    "average_amount_20d", "current_amount_ratio_20d", "recent_limit_up_count_5d",
    "pe_ttm", "pb", "pe_ttm_percentile_250d", "pb_percentile_250d",
    "coverage_status",
]

HOTSPOT_COMPACT_COLUMNS = [
    "analysis_date", "group_type", "group_code", "group_name", "level",
    "member_count", "observed_member_count", "member_coverage_ratio",
    "coverage_status", "equal_weight_return_5d", "breadth_5d",
    "relative_return_5d", "equal_weight_return_20d", "breadth_20d",
    "relative_return_20d", "turnover_share_change_5d", "new_high_20d_share",
    "group_amount_vs_20d_average", "narrow_participation_flag",
    "high_volume_low_progress_flag", "turnover_return_divergence_flag",
]


def _formation_features(
    data: dict[str, Any], formation_date: pd.Timestamp
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    boundary = _formation_boundary(formation_date).tz_convert("UTC")

    def legal(frame: pd.DataFrame, *, adj: bool = False) -> pd.DataFrame:
        values = frame[pd.to_datetime(frame["trade_date"]).dt.normalize() <= formation_date].copy()
        if "available_at" in values:
            values = values[pd.to_datetime(values["available_at"], utc=True) <= boundary]
        if adj and "adj_available_at" in values:
            values = values[pd.to_datetime(values["adj_available_at"], utc=True) <= boundary]
        return values

    equity = legal(data["equity"], adj=True)
    limits = legal(data["limits"])
    valuations = legal(data["valuations"])
    indexes = legal(data["indexes"])
    benchmark = indexes[indexes["index_code"].astype(str) == "000300.SH"][
        ["trade_date", "close"]
    ]
    current_count = int(
        equity.loc[
            pd.to_datetime(equity["trade_date"]).dt.normalize() == formation_date,
            "ts_code",
        ].nunique()
    )
    market = compute_market_context_features(
        equity,
        indexes,
        limits,
        analysis_date=formation_date.date(),
        expected_current_rows=current_count,
    )
    stocks = compute_stock_context_features(
        equity,
        benchmark,
        limits,
        valuations,
        analysis_date=formation_date.date(),
    )
    market_sessions = sorted(pd.to_datetime(equity["trade_date"]).dt.normalize().unique())
    hotspot_start = pd.Timestamp(market_sessions[max(0, len(market_sessions) - 83)])
    hotspot_equity = equity[
        pd.to_datetime(equity["trade_date"]).dt.normalize() >= hotspot_start
    ]
    hotspot_limits = limits[
        pd.to_datetime(limits["trade_date"]).dt.normalize() >= hotspot_start
    ]
    hotspot_benchmark = benchmark[
        pd.to_datetime(benchmark["trade_date"]).dt.normalize() >= hotspot_start
    ]
    official = data["official"].copy()
    official = official[
        (pd.to_datetime(official["trade_date"]).dt.normalize() >= hotspot_start)
        & (pd.to_datetime(official["trade_date"]).dt.normalize() <= formation_date)
    ]
    catalogs, memberships = _as_of_sector_inputs(data, formation_date)
    minutes = pd.DataFrame(
        columns=["trade_date", "ts_code", "minute", "close", "amount"]
    )
    hotspots = compute_hotspot_features(
        hotspot_equity,
        catalogs,
        memberships,
        hotspot_benchmark,
        hotspot_limits,
        official,
        minutes,
        analysis_date=formation_date.date(),
    )
    return market, stocks, hotspots, memberships


def _latest_company_facts(
    data: dict[str, Any], formation_date: pd.Timestamp
) -> pd.DataFrame:
    financials = select_latest_available_financials(
        data["financials"], formation_date=formation_date
    )
    cash = select_latest_available_financials(
        data["cash_flow"], formation_date=formation_date
    )
    cash = cash[["ts_code", "report_period", "n_cashflow_act"]].copy()
    return financials.merge(
        cash, on=["ts_code", "report_period"], how="left", validate="one_to_one"
    )


def _active_memberships(
    memberships: pd.DataFrame, formation_date: pd.Timestamp
) -> pd.DataFrame:
    values = memberships.copy()
    values["valid_from"] = pd.to_datetime(values["valid_from"], errors="coerce")
    values["valid_to"] = pd.to_datetime(values["valid_to"], errors="coerce")
    return values[
        (values["valid_from"] <= formation_date)
        & (values["valid_to"].isna() | (values["valid_to"] >= formation_date))
    ].copy()


def limit_to_tradable_route(
    ranked_codes: list[str], *, tradable_codes: set[str], limit: int
) -> list[str]:
    """Apply the route cap only after removing names absent from today's stock pool."""

    if limit < 0:
        raise ValueError("route limit must be non-negative")
    selected: list[str] = []
    seen: set[str] = set()
    for raw_code in ranked_codes:
        code = str(raw_code)
        if code in seen or code not in tradable_codes:
            continue
        seen.add(code)
        selected.append(code)
        if len(selected) >= limit:
            break
    return selected


def _build_route_evidence(
    *,
    config: ValidationConfig,
    formation_date: pd.Timestamp,
    market: pd.DataFrame,
    stocks: pd.DataFrame,
    hotspots: pd.DataFrame,
    memberships: pd.DataFrame,
    company_facts: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    stock = stocks.copy().set_index("ts_code", drop=False)
    tradable_codes = set(stock.index.astype(str))
    complete_groups = hotspots[
        hotspots["coverage_status"].astype(str).str.startswith("complete")
        & (pd.to_numeric(hotspots["breadth_5d"], errors="coerce") >= 0.50)
        & (pd.to_numeric(hotspots["relative_return_5d"], errors="coerce") > 0)
    ].copy()
    complete_groups = complete_groups.sort_values(
        ["relative_return_20d", "breadth_5d", "turnover_share_change_5d"],
        ascending=False,
        na_position="last",
    ).head(10)
    active = _active_memberships(memberships, formation_date)
    top_keys = set(
        zip(complete_groups["group_type"].astype(str), complete_groups["group_code"].astype(str))
    )
    active["group_key"] = list(zip(active["group_type"].astype(str), active["group_code"].astype(str)))
    active_top = active[active["group_key"].isin(top_keys)].copy()
    group_rank = {
        (str(row.group_type), str(row.group_code)): rank
        for rank, row in enumerate(complete_groups.itertuples(index=False), start=1)
    }
    active_top["group_rank"] = active_top["group_key"].map(group_rank)
    hotspot_members = active_top.merge(
        stocks[["ts_code", "relative_return_20d", "current_amount_ratio_20d"]],
        on="ts_code",
        how="inner",
    ).sort_values(
        ["group_rank", "relative_return_20d", "current_amount_ratio_20d"],
        ascending=[True, False, False],
        na_position="last",
    )
    hotspot_codes = limit_to_tradable_route(
        hotspot_members.drop_duplicates("ts_code")["ts_code"].astype(str).tolist(),
        tradable_codes=tradable_codes,
        limit=config.route_recall_cap,
    )

    company = company_facts.copy()
    company["report_age_days"] = (
        formation_date - pd.to_datetime(company["report_period"]).dt.normalize()
    ).dt.days
    numeric_company = [
        "tr_yoy", "netprofit_yoy", "dt_netprofit_yoy", "ocf_yoy", "ocfps", "n_cashflow_act"
    ]
    for column in numeric_company:
        company[column] = pd.to_numeric(company[column], errors="coerce")
    company["company_evidence"] = (
        company["report_age_days"].between(0, 150)
        & (company["tr_yoy"] > 0)
        & (company["netprofit_yoy"] > 0)
        & (company["dt_netprofit_yoy"] > 0)
        & (company["n_cashflow_act"] > 0)
    )
    earnings = company[company["company_evidence"]].sort_values(
        ["dt_netprofit_yoy", "netprofit_yoy", "tr_yoy", "available_at"],
        ascending=[False, False, False, False],
        na_position="last",
    )
    earnings_codes = limit_to_tradable_route(
        earnings["ts_code"].astype(str).tolist(),
        tradable_codes=tradable_codes,
        limit=config.route_recall_cap,
    )

    price = stocks[
        (pd.to_numeric(stocks["relative_return_20d"], errors="coerce") > 0)
        & (pd.to_numeric(stocks["price_location_60d"], errors="coerce") >= 0.50)
        & (pd.to_numeric(stocks["current_amount_ratio_20d"], errors="coerce") >= 1.0)
        & (pd.to_numeric(stocks["average_amount_20d"], errors="coerce") >= 20000.0)
    ].sort_values(
        ["relative_return_20d", "current_amount_ratio_20d"],
        ascending=False,
        na_position="last",
    )
    price_codes = limit_to_tradable_route(
        price["ts_code"].astype(str).tolist(),
        tradable_codes=tradable_codes,
        limit=config.route_recall_cap,
    )
    route_lists = {
        "hotspot": hotspot_codes,
        "earnings": earnings_codes,
        "price": price_codes,
    }
    research_codes = round_robin_union(
        route_lists, limit=config.route_recall_cap * len(config.supported_routes)
    )
    company_by_code = company.set_index("ts_code", drop=False)
    active_top_by_code = active_top.sort_values("group_rank").drop_duplicates("ts_code").set_index("ts_code")
    amounts = pd.to_numeric(stocks["average_amount_20d"], errors="coerce")
    q33, q67 = amounts.quantile([0.33, 0.67]).tolist()
    market_breadth = float(market.iloc[0].get("breadth_20d", np.nan))
    evidence_rows: list[dict[str, Any]] = []
    for code in research_codes:
        if code not in stock.index:
            continue
        observation = stock.loc[code]
        if isinstance(observation, pd.DataFrame):
            raise ValueError("stock context has duplicate codes")
        financial = company_by_code.loc[code] if code in company_by_code.index else None
        if isinstance(financial, pd.DataFrame):
            financial = financial.iloc[-1]
        routes = [route for route, codes in route_lists.items() if code in codes]
        report_age = int(financial["report_age_days"]) if financial is not None else 9999
        freshness = 3 if report_age <= 60 else 2 if report_age <= 120 else 1
        if financial is None:
            consistency = 0
            company_evidence = False
        else:
            positives = sum(
                bool(pd.notna(financial[field]) and float(financial[field]) > 0)
                for field in ("tr_yoy", "netprofit_yoy", "dt_netprofit_yoy", "ocf_yoy")
            )
            consistency = 3 if positives == 4 else 2 if positives >= 3 else 1
            company_evidence = bool(financial["company_evidence"])
        hotspot_support = 0
        group_name = None
        if code in active_top_by_code.index:
            member = active_top_by_code.loc[code]
            rank = int(member["group_rank"])
            hotspot_support = 3 if rank <= 3 else 2
            group_name = next(
                (
                    str(row.group_name)
                    for row in complete_groups.itertuples(index=False)
                    if str(row.group_type) == str(member["group_type"])
                    and str(row.group_code) == str(member["group_code"])
                ),
                None,
            )
        return_20 = float(observation["return_20d"]) if pd.notna(observation["return_20d"]) else np.nan
        location = float(observation["price_location_60d"]) if pd.notna(observation["price_location_60d"]) else np.nan
        if np.isfinite(return_20) and np.isfinite(location) and 0 <= return_20 <= 0.20 and location <= 0.90:
            price_safety = 3
        elif np.isfinite(return_20) and np.isfinite(location) and return_20 <= 0.40 and location < 0.99:
            price_safety = 2
        else:
            price_safety = 1
        average_amount = float(observation["average_amount_20d"]) if pd.notna(observation["average_amount_20d"]) else np.nan
        liquidity = 3 if average_amount >= q67 else 2 if average_amount >= q33 else 1
        hard_invalid = (
            not np.isfinite(average_amount)
            or average_amount < 20000.0
            or (pd.notna(observation["return_5d"]) and float(observation["return_5d"]) > 0.30)
            or (np.isfinite(location) and location >= 0.995)
            or (np.isfinite(market_breadth) and market_breadth < 0.45 and price_safety < 2)
        )
        evidence_rows.append(
            {
                "formation_date": formation_date,
                "ts_code": code,
                "routes": "|".join(routes),
                "company_evidence": company_evidence,
                "hard_invalid": hard_invalid,
                "evidence_freshness": freshness,
                "earnings_cash_consistency": consistency,
                "hotspot_support": hotspot_support,
                "price_consumption_safety": price_safety,
                "liquidity": liquidity,
                "market_breadth_20d": market_breadth,
                "hotspot_group_name": group_name,
                "report_period": financial["report_period"] if financial is not None else pd.NaT,
                "report_available_at": financial["available_at"] if financial is not None else pd.NaT,
                "tr_yoy": financial["tr_yoy"] if financial is not None else np.nan,
                "netprofit_yoy": financial["netprofit_yoy"] if financial is not None else np.nan,
                "dt_netprofit_yoy": financial["dt_netprofit_yoy"] if financial is not None else np.nan,
                "ocf_yoy": financial["ocf_yoy"] if financial is not None else np.nan,
                "n_cashflow_act": financial["n_cashflow_act"] if financial is not None else np.nan,
                "return_5d": observation["return_5d"],
                "return_20d": observation["return_20d"],
                "relative_return_20d": observation["relative_return_20d"],
                "price_location_60d": observation["price_location_60d"],
                "current_amount_ratio_20d": observation["current_amount_ratio_20d"],
                "average_amount_20d": observation["average_amount_20d"],
                "pe_ttm": observation["pe_ttm"],
                "pb": observation["pb"],
            }
        )
    route_rows = [
        {
            "formation_date": formation_date,
            "route": route,
            "route_rank": rank,
            "ts_code": code,
        }
        for route, codes in route_lists.items()
        for rank, code in enumerate(codes, start=1)
    ]
    evidence = pd.DataFrame(evidence_rows)
    decisions = compress_candidates(
        evidence, candidate_cap=config.candidate_cap, focus_cap=config.focus_cap
    ) if not evidence.empty else evidence
    return pd.DataFrame(route_rows), evidence, decisions


def _matched_controls(
    *,
    formation_date: pd.Timestamp,
    stocks: pd.DataFrame,
    hotspots: pd.DataFrame,
    memberships: pd.DataFrame,
    evidence: pd.DataFrame,
    decisions: pd.DataFrame,
) -> pd.DataFrame:
    if evidence.empty:
        return pd.DataFrame()
    universe = stocks.copy()
    amounts = pd.to_numeric(universe["average_amount_20d"], errors="coerce")
    q33, q67 = amounts.quantile([0.33, 0.67]).tolist()
    universe["liquidity"] = np.where(amounts >= q67, 3, np.where(amounts >= q33, 2, 1))
    universe["exchange"] = universe["ts_code"].astype(str).str.rsplit(".", n=1).str[-1]
    active = _active_memberships(memberships, formation_date)
    levels = hotspots[["group_type", "group_code", "level"]].drop_duplicates()
    industry = active.merge(levels, on=["group_type", "group_code"], how="left")
    industry = industry[
        (industry["group_type"] == "industry") & (industry["level"].astype(str) == "L1")
    ].drop_duplicates("ts_code")
    industry_map = industry.set_index("ts_code")["group_code"].astype(str).to_dict()
    universe["industry_l1"] = universe["ts_code"].map(industry_map)
    research_codes = set(evidence["ts_code"].astype(str))
    chosen: list[dict[str, Any]] = []
    targets = evidence[["ts_code", "liquidity"]].copy()
    targets["control_for"] = "research"
    selected = decisions[decisions["layer"].isin(["focus", "candidate"])][
        ["ts_code", "liquidity"]
    ].copy()
    selected["control_for"] = "candidate"
    targets = pd.concat([targets, selected], ignore_index=True)
    for target in targets.itertuples(index=False):
        code = str(target.ts_code)
        exchange = code.rsplit(".", 1)[-1]
        industry_code = industry_map.get(code)
        pool = universe[
            (~universe["ts_code"].astype(str).isin(research_codes))
            & (universe["exchange"] == exchange)
            & (universe["liquidity"] == int(target.liquidity))
            & (pd.to_numeric(universe["average_amount_20d"], errors="coerce") >= 20000.0)
        ]
        industry_pool = pool[pool["industry_l1"] == industry_code] if industry_code else pool.iloc[0:0]
        if not industry_pool.empty:
            pool = industry_pool
        if pool.empty:
            continue
        ranked = sorted(
            pool["ts_code"].astype(str).tolist(),
            key=lambda candidate: hashlib.sha256(
                f"{formation_date.date()}|{code}|{candidate}|v3-control-v1".encode()
            ).hexdigest(),
        )
        chosen.append(
            {
                "formation_date": formation_date,
                "ts_code": ranked[0],
                "policy": f"matched_{target.control_for}_control",
                "layer": "control",
                "matched_to": code,
                "control_for": target.control_for,
                "exchange": exchange,
                "industry_l1": industry_code,
                "liquidity": int(target.liquidity),
            }
        )
    return pd.DataFrame(chosen)


def _write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)


def _write_json(payload: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def _write_manifests(config: ValidationConfig, output: Path) -> None:
    _write_json(_as_jsonable_config(config), output / "manifests" / "config_snapshot.json")
    capability = {
        "supported": {
            "market_environment": "production formula, business-date and available_at bounded",
            "hotspot": "production sector-hotspot-v3 formula; industry and official-theme membership",
            "earnings": "financial indicator plus operating cash flow, available_at bounded",
            "price_liquidity_valuation": "production stock-trading-context-v2 formula",
            "candidate_management": "frozen hard gates, Pareto comparison and state protocol",
        },
        "not_testable": {
            "company_event": "missing repeatable event-body economic materiality fields",
            "industry_cycle": "missing governed demand, supply, price, inventory and company sensitivity history",
            "distress_repair": "missing repeatable formal-risk relief and multi-statement repair execution history",
        },
    }
    _write_json(capability, output / "manifests" / "capability_manifest.json")
    inputs = []
    for table in (
        "equity_daily", "adj_factor", "stock_limit", "daily_basic", "index_daily",
        "industry_daily", "theme_daily", "financial_indicator", "cash_flow",
        "industry_catalog", "industry_member", "theme_catalog", "theme_member",
    ):
        root = config.warehouse_root / "facts" / table
        files = list(root.rglob("*.parquet"))
        inputs.append(
            {
                "table": table,
                "root": str(root),
                "file_count": len(files),
                "bytes": sum(path.stat().st_size for path in files),
                "latest_mtime_ns": max((path.stat().st_mtime_ns for path in files), default=None),
            }
        )
    _write_json(inputs, output / "manifests" / "input_manifest.json")


def run_blocks(
    config: ValidationConfig,
    block_ids: list[str],
) -> None:
    output = prepare_output_root(config)
    _write_manifests(config, output)
    blocks = {block.id: block for block in config.blocks}
    unknown = sorted(set(block_ids) - set(blocks))
    if unknown:
        raise ValueError(f"unknown blocks: {', '.join(unknown)}")
    for block_id in block_ids:
        block = blocks[block_id]
        started = time.perf_counter()
        print(f"[{block_id}] loading local facts", flush=True)
        data = _load_block_inputs(config, block)
        previous_projects = pd.DataFrame()
        for position, formation_date in enumerate(data["formation_sessions"], start=1):
            date_root = (
                output
                / "tables"
                / "formations"
                / f"block={block_id}"
                / f"formation_date={formation_date.date().isoformat()}"
            )
            completion_path = date_root / "completion.json"
            if completion_path.exists():
                previous_projects = pd.read_parquet(date_root / "projects.parquet")
                print(f"[{block_id}] {position:02d}/30 resume {formation_date.date()}", flush=True)
                continue
            day_started = time.perf_counter()
            market, stocks, hotspots, memberships = _formation_features(data, formation_date)
            company_facts = _latest_company_facts(data, formation_date)
            routes, evidence, decisions = _build_route_evidence(
                config=config,
                formation_date=formation_date,
                market=market,
                stocks=stocks,
                hotspots=hotspots,
                memberships=memberships,
                company_facts=company_facts,
            )
            if not decisions.empty:
                decisions["block"] = block_id
                decisions["policy"] = "v3_partial_candidate"
            controls = _matched_controls(
                formation_date=formation_date,
                stocks=stocks,
                hotspots=hotspots,
                memberships=memberships,
                evidence=evidence,
                decisions=decisions,
            )
            projects = update_project_states(
                previous_projects,
                decisions,
                formation_date=formation_date,
                session_increment=1,
            )
            if not projects.empty:
                projects["block"] = block_id
            previous_projects = projects
            _write_parquet(market, date_root / "market.parquet")
            _write_parquet(stocks[[column for column in STOCK_COMPACT_COLUMNS if column in stocks]], date_root / "stocks.parquet")
            _write_parquet(hotspots[[column for column in HOTSPOT_COMPACT_COLUMNS if column in hotspots]], date_root / "hotspots.parquet")
            _write_parquet(routes, date_root / "routes.parquet")
            _write_parquet(evidence, date_root / "evidence.parquet")
            _write_parquet(decisions, date_root / "decisions.parquet")
            _write_parquet(controls, date_root / "controls.parquet")
            _write_parquet(projects, date_root / "projects.parquet")
            elapsed = time.perf_counter() - day_started
            _write_json(
                {
                    "block": block_id,
                    "formation_date": formation_date.date().isoformat(),
                    "elapsed_seconds": elapsed,
                    "research_count": len(evidence),
                    "candidate_count": int(decisions["layer"].isin(["focus", "candidate"]).sum()) if not decisions.empty else 0,
                    "focus_count": int((decisions["layer"] == "focus").sum()) if not decisions.empty else 0,
                },
                completion_path,
            )
            print(
                f"[{block_id}] {position:02d}/30 formed {formation_date.date()} in {elapsed:.1f}s",
                flush=True,
            )
        block_elapsed = time.perf_counter() - started
        _write_json(
            {"block": block_id, "status": "formed", "elapsed_seconds": block_elapsed},
            output / "manifests" / f"block_{block_id}_status.json",
        )
        print(f"[{block_id}] completed formation in {block_elapsed / 60:.1f}m", flush=True)


def _read_formation_outputs(
    output: Path, block_id: str, table: str
) -> pd.DataFrame:
    paths = sorted(
        (output / "tables" / "formations" / f"block={block_id}").glob(
            f"formation_date=*/{table}.parquet"
        )
    )
    if len(paths) != 30:
        raise ValueError(f"block {block_id} has {len(paths)}/30 {table} outputs")
    return pd.concat([pd.read_parquet(path) for path in paths], ignore_index=True)


def _outcome_price_frame(
    config: ValidationConfig, block: Block
) -> pd.DataFrame:
    sessions = available_sessions(config.warehouse_root)
    start_index = sessions.index(pd.Timestamp(block.start))
    end_index = sessions.index(pd.Timestamp(block.end))
    required = sessions[start_index : end_index + max(config.horizons) + 1]
    if len(required) != 30 + max(config.horizons):
        raise ValueError(f"block {block.id} lacks a complete 30-session future window")
    equity = _read_daily_partitions(
        config.warehouse_root,
        "equity_daily",
        required,
        ["trade_date", "ts_code", "high", "low", "close"],
    )
    factors = _read_daily_partitions(
        config.warehouse_root,
        "adj_factor",
        required,
        ["trade_date", "ts_code", "adj_factor"],
    )
    prices = equity.merge(
        factors, on=["trade_date", "ts_code"], how="left", validate="one_to_one"
    )
    for raw, adjusted in (
        ("close", "adj_close"), ("high", "adj_high"), ("low", "adj_low")
    ):
        prices[adjusted] = pd.to_numeric(prices[raw], errors="coerce") * pd.to_numeric(
            prices["adj_factor"], errors="coerce"
        )
    return prices[["trade_date", "ts_code", "adj_close", "adj_high", "adj_low"]]


def _replacement_selections(projects: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    selections: list[dict[str, Any]] = []
    pairs: list[dict[str, Any]] = []
    for formation_date, day in projects.groupby("formation_date", sort=True):
        exits = day[day["project_status"] == "exit"]
        entries = day[day["project_status"] == "new"]
        if exits.empty or entries.empty:
            continue
        available_entries = list(entries.index)
        for exit_index, old in exits.iterrows():
            if not available_entries:
                break
            eligible = [
                index
                for index in available_entries
                if challenger_can_replace(
                    entries.loc[index],
                    old,
                    incumbent_invalid=old.get("exit_reason") == "no_longer_qualified",
                )
            ]
            if not eligible:
                continue
            chosen = min(
                eligible,
                key=lambda index: hashlib.sha256(
                    f"{formation_date}|{old['ts_code']}|{entries.loc[index, 'ts_code']}|replacement-v1".encode()
                ).hexdigest(),
            )
            available_entries.remove(chosen)
            new = entries.loc[chosen]
            pair_id = f"{pd.Timestamp(formation_date).date()}:{old['ts_code']}:{new['ts_code']}"
            pairs.append(
                {
                    "pair_id": pair_id,
                    "formation_date": formation_date,
                    "old_ts_code": old["ts_code"],
                    "new_ts_code": new["ts_code"],
                    "old_exit_reason": old.get("exit_reason"),
                }
            )
            selections.extend(
                [
                    {
                        "formation_date": formation_date,
                        "ts_code": old["ts_code"],
                        "policy": "replacement_old",
                        "layer": "counterfactual_keep",
                    },
                    {
                        "formation_date": formation_date,
                        "ts_code": new["ts_code"],
                        "policy": "replacement_new",
                        "layer": "actual_challenger",
                    },
                ]
            )
    return pd.DataFrame(selections), pd.DataFrame(pairs)


def _omission_cases(
    prices: pd.DataFrame,
    evidence: pd.DataFrame,
    formation_sessions: list[pd.Timestamp],
) -> pd.DataFrame:
    price = prices.copy()
    price["trade_date"] = pd.to_datetime(price["trade_date"]).dt.normalize()
    market_sessions = sorted(price["trade_date"].unique())
    rows: list[dict[str, Any]] = []
    research_by_date = {
        pd.Timestamp(day).normalize(): set(group["ts_code"].astype(str))
        for day, group in evidence.groupby("formation_date")
    }
    for formation in formation_sessions:
        position = market_sessions.index(np.datetime64(formation))
        future_dates = market_sessions[position + 1 : position + 21]
        current = price[price["trade_date"] == formation][["ts_code", "adj_close"]]
        future = price[price["trade_date"].isin(future_dates)]
        max_high = future.groupby("ts_code")["adj_high"].max().rename("future_max_high")
        candidates = current.merge(max_high, on="ts_code", how="inner")
        candidates["max_return_20d"] = candidates["future_max_high"] / candidates["adj_close"] - 1.0
        candidates = candidates[
            (candidates["max_return_20d"] >= 0.20)
            & (~candidates["ts_code"].astype(str).isin(research_by_date.get(formation, set())))
        ].nlargest(1, "max_return_20d")
        for item in candidates.itertuples(index=False):
            rows.append(
                {
                    "formation_date": formation,
                    "ts_code": item.ts_code,
                    "max_return_20d": item.max_return_20d,
                    "missing_evidence": "未进入热点、盈利或价格三个可执行入口的前30；事件、周期、困境入口本地不可验证",
                }
            )
    return pd.DataFrame(rows)


def reveal_outcomes(config: ValidationConfig) -> None:
    output = prepare_output_root(config)
    all_outcomes: list[pd.DataFrame] = []
    all_pairs: list[pd.DataFrame] = []
    all_omissions: list[pd.DataFrame] = []
    for block in config.blocks:
        print(f"[{block.id}] revealing future paths", flush=True)
        routes = _read_formation_outputs(output, block.id, "routes")
        evidence = _read_formation_outputs(output, block.id, "evidence")
        decisions = _read_formation_outputs(output, block.id, "decisions")
        controls = _read_formation_outputs(output, block.id, "controls")
        projects = _read_formation_outputs(output, block.id, "projects")
        selections: list[pd.DataFrame] = []
        if not routes.empty:
            route_selection = routes.copy()
            route_selection["policy"] = "route_" + route_selection["route"].astype(str)
            route_selection["layer"] = "route_recall"
            selections.append(route_selection)
        if not evidence.empty:
            research = evidence[["formation_date", "ts_code"]].copy()
            research["policy"] = "research_union"
            research["layer"] = "research"
            selections.append(research)
        selected = decisions[decisions["layer"].isin(["focus", "candidate"])].copy()
        if not selected.empty:
            selected["policy"] = "v3_partial_candidate"
            selections.append(selected[["formation_date", "ts_code", "policy", "layer"]])
        if not controls.empty:
            selections.append(controls[["formation_date", "ts_code", "policy", "layer"]])
        if not projects.empty:
            lifecycle = projects[projects["project_status"] != "exit"].copy()
            lifecycle["age_bucket"] = pd.cut(
                lifecycle["age_sessions"],
                bins=[-1, 4, 9, 19, 30],
                labels=["0_4", "5_9", "10_19", "20_30"],
            ).astype(str)
            lifecycle["policy"] = "lifecycle_age_" + lifecycle["age_bucket"]
            lifecycle["layer"] = lifecycle["project_status"]
            selections.append(lifecycle[["formation_date", "ts_code", "policy", "layer"]])
        replacements, pairs = _replacement_selections(projects)
        if not replacements.empty:
            selections.append(replacements)
            pairs["block"] = block.id
            all_pairs.append(pairs)
        frozen = pd.concat(selections, ignore_index=True).drop_duplicates(
            ["formation_date", "ts_code", "policy", "layer"]
        )
        prices = _outcome_price_frame(config, block)
        outcomes = compute_forward_outcomes(
            prices,
            frozen,
            horizons=config.horizons,
            target_return=config.target_return,
        )
        outcomes["block"] = block.id
        _write_parquet(frozen, output / "tables" / "selections" / f"block={block.id}.parquet")
        _write_parquet(outcomes, output / "tables" / "outcomes" / f"block={block.id}.parquet")
        omissions = _omission_cases(prices, evidence, block_sessions(config, block))
        omissions["block"] = block.id
        all_omissions.append(omissions)
        all_outcomes.append(outcomes)
    combined = pd.concat(all_outcomes, ignore_index=True)
    _write_parquet(combined, output / "tables" / "outcomes_all.parquet")
    _write_parquet(
        pd.concat(all_pairs, ignore_index=True) if all_pairs else pd.DataFrame(),
        output / "tables" / "replacement_pairs.parquet",
    )
    _write_parquet(pd.concat(all_omissions, ignore_index=True), output / "tables" / "omission_cases.parquet")
    _write_json({"status": "revealed", "rows": len(combined)}, output / "manifests" / "reveal_status.json")


def _policy_metrics(outcomes: pd.DataFrame, policy: str, *, layer: str | None = None) -> dict[str, float]:
    sample = outcomes[
        (outcomes["policy"] == policy)
        & (outcomes["horizon"] == 20)
        & outcomes["complete_horizon"].astype(bool)
    ]
    if layer is not None:
        sample = sample[sample["layer"] == layer]
    return {
        "observations": float(len(sample)),
        "precision": float(sample["target_touched"].astype(bool).mean()) if len(sample) else np.nan,
        "median_terminal_return": float(sample["terminal_return"].median()) if len(sample) else np.nan,
        "median_max_adverse_return": float(sample["max_adverse_return"].median()) if len(sample) else np.nan,
        "clean_path_5_share": float(sample["target_before_drawdown_5"].astype(bool).mean()) if len(sample) else np.nan,
    }


def _module_diagnostics(
    outcomes: pd.DataFrame, evidence: pd.DataFrame, projects: pd.DataFrame
) -> pd.DataFrame:
    comparisons = {
        "discovery": ("research_union", None, "matched_research_control", None),
        "compression": ("v3_partial_candidate", None, "research_union", None),
        "focus": ("v3_partial_candidate", "focus", "v3_partial_candidate", "candidate"),
        "replacement": ("replacement_new", None, "replacement_old", None),
        "lifecycle": ("lifecycle_later", None, "matched_candidate_control", None),
    }
    expanded = outcomes.copy()
    expanded.loc[
        expanded["policy"].isin(
            ["lifecycle_age_5_9", "lifecycle_age_10_19", "lifecycle_age_20_30"]
        ),
        "policy",
    ] = "lifecycle_later"
    project_max_age = (
        projects.groupby("project_id")["age_sessions"].max()
        if not projects.empty
        else pd.Series(dtype=float)
    )
    lifecycle_operational_failure = bool(
        len(project_max_age) >= 30 and int((project_max_age >= 5).sum()) < 10
    )
    rows: list[dict[str, Any]] = []
    for module, (left_policy, left_layer, right_policy, right_layer) in comparisons.items():
        left = _policy_metrics(expanded, left_policy, layer=left_layer)
        right = _policy_metrics(expanded, right_policy, layer=right_layer)
        combined_effect = (
            left["precision"] - right["precision"]
            if np.isfinite(left["precision"]) and np.isfinite(right["precision"])
            else None
        )
        block_effects: list[float] = []
        for block_id in ("A", "B", "C"):
            block = expanded[expanded["block"] == block_id]
            block_left = _policy_metrics(block, left_policy, layer=left_layer)
            block_right = _policy_metrics(block, right_policy, layer=right_layer)
            if np.isfinite(block_left["precision"]) and np.isfinite(block_right["precision"]):
                block_effects.append(block_left["precision"] - block_right["precision"])
        path_ok = (
            np.isfinite(left["median_max_adverse_return"])
            and np.isfinite(right["median_max_adverse_return"])
            and left["median_max_adverse_return"] >= right["median_max_adverse_return"] - 0.05
            and left["median_terminal_return"] >= right["median_terminal_return"] - 0.03
        )
        concentration_ok = True
        if module in {"discovery", "compression", "focus"}:
            hits = expanded[
                (expanded["policy"] == left_policy)
                & (expanded["horizon"] == 20)
                & expanded["target_touched"].astype(bool)
            ][["formation_date", "ts_code"]]
            if left_layer is not None:
                hit_index = expanded[
                    (expanded["policy"] == left_policy)
                    & (expanded["layer"] == left_layer)
                    & (expanded["horizon"] == 20)
                    & expanded["target_touched"].astype(bool)
                ][["formation_date", "ts_code"]]
                hits = hit_index
            if len(hits):
                stock_share = hits["ts_code"].value_counts(normalize=True).max()
                enriched = hits.merge(
                    evidence[["formation_date", "ts_code", "hotspot_group_name"]].drop_duplicates(),
                    on=["formation_date", "ts_code"],
                    how="left",
                )
                named = enriched["hotspot_group_name"].dropna()
                group_share = named.value_counts(normalize=True).max() if len(named) else 0.0
                concentration_ok = bool(stock_share <= 0.20 and group_share <= 0.50)
        observations = int(min(left["observations"], right["observations"]))
        status = classify_module(
            block_effects=block_effects,
            combined_effect=combined_effect,
            observations=observations,
            concentration_ok=concentration_ok,
            path_ok=bool(path_ok),
            operational_failure=(module == "lifecycle" and lifecycle_operational_failure),
        )
        if module == "replacement" and lifecycle_operational_failure:
            status = "insufficient_evidence"
        rows.append(
            {
                "module": module,
                "status": status,
                "left_policy": left_policy,
                "right_policy": right_policy,
                "left_observations": int(left["observations"]),
                "right_observations": int(right["observations"]),
                "left_precision": left["precision"],
                "right_precision": right["precision"],
                "combined_effect": combined_effect,
                "block_effects": json.dumps(block_effects),
                "block_effect_min": min(block_effects) if block_effects else np.nan,
                "block_effect_max": max(block_effects) if block_effects else np.nan,
                "left_median_terminal_return": left["median_terminal_return"],
                "right_median_terminal_return": right["median_terminal_return"],
                "left_median_max_adverse_return": left["median_max_adverse_return"],
                "right_median_max_adverse_return": right["median_max_adverse_return"],
                "concentration_ok": concentration_ok,
                "path_ok": bool(path_ok),
            }
        )
    rows.append(
        {
            "module": "market_environment",
            "status": "insufficient_evidence",
            "left_policy": "embedded_market_gate",
            "right_policy": None,
            "left_observations": 90,
            "right_observations": 0,
            "combined_effect": np.nan,
            "block_effects": "[]",
            "diagnostic_note": "市场环境参与了形成门槛，但本实验没有冻结同日无市场门槛反事实，不能独立归因",
        }
    )
    for module in EXPECTED_NOT_TESTABLE_ROUTES:
        rows.append(
            {
                "module": module,
                "status": "not_testable",
                "left_policy": None,
                "right_policy": None,
                "left_observations": 0,
                "right_observations": 0,
                "combined_effect": np.nan,
                "block_effects": "[]",
            }
        )
    return pd.DataFrame(rows)


def _format_pct(value: Any) -> str:
    return "—" if value is None or pd.isna(value) else f"{float(value):.2%}"


def _markdown_table(frame: pd.DataFrame, columns: list[str], headers: list[str]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in frame[columns].itertuples(index=False, name=None):
        lines.append("| " + " | ".join(str(value) for value in row) + " |")
    return "\n".join(lines)


def generate_report(config: ValidationConfig) -> Path:
    output = prepare_output_root(config)
    outcomes = pd.read_parquet(output / "tables" / "outcomes_all.parquet")
    evidence = pd.concat(
        [_read_formation_outputs(output, block.id, "evidence") for block in config.blocks],
        ignore_index=True,
    )
    decisions = pd.concat(
        [_read_formation_outputs(output, block.id, "decisions") for block in config.blocks],
        ignore_index=True,
    )
    projects = pd.concat(
        [_read_formation_outputs(output, block.id, "projects") for block in config.blocks],
        ignore_index=True,
    )
    diagnostics = _module_diagnostics(outcomes, evidence, projects)
    _write_parquet(diagnostics, output / "tables" / "module_diagnostics.parquet")
    summary_rows = []
    for block_id in ("A", "B", "C", "ALL"):
        sample = outcomes if block_id == "ALL" else outcomes[outcomes["block"] == block_id]
        for policy, layer in (
            ("route_hotspot", None), ("route_earnings", None), ("route_price", None),
            ("research_union", None), ("v3_partial_candidate", None),
            ("v3_partial_candidate", "focus"), ("v3_partial_candidate", "candidate"),
            ("matched_candidate_control", None),
        ):
            metric = _policy_metrics(sample, policy, layer=layer)
            summary_rows.append({"block": block_id, "policy": policy, "layer": layer or "all", **metric})
    summaries = pd.DataFrame(summary_rows)
    _write_parquet(summaries, output / "tables" / "summary_metrics.parquet")

    candidate_20 = outcomes[
        (outcomes["policy"] == "v3_partial_candidate")
        & (outcomes["horizon"] == 20)
        & outcomes["complete_horizon"].astype(bool)
    ].copy()
    successes = candidate_20[candidate_20["target_touched"].astype(bool)].sort_values(
        ["max_adverse_return", "terminal_return"], ascending=[False, False]
    ).head(8)
    failures = candidate_20[~candidate_20["target_touched"].astype(bool)].sort_values(
        "terminal_return"
    ).head(8)
    omissions = pd.read_parquet(output / "tables" / "omission_cases.parquet")
    pairs = pd.read_parquet(output / "tables" / "replacement_pairs.parquet")

    daily = decisions.groupby(["block", "formation_date"])["layer"].agg(
        candidate_count=lambda values: int(pd.Series(values).isin(["focus", "candidate"]).sum()),
        focus_count=lambda values: int((pd.Series(values) == "focus").sum()),
    ).reset_index()
    new_count = int((projects["project_status"] == "new").sum())
    exit_count = int((projects["project_status"] == "exit").sum())
    active_days = projects.groupby("project_id")["age_sessions"].max() if not projects.empty else pd.Series(dtype=float)
    entries = (
        projects.sort_values("formation_date")
        .drop_duplicates("project_id", keep="first")
        [["project_id", "entry_date", "ts_code"]]
        .copy()
    )
    entry_outcomes = candidate_20[["formation_date", "ts_code", "target_touched"]].copy()
    entries["entry_date"] = pd.to_datetime(entries["entry_date"]).dt.normalize()
    entry_outcomes["formation_date"] = pd.to_datetime(entry_outcomes["formation_date"]).dt.normalize()
    entry_audit = entries.merge(
        entry_outcomes,
        left_on=["entry_date", "ts_code"],
        right_on=["formation_date", "ts_code"],
        how="left",
    ).set_index("project_id")
    wrong_durations = [
        float(age)
        for project_id, age in active_days.items()
        if project_id in entry_audit.index
        and not bool(entry_audit.loc[project_id, "target_touched"])
    ]
    wrong_occupancy = float(np.mean(wrong_durations)) if wrong_durations else np.nan

    status_cn = {
        "accuracy_supported": "数据支持",
        "inaccuracy_supported": "数据反对",
        "insufficient_evidence": "证据不足",
        "not_testable": "当前不可验证",
    }
    module_table = diagnostics.copy()
    module_table["结论"] = module_table["status"].map(status_cn)
    module_table["样本"] = module_table["left_observations"].fillna(0).astype(int).astype(str) + "/" + module_table["right_observations"].fillna(0).astype(int).astype(str)
    module_table["总体差"] = module_table["combined_effect"].map(_format_pct)
    module_table["三段范围"] = module_table.apply(
        lambda row: f"{_format_pct(row.get('block_effect_min'))} 至 {_format_pct(row.get('block_effect_max'))}", axis=1
    )
    all_summary = summaries[summaries["block"] == "ALL"].copy()
    all_summary["名称"] = all_summary["policy"] + "/" + all_summary["layer"]
    all_summary["命中"] = all_summary["precision"].map(_format_pct)
    all_summary["期末中位"] = all_summary["median_terminal_return"].map(_format_pct)
    all_summary["最大不利中位"] = all_summary["median_max_adverse_return"].map(_format_pct)
    block_summary = summaries[
        (summaries["block"] != "ALL")
        & (
            summaries["policy"].isin(
                ["research_union", "v3_partial_candidate", "matched_candidate_control"]
            )
        )
    ].copy()
    block_summary["层级"] = block_summary["policy"] + "/" + block_summary["layer"]
    block_summary["样本"] = block_summary["observations"].astype(int)
    block_summary["命中"] = block_summary["precision"].map(_format_pct)

    lines = [
        "# 股票分析助手 V3：轻量分层历史验证结果",
        "",
        "> 形成日：三个独立区块、每块连续 30 个交易日，共 90 个形成日。未来窗口：10/20/30 个交易日。目标：从形成日收盘出发，未来盘中触及 +20%。",
        "",
        "## 1. 结论边界",
        "",
        "本实验只验证本地数据能够按历史时点复现的部分：市场环境、板块/概念热度、盈利与经营现金流、价格成交流动性，以及十只压缩、重点五只、替换和生命周期的最小协议。公司事件正文、产业/周期供需链和困境反转仍不可验证，因此无论结果多好，都不能说完整 V3 已经被证明可靠。",
        "",
        "模块结论不是看一个总命中率：总体必须优于合法对照、三个区块至少两个同向、不能被少数股票或单一热点解释，而且途中回撤和期末结果不能反对。三段范围是区块稳健范围，不把同一股票的相邻日期误当成独立样本。",
        "",
        "## 2. 哪些部分准确、哪些不准确",
        "",
        _markdown_table(module_table, ["module", "结论", "样本", "总体差", "三段范围"], ["模块", "判定", "左/右样本", "20日命中差", "三个区块差值范围"]),
        "",
        "`数据支持` 表示当前可执行口径得到一致证据；`数据反对` 表示现有协议应优化；`证据不足` 不能解释成通过；`当前不可验证` 表示本地缺少形成该判断所需的历史事实。",
        "",
        "## 3. 关键数字如何支撑结论",
        "",
        _markdown_table(all_summary, ["名称", "observations", "命中", "期末中位", "最大不利中位"], ["层/入口", "20日样本", "盘中触及+20%", "第20日期末中位", "途中最大不利中位"]),
        "",
        "入口层的含义需要分开看：价格入口命中最高，但期末中位和途中回撤最差；热点入口命中明显高于盈利入口，路径也较深；盈利入口命中较低，但回撤相对温和。这支持‘价格发现启动、热点说明共同性、公司证据控制持续性与风险’，不支持把近期强势或业绩增长单独翻译为应该买。",
        "",
        "三个独立区块的中心窗口结果如下：",
        "",
        _markdown_table(block_summary, ["block", "层级", "样本", "命中"], ["区块", "层级", "20日样本", "盘中触及+20%"]),
        "",
        "最终候选 27.50% 的命中仍略高于同日、同市场/行业与流动性匹配对照的 24.45%，但明显低于它所来自的研究池 34.50%；且三个区块里候选相对研究池分别少约 8.99、3.67、8.22 个百分点。因此问题不是框架完全没有发现能力，而是当前公司证据硬门槛、Pareto 淘汰和容量决胜没有把研究池里的机会正确压缩出来。平均每天只留下 3.58 只也说明协议很保守，但‘少而精’并没有兑现为更高命中。",
        "",
        f"90 个形成日平均每天形成 {daily['candidate_count'].mean():.2f} 只最终候选、{daily['focus_count'].mean():.2f} 只重点候选；共记录 {new_count} 次新项目和 {exit_count} 次退出。能够形成配对审计的挑战者替换有 {len(pairs)} 次。未在入场后 20 日触及目标的项目，平均占位约 {_format_number(wrong_occupancy)} 个交易日。",
        "",
        "生命周期的过程证据本身已经否定当前最小机制：220 次新项目、212 次退出，90 个形成日里只有 3 个满 5 日以上的可评价快照。也就是说，它实际变成了高频换名单，没有把每日发现转成 1—6 周研究项目。因此生命周期判为‘数据反对’；替换虽然表面多出约 2.5 个百分点命中，但建立在这个失效状态流上，只能判为证据不足。",
        "",
        "## 4. 代表性成功与失败",
        "",
        "成功案例不是只看摸到目标，还优先展示较浅回撤和较好期末：",
        "",
        _case_table(successes),
        "",
        "失败案例按第 20 日期末表现从差到好列出，用于定位错误候选为何占位：",
        "",
        _case_table(failures),
        "",
        "## 5. 被遗漏但后来上涨的案例",
        "",
        _omission_table(omissions.head(18)),
        "",
        "这些遗漏只说明三个当前可执行入口没有及时把它们排进前 30，不等同于事后认定它们当时应该推荐。事件、周期和困境反转缺少可复现历史证据，是当前覆盖盲区之一。",
        "",
        "## 6. 后续应怎样优化",
        "",
    ]
    for row in diagnostics.itertuples(index=False):
        if row.status == "inaccuracy_supported":
            lines.append(f"- `{row.module}`：现有协议被数据反对。只针对该模块检查门槛、比较关系和失效条件；不得改目标或用未来结果调权重。")
        elif row.status == "insufficient_evidence":
            lines.append(f"- `{row.module}`：保留为未决问题。优先增加真正独立的形成期或补齐配对样本，不以当前结果定型。")
        elif row.status == "accuracy_supported":
            lines.append(f"- `{row.module}`：保留当前逻辑作为下一轮基线，但继续影子验证，不能升级为收益保证。")
        else:
            lines.append(f"- `{row.module}`：先补齐可审计历史事实和执行协议；本实验不允许用价格代理替代。")
    lines.extend(
        [
            "",
            "## 7. 数据与方法限制",
            "",
            "- 这是按业务日期与 `available_at` 重建的历史验证，不是包含成交冲击、涨停可买性、手续费和仓位的交易策略回测。",
            "- 盘中最高价触及 +20% 不等于一定可以成交；所以同时保留期末收益、最大不利路径和先回撤后命中。",
            "- 相邻每日形成样本高度相关；判定以三个独立 30 日区块为单位，不用普通独立样本显著性夸大把握。",
            "- 本实验没有修改临时框架、数据底座或正式代码；优化建议必须另行讨论确认。",
        ]
    )
    report = output / "reports" / "v3-layered-historical-validation-results.md"
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _write_json({"status": "reported", "report": str(report)}, output / "manifests" / "report_status.json")
    return report


def _format_number(value: float) -> str:
    return "—" if not np.isfinite(value) else f"{value:.1f}"


def _case_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "无足够案例。"
    show = frame[["block", "formation_date", "ts_code", "layer", "first_target_session", "max_favorable_return", "max_adverse_return", "terminal_return"]].copy()
    show["formation_date"] = pd.to_datetime(show["formation_date"]).dt.date.astype(str)
    for column in ("max_favorable_return", "max_adverse_return", "terminal_return"):
        show[column] = show[column].map(_format_pct)
    show["first_target_session"] = show["first_target_session"].map(
        lambda value: "—" if pd.isna(value) else str(int(value))
    )
    return _markdown_table(
        show,
        ["block", "formation_date", "ts_code", "layer", "first_target_session", "max_favorable_return", "max_adverse_return", "terminal_return"],
        ["区块", "形成日", "股票", "层级", "首次触及日", "最高收益", "最大不利", "第20日期末"],
    )


def _omission_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "无可审计遗漏案例。"
    show = frame[["block", "formation_date", "ts_code", "max_return_20d", "missing_evidence"]].copy()
    show["formation_date"] = pd.to_datetime(show["formation_date"]).dt.date.astype(str)
    show["max_return_20d"] = show["max_return_20d"].map(_format_pct)
    return _markdown_table(
        show,
        ["block", "formation_date", "ts_code", "max_return_20d", "missing_evidence"],
        ["区块", "形成日", "股票", "20日盘中最高", "当时缺失/未进入的证据"],
    )


def preflight(config: ValidationConfig) -> dict[str, Any]:
    output = prepare_output_root(config)
    usage = shutil.disk_usage(output)
    blocks = {
        block.id: {
            "formation_sessions": len(block_sessions(config, block)),
            "future_sessions_available": len(
                [
                    session
                    for session in available_sessions(config.warehouse_root)
                    if pd.Timestamp(block.end) < session
                ][: max(config.horizons)]
            ),
        }
        for block in config.blocks
    }
    result = {
        "output_root": str(output),
        "usb_free_bytes": usage.free,
        "usb_soft_bytes": config.usb_soft_bytes,
        "blocks": blocks,
    }
    if usage.free < config.usb_soft_bytes:
        raise RuntimeError("U盘剩余空间低于冻结软上限")
    if any(item["future_sessions_available"] < 30 for item in blocks.values()):
        raise RuntimeError("至少一个区块缺少完整30交易日未来窗口")
    _write_json(result, output / "manifests" / "preflight.json")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("preflight", "reveal", "report"):
        sub = subparsers.add_parser(name)
        sub.add_argument("--config", required=True)
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--config", required=True)
    run_parser.add_argument("--blocks", nargs="+", required=True)
    args = parser.parse_args(argv)
    config = load_config(args.config)
    if args.command == "preflight":
        print(json.dumps(preflight(config), ensure_ascii=False, indent=2))
    elif args.command == "run":
        run_blocks(config, args.blocks)
    elif args.command == "reveal":
        reveal_outcomes(config)
    elif args.command == "report":
        print(generate_report(config))
    return 0


if __name__ == "__main__":
    sys.exit(main())
