from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from stock_analyzer.data.formal_routes import FormalRoutePair
from stock_analyzer.data.readiness import (
    AcquisitionGroupContract,
    AcquisitionGroupId,
    AcquisitionPayload,
    FailureClassification,
    FormalRunState,
    GroupValidation,
    RouteCapabilityEvidence,
    RouteKind,
)
from stock_analyzer.data.acquisition import PermanentRouteFailure
from stock_analyzer.ops.activation import InMemoryFormalLedger
from stock_analyzer.ops.formal_run import (
    FormalAcquisitionGroup,
    FormalAnalysisOutput,
    FormalPipelineDependencies,
    FormalScreeningOutput,
    RunReceipt,
    run_formal_strategy_v2,
)
from stock_analyzer.pipeline import (
    ProductionDataSourceUnavailable,
    StoredAnalysisNotFound,
    render_report_for_date,
    run_daily_pipeline,
)
from stock_analyzer.storage.evidence_store import LocalEvidenceStore
from stock_analyzer.storage.repositories import InMemoryAnalysisRepository


TARGET = date(2026, 7, 10)
CUTOFF = datetime(2026, 7, 10, 16, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
CONTRACT_VERSION = "formal-v1"


class FakeRoute:
    def __init__(
        self,
        group_id: AcquisitionGroupId,
        kind: RouteKind,
        calls: list[str],
        *,
        incomplete: bool = False,
        fail: bool = False,
    ) -> None:
        self.group_id = group_id
        self.kind = kind
        self.calls = calls
        self.incomplete = incomplete
        self.fail = fail
        self.route_id = f"{kind.value}.{group_id.value}.v1"
        self.capability = RouteCapabilityEvidence(
            route_id=self.route_id,
            group_id=group_id,
            contract_version=CONTRACT_VERSION,
            full_contract_tested=True,
            field_semantics_verified=True,
            full_universe_verified=True,
            post_close_verified=True,
            tested_at=CUTOFF,
        )

    def fetch(self, request):
        self.calls.append(self.route_id)
        if self.fail:
            raise PermanentRouteFailure(
                "recorded route failed",
                FailureClassification.MISSING_FIELDS,
            )
        codes = request.target_codes or ("600000.SH", "600001.SH")
        if self.incomplete:
            codes = codes[:1]
        records = tuple(
            {
                "trade_date": request.trade_date,
                "ts_code": code,
                "value": 1,
            }
            for code in codes
        )
        return AcquisitionPayload(
            group_id=self.group_id,
            route_id=self.route_id,
            route_kind=self.kind,
            trade_date=request.trade_date,
            fetched_at=request.report_cutoff,
            source_names=(self.route_id,),
            records=records,
            covered_dates=(request.trade_date,),
            coverage_codes=tuple(codes),
            coverage_proven=True,
            field_coverage={"trade_date": True, "ts_code": True, "value": True},
            contract_version=request.contract_version,
        )


def _group(
    group_id: AcquisitionGroupId,
    calls: list[str],
    *,
    expected_codes: tuple[str, ...] = (),
    primary_incomplete: bool = False,
    backup_incomplete: bool = False,
    primary_fail: bool = False,
    backup_fail: bool = False,
) -> FormalAcquisitionGroup:
    return FormalAcquisitionGroup(
        contract=AcquisitionGroupContract(
            group_id=group_id,
            contract_version=CONTRACT_VERSION,
            required_fields=("trade_date", "ts_code", "value"),
            unique_key_fields=("trade_date", "ts_code"),
            current_fact_fields=("value",),
            expected_codes=expected_codes,
        ),
        routes=FormalRoutePair(
            primary=FakeRoute(
                group_id,
                RouteKind.PRIMARY,
                calls,
                incomplete=primary_incomplete,
                fail=primary_fail,
            ),
            backup=FakeRoute(
                group_id,
                RouteKind.BACKUP,
                calls,
                incomplete=backup_incomplete,
                fail=backup_fail,
            ),
        ),
    )


def _dependencies(
    tmp_path: Path,
    calls: list[str],
    *,
    screening_group: FormalAcquisitionGroup | None = None,
    target_group: FormalAcquisitionGroup | None = None,
) -> FormalPipelineDependencies:
    evidence_store = LocalEvidenceStore(tmp_path / "local_warehouse" / "formal_evidence")
    ledger = InMemoryFormalLedger()
    screening_group = screening_group or _group(
        AcquisitionGroupId.MARKET_DECISION,
        calls,
        expected_codes=("600000.SH", "600001.SH"),
    )
    target_group = target_group or _group(
        AcquisitionGroupId.CANDIDATE_FUNDAMENTAL,
        calls,
    )

    def screen(receipt, payloads):
        calls.append(f"screen:{receipt.state.value}")
        assert set(payloads) == {AcquisitionGroupId.MARKET_DECISION}
        return FormalScreeningOutput(
            ordered_codes=("600000.SH",),
            active_focus_codes=("600001.SH",),
        )

    def analyze(receipt, candidate_set, payloads):
        calls.append(f"analyze:{receipt.state.value}")
        assert candidate_set.ordered_codes == ("600000.SH",)
        assert set(payloads) == {
            AcquisitionGroupId.MARKET_DECISION,
            AcquisitionGroupId.CANDIDATE_FUNDAMENTAL,
        }
        return FormalAnalysisOutput(
            value={"recommendations": ["600000.SH"]},
            ledger_rows=({"kind": "recommendation", "ts_code": "600000.SH"},),
            evidence_hashes={"600000.SH": "evidence-hash"},
            pointer_payloads={
                tmp_path / "reports" / "current.json": b'{"run_id":"formal-run"}\n'
            },
            has_publishable_output=True,
        )

    def llm_express(receipt, analysis):
        calls.append(f"llm:{receipt.state.value}")
        return {"text": "structured facts only"}

    def render(staging, receipt, analysis, narrative):
        calls.append(f"render:{receipt.state.value}")
        staging.mkdir(parents=True, exist_ok=True)
        (staging / "index.html").write_text("<html>formal</html>", encoding="utf-8")
        (staging / "latest.json").write_text(
            '{"report_mode":"production"}\n', encoding="utf-8"
        )

    def verify(staging, artifact_hashes, receipt):
        calls.append(f"verify:{receipt.state.value}")
        return set(artifact_hashes) == {"index.html", "latest.json"}

    return FormalPipelineDependencies(
        screening_routes=(screening_group,),
        target_routes=(target_group,),
        screen=screen,
        analyze=analyze,
        llm_express=llm_express,
        render=render,
        verify=verify,
        ledger=ledger,
        evidence_store=evidence_store,
        log_root=tmp_path / "logs" / "run-daily",
    )


def test_screening_gate_cannot_call_analysis_llm_render_or_ledger(tmp_path):
    calls: list[str] = []
    failing_screening = _group(
        AcquisitionGroupId.MARKET_DECISION,
        calls,
        expected_codes=("600000.SH", "600001.SH"),
        primary_fail=True,
        backup_fail=True,
    )
    dependencies = _dependencies(
        tmp_path,
        calls,
        screening_group=failing_screening,
    )

    result = run_formal_strategy_v2(
        TARGET,
        CUTOFF,
        dependencies,
        run_id="screening-block",
    )

    assert result.receipt.state == FormalRunState.BLOCKED_NEEDS_HUMAN
    assert not any(call.startswith(("screen:", "analyze:", "llm:", "render:", "verify:")) for call in calls)
    assert dependencies.ledger.pending == {}
    assert (dependencies.log_root / "screening-block.json").is_file()
    assert not (tmp_path / "reports").exists()


def test_target_failure_for_frozen_candidate_blocks_without_promotion(tmp_path):
    calls: list[str] = []
    failing_target = _group(
        AcquisitionGroupId.CANDIDATE_FUNDAMENTAL,
        calls,
        primary_incomplete=True,
        backup_incomplete=True,
    )
    dependencies = _dependencies(tmp_path, calls, target_group=failing_target)

    result = run_formal_strategy_v2(
        TARGET,
        CUTOFF,
        dependencies,
        run_id="target-block",
    )

    assert result.receipt.state == FormalRunState.BLOCKED_NEEDS_HUMAN
    frozen = dependencies.evidence_store.candidate_set(result.receipt.candidate_set_id)
    assert frozen.ordered_codes == ("600000.SH",)
    assert not any(call.startswith(("analyze:", "llm:", "render:", "verify:")) for call in calls)
    assert "600001.SH" not in frozen.ordered_codes


def test_target_retry_reuses_same_run_and_frozen_candidate_set(tmp_path):
    calls: list[str] = []
    blocked_dependencies = _dependencies(
        tmp_path,
        calls,
        target_group=_group(
            AcquisitionGroupId.CANDIDATE_FUNDAMENTAL,
            calls,
            primary_fail=True,
            backup_fail=True,
        ),
    )
    blocked = run_formal_strategy_v2(
        TARGET,
        CUTOFF,
        blocked_dependencies,
        run_id="same-run-target-retry",
    )
    frozen_id = blocked.receipt.candidate_set_id

    def forbidden_screen(*_args):
        raise AssertionError("target retry must not rerun screening")

    retry_dependencies = replace(
        _dependencies(tmp_path, calls),
        evidence_store=blocked_dependencies.evidence_store,
        ledger=blocked_dependencies.ledger,
        screen=forbidden_screen,
    )
    completed = run_formal_strategy_v2(
        TARGET,
        CUTOFF,
        retry_dependencies,
        run_id="same-run-target-retry",
    )

    assert completed.receipt.state == FormalRunState.REPORT_GENERATED
    assert completed.receipt.candidate_set_id == frozen_id
    assert completed.candidate_set.candidate_set_id == frozen_id


def test_required_group_failure_calls_no_strategy_llm_report_publish_or_decision_write(tmp_path):
    calls: list[str] = []
    dependencies = _dependencies(
        tmp_path,
        calls,
        target_group=_group(
            AcquisitionGroupId.CANDIDATE_FUNDAMENTAL,
            calls,
            primary_fail=True,
            backup_fail=True,
        ),
    )

    result = run_formal_strategy_v2(TARGET, CUTOFF, dependencies, run_id="hard-block")

    assert result.receipt.state == FormalRunState.BLOCKED_NEEDS_HUMAN
    assert dependencies.ledger.active == {}
    assert dependencies.ledger.pending == {}
    assert not (tmp_path / "reports" / "current.json").exists()


def test_market_group_inherits_validated_calendar_universe_coverage(tmp_path):
    calls: list[str] = []
    calendar = _group(
        AcquisitionGroupId.CALENDAR_UNIVERSE,
        calls,
        expected_codes=("600000.SH", "600001.SH"),
    )
    partial_market = _group(
        AcquisitionGroupId.MARKET_DECISION,
        calls,
        primary_incomplete=True,
        backup_incomplete=True,
    )
    dependencies = replace(
        _dependencies(tmp_path, calls),
        screening_routes=(calendar, partial_market),
        target_routes=(
            _group(
                AcquisitionGroupId.CANDIDATE_FUNDAMENTAL,
                calls,
                primary_fail=True,
                backup_fail=True,
            ),
        ),
        screen=lambda receipt, payloads: FormalScreeningOutput(
            ordered_codes=("600000.SH",),
        ),
    )

    result = run_formal_strategy_v2(
        TARGET,
        CUTOFF,
        dependencies,
        run_id="dynamic-universe-block",
    )

    assert result.receipt.state == FormalRunState.BLOCKED_NEEDS_HUMAN
    assert result.receipt.blocked_group == AcquisitionGroupId.MARKET_DECISION
    assert any("missing_code:600001.SH" in reason for reason in result.receipt.blocked_reasons)
    assert not any(call.startswith("screen:") for call in calls)


def test_complete_run_calls_analysis_only_after_ready_to_analyze(tmp_path):
    calls: list[str] = []
    dependencies = _dependencies(tmp_path, calls)

    result = run_formal_strategy_v2(TARGET, CUTOFF, dependencies, run_id="formal-run")

    assert result.receipt.state == FormalRunState.REPORT_GENERATED
    assert "screen:ready_to_screen" in calls
    assert "analyze:analyzing" in calls
    assert "llm:analyzing" in calls
    assert "render:rendering" in calls
    assert "verify:verifying" in calls
    assert result.receipt.input_set_id is not None
    assert result.receipt.candidate_set_id is not None
    assert result.receipt.evidence_hashes == {"600000.SH": "evidence-hash"}
    assert result.receipt.artifact_hashes
    assert dependencies.ledger.visible_rows(
        result.receipt.run_id, result.receipt.local_activation_id
    ) == [{"kind": "recommendation", "ts_code": "600000.SH"}]


@pytest.mark.parametrize(
    ("state", "local_activation_id", "ledger_activation_id", "expected_input_set_id"),
    [
        (FormalRunState.BLOCKED_NEEDS_HUMAN, None, None, "input-1"),
        (FormalRunState.COMMITTING, None, None, "input-1"),
        (FormalRunState.REPORT_GENERATED, "activation-1", "activation-1", "wrong-input"),
    ],
)
def test_manual_render_rejects_blocked_uncommitted_and_mismatched_receipts(
    tmp_path,
    state,
    local_activation_id,
    ledger_activation_id,
    expected_input_set_id,
):
    store = LocalEvidenceStore(tmp_path / "evidence")
    store.save_run_receipt(
        RunReceipt(
            run_id=f"receipt-{state.value}",
            target_date=TARGET,
            report_cutoff=CUTOFF,
            acquisition_contract_version=CONTRACT_VERSION,
            screening_version="screen-v1",
            state=state,
            group_version_ids={"market_decision": "version-1"},
            input_set_id="input-1",
            candidate_set_id="candidate-1",
            evidence_hashes={"evidence": "hash"},
            artifact_hashes={"index.html": "hash"},
            local_activation_id=local_activation_id,
            ledger_activation_id=ledger_activation_id,
        )
    )

    with pytest.raises(StoredAnalysisNotFound, match="committed REPORT_GENERATED receipt|input_set_id"):
        render_report_for_date(
            TARGET,
            tmp_path / "reports",
            repository=InMemoryAnalysisRepository(),
            receipt_store=store,
            expected_input_set_id=expected_input_set_id,
        )


def test_manual_render_rejects_missing_receipt_store_before_reading_rows(tmp_path):
    with pytest.raises(StoredAnalysisNotFound, match="committed REPORT_GENERATED receipt"):
        render_report_for_date(
            TARGET,
            tmp_path / "reports",
            repository=InMemoryAnalysisRepository(),
            expected_input_set_id="input-1",
        )


def test_manual_render_accepts_only_matching_committed_report_generated_receipt(tmp_path):
    repository = InMemoryAnalysisRepository()
    run_daily_pipeline(
        TARGET,
        tmp_path / "fixture-report",
        repository=repository,
        fixture_mode=True,
        persist=True,
    )
    store = LocalEvidenceStore(tmp_path / "evidence")
    store.save_run_receipt(
        RunReceipt(
            run_id="committed-run",
            target_date=TARGET,
            report_cutoff=CUTOFF,
            acquisition_contract_version=CONTRACT_VERSION,
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
    )

    result = render_report_for_date(
        TARGET,
        tmp_path / "reports",
        repository=repository,
        receipt_store=store,
        expected_input_set_id="input-1",
    )

    assert result.trade_date == TARGET
    assert (tmp_path / "reports" / "data" / "latest.json").is_file()


def test_legacy_complete_provider_cannot_bypass_formal_run_receipt(tmp_path):
    from tests.test_pipeline_smoke import FakeProductionProvider

    repository = InMemoryAnalysisRepository()

    with pytest.raises(
        ProductionDataSourceUnavailable,
        match="run_formal_strategy_v2",
    ):
        run_daily_pipeline(
            TARGET,
            tmp_path / "reports",
            repository=repository,
            fixture_mode=False,
            market_data_provider=FakeProductionProvider(),
        )

    assert repository.recommendations == []
    assert not (tmp_path / "reports" / "index.html").exists()
