from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from typer.testing import CliRunner

from stock_analyzer.cli import app
from stock_analyzer.ops.calendar import TradingDayDecision
from stock_analyzer.ops.cleanup import CleanupSummary
from stock_analyzer.data.readiness import FormalRunState
from stock_analyzer.ops.formal_run import RunReceipt
from stock_analyzer.ops.job import (
    HumanInterventionJobError,
    RetryableJobError,
    _default_run_daily,
    _default_publish,
    run_daily_job,
)
from stock_analyzer.ops.status import FailureClass, JobStatus, RunStatus
from stock_analyzer.data.models import DailyBar, DailyBasicRow, SourceGrade
from stock_analyzer.data.provider import CurrentLiveDataUnavailable
from stock_analyzer.domain.models import (
    ActionLabel,
    EvaluationTask,
    EvidencePackage,
    Recommendation,
)
from stock_analyzer.ops.verify import (
    ProductionVerification,
    ProductionVerificationFailure,
    verify_production_result,
)
from stock_analyzer.storage.capacity_guard import (
    MAX_SELECTED_WINDOW_CODES,
    MAX_SELECTED_WINDOW_ROWS,
)


def _activated_receipt(trade_date: date) -> RunReceipt:
    return RunReceipt(
        run_id=f"verified-{trade_date.isoformat()}",
        target_date=trade_date,
        report_cutoff=datetime(
            trade_date.year,
            trade_date.month,
            trade_date.day,
            16,
            tzinfo=ZoneInfo("Asia/Shanghai"),
        ),
        acquisition_contract_version="formal-v1",
        screening_version="screen-v1",
        state=FormalRunState.REPORT_GENERATED,
        group_version_ids={"market_decision": "version-1"},
        input_set_id="input-1",
        candidate_set_id="candidate-1",
        evidence_hashes={"evidence": "hash"},
        artifact_hashes={"index.html": "hash"},
        local_activation_id="activation-1",
        ledger_activation_id="activation-1",
    )


def _verify(project_root, repository, trade_date):
    return verify_production_result(
        project_root,
        repository,
        trade_date,
        receipt=_activated_receipt(trade_date),
    )


def test_verify_accepts_zero_recommendations_as_success_no_recommendations(tmp_path):
    trade_date = date(2026, 7, 9)
    repository = FakeVerificationRepository()
    _write_production_report(tmp_path, trade_date)

    verification = _verify(tmp_path, repository, trade_date)

    assert verification.passed is True
    assert verification.status == RunStatus.SUCCESS_NO_RECOMMENDATIONS
    assert verification.recommendations == 0
    assert verification.evidence_packages == 0
    assert verification.evaluation_tasks == 0
    assert verification.failures == ()


def test_verify_accepts_recommendations_when_counts_and_artifacts_match(tmp_path):
    trade_date = date(2026, 7, 9)
    recommendations = [
        _recommendation(trade_date, "600000.SH"),
        _recommendation(trade_date, "600519.SH"),
    ]
    repository = FakeVerificationRepository(
        recommendations=recommendations,
        evidence_packages=[
            _evidence_package(trade_date, "600000.SH"),
            _evidence_package(trade_date, "600519.SH"),
        ],
        evaluation_tasks=[
            task
            for recommendation in recommendations
            for task in _evaluation_tasks(recommendation)
        ],
        market_bars=[_daily_bar(trade_date, "600000.SH")],
        daily_basic_indicators=[_daily_basic(trade_date, "600000.SH")],
    )
    _write_production_report(tmp_path, trade_date)

    verification = _verify(tmp_path, repository, trade_date)

    assert verification.passed is True
    assert verification.status == RunStatus.SUCCESS_WITH_RECOMMENDATIONS
    assert verification.recommendations == 2
    assert verification.evidence_packages == 2
    assert verification.evaluation_tasks == 12
    assert verification.market_price_daily_current_day_rows == 1
    assert verification.daily_basic_indicator_current_day_rows == 1


def test_verify_accepts_additional_focus_evidence_with_complete_evaluation_tasks(
    tmp_path,
):
    trade_date = date(2026, 7, 9)
    recommendations = [
        _recommendation(trade_date, "600000.SH"),
        _recommendation(trade_date, "600519.SH"),
    ]
    focus_code = "000001.SZ"
    all_evidence_codes = [
        *(item.ts_code for item in recommendations),
        focus_code,
    ]
    repository = FakeVerificationRepository(
        recommendations=recommendations,
        evidence_packages=[
            _evidence_package(trade_date, code) for code in all_evidence_codes
        ],
        evaluation_tasks=[
            task
            for code in all_evidence_codes
            for task in _evaluation_tasks(_recommendation(trade_date, code))
        ],
    )
    _write_production_report(tmp_path, trade_date)

    verification = _verify(tmp_path, repository, trade_date)

    assert verification.passed is True
    assert verification.recommendations == 2
    assert verification.evidence_packages == 3
    assert verification.evaluation_tasks == 18


def test_verify_rejects_evaluation_task_for_unknown_evidence(tmp_path):
    trade_date = date(2026, 7, 9)
    recommendation = _recommendation(trade_date, "600000.SH")
    tasks = _evaluation_tasks(recommendation)
    tasks[-1] = tasks[-1].model_copy(update={"evidence_id": "unknown-evidence"})
    repository = FakeVerificationRepository(
        recommendations=[recommendation],
        evidence_packages=[_evidence_package(trade_date, "600000.SH")],
        evaluation_tasks=tasks,
    )
    _write_production_report(tmp_path, trade_date)

    verification = _verify(tmp_path, repository, trade_date)

    assert verification.passed is False
    assert _failure(verification, "evaluation_task_count_mismatch").fix_suggestion


def test_verify_fails_when_recommendations_exceed_daily_limit(tmp_path):
    trade_date = date(2026, 7, 9)
    recommendations = [
        _recommendation(trade_date, f"600{i:03d}.SH")
        for i in range(11)
    ]
    repository = FakeVerificationRepository(
        recommendations=recommendations,
        evidence_packages=[
            _evidence_package(trade_date, recommendation.ts_code)
            for recommendation in recommendations
        ],
        evaluation_tasks=[
            task
            for recommendation in recommendations
            for task in _evaluation_tasks(recommendation)
        ],
    )
    _write_production_report(tmp_path, trade_date)

    verification = _verify(tmp_path, repository, trade_date)

    assert verification.passed is False
    assert verification.status == RunStatus.FAILED_NEEDS_HUMAN
    assert _failure(verification, "recommendation_count_out_of_range").fix_suggestion


def test_verify_fails_when_evidence_count_does_not_match_recommendations(tmp_path):
    trade_date = date(2026, 7, 9)
    recommendation = _recommendation(trade_date, "600000.SH")
    repository = FakeVerificationRepository(
        recommendations=[recommendation],
        evidence_packages=[],
        evaluation_tasks=_evaluation_tasks(recommendation),
    )
    _write_production_report(tmp_path, trade_date)

    verification = _verify(tmp_path, repository, trade_date)

    assert verification.passed is False
    assert _failure(verification, "evidence_count_mismatch").fix_suggestion


def test_verify_fails_when_evaluation_task_count_is_not_six_per_recommendation(
    tmp_path,
):
    trade_date = date(2026, 7, 9)
    recommendation = _recommendation(trade_date, "600000.SH")
    repository = FakeVerificationRepository(
        recommendations=[recommendation],
        evidence_packages=[_evidence_package(trade_date, "600000.SH")],
        evaluation_tasks=_evaluation_tasks(recommendation)[:-1],
    )
    _write_production_report(tmp_path, trade_date)

    verification = _verify(tmp_path, repository, trade_date)

    assert verification.passed is False
    assert _failure(verification, "evaluation_task_count_mismatch").fix_suggestion


def test_verify_fails_when_selected_market_rows_reach_full_market_scale(tmp_path):
    trade_date = date(2026, 7, 9)
    repository = FakeVerificationRepository(
        market_bars=[
            _daily_bar(trade_date, f"600{i % 40:03d}.SH")
            for i in range(MAX_SELECTED_WINDOW_ROWS + 1)
        ],
    )
    _write_production_report(tmp_path, trade_date)

    verification = _verify(tmp_path, repository, trade_date)

    assert verification.passed is False
    assert _failure(verification, "selected_market_rows_too_large").fix_suggestion


def test_verify_fails_when_supabase_selected_market_codes_exceed_limit(tmp_path):
    trade_date = date(2026, 7, 9)
    client = FakeVerificationSupabaseClient(
        {
            "market_price_daily": [
                {
                    "trade_date": trade_date.isoformat(),
                    "ts_code": f"600{i:03d}.SH",
                }
                for i in range(MAX_SELECTED_WINDOW_CODES + 1)
            ],
            "daily_basic_indicator": [],
        }
    )
    repository = FakeSupabaseVerificationRepository(client)
    _write_production_report(tmp_path, trade_date)

    verification = _verify(tmp_path, repository, trade_date)

    assert verification.passed is False
    assert _failure(verification, "selected_market_codes_too_large").fix_suggestion


def test_verify_fails_when_report_date_differs_from_trade_date(tmp_path):
    trade_date = date(2026, 7, 9)
    _write_production_report(tmp_path, date(2026, 7, 8))

    verification = _verify(
        tmp_path,
        FakeVerificationRepository(),
        trade_date,
    )

    assert verification.passed is False
    assert _failure(verification, "report_date_mismatch").fix_suggestion


def test_verify_fails_when_fixture_or_sample_strings_leak_into_reports(tmp_path):
    trade_date = date(2026, 7, 9)
    _write_production_report(
        tmp_path,
        trade_date,
        index_html="<html>Fixture/sample report: generated from local sample data</html>",
    )

    verification = _verify(
        tmp_path,
        FakeVerificationRepository(),
        trade_date,
    )

    assert verification.passed is False
    assert _failure(verification, "fixture_sample_leak").fix_suggestion


def test_verify_ignores_historical_leaks_outside_activated_receipt_artifacts(
    tmp_path,
):
    trade_date = date(2026, 7, 9)
    _write_production_report(tmp_path, trade_date)
    historical = tmp_path / "reports" / "daily" / "2026-07-07" / "index.html"
    historical.parent.mkdir(parents=True)
    historical.write_text(
        "<html>Fixture/sample report 总评分：83.2</html>",
        encoding="utf-8",
    )

    verification = _verify(
        tmp_path,
        FakeVerificationRepository(),
        trade_date,
    )

    assert verification.passed is True


def test_verify_fails_when_fixture_or_sample_strings_leak_into_report_json(tmp_path):
    trade_date = date(2026, 7, 9)
    _write_production_report(
        tmp_path,
        trade_date,
        report_json_payload={
            "trade_date": trade_date.isoformat(),
            "report_mode": "production",
            "is_fixture": False,
            "sections": [
                {
                    "title": "Signals",
                    "note": "generated from local sample data",
                }
            ],
            "recommendations": [],
        },
    )

    verification = _verify(
        tmp_path,
        FakeVerificationRepository(),
        trade_date,
    )

    assert verification.passed is False
    assert _failure(verification, "fixture_sample_leak").fix_suggestion


def test_verify_ignores_false_fixture_flags_in_report_json(tmp_path):
    trade_date = date(2026, 7, 9)
    _write_production_report(
        tmp_path,
        trade_date,
        report_json_payload={
            "trade_date": trade_date.isoformat(),
            "report_mode": "production",
            "is_fixture": False,
            "quality_flags": {
                "fixture": False,
                "sample": False,
            },
            "recommendations": [],
            "operational_status": {
                "is_trading_day": True,
                "recommendation_state": "generated",
                "focus_state": "generated",
            },
        },
    )

    verification = _verify(
        tmp_path,
        FakeVerificationRepository(),
        trade_date,
    )

    assert verification.passed is True


def test_verify_strategy_v2_fails_when_score_is_visible_in_production_html(
    tmp_path,
):
    trade_date = date(2026, 7, 10)
    _write_production_report(
        tmp_path,
        trade_date,
        index_html="<html><body>评分 83.2</body></html>",
        report_json_payload={
            "trade_date": trade_date.isoformat(),
            "report_mode": "production",
            "is_fixture": False,
            "recommendation_cards": [{"ts_code": "600000.SH"}],
            "strategy_snapshots": [{"internal_score": 83.2}],
            "operational_status": {
                "recommendation_state": "generated",
                "focus_state": "generated",
            },
        },
    )

    verification = _verify(
        tmp_path,
        FakeVerificationRepository(),
        trade_date,
    )

    assert verification.passed is False
    assert _failure(verification, "visible_total_score").fix_suggestion


def test_verify_strategy_v2_score_scan_runs_with_empty_cards_and_generated_status(
    tmp_path,
):
    trade_date = date(2026, 7, 10)
    _write_production_report(
        tmp_path,
        trade_date,
        index_html="<html><body>评分 83.2</body></html>",
        report_json_payload={
            "trade_date": trade_date.isoformat(),
            "report_mode": "production",
            "is_fixture": False,
            "recommendation_cards": [],
            "strategy_snapshots": [{"internal_score": 83.2}],
            "operational_status": {
                "recommendation_state": "generated",
                "focus_state": "generated",
            },
        },
    )

    verification = _verify(
        tmp_path,
        FakeVerificationRepository(),
        trade_date,
    )

    assert verification.passed is False
    assert _failure(verification, "visible_total_score").fix_suggestion


def test_verify_rejects_report_with_missing_report_mode(tmp_path):
    trade_date = date(2026, 7, 10)
    _write_production_report(
        tmp_path,
        trade_date,
        report_json_payload={
            "trade_date": trade_date.isoformat(),
            "is_fixture": False,
            "recommendations": [],
        },
    )

    verification = _verify(
        tmp_path,
        FakeVerificationRepository(),
        trade_date,
    )

    assert verification.passed is False
    failure = _failure(verification, "report_mode_invalid")
    assert "report_mode" in failure.message
    assert failure.fix_suggestion


def test_verify_rejects_report_with_unknown_report_mode(tmp_path):
    trade_date = date(2026, 7, 10)
    _write_production_report(
        tmp_path,
        trade_date,
        report_json_payload={
            "trade_date": trade_date.isoformat(),
            "report_mode": "preview",
            "is_fixture": False,
            "recommendations": [],
        },
    )

    verification = _verify(
        tmp_path,
        FakeVerificationRepository(),
        trade_date,
    )

    assert verification.passed is False
    failure = _failure(verification, "report_mode_invalid")
    assert "preview" in failure.message
    assert failure.fix_suggestion


def test_verify_strategy_v2_score_scan_runs_when_report_mode_is_missing(
    tmp_path,
):
    trade_date = date(2026, 7, 10)
    _write_production_report(
        tmp_path,
        trade_date,
        index_html="<html><body>评分 83.2</body></html>",
        report_json_payload={
            "trade_date": trade_date.isoformat(),
            "is_fixture": False,
            "recommendation_cards": [{"ts_code": "600000.SH"}],
            "strategy_snapshots": [{"internal_score": 83.2}],
        },
    )

    verification = _verify(
        tmp_path,
        FakeVerificationRepository(),
        trade_date,
    )

    assert verification.passed is False
    assert _failure(verification, "report_mode_invalid").fix_suggestion
    assert _failure(verification, "visible_total_score").fix_suggestion


def test_verify_rejects_production_report_without_generated_operational_status(
    tmp_path,
):
    trade_date = date(2026, 7, 10)
    _write_production_report(
        tmp_path,
        trade_date,
        report_json_payload={
            "trade_date": trade_date.isoformat(),
            "report_mode": "production",
            "is_fixture": False,
            "recommendations": [],
        },
    )

    verification = _verify(
        tmp_path,
        FakeVerificationRepository(),
        trade_date,
    )

    assert verification.passed is False
    assert _failure(verification, "trading_day_output_state_invalid").fix_suggestion


def test_verify_rejects_production_report_with_incomplete_operational_status(
    tmp_path,
):
    trade_date = date(2026, 7, 10)
    _write_production_report(
        tmp_path,
        trade_date,
        report_json_payload={
            "trade_date": trade_date.isoformat(),
            "report_mode": "production",
            "is_fixture": False,
            "recommendations": [],
            "operational_status": {
                "is_trading_day": True,
                "recommendation_state": "generated",
            },
        },
    )

    verification = _verify(
        tmp_path,
        FakeVerificationRepository(),
        trade_date,
    )

    assert verification.passed is False
    assert _failure(verification, "trading_day_output_state_invalid").fix_suggestion


def test_verify_rejects_data_insufficient_as_formal_report_mode(tmp_path):
    trade_date = date(2026, 7, 10)
    _write_production_report(
        tmp_path,
        trade_date,
        report_json_payload={
            "trade_date": trade_date.isoformat(),
            "report_mode": "data_insufficient",
            "is_fixture": False,
            "recommendations": [],
            "operational_status": {
                "trade_date": trade_date.isoformat(),
                "is_trading_day": True,
                "recommendation_state": "data_insufficient",
                "focus_state": "data_insufficient",
                "recommendation_count": 0,
                "focus_count": 0,
                "data_recovery_attempts": [
                    {
                        "family": "daily_ohlcv",
                        "source_name": "tushare.daily",
                        "status": "failed",
                    }
                ],
                "blocking_missing_fields": ["daily_ohlcv.close"],
                "message": "核心行情缺失。",
            },
        },
    )

    verification = _verify(
        tmp_path,
        FakeVerificationRepository(),
        trade_date,
    )

    assert verification.passed is False
    assert _failure(verification, "report_mode_invalid").fix_suggestion


def test_verify_rejects_data_insufficient_report_without_recovery_evidence(tmp_path):
    trade_date = date(2026, 7, 10)
    _write_production_report(
        tmp_path,
        trade_date,
        report_json_payload={
            "trade_date": trade_date.isoformat(),
            "report_mode": "data_insufficient",
            "is_fixture": False,
            "recommendations": [],
            "operational_status": {
                "trade_date": trade_date.isoformat(),
                "is_trading_day": True,
                "recommendation_state": "data_insufficient",
                "focus_state": "data_insufficient",
                "recommendation_count": 0,
                "focus_count": 0,
                "data_recovery_attempts": [],
                "blocking_missing_fields": [],
                "message": "核心行情缺失。",
            },
        },
    )

    verification = _verify(
        tmp_path,
        FakeVerificationRepository(),
        trade_date,
    )

    assert verification.passed is False
    assert _failure(verification, "report_mode_invalid").fix_suggestion


def test_verify_rejects_data_insufficient_report_with_malformed_recovery_attempt(
    tmp_path,
):
    trade_date = date(2026, 7, 10)
    _write_production_report(
        tmp_path,
        trade_date,
        report_json_payload={
            "trade_date": trade_date.isoformat(),
            "report_mode": "data_insufficient",
            "is_fixture": False,
            "recommendations": [],
            "operational_status": {
                "trade_date": trade_date.isoformat(),
                "is_trading_day": True,
                "recommendation_state": "data_insufficient",
                "focus_state": "data_insufficient",
                "recommendation_count": 0,
                "focus_count": 0,
                "data_recovery_attempts": [{"foo": "bar"}],
                "blocking_missing_fields": ["daily_ohlcv.close"],
                "message": "核心行情缺失。",
            },
        },
    )

    verification = _verify(
        tmp_path,
        FakeVerificationRepository(),
        trade_date,
    )

    assert verification.passed is False
    assert _failure(verification, "report_mode_invalid").fix_suggestion


def test_verify_fails_when_report_index_is_missing(tmp_path):
    trade_date = date(2026, 7, 9)
    _write_production_report(tmp_path, trade_date, include_root_index=False)

    verification = _verify(
        tmp_path,
        FakeVerificationRepository(),
        trade_date,
    )

    assert verification.passed is False
    assert _failure(verification, "report_index_missing").fix_suggestion


def test_run_daily_job_skips_non_trading_day_without_production_run(tmp_path):
    trade_date = date(2026, 7, 11)
    events: list[str] = []

    status = run_daily_job(
        tmp_path,
        trade_date,
        "18:30",
        1,
        prepare_deploy=True,
        repository=FakeJobRepository(),
        calendar_decider=_calendar_decider(
            TradingDayDecision(
                status="non_trading_day",
                source="supabase",
                message="market closed",
            ),
            events,
        ),
        health_check=_recording_call(events, "health_check"),
        run_daily=_recording_call(events, "run_daily"),
        verifier=lambda *_args: _successful_verification(trade_date),
        cleanup=_recording_call(events, "cleanup"),
        prepare_deploy_func=_recording_call(events, "prepare_deploy"),
    )

    assert status.status == RunStatus.SKIPPED_NON_TRADING_DAY
    assert status.publish_skipped_reason == "non_trading_day"
    assert status.deploy_artifact_prepared is False
    assert events == ["calendar"]


def test_default_run_daily_uses_formal_strategy_v2_entry(
    monkeypatch,
    tmp_path,
):
    captured = []
    dependencies = object()
    result = SimpleNamespace(receipt=SimpleNamespace(state=FormalRunState.REPORT_GENERATED))
    monkeypatch.setattr(
        "stock_analyzer.ops.job.build_production_formal_dependencies",
        lambda project_root, repository, trade_date: dependencies,
    )
    monkeypatch.setattr(
        "stock_analyzer.ops.job.run_formal_strategy_v2",
        lambda trade_date, report_cutoff, dependencies_arg, run_id=None: captured.append(
            (trade_date, report_cutoff, dependencies_arg, run_id)
        ) or result,
    )

    returned = _default_run_daily(
        tmp_path,
        FakeJobRepository(),
        date(2026, 7, 10),
    )

    assert returned is result
    assert captured[0][0] == date(2026, 7, 10)
    assert captured[0][1].tzinfo is not None
    assert captured[0][2] is dependencies
    assert captured[0][3] == "formal-2026-07-10"


def test_blocked_job_skips_verify_prepare_deploy_and_publish(tmp_path):
    trade_date = date(2026, 7, 10)
    events: list[str] = []
    blocked_result = SimpleNamespace(
        receipt=SimpleNamespace(
            state=FormalRunState.BLOCKED_NEEDS_HUMAN,
            run_id="blocked-formal-run",
            blocked_reasons=("missing_field:value",),
        )
    )

    status = run_daily_job(
        tmp_path,
        trade_date,
        "18:30",
        1,
        prepare_deploy=True,
        repository=FakeJobRepository(),
        calendar_decider=lambda *_args, **_kwargs: TradingDayDecision(
            status="trading_day",
            source="supabase",
            message="market open",
        ),
        health_check=lambda *_args: events.append("health"),
        run_daily=lambda *_args: events.append("run") or blocked_result,
        verifier=lambda *_args: events.append("verify"),
        prepare_deploy_func=lambda *_args: events.append("prepare"),
        auto_publish=True,
        publish_func=lambda *_args: events.append("publish"),
    )

    assert status.status == RunStatus.BLOCKED_NEEDS_HUMAN
    assert status.run_id == "blocked-formal-run"
    assert status.stage == "run_daily"
    assert status.deploy_artifact_prepared is False
    assert status.publish_skipped_reason == "data_readiness_blocked"
    assert events == ["health", "run"]


def test_run_daily_job_calendar_unknown_requires_human_intervention(tmp_path):
    trade_date = date(2026, 7, 9)

    status = run_daily_job(
        tmp_path,
        trade_date,
        "18:30",
        1,
        prepare_deploy=False,
        repository=FakeJobRepository(),
        calendar_decider=lambda *_args, **_kwargs: TradingDayDecision(
            status="calendar_unknown",
            source="unknown",
            message="calendar lookup failed",
        ),
    )

    assert status.status == RunStatus.CALENDAR_UNKNOWN
    assert status.failure_class == FailureClass.CALENDAR_UNKNOWN
    assert status.retryable is False
    assert status.fix_suggestion


def test_run_daily_job_default_calendar_loader_failure_writes_redacted_status(
    monkeypatch,
    tmp_path,
):
    trade_date = date(2026, 7, 9)
    status_path = tmp_path / "logs" / "run-daily" / "latest-status.json"

    def fail_loader():
        raise RuntimeError(
            "Tushare token failed CREDENTIAL_KEY=loader-redaction-sentinel"
        )

    monkeypatch.setattr(
        "stock_analyzer.ops.job._default_tushare_calendar_loader",
        fail_loader,
    )

    status = run_daily_job(
        tmp_path,
        trade_date,
        "18:30",
        1,
        prepare_deploy=False,
        repository=FakeJobRepository(),
        status_path=status_path,
    )

    status_text = status_path.read_text(encoding="utf-8")
    assert status.status == RunStatus.CALENDAR_UNKNOWN
    assert status.failure_class == FailureClass.CALENDAR_UNKNOWN
    assert status.stage == "calendar"
    assert "loader-redaction-sentinel" not in status_text
    assert "[REDACTED]" in status_text


def test_run_daily_job_attempt_two_cleans_before_rerun(tmp_path):
    trade_date = date(2026, 7, 9)
    events: list[str] = []
    status_path = tmp_path / "logs" / "run-daily" / "latest-status.json"
    _write_previous_status(
        status_path,
        trade_date=trade_date,
        attempt=1,
        run_status=RunStatus.FAILED_RETRYABLE,
    )

    status = run_daily_job(
        tmp_path,
        trade_date,
        "19:00",
        2,
        prepare_deploy=False,
        repository=FakeJobRepository(),
        calendar_decider=_calendar_decider(
            TradingDayDecision(
                status="trading_day",
                source="supabase",
                message="market open",
            ),
            events,
        ),
        cleanup=lambda *_args: _cleanup_summary(trade_date, events),
        health_check=_recording_call(events, "health_check"),
        run_daily=_recording_call(events, "run_daily"),
        verifier=lambda *_args: _successful_verification(trade_date),
        status_path=status_path,
    )

    assert status.status == RunStatus.SUCCESS_NO_RECOMMENDATIONS
    assert status.cleanup_performed is True
    assert status.cleanup_summary["repository_deleted_counts"] == {
        "recommendation_daily": 1,
    }
    assert events == ["calendar", "cleanup", "health_check", "run_daily"]


def test_run_daily_job_attempt_two_after_success_does_not_cleanup_or_run(tmp_path):
    trade_date = date(2026, 7, 9)
    events: list[str] = []
    status_path = tmp_path / "logs" / "run-daily" / "latest-status.json"
    _write_previous_status(
        status_path,
        trade_date=trade_date,
        attempt=1,
        run_status=RunStatus.SUCCESS_NO_RECOMMENDATIONS,
    )

    status = run_daily_job(
        tmp_path,
        trade_date,
        "19:00",
        2,
        prepare_deploy=False,
        repository=FakeJobRepository(),
        calendar_decider=_calendar_decider(
            TradingDayDecision(
                status="trading_day",
                source="supabase",
                message="market open",
            ),
            events,
        ),
        cleanup=lambda *_args: _cleanup_summary(trade_date, events),
        health_check=_recording_call(events, "health_check"),
        run_daily=_recording_call(events, "run_daily"),
        verifier=lambda *_args: _successful_verification(trade_date),
        status_path=status_path,
    )

    assert status.status == RunStatus.SUCCESS_NO_RECOMMENDATIONS
    assert status.attempt == 1
    assert status.cleanup_performed is False
    assert events == []


def test_run_daily_job_attempt_three_after_attempt_one_success_is_noop(tmp_path):
    trade_date = date(2026, 7, 9)
    events: list[str] = []
    status_path = tmp_path / "logs" / "run-daily" / "latest-status.json"
    _write_previous_status(
        status_path,
        trade_date=trade_date,
        attempt=1,
        run_status=RunStatus.SUCCESS_WITH_RECOMMENDATIONS,
    )

    status = run_daily_job(
        tmp_path,
        trade_date,
        "19:30",
        3,
        prepare_deploy=True,
        repository=FakeJobRepository(),
        calendar_decider=_calendar_decider(
            TradingDayDecision(
                status="trading_day",
                source="supabase",
                message="market open",
            ),
            events,
        ),
        cleanup=lambda *_args: _cleanup_summary(trade_date, events),
        health_check=_recording_call(events, "health_check"),
        run_daily=_recording_call(events, "run_daily"),
        verifier=lambda *_args: _successful_verification(trade_date),
        prepare_deploy_func=_recording_call(events, "prepare_deploy"),
        status_path=status_path,
    )

    assert status.status is RunStatus.SUCCESS_WITH_RECOMMENDATIONS
    assert status.attempt == 1
    assert events == []


def test_run_daily_job_attempt_two_after_human_failure_does_not_cleanup_or_run(
    tmp_path,
):
    trade_date = date(2026, 7, 9)
    events: list[str] = []
    status_path = tmp_path / "logs" / "run-daily" / "latest-status.json"
    _write_previous_status(
        status_path,
        trade_date=trade_date,
        attempt=1,
        run_status=RunStatus.FAILED_NEEDS_HUMAN,
    )

    status = run_daily_job(
        tmp_path,
        trade_date,
        "19:00",
        2,
        prepare_deploy=False,
        repository=FakeJobRepository(),
        calendar_decider=_calendar_decider(
            TradingDayDecision(
                status="trading_day",
                source="supabase",
                message="market open",
            ),
            events,
        ),
        cleanup=lambda *_args: _cleanup_summary(trade_date, events),
        health_check=_recording_call(events, "health_check"),
        run_daily=_recording_call(events, "run_daily"),
        verifier=lambda *_args: _successful_verification(trade_date),
        status_path=status_path,
    )

    assert status.status == RunStatus.FAILED_NEEDS_HUMAN
    assert status.stage == "retry_preflight"
    assert status.cleanup_performed is False
    assert events == []


def test_run_daily_job_cleanup_failure_returns_failed_needs_human(tmp_path):
    trade_date = date(2026, 7, 9)
    events: list[str] = []
    status_path = tmp_path / "logs" / "run-daily" / "latest-status.json"
    _write_previous_status(
        status_path,
        trade_date=trade_date,
        attempt=1,
        run_status=RunStatus.FAILED_RETRYABLE,
    )

    def fail_cleanup(*_args):
        events.append("cleanup")
        raise RuntimeError("cleanup failed")

    status = run_daily_job(
        tmp_path,
        trade_date,
        "19:00",
        2,
        prepare_deploy=False,
        repository=FakeJobRepository(),
        calendar_decider=_calendar_decider(
            TradingDayDecision(
                status="trading_day",
                source="supabase",
                message="market open",
            ),
            events,
        ),
        cleanup=fail_cleanup,
        health_check=_recording_call(events, "health_check"),
        run_daily=_recording_call(events, "run_daily"),
        status_path=status_path,
    )

    assert status.status == RunStatus.FAILED_NEEDS_HUMAN
    assert status.failure_class == FailureClass.CLEANUP_FAILED
    assert status.cleanup_performed is False
    assert events == ["calendar", "cleanup"]


def test_run_daily_job_third_failed_attempt_needs_human(tmp_path):
    trade_date = date(2026, 7, 9)
    events: list[str] = []
    status_path = tmp_path / "logs" / "run-daily" / "latest-status.json"
    _write_previous_status(
        status_path,
        trade_date=trade_date,
        attempt=2,
        run_status=RunStatus.FAILED_RETRYABLE,
    )

    def fail_retryable(*_args):
        events.append("run_daily")
        raise RetryableJobError(
            "temporary network timeout",
            failure_class=FailureClass.NETWORK_TIMEOUT,
        )

    status = run_daily_job(
        tmp_path,
        trade_date,
        "19:30",
        3,
        prepare_deploy=False,
        repository=FakeJobRepository(),
        calendar_decider=_calendar_decider(
            TradingDayDecision(
                status="trading_day",
                source="supabase",
                message="market open",
            ),
            events,
        ),
        cleanup=lambda *_args: _cleanup_summary(trade_date, events),
        health_check=_recording_call(events, "health_check"),
        run_daily=fail_retryable,
        status_path=status_path,
    )

    assert status.status == RunStatus.FAILED_NEEDS_HUMAN
    assert status.failure_class == FailureClass.MAX_ATTEMPTS_EXCEEDED
    assert status.retryable is False
    assert events == ["calendar", "cleanup", "health_check", "run_daily"]


def test_run_daily_job_attempt_above_max_is_rejected_before_calendar_or_cleanup(
    tmp_path,
):
    trade_date = date(2026, 7, 9)
    events: list[str] = []

    status = run_daily_job(
        tmp_path,
        trade_date,
        "20:00",
        4,
        prepare_deploy=True,
        repository=FakeJobRepository(),
        calendar_decider=_calendar_decider(
            TradingDayDecision(
                status="trading_day",
                source="supabase",
                message="market open",
            ),
            events,
        ),
        cleanup=lambda *_args: _cleanup_summary(trade_date, events),
        health_check=_recording_call(events, "health_check"),
        run_daily=_recording_call(events, "run_daily"),
        verifier=lambda *_args: _successful_verification(trade_date),
        prepare_deploy_func=_recording_call(events, "prepare_deploy"),
    )

    assert status.status == RunStatus.FAILED_NEEDS_HUMAN
    assert status.failure_class == FailureClass.MAX_ATTEMPTS_EXCEEDED
    assert status.stage == "retry_preflight"
    assert status.cleanup_performed is False
    assert events == []


def test_run_daily_job_success_with_zero_recommendations_writes_status(tmp_path):
    trade_date = date(2026, 7, 9)
    status_path = tmp_path / "logs" / "run-daily" / "latest-status.json"
    prepared_paths: list[str] = []

    status = run_daily_job(
        tmp_path,
        trade_date,
        "18:30",
        1,
        prepare_deploy=True,
        repository=FakeJobRepository(),
        calendar_decider=lambda *_args, **_kwargs: TradingDayDecision(
            status="trading_day",
            source="supabase",
            message="market open",
        ),
        run_daily=lambda *_args: None,
        verifier=lambda *_args: _successful_verification(trade_date),
        prepare_deploy_func=lambda project_root: prepared_paths.append(
            str(project_root / "dist" / "pages")
        )
        or (project_root / "dist" / "pages"),
        status_path=status_path,
    )

    payload = json.loads(status_path.read_text(encoding="utf-8"))
    assert status.status == RunStatus.SUCCESS_NO_RECOMMENDATIONS
    assert status.recommendations == 0
    assert status.deploy_artifact_prepared is True
    assert prepared_paths == [str(tmp_path / "dist" / "pages")]
    assert payload["status"] == "success_no_recommendations"
    assert payload["recommendations"] == 0
    assert payload["deploy_artifact_prepared"] is True


def test_run_daily_job_writes_operational_states_from_successful_verification(
    tmp_path,
):
    trade_date = date(2026, 7, 9)
    status_path = tmp_path / "logs" / "run-daily" / "latest-status.json"

    status = run_daily_job(
        tmp_path,
        trade_date,
        "18:30",
        1,
        prepare_deploy=False,
        repository=FakeJobRepository(),
        calendar_decider=lambda *_args, **_kwargs: TradingDayDecision(
            status="trading_day",
            source="supabase",
            message="market open",
        ),
        health_check=lambda *_args: None,
        run_daily=lambda *_args: None,
        verifier=lambda *_args: _successful_verification(
            trade_date,
            recommendation_state="data_insufficient",
            focus_state="data_insufficient",
            blocking_missing_fields=("daily_ohlcv.close",),
        ),
        status_path=status_path,
    )

    payload = json.loads(status_path.read_text(encoding="utf-8"))
    assert status.recommendation_state == "data_insufficient"
    assert status.focus_state == "data_insufficient"
    assert status.blocking_missing_fields == ["daily_ohlcv.close"]
    assert payload["recommendation_state"] == "data_insufficient"
    assert payload["focus_state"] == "data_insufficient"
    assert payload["blocking_missing_fields"] == ["daily_ohlcv.close"]


def test_run_daily_job_writes_operational_states_from_failed_verification(
    tmp_path,
):
    trade_date = date(2026, 7, 9)
    status_path = tmp_path / "logs" / "run-daily" / "latest-status.json"

    status = run_daily_job(
        tmp_path,
        trade_date,
        "18:30",
        1,
        prepare_deploy=False,
        repository=FakeJobRepository(),
        calendar_decider=lambda *_args, **_kwargs: TradingDayDecision(
            status="trading_day",
            source="supabase",
            message="market open",
        ),
        health_check=lambda *_args: None,
        run_daily=lambda *_args: None,
        verifier=lambda *_args: ProductionVerification(
            trade_date=trade_date,
            status=RunStatus.FAILED_NEEDS_HUMAN,
            passed=False,
            recommendations=0,
            evidence_packages=0,
            evaluation_tasks=0,
            market_price_daily_current_day_rows=0,
            daily_basic_indicator_current_day_rows=0,
            report_index_exists=True,
            daily_report_index_exists=True,
            report_json_exists=True,
            failures=(
                _production_failure(
                    "data_insufficient_recovery_missing",
                    "Add recovery evidence.",
                ),
            ),
            recommendation_state="data_insufficient",
            focus_state="data_insufficient",
            blocking_missing_fields=("daily_ohlcv.close",),
        ),
        status_path=status_path,
    )

    payload = json.loads(status_path.read_text(encoding="utf-8"))
    assert status.status == RunStatus.FAILED_NEEDS_HUMAN
    assert status.recommendation_state == "data_insufficient"
    assert status.focus_state == "data_insufficient"
    assert status.blocking_missing_fields == ["daily_ohlcv.close"]
    assert payload["recommendation_state"] == "data_insufficient"
    assert payload["focus_state"] == "data_insufficient"
    assert payload["blocking_missing_fields"] == ["daily_ohlcv.close"]


def test_run_daily_job_triggers_auto_publish_after_success(tmp_path):
    trade_date = date(2026, 7, 9)
    publish_calls = []

    def fake_publish(project_root, trade_date_arg):
        publish_calls.append((project_root, trade_date_arg))

    status = run_daily_job(
        tmp_path,
        trade_date,
        "18:30",
        1,
        prepare_deploy=False,
        repository=FakeJobRepository(),
        calendar_decider=lambda *_args, **_kwargs: TradingDayDecision(
            status="trading_day",
            source="supabase",
            message="market open",
        ),
        health_check=lambda *_args: None,
        run_daily=lambda *_args: None,
        verifier=lambda *_args: _successful_verification_with_recommendations(
            trade_date
        ),
        auto_publish=True,
        publish_func=fake_publish,
    )

    assert status.status == RunStatus.SUCCESS_WITH_RECOMMENDATIONS
    assert publish_calls == [(tmp_path, trade_date)]


def test_run_daily_job_writes_current_success_status_before_auto_publish(tmp_path):
    current_trade_date = date(2026, 7, 9)
    stale_trade_date = date(2026, 7, 8)
    status_path = tmp_path / "logs" / "run-daily" / "latest-status.json"
    _write_previous_status(
        status_path,
        trade_date=stale_trade_date,
        attempt=1,
        run_status=RunStatus.SUCCESS_NO_RECOMMENDATIONS,
    )
    publish_seen_payloads = []

    def fake_publish(project_root, trade_date_arg):
        publish_seen_payloads.append(
            json.loads(
                (project_root / "logs" / "run-daily" / "latest-status.json").read_text(
                    encoding="utf-8"
                )
            )
        )

    status = run_daily_job(
        tmp_path,
        current_trade_date,
        "18:30",
        1,
        prepare_deploy=False,
        repository=FakeJobRepository(),
        calendar_decider=lambda *_args, **_kwargs: TradingDayDecision(
            status="trading_day",
            source="supabase",
            message="market open",
        ),
        health_check=lambda *_args: None,
        run_daily=lambda *_args: None,
        verifier=lambda *_args: _successful_verification_with_recommendations(
            current_trade_date
        ),
        auto_publish=True,
        publish_func=fake_publish,
    )

    assert status.status == RunStatus.SUCCESS_WITH_RECOMMENDATIONS
    assert publish_seen_payloads == [
        {
            **publish_seen_payloads[0],
            "trade_date": current_trade_date.isoformat(),
            "status": "success_with_recommendations",
            "recommendations": 1,
        }
    ]


def test_default_auto_publish_passes_capacity_checker(monkeypatch, tmp_path):
    trade_date = date(2026, 7, 9)
    flag_path = tmp_path / "logs" / "publish" / "auto-publish-enabled.json"
    flag_path.parent.mkdir(parents=True)
    flag_path.write_text(json.dumps({"enabled": True}), encoding="utf-8")
    sentinel_capacity_checker = object()
    captured_kwargs = []

    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv(
        "REPORT_SITE_URL",
        "https://stock-analysis-assistant-v3.pages.dev",
    )
    monkeypatch.setenv(
        "CLOUDFLARE_PAGES_PROJECT_NAME",
        "stock-analysis-assistant-v3",
    )
    monkeypatch.setattr(
        "stock_analyzer.ops.publish.build_publish_capacity_checker",
        lambda config: sentinel_capacity_checker,
        raising=False,
    )

    def fake_publish(config, *, mode, trade_date=None, notify_enabled=False, **kwargs):
        captured_kwargs.append(kwargs)
        return "published"

    monkeypatch.setattr("stock_analyzer.ops.publish.publish_report_site", fake_publish)

    result = _default_publish(tmp_path, trade_date)

    assert result == "published"
    assert captured_kwargs[0]["capacity_checker"] is sentinel_capacity_checker


def test_run_daily_job_does_not_auto_publish_zero_recommendations(tmp_path):
    trade_date = date(2026, 7, 9)
    publish_calls = []

    status = run_daily_job(
        tmp_path,
        trade_date,
        "18:30",
        1,
        prepare_deploy=False,
        repository=FakeJobRepository(),
        calendar_decider=lambda *_args, **_kwargs: TradingDayDecision(
            status="trading_day",
            source="supabase",
            message="market open",
        ),
        health_check=lambda *_args: None,
        run_daily=lambda *_args: None,
        verifier=lambda *_args: _successful_verification(trade_date),
        auto_publish=True,
        publish_func=lambda project_root, trade_date_arg: publish_calls.append(
            (project_root, trade_date_arg)
        ),
    )

    assert status.status == RunStatus.SUCCESS_NO_RECOMMENDATIONS
    assert publish_calls == []


def test_run_daily_job_redacts_status_json_error_messages(tmp_path):
    trade_date = date(2026, 7, 9)
    status_path = tmp_path / "logs" / "run-daily" / "latest-status.json"

    def fail_with_secret(*_args):
        raise RetryableJobError(
            "Authorization: Bearer opaque-token CREDENTIAL_KEY=opaque-value",
            failure_class=FailureClass.NETWORK_TIMEOUT,
        )

    run_daily_job(
        tmp_path,
        trade_date,
        "18:30",
        1,
        prepare_deploy=False,
        repository=FakeJobRepository(),
        calendar_decider=lambda *_args, **_kwargs: TradingDayDecision(
            status="trading_day",
            source="supabase",
            message="market open",
        ),
        run_daily=fail_with_secret,
        status_path=status_path,
    )

    status_text = status_path.read_text(encoding="utf-8")
    assert "opaque-token" not in status_text
    assert "opaque-value" not in status_text
    assert "[REDACTED]" in status_text


def test_run_daily_job_redacts_known_env_secret_value_without_secret_syntax(
    monkeypatch,
    tmp_path,
):
    trade_date = date(2026, 7, 9)
    status_path = tmp_path / "logs" / "run-daily" / "latest-status.json"
    raw_secret = "-".join(("raw", "session", "secret", "without", "syntax"))
    monkeypatch.setenv("REPORT_SESSION_SECRET", raw_secret)

    def fail_with_raw_secret(*_args):
        raise RetryableJobError(
            f"upstream response included {raw_secret}",
            failure_class=FailureClass.NETWORK_TIMEOUT,
        )

    run_daily_job(
        tmp_path,
        trade_date,
        "18:30",
        1,
        prepare_deploy=False,
        repository=FakeJobRepository(),
        calendar_decider=lambda *_args, **_kwargs: TradingDayDecision(
            status="trading_day",
            source="supabase",
            message="market open",
        ),
        run_daily=fail_with_raw_secret,
        status_path=status_path,
    )

    status_text = status_path.read_text(encoding="utf-8")
    assert raw_secret not in status_text
    assert "[REDACTED]" in status_text


def test_run_daily_job_notifies_human_failure_only_when_enabled(tmp_path):
    trade_date = date(2026, 7, 9)
    notifications: list[tuple[str, str, bool]] = []

    def fail_needs_human(*_args):
        raise HumanInterventionJobError(
            "schema mismatch requires intervention",
            failure_class=FailureClass.SCHEMA_MISMATCH,
        )

    status = run_daily_job(
        tmp_path,
        trade_date,
        "18:30",
        1,
        prepare_deploy=False,
        repository=FakeJobRepository(),
        calendar_decider=lambda *_args, **_kwargs: TradingDayDecision(
            status="trading_day",
            source="supabase",
            message="market open",
        ),
        run_daily=fail_needs_human,
        notify_func=lambda title, message, enabled=False: notifications.append(
            (title, message, enabled)
        ),
    )

    assert status.status == RunStatus.FAILED_NEEDS_HUMAN
    assert notifications == []

    status = run_daily_job(
        tmp_path,
        trade_date,
        "18:30",
        1,
        prepare_deploy=False,
        repository=FakeJobRepository(),
        calendar_decider=lambda *_args, **_kwargs: TradingDayDecision(
            status="trading_day",
            source="supabase",
            message="market open",
        ),
        run_daily=fail_needs_human,
        notify_enabled=True,
        notify_func=lambda title, message, enabled=False: notifications.append(
            (title, message, enabled)
        ),
    )

    assert status.status == RunStatus.FAILED_NEEDS_HUMAN
    assert len(notifications) == 1
    assert notifications[0][2] is True


def test_run_daily_job_does_not_notify_retryable_failure_even_when_enabled(tmp_path):
    trade_date = date(2026, 7, 9)
    notifications: list[tuple[str, str, bool]] = []

    def fail_retryable(*_args):
        raise RetryableJobError(
            "temporary network timeout",
            failure_class=FailureClass.NETWORK_TIMEOUT,
        )

    status = run_daily_job(
        tmp_path,
        trade_date,
        "18:30",
        1,
        prepare_deploy=False,
        repository=FakeJobRepository(),
        calendar_decider=lambda *_args, **_kwargs: TradingDayDecision(
            status="trading_day",
            source="supabase",
            message="market open",
        ),
        run_daily=fail_retryable,
        notify_enabled=True,
        notify_func=lambda title, message, enabled=False: notifications.append(
            (title, message, enabled)
        ),
    )

    assert status.status == RunStatus.FAILED_RETRYABLE
    assert notifications == []


@pytest.mark.parametrize(
    "run_status",
    [
        RunStatus.FAILED_NEEDS_HUMAN,
        RunStatus.FAILED_RETRYABLE,
        RunStatus.CALENDAR_UNKNOWN,
    ],
)
def test_ops_run_daily_job_cli_exits_nonzero_for_action_required_status(
    monkeypatch,
    tmp_path,
    run_status,
):
    def fake_run_daily_job(**kwargs):
        return JobStatus(
            trade_date=kwargs["trade_date"],
            attempt=kwargs["attempt"],
            scheduled_slot=kwargs["scheduled_slot"],
            status=run_status,
            stage="run_daily",
        )

    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr("stock_analyzer.cli.run_daily_job", fake_run_daily_job)

    result = CliRunner().invoke(
        app,
        [
            "ops",
            "run-daily-job",
            "--trade-date",
            "2026-07-09",
            "--scheduled-slot",
            "18:30",
            "--attempt",
            "1",
        ],
    )

    assert result.exit_code != 0
    assert run_status.value in result.output


def test_ops_run_daily_job_cli_enables_notification_from_option(monkeypatch, tmp_path):
    captured_notify_enabled: list[bool] = []

    def fake_run_daily_job(**kwargs):
        captured_notify_enabled.append(kwargs["notify_enabled"])
        return JobStatus(
            trade_date=kwargs["trade_date"],
            attempt=kwargs["attempt"],
            scheduled_slot=kwargs["scheduled_slot"],
            status=RunStatus.SUCCESS_NO_RECOMMENDATIONS,
            stage="complete",
        )

    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.delenv("STOCK_ANALYZER_NOTIFY_MAC", raising=False)
    monkeypatch.setattr("stock_analyzer.cli.run_daily_job", fake_run_daily_job)

    result = CliRunner().invoke(
        app,
        [
            "ops",
            "run-daily-job",
            "--trade-date",
            "2026-07-09",
            "--scheduled-slot",
            "18:30",
            "--attempt",
            "1",
            "--notify-mac",
        ],
    )

    assert result.exit_code == 0
    assert captured_notify_enabled == [True]


def test_ops_run_daily_job_cli_enables_notification_from_env(monkeypatch, tmp_path):
    captured_notify_enabled: list[bool] = []

    def fake_run_daily_job(**kwargs):
        captured_notify_enabled.append(kwargs["notify_enabled"])
        return JobStatus(
            trade_date=kwargs["trade_date"],
            attempt=kwargs["attempt"],
            scheduled_slot=kwargs["scheduled_slot"],
            status=RunStatus.SUCCESS_NO_RECOMMENDATIONS,
            stage="complete",
        )

    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("STOCK_ANALYZER_NOTIFY_MAC", "1")
    monkeypatch.setattr("stock_analyzer.cli.run_daily_job", fake_run_daily_job)

    result = CliRunner().invoke(
        app,
        [
            "ops",
            "run-daily-job",
            "--trade-date",
            "2026-07-09",
            "--scheduled-slot",
            "18:30",
            "--attempt",
            "1",
        ],
    )

    assert result.exit_code == 0
    assert captured_notify_enabled == [True]


def test_ops_verify_production_cli_exits_zero_when_verification_passes(
    monkeypatch,
    tmp_path,
):
    trade_date = date(2026, 7, 8)
    repository = FakeJobRepository()

    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr(
        "stock_analyzer.cli._analysis_repository",
        lambda *_args, **_kwargs: repository,
    )
    monkeypatch.setattr(
        "stock_analyzer.cli.verify_production_result",
        lambda project_root, repo, parsed_trade_date, **_kwargs: ProductionVerification(
            trade_date=parsed_trade_date,
            status=RunStatus.SUCCESS_NO_RECOMMENDATIONS,
            passed=True,
            recommendations=0,
            evidence_packages=0,
            evaluation_tasks=0,
            market_price_daily_current_day_rows=0,
            daily_basic_indicator_current_day_rows=0,
            report_index_exists=True,
            daily_report_index_exists=True,
            report_json_exists=True,
            failures=(),
        ),
    )

    result = CliRunner().invoke(
        app,
        ["ops", "verify-production", "--trade-date", trade_date.isoformat()],
    )

    assert result.exit_code == 0
    assert "success_no_recommendations" in result.output


def test_ops_verify_production_cli_exits_nonzero_when_verification_fails(
    monkeypatch,
    tmp_path,
):
    trade_date = date(2026, 7, 8)
    repository = FakeJobRepository()

    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr(
        "stock_analyzer.cli._analysis_repository",
        lambda *_args, **_kwargs: repository,
    )
    monkeypatch.setattr(
        "stock_analyzer.cli.verify_production_result",
        lambda project_root, repo, parsed_trade_date, **_kwargs: ProductionVerification(
            trade_date=parsed_trade_date,
            status=RunStatus.FAILED_NEEDS_HUMAN,
            passed=False,
            recommendations=0,
            evidence_packages=0,
            evaluation_tasks=0,
            market_price_daily_current_day_rows=0,
            daily_basic_indicator_current_day_rows=0,
            report_index_exists=False,
            daily_report_index_exists=False,
            report_json_exists=False,
            failures=(
                _production_failure(
                    "report_index_missing",
                    "Rerun report generation.",
                ),
            ),
        ),
    )

    result = CliRunner().invoke(
        app,
        ["ops", "verify-production", "--trade-date", trade_date.isoformat()],
    )

    assert result.exit_code != 0
    assert "report_index_missing" in result.output
    assert "Rerun report generation." in result.output


class FakeJobRepository:
    def load_market_calendar_day(self, trade_date):
        return True

    def save_market_calendar_day(self, trade_date, is_trading_day, market="CN_A"):
        return None


def _calendar_decider(decision: TradingDayDecision, events: list[str]):
    def decide(*_args, **_kwargs):
        events.append("calendar")
        return decision

    return decide


def _recording_call(events: list[str], name: str):
    def call(*_args, **_kwargs):
        events.append(name)
        return None

    return call


def _cleanup_summary(trade_date: date, events: list[str]) -> CleanupSummary:
    events.append("cleanup")
    return CleanupSummary(
        trade_date=trade_date,
        repository_deleted_counts={"recommendation_daily": 1},
        removed_paths=("reports/daily/2026-07-09",),
    )


def _write_previous_status(
    status_path,
    *,
    trade_date: date,
    attempt: int,
    run_status: RunStatus,
) -> None:
    JobStatus(
        trade_date=trade_date,
        attempt=attempt,
        scheduled_slot="18:30" if attempt == 1 else "19:00",
        status=run_status,
        stage="run_daily",
        failure_class=(
            FailureClass.NETWORK_TIMEOUT
            if run_status == RunStatus.FAILED_RETRYABLE
            else None
        ),
    ).write_json(status_path)


def _successful_verification(
    trade_date: date,
    *,
    recommendation_state: str | None = None,
    focus_state: str | None = None,
    blocking_missing_fields: tuple[str, ...] = (),
) -> ProductionVerification:
    return ProductionVerification(
        trade_date=trade_date,
        status=RunStatus.SUCCESS_NO_RECOMMENDATIONS,
        passed=True,
        recommendations=0,
        evidence_packages=0,
        evaluation_tasks=0,
        market_price_daily_current_day_rows=0,
        daily_basic_indicator_current_day_rows=0,
        report_index_exists=True,
        daily_report_index_exists=True,
        report_json_exists=True,
        failures=(),
        recommendation_state=recommendation_state,
        focus_state=focus_state,
        blocking_missing_fields=blocking_missing_fields,
    )


def _successful_verification_with_recommendations(
    trade_date: date,
) -> ProductionVerification:
    return ProductionVerification(
        trade_date=trade_date,
        status=RunStatus.SUCCESS_WITH_RECOMMENDATIONS,
        passed=True,
        recommendations=1,
        evidence_packages=1,
        evaluation_tasks=6,
        market_price_daily_current_day_rows=1,
        daily_basic_indicator_current_day_rows=1,
        report_index_exists=True,
        daily_report_index_exists=True,
        report_json_exists=True,
        failures=(),
    )


class FakeVerificationRepository:
    def __init__(
        self,
        recommendations=None,
        evidence_packages=None,
        evaluation_tasks=None,
        market_bars=None,
        daily_basic_indicators=None,
    ) -> None:
        self.recommendations = list(recommendations or [])
        self.evidence_packages = list(evidence_packages or [])
        self.evaluation_tasks = list(evaluation_tasks or [])
        self.market_bars = list(market_bars or [])
        self.daily_basic_indicators = list(daily_basic_indicators or [])

    def load_daily_recommendations(self, trade_date):
        return [item for item in self.recommendations if item.trade_date == trade_date]

    def load_evidence_packages(self, trade_date):
        return [item for item in self.evidence_packages if item.trade_date == trade_date]

    def load_evaluation_tasks(self, trade_date):
        return [item for item in self.evaluation_tasks if item.trade_date == trade_date]


class FakeSupabaseVerificationRepository:
    def __init__(self, client) -> None:
        self.client = client

    def load_daily_recommendations(self, trade_date):
        return []

    def load_evidence_packages(self, trade_date):
        return []

    def load_evaluation_tasks(self, trade_date):
        return []


class FakeVerificationSupabaseResult:
    def __init__(self, data) -> None:
        self.data = data
        self.count = len(data)


class FakeVerificationSupabaseTable:
    def __init__(self, name: str, client: "FakeVerificationSupabaseClient") -> None:
        self.name = name
        self.client = client
        self.filters = []

    def select(self, columns: str, **options):
        return self

    def eq(self, column: str, value):
        self.filters.append((column, value))
        return self

    def execute(self):
        rows = list(self.client.table_data.get(self.name, []))
        for column, value in self.filters:
            rows = [row for row in rows if row.get(column) == value]
        return FakeVerificationSupabaseResult(rows)


class FakeVerificationSupabaseClient:
    def __init__(self, table_data) -> None:
        self.table_data = table_data

    def table(self, name: str) -> FakeVerificationSupabaseTable:
        return FakeVerificationSupabaseTable(name, self)


def _write_production_report(
    project_root,
    trade_date: date,
    *,
    index_html: str | None = None,
    include_root_index: bool = True,
    report_json_payload=None,
) -> None:
    reports = project_root / "reports"
    daily = reports / "daily" / trade_date.isoformat()
    data = reports / "data"
    daily.mkdir(parents=True)
    data.mkdir(parents=True)

    if include_root_index:
        (reports / "index.html").write_text(
            index_html or f"<html>生产报告 {trade_date.isoformat()}</html>",
            encoding="utf-8",
        )
    (daily / "index.html").write_text(
        f"<html>生产日报 {trade_date.isoformat()}</html>",
        encoding="utf-8",
    )
    payload = report_json_payload or {
        "trade_date": trade_date.isoformat(),
        "report_mode": "production",
        "is_fixture": False,
        "recommendations": [],
        "operational_status": {
            "is_trading_day": True,
            "recommendation_state": "generated",
            "focus_state": "generated",
        },
    }
    (data / "latest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _recommendation(trade_date: date, ts_code: str) -> Recommendation:
    return Recommendation(
        trade_date=trade_date,
        ts_code=ts_code,
        name="浦发银行",
        action=ActionLabel.ENTER_OBSERVATION,
        score=80,
        reasons=["趋势改善"],
        risks=["需要确认"],
        evidence_id=f"{trade_date.isoformat()}-{ts_code}",
    )


def _evidence_package(trade_date: date, ts_code: str) -> EvidencePackage:
    return EvidencePackage(
        evidence_id=f"{trade_date.isoformat()}-{ts_code}",
        trade_date=trade_date,
        ts_code=ts_code,
        thesis="观察",
        support=["趋势改善"],
        counter_evidence=["需要确认"],
        matched_rules=[],
        confidence_level="medium",
        expected_confirmation_path=["趋势延续"],
        invalidation_conditions=["趋势失效"],
        source_versions={"recommendation": f"{trade_date.isoformat()}-{ts_code}"},
    )


def _evaluation_tasks(recommendation: Recommendation) -> list[EvaluationTask]:
    return [
        EvaluationTask(
            trade_date=recommendation.trade_date,
            ts_code=recommendation.ts_code,
            evidence_id=recommendation.evidence_id or "",
            checkpoint_days=checkpoint_days,
            due_date=recommendation.trade_date + timedelta(days=checkpoint_days),
            evaluation_layer=layer,
        )
        for checkpoint_days, layer in [
            (5, "result"),
            (20, "result"),
            (40, "result"),
            (20, "method"),
            (40, "method"),
            (40, "knowledge"),
        ]
    ]


def _daily_bar(trade_date: date, ts_code: str) -> DailyBar:
    return DailyBar(
        trade_date=trade_date,
        ts_code=ts_code,
        close=10.0,
        source_name="tushare",
        source_grade=SourceGrade.PRIMARY,
    )


def _daily_basic(trade_date: date, ts_code: str) -> DailyBasicRow:
    return DailyBasicRow(
        trade_date=trade_date,
        ts_code=ts_code,
        turnover_rate=1.5,
        source_name="tushare",
        source_grade=SourceGrade.PRIMARY,
    )


def _failure(verification, code):
    return next(failure for failure in verification.failures if failure.code == code)


def _production_failure(
    code: str,
    fix_suggestion: str,
) -> ProductionVerificationFailure:
    return ProductionVerificationFailure(
        code=code,
        message=f"{code} occurred",
        fix_suggestion=fix_suggestion,
    )
