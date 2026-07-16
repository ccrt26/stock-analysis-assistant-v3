from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

import pandas as pd
from pydantic import BaseModel, Field

from stock_analyzer.data.research_contracts import (
    FactBatch,
    ResearchDatasetId,
    research_contract,
)
from stock_analyzer.data.tushare_research_client import (
    ResearchSourceError,
    TushareResearchClient,
)
from stock_analyzer.storage.research_schema import connect_research_warehouse
from stock_analyzer.storage.research_warehouse import ResearchWarehouse
from stock_analyzer.storage.research_contract_audit import (
    audit_fact_partition_contract,
)


class BackfillSummary(BaseModel):
    scope: str
    start: date
    through: date
    committed: int = 0
    skipped: int = 0
    waiting_upstream: int = 0
    limited: int = 0
    limitations_checked: bool = False
    failed: int = 0
    issues: list[str] = Field(default_factory=list)
    retry_codes: list[str] = Field(default_factory=list)


class ResearchBackfillService:
    def __init__(
        self,
        client: TushareResearchClient,
        warehouse: ResearchWarehouse,
        *,
        broad_index_codes: tuple[str, ...] = (
            "000001.SH",
            "399001.SZ",
            "399006.SZ",
            "000688.SH",
            "000300.SH",
            "000905.SH",
            "000852.SH",
            "899050.BJ",
        ),
    ) -> None:
        self.client = client
        self.warehouse = warehouse
        self.broad_index_codes = broad_index_codes

    def backfill_market_core(
        self,
        *,
        start: date,
        through: date,
        resume: bool = True,
    ) -> BackfillSummary:
        summary = BackfillSummary(scope="market-core", start=start, through=through)
        calendar = self.client.fetch_trade_calendar(start, through)
        for year, frame in calendar.groupby("cal_year"):
            partition = str(year)
            records = frame.drop(columns=["cal_year"]).to_dict(orient="records")
            self.warehouse.commit_batch(
                FactBatch(
                    dataset_id=ResearchDatasetId.TRADE_CALENDAR,
                    partition_value=partition,
                    source_name="tushare",
                    source_endpoint="trade_cal",
                    ingestion_run_id=f"market-core:calendar:{partition}",
                    ingested_at=datetime.now(timezone.utc),
                    default_available_at=_post_close_utc(through),
                    records=records,
                )
            )
            summary.committed += 1

        snapshot = "security-master"
        if not (resume and self._complete(ResearchDatasetId.SECURITY_MASTER, snapshot)):
            securities = self.client.fetch_security_master(through)
            self.warehouse.commit_batch(
                FactBatch(
                    dataset_id=ResearchDatasetId.SECURITY_MASTER,
                    partition_value=snapshot,
                    source_name="tushare",
                    source_endpoint="stock_basic",
                    ingestion_run_id=f"market-core:security:{snapshot}",
                    ingested_at=datetime.now(timezone.utc),
                    default_available_at=_post_close_utc(through),
                    records=securities.to_dict(orient="records"),
                )
            )
            summary.committed += 1
        else:
            summary.skipped += 1

        open_dates = sorted(
            value
            for value in calendar.loc[calendar["is_open"], "cal_date"].tolist()
            if start <= value <= through
        )
        daily_datasets = (
            ResearchDatasetId.EQUITY_DAILY,
            ResearchDatasetId.ADJ_FACTOR,
            ResearchDatasetId.DAILY_BASIC,
            ResearchDatasetId.STOCK_LIMIT,
        )
        for trade_date in open_dates:
            partition = trade_date.isoformat()
            needed = {
                dataset
                for dataset in daily_datasets
                if not (resume and self._complete(dataset, partition))
            }
            summary.skipped += len(daily_datasets) - len(needed)
            if not needed:
                continue
            run_id = f"market-core:{partition}"
            try:
                batches = self.client.fetch_market_date(
                    trade_date,
                    run_id=run_id,
                    datasets=needed,
                )
            except ResearchSourceError as exc:
                status = (
                    "waiting_upstream"
                    if exc.category == "waiting_upstream"
                    else "failed"
                )
                self._record_gap(
                    dataset=ResearchDatasetId.EQUITY_DAILY,
                    partition=partition,
                    status=status,
                    reason=exc.category,
                    source="tushare",
                    impact="该交易日核心行情不完整，不能用于全市场筛选。",
                    detail=str(exc),
                )
                if status == "waiting_upstream":
                    summary.waiting_upstream += 1
                else:
                    summary.failed += 1
                continue
            for batch in batches:
                self.warehouse.commit_batch(batch)
                summary.committed += 1
        self._backfill_broad_indexes(start, through, resume, summary)
        return summary

    def _backfill_broad_indexes(
        self,
        start: date,
        through: date,
        resume: bool,
        summary: BackfillSummary,
    ) -> None:
        grouped: dict[str, list[dict]] = {}
        for code in self.broad_index_codes:
            frame = self.client.call(
                "index_daily",
                ts_code=code,
                start_date=start.strftime("%Y%m%d"),
                end_date=through.strftime("%Y%m%d"),
            )
            required = {
                "ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount"
            }
            missing = sorted(required - set(frame.columns))
            if missing:
                raise ResearchSourceError(
                    f"Tushare index_daily missing columns: {', '.join(missing)}",
                    category="schema",
                    endpoint="index_daily",
                )
            if frame.empty:
                summary.waiting_upstream += 1
                continue
            for raw in frame.to_dict(orient="records"):
                trading_date = datetime.strptime(
                    str(raw["trade_date"]), "%Y%m%d"
                ).date()
                grouped.setdefault(trading_date.isoformat(), []).append(
                    {
                        "trade_date": trading_date,
                        "index_code": str(raw["ts_code"]),
                        "open": _optional_number(raw.get("open")),
                        "high": _optional_number(raw.get("high")),
                        "low": _optional_number(raw.get("low")),
                        "close": _optional_number(raw.get("close")),
                        "pre_close": _optional_number(raw.get("pre_close")),
                        "pct_chg": _optional_number(raw.get("pct_chg")),
                        "volume": _optional_number(raw.get("vol"), 100.0),
                        "amount": _optional_number(raw.get("amount"), 1_000.0),
                    }
                )
        for partition, rows in sorted(grouped.items()):
            if resume and self._complete(ResearchDatasetId.INDEX_DAILY, partition):
                summary.skipped += 1
                continue
            self.warehouse.commit_batch(
                FactBatch(
                    dataset_id=ResearchDatasetId.INDEX_DAILY,
                    partition_value=partition,
                    source_name="tushare",
                    source_endpoint="index_daily",
                    ingestion_run_id=f"market-core:index:{partition}",
                    ingested_at=datetime.now(timezone.utc),
                    default_available_at=_post_close_utc(date.fromisoformat(partition)),
                    records=rows,
                )
            )
            summary.committed += 1

    def _complete(self, dataset: ResearchDatasetId, partition: str) -> bool:
        manifest = self.warehouse.partition_manifest(dataset)
        if manifest.empty:
            return False
        complete = bool(
            (
                (manifest["partition_value"].astype(str) == partition)
                & (manifest["quality_status"] == "passed")
            ).any()
        )
        if not complete:
            return False
        selected = manifest[manifest["partition_value"].astype(str) == partition]
        path = self.warehouse.root / str(selected.iloc[0]["relative_path"])
        return path.is_file() and audit_fact_partition_contract(
            path, research_contract(dataset)
        ).valid

    def _record_gap(
        self,
        *,
        dataset: ResearchDatasetId,
        partition: str,
        status: str,
        reason: str,
        source: str,
        impact: str,
        detail: str,
    ) -> None:
        now = datetime.now(timezone.utc)
        gap_id = hashlib.sha256(
            f"{dataset.value}|{partition}|{reason}".encode("utf-8")
        ).hexdigest()
        with connect_research_warehouse(self.warehouse.duckdb_path) as connection:
            connection.execute(
                """
                insert into research_data_gaps
                (gap_id, dataset_id, partition_value, status, reason_category,
                 source_name, first_seen_at, last_checked_at, next_retry_at,
                 impact_text, detail_json)
                values (?, ?, ?, ?, ?, ?, ?, ?, null, ?, ?)
                on conflict(dataset_id, partition_value, reason_category)
                do update set status=excluded.status,
                              last_checked_at=excluded.last_checked_at,
                              impact_text=excluded.impact_text,
                              detail_json=excluded.detail_json
                """,
                [
                    gap_id,
                    dataset.value,
                    partition,
                    status,
                    reason,
                    source,
                    now,
                    now,
                    impact,
                    json.dumps({"message": detail}, ensure_ascii=False),
                ],
            )


def _post_close_utc(value: date) -> datetime:
    local = datetime.combine(value, time(15, 1), tzinfo=ZoneInfo("Asia/Shanghai"))
    return local.astimezone(timezone.utc)


def _optional_number(value, multiplier: float = 1.0) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value) * multiplier


__all__ = ["BackfillSummary", "ResearchBackfillService"]
