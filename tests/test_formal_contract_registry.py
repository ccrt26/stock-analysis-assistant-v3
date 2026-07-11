from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from stock_analyzer.data.formal_contracts import (
    FORMAL_CONTRACT_VERSION,
    build_screening_contracts,
    build_target_contracts,
)
from stock_analyzer.data.readiness import (
    JULY_10_OFFICIAL_SESSIONS,
    AcquisitionGroupId,
    AcquisitionPayload,
    AcquisitionRequest,
    RouteKind,
    validate_group_payload,
)


TARGET = date(2026, 7, 10)
CUTOFF = datetime(2026, 7, 10, 16, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
CODES = ("600000.SH",)
INDEX_CODES = ("000001.SH", "399001.SZ", "899050.BJ")


def request() -> AcquisitionRequest:
    return AcquisitionRequest(
        run_id="formal-2026-07-10",
        trade_date=TARGET,
        report_cutoff=CUTOFF,
        target_codes=CODES,
        contract_version=FORMAL_CONTRACT_VERSION,
    )


def complete_market_payload() -> AcquisitionPayload:
    equity_bars = tuple(
        {
            "record_type": "equity_bar",
            "trade_date": session,
            "ts_code": CODES[0],
            "open": 10.0,
            "high": 11.0,
            "low": 9.0,
            "close": 10.5,
            "volume": 1_000_000.0,
            "amount": 10_500_000.0,
            "source_name": "tushare.daily",
        }
        for session in JULY_10_OFFICIAL_SESSIONS
    )
    daily_basic = (
        {
            "record_type": "daily_basic",
            "trade_date": TARGET,
            "ts_code": CODES[0],
            "turnover_rate": 1.2,
            "total_mv": 100_000_000_000.0,
            "circ_mv": 80_000_000_000.0,
            "pe_ttm": 9.5,
            "pb": 1.1,
            "source_name": "tushare.daily_basic",
        },
    )
    index_bars = tuple(
        {
            "record_type": "index_bar",
            "trade_date": TARGET,
            "ts_code": code,
            "open": 3_000.0,
            "high": 3_050.0,
            "low": 2_990.0,
            "close": 3_020.0,
            "volume": 2_000_000.0,
            "amount": 20_000_000.0,
            "source_name": "tushare.index_daily",
        }
        for code in INDEX_CODES
    )
    records = equity_bars + daily_basic + index_bars
    fields = {key for record in records for key in record}
    return AcquisitionPayload(
        group_id=AcquisitionGroupId.MARKET_DECISION,
        route_id="tushare.market_decision.v2",
        route_kind=RouteKind.PRIMARY,
        trade_date=TARGET,
        fetched_at=CUTOFF,
        source_names=("tushare.daily", "tushare.daily_basic", "tushare.index_daily"),
        records=records,
        covered_dates=JULY_10_OFFICIAL_SESSIONS,
        coverage_codes=CODES + INDEX_CODES,
        coverage_proven=True,
        field_coverage={field: True for field in fields},
        unit_metadata={"volume": "shares", "amount": "CNY"},
        adjustment_basis="unadjusted",
        contract_version=FORMAL_CONTRACT_VERSION,
    )


def market_contract():
    return build_screening_contracts(TARGET, CODES)[AcquisitionGroupId.MARKET_DECISION]


def test_market_contract_validates_equity_bars_daily_basic_and_index_bars_by_record_type():
    result = validate_group_payload(market_contract(), request(), complete_market_payload())

    assert result.complete is True
    assert result.reasons == ()


def test_unknown_record_type_and_missing_type_specific_field_fail_closed():
    unknown = complete_market_payload().model_copy(
        update={"records": ({"record_type": "unknown", "trade_date": TARGET},)}
    )
    unknown_result = validate_group_payload(market_contract(), request(), unknown)

    missing_close_records = list(complete_market_payload().records)
    missing_close_records[0] = dict(missing_close_records[0])
    del missing_close_records[0]["close"]
    missing_result = validate_group_payload(
        market_contract(),
        request(),
        complete_market_payload().model_copy(update={"records": tuple(missing_close_records)}),
    )

    assert "unknown_record_type:unknown:row=0" in unknown_result.reasons
    assert "missing_field:close:row=0" in missing_result.reasons


def test_legitimate_null_requires_explicit_provider_reason():
    records = list(complete_market_payload().records)
    basic_index = next(
        index
        for index, record in enumerate(records)
        if record["record_type"] == "daily_basic"
    )
    records[basic_index] = {
        **records[basic_index],
        "pe_ttm": None,
        "pb": None,
        "valuation_null_reason": "provider_reported_not_applicable",
    }
    explained = complete_market_payload().model_copy(update={"records": tuple(records)})

    explained_result = validate_group_payload(market_contract(), request(), explained)
    unexplained_records = list(explained.records)
    unexplained_records[basic_index] = dict(unexplained_records[basic_index])
    del unexplained_records[basic_index]["valuation_null_reason"]
    unexplained_result = validate_group_payload(
        market_contract(),
        request(),
        explained.model_copy(update={"records": tuple(unexplained_records)}),
    )

    assert explained_result.complete is True
    assert "unclassified_null:pe_ttm:row=82" in unexplained_result.reasons
    assert "unclassified_null:pb:row=82" in unexplained_result.reasons


def test_formal_v2_registry_contains_all_required_groups_and_exact_history():
    screening = build_screening_contracts(TARGET, CODES)
    target = build_target_contracts(TARGET, CODES)

    assert set(screening) == {
        AcquisitionGroupId.CALENDAR_UNIVERSE,
        AcquisitionGroupId.MARKET_DECISION,
    }
    assert set(target) == {
        AcquisitionGroupId.BOARD_INDUSTRY,
        AcquisitionGroupId.CANDIDATE_FUNDAMENTAL,
        AcquisitionGroupId.OFFICIAL_EVENTS_RISK,
        AcquisitionGroupId.MANUAL_HOLDINGS,
    }
    assert screening[AcquisitionGroupId.MARKET_DECISION].minimum_history_sessions == 82
    assert screening[AcquisitionGroupId.MARKET_DECISION].contract_version == "formal-v2"
