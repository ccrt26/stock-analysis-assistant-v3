from __future__ import annotations

import time
from pathlib import Path
from collections.abc import Callable

import duckdb


RESEARCH_SCHEMA_VERSION = 6


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
    scope_key varchar not null default '',
    status varchar not null,
    reason_category varchar not null,
    source_name varchar,
    source_endpoint varchar,
    first_seen_at timestamptz not null,
    last_checked_at timestamptz not null,
    next_retry_at timestamptz,
    resolved_at timestamptz,
    impact_text varchar not null,
    detail_json json,
    unique(dataset_id, partition_value, scope_key)
);

create table if not exists research_fact_conflicts (
    conflict_id varchar primary key,
    dataset_id varchar not null,
    partition_value varchar not null,
    business_key_hash varchar not null,
    business_key_json json not null,
    payload_hash varchar not null,
    row_payload json not null,
    source_name varchar not null,
    source_endpoint varchar not null,
    available_at timestamptz,
    first_seen_at timestamptz not null,
    last_seen_at timestamptz not null,
    status varchar not null,
    resolved_at timestamptz,
    resolution_basis json,
    unique(dataset_id, business_key_hash, payload_hash, first_seen_at)
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
create index if not exists research_conflicts_lookup_idx
    on research_fact_conflicts(dataset_id, business_key_hash, status);
create index if not exists research_fact_keys_partition_idx
    on research_fact_keys(dataset_id, partition_value);
create index if not exists research_derived_partitions_feature_date_idx
    on research_derived_partitions(feature_set, analysis_date);
"""


def connect_research_warehouse(
    path: Path,
    *,
    read_only: bool = False,
    lock_retry_attempts: int = 5,
    lock_retry_initial_seconds: float = 0.05,
    sleeper: Callable[[float], None] = time.sleep,
) -> duckdb.DuckDBPyConnection:
    database_path = Path(path)
    if read_only:
        if not database_path.is_file():
            raise FileNotFoundError(database_path)
        return _connect_with_lock_retry(
            database_path,
            read_only=True,
            attempts=lock_retry_attempts,
            initial_seconds=lock_retry_initial_seconds,
            sleeper=sleeper,
        )
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = _connect_with_lock_retry(
        database_path,
        read_only=False,
        attempts=lock_retry_attempts,
        initial_seconds=lock_retry_initial_seconds,
        sleeper=sleeper,
    )
    try:
        initialize_research_schema(connection)
    except Exception:
        connection.close()
        raise
    return connection


def _connect_with_lock_retry(
    database_path: Path,
    *,
    read_only: bool,
    attempts: int,
    initial_seconds: float,
    sleeper: Callable[[float], None],
) -> duckdb.DuckDBPyConnection:
    if attempts < 1:
        raise ValueError("lock_retry_attempts must be positive")
    for attempt in range(attempts):
        try:
            return duckdb.connect(str(database_path), read_only=read_only)
        except Exception as exc:
            if not _is_lock_error(exc) or attempt + 1 >= attempts:
                raise
            sleeper(initial_seconds * (2 ** attempt))
    raise AssertionError("unreachable")


def _is_lock_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(
        marker in message
        for marker in (
            "could not set lock",
            "conflicting lock",
            "database is locked",
            "database is busy",
        )
    )


def initialize_research_schema(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute("begin transaction")
    try:
        connection.execute(_SCHEMA_SQL)
        gap_columns = {
            str(row[1])
            for row in connection.execute(
                "pragma table_info('research_data_gaps')"
            ).fetchall()
        }
        if "scope_key" not in gap_columns:
            _migrate_v4_gaps(connection)
        conflict_unique_keys = connection.execute(
            "select constraint_column_names from duckdb_constraints() "
            "where table_name = 'research_fact_conflicts' "
            "and constraint_type = 'UNIQUE'"
        ).fetchall()
        if any(
            fields == ["dataset_id", "business_key_hash", "payload_hash"]
            for (fields,) in conflict_unique_keys
        ):
            _migrate_v5_conflicts(connection)
        connection.execute(
            """
            create index if not exists research_gaps_status_idx
                on research_data_gaps(status, dataset_id);
            create index if not exists research_conflicts_lookup_idx
                on research_fact_conflicts(dataset_id, business_key_hash, status)
            """
        )
        connection.execute(
            "insert or replace into research_metadata values (?, ?)",
            ["research_schema_version", str(RESEARCH_SCHEMA_VERSION)],
        )
        connection.execute("commit")
    except Exception:
        connection.execute("rollback")
        raise


def _migrate_v4_gaps(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        """
        create table research_data_gaps_v5 (
            gap_id varchar primary key,
            dataset_id varchar not null,
            partition_value varchar not null,
            scope_key varchar not null default '',
            status varchar not null,
            reason_category varchar not null,
            source_name varchar,
            source_endpoint varchar,
            first_seen_at timestamptz not null,
            last_checked_at timestamptz not null,
            next_retry_at timestamptz,
            resolved_at timestamptz,
            impact_text varchar not null,
            detail_json json,
            unique(dataset_id, partition_value, scope_key)
        )
        """
    )
    connection.execute(
        """
        insert into research_data_gaps_v5
        select gap_id, dataset_id, partition_value, '', status,
               reason_category, source_name, null, first_seen_at,
               last_checked_at, next_retry_at,
               case when status = 'resolved' then last_checked_at else null end,
               impact_text, detail_json
        from research_data_gaps
        qualify row_number() over (
            partition by dataset_id, partition_value
            order by last_checked_at desc, gap_id desc
        ) = 1
        """
    )
    connection.execute("drop table research_data_gaps")
    connection.execute(
        "alter table research_data_gaps_v5 rename to research_data_gaps"
    )


def _migrate_v5_conflicts(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        """
        create table research_fact_conflicts_v6 (
            conflict_id varchar primary key,
            dataset_id varchar not null,
            partition_value varchar not null,
            business_key_hash varchar not null,
            business_key_json json not null,
            payload_hash varchar not null,
            row_payload json not null,
            source_name varchar not null,
            source_endpoint varchar not null,
            available_at timestamptz,
            first_seen_at timestamptz not null,
            last_seen_at timestamptz not null,
            status varchar not null,
            resolved_at timestamptz,
            resolution_basis json,
            unique(dataset_id, business_key_hash, payload_hash, first_seen_at)
        )
        """
    )
    connection.execute(
        """
        insert into research_fact_conflicts_v6
        select conflict_id, dataset_id, partition_value, business_key_hash,
               business_key_json, payload_hash, row_payload, source_name,
               source_endpoint, available_at, first_seen_at, last_seen_at,
               status, resolved_at, resolution_basis
        from research_fact_conflicts
        """
    )
    connection.execute("drop table research_fact_conflicts")
    connection.execute(
        "alter table research_fact_conflicts_v6 rename to research_fact_conflicts"
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
