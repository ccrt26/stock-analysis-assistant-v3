from __future__ import annotations

from datetime import date, datetime
from math import nan
from zoneinfo import ZoneInfo

from stock_analyzer.data.readiness import (
    JULY_10_OFFICIAL_SESSIONS,
    AcquisitionGroupContract,
    AcquisitionGroupId,
    AcquisitionPayload,
    AcquisitionRequest,
    RouteKind,
    validate_group_payload,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")
TRADE_DATE = date(2026, 7, 10)
CUTOFF = datetime(2026, 7, 10, 16, 0, tzinfo=SHANGHAI)


def _contract(**updates) -> AcquisitionGroupContract:
    values = {
        "group_id": AcquisitionGroupId.MARKET_DECISION,
        "contract_version": "formal-v1",
        "required_fields": (
            "trade_date",
            "ts_code",
            "open",
            "high",
            "low",
            "close",
            "vol",
            "amount",
            "pe_ttm",
            "pe_ttm_null_reason",
        ),
        "legitimate_null_fields": {"pe_ttm": "pe_ttm_null_reason"},
        "unique_key_fields": ("trade_date", "ts_code"),
        "current_fact_fields": ("open", "high", "low", "close", "vol", "amount"),
        "minimum_history_sessions": 1,
        "require_target_date": True,
        "expected_codes": ("600000.SH",),
    }
    values.update(updates)
    return AcquisitionGroupContract(**values)


def _request(**updates) -> AcquisitionRequest:
    values = {
        "run_id": "formal-20260710-001",
        "trade_date": TRADE_DATE,
        "report_cutoff": CUTOFF,
        "target_codes": ("600000.SH",),
        "contract_version": "formal-v1",
    }
    values.update(updates)
    return AcquisitionRequest(**values)


def _record(**updates) -> dict[str, object]:
    values: dict[str, object] = {
        "trade_date": TRADE_DATE,
        "ts_code": "600000.SH",
        "open": 10.0,
        "high": 11.0,
        "low": 9.5,
        "close": 10.5,
        "vol": 1_000.0,
        "amount": 10_500.0,
        "pe_ttm": 8.2,
        "pe_ttm_null_reason": None,
    }
    values.update(updates)
    return values


def _payload(*records: dict[str, object], **updates) -> AcquisitionPayload:
    values = {
        "group_id": AcquisitionGroupId.MARKET_DECISION,
        "route_id": "tushare-market-complete-v1",
        "route_kind": RouteKind.PRIMARY,
        "trade_date": TRADE_DATE,
        "fetched_at": CUTOFF,
        "source_names": ("tushare.daily", "tushare.daily_basic"),
        "records": tuple(records or (_record(),)),
        "covered_dates": (TRADE_DATE,),
        "field_coverage": {name: True for name in _contract().required_fields},
        "unit_metadata": {"vol": "shares", "amount": "CNY"},
        "adjustment_basis": "unadjusted",
        "publication_times": {},
    }
    values.update(updates)
    return AcquisitionPayload(**values)


def test_july_10_window_is_exactly_82_official_sessions():
    assert len(JULY_10_OFFICIAL_SESSIONS) == 82
    assert JULY_10_OFFICIAL_SESSIONS[0] == date(2026, 3, 12)
    assert JULY_10_OFFICIAL_SESSIONS[-1] == TRADE_DATE
    assert tuple(sorted(set(JULY_10_OFFICIAL_SESSIONS))) == JULY_10_OFFICIAL_SESSIONS


def test_group_validator_accepts_complete_current_payload():
    result = validate_group_payload(_contract(), _request(), _payload())

    assert result.complete is True
    assert result.reasons == ()
    assert result.covered_codes == ("600000.SH",)
    assert result.covered_dates == (TRADE_DATE,)


def test_group_validator_rejects_missing_required_column_even_when_null_is_legitimate():
    record = _record()
    del record["pe_ttm"]

    result = validate_group_payload(_contract(), _request(), _payload(record))

    assert result.complete is False
    assert "missing_field:pe_ttm:row=0" in result.reasons


def test_group_validator_accepts_classified_legitimate_null():
    payload = _payload(_record(pe_ttm=None, pe_ttm_null_reason="loss_making"))

    result = validate_group_payload(_contract(), _request(), payload)

    assert result.complete is True


def test_group_validator_rejects_duplicate_keys_nonfinite_ohlc_and_negative_amount():
    first = _record(high=9.0, close=nan, amount=-1.0)
    result = validate_group_payload(_contract(), _request(), _payload(first, dict(first)))

    assert result.complete is False
    assert any(reason.startswith("duplicate_key:") for reason in result.reasons)
    assert any(reason.startswith("invalid_ohlc:") for reason in result.reasons)
    assert any(reason.startswith("nonfinite_value:") for reason in result.reasons)
    assert any(reason.startswith("negative_value:amount:") for reason in result.reasons)


def test_group_validator_requires_target_date_and_expected_code_coverage():
    prior_date = date(2026, 7, 9)
    contract = _contract(expected_codes=("600000.SH", "000001.SZ"))
    payload = _payload(
        _record(trade_date=prior_date),
        covered_dates=(prior_date,),
    )

    result = validate_group_payload(contract, _request(), payload)

    assert result.complete is False
    assert "missing_target_date:2026-07-10" in result.reasons
    assert "missing_code:600000.SH:2026-07-10" in result.reasons
    assert "missing_code:000001.SZ:2026-07-10" in result.reasons


def test_payload_hash_is_order_stable_and_route_bound():
    second = _record(ts_code="000001.SZ")
    a = _payload(_record(), second)
    b = _payload(second, _record())
    backup = _payload(
        _record(),
        second,
        route_id="eastmoney-market-complete-v1",
        route_kind=RouteKind.BACKUP,
        source_names=("eastmoney.market",),
    )

    assert a.content_hash == b.content_hash
    assert a.content_hash != backup.content_hash


def test_point_in_time_payload_rejects_publication_after_report_cutoff():
    payload = _payload(
        publication_times={
            "600000.SH:financial": datetime(2026, 7, 10, 16, 1, tzinfo=SHANGHAI)
        }
    )

    result = validate_group_payload(_contract(), _request(), payload)

    assert result.complete is False
    assert "look_ahead:600000.SH:financial" in result.reasons
