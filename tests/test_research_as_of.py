from datetime import date, datetime, timedelta, timezone

import pytest
import pandas as pd

from stock_analyzer.data.research_contracts import FactBatch, ResearchDatasetId
from stock_analyzer.storage.research_query import ResearchQuery
from stock_analyzer.storage.research_warehouse import ResearchWarehouse


def _balance_batch(
    *,
    total_assets: float,
    published_at: datetime,
    ingested_at: datetime,
    run_id: str,
) -> FactBatch:
    return FactBatch(
        dataset_id=ResearchDatasetId.BALANCE_SHEET,
        partition_value="2025-12-31",
        source_name="tushare",
        source_endpoint="balancesheet",
        ingestion_run_id=run_id,
        ingested_at=ingested_at,
        default_available_at=published_at,
        records=[
            {
                "ts_code": "000001.SZ",
                "report_period": date(2025, 12, 31),
                "report_type": "1",
                "statement_type": "comp=1;end=4",
                "ann_date": "20260429",
                "f_ann_date": "20260429",
                "comp_type": "1",
                "end_type": "4",
                "update_flag": "1",
                "total_assets": total_assets,
                "available_at": published_at,
            }
        ],
    )


def _announcement_batch(
    *,
    title: str,
    available_at: datetime,
    run_id: str,
    ingested_at: datetime | None = None,
):
    received_at = ingested_at or available_at
    return FactBatch(
        dataset_id=ResearchDatasetId.ANNOUNCEMENT,
        partition_value="2026-07",
        source_name="cninfo",
        source_endpoint="new/hisAnnouncement/query",
        ingestion_run_id=run_id,
        ingested_at=received_at,
        default_available_at=available_at,
        records=[
            {
                "announcement_id": "ANN-1",
                "ts_code": "000001.SZ",
                "announcement_time": available_at,
                "available_at": available_at,
                "title": title,
                "url": "https://example.invalid/ANN-1.pdf",
            }
        ],
    )


def test_as_of_excludes_future_announcement_and_can_reconstruct_earlier_revision(tmp_path):
    warehouse = ResearchWarehouse(tmp_path)
    first_time = datetime(2026, 7, 10, 12, tzinfo=timezone.utc)
    corrected_time = datetime(2026, 7, 11, 2, tzinfo=timezone.utc)
    warehouse.commit_batch(
        _announcement_batch(title="首次公告", available_at=first_time, run_id="r1")
    )
    warehouse.commit_batch(
        _announcement_batch(title="更正公告", available_at=corrected_time, run_id="r2")
    )
    query = ResearchQuery(warehouse)

    before = query.dataset_as_of(
        ResearchDatasetId.ANNOUNCEMENT,
        datetime(2026, 7, 10, 10, tzinfo=timezone.utc),
    )
    at_first = query.dataset_as_of(
        ResearchDatasetId.ANNOUNCEMENT,
        datetime(2026, 7, 10, 13, tzinfo=timezone.utc),
    )
    after = query.dataset_as_of(
        ResearchDatasetId.ANNOUNCEMENT,
        datetime(2026, 7, 11, 3, tzinfo=timezone.utc),
    )

    assert before.empty
    assert at_first.iloc[0]["title"] == "首次公告"
    assert after.iloc[0]["title"] == "更正公告"


def test_substantive_announcement_revision_uses_observed_receipt_when_source_time_recedes(
    tmp_path,
):
    warehouse = ResearchWarehouse(tmp_path)
    first_time = datetime(2026, 7, 10, 12, tzinfo=timezone.utc)
    receded_source_time = datetime(2026, 7, 10, 11, 59, tzinfo=timezone.utc)
    correction_received_at = datetime(2026, 7, 11, 2, tzinfo=timezone.utc)
    warehouse.commit_batch(
        _announcement_batch(title="首次公告", available_at=first_time, run_id="r1")
    )
    warehouse.commit_batch(
        _announcement_batch(
            title="更正公告",
            available_at=receded_source_time,
            ingested_at=correction_received_at,
            run_id="r2",
        )
    )

    query = ResearchQuery(warehouse)
    before_receipt = query.dataset_as_of(
        ResearchDatasetId.ANNOUNCEMENT,
        datetime(2026, 7, 10, 13, tzinfo=timezone.utc),
    )
    after_receipt = query.dataset_as_of(
        ResearchDatasetId.ANNOUNCEMENT,
        datetime(2026, 7, 11, 3, tzinfo=timezone.utc),
    )
    current = warehouse.read_current(ResearchDatasetId.ANNOUNCEMENT)
    revision = warehouse.revision_rows(ResearchDatasetId.ANNOUNCEMENT)[0]

    assert before_receipt.iloc[0]["title"] == "首次公告"
    assert after_receipt.iloc[0]["title"] == "更正公告"
    assert current.iloc[0]["available_at"].to_pydatetime() == correction_received_at
    assert revision["valid_from"] <= revision["valid_to"]


def test_late_financial_correction_with_same_source_time_is_not_visible_before_receipt(
    tmp_path,
):
    warehouse = ResearchWarehouse(tmp_path)
    published = datetime(2026, 4, 30, tzinfo=timezone.utc)
    warehouse.commit_batch(
        _balance_batch(
            total_assets=100.0,
            published_at=published,
            ingested_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
            run_id="balance-original",
        )
    )
    received = datetime(2026, 7, 14, tzinfo=timezone.utc)
    warehouse.commit_batch(
        _balance_batch(
            total_assets=101.0,
            published_at=published,
            ingested_at=received,
            run_id="balance-correction",
        )
    )

    query = ResearchQuery(warehouse)
    before_receipt = query.dataset_as_of(
        ResearchDatasetId.BALANCE_SHEET,
        datetime(2026, 5, 2, tzinfo=timezone.utc),
    )
    after_receipt = query.dataset_as_of(
        ResearchDatasetId.BALANCE_SHEET,
        datetime(2026, 7, 15, tzinfo=timezone.utc),
    )

    assert before_receipt.iloc[0]["total_assets"] == 100.0
    assert after_receipt.iloc[0]["total_assets"] == 101.0


def test_as_of_rejects_naive_cutoff_instead_of_assuming_utc(tmp_path):
    query = ResearchQuery(ResearchWarehouse(tmp_path))

    with pytest.raises(ValueError, match="timezone-aware"):
        query.dataset_as_of(
            ResearchDatasetId.ANNOUNCEMENT,
            datetime(2026, 7, 10, 15),
        )


def test_industry_member_current_flag_is_recomputed_at_historical_cutoff(tmp_path):
    warehouse = ResearchWarehouse(tmp_path)
    warehouse.commit_batch(
        FactBatch(
            dataset_id=ResearchDatasetId.INDUSTRY_MEMBER,
            partition_value="SW2021",
            source_name="tushare",
            source_endpoint="index_member_all",
            ingestion_run_id="industry-history",
            ingested_at=datetime(2026, 8, 3, tzinfo=timezone.utc),
            default_available_at=datetime(2020, 1, 1, 7, 1, tzinfo=timezone.utc),
            records=[
                {
                    "ts_code": "000001.SZ",
                    "industry_system": "SW2021",
                    "level": "L1",
                    "industry_code": "801010.SI",
                    "industry_name": "农林牧渔",
                    "valid_from": date(2020, 1, 1),
                    "valid_to": date(2026, 8, 1),
                    "is_current": False,
                    "available_at": datetime(
                        2020, 1, 1, 7, 1, tzinfo=timezone.utc
                    ),
                }
            ],
        )
    )

    row = ResearchQuery(warehouse).dataset_as_of(
        ResearchDatasetId.INDUSTRY_MEMBER,
        datetime(2025, 1, 1, tzinfo=timezone.utc),
    ).iloc[0]

    assert pd.isna(row["valid_to"])
    assert bool(row["is_current"]) is True


def test_as_of_accepts_mixed_iso_precision_and_compares_absolute_instants():
    class StaticWarehouse:
        def read_current(self, dataset_id):
            return pd.DataFrame.from_records(
                [
                    {
                        "announcement_id": "AT-CUTOFF",
                        "business_key_hash": "at-cutoff",
                        "revision_no": 1,
                        "available_at": "2026-07-10T20:00:00+08:00",
                        "title": "截止时刻可见",
                    },
                    {
                        "announcement_id": "AFTER-CUTOFF",
                        "business_key_hash": "after-cutoff",
                        "revision_no": 1,
                        "available_at": "2026-07-10T12:00:00.000001+00:00",
                        "title": "截止时刻后不可见",
                    },
                    {
                        "announcement_id": "MISSING-CUTOFF",
                        "business_key_hash": "missing-cutoff",
                        "revision_no": 1,
                        "available_at": None,
                        "title": "缺少可用时间不可见",
                    },
                ]
            )

        def revision_rows(self, dataset_id):
            return []

    result = ResearchQuery(StaticWarehouse()).dataset_as_of(
        ResearchDatasetId.ANNOUNCEMENT,
        datetime(2026, 7, 10, 12, tzinfo=timezone.utc),
    )

    assert result["announcement_id"].tolist() == ["AT-CUTOFF"]


def test_as_of_rejects_invalid_available_at():
    class StaticWarehouse:
        def read_current(self, dataset_id):
            return pd.DataFrame.from_records(
                [
                    {
                        "announcement_id": "INVALID-TIME",
                        "business_key_hash": "invalid-time",
                        "revision_no": 1,
                        "available_at": "not-an-iso-time",
                        "title": "非法时间",
                    }
                ]
            )

        def revision_rows(self, dataset_id):
            return []

    with pytest.raises(ValueError):
        ResearchQuery(StaticWarehouse()).dataset_as_of(
            ResearchDatasetId.ANNOUNCEMENT,
            datetime(2026, 7, 10, 12, tzinfo=timezone.utc),
        )


def test_mixed_precision_revisions_keep_as_of_selection_order(tmp_path):
    warehouse = ResearchWarehouse(tmp_path)
    published = datetime(2026, 4, 30, tzinfo=timezone.utc)
    warehouse.commit_batch(
        _balance_batch(
            total_assets=100.0,
            published_at=published,
            ingested_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
            run_id="balance-original",
        )
    )
    correction_with_fraction = datetime(
        2026, 7, 14, 4, 0, 0, 123456, tzinfo=timezone.utc
    )
    warehouse.commit_batch(
        _balance_batch(
            total_assets=101.0,
            published_at=published,
            ingested_at=correction_with_fraction,
            run_id="balance-correction-fractional",
        )
    )
    warehouse.commit_batch(
        _balance_batch(
            total_assets=102.0,
            published_at=published,
            ingested_at=datetime(2026, 7, 15, 4, tzinfo=timezone.utc),
            run_id="balance-correction-whole-second",
        )
    )

    at_second_revision = ResearchQuery(warehouse).dataset_as_of(
        ResearchDatasetId.BALANCE_SHEET,
        datetime(
            2026,
            7,
            14,
            12,
            0,
            0,
            123456,
            tzinfo=timezone(timedelta(hours=8)),
        ),
    )

    assert at_second_revision.iloc[0]["total_assets"] == 101.0
