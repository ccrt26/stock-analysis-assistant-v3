from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from stock_analyzer.data.readiness import (
    AcquisitionGroupId,
    AcquisitionPayload,
    GroupValidation,
    RouteKind,
)


_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]+$")


class GroupVersionManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    version_id: str
    group_id: AcquisitionGroupId
    trade_date: date
    route_id: str
    route_kind: RouteKind
    content_hash: str
    complete: bool
    created_at: datetime


class ReconciliationTask(BaseModel):
    model_config = ConfigDict(frozen=True)

    task_id: str
    group_id: AcquisitionGroupId
    trade_date: date
    backup_version_id: str
    status: str
    primary_version_id: str | None = None


class FrozenReportReference(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    input_set_id: str
    group_version_ids: tuple[str, ...]
    artifact_hashes: dict[str, str]


class _Checkpoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    trade_date: date
    contract_version: str
    stage: str
    object_id: str


class LocalEvidenceStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def version_path(self, version_id: str) -> Path:
        _validate_id(version_id)
        return self.root / "group_versions" / f"{version_id}.json"

    def save_group_version(
        self,
        payload: AcquisitionPayload,
        validation: GroupValidation,
    ) -> GroupVersionManifest:
        if not validation.complete:
            raise ValueError("cannot persist an incomplete acquisition group version")
        version_id = (
            f"{payload.group_id.value}-{payload.trade_date.isoformat()}-"
            f"{payload.content_hash}"
        )
        manifest = GroupVersionManifest(
            version_id=version_id,
            group_id=payload.group_id,
            trade_date=payload.trade_date,
            route_id=payload.route_id,
            route_kind=payload.route_kind,
            content_hash=payload.content_hash,
            complete=True,
            created_at=payload.fetched_at,
        )
        serialized = _json_bytes(
            {
                "manifest": manifest.model_dump(mode="json"),
                "payload": payload.model_dump(mode="json"),
            }
        )
        _write_immutable(self.version_path(version_id), serialized)
        return manifest

    def read_group_version(
        self,
        version_id: str,
        *,
        report_cutoff: datetime | None = None,
    ) -> AcquisitionPayload | None:
        envelope = _read_json(self.version_path(version_id))
        manifest = GroupVersionManifest.model_validate(envelope["manifest"])
        payload = AcquisitionPayload.model_validate(envelope["payload"])
        if manifest.version_id != version_id or manifest.content_hash != payload.content_hash:
            raise ValueError("group version content hash mismatch")
        if report_cutoff is not None and any(
            published_at > report_cutoff
            for published_at in payload.publication_times.values()
        ):
            return None
        return payload

    def group_version_manifest(self, version_id: str) -> GroupVersionManifest:
        envelope = _read_json(self.version_path(version_id))
        return GroupVersionManifest.model_validate(envelope["manifest"])

    def set_canonical(
        self,
        group_id: AcquisitionGroupId,
        trade_date: date,
        version_id: str,
    ) -> None:
        manifest = self.group_version_manifest(version_id)
        if manifest.group_id != group_id or manifest.trade_date != trade_date:
            raise ValueError("canonical pointer group/date mismatch")
        _atomic_write(
            self._canonical_path(group_id, trade_date),
            _json_bytes({"version_id": version_id}),
        )

    def canonical_manifest(
        self,
        group_id: AcquisitionGroupId,
        trade_date: date,
    ) -> GroupVersionManifest | None:
        path = self._canonical_path(group_id, trade_date)
        if not path.is_file():
            return None
        version_id = _read_json(path)["version_id"]
        manifest = self.group_version_manifest(version_id)
        if manifest.group_id != group_id or manifest.trade_date != trade_date:
            raise ValueError("canonical pointer content mismatch")
        return manifest

    def load_prior_sessions(
        self,
        group_id: AcquisitionGroupId,
        before_date: date,
        limit: int,
    ) -> list[AcquisitionPayload]:
        if limit < 0:
            raise ValueError("limit cannot be negative")
        directory = self.root / "canonical" / group_id.value
        candidates: list[tuple[date, str]] = []
        if directory.is_dir():
            for path in directory.glob("*.json"):
                try:
                    covered_date = date.fromisoformat(path.stem)
                except ValueError:
                    continue
                if covered_date < before_date:
                    candidates.append((covered_date, _read_json(path)["version_id"]))
        selected = sorted(candidates)[-limit:] if limit else []
        return [
            payload
            for _, version_id in selected
            if (payload := self.read_group_version(version_id)) is not None
        ]

    def save_checkpoint(
        self,
        run_id: str,
        trade_date: date,
        contract_version: str,
        stage: str,
        object_id: str,
    ) -> None:
        checkpoint = _Checkpoint(
            run_id=run_id,
            trade_date=trade_date,
            contract_version=contract_version,
            stage=stage,
            object_id=object_id,
        )
        _atomic_write(
            self._checkpoint_path(run_id, stage),
            _json_bytes(checkpoint.model_dump(mode="json")),
        )

    def load_checkpoint(
        self,
        run_id: str,
        trade_date: date,
        contract_version: str,
        stage: str,
    ) -> str | None:
        path = self._checkpoint_path(run_id, stage)
        if not path.is_file():
            return None
        checkpoint = _Checkpoint.model_validate(_read_json(path))
        if (
            checkpoint.run_id != run_id
            or checkpoint.trade_date != trade_date
            or checkpoint.contract_version != contract_version
            or checkpoint.stage != stage
        ):
            return None
        return checkpoint.object_id

    def create_reconciliation_task(
        self,
        backup_manifest: GroupVersionManifest,
    ) -> ReconciliationTask:
        if backup_manifest.route_kind != RouteKind.BACKUP:
            raise ValueError("reconciliation requires a backup group version")
        task_id = hashlib.sha256(
            f"reconcile:{backup_manifest.version_id}".encode("utf-8")
        ).hexdigest()
        task = ReconciliationTask(
            task_id=task_id,
            group_id=backup_manifest.group_id,
            trade_date=backup_manifest.trade_date,
            backup_version_id=backup_manifest.version_id,
            status="pending",
        )
        _write_immutable(
            self._reconciliation_path(task_id),
            _json_bytes(task.model_dump(mode="json")),
        )
        return task

    def reconciliation_task(self, task_id: str) -> ReconciliationTask:
        return ReconciliationTask.model_validate(
            _read_json(self._reconciliation_path(task_id))
        )

    def reconcile_primary(
        self,
        task_id: str,
        primary_payload: AcquisitionPayload,
        validation: GroupValidation,
    ) -> GroupVersionManifest:
        task = self.reconciliation_task(task_id)
        if task.status == "completed":
            if task.primary_version_id is None:
                raise ValueError("completed reconciliation lacks primary version")
            return self.group_version_manifest(task.primary_version_id)
        if primary_payload.route_kind != RouteKind.PRIMARY:
            raise ValueError("reconciliation payload must use the primary route")
        if (
            primary_payload.group_id != task.group_id
            or primary_payload.trade_date != task.trade_date
        ):
            raise ValueError("reconciliation primary group/date mismatch")
        manifest = self.save_group_version(primary_payload, validation)
        self.set_canonical(task.group_id, task.trade_date, manifest.version_id)
        completed = task.model_copy(
            update={
                "status": "completed",
                "primary_version_id": manifest.version_id,
            }
        )
        _atomic_write(
            self._reconciliation_path(task_id),
            _json_bytes(completed.model_dump(mode="json")),
        )
        return manifest

    def save_frozen_report_reference(
        self,
        reference: FrozenReportReference,
    ) -> Path:
        path = self._frozen_report_path(reference.run_id)
        _write_immutable(path, _json_bytes(reference.model_dump(mode="json")))
        return path

    def frozen_report_reference(self, run_id: str) -> FrozenReportReference:
        return FrozenReportReference.model_validate(
            _read_json(self._frozen_report_path(run_id))
        )

    def save_run_receipt(self, receipt) -> Path:
        from stock_analyzer.ops.formal_run import RunReceipt

        validated = RunReceipt.model_validate(receipt)
        path = self._run_receipt_revision_path(validated.run_id, validated.revision)
        _write_immutable(path, _json_bytes(validated.model_dump(mode="json")))
        _atomic_write(
            self._run_receipt_latest_path(validated.run_id),
            _json_bytes({"revision": validated.revision}),
        )
        return path

    def latest_run_receipt(self, run_id: str):
        from stock_analyzer.ops.formal_run import RunReceipt

        latest = _read_json(self._run_receipt_latest_path(run_id))
        return RunReceipt.model_validate(
            _read_json(self._run_receipt_revision_path(run_id, latest["revision"]))
        )

    def save_candidate_set(self, candidate_set) -> Path:
        from stock_analyzer.ops.formal_run import CandidateSet

        validated = CandidateSet.model_validate(candidate_set)
        path = self._candidate_set_path(validated.candidate_set_id)
        _write_immutable(path, _json_bytes(validated.model_dump(mode="json")))
        return path

    def candidate_set(self, candidate_set_id: str):
        from stock_analyzer.ops.formal_run import CandidateSet

        return CandidateSet.model_validate(
            _read_json(self._candidate_set_path(candidate_set_id))
        )

    def save_report_candidate_bundle(
        self,
        run_id: str,
        bundle: dict[str, Any],
    ) -> Path:
        path = self._report_candidate_path(run_id)
        _write_immutable(path, _json_bytes(bundle))
        return path

    def report_candidate_bundle(self, run_id: str) -> dict[str, Any]:
        value = _read_json(self._report_candidate_path(run_id))
        if not isinstance(value, dict) or value.get("run_id") != run_id:
            raise ValueError("formal report candidate bundle mismatch")
        return value

    def _canonical_path(
        self,
        group_id: AcquisitionGroupId,
        trade_date: date,
    ) -> Path:
        return self.root / "canonical" / group_id.value / f"{trade_date.isoformat()}.json"

    def _checkpoint_path(self, run_id: str, stage: str) -> Path:
        _validate_id(run_id)
        _validate_id(stage)
        return self.root / "checkpoints" / run_id / f"{stage}.json"

    def _reconciliation_path(self, task_id: str) -> Path:
        _validate_id(task_id)
        return self.root / "reconciliation" / f"{task_id}.json"

    def _frozen_report_path(self, run_id: str) -> Path:
        _validate_id(run_id)
        return self.root / "frozen_reports" / f"{run_id}.json"

    def _run_receipt_revision_path(self, run_id: str, revision: int) -> Path:
        _validate_id(run_id)
        return self.root / "run_receipts" / run_id / f"{revision:06d}.json"

    def _run_receipt_latest_path(self, run_id: str) -> Path:
        _validate_id(run_id)
        return self.root / "run_receipts" / run_id / "latest.json"

    def _candidate_set_path(self, candidate_set_id: str) -> Path:
        _validate_id(candidate_set_id)
        return self.root / "candidate_sets" / f"{candidate_set_id}.json"

    def _report_candidate_path(self, run_id: str) -> Path:
        _validate_id(run_id)
        return self.root / "report_candidates" / f"{run_id}.json"


def _validate_id(value: str) -> None:
    if not _SAFE_ID.fullmatch(value):
        raise ValueError("identifier contains unsafe path characters")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _write_immutable(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        if path.read_bytes() != payload:
            raise ValueError(f"immutable evidence already exists with different bytes: {path.name}")


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
    "FrozenReportReference",
    "GroupVersionManifest",
    "LocalEvidenceStore",
    "ReconciliationTask",
]
