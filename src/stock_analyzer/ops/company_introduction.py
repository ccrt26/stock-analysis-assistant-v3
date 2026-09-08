"""公司介绍：正式推荐附属资料的只读备料、单篇保存与展示读取。

prepare 只读事实仓与正式 trace，产出一次介绍写作所需的紧凑事实（facts-file）；
record 校验 AI 撰写的单篇介绍并原子保存到 local_archive/company_introductions。
介绍是正式推荐的后续附属资料：不进入 DuckDB、Forward CSV、V4 trace、
monitor snapshot 或复盘模型，不参与正式身份判定，也不反过来阻断推荐或网页同步。
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal, Sequence
from zoneinfo import ZoneInfo

import duckdb
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from stock_analyzer.data.research_contracts import ResearchDatasetId
from stock_analyzer.ops.forward_selection import selection_output_class
from stock_analyzer.storage.research_query import ResearchQuery
from stock_analyzer.storage.research_warehouse import FactRecoveryError, ResearchWarehouse


SHANGHAI = ZoneInfo("Asia/Shanghai")
INTRO_SCHEMA_VERSION = "company-introduction-v1"
FACTS_FILE_VERSION = "company-introduction-facts-v1"
INTRO_DIR_NAME = "company_introductions"
SELECTION_DIR_NAME = "forward_selection"
RECORDABLE_OUTPUT_CLASSES = frozenset(
    {"confirmed_active", "legacy_v1_not_rewritten"}
)
PRODUCTION_OUTPUT_CLASSES = frozenset({"confirmed_active"})
# 仅处理已有读取/连接故障；SQL、字段绑定和其他程序错误继续抛出。
_LOCAL_READ_ERRORS = (
    OSError,
    FactRecoveryError,
    duckdb.IOException,
    duckdb.ConnectionException,
    duckdb.PermissionException,
)
ANNOUNCEMENT_MONTH_COUNT = 3
ANNOUNCEMENT_ROW_LIMIT = 15
STATEMENT_PARTITION_WINDOW = 8
DISPLAY_OUTPUT_CLASSES = frozenset(
    {"confirmed_active", "legacy_v1_not_rewritten"}
)


# ---------------------------------------------------------------------------
# 时间与路径小工具
# ---------------------------------------------------------------------------


def _require_aware(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must include a timezone")
    return value


def _parse_as_of(value: Any, label: str) -> datetime:
    try:
        parsed = (
            value
            if isinstance(value, datetime)
            else datetime.fromisoformat(str(value))
        )
    except ValueError as error:
        raise ValueError(f"{label} is not an ISO datetime: {value!r}") from error
    return _require_aware(parsed, label)


def _shanghai_date(value: datetime) -> date:
    return value.astimezone(SHANGHAI).date()


def intro_path(intro_root: Path, action_date: str, ts_code: str) -> Path:
    return Path(intro_root) / action_date / f"{ts_code}.json"


def default_intro_root(project_root: Path) -> Path:
    return Path(project_root) / "local_archive" / INTRO_DIR_NAME


def default_selection_dir(project_root: Path) -> Path:
    return Path(project_root) / "local_archive" / SELECTION_DIR_NAME


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=path.name + ".tmp-",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(payload, stream, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as error:
        raise ValueError(f"cannot read {path}: {error}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"{path} is not valid JSON: {error}") from error
    if not isinstance(document, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return document


# ---------------------------------------------------------------------------
# 正式 trace 读取与范围解析（不改写、不重跑研究）
# ---------------------------------------------------------------------------


def load_formal_trace(selection_dir: Path, formation_date: str) -> dict[str, Any]:
    """按原归档文件名读取 trace 原始 JSON；不做 V4 模型解析，历史 V1 原样可用。"""

    path = Path(selection_dir) / f"research-trace-{formation_date}.json"
    if not path.is_file():
        raise ValueError(f"formal trace is missing: {path}")
    trace = _load_json(path)
    if str(trace.get("formation_date") or "") != formation_date:
        raise ValueError(
            f"trace formation_date does not match {formation_date}: {path}"
        )
    return trace


def trace_context(trace: dict[str, Any]) -> dict[str, str]:
    formation = str(trace.get("formation_date") or "")
    action = str(trace.get("action_date") or "")
    as_of = str(trace.get("as_of") or "")
    if not formation or not action or not as_of:
        raise ValueError("formal trace is missing formation_date/action_date/as_of")
    _parse_as_of(as_of, "trace as_of")
    if action <= formation:
        raise ValueError("trace action_date must follow formation_date")
    return {
        "formation_date": formation,
        "action_date": action,
        "as_of": as_of,
        "trace_version": str(trace.get("trace_version") or ""),
    }


def selected_candidates(trace: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in trace.get("candidate_ledger") or []:
        if isinstance(item, dict) and item.get("final_fate") == "selected":
            result.append(item)
    return result


def candidate_class(
    trace: dict[str, Any], candidate: dict[str, Any]
) -> str:
    return selection_output_class(
        trace_version=str(trace.get("trace_version") or ""),
        candidate=candidate,
    )


def research_completed(trace: dict[str, Any]) -> bool:
    research = trace.get("research_result") or {}
    return bool(
        isinstance(research, dict)
        and research.get("research_completed")
        and research.get("point_in_time_evidence_verified")
    )


# ---------------------------------------------------------------------------
# 介绍文章的轻量合同
# ---------------------------------------------------------------------------


class IntroSection(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1)
    paragraphs: list[str] = Field(min_length=1)
    table: dict[str, Any] | None = None
    source_ids: list[str] = Field(default_factory=list)


class IntroSource(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(min_length=1)
    kind: Literal["warehouse", "official_document"]
    title: str = Field(min_length=1)
    available_at: datetime
    locator: str = Field(min_length=1)
    dataset: str | None = None
    block_id: str | None = None
    report_period: str | None = None
    values: dict[str, Any] | None = None
    url: str | None = None
    availability_basis: str | None = None
    retrieved_at: datetime | None = None

    @model_validator(mode="after")
    def validate_source(self) -> "IntroSource":
        _require_aware(self.available_at, f"source {self.id} available_at")
        if self.kind == "warehouse":
            if not self.dataset or not self.block_id:
                raise ValueError(
                    f"warehouse source {self.id} requires dataset and block_id"
                )
            if self.url is not None or self.retrieved_at is not None:
                raise ValueError(
                    f"warehouse source {self.id} must not carry url/retrieved_at"
                )
        else:
            if not self.availability_basis or self.retrieved_at is None:
                raise ValueError(
                    f"official source {self.id} requires availability_basis "
                    "(公开时间的具体定位) and retrieved_at (实际补读时间)"
                )
            _require_aware(
                self.retrieved_at, f"source {self.id} retrieved_at"
            )
            if self.url is not None and not self.url.lower().startswith(
                ("http://", "https://")
            ):
                raise ValueError(
                    f"official source {self.id} url must be http(s)"
                )
        return self


class CompanyIntroductionV1(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: Literal["company-introduction-v1"]
    ts_code: str = Field(min_length=9, max_length=9)
    name: str = Field(min_length=1)
    formation_date: str
    action_date: str
    as_of: datetime
    generated_at: datetime
    sections: list[IntroSection] = Field(min_length=1)
    sources: list[IntroSource] = Field(min_length=1)
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_structure(self) -> "CompanyIntroductionV1":
        _require_aware(self.as_of, "as_of")
        _require_aware(self.generated_at, "generated_at")
        if self.action_date <= self.formation_date:
            raise ValueError("action_date must follow formation_date")
        if self.generated_at < self.as_of:
            raise ValueError("generated_at must not precede as_of")
        known = {source.id for source in self.sources}
        referenced: set[str] = set()
        for index, section in enumerate(self.sections):
            referenced.update(section.source_ids)
            table = section.table
            if table is None:
                continue
            columns = table.get("columns")
            rows = table.get("rows")
            if (
                not isinstance(columns, list)
                or not columns
                or not isinstance(rows, list)
                or any(not isinstance(row, list) or len(row) != len(columns) for row in rows)
            ):
                raise ValueError(
                    f"sections[{index}] table must have columns and equal-width rows"
                )
        missing = referenced - known
        if missing:
            raise ValueError(f"sections reference unknown source ids: {sorted(missing)}")
        for source in self.sources:
            if source.available_at > self.as_of:
                raise ValueError(
                    f"source {source.id} available_at is after as_of"
                )
        return self


def read_introduction_file(path: Path) -> CompanyIntroductionV1:
    document = _load_json(Path(path))
    try:
        return CompanyIntroductionV1.model_validate(document)
    except ValidationError as error:
        raise ValueError(f"introduction contract violation in {path}: {error}") from error


def introduction_matches_identity(
    intro: CompanyIntroductionV1,
    *,
    ts_code: str,
    formation_date: str,
    action_date: str,
    as_of: str,
) -> bool:
    return (
        intro.ts_code == ts_code
        and intro.formation_date == formation_date
        and intro.action_date == action_date
        and _same_instant(intro.as_of, as_of)
    )


def _same_instant(left: datetime | str, right: datetime | str) -> bool:
    left_dt = left if isinstance(left, datetime) else _parse_as_of(left, "left")
    right_dt = right if isinstance(right, datetime) else _parse_as_of(right, "right")
    return left_dt.astimezone(timezone.utc) == right_dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# 只读备料：分区限定 + 每股事实块
# ---------------------------------------------------------------------------


def _partition_values(
    warehouse: ResearchWarehouse, dataset: ResearchDatasetId
) -> list[str]:
    manifest = warehouse.partition_manifest(dataset)
    if manifest.empty:
        return []
    return sorted(manifest["partition_value"].astype(str))


def _stock_rows(frame: pd.DataFrame, ts_code: str) -> pd.DataFrame:
    if frame.empty or "ts_code" not in frame.columns:
        return frame.iloc[0:0]
    return frame.loc[frame["ts_code"].astype(str) == ts_code]


def _json_value(value: Any) -> Any:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (pd.Timestamp, datetime)):
        return pd.Timestamp(value).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


_DATE_ONLY_FIELDS = frozenset(
    {"report_period", "trade_date", "ann_date", "f_ann_date", "valid_from",
     "snapshot_date", "profile_snapshot_date"}
)


def _row_subset(row: dict[str, Any], columns: Sequence[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for column in columns:
        if column not in row:
            continue
        result[column] = (
            _period_iso(row.get(column))
            if column in _DATE_ONLY_FIELDS
            else _json_value(row.get(column))
        )
    return result


def _iso_or_none(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    try:
        return pd.Timestamp(value).isoformat()
    except (ValueError, TypeError):
        return str(value)


class _FactGatherer:
    """按数据集限定分区并解析 as_of 可见行；查询失败按资料块隔离。"""

    def __init__(
        self,
        query: ResearchQuery,
        as_of: datetime,
        ts_codes: list[str],
    ) -> None:
        self.query = query
        self.warehouse = query.warehouse
        self.as_of = as_of
        self.ts_codes = ts_codes
        self.gaps: list[dict[str, Any]] = []
        self.used_partitions: dict[str, list[str]] = {}
        self.failed_datasets: set[str] = set()
        self._cache: dict[
            ResearchDatasetId, dict[str, pd.DataFrame]
        ] = {}

    def frames(
        self,
        dataset: ResearchDatasetId,
        partitions: Sequence[str],
    ) -> dict[str, pd.DataFrame]:
        """解析一次数据集的可见行，按股票代码分帧缓存。"""

        cached = self._cache.get(dataset)
        if cached is not None:
            return cached
        frames: dict[str, pd.DataFrame] = {
            code: pd.DataFrame() for code in self.ts_codes
        }
        wanted = set(self.ts_codes)
        if partitions and wanted:
            try:
                resolved = self.query.dataset_partitions_as_of(
                    dataset, partitions, self.as_of
                )
                self.used_partitions[dataset.value] = list(partitions)
                if not resolved.empty and "ts_code" in resolved.columns:
                    for code, group in resolved.groupby(
                        resolved["ts_code"].astype(str)
                    ):
                        if code in wanted:
                            frames[code] = group
            except _LOCAL_READ_ERRORS as error:  # 已知读取故障按数据集隔离
                self.failed_datasets.add(dataset.value)
                self.gaps.append(
                    {
                        "dataset": dataset.value,
                        "gap": "query_failed",
                        "detail": str(error),
                    }
                )
        self._cache[dataset] = frames
        return frames

    def note_gap(self, dataset: str, gap: str, detail: str) -> None:
        # 该数据集查询失败时，一切"行/分区缺失"都不可信，只能记查询失败，
        # 不把查不到写成真实无记录。
        if dataset in self.failed_datasets and gap.endswith("_missing"):
            return
        self.gaps.append({"dataset": dataset, "gap": gap, "detail": detail})

    def invalidate(self, dataset: ResearchDatasetId) -> None:
        self._cache.pop(dataset, None)
        self.used_partitions.pop(dataset.value, None)


def _statement_partitions(
    warehouse: ResearchWarehouse,
    dataset: ResearchDatasetId,
    as_of: datetime,
    extra_period: str | None = None,
) -> list[str]:
    upper = _shanghai_date(as_of)
    values = [
        value
        for value in _partition_values(warehouse, dataset)
        if value <= upper.isoformat()
    ]
    chosen = values[-STATEMENT_PARTITION_WINDOW:]
    if extra_period is not None and extra_period in values:
        chosen = sorted(set(chosen) | {extra_period})
    return chosen


def _period_iso(value: Any) -> str:
    """报告期统一为 YYYY-MM-DD：仓库行可能是 Timestamp 或带时间的字符串。"""

    try:
        return pd.Timestamp(value).date().isoformat()
    except (ValueError, TypeError):
        return str(value)[:10]


_REPORT_TYPE_PRIORITY = {
    "1": 0, "4": 1, "2": 2, "3": 3, "5": 4, "6": 5, "9": 6, "7": 7, "8": 8, "10": 9,
}


def _select_comparable_rows(rows: pd.DataFrame) -> pd.DataFrame:
    """同报告期多行时按 comparable_financials_as_of 的既有优先规则选一行。

    规则与 ResearchQuery.comparable_financials_as_of 一致：期末类型匹配 →
    报告类型（合并优先）→ available_at 最新 → statement_type。不复制该函数
    的全库扫描路径，只在本模块已限定分区的行上执行。
    """

    if rows.empty:
        return rows
    frame = rows.copy()
    periods = pd.to_datetime(frame["report_period"], errors="raise")
    expected_end_type = periods.dt.month.map({3: "1", 6: "2", 9: "3", 12: "4"})
    actual_end_type = frame.get(
        "end_type", pd.Series(index=frame.index, dtype="object")
    ).astype("string")
    frame["__end_match"] = actual_end_type.eq(expected_end_type)
    frame["__report_priority"] = (
        frame["report_type"].astype(str).map(_REPORT_TYPE_PRIORITY).fillna(99)
        if "report_type" in frame.columns
        else 99
    )
    frame["__available_rank"] = pd.to_datetime(
        frame["available_at"], errors="coerce", utc=True
    )
    frame["__statement_rank"] = (
        frame["statement_type"].astype(str)
        if "statement_type" in frame.columns
        else ""
    )
    return (
        frame.sort_values(
            ["__end_match", "__report_priority", "__available_rank", "__statement_rank"],
            ascending=[False, True, False, True],
            kind="mergesort",
        )
        .drop_duplicates(["report_period"], keep="first")
    )


def _latest_period_row(
    rows: pd.DataFrame,
) -> tuple[str | None, dict[str, Any] | None]:
    if rows.empty:
        return None, None
    ordered = rows.copy()
    ordered["_period"] = ordered["report_period"].map(_period_iso)
    ordered = ordered.sort_values("_period")
    row = ordered.iloc[-1].to_dict()
    return str(row.get("_period")), row


def _year_ago_period(period: str) -> str:
    day = date.fromisoformat(_period_iso(period))
    try:
        return day.replace(year=day.year - 1).isoformat()
    except ValueError:  # 2 月 29 日
        return (day.replace(month=2, day=28).replace(year=day.year - 1)).isoformat()


def _statement_rows(
    gatherer: _FactGatherer,
    dataset: ResearchDatasetId,
    ts_code: str,
    *,
    single_row_per_period: bool = True,
) -> pd.DataFrame:
    """先按窗口分区解析；年同比期间缺失时定向补那个分区再解析一次。

    single_row_per_period：利润表/现金流量表/财务指标每个报告期按既有优先
    规则只取一行；主营构成一个报告期本就有多行，不做该归并。
    """

    warehouse = gatherer.warehouse
    partitions = _statement_partitions(warehouse, dataset, gatherer.as_of)
    frames = gatherer.frames(dataset, partitions)
    stock_rows = _stock_rows(frames.get(ts_code, pd.DataFrame()), ts_code)
    rows = (
        _select_comparable_rows(stock_rows)
        if single_row_per_period
        else stock_rows
    )
    period, _ = _latest_period_row(rows)
    if period is not None:
        year_ago = _year_ago_period(period)
        upper = _shanghai_date(gatherer.as_of).isoformat()
        if year_ago <= upper and year_ago not in partitions:
            partitions = _statement_partitions(
                warehouse, dataset, gatherer.as_of, extra_period=year_ago
            )
            gatherer.invalidate(dataset)
            frames = gatherer.frames(dataset, partitions)
            stock_rows = _stock_rows(frames.get(ts_code, pd.DataFrame()), ts_code)
            rows = (
                _select_comparable_rows(stock_rows)
                if single_row_per_period
                else stock_rows
            )
    return rows


def _identity_block(
    gatherer: _FactGatherer, ts_code: str
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    warehouse = gatherer.warehouse
    master_partitions = _partition_values(warehouse, ResearchDatasetId.SECURITY_MASTER)
    frames = gatherer.frames(ResearchDatasetId.SECURITY_MASTER, master_partitions[-1:])
    master_rows = _stock_rows(
        frames.get(ts_code, pd.DataFrame()), ts_code
    )
    master_row: dict[str, Any] | None = None
    if master_rows.empty:
        gatherer.note_gap(
            ResearchDatasetId.SECURITY_MASTER.value,
            "identity_row_missing",
            f"{ts_code} 在证券主表中没有 as_of 可见行",
        )
    else:
        master = master_rows.assign(
            _k=pd.to_datetime(master_rows["valid_from"], errors="coerce", utc=True)
        ).sort_values("_k")
        row = master.iloc[-1].to_dict()
        master_row = {
            "block_id": "identity",
            "kind": "warehouse",
            "dataset": ResearchDatasetId.SECURITY_MASTER.value,
            "title": "证券身份（as_of 可见的最后一行）",
            "available_at": _iso_or_none(row.get("available_at")),
            "locator": f"security_master ts_code={ts_code} valid_from={_iso_or_none(row.get('valid_from'))}",
            "row": _row_subset(
                row,
                ("ts_code", "name", "industry", "market", "exchange",
                 "list_date", "list_status", "valid_from", "snapshot_date"),
            ),
        }

    profile_partitions = _partition_values(
        warehouse, ResearchDatasetId.COMPANY_PROFILE
    )
    profile_frames = gatherer.frames(
        ResearchDatasetId.COMPANY_PROFILE, profile_partitions[-1:]
    )
    profile_rows = _stock_rows(
        profile_frames.get(ts_code, pd.DataFrame()), ts_code
    )
    profile_row: dict[str, Any] | None = None
    if profile_rows.empty:
        gatherer.note_gap(
            ResearchDatasetId.COMPANY_PROFILE.value,
            "company_profile_missing",
            f"{ts_code} 在公司概况中没有 as_of 可见行",
        )
    else:
        profile = profile_rows.assign(
            _k=pd.to_datetime(profile_rows["available_at"], errors="coerce", utc=True)
        ).sort_values("_k")
        row = profile.iloc[-1].to_dict()
        profile_row = {
            "block_id": "profile",
            "kind": "warehouse",
            "dataset": ResearchDatasetId.COMPANY_PROFILE.value,
            "title": "公司概况快照（可能陈旧，须与业务统计日期分开使用）",
            "available_at": _iso_or_none(row.get("available_at")),
            "locator": (
                f"company_profile ts_code={ts_code} "
                f"profile_snapshot_date={_iso_or_none(row.get('profile_snapshot_date'))}"
            ),
            "row": _row_subset(
                row,
                ("ts_code", "com_name", "chairman", "introduction", "main_business",
                 "employees", "profile_snapshot_date", "valid_from"),
            ),
        }
    return master_row, [block for block in (master_row, profile_row) if block]


def _financial_blocks(
    gatherer: _FactGatherer, ts_code: str
) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []

    income_rows = _statement_rows(
        gatherer, ResearchDatasetId.INCOME_STATEMENT, ts_code
    )
    period_by_dataset: dict[str, str] = {}
    income_columns = (
        "report_period", "report_type", "end_type", "ann_date", "f_ann_date",
        "revenue", "total_revenue", "operate_cost", "total_cogs", "oper_cost",
        "total_profit", "n_income", "n_income_attr_p",
    )
    if not income_rows.empty:
        period, row = _latest_period_row(income_rows)
        if row is not None and period is not None:
            period_by_dataset[ResearchDatasetId.INCOME_STATEMENT.value] = period
            blocks.append(
                {
                    "block_id": f"income-{period}",
                    "kind": "warehouse",
                    "dataset": ResearchDatasetId.INCOME_STATEMENT.value,
                    "title": f"利润表 {period}（确定性选择的一行）",
                    "report_period": period,
                    "available_at": _iso_or_none(row.get("available_at")),
                    "locator": (
                        f"income_statement ts_code={ts_code} report_period={period} "
                        f"report_type={row.get('report_type')} end_type={row.get('end_type')}"
                    ),
                    "row": _row_subset(row, income_columns),
                }
            )
    else:
        gatherer.note_gap(
            ResearchDatasetId.INCOME_STATEMENT.value,
            "income_rows_missing",
            f"{ts_code} 没有可见的利润表行",
        )

    year_ago_income: dict[str, Any] | None = None
    if period_by_dataset:
        year_ago = _year_ago_period(period_by_dataset[ResearchDatasetId.INCOME_STATEMENT.value])
        matched = income_rows.loc[
            income_rows["report_period"].map(_period_iso) == year_ago
        ]
        if not matched.empty:
            year_ago_income = matched.sort_values("available_at").iloc[-1].to_dict()

    cash_rows = _statement_rows(gatherer, ResearchDatasetId.CASH_FLOW, ts_code)
    year_ago_cashflow: dict[str, Any] | None = None
    if not cash_rows.empty:
        period, row = _latest_period_row(cash_rows)
        if row is not None and period is not None:
            blocks.append(
                {
                    "block_id": f"cashflow-{period}",
                    "kind": "warehouse",
                    "dataset": ResearchDatasetId.CASH_FLOW.value,
                    "title": f"现金流量表 {period}（确定性选择的一行）",
                    "report_period": period,
                    "available_at": _iso_or_none(row.get("available_at")),
                    "locator": (
                        f"cash_flow ts_code={ts_code} report_period={period} "
                        f"report_type={row.get('report_type')}"
                    ),
                    "row": _row_subset(
                        row,
                        ("report_period", "report_type", "end_type", "ann_date",
                         "f_ann_date", "n_cashflow_act", "c_inf_fr_operate_a",
                         "c_paid_goods_s"),
                    ),
                }
            )
            matched = cash_rows.loc[
                cash_rows["report_period"].map(_period_iso) == _year_ago_period(period)
            ]
            if not matched.empty:
                year_ago_cashflow = matched.sort_values("available_at").iloc[-1].to_dict()
    else:
        gatherer.note_gap(
            ResearchDatasetId.CASH_FLOW.value,
            "cashflow_rows_missing",
            f"{ts_code} 没有可见的现金流量表行",
        )

    indicator_rows = _statement_rows(
        gatherer, ResearchDatasetId.FINANCIAL_INDICATOR, ts_code
    )
    year_ago_indicator: dict[str, Any] | None = None
    if not indicator_rows.empty:
        period, row = _latest_period_row(indicator_rows)
        if row is not None and period is not None:
            blocks.append(
                {
                    "block_id": f"indicator-{period}",
                    "kind": "warehouse",
                    "dataset": ResearchDatasetId.FINANCIAL_INDICATOR.value,
                    "title": f"财务指标 {period}（确定性选择的一行）",
                    "report_period": period,
                    "available_at": _iso_or_none(row.get("available_at")),
                    "locator": (
                        f"financial_indicator ts_code={ts_code} report_period={period} "
                        f"report_type={row.get('report_type')}"
                    ),
                    "row": _row_subset(
                        row,
                        ("report_period", "report_type", "ann_date", "eps", "dt_eps",
                         "profit_dedt", "gross_margin", "netprofit_margin", "roe",
                         "roe_dt", "debt_to_assets"),
                    ),
                }
            )
            matched = indicator_rows.loc[
                indicator_rows["report_period"].map(_period_iso) == _year_ago_period(period)
            ]
            if not matched.empty:
                year_ago_indicator = matched.sort_values("available_at").iloc[-1].to_dict()
    else:
        gatherer.note_gap(
            ResearchDatasetId.FINANCIAL_INDICATOR.value,
            "indicator_rows_missing",
            f"{ts_code} 没有可见的财务指标行（后续修订版本不得替代）",
        )

    business_rows = _statement_rows(
        gatherer, ResearchDatasetId.MAIN_BUSINESS, ts_code,
        single_row_per_period=False,
    )
    if not business_rows.empty:
        period, row = _latest_period_row(business_rows)
        business_block: dict[str, Any] | None = None
        if row is not None and period is not None:
            matched = business_rows.loc[
                business_rows["report_period"].map(_period_iso) == period
            ]
            records = [
                _row_subset(
                    item,
                    ("bz_item", "bz_code", "bz_sales", "bz_profit", "bz_cost",
                     "curr_type", "report_period", "classification", "item_name"),
                )
                for item in matched.to_dict(orient="records")
            ]
            business_block = {
                "block_id": f"main-business-{period}",
                "kind": "warehouse",
                "dataset": ResearchDatasetId.MAIN_BUSINESS.value,
                "title": f"主营构成 {period}（同一报告期全部分类行）",
                "report_period": period,
                "available_at": _iso_or_none(row.get("available_at")),
                "locator": (
                    f"main_business ts_code={ts_code} report_period={period} "
                    f"共{len(records)}行，分类不得混加"
                ),
                "rows": records,
            }
            blocks.append(business_block)
        _attach_business_shares(business_block)
    else:
        gatherer.note_gap(
            ResearchDatasetId.MAIN_BUSINESS.value,
            "main_business_rows_missing",
            f"{ts_code} 没有可见的主营构成行",
        )

    computed = _financial_computed(
        blocks, year_ago_income, year_ago_cashflow, year_ago_indicator
    )
    if computed:
        blocks.append(
            {
                "block_id": "computed",
                "kind": "computed",
                "title": "确定性计算（原值、格式化结果与公式依据）",
                "entries": computed,
            }
        )
    return blocks


def _first_number(block: dict[str, Any] | None, *fields: str) -> float | None:
    if not block:
        return None
    row = block.get("row") or {}
    for field in fields:
        value = row.get(field)
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            return float(value)
    return None


def _financial_computed(
    blocks: list[dict[str, Any]],
    year_ago_income: dict[str, Any] | None,
    year_ago_cashflow: dict[str, Any] | None = None,
    year_ago_indicator: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    income = next(
        (b for b in blocks if b.get("dataset") == "income_statement"), None
    )
    indicator = next(
        (b for b in blocks if b.get("dataset") == "financial_indicator"), None
    )
    cashflow = next(
        (b for b in blocks if b.get("dataset") == "cash_flow"), None
    )
    entries: list[dict[str, Any]] = []

    def money_entry(
        label: str, value: float | None, block_id: str | None, field: str
    ) -> None:
        if value is None:
            return
        entries.append(
            {
                "key": label,
                "value": value,
                "formatted": f"{value / 1e8:.2f}亿元",
                "basis": f"{block_id}.{field} 原值 {value}，按 1亿元=1e8 元换算",
            }
        )

    revenue = _first_number(income, "revenue", "total_revenue")
    # 毛利率只用营业成本（oper_cost/operate_cost）；total_cogs 是营业总成本，
    # 含期间费用，用它算出的是"1-总成本率"而不是毛利率。
    cost = _first_number(income, "oper_cost", "operate_cost")
    cost_basis_field = "oper_cost"
    if cost is None:
        cost = _first_number(income, "total_cogs")
        cost_basis_field = "total_cogs（营业总成本，含期间费用，非毛利率口径）"
    attr_profit = _first_number(income, "n_income_attr_p")
    cash_flow = _first_number(cashflow, "n_cashflow_act")
    money_entry("营业收入", revenue, income.get("block_id") if income else None, "revenue")
    money_entry(
        "归母净利润", attr_profit,
        income.get("block_id") if income else None, "n_income_attr_p",
    )
    money_entry(
        "经营活动现金流净额", cash_flow,
        cashflow.get("block_id") if cashflow else None, "n_cashflow_act",
    )
    if revenue and cost:
        entries.append(
            {
                "key": "毛利率（由收入与营业成本计算）",
                "value": 1.0 - cost / revenue,
                "formatted": f"{(1.0 - cost / revenue) * 100:.1f}%",
                "basis": (
                    f"{income.get('block_id')}：1 - 营业成本 {cost} / 营业收入 {revenue}；"
                    f"成本字段取 {cost_basis_field}，字段含 cost 不自动等于净利润口径"
                ),
            }
        )
    for key, field in (
        ("销售毛利率（来源原值）", "gross_margin"),
        ("销售净利率（来源原值）", "netprofit_margin"),
        ("净资产收益率（来源原值）", "roe"),
        ("扣非净资产收益率（来源原值）", "roe_dt"),
        ("资产负债率（来源原值）", "debt_to_assets"),
    ):
        value = _first_number(indicator, field)
        if value is None:
            continue
        entry: dict[str, Any] = {
            "key": key,
            "value": value,
            "formatted": f"{value:.2f}%",
            "basis": (
                f"{indicator.get('block_id')}.{field} 原值 {value}；"
                "该来源为百分数数值口径（如 8.99 表示 8.99%）"
            ),
        }
        if abs(value) > 1000:
            entry["quality_note"] = (
                "原值超出常规百分比范围，疑似来源异常；引用前必须用利润表原始"
                "收入与成本另行核对，不得把它当作正常比率展示"
            )
        entries.append(entry)
    if year_ago_cashflow is not None and cashflow is not None:
        prior_cash = year_ago_cashflow.get("n_cashflow_act")
        if isinstance(prior_cash, (int, float)) and math.isfinite(float(prior_cash)):
            entries.append(
                {
                    "key": "经营活动现金流净额（上年同期）",
                    "value": float(prior_cash),
                    "formatted": f"{float(prior_cash) / 1e8:.2f}亿元",
                    "basis": (
                        f"cash_flow 上年同期 "
                        f"{_period_iso(year_ago_cashflow.get('report_period'))} 行原值 "
                        f"{prior_cash}；现金流量表为合并口径"
                    ),
                }
            )
            same_shape = year_ago_cashflow.get("report_type") == (
                cashflow.get("row") or {}
            ).get("report_type")
            if (
                same_shape
                and cash_flow is not None
                and float(prior_cash) != 0.0
            ):
                entries.append(
                    {
                        "key": "经营活动现金流净额同比",
                        "value": cash_flow / float(prior_cash) - 1.0,
                        "formatted": f"{(cash_flow / float(prior_cash) - 1.0) * 100:.1f}%",
                        "basis": (
                            f"本期 {cashflow.get('block_id')} 与上年同期同 report_type "
                            f"行相除；上年同期接近零时该比率无意义，须展示原值"
                        ),
                    }
                )
    if year_ago_indicator is not None:
        for key, field in (
            ("销售毛利率（上年同期原值）", "gross_margin"),
            ("销售净利率（上年同期原值）", "netprofit_margin"),
            ("净资产收益率（上年同期原值）", "roe"),
        ):
            value = _first_number({"row": year_ago_indicator}, field)
            if value is None or abs(value) > 1000:
                continue
            entries.append(
                {
                    "key": key,
                    "value": float(value),
                    "formatted": f"{float(value):.2f}%",
                    "basis": (
                        f"financial_indicator 上年同期 "
                        f"{_period_iso(year_ago_indicator.get('report_period'))} 行原值 "
                        f"{value}；百分数数值口径"
                    ),
                }
            )
    if revenue and year_ago_income is not None:
        prior_revenue = year_ago_income.get("revenue")
        prior_attr = year_ago_income.get("n_income_attr_p")
        same_shape = (
            year_ago_income.get("report_type") == (income or {}).get("row", {}).get("report_type")
            and year_ago_income.get("end_type") == (income or {}).get("row", {}).get("end_type")
        )
        if not same_shape:
            entries.append(
                {
                    "key": "同比",
                    "error": "report_type_or_end_type_differs",
                    "basis": "上年同期行的报告类型与本期不同，不生成同比",
                }
            )
        else:
            if isinstance(prior_revenue, (int, float)) and prior_revenue not in (0, 0.0):
                entries.append(
                    {
                        "key": "营业收入同比",
                        "value": revenue / float(prior_revenue) - 1.0,
                        "formatted": f"{(revenue / float(prior_revenue) - 1.0) * 100:.1f}%",
                        "basis": (
                            f"本期 {income.get('block_id')} 与上年同期 "
                            f"{year_ago_income.get('report_period')} 同 report_type/"
                            f"end_type 行相除；合并范围是否可比仍需按报告核对"
                        ),
                    }
                )
            if (
                isinstance(prior_attr, (int, float))
                and prior_attr not in (0, 0.0)
                and attr_profit is not None
            ):
                entries.append(
                    {
                        "key": "归母净利润同比",
                        "value": attr_profit / float(prior_attr) - 1.0,
                        "formatted": f"{(attr_profit / float(prior_attr) - 1.0) * 100:.1f}%",
                        "basis": (
                            f"本期 {income.get('block_id')} 与上年同期 "
                            f"{year_ago_income.get('report_period')} 同 report_type/"
                            f"end_type 行相除；存在合并或重述疑点时不得作为已确认同比"
                        ),
                    }
                )
    return entries


def _attach_business_shares(block: dict[str, Any] | None) -> None:
    """同一分类内的收入占比；分母明确，缺其他/合计行时合计不等于 100%。"""

    if not block or "rows" not in block:
        return
    groups: dict[str, float] = {}
    for row in block["rows"]:
        sales = row.get("bz_sales")
        classification = str(row.get("classification") or "未分类")
        if isinstance(sales, (int, float)) and math.isfinite(float(sales)):
            groups[classification] = groups.get(classification, 0.0) + float(sales)
    shares: dict[str, dict[str, Any]] = {}
    for classification, total in groups.items():
        if total <= 0:
            continue
        for row in block["rows"]:
            if str(row.get("classification") or "未分类") != classification:
                continue
            sales = row.get("bz_sales")
            if isinstance(sales, (int, float)) and float(sales) >= 0:
                shares[f"{classification}|{row.get('bz_item')}"] = {
                    "share": float(sales) / total,
                    "formatted": f"{float(sales) / total * 100:.1f}%",
                    "basis": (
                        f"{classification} 内 bz_sales {sales} / 同分类合计 {total}；"
                        "分类之间不得混加，合计可能小于全部收入"
                    ),
                }
    if shares:
        block["computed_shares"] = shares


def _valuation_block(
    gatherer: _FactGatherer,
    ts_code: str,
    price_date_upper: date,
) -> dict[str, Any] | None:
    partitions = [
        value
        for value in _partition_values(gatherer.warehouse, ResearchDatasetId.DAILY_BASIC)
        if value <= price_date_upper.isoformat()
    ][-3:]
    if not partitions:
        gatherer.note_gap(
            ResearchDatasetId.DAILY_BASIC.value,
            "valuation_partitions_missing",
            f"截至 {price_date_upper.isoformat()} 没有每日指标分区",
        )
        return None
    frames = gatherer.frames(ResearchDatasetId.DAILY_BASIC, partitions)
    rows = _stock_rows(frames.get(ts_code, pd.DataFrame()), ts_code)
    if rows.empty:
        gatherer.note_gap(
            ResearchDatasetId.DAILY_BASIC.value,
            "valuation_row_missing",
            f"{ts_code} 在截至 {price_date_upper.isoformat()} 的每日指标中无可见行",
        )
        return None
    ordered = rows.copy()
    ordered["_day"] = ordered["trade_date"].map(_period_iso)
    ordered = ordered.sort_values("_day")
    row = ordered.iloc[-1].to_dict()
    trade_day = _period_iso(row.get("trade_date"))
    block = {
        "block_id": f"valuation-{trade_day}",
        "kind": "warehouse",
        "dataset": ResearchDatasetId.DAILY_BASIC.value,
        "title": (
            f"估值与市值参考（交易日 {trade_day}，"
            "不晚于形成日且在 as_of 可见）"
        ),
        "report_period": None,
        "available_at": _iso_or_none(row.get("available_at")),
        "locator": (
            f"daily_basic ts_code={ts_code} trade_date={trade_day}"
        ),
        "row": _row_subset(
            row,
            ("trade_date", "close", "pe", "pe_ttm", "pb", "ps_ttm", "dv_ratio",
             "total_mv", "circ_mv", "turnover_rate_f"),
        ),
    }
    block["row"]["trade_date"] = trade_day
    total_mv = block["row"].get("total_mv")
    computed = []
    if isinstance(total_mv, (int, float)) and math.isfinite(float(total_mv)):
        computed.append(
            {
                "key": "总市值",
                "value": float(total_mv),
                "formatted": f"{float(total_mv) / 1e4:.0f}亿元",
                "basis": (
                    f"{block['block_id']}.total_mv 原值 {total_mv}（万元口径按来源），"
                    "展示口径须对照来源单位"
                ),
            }
        )
    if computed:
        block["computed_entries"] = computed
    return block


def _announcement_block(
    gatherer: _FactGatherer, ts_code: str
) -> dict[str, Any] | None:
    months: list[str] = []
    cursor = _shanghai_date(gatherer.as_of)
    for offset in range(ANNOUNCEMENT_MONTH_COUNT):
        months.append((cursor - timedelta(days=31 * offset)).strftime("%Y-%m"))
    existing = set(_partition_values(gatherer.warehouse, ResearchDatasetId.ANNOUNCEMENT))
    partitions = sorted(month for month in months if month in existing)
    if not partitions:
        gatherer.note_gap(
            ResearchDatasetId.ANNOUNCEMENT.value,
            "announcement_partitions_missing",
            f"近 {ANNOUNCEMENT_MONTH_COUNT} 个月没有公告分区",
        )
        return None
    frames = gatherer.frames(ResearchDatasetId.ANNOUNCEMENT, partitions)
    rows = _stock_rows(frames.get(ts_code, pd.DataFrame()), ts_code)
    if rows.empty:
        gatherer.note_gap(
            ResearchDatasetId.ANNOUNCEMENT.value,
            "announcement_rows_missing",
            f"{ts_code} 在近 {ANNOUNCEMENT_MONTH_COUNT} 个月公告中没有可见行",
        )
        return None
    ordered = rows.copy()
    ordered["_time"] = ordered["announcement_time"].astype(str)
    ordered = ordered.sort_values("_time", ascending=False).head(ANNOUNCEMENT_ROW_LIMIT)
    records = [
        _row_subset(
            row,
            ("announcement_id", "announcement_time", "available_at", "title",
             "url", "candidate_event_types"),
        )
        for row in ordered.to_dict(orient="records")
    ]
    return {
        "block_id": "announcements",
        "kind": "warehouse",
        "dataset": ResearchDatasetId.ANNOUNCEMENT.value,
        "title": (
            f"公告元数据（最近 {len(records)} 条 as_of 可见；"
            "正文未入库，重要条款需按披露链读取原文）"
        ),
        "available_at": None,
        "locator": f"announcement ts_code={ts_code} 近{ANNOUNCEMENT_MONTH_COUNT}个月分区",
        "rows": records,
    }


def _stock_facts(
    gatherer: _FactGatherer,
    ts_code: str,
    name_hint: str,
    price_date_upper: date,
) -> dict[str, Any]:
    identity, identity_blocks = _identity_block(gatherer, ts_code)
    blocks = identity_blocks + _financial_blocks(gatherer, ts_code)
    valuation = _valuation_block(gatherer, ts_code, price_date_upper)
    if valuation is not None:
        blocks.append(valuation)
    announcements = _announcement_block(gatherer, ts_code)
    if announcements is not None:
        blocks.append(announcements)
    name = None
    if identity is not None:
        name = (identity.get("row") or {}).get("name")
    return {
        "ts_code": ts_code,
        "name": name or name_hint,
        "blocks": blocks,
        "gaps": list(gatherer.gaps),
    }


def _context_header(
    *,
    formation_date: str | None,
    action_date: str | None,
    as_of: str,
    mode: Literal["formal", "single_stock"],
    trace_version: str | None,
    trace_path: str | None,
) -> dict[str, Any]:
    return {
        "facts_file_version": FACTS_FILE_VERSION,
        "mode": mode,
        "formation_date": formation_date,
        "action_date": action_date,
        "as_of": as_of,
        "trace_version": trace_version,
        "trace_path": trace_path,
        "generated_at": datetime.now(SHANGHAI).isoformat(timespec="seconds"),
        "note": (
            "facts-file 是本轮写作的临时输入，不是第二份正文或永久证据库；"
            "正式顺序与身份以 trace 归档为准。"
        ),
    }


def prepare_formal_context(
    *,
    formation_date: str,
    action_date: str | None = None,
    as_of: str | None = None,
    include_legacy: bool = False,
    project_root: Path | None = None,
    warehouse_root: Path | None = None,
    intro_root: Path | None = None,
) -> dict[str, Any]:
    """正式范围备料：只读 trace 与事实仓；不写研究、不写介绍。

    include_legacy 仅用于用户明确要求补写历史正式类别
    （legacy_v1_not_rewritten）的介绍；日常自动范围只处理 confirmed_active。
    """

    from stock_analyzer.config import AppConfig

    config = AppConfig.load()
    root = Path(project_root) if project_root is not None else config.project_root
    selection_dir = default_selection_dir(root)
    intro_root = Path(intro_root) if intro_root is not None else default_intro_root(root)
    trace = load_formal_trace(selection_dir, formation_date)
    context = trace_context(trace)
    if action_date is not None and action_date != context["action_date"]:
        raise ValueError(
            f"action_date {action_date} does not match the archived trace "
            f"{context['action_date']}"
        )
    if as_of is not None and not _same_instant(_parse_as_of(as_of, "--as-of"), context["as_of"]):
        raise ValueError(
            f"as_of {as_of} does not match the archived trace {context['as_of']}"
        )
    if not research_completed(trace):
        raise ValueError(
            "formal research is not complete; introductions need a frozen selection"
        )
    as_of_dt = _parse_as_of(context["as_of"], "trace as_of")

    scope: list[dict[str, Any]] = []
    allowed_classes = (
        PRODUCTION_OUTPUT_CLASSES | {"legacy_v1_not_rewritten"}
        if include_legacy
        else PRODUCTION_OUTPUT_CLASSES
    )
    for candidate in selected_candidates(trace):
        output_class = candidate_class(trace, candidate)
        if output_class not in allowed_classes:
            continue
        ts_code = str(candidate.get("ts_code") or "")
        if len(ts_code) != 9:
            continue
        path = intro_path(
            intro_root, context["action_date"], ts_code
        )
        status = "missing"
        if path.is_file():
            try:
                intro = read_introduction_file(path)
                status = (
                    "reusable"
                    if introduction_matches_identity(
                        intro,
                        ts_code=ts_code,
                        formation_date=context["formation_date"],
                        action_date=context["action_date"],
                        as_of=context["as_of"],
                    )
                    else "identity_conflict"
                )
            except ValueError:
                status = "file_unreadable"
        scope.append(
            {
                "ts_code": ts_code,
                "name": str(candidate.get("name") or ts_code),
                "output_class": output_class,
                "intro_status": status,
                "intro_path": str(path),
            }
        )

    stocks: dict[str, Any] = {}
    warehouse_gaps: list[dict[str, Any]] = []
    used_partitions: dict[str, list[str]] = {}
    missing_codes = [item["ts_code"] for item in scope if item["intro_status"] == "missing"]
    if missing_codes:
        wh_root = (
            Path(warehouse_root)
            if warehouse_root is not None
            else config.local_warehouse_dir
        )
        query = None
        open_gap = None
        try:
            warehouse = ResearchWarehouse(wh_root, read_only=True)
            query = ResearchQuery(warehouse)
        except _LOCAL_READ_ERRORS as error:
            # 正式身份已在上面核对。保留真实范围供官方补证，不恢复事实仓。
            open_gap = {
                "dataset": "warehouse",
                "gap": "warehouse_unavailable",
                "detail": str(error),
            }
            warehouse_gaps.append(open_gap)
        for item in scope:
            if item["intro_status"] != "missing":
                continue
            code = item["ts_code"]
            if open_gap is not None:
                stocks[code] = {
                    "ts_code": code, "name": item["name"],
                    "blocks": [], "gaps": [dict(open_gap)],
                }
                continue
            assert query is not None
            gatherer = _FactGatherer(query, as_of_dt, [code])
            try:
                stocks[code] = _stock_facts(
                    gatherer, code, item["name"],
                    price_date_upper=_shanghai_date(as_of_dt),
                )
            except _LOCAL_READ_ERRORS as error:
                gatherer.note_gap("warehouse", "query_failed", str(error))
                stocks[code] = {
                    "ts_code": code, "name": item["name"], "blocks": [],
                }
            stocks[code]["gaps"] = list(gatherer.gaps)
            warehouse_gaps.extend(gatherer.gaps)
            for dataset, partitions in gatherer.used_partitions.items():
                used_partitions[dataset] = sorted(
                    set(used_partitions.get(dataset, [])) | set(partitions)
                )

    result = {
        "context": _context_header(
            formation_date=context["formation_date"],
            action_date=context["action_date"],
            as_of=context["as_of"],
            mode="formal",
            trace_version=context["trace_version"],
            trace_path=str(selection_dir / f"research-trace-{context['formation_date']}.json"),
        ),
        "scope": scope,
        "stocks": stocks,
        "warehouse_gaps": list(
            {json.dumps(g, ensure_ascii=False): g for g in warehouse_gaps}.values()
        ),
        "used_partitions": used_partitions,
    }
    return result


def prepare_single_stock(
    *,
    code: str,
    as_of: str,
    price_date: str | None = None,
    project_root: Path | None = None,
    warehouse_root: Path | None = None,
) -> dict[str, Any]:
    """用户指定单股的只读备料；不要求正式推荐，不进入生产 record。"""

    from stock_analyzer.config import AppConfig

    if len(code) != 9 or code[7:] not in {"SH", "SZ"} or not code[:6].isdigit():
        raise ValueError(
            "--code must be a 9-character ts_code like 600583.SH"
        )
    as_of_dt = _parse_as_of(as_of, "--as-of")
    upper = (
        date.fromisoformat(price_date)
        if price_date is not None
        else _shanghai_date(as_of_dt)
    )
    if price_date is not None and date.fromisoformat(price_date) > _shanghai_date(as_of_dt):
        raise ValueError("--price-date must not be after the as_of Shanghai date")
    config = AppConfig.load()
    wh_root = (
        Path(warehouse_root)
        if warehouse_root is not None
        else config.local_warehouse_dir
    )
    warehouse = ResearchWarehouse(wh_root, read_only=True)
    query = ResearchQuery(warehouse)
    ts_code = code.upper()
    gatherer = _FactGatherer(query, as_of_dt, [ts_code])
    facts = _stock_facts(gatherer, ts_code, ts_code, price_date_upper=upper)
    return {
        "context": _context_header(
            formation_date=None,
            action_date=None,
            as_of=as_of_dt.isoformat(),
            mode="single_stock",
            trace_version=None,
            trace_path=None,
        ),
        "scope": [
            {
                "ts_code": ts_code,
                "name": facts["name"],
                "output_class": None,
                "intro_status": "single_stock",
                "intro_path": None,
            }
        ],
        "stocks": {ts_code: facts},
        "warehouse_gaps": list(gatherer.gaps),
        "used_partitions": gatherer.used_partitions,
    }


# ---------------------------------------------------------------------------
# record：单篇保存（先核对，再原子写入）
# ---------------------------------------------------------------------------


def _value_matches(left: Any, right: Any) -> bool:
    if isinstance(left, (int, float)) and not isinstance(left, bool) and isinstance(
        right, (int, float)
    ) and not isinstance(right, bool):
        scale = max(1.0, abs(float(left)), abs(float(right)))
        return abs(float(left) - float(right)) <= 1e-9 * scale
    return str(left) == str(right)


def _cited_values_present(source: IntroSource, block: dict[str, Any]) -> bool:
    values = source.values or {}
    if not values:
        return True
    candidates: list[dict[str, Any]] = []
    if isinstance(block.get("row"), dict):
        candidates.append(block["row"])
    candidates.extend(block.get("rows") or [])
    extras = block.get("extra_rows")
    if isinstance(extras, list):
        candidates.extend(extras)
    for key, cited in values.items():
        if any(
            field in row and _value_matches(row[field], cited)
            for row in candidates
            for field in (key,)
        ):
            continue
        return False
    return True


def record_introduction(
    *,
    intro_file: Path,
    facts_file: Path,
    intro_root: Path | None = None,
    project_root: Path | None = None,
) -> dict[str, Any]:
    """校验单篇介绍并保存；已有有效同身份文件直接复用，不覆盖冲突或损坏文件。"""

    from stock_analyzer.config import AppConfig

    config = AppConfig.load()
    root = Path(project_root) if project_root is not None else config.project_root
    intro_root = Path(intro_root) if intro_root is not None else default_intro_root(root)
    intro = read_introduction_file(Path(intro_file))
    facts = _load_json(Path(facts_file))
    context = facts.get("context") or {}
    if context.get("facts_file_version") != FACTS_FILE_VERSION:
        raise ValueError(
            "facts-file version mismatch; record only accepts the current "
            "facts-file produced by this round's prepare"
        )
    if context.get("mode") != "formal":
        raise ValueError(
            "single-stock facts cannot pass production record; formal "
            "introductions require a frozen selection"
        )
    formation = str(context.get("formation_date") or "")
    action = str(context.get("action_date") or "")
    as_of = str(context.get("as_of") or "")
    if not formation or not action or not as_of:
        raise ValueError("facts-file is missing its formal context")
    if not introduction_matches_identity(
        intro,
        ts_code=intro.ts_code,
        formation_date=formation,
        action_date=action,
        as_of=as_of,
    ):
        raise ValueError(
            "introduction identity does not match this round's facts-file; "
            "a different context needs its own prepare"
        )

    selection_dir = default_selection_dir(root)
    trace = load_formal_trace(selection_dir, formation)
    trace_values = trace_context(trace)
    if (
        trace_values["action_date"] != action
        or not _same_instant(_parse_as_of(trace_values["as_of"], "trace as_of"), as_of)
    ):
        raise ValueError("facts-file context contradicts the archived trace")
    if not research_completed(trace):
        raise ValueError("formal research is not complete in the archived trace")
    candidate = next(
        (
            item
            for item in selected_candidates(trace)
            if str(item.get("ts_code") or "") == intro.ts_code
        ),
        None,
    )
    if candidate is None:
        raise ValueError(
            f"{intro.ts_code} is not a selected candidate in the archived trace"
        )
    output_class = candidate_class(trace, candidate)
    if output_class not in RECORDABLE_OUTPUT_CLASSES:
        raise ValueError(
            f"{intro.ts_code} has output class {output_class}; conditional and "
            "informal candidates cannot pass production record"
        )

    scope_entry = next(
        (
            item
            for item in facts.get("scope") or []
            if item.get("ts_code") == intro.ts_code
        ),
        None,
    )
    stock_facts = (facts.get("stocks") or {}).get(intro.ts_code) or {}
    blocks_by_id = {
        str(block.get("block_id")): block for block in stock_facts.get("blocks") or []
    }
    for source in intro.sources:
        if source.kind != "warehouse":
            continue
        block = blocks_by_id.get(str(source.block_id))
        if block is None or block.get("dataset") != source.dataset:
            raise ValueError(
                f"warehouse source {source.id} does not match this round's "
                f"facts-file blocks ({source.block_id}/{source.dataset})"
            )
        if source.available_at is not None and block.get("available_at") is not None:
            if not _same_instant(
                source.available_at, str(block["available_at"])
            ):
                raise ValueError(
                    f"warehouse source {source.id} available_at contradicts the "
                    "facts-file row"
                )
        if not str(source.locator or "").strip():
            raise ValueError(f"warehouse source {source.id} needs a locator")
        if not _cited_values_present(source, block):
            raise ValueError(
                f"warehouse source {source.id} cites values that are not in the "
                "facts-file block; only cited key values from the prepared rows "
                "can pass"
            )

    target = intro_path(intro_root, action, intro.ts_code)
    if target.is_file():
        try:
            existing = read_introduction_file(target)
            if introduction_matches_identity(
                existing,
                ts_code=intro.ts_code,
                formation_date=formation,
                action_date=action,
                as_of=as_of,
            ):
                return {
                    "status": "already_exists",
                    "path": str(target),
                    "ts_code": intro.ts_code,
                    "action_date": action,
                    "note": "已有有效同身份介绍，直接复用，不更新 generated_at 或正文",
                }
            raise ValueError(
                f"existing file has a conflicting identity: {target}; "
                "record will not overwrite it automatically"
            )
        except ValidationError as error:
            raise ValueError(
                f"existing file is unreadable as an introduction: {target} "
                f"({error}); record will not overwrite it automatically"
            ) from error

    payload = intro.model_dump(mode="json")
    _atomic_write_json(target, payload)
    return {
        "status": "recorded",
        "path": str(target),
        "ts_code": intro.ts_code,
        "action_date": action,
        "output_class": output_class,
        "scope_status": (scope_entry or {}).get("intro_status"),
    }


# ---------------------------------------------------------------------------
# 展示读取：按 (ts_code, action_date) 身份核对后加载
# ---------------------------------------------------------------------------


def load_introductions_for_display(
    selection_dir: Path,
    intro_root: Path,
    identities: Sequence[tuple[str, str, str | None]],
) -> dict[tuple[str, str], dict[str, Any]]:
    """按原推荐身份读取介绍；无法证明身份匹配时返回缺失，不取同代码最新一篇。

    identities 每项为 (ts_code, action_date, formation_date)。trace 只读原始
    JSON，不强制 V4 模型解析，历史 V1 记录按原身份可用。
    """

    result: dict[tuple[str, str], dict[str, Any]] = {}
    trace_cache: dict[str, dict[str, Any] | None] = {}
    for ts_code, action_date, formation_date in identities:
        if not ts_code or not action_date or not formation_date:
            continue
        if formation_date not in trace_cache:
            try:
                trace = load_formal_trace(selection_dir, formation_date)
                values = trace_context(trace)
                if values["action_date"] != action_date or not research_completed(trace):
                    trace_cache[formation_date] = None
                else:
                    trace_cache[formation_date] = trace
            except ValueError:
                trace_cache[formation_date] = None
        trace = trace_cache[formation_date]
        if trace is None:
            continue
        candidate = next(
            (
                item
                for item in selected_candidates(trace)
                if str(item.get("ts_code") or "") == ts_code
            ),
            None,
        )
        if candidate is None or candidate_class(trace, candidate) not in (
            DISPLAY_OUTPUT_CLASSES
        ):
            continue
        path = intro_path(intro_root, action_date, ts_code)
        if not path.is_file():
            continue
        try:
            intro = read_introduction_file(path)
        except ValueError:
            continue
        if not introduction_matches_identity(
            intro,
            ts_code=ts_code,
            formation_date=formation_date,
            action_date=action_date,
            as_of=str(trace.get("as_of") or ""),
        ):
            continue
        result[(ts_code, action_date)] = intro.model_dump(mode="json")
    return result


def needs_second_sync(*, first_sync_ok: bool, new_articles_saved: bool) -> bool:
    """收尾第二次同步条件：新增保存了介绍，或第一次同步失败。"""

    return (not first_sync_ok) or bool(new_articles_saved)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m stock_analyzer.ops.company_introduction",
        description="公司介绍：prepare 只读备料，record 单篇保存",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare_parser = subparsers.add_parser(
        "prepare",
        help="正式范围（或用户指定单股）的只读事实备料，输出 facts-file JSON",
    )
    prepare_parser.add_argument("--formation-date", help="正式 trace 的形成日")
    prepare_parser.add_argument("--action-date", help="必须与归档 trace 一致")
    prepare_parser.add_argument("--as-of", help="必须与归档 trace 一致（带时区）")
    prepare_parser.add_argument(
        "--include-legacy",
        action="store_true",
        help="仅限用户明确要求补写历史正式类别（legacy_v1_not_rewritten）时使用",
    )
    prepare_parser.add_argument("--code", help="单股入口：ts_code，如 600583.SH")
    prepare_parser.add_argument("--price-date", help="单股估值参考日上界（YYYY-MM-DD）")
    prepare_parser.add_argument("--output", help="facts-file 输出路径（缺省打印到标准输出）")
    prepare_parser.add_argument("--project-root", default=None)
    prepare_parser.add_argument("--warehouse-root", default=None)
    prepare_parser.add_argument("--intro-root", default=None)
    record_parser = subparsers.add_parser(
        "record", help="校验 AI 撰写的单篇介绍并保存到附属目录"
    )
    record_parser.add_argument("--intro-file", required=True)
    record_parser.add_argument("--facts-file", required=True)
    record_parser.add_argument("--project-root", default=None)
    record_parser.add_argument("--intro-root", default=None)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            if args.code:
                if args.formation_date or args.action_date:
                    parser.error(
                        "single-stock prepare takes --code/--as-of and must not "
                        "mix with --formation-date/--action-date"
                    )
                result = prepare_single_stock(
                    code=args.code,
                    as_of=args.as_of or "",
                    price_date=args.price_date,
                    project_root=(
                        Path(args.project_root) if args.project_root else None
                    ),
                    warehouse_root=(
                        Path(args.warehouse_root) if args.warehouse_root else None
                    ),
                )
            else:
                if not (args.formation_date and args.as_of):
                    parser.error(
                        "formal prepare requires --formation-date and --as-of "
                        "(--action-date is checked against the trace when given)"
                    )
                result = prepare_formal_context(
                    formation_date=args.formation_date,
                    action_date=args.action_date,
                    as_of=args.as_of,
                    include_legacy=args.include_legacy,
                    project_root=(
                        Path(args.project_root) if args.project_root else None
                    ),
                    warehouse_root=(
                        Path(args.warehouse_root) if args.warehouse_root else None
                    ),
                    intro_root=Path(args.intro_root) if args.intro_root else None,
                )
            rendered = json.dumps(result, ensure_ascii=False, indent=2)
            if args.output:
                _atomic_write_json(Path(args.output), result)
                print(f"facts_file={args.output}")
            else:
                print(rendered)
        else:
            summary = record_introduction(
                intro_file=Path(args.intro_file),
                facts_file=Path(args.facts_file),
                intro_root=Path(args.intro_root) if args.intro_root else None,
                project_root=(
                    Path(args.project_root) if args.project_root else None
                ),
            )
            print(json.dumps(summary, ensure_ascii=False))
    except (ValueError, FileNotFoundError, PermissionError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
