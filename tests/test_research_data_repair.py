import json
from datetime import date, datetime, timezone
from pathlib import Path

from stock_analyzer.data.research_contracts import FactBatch, ResearchDatasetId
from stock_analyzer.ops.research_data_repair import (
    AFFECTED_DERIVED_DATES,
    DAILY_REPAIR_TARGETS,
    create_repair_backup,
    extract_financial_indicator_conflict_targets,
    missing_financial_indicator_targets_from_files,
    missing_financial_indicator_targets,
    repair_known_zero_length_financial_revision,
)
from stock_analyzer.storage.research_schema import connect_research_warehouse
from stock_analyzer.storage.research_warehouse import ResearchWarehouse


def test_derived_audit_uses_actual_proxy_index_status_field(tmp_path, monkeypatch):
    import pandas as pd
    from types import SimpleNamespace
    from tools import audit_research_gap_closure as audit

    class Store:
        def partition_manifest(self, *args, **kwargs):
            return pd.DataFrame([{
                "input_manifest_json": json.dumps({
                    "fact_snapshot": {"partitions": [
                        {"dataset": "industry_daily_proxy"}
                    ]}
                })
            }])

        def read(self, *args, **kwargs):
            return pd.DataFrame([{
                "group_type": "industry", "level": "L1",
                "proxy_index_status": "complete",
            }])

    monkeypatch.setattr(audit, "DerivedFeatureStore", lambda root: Store())
    result = audit._derived_audit(SimpleNamespace(root=tmp_path))

    assert result["passed"] is True
    assert result["problem_count"] == 0


def _batch(value, run_id):
    available = datetime(2026, 8, 5, 16, tzinfo=timezone.utc)
    return FactBatch(
        dataset_id=ResearchDatasetId.FINANCIAL_INDICATOR,
        partition_value="2026-06-30",
        source_name="tushare",
        source_endpoint="fina_indicator",
        ingestion_run_id=run_id,
        ingested_at=available,
        default_available_at=available,
        reconstruct_source_revisions=True,
        records=[{
            "ts_code": "688668.SH", "report_period": date(2026, 6, 30),
            "report_type": "indicator", "ann_date": date(2026, 8, 5),
            "fcff": value, "available_at": available,
        }],
    )


def test_known_zero_length_revision_moves_variants_to_conflicts_before_delete(
    tmp_path,
):
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    warehouse.commit_batch(_batch(None, "first"))
    warehouse.commit_batch(_batch(42.0, "second"))
    with connect_research_warehouse(warehouse.duckdb_path) as connection:
        row = connection.execute(
            """
            select business_key_hash from research_fact_revisions
            where dataset_id = 'financial_indicator' and valid_to = valid_from
            """
        ).fetchone()
        assert row is not None
        key_hash = row[0]

    result = repair_known_zero_length_financial_revision(
        warehouse,
        business_key_hash=key_hash,
        dry_run=False,
        observed_at=datetime(2026, 9, 3, tzinfo=timezone.utc),
    )

    assert result["deleted_revision_rows"] == 1
    with connect_research_warehouse(
        warehouse.duckdb_path, read_only=True
    ) as connection:
        invalid = connection.execute(
            "select count(*) from research_fact_revisions where valid_to <= valid_from"
        ).fetchone()[0]
        conflicts = connection.execute(
            "select count(*) from research_fact_conflicts"
        ).fetchone()[0]
    assert invalid == 0
    assert conflicts == 2


def test_conflict_target_extraction_reads_all_unresolved_ledger_keys(tmp_path):
    from stock_analyzer.storage.research_conflicts import ResearchConflictRegistry

    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    registry = ResearchConflictRegistry(warehouse.duckdb_path)
    for code, period in (
        ("000001.SZ", "2026-06-30"),
        ("600000.SH", "2025-12-31"),
    ):
        registry.record_variants(
            ResearchDatasetId.FINANCIAL_INDICATOR,
            period,
            business_key=(code, period, "indicator"),
            rows=[
                {"ts_code": code, "report_period": period,
                 "report_type": "indicator", "fcff": 1.0},
                {"ts_code": code, "report_period": period,
                 "report_type": "indicator", "fcff": 2.0},
            ],
            source_name="tushare",
            source_endpoint="fina_indicator",
        )
    registry.resolve(
        ResearchDatasetId.FINANCIAL_INDICATOR,
        business_key=("600000.SH", "2025-12-31", "indicator"),
        resolved_at=datetime.now(timezone.utc),
        resolution_basis={"basis": "test"},
    )

    targets = extract_financial_indicator_conflict_targets(
        warehouse.duckdb_path
    )

    assert targets == (("000001.SZ", date(2026, 6, 30)),)


def test_missing_indicator_targets_excludes_existing_business_key(tmp_path):
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    warehouse.commit_batch(_batch(42.0, "first"))

    missing = missing_financial_indicator_targets(
        warehouse,
        (
            ("688668.SH", date(2026, 6, 30)),
            ("000001.SZ", date(2026, 6, 30)),
        ),
    )

    assert missing == (("000001.SZ", date(2026, 6, 30)),)
    assert missing_financial_indicator_targets_from_files(
        warehouse.root,
        (
            ("688668.SH", date(2026, 6, 30)),
            ("000001.SZ", date(2026, 6, 30)),
        ),
    ) == missing


def test_repair_backup_freezes_database_target_files_and_baseline(tmp_path):
    warehouse_root = tmp_path / "warehouse"
    archive_root = tmp_path / "archive"
    warehouse = ResearchWarehouse(warehouse_root)
    warehouse.commit_batch(_batch(42.0, "first"))

    result = create_repair_backup(
        warehouse_root=warehouse_root,
        archive_root=archive_root,
        financial_targets=(("688668.SH", date(2026, 6, 30)),),
        created_at=datetime(2026, 9, 3, 8, 30, tzinfo=timezone.utc),
    )

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    checksums = result.checksums_path.read_text(encoding="utf-8")
    assert (result.backup_root / "warehouse" / "research.duckdb").is_file()
    assert (
        result.backup_root
        / "warehouse"
        / "facts/financial_indicator/report_period=2026-06-30/data.parquet"
    ).is_file()
    assert manifest["daily_targets"] == {
        key: [value.isoformat() for value in values]
        for key, values in DAILY_REPAIR_TARGETS.items()
    }
    assert "industry_daily_proxy" in manifest["daily_targets"]
    assert "industry_daily" not in manifest["daily_targets"]
    assert manifest["affected_derived_dates"] == [
        value.isoformat() for value in AFFECTED_DERIVED_DATES
    ]
    assert manifest["baseline"]["schema_version"] == "6"
    assert "warehouse/research.duckdb" in checksums
