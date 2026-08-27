from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from stock_analyzer.data.exchange_announcement_client import (
    ExchangeAnnouncementClient,
)
from stock_analyzer.data.tushare_research_client import ResearchSourceError


class Response:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


def _sse_row(number: int) -> dict:
    return {
        "SECURITY_CODE": "600000",
        "SECURITY_NAME": "浦发银行",
        "TITLE": "关于股东减持计划的公告" if number == 1 else "年度报告",
        "ADDDATE": f"2026-08-26 08:0{number}:00",
        "SSEDATE": "2026-08-26",
        "URL": f"/disclosure/listedinfo/announcement/c/new/sse-{number}.pdf",
        "BULLETIN_TYPE": "临时公告",
        "BULLETIN_HEADING": "公司公告",
    }


def _szse_row(number: int) -> dict:
    return {
        "annId": f"SZ{number}",
        "id": f"row-{number}",
        "secCode": ["000001"],
        "secName": ["平安银行"],
        "title": "关于回购股份的公告" if number == 1 else "年度报告",
        "publishTime": f"2026-08-26 08:1{number}:00",
        "attachPath": f"/disc/disk03/finalpage/szse-{number}.PDF",
        "attachFormat": "PDF",
    }


def test_sse_reads_last_page_and_preserves_official_precise_time_and_source():
    class Http:
        def __init__(self):
            self.pages = []

        def get(self, url, *, params, headers, timeout):
            page = int(params["pageHelp.pageNo"])
            self.pages.append(page)
            rows = [_sse_row(page)]
            return Response(
                {
                    "pageHelp": {
                        "pageNo": page,
                        "pageCount": 2,
                        "total": 2,
                        "data": rows,
                    }
                }
            )

    http = Http()
    client = ExchangeAnnouncementClient(
        http, sse_page_size=1, max_retries=0, pacer=lambda source: None
    )

    rows = client.fetch_sse_announcements(
        date(2026, 8, 26), date(2026, 8, 26)
    )

    assert http.pages == [1, 2]
    assert len(rows) == 2
    assert rows[0]["announcement_id"].startswith("sse:")
    assert rows[0]["source_name"] == "sse"
    assert rows[0]["source_record_id"].endswith("sse-1.pdf")
    assert rows[0]["source_endpoint"] == (
        "security/stock/queryCompanyBulletin.do"
    )
    assert rows[0]["available_at"] == datetime(
        2026, 8, 26, 8, 1, tzinfo=ZoneInfo("Asia/Shanghai")
    )
    assert rows[0]["candidate_event_types"] == ["shareholder_reduction"]
    assert rows[0]["classification_is_fact"] is False


def test_sse_rejects_duplicate_page_rows_as_incomplete():
    class Http:
        def get(self, url, *, params, headers, timeout):
            page = int(params["pageHelp.pageNo"])
            return Response(
                {
                    "pageHelp": {
                        "pageNo": page,
                        "pageCount": 2,
                        "total": 2,
                        "data": [_sse_row(1)],
                    }
                }
            )

    client = ExchangeAnnouncementClient(
        Http(), sse_page_size=1, max_retries=0, pacer=lambda source: None
    )

    with pytest.raises(ResearchSourceError) as exc_info:
        client.fetch_sse_announcements(
            date(2026, 8, 26), date(2026, 8, 26)
        )

    assert exc_info.value.category == "incomplete"
    assert exc_info.value.endpoint == "security/stock/queryCompanyBulletin.do"


def test_szse_reads_last_page_and_preserves_official_precise_time_and_source():
    class Http:
        def __init__(self):
            self.pages = []

        def post(self, url, *, json, headers, timeout):
            page = int(json["pageNum"])
            self.pages.append(page)
            return Response(
                {
                    "announceCount": 2,
                    "data": [_szse_row(page)],
                }
            )

    http = Http()
    client = ExchangeAnnouncementClient(
        http, szse_page_size=1, max_retries=0, pacer=lambda source: None
    )

    rows = client.fetch_szse_announcements(
        date(2026, 8, 26), date(2026, 8, 26)
    )

    assert http.pages == [1, 2]
    assert [row["announcement_id"] for row in rows] == ["szse:SZ1", "szse:SZ2"]
    assert rows[0]["source_name"] == "szse"
    assert rows[0]["source_record_id"] == "SZ1"
    assert rows[0]["source_endpoint"] == "api/disc/announcement/annList"
    assert rows[0]["available_at"] == datetime(
        2026, 8, 26, 8, 11, tzinfo=ZoneInfo("Asia/Shanghai")
    )
    assert rows[0]["url"].endswith("/disc/disk03/finalpage/szse-1.PDF")
    assert rows[0]["candidate_event_types"] == ["repurchase"]
    assert rows[0]["classification_is_fact"] is False


def test_szse_rejects_changed_announce_count_without_partial_result():
    class Http:
        def post(self, url, *, json, headers, timeout):
            page = int(json["pageNum"])
            return Response(
                {
                    "announceCount": 2 if page == 1 else 3,
                    "data": [_szse_row(page)],
                }
            )

    client = ExchangeAnnouncementClient(
        Http(), szse_page_size=1, max_retries=0, pacer=lambda source: None
    )

    with pytest.raises(ResearchSourceError) as exc_info:
        client.fetch_szse_announcements(
            date(2026, 8, 26), date(2026, 8, 26)
        )

    assert exc_info.value.category == "incomplete"
    assert exc_info.value.endpoint == "api/disc/announcement/annList"
