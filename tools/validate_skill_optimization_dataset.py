#!/usr/bin/env python3
"""Validate the published A-share Skill optimization sample."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import zipfile
from pathlib import Path
from typing import Any, Iterable


EXPECTED = {
    "formal_selections": 29,
    "unique_selected_stocks": 28,
    "action_dates": 8,
    "research_runs": 8,
    "candidate_ledger": 78,
    "decision_trace": 126,
    "review_contracts": 78,
    "monitor_episodes": 39,
    "monitor_alerts": 31,
    "monitor_reviews": 26,
    "daily_price_volume": 124,
    "market_context": 8,
    "sector_context": 54,
    "price_context": 78,
}
START_ACTION_DATE = "2026-08-20"
END_ACTION_DATE = "2026-08-31"
OUTCOME_THROUGH_DATE = "2026-08-31"
WORKBOOK_NAME = "A股Skill优化样本_2026-08-20至2026-08-31.xlsx"
PRIVATE_PATTERNS = (
    re.compile(r"/Users/"),
    re.compile(r"/home/"),
    re.compile(r"[A-Za-z]:\\\\Users\\\\"),
    re.compile(r"(?i)(api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret)\s*[:=]\s*[^\s,}\]]+"),
)
FORMULA_ERRORS = ("#REF!", "#DIV/0!", "#VALUE!", "#NAME?", "#NUM!", "#NULL!")


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
    workbook_path = package_dir / WORKBOOK_NAME
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
    if manifest["action_date_start"] != START_ACTION_DATE:
        raise ValueError("unexpected action-date start")
    if manifest["action_date_end"] != END_ACTION_DATE:
        raise ValueError("unexpected action-date end")
    if manifest["outcome_through_date"] != OUTCOME_THROUGH_DATE:
        raise ValueError("unexpected outcome boundary")
    for key, expected in EXPECTED.items():
        if int(manifest["record_counts"][key]) != expected:
            raise ValueError(f"manifest count mismatch for {key}")

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
    if actual_counts != EXPECTED:
        raise ValueError(f"actual record counts differ: {actual_counts}")

    if min(row["action_date"] for row in selections) != START_ACTION_DATE:
        raise ValueError("formal selections do not start at requested boundary")
    if max(row["action_date"] for row in selections) != END_ACTION_DATE:
        raise ValueError("formal selections do not end at requested boundary")
    if max(row["trade_date"] for row in daily) > OUTCOME_THROUGH_DATE:
        raise ValueError("daily outcome exceeds requested boundary")
    if any(row["action_date"] > END_ACTION_DATE for row in candidates):
        raise ValueError("candidate action date exceeds boundary")
    if any(row["action_date"] > END_ACTION_DATE for row in research_runs):
        raise ValueError("research-run action date exceeds boundary")
    assert_unique((row["event_key"] for row in selections), "formal event_key")
    assert_unique((row["run_id"] for row in research_runs), "research run_id")
    selection_keys = {row["event_key"] for row in selections}
    if {row["event_key"] for row in daily} != selection_keys:
        raise ValueError("daily paths do not cover every formal selection")
    selected_contracts = [row for row in contracts if row["final_fate"] == "selected"]
    if len(selected_contracts) != len(selections):
        raise ValueError("selected review-contract count differs from selections")
    candidate_keys = {(row["run_id"], row["ts_code"]) for row in candidates}
    if any((row["run_id"], row["ts_code"]) not in candidate_keys for row in price):
        raise ValueError("price context has a row outside the candidate ledger")
    if any(row.get("trace_payload", {}).get("action_date") > END_ACTION_DATE for row in research_runs):
        raise ValueError("embedded trace exceeds action-date boundary")
    if not (package_dir / WORKBOOK_NAME).is_file():
        raise ValueError("review workbook is missing")
    with zipfile.ZipFile(package_dir / WORKBOOK_NAME) as workbook:
        workbook.testzip()
        workbook_xml = workbook.read("xl/workbook.xml").decode("utf-8")
        if len(re.findall(r"<(?:\w+:)?sheet\s", workbook_xml)) != 11:
            raise ValueError("review workbook should contain 11 sheets")

    validate_checksums(package_dir, manifest)
    scan_public_safety(package_dir)
    return {
        "status": "PASS",
        "record_counts": actual_counts,
        "workbook_sheets": 11,
        "checksums_verified": len(manifest["files"]),
        "privacy_scan": "PASS",
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
