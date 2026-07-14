from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

import duckdb
import pandas as pd

from stock_analyzer.data.research_contracts import (
    FactBatch,
    ResearchDatasetId,
    research_contract,
    research_contract_registry,
)
from stock_analyzer.storage.research_parquet import (
    atomic_promote,
    discard_backup,
    restore_previous,
    sha256_file,
    write_staged_parquet,
)
from stock_analyzer.storage.research_schema import connect_research_warehouse


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

_EXACT_DATE_PARTITION_DATASETS = {
    ResearchDatasetId.EQUITY_DAILY,
    ResearchDatasetId.ADJ_FACTOR,
    ResearchDatasetId.DAILY_BASIC,
    ResearchDatasetId.STOCK_LIMIT,
    ResearchDatasetId.INDEX_DAILY,
    ResearchDatasetId.INDUSTRY_DAILY,
    ResearchDatasetId.THEME_DAILY,
    ResearchDatasetId.SUSPENSION,
    ResearchDatasetId.MARGIN_DETAIL,
    ResearchDatasetId.MINUTE_BAR,
}

_GLOBAL_KEY_INDEX_DATASETS = set(research_contract_registry()) - (
    _EXACT_DATE_PARTITION_DATASETS | {ResearchDatasetId.TRADE_CALENDAR}
)


@dataclass(frozen=True)
class FactCommitResult:
    dataset_id: ResearchDatasetId
    partition_value: str
    row_count: int
    new_rows: int
    changed_rows: int
    unchanged_rows: int
    content_hash: str
    file_sha256: str


class ResearchWarehouse:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.facts_root = self.root / "facts"
        self.staging_root = self.root / ".staging"
        self.duckdb_path = self.root / "research.duckdb"
        self.root.mkdir(parents=True, exist_ok=True)
        with connect_research_warehouse(self.duckdb_path) as connection:
            for dataset_id, contract in research_contract_registry().items():
                connection.execute(
                    """
                    insert or replace into research_dataset_catalog
                    (dataset_id, contract_json, updated_at)
                    values (?, ?, now())
                    """,
                    [dataset_id.value, contract.model_dump_json()],
                )
        self._ensure_fact_key_index()

    def commit_batch(self, batch: FactBatch) -> FactCommitResult:
        contract = research_contract(batch.dataset_id)
        incoming = self._normalize_batch(batch)
        self._validate_frame(batch.dataset_id, incoming, contract.business_key)
        self._validate_partition_semantics(batch, incoming)
        final_path = self._partition_path(batch.dataset_id, batch.partition_value)
        existing = self._read_path(final_path)
        merged, revisions, counts = self._merge(
            existing,
            incoming,
            contract.business_key,
            batch,
        )
        self._assert_partition_ownership(
            batch.dataset_id,
            batch.partition_value,
            set(incoming.get("business_key_hash", pd.Series(dtype=str)).astype(str)),
        )
        content_hash = self._frame_content_hash(merged)

        current_meta = self._partition_metadata(
            batch.dataset_id,
            batch.partition_value,
        )
        if (
            current_meta is not None
            and current_meta[0] == content_hash
            and counts[0] == 0
            and counts[1] == 0
        ):
            return FactCommitResult(
                dataset_id=batch.dataset_id,
                partition_value=batch.partition_value,
                row_count=len(merged),
                new_rows=0,
                changed_rows=0,
                unchanged_rows=counts[2],
                content_hash=content_hash,
                file_sha256=current_meta[1],
            )

        stage_dir = self.staging_root / batch.ingestion_run_id / batch.dataset_id.value
        staged_path = stage_dir / f"{_safe_partition(batch.partition_value)}.parquet"
        file_sha256 = write_staged_parquet(staged_path, merged)
        backup_path: Path | None = None
        try:
            backup_path = self._promote_staged_partition(staged_path, final_path)
            try:
                self._commit_metadata(
                    batch,
                    merged,
                    final_path,
                    content_hash,
                    file_sha256,
                    revisions,
                )
            except Exception:
                restore_previous(final_path, backup_path)
                raise
            discard_backup(backup_path)
        finally:
            shutil.rmtree(stage_dir.parent, ignore_errors=True)

        return FactCommitResult(
            dataset_id=batch.dataset_id,
            partition_value=batch.partition_value,
            row_count=len(merged),
            new_rows=counts[0],
            changed_rows=counts[1],
            unchanged_rows=counts[2],
            content_hash=content_hash,
            file_sha256=file_sha256,
        )

    def _promote_staged_partition(self, staged_path: Path, final_path: Path) -> Path | None:
        return atomic_promote(staged_path, final_path)

    def read_current(
        self,
        dataset_id: ResearchDatasetId | str,
        *,
        partition_value: str | None = None,
    ) -> pd.DataFrame:
        dataset = ResearchDatasetId(dataset_id)
        if partition_value is not None:
            return self._read_path(self._partition_path(dataset, partition_value))
        paths = sorted((self.facts_root / dataset.value).glob("*/data.parquet"))
        if not paths:
            return pd.DataFrame()
        with duckdb.connect() as connection:
            return connection.execute(
                "select * from read_parquet(?, union_by_name=true, hive_partitioning=false)",
                [[str(path) for path in paths]],
            ).fetchdf()

    def read_current_partitions(
        self,
        dataset_id: ResearchDatasetId | str,
        partition_values: Iterable[str],
    ) -> pd.DataFrame:
        dataset = ResearchDatasetId(dataset_id)
        partitions = _normalized_partition_values(partition_values)
        paths: list[Path] = []
        for partition in partitions:
            path = self._partition_path(dataset, partition)
            if path.is_file():
                paths.append(path)
        if not paths:
            return pd.DataFrame()
        with duckdb.connect() as connection:
            return connection.execute(
                "select * from read_parquet(?, union_by_name=true, "
                "hive_partitioning=false)",
                [[str(path) for path in paths]],
            ).fetchdf()

    def revision_count(self, dataset_id: ResearchDatasetId | str) -> int:
        with connect_research_warehouse(self.duckdb_path, read_only=True) as connection:
            return int(
                connection.execute(
                    "select count(*) from research_fact_revisions where dataset_id = ?",
                    [ResearchDatasetId(dataset_id).value],
                ).fetchone()[0]
            )

    def revision_rows(
        self,
        dataset_id: ResearchDatasetId | str,
        *,
        partition_values: Iterable[str] | None = None,
    ) -> list[dict[str, Any]]:
        dataset = ResearchDatasetId(dataset_id)
        parameters: list[Any] = [dataset.value]
        partition_filter = ""
        if partition_values is not None:
            partitions = _normalized_partition_values(partition_values)
            if not partitions:
                return []
            placeholders = ",".join("?" for _ in partitions)
            partition_filter = f" and partition_value in ({placeholders})"
            parameters.extend(partitions)
        with connect_research_warehouse(self.duckdb_path, read_only=True) as connection:
            cursor = connection.execute(
                f"""
                select business_key_hash, revision_no, partition_value, row_payload,
                       cast(valid_from as varchar), cast(valid_to as varchar)
                from research_fact_revisions
                where dataset_id = ?
                {partition_filter}
                order by business_key_hash, revision_no
                """,
                parameters,
            )
            rows = cursor.fetchall()
        return [
            {
                "business_key_hash": row[0],
                "revision_no": int(row[1]),
                "partition_value": str(row[2]),
                "row_payload": _from_json(row[3]),
                "valid_from": _parse_datetime(row[4]),
                "valid_to": _parse_datetime(row[5]),
            }
            for row in rows
        ]

    def partition_manifest(
        self,
        dataset_id: ResearchDatasetId | str,
        *,
        partition_values: Iterable[str] | None = None,
    ) -> pd.DataFrame:
        dataset = ResearchDatasetId(dataset_id)
        parameters: list[Any] = [dataset.value]
        partition_filter = ""
        if partition_values is not None:
            partitions = _normalized_partition_values(partition_values)
            if not partitions:
                return pd.DataFrame()
            placeholders = ",".join("?" for _ in partitions)
            partition_filter = f" and partition_value in ({placeholders})"
            parameters.extend(partitions)
        with connect_research_warehouse(self.duckdb_path, read_only=True) as connection:
            return connection.execute(
                f"""
                select * from research_fact_partitions
                where dataset_id = ?
                {partition_filter}
                order by partition_value
                """,
                parameters,
            ).fetchdf()

    def prune_partitions_before(
        self,
        dataset_id: ResearchDatasetId | str,
        keep_from_partition: str,
    ) -> tuple[str, ...]:
        dataset = ResearchDatasetId(dataset_id)
        manifest = self.partition_manifest(dataset)
        if manifest.empty:
            return ()
        selected = manifest.loc[
            manifest["partition_value"].astype(str) < str(keep_from_partition),
            ["partition_value", "relative_path"],
        ].sort_values("partition_value")
        if selected.empty:
            return ()

        prune_root = self.staging_root / "prune" / uuid4().hex
        moved: list[tuple[Path, Path]] = []
        partitions = tuple(selected["partition_value"].astype(str).tolist())
        try:
            for row in selected.to_dict(orient="records"):
                source_file = self.root / str(row["relative_path"])
                if not source_file.is_file():
                    raise FileNotFoundError(source_file)
                source_dir = source_file.parent
                staged_dir = prune_root / source_dir.relative_to(self.root)
                staged_dir.parent.mkdir(parents=True, exist_ok=True)
                source_dir.replace(staged_dir)
                moved.append((source_dir, staged_dir))

            with connect_research_warehouse(self.duckdb_path) as connection:
                connection.begin()
                try:
                    self._delete_partition_metadata(
                        connection, dataset, partitions
                    )
                except Exception:
                    connection.rollback()
                    raise
                connection.commit()
        except Exception:
            for source_dir, staged_dir in reversed(moved):
                if staged_dir.exists():
                    source_dir.parent.mkdir(parents=True, exist_ok=True)
                    staged_dir.replace(source_dir)
            shutil.rmtree(prune_root, ignore_errors=True)
            raise

        shutil.rmtree(prune_root, ignore_errors=True)
        return partitions

    def replace_dataset_batches(
        self,
        dataset_id: ResearchDatasetId | str,
        batches: Iterable[FactBatch],
    ) -> None:
        """Atomically replace one dataset after rebuilding all current partitions."""
        dataset = ResearchDatasetId(dataset_id)
        prepared = tuple(batches)
        if any(batch.dataset_id is not dataset for batch in prepared):
            raise ValueError("replacement batches must belong to one dataset")
        partitions = [batch.partition_value for batch in prepared]
        if len(partitions) != len(set(partitions)):
            raise ValueError("replacement batches must have unique partitions")

        rebuild_root = self.staging_root / f"rebuild-{uuid4().hex}"
        rebuilt = ResearchWarehouse(rebuild_root)
        for batch in prepared:
            rebuilt.commit_batch(batch)

        source_dir = rebuilt.facts_root / dataset.value
        source_dir.mkdir(parents=True, exist_ok=True)
        target_dir = self.facts_root / dataset.value
        swap_root = self.staging_root / f"swap-{uuid4().hex}"
        backup_dir = swap_root / "previous"
        swap_root.mkdir(parents=True, exist_ok=True)
        had_previous = target_dir.exists()
        if had_previous:
            target_dir.replace(backup_dir)
        target_dir.parent.mkdir(parents=True, exist_ok=True)
        source_dir.replace(target_dir)

        try:
            with connect_research_warehouse(self.duckdb_path) as connection:
                rebuilt_path = str(rebuilt.duckdb_path).replace("'", "''")
                connection.execute(
                    f"attach '{rebuilt_path}' as rebuilt_db (read_only)"
                )
                connection.begin()
                try:
                    connection.execute(
                        "delete from research_fact_revisions where dataset_id = ?",
                        [dataset.value],
                    )
                    connection.execute(
                        "delete from research_fact_keys where dataset_id = ?",
                        [dataset.value],
                    )
                    connection.execute(
                        "delete from research_fact_partitions where dataset_id = ?",
                        [dataset.value],
                    )
                    connection.execute(
                        """
                        insert into research_fact_partitions
                        select * from rebuilt_db.research_fact_partitions
                        where dataset_id = ?
                        """,
                        [dataset.value],
                    )
                    connection.execute(
                        """
                        insert into research_fact_keys
                        select * from rebuilt_db.research_fact_keys
                        where dataset_id = ?
                        """,
                        [dataset.value],
                    )
                    connection.execute(
                        """
                        insert into research_fact_revisions
                        select * from rebuilt_db.research_fact_revisions
                        where dataset_id = ?
                        """,
                        [dataset.value],
                    )
                except Exception:
                    connection.rollback()
                    connection.execute("detach rebuilt_db")
                    raise
                connection.commit()
                connection.execute("detach rebuilt_db")
        except Exception:
            target_dir.replace(source_dir)
            if had_previous:
                backup_dir.replace(target_dir)
            shutil.rmtree(rebuild_root, ignore_errors=True)
            shutil.rmtree(swap_root, ignore_errors=True)
            raise

        shutil.rmtree(rebuild_root, ignore_errors=True)
        shutil.rmtree(swap_root, ignore_errors=True)

    def _delete_partition_metadata(
        self,
        connection: duckdb.DuckDBPyConnection,
        dataset: ResearchDatasetId,
        partitions: tuple[str, ...],
    ) -> None:
        placeholders = ",".join("?" for _ in partitions)
        parameters = [dataset.value, *partitions]
        connection.execute(
            f"""
            delete from research_fact_revisions
            where dataset_id = ? and partition_value in ({placeholders})
            """,
            parameters,
        )
        connection.execute(
            f"""
            delete from research_fact_keys
            where dataset_id = ? and partition_value in ({placeholders})
            """,
            parameters,
        )
        connection.execute(
            f"""
            delete from research_fact_partitions
            where dataset_id = ? and partition_value in ({placeholders})
            """,
            parameters,
        )

    def _normalize_batch(self, batch: FactBatch) -> pd.DataFrame:
        contract = research_contract(batch.dataset_id)
        rows: list[dict[str, Any]] = []
        for raw in batch.records:
            missing = [field for field in contract.business_key if raw.get(field) is None]
            if missing:
                raise ValueError(
                    f"missing business key fields for {batch.dataset_id.value}: {missing}"
                )
            row = {key: _parquet_safe(value) for key, value in raw.items()}
            available_at = raw.get("available_at", batch.default_available_at)
            if available_at is None:
                raise ValueError("available_at is required for every fact")
            key_payload = {field: _json_safe(raw[field]) for field in contract.business_key}
            business_payload = {
                key: _json_safe(value)
                for key, value in raw.items()
                if key not in _GOVERNANCE_FIELDS
            }
            row.update(
                {
                    "source_name": raw.get("source_name", batch.source_name),
                    "source_endpoint": raw.get("source_endpoint", batch.source_endpoint),
                    "source_record_id": raw.get(
                        "source_record_id", _stable_hash(key_payload)
                    ),
                    "source_updated_at": _parquet_safe(raw.get("source_updated_at")),
                    "available_at": _as_utc(available_at),
                    "availability_precision": raw.get(
                        "availability_precision", batch.availability_precision.value
                    ),
                    "ingested_at": _as_utc(batch.ingested_at),
                    "ingestion_run_id": batch.ingestion_run_id,
                    "payload_hash": _stable_hash(business_payload),
                    "business_key_hash": _stable_hash(key_payload),
                    "quality_status": "passed",
                    "revision_no": 1,
                }
            )
            rows.append(row)
        return pd.DataFrame(rows)

    def _validate_frame(
        self,
        dataset_id: ResearchDatasetId,
        frame: pd.DataFrame,
        business_key: tuple[str, ...],
    ) -> None:
        if frame.empty:
            return
        duplicates = frame.duplicated(subset=list(business_key), keep=False)
        if duplicates.any():
            raise ValueError(
                f"duplicate business key in {dataset_id.value}: "
                f"{int(duplicates.sum())} rows"
            )
        ohlc_datasets = {
            ResearchDatasetId.EQUITY_DAILY,
            ResearchDatasetId.INDEX_DAILY,
            ResearchDatasetId.INDUSTRY_DAILY,
            ResearchDatasetId.THEME_DAILY,
            ResearchDatasetId.MINUTE_BAR,
        }
        if dataset_id in ohlc_datasets and {"open", "high", "low", "close"} <= set(frame):
            invalid = (
                (frame["high"] < frame[["open", "close", "low"]].max(axis=1))
                | (frame["low"] > frame[["open", "close", "high"]].min(axis=1))
            )
            if invalid.any():
                raise ValueError(f"OHLC relationship failed for {dataset_id.value}")
        for field in ("vol", "volume", "amount"):
            if field in frame and (pd.to_numeric(frame[field], errors="coerce") < 0).any():
                raise ValueError(f"negative {field} in {dataset_id.value}")

    def _merge(
        self,
        existing: pd.DataFrame,
        incoming: pd.DataFrame,
        business_key: tuple[str, ...],
        batch: FactBatch,
    ) -> tuple[pd.DataFrame, list[dict[str, Any]], tuple[int, int, int]]:
        if existing.empty:
            return incoming.sort_values(list(business_key)).reset_index(drop=True), [], (
                len(incoming),
                0,
                0,
            )
        if incoming.empty:
            return existing, [], (0, 0, 0)

        old_by_hash = {
            str(row["business_key_hash"]): row
            for row in existing.to_dict(orient="records")
        }
        new_by_hash = {
            str(row["business_key_hash"]): row
            for row in incoming.to_dict(orient="records")
        }
        revisions: list[dict[str, Any]] = []
        new_rows = 0
        changed_rows = 0
        unchanged_rows = 0
        merged_by_hash = dict(old_by_hash)

        for key_hash, new_row in new_by_hash.items():
            old_row = old_by_hash.get(key_hash)
            if old_row is None:
                new_rows += 1
                merged_by_hash[key_hash] = new_row
                continue
            if str(old_row["payload_hash"]) == str(new_row["payload_hash"]):
                unchanged_rows += 1
                merged_by_hash[key_hash] = old_row
                continue
            changed_rows += 1
            old_revision = int(old_row.get("revision_no", 1))
            new_row["revision_no"] = old_revision + 1
            revisions.append(
                {
                    "dataset_id": batch.dataset_id.value,
                    "business_key_hash": key_hash,
                    "revision_no": old_revision,
                    "partition_value": batch.partition_value,
                    "payload_hash": str(old_row["payload_hash"]),
                    "row_payload": _row_json(old_row),
                    "valid_from": _as_utc(old_row["available_at"]),
                    "valid_to": _as_utc(new_row["available_at"]),
                    "superseded_by_run_id": batch.ingestion_run_id,
                    "changed_fields": _changed_business_fields(old_row, new_row),
                }
            )
            merged_by_hash[key_hash] = new_row

        merged = pd.DataFrame(list(merged_by_hash.values()))
        merged = merged.sort_values(list(business_key)).reset_index(drop=True)
        self._validate_frame(batch.dataset_id, merged, business_key)
        return merged, revisions, (new_rows, changed_rows, unchanged_rows)

    def _commit_metadata(
        self,
        batch: FactBatch,
        frame: pd.DataFrame,
        final_path: Path,
        content_hash: str,
        file_sha256: str,
        revisions: list[dict[str, Any]],
    ) -> None:
        available = pd.to_datetime(frame.get("available_at"), utc=True, errors="coerce")
        min_available = None if frame.empty else available.min().to_pydatetime()
        max_available = None if frame.empty else available.max().to_pydatetime()
        sources = sorted(set(frame.get("source_name", pd.Series(dtype=str)).dropna().astype(str)))
        with connect_research_warehouse(self.duckdb_path) as connection:
            connection.begin()
            try:
                for revision in revisions:
                    connection.execute(
                        """
                        insert into research_fact_revisions values
                        (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        on conflict(dataset_id, business_key_hash, revision_no)
                        do nothing
                        """,
                        [
                            revision["dataset_id"],
                            revision["business_key_hash"],
                            revision["revision_no"],
                            revision["partition_value"],
                            revision["payload_hash"],
                            json.dumps(revision["row_payload"], ensure_ascii=False, sort_keys=True),
                            revision["valid_from"],
                            revision["valid_to"],
                            revision["superseded_by_run_id"],
                            json.dumps(revision["changed_fields"], ensure_ascii=False, sort_keys=True),
                        ],
                    )
                connection.execute(
                    """
                    insert into research_fact_partitions
                    (dataset_id, partition_value, relative_path, row_count,
                     content_hash, file_sha256, min_available_at, max_available_at,
                     source_names, committed_at, ingestion_run_id, quality_status)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, now(), ?, 'passed')
                    on conflict(dataset_id, partition_value) do update set
                        relative_path = excluded.relative_path,
                        row_count = excluded.row_count,
                        content_hash = excluded.content_hash,
                        file_sha256 = excluded.file_sha256,
                        min_available_at = excluded.min_available_at,
                        max_available_at = excluded.max_available_at,
                        source_names = excluded.source_names,
                        committed_at = excluded.committed_at,
                        ingestion_run_id = excluded.ingestion_run_id,
                        quality_status = excluded.quality_status
                    """,
                    [
                        batch.dataset_id.value,
                        batch.partition_value,
                        final_path.relative_to(self.root).as_posix(),
                        len(frame),
                        content_hash,
                        file_sha256,
                        min_available,
                        max_available,
                        json.dumps(sources, ensure_ascii=False),
                        batch.ingestion_run_id,
                    ],
                )
                if batch.dataset_id in _GLOBAL_KEY_INDEX_DATASETS:
                    connection.execute(
                        """
                        insert or ignore into research_fact_keys
                        (dataset_id, business_key_hash, partition_value)
                        select ?, cast(business_key_hash as varchar), ?
                        from read_parquet(?, hive_partitioning=false)
                        """,
                        [
                            batch.dataset_id.value,
                            batch.partition_value,
                            str(final_path),
                        ],
                    )
            except Exception:
                connection.rollback()
                raise
            connection.commit()

    def _partition_metadata(
        self,
        dataset_id: ResearchDatasetId,
        partition_value: str,
    ) -> tuple[str, str] | None:
        with connect_research_warehouse(self.duckdb_path, read_only=True) as connection:
            row = connection.execute(
                """
                select content_hash, file_sha256 from research_fact_partitions
                where dataset_id = ? and partition_value = ?
                """,
                [dataset_id.value, partition_value],
            ).fetchone()
        return None if row is None else (str(row[0]), str(row[1]))

    def _assert_partition_ownership(
        self,
        dataset_id: ResearchDatasetId,
        partition_value: str,
        key_hashes: set[str],
    ) -> None:
        if dataset_id not in _GLOBAL_KEY_INDEX_DATASETS or not key_hashes:
            return
        hashes = sorted(key_hashes)
        with connect_research_warehouse(self.duckdb_path, read_only=True) as connection:
            for start in range(0, len(hashes), 500):
                chunk = hashes[start : start + 500]
                placeholders = ",".join("?" for _ in chunk)
                rows = connection.execute(
                    f"""
                    select business_key_hash, partition_value
                    from research_fact_keys
                    where dataset_id = ?
                      and business_key_hash in ({placeholders})
                      and partition_value <> ?
                    """,
                    [dataset_id.value, *chunk, partition_value],
                ).fetchall()
                if rows:
                    raise ValueError(
                        f"business key belongs to a different partition in "
                        f"{dataset_id.value}: {rows[0][1]}"
                    )

    def _ensure_fact_key_index(self) -> None:
        with connect_research_warehouse(self.duckdb_path) as connection:
            marker = connection.execute(
                "select value from research_metadata where key = 'fact_key_index_built'"
            ).fetchone()
            if marker is not None:
                return
            manifests = connection.execute(
                """
                select dataset_id, partition_value, relative_path
                from research_fact_partitions
                order by dataset_id, partition_value
                """
            ).fetchall()
            connection.begin()
            try:
                connection.execute("delete from research_fact_keys")
                for dataset_id, partition_value, relative_path in manifests:
                    if ResearchDatasetId(str(dataset_id)) not in _GLOBAL_KEY_INDEX_DATASETS:
                        continue
                    parquet_path = self.root / str(relative_path)
                    if not parquet_path.is_file():
                        raise FileNotFoundError(parquet_path)
                    connection.execute(
                        """
                        insert into research_fact_keys
                        select ?, cast(business_key_hash as varchar), ?
                        from read_parquet(?, hive_partitioning=false)
                        """,
                        [str(dataset_id), str(partition_value), str(parquet_path)],
                    )
                connection.execute(
                    "insert or replace into research_metadata values "
                    "('fact_key_index_built', '1')"
                )
            except Exception:
                connection.rollback()
                raise
            connection.commit()

    def _validate_partition_semantics(
        self,
        batch: FactBatch,
        frame: pd.DataFrame,
    ) -> None:
        if frame.empty:
            return
        if batch.dataset_id in _EXACT_DATE_PARTITION_DATASETS:
            values = {
                pd.Timestamp(value).date().isoformat()
                for value in frame["trade_date"].dropna().tolist()
            }
            if values != {batch.partition_value}:
                raise ValueError(
                    f"partition does not match trade_date in {batch.dataset_id.value}"
                )
        elif batch.dataset_id is ResearchDatasetId.TRADE_CALENDAR:
            years = {
                str(pd.Timestamp(value).year)
                for value in frame["cal_date"].dropna().tolist()
            }
            if years != {batch.partition_value}:
                raise ValueError("partition does not match calendar year")

    def _partition_path(
        self,
        dataset_id: ResearchDatasetId,
        partition_value: str,
    ) -> Path:
        contract = research_contract(dataset_id)
        return (
            self.facts_root
            / dataset_id.value
            / f"{contract.partition_field}={_safe_partition(partition_value)}"
            / "data.parquet"
        )

    def _read_path(self, path: Path) -> pd.DataFrame:
        if not path.is_file():
            return pd.DataFrame()
        return pd.read_parquet(path)

    def _frame_content_hash(self, frame: pd.DataFrame) -> str:
        if frame.empty:
            return hashlib.sha256(b"[]").hexdigest()
        rows = sorted(
            (
                str(row["business_key_hash"]),
                str(row["payload_hash"]),
                int(row.get("revision_no", 1)),
            )
            for row in frame.to_dict(orient="records")
        )
        return _stable_hash(rows)


def _changed_business_fields(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    keys = (set(old) | set(new)) - _GOVERNANCE_FIELDS
    return sorted(
        key for key in keys if _json_safe(old.get(key)) != _json_safe(new.get(key))
    )


def _row_json(row: dict[str, Any]) -> dict[str, Any]:
    return {key: _json_safe(value) for key, value in row.items()}


def _parquet_safe(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list, tuple, set)):
        return json.dumps(_json_safe(value), ensure_ascii=False, sort_keys=True)
    if isinstance(value, datetime):
        return _as_utc(value)
    return value


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, pd.Timestamp)):
        return _as_utc(value).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if pd.isna(value):
        return None
    return str(value)


def _stable_hash(value: Any) -> str:
    encoded = json.dumps(
        _json_safe(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _as_utc(value: Any) -> datetime:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp.to_pydatetime()


def _parse_datetime(value: Any) -> datetime:
    return _as_utc(value)


def _from_json(value: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    return value


def _safe_partition(value: str) -> str:
    return value.replace("/", "_").replace("..", "_")


def _normalized_partition_values(values: Iterable[str]) -> tuple[str, ...]:
    if isinstance(values, str):
        values = (values,)
    return tuple(sorted({str(value) for value in values}))


__all__ = ["FactCommitResult", "ResearchWarehouse"]
