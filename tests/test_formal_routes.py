from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from stock_analyzer.data.acquisition import PermanentRouteFailure
from stock_analyzer.data.formal_routes import (
    EndpointResponse,
    ManualHoldingsFileRoute,
    NormalizedEndpointRoute,
    build_formal_route_registry,
    derive_expected_tradable_codes,
)
from stock_analyzer.data.readiness import (
    JULY_10_OFFICIAL_SESSIONS,
    AcquisitionGroupContract,
    AcquisitionGroupId,
    AcquisitionRequest,
    RouteCapabilityEvidence,
    RouteKind,
    validate_group_payload,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")
TARGET = date(2026, 7, 10)
CUTOFF = datetime(2026, 7, 10, 16, 0, tzinfo=SHANGHAI)


def _request(codes=("600000.SH",)) -> AcquisitionRequest:
    return AcquisitionRequest(
        run_id="formal-route-test",
        trade_date=TARGET,
        report_cutoff=CUTOFF,
        target_codes=codes,
        contract_version="formal-v1",
    )


def _capability(route_id: str, group_id: AcquisitionGroupId) -> RouteCapabilityEvidence:
    return RouteCapabilityEvidence(
        route_id=route_id,
        group_id=group_id,
        contract_version="formal-v1",
        full_contract_tested=True,
        field_semantics_verified=True,
        full_universe_verified=True,
        post_close_verified=True,
        tested_at=CUTOFF,
    )


def _response(group_id: AcquisitionGroupId, codes=("600000.SH",)) -> EndpointResponse:
    records = tuple(
        {"trade_date": TARGET, "ts_code": code, "value": 1.0}
        for code in codes
    )
    return EndpointResponse(
        records=records,
        covered_dates=(TARGET,),
        coverage_codes=codes,
        field_coverage={"trade_date": True, "ts_code": True, "value": True},
        source_names=(f"recorded.{group_id.value}",),
        unit_metadata={"value": "declared"},
        adjustment_basis=None,
        publication_times={},
    )


class RecordedClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, AcquisitionRequest]] = []

    def _record(self, method: str, request: AcquisitionRequest, group_id: AcquisitionGroupId):
        self.calls.append((method, request))
        return _response(group_id, request.target_codes or ("600000.SH",))

    def fetch_calendar_universe(self, request):
        return self._record("fetch_calendar_universe", request, AcquisitionGroupId.CALENDAR_UNIVERSE)

    def fetch_market_decision(self, request):
        return self._record("fetch_market_decision", request, AcquisitionGroupId.MARKET_DECISION)

    def fetch_board_industry(self, request):
        return self._record("fetch_board_industry", request, AcquisitionGroupId.BOARD_INDUSTRY)

    def fetch_candidate_fundamentals(self, request):
        return self._record(
            "fetch_candidate_fundamentals", request, AcquisitionGroupId.CANDIDATE_FUNDAMENTAL
        )

    def fetch_official_events_risk(self, request):
        return self._record(
            "fetch_official_events_risk", request, AcquisitionGroupId.OFFICIAL_EVENTS_RISK
        )

    def fetch_concepts(self, request):
        return self._record("fetch_concepts", request, AcquisitionGroupId.CONCEPT_THEME)


ROUTE_SPECS = {
    AcquisitionGroupId.CALENDAR_UNIVERSE: (
        "tushare.calendar_universe.v1",
        "official_exchange.calendar_universe.v1",
    ),
    AcquisitionGroupId.MARKET_DECISION: (
        "tushare.market_decision.v1",
        "eastmoney.market_decision.v1",
    ),
    AcquisitionGroupId.BOARD_INDUSTRY: (
        "tushare.board_industry.v1",
        "eastmoney.board_industry.v1",
    ),
    AcquisitionGroupId.CANDIDATE_FUNDAMENTAL: (
        "tushare.candidate_fundamental.v1",
        "eastmoney.candidate_fundamental.v1",
    ),
    AcquisitionGroupId.OFFICIAL_EVENTS_RISK: (
        "official.events_risk.v1",
        "eastmoney.events_risk.v1",
    ),
    AcquisitionGroupId.CONCEPT_THEME: (
        "tushare.concept_theme.v1",
        "eastmoney.concept_theme.v1",
    ),
}


def _capabilities():
    return {
        route_id: _capability(route_id, group_id)
        for group_id, route_ids in ROUTE_SPECS.items()
        for route_id in route_ids
    }


def test_every_required_group_has_executable_primary_and_backup_or_approved_single_source(tmp_path):
    primary = RecordedClient()
    backup = RecordedClient()
    official = RecordedClient()
    registry = build_formal_route_registry(
        primary,
        backup,
        official,
        tmp_path / "holdings.json",
        _capabilities(),
    )

    for group_id in (
        AcquisitionGroupId.CALENDAR_UNIVERSE,
        AcquisitionGroupId.MARKET_DECISION,
        AcquisitionGroupId.BOARD_INDUSTRY,
        AcquisitionGroupId.CANDIDATE_FUNDAMENTAL,
        AcquisitionGroupId.OFFICIAL_EVENTS_RISK,
    ):
        pair = registry[group_id]
        assert callable(pair.primary.fetch)
        assert callable(pair.backup.fetch)
        assert pair.approved_single_source is False

    holdings = registry[AcquisitionGroupId.MANUAL_HOLDINGS]
    assert callable(holdings.primary.fetch)
    assert holdings.backup is None
    assert holdings.approved_single_source is True


def test_each_route_calls_its_exact_endpoint_method_and_normalizes_a_complete_payload():
    client = RecordedClient()
    capability = _capability(
        "tushare.candidate_fundamental.v1",
        AcquisitionGroupId.CANDIDATE_FUNDAMENTAL,
    )
    route = NormalizedEndpointRoute(
        route_id=capability.route_id,
        kind=RouteKind.PRIMARY,
        group_id=capability.group_id,
        client=client,
        client_method="fetch_candidate_fundamentals",
        capability=capability,
    )

    payload = route.fetch(_request())

    assert [name for name, _ in client.calls] == ["fetch_candidate_fundamentals"]
    assert payload.group_id == AcquisitionGroupId.CANDIDATE_FUNDAMENTAL
    assert payload.route_id == route.route_id
    assert payload.route_kind == RouteKind.PRIMARY
    assert payload.coverage_codes == ("600000.SH",)


def test_market_route_preserves_declared_units_adjustment_basis_and_82_covered_sessions():
    class MarketClient(RecordedClient):
        def fetch_market_decision(self, request):
            self.calls.append(("fetch_market_decision", request))
            return EndpointResponse(
                records=tuple(
                    {
                        "trade_date": session,
                        "ts_code": "600000.SH",
                        "open": 10.0,
                        "high": 11.0,
                        "low": 9.0,
                        "close": 10.5,
                        "vol": 1_000.0,
                        "amount": 10_500.0,
                    }
                    for session in JULY_10_OFFICIAL_SESSIONS
                ),
                covered_dates=JULY_10_OFFICIAL_SESSIONS,
                coverage_codes=("600000.SH",),
                field_coverage={
                    key: True
                    for key in ("trade_date", "ts_code", "open", "high", "low", "close", "vol", "amount")
                },
                source_names=("tushare.daily", "tushare.daily_basic", "tushare.index_daily"),
                unit_metadata={"vol": "shares", "amount": "CNY"},
                adjustment_basis="unadjusted",
            )

    capability = _capability("tushare.market_decision.v1", AcquisitionGroupId.MARKET_DECISION)
    route = NormalizedEndpointRoute(
        route_id=capability.route_id,
        kind=RouteKind.PRIMARY,
        group_id=capability.group_id,
        client=MarketClient(),
        client_method="fetch_market_decision",
        capability=capability,
    )

    payload = route.fetch(_request())

    assert len(payload.covered_dates) == 82
    assert payload.unit_metadata == {"vol": "shares", "amount": "CNY"}
    assert payload.adjustment_basis == "unadjusted"


def test_official_event_route_accepts_proven_empty_coverage_but_rejects_endpoint_failure():
    class EmptyEventClient(RecordedClient):
        def fetch_official_events_risk(self, request):
            return EndpointResponse(
                records=(),
                covered_dates=(TARGET,),
                coverage_codes=request.target_codes,
                field_coverage={"event_type": True, "publication_time": True},
                source_names=("sse.disclosure", "szse.disclosure"),
                coverage_proven=True,
            )

    capability = _capability("official.events_risk.v1", AcquisitionGroupId.OFFICIAL_EVENTS_RISK)
    route = NormalizedEndpointRoute(
        route_id=capability.route_id,
        kind=RouteKind.PRIMARY,
        group_id=capability.group_id,
        client=EmptyEventClient(),
        client_method="fetch_official_events_risk",
        capability=capability,
    )
    payload = route.fetch(_request())
    contract = AcquisitionGroupContract(
        group_id=AcquisitionGroupId.OFFICIAL_EVENTS_RISK,
        contract_version="formal-v1",
        required_fields=(),
        unique_key_fields=(),
        expected_codes=("600000.SH",),
    )

    assert validate_group_payload(contract, _request(), payload).complete is True

    class FailedEventClient(RecordedClient):
        def fetch_official_events_risk(self, request):
            raise RuntimeError("endpoint unavailable")

    failed_route = route.model_copy(update={"client": FailedEventClient()})
    with pytest.raises(RuntimeError, match="endpoint unavailable"):
        failed_route.fetch(_request())


def test_calendar_route_excuses_only_officially_suspended_or_hard_excluded_codes():
    rows = (
        {"ts_code": "600000.SH", "status_verified": True, "is_suspended": False, "hard_excluded": False},
        {"ts_code": "000001.SZ", "status_verified": True, "is_suspended": True, "hard_excluded": False},
        {"ts_code": "300001.SZ", "status_verified": True, "is_suspended": False, "hard_excluded": True},
    )

    assert derive_expected_tradable_codes(rows) == ("600000.SH",)


def test_unknown_missing_market_code_is_not_inferred_suspended():
    rows = (
        {"ts_code": "600000.SH", "status_verified": True, "is_suspended": False, "hard_excluded": False},
        {"ts_code": "000001.SZ", "status_verified": False},
    )

    with pytest.raises(ValueError, match="unverified_status:000001.SZ"):
        derive_expected_tradable_codes(rows)


def test_manual_holdings_route_distinguishes_explicit_empty_missing_and_malformed_files(tmp_path):
    path = tmp_path / "holdings.json"
    route = ManualHoldingsFileRoute(path)

    with pytest.raises(PermanentRouteFailure, match="missing"):
        route.fetch(_request())

    path.write_text("[]\n", encoding="utf-8")
    assert route.fetch(_request()).records == ()

    path.write_text(json.dumps({"ts_code": "600000.SH"}), encoding="utf-8")
    with pytest.raises(PermanentRouteFailure, match="JSON array"):
        route.fetch(_request())


def test_registry_contains_no_unverified_tushare_announcements_name():
    from stock_analyzer.data.source_registry import strategy_v2_source_registry

    serialized = " ".join(
        f"{plan.primary_path} {plan.backup_path}"
        for plan in strategy_v2_source_registry().values()
    )
    assert "tushare.announcements" not in serialized
    assert "OfficialDisclosureClient.fetch_official_events_risk" in serialized
