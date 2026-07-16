from __future__ import annotations

from datetime import date, datetime, timezone

import pandas as pd
import pytest

from stock_analyzer.data.research_contracts import (
    AvailabilityPolicy,
    FactBatch,
    ResearchDatasetId,
    research_contract,
)
from stock_analyzer.storage import research_time_migration as migration_module
from stock_analyzer.storage.research_parquet import sha256_file
from stock_analyzer.storage.research_time_migration import (
    audit_research_time_semantics,
    migrate_research_time_semantics,
)
from stock_analyzer.storage.research_warehouse import ResearchWarehouse


_BACKFILL = datetime(2026, 7, 13, 7, 1, tzinfo=timezone.utc)
_INGESTED = datetime(2026, 7, 13, 15, 30, tzinfo=timezone.utc)


def _commit(
    warehouse: ResearchWarehouse,
    dataset: ResearchDatasetId,
    partition: str,
    records: list[dict],
    *,
    run_id: str,
    ingested_at: datetime = _INGESTED,
) -> None:
    warehouse.commit_batch(
        FactBatch(
            dataset_id=dataset,
            partition_value=partition,
            source_name="test",
            source_endpoint=dataset.value,
            ingestion_run_id=run_id,
            ingested_at=ingested_at,
            default_available_at=_BACKFILL,
            records=records,
        )
    )


def _commit_legacy_backdated(
    warehouse: ResearchWarehouse,
    dataset: ResearchDatasetId,
    partition: str,
    records: list[dict],
    *,
    run_id: str,
) -> None:
    contract = research_contract(dataset)
    policy = contract.availability_policy
    contract.availability_policy = AvailabilityPolicy.SOURCE_PUBLISHED
    try:
        _commit(
            warehouse,
            dataset,
            partition,
            records,
            run_id=run_id,
        )
    finally:
        contract.availability_policy = policy


def _seed_affected_warehouse(root) -> ResearchWarehouse:
    warehouse = ResearchWarehouse(root)
    _commit(
        warehouse,
        ResearchDatasetId.TRADE_CALENDAR,
        "2025",
        [
            {
                "exchange": "SSE",
                "cal_date": date(2025, 8, 15),
                "is_open": True,
                "available_at": _BACKFILL,
            },
            {
                "exchange": "SSE",
                "cal_date": date(2025, 8, 16),
                "is_open": False,
                "available_at": _BACKFILL,
            },
        ],
        run_id="calendar",
    )
    market_row = {
        "trade_date": date(2025, 8, 15),
        "open": 10.0,
        "high": 11.0,
        "low": 9.0,
        "close": 10.5,
        "available_at": _BACKFILL,
    }
    _commit(
        warehouse,
        ResearchDatasetId.INDUSTRY_DAILY,
        "2025-08-15",
        [{**market_row, "industry_code": "801010.SI"}],
        run_id="industry",
    )
    _commit(
        warehouse,
        ResearchDatasetId.THEME_DAILY,
        "2025-08-15",
        [{**market_row, "theme_code": "000019.SH"}],
        run_id="theme",
    )
    _commit_legacy_backdated(
        warehouse,
        ResearchDatasetId.SECURITY_MASTER,
        "security-master",
        [
            {
                "ts_code": "000001.SZ",
                "valid_from": date(1991, 4, 3),
                "name": "平安银行",
                "available_at": _BACKFILL,
            }
        ],
        run_id="security",
    )
    _commit_legacy_backdated(
        warehouse,
        ResearchDatasetId.COMPANY_PROFILE,
        "company-profile",
        [
            {
                "ts_code": "000001.SZ",
                "valid_from": date(2026, 7, 13),
                "introduction": "银行",
                "available_at": _BACKFILL,
            }
        ],
        run_id="company",
    )
    _commit_legacy_backdated(
        warehouse,
        ResearchDatasetId.PLEDGE,
        "2025-08",
        [
            {
                "ts_code": "000001.SZ",
                "end_date": date(2025, 8, 15),
                "pledge_ratio": 1.0,
                "available_at": _BACKFILL,
            }
        ],
        run_id="pledge",
    )
    first = datetime(2026, 3, 31, 16, tzinfo=timezone.utc)
    revised = datetime(2026, 4, 30, 16, tzinfo=timezone.utc)
    base = {
        "ts_code": "000001.SZ",
        "report_period": date(2025, 12, 31),
        "report_type": "1",
        "statement_type": "consolidated",
        "ann_date": date(2026, 3, 31),
        "revenue": 100.0,
        "available_at": first,
    }
    _commit(
        warehouse,
        ResearchDatasetId.INCOME_STATEMENT,
        "2025-12-31",
        [base],
        run_id="income-first",
        ingested_at=first,
    )
    _commit(
        warehouse,
        ResearchDatasetId.INCOME_STATEMENT,
        "2025-12-31",
        [{**base, "revenue": 101.0, "available_at": revised}],
        run_id="income-revised",
        ingested_at=revised,
    )
    announcement_time = datetime(2025, 8, 20, 3, 12, tzinfo=timezone.utc)
    _commit(
        warehouse,
        ResearchDatasetId.ANNOUNCEMENT,
        "2025-08",
        [
            {
                "announcement_id": "A1",
                "title": "公告",
                "available_at": announcement_time,
            }
        ],
        run_id="announcement",
        ingested_at=datetime(2026, 7, 14, tzinfo=timezone.utc),
    )
    return warehouse


def _current_identity(warehouse: ResearchWarehouse, dataset: ResearchDatasetId):
    frame = warehouse.read_current(dataset)
    return sorted(
        zip(
            frame["business_key_hash"].astype(str),
            frame["payload_hash"].astype(str),
            frame["revision_no"].astype(int),
            strict=True,
        )
    )


def test_temporal_migration_preserves_business_facts_and_revisions(tmp_path):
    warehouse = _seed_affected_warehouse(tmp_path / "warehouse")
    datasets = tuple(ResearchDatasetId)
    identities_before = {
        dataset: _current_identity(warehouse, dataset)
        for dataset in datasets
        if not warehouse.read_current(dataset).empty
    }
    partitions_before = {
        dataset: tuple(
            warehouse.partition_manifest(dataset)["partition_value"].astype(str)
        )
        for dataset in identities_before
    }
    revisions_before = warehouse.revision_rows(
        ResearchDatasetId.INCOME_STATEMENT
    )
    announcement_before = warehouse.read_current(
        ResearchDatasetId.ANNOUNCEMENT
    ).iloc[0]["available_at"]

    report = migrate_research_time_semantics(
        warehouse,
        migration_id="temporal-test-v1",
    )

    assert set(report.changed_datasets) == {
        "company_profile",
        "income_statement",
        "industry_daily",
        "pledge",
        "security_master",
        "theme_daily",
        "trade_calendar",
    }
    assert report.conservation_passed is True
    for dataset, identity in identities_before.items():
        assert _current_identity(warehouse, dataset) == identity
        assert tuple(
            warehouse.partition_manifest(dataset)["partition_value"].astype(str)
        ) == partitions_before[dataset]
    assert len(warehouse.revision_rows(ResearchDatasetId.INCOME_STATEMENT)) == len(
        revisions_before
    )
    assert warehouse.read_current(ResearchDatasetId.ANNOUNCEMENT).iloc[0][
        "available_at"
    ] == announcement_before

    calendar = warehouse.read_current(ResearchDatasetId.TRADE_CALENDAR)
    assert pd.to_datetime(calendar["available_at"], utc=True).dt.date.tolist() == [
        date(2025, 8, 15),
        date(2025, 8, 16),
    ]
    for dataset in (
        ResearchDatasetId.SECURITY_MASTER,
        ResearchDatasetId.COMPANY_PROFILE,
        ResearchDatasetId.PLEDGE,
    ):
        row = warehouse.read_current(dataset).iloc[0]
        assert row["available_at"] == row["ingested_at"]
        assert row["availability_precision"] == "ingestion_cutoff"
    income = warehouse.read_current(ResearchDatasetId.INCOME_STATEMENT)
    assert set(income["availability_precision"]) == {"date_conservative"}
    revision_payload = warehouse.revision_rows(
        ResearchDatasetId.INCOME_STATEMENT
    )[0]["row_payload"]
    assert revision_payload["availability_precision"] == "date_conservative"


def test_temporal_migration_rolls_back_files_when_metadata_update_fails(
    tmp_path, monkeypatch
):
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    _commit(
        warehouse,
        ResearchDatasetId.TRADE_CALENDAR,
        "2025",
        [
            {
                "exchange": "SSE",
                "cal_date": date(2025, 8, 15),
                "is_open": True,
                "available_at": _BACKFILL,
            }
        ],
        run_id="calendar",
    )
    path = warehouse.root / str(
        warehouse.partition_manifest(ResearchDatasetId.TRADE_CALENDAR).iloc[0][
            "relative_path"
        ]
    )
    before_sha = sha256_file(path)
    before_available = warehouse.read_current(
        ResearchDatasetId.TRADE_CALENDAR
    ).iloc[0]["available_at"]

    monkeypatch.setattr(
        migration_module,
        "_update_dataset_metadata",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("simulated metadata failure")
        ),
    )

    with pytest.raises(RuntimeError, match="simulated metadata failure"):
        migrate_research_time_semantics(
            warehouse,
            migration_id="temporal-rollback-v1",
        )

    assert sha256_file(path) == before_sha
    assert warehouse.read_current(ResearchDatasetId.TRADE_CALENDAR).iloc[0][
        "available_at"
    ] == before_available


def test_temporal_migration_is_idempotent_and_audit_covers_registry(tmp_path):
    warehouse = _seed_affected_warehouse(tmp_path / "warehouse")
    first = migrate_research_time_semantics(
        warehouse,
        migration_id="temporal-idempotent-v1",
    )
    manifests = {
        dataset: tuple(
            warehouse.partition_manifest(dataset)["file_sha256"].astype(str)
        )
        for dataset in ResearchDatasetId
    }

    second = migrate_research_time_semantics(
        warehouse,
        migration_id="temporal-idempotent-v1",
    )

    assert first.already_completed is False
    assert second.already_completed is True
    assert {
        dataset: tuple(
            warehouse.partition_manifest(dataset)["file_sha256"].astype(str)
        )
        for dataset in ResearchDatasetId
    } == manifests
    audit = audit_research_time_semantics(warehouse)
    assert len(audit) == len(ResearchDatasetId)
    assert {item.dataset_id for item in audit} == {
        dataset.value for dataset in ResearchDatasetId
    }
