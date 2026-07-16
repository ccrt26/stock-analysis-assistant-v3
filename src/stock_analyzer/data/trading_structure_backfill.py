from __future__ import annotations

import hashlib
import json
import time as system_time
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Callable, Iterable
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


class MinuteRequestPacer:
    def __init__(
        self,
        *,
        interval_seconds: float = 0.13,
        clock: Callable[[], float] = system_time.monotonic,
        sleeper: Callable[[float], None] = system_time.sleep,
    ) -> None:
        self.interval_seconds = interval_seconds
        self.clock = clock
        self.sleeper = sleeper
        self.last_call: float | None = None

    def __call__(self) -> None:
        now = self.clock()
        if self.last_call is not None:
            delay = self.last_call + self.interval_seconds - now
            if delay > 0:
                self.sleeper(delay)
                now = self.clock()
        self.last_call = now


class TradingStructureBackfillService:
    def __init__(
        self,
        client: TushareResearchClient,
        warehouse: ResearchWarehouse,
        *,
        minute_fetcher: Callable[..., pd.DataFrame],
        minute_pacer: Callable[[], None] | None = None,
    ) -> None:
        self.client = client
        self.warehouse = warehouse
        self.minute_fetcher = minute_fetcher
        self.minute_pacer = minute_pacer or MinuteRequestPacer()

    def backfill(
        self,
        *,
        trading_dates: Iterable[date],
        through: date,
        candidate_codes: tuple[str, ...],
        index_codes: tuple[str, ...],
        resume: bool = True,
    ) -> BackfillSummary:
        dates = tuple(sorted(set(trading_dates)))
        if not dates:
            raise ValueError("trading-structure backfill requires trading dates")
        margin_dates = dates[-250:]
        summary = BackfillSummary(
            scope="trading-structure", start=margin_dates[0], through=through
        )
        for trading_date in margin_dates:
            partition = trading_date.isoformat()
            if resume and self._complete(ResearchDatasetId.MARGIN_DETAIL, partition):
                summary.skipped += 1
                continue
            frame = self.client.call(
                "margin_detail", trade_date=_yyyymmdd(trading_date)
            )
            if frame.empty:
                summary.waiting_upstream += 1
                summary.issues.append(
                    f"margin_detail:{partition}:waiting_upstream"
                )
                continue
            required = (
                "trade_date",
                "ts_code",
                "rzye",
                "rqye",
                "rzmre",
                "rqyl",
                "rzche",
                "rqchl",
                "rqmcl",
                "rzrqye",
            )
            _require(frame, required, "margin_detail")
            rows = []
            for raw in frame.to_dict(orient="records"):
                row = _clean(raw)
                row["trade_date"] = _date(raw["trade_date"])
                row["exchange"] = _exchange(str(raw["ts_code"]))
                row["available_at"] = _next_morning(trading_date)
                row["availability_precision"] = (
                    AvailabilityPrecision.INFERRED_FROM_ENDPOINT_POLICY.value
                )
                rows.append(row)
            self._commit(
                ResearchDatasetId.MARGIN_DETAIL,
                partition,
                "margin_detail",
                rows,
                through,
            )
            summary.committed += 1

        codes = tuple(sorted(set(candidate_codes) | set(index_codes)))
        summary.limitations_checked = bool(codes)
        self._freeze_scope(through, candidate_codes, index_codes)
        minute_dates = margin_dates[-20:]
        existing_minute = self.warehouse.read_current(ResearchDatasetId.MINUTE_BAR)
        covered_pairs = _complete_minute_pairs(existing_minute)
        start_at = f"{minute_dates[0].isoformat()} 09:00:00"
        end_at = f"{minute_dates[-1].isoformat()} 15:30:00"
        index_set = set(index_codes)
        for code in codes:
            if resume and all((code, value) in covered_pairs for value in minute_dates):
                summary.skipped += 1
                continue
            self.minute_pacer()
            try:
                frame = self.minute_fetcher(
                    ts_code=code,
                    start_date=start_at,
                    end_date=end_at,
                    freq="1min",
                    asset="I" if code in index_set else "E",
                )
            except Exception as exc:
                category = _minute_failure_category(exc)
                if category == "access_or_rate_limit":
                    summary.limited += 1
                else:
                    summary.failed += 1
                summary.issues.append(f"minute_bar:{category}")
                break
            if not isinstance(frame, pd.DataFrame):
                summary.failed += 1
                summary.issues.append("minute_bar:invalid_response")
                break
            required = (
                "ts_code",
                "trade_time",
                "open",
                "high",
                "low",
                "close",
                "vol",
                "amount",
                "trade_date",
            )
            _require(frame, required, "pro_bar:1min")
            if frame.empty:
                summary.waiting_upstream += 1
                continue
            grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for raw in frame.to_dict(orient="records"):
                trading_date = _date(raw["trade_date"])
                minute = _minute_utc(raw["trade_time"])
                grouped[trading_date.isoformat()].append(
                    {
                        "trade_date": trading_date,
                        "instrument_code": code,
                        "instrument_type": "index" if code in index_set else "equity",
                        "minute": minute,
                        "frequency": "1min",
                        "open": _number(raw["open"]),
                        "high": _number(raw["high"]),
                        "low": _number(raw["low"]),
                        "close": _number(raw["close"]),
                        "volume": _number(raw["vol"]),
                        "amount": _number(raw["amount"]),
                        "available_at": _post_close(trading_date),
                        "availability_precision": (
                            AvailabilityPrecision.INFERRED_FROM_ENDPOINT_POLICY.value
                        ),
                    }
                )
            for partition, rows in sorted(grouped.items()):
                self._commit(
                    ResearchDatasetId.MINUTE_BAR,
                    partition,
                    "pro_bar:1min",
                    rows,
                    through,
                )
                summary.committed += 1
        return summary

    def frozen_scope_codes(self, analysis_date: date) -> tuple[str, ...]:
        with connect_research_warehouse(
            self.warehouse.duckdb_path, read_only=True
        ) as connection:
            row = connection.execute(
                """
                select codes_json from research_candidate_scopes
                where analysis_date = ? order by created_at desc limit 1
                """,
                [analysis_date],
            ).fetchone()
        if row is None:
            return ()
        payload = row[0]
        if isinstance(payload, str):
            payload = json.loads(payload)
        return tuple(payload["candidate_codes"])

    def _freeze_scope(
        self,
        through: date,
        candidate_codes: tuple[str, ...],
        index_codes: tuple[str, ...],
    ) -> None:
        payload = {
            "candidate_codes": sorted(set(candidate_codes)),
            "index_codes": sorted(set(index_codes)),
        }
        scope_id = hashlib.sha256(
            f"{through.isoformat()}|{json.dumps(payload, sort_keys=True)}".encode()
        ).hexdigest()
        with connect_research_warehouse(self.warehouse.duckdb_path) as connection:
            connection.execute(
                """
                insert into research_candidate_scopes
                (scope_id, analysis_date, formula_version, created_at,
                 codes_json, input_manifest_json)
                values (?, ?, 'frozen-explicit-v1', now(), ?, ?)
                on conflict(scope_id) do nothing
                """,
                [
                    scope_id,
                    through,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    json.dumps(
                        {
                            "selection": "explicit frozen scope; no future performance",
                            "created_for": "minute data coverage",
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                ],
            )

    def _commit(
        self,
        dataset: ResearchDatasetId,
        partition: str,
        endpoint: str,
        rows: list[dict[str, Any]],
        through: date,
    ) -> None:
        self.warehouse.commit_batch(
            FactBatch(
                dataset_id=dataset,
                partition_value=partition,
                source_name="tushare",
                source_endpoint=endpoint,
                ingestion_run_id=f"trading-structure:{dataset.value}:{partition}",
                ingested_at=datetime.now(timezone.utc),
                default_available_at=_post_close(through),
                records=rows,
            )
        )

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


def _clean(raw: dict[str, Any]) -> dict[str, Any]:
    result = {}
    for key, value in raw.items():
        if value is None or pd.isna(value):
            result[key] = None
        elif hasattr(value, "item"):
            result[key] = value.item()
        else:
            result[key] = value
    return result


def _exchange(ts_code: str) -> str:
    suffix = ts_code.rsplit(".", 1)[-1]
    return {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE"}.get(suffix, suffix)


def _minute_failure_category(exc: Exception) -> str:
    message = str(exc).lower()
    access_markers = (
        "权限",
        "频率",
        "积分",
        "permission",
        "rate",
        "次/天",
        "次/分钟",
    )
    if any(marker in message for marker in access_markers):
        return "access_or_rate_limit"
    return "provider_error"


def _complete_minute_pairs(frame: pd.DataFrame) -> set[tuple[str, date]]:
    if frame.empty or not {"instrument_code", "trade_date", "minute"} <= set(frame):
        return set()
    result: set[tuple[str, date]] = set()
    working = frame.copy()
    working["trade_date"] = pd.to_datetime(
        working["trade_date"], errors="coerce"
    ).dt.date
    working["minute"] = pd.to_datetime(working["minute"], utc=True, errors="coerce")
    for (code, trading_date), group in working.groupby(
        ["instrument_code", "trade_date"], dropna=True
    ):
        minutes = group["minute"].dropna()
        if len(minutes) < 200 or minutes.duplicated().any():
            continue
        local = minutes.dt.tz_convert("Asia/Shanghai")
        if local.min().time() <= time(9, 35) and local.max().time() >= time(14, 55):
            result.add((str(code), trading_date))
    return result


def _minute_utc(value: Any) -> datetime:
    timestamp = pd.Timestamp(str(value))
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("Asia/Shanghai")
    return timestamp.tz_convert("UTC").to_pydatetime()


def _date(value: Any) -> date:
    return datetime.strptime(str(value).replace("-", ""), "%Y%m%d").date()


def _yyyymmdd(value: date) -> str:
    return value.strftime("%Y%m%d")


def _number(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def _post_close(value: date) -> datetime:
    return datetime.combine(
        value, time(15, 1), tzinfo=ZoneInfo("Asia/Shanghai")
    ).astimezone(timezone.utc)


def _next_morning(value: date) -> datetime:
    return datetime.combine(
        value + timedelta(days=1), time(8, 0), tzinfo=ZoneInfo("Asia/Shanghai")
    ).astimezone(timezone.utc)


__all__ = ["MinuteRequestPacer", "TradingStructureBackfillService"]
