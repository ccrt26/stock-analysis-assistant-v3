import json
from datetime import datetime, timedelta, timezone

from stock_analyzer.ops.revision_metadata_repair import (
    MIGRATION_ID,
    inspect_revision_metadata_repair,
    run_revision_metadata_repair,
)
from stock_analyzer.storage.research_schema import connect_research_warehouse
from stock_analyzer.storage.research_warehouse import ResearchWarehouse


def _insert_revision_rows(warehouse: ResearchWarehouse) -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = (
        (1, "payload-a", start, start),
        (2, "payload-a", start, start + timedelta(days=1)),
        (3, "payload-a", start, start + timedelta(days=2)),
        (4, "payload-b", start + timedelta(days=3), start + timedelta(days=2)),
        (5, "payload-b", start + timedelta(days=2), start + timedelta(days=3)),
    )
    with connect_research_warehouse(warehouse.duckdb_path) as connection:
        for revision_no, payload_hash, valid_from, valid_to in rows:
            connection.execute(
                """
                insert into research_fact_revisions
                (dataset_id, business_key_hash, revision_no, partition_value,
                 payload_hash, row_payload, valid_from, valid_to,
                 superseded_by_run_id, changed_fields)
                values ('equity_daily', 'key-1', ?, '2026-01-01', ?, ?, ?, ?,
                        'legacy-run', '[]')
                """,
                [
                    revision_no,
                    payload_hash,
                    json.dumps({"payload": payload_hash}),
                    valid_from,
                    valid_to,
                ],
            )


def test_revision_metadata_repair_is_dry_runnable_recoverable_and_idempotent(
    tmp_path,
):
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    archive = tmp_path / "archive"
    _insert_revision_rows(warehouse)
    stale = (
        warehouse.root
        / ".backfill_staging"
        / "fundamentals"
        / "income_statement"
        / "000001.SZ.parquet"
    )
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"legacy staging")

    dry_run = inspect_revision_metadata_repair(warehouse.root)

    assert dry_run["rows_before"] == 5
    assert dry_run["rows_after"] == 2
    assert dry_run["nonpositive_rows_removed"] == 2
    assert dry_run["redundant_rows_merged"] == 1
    assert dry_run["invalid_after"] == 0
    assert dry_run["overlaps_after"] == 0
    assert dry_run["legacy_staging_files"] == 1
    assert stale.is_file()

    receipt = run_revision_metadata_repair(warehouse.root, archive)

    assert receipt["status"] == "completed"
    repair_root = archive / "repairs" / MIGRATION_ID
    assert (repair_root / "backups" / "research.duckdb").is_file()
    assert (
        repair_root
        / "backups"
        / "legacy-fundamental-staging"
        / "income_statement"
        / "000001.SZ.parquet"
    ).is_file()
    assert not stale.exists()
    assert (repair_root / "receipt.json").is_file()
    assert (repair_root / "receipt.txt").is_file()
    with connect_research_warehouse(
        warehouse.duckdb_path, read_only=True
    ) as connection:
        rows = connection.execute(
            """
            select revision_no, payload_hash,
                   cast(valid_from as varchar), cast(valid_to as varchar)
            from research_fact_revisions
            order by valid_from, valid_to
            """
        ).fetchall()
        migration_count = connection.execute(
            "select count(*) from research_migrations where migration_id = ?",
            [MIGRATION_ID],
        ).fetchone()[0]
    assert len(rows) == 2
    assert [row[1] for row in rows] == ["payload-a", "payload-b"]
    assert migration_count == 1

    second = run_revision_metadata_repair(warehouse.root, archive)

    assert second["status"] == "already_applied"
    with connect_research_warehouse(
        warehouse.duckdb_path, read_only=True
    ) as connection:
        assert connection.execute(
            "select count(*) from research_fact_revisions"
        ).fetchone()[0] == 2
