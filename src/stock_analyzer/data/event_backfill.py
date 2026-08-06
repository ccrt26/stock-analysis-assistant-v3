from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import pandas as pd

from stock_analyzer.data.research_backfill import BackfillSummary
from stock_analyzer.data.research_contracts import (
    AvailabilityPrecision,
    FactBatch,
    ResearchDatasetId,
)
from stock_analyzer.data.tushare_research_client import (
    ResearchSourceError,
    TushareResearchClient,
)
from stock_analyzer.storage.research_schema import connect_research_warehouse
from stock_analyzer.storage.research_warehouse import ResearchWarehouse


_SHARE_FLOAT_PAGE_SIZE = 5000
_SHARE_FLOAT_MAX_PAGES = 20
_SHARE_FLOAT_HISTORY_DAYS = 365
_SHARE_FLOAT_FUTURE_DAYS = 3 * 366


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
            if self._should_skip_historical(
                ResearchDatasetId.ANNOUNCEMENT,
                partition,
                current_month=current_month,
                through=through,
                resume=resume,
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
            self._mark_partition_checked(
                ResearchDatasetId.ANNOUNCEMENT,
                partition,
                f"rows:{len(announcements)}",
            )

        for month_start, month_end in _month_ranges(start, through):
            partition = month_start.strftime("%Y-%m")
            if self._should_skip_historical(
                ResearchDatasetId.HOLDER_TRADE,
                partition,
                current_month=current_month,
                through=through,
                resume=resume,
            ):
                summary.skipped += 1
                continue
            holder = self.tushare.call_paged(
                "stk_holdertrade",
                limit=3000,
                start_date=_yyyymmdd(month_start),
                end_date=_yyyymmdd(month_end),
            ).drop_duplicates(ignore_index=True)
            self._require_dates_in_range(
                holder,
                "ann_date",
                month_start,
                month_end,
                "stk_holdertrade",
            )
            holder_rows = [
                _holder_row(row) for row in holder.to_dict(orient="records")
            ]
            self._commit(
                ResearchDatasetId.HOLDER_TRADE,
                partition,
                "stk_holdertrade",
                holder_rows,
                through,
                summary,
            )
            self._mark_partition_checked(
                ResearchDatasetId.HOLDER_TRADE,
                partition,
                f"rows:{len(holder_rows)}",
            )

        self._backfill_share_float(
            start=start,
            through=through,
            current_month=current_month,
            resume=resume,
            summary=summary,
        )

        for month_start, month_end in _month_ranges(start, through):
            partition = month_start.strftime("%Y-%m")
            if self._should_skip_historical(
                ResearchDatasetId.REPURCHASE,
                partition,
                current_month=current_month,
                through=through,
                resume=resume,
            ):
                summary.skipped += 1
                continue
            repurchases = self.tushare.call_paged(
                "repurchase",
                start_date=_yyyymmdd(month_start),
                end_date=_yyyymmdd(month_end),
            ).drop_duplicates(ignore_index=True)
            self._require_dates_in_range(
                repurchases,
                "ann_date",
                month_start,
                month_end,
                "repurchase",
            )
            repurchase_rows = [
                _repurchase_row(row)
                for row in repurchases.to_dict(orient="records")
            ]
            self._commit(
                ResearchDatasetId.REPURCHASE,
                partition,
                "repurchase",
                repurchase_rows,
                through,
                summary,
            )
            self._mark_partition_checked(
                ResearchDatasetId.REPURCHASE,
                partition,
                f"rows:{len(repurchase_rows)}",
            )

        for snapshot in _quarter_snapshots(start, through):
            requested_snapshot = snapshot
            partition = requested_snapshot.strftime("%Y-%m")
            if self._should_skip_historical(
                ResearchDatasetId.PLEDGE,
                partition,
                current_month=current_month,
                through=through,
                resume=resume,
            ):
                summary.skipped += 1
                continue
            frame, actual_snapshot = self._fetch_pledge_snapshot(
                requested_snapshot
            )
            if frame.empty:
                summary.waiting_upstream += 1
                summary.issues.append(
                    f"pledge:{requested_snapshot.isoformat()}:waiting_upstream"
                )
                continue
            actual_partition = actual_snapshot.strftime("%Y-%m")
            self._require_dates_in_range(
                frame,
                "end_date",
                actual_snapshot,
                actual_snapshot,
                "pledge_stat",
            )
            pledge_rows: list[dict[str, Any]] = []
            for row in frame.to_dict(orient="records"):
                normalized = _clean(row)
                normalized["end_date"] = _date(row["end_date"])
                pledge_rows.append(normalized)
            self._commit(
                ResearchDatasetId.PLEDGE,
                actual_partition,
                "pledge_stat",
                pledge_rows,
                through,
                summary,
            )
            self._mark_partition_checked(
                ResearchDatasetId.PLEDGE,
                partition,
                f"actual:{actual_snapshot.isoformat()}:rows:{len(pledge_rows)}",
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
                row["availability_precision"] = (
                    AvailabilityPrecision.INFERRED_FROM_ENDPOINT_POLICY.value
                )
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

    def _fetch_share_float_range(self, start: date, through: date) -> pd.DataFrame:
        try:
            frame = self.tushare.call_paged(
                "share_float",
                limit=_SHARE_FLOAT_PAGE_SIZE,
                max_pages=_SHARE_FLOAT_MAX_PAGES,
                start_date=_yyyymmdd(start),
                end_date=_yyyymmdd(through),
            )
        except ResearchSourceError as exc:
            if exc.category != "incomplete" or start >= through:
                raise
            midpoint = start + timedelta(days=(through - start).days // 2)
            left = self._fetch_share_float_range(start, midpoint)
            right = self._fetch_share_float_range(midpoint + timedelta(days=1), through)
            return pd.concat([left, right], ignore_index=True, sort=False).drop_duplicates(
                ignore_index=True
            )
        if frame.empty:
            return frame
        if "float_date" not in frame.columns:
            raise ResearchSourceError(
                "Tushare share_float lacks float_date",
                category="schema",
                endpoint="share_float",
            )
        returned_dates = frame["float_date"].map(_date)
        if ((returned_dates < start) | (returned_dates > through)).any():
            raise ResearchSourceError(
                "Tushare share_float returned rows outside the requested range",
                category="invalid_semantics",
                endpoint="share_float",
            )
        return frame.drop_duplicates(ignore_index=True)

    def _fetch_pledge_snapshot(
        self,
        requested: date,
        *,
        max_weeks_back: int = 4,
    ) -> tuple[pd.DataFrame, date]:
        latest_friday = _latest_friday_on_or_before(requested)
        candidates = [requested]
        candidates.extend(
            latest_friday - timedelta(days=7 * weeks_back)
            for weeks_back in range(max_weeks_back + 1)
        )
        seen: set[date] = set()
        for candidate in candidates:
            if candidate in seen:
                continue
            seen.add(candidate)
            frame = self.tushare.call_paged(
                "pledge_stat", end_date=_yyyymmdd(candidate)
            ).drop_duplicates(ignore_index=True)
            if not frame.empty:
                return frame, candidate
        return pd.DataFrame(), requested

    def _backfill_share_float(
        self,
        *,
        start: date,
        through: date,
        current_month: str,
        resume: bool,
        summary: BackfillSummary,
    ) -> None:
        if start == through:
            self._backfill_share_float_announcements(through, summary)
            return

        full_window = start < through - timedelta(days=_SHARE_FLOAT_HISTORY_DAYS)
        window_start = (
            through - timedelta(days=_SHARE_FLOAT_HISTORY_DAYS)
            if full_window
            else start
        )
        window_end = (
            through + timedelta(days=_SHARE_FLOAT_FUTURE_DAYS)
            if full_window
            else through
        )
        total_shares = self._latest_total_shares(through)
        for month_start, month_end in _month_ranges(window_start, window_end):
            partition = month_start.strftime("%Y-%m")
            if resume and partition != current_month and (
                self._complete(ResearchDatasetId.SHARE_FLOAT, partition)
                or self._partition_checked(ResearchDatasetId.SHARE_FLOAT, partition)
            ):
                summary.skipped += 1
                continue
            floats = self._fetch_share_float_range(month_start, month_end)
            float_rows = _collapse_share_float_rows([
                _float_row(row)
                for row in floats.to_dict(orient="records")
                if _share_float_known_as_of(row, through)
            ], total_shares)
            self._commit(
                ResearchDatasetId.SHARE_FLOAT,
                partition,
                "share_float",
                float_rows,
                through,
                summary,
            )
            self._mark_partition_checked(
                ResearchDatasetId.SHARE_FLOAT,
                partition,
                f"rows:{len(float_rows)}",
            )
        if full_window:
            removed = self.warehouse.prune_partitions_before(
                ResearchDatasetId.SHARE_FLOAT,
                window_start.strftime("%Y-%m"),
            )
            self._clear_partition_checks(ResearchDatasetId.SHARE_FLOAT, removed)

    def _backfill_share_float_announcements(
        self,
        announcement_date: date,
        summary: BackfillSummary,
    ) -> None:
        frame = self.tushare.call_paged(
            "share_float",
            limit=_SHARE_FLOAT_PAGE_SIZE,
            max_pages=_SHARE_FLOAT_MAX_PAGES,
            ann_date=_yyyymmdd(announcement_date),
        ).drop_duplicates(ignore_index=True)
        self._require_dates_in_range(
            frame,
            "ann_date",
            announcement_date,
            announcement_date,
            "share_float",
        )
        grouped: dict[str, list[dict[str, Any]]] = {}
        for raw in frame.to_dict(orient="records"):
            if not _share_float_known_as_of(raw, announcement_date):
                continue
            row = _float_row(raw)
            partition = row["float_date"].strftime("%Y-%m")
            grouped.setdefault(partition, []).append(row)
        for partition, rows in sorted(grouped.items()):
            rows = _collapse_share_float_rows(
                rows,
                self._latest_total_shares(announcement_date),
            )
            self._commit(
                ResearchDatasetId.SHARE_FLOAT,
                partition,
                "share_float:ann_date",
                rows,
                announcement_date,
                summary,
            )

    def _latest_total_shares(self, through: date) -> dict[str, float]:
        return _latest_total_shares(self.warehouse, through)

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

    def _should_skip_historical(
        self,
        dataset: ResearchDatasetId,
        partition: str,
        *,
        current_month: str,
        through: date,
        resume: bool,
    ) -> bool:
        previous_month = (through.replace(day=1) - timedelta(days=1)).strftime(
            "%Y-%m"
        )
        refresh_previous_month = through.day <= 7 and partition == previous_month
        return bool(
            resume
            and partition < current_month
            and not refresh_previous_month
            and (
                self._complete(dataset, partition)
                or self._partition_checked(dataset, partition)
            )
        )

    def _partition_checked(
        self, dataset: ResearchDatasetId, partition: str
    ) -> bool:
        with connect_research_warehouse(
            self.warehouse.duckdb_path, read_only=True
        ) as connection:
            row = connection.execute(
                """
                select 1 from research_watermarks
                where dataset_id = ? and scope_key = ?
                """,
                [_partition_check_dataset_id(dataset), partition],
            ).fetchone()
        return row is not None

    def _mark_partition_checked(
        self,
        dataset: ResearchDatasetId,
        partition: str,
        value: str,
    ) -> None:
        with connect_research_warehouse(self.warehouse.duckdb_path) as connection:
            connection.execute(
                """
                insert or replace into research_watermarks
                (dataset_id, scope_key, watermark_value, updated_at, run_id)
                values (?, ?, ?, now(), ?)
                """,
                [
                    _partition_check_dataset_id(dataset),
                    partition,
                    value,
                    f"events:{dataset.value}-check:{partition}",
                ],
            )

    def _clear_partition_checks(
        self,
        dataset: ResearchDatasetId,
        partitions: tuple[str, ...],
    ) -> None:
        if not partitions:
            return
        placeholders = ",".join("?" for _ in partitions)
        with connect_research_warehouse(self.warehouse.duckdb_path) as connection:
            connection.execute(
                f"""
                delete from research_watermarks
                where dataset_id = ? and scope_key in ({placeholders})
                """,
                [_partition_check_dataset_id(dataset), *partitions],
            )

    @staticmethod
    def _require_dates_in_range(
        frame: pd.DataFrame,
        field: str,
        start: date,
        through: date,
        endpoint: str,
    ) -> None:
        if frame.empty:
            return
        if field not in frame.columns:
            raise ResearchSourceError(
                f"Tushare {endpoint} lacks {field}",
                category="schema",
                endpoint=endpoint,
            )
        returned_dates = frame[field].map(_date)
        if ((returned_dates < start) | (returned_dates > through)).any():
            raise ResearchSourceError(
                f"Tushare {endpoint} returned rows outside the requested range",
                category="invalid_semantics",
                endpoint=endpoint,
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
    row["availability_precision"] = AvailabilityPrecision.DATE_CONSERVATIVE.value
    return row


def _float_row(raw: dict[str, Any]) -> dict[str, Any]:
    row = _clean(raw)
    row["provider_record_id"] = _stable_payload_hash(row)
    row["variant_group_id"] = _stable_payload_hash(
        {
            key: row.get(key)
            for key in ("ts_code", "float_date", "holder_name", "share_type")
        }
    )
    row["ann_date"] = _optional_date(raw.get("ann_date"))
    row["float_date"] = _date(raw["float_date"])
    publication = row["ann_date"] or row["float_date"]
    row["available_at"] = _conservative_available(publication)
    row["availability_precision"] = AvailabilityPrecision.DATE_CONSERVATIVE.value
    if row["ann_date"] is None:
        row["availability_limitation"] = (
            "provider_has_no_announcement_date; usable only after float_date"
        )
    return row


def _collapse_share_float_rows(
    rows: list[dict[str, Any]],
    total_shares: dict[str, float],
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["variant_group_id"]), []).append(row)

    collapsed: list[dict[str, Any]] = []
    for group in grouped.values():
        exact = {str(row["provider_record_id"]): row for row in group}
        variants = list(exact.values())
        if (
            len(variants) == 1
            and int(variants[0].get("provider_variant_count") or 1) > 1
        ):
            collapsed.append(dict(variants[0]))
            continue
        variants.sort(
            key=lambda row: (
                _sortable_date(row.get("ann_date")),
                _finite_number(row.get("float_share")),
                _finite_number(row.get("float_ratio")),
                str(row["provider_record_id"]),
            ),
            reverse=True,
        )
        latest_announcement = _sortable_date(variants[0].get("ann_date"))
        candidates = [
            row
            for row in variants
            if _sortable_date(row.get("ann_date")) == latest_announcement
        ]
        total_share = total_shares.get(str(candidates[0].get("ts_code")))
        resolution = "largest_float_share_fallback"
        if total_share:
            def ratio_error(row: dict[str, Any]) -> tuple[float, str]:
                expected = _finite_number(row.get("float_share")) / total_share * 100.0
                reported = _finite_number(row.get("float_ratio"))
                return abs(expected - reported), str(row["provider_record_id"])

            chosen = min(candidates, key=ratio_error)
            resolution = "matched_latest_total_share"
        else:
            chosen = candidates[0]
        chosen = dict(chosen)
        chosen["provider_variant_count"] = len(variants)
        chosen["provider_variant_resolution"] = resolution
        chosen["provider_variant_hashes_json"] = json.dumps(
            sorted(str(row["provider_record_id"]) for row in variants),
            ensure_ascii=False,
        )
        collapsed.append(chosen)
    return collapsed


def normalize_existing_share_float(
    warehouse: ResearchWarehouse,
    *,
    through: date,
) -> dict[str, int]:
    """Rebuild current share-float facts on their stable natural business key."""
    manifest = warehouse.partition_manifest(ResearchDatasetId.SHARE_FLOAT)
    total_shares = _latest_total_shares(warehouse, through)
    batches: list[FactBatch] = []
    before_rows = 0
    after_rows = 0
    fallback_rows = 0
    now = datetime.now(timezone.utc)
    for partition in manifest["partition_value"].astype(str).tolist():
        frame = warehouse.read_current(
            ResearchDatasetId.SHARE_FLOAT,
            partition_value=partition,
        )
        before_rows += len(frame)
        rows = _collapse_share_float_rows(
            frame.to_dict(orient="records"),
            total_shares,
        )
        after_rows += len(rows)
        fallback_rows += sum(
            row.get("provider_variant_resolution") == "largest_float_share_fallback"
            and int(row.get("provider_variant_count") or 1) > 1
            for row in rows
        )
        if rows:
            batches.append(
                FactBatch(
                    dataset_id=ResearchDatasetId.SHARE_FLOAT,
                    partition_value=partition,
                    source_name="tushare",
                    source_endpoint="share_float:stable-key-normalization",
                    ingestion_run_id=f"share-float-normalize:{partition}",
                    ingested_at=now,
                    default_available_at=_conservative_available(through),
                    records=rows,
                )
            )
    warehouse.replace_dataset_batches(ResearchDatasetId.SHARE_FLOAT, batches)
    return {
        "before_rows": before_rows,
        "after_rows": after_rows,
        "collapsed_rows": before_rows - after_rows,
        "fallback_variant_groups": fallback_rows,
    }


def _latest_total_shares(
    warehouse: ResearchWarehouse,
    through: date,
) -> dict[str, float]:
    manifest = warehouse.partition_manifest(ResearchDatasetId.DAILY_BASIC)
    if manifest.empty:
        return {}
    eligible = manifest.loc[
        manifest["partition_value"].astype(str) <= through.isoformat()
    ]
    if eligible.empty:
        return {}
    partition = str(eligible["partition_value"].astype(str).max())
    frame = warehouse.read_current(
        ResearchDatasetId.DAILY_BASIC,
        partition_value=partition,
    )
    if frame.empty or not {"ts_code", "total_share"} <= set(frame):
        return {}
    result: dict[str, float] = {}
    for raw in frame[["ts_code", "total_share"]].to_dict(orient="records"):
        value = pd.to_numeric(raw.get("total_share"), errors="coerce")
        if pd.notna(value) and float(value) > 0:
            # daily_basic is normalized by TushareResearchClient from ten-
            # thousand shares to shares.  Event matching uses that internal
            # unit directly; converting again would inflate the denominator.
            result[str(raw["ts_code"])] = float(value)
    return result


def _sortable_date(value: Any) -> date:
    if value is None or pd.isna(value):
        return date.min
    return pd.Timestamp(value).date()


def _finite_number(value: Any) -> float:
    parsed = pd.to_numeric(value, errors="coerce")
    return 0.0 if pd.isna(parsed) else float(parsed)


def _repurchase_row(raw: dict[str, Any]) -> dict[str, Any]:
    row = _clean(raw)
    row["provider_record_id"] = _stable_payload_hash(row)
    ann_date = _date(raw["ann_date"])
    row["announcement_date"] = ann_date
    row["process"] = str(raw.get("proc") or "unknown")
    row["expected_end_date"] = _optional_date(raw.get("exp_date"))
    row["event_effective_date"] = (
        _optional_date(raw.get("end_date"))
        or row["expected_end_date"]
        or ann_date
    )
    row["variant_group_id"] = _stable_payload_hash(
        {
            "ts_code": row.get("ts_code"),
            "announcement_date": row["announcement_date"],
            "process": row["process"],
            "event_effective_date": row["event_effective_date"],
        }
    )
    row["available_at"] = _conservative_available(ann_date)
    row["availability_precision"] = AvailabilityPrecision.DATE_CONSERVATIVE.value
    return row


def _quarter_snapshots(start: date, through: date) -> list[date]:
    candidates: set[date] = {through}
    for year in range(start.year, through.year + 1):
        for month, day in ((3, 31), (6, 30), (9, 30), (12, 31)):
            value = date(year, month, day)
            if start <= value <= through:
                candidates.add(value)
    return sorted(candidates)


def _latest_friday_on_or_before(value: date) -> date:
    return value - timedelta(days=(value.weekday() - 4) % 7)


def _partition_check_dataset_id(dataset: ResearchDatasetId) -> str:
    if dataset is ResearchDatasetId.PLEDGE:
        return "event_partition_check_v2:pledge"
    return f"event_partition_check:{dataset.value}"


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


def _share_float_known_as_of(raw: dict[str, Any], known_through: date) -> bool:
    float_date = _date(raw["float_date"])
    announcement_date = _optional_date(raw.get("ann_date"))
    if announcement_date is not None:
        return announcement_date <= known_through
    return float_date <= known_through


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
