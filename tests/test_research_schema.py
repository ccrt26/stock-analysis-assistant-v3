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
    } <= table_names


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
