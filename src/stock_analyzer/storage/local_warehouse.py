from __future__ import annotations

import json
import shutil
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd
from pydantic import BaseModel

from stock_analyzer.data.models import MarketDataBundle
from stock_analyzer.storage.manual_holdings import ManualHoldingStore


class WarehouseWriteResult(BaseModel):
    market_daily_rows: int
    daily_basic_rows: int
    stock_basic_rows: int
    source_run_rows: int


class LocalWarehouse:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.parquet_root = root / "parquet"
        self.duckdb_path = root / "warehouse.duckdb"

    def save_bundle(self, bundle: MarketDataBundle) -> WarehouseWriteResult:
        self.root.mkdir(parents=True, exist_ok=True)
        self.parquet_root.mkdir(parents=True, exist_ok=True)
        market_rows = [self._parquet_safe_row(item.model_dump(mode="json")) for item in bundle.daily_bars]
        basic_rows = [self._parquet_safe_row(item.model_dump(mode="json")) for item in bundle.daily_basic]
        stock_rows = [self._parquet_safe_row(item.model_dump(mode="json")) for item in bundle.stock_basic]
        source_rows = [self._parquet_safe_row(item.model_dump(mode="json")) for item in bundle.source_runs]

        self._write_trade_date_partition("market_daily", bundle.trade_date, market_rows)
        self._write_trade_date_partition("daily_basic", bundle.trade_date, basic_rows)
        self._write_trade_date_partition("source_runs", bundle.trade_date, source_rows)
        self._write_snapshot_partition("stock_basic", bundle.trade_date, stock_rows)
        self._refresh_duckdb_marker()
        return WarehouseWriteResult(
            market_daily_rows=len(market_rows),
            daily_basic_rows=len(basic_rows),
            stock_basic_rows=len(stock_rows),
            source_run_rows=len(source_rows),
        )

    def query_count(self, dataset: str, trade_date: date) -> int:
        partition = self.parquet_root / dataset / f"trade_date={trade_date.isoformat()}" / "data.parquet"
        if not partition.exists():
            return 0
        with duckdb.connect(str(self.duckdb_path)) as connection:
            return int(
                connection.execute(
                    "select count(*) from read_parquet(?)",
                    [str(partition)],
                ).fetchone()[0]
            )

    def manual_holding_store(self) -> ManualHoldingStore:
        return ManualHoldingStore(self.root / "manual")

    def _write_trade_date_partition(self, dataset: str, trade_date: date, rows: list[dict]) -> None:
        partition_dir = self.parquet_root / dataset / f"trade_date={trade_date.isoformat()}"
        self._replace_partition(partition_dir, rows)

    def _write_snapshot_partition(self, dataset: str, snapshot_date: date, rows: list[dict]) -> None:
        partition_dir = self.parquet_root / dataset / f"snapshot_date={snapshot_date.isoformat()}"
        self._replace_partition(partition_dir, rows)

    def _replace_partition(self, partition_dir: Path, rows: list[dict]) -> None:
        if partition_dir.exists():
            shutil.rmtree(partition_dir)
        partition_dir.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows).to_parquet(partition_dir / "data.parquet", index=False)

    def _parquet_safe_row(self, row: dict) -> dict:
        return {
            key: json.dumps(value, ensure_ascii=False, sort_keys=True) if isinstance(value, (dict, list)) else value
            for key, value in row.items()
        }

    def _refresh_duckdb_marker(self) -> None:
        with duckdb.connect(str(self.duckdb_path)) as connection:
            connection.execute("create table if not exists warehouse_metadata (key text primary key, value text)")
            connection.execute("insert or replace into warehouse_metadata values ('format', 'duckdb-parquet-v1')")
