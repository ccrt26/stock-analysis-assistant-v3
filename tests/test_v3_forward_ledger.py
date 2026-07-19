from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from stock_analyzer.evaluation.v3_forward.ledger import (
    FROZEN_OUTPUT_ROOT,
    ForwardLedger,
    ImmutableEvidenceConflict,
    sha256_file,
)


FORMATION_DATE = date(2026, 7, 17)
ENTRY_DATE = date(2026, 7, 20)
PAYLOAD = {
    "schema_version": "v3-forward-ledger-01",
    "rule_version": "v3-forward-baseline-01",
    "formation_date": FORMATION_DATE.isoformat(),
    "data_cutoff_at": "2026-07-17T23:59:59+08:00",
    "generated_at": "2026-07-19T16:00:00+08:00",
    "attention_count": 1,
    "action_count": 1,
}
CANDIDATES = pd.DataFrame(
    {
        "formation_date": [FORMATION_DATE],
        "ts_code": ["000001.SZ"],
        "user_layer": ["关注"],
        "action_confirmed": [True],
    }
)
ENTRIES = pd.DataFrame(
    {
        "formation_date": [FORMATION_DATE],
        "entry_date": [ENTRY_DATE],
        "ts_code": ["000001.SZ"],
        "entry_status": ["executable_entry"],
        "action_price": [10.0],
    }
)
SNAPSHOTS = pd.DataFrame(
    {
        "formation_date": [FORMATION_DATE],
        "entry_date": [ENTRY_DATE],
        "as_of_date": [date(2026, 7, 24)],
        "ts_code": ["000001.SZ"],
        "horizon": [5],
        "target_touched": [False],
    }
)


@pytest.fixture
def ledger(tmp_path: Path) -> ForwardLedger:
    return ForwardLedger(tmp_path / "forward", enforce_real_root=False)


def test_real_mode_rejects_non_frozen_output_root(tmp_path: Path):
    with pytest.raises(ValueError, match="U盘专用目录"):
        ForwardLedger(tmp_path / "wrong", enforce_real_root=True)

    assert FROZEN_OUTPUT_ROOT.as_posix().endswith(
        "/股票分析助手-V3回测/2026-07-19-v3-forward-observation"
    )


def test_formation_rejects_duplicate_stock_date_rows(ledger: ForwardLedger):
    duplicates = pd.concat([CANDIDATES, CANDIDATES], ignore_index=True)

    with pytest.raises(ValueError, match="duplicate stock-date"):
        ledger.write_formation_bundle(PAYLOAD, duplicates, "形成报告")


def test_identical_formation_rerun_is_noop_and_preserves_bytes(
    ledger: ForwardLedger,
):
    first = ledger.write_formation_bundle(PAYLOAD, CANDIDATES, "形成报告")
    before = {path.name: sha256_file(path) for path in first.path.iterdir() if path.is_file()}

    second = ledger.write_formation_bundle(PAYLOAD, CANDIDATES, "形成报告")
    after = {path.name: sha256_file(path) for path in first.path.iterdir() if path.is_file()}

    assert second.idempotent is True
    assert second.path == first.path
    assert after == before


def test_different_content_for_same_identity_fails_without_overwrite(
    ledger: ForwardLedger,
):
    first = ledger.write_formation_bundle(PAYLOAD, CANDIDATES, "形成报告")
    before = sha256_file(first.path / "formation.json")
    changed = {**PAYLOAD, "action_count": 0}

    with pytest.raises(ImmutableEvidenceConflict):
        ledger.write_formation_bundle(changed, CANDIDATES, "形成报告")

    assert sha256_file(first.path / "formation.json") == before


def test_entry_and_snapshot_do_not_change_formation_hash(ledger: ForwardLedger):
    formation = ledger.write_formation_bundle(PAYLOAD, CANDIDATES, "形成报告")
    before = {
        path.name: sha256_file(path) for path in formation.path.iterdir() if path.is_file()
    }

    ledger.write_entry_bundle(FORMATION_DATE, ENTRY_DATE, ENTRIES, "开盘报告")
    ledger.write_snapshot_bundle(
        FORMATION_DATE,
        date(2026, 7, 24),
        5,
        SNAPSHOTS,
        "阶段快照",
    )

    after = {
        path.name: sha256_file(path) for path in formation.path.iterdir() if path.is_file()
    }
    assert after == before
    assert len(ledger.load_formations()) == 1
    assert ledger.load_formations()[0].payload["formation_date"] == "2026-07-17"
