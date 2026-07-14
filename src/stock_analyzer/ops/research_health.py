from __future__ import annotations

import json
import hashlib
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import duckdb
import pyarrow.parquet as pq
from pydantic import BaseModel

from stock_analyzer.analysis.hotspot_features import HOTSPOT_FORMULA_VERSION
from stock_analyzer.analysis.market_context_features import MARKET_CONTEXT_FORMULA_VERSION
from stock_analyzer.analysis.stock_context_features import STOCK_CONTEXT_FORMULA_VERSION
from stock_analyzer.data.research_contracts import (
    ResearchDatasetId,
    research_contract_registry,
)
from stock_analyzer.storage.research_query import ResearchQuery
from stock_analyzer.storage.research_schema import connect_research_warehouse
from stock_analyzer.storage.research_warehouse import ResearchWarehouse


_EXPECTED_DERIVED_FORMULAS = {
    "market_context": MARKET_CONTEXT_FORMULA_VERSION,
    "sector_hotspot": HOTSPOT_FORMULA_VERSION,
    "stock_trading_context": STOCK_CONTEXT_FORMULA_VERSION,
}


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


class DerivedFeatureHealth(BaseModel):
    feature_set: str
    expected_formula_version: str
    formula_version: str | None
    present: bool
    rows: int
    checked_rows: int
    quality_status: str | None
    limitations: tuple[str, ...]
    no_membership_entities: int
    no_membership_industries: int
    no_membership_themes: int
    intraday_limited_entities: int
    missing_files: int
    hash_mismatches: int
    row_count_mismatches: int
    stale_formula: bool
    stale_input_manifest: bool
    unresolved_failed_runs: int
    ready: bool


class ResearchHealthReport(BaseModel):
    data_date: date
    generated_at: datetime
    datasets: tuple[DatasetHealth, ...]
    gap_counts: dict[str, int]
    complete_core_date: bool
    derived_features: tuple[DerivedFeatureHealth, ...]
    derived_ready_for_research: bool
    derived_has_declared_gaps: bool


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
    derived = _build_derived_health(warehouse, data_date)
    return ResearchHealthReport(
        data_date=data_date,
        generated_at=datetime.now(timezone.utc),
        datasets=tuple(datasets),
        gap_counts={str(status): int(count) for status, count in gap_rows},
        complete_core_date=bool(core_complete),
        derived_features=derived,
        derived_ready_for_research=all(item.ready for item in derived),
        derived_has_declared_gaps=any(
            item.quality_status == "complete_with_declared_gaps"
            or bool(item.limitations)
            for item in derived
        ),
    )


def _build_derived_health(
    warehouse: ResearchWarehouse,
    data_date: date,
) -> tuple[DerivedFeatureHealth, ...]:
    with connect_research_warehouse(
        warehouse.duckdb_path, read_only=True
    ) as connection:
        partitions = connection.execute(
            """
            select * from research_derived_partitions
            where analysis_date = ?
            order by feature_set, committed_at desc
            """,
            [data_date],
        ).fetchdf()
        failed_runs = connection.execute(
            """
            select feature_set, formula_version, started_at
            from research_derived_runs
            where analysis_date = ? and status = 'failed'
            """,
            [data_date],
        ).fetchdf()

    result: list[DerivedFeatureHealth] = []
    for feature_set, expected_formula in _EXPECTED_DERIVED_FORMULAS.items():
        candidates = partitions[
            partitions["feature_set"].astype(str) == feature_set
        ]
        expected = candidates[
            candidates["formula_version"].astype(str) == expected_formula
        ]
        present = not expected.empty
        stale_formula = not candidates.empty and expected.empty
        selected = expected.head(1) if present else candidates.head(1)
        formula_version: str | None = None
        quality_status: str | None = None
        limitations: tuple[str, ...] = ()
        rows = 0
        checked_rows = 0
        missing_files = 0
        hash_mismatches = 0
        row_count_mismatches = 0
        no_membership_entities = 0
        no_membership_industries = 0
        no_membership_themes = 0
        intraday_limited_entities = 0
        stale_input_manifest = False
        committed_at: datetime | None = None

        if not selected.empty:
            row = selected.iloc[0]
            formula_version = str(row["formula_version"])
            quality_status = str(row["quality_status"])
            limitations = _json_text_tuple(row["limitations_json"])
            rows = int(row["row_count"])
            committed_at = _as_utc_datetime(row["committed_at"])
            audit = _audit_derived_partition(warehouse, row)
            checked_rows = audit["rows"]
            missing_files = audit["missing"]
            hash_mismatches = audit["hash_mismatches"]
            row_count_mismatches = audit["row_count_mismatches"]
            no_membership_entities = audit["no_membership_entities"]
            no_membership_industries = audit["no_membership_industries"]
            no_membership_themes = audit["no_membership_themes"]
            intraday_limited_entities = audit["intraday_limited_entities"]
            stale_input_manifest = _derived_input_is_stale(
                warehouse, row["input_manifest_json"]
            )

        matching_failures = failed_runs[
            (failed_runs["feature_set"].astype(str) == feature_set)
            & (failed_runs["formula_version"].astype(str) == expected_formula)
        ]
        if committed_at is not None and not matching_failures.empty:
            failure_times = matching_failures["started_at"].map(_as_utc_datetime)
            matching_failures = matching_failures[failure_times > committed_at]
        unresolved_failed_runs = len(matching_failures)
        ready = (
            present
            and quality_status in {"complete", "complete_with_declared_gaps"}
            and missing_files == 0
            and hash_mismatches == 0
            and row_count_mismatches == 0
            and not stale_input_manifest
            and unresolved_failed_runs == 0
        )
        result.append(
            DerivedFeatureHealth(
                feature_set=feature_set,
                expected_formula_version=expected_formula,
                formula_version=formula_version,
                present=present,
                rows=rows,
                checked_rows=checked_rows,
                quality_status=quality_status,
                limitations=limitations,
                no_membership_entities=no_membership_entities,
                no_membership_industries=no_membership_industries,
                no_membership_themes=no_membership_themes,
                intraday_limited_entities=intraday_limited_entities,
                missing_files=missing_files,
                hash_mismatches=hash_mismatches,
                row_count_mismatches=row_count_mismatches,
                stale_formula=stale_formula,
                stale_input_manifest=stale_input_manifest,
                unresolved_failed_runs=unresolved_failed_runs,
                ready=ready,
            )
        )
    return tuple(result)


def _audit_derived_partition(
    warehouse: ResearchWarehouse,
    row: Any,
) -> dict[str, int]:
    path = warehouse.root / str(row["relative_path"])
    audit = {
        "rows": 0,
        "missing": 0,
        "hash_mismatches": 0,
        "row_count_mismatches": 0,
        "no_membership_entities": 0,
        "no_membership_industries": 0,
        "no_membership_themes": 0,
        "intraday_limited_entities": 0,
    }
    if not path.is_file():
        audit["missing"] = 1
        return audit
    parquet = pq.ParquetFile(path)
    audit["rows"] = int(parquet.metadata.num_rows)
    audit["row_count_mismatches"] = int(
        audit["rows"] != int(row["row_count"])
    )
    audit["hash_mismatches"] = int(
        _sha256(path) != str(row["file_sha256"])
    )
    names = set(parquet.schema_arrow.names)
    columns = [
        name
        for name in ("coverage_status", "group_type", "intraday_status")
        if name in names
    ]
    if columns:
        observations = parquet.read(columns=columns).to_pandas()
        if "coverage_status" in observations:
            no_membership = (
                observations["coverage_status"].astype(str)
                == "limited_no_membership"
            )
            audit["no_membership_entities"] = int(no_membership.sum())
            if "group_type" in observations:
                group_type = observations["group_type"].astype(str)
                audit["no_membership_industries"] = int(
                    (no_membership & group_type.eq("industry")).sum()
                )
                audit["no_membership_themes"] = int(
                    (no_membership & group_type.eq("theme")).sum()
                )
        if "intraday_status" in observations:
            audit["intraday_limited_entities"] = int(
                (observations["intraday_status"].astype(str) == "limited").sum()
            )
    return audit


def _derived_input_is_stale(
    warehouse: ResearchWarehouse,
    raw_manifest: Any,
) -> bool:
    try:
        manifest = _json_object(raw_manifest)
        snapshot = manifest["fact_snapshot"]
        requested: dict[ResearchDatasetId, list[str]] = {}
        for item in snapshot["partitions"]:
            dataset = ResearchDatasetId(str(item["dataset"]))
            requested.setdefault(dataset, []).append(str(item["partition"]))
        current = ResearchQuery(warehouse).input_manifest(
            {key: tuple(values) for key, values in requested.items()},
            as_of=datetime.fromisoformat(str(snapshot["as_of"])),
        )
        return str(current["input_manifest_hash"]) != str(
            snapshot["input_manifest_hash"]
        )
    except Exception:
        return True


def _json_object(value: Any) -> dict[str, Any]:
    parsed = json.loads(value) if isinstance(value, str) else value
    if not isinstance(parsed, dict):
        raise ValueError("expected JSON object")
    return parsed


def _json_text_tuple(value: Any) -> tuple[str, ...]:
    parsed = json.loads(value) if isinstance(value, str) else value
    if parsed is None:
        return ()
    return tuple(str(item) for item in parsed)


def _as_utc_datetime(value: Any) -> datetime:
    stamp = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc)


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
    lines.extend(
        [
            "",
            "## 每日研究观察",
            "",
            (
                "三类研究观察：可以使用，但有明确限制。"
                if report.derived_ready_for_research
                and report.derived_has_declared_gaps
                else (
                    "三类研究观察：已通过完整性检查。"
                    if report.derived_ready_for_research
                    else "三类研究观察：尚未全部通过，不应当作完整输入。"
                )
            ),
            "",
            "| 观察类型 | 行数 | 公式 | 状态 | 可用 | 文件/输入异常 |",
            "| --- | ---: | --- | --- | --- | ---: |",
        ]
    )
    for item in report.derived_features:
        problems = (
            item.missing_files
            + item.hash_mismatches
            + item.row_count_mismatches
            + int(item.stale_formula)
            + int(item.stale_input_manifest)
            + item.unresolved_failed_runs
        )
        lines.append(
            f"| {item.feature_set} | {item.rows} | "
            f"{item.formula_version or '-'} | {item.quality_status or '缺失'} | "
            f"{'是' if item.ready else '否'} | {problems} |"
        )
        if item.no_membership_themes:
            lines.append(
                f"- {item.no_membership_themes} 个主题没有公开成分股，"
                "程序保留了主题名称，但不编造板块内部结论。"
            )
        if item.no_membership_industries:
            lines.append(
                f"- {item.no_membership_industries} 个行业目录没有可用成分股，"
                "程序保留目录状态，但不参与热点比较。"
            )
        if item.intraday_limited_entities:
            lines.append(
                f"- {item.intraday_limited_entities} 个板块的分钟数据不可用，"
                "盘中持续性和尾盘拉升等观察保持空值。"
            )
        for limitation in item.limitations:
            lines.append(f"- {item.feature_set}：{limitation}")
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
    "DerivedFeatureHealth",
    "ResearchHealthReport",
    "build_research_health_report",
    "write_health_report",
]
