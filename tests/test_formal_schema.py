from pathlib import Path

import pytest

from stock_analyzer.storage.formal_schema import (
    FORMAL_WAREHOUSE_SCHEMA_VERSION,
    connect_formal_warehouse,
    formal_schema_version,
)


EXPECTED_TABLES = {
    "formal_versions",
    "formal_version_files",
    "formal_canonical_versions",
    "formal_run_receipts",
    "formal_run_latest",
    "formal_candidate_sets",
    "formal_checkpoints",
    "formal_reconciliation_tasks",
    "formal_frozen_reports",
    "formal_report_candidates",
    "formal_capability_bundles",
    "formal_migrations",
    "warehouse_metadata",
}


def _tables(path: Path) -> set[str]:
    with connect_formal_warehouse(path, read_only=True) as connection:
        return {
            row[0]
            for row in connection.execute(
                "select table_name from information_schema.tables "
                "where table_schema = 'main'"
            ).fetchall()
        }


def test_initialize_formal_schema_creates_exact_catalog(tmp_path):
    path = tmp_path / "warehouse.duckdb"

    with connect_formal_warehouse(path) as connection:
        assert FORMAL_WAREHOUSE_SCHEMA_VERSION == 1
        assert formal_schema_version(connection) == 1

    assert EXPECTED_TABLES <= _tables(path)


def test_catalog_transaction_rolls_back_version_and_file_together(tmp_path):
    path = tmp_path / "warehouse.duckdb"

    with connect_formal_warehouse(path) as connection:
        connection.begin()
        connection.execute(
            """
            insert into formal_versions (
                version_id, group_id, target_date, route_id, route_kind,
                content_hash, complete, fetched_at, contract_version,
                covered_dates, coverage_codes, coverage_proven,
                field_coverage, source_names, unit_metadata,
                adjustment_basis, publication_times
            ) values (
                'version-1', 'market_decision', date '2026-07-10',
                'route-1', 'primary', 'hash-1', true,
                timestamptz '2026-07-10 16:00:00+08:00', 'formal-v2',
                '[]', '[]', true, '{}', '[]', '{}', null, '{}'
            )
            """
        )
        connection.execute(
            """
            insert into formal_version_files values (
                'version-1', 'equity_bar', date '2026-07-10',
                'parquet/formal/market_daily/file.parquet', 1,
                'file-hash', '{}'
            )
            """
        )
        connection.rollback()

        assert connection.execute("select count(*) from formal_versions").fetchone()[0] == 0
        assert connection.execute("select count(*) from formal_version_files").fetchone()[0] == 0


def test_read_only_connection_does_not_initialize_missing_database(tmp_path):
    path = tmp_path / "missing.duckdb"

    with pytest.raises((OSError, RuntimeError)):
        connect_formal_warehouse(path, read_only=True)

    assert not path.exists()


def test_reopening_schema_is_idempotent(tmp_path):
    path = tmp_path / "warehouse.duckdb"

    with connect_formal_warehouse(path):
        pass
    with connect_formal_warehouse(path) as connection:
        assert formal_schema_version(connection) == 1

    assert EXPECTED_TABLES <= _tables(path)
