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
PACKAGE_VERSION = "a-share-skill-optimization-sample-v2"
LEGACY_TRACE_NAME = "regenerated-selection-2026-08-19-asof-2026-08-20T090500+0800.json"
TRACE_GLOB = "research-trace-*.json"
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
    candidates.extend(sorted(selection_dir.glob(TRACE_GLOB)))
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


def load_selection_impact_rows(output_dir: Path) -> list[dict[str, str]]:
    path = output_dir / "selection-impact-matrix.csv"
    if not path.is_file():
        path = (
            Path(__file__).resolve().parents[1]
            / "research"
            / "skill-optimization"
            / "five-skill-selection-logic-optimization-20260901"
            / "selection-impact-matrix.csv"
        )
    if not path.is_file():
        raise ValueError("selection impact matrix is required for conditional outcomes")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def build_formal_selections(
    traces: Sequence[tuple[str, Mapping[str, Any]]], log_rows: Sequence[Mapping[str, str]]
) -> list[dict[str, Any]]:
    log_by_key = {(row["action_date"], row["ts_code"]): row for row in log_rows}
    traced_log_keys: set[tuple[str, str]] = set()
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
                raise ValueError(
                    f"trace/log mismatch for {key}: {', '.join(mismatched_fields)}"
                )
            output_class = selection_output_class(
                version, candidate_by_code.get(str(selected["ts_code"]))
            )
            if output_class not in {
                "confirmed_active",
                "legacy_v1_not_rewritten",
            }:
                continue
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
    if set(log_by_key) != traced_log_keys:
        missing = sorted(set(log_by_key) - traced_log_keys)
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
    traces: Sequence[tuple[str, Mapping[str, Any]]]
) -> list[dict[str, Any]]:
    return [
        {
            "run_id": build_run_id(str(trace["formation_date"]), str(trace["action_date"])),
            "logical_source_id": f"frozen-selection/{trace['formation_date']}",
            "trace_version": _trace_version(source_name, trace),
            "formation_date": trace["formation_date"],
            "action_date": trace["action_date"],
            "selection_as_of": trace.get("as_of"),
            "trace_payload": dict(trace),
        }
        for source_name, trace in traces
    ]


def load_latest_monitor_snapshot(
    monitor_dir: Path, outcome_through_date: str
) -> tuple[dict[str, Any], str]:
    eligible: list[tuple[str, Path]] = []
    for path in monitor_dir.glob("snapshot-*.json"):
        analysis_date = path.stem.removeprefix("snapshot-")
        if analysis_date <= outcome_through_date:
            eligible.append((analysis_date, path))
    if not eligible:
        return {}, ""
    analysis_date, path = sorted(eligible)[-1]
    return load_json(path), analysis_date


def build_monitor_records(
    monitor_dir: Path,
    start_action_date: str,
    end_action_date: str,
    outcome_through_date: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    snapshot, snapshot_analysis_date = load_latest_monitor_snapshot(
        monitor_dir, outcome_through_date
    )
    episodes = [
        dict(row)
        for row in snapshot.get("episodes") or []
        if row.get("source_type") == "formal"
        and start_action_date <= str(row.get("action_date") or "") <= end_action_date
    ]
    valid_episode_ids = {str(row["episode_id"]) for row in episodes}
    alerts: list[dict[str, Any]] = []
    reviews: list[dict[str, Any]] = []
    for path in sorted(monitor_dir.glob("monitor-report-*.json")):
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
                    "report_analysis_date": analysis_date,
                    "report_as_of": report.get("as_of"),
                    "market_overview": report.get("market_overview"),
                    "alert": normalized_alert,
                }
            )
            for review in matching_reviews:
                reviews.append(
                    {
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
    for episode in episodes:
        episode["snapshot_analysis_date"] = snapshot_analysis_date
        episode["snapshot_as_of"] = snapshot.get("as_of")
    return episodes, alerts, reviews


def _parquet_records(path: Path) -> list[dict[str, Any]]:
    return [normalize_json(row) for row in pd.read_parquet(path).to_dict("records")]


def _latest_formula_file(root: Path, feature_set: str, analysis_date: str) -> Path | None:
    directory = root / "derived" / feature_set / f"analysis_date={analysis_date}"
    files = sorted(directory.glob("formula_version=*/data.parquet"))
    return files[-1] if files else None


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
            for row in _parquet_records(market_path):
                market_records.append(
                    {
                        "run_id": build_run_id(formation_date, str(trace["action_date"])),
                        "context_role": "formation_date_derived_audit_slice",
                        **row,
                    }
                )
        price_path = _latest_formula_file(
            warehouse_root, "price_analysis_context", formation_date
        )
        if price_path is not None:
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
        frame = pd.read_parquet(sector_path)
        filtered = frame.loc[frame["group_code"].astype(str).isin(codes)]
        for row in filtered.to_dict("records"):
            sector_records.append(
                {
                    "run_id": build_run_id(
                        formation_date, action_by_formation[formation_date]
                    ),
                    "context_role": "referenced_group_formation_date_audit_slice",
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


def build_daily_price_volume_records(
    warehouse_root: Path,
    selections: Sequence[Mapping[str, Any]],
    outcome_through_date: str,
) -> list[dict[str, Any]]:
    start_date = min(str(row["action_date"]) for row in selections)
    trading_dates = sorted(
        path.parent.name.removeprefix("trade_date=")
        for path in (warehouse_root / "facts" / "equity_daily").glob(
            "trade_date=*/data.parquet"
        )
        if start_date
        <= path.parent.name.removeprefix("trade_date=")
        <= outcome_through_date
    )
    selected_codes = {str(row["ts_code"]) for row in selections}
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
    for selection in selections:
        action_date = str(selection["action_date"])
        code = str(selection["ts_code"])
        event_dates = [day for day in trading_dates if day >= action_date]
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
            row = equity_by_date_code.get((trading_date, code))
            factor = adj_by_date_code.get((trading_date, code))
            if row is None:
                records.append(
                    {
                        "event_key": selection["event_key"],
                        "formation_date": selection["formation_date"],
                        "action_date": action_date,
                        "selection_as_of": selection["selection_as_of"],
                        "ts_code": code,
                        "name": selection["name"],
                        "trade_date": trading_date,
                        "trading_day_number": day_number,
                        "is_action_date": trading_date == action_date,
                        "data_status": "missing_equity_daily",
                        "price_basis": "raw_ohlc; cumulative_returns_use_ohlc_times_adj_factor",
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
            records.append(
                {
                    "event_key": selection["event_key"],
                    "formation_date": selection["formation_date"],
                    "action_date": action_date,
                    "selection_as_of": selection["selection_as_of"],
                    "ts_code": code,
                    "name": selection["name"],
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
                }
            )
    return records


def enrich_selections_with_outcomes(
    selections: Sequence[dict[str, Any]],
    daily_records: Sequence[Mapping[str, Any]],
    outcome_through_date: str,
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
            }
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
) -> list[dict[str, Any]]:
    subjects = build_candidate_outcome_subjects(candidates)
    enrich_selections_with_outcomes(subjects, daily_records, outcome_through_date)
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
                "relative_market_return_if_available": None,
                "relative_sector_return_if_available": None,
            }
        )
    return records


def build_conditional_event_outcomes(
    candidates: Sequence[Mapping[str, Any]],
    decisions: Sequence[Mapping[str, Any]],
    impact_rows: Sequence[Mapping[str, str]],
) -> list[dict[str, Any]]:
    decisions_by_id = {
        str(row.get("decision_id")): row
        for row in decisions
        if row.get("decision_id")
    }
    impact_by_event = {
        str(row.get("event_key")): row for row in impact_rows if row.get("event_key")
    }
    records: list[dict[str, Any]] = []
    for candidate in candidates:
        thesis = candidate.get("research_thesis")
        thesis_map = thesis if isinstance(thesis, Mapping) else {}
        if not (
            candidate.get("final_fate") == "selected"
            and thesis_map.get("engine_type") == "fresh_event_pending"
            and thesis_map.get("engine_status") == "conditional"
        ):
            continue
        event_key = build_event_key(
            str(candidate["formation_date"]), str(candidate["ts_code"]), "selected"
        )
        impact = impact_by_event.get(event_key)
        if impact is None:
            raise ValueError(f"conditional event missing from impact matrix: {event_key}")
        condition_result = str(impact.get("action_condition_effect") or "")
        if condition_result not in CONDITION_RESULTS:
            raise ValueError(
                f"invalid conditional result for {event_key}: {condition_result}"
            )
        company = thesis_map.get("company_information")
        company_map = company if isinstance(company, Mapping) else {}
        decision_id = thesis_map.get("action_condition_decision_id")
        decision = decisions_by_id.get(str(decision_id)) if decision_id else None
        decision_map = decision if isinstance(decision, Mapping) else {}
        formation_values = decision_map.get("formation_values")
        formation_map = (
            formation_values if isinstance(formation_values, Mapping) else {}
        )
        records.append(
            {
                "event_key": event_key,
                "formation_date": candidate.get("formation_date"),
                "action_date": candidate.get("action_date"),
                "ts_code": candidate.get("ts_code"),
                "name": candidate.get("name"),
                "event_id": company_map.get("event_id"),
                "event_available_at": company_map.get("event_available_at"),
                "original_action_condition": thesis_map.get("critical_unknown"),
                "first_observable_session": formation_map.get(
                    "reaction_start_date"
                ),
                "condition_result": condition_result,
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
                "notes": impact.get("early_outcome_used_only_for_evaluation"),
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
    selections: Sequence[Mapping[str, Any]],
    candidate_count: int,
    decision_count: int,
    monitor_review_count: int,
) -> None:
    unique_codes = len({row["ts_code"] for row in selections})
    action_days = len({row["action_date"] for row in selections})
    text = f"""# A 股五 Skill 优化研究样本

本目录是从本地冻结研究产物和事实仓中导出的**公开安全、只读、可核对切片**，用于优化市场、板块、公司、价格和总控五个 Skill。它不是交易建议，也不包含仓位、自动交易、止盈止损或收益承诺。

## 边界与数量

- 正式行动日：`{start_action_date}` 至 `{end_action_date}`（含首尾）；
- 事后行情终点：`{outcome_through_date}`；
- 正式入选事件：{len(selections)} 条；
- 不同股票：{unique_codes} 只；
- 行动日：{action_days} 个；
- 候选账记录：{candidate_count} 条；
- 决策证据记录：{decision_count} 条；
- 已形成的逐 episode 跟踪复盘：{monitor_review_count} 条。

起点以用户提供的历史工作簿中最早 `action_date=2026-08-20` 为准。`action_date=2026-09-01` 的研究不在本样本内。形成日证据始终以各次 `selection_as_of` 冻结；`2026-08-31` 行情只进入 outcome/review 文件，不反向改写选择理由。

## 文件说明

- `data/formal_selections.csv`：confirmed active 与旧 V1 正式记录；不包含四条 conditional event lead；
- `data/candidate_outcomes.csv`：全部候选账的同口径行动后价格摘要，覆盖 selected、rejected 与 unresolved；
- `data/conditional_event_outcomes.csv`：四条 `fresh_event_pending + conditional` 的人工条件判定；无可靠入口时不启动正式收益；
- `data/research_runs.jsonl`：8 次研究的完整冻结 trace 载荷，使用逻辑来源标识，不含本地路径；
- `data/candidate_ledger.jsonl`：所有明确进入候选账的股票；
- `data/decision_trace.jsonl`：研究 trace 中实际引用的结构化决策证据；
- `data/review_contracts.jsonl`：发动机、催化、传播、价格确认、剩余路径、反证、关键未知和行动条件引用；
- `data/monitor_episodes.jsonl`：截至 8 月 31 日收盘的正式 episode 快照；
- `data/monitor_alerts.jsonl` 与 `data/monitor_reviews.jsonl`：截至该交易日已生成的提醒和逐 episode 复盘；
- `data/daily_price_volume.csv`：每条正式入选事件从行动日起到 8 月 31 日的原始 OHLC、成交量、成交额和复权累计路径；
- `data/market_context.jsonl`：各形成日完整市场派生行；
- `data/sector_context.jsonl`：候选与决策证据实际引用行业，以及候选形成日主行业的派生行；
- `data/price_context.jsonl`：候选股票在各自形成日的价格派生行；
- `A股Skill优化样本_2026-08-20至2026-08-31.xlsx`：便于人工筛选和复盘的汇总工作簿；
- `manifest.json` 与 `checksums.sha256`：记录数、边界、文件哈希和已知限制。

## 口径

- `event_key` 以形成日、股票代码和角色区分事件，因此洛阳钼业两次入选分别保留；
- OHLC 为未复权原始价格，成交量单位为股，成交额单位为人民币元；
- 从行动日开盘计算的跨日累计收益使用 `raw_price × adj_factor`；
- 候选结果的行动日开盘基准只用于 selected/rejected/unresolved 同口径评价，不代表历史正式参与；
- conditional 的 `condition_result` 只读取人工影响矩阵，不从名称、监控状态或后续最高价推断；无可靠入口时正式收益字段保持空值；
- 当前派生切片不足以按每个形成日重建完整合格股票范围，因此不生成 `undiscovered_outcome_leads.csv`，也不补猜；
- 缺少可靠行情的交易日保留一行并标记 `missing_equity_daily`，不补猜；
- 8 月 31 日收盘跟踪报告在 9 月 1 日盘前形成，其 `report_as_of` 被完整保留，不能当作 8 月 31 日开盘前信息；
- 旧格式的 8 月 20 日研究没有 V4 `research_thesis` 和 `decision_trace`，对应字段保持空值并明确标记，绝不事后重建。

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
    record_counts: Mapping[str, int],
    selected_codes: Sequence[str],
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
    manifest = {
        "package_version": PACKAGE_VERSION,
        "action_date_start": start_action_date,
        "action_date_end": end_action_date,
        "outcome_through_date": outcome_through_date,
        "formation_evidence_policy": "preserve each frozen selection_as_of",
        "outcome_policy": "post-selection data are separate and do not rewrite formation evidence",
        "record_counts": dict(record_counts),
        "selected_stock_codes": sorted(set(selected_codes)),
        "files": file_entries,
        "privacy": {
            "contains_credentials": False,
            "contains_personal_absolute_paths": False,
            "contains_raw_local_warehouse": False,
            "contains_raw_local_archive": False,
        },
        "known_limitations": [
            "The 2026-08-20 action-date trace predates V4 and has no recorded research_thesis or decision_trace.",
            "Sector and price derived contexts are referenced audit slices, not full-universe exports.",
            "Candidate-relative market and sector outcome returns remain null because no matching post-action benchmark series is exported.",
            "The package cannot reconstruct each formation date's complete eligible universe, so no undiscovered outcome leads are generated.",
            "The 2026-08-31 close monitor was produced on 2026-09-01 pre-open; report_as_of remains explicit.",
        ],
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


def export_dataset(
    source_root: Path,
    output_dir: Path,
    *,
    start_action_date: str = DEFAULT_START_ACTION_DATE,
    end_action_date: str = DEFAULT_END_ACTION_DATE,
    outcome_through_date: str = DEFAULT_OUTCOME_THROUGH_DATE,
) -> dict[str, int]:
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
    selections = build_formal_selections(traces, log_rows)
    candidates = [
        record
        for source_name, trace in traces
        for record in extract_candidate_records(trace, _trace_version(source_name, trace))
    ]
    decisions = build_decision_records(traces)
    impact_rows = load_selection_impact_rows(output_dir)
    research_runs = build_research_run_records(traces)
    review_contracts = build_review_contracts(candidates)
    monitor_episodes, monitor_alerts, monitor_reviews = build_monitor_records(
        monitor_dir,
        start_action_date,
        end_action_date,
        outcome_through_date,
    )
    market_context, sector_context, price_context = build_derived_context_records(
        warehouse_root, traces, candidates, decisions
    )
    daily_prices = build_daily_price_volume_records(
        warehouse_root, selections, outcome_through_date
    )
    enrich_selections_with_outcomes(
        selections, daily_prices, outcome_through_date
    )
    candidate_subjects = build_candidate_outcome_subjects(candidates)
    candidate_daily_prices = build_daily_price_volume_records(
        warehouse_root, candidate_subjects, outcome_through_date
    )
    candidate_outcomes = build_candidate_outcome_records(
        candidates, candidate_daily_prices, outcome_through_date
    )
    conditional_event_outcomes = build_conditional_event_outcomes(
        candidates, decisions, impact_rows
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
        "outcome_through_date",
        "outcome_trading_day_count",
        "outcome_data_status",
        "outcome_close_return",
        "outcome_max_close_return",
        "outcome_max_high_return",
        "outcome_mae",
        "outcome_close_drawdown_from_peak",
        "relative_market_return_if_available",
        "relative_sector_return_if_available",
    ]
    counts["candidate_outcomes"] = write_csv(
        data_dir / "candidate_outcomes.csv",
        candidate_outcomes,
        candidate_outcome_fields,
    )
    conditional_outcome_fields = [
        "event_key",
        "formation_date",
        "action_date",
        "ts_code",
        "name",
        "event_id",
        "event_available_at",
        "original_action_condition",
        "first_observable_session",
        "condition_result",
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
    ]
    counts["daily_price_volume"] = write_csv(
        data_dir / "daily_price_volume.csv", daily_prices, daily_fields
    )
    write_readme(
        output_dir,
        start_action_date=start_action_date,
        end_action_date=end_action_date,
        outcome_through_date=outcome_through_date,
        selections=selections,
        candidate_count=len(candidates),
        decision_count=len(decisions),
        monitor_review_count=len(monitor_reviews),
    )
    counts["unique_selected_stocks"] = len({row["ts_code"] for row in selections})
    counts["action_dates"] = len({row["action_date"] for row in selections})
    finalize_manifest(
        output_dir,
        start_action_date=start_action_date,
        end_action_date=end_action_date,
        outcome_through_date=outcome_through_date,
        record_counts=counts,
        selected_codes=[str(row["ts_code"]) for row in selections],
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
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    counts = export_dataset(
        args.source_root.resolve(),
        args.output_dir.resolve(),
        start_action_date=args.start_action_date,
        end_action_date=args.end_action_date,
        outcome_through_date=args.outcome_through_date,
    )
    print(json.dumps(counts, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
