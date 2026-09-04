from datetime import date, datetime, timezone

import pandas as pd
import stock_analyzer.data.event_backfill as event_backfill_module

from stock_analyzer.data.event_backfill import EventBackfillService
from stock_analyzer.data.research_contracts import (
    FactBatch,
    ResearchDatasetId,
    research_contract,
)
from stock_analyzer.data.tushare_research_client import TushareResearchClient
from stock_analyzer.data.tushare_research_client import ResearchSourceError
from stock_analyzer.storage.research_warehouse import ResearchWarehouse


class ActionPro:
    def __init__(self):
        self.suspension_calls = []

    def stk_holdertrade(self, **kwargs):
        return pd.DataFrame([{
            "ts_code": "000001.SZ",
            "ann_date": kwargs.get("end_date", "20260710"),
            "holder_name": "股东A",
            "holder_type": "G", "in_de": "DE", "change_vol": 100.0,
            "change_ratio": 0.1, "after_share": 900.0, "after_ratio": 0.9,
            "avg_price": 10.0, "total_share": 1000.0,
        }])

    def share_float(self, **kwargs):
        if kwargs.get("ann_date"):
            return pd.DataFrame([{
                "ts_code": "000001.SZ",
                "ann_date": kwargs["ann_date"],
                "float_date": "20280620",
                "float_share": 100.0,
                "float_ratio": 1.0,
                "holder_name": "股东A",
                "share_type": "首发",
            }])
        return pd.DataFrame([{
            "ts_code": "000001.SZ", "ann_date": kwargs.get("start_date", "20260701"),
            "float_date": kwargs.get("end_date", "20260710"),
            "float_share": 100.0, "float_ratio": 1.0, "holder_name": "股东A",
            "share_type": "首发",
        }])

    def repurchase(self, **kwargs):
        return pd.DataFrame([{
            "ts_code": "000001.SZ",
            "ann_date": kwargs.get("end_date", "20260710"),
            "end_date": kwargs.get("end_date", "20260709"),
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


def _official_announcement(source: str, announcement_id: str) -> dict:
    suffix = "SH" if source == "sse" else "SZ"
    return {
        "announcement_id": announcement_id,
        "ts_code": f"600000.{suffix}" if source == "sse" else "000001.SZ",
        "title": "年度报告",
        "announcement_time": datetime(2026, 8, 26, 8, tzinfo=timezone.utc),
        "available_at": datetime(2026, 8, 26, 8, tzinfo=timezone.utc),
        "url": f"https://official.example/{announcement_id}.pdf",
        "pdf_path": f"/{announcement_id}.pdf",
        "source_name": source,
        "source_endpoint": f"{source}/announcements",
        "source_record_id": announcement_id,
        "candidate_event_types": [],
        "classification_version": "official-title-v1",
        "classification_is_fact": False,
        "hard_risk_candidate": False,
    }


def test_announcement_backfill_uses_cninfo_without_calling_exchange_fallback(tmp_path):
    class Cninfo:
        def fetch_announcements(self, start, through):
            return AnnouncementClient().fetch_announcements(start, through)

    class Exchanges:
        def __init__(self):
            self.calls = []

        def fetch_sse_announcements(self, start, through):
            self.calls.append("sse")
            return []

        def fetch_szse_announcements(self, start, through):
            self.calls.append("szse")
            return []

    exchanges = Exchanges()
    service = EventBackfillService(
        TushareResearchClient(ActionPro(), pacer=lambda method: None),
        Cninfo(),
        ResearchWarehouse(tmp_path / "warehouse"),
        exchange_announcements=exchanges,
    )

    summary = service.backfill_announcements(
        start=date(2026, 8, 26),
        through=date(2026, 8, 26),
        resume=False,
        fallback_to_exchanges=True,
    )

    assert exchanges.calls == []
    assert summary.capabilities["announcement_status"] == "cninfo_complete"
    assert summary.capabilities["announcement_exchanges"] == ["SSE", "SZSE"]


def test_announcement_backfill_uses_both_official_exchanges_after_cninfo_source_failure(tmp_path):
    class Cninfo:
        def fetch_announcements(self, start, through):
            raise ResearchSourceError(
                "CNINFO timeout", category="network", endpoint="cninfo"
            )

    class Exchanges:
        def fetch_sse_announcements(self, start, through):
            return [_official_announcement("sse", "sse:one")]

        def fetch_szse_announcements(self, start, through):
            return [_official_announcement("szse", "szse:one")]

    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    service = EventBackfillService(
        TushareResearchClient(ActionPro(), pacer=lambda method: None),
        Cninfo(),
        warehouse,
        exchange_announcements=Exchanges(),
    )

    summary = service.backfill_announcements(
        start=date(2026, 8, 26),
        through=date(2026, 8, 26),
        resume=False,
        fallback_to_exchanges=True,
    )

    rows = warehouse.read_current(ResearchDatasetId.ANNOUNCEMENT)
    assert set(rows["source_name"]) == {"sse", "szse"}
    assert summary.capabilities["announcement_status"] == "exchange_complete"
    assert summary.capabilities["announcement_exchanges"] == ["SSE", "SZSE"]
    assert summary.capabilities["announcement_failures"]["cninfo"] == "network"
    assert summary.limited == 0


def test_announcement_backfill_keeps_one_complete_exchange_as_partial(tmp_path):
    class Cninfo:
        def fetch_announcements(self, start, through):
            raise ResearchSourceError(
                "CNINFO timeout", category="network", endpoint="cninfo"
            )

    class Exchanges:
        def fetch_sse_announcements(self, start, through):
            return [_official_announcement("sse", "sse:one")]

        def fetch_szse_announcements(self, start, through):
            raise ResearchSourceError(
                "SZSE changed total", category="incomplete", endpoint="szse"
            )

    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    service = EventBackfillService(
        TushareResearchClient(ActionPro(), pacer=lambda method: None),
        Cninfo(),
        warehouse,
        exchange_announcements=Exchanges(),
    )

    summary = service.backfill_announcements(
        start=date(2026, 8, 26),
        through=date(2026, 8, 26),
        resume=False,
        fallback_to_exchanges=True,
    )

    rows = warehouse.read_current(ResearchDatasetId.ANNOUNCEMENT)
    assert set(rows["source_name"]) == {"sse"}
    assert summary.capabilities["announcement_status"] == "exchange_partial"
    assert summary.capabilities["announcement_exchanges"] == ["SSE"]
    assert summary.capabilities["announcement_failures"]["szse"] == "incomplete"
    assert summary.limited == 1


def test_announcement_backfill_does_not_hide_local_cninfo_client_errors(tmp_path):
    class BrokenCninfo:
        def fetch_announcements(self, start, through):
            raise RuntimeError("local normalization bug")

    class Exchanges:
        def __init__(self):
            self.called = False

        def fetch_sse_announcements(self, start, through):
            self.called = True
            return []

        def fetch_szse_announcements(self, start, through):
            self.called = True
            return []

    exchanges = Exchanges()
    service = EventBackfillService(
        TushareResearchClient(ActionPro(), pacer=lambda method: None),
        BrokenCninfo(),
        ResearchWarehouse(tmp_path / "warehouse"),
        exchange_announcements=exchanges,
    )

    with __import__("pytest").raises(RuntimeError, match="local normalization bug"):
        service.backfill_announcements(
            start=date(2026, 8, 26),
            through=date(2026, 8, 26),
            resume=False,
            fallback_to_exchanges=True,
        )

    assert exchanges.called is False


def test_announcement_backfill_marks_all_sources_unavailable_without_blocking(tmp_path):
    class Cninfo:
        def fetch_announcements(self, start, through):
            raise ResearchSourceError(
                "CNINFO timeout", category="network", endpoint="cninfo"
            )

    class Exchanges:
        def fetch_sse_announcements(self, start, through):
            raise ResearchSourceError(
                "SSE timeout", category="network", endpoint="sse"
            )

        def fetch_szse_announcements(self, start, through):
            raise ResearchSourceError(
                "SZSE timeout", category="network", endpoint="szse"
            )

    service = EventBackfillService(
        TushareResearchClient(ActionPro(), pacer=lambda method: None),
        Cninfo(),
        ResearchWarehouse(tmp_path / "warehouse"),
        exchange_announcements=Exchanges(),
    )

    summary = service.backfill_announcements(
        start=date(2026, 8, 26),
        through=date(2026, 8, 26),
        resume=False,
        fallback_to_exchanges=True,
    )

    assert summary.capabilities["announcement_status"] == "announcement_unavailable"
    assert summary.capabilities["announcement_exchanges"] == []
    assert summary.limited == 1
    assert summary.failed == 0


def test_exchange_fallback_drops_only_obvious_existing_cross_source_duplicate(
    tmp_path,
):
    published = datetime(2026, 8, 26, 8, tzinfo=timezone.utc)
    duplicate = _official_announcement("szse", "szse:duplicate")
    duplicate["title"] = "年度 报告"
    duplicate["available_at"] = published
    duplicate["announcement_time"] = published

    class FirstCninfo:
        def fetch_announcements(self, start, through):
            row = dict(duplicate)
            row.update(
                announcement_id="cninfo:duplicate",
                title="年度报告",
                source_name="cninfo",
                source_endpoint="new/hisAnnouncement/query",
                source_record_id="cninfo:duplicate",
            )
            return [row]

    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    base = TushareResearchClient(ActionPro(), pacer=lambda method: None)
    EventBackfillService(base, FirstCninfo(), warehouse).backfill_announcements(
        start=date(2026, 8, 26), through=date(2026, 8, 26), resume=False
    )

    class FailedCninfo:
        def fetch_announcements(self, start, through):
            raise ResearchSourceError(
                "CNINFO timeout", category="network", endpoint="cninfo"
            )

    class Exchanges:
        def fetch_sse_announcements(self, start, through):
            return []

        def fetch_szse_announcements(self, start, through):
            return [duplicate]

    summary = EventBackfillService(
        base,
        FailedCninfo(),
        warehouse,
        exchange_announcements=Exchanges(),
    ).backfill_announcements(
        start=date(2026, 8, 26),
        through=date(2026, 8, 26),
        resume=False,
        fallback_to_exchanges=True,
    )

    rows = warehouse.read_current(ResearchDatasetId.ANNOUNCEMENT)
    assert len(rows) == 1
    assert rows.iloc[0]["source_name"] == "cninfo"
    assert summary.capabilities["announcement_status"] == "exchange_complete"


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
    pledge = warehouse.read_current(ResearchDatasetId.PLEDGE)
    assert not pledge.empty
    assert pledge.iloc[0]["available_at"] == pledge.iloc[0]["ingested_at"]
    assert pledge.iloc[0]["availability_precision"] == "ingestion_cutoff"
    assert set(
        warehouse.read_current(ResearchDatasetId.HOLDER_TRADE)[
            "availability_precision"
        ]
    ) == {"date_conservative"}
    assert summary.failed == 0


def test_next_morning_extension_changes_only_the_announcement_end_date(tmp_path):
    class TrackingActionPro(ActionPro):
        def __init__(self):
            super().__init__()
            self.holder_calls = []
            self.float_calls = []
            self.repurchase_calls = []
            self.pledge_calls = []

        def stk_holdertrade(self, **kwargs):
            self.holder_calls.append(kwargs)
            return super().stk_holdertrade(**kwargs)

        def share_float(self, **kwargs):
            self.float_calls.append(kwargs)
            return super().share_float(**kwargs)

        def repurchase(self, **kwargs):
            self.repurchase_calls.append(kwargs)
            return super().repurchase(**kwargs)

        def pledge_stat(self, **kwargs):
            self.pledge_calls.append(kwargs)
            return super().pledge_stat(**kwargs)

    class TrackingAnnouncementClient:
        def __init__(self):
            self.calls = []

        def fetch_announcements(self, start, through):
            self.calls.append((start, through))
            return []

    friday = date(2026, 8, 21)
    monday = date(2026, 8, 24)
    pro = TrackingActionPro()
    announcements = TrackingAnnouncementClient()
    service = EventBackfillService(
        TushareResearchClient(pro, pacer=lambda method: None),
        announcements,
        ResearchWarehouse(tmp_path / "warehouse"),
    )

    service.backfill(
        start=friday,
        through=friday,
        announcement_through=monday,
        trading_dates=(friday,),
        resume=False,
    )

    assert announcements.calls == [(friday, monday)]
    assert pro.holder_calls[0]["end_date"] == "20260821"
    assert pro.float_calls[0]["ann_date"] == "20260821"
    assert pro.repurchase_calls[0]["end_date"] == "20260821"
    assert pro.pledge_calls[0]["end_date"] == "20260821"
    assert pro.suspension_calls == ["20260821"]


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


def test_targeted_suspension_backfill_calls_only_suspend_endpoint(tmp_path):
    pro = ActionPro()
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    service = EventBackfillService(
        TushareResearchClient(pro, pacer=lambda method: None),
        object(),
        warehouse,
    )

    summary = service.backfill_suspensions(
        trading_dates=(date(2026, 8, 26),),
        through=date(2026, 8, 26),
        resume=False,
    )

    assert pro.suspension_calls == ["20260826"]
    assert summary.failed == 0
    assert summary.scope == "suspension"


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


def test_repurchase_deduplicates_exact_rows_but_preserves_distinct_lots(tmp_path):
    class VariantRepurchasePro(ActionPro):
        def repurchase(self, **kwargs):
            base = {
                "ts_code": "000001.SZ",
                "ann_date": kwargs["end_date"],
                "end_date": kwargs["end_date"],
                "proc": "完成",
                "exp_date": None,
                "vol": 100.0,
                "amount": 1000.0,
                "high_limit": 10.0,
                "low_limit": 10.0,
            }
            return pd.DataFrame([base, base, {**base, "amount": 1200.0}])

    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    service = EventBackfillService(
        TushareResearchClient(
            VariantRepurchasePro(), pacer=lambda method: None
        ),
        AnnouncementClient(),
        warehouse,
    )

    service.backfill(
        start=date(2026, 7, 1),
        through=date(2026, 7, 10),
        trading_dates=(),
        resume=True,
    )

    rows = warehouse.read_current(ResearchDatasetId.REPURCHASE)
    assert len(rows) == 2
    assert rows["provider_record_id"].nunique() == 2
    assert rows["variant_group_id"].nunique() == 1


def test_share_float_keeps_one_current_fact_for_provider_variants(tmp_path):
    class VariantFloatPro(ActionPro):
        def share_float(self, **kwargs):
            base = {
                "ts_code": "000001.SZ",
                "ann_date": "20260701",
                "float_date": "20260710",
                "float_share": 100.0,
                "float_ratio": 1.0,
                "holder_name": "股东A",
                "share_type": "首发",
            }
            return pd.DataFrame([base, base, {**base, "float_share": 200.0}])

    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    service = EventBackfillService(
        TushareResearchClient(VariantFloatPro(), pacer=lambda method: None),
        AnnouncementClient(),
        warehouse,
    )

    service.backfill(
        start=date(2026, 7, 1),
        through=date(2026, 7, 10),
        trading_dates=(),
        resume=True,
    )

    rows = warehouse.read_current(ResearchDatasetId.SHARE_FLOAT)
    assert len(rows) == 1
    assert rows.iloc[0]["float_share"] == 200.0
    assert rows.iloc[0]["provider_variant_count"] == 2
    assert rows.iloc[0]["provider_variant_resolution"] == "largest_float_share_fallback"
    assert rows["variant_group_id"].nunique() == 1


def test_share_float_variant_matches_the_latest_total_share_when_available():
    base = {
        "ts_code": "300779.SZ",
        "ann_date": "20230718",
        "float_date": "20260724",
        "holder_name": "股东A",
        "share_type": "定增股份",
    }
    rows = [
        event_backfill_module._float_row(
            {**base, "float_share": 27_000_000.0, "float_ratio": 19.36}
        ),
        event_backfill_module._float_row(
            {**base, "float_share": 52_920_000.0, "float_ratio": 17.80}
        ),
    ]

    selected = event_backfill_module._collapse_share_float_rows(
        rows,
        {"300779.SZ": 297_300_000.0},
    )

    assert len(selected) == 1
    assert selected[0]["float_share"] == 52_920_000.0
    assert selected[0]["provider_variant_resolution"] == "matched_latest_total_share"


def test_share_float_candidate_matching_uses_daily_basic_total_share_in_shares(
    tmp_path,
):
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    warehouse.commit_batch(
        FactBatch(
            dataset_id=ResearchDatasetId.DAILY_BASIC,
            partition_value="2026-07-10",
            source_name="tushare",
            source_endpoint="daily_basic",
            ingestion_run_id="market:2026-07-10",
            ingested_at=datetime(2026, 7, 10, 8, tzinfo=timezone.utc),
            records=[
                {
                    "trade_date": date(2026, 7, 10),
                    "ts_code": "300779.SZ",
                    "total_share": 297_300_000.0,
                }
            ],
        )
    )

    total_shares = event_backfill_module._latest_total_shares(
        warehouse, date(2026, 7, 10)
    )

    assert total_shares == {"300779.SZ": 297_300_000.0}


def test_existing_share_float_is_rebuilt_on_the_stable_business_key(tmp_path):
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    contract = research_contract(ResearchDatasetId.SHARE_FLOAT)
    current_key = contract.business_key
    contract.business_key = ("provider_record_id",)
    try:
        warehouse.commit_batch(
            FactBatch(
                dataset_id=ResearchDatasetId.SHARE_FLOAT,
                partition_value="2026-07",
                source_name="tushare",
                source_endpoint="share_float",
                ingestion_run_id="legacy-share-float",
                ingested_at=datetime(2026, 7, 14, tzinfo=timezone.utc),
                default_available_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
                records=[
                    event_backfill_module._float_row({
                        "ts_code": "000001.SZ",
                        "ann_date": "20260701",
                        "float_date": "20260710",
                        "float_share": value,
                        "float_ratio": 1.0,
                        "holder_name": "股东A",
                        "share_type": "首发",
                    })
                    for value in (100.0, 200.0)
                ],
            )
        )
    finally:
        contract.business_key = current_key

    result = event_backfill_module.normalize_existing_share_float(
        warehouse,
        through=date(2026, 7, 14),
    )

    assert result["before_rows"] == 2
    assert result["after_rows"] == 1
    current = warehouse.read_current(ResearchDatasetId.SHARE_FLOAT)
    assert current["float_share"].tolist() == [200.0]


def test_share_float_recursively_splits_a_date_range_that_hits_page_capacity(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(event_backfill_module, "_SHARE_FLOAT_PAGE_SIZE", 2)
    monkeypatch.setattr(event_backfill_module, "_SHARE_FLOAT_MAX_PAGES", 1)

    class DenseFloatPro(ActionPro):
        def __init__(self):
            super().__init__()
            self.float_ranges = []

        def share_float(self, **kwargs):
            self.float_ranges.append((kwargs["start_date"], kwargs["end_date"]))
            start = kwargs["start_date"]
            end = kwargs["end_date"]
            count = 2 if start != end else 1
            return pd.DataFrame(
                [
                    {
                        "ts_code": "000001.SZ",
                        "ann_date": start,
                        "float_date": start,
                        "float_share": float(index + 1),
                        "float_ratio": 1.0,
                        "holder_name": f"股东{index}",
                        "share_type": "首发",
                    }
                    for index in range(count)
                ]
            )

    pro = DenseFloatPro()
    service = EventBackfillService(
        TushareResearchClient(pro, pacer=lambda method: None),
        AnnouncementClient(),
        ResearchWarehouse(tmp_path / "warehouse"),
    )

    frame = service._fetch_share_float_range(
        date(2026, 7, 1), date(2026, 7, 2)
    )

    assert len(frame) == 2
    assert pro.float_ranges == [
        ("20260701", "20260702"),
        ("20260701", "20260701"),
        ("20260702", "20260702"),
    ]


def test_daily_share_float_uses_announcement_date_and_keeps_future_schedule(
    tmp_path,
):
    pro = ActionPro()
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    service = EventBackfillService(
        TushareResearchClient(pro, pacer=lambda method: None),
        AnnouncementClient(),
        warehouse,
    )

    service.backfill(
        start=date(2026, 7, 10),
        through=date(2026, 7, 10),
        trading_dates=(),
        resume=True,
    )

    future = warehouse.read_current(
        ResearchDatasetId.SHARE_FLOAT, partition_value="2028-06"
    )
    assert len(future) == 1
    assert future.iloc[0]["float_date"] == date(2028, 6, 20)


def test_long_backfill_limits_share_float_history_and_fetches_known_future(tmp_path):
    class WindowPro(ActionPro):
        def __init__(self):
            super().__init__()
            self.float_ranges = []

        def stk_holdertrade(self, **kwargs):
            return pd.DataFrame()

        def share_float(self, **kwargs):
            self.float_ranges.append((kwargs["start_date"], kwargs["end_date"]))
            return pd.DataFrame()

        def repurchase(self, **kwargs):
            return pd.DataFrame()

        def pledge_stat(self, **kwargs):
            return pd.DataFrame()

    pro = WindowPro()
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    warehouse.commit_batch(
        FactBatch(
            dataset_id=ResearchDatasetId.SHARE_FLOAT,
            partition_value="2024-01",
            source_name="tushare",
            source_endpoint="share_float",
            ingestion_run_id="old-share-float",
            ingested_at=datetime(2024, 1, 31, tzinfo=timezone.utc),
            default_available_at=datetime(2024, 1, 31, tzinfo=timezone.utc),
            records=[
                    {
                        "provider_record_id": "old-lot",
                        "variant_group_id": "old-fact",
                        "ts_code": "000001.SZ",
                        "float_date": date(2024, 1, 31),
                        "available_at": datetime(
                            2024, 1, 31, tzinfo=timezone.utc
                        ),
                    }
            ],
        )
    )
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
        trading_dates=(),
        resume=True,
    )

    assert pro.float_ranges[0][0] == "20250713"
    assert pro.float_ranges[-1][1] == "20290715"
    assert all(start >= "20250713" for start, _ in pro.float_ranges)
    assert warehouse.read_current(
        ResearchDatasetId.SHARE_FLOAT, partition_value="2024-01"
    ).empty


def test_future_share_float_requires_an_announcement_known_by_analysis_date():
    known_through = date(2026, 7, 13)

    assert event_backfill_module._share_float_known_as_of(
        {"ann_date": "20260710", "float_date": "20280620"},
        known_through,
    )
    assert not event_backfill_module._share_float_known_as_of(
        {"ann_date": "20260714", "float_date": "20280620"},
        known_through,
    )
    assert not event_backfill_module._share_float_known_as_of(
        {"ann_date": None, "float_date": "20280620"},
        known_through,
    )
    assert event_backfill_module._share_float_known_as_of(
        {"ann_date": None, "float_date": "20260710"},
        known_through,
    )


def test_pledge_snapshots_try_natural_date_then_fall_back_to_latest_friday(tmp_path):
    class PledgeDatePro(ActionPro):
        def __init__(self):
            super().__init__()
            self.pledge_snapshots = []

        def pledge_stat(self, **kwargs):
            self.pledge_snapshots.append(kwargs["end_date"])
            if kwargs["end_date"] in {"20260331", "20260630", "20260713"}:
                return pd.DataFrame()
            return super().pledge_stat(**kwargs)

    pro = PledgeDatePro()
    service = EventBackfillService(
        TushareResearchClient(pro, pacer=lambda method: None),
        type(
            "EmptyAnnouncementClient",
            (),
            {"fetch_announcements": lambda self, start, through: []},
        )(),
        ResearchWarehouse(tmp_path / "warehouse"),
    )

    service.backfill(
        start=date(2026, 1, 1),
        through=date(2026, 7, 13),
        trading_dates=(),
        resume=True,
    )

    assert pro.pledge_snapshots == [
        "20260331",
        "20260327",
        "20260630",
        "20260626",
        "20260713",
        "20260710",
    ]


def test_pledge_ignores_old_empty_check_after_snapshot_strategy_change(tmp_path):
    class TrackingPledgePro(ActionPro):
        def __init__(self):
            super().__init__()
            self.pledge_snapshots = []

        def pledge_stat(self, **kwargs):
            self.pledge_snapshots.append(kwargs["end_date"])
            return super().pledge_stat(**kwargs)

    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    with event_backfill_module.connect_research_warehouse(
        warehouse.duckdb_path
    ) as connection:
        connection.execute(
            """
            insert into research_watermarks
            (dataset_id, scope_key, watermark_value, updated_at, run_id)
            values ('event_partition_check:pledge', '2026-06', 'empty', now(), 'old')
            """
        )
    pro = TrackingPledgePro()
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
        start=date(2026, 6, 1),
        through=date(2026, 7, 10),
        trading_dates=(),
        resume=True,
    )

    assert "20260630" in pro.pledge_snapshots


def test_resume_skips_checked_historical_event_ranges_before_fetch(tmp_path):
    class IncrementalActionPro(ActionPro):
        def __init__(self):
            super().__init__()
            self.holder_ranges = []
            self.float_ranges = []
            self.repurchase_ranges = []
            self.pledge_snapshots = []

        def stk_holdertrade(self, **kwargs):
            requested = (kwargs["start_date"], kwargs["end_date"])
            self.holder_ranges.append(requested)
            if kwargs["start_date"] == "20260601":
                return pd.DataFrame()
            row = super().stk_holdertrade(**kwargs).iloc[0].to_dict()
            row["ann_date"] = kwargs["end_date"]
            return pd.DataFrame([row])

        def share_float(self, **kwargs):
            requested = (kwargs["start_date"], kwargs["end_date"])
            self.float_ranges.append(requested)
            if kwargs["start_date"] == "20260601":
                return pd.DataFrame()
            return super().share_float(**kwargs)

        def repurchase(self, **kwargs):
            requested = (kwargs["start_date"], kwargs["end_date"])
            self.repurchase_ranges.append(requested)
            if kwargs["start_date"] == "20260601":
                return pd.DataFrame()
            row = super().repurchase(**kwargs).iloc[0].to_dict()
            row["ann_date"] = kwargs["end_date"]
            return pd.DataFrame([row])

        def pledge_stat(self, **kwargs):
            self.pledge_snapshots.append(kwargs["end_date"])
            if kwargs["end_date"] in {"20260630", "20260626"}:
                return pd.DataFrame()
            return super().pledge_stat(**kwargs)

    pro = IncrementalActionPro()
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
            start=date(2026, 6, 1),
            through=date(2026, 7, 10),
            trading_dates=(),
            resume=True,
        )

    expected_month_ranges = [
        ("20260601", "20260630"),
        ("20260701", "20260710"),
        ("20260701", "20260710"),
    ]
    assert pro.holder_ranges == expected_month_ranges
    assert pro.float_ranges == expected_month_ranges
    assert pro.repurchase_ranges == expected_month_ranges
    assert pro.pledge_snapshots == [
        "20260630",
        "20260626",
        "20260619",
        "20260710",
        "20260710",
    ]


def test_first_week_refreshes_previous_month_for_late_event_arrivals(tmp_path):
    class TrackingPro(ActionPro):
        def __init__(self):
            super().__init__()
            self.holder_ranges = []
            self.repurchase_ranges = []

        def stk_holdertrade(self, **kwargs):
            self.holder_ranges.append((kwargs["start_date"], kwargs["end_date"]))
            return pd.DataFrame()

        def repurchase(self, **kwargs):
            self.repurchase_ranges.append(
                (kwargs["start_date"], kwargs["end_date"])
            )
            return pd.DataFrame()

        def pledge_stat(self, **kwargs):
            return pd.DataFrame()

    class TrackingAnnouncements:
        def __init__(self):
            self.ranges = []

        def fetch_announcements(self, start, through):
            self.ranges.append((start, through))
            return []

    pro = TrackingPro()
    announcements = TrackingAnnouncements()
    service = EventBackfillService(
        TushareResearchClient(pro, pacer=lambda method: None),
        announcements,
        ResearchWarehouse(tmp_path / "warehouse"),
    )

    for _ in range(2):
        service.backfill(
            start=date(2026, 7, 1),
            through=date(2026, 8, 4),
            trading_dates=(),
            resume=True,
        )

    expected = [
        (date(2026, 7, 1), date(2026, 7, 31)),
        (date(2026, 8, 1), date(2026, 8, 4)),
    ] * 2
    assert announcements.ranges == expected
    expected_text = [
        (start.strftime("%Y%m%d"), through.strftime("%Y%m%d"))
        for start, through in expected
    ]
    assert pro.holder_ranges == expected_text
    assert pro.repurchase_ranges == expected_text
