from __future__ import annotations

import json
import hashlib
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import duckdb
import pyarrow.parquet as pq
from pydantic import BaseModel

from stock_analyzer.data.research_contracts import research_contract_registry
from stock_analyzer.storage.research_schema import connect_research_warehouse
from stock_analyzer.storage.research_warehouse import ResearchWarehouse


class DatasetHealth(BaseModel):
    dataset_id: str
    partitions: int
    rows: int
    first_partition: str | None
    last_partition: str | None
    checked_partitions: int
    checked_rows: int
    duplicate_business_keys: int
    missing_files: int
    hash_mismatches: int
    row_count_mismatches: int


class ResearchHealthReport(BaseModel):
    data_date: date
    generated_at: datetime
    datasets: tuple[DatasetHealth, ...]
    gap_counts: dict[str, int]
    complete_core_date: bool


def build_research_health_report(
    warehouse: ResearchWarehouse,
    data_date: date,
    *,
    full_history: bool = False,
) -> ResearchHealthReport:
    datasets: list[DatasetHealth] = []
    core_complete = True
    for dataset_id, contract in research_contract_registry().items():
        manifest = warehouse.partition_manifest(dataset_id)
        partitions = len(manifest)
        rows = int(manifest["row_count"].sum()) if not manifest.empty else 0
        values = (
            sorted(manifest["partition_value"].astype(str))
            if not manifest.empty
            else []
        )
        selected = manifest
        if not full_history and not manifest.empty:
            same_day = manifest[
                manifest["partition_value"].astype(str) == data_date.isoformat()
            ]
            selected = same_day if not same_day.empty else manifest.tail(1)
        file_audit = _audit_partition_files(warehouse, selected)
        duplicates = 0
        if full_history and file_audit["paths"]:
            with duckdb.connect() as connection:
                physical_rows, unique_keys = connection.execute(
                    """
                    select count(*), count(distinct business_key_hash)
                    from read_parquet(?, union_by_name=true, hive_partitioning=false)
                    """,
                    [file_audit["paths"]],
                ).fetchone()
            duplicates = int(physical_rows - unique_keys)
        datasets.append(
            DatasetHealth(
                dataset_id=dataset_id.value,
                partitions=partitions,
                rows=rows,
                first_partition=values[0] if values else None,
                last_partition=values[-1] if values else None,
                checked_partitions=len(selected),
                checked_rows=file_audit["rows"],
                duplicate_business_keys=duplicates,
                missing_files=file_audit["missing"],
                hash_mismatches=file_audit["hash_mismatches"],
                row_count_mismatches=file_audit["row_count_mismatches"],
            )
        )
        if contract.required_for_close_screen:
            if dataset_id.value in {
                "trade_calendar",
                "security_master",
                "industry_catalog",
                "industry_member",
                "theme_catalog",
                "theme_member",
            }:
                core_complete &= partitions > 0
            else:
                core_complete &= data_date.isoformat() in set(values)
    with connect_research_warehouse(
        warehouse.duckdb_path, read_only=True
    ) as connection:
        gap_rows = connection.execute(
            "select status, count(*) from research_data_gaps group by status"
        ).fetchall()
    return ResearchHealthReport(
        data_date=data_date,
        generated_at=datetime.now(timezone.utc),
        datasets=tuple(datasets),
        gap_counts={str(status): int(count) for status, count in gap_rows},
        complete_core_date=bool(core_complete),
    )


def _audit_partition_files(warehouse: ResearchWarehouse, manifest) -> dict[str, Any]:
    paths: list[str] = []
    rows = 0
    missing = 0
    hash_mismatches = 0
    row_count_mismatches = 0
    for item in manifest.to_dict(orient="records"):
        path = warehouse.root / str(item["relative_path"])
        if not path.is_file():
            missing += 1
            continue
        paths.append(str(path))
        metadata_rows = int(pq.ParquetFile(path).metadata.num_rows)
        rows += metadata_rows
        if metadata_rows != int(item["row_count"]):
            row_count_mismatches += 1
        if _sha256(path) != str(item["file_sha256"]):
            hash_mismatches += 1
    return {
        "paths": paths,
        "rows": rows,
        "missing": missing,
        "hash_mismatches": hash_mismatches,
        "row_count_mismatches": row_count_mismatches,
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_health_report(
    report: ResearchHealthReport,
    output_root: Path,
) -> tuple[Path, Path]:
    output_root.mkdir(parents=True, exist_ok=True)
    stem = report.data_date.isoformat()
    json_path = output_root / f"{stem}.json"
    md_path = output_root / f"{stem}.md"
    json_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    lines = [
        f"# {stem} 数据健康摘要",
        "",
        f"收盘核心数据是否完整：{'是' if report.complete_core_date else '否'}",
        "",
        "| 数据 | 分区 | 记录 | 本次核对分区 | 重复业务事实 | 缺文件 | 校验不符 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in report.datasets:
        lines.append(
            f"| {item.dataset_id} | {item.partitions} | {item.rows} | "
            f"{item.checked_partitions} | {item.duplicate_business_keys} | "
            f"{item.missing_files} | "
            f"{item.hash_mismatches + item.row_count_mismatches} |"
        )
    lines.extend(["", "未完成或等待事项：", ""])
    if report.gap_counts:
        for status, count in sorted(report.gap_counts.items()):
            lines.append(f"- {status}: {count}")
    else:
        lines.append("- 无已登记缺口。")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


__all__ = [
    "DatasetHealth",
    "ResearchHealthReport",
    "build_research_health_report",
    "write_health_report",
]
