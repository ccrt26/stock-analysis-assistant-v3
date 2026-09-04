from datetime import date, datetime, timezone
from types import SimpleNamespace

import pandas as pd
import pytest

from stock_analyzer.config import AppConfig
from stock_analyzer.ops.research_data_job import (
    ResearchDataRuntime,
    run_research_stage,
    select_fundamental_refresh_codes,
    select_minute_candidate_scope,
)
from stock_analyzer.data.research_backfill import BackfillSummary
from stock_analyzer.data.research_contracts import FactBatch, ResearchDatasetId
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


def test_stage_run_always_rechecks_source_and_records_each_real_execution(
    tmp_path, monkeypatch
):
    import stock_analyzer.ops.research_data_job as job

    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    runtime = SimpleNamespace(warehouse=warehouse)
    calls = []
    expected = BackfillSummary(
        scope="events",
        start=date(2026, 7, 13),
        through=date(2026, 7, 13),
        committed=2,
    )

    def execute(*args, **kwargs):
        calls.append("run")
        return (expected,)

    monkeypatch.setattr(job, "_run_research_stage_impl", execute)

    first = run_research_stage(
        runtime, stage="evening", data_date=date(2026, 7, 13)
    )
    second = run_research_stage(
        runtime, stage="evening", data_date=date(2026, 7, 13)
    )

    assert first == second == (expected,)
    assert calls == ["run", "run"]
    with connect_research_warehouse(
        warehouse.duckdb_path, read_only=True
    ) as connection:
        runs = connection.execute(
            """
            select run_id, idempotency_key, status, finished_at is not null,
                   summary_json
            from research_ingestion_runs
            order by started_at, run_id
            """
        ).fetchall()
    assert len(runs) == 2
    assert len({row[0] for row in runs}) == 2
    assert len({row[1] for row in runs}) == 2
    assert all(row[2:4] == ("succeeded", True) for row in runs)
    assert all(row[4] is not None for row in runs)


def test_stage_exception_is_recorded_as_failed_with_finished_time(
    tmp_path, monkeypatch
):
    import stock_analyzer.ops.research_data_job as job

    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    runtime = SimpleNamespace(warehouse=warehouse)

    def fail(*args, **kwargs):
        raise RuntimeError("simulated stage failure")

    monkeypatch.setattr(job, "_run_research_stage_impl", fail)

    with pytest.raises(RuntimeError, match="simulated stage failure"):
        run_research_stage(
            runtime, stage="next-morning", data_date=date(2026, 7, 13)
        )

    with connect_research_warehouse(
        warehouse.duckdb_path, read_only=True
    ) as connection:
        row = connection.execute(
            """
            select status, finished_at is not null, cast(summary_json as varchar)
            from research_ingestion_runs
            """
        ).fetchone()
    assert row[0:2] == ("failed", True)
    assert "simulated stage failure" in row[2]


def test_stage_interrupts_orphan_running_rows_before_starting_new_run(
    tmp_path, monkeypatch
):
    import stock_analyzer.ops.research_data_job as job

    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    with connect_research_warehouse(warehouse.duckdb_path) as connection:
        connection.execute(
            """
            insert into research_ingestion_runs
            values ('orphan', 'orphan', 'next-morning', '2026-09-01',
                    'running', now() - interval '1 day', null, null)
            """
        )
    monkeypatch.setattr(
        job,
        "_run_research_stage_impl",
        lambda *args, **kwargs: (
            BackfillSummary(
                scope="market-core",
                start=date(2026, 9, 2),
                through=date(2026, 9, 2),
            ),
        ),
    )

    run_research_stage(
        SimpleNamespace(warehouse=warehouse),
        stage="close",
        data_date=date(2026, 9, 2),
    )

    with connect_research_warehouse(
        warehouse.duckdb_path, read_only=True
    ) as connection:
        old = connection.execute(
            """
            select status, finished_at is not null, cast(summary_json as varchar)
            from research_ingestion_runs where run_id = 'orphan'
            """
        ).fetchone()
    assert old[0:2] == ("interrupted", True)
    assert "superseded by a later locked run" in old[2]


def test_close_stage_never_derives_partial_research_features(monkeypatch):
    import stock_analyzer.ops.research_data_job as job

    class OpenCalendarClient:
        def fetch_trade_calendar(self, start, through):
            return pd.DataFrame({"cal_date": [through], "is_open": [True]})

    expected = BackfillSummary(
        scope="market-core", start=date(2026, 7, 13), through=date(2026, 7, 13)
    )

    def run_backfill(*args, **kwargs):
        assert kwargs["resume"] is False
        return (expected,)

    monkeypatch.setattr(job, "run_research_backfill", run_backfill)
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
        def __init__(self, *args, **kwargs):
            pass

        def backfill(self, **kwargs):
            assert kwargs["resume"] is False
            order.append("events")
            return BackfillSummary(
                scope="events", start=date(2026, 7, 13), through=date(2026, 7, 13)
            )

    class ClassificationService:
        def __init__(self, *args):
            pass

        def refresh_daily(self, data_date, *, datasets, refresh_memberships):
            dataset = tuple(datasets)[0]
            order.append(dataset.value)
            return BackfillSummary(
                scope=dataset.value, start=data_date, through=data_date
            )

    monkeypatch.setattr(job, "EventBackfillService", EventService)
    monkeypatch.setattr(job, "ClassificationBackfillService", ClassificationService)
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
        tushare=object(), cninfo=object(), warehouse=Warehouse(),
        exchange_announcements=object(),
    )

    summaries = run_research_stage(
        runtime, stage="evening", data_date=date(2026, 7, 13)
    )

    assert order == [
        "events",
        "industry_daily_proxy",
        "theme_daily",
        "reconcile",
        "derive",
    ]
    assert summaries[-1].scope == "derived-research-features"
    assert summaries[-1].committed == 3
    assert summaries[-1].issues == ["2026-07-13 已完成三类研究观察。"]


def test_evening_continues_industry_and_theme_refresh_after_event_failure(monkeypatch):
    import stock_analyzer.ops.research_data_job as job

    order = []

    class Warehouse:
        def read_current(self, dataset, *, partition_value=None):
            if ResearchDatasetId(dataset) is ResearchDatasetId.ANNOUNCEMENT:
                return pd.DataFrame(columns=["announcement_time", "title", "ts_code"])
            return pd.DataFrame()

    class EventService:
        def __init__(self, *args, **kwargs):
            pass

        def backfill(self, **kwargs):
            order.append("events-failed")
            raise RuntimeError("local event failure")

    class ClassificationService:
        def __init__(self, *args):
            pass

        def refresh_daily(self, data_date, *, datasets, refresh_memberships):
            dataset = tuple(datasets)[0]
            order.append(dataset.value)
            return BackfillSummary(
                scope=dataset.value, start=data_date, through=data_date
            )

    monkeypatch.setattr(job, "_trading_dates", lambda *args: (date(2026, 7, 13),))
    monkeypatch.setattr(job, "EventBackfillService", EventService)
    monkeypatch.setattr(job, "ClassificationBackfillService", ClassificationService)
    monkeypatch.setattr(job, "reconcile_research_gaps", lambda *args: None)
    monkeypatch.setattr(job, "run_research_features", lambda *args: _derived_summary())
    runtime = SimpleNamespace(
        tushare=object(),
        cninfo=object(),
        exchange_announcements=object(),
        warehouse=Warehouse(),
    )

    summaries = run_research_stage(
        runtime, stage="evening", data_date=date(2026, 7, 13)
    )

    assert order == ["events-failed", "industry_daily_proxy", "theme_daily"]
    assert summaries[0].scope == "events"
    assert summaries[0].failed == 1
    assert "RuntimeError" in summaries[0].issues[0]
    assert {summary.scope for summary in summaries} >= {
        "industry_daily_proxy",
        "theme_daily",
        "derived-research-features",
    }


def test_evening_continues_theme_refresh_after_industry_failure(monkeypatch):
    import stock_analyzer.ops.research_data_job as job

    calls = []

    class Warehouse:
        def read_current(self, dataset, *, partition_value=None):
            if ResearchDatasetId(dataset) is ResearchDatasetId.ANNOUNCEMENT:
                return pd.DataFrame(columns=["announcement_time", "title", "ts_code"])
            return pd.DataFrame()

    monkeypatch.setattr(job, "_trading_dates", lambda *args: ())
    monkeypatch.setattr(
        job,
        "EventBackfillService",
        lambda *args, **kwargs: SimpleNamespace(
            backfill=lambda **options: BackfillSummary(
                scope="events",
                start=date(2026, 7, 13),
                through=date(2026, 7, 13),
            )
        ),
    )

    class ClassificationService:
        def __init__(self, *args):
            pass

        def refresh_daily(self, data_date, *, datasets, refresh_memberships):
            dataset = tuple(datasets)[0]
            calls.append(dataset)
            if dataset is ResearchDatasetId.INDUSTRY_DAILY_PROXY:
                raise RuntimeError("industry endpoint failed")
            return BackfillSummary(
                scope=dataset.value, start=data_date, through=data_date
            )

    monkeypatch.setattr(job, "ClassificationBackfillService", ClassificationService)
    monkeypatch.setattr(job, "reconcile_research_gaps", lambda *args: None)
    monkeypatch.setattr(job, "run_research_features", lambda *args: _derived_summary())
    runtime = SimpleNamespace(
        tushare=object(),
        cninfo=object(),
        exchange_announcements=object(),
        warehouse=Warehouse(),
    )

    summaries = run_research_stage(
        runtime, stage="evening", data_date=date(2026, 7, 13)
    )

    assert calls == [ResearchDatasetId.INDUSTRY_DAILY_PROXY, ResearchDatasetId.THEME_DAILY]
    industry = next(summary for summary in summaries if summary.scope == "industry_daily_proxy")
    assert industry.failed == 1
    assert any(summary.scope == "theme_daily" and summary.failed == 0 for summary in summaries)


def test_fundamental_refresh_scope_uses_actual_financial_disclosures_only():
    announcements = pd.DataFrame(
        [
            {
                "ts_code": "000001.SZ",
                "announcement_time": "2026-08-04T12:00:00Z",
                "title": "2026年半年度报告",
            },
            {
                "ts_code": "000002.SZ",
                "announcement_time": "2026-08-04T12:01:00Z",
                "title": "关于2025年年度报告问询函的回复公告",
            },
            {
                "ts_code": "000003.SZ",
                "announcement_time": "2026-08-04T12:02:00Z",
                "title": "2026年半年度业绩预告的自愿性披露公告",
            },
            {
                "ts_code": "000004.SZ",
                "announcement_time": "2026-08-04T12:03:00Z",
                "title": "关于召开股东大会的通知",
            },
            {
                "ts_code": "000005.SZ",
                "announcement_time": "2026-08-03T12:03:00Z",
                "title": "2026年半年度报告",
            },
        ]
    )

    assert select_fundamental_refresh_codes(
        announcements, date(2026, 8, 4)
    ) == ("000001.SZ", "000003.SZ")


def test_next_morning_only_checks_current_date_facts_and_then_derives(
    monkeypatch,
):
    import stock_analyzer.ops.research_data_job as job

    order = []
    event_options = []
    late = BackfillSummary(
        scope="events", start=date(2026, 7, 13), through=date(2026, 7, 13)
    )
    trading = BackfillSummary(
        scope="trading-structure",
        start=date(2026, 7, 13),
        through=date(2026, 7, 13),
    )

    class EventService:
        def __init__(self, *args, **kwargs):
            pass

        def backfill_announcements(self, **kwargs):
            assert kwargs["resume"] is False
            event_options.append(kwargs)
            order.append("late-events")
            return late

    class TradingService:
        def __init__(self, *args, **kwargs):
            pass

        def backfill(self, **kwargs):
            assert kwargs["resume"] is False
            order.append("trading-structure")
            return trading

    monkeypatch.setattr(
        job,
        "_trading_dates",
        lambda *args: (date(2026, 7, 13),),
    )
    monkeypatch.setattr(job, "EventBackfillService", EventService)
    monkeypatch.setattr(job, "_daily_partition_passed", lambda *args: True)
    monkeypatch.setattr(job, "_shanghai_today", lambda: date(2026, 7, 16))
    monkeypatch.setattr(job, "TradingStructureBackfillService", TradingService)
    monkeypatch.setattr(
        job,
        "select_minute_candidate_scope",
        lambda *args, **kwargs: order.append("candidate-scope") or (),
    )
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
        exchange_announcements=object(),
    )

    summaries = run_research_stage(
        runtime, stage="next-morning", data_date=date(2026, 7, 13)
    )

    assert order == [
        "late-events",
        "candidate-scope",
        "trading-structure",
        "reconcile",
        "derive",
    ]
    assert event_options == [
        {
            "start": date(2026, 7, 13),
            "through": date(2026, 7, 16),
            "resume": False,
            "fallback_to_exchanges": True,
        }
    ]
    assert summaries[-1].scope == "derived-research-features"


def test_next_morning_repairs_only_missing_theme_daily_partition(monkeypatch):
    import stock_analyzer.ops.research_data_job as job

    order = []

    monkeypatch.setattr(job, "_trading_dates", lambda *args: (date(2026, 7, 13),))
    monkeypatch.setattr(job, "_shanghai_today", lambda: date(2026, 7, 14))
    monkeypatch.setattr(
        job,
        "_daily_partition_passed",
        lambda warehouse, dataset, data_date: dataset
        is ResearchDatasetId.INDUSTRY_DAILY_PROXY,
    )
    monkeypatch.setattr(
        job,
        "EventBackfillService",
        lambda *args, **kwargs: SimpleNamespace(
            backfill_announcements=lambda **options: order.append("announcements")
            or BackfillSummary(
                scope="announcements",
                start=date(2026, 7, 13),
                through=date(2026, 7, 14),
            )
        ),
    )

    class ClassificationService:
        def __init__(self, *args):
            pass

        def refresh_daily(self, data_date, *, datasets, refresh_memberships):
            order.append(tuple(datasets)[0].value)
            assert refresh_memberships is False
            return BackfillSummary(
                scope="theme_daily", start=data_date, through=data_date
            )

    monkeypatch.setattr(job, "ClassificationBackfillService", ClassificationService)
    monkeypatch.setattr(job, "select_minute_candidate_scope", lambda *args: ())
    monkeypatch.setattr(
        job,
        "TradingStructureBackfillService",
        lambda *args, **kwargs: SimpleNamespace(
            backfill=lambda **options: order.append("trading")
            or BackfillSummary(
                scope="trading-structure",
                start=date(2026, 7, 13),
                through=date(2026, 7, 13),
            )
        ),
    )
    monkeypatch.setattr(job, "reconcile_research_gaps", lambda *args: None)
    monkeypatch.setattr(job, "run_research_features", lambda *args: _derived_summary())
    runtime = SimpleNamespace(
        tushare=object(),
        cninfo=object(),
        exchange_announcements=object(),
        warehouse=object(),
        minute_fetcher=None,
    )

    run_research_stage(runtime, stage="next-morning", data_date=date(2026, 7, 13))

    assert order == ["announcements", "theme_daily", "trading"]


def test_feature_failure_is_returned_as_a_failed_data_stage(monkeypatch):
    import stock_analyzer.ops.research_data_job as job

    monkeypatch.setattr(job, "_trading_dates", lambda *args: (date(2026, 7, 13),))
    monkeypatch.setattr(
        job,
        "EventBackfillService",
        lambda *args, **kwargs: SimpleNamespace(
            backfill_announcements=lambda **options: BackfillSummary(
                scope="events",
                start=date(2026, 7, 13),
                through=date(2026, 7, 13),
            )
        ),
    )
    monkeypatch.setattr(job, "_daily_partition_passed", lambda *args: True)
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
    monkeypatch.setattr(job, "reconcile_research_gaps", lambda *args: None)
    monkeypatch.setattr(
        job,
        "run_research_features",
        lambda *args: _derived_summary(failed=("sector_hotspot",)),
        raising=False,
    )
    runtime = SimpleNamespace(
        tushare=object(), cninfo=object(), warehouse=object(), minute_fetcher=None,
        exchange_announcements=object(),
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



def test_proxy_partition_with_active_gap_is_not_treated_as_passed(tmp_path):
    import stock_analyzer.ops.research_data_job as job
    from stock_analyzer.storage.research_gap_registry import ResearchGapRegistry

    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    observed = datetime(2026, 9, 2, 7, 1, tzinfo=timezone.utc)
    warehouse.commit_batch(
        FactBatch(
            dataset_id=ResearchDatasetId.INDUSTRY_DAILY_PROXY,
            partition_value="2026-09-02",
            source_name="local_derived",
            source_endpoint="sw_l1_free_float_proxy_v1",
            ingestion_run_id="proxy",
            ingested_at=observed,
            default_available_at=observed,
            records=[{
                "trade_date": date(2026, 9, 2),
                "industry_system": "SW2021",
                "level": "L1",
                "industry_code": "801010.SI",
                "industry_name": "农林牧渔",
                "proxy_return": 0.01,
                "effective_member_count": 10,
                "observed_member_count": 10,
                "member_coverage_ratio": 1.0,
                "coverage_status": "complete",
                "limitation_notes": "",
                "weight_date": date(2026, 9, 1),
                "proxy_method": "sw_l1_free_float_proxy_v1",
                "formula_version": "sw-l1-free-float-proxy-v1",
                "input_manifest_hash": "manifest",
                "available_at": observed,
            }],
        )
    )
    assert job._daily_partition_passed(
        warehouse,
        ResearchDatasetId.INDUSTRY_DAILY_PROXY,
        date(2026, 9, 2),
    )

    ResearchGapRegistry(warehouse.duckdb_path).record(
        ResearchDatasetId.INDUSTRY_DAILY_PROXY,
        "2026-09-02",
        status="unclassified_missing",
        reason_category="member_coverage_below_80_percent",
        source_name="local_derived",
        source_endpoint="sw_l1_free_float_proxy_v1",
    )

    assert not job._daily_partition_passed(
        warehouse,
        ResearchDatasetId.INDUSTRY_DAILY_PROXY,
        date(2026, 9, 2),
    )
