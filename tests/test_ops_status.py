import json
from datetime import date

from stock_analyzer.ops.redaction import redact_secrets
from stock_analyzer.ops.status import JobStatus, RunStatus


def test_run_status_values_match_operations_plan():
    assert [status.value for status in RunStatus] == [
        "success_with_recommendations",
        "success_no_recommendations",
        "skipped_non_trading_day",
        "calendar_unknown",
        "warning",
        "failed_retryable",
        "failed_needs_human",
    ]


def test_job_status_writes_complete_machine_json(tmp_path):
    output_path = tmp_path / "logs" / "run-daily" / "latest-status.json"
    raw_error = (
        "temporary upstream error for fake-secret-value; "
        "Authorization: Bearer fake-bearer-token"
    )
    status = JobStatus(
        trade_date=date(2026, 7, 9),
        attempt=1,
        scheduled_slot="18:30",
        status=RunStatus.SUCCESS_NO_RECOMMENDATIONS,
        stage="complete",
        recommendations=0,
        evidence_packages=0,
        evaluation_tasks=0,
        fix_suggestion="No action needed.",
        error_message_redacted=redact_secrets(
            raw_error,
            explicit_secrets=["fake-secret-value"],
        ),
    )

    status.write_json(output_path)

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert {
        "trade_date",
        "attempt",
        "scheduled_slot",
        "started_at",
        "finished_at",
        "status",
        "stage",
        "failure_class",
        "retryable",
        "cleanup_performed",
        "cleanup_summary",
        "recommendations",
        "evidence_packages",
        "evaluation_tasks",
        "market_price_daily_current_day_rows",
        "daily_basic_indicator_current_day_rows",
        "supabase_database_size_mb",
        "report_index_exists",
        "archive_manifest_exists",
        "warehouse_updated",
        "deploy_artifact_prepared",
        "publish_skipped_reason",
        "fix_suggestion",
        "error_message_redacted",
    } <= set(payload)
    assert payload["trade_date"] == "2026-07-09"
    assert payload["attempt"] == 1
    assert payload["scheduled_slot"] == "18:30"
    assert payload["status"] == "success_no_recommendations"
    assert payload["stage"] == "complete"
    assert payload["fix_suggestion"] == "No action needed."

    written_text = output_path.read_text(encoding="utf-8")
    assert "fake-secret-value" not in written_text
    assert "fake-bearer-token" not in written_text


def test_redact_secrets_removes_explicit_values_and_bearer_tokens():
    redacted = redact_secrets(
        "failed with fake-secret-value and Authorization: Bearer fake-bearer-token",
        explicit_secrets=["fake-secret-value"],
    )

    assert "fake-secret-value" not in redacted
    assert "fake-bearer-token" not in redacted
    assert "[REDACTED]" in redacted
