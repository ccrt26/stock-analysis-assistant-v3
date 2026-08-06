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
import pyarrow.parquet as pq

from stock_analyzer.data.research_backfill import BackfillSummary
from stock_analyzer.data.research_contracts import (
    AvailabilityPrecision,
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
_CORE_FINANCIALS = _STATEMENTS | {ResearchDatasetId.FINANCIAL_INDICATOR}
_GOVERNANCE_FIELDS = {
    "source_name",
    "source_endpoint",
    "source_record_id",
    "source_updated_at",
    "available_at",
    "availability_precision",
    "ingested_at",
    "ingestion_run_id",
    "payload_hash",
    "business_key_hash",
    "quality_status",
    "revision_no",
}


class AmbiguousProviderVariantError(ValueError):
    pass


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
        effective_codes = tuple(sorted(set(codes or self._warehouse_codes())))
        if not effective_codes:
            raise ValueError("fundamental backfill has no security universe")
        target_periods = _target_report_periods(start, through)
        expected_core_codes = self._expected_core_codes(effective_codes, through)
        scope_hash = hashlib.sha256("|".join(effective_codes).encode("utf-8")).hexdigest()
        scope_key = f"{start.isoformat()}:{through.isoformat()}:{scope_hash}"
        if resume and self._watermark_complete(scope_key):
            summary.skipped = 1
            return summary

        try:
            self._backfill_company_profiles(through, resume, summary)
        except ResearchSourceError:
            summary.failed += 1

        staging_scope = hashlib.sha256(scope_key.encode("utf-8")).hexdigest()[:24]
        staging = (
            self.warehouse.root
            / ".backfill_staging"
            / "fundamentals"
            / staging_scope
        )
        staging.mkdir(parents=True, exist_ok=True)
        for code in effective_codes:
            income_announcement_map: dict[str, str] = {}
            for dataset, endpoint in _ENDPOINTS.items():
                path = staging / dataset.value / f"{code}.parquet"
                if resume and path.is_file():
                    if (
                        dataset in _CORE_FINANCIALS
                        and code in expected_core_codes
                        and pq.ParquetFile(path).metadata.num_rows == 0
                    ):
                        path.unlink()
                    else:
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
                    if code not in summary.retry_codes:
                        summary.retry_codes.append(code)
                    continue
                if "end_date" not in frame.columns:
                    if frame.empty:
                        frame = frame.copy()
                        frame["end_date"] = pd.Series(dtype=str)
                    else:
                        summary.failed += 1
                        if code not in summary.retry_codes:
                            summary.retry_codes.append(code)
                        continue
                if (
                    frame.empty
                    and dataset in _CORE_FINANCIALS
                    and code in expected_core_codes
                ):
                    summary.waiting_upstream += 1
                    if code not in summary.retry_codes:
                        summary.retry_codes.append(code)
                    continue
                if not frame.empty:
                    frame = frame.loc[
                        frame["end_date"].map(
                            lambda value: _date(value) in target_periods
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
            files = [
                staging / dataset.value / f"{code}.parquet"
                for code in effective_codes
                if (staging / dataset.value / f"{code}.parquet").is_file()
            ]
            if not files:
                continue
            self._materialize_staged_dataset(
                dataset,
                endpoint,
                files,
                through,
                summary,
            )

        if summary.failed == 0 and summary.waiting_upstream == 0:
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
        existing = self.warehouse.read_current(
            ResearchDatasetId.COMPANY_PROFILE,
            partition_value=partition,
        )
        active_by_code: dict[str, dict[str, Any]] = {}
        if not existing.empty:
            active = existing.loc[existing["valid_to"].isna()]
            duplicated = active["ts_code"].astype(str).duplicated(keep=False)
            if duplicated.any():
                codes = sorted(active.loc[duplicated, "ts_code"].astype(str).unique())
                raise ValueError(
                    "company_profile has overlapping active entities: "
                    + ", ".join(codes[:10])
                )
            active_by_code = {
                str(row["ts_code"]): row
                for row in active.to_dict(orient="records")
            }

        records: list[dict[str, Any]] = []
        for raw in combined.drop_duplicates("ts_code", keep="last").to_dict(
            orient="records"
        ):
            profile = _clean_row(raw)
            profile["registered_capital_unit"] = "provider_10k_cny"
            code = str(profile["ts_code"])
            current = active_by_code.get(code)
            if current is None:
                records.append(
                    {
                        **profile,
                        "valid_from": through,
                        "valid_to": None,
                        "profile_snapshot_date": through,
                    }
                )
                continue
            if _profile_content(current) == _profile_content(profile):
                continue
            current_start = pd.Timestamp(current["valid_from"]).date()
            if current_start < through:
                closure = _profile_record_from_fact(current)
                closure["valid_to"] = through - timedelta(days=1)
                records.append(closure)
                records.append(
                    {
                        **profile,
                        "valid_from": through,
                        "valid_to": None,
                        "profile_snapshot_date": through,
                    }
                )
            else:
                records.append(
                    {
                        **profile,
                        "valid_from": current_start,
                        "valid_to": None,
                        "profile_snapshot_date": through,
                    }
                )
        if not records:
            summary.skipped += 1
            return
        result = self.warehouse.commit_batch(
            FactBatch(
                dataset_id=ResearchDatasetId.COMPANY_PROFILE,
                partition_value=partition,
                source_name="tushare",
                source_endpoint="stock_company",
                ingestion_run_id=f"fundamentals:company:{through.isoformat()}",
                ingested_at=datetime.now(timezone.utc),
                default_available_at=_conservative_date_available(through),
                records=records,
            )
        )
        if result.new_rows or result.changed_rows:
            summary.committed += 1
        else:
            summary.skipped += 1

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
            if dataset in {
                ResearchDatasetId.EARNINGS_FORECAST,
                ResearchDatasetId.EARNINGS_EXPRESS,
            }:
                groups = [
                    str(row[0])
                    for row in connection.execute(
                        """
                        select distinct substr(cast(ann_date as varchar), 1, 6)
                        from read_parquet(?, union_by_name=true,
                                           hive_partitioning=false)
                        where ann_date is not null
                          and length(cast(ann_date as varchar)) >= 6
                        order by 1
                        """,
                        [paths],
                    ).fetchall()
                ]
                for ann_month in groups:
                    frame = connection.execute(
                        """
                        select * from read_parquet(?, union_by_name=true,
                                                   hive_partitioning=false)
                        where substr(cast(ann_date as varchar), 1, 6) = ?
                        """,
                        [paths, ann_month],
                    ).fetchdf()
                    records = [
                        self._normalize_financial_row(dataset, row, through)
                        for row in frame.to_dict(orient="records")
                    ]
                    self._commit_revision_levels(
                        dataset,
                        f"{ann_month[:4]}-{ann_month[4:6]}",
                        endpoint,
                        records,
                        through,
                        summary,
                    )
                return
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
            row["classification"] = _main_business_classification(
                item,
                row.get("bz_code"),
            )
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
            publication_date = None
            row["availability_limitation"] = (
                "provider_has_no_announcement_date; usable only from ingestion cutoff"
            )
        if publication_date is not None:
            row["available_at"] = _conservative_date_available(publication_date)
            row["source_updated_at"] = row["available_at"]
            row["availability_precision"] = (
                AvailabilityPrecision.DATE_CONSERVATIVE.value
            )
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
        initial_current = self.warehouse.read_current(
            dataset,
            partition_value=partition,
        )
        initial_keys = {
            tuple(str(row.get(field)) for field in contract.business_key)
            for row in initial_current.to_dict(orient="records")
        }
        current_hashes = {
            tuple(str(row.get(field)) for field in contract.business_key): str(
                row["payload_hash"]
            )
            for row in initial_current.to_dict(orient="records")
        }
        known_hashes: dict[tuple[str, ...], set[str]] = defaultdict(set)
        for row in initial_current.to_dict(orient="records"):
            key = tuple(str(row.get(field)) for field in contract.business_key)
            known_hashes[key].add(str(row["payload_hash"]))
        for revision in self.warehouse.revision_rows(
            dataset,
            partition_values=(partition,),
        ):
            payload = revision["row_payload"]
            key = tuple(str(payload.get(field)) for field in contract.business_key)
            known_hashes[key].add(str(revision["payload_hash"]))

        reconstruction_levels: dict[int, list[dict[str, Any]]] = defaultdict(list)
        observed_rows: list[dict[str, Any]] = []
        for key, rows in grouped.items():
            try:
                timeline = _canonical_provider_timeline(
                    dataset,
                    key,
                    rows,
                    preferred_payload_hash=current_hashes.get(key),
                )
            except AmbiguousProviderVariantError:
                summary.limited += 1
                summary.limitations_checked = True
                summary.issues.append(
                    f"{dataset.value}:{'/'.join(key)}:"
                    "同一公开时间存在多个无法排序的上游版本，未写入该业务键"
                )
                continue
            if key in initial_keys:
                unseen = [
                    row for row in timeline
                    if _business_hash(row) not in known_hashes[key]
                ]
                if unseen:
                    # All unseen content was first observed in this run.  Only
                    # the provider's final state is knowable at receipt time.
                    observed_rows.append(unseen[-1])
                continue
            for rank, row in enumerate(timeline):
                reconstruction_levels[rank].append(row)

        for rank, level_rows in sorted(reconstruction_levels.items()):
            if not level_rows:
                continue
            self._commit_financial_rows(
                dataset=dataset,
                partition=partition,
                endpoint=endpoint,
                rows=level_rows,
                through=through,
                run_suffix=f"reconstruction-{rank}",
                reconstruct_source_revisions=True,
                summary=summary,
            )
        if observed_rows:
            self._commit_financial_rows(
                dataset=dataset,
                partition=partition,
                endpoint=endpoint,
                rows=observed_rows,
                through=through,
                run_suffix="observed-change",
                reconstruct_source_revisions=False,
                summary=summary,
            )

    def _commit_financial_rows(
        self,
        *,
        dataset: ResearchDatasetId,
        partition: str,
        endpoint: str,
        rows: list[dict[str, Any]],
        through: date,
        run_suffix: str,
        reconstruct_source_revisions: bool,
        summary: BackfillSummary,
    ) -> None:
        ingested_at = datetime.now(timezone.utc)
        prepared_rows: list[dict[str, Any]] = []
        for row in rows:
            prepared = dict(row)
            if prepared.get("available_at") is None:
                prepared["available_at"] = ingested_at
                prepared["availability_precision"] = (
                    AvailabilityPrecision.INGESTION_CUTOFF.value
                )
            prepared_rows.append(prepared)
        self.warehouse.commit_batch(
            FactBatch(
                dataset_id=dataset,
                partition_value=partition,
                source_name="tushare",
                source_endpoint=endpoint,
                ingestion_run_id=(
                    f"fundamentals:{dataset.value}:{partition}:{run_suffix}"
                ),
                ingested_at=ingested_at,
                default_available_at=_conservative_date_available(through),
                reconstruct_source_revisions=reconstruct_source_revisions,
                records=prepared_rows,
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

    def _expected_core_codes(
        self,
        codes: tuple[str, ...],
        through: date,
    ) -> set[str]:
        required_period = _latest_mandatory_report_period(through)
        securities = self.warehouse.read_current(ResearchDatasetId.SECURITY_MASTER)
        if required_period is None or securities.empty or "list_date" not in securities:
            return set(codes)
        list_dates = {
            str(row["ts_code"]): _optional_date(row.get("list_date"))
            for row in securities.to_dict(orient="records")
        }
        return {
            code
            for code in codes
            if list_dates.get(code) is None or list_dates[code] <= required_period
        }

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


def _profile_content(row: dict[str, Any]) -> dict[str, Any]:
    excluded = _GOVERNANCE_FIELDS | {
        "valid_from",
        "valid_to",
        "profile_snapshot_date",
    }
    return {
        key: _json_safe(value)
        for key, value in row.items()
        if key not in excluded
    }


def _profile_record_from_fact(row: dict[str, Any]) -> dict[str, Any]:
    record = {
        key: value
        for key, value in row.items()
        if key not in _GOVERNANCE_FIELDS
    }
    for field in ("valid_from", "valid_to", "profile_snapshot_date"):
        value = record.get(field)
        if value is not None and not pd.isna(value):
            record[field] = pd.Timestamp(value).date()
        elif field == "valid_to":
            record[field] = None
    return record


def _canonical_provider_timeline(
    dataset: ResearchDatasetId,
    key: tuple[str, ...],
    rows: list[dict[str, Any]],
    *,
    preferred_payload_hash: str | None = None,
) -> list[dict[str, Any]]:
    by_availability: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        value = row.get("available_at")
        bucket = "~ingestion" if value is None else pd.Timestamp(value).isoformat()
        by_availability[bucket].append(row)

    result: list[dict[str, Any]] = []
    for bucket in sorted(by_availability):
        unique = {
            _business_hash(row): row for row in by_availability[bucket]
        }
        candidates = list(unique.values())
        if len(candidates) == 1:
            result.append(candidates[0])
            continue
        ranked = [(_update_flag_rank(row.get("update_flag")), row) for row in candidates]
        if any(rank is None for rank, _ in ranked):
            preferred = [
                row
                for row in candidates
                if _business_hash(row) == preferred_payload_hash
            ]
            if len(preferred) == 1:
                result.append(preferred[0])
                continue
            raise AmbiguousProviderVariantError(
                f"ambiguous same-time provider variants for {dataset.value} "
                f"key={key} available_at={bucket}"
            )
        highest = max(rank for rank, _ in ranked if rank is not None)
        winners = [row for rank, row in ranked if rank == highest]
        if len(winners) != 1:
            raise AmbiguousProviderVariantError(
                f"ambiguous highest update_flag for {dataset.value} "
                f"key={key} available_at={bucket}"
            )
        result.append(winners[0])
    return result


def _update_flag_rank(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _business_hash(row: dict[str, Any]) -> str:
    payload = {
        key: _json_safe(value)
        for key, value in row.items()
        if key not in _GOVERNANCE_FIELDS
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, pd.Timestamp)):
        timestamp = pd.Timestamp(value)
        if timestamp.tzinfo is None:
            timestamp = timestamp.tz_localize("UTC")
        else:
            timestamp = timestamp.tz_convert("UTC")
        return timestamp.to_pydatetime().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if pd.isna(value):
        return None
    return str(value)


def _main_business_classification(item: str, provider_code: Any = None) -> str:
    mapped = {
        "P": "product",
        "D": "region",
        "I": "industry",
    }.get(str(provider_code or "").strip().upper())
    if mapped is not None:
        return mapped
    if item.endswith("(产品)") or item.endswith("（产品）"):
        return "product"
    if item.endswith("(地区)") or item.endswith("（地区）"):
        return "region"
    if item.endswith("(行业)") or item.endswith("（行业）"):
        return "industry"
    return "provider_unspecified"


def _date(value: Any) -> date:
    return datetime.strptime(str(value).replace("-", ""), "%Y%m%d").date()


def _optional_date(value: Any) -> date | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, pd.Timestamp):
        return value.date()
    return _date(value)


def _yyyymmdd(value: date) -> str:
    return value.strftime("%Y%m%d")


def _target_report_periods(start: date, through: date) -> set[date]:
    quarter_ends: list[date] = []
    for year in range(through.year - 6, through.year + 1):
        for month, day in ((3, 31), (6, 30), (9, 30), (12, 31)):
            value = date(year, month, day)
            if start <= value <= through:
                quarter_ends.append(value)
    latest_quarters = sorted(quarter_ends, reverse=True)[:12]

    annual_ends = [
        date(year, 12, 31)
        for year in range(through.year, through.year - 7, -1)
        if start <= date(year, 12, 31) <= through
    ][:5]
    return set(latest_quarters) | set(annual_ends)


def _latest_mandatory_report_period(through: date) -> date | None:
    candidates: list[tuple[date, date]] = []
    for year in range(through.year - 3, through.year + 1):
        candidates.extend(
            [
                (date(year, 3, 31), date(year, 4, 30)),
                (date(year, 6, 30), date(year, 8, 31)),
                (date(year, 9, 30), date(year, 10, 31)),
                (date(year, 12, 31), date(year + 1, 4, 30)),
            ]
        )
    available = [item for item in candidates if item[1] <= through]
    if not available:
        return None
    return max(available, key=lambda item: (item[1], item[0]))[0]


def _conservative_date_available(value: date) -> datetime:
    local = datetime.combine(
        value + timedelta(days=1), time.min, tzinfo=ZoneInfo("Asia/Shanghai")
    )
    return local.astimezone(timezone.utc)


__all__ = ["FundamentalBackfillService"]
