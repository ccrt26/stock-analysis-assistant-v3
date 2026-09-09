#!/usr/bin/env python3
"""Validate an exported A-share Skill optimization sample package (v2 and v3).

Validation is driven entirely by the package's own manifest and files: date
ranges and record counts are read from the package, never from hard-coded
historical constants. Legacy v2 packages (with the review workbook and without
the v3-only files) remain validatable.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import zipfile
from pathlib import Path
from typing import Any, Iterable


PRIVATE_PATTERNS = (
    re.compile(r"/Users/"),
    re.compile(r"/home/"),
    re.compile(r"[A-Za-z]:\\\\Users\\\\"),
    re.compile(r"(?i)(api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret)\s*[:=]\s*[^\s,}\]]+"),
)
FORMULA_ERRORS = ("#REF!", "#DIV/0!", "#VALUE!", "#NAME?", "#NUM!", "#NULL!")
FIXED_D20_STATUSES = {
    "not_applicable",
    "no_reliable_entry",
    "not_mature",
    "missing_path",
    "complete",
}
FATES = {"selected", "rejected", "unresolved"}
FORMAL_CLASSES = {"confirmed_active", "legacy_v1_not_rewritten"}
REVIEW_KINDS = {"checkpoint_detail", "regular_detail", "brief"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def assert_unique(values: Iterable[str], label: str) -> None:
    materialized = list(values)
    if len(materialized) != len(set(materialized)):
        raise ValueError(f"duplicate {label}")


def parse_bool(text: str | None) -> bool:
    return str(text).strip().lower() in {"true", "1", "yes"}


def scan_public_safety(package_dir: Path) -> None:
    for path in package_dir.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() in {".md", ".json", ".jsonl", ".csv", ".sha256"}:
            text = path.read_text(encoding="utf-8-sig", errors="strict")
            for pattern in PRIVATE_PATTERNS:
                if pattern.search(text):
                    raise ValueError(
                        f"public-safety pattern {pattern.pattern!r} in {path.name}"
                    )
    workbook_paths = sorted(package_dir.glob("*.xlsx"))
    for workbook_path in workbook_paths:
        with zipfile.ZipFile(workbook_path) as archive:
            for member in archive.namelist():
                if not member.endswith(".xml"):
                    continue
                text = archive.read(member).decode("utf-8", errors="ignore")
                for pattern in PRIVATE_PATTERNS:
                    if pattern.search(text):
                        raise ValueError(
                            f"public-safety pattern {pattern.pattern!r} in workbook {member}"
                        )
                if any(error in text for error in FORMULA_ERRORS):
                    raise ValueError(f"formula error token in workbook {member}")


def validate_checksums(package_dir: Path, manifest: dict[str, Any]) -> None:
    listed = {entry["path"]: entry for entry in manifest["files"]}
    for relative_path, entry in listed.items():
        path = package_dir / relative_path
        if not path.is_file():
            raise ValueError(f"manifest file missing: {relative_path}")
        if path.stat().st_size != int(entry["bytes"]):
            raise ValueError(f"size mismatch: {relative_path}")
        if sha256(path) != entry["sha256"]:
            raise ValueError(f"checksum mismatch: {relative_path}")
    checksum_rows = {}
    for line in (package_dir / "checksums.sha256").read_text(encoding="utf-8").splitlines():
        digest, relative_path = line.split("  ", 1)
        checksum_rows[relative_path] = digest
    if checksum_rows != {path: entry["sha256"] for path, entry in listed.items()}:
        raise ValueError("checksums.sha256 does not match manifest files")


def validate_package(package_dir: Path) -> dict[str, Any]:
    manifest = json.loads((package_dir / "manifest.json").read_text(encoding="utf-8"))
    package_version = str(manifest.get("package_version") or "")
    is_v3 = package_version.endswith("-v3")
    start_action_date = str(manifest["action_date_start"])
    end_action_date = str(manifest["action_date_end"])
    outcome_through = str(manifest["outcome_through_date"])
    if end_action_date < start_action_date:
        raise ValueError("manifest action-date end precedes start")
    if outcome_through < start_action_date:
        raise ValueError("outcome boundary precedes action-date start")

    data_dir = package_dir / "data"
    selections = read_csv(data_dir / "formal_selections.csv")
    research_runs = read_jsonl(data_dir / "research_runs.jsonl")
    candidates = read_jsonl(data_dir / "candidate_ledger.jsonl")
    decisions = read_jsonl(data_dir / "decision_trace.jsonl")
    contracts = read_jsonl(data_dir / "review_contracts.jsonl")
    monitor_episodes = read_jsonl(data_dir / "monitor_episodes.jsonl")
    monitor_alerts = read_jsonl(data_dir / "monitor_alerts.jsonl")
    monitor_reviews = read_jsonl(data_dir / "monitor_reviews.jsonl")
    daily = read_csv(data_dir / "daily_price_volume.csv")
    market = read_jsonl(data_dir / "market_context.jsonl")
    sector = read_jsonl(data_dir / "sector_context.jsonl")
    price = read_jsonl(data_dir / "price_context.jsonl")
    has_candidate_outcomes = (data_dir / "candidate_outcomes.csv").is_file()
    has_conditional_outcomes = (
        data_dir / "conditional_event_outcomes.csv"
    ).is_file()
    if is_v3 and not (has_candidate_outcomes and has_conditional_outcomes):
        raise ValueError("v3 package is missing candidate/conditional outcome files")
    candidate_outcomes = (
        read_csv(data_dir / "candidate_outcomes.csv") if has_candidate_outcomes else []
    )
    conditional_outcomes = (
        read_csv(data_dir / "conditional_event_outcomes.csv")
        if has_conditional_outcomes
        else []
    )
    candidate_daily: list[dict[str, str]] = []
    daily_reviews: list[dict[str, Any]] = []
    if is_v3:
        candidate_daily = read_csv(data_dir / "candidate_daily_price_volume.csv")
        daily_reviews = read_jsonl(data_dir / "daily_formal_reviews.jsonl")

    actual_counts = {
        "formal_selections": len(selections),
        "unique_selected_stocks": len({row["ts_code"] for row in selections}),
        "action_dates": len({row["action_date"] for row in selections}),
        "research_runs": len(research_runs),
        "candidate_ledger": len(candidates),
        "decision_trace": len(decisions),
        "review_contracts": len(contracts),
        "monitor_episodes": len(monitor_episodes),
        "monitor_alerts": len(monitor_alerts),
        "monitor_reviews": len(monitor_reviews),
        "daily_price_volume": len(daily),
        "market_context": len(market),
        "sector_context": len(sector),
        "price_context": len(price),
    }
    if has_candidate_outcomes:
        actual_counts["candidate_outcomes"] = len(candidate_outcomes)
    if has_conditional_outcomes:
        actual_counts["conditional_event_outcomes"] = len(conditional_outcomes)
    if is_v3:
        actual_counts["candidate_daily_price_volume"] = len(candidate_daily)
        actual_counts["daily_formal_reviews"] = len(daily_reviews)
    declared = manifest.get("record_counts") or {}
    for key, actual in actual_counts.items():
        if key in declared and int(declared[key]) != actual:
            raise ValueError(
                f"manifest count mismatch for {key}: declared {declared[key]}, actual {actual}"
            )
    if is_v3:
        missing_declared = [key for key in actual_counts if key not in declared]
        if missing_declared:
            raise ValueError(
                f"manifest does not declare counts for: {sorted(missing_declared)}"
            )

    # Boundary checks: every record must sit inside the manifest-declared range.
    if any(
        not start_action_date <= row["action_date"] <= end_action_date
        for row in selections
    ):
        raise ValueError("formal selection outside declared action-date range")
    if any(
        not start_action_date <= str(row.get("action_date") or "") <= end_action_date
        for row in research_runs
    ):
        raise ValueError("research-run action date outside declared range")
    if any(
        not start_action_date <= str(row.get("action_date") or "") <= end_action_date
        for row in candidates
    ):
        raise ValueError("candidate action date outside declared range")
    if any(row["trade_date"] > outcome_through for row in daily):
        raise ValueError("daily outcome exceeds declared boundary")
    if any(row["trade_date"] > outcome_through for row in candidate_daily):
        raise ValueError("candidate daily outcome exceeds declared boundary")

    # Identity and coverage checks that hold for any batch size, including empty.
    assert_unique((row["event_key"] for row in selections), "formal event_key")
    assert_unique((row["run_id"] for row in research_runs), "research run_id")
    if selections:
        if min(row["action_date"] for row in selections) < start_action_date:
            raise ValueError("formal selections precede the declared start")
        selection_keys = {row["event_key"] for row in selections}
        if {row["event_key"] for row in daily} != selection_keys:
            raise ValueError("daily paths do not cover every formal selection")
    class_values = {row.get("selection_output_class") or None for row in selections}
    invalid_classes = class_values - FORMAL_CLASSES
    if invalid_classes - {None} or (None in invalid_classes and is_v3):
        raise ValueError("formal selections contain an invalid output class")
    if has_candidate_outcomes:
        if {row["final_fate"] for row in candidate_outcomes} - FATES:
            raise ValueError("candidate outcomes contain an unknown final fate")
        candidate_outcome_keys = {
            (row["run_id"], row["ts_code"]) for row in candidate_outcomes
        }
        if candidate_outcome_keys != {
            (row["run_id"], row["ts_code"]) for row in candidates
        }:
            raise ValueError("candidate outcomes do not cover the candidate ledger")
        if any(row.get("outcome_usage") not in (None, "", "candidate_price_comparison") for row in candidate_outcomes):
            raise ValueError("candidate outcome has an invalid outcome_usage")
        fixed_statuses = {
            row["fixed_d20_status"] for row in candidate_outcomes if row.get("fixed_d20_status")
        }
        if fixed_statuses - FIXED_D20_STATUSES:
            raise ValueError("candidate outcome has an invalid fixed_d20_status")
    if has_conditional_outcomes:
        conditional_keys = {
            (row.get("run_id"), row.get("ts_code")) for row in conditional_outcomes
        }
        if has_candidate_outcomes:
            for row in candidate_outcomes:
                if (row["run_id"], row["ts_code"]) in conditional_keys:
                    if row.get("fixed_d20_status") not in (None, "", "not_applicable"):
                        raise ValueError("conditional candidate must not carry a fixed formal D20 result")
        if any(
            row["condition_result"] not in {"met", "not_met", "unknown"}
            for row in conditional_outcomes
        ):
            raise ValueError("conditional outcome has an invalid condition result")
        if any(
            parse_bool(row.get("formal_return_started"))
            or parse_bool(row.get("reliable_entry_available"))
            or row.get("reliable_entry_price")
            or row.get("outcome_close_return")
            or row.get("outcome_max_close_return")
            or row.get("outcome_mae")
            for row in conditional_outcomes
        ):
            raise ValueError("conditional outcome incorrectly starts a formal return")
    selected_contracts = [row for row in contracts if row.get("final_fate") == "selected"]
    expected_formal_count = len(selections) + (
        len(conditional_outcomes) if has_conditional_outcomes else 0
    )
    if selected_contracts and len(selected_contracts) != expected_formal_count:
        raise ValueError("selected contracts do not split into formal and conditional")
    candidate_keys = {(row["run_id"], row["ts_code"]) for row in candidates}
    if any((row.get("run_id"), row.get("ts_code")) not in candidate_keys for row in price):
        raise ValueError("price context has a row outside the candidate ledger")
    candidate_event_keys = {
        f"formal:{row['formation_date']}:{row['ts_code']}:candidate-{row.get('final_fate') or 'unknown'}"
        for row in candidates
    }
    if any(row["event_key"] not in candidate_event_keys for row in candidate_daily):
        raise ValueError("candidate daily path has a row outside the candidate ledger")
    if any(row.get("action_date") and str(row["action_date"]) > end_action_date for row in research_runs):
        raise ValueError("embedded trace exceeds action-date boundary")
    if is_v3:
        review_keys = [
            (str(row.get("episode_id")), str(row.get("analysis_date")))
            for row in daily_reviews
        ]
        assert_unique(review_keys, "daily review (episode_id, analysis_date)")
        if any(row.get("review_kind") not in REVIEW_KINDS for row in daily_reviews):
            raise ValueError("daily review has an invalid review_kind")

    workbook_paths = sorted(package_dir.glob("*.xlsx"))
    declared_sheets = manifest.get("workbook_sheets")
    for workbook_path in workbook_paths:
        with zipfile.ZipFile(workbook_path) as workbook:
            if workbook.testzip() is not None:
                raise ValueError(f"corrupt workbook archive: {workbook_path.name}")
            if declared_sheets is not None:
                workbook_xml = workbook.read("xl/workbook.xml").decode("utf-8")
                sheets = len(re.findall(r"<(?:\w+:)?sheet\s", workbook_xml))
                if sheets != int(declared_sheets):
                    raise ValueError(
                        f"workbook sheet count {sheets} differs from declared {declared_sheets}"
                    )

    validate_checksums(package_dir, manifest)
    scan_public_safety(package_dir)
    maturity: dict[str, int] = {}
    for row in selections:
        status = row.get("fixed_d20_status") or "unknown"
        maturity[status] = maturity.get(status, 0) + 1
    return {
        "status": "PASS",
        "package_version": package_version,
        "record_counts": actual_counts,
        "fixed_d20_maturity": maturity,
        "checksums_verified": len(manifest["files"]),
        "privacy_scan": "PASS",
        "workbook_checked": len(workbook_paths),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package_dir", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = validate_package(args.package_dir.resolve())
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
