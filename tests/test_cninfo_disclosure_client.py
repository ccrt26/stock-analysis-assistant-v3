from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from stock_analyzer.data.acquisition import PermanentRouteFailure, TransientRouteFailure
from stock_analyzer.data.cninfo_disclosure_client import (
    CninfoDisclosureClient,
    CninfoRequestPacer,
)
from stock_analyzer.data.formal_routes import EndpointResponse
from stock_analyzer.data.readiness import (
    AcquisitionGroupId,
    AcquisitionRequest,
    FailureClassification,
)


TARGET = date(2026, 7, 10)
SHANGHAI = ZoneInfo("Asia/Shanghai")
CUTOFF = datetime(2026, 7, 10, 18, 30, tzinfo=SHANGHAI)
CODE = "600000.SH"
RISK_CATEGORIES = {
    "category_fxts_szsh",
    "category_tbclts_szsh",
    "category_tszlq_szsh",
}


def request(codes=(CODE,)) -> AcquisitionRequest:
    return AcquisitionRequest(
        run_id="formal-cninfo-test",
        trade_date=TARGET,
        report_cutoff=CUTOFF,
        target_codes=codes,
        contract_version="formal-v2",
    )


def epoch_ms(value: datetime) -> int:
    return int(value.astimezone(timezone.utc).timestamp() * 1000)


def announcement(
    identifier: str,
    *,
    code: str = "600000",
    published_at: datetime | None = None,
    title: str = "关于重大事项的公告",
    path: str | None = None,
) -> dict:
    published_at = published_at or datetime(
        2026,
        7,
        10,
        17,
        5,
        6,
        123000,
        tzinfo=SHANGHAI,
    )
    return {
        "secCode": code,
        "secName": "浦发银行",
        "orgId": "gssh0600000",
        "announcementId": identifier,
        "announcementTitle": title,
        "announcementTime": epoch_ms(published_at),
        "adjunctUrl": path or f"finalpage/2026-07-10/{identifier}.PDF",
    }


def page(items=(), *, total: int | None = None) -> dict:
    rows = list(items)
    return {
        "totalAnnouncement": len(rows) if total is None else total,
        "announcements": rows,
    }


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload


class RecordedHttpClient:
    def __init__(self, handler):
        self.handler = handler
        self.calls: list[tuple[str, str, dict]] = []

    def get(self, path, **kwargs):
        self.calls.append(("GET", path, kwargs))
        return self.handler("GET", path, kwargs)

    def post(self, path, **kwargs):
        self.calls.append(("POST", path, kwargs))
        return self.handler("POST", path, kwargs)


class RecordedStatusClient:
    def __init__(self, records=()):
        self.records = tuple(records)
        self.calls = 0

    def fetch_official_status_risk(self, acquisition_request):
        self.calls += 1
        return EndpointResponse(
            records=self.records,
            covered_dates=(date(2026, 7, 9), TARGET),
            coverage_codes=tuple(sorted(acquisition_request.target_codes)),
            coverage_proven=True,
            field_coverage={
                "trade_date": True,
                "ts_code": True,
                "event_id": True,
                "event_type": True,
                "title": True,
                "publication_time": True,
                "source_reliability": True,
                "is_new_information": True,
                "hard_risk": True,
            },
            source_names=("tushare.suspend_d", "tushare.stock_basic"),
            publication_times={},
        )


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def stock_map(*codes: str) -> dict:
    return {
        "stockList": [
            {
                "code": code,
                "orgId": f"org-{code}",
                "zwjc": f"公司-{code}",
                "category": "A股",
            }
            for code in codes
        ]
    }


def client_with(handler, *, status_client=None, **kwargs):
    status_client = status_client or RecordedStatusClient()
    http = RecordedHttpClient(handler)
    return (
        CninfoDisclosureClient(status_client, http, **kwargs),
        status_client,
        http,
    )


def test_cninfo_route_preserves_epoch_milliseconds_and_filters_after_cutoff():
    before = announcement("before")
    after = announcement(
        "after",
        published_at=datetime(2026, 7, 10, 19, 0, tzinfo=SHANGHAI),
    )

    def handler(method, path, kwargs):
        if method == "GET":
            return FakeResponse(stock_map("600000"))
        category = kwargs["data"]["category"]
        if category == "":
            return FakeResponse(page([before, after]))
        if category == "category_fxts_szsh":
            return FakeResponse(page([before]))
        return FakeResponse(page())

    status_event = {
        "record_type": "official_event",
        "trade_date": TARGET,
        "ts_code": CODE,
        "event_id": "status:600000",
        "event_type": "special_treatment",
        "title": "ST浦发",
        "publication_time": datetime(2026, 7, 10, 0, 0, tzinfo=SHANGHAI),
        "source_reliability": "official_provider",
        "is_new_information": True,
        "hard_risk": True,
        "source_name": "tushare.stock_basic",
    }
    client, status, _ = client_with(
        handler,
        status_client=RecordedStatusClient((status_event,)),
    )

    response = client.fetch_official_events_risk(request())

    assert status.calls == 1
    assert response.coverage_codes == (CODE,)
    assert response.coverage_proven is True
    disclosure = next(row for row in response.records if row["event_id"] == "before")
    assert disclosure["publication_time"].microsecond == 123000
    assert disclosure["publication_time"].tzinfo is not None
    assert disclosure["hard_risk"] is True
    assert disclosure["event_type"] == "risk_warning"
    assert all(row["event_id"] != "after" for row in response.records)
    assert response.source_names == (
        "tushare.suspend_d",
        "tushare.stock_basic",
        "cninfo.raw.disclosure",
    )


def test_cninfo_route_paginates_each_code_and_category_and_deduplicates_id():
    first_page = [announcement(f"first-{index:02d}") for index in range(30)]
    second = announcement("second")

    def handler(method, path, kwargs):
        if method == "GET":
            return FakeResponse(stock_map("600000"))
        data = kwargs["data"]
        if data["category"] == "" and data["pageNum"] == "1":
            return FakeResponse(page(first_page, total=31))
        if data["category"] == "" and data["pageNum"] == "2":
            return FakeResponse(page([second], total=31))
        if data["category"] == "category_tbclts_szsh":
            return FakeResponse(page([second]))
        return FakeResponse(page())

    client, _, http = client_with(handler)

    response = client.fetch_official_events_risk(request())

    assert len(response.records) == 31
    assert {row["event_id"] for row in response.records} == {
        *(f"first-{index:02d}" for index in range(30)),
        "second",
    }
    assert next(row for row in response.records if row["event_id"] == "second")[
        "hard_risk"
    ] is True
    generic_pages = [
        call[2]["data"]["pageNum"]
        for call in http.calls
        if call[0] == "POST" and call[2]["data"]["category"] == ""
    ]
    assert generic_pages == ["1", "2"]


def test_cninfo_route_refetches_status_and_never_reuses_primary_payload():
    def handler(method, path, kwargs):
        if method == "GET":
            return FakeResponse(stock_map("600000"))
        return FakeResponse(page())

    client, status, _ = client_with(handler)

    first = client.fetch_official_events_risk(request())
    second = client.fetch_official_events_risk(request())

    assert status.calls == 2
    assert first is not second
    assert first.records == second.records == ()


def test_cninfo_route_proves_valid_code_empty_coverage():
    def handler(method, path, kwargs):
        if method == "GET":
            return FakeResponse(stock_map("600000"))
        return FakeResponse(page())

    client, _, _ = client_with(handler)

    response = client.fetch_official_events_risk(request())

    assert response.records == ()
    assert response.coverage_codes == (CODE,)
    assert response.coverage_proven is True


def test_cninfo_route_accepts_null_announcements_only_when_total_zero():
    def empty_handler(method, path, kwargs):
        if method == "GET":
            return FakeResponse(stock_map("600000"))
        return FakeResponse({"totalAnnouncement": 0, "announcements": None})

    client, _, _ = client_with(empty_handler)

    response = client.fetch_official_events_risk(request())

    assert response.records == ()
    assert response.coverage_proven is True

    def inconsistent_handler(method, path, kwargs):
        if method == "GET":
            return FakeResponse(stock_map("600000"))
        return FakeResponse({"totalAnnouncement": 1, "announcements": None})

    inconsistent, _, _ = client_with(inconsistent_handler)
    with pytest.raises(PermanentRouteFailure) as raised:
        inconsistent.fetch_official_events_risk(request())
    assert raised.value.classification is FailureClassification.SCHEMA


def test_cninfo_route_rejects_missing_stock_map_code():
    def handler(method, path, kwargs):
        return FakeResponse(stock_map("000001"))

    client, _, http = client_with(handler)

    with pytest.raises(PermanentRouteFailure) as raised:
        client.fetch_official_events_risk(request())

    assert raised.value.classification is FailureClassification.INCOMPLETE_UNIVERSE
    assert [call[0] for call in http.calls] == ["GET"]


@pytest.mark.parametrize("bad_timestamp", [None, "2026-07-10", "not-a-time"])
def test_cninfo_route_rejects_date_string_missing_or_malformed_timestamp(
    bad_timestamp,
):
    invalid = announcement("invalid")
    invalid["announcementTime"] = bad_timestamp

    def handler(method, path, kwargs):
        if method == "GET":
            return FakeResponse(stock_map("600000"))
        if kwargs["data"]["category"] == "":
            return FakeResponse(page([invalid]))
        return FakeResponse(page())

    client, _, _ = client_with(handler)

    with pytest.raises(PermanentRouteFailure) as raised:
        client.fetch_official_events_risk(request())

    assert raised.value.classification is FailureClassification.INVALID_SEMANTICS


@pytest.mark.parametrize(
    "mutation",
    [
        {"secCode": "000001"},
        {"announcementId": ""},
        {"adjunctUrl": ""},
        {
            "announcementTime": epoch_ms(
                datetime(2026, 7, 1, 9, 0, tzinfo=SHANGHAI)
            )
        },
    ],
)
def test_cninfo_route_rejects_wrong_code_date_or_missing_stable_identity(mutation):
    invalid = announcement("invalid")
    invalid.update(mutation)

    def handler(method, path, kwargs):
        if method == "GET":
            return FakeResponse(stock_map("600000"))
        if kwargs["data"]["category"] == "":
            return FakeResponse(page([invalid]))
        return FakeResponse(page())

    client, _, _ = client_with(handler)

    with pytest.raises(PermanentRouteFailure) as raised:
        client.fetch_official_events_risk(request())

    assert raised.value.classification in {
        FailureClassification.SCHEMA,
        FailureClassification.INVALID_SEMANTICS,
    }


def test_cninfo_route_rejects_duplicate_id_with_conflicting_facts():
    first = announcement("duplicate")
    conflicting = announcement("duplicate", title="冲突公告")

    def handler(method, path, kwargs):
        if method == "GET":
            return FakeResponse(stock_map("600000"))
        if kwargs["data"]["category"] == "":
            return FakeResponse(page([first, conflicting]))
        return FakeResponse(page())

    client, _, _ = client_with(handler)

    with pytest.raises(PermanentRouteFailure) as raised:
        client.fetch_official_events_risk(request())

    assert raised.value.classification is FailureClassification.SCHEMA


def test_cninfo_route_classifies_429_as_transient_and_schema_as_permanent():
    clock = FakeClock()
    pacer = CninfoRequestPacer(
        calls_per_minute=20,
        clock=clock,
        sleeper=clock.sleep,
    )

    throttled, _, throttled_http = client_with(
        lambda *_: FakeResponse({}, status_code=429),
        request_pacer=pacer,
        max_retries=1,
    )
    with pytest.raises(TransientRouteFailure) as raised:
        throttled.fetch_official_events_risk(request())
    assert raised.value.classification is FailureClassification.RATE_LIMIT
    assert len(throttled_http.calls) == 2

    malformed, _, _ = client_with(lambda *_: FakeResponse({}))
    with pytest.raises(PermanentRouteFailure) as raised:
        malformed.fetch_official_events_risk(request())
    assert raised.value.classification is FailureClassification.SCHEMA


def test_cninfo_semantic_probe_requires_non_midnight_populated_and_real_empty_case():
    populated = announcement("populated")

    def handler(method, path, kwargs):
        if method == "GET":
            return FakeResponse(stock_map("600000", "600001"))
        data = kwargs["data"]
        if data["stock"] == "":
            return FakeResponse(page([populated]))
        if data["stock"].startswith("600000,"):
            return FakeResponse(page([populated]))
        return FakeResponse(page())

    client, _, _ = client_with(handler)

    hashes = client.verify_event_semantics(request())

    assert set(hashes) == {"populated_precise_time", "empty_coverage"}
    assert all(len(value) == 64 for value in hashes.values())
    assert len(set(hashes.values())) == 2

    midnight = announcement(
        "midnight",
        published_at=datetime(2026, 7, 10, 0, 0, tzinfo=SHANGHAI),
    )

    def midnight_handler(method, path, kwargs):
        if method == "GET":
            return FakeResponse(stock_map("600000"))
        return FakeResponse(page([midnight]))

    invalid, _, _ = client_with(midnight_handler)
    with pytest.raises(PermanentRouteFailure) as raised:
        invalid.verify_event_semantics(request())
    assert raised.value.classification is FailureClassification.INVALID_SEMANTICS


def test_cninfo_pacer_waits_at_configured_limit_without_busy_loop():
    clock = FakeClock()
    pacer = CninfoRequestPacer(
        calls_per_minute=2,
        window_seconds=60,
        clock=clock,
        sleeper=clock.sleep,
    )

    pacer.wait()
    pacer.wait()
    pacer.wait()

    assert clock.sleeps == [60]
    assert clock.now == 60
