from datetime import date

import pandas as pd

from stock_analyzer.data.event_backfill import EventBackfillService
from stock_analyzer.data.research_contracts import ResearchDatasetId
from stock_analyzer.data.tushare_research_client import TushareResearchClient
from stock_analyzer.storage.research_warehouse import ResearchWarehouse


class ActionPro:
    def __init__(self):
        self.suspension_calls = []

    def stk_holdertrade(self, **kwargs):
        return pd.DataFrame([{
            "ts_code": "000001.SZ", "ann_date": "20260710", "holder_name": "股东A",
            "holder_type": "G", "in_de": "DE", "change_vol": 100.0,
            "change_ratio": 0.1, "after_share": 900.0, "after_ratio": 0.9,
            "avg_price": 10.0, "total_share": 1000.0,
        }])

    def share_float(self, **kwargs):
        return pd.DataFrame([{
            "ts_code": "000001.SZ", "ann_date": "20260701", "float_date": "20260710",
            "float_share": 100.0, "float_ratio": 1.0, "holder_name": "股东A",
            "share_type": "首发",
        }])

    def repurchase(self, **kwargs):
        return pd.DataFrame([{
            "ts_code": "000001.SZ", "ann_date": "20260710", "end_date": "20260709",
            "proc": "实施", "exp_date": None, "vol": 10.0, "amount": 100.0,
            "high_limit": 11.0, "low_limit": 9.0,
        }])

    def pledge_stat(self, **kwargs):
        return pd.DataFrame([{
            "ts_code": "000001.SZ", "end_date": kwargs["end_date"], "pledge_count": 1,
            "unrest_pledge": 10.0, "rest_pledge": 0.0, "total_share": 1000.0,
            "pledge_ratio": 1.0,
        }])

    def suspend_d(self, **kwargs):
        self.suspension_calls.append(kwargs["trade_date"])
        return pd.DataFrame(columns=["ts_code", "trade_date", "suspend_timing", "suspend_type"])


class AnnouncementClient:
    def fetch_announcements(self, start, through):
        return [{
            "announcement_id": "A1", "ts_code": "000001.SZ", "title": "减持公告",
            "announcement_time": __import__("datetime").datetime(2026, 7, 10, 10, tzinfo=__import__("datetime").timezone.utc),
            "available_at": __import__("datetime").datetime(2026, 7, 10, 10, tzinfo=__import__("datetime").timezone.utc),
            "url": "https://www.cninfo.com.cn/a", "pdf_path": "a.pdf",
            "candidate_event_types": ["shareholder_reduction"],
            "classification_version": "cninfo-title-v1", "classification_is_fact": False,
            "hard_risk_candidate": False,
        }]


def test_event_backfill_stores_official_announcement_and_structured_actions(tmp_path):
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    service = EventBackfillService(
        TushareResearchClient(ActionPro(), pacer=lambda method: None),
        AnnouncementClient(),
        warehouse,
    )
    summary = service.backfill(
        start=date(2026, 7, 1), through=date(2026, 7, 10),
        trading_dates=(date(2026, 7, 10),), resume=True,
    )
    assert len(warehouse.read_current(ResearchDatasetId.ANNOUNCEMENT)) == 1
    assert len(warehouse.read_current(ResearchDatasetId.HOLDER_TRADE)) == 1
    assert len(warehouse.read_current(ResearchDatasetId.SHARE_FLOAT)) == 1
    assert len(warehouse.read_current(ResearchDatasetId.REPURCHASE)) == 1
    assert summary.failed == 0


def test_event_backfill_limits_daily_suspension_history_to_one_year(tmp_path):
    pro = ActionPro()
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    service = EventBackfillService(
        TushareResearchClient(pro, pacer=lambda method: None),
        type(
            "EmptyAnnouncementClient",
            (),
            {"fetch_announcements": lambda self, start, through: []},
        )(),
        warehouse,
    )

    service.backfill(
        start=date(2021, 7, 14),
        through=date(2026, 7, 13),
        trading_dates=(date(2024, 7, 10), date(2026, 7, 10)),
        resume=True,
    )

    assert pro.suspension_calls == ["20260710"]


def test_empty_suspension_day_is_checked_once_on_resume(tmp_path):
    pro = ActionPro()
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    service = EventBackfillService(
        TushareResearchClient(pro, pacer=lambda method: None),
        type(
            "EmptyAnnouncementClient",
            (),
            {"fetch_announcements": lambda self, start, through: []},
        )(),
        warehouse,
    )

    for _ in range(2):
        service.backfill(
            start=date(2026, 7, 10),
            through=date(2026, 7, 10),
            trading_dates=(date(2026, 7, 10),),
            resume=True,
        )

    assert pro.suspension_calls == ["20260710"]


def test_holder_trade_deduplicates_exact_rows_but_preserves_provider_variants(tmp_path):
    class VariantHolderPro(ActionPro):
        def __init__(self):
            super().__init__()
            self.holder_limits = []

        def stk_holdertrade(self, **kwargs):
            self.holder_limits.append(kwargs["limit"])
            base = {
                "ts_code": "000001.SZ",
                "ann_date": "20260710",
                "holder_name": "股东A",
                "holder_type": "G",
                "in_de": "IN",
                "change_vol": 100.0,
                "change_ratio": 0.1,
                "after_share": 900.0,
                "after_ratio": 0.9,
                "avg_price": 10.0,
                "total_share": 1000.0,
            }
            variant = {**base, "avg_price": 10.1}
            return pd.DataFrame([base, base, variant])

    pro = VariantHolderPro()
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    service = EventBackfillService(
        TushareResearchClient(pro, pacer=lambda method: None),
        AnnouncementClient(),
        warehouse,
    )

    service.backfill(
        start=date(2026, 7, 1),
        through=date(2026, 7, 10),
        trading_dates=(),
        resume=True,
    )

    rows = warehouse.read_current(ResearchDatasetId.HOLDER_TRADE)
    assert len(rows) == 2
    assert rows["provider_record_id"].nunique() == 2
    assert rows["variant_group_id"].nunique() == 1
    assert pro.holder_limits == [3000]
