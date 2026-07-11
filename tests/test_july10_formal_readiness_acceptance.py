from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from stock_analyzer.analysis.focus import FormalFocusDay, contiguous_focus_window
from stock_analyzer.data.acquisition import PermanentRouteFailure
from stock_analyzer.data.formal_routes import FormalRoutePair
from stock_analyzer.data.readiness import (
    JULY_10_OFFICIAL_SESSIONS,
    AcquisitionGroupContract,
    AcquisitionGroupId,
    AcquisitionPayload,
    AcquisitionRequest,
    FailureClassification,
    FormalRunState,
    RouteCapabilityEvidence,
    RouteKind,
    validate_group_payload,
)
from stock_analyzer.ops.activation import (
    ActivationError,
    InMemoryFormalLedger,
    activation_markers_agree,
)
from stock_analyzer.ops.formal_run import (
    FormalAcquisitionGroup,
    FormalAnalysisOutput,
    FormalPipelineDependencies,
    FormalScreeningOutput,
    run_formal_strategy_v2,
)
from stock_analyzer.pipeline import StoredAnalysisNotFound, render_report_for_date
from stock_analyzer.storage.evidence_store import LocalEvidenceStore
from stock_analyzer.storage.repositories import InMemoryAnalysisRepository
from tests.test_focus_strategy_v2 import _snapshot


TARGET = date(2026, 7, 10)
CUTOFF = datetime(2026, 7, 10, 16, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
CONTRACT_VERSION = "formal-v1"
SCREENING_CODES = ("600000.SH", "600001.SH")


class AcceptanceCallRecorder:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def record(self, value: str) -> None:
        self.calls.append(value)


class July10FixtureRoute:
    def __init__(
        self,
        group_id: AcquisitionGroupId,
        kind: RouteKind,
        recorder: AcceptanceCallRecorder,
        *,
        partial: bool = False,
        fail: bool = False,
    ) -> None:
        self.group_id = group_id
        self.kind = kind
        self.recorder = recorder
        self.partial = partial
        self.fail = fail
        self.route_id = f"{kind.value}.{group_id.value}.july10"
        self.capability = RouteCapabilityEvidence(
            route_id=self.route_id,
            group_id=group_id,
            contract_version=CONTRACT_VERSION,
            full_contract_tested=True,
            field_semantics_verified=True,
            full_universe_verified=True,
            post_close_verified=True,
            tested_at=CUTOFF,
            semantic_probe_hashes=(
                {
                    "populated_precise_time": "b" * 64,
                    "empty_coverage": "c" * 64,
                }
                if group_id is AcquisitionGroupId.OFFICIAL_EVENTS_RISK
                else {}
            ),
        )

    def fetch(self, request: AcquisitionRequest) -> AcquisitionPayload:
        self.recorder.record(f"route:{self.route_id}")
        if self.fail:
            raise PermanentRouteFailure(
                "synthetic complete route failure",
                FailureClassification.INCOMPLETE_UNIVERSE,
            )
        if self.group_id == AcquisitionGroupId.MARKET_DECISION:
            records = [
                {
                    "trade_date": session,
                    "ts_code": code,
                    "value": 100 + index,
                }
                for index, session in enumerate(JULY_10_OFFICIAL_SESSIONS)
                for code in SCREENING_CODES
                if not (
                    self.partial
                    and session == request.trade_date
                    and code == SCREENING_CODES[-1]
                )
            ]
            covered_dates = JULY_10_OFFICIAL_SESSIONS
            coverage_codes = SCREENING_CODES
        else:
            codes = request.target_codes
            if self.partial:
                codes = codes[:1]
            records = [
                {
                    "trade_date": request.trade_date,
                    "ts_code": code,
                    "value": 1,
                }
                for code in codes
            ]
            covered_dates = (request.trade_date,)
            coverage_codes = tuple(codes)
        return AcquisitionPayload(
            group_id=self.group_id,
            route_id=self.route_id,
            route_kind=self.kind,
            trade_date=request.trade_date,
            fetched_at=request.report_cutoff,
            source_names=(self.route_id,),
            records=tuple(records),
            covered_dates=tuple(covered_dates),
            coverage_codes=coverage_codes,
            coverage_proven=True,
            field_coverage={"trade_date": True, "ts_code": True, "value": True},
            contract_version=request.contract_version,
        )


class July10FixtureRoutes:
    def __init__(
        self,
        recorder: AcceptanceCallRecorder,
        *,
        partial_primary: bool = False,
        incomplete_backup: bool = False,
    ) -> None:
        self.recorder = recorder
        self.market_contract = AcquisitionGroupContract(
            group_id=AcquisitionGroupId.MARKET_DECISION,
            contract_version=CONTRACT_VERSION,
            required_fields=("trade_date", "ts_code", "value"),
            unique_key_fields=("trade_date", "ts_code"),
            current_fact_fields=("value",),
            minimum_history_sessions=82,
            expected_codes=SCREENING_CODES,
        )
        self.target_contract = AcquisitionGroupContract(
            group_id=AcquisitionGroupId.CANDIDATE_FUNDAMENTAL,
            contract_version=CONTRACT_VERSION,
            required_fields=("trade_date", "ts_code", "value"),
            unique_key_fields=("trade_date", "ts_code"),
            current_fact_fields=("value",),
        )
        self.screening = FormalAcquisitionGroup(
            contract=self.market_contract,
            routes=FormalRoutePair(
                primary=July10FixtureRoute(
                    AcquisitionGroupId.MARKET_DECISION,
                    RouteKind.PRIMARY,
                    recorder,
                    partial=partial_primary,
                ),
                backup=July10FixtureRoute(
                    AcquisitionGroupId.MARKET_DECISION,
                    RouteKind.BACKUP,
                    recorder,
                    partial=incomplete_backup,
                    fail=incomplete_backup,
                ),
            ),
        )
        self.target = FormalAcquisitionGroup(
            contract=self.target_contract,
            routes=FormalRoutePair(
                primary=July10FixtureRoute(
                    AcquisitionGroupId.CANDIDATE_FUNDAMENTAL,
                    RouteKind.PRIMARY,
                    recorder,
                ),
                backup=July10FixtureRoute(
                    AcquisitionGroupId.CANDIDATE_FUNDAMENTAL,
                    RouteKind.BACKUP,
                    recorder,
                ),
            ),
        )


def _dependencies(
    tmp_path: Path,
    routes: July10FixtureRoutes,
    recorder: AcceptanceCallRecorder,
    *,
    failure_point: str | None = None,
) -> FormalPipelineDependencies:
    store = LocalEvidenceStore(tmp_path / "local_warehouse" / "formal_evidence")
    ledger = InMemoryFormalLedger()

    def screen(receipt, payloads):
        recorder.record(f"screen:{receipt.state.value}")
        market = payloads[AcquisitionGroupId.MARKET_DECISION]
        assert len(set(market.covered_dates)) == 82
        return FormalScreeningOutput(
            ordered_codes=("600000.SH",),
            active_focus_codes=("600001.SH",),
        )

    def analyze(receipt, candidate_set, payloads):
        recorder.record(f"analyze:{receipt.state.value}")
        market = payloads[AcquisitionGroupId.MARKET_DECISION]
        target = payloads[AcquisitionGroupId.CANDIDATE_FUNDAMENTAL]
        focus_action = {
            "ts_code": "600001.SH",
            "decision": "continue_observation",
            "position_range": "0%-5%",
            "reasons": ["五日证据连续"],
            "confirmation": ["趋势延续"],
            "invalidation": ["跌破支撑"],
            "risk_if_wrong": ["趋势反转"],
        }
        return FormalAnalysisOutput(
            value={
                "sources": {
                    "market": market.route_id,
                    "target": target.route_id,
                },
                "focus_actions": [focus_action],
            },
            ledger_rows=(
                {"kind": "recommendation", "ts_code": "600000.SH"},
                {"kind": "focus", "ts_code": "600001.SH"},
            ),
            evidence_hashes={
                "600000.SH": "evidence-600000",
                "600001.SH": "evidence-600001",
            },
            pointer_payloads={
                tmp_path / "reports" / "current.json": (
                    b'{"run_id":"july10-formal"}\n'
                )
            },
            has_publishable_output=True,
        )

    def llm_express(receipt, analysis):
        recorder.record(f"llm:{receipt.state.value}")
        return {"summary": "结构化证据充分，维持审慎观察。"}

    def render(staging, receipt, analysis, narrative):
        recorder.record(f"render:{receipt.state.value}")
        (staging / "data").mkdir(parents=True, exist_ok=True)
        (staging / "daily" / TARGET.isoformat()).mkdir(parents=True, exist_ok=True)
        (staging / "index.html").write_text(
            "<html><body>Strategy V2 正式分析</body></html>",
            encoding="utf-8",
        )
        (staging / "daily" / TARGET.isoformat() / "index.html").write_text(
            "<html><body>2026-07-10 正式日报</body></html>",
            encoding="utf-8",
        )
        (staging / "data" / "latest.json").write_text(
            json.dumps(
                {
                    "trade_date": TARGET.isoformat(),
                    "report_mode": "production",
                    "is_fixture": False,
                    "recommendation_cards": [{"ts_code": "600000.SH"}],
                    "focus_actions": analysis["focus_actions"],
                    "narrative": narrative,
                    "sources": analysis["sources"],
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

    def verify(staging, artifact_hashes, receipt):
        recorder.record(f"verify:{receipt.state.value}")
        payload = json.loads(
            (staging / "data" / "latest.json").read_text(encoding="utf-8")
        )
        return (
            payload["report_mode"] == "production"
            and payload["is_fixture"] is False
            and "index.html" in artifact_hashes
        )

    return FormalPipelineDependencies(
        screening_routes=(routes.screening,),
        target_routes=(routes.target,),
        screen=screen,
        analyze=analyze,
        llm_express=llm_express,
        render=render,
        verify=verify,
        ledger=ledger,
        evidence_store=store,
        log_root=tmp_path / "logs" / "run-daily",
        activation_failure_point=failure_point,
    )


def test_july10_complete_82_session_path_generates_formal_strategy_v2_report(tmp_path):
    recorder = AcceptanceCallRecorder()
    routes = July10FixtureRoutes(recorder)
    dependencies = _dependencies(tmp_path, routes, recorder)

    result = run_formal_strategy_v2(
        TARGET,
        CUTOFF,
        dependencies,
        run_id="july10-formal",
    )

    assert len(JULY_10_OFFICIAL_SESSIONS) == 82
    assert JULY_10_OFFICIAL_SESSIONS[0] == date(2026, 3, 12)
    assert JULY_10_OFFICIAL_SESSIONS[-1] == TARGET
    assert result.receipt.state == FormalRunState.REPORT_GENERATED
    assert result.receipt.input_set_id is not None
    assert result.receipt.candidate_set_id is not None
    assert result.receipt.evidence_hashes
    for version_id in result.receipt.group_version_ids.values():
        assert dependencies.evidence_store.group_version_manifest(version_id).complete
    assert dependencies.evidence_store.frozen_report_reference(result.receipt.run_id).input_set_id == result.receipt.input_set_id
    report_json = tmp_path / "reports" / "data" / "latest.json"
    payload = json.loads(report_json.read_text(encoding="utf-8"))
    serialized = report_json.read_text(encoding="utf-8") + (tmp_path / "reports" / "index.html").read_text(encoding="utf-8")
    assert payload["report_mode"] == "production"
    assert payload["is_fixture"] is False
    assert '"is_fixture": true' not in serialized.lower()
    assert "fixture/sample" not in serialized.lower()
    assert "sample" not in serialized.lower()
    assert "total_score" not in serialized.lower()
    assert "总分" not in serialized
    for action in payload["focus_actions"]:
        assert {
            "decision",
            "position_range",
            "reasons",
            "confirmation",
            "invalidation",
            "risk_if_wrong",
        } <= set(action)


def test_july10_partial_primary_is_discarded_and_complete_backup_alone_supports_report(tmp_path):
    recorder = AcceptanceCallRecorder()
    routes = July10FixtureRoutes(recorder, partial_primary=True)
    dependencies = _dependencies(tmp_path, routes, recorder)

    result = run_formal_strategy_v2(
        TARGET,
        CUTOFF,
        dependencies,
        run_id="july10-backup",
    )

    market_version = result.receipt.group_version_ids[AcquisitionGroupId.MARKET_DECISION.value]
    market_payload = dependencies.evidence_store.read_group_version(market_version)
    assert result.receipt.state == FormalRunState.REPORT_GENERATED
    assert market_payload is not None
    assert market_payload.route_kind == RouteKind.BACKUP
    assert market_payload.source_names == ("backup.market_decision.july10",)
    assert all("primary" not in source for source in market_payload.source_names)
    assert result.analysis.value["sources"]["market"] == "backup.market_decision.july10"


def test_july10_incomplete_primary_and_backup_block_without_analysis_or_report(tmp_path):
    recorder = AcceptanceCallRecorder()
    routes = July10FixtureRoutes(
        recorder,
        partial_primary=True,
        incomplete_backup=True,
    )
    dependencies = _dependencies(tmp_path, routes, recorder)

    result = run_formal_strategy_v2(
        TARGET,
        CUTOFF,
        dependencies,
        run_id="july10-blocked",
    )

    assert result.receipt.state == FormalRunState.BLOCKED_NEEDS_HUMAN
    assert not any(call.startswith(("screen:", "analyze:", "llm:", "render:", "verify:")) for call in recorder.calls)
    assert dependencies.ledger.pending == {}
    assert dependencies.ledger.active == {}
    assert not (tmp_path / "reports").exists()
    status = json.loads(
        (tmp_path / "logs" / "run-daily" / "latest-status.json").read_text(
            encoding="utf-8"
        )
    )
    assert status["status"] == "blocked_needs_human"


def test_july10_recovered_primary_becomes_canonical_without_rewriting_frozen_report(tmp_path):
    recorder = AcceptanceCallRecorder()
    routes = July10FixtureRoutes(recorder, partial_primary=True)
    dependencies = _dependencies(tmp_path, routes, recorder)
    result = run_formal_strategy_v2(
        TARGET,
        CUTOFF,
        dependencies,
        run_id="july10-reconcile",
    )
    frozen_before = dependencies.evidence_store.frozen_report_reference(
        result.receipt.run_id
    )
    task_path = next((dependencies.evidence_store.root / "reconciliation").glob("*.json"))
    task = dependencies.evidence_store.reconciliation_task(task_path.stem)
    recovery_cutoff = CUTOFF + timedelta(days=1)
    request = AcquisitionRequest(
        run_id="primary-recovery",
        trade_date=TARGET,
        report_cutoff=recovery_cutoff,
        target_codes=(),
        contract_version=CONTRACT_VERSION,
    )
    primary_payload = July10FixtureRoute(
        AcquisitionGroupId.MARKET_DECISION,
        RouteKind.PRIMARY,
        recorder,
    ).fetch(request)
    validation = validate_group_payload(routes.market_contract, request, primary_payload)

    primary_manifest = dependencies.evidence_store.reconcile_primary(
        task.task_id,
        primary_payload,
        validation,
    )

    canonical = dependencies.evidence_store.canonical_manifest(
        AcquisitionGroupId.MARKET_DECISION,
        TARGET,
    )
    frozen_after = dependencies.evidence_store.frozen_report_reference(
        result.receipt.run_id
    )
    assert canonical.version_id == primary_manifest.version_id
    assert primary_manifest.route_kind == RouteKind.PRIMARY
    assert frozen_after == frozen_before
    assert result.receipt.group_version_ids[AcquisitionGroupId.MARKET_DECISION.value] == task.backup_version_id
    assert dependencies.evidence_store.version_path(task.backup_version_id).is_file()


def test_july10_focus_history_breaks_on_blocked_eligible_day():
    prior_dates = list(JULY_10_OFFICIAL_SESSIONS[-6:-1])
    snapshots = [_snapshot(day, "600000.SH") for day in prior_dates]
    complete_days = [
        FormalFocusDay(trade_date=day, formally_committed=True)
        for day in prior_dates
    ]
    blocked_days = list(complete_days)
    blocked_days[2] = blocked_days[2].model_copy(
        update={"formally_committed": False, "blocked": True}
    )

    assert len(contiguous_focus_window(snapshots, complete_days, TARGET)) == 5
    assert contiguous_focus_window(snapshots, blocked_days, TARGET) == []


def test_july10_direct_render_rejects_rows_without_committed_receipt(tmp_path):
    repository = InMemoryAnalysisRepository()

    with pytest.raises(StoredAnalysisNotFound, match="committed REPORT_GENERATED receipt"):
        render_report_for_date(
            TARGET,
            tmp_path / "reports",
            repository=repository,
            expected_input_set_id="input-uncredentialed",
        )


@pytest.mark.parametrize(
    "failure_point",
    ["render", "verify", "ledger_prepare", "pointer"],
)
def test_july10_atomic_failures_preserve_all_formal_consumers(tmp_path, failure_point):
    recorder = AcceptanceCallRecorder()
    routes = July10FixtureRoutes(recorder)
    dependencies = _dependencies(
        tmp_path,
        routes,
        recorder,
        failure_point=failure_point,
    )
    reports = tmp_path / "reports"
    reports.mkdir(parents=True)
    prior_report = reports / "index.html"
    pointer = reports / "current.json"
    prior_report.write_bytes(b"prior-report")
    pointer.write_bytes(b'{"run_id":"prior"}\n')

    with pytest.raises(ActivationError, match=failure_point):
        run_formal_strategy_v2(
            TARGET,
            CUTOFF,
            dependencies,
            run_id=f"atomic-{failure_point}",
        )

    receipt = dependencies.evidence_store.latest_run_receipt(
        f"atomic-{failure_point}"
    )
    assert receipt.state == FormalRunState.FAILED_RETRYABLE
    assert prior_report.read_bytes() == b"prior-report"
    assert pointer.read_bytes() == b'{"run_id":"prior"}\n'
    assert activation_markers_agree(receipt, dependencies.ledger) is False
