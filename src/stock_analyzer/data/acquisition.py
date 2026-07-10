from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict

from stock_analyzer.data.readiness import (
    AcquisitionGroupContract,
    AcquisitionGroupId,
    AcquisitionPayload,
    AcquisitionRequest,
    FailureClassification,
    GroupValidation,
    RouteCapabilityEvidence,
    RouteKind,
    validate_group_payload,
)
from stock_analyzer.ops.redaction import redact_secrets


class AcquisitionRoute(Protocol):
    route_id: str
    kind: RouteKind
    capability: RouteCapabilityEvidence

    def fetch(self, request: AcquisitionRequest) -> AcquisitionPayload: ...


class RouteFailure(RuntimeError):
    def __init__(
        self,
        message: str,
        classification: FailureClassification,
    ) -> None:
        self.classification = classification
        self.redacted_message = redact_secrets(message)
        super().__init__(self.redacted_message)


class TransientRouteFailure(RouteFailure):
    pass


class PermanentRouteFailure(RouteFailure):
    pass


class RouteAttempt(BaseModel):
    model_config = ConfigDict(frozen=True)

    route_id: str
    route_kind: RouteKind
    attempt: int
    status: str
    classification: FailureClassification | None = None
    message: str
    validation_reasons: tuple[str, ...] = ()


class AcquisitionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    payload: AcquisitionPayload
    validation: GroupValidation
    attempts: tuple[RouteAttempt, ...]
    used_backup: bool


class AcquisitionBlocked(RuntimeError):
    def __init__(
        self,
        group_id: AcquisitionGroupId,
        attempts: tuple[RouteAttempt, ...],
        reasons: tuple[str, ...],
    ) -> None:
        self.group_id = group_id
        self.attempts = attempts
        self.reasons = reasons
        message = redact_secrets(
            f"Acquisition group {group_id.value} blocked: "
            + ("; ".join(reasons) if reasons else "routes exhausted")
        )
        super().__init__(message)


class AtomicGroupAcquirer:
    def __init__(self, primary_retry_limit: int = 2) -> None:
        if primary_retry_limit < 1:
            raise ValueError("primary_retry_limit must be at least 1")
        self.primary_retry_limit = primary_retry_limit

    def acquire(
        self,
        contract: AcquisitionGroupContract,
        request: AcquisitionRequest,
        primary: AcquisitionRoute,
        backup: AcquisitionRoute,
    ) -> AcquisitionResult:
        capability_reasons = self._capability_reasons(
            contract,
            primary,
            backup,
        )
        if capability_reasons:
            raise AcquisitionBlocked(contract.group_id, (), capability_reasons)

        attempts: list[RouteAttempt] = []
        primary_result = self._run_route(
            contract,
            request,
            primary,
            attempts,
            retry_limit=self.primary_retry_limit,
        )
        if primary_result is not None:
            payload, validation = primary_result
            return AcquisitionResult(
                payload=payload,
                validation=validation,
                attempts=tuple(attempts),
                used_backup=False,
            )

        backup_result = self._run_route(
            contract,
            request,
            backup,
            attempts,
            retry_limit=self.primary_retry_limit,
        )
        if backup_result is not None:
            payload, validation = backup_result
            return AcquisitionResult(
                payload=payload,
                validation=validation,
                attempts=tuple(attempts),
                used_backup=True,
            )

        reasons = tuple(
            reason
            for attempt in attempts
            for reason in (
                attempt.validation_reasons
                or ((attempt.message,) if attempt.status == "failed" else ())
            )
        )
        raise AcquisitionBlocked(
            contract.group_id,
            tuple(attempts),
            tuple(dict.fromkeys(reasons)),
        )

    @staticmethod
    def _capability_reasons(
        contract: AcquisitionGroupContract,
        primary: AcquisitionRoute,
        backup: AcquisitionRoute,
    ) -> tuple[str, ...]:
        reasons: list[str] = []
        for route, expected_kind in (
            (primary, RouteKind.PRIMARY),
            (backup, RouteKind.BACKUP),
        ):
            capability = route.capability
            if route.kind != expected_kind:
                reasons.append(
                    f"capability_kind_mismatch:{route.route_id}:{route.kind.value}"
                )
            if capability.route_id != route.route_id:
                reasons.append(f"capability_route_mismatch:{route.route_id}")
            if capability.group_id != contract.group_id:
                reasons.append(f"capability_group_mismatch:{route.route_id}")
            if capability.contract_version != contract.contract_version:
                reasons.append(f"capability_contract_mismatch:{route.route_id}")
            if not capability.approved:
                reasons.append(f"capability_unproven:{route.route_id}")
        return tuple(reasons)

    @staticmethod
    def _run_route(
        contract: AcquisitionGroupContract,
        request: AcquisitionRequest,
        route: AcquisitionRoute,
        attempts: list[RouteAttempt],
        *,
        retry_limit: int,
    ) -> tuple[AcquisitionPayload, GroupValidation] | None:
        for attempt_number in range(1, retry_limit + 1):
            try:
                payload = route.fetch(request)
            except TransientRouteFailure as exc:
                attempts.append(
                    RouteAttempt(
                        route_id=route.route_id,
                        route_kind=route.kind,
                        attempt=attempt_number,
                        status="failed",
                        classification=exc.classification,
                        message=exc.redacted_message,
                    )
                )
                continue
            except PermanentRouteFailure as exc:
                attempts.append(
                    RouteAttempt(
                        route_id=route.route_id,
                        route_kind=route.kind,
                        attempt=attempt_number,
                        status="failed",
                        classification=exc.classification,
                        message=exc.redacted_message,
                    )
                )
                return None
            except Exception as exc:
                attempts.append(
                    RouteAttempt(
                        route_id=route.route_id,
                        route_kind=route.kind,
                        attempt=attempt_number,
                        status="failed",
                        classification=FailureClassification.UNKNOWN,
                        message=redact_secrets(str(exc)),
                    )
                )
                return None

            validation = validate_group_payload(contract, request, payload)
            if validation.complete:
                attempts.append(
                    RouteAttempt(
                        route_id=route.route_id,
                        route_kind=route.kind,
                        attempt=attempt_number,
                        status="success",
                        message="complete acquisition group accepted",
                    )
                )
                return payload, validation
            attempts.append(
                RouteAttempt(
                    route_id=route.route_id,
                    route_kind=route.kind,
                    attempt=attempt_number,
                    status="failed",
                    classification=FailureClassification.INVALID_SEMANTICS,
                    message="complete acquisition group rejected",
                    validation_reasons=validation.reasons,
                )
            )
            return None
        return None


__all__ = [
    "AcquisitionBlocked",
    "AcquisitionResult",
    "AcquisitionRoute",
    "AtomicGroupAcquirer",
    "PermanentRouteFailure",
    "RouteAttempt",
    "TransientRouteFailure",
]
