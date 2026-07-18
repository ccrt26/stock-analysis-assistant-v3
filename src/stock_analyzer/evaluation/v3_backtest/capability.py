"""Fail-closed capability and zero-write preflight for the isolated V3 replay."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, TypeVar
from zoneinfo import ZoneInfo

import pyarrow.parquet as pq

from stock_analyzer.evaluation.v3_backtest.contracts import DiscoveryRoute
from stock_analyzer.evaluation.v3_backtest.snapshots import tree_fingerprint


_APPROVED_EXPERIMENT_ROOT = Path(
    "/Volumes/ZHUTONG/股票分析助手-V3回测/"
    "2026-07-18-v3-continuous-multiblock"
).resolve(strict=False)
_FORMATION_START = date(2025, 10, 30)
_FORMATION_END = date(2026, 6, 4)
_FORMATION_COUNT = 144
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_AUDIT_TOKEN = object()
_RECEIPT_TOKEN = object()
_SHA256_LENGTH = 64
_WORKSPACE_DIRECTORIES = (
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
)
_PREFLIGHT_FILENAMES = frozenset(
    {"capability-matrix.json", "mac-warehouse-fingerprint-before.json"}
)
_ROUTE_DATASETS: Mapping[DiscoveryRoute, tuple[tuple[str, str], ...]] = (
    MappingProxyType(
        {
            DiscoveryRoute.HOTSPOT: (
                ("derived", "sector_hotspot"),
                ("facts", "industry_member"),
                ("facts", "theme_member"),
            ),
            DiscoveryRoute.EARNINGS: (
                ("facts", "earnings_forecast"),
                ("facts", "earnings_express"),
                ("facts", "income_statement"),
            ),
            DiscoveryRoute.COMPANY_EVENT: (("facts", "announcement"),),
            DiscoveryRoute.INDUSTRY_CYCLE: (
                ("facts", "industry_daily"),
                ("facts", "main_business"),
            ),
            DiscoveryRoute.DISTRESS_REPAIR: (
                ("facts", "repurchase"),
                ("facts", "income_statement"),
                ("facts", "balance_sheet"),
                ("facts", "cash_flow"),
            ),
            DiscoveryRoute.PRICE_ANOMALY: (
                ("derived", "stock_trading_context"),
            ),
        }
    )
)
_REQUIRED_FIELDS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "sector_hotspot": (
            "analysis_date",
            "group_type",
            "group_code",
            "relative_return_20d",
            "median_return_20d",
            "breadth_20d",
            "turnover_share_average_20d",
            "top3_positive_contribution_1d",
            "high_volume_low_progress_flag",
            "upper_wick_reversal_flag",
            "narrow_participation_flag",
            "turnover_return_divergence_flag",
            "coverage_status",
        ),
        "industry_member": (
            "ts_code",
            "industry_code",
            "valid_from",
            "valid_to",
            "available_at",
        ),
        "theme_member": (
            "ts_code",
            "theme_code",
            "valid_from",
            "valid_to",
            "available_at",
        ),
        "earnings_forecast": ("ts_code", "report_period", "available_at"),
        "earnings_express": ("ts_code", "report_period", "available_at"),
        "income_statement": ("ts_code", "report_period", "available_at"),
        "announcement": (
            "announcement_id",
            "ts_code",
            "announcement_time",
            "available_at",
            "title",
            "candidate_event_types",
        ),
        "industry_daily": (
            "industry_code",
            "trade_date",
            "available_at",
        ),
        "main_business": ("ts_code", "report_period", "available_at"),
        "repurchase": ("ts_code", "available_at"),
        "balance_sheet": ("ts_code", "report_period", "available_at"),
        "cash_flow": ("ts_code", "report_period", "available_at"),
        "stock_trading_context": (
            "ts_code",
            "analysis_date",
            "relative_return_20d",
            "coverage_status",
        ),
    }
)
_EARNINGS_VALUE_FIELDS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "earnings_forecast": (
            "p_change_min",
            "p_change_max",
            "net_profit_min",
            "net_profit_max",
        ),
        "earnings_express": (
            "operating_revenue",
            "revenue",
            "net_profit",
            "operating_profit",
        ),
        "income_statement": (
            "total_revenue",
            "revenue",
            "operating_revenue",
            "net_profit",
            "operating_profit",
        ),
    }
)
_EVENT_DEEP_READ_FIELDS = (
    "body",
    "amount",
    "subject",
    "execution_conditions",
    "deep_read_completed",
    "deep_read_input_hash",
)
_CYCLE_INDUSTRY_FIELDS = (
    "demand_change",
    "supply_change",
    "price_change",
    "inventory_change",
    "policy_change",
    "peer_evidence",
)
_DAILY_DATASETS = frozenset(
    {"sector_hotspot", "stock_trading_context", "industry_daily"}
)
_RELATIONSHIP_DATASETS = frozenset({"industry_member", "theme_member"})
_COVERAGE_COLUMNS = (
    "available_at",
    "analysis_date",
    "trade_date",
    "valid_from",
    "valid_to",
)

ExecutionStatus = Literal[
    "executable_ready",
    "executable_internal_recall",
    "not_executable_with_local_data",
]
_T = TypeVar("_T")


@dataclass(frozen=True, slots=True)
class RouteCapability:
    """One route's audited executable surface."""

    route: DiscoveryRoute
    can_enumerate_all: bool
    can_form_ready_card: bool
    can_enter_ten: bool
    missing_fields: tuple[str, ...]
    coverage_start: date | None
    coverage_end: date | None
    covers_required_formations: bool
    internal_recall_only: bool
    evidence_hashes: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.route, DiscoveryRoute):
            raise TypeError("route must be a DiscoveryRoute")
        for name in (
            "can_enumerate_all",
            "can_form_ready_card",
            "can_enter_ten",
            "covers_required_formations",
            "internal_recall_only",
        ):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name} must be a strict boolean")
        if self.can_enter_ten and not self.can_form_ready_card:
            raise ValueError("a route cannot enter ten without a ready card")
        if (self.can_form_ready_card or self.can_enter_ten) and not (
            self.can_enumerate_all and self.covers_required_formations
        ):
            raise ValueError("ready and enter-ten capability must enumerate all formations")
        if self.missing_fields and (
            self.can_form_ready_card or self.can_enter_ten
        ):
            raise ValueError("missing_fields cannot coexist with ready or enter-ten capability")
        if self.internal_recall_only and (
            self.can_form_ready_card or self.can_enter_ten
        ):
            raise ValueError("internal recall cannot be declared ready")
        if self.internal_recall_only and not self.can_enumerate_all:
            raise ValueError("internal recall requires exhaustive enumeration")
        if self.can_enumerate_all and not self.covers_required_formations:
            raise ValueError("exhaustive enumeration requires formation-session coverage")
        if (self.coverage_start is None) != (self.coverage_end is None):
            raise ValueError("coverage_start and coverage_end must be present together")
        if (
            self.coverage_start is not None
            and self.coverage_end is not None
            and self.coverage_start > self.coverage_end
        ):
            raise ValueError("coverage_start cannot follow coverage_end")
        if any(not isinstance(value, str) or not value.strip() for value in self.missing_fields):
            raise ValueError("missing_fields must contain non-blank strings")
        if len(self.missing_fields) != len(set(self.missing_fields)):
            raise ValueError("missing_fields must be unique")

    @property
    def execution_status(self) -> ExecutionStatus:
        if self.internal_recall_only and self.can_enumerate_all:
            return "executable_internal_recall"
        if (
            self.can_enumerate_all
            and self.can_form_ready_card
            and self.can_enter_ten
            and not self.missing_fields
        ):
            return "executable_ready"
        return "not_executable_with_local_data"

    def to_record(self) -> dict[str, Any]:
        return {
            "route": self.route.value,
            "execution_status": self.execution_status,
            "can_enumerate_all": self.can_enumerate_all,
            "can_form_ready_card": self.can_form_ready_card,
            "can_enter_ten": self.can_enter_ten,
            "missing_fields": list(self.missing_fields),
            "coverage_start": self.coverage_start.isoformat() if self.coverage_start else None,
            "coverage_end": self.coverage_end.isoformat() if self.coverage_end else None,
            "covers_required_formations": self.covers_required_formations,
            "internal_recall_only": self.internal_recall_only,
            "evidence_hashes": list(self.evidence_hashes),
        }


@dataclass(frozen=True, slots=True)
class _AuditSeal:
    routes_hash: str
    audit_hash: str
    token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.token is not _AUDIT_TOKEN:
            raise ValueError("audit seal must be produced by the local capability audit")
        if not _is_sha256(self.routes_hash) or not _is_sha256(self.audit_hash):
            raise ValueError("audit seal hashes must be SHA-256 digests")


@dataclass(frozen=True, slots=True)
class CapabilityMatrix:
    routes: Mapping[DiscoveryRoute, RouteCapability]
    _audit_seal: _AuditSeal | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.routes, Mapping):
            raise TypeError("routes must be a mapping")
        normalized: dict[DiscoveryRoute, RouteCapability] = {}
        for raw_route, capability in self.routes.items():
            try:
                route = DiscoveryRoute(raw_route)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"unknown discovery route: {raw_route!r}") from exc
            if not isinstance(capability, RouteCapability):
                raise TypeError("routes must contain RouteCapability values")
            if capability.route is not route:
                raise ValueError("route key and RouteCapability.route must match")
            if route in normalized:
                raise ValueError("routes cannot contain duplicate normalized keys")
            normalized[route] = capability
        object.__setattr__(self, "routes", MappingProxyType(normalized))

    def freeze(self) -> CapabilityReceipt:
        expected = set(DiscoveryRoute)
        actual = set(self.routes)
        if actual != expected:
            missing = sorted(route.value for route in expected.difference(actual))
            extra = sorted(route.value for route in actual.difference(expected))
            raise ValueError(
                "capability matrix must contain exactly the six discovery routes; "
                f"missing={missing}, extra={extra}"
            )
        for capability in self.routes.values():
            if not capability.evidence_hashes:
                raise ValueError(f"{capability.route.value} lacks a capability evidence hash")
            if len(capability.evidence_hashes) != len(set(capability.evidence_hashes)):
                raise ValueError(
                    f"{capability.route.value} capability evidence hashes must be unique"
                )
            if any(not _is_sha256(value) for value in capability.evidence_hashes):
                raise ValueError(
                    f"{capability.route.value} has an invalid capability evidence hash"
                )
        if self._audit_seal is None or self._audit_seal.token is not _AUDIT_TOKEN:
            raise ValueError("freeze requires audit-produced evidence")
        if _routes_hash(self.routes) != self._audit_seal.routes_hash:
            raise ValueError("capability audit evidence changed after audit")

        full = all(
            capability.execution_status != "not_executable_with_local_data"
            for capability in self.routes.values()
        )
        routes = MappingProxyType(
            {route.value: self.routes[route] for route in DiscoveryRoute}
        )
        scope = "full" if full else "partial"
        status = "executable" if full else "not_executable"
        payload = _capability_receipt_payload(
            scope,
            status,
            routes,
            self._audit_seal.audit_hash,
        )
        return CapabilityReceipt(
            experiment_scope=scope,
            full_v3_status=status,
            routes=routes,
            audit_hash=self._audit_seal.audit_hash,
            receipt_hash=_canonical_hash(payload),
            _token=_RECEIPT_TOKEN,
        )


@dataclass(frozen=True, slots=True)
class CapabilityReceipt:
    experiment_scope: Literal["full", "partial"]
    full_v3_status: Literal["executable", "not_executable"]
    routes: Mapping[str, RouteCapability]
    audit_hash: str
    receipt_hash: str
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._token is not _RECEIPT_TOKEN:
            raise ValueError("CapabilityReceipt must be produced by CapabilityMatrix.freeze")
        frozen_routes = MappingProxyType(dict(self.routes))
        object.__setattr__(self, "routes", frozen_routes)
        if set(frozen_routes) != {route.value for route in DiscoveryRoute}:
            raise ValueError("capability receipt must contain the six routes")
        full = all(
            item.execution_status != "not_executable_with_local_data"
            for item in frozen_routes.values()
        )
        expected_scope = "full" if full else "partial"
        expected_status = "executable" if full else "not_executable"
        if (
            self.experiment_scope != expected_scope
            or self.full_v3_status != expected_status
        ):
            raise ValueError("capability receipt scope/status contradict route evidence")
        if not _is_sha256(self.audit_hash) or not _is_sha256(self.receipt_hash):
            raise ValueError("capability receipt hashes must be SHA-256 digests")
        expected = _canonical_hash(
            _capability_receipt_payload(
                self.experiment_scope,
                self.full_v3_status,
                frozen_routes,
                self.audit_hash,
            )
        )
        if self.receipt_hash != expected:
            raise ValueError("capability receipt hash mismatch")

    def to_record(self) -> dict[str, Any]:
        return {
            **_capability_receipt_payload(
                self.experiment_scope,
                self.full_v3_status,
                self.routes,
                self.audit_hash,
            ),
            "receipt_hash": self.receipt_hash,
        }


def freeze_capability_matrix(matrix: CapabilityMatrix) -> CapabilityReceipt:
    if not isinstance(matrix, CapabilityMatrix):
        raise TypeError("matrix must be a CapabilityMatrix")
    return matrix.freeze()


@dataclass(frozen=True, slots=True)
class WorkspacePaths:
    root: Path
    directories: tuple[Path, ...]

    def __post_init__(self) -> None:
        root = _validate_approved_root(self.root)
        expected = tuple(root / value for value in _WORKSPACE_DIRECTORIES)
        normalized = tuple(Path(value).resolve(strict=False) for value in self.directories)
        if normalized != expected:
            raise ValueError("WorkspacePaths directories do not match the frozen workspace")
        object.__setattr__(self, "root", root)
        object.__setattr__(self, "directories", normalized)

    @property
    def preflight(self) -> Path:
        return self.root / "preflight"


def prepare_backtest_workspace(root: Path | None = None) -> WorkspacePaths:
    """Create the one approved U-disk workspace after validating all temp roots."""

    configured = os.environ.get("V3_BACKTEST_ROOT")
    candidate = Path(root) if root is not None else Path(configured or "")
    approved = _validate_approved_root(candidate)
    if not configured or Path(configured).expanduser().resolve(strict=False) != approved:
        raise ValueError("V3_BACKTEST_ROOT must equal the approved U-disk experiment root")
    _require_environment_path("TMPDIR", approved / "tmp")
    _require_environment_path("DUCKDB_TMPDIR", approved / "duckdb-tmp")
    directories = tuple(approved / value for value in _WORKSPACE_DIRECTORIES)
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)
    return WorkspacePaths(root=approved, directories=directories)


@dataclass(frozen=True, slots=True)
class TreeFingerprint:
    tree_sha256: str

    def to_record(self) -> dict[str, Any]:
        return {"tree_sha256": self.tree_sha256}


@dataclass(frozen=True, slots=True)
class FileFingerprint:
    sha256: str
    size: int
    mtime_ns: int

    def to_record(self) -> dict[str, Any]:
        return {"sha256": self.sha256, "size": self.size, "mtime_ns": self.mtime_ns}


@dataclass(frozen=True, slots=True)
class WarehouseFingerprint:
    warehouse_root: str
    facts: TreeFingerprint
    derived: TreeFingerprint
    research_duckdb: FileFingerprint

    def to_record(self) -> dict[str, Any]:
        return {
            "warehouse_root": self.warehouse_root,
            "facts": self.facts.to_record(),
            "derived": self.derived.to_record(),
            "research_duckdb": self.research_duckdb.to_record(),
        }


def fingerprint_mac_warehouse(warehouse_root: Path) -> WarehouseFingerprint:
    """Hash the production warehouse without markers or temporary files."""

    root = Path(warehouse_root).expanduser().resolve(strict=True)
    facts = root / "facts"
    derived = root / "derived"
    database = root / "research.duckdb"
    if not facts.is_dir():
        raise FileNotFoundError(facts)
    if not derived.is_dir():
        raise FileNotFoundError(derived)
    if not database.is_file():
        raise FileNotFoundError(database)
    database_before = database.stat()
    database_hash = _file_sha256(database)
    facts_hash = tree_fingerprint(facts)
    derived_hash = tree_fingerprint(derived)
    database_after = database.stat()
    if (
        database_before.st_size,
        database_before.st_mtime_ns,
    ) != (
        database_after.st_size,
        database_after.st_mtime_ns,
    ):
        raise RuntimeError("research.duckdb changed while it was fingerprinted")
    return WarehouseFingerprint(
        warehouse_root=str(root),
        facts=TreeFingerprint(tree_sha256=facts_hash),
        derived=TreeFingerprint(tree_sha256=derived_hash),
        research_duckdb=FileFingerprint(
            sha256=database_hash,
            size=database_after.st_size,
            mtime_ns=database_after.st_mtime_ns,
        ),
    )


def assert_warehouse_unchanged(
    expected: WarehouseFingerprint,
    actual: WarehouseFingerprint,
) -> None:
    if expected != actual:
        raise RuntimeError("Mac warehouse fingerprint changed; fail closed")


@dataclass(frozen=True, slots=True)
class WarehousePhaseGuard:
    warehouse_root: Path
    before: WarehouseFingerprint

    @classmethod
    def capture(cls, warehouse_root: Path) -> WarehousePhaseGuard:
        root = Path(warehouse_root).expanduser().resolve(strict=True)
        return cls(root, fingerprint_mac_warehouse(root))

    def verify_current(self) -> WarehouseFingerprint:
        current = fingerprint_mac_warehouse(self.warehouse_root)
        assert_warehouse_unchanged(self.before, current)
        return current

    def run_phase(self, phase: str, operation: Callable[[], _T]) -> _T:
        if not isinstance(phase, str) or not phase.strip():
            raise ValueError("phase must not be blank")
        self.verify_current()
        result = operation()
        self.verify_current()
        return result

    def publish_preflight(
        self,
        workspace: WorkspacePaths,
        capability: CapabilityReceipt,
    ) -> tuple[Path, Path]:
        return write_preflight_receipts(
            workspace,
            capability,
            self.before,
            guard=self,
        )


@dataclass(frozen=True, slots=True)
class _DatasetInventory:
    domain: str
    dataset: str
    files: tuple[Path, ...]
    fields: frozenset[str]
    available_dates: tuple[date, ...]
    business_dates: tuple[date, ...]
    relationship_intervals: tuple[tuple[date, date, date | None], ...]
    evidence_hash: str

    @property
    def present(self) -> bool:
        return bool(self.files)


@dataclass(frozen=True, slots=True)
class _DatasetCoverage:
    start: date | None
    end: date | None
    covers_required_formations: bool


@dataclass(frozen=True, slots=True)
class _AdmissionEvidence:
    helper: str | None
    emits_route_lead: bool
    has_non_internal_lead: bool
    internal_only: bool
    has_preliminary_opportunity: bool
    usable_for_decision_possible: bool


@dataclass(frozen=True, slots=True)
class _RouteSourceAudit:
    source_hash: str
    generic_enumeration: bool
    eligible_path_attested: bool
    admissions: Mapping[DiscoveryRoute, _AdmissionEvidence]
    audit_hash: str


def audit_local_capability_matrix(
    warehouse_root: Path,
    *,
    routes_source: Path | None = None,
    warehouse_fingerprint: WarehouseFingerprint | None = None,
    formation_sessions: Sequence[date] | None = None,
) -> CapabilityMatrix:
    """Audit actual admission code, local values and all 144 formation sessions."""

    root = Path(warehouse_root).expanduser().resolve(strict=True)
    if routes_source is None:
        from stock_analyzer.evaluation.v3_backtest import routes as routes_module

        routes_source = Path(routes_module.__file__)
    source = Path(routes_source).expanduser().resolve(strict=True)
    source_audit = _audit_route_source(source.read_text(encoding="utf-8"))
    fingerprint = warehouse_fingerprint or fingerprint_mac_warehouse(root)
    if Path(fingerprint.warehouse_root) != root:
        raise ValueError("warehouse fingerprint does not belong to warehouse_root")
    sessions = _validated_formation_sessions(
        formation_sessions or _load_formation_sessions(root)
    )
    session_hash = _canonical_hash([value.isoformat() for value in sessions])

    inventories: dict[tuple[str, str], _DatasetInventory] = {}
    for domain, dataset in {
        item for values in _ROUTE_DATASETS.values() for item in values
    }:
        inventories[(domain, dataset)] = _inventory_dataset(
            root,
            domain=domain,
            dataset=dataset,
        )

    capabilities: dict[DiscoveryRoute, RouteCapability] = {}
    for route in DiscoveryRoute:
        route_inventories = tuple(inventories[item] for item in _ROUTE_DATASETS[route])
        missing = _enumeration_missing_fields(route_inventories)
        coverages = {
            inventory.dataset: _dataset_coverage(inventory, sessions)
            for inventory in route_inventories
        }
        for dataset, coverage in coverages.items():
            if not coverage.covers_required_formations:
                missing.append(f"{dataset}.formation_session_coverage")
        coverage_start, coverage_end = _route_coverage(tuple(coverages.values()))
        covers_required = all(
            coverage.covers_required_formations for coverage in coverages.values()
        )
        admission = source_audit.admissions[route]
        if not admission.emits_route_lead:
            missing.append(f"{route.value}.lead_implementation")
        if not source_audit.eligible_path_attested:
            missing.append("routes.eligible_for_ten_attestation")

        local_ready, local_missing = _local_ready_evidence(
            route,
            inventories,
        )
        missing.extend(local_missing)
        source_can_ready = (
            admission.emits_route_lead
            and admission.has_non_internal_lead
            and admission.has_preliminary_opportunity
            and admission.usable_for_decision_possible
            and source_audit.eligible_path_attested
        )
        if (
            admission.emits_route_lead
            and admission.has_non_internal_lead
            and not admission.has_preliminary_opportunity
        ):
            missing.append(f"{route.value}.preliminary_opportunity")
        can_enumerate = (
            source_audit.generic_enumeration
            and not _enumeration_missing_fields(route_inventories)
            and covers_required
        )
        ready = can_enumerate and source_can_ready and local_ready
        internal_recall = (
            can_enumerate
            and admission.emits_route_lead
            and admission.internal_only
            and source_audit.eligible_path_attested
        )
        if ready:
            missing = []

        evidence_hashes = [
            source_audit.source_hash,
            source_audit.audit_hash,
            session_hash,
        ]
        if any(item.domain == "facts" for item in route_inventories):
            evidence_hashes.append(fingerprint.facts.tree_sha256)
        if any(item.domain == "derived" for item in route_inventories):
            evidence_hashes.append(fingerprint.derived.tree_sha256)
        evidence_hashes.extend(item.evidence_hash for item in route_inventories)
        capabilities[route] = RouteCapability(
            route=route,
            can_enumerate_all=can_enumerate,
            can_form_ready_card=ready,
            can_enter_ten=ready,
            missing_fields=tuple(dict.fromkeys(missing)),
            coverage_start=coverage_start,
            coverage_end=coverage_end,
            covers_required_formations=covers_required,
            internal_recall_only=internal_recall,
            evidence_hashes=tuple(dict.fromkeys(evidence_hashes)),
        )

    routes_hash = _routes_hash(capabilities)
    audit_hash = _canonical_hash(
        {
            "routes_hash": routes_hash,
            "route_source_audit": source_audit.audit_hash,
            "formation_sessions": session_hash,
            "warehouse": fingerprint.to_record(),
        }
    )
    return CapabilityMatrix(
        routes=capabilities,
        _audit_seal=_AuditSeal(
            routes_hash=routes_hash,
            audit_hash=audit_hash,
            token=_AUDIT_TOKEN,
        ),
    )


def run_capability_preflight(
    workspace: WorkspacePaths,
    warehouse_root: Path,
    *,
    routes_source: Path | None = None,
    formation_sessions: Sequence[date] | None = None,
) -> tuple[CapabilityReceipt, tuple[Path, Path], WarehousePhaseGuard]:
    """Own the before/audit/after/publish sequence as one fail-closed preflight."""

    _validate_workspace(workspace)
    guard = WarehousePhaseGuard.capture(warehouse_root)
    matrix = guard.run_phase(
        "capability-audit",
        lambda: audit_local_capability_matrix(
            warehouse_root,
            routes_source=routes_source,
            warehouse_fingerprint=guard.before,
            formation_sessions=formation_sessions,
        ),
    )
    receipt = matrix.freeze()
    paths = guard.publish_preflight(workspace, receipt)
    return receipt, paths, guard


def write_preflight_receipts(
    workspace: WorkspacePaths,
    capability: CapabilityReceipt,
    warehouse: WarehouseFingerprint,
    *,
    guard: WarehousePhaseGuard | None = None,
) -> tuple[Path, Path]:
    _validate_workspace(workspace)
    if not isinstance(capability, CapabilityReceipt) or capability._token is not _RECEIPT_TOKEN:
        raise ValueError("preflight write requires a frozen audited capability receipt")
    if guard is None or not isinstance(guard, WarehousePhaseGuard):
        raise ValueError("preflight write requires WarehousePhaseGuard")
    if guard.before != warehouse:
        raise ValueError("warehouse receipt must equal the phase guard before fingerprint")
    guard.verify_current()
    capability_path = workspace.preflight / "capability-matrix.json"
    fingerprint_path = workspace.preflight / "mac-warehouse-fingerprint-before.json"
    _atomic_write_json(capability_path, capability.to_record())
    guard.verify_current()
    _atomic_write_json(fingerprint_path, warehouse.to_record())
    return capability_path, fingerprint_path


def _audit_route_source(source: str) -> _RouteSourceAudit:
    tree = ast.parse(source)
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    scan = functions.get("_scan_route")
    if scan is None:
        raise ValueError("routes source must define exactly one _scan_route")
    generic = any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "read"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "view"
        for node in ast.walk(scan)
    )
    helpers: dict[DiscoveryRoute, str] = {}
    for node in ast.walk(scan):
        if not isinstance(node, ast.If):
            continue
        route = _route_from_expression(node.test)
        if route is None:
            continue
        helper_names = [
            call.func.id
            for statement in node.body
            for call in ast.walk(statement)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id.endswith("_leads")
        ]
        if helper_names:
            helpers[route] = helper_names[0]
    lead_defaults = _lead_keyword_defaults(functions.get("_lead"))
    admissions: dict[DiscoveryRoute, _AdmissionEvidence] = {}
    for route in DiscoveryRoute:
        helper_name = helpers.get(route)
        helper = functions.get(helper_name or "")
        lead_calls = (
            [
                node
                for node in ast.walk(helper)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "_lead"
                and _lead_call_route(node) is route
            ]
            if helper is not None
            else []
        )
        internal_states = [
            _call_keyword_bool(call, "internal_only", lead_defaults.get("internal_only"))
            for call in lead_calls
        ]
        usable_states = [
            _call_keyword_not_false(call, "usable", lead_defaults.get("usable"))
            for call in lead_calls
        ]
        preliminary_states = [
            _call_keyword_not_none(
                call,
                "preliminary_opportunity",
                lead_defaults.get("preliminary_opportunity"),
            )
            for call in lead_calls
        ]
        admissions[route] = _AdmissionEvidence(
            helper=helper_name,
            emits_route_lead=bool(lead_calls),
            has_non_internal_lead=any(value is False for value in internal_states),
            internal_only=bool(internal_states) and all(
                value is True for value in internal_states
            ),
            has_preliminary_opportunity=any(preliminary_states),
            usable_for_decision_possible=any(usable_states),
        )
    eligible = _eligible_path_attested(functions.get("_merge_leads"))
    source_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
    audit_record = {
        "source_hash": source_hash,
        "generic_enumeration": generic,
        "eligible_path_attested": eligible,
        "admissions": {
            route.value: {
                "helper": evidence.helper,
                "emits_route_lead": evidence.emits_route_lead,
                "has_non_internal_lead": evidence.has_non_internal_lead,
                "internal_only": evidence.internal_only,
                "has_preliminary_opportunity": evidence.has_preliminary_opportunity,
                "usable_for_decision_possible": evidence.usable_for_decision_possible,
            }
            for route, evidence in admissions.items()
        },
    }
    return _RouteSourceAudit(
        source_hash=source_hash,
        generic_enumeration=generic,
        eligible_path_attested=eligible,
        admissions=MappingProxyType(admissions),
        audit_hash=_canonical_hash(audit_record),
    )


def _route_from_expression(expression: ast.AST) -> DiscoveryRoute | None:
    for node in ast.walk(expression):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "DiscoveryRoute"
        ):
            try:
                return DiscoveryRoute[node.attr]
            except KeyError:
                return None
    return None


def _lead_call_route(call: ast.Call) -> DiscoveryRoute | None:
    candidates = list(call.args[1:2])
    candidates.extend(
        keyword.value for keyword in call.keywords if keyword.arg == "route"
    )
    return _route_from_expression(candidates[0]) if candidates else None


def _lead_keyword_defaults(
    function: ast.FunctionDef | ast.AsyncFunctionDef | None,
) -> dict[str, ast.AST | None]:
    if function is None:
        return {}
    return {
        argument.arg: default
        for argument, default in zip(
            function.args.kwonlyargs,
            function.args.kw_defaults,
            strict=True,
        )
    }


def _call_keyword_value(
    call: ast.Call,
    name: str,
    default: ast.AST | None,
) -> ast.AST | None:
    return next(
        (keyword.value for keyword in call.keywords if keyword.arg == name),
        default,
    )


def _call_keyword_bool(
    call: ast.Call,
    name: str,
    default: ast.AST | None,
) -> bool | None:
    value = _call_keyword_value(call, name, default)
    return value.value if isinstance(value, ast.Constant) and type(value.value) is bool else None


def _call_keyword_not_false(
    call: ast.Call,
    name: str,
    default: ast.AST | None,
) -> bool:
    value = _call_keyword_value(call, name, default)
    return not (isinstance(value, ast.Constant) and value.value is False)


def _call_keyword_not_none(
    call: ast.Call,
    name: str,
    default: ast.AST | None,
) -> bool:
    value = _call_keyword_value(call, name, default)
    if value is None or (isinstance(value, ast.Constant) and value.value is None):
        return False
    if isinstance(value, ast.IfExp):
        return any(
            not (isinstance(branch, ast.Constant) and branch.value is None)
            for branch in (value.body, value.orelse)
        )
    return True


def _eligible_path_attested(
    function: ast.FunctionDef | ast.AsyncFunctionDef | None,
) -> bool:
    if function is None:
        return False
    usable_filters_decision = any(
        isinstance(node, (ast.Assign, ast.AnnAssign))
        and _assignment_targets_name(node, "usable")
        and any(
            isinstance(child, ast.Attribute)
            and child.attr == "usable_for_decision"
            for child in ast.walk(node)
        )
        for node in ast.walk(function)
    )
    eligible_from_non_internal_usable = any(
        isinstance(node, ast.keyword)
        and node.arg == "eligible_for_ten"
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "any"
        and any(
            isinstance(child, ast.GeneratorExp)
            and isinstance(child.elt, ast.UnaryOp)
            and isinstance(child.elt.op, ast.Not)
            and isinstance(child.elt.operand, ast.Attribute)
            and child.elt.operand.attr == "internal_only"
            and any(
                isinstance(generator.iter, ast.Name)
                and generator.iter.id == "usable"
                for generator in child.generators
            )
            for child in ast.walk(node.value)
        )
        for node in ast.walk(function)
    )
    return usable_filters_decision and eligible_from_non_internal_usable


def _assignment_targets_name(node: ast.Assign | ast.AnnAssign, name: str) -> bool:
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    return any(isinstance(target, ast.Name) and target.id == name for target in targets)


def _inventory_dataset(
    root: Path,
    *,
    domain: str,
    dataset: str,
) -> _DatasetInventory:
    directory = root / domain / dataset
    files = _parquet_files(directory)
    fields: set[str] = set()
    available_dates: list[date] = []
    business_dates: list[date] = []
    relationships: list[tuple[date, date, date | None]] = []
    evidence_files: list[dict[str, Any]] = []
    for path in files:
        parquet = pq.ParquetFile(path)
        names = tuple(parquet.schema_arrow.names)
        fields.update(names)
        selected = [name for name in _COVERAGE_COLUMNS if name in names]
        rows = parquet.read(columns=selected).to_pylist() if selected else []
        for row in rows:
            available = _as_local_date(row.get("available_at"))
            if available is not None:
                available_dates.append(available)
            for field_name in ("analysis_date", "trade_date"):
                value = _as_local_date(row.get(field_name))
                if value is not None:
                    business_dates.append(value)
            valid_from = _as_local_date(row.get("valid_from"))
            if available is not None and valid_from is not None:
                relationships.append(
                    (available, valid_from, _as_local_date(row.get("valid_to")))
                )
        stat = path.stat()
        evidence_files.append(
            {
                "path": path.relative_to(root).as_posix(),
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "fields": names,
                "rows": parquet.metadata.num_rows,
            }
        )
    return _DatasetInventory(
        domain=domain,
        dataset=dataset,
        files=files,
        fields=frozenset(fields),
        available_dates=tuple(sorted(set(available_dates))),
        business_dates=tuple(sorted(set(business_dates))),
        relationship_intervals=tuple(relationships),
        evidence_hash=_canonical_hash(
            {
                "domain": domain,
                "dataset": dataset,
                "files": evidence_files,
                "missing": not bool(files),
            }
        ),
    )


def _dataset_coverage(
    inventory: _DatasetInventory,
    sessions: tuple[date, ...],
) -> _DatasetCoverage:
    if inventory.dataset in _DAILY_DATASETS:
        observed = set(inventory.business_dates)
        return _DatasetCoverage(
            start=min(observed) if observed else None,
            end=max(observed) if observed else None,
            covers_required_formations=set(sessions).issubset(observed),
        )
    if inventory.dataset in _RELATIONSHIP_DATASETS:
        covered = tuple(
            session
            for session in sessions
            if any(
                available <= session
                and valid_from <= session
                and (valid_to is None or session <= valid_to)
                for available, valid_from, valid_to in inventory.relationship_intervals
            )
        )
        return _DatasetCoverage(
            start=min(covered) if covered else None,
            end=max(covered) if covered else None,
            covers_required_formations=len(covered) == len(sessions),
        )
    observed = inventory.available_dates
    return _DatasetCoverage(
        start=min(observed) if observed else None,
        end=max(observed) if observed else None,
        covers_required_formations=(
            bool(observed) and min(observed) <= sessions[0] and max(observed) >= sessions[-1]
        ),
    )


def _route_coverage(
    coverages: tuple[_DatasetCoverage, ...],
) -> tuple[date | None, date | None]:
    starts = [item.start for item in coverages if item.start is not None]
    ends = [item.end for item in coverages if item.end is not None]
    if len(starts) != len(coverages) or len(ends) != len(coverages):
        return None, None
    start = max(starts)
    end = min(ends)
    return (start, end) if start <= end else (None, None)


def _enumeration_missing_fields(
    inventories: Sequence[_DatasetInventory],
) -> list[str]:
    missing: list[str] = []
    for inventory in inventories:
        if not inventory.present:
            missing.append(f"{inventory.dataset}.*")
            continue
        for field_name in _REQUIRED_FIELDS[inventory.dataset]:
            if field_name not in inventory.fields:
                missing.append(f"{inventory.dataset}.{field_name}")
    return missing


def _local_ready_evidence(
    route: DiscoveryRoute,
    inventories: Mapping[tuple[str, str], _DatasetInventory],
) -> tuple[bool, list[str]]:
    missing: list[str] = []
    if route is DiscoveryRoute.EARNINGS:
        for dataset, fields in _EARNINGS_VALUE_FIELDS.items():
            if not _inventory_has_non_null_any(inventories[("facts", dataset)], fields):
                missing.append(f"{dataset}.operating_value")
    elif route is DiscoveryRoute.COMPANY_EVENT:
        event = inventories[("facts", "announcement")]
        for field_name in _EVENT_DEEP_READ_FIELDS:
            if field_name not in event.fields:
                missing.append(f"announcement.{field_name}")
        if not missing and not _inventory_has_ready_event(event):
            missing.append("announcement.completed_deep_read_row")
    elif route is DiscoveryRoute.INDUSTRY_CYCLE:
        industry = inventories[("facts", "industry_daily")]
        business = inventories[("facts", "main_business")]
        if not _inventory_has_all_non_null(industry, _CYCLE_INDUSTRY_FIELDS):
            missing.extend(
                f"industry_daily.{field_name}"
                for field_name in _CYCLE_INDUSTRY_FIELDS
                if field_name not in industry.fields
            )
            if not missing:
                missing.append("industry_daily.complete_cycle_evidence_row")
        if not _inventory_has_non_null_any(business, ("company_sensitivity",)):
            missing.append("main_business.company_sensitivity")
    elif route is DiscoveryRoute.DISTRESS_REPAIR:
        repurchase = inventories[("facts", "repurchase")]
        if not _inventory_has_true(repurchase, "core_risk_mitigated"):
            missing.append("repurchase.core_risk_mitigated")
        for dataset in ("income_statement", "balance_sheet", "cash_flow"):
            if not _inventory_has_true(inventories[("facts", dataset)], "statement_improved"):
                missing.append(f"{dataset}.statement_improved")
    return not missing, missing


def _inventory_has_non_null_any(
    inventory: _DatasetInventory,
    fields: Sequence[str],
) -> bool:
    for path in inventory.files:
        parquet = pq.ParquetFile(path)
        selected = [field_name for field_name in fields if field_name in parquet.schema_arrow.names]
        if not selected:
            continue
        table = parquet.read(columns=selected)
        if any(column.null_count < len(column) for column in table.columns):
            return True
    return False


def _inventory_has_all_non_null(
    inventory: _DatasetInventory,
    fields: Sequence[str],
) -> bool:
    if not set(fields).issubset(inventory.fields):
        return False
    for path in inventory.files:
        parquet = pq.ParquetFile(path)
        if not set(fields).issubset(parquet.schema_arrow.names):
            continue
        if any(all(_present(row[field_name]) for field_name in fields) for row in parquet.read(columns=list(fields)).to_pylist()):
            return True
    return False


def _inventory_has_true(inventory: _DatasetInventory, field_name: str) -> bool:
    for path in inventory.files:
        parquet = pq.ParquetFile(path)
        if field_name not in parquet.schema_arrow.names:
            continue
        if any(row[field_name] is True for row in parquet.read(columns=[field_name]).to_pylist()):
            return True
    return False


def _inventory_has_ready_event(inventory: _DatasetInventory) -> bool:
    if not set(_EVENT_DEEP_READ_FIELDS).issubset(inventory.fields):
        return False
    for path in inventory.files:
        parquet = pq.ParquetFile(path)
        if not set(_EVENT_DEEP_READ_FIELDS).issubset(parquet.schema_arrow.names):
            continue
        for row in parquet.read(columns=list(_EVENT_DEEP_READ_FIELDS)).to_pylist():
            deep_hash = row["deep_read_input_hash"]
            if (
                row["deep_read_completed"] is True
                and _is_sha256(deep_hash)
                and all(_present(row[field_name]) for field_name in _EVENT_DEEP_READ_FIELDS[:4])
            ):
                return True
    return False


def _load_formation_sessions(root: Path) -> tuple[date, ...]:
    directory = root / "facts" / "trade_calendar"
    sessions: set[date] = set()
    for path in _parquet_files(directory):
        parquet = pq.ParquetFile(path)
        required = {"cal_date", "is_open"}
        if not required.issubset(parquet.schema_arrow.names):
            raise ValueError("trade_calendar lacks cal_date/is_open")
        for row in parquet.read(columns=["cal_date", "is_open"]).to_pylist():
            value = _as_local_date(row["cal_date"])
            if row["is_open"] is True and value is not None and _FORMATION_START <= value <= _FORMATION_END:
                sessions.add(value)
    return tuple(sorted(sessions))


def _validated_formation_sessions(values: Sequence[date]) -> tuple[date, ...]:
    sessions = tuple(values)
    if (
        len(sessions) != _FORMATION_COUNT
        or len(set(sessions)) != _FORMATION_COUNT
        or tuple(sorted(sessions)) != sessions
        or sessions[0] != _FORMATION_START
        or sessions[-1] != _FORMATION_END
    ):
        raise ValueError("formation_sessions must be the frozen 144-session sample")
    return sessions


def _parquet_files(directory: Path) -> tuple[Path, ...]:
    if not directory.is_dir():
        return ()
    return tuple(
        sorted(
            path
            for path in directory.rglob("*.parquet")
            if not any(part.startswith("._") for part in path.parts)
        )
    )


def _as_local_date(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(_SHANGHAI)
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone(_SHANGHAI)
            return parsed.date()
        except ValueError:
            try:
                return date.fromisoformat(value)
            except ValueError:
                return None
    return None


def _validate_approved_root(value: Path) -> Path:
    resolved = Path(value).expanduser().resolve(strict=False)
    if resolved != _APPROVED_EXPERIMENT_ROOT:
        raise ValueError(
            f"path must equal approved U-disk experiment root: {_APPROVED_EXPERIMENT_ROOT}"
        )
    return resolved


def _validate_workspace(workspace: WorkspacePaths) -> None:
    if not isinstance(workspace, WorkspacePaths):
        raise TypeError("workspace must be WorkspacePaths")
    workspace.__post_init__()
    configured = os.environ.get("V3_BACKTEST_ROOT")
    if not configured or Path(configured).expanduser().resolve(strict=False) != workspace.root:
        raise ValueError("V3_BACKTEST_ROOT must equal the approved U-disk experiment root")
    _require_environment_path("TMPDIR", workspace.root / "tmp")
    _require_environment_path("DUCKDB_TMPDIR", workspace.root / "duckdb-tmp")
    if any(not path.is_dir() for path in workspace.directories):
        raise ValueError("approved workspace directories are incomplete")


def _require_environment_path(name: str, expected: Path) -> None:
    raw = os.environ.get(name)
    if not raw or Path(raw).expanduser().resolve(strict=False) != expected:
        raise ValueError(f"{name} must be set to {expected}")


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    approved = _APPROVED_EXPERIMENT_ROOT
    resolved = Path(path).expanduser().resolve(strict=False)
    if resolved.parent != approved / "preflight" or resolved.name not in _PREFLIGHT_FILENAMES:
        raise ValueError("write path must be an approved U-disk experiment root preflight receipt")
    if not resolved.parent.is_dir():
        raise ValueError("approved preflight directory does not exist")
    encoded = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=resolved.parent,
            prefix=f".{resolved.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, resolved)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _routes_hash(routes: Mapping[Any, RouteCapability]) -> str:
    normalized = {
        route.value: routes[route].to_record()
        for route in DiscoveryRoute
    }
    return _canonical_hash(normalized)


def _capability_receipt_payload(
    experiment_scope: str,
    full_v3_status: str,
    routes: Mapping[str, RouteCapability],
    audit_hash: str,
) -> dict[str, Any]:
    return {
        "experiment_scope": experiment_scope,
        "full_v3_status": full_v3_status,
        "audit_hash": audit_hash,
        "routes": {
            route.value: routes[route.value].to_record()
            for route in DiscoveryRoute
        },
    }


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == _SHA256_LENGTH
        and all(character in "0123456789abcdef" for character in value)
    )


def _present(value: object) -> bool:
    return value is not None and (not isinstance(value, str) or bool(value.strip()))


__all__ = [
    "CapabilityMatrix",
    "CapabilityReceipt",
    "FileFingerprint",
    "RouteCapability",
    "TreeFingerprint",
    "WarehouseFingerprint",
    "WarehousePhaseGuard",
    "WorkspacePaths",
    "assert_warehouse_unchanged",
    "audit_local_capability_matrix",
    "fingerprint_mac_warehouse",
    "freeze_capability_matrix",
    "prepare_backtest_workspace",
    "run_capability_preflight",
    "write_preflight_receipts",
]
