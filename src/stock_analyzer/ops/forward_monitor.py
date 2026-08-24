from __future__ import annotations

import argparse
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator

from stock_analyzer.ops.forward_selection import MarketPropagationModeV4


REGISTER_VERSION = "registered-forward-monitor-episodes-v1"
TRACE_VERSION = "daily-research-trace-v4"
SNAPSHOT_VERSION = "forward-monitor-snapshot-v1"
CHECKPOINTS = {1: "D1", 3: "D3", 5: "D5", 10: "D10", 20: "D20", 25: "D25", 30: "D30"}
POSITIVE_SCENARIOS = {"initial_activation", "confirmed_breakout", "trend_continuation", "reversal_attempt"}
NEGATIVE_SCENARIOS = {"failed_breakout", "single_day_impulse", "range_cross_noise"}
OVERHEAT_SCENARIOS = {"single_day_impulse", "trend_exhaustion", "failed_breakout"}


@dataclass(frozen=True)
class RegisterSummary:
    status: str
    registry_file: str
    selected_registered: int
    comparators_registered: int


@dataclass(frozen=True)
class PrepareSummary:
    status: str
    analysis_date: str
    snapshot_file: str
    open_episode_count: int
    distinct_stock_count: int
    attention_stock_count: int
    selected_count: int
    comparator_count: int
    primary_count: int
    passive_tail_count: int
    closed_count: int


class MarketOverviewV1(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    market_propagation_mode: MarketPropagationModeV4
    market_risk_overlays: list[str]
    what_changed: str = Field(min_length=1)
    implication_for_monitored_stocks: str = Field(min_length=1)


class MonitorPoolSummaryV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    open_episode_count: int = Field(ge=0)
    distinct_stock_count: int = Field(ge=0)
    selected_count: int = Field(ge=0)
    comparator_count: int = Field(ge=0)
    primary_count: int = Field(ge=0)
    passive_tail_count: int = Field(ge=0)
    attention_stock_count: int = Field(ge=0)
    routine_stock_count: int = Field(ge=0)


class ForwardMonitorAlertV1(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    ts_code: str = Field(min_length=9)
    name: str = Field(min_length=1)
    episode_ids: list[str] = Field(min_length=1)
    role: Literal["selected", "comparator"]
    day_numbers: list[int] = Field(min_length=1)
    original_engine_types: list[str]
    alert_type: Literal[
        "new_event", "first_reaction", "strengthening", "actionable_watch",
        "overheated", "invalidated", "target_hit", "late_activation",
        "checkpoint", "data_problem",
    ]
    monitor_state: Literal[
        "pending_confirmation", "routine", "strengthening", "actionable_watch",
        "overheated", "invalidated", "target_hit", "passive_tail",
    ]
    market_change: str = Field(min_length=1)
    sector_change: str = Field(min_length=1)
    stock_change: str = Field(min_length=1)
    company_change: str = Field(min_length=1)
    outlook_1_3d: Literal[
        "event_pending", "strengthening", "continuation_possible", "range_or_wait",
        "weakening", "overheated", "invalidated",
    ]
    confirmation_condition: str = Field(min_length=1)
    invalidation_condition: str = Field(min_length=1)
    why_reported: str = Field(min_length=1)


class DailyForwardMonitorReportV1(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    report_version: Literal["daily-forward-monitor-report-v1"]
    analysis_date: date
    as_of: datetime
    market_overview: MarketOverviewV1
    pool_summary: MonitorPoolSummaryV1
    alerts: list[ForwardMonitorAlertV1] = Field(max_length=8)
    unreported_attention_count: int = Field(ge=0)
    routine_summary: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_report(self) -> "DailyForwardMonitorReportV1":
        codes = [alert.ts_code for alert in self.alerts]
        if len(codes) != len(set(codes)):
            raise ValueError("the same stock may appear only once")
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("as_of must include a timezone")
        if self.analysis_date > self.as_of.date():
            raise ValueError("report contains a future analysis date")
        return self


@dataclass(frozen=True)
class RecordSummary:
    status: str
    analysis_date: str
    json_file: str
    markdown_file: str
    alert_count: int
    unreported_attention_count: int


def register_episodes(
    *,
    trace_file: Path,
    label: str,
    project_root: Path,
) -> RegisterSummary:
    trace_path = Path(trace_file)
    payload = json.loads(trace_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("trace_version") != TRACE_VERSION:
        raise ValueError("register requires daily-research-trace-v4")
    clean_label = str(label).strip()
    if not clean_label:
        raise ValueError("label is required")

    registry_path = (
        Path(project_root)
        / "local_archive"
        / "forward_monitor"
        / "registered-episodes.json"
    )
    document = _read_registry(registry_path)
    existing = {
        str(episode["episode_id"]): episode
        for episode in document["episodes"]
    }
    additions = _trace_episodes(
        payload,
        label=clean_label,
        source_type="registered_replay",
    )
    selected_registered = 0
    comparators_registered = 0
    for episode in additions:
        episode_id = str(episode["episode_id"])
        if episode_id in existing:
            continue
        existing[episode_id] = episode
        if episode["role"] == "selected":
            selected_registered += 1
        else:
            comparators_registered += 1
    output = {
        "registry_version": REGISTER_VERSION,
        "episodes": [existing[key] for key in sorted(existing)],
    }
    _atomic_write_json(registry_path, output)
    return RegisterSummary(
        status="registered",
        registry_file=str(registry_path),
        selected_registered=selected_registered,
        comparators_registered=comparators_registered,
    )


def prepare_forward_monitor(
    *,
    analysis_date: date,
    as_of: datetime,
    project_root: Path,
) -> PrepareSummary:
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must include a timezone")
    if analysis_date > as_of.date():
        raise ValueError("analysis_date cannot be after as_of")
    if analysis_date == as_of.date() and as_of.hour < 15:
        raise ValueError("analysis_date has not closed at as_of")

    root = Path(project_root)
    monitor_dir = root / "local_archive" / "forward_monitor"
    sessions = _trading_sessions(root, as_of)
    if analysis_date not in sessions:
        raise ValueError("analysis_date is not an available open trading day")

    episodes_by_id: dict[str, dict[str, Any]] = {}
    registered_path = monitor_dir / "registered-episodes.json"
    if registered_path.is_file():
        episodes_by_id.update(
            {
                str(item["episode_id"]): dict(item)
                for item in _read_registry(registered_path)["episodes"]
            }
        )
    formal_dir = root / "local_archive" / "forward_selection"
    for trace_path in sorted(formal_dir.glob("research-trace-*.json")):
        try:
            trace = json.loads(trace_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(trace, dict) or trace.get("trace_version") != TRACE_VERSION:
            continue
        for episode in _trace_episodes(trace, label="formal", source_type="formal"):
            episodes_by_id.setdefault(str(episode["episode_id"]), episode)

    previous = _previous_snapshot(monitor_dir, analysis_date)
    previous_by_id = {
        str(item.get("episode_id")): item
        for item in (previous or {}).get("episodes", [])
    }
    previous_monitor_states = _previous_monitor_states(
        monitor_dir,
        analysis_date,
        previous,
    )
    price_by_code = {
        str(row.get("ts_code")): row
        for row in _derived_rows(
            root,
            "price_analysis_context",
            analysis_date,
            "price-analysis-context-v2",
            as_of,
        )
    }
    market_rows = _derived_rows(
        root,
        "market_context",
        analysis_date,
        "market-context-v3",
        as_of,
    )
    sector_by_code = {
        str(row.get("group_code")): row
        for row in _derived_rows(
            root,
            "sector_hotspot",
            analysis_date,
            "sector-hotspot-v3",
            as_of,
        )
    }
    announcement_rows = _fact_rows(root, "announcement", as_of)
    industry_rows = _fact_rows(root, "industry_member", as_of)

    episode_windows: dict[
        str,
        tuple[dict[str, Any], datetime | None, int, str, list[date]],
    ] = {}
    all_path_days: set[date] = set()
    for episode_id in sorted(episodes_by_id):
        base = episodes_by_id[episode_id]
        source_as_of = _as_datetime(base.get("source_as_of"))
        if source_as_of is not None and source_as_of > as_of:
            continue
        action_date = date.fromisoformat(str(base["action_date"]))
        elapsed = [day for day in sessions if action_date <= day <= analysis_date]
        if not elapsed:
            continue
        day_number = len(elapsed)
        if day_number > 31:
            continue
        phase = (
            "primary"
            if day_number <= 20
            else "passive_tail"
            if day_number <= 30
            else "closed"
        )
        path_days = elapsed[: min(day_number, 30)]
        episode_windows[episode_id] = (
            base,
            source_as_of,
            day_number,
            phase,
            path_days,
        )
        all_path_days.update(path_days)

    price_path_cache = _daily_price_cache(
        root,
        sorted(all_path_days),
        as_of,
    )
    observations: list[dict[str, Any]] = []
    for episode_id in sorted(episode_windows):
        base, source_as_of, day_number, phase, path_days = episode_windows[
            episode_id
        ]
        group_code = base.get("original_group_code") or _formation_industry(
            industry_rows,
            str(base["ts_code"]),
            date.fromisoformat(str(base["formation_date"])),
            source_as_of,
        )
        observation = _episode_observation(
            price_path_cache=price_path_cache,
            base=base,
            analysis_date=analysis_date,
            as_of=as_of,
            day_number=day_number,
            phase=phase,
            path_days=path_days,
            price_row=(price_by_code.get(str(base["ts_code"])) if phase != "closed" else None),
            sector_row=(sector_by_code.get(str(group_code)) if group_code else None),
            group_code=group_code,
            announcements=announcement_rows,
            previous_episode=previous_by_id.get(episode_id),
            previous_as_of=(previous or {}).get("as_of"),
            previous_monitor_state=previous_monitor_states.get(episode_id),
            market_context_available=bool(market_rows),
        )
        observations.append(observation)

    attention_stocks = _aggregate_attention(observations)
    open_episodes = [item for item in observations if item["monitor_phase"] != "closed"]
    summary_payload = {
        "open_episode_count": len(open_episodes),
        "distinct_stock_count": len({item["ts_code"] for item in open_episodes}),
        "attention_stock_count": len(attention_stocks),
        "selected_count": sum(item["role"] == "selected" for item in open_episodes),
        "comparator_count": sum(item["role"] == "comparator" for item in open_episodes),
        "primary_count": sum(item["monitor_phase"] == "primary" for item in observations),
        "passive_tail_count": sum(item["monitor_phase"] == "passive_tail" for item in observations),
        "closed_count": sum(item["monitor_phase"] == "closed" for item in observations),
    }
    snapshot_path = monitor_dir / f"snapshot-{analysis_date.isoformat()}.json"
    _atomic_write_json(
        snapshot_path,
        {
            "snapshot_version": SNAPSHOT_VERSION,
            "analysis_date": analysis_date.isoformat(),
            "as_of": as_of.isoformat(),
            "market_context": market_rows[0] if market_rows else None,
            "summary": summary_payload,
            "episodes": observations,
            "attention_stocks": attention_stocks,
        },
    )
    return PrepareSummary(
        status="prepared",
        analysis_date=analysis_date.isoformat(),
        snapshot_file=str(snapshot_path),
        **summary_payload,
    )


def record_forward_monitor(
    *,
    snapshot_file: Path,
    report_file: Path,
    project_root: Path,
) -> RecordSummary:
    snapshot_path = Path(snapshot_file)
    pending_path = Path(report_file)
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    if not isinstance(snapshot, dict) or snapshot.get("snapshot_version") != SNAPSHOT_VERSION:
        raise ValueError("snapshot must be forward-monitor-snapshot-v1")
    raw_report = json.loads(pending_path.read_text(encoding="utf-8"))
    report = DailyForwardMonitorReportV1.model_validate(raw_report)
    if report.analysis_date.isoformat() != str(snapshot.get("analysis_date")):
        raise ValueError("report analysis_date does not match snapshot")
    snapshot_as_of = _as_datetime(snapshot.get("as_of"))
    if snapshot_as_of is None or report.as_of != snapshot_as_of:
        raise ValueError("report as_of does not match snapshot")

    snapshot_summary = snapshot.get("summary", {})
    expected_pool_summary = {
        key: int(snapshot_summary.get(key, 0))
        for key in (
            "open_episode_count",
            "distinct_stock_count",
            "selected_count",
            "comparator_count",
            "primary_count",
            "passive_tail_count",
            "attention_stock_count",
        )
    }
    expected_pool_summary["routine_stock_count"] = (
        expected_pool_summary["distinct_stock_count"]
        - expected_pool_summary["attention_stock_count"]
    )
    if report.pool_summary.model_dump() != expected_pool_summary:
        raise ValueError("report pool_summary does not match snapshot")

    attention = {
        str(item.get("ts_code")): item
        for item in snapshot.get("attention_stocks", [])
        if isinstance(item, dict)
    }
    episodes = {
        str(item.get("episode_id")): item
        for item in snapshot.get("episodes", [])
        if isinstance(item, dict)
    }
    for alert in report.alerts:
        attention_item = attention.get(alert.ts_code)
        if attention_item is None:
            raise ValueError(f"alert stock is not in snapshot attention set: {alert.ts_code}")
        if alert.name != str(attention_item.get("name", "")):
            raise ValueError(f"alert stock name does not match snapshot: {alert.ts_code}")
        if len(alert.episode_ids) != len(set(alert.episode_ids)):
            raise ValueError(f"alert contains duplicate episode ids: {alert.ts_code}")
        attention_episode_ids = {
            str(value)
            for value in attention_item.get("episode_ids", [])
        }
        if not set(alert.episode_ids).issubset(attention_episode_ids):
            raise ValueError(f"alert episode is not in stock attention set: {alert.ts_code}")
        referenced: list[dict[str, Any]] = []
        for episode_id in alert.episode_ids:
            episode = episodes.get(episode_id)
            if episode is None:
                raise ValueError(f"alert episode does not exist: {episode_id}")
            if str(episode.get("ts_code")) != alert.ts_code:
                raise ValueError(f"alert episode stock mismatch: {episode_id}")
            referenced.append(episode)
        valid_roles = {str(item.get("role")) for item in referenced}
        if valid_roles != {alert.role}:
            raise ValueError(f"alert role does not match referenced episodes: {alert.ts_code}")
        valid_days = sorted({int(item["day_number"]) for item in referenced})
        if alert.day_numbers != valid_days:
            raise ValueError(f"alert day numbers do not match referenced episodes: {alert.ts_code}")
        valid_engines = sorted(
            {
                str(item["original_engine_type"])
                for item in referenced
                if item.get("original_engine_type")
            }
        )
        if alert.original_engine_types != valid_engines:
            raise ValueError(f"alert original engines do not match referenced episodes: {alert.ts_code}")

    expected_unreported = (
        int(snapshot_summary.get("attention_stock_count", 0))
        - len(report.alerts)
    )
    if report.unreported_attention_count != expected_unreported:
        raise ValueError(
            "report unreported_attention_count does not match snapshot"
        )

    output = report.model_dump(mode="json")
    monitor_dir = Path(project_root) / "local_archive" / "forward_monitor"
    json_path = monitor_dir / f"monitor-report-{report.analysis_date.isoformat()}.json"
    markdown_path = monitor_dir / f"monitor-report-{report.analysis_date.isoformat()}.md"
    if json_path.is_file():
        try:
            existing_raw = json.loads(json_path.read_text(encoding="utf-8"))
            existing = DailyForwardMonitorReportV1.model_validate(
                existing_raw
            ).model_dump(mode="json")
        except (OSError, json.JSONDecodeError, ValueError):
            existing = None
        if existing == output:
            if not markdown_path.is_file():
                _atomic_write_text(
                    markdown_path,
                    _render_markdown(report, snapshot),
                )
            pending_path.unlink()
            return RecordSummary(
                status="already_recorded",
                analysis_date=report.analysis_date.isoformat(),
                json_file=str(json_path),
                markdown_file=str(markdown_path),
                alert_count=len(report.alerts),
                unreported_attention_count=report.unreported_attention_count,
            )
        return RecordSummary(
            status="report_conflict",
            analysis_date=report.analysis_date.isoformat(),
            json_file=str(json_path),
            markdown_file=str(markdown_path),
            alert_count=len(report.alerts),
            unreported_attention_count=report.unreported_attention_count,
        )

    _atomic_write_json(json_path, output)
    _atomic_write_text(markdown_path, _render_markdown(report, snapshot))
    pending_path.unlink()
    return RecordSummary(
        status="recorded",
        analysis_date=report.analysis_date.isoformat(),
        json_file=str(json_path),
        markdown_file=str(markdown_path),
        alert_count=len(report.alerts),
        unreported_attention_count=report.unreported_attention_count,
    )


def _render_markdown(
    report: DailyForwardMonitorReportV1,
    snapshot: dict[str, Any],
) -> str:
    overview = report.market_overview
    pool = report.pool_summary
    episodes = {
        str(item.get("episode_id")): item
        for item in snapshot.get("episodes", [])
        if isinstance(item, dict)
    }
    role_labels = {
        "selected": "入选",
        "comparator": "对照",
    }
    basis_labels = {
        "fresh_event_pending": "新事件等待首次定价",
        "event_repricing_confirmed": "事件带来的价格变化已得到确认",
        "sector_broad_diffusion": "板块内多数股票共同走强",
        "sector_leader_cluster": "板块内龙头股票集中走强",
        "independent_demand_acceleration": "个股独立需求加速",
        "anchor_only": "只有基本面支撑，暂未出现有效短期推动因素",
        "unresolved": "尚未确认短期推动因素",
    }
    state_labels = {
        "pending_confirmation": "等待确认",
        "routine": "常规观察",
        "strengthening": "正在转强",
        "actionable_watch": "接近重点观察条件",
        "overheated": "短期可能过热",
        "invalidated": "原判断已失效",
        "target_hit": "前20个交易日目标已达到",
        "passive_tail": "后10个交易日继续观察",
    }
    outlook_labels = {
        "event_pending": "等待新事件首次反应",
        "strengthening": "正在转强",
        "continuation_possible": "仍有延续可能",
        "range_or_wait": "震荡或继续等待",
        "weakening": "正在转弱",
        "overheated": "可能过热",
        "invalidated": "原判断已失效",
    }
    lines = [
        f"# {report.analysis_date.isoformat()} 股票跟踪",
        "",
        "## 今日市场",
        "",
        f"{overview.what_changed} {overview.implication_for_monitored_stocks}",
        "",
        "## 重点提醒",
        "",
    ]
    if not report.alerts:
        lines.append("今天没有需要详细提醒的股票。")
    for alert in report.alerts:
        referenced = [
            episodes[episode_id]
            for episode_id in alert.episode_ids
        ]
        primary_reasons = list(
            dict.fromkeys(
                str(item["original_primary_reason"])
                for item in referenced
                if item.get("original_primary_reason")
            )
        )
        basis = "；".join(
            basis_labels.get(engine, "尚未确认短期推动因素")
            for engine in alert.original_engine_types
        )
        lines.extend(
            [
                f"### {alert.name}（{alert.ts_code}）",
                "",
                "当前："
                + " / ".join(f"D{day}" for day in alert.day_numbers),
                f"原角色：{role_labels[alert.role]}",
                f"最初入选依据：{basis or '未记录'}",
                "原始主要理由："
                + ("；".join(primary_reasons) if primary_reasons else "未记录"),
                f"当前状态：{state_labels[alert.monitor_state]}",
                f"大盘：{alert.market_change}",
                f"板块：{alert.sector_change}",
                f"个股：{alert.stock_change}",
                f"公司：{alert.company_change}",
                "未来1—3个交易日基础情形："
                + outlook_labels[alert.outlook_1_3d],
                f"确认条件：{alert.confirmation_condition}",
                f"失效条件：{alert.invalidation_condition}",
                f"提醒原因：{alert.why_reported}",
            ]
        )
        if alert.alert_type == "late_activation":
            lines.append("迟到启动，不改变原20个交易日结果")
        lines.append("")
    lines.extend(
        [
            "## 跟踪数量概览",
            "",
            f"仍在跟踪 {pool.open_episode_count} 条记录，涉及 {pool.distinct_stock_count} 只股票；前20个交易日 {pool.primary_count} 条，后10个交易日观察 {pool.passive_tail_count} 条。",
            "",
            "## 未详细显示",
            "",
            f"还有 {report.unreported_attention_count} 只触发变化但未在上面详细显示。{report.routine_summary}",
            "",
        ]
    )
    return "\n".join(lines)


def _episode_observation(
    *,
    price_path_cache: dict[
        date,
        tuple[pd.DataFrame, pd.DataFrame],
    ],
    base: dict[str, Any],
    analysis_date: date,
    as_of: datetime,
    day_number: int,
    phase: str,
    path_days: list[date],
    price_row: dict[str, Any] | None,
    sector_row: dict[str, Any] | None,
    group_code: str | None,
    announcements: list[dict[str, Any]],
    previous_episode: dict[str, Any] | None,
    previous_as_of: str | None,
    previous_monitor_state: str | None,
    market_context_available: bool,
) -> dict[str, Any]:
    ts_code = str(base["ts_code"])
    limitations: list[str] = []
    path = _adjusted_path(
        price_path_cache,
        ts_code,
        path_days,
    )
    if not path:
        limitations.append("missing_price_path")
    elif len(path) != len(path_days):
        limitations.append("incomplete_price_path")
    action_date = date.fromisoformat(str(base["action_date"]))
    entry = next(
        (item["open"] for item in path if item["date"] == action_date),
        None,
    )
    d20_dates = set(path_days[:20])
    d20_path = [item for item in path if item["date"] in d20_dates]
    d20_metrics_path = d20_path
    if day_number >= 20 and not (
        len(d20_path) == 20
        and [item["date"] for item in d20_path] == path_days[:20]
    ):
        d20_metrics_path = []
        if "incomplete_price_path" not in limitations:
            limitations.append("incomplete_price_path")
    current_fields = _price_fields(price_row)
    if phase != "closed" and price_row is None:
        limitations.append("missing_current_price_context")
    elif phase != "closed" and str((price_row or {}).get("coverage_status", "complete")) != "complete":
        limitations.append("price_context_incomplete")
    if phase != "closed" and base.get("original_engine_type") in {"sector_broad_diffusion", "sector_leader_cluster"} and sector_row is None:
        limitations.append("missing_sector_context")
    if phase != "closed" and not market_context_available:
        limitations.append("missing_market_context")
    if phase == "closed":
        current_fields = {
            key: ([] if key in {"scenario_case_ids", "scenario_control_ids"} else None)
            for key in current_fields
        }

    new_announcements = _new_announcements(
        announcements,
        ts_code=ts_code,
        after=_as_datetime(previous_as_of) or _as_datetime(base.get("source_as_of")),
        as_of=as_of,
    )
    checkpoint = CHECKPOINTS.get(day_number) if phase != "closed" else None
    observation: dict[str, Any] = {
        **{key: value for key, value in base.items() if key != "source_as_of"},
        "analysis_date": analysis_date.isoformat(),
        "day_number": day_number,
        "monitor_phase": phase,
        "primary_days_remaining": max(20 - day_number, 0) if phase == "primary" else 0,
        "tail_days_remaining": 10 if phase == "primary" else max(30 - day_number, 0),
        "entry_open": entry,
        "first_observable_date": (
            path[0]["date"].isoformat() if path else None
        ),
        **_path_metrics(d20_metrics_path, entry, prefix="d20"),
        **_path_metrics(path, entry, prefix="current"),
        **current_fields,
        "original_group_code": group_code,
        **_sector_fields(sector_row),
        "new_announcements": new_announcements,
        "checkpoint": checkpoint,
        "previous_monitor_state": previous_monitor_state,
        "attention_reasons": [],
        "data_limitations": limitations,
    }
    if phase != "closed":
        observation["attention_reasons"] = _attention_reasons(
            observation,
            previous_episode,
        )
    return _json_value(observation)


def _attention_reasons(
    current: dict[str, Any],
    previous: dict[str, Any] | None,
) -> list[str]:
    reasons: list[str] = []
    if current["checkpoint"]:
        reasons.append("checkpoint")
    if current["new_announcements"]:
        reasons.append("new_official_event")
    if (
        current["original_engine_type"] == "fresh_event_pending"
        and current.get("first_observable_date") == current["analysis_date"]
    ):
        reasons.append("first_event_reaction")
    first_hit = current["d20_first_close_hit_20pct_date"]
    previous_first_hit = None
    if previous is not None:
        if "d20_first_close_hit_20pct_date" in previous:
            previous_first_hit = previous.get(
                "d20_first_close_hit_20pct_date"
            )
        else:
            previous_first_hit = previous.get("first_close_hit_20pct_date")
    if first_hit and (
        (previous is not None and not previous_first_hit)
        or (previous is None and first_hit == current["analysis_date"])
    ):
        reasons.append("target_hit_first_time")
    if previous:
        if any(
            _sign_flip(previous.get(key), current.get(key))
            for key in ("relative_market_5d", "relative_industry_5d")
        ):
            reasons.append("relative_state_changed")
        if set(previous.get("scenario_case_ids") or []) != set(current.get("scenario_case_ids") or []):
            reasons.append("scenario_changed")
        if _breakout_state(previous.get("breakout_vs_prior60")) != _breakout_state(current.get("breakout_vs_prior60")):
            reasons.append("breakout_changed")
        if current.get("original_engine_type") in {"sector_broad_diffusion", "sector_leader_cluster"} and _sector_holds(previous) != _sector_holds(current):
            reasons.append("sector_state_changed")
    if _late_activation(current, previous):
        reasons.append("late_activation_candidate")
    if _overheat(current, previous):
        reasons.append("overheat_candidate")
    current_limitations = set(current["data_limitations"])
    previous_limitations = set((previous or {}).get("data_limitations") or [])
    if current_limitations and (
        previous is None
        or current_limitations != previous_limitations
        or current["checkpoint"]
    ):
        reasons.append("data_problem")
    allowed_order = [
        "checkpoint", "new_official_event", "first_event_reaction",
        "target_hit_first_time", "relative_state_changed", "scenario_changed",
        "breakout_changed", "sector_state_changed", "late_activation_candidate",
        "overheat_candidate", "data_problem",
    ]
    return [reason for reason in allowed_order if reason in reasons]


def _late_activation(current: dict[str, Any], previous: dict[str, Any] | None) -> bool:
    if current["monitor_phase"] != "passive_tail" or previous is None:
        return False
    if not all(_positive(current.get(key)) for key in ("relative_market_3d", "relative_market_5d")):
        return False
    industry_reliable = current.get("relative_industry_3d") is not None and current.get("relative_industry_5d") is not None
    if industry_reliable and not all(_positive(current.get(key)) for key in ("relative_industry_3d", "relative_industry_5d")):
        return False
    if not _greater(current.get("amount_ratio_last_20d"), 1.0):
        return False
    current_cases = set(current.get("scenario_case_ids") or [])
    previous_cases = set((previous or {}).get("scenario_case_ids") or [])
    new_cases = current_cases - previous_cases
    breakout_new = _breakout_state(current.get("breakout_vs_prior60")) and not _breakout_state((previous or {}).get("breakout_vs_prior60"))
    if not (breakout_new or bool(new_cases & POSITIVE_SCENARIOS)):
        return False
    return not bool(new_cases & NEGATIVE_SCENARIOS)


def _overheat(current: dict[str, Any], previous: dict[str, Any] | None) -> bool:
    if previous is None:
        return False
    current_cases = set(current.get("scenario_case_ids") or [])
    previous_cases = set(previous.get("scenario_case_ids") or [])
    if (current_cases - previous_cases) & OVERHEAT_SCENARIOS:
        return True
    if _greater(current.get("limit_up_return_contribution_5d"), 0.5) and not _greater(previous.get("limit_up_return_contribution_5d"), 0.5):
        return True
    high_state = _breakout_state(current.get("breakout_vs_prior60"))
    fade_worse = _greater(current.get("fade_frequency_5d"), previous.get("fade_frequency_5d"))
    shadow_worse = _greater(current.get("upper_shadow_frequency_5d"), previous.get("upper_shadow_frequency_5d"))
    efficiency_worse = _less(current.get("volume_price_efficiency_5d"), previous.get("volume_price_efficiency_5d"))
    return high_state and (fade_worse or shadow_worse or efficiency_worse)


def _trading_sessions(root: Path, as_of: datetime) -> list[date]:
    rows = _fact_rows(root, "trade_calendar", as_of)
    dates = {
        _as_date(row.get("cal_date"))
        for row in rows
        if _truth(row.get("is_open")) and _as_date(row.get("cal_date")) is not None
    }
    return sorted(day for day in dates if day is not None and day <= as_of.date())


def _fact_rows(root: Path, dataset: str, as_of: datetime) -> list[dict[str, Any]]:
    base = root / "local_warehouse" / "facts" / dataset
    frames: list[pd.DataFrame] = []
    for path in sorted(base.glob("**/*.parquet")):
        try:
            frame = pd.read_parquet(path)
        except (OSError, ValueError):
            continue
        if "available_at" in frame.columns:
            available = pd.to_datetime(frame["available_at"], utc=True, errors="coerce")
            cutoff = pd.Timestamp(as_of).tz_convert("UTC")
            frame = frame.loc[available.notna() & available.le(cutoff)]
        if not frame.empty:
            frames.append(frame)
    if not frames:
        return []
    return [_json_value(row) for row in pd.concat(frames, ignore_index=True).to_dict("records")]


def _derived_rows(
    root: Path,
    dataset: str,
    analysis_date: date,
    formula_version: str,
    as_of: datetime,
) -> list[dict[str, Any]]:
    path = (
        root
        / "local_warehouse"
        / "derived"
        / dataset
        / f"analysis_date={analysis_date.isoformat()}"
        / f"formula_version={formula_version}"
        / "data.parquet"
    )
    if not path.is_file():
        return []
    frame = pd.read_parquet(path)
    if "available_at" in frame.columns:
        available = pd.to_datetime(frame["available_at"], utc=True, errors="coerce")
        frame = frame.loc[available.notna() & available.le(pd.Timestamp(as_of).tz_convert("UTC"))]
    return [_json_value(row) for row in frame.to_dict("records")]


def _daily_price_cache(
    root: Path,
    path_days: list[date],
    as_of: datetime,
) -> dict[date, tuple[pd.DataFrame, pd.DataFrame]]:
    cache: dict[date, tuple[pd.DataFrame, pd.DataFrame]] = {}
    cutoff = pd.Timestamp(as_of).tz_convert("UTC")
    for day in path_days:
        equity_path = root / "local_warehouse" / "facts" / "equity_daily" / f"trade_date={day.isoformat()}" / "data.parquet"
        factor_path = root / "local_warehouse" / "facts" / "adj_factor" / f"trade_date={day.isoformat()}" / "data.parquet"
        if not equity_path.is_file() or not factor_path.is_file():
            continue
        equity = pd.read_parquet(equity_path)
        factors = pd.read_parquet(factor_path)
        if "available_at" in equity.columns:
            available = pd.to_datetime(
                equity["available_at"],
                utc=True,
                errors="coerce",
            )
            equity = equity.loc[
                available.notna() & available.le(cutoff)
            ]
        if "available_at" in factors.columns:
            available = pd.to_datetime(
                factors["available_at"],
                utc=True,
                errors="coerce",
            )
            factors = factors.loc[
                available.notna() & available.le(cutoff)
            ]
        cache[day] = (equity, factors)
    return cache


def _adjusted_path(
    cache: dict[date, tuple[pd.DataFrame, pd.DataFrame]],
    ts_code: str,
    path_days: list[date],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for day in path_days:
        frames = cache.get(day)
        if frames is None:
            continue
        equity, factors = frames
        equity = equity.loc[equity["ts_code"].astype(str).eq(ts_code)]
        factors = factors.loc[factors["ts_code"].astype(str).eq(ts_code)]
        if equity.empty or factors.empty:
            continue
        row = equity.iloc[-1]
        factor = _number(factors.iloc[-1].get("adj_factor"))
        if factor is None:
            continue
        values = {name: _number(row.get(name)) for name in ("open", "close", "high", "low")}
        if any(value is None for value in values.values()):
            continue
        result.append(
            {
                "date": day,
                **{name: float(value) * factor for name, value in values.items()},
            }
        )
    return result


def _path_metrics(
    path: list[dict[str, Any]],
    entry: float | None,
    *,
    prefix: Literal["d20", "current"],
) -> dict[str, Any]:
    hit_key = (
        "d20_hit_20pct_close_within_20d"
        if prefix == "d20"
        else "current_hit_20pct_close"
    )
    empty = {
        f"{prefix}_close_return_since_entry": None,
        f"{prefix}_max_close_return_since_entry": None,
        f"{prefix}_max_high_return_since_entry": None,
        f"{prefix}_mae_since_entry": None,
        f"{prefix}_first_close_hit_20pct_date": None,
        f"{prefix}_first_high_hit_20pct_date": None,
        hit_key: None,
    }
    if not path or entry is None or entry <= 0:
        return empty
    close_returns = [(item["close"] / entry) - 1.0 for item in path]
    high_returns = [(item["high"] / entry) - 1.0 for item in path]
    low_returns = [(item["low"] / entry) - 1.0 for item in path]
    close_hit_threshold = 0.20 - 1e-12 if prefix == "d20" else 0.20
    first_close_hit = next(
        (
            item["date"].isoformat()
            for item, value in zip(path, close_returns, strict=True)
            if value >= close_hit_threshold
        ),
        None,
    )
    return {
        f"{prefix}_close_return_since_entry": close_returns[-1],
        f"{prefix}_max_close_return_since_entry": max(close_returns),
        f"{prefix}_max_high_return_since_entry": max(high_returns),
        f"{prefix}_mae_since_entry": min(low_returns),
        f"{prefix}_first_close_hit_20pct_date": first_close_hit,
        f"{prefix}_first_high_hit_20pct_date": next(
            (
                item["date"].isoformat()
                for item, value in zip(path, high_returns, strict=True)
                if value >= 0.2
            ),
            None,
        ),
        hit_key: first_close_hit is not None,
    }


def _price_fields(row: dict[str, Any] | None) -> dict[str, Any]:
    row = row or {}
    mapping = {
        "relative_market_1d": "relative_market_1d",
        "relative_market_3d": "relative_market_3d",
        "relative_market_5d": "relative_market_5d",
        "relative_industry_1d": "relative_industry_return_1d",
        "relative_industry_3d": "relative_industry_return_3d",
        "relative_industry_5d": "relative_industry_return_5d",
        "amount_ratio_last_20d": "amount_ratio_last_20d",
        "volume_price_efficiency_5d": "volume_price_efficiency_5d",
        "mean_close_position_5d": "mean_close_position_5d",
        "upper_shadow_frequency_5d": "upper_shadow_frequency_5d",
        "fade_frequency_5d": "fade_frequency_5d",
        "breakout_vs_prior60": "breakout_vs_prior60",
        "limit_up_return_contribution_5d": "limit_up_return_contribution_5d",
        "target_atr_distance_20pct": "target_atr_distance_20pct",
    }
    fields = {target: _number(row.get(source)) for target, source in mapping.items()}
    fields["scenario_case_ids"] = _ids(row.get("scenario_case_ids"))
    fields["scenario_control_ids"] = _ids(row.get("scenario_control_ids"))
    return fields


def _sector_fields(row: dict[str, Any] | None) -> dict[str, Any]:
    row = row or {}
    mapping = {
        "sector_relative_return_3d": "relative_return_3d",
        "sector_relative_return_5d": "relative_return_5d",
        "sector_median_return_3d": "median_return_3d",
        "sector_median_return_5d": "median_return_5d",
        "sector_breadth_3d": "breadth_3d",
        "sector_breadth_5d": "breadth_5d",
        "sector_turnover_share_change_5d": "turnover_share_change_5d",
        "sector_top_contribution": "top3_positive_contribution_1d",
        "sector_dispersion": "return_dispersion_1d",
    }
    return {target: _number(row.get(source)) for target, source in mapping.items()}


def _new_announcements(
    rows: list[dict[str, Any]],
    *,
    ts_code: str,
    after: datetime | None,
    as_of: datetime,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get("ts_code")) != ts_code:
            continue
        available = _as_datetime(row.get("available_at"))
        if available is None or available > as_of:
            continue
        if after is not None and available <= after:
            continue
        result.append(
            {
                "announcement_id": row.get("announcement_id"),
                "announcement_time": row.get("announcement_time"),
                "available_at": available.isoformat(),
                "title": row.get("title"),
            }
        )
    return sorted(result, key=lambda item: (str(item["available_at"]), str(item["announcement_id"])))


def _formation_industry(
    rows: list[dict[str, Any]],
    ts_code: str,
    formation_date: date,
    source_as_of: datetime | None,
) -> str | None:
    if source_as_of is None:
        return None
    matches: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get("ts_code")) != ts_code:
            continue
        if row.get("industry_system") != "SW2021" or row.get("level") != "L2":
            continue
        available = _as_datetime(row.get("available_at"))
        if available is None or available > source_as_of:
            continue
        valid_from = _as_date(row.get("valid_from"))
        valid_to = _as_date(row.get("valid_to"))
        if valid_from and valid_from <= formation_date and (valid_to is None or formation_date <= valid_to):
            matches.append(row)
    if not matches:
        return None
    matches.sort(
        key=lambda row: (
            _as_date(row.get("valid_from")) or date.min,
            _as_datetime(row.get("available_at")) or datetime.min,
        )
    )
    return str(matches[-1].get("industry_code") or "") or None


def _aggregate_attention(episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for episode in episodes:
        if episode["monitor_phase"] == "closed" or not episode["attention_reasons"]:
            continue
        grouped.setdefault(str(episode["ts_code"]), []).append(episode)
    result: list[dict[str, Any]] = []
    allowed = [
        "checkpoint", "new_official_event", "first_event_reaction",
        "target_hit_first_time", "relative_state_changed", "scenario_changed",
        "breakout_changed", "sector_state_changed", "late_activation_candidate",
        "overheat_candidate", "data_problem",
    ]
    for ts_code in sorted(grouped):
        items = grouped[ts_code]
        reasons = {reason for item in items for reason in item["attention_reasons"]}
        result.append(
            {
                "ts_code": ts_code,
                "name": next((str(item["name"]) for item in items if item.get("name")), ""),
                "episode_ids": sorted(str(item["episode_id"]) for item in items),
                "roles": sorted({str(item["role"]) for item in items}),
                "day_numbers": sorted({int(item["day_number"]) for item in items}),
                "original_engine_types": sorted({str(item["original_engine_type"]) for item in items if item.get("original_engine_type")}),
                "attention_reasons": [reason for reason in allowed if reason in reasons],
            }
        )
    return result


def _previous_snapshot(monitor_dir: Path, analysis_date: date) -> dict[str, Any] | None:
    candidates: list[tuple[date, Path]] = []
    for path in monitor_dir.glob("snapshot-*.json"):
        try:
            snapshot_date = date.fromisoformat(path.stem.removeprefix("snapshot-"))
        except ValueError:
            continue
        if snapshot_date < analysis_date:
            candidates.append((snapshot_date, path))
    if not candidates:
        return None
    path = max(candidates, key=lambda item: item[0])[1]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) and payload.get("snapshot_version") == SNAPSHOT_VERSION else None


def _previous_monitor_states(
    monitor_dir: Path,
    analysis_date: date,
    previous_snapshot: dict[str, Any] | None,
) -> dict[str, str]:
    carried = {
        str(item.get("episode_id")): str(item["previous_monitor_state"])
        for item in (previous_snapshot or {}).get("episodes", [])
        if item.get("episode_id") and item.get("previous_monitor_state")
    }
    reports: list[tuple[date, Path]] = []
    for path in monitor_dir.glob("monitor-report-*.json"):
        try:
            report_date = date.fromisoformat(
                path.stem.removeprefix("monitor-report-")
            )
        except ValueError:
            continue
        if report_date < analysis_date:
            reports.append((report_date, path))
    found: dict[str, str] = {}
    for _, path in sorted(reports):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        for alert in payload.get("alerts", []):
            if not isinstance(alert, dict) or not alert.get("monitor_state"):
                continue
            for episode_id in alert.get("episode_ids", []):
                found[str(episode_id)] = str(alert["monitor_state"])
    return {**carried, **found}


def _sector_holds(item: dict[str, Any]) -> bool:
    engine = item.get("original_engine_type")
    common = (
        _positive(item.get("sector_relative_return_3d"))
        and _positive(item.get("sector_relative_return_5d"))
        and _positive(item.get("sector_turnover_share_change_5d"))
    )
    if engine == "sector_broad_diffusion":
        return bool(
            common
            and _positive(item.get("sector_median_return_3d"))
            and _positive(item.get("sector_median_return_5d"))
            and _greater(item.get("sector_breadth_3d"), 0.5)
            and _greater(item.get("sector_breadth_5d"), 0.5)
            and _less(item.get("sector_top_contribution"), 0.8)
        )
    if engine == "sector_leader_cluster":
        return bool(common and not _greater(item.get("sector_top_contribution"), 0.6))
    return False


def _ids(value: Any) -> list[str]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    if isinstance(value, list):
        return sorted({str(item).strip() for item in value if str(item).strip()})
    text = str(value).strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            return sorted({str(item).strip() for item in parsed if str(item).strip()})
    return sorted({part.strip() for part in text.replace(";", ",").split(",") if part.strip()})


def _number(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _positive(value: Any) -> bool:
    return _greater(value, 0.0)


def _greater(left: Any, right: Any) -> bool:
    left_number = _number(left)
    right_number = _number(right)
    return left_number is not None and right_number is not None and left_number > right_number


def _less(left: Any, right: Any) -> bool:
    left_number = _number(left)
    right_number = _number(right)
    return left_number is not None and right_number is not None and left_number < right_number


def _truth(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return bool(value) if value is not None and not pd.isna(value) else False


def _breakout_state(value: Any) -> bool:
    return _greater(value, 0.0)


def _sign_flip(before: Any, after: Any) -> bool:
    left = _number(before)
    right = _number(after)
    return left is not None and right is not None and ((left > 0 > right) or (left < 0 < right))


def _as_date(value: Any) -> date | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _as_datetime(value: Any) -> datetime | None:
    if value is None or pd.isna(value):
        return None
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None:
        return None
    return stamp.to_pydatetime()


def _json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_value(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if value is None or value is pd.NA:
        return None
    if hasattr(value, "item"):
        try:
            value = value.item()
        except (TypeError, ValueError):
            pass
    if isinstance(value, float) and pd.isna(value):
        return None
    return value


def _trace_episodes(
    trace: dict[str, Any],
    *,
    label: str,
    source_type: str,
) -> list[dict[str, Any]]:
    formation_date = str(trace.get("formation_date", ""))
    action_date = str(trace.get("action_date", ""))
    source_as_of = str(trace.get("as_of", ""))
    ledger = {
        str(item.get("ts_code", "")): item
        for item in trace.get("candidate_ledger", [])
        if isinstance(item, dict)
    }
    result = trace.get("research_result", {})
    groups = (
        ("selected", result.get("selected_stocks", [])),
        ("comparator", result.get("nearest_nonselections", [])),
    )
    episodes: list[dict[str, Any]] = []
    for role, items in groups:
        for item in items:
            ts_code = str(item.get("ts_code", "")).strip()
            candidate = ledger.get(ts_code, {})
            thesis = candidate.get("research_thesis", {})
            recognition = thesis.get("market_recognition")
            broad = thesis.get("sector_broad_diffusion") or {}
            cluster = thesis.get("sector_leader_cluster") or {}
            episodes.append(
                {
                    "episode_id": f"{label}:{formation_date}:{ts_code}:{role}",
                    "source_type": source_type,
                    "source_as_of": source_as_of,
                    "role": role,
                    "formation_date": formation_date,
                    "action_date": action_date,
                    "ts_code": ts_code,
                    "name": str(item.get("name", "")).strip(),
                    "original_priority": item.get("priority"),
                    "original_opportunity_type": item.get("opportunity_type"),
                    "original_engine_type": thesis.get("engine_type"),
                    "original_engine_status": thesis.get("engine_status"),
                    "original_market_recognition": recognition,
                    "original_primary_reason": candidate.get("primary_reason"),
                    "original_strongest_counterevidence": item.get(
                        "strongest_counterevidence"
                    ),
                    "original_nearest_comparison": item.get("nearest_comparison"),
                    "original_group_code": broad.get("group_code")
                    or cluster.get("group_code"),
                }
            )
    return episodes


def _read_registry(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"registry_version": REGISTER_VERSION, "episodes": []}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(payload, dict)
        or payload.get("registry_version") != REGISTER_VERSION
        or not isinstance(payload.get("episodes"), list)
    ):
        raise ValueError("registered episode file is invalid")
    return payload


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_name = handle.name
            json.dump(
                payload,
                handle,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except Exception:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)
        raise


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_name = handle.name
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except Exception:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)
        raise


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Track V4 selections after they are chosen")
    commands = parser.add_subparsers(dest="command", required=True)
    register = commands.add_parser("register")
    register.add_argument("--trace-file", required=True)
    register.add_argument("--label", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--analysis-date", required=True)
    prepare.add_argument("--as-of", required=True)
    record = commands.add_parser("record")
    record.add_argument("--snapshot-file", required=True)
    record.add_argument("--report-file", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    project_root = Path(__file__).resolve().parents[3]
    try:
        if args.command == "register":
            summary: Any = register_episodes(
                trace_file=Path(args.trace_file).expanduser().resolve(),
                label=args.label,
                project_root=project_root,
            )
        elif args.command == "prepare":
            summary = prepare_forward_monitor(
                analysis_date=date.fromisoformat(args.analysis_date),
                as_of=datetime.fromisoformat(args.as_of),
                project_root=project_root,
            )
        else:
            summary = record_forward_monitor(
                snapshot_file=Path(args.snapshot_file).expanduser().resolve(),
                report_file=Path(args.report_file).expanduser().resolve(),
                project_root=project_root,
            )
    except Exception as error:
        print("status=error")
        print(f"error={type(error).__name__}: {error}")
        return 2
    for key, value in asdict(summary).items():
        print(f"{key}={value}")
    return 0


__all__ = [
    "DailyForwardMonitorReportV1",
    "PrepareSummary",
    "RecordSummary",
    "RegisterSummary",
    "prepare_forward_monitor",
    "record_forward_monitor",
    "register_episodes",
]


if __name__ == "__main__":
    raise SystemExit(main())
