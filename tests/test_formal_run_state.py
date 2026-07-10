from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from stock_analyzer.data.acquisition import RouteAttempt
from stock_analyzer.data.readiness import (
    AcquisitionGroupId,
    FailureClassification,
    FormalRunState,
    RouteKind,
)
from stock_analyzer.ops.formal_run import (
    FormalRunController,
    InvalidRunTransition,
    write_blocked_status,
)
from stock_analyzer.storage.evidence_store import LocalEvidenceStore


SHANGHAI = ZoneInfo("Asia/Shanghai")
TARGET = date(2026, 7, 10)
CUTOFF = datetime(2026, 7, 10, 16, 0, tzinfo=SHANGHAI)


def _controller(tmp_path: Path) -> FormalRunController:
    return FormalRunController.start(
        LocalEvidenceStore(tmp_path / "evidence"),
        run_id="formal-20260710-001",
        target_date=TARGET,
        report_cutoff=CUTOFF,
        acquisition_contract_version="formal-v1",
        screening_version="strategy-v2-screen-v1",
    )


def _ready_to_screen(controller: FormalRunController) -> FormalRunController:
    controller.transition(FormalRunState.ACQUIRING_SCREENING_PRIMARY)
    controller.record_group(AcquisitionGroupId.CALENDAR_UNIVERSE, "calendar-v1")
    controller.record_group(AcquisitionGroupId.MARKET_DECISION, "market-v1")
    controller.record_group(AcquisitionGroupId.BOARD_INDUSTRY, "board-v1")
    controller.record_group(AcquisitionGroupId.OFFICIAL_EVENTS_RISK, "risk-v1")
    controller.transition(FormalRunState.VALIDATING_SCREENING)
    controller.enter_ready_to_screen()
    return controller


def test_only_ready_to_screen_can_freeze_candidates(tmp_path):
    controller = _controller(tmp_path)

    with pytest.raises(InvalidRunTransition, match="READY_TO_SCREEN"):
        controller.freeze_candidates(("600000.SH",), ())

    _ready_to_screen(controller)
    candidate_set = controller.freeze_candidates(
        ("600000.SH", "000001.SZ"),
        ("600519.SH",),
    )
    assert candidate_set.ordered_codes == ("600000.SH", "000001.SZ")
    assert controller.receipt.state == FormalRunState.TARGET_SET_FROZEN


def test_candidate_set_is_ordered_frozen_and_resume_uses_same_id(tmp_path):
    controller = _ready_to_screen(_controller(tmp_path))
    candidate_set = controller.freeze_candidates(
        ("600000.SH", "000001.SZ"),
        ("600519.SH",),
    )

    resumed = FormalRunController.resume(controller.store, controller.receipt.run_id)
    loaded = controller.store.candidate_set(candidate_set.candidate_set_id)

    assert loaded == candidate_set
    assert resumed.receipt.candidate_set_id == candidate_set.candidate_set_id
    assert loaded.ordered_codes == ("600000.SH", "000001.SZ")


def test_target_failure_does_not_replace_candidate_with_next_ranked_code(tmp_path):
    controller = _ready_to_screen(_controller(tmp_path))
    frozen = controller.freeze_candidates(("600000.SH", "000001.SZ"), ())
    controller.transition(FormalRunState.ACQUIRING_TARGET_PRIMARY)
    controller.block(
        AcquisitionGroupId.CANDIDATE_FUNDAMENTAL,
        reasons=("missing_code:000001.SZ",),
    )

    persisted = controller.store.candidate_set(frozen.candidate_set_id)
    assert persisted.ordered_codes == ("600000.SH", "000001.SZ")
    assert "600519.SH" not in persisted.ordered_codes


def test_only_ready_to_analyze_can_begin_analysis(tmp_path):
    controller = _ready_to_screen(_controller(tmp_path))
    controller.freeze_candidates(("600000.SH",), ())

    with pytest.raises(InvalidRunTransition, match="READY_TO_ANALYZE"):
        controller.begin_analysis()

    controller.transition(FormalRunState.ACQUIRING_TARGET_PRIMARY)
    controller.record_group(AcquisitionGroupId.CANDIDATE_FUNDAMENTAL, "fund-v1")
    controller.record_group(AcquisitionGroupId.MANUAL_HOLDINGS, "holdings-v1")
    controller.transition(FormalRunState.VALIDATING_TARGET)
    controller.enter_ready_to_analyze()
    controller.begin_analysis()
    assert controller.receipt.state == FormalRunState.ANALYZING


def test_blocked_receipt_has_no_candidate_analysis_or_artifact_hashes(tmp_path):
    controller = _controller(tmp_path)
    controller.transition(FormalRunState.ACQUIRING_SCREENING_PRIMARY)
    controller.block(
        AcquisitionGroupId.MARKET_DECISION,
        reasons=("missing_target_date:2026-07-10",),
    )

    assert controller.receipt.state == FormalRunState.BLOCKED_NEEDS_HUMAN
    assert controller.receipt.candidate_set_id is None
    assert controller.receipt.evidence_hashes == {}
    assert controller.receipt.artifact_hashes == {}


def test_blocked_status_is_redacted_local_only_and_contains_operator_fields(tmp_path):
    controller = _controller(tmp_path)
    controller.transition(FormalRunState.ACQUIRING_SCREENING_PRIMARY)
    receipt = controller.block(
        AcquisitionGroupId.MARKET_DECISION,
        reasons=("token=secret-value missing_field:close",),
    )
    attempts = (
        RouteAttempt(
            route_id="primary.market.v1",
            route_kind=RouteKind.PRIMARY,
            attempt=1,
            status="failed",
            classification=FailureClassification.MISSING_FIELDS,
            message="Authorization: Bearer hidden-value",
            validation_reasons=("missing_field:close",),
        ),
    )

    path = write_blocked_status(
        tmp_path / "logs" / "run-daily",
        receipt,
        AcquisitionGroupId.MARKET_DECISION,
        attempts,
        ("missing_field:close",),
        "verify the complete market route and retry",
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    serialized = path.read_text(encoding="utf-8")
    assert payload["status"] == "blocked_needs_human"
    assert payload["failed_group"] == "market_decision"
    assert payload["operator_action"] == "verify the complete market route and retry"
    assert payload["analysis_impact"] == "all formal analysis and report output stopped"
    assert "secret-value" not in serialized
    assert "hidden-value" not in serialized
    assert (tmp_path / "logs" / "run-daily" / "latest-status.json").is_file()
    assert not (tmp_path / "reports").exists()


def test_blocked_retry_preserves_existing_report_and_current_pointer_bytes(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    report = reports / "index.html"
    pointer = reports / "current.json"
    report.write_bytes(b"old-report")
    pointer.write_bytes(b'{"run_id":"old"}\n')
    report_before = report.read_bytes()
    pointer_before = pointer.read_bytes()
    controller = _controller(tmp_path)
    controller.transition(FormalRunState.ACQUIRING_SCREENING_PRIMARY)
    receipt = controller.block(AcquisitionGroupId.MARKET_DECISION, ("incomplete",))

    write_blocked_status(
        tmp_path / "logs" / "run-daily",
        receipt,
        AcquisitionGroupId.MARKET_DECISION,
        (),
        ("incomplete",),
        "retry complete acquisition",
    )

    assert report.read_bytes() == report_before
    assert pointer.read_bytes() == pointer_before


def test_blocked_writer_rejects_publishable_report_tree(tmp_path):
    controller = _controller(tmp_path)
    controller.transition(FormalRunState.ACQUIRING_SCREENING_PRIMARY)
    receipt = controller.block(AcquisitionGroupId.MARKET_DECISION, ("incomplete",))

    with pytest.raises(ValueError, match="publishable report tree"):
        write_blocked_status(
            tmp_path / "reports" / "run-daily",
            receipt,
            AcquisitionGroupId.MARKET_DECISION,
            (),
            ("incomplete",),
            "retry",
        )
