from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd

from stock_analyzer.data.fundamental_backfill import (
    _main_business_classification,
)
from stock_analyzer.data.research_contracts import (
    ResearchDatasetId,
    research_contract,
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
    _stable_hash,
)


MIGRATION_ID = "2026-08-05-main-business-provider-type-repair-v1"
_DATASET = ResearchDatasetId.MAIN_BUSINESS


def inspect_main_business_classification_repair(
    warehouse_root: Path,
) -> dict[str, Any]:
    warehouse = ResearchWarehouse(Path(warehouse_root))
    _, _, audit = _prepare_repair(warehouse)
    return audit


def run_main_business_classification_repair(
    warehouse_root: Path,
    archive_root: Path,
    *,
    migration_id: str = MIGRATION_ID,
) -> dict[str, Any]:
    warehouse = ResearchWarehouse(Path(warehouse_root))
    repair_root = Path(archive_root) / "repairs" / migration_id
    prior = _prior_report(warehouse.duckdb_path, migration_id)
    if prior is not None:
        current = inspect_main_business_classification_repair(warehouse.root)
        if current["fact_rows_changed"] or current["revision_rows_changed"]:
            raise ValueError("迁移已登记，但主营构成类型仍未修正")
        report = dict(prior)
        report["status"] = "already_applied"
        _write_receipts(repair_root, report)
        return report

    frames, revisions, audit = _prepare_repair(warehouse)
    if audit["duplicate_business_keys_after"]:
        raise ValueError("按 bz_code 修正后仍有重复主营构成业务键")
    if audit["duplicate_revision_keys_after"]:
        raise ValueError("按 bz_code 修正后仍有重复主营构成修订键")
    if audit["invalid_revision_intervals_after"] or audit[
        "overlapping_revision_intervals_after"
    ]:
        raise ValueError("按 bz_code 修正后修订链仍有异常")
    if not audit["fact_rows_changed"] and not audit["revision_rows_changed"]:
        raise ValueError("没有发现需要修复的主营构成类型")

    backup_root = repair_root / "backups"
    if backup_root.exists():
        raise FileExistsError("存在未登记的同名备份，拒绝覆盖")
    backup_root.mkdir(parents=True)
    database_backup = backup_root / "research.duckdb"
    source_fact_root = warehouse.facts_root / _DATASET.value
    fact_backup_root = backup_root / "facts" / _DATASET.value
    stage_root = warehouse.staging_root / migration_id
    source_hash = hashlib.sha256(
        json.dumps(audit, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    report = {
        "migration_id": migration_id,
        "status": "completed",
        "warehouse_root": str(warehouse.root.resolve()),
        "backup_root": str(backup_root.resolve()),
        "source_manifest_hash": source_hash,
        "main_business": audit,
    }

    promoted: list[tuple[Path, Path | None]] = []
    with warehouse._file_lock(exclusive=True):
        shutil.copy2(warehouse.duckdb_path, database_backup)
        shutil.copytree(source_fact_root, fact_backup_root)
        staged: dict[str, tuple[Path, str]] = {}
        manifest = warehouse.partition_manifest(_DATASET)
        for partition, frame in frames.items():
            relative = str(
                manifest.loc[
                    manifest["partition_value"].astype(str) == partition,
                    "relative_path",
                ].iloc[0]
            )
            staged_path = stage_root / relative
            staged[partition] = (
                staged_path,
                write_staged_parquet(staged_path, frame),
            )
        try:
            for partition, (staged_path, _) in staged.items():
                final_path = warehouse._partition_path(_DATASET, partition)
                promoted.append(
                    (final_path, atomic_promote(staged_path, final_path))
                )
            _commit_metadata(
                warehouse,
                frames,
                revisions,
                staged,
                migration_id,
                source_hash,
                report,
            )
        except Exception:
            for final_path, previous in reversed(promoted):
                restore_previous(final_path, previous)
            raise
        else:
            for _, previous in promoted:
                discard_backup(previous)
        finally:
            shutil.rmtree(stage_root, ignore_errors=True)

    backup_files = sorted(fact_backup_root.rglob("data.parquet"))
    backup_manifest = {
        "migration_id": migration_id,
        "database_backup": str(database_backup.relative_to(repair_root)),
        "database_bytes": database_backup.stat().st_size,
        "database_sha256": sha256_file(database_backup),
        "fact_files": [
            {
                "relative_path": str(path.relative_to(repair_root)),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in backup_files
        ],
    }
    _write_json_atomic(repair_root / "backup-manifest.json", backup_manifest)
    _write_receipts(repair_root, report)
    return report


def _prepare_repair(
    warehouse: ResearchWarehouse,
) -> tuple[dict[str, pd.DataFrame], list[dict[str, Any]], dict[str, Any]]:
    contract = research_contract(_DATASET)
    frames: dict[str, pd.DataFrame] = {}
    fact_rows_changed = 0
    all_keys: list[str] = []
    manifest = warehouse.partition_manifest(_DATASET)
    if manifest.empty:
        raise ValueError("main_business 数据集为空")
    for partition in manifest["partition_value"].astype(str):
        frame = warehouse.read_current(_DATASET, partition_value=partition)
        repaired_rows: list[dict[str, Any]] = []
        for row in frame.to_dict(orient="records"):
            repaired, changed = _repair_payload(row, contract.business_key)
            repaired_rows.append(repaired)
            fact_rows_changed += int(changed)
            all_keys.append(str(repaired["business_key_hash"]))
        repaired_frame = pd.DataFrame(repaired_rows, columns=frame.columns)
        frames[partition] = repaired_frame.sort_values(
            list(contract.business_key)
        ).reset_index(drop=True)

    revisions: list[dict[str, Any]] = []
    revision_rows_changed = 0
    for revision in _full_revision_rows(warehouse.duckdb_path):
        repaired_payload, changed = _repair_payload(
            revision["row_payload"],
            contract.business_key,
        )
        repaired_revision = dict(revision)
        repaired_revision["business_key_hash"] = repaired_payload[
            "business_key_hash"
        ]
        repaired_revision["payload_hash"] = repaired_payload["payload_hash"]
        repaired_revision["row_payload"] = repaired_payload
        revisions.append(repaired_revision)
        revision_rows_changed += int(changed)

    revision_keys = [
        (
            item["dataset_id"],
            item["business_key_hash"],
            int(item["revision_no"]),
        )
        for item in revisions
    ]
    invalid, overlaps = _revision_interval_counts(revisions)
    return frames, revisions, {
        "partitions": len(frames),
        "fact_rows": sum(len(frame) for frame in frames.values()),
        "fact_rows_changed": fact_rows_changed,
        "revision_rows": len(revisions),
        "revision_rows_changed": revision_rows_changed,
        "duplicate_business_keys_after": len(all_keys) - len(set(all_keys)),
        "duplicate_revision_keys_after": len(revision_keys)
        - len(set(revision_keys)),
        "invalid_revision_intervals_after": invalid,
        "overlapping_revision_intervals_after": overlaps,
        "classification_basis": "Tushare fina_mainbz.bz_code P/D/I",
    }


def _full_revision_rows(database: Path) -> list[dict[str, Any]]:
    with connect_research_warehouse(database, read_only=True) as connection:
        rows = connection.execute(
            """
            select dataset_id, business_key_hash, revision_no,
                   partition_value, payload_hash, cast(row_payload as varchar),
                   cast(valid_from as varchar), cast(valid_to as varchar),
                   superseded_by_run_id,
                   cast(changed_fields as varchar)
            from research_fact_revisions
            where dataset_id = ?
            order by business_key_hash, revision_no
            """,
            [_DATASET.value],
        ).fetchall()
    return [
        {
            "dataset_id": str(row[0]),
            "business_key_hash": str(row[1]),
            "revision_no": int(row[2]),
            "partition_value": str(row[3]),
            "payload_hash": str(row[4]),
            "row_payload": json.loads(row[5]),
            "valid_from": datetime.fromisoformat(row[6]),
            "valid_to": datetime.fromisoformat(row[7]),
            "superseded_by_run_id": str(row[8]),
            "changed_fields": json.loads(row[9]),
        }
        for row in rows
    ]


def _repair_payload(
    raw: dict[str, Any],
    business_key: tuple[str, ...],
) -> tuple[dict[str, Any], bool]:
    row = dict(raw)
    before = str(row.get("classification") or "")
    after = _main_business_classification(
        str(row.get("item_name") or row.get("bz_item") or ""),
        row.get("bz_code"),
    )
    row["classification"] = after
    old_key_hash = str(row.get("business_key_hash") or "")
    key_payload = {
        field: _json_safe(row[field])
        for field in business_key
    }
    new_key_hash = _stable_hash(key_payload)
    if str(row.get("source_record_id") or "") == old_key_hash:
        row["source_record_id"] = new_key_hash
    business_payload = {
        key: _json_safe(value)
        for key, value in row.items()
        if key not in _GOVERNANCE_FIELDS
    }
    row["business_key_hash"] = new_key_hash
    row["payload_hash"] = _stable_hash(business_payload)
    return row, before != after


def _revision_interval_counts(
    revisions: list[dict[str, Any]],
) -> tuple[int, int]:
    invalid = 0
    overlaps = 0
    grouped: dict[str, list[tuple[pd.Timestamp, pd.Timestamp]]] = {}
    for item in revisions:
        start = pd.Timestamp(item["valid_from"])
        end = pd.Timestamp(item["valid_to"])
        invalid += int(end <= start)
        grouped.setdefault(str(item["business_key_hash"]), []).append(
            (start, end)
        )
    for intervals in grouped.values():
        prior_end: pd.Timestamp | None = None
        for start, end in sorted(intervals):
            if prior_end is not None and prior_end > start:
                overlaps += 1
            prior_end = end if prior_end is None else max(prior_end, end)
    return invalid, overlaps


def _commit_metadata(
    warehouse: ResearchWarehouse,
    frames: dict[str, pd.DataFrame],
    revisions: list[dict[str, Any]],
    staged: dict[str, tuple[Path, str]],
    migration_id: str,
    source_hash: str,
    report: dict[str, Any],
) -> None:
    with connect_research_warehouse(warehouse.duckdb_path) as connection:
        connection.begin()
        try:
            connection.execute(
                "delete from research_fact_keys where dataset_id = ?",
                [_DATASET.value],
            )
            connection.execute(
                "delete from research_fact_revisions where dataset_id = ?",
                [_DATASET.value],
            )
            for partition, frame in frames.items():
                available = pd.to_datetime(frame["available_at"], utc=True)
                connection.execute(
                    """
                    update research_fact_partitions
                    set row_count = ?, content_hash = ?, file_sha256 = ?,
                        min_available_at = ?, max_available_at = ?,
                        committed_at = now(), ingestion_run_id = ?,
                        quality_status = 'passed'
                    where dataset_id = ? and partition_value = ?
                    """,
                    [
                        len(frame),
                        warehouse._frame_content_hash(frame),
                        staged[partition][1],
                        available.min().to_pydatetime(),
                        available.max().to_pydatetime(),
                        migration_id,
                        _DATASET.value,
                        partition,
                    ],
                )
                connection.executemany(
                    """
                    insert into research_fact_keys
                    (dataset_id, business_key_hash, partition_value)
                    values (?, ?, ?)
                    """,
                    [
                        (_DATASET.value, str(key), partition)
                        for key in frame["business_key_hash"]
                    ],
                )
            if revisions:
                connection.executemany(
                    """
                    insert into research_fact_revisions
                    (dataset_id, business_key_hash, revision_no,
                     partition_value, payload_hash, row_payload, valid_from,
                     valid_to, superseded_by_run_id, changed_fields)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            item["dataset_id"],
                            item["business_key_hash"],
                            int(item["revision_no"]),
                            item["partition_value"],
                            item["payload_hash"],
                            json.dumps(
                                item["row_payload"],
                                ensure_ascii=False,
                                sort_keys=True,
                                default=str,
                            ),
                            item["valid_from"],
                            item["valid_to"],
                            item["superseded_by_run_id"],
                            json.dumps(item["changed_fields"], ensure_ascii=False),
                        )
                        for item in revisions
                    ],
                )
            connection.execute(
                """
                insert into research_migrations
                values (?, ?, ?, 'completed', ?, now())
                """,
                [
                    migration_id,
                    str(warehouse.root.resolve()),
                    source_hash,
                    json.dumps(report, ensure_ascii=False, sort_keys=True),
                ],
            )
        except Exception:
            connection.rollback()
            raise
        connection.commit()


def _prior_report(database: Path, migration_id: str) -> dict[str, Any] | None:
    with connect_research_warehouse(database, read_only=True) as connection:
        row = connection.execute(
            """
            select cast(report_json as varchar)
            from research_migrations where migration_id = ?
            """,
            [migration_id],
        ).fetchone()
    return None if row is None else json.loads(row[0])


def _write_receipts(repair_root: Path, report: dict[str, Any]) -> None:
    _write_json_atomic(repair_root / "receipt.json", report)
    audit = report["main_business"]
    text = (
        f"主营构成类型修复：{report['migration_id']}\n"
        f"状态：{report['status']}\n"
        f"事实分区：{audit['partitions']} 个。\n"
        f"修正事实：{audit['fact_rows_changed']} 条。\n"
        f"修正历史修订：{audit['revision_rows_changed']} 条。\n"
        f"修复后重复业务键：{audit['duplicate_business_keys_after']} 条。\n"
        f"修复后异常修订区间："
        f"{audit['invalid_revision_intervals_after'] + audit['overlapping_revision_intervals_after']} 条。\n"
        "分类依据：Tushare fina_mainbz.bz_code（P 产品、D 地区、I 行业）。\n"
    )
    _write_text_atomic(repair_root / "receipt.txt", text)


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    _write_text_atomic(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    staged.write_text(text, encoding="utf-8")
    os.replace(staged, path)


def main() -> None:
    parser = argparse.ArgumentParser(description="修复主营构成的提供方类型")
    parser.add_argument("--warehouse", required=True, type=Path)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.apply:
        if args.archive is None:
            parser.error("--apply requires --archive")
        report = run_main_business_classification_repair(
            args.warehouse,
            args.archive,
        )
    else:
        report = inspect_main_business_classification_repair(args.warehouse)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
