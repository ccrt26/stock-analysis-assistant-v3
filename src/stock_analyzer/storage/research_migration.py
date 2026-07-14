from __future__ import annotations

import hashlib
import json
import re
import gc
import shutil
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


class LegacyMarketMigrationAudit(BaseModel):
    model_config = ConfigDict(frozen=True)

    migration_id: str
    passed: bool
    source_manifest_matches: bool
    source_business_keys: int
    target_business_keys: int
    missing_target_keys: int
    extra_target_keys: int
    value_mismatches: int


class LegacyMarketCleanupFile(BaseModel):
    model_config = ConfigDict(frozen=True)

    relative_path: str
    sha256: str
    size: int


class LegacyMarketCleanupManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    migration_id: str
    source_root: str
    source_manifest_hash: str
    strict_audit: LegacyMarketMigrationAudit
    record_types: tuple[str, ...]
    replacement_datasets: dict[str, tuple[str, ...]]
    files: tuple[LegacyMarketCleanupFile, ...]
    total_bytes: int
    generated_at: datetime


class LegacyMarketCleanupReceipt(BaseModel):
    model_config = ConfigDict(frozen=True)

    migration_id: str
    source_manifest_hash: str
    files_deleted: int
    bytes_deleted: int
    source_removed: bool
    completed_at: datetime


_LEGACY_RECORD_REPLACEMENTS: dict[str, tuple[ResearchDatasetId, ...]] = {
    "board_bar": (
        ResearchDatasetId.INDUSTRY_DAILY,
        ResearchDatasetId.THEME_DAILY,
    ),
    "calendar": (ResearchDatasetId.TRADE_CALENDAR,),
    "company_profile": (ResearchDatasetId.COMPANY_PROFILE,),
    "daily_basic": (ResearchDatasetId.DAILY_BASIC,),
    "equity_bar": (ResearchDatasetId.EQUITY_DAILY,),
    "express": (ResearchDatasetId.EARNINGS_EXPRESS,),
    "financial_summary": (
        ResearchDatasetId.INCOME_STATEMENT,
        ResearchDatasetId.BALANCE_SHEET,
        ResearchDatasetId.CASH_FLOW,
        ResearchDatasetId.FINANCIAL_INDICATOR,
    ),
    "forecast": (ResearchDatasetId.EARNINGS_FORECAST,),
    "index_bar": (ResearchDatasetId.INDEX_DAILY,),
    "industry_mapping": (ResearchDatasetId.INDUSTRY_MEMBER,),
    "main_business": (ResearchDatasetId.MAIN_BUSINESS,),
    "official_event": (ResearchDatasetId.ANNOUNCEMENT,),
    "security": (ResearchDatasetId.SECURITY_MASTER,),
}


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


def audit_legacy_market_migration(
    source_root: Path,
    warehouse: ResearchWarehouse,
    *,
    migration_id: str,
    strict_hashes: bool = False,
    cleanup_manifest: LegacyMarketCleanupManifest | None = None,
    cleanup_receipt: LegacyMarketCleanupReceipt | None = None,
) -> LegacyMarketMigrationAudit:
    stored = _stored_report(warehouse, migration_id)
    if stored is None:
        raise ValueError(f"migration is not complete: {migration_id}")
    if not _market_files(Path(source_root)):
        return _audit_removed_legacy_market(
            source_root,
            warehouse,
            stored=stored,
            migration_id=migration_id,
            cleanup_manifest=cleanup_manifest,
            cleanup_receipt=cleanup_receipt,
        )
    source_audit = inspect_legacy_market(source_root)
    manifest_matches = (
        source_audit.source_manifest_hash
        == stored.source_audit.source_manifest_hash
    )
    source_files = _market_files(Path(source_root))
    source_dates = sorted(source_audit.per_date)
    target_manifest = warehouse.partition_manifest(ResearchDatasetId.EQUITY_DAILY)
    target_manifest = target_manifest[
        target_manifest["partition_value"].astype(str).isin(source_dates)
    ]
    target_files = [
        warehouse.root / str(value)
        for value in target_manifest["relative_path"].tolist()
    ]
    if not target_files or any(not path.is_file() for path in target_files):
        target_business_keys = int(target_manifest["row_count"].sum())
        missing = max(0, source_audit.unique_business_keys - target_business_keys)
        extra = max(0, target_business_keys - source_audit.unique_business_keys)
        mismatches = 0
    else:
        source_volume = _first_available_column(source_files, ("volume", "vol"))
        target_volume = _first_available_column(target_files, ("volume", "vol"))
        source_paths = [str(path) for path in source_files]
        target_paths = [str(path) for path in target_files]
        with duckdb.connect() as connection:
            result = connection.execute(
                f"""
                with source_ranked as (
                    select cast(trade_date as varchar) as trade_date,
                           cast(ts_code as varchar) as ts_code,
                           try_cast(open as double) as open,
                           try_cast(high as double) as high,
                           try_cast(low as double) as low,
                           try_cast(close as double) as close,
                           try_cast({source_volume} as double) as volume,
                           try_cast(amount as double) as amount,
                           row_number() over (
                               partition by cast(trade_date as varchar), ts_code
                               order by cast(__version_id as varchar) desc
                           ) as ordinal
                    from read_parquet(?, union_by_name=true, hive_partitioning=false)
                ),
                source_current as (
                    select * exclude ordinal from source_ranked where ordinal = 1
                ),
                target_current as (
                    select cast(trade_date as varchar) as trade_date,
                           cast(ts_code as varchar) as ts_code,
                           try_cast(open as double) as open,
                           try_cast(high as double) as high,
                           try_cast(low as double) as low,
                           try_cast(close as double) as close,
                           try_cast({target_volume} as double) as volume,
                           try_cast(amount as double) as amount
                    from read_parquet(?, union_by_name=true, hive_partitioning=false)
                ),
                compared as (
                    select s.trade_date as source_date,
                           s.ts_code as source_code,
                           t.trade_date as target_date,
                           t.ts_code as target_code,
                           case when s.trade_date is not null and t.trade_date is not null
                                     and (s.open is distinct from t.open
                                       or s.high is distinct from t.high
                                       or s.low is distinct from t.low
                                       or s.close is distinct from t.close
                                       or s.volume is distinct from t.volume
                                       or s.amount is distinct from t.amount)
                                then 1 else 0 end as differs
                    from source_current s
                    full outer join target_current t
                      on s.trade_date = t.trade_date and s.ts_code = t.ts_code
                )
                select
                    (select count(*) from source_current),
                    (select count(*) from target_current),
                    sum(case when target_date is null then 1 else 0 end),
                    sum(case when source_date is null then 1 else 0 end),
                    sum(differs)
                from compared
                """,
                [source_paths, target_paths],
            ).fetchone()
        target_business_keys = int(result[1])
        missing = int(result[2] or 0)
        extra = int(result[3] or 0)
        mismatches = int(result[4] or 0)
    passed = (
        (manifest_matches or not strict_hashes)
        and source_audit.unique_business_keys == target_business_keys
        and missing == 0
        and extra == 0
        and mismatches == 0
    )
    return LegacyMarketMigrationAudit(
        migration_id=migration_id,
        passed=passed,
        source_manifest_matches=manifest_matches,
        source_business_keys=source_audit.unique_business_keys,
        target_business_keys=target_business_keys,
        missing_target_keys=missing,
        extra_target_keys=extra,
        value_mismatches=mismatches,
    )


def _audit_removed_legacy_market(
    source_root: Path,
    warehouse: ResearchWarehouse,
    *,
    stored: LegacyMarketMigrationReport,
    migration_id: str,
    cleanup_manifest: LegacyMarketCleanupManifest | None,
    cleanup_receipt: LegacyMarketCleanupReceipt | None,
) -> LegacyMarketMigrationAudit:
    if cleanup_manifest is None or cleanup_receipt is None:
        raise FileNotFoundError(
            "legacy source was removed; cleanup manifest and receipt are required"
        )
    embedded = cleanup_manifest.strict_audit
    source = Path(source_root).resolve()
    evidence_matches = bool(
        cleanup_manifest.migration_id == migration_id
        and cleanup_receipt.migration_id == migration_id
        and Path(cleanup_manifest.source_root).resolve() == source
        and cleanup_receipt.source_manifest_hash
        == cleanup_manifest.source_manifest_hash
        and cleanup_receipt.files_deleted == len(cleanup_manifest.files)
        and cleanup_receipt.bytes_deleted == cleanup_manifest.total_bytes
        and cleanup_receipt.source_removed
        and not source.exists()
        and embedded.migration_id == migration_id
        and embedded.passed
        and embedded.source_manifest_matches
        and embedded.source_business_keys
        == stored.source_audit.unique_business_keys
    )
    source_dates = set(stored.source_audit.per_date)
    target_manifest = warehouse.partition_manifest(ResearchDatasetId.EQUITY_DAILY)
    target_manifest = target_manifest[
        target_manifest["partition_value"].astype(str).isin(source_dates)
    ]
    integrity_failures = 0
    target_paths: list[str] = []
    for row in target_manifest.to_dict(orient="records"):
        path = warehouse.root / str(row["relative_path"])
        if not path.is_file():
            integrity_failures += 1
            continue
        target_paths.append(str(path))
        if pq.ParquetFile(path).metadata.num_rows != int(row["row_count"]):
            integrity_failures += 1
        if _sha256(path) != str(row["file_sha256"]):
            integrity_failures += 1
    if len(target_manifest) != len(source_dates):
        integrity_failures += abs(len(source_dates) - len(target_manifest))
    target_content_mismatch = 1
    if target_paths and len(target_paths) == len(target_manifest):
        with duckdb.connect() as connection:
            target_rows = connection.execute(
                """
                select cast(business_key_hash as varchar),
                       cast(payload_hash as varchar)
                from read_parquet(?, union_by_name=true, hive_partitioning=false)
                """,
                [target_paths],
            ).fetchall()
        target_business_keys = len(target_rows)
        target_content_hash = _stable_hash(sorted(target_rows))
        target_content_mismatch = int(
            target_content_hash != stored.target_content_hash
        )
    else:
        target_business_keys = int(target_manifest["row_count"].sum())
    source_business_keys = stored.source_audit.unique_business_keys
    missing = max(0, source_business_keys - target_business_keys)
    extra = max(0, target_business_keys - source_business_keys)
    mismatches = (
        embedded.value_mismatches
        + integrity_failures
        + target_content_mismatch
    )
    return LegacyMarketMigrationAudit(
        migration_id=migration_id,
        passed=bool(
            evidence_matches
            and missing == 0
            and extra == 0
            and mismatches == 0
        ),
        source_manifest_matches=evidence_matches,
        source_business_keys=source_business_keys,
        target_business_keys=target_business_keys,
        missing_target_keys=missing,
        extra_target_keys=extra,
        value_mismatches=mismatches,
    )


def build_legacy_market_cleanup_manifest(
    source_root: Path,
    warehouse: ResearchWarehouse,
    *,
    migration_id: str,
) -> LegacyMarketCleanupManifest:
    root = Path(source_root).resolve()
    expected = (warehouse.root / "parquet" / "formal").resolve()
    if root != expected:
        raise ValueError(
            f"legacy cleanup source must be the managed formal path: {expected}"
        )
    strict_audit = audit_legacy_market_migration(
        root,
        warehouse,
        migration_id=migration_id,
        strict_hashes=True,
    )
    if not strict_audit.passed:
        raise ValueError("legacy market migration is not strictly auditable")

    parquet_files = sorted(root.rglob("*.parquet"))
    record_types = tuple(sorted({_record_type_from_path(path) for path in parquet_files}))
    unknown = sorted(set(record_types) - set(_LEGACY_RECORD_REPLACEMENTS))
    if unknown:
        raise ValueError(f"legacy record types lack replacements: {', '.join(unknown)}")
    replacements: dict[str, tuple[str, ...]] = {}
    for record_type in record_types:
        datasets = _LEGACY_RECORD_REPLACEMENTS[record_type]
        missing = [
            dataset.value
            for dataset in datasets
            if warehouse.partition_manifest(dataset).empty
        ]
        if missing:
            raise ValueError(
                f"legacy {record_type} replacements are empty: {', '.join(missing)}"
            )
        replacements[record_type] = tuple(dataset.value for dataset in datasets)

    entries = tuple(
        LegacyMarketCleanupFile(
            relative_path=path.relative_to(root).as_posix(),
            sha256=_sha256(path),
            size=path.stat().st_size,
        )
        for path in sorted(path for path in root.rglob("*") if path.is_file())
    )
    source_manifest_hash = _stable_hash(
        [(item.relative_path, item.sha256, item.size) for item in entries]
    )
    return LegacyMarketCleanupManifest(
        migration_id=migration_id,
        source_root=str(root),
        source_manifest_hash=source_manifest_hash,
        strict_audit=strict_audit,
        record_types=record_types,
        replacement_datasets=replacements,
        files=entries,
        total_bytes=sum(item.size for item in entries),
        generated_at=datetime.now(timezone.utc),
    )


def execute_legacy_market_cleanup(
    manifest: LegacyMarketCleanupManifest,
    warehouse: ResearchWarehouse,
) -> LegacyMarketCleanupReceipt:
    current = build_legacy_market_cleanup_manifest(
        Path(manifest.source_root),
        warehouse,
        migration_id=manifest.migration_id,
    )
    if (
        current.source_manifest_hash != manifest.source_manifest_hash
        or current.files != manifest.files
    ):
        raise ValueError("source changed after cleanup manifest")

    source = Path(manifest.source_root)
    staged = (
        warehouse.staging_root
        / "legacy-cleanup"
        / manifest.source_manifest_hash
    )
    if staged.exists():
        raise FileExistsError(f"legacy cleanup staging already exists: {staged}")
    staged.parent.mkdir(parents=True, exist_ok=True)
    source.replace(staged)
    try:
        shutil.rmtree(staged)
    except Exception:
        if staged.exists() and not source.exists():
            source.parent.mkdir(parents=True, exist_ok=True)
            staged.replace(source)
        raise
    return LegacyMarketCleanupReceipt(
        migration_id=manifest.migration_id,
        source_manifest_hash=manifest.source_manifest_hash,
        files_deleted=len(manifest.files),
        bytes_deleted=manifest.total_bytes,
        source_removed=not source.exists(),
        completed_at=datetime.now(timezone.utc),
    )


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


def _record_type_from_path(path: Path) -> str:
    for part in path.parts:
        if part.startswith("record_type="):
            return part.split("=", 1)[1]
    raise ValueError(f"legacy parquet lacks record_type partition: {path}")


def _first_available_column(files: list[Path], candidates: tuple[str, ...]) -> str:
    names: set[str] = set()
    for path in files:
        names.update(pq.ParquetFile(path).schema_arrow.names)
        if any(candidate in names for candidate in candidates):
            break
    for candidate in candidates:
        if candidate in names:
            return candidate
    raise ValueError(f"missing required columns: {', '.join(candidates)}")


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
    "LegacyMarketCleanupFile",
    "LegacyMarketCleanupManifest",
    "LegacyMarketCleanupReceipt",
    "LegacyMarketAudit",
    "LegacyMarketMigrationReport",
    "LegacyMarketMigrationAudit",
    "audit_legacy_market_migration",
    "build_legacy_market_cleanup_manifest",
    "execute_legacy_market_cleanup",
    "inspect_legacy_market",
    "migrate_legacy_market",
]
