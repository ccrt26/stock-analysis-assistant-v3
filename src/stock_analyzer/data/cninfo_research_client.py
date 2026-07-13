from __future__ import annotations

import math
import re
import time as system_time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

from stock_analyzer.data.tushare_research_client import ResearchSourceError


_TITLE_TAG = re.compile(r"<[^>]+>")
_DENSE_DAY_PLATES = ("szmb", "szcy", "shmb", "shkcp", "bj")


class _PaginationTotalChanged(RuntimeError):
    def __init__(self, *, expected: int, actual: int, page: int) -> None:
        self.expected = expected
        self.actual = actual
        self.page = page
        super().__init__(
            f"pagination total changed from {expected} to {actual} at page {page}"
        )


class CninfoRequestPacer:
    def __init__(
        self,
        *,
        interval_seconds: float = 0.25,
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


class CninfoResearchClient:
    def __init__(
        self,
        http_client: Any,
        *,
        base_url: str = "https://www.cninfo.com.cn",
        page_size: int = 30,
        max_pages: int = 100,
        stock_batch_size: int = 50,
        timeout_seconds: float = 20.0,
        max_retries: int = 2,
        pacer: Callable[[], None] | None = None,
    ) -> None:
        if page_size <= 0 or max_pages <= 0 or stock_batch_size <= 0:
            raise ValueError("CNINFO pagination settings must be positive")
        self.http_client = http_client
        self.base_url = base_url.rstrip("/")
        self.page_size = page_size
        self.max_pages = max_pages
        self.stock_batch_size = stock_batch_size
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.pacer = pacer or CninfoRequestPacer()
        self._stock_map: list[tuple[str, str]] | None = None

    def fetch_announcements(self, start: date, through: date) -> list[dict[str, Any]]:
        records: dict[str, dict[str, Any]] = {}
        current = start
        while current <= through:
            rows = self._query_day(current)
            for raw in rows:
                normalized = self._normalize(raw, current)
                previous = records.get(normalized["announcement_id"])
                if previous is not None and previous != normalized:
                    conflicting_fields = sorted(
                        key
                        for key in set(previous) | set(normalized)
                        if previous.get(key) != normalized.get(key)
                    )
                    non_time_conflicts = set(conflicting_fields) - {
                        "announcement_time",
                        "available_at",
                    }
                    if non_time_conflicts:
                        raise ResearchSourceError(
                            f"CNINFO duplicate announcement id "
                            f"{normalized['announcement_id']} has conflicting fields: "
                            f"{','.join(conflicting_fields)}",
                            category="schema",
                            endpoint="new/hisAnnouncement/query",
                        )
                    if previous["announcement_time"] > normalized["announcement_time"]:
                        normalized = previous
                records[normalized["announcement_id"]] = normalized
            current += timedelta(days=1)
        return sorted(
            records.values(),
            key=lambda row: (row["announcement_time"], row["announcement_id"]),
        )

    def _query_day(self, value: date) -> list[dict[str, Any]]:
        first_page = self._query_page(value, 1, plate="", stock="")
        if math.ceil(first_page[1] / self.page_size) > self.max_pages:
            return self._query_split_day(value, expected_total=first_page[1])
        try:
            rows, _ = self._query_stable_scope(
                value, plate="", stock="", first_page=first_page
            )
        except _PaginationTotalChanged:
            return self._query_split_day(value, expected_total=None)
        return rows

    def _query_split_day(
        self, value: date, *, expected_total: int | None
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        split_total = 0
        for plate in _DENSE_DAY_PLATES:
            first_plate_page = self._query_page(value, 1, plate=plate, stock="")
            if math.ceil(first_plate_page[1] / self.page_size) > self.max_pages:
                plate_rows, plate_total = self._query_by_stock_batches(
                    value, plate=plate, expected_total=first_plate_page[1]
                )
            else:
                try:
                    plate_rows, plate_total = self._query_stable_scope(
                        value,
                        plate=plate,
                        stock="",
                        first_page=first_plate_page,
                    )
                except _PaginationTotalChanged:
                    plate_rows, plate_total = self._query_by_stock_batches(
                        value, plate=plate, expected_total=first_plate_page[1]
                    )
            rows.extend(plate_rows)
            split_total += plate_total
        announcement_ids = {
            str(row.get("announcementId", "")).strip() for row in rows
        }
        split_is_incomplete = (
            not all(announcement_ids) or len(announcement_ids) != split_total
        )
        conflicts_with_stable_global = expected_total is not None and (
            split_total != expected_total or len(announcement_ids) != expected_total
        )
        if split_is_incomplete or conflicts_with_stable_global:
            global_description = (
                str(expected_total) if expected_total is not None else "unstable"
            )
            raise ResearchSourceError(
                f"CNINFO {value.isoformat()} market plates returned "
                f"{len(announcement_ids)} unique rows and declared {split_total}, "
                f"but the global total was {global_description}",
                category="incomplete",
                endpoint="new/hisAnnouncement/query",
            )
        return rows

    def _query_by_stock_batches(
        self, value: date, *, plate: str, expected_total: int
    ) -> tuple[list[dict[str, Any]], int]:
        stocks = [
            f"{code},{org_id}"
            for code, org_id in self._load_stock_map()
            if _plate_for_code(code) == plate
        ]
        rows: list[dict[str, Any]] = []
        for offset in range(0, len(stocks), self.stock_batch_size):
            stock = ";".join(stocks[offset : offset + self.stock_batch_size])
            first_page = self._query_page(value, 1, plate=plate, stock=stock)
            try:
                batch_rows, _ = self._query_stable_scope(
                    value,
                    plate=plate,
                    stock=stock,
                    first_page=first_page,
                )
            except _PaginationTotalChanged as exc:
                raise ResearchSourceError(
                    f"CNINFO {value.isoformat()} plate={plate} stock batch "
                    f"changed total from {exc.expected} to {exc.actual} "
                    f"at page {exc.page}",
                    category="incomplete",
                    endpoint="new/hisAnnouncement/query",
                ) from exc
            rows.extend(batch_rows)
        announcement_ids = {
            str(row.get("announcementId", "")).strip() for row in rows
        }
        if not all(announcement_ids) or len(announcement_ids) != expected_total:
            raise ResearchSourceError(
                f"CNINFO {value.isoformat()} plate={plate} stock batches returned "
                f"{len(announcement_ids)} unique rows but declared {expected_total}",
                category="incomplete",
                endpoint="new/hisAnnouncement/query",
            )
        return rows, expected_total

    def _query_stable_scope(
        self,
        value: date,
        *,
        plate: str,
        stock: str,
        first_page: tuple[list[dict[str, Any]], int] | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        rows: list[dict[str, Any]] = []
        declared_total: int | None = None
        unique_total = 0
        for attempt in range(self.max_retries + 1):
            try:
                pass_rows, pass_total = self._query_pages_once(
                    value,
                    plate=plate,
                    stock=stock,
                    first_page=first_page if attempt == 0 else None,
                )
            except _PaginationTotalChanged as exc:
                if attempt < self.max_retries:
                    continue
                raise
            if declared_total is None:
                declared_total = pass_total
            elif pass_total != declared_total:
                raise ResearchSourceError(
                    "CNINFO pagination total changed during acquisition",
                    category="schema",
                    endpoint="new/hisAnnouncement/query",
                )
            rows.extend(pass_rows)
            announcement_ids = [
                str(row.get("announcementId", "")).strip() for row in rows
            ]
            unique_total = len(set(announcement_ids))
            if all(announcement_ids) and unique_total == declared_total:
                return rows, declared_total
            if unique_total > declared_total:
                raise ResearchSourceError(
                    "CNINFO returned more unique announcement IDs than declared",
                    category="incomplete",
                    endpoint="new/hisAnnouncement/query",
                )
        raise ResearchSourceError(
            f"CNINFO {value.isoformat()} plate={plate or 'all'} returned "
            f"{unique_total} unique rows "
            f"but declared {declared_total}",
            category="incomplete",
            endpoint="new/hisAnnouncement/query",
        )

    def _query_pages_once(
        self,
        value: date,
        *,
        plate: str,
        stock: str,
        first_page: tuple[list[dict[str, Any]], int] | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        first, total = first_page or self._query_page(
            value, 1, plate=plate, stock=stock
        )
        rows = list(first)
        pages = math.ceil(total / self.page_size)
        if pages > self.max_pages:
            raise ResearchSourceError(
                f"CNINFO plate={plate or 'all'} exceeds the pagination limit",
                category="incomplete",
                endpoint="new/hisAnnouncement/query",
            )
        for page in range(2, pages + 1):
            page_rows, page_total = self._query_page(
                value, page, plate=plate, stock=stock
            )
            if page_total != total:
                raise _PaginationTotalChanged(
                    expected=total, actual=page_total, page=page
                )
            rows.extend(page_rows)
        return rows, total

    def _query_page(
        self, value: date, page: int, *, plate: str, stock: str
    ) -> tuple[list[dict[str, Any]], int]:
        payload = self._post(
            {
                "pageNum": str(page),
                "pageSize": str(self.page_size),
                "column": "szse",
                "tabName": "fulltext",
                "plate": plate,
                "stock": stock,
                "searchkey": "",
                "secid": "",
                "category": "",
                "trade": "",
                "seDate": f"{value.isoformat()}~{value.isoformat()}",
                "sortName": "",
                "sortType": "",
                "isHLtitle": "true",
            }
        )
        if not isinstance(payload, dict):
            raise ResearchSourceError(
                "CNINFO response is not an object",
                category="schema",
                endpoint="new/hisAnnouncement/query",
            )
        raw_rows = payload.get("announcements")
        raw_total = payload.get("totalAnnouncement")
        try:
            total = int(raw_total)
        except (TypeError, ValueError) as exc:
            raise ResearchSourceError(
                "CNINFO totalAnnouncement is invalid",
                category="schema",
                endpoint="new/hisAnnouncement/query",
            ) from exc
        if total == 0 and raw_rows is None:
            raw_rows = []
        if not isinstance(raw_rows, list) or any(
            not isinstance(row, dict) for row in raw_rows
        ):
            raise ResearchSourceError(
                "CNINFO announcement rows are malformed",
                category="schema",
                endpoint="new/hisAnnouncement/query",
            )
        return list(raw_rows), total

    def _load_stock_map(self) -> list[tuple[str, str]]:
        if self._stock_map is not None:
            return self._stock_map
        payload = self._get_json("/new/data/szse_stock.json")
        raw_rows = payload.get("stockList") if isinstance(payload, dict) else None
        if not isinstance(raw_rows, list) or any(
            not isinstance(row, dict) for row in raw_rows
        ):
            raise ResearchSourceError(
                "CNINFO stock map is malformed",
                category="schema",
                endpoint="new/data/szse_stock.json",
            )
        stocks: dict[str, str] = {}
        for row in raw_rows:
            code = str(row.get("code", "")).strip().zfill(6)
            org_id = str(row.get("orgId", "")).strip()
            if len(code) != 6 or not code.isdigit() or not org_id:
                raise ResearchSourceError(
                    "CNINFO stock map contains an invalid code or orgId",
                    category="schema",
                    endpoint="new/data/szse_stock.json",
                )
            previous = stocks.get(code)
            if previous is not None and previous != org_id:
                raise ResearchSourceError(
                    f"CNINFO stock map contains conflicting orgId values for {code}",
                    category="schema",
                    endpoint="new/data/szse_stock.json",
                )
            stocks[code] = org_id
        if not stocks:
            raise ResearchSourceError(
                "CNINFO stock map is empty",
                category="incomplete",
                endpoint="new/data/szse_stock.json",
            )
        self._stock_map = sorted(stocks.items())
        return self._stock_map

    def _get_json(self, path: str) -> Any:
        url = f"{self.base_url}{path}"
        for attempt in range(self.max_retries + 1):
            self.pacer()
            try:
                response = self.http_client.get(url, timeout=self.timeout_seconds)
            except Exception as exc:
                if attempt < self.max_retries:
                    system_time.sleep(min(2**attempt, 5))
                    continue
                raise ResearchSourceError(
                    f"CNINFO transport failed: {type(exc).__name__}",
                    category="network",
                    endpoint=path.lstrip("/"),
                ) from exc
            status = getattr(response, "status_code", None)
            if status == 429 or (isinstance(status, int) and status >= 500):
                if attempt < self.max_retries:
                    system_time.sleep(min(2**attempt, 5))
                    continue
                raise ResearchSourceError(
                    f"CNINFO HTTP {status}",
                    category="rate_limited" if status == 429 else "network",
                    endpoint=path.lstrip("/"),
                )
            if status in {401, 403}:
                raise ResearchSourceError(
                    f"CNINFO HTTP {status}",
                    category="permission_denied",
                    endpoint=path.lstrip("/"),
                )
            if not isinstance(status, int) or status >= 400:
                raise ResearchSourceError(
                    f"CNINFO HTTP {status}",
                    category="schema",
                    endpoint=path.lstrip("/"),
                )
            try:
                return response.json()
            except Exception as exc:
                raise ResearchSourceError(
                    "CNINFO returned invalid JSON",
                    category="schema",
                    endpoint=path.lstrip("/"),
                ) from exc
        raise AssertionError("unreachable")

    def _post(self, data: dict[str, str]) -> Any:
        url = f"{self.base_url}/new/hisAnnouncement/query"
        for attempt in range(self.max_retries + 1):
            self.pacer()
            try:
                response = self.http_client.post(
                    url, data=data, timeout=self.timeout_seconds
                )
            except Exception as exc:
                if attempt < self.max_retries:
                    system_time.sleep(min(2**attempt, 5))
                    continue
                raise ResearchSourceError(
                    f"CNINFO transport failed: {type(exc).__name__}",
                    category="network",
                    endpoint="new/hisAnnouncement/query",
                ) from exc
            status = getattr(response, "status_code", None)
            if status == 429 or (isinstance(status, int) and status >= 500):
                if attempt < self.max_retries:
                    system_time.sleep(min(2**attempt, 5))
                    continue
                raise ResearchSourceError(
                    f"CNINFO HTTP {status}",
                    category="rate_limited" if status == 429 else "network",
                    endpoint="new/hisAnnouncement/query",
                )
            if status in {401, 403}:
                raise ResearchSourceError(
                    f"CNINFO HTTP {status}",
                    category="permission_denied",
                    endpoint="new/hisAnnouncement/query",
                )
            if not isinstance(status, int) or status >= 400:
                raise ResearchSourceError(
                    f"CNINFO HTTP {status}",
                    category="schema",
                    endpoint="new/hisAnnouncement/query",
                )
            try:
                return response.json()
            except Exception as exc:
                raise ResearchSourceError(
                    "CNINFO returned invalid JSON",
                    category="schema",
                    endpoint="new/hisAnnouncement/query",
                ) from exc
        raise AssertionError("unreachable")

    def _normalize(self, raw: dict[str, Any], requested_date: date) -> dict[str, Any]:
        announcement_id = str(raw.get("announcementId", "")).strip()
        title = _TITLE_TAG.sub("", str(raw.get("announcementTitle", ""))).strip()
        code = str(raw.get("secCode", "")).strip()
        pdf_path = str(raw.get("adjunctUrl", "")).strip()
        raw_time = raw.get("announcementTime")
        if (
            not announcement_id
            or not title
            or len(code) != 6
            or not code.isdigit()
            or not pdf_path
            or isinstance(raw_time, bool)
            or not isinstance(raw_time, (int, float))
        ):
            raise ResearchSourceError(
                "CNINFO announcement lacks stable id, code, title, PDF, or timestamp",
                category="schema",
                endpoint="new/hisAnnouncement/query",
            )
        published = datetime.fromtimestamp(
            int(raw_time) / 1000, tz=timezone.utc
        ).astimezone(ZoneInfo("Asia/Shanghai"))
        if published.date() != requested_date:
            raise ResearchSourceError(
                "CNINFO announcement falls outside requested day",
                category="invalid_semantics",
                endpoint="new/hisAnnouncement/query",
            )
        candidate_types = _candidate_event_types(title)
        return {
            "announcement_id": announcement_id,
            "ts_code": _ts_code(code),
            "security_name": str(raw.get("secName", "")).strip(),
            "announcement_time": published,
            "available_at": published,
            "title": title,
            "url": f"{self.base_url}/{pdf_path.lstrip('/')}",
            "pdf_path": pdf_path,
            "candidate_event_types": candidate_types,
            "classification_version": "cninfo-title-v1",
            "classification_is_fact": False,
            "hard_risk_candidate": bool(
                set(candidate_types)
                & {"investigation", "penalty", "delisting", "risk_warning"}
            ),
        }


def _candidate_event_types(title: str) -> list[str]:
    rules = (
        ("shareholder_reduction", ("减持",)),
        ("share_unlock", ("解除限售", "限售股上市流通", "解禁")),
        ("pledge", ("质押",)),
        ("repurchase", ("回购",)),
        ("investigation", ("立案", "调查通知书")),
        ("penalty", ("处罚", "监管措施")),
        ("inquiry", ("问询函", "关注函")),
        ("suspension", ("停牌", "复牌")),
        ("delisting", ("退市", "终止上市")),
        ("risk_warning", ("风险警示", "ST",)),
        ("restructuring", ("重大资产重组",)),
        ("major_contract", ("重大合同", "中标")),
    )
    return [name for name, words in rules if any(word in title for word in words)]


def _ts_code(code: str) -> str:
    if code.startswith(("4", "8", "92")):
        suffix = "BJ"
    elif code.startswith(("0", "2", "3")):
        suffix = "SZ"
    elif code.startswith(("5", "6", "9")):
        suffix = "SH"
    else:
        raise ResearchSourceError(
            f"CNINFO unrecognized security code: {code}",
            category="schema",
            endpoint="new/hisAnnouncement/query",
        )
    return f"{code}.{suffix}"


def _plate_for_code(code: str) -> str:
    if code.startswith(("300", "301", "302")):
        return "szcy"
    if code.startswith(("000", "001", "002", "003", "200", "201")):
        return "szmb"
    if code.startswith(("688", "689")):
        return "shkcp"
    if code.startswith(("600", "601", "603", "605", "900")):
        return "shmb"
    if code.startswith(("4", "8", "92")):
        return "bj"
    raise ResearchSourceError(
        f"CNINFO stock map contains an unrecognized security code: {code}",
        category="schema",
        endpoint="new/data/szse_stock.json",
    )


__all__ = ["CninfoRequestPacer", "CninfoResearchClient"]
