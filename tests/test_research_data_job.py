from datetime import date
from types import SimpleNamespace

import pandas as pd

from stock_analyzer.config import AppConfig
from stock_analyzer.ops.research_data_job import (
    ResearchDataRuntime,
    _record_scope_outcome,
    run_research_stage,
    select_minute_candidate_scope,
)
from stock_analyzer.data.research_backfill import BackfillSummary
from stock_analyzer.data.research_contracts import ResearchDatasetId
from stock_analyzer.storage.research_schema import connect_research_warehouse
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


def test_runtime_minute_fetcher_uses_direct_endpoint_and_derives_trade_date(
    tmp_path,
):
    class MinutePro:
        def __init__(self):
            self.calls = []

        def stk_mins(self, **kwargs):
            self.calls.append(kwargs)
            return pd.DataFrame(
                [
                    {
                        "ts_code": kwargs["ts_code"],
                        "trade_time": "2026-07-10 09:31:00",
                        "open": 10.0,
                        "high": 10.2,
                        "low": 9.9,
                        "close": 10.1,
                        "vol": 40.0,
                        "amount": 400.0,
                    }
                ]
            )

    pro = MinutePro()
    runtime = ResearchDataRuntime(
        config=AppConfig(project_root=tmp_path),
        pro=pro,
        tushare_module=None,
        tushare=None,
        cninfo=None,
        warehouse=ResearchWarehouse(tmp_path / "warehouse"),
        http_client=None,
    )

    frame = runtime.minute_fetcher(
        ts_code="000001.SZ",
        start_date="2026-07-10 09:00:00",
        end_date="2026-07-10 15:30:00",
        freq="1min",
        asset="E",
    )

    assert frame["trade_date"].tolist() == ["20260710"]
    assert pro.calls == [
        {
            "ts_code": "000001.SZ",
            "start_date": "2026-07-10 09:00:00",
            "end_date": "2026-07-10 15:30:00",
            "freq": "1min",
        }
    ]


def test_minute_candidate_scope_reads_only_latest_21_daily_partitions():
    dates = tuple(pd.date_range("2026-06-10", periods=22, freq="B").date)

    class PartitionWarehouse:
        def __init__(self):
            self.daily_partition_calls = []

        def read_current(self, dataset, *, partition_value=None):
            dataset = ResearchDatasetId(dataset)
            if dataset is ResearchDatasetId.TRADE_CALENDAR:
                return pd.DataFrame(
                    {"cal_date": dates, "is_open": [True] * len(dates)}
                )
            if dataset is ResearchDatasetId.EQUITY_DAILY:
                assert partition_value is not None
                self.daily_partition_calls.append(partition_value)
                trading_date = date.fromisoformat(partition_value)
                offset = dates.index(trading_date)
                return pd.DataFrame(
                    [
                        {
                            "trade_date": trading_date,
                            "ts_code": "000001.SZ",
                            "close": 10.0 + offset,
                            "amount": 100_000_000.0,
                        },
                        {
                            "trade_date": trading_date,
                            "ts_code": "000002.SZ",
                            "close": 10.0,
                            "amount": 80_000_000.0,
                        },
                    ]
                )
            raise AssertionError(dataset)

    warehouse = PartitionWarehouse()
    result = select_minute_candidate_scope(warehouse, dates[-1], limit=2)

    assert result
    assert warehouse.daily_partition_calls == [
        value.isoformat() for value in dates[-21:]
    ]


def test_known_provider_limit_is_separate_from_temporary_upstream_wait(tmp_path):
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    summary = BackfillSummary(
        scope="trading-structure",
        start=date(2026, 7, 10),
        through=date(2026, 7, 10),
        waiting_upstream=1,
        limited=1,
        limitations_checked=True,
        issues=[
            "margin_detail:2026-07-10:waiting_upstream",
            "minute_bar:access_or_rate_limit",
        ],
    )

    _record_scope_outcome(warehouse, summary)

    with connect_research_warehouse(
        warehouse.duckdb_path, read_only=True
    ) as connection:
        rows = connection.execute(
            """
            select status, reason_category from research_data_gaps
            where dataset_id = 'scope:trading-structure'
            order by status
            """
        ).fetchall()
    assert rows == [
        ("limited", "source_limited"),
        ("waiting_upstream", "scope_incomplete"),
    ]

    unchecked = BackfillSummary(
        scope="trading-structure",
        start=date(2026, 7, 11),
        through=date(2026, 7, 11),
    )
    _record_scope_outcome(warehouse, unchecked)
    with connect_research_warehouse(
        warehouse.duckdb_path, read_only=True
    ) as connection:
        status = connection.execute(
            """
            select status from research_data_gaps
            where dataset_id = 'scope:trading-structure'
              and reason_category = 'source_limited'
            """
        ).fetchone()[0]
    assert status == "limited"
