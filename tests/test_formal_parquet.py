from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from stock_analyzer.data.readiness import (
    AcquisitionGroupId,
    AcquisitionPayload,
    RouteKind,
)
from stock_analyzer.storage.formal_parquet import (
    FormalParquetConflict,
    FormalParquetCorruption,
    prepare_version_files,
    promote_prepared_version,
    read_version_records,
    verify_prepared_version,
    verify_version_files,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")
TARGET = date(2026, 7, 10)


def _payload() -> AcquisitionPayload:
    return AcquisitionPayload(
        group_id=AcquisitionGroupId.MARKET_DECISION,
        route_id="tushare.market.v1",
        route_kind=RouteKind.PRIMARY,
        trade_date=TARGET,
        fetched_at=datetime(2026, 7, 10, 16, 0, tzinfo=SHANGHAI),
        source_names=("tushare.daily", "tushare.daily_basic"),
        records=(
            {
                "record_type": "equity_bar",
                "trade_date": date(2026, 7, 9),
                "ts_code": "600000.SH",
                "close": 10,
                "note": None,
                "tags": ["bank", "value"],
            },
            {
                "record_type": "equity_bar",
                "trade_date": TARGET,
                "ts_code": "600000.SH",
                "close": 10.5,
            },
            {
                "record_type": "daily_basic",
                "trade_date": TARGET,
                "ts_code": "600000.SH",
                "turnover_rate": 1.2,
                "details": {"currency": "CNY"},
            },
            {
                "record_type": "index_bar",
                "trade_date": TARGET,
                "ts_code": "000001.SH",
                "close": 3500.0,
            },
        ),
        covered_dates=(date(2026, 7, 9), TARGET),
        coverage_codes=("600000.SH",),
        coverage_proven=True,
        field_coverage={"trade_date": True, "close": True},
        unit_metadata={"amount": "CNY"},
        adjustment_basis="unadjusted",
        contract_version="formal-v2",
    )


def test_prepare_market_version_partitions_by_actual_trade_date(tmp_path):
    prepared = prepare_version_files(tmp_path, _payload())

    paths = {item.relative_path.as_posix() for item in prepared.files}
    assert any("market_daily/trade_date=2026-07-09" in path for path in paths)
    assert any("market_daily/trade_date=2026-07-10" in path for path in paths)
    assert any("daily_basic/trade_date=2026-07-10" in path for path in paths)
    assert not any("daily_basic/trade_date=2026-07-09" in path for path in paths)
    assert any("index_daily/trade_date=2026-07-10" in path for path in paths)


def test_parquet_round_trip_preserves_records_and_payload_hash(tmp_path):
    payload = _payload()
    prepared = prepare_version_files(tmp_path, payload)
    verify_prepared_version(prepared, payload)
    files = promote_prepared_version(tmp_path, prepared)

    records = read_version_records(tmp_path, files)
    rebuilt = payload.model_copy(update={"records": records})

    assert records == payload.records
    assert rebuilt.content_hash == payload.content_hash
    assert "note" in records[0] and records[0]["note"] is None
    assert "note" not in records[1]
    assert isinstance(records[0]["close"], int)
    assert isinstance(records[1]["close"], float)


def test_promoting_same_version_rejects_changed_immutable_file(tmp_path):
    payload = _payload()
    first = prepare_version_files(tmp_path, payload)
    files = promote_prepared_version(tmp_path, first)
    (tmp_path / files[0].relative_path).write_bytes(b"changed")
    second = prepare_version_files(tmp_path, payload)

    with pytest.raises(FormalParquetConflict, match="immutable"):
        promote_prepared_version(tmp_path, second)


def test_strict_verification_rejects_corrupt_file(tmp_path):
    prepared = prepare_version_files(tmp_path, _payload())
    files = promote_prepared_version(tmp_path, prepared)
    path = tmp_path / files[-1].relative_path
    path.write_bytes(path.read_bytes() + b"x")

    with pytest.raises(FormalParquetCorruption, match="hash"):
        verify_version_files(tmp_path, files, strict_hashes=True)


def test_unknown_record_type_fails_closed(tmp_path):
    payload = _payload().model_copy(
        update={"records": ({"record_type": "mystery", "trade_date": TARGET},)}
    )

    with pytest.raises(ValueError, match="unsupported formal record type"):
        prepare_version_files(tmp_path, payload)


def test_empty_payload_needs_no_parquet_file(tmp_path):
    payload = _payload().model_copy(update={"records": ()})

    prepared = prepare_version_files(tmp_path, payload)

    assert prepared.files == ()
    assert read_version_records(tmp_path, ()) == ()
