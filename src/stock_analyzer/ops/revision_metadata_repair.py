from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any
from uuid import uuid4

from stock_analyzer.storage.research_parquet import sha256_file
from stock_analyzer.storage.research_schema import connect_research_warehouse
from stock_analyzer.storage.research_warehouse import ResearchWarehouse


MIGRATION_ID = "2026-08-05-legacy-revision-metadata-and-staging-v1"

_LEGACY_STAGING_DATASETS = {
    "income_statement",
    "balance_sheet",
    "cash_flow",
    "financial_indicator",
    "main_business",
    "earnings_forecast",
    "earnings_express",
}

_CANONICAL_CTE = """
positive as (
    select *
    from research_fact_revisions
    where valid_to > valid_from
),
ranked as (
    select *,
           max(valid_to) over (
               partition by dataset_id, business_key_hash,
                            payload_hash, valid_from
           ) as merged_valid_to,
           row_number() over (
               partition by dataset_id, business_key_hash,
                            payload_hash, valid_from
               order by valid_to desc, revision_no desc
           ) as merge_rank
    from positive
),
canonical as (
    select dataset_id, business_key_hash, revision_no, partition_value,
           payload_hash, row_payload, valid_from,
           merged_valid_to as valid_to, superseded_by_run_id, changed_fields
    from ranked
    where merge_rank = 1
)
"""


def inspect_revision_metadata_repair(warehouse_root: Path) -> dict[str, Any]:
    root = Path(warehouse_root)
    database = root / "research.duckdb"
    with connect_research_warehouse(database, read_only=True) as connection:
        rows_before = int(
            connection.execute(
                "select count(*) from research_fact_revisions"
            ).fetchone()[0]
        )
        nonpositive = int(
            connection.execute(
                """
                select count(*) from research_fact_revisions
                where valid_to <= valid_from
                """
            ).fetchone()[0]
        )
        same_payload_row_variants = int(
            connection.execute(
                """
                select count(*) from (
                    select dataset_id, business_key_hash, payload_hash,
                           valid_from
                    from research_fact_revisions
                    where valid_to > valid_from
                    group by 1, 2, 3, 4
                    having count(distinct cast(row_payload as varchar)) > 1
                )
                """
            ).fetchone()[0]
        )
        rows_after = int(
            connection.execute(
                f"with {_CANONICAL_CTE} select count(*) from canonical"
            ).fetchone()[0]
        )
        invalid_after, overlaps_after = connection.execute(
            f"""
            with {_CANONICAL_CTE},
            ordered as (
                select *, lag(valid_to) over (
                    partition by dataset_id, business_key_hash
                    order by valid_from, valid_to, revision_no
                ) as prior_valid_to
                from canonical
            )
            select count(*) filter (where valid_to <= valid_from),
                   count(*) filter (where prior_valid_to > valid_from)
            from ordered
            """
        ).fetchone()
        before_by_dataset = {
            str(dataset): int(count)
            for dataset, count in connection.execute(
                """
                select dataset_id, count(*)
                from research_fact_revisions
                group by dataset_id order by dataset_id
                """
            ).fetchall()
        }
        after_by_dataset = {
            str(dataset): int(count)
            for dataset, count in connection.execute(
                f"""
                with {_CANONICAL_CTE}
                select dataset_id, count(*)
                from canonical group by dataset_id order by dataset_id
                """
            ).fetchall()
        }

    legacy_dirs = _legacy_staging_dirs(root)
    legacy_files = [
        path for directory in legacy_dirs for path in directory.rglob("*")
        if path.is_file()
    ]
    return {
        "rows_before": rows_before,
        "rows_after": rows_after,
        "nonpositive_rows_removed": nonpositive,
        "redundant_rows_merged": rows_before - nonpositive - rows_after,
        "invalid_after": int(invalid_after),
        "overlaps_after": int(overlaps_after),
        "same_payload_governance_variants": same_payload_row_variants,
        "before_by_dataset": before_by_dataset,
        "after_by_dataset": after_by_dataset,
        "legacy_staging_directories": [path.name for path in legacy_dirs],
        "legacy_staging_files": len(legacy_files),
        "legacy_staging_bytes": sum(path.stat().st_size for path in legacy_files),
    }


def run_revision_metadata_repair(
    warehouse_root: Path,
    archive_root: Path,
    *,
    migration_id: str = MIGRATION_ID,
) -> dict[str, Any]:
    warehouse = ResearchWarehouse(Path(warehouse_root))
    repair_root = Path(archive_root) / "repairs" / migration_id
    prior = _prior_report(warehouse.duckdb_path, migration_id)
    if prior is not None:
        current = inspect_revision_metadata_repair(warehouse.root)
        if current["invalid_after"] or current["overlaps_after"]:
            raise ValueError("迁移已登记，但修订区间仍有异常")
        report = dict(prior)
        report["status"] = "already_applied"
        _write_receipts(repair_root, report)
        return report

    dry_run = inspect_revision_metadata_repair(warehouse.root)
    if dry_run["invalid_after"] or dry_run["overlaps_after"]:
        raise ValueError("保守整理后仍有修订区间冲突，拒绝猜测")
    if dry_run["rows_before"] == dry_run["rows_after"] and not dry_run[
        "legacy_staging_files"
    ]:
        raise ValueError("没有发现需要修复的旧修订或 staging")

    backup_root = repair_root / "backups"
    if backup_root.exists():
        raise FileExistsError("存在未登记的同名备份，拒绝覆盖")
    backup_root.mkdir(parents=True)
    database_backup = backup_root / "research.duckdb"
    moved: list[tuple[Path, Path]] = []

    with warehouse._file_lock(exclusive=True):
        shutil.copy2(warehouse.duckdb_path, database_backup)
        legacy_backup = backup_root / "legacy-fundamental-staging"
        for source in _legacy_staging_dirs(warehouse.root):
            target = legacy_backup / source.name
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(source, target)
            moved.append((source, target))

        source_hash = hashlib.sha256(
            json.dumps(dry_run, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        report = {
            "migration_id": migration_id,
            "status": "completed",
            "warehouse_root": str(warehouse.root.resolve()),
            "backup_root": str(backup_root.resolve()),
            "source_manifest_hash": source_hash,
            "revision_metadata": dry_run,
            "facts_parquet_modified": False,
        }
        try:
            with connect_research_warehouse(warehouse.duckdb_path) as connection:
                connection.execute(
                    f"""
                    create temporary table repaired_revisions as
                    with {_CANONICAL_CTE}
                    select * from canonical
                    """
                )
                connection.begin()
                try:
                    connection.execute("delete from research_fact_revisions")
                    connection.execute(
                        """
                        insert into research_fact_revisions
                        select * from repaired_revisions
                        """
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
        except Exception:
            for source, target in reversed(moved):
                source.parent.mkdir(parents=True, exist_ok=True)
                os.replace(target, source)
            raise

    backup_manifest = {
        "migration_id": migration_id,
        "database_backup": str(database_backup.relative_to(repair_root)),
        "database_bytes": database_backup.stat().st_size,
        "database_sha256": sha256_file(database_backup),
        "legacy_staging_files": dry_run["legacy_staging_files"],
        "legacy_staging_bytes": dry_run["legacy_staging_bytes"],
        "legacy_staging_directories": dry_run["legacy_staging_directories"],
    }
    _write_json_atomic(repair_root / "backup-manifest.json", backup_manifest)
    _write_receipts(repair_root, report)
    return report


def _legacy_staging_dirs(warehouse_root: Path) -> list[Path]:
    root = Path(warehouse_root) / ".backfill_staging" / "fundamentals"
    if not root.is_dir():
        return []
    return sorted(
        path
        for path in root.iterdir()
        if path.is_dir() and path.name in _LEGACY_STAGING_DATASETS
    )


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
    audit = report["revision_metadata"]
    text = (
        f"数据修订元数据收口迁移：{report['migration_id']}\n"
        f"状态：{report['status']}\n"
        f"修订记录：{audit['rows_before']} 条整理为 {audit['rows_after']} 条。\n"
        f"删除不可见的非正区间：{audit['nonpositive_rows_removed']} 条。\n"
        f"合并相同内容的重复区间：{audit['redundant_rows_merged']} 条。\n"
        f"迁移后倒置或零长度区间：{audit['invalid_after']} 条。\n"
        f"迁移后重叠区间：{audit['overlaps_after']} 条。\n"
        f"归档旧 staging 文件：{audit['legacy_staging_files']} 个。\n"
        "事实 Parquet 未修改。\n"
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
    parser = argparse.ArgumentParser(description="整理旧修订元数据和旧 staging")
    parser.add_argument("--warehouse", required=True, type=Path)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.apply:
        if args.archive is None:
            parser.error("--apply requires --archive")
        report = run_revision_metadata_repair(args.warehouse, args.archive)
    else:
        report = inspect_revision_metadata_repair(args.warehouse)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
