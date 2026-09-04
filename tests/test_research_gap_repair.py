from datetime import date, datetime, timezone

from stock_analyzer.data.research_contracts import FactBatch, ResearchDatasetId
from stock_analyzer.ops.research_data_job import (
    reconcile_research_gaps,
)
from stock_analyzer.storage.research_schema import connect_research_warehouse
from stock_analyzer.storage.research_warehouse import ResearchWarehouse


def test_gap_is_marked_resolved_only_after_partition_is_committed(tmp_path):
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    with connect_research_warehouse(warehouse.duckdb_path) as connection:
        connection.execute(
            """
            insert into research_data_gaps
            (gap_id, dataset_id, partition_value, scope_key, status,
             reason_category, source_name, source_endpoint, first_seen_at,
             last_checked_at, next_retry_at, resolved_at, impact_text,
             detail_json)
            values
            ('gap', 'equity_daily', '2026-07-10', '', 'waiting_upstream',
             'waiting_upstream', 'test', 'daily', now(), now(), null, null,
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
