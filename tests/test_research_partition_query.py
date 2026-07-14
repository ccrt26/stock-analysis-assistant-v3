from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone

import pandas as pd
import pytest

from stock_analyzer.data.research_contracts import FactBatch, ResearchDatasetId
from stock_analyzer.storage.research_query import ResearchQuery
from stock_analyzer.storage.research_warehouse import ResearchWarehouse


def _daily_batch(
    partition: str,
    *,
    close: float = 10.2,
    available_at: datetime | None = None,
    run_id: str | None = None,
) -> FactBatch:
    trade_date = date.fromisoformat(partition)
    known_at = available_at or datetime(
        trade_date.year,
        trade_date.month,
        trade_date.day,
        8,
        tzinfo=timezone.utc,
    )
    return FactBatch(
        dataset_id=ResearchDatasetId.EQUITY_DAILY,
        partition_value=partition,
        source_name="tushare",
        source_endpoint="daily",
        ingestion_run_id=run_id or f"daily-{partition}",
        ingested_at=known_at,
        default_available_at=known_at,
        records=[
            {
                "trade_date": trade_date,
                "ts_code": "000001.SZ",
                "open": 10.0,
                "high": max(10.5, close),
                "low": min(9.8, close),
                "close": close,
                "vol": 100.0,
                "amount": 1000.0,
            }
        ],
    )


def _partition_file(root, partition: str):
    return (
        root
        / "facts"
        / ResearchDatasetId.EQUITY_DAILY.value
        / f"trade_date={partition}"
        / "data.parquet"
    )


def test_partition_query_physically_reads_only_requested_parquet_files(tmp_path):
    warehouse = ResearchWarehouse(tmp_path)
    warehouse.commit_batch(_daily_batch("2026-07-08"))
    warehouse.commit_batch(_daily_batch("2026-07-11"))
    _partition_file(tmp_path, "2026-07-11").write_bytes(b"not a parquet file")

    result = ResearchQuery(warehouse).dataset_partitions_as_of(
        ResearchDatasetId.EQUITY_DAILY,
        ["2026-07-08"],
        datetime(2026, 7, 12, tzinfo=timezone.utc),
    )

    assert pd.to_datetime(result["trade_date"]).dt.date.tolist() == [
        date(2026, 7, 8)
    ]


def test_partition_query_applies_cutoff_and_recovers_the_known_revision(tmp_path):
    warehouse = ResearchWarehouse(tmp_path)
    warehouse.commit_batch(
        _daily_batch(
            "2026-07-08",
            close=10.2,
            available_at=datetime(2026, 7, 8, 8, tzinfo=timezone.utc),
            run_id="first",
        )
    )
    warehouse.commit_batch(
        _daily_batch(
            "2026-07-08",
            close=10.8,
            available_at=datetime(2026, 7, 10, 8, tzinfo=timezone.utc),
            run_id="correction",
        )
    )
    warehouse.commit_batch(
        _daily_batch(
            "2026-07-09",
            close=11.0,
            available_at=datetime(2026, 7, 9, 13, tzinfo=timezone.utc),
        )
    )

    result = ResearchQuery(warehouse).dataset_partitions_as_of(
        ResearchDatasetId.EQUITY_DAILY,
        ["2026-07-08", "2026-07-09"],
        datetime(2026, 7, 9, 12, tzinfo=timezone.utc),
    )

    assert len(result) == 1
    assert result.iloc[0]["close"] == pytest.approx(10.2)
    assert int(result.iloc[0]["revision_no"]) == 1


def test_partition_query_never_admits_a_future_partition_at_historical_cutoff(
    tmp_path,
):
    warehouse = ResearchWarehouse(tmp_path)
    warehouse.commit_batch(_daily_batch("2026-07-08"))
    warehouse.commit_batch(
        _daily_batch(
            "2026-07-10",
            available_at=datetime(2026, 7, 8, 8, tzinfo=timezone.utc),
        )
    )

    result = ResearchQuery(warehouse).dataset_partitions_as_of(
        ResearchDatasetId.EQUITY_DAILY,
        ["2026-07-08", "2026-07-10"],
        datetime(2026, 7, 9, 15, 59, tzinfo=timezone.utc),
    )

    assert pd.to_datetime(result["trade_date"]).dt.date.tolist() == [
        date(2026, 7, 8)
    ]


def test_partition_query_fails_closed_on_duplicate_business_keys(tmp_path):
    warehouse = ResearchWarehouse(tmp_path)
    warehouse.commit_batch(_daily_batch("2026-07-08"))
    warehouse.commit_batch(_daily_batch("2026-07-09"))

    first = pd.read_parquet(_partition_file(tmp_path, "2026-07-08"))
    duplicate = pd.read_parquet(_partition_file(tmp_path, "2026-07-09"))
    duplicate.loc[:, "trade_date"] = first.iloc[0]["trade_date"]
    duplicate.to_parquet(_partition_file(tmp_path, "2026-07-09"), index=False)

    with pytest.raises(ValueError, match="duplicate business key"):
        ResearchQuery(warehouse).dataset_partitions_as_of(
            ResearchDatasetId.EQUITY_DAILY,
            ["2026-07-08", "2026-07-09"],
            datetime(2026, 7, 10, tzinfo=timezone.utc),
        )


def test_input_manifest_has_exact_stably_ordered_partition_metadata_and_hash(
    tmp_path,
):
    warehouse = ResearchWarehouse(tmp_path)
    first = warehouse.commit_batch(_daily_batch("2026-07-08"))
    second = warehouse.commit_batch(_daily_batch("2026-07-09"))
    query = ResearchQuery(warehouse)

    reversed_manifest = query.input_manifest(
        {ResearchDatasetId.EQUITY_DAILY: ["2026-07-09", "2026-07-08"]}
    )
    ordered_manifest = query.input_manifest(
        {ResearchDatasetId.EQUITY_DAILY.value: ["2026-07-08", "2026-07-09"]}
    )

    assert reversed_manifest == ordered_manifest
    assert reversed_manifest["partitions"] == [
        {
            "dataset": ResearchDatasetId.EQUITY_DAILY.value,
            "partition": "2026-07-08",
            "row_count": 1,
            "content_hash": first.content_hash,
            "file_sha256": first.file_sha256,
            "quality_status": "passed",
        },
        {
            "dataset": ResearchDatasetId.EQUITY_DAILY.value,
            "partition": "2026-07-09",
            "row_count": 1,
            "content_hash": second.content_hash,
            "file_sha256": second.file_sha256,
            "quality_status": "passed",
        },
    ]
    canonical = json.dumps(
        reversed_manifest["partitions"],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    assert reversed_manifest["input_manifest_hash"] == hashlib.sha256(
        canonical
    ).hexdigest()
