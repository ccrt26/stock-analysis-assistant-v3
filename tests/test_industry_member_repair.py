import os
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

from stock_analyzer.data.research_contracts import FactBatch, ResearchDatasetId
from stock_analyzer.ops import industry_member_repair
from stock_analyzer.ops.industry_member_repair import (
    MIGRATION_ID,
    RepairEvidenceProfile,
    run_industry_member_repair,
)
from stock_analyzer.storage.research_parquet import sha256_file
from stock_analyzer.storage.research_query import ResearchQuery
from stock_analyzer.storage.research_schema import connect_research_warehouse
from stock_analyzer.storage.research_warehouse import ResearchWarehouse


OLD_RECEIPT = datetime(2026, 7, 13, 16, 25, tzinfo=timezone.utc)
NEW_RECEIPT = datetime(2026, 8, 3, 13, 30, tzinfo=timezone.utc)


def _member_batch(
    *,
    valid_from: date,
    industry_code: str,
    industry_name: str,
    received_at: datetime,
    run_id: str,
    ts_code: str = "000876.SZ",
) -> FactBatch:
    return FactBatch(
        dataset_id=ResearchDatasetId.INDUSTRY_MEMBER,
        partition_value="SW2021",
        source_name="tushare",
        source_endpoint="index_member_all",
        ingestion_run_id=run_id,
        ingested_at=received_at,
        default_available_at=received_at,
        records=[
            {
                "ts_code": ts_code,
                "security_name": "新希望",
                "industry_system": "SW2021",
                "level": "L1",
                "industry_code": industry_code,
                "industry_name": industry_name,
                "valid_from": valid_from,
                "valid_to": None,
                "is_current": True,
                "available_at": datetime.combine(
                    valid_from,
                    datetime.min.time(),
                    timezone.utc,
                ),
            }
        ],
    )


def _corrupt_membership(warehouse: ResearchWarehouse, *, changed_code: bool) -> None:
    warehouse.commit_batch(
        _member_batch(
            valid_from=date(1998, 3, 11),
            industry_code="801010.SI",
            industry_name="农林牧渔",
            received_at=OLD_RECEIPT,
            run_id="classification:industry_member:initial",
        )
    )
    warehouse.commit_batch(
        _member_batch(
            valid_from=date(2026, 7, 1),
            industry_code="801020.SI" if changed_code else "801010.SI",
            industry_name="煤炭" if changed_code else "农林牧渔",
            received_at=NEW_RECEIPT,
            run_id="classification:industry_member:refresh",
        )
    )
    with connect_research_warehouse(warehouse.duckdb_path) as connection:
        connection.execute(
            """
            insert or replace into research_watermarks
            values ('classification_membership_month', '2026-08',
                    '2026-08-03', ?, 'classification:2026-08')
            """,
            [NEW_RECEIPT],
        )


def _fixture_evidence_profile(
    warehouse: ResearchWarehouse,
) -> RepairEvidenceProfile:
    frame = warehouse.read_current(
        ResearchDatasetId.INDUSTRY_MEMBER,
        partition_value="SW2021",
    )
    _, _, audit = industry_member_repair._repair_member_frame(
        frame, MIGRATION_ID
    )
    before = industry_member_repair._partition_receipt(warehouse, frame)
    entities = audit["entities"]
    return RepairEvidenceProfile(
        source_file_sha256=before["file_sha256"],
        candidate_manifest_hash=(
            industry_member_repair._candidate_manifest_hash(audit)
        ),
        repaired_slots=audit["repaired_slots"],
        stock_count=len({item["ts_code"] for item in entities}),
        level_counts=tuple(sorted(
            (level, sum(item["level"] == level for item in entities))
            for level in {item["level"] for item in entities}
        )),
        same_industry_slots=audit["same_industry_slots"],
        changed_industry_slots=audit["changed_industry_slots"],
        expected_new_valid_from=date.fromisoformat(
            entities[0]["new_valid_from"]
        ),
        expected_new_received_at=datetime.fromisoformat(
            entities[0]["new_received_at"]
        ),
    )


@pytest.mark.parametrize("changed_code", [False, True])
def test_industry_member_repair_backs_up_repairs_history_and_is_idempotent(
    tmp_path,
    changed_code,
):
    warehouse_root = tmp_path / "warehouse"
    archive_root = tmp_path / "archive"
    warehouse = ResearchWarehouse(warehouse_root)
    _corrupt_membership(warehouse, changed_code=changed_code)
    evidence_profile = _fixture_evidence_profile(warehouse)

    first = run_industry_member_repair(
        warehouse_root,
        archive_root,
        evidence_profile=evidence_profile,
    )
    rows = warehouse.read_current(ResearchDatasetId.INDUSTRY_MEMBER).sort_values(
        "valid_from"
    )
    query = ResearchQuery(warehouse)
    before_receipt = query.dataset_as_of(
        ResearchDatasetId.INDUSTRY_MEMBER,
        NEW_RECEIPT - timedelta(minutes=1),
    )
    after_receipt = query.dataset_as_of(
        ResearchDatasetId.INDUSTRY_MEMBER,
        NEW_RECEIPT + timedelta(minutes=1),
    ).sort_values("valid_from")
    partition_path = warehouse._partition_path(
        ResearchDatasetId.INDUSTRY_MEMBER,
        "SW2021",
    )
    first_sha = sha256_file(partition_path)

    assert first["status"] == "completed"
    assert first["industry_member"]["repaired_slots"] == 1
    assert first["industry_member"]["same_industry_slots"] == int(not changed_code)
    assert first["industry_member"]["changed_industry_slots"] == int(changed_code)
    assert len(first["industry_member"]["entities"]) == 1
    assert pd.Timestamp(rows.iloc[0]["valid_to"]).date() == date(2026, 6, 30)
    assert bool(rows.iloc[0]["is_current"]) is False
    assert int(rows.iloc[0]["revision_no"]) == 2
    assert pd.Timestamp(rows.iloc[1]["available_at"]).to_pydatetime() == NEW_RECEIPT
    assert rows.iloc[1]["availability_precision"] == "ingestion_cutoff"
    assert before_receipt["industry_code"].astype(str).tolist() == ["801010.SI"]
    assert pd.isna(before_receipt.iloc[0]["valid_to"])
    assert after_receipt["industry_code"].astype(str).tolist() == [
        "801010.SI",
        "801020.SI" if changed_code else "801010.SI",
    ]
    assert warehouse.revision_count(ResearchDatasetId.INDUSTRY_MEMBER) == 1

    repair_root = archive_root / "repairs" / first["migration_id"]
    assert (repair_root / "receipt.json").is_file()
    assert (repair_root / "backup-manifest.json").is_file()
    metadata_names = {
        path.name
        for path in (repair_root / "backups" / "duckdb_metadata").glob("*.parquet")
    }
    assert {
        "research_fact_partitions.parquet",
        "research_fact_keys.parquet",
        "research_fact_revisions.parquet",
        "research_ingestion_runs.parquet",
        "research_run_datasets.parquet",
        "research_watermarks.parquet",
    } <= metadata_names

    manifest = warehouse.partition_manifest(ResearchDatasetId.INDUSTRY_MEMBER).iloc[0]
    assert str(manifest["file_sha256"]) == first_sha
    assert not list(warehouse_root.rglob("*.previous"))

    second = run_industry_member_repair(
        warehouse_root,
        archive_root,
        evidence_profile=evidence_profile,
    )
    assert second["status"] == "already_applied"
    assert sha256_file(partition_path) == first_sha


def test_industry_member_repair_refuses_ambiguous_overlap_without_writing(tmp_path):
    warehouse_root = tmp_path / "warehouse"
    archive_root = tmp_path / "archive"
    warehouse = ResearchWarehouse(warehouse_root)
    _corrupt_membership(warehouse, changed_code=False)
    evidence_profile = _fixture_evidence_profile(warehouse)
    warehouse.commit_batch(
        _member_batch(
            valid_from=date(2026, 8, 1),
            industry_code="801010.SI",
            industry_name="农林牧渔",
            received_at=datetime(2026, 8, 4, tzinfo=timezone.utc),
            run_id="classification:industry_member:ambiguous",
        )
    )
    partition_path = warehouse._partition_path(
        ResearchDatasetId.INDUSTRY_MEMBER,
        "SW2021",
    )
    before_sha = sha256_file(partition_path)

    with pytest.raises(ValueError, match="ambiguous industry member overlap"):
        run_industry_member_repair(
            warehouse_root,
            archive_root,
            evidence_profile=evidence_profile,
        )

    assert sha256_file(partition_path) == before_sha
    assert warehouse.revision_count(ResearchDatasetId.INDUSTRY_MEMBER) == 0
    assert not list(warehouse_root.rglob("*.previous"))


def test_industry_member_repair_restores_partition_when_metadata_commit_fails(
    tmp_path,
    monkeypatch,
):
    warehouse_root = tmp_path / "warehouse"
    archive_root = tmp_path / "archive"
    warehouse = ResearchWarehouse(warehouse_root)
    _corrupt_membership(warehouse, changed_code=False)
    evidence_profile = _fixture_evidence_profile(warehouse)
    partition_path = warehouse._partition_path(
        ResearchDatasetId.INDUSTRY_MEMBER,
        "SW2021",
    )
    before_sha = sha256_file(partition_path)
    before_manifest = warehouse.partition_manifest(
        ResearchDatasetId.INDUSTRY_MEMBER
    ).iloc[0]

    def fail_metadata(*args, **kwargs):
        raise RuntimeError("injected metadata failure")

    monkeypatch.setattr(
        industry_member_repair,
        "_commit_repaired_metadata",
        fail_metadata,
    )
    with pytest.raises(RuntimeError, match="injected metadata failure"):
        run_industry_member_repair(
            warehouse_root,
            archive_root,
            evidence_profile=evidence_profile,
        )

    after_manifest = warehouse.partition_manifest(
        ResearchDatasetId.INDUSTRY_MEMBER
    ).iloc[0]
    assert sha256_file(partition_path) == before_sha
    assert str(after_manifest["file_sha256"]) == str(before_manifest["file_sha256"])
    assert warehouse.revision_count(ResearchDatasetId.INDUSTRY_MEMBER) == 0


def test_industry_member_repair_refuses_unreviewed_extra_candidate(tmp_path):
    warehouse_root = tmp_path / "warehouse"
    archive_root = tmp_path / "archive"
    warehouse = ResearchWarehouse(warehouse_root)
    _corrupt_membership(warehouse, changed_code=False)
    evidence_profile = _fixture_evidence_profile(warehouse)
    warehouse.commit_batch(
        _member_batch(
            ts_code="000001.SZ",
            valid_from=date(2000, 1, 1),
            industry_code="801010.SI",
            industry_name="农林牧渔",
            received_at=OLD_RECEIPT,
            run_id="classification:industry_member:extra-initial",
        )
    )
    warehouse.commit_batch(
        _member_batch(
            ts_code="000001.SZ",
            valid_from=date(2026, 7, 1),
            industry_code="801020.SI",
            industry_name="煤炭",
            received_at=NEW_RECEIPT,
            run_id="classification:industry_member:extra-refresh",
        )
    )
    partition_path = warehouse._partition_path(
        ResearchDatasetId.INDUSTRY_MEMBER, "SW2021"
    )
    before_sha = sha256_file(partition_path)

    with pytest.raises(ValueError, match="evidence profile mismatch"):
        run_industry_member_repair(
            warehouse_root,
            archive_root,
            evidence_profile=evidence_profile,
        )

    assert sha256_file(partition_path) == before_sha
    assert not (archive_root / "repairs" / MIGRATION_ID).exists()


def test_industry_member_repair_recovers_completed_promotion_and_receipt(
    tmp_path,
):
    warehouse_root = tmp_path / "warehouse"
    archive_root = tmp_path / "archive"
    warehouse = ResearchWarehouse(warehouse_root)
    _corrupt_membership(warehouse, changed_code=False)
    evidence_profile = _fixture_evidence_profile(warehouse)
    first = run_industry_member_repair(
        warehouse_root,
        archive_root,
        evidence_profile=evidence_profile,
    )
    repair_root = archive_root / "repairs" / MIGRATION_ID
    final_path = warehouse._partition_path(
        ResearchDatasetId.INDUSTRY_MEMBER, "SW2021"
    )
    previous_path = final_path.with_suffix(".parquet.previous")
    backup_path = repair_root / "backups" / first["partitions_before"][0][
        "relative_path"
    ]
    shutil.copy2(backup_path, previous_path)
    (repair_root / "receipt.json").unlink()
    stale_fact_stage = warehouse.staging_root / MIGRATION_ID / "partial"
    stale_fact_stage.mkdir(parents=True)
    (stale_fact_stage / "data.parquet").write_text(
        "interrupted", encoding="utf-8"
    )

    second = run_industry_member_repair(
        warehouse_root,
        archive_root,
        evidence_profile=evidence_profile,
    )

    assert second["status"] == "already_applied"
    assert (repair_root / "receipt.json").is_file()
    assert not previous_path.exists()
    assert not (warehouse.staging_root / MIGRATION_ID).exists()


def test_industry_member_repair_recovers_promotion_before_metadata_commit(
    tmp_path,
):
    warehouse_root = tmp_path / "warehouse"
    archive_root = tmp_path / "archive"
    warehouse = ResearchWarehouse(warehouse_root)
    _corrupt_membership(warehouse, changed_code=False)
    evidence_profile = _fixture_evidence_profile(warehouse)
    frame = warehouse.read_current(
        ResearchDatasetId.INDUSTRY_MEMBER, partition_value="SW2021"
    )
    repaired, _, _ = industry_member_repair._repair_member_frame(
        frame, MIGRATION_ID
    )
    final_path = warehouse._partition_path(
        ResearchDatasetId.INDUSTRY_MEMBER, "SW2021"
    )
    previous_path = final_path.with_suffix(".parquet.previous")
    os.replace(final_path, previous_path)
    repaired.to_parquet(final_path, index=False)

    result = run_industry_member_repair(
        warehouse_root,
        archive_root,
        evidence_profile=evidence_profile,
    )

    assert result["status"] == "completed"
    assert not previous_path.exists()


def test_industry_member_repair_discards_partial_staged_backup(tmp_path):
    warehouse_root = tmp_path / "warehouse"
    archive_root = tmp_path / "archive"
    warehouse = ResearchWarehouse(warehouse_root)
    _corrupt_membership(warehouse, changed_code=False)
    evidence_profile = _fixture_evidence_profile(warehouse)
    staged_root = (
        archive_root / "repairs" / f"{MIGRATION_ID}.backup-staged"
    )
    staged_root.mkdir(parents=True)
    (staged_root / "partial").write_text("interrupted", encoding="utf-8")

    result = run_industry_member_repair(
        warehouse_root,
        archive_root,
        evidence_profile=evidence_profile,
    )

    assert result["status"] == "completed"
    assert not staged_root.exists()
    assert not list(warehouse_root.rglob("*.previous"))
