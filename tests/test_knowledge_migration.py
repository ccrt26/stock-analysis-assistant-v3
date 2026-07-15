from datetime import date
from pathlib import Path

import yaml

from stock_analyzer.knowledge.capability import (
    CapabilityItem,
    CapabilitySnapshot,
    assess_entry_capability,
)
from stock_analyzer.knowledge.governance_audit import (
    audit_knowledge_governance,
    decide_migration_action,
)
from stock_analyzer.knowledge.governance_models import MigrationAction
from stock_analyzer.knowledge.registry import (
    load_knowledge_registry,
    load_legacy_migration,
)


LEGACY_PATH = Path("src/stock_analyzer/knowledge/strategy_v2_map.yaml")
MIGRATION_PATH = Path("src/stock_analyzer/knowledge/strategy_v2_migration.yaml")
REGISTRY_PATH = Path("src/stock_analyzer/knowledge/research_registry.yaml")


def complete_snapshot_for_registry():
    registry = load_knowledge_registry(REGISTRY_PATH)
    fields: dict[tuple[str, str], set[str]] = {}
    for entry in registry.entries:
        if entry.version_status != "current":
            continue
        for requirement in entry.data_requirements:
            fields.setdefault((requirement.kind, requirement.name), set()).update(
                requirement.required_fields
            )
    return CapabilitySnapshot(
        analysis_date=date(2026, 7, 14),
        items=tuple(
            CapabilityItem(
                kind=kind,
                name=name,
                fields=tuple(sorted(required_fields)),
                partition_count=1,
                row_count=1,
                formula_versions=("fixture-v1",) if kind == "derived" else (),
                quality_statuses=("complete",),
                as_of_supported=True,
                structurally_ready=True,
            )
            for (kind, name), required_fields in sorted(fields.items())
        ),
        snapshot_hash="migration-complete-capability-fixture",
    )


def legacy_ids() -> set[str]:
    payload = yaml.safe_load(LEGACY_PATH.read_text(encoding="utf-8"))
    return {row["knowledge_id"] for row in payload["entries"]}


def test_migration_ids_equal_all_legacy_ids_exactly_once():
    expected = legacy_ids()
    migration = load_legacy_migration(MIGRATION_PATH)
    actual = {row.legacy_knowledge_id for row in migration.entries}

    assert len(migration.entries) == len(expected) == 74
    assert actual == expected


def test_active_migration_actions_resolve_to_admitted_new_entries():
    registry = load_knowledge_registry(REGISTRY_PATH)
    migration = load_legacy_migration(MIGRATION_PATH)
    snapshot = complete_snapshot_for_registry()
    entries = {entry.knowledge_id: entry for entry in registry.entries}
    active_actions = {
        MigrationAction.RETAIN,
        MigrationAction.UPDATE,
        MigrationAction.REVALIDATE,
    }

    for record in migration.entries:
        if record.action not in active_actions:
            continue
        assert record.target_knowledge_ids
        for target_id in record.target_knowledge_ids:
            assert target_id in entries
            target = entries[target_id]
            assert target.version_status == "current"
            assert assess_entry_capability(target, snapshot).status.value == "complete"


def test_defer_and_retire_have_no_active_target_and_a_concrete_reason():
    migration = load_legacy_migration(MIGRATION_PATH)

    for record in migration.entries:
        if record.action not in {MigrationAction.DEFER, MigrationAction.RETIRE}:
            continue
        assert record.target_knowledge_ids == ()
        assert len("".join(record.reason.split())) >= 20


def test_no_migration_action_requests_a_new_data_source():
    serialized = MIGRATION_PATH.read_text(encoding="utf-8")

    assert "add_data_source" not in serialized
    assert "future_enhancement" not in serialized


def test_legacy_data_exists_does_not_determine_the_new_action():
    old_rows = (
        {"knowledge_id": "same-old-id", "data_exists": True},
        {"knowledge_id": "same-old-id", "data_exists": False},
    )

    actions = {
        decide_migration_action(
            source_verified=True,
            current_a_share_applicability="method_only",
            data_gate="complete",
            local_validation_required=True,
            target_knowledge_ids=("new-id",),
            same_identity=False,
        )
        for _old_row in old_rows
    }

    assert actions == {MigrationAction.REVALIDATE}


def test_real_migration_passes_governance_cross_reference_audit():
    registry = load_knowledge_registry(REGISTRY_PATH)
    migration = load_legacy_migration(MIGRATION_PATH)

    report = audit_knowledge_governance(
        registry,
        migration,
        legacy_ids(),
        complete_snapshot_for_registry(),
    )

    assert report.passed is True, report.errors
    assert report.legacy_entry_count == 74
    assert report.unmapped_legacy_entry_count == 0
