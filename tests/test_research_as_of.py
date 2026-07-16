from datetime import date, datetime, timezone

from stock_analyzer.data.research_contracts import FactBatch, ResearchDatasetId
from stock_analyzer.storage.research_query import ResearchQuery
from stock_analyzer.storage.research_warehouse import ResearchWarehouse


def _announcement_batch(*, title: str, available_at: datetime, run_id: str):
    return FactBatch(
        dataset_id=ResearchDatasetId.ANNOUNCEMENT,
        partition_value="2026-07",
        source_name="cninfo",
        source_endpoint="new/hisAnnouncement/query",
        ingestion_run_id=run_id,
        ingested_at=available_at,
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
