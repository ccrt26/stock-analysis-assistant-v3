import os
from collections import Counter
from datetime import date
from pathlib import Path

import duckdb
import pytest

from stock_analyzer.data.readiness import AcquisitionGroupId
from stock_analyzer.storage.formal_migration import (
    audit_formal_warehouse,
)
from stock_analyzer.storage.formal_warehouse import FormalWarehouse


ROOT_ENV = "STOCK_ANALYZER_REAL_WAREHOUSE_ROOT"


def _root() -> Path:
    value = os.environ.get(ROOT_ENV)
    if not value:
        pytest.skip(f"{ROOT_ENV} is not set")
    return Path(value)


CANONICAL_MARKET_VERSION = (
    "market_decision-2026-07-10-"
    "b7a9de49700fa01bc8836b18f0f050e5d31f6c6c1107b0453707515df8e2cb66"
)


def test_real_formal_warehouse_is_complete_without_legacy_json():
    root = _root()
    source = root / "formal_evidence"
    assert not source.exists()

    with duckdb.connect(str(root / "warehouse.duckdb"), read_only=True) as connection:
        assert connection.execute("select count(*) from formal_versions").fetchone()[0] == 18
        assert connection.execute("select count(*) from formal_run_receipts").fetchone()[0] == 116
        assert connection.execute("select count(*) from formal_candidate_sets").fetchone()[0] == 5
        assert connection.execute("select count(*) from formal_frozen_reports").fetchone()[0] == 1
        assert connection.execute("select count(*) from formal_report_candidates").fetchone()[0] == 2
        assert connection.execute("select count(*) from formal_capability_bundles").fetchone()[0] == 7
        assert connection.execute("select count(*) from formal_canonical_versions").fetchone()[0] == 6

    warehouse = FormalWarehouse(root)
    manifest = warehouse.canonical_manifest(
        AcquisitionGroupId.MARKET_DECISION,
        date(2026, 7, 10),
    )
    assert manifest is not None
    assert manifest.version_id == CANONICAL_MARKET_VERSION
    payload = warehouse.read_group_version(manifest.version_id)
    assert payload is not None
    counts = Counter(record["record_type"] for record in payload.records)
    assert len(payload.covered_dates) == 82
    assert payload.covered_dates[0] == date(2026, 3, 12)
    assert payload.covered_dates[-1] == date(2026, 7, 10)
    assert counts == {
        "equity_bar": 431_310,
        "index_bar": 246,
        "daily_basic": 5_270,
    }
    audit = audit_formal_warehouse(warehouse, strict_hashes=True)
    assert audit.complete is True, audit.errors

    receipts = warehouse.list_run_receipts()
    assert len(receipts) == 116
    candidate_references = 0
    for stored_receipt in receipts:
        assert all(
            warehouse.group_version_manifest(version_id) is not None
            for version_id in stored_receipt.group_version_ids.values()
        )
        if stored_receipt.candidate_set_id is not None:
            candidate_references += 1
            candidate = warehouse.candidate_set(stored_receipt.candidate_set_id)
            assert candidate.run_id == stored_receipt.run_id
    assert candidate_references == 81
