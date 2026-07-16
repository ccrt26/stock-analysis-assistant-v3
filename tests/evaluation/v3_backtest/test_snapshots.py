from __future__ import annotations

import shutil
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

import stock_analyzer.evaluation.v3_backtest.snapshots as snapshots_module
from stock_analyzer.analysis.hotspot_features import HOTSPOT_FORMULA_VERSION
from stock_analyzer.analysis.market_context_features import (
    MARKET_CONTEXT_FORMULA_VERSION,
)
from stock_analyzer.analysis.stock_context_features import STOCK_CONTEXT_FORMULA_VERSION
from stock_analyzer.data.research_contracts import FactBatch, ResearchDatasetId
from stock_analyzer.evaluation.v3_backtest.snapshots import (
    formation_cutoff,
    materialize_formation_snapshot,
    tree_fingerprint,
)
from stock_analyzer.storage.research_derived import DerivedFeatureStore
from stock_analyzer.storage.research_query import ResearchQuery
from stock_analyzer.storage.research_warehouse import ResearchWarehouse


SHANGHAI = ZoneInfo("Asia/Shanghai")
ORIGIN = date(2025, 10, 30)
EMPTY_FACT_PLAN: dict[ResearchDatasetId, tuple[str, ...]] = {}
TEMPORAL_FACT_PLAN = {
    ResearchDatasetId.ANNOUNCEMENT: ("2025-10",),
    ResearchDatasetId.THEME_MEMBER: ("official-theme-v1",),
    ResearchDatasetId.COMPANY_PROFILE: ("company-profile",),
    ResearchDatasetId.PLEDGE: ("2025-10",),
    ResearchDatasetId.INCOME_STATEMENT: ("2025-09-30",),
}


@pytest.fixture
def temp_root():
    path = Path("/tmp") / f"v3-complete-backtest-{uuid4().hex}"
    yield path
    shutil.rmtree(path, ignore_errors=True)


def _warehouse(tmp_path: Path) -> ResearchWarehouse:
    warehouse = ResearchWarehouse(tmp_path / "source")
    warehouse.facts_root.mkdir(parents=True, exist_ok=True)
    return warehouse


def _feature_runner(
    *,
    row_counts: tuple[int, int, int] = (1, 1, 1),
    fact_hash_seed: str = "a",
    failures: tuple[str, ...] = (),
    errors: tuple[str, ...] = (),
):
    def run(warehouse, analysis_date, *, as_of):
        assert not hasattr(warehouse, "commit_batch")
        store = DerivedFeatureStore(warehouse.root)
        definitions = (
            (
                "market_context",
                MARKET_CONTEXT_FORMULA_VERSION,
                "analysis_date",
                pd.DataFrame({"analysis_date": [analysis_date] * row_counts[0]}),
            ),
            (
                "sector_hotspot",
                HOTSPOT_FORMULA_VERSION,
                ("analysis_date", "group_type", "group_code"),
                pd.DataFrame(
                    {
                        "analysis_date": [analysis_date] * row_counts[1],
                        "group_type": ["industry"] * row_counts[1],
                        "group_code": [f"G{index}" for index in range(row_counts[1])],
                    }
                ),
            ),
            (
                "stock_trading_context",
                STOCK_CONTEXT_FORMULA_VERSION,
                ("analysis_date", "ts_code"),
                pd.DataFrame(
                    {
                        "analysis_date": [analysis_date] * row_counts[2],
                        "ts_code": [f"{index:06d}.SZ" for index in range(row_counts[2])],
                    }
                ),
            ),
        )
        if not failures and not errors:
            for index, (feature_set, formula_version, entity_key, frame) in enumerate(
                definitions
            ):
                store.commit(
                    feature_set,
                    analysis_date,
                    formula_version,
                    frame,
                    input_manifest={
                        "fact_snapshot": {
                            "as_of": as_of.astimezone(timezone.utc).isoformat(),
                            "input_manifest_hash": fact_hash_seed * 64,
                        }
                    },
                    entity_key=entity_key,
                    quality_status="complete",
                    run_id=f"test:{feature_set}:{analysis_date.isoformat()}:{index}",
                )
        return SimpleNamespace(
            failed_feature_sets=failures,
            errors=errors,
            market_rows=row_counts[0],
            sector_rows=row_counts[1],
            stock_rows=row_counts[2],
            limitations=("known historical limitation",),
        )

    return run


def _commit(
    warehouse: ResearchWarehouse,
    dataset: ResearchDatasetId,
    partition: str,
    records: list[dict],
    *,
    ingested_at: datetime,
) -> None:
    warehouse.commit_batch(
        FactBatch(
            dataset_id=dataset,
            partition_value=partition,
            source_name="test",
            source_endpoint=dataset.value,
            ingestion_run_id=f"test:{dataset.value}:{partition}:{ingested_at.isoformat()}",
            ingested_at=ingested_at,
            default_available_at=ingested_at,
            records=records,
        )
    )


def _seed_temporal_facts(warehouse: ResearchWarehouse) -> None:
    before = datetime(2025, 10, 29, 12, tzinfo=SHANGHAI)
    after = datetime(2025, 11, 1, 12, tzinfo=SHANGHAI)
    _commit(
        warehouse,
        ResearchDatasetId.ANNOUNCEMENT,
        "2025-10",
        [
            {
                "announcement_id": "A1",
                "title": "formation-time title",
                "available_at": before,
            }
        ],
        ingested_at=before,
    )
    _commit(
        warehouse,
        ResearchDatasetId.ANNOUNCEMENT,
        "2025-10",
        [
            {
                "announcement_id": "A1",
                "title": "future revision",
                "available_at": after,
            }
        ],
        ingested_at=after,
    )
    _commit(
        warehouse,
        ResearchDatasetId.THEME_MEMBER,
        "official-theme-v1",
        [
            {
                "theme_code": "T1",
                "ts_code": "000001.SZ",
                "valid_from": date(2020, 1, 1),
                "valid_to": date(2025, 12, 31),
            },
            {
                "theme_code": "T1",
                "ts_code": "000002.SZ",
                "valid_from": date(2025, 11, 1),
                "valid_to": None,
            },
            {
                "theme_code": "T1",
                "ts_code": "000003.SZ",
                "valid_from": date(2020, 1, 1),
                "valid_to": date(2025, 10, 1),
            },
        ],
        ingested_at=before,
    )
    _commit(
        warehouse,
        ResearchDatasetId.COMPANY_PROFILE,
        "company-profile",
        [{"ts_code": "000001.SZ", "valid_from": date(1991, 4, 3)}],
        ingested_at=after,
    )
    _commit(
        warehouse,
        ResearchDatasetId.INCOME_STATEMENT,
        "2025-09-30",
        [
            {
                "ts_code": "000001.SZ",
                "report_period": date(2025, 9, 30),
                "report_type": "1",
                "statement_type": "consolidated",
                "revenue": 100.0,
                "available_at": before,
            }
        ],
        ingested_at=before,
    )
    _commit(
        warehouse,
        ResearchDatasetId.INCOME_STATEMENT,
        "2025-09-30",
        [
            {
                "ts_code": "000001.SZ",
                "report_period": date(2025, 9, 30),
                "report_type": "1",
                "statement_type": "consolidated",
                "revenue": 200.0,
                "available_at": after,
            }
        ],
        ingested_at=after,
    )
    _commit(
        warehouse,
        ResearchDatasetId.PLEDGE,
        "2025-10",
        [{"ts_code": "000001.SZ", "end_date": date(2025, 10, 1)}],
        ingested_at=after,
    )


def test_formation_cutoff_is_end_of_origin_day_in_shanghai():
    cutoff = formation_cutoff(ORIGIN)

    assert cutoff.isoformat() == "2025-10-30T23:59:59+08:00"


def test_tree_fingerprint_hashes_a_single_database_file(tmp_path: Path):
    database = tmp_path / "research.duckdb"
    database.write_bytes(b"one")
    first = tree_fingerprint(database)

    database.write_bytes(b"two")

    assert tree_fingerprint(database) != first


def test_temp_root_must_use_frozen_tmp_prefix_and_be_separate_from_source(
    tmp_path: Path,
):
    warehouse = _warehouse(tmp_path)

    with pytest.raises(ValueError, match="/tmp/v3-complete-backtest"):
        materialize_formation_snapshot(
            warehouse,
            ORIGIN,
            tmp_path / "ordinary-temp",
            fact_plan=EMPTY_FACT_PLAN,
            feature_runner=_feature_runner(),
        )
    with pytest.raises(ValueError, match="separate from source"):
        materialize_formation_snapshot(
            warehouse,
            ORIGIN,
            warehouse.root / "v3-complete-backtest-nested",
            fact_plan=EMPTY_FACT_PLAN,
            feature_runner=_feature_runner(),
        )


def test_snapshot_exposes_fixed_cutoff_fact_and_feature_views_not_internal_root(
    tmp_path: Path,
    temp_root: Path,
):
    warehouse = _warehouse(tmp_path)
    _seed_temporal_facts(warehouse)

    snapshot = materialize_formation_snapshot(
        warehouse,
        ORIGIN,
        temp_root,
        fact_plan=TEMPORAL_FACT_PLAN,
        feature_runner=_feature_runner(),
    )

    announcements = snapshot.facts.dataset(ResearchDatasetId.ANNOUNCEMENT)
    members = snapshot.facts.dataset(ResearchDatasetId.THEME_MEMBER)
    financials = snapshot.facts.dataset(ResearchDatasetId.INCOME_STATEMENT)
    assert announcements["title"].tolist() == ["formation-time title"]
    assert members["ts_code"].tolist() == ["000001.SZ"]
    assert pd.isna(members.iloc[0]["valid_to"])
    assert financials["revenue"].tolist() == [100.0]
    assert snapshot.facts.dataset(ResearchDatasetId.COMPANY_PROFILE).empty
    assert snapshot.facts.dataset(ResearchDatasetId.PLEDGE).empty
    assert len(snapshot.features.read("stock_trading_context")) == 1
    assert not hasattr(snapshot, "isolated_root")
    assert not hasattr(snapshot.facts, "root")
    assert not any(
        token in attribute.lower()
        for attribute in dir(snapshot.facts)
        for token in ("query", "warehouse", "root", "store")
    )
    assert not any(
        token in attribute.lower()
        for attribute in dir(snapshot.features)
        for token in ("query", "warehouse", "root", "store")
    )

    shutil.rmtree(temp_root)
    assert snapshot.facts.dataset(ResearchDatasetId.ANNOUNCEMENT)["title"].tolist() == [
        "formation-time title"
    ]
    assert len(snapshot.features.read("stock_trading_context")) == 1


def test_snapshot_keeps_relationship_whose_future_valid_to_is_masked_as_open(
    tmp_path: Path,
    temp_root: Path,
):
    warehouse = _warehouse(tmp_path)
    known_at = datetime(2025, 10, 29, 12, tzinfo=SHANGHAI)
    _commit(
        warehouse,
        ResearchDatasetId.THEME_MEMBER,
        "official-theme-v1",
        [
            {
                "theme_code": "T1",
                "ts_code": "000001.SZ",
                "valid_from": date(2020, 1, 1),
                "valid_to": date(2025, 12, 31),
            }
        ],
        ingested_at=known_at,
    )

    query_frame = ResearchQuery(warehouse).dataset_partitions_as_of(
        ResearchDatasetId.THEME_MEMBER,
        ("official-theme-v1",),
        formation_cutoff(ORIGIN),
    )
    assert pd.isna(query_frame.iloc[0]["valid_to"])

    snapshot = materialize_formation_snapshot(
        warehouse,
        ORIGIN,
        temp_root,
        fact_plan={
            ResearchDatasetId.THEME_MEMBER: ("official-theme-v1",),
        },
        feature_runner=_feature_runner(),
    )

    members = snapshot.facts.dataset(ResearchDatasetId.THEME_MEMBER)
    assert members["ts_code"].tolist() == ["000001.SZ"]
    assert pd.isna(members.iloc[0]["valid_to"])


def test_materialization_does_not_mutate_any_source_warehouse_tree(
    tmp_path: Path,
    temp_root: Path,
):
    warehouse = _warehouse(tmp_path)
    _seed_temporal_facts(warehouse)
    before = {
        "facts": tree_fingerprint(warehouse.facts_root),
        "derived": tree_fingerprint(warehouse.root / "derived"),
        "database": tree_fingerprint(warehouse.duckdb_path),
    }

    snapshot = materialize_formation_snapshot(
        warehouse,
        ORIGIN,
        temp_root,
        fact_plan=TEMPORAL_FACT_PLAN,
        feature_runner=_feature_runner(),
    )
    snapshot.facts.dataset(ResearchDatasetId.ANNOUNCEMENT)

    assert tree_fingerprint(warehouse.facts_root) == before["facts"]
    assert tree_fingerprint(warehouse.root / "derived") == before["derived"]
    assert tree_fingerprint(warehouse.duckdb_path) == before["database"]


def test_malicious_feature_runner_can_only_write_the_cloned_facts_tree(
    tmp_path: Path,
    temp_root: Path,
):
    warehouse = _warehouse(tmp_path)
    source_before = tree_fingerprint(warehouse.facts_root)
    successful_runner = _feature_runner()

    def writes_facts(warehouse_view, analysis_date, *, as_of):
        (warehouse_view.root / "facts" / "runner-write.txt").write_text(
            "isolated",
            encoding="utf-8",
        )
        return successful_runner(warehouse_view, analysis_date, as_of=as_of)

    materialize_formation_snapshot(
        warehouse,
        ORIGIN,
        temp_root,
        fact_plan=EMPTY_FACT_PLAN,
        feature_runner=writes_facts,
    )

    assert not (temp_root / "facts").is_symlink()
    assert (temp_root / "facts" / "runner-write.txt").read_text(encoding="utf-8") == (
        "isolated"
    )
    assert not (warehouse.facts_root / "runner-write.txt").exists()
    assert tree_fingerprint(warehouse.facts_root) == source_before


def test_clone_failure_fails_closed_cleans_partial_root_and_preserves_source(
    tmp_path: Path,
    temp_root: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    warehouse = _warehouse(tmp_path)
    before = tree_fingerprint(warehouse.root)
    monkeypatch.setattr(
        snapshots_module.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1),
    )

    def fail_copy(*args, **kwargs):
        raise OSError("copy failed")

    monkeypatch.setattr(snapshots_module.shutil, "copy2", fail_copy)

    with pytest.raises(OSError, match="copy failed"):
        materialize_formation_snapshot(
            warehouse,
            ORIGIN,
            temp_root,
            fact_plan=EMPTY_FACT_PLAN,
            feature_runner=_feature_runner(),
        )

    assert not temp_root.exists()
    assert tree_fingerprint(warehouse.root) == before


def test_feature_failure_fails_closed_and_cleans_partial_root(
    tmp_path: Path,
    temp_root: Path,
):
    warehouse = _warehouse(tmp_path)

    with pytest.raises(RuntimeError, match="sector_hotspot.*future evidence"):
        materialize_formation_snapshot(
            warehouse,
            ORIGIN,
            temp_root,
            fact_plan=EMPTY_FACT_PLAN,
            feature_runner=_feature_runner(
                failures=("sector_hotspot",),
                errors=("future evidence",),
            ),
        )

    assert not temp_root.exists()


@pytest.mark.parametrize("row_counts", [(0, 1, 1), (1, 0, 1), (1, 1, 0)])
def test_any_empty_core_feature_fails_closed(
    tmp_path: Path,
    temp_root: Path,
    row_counts: tuple[int, int, int],
):
    warehouse = _warehouse(tmp_path)

    with pytest.raises(RuntimeError, match="core feature output is empty"):
        materialize_formation_snapshot(
            warehouse,
            ORIGIN,
            temp_root,
            fact_plan=EMPTY_FACT_PLAN,
            feature_runner=_feature_runner(row_counts=row_counts),
        )

    assert not temp_root.exists()


def test_cache_key_binds_origin_cutoff_fact_manifests_and_formula_versions(
    tmp_path: Path,
):
    warehouse = _warehouse(tmp_path)
    roots = [
        Path("/tmp") / f"v3-complete-backtest-{uuid4().hex}" for _ in range(3)
    ]
    try:
        first = materialize_formation_snapshot(
            warehouse,
            ORIGIN,
            roots[0],
            fact_plan=EMPTY_FACT_PLAN,
            feature_runner=_feature_runner(fact_hash_seed="a"),
        )
        identical = materialize_formation_snapshot(
            warehouse,
            ORIGIN,
            roots[1],
            fact_plan=EMPTY_FACT_PLAN,
            feature_runner=_feature_runner(fact_hash_seed="a"),
        )
        changed_facts = materialize_formation_snapshot(
            warehouse,
            ORIGIN,
            roots[2],
            fact_plan=EMPTY_FACT_PLAN,
            feature_runner=_feature_runner(fact_hash_seed="b"),
        )
    finally:
        for root in roots:
            shutil.rmtree(root, ignore_errors=True)

    assert first.cache_key == identical.cache_key
    assert first.cache_key != changed_facts.cache_key
    assert dict(first.formula_versions) == {
        "market_context": MARKET_CONTEXT_FORMULA_VERSION,
        "sector_hotspot": HOTSPOT_FORMULA_VERSION,
        "stock_trading_context": STOCK_CONTEXT_FORMULA_VERSION,
    }
    assert dict(first.fact_manifest_hashes) == {
        "market_context": "a" * 64,
        "sector_hotspot": "a" * 64,
        "stock_trading_context": "a" * 64,
    }
    assert first.limitations == ("known historical limitation",)


def test_initialized_temp_root_is_reused_across_dates_without_recloning(
    tmp_path: Path,
    temp_root: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    warehouse = _warehouse(tmp_path)
    source_before = tree_fingerprint(warehouse.root)
    first = materialize_formation_snapshot(
        warehouse,
        ORIGIN,
        temp_root,
        fact_plan=EMPTY_FACT_PLAN,
        feature_runner=_feature_runner(fact_hash_seed="a"),
    )

    def clone_must_not_run(*args, **kwargs):
        pytest.fail("an initialized temp root must not clone the warehouse again")

    monkeypatch.setattr(snapshots_module, "_clone_path", clone_must_not_run)
    second = materialize_formation_snapshot(
        warehouse,
        date(2025, 10, 31),
        temp_root,
        fact_plan=EMPTY_FACT_PLAN,
        feature_runner=_feature_runner(fact_hash_seed="b"),
    )

    assert first.cache_key != second.cache_key
    assert len(first.features.read("stock_trading_context")) == 1
    assert len(second.features.read("stock_trading_context")) == 1
    assert tree_fingerprint(warehouse.root) == source_before


def test_nonempty_uninitialized_temp_root_is_rejected_without_deletion(
    tmp_path: Path,
    temp_root: Path,
):
    warehouse = _warehouse(tmp_path)
    temp_root.mkdir(parents=True)
    sentinel = temp_root / "unrelated.txt"
    sentinel.write_text("keep", encoding="utf-8")

    with pytest.raises(ValueError, match="not initialized by v3 snapshot module"):
        materialize_formation_snapshot(
            warehouse,
            ORIGIN,
            temp_root,
            fact_plan=EMPTY_FACT_PLAN,
            feature_runner=_feature_runner(),
        )

    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_initialized_temp_root_rejects_a_different_source_identity(
    tmp_path: Path,
    temp_root: Path,
):
    first_warehouse = _warehouse(tmp_path / "first")
    second_warehouse = _warehouse(tmp_path / "second")
    materialize_formation_snapshot(
        first_warehouse,
        ORIGIN,
        temp_root,
        fact_plan=EMPTY_FACT_PLAN,
        feature_runner=_feature_runner(),
    )
    root_before = tree_fingerprint(temp_root)

    with pytest.raises(ValueError, match="source identity mismatch"):
        materialize_formation_snapshot(
            second_warehouse,
            date(2025, 10, 31),
            temp_root,
            fact_plan=EMPTY_FACT_PLAN,
            feature_runner=_feature_runner(),
        )

    assert tree_fingerprint(temp_root) == root_before


def test_failed_date_cleanup_preserves_prior_dates_in_reused_root(
    tmp_path: Path,
    temp_root: Path,
):
    warehouse = _warehouse(tmp_path)
    first = materialize_formation_snapshot(
        warehouse,
        ORIGIN,
        temp_root,
        fact_plan=EMPTY_FACT_PLAN,
        feature_runner=_feature_runner(),
    )
    successful_runner = _feature_runner(fact_hash_seed="b")

    def commits_then_fails(warehouse_view, analysis_date, *, as_of):
        summary = successful_runner(warehouse_view, analysis_date, as_of=as_of)
        summary.failed_feature_sets = ("stock_trading_context",)
        summary.errors = ("forced failure after partial commits",)
        return summary

    failed_date = date(2025, 10, 31)
    with pytest.raises(RuntimeError, match="forced failure after partial commits"):
        materialize_formation_snapshot(
            warehouse,
            failed_date,
            temp_root,
            fact_plan=EMPTY_FACT_PLAN,
            feature_runner=commits_then_fails,
        )

    store = DerivedFeatureStore(temp_root)
    assert len(first.features.read("market_context")) == 1
    assert store.partition_manifest(analysis_date=failed_date).empty
    assert temp_root.exists()


def test_existing_successful_origin_is_read_only_and_never_reruns_features(
    tmp_path: Path,
    temp_root: Path,
):
    warehouse = _warehouse(tmp_path)
    first = materialize_formation_snapshot(
        warehouse,
        ORIGIN,
        temp_root,
        fact_plan=EMPTY_FACT_PLAN,
        feature_runner=_feature_runner(),
    )

    def must_not_run(*args, **kwargs):
        raise AssertionError("an existing successful origin must not be recomputed")

    repeated = materialize_formation_snapshot(
        warehouse,
        ORIGIN,
        temp_root,
        fact_plan=EMPTY_FACT_PLAN,
        feature_runner=must_not_run,
    )

    assert repeated.cache_key == first.cache_key
    assert len(repeated.features.read("market_context")) == 1
    assert len(first.features.read("market_context")) == 1
