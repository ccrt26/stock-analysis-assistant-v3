from __future__ import annotations

import argparse
import json
import os
import shutil
from datetime import date
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from stock_analyzer.config import AppConfig
from stock_analyzer.data.research_contracts import ResearchDatasetId, research_contract
from stock_analyzer.storage.research_parquet import (
    atomic_promote,
    discard_backup,
    restore_previous,
    sha256_file,
    write_staged_parquet,
)
from stock_analyzer.storage.research_schema import connect_research_warehouse
from stock_analyzer.storage.research_warehouse import (
    ResearchWarehouse,
    _GOVERNANCE_FIELDS,
    _json_safe,
    _stable_hash,
)


MIGRATION_ID = "2026-08-04-known-data-foundation-faults-v2"
INTERRUPTED_PROMOTION_RECOVERY_ID = "2026-08-04-interrupted-promotion-recovery-v1"
_INDUSTRY_IDENTITY = ("industry_system", "level", "industry_code")
_INDUSTRY_TIME_FIELDS = {"valid_from", "valid_to"}


def run_known_data_repair(
    warehouse_root: Path,
    archive_root: Path,
    *,
    migration_id: str = MIGRATION_ID,
) -> dict[str, Any]:
    warehouse = ResearchWarehouse(Path(warehouse_root))
    repair_root = Path(archive_root) / "repairs" / migration_id
    receipt_path = repair_root / "receipt.json"

    prior = _prior_migration(warehouse.duckdb_path, migration_id)
    if prior is not None:
        report = dict(prior)
        report["status"] = "already_applied"
        report["partitions_before"] = _backed_up_partition_receipt(
            warehouse,
            repair_root,
            report.get("partitions_before", ()),
        )
        report["partitions_after"] = _current_partition_receipt(
            warehouse,
            report.get("partitions_after", ()),
        )
        _replace_migration_report(warehouse.duckdb_path, migration_id, report)
        _write_json_atomic(receipt_path, report)
        return report

    industry_partition = "SW2021"
    industry = warehouse.read_current(
        ResearchDatasetId.INDUSTRY_CATALOG,
        partition_value=industry_partition,
    )
    repaired_industry, industry_audit = _repair_industry_catalog(industry)

    revisions = _announcement_revision_rows(warehouse.duckdb_path)
    announcement_partitions = sorted({row["partition_value"] for row in revisions})
    announcements = {
        partition: warehouse.read_current(
            ResearchDatasetId.ANNOUNCEMENT,
            partition_value=partition,
        )
        for partition in announcement_partitions
    }
    repaired_announcements, folded_hashes, announcement_audit = (
        _repair_announcement_jitter(announcements, revisions)
    )

    affected: dict[tuple[ResearchDatasetId, str], pd.DataFrame] = {}
    if industry_audit["removed_rows"]:
        affected[(ResearchDatasetId.INDUSTRY_CATALOG, industry_partition)] = (
            repaired_industry
        )
    for partition, frame in repaired_announcements.items():
        affected[(ResearchDatasetId.ANNOUNCEMENT, partition)] = frame

    if not affected:
        raise ValueError("known data faults were not found; refusing no-op migration")

    original_affected: dict[tuple[ResearchDatasetId, str], pd.DataFrame] = {}
    for key in affected:
        dataset, partition = key
        original_affected[key] = (
            industry
            if dataset is ResearchDatasetId.INDUSTRY_CATALOG
            else announcements[partition]
        )
    before = _partition_receipt(warehouse, original_affected)
    backup_manifest = _backup_affected_state(
        warehouse,
        repair_root,
        affected,
        folded_hashes,
        migration_id,
    )
    source_manifest_hash = _stable_hash(backup_manifest)
    staged = _stage_frames(warehouse, affected, migration_id)
    promoted: list[tuple[Path, Path | None]] = []
    try:
        for key, staged_path in staged.items():
            final_path = warehouse._partition_path(*key)
            promoted.append((final_path, atomic_promote(staged_path, final_path)))

        after = _commit_repaired_metadata(
            warehouse,
            affected,
            folded_hashes,
            migration_id,
            source_manifest_hash,
            industry_audit,
            announcement_audit,
            before,
        )
    except Exception:
        for final_path, backup_path in reversed(promoted):
            restore_previous(final_path, backup_path)
        raise
    else:
        for _, backup_path in promoted:
            discard_backup(backup_path)
    finally:
        shutil.rmtree(warehouse.staging_root / migration_id, ignore_errors=True)

    report = {
        "migration_id": migration_id,
        "status": "completed",
        "warehouse_root": str(warehouse.root.resolve()),
        "backup_root": str((repair_root / "backups").resolve()),
        "source_manifest_hash": source_manifest_hash,
        "industry_catalog": industry_audit,
        "announcement": announcement_audit,
        "partitions_before": before,
        "partitions_after": after,
    }
    _replace_migration_report(warehouse.duckdb_path, migration_id, report)
    _write_json_atomic(receipt_path, report)
    return report


def recover_interrupted_promotion(
    warehouse_root: Path,
    archive_root: Path,
    relative_path: str,
) -> dict[str, Any]:
    root = Path(warehouse_root).resolve()
    final_path = (root / relative_path).resolve()
    if root not in final_path.parents or final_path.name != "data.parquet":
        raise ValueError(f"unsafe fact partition path: {relative_path}")
    previous_path = final_path.with_suffix(".parquet.previous")
    recovery_root = (
        Path(archive_root)
        / "repairs"
        / INTERRUPTED_PROMOTION_RECOVERY_ID
        / _stable_hash(relative_path)[:16]
    )
    receipt_path = recovery_root / "receipt.json"
    with connect_research_warehouse(root / "research.duckdb", read_only=True) as connection:
        row = connection.execute(
            """
            select dataset_id, partition_value, file_sha256
            from research_fact_partitions where relative_path = ?
            """,
            [relative_path],
        ).fetchone()
    if row is None:
        raise ValueError(f"partition metadata is missing: {relative_path}")
    expected_sha = str(row[2])
    if not previous_path.is_file():
        if final_path.is_file() and sha256_file(final_path) == expected_sha and receipt_path.is_file():
            report = json.loads(receipt_path.read_text(encoding="utf-8"))
            report["status"] = "already_recovered"
            _write_json_atomic(receipt_path, report)
            return report
        raise ValueError(f"no recoverable previous partition: {relative_path}")
    if not final_path.is_file():
        raise FileNotFoundError(final_path)
    previous_sha = sha256_file(previous_path)
    orphan_sha = sha256_file(final_path)
    if previous_sha != expected_sha:
        raise ValueError("previous partition does not match DuckDB metadata")
    if orphan_sha == expected_sha:
        raise ValueError("current partition already matches metadata; refusing recovery")
    if recovery_root.exists():
        raise FileExistsError(f"recovery backup already exists: {recovery_root}")

    backup_root = recovery_root / "backups"
    backup_root.mkdir(parents=True, exist_ok=False)
    shutil.copy2(final_path, backup_root / "orphan-promoted.parquet")
    shutil.copy2(previous_path, backup_root / "metadata-matched-previous.parquet")
    metadata_path = backup_root / "research_fact_partition.parquet"
    with connect_research_warehouse(root / "research.duckdb", read_only=True) as connection:
        connection.execute(
            "copy (select * from research_fact_partitions where relative_path = "
            f"'{_sql(relative_path)}') to '{_sql(str(metadata_path))}' (format parquet)"
        )
    quarantined = recovery_root / "quarantine" / "orphan-promoted.parquet"
    quarantined.parent.mkdir(parents=True, exist_ok=True)
    os.replace(final_path, quarantined)
    try:
        os.replace(previous_path, final_path)
    except Exception:
        os.replace(quarantined, final_path)
        raise
    restored_sha = sha256_file(final_path)
    if restored_sha != expected_sha:
        raise ValueError("restored partition hash does not match DuckDB metadata")
    report = {
        "recovery_id": INTERRUPTED_PROMOTION_RECOVERY_ID,
        "status": "recovered",
        "dataset_id": str(row[0]),
        "partition_value": str(row[1]),
        "relative_path": relative_path,
        "metadata_expected_sha256": expected_sha,
        "orphan_sha256": orphan_sha,
        "restored_sha256": restored_sha,
        "backup_root": str(backup_root.resolve()),
        "quarantined_orphan": str(quarantined.resolve()),
    }
    _write_json_atomic(receipt_path, report)
    return report


def _repair_industry_catalog(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    if frame.empty:
        raise ValueError("industry_catalog:SW2021 is missing")
    rows = frame.to_dict(orient="records")
    repaired: list[dict[str, Any]] = []
    merged_entities: list[dict[str, Any]] = []
    grouped: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for row in rows:
        identity = tuple(str(row[field]) for field in _INDUSTRY_IDENTITY)
        grouped.setdefault(identity, []).append(row)

    for identity, entity_rows in grouped.items():
        ordered = sorted(entity_rows, key=lambda row: _as_date(row["valid_from"]))
        clusters: list[list[dict[str, Any]]] = []
        for row in ordered:
            if not clusters or not _industry_intervals_overlap(clusters[-1], row):
                clusters.append([row])
            else:
                clusters[-1].append(row)
        for cluster in clusters:
            if len(cluster) == 1:
                repaired.append(cluster[0])
                continue
            signatures = {_substantive_signature(row, _INDUSTRY_TIME_FIELDS) for row in cluster}
            if len(signatures) != 1:
                raise ValueError(
                    "overlapping industry definitions differ for " + "/".join(identity)
                )
            keeper = dict(min(cluster, key=lambda row: _as_date(row["valid_from"])))
            ends = [_optional_date(row.get("valid_to")) for row in cluster]
            keeper["valid_to"] = None if any(end is None for end in ends) else max(ends)
            _refresh_fact_hashes(ResearchDatasetId.INDUSTRY_CATALOG, keeper)
            repaired.append(keeper)
            merged_entities.append(
                {
                    "industry_system": identity[0],
                    "level": identity[1],
                    "industry_code": identity[2],
                    "kept_valid_from": _as_date(keeper["valid_from"]).isoformat(),
                    "removed_valid_from": sorted(
                        _as_date(row["valid_from"]).isoformat()
                        for row in cluster
                        if row is not min(cluster, key=lambda item: _as_date(item["valid_from"]))
                    ),
                }
            )

    result = pd.DataFrame(repaired, columns=frame.columns).sort_values(
        list(research_contract(ResearchDatasetId.INDUSTRY_CATALOG).business_key)
    ).reset_index(drop=True)
    _assert_no_industry_overlaps(result)
    return result, {
        "rows_before": len(frame),
        "rows_after": len(result),
        "removed_rows": len(frame) - len(result),
        "merged_entities": merged_entities,
        "time_basis": "earliest locally observed valid_from retained",
    }


def _repair_announcement_jitter(
    frames: dict[str, pd.DataFrame],
    revisions: list[dict[str, Any]],
) -> tuple[dict[str, pd.DataFrame], set[str], dict[str, Any]]:
    by_hash: dict[str, list[dict[str, Any]]] = {}
    for row in revisions:
        by_hash.setdefault(row["business_key_hash"], []).append(row)
    current: dict[str, tuple[str, int, dict[str, Any]]] = {}
    for partition, frame in frames.items():
        for index, row in frame.iterrows():
            current[str(row["business_key_hash"])] = (partition, index, row.to_dict())

    repaired = {partition: frame.copy() for partition, frame in frames.items()}
    folded: set[str] = set()
    audits: list[dict[str, Any]] = []
    for key_hash, chain in sorted(by_hash.items()):
        if key_hash not in current:
            raise ValueError(f"announcement revision has no current row: {key_hash}")
        if any(
            row["changed_fields"] not in ([], ["announcement_time"])
            for row in chain
        ):
            continue
        partition, index, current_row = current[key_hash]
        payloads = [row["row_payload"] for row in chain] + [current_row]
        signatures = {
            _substantive_signature(payload, {"announcement_time"})
            for payload in payloads
        }
        if len(signatures) != 1:
            continue
        times = [_as_timestamp(payload.get("announcement_time")) for payload in payloads]
        if max(times) - min(times) > pd.Timedelta(seconds=1):
            continue
        canonical = max(times)
        canonical_payloads = [
            payload
            for payload, timestamp in zip(payloads, times, strict=True)
            if timestamp == canonical
        ]
        if any(payload.get("payload_hash") is None for payload in canonical_payloads):
            raise ValueError(
                f"announcement canonical payload hash is missing: {key_hash}"
            )
        canonical_payload_hashes = {
            str(payload.get("payload_hash")) for payload in canonical_payloads
        }
        if len(canonical_payload_hashes) != 1:
            if all(row["changed_fields"] == [] for row in chain):
                canonical_payload_hashes = {str(current_row["payload_hash"])}
            else:
                raise ValueError(
                    f"announcement canonical payload hash is ambiguous: {key_hash}"
                )
        updated = dict(current_row)
        updated["announcement_time"] = canonical
        updated["available_at"] = canonical
        updated["revision_no"] = 1
        updated["payload_hash"] = canonical_payload_hashes.pop()
        for column, value in updated.items():
            repaired[partition].at[index, column] = value
        folded.add(key_hash)
        audits.append(
            {
                "announcement_id": str(current_row.get("announcement_id")),
                "business_key_hash": key_hash,
                "partition_value": partition,
                "folded_revision_rows": len(chain),
                "observed_times": sorted({timestamp.isoformat() for timestamp in times}),
                "canonical_time": canonical.isoformat(),
                "repair_basis": "maximum observed upstream publication time; no receipt time invented",
            }
        )

    if by_hash and not folded:
        raise ValueError("no announcement revision chain was safe to fold")
    for partition, frame in repaired.items():
        repaired[partition] = frame.sort_values("announcement_id").reset_index(drop=True)
    return repaired, folded, {
        "candidate_business_keys": len(by_hash),
        "folded_business_keys": len(folded),
        "folded_revision_rows": sum(item["folded_revision_rows"] for item in audits),
        "chains": audits,
        "unfolded_business_keys": sorted(set(by_hash) - folded),
    }


def _backup_affected_state(
    warehouse: ResearchWarehouse,
    repair_root: Path,
    affected: dict[tuple[ResearchDatasetId, str], pd.DataFrame],
    folded_hashes: set[str],
    migration_id: str,
) -> list[dict[str, Any]]:
    backup_root = repair_root / "backups"
    if backup_root.exists():
        raise FileExistsError(f"backup already exists without migration receipt: {backup_root}")
    files: list[Path] = []
    for dataset, partition in affected:
        source = warehouse._partition_path(dataset, partition)
        target = backup_root / source.relative_to(warehouse.root)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        files.append(target)

    metadata_root = backup_root / "duckdb_metadata"
    metadata_root.mkdir(parents=True, exist_ok=True)
    pairs = [(dataset.value, partition) for dataset, partition in affected]
    with connect_research_warehouse(warehouse.duckdb_path, read_only=True) as connection:
        pair_predicate = " or ".join(
            f"(dataset_id = '{_sql(dataset)}' and partition_value = '{_sql(partition)}')"
            for dataset, partition in pairs
        )
        hash_predicate = ",".join(f"'{_sql(value)}'" for value in sorted(folded_hashes))
        queries = {
            "research_fact_partitions.parquet": (
                f"select * from research_fact_partitions where {pair_predicate}"
            ),
            "research_fact_keys.parquet": (
                f"select * from research_fact_keys where {pair_predicate}"
            ),
            "research_fact_revisions.parquet": (
                "select * from research_fact_revisions where dataset_id = 'announcement' "
                f"and business_key_hash in ({hash_predicate})"
            ),
            "research_migrations.parquet": (
                "select * from research_migrations "
                f"where migration_id = '{_sql(migration_id)}'"
            ),
        }
        for name, query in queries.items():
            target = metadata_root / name
            connection.execute(
                f"copy ({query}) to '{_sql(str(target))}' (format parquet)"
            )
            files.append(target)

    manifest = [
        {
            "relative_path": str(path.relative_to(repair_root)),
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in sorted(files)
    ]
    _write_json_atomic(repair_root / "backup-manifest.json", manifest)
    return manifest


def _stage_frames(
    warehouse: ResearchWarehouse,
    affected: dict[tuple[ResearchDatasetId, str], pd.DataFrame],
    migration_id: str,
) -> dict[tuple[ResearchDatasetId, str], Path]:
    staged: dict[tuple[ResearchDatasetId, str], Path] = {}
    for (dataset, partition), frame in affected.items():
        path = warehouse.staging_root / migration_id / dataset.value / f"{partition}.parquet"
        write_staged_parquet(path, frame)
        staged[(dataset, partition)] = path
    return staged


def _commit_repaired_metadata(
    warehouse: ResearchWarehouse,
    affected: dict[tuple[ResearchDatasetId, str], pd.DataFrame],
    folded_hashes: set[str],
    migration_id: str,
    source_manifest_hash: str,
    industry_audit: dict[str, Any],
    announcement_audit: dict[str, Any],
    before: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    after = _partition_receipt(warehouse, affected)
    provisional_report = {
        "migration_id": migration_id,
        "status": "completed",
        "warehouse_root": str(warehouse.root.resolve()),
        "backup_root": "recorded in external receipt",
        "source_manifest_hash": source_manifest_hash,
        "industry_catalog": industry_audit,
        "announcement": announcement_audit,
        "partitions_before": before,
        "partitions_after": after,
    }
    with connect_research_warehouse(warehouse.duckdb_path) as connection:
        connection.begin()
        try:
            for (dataset, partition), frame in affected.items():
                row = next(
                    item
                    for item in after
                    if item["dataset_id"] == dataset.value
                    and item["partition_value"] == partition
                )
                available = pd.to_datetime(frame["available_at"], utc=True, errors="raise")
                sources = sorted(set(frame["source_name"].dropna().astype(str)))
                connection.execute(
                    """
                    update research_fact_partitions set
                        row_count = ?, content_hash = ?, file_sha256 = ?,
                        min_available_at = ?, max_available_at = ?, source_names = ?,
                        committed_at = now(), ingestion_run_id = ?, quality_status = 'passed'
                    where dataset_id = ? and partition_value = ?
                    """,
                    [
                        len(frame),
                        row["content_hash"],
                        row["file_sha256"],
                        available.min().to_pydatetime(),
                        available.max().to_pydatetime(),
                        json.dumps(sources, ensure_ascii=False),
                        migration_id,
                        dataset.value,
                        partition,
                    ],
                )
                connection.execute(
                    "delete from research_fact_keys where dataset_id = ? and partition_value = ?",
                    [dataset.value, partition],
                )
                connection.executemany(
                    "insert into research_fact_keys values (?, ?, ?)",
                    [
                        (dataset.value, str(key_hash), partition)
                        for key_hash in frame["business_key_hash"].astype(str)
                    ],
                )
            if folded_hashes:
                connection.executemany(
                    "delete from research_fact_revisions "
                    "where dataset_id = 'announcement' and business_key_hash = ?",
                    [(key_hash,) for key_hash in sorted(folded_hashes)],
                )
            _assert_revision_integrity(connection)
            connection.execute(
                "insert into research_migrations values (?, ?, ?, ?, ?, now())",
                [
                    migration_id,
                    str(warehouse.root.resolve()),
                    source_manifest_hash,
                    "completed",
                    json.dumps(provisional_report, ensure_ascii=False, sort_keys=True),
                ],
            )
        except Exception:
            connection.rollback()
            raise
        connection.commit()
    return after


def _replace_migration_report(
    duckdb_path: Path,
    migration_id: str,
    report: dict[str, Any],
) -> None:
    with connect_research_warehouse(duckdb_path) as connection:
        connection.execute(
            "update research_migrations set report_json = ? where migration_id = ?",
            [json.dumps(report, ensure_ascii=False, sort_keys=True), migration_id],
        )


def _assert_revision_integrity(connection: Any) -> None:
    inverted = connection.execute(
        "select count(*) from research_fact_revisions "
        "where dataset_id = 'announcement' and valid_to < valid_from"
    ).fetchone()[0]
    if inverted:
        raise ValueError(f"revision intervals remain inverted: {inverted}")
    overlapping = connection.execute(
        """
        with ordered as (
            select dataset_id, business_key_hash, revision_no, valid_from, valid_to,
                   lag(valid_to) over (
                       partition by dataset_id, business_key_hash order by revision_no
                   ) as prior_valid_to
            from research_fact_revisions
            where dataset_id = 'announcement'
        )
        select count(*) from ordered
        where prior_valid_to is not null and valid_from < prior_valid_to
        """
    ).fetchone()[0]
    if overlapping:
        raise ValueError(f"revision intervals remain overlapping: {overlapping}")


def _announcement_revision_rows(duckdb_path: Path) -> list[dict[str, Any]]:
    with connect_research_warehouse(duckdb_path, read_only=True) as connection:
        rows = connection.execute(
            """
            select business_key_hash, revision_no, partition_value,
                   cast(row_payload as varchar), cast(changed_fields as varchar)
            from research_fact_revisions
            where dataset_id = 'announcement'
            order by business_key_hash, revision_no
            """
        ).fetchall()
    return [
        {
            "business_key_hash": str(row[0]),
            "revision_no": int(row[1]),
            "partition_value": str(row[2]),
            "row_payload": json.loads(row[3]),
            "changed_fields": json.loads(row[4]),
        }
        for row in rows
    ]


def _partition_receipt(
    warehouse: ResearchWarehouse,
    affected: dict[tuple[ResearchDatasetId, str], pd.DataFrame],
) -> list[dict[str, Any]]:
    rows = []
    for (dataset, partition), frame in sorted(
        affected.items(), key=lambda item: (item[0][0].value, item[0][1])
    ):
        path = warehouse._partition_path(dataset, partition)
        rows.append(
            {
                "dataset_id": dataset.value,
                "partition_value": partition,
                "relative_path": str(path.relative_to(warehouse.root)),
                "row_count": len(frame),
                "content_hash": warehouse._frame_content_hash(frame),
                "file_sha256": sha256_file(path),
            }
        )
    return rows


def _current_partition_receipt(
    warehouse: ResearchWarehouse,
    prior_rows: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    affected = {}
    for row in prior_rows:
        dataset = ResearchDatasetId(row["dataset_id"])
        partition = str(row["partition_value"])
        affected[(dataset, partition)] = warehouse.read_current(
            dataset, partition_value=partition
        )
    return _partition_receipt(warehouse, affected)


def _backed_up_partition_receipt(
    warehouse: ResearchWarehouse,
    repair_root: Path,
    prior_rows: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    for prior in prior_rows:
        path = repair_root / "backups" / str(prior["relative_path"])
        if not path.is_file():
            raise FileNotFoundError(f"migration backup is missing: {path}")
        frame = pd.read_parquet(path)
        rows.append(
            {
                "dataset_id": str(prior["dataset_id"]),
                "partition_value": str(prior["partition_value"]),
                "relative_path": str(prior["relative_path"]),
                "row_count": len(frame),
                "content_hash": warehouse._frame_content_hash(frame),
                "file_sha256": sha256_file(path),
            }
        )
    return sorted(rows, key=lambda row: (row["dataset_id"], row["partition_value"]))


def _prior_migration(duckdb_path: Path, migration_id: str) -> dict[str, Any] | None:
    with connect_research_warehouse(duckdb_path, read_only=True) as connection:
        row = connection.execute(
            "select cast(report_json as varchar) from research_migrations where migration_id = ?",
            [migration_id],
        ).fetchone()
    return None if row is None else json.loads(row[0])


def _industry_intervals_overlap(cluster: list[dict[str, Any]], row: dict[str, Any]) -> bool:
    cluster_end = None
    for item in cluster:
        end = _optional_date(item.get("valid_to"))
        if end is None:
            return True
        cluster_end = end if cluster_end is None else max(cluster_end, end)
    return _as_date(row["valid_from"]) <= cluster_end


def _assert_no_industry_overlaps(frame: pd.DataFrame) -> None:
    for identity, group in frame.groupby(list(_INDUSTRY_IDENTITY), dropna=False):
        prior_end: date | None = None
        open_interval = False
        for row in group.sort_values("valid_from").to_dict(orient="records"):
            start = _as_date(row["valid_from"])
            if open_interval or (prior_end is not None and start <= prior_end):
                raise ValueError(f"industry overlap remains for {identity}")
            prior_end = _optional_date(row.get("valid_to"))
            open_interval = prior_end is None


def _refresh_fact_hashes(dataset: ResearchDatasetId, row: dict[str, Any]) -> None:
    contract = research_contract(dataset)
    row["business_key_hash"] = _stable_hash(
        {field: _json_safe(row[field]) for field in contract.business_key}
    )
    row["payload_hash"] = _stable_hash(
        {
            key: _json_safe(value)
            for key, value in row.items()
            if key not in _GOVERNANCE_FIELDS
        }
    )


def _substantive_signature(row: dict[str, Any], extra_excluded: set[str]) -> str:
    excluded = _GOVERNANCE_FIELDS | extra_excluded
    return _stable_hash(
        {
            key: _canonical_value(value)
            for key, value in row.items()
            if key not in excluded
        }
    )


def _canonical_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    return _json_safe(value)


def _as_date(value: Any) -> date:
    return pd.Timestamp(value).date()


def _optional_date(value: Any) -> date | None:
    if value is None or pd.isna(value):
        return None
    return _as_date(value)


def _as_timestamp(value: Any) -> pd.Timestamp:
    if value is None or pd.isna(value):
        raise ValueError("announcement_time is required for jitter repair")
    timestamp = pd.Timestamp(value)
    return timestamp.tz_localize("UTC") if timestamp.tzinfo is None else timestamp.tz_convert("UTC")


def _sql(value: str) -> str:
    return value.replace("'", "''")


def _write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = path.with_suffix(path.suffix + ".staged")
    staged.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(staged, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Repair the two 2026-08-04 known fact-store faults")
    parser.add_argument("--warehouse-root", type=Path)
    parser.add_argument("--archive-root", type=Path)
    parser.add_argument("--recover-relative-path")
    args = parser.parse_args(argv)
    config = AppConfig.load()
    warehouse_root = args.warehouse_root or config.local_warehouse_dir
    archive_root = args.archive_root or config.local_archive_dir
    report = (
        recover_interrupted_promotion(
            warehouse_root,
            archive_root,
            args.recover_relative_path,
        )
        if args.recover_relative_path
        else run_known_data_repair(warehouse_root, archive_root)
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
