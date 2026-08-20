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
        self.hidden_datasets: set[ResearchDatasetId] = set()
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
            ResearchDatasetId.ADJ_FACTOR,
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
        frame = self._frame(dataset, values)
        return frame

    def materialize_snapshot(self, mapping, *, as_of: datetime):
        normalized = {
            ResearchDatasetId(dataset): tuple(str(value) for value in partitions)
            for dataset, partitions in mapping.items()
        }
        frames = {
            dataset: self._frame(dataset, partitions)
            for dataset, partitions in normalized.items()
        }
        manifest = self.input_manifest(normalized, as_of=as_of)
        self.warehouse.calls.append(("snapshot", normalized, manifest))
        return FakeSnapshot(frames, manifest)

    def _frame(self, dataset, values):
        if dataset in self.warehouse.hidden_datasets:
            return self.warehouse.frames[dataset].iloc[0:0].copy()
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


class FakeSnapshot:
    def __init__(self, frames, input_manifest):
        self.frames = frames
        self.input_manifest = input_manifest

    def frame(self, dataset):
        return self.frames[ResearchDatasetId(dataset)].copy()


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


def test_market_scope_excludes_star_bse_and_special_treatment() -> None:
    from stock_analyzer.ops.research_features import _default_market_scope_codes

    securities = pd.DataFrame(
        [
            {"ts_code": "600001.SH", "market": "主板", "exchange": "SSE", "name": "沪主板", "valid_from": date(2020, 1, 1), "valid_to": None, "list_status": "L"},
            {"ts_code": "000001.SZ", "market": "主板", "exchange": "SZSE", "name": "深主板", "valid_from": date(2020, 1, 1), "valid_to": None, "list_status": "L"},
            {"ts_code": "300001.SZ", "market": "创业板", "exchange": "SZSE", "name": "创业板", "valid_from": date(2020, 1, 1), "valid_to": None, "list_status": "L"},
            {"ts_code": "688001.SH", "market": "科创板", "exchange": "SSE", "name": "科创板", "valid_from": date(2020, 1, 1), "valid_to": None, "list_status": "L"},
            {"ts_code": "830001.BJ", "market": "北交所", "exchange": "BSE", "name": "北证", "valid_from": date(2020, 1, 1), "valid_to": None, "list_status": "L"},
            {"ts_code": "600002.SH", "market": "主板", "exchange": "SSE", "name": "ST风险", "valid_from": date(2020, 1, 1), "valid_to": None, "list_status": "L"},
        ]
    )

    assert _default_market_scope_codes(securities, ANALYSIS_DATE) == {
        "600001.SH",
        "000001.SZ",
        "300001.SZ",
    }


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
    monkeypatch.setattr(job, "compute_price_analysis_features", _capture_price(captured))

    summary = job.run_research_features(warehouse, ANALYSIS_DATE)

    snapshots = [call[1] for call in warehouse.calls if call[0] == "snapshot"]
    equity_windows = [
        mapping[ResearchDatasetId.EQUITY_DAILY]
        for mapping in snapshots
        if ResearchDatasetId.EQUITY_DAILY in mapping
    ]
    index_windows = [
        mapping[ResearchDatasetId.INDEX_DAILY]
        for mapping in snapshots
        if ResearchDatasetId.INDEX_DAILY in mapping
    ]
    valuation_windows = [
        mapping[ResearchDatasetId.DAILY_BASIC]
        for mapping in snapshots
        if ResearchDatasetId.DAILY_BASIC in mapping
    ]
    assert equity_windows and max(map(len, equity_windows)) == 251
    adjustment_windows = [
        mapping[ResearchDatasetId.ADJ_FACTOR]
        for mapping in snapshots
        if ResearchDatasetId.ADJ_FACTOR in mapping
    ]
    assert sorted(map(len, adjustment_windows)) == [82, 82, 82, 251]
    assert index_windows and max(map(len, index_windows)) == 251
    assert valuation_windows and len(max(valuation_windows, key=len)) == 300
    assert summary.as_of.isoformat() == "2026-07-13T23:59:59+08:00"
    assert summary.failed_feature_sets == ()
    assert summary.committed_feature_sets == (
        "market_context",
        "sector_hotspot",
        "stock_trading_context",
        "price_analysis_context",
    )
    assert [call["formula_version"] for call in warehouse.commits] == [
        "market-context-v3",
        "sector-hotspot-v3",
        "stock-trading-context-v2",
        "price-analysis-context-v1",
    ]
    assert [call["entity_key"] for call in warehouse.commits] == [
        "analysis_date",
        ("analysis_date", "group_type", "group_code"),
        ("analysis_date", "ts_code"),
        ("analysis_date", "ts_code"),
    ]
    assert captured["sector"][6].empty
    assert captured["stock"][1]["trade_date"].nunique() == 250
    assert captured["price"][0]["trade_date"].nunique() == 251
    assert captured["price"][1]["trade_date"].nunique() == 251
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
    price_manifest = warehouse.commits[3]["input_manifest"]["fact_snapshot"]
    price_index_partitions = [
        item for item in price_manifest["partitions"]
        if item["dataset"] == ResearchDatasetId.INDEX_DAILY.value
    ]
    assert len(price_index_partitions) == 251


def test_job_persists_scenario_ready_price_context_from_251_sessions(
    tmp_path: Path, monkeypatch
) -> None:
    import stock_analyzer.ops.research_features as job

    dates = [value.date() for value in pd.bdate_range(end=ANALYSIS_DATE, periods=300)]
    warehouse = FakeWarehouse(tmp_path, dates)
    _WAREHOUSES[tmp_path] = warehouse
    captured: dict[str, tuple] = {}
    monkeypatch.setattr(job, "ResearchQuery", FakeQuery)
    monkeypatch.setattr(job, "DerivedFeatureStore", FakeStore)
    monkeypatch.setattr(job, "compute_market_context_features", _simple_market)
    monkeypatch.setattr(job, "compute_hotspot_features", _simple_sector)
    monkeypatch.setattr(job, "compute_stock_context_features", _simple_stock)
    monkeypatch.setattr(
        job,
        "compute_price_analysis_features",
        _capture_price(captured),
    )

    summary = job.run_research_features(warehouse, ANALYSIS_DATE)

    price_commit = next(
        call
        for call in warehouse.commits
        if call["feature_set"] == "price_analysis_context"
    )
    price_snapshot = next(
        call[1]
        for call in warehouse.calls
        if call[0] == "snapshot"
        and len(call[1].get(ResearchDatasetId.EQUITY_DAILY, ())) == 251
    )
    assert summary.price_rows == 1
    assert price_commit["formula_version"] == "price-analysis-context-v1"
    assert price_commit["entity_key"] == ("analysis_date", "ts_code")
    assert len(price_snapshot[ResearchDatasetId.EQUITY_DAILY]) == 251
    assert len(price_snapshot[ResearchDatasetId.ADJ_FACTOR]) == 251
    assert len(price_snapshot[ResearchDatasetId.INDEX_DAILY]) == 251
    assert price_snapshot[ResearchDatasetId.STOCK_LIMIT] == tuple(
        value.isoformat() for value in dates[-251:]
    )
    price_equity, price_benchmark = captured["price"]
    assert price_equity["trade_date"].max() == ANALYSIS_DATE
    assert price_equity["up_limit"].notna().all()
    assert price_benchmark["trade_date"].nunique() == 251


def test_job_normalizes_equity_and_adjustment_trade_date_types(
    tmp_path: Path, monkeypatch
) -> None:
    import stock_analyzer.ops.research_features as job

    dates = [value.date() for value in pd.bdate_range(end=ANALYSIS_DATE, periods=300)]
    warehouse = FakeWarehouse(tmp_path, dates)
    warehouse.frames[ResearchDatasetId.ADJ_FACTOR]["trade_date"] = pd.to_datetime(
        warehouse.frames[ResearchDatasetId.ADJ_FACTOR]["trade_date"]
    )
    _WAREHOUSES[tmp_path] = warehouse
    captured: dict[str, tuple] = {}
    monkeypatch.setattr(job, "ResearchQuery", FakeQuery)
    monkeypatch.setattr(job, "DerivedFeatureStore", FakeStore)
    monkeypatch.setattr(job, "compute_market_context_features", _capture_market(captured))
    monkeypatch.setattr(job, "compute_hotspot_features", _capture_sector(captured))
    monkeypatch.setattr(job, "compute_stock_context_features", _capture_stock(captured))

    summary = job.run_research_features(warehouse, ANALYSIS_DATE)

    assert summary.failed_feature_sets == ()
    assert set(captured["market"][0]["adj_factor"]) == {1.0}


def test_job_is_idempotent_and_only_related_manifest_changes_recompute(
    tmp_path: Path, monkeypatch
) -> None:
    import stock_analyzer.ops.research_features as job

    dates = [value.date() for value in pd.bdate_range(end=ANALYSIS_DATE, periods=300)]
    warehouse = FakeWarehouse(tmp_path, dates)
    _WAREHOUSES[tmp_path] = warehouse
    monkeypatch.setattr(job, "ResearchQuery", FakeQuery)
    monkeypatch.setattr(job, "DerivedFeatureStore", FakeStore)
    counts = {"market": 0, "sector": 0, "stock": 0, "price": 0}
    monkeypatch.setattr(job, "compute_market_context_features", _counted(counts, "market", _simple_market))
    monkeypatch.setattr(job, "compute_hotspot_features", _counted(counts, "sector", _simple_sector))
    monkeypatch.setattr(job, "compute_stock_context_features", _counted(counts, "stock", _simple_stock))
    monkeypatch.setattr(job, "compute_price_analysis_features", _counted(counts, "price", _simple_price))

    first = job.run_research_features(warehouse, ANALYSIS_DATE)
    second = job.run_research_features(warehouse, ANALYSIS_DATE)
    warehouse.revisions[ResearchDatasetId.THEME_DAILY.value] = "revised"
    third = job.run_research_features(warehouse, ANALYSIS_DATE)

    assert first.committed_feature_sets == (
        "market_context", "sector_hotspot", "stock_trading_context",
        "price_analysis_context"
    )
    assert second.skipped_feature_sets == (
        "market_context", "sector_hotspot", "stock_trading_context",
        "price_analysis_context"
    )
    assert third.committed_feature_sets == ("sector_hotspot",)
    assert third.skipped_feature_sets == (
        "market_context", "stock_trading_context", "price_analysis_context"
    )
    assert counts == {"market": 1, "sector": 2, "stock": 1, "price": 1}


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
        ("sector_hotspot", ANALYSIS_DATE, "sector-hotspot-v3")
    ]["frame"].copy()
    warehouse.revisions[ResearchDatasetId.EQUITY_DAILY.value] = "new-equity"

    def fail_sector(*args, **kwargs):
        raise RuntimeError("sector formula failed")

    monkeypatch.setattr(job, "compute_hotspot_features", fail_sector)
    summary = job.run_research_features(warehouse, ANALYSIS_DATE)

    assert summary.failed_feature_sets == ("sector_hotspot",)
    assert "sector formula failed" in summary.plain_language_summary
    pd.testing.assert_frame_equal(
        warehouse.current[("sector_hotspot", ANALYSIS_DATE, "sector-hotspot-v3")]["frame"],
        previous_sector,
    )
    assert summary.committed_feature_sets == (
        "market_context", "stock_trading_context", "price_analysis_context"
    )


def test_each_feature_uses_its_own_exact_materialized_snapshot(
    tmp_path: Path, monkeypatch
) -> None:
    import stock_analyzer.ops.research_features as job

    dates = [value.date() for value in pd.bdate_range(end=ANALYSIS_DATE, periods=300)]
    warehouse = FakeWarehouse(tmp_path, dates)
    _WAREHOUSES[tmp_path] = warehouse
    captured = {}
    monkeypatch.setattr(job, "ResearchQuery", FakeQuery)
    monkeypatch.setattr(job, "DerivedFeatureStore", FakeStore)

    def market_then_revise(*args, **kwargs):
        warehouse.frames[ResearchDatasetId.EQUITY_DAILY].loc[:, "close"] = 20.0
        warehouse.revisions[ResearchDatasetId.EQUITY_DAILY.value] = "revision-2"
        return _simple_market()

    monkeypatch.setattr(job, "compute_market_context_features", market_then_revise)
    monkeypatch.setattr(job, "compute_hotspot_features", _capture_sector(captured))
    monkeypatch.setattr(job, "compute_stock_context_features", _capture_stock(captured))

    summary = job.run_research_features(warehouse, ANALYSIS_DATE)

    assert summary.failed_feature_sets == ()
    assert set(captured["sector"][0]["close"].unique()) == {20.0}
    assert set(captured["stock"][0]["close"].unique()) == {20.0}
    sector_manifest = warehouse.commits[1]["input_manifest"]["fact_snapshot"]
    assert {
        item["resolved_content_hash"]
        for item in sector_manifest["partitions"]
        if item["dataset"] == ResearchDatasetId.EQUITY_DAILY.value
    } == {"revision-2"}


def test_minute_partition_invisible_or_partial_is_declared(
    tmp_path: Path, monkeypatch
) -> None:
    import stock_analyzer.ops.research_features as job

    dates = [value.date() for value in pd.bdate_range(end=ANALYSIS_DATE, periods=300)]

    def run_case(root: Path, *, hidden: bool):
        warehouse = FakeWarehouse(root, dates)
        warehouse.partitions[ResearchDatasetId.MINUTE_BAR] = [
            ANALYSIS_DATE.isoformat()
        ]
        warehouse.frames[ResearchDatasetId.MINUTE_BAR] = pd.DataFrame([
            {
                "trade_date": ANALYSIS_DATE,
                "instrument_code": "000001.SZ",
                "minute": "2026-07-13T01:30:00+00:00",
                "frequency": "1min",
                "close": 10.0,
                "amount": 1000.0,
            }
        ])
        if hidden:
            warehouse.hidden_datasets.add(ResearchDatasetId.MINUTE_BAR)
        _WAREHOUSES[root] = warehouse
        monkeypatch.setattr(job, "ResearchQuery", FakeQuery)
        monkeypatch.setattr(job, "DerivedFeatureStore", FakeStore)
        monkeypatch.setattr(job, "compute_market_context_features", _simple_market)
        monkeypatch.setattr(job, "compute_hotspot_features", _simple_sector)
        monkeypatch.setattr(job, "compute_stock_context_features", _simple_stock)
        job.run_research_features(warehouse, ANALYSIS_DATE)
        return next(
            call for call in warehouse.commits
            if call["feature_set"] == "sector_hotspot"
        )

    invisible = run_case(tmp_path / "invisible", hidden=True)
    partial = run_case(tmp_path / "partial", hidden=False)

    assert any("截止时点" in text for text in invisible["limitations"])
    assert any("覆盖不完整" in text for text in partial["limitations"])


def test_summary_counts_catalog_groups_without_public_membership(
    tmp_path: Path, monkeypatch
) -> None:
    import stock_analyzer.ops.research_features as job

    dates = [value.date() for value in pd.bdate_range(end=ANALYSIS_DATE, periods=300)]
    warehouse = FakeWarehouse(tmp_path, dates)
    _WAREHOUSES[tmp_path] = warehouse
    monkeypatch.setattr(job, "ResearchQuery", FakeQuery)
    monkeypatch.setattr(job, "DerivedFeatureStore", FakeStore)
    monkeypatch.setattr(job, "compute_market_context_features", _simple_market)
    monkeypatch.setattr(
        job,
        "compute_hotspot_features",
        lambda *args, **kwargs: pd.DataFrame([
            {
                "analysis_date": ANALYSIS_DATE,
                "group_type": "theme",
                "group_code": "EMPTY",
                "coverage_status": "limited_no_membership",
                "intraday_status": "limited",
            }
        ]),
    )
    monkeypatch.setattr(job, "compute_stock_context_features", _simple_stock)

    summary = job.run_research_features(warehouse, ANALYSIS_DATE)

    assert summary.sector_no_membership_count == 1
    assert "1 个行业/主题因未公开成分" in summary.plain_language_summary


def _fact_frames(dates: list[date]) -> dict[ResearchDatasetId, pd.DataFrame]:
    rows = [{"exchange": "SSE", "cal_date": day, "is_open": True} for day in dates]
    equity = pd.DataFrame(
        [{"trade_date": day, "ts_code": "000001.SZ", "open": 10.0, "high": 10.5,
          "low": 9.8, "close": 10.2, "amount": 1_000_000.0} for day in dates]
    )
    adjustments = pd.DataFrame(
        [{"trade_date": day, "ts_code": "000001.SZ", "adj_factor": 1.0}
         for day in dates]
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
             "list_status": "L", "market": "主板", "exchange": "SZSE", "name": "平安银行"}
        ]),
        ResearchDatasetId.EQUITY_DAILY: equity,
        ResearchDatasetId.ADJ_FACTOR: adjustments,
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


def _capture_price(captured):
    def compute(equity, benchmark, **kwargs):
        captured["price"] = (equity, benchmark)
        return _simple_price(equity, benchmark, **kwargs)
    return compute


def _simple_market(*args, **kwargs):
    return pd.DataFrame([{"analysis_date": ANALYSIS_DATE, "coverage_status": "complete"}])


def _simple_sector(*args, **kwargs):
    return pd.DataFrame([
        {
            "analysis_date": ANALYSIS_DATE,
            "group_type": "industry",
            "group_code": "801010.SI",
            "coverage_status": "complete_with_declared_gaps",
            "intraday_status": "limited",
            "limitation_notes": "minute data unavailable",
        }
    ])


def _simple_stock(*args, **kwargs):
    return pd.DataFrame([
        {"analysis_date": ANALYSIS_DATE, "ts_code": "000001.SZ",
         "coverage_status": "complete_with_declared_gaps",
         "limitation_notes": "trader identity unavailable"}
    ])


def _simple_price(*args, **kwargs):
    return pd.DataFrame([
        {"analysis_date": ANALYSIS_DATE, "ts_code": "000001.SZ",
         "coverage_status": "complete"}
    ])


def _counted(counts, label, function):
    def compute(*args, **kwargs):
        counts[label] += 1
        return function(*args, **kwargs)
    return compute
