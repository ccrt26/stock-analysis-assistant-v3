"""Formation-time candidate evidence for the isolated V3 backtest.

The evidence contract is frozen independently of knowledge selection.  Knowledge
may interpret materialized evidence, but it cannot decide which source facts are
allowed to enter the packet.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Annotated, Any, Literal, Self
from weakref import WeakKeyDictionary
from zoneinfo import ZoneInfo

import pandas as pd
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from stock_analyzer.evaluation.v3_backtest.contracts import (
    DiscoveryRoute,
    EvidenceKind,
    OpportunityType as BacktestOpportunityType,
    RouteScanManifest,
)
from stock_analyzer.evaluation.v3_backtest.snapshots import formation_cutoff
from stock_analyzer.evaluation.v3_backtest.snapshots import FormationSnapshot
from stock_analyzer.evaluation.v3_backtest.routes import (
    RouteFactPlan,
    RouteWindowPolicy,
    VerifiedRouteScanBatch,
    build_source_catalog_attestation,
    require_verified_route_scan_batch,
)
from stock_analyzer.knowledge.capability import (
    CapabilityItem,
    CapabilitySnapshot,
    assess_entry_capability,
)
from stock_analyzer.knowledge.governance_models import (
    AnalysisContext,
    AnalysisModule,
    CapabilityStatus,
    KnowledgeEffect,
    KnowledgeRegistry,
    KnowledgeTopic,
    OpportunityType,
)
from stock_analyzer.knowledge.registry import load_knowledge_registry
from stock_analyzer.knowledge.selector import KnowledgeSelection, select_knowledge
from stock_analyzer.data.research_contracts import ResearchDatasetId
from stock_analyzer.storage.research_query import ResearchQuery
from stock_analyzer.storage.research_warehouse import ResearchWarehouse


_SHANGHAI = ZoneInfo("Asia/Shanghai")
_REGISTRY_PATH = Path(__file__).resolve().parents[2] / "knowledge" / "research_registry.yaml"
_FROZEN_REGISTRY_HASH = "78d5d53da138f1e2a113d848cbe25c52f03e8e4478c4d39f01e01d16878e0bd4"
_FROZEN_REGISTRY_FILE_SHA256 = "40762d5736b15d05e616a70279f7586c3e4da5562ba819393c4dbda96cdaafeb"
_FROZEN_CURRENT_COUNT = 27
_FROZEN_HISTORICAL_COUNT = 3
_FROZEN_CURRENT_IDS_HASH = "d189d87d8c19510e1b5d9c25b5cebb1df72c89c8f2133f3c9c2cdd14f71b7fae"
_FROZEN_HISTORICAL_IDS_HASH = "b87cf04aba6b094510f776d386761fc91a5a2b51ca384e4dfa280bb900a052fe"
_FEATURE_NAMES = {"market_context", "sector_hotspot", "stock_trading_context"}
_EVIDENCE_PLAN_TOKEN = object()
_EVIDENCE_CATALOG_TOKEN = object()
_EVIDENCE_BUNDLE_TOKEN = object()


@dataclass(frozen=True, slots=True)
class _EvidenceBundleRegistration:
    batch_hash: str
    batch_identity: int
    bundle_hash: str
    snapshot_identity: int
    plan_identity: int
    catalog_identity: int


_EVIDENCE_BUNDLE_REGISTRY: WeakKeyDictionary[
    "VerifiedEvidenceSnapshotBundle", _EvidenceBundleRegistration
] = WeakKeyDictionary()
_SECURITY_FIELD = "ts_code"
_BUSINESS_TIME_FIELDS = (
    "trade_date",
    "announcement_time",
    "announcement_date",
    "ann_date",
    "report_period",
    "analysis_date",
    "valid_from",
)
_NUMBER = re.compile(r"(?<![A-Za-z_])\d+(?:\.\d+)?%?")

# Closed field boundary for source facts.  Required fields are always allowed;
# these additions are the only optional official fields that may enter semantic
# checks.  Everything else is deliberately ignored so future labels cannot
# leak into a historical packet merely because a warehouse table gained a
# column.
_OPTIONAL_API_FIELDS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "industry_member": ("valid_to",),
        "theme_member": ("valid_to",),
        "main_business": ("bz_sales", "bz_profit", "bz_cost", "currency"),
        "income_statement": ("report_type", "ann_date", "operate_profit", "oper_cost"),
        "industry_daily": (
            "demand_change",
            "supply_change",
            "capacity_change",
            "price_change",
            "inventory_change",
            "shipment_change",
            "adoption_change",
        ),
        "announcement": (
            "body",
            "amount",
            "subject",
            "execution_conditions",
            "event_stage",
            "failure_conditions",
        ),
        "balance_sheet": (
            "money_cap",
            "st_borr",
            "non_cur_liab_due_1y",
        ),
    }
)
_LOCAL_FACT_FIELDS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "announcement": (
            "candidate_event_types",
            "classification_is_fact",
            "classification_version",
            "hard_risk_candidate",
            "deep_read_completed",
            "deep_read_input_hash",
        )
    }
)

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
EvidenceScalar = str | int | float | Decimal | bool | date | datetime | tuple[str, ...]


class EvidenceAvailability(StrEnum):
    EVIDENCE_READY_FOR_JUDGMENT = "evidence_ready_for_judgment"
    NOT_AVAILABLE_AS_OF = "not_available_as_of"


class EvidenceInputStatus(StrEnum):
    READY = "ready"
    NOT_MATERIALIZED = "not_materialized"
    COVERAGE_GAP = "coverage_gap"
    NOT_AVAILABLE_AS_OF = "not_available_as_of"
    CANDIDATE_HAS_NO_ROW = "candidate_has_no_row"
    INVALID_SCHEMA = "invalid_schema"


class EvidenceCardStatus(StrEnum):
    EVIDENCE_READY_FOR_JUDGMENT = "evidence_ready_for_judgment"
    INCOMPLETE = "incomplete"


class KnowledgeRoutingStatus(StrEnum):
    PREPARED_FOR_JUDGMENT = "prepared_for_judgment"
    NOT_APPLICABLE = "not_applicable"


class EvidenceSectionName(StrEnum):
    MARKET_CONSTRAINTS = "market_constraints"
    HOTSPOT_PANORAMA = "hotspot_panorama"
    BUSINESS_TRANSMISSION = "business_transmission"
    INDUSTRY_TREND_EVIDENCE = "industry_trend_evidence"
    EARNINGS_REVALUATION_EVIDENCE = "earnings_revaluation_evidence"
    SUPPLY_DEMAND_CYCLE_EVIDENCE = "supply_demand_cycle_evidence"
    COMPANY_EVENT_REVALUATION_EVIDENCE = "company_event_revaluation_evidence"
    DISTRESS_REVERSAL_EVIDENCE = "distress_reversal_evidence"
    FINANCIAL_QUALITY = "financial_quality"
    VALUATION_CONTEXT = "valuation_context"
    COMPANY_EVENTS = "company_events"
    PRICE_VOLUME_LIQUIDITY = "price_volume_liquidity"
    POST_FACT_PRICE_RESPONSE = "post_fact_price_response"
    CURRENT_PRICE_TO_TARGET_CONDITIONS = "current_price_to_target_conditions"
    COUNTEREVIDENCE = "counterevidence"
    UNKNOWNS = "unknowns"
    NEXT_VALIDATION_FACT = "next_validation_fact"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)


def _validate_numeric_text(text: str, evidence_ids: Sequence[str]) -> str:
    if _NUMBER.search(text):
        raise ValueError("numeric free text is forbidden; use atomic evidence values")
    return text


class EvidenceText(_FrozenModel):
    text: NonEmptyStr
    evidence_ids: tuple[NonEmptyStr, ...] = ()
    source_text_hash: Sha256 | None = None

    @model_validator(mode="after")
    def validate_text_references(self) -> Self:
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("text evidence_ids must be unique")
        _validate_numeric_text(self.text, self.evidence_ids)
        return self


class EvidenceDatum(_FrozenModel):
    """One atomic value whose numeric content is inseparable from its id."""

    evidence_id: NonEmptyStr
    kind: EvidenceKind
    dataset: NonEmptyStr
    field: NonEmptyStr
    row_key: NonEmptyStr
    value: EvidenceScalar
    business_time: datetime
    available_at: datetime
    input_hash: Sha256
    source_evidence_id: NonEmptyStr | None = None

    @field_validator("business_time", "available_at")
    @classmethod
    def aware_time(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("evidence timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def temporal_order(self) -> Self:
        if self.available_at < self.business_time:
            raise ValueError("available_at cannot precede business_time")
        return self


class ModelJudgment(_FrozenModel):
    """Text plus explicit references only; no field exists to overwrite facts."""

    judgment_id: NonEmptyStr
    text: NonEmptyStr
    evidence_ids: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_judgment(self) -> Self:
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("judgment evidence_ids must be unique")
        _validate_numeric_text(self.text, self.evidence_ids)
        return self


class EvidenceSection(_FrozenModel):
    name: EvidenceSectionName
    availability: EvidenceAvailability
    evidence_ids: tuple[NonEmptyStr, ...] = ()
    note: NonEmptyStr

    @model_validator(mode="after")
    def validate_section(self) -> Self:
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("section evidence_ids must be unique")
        if (
            self.availability
            is EvidenceAvailability.EVIDENCE_READY_FOR_JUDGMENT
            and not self.evidence_ids
        ):
            raise ValueError("evidence-ready sections require dedicated evidence")
        if self.availability is EvidenceAvailability.NOT_AVAILABLE_AS_OF:
            if self.evidence_ids:
                raise ValueError("unavailable sections cannot cite evidence")
            if not any(
                marker in self.note
                for marker in (
                    "not_materialized",
                    "coverage_gap",
                    "not_available_as_of",
                    "candidate_has_no_row",
                    "invalid_schema",
                    "incomplete",
                )
            ):
                raise ValueError("unavailable section must state a concrete missing reason")
        _validate_numeric_text(self.note, self.evidence_ids)
        return self


class EvidenceInputCoverage(_FrozenModel):
    dataset: NonEmptyStr
    kind: Literal["fact", "derived", "local"]
    scope: Literal["global", "group", "candidate"]
    status: EvidenceInputStatus
    required_fields: tuple[NonEmptyStr, ...]
    observed_rows: Annotated[int, Field(ge=0)]
    missing_fields: tuple[NonEmptyStr, ...] = ()
    detail: NonEmptyStr
    source_manifest_hash: Sha256 | None = None


class EvidenceInputRequirement(_FrozenModel):
    dataset: NonEmptyStr
    kind: Literal["fact", "derived", "local"]
    scope: Literal["global", "group", "candidate"]
    required_fields: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]
    sections: Annotated[tuple[EvidenceSectionName, ...], Field(min_length=1)]


class OpportunityEvidenceCard(_FrozenModel):
    opportunity: BacktestOpportunityType
    status: EvidenceCardStatus
    required_requirements: tuple[NonEmptyStr, ...]
    missing_requirements: tuple[NonEmptyStr, ...] = ()
    evidence_ids: tuple[NonEmptyStr, ...] = ()
    requirement_evidence_ids: tuple[
        tuple[NonEmptyStr, tuple[NonEmptyStr, ...]], ...
    ] = ()

    @model_validator(mode="after")
    def validate_card(self) -> Self:
        if self.status is EvidenceCardStatus.EVIDENCE_READY_FOR_JUDGMENT:
            bound_requirements = tuple(
                requirement for requirement, _ in self.requirement_evidence_ids
            )
            bound_ids = tuple(
                evidence_id
                for _, evidence_ids in self.requirement_evidence_ids
                for evidence_id in evidence_ids
            )
            if (
                self.missing_requirements
                or not self.evidence_ids
                or bound_requirements != self.required_requirements
                or any(not evidence_ids for _, evidence_ids in self.requirement_evidence_ids)
                or not set(bound_ids).issubset(self.evidence_ids)
            ):
                raise ValueError("evidence-ready card needs evidence and no input gaps")
        elif (
            self.evidence_ids
            or self.requirement_evidence_ids
            or not self.missing_requirements
        ):
            raise ValueError("incomplete opportunity card must expose gaps, not evidence")
        return self


class RouteManifestAudit(_FrozenModel):
    route: DiscoveryRoute
    input_hash: Sha256
    snapshot_cache_key: Sha256
    bound_hash: Sha256


class EvidencePlanAudit(_FrozenModel):
    evidence_plan_hash: Sha256
    evidence_source_catalog_hash: Sha256
    evidence_catalog_manifest_hash: Sha256
    snapshot_source_manifest_hash: Sha256
    route_policy_hash: Sha256
    universe_source_manifest_hash: Sha256
    universe_source_attestation_hash: Sha256
    universe_catalog_hash: Sha256
    complete_route_scan_hash: Sha256
    verified_batch_receipt_hash: Sha256
    raw_lead_ledger_hash: Sha256


class SelectedKnowledgeAudit(_FrozenModel):
    knowledge_id: NonEmptyStr
    version_status: Literal["current"]
    entry_content_hash: Sha256
    effect: KnowledgeEffect
    use_purpose: NonEmptyStr


class RegistryAudit(_FrozenModel):
    registry_hash: Sha256
    registry_file_sha256: Sha256
    current_count: Literal[27]
    historical_only_count: Literal[3]
    current_ids_hash: Sha256
    historical_only_ids_hash: Sha256
    prepared_entries: tuple[SelectedKnowledgeAudit, ...]


class KnowledgeRoutingRecord(_FrozenModel):
    knowledge_id: NonEmptyStr
    status: KnowledgeRoutingStatus
    reason: NonEmptyStr
    use_purpose: NonEmptyStr | None = None
    claim_summary_hash: Sha256 | None = None
    allowed_use_hash: Sha256 | None = None
    effect: KnowledgeEffect | None = None
    selection_reasons: tuple[NonEmptyStr, ...] = ()
    evidence_ids: tuple[NonEmptyStr, ...] = ()

    @model_validator(mode="after")
    def validate_routing(self) -> Self:
        if self.status is KnowledgeRoutingStatus.PREPARED_FOR_JUDGMENT:
            if not all(
                (
                    self.use_purpose,
                    self.claim_summary_hash,
                    self.allowed_use_hash,
                    self.effect,
                )
            ) or not self.evidence_ids:
                raise ValueError(
                    "prepared knowledge requires purpose, content hashes and evidence"
                )
        elif any(
            (
                self.use_purpose,
                self.claim_summary_hash,
                self.allowed_use_hash,
                self.effect,
                self.evidence_ids,
            )
        ):
            raise ValueError("not-applicable knowledge cannot claim preparation")
        return self


class CandidateEvidencePacket(_FrozenModel):
    security_id: NonEmptyStr
    formation_date: date
    cutoff: datetime
    discovery_routes: Annotated[tuple[DiscoveryRoute, ...], Field(min_length=1)]
    preliminary_opportunity: BacktestOpportunityType | None
    registry_audit: RegistryAudit
    evidence_plan_audit: EvidencePlanAudit
    route_manifest_audit: tuple[RouteManifestAudit, ...]
    input_coverage: tuple[EvidenceInputCoverage, ...]
    api_facts: tuple[EvidenceDatum, ...] = ()
    local_observations: tuple[EvidenceDatum, ...] = ()
    model_judgments: tuple[ModelJudgment, ...] = ()
    opportunity_cards: Annotated[
        tuple[OpportunityEvidenceCard, ...], Field(min_length=5, max_length=5)
    ]
    sections: Annotated[
        tuple[EvidenceSection, ...], Field(min_length=len(EvidenceSectionName))
    ]
    knowledge_routing: tuple[KnowledgeRoutingRecord, ...]
    unknowns: tuple[EvidenceText, ...]
    next_validation: tuple[EvidenceText, ...]

    @model_validator(mode="after")
    def integrity(self) -> Self:
        if not _is_exact_formation_cutoff(self.cutoff, self.formation_date):
            raise ValueError("cutoff must be Asia/Shanghai 23:59:59 on formation date")
        if len(self.discovery_routes) != len(set(self.discovery_routes)):
            raise ValueError("discovery routes must be unique and cannot be votes")
        evidence = (*self.api_facts, *self.local_observations)
        if any(item.kind is not EvidenceKind.API_FACT for item in self.api_facts):
            raise ValueError("api fact layer contains non-API evidence")
        if any(
            item.kind is not EvidenceKind.LOCAL_OBSERVATION
            for item in self.local_observations
        ):
            raise ValueError("local observation layer contains non-local evidence")
        evidence_ids = [item.evidence_id for item in evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("evidence ids must be unique across factual layers")
        if any(item.available_at > self.cutoff for item in evidence):
            raise ValueError("evidence became available after formation cutoff")
        known = set(evidence_ids)
        for item in self.local_observations:
            if (
                item.dataset == "event_price_response"
                and item.source_evidence_id not in known
            ):
                raise ValueError(
                    "event response must bind an existing source-event evidence id"
                )
        for judgment in self.model_judgments:
            _reject_unknown(judgment.evidence_ids, known, "model judgment")
        section_names = [section.name for section in self.sections]
        if len(section_names) != len(set(section_names)) or set(section_names) != set(
            EvidenceSectionName
        ):
            raise ValueError("packet must contain every section exactly once")
        for section in self.sections:
            _reject_unknown(section.evidence_ids, known, "section")
        card_types = [card.opportunity for card in self.opportunity_cards]
        if len(card_types) != len(set(card_types)) or set(card_types) != set(
            BacktestOpportunityType
        ):
            raise ValueError("packet must contain all five opportunity cards exactly once")
        for card in self.opportunity_cards:
            _reject_unknown(card.evidence_ids, known, "opportunity card")
        for record in self.knowledge_routing:
            _reject_unknown(record.evidence_ids, known, "knowledge routing")
        for value in (*self.unknowns, *self.next_validation):
            _reject_unknown(value.evidence_ids, known, "structured text")
        route_order = tuple(item.route for item in self.route_manifest_audit)
        if route_order != tuple(DiscoveryRoute):
            raise ValueError("route manifest audit must contain the full six-route scan")
        return self


@dataclass(frozen=True, slots=True)
class _InputSpec:
    dataset: str
    kind: Literal["fact", "derived", "local"]
    scope: Literal["global", "group", "candidate"]
    required_fields: tuple[str, ...]
    sections: tuple[EvidenceSectionName, ...]


class EvidenceFactPlan(Mapping[str, tuple[str, ...]]):
    """Immutable route-plus-evidence plan produced only by its public builder."""

    __slots__ = (
        "__partitions",
        "__plan_hash",
        "__route_plan",
        "__catalog_hash",
        "__source_manifest_hash",
        "__source_attestation_hash",
        "__source_as_of",
        "__source_entries",
        "__missing_datasets",
    )

    def __init__(
        self,
        partitions: Mapping[str, tuple[str, ...]],
        *,
        route_plan: RouteFactPlan | None = None,
        catalog_hash: str | None = None,
        source_manifest_hash: str | None = None,
        source_attestation_hash: str | None = None,
        source_as_of: str | None = None,
        source_entries: Sequence[Mapping[str, Any]] = (),
        missing_datasets: tuple[str, ...] = (),
        _token: object | None = None,
    ) -> None:
        if (
            _token is not _EVIDENCE_PLAN_TOKEN
            or route_plan is None
            or catalog_hash is None
            or source_manifest_hash is None
            or source_attestation_hash is None
            or source_as_of is None
        ):
            raise ValueError(
                "EvidenceFactPlan must be created by build_evidence_fact_plan builder"
            )
        route_plan.validate_integrity()
        self.__partitions = MappingProxyType(dict(partitions))
        self.__route_plan = route_plan
        self.__catalog_hash = catalog_hash
        self.__source_manifest_hash = source_manifest_hash
        self.__source_attestation_hash = source_attestation_hash
        self.__source_as_of = source_as_of
        self.__source_entries = tuple(
            MappingProxyType(dict(item)) for item in source_entries
        )
        self.__missing_datasets = tuple(sorted(missing_datasets))
        if self.__source_manifest_hash != _stable_hash(
            {
                "as_of": self.__source_as_of,
                "partitions": [dict(item) for item in self.__source_entries],
            }
        ):
            raise ValueError("evidence plan source entries do not match manifest hash")
        self.__plan_hash = _stable_hash(
            {
                "partitions": self.__partitions,
                "route_plan": dict(route_plan),
                "catalog_hash": catalog_hash,
                "source_manifest_hash": source_manifest_hash,
                "source_attestation_hash": source_attestation_hash,
                "source_as_of": source_as_of,
                "source_entries": self.__source_entries,
                "missing_datasets": self.__missing_datasets,
            }
        )

    def __getitem__(self, dataset: str) -> tuple[str, ...]:
        return self.__partitions[dataset]

    def __iter__(self):
        return iter(self.__partitions)

    def __len__(self) -> int:
        return len(self.__partitions)

    @property
    def plan_hash(self) -> str:
        return self.__plan_hash

    @property
    def route_fact_plan(self) -> RouteFactPlan:
        return self.__route_plan

    @property
    def catalog_hash(self) -> str:
        return self.__catalog_hash

    @property
    def source_manifest_hash(self) -> str:
        return self.__source_manifest_hash

    @property
    def source_attestation_hash(self) -> str:
        return self.__source_attestation_hash

    @property
    def missing_datasets(self) -> tuple[str, ...]:
        return self.__missing_datasets

    @property
    def source_entries(self) -> tuple[dict[str, Any], ...]:
        return tuple(dict(item) for item in self.__source_entries)

    def validate_integrity(self) -> None:
        self.__route_plan.validate_integrity()
        expected = _stable_hash(
            {
                "partitions": self.__partitions,
                "route_plan": dict(self.__route_plan),
                "catalog_hash": self.__catalog_hash,
                "source_manifest_hash": self.__source_manifest_hash,
                "source_attestation_hash": self.__source_attestation_hash,
                "source_as_of": self.__source_as_of,
                "source_entries": self.__source_entries,
                "missing_datasets": self.__missing_datasets,
            }
        )
        if expected != self.__plan_hash:
            raise ValueError("evidence fact plan integrity hash mismatch")


class EvidenceSourceCatalog:
    """Opaque full Task5 inventory attested to the exact Task4 warehouse."""

    __slots__ = (
        "__formation_date",
        "__as_of",
        "__route_catalog_hash",
        "__source_attestation_hash",
        "__warehouse_root_identity",
        "__warehouse_tree_hash",
        "__inventory",
        "__source_entries",
        "__source_manifest_hash",
        "__inventory_hash",
        "__catalog_hash",
    )

    def __init__(
        self,
        *,
        formation_date: date,
        as_of: datetime,
        route_catalog_hash: str,
        source_attestation_hash: str,
        warehouse_root_identity: tuple[str, int, int],
        warehouse_tree_hash: str,
        inventory: Sequence[Mapping[str, Any]],
        source_entries: Sequence[Mapping[str, Any]],
        source_manifest_hash: str,
        _token: object | None = None,
    ) -> None:
        if _token is not _EVIDENCE_CATALOG_TOKEN:
            raise ValueError(
                "EvidenceSourceCatalog must be created by "
                "build_evidence_source_catalog"
            )
        self.__formation_date = formation_date
        self.__as_of = as_of
        self.__route_catalog_hash = route_catalog_hash
        self.__source_attestation_hash = source_attestation_hash
        self.__warehouse_root_identity = tuple(warehouse_root_identity)
        self.__warehouse_tree_hash = warehouse_tree_hash
        self.__inventory = tuple(
            MappingProxyType(dict(item))
            for item in sorted(
                inventory,
                key=lambda item: (str(item.get("dataset")), str(item.get("partition"))),
            )
        )
        self.__source_entries = tuple(
            MappingProxyType(dict(item))
            for item in sorted(
                source_entries,
                key=lambda item: (str(item.get("dataset")), str(item.get("partition"))),
            )
        )
        self.__source_manifest_hash = source_manifest_hash
        self.__inventory_hash = _stable_hash(self.__inventory)
        self.__catalog_hash = _stable_hash(self._payload())
        self.validate_integrity()

    def _payload(self) -> Mapping[str, Any]:
        return {
            "formation_date": self.__formation_date,
            "as_of": self.__as_of,
            "route_catalog_hash": self.__route_catalog_hash,
            "source_attestation_hash": self.__source_attestation_hash,
            "warehouse_root_identity": self.__warehouse_root_identity,
            "warehouse_tree_hash": self.__warehouse_tree_hash,
            "inventory_hash": self.__inventory_hash,
            "source_entries": self.__source_entries,
            "source_manifest_hash": self.__source_manifest_hash,
        }

    @property
    def formation_date(self) -> date:
        return self.__formation_date

    @property
    def as_of(self) -> datetime:
        return self.__as_of

    @property
    def route_catalog_hash(self) -> str:
        return self.__route_catalog_hash

    @property
    def source_attestation_hash(self) -> str:
        return self.__source_attestation_hash

    @property
    def source_manifest_hash(self) -> str:
        return self.__source_manifest_hash

    @property
    def catalog_hash(self) -> str:
        return self.__catalog_hash

    @property
    def inventory_hash(self) -> str:
        return self.__inventory_hash

    @property
    def warehouse_root_identity(self) -> tuple[str, int, int]:
        return self.__warehouse_root_identity

    @property
    def warehouse_tree_hash(self) -> str:
        return self.__warehouse_tree_hash

    def source_entries(self) -> tuple[dict[str, Any], ...]:
        return tuple(dict(item) for item in self.__source_entries)

    def partitions(self, dataset: str) -> tuple[str, ...]:
        return tuple(
            str(item["partition"])
            for item in self.__source_entries
            if item["dataset"] == dataset
        )

    def validate_integrity(self) -> None:
        if _stable_hash(self.__inventory) != self.__inventory_hash:
            raise ValueError("evidence source catalog inventory hash mismatch")
        source_payload = {
            "as_of": self.__as_of.astimezone(timezone.utc).isoformat(),
            "partitions": [dict(item) for item in self.__source_entries],
        }
        if _stable_hash(source_payload) != self.__source_manifest_hash:
            raise ValueError("evidence source catalog manifest hash mismatch")
        if _stable_hash(self._payload()) != self.__catalog_hash:
            raise ValueError("evidence source catalog integrity hash mismatch")


class VerifiedEvidenceSnapshotBundle:
    """Opaque binding of one full evidence snapshot to one Task4 scan batch."""

    __slots__ = (
        "__batch_hash",
        "__snapshot",
        "__evidence_plan",
        "__source_catalog",
        "__snapshot_content_hash",
        "__route_projection_hash",
        "__bundle_hash",
        "__weakref__",
    )

    def __init__(
        self,
        *,
        batch_hash: str,
        batch_identity: int,
        snapshot: FormationSnapshot,
        evidence_plan: EvidenceFactPlan,
        source_catalog: EvidenceSourceCatalog,
        route_projection_hash: str,
        _token: object | None = None,
    ) -> None:
        if _token is not _EVIDENCE_BUNDLE_TOKEN:
            raise ValueError(
                "VerifiedEvidenceSnapshotBundle must be created by its builder"
            )
        self.__batch_hash = batch_hash
        self.__snapshot = snapshot
        self.__evidence_plan = evidence_plan
        self.__source_catalog = source_catalog
        self.__snapshot_content_hash = _formation_snapshot_content_hash(snapshot)
        self.__route_projection_hash = route_projection_hash
        self.__bundle_hash = _stable_hash(
            {
                "batch_hash": batch_hash,
                "snapshot_content_hash": self.__snapshot_content_hash,
                "evidence_plan_hash": evidence_plan.plan_hash,
                "source_catalog_hash": source_catalog.catalog_hash,
                "route_projection_hash": route_projection_hash,
            }
        )
        _EVIDENCE_BUNDLE_REGISTRY[self] = _EvidenceBundleRegistration(
            batch_hash=batch_hash,
            batch_identity=batch_identity,
            bundle_hash=self.__bundle_hash,
            snapshot_identity=id(snapshot),
            plan_identity=id(evidence_plan),
            catalog_identity=id(source_catalog),
        )


_INPUT_SPECS = (
    _InputSpec(
        "market_context",
        "derived",
        "global",
        (
            "analysis_date",
            "median_return_1d",
            "breadth_1d",
            "market_turnover_amount",
            "realized_volatility_20d_annualized",
            "return_dispersion_1d",
            "coverage_status",
        ),
        (EvidenceSectionName.MARKET_CONSTRAINTS,),
    ),
    _InputSpec(
        "sector_hotspot",
        "derived",
        "group",
        (
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
        (EvidenceSectionName.HOTSPOT_PANORAMA, EvidenceSectionName.COUNTEREVIDENCE),
    ),
    _InputSpec(
        "stock_trading_context",
        "derived",
        "candidate",
        (
            "analysis_date",
            "ts_code",
            "return_20d",
            "relative_return_20d",
            "current_amount_ratio_20d",
            "price_location_60d",
            "realized_volatility_20d_annualized",
            "atr_ratio_20d",
            "coverage_status",
        ),
        (EvidenceSectionName.PRICE_VOLUME_LIQUIDITY, EvidenceSectionName.COUNTEREVIDENCE),
    ),
    _InputSpec(
        "event_price_response",
        "local",
        "candidate",
        (
            "analysis_date",
            "ts_code",
            "event_time",
            "event_dataset",
            "event_record_id",
            "source_event_row_key",
            "source_event_evidence_id",
            "source_record_id",
            "source_report_period",
            "source_deep_read_status",
            "source_deep_read_input_hash",
            "market_benchmark_code",
            "industry_code",
            "pre_event_trade_date",
            "formation_trade_date",
            "elapsed_trading_days",
            "stock_return_to_formation",
            "market_return_to_formation",
            "industry_return_to_formation",
            "stock_market_relative_return",
            "stock_industry_relative_return",
            "formula_version",
            "input_hash",
        ),
        (EvidenceSectionName.POST_FACT_PRICE_RESPONSE,),
    ),
    _InputSpec(
        "target_path_context",
        "local",
        "candidate",
        (
            "analysis_date",
            "ts_code",
            "current_baseline",
            "target_return",
            "target_price",
            "horizon_days_10",
            "horizon_days_20",
            "horizon_days_30",
            "recent_return_20d",
            "relative_return_20d",
            "realized_volatility_20d_annualized",
            "atr_ratio_20d",
            "price_location_60d",
            "candidate_driver_evidence_ids",
            "counterevidence_input_ids",
            "formula_version",
            "input_hash",
        ),
        (EvidenceSectionName.CURRENT_PRICE_TO_TARGET_CONDITIONS,),
    ),
    _InputSpec("industry_member", "fact", "candidate", ("ts_code", "industry_code", "valid_from", "available_at"), (EvidenceSectionName.HOTSPOT_PANORAMA,)),
    _InputSpec("theme_member", "fact", "candidate", ("ts_code", "theme_code", "valid_from", "available_at"), (EvidenceSectionName.HOTSPOT_PANORAMA,)),
    _InputSpec("industry_daily", "fact", "group", ("industry_code", "trade_date", "close", "available_at"), (EvidenceSectionName.HOTSPOT_PANORAMA,)),
    _InputSpec("company_profile", "fact", "candidate", ("ts_code", "main_business", "business_scope", "available_at"), (EvidenceSectionName.BUSINESS_TRANSMISSION,)),
    _InputSpec("main_business", "fact", "candidate", ("ts_code", "report_period", "classification", "item_name", "available_at"), (EvidenceSectionName.BUSINESS_TRANSMISSION,)),
    _InputSpec("earnings_forecast", "fact", "candidate", ("ts_code", "report_period", "ann_date", "type", "p_change_min", "p_change_max", "available_at"), (EvidenceSectionName.FINANCIAL_QUALITY,)),
    _InputSpec("earnings_express", "fact", "candidate", ("ts_code", "report_period", "ann_date", "announcement_type", "yoy_net_profit", "available_at"), (EvidenceSectionName.FINANCIAL_QUALITY,)),
    _InputSpec("income_statement", "fact", "candidate", ("ts_code", "report_period", "revenue", "n_income_attr_p", "available_at"), (EvidenceSectionName.FINANCIAL_QUALITY,)),
    _InputSpec("balance_sheet", "fact", "candidate", ("ts_code", "report_period", "total_assets", "total_liab", "available_at"), (EvidenceSectionName.FINANCIAL_QUALITY, EvidenceSectionName.COUNTEREVIDENCE)),
    _InputSpec("cash_flow", "fact", "candidate", ("ts_code", "report_period", "n_cashflow_act", "available_at"), (EvidenceSectionName.FINANCIAL_QUALITY, EvidenceSectionName.COUNTEREVIDENCE)),
    _InputSpec("financial_indicator", "fact", "candidate", ("ts_code", "report_period", "roe", "available_at"), (EvidenceSectionName.FINANCIAL_QUALITY,)),
    _InputSpec("daily_basic", "fact", "group", ("ts_code", "trade_date", "pe_ttm", "pb", "ps_ttm", "total_mv", "available_at"), (EvidenceSectionName.VALUATION_CONTEXT,)),
    _InputSpec("equity_daily", "fact", "candidate", ("ts_code", "trade_date", "close", "high", "amount", "available_at"), (EvidenceSectionName.PRICE_VOLUME_LIQUIDITY,)),
    _InputSpec("adj_factor", "fact", "candidate", ("ts_code", "trade_date", "adj_factor", "available_at"), (EvidenceSectionName.PRICE_VOLUME_LIQUIDITY,)),
    _InputSpec("index_daily", "fact", "global", ("index_code", "trade_date", "close", "available_at"), (EvidenceSectionName.MARKET_CONSTRAINTS,)),
    _InputSpec("security_master", "fact", "candidate", ("ts_code", "exchange", "market", "list_status", "available_at"), (EvidenceSectionName.MARKET_CONSTRAINTS,)),
    _InputSpec("stock_limit", "fact", "candidate", ("ts_code", "trade_date", "up_limit", "down_limit", "available_at"), (EvidenceSectionName.MARKET_CONSTRAINTS,)),
    _InputSpec("suspension", "fact", "candidate", ("ts_code", "trade_date", "suspend_type", "available_at"), (EvidenceSectionName.MARKET_CONSTRAINTS,)),
    _InputSpec("announcement", "fact", "candidate", ("ts_code", "announcement_id", "announcement_time", "title", "available_at"), (EvidenceSectionName.COMPANY_EVENTS,)),
    _InputSpec("repurchase", "fact", "candidate", ("ts_code", "announcement_date", "process", "amount", "vol", "available_at"), (EvidenceSectionName.COMPANY_EVENTS, EvidenceSectionName.COUNTEREVIDENCE)),
    _InputSpec("holder_trade", "fact", "candidate", ("ts_code", "ann_date", "holder_name", "in_de", "change_vol", "available_at"), (EvidenceSectionName.COMPANY_EVENTS, EvidenceSectionName.COUNTEREVIDENCE)),
    _InputSpec("share_float", "fact", "candidate", ("ts_code", "ann_date", "float_date", "float_share", "available_at"), (EvidenceSectionName.COMPANY_EVENTS, EvidenceSectionName.COUNTEREVIDENCE)),
    _InputSpec("pledge", "fact", "candidate", ("ts_code", "end_date", "pledge_ratio", "available_at"), (EvidenceSectionName.COMPANY_EVENTS, EvidenceSectionName.COUNTEREVIDENCE)),
    _InputSpec("margin_detail", "fact", "candidate", ("ts_code", "trade_date", "rzye", "rzmre", "available_at"), (EvidenceSectionName.PRICE_VOLUME_LIQUIDITY,)),
)


_FIXED_ANALYSIS_NEEDS = (
    (EvidenceSectionName.MARKET_CONSTRAINTS, AnalysisModule.MARKET_ENVIRONMENT, (KnowledgeTopic.MARKET_STATE_RELIABILITY, KnowledgeTopic.RETURN_DISPERSION, KnowledgeTopic.MARKET_PRICE_PERSISTENCE)),
    (EvidenceSectionName.HOTSPOT_PANORAMA, AnalysisModule.SECTOR_THEME, (KnowledgeTopic.SECTOR_PRICE_PERSISTENCE, KnowledgeTopic.RETURN_DISPERSION)),
    (EvidenceSectionName.BUSINESS_TRANSMISSION, AnalysisModule.COMPANY_BUSINESS, (KnowledgeTopic.BUSINESS_TRANSMISSION, KnowledgeTopic.OFFICIAL_PUBLICATION_TIMING)),
    (EvidenceSectionName.FINANCIAL_QUALITY, AnalysisModule.FUNDAMENTALS, (KnowledgeTopic.PROFITABILITY_QUALITY, KnowledgeTopic.EARNINGS_DISCLOSURE_HIERARCHY, KnowledgeTopic.FINANCIAL_TURNAROUND)),
    (EvidenceSectionName.VALUATION_CONTEXT, AnalysisModule.VALUATION, (KnowledgeTopic.VALUATION_METHOD, KnowledgeTopic.PROFITABILITY_QUALITY)),
    (EvidenceSectionName.COMPANY_EVENTS, AnalysisModule.EVENTS, (KnowledgeTopic.OFFICIAL_PUBLICATION_TIMING, KnowledgeTopic.EVENT_PRICE_REACTION, KnowledgeTopic.EARNINGS_DRIFT, KnowledgeTopic.SHARE_REDUCTION, KnowledgeTopic.BUYBACK_STAGE, KnowledgeTopic.RESTRUCTURING_STAGE)),
    (EvidenceSectionName.PRICE_VOLUME_LIQUIDITY, AnalysisModule.PRICE_TRADING, (KnowledgeTopic.MARKET_PRICE_PERSISTENCE, KnowledgeTopic.LIQUIDITY_TRADING_ACTIVITY, KnowledgeTopic.RISK_OVEREXTENSION, KnowledgeTopic.TRADER_IDENTITY_BOUNDARY, KnowledgeTopic.EXCHANGE_CONSTRAINTS)),
    (EvidenceSectionName.COUNTEREVIDENCE, AnalysisModule.RISK, (KnowledgeTopic.DELISTING_RISK, KnowledgeTopic.PLEDGE_CONDITIONAL_RISK, KnowledgeTopic.LIQUIDITY_TRADING_ACTIVITY, KnowledgeTopic.RISK_OVEREXTENSION, KnowledgeTopic.PROFITABILITY_QUALITY)),
    (EvidenceSectionName.CURRENT_PRICE_TO_TARGET_CONDITIONS, AnalysisModule.TARGET_CONDITIONS, (KnowledgeTopic.VALUATION_METHOD, KnowledgeTopic.PROFITABILITY_QUALITY)),
)


def evidence_input_contract() -> tuple[EvidenceInputRequirement, ...]:
    """Return the frozen route-plus-evidence materialization contract."""

    return tuple(
        EvidenceInputRequirement(
            dataset=spec.dataset,
            kind=spec.kind,
            scope=spec.scope,
            required_fields=spec.required_fields,
            sections=spec.sections,
        )
        for spec in _INPUT_SPECS
    )


def build_evidence_source_catalog(
    warehouse: ResearchWarehouse,
    *,
    formation_date: date,
    route_fact_plan: RouteFactPlan,
) -> EvidenceSourceCatalog:
    """Attest the complete Task5-related inventory in Task4's warehouse."""

    if not isinstance(warehouse, ResearchWarehouse):
        raise TypeError("evidence source catalog requires a real ResearchWarehouse")
    if not isinstance(route_fact_plan, RouteFactPlan):
        raise TypeError("route_fact_plan must come from build_route_fact_plan")
    route_fact_plan.validate_integrity()
    universe_catalog = route_fact_plan.universe_catalog
    universe_catalog.validate_integrity()
    if formation_date != universe_catalog.formation_date:
        raise ValueError("evidence catalog formation date differs from Task4 catalog")
    attestation = build_source_catalog_attestation(
        warehouse, formation_date=formation_date
    )
    if attestation.attestation_hash != universe_catalog.source_attestation_hash:
        raise ValueError("evidence catalog is not from Task4's attested warehouse")

    inventory: list[dict[str, Any]] = []
    materialization_plan: dict[ResearchDatasetId, tuple[str, ...]] = {}
    fact_datasets = tuple(
        dict.fromkeys(spec.dataset for spec in _INPUT_SPECS if spec.kind == "fact")
    )
    for label in fact_datasets:
        dataset = ResearchDatasetId(label)
        manifest = warehouse.partition_manifest(dataset)
        if manifest.empty:
            continue
        if "partition_value" not in manifest:
            raise ValueError(f"warehouse inventory lacks partition key: {label}")
        partitions = tuple(sorted(manifest["partition_value"].astype(str)))
        validated = warehouse.validated_partition_manifest(dataset, partitions)
        if len(validated) != len(partitions):
            raise ValueError(f"validated evidence inventory is incomplete: {label}")
        for row in validated.to_dict(orient="records"):
            inventory.append(
                {
                    "dataset": label,
                    "partition": str(row["partition_value"]),
                    "row_count": int(row["row_count"]),
                    "content_hash": str(row["content_hash"]),
                    "file_sha256": str(row["file_sha256"]),
                    "quality_status": str(row["quality_status"]),
                }
            )
        materialization_plan[dataset] = partitions
    cutoff = formation_cutoff(formation_date)
    materialized = ResearchQuery(warehouse).materialize_snapshot(
        materialization_plan,
        as_of=cutoff,
    )
    source = materialized.input_manifest
    entries = source.get("partitions")
    source_hash = source.get("input_manifest_hash")
    if not isinstance(entries, Sequence) or not isinstance(source_hash, str):
        raise ValueError("evidence inventory materialization lacks a source manifest")
    final_attestation = build_source_catalog_attestation(
        warehouse, formation_date=formation_date
    )
    if final_attestation.attestation_hash != attestation.attestation_hash:
        raise ValueError("attested warehouse changed during evidence preflight")
    return EvidenceSourceCatalog(
        formation_date=formation_date,
        as_of=cutoff,
        route_catalog_hash=universe_catalog.catalog_hash,
        source_attestation_hash=attestation.attestation_hash,
        warehouse_root_identity=attestation.warehouse_root_identity,
        warehouse_tree_hash=attestation.warehouse_tree_hash,
        inventory=inventory,
        source_entries=entries,
        source_manifest_hash=source_hash,
        _token=_EVIDENCE_CATALOG_TOKEN,
    )


def build_evidence_fact_plan(
    *,
    route_fact_plan: RouteFactPlan,
    source_catalog: EvidenceSourceCatalog,
) -> EvidenceFactPlan:
    """Freeze the only Task 3 plan accepted by Task 5.

    Route partitions are copied exactly from Task 4.  Extra evidence partitions
    are selected from the same hashed source catalog using fixed historical
    windows; callers cannot inject ad-hoc partitions.
    """

    if not isinstance(route_fact_plan, RouteFactPlan):
        raise TypeError("route_fact_plan must come from build_route_fact_plan")
    if not isinstance(source_catalog, EvidenceSourceCatalog):
        raise TypeError("source_catalog must come from build_evidence_source_catalog")
    route_fact_plan.validate_integrity()
    source_catalog.validate_integrity()
    universe_catalog = route_fact_plan.universe_catalog
    universe_catalog.validate_integrity()
    formation_date = source_catalog.formation_date
    if source_catalog.route_catalog_hash != universe_catalog.catalog_hash:
        raise ValueError("evidence source and route plan use different catalogs")
    if (
        source_catalog.source_attestation_hash
        != universe_catalog.source_attestation_hash
    ):
        raise ValueError("evidence source and route plan use different warehouses")
    if universe_catalog.as_of.astimezone(_SHANGHAI).date() != formation_date:
        raise ValueError("universe catalog does not match evidence formation date")
    source_entries = source_catalog.source_entries()
    available = {
        dataset: source_catalog.partitions(dataset)
        for dataset in {str(item["dataset"]) for item in source_entries}
    }
    plan: dict[str, tuple[str, ...]] = dict(route_fact_plan)
    missing: list[str] = []
    daily_datasets = {
        "daily_basic",
        "equity_daily",
        "index_daily",
        "stock_limit",
        "suspension",
        "adj_factor",
        "margin_detail",
    }
    static_datasets = {"company_profile", "security_master"}
    report_datasets = {
        "income_statement",
        "balance_sheet",
        "cash_flow",
        "financial_indicator",
        "main_business",
    }
    event_month_datasets = {"holder_trade", "pledge"}
    forward_month_datasets = {"share_float"}
    announcement_months = route_fact_plan["announcement"]
    formation_month = formation_date.strftime("%Y-%m")
    for dataset in (
        *sorted(daily_datasets),
        *sorted(static_datasets),
        *sorted(report_datasets),
        *sorted(event_month_datasets),
        *sorted(forward_month_datasets),
    ):
        candidates = available.get(dataset, ())
        if dataset in daily_datasets:
            selected = tuple(
                sorted(
                    partition
                    for partition in candidates
                    if _partition_date(partition) is not None
                    and _partition_date(partition) <= formation_date
                )[-82:]
            )
        elif dataset in static_datasets:
            selected = candidates
        elif dataset in report_datasets:
            selected = tuple(
                sorted(
                    partition
                    for partition in candidates
                    if _partition_date(partition) is not None
                    and _partition_date(partition) <= formation_date
                )[-8:]
            )
        elif dataset in event_month_datasets:
            selected = tuple(
                month for month in announcement_months if month in candidates
            )
        else:
            selected = tuple(
                partition
                for partition in candidates
                if formation_month <= partition <= _month_offset(formation_date, 2)
            )
        if selected:
            plan[dataset] = selected
        else:
            missing.append(dataset)
    selected_keys = {
        (dataset, partition)
        for dataset, selected in plan.items()
        for partition in selected
    }
    selected_entries = tuple(
        item
        for item in source_entries
        if (str(item["dataset"]), str(item["partition"])) in selected_keys
    )
    if len(selected_entries) != len(selected_keys):
        raise ValueError("evidence plan contains a partition absent from source catalog")
    source_payload = {
        "as_of": source_catalog.as_of.astimezone(timezone.utc).isoformat(),
        "partitions": list(selected_entries),
    }
    plan_source_hash = _stable_hash(source_payload)
    evidence_plan = EvidenceFactPlan(
        plan,
        route_plan=route_fact_plan,
        catalog_hash=source_catalog.catalog_hash,
        source_manifest_hash=plan_source_hash,
        source_attestation_hash=source_catalog.source_attestation_hash,
        source_as_of=source_catalog.as_of.astimezone(timezone.utc).isoformat(),
        source_entries=selected_entries,
        missing_datasets=tuple(missing),
        _token=_EVIDENCE_PLAN_TOKEN,
    )
    return evidence_plan


def project_route_snapshot(
    snapshot: FormationSnapshot,
    evidence_plan: EvidenceFactPlan,
) -> FormationSnapshot:
    """Accept only an independently materialized exact route snapshot.

    Source attestation hashes cover physical files and effective content.  An
    in-memory projection must therefore never manufacture a replacement facts
    manifest.  Callers materialize ``evidence_plan.route_fact_plan`` through
    Task 3 and use this helper only to assert that the resulting public snapshot
    is exact before scanning.
    """

    if type(snapshot) is not FormationSnapshot:
        raise TypeError("route snapshot must be a Task 3 FormationSnapshot")
    if not isinstance(evidence_plan, EvidenceFactPlan):
        raise TypeError("evidence_plan must come from build_evidence_fact_plan")
    evidence_plan.validate_integrity()
    route_plan = evidence_plan.route_fact_plan
    source = snapshot.facts.manifest["source_snapshot"]
    source_partitions = source.get("partitions")
    if not isinstance(source_partitions, Sequence):
        raise TypeError("route snapshot lacks source partitions")
    actual_keys = {
        (str(item.get("dataset")), str(item.get("partition")))
        for item in source_partitions
        if isinstance(item, Mapping)
    }
    required_keys = {
        (dataset, partition)
        for dataset, partitions in route_plan.items()
        for partition in partitions
    }
    if actual_keys != required_keys:
        raise ValueError("Task 3 snapshot does not exactly equal the route fact plan")
    _fact_frames(snapshot)
    return snapshot


def build_verified_evidence_snapshot_bundle(
    route_scan_batch: VerifiedRouteScanBatch,
    warehouse: ResearchWarehouse,
    source_catalog: EvidenceSourceCatalog,
    evidence_plan: EvidenceFactPlan,
    snapshot: FormationSnapshot,
) -> VerifiedEvidenceSnapshotBundle:
    """Bind an independently materialized full snapshot to one verified scan."""

    batch = require_verified_route_scan_batch(route_scan_batch)
    if not isinstance(warehouse, ResearchWarehouse):
        raise TypeError("evidence bundle requires the real source warehouse")
    if not isinstance(source_catalog, EvidenceSourceCatalog):
        raise TypeError("source_catalog must come from its public builder")
    if not isinstance(evidence_plan, EvidenceFactPlan):
        raise TypeError("evidence_plan must come from its public builder")
    if type(snapshot) is not FormationSnapshot:
        raise TypeError("evidence snapshot must be a Task3 FormationSnapshot")
    source_catalog.validate_integrity()
    evidence_plan.validate_integrity()
    if evidence_plan.catalog_hash != source_catalog.catalog_hash:
        raise ValueError("evidence plan and source catalog identities differ")
    policy = batch.window_policy
    if (
        policy.universe_source_attestation_hash
        != source_catalog.source_attestation_hash
        or policy.universe_catalog_hash != source_catalog.route_catalog_hash
    ):
        raise ValueError("evidence bundle and route batch are from different warehouses")
    refreshed = build_evidence_source_catalog(
        warehouse,
        formation_date=source_catalog.formation_date,
        route_fact_plan=evidence_plan.route_fact_plan,
    )
    if (
        refreshed.catalog_hash != source_catalog.catalog_hash
        or refreshed.warehouse_root_identity != source_catalog.warehouse_root_identity
        or refreshed.warehouse_tree_hash != source_catalog.warehouse_tree_hash
    ):
        raise ValueError("evidence warehouse changed after catalog preflight")
    _validate_evidence_snapshot(snapshot, evidence_plan)
    route_projection_hash = _route_projection_hash(
        snapshot,
        batch.snapshot,
        evidence_plan,
    )
    return VerifiedEvidenceSnapshotBundle(
        batch_hash=batch.batch_hash,
        batch_identity=id(batch),
        snapshot=snapshot,
        evidence_plan=evidence_plan,
        source_catalog=source_catalog,
        route_projection_hash=route_projection_hash,
        _token=_EVIDENCE_BUNDLE_TOKEN,
    )


def require_verified_evidence_snapshot_bundle(
    value: Any,
    route_scan_batch: VerifiedRouteScanBatch,
) -> VerifiedEvidenceSnapshotBundle:
    """Fail closed unless the exact registered bundle matches this batch."""

    batch = require_verified_route_scan_batch(route_scan_batch)
    if type(value) is not VerifiedEvidenceSnapshotBundle:
        raise ValueError("evidence snapshot bundle lacks registered provenance")
    registration = _EVIDENCE_BUNDLE_REGISTRY.get(value)
    if registration is None:
        raise ValueError("evidence snapshot bundle lacks registered provenance")
    snapshot = value._VerifiedEvidenceSnapshotBundle__snapshot
    evidence_plan = value._VerifiedEvidenceSnapshotBundle__evidence_plan
    source_catalog = value._VerifiedEvidenceSnapshotBundle__source_catalog
    if (
        registration.snapshot_identity != id(snapshot)
        or registration.plan_identity != id(evidence_plan)
        or registration.catalog_identity != id(source_catalog)
    ):
        raise ValueError("evidence snapshot bundle component identity mismatch")
    if (
        registration.batch_hash != batch.batch_hash
        or registration.batch_identity != id(batch)
    ):
        raise ValueError("evidence snapshot bundle belongs to another route batch")
    source_catalog.validate_integrity()
    evidence_plan.validate_integrity()
    _validate_evidence_snapshot(snapshot, evidence_plan)
    snapshot_hash = _formation_snapshot_content_hash(snapshot)
    if snapshot_hash != value._VerifiedEvidenceSnapshotBundle__snapshot_content_hash:
        raise ValueError("evidence snapshot bundle content changed")
    route_projection_hash = _route_projection_hash(
        snapshot,
        batch.snapshot,
        evidence_plan,
    )
    if route_projection_hash != value._VerifiedEvidenceSnapshotBundle__route_projection_hash:
        raise ValueError("evidence route projection changed")
    bundle_hash = _stable_hash(
        {
            "batch_hash": batch.batch_hash,
            "snapshot_content_hash": snapshot_hash,
            "evidence_plan_hash": evidence_plan.plan_hash,
            "source_catalog_hash": source_catalog.catalog_hash,
            "route_projection_hash": route_projection_hash,
        }
    )
    if (
        bundle_hash != registration.bundle_hash
        or bundle_hash != value._VerifiedEvidenceSnapshotBundle__bundle_hash
    ):
        raise ValueError("evidence snapshot bundle canonical hash mismatch")
    return value


def _validate_evidence_snapshot(
    snapshot: FormationSnapshot,
    evidence_plan: EvidenceFactPlan,
) -> None:
    if (
        snapshot.analysis_date
        != evidence_plan.route_fact_plan.universe_catalog.formation_date
    ):
        raise ValueError("evidence snapshot formation date differs from its plan")
    source = snapshot.facts.manifest["source_snapshot"]
    entries = tuple(dict(item) for item in source.get("partitions", ()))
    if (
        source.get("input_manifest_hash") != evidence_plan.source_manifest_hash
        or entries != evidence_plan.source_entries
    ):
        raise ValueError("full snapshot does not exactly match the evidence plan")
    _fact_frames(snapshot)
    _feature_frames(snapshot)


def _route_projection_hash(
    full_snapshot: FormationSnapshot,
    route_snapshot: FormationSnapshot,
    evidence_plan: EvidenceFactPlan,
) -> str:
    if (
        full_snapshot.analysis_date != route_snapshot.analysis_date
        or full_snapshot.as_of != route_snapshot.as_of
    ):
        raise ValueError("full and route snapshots use different formation cutoffs")
    if full_snapshot.formula_versions != route_snapshot.formula_versions:
        raise ValueError("full and route snapshots use different formula versions")
    if full_snapshot.fact_manifest_hashes != route_snapshot.fact_manifest_hashes:
        raise ValueError("full and route feature input manifests differ")
    if full_snapshot.cache_key != route_snapshot.cache_key:
        raise ValueError("full and route feature cache identities differ")
    route_plan = evidence_plan.route_fact_plan
    route_keys = {
        (dataset, partition)
        for dataset, partitions in route_plan.items()
        for partition in partitions
    }
    full_source = full_snapshot.facts.manifest["source_snapshot"]
    route_source = route_snapshot.facts.manifest["source_snapshot"]
    projected_entries = tuple(
        item
        for item in full_source["partitions"]
        if (str(item.get("dataset")), str(item.get("partition"))) in route_keys
    )
    route_entries = tuple(route_source["partitions"])
    if projected_entries != route_entries:
        raise ValueError("full snapshot route partitions differ from Task4 snapshot")
    projected_source_hash = _stable_hash(
        {"as_of": full_source["as_of"], "partitions": list(projected_entries)}
    )
    if projected_source_hash != route_source.get("input_manifest_hash"):
        raise ValueError("full snapshot route source hash differs from Task4 snapshot")
    full_facts, _ = _fact_frames(full_snapshot)
    route_facts, _ = _fact_frames(route_snapshot)
    fact_hashes = {
        dataset: _frame_content_hash(
            _project_fact_frame_to_partitions(
                dataset,
                full_facts.get(dataset, pd.DataFrame()),
                route_plan[dataset],
            )
        )
        for dataset in route_plan
    }
    route_fact_hashes = {
        dataset: _frame_content_hash(route_facts.get(dataset, pd.DataFrame()))
        for dataset in route_plan
    }
    if fact_hashes != route_fact_hashes:
        raise ValueError("full snapshot route fact contents differ from Task4 snapshot")
    full_features = _feature_frames(full_snapshot)
    route_features = _feature_frames(route_snapshot)
    feature_names = tuple(sorted(set(route_features)))
    full_feature_hashes = {
        name: _frame_content_hash(full_features.get(name, pd.DataFrame()))
        for name in feature_names
    }
    route_feature_hashes = {
        name: _frame_content_hash(route_features[name]) for name in feature_names
    }
    if full_feature_hashes != route_feature_hashes:
        raise ValueError("full snapshot route feature contents differ from Task4 snapshot")
    return _stable_hash(
        {
            "source_hash": projected_source_hash,
            "fact_hashes": fact_hashes,
            "feature_hashes": full_feature_hashes,
            "formula_versions": full_snapshot.formula_versions,
            "feature_input_manifest_hashes": full_snapshot.fact_manifest_hashes,
            "feature_cache_key": full_snapshot.cache_key,
            "cutoff": full_snapshot.as_of,
        }
    )


def _project_fact_frame_to_partitions(
    dataset: str,
    frame: pd.DataFrame,
    partitions: Sequence[str],
) -> pd.DataFrame:
    if frame.empty:
        return frame.copy(deep=True)
    partition_set = set(partitions)
    if "report_period" in frame and all(_partition_date(value) for value in partitions):
        return frame[frame["report_period"].astype(str).isin(partition_set)].copy()
    if "trade_date" in frame and all(_partition_date(value) for value in partitions):
        return frame[frame["trade_date"].astype(str).isin(partition_set)].copy()
    if all(len(value) == 7 for value in partitions):
        date_fields = (
            "announcement_time",
            "announcement_date",
            "ann_date",
            "end_date",
        )
        for field in date_fields:
            if field in frame:
                months = pd.to_datetime(frame[field], errors="coerce").dt.strftime("%Y-%m")
                return frame[months.isin(partition_set)].copy()
    return frame.copy(deep=True)


def _frame_content_hash(frame: pd.DataFrame) -> str:
    columns = tuple(sorted(str(column) for column in frame.columns))
    row_hashes = sorted(
        _stable_hash(
            {column: _scalar(row[column]) for column in columns}
        )
        for _, row in frame.loc[:, list(columns)].iterrows()
    )
    return _stable_hash({"columns": columns, "rows": row_hashes})


def _formation_snapshot_content_hash(snapshot: FormationSnapshot) -> str:
    facts, source = _fact_frames(snapshot)
    features = _feature_frames(snapshot)
    return _stable_hash(
        {
            "analysis_date": snapshot.analysis_date,
            "as_of": snapshot.as_of,
            "source_manifest": source,
            "fact_hashes": {
                name: _frame_content_hash(frame) for name, frame in sorted(facts.items())
            },
            "feature_hashes": {
                name: _frame_content_hash(frame)
                for name, frame in sorted(features.items())
            },
            "formula_versions": snapshot.formula_versions,
        }
    )


def _verified_lead_ledger_hash(lead_members: Sequence[Any]) -> str:
    return _stable_hash(
        tuple(
            {
                "route": item.route.value,
                "evidence_id": item.evidence_id,
                "security_id": item.security_id,
                "usable_for_decision": item.usable_for_decision,
                "needs_deep_read": item.needs_deep_read,
                "route_input_record": item.route_input_record,
                "input_hash": item.input_hash,
                "route_manifest_input_hash": item.route_manifest_input_hash,
                "dataset": item.dataset,
                "available_at": item.available_at,
                "fact_summary": item.fact_summary,
                "deep_read_input_hash": item.deep_read_input_hash,
            }
            for item in lead_members
        )
    )


def _partition_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _month_offset(value: date, months: int) -> str:
    absolute = value.year * 12 + value.month - 1 + months
    return f"{absolute // 12:04d}-{absolute % 12 + 1:02d}"


def build_candidate_packet(
    route_scan_batch: VerifiedRouteScanBatch,
    evidence_snapshot_bundle: VerifiedEvidenceSnapshotBundle,
    security_id: str,
) -> CandidateEvidencePacket:
    """Build from the sole trusted Task4 receipt; no component injection API."""

    batch = require_verified_route_scan_batch(route_scan_batch)
    bundle = require_verified_evidence_snapshot_bundle(
        evidence_snapshot_bundle, batch
    )
    snapshot = bundle._VerifiedEvidenceSnapshotBundle__snapshot
    evidence_plan = bundle._VerifiedEvidenceSnapshotBundle__evidence_plan
    hypothesis = batch.hypothesis_for_security(security_id)
    route_manifests = batch.manifests_for_security(security_id)
    lead_members = batch.lead_members(security_id)
    return _build_candidate_packet_from_verified_parts(
        snapshot,
        hypothesis,
        load_knowledge_registry(_REGISTRY_PATH),
        evidence_plan=evidence_plan,
        route_policy=batch.window_policy,
        route_manifests=route_manifests,
        verified_batch_receipt_hash=batch.batch_hash,
        raw_lead_ledger_hash=_verified_lead_ledger_hash(lead_members),
    )


def _build_candidate_packet_from_verified_parts(
    snapshot: Any,
    hypothesis: Any,
    registry: KnowledgeRegistry,
    *,
    evidence_plan: EvidenceFactPlan,
    route_policy: RouteWindowPolicy,
    route_manifests: Iterable[RouteScanManifest],
    verified_batch_receipt_hash: str,
    raw_lead_ledger_hash: str,
    requested_knowledge_ids: Iterable[str] = (),
) -> CandidateEvidencePacket:
    """Build one strict packet; absent inputs remain explicitly absent."""

    _validate_cutoffs(snapshot, hypothesis)
    official, registry_audit_base = _validate_frozen_registry(registry)
    plan_audit, route_audit, manifests_by_route = _bind_route_manifests(
        snapshot,
        hypothesis,
        evidence_plan,
        route_policy,
        route_manifests,
        verified_batch_receipt_hash,
        raw_lead_ledger_hash,
    )
    requested = tuple(dict.fromkeys(str(value) for value in requested_knowledge_ids))
    entries_by_id = {entry.knowledge_id: entry for entry in official.entries}
    for knowledge_id in requested:
        entry = entries_by_id.get(knowledge_id)
        if entry is None:
            raise ValueError(f"unknown knowledge reference: {knowledge_id}")
        if entry.version_status == "historical_only":
            raise ValueError(f"historical_only knowledge is forbidden: {knowledge_id}")
        if entry.version_status != "current":
            raise ValueError(f"non-current knowledge is forbidden: {knowledge_id}")

    raw_facts, fact_manifest = _fact_frames(snapshot)
    raw_features = _feature_frames(snapshot)
    _reject_future_rows((*raw_facts.values(),), snapshot.as_of)
    _validate_derived_dates(raw_features, snapshot.analysis_date)
    facts, features, coverage = _prepare_inputs(
        snapshot,
        hypothesis.security_id,
        raw_facts,
        raw_features,
        fact_manifest,
    )
    api, local, dataset_ids = _materialize_fixed_evidence(
        snapshot,
        hypothesis,
        facts,
        features,
        coverage,
        manifests_by_route,
    )
    generated_frames, generated_local, generated_coverage = _build_local_observation_inputs(
        snapshot,
        hypothesis.security_id,
        facts,
        features,
        (*api, *local),
        dataset_ids,
    )
    features = {**features, **generated_frames}
    local = tuple(sorted((*local, *generated_local), key=lambda item: item.evidence_id))
    coverage = (*coverage, *generated_coverage)
    cards = _build_opportunity_cards(
        coverage,
        facts,
        features,
        dataset_ids,
        snapshot.as_of,
        hypothesis.security_id,
    )
    sections, section_ids, missing_text = _build_sections(
        coverage,
        cards,
        dataset_ids,
        facts,
        features,
        snapshot.as_of,
        hypothesis.security_id,
    )
    capabilities = _candidate_capabilities(snapshot, facts, features, coverage)
    current_entries = tuple(
        entry for entry in official.entries if entry.version_status == "current"
    )
    current_registry = official.model_copy(update={"entries": current_entries})
    governed_opportunities = _governed_opportunities(
        hypothesis.preliminary_opportunity, hypothesis.discovery_routes
    )
    selected_values: dict[str, list[KnowledgeSelection]] = defaultdict(list)
    for governed_opportunity in governed_opportunities:
        for knowledge_id, values in _select_for_fixed_needs(
            current_registry,
            capabilities,
            snapshot.analysis_date,
            governed_opportunity,
            hypothesis.discovery_routes,
        ).items():
            selected_values[knowledge_id].extend(values)
    selected = {
        knowledge_id: tuple(values)
        for knowledge_id, values in selected_values.items()
    }
    candidate_gaps = {
        entry.knowledge_id: _candidate_requirement_gaps(entry, facts, features)
        for entry in current_entries
    }
    selected = {
        knowledge_id: value
        for knowledge_id, value in selected.items()
        if not candidate_gaps[knowledge_id]
    }
    evidence = (*api, *local)
    routing = _knowledge_routing(
        current_entries,
        selected,
        candidate_gaps,
        capabilities,
        snapshot.analysis_date,
        _governed_opportunity(hypothesis.preliminary_opportunity),
        evidence,
        section_ids,
    )
    prepared_ids = {
        record.knowledge_id
        for record in routing
        if record.status is KnowledgeRoutingStatus.PREPARED_FOR_JUDGMENT
    }
    for knowledge_id in requested:
        if knowledge_id not in prepared_ids:
            raise ValueError(
                f"knowledge is not applicable or not prepared for judgment: {knowledge_id}"
            )
    selected_audit = tuple(
        SelectedKnowledgeAudit(
            knowledge_id=entry.knowledge_id,
            version_status="current",
            entry_content_hash=_stable_hash(entry.model_dump(mode="json")),
            effect=entry.effect,
            use_purpose=next(
                record.use_purpose
                for record in routing
                if record.knowledge_id == entry.knowledge_id
            ),
        )
        for entry in current_entries
        if entry.knowledge_id in prepared_ids
    )
    registry_audit = registry_audit_base.model_copy(
        update={"prepared_entries": selected_audit}
    )
    known_ids = tuple(item.evidence_id for item in evidence)
    next_validation = tuple(
        _referenced_text(question, known_ids)
        for question in hypothesis.questions_to_verify
    )
    return CandidateEvidencePacket(
        security_id=hypothesis.security_id,
        formation_date=snapshot.analysis_date,
        cutoff=snapshot.as_of,
        discovery_routes=tuple(hypothesis.discovery_routes),
        preliminary_opportunity=hypothesis.preliminary_opportunity,
        registry_audit=registry_audit,
        evidence_plan_audit=plan_audit,
        route_manifest_audit=route_audit,
        input_coverage=coverage,
        api_facts=api,
        local_observations=local,
        model_judgments=(),
        opportunity_cards=cards,
        sections=sections,
        knowledge_routing=routing,
        unknowns=tuple(EvidenceText(text=value) for value in missing_text),
        next_validation=next_validation,
    )


def _validate_cutoffs(snapshot: Any, hypothesis: Any) -> None:
    for field in ("analysis_date", "as_of", "facts", "features"):
        if not hasattr(snapshot, field):
            raise TypeError(f"snapshot lacks {field}")
    for field in ("security_id", "formation_date", "cutoff", "discovery_routes", "evidence"):
        if not hasattr(hypothesis, field):
            raise TypeError(f"hypothesis lacks {field}")
    if snapshot.analysis_date != hypothesis.formation_date:
        raise ValueError("snapshot and hypothesis formation dates differ")
    expected = formation_cutoff(snapshot.analysis_date)
    if not _is_exact_formation_cutoff(
        snapshot.as_of, snapshot.analysis_date
    ) or not _is_exact_formation_cutoff(hypothesis.cutoff, snapshot.analysis_date):
        raise ValueError("formation cutoff must be Asia/Shanghai 23:59:59")
    if snapshot.as_of != expected or hypothesis.cutoff != expected:
        raise ValueError("formation cutoff must be Asia/Shanghai 23:59:59")


def _is_exact_formation_cutoff(value: datetime, origin: date) -> bool:
    return (
        isinstance(value, datetime)
        and getattr(value.tzinfo, "key", None) == "Asia/Shanghai"
        and value.date() == origin
        and value.timetz().replace(tzinfo=None) == time(23, 59, 59)
    )


def _validate_frozen_registry(
    supplied: KnowledgeRegistry,
) -> tuple[KnowledgeRegistry, RegistryAudit]:
    if not isinstance(supplied, KnowledgeRegistry):
        raise TypeError("registry must be a governed KnowledgeRegistry")
    file_hash = _sha256_file(_REGISTRY_PATH)
    official = load_knowledge_registry(_REGISTRY_PATH)
    current_ids = tuple(
        sorted(entry.knowledge_id for entry in official.entries if entry.version_status == "current")
    )
    historical_ids = tuple(
        sorted(
            entry.knowledge_id
            for entry in official.entries
            if entry.version_status == "historical_only"
        )
    )
    checks = (
        file_hash == _FROZEN_REGISTRY_FILE_SHA256,
        official.registry_hash == _FROZEN_REGISTRY_HASH,
        len(current_ids) == _FROZEN_CURRENT_COUNT,
        len(historical_ids) == _FROZEN_HISTORICAL_COUNT,
        _stable_hash(current_ids) == _FROZEN_CURRENT_IDS_HASH,
        _stable_hash(historical_ids) == _FROZEN_HISTORICAL_IDS_HASH,
        supplied.model_dump(mode="json") == official.model_dump(mode="json"),
    )
    if not all(checks):
        raise ValueError("supplied registry does not match the frozen official registry")
    return official, RegistryAudit(
        registry_hash=official.registry_hash,
        registry_file_sha256=file_hash,
        current_count=27,
        historical_only_count=3,
        current_ids_hash=_stable_hash(current_ids),
        historical_only_ids_hash=_stable_hash(historical_ids),
        prepared_entries=(),
    )


def _bind_route_manifests(
    snapshot: Any,
    hypothesis: Any,
    evidence_plan: EvidenceFactPlan,
    route_policy: RouteWindowPolicy,
    manifests: Iterable[RouteScanManifest],
    verified_batch_receipt_hash: str,
    raw_lead_ledger_hash: str,
) -> tuple[
    EvidencePlanAudit,
    tuple[RouteManifestAudit, ...],
    dict[DiscoveryRoute, RouteScanManifest],
]:
    if not isinstance(evidence_plan, EvidenceFactPlan):
        raise TypeError("evidence_plan must come from build_evidence_fact_plan")
    if not isinstance(route_policy, RouteWindowPolicy):
        raise TypeError("route_policy must come from build_route_window_policy")
    for label, value in (
        ("verified batch receipt", verified_batch_receipt_hash),
        ("raw lead ledger", raw_lead_ledger_hash),
    ):
        if not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ValueError(f"{label} hash is invalid")
    evidence_plan.validate_integrity()
    if route_policy.formation_date != snapshot.analysis_date:
        raise ValueError("route policy formation date does not match snapshot")
    if (
        route_policy.universe_catalog_hash
        != evidence_plan.route_fact_plan.universe_catalog.catalog_hash
    ):
        raise ValueError("route policy and evidence plan use different route catalogs")
    if (
        route_policy.universe_source_manifest_hash
        != evidence_plan.route_fact_plan.universe_catalog.source_manifest_hash
    ):
        raise ValueError("route policy and route plan use different universe manifests")
    if (
        route_policy.universe_source_attestation_hash
        != evidence_plan.source_attestation_hash
    ):
        raise ValueError("route policy and evidence plan use different attestations")
    source = getattr(snapshot.facts, "manifest", {}).get("source_snapshot", {})
    source_payload = {"as_of": source.get("as_of"), "partitions": source.get("partitions")}
    snapshot_source_hash = source.get("input_manifest_hash")
    if snapshot_source_hash != _stable_hash(source_payload):
        raise ValueError("snapshot source manifest hash mismatch")
    if snapshot_source_hash != evidence_plan.source_manifest_hash:
        raise ValueError("snapshot source manifest differs from evidence source catalog")
    actual_entries = tuple(
        dict(item)
        for item in source.get("partitions", ())
        if isinstance(item, Mapping)
    )
    if actual_entries != evidence_plan.source_entries:
        raise ValueError(
            "snapshot partition contents differ from the attested evidence plan"
        )
    actual_plan: dict[str, list[str]] = defaultdict(list)
    for item in source.get("partitions", ()):
        if isinstance(item, Mapping):
            actual_plan[str(item.get("dataset"))].append(str(item.get("partition")))
    if {
        dataset: tuple(partitions) for dataset, partitions in actual_plan.items()
    } != dict(evidence_plan):
        raise ValueError("snapshot partitions do not exactly equal the evidence plan")
    values = tuple(manifests)
    by_route = {item.route: item for item in values}
    if len(by_route) != len(values) or set(by_route) != set(DiscoveryRoute):
        raise ValueError("route manifests must contain each route exactly once")
    audits: list[RouteManifestAudit] = []
    for route in DiscoveryRoute:
        manifest = by_route[route]
        if manifest.formation_date != snapshot.analysis_date or manifest.cutoff != snapshot.as_of:
            raise ValueError("route manifest formation cutoff does not match snapshot")
        expected_partitions = tuple(
            f"{dataset}:{partition}"
            for dataset, partitions in route_policy.route_partitions[route].items()
            for partition in partitions
        )
        if manifest.requested_partitions != expected_partitions:
            raise ValueError("route manifest does not match the frozen route policy")
        audits.append(
            RouteManifestAudit(
                route=route,
                input_hash=manifest.input_hash,
                snapshot_cache_key=snapshot.cache_key,
                bound_hash=_stable_hash(
                    {
                        "route": route.value,
                        "route_input_hash": manifest.input_hash,
                        "snapshot_cache_key": snapshot.cache_key,
                        "formula_versions": getattr(snapshot, "formula_versions", ()),
                    }
                ),
            )
        )
    scan_hash = _stable_hash(
        [by_route[route].model_dump(mode="json") for route in DiscoveryRoute]
    )
    return (
        EvidencePlanAudit(
            evidence_plan_hash=evidence_plan.plan_hash,
            evidence_source_catalog_hash=evidence_plan.catalog_hash,
            evidence_catalog_manifest_hash=evidence_plan.source_manifest_hash,
            snapshot_source_manifest_hash=str(snapshot_source_hash),
            route_policy_hash=route_policy.policy_hash,
            universe_source_manifest_hash=route_policy.universe_source_manifest_hash,
            universe_source_attestation_hash=route_policy.universe_source_attestation_hash,
            universe_catalog_hash=route_policy.universe_catalog_hash,
            complete_route_scan_hash=scan_hash,
            verified_batch_receipt_hash=verified_batch_receipt_hash,
            raw_lead_ledger_hash=raw_lead_ledger_hash,
        ),
        tuple(audits),
        by_route,
    )


def _fact_frames(snapshot: Any) -> tuple[dict[str, pd.DataFrame], Mapping[str, Any]]:
    manifest = getattr(snapshot.facts, "manifest", None)
    source = manifest.get("source_snapshot") if isinstance(manifest, Mapping) else None
    partitions = source.get("partitions") if isinstance(source, Mapping) else None
    if not isinstance(partitions, Sequence):
        raise TypeError("snapshot fact manifest lacks source partitions")
    datasets = sorted(
        {
            str(item.get("dataset") or item.get("dataset_id"))
            for item in partitions
            if isinstance(item, Mapping)
            and (item.get("dataset") or item.get("dataset_id"))
        }
    )
    frames = {
        dataset: _as_frame(snapshot.facts.dataset(dataset)) for dataset in datasets
    }
    source_payload = {
        "as_of": source.get("as_of"),
        "partitions": partitions,
    }
    if source.get("input_manifest_hash") != _stable_hash(source_payload):
        raise ValueError("snapshot source manifest hash mismatch")
    view_payload = {
        "source_snapshot": source,
        "effective_date": manifest.get("effective_date"),
        "effective_rows": manifest.get("effective_rows"),
    }
    if manifest.get("view_manifest_hash") != _stable_hash(view_payload):
        raise ValueError("snapshot fact view manifest hash mismatch")
    if manifest.get("effective_date") != snapshot.analysis_date.isoformat():
        raise ValueError("snapshot fact view effective date mismatch")
    effective_rows = manifest.get("effective_rows")
    if not isinstance(effective_rows, Sequence):
        raise TypeError("snapshot fact view lacks effective rows")
    declared: dict[str, int] = {}
    for raw in effective_rows:
        if not isinstance(raw, Mapping):
            raise TypeError("effective row entries must be mappings")
        dataset = str(raw.get("dataset", ""))
        if not dataset or dataset in declared:
            raise ValueError("effective row entries must have unique dataset keys")
        declared[dataset] = int(raw.get("row_count", -1))
    if declared != {dataset: len(frame) for dataset, frame in frames.items()}:
        raise ValueError("snapshot fact view effective rows do not match materialized frames")
    return frames, source


def _feature_frames(snapshot: Any) -> dict[str, pd.DataFrame]:
    frames: dict[str, pd.DataFrame] = {}
    for spec in _INPUT_SPECS:
        if spec.kind != "derived":
            continue
        try:
            frames[spec.dataset] = _as_frame(snapshot.features.read(spec.dataset))
        except KeyError:
            continue
    return frames


def _prepare_inputs(
    snapshot: Any,
    security_id: str,
    raw_facts: Mapping[str, pd.DataFrame],
    raw_features: Mapping[str, pd.DataFrame],
    source_manifest: Mapping[str, Any],
) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame], tuple[EvidenceInputCoverage, ...]]:
    specs = {spec.dataset: spec for spec in _INPUT_SPECS}
    for dataset, frame in (*raw_facts.items(), *raw_features.items()):
        spec = specs.get(dataset)
        if spec is not None and spec.scope == "candidate" and not frame.empty:
            if _SECURITY_FIELD not in frame.columns:
                raise ValueError(f"candidate dataset {dataset} lacks a governed security key")

    memberships: dict[str, set[str]] = {"industry": set(), "theme": set()}
    facts: dict[str, pd.DataFrame] = {}
    features: dict[str, pd.DataFrame] = {}
    for spec in _INPUT_SPECS:
        if spec.kind == "local":
            continue
        source = (raw_facts if spec.kind == "fact" else raw_features).get(spec.dataset)
        if source is None:
            continue
        if spec.scope == "candidate":
            filtered = _filter_candidate(source, security_id, spec.dataset)
        elif spec.scope == "global":
            filtered = source.copy(deep=True)
        else:
            filtered = source.copy(deep=True)
        (facts if spec.kind == "fact" else features)[spec.dataset] = filtered
        if spec.dataset in {"industry_member", "theme_member"} and not filtered.empty:
            _validate_effective_membership(filtered, snapshot.analysis_date, spec.dataset)
            kind = "industry" if spec.dataset == "industry_member" else "theme"
            field = "industry_code" if kind == "industry" else "theme_code"
            if field in filtered:
                memberships[kind].update(filtered[field].dropna().astype(str))

    if "industry_daily" in facts:
        frame = facts["industry_daily"]
        facts["industry_daily"] = (
            frame[frame["industry_code"].astype(str).isin(memberships["industry"])].copy()
            if "industry_code" in frame
            else frame.iloc[0:0].copy()
        )
    if "daily_basic" in facts:
        peer_ids = {security_id}
        membership = raw_facts.get("industry_member")
        if membership is not None and not membership.empty:
            for _, row in membership.iterrows():
                valid_from = _as_datetime(row.get("valid_from"))
                valid_to = _as_datetime(row.get("valid_to"))
                code = str(row.get("industry_code", ""))
                if (
                    code in memberships["industry"]
                    and valid_from is not None
                    and valid_from.date() <= snapshot.analysis_date
                    and (valid_to is None or valid_to.date() >= snapshot.analysis_date)
                ):
                    peer_ids.add(str(row.get("ts_code", "")))
        frame = facts["daily_basic"]
        facts["daily_basic"] = (
            frame[frame["ts_code"].astype(str).isin(peer_ids)].copy()
            if "ts_code" in frame
            else frame.iloc[0:0].copy()
        )
    if "sector_hotspot" in features:
        frame = features["sector_hotspot"]
        if {"group_type", "group_code"}.issubset(frame.columns):
            mask = pd.Series(False, index=frame.index)
            for kind, codes in memberships.items():
                mask |= frame["group_type"].astype(str).eq(kind) & frame[
                    "group_code"
                ].astype(str).isin(codes)
            features["sector_hotspot"] = frame[mask].copy()
        else:
            features["sector_hotspot"] = frame.iloc[0:0].copy()

    source_hash = source_manifest.get("input_manifest_hash")
    coverage: list[EvidenceInputCoverage] = []
    for spec in _INPUT_SPECS:
        if spec.kind == "local":
            continue
        frame = (facts if spec.kind == "fact" else features).get(spec.dataset)
        raw = (raw_facts if spec.kind == "fact" else raw_features).get(spec.dataset)
        status: EvidenceInputStatus
        detail: str
        missing_fields: tuple[str, ...] = ()
        if raw is None:
            status = EvidenceInputStatus.NOT_MATERIALIZED
            detail = "not_materialized: dataset absent from formation snapshot"
        elif frame is None or frame.empty:
            status = (
                EvidenceInputStatus.CANDIDATE_HAS_NO_ROW
                if spec.scope in {"candidate", "group"}
                else EvidenceInputStatus.NOT_AVAILABLE_AS_OF
            )
            detail = f"{status.value}: no scoped formation row"
        else:
            missing_fields = tuple(
                field for field in spec.required_fields if field not in frame.columns
            )
            if missing_fields:
                status = EvidenceInputStatus.INVALID_SCHEMA
                detail = "invalid_schema: required fields missing"
            elif not _has_complete_row(frame, spec.required_fields):
                status = EvidenceInputStatus.NOT_AVAILABLE_AS_OF
                detail = "not_available_as_of: no row has all required values"
            else:
                status = EvidenceInputStatus.READY
                detail = "ready: fixed evidence contract satisfied"
        coverage.append(
            EvidenceInputCoverage(
                dataset=spec.dataset,
                kind=spec.kind,
                scope=spec.scope,
                status=status,
                required_fields=spec.required_fields,
                observed_rows=0 if frame is None else len(frame),
                missing_fields=missing_fields,
                detail=detail,
                source_manifest_hash=(
                    str(source_hash)
                    if isinstance(source_hash, str) and len(source_hash) == 64
                    else None
                ),
            )
        )
    return facts, features, tuple(coverage)


def _materialize_fixed_evidence(
    snapshot: Any,
    hypothesis: Any,
    facts: Mapping[str, pd.DataFrame],
    features: Mapping[str, pd.DataFrame],
    coverage: Sequence[EvidenceInputCoverage],
    route_manifests: Mapping[DiscoveryRoute, RouteScanManifest],
) -> tuple[
    tuple[EvidenceDatum, ...],
    tuple[EvidenceDatum, ...],
    dict[str, set[str]],
]:
    api: list[EvidenceDatum] = []
    local: list[EvidenceDatum] = []
    dataset_ids: dict[str, set[str]] = defaultdict(set)
    coverage_by_dataset = {item.dataset: item for item in coverage}
    for spec in _INPUT_SPECS:
        if spec.kind == "local":
            continue
        frame = (facts if spec.kind == "fact" else features).get(spec.dataset)
        if frame is None or frame.empty:
            continue
        for _, row in frame.iterrows():
            row_key, business, available = _fixed_source_row_identity(
                spec,
                row,
                hypothesis.security_id,
                snapshot.as_of,
            )
            if available > snapshot.as_of:
                raise ValueError("source row became available after formation cutoff")
            api_fields = set(spec.required_fields).union(
                _OPTIONAL_API_FIELDS.get(spec.dataset, ())
            )
            local_fields = set(_LOCAL_FACT_FIELDS.get(spec.dataset, ()))
            allowed_fields = (
                api_fields.union(local_fields)
                if spec.kind == "fact"
                else set(spec.required_fields)
            )
            for field in sorted(allowed_fields.intersection(frame.columns)):
                if _is_missing(row[field]):
                    continue
                value = _scalar(row[field])
                identity = {
                    "dataset": spec.dataset,
                    "row_key": row_key,
                    "field": field,
                    "value": value,
                    "available_at": available,
                }
                datum = EvidenceDatum(
                    evidence_id=_stable_hash(identity),
                    kind=(
                        EvidenceKind.LOCAL_OBSERVATION
                        if spec.kind == "derived" or field in local_fields
                        else EvidenceKind.API_FACT
                    ),
                    dataset=spec.dataset,
                    field=field,
                    row_key=row_key,
                    value=value,
                    business_time=business,
                    available_at=available,
                    input_hash=_stable_hash(
                        {
                            "snapshot": snapshot.cache_key,
                            "source_manifest": coverage_by_dataset[
                                spec.dataset
                            ].source_manifest_hash,
                            **identity,
                        }
                    ),
                )
                (
                    local
                    if datum.kind is EvidenceKind.LOCAL_OBSERVATION
                    else api
                ).append(datum)
                dataset_ids[spec.dataset].add(datum.evidence_id)

    for route_evidence in hypothesis.evidence:
        if not route_evidence.usable_for_decision:
            continue
        manifest = route_manifests[route_evidence.route]
        available = _as_datetime(route_evidence.available_at)
        if available is None and route_evidence.dataset in _FEATURE_NAMES:
            available = snapshot.as_of
        if available is None:
            continue
        if available > snapshot.as_of:
            raise ValueError("route evidence became available after formation cutoff")
        row_key = _stable_hash(
            (route_evidence.route.value, route_evidence.evidence_id, hypothesis.security_id)
        )
        identity = {
            "route": route_evidence.route.value,
            "source_evidence_id": route_evidence.evidence_id,
            "route_manifest_hash": manifest.input_hash,
            "snapshot_cache_key": snapshot.cache_key,
            "formula_versions": getattr(snapshot, "formula_versions", ()),
            "deep_read_input_hash": route_evidence.deep_read_input_hash,
        }
        datum = EvidenceDatum(
            evidence_id=_stable_hash(("route-observation", identity)),
            kind=EvidenceKind.LOCAL_OBSERVATION,
            dataset=route_evidence.dataset,
            field="route_trigger",
            row_key=row_key,
            value=route_evidence.route.value,
            business_time=available,
            available_at=available,
            input_hash=_stable_hash(identity),
            source_evidence_id=route_evidence.evidence_id,
        )
        local.append(datum)
        dataset_ids[f"route:{route_evidence.route.value}"].add(datum.evidence_id)
    return (
        tuple(sorted(api, key=lambda item: item.evidence_id)),
        tuple(sorted(local, key=lambda item: item.evidence_id)),
        dataset_ids,
    )


def _fixed_source_row_identity(
    spec: _InputSpec,
    row: pd.Series,
    security_id: str,
    cutoff: datetime,
) -> tuple[str, datetime, datetime]:
    available = _row_available_at(row, cutoff, spec.kind)
    business = _row_business_time(row, available)
    identity_fields = tuple(
        field
        for field in spec.required_fields
        if field in row.index and field != "available_at"
    )
    row_key = _stable_hash(
        {
            "dataset": spec.dataset,
            "business_key": {
                field: _scalar(row[field])
                for field in identity_fields
                if not _is_missing(row[field])
            },
            "security": security_id,
            "business_time": business,
        }
    )
    return row_key, business, available


def _build_local_observation_inputs(
    snapshot: Any,
    security_id: str,
    facts: Mapping[str, pd.DataFrame],
    features: Mapping[str, pd.DataFrame],
    existing_evidence: Sequence[EvidenceDatum],
    dataset_ids: dict[str, set[str]],
) -> tuple[
    dict[str, pd.DataFrame],
    tuple[EvidenceDatum, ...],
    tuple[EvidenceInputCoverage, ...],
]:
    generated_frames: dict[str, pd.DataFrame] = {}
    generated: list[EvidenceDatum] = []
    coverage: list[EvidenceInputCoverage] = []
    specs = {
        spec.dataset: spec for spec in _INPUT_SPECS if spec.kind == "local"
    }

    event_rows = _compute_event_price_responses(
        snapshot,
        security_id,
        facts,
        existing_evidence,
    )
    target_row = _compute_target_path_inputs(
        snapshot,
        security_id,
        facts,
        features,
        dataset_ids,
    )
    for dataset, rows in (
        ("event_price_response", event_rows),
        ("target_path_context", () if target_row is None else (target_row,)),
    ):
        spec = specs[dataset]
        if not rows:
            coverage.append(
                EvidenceInputCoverage(
                    dataset=dataset,
                    kind="local",
                    scope="candidate",
                    status=EvidenceInputStatus.NOT_AVAILABLE_AS_OF,
                    required_fields=spec.required_fields,
                    observed_rows=0,
                    detail=(
                        "not_available_as_of: frozen formation facts cannot yet "
                        "recompute this local observation"
                    ),
                )
            )
            continue
        frame = pd.DataFrame(list(rows))
        generated_frames[dataset] = frame
        for row in rows:
            input_hash = str(row["input_hash"])
            row_key = _stable_hash(
                {
                    "dataset": dataset,
                    "security_id": security_id,
                    "analysis_date": snapshot.analysis_date,
                    "input_hash": input_hash,
                }
            )
            business_time = snapshot.as_of
            for field in spec.required_fields:
                value = row[field]
                datum = EvidenceDatum(
                    evidence_id=_stable_hash(
                        {
                            "dataset": dataset,
                            "row_key": row_key,
                            "field": field,
                            "value": value,
                        }
                    ),
                    kind=EvidenceKind.LOCAL_OBSERVATION,
                    dataset=dataset,
                    field=field,
                    row_key=row_key,
                    value=_scalar(value),
                    business_time=business_time,
                    available_at=snapshot.as_of,
                    input_hash=input_hash,
                    source_evidence_id=(
                        str(row["source_event_evidence_id"])
                        if dataset == "event_price_response"
                        else None
                    ),
                )
                generated.append(datum)
                dataset_ids[dataset].add(datum.evidence_id)
        coverage.append(
            EvidenceInputCoverage(
                dataset=dataset,
                kind="local",
                scope="candidate",
                status=EvidenceInputStatus.READY,
                required_fields=spec.required_fields,
                observed_rows=len(rows),
                detail=(
                    "ready: frozen local formula recomputed from formation-time facts; "
                    "Task6 must judge meaning"
                ),
                source_manifest_hash=snapshot.facts.manifest["source_snapshot"].get(
                    "input_manifest_hash"
                ),
            )
        )
    return generated_frames, tuple(generated), tuple(coverage)


def _compute_event_price_response(
    snapshot: Any,
    security_id: str,
    facts: Mapping[str, pd.DataFrame],
) -> dict[str, Any] | None:
    """Compatibility probe for the deterministic formula, not packet ingestion."""

    evidence = _synthetic_event_source_evidence(snapshot, security_id, facts)
    rows = _compute_event_price_responses(
        snapshot,
        security_id,
        facts,
        evidence,
    )
    return None if not rows else rows[-1]


def _compute_event_price_responses(
    snapshot: Any,
    security_id: str,
    facts: Mapping[str, pd.DataFrame],
    existing_evidence: Sequence[EvidenceDatum],
) -> tuple[dict[str, Any], ...]:
    equity = facts.get("equity_daily")
    index = facts.get("index_daily")
    industry = facts.get("industry_daily")
    if any(frame is None or frame.empty for frame in (equity, index, industry)):
        return ()
    events: list[tuple[datetime, str, pd.Series, str, EvidenceDatum]] = []
    specs = {spec.dataset: spec for spec in _INPUT_SPECS if spec.kind == "fact"}
    by_row: dict[tuple[str, str], list[EvidenceDatum]] = defaultdict(list)
    for datum in existing_evidence:
        by_row[(datum.dataset, datum.row_key)].append(datum)
    event_datasets = (
        "announcement",
        "earnings_forecast",
        "earnings_express",
        "repurchase",
        "holder_trade",
        "share_float",
        "pledge",
    )
    for dataset in event_datasets:
        frame = facts.get(dataset)
        if frame is None:
            continue
        for _, row in frame.iterrows():
            spec = specs[dataset]
            row_key, _, _ = _fixed_source_row_identity(
                spec, row, security_id, snapshot.as_of
            )
            source_candidates = by_row.get((dataset, row_key), ())
            source_datum = _event_source_datum(dataset, source_candidates)
            if source_datum is None:
                continue
            event_time = next(
                (
                    _as_datetime(row.get(field))
                    for field in (
                        "announcement_time",
                        "available_at",
                        "ann_date",
                        "announcement_date",
                        "end_date",
                    )
                    if _as_datetime(row.get(field)) is not None
                ),
                None,
            )
            if event_time is not None and event_time <= snapshot.as_of:
                events.append((event_time, dataset, row, row_key, source_datum))
    if not events:
        return ()

    stock_prices = _dated_close_rows(equity, code_field="ts_code", code=security_id)
    market_code = _deterministic_series_code(
        index, "index_code", preferred="000300.SH"
    )
    industry_code = _deterministic_series_code(industry, "industry_code")
    if market_code is None or industry_code is None:
        return ()
    market_prices = _dated_close_rows(
        index, code_field="index_code", code=market_code
    )
    industry_prices = _dated_close_rows(
        industry, code_field="industry_code", code=industry_code
    )
    responses: list[dict[str, Any]] = []
    for event_time, event_dataset, event, source_row_key, source_datum in events:
        event_day = event_time.astimezone(_SHANGHAI).date()
        include_event_close = event_time.astimezone(_SHANGHAI).time() >= time(15)
        stock_pair = _price_pair(
            stock_prices,
            event_day,
            snapshot.analysis_date,
            include_event_day=include_event_close,
        )
        market_pair = _price_pair(
            market_prices,
            event_day,
            snapshot.analysis_date,
            include_event_day=include_event_close,
        )
        industry_pair = _price_pair(
            industry_prices,
            event_day,
            snapshot.analysis_date,
            include_event_day=include_event_close,
        )
        if stock_pair is None or market_pair is None or industry_pair is None:
            continue
        stock_return = stock_pair[3] / stock_pair[1] - Decimal("1")
        market_return = market_pair[3] / market_pair[1] - Decimal("1")
        industry_return = industry_pair[3] / industry_pair[1] - Decimal("1")
        trading_days = sum(
            stock_pair[0] < trade_date <= stock_pair[2]
            for trade_date, _ in stock_prices
        )
        report_period = _as_datetime(event.get("report_period"))
        source_report_period = (
            report_period.date().isoformat()
            if report_period is not None
            else "not_applicable"
        )
        source_record_id = _event_source_record_id(
            event_dataset, event, source_row_key
        )
        raw_deep_complete = event.get("deep_read_completed")
        deep_complete = _is_literal_python_true(raw_deep_complete)
        deep_hash = str(event.get("deep_read_input_hash", ""))
        source_deep_read_status = (
            "complete"
            if event_dataset == "announcement"
            and deep_complete
            and re.fullmatch(r"[0-9a-f]{64}", deep_hash)
            else (
                "not_complete"
                if event_dataset == "announcement"
                else "not_applicable"
            )
        )
        source_deep_read_input_hash = (
            deep_hash
            if source_deep_read_status == "complete"
            else "not_applicable"
        )
        event_identity = {
            "event_dataset": event_dataset,
            "event_time": event_time,
            "source_event_row_key": source_row_key,
            "source_event_evidence_id": source_datum.evidence_id,
            "source_record_id": source_record_id,
            "source_report_period": source_report_period,
            "source_deep_read_status": source_deep_read_status,
            "source_deep_read_input_hash": source_deep_read_input_hash,
        }
        event_record_id = _stable_hash(event_identity)
        formula_input = {
            "formula_version": "event-price-response-v2",
            "security_id": security_id,
            "event_identity": event_identity,
            "market_benchmark_code": market_code,
            "industry_code": industry_code,
            "stock_pair": stock_pair,
            "market_pair": market_pair,
            "industry_pair": industry_pair,
            "formation_date": snapshot.analysis_date,
        }
        input_hash = _stable_hash(formula_input)
        responses.append(
            {
                "analysis_date": snapshot.analysis_date,
                "ts_code": security_id,
                "event_time": event_time,
                "event_dataset": event_dataset,
                "event_record_id": event_record_id,
                "source_event_row_key": source_row_key,
                "source_event_evidence_id": source_datum.evidence_id,
                "source_record_id": source_record_id,
                "source_report_period": source_report_period,
                "source_deep_read_status": source_deep_read_status,
                "source_deep_read_input_hash": source_deep_read_input_hash,
                "market_benchmark_code": market_code,
                "industry_code": industry_code,
                "pre_event_trade_date": stock_pair[0],
                "formation_trade_date": stock_pair[2],
                "elapsed_trading_days": trading_days,
                "stock_return_to_formation": stock_return,
                "market_return_to_formation": market_return,
                "industry_return_to_formation": industry_return,
                "stock_market_relative_return": stock_return - market_return,
                "stock_industry_relative_return": stock_return - industry_return,
                "formula_version": "event-price-response-v2",
                "input_hash": input_hash,
            }
        )
    return tuple(
        sorted(
            responses,
            key=lambda row: (
                _as_datetime(row["event_time"]),
                str(row["event_dataset"]),
                str(row["source_record_id"]),
            ),
        )
    )


def _event_source_datum(
    dataset: str,
    candidates: Sequence[EvidenceDatum],
) -> EvidenceDatum | None:
    preferred = {
        "announcement": ("announcement_id",),
        "earnings_forecast": ("report_period", "ann_date"),
        "earnings_express": ("report_period", "ann_date"),
        "repurchase": ("announcement_date",),
        "holder_trade": ("ann_date",),
        "share_float": ("ann_date", "float_date"),
        "pledge": ("end_date",),
    }[dataset]
    for field in preferred:
        found = next((item for item in candidates if item.field == field), None)
        if found is not None:
            return found
    return None


def _event_source_record_id(
    dataset: str,
    row: pd.Series,
    row_key: str,
) -> str:
    if dataset == "announcement" and not _is_missing(row.get("announcement_id")):
        return str(row.get("announcement_id"))
    return _stable_hash(
        {
            "dataset": dataset,
            "row_key": row_key,
            "report_period": row.get("report_period"),
            "ann_date": row.get("ann_date"),
            "announcement_date": row.get("announcement_date"),
            "end_date": row.get("end_date"),
        }
    )


def _is_literal_python_true(value: Any) -> bool:
    """Accept only the same strict deep-read completion marker as Task 4."""

    return type(value) is bool and value is True


def _synthetic_event_source_evidence(
    snapshot: Any,
    security_id: str,
    facts: Mapping[str, pd.DataFrame],
) -> tuple[EvidenceDatum, ...]:
    """Test-only formula adapter; public packets never use synthetic evidence."""

    specs = {spec.dataset: spec for spec in _INPUT_SPECS if spec.kind == "fact"}
    values: list[EvidenceDatum] = []
    for dataset in (
        "announcement",
        "earnings_forecast",
        "earnings_express",
        "repurchase",
        "holder_trade",
        "share_float",
        "pledge",
    ):
        frame = facts.get(dataset)
        if frame is None:
            continue
        for _, row in frame.iterrows():
            row_key, business, available = _fixed_source_row_identity(
                specs[dataset], row, security_id, snapshot.as_of
            )
            field = {
                "announcement": "announcement_id",
                "earnings_forecast": "report_period",
                "earnings_express": "report_period",
                "repurchase": "announcement_date",
                "holder_trade": "ann_date",
                "share_float": "ann_date",
                "pledge": "end_date",
            }[dataset]
            if field not in row or _is_missing(row[field]):
                continue
            values.append(
                EvidenceDatum(
                    evidence_id=_stable_hash(("synthetic-formula-source", dataset, row_key)),
                    kind=EvidenceKind.API_FACT,
                    dataset=dataset,
                    field=field,
                    row_key=row_key,
                    value=_scalar(row[field]),
                    business_time=business,
                    available_at=available,
                    input_hash=_stable_hash(("synthetic-formula-input", dataset, row_key)),
                )
            )
    return tuple(values)


def _compute_target_path_inputs(
    snapshot: Any,
    security_id: str,
    facts: Mapping[str, pd.DataFrame],
    features: Mapping[str, pd.DataFrame],
    dataset_ids: Mapping[str, set[str]],
) -> dict[str, Any] | None:
    equity = facts.get("equity_daily")
    stock_context = features.get("stock_trading_context")
    if equity is None or equity.empty or stock_context is None or stock_context.empty:
        return None
    prices = _dated_close_rows(equity, code_field="ts_code", code=security_id)
    if not prices:
        return None
    formation_rows = [item for item in prices if item[0] <= snapshot.analysis_date]
    if not formation_rows:
        return None
    formation_date, close = formation_rows[-1]
    context = stock_context.iloc[-1]
    metric_fields = (
        "return_20d",
        "relative_return_20d",
        "realized_volatility_20d_annualized",
        "atr_ratio_20d",
        "price_location_60d",
    )
    metrics = {field: _decimal_value(context.get(field)) for field in metric_fields}
    if any(value is None for value in metrics.values()):
        return None
    driver_datasets = {
        "sector_hotspot",
        "company_profile",
        "main_business",
        "earnings_forecast",
        "earnings_express",
        "income_statement",
        "announcement",
    }
    counter_datasets = {
        "sector_hotspot",
        "balance_sheet",
        "cash_flow",
        "repurchase",
        "holder_trade",
        "share_float",
        "pledge",
        "stock_trading_context",
    }
    driver_ids = tuple(
        sorted(
            evidence_id
            for dataset in driver_datasets
            for evidence_id in dataset_ids.get(dataset, ())
        )
    )
    counter_ids = tuple(
        sorted(
            evidence_id
            for dataset in counter_datasets
            for evidence_id in dataset_ids.get(dataset, ())
        )
    )
    target_return = Decimal("0.20")
    target_price = close * (Decimal("1") + target_return)
    formula_input = {
        "formula_version": "target-path-inputs-v2",
        "security_id": security_id,
        "formation_date": formation_date,
        "close": close,
        "metrics": metrics,
        "driver_ids": driver_ids,
        "counter_ids": counter_ids,
    }
    return {
        "analysis_date": snapshot.analysis_date,
        "ts_code": security_id,
        "current_baseline": close,
        "target_return": target_return,
        "target_price": target_price,
        "horizon_days_10": 10,
        "horizon_days_20": 20,
        "horizon_days_30": 30,
        "recent_return_20d": metrics["return_20d"],
        "relative_return_20d": metrics["relative_return_20d"],
        "realized_volatility_20d_annualized": metrics[
            "realized_volatility_20d_annualized"
        ],
        "atr_ratio_20d": metrics["atr_ratio_20d"],
        "price_location_60d": metrics["price_location_60d"],
        "candidate_driver_evidence_ids": driver_ids,
        "counterevidence_input_ids": counter_ids,
        "formula_version": "target-path-inputs-v2",
        "input_hash": _stable_hash(formula_input),
    }


def _dated_close_rows(
    frame: pd.DataFrame,
    *,
    code_field: str,
    code: str | None,
) -> tuple[tuple[date, Decimal], ...]:
    selected = frame
    if code is not None:
        if code_field not in frame:
            return ()
        selected = frame[frame[code_field].astype(str) == code]
    elif code_field in frame and not frame.empty:
        first_code = sorted(frame[code_field].dropna().astype(str).unique())[0]
        selected = frame[frame[code_field].astype(str) == first_code]
    rows: dict[date, Decimal] = {}
    for _, row in selected.iterrows():
        trade_time = _as_datetime(row.get("trade_date"))
        close = _decimal_value(row.get("close"))
        if trade_time is not None and close is not None and close > 0:
            rows[trade_time.date()] = close
    return tuple(sorted(rows.items()))


def _price_pair(
    prices: Sequence[tuple[date, Decimal]],
    event_day: date,
    formation_date: date,
    *,
    include_event_day: bool = False,
) -> tuple[date, Decimal, date, Decimal] | None:
    before = [
        item
        for item in prices
        if (
            item[0] <= event_day
            if include_event_day
            else item[0] < event_day
        )
    ]
    through_formation = [item for item in prices if item[0] <= formation_date]
    if not before or not through_formation:
        return None
    return (*before[-1], *through_formation[-1])


def _deterministic_series_code(
    frame: pd.DataFrame,
    field: str,
    *,
    preferred: str | None = None,
) -> str | None:
    if field not in frame or frame.empty:
        return None
    codes = tuple(sorted(frame[field].dropna().astype(str).unique()))
    if not codes:
        return None
    return preferred if preferred in codes else codes[0]


def _build_opportunity_cards(
    coverage: Sequence[EvidenceInputCoverage],
    facts: Mapping[str, pd.DataFrame],
    features: Mapping[str, pd.DataFrame],
    dataset_ids: Mapping[str, set[str]],
    cutoff: datetime,
    security_id: str,
) -> tuple[OpportunityEvidenceCard, ...]:
    ready = {
        item.dataset
        for item in coverage
        if item.status is EvidenceInputStatus.READY
    }
    definitions: dict[
        BacktestOpportunityType,
        tuple[tuple[str, ...], tuple[str, ...]],
    ] = {
        BacktestOpportunityType.INDUSTRY_TREND: (
            (
                "complete related hotspot input",
                "effective company membership",
                "business contribution numerator and company denominator inputs",
                "two formation-time industry demand or adoption input periods",
            ),
            ("sector_hotspot", "industry_member|theme_member", "business_contribution_inputs", "industry_trend_inputs"),
        ),
        BacktestOpportunityType.EARNINGS_REVALUATION: (
            (
                "formal disclosure hierarchy",
                "aligned profit inputs",
                "aligned cash inputs",
                "own-history and peer valuation inputs",
                "event-aligned relative price response",
            ),
            ("earnings_disclosure", "income_statement", "cash_flow", "daily_basic", "earnings_event_response"),
        ),
        BacktestOpportunityType.SUPPLY_DEMAND_CYCLE: (
            (
                "two-period industry supply demand price and inventory inputs",
                "company sensitivity inputs",
                "two-period profit inputs",
                "two-period cash inputs",
            ),
            ("cycle_inputs", "business_contribution_inputs", "income_two_periods", "cash_two_periods"),
        ),
        BacktestOpportunityType.COMPANY_EVENT_REVALUATION: (
            (
                "auditable event body amount subject stage conditions and failure inputs",
                "business transmission inputs",
                "event-aligned relative price response",
            ),
            ("deep_event", "company_profile|main_business", "company_event_response"),
        ),
        BacktestOpportunityType.DISTRESS_REVERSAL: (
            (
                "raw distress and financing-risk inputs",
                "two aligned multi-statement periods",
                "own-history and peer valuation inputs",
                "event-aligned relative price response input",
            ),
            ("distress_risk_inputs", "distress_financial_inputs", "daily_basic", "distress_event_response"),
        ),
    }
    requirement_datasets: dict[str, tuple[str, ...]] = {
        "sector_hotspot": ("sector_hotspot",),
        "industry_member|theme_member": ("industry_member", "theme_member"),
        "business_contribution_inputs": ("main_business", "income_statement"),
        "industry_trend_inputs": ("industry_daily",),
        "earnings_disclosure": (
            "earnings_forecast",
            "earnings_express",
            "income_statement",
        ),
        "income_statement": ("income_statement",),
        "cash_flow": ("income_statement", "cash_flow"),
        "daily_basic": ("daily_basic",),
        "earnings_event_response": (
            "earnings_forecast",
            "earnings_express",
            "event_price_response",
        ),
        "cycle_inputs": ("industry_daily",),
        "income_two_periods": ("income_statement",),
        "cash_two_periods": ("cash_flow",),
        "deep_event": ("announcement",),
        "company_profile|main_business": ("company_profile", "main_business"),
        "company_event_response": ("announcement", "event_price_response"),
        "distress_risk_inputs": (
            "security_master",
            "repurchase",
            "holder_trade",
            "share_float",
            "pledge",
        ),
        "distress_financial_inputs": (
            "income_statement",
            "balance_sheet",
            "cash_flow",
            "financial_indicator",
        ),
        "distress_event_response": (
            "repurchase",
            "holder_trade",
            "share_float",
            "pledge",
            "event_price_response",
        ),
    }
    aligned_distress_source_ids = _aligned_distress_source_evidence_ids(
        facts,
        features.get("event_price_response"),
        cutoff,
        security_id,
    )
    checks = {
        "sector_hotspot": "sector_hotspot" in ready,
        "industry_member|theme_member": bool({"industry_member", "theme_member"} & ready),
        "business_contribution_inputs": _has_business_contribution_inputs(facts),
        "industry_trend_inputs": _has_optional_measure_periods(
            facts.get("industry_daily"),
            ("demand_change", "shipment_change", "adoption_change"),
            minimum_periods=2,
        ),
        "earnings_disclosure": bool(
            {"earnings_forecast", "earnings_express", "income_statement"} & ready
        ),
        "income_statement": "income_statement" in ready
        and _has_aligned_report_periods(facts, ("income_statement",), 1),
        "cash_flow": "cash_flow" in ready
        and _has_aligned_report_periods(facts, ("income_statement", "cash_flow"), 1),
        "daily_basic": "daily_basic" in ready
        and _has_valuation_context_inputs(
            facts.get("daily_basic"), security_id
        ),
        "event_price_response": "event_price_response" in ready
        and _has_valid_event_response(features.get("event_price_response"), cutoff),
        "earnings_event_response": "event_price_response" in ready
        and _has_aligned_earnings_event_inputs(
            facts,
            features.get("event_price_response"),
            cutoff,
            security_id,
        ),
        "company_event_response": "event_price_response" in ready
        and _has_aligned_company_event_inputs(
            facts.get("announcement"),
            features.get("event_price_response"),
            cutoff,
            security_id,
        ),
        "distress_event_response": "event_price_response" in ready
        and bool(aligned_distress_source_ids),
        "cycle_inputs": _has_complete_periods(
            facts.get("industry_daily"),
            ("demand_change", "supply_change", "price_change", "inventory_change"),
            minimum_periods=2,
        ),
        "income_two_periods": _has_complete_periods(
            facts.get("income_statement"),
            ("revenue", "n_income_attr_p"),
            minimum_periods=2,
        ) and _has_aligned_report_periods(
            facts, ("income_statement", "cash_flow"), 2
        ),
        "cash_two_periods": _has_complete_periods(
            facts.get("cash_flow"),
            ("n_cashflow_act",),
            minimum_periods=2,
        ) and _has_aligned_report_periods(
            facts, ("income_statement", "cash_flow"), 2
        ),
        "deep_event": _has_strict_deep_event_inputs(
            facts.get("announcement")
        ),
        "company_profile|main_business": bool(
            {"company_profile", "main_business"} & ready
        ),
        "distress_risk_inputs": "security_master" in ready and bool(
            {"holder_trade", "share_float", "pledge", "repurchase"} & ready
        ),
        "distress_financial_inputs": all(
            dataset in ready
            for dataset in (
                "income_statement",
                "balance_sheet",
                "cash_flow",
                "financial_indicator",
            )
        ) and all(
            (
                _has_complete_periods(
                    facts.get("income_statement"),
                    ("revenue", "n_income_attr_p"),
                    minimum_periods=2,
                ),
                _has_complete_periods(
                    facts.get("balance_sheet"),
                    (
                        "total_assets",
                        "total_liab",
                        "money_cap",
                        "st_borr",
                        "non_cur_liab_due_1y",
                    ),
                    minimum_periods=2,
                ),
                _has_complete_periods(
                    facts.get("cash_flow"),
                    ("n_cashflow_act",),
                    minimum_periods=2,
                ),
                _has_complete_periods(
                    facts.get("financial_indicator"),
                    ("roe",),
                    minimum_periods=2,
                ),
            )
        ) and _has_aligned_report_periods(
            facts,
            (
                "income_statement",
                "balance_sheet",
                "cash_flow",
                "financial_indicator",
            ),
            2,
        ),
    }
    cards: list[OpportunityEvidenceCard] = []
    for opportunity in BacktestOpportunityType:
        requirements, keys = definitions[opportunity]
        missing = tuple(
            requirement
            for requirement, key in zip(requirements, keys, strict=True)
            if not checks.get(key, False)
        )
        if missing:
            cards.append(
                OpportunityEvidenceCard(
                    opportunity=opportunity,
                    status=EvidenceCardStatus.INCOMPLETE,
                    required_requirements=requirements,
                    missing_requirements=missing,
                )
            )
            continue
        requirement_bindings: list[tuple[str, tuple[str, ...]]] = []
        for requirement, key in zip(requirements, keys, strict=True):
            ids_for_requirement = {
                evidence_id
                for dataset in requirement_datasets[key]
                for evidence_id in dataset_ids.get(dataset, ())
            }
            if key == "distress_event_response":
                raw_risk_ids = {
                    evidence_id
                    for dataset in (
                        "repurchase",
                        "holder_trade",
                        "share_float",
                        "pledge",
                    )
                    for evidence_id in dataset_ids.get(dataset, ())
                }
                aligned_ids = set(aligned_distress_source_ids)
                if not aligned_ids.issubset(raw_risk_ids):
                    ids_for_requirement.clear()
                else:
                    ids_for_requirement.update(aligned_ids)
            requirement_bindings.append(
                (requirement, tuple(sorted(ids_for_requirement)))
            )
        missing_bindings = tuple(
            requirement
            for requirement, evidence_ids in requirement_bindings
            if not evidence_ids
        )
        if missing_bindings:
            cards.append(
                OpportunityEvidenceCard(
                    opportunity=opportunity,
                    status=EvidenceCardStatus.INCOMPLETE,
                    required_requirements=requirements,
                    missing_requirements=missing_bindings,
                )
            )
            continue
        ids = {
            evidence_id
            for _, evidence_ids in requirement_bindings
            for evidence_id in evidence_ids
        }
        cards.append(
            OpportunityEvidenceCard(
                opportunity=opportunity,
                status=EvidenceCardStatus.EVIDENCE_READY_FOR_JUDGMENT,
                required_requirements=requirements,
                evidence_ids=tuple(sorted(ids)),
                requirement_evidence_ids=tuple(requirement_bindings),
            )
        )
    return tuple(cards)


def _build_sections(
    coverage: Sequence[EvidenceInputCoverage],
    cards: Sequence[OpportunityEvidenceCard],
    dataset_ids: Mapping[str, set[str]],
    facts: Mapping[str, pd.DataFrame],
    features: Mapping[str, pd.DataFrame],
    cutoff: datetime,
    security_id: str,
) -> tuple[tuple[EvidenceSection, ...], dict[EvidenceSectionName, set[str]], tuple[str, ...]]:
    spec_by_dataset = {spec.dataset: spec for spec in _INPUT_SPECS}
    coverage_by_dataset = {item.dataset: item for item in coverage}
    ready = {
        item.dataset
        for item in coverage
        if item.status is EvidenceInputStatus.READY
    }
    input_ready = {
        EvidenceSectionName.MARKET_CONSTRAINTS: all(
            dataset in ready
            for dataset in ("market_context", "security_master", "stock_limit", "suspension")
        ),
        EvidenceSectionName.HOTSPOT_PANORAMA: "sector_hotspot" in ready
        and bool({"industry_member", "theme_member"} & ready),
        EvidenceSectionName.BUSINESS_TRANSMISSION: _has_business_contribution_inputs(
            facts
        ),
        EvidenceSectionName.FINANCIAL_QUALITY: bool(
            {"earnings_forecast", "earnings_express", "income_statement"} & ready
        )
        and "cash_flow" in ready
        and _has_aligned_report_periods(
            facts, ("income_statement", "cash_flow"), 1
        ),
        EvidenceSectionName.VALUATION_CONTEXT: all(
            dataset in ready for dataset in ("daily_basic", "industry_member", "financial_indicator")
        ) and _has_valuation_context_inputs(
            facts.get("daily_basic"), security_id
        ),
        EvidenceSectionName.COMPANY_EVENTS: "announcement" in ready
        and _has_complete_row(
            facts.get("announcement"),
            (
                "body",
                "amount",
                "subject",
                "execution_conditions",
                "event_stage",
                "failure_conditions",
            ),
        ),
        EvidenceSectionName.PRICE_VOLUME_LIQUIDITY: all(
            dataset in ready
            for dataset in ("stock_trading_context", "equity_daily", "stock_limit", "suspension")
        ),
        EvidenceSectionName.POST_FACT_PRICE_RESPONSE: "event_price_response" in ready
        and _has_valid_event_response(features.get("event_price_response"), cutoff),
        EvidenceSectionName.CURRENT_PRICE_TO_TARGET_CONDITIONS: "target_path_context" in ready
        and _has_valid_target_path(features.get("target_path_context")),
        EvidenceSectionName.COUNTEREVIDENCE: bool(
            {
                "sector_hotspot",
                "balance_sheet",
                "cash_flow",
                "repurchase",
                "holder_trade",
                "share_float",
                "pledge",
            }
            & ready
        ),
    }
    section_ids: dict[EvidenceSectionName, set[str]] = defaultdict(set)
    for dataset, ids in dataset_ids.items():
        spec = spec_by_dataset.get(dataset)
        if spec is None or coverage_by_dataset[dataset].status is not EvidenceInputStatus.READY:
            continue
        for section in spec.sections:
            if input_ready.get(section, False):
                section_ids[section].update(ids)

    card_section = {
        BacktestOpportunityType.INDUSTRY_TREND: EvidenceSectionName.INDUSTRY_TREND_EVIDENCE,
        BacktestOpportunityType.EARNINGS_REVALUATION: EvidenceSectionName.EARNINGS_REVALUATION_EVIDENCE,
        BacktestOpportunityType.SUPPLY_DEMAND_CYCLE: EvidenceSectionName.SUPPLY_DEMAND_CYCLE_EVIDENCE,
        BacktestOpportunityType.COMPANY_EVENT_REVALUATION: EvidenceSectionName.COMPANY_EVENT_REVALUATION_EVIDENCE,
        BacktestOpportunityType.DISTRESS_REVERSAL: EvidenceSectionName.DISTRESS_REVERSAL_EVIDENCE,
    }
    for card in cards:
        if card.status is EvidenceCardStatus.EVIDENCE_READY_FOR_JUDGMENT:
            section_ids[card_section[card.opportunity]].update(card.evidence_ids)

    sections: list[EvidenceSection] = []
    missing: list[str] = []
    for name in EvidenceSectionName:
        ids = tuple(sorted(section_ids.get(name, ())))
        if ids and name not in {
            EvidenceSectionName.UNKNOWNS,
            EvidenceSectionName.NEXT_VALIDATION_FACT,
        }:
            sections.append(
                EvidenceSection(
                    name=name,
                    availability=EvidenceAvailability.EVIDENCE_READY_FOR_JUDGMENT,
                    evidence_ids=ids,
                    note=(
                        "formation inputs are ready for Task6 judgment; this does not "
                        "assert direction, opportunity, driver, risk, or valuation conclusion"
                    ),
                )
            )
            continue
        related = [
            item
            for item in coverage
            if name in spec_by_dataset[item.dataset].sections
            and item.status is not EvidenceInputStatus.READY
        ]
        if related:
            reason = "; ".join(
                f"{item.dataset}={item.status.value}" for item in related
            )
        elif name in card_section.values():
            card = next(
                card
                for card in cards
                if card_section[card.opportunity] is name
            )
            reason = "incomplete: " + "; ".join(card.missing_requirements)
        elif name in input_ready and not input_ready[name]:
            reason = "incomplete: dedicated section inputs are not jointly sufficient"
        else:
            reason = "not_available_as_of: no dedicated input observation"
        note = f"{reason}; section remains unavailable"
        sections.append(
            EvidenceSection(
                name=name,
                availability=EvidenceAvailability.NOT_AVAILABLE_AS_OF,
                note=note,
            )
        )
        missing.append(f"{name.value}: {reason}")
    return tuple(sections), section_ids, tuple(missing)


def _candidate_capabilities(
    snapshot: Any,
    facts: Mapping[str, pd.DataFrame],
    features: Mapping[str, pd.DataFrame],
    coverage: Sequence[EvidenceInputCoverage],
) -> CapabilitySnapshot:
    ready = {
        item.dataset
        for item in coverage
        if item.status is EvidenceInputStatus.READY
    }
    versions = dict(getattr(snapshot, "formula_versions", ()))
    items: list[CapabilityItem] = []
    for kind, frames in (("fact", facts), ("derived", features)):
        for name, frame in frames.items():
            if name in {"event_price_response", "target_path_context"}:
                continue
            fields = tuple(
                sorted(column for column in frame.columns if not frame[column].isna().all())
            )
            structurally_ready = name in ready
            items.append(
                CapabilityItem(
                    kind=kind,
                    name=name,
                    fields=fields,
                    partition_count=1,
                    row_count=len(frame),
                    formula_versions=(versions.get(name, "formation-snapshot"),)
                    if kind == "derived"
                    else (),
                    quality_statuses=("complete",) if structurally_ready else (),
                    as_of_supported=structurally_ready,
                    structurally_ready=structurally_ready,
                )
            )
    return CapabilitySnapshot(
        analysis_date=snapshot.analysis_date,
        items=tuple(sorted(items, key=lambda item: (item.kind, item.name))),
        snapshot_hash=_stable_hash(
            [item.model_dump(mode="json") for item in items]
        ),
    )


def _select_for_fixed_needs(
    registry: KnowledgeRegistry,
    capabilities: CapabilitySnapshot,
    analysis_date: date,
    opportunity: OpportunityType,
    routes: Sequence[DiscoveryRoute],
) -> dict[str, tuple[KnowledgeSelection, ...]]:
    allowed_sections = {
        EvidenceSectionName.MARKET_CONSTRAINTS,
        EvidenceSectionName.PRICE_VOLUME_LIQUIDITY,
        EvidenceSectionName.COUNTEREVIDENCE,
        EvidenceSectionName.CURRENT_PRICE_TO_TARGET_CONDITIONS,
    }
    if DiscoveryRoute.HOTSPOT in routes:
        allowed_sections.update(
            (EvidenceSectionName.HOTSPOT_PANORAMA, EvidenceSectionName.BUSINESS_TRANSMISSION)
        )
    if DiscoveryRoute.EARNINGS in routes:
        allowed_sections.update(
            (EvidenceSectionName.FINANCIAL_QUALITY, EvidenceSectionName.VALUATION_CONTEXT, EvidenceSectionName.COMPANY_EVENTS)
        )
    if DiscoveryRoute.COMPANY_EVENT in routes:
        allowed_sections.update(
            (EvidenceSectionName.COMPANY_EVENTS, EvidenceSectionName.BUSINESS_TRANSMISSION, EvidenceSectionName.FINANCIAL_QUALITY, EvidenceSectionName.VALUATION_CONTEXT)
        )
    if DiscoveryRoute.INDUSTRY_CYCLE in routes or DiscoveryRoute.DISTRESS_REPAIR in routes:
        allowed_sections.update(
            (EvidenceSectionName.HOTSPOT_PANORAMA, EvidenceSectionName.BUSINESS_TRANSMISSION, EvidenceSectionName.FINANCIAL_QUALITY, EvidenceSectionName.VALUATION_CONTEXT)
        )
    selected: dict[str, list[KnowledgeSelection]] = defaultdict(list)
    for section, module, topics in _FIXED_ANALYSIS_NEEDS:
        if section not in allowed_sections:
            continue
        context = AnalysisContext(
            analysis_date=analysis_date,
            module=module,
            opportunity_type=opportunity,
            required_topics=topics,
            question=f"prepare governed evidence for {section.value}",
        )
        for value in select_knowledge(registry, context, capabilities):
            selected[value.knowledge_id].append(value)
    return {
        knowledge_id: tuple(values)
        for knowledge_id, values in sorted(selected.items())
    }


def _knowledge_routing(
    entries: Sequence[Any],
    selected: Mapping[str, tuple[KnowledgeSelection, ...]],
    candidate_gaps: Mapping[str, tuple[str, ...]],
    capabilities: CapabilitySnapshot,
    analysis_date: date,
    opportunity: OpportunityType,
    evidence: Sequence[EvidenceDatum],
    section_ids: Mapping[EvidenceSectionName, set[str]],
) -> tuple[KnowledgeRoutingRecord, ...]:
    by_dataset_row: dict[tuple[str, str], dict[str, str]] = defaultdict(dict)
    for datum in evidence:
        by_dataset_row[(datum.dataset, datum.row_key)][datum.field] = datum.evidence_id
    records: list[KnowledgeRoutingRecord] = []
    for entry in sorted(entries, key=lambda value: value.knowledge_id):
        selections = selected.get(entry.knowledge_id)
        purpose = _knowledge_purpose(entry, section_ids)
        refs = _knowledge_evidence_refs(entry, by_dataset_row)
        if selections and purpose is not None and refs and not candidate_gaps[entry.knowledge_id]:
            records.append(
                KnowledgeRoutingRecord(
                    knowledge_id=entry.knowledge_id,
                    status=KnowledgeRoutingStatus.PREPARED_FOR_JUDGMENT,
                    reason="knowledge requirement satisfied and prepared for a fixed judgment question",
                    use_purpose=f"prepare {purpose.value} formation evidence",
                    claim_summary_hash=_stable_hash(entry.claim_summary),
                    allowed_use_hash=_stable_hash(entry.allowed_uses[0]),
                    effect=entry.effect,
                    selection_reasons=tuple(
                        dict.fromkeys(
                            reason
                            for selection in selections
                            for reason in selection.selection_reasons
                        )
                    ),
                    evidence_ids=refs,
                )
            )
            continue
        records.append(
            KnowledgeRoutingRecord(
                knowledge_id=entry.knowledge_id,
                status=KnowledgeRoutingStatus.NOT_APPLICABLE,
                reason=_not_applicable_reason(
                    entry,
                    analysis_date,
                    opportunity,
                    capabilities,
                    candidate_gaps[entry.knowledge_id],
                    selections is not None,
                    purpose,
                    bool(refs),
                ),
            )
        )
    return tuple(records)


def _knowledge_purpose(
    entry: Any,
    section_ids: Mapping[EvidenceSectionName, set[str]],
) -> EvidenceSectionName | None:
    for section, module, topics in _FIXED_ANALYSIS_NEEDS:
        if (
            section_ids.get(section)
            and module in entry.modules
            and set(topics).intersection(entry.topics)
        ):
            return section
    return None


def _knowledge_evidence_refs(
    entry: Any,
    rows: Mapping[tuple[str, str], Mapping[str, str]],
) -> tuple[str, ...]:
    refs: set[str] = set()
    for requirement in entry.data_requirements:
        matching_rows = [
            values
            for (dataset, _), values in rows.items()
            if dataset == requirement.name
            and set(requirement.required_fields).issubset(values)
        ]
        if len(matching_rows) < requirement.minimum_rows:
            return ()
        for values in matching_rows[: requirement.minimum_rows]:
            refs.update(values[field] for field in requirement.required_fields)
    return tuple(sorted(refs))


def _not_applicable_reason(
    entry: Any,
    analysis_date: date,
    opportunity: OpportunityType,
    capabilities: CapabilitySnapshot,
    candidate_gaps: tuple[str, ...],
    selected: bool,
    purpose: EvidenceSectionName | None,
    has_refs: bool,
) -> str:
    if entry.effective_from is not None and analysis_date < entry.effective_from:
        return f"not_effective_as_of: effective from {entry.effective_from.isoformat()}"
    if entry.effective_to is not None and analysis_date > entry.effective_to:
        return f"not_effective_as_of: expired on {entry.effective_to.isoformat()}"
    if not (
        OpportunityType.GENERAL in entry.opportunity_types
        or opportunity in entry.opportunity_types
    ):
        return "opportunity_not_applicable: governed candidate contexts do not match"
    if candidate_gaps:
        return "not_available_as_of: " + ", ".join(candidate_gaps)
    assessment = assess_entry_capability(entry, capabilities)
    if assessment.status is not CapabilityStatus.COMPLETE:
        return "not_available_as_of: " + ", ".join(assessment.missing_requirements)
    if not selected:
        return "scene_not_applicable: fixed framework question did not select this entry"
    if purpose is None:
        return "not_available_as_of: no complete packet section can use this knowledge"
    if not has_refs:
        return "not_available_as_of: required evidence is not present in the same scoped rows"
    return "scene_not_applicable: knowledge did not alter packet preparation"


def _candidate_requirement_gaps(
    entry: Any,
    facts: Mapping[str, pd.DataFrame],
    features: Mapping[str, pd.DataFrame],
) -> tuple[str, ...]:
    gaps: list[str] = []
    for requirement in entry.data_requirements:
        frame = (facts if requirement.kind == "fact" else features).get(requirement.name)
        if frame is None or frame.empty:
            gaps.append(f"{requirement.kind}:{requirement.name}")
            continue
        absent = tuple(
            field for field in requirement.required_fields if field not in frame.columns
        )
        if absent:
            gaps.extend(
                f"{requirement.kind}:{requirement.name}.{field}" for field in absent
            )
            continue
        if not _has_complete_row(frame, requirement.required_fields, requirement.minimum_rows):
            gaps.append(
                f"{requirement.kind}:{requirement.name} has no row with all required fields"
            )
    return tuple(gaps)


def _governed_opportunity(
    value: BacktestOpportunityType | None,
) -> OpportunityType:
    return {
        None: OpportunityType.GENERAL,
        BacktestOpportunityType.INDUSTRY_TREND: OpportunityType.INDUSTRY_TREND,
        BacktestOpportunityType.EARNINGS_REVALUATION: OpportunityType.EARNINGS_RERATING,
        BacktestOpportunityType.SUPPLY_DEMAND_CYCLE: OpportunityType.CYCLE_INFLECTION,
        BacktestOpportunityType.COMPANY_EVENT_REVALUATION: OpportunityType.COMPANY_EVENT,
        BacktestOpportunityType.DISTRESS_REVERSAL: OpportunityType.TURNAROUND,
    }[value]


def _governed_opportunities(
    value: BacktestOpportunityType | None,
    routes: Sequence[DiscoveryRoute],
) -> tuple[OpportunityType, ...]:
    values: list[OpportunityType] = [OpportunityType.GENERAL]
    if value is not None:
        values.append(_governed_opportunity(value))
    route_map = {
        DiscoveryRoute.HOTSPOT: OpportunityType.INDUSTRY_TREND,
        DiscoveryRoute.EARNINGS: OpportunityType.EARNINGS_RERATING,
        DiscoveryRoute.COMPANY_EVENT: OpportunityType.COMPANY_EVENT,
        DiscoveryRoute.INDUSTRY_CYCLE: OpportunityType.CYCLE_INFLECTION,
        DiscoveryRoute.DISTRESS_REPAIR: OpportunityType.TURNAROUND,
    }
    values.extend(route_map[route] for route in routes if route in route_map)
    return tuple(dict.fromkeys(values))


def _filter_candidate(
    frame: pd.DataFrame, security_id: str, dataset: str
) -> pd.DataFrame:
    if _SECURITY_FIELD not in frame.columns:
        if frame.empty:
            return frame.copy(deep=True)
        raise ValueError(f"candidate dataset {dataset} lacks a governed security key")
    return frame[frame[_SECURITY_FIELD].astype(str) == security_id].copy()


def _validate_effective_membership(
    frame: pd.DataFrame, formation_date: date, dataset: str
) -> None:
    for _, row in frame.iterrows():
        valid_from = _as_datetime(row.get("valid_from"))
        valid_to = _as_datetime(row.get("valid_to"))
        if valid_from is None or valid_from.date() > formation_date:
            raise ValueError(f"{dataset} contains membership not effective at formation")
        if valid_to is not None and valid_to.date() < formation_date:
            raise ValueError(f"{dataset} contains expired membership at formation")


def _has_complete_row(
    frame: pd.DataFrame | None,
    fields: Sequence[str],
    minimum_rows: int = 1,
) -> bool:
    if frame is None or frame.empty or not set(fields).issubset(frame.columns):
        return False
    return int(frame.loc[:, list(fields)].notna().all(axis=1).sum()) >= minimum_rows


def _decimal_value(value: Any) -> Decimal | None:
    if _is_missing(value) or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except Exception:
        return None
    return result if result.is_finite() else None


def _has_complete_periods(
    frame: pd.DataFrame | None,
    fields: Sequence[str],
    *,
    minimum_periods: int,
) -> bool:
    if frame is None or frame.empty:
        return False
    period_field = "report_period" if "report_period" in frame else "trade_date"
    required = (period_field, *fields)
    if not set(required).issubset(frame.columns):
        return False
    complete = frame.loc[:, list(required)].dropna()
    return complete[period_field].astype(str).nunique() >= minimum_periods


def _has_optional_measure_periods(
    frame: pd.DataFrame | None,
    fields: Sequence[str],
    *,
    minimum_periods: int,
) -> bool:
    if frame is None or frame.empty or "trade_date" not in frame:
        return False
    available_fields = [field for field in fields if field in frame]
    if not available_fields:
        return False
    mask = frame[available_fields].notna().any(axis=1)
    return frame.loc[mask, "trade_date"].astype(str).nunique() >= minimum_periods


def _has_aligned_report_periods(
    facts: Mapping[str, pd.DataFrame],
    datasets: Sequence[str],
    minimum_periods: int,
) -> bool:
    period_sets: list[set[str]] = []
    for dataset in datasets:
        frame = facts.get(dataset)
        if frame is None or frame.empty or "report_period" not in frame:
            return False
        period_sets.append(set(frame["report_period"].dropna().astype(str)))
    return bool(period_sets) and len(set.intersection(*period_sets)) >= minimum_periods


def _has_business_contribution_inputs(
    facts: Mapping[str, pd.DataFrame],
) -> bool:
    business = facts.get("main_business")
    income = facts.get("income_statement")
    if not _has_complete_row(
        business,
        ("report_period", "item_name", "bz_sales", "bz_profit"),
    ) or not _has_complete_row(income, ("report_period", "revenue")):
        return False
    return _has_aligned_report_periods(
        facts, ("main_business", "income_statement"), 1
    )


def _has_valuation_context_inputs(
    frame: pd.DataFrame | None,
    security_id: str,
) -> bool:
    if frame is None or frame.empty or "ts_code" not in frame:
        return False
    required = ("trade_date", "pe_ttm", "pb", "ps_ttm", "total_mv")
    if not set(required).issubset(frame.columns):
        return False
    complete = frame.dropna(subset=list(required))
    codes = complete["ts_code"].astype(str)
    candidate = complete[codes == security_id]
    if candidate["trade_date"].astype(str).nunique() < 2:
        return False
    candidate_latest = max(candidate["trade_date"].astype(str))
    peers_same_day = complete[
        (codes != security_id)
        & complete["trade_date"].astype(str).eq(candidate_latest)
    ]
    return not peers_same_day.empty


def _has_valid_event_response(
    frame: pd.DataFrame | None,
    cutoff: datetime,
    *,
    allowed_datasets: Sequence[str] | None = None,
) -> bool:
    if frame is None or frame.empty:
        return False
    for _, row in frame.iterrows():
        event_time = _as_datetime(row.get("event_time"))
        input_hash = str(row.get("input_hash", ""))
        returns = tuple(
            _decimal_value(row.get(field))
            for field in (
                "stock_return_to_formation",
                "market_return_to_formation",
                "industry_return_to_formation",
                "stock_market_relative_return",
                "stock_industry_relative_return",
            )
        )
        if (
            event_time is not None
            and event_time <= cutoff
            and bool(str(row.get("event_dataset", "")))
            and (
                allowed_datasets is None
                or str(row.get("event_dataset")) in allowed_datasets
            )
            and re.fullmatch(r"[0-9a-f]{64}", str(row.get("event_record_id", "")))
            and re.fullmatch(
                r"[0-9a-f]{64}", str(row.get("source_event_row_key", ""))
            )
            and re.fullmatch(
                r"[0-9a-f]{64}", str(row.get("source_event_evidence_id", ""))
            )
            and bool(str(row.get("source_record_id", "")))
            and bool(str(row.get("source_report_period", "")))
            and str(row.get("source_deep_read_status", ""))
            in {"complete", "not_complete", "not_applicable"}
            and bool(str(row.get("market_benchmark_code", "")))
            and bool(str(row.get("industry_code", "")))
            and row.get("formula_version") == "event-price-response-v2"
            and re.fullmatch(r"[0-9a-f]{64}", input_hash)
            and None not in returns
        ):
            return True
    return False


def _has_strict_deep_event_inputs(frame: pd.DataFrame | None) -> bool:
    if frame is None or frame.empty:
        return False
    required = (
        "body",
        "amount",
        "subject",
        "execution_conditions",
        "event_stage",
        "failure_conditions",
        "deep_read_completed",
        "deep_read_input_hash",
    )
    for _, row in frame.iterrows():
        if any(field not in row or _is_missing(row[field]) for field in required):
            continue
        if _is_literal_python_true(row["deep_read_completed"]) and re.fullmatch(
            r"[0-9a-f]{64}", str(row["deep_read_input_hash"])
        ):
            return True
    return False


def _has_aligned_company_event_inputs(
    announcement: pd.DataFrame | None,
    response: pd.DataFrame | None,
    cutoff: datetime,
    security_id: str,
) -> bool:
    if announcement is None or announcement.empty or response is None:
        return False
    spec = next(spec for spec in _INPUT_SPECS if spec.dataset == "announcement")
    required = (
        "body",
        "amount",
        "subject",
        "execution_conditions",
        "event_stage",
        "failure_conditions",
        "deep_read_completed",
        "deep_read_input_hash",
    )
    for _, event in announcement.iterrows():
        if any(field not in event or _is_missing(event[field]) for field in required):
            continue
        deep_hash = str(event["deep_read_input_hash"])
        if not _is_literal_python_true(event["deep_read_completed"]) or not re.fullmatch(
            r"[0-9a-f]{64}", deep_hash
        ):
            continue
        row_key, _, _ = _fixed_source_row_identity(
            spec, event, security_id, cutoff
        )
        event_time = _as_datetime(event.get("announcement_time"))
        record_id = str(event.get("announcement_id", ""))
        for _, row in response.iterrows():
            if (
                _has_valid_event_response(
                    pd.DataFrame([row]), cutoff, allowed_datasets=("announcement",)
                )
                and str(row.get("source_event_row_key")) == row_key
                and str(row.get("source_record_id")) == record_id
                and _as_datetime(row.get("event_time")) == event_time
                and row.get("source_deep_read_status") == "complete"
                and str(row.get("source_deep_read_input_hash")) == deep_hash
            ):
                return True
    return False


def _has_aligned_earnings_event_inputs(
    facts: Mapping[str, pd.DataFrame],
    response: pd.DataFrame | None,
    cutoff: datetime,
    security_id: str,
) -> bool:
    if response is None or response.empty:
        return False
    for dataset in ("earnings_forecast", "earnings_express"):
        frame = facts.get(dataset)
        if frame is None or frame.empty:
            continue
        spec = next(spec for spec in _INPUT_SPECS if spec.dataset == dataset)
        for _, event in frame.iterrows():
            if any(
                field not in event or _is_missing(event[field])
                for field in spec.required_fields
            ):
                continue
            report_period = _as_datetime(event.get("report_period"))
            if report_period is None:
                continue
            period = report_period.date().isoformat()
            if not (
                _period_has_complete_values(
                    facts.get("income_statement"),
                    period,
                    ("revenue", "n_income_attr_p"),
                )
                and _period_has_complete_values(
                    facts.get("cash_flow"), period, ("n_cashflow_act",)
                )
            ):
                continue
            row_key, _, _ = _fixed_source_row_identity(
                spec, event, security_id, cutoff
            )
            for _, row in response.iterrows():
                if (
                    _has_valid_event_response(
                        pd.DataFrame([row]), cutoff, allowed_datasets=(dataset,)
                    )
                    and str(row.get("source_event_row_key")) == row_key
                    and str(row.get("source_report_period")) == period
                ):
                    return True
    return False


def _has_aligned_distress_event_inputs(
    facts: Mapping[str, pd.DataFrame],
    response: pd.DataFrame | None,
    cutoff: datetime,
    security_id: str,
) -> bool:
    return bool(
        _aligned_distress_source_evidence_ids(
            facts, response, cutoff, security_id
        )
    )


def _aligned_distress_source_evidence_ids(
    facts: Mapping[str, pd.DataFrame],
    response: pd.DataFrame | None,
    cutoff: datetime,
    security_id: str,
) -> tuple[str, ...]:
    if response is None or response.empty:
        return ()
    source_ids: set[str] = set()
    for dataset in ("repurchase", "holder_trade", "share_float", "pledge"):
        frame = facts.get(dataset)
        if frame is None or frame.empty:
            continue
        spec = next(spec for spec in _INPUT_SPECS if spec.dataset == dataset)
        for _, event in frame.iterrows():
            row_key, _, _ = _fixed_source_row_identity(
                spec, event, security_id, cutoff
            )
            for _, row in response.iterrows():
                if (
                    _has_valid_event_response(
                        pd.DataFrame([row]), cutoff, allowed_datasets=(dataset,)
                    )
                    and str(row.get("source_event_row_key")) == row_key
                ):
                    source_ids.add(str(row.get("source_event_evidence_id")))
    return tuple(sorted(source_ids))


def _period_has_complete_values(
    frame: pd.DataFrame | None,
    period: str,
    fields: Sequence[str],
) -> bool:
    if (
        frame is None
        or frame.empty
        or "report_period" not in frame
        or not set(fields).issubset(frame.columns)
    ):
        return False
    selected = frame[frame["report_period"].astype(str) == period]
    return _has_complete_row(selected, fields)


def _has_valid_target_path(frame: pd.DataFrame | None) -> bool:
    if frame is None or frame.empty:
        return False
    for _, row in frame.iterrows():
        baseline = _decimal_value(row.get("current_baseline"))
        target_return = _decimal_value(row.get("target_return"))
        target_price = _decimal_value(row.get("target_price"))
        input_hash = str(row.get("input_hash", ""))
        drivers = row.get("candidate_driver_evidence_ids")
        risks = row.get("counterevidence_input_ids")
        if (
            baseline is not None
            and baseline > 0
            and target_return == Decimal("0.20")
            and target_price == baseline * Decimal("1.20")
            and row.get("horizon_days_10") == 10
            and row.get("horizon_days_20") == 20
            and row.get("horizon_days_30") == 30
            and isinstance(drivers, (tuple, list))
            and isinstance(risks, (tuple, list))
            and row.get("formula_version") == "target-path-inputs-v2"
            and re.fullmatch(r"[0-9a-f]{64}", input_hash)
        ):
            return True
    return False


def _row_available_at(
    row: pd.Series, cutoff: datetime, kind: Literal["fact", "derived"]
) -> datetime:
    if kind == "derived":
        return cutoff
    if "available_at" not in row or _is_missing(row["available_at"]):
        raise ValueError("API fact lacks available_at")
    value = _as_datetime(row["available_at"])
    if value is None:
        raise ValueError("API fact has invalid available_at")
    return value


def _row_business_time(row: pd.Series, available_at: datetime) -> datetime:
    for field in _BUSINESS_TIME_FIELDS:
        if field in row and not _is_missing(row[field]):
            value = _as_datetime(row[field])
            if value is not None and value <= available_at:
                return value
    return available_at


def _referenced_text(text: str, evidence_ids: Sequence[str]) -> EvidenceText:
    if _NUMBER.search(text):
        return EvidenceText(
            text="numeric validation condition preserved by governed source hash",
            source_text_hash=_stable_hash(text),
        )
    return EvidenceText(text=text)


def _reject_unknown(values: Sequence[str], known: set[str], label: str) -> None:
    unknown = set(values).difference(known)
    if unknown:
        raise ValueError(f"{label} cites unknown evidence: " + ", ".join(sorted(unknown)))


def _reject_future_rows(frames: Iterable[pd.DataFrame], cutoff: datetime) -> None:
    for frame in frames:
        if "available_at" not in frame.columns:
            continue
        for raw in frame["available_at"].dropna().tolist():
            value = _as_datetime(raw)
            if value is None:
                raise ValueError("unparseable available_at in formation snapshot")
            if value > cutoff:
                raise ValueError("source row became available after formation cutoff")


def _validate_derived_dates(
    frames: Mapping[str, pd.DataFrame], analysis_date: date
) -> None:
    for dataset, frame in frames.items():
        if frame.empty:
            continue
        if "analysis_date" not in frame.columns:
            raise ValueError(f"derived analysis_date missing for {dataset}")
        try:
            observed = set(pd.to_datetime(frame["analysis_date"], errors="raise").dt.date)
        except Exception as exc:
            raise ValueError(f"derived analysis_date invalid for {dataset}") from exc
        if observed != {analysis_date}:
            raise ValueError(f"derived analysis_date differs from formation date for {dataset}")


def _as_frame(value: Any) -> pd.DataFrame:
    return value.copy(deep=True) if isinstance(value, pd.DataFrame) else pd.DataFrame(value)


def _as_datetime(value: Any) -> datetime | None:
    if value is None or _is_missing(value):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=_SHANGHAI)
    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=_SHANGHAI)
    try:
        parsed = pd.Timestamp(value)
    except Exception:
        return None
    if pd.isna(parsed):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.tz_localize(_SHANGHAI)
    return parsed.to_pydatetime()


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        result = pd.isna(value)
    except Exception:
        return False
    if result is pd.NA:
        return True
    try:
        return bool(result)
    except (TypeError, ValueError):
        return False


def _scalar(value: Any) -> EvidenceScalar:
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    if hasattr(value, "item") and not isinstance(value, (str, bytes, Decimal)):
        try:
            value = value.item()
        except (TypeError, ValueError):
            pass
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("non-finite evidence values are forbidden")
    if isinstance(value, tuple) and all(isinstance(item, str) for item in value):
        return value
    if not isinstance(value, (str, int, float, Decimal, bool, date, datetime)):
        return str(value)
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _stable_hash(value: Any) -> str:
    canonical = json.dumps(
        _jsonable(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, StrEnum):
        return value.value
    if hasattr(value, "item"):
        try:
            return _jsonable(value.item())
        except (TypeError, ValueError):
            pass
    return value


__all__ = [
    "CandidateEvidencePacket",
    "EvidenceFactPlan",
    "EvidencePlanAudit",
    "EvidenceAvailability",
    "EvidenceCardStatus",
    "EvidenceDatum",
    "EvidenceInputCoverage",
    "EvidenceInputRequirement",
    "EvidenceInputStatus",
    "EvidenceSection",
    "EvidenceSectionName",
    "EvidenceText",
    "KnowledgeRoutingRecord",
    "KnowledgeRoutingStatus",
    "ModelJudgment",
    "OpportunityEvidenceCard",
    "RegistryAudit",
    "RouteManifestAudit",
    "build_candidate_packet",
    "build_evidence_fact_plan",
    "evidence_input_contract",
    "project_route_snapshot",
]
