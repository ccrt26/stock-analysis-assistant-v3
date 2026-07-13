from datetime import date, datetime, timezone

from stock_analyzer.data.cninfo_research_client import CninfoResearchClient


class Response:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class Http:
    def __init__(self):
        self.pages = []

    def post(self, url, data, timeout):
        self.pages.append(int(data["pageNum"]))
        page = int(data["pageNum"])
        rows = [
            {
                "announcementId": f"A{page}",
                "announcementTitle": "关于股东减持计划的公告" if page == 1 else "年度报告",
                "announcementTime": int(
                    datetime(2026, 7, 10, 10, tzinfo=timezone.utc).timestamp() * 1000
                ) + page * 1000,
                "secCode": "000001",
                "secName": "平安银行",
                "adjunctUrl": f"finalpage/{page}.PDF",
            }
        ]
        return Response({"totalAnnouncement": 2, "announcements": rows})


def test_cninfo_global_pagination_preserves_precise_time_and_only_labels_candidate_event():
    client = CninfoResearchClient(
        Http(), page_size=1, pacer=lambda: None, max_retries=0
    )

    rows = client.fetch_announcements(date(2026, 7, 10), date(2026, 7, 10))

    assert [row["announcement_id"] for row in rows] == ["A1", "A2"]
    assert rows[0]["available_at"].tzinfo is not None
    assert rows[0]["candidate_event_types"] == ["shareholder_reduction"]
    assert rows[0]["classification_is_fact"] is False
    assert rows[0]["url"].endswith("finalpage/1.PDF")
