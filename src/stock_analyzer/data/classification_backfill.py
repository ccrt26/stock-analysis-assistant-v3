from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from stock_analyzer.data.research_backfill import BackfillSummary
from stock_analyzer.data.research_contracts import FactBatch, ResearchDatasetId
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
        history_start = self._latest_session_start(start, through, sessions=250)
        catalog, members = self._sw_catalog_and_members(through)
        self._commit(
            ResearchDatasetId.INDUSTRY_CATALOG,
            "SW2021",
            "index_classify+index_basic",
            catalog,
            through,
            resume,
            summary,
        )
        self._commit(
            ResearchDatasetId.INDUSTRY_MEMBER,
            "SW2021",
            "index_member_all",
            members,
            through,
            resume,
            summary,
        )

        industry_codes = sorted(
            {
                str(row["industry_code"])
                for row in catalog
                if str(row.get("is_published", "")) == "1"
            }
        )
        industry_bars = self._index_history(
            industry_codes,
            start=history_start,
            through=through,
            code_field="industry_code",
            summary=summary,
        )
        self._commit_daily_groups(
            ResearchDatasetId.INDUSTRY_DAILY,
            "index_daily",
            industry_bars,
            through,
            resume,
            summary,
        )

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
        theme_bars = self._index_history(
            theme_codes,
            start=history_start,
            through=through,
            code_field="theme_code",
            summary=summary,
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
        calendar = self.warehouse.read_current(ResearchDatasetId.TRADE_CALENDAR)
        if calendar.empty:
            return requested_start
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
            return requested_start
        return open_dates[-sessions]

    def refresh_daily(self, data_date: date) -> BackfillSummary:
        summary = BackfillSummary(
            scope="classification-daily", start=data_date, through=data_date
        )
        industry_catalog = self.warehouse.read_current(
            ResearchDatasetId.INDUSTRY_CATALOG
        )
        theme_catalog = self.warehouse.read_current(ResearchDatasetId.THEME_CATALOG)
        if industry_catalog.empty or theme_catalog.empty:
            return self.backfill(start=data_date, through=data_date, resume=True)
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
        industry_codes = set(industry_catalog["industry_code"].astype(str))
        theme_codes = set(theme_catalog["theme_code"].astype(str))
        industry_rows: list[dict[str, Any]] = []
        theme_rows: list[dict[str, Any]] = []
        for raw in frame.to_dict(orient="records"):
            code = str(raw["ts_code"])
            target: list[dict[str, Any]] | None = None
            code_field = ""
            if code in industry_codes:
                target = industry_rows
                code_field = "industry_code"
            elif code in theme_codes:
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
        self._commit(
            ResearchDatasetId.INDUSTRY_DAILY,
            partition,
            "index_daily",
            industry_rows,
            data_date,
            True,
            summary,
        )
        self._commit(
            ResearchDatasetId.THEME_DAILY,
            partition,
            "index_daily",
            theme_rows,
            data_date,
            True,
            summary,
        )
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
        catalog, members = self._sw_catalog_and_members(data_date)
        self._commit(
            ResearchDatasetId.INDUSTRY_CATALOG,
            "SW2021",
            "index_classify+index_basic",
            catalog,
            data_date,
            False,
            summary,
        )
        self._commit(
            ResearchDatasetId.INDUSTRY_MEMBER,
            "SW2021",
            "index_member_all",
            members,
            data_date,
            False,
            summary,
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
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        sw_basic = self.client.call_paged("index_basic", market="SW")
        list_dates = {
            str(row["ts_code"]): _optional_date(row.get("list_date"))
            for row in sw_basic.to_dict(orient="records")
        }
        catalog: list[dict[str, Any]] = []
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
                valid_from = list_dates.get(index_code) or through
                catalog.append(
                    {
                        "industry_system": str(row["src"]),
                        "level": str(row["level"]),
                        "industry_code": index_code,
                        "classification_code": str(row["industry_code"]),
                        "industry_name": str(row["industry_name"]),
                        "parent_code": str(row["parent_code"]),
                        "is_published": str(row["is_pub"]),
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
        member_frame = pd.DataFrame(member_rows)
        if not member_frame.empty:
            member_frame = member_frame.drop_duplicates(
                subset=["ts_code", "industry_system", "level", "valid_from"],
                keep="last",
            )
        return catalog, member_frame.to_dict(orient="records")

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
        for code in codes:
            frame = self.client.call_paged(
                "index_weight",
                index_code=code,
                start_date=_yyyymmdd(start),
                end_date=_yyyymmdd(through),
            )
            if frame.empty:
                summary.waiting_upstream += 1
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
            grouped[str(row["trade_date"])].append(row)
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
                ingested_at=datetime.now(timezone.utc),
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
