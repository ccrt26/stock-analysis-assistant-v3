from datetime import date

from stock_analyzer.data.models import (
    DailyBar,
    DailyBasicRow,
    DataStatus,
    MarketDataBundle,
    SourceGrade,
    SourceRunRecord,
    SourceStatus,
    StockBasicRow,
)
from stock_analyzer.storage.local_warehouse import LocalWarehouse
from stock_analyzer.storage.formal_schema import connect_formal_warehouse


def _bundle(trade_date: date) -> MarketDataBundle:
    return MarketDataBundle(
        trade_date=trade_date,
        data_status=DataStatus.COMPLETE_PRIMARY,
        source_grade=SourceGrade.PRIMARY,
        source_versions={"tushare": f"daily:{trade_date.isoformat()}"},
        stock_basic=[
            StockBasicRow(ts_code="600000.SH", name="浦发银行", exchange="SSE"),
            StockBasicRow(ts_code="000004.SZ", name="国华网安", exchange="SZSE"),
        ],
        daily_bars=[
            DailyBar(
                trade_date=trade_date,
                ts_code="600000.SH",
                close=10.2,
                amount=100000000,
                source_name="tushare",
                source_grade=SourceGrade.PRIMARY,
            ),
            DailyBar(
                trade_date=trade_date,
                ts_code="000004.SZ",
                close=12.3,
                amount=80000000,
                source_name="tushare",
                source_grade=SourceGrade.PRIMARY,
            ),
        ],
        daily_basic=[
            DailyBasicRow(
                trade_date=trade_date,
                ts_code="600000.SH",
                turnover_rate=1.2,
                source_name="tushare",
                source_grade=SourceGrade.PRIMARY,
            )
        ],
        source_runs=[
            SourceRunRecord(
                trade_date=trade_date,
                source_name="tushare",
                stage="daily",
                status=SourceStatus.SUCCESS,
                message="ok",
                source_grade=SourceGrade.PRIMARY,
                data_status=DataStatus.COMPLETE_PRIMARY,
                record_count=2,
            )
        ],
    )


def test_local_warehouse_writes_partitioned_parquet_and_duckdb_index(tmp_path):
    trade_date = date(2026, 7, 8)
    warehouse = LocalWarehouse(tmp_path / "local_warehouse")

    result = warehouse.save_bundle(_bundle(trade_date))

    assert result.market_daily_rows == 2
    assert result.daily_basic_rows == 1
    assert result.stock_basic_rows == 2
    assert result.source_run_rows == 1
    assert (tmp_path / "local_warehouse" / "warehouse.duckdb").exists()
    assert warehouse.query_count("market_daily", trade_date) == 2
    assert warehouse.query_count("daily_basic", trade_date) == 1
    with connect_formal_warehouse(
        tmp_path / "local_warehouse" / "warehouse.duckdb",
        read_only=True,
    ) as connection:
        metadata = dict(
            connection.execute(
                "select key, value from warehouse_metadata"
            ).fetchall()
        )
    assert metadata["format"] == "duckdb-parquet-v2"
    assert metadata["formal_schema_version"] == "1"


def test_local_warehouse_rerun_replaces_same_partition(tmp_path):
    trade_date = date(2026, 7, 8)
    warehouse = LocalWarehouse(tmp_path / "local_warehouse")

    warehouse.save_bundle(_bundle(trade_date))
    warehouse.save_bundle(_bundle(trade_date))

    assert warehouse.query_count("market_daily", trade_date) == 2
