from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from pydantic import BaseModel

from stock_analyzer.storage.formal_migration import (
    DeletionManifest,
    LegacyInventory,
    MigrationAudit,
    WarehouseAudit,
    audit_formal_warehouse,
    build_deletion_manifest,
    inventory_legacy_formal_store,
    migrate_legacy_formal_store,
)
from stock_analyzer.storage.formal_warehouse import FormalWarehouse


def run_formal_warehouse_inventory(
    source_root: Path,
    output: Path,
) -> LegacyInventory:
    inventory = inventory_legacy_formal_store(source_root)
    _write_model(output, inventory)
    return inventory


def run_formal_warehouse_migration(
    source_root: Path,
    warehouse_root: Path,
    migration_id: str,
    output: Path,
) -> MigrationAudit:
    warehouse = FormalWarehouse(warehouse_root)
    audit = migrate_legacy_formal_store(
        source_root,
        warehouse,
        migration_id=migration_id,
    )
    warehouse.save_migration_audit(
        migration_id,
        str(Path(source_root)),
        "validated" if audit.deletion_eligible else "blocked",
        audit.deletion_eligible,
        audit.model_dump(mode="json"),
    )
    _write_model(output, audit)
    return audit


def run_formal_warehouse_audit(
    warehouse_root: Path,
    output: Path,
    *,
    strict_hashes: bool,
) -> WarehouseAudit:
    audit = audit_formal_warehouse(
        FormalWarehouse(warehouse_root),
        strict_hashes=strict_hashes,
    )
    _write_model(output, audit)
    return audit


def run_formal_warehouse_deletion_manifest(
    source_root: Path,
    warehouse_root: Path,
    migration_id: str,
    output: Path,
) -> DeletionManifest:
    warehouse = FormalWarehouse(warehouse_root)
    audit = MigrationAudit.model_validate(
        warehouse.migration_audit_payload(migration_id)
    )
    manifest = build_deletion_manifest(source_root, audit)
    _write_model(output, manifest)
    return manifest


def _write_model(path: Path, model: BaseModel) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(
                model.model_dump(mode="json"),
                handle,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


__all__ = [
    "run_formal_warehouse_audit",
    "run_formal_warehouse_deletion_manifest",
    "run_formal_warehouse_inventory",
    "run_formal_warehouse_migration",
]
