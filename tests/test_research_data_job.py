from datetime import date
from types import SimpleNamespace

import pandas as pd

from stock_analyzer.ops.research_data_job import run_research_stage
from stock_analyzer.storage.research_warehouse import ResearchWarehouse


class ClosedCalendarClient:
    def __init__(self):
        self.calls = []

    def fetch_trade_calendar(self, start, through):
        self.calls.append((start, through))
        return pd.DataFrame(
            [
                {
                    "exchange": "SSE",
                    "cal_date": through,
                    "is_open": False,
                    "pretrade_date": through,
                    "cal_year": str(through.year),
                }
            ]
        )


def test_close_stage_on_non_trading_day_does_not_request_market_endpoints(tmp_path):
    client = ClosedCalendarClient()
    runtime = SimpleNamespace(
        tushare=client,
        warehouse=ResearchWarehouse(tmp_path / "warehouse"),
    )

    summaries = run_research_stage(
        runtime, stage="close", data_date=date(2026, 7, 12)
    )

    assert len(summaries) == 1
    assert summaries[0].scope == "market-core"
    assert summaries[0].skipped == 1
    assert client.calls == [(date(2026, 7, 12), date(2026, 7, 12))]
