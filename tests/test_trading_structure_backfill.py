from datetime import date

import pandas as pd

from stock_analyzer.data.research_contracts import ResearchDatasetId
from stock_analyzer.data.trading_structure_backfill import TradingStructureBackfillService
from stock_analyzer.data.tushare_research_client import TushareResearchClient
from stock_analyzer.storage.research_warehouse import ResearchWarehouse


class Pro:
    def margin_detail(self, **kwargs):
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
