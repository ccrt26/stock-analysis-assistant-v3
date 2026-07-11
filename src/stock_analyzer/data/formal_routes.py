from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from stock_analyzer.data.acquisition import PermanentRouteFailure
from stock_analyzer.data.readiness import (
    AcquisitionGroupId,
    AcquisitionPayload,
    AcquisitionRequest,
    FailureClassification,
    RouteCapabilityEvidence,
    RouteKind,
)


class EndpointResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    records: tuple[dict[str, Any], ...]
    covered_dates: tuple[date, ...]
    coverage_codes: tuple[str, ...] = ()
    coverage_proven: bool = False
    field_coverage: dict[str, bool]
    source_names: tuple[str, ...]
    unit_metadata: dict[str, str] = Field(default_factory=dict)
    adjustment_basis: str | None = None
    publication_times: dict[str, datetime] = Field(default_factory=dict)


class FormalEndpointClient(Protocol):
    def fetch_calendar_universe(self, request: AcquisitionRequest) -> EndpointResponse: ...

    def fetch_market_decision(self, request: AcquisitionRequest) -> EndpointResponse: ...

    def fetch_board_industry(self, request: AcquisitionRequest) -> EndpointResponse: ...

    def fetch_candidate_fundamentals(
        self, request: AcquisitionRequest
    ) -> EndpointResponse: ...

    def fetch_official_events_risk(
        self, request: AcquisitionRequest
    ) -> EndpointResponse: ...

    def fetch_concepts(self, request: AcquisitionRequest) -> EndpointResponse: ...


class NormalizedEndpointRoute(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    route_id: str
    kind: RouteKind
    group_id: AcquisitionGroupId
    client: Any
    client_method: str
    capability: RouteCapabilityEvidence

    def fetch(self, request: AcquisitionRequest) -> AcquisitionPayload:
        method = getattr(self.client, self.client_method)
        response = EndpointResponse.model_validate(method(request))
        return AcquisitionPayload(
            group_id=self.group_id,
            route_id=self.route_id,
            route_kind=self.kind,
            trade_date=request.trade_date,
            fetched_at=request.report_cutoff,
            source_names=response.source_names,
            records=response.records,
            covered_dates=response.covered_dates,
            coverage_codes=response.coverage_codes,
            coverage_proven=response.coverage_proven,
            field_coverage=response.field_coverage,
            unit_metadata=response.unit_metadata,
            adjustment_basis=response.adjustment_basis,
            publication_times=response.publication_times,
            contract_version=request.contract_version,
        )


class ManualHoldingsFileRoute:
    route_id = "local.manual_holdings.v1"
    kind = RouteKind.LOCAL
    group_id = AcquisitionGroupId.MANUAL_HOLDINGS

    def __init__(
        self,
        path: Path,
        capability: RouteCapabilityEvidence | None = None,
        contract_version: str = "formal-v1",
    ) -> None:
        self.path = Path(path)
        self.capability = capability or RouteCapabilityEvidence(
            route_id=self.route_id,
            group_id=self.group_id,
            contract_version=contract_version,
            full_contract_tested=True,
            field_semantics_verified=True,
            full_universe_verified=True,
            post_close_verified=True,
            tested_at=datetime.now(timezone.utc),
        )

    def fetch(self, request: AcquisitionRequest) -> AcquisitionPayload:
        if not self.path.is_file():
            raise PermanentRouteFailure(
                "manual holdings file is missing",
                FailureClassification.MISSING_FIELDS,
            )
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PermanentRouteFailure(
                f"manual holdings file is malformed: {exc}",
                FailureClassification.SCHEMA,
            ) from exc
        if not isinstance(raw, list):
            raise PermanentRouteFailure(
                "manual holdings file must contain a JSON array",
                FailureClassification.SCHEMA,
            )
        records: list[dict[str, Any]] = []
        for index, item in enumerate(raw):
            if not isinstance(item, dict) or not isinstance(item.get("ts_code"), str):
                raise PermanentRouteFailure(
                    f"manual holdings row {index} must contain ts_code",
                    FailureClassification.SCHEMA,
                )
            records.append(
                {
                    **item,
                    "record_type": "manual_holding",
                    "trade_date": request.trade_date,
                    "source_name": "local.manual_holdings",
                }
            )
        return AcquisitionPayload(
            group_id=self.group_id,
            route_id=self.route_id,
            route_kind=self.kind,
            trade_date=request.trade_date,
            fetched_at=request.report_cutoff,
            source_names=("local.manual_holdings",),
            records=tuple(records),
            covered_dates=(request.trade_date,),
            coverage_codes=tuple(sorted(item["ts_code"] for item in records)),
            coverage_proven=True,
            field_coverage={
                "record_type": True,
                "trade_date": True,
                "ts_code": True,
                "name": True,
                "position_pct": True,
                "source_name": True,
            },
            contract_version=request.contract_version,
        )


class FormalRoutePair(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    primary: Any
    backup: Any | None
    approved_single_source: bool = False


class UnavailableFormalRoute:
    def __init__(
        self,
        route_id: str,
        kind: RouteKind,
        group_id: AcquisitionGroupId,
    ) -> None:
        self.route_id = route_id
        self.kind = kind
        self.group_id = group_id
        self.capability = RouteCapabilityEvidence(
            route_id=route_id,
            group_id=group_id,
            contract_version="unavailable",
            full_contract_tested=False,
            field_semantics_verified=False,
            full_universe_verified=False,
            post_close_verified=False,
            tested_at=datetime(1970, 1, 1, tzinfo=timezone.utc),
        )

    def fetch(self, request: AcquisitionRequest) -> AcquisitionPayload:
        del request
        raise PermanentRouteFailure(
            f"formal route has no verified live capability: {self.route_id}",
            FailureClassification.PERMISSION,
        )


_ROUTE_DEFINITIONS = {
    AcquisitionGroupId.CALENDAR_UNIVERSE: (
        "tushare.calendar_universe.v1",
        "official_exchange.calendar_universe.v1",
        "fetch_calendar_universe",
    ),
    AcquisitionGroupId.MARKET_DECISION: (
        "tushare.market_decision.v1",
        "eastmoney.market_decision.v1",
        "fetch_market_decision",
    ),
    AcquisitionGroupId.BOARD_INDUSTRY: (
        "tushare.board_industry.v1",
        "eastmoney.board_industry.v1",
        "fetch_board_industry",
    ),
    AcquisitionGroupId.CANDIDATE_FUNDAMENTAL: (
        "tushare.candidate_fundamental.v1",
        "eastmoney.candidate_fundamental.v1",
        "fetch_candidate_fundamentals",
    ),
    AcquisitionGroupId.OFFICIAL_EVENTS_RISK: (
        "official.events_risk.v1",
        "cninfo.direct.events_risk.v2",
        "fetch_official_events_risk",
    ),
    AcquisitionGroupId.CONCEPT_THEME: (
        "tushare.concept_theme.v1",
        "eastmoney.concept_theme.v1",
        "fetch_concepts",
    ),
}


def build_formal_route_registry(
    primary_client: FormalEndpointClient,
    backup_client: FormalEndpointClient,
    official_client: FormalEndpointClient,
    holdings_path: Path,
    capabilities: dict[str, RouteCapabilityEvidence],
    *,
    events_backup_client: FormalEndpointClient | None = None,
    require_live_capability: bool = False,
) -> dict[AcquisitionGroupId, FormalRoutePair]:
    if require_live_capability:
        recorded_routes = sorted(
            route_id
            for route_id, capability in capabilities.items()
            if not capability.approved_for_live
        )
        if recorded_routes:
            raise ValueError(
                "live capability evidence required for " + ", ".join(recorded_routes)
            )
    registry: dict[AcquisitionGroupId, FormalRoutePair] = {}
    contract_versions = {item.contract_version for item in capabilities.values()}
    if len(contract_versions) != 1:
        raise ValueError("formal route capabilities must share one contract version")
    contract_version = next(iter(contract_versions))
    for group_id, (primary_id, backup_id, method) in _ROUTE_DEFINITIONS.items():
        primary_owner = official_client if group_id == AcquisitionGroupId.OFFICIAL_EVENTS_RISK else primary_client
        backup_owner = (
            events_backup_client or backup_client
            if group_id == AcquisitionGroupId.OFFICIAL_EVENTS_RISK
            else backup_client
        )
        primary_capability = capabilities.get(primary_id)
        backup_capability = capabilities.get(backup_id)
        registry[group_id] = FormalRoutePair(
            primary=(
                NormalizedEndpointRoute(
                    route_id=primary_id,
                    kind=RouteKind.PRIMARY,
                    group_id=group_id,
                    client=primary_owner,
                    client_method=method,
                    capability=_required_capability(capabilities, primary_id, group_id),
                )
                if primary_capability is not None
                else UnavailableFormalRoute(primary_id, RouteKind.PRIMARY, group_id)
            ),
            backup=(
                NormalizedEndpointRoute(
                    route_id=backup_id,
                    kind=RouteKind.BACKUP,
                    group_id=group_id,
                    client=backup_owner,
                    client_method=method,
                    capability=_required_capability(capabilities, backup_id, group_id),
                )
                if backup_capability is not None
                else UnavailableFormalRoute(
                    backup_id,
                    RouteKind.BACKUP,
                    group_id,
                )
            ),
        )
    registry[AcquisitionGroupId.MANUAL_HOLDINGS] = FormalRoutePair(
        primary=ManualHoldingsFileRoute(
            holdings_path,
            contract_version=contract_version,
        ),
        backup=None,
        approved_single_source=True,
    )
    return registry


def formal_route_group_ids() -> dict[str, AcquisitionGroupId]:
    groups = {
        route_id: group_id
        for group_id, definition in _ROUTE_DEFINITIONS.items()
        for route_id in definition[:2]
    }
    groups[ManualHoldingsFileRoute.route_id] = AcquisitionGroupId.MANUAL_HOLDINGS
    return groups


def formal_network_route_definitions() -> dict[
    AcquisitionGroupId,
    tuple[str, str, str],
]:
    return dict(_ROUTE_DEFINITIONS)


def derive_expected_tradable_codes(
    universe_records: tuple[dict[str, Any], ...],
    *,
    minimum_history_start: date | None = None,
) -> tuple[str, ...]:
    expected: list[str] = []
    seen: set[str] = set()
    for record in universe_records:
        code = record.get("ts_code")
        if not isinstance(code, str) or not code:
            raise ValueError("universe row is missing ts_code")
        if code in seen:
            raise ValueError(f"duplicate_universe_code:{code}")
        seen.add(code)
        if record.get("status_verified") is not True:
            raise ValueError(f"unverified_status:{code}")
        if record.get("is_suspended") is True or record.get("hard_excluded") is True:
            continue
        if minimum_history_start is not None:
            raw_list_date = record.get("list_date")
            try:
                list_date = (
                    raw_list_date.date()
                    if isinstance(raw_list_date, datetime)
                    else raw_list_date
                    if isinstance(raw_list_date, date)
                    else date.fromisoformat(str(raw_list_date)[:10])
                )
            except (TypeError, ValueError) as exc:
                raise ValueError(f"invalid_list_date:{code}") from exc
            if list_date > minimum_history_start:
                continue
        expected.append(code)
    return tuple(sorted(expected))


def _required_capability(
    capabilities: dict[str, RouteCapabilityEvidence],
    route_id: str,
    group_id: AcquisitionGroupId,
) -> RouteCapabilityEvidence:
    capability = capabilities.get(route_id)
    if capability is None:
        raise ValueError(f"missing capability evidence for {route_id}")
    if capability.group_id != group_id:
        raise ValueError(f"capability group mismatch for {route_id}")
    return capability


__all__ = [
    "EndpointResponse",
    "FormalEndpointClient",
    "FormalRoutePair",
    "ManualHoldingsFileRoute",
    "NormalizedEndpointRoute",
    "UnavailableFormalRoute",
    "build_formal_route_registry",
    "derive_expected_tradable_codes",
    "formal_route_group_ids",
    "formal_network_route_definitions",
]
