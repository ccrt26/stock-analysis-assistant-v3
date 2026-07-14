from datetime import date, datetime, timedelta, timezone

import pandas as pd

from stock_analyzer.data.research_contracts import FactBatch, ResearchDatasetId
from stock_analyzer.analysis.hotspot_features import HOTSPOT_FORMULA_VERSION
from stock_analyzer.analysis.market_context_features import MARKET_CONTEXT_FORMULA_VERSION
from stock_analyzer.analysis.stock_context_features import STOCK_CONTEXT_FORMULA_VERSION
from stock_analyzer.ops.research_health import (
    build_research_health_report,
    write_health_report,
)
from stock_analyzer.storage.research_derived import DerivedFeatureStore
from stock_analyzer.storage.research_query import ResearchQuery
from stock_analyzer.storage.research_schema import connect_research_warehouse
from stock_analyzer.storage.research_warehouse import ResearchWarehouse


def _daily_batch(partition: str, code: str) -> FactBatch:
    trade_date = date.fromisoformat(partition)
    return FactBatch(
        dataset_id=ResearchDatasetId.EQUITY_DAILY,
        partition_value=partition,
        source_name="test",
        source_endpoint="daily",
        ingestion_run_id=f"run-{partition}",
        ingested_at=datetime.now(timezone.utc),
        default_available_at=datetime.now(timezone.utc),
        records=[
            {
                "trade_date": trade_date,
                "ts_code": code,
                "open": 10.0,
                "high": 10.5,
                "low": 9.8,
                "close": 10.2,
                "amount": 1000.0,
            }
        ],
    )


def test_full_history_health_audits_files_without_loading_all_facts_into_pandas(
    tmp_path, monkeypatch
):
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    warehouse.commit_batch(_daily_batch("2026-07-09", "000001.SZ"))
    warehouse.commit_batch(_daily_batch("2026-07-10", "000002.SZ"))

    monkeypatch.setattr(
        warehouse,
        "read_current",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("health must not load a full dataset into pandas")
        ),
    )
    report = build_research_health_report(
        warehouse, date(2026, 7, 10), full_history=True
    )
    daily = next(item for item in report.datasets if item.dataset_id == "equity_daily")

    assert daily.rows == 2
    assert daily.checked_partitions == 2
    assert daily.checked_rows == 2
    assert daily.duplicate_business_keys == 0
    assert daily.missing_files == 0
    assert daily.hash_mismatches == 0
    assert daily.row_count_mismatches == 0


def test_fast_health_checks_latest_partition_only(tmp_path):
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    warehouse.commit_batch(_daily_batch("2026-07-09", "000001.SZ"))
    warehouse.commit_batch(_daily_batch("2026-07-10", "000002.SZ"))

    report = build_research_health_report(
        warehouse, date(2026, 7, 10), full_history=False
    )
    daily = next(item for item in report.datasets if item.dataset_id == "equity_daily")

    assert daily.partitions == 2
    assert daily.checked_partitions == 1
    assert daily.checked_rows == 1


def _commit_derived_set(
    warehouse: ResearchWarehouse,
    data_date: date,
    *,
    sector_quality: str = "complete_with_declared_gaps",
) -> DerivedFeatureStore:
    cutoff = datetime.now(timezone.utc) + timedelta(days=1)
    snapshot = ResearchQuery(warehouse).input_manifest(
        {ResearchDatasetId.EQUITY_DAILY: (data_date.isoformat(),)},
        as_of=cutoff,
    )
    input_manifest = {
        "fact_snapshot": snapshot,
        "plain_language_summary": "test",
    }
    store = DerivedFeatureStore(warehouse.root)
    store.commit(
        "market_context",
        data_date,
        MARKET_CONTEXT_FORMULA_VERSION,
        pd.DataFrame(
            [{"analysis_date": data_date, "coverage_status": "complete"}]
        ),
        input_manifest=input_manifest,
        entity_key="analysis_date",
        quality_status="complete",
        run_id="health-market",
    )
    store.commit(
        "sector_hotspot",
        data_date,
        HOTSPOT_FORMULA_VERSION,
        pd.DataFrame(
            [
                {
                    "analysis_date": data_date,
                    "group_type": "industry",
                    "group_code": "801010.SI",
                    "coverage_status": "complete_with_declared_gaps",
                    "intraday_status": "limited",
                },
                {
                    "analysis_date": data_date,
                    "group_type": "theme",
                    "group_code": "000802.SH",
                    "coverage_status": "limited_no_membership",
                    "intraday_status": "limited",
                },
            ]
        ),
        input_manifest=input_manifest,
        entity_key=("analysis_date", "group_type", "group_code"),
        quality_status=sector_quality,
        limitations=(
            "历史分钟事实当前不可用，盘中路径指标留空",
            "1 行因核心输入不足仅保留可用观察",
        ),
        run_id="health-sector",
    )
    store.commit(
        "stock_trading_context",
        data_date,
        STOCK_CONTEXT_FORMULA_VERSION,
        pd.DataFrame(
            [
                {
                    "analysis_date": data_date,
                    "ts_code": "000001.SZ",
                    "coverage_status": "complete",
                }
            ]
        ),
        input_manifest=input_manifest,
        entity_key=("analysis_date", "ts_code"),
        quality_status="complete_with_declared_gaps",
        limitations=("日线事实不能识别交易者身份",),
        run_id="health-stock",
    )
    return store


def test_derived_health_preserves_declared_gaps_and_explains_them_plainly(
    tmp_path,
):
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    warehouse.commit_batch(_daily_batch("2026-07-10", "000001.SZ"))
    _commit_derived_set(warehouse, date(2026, 7, 10))

    report = build_research_health_report(warehouse, date(2026, 7, 10))
    sector = next(
        item for item in report.derived_features
        if item.feature_set == "sector_hotspot"
    )
    _, markdown = write_health_report(report, tmp_path / "health")
    text = markdown.read_text(encoding="utf-8")

    assert report.derived_ready_for_research is True
    assert report.derived_has_declared_gaps is True
    assert sector.quality_status == "complete_with_declared_gaps"
    assert sector.ready is True
    assert sector.no_membership_entities == 1
    assert sector.no_membership_industries == 0
    assert sector.no_membership_themes == 1
    assert sector.intraday_limited_entities == 2
    assert "可以使用，但有明确限制" in text
    assert "1 个主题没有公开成分股" in text
    assert "分钟数据不可用" in text


def test_derived_health_reports_missing_stale_formula_and_unresolved_failure(
    tmp_path,
):
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    warehouse.commit_batch(_daily_batch("2026-07-10", "000001.SZ"))
    _commit_derived_set(warehouse, date(2026, 7, 10))
    store = DerivedFeatureStore(warehouse.root)
    market = store.partition_manifest(
        "market_context",
        analysis_date=date(2026, 7, 10),
        formula_version=MARKET_CONTEXT_FORMULA_VERSION,
    ).iloc[0]
    (warehouse.root / market["relative_path"]).unlink()
    with connect_research_warehouse(warehouse.duckdb_path) as connection:
        connection.execute(
            """
            update research_derived_partitions
            set formula_version = 'sector-hotspot-v1'
            where feature_set = 'sector_hotspot' and analysis_date = ?
            """,
            [date(2026, 7, 10)],
        )
        connection.execute(
            """
            insert into research_derived_runs
            values ('health-failed', 'stock_trading_context', ?, ?, '{}',
                    'input', 'failed', '[]', 'failed', null, null, null, ?, ?)
            """,
            [
                date(2026, 7, 10),
                STOCK_CONTEXT_FORMULA_VERSION,
                datetime.now(timezone.utc) + timedelta(days=2),
                datetime.now(timezone.utc) + timedelta(days=2),
            ],
        )

    report = build_research_health_report(warehouse, date(2026, 7, 10))
    by_name = {item.feature_set: item for item in report.derived_features}

    assert by_name["market_context"].missing_files == 1
    assert by_name["market_context"].ready is False
    assert by_name["sector_hotspot"].present is False
    assert by_name["sector_hotspot"].stale_formula is True
    assert by_name["stock_trading_context"].unresolved_failed_runs == 1
    assert by_name["stock_trading_context"].ready is False
    assert report.derived_ready_for_research is False


def test_derived_health_detects_row_hash_and_input_manifest_changes(tmp_path):
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    warehouse.commit_batch(_daily_batch("2026-07-10", "000001.SZ"))
    _commit_derived_set(warehouse, date(2026, 7, 10))
    with connect_research_warehouse(warehouse.duckdb_path) as connection:
        connection.execute(
            """
            update research_derived_partitions
            set row_count = row_count + 1
            where feature_set = 'market_context' and analysis_date = ?
            """,
            [date(2026, 7, 10)],
        )
        connection.execute(
            """
            update research_derived_partitions
            set file_sha256 = 'wrong'
            where feature_set = 'sector_hotspot' and analysis_date = ?
            """,
            [date(2026, 7, 10)],
        )
    warehouse.commit_batch(
        FactBatch(
            **{
                **_daily_batch("2026-07-10", "000001.SZ").model_dump(),
                "ingestion_run_id": "revised-health-fact",
                "records": [
                    {
                        "trade_date": date(2026, 7, 10),
                        "ts_code": "000001.SZ",
                        "open": 10.0,
                        "high": 11.0,
                        "low": 9.8,
                        "close": 10.8,
                        "amount": 2000.0,
                    }
                ],
            }
        )
    )

    report = build_research_health_report(warehouse, date(2026, 7, 10))
    by_name = {item.feature_set: item for item in report.derived_features}

    assert by_name["market_context"].row_count_mismatches == 1
    assert by_name["sector_hotspot"].hash_mismatches == 1
    assert by_name["stock_trading_context"].stale_input_manifest is True
    assert report.derived_ready_for_research is False
