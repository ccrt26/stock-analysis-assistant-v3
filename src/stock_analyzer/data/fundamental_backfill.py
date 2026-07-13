from __future__ import annotations

import hashlib
import json
import shutil
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import duckdb
import pandas as pd

from stock_analyzer.data.research_backfill import BackfillSummary
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


_ENDPOINTS = {
    ResearchDatasetId.INCOME_STATEMENT: "income",
    ResearchDatasetId.BALANCE_SHEET: "balancesheet",
    ResearchDatasetId.CASH_FLOW: "cashflow",
    ResearchDatasetId.FINANCIAL_INDICATOR: "fina_indicator",
    ResearchDatasetId.MAIN_BUSINESS: "fina_mainbz",
    ResearchDatasetId.EARNINGS_FORECAST: "forecast",
    ResearchDatasetId.EARNINGS_EXPRESS: "express",
}
_STATEMENTS = {
    ResearchDatasetId.INCOME_STATEMENT,
    ResearchDatasetId.BALANCE_SHEET,
    ResearchDatasetId.CASH_FLOW,
}


class FundamentalBackfillService:
    def __init__(
        self,
        client: TushareResearchClient,
        warehouse: ResearchWarehouse,
    ) -> None:
        self.client = client
        self.warehouse = warehouse

    def backfill(
        self,
        *,
        start: date,
        through: date,
        codes: tuple[str, ...] | None = None,
        resume: bool = True,
    ) -> BackfillSummary:
        summary = BackfillSummary(scope="fundamentals", start=start, through=through)
        scope_key = f"{start.isoformat()}:{through.isoformat()}"
        if resume and self._watermark_complete(scope_key):
            summary.skipped = 1
            return summary
        effective_codes = tuple(sorted(set(codes or self._warehouse_codes())))
        if not effective_codes:
            raise ValueError("fundamental backfill has no security universe")

        try:
            self._backfill_company_profiles(through, resume, summary)
        except ResearchSourceError:
            summary.failed += 1

        staging = self.warehouse.root / ".backfill_staging" / "fundamentals"
        staging.mkdir(parents=True, exist_ok=True)
        for code in effective_codes:
            income_announcement_map: dict[str, str] = {}
            for dataset, endpoint in _ENDPOINTS.items():
                path = staging / dataset.value / f"{code}.parquet"
                if resume and path.is_file():
                    if dataset is ResearchDatasetId.INCOME_STATEMENT:
                        income_announcement_map = _announcement_map(pd.read_parquet(path))
                    summary.skipped += 1
                    continue
                try:
                    frame = self.client.call(
                        endpoint,
                        ts_code=code,
                        start_date=_yyyymmdd(start),
                        end_date=_yyyymmdd(through),
                    )
                except ResearchSourceError:
                    summary.failed += 1
                    continue
                if "end_date" not in frame.columns:
                    if frame.empty:
                        frame = frame.copy()
                        frame["end_date"] = pd.Series(dtype=str)
                    else:
                        summary.failed += 1
                        continue
                if not frame.empty:
                    frame = frame.loc[
                        frame["end_date"].map(
                            lambda value: start <= _date(value) <= through
                        ).astype(bool)
                    ].copy()
                if dataset is ResearchDatasetId.INCOME_STATEMENT:
                    income_announcement_map = _announcement_map(frame)
                if dataset is ResearchDatasetId.MAIN_BUSINESS:
                    frame["_report_ann_date"] = frame["end_date"].map(
                        lambda value: income_announcement_map.get(str(value))
                    )
                path.parent.mkdir(parents=True, exist_ok=True)
                frame.to_parquet(path, index=False)
                summary.committed += 1

        for dataset, endpoint in _ENDPOINTS.items():
            files = sorted((staging / dataset.value).glob("*.parquet"))
            if not files:
                continue
            self._materialize_staged_dataset(
                dataset,
                endpoint,
                files,
                through,
                summary,
            )

        if summary.failed == 0:
            self._save_watermark(scope_key, through)
            shutil.rmtree(staging, ignore_errors=True)
        return summary

    def _backfill_company_profiles(
        self,
        through: date,
        resume: bool,
        summary: BackfillSummary,
    ) -> None:
        partition = "company-profile"
        if resume and self._partition_complete(
            ResearchDatasetId.COMPANY_PROFILE, partition
        ):
            summary.skipped += 1
            return
        frames: list[pd.DataFrame] = []
        for exchange in ("SSE", "SZSE", "BSE"):
            frame = self.client.call("stock_company", exchange=exchange)
            if not frame.empty:
                frames.append(frame)
        if not frames:
            raise ResearchSourceError(
                "Tushare stock_company returned no companies",
                category="waiting_upstream",
                endpoint="stock_company",
            )
        combined = pd.concat(frames, ignore_index=True, sort=False)
        required = {"ts_code", "introduction", "main_business", "exchange"}
        missing = sorted(required - set(combined.columns))
        if missing:
            raise ResearchSourceError(
                f"Tushare stock_company missing columns: {', '.join(missing)}",
                category="schema",
                endpoint="stock_company",
            )
        records = []
        for raw in combined.drop_duplicates("ts_code", keep="last").to_dict(
            orient="records"
        ):
            record = _clean_row(raw)
            record.update(
                {
                    "valid_from": through,
                    "valid_to": None,
                    "profile_snapshot_date": through,
                    "registered_capital_unit": "provider_10k_cny",
                    "available_at": _conservative_date_available(through),
                }
            )
            records.append(record)
        self.warehouse.commit_batch(
            FactBatch(
                dataset_id=ResearchDatasetId.COMPANY_PROFILE,
                partition_value=partition,
                source_name="tushare",
                source_endpoint="stock_company",
                ingestion_run_id=f"fundamentals:company:{partition}",
                ingested_at=datetime.now(timezone.utc),
                default_available_at=_conservative_date_available(through),
                records=records,
            )
        )
        summary.committed += 1

    def _materialize_staged_dataset(
        self,
        dataset: ResearchDatasetId,
        endpoint: str,
        files: list[Path],
        through: date,
        summary: BackfillSummary,
    ) -> None:
        paths = [str(path) for path in files]
        with duckdb.connect() as connection:
            periods = [
                str(row[0])
                for row in connection.execute(
                    """
                    select distinct cast(end_date as varchar)
                    from read_parquet(?, union_by_name=true, hive_partitioning=false)
                    where end_date is not null and cast(end_date as varchar) <> ''
                    order by 1
                    """,
                    [paths],
                ).fetchall()
            ]
            for period in periods:
                frame = connection.execute(
                    """
                    select * from read_parquet(?, union_by_name=true,
                                               hive_partitioning=false)
                    where cast(end_date as varchar) = ?
                    """,
                    [paths, period],
                ).fetchdf()
                records = [
                    self._normalize_financial_row(dataset, row, through)
                    for row in frame.to_dict(orient="records")
                ]
                self._commit_revision_levels(
                    dataset,
                    _date(period).isoformat(),
                    endpoint,
                    records,
                    through,
                    summary,
                )

    def _normalize_financial_row(
        self,
        dataset: ResearchDatasetId,
        raw: dict[str, Any],
        through: date,
    ) -> dict[str, Any]:
        row = _clean_row(raw)
        report_period = _date(row.pop("end_date"))
        row["report_period"] = report_period
        if dataset in _STATEMENTS:
            row["report_type"] = str(row.get("report_type") or "provider_default")
            row["statement_type"] = (
                f"comp={row.get('comp_type') or 'unknown'};"
                f"end={row.get('end_type') or 'unknown'}"
            )
        elif dataset is ResearchDatasetId.FINANCIAL_INDICATOR:
            row["report_type"] = "indicator"
        elif dataset is ResearchDatasetId.MAIN_BUSINESS:
            item = str(row.get("bz_item") or "").strip()
            row["classification"] = _main_business_classification(item)
            row["item_name"] = item
        elif dataset is ResearchDatasetId.EARNINGS_FORECAST:
            row["announcement_type"] = str(row.get("type") or "forecast")
            row["ann_date"] = _date(row["ann_date"])
        elif dataset is ResearchDatasetId.EARNINGS_EXPRESS:
            row["announcement_type"] = "express"
            row["ann_date"] = _date(row["ann_date"])

        publication = (
            row.get("f_ann_date")
            or row.get("ann_date")
            or row.get("_report_ann_date")
        )
        if isinstance(publication, date):
            publication_date = publication
        elif publication is not None and str(publication).strip():
            publication_date = _date(publication)
        else:
            publication_date = through
            row["availability_limitation"] = (
                "provider_has_no_announcement_date; usable only from ingestion cutoff"
            )
        row["available_at"] = _conservative_date_available(publication_date)
        row["source_updated_at"] = row["available_at"]
        row.pop("_report_ann_date", None)
        return row

    def _commit_revision_levels(
        self,
        dataset: ResearchDatasetId,
        partition: str,
        endpoint: str,
        records: list[dict[str, Any]],
        through: date,
        summary: BackfillSummary,
    ) -> None:
        contract = research_contract(dataset)
        grouped: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
        for row in records:
            key = tuple(str(row.get(field)) for field in contract.business_key)
            grouped[key].append(row)
        levels: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for rows in grouped.values():
            rows.sort(key=lambda item: str(item["available_at"]))
            seen: set[str] = set()
            rank = 0
            for row in rows:
                payload_hash = _business_hash(row)
                if payload_hash in seen:
                    continue
                seen.add(payload_hash)
                levels[rank].append(row)
                rank += 1
        for rank, level_rows in sorted(levels.items()):
            if not level_rows:
                continue
            self.warehouse.commit_batch(
                FactBatch(
                    dataset_id=dataset,
                    partition_value=partition,
                    source_name="tushare",
                    source_endpoint=endpoint,
                    ingestion_run_id=(
                        f"fundamentals:{dataset.value}:{partition}:revision-{rank}"
                    ),
                    ingested_at=datetime.now(timezone.utc),
                    default_available_at=_conservative_date_available(through),
                    records=level_rows,
                )
            )
            summary.committed += 1

    def _warehouse_codes(self) -> tuple[str, ...]:
        securities = self.warehouse.read_current(ResearchDatasetId.SECURITY_MASTER)
        if securities.empty:
            return ()
        if "list_status" in securities:
            securities = securities[securities["list_status"] == "L"]
        return tuple(sorted(securities["ts_code"].astype(str).unique()))

    def _partition_complete(
        self,
        dataset: ResearchDatasetId,
        partition: str,
    ) -> bool:
        frame = self.warehouse.partition_manifest(dataset)
        return not frame.empty and bool(
            (frame["partition_value"].astype(str) == partition).any()
        )

    def _watermark_complete(self, scope_key: str) -> bool:
        with connect_research_warehouse(
            self.warehouse.duckdb_path, read_only=True
        ) as connection:
            row = connection.execute(
                """
                select 1 from research_watermarks
                where dataset_id = 'fundamentals_scope' and scope_key = ?
                """,
                [scope_key],
            ).fetchone()
        return row is not None

    def _save_watermark(self, scope_key: str, through: date) -> None:
        with connect_research_warehouse(self.warehouse.duckdb_path) as connection:
            connection.execute(
                """
                insert or replace into research_watermarks
                (dataset_id, scope_key, watermark_value, updated_at, run_id)
                values ('fundamentals_scope', ?, ?, now(), ?)
                """,
                [scope_key, through.isoformat(), f"fundamentals:{scope_key}"],
            )


def _announcement_map(frame: pd.DataFrame) -> dict[str, str]:
    if frame.empty or "end_date" not in frame:
        return {}
    result: dict[str, str] = {}
    for row in frame.to_dict(orient="records"):
        publication = row.get("f_ann_date") or row.get("ann_date")
        if publication is None or pd.isna(publication):
            continue
        key = str(row["end_date"])
        result[key] = max(result.get(key, ""), str(publication))
    return result


def _clean_row(raw: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in raw.items():
        if value is None or (not isinstance(value, (list, dict)) and pd.isna(value)):
            result[key] = None
        elif hasattr(value, "item"):
            try:
                result[key] = value.item()
            except Exception:
                result[key] = value
        else:
            result[key] = value
    return result


def _business_hash(row: dict[str, Any]) -> str:
    excluded = {"available_at", "source_updated_at", "source_name", "source_endpoint"}
    payload = {key: value for key, value in row.items() if key not in excluded}
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode()
    ).hexdigest()


def _main_business_classification(item: str) -> str:
    if item.endswith("(产品)") or item.endswith("（产品）"):
        return "product"
    if item.endswith("(地区)") or item.endswith("（地区）"):
        return "region"
    if item.endswith("(行业)") or item.endswith("（行业）"):
        return "industry"
    return "provider_unspecified"


def _date(value: Any) -> date:
    return datetime.strptime(str(value).replace("-", ""), "%Y%m%d").date()


def _yyyymmdd(value: date) -> str:
    return value.strftime("%Y%m%d")


def _conservative_date_available(value: date) -> datetime:
    local = datetime.combine(
        value + timedelta(days=1), time.min, tzinfo=ZoneInfo("Asia/Shanghai")
    )
    return local.astimezone(timezone.utc)


__all__ = ["FundamentalBackfillService"]
