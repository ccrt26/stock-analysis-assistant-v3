from datetime import date, datetime, timezone

import pandas as pd

from stock_analyzer.data.research_contracts import FactBatch, ResearchDatasetId
from stock_analyzer.data.research_backfill import ResearchBackfillService
from stock_analyzer.storage.research_warehouse import ResearchWarehouse
from tests.test_tushare_research_client import FakePro
from stock_analyzer.data.tushare_research_client import TushareResearchClient


class CalendarPro(FakePro):
    security_name = "平安银行"

    def trade_cal(self, **kwargs):
        self.calls.append(("trade_cal", kwargs))
        return __import__("pandas").DataFrame(
            [
                {"exchange": "SSE", "cal_date": "20260709", "is_open": 1, "pretrade_date": "20260708"},
                {"exchange": "SSE", "cal_date": "20260710", "is_open": 1, "pretrade_date": "20260709"},
            ]
        )

    def stock_basic(self, **kwargs):
        self.calls.append(("stock_basic", kwargs))
        status = kwargs["list_status"]
        if status != "L":
            return __import__("pandas").DataFrame(columns=[
                "ts_code", "symbol", "name", "area", "industry", "market",
                "exchange", "list_status", "list_date", "delist_date", "is_hs"
            ])
        return __import__("pandas").DataFrame(
            [{
                "ts_code": "000001.SZ", "symbol": "000001", "name": self.security_name,
                "area": "深圳", "industry": "银行", "market": "主板",
                "exchange": "SZSE", "list_status": "L", "list_date": "19910403",
                "delist_date": None, "is_hs": "S"
            }]
        )


def test_security_master_refreshes_with_resume_and_unchanged_snapshot_converges(
    tmp_path,
):
    pro = CalendarPro()
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    service = ResearchBackfillService(
        TushareResearchClient(pro, pacer=lambda method: None),
        warehouse,
        broad_index_codes=(),
    )

    service.backfill_market_core(
        start=date(2026, 7, 10), through=date(2026, 7, 10), resume=True
    )
    service.backfill_market_core(
        start=date(2026, 7, 11), through=date(2026, 7, 11), resume=True
    )

    stock_basic_calls = [method for method, _ in pro.calls if method == "stock_basic"]
    master = warehouse.read_current(ResearchDatasetId.SECURITY_MASTER)
    assert len(stock_basic_calls) == 6
    assert len(master) == 1
    assert pd.Timestamp(master.iloc[0]["snapshot_date"]).date() == date(2026, 7, 10)
    assert warehouse.revision_count(ResearchDatasetId.SECURITY_MASTER) == 0


def test_security_master_content_change_becomes_an_observed_revision(tmp_path):
    pro = CalendarPro()
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    service = ResearchBackfillService(
        TushareResearchClient(pro, pacer=lambda method: None),
        warehouse,
        broad_index_codes=(),
    )
    service.backfill_market_core(
        start=date(2026, 7, 10), through=date(2026, 7, 10), resume=True
    )
    pro.security_name = "平安银行股份有限公司"

    service.backfill_market_core(
        start=date(2026, 7, 11), through=date(2026, 7, 11), resume=True
    )

    master = warehouse.read_current(ResearchDatasetId.SECURITY_MASTER)
    revisions = warehouse.revision_rows(ResearchDatasetId.SECURITY_MASTER)
    assert master.iloc[0]["name"] == "平安银行股份有限公司"
    assert len(revisions) == 1
    assert revisions[0]["row_payload"]["name"] == "平安银行"
    assert revisions[0]["valid_to"] >= revisions[0]["valid_from"]


def test_market_backfill_repairs_committed_partition_with_incomplete_vendor_schema(tmp_path):
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    existing = FactBatch(
        dataset_id=ResearchDatasetId.EQUITY_DAILY,
        partition_value="2026-07-09",
        source_name="legacy_formal",
        source_endpoint="legacy",
        ingestion_run_id="migration",
        ingested_at=datetime.now(timezone.utc),
        default_available_at=datetime(2026, 7, 9, 7, 1, tzinfo=timezone.utc),
        records=[{
            "trade_date": date(2026, 7, 9), "ts_code": "000001.SZ",
            "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.2,
            "pre_close": None, "change": None, "pct_chg": None,
            "volume": 100.0, "amount": 1000.0,
        }],
    )
    warehouse.commit_batch(existing)
    pro = CalendarPro()
    client = TushareResearchClient(pro, pacer=lambda method: None)
    service = ResearchBackfillService(client, warehouse, broad_index_codes=())

    summary = service.backfill_market_core(
        start=date(2026, 7, 9),
        through=date(2026, 7, 10),
        resume=True,
    )

    daily_calls = [kwargs for method, kwargs in pro.calls if method == "daily"]
    assert daily_calls == [
        {"trade_date": "20260709"},
        {"trade_date": "20260710"},
    ]
    assert summary.failed == 0
    assert warehouse.read_current(ResearchDatasetId.EQUITY_DAILY).shape[0] == 2
    assert warehouse.read_current(ResearchDatasetId.ADJ_FACTOR).shape[0] == 2
    repaired = warehouse.read_current(
        ResearchDatasetId.EQUITY_DAILY, partition_value="2026-07-09"
    )
    assert repaired[["pre_close", "change", "pct_chg"]].notna().all().all()
    calendar = warehouse.read_current(ResearchDatasetId.TRADE_CALENDAR)
    assert pd.to_datetime(calendar["available_at"], utc=True).dt.date.tolist() == [
        date(2026, 7, 9),
        date(2026, 7, 10),
    ]
    assert set(calendar["availability_precision"]) == {
        "inferred_from_endpoint_policy"
    }


def test_empty_required_daily_response_is_recorded_as_waiting_not_complete(tmp_path):
    pro = CalendarPro()
    pro.daily = lambda **kwargs: __import__("pandas").DataFrame(columns=[
        "ts_code", "trade_date", "open", "high", "low", "close", "pre_close",
        "change", "pct_chg", "vol", "amount"
    ])
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    service = ResearchBackfillService(
        TushareResearchClient(pro, pacer=lambda method: None),
        warehouse,
        broad_index_codes=(),
    )

    summary = service.backfill_market_core(
        start=date(2026, 7, 10),
        through=date(2026, 7, 10),
        resume=True,
    )

    assert summary.waiting_upstream == 1
    assert warehouse.read_current(ResearchDatasetId.EQUITY_DAILY).empty
