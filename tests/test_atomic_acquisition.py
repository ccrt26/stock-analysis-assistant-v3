from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from stock_analyzer.data.acquisition import (
    AcquisitionBlocked,
    AtomicGroupAcquirer,
    TransientRouteFailure,
)
from stock_analyzer.data.readiness import (
    AcquisitionGroupContract,
    AcquisitionGroupId,
    AcquisitionPayload,
    AcquisitionRequest,
    FailureClassification,
    CapabilityEvidenceKind,
    RouteCapabilityEvidence,
    RouteKind,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")
TARGET = date(2026, 7, 10)
NOW = datetime(2026, 7, 10, 16, 0, tzinfo=SHANGHAI)


def _contract() -> AcquisitionGroupContract:
    return AcquisitionGroupContract(
        group_id=AcquisitionGroupId.MARKET_DECISION,
        contract_version="formal-v1",
        required_fields=("trade_date", "ts_code", "open", "high", "low", "close", "vol", "amount"),
        unique_key_fields=("trade_date", "ts_code"),
        current_fact_fields=("open", "high", "low", "close", "vol", "amount"),
        minimum_history_sessions=1,
        expected_codes=("600000.SH",),
    )


def _request() -> AcquisitionRequest:
    return AcquisitionRequest(
        run_id="run-1",
        trade_date=TARGET,
        report_cutoff=NOW,
        target_codes=("600000.SH",),
        contract_version="formal-v1",
    )


def _payload(kind: RouteKind, route_id: str, close: float = 10.5, complete: bool = True):
    record = {
        "trade_date": TARGET,
        "ts_code": "600000.SH",
        "open": 10.0,
        "high": max(11.0, close),
        "low": 9.5,
        "close": close,
        "vol": 1000.0,
        "amount": 10_500.0,
    }
    if not complete:
        del record["amount"]
    return AcquisitionPayload(
        group_id=AcquisitionGroupId.MARKET_DECISION,
        route_id=route_id,
        route_kind=kind,
        trade_date=TARGET,
        fetched_at=NOW,
        source_names=(f"{route_id}.source",),
        records=(record,),
        covered_dates=(TARGET,),
        field_coverage={field: field in record for field in _contract().required_fields},
        unit_metadata={"vol": "shares", "amount": "CNY"},
        adjustment_basis="unadjusted",
    )


def _capability(route_id: str, kind: RouteKind, approved: bool = True):
    return RouteCapabilityEvidence(
        route_id=route_id,
        group_id=AcquisitionGroupId.MARKET_DECISION,
        contract_version="formal-v1",
        full_contract_tested=approved,
        field_semantics_verified=approved,
        full_universe_verified=approved,
        post_close_verified=approved,
        tested_at=NOW,
    )


class FakeRoute:
    def __init__(self, route_id: str, kind: RouteKind, outcomes: list[object], approved: bool = True):
        self.route_id = route_id
        self.kind = kind
        self.capability = _capability(route_id, kind, approved)
        self.outcomes = list(outcomes)
        self.calls: list[AcquisitionRequest] = []

    def fetch(self, request: AcquisitionRequest) -> AcquisitionPayload:
        assert isinstance(request, AcquisitionRequest)
        self.calls.append(request)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def test_complete_primary_succeeds_without_calling_backup():
    primary = FakeRoute("primary", RouteKind.PRIMARY, [_payload(RouteKind.PRIMARY, "primary")])
    backup = FakeRoute("backup", RouteKind.BACKUP, [_payload(RouteKind.BACKUP, "backup")])

    result = AtomicGroupAcquirer().acquire(_contract(), _request(), primary, backup)

    assert result.payload.route_id == "primary"
    assert result.used_backup is False
    assert len(primary.calls) == 1
    assert backup.calls == []


def test_transient_primary_failure_retries_before_backup():
    primary = FakeRoute(
        "primary",
        RouteKind.PRIMARY,
        [
            TransientRouteFailure("network timeout", FailureClassification.TRANSPORT),
            _payload(RouteKind.PRIMARY, "primary"),
        ],
    )
    backup = FakeRoute("backup", RouteKind.BACKUP, [_payload(RouteKind.BACKUP, "backup")])

    result = AtomicGroupAcquirer(primary_retry_limit=2).acquire(
        _contract(), _request(), primary, backup
    )

    assert result.payload.route_id == "primary"
    assert len(primary.calls) == 2
    assert backup.calls == []
    assert [attempt.status for attempt in result.attempts] == ["failed", "success"]


def test_partial_primary_is_discarded_and_backup_starts_empty():
    primary = FakeRoute(
        "primary", RouteKind.PRIMARY, [_payload(RouteKind.PRIMARY, "primary", complete=False)]
    )
    backup_payload = _payload(RouteKind.BACKUP, "backup", close=99.0)
    backup = FakeRoute("backup", RouteKind.BACKUP, [backup_payload])

    result = AtomicGroupAcquirer().acquire(_contract(), _request(), primary, backup)

    assert result.used_backup is True
    assert result.payload == backup_payload
    assert len(backup.calls) == 1
    assert len(result.payload.records) == 1


def test_backup_result_contains_no_primary_record_or_source_name():
    primary = FakeRoute(
        "primary", RouteKind.PRIMARY, [_payload(RouteKind.PRIMARY, "primary", complete=False)]
    )
    backup = FakeRoute("backup", RouteKind.BACKUP, [_payload(RouteKind.BACKUP, "backup", close=88.0)])

    result = AtomicGroupAcquirer().acquire(_contract(), _request(), primary, backup)

    serialized = result.payload.model_dump_json()
    assert "primary.source" not in serialized
    assert result.payload.records[0]["close"] == 88.0


def test_no_provider_value_comparison_or_difference_alert_is_emitted():
    primary = FakeRoute(
        "primary", RouteKind.PRIMARY, [_payload(RouteKind.PRIMARY, "primary", close=10.5, complete=False)]
    )
    backup = FakeRoute("backup", RouteKind.BACKUP, [_payload(RouteKind.BACKUP, "backup", close=500.0)])

    result = AtomicGroupAcquirer().acquire(_contract(), _request(), primary, backup)

    assert result.validation.complete is True
    assert not hasattr(result, "difference_warning")
    assert all("difference" not in attempt.message.lower() for attempt in result.attempts)


def test_incomplete_backup_raises_acquisition_blocked():
    primary = FakeRoute(
        "primary", RouteKind.PRIMARY, [_payload(RouteKind.PRIMARY, "primary", complete=False)]
    )
    backup = FakeRoute(
        "backup", RouteKind.BACKUP, [_payload(RouteKind.BACKUP, "backup", complete=False)]
    )

    with pytest.raises(AcquisitionBlocked) as captured:
        AtomicGroupAcquirer().acquire(_contract(), _request(), primary, backup)

    assert captured.value.group_id == AcquisitionGroupId.MARKET_DECISION
    assert len(captured.value.attempts) == 2
    assert any(reason.startswith("missing_field:amount") for reason in captured.value.reasons)


def test_unproven_route_capability_blocks_before_fetch():
    primary = FakeRoute(
        "primary", RouteKind.PRIMARY, [_payload(RouteKind.PRIMARY, "primary")], approved=False
    )
    backup = FakeRoute("backup", RouteKind.BACKUP, [_payload(RouteKind.BACKUP, "backup")])

    with pytest.raises(AcquisitionBlocked, match="capability"):
        AtomicGroupAcquirer().acquire(_contract(), _request(), primary, backup)

    assert primary.calls == []
    assert backup.calls == []


def test_recorded_capability_is_approved_offline_but_not_for_live_use():
    capability = _capability("primary", RouteKind.PRIMARY)

    assert capability.evidence_kind is CapabilityEvidenceKind.RECORDED
    assert capability.approved is True
    assert capability.approved_for_live is False
