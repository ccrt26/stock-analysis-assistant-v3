import json

from stock_analyzer.ops.virtual_scope_gap_cleanup import (
    MIGRATION_ID,
    inspect_virtual_scope_gaps,
    run_virtual_scope_gap_cleanup,
)
from stock_analyzer.storage.research_schema import connect_research_warehouse
from stock_analyzer.storage.research_warehouse import ResearchWarehouse


def test_virtual_scope_gap_cleanup_removes_only_virtual_rows_and_is_idempotent(
    tmp_path,
):
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    archive = tmp_path / "archive"
    with connect_research_warehouse(warehouse.duckdb_path) as connection:
        connection.execute(
            """
            insert into research_data_gaps values
            ('virtual', 'scope:fundamentals', '2021-01-01:2026-01-01',
             'waiting_upstream', 'scope_incomplete', null,
             now(), now(), null, '虚拟范围', '{}')
            """
        )
        connection.execute(
            """
            insert into research_data_gaps values
            ('real', 'equity_daily', '2026-01-01',
             'waiting_upstream', 'waiting_upstream', 'tushare',
             now(), now(), null, '真实分区', '{}')
            """
        )

    assert inspect_virtual_scope_gaps(warehouse.root)["rows"] == 1

    receipt = run_virtual_scope_gap_cleanup(warehouse.root, archive)

    assert receipt["status"] == "completed"
    repair_root = archive / "repairs" / MIGRATION_ID
    backup = json.loads((repair_root / "backups" / "rows.json").read_text())
    assert [row["gap_id"] for row in backup] == ["virtual"]
    with connect_research_warehouse(
        warehouse.duckdb_path, read_only=True
    ) as connection:
        rows = connection.execute(
            "select gap_id, dataset_id from research_data_gaps order by gap_id"
        ).fetchall()
    assert rows == [("real", "equity_daily")]

    second = run_virtual_scope_gap_cleanup(warehouse.root, archive)
    assert second["status"] == "already_applied"
