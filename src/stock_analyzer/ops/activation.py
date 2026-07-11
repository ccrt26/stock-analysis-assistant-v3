from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from stock_analyzer.data.readiness import FormalRunState
from stock_analyzer.ops.formal_run import (
    ALLOWED_TRANSITIONS,
    FormalRunController,
    RunReceipt,
)
from stock_analyzer.storage.evidence_store import LocalEvidenceStore


class ActivationError(RuntimeError):
    pass


@dataclass(frozen=True)
class PreparedReportCandidate:
    run_id: str
    candidate_root: Path
    artifact_hashes: dict[str, str]
    candidate_hash: str
    ledger_rows_hash: str
    narrative_hash: str
    receipt: RunReceipt


class FormalLedger(Protocol):
    def register_formal_receipt(
        self,
        receipt: RunReceipt,
        receipt_hash: str,
        final_state: FormalRunState,
    ) -> None: ...

    def prepare_formal_run(
        self,
        run_id: str,
        receipt_hash: str,
        rows: tuple[dict[str, Any], ...],
    ) -> str: ...

    def pending_hash(self, pending_id: str) -> str: ...

    def activate_formal_run(
        self,
        run_id: str,
        pending_id: str,
        activation_id: str,
    ) -> None: ...

    def is_formal_run_active(self, run_id: str, activation_id: str) -> bool: ...

    def verify_formal_run_active(
        self,
        run_id: str,
        activation_id: str,
        receipt_hash: str,
        rows_hash: str,
    ) -> bool: ...

    def discard_pending(self, pending_id: str) -> None: ...


class InMemoryFormalLedger:
    def __init__(self) -> None:
        self.pending: dict[str, dict[str, Any]] = {}
        self.active: dict[str, dict[str, str]] = {}
        self.activation_count = 0
        self.receipts: dict[str, dict[str, Any]] = {}

    def register_formal_receipt(
        self,
        receipt: RunReceipt,
        receipt_hash: str,
        final_state: FormalRunState,
    ) -> None:
        payload = {
            "receipt_hash": receipt_hash,
            "final_state": final_state,
        }
        existing = self.receipts.get(receipt.run_id)
        if existing is not None and existing != payload:
            raise ActivationError("formal receipt registration mismatch")
        self.receipts[receipt.run_id] = payload

    def prepare_formal_run(
        self,
        run_id: str,
        receipt_hash: str,
        rows: tuple[dict[str, Any], ...],
    ) -> str:
        rows_hash = hash_ledger_rows(rows)
        pending_id = f"pending-{_hash({'run_id': run_id, 'receipt_hash': receipt_hash, 'rows_hash': rows_hash})}"
        payload = {
            "run_id": run_id,
            "receipt_hash": receipt_hash,
            "rows": tuple(rows),
            "rows_hash": rows_hash,
        }
        existing = self.pending.get(pending_id)
        if existing is not None and existing != payload:
            raise ActivationError("pending batch id collision")
        self.pending[pending_id] = payload
        return pending_id

    def pending_hash(self, pending_id: str) -> str:
        return self.pending[pending_id]["rows_hash"]

    def activate_formal_run(
        self,
        run_id: str,
        pending_id: str,
        activation_id: str,
    ) -> None:
        pending = self.pending.get(pending_id)
        if pending is None or pending["run_id"] != run_id:
            raise ActivationError("pending batch does not belong to run")
        marker = {
            "pending_id": pending_id,
            "activation_id": activation_id,
        }
        existing = self.active.get(run_id)
        if existing is not None:
            if existing != marker:
                raise ActivationError("run is already active with another marker")
            return
        self.active[run_id] = marker
        self.activation_count += 1

    def is_formal_run_active(self, run_id: str, activation_id: str) -> bool:
        marker = self.active.get(run_id)
        return marker is not None and marker["activation_id"] == activation_id

    def verify_formal_run_active(
        self,
        run_id: str,
        activation_id: str,
        receipt_hash: str,
        rows_hash: str,
    ) -> bool:
        marker = self.active.get(run_id)
        receipt = self.receipts.get(run_id)
        if (
            marker is None
            or marker["activation_id"] != activation_id
            or receipt is None
            or receipt["receipt_hash"] != receipt_hash
        ):
            return False
        pending = self.pending.get(marker["pending_id"])
        return (
            pending is not None
            and pending["run_id"] == run_id
            and pending["receipt_hash"] == receipt_hash
            and pending["rows_hash"] == rows_hash
            and hash_ledger_rows(pending["rows"]) == rows_hash
        )

    def discard_pending(self, pending_id: str) -> None:
        if any(
            marker["pending_id"] == pending_id for marker in self.active.values()
        ):
            return
        self.pending.pop(pending_id, None)

    def visible_rows(
        self,
        run_id: str,
        local_activation_id: str | None,
    ) -> list[dict[str, Any]]:
        if local_activation_id is None or not self.is_formal_run_active(
            run_id, local_activation_id
        ):
            return []
        pending_id = self.active[run_id]["pending_id"]
        return list(self.pending[pending_id]["rows"])


class FormalActivationCoordinator:
    def __init__(
        self,
        report_root: Path,
        evidence_store: LocalEvidenceStore,
        ledger: FormalLedger,
        *,
        failure_point: str | None = None,
    ) -> None:
        self.report_root = Path(report_root)
        self.evidence_store = evidence_store
        self.ledger = ledger
        self.failure_point = failure_point

    def activate(
        self,
        receipt: RunReceipt,
        *,
        render: Callable[[Path], None],
        verify: Callable[[Path, dict[str, str]], bool],
        ledger_rows: tuple[dict[str, Any], ...],
        pointer_payloads: dict[Path, bytes],
        advance_report_pointer: bool = True,
    ) -> RunReceipt:
        candidate = self.prepare_candidate(
            receipt,
            render=render,
            verify=verify,
            ledger_rows=ledger_rows,
            pointer_payloads=pointer_payloads,
            advance_report_pointer=advance_report_pointer,
        )
        return self.activate_prepared_candidate(
            candidate,
            candidate.candidate_hash,
        )

    def prepare_candidate(
        self,
        receipt: RunReceipt,
        *,
        render: Callable[[Path], None],
        verify: Callable[[Path, dict[str, str]], bool],
        ledger_rows: tuple[dict[str, Any], ...],
        pointer_payloads: dict[Path, bytes],
        advance_report_pointer: bool = True,
    ) -> PreparedReportCandidate:
        controller = FormalRunController.resume(self.evidence_store, receipt.run_id)
        if controller.receipt.state not in {
            FormalRunState.ANALYZING,
            FormalRunState.FAILED_RETRYABLE,
        }:
            raise ActivationError(
                "candidate preparation requires ANALYZING or FAILED_RETRYABLE, "
                f"got {controller.receipt.state.value}"
            )
        staging = self.report_root / ".staging" / receipt.run_id
        try:
            controller.transition(FormalRunState.RENDERING)
            if staging.exists():
                shutil.rmtree(staging)
            self._inject("render")
            render(staging)
            artifact_hashes = hash_artifact_tree(staging)
            if not artifact_hashes:
                raise ActivationError("render produced no artifacts")
            controller.record_artifact_hashes(artifact_hashes)

            controller.transition(FormalRunState.VERIFYING)
            self._inject("verify")
            if verify(staging, artifact_hashes) is not True:
                raise ActivationError("verify rejected staged artifacts")

            pointer_records = self._pointer_records(pointer_payloads)
            ledger_rows_hash = hash_ledger_rows(ledger_rows)
            narrative_hash = _candidate_narrative_hash(staging)
            candidate_core = {
                "run_id": receipt.run_id,
                "receipt_hash": formal_receipt_hash(controller.receipt),
                "artifact_hashes": dict(sorted(artifact_hashes.items())),
                "ledger_rows_hash": ledger_rows_hash,
                "narrative_hash": narrative_hash,
                "pointer_hashes": {
                    item["relative_path"]: item["payload_hash"]
                    for item in pointer_records
                },
                "advance_report_pointer": advance_report_pointer,
            }
            candidate_hash = _hash(candidate_core)
            bundle = {
                **candidate_core,
                "candidate_hash": candidate_hash,
                "ledger_rows": list(ledger_rows),
                "pointer_payloads": pointer_records,
            }
            self.evidence_store.save_report_candidate_bundle(receipt.run_id, bundle)
            awaiting = controller.transition(
                FormalRunState.AWAITING_HUMAN_ACCEPTANCE
            )
            return PreparedReportCandidate(
                run_id=receipt.run_id,
                candidate_root=staging,
                artifact_hashes=artifact_hashes,
                candidate_hash=candidate_hash,
                ledger_rows_hash=ledger_rows_hash,
                narrative_hash=narrative_hash,
                receipt=awaiting,
            )
        except Exception as exc:
            self._mark_retryable(controller)
            if isinstance(exc, ActivationError):
                raise
            raise ActivationError(str(exc)) from exc

    def load_prepared_candidate(self, run_id: str) -> PreparedReportCandidate:
        bundle = self.evidence_store.report_candidate_bundle(run_id)
        receipt = self.evidence_store.latest_run_receipt(run_id)
        return PreparedReportCandidate(
            run_id=run_id,
            candidate_root=self.report_root / ".staging" / run_id,
            artifact_hashes=dict(bundle.get("artifact_hashes") or {}),
            candidate_hash=str(bundle.get("candidate_hash") or ""),
            ledger_rows_hash=str(bundle.get("ledger_rows_hash") or ""),
            narrative_hash=str(bundle.get("narrative_hash") or ""),
            receipt=receipt,
        )

    def activate_prepared_candidate(
        self,
        candidate: PreparedReportCandidate,
        expected_candidate_hash: str,
    ) -> RunReceipt:
        controller = FormalRunController.resume(
            self.evidence_store,
            candidate.run_id,
        )
        if controller.receipt.state is not FormalRunState.AWAITING_HUMAN_ACCEPTANCE:
            raise ActivationError("candidate is not awaiting human acceptance")
        bundle = self.evidence_store.report_candidate_bundle(candidate.run_id)
        self._validate_candidate_bundle(
            candidate,
            bundle,
            expected_candidate_hash,
        )
        ledger_rows = tuple(bundle["ledger_rows"])
        pointer_payloads = self._decode_pointer_records(
            bundle["pointer_payloads"]
        )
        advance_report_pointer = bool(bundle["advance_report_pointer"])
        artifact_hashes = dict(bundle["artifact_hashes"])
        try:
            controller.transition(FormalRunState.COMMITTING)
            receipt_hash = formal_receipt_hash(controller.receipt)
            expected_pending_hash = str(bundle["ledger_rows_hash"])
            self._inject("ledger_prepare")
            final_state = (
                FormalRunState.REPORT_GENERATED
                if advance_report_pointer
                else FormalRunState.ANALYSIS_COMPLETE_NO_RECOMMENDATIONS
            )
            self.ledger.register_formal_receipt(
                controller.receipt,
                receipt_hash,
                final_state,
            )
            pending_id = self.ledger.prepare_formal_run(
                candidate.run_id,
                receipt_hash,
                ledger_rows,
            )
            if self.ledger.pending_hash(pending_id) != expected_pending_hash:
                raise ActivationError("pending hash mismatch")
            activation_id = (
                "activation-"
                + _hash(
                    {
                        "run_id": candidate.run_id,
                        "receipt_hash": receipt_hash,
                        "pending_id": pending_id,
                    }
                )
            )

            self._inject("local_marker")
            _atomic_write(
                self.report_root
                / ".activation"
                / f"{candidate.run_id}.pending.json",
                _json_bytes(
                    {
                        "run_id": candidate.run_id,
                        "activation_id": activation_id,
                        "artifact_hashes": artifact_hashes,
                        "pending_id": pending_id,
                    }
                ),
            )

            self._inject("ledger_activate")
            self.ledger.activate_formal_run(
                candidate.run_id,
                pending_id,
                activation_id,
            )
            if not self.ledger.verify_formal_run_active(
                candidate.run_id,
                activation_id,
                receipt_hash,
                expected_pending_hash,
            ):
                raise ActivationError("ledger activation strong readback failed")

            immutable_root = self.report_root / ".formal-runs" / candidate.run_id
            _preserve_immutable_artifacts(
                candidate.candidate_root,
                immutable_root,
                artifact_hashes,
            )
            if advance_report_pointer:
                self._inject("pointer")
                activated_payloads = {
                    self.report_root / relative_path: (
                        immutable_root / relative_path
                    ).read_bytes()
                    for relative_path in artifact_hashes
                }
                for pointer_path, pointer_payload in pointer_payloads.items():
                    existing_payload = activated_payloads.get(pointer_path)
                    if (
                        existing_payload is not None
                        and existing_payload != pointer_payload
                    ):
                        raise ActivationError(
                            "pointer payload conflicts with report artifact: "
                            f"{pointer_path}"
                        )
                    activated_payloads[pointer_path] = pointer_payload
                _write_pointer_batch(activated_payloads)

            completed = controller.commit_activation(
                activation_id,
                no_recommendations=not advance_report_pointer,
            )
            _atomic_write(
                self.report_root
                / ".activation"
                / f"{candidate.run_id}.active.json",
                _json_bytes(
                    {
                        "run_id": candidate.run_id,
                        "activation_id": activation_id,
                    }
                ),
            )
            return completed
        except Exception as exc:
            self._mark_retryable(controller)
            if isinstance(exc, ActivationError):
                raise
            raise ActivationError(str(exc)) from exc

    def _validate_candidate_bundle(
        self,
        candidate: PreparedReportCandidate,
        bundle: dict[str, Any],
        expected_candidate_hash: str,
    ) -> None:
        stored_hash = bundle.get("candidate_hash")
        expected_root = self.report_root / ".staging" / candidate.run_id
        if candidate.candidate_root != expected_root:
            raise ActivationError("candidate root mismatch")
        if (
            expected_candidate_hash != stored_hash
            or candidate.candidate_hash != stored_hash
        ):
            raise ActivationError("candidate hash mismatch")
        if (
            candidate.artifact_hashes != bundle.get("artifact_hashes")
            or candidate.ledger_rows_hash != bundle.get("ledger_rows_hash")
            or candidate.narrative_hash != bundle.get("narrative_hash")
        ):
            raise ActivationError("candidate metadata mismatch")
        current_receipt = self.evidence_store.latest_run_receipt(candidate.run_id)
        if formal_receipt_hash(current_receipt) != bundle.get("receipt_hash"):
            raise ActivationError("candidate receipt hash mismatch")
        if hash_artifact_tree(candidate.candidate_root) != bundle.get(
            "artifact_hashes"
        ):
            raise ActivationError("candidate artifact hash mismatch")
        if hash_ledger_rows(tuple(bundle.get("ledger_rows") or ())) != bundle.get(
            "ledger_rows_hash"
        ):
            raise ActivationError("candidate ledger rows hash mismatch")
        if _candidate_narrative_hash(candidate.candidate_root) != bundle.get(
            "narrative_hash"
        ):
            raise ActivationError("candidate narrative hash mismatch")
        pointer_hashes = {
            item["relative_path"]: hashlib.sha256(
                base64.b64decode(item["payload_base64"], validate=True)
            ).hexdigest()
            for item in bundle.get("pointer_payloads") or []
        }
        candidate_core = {
            "run_id": candidate.run_id,
            "receipt_hash": bundle.get("receipt_hash"),
            "artifact_hashes": bundle.get("artifact_hashes"),
            "ledger_rows_hash": bundle.get("ledger_rows_hash"),
            "narrative_hash": bundle.get("narrative_hash"),
            "pointer_hashes": pointer_hashes,
            "advance_report_pointer": bundle.get("advance_report_pointer"),
        }
        if _hash(candidate_core) != stored_hash:
            raise ActivationError("candidate hash mismatch")

    def _pointer_records(
        self,
        pointer_payloads: dict[Path, bytes],
    ) -> list[dict[str, str]]:
        records: list[dict[str, str]] = []
        for path, payload in sorted(
            pointer_payloads.items(), key=lambda item: str(item[0])
        ):
            try:
                relative = Path(path).relative_to(self.report_root)
            except ValueError as exc:
                raise ActivationError(
                    "pointer path must remain within the report root"
                ) from exc
            records.append(
                {
                    "relative_path": relative.as_posix(),
                    "payload_base64": base64.b64encode(payload).decode("ascii"),
                    "payload_hash": hashlib.sha256(payload).hexdigest(),
                }
            )
        return records

    def _decode_pointer_records(
        self,
        records: list[dict[str, str]],
    ) -> dict[Path, bytes]:
        payloads: dict[Path, bytes] = {}
        for item in records:
            relative = Path(item["relative_path"])
            if relative.is_absolute() or ".." in relative.parts:
                raise ActivationError("candidate pointer path is unsafe")
            payloads[self.report_root / relative] = base64.b64decode(
                item["payload_base64"],
                validate=True,
            )
        return payloads

    @staticmethod
    def _mark_retryable(controller: FormalRunController) -> None:
        current = controller.receipt.state
        if (
            current != FormalRunState.FAILED_RETRYABLE
            and FormalRunState.FAILED_RETRYABLE
            in ALLOWED_TRANSITIONS.get(current, set())
        ):
            controller.transition(FormalRunState.FAILED_RETRYABLE)

    def _inject(self, point: str) -> None:
        if self.failure_point == point:
            raise ActivationError(f"injected activation failure at {point}")


def activation_markers_agree(receipt: RunReceipt, ledger: FormalLedger) -> bool:
    return (
        receipt.local_activation_id is not None
        and receipt.local_activation_id == receipt.ledger_activation_id
        and ledger.is_formal_run_active(receipt.run_id, receipt.local_activation_id)
    )


def formal_receipt_hash(receipt: RunReceipt) -> str:
    return _hash(
        {
            "run_id": receipt.run_id,
            "target_date": receipt.target_date.isoformat(),
            "report_cutoff": receipt.report_cutoff.isoformat(),
            "acquisition_contract_version": receipt.acquisition_contract_version,
            "screening_version": receipt.screening_version,
            "group_version_ids": receipt.group_version_ids,
            "input_set_id": receipt.input_set_id,
            "candidate_set_id": receipt.candidate_set_id,
            "evidence_hashes": receipt.evidence_hashes,
            "artifact_hashes": receipt.artifact_hashes,
        }
    )


def hash_ledger_rows(rows: tuple[dict[str, Any], ...]) -> str:
    return _hash([_canonical_json(row) for row in rows])


def hash_artifact_tree(root: Path) -> dict[str, str]:
    if not root.is_dir():
        return {}
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _write_pointer_batch(pointer_payloads: dict[Path, bytes]) -> None:
    originals = {
        Path(path): (Path(path).is_file(), Path(path).read_bytes() if Path(path).is_file() else b"")
        for path in pointer_payloads
    }
    try:
        for path, payload in pointer_payloads.items():
            _atomic_write(Path(path), payload)
    except Exception:
        for path, (existed, payload) in originals.items():
            if existed:
                _atomic_write(path, payload)
            elif path.exists():
                path.unlink()
        raise


def _preserve_immutable_artifacts(
    staging: Path,
    immutable_root: Path,
    expected_hashes: dict[str, str],
) -> None:
    if immutable_root.exists():
        if hash_artifact_tree(immutable_root) != expected_hashes:
            raise ActivationError("immutable formal artifact hash mismatch")
        return
    immutable_root.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copytree(staging, immutable_root)
    except Exception:
        if immutable_root.exists():
            shutil.rmtree(immutable_root)
        raise
    if hash_artifact_tree(immutable_root) != expected_hashes:
        shutil.rmtree(immutable_root)
        raise ActivationError("immutable formal artifact copy hash mismatch")


def _candidate_narrative_hash(candidate_root: Path) -> str:
    latest_paths = (
        candidate_root / "data" / "latest.json",
        candidate_root / "latest.json",
    )
    for path in latest_paths:
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ActivationError("candidate latest JSON is invalid") from exc
        if not isinstance(payload, dict):
            raise ActivationError("candidate latest JSON must be an object")
        return _hash(payload.get("formal_narrative"))
    raise ActivationError("candidate latest JSON is missing")


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode(
        "utf-8"
    )


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
    "ActivationError",
    "FormalActivationCoordinator",
    "FormalLedger",
    "InMemoryFormalLedger",
    "PreparedReportCandidate",
    "activation_markers_agree",
    "formal_receipt_hash",
    "hash_artifact_tree",
    "hash_ledger_rows",
]
