from __future__ import annotations

import fcntl
import json
import re
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import partial
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
import pandas as pd

from stock_analyzer.config import AppConfig
from stock_analyzer.data.classification_backfill import ClassificationBackfillService
from stock_analyzer.data.cninfo_research_client import CninfoResearchClient
from stock_analyzer.data.event_backfill import EventBackfillService
from stock_analyzer.data.exchange_announcement_client import (
    ExchangeAnnouncementClient,
)
from stock_analyzer.data.fundamental_backfill import FundamentalBackfillService
from stock_analyzer.data.research_backfill import BackfillSummary, ResearchBackfillService
from stock_analyzer.data.research_contracts import ResearchDatasetId
from stock_analyzer.data.trading_structure_backfill import TradingStructureBackfillService
from stock_analyzer.data.tushare_research_client import TushareResearchClient
from stock_analyzer.ops.research_features import run_research_features
from stock_analyzer.storage.research_schema import connect_research_warehouse
from stock_analyzer.storage.research_gap_registry import ResearchGapRegistry
from stock_analyzer.storage.research_warehouse import ResearchWarehouse


BROAD_INDEX_CODES = (
    "000001.SH",
    "399001.SZ",
    "399006.SZ",
    "000688.SH",
    "000300.SH",
    "000905.SH",
    "000852.SH",
    "899050.BJ",
)
SHANGHAI = ZoneInfo("Asia/Shanghai")

_FINANCIAL_REPORT_TITLE = re.compile(
    r"\d{4}年(?:年度|半年度|第一季度|第三季度)报告"
    r"(?:摘要)?(?:[（(](?:修订|更正|更新)[^）)]*[）)])?$"
)


@dataclass
class ResearchDataRuntime:
    config: AppConfig
    pro: Any
    tushare_module: Any
    tushare: TushareResearchClient
    cninfo: CninfoResearchClient
    warehouse: ResearchWarehouse
    http_client: httpx.Client
    exchange_announcements: ExchangeAnnouncementClient | None = None

    def minute_fetcher(self, **kwargs: Any) -> pd.DataFrame:
        frame = self.pro.stk_mins(
            ts_code=kwargs["ts_code"],
            start_date=kwargs["start_date"],
            end_date=kwargs["end_date"],
            freq=kwargs["freq"],
        )
        if isinstance(frame, pd.DataFrame) and not frame.empty:
            frame = frame.copy()
            if "trade_date" not in frame.columns and "trade_time" in frame.columns:
                frame["trade_date"] = (
                    frame["trade_time"]
                    .astype(str)
                    .str.slice(0, 10)
                    .str.replace("-", "", regex=False)
                )
        return frame


def build_research_data_runtime(config: AppConfig) -> ResearchDataRuntime:
    token = config.resolve_tushare_token()
    if not token:
        raise RuntimeError("Tushare token missing")
    import tushare as ts

    pro = ts.pro_api(token)
    http_client = httpx.Client(
        headers={
            "User-Agent": "Mozilla/5.0 stock-research-data/1.0",
            "Referer": "https://www.cninfo.com.cn/",
        }
    )
    return ResearchDataRuntime(
        config=config,
        pro=pro,
        tushare_module=ts,
        tushare=TushareResearchClient(pro),
        cninfo=CninfoResearchClient(
            http_client,
            base_url=config.cninfo_base_url,
            timeout_seconds=config.cninfo_timeout_seconds,
            max_retries=config.cninfo_max_retries,
        ),
        warehouse=ResearchWarehouse(config.local_warehouse_dir),
        http_client=http_client,
        exchange_announcements=ExchangeAnnouncementClient(http_client),
    )


def run_research_backfill(
    runtime: ResearchDataRuntime,
    *,
    start: date,
    through: date,
    scope: str,
    resume: bool,
) -> tuple[BackfillSummary, ...]:
    valid = {
        "all",
        "market-core",
        "classifications",
        "fundamentals",
        "events",
        "trading-structure",
    }
    if scope not in valid:
        raise ValueError(f"unsupported backfill scope: {scope}")
    summaries: list[BackfillSummary] = []
    market = ResearchBackfillService(runtime.tushare, runtime.warehouse)
    if scope in {"all", "market-core"}:
        summaries.append(
            market.backfill_market_core(start=start, through=through, resume=resume)
        )
    if scope in {"all", "classifications"}:
        summaries.append(
            ClassificationBackfillService(
                runtime.tushare, runtime.warehouse
            ).backfill(start=start, through=through, resume=resume)
        )
    if scope in {"all", "fundamentals"}:
        summaries.append(
            FundamentalBackfillService(
                runtime.tushare, runtime.warehouse
            ).backfill(start=start, through=through, resume=resume)
        )
    trading_dates = _trading_dates(runtime.warehouse, start, through)
    if scope in {"all", "events"}:
        summaries.append(
            EventBackfillService(
                runtime.tushare,
                runtime.cninfo,
                runtime.warehouse,
                exchange_announcements=runtime.exchange_announcements,
            ).backfill(
                start=start,
                through=through,
                trading_dates=trading_dates,
                resume=resume,
            )
        )
    if scope in {"all", "trading-structure"}:
        candidates = select_minute_candidate_scope(runtime.warehouse, through)
        summaries.append(
            TradingStructureBackfillService(
                runtime.tushare,
                runtime.warehouse,
                minute_fetcher=runtime.minute_fetcher,
            ).backfill(
                trading_dates=trading_dates,
                through=through,
                candidate_codes=candidates,
                index_codes=BROAD_INDEX_CODES,
                resume=resume,
            )
        )
    reconcile_research_gaps(runtime.warehouse)
    return tuple(summaries)


def reconcile_research_gaps(warehouse: ResearchWarehouse) -> int:
    with connect_research_warehouse(
        warehouse.duckdb_path, read_only=True
    ) as connection:
        rows = connection.execute(
            """
            select dataset_id, partition_value, scope_key,
                   source_name, source_endpoint
            from research_data_gaps
            where status in (
                'legitimate_empty', 'waiting_upstream', 'permission_denied',
                'failed', 'unclassified_missing'
            )
            """
        ).fetchall()
    registry = ResearchGapRegistry(warehouse.duckdb_path)
    resolved = 0
    for dataset_id, partition_value, scope_key, source_name, source_endpoint in rows:
        if not source_name or not source_endpoint:
            continue
        frame = warehouse.read_current(
            ResearchDatasetId(dataset_id), partition_value=str(partition_value)
        )
        if frame.empty or not {"source_name", "source_endpoint"} <= set(frame):
            continue
        matched = frame[
            (frame["source_name"].astype(str) == str(source_name))
            & (frame["source_endpoint"].astype(str) == str(source_endpoint))
        ]
        if str(scope_key or ""):
            scope_column = (
                "instrument_code"
                if dataset_id == ResearchDatasetId.MINUTE_BAR.value
                else "ts_code"
            )
            if scope_column not in matched:
                continue
            matched = matched[
                matched[scope_column].astype(str) == str(scope_key)
            ]
        if matched.empty:
            continue
        resolved += registry.resolve_from_success(
            ResearchDatasetId(dataset_id),
            str(partition_value),
            scope_key=str(scope_key or ""),
            source_name=str(source_name),
            source_endpoint=str(source_endpoint),
        )
    return resolved


def run_research_stage(
    runtime: ResearchDataRuntime,
    *,
    stage: str,
    data_date: date,
    already_locked: bool = False,
) -> tuple[BackfillSummary, ...]:
    warehouse = getattr(runtime, "warehouse", None)
    if warehouse is None or not hasattr(warehouse, "duckdb_path"):
        return _run_research_stage_impl(runtime, stage=stage, data_date=data_date)
    if already_locked:
        return _run_research_stage_locked(
            runtime, stage=stage, data_date=data_date
        )
    with research_job_lock(warehouse.root):
        return _run_research_stage_locked(
            runtime, stage=stage, data_date=data_date
        )


def _run_research_stage_locked(
    runtime: ResearchDataRuntime,
    *,
    stage: str,
    data_date: date,
) -> tuple[BackfillSummary, ...]:
    warehouse = runtime.warehouse
    interrupt_orphan_runs(warehouse)
    run_id = _begin_stage_run(warehouse, stage, data_date)
    try:
        summaries = _run_research_stage_impl(
            runtime, stage=stage, data_date=data_date
        )
    except Exception as exc:
        _finish_failed_stage_run(warehouse, run_id, exc)
        raise
    _finish_stage_run(warehouse, run_id, summaries)
    return summaries


def _run_research_stage_impl(
    runtime: ResearchDataRuntime,
    *,
    stage: str,
    data_date: date,
) -> tuple[BackfillSummary, ...]:
    if stage == "close":
        calendar = runtime.tushare.fetch_trade_calendar(data_date, data_date)
        is_open = bool(
            not calendar.empty
            and calendar.loc[
                calendar["cal_date"] == data_date, "is_open"
            ].astype(bool).any()
        )
        if not is_open:
            summary = BackfillSummary(
                scope="market-core",
                start=data_date,
                through=data_date,
                skipped=1,
            )
            return (summary,)
        return run_research_backfill(
            runtime,
            start=data_date,
            through=data_date,
            scope="market-core",
            resume=False,
        )
    trading_dates = _trading_dates(
        runtime.warehouse, data_date - timedelta(days=10), data_date
    )
    if stage == "evening":
        summaries: list[BackfillSummary] = []
        try:
            summaries.append(
                EventBackfillService(
                    runtime.tushare,
                    runtime.cninfo,
                    runtime.warehouse,
                    exchange_announcements=getattr(
                        runtime, "exchange_announcements", None
                    ),
                ).backfill(
                    start=data_date,
                    through=data_date,
                    trading_dates=(
                        (data_date,) if data_date in trading_dates else ()
                    ),
                    resume=False,
                    fallback_to_exchanges=True,
                )
            )
        except Exception as exc:
            summaries.append(_failed_step_summary("events", data_date, exc))

        classifications = ClassificationBackfillService(
            runtime.tushare, runtime.warehouse
        )
        for dataset, refresh_memberships in (
            (ResearchDatasetId.INDUSTRY_DAILY_PROXY, False),
            (ResearchDatasetId.THEME_DAILY, True),
        ):
            try:
                summaries.append(
                    classifications.refresh_daily(
                        data_date,
                        datasets=(dataset,),
                        refresh_memberships=refresh_memberships,
                    )
                )
            except Exception as exc:
                summaries.append(
                    _failed_step_summary(dataset.value, data_date, exc)
                )

        try:
            announcements = runtime.warehouse.read_current(
                ResearchDatasetId.ANNOUNCEMENT
            )
            affected_codes = select_fundamental_refresh_codes(
                announcements,
                data_date,
            )
            if affected_codes:
                summaries.append(
                    FundamentalBackfillService(
                        runtime.tushare, runtime.warehouse
                    ).backfill(
                        start=data_date - timedelta(days=5 * 366),
                        through=data_date,
                        codes=affected_codes,
                        resume=False,
                    )
                )
        except Exception as exc:
            summaries.append(
                _failed_step_summary("fundamental-refresh", data_date, exc)
            )
        return _finalize_stage_with_research_features(
            runtime, summaries, data_date=data_date
        )
    if stage == "next-morning":
        summaries = []
        try:
            summaries.append(
                EventBackfillService(
                    runtime.tushare,
                    runtime.cninfo,
                    runtime.warehouse,
                    exchange_announcements=getattr(
                        runtime, "exchange_announcements", None
                    ),
                ).backfill_announcements(
                    start=data_date,
                    through=_shanghai_today(),
                    resume=False,
                    fallback_to_exchanges=True,
                )
            )
        except Exception as exc:
            summaries.append(
                _failed_step_summary("announcements", data_date, exc)
            )

        classifications = ClassificationBackfillService(
            runtime.tushare, runtime.warehouse
        )
        for dataset in (
            ResearchDatasetId.INDUSTRY_DAILY_PROXY,
            ResearchDatasetId.THEME_DAILY,
        ):
            try:
                if _daily_partition_passed(
                    runtime.warehouse, dataset, data_date
                ):
                    continue
                summaries.append(
                    classifications.refresh_daily(
                        data_date,
                        datasets=(dataset,),
                        refresh_memberships=False,
                    )
                )
            except Exception as exc:
                summaries.append(
                    _failed_step_summary(dataset.value, data_date, exc)
                )

        try:
            candidates = select_minute_candidate_scope(
                runtime.warehouse, data_date
            )
            summaries.append(
                TradingStructureBackfillService(
                    runtime.tushare,
                    runtime.warehouse,
                    minute_fetcher=runtime.minute_fetcher,
                ).backfill(
                    trading_dates=(data_date,),
                    through=data_date,
                    candidate_codes=candidates,
                    index_codes=BROAD_INDEX_CODES,
                    resume=False,
                )
            )
        except Exception as exc:
            summaries.append(
                _failed_step_summary("trading-structure", data_date, exc)
            )
        return _finalize_stage_with_research_features(
            runtime, summaries, data_date=data_date
        )
    raise ValueError(f"unsupported research data stage: {stage}")


def _shanghai_today() -> date:
    return datetime.now(SHANGHAI).date()


def _daily_partition_passed(
    warehouse: ResearchWarehouse,
    dataset: ResearchDatasetId,
    data_date: date,
) -> bool:
    manifest = warehouse.partition_manifest(dataset)
    if manifest.empty:
        return False
    passed = bool(
        (
            (manifest["partition_value"].astype(str) == data_date.isoformat())
            & (manifest["quality_status"].astype(str) == "passed")
        ).any()
    )
    if not passed:
        return False
    if dataset is ResearchDatasetId.INDUSTRY_DAILY_PROXY:
        return not ResearchGapRegistry(
            warehouse.duckdb_path
        ).has_active_gap(dataset, data_date)
    return True


def _failed_step_summary(
    scope: str, data_date: date, exc: Exception
) -> BackfillSummary:
    message = " ".join(str(exc).split())[:500]
    return BackfillSummary(
        scope=scope,
        start=data_date,
        through=data_date,
        failed=1,
        issues=[f"{type(exc).__name__}: {message}"],
    )


def select_fundamental_refresh_codes(
    announcements: pd.DataFrame,
    data_date: date,
) -> tuple[str, ...]:
    if announcements.empty or not {
        "announcement_time",
        "title",
        "ts_code",
    } <= set(announcements.columns):
        return ()
    published = pd.to_datetime(
        announcements["announcement_time"], utc=True, errors="coerce"
    ).dt.tz_convert("Asia/Shanghai")
    titles = announcements["title"].fillna("").astype(str).str.strip()
    financial = titles.map(
        lambda title: (
            "业绩预告" in title
            or "业绩快报" in title
            or _FINANCIAL_REPORT_TITLE.search(title) is not None
        )
    )
    selected = announcements.loc[
        (published.dt.date == data_date) & financial,
        "ts_code",
    ]
    return tuple(sorted(selected.dropna().astype(str).unique()))


@contextmanager
def research_job_lock(warehouse_root: Path):
    root = Path(warehouse_root)
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / ".research-jobs.lock"
    with lock_path.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _begin_stage_run(
    warehouse: ResearchWarehouse,
    stage: str,
    data_date: date,
) -> str:
    run_id = f"{stage}:{data_date}:{uuid4().hex}"
    idempotency_key = f"research-stage:{run_id}"
    with connect_research_warehouse(warehouse.duckdb_path) as connection:
        connection.execute(
            """
            insert into research_ingestion_runs
            (run_id, idempotency_key, stage, data_date, status,
             started_at, finished_at, summary_json)
            values (?, ?, ?, ?, 'running', now(), null, null)
            """,
            [run_id, idempotency_key, stage, data_date],
        )
    return run_id


def interrupt_orphan_runs(warehouse: ResearchWarehouse) -> int:
    payload = json.dumps(
        {"message": "superseded by a later locked run"},
        ensure_ascii=False,
    )
    with connect_research_warehouse(warehouse.duckdb_path) as connection:
        count = connection.execute(
            """
            select count(*) from research_ingestion_runs
            where status = 'running'
            """
        ).fetchone()[0]
        if count:
            connection.execute(
                """
                update research_ingestion_runs
                set status = 'interrupted', finished_at = now(),
                    summary_json = ?
                where status = 'running'
                """,
                [payload],
            )
    return int(count)


def _summary_status(summary: BackfillSummary) -> str:
    if summary.failed:
        return "failed"
    if summary.waiting_upstream:
        return "waiting_upstream"
    if summary.limited:
        return "limited"
    return "succeeded"


def _finish_stage_run(
    warehouse: ResearchWarehouse,
    run_id: str,
    summaries: tuple[BackfillSummary, ...],
) -> None:
    statuses = [_summary_status(summary) for summary in summaries]
    if "failed" in statuses:
        status = "failed"
    elif "waiting_upstream" in statuses:
        status = "waiting_upstream"
    elif "limited" in statuses:
        status = "limited"
    else:
        status = "succeeded"
    payload = {
        "summaries": [summary.model_dump(mode="json") for summary in summaries]
    }
    with connect_research_warehouse(warehouse.duckdb_path) as connection:
        connection.execute(
            """
            update research_ingestion_runs
            set status = ?, finished_at = now(), summary_json = ?
            where run_id = ?
            """,
            [status, json.dumps(payload, ensure_ascii=False), run_id],
        )


def _finish_failed_stage_run(
    warehouse: ResearchWarehouse,
    run_id: str,
    exc: Exception,
) -> None:
    payload = {
        "error_type": type(exc).__name__,
        "message": str(exc),
    }
    with connect_research_warehouse(warehouse.duckdb_path) as connection:
        connection.execute(
            """
            update research_ingestion_runs
            set status = 'failed', finished_at = now(), summary_json = ?
            where run_id = ?
            """,
            [json.dumps(payload, ensure_ascii=False), run_id],
        )


def _finalize_stage_summaries(
    runtime: ResearchDataRuntime,
    summaries: list[BackfillSummary],
) -> tuple[BackfillSummary, ...]:
    reconcile_research_gaps(runtime.warehouse)
    return tuple(summaries)


def _finalize_stage_with_research_features(
    runtime: ResearchDataRuntime,
    summaries: list[BackfillSummary],
    *,
    data_date: date,
) -> tuple[BackfillSummary, ...]:
    """Finish fact bookkeeping, then compute the governed local observations."""

    fact_summaries = _finalize_stage_summaries(runtime, summaries)
    try:
        derived = run_research_features(runtime.warehouse, data_date)
        derived_summary = BackfillSummary(
            scope="derived-research-features",
            start=data_date,
            through=data_date,
            committed=len(derived.committed_feature_sets),
            skipped=len(derived.skipped_feature_sets),
            limited=len(derived.limitations),
            limitations_checked=True,
            failed=len(derived.failed_feature_sets),
            issues=[derived.plain_language_summary, *derived.errors],
        )
    except Exception as exc:
        derived_summary = BackfillSummary(
            scope="derived-research-features",
            start=data_date,
            through=data_date,
            limitations_checked=True,
            failed=1,
            issues=[f"研究观察未能完成：{exc}"],
        )
    return (*fact_summaries, derived_summary)


def select_minute_candidate_scope(
    warehouse: ResearchWarehouse,
    through: date,
    *,
    limit: int = 50,
) -> tuple[str, ...]:
    calendar = warehouse.read_current(ResearchDatasetId.TRADE_CALENDAR)
    if calendar.empty:
        return ()
    dates = sorted(
        {
            value
            for value in pd.to_datetime(
                calendar.loc[calendar["is_open"].astype(bool), "cal_date"]
            ).dt.date
            if value <= through
        }
    )[-21:]
    if len(dates) < 2:
        return ()
    frames = [
        warehouse.read_current(
            ResearchDatasetId.EQUITY_DAILY,
            partition_value=value.isoformat(),
        )
        for value in dates
    ]
    frames = [frame for frame in frames if not frame.empty]
    if not frames:
        return ()
    frame = pd.concat(frames, ignore_index=True, sort=False)
    frame = frame.sort_values(["ts_code", "trade_date"])
    grouped = frame.groupby("ts_code", sort=False)
    stats = grouped.agg(
        first_close=("close", "first"),
        last_close=("close", "last"),
        avg_amount=("amount", "mean"),
        observations=("close", "count"),
    )
    stats = stats[stats["observations"] >= min(20, len(dates) - 1)].copy()
    if stats.empty:
        return ()
    stats["return"] = stats["last_close"] / stats["first_close"] - 1.0
    market_return = float(stats["return"].median())
    eligible = stats[
        (stats["avg_amount"] >= 30_000_000)
        & (stats["return"] > market_return)
    ].copy()
    if eligible.empty:
        eligible = stats.nlargest(limit, "avg_amount").copy()
    eligible["score"] = (
        eligible["return"].rank(pct=True) * 0.6
        + eligible["avg_amount"].rank(pct=True) * 0.4
    )
    return tuple(eligible.nlargest(limit, "score").index.astype(str))


def _trading_dates(
    warehouse: ResearchWarehouse,
    start: date,
    through: date,
) -> tuple[date, ...]:
    frame = warehouse.read_current(ResearchDatasetId.TRADE_CALENDAR)
    if frame.empty:
        return ()
    values = pd.to_datetime(frame.loc[frame["is_open"].astype(bool), "cal_date"]).dt.date
    return tuple(sorted({value for value in values if start <= value <= through}))


__all__ = [
    "BROAD_INDEX_CODES",
    "ResearchDataRuntime",
    "build_research_data_runtime",
    "run_research_backfill",
    "run_research_stage",
    "interrupt_orphan_runs",
    "research_job_lock",
    "reconcile_research_gaps",
    "select_minute_candidate_scope",
]
