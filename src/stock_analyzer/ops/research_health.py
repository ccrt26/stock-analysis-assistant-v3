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
from stock_analyzer.storage.research_contract_audit import (
    audit_fact_partition_contract,
)
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
    effective_interval_overlaps: int
    effective_interval_issues: tuple[str, ...]
    invalid_revision_intervals: int
    overlapping_revision_intervals: int
    missing_files: int
    hash_mismatches: int
    row_count_mismatches: int
    schema_mismatch_partitions: int
    coverage_failure_partitions: int
    missing_required_columns: tuple[str, ...]
    required_field_min_coverage: dict[str, float]
    contract_valid: bool
    physical_valid: bool


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


class StageRunHealth(BaseModel):
    stage: str
    data_date: date
    run_id: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    issues: tuple[str, ...]


class ResearchHealthReport(BaseModel):
    data_date: date
    generated_at: datetime
    datasets: tuple[DatasetHealth, ...]
    gap_counts: dict[str, int]
    complete_core_date: bool
    derived_features: tuple[DerivedFeatureHealth, ...]
    derived_ready_for_research: bool
    derived_has_declared_gaps: bool
    latest_stage_runs: tuple[StageRunHealth, ...]


def build_research_health_report(
    warehouse: ResearchWarehouse,
    data_date: date,
    *,
    full_history: bool = False,
) -> ResearchHealthReport:
    datasets: list[DatasetHealth] = []
    core_complete = True
    revision_audit = _revision_interval_audit(warehouse)
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
        interval_scoped_dataset = dataset_id in {
            ResearchDatasetId.INDUSTRY_CATALOG,
            ResearchDatasetId.INDUSTRY_MEMBER,
        }
        if (
            not full_history
            and not manifest.empty
            and not interval_scoped_dataset
        ):
            same_day = manifest[
                manifest["partition_value"].astype(str) == data_date.isoformat()
            ]
            selected = same_day if not same_day.empty else manifest.tail(1)
        file_audit = _audit_partition_files(warehouse, selected, contract)
        interval_audit = _effective_interval_audit(
            dataset_id,
            file_audit["paths"],
        )
        revision_issues = revision_audit.get(
            dataset_id.value,
            {"invalid": 0, "overlaps": 0},
        )
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
                effective_interval_overlaps=interval_audit["overlaps"],
                effective_interval_issues=tuple(interval_audit["issues"]),
                invalid_revision_intervals=revision_issues["invalid"],
                overlapping_revision_intervals=revision_issues["overlaps"],
                missing_files=file_audit["missing"],
                hash_mismatches=file_audit["hash_mismatches"],
                row_count_mismatches=file_audit["row_count_mismatches"],
                schema_mismatch_partitions=file_audit[
                    "schema_mismatch_partitions"
                ],
                coverage_failure_partitions=file_audit[
                    "coverage_failure_partitions"
                ],
                missing_required_columns=tuple(
                    file_audit["missing_required_columns"]
                ),
                required_field_min_coverage=file_audit[
                    "required_field_min_coverage"
                ],
                contract_valid=(
                    file_audit["contract_valid"]
                    and interval_audit["overlaps"] == 0
                    and revision_issues["invalid"] == 0
                    and revision_issues["overlaps"] == 0
                ),
                physical_valid=file_audit["physical_valid"],
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
                core_complete &= (
                    partitions > 0
                    and file_audit["physical_valid"]
                    and interval_audit["overlaps"] == 0
                    and revision_issues["invalid"] == 0
                    and revision_issues["overlaps"] == 0
                )
            else:
                core_complete &= (
                    data_date.isoformat() in set(values)
                    and file_audit["physical_valid"]
                    and revision_issues["invalid"] == 0
                    and revision_issues["overlaps"] == 0
                )
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
        latest_stage_runs=_latest_stage_runs(warehouse),
    )


def _latest_stage_runs(
    warehouse: ResearchWarehouse,
) -> tuple[StageRunHealth, ...]:
    with connect_research_warehouse(
        warehouse.duckdb_path, read_only=True
    ) as connection:
        rows = connection.execute(
            """
            select stage, cast(data_date as varchar), run_id, status,
                   cast(started_at as varchar), cast(finished_at as varchar),
                   cast(summary_json as varchar)
            from research_ingestion_runs
            qualify row_number() over (
                partition by stage order by started_at desc, run_id desc
            ) = 1
            order by stage
            """
        ).fetchall()
    result: list[StageRunHealth] = []
    for row in rows:
        payload = json.loads(row[6]) if row[6] else {}
        issues: list[str] = []
        if payload.get("message"):
            issues.append(str(payload["message"]))
        for summary in payload.get("summaries", []):
            issues.extend(str(item) for item in summary.get("issues", []))
        result.append(
            StageRunHealth(
                stage=str(row[0]),
                data_date=date.fromisoformat(row[1]),
                run_id=str(row[2]),
                status=str(row[3]),
                started_at=datetime.fromisoformat(row[4]),
                finished_at=(
                    datetime.fromisoformat(row[5]) if row[5] else None
                ),
                issues=tuple(dict.fromkeys(issues)),
            )
        )
    return tuple(result)


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


def _audit_partition_files(
    warehouse: ResearchWarehouse,
    manifest,
    contract,
) -> dict[str, Any]:
    paths: list[str] = []
    rows = 0
    missing = 0
    hash_mismatches = 0
    row_count_mismatches = 0
    schema_mismatch_partitions = 0
    coverage_failure_partitions = 0
    missing_required_columns: set[str] = set()
    required_field_min_coverage: dict[str, float] = {}
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
        contract_audit = audit_fact_partition_contract(path, contract)
        if contract_audit.missing_required_columns:
            schema_mismatch_partitions += 1
            missing_required_columns.update(
                contract_audit.missing_required_columns
            )
        if contract_audit.coverage_failures:
            coverage_failure_partitions += 1
        for column, ratio in contract_audit.required_field_coverage.items():
            required_field_min_coverage[column] = min(
                required_field_min_coverage.get(column, 1.0), ratio
            )
    return {
        "paths": paths,
        "rows": rows,
        "missing": missing,
        "hash_mismatches": hash_mismatches,
        "row_count_mismatches": row_count_mismatches,
        "schema_mismatch_partitions": schema_mismatch_partitions,
        "coverage_failure_partitions": coverage_failure_partitions,
        "missing_required_columns": sorted(missing_required_columns),
        "required_field_min_coverage": required_field_min_coverage,
        "contract_valid": (
            schema_mismatch_partitions == 0
            and coverage_failure_partitions == 0
        ),
        "physical_valid": (
            missing == 0
            and hash_mismatches == 0
            and row_count_mismatches == 0
            and schema_mismatch_partitions == 0
            and coverage_failure_partitions == 0
        ),
    }


def _revision_interval_audit(
    warehouse: ResearchWarehouse,
) -> dict[str, dict[str, int]]:
    with connect_research_warehouse(
        warehouse.duckdb_path, read_only=True
    ) as connection:
        rows = connection.execute(
            """
            with ordered as (
                select dataset_id, valid_from, valid_to,
                       lag(valid_to) over (
                           partition by dataset_id, business_key_hash
                           order by valid_from, valid_to, revision_no
                       ) as prior_valid_to
                from research_fact_revisions
            )
            select dataset_id,
                   count(*) filter (where valid_to <= valid_from) as invalid,
                   count(*) filter (
                       where prior_valid_to > valid_from
                   ) as overlaps
            from ordered
            group by dataset_id
            """
        ).fetchall()
    return {
        str(dataset_id): {
            "invalid": int(invalid),
            "overlaps": int(overlaps),
        }
        for dataset_id, invalid, overlaps in rows
    }


def _effective_interval_audit(
    dataset_id: ResearchDatasetId,
    paths: list[str],
) -> dict[str, Any]:
    if not paths or dataset_id not in {
        ResearchDatasetId.INDUSTRY_CATALOG,
        ResearchDatasetId.INDUSTRY_MEMBER,
    }:
        return {"overlaps": 0, "issues": []}
    if dataset_id is ResearchDatasetId.INDUSTRY_MEMBER:
        return _industry_member_interval_audit(paths)
    with duckdb.connect() as connection:
        rows = connection.execute(
            """
            select industry_system, level, industry_code, valid_from, valid_to
            from read_parquet(?, union_by_name=true, hive_partitioning=false)
            order by industry_system, level, industry_code, valid_from
            """,
            [paths],
        ).fetchall()
    issues: list[str] = []
    active: dict[
        tuple[str, str, str],
        list[tuple[Any, Any]],
    ] = {}
    for system, level, code, valid_from, valid_to in rows:
        key = (str(system), str(level), str(code))
        if valid_to is not None and valid_to < valid_from:
            issues.append(
                f"{key[0]}/{key[1]}/{key[2]}: "
                f"{_interval_text(valid_from, valid_to)} inverted"
            )
        still_active = [
            interval
            for interval in active.get(key, [])
            if interval[1] is None or valid_from <= interval[1]
        ]
        for prior_from, prior_to in still_active:
            issues.append(
                f"{key[0]}/{key[1]}/{key[2]}: "
                f"{_interval_text(prior_from, prior_to)} overlaps "
                f"{_interval_text(valid_from, valid_to)}"
            )
        still_active.append((valid_from, valid_to))
        active[key] = still_active
    return {"overlaps": len(issues), "issues": issues}


def _industry_member_interval_audit(paths: list[str]) -> dict[str, Any]:
    with duckdb.connect() as connection:
        rows = connection.execute(
            """
            select industry_system, level, ts_code, industry_code,
                   valid_from, valid_to
            from read_parquet(?, union_by_name=true, hive_partitioning=false)
            order by industry_system, level, ts_code, valid_from, industry_code
            """,
            [paths],
        ).fetchall()

    issues: list[str] = []
    active: dict[
        tuple[str, str, str],
        list[tuple[str, Any, Any]],
    ] = {}
    for system, level, ts_code, industry_code, valid_from, valid_to in rows:
        slot = (str(system), str(level), str(ts_code))
        if valid_to is not None and valid_to < valid_from:
            issues.append(
                f"industry_member {slot[0]}/{slot[1]}/{ts_code}: "
                f"{industry_code} {_interval_text(valid_from, valid_to)} inverted"
            )
        still_active = [
            item
            for item in active.get(slot, [])
            if item[2] is None or valid_from <= item[2]
        ]
        for prior_code, prior_from, prior_to in still_active:
            issues.append(
                f"industry_member {slot[0]}/{slot[1]}/{ts_code}: "
                f"{prior_code} {_interval_text(prior_from, prior_to)} overlaps "
                f"{industry_code} {_interval_text(valid_from, valid_to)}"
            )
        still_active.append((str(industry_code), valid_from, valid_to))
        active[slot] = still_active
    return {"overlaps": len(issues), "issues": issues}


def _interval_text(valid_from: Any, valid_to: Any) -> str:
    end = "open" if valid_to is None else str(valid_to)
    return f"{valid_from}..{end}"


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
        "## 最近一次真实任务",
        "",
        "| 阶段 | 数据日期 | 状态 | 问题摘要 |",
        "| --- | --- | --- | --- |",
    ]
    for run in report.latest_stage_runs:
        lines.append(
            f"| {run.stage} | {run.data_date.isoformat()} | {run.status} | "
            f"{'；'.join(run.issues) or '-'} |"
        )
    if not report.latest_stage_runs:
        lines.append("| - | - | 尚无运行记录 | - |")
    lines.extend(
        [
        "",
        "| 数据 | 分区 | 记录 | 本次核对分区 | 重复业务事实 | 缺文件 | 校验不符 | 契约异常 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for item in report.datasets:
        lines.append(
            f"| {item.dataset_id} | {item.partitions} | {item.rows} | "
            f"{item.checked_partitions} | {item.duplicate_business_keys} | "
            f"{item.missing_files} | "
            f"{item.hash_mismatches + item.row_count_mismatches} | "
            f"{item.schema_mismatch_partitions + item.coverage_failure_partitions + item.effective_interval_overlaps + item.invalid_revision_intervals + item.overlapping_revision_intervals} |"
        )
        for issue in item.effective_interval_issues:
            lines.append(f"- {item.dataset_id} 有效区间重叠：{issue}。")
        if item.invalid_revision_intervals or item.overlapping_revision_intervals:
            lines.append(
                f"- {item.dataset_id} 修订链异常：非正区间 "
                f"{item.invalid_revision_intervals} 条，重叠 "
                f"{item.overlapping_revision_intervals} 条。"
            )
        if item.missing_required_columns:
            lines.append(
                f"- {item.dataset_id} 缺少契约必需列："
                + "、".join(item.missing_required_columns)
                + "。"
            )
        if item.coverage_failure_partitions:
            coverage = "、".join(
                f"{field}={ratio:.2%}"
                for field, ratio in sorted(
                    item.required_field_min_coverage.items()
                )
            )
            lines.append(
                f"- {item.dataset_id} 有 {item.coverage_failure_partitions} 个分区"
                f"未达到核心字段覆盖阈值：{coverage}。"
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
    "StageRunHealth",
    "ResearchHealthReport",
    "build_research_health_report",
    "write_health_report",
]
