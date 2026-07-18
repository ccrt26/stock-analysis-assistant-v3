"""Fail-closed capability and zero-write preflight for the isolated V3 replay."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

import pyarrow.parquet as pq

from stock_analyzer.evaluation.v3_backtest.contracts import DiscoveryRoute
from stock_analyzer.evaluation.v3_backtest.snapshots import tree_fingerprint


_INTERNAL_RECALL_ROUTES = frozenset(
    {DiscoveryRoute.HOTSPOT, DiscoveryRoute.PRICE_ANOMALY}
)
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
        "industry_member": ("ts_code", "industry_code", "valid_from", "valid_to"),
        "theme_member": ("ts_code", "theme_code", "valid_from", "valid_to"),
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
        "industry_daily": ("industry_code", "trade_date", "available_at"),
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
_CYCLE_SEMANTIC_FIELDS = (
    "demand_change",
    "supply_change",
    "price_change",
    "inventory_change",
)
_DATE_PARTITION_FIELDS = frozenset(
    {
        "analysis_date",
        "trade_date",
        "announcement_month",
        "ann_month",
        "report_period",
        "snapshot_date",
    }
)
_SHA256_LENGTH = 64


ExecutionStatus = Literal[
    "executable_ready",
    "executable_internal_recall",
    "not_executable_with_local_data",
]


@dataclass(frozen=True, slots=True)
class RouteCapability:
    """One route's executable surface, never an inference from its mere existence."""

    route: DiscoveryRoute
    can_enumerate_all: bool
    can_form_ready_card: bool
    can_enter_ten: bool
    missing_fields: tuple[str, ...]
    coverage_start: date | None
    coverage_end: date | None
    evidence_hashes: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.route, DiscoveryRoute):
            raise TypeError("route must be a DiscoveryRoute")
        for name in (
            "can_enumerate_all",
            "can_form_ready_card",
            "can_enter_ten",
        ):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name} must be a strict boolean")
        if self.can_enter_ten and not self.can_form_ready_card:
            raise ValueError("a route cannot enter ten without a ready card")
        if self.route in _INTERNAL_RECALL_ROUTES and (
            self.can_form_ready_card or self.can_enter_ten
        ):
            raise ValueError("hotspot and price are internal recall, not ready opportunities")
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
        if self.route in _INTERNAL_RECALL_ROUTES:
            return (
                "executable_internal_recall"
                if self.can_enumerate_all
                else "not_executable_with_local_data"
            )
        if (
            self.can_enumerate_all
            and self.can_form_ready_card
            and self.can_enter_ten
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
            "coverage_start": (
                self.coverage_start.isoformat() if self.coverage_start else None
            ),
            "coverage_end": self.coverage_end.isoformat() if self.coverage_end else None,
            "evidence_hashes": list(self.evidence_hashes),
        }


@dataclass(frozen=True, slots=True)
class CapabilityMatrix:
    routes: Mapping[DiscoveryRoute, RouteCapability]

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
                raise ValueError(
                    f"{capability.route.value} lacks a capability evidence hash"
                )
            if len(capability.evidence_hashes) != len(set(capability.evidence_hashes)):
                raise ValueError(
                    f"{capability.route.value} capability evidence hashes must be unique"
                )
            if any(not _is_sha256(value) for value in capability.evidence_hashes):
                raise ValueError(
                    f"{capability.route.value} has an invalid capability evidence hash"
                )

        full = all(
            capability.execution_status != "not_executable_with_local_data"
            for capability in self.routes.values()
        )
        routes = MappingProxyType(
            {
                route.value: self.routes[route]
                for route in DiscoveryRoute
            }
        )
        scope = "full" if full else "partial"
        status = "executable" if full else "not_executable"
        payload = _capability_receipt_payload(scope, status, routes)
        return CapabilityReceipt(
            experiment_scope=scope,
            full_v3_status=status,
            routes=routes,
            receipt_hash=_canonical_hash(payload),
        )


@dataclass(frozen=True, slots=True)
class CapabilityReceipt:
    experiment_scope: Literal["full", "partial"]
    full_v3_status: Literal["executable", "not_executable"]
    routes: Mapping[str, RouteCapability]
    receipt_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "routes", MappingProxyType(dict(self.routes)))
        if not _is_sha256(self.receipt_hash):
            raise ValueError("receipt_hash must be a SHA-256 digest")
        expected = _canonical_hash(
            _capability_receipt_payload(
                self.experiment_scope,
                self.full_v3_status,
                self.routes,
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

    @property
    def preflight(self) -> Path:
        return self.root / "preflight"


def prepare_backtest_workspace(root: Path | None = None) -> WorkspacePaths:
    """Create only the approved experiment tree after validating temp routing."""

    configured = os.environ.get("V3_BACKTEST_ROOT")
    if root is None:
        if not configured:
            raise ValueError("V3_BACKTEST_ROOT must be set")
        root = Path(configured)
    resolved = Path(root).expanduser().resolve(strict=False)
    if configured and Path(configured).expanduser().resolve(strict=False) != resolved:
        raise ValueError("root must match V3_BACKTEST_ROOT")
    expected_temp = resolved / "tmp"
    expected_duckdb_temp = resolved / "duckdb-tmp"
    _require_environment_path("TMPDIR", expected_temp)
    _require_environment_path("DUCKDB_TMPDIR", expected_duckdb_temp)

    directories = tuple(resolved / relative for relative in _WORKSPACE_DIRECTORIES)
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)
    return WorkspacePaths(root=resolved, directories=directories)


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
        return {
            "sha256": self.sha256,
            "size": self.size,
            "mtime_ns": self.mtime_ns,
        }


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
    """Hash the production warehouse without creating markers or temporary files."""

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
    before = database.stat()
    database_hash = _file_sha256(database)
    after = database.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise RuntimeError("research.duckdb changed while it was fingerprinted")
    return WarehouseFingerprint(
        warehouse_root=str(root),
        facts=TreeFingerprint(tree_sha256=tree_fingerprint(facts)),
        derived=TreeFingerprint(tree_sha256=tree_fingerprint(derived)),
        research_duckdb=FileFingerprint(
            sha256=database_hash,
            size=after.st_size,
            mtime_ns=after.st_mtime_ns,
        ),
    )


def assert_warehouse_unchanged(
    expected: WarehouseFingerprint,
    actual: WarehouseFingerprint,
) -> None:
    if expected != actual:
        raise RuntimeError("Mac warehouse fingerprint changed; fail closed")


@dataclass(frozen=True, slots=True)
class _DatasetInventory:
    domain: str
    dataset: str
    files: tuple[Path, ...]
    fields: frozenset[str]
    coverage_start: date | None
    coverage_end: date | None
    evidence_hash: str

    @property
    def present(self) -> bool:
        return bool(self.files)


def audit_local_capability_matrix(
    warehouse_root: Path,
    *,
    routes_source: Path | None = None,
    warehouse_fingerprint: WarehouseFingerprint | None = None,
) -> CapabilityMatrix:
    """Audit actual route branches and local Parquet fields; never infer readiness."""

    root = Path(warehouse_root).expanduser().resolve(strict=True)
    if routes_source is None:
        from stock_analyzer.evaluation.v3_backtest import routes as routes_module

        routes_source = Path(routes_module.__file__)
    source = Path(routes_source).expanduser().resolve(strict=True)
    source_bytes = source.read_bytes()
    source_hash = hashlib.sha256(source_bytes).hexdigest()
    source_text = source_bytes.decode("utf-8")
    implemented = _implemented_route_branches(source_text)
    enumerates_route_inputs = _has_generic_route_input_enumeration(source_text)
    fingerprint = warehouse_fingerprint or fingerprint_mac_warehouse(root)
    if Path(fingerprint.warehouse_root) != root:
        raise ValueError("warehouse fingerprint does not belong to warehouse_root")

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
        route_inventories = tuple(
            inventories[item] for item in _ROUTE_DATASETS[route]
        )
        missing = _enumeration_missing_fields(route_inventories)
        can_enumerate = not missing

        if route is DiscoveryRoute.EARNINGS:
            ready = (
                can_enumerate
                and route in implemented
                and all(
                    _inventory_has_non_null_any(
                        inventories[("facts", dataset)],
                        _EARNINGS_VALUE_FIELDS[dataset],
                    )
                    for dataset in _EARNINGS_VALUE_FIELDS
                )
            )
            if route not in implemented:
                missing.append("earnings.lead_implementation")
            for dataset, fields in _EARNINGS_VALUE_FIELDS.items():
                inventory = inventories[("facts", dataset)]
                if not inventory.fields.intersection(fields):
                    missing.append(f"{dataset}.operating_value")
        elif route is DiscoveryRoute.COMPANY_EVENT:
            event = inventories[("facts", "announcement")]
            for field in _EVENT_DEEP_READ_FIELDS:
                if field not in event.fields:
                    missing.append(f"announcement.{field}")
            ready = (
                can_enumerate
                and route in implemented
                and _inventory_has_ready_event(event)
            )
            if route not in implemented:
                missing.append("company_event.lead_implementation")
        elif route is DiscoveryRoute.INDUSTRY_CYCLE:
            industry = inventories[("facts", "industry_daily")]
            if route not in implemented:
                missing.append("industry_cycle.lead_implementation")
            for field in _CYCLE_SEMANTIC_FIELDS:
                if field not in industry.fields:
                    missing.append(f"industry_daily.{field}")
            missing.extend(
                (
                    "industry_cycle.peer_evidence",
                    "industry_cycle.company_sensitivity",
                )
            )
            ready = False
        elif route is DiscoveryRoute.DISTRESS_REPAIR:
            if route not in implemented:
                missing.append("distress_repair.lead_implementation")
            missing.extend(
                (
                    "distress_repair.core_risk_mitigation_semantics",
                    "distress_repair.multi_statement_improvement_semantics",
                )
            )
            ready = False
        else:
            if route not in implemented:
                missing.append(f"{route.value}.lead_implementation")
            ready = False

        coverage_values = tuple(
            value
            for inventory in route_inventories
            for value in (inventory.coverage_start, inventory.coverage_end)
            if value is not None
        )
        evidence_hashes = [source_hash]
        if any(inventory.domain == "facts" for inventory in route_inventories):
            evidence_hashes.append(fingerprint.facts.tree_sha256)
        if any(inventory.domain == "derived" for inventory in route_inventories):
            evidence_hashes.append(fingerprint.derived.tree_sha256)
        evidence_hashes.extend(
            inventory.evidence_hash for inventory in route_inventories
        )
        capabilities[route] = RouteCapability(
            route=route,
            can_enumerate_all=can_enumerate and (
                route in implemented or enumerates_route_inputs
            ),
            can_form_ready_card=ready,
            can_enter_ten=ready,
            missing_fields=tuple(dict.fromkeys(missing)),
            coverage_start=min(coverage_values) if coverage_values else None,
            coverage_end=max(coverage_values) if coverage_values else None,
            evidence_hashes=tuple(dict.fromkeys(evidence_hashes)),
        )
    return CapabilityMatrix(routes=capabilities)


def write_preflight_receipts(
    workspace: WorkspacePaths,
    capability: CapabilityReceipt,
    warehouse: WarehouseFingerprint,
) -> tuple[Path, Path]:
    if not isinstance(workspace, WorkspacePaths):
        raise TypeError("workspace must be WorkspacePaths")
    capability_path = workspace.preflight / "capability-matrix.json"
    fingerprint_path = workspace.preflight / "mac-warehouse-fingerprint-before.json"
    _atomic_write_json(capability_path, capability.to_record())
    _atomic_write_json(fingerprint_path, warehouse.to_record())
    return capability_path, fingerprint_path


def _implemented_route_branches(source: str) -> frozenset[DiscoveryRoute]:
    tree = ast.parse(source)
    functions = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "_scan_route"
    ]
    if len(functions) != 1:
        raise ValueError("routes source must define exactly one _scan_route")
    implemented: set[DiscoveryRoute] = set()
    for node in ast.walk(functions[0]):
        if not isinstance(node, ast.Compare):
            continue
        candidates = (node.left, *node.comparators)
        for candidate in candidates:
            if (
                isinstance(candidate, ast.Attribute)
                and isinstance(candidate.value, ast.Name)
                and candidate.value.id == "DiscoveryRoute"
            ):
                try:
                    implemented.add(DiscoveryRoute[candidate.attr])
                except KeyError:
                    continue
    return frozenset(implemented)


def _has_generic_route_input_enumeration(source: str) -> bool:
    tree = ast.parse(source)
    functions = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "_scan_route"
    ]
    if len(functions) != 1:
        raise ValueError("routes source must define exactly one _scan_route")
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "read"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "view"
        for node in ast.walk(functions[0])
    )


def _inventory_dataset(
    root: Path,
    *,
    domain: str,
    dataset: str,
) -> _DatasetInventory:
    directory = root / domain / dataset
    files = (
        tuple(
            sorted(
                path
                for path in directory.rglob("*.parquet")
                if not any(part.startswith("._") for part in path.parts)
            )
        )
        if directory.is_dir()
        else ()
    )
    fields: set[str] = set()
    evidence_files: list[dict[str, Any]] = []
    coverage: list[date] = []
    for path in files:
        parquet = pq.ParquetFile(path)
        names = tuple(parquet.schema_arrow.names)
        fields.update(names)
        stat = path.stat()
        relative = path.relative_to(root).as_posix()
        evidence_files.append(
            {
                "path": relative,
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "fields": names,
                "rows": parquet.metadata.num_rows,
            }
        )
        coverage.extend(_partition_dates(path.relative_to(directory).parts[:-1]))
    payload = {
        "domain": domain,
        "dataset": dataset,
        "files": evidence_files,
        "missing": not bool(files),
    }
    return _DatasetInventory(
        domain=domain,
        dataset=dataset,
        files=files,
        fields=frozenset(fields),
        coverage_start=min(coverage) if coverage else None,
        coverage_end=max(coverage) if coverage else None,
        evidence_hash=_canonical_hash(payload),
    )


def _enumeration_missing_fields(
    inventories: Sequence[_DatasetInventory],
) -> list[str]:
    missing: list[str] = []
    for inventory in inventories:
        if not inventory.present:
            missing.append(f"{inventory.dataset}.*")
            continue
        for field in _REQUIRED_FIELDS[inventory.dataset]:
            if field not in inventory.fields:
                missing.append(f"{inventory.dataset}.{field}")
    return missing


def _inventory_has_non_null_any(
    inventory: _DatasetInventory,
    fields: Sequence[str],
) -> bool:
    selected = tuple(field for field in fields if field in inventory.fields)
    if not selected:
        return False
    for path in inventory.files:
        available = tuple(
            field for field in selected if field in pq.ParquetFile(path).schema_arrow.names
        )
        if not available:
            continue
        table = pq.ParquetFile(path).read(columns=available)
        if any(column.null_count < len(column) for column in table.columns):
            return True
    return False


def _inventory_has_ready_event(inventory: _DatasetInventory) -> bool:
    if not set(_EVENT_DEEP_READ_FIELDS).issubset(inventory.fields):
        return False
    for path in inventory.files:
        parquet = pq.ParquetFile(path)
        if not set(_EVENT_DEEP_READ_FIELDS).issubset(parquet.schema_arrow.names):
            continue
        rows = parquet.read(columns=list(_EVENT_DEEP_READ_FIELDS)).to_pylist()
        for row in rows:
            deep_hash = row["deep_read_input_hash"]
            if (
                row["deep_read_completed"] is True
                and isinstance(deep_hash, str)
                and _is_sha256(deep_hash)
                and all(_present(row[field]) for field in _EVENT_DEEP_READ_FIELDS[:4])
            ):
                return True
    return False


def _partition_dates(parts: Sequence[str]) -> tuple[date, ...]:
    values: list[date] = []
    for part in parts:
        if "=" not in part:
            continue
        field, raw_value = part.split("=", 1)
        if field not in _DATE_PARTITION_FIELDS:
            continue
        try:
            values.append(date.fromisoformat(raw_value))
        except ValueError:
            try:
                year, month = (int(value) for value in raw_value.split("-"))
                values.append(date(year, month, 1))
            except (TypeError, ValueError):
                continue
    return tuple(values)


def _capability_receipt_payload(
    experiment_scope: str,
    full_v3_status: str,
    routes: Mapping[str, RouteCapability],
) -> dict[str, Any]:
    return {
        "experiment_scope": experiment_scope,
        "full_v3_status": full_v3_status,
        "routes": {
            route.value: routes[route.value].to_record()
            for route in DiscoveryRoute
        },
    }


def _require_environment_path(name: str, expected: Path) -> None:
    raw = os.environ.get(name)
    if not raw:
        raise ValueError(f"{name} must be set to {expected}")
    if Path(raw).expanduser().resolve(strict=False) != expected:
        raise ValueError(f"{name} must be set to {expected}")


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


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
    "WorkspacePaths",
    "assert_warehouse_unchanged",
    "audit_local_capability_matrix",
    "fingerprint_mac_warehouse",
    "freeze_capability_matrix",
    "prepare_backtest_workspace",
    "write_preflight_receipts",
]
