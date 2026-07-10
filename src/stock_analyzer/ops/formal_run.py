from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from stock_analyzer.data.acquisition import RouteAttempt
from stock_analyzer.data.readiness import AcquisitionGroupId, FormalRunState
from stock_analyzer.ops.redaction import redact_secrets
from stock_analyzer.storage.evidence_store import LocalEvidenceStore


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

    def record_artifact_hashes(self, hashes: dict[str, str]) -> RunReceipt:
        if self.receipt.state != FormalRunState.RENDERING:
            raise InvalidRunTransition("artifact hashes require RENDERING")
        return self._replace(artifact_hashes=dict(sorted(hashes.items())))

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
    "FormalRunController",
    "InvalidRunTransition",
    "RunReceipt",
    "write_blocked_status",
]
