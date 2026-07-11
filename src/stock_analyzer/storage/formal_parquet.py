from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Sequence

import pyarrow as pa
import pyarrow.parquet as pq

from stock_analyzer.data.readiness import AcquisitionPayload


class FormalParquetError(RuntimeError):
    pass


class FormalParquetConflict(FormalParquetError):
    pass


class FormalParquetCorruption(FormalParquetError):
    pass


@dataclass(frozen=True)
class PreparedParquetFile:
    record_type: str
    partition_date: date
    relative_path: Path
    staging_path: Path
    row_count: int
    file_sha256: str
    schema_json: str


@dataclass(frozen=True)
class FormalVersionFile:
    version_id: str
    record_type: str
    partition_date: date
    relative_path: Path
    row_count: int
    file_sha256: str
    schema_json: str


@dataclass(frozen=True)
class PreparedVersionFiles:
    version_id: str
    staging_root: Path
    files: tuple[PreparedParquetFile, ...]


RECORD_FAMILIES = {
    "calendar": "calendar",
    "security": "stock_universe",
    "equity_bar": "market_daily",
    "daily_basic": "daily_basic",
    "index_bar": "index_daily",
    "board_bar": "board_daily",
    "company_profile": "company_profile",
    "financial": "fundamental_snapshot",
    "financial_summary": "fundamental_snapshot",
    "forecast": "fundamental_snapshot",
    "express": "fundamental_snapshot",
    "main_business": "fundamental_snapshot",
    "industry_mapping": "industry_membership",
    "concept_mapping": "concept_membership",
    "event": "event_catalyst",
    "official_event": "official_risk",
    "official_risk": "official_risk",
    "manual_holding": "manual_holding",
}

_DATE_FIELDS = (
    "trade_date",
    "cal_date",
    "as_of_date",
    "end_date",
    "ann_date",
    "published_at",
    "pub_date",
)
_RESERVED_PREFIX = "__"


def prepare_version_files(root: Path, payload: AcquisitionPayload) -> PreparedVersionFiles:
    warehouse_root = Path(root)
    version_id = _version_id(payload)
    staging_root = (
        warehouse_root
        / "parquet"
        / "formal"
        / ".staging"
        / uuid.uuid4().hex
    )
    if not payload.records:
        return PreparedVersionFiles(version_id, staging_root, ())

    grouped: dict[tuple[str, date], list[tuple[int, dict[str, Any]]]] = {}
    for ordinal, original in enumerate(payload.records):
        record = dict(original)
        record_type = str(record.get("record_type", ""))
        if record_type not in RECORD_FAMILIES:
            raise ValueError(f"unsupported formal record type: {record_type or '<missing>'}")
        reserved = sorted(key for key in record if key.startswith(_RESERVED_PREFIX))
        if reserved:
            raise ValueError("formal record uses reserved fields: " + ", ".join(reserved))
        partition_date = _partition_date(record, payload.trade_date)
        grouped.setdefault((record_type, partition_date), []).append((ordinal, record))

    files: list[PreparedParquetFile] = []
    for (record_type, partition_date), items in grouped.items():
        family = RECORD_FAMILIES[record_type]
        date_key = _partition_key(record_type)
        relative_path = (
            Path("parquet")
            / "formal"
            / family
            / f"{date_key}={partition_date.isoformat()}"
            / f"version_id={version_id}"
            / "part-00000.parquet"
        )
        staging_path = staging_root / relative_path.relative_to("parquet/formal")
        staging_path.parent.mkdir(parents=True, exist_ok=True)
        table = pa.Table.from_pylist(_arrow_rows(version_id, payload, items))
        pq.write_table(table, staging_path, compression="zstd")
        files.append(
            PreparedParquetFile(
                record_type=record_type,
                partition_date=partition_date,
                relative_path=relative_path,
                staging_path=staging_path,
                row_count=len(items),
                file_sha256=_sha256(staging_path),
                schema_json=json.dumps(
                    {"arrow_schema": str(table.schema)},
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            )
        )
    return PreparedVersionFiles(version_id, staging_root, tuple(files))


def verify_prepared_version(
    prepared: PreparedVersionFiles,
    payload: AcquisitionPayload,
) -> None:
    for item in prepared.files:
        if not item.staging_path.is_file():
            raise FormalParquetCorruption(f"staged file missing: {item.staging_path}")
        if _sha256(item.staging_path) != item.file_sha256:
            raise FormalParquetCorruption(f"staged file hash mismatch: {item.staging_path}")
    records = _read_paths(
        [(item.staging_path, item.record_type, item.row_count) for item in prepared.files]
    )
    rebuilt = payload.model_copy(update={"records": records})
    if rebuilt.content_hash != payload.content_hash:
        raise FormalParquetCorruption("staged Parquet payload hash mismatch")


def promote_prepared_version(
    root: Path,
    prepared: PreparedVersionFiles,
) -> tuple[FormalVersionFile, ...]:
    warehouse_root = Path(root)
    promoted: list[FormalVersionFile] = []
    for item in prepared.files:
        final_path = warehouse_root / item.relative_path
        final_path.parent.mkdir(parents=True, exist_ok=True)
        if final_path.exists():
            if _sha256(final_path) != item.file_sha256:
                raise FormalParquetConflict(
                    f"immutable formal Parquet conflict: {item.relative_path}"
                )
            item.staging_path.unlink(missing_ok=True)
        else:
            os.replace(item.staging_path, final_path)
        promoted.append(
            FormalVersionFile(
                version_id=prepared.version_id,
                record_type=item.record_type,
                partition_date=item.partition_date,
                relative_path=item.relative_path,
                row_count=item.row_count,
                file_sha256=item.file_sha256,
                schema_json=item.schema_json,
            )
        )
    if prepared.staging_root.exists():
        shutil.rmtree(prepared.staging_root)
    return tuple(promoted)


def read_version_records(
    root: Path,
    files: Sequence[FormalVersionFile],
) -> tuple[dict[str, Any], ...]:
    warehouse_root = Path(root)
    return _read_paths(
        [
            (warehouse_root / item.relative_path, item.record_type, item.row_count)
            for item in files
        ]
    )


def verify_version_files(
    root: Path,
    files: Sequence[FormalVersionFile],
    *,
    strict_hashes: bool,
) -> None:
    warehouse_root = Path(root)
    for item in files:
        path = warehouse_root / item.relative_path
        if not path.is_file():
            raise FormalParquetCorruption(f"formal Parquet file missing: {item.relative_path}")
        if strict_hashes and _sha256(path) != item.file_sha256:
            raise FormalParquetCorruption(f"formal Parquet file hash mismatch: {item.relative_path}")
        metadata = pq.ParquetFile(path).metadata
        if metadata.num_rows != item.row_count:
            raise FormalParquetCorruption(f"formal Parquet row count mismatch: {item.relative_path}")


def _arrow_rows(
    version_id: str,
    payload: AcquisitionPayload,
    items: list[tuple[int, dict[str, Any]]],
) -> list[dict[str, Any]]:
    fields = sorted({key for _, record in items for key in record})
    rows: list[dict[str, Any]] = []
    for ordinal, record in items:
        row: dict[str, Any] = {key: None for key in fields}
        value_types: dict[str, str] = {}
        json_fields: list[str] = []
        for key, value in record.items():
            converted, value_type, is_json = _to_storage_value(value)
            row[key] = converted
            value_types[key] = value_type
            if is_json:
                json_fields.append(key)
        row.update(
            {
                "__version_id": version_id,
                "__group_id": payload.group_id.value,
                "__record_type": str(record["record_type"]),
                "__ordinal": ordinal,
                "__present_fields": json.dumps(sorted(record), ensure_ascii=False),
                "__json_fields": json.dumps(sorted(json_fields), ensure_ascii=False),
                "__value_types": json.dumps(value_types, ensure_ascii=False, sort_keys=True),
            }
        )
        rows.append(row)
    return rows


def _to_storage_value(value: Any) -> tuple[Any, str, bool]:
    if value is None:
        return None, "null", False
    if isinstance(value, bool):
        return value, "bool", False
    if isinstance(value, int):
        return value, "int", False
    if isinstance(value, float):
        return value, "float", False
    if isinstance(value, datetime):
        return value.isoformat(), "datetime", False
    if isinstance(value, date):
        return value.isoformat(), "date", False
    if isinstance(value, str):
        return value, "str", False
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, default=_json_default),
        "json",
        True,
    )


def _read_paths(
    paths: Sequence[tuple[Path, str, int]],
) -> tuple[dict[str, Any], ...]:
    ordered: list[tuple[int, dict[str, Any]]] = []
    for path, expected_record_type, expected_rows in paths:
        if not path.is_file():
            raise FormalParquetCorruption(f"formal Parquet file missing: {path}")
        rows = pq.ParquetFile(path).read().to_pylist()
        if len(rows) != expected_rows:
            raise FormalParquetCorruption(f"formal Parquet row count mismatch: {path}")
        for row in rows:
            if row["__record_type"] != expected_record_type:
                raise FormalParquetCorruption(f"formal Parquet record type mismatch: {path}")
            present = json.loads(row.pop("__present_fields"))
            json_fields = set(json.loads(row.pop("__json_fields")))
            value_types = json.loads(row.pop("__value_types"))
            ordinal = int(row.pop("__ordinal"))
            row.pop("__version_id")
            row.pop("__group_id")
            row.pop("__record_type")
            record = {
                key: _from_storage_value(row.get(key), value_types[key], key in json_fields)
                for key in present
            }
            ordered.append((ordinal, record))
    ordered.sort(key=lambda item: item[0])
    if len({ordinal for ordinal, _ in ordered}) != len(ordered):
        raise FormalParquetCorruption("duplicate formal Parquet record ordinal")
    return tuple(record for _, record in ordered)


def _from_storage_value(value: Any, value_type: str, is_json: bool) -> Any:
    if value_type == "null":
        return None
    if is_json or value_type == "json":
        return json.loads(value)
    if value_type == "bool":
        return bool(value)
    if value_type == "int":
        return int(value)
    if value_type == "float":
        return float(value)
    if value_type == "date":
        return date.fromisoformat(value)
    if value_type == "datetime":
        return datetime.fromisoformat(value)
    return str(value)


def _partition_date(record: dict[str, Any], target_date: date) -> date:
    for field in _DATE_FIELDS:
        parsed = _as_date(record.get(field))
        if parsed is not None:
            return parsed
    return target_date


def _partition_key(record_type: str) -> str:
    if record_type == "calendar":
        return "cal_date"
    if record_type in {
        "company_profile",
        "financial",
        "financial_summary",
        "forecast",
        "express",
        "main_business",
        "industry_mapping",
        "concept_mapping",
    }:
        return "as_of_date"
    if record_type in {"event", "official_event", "official_risk"}:
        return "event_date"
    return "trade_date"


def _as_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            try:
                return date.fromisoformat(value[:10])
            except ValueError:
                return None
    return None


def _version_id(payload: AcquisitionPayload) -> str:
    return (
        f"{payload.group_id.value}-{payload.trade_date.isoformat()}-"
        f"{payload.content_hash}"
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_default(value: Any) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"unsupported nested formal value: {type(value).__name__}")


__all__ = [
    "FormalParquetConflict",
    "FormalParquetCorruption",
    "FormalVersionFile",
    "PreparedVersionFiles",
    "prepare_version_files",
    "promote_prepared_version",
    "read_version_records",
    "verify_prepared_version",
    "verify_version_files",
]
