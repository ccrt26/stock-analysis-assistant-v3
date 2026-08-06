from datetime import date, datetime, timedelta, timezone

from stock_analyzer.data.research_contracts import FactBatch, ResearchDatasetId
from stock_analyzer.ops.main_business_classification_repair import (
    MIGRATION_ID,
    inspect_main_business_classification_repair,
    run_main_business_classification_repair,
)
from stock_analyzer.storage.research_warehouse import ResearchWarehouse


def _batch(value: float, received_at: datetime) -> FactBatch:
    return FactBatch(
        dataset_id=ResearchDatasetId.MAIN_BUSINESS,
        partition_value="2026-06-30",
        source_name="tushare",
        source_endpoint="fina_mainbz",
        ingestion_run_id="legacy-main-business",
        ingested_at=received_at,
        default_available_at=received_at,
        records=[
            {
                "ts_code": "000001.SZ",
                "report_period": date(2026, 6, 30),
                "classification": "provider_unspecified",
                "item_name": "租赁",
                "bz_item": "租赁",
                "bz_code": "P",
                "bz_sales": value,
                "available_at": received_at,
            }
        ],
    )


def test_main_business_classification_repair_updates_facts_and_revisions(
    tmp_path,
):
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    archive = tmp_path / "archive"
    first = datetime(2026, 8, 4, 12, tzinfo=timezone.utc)
    warehouse.commit_batch(_batch(100.0, first))
    warehouse.commit_batch(_batch(101.0, first + timedelta(hours=1)))

    dry_run = inspect_main_business_classification_repair(warehouse.root)

    assert dry_run["fact_rows_changed"] == 1
    assert dry_run["revision_rows_changed"] == 1
    assert dry_run["duplicate_business_keys_after"] == 0

    receipt = run_main_business_classification_repair(
        warehouse.root,
        archive,
    )

    assert receipt["status"] == "completed"
    repair_root = archive / "repairs" / MIGRATION_ID
    assert (repair_root / "backups" / "research.duckdb").is_file()
    assert (
        repair_root
        / "backups"
        / "facts"
        / "main_business"
        / "report_period=2026-06-30"
        / "data.parquet"
    ).is_file()
    current = warehouse.read_current(ResearchDatasetId.MAIN_BUSINESS)
    revisions = warehouse.revision_rows(ResearchDatasetId.MAIN_BUSINESS)
    assert current.iloc[0]["classification"] == "product"
    assert revisions[0]["row_payload"]["classification"] == "product"
    assert current.iloc[0]["business_key_hash"] == revisions[0][
        "business_key_hash"
    ]

    second = run_main_business_classification_repair(
        warehouse.root,
        archive,
    )
    assert second["status"] == "already_applied"
