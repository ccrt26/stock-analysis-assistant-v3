from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from stock_analyzer.data.readiness import (
    AcquisitionGroupId,
    AcquisitionPayload,
    GroupValidation,
)
from stock_analyzer.storage.evidence_store import GroupVersionManifest
from stock_analyzer.storage.formal_parquet import (
    FormalParquetCorruption,
    FormalVersionFile,
    prepare_version_files,
    promote_prepared_version,
    read_version_records,
    verify_prepared_version,
    verify_version_files,
)
from stock_analyzer.storage.formal_schema import connect_formal_warehouse


@dataclass(frozen=True)
class GroupVersionAudit:
    version_id: str
    complete: bool
    file_count: int
    row_count: int
    content_hash: str


class FormalWarehouse:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.duckdb_path = self.root / "warehouse.duckdb"
        with self._connect():
            pass

    def _connect(self, *, read_only: bool = False):
        return connect_formal_warehouse(self.duckdb_path, read_only=read_only)

    def save_group_version(
        self,
        payload: AcquisitionPayload,
        validation: GroupValidation,
    ) -> GroupVersionManifest:
        if not validation.complete:
            raise ValueError("cannot persist an incomplete acquisition group version")
        version_id = _version_id(payload)
        existing = self._manifest_or_none(version_id)
        if existing is not None:
            loaded = self.read_group_version(version_id)
            if loaded is None or loaded.content_hash != payload.content_hash:
                raise ValueError(f"existing formal version mismatch: {version_id}")
            return existing

        prepared = prepare_version_files(self.root, payload)
        verify_prepared_version(prepared, payload)
        files = promote_prepared_version(self.root, prepared)
        with self._connect() as connection:
            connection.begin()
            try:
                self._insert_version(connection, payload, validation, files)
            except Exception:
                connection.rollback()
                raise
            connection.commit()
        return self.group_version_manifest(version_id)

    def _insert_version(
        self,
        connection,
        payload: AcquisitionPayload,
        validation: GroupValidation,
        files: tuple[FormalVersionFile, ...],
    ) -> None:
        del validation
        version_id = _version_id(payload)
        connection.execute(
            """
            insert into formal_versions (
                version_id, group_id, target_date, route_id, route_kind,
                content_hash, complete, fetched_at, contract_version,
                covered_dates, coverage_codes, coverage_proven,
                field_coverage, source_names, unit_metadata,
                adjustment_basis, publication_times
            ) values (?, ?, ?, ?, ?, ?, true, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                version_id,
                payload.group_id.value,
                payload.trade_date,
                payload.route_id,
                payload.route_kind.value,
                payload.content_hash,
                payload.fetched_at,
                payload.contract_version,
                _json(payload.covered_dates),
                _json(payload.coverage_codes),
                payload.coverage_proven,
                _json(payload.field_coverage),
                _json(payload.source_names),
                _json(payload.unit_metadata),
                payload.adjustment_basis,
                _json(payload.publication_times),
            ],
        )
        for item in files:
            connection.execute(
                """
                insert into formal_version_files (
                    version_id, record_type, partition_date, relative_path,
                    row_count, file_sha256, schema_json
                ) values (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    version_id,
                    item.record_type,
                    item.partition_date,
                    item.relative_path.as_posix(),
                    item.row_count,
                    item.file_sha256,
                    item.schema_json,
                ],
            )

    def read_group_version(
        self,
        version_id: str,
        *,
        report_cutoff: datetime | None = None,
    ) -> AcquisitionPayload | None:
        with self._connect(read_only=True) as connection:
            cursor = connection.execute(
                """
                select version_id, group_id, target_date, route_id, route_kind,
                       content_hash, complete,
                       cast(fetched_at as varchar) as fetched_at,
                       contract_version, covered_dates, coverage_codes,
                       coverage_proven, field_coverage, source_names,
                       unit_metadata, adjustment_basis, publication_times
                from formal_versions where version_id = ?
                """,
                [version_id],
            )
            row = cursor.fetchone()
            if row is None:
                raise FileNotFoundError(f"formal group version not found: {version_id}")
            values = _row_dict(cursor, row)
        files = self.version_files(version_id)
        records = read_version_records(self.root, files)
        payload = AcquisitionPayload.model_validate(
            {
                "group_id": values["group_id"],
                "route_id": values["route_id"],
                "route_kind": values["route_kind"],
                "trade_date": values["target_date"],
                "fetched_at": _parse_duckdb_timestamp(values["fetched_at"]),
                "source_names": _from_json(values["source_names"]),
                "records": records,
                "covered_dates": _from_json(values["covered_dates"]),
                "coverage_codes": _from_json(values["coverage_codes"]),
                "coverage_proven": values["coverage_proven"],
                "field_coverage": _from_json(values["field_coverage"]),
                "unit_metadata": _from_json(values["unit_metadata"]),
                "adjustment_basis": values["adjustment_basis"],
                "publication_times": _from_json(values["publication_times"]),
                "contract_version": values["contract_version"],
            }
        )
        if payload.content_hash != values["content_hash"]:
            raise FormalParquetCorruption(
                f"formal payload content hash mismatch: {version_id}"
            )
        if report_cutoff is not None and any(
            published_at > report_cutoff
            for published_at in payload.publication_times.values()
        ):
            return None
        return payload

    def group_version_manifest(self, version_id: str) -> GroupVersionManifest:
        manifest = self._manifest_or_none(version_id)
        if manifest is None:
            raise FileNotFoundError(f"formal group version not found: {version_id}")
        return manifest

    def _manifest_or_none(self, version_id: str) -> GroupVersionManifest | None:
        with self._connect(read_only=True) as connection:
            row = connection.execute(
                """
                select version_id, group_id, target_date, route_id, route_kind,
                       content_hash, complete,
                       cast(fetched_at as varchar) as fetched_at
                from formal_versions where version_id = ?
                """,
                [version_id],
            ).fetchone()
        if row is None:
            return None
        return GroupVersionManifest.model_validate(
            {
                "version_id": row[0],
                "group_id": row[1],
                "trade_date": row[2],
                "route_id": row[3],
                "route_kind": row[4],
                "content_hash": row[5],
                "complete": row[6],
                "created_at": _parse_duckdb_timestamp(row[7]),
            }
        )

    def list_group_versions(self) -> tuple[GroupVersionManifest, ...]:
        with self._connect(read_only=True) as connection:
            ids = [
                row[0]
                for row in connection.execute(
                    "select version_id from formal_versions order by fetched_at, version_id"
                ).fetchall()
            ]
        return tuple(self.group_version_manifest(version_id) for version_id in ids)

    def version_files(self, version_id: str) -> tuple[FormalVersionFile, ...]:
        with self._connect(read_only=True) as connection:
            rows = connection.execute(
                """
                select record_type, partition_date, relative_path, row_count,
                       file_sha256, schema_json
                from formal_version_files
                where version_id = ?
                order by partition_date, record_type, relative_path
                """,
                [version_id],
            ).fetchall()
        return tuple(
            FormalVersionFile(
                version_id=version_id,
                record_type=row[0],
                partition_date=row[1],
                relative_path=Path(row[2]),
                row_count=int(row[3]),
                file_sha256=row[4],
                schema_json=row[5],
            )
            for row in rows
        )

    def verify_group_version(
        self,
        version_id: str,
        *,
        strict_hashes: bool = True,
    ) -> GroupVersionAudit:
        manifest = self.group_version_manifest(version_id)
        files = self.version_files(version_id)
        verify_version_files(self.root, files, strict_hashes=strict_hashes)
        payload = self.read_group_version(version_id)
        if payload is None or payload.content_hash != manifest.content_hash:
            raise FormalParquetCorruption(
                f"formal payload content hash mismatch: {version_id}"
            )
        return GroupVersionAudit(
            version_id=version_id,
            complete=manifest.complete,
            file_count=len(files),
            row_count=sum(item.row_count for item in files),
            content_hash=manifest.content_hash,
        )

    def set_canonical(
        self,
        group_id: AcquisitionGroupId,
        trade_date: date,
        version_id: str,
    ) -> None:
        manifest = self.group_version_manifest(version_id)
        if manifest.group_id != group_id or manifest.trade_date != trade_date:
            raise ValueError("canonical pointer group/date mismatch")
        with self._connect() as connection:
            connection.begin()
            connection.execute(
                """
                insert or replace into formal_canonical_versions values (?, ?, ?, ?)
                """,
                [group_id.value, trade_date, version_id, datetime.now(timezone.utc)],
            )
            connection.commit()

    def canonical_manifest(
        self,
        group_id: AcquisitionGroupId,
        trade_date: date,
    ) -> GroupVersionManifest | None:
        with self._connect(read_only=True) as connection:
            row = connection.execute(
                """
                select version_id from formal_canonical_versions
                where group_id = ? and target_date = ?
                """,
                [group_id.value, trade_date],
            ).fetchone()
        return self.group_version_manifest(row[0]) if row is not None else None

    def load_prior_sessions(
        self,
        group_id: AcquisitionGroupId,
        before_date: date,
        limit: int,
    ) -> list[AcquisitionPayload]:
        if limit < 0:
            raise ValueError("limit cannot be negative")
        if limit == 0:
            return []
        with self._connect(read_only=True) as connection:
            rows = connection.execute(
                """
                select target_date, version_id from formal_canonical_versions
                where group_id = ? and target_date < ?
                order by target_date desc limit ?
                """,
                [group_id.value, before_date, limit],
            ).fetchall()
        payloads = [
            self.read_group_version(version_id)
            for _, version_id in reversed(rows)
        ]
        return [payload for payload in payloads if payload is not None]


def _version_id(payload: AcquisitionPayload) -> str:
    return (
        f"{payload.group_id.value}-{payload.trade_date.isoformat()}-"
        f"{payload.content_hash}"
    )


def _json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    )


def _json_default(value: Any) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if hasattr(value, "value"):
        return str(value.value)
    raise TypeError(f"unsupported formal metadata type: {type(value).__name__}")


def _from_json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _row_dict(cursor, row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        description[0]: value
        for description, value in zip(cursor.description, row, strict=True)
    }


def _parse_duckdb_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    text = str(value).replace(" ", "T", 1)
    if re.search(r"[+-]\d{2}$", text):
        text = f"{text}:00"
    return datetime.fromisoformat(text)


__all__ = ["FormalWarehouse", "GroupVersionAudit"]
