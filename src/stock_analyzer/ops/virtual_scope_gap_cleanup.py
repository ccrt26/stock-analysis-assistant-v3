from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from stock_analyzer.storage.research_schema import connect_research_warehouse
from stock_analyzer.storage.research_warehouse import ResearchWarehouse


MIGRATION_ID = "2026-08-05-remove-virtual-scope-gaps-v1"


def inspect_virtual_scope_gaps(warehouse_root: Path) -> dict[str, Any]:
    warehouse = ResearchWarehouse(Path(warehouse_root))
    return _audit_rows(_virtual_rows(warehouse.duckdb_path))


def _audit_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[tuple[str, str, str], int] = {}
    for row in rows:
        key = (row["dataset_id"], row["status"], row["reason_category"])
        groups[key] = groups.get(key, 0) + 1
    return {
        "rows": len(rows),
        "groups": [
            {
                "dataset_id": key[0],
                "status": key[1],
                "reason_category": key[2],
                "rows": count,
            }
            for key, count in sorted(groups.items())
        ],
    }


def run_virtual_scope_gap_cleanup(
    warehouse_root: Path,
    archive_root: Path,
    *,
    migration_id: str = MIGRATION_ID,
) -> dict[str, Any]:
    warehouse = ResearchWarehouse(Path(warehouse_root))
    repair_root = Path(archive_root) / "repairs" / migration_id
    prior = _prior_report(warehouse.duckdb_path, migration_id)
    if prior is not None:
        if inspect_virtual_scope_gaps(warehouse.root)["rows"]:
            raise ValueError("迁移已登记，但仍存在 scope:* 虚拟缺口")
        report = dict(prior)
        report["status"] = "already_applied"
        _write_receipts(repair_root, report)
        return report

    with warehouse._file_lock(exclusive=True):
        rows = _virtual_rows(warehouse.duckdb_path)
        if not rows:
            raise ValueError("没有发现需要撤回的 scope:* 虚拟缺口")
        source_hash = hashlib.sha256(
            json.dumps(
                rows,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        backup_path = repair_root / "backups" / "rows.json"
        if backup_path.exists():
            raise FileExistsError("存在未登记的同名备份，拒绝覆盖")
        _write_json_atomic(backup_path, rows)
        audit = _audit_rows(rows)
        report = {
            "migration_id": migration_id,
            "status": "completed",
            "warehouse_root": str(warehouse.root.resolve()),
            "backup": str(backup_path.resolve()),
            "source_manifest_hash": source_hash,
            "deleted": audit,
        }
        with connect_research_warehouse(warehouse.duckdb_path) as connection:
            connection.begin()
            try:
                connection.execute(
                    "delete from research_data_gaps where dataset_id like 'scope:%'"
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
    _write_receipts(repair_root, report)
    return report


def _virtual_rows(database: Path) -> list[dict[str, Any]]:
    with connect_research_warehouse(database, read_only=True) as connection:
        rows = connection.execute(
            """
            select gap_id, dataset_id, partition_value, status,
                   reason_category, source_name,
                   cast(first_seen_at as varchar),
                   cast(last_checked_at as varchar),
                   cast(next_retry_at as varchar), impact_text,
                   cast(detail_json as varchar)
            from research_data_gaps
            where dataset_id like 'scope:%'
            order by gap_id
            """
        ).fetchall()
    fields = (
        "gap_id",
        "dataset_id",
        "partition_value",
        "status",
        "reason_category",
        "source_name",
        "first_seen_at",
        "last_checked_at",
        "next_retry_at",
        "impact_text",
        "detail_json",
    )
    return [dict(zip(fields, row, strict=True)) for row in rows]


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
    deleted = report["deleted"]
    text = (
        f"虚拟任务范围缺口清理：{report['migration_id']}\n"
        f"状态：{report['status']}\n"
        f"删除 scope:* 元数据：{deleted['rows']} 条。\n"
        "保留真实数据集、真实分区及其缺口记录。\n"
        f"可恢复行备份：{report['backup']}\n"
    )
    _write_text_atomic(repair_root / "receipt.txt", text)


def _write_json_atomic(path: Path, payload: Any) -> None:
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
    parser = argparse.ArgumentParser(description="清理 scope:* 虚拟缺口元数据")
    parser.add_argument("--warehouse", required=True, type=Path)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.apply:
        if args.archive is None:
            parser.error("--apply requires --archive")
        report = run_virtual_scope_gap_cleanup(args.warehouse, args.archive)
    else:
        report = inspect_virtual_scope_gaps(args.warehouse)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
