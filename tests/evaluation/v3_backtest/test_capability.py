from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from stock_analyzer.evaluation.v3_backtest.capability import (
    CapabilityMatrix,
    RouteCapability,
    assert_warehouse_unchanged,
    audit_local_capability_matrix,
    fingerprint_mac_warehouse,
    freeze_capability_matrix,
    prepare_backtest_workspace,
    write_preflight_receipts,
)
from stock_analyzer.evaluation.v3_backtest.contracts import DiscoveryRoute


SHA256 = "a" * 64
FORMATION_START = date(2025, 10, 30)
FORMATION_END = date(2026, 6, 4)


def _capability(
    route: DiscoveryRoute,
    *,
    can_enumerate_all: bool = True,
    can_form_ready_card: bool | None = None,
    can_enter_ten: bool | None = None,
    missing_fields: tuple[str, ...] = (),
    evidence_hashes: tuple[str, ...] = (SHA256,),
) -> RouteCapability:
    internal_recall = route in {
        DiscoveryRoute.HOTSPOT,
        DiscoveryRoute.PRICE_ANOMALY,
    }
    ready = not internal_recall if can_form_ready_card is None else can_form_ready_card
    enter = ready if can_enter_ten is None else can_enter_ten
    return RouteCapability(
        route=route,
        can_enumerate_all=can_enumerate_all,
        can_form_ready_card=ready,
        can_enter_ten=enter,
        missing_fields=missing_fields,
        coverage_start=FORMATION_START,
        coverage_end=FORMATION_END,
        evidence_hashes=evidence_hashes,
    )


def _full_matrix() -> CapabilityMatrix:
    return CapabilityMatrix(
        routes={route: _capability(route) for route in DiscoveryRoute}
    )


def test_any_structurally_missing_required_route_forces_partial():
    matrix = _full_matrix()
    routes = dict(matrix.routes)
    routes[DiscoveryRoute.INDUSTRY_CYCLE] = _capability(
        DiscoveryRoute.INDUSTRY_CYCLE,
        can_form_ready_card=False,
        can_enter_ten=False,
        missing_fields=("industry_cycle.lead_implementation",),
    )

    receipt = freeze_capability_matrix(CapabilityMatrix(routes=routes))

    assert receipt.experiment_scope == "partial"
    assert receipt.full_v3_status == "not_executable"
    assert receipt.routes["industry_cycle"].can_enter_ten is False
    assert (
        receipt.routes["industry_cycle"].execution_status
        == "not_executable_with_local_data"
    )


def test_intentional_internal_recall_routes_do_not_make_full_matrix_partial():
    receipt = _full_matrix().freeze()

    assert receipt.experiment_scope == "full"
    assert receipt.full_v3_status == "executable"
    assert receipt.routes["hotspot"].execution_status == "executable_internal_recall"
    assert receipt.routes["price_anomaly"].can_enter_ten is False


def test_enumerable_route_without_ready_card_cannot_enter_ten():
    with pytest.raises(ValueError, match="ready card"):
        _capability(
            DiscoveryRoute.COMPANY_EVENT,
            can_form_ready_card=False,
            can_enter_ten=True,
        )


def test_internal_only_hypothesis_cannot_be_declared_ready():
    with pytest.raises(ValueError, match="internal recall"):
        _capability(
            DiscoveryRoute.HOTSPOT,
            can_form_ready_card=True,
            can_enter_ten=True,
        )


def test_missing_evidence_hash_prevents_freeze():
    matrix = _full_matrix()
    routes = dict(matrix.routes)
    routes[DiscoveryRoute.EARNINGS] = replace(
        routes[DiscoveryRoute.EARNINGS],
        evidence_hashes=(),
    )

    with pytest.raises(ValueError, match="evidence hash"):
        CapabilityMatrix(routes=routes).freeze()


def test_freeze_requires_exactly_six_routes():
    routes = dict(_full_matrix().routes)
    routes.pop(DiscoveryRoute.DISTRESS_REPAIR)

    with pytest.raises(ValueError, match="exactly the six"):
        CapabilityMatrix(routes=routes).freeze()


def test_prepare_workspace_requires_pinned_temp_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    root = tmp_path / "experiment"
    monkeypatch.setenv("V3_BACKTEST_ROOT", str(root))
    monkeypatch.setenv("TMPDIR", str(root / "tmp"))
    monkeypatch.setenv("DUCKDB_TMPDIR", str(root / "duckdb-tmp"))

    workspace = prepare_backtest_workspace()

    expected = {
        "preflight",
        "formation/snapshots",
        "formation/routes",
        "formation/evidence",
        "formation/judgments",
        "formation/projects",
        "formation/manifests",
        "outcomes",
        "statistics",
        "reports",
        "logs",
        "cache",
        "tmp",
        "duckdb-tmp",
    }
    assert workspace.root == root.resolve()
    assert expected == {
        path.relative_to(workspace.root).as_posix()
        for path in workspace.directories
    }
    assert all(path.is_dir() for path in workspace.directories)


def test_prepare_workspace_fails_closed_when_tmpdir_is_elsewhere(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    root = tmp_path / "experiment"
    monkeypatch.setenv("V3_BACKTEST_ROOT", str(root))
    monkeypatch.setenv("TMPDIR", str(tmp_path / "mac-tmp"))
    monkeypatch.setenv("DUCKDB_TMPDIR", str(root / "duckdb-tmp"))

    with pytest.raises(ValueError, match="TMPDIR"):
        prepare_backtest_workspace()

    assert not root.exists()


def test_warehouse_fingerprint_is_read_only_and_detects_change(tmp_path: Path):
    warehouse = tmp_path / "local_warehouse"
    (warehouse / "facts" / "dataset").mkdir(parents=True)
    (warehouse / "derived" / "feature").mkdir(parents=True)
    (warehouse / "facts" / "dataset" / "data.parquet").write_bytes(b"facts")
    (warehouse / "derived" / "feature" / "data.parquet").write_bytes(b"derived")
    database = warehouse / "research.duckdb"
    database.write_bytes(b"database")
    before_members = tuple(
        path.relative_to(warehouse).as_posix()
        for path in sorted(warehouse.rglob("*"))
    )

    before = fingerprint_mac_warehouse(warehouse)

    after_members = tuple(
        path.relative_to(warehouse).as_posix()
        for path in sorted(warehouse.rglob("*"))
    )
    assert after_members == before_members
    assert len(before.facts.tree_sha256) == 64
    assert before.research_duckdb.sha256 == hashlib.sha256(b"database").hexdigest()
    assert before.research_duckdb.size == len(b"database")
    assert before.research_duckdb.mtime_ns == database.stat().st_mtime_ns

    (warehouse / "facts" / "dataset" / "data.parquet").write_bytes(b"changed")
    after = fingerprint_mac_warehouse(warehouse)
    with pytest.raises(RuntimeError, match="warehouse fingerprint changed"):
        assert_warehouse_unchanged(before, after)


def test_local_audit_uses_real_route_branches_and_deep_read_fields(tmp_path: Path):
    warehouse = _minimal_warehouse(tmp_path)
    route_source = tmp_path / "routes.py"
    route_source.write_text(
        """
def _scan_route(route):
    if route is DiscoveryRoute.HOTSPOT:
        return _hotspot_leads()
    elif route is DiscoveryRoute.EARNINGS:
        return _earnings_leads()
    elif route is DiscoveryRoute.COMPANY_EVENT:
        return _event_leads()
    elif route is DiscoveryRoute.PRICE_ANOMALY:
        return _price_leads()
    return ()
""".strip(),
        encoding="utf-8",
    )
    fingerprint = fingerprint_mac_warehouse(warehouse)

    receipt = audit_local_capability_matrix(
        warehouse,
        routes_source=route_source,
        warehouse_fingerprint=fingerprint,
    ).freeze()

    assert receipt.experiment_scope == "partial"
    assert receipt.full_v3_status == "not_executable"
    assert receipt.routes["earnings"].can_enter_ten is True
    assert receipt.routes["hotspot"].can_form_ready_card is False
    assert receipt.routes["hotspot"].execution_status == "executable_internal_recall"
    event = receipt.routes["company_event"]
    assert event.can_enumerate_all is True
    assert event.can_form_ready_card is False
    assert set(event.missing_fields) >= {
        "announcement.body",
        "announcement.amount",
        "announcement.subject",
        "announcement.execution_conditions",
    }
    assert receipt.routes["industry_cycle"].can_enumerate_all is False
    assert receipt.routes["industry_cycle"].missing_fields[0] == (
        "industry_cycle.lead_implementation"
    )
    assert receipt.routes["distress_repair"].execution_status == (
        "not_executable_with_local_data"
    )
    assert all(item.evidence_hashes for item in receipt.routes.values())


def test_preflight_receipts_are_written_only_under_experiment_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    root = tmp_path / "experiment"
    monkeypatch.setenv("V3_BACKTEST_ROOT", str(root))
    monkeypatch.setenv("TMPDIR", str(root / "tmp"))
    monkeypatch.setenv("DUCKDB_TMPDIR", str(root / "duckdb-tmp"))
    workspace = prepare_backtest_workspace()
    warehouse = _minimal_warehouse(tmp_path)
    fingerprint = fingerprint_mac_warehouse(warehouse)
    receipt = _full_matrix().freeze()

    capability_path, fingerprint_path = write_preflight_receipts(
        workspace,
        receipt,
        fingerprint,
    )

    assert capability_path == root / "preflight" / "capability-matrix.json"
    assert fingerprint_path == (
        root / "preflight" / "mac-warehouse-fingerprint-before.json"
    )
    assert json.loads(capability_path.read_text(encoding="utf-8"))[
        "full_v3_status"
    ] == "executable"
    assert json.loads(fingerprint_path.read_text(encoding="utf-8"))[
        "research_duckdb"
    ]["sha256"] == fingerprint.research_duckdb.sha256


def _minimal_warehouse(tmp_path: Path) -> Path:
    warehouse = tmp_path / "local_warehouse"
    (warehouse / "facts").mkdir(parents=True, exist_ok=True)
    (warehouse / "derived").mkdir(parents=True, exist_ok=True)
    (warehouse / "research.duckdb").write_bytes(b"database")

    _write_parquet(
        warehouse / "derived" / "sector_hotspot" / "analysis_date=2025-10-30",
        group_type="industry",
        group_code="I1",
        relative_return_20d=0.1,
        median_return_20d=0.1,
        breadth_20d=0.7,
        turnover_share_average_20d=0.1,
        top3_positive_contribution_1d=0.2,
        high_volume_low_progress_flag=False,
        upper_wick_reversal_flag=False,
        narrow_participation_flag=False,
        turnover_return_divergence_flag=False,
        coverage_status="complete",
    )
    _write_parquet(
        warehouse / "derived" / "stock_trading_context" / "analysis_date=2026-06-04",
        ts_code="000001.SZ",
        analysis_date="2026-06-04",
        relative_return_20d=0.1,
        coverage_status="complete",
    )
    _write_parquet(
        warehouse / "facts" / "industry_member" / "classification_version=SW2021",
        ts_code="000001.SZ",
        industry_code="I1",
        valid_from="2020-01-01",
        valid_to=None,
        available_at="2020-01-01T00:00:00+08:00",
    )
    _write_parquet(
        warehouse / "facts" / "theme_member" / "catalog_version=official-theme-v1",
        ts_code="000001.SZ",
        theme_code="T1",
        valid_from="2020-01-01",
        valid_to=None,
        available_at="2020-01-01T00:00:00+08:00",
    )
    _write_parquet(
        warehouse / "facts" / "earnings_forecast" / "ann_month=2025-10",
        ts_code="000001.SZ",
        report_period="2025-09-30",
        available_at="2025-10-30T18:00:00+08:00",
        p_change_min=10.0,
    )
    _write_parquet(
        warehouse / "facts" / "earnings_express" / "ann_month=2026-04",
        ts_code="000001.SZ",
        report_period="2026-03-31",
        available_at="2026-04-30T18:00:00+08:00",
        revenue=100.0,
    )
    _write_parquet(
        warehouse / "facts" / "income_statement" / "report_period=2026-03-31",
        ts_code="000001.SZ",
        report_period="2026-03-31",
        available_at="2026-04-30T18:00:00+08:00",
        revenue=100.0,
    )
    _write_parquet(
        warehouse / "facts" / "announcement" / "announcement_month=2026-04",
        announcement_id="A1",
        ts_code="000001.SZ",
        announcement_time="2026-04-30T18:00:00+08:00",
        available_at="2026-04-30T18:00:00+08:00",
        title="重大合同公告",
        url="https://example.invalid/a",
        candidate_event_types="major_contract",
    )
    _write_parquet(
        warehouse / "facts" / "industry_daily" / "trade_date=2026-06-04",
        industry_code="I1",
        trade_date="2026-06-04",
        available_at="2026-06-04T18:00:00+08:00",
        close=100.0,
    )
    _write_parquet(
        warehouse / "facts" / "main_business" / "report_period=2026-03-31",
        ts_code="000001.SZ",
        report_period="2026-03-31",
        available_at="2026-04-30T18:00:00+08:00",
        bz_sales=100.0,
    )
    _write_parquet(
        warehouse / "facts" / "repurchase" / "announcement_month=2026-04",
        ts_code="000001.SZ",
        available_at="2026-04-30T18:00:00+08:00",
        amount=100.0,
    )
    _write_parquet(
        warehouse / "facts" / "balance_sheet" / "report_period=2026-03-31",
        ts_code="000001.SZ",
        report_period="2026-03-31",
        available_at="2026-04-30T18:00:00+08:00",
        total_assets=100.0,
    )
    _write_parquet(
        warehouse / "facts" / "cash_flow" / "report_period=2026-03-31",
        ts_code="000001.SZ",
        report_period="2026-03-31",
        available_at="2026-04-30T18:00:00+08:00",
        n_cashflow_act=10.0,
    )
    return warehouse


def _write_parquet(directory: Path, **values: object) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    table = pa.table({name: [value] for name, value in values.items()})
    pq.write_table(table, directory / "data.parquet")
