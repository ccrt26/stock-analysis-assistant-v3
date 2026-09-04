from datetime import date, datetime, timedelta, timezone

import pytest

from stock_analyzer.data.research_contracts import FactBatch, ResearchDatasetId
from stock_analyzer.storage.research_conflicts import ResearchConflictRegistry
from stock_analyzer.storage.research_query import ResearchQuery
from stock_analyzer.storage.research_schema import connect_research_warehouse
from stock_analyzer.storage.research_warehouse import ResearchWarehouse


def _indicator(value: float) -> dict:
    return {
        "ts_code": "000001.SZ",
        "report_period": date(2026, 6, 30),
        "report_type": "indicator",
        "ann_date": date(2026, 8, 20),
        "roe": value,
        "available_at": datetime(2026, 8, 20, 16, tzinfo=timezone.utc),
    }


def test_conflict_variants_are_idempotent_and_masked_only_after_observation(tmp_path):
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    first = _indicator(3.0)
    warehouse.commit_batch(
        FactBatch(
            dataset_id=ResearchDatasetId.FINANCIAL_INDICATOR,
            partition_value="2026-06-30",
            source_name="tushare",
            source_endpoint="fina_indicator",
            ingestion_run_id="initial",
            ingested_at=datetime(2026, 8, 21, tzinfo=timezone.utc),
            default_available_at=first["available_at"],
            records=[first],
        )
    )
    registry = ResearchConflictRegistry(warehouse.duckdb_path)
    observed = datetime(2026, 9, 1, 1, tzinfo=timezone.utc)
    for _ in range(2):
        registry.record_variants(
            ResearchDatasetId.FINANCIAL_INDICATOR,
            "2026-06-30",
            business_key=("000001.SZ", "2026-06-30", "indicator"),
            rows=[first, _indicator(4.0)],
            source_name="tushare",
            source_endpoint="fina_indicator",
            observed_at=observed,
        )

    with connect_research_warehouse(
        warehouse.duckdb_path, read_only=True
    ) as connection:
        count = connection.execute(
            "select count(*) from research_fact_conflicts"
        ).fetchone()[0]
    assert count == 2
    query = ResearchQuery(warehouse)
    assert len(query.dataset_as_of(
        ResearchDatasetId.FINANCIAL_INDICATOR,
        observed - timedelta(seconds=1),
    )) == 1
    assert query.dataset_as_of(
        ResearchDatasetId.FINANCIAL_INDICATOR, observed
    ).empty

    registry.resolve(
        ResearchDatasetId.FINANCIAL_INDICATOR,
        business_key=("000001.SZ", "2026-06-30", "indicator"),
        resolved_at=observed + timedelta(days=1),
        resolution_basis={"basis": "later official response converged"},
    )
    assert query.dataset_as_of(
        ResearchDatasetId.FINANCIAL_INDICATOR,
        observed + timedelta(hours=1),
    ).empty
    assert len(query.dataset_as_of(
        ResearchDatasetId.FINANCIAL_INDICATOR,
        observed + timedelta(days=1),
    )) == 1


def test_conflict_lifecycles_preserve_past_queries_and_ignore_old_replays(tmp_path):
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    dataset = ResearchDatasetId.FINANCIAL_INDICATOR
    first = _indicator(3.0)
    warehouse.commit_batch(FactBatch(
        dataset_id=dataset, partition_value="2026-06-30",
        source_name="tushare", source_endpoint="fina_indicator",
        ingestion_run_id="initial", ingested_at=first["available_at"],
        default_available_at=first["available_at"], records=[first],
    ))
    registry = ResearchConflictRegistry(warehouse.duckdb_path)
    key = ("000001.SZ", "2026-06-30", "indicator")
    start = datetime(2026, 9, 1, tzinfo=timezone.utc)

    def record(observed, values=(3.0, 4.0)):
        return registry.record_variants(
            dataset, "2026-06-30", business_key=key,
            rows=[_indicator(value) for value in values],
            source_name="tushare", source_endpoint="fina_indicator",
            observed_at=observed,
        )

    def resolve(at):
        return registry.resolve(
            dataset, business_key=key, resolved_at=at,
            resolution_basis={"basis": at.isoformat()},
        )

    def rows():
        with connect_research_warehouse(warehouse.duckdb_path, read_only=True) as conn:
            return conn.execute(
                "select to_json(c)::varchar from research_fact_conflicts c "
                "order by conflict_id"
            ).fetchall()

    query = ResearchQuery(warehouse)
    record(start)
    assert resolve(start + timedelta(days=1)) == 2
    closed_rows = rows()
    assert len(query.dataset_as_of(dataset, start + timedelta(days=1))) == 1

    # A replay from a closed interval is not a new conflict observation.
    record(start)
    assert rows() == closed_rows
    with connect_research_warehouse(warehouse.duckdb_path, read_only=True) as conn:
        assert conn.execute("select status from research_data_gaps").fetchone()[0] == "resolved"

    with pytest.raises(ValueError, match="observation"):
        record(start + timedelta(hours=1), values=(3.0, 9.0))
    with pytest.raises(ValueError, match="observation"):
        record(start - timedelta(hours=1))
    assert rows() == closed_rows

    recurrence = start + timedelta(days=2)
    record(recurrence)
    record(recurrence.astimezone(timezone(timedelta(hours=8))))
    record(recurrence + timedelta(hours=2))
    newest_rows = rows()
    record(recurrence + timedelta(hours=1))
    assert rows() == newest_rows
    assert len(rows()) == 4
    assert set(closed_rows) <= set(rows())
    assert query.dataset_as_of(dataset, recurrence).empty
    assert len(query.dataset_as_of(dataset, start + timedelta(days=1, hours=1))) == 1

    with pytest.raises(ValueError, match="resolution"):
        resolve(start + timedelta(days=1))
    assert rows() == newest_rows

    assert resolve(start + timedelta(days=3)) == 2
    all_closed = rows()
    assert set(closed_rows) <= set(all_closed)
    assert resolve(start + timedelta(days=4)) == 0
    assert rows() == all_closed
    for cutoff, expected_count in (
        (start - timedelta(seconds=1), 1),
        (start, 0),
        (start + timedelta(days=1), 1),
        (recurrence - timedelta(seconds=1), 1),
        (recurrence, 0),
        (start + timedelta(days=3), 1),
    ):
        assert len(query.dataset_as_of(dataset, cutoff)) == expected_count
