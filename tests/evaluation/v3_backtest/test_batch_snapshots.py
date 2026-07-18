from __future__ import annotations

import importlib
import json
import os
import shutil
import time
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from stock_analyzer.data.research_contracts import FactBatch, ResearchDatasetId
from stock_analyzer.evaluation.v3_backtest.snapshots import (
    FormationFeatureView,
    tree_fingerprint,
)
from stock_analyzer.storage.research_warehouse import ResearchWarehouse
from stock_analyzer.storage.research_query import ResearchQuery


SHANGHAI = ZoneInfo("Asia/Shanghai")
ORIGIN = date(2025, 10, 30)
NEXT_ORIGIN = date(2025, 10, 31)
FACT_PLAN = {
    ResearchDatasetId.ANNOUNCEMENT: ("2025-10",),
    ResearchDatasetId.THEME_MEMBER: ("official-theme-v1",),
}


def _batch_module():
    return importlib.import_module(
        "stock_analyzer.evaluation.v3_backtest.batch_snapshots"
    )


def _warehouse(tmp_path: Path) -> ResearchWarehouse:
    warehouse = ResearchWarehouse(tmp_path / "source")
    warehouse.facts_root.mkdir(parents=True, exist_ok=True)
    return warehouse


def _commit(
    warehouse: ResearchWarehouse,
    dataset: ResearchDatasetId,
    partition: str,
    records: list[dict[str, Any]],
    *,
    ingested_at: datetime,
) -> None:
    warehouse.commit_batch(
        FactBatch(
            dataset_id=dataset,
            partition_value=partition,
            source_name="test",
            source_endpoint=dataset.value,
            ingestion_run_id=(
                f"test:{dataset.value}:{partition}:{ingested_at.isoformat()}"
            ),
            ingested_at=ingested_at,
            default_available_at=ingested_at,
            records=records,
        )
    )


def _seed_time_boundaries(warehouse: ResearchWarehouse) -> None:
    cutoff = datetime(2025, 10, 30, 23, 59, 59, tzinfo=SHANGHAI)
    _commit(
        warehouse,
        ResearchDatasetId.ANNOUNCEMENT,
        "2025-10",
        [
            {
                "announcement_id": "A1",
                "title": "visible exactly at cutoff",
                "available_at": cutoff,
            }
        ],
        ingested_at=cutoff,
    )
    _commit(
        warehouse,
        ResearchDatasetId.ANNOUNCEMENT,
        "2025-10",
        [
            {
                "announcement_id": "A1",
                "title": "future revision by one microsecond",
                "available_at": cutoff + timedelta(microseconds=1),
            }
        ],
        ingested_at=cutoff + timedelta(microseconds=1),
    )
    known_before = datetime(2025, 10, 29, 9, tzinfo=SHANGHAI)
    _commit(
        warehouse,
        ResearchDatasetId.THEME_MEMBER,
        "official-theme-v1",
        [
            {
                "theme_code": "T1",
                "ts_code": "000001.SZ",
                "valid_from": ORIGIN,
                "valid_to": None,
            },
            {
                "theme_code": "T1",
                "ts_code": "000002.SZ",
                "valid_from": NEXT_ORIGIN,
                "valid_to": None,
            },
        ],
        ingested_at=known_before,
    )


def _feature_builder(batch, *, value: float = 1.0, duplicate_stock=False):
    def build(query, origin, cutoff):
        fact_snapshot = query.materialize_snapshot(FACT_PLAN, as_of=cutoff)
        stock_codes = ["000001.SZ", "000001.SZ"] if duplicate_stock else [
            "000001.SZ",
            "000002.SZ",
        ]
        return batch.BatchFeatureResult(
            frames={
                "market_context": pd.DataFrame(
                    {
                        "analysis_date": [origin],
                        "formula_version": ["market-context-v-test"],
                        "coverage_status": ["complete"],
                    }
                ),
                "sector_hotspot": pd.DataFrame(
                    {
                        "analysis_date": [origin],
                        "group_type": ["theme"],
                        "group_code": ["T1"],
                        "formula_version": ["hotspot-v-test"],
                        "coverage_status": ["complete"],
                    }
                ),
                "stock_trading_context": pd.DataFrame(
                    {
                        "analysis_date": [origin, origin],
                        "ts_code": stock_codes,
                        "formula_version": ["stock-context-v-test"] * 2,
                        "coverage_status": ["complete", "complete"],
                        "exact_metric": [value, np.nan],
                        "all_null_integer": pd.Series(
                            [pd.NA, pd.NA], dtype="Int64"
                        ),
                    }
                ),
            },
            fact_manifest_hashes={
                feature_set: fact_snapshot.input_manifest["input_manifest_hash"]
                for feature_set in (
                    "market_context",
                    "sector_hotspot",
                    "stock_trading_context",
                )
            },
            formula_versions={
                "market_context": "market-context-v-test",
                "sector_hotspot": "hotspot-v-test",
                "stock_trading_context": "stock-context-v-test",
            },
            limitations=("synthetic fixture",),
        )

    return build


def _configured_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    batch = _batch_module()
    warehouse = _warehouse(tmp_path)
    _seed_time_boundaries(warehouse)
    output_root = tmp_path / "backtest-root"
    monkeypatch.setenv("V3_BACKTEST_ROOT", str(output_root))
    store = batch.BatchSnapshotStore(
        warehouse,
        fact_plan=FACT_PLAN,
        feature_builder=_feature_builder(batch),
    )
    return batch, warehouse, output_root, store


def test_prepare_keeps_cutoff_and_effective_date_boundaries_isolated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    batch, warehouse, output_root, store = _configured_store(tmp_path, monkeypatch)
    source_before = tree_fingerprint(warehouse.root)
    read_calls: dict[ResearchDatasetId, int] = {}
    original_read = warehouse.read_current_partitions_with_manifest

    def counted_read(dataset, partitions):
        dataset_id = ResearchDatasetId(dataset)
        read_calls[dataset_id] = read_calls.get(dataset_id, 0) + 1
        return original_read(dataset_id, partitions)

    warehouse.read_current_partitions_with_manifest = counted_read
    receipt = store.prepare((ORIGIN, NEXT_ORIGIN), output_root)

    later = store.snapshot(NEXT_ORIGIN)
    earlier = store.snapshot(ORIGIN)
    assert earlier.facts.dataset(ResearchDatasetId.ANNOUNCEMENT)["title"].tolist() == [
        "visible exactly at cutoff"
    ]
    assert later.facts.dataset(ResearchDatasetId.ANNOUNCEMENT)["title"].tolist() == [
        "future revision by one microsecond"
    ]
    assert earlier.facts.dataset(ResearchDatasetId.THEME_MEMBER)["ts_code"].tolist() == [
        "000001.SZ"
    ]
    assert later.facts.dataset(ResearchDatasetId.THEME_MEMBER)["ts_code"].tolist() == [
        "000001.SZ",
        "000002.SZ",
    ]
    assert receipt.operational_dates == (ORIGIN, NEXT_ORIGIN)
    assert read_calls == {
        ResearchDatasetId.ANNOUNCEMENT: 1,
        ResearchDatasetId.THEME_MEMBER: 1,
    }
    assert tree_fingerprint(warehouse.root) == source_before
    assert not any(path.name.startswith(".partial-") for path in output_root.rglob("*"))


def test_snapshot_interface_fails_closed_before_prepare_and_for_unknown_origin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    _, _, output_root, store = _configured_store(tmp_path, monkeypatch)

    with pytest.raises(RuntimeError, match="prepare"):
        store.snapshot(ORIGIN)
    with pytest.raises(ValueError, match="operational_dates"):
        store.prepare((), output_root)

    store.prepare((ORIGIN,), output_root)
    with pytest.raises(KeyError, match="not prepared"):
        store.snapshot(NEXT_ORIGIN)


def test_prepare_rejects_any_output_outside_frozen_backtest_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    _, _, _, store = _configured_store(tmp_path, monkeypatch)

    with pytest.raises(ValueError, match="V3_BACKTEST_ROOT"):
        store.prepare((ORIGIN,), tmp_path / "outside")


def test_compare_snapshot_exact_uses_arrow_values_without_float_tolerance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    batch, _, output_root, store = _configured_store(tmp_path, monkeypatch)
    store.prepare((ORIGIN,), output_root)
    reference = store.snapshot(ORIGIN)

    identical = batch.compare_snapshot_exact(reference, reference)
    assert identical.exact_equal is True
    assert identical.mismatches == ()

    feature_frames = {
        feature_set: reference.features.read(feature_set)
        for feature_set in (
            "market_context",
            "sector_hotspot",
            "stock_trading_context",
        )
    }
    feature_frames["stock_trading_context"].loc[0, "exact_metric"] = np.nextafter(
        1.0, 2.0
    )
    changed = replace(reference, features=FormationFeatureView(feature_frames))
    parity = batch.compare_snapshot_exact(reference, changed)

    assert parity.exact_equal is False
    assert "feature:stock_trading_context:content_hash" in parity.mismatches


def test_compare_snapshot_exact_normalizes_nulls_but_not_column_order_or_manifests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    batch, _, output_root, store = _configured_store(tmp_path, monkeypatch)
    store.prepare((ORIGIN,), output_root)
    reference = store.snapshot(ORIGIN)
    frames = {
        feature_set: reference.features.read(feature_set)
        for feature_set in (
            "market_context",
            "sector_hotspot",
            "stock_trading_context",
        )
    }
    frames["stock_trading_context"] = frames["stock_trading_context"].astype(
        {"exact_metric": object}
    )
    frames["stock_trading_context"].loc[1, "exact_metric"] = None
    null_variant = replace(reference, features=FormationFeatureView(frames))
    assert batch.compare_snapshot_exact(reference, null_variant).exact_equal is True

    frames["market_context"] = frames["market_context"][
        list(reversed(frames["market_context"].columns))
    ]
    reordered = replace(reference, features=FormationFeatureView(frames))
    reordered_parity = batch.compare_snapshot_exact(reference, reordered)
    assert reordered_parity.exact_equal is False
    assert "feature:market_context:column_order" in reordered_parity.mismatches

    changed_manifest = replace(
        reference,
        fact_manifest_hashes=(
            ("market_context", "f" * 64),
            *reference.fact_manifest_hashes[1:],
        ),
    )
    manifest_parity = batch.compare_snapshot_exact(reference, changed_manifest)
    assert manifest_parity.exact_equal is False
    assert "fact_manifest_hashes" in manifest_parity.mismatches


def test_content_addressed_snapshot_is_atomic_deduplicated_and_key_validated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    batch, warehouse, output_root, store = _configured_store(tmp_path, monkeypatch)
    first = store.prepare((ORIGIN,), output_root)
    second = store.prepare((ORIGIN,), output_root)

    assert first.content_hashes == second.content_hashes
    assert getattr(store, "_snapshots", {}) == {}
    assert store.snapshot(ORIGIN).analysis_date == ORIGIN
    content_hash = dict(first.content_hashes)[ORIGIN.isoformat()]
    content_root = output_root / "cache" / "snapshots" / content_hash
    date_manifest = json.loads(
        (output_root / "cache" / "snapshots" / "by-date" / f"{ORIGIN}.json").read_text(
            encoding="utf-8"
        )
    )
    assert date_manifest["content_hash"] == content_hash
    assert (content_root / "manifest.json").is_file()
    content_manifest = json.loads(
        (content_root / "manifest.json").read_text(encoding="utf-8")
    )
    stock_file = next(
        item["name"]
        for item in content_manifest["files"]
        if item["table"] == "feature:stock_trading_context"
    )
    assert batch._arrow_ipc_bytes(
        store.snapshot(ORIGIN).features.read("stock_trading_context")
    ) == (content_root / stock_file).read_bytes()
    assert all(path.stat().st_size <= batch.MAX_CACHE_FILE_BYTES for path in content_root.iterdir())
    assert len(
        [
            path
            for path in (output_root / "cache" / "snapshots").iterdir()
            if len(path.name) == 64
        ]
    ) == 1

    broken = batch.BatchSnapshotStore(
        warehouse,
        fact_plan=FACT_PLAN,
        feature_builder=_feature_builder(batch, duplicate_stock=True),
    )
    with pytest.raises(ValueError, match="duplicate business key"):
        broken.prepare((NEXT_ORIGIN,), output_root)
    assert not any(path.name.startswith(".partial-") for path in output_root.rglob("*"))


def test_repeated_prepare_revalidates_content_addressed_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    _, _, output_root, store = _configured_store(tmp_path, monkeypatch)
    receipt = store.prepare((ORIGIN,), output_root)
    content_hash = dict(receipt.content_hashes)[ORIGIN.isoformat()]
    manifest = json.loads(
        (
            output_root
            / "cache"
            / "snapshots"
            / content_hash
            / "manifest.json"
        ).read_text(encoding="utf-8")
    )
    damaged = output_root / "cache" / "snapshots" / content_hash / manifest["files"][0]["name"]
    damaged.write_bytes(b"damaged")

    with pytest.raises(ValueError, match="snapshot file"):
        store.prepare((ORIGIN,), output_root)


def test_fresh_store_rejects_tampered_content_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    batch, warehouse, output_root, store = _configured_store(tmp_path, monkeypatch)
    receipt = store.prepare((ORIGIN,), output_root)
    content_hash = dict(receipt.content_hashes)[ORIGIN.isoformat()]
    manifest_path = (
        output_root
        / "cache"
        / "snapshots"
        / content_hash
        / "manifest.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["limitations"] = ["tampered after content addressing"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    fresh = batch.BatchSnapshotStore(
        warehouse,
        fact_plan=FACT_PLAN,
        feature_builder=_feature_builder(batch),
    )
    with pytest.raises(ValueError, match="identity hash"):
        fresh.prepare((ORIGIN,), output_root)


def test_canonical_ipc_ignores_hidden_payload_of_null_integer_slots():
    batch = _batch_module()
    mask = np.array([True, True], dtype=bool)
    zero_payload = pd.Series(
        pd.arrays.IntegerArray(np.array([0, 0], dtype=np.int64), mask)
    )
    one_payload = pd.Series(
        pd.arrays.IntegerArray(np.array([1, 1], dtype=np.int64), mask)
    )

    assert zero_payload.equals(one_payload)
    assert batch._arrow_ipc_bytes(
        pd.DataFrame({"all_null_integer": zero_payload})
    ) == batch._arrow_ipc_bytes(
        pd.DataFrame({"all_null_integer": one_payload})
    )


def test_equivalence_gate_writes_receipt_only_when_every_origin_is_exact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    batch, _, output_root, store = _configured_store(tmp_path, monkeypatch)
    store.prepare((ORIGIN,), output_root)
    snapshot = store.snapshot(ORIGIN)
    exact = batch.compare_snapshot_exact(snapshot, snapshot)

    receipt_path = batch.persist_equivalence_gate((exact,), output_root)
    assert receipt_path == output_root / "preflight" / "equivalence-receipt.json"
    assert json.loads(receipt_path.read_text(encoding="utf-8"))["exact_equal"] is True

    mismatch = replace(exact, exact_equal=False, mismatches=("forced",))
    with pytest.raises(RuntimeError, match="exact snapshot equivalence"):
        batch.persist_equivalence_gate((mismatch,), output_root)
    assert not receipt_path.exists()
    assert (
        output_root
        / "preflight"
        / "equivalence-diff"
        / f"{ORIGIN.isoformat()}.json"
    ).is_file()

    batch.persist_equivalence_gate((exact,), output_root)
    assert not (output_root / "preflight" / "equivalence-diff").exists()


def test_union_preload_restores_requested_partition_schema_and_column_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    batch = _batch_module()
    warehouse = _warehouse(tmp_path)
    known = datetime(2025, 9, 30, 12, tzinfo=SHANGHAI)
    _commit(
        warehouse,
        ResearchDatasetId.ANNOUNCEMENT,
        "2025-09",
        [
            {
                "announcement_id": "SEP",
                "title": "older physical schema",
                "availability_limitation": None,
                "available_at": known,
            }
        ],
        ingested_at=known,
    )
    _commit(
        warehouse,
        ResearchDatasetId.ANNOUNCEMENT,
        "2025-10",
        [
            {
                "announcement_id": "OCT",
                "title": "newer physical schema",
                "available_at": known,
            }
        ],
        ingested_at=known,
    )
    plans = {
        ORIGIN: {
            ResearchDatasetId.ANNOUNCEMENT: ("2025-09",),
            ResearchDatasetId.THEME_MEMBER: ("official-theme-v1",),
        },
        NEXT_ORIGIN: {
            ResearchDatasetId.ANNOUNCEMENT: ("2025-10",),
            ResearchDatasetId.THEME_MEMBER: ("official-theme-v1",),
        },
    }

    def build(query, origin, cutoff):
        fact_snapshot = query.materialize_snapshot(plans[origin], as_of=cutoff)
        synthetic = _feature_builder(batch)
        # The fixture builder only needs the fact hash; expose the same plan it
        # would have queried while keeping the three deterministic test frames.
        result = synthetic(query, origin, cutoff)
        return replace(
            result,
            fact_manifest_hashes={
                name: fact_snapshot.input_manifest["input_manifest_hash"]
                for name in result.frames
            },
        )

    # The shared fixture builder queries FACT_PLAN, so load those partitions as
    # well; only the public fact plan varies and is asserted below.
    _seed_time_boundaries(warehouse)
    output_root = tmp_path / "backtest-schema-root"
    monkeypatch.setenv("V3_BACKTEST_ROOT", str(output_root))
    store = batch.BatchSnapshotStore(
        warehouse,
        fact_plan=lambda origin: plans[origin],
        feature_builder=build,
    )
    store.prepare((ORIGIN, NEXT_ORIGIN), output_root)

    strict = ResearchQuery(warehouse).materialize_snapshot(
        plans[NEXT_ORIGIN], as_of=batch.formation_cutoff(NEXT_ORIGIN)
    ).frame(ResearchDatasetId.ANNOUNCEMENT)
    candidate = store.snapshot(NEXT_ORIGIN).facts.dataset(
        ResearchDatasetId.ANNOUNCEMENT
    )
    assert candidate.columns.tolist() == strict.columns.tolist()


def _readonly_real_warehouse(root: Path) -> ResearchWarehouse:
    warehouse = object.__new__(ResearchWarehouse)
    warehouse.root = root
    warehouse.facts_root = root / "facts"
    warehouse.staging_root = root / ".staging"
    warehouse.duckdb_path = root / "research.duckdb"
    return warehouse


def _month_values(start: date, end: date) -> tuple[str, ...]:
    values: list[str] = []
    cursor = date(start.year, start.month, 1)
    while cursor <= end:
        values.append(cursor.strftime("%Y-%m"))
        cursor = (
            date(cursor.year + 1, 1, 1)
            if cursor.month == 12
            else date(cursor.year, cursor.month + 1, 1)
        )
    return tuple(values)


def _real_six_route_fact_plan(warehouse: ResearchWarehouse, origin: date):
    from stock_analyzer.evaluation.v3_backtest.routes import (
        derive_declared_route_windows,
    )

    inventory = {
        dataset: tuple(
            warehouse.partition_manifest(dataset)
            .get("partition_value", pd.Series(dtype=str))
            .astype(str)
            .tolist()
        )
        for dataset in (
            ResearchDatasetId.INDUSTRY_MEMBER,
            ResearchDatasetId.THEME_MEMBER,
            ResearchDatasetId.EARNINGS_FORECAST,
            ResearchDatasetId.EARNINGS_EXPRESS,
            ResearchDatasetId.INCOME_STATEMENT,
            ResearchDatasetId.ANNOUNCEMENT,
            ResearchDatasetId.INDUSTRY_DAILY,
            ResearchDatasetId.MAIN_BUSINESS,
            ResearchDatasetId.REPURCHASE,
            ResearchDatasetId.BALANCE_SHEET,
            ResearchDatasetId.CASH_FLOW,
        )
    }
    event_start, report_periods = derive_declared_route_windows(
        formation_date=origin,
        event_lookback_calendar_days=45,
        completed_quarter_count=4,
        future_quarter_count=2,
    )
    completed_reports = tuple(
        value.isoformat() for value in report_periods if value <= origin
    )
    report_year = min(value.year for value in report_periods)
    earnings_months = _month_values(date(report_year, 1, 1), origin)
    event_months = _month_values(event_start, origin)

    def present(dataset: ResearchDatasetId, requested):
        available = set(inventory[dataset])
        selected = tuple(value for value in requested if value in available)
        if not selected:
            raise AssertionError(f"real route input has no partition: {dataset.value}")
        return selected

    industry_dates = tuple(
        value
        for value in sorted(inventory[ResearchDatasetId.INDUSTRY_DAILY])
        if value <= origin.isoformat()
    )[-82:]
    return {
        ResearchDatasetId.INDUSTRY_MEMBER: inventory[
            ResearchDatasetId.INDUSTRY_MEMBER
        ],
        ResearchDatasetId.THEME_MEMBER: inventory[ResearchDatasetId.THEME_MEMBER],
        ResearchDatasetId.EARNINGS_FORECAST: present(
            ResearchDatasetId.EARNINGS_FORECAST, earnings_months
        ),
        ResearchDatasetId.EARNINGS_EXPRESS: present(
            ResearchDatasetId.EARNINGS_EXPRESS, earnings_months
        ),
        ResearchDatasetId.INCOME_STATEMENT: present(
            ResearchDatasetId.INCOME_STATEMENT, completed_reports
        ),
        ResearchDatasetId.ANNOUNCEMENT: present(
            ResearchDatasetId.ANNOUNCEMENT, event_months
        ),
        ResearchDatasetId.INDUSTRY_DAILY: industry_dates,
        ResearchDatasetId.MAIN_BUSINESS: present(
            ResearchDatasetId.MAIN_BUSINESS, completed_reports
        ),
        ResearchDatasetId.REPURCHASE: present(
            ResearchDatasetId.REPURCHASE, event_months
        ),
        ResearchDatasetId.BALANCE_SHEET: present(
            ResearchDatasetId.BALANCE_SHEET, completed_reports
        ),
        ResearchDatasetId.CASH_FLOW: present(
            ResearchDatasetId.CASH_FLOW, completed_reports
        ),
    }


@pytest.mark.skipif(
    not os.environ.get("V3_REAL_WAREHOUSE"),
    reason="set V3_REAL_WAREHOUSE for the preregistered three-date exact gate",
)
def test_real_three_date_batch_snapshots_are_exact_and_source_read_only():
    batch = _batch_module()
    source_root = Path(os.environ["V3_REAL_WAREHOUSE"]).resolve()
    output_root = Path(os.environ["V3_BACKTEST_ROOT"]).resolve()
    warehouse = _readonly_real_warehouse(source_root)
    origins = (date(2025, 10, 30), date(2026, 2, 11), date(2026, 6, 4))
    plans = {
        origin: _real_six_route_fact_plan(warehouse, origin) for origin in origins
    }
    source_before = {
        "facts": tree_fingerprint(warehouse.facts_root),
        "derived": tree_fingerprint(source_root / "derived"),
        "database": tree_fingerprint(warehouse.duckdb_path),
    }
    free_before = shutil.disk_usage(output_root).free

    started = time.perf_counter()
    store = batch.BatchSnapshotStore(
        warehouse,
        fact_plan=lambda origin: plans[origin],
    )
    batch_started = time.perf_counter()
    batch_receipt = store.prepare(origins, output_root)
    batch_seconds = time.perf_counter() - batch_started
    receipts = []
    reference_seconds: dict[str, float] = {}
    for origin in origins:
        reference_started = time.perf_counter()
        reference = batch.materialize_readonly_reference_snapshot(
            warehouse,
            origin,
            fact_plan=plans[origin],
        )
        reference_seconds[origin.isoformat()] = time.perf_counter() - reference_started
        receipts.append(batch.compare_snapshot_exact(reference, store.snapshot(origin)))
    gate = batch.persist_equivalence_gate(receipts, output_root)
    elapsed = time.perf_counter() - started
    free_after = shutil.disk_usage(output_root).free
    source_after = {
        "facts": tree_fingerprint(warehouse.facts_root),
        "derived": tree_fingerprint(source_root / "derived"),
        "database": tree_fingerprint(warehouse.duckdb_path),
    }
    metrics = {
        "origins": [value.isoformat() for value in origins],
        "exact_equal": [value.exact_equal for value in receipts],
        "batch_seconds": batch_seconds,
        "reference_seconds": reference_seconds,
        "total_seconds": elapsed,
        "cache_bytes_written": batch_receipt.cache_bytes,
        "external_space_consumed_bytes": max(0, free_before - free_after),
        "source_fingerprint_before": source_before,
        "source_fingerprint_after": source_after,
        "source_fact_reads": dict(batch_receipt.source_fact_reads),
    }
    metrics_path = output_root / "preflight" / "equivalence-performance.json"
    staged = metrics_path.with_name(f".{metrics_path.name}.partial")
    staged.write_text(json.dumps(metrics, sort_keys=True), encoding="utf-8")
    os.replace(staged, metrics_path)

    assert gate.is_file()
    assert all(value.exact_equal for value in receipts)
    assert source_after == source_before
    assert all(count == 1 for count in dict(batch_receipt.source_fact_reads).values())
