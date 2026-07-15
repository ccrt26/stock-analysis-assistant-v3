from datetime import date, datetime, timezone
import hashlib
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from stock_analyzer.analysis.market_context_features import (
    MARKET_CONTEXT_FORMULA_VERSION,
)
from stock_analyzer.knowledge import capability as capability_module
from stock_analyzer.knowledge.capability import inspect_warehouse_capabilities
from stock_analyzer.storage.research_schema import connect_research_warehouse
from stock_analyzer.storage.research_warehouse import ResearchWarehouse


ANALYSIS_DATE = date(2026, 7, 10)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def initialize_root(tmp_path: Path, name: str = "warehouse") -> Path:
    root = tmp_path / name
    root.mkdir()
    with connect_research_warehouse(root / "research.duckdb"):
        pass
    return root


def write_table(root: Path, relative_path: str, rows: list[dict]) -> tuple[Path, str]:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), path)
    return path, sha256_file(path)


def insert_fact(
    root: Path,
    *,
    dataset_id: str = "equity_daily",
    include_available_at: bool = True,
    file_sha256: str | None = None,
) -> Path:
    row = {
        "trade_date": ANALYSIS_DATE,
        "ts_code": "000001.SZ",
        "close": 10.2,
    }
    if include_available_at:
        row["available_at"] = datetime(2026, 7, 10, 7, 1, tzinfo=timezone.utc)
    relative_path = f"facts/{dataset_id}/date=2026-07-10/data.parquet"
    path, actual_sha = write_table(root, relative_path, [row])
    with connect_research_warehouse(root / "research.duckdb") as connection:
        connection.execute(
            """
            insert into research_fact_partitions values
            (?, '2026-07-10', ?, 1, 'content', ?, null, null,
             '["test"]', now(), 'test-run', 'passed')
            """,
            [dataset_id, relative_path, file_sha256 or actual_sha],
        )
    return path


def insert_derived(
    root: Path,
    *,
    feature_set: str = "market_context",
    analysis_date: date = ANALYSIS_DATE,
    formula_version: str = MARKET_CONTEXT_FORMULA_VERSION,
    quality_status: str = "complete",
    limitations: str = "[]",
    file_sha256: str | None = None,
) -> Path:
    relative_path = (
        f"derived/{feature_set}/analysis_date={analysis_date.isoformat()}/"
        f"formula_version={formula_version}/data.parquet"
    )
    path, actual_sha = write_table(
        root,
        relative_path,
        [{"analysis_date": analysis_date, "coverage_status": "complete"}],
    )
    with connect_research_warehouse(root / "research.duckdb") as connection:
        connection.execute(
            """
            insert into research_derived_partitions values
            (?, ?, ?, ?, 1, 'content', ?, 'input-hash', '{}', ?, ?,
             now(), 'derived-run')
            """,
            [
                feature_set,
                analysis_date,
                formula_version,
                relative_path,
                file_sha256 or actual_sha,
                quality_status,
                limitations,
            ],
        )
    return path


def fail_row_loading(*args, **kwargs):
    raise AssertionError("capability inspection must not load parquet rows")


def test_inspector_reads_manifests_and_parquet_schema_without_loading_rows(
    tmp_path, monkeypatch
):
    root = initialize_root(tmp_path)
    insert_fact(root)
    insert_derived(root)
    monkeypatch.setattr(pd, "read_parquet", fail_row_loading)
    monkeypatch.setattr(ResearchWarehouse, "read_current", fail_row_loading)

    snapshot = inspect_warehouse_capabilities(root, ANALYSIS_DATE)

    fact = snapshot.lookup("fact", "equity_daily")
    derived = snapshot.lookup("derived", "market_context")
    assert fact is not None
    assert fact.fields == ("available_at", "close", "trade_date", "ts_code")
    assert fact.row_count == 1
    assert fact.structurally_ready is True
    assert derived is not None
    assert derived.fields == ("analysis_date", "coverage_status")
    assert derived.structurally_ready is True


def test_inspector_opens_duckdb_read_only(tmp_path, monkeypatch):
    root = initialize_root(tmp_path)
    insert_fact(root)
    captured: list[bool] = []
    original = connect_research_warehouse

    def capture(path, *, read_only=False):
        captured.append(read_only)
        return original(path, read_only=read_only)

    monkeypatch.setattr(capability_module, "connect_research_warehouse", capture)
    inspect_warehouse_capabilities(root, ANALYSIS_DATE)

    assert captured
    assert all(value is True for value in captured)


def test_fact_capability_requires_available_at_for_as_of(tmp_path):
    root = initialize_root(tmp_path)
    insert_fact(root, include_available_at=False)

    item = inspect_warehouse_capabilities(root, ANALYSIS_DATE).lookup(
        "fact", "equity_daily"
    )

    assert item is not None
    assert item.as_of_supported is False
    assert item.structurally_ready is False
    assert any("available_at" in reason for reason in item.limitations)


@pytest.mark.parametrize(
    ("date_offset", "formula_version", "quality_status", "expected_present"),
    [
        (date(2026, 7, 9), MARKET_CONTEXT_FORMULA_VERSION, "complete", False),
        (ANALYSIS_DATE, "market-context-v0", "complete", True),
        (ANALYSIS_DATE, MARKET_CONTEXT_FORMULA_VERSION, "limited", True),
    ],
    ids=["wrong-date", "wrong-formula", "limited-quality"],
)
def test_derived_capability_requires_exact_date_formula_and_ready_quality(
    tmp_path, date_offset, formula_version, quality_status, expected_present
):
    root = initialize_root(tmp_path)
    insert_derived(
        root,
        analysis_date=date_offset,
        formula_version=formula_version,
        quality_status=quality_status,
    )

    item = inspect_warehouse_capabilities(root, ANALYSIS_DATE).lookup(
        "derived", "market_context"
    )

    if not expected_present:
        assert item is None
    else:
        assert item is not None
        assert item.structurally_ready is False


@pytest.mark.parametrize("damage", ["missing", "hash"], ids=["missing", "hash"])
def test_missing_file_or_hash_mismatch_is_not_complete(tmp_path, damage):
    root = initialize_root(tmp_path)
    path = insert_fact(root)
    if damage == "missing":
        path.unlink()
        expected = "missing file"
    else:
        path.write_bytes(path.read_bytes() + b"changed")
        expected = "sha256 mismatch"

    item = inspect_warehouse_capabilities(root, ANALYSIS_DATE).lookup(
        "fact", "equity_daily"
    )

    assert item is not None
    assert item.structurally_ready is False
    assert any(expected in reason for reason in item.limitations)


def test_complete_with_declared_gaps_is_ready_but_preserves_limitations(tmp_path):
    root = initialize_root(tmp_path)
    insert_derived(
        root,
        quality_status="complete_with_declared_gaps",
        limitations='["minute history unavailable"]',
    )

    item = inspect_warehouse_capabilities(root, ANALYSIS_DATE).lookup(
        "derived", "market_context"
    )

    assert item is not None
    assert item.structurally_ready is True
    assert item.limitations == ("minute history unavailable",)


def test_inspection_does_not_change_duckdb_sha256(tmp_path):
    root = initialize_root(tmp_path)
    insert_fact(root)
    insert_derived(root)
    database = root / "research.duckdb"
    before = sha256_file(database)

    inspect_warehouse_capabilities(root, ANALYSIS_DATE)

    assert sha256_file(database) == before
