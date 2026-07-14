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


def _derived_summary(*, failed: tuple[str, ...] = ()):  # business-stage fixture
    return SimpleNamespace(
        analysis_date=date(2026, 7, 13),
        committed_feature_sets=(
            "market_context",
            "sector_hotspot",
            "stock_trading_context",
        ) if not failed else (),
        skipped_feature_sets=(),
        failed_feature_sets=failed,
        limitations=("历史分钟事实当前不可用",),
        errors=tuple(f"{name}: failed" for name in failed),
        plain_language_summary="2026-07-13 已完成三类研究观察。",
    )


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


def test_close_stage_never_derives_partial_research_features(monkeypatch):
    import stock_analyzer.ops.research_data_job as job

    class OpenCalendarClient:
        def fetch_trade_calendar(self, start, through):
            return pd.DataFrame({"cal_date": [through], "is_open": [True]})

    expected = BackfillSummary(
        scope="market-core", start=date(2026, 7, 13), through=date(2026, 7, 13)
    )
    monkeypatch.setattr(
        job, "run_research_backfill", lambda *args, **kwargs: (expected,)
    )
    monkeypatch.setattr(
        job,
        "run_research_features",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("收盘阶段不得计算不完整研究观察")
        ),
    )
    runtime = SimpleNamespace(tushare=OpenCalendarClient())

    summaries = run_research_stage(
        runtime, stage="close", data_date=date(2026, 7, 13)
    )

    assert summaries == (expected,)


def test_evening_derives_only_after_fact_commits_and_reconciliation(monkeypatch):
    import stock_analyzer.ops.research_data_job as job

    order = []

    class Warehouse:
        def read_current(self, dataset, *, partition_value=None):
            dataset = ResearchDatasetId(dataset)
            if dataset is ResearchDatasetId.TRADE_CALENDAR:
                return pd.DataFrame(
                    {"cal_date": [date(2026, 7, 13)], "is_open": [True]}
                )
            if dataset is ResearchDatasetId.ANNOUNCEMENT:
                return pd.DataFrame(columns=["announcement_time", "ts_code"])
            raise AssertionError(dataset)

    class EventService:
        def __init__(self, *args):
            pass

        def backfill(self, **kwargs):
            order.append("events")
            return BackfillSummary(
                scope="events", start=date(2026, 7, 13), through=date(2026, 7, 13)
            )

    class ClassificationService:
        def __init__(self, *args):
            pass

        def refresh_daily(self, data_date):
            order.append("classifications")
            return BackfillSummary(
                scope="classifications", start=data_date, through=data_date
            )

    monkeypatch.setattr(job, "EventBackfillService", EventService)
    monkeypatch.setattr(job, "ClassificationBackfillService", ClassificationService)
    monkeypatch.setattr(job, "_record_scope_outcome", lambda *args: order.append("record"))
    monkeypatch.setattr(
        job, "reconcile_research_gaps", lambda *args: order.append("reconcile")
    )
    monkeypatch.setattr(
        job,
        "run_research_features",
        lambda warehouse, data_date: order.append("derive") or _derived_summary(),
        raising=False,
    )
    runtime = SimpleNamespace(
        tushare=object(), cninfo=object(), warehouse=Warehouse()
    )

    summaries = run_research_stage(
        runtime, stage="evening", data_date=date(2026, 7, 13)
    )

    assert order == [
        "events",
        "classifications",
        "record",
        "record",
        "reconcile",
        "derive",
    ]
    assert summaries[-1].scope == "derived-research-features"
    assert summaries[-1].committed == 3
    assert summaries[-1].issues == ["2026-07-13 已完成三类研究观察。"]


def test_next_morning_derives_after_repairs_late_facts_and_reconciliation(
    monkeypatch,
):
    import stock_analyzer.ops.research_data_job as job

    order = []
    repaired = BackfillSummary(
        scope="repair", start=date(2026, 7, 13), through=date(2026, 7, 13)
    )
    late = BackfillSummary(
        scope="events", start=date(2026, 7, 13), through=date(2026, 7, 13)
    )
    trading = BackfillSummary(
        scope="trading-structure",
        start=date(2026, 7, 13),
        through=date(2026, 7, 13),
    )

    class EventService:
        def __init__(self, *args):
            pass

        def backfill(self, **kwargs):
            order.append("late-events")
            return late

    class TradingService:
        def __init__(self, *args, **kwargs):
            pass

        def backfill(self, **kwargs):
            order.append("trading-structure")
            return trading

    monkeypatch.setattr(
        job,
        "_trading_dates",
        lambda *args: (date(2026, 7, 13),),
    )
    monkeypatch.setattr(
        job,
        "repair_research_gaps",
        lambda *args, **kwargs: order.append("repairs") or (repaired,),
    )
    monkeypatch.setattr(job, "EventBackfillService", EventService)
    monkeypatch.setattr(job, "TradingStructureBackfillService", TradingService)
    monkeypatch.setattr(
        job,
        "select_minute_candidate_scope",
        lambda *args, **kwargs: order.append("candidate-scope") or (),
    )
    monkeypatch.setattr(job, "_record_scope_outcome", lambda *args: order.append("record"))
    monkeypatch.setattr(
        job, "reconcile_research_gaps", lambda *args: order.append("reconcile")
    )
    monkeypatch.setattr(
        job,
        "run_research_features",
        lambda warehouse, data_date: order.append("derive") or _derived_summary(),
        raising=False,
    )
    runtime = SimpleNamespace(
        tushare=object(),
        cninfo=object(),
        warehouse=object(),
        minute_fetcher=lambda **kwargs: pd.DataFrame(),
    )

    summaries = run_research_stage(
        runtime, stage="next-morning", data_date=date(2026, 7, 13)
    )

    assert order == [
        "repairs",
        "late-events",
        "candidate-scope",
        "trading-structure",
        "record",
        "record",
        "record",
        "reconcile",
        "derive",
    ]
    assert summaries[-1].scope == "derived-research-features"


def test_feature_failure_is_returned_as_a_failed_data_stage(monkeypatch):
    import stock_analyzer.ops.research_data_job as job

    monkeypatch.setattr(job, "_trading_dates", lambda *args: (date(2026, 7, 13),))
    monkeypatch.setattr(
        job, "repair_research_gaps", lambda *args, **kwargs: ()
    )
    monkeypatch.setattr(
        job,
        "EventBackfillService",
        lambda *args: SimpleNamespace(
            backfill=lambda **kwargs: BackfillSummary(
                scope="events",
                start=date(2026, 7, 13),
                through=date(2026, 7, 13),
            )
        ),
    )
    monkeypatch.setattr(job, "select_minute_candidate_scope", lambda *args: ())
    monkeypatch.setattr(
        job,
        "TradingStructureBackfillService",
        lambda *args, **kwargs: SimpleNamespace(
            backfill=lambda **options: BackfillSummary(
                scope="trading-structure",
                start=date(2026, 7, 13),
                through=date(2026, 7, 13),
            )
        ),
    )
    monkeypatch.setattr(job, "_record_scope_outcome", lambda *args: None)
    monkeypatch.setattr(job, "reconcile_research_gaps", lambda *args: None)
    monkeypatch.setattr(
        job,
        "run_research_features",
        lambda *args: _derived_summary(failed=("sector_hotspot",)),
        raising=False,
    )
    runtime = SimpleNamespace(
        tushare=object(), cninfo=object(), warehouse=object(), minute_fetcher=None
    )

    summaries = run_research_stage(
        runtime, stage="next-morning", data_date=date(2026, 7, 13)
    )

    assert summaries[-1].scope == "derived-research-features"
    assert summaries[-1].failed == 1
    assert "sector_hotspot: failed" in summaries[-1].issues


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
