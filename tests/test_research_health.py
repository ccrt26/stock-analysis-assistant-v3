from datetime import date, datetime, timezone

from stock_analyzer.data.research_contracts import FactBatch, ResearchDatasetId
from stock_analyzer.ops.research_health import build_research_health_report
from stock_analyzer.storage.research_warehouse import ResearchWarehouse


def _daily_batch(partition: str, code: str) -> FactBatch:
    trade_date = date.fromisoformat(partition)
    return FactBatch(
        dataset_id=ResearchDatasetId.EQUITY_DAILY,
        partition_value=partition,
        source_name="test",
        source_endpoint="daily",
        ingestion_run_id=f"run-{partition}",
        ingested_at=datetime.now(timezone.utc),
        default_available_at=datetime.now(timezone.utc),
        records=[
            {
                "trade_date": trade_date,
                "ts_code": code,
                "open": 10.0,
                "high": 10.5,
                "low": 9.8,
                "close": 10.2,
                "amount": 1000.0,
            }
        ],
    )


def test_full_history_health_audits_files_without_loading_all_facts_into_pandas(
    tmp_path, monkeypatch
):
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    warehouse.commit_batch(_daily_batch("2026-07-09", "000001.SZ"))
    warehouse.commit_batch(_daily_batch("2026-07-10", "000002.SZ"))

    monkeypatch.setattr(
        warehouse,
        "read_current",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("health must not load a full dataset into pandas")
        ),
    )
    report = build_research_health_report(
        warehouse, date(2026, 7, 10), full_history=True
    )
    daily = next(item for item in report.datasets if item.dataset_id == "equity_daily")

    assert daily.rows == 2
    assert daily.checked_partitions == 2
    assert daily.checked_rows == 2
    assert daily.duplicate_business_keys == 0
    assert daily.missing_files == 0
    assert daily.hash_mismatches == 0
    assert daily.row_count_mismatches == 0


def test_fast_health_checks_latest_partition_only(tmp_path):
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    warehouse.commit_batch(_daily_batch("2026-07-09", "000001.SZ"))
    warehouse.commit_batch(_daily_batch("2026-07-10", "000002.SZ"))

    report = build_research_health_report(
        warehouse, date(2026, 7, 10), full_history=False
    )
    daily = next(item for item in report.datasets if item.dataset_id == "equity_daily")

    assert daily.partitions == 2
    assert daily.checked_partitions == 1
    assert daily.checked_rows == 1
