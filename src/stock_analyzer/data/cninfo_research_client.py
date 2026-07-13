from __future__ import annotations

import math
import re
import time as system_time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

from stock_analyzer.data.tushare_research_client import ResearchSourceError


_TITLE_TAG = re.compile(r"<[^>]+>")


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
        timeout_seconds: float = 20.0,
        max_retries: int = 2,
        pacer: Callable[[], None] | None = None,
    ) -> None:
        self.http_client = http_client
        self.base_url = base_url.rstrip("/")
        self.page_size = page_size
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.pacer = pacer or CninfoRequestPacer()

    def fetch_announcements(self, start: date, through: date) -> list[dict[str, Any]]:
        records: dict[str, dict[str, Any]] = {}
        current = start
        while current <= through:
            rows = self._query_day(current)
            for raw in rows:
                normalized = self._normalize(raw, current)
                previous = records.get(normalized["announcement_id"])
                if previous is not None and previous != normalized:
                    raise ResearchSourceError(
                        "CNINFO duplicate announcement id has conflicting content",
                        category="schema",
                        endpoint="new/hisAnnouncement/query",
                    )
                records[normalized["announcement_id"]] = normalized
            current += timedelta(days=1)
        return sorted(
            records.values(),
            key=lambda row: (row["announcement_time"], row["announcement_id"]),
        )
    def _query_day(self, value: date) -> list[dict[str, Any]]:
        first, total = self._query_page(value, 1)
        rows = list(first)
        pages = math.ceil(total / self.page_size)
        for page in range(2, pages + 1):
            page_rows, page_total = self._query_page(value, page)
            if page_total != total:
                raise ResearchSourceError(
                    "CNINFO pagination total changed during acquisition",
                    category="schema",
                    endpoint="new/hisAnnouncement/query",
                )
            rows.extend(page_rows)
        if len(rows) != total:
            raise ResearchSourceError(
                f"CNINFO returned {len(rows)} rows but declared {total}",
                category="incomplete",
                endpoint="new/hisAnnouncement/query",
            )
        return rows

    def _query_page(self, value: date, page: int) -> tuple[list[dict[str, Any]], int]:
        payload = self._post(
            {
                "pageNum": str(page),
                "pageSize": str(self.page_size),
                "column": "szse",
                "tabName": "fulltext",
                "plate": "",
                "stock": "",
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
    elif code.startswith(("0", "3")):
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


__all__ = ["CninfoRequestPacer", "CninfoResearchClient"]
