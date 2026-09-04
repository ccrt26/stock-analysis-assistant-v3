from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pytest

from stock_analyzer.data.classification_backfill import ClassificationBackfillService
from stock_analyzer.data.research_contracts import FactBatch, ResearchDatasetId
from stock_analyzer.data.tushare_research_client import TushareResearchClient
from stock_analyzer.storage.research_query import ResearchQuery
from stock_analyzer.storage.research_schema import connect_research_warehouse
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

    def sw_daily(self, **kwargs):
        self.calls.append(("sw_daily", kwargs))
        trade_date = kwargs.get("trade_date", "20260710")
        return pd.DataFrame([{
            "ts_code": "801010.SI", "trade_date": trade_date, "name": "L1",
            "close": 1000.0, "open": 990.0, "high": 1010.0,
            "low": 980.0, "change": 15.0, "pct_change": 1.5,
            "vol": 10.0, "amount": 20.0, "pe": 20.0, "pb": 2.0,
            "float_mv": 3.0, "total_mv": 4.0,
        }])


class MissingListDateClassificationPro(ClassificationPro):
    def __init__(self):
        super().__init__()
        self.l3_name = "L3"
        self.l3_list_date = None

    def index_classify(self, **kwargs):
        frame = super().index_classify(**kwargs)
        if kwargs["level"] == "L3":
            frame.loc[:, "industry_name"] = self.l3_name
        return frame

    def index_basic(self, **kwargs):
        frame = super().index_basic(**kwargs)
        if kwargs["market"] == "SW":
            frame.loc[
                frame["ts_code"] == "850113.SI", "list_date"
            ] = self.l3_list_date
        return frame


class MutableMemberClassificationPro(ClassificationPro):
    def __init__(self):
        super().__init__()
        self.member_valid_from = "20220101"
        self.member_valid_to = None
        self.member_is_new = "Y"
        self.member_codes = {
            "L1": ("801010.SI", "L1"),
            "L2": ("801016.SI", "L2"),
            "L3": ("850113.SI", "L3"),
        }

    def index_member_all(self, **kwargs):
        self.calls.append(("index_member_all", kwargs))
        return pd.DataFrame([{
            "l1_code": self.member_codes["L1"][0],
            "l1_name": self.member_codes["L1"][1],
            "l2_code": self.member_codes["L2"][0],
            "l2_name": self.member_codes["L2"][1],
            "l3_code": self.member_codes["L3"][0],
            "l3_name": self.member_codes["L3"][1],
            "ts_code": "000001.SZ",
            "name": "平安银行",
            "in_date": self.member_valid_from,
            "out_date": self.member_valid_to,
            "is_new": self.member_is_new,
        }])

def test_classification_backfill_builds_all_sw_levels_and_traceable_themes(tmp_path):
    pro = ClassificationPro()
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    available_at = datetime(2026, 7, 10, 10, tzinfo=timezone.utc)
    warehouse.commit_batch(
        FactBatch(
            dataset_id=ResearchDatasetId.TRADE_CALENDAR,
            partition_value="2026",
            source_name="test",
            source_endpoint="calendar",
            ingestion_run_id="calendar-2026",
            ingested_at=available_at,
            default_available_at=available_at,
            records=[
                {
                    "exchange": "SSE",
                    "cal_date": date(2026, 7, 10),
                    "is_open": True,
                    "pretrade_date": None,
                }
            ],
        )
    )
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
    industry_daily_calls = [
        kwargs["trade_date"]
        for method, kwargs in pro.calls
        if method == "sw_daily"
    ]
    assert industry_daily_calls == []
    assert all(
        not (method == "index_daily" and kwargs.get("ts_code", "").endswith(".SI"))
        for method, kwargs in pro.calls
    )
    industry_proxy = warehouse.read_current(
        ResearchDatasetId.INDUSTRY_DAILY_PROXY
    )
    theme_daily = warehouse.read_current(ResearchDatasetId.THEME_DAILY)
    assert industry_proxy.empty
    assert set(theme_daily["availability_precision"]) == {
        "inferred_from_endpoint_policy"
    }


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


def test_classification_backfill_records_empty_theme_members_as_source_limit(tmp_path):
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
    controlled = ResearchQuery(warehouse).controlled_themes_as_of(
        datetime(2026, 7, 10, 10, tzinfo=timezone.utc)
    )
    assert set(members["theme_code"]) == {"399013.SZ"}
    assert set(controlled["theme_code"]) == {"399013.SZ"}
    assert summary.waiting_upstream == 1
    assert summary.limited == 1
    assert summary.limitations_checked
    assert set(summary.issues) == {
        "industry_daily_proxy:2026-07-10:missing_previous_trading_session",
        "theme_member:000019.SH:source_unavailable",
    }


def test_classification_backfill_records_empty_index_history_as_waiting(tmp_path):
    class OneEmptyIndexPro(ClassificationPro):
        def sw_daily(self, **kwargs):
            self.calls.append(("sw_daily", kwargs))
            return pd.DataFrame()

    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    service = ClassificationBackfillService(
        TushareResearchClient(OneEmptyIndexPro(), pacer=lambda method: None),
        warehouse,
    )

    summary = service.backfill(
        start=date(2026, 7, 10), through=date(2026, 7, 10), resume=True
    )

    industry = warehouse.read_current(ResearchDatasetId.INDUSTRY_DAILY)
    assert industry.empty
    assert summary.waiting_upstream == 1


def test_legacy_industry_daily_is_not_an_active_refresh_dataset(tmp_path):
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    service = ClassificationBackfillService(
        TushareResearchClient(ClassificationPro(), pacer=lambda method: None),
        warehouse,
    )

    with pytest.raises(ValueError, match="only supports industry/theme"):
        service.refresh_daily(
            date(2026, 7, 13),
            datasets=(ResearchDatasetId.INDUSTRY_DAILY,),
            refresh_memberships=False,
        )

def test_industry_history_stops_after_permission_denial_and_classifies_remaining_dates(
    tmp_path,
):
    class DeniedHistoryPro(ClassificationPro):
        def sw_daily(self, **kwargs):
            self.calls.append(("sw_daily", kwargs))
            raise RuntimeError("抱歉，您没有接口访问权限")

    pro = DeniedHistoryPro()
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    dates = (date(2026, 7, 8), date(2026, 7, 9), date(2026, 7, 10))
    warehouse.commit_batch(
        FactBatch(
            dataset_id=ResearchDatasetId.TRADE_CALENDAR,
            partition_value="2026", source_name="tushare",
            source_endpoint="trade_cal", ingestion_run_id="calendar",
            ingested_at=datetime.now(timezone.utc),
            default_available_at=datetime.now(timezone.utc),
            records=[{
                "exchange": "SSE", "cal_date": value, "is_open": True,
                "pretrade_date": None,
            } for value in dates],
        )
    )
    summary = ClassificationBackfillService(
        TushareResearchClient(pro, pacer=lambda method: None), warehouse
    ).backfill(start=dates[0], through=dates[-1], resume=False)

    assert len([1 for method, _ in pro.calls if method == "sw_daily"]) == 0
    assert summary.waiting_upstream == len(dates)
    with connect_research_warehouse(
        warehouse.duckdb_path, read_only=True
    ) as connection:
        rows = connection.execute(
            """
            select partition_value, status from research_data_gaps
            where dataset_id = 'industry_daily_proxy' order by partition_value
            """
        ).fetchall()
    assert rows == [
        (value.isoformat(), "unclassified_missing") for value in dates
    ]


def test_classification_daily_history_keeps_only_a_share_open_dates(tmp_path):
    class HolidayIndexPro(ClassificationPro):
        def index_daily(self, **kwargs):
            self.calls.append(("index_daily", kwargs))
            return pd.DataFrame(
                [
                    {
                        "ts_code": kwargs["ts_code"],
                        "trade_date": trade_date,
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
                    for trade_date in ("20260710", "20260711")
                ]
            )

    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    warehouse.commit_batch(
        FactBatch(
            dataset_id=ResearchDatasetId.TRADE_CALENDAR,
            partition_value="2026",
            source_name="test",
            source_endpoint="calendar",
            ingestion_run_id="calendar-2026",
            ingested_at=datetime.now(timezone.utc),
            default_available_at=datetime.now(timezone.utc),
            records=[
                {
                    "exchange": "SSE",
                    "cal_date": date(2026, 7, 10),
                    "is_open": True,
                    "pretrade_date": None,
                },
                {
                    "exchange": "SSE",
                    "cal_date": date(2026, 7, 11),
                    "is_open": False,
                    "pretrade_date": date(2026, 7, 10),
                },
            ],
        )
    )
    service = ClassificationBackfillService(
        TushareResearchClient(HolidayIndexPro(), pacer=lambda method: None),
        warehouse,
    )

    service.backfill(
        start=date(2026, 7, 10), through=date(2026, 7, 11), resume=True
    )

    themes = warehouse.read_current(ResearchDatasetId.THEME_DAILY)
    assert set(pd.to_datetime(themes["trade_date"]).dt.date) == {
        date(2026, 7, 10)
    }


def test_classification_resume_does_not_refetch_complete_daily_partitions(tmp_path):
    pro = ClassificationPro()
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    available_at = datetime(2026, 7, 10, 10, tzinfo=timezone.utc)
    warehouse.commit_batch(
        FactBatch(
            dataset_id=ResearchDatasetId.TRADE_CALENDAR,
            partition_value="2026",
            source_name="test",
            source_endpoint="calendar",
            ingestion_run_id="calendar-2026",
            ingested_at=available_at,
            default_available_at=available_at,
            records=[
                {
                    "exchange": "SSE",
                    "cal_date": date(2026, 7, 10),
                    "is_open": True,
                    "pretrade_date": None,
                }
            ],
        )
    )
    for dataset, code_field, codes in (
        (
            ResearchDatasetId.INDUSTRY_DAILY,
            "industry_code",
            ("801010.SI",),
        ),
        (
            ResearchDatasetId.THEME_DAILY,
            "theme_code",
            ("000019.SH", "399013.SZ"),
        ),
    ):
        warehouse.commit_batch(
            FactBatch(
                dataset_id=dataset,
                partition_value="2026-07-10",
                source_name="test",
                source_endpoint="index_daily",
                ingestion_run_id=f"{dataset.value}-20260710",
                ingested_at=available_at,
                default_available_at=available_at,
                records=[
                    {
                        "trade_date": date(2026, 7, 10),
                        code_field: code,
                        "open": 990.0,
                        "high": 1010.0,
                        "low": 980.0,
                        "close": 1000.0,
                        "volume": 1000.0,
                        "amount": 2000.0,
                    }
                    for code in codes
                ],
            )
        )
    service = ClassificationBackfillService(
        TushareResearchClient(pro, pacer=lambda method: None), warehouse
    )

    service.backfill(
        start=date(2026, 7, 10), through=date(2026, 7, 10), resume=True
    )

    assert all(method != "index_daily" for method, _ in pro.calls)


def test_classification_resume_skips_all_complete_catalog_and_member_requests(
    tmp_path,
):
    pro = ClassificationPro()
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    available_at = datetime(2026, 7, 10, 10, tzinfo=timezone.utc)
    warehouse.commit_batch(
        FactBatch(
            dataset_id=ResearchDatasetId.TRADE_CALENDAR,
            partition_value="2026",
            source_name="test",
            source_endpoint="calendar",
            ingestion_run_id="calendar-2026",
            ingested_at=available_at,
            default_available_at=available_at,
            records=[
                {
                    "exchange": "SSE",
                    "cal_date": date(2026, 7, 10),
                    "is_open": True,
                    "pretrade_date": None,
                }
            ],
        )
    )
    service = ClassificationBackfillService(
        TushareResearchClient(pro, pacer=lambda method: None), warehouse
    )
    service.backfill(
        start=date(2026, 7, 10), through=date(2026, 7, 10), resume=True
    )
    pro.calls.clear()

    service.backfill(
        start=date(2026, 7, 10), through=date(2026, 7, 10), resume=True
    )

    assert pro.calls == []


def test_missing_sw_list_date_reuses_first_observed_effective_date(tmp_path):
    pro = MissingListDateClassificationPro()
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    service = ClassificationBackfillService(
        TushareResearchClient(pro, pacer=lambda method: None), warehouse
    )

    service.backfill(
        start=date(2026, 7, 13), through=date(2026, 7, 13), resume=False
    )
    pro.l3_list_date = "20200101"
    service.backfill(
        start=date(2026, 8, 3), through=date(2026, 8, 3), resume=False
    )

    catalog = warehouse.read_current(ResearchDatasetId.INDUSTRY_CATALOG)
    target = catalog[catalog["industry_code"].astype(str) == "850113.SI"]
    active = target[pd.to_datetime(target["valid_to"], errors="coerce").isna()]

    assert len(target) == 1
    assert len(active) == 1
    assert pd.Timestamp(active.iloc[0]["valid_from"]).date() == date(2026, 7, 13)


def test_missing_sw_list_date_closes_prior_definition_when_attributes_change(
    tmp_path,
):
    pro = MissingListDateClassificationPro()
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    service = ClassificationBackfillService(
        TushareResearchClient(pro, pacer=lambda method: None), warehouse
    )
    service.backfill(
        start=date(2026, 7, 13), through=date(2026, 7, 13), resume=False
    )

    pro.l3_name = "更新后的L3"
    pro.l3_list_date = "20200101"
    service.backfill(
        start=date(2026, 8, 3), through=date(2026, 8, 3), resume=False
    )

    catalog = warehouse.read_current(ResearchDatasetId.INDUSTRY_CATALOG)
    target = catalog[
        catalog["industry_code"].astype(str) == "850113.SI"
    ].sort_values("valid_from")

    assert target["industry_name"].tolist() == ["L3", "更新后的L3"]
    assert pd.Timestamp(target.iloc[0]["valid_from"]).date() == date(2026, 7, 13)
    assert pd.Timestamp(target.iloc[0]["valid_to"]).date() == date(2026, 8, 2)
    assert pd.Timestamp(target.iloc[1]["valid_from"]).date() == date(2026, 8, 3)
    assert pd.isna(target.iloc[1]["valid_to"])


def _refresh_mutable_membership(
    service: ClassificationBackfillService,
    data_date: date,
) -> None:
    service.backfill(start=data_date, through=data_date, resume=False)


def _member_rows(
    warehouse: ResearchWarehouse,
    *,
    level: str = "L1",
) -> pd.DataFrame:
    frame = warehouse.read_current(ResearchDatasetId.INDUSTRY_MEMBER)
    return frame[
        (frame["ts_code"].astype(str) == "000001.SZ")
        & (frame["level"].astype(str) == level)
    ].sort_values("valid_from").reset_index(drop=True)


def test_identical_industry_member_refresh_is_idempotent(tmp_path):
    pro = MutableMemberClassificationPro()
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    service = ClassificationBackfillService(
        TushareResearchClient(pro, pacer=lambda method: None), warehouse
    )

    _refresh_mutable_membership(service, date(2026, 7, 10))
    before = _member_rows(warehouse)
    revision_count = warehouse.revision_count(ResearchDatasetId.INDUSTRY_MEMBER)
    _refresh_mutable_membership(service, date(2026, 8, 3))
    after = _member_rows(warehouse)

    assert len(after) == 1
    assert after.iloc[0]["business_key_hash"] == before.iloc[0]["business_key_hash"]
    assert after.iloc[0]["available_at"] == before.iloc[0]["available_at"]
    assert warehouse.revision_count(ResearchDatasetId.INDUSTRY_MEMBER) == revision_count


def test_later_same_industry_member_start_closes_old_version_and_repeat_converges(
    tmp_path,
):
    pro = MutableMemberClassificationPro()
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    service = ClassificationBackfillService(
        TushareResearchClient(pro, pacer=lambda method: None), warehouse
    )
    _refresh_mutable_membership(service, date(2026, 7, 10))

    pro.member_valid_from = "20260701"
    receipt_lower_bound = datetime.now(timezone.utc)
    _refresh_mutable_membership(service, date(2026, 8, 3))
    first = _member_rows(warehouse)
    first_revision_count = warehouse.revision_count(
        ResearchDatasetId.INDUSTRY_MEMBER
    )

    assert len(first) == 2
    assert pd.Timestamp(first.iloc[0]["valid_to"]).date() == date(2026, 6, 30)
    assert bool(first.iloc[0]["is_current"]) is False
    assert pd.isna(first.iloc[1]["valid_to"])
    assert pd.Timestamp(first.iloc[1]["available_at"]).to_pydatetime() >= (
        receipt_lower_bound
    )
    transition_available_at = pd.Timestamp(
        first.iloc[1]["available_at"]
    ).to_pydatetime()
    with connect_research_warehouse(
        warehouse.duckdb_path, read_only=True
    ) as connection:
        revision_valid_to = connection.execute(
            "select cast(valid_to as varchar) from research_fact_revisions "
            "where dataset_id = 'industry_member'"
        ).fetchone()[0]
    assert pd.Timestamp(revision_valid_to).to_pydatetime() == transition_available_at

    _refresh_mutable_membership(service, date(2026, 8, 3))
    repeated = _member_rows(warehouse)
    assert len(repeated) == 2
    assert warehouse.revision_count(
        ResearchDatasetId.INDUSTRY_MEMBER
    ) == first_revision_count


def test_industry_change_is_visible_only_after_local_receipt(tmp_path):
    pro = MutableMemberClassificationPro()
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    service = ClassificationBackfillService(
        TushareResearchClient(pro, pacer=lambda method: None), warehouse
    )
    _refresh_mutable_membership(service, date(2026, 7, 10))

    pro.member_valid_from = "20260701"
    pro.member_codes["L1"] = ("801020.SI", "采掘")
    _refresh_mutable_membership(service, date(2026, 8, 3))

    query = ResearchQuery(warehouse)
    before_receipt = query.dataset_as_of(
        ResearchDatasetId.INDUSTRY_MEMBER,
        datetime(2026, 7, 15, 12, tzinfo=timezone.utc),
    )
    after_receipt = query.dataset_as_of(
        ResearchDatasetId.INDUSTRY_MEMBER,
        datetime.now(timezone.utc) + timedelta(minutes=1),
    )
    before_l1 = before_receipt[
        (before_receipt["ts_code"].astype(str) == "000001.SZ")
        & (before_receipt["level"].astype(str) == "L1")
    ]
    after_l1 = after_receipt[
        (after_receipt["ts_code"].astype(str) == "000001.SZ")
        & (after_receipt["level"].astype(str) == "L1")
    ].sort_values("valid_from")

    assert before_l1["industry_code"].astype(str).tolist() == ["801010.SI"]
    assert pd.isna(before_l1.iloc[0]["valid_to"])
    assert after_l1["industry_code"].astype(str).tolist() == [
        "801010.SI",
        "801020.SI",
    ]
    assert pd.Timestamp(after_l1.iloc[0]["valid_to"]).date() == date(2026, 6, 30)


def test_real_exit_and_reentry_preserve_two_non_overlapping_member_versions(
    tmp_path,
):
    pro = MutableMemberClassificationPro()
    pro.member_valid_to = "20260630"
    pro.member_is_new = "N"
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    service = ClassificationBackfillService(
        TushareResearchClient(pro, pacer=lambda method: None), warehouse
    )
    _refresh_mutable_membership(service, date(2026, 7, 10))

    pro.member_valid_from = "20260701"
    pro.member_valid_to = None
    pro.member_is_new = "Y"
    receipt_lower_bound = datetime.now(timezone.utc)
    _refresh_mutable_membership(service, date(2026, 8, 3))
    rows = _member_rows(warehouse)

    assert len(rows) == 2
    assert pd.Timestamp(rows.iloc[0]["valid_to"]).date() == date(2026, 6, 30)
    assert pd.Timestamp(rows.iloc[1]["valid_from"]).date() == date(2026, 7, 1)
    assert pd.Timestamp(rows.iloc[1]["available_at"]).to_pydatetime() >= (
        receipt_lower_bound
    )


def test_later_observed_exit_and_reentry_preserve_the_real_gap(tmp_path):
    class ExitAndReentryPro(MutableMemberClassificationPro):
        def __init__(self):
            super().__init__()
            self.include_reentry = False

        def index_member_all(self, **kwargs):
            frame = super().index_member_all(**kwargs)
            if not self.include_reentry:
                return frame
            exited = frame.iloc[0].copy()
            exited["out_date"] = "20260630"
            exited["is_new"] = "N"
            reentry = exited.copy()
            reentry["in_date"] = "20260715"
            reentry["out_date"] = None
            reentry["is_new"] = "Y"
            return pd.DataFrame([exited, reentry])

    pro = ExitAndReentryPro()
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    service = ClassificationBackfillService(
        TushareResearchClient(pro, pacer=lambda method: None), warehouse
    )
    _refresh_mutable_membership(service, date(2026, 7, 10))
    pro.include_reentry = True
    _refresh_mutable_membership(service, date(2026, 8, 3))

    rows = _member_rows(warehouse)
    transition_time = pd.Timestamp(rows.iloc[1]["available_at"]).to_pydatetime()
    query = ResearchQuery(warehouse)
    before = query.dataset_as_of(
        ResearchDatasetId.INDUSTRY_MEMBER,
        transition_time - timedelta(microseconds=1),
    )
    before = before[
        (before["ts_code"].astype(str) == "000001.SZ")
        & (before["level"].astype(str) == "L1")
    ]

    assert len(rows) == 2
    assert pd.Timestamp(rows.iloc[0]["valid_to"]).date() == date(2026, 6, 30)
    assert pd.Timestamp(rows.iloc[1]["valid_from"]).date() == date(2026, 7, 15)
    assert pd.isna(rows.iloc[1]["valid_to"])
    assert pd.Timestamp(rows.iloc[0]["available_at"]) == pd.Timestamp(
        transition_time
    )
    assert len(before) == 1
    assert pd.isna(before.iloc[0]["valid_to"])


@pytest.mark.parametrize("conflicting_start", ["20210101", "20220101"])
def test_conflicting_member_start_does_not_silently_rewrite_history(
    tmp_path,
    conflicting_start,
):
    pro = MutableMemberClassificationPro()
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    service = ClassificationBackfillService(
        TushareResearchClient(pro, pacer=lambda method: None), warehouse
    )
    _refresh_mutable_membership(service, date(2026, 7, 10))

    pro.member_valid_from = conflicting_start
    pro.member_codes["L1"] = ("801020.SI", "采掘")

    with pytest.raises(ValueError, match="industry member.*conflict"):
        _refresh_mutable_membership(service, date(2026, 8, 3))


def test_same_member_effective_date_with_changed_name_is_rejected(tmp_path):
    pro = MutableMemberClassificationPro()
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    service = ClassificationBackfillService(
        TushareResearchClient(pro, pacer=lambda method: None), warehouse
    )
    _refresh_mutable_membership(service, date(2026, 7, 10))

    pro.member_codes["L1"] = ("801010.SI", "被篡改的行业名")

    with pytest.raises(ValueError, match="industry member.*conflict"):
        _refresh_mutable_membership(service, date(2026, 8, 3))


def test_conflicting_duplicate_member_rows_from_source_are_rejected(tmp_path):
    class ConflictingDuplicateMemberPro(MutableMemberClassificationPro):
        def index_member_all(self, **kwargs):
            frame = super().index_member_all(**kwargs)
            conflicting = frame.copy()
            conflicting.loc[:, "l1_name"] = "冲突的行业名"
            return pd.concat([frame, conflicting], ignore_index=True)

    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    service = ClassificationBackfillService(
        TushareResearchClient(
            ConflictingDuplicateMemberPro(), pacer=lambda method: None
        ),
        warehouse,
    )

    with pytest.raises(ValueError, match="conflicting industry member source rows"):
        _refresh_mutable_membership(service, date(2026, 7, 10))


def test_exact_duplicate_member_rows_from_source_converge(tmp_path):
    class ExactDuplicateMemberPro(MutableMemberClassificationPro):
        def index_member_all(self, **kwargs):
            frame = super().index_member_all(**kwargs)
            return pd.concat([frame, frame.copy()], ignore_index=True)

    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    service = ClassificationBackfillService(
        TushareResearchClient(
            ExactDuplicateMemberPro(), pacer=lambda method: None
        ),
        warehouse,
    )

    _refresh_mutable_membership(service, date(2026, 7, 10))

    members = warehouse.read_current(ResearchDatasetId.INDUSTRY_MEMBER)
    assert len(members) == 3
    assert set(members["level"].astype(str)) == {"L1", "L2", "L3"}


def test_new_member_slot_with_two_source_versions_is_reconciled_in_one_batch(
    tmp_path,
):
    class NewSlotHistoryPro(MutableMemberClassificationPro):
        def __init__(self):
            super().__init__()
            self.include_history = False

        def index_member_all(self, **kwargs):
            frame = super().index_member_all(**kwargs)
            if not self.include_history:
                return frame
            older = frame.iloc[0].copy()
            older["ts_code"] = "000002.SZ"
            older["name"] = "万科A"
            older["in_date"] = "20200101"
            newer = older.copy()
            newer["in_date"] = "20260701"
            return pd.concat(
                [frame, pd.DataFrame([older, newer])],
                ignore_index=True,
            )

    pro = NewSlotHistoryPro()
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    service = ClassificationBackfillService(
        TushareResearchClient(pro, pacer=lambda method: None), warehouse
    )
    _refresh_mutable_membership(service, date(2026, 7, 10))
    pro.include_history = True
    receipt_lower_bound = datetime.now(timezone.utc)

    _refresh_mutable_membership(service, date(2026, 8, 3))

    members = warehouse.read_current(ResearchDatasetId.INDUSTRY_MEMBER)
    target = members[
        (members["ts_code"].astype(str) == "000002.SZ")
        & (members["level"].astype(str) == "L1")
    ].sort_values("valid_from")
    assert len(target) == 2
    assert pd.Timestamp(target.iloc[0]["valid_to"]).date() == date(2026, 6, 30)
    assert pd.isna(target.iloc[1]["valid_to"])
    assert pd.Timestamp(target.iloc[1]["available_at"]).to_pydatetime() >= (
        receipt_lower_bound
    )


class NoSwDailyClassificationPro(ClassificationPro):
    def sw_daily(self, **kwargs):
        raise AssertionError("active proxy path must not call sw_daily")


def _commit_proxy_inputs(
    warehouse: ResearchWarehouse,
    *,
    member_codes: tuple[str, ...] = ("000001.SZ", "000002.SZ"),
) -> None:
    observed = datetime(2026, 9, 2, 7, 1, tzinfo=timezone.utc)
    warehouse.commit_batch(
        FactBatch(
            dataset_id=ResearchDatasetId.TRADE_CALENDAR,
            partition_value="2026",
            source_name="tushare",
            source_endpoint="trade_cal",
            ingestion_run_id="proxy-calendar",
            ingested_at=observed,
            default_available_at=observed,
            records=[
                {"exchange": "SSE", "cal_date": date(2026, 9, 1), "is_open": True, "pretrade_date": date(2026, 8, 31)},
                {"exchange": "SSE", "cal_date": date(2026, 9, 2), "is_open": True, "pretrade_date": date(2026, 9, 1)},
            ],
        )
    )
    warehouse.commit_batch(
        FactBatch(
            dataset_id=ResearchDatasetId.INDUSTRY_CATALOG,
            partition_value="SW2021",
            source_name="tushare",
            source_endpoint="index_classify+index_basic",
            ingestion_run_id="proxy-catalog",
            ingested_at=observed,
            default_available_at=observed,
            records=[{
                "industry_system": "SW2021",
                "level": "L1",
                "industry_code": "801010.SI",
                "classification_code": "110000",
                "industry_name": "农林牧渔",
                "parent_code": "0",
                "is_published": "1",
                "valid_from": date(2021, 12, 13),
                "valid_to": None,
            }],
        )
    )
    warehouse.commit_batch(
        FactBatch(
            dataset_id=ResearchDatasetId.SECURITY_MASTER,
            partition_value="security-master",
            source_name="tushare",
            source_endpoint="stock_basic",
            ingestion_run_id="proxy-security-master",
            ingested_at=observed,
            default_available_at=observed,
            records=[
                {
                    "ts_code": code,
                    "valid_from": date(2020, 1, 1),
                    "valid_to": None,
                    "list_date": date(2020, 1, 1),
                    "delist_date": None,
                    "list_status": "L",
                }
                for code in member_codes
            ],
        )
    )
    warehouse.commit_batch(
        FactBatch(
            dataset_id=ResearchDatasetId.INDUSTRY_MEMBER,
            partition_value="SW2021",
            source_name="tushare",
            source_endpoint="index_member_all",
            ingestion_run_id="proxy-members",
            ingested_at=observed,
            default_available_at=observed,
            records=[
                {
                    "ts_code": code,
                    "security_name": code,
                    "industry_system": "SW2021",
                    "level": "L1",
                    "industry_code": "801010.SI",
                    "industry_name": "农林牧渔",
                    "valid_from": date(2021, 12, 13),
                    "valid_to": None,
                    "is_current": True,
                }
                for code in member_codes
            ],
        )
    )
    for trading_day, prices, changes in (
        (date(2026, 9, 1), (10.0, 20.0), (0.0, 0.0)),
        (date(2026, 9, 2), (11.0, 19.0), (10.0, -5.0)),
    ):
        warehouse.commit_batch(
            FactBatch(
                dataset_id=ResearchDatasetId.EQUITY_DAILY,
                partition_value=trading_day.isoformat(),
                source_name="tushare",
                source_endpoint="daily",
                ingestion_run_id=f"proxy-equity-{trading_day}",
                ingested_at=observed,
                default_available_at=observed,
                records=[
                    {
                        "trade_date": trading_day,
                        "ts_code": code,
                        "open": price,
                        "high": price,
                        "low": price,
                        "close": price,
                        "pre_close": price,
                        "change": 0.0,
                        "pct_chg": change,
                        "volume": 100.0,
                        "amount": 1000.0,
                    }
                    for code, price, change in zip(
                        ("000001.SZ", "000002.SZ"), prices, changes
                    )
                ],
            )
        )
    warehouse.commit_batch(
        FactBatch(
            dataset_id=ResearchDatasetId.DAILY_BASIC,
            partition_value="2026-09-01",
            source_name="tushare",
            source_endpoint="daily_basic",
            ingestion_run_id="proxy-basic",
            ingested_at=observed,
            default_available_at=observed,
            records=[
                {"trade_date": date(2026, 9, 1), "ts_code": "000001.SZ", "free_share": 100.0},
                {"trade_date": date(2026, 9, 1), "ts_code": "000002.SZ", "free_share": 200.0},
            ],
        )
    )


def test_daily_proxy_refresh_uses_local_facts_is_idempotent_and_resolves_legacy_gap(tmp_path):
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    _commit_proxy_inputs(warehouse)
    from stock_analyzer.storage.research_gap_registry import ResearchGapRegistry

    gaps = ResearchGapRegistry(warehouse.duckdb_path)
    gaps.record(
        ResearchDatasetId.INDUSTRY_DAILY,
        date(2026, 9, 2),
        status="permission_denied",
        reason_category="permission_denied",
        source_name="tushare",
        source_endpoint="sw_daily",
    )
    service = ClassificationBackfillService(
        TushareResearchClient(NoSwDailyClassificationPro(), pacer=lambda method: None),
        warehouse,
    )

    first = service.refresh_daily(
        date(2026, 9, 2),
        datasets=(ResearchDatasetId.INDUSTRY_DAILY_PROXY,),
        refresh_memberships=False,
    )
    second = service.refresh_daily(
        date(2026, 9, 2),
        datasets=(ResearchDatasetId.INDUSTRY_DAILY_PROXY,),
        refresh_memberships=False,
    )

    proxy = warehouse.read_current(
        ResearchDatasetId.INDUSTRY_DAILY_PROXY,
        partition_value="2026-09-02",
    )
    assert first.committed == 1
    assert second.committed == 1
    assert len(proxy) == 1
    assert proxy.iloc[0]["proxy_return"] == pytest.approx(-0.02)
    assert set(proxy["source_name"]) == {"local_derived"}
    assert set(proxy["source_endpoint"]) == {"sw_l1_free_float_proxy_v1"}
    assert warehouse.revision_rows(ResearchDatasetId.INDUSTRY_DAILY_PROXY) == []
    with connect_research_warehouse(warehouse.duckdb_path, read_only=True) as connection:
        status, detail = connection.execute(
            """
            select status, detail_json from research_data_gaps
            where dataset_id = 'industry_daily' and partition_value = '2026-09-02'
            """
        ).fetchone()
    assert status == "resolved"
    assert "industry_daily_proxy" in detail
    assert "sw_l1_free_float_proxy_v1" in detail


def test_daily_proxy_refresh_records_low_member_coverage_as_active_gap(tmp_path):
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    _commit_proxy_inputs(
        warehouse,
        member_codes=(
            "000001.SZ",
            "000002.SZ",
            "000003.SZ",
            "000004.SZ",
            "000005.SZ",
        ),
    )
    service = ClassificationBackfillService(
        TushareResearchClient(NoSwDailyClassificationPro(), pacer=lambda method: None),
        warehouse,
    )

    summary = service.refresh_daily(
        date(2026, 9, 2),
        datasets=(ResearchDatasetId.INDUSTRY_DAILY_PROXY,),
        refresh_memberships=False,
    )

    proxy = warehouse.read_current(
        ResearchDatasetId.INDUSTRY_DAILY_PROXY,
        partition_value="2026-09-02",
    )
    assert summary.limited == 1
    assert pd.isna(proxy.iloc[0]["proxy_return"])
    with connect_research_warehouse(warehouse.duckdb_path, read_only=True) as connection:
        row = connection.execute(
            """
            select status, reason_category from research_data_gaps
            where dataset_id = 'industry_daily_proxy'
              and partition_value = '2026-09-02'
            """
        ).fetchone()
    assert row == ("unclassified_missing", "member_coverage_below_80_percent")


def test_proxy_uses_security_master_version_known_on_trade_date(tmp_path):
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    _commit_proxy_inputs(warehouse)
    next_day = datetime(2026, 9, 3, 7, 1, tzinfo=timezone.utc)
    warehouse.commit_batch(FactBatch(
        dataset_id=ResearchDatasetId.SECURITY_MASTER,
        partition_value="security-master",
        source_name="tushare",
        source_endpoint="stock_basic",
        ingestion_run_id="next-day-security-revision",
        ingested_at=next_day,
        default_available_at=next_day,
        records=[{
            "ts_code": "000001.SZ", "valid_from": date(2020, 1, 1),
            "valid_to": None, "list_date": date(2020, 1, 1),
            "delist_date": None, "list_status": "L", "name": "revised name",
        }],
    ))
    service = ClassificationBackfillService(
        TushareResearchClient(NoSwDailyClassificationPro(), pacer=lambda method: None),
        warehouse,
    )

    service.refresh_daily(
        date(2026, 9, 2),
        datasets=(ResearchDatasetId.INDUSTRY_DAILY_PROXY,),
        refresh_memberships=False,
    )

    proxy = warehouse.read_current(
        ResearchDatasetId.INDUSTRY_DAILY_PROXY,
        partition_value="2026-09-02",
    )
    assert proxy.iloc[0]["proxy_return"] == pytest.approx(-0.02)
    assert pd.Timestamp(proxy.iloc[0]["available_at"]) < pd.Timestamp(next_day)
