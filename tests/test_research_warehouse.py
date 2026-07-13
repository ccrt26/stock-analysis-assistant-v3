from datetime import date, datetime, timezone

import pandas as pd
import pytest

from stock_analyzer.data.research_contracts import FactBatch, ResearchDatasetId
from stock_analyzer.storage import research_warehouse as research_warehouse_module
from stock_analyzer.storage.research_warehouse import ResearchWarehouse


def _batch(*, close: float = 10.2, records: list[dict] | None = None) -> FactBatch:
    if records is None:
        records = [
            {
                "trade_date": date(2026, 7, 10),
                "ts_code": "000001.SZ",
                "open": 10.0,
                "high": max(10.5, close),
                "low": min(9.8, close),
                "close": close,
                "vol": 100.0,
                "amount": 1000.0,
            }
        ]
    return FactBatch(
        dataset_id=ResearchDatasetId.EQUITY_DAILY,
        partition_value="2026-07-10",
        source_name="tushare",
        source_endpoint="daily",
        ingestion_run_id="run-1",
        ingested_at=datetime(2026, 7, 10, 10, tzinfo=timezone.utc),
        default_available_at=datetime(2026, 7, 10, 7, 1, tzinfo=timezone.utc),
        records=records,
    )


def _announcement_batch(
    partition: str,
    announcement_id: str,
    *,
    title: str = "公告",
    run_id: str = "announcement-1",
) -> FactBatch:
    return FactBatch(
        dataset_id=ResearchDatasetId.ANNOUNCEMENT,
        partition_value=partition,
        source_name="cninfo",
        source_endpoint="announcement",
        ingestion_run_id=run_id,
        ingested_at=datetime(2026, 7, 13, 10, tzinfo=timezone.utc),
        default_available_at=datetime(2026, 7, 13, 10, tzinfo=timezone.utc),
        records=[{"announcement_id": announcement_id, "title": title}],
    )


def test_identical_retry_is_idempotent_and_keeps_one_business_fact(tmp_path):
    warehouse = ResearchWarehouse(tmp_path)
    first = warehouse.commit_batch(_batch())
    second = warehouse.commit_batch(_batch())

    frame = warehouse.read_current(ResearchDatasetId.EQUITY_DAILY)
    assert len(frame) == 1
    assert first.content_hash == second.content_hash
    assert second.changed_rows == 0
    assert warehouse.revision_count(ResearchDatasetId.EQUITY_DAILY) == 0
    assert len(list((tmp_path / "facts" / "equity_daily").rglob("*.parquet"))) == 1


def test_changed_fact_replaces_current_and_preserves_revision(tmp_path):
    warehouse = ResearchWarehouse(tmp_path)
    warehouse.commit_batch(_batch(close=10.2))
    changed = _batch(close=10.4).model_copy(
        update={
            "ingestion_run_id": "run-2",
            "ingested_at": datetime(2026, 7, 11, 10, tzinfo=timezone.utc),
        }
    )

    result = warehouse.commit_batch(changed)
    current = warehouse.read_current(ResearchDatasetId.EQUITY_DAILY)

    assert result.changed_rows == 1
    assert current.iloc[0]["close"] == pytest.approx(10.4)
    assert int(current.iloc[0]["revision_no"]) == 2
    assert warehouse.revision_count(ResearchDatasetId.EQUITY_DAILY) == 1


def test_duplicate_business_key_fails_without_changing_committed_partition(tmp_path):
    warehouse = ResearchWarehouse(tmp_path)
    warehouse.commit_batch(_batch())
    duplicate_records = _batch().records * 2

    with pytest.raises(ValueError, match="duplicate business key"):
        warehouse.commit_batch(_batch(records=duplicate_records))

    assert len(warehouse.read_current(ResearchDatasetId.EQUITY_DAILY)) == 1


def test_failure_before_atomic_promote_leaves_previous_partition_visible(tmp_path, monkeypatch):
    warehouse = ResearchWarehouse(tmp_path)
    warehouse.commit_batch(_batch(close=10.2))

    def fail_promote(*args, **kwargs):
        raise RuntimeError("simulated promote failure")

    monkeypatch.setattr(warehouse, "_promote_staged_partition", fail_promote)
    with pytest.raises(RuntimeError, match="simulated"):
        warehouse.commit_batch(
            _batch(close=10.8).model_copy(
                update={"ingestion_run_id": "run-fail"}
            )
        )

    current = warehouse.read_current(ResearchDatasetId.EQUITY_DAILY)
    assert current.iloc[0]["close"] == pytest.approx(10.2)
    assert warehouse.revision_count(ResearchDatasetId.EQUITY_DAILY) == 0


def test_ohlc_quality_failure_is_rejected(tmp_path):
    warehouse = ResearchWarehouse(tmp_path)
    bad = _batch(
        records=[
            {
                "trade_date": date(2026, 7, 10),
                "ts_code": "000001.SZ",
                "open": 10.0,
                "high": 9.0,
                "low": 9.8,
                "close": 10.2,
                "vol": 100.0,
                "amount": 1000.0,
            }
        ]
    )
    with pytest.raises(ValueError, match="OHLC"):
        warehouse.commit_batch(bad)
    assert warehouse.read_current(ResearchDatasetId.EQUITY_DAILY).empty


def test_same_business_key_cannot_silently_move_to_another_partition(tmp_path):
    warehouse = ResearchWarehouse(tmp_path)
    first = FactBatch(
        dataset_id=ResearchDatasetId.ANNOUNCEMENT,
        partition_value="2026-07",
        source_name="cninfo",
        source_endpoint="announcement",
        ingestion_run_id="a1",
        ingested_at=datetime(2026, 7, 10, 10, tzinfo=timezone.utc),
        default_available_at=datetime(2026, 7, 10, 10, tzinfo=timezone.utc),
        records=[{"announcement_id": "A1", "title": "公告"}],
    )
    warehouse.commit_batch(first)
    moved = first.model_copy(
        update={"partition_value": "2026-08", "ingestion_run_id": "a2"}
    )
    with pytest.raises(ValueError, match="different partition"):
        warehouse.commit_batch(moved)


def test_prune_partitions_before_removes_files_metadata_keys_and_revisions(tmp_path):
    warehouse = ResearchWarehouse(tmp_path)
    warehouse.commit_batch(_announcement_batch("2025-06", "A1"))
    warehouse.commit_batch(
        _announcement_batch(
            "2025-06", "A1", title="更正公告", run_id="announcement-2"
        )
    )
    warehouse.commit_batch(_announcement_batch("2025-07", "A2"))

    removed = warehouse.prune_partitions_before(
        ResearchDatasetId.ANNOUNCEMENT, "2025-07"
    )

    assert removed == ("2025-06",)
    assert not (
        tmp_path / "facts" / "announcement" / "announcement_month=2025-06"
    ).exists()
    assert warehouse.partition_manifest(ResearchDatasetId.ANNOUNCEMENT)[
        "partition_value"
    ].tolist() == ["2025-07"]
    assert warehouse.revision_count(ResearchDatasetId.ANNOUNCEMENT) == 0
    current = warehouse.read_current(ResearchDatasetId.ANNOUNCEMENT)
    assert current["announcement_id"].tolist() == ["A2"]


def test_prune_partition_metadata_failure_restores_moved_files(
    tmp_path, monkeypatch
):
    warehouse = ResearchWarehouse(tmp_path)
    warehouse.commit_batch(_announcement_batch("2025-06", "A1"))

    def fail_metadata(*args, **kwargs):
        raise RuntimeError("simulated prune metadata failure")

    monkeypatch.setattr(warehouse, "_delete_partition_metadata", fail_metadata)

    with pytest.raises(RuntimeError, match="simulated prune metadata failure"):
        warehouse.prune_partitions_before(
            ResearchDatasetId.ANNOUNCEMENT, "2025-07"
        )

    assert len(
        warehouse.read_current(
            ResearchDatasetId.ANNOUNCEMENT, partition_value="2025-06"
        )
    ) == 1
    assert warehouse.partition_manifest(ResearchDatasetId.ANNOUNCEMENT)[
        "partition_value"
    ].tolist() == ["2025-06"]


def test_daily_fact_date_must_match_its_partition(tmp_path):
    warehouse = ResearchWarehouse(tmp_path)
    wrong_partition = _batch().model_copy(
        update={"partition_value": "2026-07-11"}
    )

    with pytest.raises(ValueError, match="partition does not match"):
        warehouse.commit_batch(wrong_partition)


def test_global_fact_keys_are_inserted_without_row_by_row_executemany(
    tmp_path, monkeypatch
):
    warehouse = ResearchWarehouse(tmp_path)
    real_connect = research_warehouse_module.connect_research_warehouse

    class NoFactKeyExecutemany:
        def __init__(self, connection):
            self.connection = connection

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return self.connection.__exit__(*args)

        def __getattr__(self, name):
            return getattr(self.connection, name)

        def executemany(self, sql, parameters):
            if "research_fact_keys" in sql:
                raise AssertionError("fact keys must use a bulk insert")
            return self.connection.executemany(sql, parameters)

    def connect_without_key_executemany(*args, **kwargs):
        return NoFactKeyExecutemany(real_connect(*args, **kwargs))

    monkeypatch.setattr(
        research_warehouse_module,
        "connect_research_warehouse",
        connect_without_key_executemany,
    )
    batch = FactBatch(
        dataset_id=ResearchDatasetId.COMPANY_PROFILE,
        partition_value="catalog-v1",
        source_name="tushare",
        source_endpoint="stock_company",
        ingestion_run_id="profile-1",
        ingested_at=datetime(2026, 7, 13, 10, tzinfo=timezone.utc),
        default_available_at=datetime(2026, 7, 13, 10, tzinfo=timezone.utc),
        records=[
            {
                "ts_code": "000001.SZ",
                "valid_from": date(1991, 4, 3),
                "company_name": "平安银行",
            }
        ],
    )

    warehouse.commit_batch(batch)

    assert len(warehouse.read_current(ResearchDatasetId.COMPANY_PROFILE)) == 1
