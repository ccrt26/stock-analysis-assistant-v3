"""Isolated holdout validation for V3 project lifecycle and action confirmation.

This is an evaluation tool, not a production recommendation or trading service.
All runtime artifacts are restricted to the dedicated USB experiment directory.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import argparse
import json
from pathlib import Path
import shutil
import sys
import time
from typing import Any

import numpy as np
import pandas as pd
import yaml

from stock_analyzer.evaluation.v3_compression_revalidation import (
    compress_decision_list,
)
from stock_analyzer.evaluation.v3_next_day_entry_validation import (
    _read_action_price_frame,
    compute_action_path,
    summarize_actions,
    validate_action_contracts,
)
from stock_analyzer.evaluation.v3_layered_validation import (
    Block as LayeredBlock,
    ValidationConfig as LayeredValidationConfig,
    available_sessions,
    run_blocks,
)
from stock_analyzer.evaluation.v3_target_retention_diagnostic import (
    _tree_signature,
    _write_json,
    _write_parquet,
)


DEFAULT_ALLOWED_VOLUME_ROOT = Path("/Volumes/ZHUTONG")
ACTION_FIELDS = (
    "return_5d",
    "relative_return_20d",
    "current_amount_ratio_20d",
)


@dataclass(frozen=True)
class HoldoutBlock:
    id: str
    start: date
    end: date


@dataclass(frozen=True)
class LifecycleActionConfig:
    experiment_id: str
    warehouse_root: Path
    development_compression_root: Path
    output_root: Path
    holdout: HoldoutBlock
    formation_sessions: int
    horizons: tuple[int, ...]
    target_return: float
    retention_windows: tuple[int, ...]
    candidate_cap: int
    no_confirmation_exit_session: int
    second_wave_check_start: int
    second_wave_exit_session: int
    expiry_session: int
    entry_delay_market_sessions: int
    entry_price_field: str
    entry_day_counts_as_session_one: bool
    exclude_one_price_limit_up: bool
    minimum_executable_action_projects: int
    runtime_stop_hours: float
    rule_optimization_allowed: bool
    action_fields: tuple[str, ...] = ACTION_FIELDS


def load_config(path: str | Path) -> LifecycleActionConfig:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("lifecycle action config must be a mapping")
    holdout = payload["holdout"]
    config = LifecycleActionConfig(
        experiment_id=str(payload["experiment_id"]),
        warehouse_root=Path(payload["warehouse_root"]),
        development_compression_root=Path(payload["development_compression_root"]),
        output_root=Path(payload["output_root"]),
        holdout=HoldoutBlock(
            id=str(holdout["id"]),
            start=date.fromisoformat(str(holdout["start"])),
            end=date.fromisoformat(str(holdout["end"])),
        ),
        formation_sessions=int(payload["formation_sessions"]),
        horizons=tuple(int(value) for value in payload["horizons"]),
        target_return=float(payload["target_return"]),
        retention_windows=tuple(int(value) for value in payload["retention_windows"]),
        candidate_cap=int(payload["candidate_cap"]),
        no_confirmation_exit_session=int(payload["no_confirmation_exit_session"]),
        second_wave_check_start=int(payload["second_wave_check_start"]),
        second_wave_exit_session=int(payload["second_wave_exit_session"]),
        expiry_session=int(payload["expiry_session"]),
        entry_delay_market_sessions=int(payload["entry_delay_market_sessions"]),
        entry_price_field=str(payload["entry_price_field"]),
        entry_day_counts_as_session_one=bool(payload["entry_day_counts_as_session_one"]),
        exclude_one_price_limit_up=bool(payload["exclude_one_price_limit_up"]),
        minimum_executable_action_projects=int(
            payload["minimum_executable_action_projects"]
        ),
        runtime_stop_hours=float(payload["runtime_stop_hours"]),
        rule_optimization_allowed=bool(payload["rule_optimization_allowed"]),
    )
    _validate_config(config)
    return config


def _validate_config(config: LifecycleActionConfig) -> None:
    if config.holdout != HoldoutBlock(
        id="D", start=date(2025, 12, 11), end=date(2026, 1, 23)
    ):
        raise ValueError("holdout interval differs from the frozen D block")
    if config.formation_sessions != 30:
        raise ValueError("holdout must contain exactly 30 formation sessions")
    if config.horizons != (20, 30) or not np.isclose(config.target_return, 0.20):
        raise ValueError("target must remain +20% within 20/30 sessions")
    if config.retention_windows != (1, 3, 5):
        raise ValueError("retention windows must remain 1/3/5")
    if config.candidate_cap != 10:
        raise ValueError("attention list cap must remain 10")
    if (
        config.no_confirmation_exit_session,
        config.second_wave_check_start,
        config.second_wave_exit_session,
        config.expiry_session,
    ) != (10, 16, 20, 30):
        raise ValueError("lifecycle checkpoints differ from the frozen design")
    if config.entry_delay_market_sessions != 1 or config.entry_price_field != "open":
        raise ValueError("action entry must remain next-session open")
    if not config.entry_day_counts_as_session_one or not config.exclude_one_price_limit_up:
        raise ValueError("action execution semantics differ from the frozen design")
    if config.minimum_executable_action_projects != 20:
        raise ValueError("minimum action sample must remain 20 projects")
    if config.rule_optimization_allowed:
        raise ValueError("holdout rule optimization is forbidden")
    if config.runtime_stop_hours <= 0:
        raise ValueError("runtime stop must be positive")


def action_condition(row: pd.Series | dict[str, Any]) -> bool:
    values = pd.Series(row)
    if str(values.get("user_layer", "")) != "关注":
        return False
    if bool(values.get("hard_invalid", True)):
        return False
    numeric = pd.to_numeric(values.loc[list(ACTION_FIELDS)], errors="coerce")
    if numeric.isna().any():
        return False
    return bool(
        numeric["return_5d"] > 0
        and numeric["relative_return_20d"] > 0
        and numeric["current_amount_ratio_20d"] >= 1
    )


def prepare_output_root(
    config: LifecycleActionConfig,
    *,
    output_override: str | Path | None = None,
    allowed_volume_root: str | Path = DEFAULT_ALLOWED_VOLUME_ROOT,
) -> Path:
    output = Path(output_override) if output_override is not None else config.output_root
    expected = Path(allowed_volume_root) / "股票分析助手-V3回测" / config.experiment_id
    if output.resolve(strict=False) != expected.resolve(strict=False):
        raise ValueError("输出路径必须是冻结的U盘专用实验目录")
    for child in ("manifests", "tables", "reports", "logs"):
        (output / child).mkdir(parents=True, exist_ok=True)
    return output


def _normalize_date_column(frame: pd.DataFrame, column: str) -> pd.DataFrame:
    prepared = frame.copy()
    if column in prepared:
        prepared[column] = pd.to_datetime(prepared[column], errors="raise").dt.normalize()
    return prepared


def _snapshot(project: dict[str, Any], day: pd.Timestamp, *, active: bool) -> dict[str, Any]:
    return {
        "formation_date": day,
        "project_id": project["project_id"],
        "ts_code": project["ts_code"],
        "admission_date": project["admission_date"],
        "age_sessions": int(project["age_sessions"]),
        "status": project["status"],
        "active": bool(active),
        "action_plan_date": project.get("action_plan_date"),
        "action_date": project.get("action_date"),
        "entry_date": project.get("entry_date"),
        "action_price": project.get("action_price", np.nan),
        "last_condition_age": project.get("last_condition_age"),
        "unexecutable_attempts": int(project.get("unexecutable_attempts", 0)),
        "exit_reason": project.get("exit_reason"),
    }


def simulate_lifecycle(
    daily_attention: pd.DataFrame,
    daily_facts: pd.DataFrame,
    action_executions: pd.DataFrame,
    daily_prices: pd.DataFrame,
    sessions: pd.Index,
    config: LifecycleActionConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Simulate the frozen project protocol in strict session order.

    ``action_executions`` may contain next-session execution facts, but no
    forward target outcome. Target completion is checked only from each
    current session's high after an executable action has occurred.
    """

    calendar = pd.Index(pd.to_datetime(sessions, errors="raise").normalize())
    if calendar.has_duplicates or not calendar.is_monotonic_increasing:
        raise ValueError("sessions must be unique and increasing")
    attention = _normalize_date_column(daily_attention, "formation_date")
    facts = _normalize_date_column(daily_facts, "formation_date")
    executions = _normalize_date_column(action_executions, "plan_date")
    executions = _normalize_date_column(executions, "entry_date")
    prices = _normalize_date_column(daily_prices, "trade_date")
    if not attention.empty and attention.duplicated(["formation_date", "ts_code"]).any():
        raise ValueError("daily attention contains duplicate stock-date rows")
    if not executions.empty and executions.duplicated(["plan_date", "ts_code"]).any():
        raise ValueError("action executions contain duplicate plans")

    attention_by_day = {
        day: group.copy()
        for day, group in attention.groupby("formation_date", sort=False)
    }
    invalid_lookup = {
        (row.formation_date, str(row.ts_code)): bool(row.hard_invalid)
        for row in facts.itertuples(index=False)
    }
    execution_lookup = {
        (row.plan_date, str(row.ts_code)): row._asdict()
        for row in executions.itertuples(index=False)
    }
    high_lookup = {
        (row.trade_date, str(row.ts_code)): float(row.adj_high)
        for row in prices.itertuples(index=False)
        if pd.notna(row.adj_high)
    }

    active: dict[str, dict[str, Any]] = {}
    ended_codes: set[str] = set()
    snapshot_rows: list[dict[str, Any]] = []
    action_rows: list[dict[str, Any]] = []
    exclusion_rows: list[dict[str, Any]] = []

    def end_project(project: dict[str, Any], day: pd.Timestamp, reason: str) -> None:
        project["status"] = "completed" if reason == "target_completed" else "ended"
        project["exit_reason"] = reason
        snapshot_rows.append(_snapshot(project, day, active=False))
        active.pop(str(project["ts_code"]), None)
        ended_codes.add(str(project["ts_code"]))

    for session_index, day in enumerate(calendar):
        current_rows = attention_by_day.get(day, pd.DataFrame())
        current_by_code = (
            current_rows.set_index("ts_code", drop=False)
            if not current_rows.empty
            else pd.DataFrame()
        )

        for code in list(active):
            project = active[code]
            project["age_sessions"] = session_index - int(project["admission_index"])
            if project["status"] == "new" and project["age_sessions"] > 0:
                project["status"] = "tracking"

            pending = project.get("pending_plan_date")
            if pending is not None:
                execution = execution_lookup.get((pending, code))
                if execution is not None and execution["entry_date"] == day:
                    if bool(execution["executable_entry"]):
                        project.update(
                            {
                                "status": "action_confirmed",
                                "action_plan_date": pending,
                                "action_date": pending,
                                "entry_date": day,
                                "action_price": float(execution["action_price"]),
                                "pending_plan_date": None,
                            }
                        )
                        action_rows.append(
                            {
                                "project_id": project["project_id"],
                                "ts_code": code,
                                "plan_date": pending,
                                "entry_date": day,
                                "executable_entry": True,
                                "action_price": float(execution["action_price"]),
                            }
                        )
                    else:
                        project["pending_plan_date"] = None
                        project["unexecutable_attempts"] += 1

            if invalid_lookup.get((day, code), False):
                end_project(project, day, "hard_invalidation")
                continue

            action_price = project.get("action_price")
            current_high = high_lookup.get((day, code))
            if (
                action_price is not None
                and pd.notna(action_price)
                and current_high is not None
                and current_high / float(action_price) - 1.0 >= config.target_return
            ):
                end_project(project, day, "target_completed")
                continue

            if code in getattr(current_by_code, "index", []):
                row = current_by_code.loc[code]
                if isinstance(row, pd.DataFrame):
                    raise ValueError("daily attention contains duplicate securities")
                if action_condition(row):
                    project["last_condition_age"] = int(project["age_sessions"])
                    if (
                        project.get("action_price") is None
                        and project.get("pending_plan_date") is None
                    ):
                        project["pending_plan_date"] = day

            age = int(project["age_sessions"])
            if age >= config.expiry_session:
                end_project(project, day, "day_30_expiry")
            elif (
                age >= config.second_wave_exit_session
                and project.get("action_price") is not None
                and (
                    project.get("last_condition_age") is None
                    or int(project["last_condition_age"])
                    < config.second_wave_check_start
                )
            ):
                end_project(project, day, "no_second_wave_confirmation")
            elif (
                age >= config.no_confirmation_exit_session
                and project.get("action_price") is None
                and project.get("pending_plan_date") is None
            ):
                end_project(project, day, "not_confirmed_by_day_10")

        if not current_rows.empty:
            for candidate in current_rows.to_dict(orient="records"):
                code = str(candidate["ts_code"])
                if code in active or code in ended_codes:
                    continue
                if len(active) >= config.candidate_cap:
                    exclusion_rows.append(
                        {
                            "formation_date": day,
                            "ts_code": code,
                            "reason": "capacity_occupied_by_active_projects",
                        }
                    )
                    continue
                project = {
                    "project_id": f"{code}:{day.date().isoformat()}",
                    "ts_code": code,
                    "admission_date": day,
                    "admission_index": session_index,
                    "age_sessions": 0,
                    "status": "new",
                    "pending_plan_date": None,
                    "action_plan_date": None,
                    "action_date": None,
                    "entry_date": None,
                    "action_price": None,
                    "last_condition_age": None,
                    "unexecutable_attempts": 0,
                    "exit_reason": None,
                }
                active[code] = project
                if action_condition(pd.Series(candidate)):
                    project["last_condition_age"] = 0
                    project["pending_plan_date"] = day

        for project in active.values():
            snapshot_rows.append(_snapshot(project, day, active=True))

    snapshot_columns = [
        "formation_date",
        "project_id",
        "ts_code",
        "admission_date",
        "age_sessions",
        "status",
        "active",
        "action_plan_date",
        "action_date",
        "entry_date",
        "action_price",
        "last_condition_age",
        "unexecutable_attempts",
        "exit_reason",
    ]
    action_columns = [
        "project_id",
        "ts_code",
        "plan_date",
        "entry_date",
        "executable_entry",
        "action_price",
    ]
    exclusion_columns = ["formation_date", "ts_code", "reason"]
    return (
        pd.DataFrame(snapshot_rows, columns=snapshot_columns),
        pd.DataFrame(action_rows, columns=action_columns),
        pd.DataFrame(exclusion_rows, columns=exclusion_columns),
    )


def build_daily_attention(
    source_experiment_root: str | Path,
    *,
    candidate_cap: int = 10,
) -> pd.DataFrame:
    root = Path(source_experiment_root)
    evidence_paths = sorted(
        root.glob("tables/formations/block=*/formation_date=*/evidence.parquet")
    )
    if not evidence_paths:
        raise FileNotFoundError("no frozen formation evidence found")
    frames: list[pd.DataFrame] = []
    for path in evidence_paths:
        decisions = compress_decision_list(
            pd.read_parquet(path),
            candidate_cap=candidate_cap,
            focus_cap=0,
        )
        selected = decisions[decisions["user_layer"].eq("关注")].copy()
        selected["block"] = path.parent.parent.name.split("=", maxsplit=1)[1]
        frames.append(selected)
    attention = pd.concat(frames, ignore_index=True)
    attention["formation_date"] = pd.to_datetime(
        attention["formation_date"], errors="raise"
    ).dt.normalize()
    if attention.duplicated(["formation_date", "ts_code"]).any():
        raise ValueError("compressed attention contains duplicate stock-date rows")
    if attention.groupby("formation_date").size().max() > candidate_cap:
        raise ValueError("compressed attention exceeds the candidate cap")
    return attention.sort_values(["formation_date"], kind="stable").reset_index(
        drop=True
    )


def build_action_paths_for_signals(
    signals: pd.DataFrame,
    prices: pd.DataFrame,
    config: LifecycleActionConfig,
    *,
    policy: str,
) -> pd.DataFrame:
    required = {"formation_date", "ts_code"}
    missing = sorted(required - set(signals.columns))
    if missing:
        raise ValueError(f"signals lack required fields: {', '.join(missing)}")
    prepared = signals.copy()
    prepared["formation_date"] = pd.to_datetime(
        prepared["formation_date"], errors="raise"
    ).dt.normalize()
    prepared["ts_code"] = prepared["ts_code"].astype(str)
    prepared = prepared.drop_duplicates(["formation_date", "ts_code"])
    rows: list[dict[str, Any]] = []
    for signal in prepared.itertuples(index=False):
        stock_prices = prices[prices["ts_code"].astype(str).eq(str(signal.ts_code))]
        for horizon in config.horizons:
            row = compute_action_path(
                stock_prices,
                formation_date=signal.formation_date,
                ts_code=str(signal.ts_code),
                horizon=horizon,
                target_return=config.target_return,
                retention_windows=config.retention_windows,
            )
            row["policy"] = str(policy)
            rows.append(row)
    paths = pd.DataFrame(rows)
    for column in ("target_touched", "close_confirmed"):
        if column in paths:
            paths[column] = paths[column].astype("boolean")
    for window in config.retention_windows:
        column = f"retain_{window}"
        if column in paths:
            paths[column] = paths[column].astype("boolean")
    return paths


def _summary_row(
    summary: pd.DataFrame, policy: str, horizon: int
) -> pd.Series | None:
    rows = summary[
        summary["policy"].eq(policy) & summary["horizon"].eq(horizon)
    ]
    if "block" in rows and rows["block"].eq("ALL").any():
        rows = rows[rows["block"].eq("ALL")]
    if "layer" in rows and rows["layer"].eq("all").any():
        rows = rows[rows["layer"].eq("all")]
    if len(rows) != 1:
        return None
    return rows.iloc[0]


def evaluate_acceptance(
    action_summary: pd.DataFrame,
    lifecycle_summary: dict[str, float],
    quality_checks: dict[str, bool],
    config: LifecycleActionConfig,
    *,
    largest_stock_success_share: float,
) -> dict[str, Any]:
    technical_passed = bool(
        quality_checks and all(bool(value) for value in quality_checks.values())
    )
    if not technical_passed:
        return {
            "technical_passed": False,
            "lifecycle_feasibility": "technical_failure",
            "action_feasibility": "technical_failure",
        }

    mature = float(lifecycle_summary.get("mature_projects_5", 0.0))
    survived = float(lifecycle_summary.get("survived_5_projects", 0.0))
    survival_rate = survived / mature if mature else 0.0
    stability_checks = {
        "median_duration_at_least_5": float(
            lifecycle_summary.get("median_duration_sessions", 0.0)
        )
        >= 5.0,
        "survival_5_rate_at_least_30pct": survival_rate >= 0.30,
        "retention_above_daily_reset": float(
            lifecycle_summary.get("rolling_retention_rate", 0.0)
        )
        > float(lifecycle_summary.get("reset_retention_rate", 0.0)),
        "churn_at_least_25pct_lower": float(
            lifecycle_summary.get("rolling_churn_intensity", np.inf)
        )
        <= 0.75 * float(lifecycle_summary.get("reset_churn_intensity", 0.0)),
    }
    admitted_touch = float(lifecycle_summary.get("admitted_touch_30", np.nan))
    opportunity_checks = {
        "capacity_misses_not_materially_better": float(
            lifecycle_summary.get("capacity_excluded_touch_30", admitted_touch)
        )
        <= admitted_touch + 0.05,
        "day_10_exits_not_materially_better": float(
            lifecycle_summary.get("day_10_exit_touch_30", admitted_touch)
        )
        <= admitted_touch + 0.05,
    }
    if all(stability_checks.values()) and all(opportunity_checks.values()):
        lifecycle_feasibility = "supported"
    elif all(stability_checks.values()):
        lifecycle_feasibility = "stable_but_unusable"
    else:
        lifecycle_feasibility = "rejected"

    action_rows = [
        _summary_row(action_summary, "project_action", horizon)
        for horizon in config.horizons
    ]
    baseline_rows = [
        _summary_row(action_summary, "project_entry", horizon)
        for horizon in config.horizons
    ]
    if any(row is None for row in [*action_rows, *baseline_rows]):
        action_feasibility = "insufficient_evidence"
    else:
        assert all(row is not None for row in action_rows)
        assert all(row is not None for row in baseline_rows)
        executable_sample = min(
            int(row["executable_entries"]) for row in action_rows if row is not None
        )
        if executable_sample < config.minimum_executable_action_projects:
            action_feasibility = "insufficient_evidence"
        else:
            both_core_lower = any(
                float(action["touch_yield_all_plans"])
                < float(baseline["touch_yield_all_plans"])
                and float(action["close_yield_all_plans"])
                < float(baseline["close_yield_all_plans"])
                for action, baseline in zip(action_rows, baseline_rows, strict=True)
                if action is not None and baseline is not None
            )
            any_core_higher = any(
                float(action[metric]) > float(baseline[metric])
                for action, baseline in zip(action_rows, baseline_rows, strict=True)
                if action is not None and baseline is not None
                for metric in ("touch_yield_all_plans", "close_yield_all_plans")
            )
            retention_worse_both = all(
                float(action["retain_3_yield_all_plans"])
                < float(baseline["retain_3_yield_all_plans"])
                for action, baseline in zip(action_rows, baseline_rows, strict=True)
                if action is not None and baseline is not None
            )
            risk_worse_both = all(
                float(action["median_window_min_return"])
                < float(baseline["median_window_min_return"])
                for action, baseline in zip(action_rows, baseline_rows, strict=True)
                if action is not None and baseline is not None
            )
            concentrated = largest_stock_success_share >= 0.40
            if both_core_lower or (retention_worse_both and risk_worse_both):
                action_feasibility = "rejected"
            elif concentrated or not any_core_higher:
                action_feasibility = "insufficient_evidence"
            else:
                action_feasibility = "supported"

    return {
        "technical_passed": technical_passed,
        "lifecycle_feasibility": lifecycle_feasibility,
        "action_feasibility": action_feasibility,
        "lifecycle_checks": {**stability_checks, **opportunity_checks},
        "largest_stock_success_share": float(largest_stock_success_share),
    }


def apply_post_run_safety_audit(
    acceptance: dict[str, Any],
    snapshots: pd.DataFrame,
    project_entry_paths: pd.DataFrame,
) -> dict[str, Any]:
    """Veto a lifecycle result when an entry gate is misused as an exit rule.

    This audit is deliberately reported as post-run evidence. It does not
    pretend to be part of the original pre-registration and never changes the
    action-confirmation result.
    """

    result = dict(acceptance)
    result["pre_registered_lifecycle_feasibility"] = acceptance.get(
        "lifecycle_feasibility"
    )
    terminals = snapshots.sort_values("formation_date").drop_duplicates(
        "project_id", keep="last"
    )
    hard = terminals[terminals["exit_reason"].eq("hard_invalidation")][
        ["project_id", "ts_code", "formation_date"]
    ]
    paths = project_entry_paths[project_entry_paths["horizon"].eq(30)][
        ["project_id", "ts_code", "target_touched", "first_touch_date"]
    ]
    audit = hard.merge(paths, on=["project_id", "ts_code"], how="left")
    later = (
        audit["target_touched"].fillna(False).astype(bool)
        & (
            pd.to_datetime(audit["first_touch_date"], errors="coerce")
            > pd.to_datetime(audit["formation_date"], errors="coerce")
        )
    )
    hard_count = int(len(audit))
    later_count = int(later.sum())
    later_rate = float(later_count / hard_count) if hard_count else 0.0
    material_misclassification = bool(later_count >= 3 and later_rate >= 0.20)
    result["post_run_safety_audit"] = {
        "audit_was_pre_registered": False,
        "hard_exit_count": hard_count,
        "hard_exit_later_touch_count": later_count,
        "hard_exit_later_touch_rate": later_rate,
        "material_entry_exit_conflation": material_misclassification,
        "reason": (
            "价格透支等新行动限制被误用为旧项目硬失效，退出后仍有大量对象达到目标"
            if material_misclassification
            else "未发现足以否决生命周期的行动限制与项目失效混用"
        ),
    }
    if material_misclassification:
        result["lifecycle_feasibility"] = "rejected"
    return result


def _pct(value: Any) -> str:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return "—" if pd.isna(numeric) else f"{float(numeric) * 100:.2f}%"


def _action_report_table(summary: pd.DataFrame) -> str:
    rows = summary[
        summary["policy"].isin(["project_entry", "project_action"])
    ].copy()
    if "block" in rows:
        all_rows = rows[rows["block"].eq("ALL")]
        if not all_rows.empty:
            rows = all_rows
    if "layer" in rows:
        all_rows = rows[rows["layer"].eq("all")]
        if not all_rows.empty:
            rows = all_rows
    labels = {"project_entry": "全部新项目", "project_action": "行动条件已出现"}
    lines = [
        "| 对象 | 观察窗口 | 计划数 | 可执行数 | 盘中达到+20% | 收盘达到+20% | 连续3日保持 | 最低收益中位 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows.sort_values(["horizon", "policy"]).itertuples(index=False):
        lines.append(
            "| "
            + " | ".join(
                [
                    labels.get(str(row.policy), str(row.policy)),
                    f"{int(row.horizon)}个交易日内",
                    str(int(row.planned_actions)),
                    str(int(row.executable_entries)),
                    _pct(row.touch_yield_all_plans),
                    _pct(row.close_yield_all_plans),
                    _pct(row.retain_3_yield_all_plans),
                    _pct(row.median_window_min_return),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def generate_report(
    action_summary: pd.DataFrame,
    lifecycle_summary: dict[str, float],
    acceptance: dict[str, Any],
    quality_checks: dict[str, bool],
    cases: pd.DataFrame,
    path: str | Path,
) -> Path:
    output = Path(path)
    case_lines = [
        "| 类型 | 股票 | 形成日 | 说明 |",
        "| --- | --- | --- | --- |",
    ]
    if cases.empty:
        case_lines.append("| — | — | — | 没有对应案例 |")
    else:
        for row in cases.itertuples(index=False):
            case_lines.append(
                f"| {row.case_type} | {row.ts_code} | "
                f"{pd.Timestamp(row.formation_date).date()} | {row.detail} |"
            )
    status_cn = {
        "supported": "支持保留",
        "rejected": "不支持使用",
        "insufficient_evidence": "证据不足",
        "stable_but_unusable": "稳定但不可用",
        "technical_failure": "技术失败",
    }
    safety = acceptance.get("post_run_safety_audit", {})
    safety_lines = []
    if safety:
        safety_lines = [
            "",
            "## 2. 自动验收以后发现的安全反证",
            "",
            f"预登记检查原本把生命周期判为 `{acceptance.get('pre_registered_lifecycle_feasibility')}`，但独立安全审计发现：{int(safety.get('hard_exit_count', 0))} 个硬失效退出中，有 {int(safety.get('hard_exit_later_touch_count', 0))} 个是在退出以后才达到 +20%，占 {_pct(safety.get('hard_exit_later_touch_rate'))}。",
            "",
            "根因是当前 `hard_invalid` 同时包含价格涨得过快、位置过高等‘不适合从今天新买’的限制，却被生命周期误当成‘原项目逻辑已经失效’。行动限制和项目失效不能共用一个退出开关。因此最终评估否决生命周期通过结论，但不改变行动确认的独立结果。",
        ]
    lines = [
        "# 股票分析助手 V3：持续关注与行动确认留出验证结果",
        "",
        "> 留出形成日固定为 2025-12-11 至 2026-01-23，共 30 个连续交易日。规则在读取本区间未来结果以前冻结。",
        "",
        "## 1. 先说结论",
        "",
        f"- 技术检查：{'通过' if acceptance.get('technical_passed') else '失败'}；",
        f"- 生命周期：{status_cn.get(str(acceptance.get('lifecycle_feasibility')), str(acceptance.get('lifecycle_feasibility', '—')))}；",
        f"- 行动确认：{status_cn.get(str(acceptance.get('action_feasibility')), str(acceptance.get('action_feasibility', '—')))}。",
        "",
        "这里的20个交易日内和30个交易日内，是从次日开盘行动价开始，在整个窗口内任意一天达到目标；不是只检查第20个交易日当天或第30个交易日当天。",
        *safety_lines,
        "",
        "## 3. 行动结果",
        "",
        _action_report_table(action_summary),
        "",
        "## 4. 名单是否真正稳定",
        "",
        f"- 项目存续中位：{lifecycle_summary.get('median_duration_sessions', float('nan')):.2f} 个交易日；",
        f"- 相邻日滚动名单保留率：{_pct(lifecycle_summary.get('rolling_retention_rate'))}；每日重置对照：{_pct(lifecycle_summary.get('reset_retention_rate'))}；",
        f"- 滚动换手强度：{lifecycle_summary.get('rolling_churn_intensity', float('nan')):.3f}；每日重置对照：{lifecycle_summary.get('reset_churn_intensity', float('nan')):.3f}；",
        f"- 容量遗漏对象30日达到率：{_pct(lifecycle_summary.get('capacity_excluded_touch_30'))}；已接纳项目：{_pct(lifecycle_summary.get('admitted_touch_30'))}；",
        f"- 第10日退出对象后来30日达到率：{_pct(lifecycle_summary.get('day_10_exit_touch_30'))}。",
        "",
        "## 5. 失败和遗漏案例",
        "",
        *case_lines,
        "",
        "## 6. 技术与方法边界",
        "",
        f"质量检查通过 {sum(bool(value) for value in quality_checks.values())}/{len(quality_checks)} 项。",
        "本实验没有交易成本、仓位和正式退出成交规则，不能证明正式买入或卖出能力，也不能把盘中达到率写成用户实际收益率。",
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output


def _source_signatures(config: LifecycleActionConfig) -> dict[str, Any]:
    return {
        "warehouse": _tree_signature(config.warehouse_root),
        "development_compression": _tree_signature(
            config.development_compression_root
        ),
    }


def preflight(config: LifecycleActionConfig) -> dict[str, Any]:
    output = prepare_output_root(config)
    sessions = available_sessions(config.warehouse_root)
    holdout_sessions = [
        session
        for session in sessions
        if pd.Timestamp(config.holdout.start)
        <= session
        <= pd.Timestamp(config.holdout.end)
    ]
    end_position = sessions.index(pd.Timestamp(config.holdout.end))
    future_sessions = len(sessions) - end_position - 1
    result = {
        "experiment_id": config.experiment_id,
        "holdout_id": config.holdout.id,
        "holdout_start": config.holdout.start.isoformat(),
        "holdout_end": config.holdout.end.isoformat(),
        "formation_sessions": len(holdout_sessions),
        "formation_dates": [item.date().isoformat() for item in holdout_sessions],
        "future_sessions_available": future_sessions,
        "usb_free_bytes": shutil.disk_usage(output).free,
        "output_root": str(output),
    }
    if len(holdout_sessions) != config.formation_sessions:
        raise RuntimeError("留出区间不是冻结的30个交易日")
    if future_sessions < max(config.horizons) + max(config.retention_windows):
        raise RuntimeError("留出区间缺少完整行动与保持窗口")
    _write_json(result, output / "manifests" / "preflight.json")
    signature_path = output / "manifests" / "source_signatures_before.json"
    if not signature_path.exists():
        _write_json(_source_signatures(config), signature_path)
    return result


def _layered_config(config: LifecycleActionConfig) -> LayeredValidationConfig:
    return LayeredValidationConfig(
        experiment_id=config.experiment_id,
        warehouse_root=config.warehouse_root,
        output_root=config.output_root,
        blocks=(
            LayeredBlock(
                id=config.holdout.id,
                start=config.holdout.start,
                end=config.holdout.end,
            ),
        ),
        horizons=(10, 20, 30),
        target_return=config.target_return,
        candidate_cap=config.candidate_cap,
        focus_cap=5,
        route_recall_cap=30,
        supported_routes=("hotspot", "earnings", "price"),
        not_testable_routes=(
            "company_event",
            "industry_cycle",
            "distress_repair",
        ),
        runtime_soft_hours=config.runtime_stop_hours * 0.75,
        runtime_stop_hours=config.runtime_stop_hours,
        usb_soft_bytes=3 * 1024**3,
    )


def _price_safety(return_20d: Any, location_60d: Any) -> int:
    ret = pd.to_numeric(pd.Series([return_20d]), errors="coerce").iloc[0]
    loc = pd.to_numeric(pd.Series([location_60d]), errors="coerce").iloc[0]
    if pd.notna(ret) and pd.notna(loc) and 0 <= ret <= 0.20 and loc <= 0.90:
        return 3
    if pd.notna(ret) and pd.notna(loc) and ret <= 0.40 and loc < 0.99:
        return 2
    return 1


def build_daily_project_facts(
    source_experiment_root: str | Path,
    attention: pd.DataFrame,
) -> pd.DataFrame:
    root = Path(source_experiment_root)
    codes = sorted(attention["ts_code"].astype(str).unique())
    rows: list[dict[str, Any]] = []
    for stock_path in sorted(
        root.glob("tables/formations/block=*/formation_date=*/stocks.parquet")
    ):
        day = pd.Timestamp(stock_path.parent.name.split("=", maxsplit=1)[1])
        market_path = stock_path.parent / "market.parquet"
        stocks = pd.read_parquet(stock_path)
        stocks["ts_code"] = stocks["ts_code"].astype(str)
        current = stocks[stocks["ts_code"].isin(codes)].set_index("ts_code")
        market = pd.read_parquet(market_path)
        breadth = float(pd.to_numeric(market["breadth_20d"], errors="coerce").iloc[0])
        for code in codes:
            if code not in current.index:
                rows.append(
                    {
                        "formation_date": day,
                        "ts_code": code,
                        "hard_invalid": True,
                    }
                )
                continue
            stock = current.loc[code]
            if isinstance(stock, pd.DataFrame):
                raise ValueError("stock facts contain duplicate securities")
            average_amount = pd.to_numeric(
                pd.Series([stock.get("average_amount_20d")]), errors="coerce"
            ).iloc[0]
            return_5d = pd.to_numeric(
                pd.Series([stock.get("return_5d")]), errors="coerce"
            ).iloc[0]
            location = pd.to_numeric(
                pd.Series([stock.get("price_location_60d")]), errors="coerce"
            ).iloc[0]
            safety = _price_safety(stock.get("return_20d"), location)
            hard_invalid = bool(
                pd.isna(average_amount)
                or float(average_amount) < 20000.0
                or (pd.notna(return_5d) and float(return_5d) > 0.30)
                or (pd.notna(location) and float(location) >= 0.995)
                or (np.isfinite(breadth) and breadth < 0.45 and safety < 2)
            )
            rows.append(
                {
                    "formation_date": day,
                    "ts_code": code,
                    "hard_invalid": hard_invalid,
                }
            )
    return pd.DataFrame(rows)


def form_holdout(config: LifecycleActionConfig) -> Path:
    started = time.perf_counter()
    preflight(config)
    output = prepare_output_root(config)
    run_blocks(_layered_config(config), [config.holdout.id])
    attention = build_daily_attention(output, candidate_cap=config.candidate_cap)
    if attention["formation_date"].nunique() != config.formation_sessions:
        raise RuntimeError("形成阶段没有得到30个关注名单日期")
    signals = attention[
        attention.apply(action_condition, axis=1)
    ].copy()
    facts = build_daily_project_facts(output, attention)
    _write_parquet(attention, output / "tables" / "daily_attention.parquet")
    _write_parquet(signals, output / "tables" / "planned_action_signals.parquet")
    _write_parquet(facts, output / "tables" / "daily_project_facts.parquet")
    before = json.loads(
        (output / "manifests" / "source_signatures_before.json").read_text(
            encoding="utf-8"
        )
    )
    after = _source_signatures(config)
    _write_json(after, output / "manifests" / "source_signatures_after_form.json")
    status = {
        "status": "formed_without_future_action_outcomes",
        "formation_dates": int(attention["formation_date"].nunique()),
        "attention_rows": int(len(attention)),
        "planned_action_signal_rows": int(len(signals)),
        "source_unchanged": before == after,
        "runtime_seconds": time.perf_counter() - started,
    }
    _write_json(status, output / "manifests" / "formation_status.json")
    return output


def _churn_and_retention(sets_by_day: list[set[str]]) -> tuple[float, float]:
    churn: list[float] = []
    retention: list[float] = []
    for previous, current in zip(sets_by_day, sets_by_day[1:], strict=False):
        denominator = max(len(previous), 1)
        churn.append((len(current - previous) + len(previous - current)) / denominator)
        retention.append(len(previous & current) / denominator)
    return (
        float(np.mean(churn)) if churn else np.nan,
        float(np.mean(retention)) if retention else np.nan,
    )


def _touch_rate(paths: pd.DataFrame, horizon: int = 30) -> float:
    sample = paths[
        paths["horizon"].eq(horizon)
        & paths["complete_horizon"].fillna(False).astype(bool)
    ]
    if sample.empty:
        return np.nan
    executable = sample["executable_entry"].fillna(False).astype(bool)
    touched = sample["target_touched"].fillna(False).astype(bool)
    return float((executable & touched).sum() / len(sample))


def summarize_lifecycle(
    snapshots: pd.DataFrame,
    attention: pd.DataFrame,
    exclusions: pd.DataFrame,
    project_entry_paths: pd.DataFrame,
    exclusion_paths: pd.DataFrame,
    sessions: pd.Index,
) -> dict[str, float]:
    ordered_sessions = list(pd.to_datetime(sessions).normalize())
    session_position = {day: index for index, day in enumerate(ordered_sessions)}
    project_last = snapshots.sort_values("formation_date").drop_duplicates(
        "project_id", keep="last"
    )
    eligible = project_last[
        ~project_last["exit_reason"].isin(["target_completed", "hard_invalidation"])
    ].copy()
    durations = eligible["age_sessions"].astype(float)
    mature_mask = eligible["admission_date"].map(
        lambda day: len(ordered_sessions) - 1 - session_position[pd.Timestamp(day)] >= 5
    )
    mature = eligible[mature_mask]
    survived = mature[mature["age_sessions"].ge(5)]

    active_sets = [
        set(
            snapshots[
                snapshots["formation_date"].eq(day) & snapshots["active"].astype(bool)
            ]["ts_code"].astype(str)
        )
        for day in ordered_sessions
    ]
    reset_sets = [
        set(attention[attention["formation_date"].eq(day)]["ts_code"].astype(str))
        for day in ordered_sessions
    ]
    rolling_churn, rolling_retention = _churn_and_retention(active_sets)
    reset_churn, reset_retention = _churn_and_retention(reset_sets)
    admitted_touch = _touch_rate(project_entry_paths, 30)
    excluded_touch = _touch_rate(exclusion_paths, 30)
    if not np.isfinite(excluded_touch):
        excluded_touch = admitted_touch
    day_10_ids = set(
        project_last[
            project_last["exit_reason"].eq("not_confirmed_by_day_10")
        ]["project_id"]
    )
    day_10_paths = project_entry_paths[
        project_entry_paths.get("project_id", pd.Series(dtype=str)).isin(day_10_ids)
    ]
    day_10_touch = _touch_rate(day_10_paths, 30)
    if not np.isfinite(day_10_touch):
        day_10_touch = admitted_touch
    return {
        "project_count": float(snapshots["project_id"].nunique()),
        "median_duration_sessions": float(durations.median()) if len(durations) else np.nan,
        "mature_projects_5": float(len(mature)),
        "survived_5_projects": float(len(survived)),
        "rolling_retention_rate": rolling_retention,
        "reset_retention_rate": reset_retention,
        "rolling_churn_intensity": rolling_churn,
        "reset_churn_intensity": reset_churn,
        "admitted_touch_30": admitted_touch,
        "capacity_excluded_touch_30": excluded_touch,
        "day_10_exit_touch_30": day_10_touch,
        "capacity_exclusion_rows": float(len(exclusions)),
    }


def _case_studies(
    snapshots: pd.DataFrame,
    entry_paths: pd.DataFrame,
    exclusions: pd.DataFrame,
    exclusion_paths: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    terminals = snapshots.sort_values("formation_date").drop_duplicates(
        "project_id", keep="last"
    )
    day_10 = terminals[
        terminals["exit_reason"].eq("not_confirmed_by_day_10")
    ][["project_id", "ts_code", "admission_date"]]
    winners = entry_paths[
        entry_paths["horizon"].eq(30)
        & entry_paths["executable_entry"].fillna(False).astype(bool)
        & entry_paths["target_touched"].fillna(False).astype(bool)
    ]
    hard_exits = terminals[terminals["exit_reason"].eq("hard_invalidation")][
        ["project_id", "ts_code", "formation_date", "admission_date"]
    ]
    hard_later_winners = hard_exits.merge(
        winners[["project_id", "ts_code", "first_touch_date"]],
        on=["project_id", "ts_code"],
        how="inner",
    )
    hard_later_winners = hard_later_winners[
        pd.to_datetime(hard_later_winners["first_touch_date"], errors="coerce")
        > pd.to_datetime(hard_later_winners["formation_date"], errors="coerce")
    ]
    for item in hard_later_winners.head(20).itertuples():
        rows.append(
            {
                "case_type": "hard_exit_later_winner",
                "ts_code": item.ts_code,
                "formation_date": item.admission_date,
                "detail": "被价格等新行动限制判为硬失效退出，但退出后才在30个交易日内达到+20%",
            }
        )
    for item in day_10.merge(winners, on=["project_id", "ts_code"], how="inner").itertuples():
        rows.append(
            {
                "case_type": "day_10_early_exit_winner",
                "ts_code": item.ts_code,
                "formation_date": item.admission_date,
                "detail": "第10日未确认退出，但从最初次日开盘价出发在30个交易日内后来达到+20%",
            }
        )
    if not exclusions.empty and not exclusion_paths.empty:
        missed = exclusion_paths[
            exclusion_paths["horizon"].eq(30)
            & exclusion_paths["executable_entry"].fillna(False).astype(bool)
            & exclusion_paths["target_touched"].fillna(False).astype(bool)
        ]
        for item in missed.head(20).itertuples():
            rows.append(
                {
                    "case_type": "capacity_excluded_winner",
                    "ts_code": item.ts_code,
                    "formation_date": item.formation_date,
                    "detail": "因旧项目占位未进入持续关注名单，随后30个交易日内达到+20%",
                }
            )
    return pd.DataFrame(
        rows, columns=["case_type", "ts_code", "formation_date", "detail"]
    )


def evaluate_holdout(config: LifecycleActionConfig) -> Path:
    started = time.perf_counter()
    output = prepare_output_root(config)
    formation_status = output / "manifests" / "formation_status.json"
    if not formation_status.exists():
        raise RuntimeError("必须先完成形成阶段再揭示未来路径")
    attention = pd.read_parquet(output / "tables" / "daily_attention.parquet")
    signals = pd.read_parquet(output / "tables" / "planned_action_signals.parquet")
    facts = pd.read_parquet(output / "tables" / "daily_project_facts.parquet")
    attention["formation_date"] = pd.to_datetime(attention["formation_date"]).dt.normalize()
    signals["formation_date"] = pd.to_datetime(signals["formation_date"]).dt.normalize()
    prices, price_inputs = _read_action_price_frame(config, attention["formation_date"])
    daily_paths = build_action_paths_for_signals(
        attention, prices, config, policy="daily_attention"
    )
    signal_paths = build_action_paths_for_signals(
        signals, prices, config, policy="action_condition"
    )
    execution_rows = signal_paths[signal_paths["horizon"].eq(20)][
        [
            "formation_date",
            "entry_date",
            "ts_code",
            "executable_entry",
            "action_price",
        ]
    ].rename(columns={"formation_date": "plan_date"})
    sessions = pd.Index(sorted(attention["formation_date"].unique()))
    state_prices = prices[prices["trade_date"].isin(sessions)][
        ["trade_date", "ts_code", "adj_high"]
    ]
    snapshots, actions, exclusions = simulate_lifecycle(
        attention,
        facts,
        execution_rows,
        state_prices,
        sessions,
        config,
    )
    entries = snapshots.sort_values("formation_date").drop_duplicates(
        "project_id", keep="first"
    )[["project_id", "ts_code", "admission_date"]].rename(
        columns={"admission_date": "formation_date"}
    )
    entry_paths = build_action_paths_for_signals(
        entries, prices, config, policy="project_entry"
    ).merge(entries, on=["formation_date", "ts_code"], how="left")
    action_signals = actions[["project_id", "ts_code", "plan_date"]].rename(
        columns={"plan_date": "formation_date"}
    )
    action_paths = build_action_paths_for_signals(
        action_signals, prices, config, policy="project_action"
    ).merge(action_signals, on=["formation_date", "ts_code"], how="left")
    if exclusions.empty:
        exclusion_paths = pd.DataFrame(columns=entry_paths.columns)
    else:
        exclusion_signals = exclusions.rename(
            columns={"formation_date": "formation_date"}
        )[["formation_date", "ts_code"]].drop_duplicates()
        exclusion_paths = build_action_paths_for_signals(
            exclusion_signals, prices, config, policy="capacity_excluded"
        )
    all_paths = pd.concat(
        [daily_paths, signal_paths, entry_paths, action_paths, exclusion_paths],
        ignore_index=True,
        sort=False,
    )
    all_paths["block"] = config.holdout.id
    all_paths["layer"] = "all"
    summary = summarize_actions(
        all_paths,
        retention_windows=config.retention_windows,
    )
    lifecycle = summarize_lifecycle(
        snapshots,
        attention,
        exclusions,
        entry_paths,
        exclusion_paths,
        sessions,
    )
    contracts = validate_action_contracts(
        all_paths, retention_windows=config.retention_windows
    )
    before = json.loads(
        (output / "manifests" / "source_signatures_before.json").read_text(
            encoding="utf-8"
        )
    )
    after = _source_signatures(config)
    banned_future = {
        "target_touched",
        "close_confirmed",
        "window_min_return",
        "terminal_return",
    }
    quality = {
        "dates_30": attention["formation_date"].nunique() == 30,
        "formation_files_30": len(
            list(output.glob("tables/formations/block=D/formation_date=*/evidence.parquet"))
        )
        == 30,
        "daily_cap": attention.groupby("formation_date").size().max()
        <= config.candidate_cap,
        "single_user_layer": set(attention["user_layer"].unique()) == {"关注"},
        "no_duplicate_projects": snapshots.groupby("project_id")["ts_code"].nunique().max()
        == 1,
        "project_daily_cap": snapshots[
            snapshots["active"].astype(bool)
        ].groupby("formation_date").size().max()
        <= config.candidate_cap,
        "formation_has_no_future_results": not bool(
            banned_future & set(attention.columns)
        ),
        "source_unchanged": before == after,
        "runtime_within_limit": time.perf_counter() - started
        <= config.runtime_stop_hours * 3600,
        **contracts,
    }
    success = action_paths[
        action_paths["horizon"].eq(30)
        & action_paths["executable_entry"].fillna(False).astype(bool)
        & action_paths["target_touched"].fillna(False).astype(bool)
    ]
    largest_share = (
        float(success["ts_code"].value_counts().max() / len(success))
        if len(success)
        else 0.0
    )
    acceptance = evaluate_acceptance(
        summary,
        lifecycle,
        quality,
        config,
        largest_stock_success_share=largest_share,
    )
    acceptance = apply_post_run_safety_audit(
        acceptance,
        snapshots,
        entry_paths,
    )
    cases = _case_studies(snapshots, entry_paths, exclusions, exclusion_paths)
    _write_parquet(snapshots, output / "tables" / "project_snapshots.parquet")
    _write_parquet(actions, output / "tables" / "project_actions.parquet")
    _write_parquet(exclusions, output / "tables" / "capacity_exclusions.parquet")
    _write_parquet(all_paths, output / "tables" / "action_paths.parquet")
    _write_parquet(summary, output / "tables" / "action_summary.parquet")
    _write_parquet(pd.DataFrame([lifecycle]), output / "tables" / "lifecycle_summary.parquet")
    _write_parquet(cases, output / "tables" / "case_studies.parquet")
    _write_json(quality, output / "manifests" / "quality_checks.json")
    _write_json(acceptance, output / "manifests" / "acceptance_checks.json")
    _write_json(after, output / "manifests" / "source_signatures_after.json")
    _write_json(
        [{"path": str(path)} for path in price_inputs],
        output / "manifests" / "price_input_manifest.json",
    )
    report = generate_report(
        summary,
        lifecycle,
        acceptance,
        quality,
        cases,
        output / "reports" / "v3-lifecycle-action-validation-results.md",
    )
    _write_json(
        {
            "status": "evaluated",
            "report": str(report),
            "runtime_seconds": time.perf_counter() - started,
        },
        output / "manifests" / "run_status.json",
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("preflight", "form", "evaluate"):
        command = subparsers.add_parser(name)
        command.add_argument("--config", required=True)
    args = parser.parse_args(argv)
    config = load_config(args.config)
    if args.command == "preflight":
        print(json.dumps(preflight(config), ensure_ascii=False, indent=2))
    elif args.command == "form":
        print(form_holdout(config))
    else:
        print(evaluate_holdout(config))
    return 0


if __name__ == "__main__":
    sys.exit(main())
