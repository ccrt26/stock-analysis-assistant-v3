from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd

from stock_analyzer.storage.research_parquet import (
    discard_backup,
    sha256_file,
    write_staged_parquet,
)
from stock_analyzer.storage.research_schema import connect_research_warehouse


_COMMITTABLE_QUALITY_STATUSES = {
    "complete",
    "complete_with_declared_gaps",
    "limited",
}


class DerivedDeterminismError(ValueError):
    pass


class DerivedRecoveryError(RuntimeError):
    pass


@dataclass(frozen=True)
class DerivedCommitResult:
    feature_set: str
    analysis_date: date
    formula_version: str
    run_id: str
    row_count: int
    content_hash: str
    file_sha256: str
    input_manifest_hash: str
    relative_path: str
    quality_status: str
    limitations: tuple[str, ...]
    idempotent: bool
    skipped: bool


@dataclass(frozen=True)
class _PartitionMetadata:
    row_count: int
    content_hash: str
    file_sha256: str
    input_manifest_hash: str
    relative_path: str
    quality_status: str
    limitations: tuple[str, ...]
    run_id: str


class DerivedFeatureStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.derived_root = self.root / "derived"
        self.staging_root = self.root / ".staging" / "derived"
        self.duckdb_path = self.root / "research.duckdb"
        self.root.mkdir(parents=True, exist_ok=True)
        with connect_research_warehouse(self.duckdb_path):
            pass
        self._recover_interrupted_promotions()

    def commit(
        self,
        feature_set: str,
        analysis_date: date | str,
        formula_version: str,
        frame: pd.DataFrame,
        *,
        input_manifest: Mapping[str, Any],
        entity_key: str | Iterable[str],
        quality_status: str,
        limitations: Iterable[str] = (),
        run_id: str,
    ) -> DerivedCommitResult:
        normalized_date = _as_date(analysis_date)
        normalized_feature_set = _path_component(feature_set, "feature_set")
        normalized_formula_version = _path_component(
            formula_version, "formula_version"
        )
        normalized_run_id = _required_text(run_id, "run_id")
        normalized_limitations = _normalize_limitations(limitations)
        if quality_status == "failed":
            raise ValueError("failed quality status cannot commit a derived partition")
        if quality_status not in _COMMITTABLE_QUALITY_STATUSES:
            raise ValueError(f"unsupported derived quality status: {quality_status}")
        if not isinstance(frame, pd.DataFrame):
            raise TypeError("frame must be a pandas DataFrame")
        if not isinstance(input_manifest, Mapping):
            raise TypeError("input_manifest must be a mapping")

        entity_fields = _normalize_entity_key(entity_key)
        prepared = _prepare_frame(frame, entity_fields, normalized_feature_set)
        content_hash = stable_dataframe_content_hash(prepared)
        input_manifest_json = _stable_json(input_manifest)
        input_manifest_hash = _sha256_text(input_manifest_json)
        relative_path = self._partition_path(
            normalized_feature_set,
            normalized_date,
            normalized_formula_version,
        ).relative_to(self.root).as_posix()

        current = self._partition_metadata(
            normalized_feature_set,
            normalized_date,
            normalized_formula_version,
        )
        if current is not None and current.input_manifest_hash == input_manifest_hash:
            conflicts = []
            if current.content_hash != content_hash:
                conflicts.append("content_hash")
            if current.quality_status != quality_status:
                conflicts.append("quality_status")
            if current.limitations != normalized_limitations:
                conflicts.append("limitations")
            if conflicts:
                raise DerivedDeterminismError(
                    "deterministic conflict for derived partition "
                    f"{normalized_feature_set}/{normalized_date.isoformat()}/"
                    f"{normalized_formula_version}: {', '.join(conflicts)} changed "
                    "for the same input manifest"
                )
            return DerivedCommitResult(
                feature_set=normalized_feature_set,
                analysis_date=normalized_date,
                formula_version=normalized_formula_version,
                run_id=current.run_id,
                row_count=current.row_count,
                content_hash=current.content_hash,
                file_sha256=current.file_sha256,
                input_manifest_hash=current.input_manifest_hash,
                relative_path=current.relative_path,
                quality_status=current.quality_status,
                limitations=current.limitations,
                idempotent=True,
                skipped=True,
            )

        final_path = self.root / relative_path
        stage_dir = self.staging_root / uuid4().hex
        staged_path = stage_dir / "data.parquet"
        backup_path: Path | None = None
        try:
            file_sha256 = write_staged_parquet(staged_path, prepared)
            backup_path = self._promote_staged_partition(staged_path, final_path)
            try:
                self._commit_metadata(
                    feature_set=normalized_feature_set,
                    analysis_date=normalized_date,
                    formula_version=normalized_formula_version,
                    run_id=normalized_run_id,
                    row_count=len(prepared),
                    content_hash=content_hash,
                    file_sha256=file_sha256,
                    input_manifest_hash=input_manifest_hash,
                    input_manifest_json=input_manifest_json,
                    relative_path=relative_path,
                    quality_status=quality_status,
                    limitations=normalized_limitations,
                )
            except Exception:
                self._restore_previous_partition(final_path, backup_path)
                raise
            discard_backup(backup_path)
        finally:
            shutil.rmtree(stage_dir, ignore_errors=True)
            self._remove_empty_staging_parents()

        return DerivedCommitResult(
            feature_set=normalized_feature_set,
            analysis_date=normalized_date,
            formula_version=normalized_formula_version,
            run_id=normalized_run_id,
            row_count=len(prepared),
            content_hash=content_hash,
            file_sha256=file_sha256,
            input_manifest_hash=input_manifest_hash,
            relative_path=relative_path,
            quality_status=quality_status,
            limitations=normalized_limitations,
            idempotent=False,
            skipped=False,
        )

    def read(
        self,
        feature_set: str,
        analysis_date: date | str,
        formula_version: str,
    ) -> pd.DataFrame:
        path = self._partition_path(
            _path_component(feature_set, "feature_set"),
            _as_date(analysis_date),
            _path_component(formula_version, "formula_version"),
        )
        if not path.is_file():
            return pd.DataFrame()
        return pd.read_parquet(path)

    def partition_manifest(
        self,
        feature_set: str | None = None,
        *,
        analysis_date: date | str | None = None,
        formula_version: str | None = None,
    ) -> pd.DataFrame:
        clauses: list[str] = []
        parameters: list[Any] = []
        if feature_set is not None:
            clauses.append("feature_set = ?")
            parameters.append(_path_component(feature_set, "feature_set"))
        if analysis_date is not None:
            clauses.append("analysis_date = ?")
            parameters.append(_as_date(analysis_date))
        if formula_version is not None:
            clauses.append("formula_version = ?")
            parameters.append(
                _path_component(formula_version, "formula_version")
            )
        where = "" if not clauses else " where " + " and ".join(clauses)
        with connect_research_warehouse(
            self.duckdb_path, read_only=True
        ) as connection:
            return connection.execute(
                f"""
                select * from research_derived_partitions
                {where}
                order by feature_set, analysis_date, formula_version
                """,
                parameters,
            ).fetchdf()

    def _partition_path(
        self,
        feature_set: str,
        analysis_date: date,
        formula_version: str,
    ) -> Path:
        return (
            self.derived_root
            / feature_set
            / f"analysis_date={analysis_date.isoformat()}"
            / f"formula_version={formula_version}"
            / "data.parquet"
        )

    def _remove_empty_staging_parents(self) -> None:
        for path in (self.staging_root, self.staging_root.parent):
            try:
                path.rmdir()
            except OSError:
                pass

    def _promote_staged_partition(
        self, staged_path: Path, final_path: Path
    ) -> Path | None:
        final_path.parent.mkdir(parents=True, exist_ok=True)
        if not final_path.exists():
            os.replace(staged_path, final_path)
            return None

        backup_path = final_path.with_suffix(".parquet.previous")
        if backup_path.exists():
            raise DerivedRecoveryError(
                f"unreconciled derived backup already exists: {backup_path}"
            )
        shutil.copy2(final_path, backup_path)
        try:
            os.replace(staged_path, final_path)
        except Exception:
            if final_path.is_file() and sha256_file(final_path) == sha256_file(
                backup_path
            ):
                discard_backup(backup_path)
            raise
        return backup_path

    def _restore_previous_partition(
        self,
        final_path: Path,
        backup_path: Path | None,
    ) -> None:
        if backup_path is None:
            if final_path.exists():
                final_path.unlink()
            return
        if not backup_path.is_file():
            raise DerivedRecoveryError(
                f"cannot restore missing derived backup: {backup_path}"
            )
        os.replace(backup_path, final_path)

    def _recover_interrupted_promotions(self) -> None:
        backup_paths = sorted(self.derived_root.rglob("*.parquet.previous"))
        if not backup_paths:
            return
        with connect_research_warehouse(
            self.duckdb_path, read_only=True
        ) as connection:
            for backup_path in backup_paths:
                final_path = backup_path.with_suffix("")
                relative_path = final_path.relative_to(self.root).as_posix()
                row = connection.execute(
                    """
                    select file_sha256 from research_derived_partitions
                    where relative_path = ?
                    """,
                    [relative_path],
                ).fetchone()
                if row is None:
                    raise DerivedRecoveryError(
                        "cannot reconcile interrupted derived promotion without "
                        f"metadata: {relative_path}"
                    )
                metadata_sha256 = str(row[0])
                try:
                    final_sha256 = (
                        sha256_file(final_path) if final_path.is_file() else None
                    )
                    backup_sha256 = sha256_file(backup_path)
                except OSError as exc:
                    raise DerivedRecoveryError(
                        "cannot reconcile interrupted derived promotion for "
                        f"{relative_path}"
                    ) from exc

                if final_sha256 == metadata_sha256:
                    discard_backup(backup_path)
                    continue
                if backup_sha256 == metadata_sha256:
                    os.replace(backup_path, final_path)
                    continue
                raise DerivedRecoveryError(
                    "cannot reconcile interrupted derived promotion for "
                    f"{relative_path}: neither file matches metadata"
                )

    def _commit_metadata(
        self,
        *,
        feature_set: str,
        analysis_date: date,
        formula_version: str,
        run_id: str,
        row_count: int,
        content_hash: str,
        file_sha256: str,
        input_manifest_hash: str,
        input_manifest_json: str,
        relative_path: str,
        quality_status: str,
        limitations: tuple[str, ...],
    ) -> None:
        limitations_json = _stable_json(limitations)
        committed_at = datetime.now(timezone.utc)
        with connect_research_warehouse(self.duckdb_path) as connection:
            connection.begin()
            try:
                connection.execute(
                    """
                    insert into research_derived_runs
                    (run_id, feature_set, analysis_date, formula_version,
                     input_manifest_json, input_manifest_hash, quality_status,
                     limitations_json, status, row_count, content_hash,
                     file_sha256, started_at, finished_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, 'committed', ?, ?, ?, ?, ?)
                    """,
                    [
                        run_id,
                        feature_set,
                        analysis_date,
                        formula_version,
                        input_manifest_json,
                        input_manifest_hash,
                        quality_status,
                        limitations_json,
                        row_count,
                        content_hash,
                        file_sha256,
                        committed_at,
                        committed_at,
                    ],
                )
                connection.execute(
                    """
                    insert into research_derived_partitions
                    (feature_set, analysis_date, formula_version, relative_path,
                     row_count, content_hash, file_sha256, input_manifest_hash,
                     input_manifest_json, quality_status, limitations_json,
                     committed_at, run_id)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    on conflict(feature_set, analysis_date, formula_version)
                    do update set
                        relative_path = excluded.relative_path,
                        row_count = excluded.row_count,
                        content_hash = excluded.content_hash,
                        file_sha256 = excluded.file_sha256,
                        input_manifest_hash = excluded.input_manifest_hash,
                        input_manifest_json = excluded.input_manifest_json,
                        quality_status = excluded.quality_status,
                        limitations_json = excluded.limitations_json,
                        committed_at = excluded.committed_at,
                        run_id = excluded.run_id
                    """,
                    [
                        feature_set,
                        analysis_date,
                        formula_version,
                        relative_path,
                        row_count,
                        content_hash,
                        file_sha256,
                        input_manifest_hash,
                        input_manifest_json,
                        quality_status,
                        limitations_json,
                        committed_at,
                        run_id,
                    ],
                )
            except Exception:
                connection.rollback()
                raise
            connection.commit()

    def _partition_metadata(
        self,
        feature_set: str,
        analysis_date: date,
        formula_version: str,
    ) -> _PartitionMetadata | None:
        with connect_research_warehouse(
            self.duckdb_path, read_only=True
        ) as connection:
            row = connection.execute(
                """
                select row_count, content_hash, file_sha256,
                       input_manifest_hash, relative_path, quality_status,
                       limitations_json, run_id
                from research_derived_partitions
                where feature_set = ? and analysis_date = ?
                  and formula_version = ?
                """,
                [feature_set, analysis_date, formula_version],
            ).fetchone()
        if row is None:
            return None
        raw_limitations = json.loads(row[6]) if isinstance(row[6], str) else row[6]
        return _PartitionMetadata(
            row_count=int(row[0]),
            content_hash=str(row[1]),
            file_sha256=str(row[2]),
            input_manifest_hash=str(row[3]),
            relative_path=str(row[4]),
            quality_status=str(row[5]),
            limitations=tuple(str(item) for item in raw_limitations),
            run_id=str(row[7]),
        )


def stable_dataframe_content_hash(frame: pd.DataFrame) -> str:
    if frame.columns.has_duplicates:
        raise ValueError("derived output has duplicate column names")
    columns = sorted(str(column) for column in frame.columns)
    canonical_rows = [
        {column: _content_json_safe(row[column]) for column in columns}
        for row in frame.to_dict(orient="records")
    ]
    canonical_rows.sort(key=_stable_json)
    return _sha256_text(
        _stable_json({"columns": columns, "rows": canonical_rows})
    )


def stable_input_manifest_hash(input_manifest: Mapping[str, Any]) -> str:
    if not isinstance(input_manifest, Mapping):
        raise TypeError("input_manifest must be a mapping")
    return _sha256_text(_stable_json(input_manifest))


def _prepare_frame(
    frame: pd.DataFrame,
    entity_fields: tuple[str, ...],
    feature_set: str,
) -> pd.DataFrame:
    if frame.columns.has_duplicates:
        raise ValueError(f"derived output has duplicate columns in {feature_set}")
    missing = [field for field in entity_fields if field not in frame.columns]
    if missing:
        raise ValueError(f"missing entity key fields in {feature_set}: {missing}")
    if not frame.empty:
        null_keys = frame.loc[:, list(entity_fields)].isna().any(axis=1)
        if null_keys.any():
            raise ValueError(
                f"null entity key in {feature_set}: {int(null_keys.sum())} rows"
            )
        duplicates = frame.duplicated(subset=list(entity_fields), keep=False)
        if duplicates.any():
            raise ValueError(
                f"duplicate entity key in {feature_set}: "
                f"{int(duplicates.sum())} rows"
            )

    prepared = frame.copy(deep=True).reset_index(drop=True)
    if prepared.empty:
        return prepared
    sort_tokens = [
        _stable_json([_json_safe(row[field]) for field in entity_fields])
        for row in prepared.to_dict(orient="records")
    ]
    prepared["__derived_entity_sort_token__"] = sort_tokens
    prepared = prepared.sort_values(
        "__derived_entity_sort_token__", kind="stable"
    ).drop(columns="__derived_entity_sort_token__")
    return prepared.reset_index(drop=True)


def _normalize_entity_key(entity_key: str | Iterable[str]) -> tuple[str, ...]:
    if isinstance(entity_key, str):
        fields = (entity_key,)
    else:
        fields = tuple(entity_key)
    if not fields or any(not isinstance(field, str) or not field for field in fields):
        raise ValueError("entity_key must contain at least one non-empty field")
    if len(fields) != len(set(fields)):
        raise ValueError("entity_key fields must be unique")
    return fields


def _normalize_limitations(limitations: Iterable[str]) -> tuple[str, ...]:
    if isinstance(limitations, str):
        prepared = (limitations,)
    else:
        prepared = tuple(limitations)
    if any(not isinstance(item, str) or not item for item in prepared):
        raise ValueError("limitations must contain non-empty strings")
    return prepared


def _required_text(value: str, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _path_component(value: str, field: str) -> str:
    prepared = _required_text(value, field)
    if prepared in {".", ".."} or "/" in prepared or "\\" in prepared:
        raise ValueError(f"{field} must be a safe path component")
    return prepared


def _as_date(value: date | str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"invalid analysis_date: {value}") from exc


def _json_safe(value: Any) -> Any:
    if value is None or value is pd.NA:
        return None
    if isinstance(value, (datetime, pd.Timestamp)):
        timestamp = pd.Timestamp(value)
        if timestamp.tzinfo is None:
            timestamp = timestamp.tz_localize("UTC")
        else:
            timestamp = timestamp.tz_convert("UTC")
        return timestamp.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str) or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if math.isnan(value):
            return {"__non_finite_float__": "nan"}
        if value == math.inf:
            return {"__non_finite_float__": "+inf"}
        if value == -math.inf:
            return {"__non_finite_float__": "-inf"}
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (set, frozenset)):
        prepared = [_json_safe(item) for item in value]
        return sorted(prepared, key=_stable_json)
    item = getattr(value, "item", None)
    if callable(item):
        return _json_safe(item())
    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        pass
    return str(value)


def _content_json_safe(value: Any) -> Any:
    if value is None:
        return ["none"]
    if value is pd.NA:
        return ["missing", "pandas.NA"]
    if isinstance(value, (datetime, pd.Timestamp)):
        timestamp = pd.Timestamp(value)
        if timestamp.tzinfo is None:
            timestamp = timestamp.tz_localize("UTC")
        else:
            timestamp = timestamp.tz_convert("UTC")
        return ["datetime", timestamp.isoformat()]
    if isinstance(value, date):
        return ["date", value.isoformat()]
    if isinstance(value, str):
        return ["string", value]
    if isinstance(value, bool):
        return ["boolean", value]
    if isinstance(value, int):
        return ["integer", value]
    if isinstance(value, float):
        if math.isnan(value):
            return ["float", "nan"]
        if value == math.inf:
            return ["float", "+inf"]
        if value == -math.inf:
            return ["float", "-inf"]
        return ["float", value]
    if isinstance(value, Mapping):
        items = sorted(
            (
                ["key", str(key)],
                _content_json_safe(item),
            )
            for key, item in value.items()
        )
        return ["mapping", items]
    if isinstance(value, (list, tuple)):
        return ["sequence", [_content_json_safe(item) for item in value]]
    if isinstance(value, (set, frozenset)):
        prepared = [_content_json_safe(item) for item in value]
        return ["set", sorted(prepared, key=_stable_json)]
    item = getattr(value, "item", None)
    if callable(item):
        return _content_json_safe(item())
    try:
        if bool(pd.isna(value)):
            return ["missing", type(value).__name__]
    except (TypeError, ValueError):
        pass
    return ["object", type(value).__name__, str(value)]


def _stable_json(value: Any) -> str:
    return json.dumps(
        _json_safe(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


__all__ = [
    "DerivedCommitResult",
    "DerivedDeterminismError",
    "DerivedFeatureStore",
    "DerivedRecoveryError",
    "stable_dataframe_content_hash",
    "stable_input_manifest_hash",
]
