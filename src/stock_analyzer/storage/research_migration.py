from __future__ import annotations

import hashlib
import json
import re
import gc
from collections import defaultdict
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import pyarrow.parquet as pq
import pyarrow as pa
import duckdb
from pydantic import BaseModel, ConfigDict

from stock_analyzer.data.research_contracts import FactBatch, ResearchDatasetId
from stock_analyzer.storage.research_schema import connect_research_warehouse
from stock_analyzer.storage.research_warehouse import ResearchWarehouse


_VERSION_DATE = re.compile(r"market_decision-(\d{4}-\d{2}-\d{2})-")
_INTERNAL_COLUMNS = {
    "__version_id",
    "__group_id",
    "__record_type",
    "__ordinal",
    "__present_fields",
    "__json_fields",
    "__value_types",
    "record_type",
}
_VALUE_COLUMNS = ("open", "high", "low", "close", "volume", "vol", "amount")


class LegacyMarketAudit(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_root: str
    file_count: int
    physical_rows: int
    unique_business_keys: int
    duplicate_rows: int
    version_count: int
    trade_date_count: int
    conflicting_business_keys: int
    source_manifest_hash: str
    per_date: dict[str, dict[str, int]]


class LegacyMarketMigrationReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    migration_id: str
    source_audit: LegacyMarketAudit
    migrated_business_keys: int
    revision_rows: int
    partition_count: int
    target_content_hash: str
    completed_at: datetime
    already_completed: bool = False


def inspect_legacy_market(source_root: Path) -> LegacyMarketAudit:
    root = Path(source_root)
    files = _market_files(root)
    if not files:
        raise FileNotFoundError(f"no legacy equity_bar parquet files under {root}")
    manifest_items: list[tuple[str, str, int]] = []

    for path in files:
        metadata = pq.ParquetFile(path).metadata
        manifest_items.append(
            (path.relative_to(root).as_posix(), _sha256(path), metadata.num_rows)
        )
    path_strings = [str(path) for path in files]
    with duckdb.connect() as connection:
        physical_rows, unique, version_count = connection.execute(
            """
            select count(*) as physical_rows,
                   count(distinct (cast(trade_date as varchar), ts_code)) as unique_keys,
                   count(distinct __version_id) as version_count
            from read_parquet(?, union_by_name=true, hive_partitioning=false)
            """,
            [path_strings],
        ).fetchone()
        conflict_count = connection.execute(
            """
            with value_versions as (
                select cast(trade_date as varchar) as trade_date,
                       ts_code,
                       count(distinct hash(open, high, low, close,
                                           volume, amount)) as value_count
                from read_parquet(?, union_by_name=true, hive_partitioning=false)
                group by 1, 2
            )
            select count(*) from value_versions where value_count > 1
            """,
            [path_strings],
        ).fetchone()[0]
        per_date_rows = connection.execute(
            """
            select cast(trade_date as varchar) as trade_date,
                   count(*) as physical_rows,
                   count(distinct ts_code) as unique_keys
            from read_parquet(?, union_by_name=true, hive_partitioning=false)
            group by 1 order by 1
            """,
            [path_strings],
        ).fetchall()
    per_date = {
        trade_date: {
            "physical_rows": int(row_count),
            "unique_business_keys": int(unique_count),
            "duplicate_rows": int(row_count - unique_count),
        }
        for trade_date, row_count, unique_count in per_date_rows
    }
    return LegacyMarketAudit(
        source_root=str(root.resolve()),
        file_count=len(files),
        physical_rows=physical_rows,
        unique_business_keys=unique,
        duplicate_rows=physical_rows - unique,
        version_count=int(version_count),
        trade_date_count=len(per_date),
        conflicting_business_keys=int(conflict_count),
        source_manifest_hash=_stable_hash(manifest_items),
        per_date=per_date,
    )


def migrate_legacy_market(
    source_root: Path,
    warehouse: ResearchWarehouse,
    *,
    migration_id: str,
) -> LegacyMarketMigrationReport:
    existing = _stored_report(warehouse, migration_id)
    if existing is not None:
        return existing.model_copy(update={"already_completed": True})

    audit = inspect_legacy_market(source_root)
    files_by_date: dict[str, list[Path]] = defaultdict(list)
    for path in _market_files(Path(source_root)):
        files_by_date[_trade_date_from_path(path)].append(path)

    revisions_before = warehouse.revision_count(ResearchDatasetId.EQUITY_DAILY)
    for trade_date in sorted(files_by_date):
        frames: list[pd.DataFrame] = []
        for path in sorted(files_by_date[trade_date]):
            frame = _read_legacy_file(path)
            if "__version_id" not in frame:
                frame["__version_id"] = _version_from_path(path)
            frames.append(frame)
        combined = pd.concat(frames, ignore_index=True, sort=False)
        version_ids = sorted(
            set(combined["__version_id"].astype(str)),
            key=_version_sort_key,
        )
        for version_index, version_id in enumerate(version_ids):
            version_frame = combined[
                combined["__version_id"].astype(str) == version_id
            ].copy()
            version_frame = version_frame.drop_duplicates(
                subset=["trade_date", "ts_code"], keep="last"
            )
            records = []
            for row in version_frame.to_dict(orient="records"):
                record = {
                    key: _clean_scalar(value)
                    for key, value in row.items()
                    if key not in _INTERNAL_COLUMNS
                }
                records.append(record)
            run_date = _version_target_date(version_id)
            availability_date = (
                date.fromisoformat(trade_date)
                if version_index == 0
                else max(date.fromisoformat(trade_date), run_date)
            )
            available_at = _market_close_utc(availability_date)
            warehouse.commit_batch(
                FactBatch(
                    dataset_id=ResearchDatasetId.EQUITY_DAILY,
                    partition_value=trade_date,
                    source_name="legacy_formal",
                    source_endpoint="formal.market_daily.equity_bar",
                    ingestion_run_id=(
                        f"{migration_id}:{trade_date}:{_stable_hash(version_id)[:12]}"
                    ),
                    ingested_at=_market_close_utc(run_date),
                    default_available_at=available_at,
                    records=records,
                )
            )
        del combined, frames, version_frame
        gc.collect()
        pa.default_memory_pool().release_unused()

    current = warehouse.read_current(ResearchDatasetId.EQUITY_DAILY)
    migrated_keys = int(
        current[["trade_date", "ts_code"]].astype(str).drop_duplicates().shape[0]
    )
    if migrated_keys != audit.unique_business_keys:
        raise ValueError(
            "legacy migration unique-key mismatch: "
            f"source={audit.unique_business_keys} target={migrated_keys}"
        )
    target_hash = _stable_hash(
        sorted(
            zip(
                current["business_key_hash"].astype(str),
                current["payload_hash"].astype(str),
                strict=False,
            )
        )
    )
    report = LegacyMarketMigrationReport(
        migration_id=migration_id,
        source_audit=audit,
        migrated_business_keys=migrated_keys,
        revision_rows=(
            warehouse.revision_count(ResearchDatasetId.EQUITY_DAILY)
            - revisions_before
        ),
        partition_count=len(warehouse.partition_manifest(ResearchDatasetId.EQUITY_DAILY)),
        target_content_hash=target_hash,
        completed_at=datetime.now(timezone.utc),
    )
    with connect_research_warehouse(warehouse.duckdb_path) as connection:
        connection.execute(
            """
            insert into research_migrations
            (migration_id, source_root, source_manifest_hash, status,
             report_json, completed_at)
            values (?, ?, ?, 'complete', ?, ?)
            """,
            [
                migration_id,
                audit.source_root,
                audit.source_manifest_hash,
                report.model_dump_json(),
                report.completed_at,
            ],
        )
    return report


def _stored_report(
    warehouse: ResearchWarehouse,
    migration_id: str,
) -> LegacyMarketMigrationReport | None:
    with connect_research_warehouse(warehouse.duckdb_path, read_only=True) as connection:
        row = connection.execute(
            "select report_json from research_migrations where migration_id = ?",
            [migration_id],
        ).fetchone()
    if row is None:
        return None
    payload = row[0]
    if isinstance(payload, str):
        payload = json.loads(payload)
    return LegacyMarketMigrationReport.model_validate(payload)


def _market_files(root: Path) -> list[Path]:
    market_root = root / "market_daily" if (root / "market_daily").is_dir() else root
    return sorted(
        path
        for path in market_root.rglob("*.parquet")
        if "record_type=equity_bar" in path.as_posix()
    )


def _read_legacy_file(path: Path) -> pd.DataFrame:
    return pq.ParquetFile(path).read().to_pandas()


def _trade_date_from_path(path: Path) -> str:
    for part in path.parts:
        if part.startswith("trade_date="):
            return part.split("=", 1)[1]
    frame = _read_legacy_file(path)
    values = set(frame["trade_date"].astype(str))
    if len(values) != 1:
        raise ValueError(f"legacy file spans multiple trade dates: {path}")
    return values.pop()


def _version_from_path(path: Path) -> str:
    for part in path.parts:
        if part.startswith("version_id="):
            return part.split("=", 1)[1]
    raise ValueError(f"version id missing from path: {path}")


def _version_target_date(version_id: str) -> date:
    match = _VERSION_DATE.search(version_id)
    if match is None:
        return date(1970, 1, 1)
    return date.fromisoformat(match.group(1))


def _version_sort_key(version_id: str) -> tuple[date, str]:
    return (_version_target_date(version_id), version_id)


def _market_close_utc(value: date) -> datetime:
    local = datetime.combine(value, time(15, 1), tzinfo=ZoneInfo("Asia/Shanghai"))
    return local.astimezone(timezone.utc)


def _value_hash(row: dict[str, Any]) -> str:
    payload = {
        field: _clean_scalar(row.get(field))
        for field in _VALUE_COLUMNS
        if field in row
    }
    return _stable_hash(payload)


def _clean_scalar(value: Any) -> Any:
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    if pd.isna(value):
        return None
    return value


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "LegacyMarketAudit",
    "LegacyMarketMigrationReport",
    "inspect_legacy_market",
    "migrate_legacy_market",
]
