from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from stock_analyzer.data.readiness import (
    AcquisitionGroupId,
    AcquisitionPayload,
    GroupValidation,
    RouteKind,
)
from stock_analyzer.storage.formal_parquet import FormalParquetCorruption
from stock_analyzer.storage.formal_warehouse import FormalWarehouse


SHANGHAI = ZoneInfo("Asia/Shanghai")
TARGET = date(2026, 7, 10)
CUTOFF = datetime(2026, 7, 10, 16, 0, tzinfo=SHANGHAI)
VALID = GroupValidation(complete=True)


def _payload(
    trade_date: date = TARGET,
    *,
    close: float = 10.5,
    route_kind: RouteKind = RouteKind.PRIMARY,
    publication_time: datetime | None = None,
) -> AcquisitionPayload:
    return AcquisitionPayload(
        group_id=AcquisitionGroupId.MARKET_DECISION,
        route_id=f"{route_kind.value}.market.v1",
        route_kind=route_kind,
        trade_date=trade_date,
        fetched_at=CUTOFF,
        source_names=(f"{route_kind.value}.daily",),
        records=(
            {
                "record_type": "equity_bar",
                "trade_date": trade_date,
                "ts_code": "600000.SH",
                "close": close,
            },
        ),
        covered_dates=(trade_date,),
        coverage_codes=("600000.SH",),
        coverage_proven=True,
        field_coverage={"trade_date": True, "ts_code": True, "close": True},
        publication_times=(
            {"600000.SH:event": publication_time}
            if publication_time is not None
            else {}
        ),
        contract_version="formal-v2",
    )


def test_group_version_round_trip_uses_duckdb_and_parquet_only(tmp_path):
    warehouse = FormalWarehouse(tmp_path / "local_warehouse")
    payload = _payload()

    manifest = warehouse.save_group_version(payload, VALID)
    loaded = warehouse.read_group_version(manifest.version_id)

    assert loaded == payload
    assert loaded.content_hash == manifest.content_hash
    assert warehouse.verify_group_version(manifest.version_id).complete is True
    assert warehouse.list_group_versions() == (manifest,)
    assert not list((tmp_path / "local_warehouse").glob("formal_evidence/**/*.json"))
    assert list((tmp_path / "local_warehouse/parquet/formal").glob("**/*.parquet"))


def test_incomplete_group_creates_no_catalog_or_parquet(tmp_path):
    warehouse = FormalWarehouse(tmp_path / "local_warehouse")

    with pytest.raises(ValueError, match="incomplete"):
        warehouse.save_group_version(
            _payload(),
            GroupValidation(complete=False, reasons=("missing",)),
        )

    assert warehouse.list_group_versions() == ()
    assert not list((tmp_path / "local_warehouse/parquet/formal").glob("**/*.parquet"))


def test_canonical_replacement_keeps_both_immutable_versions(tmp_path):
    warehouse = FormalWarehouse(tmp_path / "local_warehouse")
    first = warehouse.save_group_version(_payload(close=10.5), VALID)
    second = warehouse.save_group_version(_payload(close=11.5), VALID)

    warehouse.set_canonical(first.group_id, TARGET, first.version_id)
    warehouse.set_canonical(second.group_id, TARGET, second.version_id)

    assert warehouse.canonical_manifest(first.group_id, TARGET) == second
    assert warehouse.group_version_manifest(first.version_id) == first
    assert warehouse.read_group_version(first.version_id) is not None
    assert len(warehouse.list_group_versions()) == 2


def test_prior_session_cache_excludes_target_date(tmp_path):
    warehouse = FormalWarehouse(tmp_path / "local_warehouse")
    prior_date = date(2026, 7, 9)
    prior = warehouse.save_group_version(_payload(prior_date), VALID)
    current = warehouse.save_group_version(_payload(TARGET, close=12.0), VALID)
    warehouse.set_canonical(prior.group_id, prior_date, prior.version_id)
    warehouse.set_canonical(current.group_id, TARGET, current.version_id)

    history = warehouse.load_prior_sessions(
        AcquisitionGroupId.MARKET_DECISION,
        TARGET,
        82,
    )

    assert [payload.trade_date for payload in history] == [prior_date]


def test_report_cutoff_rejects_look_ahead_version(tmp_path):
    warehouse = FormalWarehouse(tmp_path / "local_warehouse")
    future = datetime(2026, 7, 10, 16, 1, tzinfo=SHANGHAI)
    manifest = warehouse.save_group_version(
        _payload(publication_time=future),
        VALID,
    )

    assert warehouse.read_group_version(manifest.version_id, report_cutoff=CUTOFF) is None
    assert warehouse.read_group_version(
        manifest.version_id,
        report_cutoff=datetime(2026, 7, 10, 16, 2, tzinfo=SHANGHAI),
    ) is not None


def test_strict_group_audit_rejects_corrupt_parquet(tmp_path):
    warehouse = FormalWarehouse(tmp_path / "local_warehouse")
    manifest = warehouse.save_group_version(_payload(), VALID)
    file_row = warehouse.version_files(manifest.version_id)[0]
    path = warehouse.root / file_row.relative_path
    path.write_bytes(path.read_bytes() + b"corrupt")

    with pytest.raises(FormalParquetCorruption, match="hash"):
        warehouse.verify_group_version(manifest.version_id, strict_hashes=True)


def test_catalog_failure_leaves_no_visible_version(tmp_path, monkeypatch):
    warehouse = FormalWarehouse(tmp_path / "local_warehouse")

    def fail_insert(*args, **kwargs):
        raise RuntimeError("injected catalog failure")

    monkeypatch.setattr(warehouse, "_insert_version", fail_insert)

    with pytest.raises(RuntimeError, match="injected"):
        warehouse.save_group_version(_payload(), VALID)

    assert warehouse.list_group_versions() == ()
