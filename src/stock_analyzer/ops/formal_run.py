from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field

from stock_analyzer.data.acquisition import (
    AcquisitionBlocked,
    AcquisitionResult,
    AtomicGroupAcquirer,
    RouteAttempt,
    RouteFailure,
)
from stock_analyzer.data.formal_routes import (
    FormalRoutePair,
    derive_expected_tradable_codes,
)
from stock_analyzer.data.readiness import (
    AcquisitionGroupContract,
    AcquisitionGroupId,
    AcquisitionPayload,
    AcquisitionRequest,
    FailureClassification,
    FormalRunState,
    GroupValidation,
    RouteKind,
    validate_group_payload,
)
from stock_analyzer.ops.redaction import redact_secrets
from stock_analyzer.storage.evidence_store import (
    FrozenReportReference,
    LocalEvidenceStore,
)


class InvalidRunTransition(RuntimeError):
    pass


class RunReceipt(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    target_date: date
    report_cutoff: datetime
    acquisition_contract_version: str
    screening_version: str
    state: FormalRunState
    group_version_ids: dict[str, str] = Field(default_factory=dict)
    input_set_id: str | None = None
    candidate_set_id: str | None = None
    evidence_hashes: dict[str, str] = Field(default_factory=dict)
    artifact_hashes: dict[str, str] = Field(default_factory=dict)
    local_activation_id: str | None = None
    ledger_activation_id: str | None = None
    blocked_group: AcquisitionGroupId | None = None
    blocked_reasons: tuple[str, ...] = ()
    revision: int = Field(default=0, ge=0)


class CandidateSet(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidate_set_id: str
    run_id: str
    ordered_codes: tuple[str, ...]
    active_focus_codes: tuple[str, ...]
    screening_version: str
    upstream_input_set_id: str
    content_hash: str


@dataclass(frozen=True)
class FormalAcquisitionGroup:
    contract: AcquisitionGroupContract
    routes: FormalRoutePair


@dataclass(frozen=True)
class FormalScreeningOutput:
    ordered_codes: tuple[str, ...]
    active_focus_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class FormalAnalysisOutput:
    value: Any
    ledger_rows: tuple[dict[str, Any], ...]
    evidence_hashes: dict[str, str]
    pointer_payloads: dict[Path, bytes] = field(default_factory=dict)
    has_publishable_output: bool = True


@dataclass(frozen=True)
class FormalPipelineDependencies:
    screening_routes: tuple[FormalAcquisitionGroup, ...]
    target_routes: tuple[FormalAcquisitionGroup, ...]
    screen: Callable[..., FormalScreeningOutput]
    analyze: Callable[..., FormalAnalysisOutput]
    llm_express: Callable[..., Any] | None
    render: Callable[..., None]
    verify: Callable[..., bool]
    ledger: Any
    evidence_store: LocalEvidenceStore
    log_root: Path
    activation_failure_point: str | None = None


@dataclass(frozen=True)
class FormalRunResult:
    receipt: RunReceipt
    candidate_set: CandidateSet | None = None
    analysis: FormalAnalysisOutput | None = None
    narrative: Any = None


ALLOWED_TRANSITIONS: dict[FormalRunState, set[FormalRunState]] = {
    FormalRunState.PENDING: {
        FormalRunState.ACQUIRING_SCREENING_PRIMARY,
        FormalRunState.BLOCKED_NEEDS_HUMAN,
    },
    FormalRunState.ACQUIRING_SCREENING_PRIMARY: {
        FormalRunState.ACQUIRING_SCREENING_BACKUP,
        FormalRunState.VALIDATING_SCREENING,
        FormalRunState.BLOCKED_NEEDS_HUMAN,
    },
    FormalRunState.ACQUIRING_SCREENING_BACKUP: {
        FormalRunState.VALIDATING_SCREENING,
        FormalRunState.BLOCKED_NEEDS_HUMAN,
    },
    FormalRunState.VALIDATING_SCREENING: {
        FormalRunState.READY_TO_SCREEN,
        FormalRunState.BLOCKED_NEEDS_HUMAN,
    },
    FormalRunState.READY_TO_SCREEN: {
        FormalRunState.SCREENING,
        FormalRunState.BLOCKED_NEEDS_HUMAN,
    },
    FormalRunState.SCREENING: {
        FormalRunState.TARGET_SET_FROZEN,
        FormalRunState.BLOCKED_NEEDS_HUMAN,
    },
    FormalRunState.TARGET_SET_FROZEN: {
        FormalRunState.ACQUIRING_TARGET_PRIMARY,
        FormalRunState.BLOCKED_NEEDS_HUMAN,
    },
    FormalRunState.ACQUIRING_TARGET_PRIMARY: {
        FormalRunState.ACQUIRING_TARGET_BACKUP,
        FormalRunState.VALIDATING_TARGET,
        FormalRunState.BLOCKED_NEEDS_HUMAN,
    },
    FormalRunState.ACQUIRING_TARGET_BACKUP: {
        FormalRunState.VALIDATING_TARGET,
        FormalRunState.BLOCKED_NEEDS_HUMAN,
    },
    FormalRunState.VALIDATING_TARGET: {
        FormalRunState.READY_TO_ANALYZE,
        FormalRunState.BLOCKED_NEEDS_HUMAN,
    },
    FormalRunState.READY_TO_ANALYZE: {
        FormalRunState.ANALYZING,
        FormalRunState.BLOCKED_NEEDS_HUMAN,
    },
    FormalRunState.ANALYZING: {
        FormalRunState.RENDERING,
        FormalRunState.ANALYSIS_COMPLETE_NO_RECOMMENDATIONS,
        FormalRunState.BLOCKED_NEEDS_HUMAN,
    },
    FormalRunState.RENDERING: {
        FormalRunState.VERIFYING,
        FormalRunState.FAILED_RETRYABLE,
        FormalRunState.FAILED_NEEDS_HUMAN,
    },
    FormalRunState.VERIFYING: {
        FormalRunState.COMMITTING,
        FormalRunState.FAILED_RETRYABLE,
        FormalRunState.FAILED_NEEDS_HUMAN,
    },
    FormalRunState.COMMITTING: {
        FormalRunState.REPORT_GENERATED,
        FormalRunState.ANALYSIS_COMPLETE_NO_RECOMMENDATIONS,
        FormalRunState.FAILED_RETRYABLE,
        FormalRunState.FAILED_NEEDS_HUMAN,
    },
    FormalRunState.FAILED_RETRYABLE: {
        FormalRunState.RENDERING,
        FormalRunState.FAILED_NEEDS_HUMAN,
    },
    FormalRunState.BLOCKED_NEEDS_HUMAN: {
        FormalRunState.ACQUIRING_SCREENING_PRIMARY,
        FormalRunState.TARGET_SET_FROZEN,
    },
}


class FormalRunController:
    def __init__(self, store: LocalEvidenceStore, receipt: RunReceipt) -> None:
        self.store = store
        self.receipt = receipt

    @classmethod
    def start(
        cls,
        store: LocalEvidenceStore,
        *,
        run_id: str,
        target_date: date,
        report_cutoff: datetime,
        acquisition_contract_version: str,
        screening_version: str,
    ) -> "FormalRunController":
        receipt = RunReceipt(
            run_id=run_id,
            target_date=target_date,
            report_cutoff=report_cutoff,
            acquisition_contract_version=acquisition_contract_version,
            screening_version=screening_version,
            state=FormalRunState.PENDING,
        )
        store.save_run_receipt(receipt)
        return cls(store, receipt)

    @classmethod
    def resume(cls, store: LocalEvidenceStore, run_id: str) -> "FormalRunController":
        return cls(store, store.latest_run_receipt(run_id))

    def transition(self, next_state: FormalRunState) -> RunReceipt:
        allowed = ALLOWED_TRANSITIONS.get(self.receipt.state, set())
        if next_state not in allowed:
            raise InvalidRunTransition(
                f"cannot transition {self.receipt.state.name} to {next_state.name}"
            )
        return self._replace(state=next_state)

    def record_group(
        self,
        group_id: AcquisitionGroupId,
        version_id: str,
    ) -> RunReceipt:
        versions = dict(self.receipt.group_version_ids)
        existing = versions.get(group_id.value)
        if existing is not None and existing != version_id:
            raise ValueError(f"group version already frozen for {group_id.value}")
        versions[group_id.value] = version_id
        return self._replace(
            group_version_ids=versions,
            input_set_id=_input_set_id(versions),
        )

    def enter_ready_to_screen(self) -> RunReceipt:
        if self.receipt.state != FormalRunState.VALIDATING_SCREENING:
            raise InvalidRunTransition("READY_TO_SCREEN requires VALIDATING_SCREENING")
        if not self.receipt.group_version_ids:
            raise InvalidRunTransition("READY_TO_SCREEN requires screening group versions")
        return self.transition(FormalRunState.READY_TO_SCREEN)

    def freeze_candidates(
        self,
        ordered_codes: tuple[str, ...],
        active_focus_codes: tuple[str, ...],
    ) -> CandidateSet:
        if self.receipt.state != FormalRunState.READY_TO_SCREEN:
            raise InvalidRunTransition("candidate freeze requires READY_TO_SCREEN")
        if self.receipt.input_set_id is None:
            raise InvalidRunTransition("candidate freeze requires an upstream input set")
        self.transition(FormalRunState.SCREENING)
        content = {
            "run_id": self.receipt.run_id,
            "ordered_codes": list(ordered_codes),
            "active_focus_codes": list(active_focus_codes),
            "screening_version": self.receipt.screening_version,
            "upstream_input_set_id": self.receipt.input_set_id,
        }
        content_hash = _hash(content)
        candidate_set = CandidateSet(
            candidate_set_id=f"candidates-{content_hash}",
            run_id=self.receipt.run_id,
            ordered_codes=ordered_codes,
            active_focus_codes=active_focus_codes,
            screening_version=self.receipt.screening_version,
            upstream_input_set_id=self.receipt.input_set_id,
            content_hash=content_hash,
        )
        self.store.save_candidate_set(candidate_set)
        self._replace(
            state=FormalRunState.TARGET_SET_FROZEN,
            candidate_set_id=candidate_set.candidate_set_id,
        )
        return candidate_set

    def enter_ready_to_analyze(self) -> RunReceipt:
        if self.receipt.state != FormalRunState.VALIDATING_TARGET:
            raise InvalidRunTransition("READY_TO_ANALYZE requires VALIDATING_TARGET")
        if self.receipt.candidate_set_id is None:
            raise InvalidRunTransition("READY_TO_ANALYZE requires a frozen candidate set")
        return self.transition(FormalRunState.READY_TO_ANALYZE)

    def begin_analysis(self) -> RunReceipt:
        if self.receipt.state != FormalRunState.READY_TO_ANALYZE:
            raise InvalidRunTransition("analysis requires READY_TO_ANALYZE")
        return self.transition(FormalRunState.ANALYZING)

    def resume_blocked(self, next_state: FormalRunState) -> RunReceipt:
        if self.receipt.state != FormalRunState.BLOCKED_NEEDS_HUMAN:
            raise InvalidRunTransition("only a blocked receipt can resume")
        if next_state not in ALLOWED_TRANSITIONS[FormalRunState.BLOCKED_NEEDS_HUMAN]:
            raise InvalidRunTransition("invalid blocked-run resume stage")
        return self._replace(
            state=next_state,
            blocked_group=None,
            blocked_reasons=(),
        )

    def record_artifact_hashes(self, hashes: dict[str, str]) -> RunReceipt:
        if self.receipt.state != FormalRunState.RENDERING:
            raise InvalidRunTransition("artifact hashes require RENDERING")
        return self._replace(artifact_hashes=dict(sorted(hashes.items())))

    def record_evidence_hashes(self, hashes: dict[str, str]) -> RunReceipt:
        if self.receipt.state != FormalRunState.ANALYZING:
            raise InvalidRunTransition("evidence hashes require ANALYZING")
        return self._replace(evidence_hashes=dict(sorted(hashes.items())))

    def commit_activation(
        self,
        activation_id: str,
        *,
        no_recommendations: bool,
    ) -> RunReceipt:
        if self.receipt.state != FormalRunState.COMMITTING:
            raise InvalidRunTransition("formal activation requires COMMITTING")
        final_state = (
            FormalRunState.ANALYSIS_COMPLETE_NO_RECOMMENDATIONS
            if no_recommendations
            else FormalRunState.REPORT_GENERATED
        )
        return self._replace(
            state=final_state,
            local_activation_id=activation_id,
            ledger_activation_id=activation_id,
        )

    def block(
        self,
        group_id: AcquisitionGroupId,
        reasons: tuple[str, ...],
    ) -> RunReceipt:
        if self.receipt.state in {
            FormalRunState.REPORT_GENERATED,
            FormalRunState.ANALYSIS_COMPLETE_NO_RECOMMENDATIONS,
            FormalRunState.BLOCKED_NEEDS_HUMAN,
        }:
            raise InvalidRunTransition("terminal receipt cannot be blocked")
        if FormalRunState.BLOCKED_NEEDS_HUMAN not in ALLOWED_TRANSITIONS.get(
            self.receipt.state, set()
        ):
            raise InvalidRunTransition(
                f"cannot block from {self.receipt.state.name}"
            )
        return self._replace(
            state=FormalRunState.BLOCKED_NEEDS_HUMAN,
            blocked_group=group_id,
            blocked_reasons=tuple(redact_secrets(reason) for reason in reasons),
        )

    def _replace(self, **updates: Any) -> RunReceipt:
        updates["revision"] = self.receipt.revision + 1
        self.receipt = self.receipt.model_copy(update=updates)
        self.store.save_run_receipt(self.receipt)
        return self.receipt


def run_formal_strategy_v2(
    trade_date: date,
    report_cutoff: datetime,
    dependencies: FormalPipelineDependencies,
    run_id: str | None = None,
) -> FormalRunResult:
    if report_cutoff.tzinfo is None or report_cutoff.utcoffset() is None:
        raise ValueError("report_cutoff must be timezone-aware")
    effective_run_id = run_id or f"formal-{trade_date.isoformat()}-{uuid.uuid4().hex}"
    contract_version = _shared_contract_version(dependencies)
    try:
        existing_receipt = dependencies.evidence_store.latest_run_receipt(
            effective_run_id
        )
    except FileNotFoundError:
        existing_receipt = None
    if existing_receipt is None:
        controller = FormalRunController.start(
            dependencies.evidence_store,
            run_id=effective_run_id,
            target_date=trade_date,
            report_cutoff=report_cutoff,
            acquisition_contract_version=contract_version,
            screening_version="strategy-v2-screen-v1",
        )
    else:
        if (
            existing_receipt.target_date != trade_date
            or existing_receipt.report_cutoff != report_cutoff
            or existing_receipt.acquisition_contract_version != contract_version
        ):
            raise ValueError("formal run resume date, cutoff, or contract mismatch")
        if existing_receipt.state != FormalRunState.BLOCKED_NEEDS_HUMAN:
            raise InvalidRunTransition(
                f"formal run {effective_run_id} cannot resume from {existing_receipt.state.value}"
            )
        controller = FormalRunController(
            dependencies.evidence_store,
            existing_receipt,
        )
    candidate_set: CandidateSet | None = None
    all_payloads = _load_receipt_payloads(controller)
    resume_target = existing_receipt is not None and existing_receipt.candidate_set_id is not None
    if resume_target:
        candidate_set = dependencies.evidence_store.candidate_set(
            existing_receipt.candidate_set_id
        )
        controller.resume_blocked(FormalRunState.TARGET_SET_FROZEN)
    elif existing_receipt is not None:
        controller.resume_blocked(FormalRunState.ACQUIRING_SCREENING_PRIMARY)

    try:
        if not resume_target:
            if controller.receipt.state == FormalRunState.PENDING:
                controller.transition(FormalRunState.ACQUIRING_SCREENING_PRIMARY)
            screening_payloads, screening_used_backup = _acquire_formal_groups(
                controller,
                dependencies.screening_routes,
                target_codes=(),
            )
            all_payloads.update(screening_payloads)
            if screening_used_backup:
                controller.transition(FormalRunState.ACQUIRING_SCREENING_BACKUP)
            controller.transition(FormalRunState.VALIDATING_SCREENING)
            controller.enter_ready_to_screen()

            screening = dependencies.screen(
                controller.receipt,
                dict(screening_payloads),
            )
            if not isinstance(screening, FormalScreeningOutput):
                raise TypeError("screen must return FormalScreeningOutput")
            candidate_set = controller.freeze_candidates(
                screening.ordered_codes,
                screening.active_focus_codes,
            )
        if candidate_set is None:
            raise InvalidRunTransition("target acquisition requires frozen candidates")
        target_codes = tuple(
            dict.fromkeys(
                (*candidate_set.ordered_codes, *candidate_set.active_focus_codes)
            )
        )

        controller.transition(FormalRunState.ACQUIRING_TARGET_PRIMARY)
        target_payloads, target_used_backup = _acquire_formal_groups(
            controller,
            dependencies.target_routes,
            target_codes=target_codes,
        )
        all_payloads.update(target_payloads)
        if target_used_backup:
            controller.transition(FormalRunState.ACQUIRING_TARGET_BACKUP)
        controller.transition(FormalRunState.VALIDATING_TARGET)
        controller.enter_ready_to_analyze()
        controller.begin_analysis()

        analysis = dependencies.analyze(
            controller.receipt,
            candidate_set,
            dict(all_payloads),
        )
        if not isinstance(analysis, FormalAnalysisOutput):
            raise TypeError("analyze must return FormalAnalysisOutput")
        controller.record_evidence_hashes(analysis.evidence_hashes)
        narrative = (
            dependencies.llm_express(controller.receipt, analysis.value)
            if dependencies.llm_express is not None
            else None
        )

        from stock_analyzer.ops.activation import FormalActivationCoordinator

        report_root = Path(dependencies.log_root).parent.parent / "reports"
        coordinator = FormalActivationCoordinator(
            report_root,
            dependencies.evidence_store,
            dependencies.ledger,
            failure_point=dependencies.activation_failure_point,
        )

        def render(staging: Path) -> None:
            dependencies.render(
                staging,
                dependencies.evidence_store.latest_run_receipt(effective_run_id),
                analysis.value,
                narrative,
            )

        def verify(staging: Path, artifact_hashes: dict[str, str]) -> bool:
            return dependencies.verify(
                staging,
                artifact_hashes,
                dependencies.evidence_store.latest_run_receipt(effective_run_id),
            )

        completed = coordinator.activate(
            controller.receipt,
            render=render,
            verify=verify,
            ledger_rows=analysis.ledger_rows,
            pointer_payloads=analysis.pointer_payloads,
            advance_report_pointer=analysis.has_publishable_output,
        )
        if completed.input_set_id is None:
            raise ValueError("activated formal receipt lacks input_set_id")
        dependencies.evidence_store.save_frozen_report_reference(
            FrozenReportReference(
                run_id=completed.run_id,
                input_set_id=completed.input_set_id,
                group_version_ids=tuple(
                    completed.group_version_ids[key]
                    for key in sorted(completed.group_version_ids)
                ),
                artifact_hashes=completed.artifact_hashes,
            )
        )
        return FormalRunResult(
            receipt=completed,
            candidate_set=candidate_set,
            analysis=analysis,
            narrative=narrative,
        )
    except AcquisitionBlocked as exc:
        blocked = controller.block(exc.group_id, exc.reasons)
        write_blocked_status(
            dependencies.log_root,
            blocked,
            exc.group_id,
            exc.attempts,
            exc.reasons,
            "Inspect the failed complete route capability or data coverage, then retry the same frozen run only after correction.",
        )
        return FormalRunResult(receipt=blocked, candidate_set=candidate_set)


def _shared_contract_version(dependencies: FormalPipelineDependencies) -> str:
    groups = (*dependencies.screening_routes, *dependencies.target_routes)
    if not groups:
        raise ValueError("formal pipeline requires at least one acquisition group")
    versions = {group.contract.contract_version for group in groups}
    if len(versions) != 1:
        raise ValueError("formal acquisition groups must share one contract version")
    return versions.pop()


def _load_receipt_payloads(
    controller: FormalRunController,
) -> dict[AcquisitionGroupId, AcquisitionPayload]:
    payloads: dict[AcquisitionGroupId, AcquisitionPayload] = {}
    for group_name, version_id in controller.receipt.group_version_ids.items():
        group_id = AcquisitionGroupId(group_name)
        payload = controller.store.read_group_version(
            version_id,
            report_cutoff=controller.receipt.report_cutoff,
        )
        if payload is None:
            raise ValueError(f"frozen group version is not point-in-time valid: {version_id}")
        payloads[group_id] = payload
    return payloads


def _acquire_formal_groups(
    controller: FormalRunController,
    groups: tuple[FormalAcquisitionGroup, ...],
    *,
    target_codes: tuple[str, ...],
) -> tuple[dict[AcquisitionGroupId, AcquisitionPayload], bool]:
    payloads: dict[AcquisitionGroupId, AcquisitionPayload] = {}
    used_backup = False
    for group in groups:
        frozen_version_id = controller.receipt.group_version_ids.get(
            group.contract.group_id.value
        )
        if frozen_version_id is not None:
            frozen_payload = controller.store.read_group_version(
                frozen_version_id,
                report_cutoff=controller.receipt.report_cutoff,
            )
            if frozen_payload is None:
                raise AcquisitionBlocked(
                    group.contract.group_id,
                    (),
                    (f"frozen_group_invalid:{frozen_version_id}",),
                )
            payloads[group.contract.group_id] = frozen_payload
            continue
        request_target_codes = target_codes
        if (
            group.contract.group_id == AcquisitionGroupId.MARKET_DECISION
            and not group.contract.expected_codes
            and not request_target_codes
        ):
            universe = payloads.get(AcquisitionGroupId.CALENDAR_UNIVERSE)
            if (
                universe is None
                or not universe.coverage_proven
                or not universe.coverage_codes
            ):
                raise AcquisitionBlocked(
                    group.contract.group_id,
                    (),
                    ("validated_calendar_universe_coverage_required",),
                )
            sessions = sorted(set(universe.covered_dates))
            security_records = tuple(
                record
                for record in universe.records
                if record.get("record_type") == "security"
            )
            if len(sessions) < 61 or not security_records:
                raise AcquisitionBlocked(
                    group.contract.group_id,
                    (),
                    ("validated_calendar_eligibility_required",),
                )
            try:
                request_target_codes = derive_expected_tradable_codes(
                    security_records,
                    minimum_history_start=sessions[-61],
                )
            except ValueError as exc:
                raise AcquisitionBlocked(
                    group.contract.group_id,
                    (),
                    (str(exc),),
                ) from exc
            if not request_target_codes:
                raise AcquisitionBlocked(
                    group.contract.group_id,
                    (),
                    ("validated_calendar_has_no_analysis_eligible_codes",),
                )
        request = AcquisitionRequest(
            run_id=controller.receipt.run_id,
            trade_date=controller.receipt.target_date,
            report_cutoff=controller.receipt.report_cutoff,
            target_codes=request_target_codes,
            contract_version=group.contract.contract_version,
        )
        canonical = controller.store.canonical_manifest(
            group.contract.group_id,
            controller.receipt.target_date,
        )
        if canonical is not None:
            canonical_payload = controller.store.read_group_version(
                canonical.version_id,
                report_cutoff=controller.receipt.report_cutoff,
            )
            if canonical_payload is not None:
                canonical_validation = validate_group_payload(
                    group.contract,
                    request,
                    canonical_payload,
                )
                if canonical_validation.complete:
                    controller.record_group(
                        group.contract.group_id,
                        canonical.version_id,
                    )
                    payloads[group.contract.group_id] = canonical_payload
                    used_backup = (
                        used_backup
                        or canonical_payload.route_kind is RouteKind.BACKUP
                    )
                    continue
        result = _acquire_formal_group(group, request)
        manifest = controller.store.save_group_version(
            result.payload,
            result.validation,
        )
        controller.store.set_canonical(
            manifest.group_id,
            manifest.trade_date,
            manifest.version_id,
        )
        if result.used_backup:
            controller.store.create_reconciliation_task(manifest)
        controller.record_group(group.contract.group_id, manifest.version_id)
        payloads[group.contract.group_id] = result.payload
        used_backup = used_backup or result.used_backup
    return payloads, used_backup


def _acquire_formal_group(
    group: FormalAcquisitionGroup,
    request: AcquisitionRequest,
) -> AcquisitionResult:
    if group.routes.backup is not None:
        return AtomicGroupAcquirer().acquire(
            group.contract,
            request,
            group.routes.primary,
            group.routes.backup,
        )
    if not group.routes.approved_single_source:
        raise AcquisitionBlocked(
            group.contract.group_id,
            (),
            (f"single_source_not_approved:{group.contract.group_id.value}",),
        )
    route = group.routes.primary
    capability = route.capability
    capability_reasons = []
    if route.kind != RouteKind.LOCAL:
        capability_reasons.append(f"single_source_not_local:{route.route_id}")
    if capability.group_id != group.contract.group_id:
        capability_reasons.append(f"capability_group_mismatch:{route.route_id}")
    if capability.contract_version != group.contract.contract_version:
        capability_reasons.append(f"capability_contract_mismatch:{route.route_id}")
    if not capability.approved:
        capability_reasons.append(f"capability_unproven:{route.route_id}")
    if capability_reasons:
        raise AcquisitionBlocked(
            group.contract.group_id,
            (),
            tuple(capability_reasons),
        )
    try:
        payload = route.fetch(request)
    except RouteFailure as exc:
        attempt = RouteAttempt(
            route_id=route.route_id,
            route_kind=route.kind,
            attempt=1,
            status="failed",
            classification=exc.classification,
            message=exc.redacted_message,
        )
        raise AcquisitionBlocked(
            group.contract.group_id,
            (attempt,),
            (exc.redacted_message,),
        ) from exc
    except Exception as exc:
        message = redact_secrets(str(exc))
        attempt = RouteAttempt(
            route_id=route.route_id,
            route_kind=route.kind,
            attempt=1,
            status="failed",
            classification=FailureClassification.UNKNOWN,
            message=message,
        )
        raise AcquisitionBlocked(
            group.contract.group_id,
            (attempt,),
            (message,),
        ) from exc
    validation = validate_group_payload(group.contract, request, payload)
    if not validation.complete:
        attempt = RouteAttempt(
            route_id=route.route_id,
            route_kind=route.kind,
            attempt=1,
            status="failed",
            classification=FailureClassification.INVALID_SEMANTICS,
            message="complete single-source group rejected",
            validation_reasons=validation.reasons,
        )
        raise AcquisitionBlocked(
            group.contract.group_id,
            (attempt,),
            validation.reasons,
        )
    return AcquisitionResult(
        payload=payload,
        validation=validation,
        attempts=(
            RouteAttempt(
                route_id=route.route_id,
                route_kind=route.kind,
                attempt=1,
                status="success",
                message="complete single-source acquisition group accepted",
            ),
        ),
        used_backup=False,
    )


def write_blocked_status(
    log_root: Path,
    receipt: RunReceipt,
    group_id: AcquisitionGroupId,
    attempts: tuple[RouteAttempt, ...],
    reasons: tuple[str, ...],
    operator_action: str,
) -> Path:
    root = Path(log_root)
    if any(part.lower() in {"reports", "dist"} for part in root.parts):
        raise ValueError("blocked status cannot be written to a publishable report tree")
    payload = _redact_payload(
        {
            "run_id": receipt.run_id,
            "target_date": receipt.target_date.isoformat(),
            "report_cutoff": receipt.report_cutoff.isoformat(),
            "status": FormalRunState.BLOCKED_NEEDS_HUMAN.value,
            "failed_group": group_id.value,
            "attempts": [attempt.model_dump(mode="json") for attempt in attempts],
            "failure_reasons": list(reasons),
            "historical_cache_allowed": False,
            "historical_cache_reason": "current-day required facts cannot be replaced by cache",
            "analysis_impact": "all formal analysis and report output stopped",
            "retry_eligible": any(
                attempt.classification is not None
                and attempt.classification.value in {"transport", "rate_limit"}
                for attempt in attempts
            ),
            "operator_action": operator_action,
        }
    )
    serialized = (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")
    run_path = root / f"{receipt.run_id}.json"
    _atomic_write(run_path, serialized)
    _atomic_write(root / "latest-status.json", serialized)
    return run_path


def _input_set_id(versions: dict[str, str]) -> str:
    return f"input-{_hash(versions)}"


def _hash(value: Any) -> str:
    serialized = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _redact_payload(value: Any) -> Any:
    if isinstance(value, str):
        return redact_secrets(value)
    if isinstance(value, list):
        return [_redact_payload(item) for item in value]
    if isinstance(value, dict):
        return {key: _redact_payload(item) for key, item in value.items()}
    return value


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


__all__ = [
    "ALLOWED_TRANSITIONS",
    "CandidateSet",
    "FormalAcquisitionGroup",
    "FormalAnalysisOutput",
    "FormalPipelineDependencies",
    "FormalRunResult",
    "FormalRunController",
    "FormalScreeningOutput",
    "InvalidRunTransition",
    "RunReceipt",
    "run_formal_strategy_v2",
    "write_blocked_status",
]
