from __future__ import annotations

from pathlib import Path

import duckdb


RESEARCH_SCHEMA_VERSION = 4


_SCHEMA_SQL = """
create table if not exists research_metadata (
    key varchar primary key,
    value varchar not null
);

create table if not exists research_dataset_catalog (
    dataset_id varchar primary key,
    contract_json json not null,
    updated_at timestamptz not null default now()
);

create table if not exists research_ingestion_runs (
    run_id varchar primary key,
    idempotency_key varchar not null unique,
    stage varchar not null,
    data_date date,
    status varchar not null,
    started_at timestamptz not null,
    finished_at timestamptz,
    summary_json json
);

create table if not exists research_fact_partitions (
    dataset_id varchar not null,
    partition_value varchar not null,
    relative_path varchar not null unique,
    row_count bigint not null check(row_count >= 0),
    content_hash varchar not null,
    file_sha256 varchar not null,
    min_available_at timestamptz,
    max_available_at timestamptz,
    source_names json not null,
    committed_at timestamptz not null,
    ingestion_run_id varchar not null,
    quality_status varchar not null,
    primary key(dataset_id, partition_value)
);

create table if not exists research_fact_keys (
    dataset_id varchar not null,
    business_key_hash varchar not null,
    partition_value varchar not null,
    primary key(dataset_id, business_key_hash)
);

create table if not exists research_fact_revisions (
    dataset_id varchar not null,
    business_key_hash varchar not null,
    revision_no integer not null check(revision_no > 0),
    partition_value varchar not null,
    payload_hash varchar not null,
    row_payload json not null,
    valid_from timestamptz not null,
    valid_to timestamptz not null,
    superseded_by_run_id varchar not null,
    changed_fields json not null,
    primary key(dataset_id, business_key_hash, revision_no)
);

create table if not exists research_data_gaps (
    gap_id varchar primary key,
    dataset_id varchar not null,
    partition_value varchar not null,
    status varchar not null,
    reason_category varchar not null,
    source_name varchar,
    first_seen_at timestamptz not null,
    last_checked_at timestamptz not null,
    next_retry_at timestamptz,
    impact_text varchar not null,
    detail_json json,
    unique(dataset_id, partition_value, reason_category)
);

create table if not exists research_watermarks (
    dataset_id varchar not null,
    scope_key varchar not null,
    watermark_value varchar not null,
    updated_at timestamptz not null,
    run_id varchar not null,
    primary key(dataset_id, scope_key)
);

create table if not exists research_derived_partitions (
    feature_set varchar not null,
    analysis_date date not null,
    formula_version varchar not null,
    relative_path varchar not null unique,
    row_count bigint not null check(row_count >= 0),
    content_hash varchar not null,
    file_sha256 varchar not null,
    input_manifest_hash varchar not null,
    input_manifest_json json not null,
    quality_status varchar not null check(
        quality_status in (
            'complete', 'complete_with_declared_gaps', 'limited'
        )
    ),
    limitations_json json not null,
    committed_at timestamptz not null,
    run_id varchar not null,
    primary key(feature_set, analysis_date, formula_version)
);

create index if not exists research_partitions_dataset_idx
    on research_fact_partitions(dataset_id, partition_value);
create index if not exists research_revisions_lookup_idx
    on research_fact_revisions(dataset_id, business_key_hash, valid_from, valid_to);
create index if not exists research_gaps_status_idx
    on research_data_gaps(status, dataset_id);
create index if not exists research_fact_keys_partition_idx
    on research_fact_keys(dataset_id, partition_value);
create index if not exists research_derived_partitions_feature_date_idx
    on research_derived_partitions(feature_set, analysis_date);
"""


def connect_research_warehouse(
    path: Path,
    *,
    read_only: bool = False,
) -> duckdb.DuckDBPyConnection:
    database_path = Path(path)
    if read_only:
        if not database_path.is_file():
            raise FileNotFoundError(database_path)
        return duckdb.connect(str(database_path), read_only=True)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(database_path))
    try:
        initialize_research_schema(connection)
    except Exception:
        connection.close()
        raise
    return connection


def initialize_research_schema(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(_SCHEMA_SQL)
    connection.execute(
        "insert or replace into research_metadata values (?, ?)",
        ["research_schema_version", str(RESEARCH_SCHEMA_VERSION)],
    )


def research_schema_version(connection: duckdb.DuckDBPyConnection) -> int:
    row = connection.execute(
        "select value from research_metadata where key = 'research_schema_version'"
    ).fetchone()
    if row is None:
        raise ValueError("research warehouse schema version is missing")
    return int(row[0])


__all__ = [
    "RESEARCH_SCHEMA_VERSION",
    "connect_research_warehouse",
    "initialize_research_schema",
    "research_schema_version",
]
