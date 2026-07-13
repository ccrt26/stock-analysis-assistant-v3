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


def test_cninfo_normalizes_shenzhen_and_shanghai_b_share_codes():
    class BShareHttp:
        def post(self, url, data, timeout):
            rows = []
            for index, code in enumerate(("200553", "900901"), start=1):
                rows.append(
                    {
                        "announcementId": f"B{index}",
                        "announcementTitle": "年度报告",
                        "announcementTime": int(
                            datetime(
                                2026, 7, 10, 10, index, tzinfo=timezone.utc
                            ).timestamp()
                            * 1000
                        ),
                        "secCode": code,
                        "secName": "B股公司",
                        "adjunctUrl": f"finalpage/B{index}.PDF",
                    }
                )
            return Response({"totalAnnouncement": 2, "announcements": rows})

    client = CninfoResearchClient(
        BShareHttp(), page_size=30, pacer=lambda: None, max_retries=0
    )

    rows = client.fetch_announcements(date(2026, 7, 10), date(2026, 7, 10))

    assert [row["ts_code"] for row in rows] == ["200553.SZ", "900901.SH"]
