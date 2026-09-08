"""单股买入决策的材料准备与数值复算入口。

prepare 只读事实仓并生成一次研究所需的紧凑本地材料；
calculate 只对 AI 明确提出的价位方案作数值复算并保存。
两个命令都不生成投资结论，都不修改原选股、复盘与冻结历史。
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator

from stock_analyzer.analysis.buy_decision_features import (
    atr20_from_sessions,
    compute_buy_geometry,
    holding_window_end,
    normalize_price_history,
)
from stock_analyzer.config import AppConfig
from stock_analyzer.data.research_contracts import ResearchDatasetId
from stock_analyzer.storage.research_query import ResearchQuery
from stock_analyzer.storage.research_warehouse import ResearchWarehouse


BUY_DECISION_CONTEXT_VERSION = "buy-decision-context-v1"
BUY_DECISION_ANALYSIS_VERSION = "buy-decision-analysis-v1"
WINDOW_SESSION_COUNT = 130

_V1_TS_CODE_PREFIXES = (
    ("600", "SH"), ("601", "SH"), ("603", "SH"), ("605", "SH"),
    ("000", "SZ"), ("001", "SZ"), ("002", "SZ"), ("003", "SZ"),
    ("300", "SZ"), ("301", "SZ"),
)
_PLACEHOLDER_TEXTS = {
    "由本次研究写明",
    "仅为接口样例，真实使用必须引用本次事实与日期",
}
_BENCHMARK_INDEX = "000300.SH"


class BuyDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    ts_code: str = Field(min_length=9, max_length=9)
    position_status: Literal["not_bought"]
    as_of: datetime
    objective: Literal["near_term_profit_without_fixed_target"]
    horizon_sessions: int = Field(ge=1)
    horizon_is_hard_deadline: bool = False
    reference_entry_price: float | None = Field(default=None, gt=0)
    reference_entry_source: str | None = None
    assumed_entry_date: date | None = None
    max_tolerable_loss_pct: float | None = Field(default=None, gt=0)
    round_trip_cost_bps: float | None = Field(default=None, ge=0)
    related_episode_ids: list[str] = []

    @model_validator(mode="after")
    def validate_request(self) -> "BuyDecisionRequest":
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("as_of must include a timezone")
        code = self.ts_code.upper()
        prefix, exchange = code[:3], code[-2:]
        if (prefix, exchange) not in _V1_TS_CODE_PREFIXES:
            raise ValueError(
                "ts_code is outside the V1 tradable scope "
                "(SH/SZ main board and ChiNext A-shares only): "
                f"{self.ts_code}"
            )
        if (self.reference_entry_price is None) != (
            self.reference_entry_source is None
        ):
            raise ValueError(
                "reference_entry_price and reference_entry_source must be "
                "provided together"
            )
        return self


def prepare_buy_decision(
    *,
    request_path: Path,
    output_dir: Path,
    warehouse_root: Path | None = None,
    project_root: Path | None = None,
) -> dict[str, Any]:
    """只读事实仓，生成 request.json 与 context.json 到新 run 目录。"""

    request_path = Path(request_path)
    output_dir = Path(output_dir)
    raw_request = json.loads(request_path.read_text(encoding="utf-8"))
    request = BuyDecisionRequest.model_validate(raw_request)
    if output_dir.exists():
        raise ValueError(f"run directory already exists: {output_dir}")

    config = AppConfig.load()
    root = Path(project_root) if project_root is not None else config.project_root
    wh_root = (
        Path(warehouse_root) if warehouse_root is not None else config.local_warehouse_dir
    )
    warehouse = ResearchWarehouse(wh_root, read_only=True)
    query = ResearchQuery(warehouse)
    as_of = request.as_of

    calendar_raw = _read_raw_calendar(warehouse, as_of)
    dataset_partitions, gaps = _select_partitions(warehouse, as_of)
    if not dataset_partitions.get(ResearchDatasetId.EQUITY_DAILY):
        raise ValueError(
            "equity_daily partitions are required for a buy decision study "
            f"but none are available at {as_of.isoformat()}"
        )
    snapshot = query.materialize_snapshot(dataset_partitions, as_of=as_of)

    identity = _build_identity(request.ts_code, snapshot)
    sessions_visible = _visible_sessions(snapshot)
    price_context = _build_price_context(request.ts_code, snapshot, sessions_visible)
    benchmark_context = _build_benchmark_context(snapshot, sessions_visible)
    neutral = _build_neutral_observations(price_context, benchmark_context)
    announcements = _build_announcements(request.ts_code, snapshot)
    financials = _build_financials(request.ts_code, snapshot)
    minute_snapshot = _build_minute_snapshot(request.ts_code, snapshot, gaps)
    original = _build_original_recommendation(
        root, request.ts_code, request.related_episode_ids, as_of, gaps
    )
    horizon = _build_horizon(request, calendar_raw["sessions"])

    context = {
        "buy_decision_context_version": BUY_DECISION_CONTEXT_VERSION,
        "run_id": output_dir.name,
        "as_of": as_of.isoformat(),
        "request": raw_request,
        "identity": identity,
        "market_sessions": {
            "as_of_visible_sessions": [day.isoformat() for day in sessions_visible],
            "raw_calendar_sessions": calendar_raw,
        },
        "price_daily": price_context,
        "neutral_observations": neutral,
        "announcements": announcements,
        "financials": financials,
        "minute_snapshot": minute_snapshot,
        "original_recommendation": original,
        "horizon": horizon,
        "cost_and_tolerance": {
            "round_trip_cost_bps": request.round_trip_cost_bps,
            "max_tolerable_loss_pct": request.max_tolerable_loss_pct,
            "note": "未提供的字段保持未知，由用户决定是否补充，不代用户填写。",
        },
        "reference_entry": {
            "price": request.reference_entry_price,
            "source": request.reference_entry_source,
            "note": (
                None
                if request.reference_entry_price is None
                else "用户输入的参考买价，不是行情验证价格"
            ),
        },
        "input_manifest": snapshot.input_manifest,
        "gaps": gaps,
    }

    output_dir.mkdir(parents=True)
    (output_dir / "request.json").write_text(
        json.dumps(raw_request, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    context_path = output_dir / "context.json"
    context_path.write_text(
        json.dumps(context, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {
        "status": "prepared",
        "run_id": output_dir.name,
        "request_file": str(output_dir / "request.json"),
        "context_file": str(context_path),
        "gap_count": len(gaps),
    }


def calculate_buy_decision(
    *,
    run_dir: Path,
    analysis_input_path: Path,
) -> dict[str, Any]:
    """对 AI 明确提出的价位方案作数值复算并保存 analysis.json。"""

    run_dir = Path(run_dir)
    request_path = run_dir / "request.json"
    context_path = run_dir / "context.json"
    if not request_path.is_file() or not context_path.is_file():
        raise FileNotFoundError(
            f"run directory must contain request.json and context.json: {run_dir}"
        )
    request = json.loads(request_path.read_text(encoding="utf-8"))
    context = json.loads(context_path.read_text(encoding="utf-8"))
    if str(request.get("as_of")) != str(context.get("as_of")):
        raise ValueError(
            "request.json and context.json as_of disagree; a changed factual "
            "cutoff requires a new run"
        )
    analysis_input = json.loads(
        Path(analysis_input_path).read_text(encoding="utf-8")
    )
    if not isinstance(analysis_input, dict):
        raise ValueError("analysis input must be a JSON object")

    plans_raw = analysis_input.get("plans", [])
    if not isinstance(plans_raw, list):
        raise ValueError("plans must be a list")
    plans_computed = []
    seen_ids: set[str] = set()
    for plan in plans_raw:
        validated = _validate_plan(plan, seen_ids)
        geometry = compute_buy_geometry(
            entry_price=validated["entry_price"],
            upside_levels=validated["upside_levels"],
            invalidation_price=validated["invalidation_price"],
            atr=validated["atr"],
            round_trip_cost_bps=validated["round_trip_cost_bps"],
        )
        warnings: list[str] = []
        if geometry["invalidation"] is not None and not geometry["invalidation"][
            "below_entry"
        ]:
            warnings.append(
                "invalidation_price_is_not_below_entry_price"
            )
        plans_computed.append(
            {
                "plan_id": validated["plan_id"],
                "geometry": geometry,
                "warnings": warnings,
            }
        )

    holding_window = _resolve_holding_window(context)
    analysis = {
        "buy_decision_analysis_version": BUY_DECISION_ANALYSIS_VERSION,
        "run_id": str(context.get("run_id")),
        "as_of": context.get("as_of"),
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "input": analysis_input,
        "plans_computed": plans_computed,
        "holding_window": holding_window,
    }
    analysis_path = run_dir / "analysis.json"
    analysis_path.write_text(
        json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {
        "status": "calculated",
        "run_id": str(context.get("run_id")),
        "analysis_file": str(analysis_path),
        "plan_count": len(plans_computed),
    }


# ---------------------------------------------------------------------------
# prepare：分区选择与上下文构建
# ---------------------------------------------------------------------------


def _read_raw_calendar(
    warehouse: ResearchWarehouse,
    as_of: datetime,
) -> dict[str, Any]:
    """原始分区读取交易日历（不经 as_of 过滤），仅用于会话存在性推演。

    未来日历行的 available_at 是各自日期收盘后，经 as_of 快照读不到
    未来会话；此读法沿用 forward_selection 的既有先例。
    """

    manifest = warehouse.partition_manifest(ResearchDatasetId.TRADE_CALENDAR)
    if manifest.empty:
        return {
            "sessions": [],
            "coverage_start": None,
            "coverage_end": None,
            "note": "trade_calendar partitions are missing in the warehouse",
        }
    years = sorted(str(value) for value in manifest["partition_value"].astype(str))
    recent_years = [
        year
        for year in years
        if abs(int(year) - as_of.year) <= 1
    ]
    frame, _ = warehouse.read_current_partitions_with_manifest(
        ResearchDatasetId.TRADE_CALENDAR, recent_years
    )
    open_days = {
        pd.Timestamp(row["cal_date"]).date()
        for row in frame.to_dict(orient="records")
        if bool(row.get("is_open")) and pd.notna(row.get("cal_date"))
    }
    sessions = sorted(open_days)
    return {
        "sessions": [day.isoformat() for day in sessions],
        "coverage_start": sessions[0].isoformat() if sessions else None,
        "coverage_end": sessions[-1].isoformat() if sessions else None,
        "note": (
            "raw calendar partition read without as_of filtering; used only "
            "for session existence, not as a price fact"
        ),
    }


def _select_partitions(
    warehouse: ResearchWarehouse,
    as_of: datetime,
) -> tuple[dict[ResearchDatasetId, list[str]], list[dict[str, Any]]]:
    """按数据集挑选现有分区；可选数据集缺失记入 gaps，不拖垮其他材料。"""

    gaps: list[dict[str, Any]] = []

    def existing(dataset: ResearchDatasetId) -> list[str]:
        manifest = warehouse.partition_manifest(dataset)
        if manifest.empty:
            return []
        return sorted(manifest["partition_value"].astype(str))

    def latest_at_or_before(values: list[str], upper: date) -> str | None:
        eligible = [value for value in values if value <= upper.isoformat()]
        return eligible[-1] if eligible else None

    selected: dict[ResearchDatasetId, list[str]] = {}

    calendar_years = [
        year
        for year in existing(ResearchDatasetId.TRADE_CALENDAR)
        if abs(int(year) - as_of.year) <= 1
    ]
    if calendar_years:
        selected[ResearchDatasetId.TRADE_CALENDAR] = calendar_years
    else:
        gaps.append(
            {
                "dataset": "trade_calendar",
                "gap": "calendar_partitions_missing",
                "detail": "as_of 前后年度的交易日历分区缺失",
            }
        )

    equity_dates = existing(ResearchDatasetId.EQUITY_DAILY)
    candidate_sessions = [
        value
        for value in equity_dates
        if date.fromisoformat(value) <= as_of.date()
    ][-WINDOW_SESSION_COUNT:]
    selected[ResearchDatasetId.EQUITY_DAILY] = candidate_sessions
    factor_dates = existing(ResearchDatasetId.ADJ_FACTOR)
    selected[ResearchDatasetId.ADJ_FACTOR] = [
        value for value in candidate_sessions if value in set(factor_dates)
    ]
    if not candidate_sessions:
        gaps.append(
            {
                "dataset": "equity_daily",
                "gap": "no_partitions_at_or_before_as_of",
                "detail": f"as_of={as_of.isoformat()}",
            }
        )

    index_dates = existing(ResearchDatasetId.INDEX_DAILY)
    index_window = [value for value in candidate_sessions if value in set(index_dates)]
    if index_window:
        selected[ResearchDatasetId.INDEX_DAILY] = index_window[-WINDOW_SESSION_COUNT:]
    else:
        gaps.append(
            {
                "dataset": "index_daily",
                "gap": "benchmark_partitions_missing",
                "detail": "市场比较基准在窗口内没有分区",
            }
        )

    announcement_months = existing(ResearchDatasetId.ANNOUNCEMENT)
    months = {
        (as_of.date() - timedelta(days=30 * offset)).strftime("%Y-%m")
        for offset in range(3)
    }
    wanted = sorted(value for value in announcement_months if value in months)
    if wanted:
        selected[ResearchDatasetId.ANNOUNCEMENT] = wanted
    else:
        gaps.append(
            {
                "dataset": "announcement",
                "gap": "announcement_partitions_missing",
                "detail": f"近三个月分区不存在：{sorted(months)}",
            }
        )

    basic_latest = latest_at_or_before(existing(ResearchDatasetId.DAILY_BASIC), as_of.date())
    if basic_latest is not None:
        selected[ResearchDatasetId.DAILY_BASIC] = [basic_latest]
    else:
        gaps.append(
            {
                "dataset": "daily_basic",
                "gap": "daily_basic_partitions_missing",
                "detail": "截至 as_of 无每日指标分区",
            }
        )

    for dataset, label in (
        (ResearchDatasetId.INCOME_STATEMENT, "income_statement"),
        (ResearchDatasetId.FINANCIAL_INDICATOR, "financial_indicator"),
    ):
        periods = [
            value
            for value in existing(dataset)
            if date.fromisoformat(value) <= as_of.date()
        ]
        if periods:
            selected[dataset] = [periods[-1]]
        else:
            gaps.append(
                {
                    "dataset": label,
                    "gap": "report_period_partitions_missing",
                    "detail": "截至 as_of 无已披露报告期分区",
                }
            )

    master_values = existing(ResearchDatasetId.SECURITY_MASTER)
    if master_values:
        selected[ResearchDatasetId.SECURITY_MASTER] = [master_values[-1]]
    else:
        gaps.append(
            {
                "dataset": "security_master",
                "gap": "security_master_partitions_missing",
                "detail": "证券主档分区缺失",
            }
        )

    limit_values = set(existing(ResearchDatasetId.STOCK_LIMIT))
    limit_window = [value for value in candidate_sessions if value in limit_values]
    if limit_window:
        selected[ResearchDatasetId.STOCK_LIMIT] = [limit_window[-1]]

    suspension_values = set(existing(ResearchDatasetId.SUSPENSION))
    suspension_window = [
        value for value in candidate_sessions if value in suspension_values
    ]
    if suspension_window:
        selected[ResearchDatasetId.SUSPENSION] = [suspension_window[-1]]

    as_of_partition = as_of.date().isoformat()
    if as_of_partition in set(existing(ResearchDatasetId.MINUTE_BAR)):
        selected[ResearchDatasetId.MINUTE_BAR] = [as_of_partition]

    return selected, gaps


def _visible_sessions(snapshot: Any) -> list[date]:
    frame = _frame_or_empty(snapshot, ResearchDatasetId.TRADE_CALENDAR)
    if frame.empty:
        return []
    days = {
        pd.Timestamp(row["cal_date"]).date()
        for row in frame.to_dict(orient="records")
        if bool(row.get("is_open")) and pd.notna(row.get("cal_date"))
    }
    return sorted(days)


def _build_identity(ts_code: str, snapshot: Any) -> dict[str, Any]:
    frame = _frame_or_empty(snapshot, ResearchDatasetId.SECURITY_MASTER)
    row = None
    if not frame.empty and "ts_code" in frame.columns:
        matched = frame.loc[frame["ts_code"].astype(str) == ts_code]
        if not matched.empty:
            row = matched.sort_values("valid_from").iloc[-1]
    name = str(row.get("name")) if row is not None else None
    scope_flags: list[str] = []
    in_scope = True
    if row is None:
        scope_flags.append("security_master_row_missing")
    else:
        if name and ("ST" in name.upper()):
            in_scope = False
            scope_flags.append("st_or_risk_warning_name")
    return {
        "ts_code": ts_code,
        "name": name,
        "market": str(row.get("market")) if row is not None else None,
        "industry": str(row.get("industry")) if row is not None else None,
        "in_v1_scope": in_scope,
        "scope_notes": scope_flags,
    }


def _stock_rows(frame: pd.DataFrame, ts_code: str, column: str = "ts_code") -> pd.DataFrame:
    if frame.empty or column not in frame.columns:
        return frame.iloc[0:0]
    return frame.loc[frame[column].astype(str) == ts_code]


def _frame_or_empty(snapshot: Any, dataset: ResearchDatasetId) -> pd.DataFrame:
    """快照未包含的可选数据集返回空帧，由调用方记缺口。"""

    try:
        return snapshot.frame(dataset)
    except KeyError:
        return pd.DataFrame()


def _build_price_context(
    ts_code: str,
    snapshot: Any,
    sessions_visible: Sequence[date],
) -> dict[str, Any]:
    equity = _stock_rows(snapshot.frame(ResearchDatasetId.EQUITY_DAILY), ts_code)
    factors = _stock_rows(snapshot.frame(ResearchDatasetId.ADJ_FACTOR), ts_code)
    if equity.empty or factors.empty:
        return {
            "price_basis": "raw_times_day_factor_div_latest_factor",
            "normalization_factor": None,
            "normalization_date": None,
            "sessions": [],
            "data_cutoff_date": None,
            "limitations": ["price_history_unavailable_for_stock"],
        }
    equity = equity.copy()
    equity["trade_date"] = pd.to_datetime(equity["trade_date"]).dt.date
    factors_by_date = {
        pd.Timestamp(row["trade_date"]).date(): float(row["adj_factor"])
        for row in factors.to_dict(orient="records")
        if pd.notna(row.get("adj_factor"))
    }
    equity = equity.sort_values("trade_date")
    rows: list[dict[str, Any]] = []
    for item in equity.to_dict(orient="records"):
        day = item["trade_date"]
        factor = factors_by_date.get(day)
        if factor is None:
            continue
        rows.append(
            {
                "date": day,
                "open": item.get("open"),
                "high": item.get("high"),
                "low": item.get("low"),
                "close": item.get("close"),
                "amount": item.get("amount"),
                "factor": factor,
            }
        )
    rows = rows[-WINDOW_SESSION_COUNT:]
    normalization_factor = rows[-1]["factor"] if rows else None
    normalization_date = rows[-1]["date"] if rows else None
    normalized = normalize_price_history(rows, normalization_factor=normalization_factor)
    limitations: list[str] = []
    if len(rows) < 61:
        limitations.append("price_history_shorter_than_60_sessions")
    if len(rows) < 21:
        limitations.append("price_history_shorter_than_21_sessions")
    return {
        "price_basis": "raw_times_day_factor_div_latest_factor",
        "normalization_factor": normalization_factor,
        "normalization_date": (
            normalization_date.isoformat() if normalization_date else None
        ),
        "sessions": [
            {
                "date": item["date"].isoformat(),
                "open": item["open"],
                "high": item["high"],
                "low": item["low"],
                "close": item["close"],
                "amount": item["amount"],
                "raw_close": item["raw_close"],
                "factor": item["factor"],
            }
            for item in normalized
        ],
        "data_cutoff_date": (
            rows[-1]["date"].isoformat() if rows else None
        ),
        "requested_window_sessions": WINDOW_SESSION_COUNT,
        "limitations": limitations,
    }


def _build_benchmark_context(
    snapshot: Any,
    sessions_visible: Sequence[date],
) -> dict[str, Any]:
    frame = _frame_or_empty(snapshot, ResearchDatasetId.INDEX_DAILY)
    if frame.empty or "index_code" not in frame.columns:
        return {"code": _BENCHMARK_INDEX, "sessions": []}
    frame = frame.loc[frame["index_code"].astype(str) == _BENCHMARK_INDEX]
    frame = frame.copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.date
    frame = frame.sort_values("trade_date")
    rows = [
        {
            "date": item["trade_date"].isoformat(),
            "close": item.get("close"),
        }
        for item in frame.to_dict(orient="records")
        if item.get("close") is not None
    ]
    return {"code": _BENCHMARK_INDEX, "sessions": rows[-WINDOW_SESSION_COUNT:]}


def _close_return(rows: Sequence[Mapping[str, Any]], lookback: int) -> float | None:
    if len(rows) <= lookback:
        return None
    start = rows[-1 - lookback].get("close")
    end = rows[-1].get("close")
    if start in (None, 0) or end is None:
        return None
    return float(end) / float(start) - 1.0


def _build_neutral_observations(
    price_context: Mapping[str, Any],
    benchmark_context: Mapping[str, Any],
) -> dict[str, Any]:
    rows = price_context.get("sessions", [])
    observations: dict[str, Any] = {
        "last_close": rows[-1]["close"] if rows else None,
        "last_close_date": rows[-1]["date"] if rows else None,
        "return_1d": _close_return(rows, 1),
        "return_5d": _close_return(rows, 5),
        "return_20d": _close_return(rows, 20),
    }
    if len(rows) >= 61:
        window = rows[-61:]
        highs = [row["high"] for row in window if row.get("high") is not None]
        lows = [row["low"] for row in window if row.get("low") is not None]
        closes = [row["close"] for row in window if row.get("close") is not None]
        if len(highs) == 61 and len(lows) == 61 and len(closes) == 61 and rows[-1]["close"]:
            high_60, low_60 = max(highs), min(lows)
            observations["high_60d"] = high_60
            observations["low_60d"] = low_60
            observations["close_location_60d"] = (
                (rows[-1]["close"] - low_60) / (high_60 - low_60)
                if high_60 > low_60
                else None
            )
        else:
            observations["high_60d"] = None
            observations["low_60d"] = None
            observations["close_location_60d"] = None
    else:
        observations["high_60d"] = None
        observations["low_60d"] = None
        observations["close_location_60d"] = None
    prior_window = rows[-61:-1]
    if len(prior_window) == 60 and all(
        row.get("high") is not None and row.get("close") is not None
        for row in prior_window
    ):
        prior_high = max(row["high"] for row in prior_window)
        prior_close_high = max(row["close"] for row in prior_window)
        observations["prior60_high"] = prior_high
        observations["prior60_close_high"] = prior_close_high
        observations["prior60_high_date"] = next(
            row["date"] for row in prior_window if row["high"] == prior_high
        )
        observations["prior60_close_high_date"] = next(
            row["date"] for row in prior_window if row["close"] == prior_close_high
        )
    else:
        observations["prior60_high"] = None
        observations["prior60_close_high"] = None
        observations["prior60_high_date"] = None
        observations["prior60_close_high_date"] = None
    atr_inputs = [
        {
            "date": row["date"],
            "high": row["high"],
            "low": row["low"],
            "close": row["close"],
        }
        for row in rows
        if row.get("high") is not None
        and row.get("low") is not None
        and row.get("close") is not None
    ]
    observations["atr20"] = atr20_from_sessions(atr_inputs)
    observations["atr20_note"] = (
        "最近20个会话真实波幅的简单平均，按归一价格口径计算；"
        "只衡量普通波动宽度，不是方向、概率或亏损上限"
    )
    benchmark_rows = benchmark_context.get("sessions", [])
    observations["benchmark"] = {
        "code": benchmark_context.get("code"),
        "return_1d": _close_return(benchmark_rows, 1),
        "return_5d": _close_return(benchmark_rows, 5),
        "return_20d": _close_return(benchmark_rows, 20),
    }
    stock_5d = observations["return_5d"]
    benchmark_5d = observations["benchmark"]["return_5d"]
    observations["excess_vs_benchmark_5d"] = (
        None if stock_5d is None or benchmark_5d is None else stock_5d - benchmark_5d
    )
    limitations = list(price_context.get("limitations", []))
    if not benchmark_rows:
        limitations.append("benchmark_history_unavailable")
    if observations["atr20"] is None:
        limitations.append("atr20_unavailable")
    observations["limitations"] = limitations
    return observations


def _build_announcements(ts_code: str, snapshot: Any) -> dict[str, Any]:
    frame = _frame_or_empty(snapshot, ResearchDatasetId.ANNOUNCEMENT)
    rows = _stock_rows(frame, ts_code)
    if "announcement_time" in rows.columns and not rows.empty:
        rows = rows.sort_values("announcement_time")
    return {
        "rows": [
            {
                "announcement_id": str(item.get("announcement_id")),
                "announcement_time": _iso_or_none(item.get("announcement_time")),
                "title": item.get("title"),
                "url": item.get("url"),
                "available_at": _iso_or_none(item.get("available_at")),
            }
            for item in rows.to_dict(orient="records")
        ][-40:],
        "note": "公告元数据；正文未入库，重要条款需按披露链读取原文。",
    }


def _build_financials(ts_code: str, snapshot: Any) -> dict[str, Any] | None:
    income = _stock_rows(
        _frame_or_empty(snapshot, ResearchDatasetId.INCOME_STATEMENT), ts_code
    )
    indicator = _stock_rows(
        _frame_or_empty(snapshot, ResearchDatasetId.FINANCIAL_INDICATOR), ts_code
    )

    def _latest(frame: pd.DataFrame) -> dict[str, Any] | None:
        if frame.empty:
            return None
        ordered = frame.sort_values("report_period")
        return ordered.iloc[-1].to_dict()

    income_row = _latest(income)
    indicator_row = _latest(indicator)
    if income_row is None and indicator_row is None:
        return None
    return {
        "income_statement": _jsonify(income_row),
        "financial_indicator": _jsonify(indicator_row),
        "note": "最新报告期一行；不构成对未来利润或短期股价的推断。",
    }


def _build_minute_snapshot(
    ts_code: str,
    snapshot: Any,
    gaps: list[dict[str, Any]],
) -> dict[str, Any]:
    frame = _frame_or_empty(snapshot, ResearchDatasetId.MINUTE_BAR)
    rows = _stock_rows(frame, ts_code, column="instrument_code")
    if rows.empty:
        gaps.append(
            {
                "dataset": "minute_bar",
                "gap": "minute_snapshot_not_available_at_as_of",
                "detail": "as_of 时点没有可用的该股盘中快照行",
            }
        )
        return {
            "rows": [],
            "available": False,
            "note": "盘中快照缺失时不能声称可按现价立即参与。",
        }
    ordered = rows.sort_values("minute")
    return {
        "rows": [
            {
                "minute": _iso_or_none(item.get("minute")),
                "open": item.get("open"),
                "high": item.get("high"),
                "low": item.get("low"),
                "close": item.get("close"),
                "volume": item.get("volume"),
                "available_at": _iso_or_none(item.get("available_at")),
            }
            for item in ordered.to_dict(orient="records")
        ],
        "available": True,
        "note": "盘中快照是独立时点样本，不能替代完整日线。",
    }


def _build_original_recommendation(
    project_root: Path,
    ts_code: str,
    related_episode_ids: Sequence[str],
    as_of: datetime,
    gaps: list[dict[str, Any]],
) -> dict[str, Any]:
    monitor_dir = project_root / "local_archive" / "forward_monitor"
    registry_path = monitor_dir / "registered-episodes.json"
    episodes: list[dict[str, Any]] = []
    if registry_path.is_file():
        document = json.loads(registry_path.read_text(encoding="utf-8"))
        for item in document.get("episodes", []):
            if str(item.get("ts_code")) != ts_code:
                continue
            if related_episode_ids and str(item.get("episode_id")) not in set(
                related_episode_ids
            ):
                continue
            episodes.append(dict(item))
    else:
        gaps.append(
            {
                "dataset": "forward_monitor_registry",
                "gap": "registered_episodes_file_missing",
                "detail": str(registry_path),
            }
        )
    latest_observation = None
    snapshots = sorted(monitor_dir.glob("snapshot-*.json"))
    for snapshot_path in reversed(snapshots):
        try:
            document = json.loads(snapshot_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        analysis_date_raw = str(document.get("analysis_date", ""))
        try:
            analysis_date = date.fromisoformat(analysis_date_raw)
        except ValueError:
            continue
        if analysis_date > as_of.date():
            continue
        for item in document.get("episodes", []):
            if str(item.get("ts_code")) != ts_code:
                continue
            episode_id = item.get("episode_id")
            if related_episode_ids and str(episode_id) not in set(
                related_episode_ids
            ):
                continue
            latest_observation = {
                "analysis_date": analysis_date_raw,
                "day_number": item.get("day_number"),
                "source_snapshot": snapshot_path.name,
            }
            break
        if latest_observation is not None:
            break
    return {
        "background_only": True,
        "note": (
            "原推荐只作背景：其目标价、20%标签与观察期不是本次新买入的收益"
            "门槛或期限；新买入必须从原始事实重新评估。"
        ),
        "episodes": episodes,
        "latest_observation": latest_observation,
    }


def _build_horizon(
    request: BuyDecisionRequest,
    calendar_sessions: Sequence[str],
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "horizon_sessions": request.horizon_sessions,
        "horizon_is_hard_deadline": request.horizon_is_hard_deadline,
        "assumed_entry_date": (
            request.assumed_entry_date.isoformat()
            if request.assumed_entry_date
            else None
        ),
        "window_end_date": None,
        "window_end_note": None,
    }
    if request.assumed_entry_date is None:
        result["window_end_note"] = (
            "尚未确定假定买入日，观察窗口只能条件化说明，不虚构确定结束日期。"
        )
        return result
    sessions = [
        date.fromisoformat(value) for value in calendar_sessions
    ]
    try:
        window_end = holding_window_end(
            entry_session=request.assumed_entry_date,
            horizon_sessions=request.horizon_sessions,
            trading_sessions=sessions,
        )
    except ValueError as error:
        result["window_end_note"] = f"trading calendar error: {error}"
        return result
    result["window_end_date"] = window_end.isoformat()
    result["window_end_note"] = (
        "买入交易日计为第一天；第十天是重新判断的时间参照，不是强制卖出日期。"
    )
    return result


# ---------------------------------------------------------------------------
# calculate：方案校验与数值复算
# ---------------------------------------------------------------------------


def _validate_plan(plan: Any, seen_ids: set[str]) -> dict[str, Any]:
    if not isinstance(plan, dict):
        raise ValueError("each plan must be a JSON object")
    plan_id = str(plan.get("plan_id", "")).strip()
    if not plan_id:
        raise ValueError("plan_id must be a non-empty string")
    if plan_id in seen_ids:
        raise ValueError(f"duplicate plan_id: {plan_id}")
    seen_ids.add(plan_id)
    entry_price = plan.get("entry_price")
    _require_number(entry_price, f"plans[{plan_id}].entry_price", positive=True)
    levels_raw = plan.get("upside_levels")
    if levels_raw is None:
        levels_raw = {}
    if not isinstance(levels_raw, dict):
        raise ValueError(f"plans[{plan_id}].upside_levels must be an object")
    levels: dict[str, float] = {}
    for level_id, level_price in levels_raw.items():
        _require_number(
            level_price, f"plans[{plan_id}].upside_levels[{level_id}]", positive=True
        )
        levels[str(level_id)] = float(level_price)
    invalidation = plan.get("invalidation_price")
    if invalidation is not None:
        _require_number(
            invalidation, f"plans[{plan_id}].invalidation_price", positive=True
        )
    atr = plan.get("atr")
    if atr is not None:
        _require_number(atr, f"plans[{plan_id}].atr", positive=True)
    cost = plan.get("round_trip_cost_bps")
    if cost is not None:
        _require_number(
            cost, f"plans[{plan_id}].round_trip_cost_bps", positive=False
        )
        if float(cost) < 0:
            raise ValueError(
                f"plans[{plan_id}].round_trip_cost_bps must be non-negative"
            )
    for field in (
        "level_basis",
        "signal_known_when",
        "entry_window",
        "entry_expiry",
        "gap_or_no_fill_action",
        "invalidation_observation",
    ):
        text = plan.get(field)
        if not isinstance(text, str) or not text.strip():
            raise ValueError(
                f"plans[{plan_id}].{field} must explain the condition in "
                "words; an executable plan cannot omit it"
            )
        if text.strip() in _PLACEHOLDER_TEXTS:
            raise ValueError(
                f"plans[{plan_id}].{field} still contains placeholder text; "
                "real plans must state the actual condition"
            )
    return {
        "plan_id": plan_id,
        "entry_price": float(entry_price),
        "upside_levels": levels,
        "invalidation_price": None if invalidation is None else float(invalidation),
        "atr": None if atr is None else float(atr),
        "round_trip_cost_bps": None if cost is None else float(cost),
    }


def _resolve_holding_window(context: Mapping[str, Any]) -> dict[str, Any]:
    horizon = context.get("horizon") or {}
    raw_calendar = (context.get("market_sessions") or {}).get(
        "raw_calendar_sessions"
    ) or {}
    sessions = [
        date.fromisoformat(value)
        for value in raw_calendar.get("sessions", [])
    ]
    assumed = horizon.get("assumed_entry_date")
    result: dict[str, Any] = {
        "assumed_entry_date": assumed,
        "horizon_sessions": horizon.get("horizon_sessions"),
        "horizon_is_hard_deadline": horizon.get("horizon_is_hard_deadline"),
        "window_end_date": None,
        "error": None,
    }
    if assumed is None:
        result["error"] = "assumed_entry_date_not_provided"
        return result
    try:
        result["window_end_date"] = holding_window_end(
            entry_session=date.fromisoformat(str(assumed)),
            horizon_sessions=int(horizon.get("horizon_sessions") or 0),
            trading_sessions=sessions,
        ).isoformat()
    except ValueError as error:
        result["error"] = str(error)
    return result


# ---------------------------------------------------------------------------
# 共用小工具
# ---------------------------------------------------------------------------


def _require_number(value: Any, label: str, *, positive: bool) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a number")
    number = float(value)
    if not math.isfinite(number) or (positive and number <= 0):
        condition = "a finite positive number" if positive else "a finite number"
        raise ValueError(f"{label} must be {condition}")


def _iso_or_none(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    try:
        return pd.Timestamp(value).isoformat()
    except (ValueError, TypeError):
        return str(value)


def _jsonify(row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        key: (
            value.isoformat()
            if isinstance(value, (datetime, date, pd.Timestamp))
            else _json_value(value)
        )
        for key, value in row.items()
    }


def _json_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, pd.Timestamp, date)):
        return pd.Timestamp(value).isoformat()
    if isinstance(value, float) and math.isnan(value):
        return None
    return str(value)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m stock_analyzer.ops.buy_decision",
        description="单股买入决策：prepare 只读备料，calculate 数值复算",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare_parser = subparsers.add_parser(
        "prepare", help="只读事实仓并生成 request.json / context.json"
    )
    prepare_parser.add_argument("--request", required=True)
    prepare_parser.add_argument("--output-dir", required=True)
    prepare_parser.add_argument("--warehouse-root", default=None)
    prepare_parser.add_argument("--project-root", default=None)
    calculate_parser = subparsers.add_parser(
        "calculate", help="对明确价位方案作数值复算并保存 analysis.json"
    )
    calculate_parser.add_argument("--run-dir", required=True)
    calculate_parser.add_argument("--analysis-input", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            summary = prepare_buy_decision(
                request_path=Path(args.request),
                output_dir=Path(args.output_dir),
                warehouse_root=(
                    Path(args.warehouse_root) if args.warehouse_root else None
                ),
                project_root=Path(args.project_root) if args.project_root else None,
            )
        else:
            summary = calculate_buy_decision(
                run_dir=Path(args.run_dir),
                analysis_input_path=Path(args.analysis_input),
            )
    except (ValueError, FileNotFoundError, PermissionError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
