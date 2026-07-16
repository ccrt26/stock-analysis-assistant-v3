from __future__ import annotations

import hashlib
import json
import shutil
from collections import defaultdict
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
from pydantic import BaseModel

from stock_analyzer.data.research_contracts import (
    AvailabilityPrecision,
    DatasetContract,
    ResearchDatasetId,
    research_contract_registry,
)
from stock_analyzer.storage.research_parquet import (
    write_staged_parquet,
)
from stock_analyzer.storage.research_schema import connect_research_warehouse
from stock_analyzer.storage.research_warehouse import ResearchWarehouse


_MARKET_TIMEZONE = ZoneInfo("Asia/Shanghai")
_RECONSTRUCT_DATASETS = {
    ResearchDatasetId.TRADE_CALENDAR,
    ResearchDatasetId.INDUSTRY_DAILY,
    ResearchDatasetId.THEME_DAILY,
}
_INGESTION_CUTOFF_DATASETS = {
    ResearchDatasetId.SECURITY_MASTER,
    ResearchDatasetId.COMPANY_PROFILE,
    ResearchDatasetId.PLEDGE,
}
_DATE_ONLY_DISCLOSURE_DATASETS = {
    ResearchDatasetId.INCOME_STATEMENT,
    ResearchDatasetId.BALANCE_SHEET,
    ResearchDatasetId.CASH_FLOW,
    ResearchDatasetId.FINANCIAL_INDICATOR,
    ResearchDatasetId.MAIN_BUSINESS,
    ResearchDatasetId.EARNINGS_FORECAST,
    ResearchDatasetId.EARNINGS_EXPRESS,
    ResearchDatasetId.HOLDER_TRADE,
    ResearchDatasetId.SHARE_FLOAT,
    ResearchDatasetId.REPURCHASE,
}
_MIGRATION_DATASETS = (
    _RECONSTRUCT_DATASETS
    | _INGESTION_CUTOFF_DATASETS
    | _DATE_ONLY_DISCLOSURE_DATASETS
)
_GOVERNANCE_FIELDS = {
    "source_name",
    "source_endpoint",
    "source_record_id",
    "source_updated_at",
    "available_at",
    "availability_precision",
    "ingested_at",
    "ingestion_run_id",
    "payload_hash",
    "business_key_hash",
    "quality_status",
    "revision_no",
}


class TemporalDatasetAudit(BaseModel):
    dataset_id: str
    business_time_field: str | None
    availability_policy: str
    revision_availability_policy: str
    strict_replay_level: str
    partition_count: int
    row_count: int
    revision_count: int
    min_business_time: str | None = None
    max_business_time: str | None = None
    min_available_at: datetime | None = None
    max_available_at: datetime | None = None
    min_ingested_at: datetime | None = None
    max_ingested_at: datetime | None = None


class TemporalMigrationReport(BaseModel):
    migration_id: str
    source_manifest_hash: str
    changed_datasets: tuple[str, ...]
    partition_count: int
    row_count: int
    revision_count: int
    conservation_passed: bool
    already_completed: bool = False
    before_audit: tuple[TemporalDatasetAudit, ...]
    after_audit: tuple[TemporalDatasetAudit, ...]


def audit_research_time_semantics(
    warehouse: ResearchWarehouse,
) -> tuple[TemporalDatasetAudit, ...]:
    audits: list[TemporalDatasetAudit] = []
    for dataset, contract in research_contract_registry().items():
        manifest = warehouse.partition_manifest(dataset)
        if manifest.empty:
            audits.append(
                _empty_audit(dataset, contract, warehouse.revision_count(dataset))
            )
            continue
        paths = [warehouse.root / str(value) for value in manifest["relative_path"]]
        business_field = _audit_business_field(contract, paths[0])
        aggregates = _audit_file_aggregates(paths, business_field)
        audits.append(
            TemporalDatasetAudit(
                dataset_id=dataset.value,
                business_time_field=business_field,
                availability_policy=contract.availability_policy.value,
                revision_availability_policy=(
                    contract.revision_availability_policy.value
                ),
                strict_replay_level=contract.strict_replay_level.value,
                partition_count=len(manifest),
                row_count=int(manifest["row_count"].sum()),
                revision_count=warehouse.revision_count(dataset),
                min_business_time=aggregates[0],
                max_business_time=aggregates[1],
                min_available_at=_optional_utc(aggregates[2]),
                max_available_at=_optional_utc(aggregates[3]),
                min_ingested_at=_optional_utc(aggregates[4]),
                max_ingested_at=_optional_utc(aggregates[5]),
            )
        )
    return tuple(audits)


def migrate_research_time_semantics(
    warehouse: ResearchWarehouse,
    *,
    migration_id: str,
) -> TemporalMigrationReport:
    cleaned_id = migration_id.strip()
    if not cleaned_id:
        raise ValueError("migration_id must not be blank")
    completed = _completed_report(warehouse, cleaned_id)
    if completed is not None:
        return completed.model_copy(update={"already_completed": True})

    before = audit_research_time_semantics(warehouse)
    source_manifest_hash = _manifest_hash(warehouse)
    changed: list[str] = []
    for dataset in ResearchDatasetId:
        if dataset not in _MIGRATION_DATASETS:
            continue
        if _migrate_dataset(warehouse, dataset, cleaned_id):
            changed.append(dataset.value)
    after = audit_research_time_semantics(warehouse)
    _assert_audit_conservation(before, after)
    report = TemporalMigrationReport(
        migration_id=cleaned_id,
        source_manifest_hash=source_manifest_hash,
        changed_datasets=tuple(changed),
        partition_count=sum(item.partition_count for item in after),
        row_count=sum(item.row_count for item in after),
        revision_count=sum(item.revision_count for item in after),
        conservation_passed=True,
        before_audit=before,
        after_audit=after,
    )
    _record_completed_migration(warehouse, report)
    return report


def _migrate_dataset(
    warehouse: ResearchWarehouse,
    dataset: ResearchDatasetId,
    migration_id: str,
) -> bool:
    manifest = warehouse.partition_manifest(dataset)
    if manifest.empty:
        return False
    revisions = _revision_records(warehouse, dataset)
    if dataset in _RECONSTRUCT_DATASETS and revisions:
        raise ValueError(
            f"{dataset.value} has revisions; deterministic initial-time "
            "migration refuses to backdate later versions"
        )

    stage_root = (
        warehouse.staging_root
        / "time-semantics"
        / migration_id
        / dataset.value
    )
    shutil.rmtree(stage_root, ignore_errors=True)
    staged_dataset = stage_root / "next"
    backup_dataset = stage_root / "previous"
    target_dataset = warehouse.facts_root / dataset.value
    metadata_updates: list[dict[str, Any]] = []
    original_partition_updates: list[dict[str, Any]] = []
    current_by_key: dict[str, dict[str, Any]] = {}
    changed = False

    try:
        for metadata in manifest.to_dict(orient="records"):
            source_path = warehouse.root / str(metadata["relative_path"])
            before_frame = pd.read_parquet(source_path)
            after_frame = _transform_frame(dataset, before_frame)
            _assert_frame_conservation(dataset, before_frame, after_frame)
            changed = changed or not _temporal_columns_equal(
                before_frame, after_frame
            )
            for row in after_frame.to_dict(orient="records"):
                current_by_key[str(row["business_key_hash"])] = row
            staged_path = staged_dataset / source_path.relative_to(target_dataset)
            file_sha256 = write_staged_parquet(staged_path, after_frame)
            available = pd.to_datetime(
                after_frame["available_at"], utc=True, errors="raise"
            )
            metadata_updates.append(
                {
                    "partition_value": str(metadata["partition_value"]),
                    "file_sha256": file_sha256,
                    "min_available_at": available.min().to_pydatetime(),
                    "max_available_at": available.max().to_pydatetime(),
                }
            )
            original_partition_updates.append(
                {
                    "partition_value": str(metadata["partition_value"]),
                    "file_sha256": str(metadata["file_sha256"]),
                    "min_available_at": _optional_utc(
                        metadata["min_available_at"]
                    ),
                    "max_available_at": _optional_utc(
                        metadata["max_available_at"]
                    ),
                }
            )

        revision_updates, revision_changed = _transform_revisions(
            dataset,
            revisions,
            current_by_key,
        )
        changed = changed or revision_changed
        if not changed:
            shutil.rmtree(stage_root, ignore_errors=True)
            return False

        if not target_dataset.is_dir():
            raise FileNotFoundError(target_dataset)
        target_dataset.replace(backup_dataset)
        staged_dataset.replace(target_dataset)
        try:
            _update_dataset_metadata(
                warehouse,
                dataset,
                metadata_updates,
                revision_updates,
            )
        except Exception:
            failed_dataset = stage_root / "failed-next"
            if target_dataset.exists():
                target_dataset.replace(failed_dataset)
            backup_dataset.replace(target_dataset)
            raise
        try:
            _verify_promoted_dataset(warehouse, dataset, metadata_updates)
        except Exception:
            failed_dataset = stage_root / "failed-verification"
            target_dataset.replace(failed_dataset)
            backup_dataset.replace(target_dataset)
            _update_dataset_metadata(
                warehouse,
                dataset,
                original_partition_updates,
                revisions,
            )
            raise
        shutil.rmtree(backup_dataset, ignore_errors=True)
        return True
    finally:
        shutil.rmtree(stage_root, ignore_errors=True)


def _transform_frame(
    dataset: ResearchDatasetId,
    frame: pd.DataFrame,
) -> pd.DataFrame:
    result = frame.copy()
    if result.empty:
        return result
    if dataset is ResearchDatasetId.TRADE_CALENDAR:
        result["available_at"] = result["cal_date"].map(_post_close)
        result["availability_precision"] = (
            AvailabilityPrecision.INFERRED_FROM_ENDPOINT_POLICY.value
        )
    elif dataset in {
        ResearchDatasetId.INDUSTRY_DAILY,
        ResearchDatasetId.THEME_DAILY,
    }:
        result["available_at"] = result["trade_date"].map(_post_close)
        result["availability_precision"] = (
            AvailabilityPrecision.INFERRED_FROM_ENDPOINT_POLICY.value
        )
    elif dataset in _INGESTION_CUTOFF_DATASETS:
        result["available_at"] = pd.to_datetime(
            result["ingested_at"], utc=True, errors="raise"
        )
        result["availability_precision"] = (
            AvailabilityPrecision.INGESTION_CUTOFF.value
        )
    elif dataset in _DATE_ONLY_DISCLOSURE_DATASETS:
        result["availability_precision"] = (
            AvailabilityPrecision.DATE_CONSERVATIVE.value
        )
        if dataset is ResearchDatasetId.MAIN_BUSINESS:
            limitation = result.get(
                "availability_limitation",
                pd.Series(index=result.index, dtype=object),
            ).astype("string")
            ingestion_only = limitation.str.contains(
                "usable only from ingestion cutoff",
                na=False,
            )
            result.loc[ingestion_only, "available_at"] = pd.to_datetime(
                result.loc[ingestion_only, "ingested_at"],
                utc=True,
                errors="raise",
            )
            result.loc[ingestion_only, "availability_precision"] = (
                AvailabilityPrecision.INGESTION_CUTOFF.value
            )
    return result


def _transform_revisions(
    dataset: ResearchDatasetId,
    revisions: list[dict[str, Any]],
    current_by_key: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], bool]:
    if not revisions:
        return [], False
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    changed = False
    for revision in revisions:
        payload = dict(revision["row_payload"])
        transformed = _transform_frame(dataset, pd.DataFrame([payload])).iloc[0]
        transformed_payload = _json_record(transformed.to_dict())
        if _business_payload_digest(payload) != _business_payload_digest(
            transformed_payload
        ):
            raise ValueError(f"revision business payload changed for {dataset.value}")
        changed = changed or not _payload_temporal_equal(payload, transformed_payload)
        prepared = dict(revision)
        prepared["row_payload"] = transformed_payload
        grouped[str(revision["business_key_hash"])].append(prepared)

    updates: list[dict[str, Any]] = []
    for key_hash, versions in grouped.items():
        versions.sort(key=lambda item: int(item["revision_no"]))
        current = current_by_key.get(key_hash)
        if current is None:
            raise ValueError(
                f"revision current row missing for {dataset.value}:{key_hash}"
            )
        for index, revision in enumerate(versions):
            following = (
                versions[index + 1]["row_payload"]
                if index + 1 < len(versions)
                else current
            )
            valid_from = _as_utc(revision["row_payload"]["available_at"])
            valid_to = _as_utc(following["available_at"])
            if valid_to < valid_from:
                raise ValueError(
                    f"revision availability regressed for {dataset.value}:{key_hash}"
                )
            prepared = dict(revision)
            prepared["valid_from"] = valid_from
            prepared["valid_to"] = valid_to
            changed = changed or _as_utc(revision["valid_from"]) != valid_from
            changed = changed or _as_utc(revision["valid_to"]) != valid_to
            updates.append(prepared)
    return updates, changed


def _update_dataset_metadata(
    warehouse: ResearchWarehouse,
    dataset: ResearchDatasetId,
    partition_updates: list[dict[str, Any]],
    revision_updates: list[dict[str, Any]],
) -> None:
    with connect_research_warehouse(warehouse.duckdb_path) as connection:
        connection.begin()
        try:
            for update in partition_updates:
                connection.execute(
                    """
                    update research_fact_partitions
                    set file_sha256 = ?, min_available_at = ?,
                        max_available_at = ?, committed_at = now()
                    where dataset_id = ? and partition_value = ?
                    """,
                    [
                        update["file_sha256"],
                        update["min_available_at"],
                        update["max_available_at"],
                        dataset.value,
                        update["partition_value"],
                    ],
                )
            for update in revision_updates:
                connection.execute(
                    """
                    update research_fact_revisions
                    set row_payload = ?, valid_from = ?, valid_to = ?
                    where dataset_id = ? and business_key_hash = ?
                      and revision_no = ?
                    """,
                    [
                        json.dumps(
                            update["row_payload"],
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        update["valid_from"],
                        update["valid_to"],
                        dataset.value,
                        update["business_key_hash"],
                        update["revision_no"],
                    ],
                )
        except Exception:
            connection.rollback()
            raise
        connection.commit()


def _revision_records(
    warehouse: ResearchWarehouse,
    dataset: ResearchDatasetId,
) -> list[dict[str, Any]]:
    with connect_research_warehouse(
        warehouse.duckdb_path, read_only=True
    ) as connection:
        rows = connection.execute(
            """
            select business_key_hash, revision_no, partition_value, row_payload,
                   cast(valid_from as varchar), cast(valid_to as varchar)
            from research_fact_revisions
            where dataset_id = ?
            order by business_key_hash, revision_no
            """,
            [dataset.value],
        ).fetchall()
    return [
        {
            "business_key_hash": str(row[0]),
            "revision_no": int(row[1]),
            "partition_value": str(row[2]),
            "row_payload": _json_object(row[3]),
            "valid_from": _as_utc(row[4]),
            "valid_to": _as_utc(row[5]),
        }
        for row in rows
    ]


def _assert_frame_conservation(
    dataset: ResearchDatasetId,
    before: pd.DataFrame,
    after: pd.DataFrame,
) -> None:
    if len(before) != len(after):
        raise ValueError(f"row count changed for {dataset.value}")
    for field in ("business_key_hash", "payload_hash", "revision_no"):
        if sorted(before[field].astype(str)) != sorted(after[field].astype(str)):
            raise ValueError(f"{field} changed for {dataset.value}")
    if _frame_business_digest(before) != _frame_business_digest(after):
        raise ValueError(f"business fields changed for {dataset.value}")


def _verify_promoted_dataset(
    warehouse: ResearchWarehouse,
    dataset: ResearchDatasetId,
    updates: list[dict[str, Any]],
) -> None:
    manifest = warehouse.validated_partition_manifest(
        dataset,
        [item["partition_value"] for item in updates],
    )
    expected = {item["partition_value"]: item["file_sha256"] for item in updates}
    actual = dict(
        zip(
            manifest["partition_value"].astype(str),
            manifest["file_sha256"].astype(str),
            strict=True,
        )
    )
    if actual != expected:
        raise ValueError(f"promoted manifest mismatch for {dataset.value}")


def _temporal_columns_equal(before: pd.DataFrame, after: pd.DataFrame) -> bool:
    before_indexed = before.set_index("business_key_hash")
    after_indexed = after.set_index("business_key_hash")
    if set(before_indexed.index.astype(str)) != set(after_indexed.index.astype(str)):
        return False
    for key in before_indexed.index:
        if _as_utc(before_indexed.loc[key, "available_at"]) != _as_utc(
            after_indexed.loc[key, "available_at"]
        ):
            return False
        if str(before_indexed.loc[key, "availability_precision"]) != str(
            after_indexed.loc[key, "availability_precision"]
        ):
            return False
    return True


def _payload_temporal_equal(before: dict[str, Any], after: dict[str, Any]) -> bool:
    return (
        _as_utc(before["available_at"]) == _as_utc(after["available_at"])
        and str(before.get("availability_precision"))
        == str(after.get("availability_precision"))
    )


def _post_close(value: Any) -> datetime:
    business_date = pd.Timestamp(value).date()
    return datetime.combine(
        business_date,
        time(15, 1),
        tzinfo=_MARKET_TIMEZONE,
    ).astimezone(timezone.utc)


def _audit_business_field(contract: DatasetContract, path: Path) -> str | None:
    columns = set(pq.read_schema(path).names)
    candidates = (
        contract.business_time_field,
        "report_period",
        "announcement_time",
        "ann_date",
        "end_date",
        "trade_date",
        "valid_from",
        "cal_date",
    )
    return next((field for field in candidates if field and field in columns), None)


def _audit_file_aggregates(
    paths: list[Path],
    business_field: str | None,
) -> tuple[Any, Any, Any, Any, Any, Any]:
    minimum_business: str | None = None
    maximum_business: str | None = None
    minimum_available: datetime | None = None
    maximum_available: datetime | None = None
    minimum_ingested: datetime | None = None
    maximum_ingested: datetime | None = None
    columns = ["available_at", "ingested_at"]
    if business_field is not None:
        columns.append(business_field)
    for path in paths:
        table = pq.ParquetFile(path).read(columns=columns)
        if business_field is not None:
            business_bounds = pc.min_max(
                pc.cast(table[business_field], pa.string())
            ).as_py()
            minimum_business = _minimum(
                minimum_business, business_bounds.get("min")
            )
            maximum_business = _maximum(
                maximum_business, business_bounds.get("max")
            )
        available_bounds = pc.min_max(table["available_at"]).as_py()
        ingested_bounds = pc.min_max(table["ingested_at"]).as_py()
        minimum_available = _minimum(
            minimum_available, available_bounds.get("min")
        )
        maximum_available = _maximum(
            maximum_available, available_bounds.get("max")
        )
        minimum_ingested = _minimum(
            minimum_ingested, ingested_bounds.get("min")
        )
        maximum_ingested = _maximum(
            maximum_ingested, ingested_bounds.get("max")
        )
    return (
        minimum_business,
        maximum_business,
        minimum_available,
        maximum_available,
        minimum_ingested,
        maximum_ingested,
    )


def _minimum(current: Any, candidate: Any) -> Any:
    if candidate is None:
        return current
    return candidate if current is None or candidate < current else current


def _maximum(current: Any, candidate: Any) -> Any:
    if candidate is None:
        return current
    return candidate if current is None or candidate > current else current


def _empty_audit(
    dataset: ResearchDatasetId,
    contract: DatasetContract,
    revision_count: int,
) -> TemporalDatasetAudit:
    return TemporalDatasetAudit(
        dataset_id=dataset.value,
        business_time_field=contract.business_time_field,
        availability_policy=contract.availability_policy.value,
        revision_availability_policy=contract.revision_availability_policy.value,
        strict_replay_level=contract.strict_replay_level.value,
        partition_count=0,
        row_count=0,
        revision_count=revision_count,
    )


def _manifest_hash(warehouse: ResearchWarehouse) -> str:
    rows: list[tuple[str, str, int, str, str]] = []
    for dataset in ResearchDatasetId:
        manifest = warehouse.partition_manifest(dataset)
        rows.extend(
            (
                dataset.value,
                str(row["partition_value"]),
                int(row["row_count"]),
                str(row["content_hash"]),
                str(row["file_sha256"]),
            )
            for row in manifest.to_dict(orient="records")
        )
    return _stable_hash(sorted(rows))


def _completed_report(
    warehouse: ResearchWarehouse,
    migration_id: str,
) -> TemporalMigrationReport | None:
    with connect_research_warehouse(
        warehouse.duckdb_path, read_only=True
    ) as connection:
        row = connection.execute(
            "select report_json from research_migrations where migration_id = ?",
            [migration_id],
        ).fetchone()
    if row is None:
        return None
    return TemporalMigrationReport.model_validate(_json_object(row[0]))


def _record_completed_migration(
    warehouse: ResearchWarehouse,
    report: TemporalMigrationReport,
) -> None:
    with connect_research_warehouse(warehouse.duckdb_path) as connection:
        connection.execute(
            """
            insert into research_migrations
            (migration_id, source_root, source_manifest_hash, status,
             report_json, completed_at)
            values (?, ?, ?, 'completed', ?, now())
            """,
            [
                report.migration_id,
                str(warehouse.root.resolve()),
                report.source_manifest_hash,
                report.model_dump_json(),
            ],
        )


def _assert_audit_conservation(
    before: tuple[TemporalDatasetAudit, ...],
    after: tuple[TemporalDatasetAudit, ...],
) -> None:
    before_counts = {
        item.dataset_id: (item.partition_count, item.row_count, item.revision_count)
        for item in before
    }
    after_counts = {
        item.dataset_id: (item.partition_count, item.row_count, item.revision_count)
        for item in after
    }
    if before_counts != after_counts:
        raise ValueError("temporal migration changed dataset counts")


def _frame_business_digest(frame: pd.DataFrame) -> str:
    rows = [
        {
            key: _json_value(value)
            for key, value in row.items()
            if key not in _GOVERNANCE_FIELDS
        }
        for row in frame.to_dict(orient="records")
    ]
    rows.sort(key=lambda item: json.dumps(item, sort_keys=True, default=str))
    return _stable_hash(rows)


def _business_payload_digest(payload: dict[str, Any]) -> str:
    return _stable_hash(
        {
            key: _json_value(value)
            for key, value in payload.items()
            if key not in _GOVERNANCE_FIELDS
        }
    )


def _json_record(row: dict[str, Any]) -> dict[str, Any]:
    return {key: _json_value(value) for key, value in row.items()}


def _json_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            return _json_value(value.item())
        except Exception:
            pass
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        return json.loads(value)
    return dict(value)


def _as_utc(value: Any) -> datetime:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp.to_pydatetime()


def _optional_utc(value: Any) -> datetime | None:
    return None if value is None or pd.isna(value) else _as_utc(value)


def _stable_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "TemporalDatasetAudit",
    "TemporalMigrationReport",
    "audit_research_time_semantics",
    "migrate_research_time_semantics",
]
