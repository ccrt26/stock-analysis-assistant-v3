from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone

import pandas as pd
import pytest

from stock_analyzer.data.research_contracts import FactBatch, ResearchDatasetId
from stock_analyzer.storage.research_query import (
    ResearchQuery,
    _fact_content_hash,
    _resolve_as_of,
)
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
                "pre_close": 10.0,
                "change": close - 10.0,
                "pct_chg": (close / 10.0 - 1.0) * 100.0,
                "volume": 100.0,
                "amount": 1000.0,
                **(
                    {"available_at": available_at}
                    if available_at is not None
                    else {}
                ),
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


def _resolved_content_hash(frame: pd.DataFrame) -> str:
    rows = sorted(
        (
            str(row["business_key_hash"]),
            str(row["payload_hash"]),
            int(row.get("revision_no", 1)),
        )
        for row in frame.to_dict(orient="records")
    )
    encoded = json.dumps(
        rows,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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


def test_historical_relationship_hides_future_end_boundary(tmp_path):
    warehouse = ResearchWarehouse(tmp_path)
    warehouse.commit_batch(
        FactBatch(
            dataset_id=ResearchDatasetId.THEME_MEMBER,
            partition_value="official-theme-v1",
            source_name="tushare",
            source_endpoint="index_weight",
            ingestion_run_id="theme-members",
            ingested_at=datetime(2026, 7, 14, tzinfo=timezone.utc),
            records=[
                {
                    "theme_code": "000019.SH",
                    "ts_code": "000001.SZ",
                    "valid_from": date(2025, 7, 31),
                    "valid_to": date(2025, 8, 28),
                },
                {
                    "theme_code": "000019.SH",
                    "ts_code": "000002.SZ",
                    "valid_from": date(2025, 9, 1),
                    "valid_to": None,
                },
            ],
        )
    )
    query = ResearchQuery(warehouse)

    before_end = query.dataset_as_of(
        ResearchDatasetId.THEME_MEMBER,
        datetime(2025, 8, 15, 15, 59, tzinfo=timezone.utc),
    )
    after_end = query.dataset_as_of(
        ResearchDatasetId.THEME_MEMBER,
        datetime(2025, 8, 29, 15, 59, tzinfo=timezone.utc),
    )

    assert before_end["ts_code"].tolist() == ["000001.SZ"]
    assert pd.isna(before_end.iloc[0]["valid_to"])
    assert pd.Timestamp(after_end.iloc[0]["valid_to"]).date() == date(2025, 8, 28)


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
    current = warehouse.read_current_partitions(
        ResearchDatasetId.EQUITY_DAILY,
        ["2026-07-08"],
    )
    duplicate = current.copy()
    duplicate.loc[:, "business_key_hash"] = "distinct-corrupt-hash"

    class DuplicateWarehouse:
        def read_current_partitions_with_manifest(
            self, dataset_id, partition_values
        ):
            frame = pd.concat([current, duplicate], ignore_index=True)
            frame["__research_partition_value"] = "2026-07-08"
            return frame, pd.DataFrame(
                [{"partition_value": "2026-07-08"}]
            )

        def revision_rows(self, dataset_id, *, partition_values=None):
            return []

    with pytest.raises(ValueError, match="duplicate business key"):
        ResearchQuery(DuplicateWarehouse()).dataset_partitions_as_of(
            ResearchDatasetId.EQUITY_DAILY,
            ["2026-07-08"],
            datetime(2026, 7, 10, tzinfo=timezone.utc),
        )


def test_partition_query_and_manifest_fail_closed_when_file_is_missing(tmp_path):
    warehouse = ResearchWarehouse(tmp_path)
    warehouse.commit_batch(_daily_batch("2026-07-08"))
    _partition_file(tmp_path, "2026-07-08").unlink()
    query = ResearchQuery(warehouse)
    cutoff = datetime(2026, 7, 9, tzinfo=timezone.utc)

    with pytest.raises(FileNotFoundError, match="partition file"):
        query.dataset_partitions_as_of(
            ResearchDatasetId.EQUITY_DAILY,
            ["2026-07-08"],
            cutoff,
        )
    with pytest.raises(FileNotFoundError, match="partition file"):
        query.input_manifest(
            {ResearchDatasetId.EQUITY_DAILY: ["2026-07-08"]},
            as_of=cutoff,
        )


def test_partition_query_and_manifest_reject_valid_parquet_with_wrong_sha(tmp_path):
    warehouse = ResearchWarehouse(tmp_path)
    warehouse.commit_batch(_daily_batch("2026-07-08"))
    path = _partition_file(tmp_path, "2026-07-08")
    rewritten = pd.read_parquet(path)
    rewritten.loc[:, "close"] = 99.0
    rewritten.to_parquet(path, index=False)
    query = ResearchQuery(warehouse)
    cutoff = datetime(2026, 7, 9, tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        query.dataset_partitions_as_of(
            ResearchDatasetId.EQUITY_DAILY,
            ["2026-07-08"],
            cutoff,
        )
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        query.input_manifest(
            {ResearchDatasetId.EQUITY_DAILY: ["2026-07-08"]},
            as_of=cutoff,
        )


def test_input_manifest_has_exact_stably_ordered_partition_metadata_and_hash(
    tmp_path,
):
    warehouse = ResearchWarehouse(tmp_path)
    first = warehouse.commit_batch(_daily_batch("2026-07-08"))
    second = warehouse.commit_batch(_daily_batch("2026-07-09"))
    query = ResearchQuery(warehouse)
    cutoff = datetime(2026, 7, 10, tzinfo=timezone.utc)

    reversed_manifest = query.input_manifest(
        {ResearchDatasetId.EQUITY_DAILY: ["2026-07-09", "2026-07-08"]},
        as_of=cutoff,
    )
    ordered_manifest = query.input_manifest(
        {ResearchDatasetId.EQUITY_DAILY.value: ["2026-07-08", "2026-07-09"]},
        as_of=cutoff,
    )

    assert reversed_manifest == ordered_manifest
    assert reversed_manifest["as_of"] == "2026-07-10T00:00:00+00:00"
    assert reversed_manifest["partitions"] == [
        {
            "dataset": ResearchDatasetId.EQUITY_DAILY.value,
            "partition": "2026-07-08",
            "row_count": 1,
            "content_hash": first.content_hash,
            "file_sha256": first.file_sha256,
            "quality_status": "passed",
            "resolved_row_count": 1,
            "resolved_content_hash": first.content_hash,
            "selected_revision_count": 0,
        },
        {
            "dataset": ResearchDatasetId.EQUITY_DAILY.value,
            "partition": "2026-07-09",
            "row_count": 1,
            "content_hash": second.content_hash,
            "file_sha256": second.file_sha256,
            "quality_status": "passed",
            "resolved_row_count": 1,
            "resolved_content_hash": second.content_hash,
            "selected_revision_count": 0,
        },
    ]
    canonical = json.dumps(
        {
            "as_of": reversed_manifest["as_of"],
            "partitions": reversed_manifest["partitions"],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    assert reversed_manifest["input_manifest_hash"] == hashlib.sha256(
        canonical
    ).hexdigest()


def test_manifest_binds_historical_revision_snapshot_and_cutoff(tmp_path):
    warehouse = ResearchWarehouse(tmp_path)
    warehouse.commit_batch(
        _daily_batch(
            "2026-07-08",
            close=10.2,
            available_at=datetime(2026, 7, 8, 8, tzinfo=timezone.utc),
            run_id="first",
        )
    )
    current = warehouse.commit_batch(
        _daily_batch(
            "2026-07-08",
            close=10.8,
            available_at=datetime(2026, 7, 10, 8, tzinfo=timezone.utc),
            run_id="correction",
        )
    )
    query = ResearchQuery(warehouse)
    requested = {ResearchDatasetId.EQUITY_DAILY: ["2026-07-08"]}
    early_cutoff = datetime(2026, 7, 9, tzinfo=timezone.utc)
    late_cutoff = datetime(2026, 7, 11, tzinfo=timezone.utc)

    early = query.input_manifest(requested, as_of=early_cutoff)
    late = query.input_manifest(requested, as_of=late_cutoff)
    resolved = query.dataset_partitions_as_of(
        ResearchDatasetId.EQUITY_DAILY,
        ["2026-07-08"],
        early_cutoff,
    )

    assert early["partitions"][0]["content_hash"] == current.content_hash
    assert early["partitions"][0]["resolved_content_hash"] == (
        _resolved_content_hash(resolved)
    )
    assert early["partitions"][0]["resolved_content_hash"] != current.content_hash
    assert early["partitions"][0]["selected_revision_count"] == 1
    assert late["partitions"][0]["resolved_content_hash"] == current.content_hash
    assert late["partitions"][0]["selected_revision_count"] == 0
    assert early["partitions"][0]["resolved_content_hash"] != (
        late["partitions"][0]["resolved_content_hash"]
    )
    assert early["input_manifest_hash"] != late["input_manifest_hash"]


def test_manifest_excludes_future_trade_date_partitions(tmp_path):
    warehouse = ResearchWarehouse(tmp_path)
    warehouse.commit_batch(_daily_batch("2026-07-08"))
    warehouse.commit_batch(
        _daily_batch(
            "2026-07-10",
            available_at=datetime(2026, 7, 8, 8, tzinfo=timezone.utc),
        )
    )

    manifest = ResearchQuery(warehouse).input_manifest(
        {ResearchDatasetId.EQUITY_DAILY: ["2026-07-08", "2026-07-10"]},
        as_of=datetime(2026, 7, 9, 15, 59, tzinfo=timezone.utc),
    )

    assert [item["partition"] for item in manifest["partitions"]] == [
        "2026-07-08"
    ]


def test_materialized_snapshot_hashes_the_exact_frames_returned_to_formula(tmp_path):
    warehouse = ResearchWarehouse(tmp_path)
    warehouse.commit_batch(_daily_batch("2026-07-08", close=10.2))
    current, metadata = warehouse.read_current_partitions_with_manifest(
        ResearchDatasetId.EQUITY_DAILY,
        ["2026-07-08"],
    )

    class ChangingWarehouse:
        def __init__(self):
            self.read_count = 0

        def read_current_partitions_with_manifest(
            self, dataset_id, partition_values
        ):
            self.read_count += 1
            frame = current.copy()
            if self.read_count > 1:
                frame.loc[:, "close"] = 99.0
                frame.loc[:, "payload_hash"] = "later-revision"
            return frame, metadata.copy()

        def revision_rows(self, dataset_id, *, partition_values=None):
            return []

    changing = ChangingWarehouse()
    snapshot = ResearchQuery(changing).materialize_snapshot(
        {ResearchDatasetId.EQUITY_DAILY: ["2026-07-08"]},
        as_of=datetime(2026, 7, 9, tzinfo=timezone.utc),
    )
    resolved = snapshot.frame(ResearchDatasetId.EQUITY_DAILY)

    assert changing.read_count == 1
    assert resolved.iloc[0]["close"] == pytest.approx(10.2)
    assert snapshot.input_manifest["partitions"][0][
        "resolved_content_hash"
    ] == _resolved_content_hash(resolved)

    resolved.loc[:, "close"] = -1.0
    assert snapshot.frame(ResearchDatasetId.EQUITY_DAILY).iloc[0][
        "close"
    ] == pytest.approx(10.2)


def test_large_as_of_resolution_and_hashing_do_not_materialize_python_row_dicts(
    monkeypatch,
):
    row_count = 20_000
    current = pd.DataFrame(
        {
            "trade_date": [date(2026, 7, 10)] * row_count,
            "ts_code": [f"{value:06d}.SZ" for value in range(row_count)],
            "business_key_hash": [f"key-{value}" for value in range(row_count)],
            "payload_hash": [f"payload-{value}" for value in range(row_count)],
            "available_at": [datetime(2026, 7, 10, 8, tzinfo=timezone.utc)]
            * row_count,
            "revision_no": [1] * row_count,
        }
    )
    later = current.iloc[0].to_dict()
    later.update(
        payload_hash="revised",
        available_at=datetime(2026, 7, 10, 9, tzinfo=timezone.utc),
        revision_no=2,
    )
    monkeypatch.setattr(
        pd.DataFrame,
        "to_dict",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("large snapshots must not become Python row dictionaries")
        ),
    )

    resolved = _resolve_as_of(
        ResearchDatasetId.EQUITY_DAILY,
        current,
        [{"row_payload": later}],
        datetime(2026, 7, 11, tzinfo=timezone.utc),
    )
    digest = _fact_content_hash(resolved)

    assert len(resolved) == row_count
    assert resolved.iloc[0]["payload_hash"] == "revised"
    assert len(digest) == 64


def test_manifest_groups_resolved_rows_once_instead_of_rescanning_per_partition(
    monkeypatch,
):
    partitions = [f"2026-06-{day:02d}" for day in range(1, 9)]
    frame = pd.DataFrame(
        [
            {
                "trade_date": date.fromisoformat(partition),
                "ts_code": f"{code:06d}.SZ",
                "business_key_hash": f"{partition}-{code}",
                "payload_hash": f"payload-{partition}-{code}",
                "available_at": datetime(2026, 6, 20, tzinfo=timezone.utc),
                "revision_no": 1,
                "__research_partition_value": partition,
            }
            for partition in partitions
            for code in range(10)
        ]
    )
    metadata = pd.DataFrame(
        [
            {
                "partition_value": partition,
                "row_count": 10,
                "content_hash": f"content-{partition}",
                "file_sha256": f"file-{partition}",
                "quality_status": "passed",
            }
            for partition in partitions
        ]
    )

    class Warehouse:
        def read_current_partitions_with_manifest(self, dataset, selected):
            return frame.copy(), metadata.copy()

        def revision_rows(self, dataset, *, partition_values=None):
            return []

    comparisons = 0
    original_eq = pd.Series.__eq__

    def count_partition_comparison(series, other):
        nonlocal comparisons
        if series.name == "__research_partition_value":
            comparisons += 1
        return original_eq(series, other)

    monkeypatch.setattr(pd.Series, "__eq__", count_partition_comparison)

    snapshot = ResearchQuery(Warehouse()).materialize_snapshot(
        {ResearchDatasetId.EQUITY_DAILY: partitions},
        as_of=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )

    assert len(snapshot.input_manifest["partitions"]) == len(partitions)
    assert comparisons <= 1


def _financial_batch(
    dataset: ResearchDatasetId,
    *,
    available_at: datetime,
    rows: list[dict[str, object]],
    run_id: str,
) -> FactBatch:
    return FactBatch(
        dataset_id=dataset,
        partition_value="2025-12-31",
        source_name="tushare",
        source_endpoint=(
            "fina_indicator"
            if dataset is ResearchDatasetId.FINANCIAL_INDICATOR
            else "cashflow"
        ),
        ingestion_run_id=run_id,
        ingested_at=available_at,
        default_available_at=available_at,
        records=[
            {
                **row,
                "available_at": row.get("available_at", available_at),
                "availability_precision": "date_conservative",
            }
            for row in rows
        ],
    )


def test_financial_indicator_as_of_uses_repository_revisions_without_update_flag(
    tmp_path,
):
    warehouse = ResearchWarehouse(tmp_path)
    first = datetime(2026, 3, 31, 16, tzinfo=timezone.utc)
    revised = datetime(2026, 4, 30, 16, tzinfo=timezone.utc)
    base = {
        "ts_code": "000001.SZ",
        "report_period": date(2025, 12, 31),
        "report_type": "indicator",
        "ann_date": date(2026, 3, 31),
        "roe": 10.0,
    }
    warehouse.commit_batch(
        _financial_batch(
            ResearchDatasetId.FINANCIAL_INDICATOR,
            available_at=first,
            rows=[base],
            run_id="indicator-first",
        )
    )
    warehouse.commit_batch(
        _financial_batch(
            ResearchDatasetId.FINANCIAL_INDICATOR,
            available_at=revised,
            rows=[{**base, "roe": 11.0, "available_at": revised}],
            run_id="indicator-revised",
        )
    )

    early = ResearchQuery(warehouse).comparable_financials_as_of(
        ResearchDatasetId.FINANCIAL_INDICATOR,
        datetime(2026, 4, 15, tzinfo=timezone.utc),
    )
    late = ResearchQuery(warehouse).comparable_financials_as_of(
        ResearchDatasetId.FINANCIAL_INDICATOR,
        datetime(2026, 5, 1, tzinfo=timezone.utc),
    )

    assert early.iloc[0]["roe"] == pytest.approx(10.0)
    assert late.iloc[0]["roe"] == pytest.approx(11.0)
    assert "update_flag" not in late.columns


def test_cash_flow_comparable_selection_preserves_variants_and_is_time_point_safe(
    tmp_path,
):
    warehouse = ResearchWarehouse(tmp_path)
    early_time = datetime(2026, 3, 7, 16, tzinfo=timezone.utc)
    final_time = datetime(2026, 5, 15, 16, tzinfo=timezone.utc)
    early = {
        "ts_code": "603049.SH",
        "report_period": date(2024, 12, 31),
        "report_type": "1",
        "statement_type": "comp=1;end=unknown",
        "comp_type": "1",
        "end_type": None,
        "update_flag": "0",
        "ann_date": date(2026, 3, 7),
        "f_ann_date": date(2026, 3, 7),
        "n_cashflow_act": 100.0,
    }
    warehouse.commit_batch(
        _financial_batch(
            ResearchDatasetId.CASH_FLOW,
            available_at=early_time,
            rows=[early],
            run_id="cash-early",
        )
    )
    warehouse.commit_batch(
        _financial_batch(
            ResearchDatasetId.CASH_FLOW,
            available_at=final_time,
            rows=[
                {
                    **early,
                    "statement_type": "comp=1;end=4",
                    "end_type": "4",
                    "update_flag": "1",
                    "ann_date": date(2026, 5, 15),
                    "n_cashflow_act": 120.0,
                    "available_at": final_time,
                }
            ],
            run_id="cash-final",
        )
    )
    query = ResearchQuery(warehouse)

    raw = query.dataset_as_of(
        ResearchDatasetId.CASH_FLOW,
        datetime(2026, 5, 16, tzinfo=timezone.utc),
    )
    early_selected = query.comparable_financials_as_of(
        ResearchDatasetId.CASH_FLOW,
        datetime(2026, 4, 1, tzinfo=timezone.utc),
    )
    final_selected = query.comparable_financials_as_of(
        ResearchDatasetId.CASH_FLOW,
        datetime(2026, 5, 16, tzinfo=timezone.utc),
    )

    assert len(raw) == 2
    assert early_selected.iloc[0]["statement_type"] == "comp=1;end=unknown"
    assert final_selected.iloc[0]["statement_type"] == "comp=1;end=4"
    assert final_selected.iloc[0]["n_cashflow_act"] == pytest.approx(120.0)
    assert final_selected.iloc[0]["comparable_candidate_count"] == 2
    assert "end_type_match" in final_selected.iloc[0]["comparable_selection_rule"]


def test_statement_comparable_selection_tolerates_optional_update_and_end_type(
    tmp_path,
):
    warehouse = ResearchWarehouse(tmp_path)
    available = datetime(2026, 3, 31, 16, tzinfo=timezone.utc)
    warehouse.commit_batch(
        FactBatch(
            dataset_id=ResearchDatasetId.INCOME_STATEMENT,
            partition_value="2025-12-31",
            source_name="tushare",
            source_endpoint="income",
            ingestion_run_id="income-without-optional-ranking-fields",
            ingested_at=available,
            default_available_at=available,
            records=[
                {
                    "ts_code": "000001.SZ",
                    "report_period": date(2025, 12, 31),
                    "report_type": "1",
                        "statement_type": "consolidated",
                        "revenue": 100.0,
                        "available_at": available,
                        "availability_precision": "date_conservative",
                    }
            ],
        )
    )

    selected = ResearchQuery(warehouse).comparable_financials_as_of(
        ResearchDatasetId.INCOME_STATEMENT,
        datetime(2026, 4, 1, tzinfo=timezone.utc),
    )

    assert len(selected) == 1
    assert selected.iloc[0]["revenue"] == pytest.approx(100.0)
