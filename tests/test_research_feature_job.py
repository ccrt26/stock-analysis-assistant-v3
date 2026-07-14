from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from stock_analyzer.data.research_contracts import ResearchDatasetId


ANALYSIS_DATE = date(2026, 7, 13)


class FakeWarehouse:
    def __init__(self, root: Path, dates: list[date]) -> None:
        self.root = root
        self.calls: list[tuple[str, object]] = []
        self.commits: list[dict[str, object]] = []
        self.current: dict[tuple[str, date, str], dict[str, object]] = {}
        self.revisions: dict[str, str] = {}
        self.frames = _fact_frames(dates)
        self.partitions = {
            ResearchDatasetId.TRADE_CALENDAR: sorted({str(value.year) for value in dates}),
            ResearchDatasetId.SECURITY_MASTER: ["security-master"],
            ResearchDatasetId.INDUSTRY_CATALOG: ["SW2021"],
            ResearchDatasetId.INDUSTRY_MEMBER: ["SW2021"],
            ResearchDatasetId.THEME_CATALOG: ["official-theme-v1"],
            ResearchDatasetId.THEME_MEMBER: ["official-theme-v1"],
        }
        for dataset in (
            ResearchDatasetId.EQUITY_DAILY,
            ResearchDatasetId.DAILY_BASIC,
            ResearchDatasetId.STOCK_LIMIT,
            ResearchDatasetId.INDEX_DAILY,
            ResearchDatasetId.INDUSTRY_DAILY,
            ResearchDatasetId.THEME_DAILY,
        ):
            self.partitions[dataset] = [value.isoformat() for value in dates]
        self.partitions[ResearchDatasetId.MINUTE_BAR] = []

    def partition_manifest(self, dataset: ResearchDatasetId) -> pd.DataFrame:
        self.calls.append(("partition_manifest", dataset))
        return pd.DataFrame(
            {"partition_value": self.partitions.get(ResearchDatasetId(dataset), [])}
        )


class FakeQuery:
    def __init__(self, warehouse: FakeWarehouse) -> None:
        self.warehouse = warehouse

    def dataset_partitions_as_of(
        self,
        dataset: ResearchDatasetId,
        partitions: list[str] | tuple[str, ...],
        as_of: datetime,
    ) -> pd.DataFrame:
        dataset = ResearchDatasetId(dataset)
        values = tuple(str(value) for value in partitions)
        self.warehouse.calls.append(("query", dataset, values, as_of))
        frame = self.warehouse.frames[dataset].copy()
        if "trade_date" in frame:
            return frame[frame["trade_date"].astype(str).isin(values)].reset_index(drop=True)
        if "cal_date" in frame:
            return frame[frame["cal_date"].map(lambda value: str(value.year)).isin(values)].reset_index(drop=True)
        return frame

    def input_manifest(self, mapping, *, as_of: datetime) -> dict[str, object]:
        canonical = {
            "as_of": as_of.astimezone(timezone.utc).isoformat(),
            "partitions": [
                {
                    "dataset": ResearchDatasetId(dataset).value,
                    "partition": str(partition),
                    "resolved_content_hash": self.warehouse.revisions.get(
                        ResearchDatasetId(dataset).value, "base"
                    ),
                }
                for dataset, partitions in mapping.items()
                for partition in partitions
            ],
        }
        canonical["partitions"].sort(
            key=lambda item: (item["dataset"], item["partition"])
        )
        canonical["input_manifest_hash"] = hashlib.sha256(
            json.dumps(canonical, sort_keys=True).encode()
        ).hexdigest()
        self.warehouse.calls.append(("manifest", canonical))
        return canonical


class FakeStore:
    def __init__(self, root: Path) -> None:
        self.warehouse = _WAREHOUSES[root]

    def commit(self, feature_set, analysis_date, formula_version, frame, **kwargs):
        manifest = kwargs["input_manifest"]
        manifest_hash = hashlib.sha256(
            json.dumps(manifest, sort_keys=True).encode()
        ).hexdigest()
        key = (feature_set, analysis_date, formula_version)
        existing = self.warehouse.current.get(key)
        skipped = existing is not None and existing["manifest_hash"] == manifest_hash
        if not skipped:
            self.warehouse.current[key] = {
                "manifest_hash": manifest_hash,
                "input_manifest": manifest,
                "frame": frame.copy(),
                "quality_status": kwargs["quality_status"],
                "limitations": tuple(kwargs["limitations"]),
            }
        call = {
            "feature_set": feature_set,
            "analysis_date": analysis_date,
            "formula_version": formula_version,
            "frame": frame.copy(),
            "entity_key": kwargs["entity_key"],
            "input_manifest": manifest,
            "quality_status": kwargs["quality_status"],
            "limitations": tuple(kwargs["limitations"]),
            "skipped": skipped,
        }
        self.warehouse.commits.append(call)
        return SimpleNamespace(skipped=skipped, idempotent=skipped, row_count=len(frame))

    def partition_manifest(self, feature_set, *, analysis_date, formula_version):
        current = self.warehouse.current.get(
            (feature_set, analysis_date, formula_version)
        )
        if current is None:
            return pd.DataFrame()
        return pd.DataFrame([
            {
                "row_count": len(current["frame"]),
                "input_manifest_json": current["input_manifest"],
                "quality_status": current["quality_status"],
                "limitations_json": list(current["limitations"]),
            }
        ])


_WAREHOUSES: dict[Path, FakeWarehouse] = {}


def test_job_uses_calendar_windows_strict_manifests_and_exact_contracts(
    tmp_path: Path, monkeypatch
) -> None:
    import stock_analyzer.ops.research_features as job

    dates = [value.date() for value in pd.bdate_range(end=ANALYSIS_DATE, periods=300)]
    warehouse = FakeWarehouse(tmp_path, dates)
    _WAREHOUSES[tmp_path] = warehouse
    captured: dict[str, tuple] = {}
    monkeypatch.setattr(job, "ResearchQuery", FakeQuery)
    monkeypatch.setattr(job, "DerivedFeatureStore", FakeStore)
    monkeypatch.setattr(job, "compute_market_context_features", _capture_market(captured))
    monkeypatch.setattr(job, "compute_hotspot_features", _capture_sector(captured))
    monkeypatch.setattr(job, "compute_stock_context_features", _capture_stock(captured))

    summary = job.run_research_features(warehouse, ANALYSIS_DATE)

    query_calls = [call for call in warehouse.calls if call[0] == "query"]
    equity_windows = [call[2] for call in query_calls if call[1] is ResearchDatasetId.EQUITY_DAILY]
    index_windows = [call[2] for call in query_calls if call[1] is ResearchDatasetId.INDEX_DAILY]
    valuation_windows = [call[2] for call in query_calls if call[1] is ResearchDatasetId.DAILY_BASIC]
    assert equity_windows and max(map(len, equity_windows)) == 82
    assert index_windows and max(map(len, index_windows)) == 250
    assert valuation_windows and len(max(valuation_windows, key=len)) == 300
    assert summary.as_of.isoformat() == "2026-07-13T23:59:59+08:00"
    assert summary.failed_feature_sets == ()
    assert summary.committed_feature_sets == (
        "market_context",
        "sector_hotspot",
        "stock_trading_context",
    )
    assert [call["formula_version"] for call in warehouse.commits] == [
        "market-context-v1",
        "sector-hotspot-v2",
        "stock-trading-context-v1",
    ]
    assert [call["entity_key"] for call in warehouse.commits] == [
        "analysis_date",
        ("analysis_date", "group_type", "group_code"),
        ("analysis_date", "ts_code"),
    ]
    assert captured["sector"][6].empty
    assert captured["stock"][1]["trade_date"].nunique() == 250
    assert captured["sector"][1].columns.tolist() == [
        "group_type", "group_code", "group_name", "level", "official_index_code"
    ]
    assert "instrument_code" not in captured["sector"][6].columns
    assert all(
        call["input_manifest"]["fact_snapshot"]["as_of"]
        == "2026-07-13T15:59:59+00:00"
        for call in warehouse.commits
    )
    assert all("plain_language_summary" in call["input_manifest"] for call in warehouse.commits)
    stock_manifest = warehouse.commits[2]["input_manifest"]["fact_snapshot"]
    stock_index_partitions = [
        item for item in stock_manifest["partitions"]
        if item["dataset"] == ResearchDatasetId.INDEX_DAILY.value
    ]
    assert len(stock_index_partitions) == 250


def test_job_is_idempotent_and_only_related_manifest_changes_recompute(
    tmp_path: Path, monkeypatch
) -> None:
    import stock_analyzer.ops.research_features as job

    dates = [value.date() for value in pd.bdate_range(end=ANALYSIS_DATE, periods=300)]
    warehouse = FakeWarehouse(tmp_path, dates)
    _WAREHOUSES[tmp_path] = warehouse
    monkeypatch.setattr(job, "ResearchQuery", FakeQuery)
    monkeypatch.setattr(job, "DerivedFeatureStore", FakeStore)
    counts = {"market": 0, "sector": 0, "stock": 0}
    monkeypatch.setattr(job, "compute_market_context_features", _counted(counts, "market", _simple_market))
    monkeypatch.setattr(job, "compute_hotspot_features", _counted(counts, "sector", _simple_sector))
    monkeypatch.setattr(job, "compute_stock_context_features", _counted(counts, "stock", _simple_stock))

    first = job.run_research_features(warehouse, ANALYSIS_DATE)
    second = job.run_research_features(warehouse, ANALYSIS_DATE)
    warehouse.revisions[ResearchDatasetId.THEME_DAILY.value] = "revised"
    third = job.run_research_features(warehouse, ANALYSIS_DATE)

    assert first.committed_feature_sets == (
        "market_context", "sector_hotspot", "stock_trading_context"
    )
    assert second.skipped_feature_sets == (
        "market_context", "sector_hotspot", "stock_trading_context"
    )
    assert third.committed_feature_sets == ("sector_hotspot",)
    assert third.skipped_feature_sets == ("market_context", "stock_trading_context")
    assert counts == {"market": 1, "sector": 2, "stock": 1}


def test_later_feature_failure_preserves_prior_commits_and_continues(
    tmp_path: Path, monkeypatch
) -> None:
    import stock_analyzer.ops.research_features as job

    dates = [value.date() for value in pd.bdate_range(end=ANALYSIS_DATE, periods=300)]
    warehouse = FakeWarehouse(tmp_path, dates)
    _WAREHOUSES[tmp_path] = warehouse
    monkeypatch.setattr(job, "ResearchQuery", FakeQuery)
    monkeypatch.setattr(job, "DerivedFeatureStore", FakeStore)
    monkeypatch.setattr(job, "compute_market_context_features", _simple_market)
    monkeypatch.setattr(job, "compute_hotspot_features", _simple_sector)
    monkeypatch.setattr(job, "compute_stock_context_features", _simple_stock)
    job.run_research_features(warehouse, ANALYSIS_DATE)
    previous_sector = warehouse.current[
        ("sector_hotspot", ANALYSIS_DATE, "sector-hotspot-v2")
    ]["frame"].copy()
    warehouse.revisions[ResearchDatasetId.EQUITY_DAILY.value] = "new-equity"

    def fail_sector(*args, **kwargs):
        raise RuntimeError("sector formula failed")

    monkeypatch.setattr(job, "compute_hotspot_features", fail_sector)
    summary = job.run_research_features(warehouse, ANALYSIS_DATE)

    assert summary.failed_feature_sets == ("sector_hotspot",)
    assert "sector formula failed" in summary.plain_language_summary
    pd.testing.assert_frame_equal(
        warehouse.current[("sector_hotspot", ANALYSIS_DATE, "sector-hotspot-v2")]["frame"],
        previous_sector,
    )
    assert summary.committed_feature_sets == ("market_context", "stock_trading_context")


def _fact_frames(dates: list[date]) -> dict[ResearchDatasetId, pd.DataFrame]:
    rows = [{"exchange": "SSE", "cal_date": day, "is_open": True} for day in dates]
    equity = pd.DataFrame(
        [{"trade_date": day, "ts_code": "000001.SZ", "open": 10.0, "high": 10.5,
          "low": 9.8, "close": 10.2, "amount": 1_000_000.0} for day in dates]
    )
    daily_basic = pd.DataFrame(
        [{"trade_date": day, "ts_code": "000001.SZ", "pe_ttm": 8.0, "pb": 0.8}
         for day in dates]
    )
    limits = pd.DataFrame(
        [{"trade_date": day, "ts_code": "000001.SZ", "up_limit": 11.0, "down_limit": 9.0}
         for day in dates]
    )
    indexes = pd.DataFrame(
        [{"trade_date": day, "index_code": code, "close": 100.0}
         for day in dates for code in (
             "000001.SH", "399001.SZ", "399006.SZ", "000688.SH",
             "000300.SH", "000905.SH", "000852.SH", "899050.BJ",
         )]
    )
    industry_daily = pd.DataFrame(
        [{"trade_date": day, "industry_code": "801010.SI", "close": 100.0}
         for day in dates]
    )
    theme_daily = pd.DataFrame(
        [{"trade_date": day, "theme_code": "000802.SH", "close": 100.0}
         for day in dates]
    )
    return {
        ResearchDatasetId.TRADE_CALENDAR: pd.DataFrame(rows),
        ResearchDatasetId.SECURITY_MASTER: pd.DataFrame([
            {"ts_code": "000001.SZ", "valid_from": date(1991, 4, 3), "valid_to": None,
             "list_status": "L"}
        ]),
        ResearchDatasetId.EQUITY_DAILY: equity,
        ResearchDatasetId.DAILY_BASIC: daily_basic,
        ResearchDatasetId.STOCK_LIMIT: limits,
        ResearchDatasetId.INDEX_DAILY: indexes,
        ResearchDatasetId.INDUSTRY_CATALOG: pd.DataFrame([
            {"industry_system": "SW2021", "level": "L1", "industry_code": "801010.SI",
             "industry_name": "Agriculture", "is_published": "1", "valid_from": date(2020, 1, 1),
             "valid_to": None}
        ]),
        ResearchDatasetId.INDUSTRY_MEMBER: pd.DataFrame([
            {"industry_system": "SW2021", "level": "L1", "industry_code": "801010.SI",
             "ts_code": "000001.SZ", "valid_from": date(2020, 1, 1), "valid_to": None}
        ]),
        ResearchDatasetId.INDUSTRY_DAILY: industry_daily,
        ResearchDatasetId.THEME_CATALOG: pd.DataFrame([
            {"publisher": "official", "theme_code": "000802.SH", "theme_name": "Theme",
             "valid_from": date(2020, 1, 1), "valid_to": None}
        ]),
        ResearchDatasetId.THEME_MEMBER: pd.DataFrame([
            {"theme_code": "000802.SH", "ts_code": "000001.SZ",
             "valid_from": date(2020, 1, 1), "valid_to": None}
        ]),
        ResearchDatasetId.THEME_DAILY: theme_daily,
        ResearchDatasetId.MINUTE_BAR: pd.DataFrame(
            columns=["trade_date", "instrument_code", "minute", "close", "amount"]
        ),
    }


def _capture_market(captured):
    def compute(equity, indexes, limits, **kwargs):
        captured["market"] = (equity, indexes, limits, kwargs)
        return _simple_market(equity, indexes, limits, **kwargs)
    return compute


def _capture_sector(captured):
    def compute(*args, **kwargs):
        captured["sector"] = args
        return _simple_sector(*args, **kwargs)
    return compute


def _capture_stock(captured):
    def compute(*args, **kwargs):
        captured["stock"] = args
        return _simple_stock(*args, **kwargs)
    return compute


def _simple_market(*args, **kwargs):
    return pd.DataFrame([{"analysis_date": ANALYSIS_DATE, "coverage_status": "complete"}])


def _simple_sector(*args, **kwargs):
    return pd.DataFrame([
        {"analysis_date": ANALYSIS_DATE, "group_type": "industry", "group_code": "801010.SI",
         "coverage_status": "complete_with_declared_gaps", "limitation_notes": "minute data unavailable"}
    ])


def _simple_stock(*args, **kwargs):
    return pd.DataFrame([
        {"analysis_date": ANALYSIS_DATE, "ts_code": "000001.SZ",
         "coverage_status": "complete_with_declared_gaps",
         "limitation_notes": "trader identity unavailable"}
    ])


def _counted(counts, label, function):
    def compute(*args, **kwargs):
        counts[label] += 1
        return function(*args, **kwargs)
    return compute
