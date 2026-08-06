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
                "pre_close": 10.0,
                "change": 0.2,
                "pct_chg": 2.0,
                "volume": 100.0,
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


def test_health_reports_each_stage_latest_real_run_status(tmp_path):
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    with connect_research_warehouse(warehouse.duckdb_path) as connection:
        connection.execute(
            """
            insert into research_ingestion_runs values
            ('old-close', 'old-close', 'close', '2026-08-03', 'succeeded',
             now() - interval '1 hour', now() - interval '59 minutes', '{}')
            """
        )
        connection.execute(
            """
            insert into research_ingestion_runs values
            ('new-close', 'new-close', 'close', '2026-08-04', 'failed',
             now(), now(), '{"message":"行情接口失败"}')
            """
        )

    report = build_research_health_report(warehouse, date(2026, 8, 4))

    assert len(report.latest_stage_runs) == 1
    assert report.latest_stage_runs[0].run_id == "new-close"
    assert report.latest_stage_runs[0].status == "failed"
    assert report.latest_stage_runs[0].issues == ("行情接口失败",)


def test_health_rejects_nonpositive_and_overlapping_revision_intervals(tmp_path):
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    first = datetime(2026, 8, 4, 7, 1, tzinfo=timezone.utc)
    second = first + timedelta(hours=1)
    initial = _daily_batch("2026-08-04", "000001.SZ")
    initial.ingested_at = first
    initial.default_available_at = first
    warehouse.commit_batch(initial)
    changed = _daily_batch("2026-08-04", "000001.SZ")
    changed.ingested_at = second
    changed.default_available_at = second
    changed.records[0]["close"] = 10.3
    warehouse.commit_batch(changed)
    with connect_research_warehouse(warehouse.duckdb_path) as connection:
        connection.execute(
            """
            update research_fact_revisions
            set valid_to = valid_from - interval '1 second'
            where dataset_id = 'equity_daily'
            """
        )

    report = build_research_health_report(
        warehouse, date(2026, 8, 4), full_history=False
    )
    daily = next(item for item in report.datasets if item.dataset_id == "equity_daily")

    assert daily.invalid_revision_intervals == 1
    assert daily.overlapping_revision_intervals == 0
    assert daily.contract_valid is False
    assert report.complete_core_date is False


def test_health_reports_overlapping_industry_catalog_intervals(tmp_path):
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    observed_at = datetime(2026, 8, 3, 7, 1, tzinfo=timezone.utc)
    warehouse.commit_batch(
        FactBatch(
            dataset_id=ResearchDatasetId.INDUSTRY_CATALOG,
            partition_value="SW2021",
            source_name="tushare",
            source_endpoint="index_classify+index_basic",
            ingestion_run_id="overlapping-industry-catalog",
            ingested_at=observed_at,
            default_available_at=observed_at,
            records=[
                {
                    "industry_system": "SW2021",
                    "level": "L3",
                    "industry_code": "850401.SI",
                    "classification_code": "230501",
                    "industry_name": "特钢Ⅲ",
                    "parent_code": "230500",
                    "is_published": "1",
                    "valid_from": date(2026, 7, 13),
                    "valid_to": None,
                    "available_at": datetime(
                        2026, 7, 13, 7, 1, tzinfo=timezone.utc
                    ),
                },
                {
                    "industry_system": "SW2021",
                    "level": "L3",
                    "industry_code": "850401.SI",
                    "classification_code": "230501",
                    "industry_name": "特钢Ⅲ",
                    "parent_code": "230500",
                    "is_published": "1",
                    "valid_from": date(2026, 8, 3),
                    "valid_to": None,
                    "available_at": observed_at,
                },
            ],
        )
    )

    report = build_research_health_report(
        warehouse, date(2026, 8, 3), full_history=False
    )
    industry = next(
        item for item in report.datasets
        if item.dataset_id == ResearchDatasetId.INDUSTRY_CATALOG.value
    )
    _, markdown = write_health_report(report, tmp_path / "health")
    text = markdown.read_text(encoding="utf-8")

    assert industry.duplicate_business_keys == 0
    assert industry.effective_interval_overlaps == 1
    assert any(
        "SW2021/L3/850401.SI" in issue
        for issue in industry.effective_interval_issues
    )
    assert industry.contract_valid is False
    assert report.complete_core_date is False
    assert "SW2021/L3/850401.SI" in text


def test_health_reports_nested_industry_catalog_intervals(tmp_path):
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    observed_at = datetime(2026, 8, 3, 7, 1, tzinfo=timezone.utc)
    base = {
        "industry_system": "SW2021",
        "level": "L3",
        "industry_code": "850401.SI",
        "classification_code": "230501",
        "industry_name": "特钢Ⅲ",
        "parent_code": "230500",
        "is_published": "1",
        "available_at": observed_at,
    }
    warehouse.commit_batch(
        FactBatch(
            dataset_id=ResearchDatasetId.INDUSTRY_CATALOG,
            partition_value="SW2021",
            source_name="test",
            source_endpoint="index_classify",
            ingestion_run_id="nested-catalog",
            ingested_at=observed_at,
            default_available_at=observed_at,
            records=[
                base | {
                    "valid_from": date(2020, 1, 1),
                    "valid_to": date(2025, 12, 31),
                },
                base | {
                    "valid_from": date(2021, 1, 1),
                    "valid_to": date(2021, 12, 31),
                },
                base | {
                    "valid_from": date(2024, 1, 1),
                    "valid_to": date(2024, 12, 31),
                },
            ],
        )
    )

    report = build_research_health_report(
        warehouse, date(2026, 8, 3), full_history=False
    )
    catalog = next(
        item for item in report.datasets
        if item.dataset_id == ResearchDatasetId.INDUSTRY_CATALOG.value
    )

    assert catalog.effective_interval_overlaps == 2
    assert catalog.contract_valid is False


def test_fast_health_audits_all_catalog_partitions_and_inverted_interval(
    tmp_path,
):
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    observed_at = datetime(2026, 8, 3, 7, 1, tzinfo=timezone.utc)
    base = {
        "industry_system": "SW2021",
        "level": "L3",
        "classification_code": "230501",
        "industry_name": "特钢Ⅲ",
        "parent_code": "230500",
        "is_published": "1",
        "available_at": observed_at,
    }
    for partition, code, start, end in (
        ("SW2021-old", "850401.SI", date(2026, 7, 1), date(2026, 6, 30)),
        ("SW2021-new", "850402.SI", date(2026, 7, 1), None),
    ):
        warehouse.commit_batch(
            FactBatch(
                dataset_id=ResearchDatasetId.INDUSTRY_CATALOG,
                partition_value=partition,
                source_name="test",
                source_endpoint="index_classify",
                ingestion_run_id=f"catalog-{partition}",
                ingested_at=observed_at,
                default_available_at=observed_at,
                records=[
                    base | {
                        "industry_code": code,
                        "valid_from": start,
                        "valid_to": end,
                    }
                ],
            )
        )

    report = build_research_health_report(
        warehouse, date(2026, 8, 3), full_history=False
    )
    catalog = next(
        item for item in report.datasets
        if item.dataset_id == ResearchDatasetId.INDUSTRY_CATALOG.value
    )

    assert catalog.checked_partitions == 2
    assert catalog.effective_interval_overlaps == 1
    assert any(
        "inverted" in issue and "850401.SI" in issue
        for issue in catalog.effective_interval_issues
    )


def test_health_reports_overlapping_industry_member_slots_with_details(tmp_path):
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    observed_at = datetime(2026, 8, 3, 13, 30, tzinfo=timezone.utc)
    warehouse.commit_batch(
        FactBatch(
            dataset_id=ResearchDatasetId.INDUSTRY_MEMBER,
            partition_value="SW2021",
            source_name="tushare",
            source_endpoint="index_member_all",
            ingestion_run_id="overlapping-industry-members",
            ingested_at=observed_at,
            default_available_at=observed_at,
            records=[
                {
                    "ts_code": "000876.SZ",
                    "security_name": "新希望",
                    "industry_system": "SW2021",
                    "level": "L1",
                    "industry_code": "801010.SI",
                    "industry_name": "农林牧渔",
                    "valid_from": date(1998, 3, 11),
                    "valid_to": None,
                    "is_current": True,
                    "available_at": datetime(
                        2026, 7, 14, tzinfo=timezone.utc
                    ),
                },
                {
                    "ts_code": "000876.SZ",
                    "security_name": "新希望",
                    "industry_system": "SW2021",
                    "level": "L1",
                    "industry_code": "801010.SI",
                    "industry_name": "农林牧渔",
                    "valid_from": date(2026, 7, 1),
                    "valid_to": None,
                    "is_current": True,
                    "available_at": observed_at,
                },
            ],
        )
    )

    report = build_research_health_report(
        warehouse, date(2026, 8, 3), full_history=False
    )
    members = next(
        item for item in report.datasets
        if item.dataset_id == ResearchDatasetId.INDUSTRY_MEMBER.value
    )
    _, markdown = write_health_report(report, tmp_path / "health")
    text = markdown.read_text(encoding="utf-8")

    assert members.duplicate_business_keys == 0
    assert members.effective_interval_overlaps == 1
    assert any(
        all(token in issue for token in (
            "industry_member",
            "SW2021",
            "L1",
            "801010.SI",
            "000876.SZ",
            "1998-03-11..open",
            "2026-07-01..open",
        ))
        for issue in members.effective_interval_issues
    )
    assert members.contract_valid is False
    assert report.complete_core_date is False
    assert "000876.SZ" in text


def test_fast_health_audits_all_industry_member_partitions(tmp_path):
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    observed_at = datetime(2026, 8, 3, 13, 30, tzinfo=timezone.utc)
    common = {
        "ts_code": "000876.SZ",
        "security_name": "新希望",
        "industry_system": "SW2021",
        "level": "L1",
        "industry_name": "农林牧渔",
        "valid_to": None,
        "is_current": True,
        "available_at": observed_at,
    }
    warehouse.commit_batch(
        FactBatch(
            dataset_id=ResearchDatasetId.INDUSTRY_MEMBER,
            partition_value="SW2021-old",
            source_name="test",
            source_endpoint="index_member_all",
            ingestion_run_id="old-overlap",
            ingested_at=observed_at,
            default_available_at=observed_at,
            records=[
                common | {
                    "industry_code": "801010.SI",
                    "valid_from": date(1998, 3, 11),
                },
                common | {
                    "industry_code": "801020.SI",
                    "valid_from": date(2026, 7, 1),
                },
            ],
        )
    )
    warehouse.commit_batch(
        FactBatch(
            dataset_id=ResearchDatasetId.INDUSTRY_MEMBER,
            partition_value="SW2021-new",
            source_name="test",
            source_endpoint="index_member_all",
            ingestion_run_id="clean-latest",
            ingested_at=observed_at,
            default_available_at=observed_at,
            records=[
                common
                | {
                    "ts_code": "000001.SZ",
                    "industry_code": "801010.SI",
                    "valid_from": date(2020, 1, 1),
                }
            ],
        )
    )

    report = build_research_health_report(
        warehouse, date(2026, 8, 3), full_history=False
    )
    members = next(
        item for item in report.datasets
        if item.dataset_id == ResearchDatasetId.INDUSTRY_MEMBER.value
    )

    assert members.checked_partitions == 2
    assert members.effective_interval_overlaps == 1
    assert any("000876.SZ" in issue for issue in members.effective_interval_issues)


def test_health_reports_inverted_industry_member_interval(tmp_path):
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    observed_at = datetime(2026, 8, 3, 13, 30, tzinfo=timezone.utc)
    warehouse.commit_batch(
        FactBatch(
            dataset_id=ResearchDatasetId.INDUSTRY_MEMBER,
            partition_value="SW2021",
            source_name="test",
            source_endpoint="index_member_all",
            ingestion_run_id="inverted-member",
            ingested_at=observed_at,
            default_available_at=observed_at,
            records=[{
                "ts_code": "000876.SZ",
                "security_name": "新希望",
                "industry_system": "SW2021",
                "level": "L1",
                "industry_code": "801010.SI",
                "industry_name": "农林牧渔",
                "valid_from": date(2026, 7, 1),
                "valid_to": date(2026, 6, 30),
                "is_current": False,
                "available_at": observed_at,
            }],
        )
    )

    report = build_research_health_report(
        warehouse, date(2026, 8, 3), full_history=False
    )
    members = next(
        item for item in report.datasets
        if item.dataset_id == ResearchDatasetId.INDUSTRY_MEMBER.value
    )

    assert members.effective_interval_overlaps == 1
    assert any(
        "inverted" in issue and "000876.SZ" in issue
        for issue in members.effective_interval_issues
    )


def test_health_rejects_passed_manifest_when_required_vendor_columns_are_absent(
    tmp_path,
):
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    warehouse.commit_batch(_daily_batch("2026-07-10", "000001.SZ"))
    manifest = warehouse.partition_manifest(ResearchDatasetId.EQUITY_DAILY).iloc[0]
    path = warehouse.root / str(manifest["relative_path"])
    legacy = pd.read_parquet(path).drop(
        columns=["pre_close", "change", "pct_chg"]
    )
    legacy.to_parquet(path, index=False)

    report = build_research_health_report(
        warehouse, date(2026, 7, 10), full_history=False
    )
    daily = next(
        item for item in report.datasets if item.dataset_id == "equity_daily"
    )

    assert daily.schema_mismatch_partitions == 1
    assert set(daily.missing_required_columns) == {
        "change",
        "pct_chg",
        "pre_close",
    }
    assert daily.contract_valid is False
    assert report.complete_core_date is False


def test_core_health_rejects_fact_file_hash_mismatch(tmp_path):
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    warehouse.commit_batch(_daily_batch("2026-07-10", "000001.SZ"))
    manifest = warehouse.partition_manifest(ResearchDatasetId.EQUITY_DAILY).iloc[0]
    path = warehouse.root / str(manifest["relative_path"])
    changed = pd.read_parquet(path)
    changed.loc[:, "close"] = 10.3
    changed.to_parquet(path, index=False)

    report = build_research_health_report(
        warehouse, date(2026, 7, 10), full_history=False
    )
    daily = next(
        item for item in report.datasets if item.dataset_id == "equity_daily"
    )

    assert daily.hash_mismatches == 1
    assert daily.contract_valid is True
    assert daily.physical_valid is False
    assert report.complete_core_date is False


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
                            "pre_close": 10.2,
                            "change": 0.6,
                            "pct_chg": 100.0 * (10.8 / 10.2 - 1.0),
                            "volume": 100.0,
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
