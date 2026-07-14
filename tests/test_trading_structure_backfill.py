from datetime import date

import pandas as pd

from stock_analyzer.data.research_contracts import ResearchDatasetId
from stock_analyzer.data.trading_structure_backfill import (
    MinuteRequestPacer,
    TradingStructureBackfillService,
)
from stock_analyzer.data.tushare_research_client import TushareResearchClient
from stock_analyzer.storage.research_warehouse import ResearchWarehouse


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
    assert summary.waiting_upstream == 1
    assert len(minute) == 2
    assert set(minute["instrument_code"]) == {"000001.SZ"}
    assert service.frozen_scope_codes(date(2026, 7, 13)) == ("000001.SZ",)


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
    assert summary.failed == 1
    assert summary.issues == ["minute_bar:access_or_rate_limit"]
