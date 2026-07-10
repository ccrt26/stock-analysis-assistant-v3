from datetime import date

from stock_analyzer.domain.models import ActionDecision, ManualActionRecord, ManualHolding
from stock_analyzer.storage.local_warehouse import LocalWarehouse
from stock_analyzer.storage.manual_holdings import ManualHoldingStore


def test_manual_holding_store_round_trips_holdings_and_actions(tmp_path):
    store = ManualHoldingStore(tmp_path / "local_warehouse" / "manual")
    holding = ManualHolding(
        ts_code="600000.SH",
        name="浦发银行",
        position_pct=6.5,
        cost_price=10.2,
        quantity=1000,
        entry_date=date(2026, 7, 1),
        thesis_id="2026-07-01-600000.SH",
        notes="测试持仓",
    )
    action = ManualActionRecord(
        action_date=date(2026, 7, 10),
        ts_code="600000.SH",
        name="浦发银行",
        decision=ActionDecision.SMALL_EXPLORATORY,
        position_pct=6.5,
        reason="首次记录",
        evidence_id="2026-07-10-600000.SH",
        notes="首次记录",
    )

    store.save_holdings([holding])
    store.append_action(action)

    assert store.load_holdings() == [holding]
    assert store.load_actions() == [action]


def test_manual_holding_store_missing_files_return_empty_lists(tmp_path):
    store = ManualHoldingStore(tmp_path / "manual")

    assert store.load_holdings() == []
    assert store.load_actions() == []


def test_local_warehouse_exposes_manual_holding_store(tmp_path):
    warehouse = LocalWarehouse(tmp_path / "local_warehouse")

    store = warehouse.manual_holding_store()

    assert isinstance(store, ManualHoldingStore)
    assert store.root == tmp_path / "local_warehouse" / "manual"
