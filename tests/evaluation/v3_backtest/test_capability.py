from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from stock_analyzer.evaluation.v3_backtest import capability as capability_module
from stock_analyzer.evaluation.v3_backtest.calendar import build_frozen_calendar
from stock_analyzer.evaluation.v3_backtest.capability import (
    CapabilityMatrix,
    RouteCapability,
    WorkspacePaths,
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


def test_prepare_rejects_root_other_than_frozen_usb(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    root = tmp_path / "mac-experiment"
    monkeypatch.setenv("V3_BACKTEST_ROOT", str(root))
    monkeypatch.setenv("TMPDIR", str(root / "tmp"))
    monkeypatch.setenv("DUCKDB_TMPDIR", str(root / "duckdb-tmp"))

    with pytest.raises(ValueError, match="approved U-disk experiment root"):
        prepare_backtest_workspace(root)

    assert not root.exists()


def test_workspace_paths_rejects_forged_mac_root(tmp_path: Path):
    root = tmp_path / "forged"

    with pytest.raises(ValueError, match="approved U-disk experiment root"):
        WorkspacePaths(root=root, directories=(root / "preflight",))


def test_both_preflight_write_layers_reject_paths_outside_usb_root(
    tmp_path: Path,
):
    root = tmp_path / "forged"
    workspace = object.__new__(WorkspacePaths)
    object.__setattr__(workspace, "root", root)
    object.__setattr__(workspace, "directories", (root / "preflight",))
    fingerprint = fingerprint_mac_warehouse(_minimal_warehouse(tmp_path))

    with pytest.raises(ValueError, match="approved U-disk experiment root"):
        write_preflight_receipts(workspace, object(), fingerprint)
    with pytest.raises(ValueError, match="approved U-disk experiment root"):
        capability_module._atomic_write_json(root / "escape.json", {"bad": True})

    assert not root.exists()


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
        covers_required_formations=True,
        coverage_semantics={"synthetic": "formation_sessions"},
        internal_recall_only=internal_recall,
        evidence_hashes=evidence_hashes,
    )


def _full_matrix() -> CapabilityMatrix:
    return CapabilityMatrix(
        routes={route: _capability(route) for route in DiscoveryRoute}
    )


def test_any_structurally_missing_required_route_forces_partial(tmp_path: Path):
    receipt = freeze_capability_matrix(_audited_matrix(tmp_path))

    assert receipt.experiment_scope == "partial"
    assert receipt.full_v3_status == "not_executable"
    assert receipt.routes["industry_cycle"].can_enter_ten is False
    assert (
        receipt.routes["industry_cycle"].execution_status
        == "not_executable_with_local_data"
    )


def test_intentional_internal_recall_routes_are_attested_from_source(tmp_path: Path):
    receipt = _audited_matrix(tmp_path).freeze()

    assert receipt.experiment_scope == "partial"
    assert receipt.full_v3_status == "not_executable"
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


def test_ready_or_enter_ten_requires_exhaustive_enumeration():
    with pytest.raises(ValueError, match="enumerate"):
        _capability(
            DiscoveryRoute.EARNINGS,
            can_enumerate_all=False,
            can_form_ready_card=True,
            can_enter_ten=True,
        )


def test_structural_missing_fields_cannot_be_marked_ready():
    with pytest.raises(ValueError, match="missing_fields"):
        _capability(
            DiscoveryRoute.EARNINGS,
            can_form_ready_card=True,
            can_enter_ten=True,
            missing_fields=("earnings.operating_value",),
        )


def test_synthetic_full_matrix_cannot_freeze_from_arbitrary_hashes():
    with pytest.raises(ValueError, match="audit-produced evidence"):
        _full_matrix().freeze()


def test_audit_seal_rejects_route_evidence_replacement(tmp_path: Path):
    warehouse = _minimal_warehouse(tmp_path)
    route_source = tmp_path / "routes-audited.py"
    route_source.write_text(
        _admission_source(
            DiscoveryRoute.EARNINGS,
            "_earnings_leads",
            "EARNINGS_REVALUATION",
        ),
        encoding="utf-8",
    )
    matrix = audit_local_capability_matrix(
        warehouse,
        routes_source=route_source,
        warehouse_fingerprint=fingerprint_mac_warehouse(warehouse),
    )
    routes = dict(matrix.routes)
    routes[DiscoveryRoute.EARNINGS] = replace(
        routes[DiscoveryRoute.EARNINGS],
        evidence_hashes=("b" * 64,),
    )

    with pytest.raises(ValueError, match="audit evidence changed"):
        replace(matrix, routes=routes).freeze()


def test_missing_evidence_hash_prevents_freeze(tmp_path: Path):
    matrix = _audited_matrix(tmp_path)
    routes = dict(matrix.routes)
    routes[DiscoveryRoute.EARNINGS] = replace(
        routes[DiscoveryRoute.EARNINGS],
        evidence_hashes=(),
    )

    with pytest.raises(ValueError, match="evidence hash"):
        replace(matrix, routes=routes).freeze()


def test_freeze_requires_exactly_six_routes(tmp_path: Path):
    matrix = _audited_matrix(tmp_path)
    routes = dict(matrix.routes)
    routes.pop(DiscoveryRoute.DISTRESS_REPAIR)

    with pytest.raises(ValueError, match="exactly the six"):
        replace(matrix, routes=routes).freeze()


def test_prepare_workspace_requires_pinned_temp_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    workspace = _approved_workspace(tmp_path, monkeypatch)
    root = workspace.root

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
    root = (tmp_path / "approved-experiment").resolve()
    monkeypatch.setattr(capability_module, "_APPROVED_EXPERIMENT_ROOT", root)
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


def test_phase_guard_recomputes_fingerprint_after_read_only_work(tmp_path: Path):
    warehouse = _minimal_warehouse(tmp_path)
    guard = capability_module.WarehousePhaseGuard.capture(warehouse)

    def mutate_warehouse() -> str:
        (warehouse / "facts" / "mutation.txt").write_text("changed", encoding="utf-8")
        return "untrusted"

    with pytest.raises(RuntimeError, match="warehouse fingerprint changed"):
        guard.run_phase("mutating-phase", mutate_warehouse)


def test_phase_guard_rechecks_after_operation_mutates_then_raises(tmp_path: Path):
    warehouse = _minimal_warehouse(tmp_path)
    guard = capability_module.WarehousePhaseGuard.capture(warehouse)

    def mutate_then_raise() -> None:
        (warehouse / "facts" / "mutation.txt").write_text("changed", encoding="utf-8")
        raise ValueError("operation exploded")

    with pytest.raises(ExceptionGroup) as caught:
        guard.run_phase("raising-mutating-phase", mutate_then_raise)

    messages = tuple(str(error) for error in caught.value.exceptions)
    assert any("operation exploded" in message for message in messages)
    assert any("warehouse fingerprint changed" in message for message in messages)


def test_preflight_guard_rechecks_before_publishing_any_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    workspace = _approved_workspace(tmp_path, monkeypatch)
    warehouse = _minimal_warehouse(tmp_path)
    route_source = tmp_path / "routes-guarded.py"
    route_source.write_text(
        _admission_source(
            DiscoveryRoute.EARNINGS,
            "_earnings_leads",
            "EARNINGS_REVALUATION",
        ),
        encoding="utf-8",
    )
    guard = capability_module.WarehousePhaseGuard.capture(warehouse)
    matrix = guard.run_phase(
        "capability-audit",
        lambda: audit_local_capability_matrix(
            warehouse,
            routes_source=route_source,
            warehouse_fingerprint=guard.before,
        ),
    )
    (warehouse / "derived" / "post-audit-mutation.txt").write_text(
        "changed",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="warehouse fingerprint changed"):
        guard.publish_preflight(workspace, matrix.freeze())

    assert not (workspace.preflight / "capability-matrix.json").exists()
    assert not (
        workspace.preflight / "mac-warehouse-fingerprint-before.json"
    ).exists()


def test_preflight_pair_publish_failure_leaves_neither_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    workspace = _approved_workspace(tmp_path, monkeypatch)
    warehouse = _minimal_warehouse(tmp_path)
    guard = capability_module.WarehousePhaseGuard.capture(warehouse)
    receipt = guard.run_phase(
        "capability-audit",
        lambda: audit_local_capability_matrix(
            warehouse,
            routes_source=_real_routes_source(),
            warehouse_fingerprint=guard.before,
            _test_formation_sessions=_formation_sessions(),
        ),
    ).freeze()
    real_replace = capability_module.os.replace

    def fail_second_receipt(source: object, destination: object) -> None:
        if Path(destination).name == "mac-warehouse-fingerprint-before.json":
            raise OSError("injected second receipt publish failure")
        real_replace(source, destination)

    monkeypatch.setattr(capability_module.os, "replace", fail_second_receipt)

    with pytest.raises(OSError, match="second receipt publish failure"):
        guard.publish_preflight(workspace, receipt)

    assert not (workspace.preflight / "capability-matrix.json").exists()
    assert not (
        workspace.preflight / "mac-warehouse-fingerprint-before.json"
    ).exists()
    assert not tuple(workspace.preflight.glob(".receipt-pair.*"))


def test_local_audit_uses_real_route_branches_and_deep_read_fields(tmp_path: Path):
    warehouse = _minimal_warehouse(tmp_path)
    fingerprint = fingerprint_mac_warehouse(warehouse)

    receipt = audit_local_capability_matrix(
        warehouse,
        routes_source=_real_routes_source(),
        warehouse_fingerprint=fingerprint,
        _test_formation_sessions=_formation_sessions(),
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
    assert receipt.routes["industry_cycle"].can_enumerate_all is True
    assert receipt.routes["industry_cycle"].missing_fields[0] == (
        "industry_cycle.lead_implementation"
    )
    assert receipt.routes["distress_repair"].execution_status == (
        "not_executable_with_local_data"
    )
    assert all(item.evidence_hashes for item in receipt.routes.values())


@pytest.mark.parametrize(
    ("route", "helper", "opportunity"),
    (
        (
            DiscoveryRoute.INDUSTRY_CYCLE,
            "_cycle_leads",
            "SUPPLY_DEMAND_CYCLE",
        ),
        (
            DiscoveryRoute.DISTRESS_REPAIR,
            "_repair_leads",
            "DISTRESS_REVERSAL",
        ),
    ),
)
def test_new_admission_branch_and_local_evidence_can_become_executable(
    tmp_path: Path,
    route: DiscoveryRoute,
    helper: str,
    opportunity: str,
):
    warehouse = _minimal_warehouse(tmp_path)
    if route is DiscoveryRoute.INDUSTRY_CYCLE:
        _add_cycle_ready_evidence(warehouse)
    else:
        _add_distress_ready_evidence(warehouse)
    route_source = tmp_path / f"routes-{route.value}.py"
    route_source.write_text(
        _admission_source(route, helper, opportunity),
        encoding="utf-8",
    )

    receipt = audit_local_capability_matrix(
        warehouse,
        routes_source=route_source,
        warehouse_fingerprint=fingerprint_mac_warehouse(warehouse),
    ).freeze()

    assert receipt.routes[route.value].can_form_ready_card is True
    assert receipt.routes[route.value].can_enter_ten is True
    assert receipt.routes[route.value].execution_status == "executable_ready"


def test_hotspot_status_follows_non_internal_admission_not_route_name(tmp_path: Path):
    warehouse = _minimal_warehouse(tmp_path)
    route_source = tmp_path / "routes-hotspot-ready.py"
    route_source.write_text(
        _admission_source(
            DiscoveryRoute.HOTSPOT,
            "_hotspot_leads",
            "INDUSTRY_TREND",
        ),
        encoding="utf-8",
    )

    receipt = audit_local_capability_matrix(
        warehouse,
        routes_source=route_source,
        warehouse_fingerprint=fingerprint_mac_warehouse(warehouse),
    ).freeze()

    assert receipt.routes["hotspot"].can_form_ready_card is True
    assert receipt.routes["hotspot"].can_enter_ten is True


def test_ready_route_requires_attested_usable_non_internal_eligibility_path(
    tmp_path: Path,
):
    warehouse = _minimal_warehouse(tmp_path)
    route_source = tmp_path / "routes-forged-eligibility.py"
    source = _admission_source(
        DiscoveryRoute.EARNINGS,
        "_earnings_leads",
        "EARNINGS_REVALUATION",
    ).replace(
        "eligible_for_ten=any(not item.internal_only for item in usable)",
        "eligible_for_ten=True",
    )
    route_source.write_text(source, encoding="utf-8")

    receipt = audit_local_capability_matrix(
        warehouse,
        routes_source=route_source,
        warehouse_fingerprint=fingerprint_mac_warehouse(warehouse),
    ).freeze()

    assert receipt.routes["earnings"].can_enter_ten is False
    assert "routes.eligible_for_ten_attestation" in receipt.routes[
        "earnings"
    ].missing_fields


def test_unknown_usable_expression_fails_closed(tmp_path: Path):
    warehouse = _minimal_warehouse(tmp_path)
    route_source = tmp_path / "routes-unknown-usable.py"
    source = _admission_source(
        DiscoveryRoute.EARNINGS,
        "_earnings_leads",
        "EARNINGS_REVALUATION",
    ).replace(
        "        usable=True,\n",
        "        usable=runtime_value_that_is_always_false,\n",
    )
    route_source.write_text(source, encoding="utf-8")

    receipt = audit_local_capability_matrix(
        warehouse,
        routes_source=route_source,
        warehouse_fingerprint=fingerprint_mac_warehouse(warehouse),
        _test_formation_sessions=_formation_sessions(),
    ).freeze()

    earnings = receipt.routes["earnings"]
    assert earnings.can_form_ready_card is False
    assert "earnings.usable_for_decision_attestation" in earnings.missing_fields


def test_unreachable_lead_call_fails_closed(tmp_path: Path):
    warehouse = _minimal_warehouse(tmp_path)
    route_source = tmp_path / "routes-unreachable-lead.py"
    source = _admission_source(
        DiscoveryRoute.EARNINGS,
        "_earnings_leads",
        "EARNINGS_REVALUATION",
    ).replace(
        "def _earnings_leads():\n    return (_lead(",
        "def _earnings_leads():\n    if False:\n        return (_lead(",
    )
    route_source.write_text(source, encoding="utf-8")

    receipt = audit_local_capability_matrix(
        warehouse,
        routes_source=route_source,
        warehouse_fingerprint=fingerprint_mac_warehouse(warehouse),
        _test_formation_sessions=_formation_sessions(),
    ).freeze()

    earnings = receipt.routes["earnings"]
    assert earnings.can_form_ready_card is False
    assert "earnings.lead_implementation" in earnings.missing_fields


def test_daily_route_coverage_requires_every_one_of_144_formation_sessions(
    tmp_path: Path,
):
    sessions = _formation_sessions()
    warehouse = _minimal_warehouse(tmp_path)
    _write_rows(
        warehouse / "derived" / "sector_hotspot" / "unpartitioned",
        _hotspot_rows(tuple(day for day in sessions if day != sessions[72])),
    )
    route_source = tmp_path / "routes-hotspot-internal.py"
    route_source.write_text(
        _admission_source(
            DiscoveryRoute.HOTSPOT,
            "_hotspot_leads",
            "INDUSTRY_TREND",
            internal_only=True,
        ),
        encoding="utf-8",
    )

    receipt = audit_local_capability_matrix(
        warehouse,
        routes_source=route_source,
        warehouse_fingerprint=fingerprint_mac_warehouse(warehouse),
        _test_formation_sessions=sessions,
    ).freeze()
    hotspot = receipt.routes["hotspot"]

    assert hotspot.coverage_start == sessions[0]
    assert hotspot.coverage_end == sessions[-1]
    assert hotspot.covers_required_formations is False
    assert hotspot.can_enumerate_all is False
    assert "sector_hotspot.formation_session_coverage" in hotspot.missing_fields


def test_available_at_values_not_partition_names_define_route_coverage(tmp_path: Path):
    sessions = _formation_sessions()
    warehouse = _minimal_warehouse(tmp_path)
    for dataset, value_field in (
        ("earnings_forecast", "p_change_min"),
        ("earnings_express", "revenue"),
        ("income_statement", "revenue"),
    ):
        _write_rows(
            warehouse / "facts" / dataset / "unpartitioned",
            (
                {
                    "ts_code": "000001.SZ",
                    "report_period": "2025-09-30",
                    "available_at": "2026-07-01T18:00:00+08:00",
                    value_field: 100.0,
                },
                {
                    "ts_code": "000001.SZ",
                    "report_period": "2026-03-31",
                    "available_at": "2026-07-02T18:00:00+08:00",
                    value_field: 110.0,
                },
            ),
        )
    route_source = tmp_path / "routes-earnings.py"
    route_source.write_text(
        _admission_source(
            DiscoveryRoute.EARNINGS,
            "_earnings_leads",
            "EARNINGS_REVALUATION",
        ),
        encoding="utf-8",
    )

    receipt = audit_local_capability_matrix(
        warehouse,
        routes_source=route_source,
        warehouse_fingerprint=fingerprint_mac_warehouse(warehouse),
        _test_formation_sessions=sessions,
    ).freeze()
    earnings = receipt.routes["earnings"]

    assert earnings.coverage_start == date(2026, 7, 1)
    assert earnings.coverage_end == date(2026, 7, 2)
    assert earnings.covers_required_formations is False
    assert earnings.can_enter_ten is False


def test_non_daily_coverage_is_labeled_as_observed_range(tmp_path: Path):
    receipt = audit_local_capability_matrix(
        _minimal_warehouse(tmp_path),
        routes_source=_real_routes_source(),
        _test_formation_sessions=_formation_sessions(),
    ).freeze()

    earnings = receipt.routes["earnings"].to_record()
    assert earnings["coverage_semantics"] == {
        "earnings_express": "observed_range",
        "earnings_forecast": "observed_range",
        "income_statement": "observed_range",
    }


def test_correct_endpoints_but_wrong_calendar_member_is_rejected(tmp_path: Path):
    warehouse = _minimal_warehouse(tmp_path)
    wrong = list(_formation_sessions())
    wrong[45] = date(2026, 1, 3)
    wrong = sorted(wrong)
    assert len(wrong) == 144
    assert wrong[0] == FORMATION_START
    assert wrong[-1] == FORMATION_END

    with pytest.raises(ValueError, match="authoritative frozen calendar"):
        audit_local_capability_matrix(
            warehouse,
            routes_source=_real_routes_source(),
            _test_formation_sessions=wrong,
        )


def test_appledouble_parquet_sidecar_is_never_opened_by_pyarrow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    warehouse = _minimal_warehouse(tmp_path)
    sidecar = (
        warehouse
        / "facts"
        / "earnings_forecast"
        / "unpartitioned"
        / "._data.parquet"
    )
    sidecar.write_bytes(b"AppleDouble, not parquet")
    fingerprint = fingerprint_mac_warehouse(warehouse)
    route_source = tmp_path / "routes-appledouble.py"
    route_source.write_text(
        _admission_source(
            DiscoveryRoute.EARNINGS,
            "_earnings_leads",
            "EARNINGS_REVALUATION",
        ),
        encoding="utf-8",
    )
    opened: list[Path] = []
    real_parquet_file = pq.ParquetFile

    def record_open(path: Path, *args: object, **kwargs: object):
        opened.append(Path(path))
        return real_parquet_file(path, *args, **kwargs)

    monkeypatch.setattr(capability_module.pq, "ParquetFile", record_open)

    audit_local_capability_matrix(
        warehouse,
        routes_source=route_source,
        warehouse_fingerprint=fingerprint,
        _test_formation_sessions=_formation_sessions(),
    ).freeze()

    assert opened
    assert sidecar not in opened
    assert all(not path.name.startswith("._") for path in opened)


def test_preflight_receipts_are_written_only_under_experiment_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    workspace = _approved_workspace(tmp_path, monkeypatch)
    root = workspace.root
    warehouse = _minimal_warehouse(tmp_path)
    guard = capability_module.WarehousePhaseGuard.capture(warehouse)
    receipt = guard.run_phase(
        "capability-audit",
        lambda: audit_local_capability_matrix(
            warehouse,
            routes_source=_real_routes_source(),
            warehouse_fingerprint=guard.before,
            _test_formation_sessions=_formation_sessions(),
        ),
    ).freeze()

    capability_path, fingerprint_path = write_preflight_receipts(
        workspace,
        receipt,
        guard.before,
        guard=guard,
    )

    assert capability_path == root / "preflight" / "capability-matrix.json"
    assert fingerprint_path == (
        root / "preflight" / "mac-warehouse-fingerprint-before.json"
    )
    assert json.loads(capability_path.read_text(encoding="utf-8"))[
        "full_v3_status"
    ] == "not_executable"
    assert json.loads(fingerprint_path.read_text(encoding="utf-8"))[
        "research_duckdb"
    ]["sha256"] == guard.before.research_duckdb.sha256


def _minimal_warehouse(tmp_path: Path) -> Path:
    warehouse = tmp_path / "local_warehouse"
    (warehouse / "facts").mkdir(parents=True, exist_ok=True)
    (warehouse / "derived").mkdir(parents=True, exist_ok=True)
    (warehouse / "research.duckdb").write_bytes(b"database")
    sessions = _formation_sessions()

    _write_rows(
        warehouse / "derived" / "sector_hotspot" / "unpartitioned",
        _hotspot_rows(sessions),
    )
    _write_rows(
        warehouse / "derived" / "stock_trading_context" / "unpartitioned",
        tuple(
            {
                "ts_code": "000001.SZ",
                "analysis_date": day.isoformat(),
                "relative_return_20d": 0.1,
                "coverage_status": "complete",
            }
            for day in sessions
        ),
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
    for dataset, value_field in (
        ("earnings_forecast", "p_change_min"),
        ("earnings_express", "revenue"),
        ("income_statement", "revenue"),
    ):
        _write_rows(
            warehouse / "facts" / dataset / "unpartitioned",
            _periodic_rows(value_field),
        )
    _write_rows(
        warehouse / "facts" / "announcement" / "unpartitioned",
        tuple(
            {
                "announcement_id": f"A{index}",
                "ts_code": "000001.SZ",
                "announcement_time": f"{day.isoformat()}T18:00:00+08:00",
                "available_at": f"{day.isoformat()}T18:00:00+08:00",
                "title": "重大合同公告",
                "url": "https://example.invalid/a",
                "candidate_event_types": "major_contract",
            }
            for index, day in enumerate((sessions[0], sessions[-1]))
        ),
    )
    _write_rows(
        warehouse / "facts" / "industry_daily" / "unpartitioned",
        tuple(
            {
                "industry_code": "I1",
                "trade_date": day.isoformat(),
                "available_at": f"{day.isoformat()}T18:00:00+08:00",
                "close": 100.0,
            }
            for day in sessions
        ),
    )
    for dataset, value_field in (
        ("main_business", "bz_sales"),
        ("repurchase", "amount"),
        ("balance_sheet", "total_assets"),
        ("cash_flow", "n_cashflow_act"),
    ):
        _write_rows(
            warehouse / "facts" / dataset / "unpartitioned",
            _periodic_rows(value_field),
        )
    _write_rows(
        warehouse / "facts" / "trade_calendar" / "unpartitioned",
        tuple(
            {
                "exchange": "SSE",
                "cal_date": day.isoformat(),
                "is_open": True,
                "available_at": "2020-01-01T00:00:00+08:00",
            }
            for day in _open_sessions()
        ),
    )
    return warehouse


def _write_parquet(directory: Path, **values: object) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    table = pa.table({name: [value] for name, value in values.items()})
    pq.write_table(table, directory / "data.parquet")


def _write_rows(directory: Path, rows: tuple[dict[str, object], ...]) -> None:
    assert rows
    directory.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(list(rows)), directory / "data.parquet")


def _formation_sessions() -> tuple[date, ...]:
    return build_frozen_calendar(
        _open_sessions(),
        data_end=date(2026, 7, 17),
    ).mature


def _open_sessions() -> tuple[date, ...]:
    closed = {
        date(2026, 1, 1),
        date(2026, 1, 2),
        date(2026, 2, 16),
        date(2026, 2, 17),
        date(2026, 2, 18),
        date(2026, 2, 19),
        date(2026, 2, 20),
        date(2026, 2, 23),
        date(2026, 4, 6),
        date(2026, 5, 1),
        date(2026, 5, 4),
        date(2026, 5, 5),
        date(2026, 6, 19),
    }
    values: list[date] = []
    current = FORMATION_START
    while current <= date(2026, 7, 17):
        if current.weekday() < 5 and current not in closed:
            values.append(current)
        current += timedelta(days=1)
    sessions = tuple(values)
    assert len(sessions) == 174
    return sessions


def _hotspot_rows(sessions: tuple[date, ...]) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "analysis_date": day.isoformat(),
            "group_type": "industry",
            "group_code": "I1",
            "relative_return_20d": 0.1,
            "median_return_20d": 0.1,
            "breadth_20d": 0.7,
            "turnover_share_average_20d": 0.1,
            "top3_positive_contribution_1d": 0.2,
            "high_volume_low_progress_flag": False,
            "upper_wick_reversal_flag": False,
            "narrow_participation_flag": False,
            "turnover_return_divergence_flag": False,
            "coverage_status": "complete",
        }
        for day in sessions
    )


def _periodic_rows(value_field: str) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "ts_code": "000001.SZ",
            "report_period": (
                "2025-09-30" if day == FORMATION_START else "2026-03-31"
            ),
            "available_at": f"{day.isoformat()}T18:00:00+08:00",
            value_field: value,
        }
        for day, value in ((FORMATION_START, 100.0), (FORMATION_END, 110.0))
    )


def _approved_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> WorkspacePaths:
    root = (tmp_path / "approved-experiment").resolve()
    monkeypatch.setattr(
        capability_module,
        "_APPROVED_EXPERIMENT_ROOT",
        root,
        raising=False,
    )
    monkeypatch.setenv("V3_BACKTEST_ROOT", str(root))
    monkeypatch.setenv("TMPDIR", str(root / "tmp"))
    monkeypatch.setenv("DUCKDB_TMPDIR", str(root / "duckdb-tmp"))
    return prepare_backtest_workspace(root)


def _real_routes_source() -> Path:
    return Path(capability_module.__file__).with_name("routes.py")


def _audited_matrix(tmp_path: Path) -> CapabilityMatrix:
    warehouse = _minimal_warehouse(tmp_path)
    return audit_local_capability_matrix(
        warehouse,
        routes_source=_real_routes_source(),
        warehouse_fingerprint=fingerprint_mac_warehouse(warehouse),
        _test_formation_sessions=_formation_sessions(),
    )


def _add_cycle_ready_evidence(warehouse: Path) -> None:
    _write_rows(
        warehouse / "facts" / "industry_daily" / "unpartitioned",
        tuple(
            {
                "industry_code": "I1",
                "trade_date": day.isoformat(),
                "available_at": f"{day.isoformat()}T18:00:00+08:00",
                "demand_change": 1.0,
                "supply_change": -1.0,
                "price_change": 1.0,
                "inventory_change": -1.0,
                "policy_change": "supportive",
                "peer_evidence": "broad",
            }
            for day in _formation_sessions()
        ),
    )
    _write_rows(
        warehouse / "facts" / "main_business" / "unpartitioned",
        tuple(
            {**row, "company_sensitivity": "material"}
            for row in _periodic_rows("bz_sales")
        ),
    )


def _add_distress_ready_evidence(warehouse: Path) -> None:
    _write_rows(
        warehouse / "facts" / "repurchase" / "unpartitioned",
        tuple(
            {**row, "core_risk_mitigated": True}
            for row in _periodic_rows("amount")
        ),
    )
    for dataset, field in (
        ("income_statement", "revenue"),
        ("balance_sheet", "total_assets"),
        ("cash_flow", "n_cashflow_act"),
    ):
        _write_rows(
            warehouse / "facts" / dataset / "unpartitioned",
            tuple(
                {**row, "statement_improved": True}
                for row in _periodic_rows(field)
            ),
        )


def _admission_source(
    route: DiscoveryRoute,
    helper: str,
    opportunity: str,
    *,
    internal_only: bool = False,
) -> str:
    return f"""
def _lead(security_id, route, *, internal_only=False, usable=True, preliminary_opportunity=None):
    return Lead(
        security_id=security_id,
        route=route,
        internal_only=internal_only,
        usable=usable,
        preliminary_opportunity=preliminary_opportunity,
    )

def {helper}():
    return (_lead(
        "000001.SZ",
        DiscoveryRoute.{route.name},
        internal_only={internal_only!r},
        usable=True,
        preliminary_opportunity=OpportunityType.{opportunity},
    ),)

def _scan_route(route, view, policy):
    datasets = tuple(
        view.read(dataset, partitions)
        for dataset, partitions in policy.route_partitions[route].items()
    )
    if route is DiscoveryRoute.{route.name}:
        return {helper}()
    return ()

def _merge_leads(items):
    usable = tuple(
        item for item in items if item.evidence.usable_for_decision
    )
    return ResearchHypothesis(
        eligible_for_ten=any(not item.internal_only for item in usable),
    )
""".strip()
