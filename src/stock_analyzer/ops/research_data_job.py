from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from functools import partial
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

from stock_analyzer.config import AppConfig
from stock_analyzer.data.classification_backfill import ClassificationBackfillService
from stock_analyzer.data.cninfo_research_client import CninfoResearchClient
from stock_analyzer.data.event_backfill import EventBackfillService
from stock_analyzer.data.fundamental_backfill import FundamentalBackfillService
from stock_analyzer.data.research_backfill import BackfillSummary, ResearchBackfillService
from stock_analyzer.data.research_contracts import ResearchDatasetId
from stock_analyzer.data.trading_structure_backfill import TradingStructureBackfillService
from stock_analyzer.data.tushare_research_client import TushareResearchClient
from stock_analyzer.storage.research_schema import connect_research_warehouse
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


@dataclass
class ResearchDataRuntime:
    config: AppConfig
    pro: Any
    tushare_module: Any
    tushare: TushareResearchClient
    cninfo: CninfoResearchClient
    warehouse: ResearchWarehouse
    http_client: httpx.Client

    def minute_fetcher(self, **kwargs: Any) -> pd.DataFrame:
        return self.tushare_module.pro_bar(api=self.pro, **kwargs)


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
                runtime.tushare, runtime.cninfo, runtime.warehouse
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
    for summary in summaries:
        _record_scope_outcome(runtime.warehouse, summary)
    reconcile_research_gaps(runtime.warehouse)
    return tuple(summaries)


def repair_research_gaps(
    runtime: ResearchDataRuntime,
    *,
    through: date,
) -> tuple[BackfillSummary, ...]:
    with connect_research_warehouse(
        runtime.warehouse.duckdb_path, read_only=True
    ) as connection:
        rows = connection.execute(
            """
            select dataset_id, partition_value
            from research_data_gaps
            where status in ('waiting_upstream', 'failed', 'validation_failed')
            order by first_seen_at
            """
        ).fetchall()
    if not rows:
        return ()
    scopes: dict[str, date] = {}
    dataset_scope = {
        "equity_daily": "market-core",
        "adj_factor": "market-core",
        "daily_basic": "market-core",
        "stock_limit": "market-core",
        "index_daily": "market-core",
    }
    for dataset_id, partition_value in rows:
        dataset_text = str(dataset_id)
        if dataset_text.startswith("scope:"):
            scope = dataset_text.split(":", 1)[1]
        else:
            scope = dataset_scope.get(dataset_text)
        if scope is None:
            continue
        first_partition = str(partition_value).split(":", 1)[0]
        try:
            start = date.fromisoformat(first_partition)
        except ValueError:
            start = through - timedelta(days=5 * 366)
        scopes[scope] = min(scopes.get(scope, start), start)
    summaries: list[BackfillSummary] = []
    for scope, start in sorted(scopes.items()):
        summaries.extend(
            run_research_backfill(
                runtime,
                start=start,
                through=through,
                scope=scope,
                resume=True,
            )
        )
    reconcile_research_gaps(runtime.warehouse)
    return tuple(summaries)


def reconcile_research_gaps(warehouse: ResearchWarehouse) -> int:
    with connect_research_warehouse(warehouse.duckdb_path) as connection:
        rows = connection.execute(
            """
            select gap_id, dataset_id, partition_value
            from research_data_gaps
            where status in ('waiting_upstream', 'failed', 'validation_failed')
            """
        ).fetchall()
        resolved = 0
        for gap_id, dataset_id, partition_value in rows:
            complete = connection.execute(
                """
                select 1 from research_fact_partitions
                where dataset_id = ? and partition_value = ?
                  and quality_status = 'passed'
                """,
                [dataset_id, partition_value],
            ).fetchone()
            if complete is None:
                continue
            connection.execute(
                """
                update research_data_gaps
                set status = 'resolved', last_checked_at = now(), next_retry_at = null
                where gap_id = ?
                """,
                [gap_id],
            )
            resolved += 1
    return resolved


def _record_scope_outcome(
    warehouse: ResearchWarehouse,
    summary: BackfillSummary,
) -> None:
    scope_partition = f"{summary.start.isoformat()}:{summary.through.isoformat()}"
    gap_id = hashlib.sha256(
        f"scope|{summary.scope}|{scope_partition}".encode("utf-8")
    ).hexdigest()
    if summary.failed == 0 and summary.waiting_upstream == 0:
        with connect_research_warehouse(warehouse.duckdb_path) as connection:
            connection.execute(
                """
                update research_data_gaps
                set status = 'resolved', last_checked_at = now(), next_retry_at = null
                where gap_id = ?
                """,
                [gap_id],
            )
        return
    status = "failed" if summary.failed else "waiting_upstream"
    impact = {
        "market-core": "核心行情不完整，不能进行全市场横向筛选。",
        "classifications": "板块归属或板块行情不完整，热点判断需要降级。",
        "fundamentals": "部分公司财务或主营资料不完整，基本面判断需要标注缺口。",
        "events": "部分公告或公司行动不完整，事件与风险判断需要标注缺口。",
        "trading-structure": "融资融券或分钟数据不完整，不能据此证明资金身份。",
    }.get(summary.scope, "该范围数据不完整，相关结论需要降级。")
    now = datetime.now(timezone.utc)
    with connect_research_warehouse(warehouse.duckdb_path) as connection:
        connection.execute(
            """
            insert into research_data_gaps
            (gap_id, dataset_id, partition_value, status, reason_category,
             source_name, first_seen_at, last_checked_at, next_retry_at,
             impact_text, detail_json)
            values (?, ?, ?, ?, ?, null, ?, ?, null, ?, ?)
            on conflict(dataset_id, partition_value, reason_category)
            do update set status=excluded.status,
                          last_checked_at=excluded.last_checked_at,
                          impact_text=excluded.impact_text,
                          detail_json=excluded.detail_json
            """,
            [
                gap_id,
                f"scope:{summary.scope}",
                scope_partition,
                status,
                "scope_incomplete",
                now,
                now,
                impact,
                json.dumps(summary.model_dump(mode="json"), ensure_ascii=False),
            ],
        )


def run_research_stage(
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
            _record_scope_outcome(runtime.warehouse, summary)
            return (summary,)
        return run_research_backfill(
            runtime,
            start=data_date,
            through=data_date,
            scope="market-core",
            resume=True,
        )
    trading_dates = _trading_dates(
        runtime.warehouse, data_date - timedelta(days=10), data_date
    )
    if stage == "evening":
        event_summary = EventBackfillService(
            runtime.tushare, runtime.cninfo, runtime.warehouse
        ).backfill(
            start=data_date,
            through=data_date,
            trading_dates=(data_date,) if data_date in trading_dates else (),
            resume=True,
        )
        classification_summary = ClassificationBackfillService(
            runtime.tushare, runtime.warehouse
        ).refresh_daily(data_date)
        announcements = runtime.warehouse.read_current(
            ResearchDatasetId.ANNOUNCEMENT
        )
        affected_codes: tuple[str, ...] = ()
        if not announcements.empty:
            published = pd.to_datetime(
                announcements["announcement_time"], utc=True
            ).dt.tz_convert("Asia/Shanghai")
            affected_codes = tuple(
                sorted(
                    announcements.loc[
                        published.dt.date == data_date, "ts_code"
                    ].astype(str).unique()
                )
            )
        summaries: list[BackfillSummary] = [event_summary, classification_summary]
        if affected_codes:
            summaries.append(
                FundamentalBackfillService(
                    runtime.tushare, runtime.warehouse
                ).backfill(
                    start=data_date - timedelta(days=5 * 366),
                    through=data_date,
                    codes=affected_codes,
                    resume=True,
                )
            )
        return _finalize_stage_summaries(runtime, summaries)
    if stage == "next-morning":
        repaired = list(repair_research_gaps(runtime, through=data_date))
        late_event_summary = EventBackfillService(
            runtime.tushare, runtime.cninfo, runtime.warehouse
        ).backfill(
            start=data_date,
            through=data_date,
            trading_dates=(),
            resume=True,
        )
        candidates = select_minute_candidate_scope(runtime.warehouse, data_date)
        summary = TradingStructureBackfillService(
            runtime.tushare,
            runtime.warehouse,
            minute_fetcher=runtime.minute_fetcher,
        ).backfill(
            trading_dates=(data_date,),
            through=data_date,
            candidate_codes=candidates,
            index_codes=BROAD_INDEX_CODES,
            resume=True,
        )
        return _finalize_stage_summaries(
            runtime, [*repaired, late_event_summary, summary]
        )
    raise ValueError(f"unsupported research data stage: {stage}")


def _finalize_stage_summaries(
    runtime: ResearchDataRuntime,
    summaries: list[BackfillSummary],
) -> tuple[BackfillSummary, ...]:
    for summary in summaries:
        _record_scope_outcome(runtime.warehouse, summary)
    reconcile_research_gaps(runtime.warehouse)
    return tuple(summaries)


def select_minute_candidate_scope(
    warehouse: ResearchWarehouse,
    through: date,
    *,
    limit: int = 50,
) -> tuple[str, ...]:
    frame = warehouse.read_current(ResearchDatasetId.EQUITY_DAILY)
    if frame.empty:
        return ()
    frame = frame[pd.to_datetime(frame["trade_date"]).dt.date <= through].copy()
    dates = sorted(pd.to_datetime(frame["trade_date"]).dt.date.unique())[-21:]
    if len(dates) < 2:
        return ()
    frame = frame[pd.to_datetime(frame["trade_date"]).dt.date.isin(dates)]
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
    "repair_research_gaps",
    "reconcile_research_gaps",
    "select_minute_candidate_scope",
]
