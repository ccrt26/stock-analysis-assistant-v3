from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from stock_analyzer.ops.status import FailureClass, RunStatus
from stock_analyzer.storage.capacity_guard import (
    MAX_SELECTED_WINDOW_CODES,
    MAX_SELECTED_WINDOW_ROWS,
)


MAX_DAILY_RECOMMENDATIONS = 10
EVALUATION_TASKS_PER_RECOMMENDATION = 6
FIXTURE_SAMPLE_PATTERNS = (
    re.compile(r"fixture/sample", re.IGNORECASE),
    re.compile(r"\bfixture\b", re.IGNORECASE),
    re.compile(r"\bsample\b", re.IGNORECASE),
    re.compile(r"local sample data", re.IGNORECASE),
    re.compile(r"not production data", re.IGNORECASE),
)


@dataclass(frozen=True)
class ProductionVerificationFailure:
    code: str
    message: str
    fix_suggestion: str
    failure_class: FailureClass = FailureClass.REPORT_ARTIFACT_INVALID


@dataclass(frozen=True)
class ProductionVerification:
    trade_date: date
    status: RunStatus
    passed: bool
    recommendations: int
    evidence_packages: int
    evaluation_tasks: int
    market_price_daily_current_day_rows: int
    daily_basic_indicator_current_day_rows: int
    report_index_exists: bool
    daily_report_index_exists: bool
    report_json_exists: bool
    failures: tuple[ProductionVerificationFailure, ...]

    @property
    def failure_class(self) -> FailureClass | None:
        if not self.failures:
            return None
        return self.failures[0].failure_class

    @property
    def fix_suggestion(self) -> str | None:
        if not self.failures:
            return None
        return self.failures[0].fix_suggestion


def verify_production_result(
    project_root: Path,
    repository,
    trade_date: date,
) -> ProductionVerification:
    _ensure_trade_date(trade_date)
    root = Path(project_root)
    reports_dir = root / "reports"

    recommendations = list(repository.load_daily_recommendations(trade_date))
    evidence_packages = list(repository.load_evidence_packages(trade_date))
    evaluation_tasks = list(repository.load_evaluation_tasks(trade_date))
    market_rows = _count_current_day_rows(
        repository,
        attr_name="market_bars",
        table_name="market_price_daily",
        trade_date=trade_date,
    )
    daily_basic_rows = _count_current_day_rows(
        repository,
        attr_name="daily_basic_indicators",
        table_name="daily_basic_indicator",
        trade_date=trade_date,
    )

    report_index = reports_dir / "index.html"
    daily_report_index = reports_dir / "daily" / trade_date.isoformat() / "index.html"
    report_json = reports_dir / "data" / "latest.json"
    report_index_exists = report_index.exists()
    daily_report_index_exists = daily_report_index.exists()
    report_json_exists = report_json.exists()

    failures: list[ProductionVerificationFailure] = []

    if not 0 <= len(recommendations) <= MAX_DAILY_RECOMMENDATIONS:
        failures.append(
            ProductionVerificationFailure(
                code="recommendation_count_out_of_range",
                message=(
                    f"Expected 0-{MAX_DAILY_RECOMMENDATIONS} recommendations, "
                    f"found {len(recommendations)}."
                ),
                fix_suggestion=(
                    "Review the recommendation selection limit and rerun the daily "
                    "pipeline after clearing only the target trade_date outputs."
                ),
            )
        )

    if len(evidence_packages) != len(recommendations):
        failures.append(
            ProductionVerificationFailure(
                code="evidence_count_mismatch",
                message=(
                    f"Expected {len(recommendations)} evidence packages, "
                    f"found {len(evidence_packages)}."
                ),
                fix_suggestion=(
                    "Regenerate evidence packages for each recommendation and verify "
                    "that stale same-day rows were cleaned before retrying."
                ),
            )
        )

    expected_evaluation_tasks = (
        len(recommendations) * EVALUATION_TASKS_PER_RECOMMENDATION
    )
    if len(evaluation_tasks) != expected_evaluation_tasks:
        failures.append(
            ProductionVerificationFailure(
                code="evaluation_task_count_mismatch",
                message=(
                    f"Expected {expected_evaluation_tasks} evaluation tasks, "
                    f"found {len(evaluation_tasks)}."
                ),
                fix_suggestion=(
                    "Recreate evaluation tasks from the evidence packages so each "
                    "recommendation has the configured evaluation schedule."
                ),
            )
        )

    _append_selected_market_failures(
        failures,
        repository,
        trade_date,
        market_rows,
        daily_basic_rows,
    )
    _append_report_artifact_failures(
        failures,
        reports_dir,
        trade_date,
        report_index_exists,
        daily_report_index_exists,
        report_json,
        report_json_exists,
    )

    passed = not failures
    status = _verification_status(passed, len(recommendations))
    return ProductionVerification(
        trade_date=trade_date,
        status=status,
        passed=passed,
        recommendations=len(recommendations),
        evidence_packages=len(evidence_packages),
        evaluation_tasks=len(evaluation_tasks),
        market_price_daily_current_day_rows=market_rows,
        daily_basic_indicator_current_day_rows=daily_basic_rows,
        report_index_exists=report_index_exists,
        daily_report_index_exists=daily_report_index_exists,
        report_json_exists=report_json_exists,
        failures=tuple(failures),
    )


def _append_selected_market_failures(
    failures: list[ProductionVerificationFailure],
    repository,
    trade_date: date,
    market_rows: int,
    daily_basic_rows: int,
) -> None:
    if (
        market_rows > MAX_SELECTED_WINDOW_ROWS
        or daily_basic_rows > MAX_SELECTED_WINDOW_ROWS
    ):
        failures.append(
            ProductionVerificationFailure(
                code="selected_market_rows_too_large",
                message=(
                    "Selected market rows exceed the Supabase selected-window limit: "
                    f"market_price_daily={market_rows}, "
                    f"daily_basic_indicator={daily_basic_rows}."
                ),
                fix_suggestion=(
                    "Stop publishing this run, inspect selected-code filtering, and "
                    "clean only the target trade_date before rerunning."
                ),
                failure_class=FailureClass.POSSIBLE_FULL_MARKET_WRITE,
            )
        )

    code_count = _current_day_unique_code_count(repository, trade_date)
    if code_count is not None and code_count > MAX_SELECTED_WINDOW_CODES:
        failures.append(
            ProductionVerificationFailure(
                code="selected_market_codes_too_large",
                message=(
                    "Selected market code count exceeds the Supabase selected-window "
                    f"limit: {code_count} codes."
                ),
                fix_suggestion=(
                    "Review selected decision codes before retrying; production "
                    "Supabase writes must remain limited to recommendations, active "
                    "focus stocks, and approved controls."
                ),
                failure_class=FailureClass.POSSIBLE_FULL_MARKET_WRITE,
            )
        )


def _append_report_artifact_failures(
    failures: list[ProductionVerificationFailure],
    reports_dir: Path,
    trade_date: date,
    report_index_exists: bool,
    daily_report_index_exists: bool,
    report_json: Path,
    report_json_exists: bool,
) -> None:
    if not report_index_exists:
        failures.append(
            ProductionVerificationFailure(
                code="report_index_missing",
                message="reports/index.html is missing.",
                fix_suggestion=(
                    "Rerun report generation for the target trade_date; do not prepare "
                    "or deploy a package until reports/index.html exists."
                ),
            )
        )

    if not daily_report_index_exists:
        failures.append(
            ProductionVerificationFailure(
                code="daily_report_index_missing",
                message=(
                    f"reports/daily/{trade_date.isoformat()}/index.html is missing."
                ),
                fix_suggestion=(
                    "Rerun report generation for the target trade_date and confirm the "
                    "daily report index was written."
                ),
            )
        )

    if not report_json_exists:
        failures.append(
            ProductionVerificationFailure(
                code="report_json_missing",
                message="reports/data/latest.json is missing.",
                fix_suggestion=(
                    "Regenerate the report payload before publishing; latest.json is "
                    "required for production verification."
                ),
            )
        )
    else:
        _append_report_json_failures(failures, report_json, trade_date)

    leak_path = _find_fixture_sample_leak(reports_dir)
    if leak_path is not None:
        failures.append(
            ProductionVerificationFailure(
                code="fixture_sample_leak",
                message=f"Fixture/sample marker found in {leak_path}.",
                fix_suggestion=(
                    "Stop publishing this run and rerun without fixture-mode or sample "
                    "data inputs after cleaning only the target trade_date outputs."
                ),
                failure_class=FailureClass.FIXTURE_SAMPLE_IN_PRODUCTION,
            )
        )


def _append_report_json_failures(
    failures: list[ProductionVerificationFailure],
    report_json: Path,
    trade_date: date,
) -> None:
    try:
        payload = json.loads(report_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        failures.append(
            ProductionVerificationFailure(
                code="report_json_invalid",
                message=f"reports/data/latest.json is not valid JSON: {exc}.",
                fix_suggestion=(
                    "Regenerate the report payload and keep the previous published "
                    "report in place until latest.json is valid."
                ),
            )
        )
        return

    report_date = payload.get("trade_date")
    if report_date != trade_date.isoformat():
        failures.append(
            ProductionVerificationFailure(
                code="report_date_mismatch",
                message=(
                    "Report payload trade_date does not match verification trade_date: "
                    f"{report_date!r} != {trade_date.isoformat()!r}."
                ),
                fix_suggestion=(
                    "Regenerate reports for the requested trade_date and verify that "
                    "reports/data/latest.json points at the same date."
                ),
            )
        )

    if payload.get("is_fixture") is True or payload.get("report_mode") == "fixture":
        failures.append(
            ProductionVerificationFailure(
                code="fixture_sample_leak",
                message="Report payload is marked as fixture/sample output.",
                fix_suggestion=(
                    "Stop publishing this run and rerun the production pipeline without "
                    "fixture-mode or sample data inputs."
                ),
                failure_class=FailureClass.FIXTURE_SAMPLE_IN_PRODUCTION,
            )
        )


def _verification_status(passed: bool, recommendation_count: int) -> RunStatus:
    if not passed:
        return RunStatus.FAILED_NEEDS_HUMAN
    if recommendation_count == 0:
        return RunStatus.SUCCESS_NO_RECOMMENDATIONS
    return RunStatus.SUCCESS_WITH_RECOMMENDATIONS


def _ensure_trade_date(value: date) -> None:
    if not isinstance(value, date) or isinstance(value, datetime):
        raise ValueError("trade_date must be a date instance")


def _count_current_day_rows(
    repository,
    *,
    attr_name: str,
    table_name: str,
    trade_date: date,
) -> int:
    method = getattr(repository, f"count_{table_name}_rows", None)
    if callable(method):
        return int(method(trade_date))

    rows = getattr(repository, attr_name, None)
    if rows is not None:
        return _count_rows_for_date(rows, trade_date)

    supabase_count = _count_supabase_rows(repository, table_name, trade_date)
    if supabase_count is not None:
        return supabase_count

    return 0


def _count_rows_for_date(rows: Any, trade_date: date) -> int:
    return sum(1 for item in rows if getattr(item, "trade_date", None) == trade_date)


def _count_supabase_rows(repository, table_name: str, trade_date: date) -> int | None:
    client = getattr(repository, "client", None)
    if client is None:
        return None
    result = (
        client.table(table_name)
        .select("ts_code", count="exact")
        .eq("trade_date", trade_date.isoformat())
        .execute()
    )
    count = getattr(result, "count", None)
    if count is not None:
        return int(count)
    return len(getattr(result, "data", None) or [])


def _current_day_unique_code_count(repository, trade_date: date) -> int | None:
    codes: set[str] = set()
    saw_rows = False
    for attr_name in ("market_bars", "daily_basic_indicators"):
        rows = getattr(repository, attr_name, None)
        if rows is None:
            continue
        saw_rows = True
        codes.update(
            getattr(item, "ts_code", "")
            for item in rows
            if getattr(item, "trade_date", None) == trade_date
        )
    if not saw_rows:
        return None
    return len(codes)


def _find_fixture_sample_leak(reports_dir: Path) -> str | None:
    if not reports_dir.exists():
        return None
    for path in sorted(reports_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() != ".html":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = path.read_text(encoding="utf-8", errors="ignore")
        if _contains_fixture_sample_marker(text):
            return path.relative_to(reports_dir.parent).as_posix()
    return None


def _contains_fixture_sample_marker(text: str) -> bool:
    return any(pattern.search(text) for pattern in FIXTURE_SAMPLE_PATTERNS)
