from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import duckdb

from stock_analyzer.data.research_contracts import ResearchDatasetId
from stock_analyzer.storage.research_conflicts import ResearchConflictRegistry
from stock_analyzer.storage.research_parquet import sha256_file
from stock_analyzer.storage.research_schema import connect_research_warehouse
from stock_analyzer.storage.research_warehouse import ResearchWarehouse


KNOWN_ZERO_LENGTH_FINANCIAL_KEY = (
    "116770a524d690a5e628b5efb58fd3901c1394286f25ae12dc4c5b3aa7f5f2c3"
)
DAILY_REPAIR_TARGETS: dict[str, tuple[date, ...]] = {
    "margin_detail": (date(2026, 8, 11),),
    "theme_daily": (date(2026, 8, 26),),
    "suspension": (date(2026, 8, 26),),
    "industry_daily_proxy": (
        date(2026, 8, 26),
        date(2026, 9, 1),
        date(2026, 9, 2),
    ),
}
AFFECTED_DERIVED_DATES = tuple(
    date.fromisoformat(value)
    for value in (
        "2026-08-26", "2026-08-27", "2026-08-28",
        "2026-08-31", "2026-09-01", "2026-09-02",
    )
)
@dataclass(frozen=True)
class RepairBackupResult:
    backup_root: Path
    manifest_path: Path
    checksums_path: Path


def extract_financial_indicator_conflict_targets(
    duckdb_path: Path,
) -> tuple[tuple[str, date], ...]:
    # This helper is also used before the mandatory backup. Opening DuckDB
    # directly avoids triggering schema migration before that backup exists.
    with duckdb.connect(str(duckdb_path), read_only=True) as connection:
        rows = connection.execute(
            """
            select distinct cast(business_key_json as varchar)
            from research_fact_conflicts
            where dataset_id = 'financial_indicator'
              and status = 'unresolved'
            """
        ).fetchall()
    targets: set[tuple[str, date]] = set()
    for (raw_key,) in rows:
        key = json.loads(str(raw_key))
        if str(key.get("report_type")) != "indicator":
            continue
        targets.add(
            (str(key["ts_code"]), date.fromisoformat(str(key["report_period"])))
        )
    return tuple(sorted(targets))


def missing_financial_indicator_targets(
    warehouse: ResearchWarehouse,
    targets: tuple[tuple[str, date], ...],
) -> tuple[tuple[str, date], ...]:
    current = warehouse.read_current(ResearchDatasetId.FINANCIAL_INDICATOR)
    if current.empty:
        return tuple(sorted(set(targets)))
    report_type = current.get("report_type", pd.Series(index=current.index, dtype=str))
    existing = {
        (str(code), pd.Timestamp(period).date())
        for code, period in zip(
            current.loc[report_type.astype(str) == "indicator", "ts_code"],
            current.loc[report_type.astype(str) == "indicator", "report_period"],
            strict=True,
        )
    }
    return tuple(sorted(set(targets) - existing))


def missing_financial_indicator_targets_from_files(
    warehouse_root: Path,
    targets: tuple[tuple[str, date], ...],
) -> tuple[tuple[str, date], ...]:
    root = Path(warehouse_root).resolve()
    database_path = root / "research.duckdb"
    periods = {period.isoformat() for _, period in targets}
    with duckdb.connect(str(database_path), read_only=True) as connection:
        rows = connection.execute(
            "select partition_value, relative_path from research_fact_partitions "
            "where dataset_id = 'financial_indicator'"
        ).fetchall()
    paths = [
        str(root / str(relative_path))
        for partition, relative_path in rows
        if str(partition) in periods
    ]
    if not paths:
        return tuple(sorted(set(targets)))
    with duckdb.connect() as connection:
        existing_rows = connection.execute(
            "select distinct cast(ts_code as varchar), "
            "cast(cast(report_period as date) as varchar) "
            "from read_parquet(?, union_by_name=true, hive_partitioning=false) "
            "where cast(report_type as varchar) = 'indicator'",
            [paths],
        ).fetchall()
    existing = {
        (str(code), date.fromisoformat(str(period)))
        for code, period in existing_rows
    }
    return tuple(sorted(set(targets) - existing))


def create_repair_backup(
    *,
    warehouse_root: Path,
    archive_root: Path,
    financial_targets: tuple[tuple[str, date], ...],
    created_at: datetime | None = None,
) -> RepairBackupResult:
    root = Path(warehouse_root).resolve()
    database_path = root / "research.duckdb"
    if not database_path.is_file():
        raise FileNotFoundError(database_path)
    timestamp = created_at or datetime.now(timezone.utc)
    backup_root = (
        Path(archive_root)
        / "data_repairs"
        / timestamp.strftime("%Y%m%dT%H%M%SZ-research-gap-closure")
    )
    if backup_root.exists():
        raise FileExistsError(backup_root)

    fact_targets = {
        (dataset, value.isoformat())
        for dataset, values in DAILY_REPAIR_TARGETS.items()
        for value in values
    }
    fact_targets.update(
        (ResearchDatasetId.FINANCIAL_INDICATOR.value, period.isoformat())
        for _, period in financial_targets
    )
    with duckdb.connect(str(database_path)) as connection:
        connection.execute("checkpoint")
        schema = connection.execute(
            "select value from research_metadata "
            "where key = 'research_schema_version'"
        ).fetchone()
        fact_rows = connection.execute(
            "select dataset_id, partition_value, relative_path, row_count, "
            "content_hash, file_sha256 from research_fact_partitions"
        ).fetchall()
        derived_rows = connection.execute(
            "select feature_set, cast(analysis_date as varchar), relative_path, "
            "row_count, content_hash, file_sha256 from research_derived_partitions"
        ).fetchall()
        table_counts = {
            table: int(connection.execute(f"select count(*) from {table}").fetchone()[0])
            for table in (
                "research_fact_partitions", "research_fact_revisions",
                "research_data_gaps", "research_ingestion_runs",
            )
        }
        running_runs = [
            str(row[0])
            for row in connection.execute(
                "select run_id from research_ingestion_runs "
                "where status = 'running' order by run_id"
            ).fetchall()
        ]

    selected_fact_rows = [
        row
        for row in fact_rows
        if (str(row[0]), str(row[1])) in fact_targets
        or str(row[0]) == ResearchDatasetId.INDUSTRY_DAILY_PROXY.value
    ]
    derived_dates = {value.isoformat() for value in AFFECTED_DERIVED_DATES}
    selected_derived_rows = [
        row for row in derived_rows if str(row[1]) in derived_dates
    ]
    relative_paths = sorted(
        {str(row[2]) for row in (*selected_fact_rows, *selected_derived_rows)}
    )

    warehouse_backup = backup_root / "warehouse"
    warehouse_backup.mkdir(parents=True)
    copied: list[dict[str, Any]] = []
    sources = [(database_path, "research.duckdb")]
    sources.extend((root / relative, relative) for relative in relative_paths)
    for source, relative in sources:
        resolved = source.resolve()
        if resolved != database_path.resolve() and root not in resolved.parents:
            raise ValueError(f"repair target escapes warehouse root: {source}")
        if not source.is_file():
            raise FileNotFoundError(source)
        destination = warehouse_backup / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        copied.append({
            "relative_path": f"warehouse/{relative}",
            "bytes": destination.stat().st_size,
            "sha256": sha256_file(destination),
        })

    manifest = {
        "created_at": timestamp.isoformat(),
        "purpose": "2026-09-02 research data gap closure pre-write backup",
        "daily_targets": {
            key: [value.isoformat() for value in values]
            for key, values in DAILY_REPAIR_TARGETS.items()
        },
        "financial_targets": [
            {"ts_code": code, "report_period": period.isoformat()}
            for code, period in financial_targets
        ],
        "affected_derived_dates": [
            value.isoformat() for value in AFFECTED_DERIVED_DATES
        ],
        "baseline": {
            "schema_version": None if schema is None else str(schema[0]),
            "table_counts": table_counts,
            "running_run_ids": running_runs,
            "fact_partition_rows": [list(row) for row in selected_fact_rows],
            "derived_partition_rows": [list(row) for row in selected_derived_rows],
            "planned_fact_targets_without_existing_file": [
                {"dataset_id": dataset, "partition_value": partition}
                for dataset, partition in sorted(
                    fact_targets
                    - {(str(row[0]), str(row[1])) for row in selected_fact_rows}
                )
            ],
        },
        "copied_files": copied,
    }
    manifest_path = backup_root / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    checksums_path = backup_root / "checksums.sha256"
    checksums_path.write_text(
        "".join(
            f"{item['sha256']}  {item['relative_path']}\n" for item in copied
        ),
        encoding="utf-8",
    )
    return RepairBackupResult(
        backup_root=backup_root,
        manifest_path=manifest_path,
        checksums_path=checksums_path,
    )


def repair_known_zero_length_financial_revision(
    warehouse: ResearchWarehouse,
    *,
    business_key_hash: str = KNOWN_ZERO_LENGTH_FINANCIAL_KEY,
    dry_run: bool = True,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    with connect_research_warehouse(
        warehouse.duckdb_path, read_only=True
    ) as connection:
        row = connection.execute(
            """
            select partition_value, revision_no, payload_hash,
                   cast(row_payload as varchar), cast(valid_from as varchar),
                   cast(valid_to as varchar)
            from research_fact_revisions
            where dataset_id = 'financial_indicator'
              and business_key_hash = ? and revision_no = 1
              and valid_to <= valid_from
            """,
            [business_key_hash],
        ).fetchone()
    if row is None:
        return {
            "business_key_hash": business_key_hash,
            "found": False,
            "deleted_revision_rows": 0,
        }
    partition, revision_no, old_payload_hash, raw_payload, valid_from, valid_to = row
    current = warehouse.read_current(
        ResearchDatasetId.FINANCIAL_INDICATOR,
        partition_value=str(partition),
    )
    current = current[
        current["business_key_hash"].astype(str) == business_key_hash
    ]
    if len(current) != 1:
        raise ValueError(
            "known zero-length revision must have exactly one current fact"
        )
    current_row = current.iloc[0].to_dict()
    old_row = json.loads(str(raw_payload))
    if str(old_row.get("payload_hash")) != str(old_payload_hash):
        raise ValueError("revision row payload hash does not match metadata")
    business_key = (
        str(current_row["ts_code"]),
        pd.Timestamp(current_row["report_period"]).date().isoformat(),
        str(current_row["report_type"]),
    )
    result = {
        "business_key_hash": business_key_hash,
        "business_key": business_key,
        "found": True,
        "revision_no": int(revision_no),
        "valid_from": str(valid_from),
        "valid_to": str(valid_to),
        "deleted_revision_rows": 0,
    }
    if dry_run:
        return result

    ResearchConflictRegistry(warehouse.duckdb_path).record_variants(
        ResearchDatasetId.FINANCIAL_INDICATOR,
        str(partition),
        business_key=business_key,
        rows=[old_row, current_row],
        source_name="tushare",
        source_endpoint="fina_indicator",
        observed_at=observed_at or datetime.now(timezone.utc),
    )
    with connect_research_warehouse(warehouse.duckdb_path) as connection:
        count = connection.execute(
            """
            select count(*) from research_fact_revisions
            where dataset_id = 'financial_indicator'
              and business_key_hash = ? and revision_no = 1
              and valid_to <= valid_from
            """,
            [business_key_hash],
        ).fetchone()[0]
        if count != 1:
            raise ValueError("zero-length revision target changed before repair")
        connection.execute(
            """
            delete from research_fact_revisions
            where dataset_id = 'financial_indicator'
              and business_key_hash = ? and revision_no = 1
              and valid_to <= valid_from
            """,
            [business_key_hash],
        )
    result["deleted_revision_rows"] = 1
    return result


__all__ = [
    "AFFECTED_DERIVED_DATES",
    "DAILY_REPAIR_TARGETS",
    "KNOWN_ZERO_LENGTH_FINANCIAL_KEY",
    "RepairBackupResult",
    "create_repair_backup",
    "extract_financial_indicator_conflict_targets",
    "missing_financial_indicator_targets",
    "missing_financial_indicator_targets_from_files",
    "repair_known_zero_length_financial_revision",
]
