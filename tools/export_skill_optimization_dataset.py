#!/usr/bin/env python3
"""Export a public-safe slice of frozen A-share selection research.

The source archive and warehouse remain read-only. Formation evidence is copied or
normalized separately from post-selection monitoring and outcome prices.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd


DEFAULT_START_ACTION_DATE = "2026-08-20"
DEFAULT_END_ACTION_DATE = "2026-08-31"
DEFAULT_OUTCOME_THROUGH_DATE = "2026-08-31"
PACKAGE_VERSION = "a-share-skill-optimization-sample-v3"
LEGACY_TRACE_NAME = "regenerated-selection-2026-08-19-asof-2026-08-20T090500+0800.json"
CANONICAL_DATE_SUFFIX = re.compile(r"(\d{4}-\d{2}-\d{2})$")
FIXED_D20_STATUSES = (
    "not_applicable",
    "no_reliable_entry",
    "not_mature",
    "missing_path",
    "complete",
)
CURRENT_OBSERVATION_MAX_DAYS = 30
FIXED_D20_DAYS = 20
CLOSE_HIT_20PCT_THRESHOLD = 0.20 - 1e-12
HIGH_HIT_20PCT_THRESHOLD = 0.20
CONFIRMED_ACTIVE_ENGINES = frozenset(
    {
        "event_repricing_confirmed",
        "sector_broad_diffusion",
        "sector_leader_cluster",
        "independent_demand_acceleration",
    }
)
CONDITION_RESULTS = frozenset({"met", "not_met", "unknown"})

_ABSOLUTE_PATH_PATTERNS = (
    re.compile(r"^/Users/"),
    re.compile(r"^/home/"),
    re.compile(r"^[A-Za-z]:\\\\"),
)
_CREDENTIAL_KEY_PATTERN = re.compile(
    r"(^|_)(api_?key|access_?token|refresh_?token|password|secret|credential)s?($|_)",
    re.IGNORECASE,
)


def build_event_key(formation_date: str, ts_code: str, role: str) -> str:
    return f"formal:{formation_date}:{ts_code}:{role}"


def build_episode_id(formation_date: str, ts_code: str, role: str) -> str:
    """Monitor episode ids use the formation date: formal:<formation>:<code>:<role>."""
    return f"formal:{formation_date}:{ts_code}:{role}"


def canonical_archive_paths(directory: Path, prefix: str) -> list[Path]:
    """Return only canonical `prefix-YYYY-MM-DD.json` archive files.

    Backup copies such as `monitor-report-2026-09-08.json.pre-checkpoint-titles-
    2026-09-09.json` stay untouched on disk but are never read as inputs.
    """
    if not directory.is_dir():
        return []
    matched: list[Path] = []
    for path in sorted(directory.glob(f"{prefix}-*.json")):
        if ".pre-" in path.name:
            continue
        stem = path.name[: -len(".json")]
        if not stem.startswith(f"{prefix}-"):
            continue
        if not CANONICAL_DATE_SUFFIX.search(stem):
            continue
        matched.append(path)
    return matched


def load_trading_dates(
    warehouse_root: Path, start_date: str, end_date: str
) -> list[str]:
    """Open market days from `facts/trade_calendar`, never from price partitions."""
    base = warehouse_root / "facts" / "trade_calendar"
    rows: list[dict[str, Any]] = []
    for path in sorted(base.glob("cal_year=*/data.parquet")):
        if not path.is_file():
            continue
        frame = pd.read_parquet(path)
        rows.extend(frame.to_dict("records"))
    open_days: set[str] = set()
    for row in rows:
        if not bool(row.get("is_open")):
            continue
        cal_date = row.get("cal_date")
        day = getattr(cal_date, "isoformat", None)
        text = cal_date.isoformat() if day is not None else str(cal_date)[:10]
        if start_date <= text <= end_date:
            open_days.add(text)
    return sorted(open_days)


def build_run_id(formation_date: str, action_date: str) -> str:
    return f"formal:{formation_date}:{action_date}"


def selection_output_class(
    trace_version: str, candidate: Mapping[str, Any] | None
) -> str:
    if trace_version != "daily-research-trace-v4":
        return "legacy_v1_not_rewritten"
    thesis = candidate.get("research_thesis") if candidate else None
    thesis_map = thesis if isinstance(thesis, Mapping) else {}
    recognition = thesis_map.get("market_recognition")
    recognition_map = recognition if isinstance(recognition, Mapping) else {}
    engine_type = thesis_map.get("engine_type")
    engine_status = thesis_map.get("engine_status")
    recognition_status = recognition_map.get("status")
    if (
        engine_type in CONFIRMED_ACTIVE_ENGINES
        and engine_status == "active"
        and recognition_status == "confirmed"
    ):
        return "confirmed_active"
    if (
        engine_type == "fresh_event_pending"
        and engine_status == "conditional"
        and recognition_status == "pending"
    ):
        return "conditional_event"
    return "not_formal_candidate"


def ensure_public_safe(value: Any, *, path: str = "$", key: str | None = None) -> None:
    """Reject personal absolute paths and credential-like fields recursively."""
    if (
        key is not None
        and _CREDENTIAL_KEY_PATTERN.search(key)
        and value not in (None, "", False)
    ):
        raise ValueError(f"credential-like field at {path}: {key}")
    if isinstance(value, Mapping):
        for child_key, child_value in value.items():
            child_key_text = str(child_key)
            ensure_public_safe(
                child_value,
                path=f"{path}.{child_key_text}",
                key=child_key_text,
            )
        return
    if isinstance(value, (list, tuple)):
        for index, child_value in enumerate(value):
            ensure_public_safe(child_value, path=f"{path}[{index}]")
        return
    if isinstance(value, str) and any(
        pattern.search(value) for pattern in _ABSOLUTE_PATH_PATTERNS
    ):
        raise ValueError(f"absolute path at {path}: {value}")


def normalize_json(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return {str(key): normalize_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [normalize_json(item) for item in value]
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return None if not math.isfinite(value) else float(value)
    if hasattr(value, "item"):
        return normalize_json(value.item())
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def write_jsonl(path: Path, records: Iterable[Mapping[str, Any]]) -> int:
    normalized = [normalize_json(dict(record)) for record in records]
    ensure_public_safe(normalized)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(
        json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
        for record in normalized
    )
    path.write_text(payload, encoding="utf-8")
    return len(normalized)


def write_csv(
    path: Path,
    records: Sequence[Mapping[str, Any]],
    fieldnames: Sequence[str],
) -> int:
    normalized = [normalize_json(dict(record)) for record in records]
    ensure_public_safe(normalized)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()
        for record in normalized:
            serialized = {
                field: (
                    json.dumps(record.get(field), ensure_ascii=False, sort_keys=True)
                    if isinstance(record.get(field), (dict, list))
                    else record.get(field)
                )
                for field in fieldnames
            }
            writer.writerow(serialized)
    return len(normalized)


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path.name}")
    return payload


def discover_frozen_traces(
    selection_dir: Path,
    start_action_date: str,
    end_action_date: str,
) -> list[tuple[str, dict[str, Any]]]:
    candidates = [selection_dir / LEGACY_TRACE_NAME]
    candidates.extend(canonical_archive_paths(selection_dir, "research-trace"))
    selected: list[tuple[str, dict[str, Any]]] = []
    seen_actions: set[str] = set()
    for path in candidates:
        if not path.is_file():
            continue
        trace = load_json(path)
        action_date = str(trace.get("action_date") or "")
        if not start_action_date <= action_date <= end_action_date:
            continue
        if action_date in seen_actions:
            raise ValueError(f"duplicate canonical trace for action date {action_date}")
        seen_actions.add(action_date)
        selected.append((path.name, trace))
    selected.sort(key=lambda pair: pair[1]["action_date"])
    return selected


def extract_candidate_records(
    trace: Mapping[str, Any], trace_version: str
) -> list[dict[str, Any]]:
    formation_date = str(trace["formation_date"])
    action_date = str(trace["action_date"])
    common = {
        "run_id": build_run_id(formation_date, action_date),
        "formation_date": formation_date,
        "action_date": action_date,
        "selection_as_of": trace.get("as_of"),
        "trace_version": trace_version,
    }
    ledger = trace.get("candidate_ledger")
    if isinstance(ledger, list):
        return [
            {
                **common,
                "ts_code": row.get("ts_code"),
                "name": row.get("name"),
                "opportunity_type": row.get("opportunity_type"),
                "source_skills": row.get("source_skills") or [],
                "final_fate": row.get("final_fate"),
                "primary_reason": row.get("primary_reason"),
                "research_thesis": row.get("research_thesis"),
                "normalization_note": None,
            }
            for row in ledger
        ]
    chain = trace.get("candidate_chain") or []
    return [
        {
            **common,
            "ts_code": row.get("ts_code"),
            "name": row.get("name"),
            "opportunity_type": row.get("opportunity_type"),
            "source_skills": row.get("origins") or [],
            "final_fate": row.get("fate"),
            "primary_reason": row.get("reason"),
            "research_thesis": None,
            "normalization_note": (
                "legacy_candidate_chain; no V4 research_thesis was recorded"
            ),
        }
        for row in chain
    ]


def _trace_version(source_name: str, trace: Mapping[str, Any]) -> str:
    return str(trace.get("trace_version") or "legacy-selection-v1")


def _selected_trace_rows(trace: Mapping[str, Any]) -> list[dict[str, Any]]:
    result = trace.get("research_result") or {}
    rows = result.get("selected_stocks") or []
    if not isinstance(rows, list):
        raise ValueError("research_result.selected_stocks must be a list")
    return [dict(row) for row in rows]


def _read_selection_log(
    path: Path, start_action_date: str, end_action_date: str
) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = [dict(row) for row in csv.DictReader(handle)]
    return [
        row
        for row in rows
        if start_action_date <= row.get("action_date", "") <= end_action_date
        and row.get("final_fate") == "selected"
    ]


def build_formal_selections(
    traces: Sequence[tuple[str, Mapping[str, Any]]],
    log_rows: Sequence[Mapping[str, str]],
    mismatch_collector: list[str] | None = None,
) -> list[dict[str, Any]]:
    log_by_key = {(row["action_date"], row["ts_code"]): row for row in log_rows}
    traced_log_keys: set[tuple[str, str]] = set()
    conditional_log_keys: set[tuple[str, str]] = set()
    records: list[dict[str, Any]] = []
    for source_name, trace in traces:
        formation_date = str(trace["formation_date"])
        action_date = str(trace["action_date"])
        version = _trace_version(source_name, trace)
        candidate_by_code = {
            str(row.get("ts_code")): row
            for row in trace.get("candidate_ledger") or []
            if isinstance(row, Mapping)
        }
        for selected in _selected_trace_rows(trace):
            key = (action_date, str(selected["ts_code"]))
            derived_class = selection_output_class(
                version, candidate_by_code.get(str(selected["ts_code"]))
            )
            if derived_class not in {
                "confirmed_active",
                "legacy_v1_not_rewritten",
            }:
                # Conditional event leads are not formal recommendations; since the
                # September contract they never enter the formal log either.
                conditional_log_keys.add(key)
                continue
            if key not in log_by_key:
                raise ValueError(f"selection missing from formal log: {key}")
            traced_log_keys.add(key)
            logged = log_by_key[key]
            comparisons = {
                "name": selected.get("name"),
                "selection_reason": selected.get("selection_reason"),
                "strongest_counterevidence": selected.get("strongest_counterevidence"),
                "nearest_comparison": selected.get("nearest_comparison"),
            }
            mismatched_fields = [
                field
                for field, expected in comparisons.items()
                if str(logged.get(field) or "") != str(expected or "")
            ]
            if mismatched_fields and version != "legacy-selection-v1":
                if mismatch_collector is None:
                    raise ValueError(
                        f"trace/log mismatch for {key}: {', '.join(mismatched_fields)}"
                    )
                mismatch_collector.append(
                    f"{action_date} {selected['ts_code']}: {', '.join(mismatched_fields)}"
                )
            output_class = derived_class
            records.append(
                {
                    "event_key": build_event_key(
                        formation_date, str(selected["ts_code"]), "selected"
                    ),
                    "run_id": build_run_id(formation_date, action_date),
                    "formation_date": formation_date,
                    "action_date": action_date,
                    "selection_as_of": trace.get("as_of"),
                    "trace_version": version,
                    "selection_output_class": output_class,
                    "priority": selected.get("priority"),
                    "ts_code": selected.get("ts_code"),
                    "name": selected.get("name"),
                    "opportunity_type": selected.get("opportunity_type"),
                    "selection_reason": logged.get("selection_reason") or None,
                    "strongest_counterevidence": logged.get(
                        "strongest_counterevidence"
                    )
                    or None,
                    "nearest_comparison": logged.get("nearest_comparison") or None,
                    "formal_reason_source": "forward-selection-log",
                    "trace_log_text_match": not mismatched_fields,
                    "trace_selection_reason": selected.get("selection_reason"),
                    "trace_strongest_counterevidence": selected.get(
                        "strongest_counterevidence"
                    ),
                    "trace_nearest_comparison": selected.get("nearest_comparison"),
                    "current_day_at_export": _optional_int(logged.get("current_day")),
                    "current_close_return_at_export": _optional_float(
                        logged.get("current_close_return")
                    ),
                    "max_close_return_so_far_at_export": _optional_float(
                        logged.get("max_close_return_so_far")
                    ),
                    "hit_20pct_close_within_20d_at_export": _optional_bool(
                        logged.get("hit_20pct_close_within_20d")
                    ),
                    "first_hit_day_at_export": _optional_int(logged.get("first_hit_day")),
                    "terminal_return_20d_at_export": _optional_float(
                        logged.get("terminal_return_20d")
                    ),
                    "validation_mode": logged.get("validation_mode") or None,
                }
            )
    if set(log_by_key) - traced_log_keys - conditional_log_keys:
        missing = sorted(set(log_by_key) - traced_log_keys - conditional_log_keys)
        raise ValueError(f"formal log selections missing from traces: {missing}")
    return sorted(
        records,
        key=lambda row: (
            row["action_date"],
            row["priority"] if row["priority"] is not None else 999,
            row["ts_code"],
        ),
    )


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(float(value))


def _optional_bool(value: Any) -> bool | None:
    if value in (None, ""):
        return None
    return str(value).strip().lower() in {"true", "1", "yes"}


def build_review_contracts(candidates: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for candidate in candidates:
        thesis = candidate.get("research_thesis")
        thesis_map = thesis if isinstance(thesis, Mapping) else {}
        recognition = thesis_map.get("market_recognition")
        recognition_map = recognition if isinstance(recognition, Mapping) else {}
        company_information = thesis_map.get("company_information")
        company_map = (
            company_information if isinstance(company_information, Mapping) else {}
        )
        role = "selected" if candidate.get("final_fate") == "selected" else "candidate"
        records.append(
            {
                "candidate_key": build_event_key(
                    str(candidate["formation_date"]), str(candidate["ts_code"]), role
                ),
                "run_id": candidate.get("run_id"),
                "formation_date": candidate.get("formation_date"),
                "action_date": candidate.get("action_date"),
                "selection_as_of": candidate.get("selection_as_of"),
                "ts_code": candidate.get("ts_code"),
                "name": candidate.get("name"),
                "final_fate": candidate.get("final_fate"),
                "engine_type": thesis_map.get("engine_type"),
                "engine_status": thesis_map.get("engine_status"),
                "market_recognition_status": recognition_map.get("status"),
                "market_recognition_basis": recognition_map.get("basis"),
                "event_id": company_map.get("event_id"),
                "event_available_at": company_map.get("event_available_at"),
                "catalyst": thesis_map.get("catalyst"),
                "short_term_engine": thesis_map.get("short_term_engine"),
                "propagation": thesis_map.get("propagation"),
                "price_confirmation": thesis_map.get("price_confirmation"),
                "remaining_path": thesis_map.get("remaining_path"),
                "fundamental_anchor": thesis_map.get("fundamental_anchor"),
                "company_risk": thesis_map.get("company_risk"),
                "critical_unknown": thesis_map.get("critical_unknown"),
                "action_condition_decision_id": thesis_map.get(
                    "action_condition_decision_id"
                ),
                "decision_ids": thesis_map.get("decision_ids") or [],
                "research_thesis": thesis,
                "normalization_note": candidate.get("normalization_note"),
            }
        )
    return records


def build_decision_records(
    traces: Sequence[tuple[str, Mapping[str, Any]]]
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for source_name, trace in traces:
        common = {
            "run_id": build_run_id(str(trace["formation_date"]), str(trace["action_date"])),
            "formation_date": trace["formation_date"],
            "action_date": trace["action_date"],
            "selection_as_of": trace.get("as_of"),
            "trace_version": _trace_version(source_name, trace),
        }
        for row in trace.get("decision_trace") or []:
            records.append({**common, **dict(row)})
    return records


def build_research_run_records(
    traces: Sequence[tuple[str, Mapping[str, Any]]],
    selection_dir: Path | None = None,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for source_name, trace in traces:
        action_date = str(trace["action_date"])
        context: dict[str, Any] | None = None
        version_status = "unknown"
        version_missing_reason: str | None = "research_run_context_file_missing"
        if selection_dir is not None:
            context_path = selection_dir / f"research-run-context-{action_date}.json"
            if context_path.is_file():
                try:
                    payload = json.loads(context_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    payload = None
                if isinstance(payload, dict):
                    file_action = str(payload.get("action_date") or "")
                    file_run_id = payload.get("run_id")
                    if file_action and file_action != action_date:
                        version_missing_reason = "research_run_context_action_date_mismatch"
                    elif file_run_id and str(file_run_id) != build_run_id(
                        str(trace["formation_date"]), action_date
                    ):
                        version_missing_reason = "research_run_context_run_id_mismatch"
                    else:
                        context = payload
                        raw_status = str(payload.get("version_status") or "")
                        version_status = (
                            raw_status
                            if raw_status in {
                                "recorded_at_run", "uncommitted_method_changes",
                            }
                            else "unknown"
                        )
                        if version_status == "unknown":
                            version_missing_reason = (
                                None if raw_status else "research_run_context_status_unknown"
                            )
                        else:
                            version_missing_reason = None
        records.append(
            {
                "run_id": build_run_id(str(trace["formation_date"]), action_date),
                "logical_source_id": f"frozen-selection/{trace['formation_date']}",
                "trace_version": _trace_version(source_name, trace),
                "source_file": source_name,
                "formation_date": trace["formation_date"],
                "action_date": action_date,
                "selection_as_of": trace.get("as_of"),
                "research_run_context": context,
                "version_status": version_status,
                "version_missing_reason": version_missing_reason,
                "trace_payload": dict(trace),
            }
        )
    return records


def load_latest_monitor_snapshot(
    monitor_dir: Path, outcome_through_date: str
) -> tuple[dict[str, Any], str, str]:
    eligible: list[tuple[str, Path]] = []
    for path in canonical_archive_paths(monitor_dir, "snapshot"):
        analysis_date = path.stem.removeprefix("snapshot-")
        if analysis_date <= outcome_through_date:
            eligible.append((analysis_date, path))
    if not eligible:
        return {}, "", ""
    analysis_date, path = sorted(eligible)[-1]
    return load_json(path), analysis_date, path.name


def build_monitor_records(
    monitor_dir: Path,
    start_action_date: str,
    end_action_date: str,
    outcome_through_date: str,
    valid_episode_ids: set[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    snapshot, snapshot_analysis_date, snapshot_source = load_latest_monitor_snapshot(
        monitor_dir, outcome_through_date
    )
    episodes = [
        dict(row)
        for row in snapshot.get("episodes") or []
        if row.get("source_type") == "formal"
        and start_action_date <= str(row.get("action_date") or "") <= end_action_date
    ]
    for episode in episodes:
        episode["snapshot_analysis_date"] = snapshot_analysis_date
        episode["snapshot_as_of"] = snapshot.get("as_of")
        episode["source_file"] = snapshot_source
    if valid_episode_ids is None:
        valid_episode_ids = {str(row["episode_id"]) for row in episodes}
    alerts: list[dict[str, Any]] = []
    reviews: list[dict[str, Any]] = []
    for path in canonical_archive_paths(monitor_dir, "monitor-report"):
        report = load_json(path)
        analysis_date = str(report.get("analysis_date") or "")
        if not analysis_date or analysis_date > outcome_through_date:
            continue
        for alert in report.get("alerts") or []:
            matching_ids = [
                episode_id
                for episode_id in alert.get("episode_ids") or []
                if episode_id in valid_episode_ids
            ]
            matching_reviews = [
                review
                for review in alert.get("episode_reviews") or []
                if review.get("episode_id") in valid_episode_ids
            ]
            if not matching_ids and not matching_reviews:
                continue
            normalized_alert = dict(alert)
            normalized_alert["episode_ids"] = matching_ids
            normalized_alert["episode_reviews"] = matching_reviews
            alerts.append(
                {
                    "source_file": path.name,
                    "report_analysis_date": analysis_date,
                    "report_as_of": report.get("as_of"),
                    "market_overview": report.get("market_overview"),
                    "alert": normalized_alert,
                }
            )
            for review in matching_reviews:
                reviews.append(
                    {
                        "source_file": path.name,
                        "report_analysis_date": analysis_date,
                        "report_as_of": report.get("as_of"),
                        "alert_type": alert.get("alert_type"),
                        "monitor_state": alert.get("monitor_state"),
                        "outlook_1_3d": alert.get("outlook_1_3d"),
                        "why_reported": alert.get("why_reported"),
                        "market_change": alert.get("market_change"),
                        "sector_change": alert.get("sector_change"),
                        "company_change": alert.get("company_change"),
                        "stock_change": alert.get("stock_change"),
                        **dict(review),
                    }
                )
    return episodes, alerts, reviews


def load_daily_formal_review_records(
    monitor_dir: Path,
    valid_episode_ids: set[str],
    outcome_through_date: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Read canonical daily review ledgers and flatten the file header per record.

    `review_kind`/`review_origin` come from the ledger row; the ledger's brief
    bodies are the only brief text and detailed-review rows legitimately carry an
    empty `current_review` (the full text lives in the monitor report).
    """
    records: list[dict[str, Any]] = []
    conflicts: list[str] = []
    report_reviews: dict[tuple[str, str], dict[str, Any]] = {}
    for record in _report_review_index(monitor_dir, valid_episode_ids, outcome_through_date):
        report_reviews[(record["episode_id"], record["report_analysis_date"])] = record
    for path in canonical_archive_paths(monitor_dir, "daily-formal-reviews"):
        payload = load_json(path)
        analysis_date = str(payload.get("analysis_date") or "")
        if not analysis_date or analysis_date > outcome_through_date:
            continue
        for row in payload.get("reviews") or []:
            episode_id = str(row.get("episode_id") or "")
            if episode_id not in valid_episode_ids:
                continue
            record = {
                "source_file": path.name,
                "analysis_date": analysis_date,
                "as_of": payload.get("as_of"),
                **dict(row),
            }
            matched = report_reviews.get((episode_id, analysis_date))
            if matched is not None:
                conflicts.extend(_common_field_conflicts(record, matched))
            records.append(record)
    records.sort(key=lambda row: (row["analysis_date"], row["episode_id"]))
    return records, sorted(set(conflicts))


def _report_review_index(
    monitor_dir: Path,
    valid_episode_ids: set[str],
    outcome_through_date: str,
) -> list[dict[str, Any]]:
    indexed: list[dict[str, Any]] = []
    for path in canonical_archive_paths(monitor_dir, "monitor-report"):
        report = load_json(path)
        analysis_date = str(report.get("analysis_date") or "")
        if not analysis_date or analysis_date > outcome_through_date:
            continue
        for alert in report.get("alerts") or []:
            for review in alert.get("episode_reviews") or []:
                episode_id = str(review.get("episode_id") or "")
                if episode_id in valid_episode_ids:
                    indexed.append(
                        {
                            "episode_id": episode_id,
                            "report_analysis_date": analysis_date,
                            **dict(review),
                        }
                    )
    return indexed


def _common_field_conflicts(
    ledger_row: Mapping[str, Any], report_row: Mapping[str, Any]
) -> list[str]:
    conflicts: list[str] = []
    for key, ledger_value in ledger_row.items():
        if key in {"source_file", "analysis_date", "as_of"}:
            continue
        report_value = report_row.get(key)
        if report_value is None or ledger_value in (None, ""):
            continue
        if normalize_json(report_value) != normalize_json(ledger_value):
            conflicts.append(
                f"{ledger_row.get('episode_id')}@{ledger_row['analysis_date']}:{key}"
            )
    return conflicts


def _parquet_records(path: Path) -> list[dict[str, Any]]:
    return [normalize_json(row) for row in pd.read_parquet(path).to_dict("records")]


def _latest_formula_file(root: Path, feature_set: str, analysis_date: str) -> Path | None:
    directory = root / "derived" / feature_set / f"analysis_date={analysis_date}"
    files = sorted(directory.glob("formula_version=*/data.parquet"))
    return files[-1] if files else None


def _formula_version_from_path(path: Path) -> str | None:
    for part in path.parts:
        if part.startswith("formula_version="):
            return part.removeprefix("formula_version=")
    return None


def build_derived_context_records(
    warehouse_root: Path,
    traces: Sequence[tuple[str, Mapping[str, Any]]],
    candidates: Sequence[Mapping[str, Any]],
    decisions: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    candidate_codes_by_formation: dict[str, set[str]] = defaultdict(set)
    for row in candidates:
        candidate_codes_by_formation[str(row["formation_date"])].add(str(row["ts_code"]))

    market_records: list[dict[str, Any]] = []
    price_records: list[dict[str, Any]] = []
    sector_codes_by_formation: dict[str, set[str]] = defaultdict(set)
    for _, trace in traces:
        formation_date = str(trace["formation_date"])
        market_path = _latest_formula_file(warehouse_root, "market_context", formation_date)
        if market_path is not None:
            version = _formula_version_from_path(market_path)
            for row in _parquet_records(market_path):
                market_records.append(
                    {
                        "run_id": build_run_id(formation_date, str(trace["action_date"])),
                        "context_role": "formation_date_derived_audit_slice",
                        # 事后重读的派生行默认是重建；仅当存在逐记录的冻结输入
                        # 引用证明该行就是当时输入时才允许 frozen_used，当前
                        # 导出器没有这类逐行证据，公式版本字符串命中不足以证明。
                        "context_origin": "retrospective_reconstruction",
                        "formula_version": version,
                        **row,
                    }
                )
        price_path = _latest_formula_file(
            warehouse_root, "price_analysis_context", formation_date
        )
        if price_path is not None:
            version = _formula_version_from_path(price_path)
            frame = pd.read_parquet(price_path)
            filtered = frame.loc[
                frame["ts_code"].astype(str).isin(candidate_codes_by_formation[formation_date])
            ]
            for row in filtered.to_dict("records"):
                normalized = normalize_json(row)
                price_records.append(
                    {
                        "run_id": build_run_id(formation_date, str(trace["action_date"])),
                        "context_role": "candidate_formation_date_derived_audit_slice",
                        "context_origin": "retrospective_reconstruction",
                        "formula_version": version,
                        **normalized,
                    }
                )
                group_code = normalized.get("primary_industry_code")
                if group_code:
                    sector_codes_by_formation[formation_date].add(str(group_code))

    for decision in decisions:
        formation_values = decision.get("formation_values")
        if isinstance(formation_values, Mapping) and formation_values.get("group_code"):
            sector_codes_by_formation[str(decision["formation_date"])].add(
                str(formation_values["group_code"])
            )
    for candidate in candidates:
        thesis = candidate.get("research_thesis")
        if not isinstance(thesis, Mapping):
            continue
        for field in ("sector_broad_diffusion", "sector_leader_cluster"):
            section = thesis.get(field)
            if isinstance(section, Mapping) and section.get("group_code"):
                sector_codes_by_formation[str(candidate["formation_date"])].add(
                    str(section["group_code"])
                )

    sector_records: list[dict[str, Any]] = []
    action_by_formation = {
        str(trace["formation_date"]): str(trace["action_date"]) for _, trace in traces
    }
    for formation_date, codes in sorted(sector_codes_by_formation.items()):
        sector_path = _latest_formula_file(warehouse_root, "sector_hotspot", formation_date)
        if sector_path is None:
            continue
        version = _formula_version_from_path(sector_path)
        frame = pd.read_parquet(sector_path)
        filtered = frame.loc[frame["group_code"].astype(str).isin(codes)]
        for row in filtered.to_dict("records"):
            sector_records.append(
                {
                    "run_id": build_run_id(
                        formation_date, action_by_formation[formation_date]
                    ),
                    "context_role": "referenced_group_formation_date_audit_slice",
                    "context_origin": "retrospective_reconstruction",
                    "formula_version": version,
                    **normalize_json(row),
                }
            )
    return market_records, sector_records, price_records


def _fact_partition(
    warehouse_root: Path, dataset: str, partition_field: str, partition_value: str
) -> Path | None:
    path = (
        warehouse_root
        / "facts"
        / dataset
        / f"{partition_field}={partition_value}"
        / "data.parquet"
    )
    return path if path.is_file() else None


def load_benchmark_daily(
    warehouse_root: Path, trading_dates: Sequence[str]
) -> dict[str, dict[str, float]]:
    """HS300 open/close per open day, one partition read per date (as of export)."""
    result: dict[str, dict[str, float]] = {}
    for day in trading_dates:
        path = (
            warehouse_root / "facts" / "index_daily" / f"trade_date={day}" / "data.parquet"
        )
        if not path.is_file():
            continue
        frame = pd.read_parquet(path)
        frame = frame.loc[frame["index_code"].astype(str).eq("000300.SH")]
        if frame.empty:
            continue
        row = frame.iloc[-1]
        open_value = _optional_float(row.get("open"))
        close_value = _optional_float(row.get("close"))
        if open_value is None or close_value is None:
            continue
        result[day] = {"open": open_value, "close": close_value}
    return result


def build_daily_price_volume_records(
    warehouse_root: Path,
    subjects: Sequence[Mapping[str, Any]],
    outcome_through_date: str,
    trading_dates: Sequence[str],
    benchmark_daily: Mapping[str, Mapping[str, float]] | None = None,
) -> list[dict[str, Any]]:
    benchmark_daily = benchmark_daily or {}
    trading_dates = list(trading_dates)
    if not subjects:
        return []
    start_date = min(str(row["action_date"]) for row in subjects)
    trading_dates = [day for day in trading_dates if start_date <= day <= outcome_through_date]
    selected_codes = {str(row["ts_code"]) for row in subjects}
    equity_by_date_code: dict[tuple[str, str], dict[str, Any]] = {}
    adj_by_date_code: dict[tuple[str, str], float] = {}
    for trading_date in trading_dates:
        equity_path = _fact_partition(
            warehouse_root, "equity_daily", "trade_date", trading_date
        )
        if equity_path is not None:
            frame = pd.read_parquet(equity_path)
            frame = frame.loc[frame["ts_code"].astype(str).isin(selected_codes)]
            for row in frame.to_dict("records"):
                equity_by_date_code[(trading_date, str(row["ts_code"]))] = row
        adj_path = _fact_partition(
            warehouse_root, "adj_factor", "trade_date", trading_date
        )
        if adj_path is not None:
            frame = pd.read_parquet(adj_path)
            frame = frame.loc[frame["ts_code"].astype(str).isin(selected_codes)]
            for row in frame.to_dict("records"):
                factor = _optional_float(row.get("adj_factor"))
                if factor is not None:
                    adj_by_date_code[(trading_date, str(row["ts_code"]))] = factor

    records: list[dict[str, Any]] = []
    for subject in subjects:
        action_date = str(subject["action_date"])
        code = str(subject["ts_code"])
        # Calendar numbering: day 1 is the planned action day; a whole-day missing
        # partition never shifts later days forward (T01).
        event_dates = [
            day for day in trading_dates if day >= action_date
        ][:CURRENT_OBSERVATION_MAX_DAYS]
        benchmark_entry = benchmark_daily.get(action_date) or {}
        benchmark_entry_open = benchmark_entry.get("open")
        entry_row = equity_by_date_code.get((action_date, code))
        entry_factor = adj_by_date_code.get((action_date, code))
        entry_open_adjusted = (
            None
            if entry_row is None or entry_factor is None
            else _optional_float(entry_row.get("open")) * entry_factor
        )
        max_close_return: float | None = None
        max_high_return: float | None = None
        min_low_return: float | None = None
        for day_number, trading_date in enumerate(event_dates, start=1):
            benchmark_close = (benchmark_daily.get(trading_date) or {}).get("close")
            market_return = (
                None
                if benchmark_entry_open is None or benchmark_close is None
                else benchmark_close / benchmark_entry_open - 1.0
            )
            row = equity_by_date_code.get((trading_date, code))
            factor = adj_by_date_code.get((trading_date, code))
            if row is None:
                records.append(
                    {
                        "event_key": subject["event_key"],
                        "formation_date": subject["formation_date"],
                        "action_date": action_date,
                        "selection_as_of": subject["selection_as_of"],
                        "ts_code": code,
                        "name": subject["name"],
                        "trade_date": trading_date,
                        "trading_day_number": day_number,
                        "is_action_date": trading_date == action_date,
                        "data_status": "missing_equity_daily",
                        "price_basis": "raw_ohlc; cumulative_returns_use_ohlc_times_adj_factor",
                        "benchmark_code": "000300.SH" if benchmark_daily else None,
                        "benchmark_entry_open": benchmark_entry_open,
                        "benchmark_close": benchmark_close,
                        "market_return_since_entry": market_return,
                        "relative_market_return": None,
                        "relative_market_basis": None,
                    }
                )
                continue
            open_price = _optional_float(row.get("open"))
            high_price = _optional_float(row.get("high"))
            low_price = _optional_float(row.get("low"))
            close_price = _optional_float(row.get("close"))
            close_return = _adjusted_return(close_price, factor, entry_open_adjusted)
            high_return = _adjusted_return(high_price, factor, entry_open_adjusted)
            low_return = _adjusted_return(low_price, factor, entry_open_adjusted)
            if close_return is not None:
                max_close_return = (
                    close_return
                    if max_close_return is None
                    else max(max_close_return, close_return)
                )
            if high_return is not None:
                max_high_return = (
                    high_return if max_high_return is None else max(max_high_return, high_return)
                )
            if low_return is not None:
                min_low_return = (
                    low_return if min_low_return is None else min(min_low_return, low_return)
                )
            drawdown = (
                None
                if close_return is None or max_close_return is None
                else (1.0 + close_return) / (1.0 + max_close_return) - 1.0
            )
            relative_market = (
                None
                if close_return is None or market_return is None
                else close_return - market_return
            )
            records.append(
                {
                    "event_key": subject["event_key"],
                    "formation_date": subject["formation_date"],
                    "action_date": action_date,
                    "selection_as_of": subject["selection_as_of"],
                    "ts_code": code,
                    "name": subject["name"],
                    "trade_date": trading_date,
                    "trading_day_number": day_number,
                    "is_action_date": trading_date == action_date,
                    "data_status": "available",
                    "open": open_price,
                    "high": high_price,
                    "low": low_price,
                    "close": close_price,
                    "pre_close": _optional_float(row.get("pre_close")),
                    "pct_chg_percent": _optional_float(row.get("pct_chg")),
                    "volume_shares": _optional_float(row.get("volume")),
                    "amount_cny": _optional_float(row.get("amount")),
                    "adj_factor": factor,
                    "entry_open_raw": (
                        _optional_float(entry_row.get("open")) if entry_row else None
                    ),
                    "entry_open_adjusted": entry_open_adjusted,
                    "open_return_since_entry": _adjusted_return(
                        open_price, factor, entry_open_adjusted
                    ),
                    "high_return_since_entry": high_return,
                    "low_return_since_entry": low_return,
                    "close_return_since_entry": close_return,
                    "max_close_return_so_far": max_close_return,
                    "max_high_return_so_far": max_high_return,
                    "mae_since_entry": min_low_return,
                    "close_drawdown_from_peak": drawdown,
                    "available_at": normalize_json(row.get("available_at")),
                    "availability_precision": row.get("availability_precision"),
                    "quality_status": row.get("quality_status"),
                    "price_basis": "raw_ohlc; cumulative_returns_use_ohlc_times_adj_factor",
                    "benchmark_code": "000300.SH" if benchmark_daily else None,
                    "benchmark_entry_open": benchmark_entry_open,
                    "benchmark_close": benchmark_close,
                    "market_return_since_entry": market_return,
                    "relative_market_return": relative_market,
                    "relative_market_basis": (
                        "action_open_to_same_close" if relative_market is not None else None
                    ),
                }
            )
    return records


def fixed_d20_fields(
    subject: Mapping[str, Any],
    subject_rows: Sequence[Mapping[str, Any]],
    trading_dates: Sequence[str],
    *,
    conditional: bool = False,
) -> dict[str, Any]:
    """Fixed first-20-trading-day outcomes under the original calendar numbering.

    Statuses follow the execution order: not_applicable / calendar unverifiable
    (missing_path) / no_reliable_entry / not_mature / missing_path / complete.
    """
    fields: dict[str, Any] = {
        "calendar_elapsed_days": 0,
        "fixed_d20_status": None,
        "fixed_d20_end_date": None,
        "fixed_d20_missing_dates": [],
        "fixed_d20_hit_20pct_close": None,
        "fixed_d20_first_hit_day": None,
        "fixed_d20_terminal_return": None,
        "fixed_d20_max_close_return": None,
        "fixed_d20_mfe": None,
        "fixed_d20_mae": None,
        "fixed_d20_max_close_drawdown": None,
        "fixed_d20_close_drawdown_at_end": None,
        "fixed_d20_range_missing_dates": [],
        "fixed_d20_note": None,
        "fixed_d20_market_return": None,
        "fixed_d20_excess_market_return": None,
        "fixed_d20_market_basis": None,
        "fixed_d20_market_missing_reason": None,
    }
    action_date = str(subject.get("action_date") or "")
    days_after = [day for day in trading_dates if action_date and day >= action_date]
    fields["calendar_elapsed_days"] = len(days_after)
    if conditional:
        fields["fixed_d20_status"] = "not_applicable"
        fields["fixed_d20_note"] = "conditional_event_not_applicable"
        return fields
    if not action_date or action_date not in set(trading_dates):
        fields["fixed_d20_status"] = "missing_path"
        fields["fixed_d20_note"] = "trade_calendar_incomplete"
        return fields
    rows_by_number = {
        int(row["trading_day_number"]): row
        for row in subject_rows
        if row.get("trading_day_number") is not None
    }
    day_one = rows_by_number.get(1) or {}
    entry_open = day_one.get("entry_open_adjusted")
    if day_one.get("data_status") != "available" or not entry_open:
        fields["fixed_d20_status"] = "no_reliable_entry"
        return fields
    if len(days_after) < FIXED_D20_DAYS:
        fields["fixed_d20_status"] = "not_mature"
        return fields
    first20 = [rows_by_number.get(number) for number in range(1, FIXED_D20_DAYS + 1)]
    expected_dates = days_after[:FIXED_D20_DAYS]
    missing_closes = [
        expected
        for expected, row in zip(expected_dates, first20)
        if row is None
        or row.get("data_status") != "available"
        or row.get("close") is None
        or row.get("adj_factor") is None
    ]
    missing_highs = [
        expected
        for expected, row in zip(expected_dates, first20)
        if row is not None
        and row.get("data_status") == "available"
        and row.get("high") is None
    ]
    missing_lows = [
        expected
        for expected, row in zip(expected_dates, first20)
        if row is not None
        and row.get("data_status") == "available"
        and row.get("low") is None
    ]
    if missing_closes:
        fields["fixed_d20_status"] = "missing_path"
        fields["fixed_d20_missing_dates"] = missing_closes
        return fields
    closes = [row["close"] * row["adj_factor"] for row in first20]
    fields["fixed_d20_status"] = "complete"
    fields["fixed_d20_end_date"] = first20[-1]["trade_date"]
    fields["fixed_d20_terminal_return"] = closes[-1] / entry_open - 1.0
    day20_market = first20[-1].get("market_return_since_entry")
    if day20_market is None:
        fields["fixed_d20_market_missing_reason"] = (
            "market_benchmark_missing_for_day20_or_action_open"
        )
    else:
        fields["fixed_d20_market_return"] = day20_market
        fields["fixed_d20_excess_market_return"] = (
            fields["fixed_d20_terminal_return"] - day20_market
        )
        fields["fixed_d20_market_basis"] = "action_open_to_same_close"
    peak = closes[0]
    max_close = closes[0]
    max_drawdown = 0.0
    for value in closes:
        peak = max(peak, value)
        max_drawdown = min(max_drawdown, value / peak - 1.0)
        max_close = max(max_close, value)
    fields["fixed_d20_max_close_return"] = max_close / entry_open - 1.0
    fields["fixed_d20_max_close_drawdown"] = max_drawdown
    fields["fixed_d20_close_drawdown_at_end"] = closes[-1] / max_close - 1.0
    for number, row in enumerate(first20, start=1):
        high_return = row.get("high_return_since_entry")
        if high_return is not None and (
            fields["fixed_d20_mfe"] is None or high_return > fields["fixed_d20_mfe"]
        ):
            fields["fixed_d20_mfe"] = high_return
        low_return = row.get("low_return_since_entry")
        if low_return is not None and (
            fields["fixed_d20_mae"] is None or low_return < fields["fixed_d20_mae"]
        ):
            fields["fixed_d20_mae"] = low_return
        close_return = row.get("close_return_since_entry")
        if (
            close_return is not None
            and close_return >= CLOSE_HIT_20PCT_THRESHOLD
            and fields["fixed_d20_first_hit_day"] is None
        ):
            fields["fixed_d20_hit_20pct_close"] = True
            fields["fixed_d20_first_hit_day"] = number
    if fields["fixed_d20_first_hit_day"] is None:
        fields["fixed_d20_hit_20pct_close"] = False
    if missing_highs:
        fields["fixed_d20_mfe"] = None
        fields["fixed_d20_range_missing_dates"] = missing_highs
    if missing_lows:
        fields["fixed_d20_mae"] = None
        fields["fixed_d20_range_missing_dates"] = sorted(
            set(fields["fixed_d20_range_missing_dates"]) | set(missing_lows)
        )
    return fields


def enrich_selections_with_outcomes(
    selections: Sequence[dict[str, Any]],
    daily_records: Sequence[Mapping[str, Any]],
    outcome_through_date: str,
    trading_dates: Sequence[str] = (),
    *,
    conditional_event_keys: frozenset[str] = frozenset(),
) -> None:
    by_event: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in daily_records:
        by_event[str(row["event_key"])].append(row)
    for selection in selections:
        rows = sorted(
            by_event.get(str(selection["event_key"]), []),
            key=lambda row: (str(row.get("trade_date") or ""), int(row.get("trading_day_number") or 0)),
        )
        available = [row for row in rows if row.get("data_status") == "available"]
        latest = available[-1] if available else None
        selection.update(
            {
                "outcome_through_date": outcome_through_date,
                "outcome_trading_day_count": max(
                    (int(row.get("trading_day_number") or 0) for row in rows),
                    default=0,
                ),
                "outcome_data_status": (
                    "available" if available else "no_reliable_entry_price"
                ),
                "outcome_close_return": (
                    latest.get("close_return_since_entry") if latest else None
                ),
                "outcome_max_close_return": (
                    latest.get("max_close_return_so_far") if latest else None
                ),
                "outcome_max_high_return": (
                    latest.get("max_high_return_so_far") if latest else None
                ),
                "outcome_mae": latest.get("mae_since_entry") if latest else None,
                "outcome_close_drawdown_from_peak": (
                    latest.get("close_drawdown_from_peak") if latest else None
                ),
                "outcome_relative_market_return": (
                    latest.get("relative_market_return") if latest else None
                ),
                "outcome_relative_market_basis": (
                    latest.get("relative_market_basis") if latest else None
                ),
            }
        )
        selection.update(
            fixed_d20_fields(
                selection,
                rows,
                list(trading_dates),
                conditional=str(selection["event_key"]) in conditional_event_keys,
            )
        )


def build_candidate_outcome_subjects(
    candidates: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "event_key": build_event_key(
                str(candidate["formation_date"]),
                str(candidate["ts_code"]),
                f"candidate-{candidate.get('final_fate') or 'unknown'}",
            ),
            "formation_date": candidate.get("formation_date"),
            "action_date": candidate.get("action_date"),
            "selection_as_of": candidate.get("selection_as_of"),
            "ts_code": candidate.get("ts_code"),
            "name": candidate.get("name"),
        }
        for candidate in candidates
    ]


def build_candidate_outcome_records(
    candidates: Sequence[Mapping[str, Any]],
    daily_records: Sequence[Mapping[str, Any]],
    outcome_through_date: str,
    trading_dates: Sequence[str] = (),
) -> list[dict[str, Any]]:
    subjects = build_candidate_outcome_subjects(candidates)
    conditional_keys = frozenset(
        subject["event_key"]
        for subject, candidate in zip(subjects, candidates, strict=True)
        if _is_conditional_candidate(candidate)
    )
    enrich_selections_with_outcomes(
        subjects,
        daily_records,
        outcome_through_date,
        trading_dates,
        conditional_event_keys=conditional_keys,
    )
    records: list[dict[str, Any]] = []
    for candidate, outcome in zip(candidates, subjects, strict=True):
        thesis = candidate.get("research_thesis")
        thesis_map = thesis if isinstance(thesis, Mapping) else {}
        records.append(
            {
                "run_id": candidate.get("run_id"),
                "formation_date": candidate.get("formation_date"),
                "action_date": candidate.get("action_date"),
                "ts_code": candidate.get("ts_code"),
                "name": candidate.get("name"),
                "final_fate": candidate.get("final_fate"),
                "opportunity_type": candidate.get("opportunity_type"),
                "engine_type": thesis_map.get("engine_type"),
                "engine_status": thesis_map.get("engine_status"),
                "selection_as_of": candidate.get("selection_as_of"),
                "selection_output_class": _candidate_output_class(candidate),
                "outcome_usage": "candidate_price_comparison",
                "outcome_through_date": outcome.get("outcome_through_date"),
                "outcome_trading_day_count": outcome.get(
                    "outcome_trading_day_count"
                ),
                "outcome_data_status": outcome.get("outcome_data_status"),
                "outcome_close_return": outcome.get("outcome_close_return"),
                "outcome_max_close_return": outcome.get(
                    "outcome_max_close_return"
                ),
                "outcome_max_high_return": outcome.get("outcome_max_high_return"),
                "outcome_mae": outcome.get("outcome_mae"),
                "outcome_close_drawdown_from_peak": outcome.get(
                    "outcome_close_drawdown_from_peak"
                ),
                "relative_market_return_if_available": outcome.get(
                    "outcome_relative_market_return"
                ),
                "relative_market_basis": outcome.get("outcome_relative_market_basis"),
                "relative_sector_return_if_available": None,
                "relative_sector_missing_reason": (
                    "no_same_window_sector_benchmark_available_locally"
                ),
                **{
                    key: outcome.get(key)
                    for key in (
                        "calendar_elapsed_days",
                        "fixed_d20_status",
                        "fixed_d20_end_date",
                        "fixed_d20_missing_dates",
                        "fixed_d20_hit_20pct_close",
                        "fixed_d20_first_hit_day",
                        "fixed_d20_terminal_return",
                        "fixed_d20_max_close_return",
                        "fixed_d20_mfe",
                        "fixed_d20_mae",
                        "fixed_d20_max_close_drawdown",
                        "fixed_d20_close_drawdown_at_end",
                        "fixed_d20_range_missing_dates",
                        "fixed_d20_note",
                    )
                },
            }
        )
    return records


def _is_conditional_candidate(candidate: Mapping[str, Any]) -> bool:
    thesis = candidate.get("research_thesis")
    thesis_map = thesis if isinstance(thesis, Mapping) else {}
    return (
        candidate.get("final_fate") == "selected"
        and thesis_map.get("engine_type") == "fresh_event_pending"
        and thesis_map.get("engine_status") == "conditional"
    )


def _candidate_output_class(candidate: Mapping[str, Any]) -> str:
    """Consumer-side class that never marks a non-selected ledger row as formal."""
    if candidate.get("final_fate") != "selected":
        return "not_formal_candidate"
    return selection_output_class(
        str(candidate.get("trace_version") or "daily-research-trace-v4"),
        candidate,
    )


def load_condition_review_records(path: Path | None) -> list[dict[str, Any]]:
    """Read the explicitly provided human condition-review JSONL, if any.

    No implicit historical matrix is consulted; absent input simply means every
    conditional event exports as `unknown`.
    """
    if path is None:
        return []
    if not path.is_file():
        raise ValueError(f"condition review file not found: {path.name}")
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError("condition review record must be a JSON object")
        records.append(row)
    return records


def build_conditional_event_outcomes(
    candidates: Sequence[Mapping[str, Any]],
    decisions: Sequence[Mapping[str, Any]],
    condition_records: Sequence[Mapping[str, Any]],
    outcome_through_date: str | None = None,
) -> list[dict[str, Any]]:
    condition_by_key: dict[tuple[str, str], Mapping[str, Any]] = {}
    for row in condition_records:
        key = (str(row.get("run_id")), str(row.get("ts_code")))
        condition_by_key[key] = row
    decisions_by_key: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    decisions_by_run: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in decisions:
        decision_id = str(row.get("decision_id") or "")
        if not decision_id:
            continue
        decisions_by_key[(str(row.get("run_id")), str(row.get("ts_code")), decision_id)] = row
        decisions_by_run[(str(row.get("run_id")), decision_id)].append(row)
    records: list[dict[str, Any]] = []
    for candidate in candidates:
        thesis = candidate.get("research_thesis")
        thesis_map = thesis if isinstance(thesis, Mapping) else {}
        if not _is_conditional_candidate(candidate):
            continue
        run_id = str(candidate.get("run_id"))
        ts_code = str(candidate["ts_code"])
        event_key = build_event_key(
            str(candidate["formation_date"]), ts_code, "selected"
        )
        record = condition_by_key.get((run_id, ts_code))
        condition_result: str = "unknown"
        unknown_reason: str | None = None
        review_status = "unreviewed"
        if not condition_records:
            unknown_reason = "no_condition_review_file_provided"
        elif record is None:
            unknown_reason = "no_matching_condition_record"
        else:
            raw_result = str(record.get("condition_result") or "")
            observed_through = str(record.get("observed_through_date") or "")
            if raw_result not in CONDITION_RESULTS:
                unknown_reason = "invalid_condition_result"
            elif (
                outcome_through_date
                and observed_through
                and observed_through > outcome_through_date
            ):
                unknown_reason = "observation_after_export_cutoff"
            else:
                condition_result = raw_result
                review_status = "reviewed"
        company = thesis_map.get("company_information")
        company_map = company if isinstance(company, Mapping) else {}
        decision_id = thesis_map.get("action_condition_decision_id")
        decision = None
        if decision_id:
            decision = decisions_by_key.get((run_id, ts_code, str(decision_id)))
            if decision is None:
                fallback = decisions_by_run.get((run_id, str(decision_id)), [])
                if len(fallback) == 1:
                    decision = fallback[0]
        decision_map = decision if isinstance(decision, Mapping) else {}
        formation_values = decision_map.get("formation_values")
        formation_map = (
            formation_values if isinstance(formation_values, Mapping) else {}
        )
        source_refs = record.get("source_refs") if record is not None else None
        note = record.get("note") if record is not None else None
        records.append(
            {
                "event_key": event_key,
                "run_id": run_id,
                "formation_date": candidate.get("formation_date"),
                "action_date": candidate.get("action_date"),
                "ts_code": ts_code,
                "name": candidate.get("name"),
                "event_id": company_map.get("event_id"),
                "event_available_at": company_map.get("event_available_at"),
                "original_action_condition": thesis_map.get("critical_unknown"),
                "first_observable_session": formation_map.get(
                    "reaction_start_date"
                ),
                "condition_result": condition_result,
                "condition_review_status": review_status,
                "condition_unknown_reason": unknown_reason,
                "condition_observed_through_date": (
                    record.get("observed_through_date") if record is not None else None
                ),
                "condition_source_refs": source_refs,
                "reliable_entry_available": False,
                "reliable_entry_date": None,
                "reliable_entry_price": None,
                "formal_return_started": False,
                "outcome_data_status": (
                    "condition_not_met"
                    if condition_result == "not_met"
                    else "condition_unknown"
                    if condition_result == "unknown"
                    else "no_reviewed_reliable_entry"
                ),
                "outcome_close_return": None,
                "outcome_max_close_return": None,
                "outcome_mae": None,
                "notes": note,
            }
        )
    return sorted(records, key=lambda row: (row["action_date"], row["ts_code"]))


def _adjusted_return(
    raw_price: float | None,
    factor: float | None,
    entry_open_adjusted: float | None,
) -> float | None:
    if raw_price is None or factor is None or not entry_open_adjusted:
        return None
    return raw_price * factor / entry_open_adjusted - 1.0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_readme(
    output_dir: Path,
    *,
    start_action_date: str,
    end_action_date: str,
    outcome_through_date: str,
    exported_at: str,
    selections: Sequence[Mapping[str, Any]],
    research_day_count: int,
    candidate_count: int,
    decision_count: int,
    monitor_review_count: int,
    daily_review_count: int,
    maturity_counts: Mapping[str, int],
    known_gaps: Sequence[str],
) -> None:
    unique_codes = len({row["ts_code"] for row in selections})
    action_days = len({row["action_date"] for row in selections})
    gap_lines = "".join(f"- {gap}\n" for gap in known_gaps) or "- 无。\n"
    text = f"""# A 股五 Skill 优化研究样本（v3）

本目录是从本地冻结研究产物和事实仓中导出的**公开安全、只读、可核对切片**，用于复盘市场、板块、公司、价格和总控五个环节的判断质量。它不是交易建议，也不包含仓位、自动交易、止盈止损或收益承诺。

## 边界与数量

- 行动日范围：`{start_action_date}` 至 `{end_action_date}`（含首尾）；
- 事后行情终点：`{outcome_through_date}`；
- 导出读取时间：`{exported_at}`；
- 研究日（含零入选日）：{research_day_count} 天；
- 正式入选事件：{len(selections)} 条；
- 不同股票：{unique_codes} 只；
- 有正式入选的行动日：{action_days} 个；
- 候选账记录：{candidate_count} 条；
- 决策证据记录：{decision_count} 条；
- 已形成的逐 episode 跟踪复盘（报告侧）：{monitor_review_count} 条；
- 每日判断账本记录（账本侧）：{daily_review_count} 条；
- 固定 20 日口径：complete {maturity_counts.get('complete', 0)} 条，not_mature {maturity_counts.get('not_mature', 0)} 条，missing_path {maturity_counts.get('missing_path', 0)} 条，no_reliable_entry {maturity_counts.get('no_reliable_entry', 0)} 条，not_applicable {maturity_counts.get('not_applicable', 0)} 条。

形成日证据始终以各次 `selection_as_of` 冻结；行情只进入 outcome/review/价格路径文件，不反向改写选择理由。`exported_at` 是本次读取归档的时间，`selection_as_of` 是当时研究截止，`outcome_through_date` 限制结果行情终点，三个时点不能互换。

## 文件说明

- `data/formal_selections.csv`：正式入选事件（confirmed active 与旧 V1），含固定 20 日口径字段与 `formal_result_consistency`；
- `data/candidate_outcomes.csv`：全部候选账的同口径价格摘要（selected/rejected/unresolved），`outcome_usage=candidate_price_comparison`，不代表实际参与；
- `data/candidate_daily_price_volume.csv`：全部候选账从各自行动日起的逐日路径（日历编号，含沪深300对照）；
- `data/conditional_event_outcomes.csv`：条件事件的人工判定结果；无人工输入或观测晚于截止时记 `unknown` 并注明原因；
- `data/research_runs.jsonl`：每次研究的完整冻结 trace 载荷及来源文件名；
- `data/candidate_ledger.jsonl`：所有明确进入候选账的股票；
- `data/decision_trace.jsonl`：研究 trace 中实际引用的结构化决策证据；
- `data/review_contracts.jsonl`：发动机、催化、传播、价格确认、剩余路径、反证、关键未知和行动条件引用；
- `data/monitor_episodes.jsonl`：最新快照中本批正式 episode 记录；
- `data/monitor_alerts.jsonl` 与 `data/monitor_reviews.jsonl`：已生成的提醒和逐 episode 复盘（报告侧唯一详评正文）；
- `data/daily_formal_reviews.jsonl`：每日判断账本（账本侧唯一简评正文；详评行正文为空属正常分工）；
- `data/daily_price_volume.csv`：每条正式入选事件按交易日历编号的逐日路径（最多 30 个交易日，含沪深300对照）；
- `data/market_context.jsonl`、`data/sector_context.jsonl`、`data/price_context.jsonl`：形成日派生上下文切片，`context_origin` 标记 frozen_used / retrospective_reconstruction；
- `manifest.json` 与 `checksums.sha256`：记录数、边界、文件哈希和已知限制。

## 口径

- `event_key` 以形成日、股票代码和角色区分事件；同股不同推荐日是不同 episode，不合并统计；
- 交易日编号来自 `facts/trade_calendar` 的实际开市日：第 1 日就是原行动日，停牌或行情缺失不延后编号；
- 当前观察最多 30 个交易日；`fixed_d20_*` 只取原第 1—20 个交易日，`outcome_*` 表示截至观察终点；
- OHLC 为未复权原始价格，成交量单位为股，成交额单位为人民币元；
- 跨日累计收益使用 `raw_price × adj_factor`，收盘触达 20% 的容差与正式 Forward 一致（`0.20 - 1e-12`），不使用盘中最高价；
- 沪深300对照为描述性比较（`action_open_to_same_close`），不是等权市场收益，也不是扣除风险后的独立收益证明；
- 板块对照：本包暂无同窗口可信行业基准，`relative_sector_return_if_available` 保持空并注明原因；
- `context_origin=retrospective_reconstruction` 的切片是按旧日期从现有数据重算的辅助资料，不能冒充当时选股输入；
- `review_origin=backfill` 的账本记录可阅读，但不是当时已经作出的判断或预测的证据；
- 缺少可靠行情的交易日保留一行并标记 `missing_equity_daily`，不补猜。

## 本批已知缺口

{gap_lines}
## 有意不包含

本目录不包含完整本地事实仓、公告正文/PDF、运行日志、环境变量、密钥、用户名或个人绝对路径。市场上下文为完整单行；板块和价格上下文仅保留本研究样本实际引用的审计切片，不代表整个 A 股发现宇宙。
"""
    ensure_public_safe(text)
    (output_dir / "README.md").write_text(text, encoding="utf-8")


def finalize_manifest(
    output_dir: Path,
    *,
    start_action_date: str,
    end_action_date: str,
    outcome_through_date: str,
    exported_at: str,
    record_counts: Mapping[str, int],
    selected_codes: Sequence[str],
    selected_action_dates: Sequence[str],
    research_action_dates: Sequence[str],
    maturity_counts: Mapping[str, int],
    known_limitations: Sequence[str],
    ledger_conflicts: Sequence[str] = (),
    current_opportunity_contract: str | None = None,
) -> None:
    payload_files = sorted(
        path
        for path in output_dir.rglob("*")
        if path.is_file()
        and path.name not in {"manifest.json", "checksums.sha256"}
        and path.suffix.lower() != ".xlsx"
        and not path.name.endswith(".inspect.ndjson")
    )
    file_entries = [
        {
            "path": path.relative_to(output_dir).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in payload_files
    ]
    limitations = list(known_limitations)
    if ledger_conflicts:
        limitations.append(
            "daily_formal_reviews ledger/report common-field conflicts: "
            + "; ".join(ledger_conflicts)
        )
    manifest = {
        "package_version": PACKAGE_VERSION,
        "action_date_start": start_action_date,
        "action_date_end": end_action_date,
        "outcome_through_date": outcome_through_date,
        "exported_at": exported_at,
        "formation_evidence_policy": "preserve each frozen selection_as_of",
        "outcome_policy": "post-selection data are separate and do not rewrite formation evidence",
        "record_counts": dict(record_counts),
        "selected_stock_codes": sorted(set(selected_codes)),
        "action_dates": sorted(set(selected_action_dates)),
        "research_action_dates": sorted(set(research_action_dates)),
        "fixed_d20_maturity": dict(maturity_counts),
        **(
            {"current_opportunity_contract": current_opportunity_contract}
            if current_opportunity_contract
            else {}
        ),
        "files": file_entries,
        "privacy": {
            "contains_credentials": False,
            "contains_personal_absolute_paths": False,
            "contains_raw_local_warehouse": False,
            "contains_raw_local_archive": False,
        },
        "known_limitations": limitations,
    }
    ensure_public_safe(manifest)
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    checksum_text = "".join(
        f"{entry['sha256']}  {entry['path']}\n" for entry in file_entries
    )
    (output_dir / "checksums.sha256").write_text(checksum_text, encoding="utf-8")


def _apply_formal_result_consistency(
    selections: Sequence[Mapping[str, Any]],
    monitor_episodes: Sequence[Mapping[str, Any]],
) -> None:
    """Compare recomputed fixed-D20 values with formal frozen numbers when available."""
    formal_by_key: dict[str, Mapping[str, Any]] = {}
    for episode in monitor_episodes:
        if episode.get("frozen_twenty_day_review") or any(
            str(field).startswith("d20_") for field in episode
        ):
            key = str(episode.get("episode_id") or "")
            if key and key not in formal_by_key:
                formal_by_key[key] = episode
    for selection in selections:
        episode = formal_by_key.get(str(selection["event_key"]))
        status = "unavailable"
        compared: list[str] = []
        if episode is not None and selection.get("fixed_d20_status") == "complete":
            frozen = episode.get("frozen_twenty_day_review")
            pairs = [
                (
                    "terminal_return",
                    selection.get("fixed_d20_terminal_return"),
                    (
                        frozen.get("d20_close_return_since_entry")
                        if isinstance(frozen, Mapping)
                        else episode.get("d20_close_return_since_entry")
                    ),
                ),
                (
                    "max_close_return",
                    selection.get("fixed_d20_max_close_return"),
                    (
                        frozen.get("d20_max_close_return_since_entry")
                        if isinstance(frozen, Mapping)
                        else episode.get("d20_max_close_return_since_entry")
                    ),
                ),
                (
                    "mae",
                    selection.get("fixed_d20_mae"),
                    (
                        frozen.get("d20_mae_since_entry")
                        if isinstance(frozen, Mapping)
                        else episode.get("d20_mae_since_entry")
                    ),
                ),
            ]
            pairs = [(name, mine, theirs) for name, mine, theirs in pairs if theirs is not None]
            if pairs:
                status = "match"
                compared = [
                    f"{name}:{mine!r}vs{theirs!r}"
                    for name, mine, theirs in pairs
                    if mine is None or not math.isclose(mine, float(theirs), rel_tol=1e-9, abs_tol=1e-9)
                ]
                if compared:
                    status = "mismatch"
        selection["formal_result_consistency"] = status
        selection["formal_result_diff_fields"] = compared


def export_dataset(
    source_root: Path,
    output_dir: Path,
    *,
    start_action_date: str = DEFAULT_START_ACTION_DATE,
    end_action_date: str = DEFAULT_END_ACTION_DATE,
    outcome_through_date: str = DEFAULT_OUTCOME_THROUGH_DATE,
    condition_review_file: Path | None = None,
    exported_at: str | None = None,
) -> dict[str, int]:
    exported_at = exported_at or datetime.now().astimezone().isoformat(timespec="seconds")
    selection_dir = source_root / "local_archive" / "forward_selection"
    monitor_dir = source_root / "local_archive" / "forward_monitor"
    warehouse_root = source_root / "local_warehouse"
    traces = discover_frozen_traces(
        selection_dir, start_action_date, end_action_date
    )
    if not traces:
        raise ValueError("no frozen selection traces found in requested boundary")
    log_rows = _read_selection_log(
        selection_dir / "forward-selection-log.csv",
        start_action_date,
        end_action_date,
    )
    trace_log_mismatches: list[str] = []
    selections = build_formal_selections(traces, log_rows, trace_log_mismatches)
    candidates = [
        record
        for source_name, trace in traces
        for record in extract_candidate_records(trace, _trace_version(source_name, trace))
    ]
    decisions = build_decision_records(traces)
    condition_records = load_condition_review_records(condition_review_file)
    research_runs = build_research_run_records(traces, selection_dir)
    review_contracts = build_review_contracts(candidates)
    # 本批原始身份：正式 selection 的 event_key（与 episode_id 同构）。
    # snapshot 只提供仍在池内的观察数据，已结束记录不得因不在最新快照而漏读。
    batch_episode_ids = {str(row["event_key"]) for row in selections}
    monitor_episodes, monitor_alerts, monitor_reviews = build_monitor_records(
        monitor_dir,
        start_action_date,
        end_action_date,
        outcome_through_date,
        valid_episode_ids=batch_episode_ids,
    )
    monitor_episode_ids = {str(row["episode_id"]) for row in monitor_episodes}
    formal_episode_ids = batch_episode_ids
    monitor_episode_ids = {str(row["episode_id"]) for row in monitor_episodes}
    daily_reviews, ledger_conflicts = load_daily_formal_review_records(
        monitor_dir,
        formal_episode_ids | monitor_episode_ids,
        outcome_through_date,
    )
    market_context, sector_context, price_context = build_derived_context_records(
        warehouse_root, traces, candidates, decisions
    )
    trading_dates = load_trading_dates(
        warehouse_root, start_action_date, outcome_through_date
    )
    benchmark_daily = load_benchmark_daily(warehouse_root, trading_dates)
    daily_prices = build_daily_price_volume_records(
        warehouse_root, selections, outcome_through_date, trading_dates, benchmark_daily
    )
    enrich_selections_with_outcomes(
        selections, daily_prices, outcome_through_date, trading_dates
    )
    _apply_formal_result_consistency(selections, monitor_episodes)
    candidate_subjects = build_candidate_outcome_subjects(candidates)
    candidate_daily_prices = build_daily_price_volume_records(
        warehouse_root,
        candidate_subjects,
        outcome_through_date,
        trading_dates,
        benchmark_daily,
    )
    candidate_outcomes = build_candidate_outcome_records(
        candidates, candidate_daily_prices, outcome_through_date, trading_dates
    )
    conditional_event_outcomes = build_conditional_event_outcomes(
        candidates, decisions, condition_records, outcome_through_date
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    data_dir = output_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    selection_fields = [
        "event_key",
        "run_id",
        "formation_date",
        "action_date",
        "selection_as_of",
        "trace_version",
        "selection_output_class",
        "priority",
        "ts_code",
        "name",
        "opportunity_type",
        "selection_reason",
        "strongest_counterevidence",
        "nearest_comparison",
        "formal_reason_source",
        "trace_log_text_match",
        "trace_selection_reason",
        "trace_strongest_counterevidence",
        "trace_nearest_comparison",
        "current_day_at_export",
        "current_close_return_at_export",
        "max_close_return_so_far_at_export",
        "hit_20pct_close_within_20d_at_export",
        "first_hit_day_at_export",
        "terminal_return_20d_at_export",
        "validation_mode",
        "outcome_through_date",
        "outcome_trading_day_count",
        "outcome_data_status",
        "outcome_close_return",
        "outcome_max_close_return",
        "outcome_max_high_return",
        "outcome_mae",
        "outcome_close_drawdown_from_peak",
        "outcome_relative_market_return",
        "outcome_relative_market_basis",
        "calendar_elapsed_days",
        "fixed_d20_status",
        "fixed_d20_end_date",
        "fixed_d20_missing_dates",
        "fixed_d20_hit_20pct_close",
        "fixed_d20_first_hit_day",
        "fixed_d20_terminal_return",
        "fixed_d20_max_close_return",
        "fixed_d20_mfe",
        "fixed_d20_mae",
        "fixed_d20_max_close_drawdown",
        "fixed_d20_close_drawdown_at_end",
        "fixed_d20_range_missing_dates",
        "fixed_d20_note",
        "fixed_d20_market_return",
        "fixed_d20_excess_market_return",
        "fixed_d20_market_basis",
        "fixed_d20_market_missing_reason",
        "formal_result_consistency",
        "formal_result_diff_fields",
    ]
    counts["formal_selections"] = write_csv(
        data_dir / "formal_selections.csv", selections, selection_fields
    )
    counts["research_runs"] = write_jsonl(
        data_dir / "research_runs.jsonl", research_runs
    )
    counts["candidate_ledger"] = write_jsonl(
        data_dir / "candidate_ledger.jsonl", candidates
    )
    counts["decision_trace"] = write_jsonl(
        data_dir / "decision_trace.jsonl", decisions
    )
    counts["review_contracts"] = write_jsonl(
        data_dir / "review_contracts.jsonl", review_contracts
    )
    counts["monitor_episodes"] = write_jsonl(
        data_dir / "monitor_episodes.jsonl", monitor_episodes
    )
    counts["monitor_alerts"] = write_jsonl(
        data_dir / "monitor_alerts.jsonl", monitor_alerts
    )
    counts["monitor_reviews"] = write_jsonl(
        data_dir / "monitor_reviews.jsonl", monitor_reviews
    )
    counts["daily_formal_reviews"] = write_jsonl(
        data_dir / "daily_formal_reviews.jsonl", daily_reviews
    )
    counts["market_context"] = write_jsonl(
        data_dir / "market_context.jsonl", market_context
    )
    counts["sector_context"] = write_jsonl(
        data_dir / "sector_context.jsonl", sector_context
    )
    counts["price_context"] = write_jsonl(
        data_dir / "price_context.jsonl", price_context
    )
    candidate_outcome_fields = [
        "run_id",
        "formation_date",
        "action_date",
        "ts_code",
        "name",
        "final_fate",
        "opportunity_type",
        "engine_type",
        "engine_status",
        "selection_as_of",
        "selection_output_class",
        "outcome_usage",
        "outcome_through_date",
        "outcome_trading_day_count",
        "outcome_data_status",
        "outcome_close_return",
        "outcome_max_close_return",
        "outcome_max_high_return",
        "outcome_mae",
        "outcome_close_drawdown_from_peak",
        "relative_market_return_if_available",
        "relative_market_basis",
        "relative_sector_return_if_available",
        "relative_sector_missing_reason",
        "calendar_elapsed_days",
        "fixed_d20_status",
        "fixed_d20_end_date",
        "fixed_d20_missing_dates",
        "fixed_d20_hit_20pct_close",
        "fixed_d20_first_hit_day",
        "fixed_d20_terminal_return",
        "fixed_d20_max_close_return",
        "fixed_d20_mfe",
        "fixed_d20_mae",
        "fixed_d20_max_close_drawdown",
        "fixed_d20_close_drawdown_at_end",
        "fixed_d20_range_missing_dates",
        "fixed_d20_note",
        "fixed_d20_market_return",
        "fixed_d20_excess_market_return",
        "fixed_d20_market_basis",
        "fixed_d20_market_missing_reason",
    ]
    counts["candidate_outcomes"] = write_csv(
        data_dir / "candidate_outcomes.csv",
        candidate_outcomes,
        candidate_outcome_fields,
    )
    conditional_outcome_fields = [
        "event_key",
        "run_id",
        "formation_date",
        "action_date",
        "ts_code",
        "name",
        "event_id",
        "event_available_at",
        "original_action_condition",
        "first_observable_session",
        "condition_result",
        "condition_review_status",
        "condition_unknown_reason",
        "condition_observed_through_date",
        "condition_source_refs",
        "reliable_entry_available",
        "reliable_entry_date",
        "reliable_entry_price",
        "formal_return_started",
        "outcome_data_status",
        "outcome_close_return",
        "outcome_max_close_return",
        "outcome_mae",
        "notes",
    ]
    counts["conditional_event_outcomes"] = write_csv(
        data_dir / "conditional_event_outcomes.csv",
        conditional_event_outcomes,
        conditional_outcome_fields,
    )
    daily_fields = [
        "event_key",
        "formation_date",
        "action_date",
        "selection_as_of",
        "ts_code",
        "name",
        "trade_date",
        "trading_day_number",
        "is_action_date",
        "data_status",
        "open",
        "high",
        "low",
        "close",
        "pre_close",
        "pct_chg_percent",
        "volume_shares",
        "amount_cny",
        "adj_factor",
        "entry_open_raw",
        "entry_open_adjusted",
        "open_return_since_entry",
        "high_return_since_entry",
        "low_return_since_entry",
        "close_return_since_entry",
        "max_close_return_so_far",
        "max_high_return_so_far",
        "mae_since_entry",
        "close_drawdown_from_peak",
        "available_at",
        "availability_precision",
        "quality_status",
        "price_basis",
        "benchmark_code",
        "benchmark_entry_open",
        "benchmark_close",
        "market_return_since_entry",
        "relative_market_return",
        "relative_market_basis",
    ]
    counts["daily_price_volume"] = write_csv(
        data_dir / "daily_price_volume.csv", daily_prices, daily_fields
    )
    candidate_daily_fields = [
        "event_key",
        "formation_date",
        "action_date",
        "selection_as_of",
        "ts_code",
        "name",
        "trade_date",
        "trading_day_number",
        "is_action_date",
        "data_status",
        "open",
        "high",
        "low",
        "close",
        "adj_factor",
        "entry_open_raw",
        "entry_open_adjusted",
        "close_return_since_entry",
        "price_basis",
        "benchmark_code",
        "benchmark_entry_open",
        "benchmark_close",
        "market_return_since_entry",
        "relative_market_return",
        "relative_market_basis",
    ]
    counts["candidate_daily_price_volume"] = write_csv(
        data_dir / "candidate_daily_price_volume.csv",
        candidate_daily_prices,
        candidate_daily_fields,
    )
    has_current_opportunity = any(
        row.get("current_opportunity") is not None for row in daily_reviews
    )
    maturity_counts: dict[str, int] = {
        status: sum(
            1 for row in selections if row.get("fixed_d20_status") == status
        )
        for status in FIXED_D20_STATUSES
    }
    known_gaps = [
        "同窗口可信行业基准暂缺：relative_sector_return_if_available 保持空并注明原因。",
    ]
    if trace_log_mismatches:
        known_gaps.append(
            "以下入选在冻结 log 与冻结 trace 间存在措辞差异（两份原文均保留，见 trace_log_text_match 与 trace_* 字段）："
            + "；".join(trace_log_mismatches)
            + "。"
        )
    if not condition_records and conditional_event_outcomes:
        known_gaps.append(
            f"{len(conditional_event_outcomes)} 条条件事件未提供人工判定文件，condition_result=unknown。"
        )
    snapshot_missing = [
        f"{row['action_date']} {row['ts_code']} {row['name']}"
        for row in selections
        if str(row["event_key"]) not in monitor_episode_ids
    ]
    if snapshot_missing:
        known_gaps.append(
            "以下正式入选在最新快照中没有对应 episode（历史记录不被最新快照完全覆盖）："
            + "；".join(snapshot_missing)
            + "。"
        )
    if any(
        str(trace.get("trace_version") or "") != "daily-research-trace-v4"
        for _, trace in traces
    ):
        known_gaps.append("批内含非 V4 旧轨迹，对应 research_thesis/decision_trace 缺失属历史事实。")
    write_readme(
        output_dir,
        start_action_date=start_action_date,
        end_action_date=end_action_date,
        outcome_through_date=outcome_through_date,
        exported_at=exported_at,
        selections=selections,
        research_day_count=len(traces),
        candidate_count=len(candidates),
        decision_count=len(decisions),
        monitor_review_count=len(monitor_reviews),
        daily_review_count=len(daily_reviews),
        maturity_counts=maturity_counts,
        known_gaps=known_gaps,
    )
    counts["unique_selected_stocks"] = len({row["ts_code"] for row in selections})
    counts["action_dates"] = len({row["action_date"] for row in selections})
    finalize_manifest(
        output_dir,
        start_action_date=start_action_date,
        end_action_date=end_action_date,
        outcome_through_date=outcome_through_date,
        exported_at=exported_at,
        record_counts=counts,
        selected_codes=[str(row["ts_code"]) for row in selections],
        selected_action_dates=[str(row["action_date"]) for row in selections],
        research_action_dates=[str(trace["action_date"]) for _, trace in traces],
        maturity_counts=maturity_counts,
        current_opportunity_contract=(
            "current-opportunity-v1" if has_current_opportunity else None
        ),
        known_limitations=[
            "Sector and price derived contexts are referenced audit slices, not full-universe exports.",
            "Same-window sector benchmark series are not available locally; relative sector fields stay null with reasons.",
            "The package cannot reconstruct each formation date's complete eligible universe, so no undiscovered outcome leads are generated.",
        ],
        ledger_conflicts=ledger_conflicts,
    )
    return counts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--start-action-date", default=DEFAULT_START_ACTION_DATE
    )
    parser.add_argument("--end-action-date", default=DEFAULT_END_ACTION_DATE)
    parser.add_argument(
        "--outcome-through-date", default=DEFAULT_OUTCOME_THROUGH_DATE
    )
    parser.add_argument(
        "--condition-review-file",
        type=Path,
        default=None,
        help="Optional human condition-review JSONL keyed by (run_id, ts_code).",
    )
    parser.add_argument("--exported-at", default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    counts = export_dataset(
        args.source_root.resolve(),
        args.output_dir.resolve(),
        start_action_date=args.start_action_date,
        end_action_date=args.end_action_date,
        outcome_through_date=args.outcome_through_date,
        condition_review_file=args.condition_review_file,
        exported_at=args.exported_at,
    )
    print(json.dumps(counts, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
