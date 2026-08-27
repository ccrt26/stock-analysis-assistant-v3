from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
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
from stock_analyzer.storage.research_warehouse import ResearchWarehouse
from stock_analyzer.storage.research_schema import connect_research_warehouse


class ClassificationBackfillService:
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
        resume: bool = True,
    ) -> BackfillSummary:
        summary = BackfillSummary(
            scope="classifications", start=start, through=through
        )
        history_dates = self._latest_sessions(start, through, sessions=250)
        history_start = history_dates[0] if history_dates else start
        allowed_dates = set(history_dates) if history_dates else None
        industry_snapshot_complete = resume and self._complete(
            ResearchDatasetId.INDUSTRY_CATALOG, "SW2021"
        ) and self._complete(ResearchDatasetId.INDUSTRY_MEMBER, "SW2021")
        if industry_snapshot_complete:
            catalog = self.warehouse.read_current(
                ResearchDatasetId.INDUSTRY_CATALOG,
                partition_value="SW2021",
            ).to_dict(orient="records")
            summary.skipped += 2
        else:
            catalog, members, observed_at = self._sw_catalog_and_members(through)
            self._commit(
                ResearchDatasetId.INDUSTRY_CATALOG,
                "SW2021",
                "index_classify+index_basic",
                catalog,
                through,
                resume,
                summary,
                ingested_at=observed_at,
            )
            self._commit(
                ResearchDatasetId.INDUSTRY_MEMBER,
                "SW2021",
                "index_member_all",
                members,
                through,
                resume,
                summary,
                ingested_at=observed_at,
            )

        industry_codes = sorted(
            {
                str(row["industry_code"])
                for row in catalog
                if str(row.get("is_published", "")) == "1"
                and str(row.get("level", "")) == "L1"
            }
        )
        if resume and self._daily_history_complete(
            ResearchDatasetId.INDUSTRY_DAILY, history_dates
        ):
            summary.skipped += len(history_dates)
        else:
            industry_bars = self._index_history(
                industry_codes,
                start=history_start,
                through=through,
                code_field="industry_code",
                summary=summary,
                allowed_dates=allowed_dates,
            )
            self._commit_daily_groups(
                ResearchDatasetId.INDUSTRY_DAILY,
                "index_daily",
                industry_bars,
                through,
                resume,
                summary,
            )

        if resume and self._complete(
            ResearchDatasetId.THEME_CATALOG, "official-theme-v1"
        ):
            themes = self.warehouse.read_current(
                ResearchDatasetId.THEME_CATALOG,
                partition_value="official-theme-v1",
            ).to_dict(orient="records")
            summary.skipped += 1
        else:
            themes = self._theme_catalog(through)
            self._commit(
                ResearchDatasetId.THEME_CATALOG,
                "official-theme-v1",
                "index_basic",
                themes,
                through,
                resume,
                summary,
            )
        theme_codes = sorted({str(row["theme_code"]) for row in themes})
        if resume and self._complete(
            ResearchDatasetId.THEME_MEMBER, "official-theme-v1"
        ):
            summary.skipped += 1
        else:
            theme_members = self._theme_members(
                theme_codes, start=history_start, through=through, summary=summary
            )
            self._commit(
                ResearchDatasetId.THEME_MEMBER,
                "official-theme-v1",
                "index_weight",
                theme_members,
                through,
                resume,
                summary,
            )
        if resume and self._daily_history_complete(
            ResearchDatasetId.THEME_DAILY, history_dates
        ):
            summary.skipped += len(history_dates)
        else:
            theme_bars = self._index_history(
                theme_codes,
                start=history_start,
                through=through,
                code_field="theme_code",
                summary=summary,
                allowed_dates=allowed_dates,
            )
            self._commit_daily_groups(
                ResearchDatasetId.THEME_DAILY,
                "index_daily",
                theme_bars,
                through,
                resume,
                summary,
            )
        return summary

    def _latest_session_start(
        self,
        requested_start: date,
        through: date,
        *,
        sessions: int,
    ) -> date:
        dates = self._latest_sessions(requested_start, through, sessions=sessions)
        return dates[0] if dates else requested_start

    def _latest_sessions(
        self,
        requested_start: date,
        through: date,
        *,
        sessions: int,
    ) -> tuple[date, ...]:
        calendar = self.warehouse.read_current(ResearchDatasetId.TRADE_CALENDAR)
        if calendar.empty:
            return ()
        values = pd.to_datetime(
            calendar.loc[calendar["is_open"].astype(bool), "cal_date"]
        ).dt.date
        open_dates = sorted(
            {
                value
                for value in values
                if requested_start <= value <= through
            }
        )
        if len(open_dates) <= sessions:
            return tuple(open_dates)
        return tuple(open_dates[-sessions:])

    def refresh_daily(
        self,
        data_date: date,
        *,
        datasets: Iterable[ResearchDatasetId] | None = None,
        refresh_memberships: bool = True,
    ) -> BackfillSummary:
        requested = (
            {
                ResearchDatasetId.INDUSTRY_DAILY,
                ResearchDatasetId.THEME_DAILY,
            }
            if datasets is None
            else {ResearchDatasetId(value) for value in datasets}
        )
        allowed = {
            ResearchDatasetId.INDUSTRY_DAILY,
            ResearchDatasetId.THEME_DAILY,
        }
        if not requested or not requested <= allowed:
            raise ValueError("daily classification refresh only supports industry/theme")
        summary = BackfillSummary(
            scope=(
                next(iter(requested)).value
                if len(requested) == 1
                else "classification-daily"
            ),
            start=data_date,
            through=data_date,
        )
        industry_catalog = self.warehouse.read_current(
            ResearchDatasetId.INDUSTRY_CATALOG
        )
        theme_catalog = self.warehouse.read_current(ResearchDatasetId.THEME_CATALOG)
        missing_requested_catalog = (
            ResearchDatasetId.INDUSTRY_DAILY in requested
            and industry_catalog.empty
        ) or (
            ResearchDatasetId.THEME_DAILY in requested and theme_catalog.empty
        )
        if missing_requested_catalog and datasets is None:
            return self.backfill(start=data_date, through=data_date, resume=True)
        if missing_requested_catalog:
            raise ResearchSourceError(
                "targeted daily classification refresh lacks its catalog",
                category="incomplete",
                endpoint="index_daily",
            )
        frame = self.client.call_paged(
            "index_daily", trade_date=_yyyymmdd(data_date)
        )
        _require(
            frame,
            (
                "ts_code", "trade_date", "open", "high", "low", "close",
                "vol", "amount",
            ),
            "index_daily",
        )
        industry_codes = (
            set(industry_catalog["industry_code"].astype(str))
            if not industry_catalog.empty
            else set()
        )
        theme_codes = (
            set(theme_catalog["theme_code"].astype(str))
            if not theme_catalog.empty
            else set()
        )
        industry_rows: list[dict[str, Any]] = []
        theme_rows: list[dict[str, Any]] = []
        for raw in frame.to_dict(orient="records"):
            code = str(raw["ts_code"])
            target: list[dict[str, Any]] | None = None
            code_field = ""
            if (
                ResearchDatasetId.INDUSTRY_DAILY in requested
                and code in industry_codes
            ):
                target = industry_rows
                code_field = "industry_code"
            elif ResearchDatasetId.THEME_DAILY in requested and code in theme_codes:
                target = theme_rows
                code_field = "theme_code"
            if target is None:
                continue
            target.append(
                {
                    "trade_date": data_date,
                    code_field: code,
                    "open": _number(raw["open"]),
                    "high": _number(raw["high"]),
                    "low": _number(raw["low"]),
                    "close": _number(raw["close"]),
                    "pre_close": _number(raw.get("pre_close")),
                    "pct_chg": _number(raw.get("pct_chg")),
                    "volume": _number(raw["vol"], multiplier=100.0),
                    "amount": _number(raw["amount"], multiplier=1_000.0),
                }
            )
        partition = data_date.isoformat()
        if ResearchDatasetId.INDUSTRY_DAILY in requested:
            self._commit(
                ResearchDatasetId.INDUSTRY_DAILY,
                partition,
                "index_daily",
                industry_rows,
                data_date,
                False,
                summary,
            )
        if ResearchDatasetId.THEME_DAILY in requested:
            self._commit(
                ResearchDatasetId.THEME_DAILY,
                partition,
                "index_daily",
                theme_rows,
                data_date,
                False,
                summary,
            )
        if refresh_memberships:
            self._refresh_monthly_memberships(data_date, summary)
        return summary

    def _refresh_monthly_memberships(
        self,
        data_date: date,
        summary: BackfillSummary,
    ) -> None:
        scope_key = data_date.strftime("%Y-%m")
        with connect_research_warehouse(
            self.warehouse.duckdb_path, read_only=True
        ) as connection:
            done = connection.execute(
                """
                select 1 from research_watermarks
                where dataset_id = 'classification_membership_month'
                  and scope_key = ?
                """,
                [scope_key],
            ).fetchone()
        if done is not None:
            summary.skipped += 1
            return
        catalog, members, observed_at = self._sw_catalog_and_members(data_date)
        self._commit(
            ResearchDatasetId.INDUSTRY_CATALOG,
            "SW2021",
            "index_classify+index_basic",
            catalog,
            data_date,
            False,
            summary,
            ingested_at=observed_at,
        )
        self._commit(
            ResearchDatasetId.INDUSTRY_MEMBER,
            "SW2021",
            "index_member_all",
            members,
            data_date,
            False,
            summary,
            ingested_at=observed_at,
        )
        themes = self._theme_catalog(data_date)
        self._commit(
            ResearchDatasetId.THEME_CATALOG,
            "official-theme-v1",
            "index_basic",
            themes,
            data_date,
            False,
            summary,
        )
        theme_rows = self._theme_members(
            sorted({str(row["theme_code"]) for row in themes}),
            start=data_date - timedelta(days=45),
            through=data_date,
            summary=summary,
        )
        theme_rows = self._close_previous_theme_snapshots(theme_rows)
        self._commit(
            ResearchDatasetId.THEME_MEMBER,
            "official-theme-v1",
            "index_weight",
            theme_rows,
            data_date,
            False,
            summary,
        )
        with connect_research_warehouse(self.warehouse.duckdb_path) as connection:
            connection.execute(
                """
                insert or replace into research_watermarks
                (dataset_id, scope_key, watermark_value, updated_at, run_id)
                values ('classification_membership_month', ?, ?, now(), ?)
                """,
                [scope_key, data_date.isoformat(), f"classification:{scope_key}"],
            )

    def _close_previous_theme_snapshots(
        self,
        new_rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not new_rows:
            return new_rows
        first_new: dict[str, date] = {}
        for row in new_rows:
            code = str(row["theme_code"])
            value = row["valid_from"]
            first_new[code] = min(first_new.get(code, value), value)
        existing = self.warehouse.read_current(ResearchDatasetId.THEME_MEMBER)
        closures: list[dict[str, Any]] = []
        if not existing.empty:
            for row in existing.to_dict(orient="records"):
                code = str(row["theme_code"])
                boundary = first_new.get(code)
                valid_from = pd.Timestamp(row["valid_from"]).date()
                if boundary is None or valid_from >= boundary or pd.notna(row.get("valid_to")):
                    continue
                updated = {
                    key: value
                    for key, value in row.items()
                    if key not in {
                        "source_name", "source_endpoint", "source_record_id",
                        "source_updated_at", "available_at", "availability_precision",
                        "ingested_at", "ingestion_run_id", "payload_hash",
                        "business_key_hash", "quality_status", "revision_no",
                    }
                }
                updated["valid_from"] = valid_from
                updated["valid_to"] = boundary - timedelta(days=1)
                updated["available_at"] = _post_close_utc(boundary)
                closures.append(updated)
        return closures + new_rows

    def _sw_catalog_and_members(
        self,
        through: date,
    ) -> tuple[
        list[dict[str, Any]],
        list[dict[str, Any]],
        datetime,
    ]:
        sw_basic = self.client.call_paged("index_basic", market="SW")
        list_dates = {
            str(row["ts_code"]): _optional_date(row.get("list_date"))
            for row in sw_basic.to_dict(orient="records")
        }
        existing_catalog = self.warehouse.read_current(
            ResearchDatasetId.INDUSTRY_CATALOG,
            partition_value="SW2021",
        )
        catalog: list[dict[str, Any]] = []
        closures: list[dict[str, Any]] = []
        frames: dict[str, pd.DataFrame] = {}
        for level in ("L1", "L2", "L3"):
            frame = self.client.call("index_classify", level=level, src="SW2021")
            _require(
                frame,
                (
                    "index_code",
                    "industry_name",
                    "level",
                    "industry_code",
                    "is_pub",
                    "parent_code",
                    "src",
                ),
                "index_classify",
            )
            frames[level] = frame
            for row in frame.to_dict(orient="records"):
                index_code = str(row["index_code"])
                definition = {
                    "industry_system": str(row["src"]),
                    "level": str(row["level"]),
                    "industry_code": index_code,
                    "classification_code": str(row["industry_code"]),
                    "industry_name": str(row["industry_name"]),
                    "parent_code": str(row["parent_code"]),
                    "is_published": str(row["is_pub"]),
                }
                source_valid_from = list_dates.get(index_code)
                matching_valid_from = _matching_industry_valid_from(
                    existing_catalog,
                    definition,
                )
                identity_seen = _industry_identity_seen(
                    existing_catalog,
                    definition,
                )
                if matching_valid_from is not None:
                    valid_from = matching_valid_from
                elif identity_seen:
                    valid_from = through
                    closures.extend(
                        _close_conflicting_industry_definitions(
                            existing_catalog,
                            definition,
                            boundary=through,
                        )
                    )
                else:
                    valid_from = source_valid_from or through
                catalog.append(
                    {
                        **definition,
                        "valid_from": valid_from,
                        "valid_to": None,
                        "available_at": _post_close_utc(valid_from),
                    }
                )

        member_rows: list[dict[str, Any]] = []
        for l1_code in sorted(frames["L1"]["index_code"].astype(str).unique()):
            frame = self.client.call("index_member_all", l1_code=l1_code)
            _require(
                frame,
                (
                    "l1_code",
                    "l1_name",
                    "l2_code",
                    "l2_name",
                    "l3_code",
                    "l3_name",
                    "ts_code",
                    "name",
                    "in_date",
                    "out_date",
                    "is_new",
                ),
                "index_member_all",
            )
            for row in frame.to_dict(orient="records"):
                valid_from = _date(row["in_date"])
                valid_to = _optional_date(row.get("out_date"))
                for level in ("L1", "L2", "L3"):
                    code = row.get(f"{level.lower()}_code")
                    name = row.get(f"{level.lower()}_name")
                    if code is None or pd.isna(code):
                        continue
                    member_rows.append(
                        {
                            "ts_code": str(row["ts_code"]),
                            "security_name": str(row["name"]),
                            "industry_system": "SW2021",
                            "level": level,
                            "industry_code": str(code),
                            "industry_name": str(name),
                            "valid_from": valid_from,
                            "valid_to": valid_to,
                            "is_current": str(row["is_new"]) == "Y",
                            "available_at": _post_close_utc(valid_from),
                        }
                    )
        member_rows = _deduplicate_industry_member_source_rows(member_rows)
        observed_at = datetime.now(timezone.utc)
        existing_members = self.warehouse.read_current(
            ResearchDatasetId.INDUSTRY_MEMBER,
            partition_value="SW2021",
        )
        reconciled_members = _reconcile_industry_member_versions(
            existing_members,
            member_rows,
            observed_at=observed_at,
        )
        return closures + catalog, reconciled_members, observed_at

    def _theme_catalog(self, through: date) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for market in ("SSE", "SZSE"):
            frame = self.client.call_paged(
                "index_basic",
                market=market,
                category="主题指数",
            )
            _require(
                frame,
                (
                    "ts_code",
                    "name",
                    "market",
                    "publisher",
                    "category",
                    "base_date",
                    "base_point",
                    "list_date",
                ),
                "index_basic",
            )
            for row in frame.to_dict(orient="records"):
                if str(row.get("category")) != "主题指数":
                    continue
                valid_from = _date(row["list_date"])
                if valid_from > through:
                    continue
                records.append(
                    {
                        "publisher": str(row["publisher"]),
                        "publisher_market": market,
                        "theme_code": str(row["ts_code"]),
                        "theme_name": str(row["name"]),
                        "category": "主题指数",
                        "base_date": _optional_date(row.get("base_date")),
                        "base_point": _number(row.get("base_point")),
                        "valid_from": valid_from,
                        "valid_to": None,
                        "available_at": _post_close_utc(valid_from),
                    }
                )
        return records

    def _theme_members(
        self,
        codes: list[str],
        *,
        start: date,
        through: date,
        summary: BackfillSummary,
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        if codes:
            summary.limitations_checked = True
        for code in codes:
            frame = self.client.call_paged(
                "index_weight",
                index_code=code,
                start_date=_yyyymmdd(start),
                end_date=_yyyymmdd(through),
            )
            if frame.empty:
                summary.limited += 1
                summary.issues.append(
                    f"theme_member:{code}:source_unavailable"
                )
                continue
            _require(frame, ("index_code", "con_code", "trade_date", "weight"), "index_weight")
            frame = frame.copy()
            frame["effective_date"] = frame["trade_date"].map(_date)
            snapshot_dates = sorted(frame["effective_date"].unique())
            next_dates = {
                value: (snapshot_dates[index + 1] - timedelta(days=1))
                if index + 1 < len(snapshot_dates)
                else None
                for index, value in enumerate(snapshot_dates)
            }
            for row in frame.to_dict(orient="records"):
                valid_from = row["effective_date"]
                records.append(
                    {
                        "theme_code": code,
                        "ts_code": str(row["con_code"]),
                        "valid_from": valid_from,
                        "valid_to": next_dates[valid_from],
                        "weight": _number(row.get("weight")),
                        "snapshot_date": valid_from,
                        "available_at": _post_close_utc(valid_from),
                    }
                )
        frame = pd.DataFrame(records)
        if frame.empty:
            return []
        frame = frame.drop_duplicates(
            subset=["theme_code", "ts_code", "valid_from"], keep="last"
        )
        return frame.to_dict(orient="records")

    def _index_history(
        self,
        codes: list[str],
        *,
        start: date,
        through: date,
        code_field: str,
        summary: BackfillSummary,
        allowed_dates: set[date] | None,
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for code in codes:
            frame = self.client.call(
                "index_daily",
                ts_code=code,
                start_date=_yyyymmdd(start),
                end_date=_yyyymmdd(through),
            )
            if frame.empty:
                summary.waiting_upstream += 1
                continue
            _require(
                frame,
                (
                    "ts_code",
                    "trade_date",
                    "open",
                    "high",
                    "low",
                    "close",
                    "vol",
                    "amount",
                ),
                "index_daily",
            )
            for row in frame.to_dict(orient="records"):
                trade_date = _date(row["trade_date"])
                if allowed_dates is not None and trade_date not in allowed_dates:
                    continue
                records.append(
                    {
                        "trade_date": trade_date,
                        code_field: code,
                        "open": _number(row["open"]),
                        "high": _number(row["high"]),
                        "low": _number(row["low"]),
                        "close": _number(row["close"]),
                        "pre_close": _number(row.get("pre_close")),
                        "pct_chg": _number(row.get("pct_chg")),
                        "volume": _number(row["vol"], multiplier=100.0),
                        "amount": _number(row["amount"], multiplier=1_000.0),
                    }
                )
        return records

    def _commit_daily_groups(
        self,
        dataset: ResearchDatasetId,
        endpoint: str,
        records: list[dict[str, Any]],
        through: date,
        resume: bool,
        summary: BackfillSummary,
    ) -> None:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in records:
            prepared = dict(row)
            prepared["available_at"] = _post_close_utc(row["trade_date"])
            prepared["availability_precision"] = (
                AvailabilityPrecision.INFERRED_FROM_ENDPOINT_POLICY.value
            )
            grouped[str(row["trade_date"])].append(prepared)
        for partition, rows in sorted(grouped.items()):
            self._commit(dataset, partition, endpoint, rows, through, resume, summary)

    def _commit(
        self,
        dataset: ResearchDatasetId,
        partition: str,
        endpoint: str,
        records: list[dict[str, Any]],
        through: date,
        resume: bool,
        summary: BackfillSummary,
        *,
        ingested_at: datetime | None = None,
    ) -> None:
        if resume and self._complete(dataset, partition):
            summary.skipped += 1
            return
        if not records:
            summary.waiting_upstream += 1
            return
        self.warehouse.commit_batch(
            FactBatch(
                dataset_id=dataset,
                partition_value=partition,
                source_name="tushare",
                source_endpoint=endpoint,
                ingestion_run_id=f"classification:{dataset.value}:{partition}",
                ingested_at=ingested_at or datetime.now(timezone.utc),
                default_available_at=_post_close_utc(through),
                records=records,
            )
        )
        summary.committed += 1

    def _complete(self, dataset: ResearchDatasetId, partition: str) -> bool:
        frame = self.warehouse.partition_manifest(dataset)
        return not frame.empty and bool(
            (frame["partition_value"].astype(str) == partition).any()
        )

    def _daily_history_complete(
        self,
        dataset: ResearchDatasetId,
        trading_dates: tuple[date, ...],
    ) -> bool:
        if not trading_dates:
            return False
        manifest = self.warehouse.partition_manifest(dataset)
        if manifest.empty:
            return False
        completed = set(manifest["partition_value"].astype(str))
        expected = {value.isoformat() for value in trading_dates}
        return expected <= completed


def _matching_industry_valid_from(
    existing: pd.DataFrame,
    definition: dict[str, str],
) -> date | None:
    if existing.empty:
        return None
    starts: list[date] = []
    for row in existing.to_dict(orient="records"):
        if pd.notna(row.get("valid_to")):
            continue
        if any(str(row.get(field)) != value for field, value in definition.items()):
            continue
        starts.append(pd.Timestamp(row["valid_from"]).date())
    return min(starts) if starts else None


def _industry_identity_seen(
    existing: pd.DataFrame,
    definition: dict[str, str],
) -> bool:
    if existing.empty:
        return False
    identity_fields = ("industry_system", "level", "industry_code")
    return any(
        all(
            str(row.get(field)) == definition[field]
            for field in identity_fields
        )
        for row in existing.to_dict(orient="records")
    )


def _close_conflicting_industry_definitions(
    existing: pd.DataFrame,
    definition: dict[str, str],
    *,
    boundary: date,
) -> list[dict[str, Any]]:
    if existing.empty:
        return []
    identity_fields = ("industry_system", "level", "industry_code")
    closures: list[dict[str, Any]] = []
    for row in existing.to_dict(orient="records"):
        if any(
            str(row.get(field)) != definition[field]
            for field in identity_fields
        ):
            continue
        if pd.notna(row.get("valid_to")):
            continue
        valid_from = pd.Timestamp(row["valid_from"]).date()
        if valid_from >= boundary:
            continue
        closures.append(
            {
                field: str(row.get(field))
                for field in definition
            }
            | {
                "valid_from": valid_from,
                "valid_to": boundary - timedelta(days=1),
                "available_at": _post_close_utc(boundary),
            }
        )
    return closures


_INDUSTRY_MEMBER_SLOT = ("ts_code", "industry_system", "level")
_INDUSTRY_MEMBER_KEY = (*_INDUSTRY_MEMBER_SLOT, "valid_from")
_INDUSTRY_MEMBER_BUSINESS_FIELDS = (
    "ts_code",
    "security_name",
    "industry_system",
    "level",
    "industry_code",
    "industry_name",
    "valid_from",
    "valid_to",
    "is_current",
)


def _deduplicate_industry_member_source_rows(
    incoming: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Collapse only exact source duplicates and reject contradictory versions."""
    prepared: dict[tuple[str, str, str, date], dict[str, Any]] = {}
    signatures: dict[tuple[str, str, str, date], tuple[Any, ...]] = {}
    for source_row in incoming:
        row = dict(source_row)
        row["valid_from"] = _member_date(row["valid_from"])
        row["valid_to"] = _optional_member_date(row.get("valid_to"))
        key = _member_version_key(row)
        signature = _member_business_signature(row)
        if key in signatures and signatures[key] != signature:
            raise ValueError(
                f"conflicting industry member source rows for {key}"
            )
        signatures[key] = signature
        prepared[key] = row
    return list(prepared.values())


def _reconcile_industry_member_versions(
    existing: pd.DataFrame,
    incoming: list[dict[str, Any]],
    *,
    observed_at: datetime,
) -> list[dict[str, Any]]:
    """Close superseded membership slots without backdating local knowledge."""
    if observed_at.tzinfo is None:
        raise ValueError("industry member observation time must be timezone-aware")
    if not incoming:
        return incoming

    prepared: dict[tuple[str, str, str, date], dict[str, Any]] = {}
    incoming_by_slot: dict[tuple[str, str, str], list[dict[str, Any]]] = (
        defaultdict(list)
    )
    for source_row in incoming:
        row = dict(source_row)
        row["valid_from"] = _member_date(row["valid_from"])
        row["valid_to"] = _optional_member_date(row.get("valid_to"))
        key = _member_version_key(row)
        if key in prepared:
            raise ValueError(f"duplicate industry member version in source: {key}")
        prepared[key] = row
        incoming_by_slot[_member_slot(row)].append(row)

    existing_by_slot: dict[tuple[str, str, str], list[dict[str, Any]]] = (
        defaultdict(list)
    )
    for source_row in existing.to_dict(orient="records"):
        row = dict(source_row)
        row["valid_from"] = _member_date(row["valid_from"])
        row["valid_to"] = _optional_member_date(row.get("valid_to"))
        existing_by_slot[_member_slot(row)].append(row)

    for slot, source_rows in incoming_by_slot.items():
        states = sorted(
            existing_by_slot.get(slot, []),
            key=lambda row: row["valid_from"],
        )
        for row in sorted(source_rows, key=lambda item: item["valid_from"]):
            start = row["valid_from"]
            exact = [item for item in states if item["valid_from"] == start]
            if exact:
                if any(
                    any(
                        str(item.get(field)) != str(row.get(field))
                        for field in ("industry_code", "industry_name")
                    )
                    for item in exact
                ):
                    raise ValueError(
                        "industry member effective-date conflict for "
                        f"{slot}: {start}"
                    )
                if len(exact) != 1:
                    raise ValueError(
                        f"industry member slot has duplicate effective dates: {slot}"
                    )
                current = exact[0]
                if _member_business_signature(current) != (
                    _member_business_signature(row)
                ):
                    row["available_at"] = observed_at
                    row["availability_precision"] = (
                        AvailabilityPrecision.INGESTION_CUTOFF.value
                    )
                    state_index = next(
                        index
                        for index, item in enumerate(states)
                        if item is current
                    )
                    states[state_index] = row
                continue

            if not states:
                states.append(row)
                continue
            latest_start = max(item["valid_from"] for item in states)
            if start <= latest_start:
                raise ValueError(
                    "industry member effective-date conflict for "
                    f"{slot}: incoming {start} is not later than {latest_start}"
                )

            overlapping = [
                item
                for item in states
                if item["valid_from"] < start
                and (
                    item.get("valid_to") is None
                    or item["valid_to"] >= start
                )
            ]
            if len(overlapping) > 1:
                raise ValueError(
                    f"industry member slot already has overlapping predecessors: {slot}"
                )
            if overlapping:
                predecessor = overlapping[0]
                predecessor_key = _member_version_key(predecessor)
                closure = {
                    field: predecessor.get(field)
                    for field in _INDUSTRY_MEMBER_BUSINESS_FIELDS
                }
                closure["valid_from"] = predecessor["valid_from"]
                closure["valid_to"] = start - timedelta(days=1)
                closure["is_current"] = False
                closure["available_at"] = observed_at
                closure["availability_precision"] = (
                    AvailabilityPrecision.INGESTION_CUTOFF.value
                )
                prepared[predecessor_key] = closure
                predecessor["valid_to"] = closure["valid_to"]
                predecessor["is_current"] = False

            row["available_at"] = observed_at
            row["availability_precision"] = (
                AvailabilityPrecision.INGESTION_CUTOFF.value
            )
            states.append(row)

    return sorted(
        prepared.values(),
        key=lambda row: tuple(
            row[field] if field != "valid_from" else _member_date(row[field])
            for field in _INDUSTRY_MEMBER_KEY
        ),
    )


def _member_slot(row: dict[str, Any]) -> tuple[str, str, str]:
    return tuple(str(row[field]) for field in _INDUSTRY_MEMBER_SLOT)


def _member_version_key(row: dict[str, Any]) -> tuple[str, str, str, date]:
    slot = _member_slot(row)
    return (*slot, _member_date(row["valid_from"]))


def _member_business_signature(row: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(
        row.get(field) for field in _INDUSTRY_MEMBER_BUSINESS_FIELDS
    )


def _member_date(value: Any) -> date:
    return pd.Timestamp(value).date()


def _optional_member_date(value: Any) -> date | None:
    if value is None or pd.isna(value):
        return None
    return _member_date(value)


def _require(frame: pd.DataFrame, columns: tuple[str, ...], endpoint: str) -> None:
    missing = sorted(set(columns) - set(frame.columns))
    if missing:
        raise ResearchSourceError(
            f"Tushare {endpoint} missing columns: {', '.join(missing)}",
            category="schema",
            endpoint=endpoint,
        )


def _date(value: Any) -> date:
    return datetime.strptime(str(value).replace("-", ""), "%Y%m%d").date()


def _optional_date(value: Any) -> date | None:
    if value is None or pd.isna(value) or not str(value).strip():
        return None
    return _date(value)


def _number(value: Any, *, multiplier: float = 1.0) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value) * multiplier


def _yyyymmdd(value: date) -> str:
    return value.strftime("%Y%m%d")


def _post_close_utc(value: date) -> datetime:
    return datetime.combine(
        value, time(15, 1), tzinfo=ZoneInfo("Asia/Shanghai")
    ).astimezone(timezone.utc)


__all__ = ["ClassificationBackfillService"]
