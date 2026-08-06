from __future__ import annotations

import argparse
import json
import os
import shutil
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from stock_analyzer.config import AppConfig
from stock_analyzer.data.research_contracts import (
    AvailabilityPrecision,
    ResearchDatasetId,
)
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
    _row_json,
    _stable_hash,
)


MIGRATION_ID = "2026-08-04-industry-member-effective-interval-repair-v1"
_PARTITION = "SW2021"
_SLOT_FIELDS = ("ts_code", "industry_system", "level")
_CANDIDATE_MANIFEST_FIELDS = (
    "ts_code",
    "industry_system",
    "level",
    "old_industry_code",
    "new_industry_code",
    "old_valid_from",
    "new_valid_from",
    "old_business_key_hash",
    "new_business_key_hash",
    "new_received_at",
    "source_endpoint",
)


@dataclass(frozen=True)
class RepairEvidenceProfile:
    source_file_sha256: str
    candidate_manifest_hash: str
    repaired_slots: int
    stock_count: int
    level_counts: tuple[tuple[str, int], ...]
    same_industry_slots: int
    changed_industry_slots: int
    expected_new_valid_from: date
    expected_new_received_at: datetime


KNOWN_EVIDENCE_PROFILE = RepairEvidenceProfile(
    source_file_sha256=(
        "1b92d189b32e74494dc91487964ed6eb39bd7b1282ddfd157e74b35e8c75cfaf"
    ),
    candidate_manifest_hash=(
        "fcf27f90939d7238dd26e38e48a1133004ddc7b17956a2bcfc9f788c2075b124"
    ),
    repaired_slots=210,
    stock_count=70,
    level_counts=(("L1", 70), ("L2", 70), ("L3", 70)),
    same_industry_slots=13,
    changed_industry_slots=197,
    expected_new_valid_from=date(2026, 7, 1),
    expected_new_received_at=datetime(
        2026, 8, 3, 13, 30, 19, 493930, tzinfo=timezone.utc
    ),
)


def run_industry_member_repair(
    warehouse_root: Path,
    archive_root: Path,
    *,
    migration_id: str = MIGRATION_ID,
    evidence_profile: RepairEvidenceProfile = KNOWN_EVIDENCE_PROFILE,
) -> dict[str, Any]:
    warehouse = ResearchWarehouse(Path(warehouse_root))
    repair_root = Path(archive_root) / "repairs" / migration_id
    staged_backup_root = _staged_backup_root(repair_root)
    if staged_backup_root.exists():
        shutil.rmtree(staged_backup_root)
    prior = _prior_migration(warehouse.duckdb_path, migration_id)
    _recover_interrupted_promotion(warehouse, prior)
    if prior is not None:
        shutil.rmtree(
            warehouse.staging_root / migration_id,
            ignore_errors=True,
        )
        _validate_applied_state(warehouse, repair_root, prior)
        receipt_path = repair_root / "receipt.json"
        if receipt_path.is_file():
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            if receipt != prior:
                raise ValueError("industry member migration receipt changed")
        else:
            _write_json_atomic(receipt_path, prior)
        result = dict(prior)
        result["status"] = "already_applied"
        return result

    frame = warehouse.read_current(
        ResearchDatasetId.INDUSTRY_MEMBER,
        partition_value=_PARTITION,
    )
    if frame.empty:
        raise ValueError("industry_member SW2021 partition is empty")
    repaired, revisions, audit = _repair_member_frame(frame, migration_id)
    before = _partition_receipt(warehouse, frame)
    _validate_evidence_profile(before, audit, evidence_profile)
    source_manifest_hash = _stable_hash(
        {
            "partition": before,
            "repaired_business_keys": sorted(
                item["new_business_key_hash"] for item in audit["entities"]
            ),
        }
    )
    backup_manifest = _backup_affected_state(
        warehouse,
        repair_root,
        migration_id,
    )

    staged_path = (
        warehouse.staging_root
        / migration_id
        / ResearchDatasetId.INDUSTRY_MEMBER.value
        / f"{_PARTITION}.parquet"
    )
    staged_sha = write_staged_parquet(staged_path, repaired)
    final_path = warehouse._partition_path(
        ResearchDatasetId.INDUSTRY_MEMBER,
        _PARTITION,
    )
    after = {
        "dataset_id": ResearchDatasetId.INDUSTRY_MEMBER.value,
        "partition_value": _PARTITION,
        "relative_path": str(final_path.relative_to(warehouse.root)),
        "row_count": len(repaired),
        "content_hash": warehouse._frame_content_hash(repaired),
        "file_sha256": staged_sha,
    }
    report = {
        "migration_id": migration_id,
        "status": "completed",
        "warehouse_root": str(warehouse.root.resolve()),
        "backup_root": str((repair_root / "backups").resolve()),
        "source_manifest_hash": source_manifest_hash,
        "backup_files": backup_manifest,
        "partitions_before": [before],
        "partitions_after": [after],
        "industry_member": audit,
    }

    previous_path: Path | None = None
    try:
        previous_path = atomic_promote(staged_path, final_path)
        try:
            _commit_repaired_metadata(
                warehouse,
                repaired,
                revisions,
                migration_id,
                source_manifest_hash,
                report,
            )
        except Exception:
            restore_previous(final_path, previous_path)
            raise
        discard_backup(previous_path)
    finally:
        shutil.rmtree(warehouse.staging_root / migration_id, ignore_errors=True)

    _write_json_atomic(repair_root / "receipt.json", report)
    return report


def _repair_member_frame(
    frame: pd.DataFrame,
    migration_id: str,
) -> tuple[pd.DataFrame, list[dict[str, Any]], dict[str, Any]]:
    if frame["business_key_hash"].astype(str).duplicated().any():
        raise ValueError("industry_member business keys are not unique")
    repaired = frame.copy()
    repaired["valid_to"] = [
        _optional_date(value) for value in repaired["valid_to"].tolist()
    ]
    candidates = _overlapping_member_transitions(repaired)
    if not candidates:
        raise ValueError("no evidence-supported industry member overlap found")

    revisions: list[dict[str, Any]] = []
    entities: list[dict[str, Any]] = []
    for old_index, new_index in candidates:
        old = repaired.loc[old_index].to_dict()
        new = repaired.loc[new_index].to_dict()
        _validate_transition(old, new)

        old_start = _as_date(old["valid_from"])
        new_start = _as_date(new["valid_from"])
        receipt = _as_utc(new["ingested_at"])
        old_available = _as_utc(old["available_at"])
        old_revision = int(old.get("revision_no", 1))
        if receipt < old_available:
            raise ValueError("industry member availability would move backwards")

        revisions.append(
            {
                "dataset_id": ResearchDatasetId.INDUSTRY_MEMBER.value,
                "business_key_hash": str(old["business_key_hash"]),
                "revision_no": old_revision,
                "partition_value": _PARTITION,
                "payload_hash": str(old["payload_hash"]),
                "row_payload": _row_json(old),
                "valid_from": old_available,
                "valid_to": receipt,
                "superseded_by_run_id": migration_id,
                "changed_fields": ["is_current", "valid_to"],
            }
        )

        repaired.at[old_index, "valid_to"] = new_start - timedelta(days=1)
        repaired.at[old_index, "is_current"] = False
        repaired.at[old_index, "available_at"] = receipt
        repaired.at[old_index, "availability_precision"] = (
            AvailabilityPrecision.INGESTION_CUTOFF.value
        )
        repaired.at[old_index, "ingested_at"] = receipt
        repaired.at[old_index, "ingestion_run_id"] = migration_id
        repaired.at[old_index, "revision_no"] = old_revision + 1
        updated_old = repaired.loc[old_index].to_dict()
        repaired.at[old_index, "payload_hash"] = _business_payload_hash(updated_old)

        repaired.at[new_index, "available_at"] = receipt
        repaired.at[new_index, "availability_precision"] = (
            AvailabilityPrecision.INGESTION_CUTOFF.value
        )

        entities.append(
            {
                "ts_code": str(new["ts_code"]),
                "industry_system": str(new["industry_system"]),
                "level": str(new["level"]),
                "old_industry_code": str(old["industry_code"]),
                "new_industry_code": str(new["industry_code"]),
                "old_valid_from": old_start.isoformat(),
                "old_valid_to_before": None,
                "old_valid_to_after": (new_start - timedelta(days=1)).isoformat(),
                "new_valid_from": new_start.isoformat(),
                "source_endpoint": str(new["source_endpoint"]),
                "source_business_date_basis": "index_member_all.in_date",
                "new_received_at": receipt.isoformat(),
                "new_available_at_before": _as_utc(new["available_at"]).isoformat(),
                "new_available_at_after": receipt.isoformat(),
                "old_business_key_hash": str(old["business_key_hash"]),
                "new_business_key_hash": str(new["business_key_hash"]),
                "repair_basis": (
                    "unique later source valid_from closes the single open "
                    "predecessor; local receipt controls historical visibility"
                ),
            }
        )

    repaired = repaired.sort_values(
        ["ts_code", "industry_system", "level", "valid_from"]
    ).reset_index(drop=True)
    _assert_no_member_overlaps(repaired)
    _assert_no_inverted_intervals(repaired)
    if repaired["business_key_hash"].astype(str).duplicated().any():
        raise ValueError("industry_member repair changed business key uniqueness")
    entities.sort(
        key=lambda item: (
            item["ts_code"],
            item["industry_system"],
            item["level"],
        )
    )
    return repaired, revisions, {
        "rows_before": len(frame),
        "rows_after": len(repaired),
        "repaired_slots": len(entities),
        "same_industry_slots": sum(
            item["old_industry_code"] == item["new_industry_code"]
            for item in entities
        ),
        "changed_industry_slots": sum(
            item["old_industry_code"] != item["new_industry_code"]
            for item in entities
        ),
        "entities": entities,
    }


def _candidate_manifest_hash(audit: dict[str, Any]) -> str:
    core = [
        {field: entity[field] for field in _CANDIDATE_MANIFEST_FIELDS}
        for entity in audit["entities"]
    ]
    return _stable_hash(core)


def _validate_evidence_profile(
    before: dict[str, Any],
    audit: dict[str, Any],
    profile: RepairEvidenceProfile,
) -> None:
    entities = audit["entities"]
    actual = {
        "source_file_sha256": before["file_sha256"],
        "candidate_manifest_hash": _candidate_manifest_hash(audit),
        "repaired_slots": audit["repaired_slots"],
        "stock_count": len({item["ts_code"] for item in entities}),
        "level_counts": tuple(
            sorted(
                (level, sum(item["level"] == level for item in entities))
                for level in {item["level"] for item in entities}
            )
        ),
        "same_industry_slots": audit["same_industry_slots"],
        "changed_industry_slots": audit["changed_industry_slots"],
        "new_valid_from_values": {
            item["new_valid_from"] for item in entities
        },
        "new_received_at_values": {
            item["new_received_at"] for item in entities
        },
    }
    expected = {
        "source_file_sha256": profile.source_file_sha256,
        "candidate_manifest_hash": profile.candidate_manifest_hash,
        "repaired_slots": profile.repaired_slots,
        "stock_count": profile.stock_count,
        "level_counts": tuple(sorted(profile.level_counts)),
        "same_industry_slots": profile.same_industry_slots,
        "changed_industry_slots": profile.changed_industry_slots,
        "new_valid_from_values": {profile.expected_new_valid_from.isoformat()},
        "new_received_at_values": {
            _as_utc(profile.expected_new_received_at).isoformat()
        },
    }
    mismatches = [
        field for field in expected if actual[field] != expected[field]
    ]
    if mismatches:
        raise ValueError(
            "industry member repair evidence profile mismatch: "
            + ", ".join(mismatches)
        )


def _staged_backup_root(repair_root: Path) -> Path:
    return repair_root.with_name(repair_root.name + ".backup-staged")


def _recover_interrupted_promotion(
    warehouse: ResearchWarehouse,
    prior: dict[str, Any] | None,
) -> None:
    final_path = warehouse._partition_path(
        ResearchDatasetId.INDUSTRY_MEMBER,
        _PARTITION,
    )
    previous_path = final_path.with_suffix(".parquet.previous")
    if not previous_path.exists():
        return

    with connect_research_warehouse(
        warehouse.duckdb_path, read_only=True
    ) as connection:
        row = connection.execute(
            "select file_sha256 from research_fact_partitions "
            "where dataset_id = 'industry_member' and partition_value = 'SW2021'"
        ).fetchone()
    if row is None:
        raise ValueError(
            "cannot recover industry member promotion without partition metadata"
        )
    metadata_sha = str(row[0])
    previous_sha = sha256_file(previous_path)
    final_sha = sha256_file(final_path) if final_path.is_file() else None

    if prior is None:
        if previous_sha == metadata_sha:
            restore_previous(final_path, previous_path)
            return
        if final_sha == metadata_sha:
            discard_backup(previous_path)
            return
        raise ValueError("ambiguous interrupted industry member promotion")

    expected_before = str(prior["partitions_before"][0]["file_sha256"])
    expected_after = str(prior["partitions_after"][0]["file_sha256"])
    if (
        final_sha == expected_after
        and metadata_sha == expected_after
        and previous_sha == expected_before
    ):
        discard_backup(previous_path)
        return
    raise ValueError("applied industry member promotion state is inconsistent")


def _overlapping_member_transitions(
    frame: pd.DataFrame,
) -> list[tuple[int, int]]:
    candidates: list[tuple[int, int]] = []
    for slot, group in frame.groupby(list(_SLOT_FIELDS), dropna=False):
        ordered = group.assign(
            __start=pd.to_datetime(group["valid_from"], errors="raise")
        ).sort_values("__start")
        active: list[int] = []
        overlaps: list[tuple[int, int]] = []
        for index in ordered.index:
            start = _as_date(frame.at[index, "valid_from"])
            active = [
                prior
                for prior in active
                if _optional_date(frame.at[prior, "valid_to"]) is None
                or start <= _optional_date(frame.at[prior, "valid_to"])
            ]
            overlaps.extend((prior, index) for prior in active)
            active.append(index)
        if overlaps:
            if len(overlaps) != 1:
                raise ValueError(
                    f"ambiguous industry member overlap for {tuple(map(str, slot))}"
                )
            candidates.append(overlaps[0])
    return candidates


def _validate_transition(old: dict[str, Any], new: dict[str, Any]) -> None:
    slot = tuple(str(new[field]) for field in _SLOT_FIELDS)
    if tuple(str(old[field]) for field in _SLOT_FIELDS) != slot:
        raise ValueError("industry member transition crossed identity slots")
    old_start = _as_date(old["valid_from"])
    new_start = _as_date(new["valid_from"])
    if new_start <= old_start:
        raise ValueError(f"ambiguous industry member overlap for {slot}")
    if _optional_date(old.get("valid_to")) is not None:
        raise ValueError(f"ambiguous industry member overlap for {slot}")
    if _optional_date(new.get("valid_to")) is not None:
        raise ValueError(f"ambiguous industry member overlap for {slot}")
    if not bool(old.get("is_current")) or not bool(new.get("is_current")):
        raise ValueError(f"ambiguous industry member current flags for {slot}")
    if str(old.get("source_endpoint")) != "index_member_all":
        raise ValueError(f"unsupported old industry member provenance for {slot}")
    if str(new.get("source_endpoint")) != "index_member_all":
        raise ValueError(f"unsupported new industry member provenance for {slot}")
    old_received = _as_utc(old["ingested_at"])
    new_received = _as_utc(new["ingested_at"])
    if new_received <= old_received:
        raise ValueError(f"ambiguous industry member receipt order for {slot}")
    if _as_utc(new["available_at"]) >= new_received:
        raise ValueError(f"industry member overlap is not a backdated refresh for {slot}")


def _backup_affected_state(
    warehouse: ResearchWarehouse,
    repair_root: Path,
    migration_id: str,
) -> list[dict[str, Any]]:
    manifest_path = repair_root / "backup-manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        _validate_backup_manifest(repair_root, manifest)
        return manifest

    if repair_root.exists():
        raise FileExistsError(
            f"industry member repair root exists without manifest: {repair_root}"
        )
    staged_root = _staged_backup_root(repair_root)
    if staged_root.exists():
        shutil.rmtree(staged_root)
    backup_root = staged_root / "backups"
    source = warehouse._partition_path(
        ResearchDatasetId.INDUSTRY_MEMBER,
        _PARTITION,
    )
    target = backup_root / source.relative_to(warehouse.root)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    files = [target]

    metadata_root = backup_root / "duckdb_metadata"
    metadata_root.mkdir(parents=True, exist_ok=True)
    queries = {
        "research_fact_partitions.parquet": (
            "select * from research_fact_partitions "
            "where dataset_id = 'industry_member' and partition_value = 'SW2021'"
        ),
        "research_fact_keys.parquet": (
            "select * from research_fact_keys where dataset_id = 'industry_member'"
        ),
        "research_fact_revisions.parquet": (
            "select * from research_fact_revisions "
            "where dataset_id = 'industry_member'"
        ),
        "research_ingestion_runs.parquet": (
            "select * from research_ingestion_runs "
            "where run_id like 'classification:%' or stage like '%classification%'"
        ),
        "research_run_datasets.parquet": (
            "select * from research_run_datasets "
            "where dataset_id = 'industry_member' or run_id like 'classification:%'"
        ),
        "research_watermarks.parquet": (
            "select * from research_watermarks "
            "where dataset_id like 'classification%' or run_id like 'classification:%'"
        ),
        "research_migrations.parquet": (
            "select * from research_migrations "
            f"where migration_id = '{_sql(migration_id)}'"
        ),
    }
    with connect_research_warehouse(
        warehouse.duckdb_path,
        read_only=True,
    ) as connection:
        for name, query in queries.items():
            path = metadata_root / name
            connection.execute(
                f"copy ({query}) to '{_sql(str(path))}' (format parquet)"
            )
            files.append(path)

    manifest = [
        {
            "relative_path": str(path.relative_to(staged_root)),
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in sorted(files)
    ]
    _write_json_atomic(staged_root / "backup-manifest.json", manifest)
    repair_root.parent.mkdir(parents=True, exist_ok=True)
    os.replace(staged_root, repair_root)
    return manifest


def _commit_repaired_metadata(
    warehouse: ResearchWarehouse,
    repaired: pd.DataFrame,
    revisions: list[dict[str, Any]],
    migration_id: str,
    source_manifest_hash: str,
    report: dict[str, Any],
) -> None:
    final_path = warehouse._partition_path(
        ResearchDatasetId.INDUSTRY_MEMBER,
        _PARTITION,
    )
    available = pd.to_datetime(repaired["available_at"], utc=True, errors="raise")
    sources = sorted(set(repaired["source_name"].dropna().astype(str)))
    with connect_research_warehouse(warehouse.duckdb_path) as connection:
        connection.begin()
        try:
            for revision in revisions:
                connection.execute(
                    """
                    insert into research_fact_revisions values
                    (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        revision["dataset_id"],
                        revision["business_key_hash"],
                        revision["revision_no"],
                        revision["partition_value"],
                        revision["payload_hash"],
                        json.dumps(
                            revision["row_payload"],
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        revision["valid_from"],
                        revision["valid_to"],
                        revision["superseded_by_run_id"],
                        json.dumps(revision["changed_fields"], ensure_ascii=False),
                    ],
                )
            connection.execute(
                """
                update research_fact_partitions set
                    row_count = ?, content_hash = ?, file_sha256 = ?,
                    min_available_at = ?, max_available_at = ?, source_names = ?,
                    committed_at = now(), ingestion_run_id = ?, quality_status = 'passed'
                where dataset_id = 'industry_member' and partition_value = 'SW2021'
                """,
                [
                    len(repaired),
                    warehouse._frame_content_hash(repaired),
                    sha256_file(final_path),
                    available.min().to_pydatetime(),
                    available.max().to_pydatetime(),
                    json.dumps(sources, ensure_ascii=False),
                    migration_id,
                ],
            )
            connection.execute(
                "delete from research_fact_keys where dataset_id = 'industry_member'"
            )
            connection.executemany(
                "insert into research_fact_keys values ('industry_member', ?, 'SW2021')",
                [(str(value),) for value in repaired["business_key_hash"]],
            )
            _assert_revision_integrity(connection)
            connection.execute(
                "insert into research_migrations values (?, ?, ?, ?, ?, now())",
                [
                    migration_id,
                    str(warehouse.root.resolve()),
                    source_manifest_hash,
                    "completed",
                    json.dumps(report, ensure_ascii=False, sort_keys=True),
                ],
            )
        except Exception:
            connection.rollback()
            raise
        connection.commit()


def _assert_revision_integrity(connection: Any) -> None:
    inverted = connection.execute(
        "select count(*) from research_fact_revisions "
        "where dataset_id = 'industry_member' and valid_to < valid_from"
    ).fetchone()[0]
    if inverted:
        raise ValueError(f"industry member revision intervals inverted: {inverted}")
    overlapping = connection.execute(
        """
        with ordered as (
            select business_key_hash, revision_no, valid_from, valid_to,
                   lag(valid_to) over (
                       partition by business_key_hash order by revision_no
                   ) as prior_valid_to
            from research_fact_revisions
            where dataset_id = 'industry_member'
        )
        select count(*) from ordered
        where prior_valid_to is not null and valid_from < prior_valid_to
        """
    ).fetchone()[0]
    if overlapping:
        raise ValueError(
            f"industry member revision intervals overlapping: {overlapping}"
        )


def _partition_receipt(
    warehouse: ResearchWarehouse,
    frame: pd.DataFrame,
) -> dict[str, Any]:
    path = warehouse._partition_path(
        ResearchDatasetId.INDUSTRY_MEMBER,
        _PARTITION,
    )
    return {
        "dataset_id": ResearchDatasetId.INDUSTRY_MEMBER.value,
        "partition_value": _PARTITION,
        "relative_path": str(path.relative_to(warehouse.root)),
        "row_count": len(frame),
        "content_hash": warehouse._frame_content_hash(frame),
        "file_sha256": sha256_file(path),
    }


def _validate_applied_state(
    warehouse: ResearchWarehouse,
    repair_root: Path,
    report: dict[str, Any],
) -> None:
    expected = report["partitions_after"][0]
    current = _partition_receipt(
        warehouse,
        warehouse.read_current(
            ResearchDatasetId.INDUSTRY_MEMBER,
            partition_value=_PARTITION,
        ),
    )
    for field in ("row_count", "content_hash", "file_sha256"):
        if current[field] != expected[field]:
            raise ValueError(
                f"applied industry member migration state changed: {field}"
            )
    manifest_path = repair_root / "backup-manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError("industry member migration backup manifest is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    _validate_backup_manifest(repair_root, manifest)


def _validate_backup_manifest(
    repair_root: Path,
    manifest: Iterable[dict[str, Any]],
) -> None:
    for item in manifest:
        path = repair_root / str(item["relative_path"])
        if not path.is_file():
            raise FileNotFoundError(f"industry member backup is missing: {path}")
        if path.stat().st_size != int(item["size"]):
            raise ValueError(f"industry member backup size changed: {path}")
        if sha256_file(path) != str(item["sha256"]):
            raise ValueError(f"industry member backup hash changed: {path}")


def _prior_migration(
    duckdb_path: Path,
    migration_id: str,
) -> dict[str, Any] | None:
    with connect_research_warehouse(duckdb_path, read_only=True) as connection:
        row = connection.execute(
            "select cast(report_json as varchar) from research_migrations "
            "where migration_id = ?",
            [migration_id],
        ).fetchone()
    return None if row is None else json.loads(row[0])


def _assert_no_member_overlaps(frame: pd.DataFrame) -> None:
    for slot, group in frame.groupby(list(_SLOT_FIELDS), dropna=False):
        active_end: date | None = None
        open_interval = False
        for row in group.sort_values("valid_from").to_dict(orient="records"):
            start = _as_date(row["valid_from"])
            if open_interval or (active_end is not None and start <= active_end):
                raise ValueError(f"industry member overlap remains for {slot}")
            active_end = _optional_date(row.get("valid_to"))
            open_interval = active_end is None


def _assert_no_inverted_intervals(frame: pd.DataFrame) -> None:
    for row in frame.to_dict(orient="records"):
        end = _optional_date(row.get("valid_to"))
        if end is not None and end < _as_date(row["valid_from"]):
            raise ValueError(
                "industry member interval inverted for "
                f"{row.get('ts_code')}/{row.get('level')}"
            )


def _business_payload_hash(row: dict[str, Any]) -> str:
    return _stable_hash(
        {
            key: _json_safe(value)
            for key, value in row.items()
            if key not in _GOVERNANCE_FIELDS
        }
    )


def _as_date(value: Any) -> date:
    return pd.Timestamp(value).date()


def _optional_date(value: Any) -> date | None:
    if value is None or pd.isna(value):
        return None
    return _as_date(value)


def _as_utc(value: Any) -> datetime:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp.to_pydatetime()


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
    parser = argparse.ArgumentParser(
        description="Repair evidence-supported industry_member interval overlaps"
    )
    parser.add_argument("--warehouse-root", type=Path)
    parser.add_argument("--archive-root", type=Path)
    args = parser.parse_args(argv)
    config = AppConfig.load()
    report = run_industry_member_repair(
        args.warehouse_root or config.local_warehouse_dir,
        args.archive_root or config.local_archive_dir,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "KNOWN_EVIDENCE_PROFILE",
    "MIGRATION_ID",
    "RepairEvidenceProfile",
    "run_industry_member_repair",
]
