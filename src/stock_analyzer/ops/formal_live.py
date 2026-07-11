from __future__ import annotations

import hashlib
import importlib.metadata
import json
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from stock_analyzer.data.acquisition import RouteFailure
from stock_analyzer.data.akshare_formal_client import AkshareFormalEndpointClient
from stock_analyzer.data.capability_store import CapabilityBundle, LocalCapabilityStore
from stock_analyzer.data.formal_contracts import (
    FORMAL_CONTRACT_VERSION,
    build_screening_contracts,
    build_target_contracts,
)
from stock_analyzer.data.formal_routes import (
    EndpointResponse,
    derive_expected_tradable_codes,
    formal_network_route_definitions,
)
from stock_analyzer.data.formal_policy import (
    FORMAL_CAPABILITY_POST_CLOSE_START,
    FORMAL_EQUITY_FEATURE_SESSION_COUNT,
    FORMAL_SCREENING_SESSION_COUNT,
)
from stock_analyzer.data.readiness import (
    AcquisitionGroupId,
    AcquisitionPayload,
    AcquisitionRequest,
    CapabilityEvidenceKind,
    GroupValidation,
    RouteCapabilityEvidence,
    RouteKind,
    validate_group_payload,
)
from stock_analyzer.data.tushare_formal_client import TushareFormalEndpointClient
from stock_analyzer.ops.redaction import redact_secrets
from stock_analyzer.storage.evidence_store import GroupVersionManifest, LocalEvidenceStore


class LiveCapabilityVerificationError(RuntimeError):
    pass


@dataclass(frozen=True)
class LiveCapabilityVerificationResult:
    bundle: CapabilityBundle
    primary_screening_versions: tuple[GroupVersionManifest, ...]
    target_probe_codes: tuple[str, ...]
    unavailable_route_ids: tuple[str, ...] = ()


def verify_and_record_live_capabilities(
    runtime: Any,
    trade_date: date,
    report_cutoff: datetime,
    *,
    evidence_kind: CapabilityEvidenceKind = CapabilityEvidenceKind.LIVE,
    confirm_live_read: bool = False,
    tested_at: datetime | None = None,
    tested_library_versions: dict[str, str] | None = None,
) -> LiveCapabilityVerificationResult:
    if evidence_kind is CapabilityEvidenceKind.LIVE and not confirm_live_read:
        raise LiveCapabilityVerificationError(
            "live provider reads require explicit confirmation"
        )
    if report_cutoff.tzinfo is None:
        raise LiveCapabilityVerificationError("report cutoff must be timezone-aware")
    if report_cutoff.time() < FORMAL_CAPABILITY_POST_CLOSE_START:
        raise LiveCapabilityVerificationError("capability verification must be post-close")

    tested_at = tested_at or datetime.now(report_cutoff.tzinfo)
    if tested_at.tzinfo is None or tested_at < report_cutoff:
        raise LiveCapabilityVerificationError(
            "tested_at must be timezone-aware and no earlier than report cutoff"
        )
    versions = tested_library_versions or _installed_library_versions()
    primary = TushareFormalEndpointClient(runtime.tushare_pro)
    backup = AkshareFormalEndpointClient(runtime.akshare_module)
    clients = (
        (RouteKind.PRIMARY, primary),
        (RouteKind.BACKUP, backup),
    )
    definitions = formal_network_route_definitions()
    include_concepts = bool(runtime.enable_concepts)
    target_group_ids = (
        AcquisitionGroupId.BOARD_INDUSTRY,
        AcquisitionGroupId.CANDIDATE_FUNDAMENTAL,
        AcquisitionGroupId.OFFICIAL_EVENTS_RISK,
        *((AcquisitionGroupId.CONCEPT_THEME,) if include_concepts else ()),
    )
    evidence: list[RouteCapabilityEvidence] = []
    unavailable_route_ids: list[str] = []
    primary_payloads: dict[AcquisitionGroupId, AcquisitionPayload] = {}
    primary_validations: dict[AcquisitionGroupId, GroupValidation] = {}
    primary_probe_codes: tuple[str, ...] = ()

    for route_kind, client in clients:
        route_index = 0 if route_kind is RouteKind.PRIMARY else 1
        if (
            evidence_kind is CapabilityEvidenceKind.LIVE
            and route_kind is RouteKind.BACKUP
        ):
            if not primary_probe_codes:
                raise LiveCapabilityVerificationError(
                    "primary screening probe codes are required before backup target verification"
                )
            unavailable_route_ids.extend(
                (
                    definitions[AcquisitionGroupId.CALENDAR_UNIVERSE][route_index],
                    definitions[AcquisitionGroupId.MARKET_DECISION][route_index],
                )
            )
            target_contracts = build_target_contracts(
                trade_date,
                primary_probe_codes,
                include_concepts=include_concepts,
            )
            for group_id in target_group_ids:
                route_id = definitions[group_id][route_index]
                if _live_capability_block_reason(client, group_id):
                    unavailable_route_ids.append(route_id)
                    continue
                target_request = _request(
                    trade_date,
                    report_cutoff,
                    target_codes=primary_probe_codes,
                    suffix=route_kind.value,
                )
                try:
                    response = EndpointResponse.model_validate(
                        getattr(client, definitions[group_id][2])(target_request)
                    )
                    _validated_payload(
                        route_id,
                        route_kind,
                        group_id,
                        target_request,
                        response,
                        target_contracts[group_id],
                        tested_at,
                    )
                except (RouteFailure, LiveCapabilityVerificationError):
                    unavailable_route_ids.append(route_id)
                    continue
                evidence.append(
                    _route_evidence(
                        route_id,
                        group_id,
                        response,
                        evidence_kind,
                        tested_at,
                        versions,
                    )
                )
            continue
        calendar_request = _request(
            trade_date,
            report_cutoff,
            target_codes=(),
            suffix=route_kind.value,
        )
        calendar_response = EndpointResponse.model_validate(
            client.fetch_calendar_universe(calendar_request)
        )
        calendar_payload, calendar_validation = _validated_payload(
            definitions[AcquisitionGroupId.CALENDAR_UNIVERSE][route_index],
            route_kind,
            AcquisitionGroupId.CALENDAR_UNIVERSE,
            calendar_request,
            calendar_response,
            build_screening_contracts(trade_date, ())[
                AcquisitionGroupId.CALENDAR_UNIVERSE
            ],
            tested_at,
        )
        evidence.append(
            _route_evidence(
                definitions[AcquisitionGroupId.CALENDAR_UNIVERSE][route_index],
                AcquisitionGroupId.CALENDAR_UNIVERSE,
                calendar_response,
                evidence_kind,
                tested_at,
                versions,
            )
        )
        sessions = sorted(set(calendar_response.covered_dates))
        if len(sessions) != FORMAL_SCREENING_SESSION_COUNT:
            raise LiveCapabilityVerificationError(
                f"{route_kind.value} calendar did not prove exactly "
                f"{FORMAL_SCREENING_SESSION_COUNT} sessions"
            )
        security_records = tuple(
            row
            for row in calendar_response.records
            if row.get("record_type") == "security"
        )
        try:
            eligible_codes = derive_expected_tradable_codes(
                security_records,
                minimum_history_start=sessions[-FORMAL_EQUITY_FEATURE_SESSION_COUNT],
            )
        except ValueError as exc:
            raise LiveCapabilityVerificationError(
                redact_secrets(f"{route_kind.value} universe eligibility failed: {exc}")
            ) from exc
        if not eligible_codes:
            raise LiveCapabilityVerificationError(
                f"{route_kind.value} universe has no analysis-eligible codes"
            )

        market_request = _request(
            trade_date,
            report_cutoff,
            target_codes=eligible_codes,
            suffix=route_kind.value,
        )
        market_response = EndpointResponse.model_validate(
            client.fetch_market_decision(market_request)
        )
        market_payload, market_validation = _validated_payload(
            definitions[AcquisitionGroupId.MARKET_DECISION][route_index],
            route_kind,
            AcquisitionGroupId.MARKET_DECISION,
            market_request,
            market_response,
            build_screening_contracts(trade_date, ())[
                AcquisitionGroupId.MARKET_DECISION
            ],
            tested_at,
        )
        evidence.append(
            _route_evidence(
                definitions[AcquisitionGroupId.MARKET_DECISION][route_index],
                AcquisitionGroupId.MARKET_DECISION,
                market_response,
                evidence_kind,
                tested_at,
                versions,
            )
        )
        probe_codes = eligible_codes[:10]
        if route_kind is RouteKind.PRIMARY:
            primary_probe_codes = probe_codes
            primary_payloads = {
                AcquisitionGroupId.CALENDAR_UNIVERSE: calendar_payload,
                AcquisitionGroupId.MARKET_DECISION: market_payload,
            }
            primary_validations = {
                AcquisitionGroupId.CALENDAR_UNIVERSE: calendar_validation,
                AcquisitionGroupId.MARKET_DECISION: market_validation,
            }

        target_contracts = build_target_contracts(
            trade_date,
            probe_codes,
            include_concepts=include_concepts,
        )
        for group_id in target_group_ids:
            method_name = definitions[group_id][2]
            target_request = _request(
                trade_date,
                report_cutoff,
                target_codes=probe_codes,
                suffix=route_kind.value,
            )
            route_id = definitions[group_id][route_index]
            if (
                evidence_kind is CapabilityEvidenceKind.LIVE
                and _live_capability_block_reason(client, group_id)
            ):
                unavailable_route_ids.append(route_id)
                continue
            try:
                response = EndpointResponse.model_validate(
                    getattr(client, method_name)(target_request)
                )
                _validated_payload(
                    route_id,
                    route_kind,
                    group_id,
                    target_request,
                    response,
                    target_contracts[group_id],
                    tested_at,
                )
            except (RouteFailure, LiveCapabilityVerificationError):
                unavailable_route_ids.append(route_id)
                continue
            evidence.append(
                _route_evidence(
                    route_id,
                    group_id,
                    response,
                    evidence_kind,
                    tested_at,
                    versions,
                )
            )

    required_groups = {
        AcquisitionGroupId.CALENDAR_UNIVERSE,
        AcquisitionGroupId.MARKET_DECISION,
        *target_group_ids,
    }
    covered_groups = {item.group_id for item in evidence}
    missing_groups = sorted(
        group_id.value for group_id in required_groups if group_id not in covered_groups
    )
    bundle = CapabilityBundle(
        contract_version=FORMAL_CONTRACT_VERSION,
        generated_at=tested_at,
        routes=tuple(sorted(evidence, key=lambda item: item.route_id)),
    )
    _save_capability_bundle(runtime.capability_store, bundle)
    store = LocalEvidenceStore(
        runtime.config.local_warehouse_dir / "formal_evidence"
    )
    manifests: list[GroupVersionManifest] = []
    for group_id in (
        AcquisitionGroupId.CALENDAR_UNIVERSE,
        AcquisitionGroupId.MARKET_DECISION,
    ):
        manifest = store.save_group_version(
            primary_payloads[group_id],
            primary_validations[group_id],
        )
        store.set_canonical(group_id, trade_date, manifest.version_id)
        manifests.append(manifest)
    if missing_groups:
        raise LiveCapabilityVerificationError(
            "no live route passed the formal contract for: " + ", ".join(missing_groups)
        )
    return LiveCapabilityVerificationResult(
        bundle=bundle,
        primary_screening_versions=tuple(manifests),
        target_probe_codes=primary_probe_codes,
        unavailable_route_ids=tuple(sorted(unavailable_route_ids)),
    )


def _route_evidence(
    route_id: str,
    group_id: AcquisitionGroupId,
    response: EndpointResponse,
    evidence_kind: CapabilityEvidenceKind,
    tested_at: datetime,
    versions: dict[str, str],
) -> RouteCapabilityEvidence:
    return RouteCapabilityEvidence(
        route_id=route_id,
        group_id=group_id,
        contract_version=FORMAL_CONTRACT_VERSION,
        full_contract_tested=True,
        field_semantics_verified=True,
        full_universe_verified=True,
        post_close_verified=True,
        tested_at=tested_at,
        evidence_kind=evidence_kind,
        response_hash=_response_hash(response),
        tested_library_versions=versions,
    )


def _live_capability_block_reason(
    client: Any,
    group_id: AcquisitionGroupId,
) -> str | None:
    checker = getattr(client, "live_capability_block_reason", None)
    if not callable(checker):
        return None
    return checker(group_id)


def _request(
    trade_date: date,
    report_cutoff: datetime,
    *,
    target_codes: tuple[str, ...],
    suffix: str,
) -> AcquisitionRequest:
    return AcquisitionRequest(
        run_id=f"capability-{trade_date.isoformat()}-{suffix}",
        trade_date=trade_date,
        report_cutoff=report_cutoff,
        target_codes=target_codes,
        contract_version=FORMAL_CONTRACT_VERSION,
    )


def _validated_payload(
    route_id: str,
    route_kind: RouteKind,
    group_id: AcquisitionGroupId,
    request: AcquisitionRequest,
    response: EndpointResponse,
    contract: Any,
    fetched_at: datetime,
) -> tuple[AcquisitionPayload, GroupValidation]:
    payload = AcquisitionPayload(
        group_id=group_id,
        route_id=route_id,
        route_kind=route_kind,
        trade_date=request.trade_date,
        fetched_at=fetched_at,
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
    validation = validate_group_payload(contract, request, payload)
    if not validation.complete:
        reasons = ", ".join(validation.reasons[:20])
        raise LiveCapabilityVerificationError(
            redact_secrets(f"{route_id} failed formal contract: {reasons}")
        )
    return payload, validation


def _response_hash(response: EndpointResponse) -> str:
    serialized = json.dumps(
        response.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _save_capability_bundle(
    store: LocalCapabilityStore,
    bundle: CapabilityBundle,
) -> None:
    if store.path.name == "latest.json":
        digest = hashlib.sha256(
            json.dumps(
                bundle.model_dump(mode="json"),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        version_path = store.path.parent / "versions" / f"{digest}.json"
        LocalCapabilityStore(version_path).save(bundle)
    store.save(bundle)


def _installed_library_versions() -> dict[str, str]:
    result: dict[str, str] = {}
    for package in ("tushare", "akshare", "pandas"):
        try:
            result[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            result[package] = "unknown"
    return result


__all__ = [
    "LiveCapabilityVerificationError",
    "LiveCapabilityVerificationResult",
    "verify_and_record_live_capabilities",
]
