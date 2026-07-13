from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Callable, Iterable
from datetime import date, datetime, time, timezone
import math
import time as system_time
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from stock_analyzer.data.research_contracts import FactBatch, ResearchDatasetId


class ResearchSourceError(RuntimeError):
    def __init__(self, message: str, *, category: str, endpoint: str) -> None:
        super().__init__(message)
        self.category = category
        self.endpoint = endpoint


class ResearchRequestPacer:
    def __init__(
        self,
        *,
        default_calls_per_minute: int = 180,
        method_limits: dict[str, int] | None = None,
        window_seconds: float = 60.0,
        clock: Callable[[], float] = system_time.monotonic,
        sleeper: Callable[[float], None] = system_time.sleep,
    ) -> None:
        self.default_limit = default_calls_per_minute
        self.method_limits = {"daily": 450, **(method_limits or {})}
        self.window_seconds = window_seconds
        self.clock = clock
        self.sleeper = sleeper
        self.calls: dict[str, deque[float]] = defaultdict(deque)

    def __call__(self, method: str) -> None:
        limit = self.method_limits.get(method, self.default_limit)
        queue = self.calls[method]
        now = self.clock()
        boundary = now - self.window_seconds
        while queue and queue[0] <= boundary:
            queue.popleft()
        if len(queue) >= limit:
            delay = max(0.0, queue[0] + self.window_seconds - now)
            if delay:
                self.sleeper(delay)
            now = self.clock()
            boundary = now - self.window_seconds
            while queue and queue[0] <= boundary:
                queue.popleft()
        queue.append(now)


class TushareResearchClient:
    def __init__(
        self,
        pro: object,
        *,
        pacer: Callable[[str], None] | None = None,
    ) -> None:
        self.pro = pro
        self.pacer = pacer or ResearchRequestPacer()

    def call(self, method: str, **kwargs: Any) -> pd.DataFrame:
        self.pacer(method)
        try:
            frame = getattr(self.pro, method)(**kwargs)
        except Exception as exc:
            message = str(exc)
            lowered = message.lower()
            if "权限" in message or "permission" in lowered or "积分" in message:
                category = "permission_denied"
            elif "频率" in message or "rate" in lowered or "每分钟" in message:
                category = "rate_limited"
            elif "timeout" in lowered or "connection" in lowered or "network" in lowered:
                category = "network"
            else:
                category = "provider_error"
            raise ResearchSourceError(
                f"Tushare {method} failed: {message}",
                category=category,
                endpoint=method,
            ) from exc
        if not isinstance(frame, pd.DataFrame):
            raise ResearchSourceError(
                f"Tushare {method} response is not a DataFrame",
                category="schema",
                endpoint=method,
            )
        return frame

    def call_paged(
        self,
        method: str,
        *,
        limit: int = 5000,
        max_pages: int = 100,
        **kwargs: Any,
    ) -> pd.DataFrame:
        frames: list[pd.DataFrame] = []
        seen_page_hashes: set[int] = set()
        for page in range(max_pages):
            frame = self.call(method, limit=limit, offset=page * limit, **kwargs)
            if frame.empty:
                break
            page_hash = int(pd.util.hash_pandas_object(frame, index=False).sum())
            if page_hash in seen_page_hashes:
                raise ResearchSourceError(
                    f"Tushare {method} repeated a pagination page",
                    category="schema",
                    endpoint=method,
                )
            seen_page_hashes.add(page_hash)
            frames.append(frame)
            if len(frame) < limit:
                break
        else:
            raise ResearchSourceError(
                f"Tushare {method} exceeded pagination safety limit",
                category="incomplete",
                endpoint=method,
            )
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True, sort=False)

    def fetch_trade_calendar(self, start: date, through: date) -> pd.DataFrame:
        frame = self.call(
            "trade_cal",
            exchange="SSE",
            start_date=_yyyymmdd(start),
            end_date=_yyyymmdd(through),
        )
        _require_columns(
            frame,
            ("exchange", "cal_date", "is_open", "pretrade_date"),
            "trade_cal",
        )
        result = frame.copy()
        result["cal_date"] = result["cal_date"].map(_parse_date)
        result["pretrade_date"] = result["pretrade_date"].map(_parse_optional_date)
        result["is_open"] = result["is_open"].astype(int).astype(bool)
        result["cal_year"] = result["cal_date"].map(lambda value: str(value.year))
        return result

    def fetch_security_master(self, snapshot_date: date) -> pd.DataFrame:
        frames: list[pd.DataFrame] = []
        fields = (
            "ts_code,symbol,name,area,industry,market,exchange,list_status,"
            "list_date,delist_date,is_hs"
        )
        for status in ("L", "D", "P"):
            frame = self.call(
                "stock_basic",
                exchange="",
                list_status=status,
                fields=fields,
            )
            _require_columns(
                frame,
                (
                    "ts_code",
                    "symbol",
                    "name",
                    "area",
                    "industry",
                    "market",
                    "exchange",
                    "list_status",
                    "list_date",
                    "delist_date",
                    "is_hs",
                ),
                "stock_basic",
            )
            frames.append(frame)
        result = pd.concat(frames, ignore_index=True, sort=False)
        if result.empty:
            raise ResearchSourceError(
                "Tushare stock_basic returned no securities",
                category="waiting_upstream",
                endpoint="stock_basic",
            )
        result = result.drop_duplicates(subset=["ts_code", "list_date"], keep="last")
        result["valid_from"] = result["list_date"].map(_parse_date)
        result["valid_to"] = result["delist_date"].map(_parse_optional_date)
        result["snapshot_date"] = snapshot_date
        return result

    def fetch_market_date(
        self,
        trade_date: date,
        *,
        run_id: str,
        datasets: Iterable[ResearchDatasetId] | None = None,
    ) -> tuple[FactBatch, ...]:
        requested = set(
            datasets
            or (
                ResearchDatasetId.EQUITY_DAILY,
                ResearchDatasetId.ADJ_FACTOR,
                ResearchDatasetId.DAILY_BASIC,
                ResearchDatasetId.STOCK_LIMIT,
            )
        )
        available_at = _post_close_utc(trade_date)
        ingested_at = datetime.now(timezone.utc)
        batches: list[FactBatch] = []
        partition = trade_date.isoformat()

        if ResearchDatasetId.EQUITY_DAILY in requested:
            frame = self.call("daily", trade_date=_yyyymmdd(trade_date))
            _require_columns(
                frame,
                (
                    "ts_code",
                    "trade_date",
                    "open",
                    "high",
                    "low",
                    "close",
                    "pre_close",
                    "change",
                    "pct_chg",
                    "vol",
                    "amount",
                ),
                "daily",
            )
            if frame.empty:
                raise ResearchSourceError(
                    f"Tushare daily is empty for {partition}",
                    category="waiting_upstream",
                    endpoint="daily",
                )
            records = []
            for row in frame.to_dict(orient="records"):
                if not _equity_code(row["ts_code"]):
                    continue
                records.append(
                    {
                        "trade_date": _parse_date(row["trade_date"]),
                        "ts_code": str(row["ts_code"]),
                        "open": _number(row["open"]),
                        "high": _number(row["high"]),
                        "low": _number(row["low"]),
                        "close": _number(row["close"]),
                        "pre_close": _number(row["pre_close"]),
                        "change": _number(row["change"]),
                        "pct_chg": _number(row["pct_chg"]),
                        "volume": _number(row["vol"], multiplier=100.0),
                        "amount": _number(row["amount"], multiplier=1_000.0),
                    }
                )
            batches.append(
                _batch(
                    ResearchDatasetId.EQUITY_DAILY,
                    partition,
                    "daily",
                    run_id,
                    ingested_at,
                    available_at,
                    records,
                )
            )

        if ResearchDatasetId.ADJ_FACTOR in requested:
            frame = self.call("adj_factor", trade_date=_yyyymmdd(trade_date))
            _require_columns(frame, ("ts_code", "trade_date", "adj_factor"), "adj_factor")
            records = [
                {
                    "trade_date": _parse_date(row["trade_date"]),
                    "ts_code": str(row["ts_code"]),
                    "adj_factor": _number(row["adj_factor"]),
                }
                for row in frame.to_dict(orient="records")
                if _equity_code(row["ts_code"])
            ]
            batches.append(
                _batch(ResearchDatasetId.ADJ_FACTOR, partition, "adj_factor", run_id, ingested_at, available_at, records)
            )

        if ResearchDatasetId.DAILY_BASIC in requested:
            frame = self.call("daily_basic", trade_date=_yyyymmdd(trade_date))
            required = (
                "ts_code", "trade_date", "close", "turnover_rate", "turnover_rate_f",
                "volume_ratio", "pe", "pe_ttm", "pb", "ps", "ps_ttm", "dv_ratio",
                "dv_ttm", "total_share", "float_share", "free_share", "total_mv", "circ_mv"
            )
            _require_columns(frame, required, "daily_basic")
            records = []
            for row in frame.to_dict(orient="records"):
                if not _equity_code(row["ts_code"]):
                    continue
                record = {key: _number(row.get(key)) for key in required if key not in {"ts_code", "trade_date"}}
                for field in ("total_share", "float_share", "free_share", "total_mv", "circ_mv"):
                    record[field] = _number(row.get(field), multiplier=10_000.0)
                record.update(
                    {"trade_date": _parse_date(row["trade_date"]), "ts_code": str(row["ts_code"])}
                )
                records.append(record)
            batches.append(
                _batch(ResearchDatasetId.DAILY_BASIC, partition, "daily_basic", run_id, ingested_at, available_at, records)
            )

        if ResearchDatasetId.STOCK_LIMIT in requested:
            frame = self.call("stk_limit", trade_date=_yyyymmdd(trade_date))
            _require_columns(frame, ("trade_date", "ts_code", "up_limit", "down_limit"), "stk_limit")
            records = [
                {
                    "trade_date": _parse_date(row["trade_date"]),
                    "ts_code": str(row["ts_code"]),
                    "up_limit": _number(row["up_limit"]),
                    "down_limit": _number(row["down_limit"]),
                }
                for row in frame.to_dict(orient="records")
                if _equity_code(row["ts_code"])
            ]
            batches.append(
                _batch(ResearchDatasetId.STOCK_LIMIT, partition, "stk_limit", run_id, ingested_at, available_at, records)
            )
        return tuple(batches)


def _batch(
    dataset: ResearchDatasetId,
    partition: str,
    endpoint: str,
    run_id: str,
    ingested_at: datetime,
    available_at: datetime,
    records: list[dict[str, Any]],
) -> FactBatch:
    return FactBatch(
        dataset_id=dataset,
        partition_value=partition,
        source_name="tushare",
        source_endpoint=endpoint,
        ingestion_run_id=run_id,
        ingested_at=ingested_at,
        default_available_at=available_at,
        records=records,
    )


def _require_columns(frame: pd.DataFrame, required: Iterable[str], endpoint: str) -> None:
    missing = sorted(set(required) - set(frame.columns))
    if missing:
        raise ResearchSourceError(
            f"Tushare {endpoint} missing columns: {', '.join(missing)}",
            category="schema",
            endpoint=endpoint,
        )


def _number(value: Any, *, multiplier: float = 1.0) -> float | None:
    if value is None or pd.isna(value):
        return None
    number = float(value) * multiplier
    if not math.isfinite(number):
        return None
    return number


def _parse_date(value: Any) -> date:
    text = str(value).strip().replace("-", "")
    return datetime.strptime(text, "%Y%m%d").date()


def _parse_optional_date(value: Any) -> date | None:
    if value is None or pd.isna(value) or not str(value).strip():
        return None
    return _parse_date(value)


def _equity_code(value: Any) -> bool:
    text = str(value)
    return len(text) == 9 and text[-3:] in {".SH", ".SZ", ".BJ"} and text[:6].isdigit()


def _yyyymmdd(value: date) -> str:
    return value.strftime("%Y%m%d")


def _post_close_utc(value: date) -> datetime:
    local = datetime.combine(value, time(15, 1), tzinfo=ZoneInfo("Asia/Shanghai"))
    return local.astimezone(timezone.utc)


__all__ = [
    "ResearchRequestPacer",
    "ResearchSourceError",
    "TushareResearchClient",
]
