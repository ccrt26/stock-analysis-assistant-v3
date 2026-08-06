from datetime import date, datetime, timezone
import json
from pathlib import Path
import shutil

import pandas as pd

from stock_analyzer.data.research_contracts import FactBatch, ResearchDatasetId
from stock_analyzer.ops.research_data_repair import (
    _repair_announcement_jitter,
    recover_interrupted_promotion,
    run_known_data_repair,
)
from stock_analyzer.storage.research_parquet import sha256_file
from stock_analyzer.storage.research_schema import connect_research_warehouse
from stock_analyzer.storage.research_warehouse import ResearchWarehouse


def _industry_batch(valid_from: date, run_id: str) -> FactBatch:
    return FactBatch(
        dataset_id=ResearchDatasetId.INDUSTRY_CATALOG,
        partition_value="SW2021",
        source_name="tushare",
        source_endpoint="index_classify+index_basic",
        ingestion_run_id=run_id,
        ingested_at=datetime.combine(valid_from, datetime.min.time(), timezone.utc),
        default_available_at=None,
        records=[
            {
                "industry_system": "SW2021",
                "level": "L3",
                "industry_code": "850401.SI",
                "classification_code": "230501",
                "industry_name": "特钢Ⅲ",
                "parent_code": "230500",
                "is_published": 1,
                "valid_from": valid_from,
                "valid_to": None,
            }
        ],
    )


def _announcement_batch(published_at: datetime) -> FactBatch:
    return FactBatch(
        dataset_id=ResearchDatasetId.ANNOUNCEMENT,
        partition_value="2026-07",
        source_name="cninfo",
        source_endpoint="new/hisAnnouncement/query",
        ingestion_run_id="legacy-announcement",
        ingested_at=datetime(2026, 7, 10, tzinfo=timezone.utc),
        default_available_at=published_at,
        records=[
            {
                "announcement_id": "ANN-LEGACY-JITTER",
                "announcement_time": published_at,
                "available_at": published_at,
                "title": "公告",
                "url": "https://example.invalid/ANN-LEGACY-JITTER.pdf",
            }
        ],
    )


def test_known_data_repair_backs_up_folds_faults_and_is_idempotent(tmp_path):
    warehouse_root = tmp_path / "warehouse"
    archive_root = tmp_path / "archive"
    warehouse = ResearchWarehouse(warehouse_root)
    warehouse.commit_batch(_industry_batch(date(2026, 7, 13), "industry-first"))
    warehouse.commit_batch(_industry_batch(date(2026, 8, 3), "industry-repeat"))

    earlier = datetime(2026, 7, 9, 9, 16, 28, tzinfo=timezone.utc)
    later = datetime(2026, 7, 9, 9, 16, 29, tzinfo=timezone.utc)
    warehouse.commit_batch(_announcement_batch(earlier))
    current = warehouse.read_current(
        ResearchDatasetId.ANNOUNCEMENT,
        partition_value="2026-07",
    ).iloc[0].to_dict()
    old_payload = warehouse._normalize_batch(_announcement_batch(later)).iloc[0].to_dict()
    with connect_research_warehouse(warehouse.duckdb_path) as connection:
        connection.execute(
            """
            insert into research_fact_revisions values
            (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ResearchDatasetId.ANNOUNCEMENT.value,
                current["business_key_hash"],
                1,
                "2026-07",
                current["payload_hash"],
                json.dumps(old_payload, ensure_ascii=False, default=str),
                later,
                earlier,
                "legacy-jitter-run",
                json.dumps(["announcement_time"]),
            ],
        )

    first = run_known_data_repair(warehouse_root, archive_root)
    industry = warehouse.read_current(ResearchDatasetId.INDUSTRY_CATALOG)
    announcement = warehouse.read_current(ResearchDatasetId.ANNOUNCEMENT)
    first_partition_hashes = {
        row["relative_path"]: row["file_sha256"]
        for row in first["partitions_after"]
    }

    assert first["status"] == "completed"
    assert len(industry) == 1
    assert pd.Timestamp(industry.iloc[0]["valid_from"]).date() == date(2026, 7, 13)
    assert pd.Timestamp(announcement.iloc[0]["announcement_time"]) == pd.Timestamp(later)
    assert pd.Timestamp(announcement.iloc[0]["available_at"]) == pd.Timestamp(later)
    assert int(announcement.iloc[0]["revision_no"]) == 1
    assert warehouse.revision_count(ResearchDatasetId.ANNOUNCEMENT) == 0
    assert first["industry_catalog"]["removed_rows"] == 1
    assert first["announcement"]["folded_revision_rows"] == 1
    before_by_dataset = {
        row["dataset_id"]: row for row in first["partitions_before"]
    }
    after_by_dataset = {
        row["dataset_id"]: row for row in first["partitions_after"]
    }
    assert before_by_dataset["industry_catalog"]["row_count"] == 2
    assert after_by_dataset["industry_catalog"]["row_count"] == 1
    assert (
        before_by_dataset["announcement"]["content_hash"]
        != after_by_dataset["announcement"]["content_hash"]
    )
    assert (archive_root / "repairs" / first["migration_id"] / "receipt.json").is_file()
    assert len(list((archive_root / "repairs" / first["migration_id"] / "backups").rglob("*.parquet"))) >= 5

    retry = warehouse.commit_batch(_announcement_batch(later))
    assert retry.changed_rows == 0
    assert warehouse.revision_count(ResearchDatasetId.ANNOUNCEMENT) == 0

    second = run_known_data_repair(warehouse_root, archive_root)
    second_partition_hashes = {
        row["relative_path"]: row["file_sha256"]
        for row in second["partitions_after"]
    }

    assert second["status"] == "already_applied"
    assert second_partition_hashes == first_partition_hashes


def test_empty_change_artifact_keeps_current_normalized_payload_hash(tmp_path):
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    published = datetime(2026, 8, 3, 10, 32, 29, tzinfo=timezone.utc)
    current = warehouse._normalize_batch(_announcement_batch(published))
    expected_hash = str(current.iloc[0]["payload_hash"])
    current.loc[0, "available_at"] = datetime(
        2026, 8, 4, 13, 33, tzinfo=timezone.utc
    )
    old_payload = current.iloc[0].to_dict()
    old_payload["available_at"] = published
    old_payload["payload_hash"] = "legacy-parquet-derived-hash"
    repaired, folded, audit = _repair_announcement_jitter(
        {"2026-07": current},
        [
            {
                "business_key_hash": str(current.iloc[0]["business_key_hash"]),
                "revision_no": 1,
                "partition_value": "2026-07",
                "row_payload": old_payload,
                "changed_fields": [],
            }
        ],
    )

    assert len(folded) == 1
    assert audit["folded_revision_rows"] == 1
    assert str(repaired["2026-07"].iloc[0]["payload_hash"]) == expected_hash
    assert pd.Timestamp(repaired["2026-07"].iloc[0]["available_at"]) == pd.Timestamp(
        published
    )


def test_interrupted_promotion_recovery_restores_metadata_matched_previous(tmp_path):
    warehouse_root = tmp_path / "warehouse"
    archive_root = tmp_path / "archive"
    warehouse = ResearchWarehouse(warehouse_root)
    warehouse.commit_batch(_industry_batch(date(2026, 7, 13), "industry-first"))
    relative_path = (
        "facts/industry_catalog/classification_version=SW2021/data.parquet"
    )
    final_path = warehouse_root / relative_path
    expected_sha = sha256_file(final_path)
    previous_path = final_path.with_suffix(".parquet.previous")
    shutil.copy2(final_path, previous_path)
    orphan = pd.read_parquet(final_path)
    orphan.loc[0, "industry_name"] = "未提交的新文件"
    orphan.to_parquet(final_path, index=False)

    first = recover_interrupted_promotion(
        warehouse_root,
        archive_root,
        relative_path,
    )
    second = recover_interrupted_promotion(
        warehouse_root,
        archive_root,
        relative_path,
    )

    assert first["status"] == "recovered"
    assert second["status"] == "already_recovered"
    assert sha256_file(final_path) == expected_sha
    assert not previous_path.exists()
    assert Path(first["quarantined_orphan"]).is_file()
