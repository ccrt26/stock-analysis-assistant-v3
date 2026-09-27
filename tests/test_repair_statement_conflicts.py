import json
from datetime import date, datetime, timezone

import pandas as pd
import pytest

from stock_analyzer.config import AppConfig
from stock_analyzer.data.research_contracts import FactBatch, ResearchDatasetId
from stock_analyzer.data.tushare_research_client import TushareResearchClient
from stock_analyzer.storage.research_conflicts import ResearchConflictRegistry
from stock_analyzer.storage.research_warehouse import ResearchWarehouse
from tools import repair_statement_conflicts as repair


def fixture(tmp_path):
    config = AppConfig(project_root=tmp_path, local_warehouse_dir=tmp_path / "warehouse", local_archive_dir=tmp_path / "archive")
    warehouse = ResearchWarehouse(config.local_warehouse_dir)
    published = datetime(2026, 4, 26, tzinfo=timezone.utc)
    base = {"ts_code": "000001.SZ", "report_period": date(2026, 3, 31), "report_type": "1",
            "statement_type": "comp=2;end=1", "ann_date": "20260425", "f_ann_date": "20260425",
            "comp_type": "2", "end_type": "1", "available_at": published}
    rows = [base | {"total_revenue": 10.0, "update_flag": "0"},
            base | {"total_revenue": 20.0, "update_flag": "1"}]
    warehouse.commit_batch(FactBatch(dataset_id=ResearchDatasetId.INCOME_STATEMENT, partition_value="2026-03-31",
        source_name="tushare", source_endpoint="income", ingestion_run_id="original", ingested_at=published,
        default_available_at=published, records=[rows[0], rows[0] | {"ts_code": "000002.SZ"}]))
    ResearchConflictRegistry(warehouse.duckdb_path).record_variants(ResearchDatasetId.INCOME_STATEMENT,
        "2026-03-31", business_key=("000001.SZ", "2026-03-31", "1", "comp=2;end=1"), rows=rows,
        source_name="tushare", source_endpoint="income", observed_at=datetime(2026, 8, 1, tzinfo=timezone.utc))
    class Pro:
        def income(self, **kwargs):
            return pd.DataFrame([{k: v for k, v in row.items() if k not in ("report_period", "available_at", "statement_type")} | {"end_date": "20260331"} for row in rows])
    return config, warehouse, lambda _: TushareResearchClient(Pro(), pacer=lambda _: None)


def test_inspection_does_not_change_any_file(tmp_path):
    config, _, _ = fixture(tmp_path)
    before = {str(p): (p.stat().st_size, p.stat().st_mtime_ns) for p in tmp_path.rglob("*") if p.is_file()}
    result = repair.inspect_conflicts(config.local_warehouse_dir)
    after = {str(p): (p.stat().st_size, p.stat().st_mtime_ns) for p in tmp_path.rglob("*") if p.is_file()}
    assert before == after
    assert result["counts"] == {"income_statement": 1}


def test_apply_preserves_history_non_targets_and_formal_health(tmp_path):
    config, warehouse, factory = fixture(tmp_path)
    official = config.local_archive_dir / "data_health" / "2026-09-22.json"
    official.parent.mkdir(parents=True)
    official.write_text('{"frozen":true}')
    reviewed = repair.inspect_conflicts(config.local_warehouse_dir)
    result = repair.apply_repair(config, reviewed, tmp_path / "repair", factory)
    assert result["status"] == "completed" and result["resolved"] == 1
    assert official.read_text() == '{"frozen":true}'
    run = next((tmp_path / "repair").glob("run-*"))
    assert (run / "backup" / "research.duckdb").is_file()
    assert json.loads((run / "result.json").read_text())["verification"]
    with __import__('duckdb').connect(str(warehouse.duckdb_path), read_only=True) as con:
        assert con.execute("select count(*) from research_fact_revisions").fetchone()[0] == 1
    assert repair.apply_repair(config, reviewed, tmp_path / "repair", factory)["status"] == "nothing_to_repair"


@pytest.mark.parametrize("obstacle", ["wal", "journal", "previous"])
def test_backup_refuses_unrecovered_state(tmp_path, obstacle):
    config, _, _ = fixture(tmp_path)
    targets = repair.inspect_conflicts(config.local_warehouse_dir)["targets"]
    root = config.local_warehouse_dir
    paths = {"wal": root / "research.duckdb.wal", "journal": root / ".fact-promotions" / "pending.json", "previous": root / "facts" / "x.parquet.previous"}
    path = paths[obstacle]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("unrecovered")
    with pytest.raises(ValueError, match="WAL|recovery"):
        repair.create_backup(root, tmp_path / "backup", targets)
    assert not (tmp_path / "backup").exists()


def test_backup_must_succeed_before_writable_warehouse_is_opened(tmp_path, monkeypatch):
    config, _, factory = fixture(tmp_path)
    reviewed = repair.inspect_conflicts(config.local_warehouse_dir)
    def refused(*args):
        raise ValueError("backup refused")
    monkeypatch.setattr(repair, "create_backup", refused)
    monkeypatch.setattr(repair, "ResearchWarehouse", lambda *a, **k: pytest.fail("must not open writable warehouse"))
    with pytest.raises(ValueError, match="backup refused"):
        repair.apply_repair(config, reviewed, tmp_path / "repair", factory)


def test_apply_rejects_unreviewed_target(tmp_path):
    config, _, factory = fixture(tmp_path)
    with pytest.raises(ValueError, match="unreviewed"):
        repair.apply_repair(config, {"targets": []}, tmp_path / "repair", factory)
    assert not (tmp_path / "repair").exists()
