from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from stock_analyzer.data.capability_store import (
    CapabilityBundle,
    WarehouseCapabilityStore,
)
from stock_analyzer.data.readiness import AcquisitionGroupId, AcquisitionPayload, GroupValidation
from stock_analyzer.ops.formal_run import CandidateSet, RunReceipt
from stock_analyzer.storage.evidence_store import (
    FrozenReportReference,
    GroupVersionManifest,
    ReconciliationTask,
)
from stock_analyzer.storage.formal_warehouse import FormalWarehouse


class LegacyInventoryItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    relative_path: str
    source_sha256: str
    size: int
    object_kind: str
    object_id: str


class LegacyInventory(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_root: str
    items: tuple[LegacyInventoryItem, ...]
    unknown_paths: tuple[str, ...]


class MigrationItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_path: str
    source_sha256: str
    object_kind: str
    object_id: str
    status: Literal["migrated", "already_present", "failed", "unknown"]
    target_ids: tuple[str, ...] = ()
    checks: dict[str, bool] = Field(default_factory=dict)
    error: str | None = None


class WarehouseAudit(BaseModel):
    model_config = ConfigDict(frozen=True)

    complete: bool
    version_count: int
    file_count: int
    row_count: int
    receipt_count: int
    errors: tuple[str, ...] = ()


class MigrationAudit(BaseModel):
    model_config = ConfigDict(frozen=True)

    migration_id: str
    source_root: str
    inventory: LegacyInventory
    items: tuple[MigrationItem, ...]
    warehouse_audit: WarehouseAudit
    deletion_eligible: bool
    completed_at: datetime


class DeletionEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: str
    sha256: str
    size: int
    object_kind: str
    object_id: str


class DeletionManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    migration_id: str
    source_root: str
    files: tuple[DeletionEntry, ...]
    total_bytes: int
    generated_at: datetime


_KIND_ORDER = {
    "group_version": 10,
    "capability_version": 20,
    "capability_latest": 21,
    "canonical_pointer": 30,
    "run_receipt": 40,
    "run_receipt_latest": 41,
    "candidate_set": 50,
    "checkpoint": 60,
    "reconciliation": 70,
    "frozen_report": 80,
    "report_candidate": 90,
    "unknown": 999,
}


def inventory_legacy_formal_store(source_root: Path) -> LegacyInventory:
    root = Path(source_root)
    items: list[LegacyInventoryItem] = []
    unknown: list[str] = []
    for path in sorted(root.rglob("*.json")):
        relative = path.relative_to(root).as_posix()
        kind, object_id = _classify(relative)
        if kind == "unknown":
            unknown.append(relative)
        items.append(
            LegacyInventoryItem(
                relative_path=relative,
                source_sha256=_sha256(path),
                size=path.stat().st_size,
                object_kind=kind,
                object_id=object_id,
            )
        )
    items.sort(key=lambda item: (_KIND_ORDER[item.object_kind], item.relative_path))
    return LegacyInventory(
        source_root=str(root),
        items=tuple(items),
        unknown_paths=tuple(sorted(unknown)),
    )


def migrate_legacy_formal_store(
    source_root: Path,
    warehouse: FormalWarehouse,
    *,
    migration_id: str,
) -> MigrationAudit:
    root = Path(source_root)
    inventory = inventory_legacy_formal_store(root)
    migrated: list[MigrationItem] = []
    for item in inventory.items:
        path = root / item.relative_path
        if item.object_kind == "unknown":
            migrated.append(
                MigrationItem(
                    source_path=item.relative_path,
                    source_sha256=item.source_sha256,
                    object_kind=item.object_kind,
                    object_id=item.object_id,
                    status="unknown",
                    checks={"source_hash": True},
                )
            )
            continue
        try:
            if _sha256(path) != item.source_sha256:
                raise ValueError("source changed during migration")
            already_present, target_ids = _migrate_item(
                path,
                item,
                warehouse,
            )
            migrated.append(
                MigrationItem(
                    source_path=item.relative_path,
                    source_sha256=item.source_sha256,
                    object_kind=item.object_kind,
                    object_id=item.object_id,
                    status="already_present" if already_present else "migrated",
                    target_ids=target_ids,
                    checks={"source_hash": True, "semantic_equal": True},
                )
            )
        except Exception as exc:
            migrated.append(
                MigrationItem(
                    source_path=item.relative_path,
                    source_sha256=item.source_sha256,
                    object_kind=item.object_kind,
                    object_id=item.object_id,
                    status="failed",
                    checks={"source_hash": path.is_file() and _sha256(path) == item.source_sha256},
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
    warehouse_audit = audit_formal_warehouse(warehouse)
    eligible = warehouse_audit.complete and all(
        item.status in {"migrated", "already_present"} for item in migrated
    )
    return MigrationAudit(
        migration_id=migration_id,
        source_root=str(root),
        inventory=inventory,
        items=tuple(migrated),
        warehouse_audit=warehouse_audit,
        deletion_eligible=eligible,
        completed_at=datetime.now(timezone.utc),
    )


def audit_formal_warehouse(
    warehouse: FormalWarehouse,
    *,
    strict_hashes: bool = True,
) -> WarehouseAudit:
    errors: list[str] = []
    versions = warehouse.list_group_versions()
    file_count = 0
    row_count = 0
    known_versions = {manifest.version_id for manifest in versions}
    for manifest in versions:
        try:
            audit = warehouse.verify_group_version(
                manifest.version_id,
                strict_hashes=strict_hashes,
            )
            file_count += audit.file_count
            row_count += audit.row_count
        except Exception as exc:
            errors.append(f"version:{manifest.version_id}:{type(exc).__name__}:{exc}")
    receipts = warehouse.list_run_receipts()
    for receipt in receipts:
        missing = sorted(set(receipt.group_version_ids.values()) - known_versions)
        if missing:
            errors.append(f"receipt:{receipt.run_id}:{receipt.revision}:missing:{','.join(missing)}")
    with warehouse._connect(read_only=True) as connection:
        frozen_rows = connection.execute(
            "select run_id, payload from formal_frozen_reports"
        ).fetchall()
    for run_id, payload_json in frozen_rows:
        payload = FrozenReportReference.model_validate(_from_json(payload_json))
        missing = sorted(set(payload.group_version_ids) - known_versions)
        if missing:
            errors.append(f"frozen:{run_id}:missing:{','.join(missing)}")
    return WarehouseAudit(
        complete=not errors,
        version_count=len(versions),
        file_count=file_count,
        row_count=row_count,
        receipt_count=len(receipts),
        errors=tuple(errors),
    )


def build_deletion_manifest(
    source_root: Path,
    audit: MigrationAudit,
) -> DeletionManifest:
    root = Path(source_root)
    if not audit.deletion_eligible:
        raise ValueError("migration is not deletion eligible")
    if str(root) != audit.source_root:
        raise ValueError("deletion source root does not match migration")
    entries: list[DeletionEntry] = []
    for item in audit.inventory.items:
        path = root / item.relative_path
        if not path.is_file() or _sha256(path) != item.source_sha256:
            raise ValueError(f"source changed after migration: {item.relative_path}")
        entries.append(
            DeletionEntry(
                path=str(path),
                sha256=item.source_sha256,
                size=item.size,
                object_kind=item.object_kind,
                object_id=item.object_id,
            )
        )
    return DeletionManifest(
        migration_id=audit.migration_id,
        source_root=str(root),
        files=tuple(entries),
        total_bytes=sum(item.size for item in entries),
        generated_at=datetime.now(timezone.utc),
    )


def _migrate_item(
    path: Path,
    item: LegacyInventoryItem,
    warehouse: FormalWarehouse,
) -> tuple[bool, tuple[str, ...]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    kind = item.object_kind
    if kind == "group_version":
        manifest = GroupVersionManifest.model_validate(value["manifest"])
        payload = AcquisitionPayload.model_validate(value["payload"])
        already = _has_version(warehouse, manifest.version_id)
        stored = warehouse.save_group_version(payload, GroupValidation(complete=True))
        if stored != manifest or warehouse.read_group_version(stored.version_id) != payload:
            raise ValueError("group version semantic mismatch")
        return already, (stored.version_id,)
    if kind == "canonical_pointer":
        parts = Path(item.relative_path).parts
        group_id = AcquisitionGroupId(parts[1])
        target_date = date_from_stem(parts[-1])
        version_id = str(value["version_id"])
        current = warehouse.canonical_manifest(group_id, target_date)
        already = current is not None and current.version_id == version_id
        warehouse.set_canonical(group_id, target_date, version_id)
        return already, (version_id,)
    if kind in {"capability_version", "capability_latest"}:
        envelope = dict(value)
        bundle_hash = str(envelope.pop("bundle_hash"))
        bundle = CapabilityBundle.model_validate(envelope)
        already = _has_capability(warehouse, bundle_hash)
        WarehouseCapabilityStore(warehouse).save(bundle)
        stored_hash, _ = warehouse.latest_capability_bundle()
        if stored_hash != bundle_hash:
            raise ValueError("capability bundle hash mismatch")
        return already, (bundle_hash,)
    if kind == "run_receipt":
        receipt = RunReceipt.model_validate(value)
        already = _has_receipt(warehouse, receipt.run_id, receipt.revision)
        warehouse.save_run_receipt(receipt)
        if warehouse.run_receipt(receipt.run_id, receipt.revision) != receipt:
            raise ValueError("run receipt semantic mismatch")
        return already, (receipt.run_id, str(receipt.revision))
    if kind == "run_receipt_latest":
        run_id = Path(item.relative_path).parts[1]
        revision = int(value["revision"])
        latest = warehouse.latest_run_receipt(run_id)
        if latest.revision != revision:
            raise ValueError("run receipt latest pointer mismatch")
        return True, (run_id, str(revision))
    if kind == "candidate_set":
        candidate = CandidateSet.model_validate(value)
        already = _has_candidate(warehouse, candidate.candidate_set_id)
        warehouse.save_candidate_set(candidate)
        return already, (candidate.candidate_set_id,)
    if kind == "checkpoint":
        run_id = str(value["run_id"])
        trade_date = date_from_value(value["trade_date"])
        contract_version = str(value["contract_version"])
        stage = str(value["stage"])
        object_id = str(value["object_id"])
        already = (
            warehouse.load_checkpoint(
                run_id,
                trade_date,
                contract_version,
                stage,
            )
            == object_id
        )
        warehouse.save_checkpoint(
            run_id,
            trade_date,
            contract_version,
            stage,
            object_id,
        )
        return already, (run_id, stage)
    if kind == "reconciliation":
        task = ReconciliationTask.model_validate(value)
        already = _has_reconciliation(warehouse, task.task_id)
        warehouse.import_reconciliation_task(task)
        return already, (task.task_id,)
    if kind == "frozen_report":
        reference = FrozenReportReference.model_validate(value)
        already = _has_frozen(warehouse, reference.run_id)
        warehouse.save_frozen_report_reference(reference)
        return already, (reference.run_id,)
    if kind == "report_candidate":
        run_id = str(value["run_id"])
        already = _has_report_candidate(warehouse, run_id)
        warehouse.save_report_candidate_bundle(run_id, value)
        return already, (run_id,)
    raise ValueError(f"unsupported migration object kind: {kind}")


def _classify(relative: str) -> tuple[str, str]:
    parts = Path(relative).parts
    stem = Path(relative).stem
    if len(parts) == 2 and parts[0] == "group_versions":
        return "group_version", stem
    if len(parts) == 3 and parts[0] == "canonical":
        return "canonical_pointer", f"{parts[1]}:{stem}"
    if parts and parts[0] == "capabilities":
        if parts[-1] == "latest.json":
            return "capability_latest", "/".join(parts[1:-1])
        if "versions" in parts:
            return "capability_version", stem
    if len(parts) == 3 and parts[0] == "run_receipts":
        if parts[-1] == "latest.json":
            return "run_receipt_latest", parts[1]
        if stem.isdigit():
            return "run_receipt", f"{parts[1]}:{int(stem)}"
    mapping = {
        "candidate_sets": "candidate_set",
        "reconciliation": "reconciliation",
        "frozen_reports": "frozen_report",
        "report_candidates": "report_candidate",
    }
    if len(parts) == 2 and parts[0] in mapping:
        return mapping[parts[0]], stem
    if len(parts) == 3 and parts[0] == "checkpoints":
        return "checkpoint", f"{parts[1]}:{stem}"
    return "unknown", relative


def _has_version(warehouse: FormalWarehouse, version_id: str) -> bool:
    try:
        warehouse.group_version_manifest(version_id)
        return True
    except FileNotFoundError:
        return False


def _has_capability(warehouse: FormalWarehouse, bundle_hash: str) -> bool:
    with warehouse._connect(read_only=True) as connection:
        return connection.execute(
            "select 1 from formal_capability_bundles where bundle_hash = ?",
            [bundle_hash],
        ).fetchone() is not None


def _has_receipt(warehouse: FormalWarehouse, run_id: str, revision: int) -> bool:
    try:
        warehouse.run_receipt(run_id, revision)
        return True
    except FileNotFoundError:
        return False


def _has_candidate(warehouse: FormalWarehouse, candidate_set_id: str) -> bool:
    try:
        warehouse.candidate_set(candidate_set_id)
        return True
    except FileNotFoundError:
        return False


def _has_reconciliation(warehouse: FormalWarehouse, task_id: str) -> bool:
    try:
        warehouse.reconciliation_task(task_id)
        return True
    except FileNotFoundError:
        return False


def _has_frozen(warehouse: FormalWarehouse, run_id: str) -> bool:
    try:
        warehouse.frozen_report_reference(run_id)
        return True
    except FileNotFoundError:
        return False


def _has_report_candidate(warehouse: FormalWarehouse, run_id: str) -> bool:
    try:
        warehouse.report_candidate_bundle(run_id)
        return True
    except FileNotFoundError:
        return False


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _from_json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def date_from_stem(filename: str) -> Any:
    return date_from_value(Path(filename).stem)


def date_from_value(value: Any) -> Any:
    from datetime import date

    return value if isinstance(value, date) else date.fromisoformat(str(value))


__all__ = [
    "DeletionManifest",
    "LegacyInventory",
    "MigrationAudit",
    "WarehouseAudit",
    "audit_formal_warehouse",
    "build_deletion_manifest",
    "inventory_legacy_formal_store",
    "migrate_legacy_formal_store",
]
