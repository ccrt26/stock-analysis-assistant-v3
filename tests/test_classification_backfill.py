from datetime import date, datetime, timedelta, timezone

import pandas as pd

from stock_analyzer.data.classification_backfill import ClassificationBackfillService
from stock_analyzer.data.research_contracts import FactBatch, ResearchDatasetId
from stock_analyzer.data.tushare_research_client import TushareResearchClient
from stock_analyzer.storage.research_warehouse import ResearchWarehouse


class ClassificationPro:
    def __init__(self):
        self.calls = []

    def index_classify(self, **kwargs):
        self.calls.append(("index_classify", kwargs))
        level = kwargs["level"]
        code = {"L1": "801010.SI", "L2": "801016.SI", "L3": "850113.SI"}[level]
        parent = {"L1": "0", "L2": "801010.SI", "L3": "801016.SI"}[level]
        return pd.DataFrame([{
            "index_code": code, "industry_name": level, "level": level,
            "industry_code": code[:6], "is_pub": "1", "parent_code": parent,
            "src": "SW2021",
        }])

    def index_basic(self, **kwargs):
        self.calls.append(("index_basic", kwargs))
        market = kwargs["market"]
        if market == "SW":
            return pd.DataFrame([
                {"ts_code": "801010.SI", "name": "L1", "market": "SW", "publisher": "申万",
                 "category": "行业指数", "base_date": "19991230", "base_point": 1000.0, "list_date": "20211213"},
                {"ts_code": "801016.SI", "name": "L2", "market": "SW", "publisher": "申万",
                 "category": "行业指数", "base_date": "19991230", "base_point": 1000.0, "list_date": "20211213"},
                {"ts_code": "850113.SI", "name": "L3", "market": "SW", "publisher": "申万",
                 "category": "行业指数", "base_date": "19991230", "base_point": 1000.0, "list_date": "20211213"},
            ])
        code = "000019.SH" if market == "SSE" else "399013.SZ"
        return pd.DataFrame([{
            "ts_code": code, "name": f"{market}主题", "market": market,
            "publisher": market, "category": "主题指数", "base_date": "20200101",
            "base_point": 1000.0, "list_date": "20200102",
        }])

    def index_member_all(self, **kwargs):
        self.calls.append(("index_member_all", kwargs))
        return pd.DataFrame([{
            "l1_code": "801010.SI", "l1_name": "L1", "l2_code": "801016.SI",
            "l2_name": "L2", "l3_code": "850113.SI", "l3_name": "L3",
            "ts_code": "000001.SZ", "name": "平安银行", "in_date": "20220101",
            "out_date": None, "is_new": "Y",
        }])

    def index_weight(self, **kwargs):
        self.calls.append(("index_weight", kwargs))
        return pd.DataFrame([{
            "index_code": kwargs["index_code"], "con_code": "000001.SZ",
            "trade_date": "20260710", "weight": 5.0,
        }])

    def index_daily(self, **kwargs):
        self.calls.append(("index_daily", kwargs))
        code = kwargs["ts_code"]
        return pd.DataFrame([{
            "ts_code": code, "trade_date": "20260710", "close": 1000.0,
            "open": 990.0, "high": 1010.0, "low": 980.0, "pre_close": 985.0,
            "change": 15.0, "pct_chg": 1.5, "vol": 10.0, "amount": 20.0,
        }])


def test_classification_backfill_builds_all_sw_levels_and_traceable_themes(tmp_path):
    pro = ClassificationPro()
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    service = ClassificationBackfillService(
        TushareResearchClient(pro, pacer=lambda method: None), warehouse
    )

    summary = service.backfill(
        start=date(2026, 7, 10), through=date(2026, 7, 10), resume=True
    )

    members = warehouse.read_current(ResearchDatasetId.INDUSTRY_MEMBER)
    themes = warehouse.read_current(ResearchDatasetId.THEME_CATALOG)
    theme_members = warehouse.read_current(ResearchDatasetId.THEME_MEMBER)
    assert set(members["level"]) == {"L1", "L2", "L3"}
    assert set(themes["publisher_market"]) == {"SSE", "SZSE"}
    assert set(theme_members["theme_code"]) == {"000019.SH", "399013.SZ"}
    assert summary.failed == 0
    assert all(method != "concept" for method, _ in pro.calls)


def test_classification_history_uses_latest_250_actual_trading_days(tmp_path):
    pro = ClassificationPro()
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    start = date(2025, 1, 1)
    calendar_rows = []
    for offset in range(400):
        value = start + timedelta(days=offset)
        calendar_rows.append(
            {
                "exchange": "SSE",
                "cal_date": value,
                "is_open": value.weekday() < 5,
                "pretrade_date": None,
            }
        )
    warehouse.commit_batch(
        FactBatch(
            dataset_id=ResearchDatasetId.TRADE_CALENDAR,
            partition_value="2025",
            source_name="test",
            source_endpoint="calendar",
            ingestion_run_id="calendar-2025",
            ingested_at=datetime.now(timezone.utc),
            default_available_at=datetime.now(timezone.utc),
            records=calendar_rows[:365],
        )
    )
    warehouse.commit_batch(
        FactBatch(
            dataset_id=ResearchDatasetId.TRADE_CALENDAR,
            partition_value="2026",
            source_name="test",
            source_endpoint="calendar",
            ingestion_run_id="calendar-2026",
            ingested_at=datetime.now(timezone.utc),
            default_available_at=datetime.now(timezone.utc),
            records=calendar_rows[365:],
        )
    )
    service = ClassificationBackfillService(
        TushareResearchClient(pro, pacer=lambda method: None), warehouse
    )
    through = calendar_rows[-1]["cal_date"]

    service.backfill(start=start, through=through, resume=True)

    index_calls = [kwargs for method, kwargs in pro.calls if method == "index_daily"]
    open_dates = [row["cal_date"] for row in calendar_rows if row["is_open"]]
    assert {kwargs["start_date"] for kwargs in index_calls} == {
        open_dates[-250].strftime("%Y%m%d")
    }


def test_classification_backfill_records_empty_theme_members_as_waiting(tmp_path):
    class OneEmptyThemePro(ClassificationPro):
        def index_weight(self, **kwargs):
            self.calls.append(("index_weight", kwargs))
            if kwargs["index_code"] == "000019.SH":
                return pd.DataFrame()
            return pd.DataFrame(
                [
                    {
                        "index_code": kwargs["index_code"],
                        "con_code": "000001.SZ",
                        "trade_date": "20260710",
                        "weight": 5.0,
                    }
                ]
            )

    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    service = ClassificationBackfillService(
        TushareResearchClient(OneEmptyThemePro(), pacer=lambda method: None),
        warehouse,
    )

    summary = service.backfill(
        start=date(2026, 7, 10), through=date(2026, 7, 10), resume=True
    )

    members = warehouse.read_current(ResearchDatasetId.THEME_MEMBER)
    assert set(members["theme_code"]) == {"399013.SZ"}
    assert summary.waiting_upstream == 1


def test_classification_backfill_records_empty_index_history_as_waiting(tmp_path):
    class OneEmptyIndexPro(ClassificationPro):
        def index_daily(self, **kwargs):
            self.calls.append(("index_daily", kwargs))
            if kwargs["ts_code"] == "801010.SI":
                return pd.DataFrame()
            return pd.DataFrame(
                [
                    {
                        "ts_code": kwargs["ts_code"],
                        "trade_date": "20260710",
                        "close": 1000.0,
                        "open": 990.0,
                        "high": 1010.0,
                        "low": 980.0,
                        "pre_close": 985.0,
                        "change": 15.0,
                        "pct_chg": 1.5,
                        "vol": 10.0,
                        "amount": 20.0,
                    }
                ]
            )

    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    service = ClassificationBackfillService(
        TushareResearchClient(OneEmptyIndexPro(), pacer=lambda method: None),
        warehouse,
    )

    summary = service.backfill(
        start=date(2026, 7, 10), through=date(2026, 7, 10), resume=True
    )

    industry = warehouse.read_current(ResearchDatasetId.INDUSTRY_DAILY)
    assert "801010.SI" not in set(industry["industry_code"])
    assert summary.waiting_upstream == 1
