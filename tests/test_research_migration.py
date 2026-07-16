from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from stock_analyzer.data.research_contracts import FactBatch, ResearchDatasetId
from stock_analyzer.storage.research_migration import (
    audit_legacy_market_migration,
    build_legacy_market_cleanup_manifest,
    execute_legacy_market_cleanup,
    inspect_legacy_market,
    migrate_legacy_market,
)
from stock_analyzer.storage.research_warehouse import ResearchWarehouse


def _write_version(
    root: Path,
    *,
    version_id: str,
    trade_date: str,
    closes: dict[str, float],
) -> None:
    rows = []
    for ordinal, (ts_code, close) in enumerate(sorted(closes.items())):
        rows.append(
            {
                "amount": 1000.0,
                "close": close,
                "high": close + 0.2,
                "low": close - 0.2,
                "open": close - 0.1,
                "record_type": "equity_bar",
                "source_name": "tushare.daily",
                "trade_date": trade_date,
                "ts_code": ts_code,
                "volume": 100.0,
                "__version_id": version_id,
                "__group_id": "market_decision",
                "__record_type": "equity_bar",
                "__ordinal": ordinal,
                "__present_fields": "[]",
                "__json_fields": "[]",
                "__value_types": "{}",
            }
        )
    path = (
        root
        / "market_daily"
        / f"trade_date={trade_date}"
        / "record_type=equity_bar"
        / f"version_id={version_id}"
        / "part-00000.parquet"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(path, index=False)


def test_inspection_counts_physical_duplicates_unique_facts_and_conflicts(tmp_path):
    source = tmp_path / "formal"
    _write_version(
        source,
        version_id="market_decision-2026-07-10-a",
        trade_date="2026-07-09",
        closes={"000001.SZ": 10.0, "000002.SZ": 20.0},
    )
    _write_version(
        source,
        version_id="market_decision-2026-07-11-b",
        trade_date="2026-07-09",
        closes={"000001.SZ": 10.0, "000002.SZ": 20.0},
    )
    _write_version(
        source,
        version_id="market_decision-2026-07-12-c",
        trade_date="2026-07-09",
        closes={"000001.SZ": 10.1, "000002.SZ": 20.0},
    )

    audit = inspect_legacy_market(source)

    assert audit.physical_rows == 6
    assert audit.unique_business_keys == 2
    assert audit.duplicate_rows == 4
    assert audit.version_count == 3
    assert audit.conflicting_business_keys == 1


def test_migration_reads_version_union_preserves_real_revision_and_is_idempotent(tmp_path):
    source = tmp_path / "formal"
    _write_version(
        source,
        version_id="market_decision-2026-07-10-a",
        trade_date="2026-07-09",
        closes={"000001.SZ": 10.0, "000002.SZ": 20.0},
    )
    _write_version(
        source,
        version_id="market_decision-2026-07-11-b",
        trade_date="2026-07-10",
        closes={"000003.SZ": 30.0},
    )
    _write_version(
        source,
        version_id="market_decision-2026-07-12-c",
        trade_date="2026-07-09",
        closes={"000001.SZ": 10.1, "000002.SZ": 20.0},
    )
    warehouse = ResearchWarehouse(tmp_path / "warehouse")

    first = migrate_legacy_market(source, warehouse, migration_id="migration-1")
    second = migrate_legacy_market(source, warehouse, migration_id="migration-1")

    current = warehouse.read_current(ResearchDatasetId.EQUITY_DAILY)
    assert len(current) == 3
    assert current.loc[current["ts_code"] == "000001.SZ", "close"].iloc[0] == 10.1
    assert warehouse.revision_count(ResearchDatasetId.EQUITY_DAILY) == 1
    assert first.source_audit.unique_business_keys == 3
    assert first.migrated_business_keys == 3
    assert second.already_completed is True
    assert warehouse.revision_count(ResearchDatasetId.EQUITY_DAILY) == 1


def test_migration_uses_all_versions_not_only_latest_snapshot(tmp_path):
    source = tmp_path / "formal"
    _write_version(
        source,
        version_id="market_decision-2026-07-10-a",
        trade_date="2026-07-08",
        closes={"000001.SZ": 9.8},
    )
    _write_version(
        source,
        version_id="market_decision-2026-07-13-z",
        trade_date="2026-07-10",
        closes={"000001.SZ": 10.2},
    )
    warehouse = ResearchWarehouse(tmp_path / "warehouse")

    result = migrate_legacy_market(source, warehouse, migration_id="union")
    current = warehouse.read_current(ResearchDatasetId.EQUITY_DAILY)

    assert result.source_audit.trade_date_count == 2
    assert sorted(current["trade_date"].astype(str)) == ["2026-07-08", "2026-07-10"]


def test_strict_migration_audit_compares_source_values_and_manifest_hash(tmp_path):
    source = tmp_path / "formal"
    _write_version(
        source,
        version_id="market_decision-2026-07-10-a",
        trade_date="2026-07-09",
        closes={"000001.SZ": 10.0},
    )
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    migrate_legacy_market(source, warehouse, migration_id="strict")

    audit = audit_legacy_market_migration(
        source, warehouse, migration_id="strict", strict_hashes=True
    )

    assert audit.passed is True
    assert audit.missing_target_keys == 0
    assert audit.extra_target_keys == 0
    assert audit.value_mismatches == 0
    assert audit.source_manifest_matches is True


def test_cleanup_manifest_requires_strict_audit_and_deletes_verified_source(tmp_path):
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    source = warehouse.root / "parquet" / "formal"
    _write_version(
        source,
        version_id="market_decision-2026-07-10-a",
        trade_date="2026-07-09",
        closes={"000001.SZ": 10.0},
    )
    migrate_legacy_market(source, warehouse, migration_id="cleanup")

    manifest = build_legacy_market_cleanup_manifest(
        source, warehouse, migration_id="cleanup"
    )
    receipt = execute_legacy_market_cleanup(manifest, warehouse)

    assert manifest.strict_audit.passed is True
    assert manifest.record_types == ("equity_bar",)
    assert receipt.files_deleted == 1
    assert receipt.source_removed is True
    assert not source.exists()
    assert len(warehouse.read_current(ResearchDatasetId.EQUITY_DAILY)) == 1

    post_cleanup_audit = audit_legacy_market_migration(
        source,
        warehouse,
        migration_id="cleanup",
        strict_hashes=True,
        cleanup_manifest=manifest,
        cleanup_receipt=receipt,
    )
    assert post_cleanup_audit.passed is True
    assert post_cleanup_audit.source_manifest_matches is True
    assert post_cleanup_audit.value_mismatches == 0

    invalid_receipt = receipt.model_copy(update={"source_removed": False})
    invalid_audit = audit_legacy_market_migration(
        source,
        warehouse,
        migration_id="cleanup",
        strict_hashes=True,
        cleanup_manifest=manifest,
        cleanup_receipt=invalid_receipt,
    )
    assert invalid_audit.passed is False

    warehouse.commit_batch(
        FactBatch(
            dataset_id=ResearchDatasetId.EQUITY_DAILY,
            partition_value="2026-07-09",
            source_name="test",
            source_endpoint="changed-after-cleanup",
            ingestion_run_id="changed-after-cleanup",
            ingested_at=datetime.now(timezone.utc),
            default_available_at=datetime.now(timezone.utc),
            records=[
                {
                    "trade_date": date(2026, 7, 9),
                    "ts_code": "000001.SZ",
                    "open": 9.9,
                    "high": 99.2,
                        "low": 9.8,
                        "close": 99.0,
                        "pre_close": 10.0,
                        "change": 89.0,
                        "pct_chg": 890.0,
                        "volume": 100.0,
                    "amount": 1000.0,
                }
            ],
        )
    )
    changed_audit = audit_legacy_market_migration(
        source,
        warehouse,
        migration_id="cleanup",
        strict_hashes=True,
        cleanup_manifest=manifest,
        cleanup_receipt=receipt,
    )
    assert changed_audit.passed is False
    assert changed_audit.value_mismatches > 0


def test_cleanup_refuses_source_changed_after_manifest(tmp_path):
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    source = warehouse.root / "parquet" / "formal"
    _write_version(
        source,
        version_id="market_decision-2026-07-10-a",
        trade_date="2026-07-09",
        closes={"000001.SZ": 10.0},
    )
    migrate_legacy_market(source, warehouse, migration_id="cleanup-changed")
    manifest = build_legacy_market_cleanup_manifest(
        source, warehouse, migration_id="cleanup-changed"
    )
    (source / ".DS_Store").write_bytes(b"changed")

    with pytest.raises(ValueError, match="source changed after cleanup manifest"):
        execute_legacy_market_cleanup(manifest, warehouse)

    assert source.exists()


def test_non_equity_cleanup_requires_an_explicit_retirement_decision(tmp_path):
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    source = warehouse.root / "parquet" / "formal"
    _write_version(
        source,
        version_id="market_decision-2026-07-10-a",
        trade_date="2026-07-09",
        closes={"000001.SZ": 10.0},
    )
    board_path = (
        source
        / "market_daily"
        / "trade_date=2026-07-09"
        / "record_type=board_bar"
        / "version_id=market_decision-2026-07-10-a"
        / "part-00000.parquet"
    )
    board_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([{"record_type": "board_bar", "board_code": "SW801010"}]).to_parquet(
        board_path, index=False
    )
    migrate_legacy_market(source, warehouse, migration_id="retirement-decision")

    with pytest.raises(ValueError, match="explicit retirement decisions: board_bar"):
        build_legacy_market_cleanup_manifest(
            source,
            warehouse,
            migration_id="retirement-decision",
        )
