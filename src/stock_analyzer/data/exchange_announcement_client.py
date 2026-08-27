from __future__ import annotations

from datetime import date, datetime, timedelta
import hashlib
import math
import time as system_time
from typing import Any, Callable
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from stock_analyzer.data.cninfo_research_client import candidate_event_types
from stock_analyzer.data.tushare_research_client import ResearchSourceError


_SHANGHAI = ZoneInfo("Asia/Shanghai")
_SSE_ENDPOINT = "security/stock/queryCompanyBulletin.do"
_SZSE_ENDPOINT = "api/disc/announcement/annList"


class ExchangeAnnouncementClient:
    """Narrow metadata client for the two official exchange announcement APIs."""

    def __init__(
        self,
        http_client: Any,
        *,
        sse_base_url: str = "https://query.sse.com.cn",
        szse_base_url: str = "https://www.szse.cn",
        szse_static_base_url: str = "https://disc.static.szse.cn",
        sse_page_size: int = 100,
        szse_page_size: int = 50,
        max_pages: int = 200,
        timeout_seconds: float = 20.0,
        max_retries: int = 2,
        pacer: Callable[[str], None] | None = None,
    ) -> None:
        if sse_page_size <= 0 or szse_page_size <= 0 or max_pages <= 0:
            raise ValueError(
                "exchange announcement pagination settings must be positive"
            )
        self.http_client = http_client
        self.sse_base_url = sse_base_url.rstrip("/")
        self.szse_base_url = szse_base_url.rstrip("/")
        self.szse_static_base_url = szse_static_base_url.rstrip("/")
        self.sse_page_size = sse_page_size
        self.szse_page_size = szse_page_size
        self.max_pages = max_pages
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.pacer = pacer or (lambda source: None)

    def fetch_sse_announcements(
        self, start: date, through: date
    ) -> list[dict[str, Any]]:
        records: dict[str, dict[str, Any]] = {}
        current = start
        while current <= through:
            for raw in self._fetch_sse_day(current):
                row = self._normalize_sse(raw, current)
                source_id = row["source_record_id"]
                if source_id in records:
                    raise ResearchSourceError(
                        f"SSE duplicate official URL path: {source_id}",
                        category="incomplete",
                        endpoint=_SSE_ENDPOINT,
                    )
                records[source_id] = row
            current += timedelta(days=1)
        return sorted(
            records.values(),
            key=lambda row: (row["announcement_time"], row["announcement_id"]),
        )

    def fetch_szse_announcements(
        self, start: date, through: date
    ) -> list[dict[str, Any]]:
        records: dict[str, dict[str, Any]] = {}
        current = start
        while current <= through:
            for raw in self._fetch_szse_day(current):
                row = self._normalize_szse(raw, current)
                source_id = row["source_record_id"]
                if source_id in records:
                    raise ResearchSourceError(
                        f"SZSE duplicate annId: {source_id}",
                        category="incomplete",
                        endpoint=_SZSE_ENDPOINT,
                    )
                records[source_id] = row
            current += timedelta(days=1)
        return sorted(
            records.values(),
            key=lambda row: (row["announcement_time"], row["announcement_id"]),
        )

    def _fetch_sse_day(self, value: date) -> list[dict[str, Any]]:
        first = self._get_sse_page(value, 1)
        _, total, page_count, rows = self._parse_sse_page(first, page=1)
        expected_pages = math.ceil(total / self.sse_page_size) if total else 0
        if page_count != expected_pages or page_count > self.max_pages:
            raise ResearchSourceError(
                "SSE declared pageCount does not match total",
                category="incomplete",
                endpoint=_SSE_ENDPOINT,
            )
        if len(rows) != min(self.sse_page_size, total):
            raise ResearchSourceError(
                "SSE first page size does not match total",
                category="incomplete",
                endpoint=_SSE_ENDPOINT,
            )
        all_rows = list(rows)
        for page in range(2, page_count + 1):
            payload = self._get_sse_page(value, page)
            _, current_total, current_pages, current_rows = (
                self._parse_sse_page(payload, page=page)
            )
            if current_total != total or current_pages != page_count:
                raise ResearchSourceError(
                    "SSE pagination totals changed during acquisition",
                    category="incomplete",
                    endpoint=_SSE_ENDPOINT,
                )
            expected_rows = min(
                self.sse_page_size,
                total - (page - 1) * self.sse_page_size,
            )
            if len(current_rows) != expected_rows:
                raise ResearchSourceError(
                    f"SSE page {page} returned an unexpected row count",
                    category="incomplete",
                    endpoint=_SSE_ENDPOINT,
                )
            all_rows.extend(current_rows)
        if len(all_rows) != total:
            raise ResearchSourceError(
                f"SSE returned {len(all_rows)} rows but declared {total}",
                category="incomplete",
                endpoint=_SSE_ENDPOINT,
            )
        return all_rows

    def _get_sse_page(self, value: date, page: int) -> Any:
        return self._request_json(
            source="SSE",
            endpoint=_SSE_ENDPOINT,
            method="get",
            url=f"{self.sse_base_url}/{_SSE_ENDPOINT}",
            params={
                "isPagination": "true",
                "beginDate": value.isoformat(),
                "endDate": value.isoformat(),
                "securityType": "0101,120100,020100,020200,120200",
                "reportType": "ALL",
                "pageHelp.pageSize": str(self.sse_page_size),
                "pageHelp.cacheSize": "1",
                "pageHelp.pageNo": str(page),
                "pageHelp.beginPage": str(page),
                "pageHelp.endPage": str(page),
            },
            headers={
                "Referer": "https://www.sse.com.cn/",
                "User-Agent": "Mozilla/5.0",
            },
        )

    def _parse_sse_page(
        self, payload: Any, *, page: int
    ) -> tuple[dict[str, Any], int, int, list[dict[str, Any]]]:
        page_help = payload.get("pageHelp") if isinstance(payload, dict) else None
        if not isinstance(page_help, dict):
            raise ResearchSourceError(
                "SSE response lacks pageHelp",
                category="schema",
                endpoint=_SSE_ENDPOINT,
            )
        try:
            actual_page = int(page_help.get("pageNo"))
            total = int(page_help.get("total"))
            page_count = int(page_help.get("pageCount"))
        except (TypeError, ValueError) as exc:
            raise ResearchSourceError(
                "SSE pageHelp contains invalid pagination values",
                category="schema",
                endpoint=_SSE_ENDPOINT,
            ) from exc
        rows = page_help.get("data")
        if (
            actual_page != page
            or total < 0
            or page_count < 0
            or not isinstance(rows, list)
            or any(not isinstance(row, dict) for row in rows)
        ):
            raise ResearchSourceError(
                "SSE page metadata or rows are malformed",
                category="schema",
                endpoint=_SSE_ENDPOINT,
            )
        return page_help, total, page_count, rows

    def _fetch_szse_day(self, value: date) -> list[dict[str, Any]]:
        first = self._post_szse_page(value, 1)
        total, rows = self._parse_szse_page(first)
        page_count = math.ceil(total / self.szse_page_size) if total else 0
        if page_count > self.max_pages:
            raise ResearchSourceError(
                "SZSE declared total exceeds pagination limit",
                category="incomplete",
                endpoint=_SZSE_ENDPOINT,
            )
        all_rows = list(rows)
        for page in range(2, page_count + 1):
            current_total, current_rows = self._parse_szse_page(
                self._post_szse_page(value, page)
            )
            if current_total != total:
                raise ResearchSourceError(
                    "SZSE announceCount changed during acquisition",
                    category="incomplete",
                    endpoint=_SZSE_ENDPOINT,
                )
            all_rows.extend(current_rows)
        if len(all_rows) != total:
            raise ResearchSourceError(
                f"SZSE returned {len(all_rows)} rows but declared {total}",
                category="incomplete",
                endpoint=_SZSE_ENDPOINT,
            )
        return all_rows

    def _post_szse_page(self, value: date, page: int) -> Any:
        return self._request_json(
            source="SZSE",
            endpoint=_SZSE_ENDPOINT,
            method="post",
            url=f"{self.szse_base_url}/{_SZSE_ENDPOINT}",
            json={
                "seDate": [value.isoformat(), value.isoformat()],
                "channelCode": ["listedNotice_disc"],
                "pageSize": self.szse_page_size,
                "pageNum": page,
            },
            headers={
                "Referer": "https://www.szse.cn/",
                "User-Agent": "Mozilla/5.0",
            },
        )

    def _parse_szse_page(self, payload: Any) -> tuple[int, list[dict[str, Any]]]:
        if not isinstance(payload, dict):
            raise ResearchSourceError(
                "SZSE response is not an object",
                category="schema",
                endpoint=_SZSE_ENDPOINT,
            )
        try:
            total = int(payload.get("announceCount"))
        except (TypeError, ValueError) as exc:
            raise ResearchSourceError(
                "SZSE announceCount is invalid",
                category="schema",
                endpoint=_SZSE_ENDPOINT,
            ) from exc
        rows = payload.get("data")
        if (
            total < 0
            or not isinstance(rows, list)
            or any(not isinstance(row, dict) for row in rows)
        ):
            raise ResearchSourceError(
                "SZSE announcement rows are malformed",
                category="schema",
                endpoint=_SZSE_ENDPOINT,
            )
        return total, rows

    def _request_json(
        self,
        *,
        source: str,
        endpoint: str,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> Any:
        for attempt in range(self.max_retries + 1):
            self.pacer(source.lower())
            try:
                response = getattr(self.http_client, method)(
                    url, timeout=self.timeout_seconds, **kwargs
                )
            except Exception as exc:
                if attempt < self.max_retries:
                    system_time.sleep(min(2**attempt, 5))
                    continue
                raise ResearchSourceError(
                    f"{source} transport failed: {type(exc).__name__}",
                    category="network",
                    endpoint=endpoint,
                ) from exc
            status = getattr(response, "status_code", None)
            if status == 429 or (isinstance(status, int) and status >= 500):
                if attempt < self.max_retries:
                    system_time.sleep(min(2**attempt, 5))
                    continue
                raise ResearchSourceError(
                    f"{source} HTTP {status}",
                    category="rate_limited" if status == 429 else "network",
                    endpoint=endpoint,
                )
            if status in {401, 403}:
                raise ResearchSourceError(
                    f"{source} HTTP {status}",
                    category="permission_denied",
                    endpoint=endpoint,
                )
            if not isinstance(status, int) or status >= 400:
                raise ResearchSourceError(
                    f"{source} HTTP {status}",
                    category="schema",
                    endpoint=endpoint,
                )
            try:
                return response.json()
            except Exception as exc:
                raise ResearchSourceError(
                    f"{source} returned invalid JSON",
                    category="schema",
                    endpoint=endpoint,
                ) from exc
        raise AssertionError("unreachable")

    def _normalize_sse(
        self, raw: dict[str, Any], requested_date: date
    ) -> dict[str, Any]:
        code = str(raw.get("SECURITY_CODE", "")).strip()
        title = str(raw.get("TITLE", "")).strip()
        added = _parse_exchange_time(raw.get("ADDDATE"), "SSE", _SSE_ENDPOINT)
        display_date = str(raw.get("SSEDATE", "")).strip()
        raw_url = str(raw.get("URL", "")).strip()
        source_id = _official_url_path(raw_url)
        if (
            display_date != requested_date.isoformat()
            or not title
            or not source_id
            or not str(raw.get("BULLETIN_TYPE", "")).strip()
            or not str(raw.get("BULLETIN_HEADING", "")).strip()
        ):
            raise ResearchSourceError(
                "SSE announcement lacks required official metadata",
                category="schema",
                endpoint=_SSE_ENDPOINT,
            )
        types = candidate_event_types(title)
        return {
            "announcement_id": f"sse:{hashlib.sha256(source_id.encode()).hexdigest()}",
            "ts_code": _exchange_ts_code(code, "SH", _SSE_ENDPOINT),
            "security_name": str(raw.get("SECURITY_NAME", "")).strip(),
            "announcement_time": added,
            "available_at": added,
            "title": title,
            "url": (
                raw_url
                if raw_url.startswith("http")
                else f"https://www.sse.com.cn{raw_url}"
            ),
            "pdf_path": source_id,
            "source_name": "sse",
            "source_endpoint": _SSE_ENDPOINT,
            "source_record_id": source_id,
            "candidate_event_types": types,
            "classification_version": "official-title-v1",
            "classification_is_fact": False,
            "hard_risk_candidate": bool(
                set(types)
                & {"investigation", "penalty", "delisting", "risk_warning"}
            ),
        }

    def _normalize_szse(
        self, raw: dict[str, Any], requested_date: date
    ) -> dict[str, Any]:
        ann_id = str(raw.get("annId", "")).strip()
        row_id = str(raw.get("id", "")).strip()
        code = _single_text(raw.get("secCode"))
        name = _single_text(raw.get("secName"))
        title = str(raw.get("title", "")).strip()
        published = _parse_exchange_time(
            raw.get("publishTime"), "SZSE", _SZSE_ENDPOINT
        )
        attach_path = str(raw.get("attachPath", "")).strip()
        attach_format = str(raw.get("attachFormat", "")).strip()
        if (
            not ann_id
            or not row_id
            or not title
            or not attach_path
            or not attach_format
            or published.date() != requested_date
        ):
            raise ResearchSourceError(
                "SZSE announcement lacks required official metadata",
                category="schema",
                endpoint=_SZSE_ENDPOINT,
            )
        types = candidate_event_types(title)
        return {
            "announcement_id": f"szse:{ann_id}",
            "ts_code": _exchange_ts_code(code, "SZ", _SZSE_ENDPOINT),
            "security_name": name,
            "announcement_time": published,
            "available_at": published,
            "title": title,
            "url": f"{self.szse_static_base_url}/{attach_path.lstrip('/')}",
            "pdf_path": attach_path,
            "source_name": "szse",
            "source_endpoint": _SZSE_ENDPOINT,
            "source_record_id": ann_id,
            "candidate_event_types": types,
            "classification_version": "official-title-v1",
            "classification_is_fact": False,
            "hard_risk_candidate": bool(
                set(types)
                & {"investigation", "penalty", "delisting", "risk_warning"}
            ),
        }


def _parse_exchange_time(value: Any, source: str, endpoint: str) -> datetime:
    if not isinstance(value, str):
        raise ResearchSourceError(
            f"{source} announcement time is invalid",
            category="schema",
            endpoint=endpoint,
        )
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=_SHANGHAI
        )
    except ValueError as exc:
        raise ResearchSourceError(
            f"{source} announcement time is invalid",
            category="schema",
            endpoint=endpoint,
        ) from exc


def _official_url_path(value: str) -> str:
    parsed = urlparse(value)
    return parsed.path if parsed.scheme else value.split("?", 1)[0]


def _single_text(value: Any) -> str:
    if isinstance(value, list):
        if len(value) != 1:
            return ""
        value = value[0]
    return str(value or "").strip()


def _exchange_ts_code(code: str, suffix: str, endpoint: str) -> str:
    if len(code) != 6 or not code.isdigit():
        raise ResearchSourceError(
            "exchange announcement contains an invalid security code",
            category="schema",
            endpoint=endpoint,
        )
    return f"{code}.{suffix}"


__all__ = ["ExchangeAnnouncementClient"]
