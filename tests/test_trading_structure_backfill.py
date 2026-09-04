import json
from datetime import date
from zoneinfo import ZoneInfo

import pandas as pd

from stock_analyzer.data.research_contracts import ResearchDatasetId
from stock_analyzer.data.trading_structure_backfill import (
    MinuteRequestPacer,
    TradingStructureBackfillService,
)
from stock_analyzer.data.tushare_research_client import TushareResearchClient
from stock_analyzer.storage.research_warehouse import ResearchWarehouse
from stock_analyzer.storage.research_schema import connect_research_warehouse


class Pro:
    def __init__(self):
        self.margin_calls = []

    def margin_detail(self, **kwargs):
        self.margin_calls.append(kwargs["trade_date"])
        if kwargs["trade_date"] == "20260713":
            return pd.DataFrame(columns=[
                "trade_date", "ts_code", "rzye", "rqye", "rzmre", "rqyl",
                "rzche", "rqchl", "rqmcl", "rzrqye"
            ])
        return pd.DataFrame([{
            "trade_date": kwargs["trade_date"], "ts_code": "000001.SZ",
            "rzye": 1.0, "rqye": 2.0, "rzmre": 3.0, "rqyl": 4.0,
            "rzche": 5.0, "rqchl": 6.0, "rqmcl": 7.0, "rzrqye": 8.0,
        }])


def minute_fetcher(**kwargs):
    return pd.DataFrame([
        {"ts_code": kwargs["ts_code"], "trade_time": "2026-07-10 09:31:00",
         "open": 10.0, "high": 10.2, "low": 9.9, "close": 10.1,
         "vol": 40.0, "amount": 400.0, "trade_date": "20260710"},
        {"ts_code": kwargs["ts_code"], "trade_time": "2026-07-10 15:00:00",
         "open": 10.1, "high": 10.3, "low": 10.0, "close": 10.2,
         "vol": 60.0, "amount": 600.0, "trade_date": "20260710"},
    ])


def test_minute_pacer_default_stays_below_official_500_calls_per_minute():
    now = [0.0]
    sleeps = []

    def clock():
        return now[0]

    def sleeper(delay):
        sleeps.append(delay)
        now[0] += delay

    pacer = MinuteRequestPacer(clock=clock, sleeper=sleeper)
    pacer()
    pacer()

    assert sleeps == [0.13]


def test_trading_structure_records_margin_lag_and_freezes_minute_scope(tmp_path):
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    service = TradingStructureBackfillService(
        TushareResearchClient(Pro(), pacer=lambda method: None),
        warehouse,
        minute_fetcher=minute_fetcher,
        minute_pacer=lambda: None,
    )

    summary = service.backfill(
        trading_dates=(date(2026, 7, 10), date(2026, 7, 13)),
        through=date(2026, 7, 13),
        candidate_codes=("000001.SZ",),
        index_codes=(),
        resume=True,
    )

    margin = warehouse.read_current(ResearchDatasetId.MARGIN_DETAIL)
    minute = warehouse.read_current(ResearchDatasetId.MINUTE_BAR)
    assert len(margin) == 1
    assert margin.iloc[0]["exchange"] == "SZSE"
    assert pd.Timestamp(margin.iloc[0]["available_at"]).tz_convert(
        ZoneInfo("Asia/Shanghai")
    ) == pd.Timestamp("2026-07-11 08:00:00", tz="Asia/Shanghai")
    assert margin.iloc[0]["availability_precision"] == (
        "inferred_from_endpoint_policy"
    )
    assert summary.waiting_upstream == 1
    assert len(minute) == 2
    assert set(minute["instrument_code"]) == {"000001.SZ"}


def test_resume_refetches_a_minute_day_when_only_a_partial_row_is_stored(tmp_path):
    calls = []

    def complete_fetcher(**kwargs):
        calls.append(kwargs["ts_code"])
        rows = []
        for minute in pd.date_range("2026-07-10 09:31:00", periods=120, freq="min"):
            rows.append({
                "ts_code": kwargs["ts_code"],
                "trade_time": minute.strftime("%Y-%m-%d %H:%M:%S"),
                "open": 10.0,
                "high": 10.2,
                "low": 9.9,
                "close": 10.1,
                "vol": 1.0,
                "amount": 10.0,
                "trade_date": "20260710",
            })
        for minute in pd.date_range("2026-07-10 13:01:00", periods=120, freq="min"):
            rows.append({
                "ts_code": kwargs["ts_code"],
                "trade_time": minute.strftime("%Y-%m-%d %H:%M:%S"),
                "open": 10.0,
                "high": 10.2,
                "low": 9.9,
                "close": 10.1,
                "vol": 1.0,
                "amount": 10.0,
                "trade_date": "20260710",
            })
        return pd.DataFrame(rows)

    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    partial_service = TradingStructureBackfillService(
        TushareResearchClient(Pro(), pacer=lambda method: None),
        warehouse,
        minute_fetcher=minute_fetcher,
        minute_pacer=lambda: None,
    )
    partial_service.backfill(
        trading_dates=(date(2026, 7, 10),),
        through=date(2026, 7, 10),
        candidate_codes=("000001.SZ",),
        index_codes=(),
        resume=False,
    )

    service = TradingStructureBackfillService(
        TushareResearchClient(Pro(), pacer=lambda method: None),
        warehouse,
        minute_fetcher=complete_fetcher,
        minute_pacer=lambda: None,
    )
    service.backfill(
        trading_dates=(date(2026, 7, 10),),
        through=date(2026, 7, 10),
        candidate_codes=("000001.SZ",),
        index_codes=(),
        resume=True,
    )

    assert calls == ["000001.SZ"]
    minute = warehouse.read_current(ResearchDatasetId.MINUTE_BAR)
    assert len(minute) == 240


def test_margin_history_is_capped_at_latest_250_trading_days(tmp_path):
    pro = Pro()
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    service = TradingStructureBackfillService(
        TushareResearchClient(pro, pacer=lambda method: None),
        warehouse,
        minute_fetcher=lambda **kwargs: pd.DataFrame(),
        minute_pacer=lambda: None,
    )
    dates = tuple(pd.date_range("2025-01-01", periods=251, freq="B").date)

    service.backfill(
        trading_dates=dates,
        through=dates[-1],
        candidate_codes=(),
        index_codes=(),
        resume=True,
    )

    assert len(pro.margin_calls) == 250
    assert pro.margin_calls[0] == dates[-250].strftime("%Y%m%d")


def test_margin_empty_dataframe_without_columns_is_waiting_not_schema_failure(
    tmp_path,
):
    class EmptyMarginPro:
        def margin_detail(self, **kwargs):
            return pd.DataFrame()

    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    service = TradingStructureBackfillService(
        TushareResearchClient(EmptyMarginPro(), pacer=lambda method: None),
        warehouse,
        minute_fetcher=lambda **kwargs: pd.DataFrame(),
        minute_pacer=lambda: None,
    )

    summary = service.backfill(
        trading_dates=(date(2026, 7, 13),),
        through=date(2026, 7, 13),
        candidate_codes=(),
        index_codes=(),
        resume=True,
    )

    assert summary.waiting_upstream == 1
    assert summary.failed == 0
    assert summary.issues == ["margin_detail:2026-07-13:waiting_upstream"]


def test_targeted_margin_backfill_does_not_touch_minute_endpoint(tmp_path):
    pro = Pro()
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    service = TradingStructureBackfillService(
        TushareResearchClient(pro, pacer=lambda method: None),
        warehouse,
        minute_fetcher=lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("minute endpoint must not be called")
        ),
        minute_pacer=lambda: None,
    )

    summary = service.backfill_margin_details(
        trading_dates=(date(2026, 7, 10),),
        through=date(2026, 7, 10),
        resume=False,
    )

    assert pro.margin_calls == ["20260710"]
    assert summary.scope == "margin-detail"
    assert summary.committed == 1


def test_minute_permission_error_stops_remaining_scope_after_first_failure(tmp_path):
    calls = []

    def denied_minute_fetcher(**kwargs):
        calls.append(kwargs["ts_code"])
        raise RuntimeError("访问接口(stk_mins)频率超限(2次/天)")

    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    service = TradingStructureBackfillService(
        TushareResearchClient(Pro(), pacer=lambda method: None),
        warehouse,
        minute_fetcher=denied_minute_fetcher,
        minute_pacer=lambda: None,
    )

    summary = service.backfill(
        trading_dates=(date(2026, 7, 10),),
        through=date(2026, 7, 10),
        candidate_codes=("000001.SZ", "000002.SZ", "000003.SZ"),
        index_codes=(),
        resume=True,
    )

    assert calls == ["000001.SZ"]
    assert summary.failed == 0
    assert summary.limited == 1
    assert summary.limitations_checked
    assert summary.issues == ["minute_bar:access_or_rate_limit"]
    with connect_research_warehouse(
        warehouse.duckdb_path, read_only=True
    ) as connection:
        frozen = connection.execute(
            """
            select watermark_value from research_watermarks
            where dataset_id = 'minute_scope' and scope_key = '2026-07-10'
            """
        ).fetchone()[0]
        gaps = connection.execute(
            """
            select scope_key, status from research_data_gaps
            where dataset_id = 'minute_bar' and partition_value = '2026-07-10'
            order by scope_key
            """
        ).fetchall()
    assert json.loads(frozen) == ["000001.SZ", "000002.SZ", "000003.SZ"]
    assert gaps == [
        ("000001.SZ", "unsupported_optional"),
        ("000002.SZ", "unsupported_optional"),
        ("000003.SZ", "unsupported_optional"),
    ]


def test_minute_error_for_one_code_does_not_drop_remaining_codes(tmp_path):
    calls = []

    def partly_failing_fetcher(**kwargs):
        calls.append(kwargs["ts_code"])
        if kwargs["ts_code"] == "000001.SZ":
            raise RuntimeError("该标的分钟数据不存在")
        return minute_fetcher(**kwargs)

    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    service = TradingStructureBackfillService(
        TushareResearchClient(Pro(), pacer=lambda method: None),
        warehouse,
        minute_fetcher=partly_failing_fetcher,
        minute_pacer=lambda: None,
    )

    summary = service.backfill(
        trading_dates=(date(2026, 7, 10),),
        through=date(2026, 7, 10),
        candidate_codes=("000001.SZ", "000002.SZ"),
        index_codes=(),
        resume=True,
    )

    assert calls == ["000001.SZ", "000002.SZ"]
    assert summary.failed == 1
    assert summary.issues == ["minute_bar:000001.SZ:provider_error"]
    minute = warehouse.read_current(ResearchDatasetId.MINUTE_BAR)
    assert set(minute["instrument_code"]) == {"000002.SZ"}
