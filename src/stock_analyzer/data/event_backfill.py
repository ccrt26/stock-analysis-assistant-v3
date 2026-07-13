from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import pandas as pd

from stock_analyzer.data.research_backfill import BackfillSummary
from stock_analyzer.data.research_contracts import FactBatch, ResearchDatasetId
from stock_analyzer.data.tushare_research_client import TushareResearchClient
from stock_analyzer.storage.research_schema import connect_research_warehouse
from stock_analyzer.storage.research_warehouse import ResearchWarehouse


class EventBackfillService:
    def __init__(
        self,
        tushare: TushareResearchClient,
        cninfo: Any,
        warehouse: ResearchWarehouse,
    ) -> None:
        self.tushare = tushare
        self.cninfo = cninfo
        self.warehouse = warehouse

    def backfill(
        self,
        *,
        start: date,
        through: date,
        trading_dates: Iterable[date],
        resume: bool = True,
    ) -> BackfillSummary:
        summary = BackfillSummary(scope="events", start=start, through=through)
        announcement_start = max(start, through - timedelta(days=365))
        current_month = through.strftime("%Y-%m")
        for month_start, month_end in _month_ranges(announcement_start, through):
            partition = month_start.strftime("%Y-%m")
            if (
                resume
                and partition < current_month
                and self._complete(ResearchDatasetId.ANNOUNCEMENT, partition)
            ):
                summary.skipped += 1
                continue
            announcements = self.cninfo.fetch_announcements(month_start, month_end)
            self._commit(
                ResearchDatasetId.ANNOUNCEMENT,
                partition,
                "cninfo.new/hisAnnouncement/query",
                announcements,
                through,
                summary,
            )

        holder = self.tushare.call_paged(
            "stk_holdertrade",
            limit=3000,
            start_date=_yyyymmdd(start),
            end_date=_yyyymmdd(through),
        ).drop_duplicates(ignore_index=True)
        self._commit_grouped(
            ResearchDatasetId.HOLDER_TRADE,
            [_holder_row(row) for row in holder.to_dict(orient="records")],
            lambda row: row["ann_date"].strftime("%Y-%m"),
            "stk_holdertrade",
            through,
            resume,
            summary,
        )

        floats = self.tushare.call_paged(
            "share_float", start_date=_yyyymmdd(start), end_date=_yyyymmdd(through)
        )
        self._commit_grouped(
            ResearchDatasetId.SHARE_FLOAT,
            [_float_row(row) for row in floats.to_dict(orient="records")],
            lambda row: row["float_date"].strftime("%Y-%m"),
            "share_float",
            through,
            resume,
            summary,
        )

        repurchases = self.tushare.call_paged(
            "repurchase", start_date=_yyyymmdd(start), end_date=_yyyymmdd(through)
        )
        self._commit_grouped(
            ResearchDatasetId.REPURCHASE,
            [_repurchase_row(row) for row in repurchases.to_dict(orient="records")],
            lambda row: row["announcement_date"].strftime("%Y-%m"),
            "repurchase",
            through,
            resume,
            summary,
        )

        pledge_rows: list[dict[str, Any]] = []
        for snapshot in _quarter_snapshots(start, through):
            frame = self.tushare.call_paged(
                "pledge_stat", end_date=_yyyymmdd(snapshot)
            )
            for row in frame.to_dict(orient="records"):
                normalized = _clean(row)
                normalized["end_date"] = _date(row["end_date"])
                normalized["available_at"] = _conservative_available(snapshot)
                pledge_rows.append(normalized)
        self._commit_grouped(
            ResearchDatasetId.PLEDGE,
            pledge_rows,
            lambda row: row["end_date"].strftime("%Y-%m"),
            "pledge_stat",
            through,
            resume,
            summary,
        )

        suspension_start = through - timedelta(days=365)
        for trading_date in sorted(
            value for value in set(trading_dates) if value >= suspension_start
        ):
            partition = trading_date.isoformat()
            if resume and (
                self._complete(ResearchDatasetId.SUSPENSION, partition)
                or self._suspension_checked(partition)
            ):
                summary.skipped += 1
                continue
            frame = self.tushare.call(
                "suspend_d", trade_date=_yyyymmdd(trading_date)
            )
            if frame.empty:
                self._mark_suspension_checked(partition, "empty")
                continue
            rows = []
            for raw in frame.to_dict(orient="records"):
                row = _clean(raw)
                row["trade_date"] = _date(raw["trade_date"])
                row["available_at"] = _post_close(trading_date)
                rows.append(row)
            self._commit(
                ResearchDatasetId.SUSPENSION,
                partition,
                "suspend_d",
                rows,
                through,
                summary,
            )
            self._mark_suspension_checked(partition, f"rows:{len(rows)}")
        return summary

    def _commit_grouped(
        self,
        dataset: ResearchDatasetId,
        rows: list[dict[str, Any]],
        partitioner,
        endpoint: str,
        through: date,
        resume: bool,
        summary: BackfillSummary,
    ) -> None:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            grouped[str(partitioner(row))].append(row)
        for partition, partition_rows in sorted(grouped.items()):
            current_month = through.strftime("%Y-%m")
            if resume and partition < current_month and self._complete(dataset, partition):
                summary.skipped += 1
                continue
            self._commit(dataset, partition, endpoint, partition_rows, through, summary)

    def _commit(
        self,
        dataset: ResearchDatasetId,
        partition: str,
        endpoint: str,
        rows: list[dict[str, Any]],
        through: date,
        summary: BackfillSummary,
    ) -> None:
        if not rows:
            return
        self.warehouse.commit_batch(
            FactBatch(
                dataset_id=dataset,
                partition_value=partition,
                source_name="cninfo" if dataset is ResearchDatasetId.ANNOUNCEMENT else "tushare",
                source_endpoint=endpoint,
                ingestion_run_id=f"events:{dataset.value}:{partition}",
                ingested_at=datetime.now(timezone.utc),
                default_available_at=_post_close(through),
                records=rows,
            )
        )
        summary.committed += 1

    def _complete(self, dataset: ResearchDatasetId, partition: str) -> bool:
        frame = self.warehouse.partition_manifest(dataset)
        return not frame.empty and bool(
            (frame["partition_value"].astype(str) == partition).any()
        )

    def _suspension_checked(self, partition: str) -> bool:
        with connect_research_warehouse(
            self.warehouse.duckdb_path, read_only=True
        ) as connection:
            row = connection.execute(
                """
                select 1 from research_watermarks
                where dataset_id = 'suspension_check' and scope_key = ?
                """,
                [partition],
            ).fetchone()
        return row is not None

    def _mark_suspension_checked(self, partition: str, value: str) -> None:
        with connect_research_warehouse(self.warehouse.duckdb_path) as connection:
            connection.execute(
                """
                insert or replace into research_watermarks
                (dataset_id, scope_key, watermark_value, updated_at, run_id)
                values ('suspension_check', ?, ?, now(), ?)
                """,
                [partition, value, f"events:suspension-check:{partition}"],
            )


def _holder_row(raw: dict[str, Any]) -> dict[str, Any]:
    row = _clean(raw)
    row["provider_record_id"] = _stable_payload_hash(row)
    row["variant_group_id"] = _stable_payload_hash(
        {
            key: row.get(key)
            for key in ("ts_code", "holder_name", "ann_date", "in_de", "change_vol")
        }
    )
    row["ann_date"] = _date(raw["ann_date"])
    row["available_at"] = _conservative_available(row["ann_date"])
    return row


def _float_row(raw: dict[str, Any]) -> dict[str, Any]:
    row = _clean(raw)
    row["ann_date"] = _optional_date(raw.get("ann_date"))
    row["float_date"] = _date(raw["float_date"])
    publication = row["ann_date"] or row["float_date"]
    row["available_at"] = _conservative_available(publication)
    return row


def _repurchase_row(raw: dict[str, Any]) -> dict[str, Any]:
    row = _clean(raw)
    ann_date = _date(raw["ann_date"])
    row["announcement_date"] = ann_date
    row["process"] = str(raw.get("proc") or "unknown")
    row["expected_end_date"] = _optional_date(raw.get("exp_date"))
    row["event_effective_date"] = (
        _optional_date(raw.get("end_date"))
        or row["expected_end_date"]
        or ann_date
    )
    row["available_at"] = _conservative_available(ann_date)
    return row


def _quarter_snapshots(start: date, through: date) -> list[date]:
    candidates: set[date] = {through}
    for year in range(start.year, through.year + 1):
        for month, day in ((3, 31), (6, 30), (9, 30), (12, 31)):
            value = date(year, month, day)
            if start <= value <= through:
                candidates.add(value)
    return sorted(candidates)


def _month_ranges(start: date, through: date) -> list[tuple[date, date]]:
    ranges: list[tuple[date, date]] = []
    current = start
    while current <= through:
        if current.month == 12:
            following = date(current.year + 1, 1, 1)
        else:
            following = date(current.year, current.month + 1, 1)
        end = min(through, following - timedelta(days=1))
        ranges.append((current, end))
        current = following
    return ranges


def _clean(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        key: None if value is None or pd.isna(value) else value.item() if hasattr(value, "item") else value
        for key, value in raw.items()
    }


def _date(value: Any) -> date:
    return datetime.strptime(str(value).replace("-", ""), "%Y%m%d").date()


def _optional_date(value: Any) -> date | None:
    if value is None or pd.isna(value) or not str(value).strip():
        return None
    return _date(value)


def _yyyymmdd(value: date) -> str:
    return value.strftime("%Y%m%d")


def _conservative_available(value: date) -> datetime:
    return datetime.combine(
        value + timedelta(days=1), time.min, tzinfo=ZoneInfo("Asia/Shanghai")
    ).astimezone(timezone.utc)


def _post_close(value: date) -> datetime:
    return datetime.combine(
        value, time(15, 1), tzinfo=ZoneInfo("Asia/Shanghai")
    ).astimezone(timezone.utc)


def _stable_payload_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = ["EventBackfillService"]
