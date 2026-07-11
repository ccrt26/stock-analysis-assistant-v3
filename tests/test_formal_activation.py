from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from stock_analyzer.data.readiness import AcquisitionGroupId, FormalRunState
from stock_analyzer.ops.activation import (
    ActivationError,
    FormalActivationCoordinator,
    InMemoryFormalLedger,
)
from stock_analyzer.ops.formal_run import FormalRunController
from stock_analyzer.storage.evidence_store import LocalEvidenceStore


TARGET = date(2026, 7, 10)
CUTOFF = datetime(2026, 7, 10, 16, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def _analyzing_controller(tmp_path: Path, run_id="activation-run") -> FormalRunController:
    store = LocalEvidenceStore(tmp_path / "evidence")
    controller = FormalRunController.start(
        store,
        run_id=run_id,
        target_date=TARGET,
        report_cutoff=CUTOFF,
        acquisition_contract_version="formal-v1",
        screening_version="screen-v1",
    )
    controller.transition(FormalRunState.ACQUIRING_SCREENING_PRIMARY)
    controller.record_group(AcquisitionGroupId.MARKET_DECISION, "market-v1")
    controller.transition(FormalRunState.VALIDATING_SCREENING)
    controller.enter_ready_to_screen()
    controller.freeze_candidates(("600000.SH",), ())
    controller.transition(FormalRunState.ACQUIRING_TARGET_PRIMARY)
    controller.record_group(AcquisitionGroupId.CANDIDATE_FUNDAMENTAL, "fund-v1")
    controller.transition(FormalRunState.VALIDATING_TARGET)
    controller.enter_ready_to_analyze()
    controller.begin_analysis()
    return controller


def _render(staging: Path) -> None:
    staging.mkdir(parents=True, exist_ok=True)
    (staging / "index.html").write_text("<html>formal</html>", encoding="utf-8")
    data = staging / "data"
    data.mkdir(exist_ok=True)
    (data / "latest.json").write_text('{"report_mode":"production"}\n', encoding="utf-8")


def _verify(staging: Path, artifact_hashes: dict[str, str]) -> bool:
    return (staging / "index.html").is_file() and set(artifact_hashes) == {
        "data/latest.json",
        "index.html",
    }


def test_pending_ledger_rows_are_invisible_until_both_markers_agree():
    ledger = InMemoryFormalLedger()
    rows = ({"kind": "focus", "ts_code": "600000.SH"},)
    pending_id = ledger.prepare_formal_run("run-1", "receipt-hash", rows)
    activation_id = "activation-1"

    assert ledger.visible_rows("run-1", local_activation_id=None) == []
    ledger.activate_formal_run("run-1", pending_id, activation_id)
    assert ledger.visible_rows("run-1", local_activation_id=None) == []
    assert ledger.visible_rows("run-1", local_activation_id=activation_id) == list(rows)


def test_prepare_candidate_preserves_active_report_and_ledger(tmp_path):
    controller = _analyzing_controller(tmp_path, run_id="human-gated")
    ledger = InMemoryFormalLedger()
    reports = tmp_path / "reports"
    reports.mkdir(exist_ok=True)
    prior = reports / "index.html"
    prior.write_bytes(b"prior-report")
    coordinator = FormalActivationCoordinator(reports, controller.store, ledger)

    candidate = coordinator.prepare_candidate(
        controller.receipt,
        render=_render,
        verify=_verify,
        ledger_rows=({"kind": "recommendation", "ts_code": "600000.SH"},),
        pointer_payloads={},
    )

    assert candidate.receipt.state is FormalRunState.AWAITING_HUMAN_ACCEPTANCE
    assert prior.read_bytes() == b"prior-report"
    assert ledger.active == {}
    assert ledger.pending == {}
    assert candidate.candidate_root.is_dir()


def test_activation_requires_exact_candidate_hash_and_does_not_rerender(tmp_path):
    controller = _analyzing_controller(tmp_path, run_id="exact-human-candidate")
    ledger = InMemoryFormalLedger()
    reports = tmp_path / "reports"
    render_calls: list[str] = []

    def render(staging):
        render_calls.append("render")
        _render(staging)

    coordinator = FormalActivationCoordinator(reports, controller.store, ledger)
    candidate = coordinator.prepare_candidate(
        controller.receipt,
        render=render,
        verify=_verify,
        ledger_rows=({"kind": "recommendation", "ts_code": "600000.SH"},),
        pointer_payloads={},
    )
    assert render_calls == ["render"]

    with pytest.raises(ActivationError, match="candidate hash"):
        coordinator.activate_prepared_candidate(candidate, "0" * 64)
    assert ledger.active == {}

    completed = coordinator.activate_prepared_candidate(
        candidate,
        candidate.candidate_hash,
    )
    assert completed.state is FormalRunState.REPORT_GENERATED
    assert render_calls == ["render"]
    assert ledger.activation_count == 1
    assert (reports / "index.html").read_bytes() == (
        candidate.candidate_root / "index.html"
    ).read_bytes()


@pytest.mark.parametrize(
    "failure_point",
    ["render", "verify", "ledger_prepare", "local_marker", "ledger_activate", "pointer"],
)
def test_each_activation_failure_preserves_prior_report_ledger_and_pointers(
    tmp_path,
    failure_point,
):
    controller = _analyzing_controller(tmp_path, run_id=f"failure-{failure_point}")
    ledger = InMemoryFormalLedger()
    reports = tmp_path / "reports"
    reports.mkdir(exist_ok=True)
    prior_report = reports / "index.html"
    pointer = reports / "current.json"
    prior_report.write_bytes(b"prior-report")
    pointer.write_bytes(b'{"run_id":"prior"}\n')
    coordinator = FormalActivationCoordinator(
        report_root=reports,
        evidence_store=controller.store,
        ledger=ledger,
        failure_point=failure_point,
    )

    with pytest.raises(ActivationError, match=failure_point):
        coordinator.activate(
            controller.receipt,
            render=_render,
            verify=_verify,
            ledger_rows=({"kind": "recommendation", "ts_code": "600000.SH"},),
            pointer_payloads={pointer: b'{"run_id":"new"}\n'},
        )

    latest = controller.store.latest_run_receipt(controller.receipt.run_id)
    assert latest.state == FormalRunState.FAILED_RETRYABLE
    assert prior_report.read_bytes() == b"prior-report"
    assert pointer.read_bytes() == b'{"run_id":"prior"}\n'
    assert ledger.visible_rows(latest.run_id, latest.local_activation_id) == []


def test_retry_is_idempotent_and_does_not_duplicate_rows_or_artifacts(tmp_path):
    controller = _analyzing_controller(tmp_path, run_id="retry-run")
    ledger = InMemoryFormalLedger()
    reports = tmp_path / "reports"
    reports.mkdir(exist_ok=True)
    pointer = reports / "current.json"
    pointer.write_bytes(b'{"run_id":"prior"}\n')
    rows = ({"kind": "recommendation", "ts_code": "600000.SH"},)
    failing = FormalActivationCoordinator(
        reports,
        controller.store,
        ledger,
        failure_point="pointer",
    )
    with pytest.raises(ActivationError):
        failing.activate(
            controller.receipt,
            render=_render,
            verify=_verify,
            ledger_rows=rows,
            pointer_payloads={pointer: b'{"run_id":"retry-run"}\n'},
        )

    retry_receipt = controller.store.latest_run_receipt("retry-run")
    completed = FormalActivationCoordinator(
        reports,
        controller.store,
        ledger,
    ).activate(
        retry_receipt,
        render=_render,
        verify=_verify,
        ledger_rows=rows,
        pointer_payloads={pointer: b'{"run_id":"retry-run"}\n'},
    )

    assert completed.state == FormalRunState.REPORT_GENERATED
    assert ledger.visible_rows(completed.run_id, completed.local_activation_id) == list(rows)
    assert ledger.activation_count == 1
    assert len(list((reports / ".staging" / "retry-run").rglob("index.html"))) == 1


def test_retry_rebuilds_staging_without_stale_partial_render_files(tmp_path):
    controller = _analyzing_controller(tmp_path, run_id="stale-retry")
    ledger = InMemoryFormalLedger()
    reports = tmp_path / "reports"

    def partial_render(staging):
        staging.mkdir(parents=True, exist_ok=True)
        (staging / "stale-secret-free-debug.txt").write_text(
            "partial",
            encoding="utf-8",
        )
        raise ActivationError("partial render failed")

    with pytest.raises(ActivationError, match="partial render failed"):
        FormalActivationCoordinator(
            reports,
            controller.store,
            ledger,
        ).activate(
            controller.receipt,
            render=partial_render,
            verify=_verify,
            ledger_rows=({"kind": "recommendation"},),
            pointer_payloads={},
        )

    completed = FormalActivationCoordinator(
        reports,
        controller.store,
        ledger,
    ).activate(
        controller.store.latest_run_receipt("stale-retry"),
        render=_render,
        verify=_verify,
        ledger_rows=({"kind": "recommendation"},),
        pointer_payloads={},
    )

    assert completed.state == FormalRunState.REPORT_GENERATED
    assert "stale-secret-free-debug.txt" not in completed.artifact_hashes
    assert not (reports / "stale-secret-free-debug.txt").exists()


def test_artifact_or_pending_hash_mismatch_fails_closed(tmp_path):
    class CorruptingLedger(InMemoryFormalLedger):
        def pending_hash(self, pending_id: str) -> str:
            return "corrupt"

    controller = _analyzing_controller(tmp_path, run_id="hash-mismatch")
    reports = tmp_path / "reports"
    reports.mkdir(exist_ok=True)
    pointer = reports / "current.json"
    pointer.write_bytes(b"prior")

    with pytest.raises(ActivationError, match="pending hash mismatch"):
        FormalActivationCoordinator(
            reports,
            controller.store,
            CorruptingLedger(),
        ).activate(
            controller.receipt,
            render=_render,
            verify=_verify,
            ledger_rows=({"kind": "focus"},),
            pointer_payloads={pointer: b"new"},
        )

    assert pointer.read_bytes() == b"prior"


def test_coordinator_does_not_move_local_pointer_when_strong_readback_fails(
    tmp_path,
):
    class ReadbackRejectingLedger(InMemoryFormalLedger):
        def verify_formal_run_active(
            self,
            run_id,
            activation_id,
            receipt_hash,
            rows_hash,
        ):
            return False

    controller = _analyzing_controller(tmp_path, run_id="readback-rejected")
    ledger = ReadbackRejectingLedger()
    reports = tmp_path / "reports"
    reports.mkdir(exist_ok=True)
    pointer = reports / "current.json"
    pointer.write_bytes(b"prior")

    with pytest.raises(ActivationError, match="strong readback"):
        FormalActivationCoordinator(
            reports,
            controller.store,
            ledger,
        ).activate(
            controller.receipt,
            render=_render,
            verify=_verify,
            ledger_rows=({"kind": "focus", "ts_code": "600000.SH"},),
            pointer_payloads={pointer: b"new"},
        )

    latest = controller.store.latest_run_receipt("readback-rejected")
    assert latest.state is FormalRunState.FAILED_RETRYABLE
    assert latest.local_activation_id is None
    assert pointer.read_bytes() == b"prior"
    assert ledger.visible_rows(latest.run_id, latest.local_activation_id) == []


def test_zero_recommendations_commits_focus_rows_without_advancing_report_pointer(tmp_path):
    controller = _analyzing_controller(tmp_path, run_id="focus-only")
    ledger = InMemoryFormalLedger()
    reports = tmp_path / "reports"
    reports.mkdir(exist_ok=True)
    pointer = reports / "current.json"
    pointer.write_bytes(b'{"run_id":"prior-recommendation"}\n')
    rows = ({"kind": "focus", "ts_code": "600000.SH"},)

    completed = FormalActivationCoordinator(
        reports,
        controller.store,
        ledger,
    ).activate(
        controller.receipt,
        render=_render,
        verify=_verify,
        ledger_rows=rows,
        pointer_payloads={pointer: b'{"run_id":"focus-only"}\n'},
        advance_report_pointer=False,
    )

    assert completed.state == FormalRunState.ANALYSIS_COMPLETE_NO_RECOMMENDATIONS
    assert pointer.read_bytes() == b'{"run_id":"prior-recommendation"}\n'
    assert ledger.visible_rows(completed.run_id, completed.local_activation_id) == list(rows)
