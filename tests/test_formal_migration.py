import json
import hashlib
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from stock_analyzer.data.capability_store import CapabilityBundle, LocalCapabilityStore
from stock_analyzer.data.readiness import (
    AcquisitionGroupId,
    AcquisitionPayload,
    CapabilityEvidenceKind,
    FormalRunState,
    GroupValidation,
    RouteCapabilityEvidence,
    RouteKind,
)
from stock_analyzer.ops.formal_run import CandidateSet, RunReceipt
from stock_analyzer.storage.evidence_store import (
    FrozenReportReference,
    LocalEvidenceStore,
)
from stock_analyzer.storage.formal_migration import (
    audit_formal_warehouse,
    build_deletion_manifest,
    inventory_legacy_formal_store,
    migrate_legacy_formal_store,
)
from stock_analyzer.storage.formal_warehouse import FormalWarehouse


SHANGHAI = ZoneInfo("Asia/Shanghai")
TARGET = date(2026, 7, 10)
NOW = datetime(2026, 7, 10, 16, 0, tzinfo=SHANGHAI)
VALID = GroupValidation(complete=True)


def _payload() -> AcquisitionPayload:
    return AcquisitionPayload(
        group_id=AcquisitionGroupId.MARKET_DECISION,
        route_id="tushare.market_decision.v1",
        route_kind=RouteKind.PRIMARY,
        trade_date=TARGET,
        fetched_at=NOW,
        source_names=("tushare.daily",),
        records=(
            {
                "record_type": "equity_bar",
                "trade_date": TARGET,
                "ts_code": "600000.SH",
                "close": 10.5,
            },
        ),
        covered_dates=(TARGET,),
        coverage_codes=("600000.SH",),
        coverage_proven=True,
        field_coverage={"trade_date": True, "ts_code": True, "close": True},
        contract_version="formal-v2",
    )


def _legacy_tree(root):
    store = LocalEvidenceStore(root)
    manifest = store.save_group_version(_payload(), VALID)
    store.set_canonical(manifest.group_id, TARGET, manifest.version_id)
    candidate = CandidateSet(
        candidate_set_id="candidate-1",
        run_id="run-1",
        ordered_codes=("600000.SH",),
        active_focus_codes=(),
        screening_version="screen-v2",
        upstream_input_set_id="input-screen",
        content_hash="a" * 64,
    )
    store.save_candidate_set(candidate)
    receipt = RunReceipt(
        run_id="run-1",
        target_date=TARGET,
        report_cutoff=NOW,
        acquisition_contract_version="formal-v2",
        screening_version="screen-v2",
        state=FormalRunState.REPORT_GENERATED,
        group_version_ids={"market_decision": manifest.version_id},
        input_set_id="input-1",
        candidate_set_id=candidate.candidate_set_id,
        evidence_hashes={"evidence": "b" * 64},
        artifact_hashes={"index.html": "c" * 64},
    )
    store.save_run_receipt(receipt)
    store.save_checkpoint("run-1", TARGET, "formal-v2", "screen", manifest.version_id)
    store.save_frozen_report_reference(
        FrozenReportReference(
            run_id="run-1",
            input_set_id="input-1",
            group_version_ids=(manifest.version_id,),
            artifact_hashes={"index.html": "c" * 64},
        )
    )
    store.save_report_candidate_bundle("run-1", {"run_id": "run-1", "hash": "d" * 64})
    capability = RouteCapabilityEvidence(
        route_id="tushare.market_decision.v1",
        group_id=AcquisitionGroupId.MARKET_DECISION,
        contract_version="formal-v2",
        full_contract_tested=True,
        field_semantics_verified=True,
        full_universe_verified=True,
        post_close_verified=True,
        tested_at=NOW,
        evidence_kind=CapabilityEvidenceKind.LIVE,
        response_hash="e" * 64,
        tested_library_versions={"tushare": "1.4.19"},
    )
    capability_path = root / "capabilities/formal-v2/latest.json"
    LocalCapabilityStore(capability_path).save(
        CapabilityBundle(
            contract_version="formal-v2",
            generated_at=NOW,
            routes=(capability,),
        )
    )
    return manifest, receipt


def test_inventory_and_migration_preserve_complete_reference_graph(tmp_path):
    source = tmp_path / "formal_evidence"
    manifest, receipt = _legacy_tree(source)
    warehouse = FormalWarehouse(tmp_path / "warehouse")

    inventory = inventory_legacy_formal_store(source)
    audit = migrate_legacy_formal_store(
        source,
        warehouse,
        migration_id="migration-1",
    )

    assert inventory.unknown_paths == ()
    assert audit.deletion_eligible is True
    assert all(item.status in {"migrated", "already_present"} for item in audit.items)
    assert warehouse.read_group_version(manifest.version_id).content_hash == manifest.content_hash
    assert warehouse.canonical_manifest(manifest.group_id, TARGET) == manifest
    assert warehouse.latest_run_receipt(receipt.run_id) == receipt
    assert warehouse.candidate_set("candidate-1").run_id == "run-1"
    assert warehouse.frozen_report_reference("run-1").input_set_id == "input-1"
    assert warehouse.report_candidate_bundle("run-1")["hash"] == "d" * 64
    assert audit_formal_warehouse(warehouse).complete is True


def test_migration_is_idempotent_and_creates_no_duplicate_versions(tmp_path):
    source = tmp_path / "formal_evidence"
    _legacy_tree(source)
    warehouse = FormalWarehouse(tmp_path / "warehouse")

    first = migrate_legacy_formal_store(source, warehouse, migration_id="migration-1")
    second = migrate_legacy_formal_store(source, warehouse, migration_id="migration-1")

    assert first.deletion_eligible and second.deletion_eligible
    assert len(warehouse.list_group_versions()) == 1
    assert all(item.status == "already_present" for item in second.items)


def test_unknown_json_blocks_deletion_eligibility(tmp_path):
    source = tmp_path / "formal_evidence"
    _legacy_tree(source)
    (source / "unknown.json").write_text("{}", encoding="utf-8")

    audit = migrate_legacy_formal_store(
        source,
        FormalWarehouse(tmp_path / "warehouse"),
        migration_id="migration-1",
    )

    assert audit.deletion_eligible is False
    assert any(item.status == "unknown" for item in audit.items)
    with pytest.raises(ValueError, match="not deletion eligible"):
        build_deletion_manifest(source, audit)


def test_deletion_manifest_rehashes_sources_and_detects_change(tmp_path):
    source = tmp_path / "formal_evidence"
    _legacy_tree(source)
    audit = migrate_legacy_formal_store(
        source,
        FormalWarehouse(tmp_path / "warehouse"),
        migration_id="migration-1",
    )
    target = next(source.glob("group_versions/*.json"))
    target.write_text(json.dumps({"changed": True}), encoding="utf-8")

    with pytest.raises(ValueError, match="changed after migration"):
        build_deletion_manifest(source, audit)


def test_deletion_manifest_lists_only_legacy_store_files(tmp_path):
    source = tmp_path / "formal_evidence"
    _legacy_tree(source)
    warehouse = FormalWarehouse(tmp_path / "warehouse")
    audit = migrate_legacy_formal_store(source, warehouse, migration_id="migration-1")

    manifest = build_deletion_manifest(source, audit)

    assert manifest.files
    assert all(entry.path.endswith(".json") for entry in manifest.files)
    relative_parts = [Path(entry.path).relative_to(source).parts for entry in manifest.files]
    assert all(parts[0] != "reports" for parts in relative_parts)
    assert all(parts[:2] != ("manual", "holdings.json") for parts in relative_parts)


def _write_historical_capability(
    path: Path,
    *,
    route_id: str,
    include_semantic_probe_hashes: bool,
) -> str:
    route = {
        "route_id": route_id,
        "group_id": "official_events_risk",
        "contract_version": "formal-v2",
        "full_contract_tested": True,
        "field_semantics_verified": True,
        "full_universe_verified": True,
        "post_close_verified": True,
        "tested_at": NOW.isoformat(),
        "evidence_kind": "live",
        "response_hash": "e" * 64,
        "tested_library_versions": {"httpx": "0.28.1"},
    }
    if include_semantic_probe_hashes:
        route["semantic_probe_hashes"] = {"probe": "f" * 64}
    payload = {
        "contract_version": "formal-v2",
        "generated_at": NOW.isoformat(),
        "routes": [route],
    }
    bundle_hash = hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({**payload, "bundle_hash": bundle_hash}, ensure_ascii=False),
        encoding="utf-8",
    )
    return bundle_hash


@pytest.mark.parametrize(
    ("route_id", "include_semantic_probe_hashes"),
    [
        ("eastmoney.events_risk.v1", True),
        ("cninfo.direct.events_risk.v2", False),
    ],
)
def test_migration_preserves_valid_historical_capability_envelopes(
    tmp_path,
    route_id,
    include_semantic_probe_hashes,
):
    source = tmp_path / "formal_evidence"
    version_path = source / "capabilities/formal-v2/versions/history.json"
    bundle_hash = _write_historical_capability(
        version_path,
        route_id=route_id,
        include_semantic_probe_hashes=include_semantic_probe_hashes,
    )
    warehouse = FormalWarehouse(tmp_path / "warehouse")

    audit = migrate_legacy_formal_store(source, warehouse, migration_id="migration-1")

    assert audit.deletion_eligible is True
    with warehouse._connect(read_only=True) as connection:
        row = connection.execute(
            "select payload from formal_capability_bundles where bundle_hash = ?",
            [bundle_hash],
        ).fetchone()
    assert row is not None
    stored_payload = json.loads(row[0])
    assert stored_payload["routes"][0]["route_id"] == route_id
    assert (
        "semantic_probe_hashes" in stored_payload["routes"][0]
    ) is include_semantic_probe_hashes
