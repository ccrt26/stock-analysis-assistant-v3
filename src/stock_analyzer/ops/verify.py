from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from html import unescape
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from stock_analyzer.ops.formal_narrative import FormalNarrative
from stock_analyzer.ops.status import FailureClass, RunStatus
from stock_analyzer.storage.capacity_guard import (
    MAX_SELECTED_WINDOW_CODES,
    MAX_SELECTED_WINDOW_ROWS,
)


MAX_DAILY_RECOMMENDATIONS = 10
EVALUATION_TASKS_PER_RECOMMENDATION = 6
VALID_REPORT_MODES = ("production",)
FIXTURE_SAMPLE_PATTERNS = (
    re.compile(r"fixture/sample", re.IGNORECASE),
    re.compile(r"\bfixture\b", re.IGNORECASE),
    re.compile(r"\bsample\b", re.IGNORECASE),
    re.compile(r"local sample data", re.IGNORECASE),
    re.compile(r"not production data", re.IGNORECASE),
)
VISIBLE_TOTAL_SCORE_PATTERNS = (
    re.compile(
        r"(?:评分|总评分|综合评分|总分)\s*[:：]?\s*"
        r"(?:100(?:\.0+)?|[1-9]?\d(?:\.\d+)?)"
    ),
    re.compile(
        r"(?:total\s+score|score)\s*[:：=]?\s*"
        r"(?:100(?:\.0+)?|[1-9]?\d(?:\.\d+)?)",
        re.IGNORECASE,
    ),
)
REPORT_MAIN_VIEW_HEADINGS = (
    "市场总体结论",
    "推荐股票排序",
    "明确动作与仓位",
    "三条核心理由",
    "买入或继续观察的条件",
    "失效和退出条件",
)
REPORT_INTERNAL_TERM_PATTERNS = (
    re.compile(r"\bgate\b", re.IGNORECASE),
    re.compile(r"\binput\s+set\b", re.IGNORECASE),
    re.compile(r"\bthesis\s+quality\b", re.IGNORECASE),
    re.compile(r"\breceipt\b", re.IGNORECASE),
    re.compile(r"数据就绪凭证"),
)
NARRATIVE_MARKER_PATTERN = re.compile(r"^NARRATIVE-[A-F0-9]{12}$")


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
    recommendation_state: str | None = None
    focus_state: str | None = None
    blocking_missing_fields: tuple[str, ...] = ()

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


def report_readability_failure_codes(
    reports_dir: Path,
    payload: dict[str, Any],
    trade_date: date,
) -> tuple[str, ...]:
    """Return bounded, non-secret REPORT-004 artifact failure codes."""
    reports_dir = Path(reports_dir)
    narrative = payload.get("formal_narrative")
    stocks = narrative.get("stocks") if isinstance(narrative, dict) else None
    market = narrative.get("market") if isinstance(narrative, dict) else None
    snapshots = payload.get("strategy_snapshots")
    if not isinstance(stocks, list) or not isinstance(market, dict):
        return ("formal_narrative_missing",)
    try:
        FormalNarrative.model_validate(narrative)
    except ValidationError:
        return ("formal_narrative_schema_invalid",)
    if not isinstance(snapshots, list):
        return ("formal_narrative_stock_set_invalid",)

    expected_codes = [
        item.get("ts_code")
        for item in snapshots
        if isinstance(item, dict) and _is_non_empty_string(item.get("ts_code"))
    ]
    actual_codes = [
        item.get("ts_code")
        for item in stocks
        if isinstance(item, dict) and _is_non_empty_string(item.get("ts_code"))
    ]
    failures: list[str] = []
    if (
        len(expected_codes) != len(set(expected_codes))
        or len(actual_codes) != len(stocks)
        or len(actual_codes) != len(set(actual_codes))
        or actual_codes != expected_codes
    ):
        failures.append("formal_narrative_stock_set_invalid")

    home = _read_utf8(reports_dir / "index.html")
    daily_home = _read_utf8(
        reports_dir / "daily" / trade_date.isoformat() / "index.html"
    )
    if home is None or daily_home is None:
        failures.append("narrative_home_missing")
        return tuple(dict.fromkeys(failures))

    for page in (home, daily_home):
        if '<details class="audit-details">' not in page:
            failures.append("audit_details_not_collapsed")
            continue
        if '<details class="audit-details" open' in page:
            failures.append("audit_details_not_collapsed")
        main_view = page.split('<details class="audit-details">', 1)[0]
        visible_main = _html_visible_text(main_view)
        if any(pattern.search(visible_main) for pattern in REPORT_INTERNAL_TERM_PATTERNS):
            failures.append("internal_term_in_main_view")
        if any(heading not in visible_main for heading in REPORT_MAIN_VIEW_HEADINGS):
            failures.append("decision_heading_missing")

    market_summary = market.get("summary")
    if (
        not _is_non_empty_string(market_summary)
        or market_summary not in _html_visible_text(home)
    ):
        failures.append("market_narrative_missing_from_home")

    stock_by_code = {
        item.get("ts_code"): item
        for item in stocks
        if isinstance(item, dict) and _is_non_empty_string(item.get("ts_code"))
    }
    snapshot_by_code = {
        item.get("ts_code"): item
        for item in snapshots
        if isinstance(item, dict) and _is_non_empty_string(item.get("ts_code"))
    }
    cards = payload.get("recommendation_cards")
    card_by_code = {
        item.get("ts_code"): item
        for item in cards or []
        if isinstance(item, dict) and _is_non_empty_string(item.get("ts_code"))
    }
    for code in expected_codes:
        stock = stock_by_code.get(code)
        snapshot = snapshot_by_code.get(code)
        if not isinstance(stock, dict) or not isinstance(snapshot, dict):
            continue
        marker = stock.get("narrative_marker")
        if (
            not isinstance(marker, str)
            or not NARRATIVE_MARKER_PATTERN.fullmatch(marker)
        ):
            failures.append("narrative_marker_invalid")
            continue
        stock_page = _read_utf8(
            reports_dir
            / "daily"
            / trade_date.isoformat()
            / "stocks"
            / f"{code}.html"
        )
        if stock_page is None or marker not in stock_page or marker not in home:
            failures.append("narrative_marker_missing")
            continue
        if (
            '<details class="audit-details">' not in stock_page
            or '<details class="audit-details" open' in stock_page
        ):
            failures.append("audit_details_not_collapsed")
        stock_main = stock_page.split('<details class="audit-details">', 1)[0]
        visible_stock = _html_visible_text(stock_main)
        if any(pattern.search(visible_stock) for pattern in REPORT_INTERNAL_TERM_PATTERNS):
            failures.append("internal_term_in_main_view")
        exact_texts = _narrative_exact_texts(stock)
        if any(text not in visible_stock for text in exact_texts):
            failures.append("narrative_text_missing_from_stock")
        if not _narrative_decision_matches(stock, snapshot, card_by_code.get(code)):
            failures.append("narrative_decision_mismatch")

    return tuple(dict.fromkeys(failures))


def verify_production_result(
    project_root: Path,
    repository,
    trade_date: date,
    *,
    receipt,
) -> ProductionVerification:
    _ensure_trade_date(trade_date)
    _require_activated_report_receipt(receipt, trade_date)
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
    artifact_paths = _receipt_artifact_paths(reports_dir, receipt)

    failures: list[ProductionVerificationFailure] = []
    report_payload = _load_report_json_payload(
        failures,
        report_json,
        report_json_exists,
    )
    operational_status = _operational_status(report_payload)
    recommendation_state = _string_or_none(
        operational_status.get("recommendation_state")
    )
    focus_state = _string_or_none(operational_status.get("focus_state"))
    blocking_missing_fields = tuple(
        item.strip()
        for item in operational_status.get("blocking_missing_fields", [])
        if isinstance(item, str) and item.strip()
    )
    valid_data_insufficient = _append_operational_status_failures(
        failures,
        report_payload,
        operational_status,
    )

    if (
        not valid_data_insufficient
        and not 0 <= len(recommendations) <= MAX_DAILY_RECOMMENDATIONS
    ):
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

    evidence_ids = [package.evidence_id for package in evidence_packages]
    evidence_id_set = set(evidence_ids)
    recommendation_evidence_ids = {
        recommendation.evidence_id
        for recommendation in recommendations
        if recommendation.evidence_id
    }
    missing_recommendation_evidence = (
        len(recommendation_evidence_ids) != len(recommendations)
        or not recommendation_evidence_ids.issubset(evidence_id_set)
    )
    duplicate_evidence_ids = len(evidence_ids) != len(evidence_id_set)
    if (
        not valid_data_insufficient
        and (missing_recommendation_evidence or duplicate_evidence_ids)
    ):
        failures.append(
            ProductionVerificationFailure(
                code="evidence_count_mismatch",
                message=(
                    "Every recommendation must reference one unique active evidence "
                    "package; focus-only packages are allowed."
                ),
                fix_suggestion=(
                    "Regenerate the combined recommendation/focus evidence set and "
                    "remove missing or duplicate evidence identifiers before retrying."
                ),
            )
        )

    expected_evaluation_tasks = (
        len(evidence_packages) * EVALUATION_TASKS_PER_RECOMMENDATION
    )
    task_counts = Counter(task.evidence_id for task in evaluation_tasks)
    invalid_task_evidence = set(task_counts) - evidence_id_set
    incomplete_task_evidence = {
        evidence_id
        for evidence_id in evidence_id_set
        if task_counts[evidence_id] != EVALUATION_TASKS_PER_RECOMMENDATION
    }
    if (
        not valid_data_insufficient
        and (
            len(evaluation_tasks) != expected_evaluation_tasks
            or invalid_task_evidence
            or incomplete_task_evidence
        )
    ):
        failures.append(
            ProductionVerificationFailure(
                code="evaluation_task_count_mismatch",
                message=(
                    f"Expected {expected_evaluation_tasks} evaluation tasks, "
                    f"found {len(evaluation_tasks)}."
                ),
                fix_suggestion=(
                    "Recreate evaluation tasks from the active evidence packages so "
                    "each recommendation or focus package has six tasks and no task "
                    "references an unknown package."
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
        report_payload,
        artifact_paths,
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
        recommendation_state=recommendation_state,
        focus_state=focus_state,
        blocking_missing_fields=blocking_missing_fields,
    )


def _require_activated_report_receipt(receipt, trade_date: date) -> None:
    from stock_analyzer.data.readiness import FormalRunState

    if (
        receipt is None
        or getattr(receipt, "target_date", None) != trade_date
        or getattr(receipt, "state", None) != FormalRunState.REPORT_GENERATED
        or not getattr(receipt, "group_version_ids", None)
        or getattr(receipt, "input_set_id", None) is None
        or getattr(receipt, "candidate_set_id", None) is None
        or not getattr(receipt, "evidence_hashes", None)
        or not getattr(receipt, "artifact_hashes", None)
        or getattr(receipt, "local_activation_id", None) is None
        or getattr(receipt, "local_activation_id", None)
        != getattr(receipt, "ledger_activation_id", None)
    ):
        raise ValueError(
            "Production verification requires an activated REPORT_GENERATED receipt."
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
    report_payload: dict[str, Any] | None,
    artifact_paths: tuple[Path, ...],
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
    elif report_payload is not None:
        _append_report_json_failures(failures, report_payload, trade_date)
        if report_payload.get("strategy_snapshots"):
            readability_codes = report_readability_failure_codes(
                reports_dir,
                report_payload,
                trade_date,
            )
            if readability_codes:
                failures.append(
                    ProductionVerificationFailure(
                        code="report_readability_invalid",
                        message=(
                            "Formal report readability verification failed: "
                            + ", ".join(readability_codes)
                            + "."
                        ),
                        fix_suggestion=(
                            "Keep the prior active report and regenerate the formal "
                            "candidate with a validated narrative present in the home "
                            "and matching stock pages."
                        ),
                    )
                )

    leak_path = _find_fixture_sample_leak(reports_dir, artifact_paths)
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

    if _should_scan_visible_total_scores(report_payload):
        score_leak_path = _find_visible_total_score_leak(
            reports_dir,
            artifact_paths,
        )
        if score_leak_path is not None:
            failures.append(
                ProductionVerificationFailure(
                    code="visible_total_score",
                    message=(
                        "Visible Strategy V2 total score text found in "
                        f"{score_leak_path}."
                    ),
                    fix_suggestion=(
                        "Remove total numeric score labels from production HTML; "
                        "keep internal_score only inside structured latest.json "
                        "strategy_snapshots."
                    ),
                )
            )


def _append_report_json_failures(
    failures: list[ProductionVerificationFailure],
    payload: dict[str, Any],
    trade_date: date,
) -> None:
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

    payload_marked_fixture = (
        payload.get("is_fixture") is True or payload.get("report_mode") == "fixture"
    )
    if payload_marked_fixture:
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
    else:
        marker_path = _find_fixture_sample_json_marker(payload)
        if marker_path is not None:
            failures.append(
                ProductionVerificationFailure(
                    code="fixture_sample_leak",
                    message=(
                        "Fixture/sample marker found in report payload at "
                        f"{marker_path}."
                    ),
                    fix_suggestion=(
                        "Stop publishing this run and rerun the production pipeline "
                        "without fixture-mode or sample data inputs."
                    ),
                    failure_class=FailureClass.FIXTURE_SAMPLE_IN_PRODUCTION,
                )
            )


def _load_report_json_payload(
    failures: list[ProductionVerificationFailure],
    report_json: Path,
    report_json_exists: bool,
) -> dict[str, Any] | None:
    if not report_json_exists:
        return None
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
        return None
    if not isinstance(payload, dict):
        failures.append(
            ProductionVerificationFailure(
                code="report_json_invalid",
                message="reports/data/latest.json must be a JSON object.",
                fix_suggestion=(
                    "Regenerate the report payload with the Strategy V2 report "
                    "contract object shape before publishing."
                ),
            )
        )
        return None
    return payload


def _append_operational_status_failures(
    failures: list[ProductionVerificationFailure],
    payload: dict[str, Any] | None,
    operational_status: dict[str, Any],
) -> bool:
    if payload is None:
        return False

    report_mode = payload.get("report_mode")
    if report_mode != "production":
        failures.append(
            ProductionVerificationFailure(
                code="report_mode_invalid",
                message=(
                    "Report payload report_mode must be one of "
                    f"{', '.join(VALID_REPORT_MODES)}; found {report_mode!r}."
                ),
                fix_suggestion=(
                    "Regenerate latest.json only after READY_TO_ANALYZE with "
                    "report_mode='production' and generated operational_status."
                ),
            )
        )
        return False

    if not _has_generated_operational_states(operational_status):
        failures.append(
            ProductionVerificationFailure(
                code="trading_day_output_state_invalid",
                message=(
                    "Trading-day production reports must record generated "
                    "recommendation_state and focus_state."
                ),
                fix_suggestion=(
                    "Regenerate the report after Strategy V2 recommendations and "
                    "focus output are generated after READY_TO_ANALYZE."
                ),
            )
        )
    return False


def _has_generated_operational_states(operational_status: dict[str, Any]) -> bool:
    return (
        operational_status.get("recommendation_state") == "generated"
        and operational_status.get("focus_state") == "generated"
    )


def _append_data_insufficient_failures(
    failures: list[ProductionVerificationFailure],
    operational_status: dict[str, Any],
) -> bool:
    valid = True
    if (
        operational_status.get("is_trading_day") is not True
        or operational_status.get("recommendation_state") != "data_insufficient"
        or operational_status.get("focus_state") != "data_insufficient"
    ):
        failures.append(
            ProductionVerificationFailure(
                code="data_insufficient_operational_status_invalid",
                message=(
                    "Data-insufficient reports must explicitly mark a trading day "
                    "with recommendation_state and focus_state set to "
                    "data_insufficient."
                ),
                fix_suggestion=(
                    "Write operational_status.is_trading_day=true and set both "
                    "generation states to data_insufficient before publishing."
                ),
            )
        )
        valid = False

    recovery_attempts = operational_status.get("data_recovery_attempts")
    blocking_fields = operational_status.get("blocking_missing_fields")
    has_recovery_attempt = _has_structured_recovery_attempts(recovery_attempts)
    has_blocking_field = (
        isinstance(blocking_fields, list)
        and any(isinstance(item, str) and item.strip() for item in blocking_fields)
    )
    recovery_missing = (
        not has_recovery_attempt
        or not has_blocking_field
    )
    if recovery_missing:
        valid = False
        failures.append(
            ProductionVerificationFailure(
                code="data_insufficient_recovery_missing",
                message=(
                    "Data-insufficient reports must include at least one recovery "
                    "attempt and at least one blocking missing field."
                ),
                fix_suggestion=(
                    "Record data_recovery_attempts with family, source_name, and "
                    "status, plus blocking_missing_fields in latest.json "
                    "operational_status before accepting the run."
                ),
            )
        )
    return valid


def _has_structured_recovery_attempts(value: Any) -> bool:
    if not isinstance(value, list) or not value:
        return False
    return all(_is_structured_recovery_attempt(item) for item in value)


def _is_structured_recovery_attempt(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    required_fields = ("family", "source_name", "status")
    return all(_is_non_empty_string(value.get(field)) for field in required_fields)


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _operational_status(payload: dict[str, Any] | None) -> dict[str, Any]:
    if payload is None:
        return {}
    status = payload.get("operational_status")
    if isinstance(status, dict):
        return status
    return {}


def _string_or_none(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    return None


def _should_scan_visible_total_scores(
    payload: dict[str, Any] | None,
) -> bool:
    if payload is None:
        return False
    cards = payload.get("recommendation_cards")
    if isinstance(cards, list) and bool(cards):
        return True
    snapshots = payload.get("strategy_snapshots")
    if isinstance(snapshots, list) and bool(snapshots):
        return True
    return _has_generated_operational_states(_operational_status(payload))


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
    method = getattr(repository, "count_selected_market_codes", None)
    if callable(method):
        return int(method(trade_date))

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
        return _count_supabase_unique_codes(repository, trade_date)
    return len(codes)


def _count_supabase_unique_codes(repository, trade_date: date) -> int | None:
    client = getattr(repository, "client", None)
    if client is None:
        return None

    codes: set[str] = set()
    for table_name in ("market_price_daily", "daily_basic_indicator"):
        result = (
            client.table(table_name)
            .select("ts_code")
            .eq("trade_date", trade_date.isoformat())
            .execute()
        )
        codes.update(
            row.get("ts_code")
            for row in getattr(result, "data", None) or []
            if row.get("ts_code")
        )
    return len(codes)


def _receipt_artifact_paths(reports_dir: Path, receipt) -> tuple[Path, ...]:
    result: list[Path] = []
    for relative_name in sorted(receipt.artifact_hashes):
        relative_path = Path(relative_name)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError("Formal receipt contains an unsafe artifact path.")
        result.append(reports_dir / relative_path)
    return tuple(result)


def _find_fixture_sample_leak(
    reports_dir: Path,
    artifact_paths: tuple[Path, ...],
) -> str | None:
    for path in artifact_paths:
        if not path.is_file() or path.suffix.lower() != ".html":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = path.read_text(encoding="utf-8", errors="ignore")
        if _contains_fixture_sample_marker(text):
            return path.relative_to(reports_dir.parent).as_posix()
    return None


def _find_visible_total_score_leak(
    reports_dir: Path,
    artifact_paths: tuple[Path, ...],
) -> str | None:
    for path in artifact_paths:
        if not path.is_file() or path.suffix.lower() != ".html":
            continue
        try:
            html_text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            html_text = path.read_text(encoding="utf-8", errors="ignore")
        visible_text = _html_visible_text(html_text)
        if any(pattern.search(visible_text) for pattern in VISIBLE_TOTAL_SCORE_PATTERNS):
            return path.relative_to(reports_dir.parent).as_posix()
    return None


def _read_utf8(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _narrative_exact_texts(stock: dict[str, Any]) -> tuple[str, ...]:
    points: list[Any] = [stock.get("analysis_summary")]
    points.extend(stock.get("core_reasons") or [])
    points.extend(stock.get("five_day_progress") or [])
    return tuple(
        point["text"]
        for point in points
        if isinstance(point, dict) and _is_non_empty_string(point.get("text"))
    )


def _narrative_decision_matches(
    stock: dict[str, Any],
    snapshot: dict[str, Any],
    card: dict[str, Any] | None,
) -> bool:
    action = snapshot.get("action")
    if not isinstance(action, dict):
        return False
    observation_conditions = (
        card.get("needed_before_focus_entry")
        if isinstance(card, dict) and card.get("needed_before_focus_entry")
        else action.get("required_confirmation")
    )
    expected = {
        "action": action.get("decision"),
        "position_min_pct": action.get("position_min_pct"),
        "position_max_pct": action.get("position_max_pct"),
        "risk_if_wrong": action.get("risk_if_wrong"),
        "required_confirmation": action.get("required_confirmation"),
        "observation_conditions": observation_conditions,
        "invalidation_conditions": action.get("invalidation_conditions"),
        "exit_conditions": action.get("invalidation_conditions"),
    }
    return all(stock.get(field) == value for field, value in expected.items())


def _html_visible_text(html_text: str) -> str:
    text = re.sub(
        r"(?is)<(script|style|template)\b[^>]*>.*?</\1>",
        " ",
        html_text,
    )
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return unescape(re.sub(r"\s+", " ", text))


def _contains_fixture_sample_marker(text: str) -> bool:
    return any(pattern.search(text) for pattern in FIXTURE_SAMPLE_PATTERNS)


def _find_fixture_sample_json_marker(value: Any, path: str = "payload") -> str | None:
    if isinstance(value, str):
        if _contains_fixture_sample_marker(value):
            return path
        return None
    if isinstance(value, dict):
        for key, child in value.items():
            marker_path = _find_fixture_sample_json_marker(
                child,
                f"{path}.{key}" if isinstance(key, str) else f"{path}[{key!r}]",
            )
            if marker_path is not None:
                return marker_path
        return None
    if isinstance(value, list):
        for index, child in enumerate(value):
            marker_path = _find_fixture_sample_json_marker(
                child,
                f"{path}[{index}]",
            )
            if marker_path is not None:
                return marker_path
    return None
