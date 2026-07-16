from datetime import date, datetime, timezone
import json

import stock_analyzer.ops.research_data_job as research_data_job_module

from stock_analyzer.data.research_contracts import FactBatch, ResearchDatasetId
from stock_analyzer.ops.research_data_job import (
    reconcile_research_gaps,
    repair_research_gaps,
)
from stock_analyzer.data.research_backfill import BackfillSummary
from stock_analyzer.storage.research_schema import connect_research_warehouse
from stock_analyzer.storage.research_warehouse import ResearchWarehouse


def test_gap_is_marked_resolved_only_after_partition_is_committed(tmp_path):
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    with connect_research_warehouse(warehouse.duckdb_path) as connection:
        connection.execute(
            """
            insert into research_data_gaps values
            ('gap', 'equity_daily', '2026-07-10', 'waiting_upstream',
             'waiting_upstream', 'tushare', now(), now(), null,
             '当日行情未到，不能做全市场比较。', '{}')
            """
        )

    assert reconcile_research_gaps(warehouse) == 0
    warehouse.commit_batch(
        FactBatch(
            dataset_id=ResearchDatasetId.EQUITY_DAILY,
            partition_value="2026-07-10",
            source_name="test",
            source_endpoint="daily",
            ingestion_run_id="repair",
            ingested_at=datetime.now(timezone.utc),
            default_available_at=datetime.now(timezone.utc),
            records=[
                {
                    "trade_date": date(2026, 7, 10),
                    "ts_code": "000001.SZ",
                    "open": 10.0,
                        "high": 10.5,
                        "low": 9.8,
                        "close": 10.2,
                        "pre_close": 10.0,
                        "change": 0.2,
                        "pct_chg": 2.0,
                        "volume": 100.0,
                        "amount": 1000.0,
                }
            ],
        )
    )

    assert reconcile_research_gaps(warehouse) == 1
    with connect_research_warehouse(
        warehouse.duckdb_path, read_only=True
    ) as connection:
        status = connection.execute(
            "select status from research_data_gaps where gap_id = 'gap'"
        ).fetchone()[0]
    assert status == "resolved"


def test_repair_with_no_declared_gap_does_not_repeat_five_year_backfill(tmp_path):
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    runtime = type("Runtime", (), {"warehouse": warehouse})()

    assert repair_research_gaps(runtime, through=date(2026, 7, 13)) == ()


def test_fundamental_gap_repair_retries_only_missing_codes(tmp_path, monkeypatch):
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    detail = json.dumps(
        {
            "scope": "fundamentals",
            "start": "2021-07-09",
            "through": "2026-07-13",
            "waiting_upstream": 2,
            "retry_codes": ["000001.SZ", "000002.SZ"],
        }
    )
    with connect_research_warehouse(warehouse.duckdb_path) as connection:
        connection.execute(
            """
            insert into research_data_gaps values
            ('fundamental-gap', 'scope:fundamentals',
             '2021-07-09:2026-07-13', 'waiting_upstream',
             'scope_incomplete', null, now(), now(), null,
             '部分公司资料待补。', ?)
            """,
            [detail],
        )
    calls = []

    class FakeFundamentalService:
        def __init__(self, client, target_warehouse):
            assert target_warehouse is warehouse

        def backfill(self, *, start, through, codes, resume):
            calls.append((start, through, codes, resume))
            return BackfillSummary(scope="fundamentals", start=start, through=through)

    monkeypatch.setattr(
        research_data_job_module,
        "FundamentalBackfillService",
        FakeFundamentalService,
    )
    runtime = type(
        "Runtime",
        (),
        {"warehouse": warehouse, "tushare": object()},
    )()

    summaries = repair_research_gaps(runtime, through=date(2026, 7, 14))

    assert len(summaries) == 1
    assert calls == [
        (
            date(2021, 7, 9),
            date(2026, 7, 14),
            ("000001.SZ", "000002.SZ"),
            True,
        )
    ]
    with connect_research_warehouse(
        warehouse.duckdb_path, read_only=True
    ) as connection:
        rows = connection.execute(
            """
            select gap_id, status from research_data_gaps
            where dataset_id = 'scope:fundamentals'
            """
        ).fetchall()
    assert rows == [("fundamental-gap", "resolved")]


def test_legacy_fundamental_gap_without_codes_never_expands_to_full_market(tmp_path):
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    with connect_research_warehouse(warehouse.duckdb_path) as connection:
        connection.execute(
            """
            insert into research_data_gaps values
            ('legacy-fundamental-gap', 'scope:fundamentals',
             '2021-07-09:2026-07-13', 'waiting_upstream',
             'scope_incomplete', null, now(), now(), null,
             '旧缺口没有股票范围。', '{}')
            """
        )
    runtime = type("Runtime", (), {"warehouse": warehouse})()

    assert repair_research_gaps(runtime, through=date(2026, 7, 14)) == ()
