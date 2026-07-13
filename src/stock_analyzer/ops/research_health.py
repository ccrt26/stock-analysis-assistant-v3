from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

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
    duplicate_business_keys: int


class ResearchHealthReport(BaseModel):
    data_date: date
    generated_at: datetime
    datasets: tuple[DatasetHealth, ...]
    gap_counts: dict[str, int]
    complete_core_date: bool


def build_research_health_report(
    warehouse: ResearchWarehouse,
    data_date: date,
) -> ResearchHealthReport:
    datasets: list[DatasetHealth] = []
    core_complete = True
    for dataset_id, contract in research_contract_registry().items():
        manifest = warehouse.partition_manifest(dataset_id)
        partitions = len(manifest)
        rows = int(manifest["row_count"].sum()) if not manifest.empty else 0
        current = warehouse.read_current(dataset_id)
        duplicates = 0
        if not current.empty:
            duplicates = int(
                current.duplicated(subset=list(contract.business_key), keep=False).sum()
            )
        values = (
            sorted(manifest["partition_value"].astype(str))
            if not manifest.empty
            else []
        )
        datasets.append(
            DatasetHealth(
                dataset_id=dataset_id.value,
                partitions=partitions,
                rows=rows,
                first_partition=values[0] if values else None,
                last_partition=values[-1] if values else None,
                duplicate_business_keys=duplicates,
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
        "| 数据 | 分区 | 记录 | 起始 | 截止 | 重复业务事实 |",
        "| --- | ---: | ---: | --- | --- | ---: |",
    ]
    for item in report.datasets:
        lines.append(
            f"| {item.dataset_id} | {item.partitions} | {item.rows} | "
            f"{item.first_partition or '-'} | {item.last_partition or '-'} | "
            f"{item.duplicate_business_keys} |"
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
