"""Frozen, auditable enumeration of the six V3 discovery routes."""

from __future__ import annotations

import hashlib
import json
import math
import weakref
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from enum import Enum
from types import MappingProxyType
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from stock_analyzer.evaluation.v3_backtest.contracts import (
    DiscoveryRoute,
    OpportunityType,
    RouteScanManifest,
)
from stock_analyzer.data.research_contracts import ResearchDatasetId, research_contract
from stock_analyzer.evaluation.v3_backtest.snapshots import (
    FormationFactView,
    tree_fingerprint,
)
from stock_analyzer.storage.research_query import ResearchQuery
from stock_analyzer.storage.research_warehouse import ResearchWarehouse


_ROUTE_ORDER = tuple(DiscoveryRoute)
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_FEATURE_DATASETS = {"sector_hotspot", "stock_trading_context"}
_POLICY_TOKEN = object()
_CATALOG_TOKEN = object()
_FACT_PLAN_TOKEN = object()
_ATTESTATION_TOKEN = object()
_CONTROLLED_UNIVERSE_DATASETS = (
    "industry_member",
    "theme_member",
    "industry_daily",
)
_CYCLE_GAP = (
    "incomplete cycle coverage: current industry_daily and main_business facts "
    "do not provide a policy/demand/price/supply/inventory/peer evidence card "
    "plus company sensitivity"
)
_REPAIR_GAP = (
    "incomplete distress-repair coverage: current repurchase and financial "
    "statements do not prove core-risk mitigation plus multi-statement improvement"
)


@dataclass(frozen=True)
class _AttestationRegistration:
    warehouse: ResearchWarehouse
    attestation_hash: str
    code_hash: str
    root_identity: tuple[str, int, int]
    tree_hash: str


_ATTESTATION_REGISTRY: weakref.WeakKeyDictionary[Any, _AttestationRegistration] = (
    weakref.WeakKeyDictionary()
)


@dataclass(frozen=True)
class RouteDataset:
    """One materialized formation-time dataset plus source-manifest coverage."""

    dataset: str
    requested_partitions: tuple[str, ...]
    actual_partitions: tuple[str, ...]
    records: tuple[Mapping[str, Any], ...]
    expected_records: int
    missing: tuple[str, ...] = ()
    exclusions: tuple[str, ...] = ()
    input_hash: str | None = None
    verified: bool = True

    def __post_init__(self) -> None:
        if not self.dataset.strip():
            raise ValueError("dataset must not be blank")
        if not self.requested_partitions:
            raise ValueError("requested_partitions must not be empty")
        if len(self.requested_partitions) != len(set(self.requested_partitions)):
            raise ValueError("requested_partitions must be unique")
        if len(self.actual_partitions) != len(set(self.actual_partitions)):
            raise ValueError("actual_partitions must be unique")
        if not set(self.actual_partitions).issubset(self.requested_partitions):
            raise ValueError("actual partitions must have been requested")
        if self.expected_records < len(self.records):
            raise ValueError("expected_records cannot be smaller than resolved records")
        if self.input_hash is not None and not _is_sha256(self.input_hash):
            raise ValueError("input_hash must be a lowercase SHA-256 digest")


@dataclass(frozen=True)
class RouteWindowPolicy:
    """A frozen real-data scan universe; construct only with the public builder."""

    formation_date: date
    route_partitions: Mapping[DiscoveryRoute, Mapping[str, tuple[str, ...]]]
    earnings_report_periods: tuple[date, ...]
    event_start: date
    event_end: date
    price_absolute_tail_fraction: float
    coverage_gaps: Mapping[DiscoveryRoute, tuple[str, ...]]
    universe_source_manifest_hash: str
    universe_source_view_manifest_hash: str
    universe_source_attestation_hash: str
    universe_catalog_hash: str
    universe_effective_content_hashes: Mapping[str, str]
    policy_hash: str
    _source_attestation: _SourceCatalogAttestation = field(
        repr=False,
        compare=False,
    )
    _token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._token is not _POLICY_TOKEN:
            raise ValueError("RouteWindowPolicy must be created by build_route_window_policy")
        if not _is_sha256(self.policy_hash):
            raise ValueError("policy_hash must be a lowercase SHA-256 digest")
        if self.policy_hash != _route_policy_hash(self):
            raise ValueError("route policy integrity hash mismatch")
        _require_registered_attestation(self._source_attestation)


@dataclass(frozen=True)
class RouteEvidence:
    evidence_id: str
    route: DiscoveryRoute
    dataset: str
    available_at: datetime | None
    fact_summary: str | None
    needs_deep_read: bool = False
    usable_for_decision: bool = True
    deep_read_input_hash: str | None = None


@dataclass(frozen=True)
class ResearchHypothesis:
    """A security-level research lead without route votes, scores, or priority."""

    security_id: str
    formation_date: date
    cutoff: datetime
    discovery_routes: tuple[DiscoveryRoute, ...]
    evidence: tuple[RouteEvidence, ...]
    transmission_hypotheses: tuple[str, ...]
    questions_to_verify: tuple[str, ...]
    needs_deep_read: bool
    eligible_for_ten: bool
    internal_review_only: bool
    preliminary_opportunity: OpportunityType | None = None


@dataclass(frozen=True)
class _Lead:
    security_id: str
    route: DiscoveryRoute
    evidence: RouteEvidence
    transmission: str
    question: str
    internal_only: bool = False
    preliminary_opportunity: OpportunityType | None = None


class FrozenUniverseCatalog:
    """Trusted complete controlled partitions bound to a source manifest hash."""

    __slots__ = (
        "__as_of",
        "__formation_date",
        "__source_manifest_hash",
        "__source_view_manifest_hash",
        "__source_attestation_hash",
        "__partitions",
        "__effective_content_hashes",
        "__source_attestation",
        "__catalog_hash",
    )

    def __init__(
        self,
        *,
        source_manifest_hash: str,
        source_view_manifest_hash: str,
        source_attestation_hash: str,
        partitions: Mapping[str, tuple[str, ...]],
        as_of: datetime | None = None,
        formation_date: date | None = None,
        effective_content_hashes: Mapping[str, str] | None = None,
        source_attestation: _SourceCatalogAttestation | None = None,
        _token: object | None = None,
    ) -> None:
        if _token is not _CATALOG_TOKEN:
            raise ValueError(
                "FrozenUniverseCatalog must be created by the catalog builder "
                "build_frozen_universe_catalog"
            )
        normalized = {
            dataset: _partitions(partitions[dataset], dataset)
            for dataset in _CONTROLLED_UNIVERSE_DATASETS
        }
        if as_of is None or as_of.tzinfo is None:
            raise ValueError("universe catalog as_of must be timezone-aware")
        if (
            formation_date is None
            or effective_content_hashes is None
            or source_attestation is None
        ):
            raise ValueError("universe catalog lacks formation content proof")
        _require_registered_attestation(source_attestation)
        normalized_hashes = {
            dataset: str(effective_content_hashes[dataset])
            for dataset in _CONTROLLED_UNIVERSE_DATASETS
        }
        if any(not _is_sha256(value) for value in normalized_hashes.values()):
            raise ValueError("universe effective content hash is invalid")
        self.__as_of = as_of
        self.__formation_date = formation_date
        self.__source_manifest_hash = source_manifest_hash
        self.__source_view_manifest_hash = source_view_manifest_hash
        self.__source_attestation_hash = source_attestation_hash
        self.__partitions = MappingProxyType(normalized)
        self.__effective_content_hashes = MappingProxyType(normalized_hashes)
        self.__source_attestation = source_attestation
        self.__catalog_hash = _stable_hash(
            {
                "source_manifest_hash": source_manifest_hash,
                "source_view_manifest_hash": source_view_manifest_hash,
                "source_attestation_hash": source_attestation_hash,
                "as_of": as_of,
                "formation_date": formation_date,
                "partitions": normalized,
                "effective_content_hashes": normalized_hashes,
            }
        )

    @property
    def as_of(self) -> datetime:
        return self.__as_of

    @property
    def formation_date(self) -> date:
        return self.__formation_date

    @property
    def source_manifest_hash(self) -> str:
        return self.__source_manifest_hash

    @property
    def source_view_manifest_hash(self) -> str:
        return self.__source_view_manifest_hash

    @property
    def source_attestation_hash(self) -> str:
        return self.__source_attestation_hash

    @property
    def catalog_hash(self) -> str:
        return self.__catalog_hash

    def partitions(self, dataset: str) -> tuple[str, ...]:
        return self.__partitions[dataset]

    def effective_content_hash(self, dataset: str) -> str:
        return self.__effective_content_hashes[dataset]

    @property
    def source_attestation(self) -> _SourceCatalogAttestation:
        return self.__source_attestation

    def validate_integrity(self) -> None:
        for label, value in (
            ("source manifest", self.__source_manifest_hash),
            ("source view manifest", self.__source_view_manifest_hash),
            ("source attestation", self.__source_attestation_hash),
        ):
            if not _is_sha256(value):
                raise ValueError(f"universe {label} hash is invalid")
        _require_registered_attestation(self.__source_attestation)
        expected = _stable_hash(
            {
                "source_manifest_hash": self.__source_manifest_hash,
                "source_view_manifest_hash": self.__source_view_manifest_hash,
                "source_attestation_hash": self.__source_attestation_hash,
                "as_of": self.__as_of,
                "formation_date": self.__formation_date,
                "partitions": self.__partitions,
                "effective_content_hashes": self.__effective_content_hashes,
            }
        )
        if self.__catalog_hash != expected:
            raise ValueError("frozen universe catalog integrity hash mismatch")


class _SourceCatalogAttestation:
    """Content-addressed preflight proof from validated warehouse partitions."""

    __slots__ = (
        "__as_of",
        "__formation_date",
        "__partitions",
        "__source_entries",
        "__source_manifest_hash",
        "__view_manifest_hash",
        "__effective_row_counts",
        "__effective_content_hashes",
        "__warehouse_root_identity",
        "__warehouse_tree_hash",
        "__code_hash",
        "__attestation_hash",
        "__weakref__",
    )

    def __init__(
        self,
        *,
        as_of: datetime,
        formation_date: date,
        partitions: Mapping[str, tuple[str, ...]],
        source_entries: Sequence[Mapping[str, Any]],
        source_manifest_hash: str,
        view_manifest_hash: str,
        effective_row_counts: Mapping[str, int],
        effective_content_hashes: Mapping[str, str],
        warehouse_root_identity: tuple[str, int, int],
        warehouse_tree_hash: str,
        code_hash: str,
        _token: object | None = None,
    ) -> None:
        if _token is not _ATTESTATION_TOKEN:
            raise ValueError(
                "source attestation is opaque and must come from the registered "
                "warehouse builder"
            )
        normalized_partitions = {
            dataset: _partitions(partitions[dataset], dataset)
            for dataset in _CONTROLLED_UNIVERSE_DATASETS
        }
        normalized_entries = tuple(
            MappingProxyType(dict(item))
            for item in sorted(
                source_entries,
                key=lambda item: (
                    _dataset_label(item.get("dataset")),
                    str(item.get("partition")),
                ),
            )
        )
        normalized_counts = {
            dataset: int(effective_row_counts[dataset])
            for dataset in _CONTROLLED_UNIVERSE_DATASETS
        }
        normalized_hashes = {
            dataset: str(effective_content_hashes[dataset])
            for dataset in _CONTROLLED_UNIVERSE_DATASETS
        }
        self.__as_of = as_of
        self.__formation_date = formation_date
        self.__partitions = MappingProxyType(normalized_partitions)
        self.__source_entries = normalized_entries
        self.__source_manifest_hash = source_manifest_hash
        self.__view_manifest_hash = view_manifest_hash
        self.__effective_row_counts = MappingProxyType(normalized_counts)
        self.__effective_content_hashes = MappingProxyType(normalized_hashes)
        self.__warehouse_root_identity = tuple(warehouse_root_identity)
        self.__warehouse_tree_hash = str(warehouse_tree_hash)
        self.__code_hash = str(code_hash)
        self.__attestation_hash = _stable_hash(self._integrity_payload())
        self.validate_integrity()

    @property
    def as_of(self) -> datetime:
        return self.__as_of

    @property
    def formation_date(self) -> date:
        return self.__formation_date

    @property
    def source_manifest_hash(self) -> str:
        return self.__source_manifest_hash

    @property
    def view_manifest_hash(self) -> str:
        return self.__view_manifest_hash

    @property
    def attestation_hash(self) -> str:
        return self.__attestation_hash

    @property
    def warehouse_root_identity(self) -> tuple[str, int, int]:
        return self.__warehouse_root_identity

    @property
    def warehouse_tree_hash(self) -> str:
        return self.__warehouse_tree_hash

    @property
    def code_hash(self) -> str:
        return self.__code_hash

    def partitions(self, dataset: str) -> tuple[str, ...]:
        return self.__partitions[_dataset_label(dataset)]

    def source_entries(self) -> tuple[dict[str, Any], ...]:
        return tuple(dict(item) for item in self.__source_entries)

    def effective_row_count(self, dataset: str) -> int:
        return self.__effective_row_counts[_dataset_label(dataset)]

    def effective_content_hash(self, dataset: str) -> str:
        return self.__effective_content_hashes[_dataset_label(dataset)]

    def validate_integrity(self) -> None:
        exact_cutoff = datetime.combine(
            self.__formation_date,
            time(23, 59, 59),
            tzinfo=_SHANGHAI,
        )
        if self.__as_of != exact_cutoff:
            raise ValueError(
                "source attestation cutoff must equal formation-date "
                "23:59:59 Asia/Shanghai"
            )
        keys = {
            (_dataset_label(item.get("dataset")), str(item.get("partition")))
            for item in self.__source_entries
        }
        expected_keys = {
            (dataset, partition)
            for dataset, partitions in self.__partitions.items()
            for partition in partitions
        }
        if keys != expected_keys or len(keys) != len(self.__source_entries):
            raise ValueError("source attestation entries do not match complete inventory")
        for item in self.__source_entries:
            _count(item, "row_count")
            _count(item, "resolved_row_count")
            _count(item, "selected_revision_count")
            for field_name in (
                "content_hash",
                "file_sha256",
                "resolved_content_hash",
            ):
                value = item.get(field_name)
                if not isinstance(value, str) or not _is_sha256(value):
                    raise ValueError(
                        f"source attestation {field_name} is not a SHA-256 digest"
                    )
        source_payload = {
            "as_of": self.__as_of.astimezone(ZoneInfo("UTC")).isoformat(),
            "partitions": [dict(item) for item in self.__source_entries],
        }
        if self.__source_manifest_hash != _stable_hash(source_payload):
            raise ValueError("source attestation manifest hash mismatch")
        effective_rows = [
            {
                "dataset": dataset,
                "row_count": self.__effective_row_counts[dataset],
            }
            for dataset in sorted(_CONTROLLED_UNIVERSE_DATASETS)
        ]
        view_payload = {
            "source_snapshot": {
                **source_payload,
                "input_manifest_hash": self.__source_manifest_hash,
            },
            "effective_date": self.__formation_date.isoformat(),
            "effective_rows": effective_rows,
        }
        if self.__view_manifest_hash != _stable_hash(view_payload):
            raise ValueError("source attestation view manifest hash mismatch")
        if any(
            not _is_sha256(value)
            for value in self.__effective_content_hashes.values()
        ):
            raise ValueError("source attestation effective content hash is invalid")
        if any(
            isinstance(value, bool) or value < 0
            for value in self.__effective_row_counts.values()
        ):
            raise ValueError("source attestation effective row count is invalid")
        if (
            len(self.__warehouse_root_identity) != 3
            or not self.__warehouse_root_identity[0]
            or not all(
                isinstance(value, int) and not isinstance(value, bool)
                for value in self.__warehouse_root_identity[1:]
            )
        ):
            raise ValueError("source attestation warehouse root identity is invalid")
        for label, value in (
            ("warehouse tree", self.__warehouse_tree_hash),
            ("code", self.__code_hash),
        ):
            if not _is_sha256(value):
                raise ValueError(f"source attestation {label} hash is invalid")
        if self.__attestation_hash != _stable_hash(self._integrity_payload()):
            raise ValueError("source attestation integrity hash mismatch")

    def _integrity_payload(self) -> dict[str, Any]:
        return {
            "as_of": self.__as_of,
            "formation_date": self.__formation_date,
            "partitions": self.__partitions,
            "source_entries": self.__source_entries,
            "source_manifest_hash": self.__source_manifest_hash,
            "view_manifest_hash": self.__view_manifest_hash,
            "effective_row_counts": self.__effective_row_counts,
            "effective_content_hashes": self.__effective_content_hashes,
            "warehouse_root_identity": self.__warehouse_root_identity,
            "warehouse_tree_hash": self.__warehouse_tree_hash,
            "code_hash": self.__code_hash,
        }


class RouteFactPlan(Mapping[str, tuple[str, ...]]):
    """Deeply immutable fact plan produced only by the public plan builder."""

    __slots__ = ("__partitions", "__plan_hash", "__universe_catalog")

    def __init__(
        self,
        partitions: Mapping[str, tuple[str, ...]],
        *,
        universe_catalog: FrozenUniverseCatalog | None = None,
        _token: object | None = None,
    ) -> None:
        if _token is not _FACT_PLAN_TOKEN or universe_catalog is None:
            raise ValueError(
                "RouteFactPlan must be created by the fact-plan builder "
                "build_route_fact_plan"
            )
        universe_catalog.validate_integrity()
        self.__partitions = MappingProxyType(dict(partitions))
        self.__universe_catalog = universe_catalog
        self.__plan_hash = _stable_hash(
            {
                "partitions": self.__partitions,
                "universe_catalog_hash": universe_catalog.catalog_hash,
            }
        )

    def __getitem__(self, dataset: str) -> tuple[str, ...]:
        return self.__partitions[dataset]

    def __iter__(self):
        return iter(self.__partitions)

    def __len__(self) -> int:
        return len(self.__partitions)

    @property
    def universe_catalog(self) -> FrozenUniverseCatalog:
        return self.__universe_catalog

    def validate_integrity(self) -> None:
        self.__universe_catalog.validate_integrity()
        if self.__plan_hash != _stable_hash(
            {
                "partitions": self.__partitions,
                "universe_catalog_hash": self.__universe_catalog.catalog_hash,
            }
        ):
            raise ValueError("route fact plan integrity hash mismatch")


def build_source_catalog_attestation(
    warehouse: ResearchWarehouse,
    *,
    formation_date: date,
) -> _SourceCatalogAttestation:
    """Preflight the complete controlled inventory from a real warehouse."""

    if not isinstance(warehouse, ResearchWarehouse):
        raise TypeError("source attestation requires a real ResearchWarehouse")
    initial_root_identity, initial_tree_hash = _warehouse_state(warehouse)
    code_hash = _module_code_hash()
    cutoff = datetime.combine(
        formation_date,
        time(23, 59, 59),
        tzinfo=_SHANGHAI,
    )
    plan: dict[ResearchDatasetId, tuple[str, ...]] = {}
    metadata_by_key: dict[tuple[str, str], Mapping[str, Any]] = {}
    for label in _CONTROLLED_UNIVERSE_DATASETS:
        dataset = ResearchDatasetId(label)
        inventory = warehouse.partition_manifest(dataset)
        if inventory.empty or "partition_value" not in inventory:
            raise ValueError(
                f"controlled warehouse inventory is empty: {dataset.value}"
            )
        partitions = tuple(sorted(inventory["partition_value"].astype(str)))
        if dataset is ResearchDatasetId.INDUSTRY_DAILY:
            try:
                partitions = tuple(
                    partition
                    for partition in partitions
                    if date.fromisoformat(partition) <= formation_date
                )
            except ValueError as error:
                raise ValueError(
                    "industry_daily warehouse inventory contains an invalid date"
                ) from error
        if not partitions:
            raise ValueError(
                f"controlled warehouse inventory has no formation-time partition: "
                f"{dataset.value}"
            )
        validated = warehouse.validated_partition_manifest(dataset, partitions)
        rows = validated.to_dict(orient="records")
        if len(rows) != len(partitions):
            raise ValueError(
                f"validated controlled inventory is incomplete: {dataset.value}"
            )
        for row in rows:
            key = (dataset.value, str(row["partition_value"]))
            metadata_by_key[key] = row
        plan[dataset] = partitions

    materialized = ResearchQuery(warehouse).materialize_snapshot(plan, as_of=cutoff)
    source = materialized.input_manifest
    entries = source.get("partitions")
    if not isinstance(entries, Sequence):
        raise TypeError("warehouse materialization lacks source partition entries")
    normalized_entries = tuple(
        dict(item)
        for item in entries
        if isinstance(item, Mapping)
    )
    if len(normalized_entries) != len(entries):
        raise TypeError("warehouse materialization partition entries must be mappings")
    for item in normalized_entries:
        key = (_dataset_label(item.get("dataset")), str(item.get("partition")))
        metadata = metadata_by_key.get(key)
        if metadata is None:
            raise ValueError("materialized source is outside validated inventory")
        for field in ("row_count", "content_hash", "file_sha256", "quality_status"):
            actual = int(item[field]) if field == "row_count" else str(item[field])
            expected = (
                int(metadata[field]) if field == "row_count" else str(metadata[field])
            )
            if actual != expected:
                raise ValueError(
                    f"validated warehouse metadata changed during preflight: "
                    f"{key[0]}:{key[1]}:{field}"
                )

    effective_counts: dict[str, int] = {}
    effective_hashes: dict[str, str] = {}
    for dataset in plan:
        label = dataset.value
        records = _records(materialized.frame(dataset), label)
        if dataset in {
            ResearchDatasetId.INDUSTRY_MEMBER,
            ResearchDatasetId.THEME_MEMBER,
        }:
            records = _effective_relationship_records(
                records,
                dataset=label,
                formation_date=formation_date,
            )
        _, partition_reason = _partition_records(label, records, plan[dataset])
        if partition_reason is not None:
            raise ValueError(partition_reason)
        effective_counts[label] = len(records)
        effective_hashes[label] = _fact_content_hash(records, label)

    source_hash = source.get("input_manifest_hash")
    if not isinstance(source_hash, str):
        raise ValueError("warehouse materialization source hash is invalid")
    effective_rows = [
        {"dataset": dataset, "row_count": effective_counts[dataset]}
        for dataset in sorted(_CONTROLLED_UNIVERSE_DATASETS)
    ]
    view_payload = {
        "source_snapshot": source,
        "effective_date": formation_date.isoformat(),
        "effective_rows": effective_rows,
    }
    final_root_identity, final_tree_hash = _warehouse_state(warehouse)
    if (
        final_root_identity != initial_root_identity
        or final_tree_hash != initial_tree_hash
    ):
        raise ValueError("attested warehouse changed during source preflight")
    attestation = _SourceCatalogAttestation(
        as_of=cutoff,
        formation_date=formation_date,
        partitions={dataset.value: values for dataset, values in plan.items()},
        source_entries=normalized_entries,
        source_manifest_hash=source_hash,
        view_manifest_hash=_stable_hash(view_payload),
        effective_row_counts=effective_counts,
        effective_content_hashes=effective_hashes,
        warehouse_root_identity=final_root_identity,
        warehouse_tree_hash=final_tree_hash,
        code_hash=code_hash,
        _token=_ATTESTATION_TOKEN,
    )
    _ATTESTATION_REGISTRY[attestation] = _AttestationRegistration(
        warehouse=warehouse,
        attestation_hash=attestation.attestation_hash,
        code_hash=code_hash,
        root_identity=final_root_identity,
        tree_hash=final_tree_hash,
    )
    _require_registered_attestation(attestation)
    return attestation


def build_frozen_universe_catalog(
    fact_view: FormationFactView,
    *,
    source_attestation: _SourceCatalogAttestation,
) -> FrozenUniverseCatalog:
    """Match a Task 3 fact view to an independently attested source catalog."""

    if type(fact_view) is not FormationFactView:
        raise TypeError("catalog source must be a Task 3 FormationFactView")
    _require_registered_attestation(source_attestation)
    source_attestation.validate_integrity()
    source_manifest = fact_view.manifest
    source = source_manifest.get("source_snapshot")
    if not isinstance(source, Mapping):
        raise TypeError("FormationFactView manifest lacks source_snapshot")
    source_hash = source.get("input_manifest_hash")
    if not isinstance(source_hash, str) or not _is_sha256(source_hash):
        raise ValueError("source manifest hash is invalid")
    partitions = source.get("partitions")
    if not isinstance(partitions, Sequence):
        raise TypeError("source manifest lacks partitions")
    canonical = {
        "as_of": source.get("as_of"),
        "partitions": partitions,
    }
    if source_hash != _stable_hash(canonical):
        raise ValueError("source manifest hash does not match its partition catalog")
    source_as_of = _as_datetime(source.get("as_of"))
    if source_as_of is None or source_as_of.tzinfo is None:
        raise ValueError("source manifest as_of must be timezone-aware")
    effective_date = _as_date(source_manifest.get("effective_date"))
    if effective_date is None:
        raise ValueError("FormationFactView manifest lacks effective_date")
    exact_cutoff = datetime.combine(
        effective_date,
        time(23, 59, 59),
        tzinfo=_SHANGHAI,
    )
    if source_as_of != exact_cutoff:
        raise ValueError(
            "universe source cutoff must equal formation-date 23:59:59 Asia/Shanghai"
        )
    view_payload = {
        "source_snapshot": source,
        "effective_date": source_manifest.get("effective_date"),
        "effective_rows": source_manifest.get("effective_rows"),
    }
    view_hash = source_manifest.get("view_manifest_hash")
    if (
        not isinstance(view_hash, str)
        or not _is_sha256(view_hash)
        or view_hash != _stable_hash(view_payload)
    ):
        raise ValueError("FormationFactView manifest view_manifest_hash mismatch")

    controlled: dict[str, list[str]] = {
        dataset: [] for dataset in _CONTROLLED_UNIVERSE_DATASETS
    }
    seen: set[tuple[str, str]] = set()
    for raw in partitions:
        if not isinstance(raw, Mapping):
            raise TypeError("source partition entries must be mappings")
        dataset = _dataset_label(raw.get("dataset"))
        if dataset not in controlled:
            continue
        partition = str(raw.get("partition", "")).strip()
        key = (dataset, partition)
        if not partition or key in seen:
            raise ValueError("complete controlled universe contains invalid duplicates")
        seen.add(key)
        controlled[dataset].append(partition)
    if any(not values for values in controlled.values()):
        raise ValueError("source manifest lacks an attested controlled dataset")
    normalized_controlled = {
        dataset: tuple(sorted(values)) for dataset, values in controlled.items()
    }
    attested_partitions = {
        dataset: source_attestation.partitions(dataset)
        for dataset in _CONTROLLED_UNIVERSE_DATASETS
    }
    if normalized_controlled != attested_partitions:
        raise ValueError(
            "Task 3 view does not match the attested complete controlled inventory"
        )
    controlled_entries = sorted(
        (
            dict(raw)
            for raw in partitions
            if isinstance(raw, Mapping)
            and _dataset_label(raw.get("dataset"))
            in _CONTROLLED_UNIVERSE_DATASETS
        ),
        key=lambda item: (_dataset_label(item.get("dataset")), str(item.get("partition"))),
    )
    controlled_source_payload = {
        "as_of": source.get("as_of"),
        "partitions": controlled_entries,
    }
    controlled_source_hash = _stable_hash(controlled_source_payload)
    if controlled_source_hash != source_attestation.source_manifest_hash:
        raise ValueError(
            "Task 3 source subset does not match the attested complete controlled inventory"
        )
    effective_rows = source_manifest.get("effective_rows")
    if not isinstance(effective_rows, Sequence):
        raise TypeError("FormationFactView manifest lacks effective_rows")
    expected_counts: dict[str, int] = {}
    for raw in effective_rows:
        if not isinstance(raw, Mapping):
            raise TypeError("effective row entries must be mappings")
        dataset = _dataset_label(raw.get("dataset"))
        if dataset in expected_counts:
            raise ValueError(f"duplicate effective row entry: {dataset}")
        expected_counts[dataset] = _count(raw, "row_count")
    effective_hashes: dict[str, str] = {}
    manifest_by_key = {
        (_dataset_label(raw.get("dataset")), str(raw.get("partition"))): raw
        for raw in partitions
        if isinstance(raw, Mapping)
    }
    controlled_effective_rows = []
    for dataset, values in normalized_controlled.items():
        records = _records(fact_view.dataset(dataset), dataset)
        expected_count = expected_counts.get(dataset)
        if expected_count != len(records):
            raise ValueError(
                f"FormationFactView {dataset} frame/effective row mismatch"
            )
        if expected_count != source_attestation.effective_row_count(dataset):
            raise ValueError(
                f"FormationFactView {dataset} row count differs from attested view"
            )
        partitioned, reason = _partition_records(dataset, records, values)
        if reason is not None:
            raise ValueError(reason)
        effective_hash = _fact_content_hash(records, dataset)
        if effective_hash != source_attestation.effective_content_hash(dataset):
            raise ValueError(
                f"FormationFactView {dataset} differs from attested effective content"
            )
        effective_hashes[dataset] = effective_hash
        controlled_effective_rows.append(
            {"dataset": dataset, "row_count": expected_count}
        )
        if dataset == "industry_daily":
            for partition in values:
                declared = manifest_by_key[(dataset, partition)].get(
                    "resolved_content_hash"
                )
                actual = _fact_content_hash(partitioned[partition], dataset)
                if declared != actual:
                    raise ValueError(
                        f"FormationFactView {dataset}:{partition} content hash mismatch"
                    )
    controlled_view_payload = {
        "source_snapshot": {
            **controlled_source_payload,
            "input_manifest_hash": controlled_source_hash,
        },
        "effective_date": source_manifest.get("effective_date"),
        "effective_rows": sorted(
            controlled_effective_rows,
            key=lambda item: item["dataset"],
        ),
    }
    if _stable_hash(controlled_view_payload) != source_attestation.view_manifest_hash:
        raise ValueError("Task 3 controlled view manifest differs from attestation")
    catalog = FrozenUniverseCatalog(
        source_manifest_hash=controlled_source_hash,
        source_view_manifest_hash=source_attestation.view_manifest_hash,
        source_attestation_hash=source_attestation.attestation_hash,
        partitions=normalized_controlled,
        as_of=source_as_of,
        formation_date=effective_date,
        effective_content_hashes=effective_hashes,
        source_attestation=source_attestation,
        _token=_CATALOG_TOKEN,
    )
    _require_registered_attestation(source_attestation)
    return catalog


def build_route_fact_plan(
    *,
    formation_date: date,
    earnings_report_periods: Iterable[date],
    event_start: date,
    universe_catalog: FrozenUniverseCatalog,
    event_end: date | None = None,
) -> RouteFactPlan:
    """Build the sole real-fact plan accepted by the six-route scanner."""

    end = event_end or formation_date
    if not isinstance(universe_catalog, FrozenUniverseCatalog):
        raise TypeError(
            "universe_catalog must come from build_frozen_universe_catalog"
        )
    universe_catalog.validate_integrity()
    exact_cutoff = datetime.combine(
        formation_date,
        time(23, 59, 59),
        tzinfo=_SHANGHAI,
    )
    if (
        universe_catalog.formation_date != formation_date
        or universe_catalog.as_of != exact_cutoff
    ):
        raise ValueError("universe catalog does not match the formation date")
    reports = _dates(earnings_report_periods, "earnings_report_periods")
    if event_start > end or end > formation_date:
        raise ValueError("event window must end on or before formation_date")
    announcement_months = _month_range(event_start, end)
    earnings_months = tuple(
        sorted(
            {
                month
                for period in reports
                for month in _month_range(
                    date(min(period.year, formation_date.year), 1, 1),
                    formation_date,
                )
            }
        )
    )
    report_partitions = tuple(
        period.isoformat() for period in reports if period <= formation_date
    )
    if not report_partitions:
        raise ValueError("at least one declared earnings period must be completed")
    plan = {
        "industry_member": universe_catalog.partitions("industry_member"),
        "theme_member": universe_catalog.partitions("theme_member"),
        "earnings_forecast": earnings_months,
        "earnings_express": earnings_months,
        "income_statement": report_partitions,
        "announcement": announcement_months,
        "industry_daily": universe_catalog.partitions("industry_daily"),
        "main_business": report_partitions,
        "repurchase": announcement_months,
        "balance_sheet": report_partitions,
        "cash_flow": report_partitions,
    }
    return RouteFactPlan(
        plan,
        universe_catalog=universe_catalog,
        _token=_FACT_PLAN_TOKEN,
    )


def derive_declared_route_windows(
    *,
    formation_date: date,
    event_lookback_calendar_days: int,
    completed_quarter_count: int,
    future_quarter_count: int,
) -> tuple[date, tuple[date, ...]]:
    """Derive windows from explicit preregistered counts; no production defaults."""

    for label, value in (
        ("event_lookback_calendar_days", event_lookback_calendar_days),
        ("completed_quarter_count", completed_quarter_count),
        ("future_quarter_count", future_quarter_count),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{label} must be a positive integer")
    current_index = formation_date.year * 4 + (formation_date.month - 1) // 3
    current_end = _quarter_end(current_index)
    last_completed = (
        current_index if formation_date >= current_end else current_index - 1
    )
    completed = tuple(
        _quarter_end(index)
        for index in range(
            last_completed - completed_quarter_count + 1,
            last_completed + 1,
        )
    )
    future = tuple(
        _quarter_end(index)
        for index in range(
            last_completed + 1,
            last_completed + future_quarter_count + 1,
        )
    )
    event_start = formation_date - timedelta(days=event_lookback_calendar_days - 1)
    return event_start, (*completed, *future)


def build_route_window_policy(
    *,
    formation_date: date,
    fact_plan: Mapping[Any, Iterable[str]],
    earnings_report_periods: Iterable[date],
    event_start: date,
    price_absolute_tail_fraction: float,
    event_end: date | None = None,
) -> RouteWindowPolicy:
    """Freeze exact route datasets and validate them against the materialization plan."""

    if isinstance(price_absolute_tail_fraction, bool) or not (
        0 < float(price_absolute_tail_fraction) <= 1
    ):
        raise ValueError("price absolute tail fraction must be in (0, 1]")
    if not isinstance(fact_plan, RouteFactPlan):
        raise TypeError("fact_plan must come directly from build_route_fact_plan")
    fact_plan.validate_integrity()
    end = event_end or formation_date
    reports = _dates(earnings_report_periods, "earnings_report_periods")
    normalized_plan = {
        _dataset_label(dataset): _partitions(values, _dataset_label(dataset))
        for dataset, values in fact_plan.items()
    }
    required_plan = build_route_fact_plan(
        formation_date=formation_date,
        earnings_report_periods=reports,
        event_start=event_start,
        universe_catalog=fact_plan.universe_catalog,
        event_end=end,
    )
    if normalized_plan != required_plan:
        raise ValueError("fact_plan must exactly equal the frozen route fact plan")

    routes: dict[DiscoveryRoute, dict[str, tuple[str, ...]]] = {
        DiscoveryRoute.HOTSPOT: {
            "sector_hotspot": (formation_date.isoformat(),),
            "industry_member": required_plan["industry_member"],
            "theme_member": required_plan["theme_member"],
        },
        DiscoveryRoute.EARNINGS: {
            "earnings_forecast": required_plan["earnings_forecast"],
            "earnings_express": required_plan["earnings_express"],
            "income_statement": required_plan["income_statement"],
        },
        DiscoveryRoute.COMPANY_EVENT: {
            "announcement": required_plan["announcement"],
        },
        DiscoveryRoute.INDUSTRY_CYCLE: {
            "industry_daily": required_plan["industry_daily"],
            "main_business": required_plan["main_business"],
        },
        DiscoveryRoute.DISTRESS_REPAIR: {
            "repurchase": required_plan["repurchase"],
            "income_statement": required_plan["income_statement"],
            "balance_sheet": required_plan["balance_sheet"],
            "cash_flow": required_plan["cash_flow"],
        },
        DiscoveryRoute.PRICE_ANOMALY: {
            "stock_trading_context": (formation_date.isoformat(),),
        },
    }
    frozen_routes = MappingProxyType(
        {
            route: MappingProxyType(dict(datasets))
            for route, datasets in routes.items()
        }
    )
    frozen_gaps = MappingProxyType(
        {
            DiscoveryRoute.INDUSTRY_CYCLE: (_CYCLE_GAP,),
            DiscoveryRoute.DISTRESS_REPAIR: (_REPAIR_GAP,),
        }
    )
    policy_values = {
        "formation_date": formation_date,
        "route_partitions": frozen_routes,
        "earnings_report_periods": reports,
        "event_start": event_start,
        "event_end": end,
        "price_absolute_tail_fraction": float(price_absolute_tail_fraction),
        "coverage_gaps": frozen_gaps,
        "universe_source_manifest_hash": (
            fact_plan.universe_catalog.source_manifest_hash
        ),
        "universe_source_view_manifest_hash": (
            fact_plan.universe_catalog.source_view_manifest_hash
        ),
        "universe_source_attestation_hash": (
            fact_plan.universe_catalog.source_attestation_hash
        ),
        "universe_catalog_hash": fact_plan.universe_catalog.catalog_hash,
        "universe_effective_content_hashes": MappingProxyType(
            {
                dataset: fact_plan.universe_catalog.effective_content_hash(dataset)
                for dataset in _CONTROLLED_UNIVERSE_DATASETS
            }
        ),
        "_source_attestation": fact_plan.universe_catalog.source_attestation,
    }
    return RouteWindowPolicy(
        **policy_values,
        policy_hash=_route_policy_hash_values(**policy_values),
        _token=_POLICY_TOKEN,
    )


def scan_routes(
    snapshot: Any,
    window_policy: RouteWindowPolicy,
) -> tuple[tuple[RouteScanManifest, ...], tuple[ResearchHypothesis, ...]]:
    """Scan all six frozen universes and merge leads by security without voting."""

    if not isinstance(window_policy, RouteWindowPolicy):
        raise TypeError("window_policy must be a frozen RouteWindowPolicy")
    if window_policy.policy_hash != _route_policy_hash(window_policy):
        raise ValueError("route policy integrity hash mismatch")
    _require_registered_attestation(window_policy._source_attestation)
    formation_date = snapshot.analysis_date
    cutoff = snapshot.as_of
    if formation_date != window_policy.formation_date:
        raise ValueError("snapshot and route policy formation dates differ")
    exact_cutoff = datetime.combine(
        formation_date,
        time(23, 59, 59),
        tzinfo=_SHANGHAI,
    )
    if cutoff != exact_cutoff:
        raise ValueError(
            "snapshot cutoff must equal formation-date 23:59:59 Asia/Shanghai"
        )
    view = _SnapshotView(snapshot)
    view.validate_fact_partitions(window_policy)
    scans = tuple(
        _scan_route(
            route,
            view=view,
            policy=window_policy,
            formation_date=formation_date,
            cutoff=cutoff,
        )
        for route in _ROUTE_ORDER
    )
    manifests = tuple(item[0] for item in scans)
    leads = tuple(lead for _, route_leads in scans for lead in route_leads)
    hypotheses = _merge_leads(leads, formation_date, cutoff)
    _require_registered_attestation(window_policy._source_attestation)
    return manifests, hypotheses


class _SnapshotView:
    def __init__(self, snapshot: Any) -> None:
        if not hasattr(snapshot, "facts") or not hasattr(snapshot, "features"):
            raise TypeError("snapshot must expose public facts and features views")
        facts_manifest = getattr(snapshot.facts, "manifest", None)
        if not isinstance(facts_manifest, Mapping):
            raise TypeError("snapshot facts view must expose its materialized manifest")
        source = facts_manifest.get("source_snapshot")
        if not isinstance(source, Mapping):
            raise TypeError("facts manifest lacks source_snapshot")
        source_as_of = _as_datetime(source.get("as_of"))
        if (
            source_as_of is None
            or source_as_of.tzinfo is None
            or source_as_of != snapshot.as_of
        ):
            raise ValueError("fact source manifest cutoff does not match snapshot")
        partitions = source.get("partitions")
        if not isinstance(partitions, Sequence):
            raise TypeError("fact source manifest lacks partitions")
        effective_date = _as_date(facts_manifest.get("effective_date"))
        if effective_date != snapshot.analysis_date:
            raise ValueError("facts manifest effective_date does not match snapshot")
        effective_rows = facts_manifest.get("effective_rows")
        if not isinstance(effective_rows, Sequence):
            raise TypeError("facts manifest lacks effective_rows")
        self.snapshot = snapshot
        self.source_manifest = source
        self.fact_manifest_errors: list[str] = []
        source_hash = source.get("input_manifest_hash")
        source_payload = {
            "as_of": source.get("as_of"),
            "partitions": partitions,
        }
        if (
            not isinstance(source_hash, str)
            or not _is_sha256(source_hash)
            or source_hash != _stable_hash(source_payload)
        ):
            self.fact_manifest_errors.append("fact source manifest hash mismatch")
        view_hash = facts_manifest.get("view_manifest_hash")
        view_payload = {
            "source_snapshot": source,
            "effective_date": facts_manifest.get("effective_date"),
            "effective_rows": effective_rows,
        }
        if (
            not isinstance(view_hash, str)
            or not _is_sha256(view_hash)
            or view_hash != _stable_hash(view_payload)
        ):
            self.fact_manifest_errors.append("fact view manifest hash mismatch")
        self.effective_rows: dict[str, int] = {}
        for raw in effective_rows:
            if not isinstance(raw, Mapping):
                raise TypeError("effective row entries must be mappings")
            dataset = _dataset_label(raw.get("dataset"))
            if dataset in self.effective_rows:
                raise ValueError(f"duplicate effective row entry: {dataset}")
            self.effective_rows[dataset] = _count(raw, "row_count")
        self.partition_rows: dict[tuple[str, str], Mapping[str, Any]] = {}
        for raw in partitions:
            if not isinstance(raw, Mapping):
                raise TypeError("fact partition manifest entries must be mappings")
            key = (_dataset_label(raw.get("dataset")), str(raw.get("partition")))
            if key in self.partition_rows:
                raise ValueError(f"duplicate fact partition manifest entry: {key}")
            self.partition_rows[key] = raw

    def validate_fact_partitions(self, policy: RouteWindowPolicy) -> None:
        self.universe_effective_content_hashes = dict(
            policy.universe_effective_content_hashes
        )
        requested = {
            (dataset, partition)
            for datasets in policy.route_partitions.values()
            for dataset, partitions in datasets.items()
            if dataset not in _FEATURE_DATASETS
            for partition in partitions
        }
        unexpected = sorted(set(self.partition_rows).difference(requested))
        if unexpected:
            labels = ", ".join(_partition_key(*item) for item in unexpected)
            raise ValueError(f"source manifest contains unrequested fact partition: {labels}")
        controlled_expected = {
            (dataset, partition)
            for dataset in _CONTROLLED_UNIVERSE_DATASETS
            for partition in next(
                datasets[dataset]
                for datasets in policy.route_partitions.values()
                if dataset in datasets
            )
        }
        controlled_actual = {
            key for key in self.partition_rows if key[0] in _CONTROLLED_UNIVERSE_DATASETS
        }
        if controlled_actual != controlled_expected:
            raise ValueError(
                "source manifest does not match the frozen complete controlled universe"
            )
        controlled_entries = sorted(
            (dict(self.partition_rows[key]) for key in controlled_actual),
            key=lambda item: (
                _dataset_label(item.get("dataset")),
                str(item.get("partition")),
            ),
        )
        controlled_source_payload = {
            "as_of": self.source_manifest.get("as_of"),
            "partitions": controlled_entries,
        }
        controlled_source_hash = _stable_hash(controlled_source_payload)
        if controlled_source_hash != policy.universe_source_manifest_hash:
            raise ValueError(
                "snapshot does not match the attested controlled source subset"
            )
        effective_counts = {
            dataset: self.effective_rows.get(dataset)
            for dataset in _CONTROLLED_UNIVERSE_DATASETS
        }
        if any(value is None for value in effective_counts.values()):
            raise ValueError("snapshot controlled effective row commitment is incomplete")
        controlled_view_payload = {
            "source_snapshot": {
                **controlled_source_payload,
                "input_manifest_hash": controlled_source_hash,
            },
            "effective_date": self.snapshot.analysis_date.isoformat(),
            "effective_rows": [
                {"dataset": dataset, "row_count": effective_counts[dataset]}
                for dataset in sorted(_CONTROLLED_UNIVERSE_DATASETS)
            ],
        }
        if (
            _stable_hash(controlled_view_payload)
            != policy.universe_source_view_manifest_hash
        ):
            raise ValueError(
                "snapshot does not match the attested controlled effective view"
            )
        controlled_partitions = {
            dataset: tuple(
                key[1] for key in sorted(controlled_expected) if key[0] == dataset
            )
            for dataset in _CONTROLLED_UNIVERSE_DATASETS
        }
        attestation_payload = {
            "as_of": datetime.combine(
                policy.formation_date,
                time(23, 59, 59),
                tzinfo=_SHANGHAI,
            ),
            "formation_date": policy.formation_date,
            "partitions": controlled_partitions,
            "source_entries": controlled_entries,
            "source_manifest_hash": controlled_source_hash,
            "view_manifest_hash": policy.universe_source_view_manifest_hash,
            "effective_row_counts": effective_counts,
            "effective_content_hashes": dict(
                policy.universe_effective_content_hashes
            ),
            "warehouse_root_identity": (
                policy._source_attestation.warehouse_root_identity
            ),
            "warehouse_tree_hash": policy._source_attestation.warehouse_tree_hash,
            "code_hash": policy._source_attestation.code_hash,
        }
        if (
            _stable_hash(attestation_payload)
            != policy.universe_source_attestation_hash
        ):
            raise ValueError("snapshot controlled source attestation hash mismatch")

    def read(self, dataset: str, requested: tuple[str, ...]) -> RouteDataset:
        if dataset in _FEATURE_DATASETS:
            return self._read_feature(dataset, requested)
        raw = self.snapshot.facts.dataset(dataset)
        records = _records(raw, dataset)
        manifest_rows = [
            self.partition_rows[(dataset, partition)]
            for partition in requested
            if (dataset, partition) in self.partition_rows
        ]
        actual = tuple(
            partition
            for partition in requested
            if (dataset, partition) in self.partition_rows
        )
        resolved = sum(_count(item, "resolved_row_count") for item in manifest_rows)
        missing = [
            f"{dataset}:{partition}"
            for partition in requested
            if (dataset, partition) not in self.partition_rows
        ]
        effective_count = self.effective_rows.get(dataset)
        if effective_count is None:
            missing.append(f"{dataset}: effective manifest lacks dataset row count")
        elif len(records) != effective_count:
            missing.append(
                f"{dataset}: materialized frame has {len(records)} rows but effective "
                f"manifest declares {effective_count}"
            )
        relationship_view = dataset in {"industry_member", "theme_member"}
        if not relationship_view and len(records) != resolved:
            missing.append(
                f"{dataset}: materialized frame has {len(records)} rows but source "
                f"manifest resolves {resolved}"
            )
        content_proof: Any = None
        try:
            if relationship_view:
                actual_content_hash = _fact_content_hash(records, dataset)
                declared_content_hash = self.universe_effective_content_hashes.get(
                    dataset
                )
                content_proof = actual_content_hash
                if actual_content_hash != declared_content_hash:
                    missing.append(
                        f"{dataset}: effective relation content hash mismatch"
                    )
            else:
                partitioned, partition_reason = _partition_records(
                    dataset,
                    records,
                    requested,
                )
                if partition_reason is not None:
                    missing.append(partition_reason)
                    content_proof = partition_reason
                else:
                    hashes = {
                        partition: _fact_content_hash(
                            partitioned[partition],
                            dataset,
                        )
                        for partition in requested
                    }
                    content_proof = hashes
                    for item in manifest_rows:
                        partition = str(item["partition"])
                        declared = item.get("resolved_content_hash")
                        if hashes[partition] != declared:
                            missing.append(
                                f"{dataset}:{partition} content hash mismatch"
                            )
        except ValueError as error:
            content_proof = str(error)
            missing.append(str(error))
        expected = (
            max(effective_count or 0, len(records))
            if relationship_view
            else max(resolved, len(records))
        )
        integrity_errors = list(self.fact_manifest_errors)
        if missing:
            integrity_errors.extend(missing)
        verified = not integrity_errors
        if integrity_errors:
            missing.append(
                f"{dataset}: fail closed because materialized facts are not "
                "fully proven by the manifest: "
                + "; ".join(dict.fromkeys(integrity_errors))
            )
        manifest_hash = _stable_hash(
            {
                "source_hash": self.source_manifest.get("input_manifest_hash"),
                "dataset": dataset,
                "requested": requested,
                "partitions": manifest_rows,
                "actual_content": content_proof,
            }
        )
        return RouteDataset(
            dataset=dataset,
            requested_partitions=requested,
            actual_partitions=actual,
            records=records,
            expected_records=expected,
            missing=tuple(missing),
            input_hash=manifest_hash,
            verified=verified,
        )

    def _read_feature(self, dataset: str, requested: tuple[str, ...]) -> RouteDataset:
        records = _records(self.snapshot.features.read(dataset), dataset)
        expected = int(
            self.snapshot.sector_rows
            if dataset == "sector_hotspot"
            else self.snapshot.stock_rows
        )
        missing = ()
        verified = len(records) == expected
        if not verified:
            missing = (
                f"{dataset}: fail closed because materialized feature has "
                f"{len(records)} rows but snapshot declares {expected}",
            )
        return RouteDataset(
            dataset=dataset,
            requested_partitions=requested,
            actual_partitions=requested,
            records=records,
            expected_records=max(expected, len(records)),
            missing=missing,
            input_hash=_stable_hash(
                {
                    "cache_key": getattr(self.snapshot, "cache_key", None),
                    "dataset": dataset,
                    "requested": requested,
                    "records": records,
                }
            ),
            verified=verified,
        )


def _scan_route(
    route: DiscoveryRoute,
    *,
    view: _SnapshotView,
    policy: RouteWindowPolicy,
    formation_date: date,
    cutoff: datetime,
) -> tuple[RouteScanManifest, tuple[_Lead, ...]]:
    datasets = tuple(
        view.read(dataset, partitions)
        for dataset, partitions in policy.route_partitions[route].items()
    )
    exclusions: list[str] = []
    route_missing: list[str] = []
    if any(not item.verified for item in datasets):
        leads = ()
        route_missing.append(
            "route fail closed because at least one input dataset failed manifest "
            "verification"
        )
    elif route is DiscoveryRoute.HOTSPOT:
        leads = _hotspot_leads(
            datasets,
            formation_date,
            cutoff,
            exclusions,
            route_missing,
        )
    elif route is DiscoveryRoute.EARNINGS:
        leads = _earnings_leads(datasets, policy, cutoff, exclusions)
    elif route is DiscoveryRoute.COMPANY_EVENT:
        leads = _event_leads(datasets, policy, cutoff, exclusions)
    elif route is DiscoveryRoute.PRICE_ANOMALY:
        leads = _price_leads(datasets, policy, cutoff, exclusions)
    else:
        leads = ()
        exclusions.append(
            "current real inputs are enumerated but cannot scientifically derive "
            "this route's admission semantics"
        )

    requested = tuple(
        _partition_key(item.dataset, partition)
        for item in datasets
        for partition in item.requested_partitions
    )
    actual = tuple(
        _partition_key(item.dataset, partition)
        for item in datasets
        for partition in item.actual_partitions
    )
    missing = [reason for item in datasets for reason in item.missing]
    missing.extend(route_missing)
    missing.extend(policy.coverage_gaps.get(route, ()))
    expected = sum(item.expected_records for item in datasets)
    scanned = sum(len(item.records) for item in datasets)
    if scanned < expected and not missing:
        missing.append(f"route resolved {scanned}/{expected} expected source rows")
    exclusions.extend(
        f"{item.dataset}: {reason}"
        for item in datasets
        for reason in item.exclusions
    )
    deep_required = sum(
        lead.route is DiscoveryRoute.COMPANY_EVENT for lead in leads
    )
    deep_completed = sum(
        lead.route is DiscoveryRoute.COMPANY_EVENT
        and not lead.evidence.needs_deep_read
        for lead in leads
    )
    manifest = RouteScanManifest(
        route=route,
        formation_date=formation_date,
        cutoff=cutoff,
        requested_partitions=requested,
        actual_partitions=actual,
        expected_records=expected,
        scanned_records=scanned,
        triggered_records=len(leads),
        deduplicated_records=len({lead.security_id for lead in leads}),
        missing=tuple(dict.fromkeys(missing)),
        exclusions=tuple(dict.fromkeys(exclusions)),
        manual_boundaries=_manual_boundaries(route, policy),
        deep_read_required=deep_required,
        deep_read_completed=deep_completed,
        input_hash=_stable_hash(
            {
                "route": route,
                "cutoff": cutoff,
                "datasets": [item.input_hash for item in datasets],
                "policy": policy.route_partitions[route],
                "price_tail": policy.price_absolute_tail_fraction,
            }
        ),
    )
    return manifest, leads


def _hotspot_leads(
    datasets: tuple[RouteDataset, ...],
    formation_date: date,
    cutoff: datetime,
    exclusions: list[str],
    missing: list[str],
) -> tuple[_Lead, ...]:
    by_name = {item.dataset: item.records for item in datasets}
    groups = by_name["sector_hotspot"]
    members = (
        *(("industry", row) for row in by_name["industry_member"]),
        *(("theme", row) for row in by_name["theme_member"]),
    )
    active_members: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    member_exclusion_counts: dict[str, int] = {}
    for member_type, member in members:
        declared_type = str(member.get("group_type", member_type))
        if declared_type != member_type:
            reason = "relation type mismatch"
        elif not _effective(member, formation_date):
            reason = "invalid effective interval"
        elif _security_id(member) is None:
            reason = "missing security mapping"
        elif (temporal_reason := _temporal_reason(member, cutoff)) is not None:
            reason = temporal_reason
        else:
            member_code = str(
                member.get("industry_code")
                or member.get("theme_code")
                or member.get("group_code")
                or ""
            ).strip()
            if not member_code:
                reason = "missing group mapping"
            else:
                active_members.setdefault((member_type, member_code), []).append(member)
                continue
        member_exclusion_counts[reason] = member_exclusion_counts.get(reason, 0) + 1
    exclusions.extend(
        f"effective membership: excluded {count} row(s): {reason}"
        for reason, count in sorted(member_exclusion_counts.items())
    )

    observation_keys: set[tuple[str, str]] = set()
    duplicate_observations: set[tuple[str, str]] = set()
    for group in groups:
        if _feature_after_cutoff(group, formation_date):
            continue
        group_type = str(group.get("group_type", "")).strip()
        group_code = str(group.get("group_code", "")).strip()
        if group_type not in {"industry", "theme"} or not group_code:
            exclusions.append("sector_hotspot: invalid group type or code")
            continue
        key = (group_type, group_code)
        if key in observation_keys:
            duplicate_observations.add(key)
        observation_keys.add(key)
    if duplicate_observations:
        missing.extend(
            f"sector_hotspot: duplicate observation for {group_type}:{group_code}"
            for group_type, group_code in sorted(duplicate_observations)
        )
        return ()
    for group_type, group_code in sorted(set(active_members).difference(observation_keys)):
        missing.append(
            f"sector_hotspot: missing observation for {group_type}:{group_code}"
        )
    for group_type, group_code in sorted(observation_keys.difference(active_members)):
        exclusions.append(
            f"sector_hotspot: {group_type}:{group_code} has no effective membership"
        )

    leads: list[_Lead] = []
    for group in groups:
        if _feature_after_cutoff(group, formation_date):
            exclusions.append("sector_hotspot: feature analysis_date is not formation date")
            continue
        missing_fields = _missing_hotspot_fields(group)
        if missing_fields:
            exclusions.append(
                "sector_hotspot: missing 6.2 fields " + ", ".join(missing_fields)
            )
            continue
        if not (
            _number(group["relative_return_20d"]) > 0
            and _number(group["median_return_20d"]) > 0
            and _number(group["breadth_20d"]) > 0.5
        ):
            exclusions.append("sector_hotspot: no positive majority common change")
            continue
        group_type = str(group.get("group_type", ""))
        group_code = str(group.get("group_code", ""))
        for member in active_members.get((group_type, group_code), ()):
            security_id = _security_id(member)
            assert security_id is not None
            evidence_id = _stable_hash(
                ("hotspot", group_type, group_code, security_id, formation_date)
            )
            leads.append(
                _lead(
                    security_id,
                    DiscoveryRoute.HOTSPOT,
                    "sector_hotspot+effective_membership",
                    evidence_id,
                    _as_datetime(member.get("available_at")),
                    "reproducible positive group co-movement with an effective, "
                    "traceable company relationship",
                    "verify business materiality and whether retreat counterevidence "
                    "weakens the 10-30 day transmission",
                    fact_summary=(
                        "relative return, median return, majority breadth, turnover "
                        "attention, head contribution and retreat counterevidence observed"
                    ),
                    internal_only=True,
                )
            )
    return tuple(leads)


def _earnings_leads(
    datasets: tuple[RouteDataset, ...],
    policy: RouteWindowPolicy,
    cutoff: datetime,
    exclusions: list[str],
) -> tuple[_Lead, ...]:
    leads: list[_Lead] = []
    allowed_periods = set(policy.earnings_report_periods)
    for item in datasets:
        for row in item.records:
            reason = _temporal_reason(row, cutoff)
            report_period = _as_date(row.get("report_period"))
            if reason is not None or report_period not in allowed_periods:
                exclusions.append(f"{item.dataset}: outside visible declared report period")
                continue
            if not _earnings_has_operating_fact(item.dataset, row):
                exclusions.append(f"{item.dataset}: no new operating value")
                continue
            security_id = _security_id(row)
            if security_id is None:
                exclusions.append(f"{item.dataset}: missing security mapping")
                continue
            evidence_id = str(
                row.get("evidence_id")
                or _stable_hash(
                    (
                        DiscoveryRoute.EARNINGS,
                        item.dataset,
                        security_id,
                        report_period,
                        row.get("available_at"),
                    )
                )
            )
            leads.append(
                _lead(
                    security_id,
                    DiscoveryRoute.EARNINGS,
                    item.dataset,
                    evidence_id,
                    _as_datetime(row.get("available_at")),
                    "formation-time-visible formal disclosure contains a new operating value",
                    "compare with company history, peers, published expectations, cash "
                    "quality and one-off items before claiming materiality",
                    preliminary_opportunity=OpportunityType.EARNINGS_REVALUATION,
                )
            )
    return tuple(leads)


def _event_leads(
    datasets: tuple[RouteDataset, ...],
    policy: RouteWindowPolicy,
    cutoff: datetime,
    exclusions: list[str],
) -> tuple[_Lead, ...]:
    rows = datasets[0].records
    leads: list[_Lead] = []
    for row in rows:
        temporal_reason = _temporal_reason(row, cutoff)
        if temporal_reason is not None:
            exclusions.append(f"announcement: {temporal_reason}")
            continue
        published = _as_datetime(row.get("announcement_time"))
        if published is None or published.tzinfo is None:
            exclusions.append("announcement: missing or timezone-naive announcement_time")
            continue
        if (
            published > cutoff
            or not policy.event_start
            <= published.astimezone(_SHANGHAI).date()
            <= policy.event_end
        ):
            exclusions.append("announcement: outside declared visible event window")
            continue
        formal = (
            _present(row.get("announcement_id"))
            and (_present(row.get("url")) or _present(row.get("pdf_path")))
        )
        security_id = _security_id(row)
        title_recall = bool(row.get("candidate_event_types"))
        if not formal or security_id is None or not title_recall:
            exclusions.append("announcement: not a formal direct title-recall candidate")
            continue
        deep_hash = row.get("deep_read_input_hash")
        deep_complete = (
            _strict_true(row.get("deep_read_completed"))
            and isinstance(deep_hash, str)
            and _is_sha256(deep_hash)
            and all(
                _present(row.get(field_name))
                for field_name in (
                    "body",
                    "amount",
                    "subject",
                    "execution_conditions",
                )
            )
        )
        evidence_id = str(row.get("evidence_id") or row["announcement_id"])
        leads.append(
            _lead(
                security_id,
                DiscoveryRoute.COMPANY_EVENT,
                "announcement",
                evidence_id,
                _as_datetime(row.get("available_at")),
                "a formal, directly related event may transmit through revenue, "
                "profit, cash, risk or valuation",
                "finish an auditable body deep read before economic interpretation",
                fact_summary=(
                    str(row.get("economic_fact_summary")) if deep_complete else None
                ),
                needs_deep_read=not deep_complete,
                usable=deep_complete,
                deep_read_input_hash=str(deep_hash) if deep_complete else None,
                preliminary_opportunity=(
                    OpportunityType.COMPANY_EVENT_REVALUATION
                    if deep_complete
                    else None
                ),
            )
        )
    return tuple(leads)


def _price_leads(
    datasets: tuple[RouteDataset, ...],
    policy: RouteWindowPolicy,
    cutoff: datetime,
    exclusions: list[str],
) -> tuple[_Lead, ...]:
    rows = datasets[0].records
    eligible: list[tuple[Mapping[str, Any], float]] = []
    for row in rows:
        if _feature_after_cutoff(row, policy.formation_date):
            exclusions.append("stock_trading_context: wrong analysis_date")
            continue
        if "tradable" in row and not _strict_true(row.get("tradable")):
            exclusions.append("stock_trading_context: explicitly non-tradable")
            continue
        coverage = str(row.get("coverage_status", ""))
        relative = _maybe_number(row.get("relative_return_20d"))
        if (
            _security_id(row) is None
            or coverage not in {"complete", "complete_with_declared_gaps"}
            or relative is None
        ):
            exclusions.append("stock_trading_context: incomplete market-relative observation")
            continue
        eligible.append((row, abs(relative)))
    if not eligible:
        return ()
    tail_count = max(1, math.ceil(len(eligible) * policy.price_absolute_tail_fraction))
    threshold = sorted((value for _, value in eligible), reverse=True)[tail_count - 1]
    leads: list[_Lead] = []
    for row, absolute_relative in eligible:
        if absolute_relative < threshold:
            continue
        security_id = _security_id(row)
        assert security_id is not None
        leads.append(
            _lead(
                security_id,
                DiscoveryRoute.PRICE_ANOMALY,
                "stock_trading_context",
                str(
                    row.get("evidence_id")
                    or _stable_hash(
                        (
                            DiscoveryRoute.PRICE_ANOMALY,
                            security_id,
                            policy.formation_date,
                            row.get("relative_return_20d"),
                        )
                    )
                ),
                _as_datetime(row.get("available_at")),
                "absolute market-relative return is in the preregistered formation-day tail",
                "investigate a visible cause; the price result is not a value source",
                fact_summary=(
                    f"absolute 20-day market-relative return {absolute_relative:.8g}; "
                    f"tail fraction {policy.price_absolute_tail_fraction:.8g}"
                ),
                internal_only=True,
            )
        )
    return tuple(leads)


def _lead(
    security_id: str,
    route: DiscoveryRoute,
    dataset: str,
    evidence_id: str,
    available_at: datetime | None,
    transmission: str,
    question: str,
    *,
    fact_summary: str | None = None,
    needs_deep_read: bool = False,
    usable: bool = True,
    deep_read_input_hash: str | None = None,
    internal_only: bool = False,
    preliminary_opportunity: OpportunityType | None = None,
) -> _Lead:
    return _Lead(
        security_id=security_id,
        route=route,
        evidence=RouteEvidence(
            evidence_id=evidence_id,
            route=route,
            dataset=dataset,
            available_at=available_at,
            fact_summary=fact_summary,
            needs_deep_read=needs_deep_read,
            usable_for_decision=usable,
            deep_read_input_hash=deep_read_input_hash,
        ),
        transmission=transmission,
        question=question,
        internal_only=internal_only,
        preliminary_opportunity=preliminary_opportunity,
    )


def _merge_leads(
    leads: tuple[_Lead, ...],
    formation_date: date,
    cutoff: datetime,
) -> tuple[ResearchHypothesis, ...]:
    grouped: dict[str, list[_Lead]] = {}
    for lead in leads:
        grouped.setdefault(lead.security_id, []).append(lead)
    hypotheses: list[ResearchHypothesis] = []
    for security_id in sorted(grouped):
        items = grouped[security_id]
        routes = tuple(
            route for route in _ROUTE_ORDER if any(item.route is route for item in items)
        )
        evidence_by_route_id: dict[tuple[DiscoveryRoute, str], RouteEvidence] = {}
        for item in items:
            evidence_by_route_id.setdefault(
                (item.route, item.evidence.evidence_id), item.evidence
            )
        evidence = tuple(
            sorted(
                evidence_by_route_id.values(),
                key=lambda item: (_ROUTE_ORDER.index(item.route), item.evidence_id),
            )
        )
        usable = [item for item in items if item.evidence.usable_for_decision]
        opportunities = {
            item.preliminary_opportunity
            for item in usable
            if item.preliminary_opportunity is not None
        }
        hypotheses.append(
            ResearchHypothesis(
                security_id=security_id,
                formation_date=formation_date,
                cutoff=cutoff,
                discovery_routes=routes,
                evidence=evidence,
                transmission_hypotheses=tuple(
                    dict.fromkeys(item.transmission for item in usable)
                ),
                questions_to_verify=tuple(dict.fromkeys(item.question for item in items)),
                needs_deep_read=any(item.needs_deep_read for item in evidence),
                eligible_for_ten=any(not item.internal_only for item in usable),
                internal_review_only=bool(items) and all(
                    item.internal_only for item in usable
                ),
                preliminary_opportunity=(
                    next(iter(opportunities)) if len(opportunities) == 1 else None
                ),
            )
        )
    return tuple(hypotheses)


def _missing_hotspot_fields(row: Mapping[str, Any]) -> tuple[str, ...]:
    numeric = (
        "relative_return_20d",
        "median_return_20d",
        "breadth_20d",
        "turnover_share_average_20d",
        "top3_positive_contribution_1d",
    )
    counterevidence = (
        "high_volume_low_progress_flag",
        "upper_wick_reversal_flag",
        "narrow_participation_flag",
        "turnover_return_divergence_flag",
    )
    missing = [name for name in numeric if _maybe_number(row.get(name)) is None]
    missing.extend(name for name in counterevidence if type(row.get(name)) is not bool)
    if str(row.get("coverage_status", "")) not in {
        "complete",
        "complete_with_declared_gaps",
    }:
        missing.append("coverage_status")
    return tuple(missing)


def _earnings_has_operating_fact(dataset: str, row: Mapping[str, Any]) -> bool:
    fields = {
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
    }[dataset]
    return any(_maybe_number(row.get(name)) is not None for name in fields)


def _manual_boundaries(
    route: DiscoveryRoute,
    policy: RouteWindowPolicy,
) -> tuple[str, ...]:
    common = "route overlap merges evidence only and creates no vote, score or priority"
    values = {
        DiscoveryRoute.HOTSPOT: (
            "all sector_hotspot rows and all effective industry/theme memberships are enumerated",
            "turnover attention, head contribution and retreat counterevidence are required; "
            "counterevidence is recorded and never votes",
        ),
        DiscoveryRoute.EARNINGS: (
            "all forecast, express and income-statement partitions for declared "
            "periods are scanned",
            "operating values trigger research; historical, peer, expectation, cash and one-off "
            "materiality remains a downstream verification question",
        ),
        DiscoveryRoute.COMPANY_EVENT: (
            "all announcement months are enumerated; title classification is recall-only",
            "unread event evidence is disabled until a hashed deep-read record completes",
        ),
        DiscoveryRoute.INDUSTRY_CYCLE: (_CYCLE_GAP,),
        DiscoveryRoute.DISTRESS_REPAIR: (_REPAIR_GAP,),
        DiscoveryRoute.PRICE_ANOMALY: (
            "the entire stock_trading_context cross-section is scanned before applying the "
            f"preregistered absolute tail fraction {policy.price_absolute_tail_fraction:.8g}",
            "price and volume trigger cause investigation and never identify traders or value",
        ),
    }
    return (*values[route], common)


def _records(raw: Any, dataset: str) -> tuple[Mapping[str, Any], ...]:
    if hasattr(raw, "to_dict"):
        values = tuple(raw.to_dict(orient="records"))
    elif isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
        values = tuple(raw)
    else:
        raise TypeError(f"unsupported materialized frame for {dataset}: {type(raw)!r}")
    if any(not isinstance(item, Mapping) for item in values):
        raise TypeError(f"materialized rows for {dataset} must be mappings")
    return values


def _fact_content_hash(
    records: Sequence[Mapping[str, Any]],
    dataset: str,
) -> str:
    canonical: list[tuple[str, str, int]] = []
    for row in records:
        business_key_hash = row.get("business_key_hash")
        payload_hash = row.get("payload_hash")
        revision = row.get("revision_no", 1)
        if not _present(business_key_hash) or not _present(payload_hash):
            raise ValueError(
                f"{dataset}: canonical content hash audit columns are missing"
            )
        if isinstance(revision, bool):
            raise ValueError(f"{dataset}: invalid revision_no for content hash")
        try:
            revision_no = int(revision)
        except (TypeError, ValueError) as error:
            raise ValueError(
                f"{dataset}: invalid revision_no for content hash"
            ) from error
        canonical.append(
            (str(business_key_hash), str(payload_hash), revision_no)
        )
    return _stable_hash(sorted(canonical))


def _effective_relationship_records(
    records: Sequence[Mapping[str, Any]],
    *,
    dataset: str,
    formation_date: date,
) -> tuple[Mapping[str, Any], ...]:
    effective: list[Mapping[str, Any]] = []
    for row in records:
        valid_from = _as_date(row.get("valid_from"))
        raw_valid_to = row.get("valid_to")
        valid_to = _as_date(raw_valid_to)
        if valid_from is None:
            raise ValueError(f"{dataset}: invalid valid_from in warehouse relation")
        if raw_valid_to is not None and valid_to is None:
            try:
                missing_valid_to = bool(raw_valid_to != raw_valid_to)
            except (TypeError, ValueError):
                missing_valid_to = False
            if not missing_valid_to:
                raise ValueError(f"{dataset}: invalid valid_to in warehouse relation")
        if valid_from <= formation_date and (
            valid_to is None or valid_to >= formation_date
        ):
            effective.append(row)
    return tuple(effective)


def _partition_records(
    dataset: str,
    records: Sequence[Mapping[str, Any]],
    requested: tuple[str, ...],
) -> tuple[dict[str, tuple[Mapping[str, Any], ...]], str | None]:
    field_name = research_contract(ResearchDatasetId(dataset)).partition_field
    grouped: dict[str, list[Mapping[str, Any]]] = {
        partition: [] for partition in requested
    }
    for row in records:
        raw_partition = row.get(field_name)
        if raw_partition is None:
            return {}, f"{dataset}: missing partition field {field_name}"
        if isinstance(raw_partition, datetime):
            partition = raw_partition.date().isoformat()
        elif isinstance(raw_partition, date):
            partition = raw_partition.isoformat()
        else:
            partition = str(raw_partition)
        if partition not in grouped:
            return {}, f"{dataset}: frame contains unrequested partition {partition}"
        grouped[partition].append(row)
    return {
        partition: tuple(values) for partition, values in grouped.items()
    }, None


def _count(row: Mapping[str, Any], field_name: str) -> int:
    value = row.get(field_name)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"manifest {field_name} must be a non-negative integer")
    return value


def _dates(values: Iterable[date], label: str) -> tuple[date, ...]:
    result = tuple(sorted(set(values)))
    if not result or any(not isinstance(value, date) for value in result):
        raise ValueError(f"{label} must contain dates")
    return result


def _partitions(values: Iterable[str], label: str) -> tuple[str, ...]:
    result = tuple(dict.fromkeys(str(value).strip() for value in values))
    if not result or any(not value for value in result):
        raise ValueError(f"{label} must contain non-empty partitions")
    return result


def _month_range(start: date, end: date) -> tuple[str, ...]:
    if start > end:
        raise ValueError("month range start exceeds end")
    current = date(start.year, start.month, 1)
    last = date(end.year, end.month, 1)
    result: list[str] = []
    while current <= last:
        result.append(current.strftime("%Y-%m"))
        current = (
            date(current.year + 1, 1, 1)
            if current.month == 12
            else date(current.year, current.month + 1, 1)
        )
    return tuple(result)


def _quarter_end(index: int) -> date:
    year, zero_based_quarter = divmod(index, 4)
    month = (zero_based_quarter + 1) * 3
    day = 31 if month in {3, 12} else 30
    return date(year, month, day)


def _dataset_label(value: Any) -> str:
    return str(getattr(value, "value", value))


def _partition_key(dataset: str, partition: str) -> str:
    return f"{dataset}:{partition}"


def _security_id(row: Mapping[str, Any]) -> str | None:
    value = row.get("security_id", row.get("ts_code"))
    if value is None or not str(value).strip():
        return None
    return str(value).strip()


def _effective(row: Mapping[str, Any], formation_date: date) -> bool:
    start = _as_date(row.get("valid_from"))
    end = _as_date(row.get("valid_to"))
    return start is not None and start <= formation_date and (
        end is None or end >= formation_date
    )


def _temporal_reason(row: Mapping[str, Any], cutoff: datetime) -> str | None:
    available = _as_datetime(row.get("available_at"))
    if available is None or available.tzinfo is None:
        return "missing or timezone-naive available_at"
    if available > cutoff:
        return "available_at exceeds formation cutoff"
    return None


def _feature_after_cutoff(row: Mapping[str, Any], formation_date: date) -> bool:
    return _as_date(row.get("analysis_date")) != formation_date


def _strict_true(value: Any) -> bool:
    return type(value) is bool and value is True


def _number(value: Any) -> float:
    result = _maybe_number(value)
    if result is None:
        raise ValueError("expected finite number")
    return result


def _maybe_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result):
        return None
    return result


def _present(value: Any) -> bool:
    return value is not None and (not isinstance(value, str) or bool(value.strip()))


def _as_date(value: Any) -> date | None:
    try:
        if value is not None and bool(value != value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _as_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _route_policy_hash(policy: RouteWindowPolicy) -> str:
    return _route_policy_hash_values(
        formation_date=policy.formation_date,
        route_partitions=policy.route_partitions,
        earnings_report_periods=policy.earnings_report_periods,
        event_start=policy.event_start,
        event_end=policy.event_end,
        price_absolute_tail_fraction=policy.price_absolute_tail_fraction,
        coverage_gaps=policy.coverage_gaps,
        universe_source_manifest_hash=policy.universe_source_manifest_hash,
        universe_source_view_manifest_hash=(
            policy.universe_source_view_manifest_hash
        ),
        universe_source_attestation_hash=policy.universe_source_attestation_hash,
        universe_catalog_hash=policy.universe_catalog_hash,
        universe_effective_content_hashes=policy.universe_effective_content_hashes,
        _source_attestation=policy._source_attestation,
    )


def _route_policy_hash_values(
    *,
    formation_date: date,
    route_partitions: Mapping[DiscoveryRoute, Mapping[str, tuple[str, ...]]],
    earnings_report_periods: tuple[date, ...],
    event_start: date,
    event_end: date,
    price_absolute_tail_fraction: float,
    coverage_gaps: Mapping[DiscoveryRoute, tuple[str, ...]],
    universe_source_manifest_hash: str,
    universe_source_view_manifest_hash: str,
    universe_source_attestation_hash: str,
    universe_catalog_hash: str,
    universe_effective_content_hashes: Mapping[str, str],
    _source_attestation: _SourceCatalogAttestation,
) -> str:
    return _stable_hash(
        {
            "formation_date": formation_date,
            "route_partitions": {
                route.value: dict(route_partitions[route]) for route in _ROUTE_ORDER
            },
            "earnings_report_periods": earnings_report_periods,
            "event_start": event_start,
            "event_end": event_end,
            "price_absolute_tail_fraction": price_absolute_tail_fraction,
            "coverage_gaps": {
                route.value: coverage_gaps.get(route, ()) for route in _ROUTE_ORDER
            },
            "universe_source_manifest_hash": universe_source_manifest_hash,
            "universe_source_view_manifest_hash": universe_source_view_manifest_hash,
            "universe_source_attestation_hash": universe_source_attestation_hash,
            "universe_catalog_hash": universe_catalog_hash,
            "universe_effective_content_hashes": dict(
                universe_effective_content_hashes
            ),
        }
    )


def _module_code_hash() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _warehouse_state(
    warehouse: ResearchWarehouse,
) -> tuple[tuple[str, int, int], str]:
    root = Path(warehouse.root).resolve(strict=True)
    stat = root.stat()
    identity = (str(root), int(stat.st_dev), int(stat.st_ino))
    return identity, tree_fingerprint(root)


def _require_registered_attestation(
    attestation: Any,
) -> _AttestationRegistration:
    if type(attestation) is not _SourceCatalogAttestation:
        raise ValueError(
            "source attestation lacks registered warehouse builder provenance"
        )
    registration = _ATTESTATION_REGISTRY.get(attestation)
    if registration is None:
        raise ValueError(
            "source attestation lacks registered warehouse builder provenance"
        )
    if (
        registration.attestation_hash != attestation.attestation_hash
        or registration.code_hash != attestation.code_hash
        or registration.root_identity != attestation.warehouse_root_identity
        or registration.tree_hash != attestation.warehouse_tree_hash
    ):
        raise ValueError("registered source attestation digest mismatch")
    if _module_code_hash() != registration.code_hash:
        raise ValueError("attestation builder code hash changed after preflight")
    try:
        root_identity, tree_hash = _warehouse_state(registration.warehouse)
    except (FileNotFoundError, OSError) as error:
        raise ValueError("attested warehouse root changed or disappeared") from error
    if (
        root_identity != registration.root_identity
        or tree_hash != registration.tree_hash
    ):
        raise ValueError("attested warehouse tree changed after preflight")
    attestation.validate_integrity()
    return registration


def _stable_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _json_default(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    return repr(value)


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


__all__ = [
    "ResearchHypothesis",
    "RouteDataset",
    "RouteEvidence",
    "RouteWindowPolicy",
    "build_frozen_universe_catalog",
    "build_route_fact_plan",
    "build_route_window_policy",
    "build_source_catalog_attestation",
    "derive_declared_route_windows",
    "scan_routes",
]
