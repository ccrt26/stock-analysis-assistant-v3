from __future__ import annotations

from pathlib import Path

import duckdb


FORMAL_WAREHOUSE_SCHEMA_VERSION = 1


_SCHEMA_SQL = """
create table if not exists warehouse_metadata (
    key varchar primary key,
    value varchar not null
);

create table if not exists formal_versions (
    version_id varchar primary key,
    group_id varchar not null,
    target_date date not null,
    route_id varchar not null,
    route_kind varchar not null,
    content_hash varchar not null,
    complete boolean not null,
    fetched_at timestamptz not null,
    contract_version varchar not null,
    covered_dates json not null,
    coverage_codes json not null,
    coverage_proven boolean not null,
    field_coverage json not null,
    source_names json not null,
    unit_metadata json not null,
    adjustment_basis varchar,
    publication_times json not null,
    unique(group_id, target_date, content_hash)
);

create table if not exists formal_version_files (
    version_id varchar not null,
    record_type varchar not null,
    partition_date date not null,
    relative_path varchar not null unique,
    row_count bigint not null check(row_count >= 0),
    file_sha256 varchar not null,
    schema_json json not null,
    primary key(version_id, record_type, partition_date, relative_path)
);

create table if not exists formal_canonical_versions (
    group_id varchar not null,
    target_date date not null,
    version_id varchar not null,
    updated_at timestamptz not null,
    primary key(group_id, target_date)
);

create table if not exists formal_run_receipts (
    run_id varchar not null,
    revision integer not null check(revision >= 0),
    target_date date not null,
    state varchar not null,
    payload json not null,
    primary key(run_id, revision)
);

create table if not exists formal_run_latest (
    run_id varchar primary key,
    revision integer not null check(revision >= 0)
);

create table if not exists formal_candidate_sets (
    candidate_set_id varchar primary key,
    target_date date not null,
    payload json not null
);

create table if not exists formal_checkpoints (
    run_id varchar not null,
    stage varchar not null,
    trade_date date not null,
    contract_version varchar not null,
    object_id varchar not null,
    primary key(run_id, stage)
);

create table if not exists formal_reconciliation_tasks (
    task_id varchar primary key,
    group_id varchar not null,
    target_date date not null,
    status varchar not null,
    payload json not null
);

create table if not exists formal_frozen_reports (
    run_id varchar primary key,
    input_set_id varchar not null,
    payload json not null
);

create table if not exists formal_report_candidates (
    run_id varchar primary key,
    payload json not null
);

create table if not exists formal_capability_bundles (
    bundle_hash varchar primary key,
    contract_version varchar not null,
    generated_at timestamptz not null,
    mode varchar not null,
    is_latest boolean not null,
    payload json not null
);

create table if not exists formal_migrations (
    migration_id varchar primary key,
    source_root varchar not null,
    state varchar not null,
    deletion_eligible boolean not null,
    updated_at timestamptz not null,
    payload json not null
);

create index if not exists formal_versions_group_date_idx
    on formal_versions(group_id, target_date);
create index if not exists formal_version_files_version_idx
    on formal_version_files(version_id);
create index if not exists formal_run_receipts_state_idx
    on formal_run_receipts(target_date, state);
"""


def connect_formal_warehouse(
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
        initialize_formal_schema(connection)
    except Exception:
        connection.close()
        raise
    return connection


def initialize_formal_schema(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(_SCHEMA_SQL)
    connection.execute(
        "insert or replace into warehouse_metadata values (?, ?)",
        ["formal_schema_version", str(FORMAL_WAREHOUSE_SCHEMA_VERSION)],
    )


def formal_schema_version(connection: duckdb.DuckDBPyConnection) -> int:
    row = connection.execute(
        "select value from warehouse_metadata where key = 'formal_schema_version'"
    ).fetchone()
    if row is None:
        raise ValueError("formal warehouse schema version is missing")
    return int(row[0])


__all__ = [
    "FORMAL_WAREHOUSE_SCHEMA_VERSION",
    "connect_formal_warehouse",
    "formal_schema_version",
    "initialize_formal_schema",
]
