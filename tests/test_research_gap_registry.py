from datetime import date

from stock_analyzer.data.research_contracts import ResearchDatasetId
from stock_analyzer.storage.research_gap_registry import ResearchGapRegistry
from stock_analyzer.storage.research_schema import connect_research_warehouse
from stock_analyzer.storage.research_warehouse import ResearchWarehouse


def _rows(warehouse):
    with connect_research_warehouse(
        warehouse.duckdb_path, read_only=True
    ) as connection:
        return connection.execute(
            """
            select dataset_id, partition_value, scope_key, status,
                   reason_category, source_endpoint
            from research_data_gaps order by scope_key
            """
        ).fetchall()


def test_gap_reason_change_updates_one_current_scope(tmp_path):
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    registry = ResearchGapRegistry(warehouse.duckdb_path)

    registry.record(
        ResearchDatasetId.INDUSTRY_DAILY,
        date(2026, 9, 1),
        status="failed",
        reason_category="network",
        source_name="tushare",
        source_endpoint="sw_daily",
    )
    registry.record(
        ResearchDatasetId.INDUSTRY_DAILY,
        date(2026, 9, 1),
        status="permission_denied",
        reason_category="permission_denied",
        source_name="tushare",
        source_endpoint="sw_daily",
    )

    assert _rows(warehouse) == [
        (
            "industry_daily", "2026-09-01", "", "permission_denied",
            "permission_denied", "sw_daily",
        )
    ]


def test_minute_scopes_do_not_overwrite_each_other(tmp_path):
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    registry = ResearchGapRegistry(warehouse.duckdb_path)
    for code in ("000001.SZ", "000002.SZ"):
        registry.record(
            ResearchDatasetId.MINUTE_BAR,
            "2026-09-01",
            scope_key=code,
            status="unsupported_optional",
            reason_category="permission_denied",
            source_name="tushare",
            source_endpoint="stk_mins",
        )

    assert [row[2] for row in _rows(warehouse)] == ["000001.SZ", "000002.SZ"]


def test_only_matching_source_endpoint_success_resolves_gap(tmp_path):
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    registry = ResearchGapRegistry(warehouse.duckdb_path)
    registry.record(
        ResearchDatasetId.INDUSTRY_DAILY,
        "2026-09-01",
        status="permission_denied",
        reason_category="permission_denied",
        source_name="tushare",
        source_endpoint="sw_daily",
    )

    assert registry.resolve_from_success(
        ResearchDatasetId.INDUSTRY_DAILY,
        "2026-09-01",
        source_name="tushare",
        source_endpoint="index_daily",
    ) == 0
    assert _rows(warehouse)[0][3] == "permission_denied"

    assert registry.resolve_from_success(
        ResearchDatasetId.INDUSTRY_DAILY,
        "2026-09-01",
        source_name="tushare",
        source_endpoint="sw_daily",
    ) == 1
    assert _rows(warehouse)[0][3] == "resolved"


def test_proxy_replacement_resolves_only_supported_legacy_industry_gaps(tmp_path):
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    registry = ResearchGapRegistry(warehouse.duckdb_path)
    registry.record(
        ResearchDatasetId.INDUSTRY_DAILY,
        "2026-09-02",
        status="permission_denied",
        reason_category="permission_denied",
        source_name="tushare",
        source_endpoint="sw_daily",
        detail={"message": "insufficient points"},
    )

    assert registry.resolve_legacy_industry_gap_with_proxy("2026-09-02") == 1

    with connect_research_warehouse(
        warehouse.duckdb_path, read_only=True
    ) as connection:
        status, source_endpoint, detail = connection.execute(
            """
            select status, source_endpoint, detail_json
            from research_data_gaps
            where dataset_id = 'industry_daily'
              and partition_value = '2026-09-02'
            """
        ).fetchone()
    assert status == "resolved"
    assert source_endpoint == "sw_daily"
    assert "replacement_capability_ready" in detail
    assert "industry_daily_proxy" in detail
    assert "sw_l1_free_float_proxy_v1" in detail
