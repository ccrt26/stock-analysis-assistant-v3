from __future__ import annotations

from collections import deque
from collections.abc import Callable
from datetime import date, datetime, time, timezone
import hashlib
import json
import math
import time as system_time
from typing import Any

from stock_analyzer.data.acquisition import (
    PermanentRouteFailure,
    TransientRouteFailure,
)
from stock_analyzer.data.formal_contracts import build_target_contracts
from stock_analyzer.data.formal_policy import (
    CNINFO_DEFAULT_CALLS_PER_MINUTE,
    CNINFO_DEFAULT_MAX_RETRIES,
    CNINFO_DEFAULT_TIMEOUT_SECONDS,
    CNINFO_RATE_LIMIT_WINDOW_SECONDS,
)
from stock_analyzer.data.formal_routes import EndpointResponse
from stock_analyzer.data.readiness import (
    AcquisitionGroupId,
    AcquisitionRequest,
    FailureClassification,
)


_PAGE_SIZE = 30
_STOCK_MAP_PATH = "/new/data/szse_stock.json"
_DISCLOSURE_PATH = "/new/hisAnnouncement/query"
_PROBE_CODE_LIMIT = 20
_CATEGORY_SPECS = (
    ("", "company_announcement", False),
    ("category_fxts_szsh", "risk_warning", True),
    ("category_tbclts_szsh", "special_treatment_or_delisting", True),
    ("category_tszlq_szsh", "delisting_period", True),
)


class CninfoRequestPacer:
    def __init__(
        self,
        *,
        calls_per_minute: int = CNINFO_DEFAULT_CALLS_PER_MINUTE,
        window_seconds: float = CNINFO_RATE_LIMIT_WINDOW_SECONDS,
        clock: Callable[[], float] = system_time.monotonic,
        sleeper: Callable[[float], None] = system_time.sleep,
    ) -> None:
        self.calls_per_minute = calls_per_minute
        self.window_seconds = window_seconds
        self.clock = clock
        self.sleeper = sleeper
        self._calls: deque[float] = deque()

    def wait(self) -> None:
        now = self.clock()
        self._discard_expired(now)
        if len(self._calls) >= self.calls_per_minute:
            delay = max(0.0, self._calls[0] + self.window_seconds - now)
            if delay:
                self.sleeper(delay)
            now = self.clock()
            self._discard_expired(now)
        self._calls.append(now)

    def cool_down(self) -> None:
        now = self.clock()
        delay = self.window_seconds
        if self._calls:
            delay = max(delay, self._calls[-1] + self.window_seconds - now)
        self.sleeper(delay)
        self._calls.clear()

    def _discard_expired(self, now: float) -> None:
        boundary = now - self.window_seconds
        while self._calls and self._calls[0] <= boundary:
            self._calls.popleft()


class CninfoDisclosureClient:
    def __init__(
        self,
        status_client: Any,
        http_client: Any,
        *,
        base_url: str = "https://www.cninfo.com.cn",
        calls_per_minute: int = CNINFO_DEFAULT_CALLS_PER_MINUTE,
        timeout_seconds: float = CNINFO_DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = CNINFO_DEFAULT_MAX_RETRIES,
        request_pacer: CninfoRequestPacer | None = None,
    ) -> None:
        self.status_client = status_client
        self.http_client = http_client
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.request_pacer = request_pacer or CninfoRequestPacer(
            calls_per_minute=calls_per_minute
        )

    def fetch_official_events_risk(
        self,
        request: AcquisitionRequest,
    ) -> EndpointResponse:
        status = EndpointResponse.model_validate(
            self.status_client.fetch_official_status_risk(request)
        )
        expected_codes = tuple(sorted(request.target_codes))
        if not status.coverage_proven or tuple(sorted(status.coverage_codes)) != expected_codes:
            raise PermanentRouteFailure(
                "CNINFO backup status component lacks complete target coverage",
                FailureClassification.INCOMPLETE_UNIVERSE,
            )
        if not status.covered_dates or max(status.covered_dates) != request.trade_date:
            raise PermanentRouteFailure(
                "CNINFO backup status component is stale",
                FailureClassification.STALE_DATA,
            )
        window_start = min(status.covered_dates)
        stock_map = self._load_stock_map()
        records_by_id: dict[str, dict[str, Any]] = {}
        publication_times = dict(status.publication_times)
        for code in expected_codes:
            bare_code = _bare_code(code)
            org_id = stock_map.get(bare_code)
            for category, event_type, hard_risk in _CATEGORY_SPECS:
                rows = self._query_pages(
                    code=bare_code,
                    org_id=org_id or "",
                    searchkey="" if org_id else bare_code,
                    category=category,
                    start_date=window_start,
                    end_date=request.trade_date,
                )
                for raw in rows:
                    normalized = self._normalize_announcement(
                        raw,
                        expected_code=bare_code,
                        start_date=window_start,
                        request=request,
                        event_type=event_type,
                        hard_risk=hard_risk,
                    )
                    if normalized is None:
                        continue
                    event_id = normalized["event_id"]
                    existing = records_by_id.get(event_id)
                    if existing is None:
                        records_by_id[event_id] = normalized
                    else:
                        _merge_duplicate(existing, normalized)
                    publication_times[event_id] = records_by_id[event_id][
                        "publication_time"
                    ]
        disclosures = tuple(
            sorted(
                records_by_id.values(),
                key=lambda row: (row["publication_time"], row["event_id"]),
            )
        )
        sources = tuple(dict.fromkeys((*status.source_names, "cninfo.raw.disclosure")))
        return EndpointResponse(
            records=tuple(status.records) + disclosures,
            covered_dates=status.covered_dates,
            coverage_codes=expected_codes,
            coverage_proven=True,
            field_coverage=_field_coverage(request),
            source_names=sources,
            publication_times=publication_times,
        )

    def verify_event_semantics(
        self,
        request: AcquisitionRequest,
    ) -> dict[str, str]:
        stock_map = self._load_stock_map()
        populated_rows, _ = self._query_page(
            code="",
            org_id="",
            searchkey="",
            category="",
            start_date=request.trade_date,
            end_date=request.trade_date,
            page_number=1,
        )
        populated_fact: dict[str, Any] | None = None
        for raw in populated_rows:
            raw_code = str(raw.get("secCode", "")).strip()
            if raw_code not in stock_map:
                continue
            published_at = _raw_publication_time(
                raw.get("announcementTime"),
                request,
            )
            if published_at.date() != request.trade_date or published_at.time() == time.min:
                continue
            event_id = str(raw.get("announcementId", "")).strip()
            if not event_id:
                continue
            populated_fact = {
                "probe": "populated_precise_time",
                "ts_code": raw_code,
                "event_id": event_id,
                "publication_time": published_at.isoformat(),
            }
            break
        if populated_fact is None:
            raise PermanentRouteFailure(
                "CNINFO did not prove a populated non-midnight millisecond timestamp",
                FailureClassification.INVALID_SEMANTICS,
            )

        empty_fact: dict[str, Any] | None = None
        for code in sorted(stock_map)[:_PROBE_CODE_LIMIT]:
            rows = self._query_pages(
                code=code,
                org_id=stock_map[code],
                searchkey="",
                category="",
                start_date=request.trade_date,
                end_date=request.trade_date,
            )
            if not rows:
                empty_fact = {
                    "probe": "empty_coverage",
                    "ts_code": code,
                    "trade_date": request.trade_date.isoformat(),
                }
                break
        if empty_fact is None:
            raise PermanentRouteFailure(
                "CNINFO did not prove a valid-code empty disclosure window",
                FailureClassification.INVALID_SEMANTICS,
            )
        return {
            "populated_precise_time": _semantic_hash(populated_fact),
            "empty_coverage": _semantic_hash(empty_fact),
        }

    def _load_stock_map(self) -> dict[str, str]:
        payload = self._request_json("GET", _STOCK_MAP_PATH)
        rows = payload.get("stockList") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise PermanentRouteFailure(
                "CNINFO stock map response is malformed",
                FailureClassification.SCHEMA,
            )
        result: dict[str, str] = {}
        for row in rows:
            if not isinstance(row, dict):
                raise PermanentRouteFailure(
                    "CNINFO stock map contains a malformed row",
                    FailureClassification.SCHEMA,
                )
            code = str(row.get("code", "")).strip()
            org_id = str(row.get("orgId", "")).strip()
            if len(code) != 6 or not code.isdigit() or not org_id:
                raise PermanentRouteFailure(
                    "CNINFO stock map contains an invalid code or orgId",
                    FailureClassification.SCHEMA,
                )
            previous = result.get(code)
            if previous is not None and previous != org_id:
                raise PermanentRouteFailure(
                    f"CNINFO stock map contains conflicting orgId values for {code}",
                    FailureClassification.SCHEMA,
                )
            result[code] = org_id
        if not result:
            raise PermanentRouteFailure(
                "CNINFO stock map is empty",
                FailureClassification.INCOMPLETE_UNIVERSE,
            )
        return result

    def _query_pages(
        self,
        *,
        code: str,
        org_id: str,
        searchkey: str,
        category: str,
        start_date: date,
        end_date: date,
    ) -> list[dict[str, Any]]:
        first_rows, total = self._query_page(
            code=code,
            org_id=org_id,
            searchkey=searchkey,
            category=category,
            start_date=start_date,
            end_date=end_date,
            page_number=1,
        )
        rows = list(first_rows)
        page_count = math.ceil(total / _PAGE_SIZE)
        for page_number in range(2, page_count + 1):
            page_rows, page_total = self._query_page(
                code=code,
                org_id=org_id,
                searchkey=searchkey,
                category=category,
                start_date=start_date,
                end_date=end_date,
                page_number=page_number,
            )
            if page_total != total:
                raise PermanentRouteFailure(
                    "CNINFO pagination total changed during acquisition",
                    FailureClassification.SCHEMA,
                )
            rows.extend(page_rows)
        if len(rows) != total:
            raise PermanentRouteFailure(
                "CNINFO pagination did not return the declared total",
                FailureClassification.INCOMPLETE_UNIVERSE,
            )
        return rows

    def _query_page(
        self,
        *,
        code: str,
        org_id: str,
        searchkey: str,
        category: str,
        start_date: date,
        end_date: date,
        page_number: int,
    ) -> tuple[list[dict[str, Any]], int]:
        stock = f"{code},{org_id}" if code and org_id else ""
        payload = self._request_json(
            "POST",
            _DISCLOSURE_PATH,
            data={
                "pageNum": str(page_number),
                "pageSize": str(_PAGE_SIZE),
                "column": "szse",
                "tabName": "fulltext",
                "plate": "",
                "stock": stock,
                "searchkey": searchkey,
                "secid": "",
                "category": category,
                "trade": "",
                "seDate": f"{start_date.isoformat()}~{end_date.isoformat()}",
                "sortName": "",
                "sortType": "",
                "isHLtitle": "true",
            },
        )
        if not isinstance(payload, dict):
            raise PermanentRouteFailure(
                "CNINFO disclosure response is not an object",
                FailureClassification.SCHEMA,
            )
        raw_total = payload.get("totalAnnouncement")
        raw_rows = payload.get("announcements")
        if isinstance(raw_total, bool):
            raw_total = None
        try:
            total = int(raw_total)
        except (TypeError, ValueError) as exc:
            raise PermanentRouteFailure(
                "CNINFO disclosure total is invalid",
                FailureClassification.SCHEMA,
            ) from exc
        if total == 0 and raw_rows is None:
            raw_rows = []
        if total < 0 or not isinstance(raw_rows, list):
            raise PermanentRouteFailure(
                "CNINFO disclosure rows are malformed",
                FailureClassification.SCHEMA,
            )
        if any(not isinstance(row, dict) for row in raw_rows):
            raise PermanentRouteFailure(
                "CNINFO disclosure contains a malformed row",
                FailureClassification.SCHEMA,
            )
        if total == 0 and raw_rows:
            raise PermanentRouteFailure(
                "CNINFO empty total conflicts with returned rows",
                FailureClassification.SCHEMA,
            )
        return list(raw_rows), total

    def _normalize_announcement(
        self,
        raw: dict[str, Any],
        *,
        expected_code: str,
        start_date: date,
        request: AcquisitionRequest,
        event_type: str,
        hard_risk: bool,
    ) -> dict[str, Any] | None:
        code = str(raw.get("secCode", "")).strip()
        if code != expected_code:
            raise PermanentRouteFailure(
                "CNINFO disclosure returned the wrong security code",
                FailureClassification.SCHEMA,
            )
        event_id = str(raw.get("announcementId", "")).strip()
        title = str(raw.get("announcementTitle", "")).strip()
        pdf_path = str(raw.get("adjunctUrl", "")).strip()
        if not event_id or not title or not pdf_path:
            raise PermanentRouteFailure(
                "CNINFO disclosure lacks stable identity, title, or PDF path",
                FailureClassification.SCHEMA,
            )
        published_at = _raw_publication_time(raw.get("announcementTime"), request)
        if not start_date <= published_at.date() <= request.trade_date:
            raise PermanentRouteFailure(
                "CNINFO disclosure falls outside the requested date window",
                FailureClassification.INVALID_SEMANTICS,
            )
        if published_at > request.report_cutoff:
            return None
        return {
            "record_type": "official_event",
            "trade_date": request.trade_date,
            "ts_code": _to_ts_code(code),
            "event_id": event_id,
            "event_type": event_type,
            "title": title,
            "publication_time": published_at,
            "source_reliability": "official_provider",
            "is_new_information": True,
            "hard_risk": hard_risk,
            "source_name": "cninfo.raw.disclosure",
            "source_url": (
                f"{self.base_url}/new/disclosure/detail?announcementId={event_id}"
            ),
            "pdf_path": pdf_path,
        }

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        data: dict[str, str] | None = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        for attempt in range(self.max_retries + 1):
            self.request_pacer.wait()
            try:
                response = (
                    self.http_client.get(url, timeout=self.timeout_seconds)
                    if method == "GET"
                    else self.http_client.post(
                        url,
                        data=data,
                        timeout=self.timeout_seconds,
                    )
                )
            except Exception as exc:
                if attempt < self.max_retries:
                    self.request_pacer.cool_down()
                    continue
                raise TransientRouteFailure(
                    f"CNINFO {method} transport failed: {type(exc).__name__}",
                    FailureClassification.TRANSPORT,
                ) from exc
            status_code = getattr(response, "status_code", None)
            if status_code == 429 or (
                isinstance(status_code, int) and status_code >= 500
            ):
                if attempt < self.max_retries:
                    self.request_pacer.cool_down()
                    continue
                classification = (
                    FailureClassification.RATE_LIMIT
                    if status_code == 429
                    else FailureClassification.TRANSPORT
                )
                raise TransientRouteFailure(
                    f"CNINFO {method} failed with HTTP {status_code}",
                    classification,
                )
            if status_code in {401, 403}:
                raise PermanentRouteFailure(
                    f"CNINFO {method} permission denied",
                    FailureClassification.PERMISSION,
                )
            if not isinstance(status_code, int) or status_code >= 400:
                raise PermanentRouteFailure(
                    f"CNINFO {method} failed with HTTP {status_code}",
                    FailureClassification.SCHEMA,
                )
            try:
                return response.json()
            except Exception as exc:
                raise PermanentRouteFailure(
                    f"CNINFO {method} returned invalid JSON",
                    FailureClassification.SCHEMA,
                ) from exc
        raise AssertionError("unreachable")


def _field_coverage(request: AcquisitionRequest) -> dict[str, bool]:
    contract = build_target_contracts(
        request.trade_date,
        request.target_codes,
    )[AcquisitionGroupId.OFFICIAL_EVENTS_RISK]
    return {
        field: True
        for record_type in contract.record_types
        for field in record_type.required_fields
    }


def _raw_publication_time(value: Any, request: AcquisitionRequest) -> datetime:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PermanentRouteFailure(
            "CNINFO disclosure lacks a raw millisecond publication timestamp",
            FailureClassification.INVALID_SEMANTICS,
        )
    if not math.isfinite(float(value)) or float(value) <= 0 or float(value) % 1:
        raise PermanentRouteFailure(
            "CNINFO disclosure contains an invalid millisecond timestamp",
            FailureClassification.INVALID_SEMANTICS,
        )
    try:
        return datetime.fromtimestamp(
            int(value) / 1000,
            tz=timezone.utc,
        ).astimezone(request.report_cutoff.tzinfo)
    except (OverflowError, OSError, ValueError) as exc:
        raise PermanentRouteFailure(
            "CNINFO disclosure timestamp is outside the supported range",
            FailureClassification.INVALID_SEMANTICS,
        ) from exc


def _merge_duplicate(existing: dict[str, Any], incoming: dict[str, Any]) -> None:
    identity_fields = (
        "trade_date",
        "ts_code",
        "event_id",
        "title",
        "publication_time",
        "pdf_path",
    )
    if any(existing[field] != incoming[field] for field in identity_fields):
        raise PermanentRouteFailure(
            "CNINFO duplicate announcement ID contains conflicting facts",
            FailureClassification.SCHEMA,
        )
    if incoming["hard_risk"]:
        existing["hard_risk"] = True
        existing["event_type"] = incoming["event_type"]


def _bare_code(ts_code: str) -> str:
    parts = str(ts_code).strip().upper().split(".")
    if len(parts) != 2 or len(parts[0]) != 6 or not parts[0].isdigit():
        raise PermanentRouteFailure(
            "CNINFO request contains an invalid security code",
            FailureClassification.SCHEMA,
        )
    if parts[1] not in {"SH", "SZ", "BJ"}:
        raise PermanentRouteFailure(
            "CNINFO request contains an unsupported exchange suffix",
            FailureClassification.SCHEMA,
        )
    return parts[0]


def _to_ts_code(code: str) -> str:
    if code.startswith(("4", "8", "92")):
        suffix = "BJ"
    elif code.startswith(("0", "3")):
        suffix = "SZ"
    elif code.startswith(("5", "6", "9")):
        suffix = "SH"
    else:
        raise PermanentRouteFailure(
            "CNINFO disclosure contains an unrecognized exchange code",
            FailureClassification.SCHEMA,
        )
    return f"{code}.{suffix}"


def _semantic_hash(value: dict[str, Any]) -> str:
    serialized = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


__all__ = ["CninfoDisclosureClient", "CninfoRequestPacer"]
