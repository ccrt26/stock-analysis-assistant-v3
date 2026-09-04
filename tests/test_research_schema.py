import duckdb
import pytest

import stock_analyzer.storage.research_schema as schema

from stock_analyzer.storage.research_schema import (
    RESEARCH_SCHEMA_VERSION,
    connect_research_warehouse,
    research_schema_version,
)


def test_research_schema_initialization_is_idempotent_and_has_live_tables(tmp_path):
    path = tmp_path / "research.duckdb"
    with connect_research_warehouse(path) as connection:
        assert research_schema_version(connection) == RESEARCH_SCHEMA_VERSION
    with connect_research_warehouse(path) as connection:
        table_names = {
            row[0]
            for row in connection.execute("show tables").fetchall()
        }

    assert {
        "research_dataset_catalog",
        "research_ingestion_runs",
        "research_fact_partitions",
        "research_fact_keys",
        "research_fact_revisions",
        "research_data_gaps",
        "research_watermarks",
        "research_derived_partitions",
        "research_fact_conflicts",
    } <= table_names
    assert RESEARCH_SCHEMA_VERSION == 6


def test_v4_gap_schema_migrates_idempotently_to_scope_identity(tmp_path):
    path = tmp_path / "research.duckdb"
    with duckdb.connect(str(path)) as connection:
        connection.execute(
            "create table research_metadata (key varchar primary key, value varchar not null)"
        )
        connection.execute(
            "insert into research_metadata values ('research_schema_version', '4')"
        )
        connection.execute(
            """
            create table research_data_gaps (
                gap_id varchar primary key, dataset_id varchar not null,
                partition_value varchar not null, status varchar not null,
                reason_category varchar not null, source_name varchar,
                first_seen_at timestamptz not null,
                last_checked_at timestamptz not null,
                next_retry_at timestamptz, impact_text varchar not null,
                detail_json json,
                unique(dataset_id, partition_value, reason_category)
            )
            """
        )
        connection.execute(
            """
            insert into research_data_gaps values
            ('old', 'industry_daily', '2026-09-01', 'failed', 'provider_error',
             'tushare', now(), now(), null, 'impact', '{}')
            """
        )

    for _ in range(2):
        with connect_research_warehouse(path) as connection:
            assert research_schema_version(connection) == 6

    with connect_research_warehouse(path, read_only=True) as connection:
        columns = {
            row[1] for row in connection.execute(
                "pragma table_info('research_data_gaps')"
            ).fetchall()
        }
        row = connection.execute(
            """
            select scope_key, source_endpoint, resolved_at
            from research_data_gaps
            """
        ).fetchone()
    assert {"scope_key", "source_endpoint", "resolved_at"} <= columns
    assert row == ("", None, None)


def test_connection_retries_only_explicit_duckdb_lock_errors(tmp_path, monkeypatch):
    real_connect = duckdb.connect
    calls = []
    sleeps = []

    def flaky(*args, **kwargs):
        calls.append(1)
        if len(calls) < 3:
            raise duckdb.IOException("Could not set lock on file: conflicting lock")
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(schema.duckdb, "connect", flaky)
    with connect_research_warehouse(
        tmp_path / "research.duckdb",
        lock_retry_attempts=3,
        lock_retry_initial_seconds=0.01,
        sleeper=sleeps.append,
    ):
        pass

    assert len(calls) == 3
    assert sleeps == [0.01, 0.02]


def _create_v5_conflict_database(path):
    with duckdb.connect(str(path)) as connection:
        connection.execute("create table research_metadata (key varchar primary key, value varchar not null)")
        connection.execute("insert into research_metadata values ('research_schema_version', '5')")
        connection.execute("""
            create table research_fact_conflicts (
                conflict_id varchar primary key, dataset_id varchar not null,
                partition_value varchar not null, business_key_hash varchar not null,
                business_key_json json not null, payload_hash varchar not null,
                row_payload json not null, source_name varchar not null,
                source_endpoint varchar not null, available_at timestamptz,
                first_seen_at timestamptz not null, last_seen_at timestamptz not null,
                status varchar not null, resolved_at timestamptz, resolution_basis json,
                unique(dataset_id, business_key_hash, payload_hash)
            )
        """)
        connection.execute("""
            insert into research_fact_conflicts values (
                'original-id', 'financial_indicator', '2026-06-30', 'key',
                '{"ts_code":"000001.SZ"}', 'payload', '{"roe":3.0}',
                'tushare', 'fina_indicator', '2026-08-20T16:00:00Z',
                '2026-09-01T00:00:00Z', '2026-09-01T01:00:00Z',
                'resolved', '2026-09-02T00:00:00Z', '{"basis":"original"}'
            )
        """)
        return connection.execute("select to_json(c)::varchar from research_fact_conflicts c").fetchall()


def test_v5_conflict_migration_preserves_rows_and_allows_recurrence(tmp_path):
    path = tmp_path / "research.duckdb"
    original = _create_v5_conflict_database(path)
    for _ in range(2):
        with connect_research_warehouse(path) as connection:
            assert connection.execute("select to_json(c)::varchar from research_fact_conflicts c").fetchall() == original
    with connect_research_warehouse(path) as connection:
        connection.execute("""
            insert into research_fact_conflicts
            select 'new-id', dataset_id, partition_value, business_key_hash,
                   business_key_json, payload_hash, row_payload, source_name,
                   source_endpoint, available_at, '2026-09-03T00:00:00Z',
                   '2026-09-03T00:00:00Z', 'unresolved', null, null
            from research_fact_conflicts where conflict_id = 'original-id'
        """)
        assert connection.execute("select count(*) from research_fact_conflicts").fetchone()[0] == 2
        assert connection.execute("select to_json(c)::varchar from research_fact_conflicts c where conflict_id='original-id'").fetchall() == original
        assert connection.execute("select count(*) from duckdb_indexes() where index_name='research_conflicts_lookup_idx'").fetchone()[0] == 1
    with connect_research_warehouse(path) as connection:
        assert connection.execute("select count(*) from research_fact_conflicts").fetchone()[0] == 2


def test_v5_conflict_migration_failure_rolls_back_original_schema_and_rows(tmp_path):
    path = tmp_path / "research.duckdb"
    original = _create_v5_conflict_database(path)
    with duckdb.connect(str(path)) as connection:
        class FailDuringRename:
            def execute(self, sql, *args):
                if "alter table research_fact_conflicts_v6 rename" in sql.lower():
                    raise RuntimeError("injected migration failure")
                return connection.execute(sql, *args)

        with pytest.raises(RuntimeError, match="injected migration failure"):
            schema.initialize_research_schema(FailDuringRename())
        assert research_schema_version(connection) == 5
        assert connection.execute("select to_json(c)::varchar from research_fact_conflicts c").fetchall() == original
        assert connection.execute("select constraint_column_names from duckdb_constraints() where table_name='research_fact_conflicts' and constraint_type='UNIQUE'").fetchone()[0] == ["dataset_id", "business_key_hash", "payload_hash"]
        assert connection.execute("select count(*) from duckdb_tables() where table_name='research_fact_conflicts_v6'").fetchone()[0] == 0


def test_connection_does_not_retry_non_lock_errors(tmp_path, monkeypatch):
    calls = []

    def invalid(*args, **kwargs):
        calls.append(1)
        raise duckdb.IOException("database file is corrupt")

    monkeypatch.setattr(schema.duckdb, "connect", invalid)
    with pytest.raises(duckdb.IOException, match="corrupt"):
        connect_research_warehouse(
            tmp_path / "research.duckdb",
            lock_retry_attempts=5,
            sleeper=lambda seconds: None,
        )
    assert len(calls) == 1


def test_same_idempotency_key_cannot_create_two_runs(tmp_path):
    path = tmp_path / "research.duckdb"
    with connect_research_warehouse(path) as connection:
        connection.execute(
            """
            insert into research_ingestion_runs
            (run_id, idempotency_key, stage, data_date, status, started_at)
            values ('run-1', 'close:2026-07-10', 'close', date '2026-07-10',
                    'fetching', now())
            """
        )
        try:
            connection.execute(
                """
                insert into research_ingestion_runs
                (run_id, idempotency_key, stage, data_date, status, started_at)
                values ('run-2', 'close:2026-07-10', 'close', date '2026-07-10',
                        'fetching', now())
                """
            )
        except Exception:
            pass
        count = connection.execute(
            "select count(*) from research_ingestion_runs"
        ).fetchone()[0]
    assert count == 1


def test_derived_partition_identity_is_unique(tmp_path):
    path = tmp_path / "research.duckdb"
    with connect_research_warehouse(path) as connection:
        parameters = [
            "market_technical",
            "2026-07-10",
            "v1",
            "derived/market_technical/analysis_date=2026-07-10/"
            "formula_version=v1/data.parquet",
            1,
            "content-hash",
            "file-sha",
            "manifest-hash",
            "{}",
            "complete",
            "[]",
            "derived-run-1",
        ]
        connection.execute(
            """
            insert into research_derived_partitions
            (feature_set, analysis_date, formula_version, relative_path,
             row_count, content_hash, file_sha256, input_manifest_hash,
             input_manifest_json, quality_status, limitations_json,
             committed_at, run_id)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, now(), ?)
            """,
            parameters,
        )
        try:
            connection.execute(
                """
                insert into research_derived_partitions
                (feature_set, analysis_date, formula_version, relative_path,
                 row_count, content_hash, file_sha256, input_manifest_hash,
                 input_manifest_json, quality_status, limitations_json,
                 committed_at, run_id)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, now(), ?)
                """,
                [
                    *parameters[:3],
                    "derived/a-different-path/data.parquet",
                    *parameters[4:-1],
                    "derived-run-2",
                ],
            )
        except Exception:
            pass
        count = connection.execute(
            "select count(*) from research_derived_partitions"
        ).fetchone()[0]

    assert count == 1
