from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from stock_analyzer.data.research_contracts import FactBatch, ResearchDatasetId
from stock_analyzer.ops.research_features import run_research_features
from stock_analyzer.storage.research_query import ResearchQuery
from stock_analyzer.storage.research_time_migration import (
    migrate_research_time_semantics,
)
from stock_analyzer.storage.research_warehouse import ResearchWarehouse


_ANALYSIS_DATE = date(2025, 8, 15)
_CUTOFF = datetime(
    2025,
    8,
    15,
    23,
    59,
    59,
    tzinfo=ZoneInfo("Asia/Shanghai"),
)
_INGESTED = datetime(2026, 7, 13, 15, 30, tzinfo=timezone.utc)
_BAD_BACKFILL = datetime(2026, 7, 13, 7, 1, tzinfo=timezone.utc)
_INDEX_CODES = (
    "000001.SH",
    "399001.SZ",
    "399006.SZ",
    "000688.SH",
    "000300.SH",
    "000905.SH",
    "000852.SH",
    "899050.BJ",
)


def _commit(
    warehouse: ResearchWarehouse,
    dataset: ResearchDatasetId,
    partition: str,
    records: list[dict],
) -> None:
    warehouse.commit_batch(
        FactBatch(
            dataset_id=dataset,
            partition_value=partition,
            source_name="test",
            source_endpoint=dataset.value,
            ingestion_run_id=f"historical:{dataset.value}:{partition}",
            ingested_at=_INGESTED,
            default_available_at=_BAD_BACKFILL,
            records=records,
        )
    )


def _seed_historical_feature_facts(warehouse: ResearchWarehouse) -> tuple[date, ...]:
    dates = tuple(
        value.date()
        for value in pd.bdate_range(end=_ANALYSIS_DATE, periods=82)
    )
    _commit(
        warehouse,
        ResearchDatasetId.TRADE_CALENDAR,
        "2025",
        [
            {
                "exchange": "SSE",
                "cal_date": value,
                "is_open": True,
                "available_at": _BAD_BACKFILL,
            }
            for value in dates
        ],
    )
    _commit(
        warehouse,
        ResearchDatasetId.SECURITY_MASTER,
        "security-master",
        [
            {
                "ts_code": "000001.SZ",
                "valid_from": date(1991, 4, 3),
                "valid_to": None,
                "list_status": "L",
            }
        ],
    )
    _commit(
        warehouse,
        ResearchDatasetId.INDUSTRY_CATALOG,
        "SW2021",
        [
            {
                "industry_system": "SW2021",
                "level": "L1",
                "industry_code": "801010.SI",
                "industry_name": "Agriculture",
                "is_published": "1",
                "valid_from": date(2020, 1, 1),
                "valid_to": None,
            }
        ],
    )
    _commit(
        warehouse,
        ResearchDatasetId.INDUSTRY_MEMBER,
        "SW2021",
        [
            {
                "industry_system": "SW2021",
                "level": "L1",
                "industry_code": "801010.SI",
                "ts_code": "000001.SZ",
                "valid_from": date(2020, 1, 1),
                "valid_to": None,
            }
        ],
    )
    _commit(
        warehouse,
        ResearchDatasetId.THEME_CATALOG,
        "official-theme-v1",
        [
            {
                "publisher": "official",
                "theme_code": "000802.SH",
                "theme_name": "Theme",
                "valid_from": date(2020, 1, 1),
                "valid_to": None,
            }
        ],
    )
    _commit(
        warehouse,
        ResearchDatasetId.THEME_MEMBER,
        "official-theme-v1",
        [
            {
                "theme_code": "000802.SH",
                "ts_code": "000001.SZ",
                "valid_from": date(2020, 1, 1),
                "valid_to": date(2025, 9, 30),
            },
            {
                "theme_code": "000802.SH",
                "ts_code": "000002.SZ",
                "valid_from": date(2025, 9, 1),
                "valid_to": None,
            },
        ],
    )
    for sequence, trading_date in enumerate(dates):
        partition = trading_date.isoformat()
        close = 10.0 + sequence * 0.01
        _commit(
            warehouse,
            ResearchDatasetId.EQUITY_DAILY,
            partition,
            [
                {
                    "trade_date": trading_date,
                    "ts_code": "000001.SZ",
                    "open": close - 0.05,
                    "high": close + 0.10,
                    "low": close - 0.10,
                    "close": close,
                    "pre_close": close - 0.01,
                    "change": 0.01,
                    "pct_chg": 0.1,
                    "volume": 100_000.0,
                    "amount": 1_000_000.0 + sequence,
                }
            ],
        )
        _commit(
            warehouse,
            ResearchDatasetId.ADJ_FACTOR,
            partition,
            [
                {
                    "trade_date": trading_date,
                    "ts_code": "000001.SZ",
                    "adj_factor": 1.0,
                }
            ],
        )
        _commit(
            warehouse,
            ResearchDatasetId.DAILY_BASIC,
            partition,
            [
                {
                    "trade_date": trading_date,
                    "ts_code": "000001.SZ",
                    "pe_ttm": 8.0 + sequence * 0.01,
                    "pb": 0.8 + sequence * 0.001,
                }
            ],
        )
        _commit(
            warehouse,
            ResearchDatasetId.STOCK_LIMIT,
            partition,
            [
                {
                    "trade_date": trading_date,
                    "ts_code": "000001.SZ",
                    "up_limit": close * 1.1,
                    "down_limit": close * 0.9,
                }
            ],
        )
        _commit(
            warehouse,
            ResearchDatasetId.INDEX_DAILY,
            partition,
            [
                {
                    "trade_date": trading_date,
                    "index_code": code,
                    "close": 100.0 + sequence * 0.1,
                }
                for code in _INDEX_CODES
            ],
        )
        if trading_date >= date(2025, 7, 2):
            _commit(
                warehouse,
                ResearchDatasetId.INDUSTRY_DAILY,
                partition,
                [
                    {
                        "trade_date": trading_date,
                        "industry_code": "801010.SI",
                        "close": 100.0 + sequence * 0.1,
                        "available_at": _BAD_BACKFILL,
                    }
                ],
            )
            _commit(
                warehouse,
                ResearchDatasetId.THEME_DAILY,
                partition,
                [
                    {
                        "trade_date": trading_date,
                        "theme_code": "000802.SH",
                        "close": 100.0 + sequence * 0.1,
                        "available_at": _BAD_BACKFILL,
                    }
                ],
            )
    future_announcement = datetime(
        2025, 8, 20, 9, tzinfo=ZoneInfo("Asia/Shanghai")
    )
    _commit(
        warehouse,
        ResearchDatasetId.ANNOUNCEMENT,
        "2025-08",
        [
            {
                "announcement_id": "FUTURE-A1",
                "title": "未来公告",
                "available_at": future_announcement,
            }
        ],
    )
    return dates


def test_strict_historical_features_work_only_after_temporal_migration(tmp_path):
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    _seed_historical_feature_facts(warehouse)

    with pytest.raises(ValueError, match="trade calendar lacks required fields"):
        run_research_features(
            warehouse,
            _ANALYSIS_DATE,
            as_of=_CUTOFF,
        )

    report = migrate_research_time_semantics(
        warehouse,
        migration_id="historical-feature-test-v1",
    )
    summary = run_research_features(
        warehouse,
        _ANALYSIS_DATE,
        as_of=_CUTOFF,
    )

    assert {"trade_calendar", "industry_daily", "theme_daily"} <= set(
        report.changed_datasets
    )
    assert summary.failed_feature_sets == (), summary.errors
    assert summary.market_rows == 1
    assert summary.stock_rows > 0
    assert summary.as_of.year == 2025
    query = ResearchQuery(warehouse)
    assert query.dataset_as_of(ResearchDatasetId.ANNOUNCEMENT, _CUTOFF).empty
    members = query.dataset_as_of(ResearchDatasetId.THEME_MEMBER, _CUTOFF)
    assert members["ts_code"].tolist() == ["000001.SZ"]
    assert pd.isna(members.iloc[0]["valid_to"])
