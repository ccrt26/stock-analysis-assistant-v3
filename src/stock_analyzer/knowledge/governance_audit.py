from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
from pathlib import Path
from typing import Sequence

from pydantic import BaseModel, ConfigDict, Field
import yaml

from .capability import (
    CapabilitySnapshot,
    assess_entry_capability,
    inspect_warehouse_capabilities,
)
from .governance_models import (
    CapabilityStatus,
    KnowledgeRegistry,
    LegacyMigrationRegistry,
)
from .registry import load_knowledge_registry, load_legacy_migration


class GovernanceAuditReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    analysis_date: date
    registry_hash: str
    capability_snapshot_hash: str
    source_count: int = Field(ge=0)
    active_entry_count: int = Field(ge=0)
    blocked_active_entry_count: int = Field(ge=0)
    legacy_entry_count: int = Field(ge=0)
    unmapped_legacy_entry_count: int = Field(ge=0)
    errors: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return (
            self.blocked_active_entry_count == 0
            and self.unmapped_legacy_entry_count == 0
            and not self.errors
        )

    @property
    def audit_hash(self) -> str:
        canonical = json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()


def audit_knowledge_governance(
    registry: KnowledgeRegistry,
    migration: LegacyMigrationRegistry,
    legacy_ids: set[str],
    capabilities: CapabilitySnapshot,
) -> GovernanceAuditReport:
    errors: list[str] = []
    active_entries = sorted(
        (
            entry
            for entry in registry.entries
            if entry.version_status == "current"
        ),
        key=lambda entry: entry.knowledge_id,
    )
    blocked = []
    for entry in active_entries:
        assessment = assess_entry_capability(entry, capabilities)
        if assessment.status is not CapabilityStatus.COMPLETE:
            blocked.append(entry.knowledge_id)
            missing = ", ".join(assessment.missing_requirements) or "not ready"
            errors.append(f"blocked active entry {entry.knowledge_id}: {missing}")

    migration_ids = [record.legacy_knowledge_id for record in migration.entries]
    duplicate_migration_ids = sorted(
        {
            knowledge_id
            for knowledge_id in migration_ids
            if migration_ids.count(knowledge_id) > 1
        }
    )
    for knowledge_id in duplicate_migration_ids:
        errors.append(f"duplicate legacy migration ID: {knowledge_id}")

    migration_id_set = set(migration_ids)
    unmapped = sorted(legacy_ids - migration_id_set)
    unexpected = sorted(migration_id_set - legacy_ids)
    if unmapped:
        errors.append("unmapped legacy IDs: " + ", ".join(unmapped))
    if unexpected:
        errors.append("unknown legacy migration IDs: " + ", ".join(unexpected))

    return GovernanceAuditReport(
        analysis_date=capabilities.analysis_date,
        registry_hash=registry.registry_hash,
        capability_snapshot_hash=capabilities.snapshot_hash,
        source_count=len(registry.sources),
        active_entry_count=len(active_entries),
        blocked_active_entry_count=len(blocked),
        legacy_entry_count=len(legacy_ids),
        unmapped_legacy_entry_count=len(unmapped),
        errors=tuple(sorted(errors)),
    )


def _load_legacy_ids(path: Path) -> set[str]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("entries"), list):
        raise ValueError("legacy map must contain an entries list")
    result: set[str] = set()
    for item in payload["entries"]:
        if not isinstance(item, dict) or not isinstance(item.get("knowledge_id"), str):
            raise ValueError("legacy map entry requires knowledge_id")
        knowledge_id = item["knowledge_id"]
        if knowledge_id in result:
            raise ValueError(f"duplicate legacy knowledge ID: {knowledge_id}")
        result.add(knowledge_id)
    return result


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit V3 knowledge governance")
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--migration", type=Path, required=True)
    parser.add_argument("--legacy-map", type=Path, required=True)
    parser.add_argument("--warehouse-root", type=Path, required=True)
    parser.add_argument("--analysis-date", type=date.fromisoformat, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    registry = load_knowledge_registry(args.registry)
    migration = load_legacy_migration(args.migration)
    legacy_ids = _load_legacy_ids(args.legacy_map)
    capabilities = inspect_warehouse_capabilities(
        args.warehouse_root, args.analysis_date
    )
    report = audit_knowledge_governance(
        registry,
        migration,
        legacy_ids,
        capabilities,
    )
    output = report.model_dump(mode="json")
    output["passed"] = report.passed
    output["audit_hash"] = report.audit_hash
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["GovernanceAuditReport", "audit_knowledge_governance", "main"]
