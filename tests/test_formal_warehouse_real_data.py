import json
import os
from collections import Counter
from datetime import date
from pathlib import Path

import duckdb
import pytest

from stock_analyzer.data.readiness import AcquisitionGroupId
from stock_analyzer.ops.formal_run import RunReceipt
from stock_analyzer.storage.formal_migration import (
    audit_formal_warehouse,
    inventory_legacy_formal_store,
)
from stock_analyzer.storage.formal_warehouse import FormalWarehouse


ROOT_ENV = "STOCK_ANALYZER_REAL_WAREHOUSE_ROOT"


def _root() -> Path:
    value = os.environ.get(ROOT_ENV)
    if not value:
        pytest.skip(f"{ROOT_ENV} is not set")
    return Path(value)


def test_real_formal_json_graph_is_fully_migrated_and_canonical_market_is_exact():
    root = _root()
    source = root / "formal_evidence"
    inventory = inventory_legacy_formal_store(source)
    kinds = Counter(item.object_kind for item in inventory.items)
    assert inventory.unknown_paths == ()

    with duckdb.connect(str(root / "warehouse.duckdb"), read_only=True) as connection:
        assert connection.execute("select count(*) from formal_versions").fetchone()[0] == kinds["group_version"]
        assert connection.execute("select count(*) from formal_run_receipts").fetchone()[0] == kinds["run_receipt"]
        assert connection.execute("select count(*) from formal_candidate_sets").fetchone()[0] == kinds["candidate_set"]
        assert connection.execute("select count(*) from formal_frozen_reports").fetchone()[0] == kinds["frozen_report"]
        assert connection.execute("select count(*) from formal_report_candidates").fetchone()[0] == kinds["report_candidate"]

    warehouse = FormalWarehouse(root)
    pointer = json.loads(
        (source / "canonical/market_decision/2026-07-10.json").read_text(
            encoding="utf-8"
        )
    )
    manifest = warehouse.canonical_manifest(
        AcquisitionGroupId.MARKET_DECISION,
        date(2026, 7, 10),
    )
    assert manifest is not None
    assert manifest.version_id == pointer["version_id"]
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

    receipt_items = [
        item for item in inventory.items if item.object_kind == "run_receipt"
    ]
    for item in receipt_items:
        source_receipt = RunReceipt.model_validate_json(
            (source / item.relative_path).read_text(encoding="utf-8")
        )
        stored_receipt = warehouse.run_receipt(
            source_receipt.run_id,
            source_receipt.revision,
        )
        assert stored_receipt == source_receipt
        assert all(
            warehouse.group_version_manifest(version_id) is not None
            for version_id in stored_receipt.group_version_ids.values()
        )
        if stored_receipt.candidate_set_id is not None:
            candidate = warehouse.candidate_set(stored_receipt.candidate_set_id)
            assert candidate.run_id == stored_receipt.run_id
