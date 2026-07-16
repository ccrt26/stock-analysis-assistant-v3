from __future__ import annotations

import hashlib
import json
import tempfile
import copy
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from stock_analyzer.analysis.hotspot_features import HOTSPOT_FORMULA_VERSION
from stock_analyzer.analysis.market_context_features import (
    MARKET_CONTEXT_FORMULA_VERSION,
)
from stock_analyzer.analysis.stock_context_features import STOCK_CONTEXT_FORMULA_VERSION
from stock_analyzer.data.research_contracts import FactBatch, ResearchDatasetId
from stock_analyzer.evaluation.v3_backtest.contracts import DiscoveryRoute
from stock_analyzer.evaluation.v3_backtest import routes as routes_module
from stock_analyzer.evaluation.v3_backtest.routes import (
    VerifiedRouteScanBatch,
    build_frozen_universe_catalog,
    build_route_fact_plan,
    build_route_window_policy,
    canonical_route_input_hash,
    derive_declared_route_windows,
    require_verified_route_scan_batch,
    scan_routes,
)
from stock_analyzer.evaluation.v3_backtest.snapshots import (
    FormationFactView,
    FormationFeatureView,
    FormationSnapshot,
    materialize_formation_snapshot,
)
from stock_analyzer.storage.research_derived import DerivedFeatureStore
from stock_analyzer.storage.research_query import ResearchQuery
from stock_analyzer.storage.research_warehouse import ResearchWarehouse


SHANGHAI = ZoneInfo("Asia/Shanghai")
FORMATION_DATE = date(2026, 7, 15)
CUTOFF = datetime(2026, 7, 15, 23, 59, 59, tzinfo=SHANGHAI)
REPORT_PERIOD = date(2026, 6, 30)
SHA256 = "a" * 64


def test_singleton_manifest_partition_can_supply_omitted_physical_partition_column():
    records = ({"ts_code": "000001.SZ", "industry_system": "SW2021"},)

    grouped, error = routes_module._partition_records(
        "industry_member", records, ("SW2021",)
    )

    assert error is None
    assert grouped == {"SW2021": records}


def test_omitted_physical_partition_column_still_fails_for_multiple_partitions():
    records = ({"ts_code": "000001.SZ", "industry_system": "SW2021"},)

    grouped, error = routes_module._partition_records(
        "industry_member", records, ("SW2021", "SW2024")
    )

    assert grouped == {}
    assert error == "industry_member: missing partition field classification_version"


def universe_catalog():
    return _default_controlled_bundle(FORMATION_DATE)[2]


def route_plan(*, catalog=None):
    return build_route_fact_plan(
        formation_date=FORMATION_DATE,
        earnings_report_periods=(REPORT_PERIOD,),
        event_start=date(2026, 5, 20),
        universe_catalog=catalog or universe_catalog(),
    )


def policy(*, tail_fraction: float = 0.4, catalog=None):
    return build_route_window_policy(
        formation_date=FORMATION_DATE,
        fact_plan=route_plan(catalog=catalog),
        earnings_report_periods=(REPORT_PERIOD,),
        event_start=date(2026, 5, 20),
        price_absolute_tail_fraction=tail_fraction,
    )


def hotspot_row(
    group_type: str,
    group_code: str,
    *,
    complete: bool = True,
) -> dict[str, Any]:
    row = {
        "analysis_date": FORMATION_DATE,
        "group_type": group_type,
        "group_code": group_code,
        "relative_return_20d": 0.08,
        "median_return_20d": 0.06,
        "breadth_20d": 0.7,
        "turnover_share_average_20d": 0.02,
        "top3_positive_contribution_1d": 0.4,
        "high_volume_low_progress_flag": True,
        "upper_wick_reversal_flag": False,
        "narrow_participation_flag": False,
        "turnover_return_divergence_flag": False,
        "coverage_status": "complete_with_declared_gaps",
    }
    if not complete:
        row.pop("turnover_share_average_20d")
    return row


def fact_rows() -> dict[str, tuple[dict[str, Any], ...]]:
    controlled_rows = _default_controlled_bundle(FORMATION_DATE)[3]
    rows = {
        "industry_member": controlled_rows["industry_member"],
        "theme_member": controlled_rows["theme_member"],
        "earnings_forecast": (
            {
                "ts_code": "000003.SZ",
                "report_period": REPORT_PERIOD,
                "announcement_type": "预增",
                "ann_month": "2026-05",
                "p_change_min": 30,
                "net_profit_min": 100_000_000,
                "available_at": datetime(2026, 5, 30, 18, tzinfo=SHANGHAI),
                "evidence_id": "shared-disclosure",
            },
        ),
        "earnings_express": (
            {
                "ts_code": "000004.SZ",
                "report_period": REPORT_PERIOD,
                "operating_revenue": 2_000_000_000,
                "ann_month": "2026-06",
                "net_profit": 200_000_000,
                "available_at": datetime(2026, 6, 28, 18, tzinfo=SHANGHAI),
            },
        ),
        "income_statement": (
            {
                "ts_code": "000005.SZ",
                "report_period": REPORT_PERIOD,
                "total_revenue": 3_000_000_000,
                "net_profit": 300_000_000,
                "available_at": datetime(2026, 7, 10, 18, tzinfo=SHANGHAI),
            },
        ),
        "announcement": (
            {
                "announcement_id": "shared-disclosure",
                "ts_code": "000003.SZ",
                "announcement_time": datetime(2026, 5, 25, 18, tzinfo=SHANGHAI),
                "announcement_month": "2026-05",
                "available_at": datetime(2026, 5, 25, 18, tzinfo=SHANGHAI),
                "title": "重大合同公告",
                "url": "https://example.invalid/a",
                "pdf_path": "a.pdf",
                "candidate_event_types": ("major_contract",),
                "classification_is_fact": False,
            },
            {
                "announcement_id": "A-JUNE",
                "ts_code": "000006.SZ",
                "announcement_time": datetime(2026, 6, 20, 18, tzinfo=SHANGHAI),
                "announcement_month": "2026-06",
                "available_at": datetime(2026, 6, 20, 18, tzinfo=SHANGHAI),
                "title": "回购进展公告",
                "url": "https://example.invalid/b",
                "pdf_path": "b.pdf",
                "candidate_event_types": ("repurchase",),
                "classification_is_fact": False,
            },
            {
                "announcement_id": "A-JULY",
                "ts_code": "000007.SZ",
                "announcement_time": datetime(2026, 7, 12, 18, tzinfo=SHANGHAI),
                "announcement_month": "2026-07",
                "available_at": datetime(2026, 7, 12, 18, tzinfo=SHANGHAI),
                "title": "批准公告",
                "url": "https://example.invalid/c",
                "pdf_path": "c.pdf",
                "candidate_event_types": ("approval",),
                "classification_is_fact": False,
            },
        ),
        "industry_daily": controlled_rows["industry_daily"],
        "main_business": (),
        "repurchase": (),
        "balance_sheet": (),
        "cash_flow": (),
    }
    return {
        dataset: (
            tuple(dataset_rows)
            if dataset in {"industry_member", "theme_member", "industry_daily"}
            else tuple(
                {
                    **row,
                    "business_key_hash": _json_hash((dataset, index, "business")),
                    "payload_hash": _json_hash((dataset, index, row)),
                    "revision_no": 1,
                }
                for index, row in enumerate(dataset_rows)
            )
        )
        for dataset, dataset_rows in rows.items()
    }


def feature_rows() -> dict[str, tuple[dict[str, Any], ...]]:
    return {
        "market_context": (
            {
                "analysis_date": FORMATION_DATE,
                "market_regime": "balanced",
                "coverage_status": "complete_with_declared_gaps",
            },
        ),
        "sector_hotspot": (
            hotspot_row("industry", "I1"),
            hotspot_row("theme", "T1"),
            hotspot_row("industry", "I2", complete=False),
        ),
        "stock_trading_context": tuple(
            {
                "analysis_date": FORMATION_DATE,
                "ts_code": f"00010{index}.SZ",
                "relative_return_20d": value,
                "coverage_status": "complete_with_declared_gaps",
            }
            for index, value in enumerate((0.01, -0.02, 0.03, 0.2, -0.5))
        ),
    }


def input_manifest(
    rows: dict[str, tuple[dict[str, Any], ...]],
    *,
    omit: tuple[tuple[str, str], ...] = (),
) -> dict[str, Any]:
    omitted = set(omit)
    items = []
    attested = {
        (item["dataset"], item["partition"]): item
        for item in _default_controlled_bundle(FORMATION_DATE)[0].source_entries()
    }
    for dataset, partitions in route_plan().items():
        if dataset in {"sector_hotspot", "stock_trading_context"}:
            continue
        for partition in partitions:
            if (dataset, partition) in omitted:
                continue
            if (dataset, partition) in attested:
                items.append(dict(attested[(dataset, partition)]))
                continue
            partition_rows = tuple(
                row
                for row in rows[dataset]
                if _row_partition(dataset, row) == partition
            )
            resolved = len(partition_rows)
            items.append(
                {
                    "dataset": dataset,
                    "partition": partition,
                    "row_count": resolved,
                    "resolved_row_count": resolved,
                    "resolved_content_hash": _canonical_fact_hash(partition_rows),
                }
            )
    return _hashed_manifest(items)


def _row_partition(dataset: str, row: dict[str, Any]) -> str:
    if dataset == "industry_member":
        return str(row["classification_version"])
    if dataset == "theme_member":
        return str(row["catalog_version"])
    if dataset in {"earnings_forecast", "earnings_express", "announcement", "repurchase"}:
        stamp = row.get("announcement_time") or row.get("available_at")
        return stamp.date().strftime("%Y-%m")
    if dataset in {
        "income_statement",
        "balance_sheet",
        "cash_flow",
        "main_business",
    }:
        return str(row.get("report_period", REPORT_PERIOD))
    if dataset == "industry_daily":
        value = row.get("trade_date", FORMATION_DATE)
        if isinstance(value, (date, datetime, pd.Timestamp)):
            return pd.Timestamp(value).date().isoformat()
        return str(value)
    raise AssertionError(dataset)


class PublicFacts:
    def __init__(
        self,
        rows: dict[str, tuple[dict[str, Any], ...]],
        manifest: dict[str, Any],
    ) -> None:
        self.rows = rows
        view_payload = {
            "source_snapshot": manifest,
            "effective_date": FORMATION_DATE.isoformat(),
            "effective_rows": [
                {"dataset": key, "row_count": len(value)}
                for key, value in sorted(rows.items())
            ],
        }
        self.manifest = {
            **view_payload,
            "view_manifest_hash": hashlib.sha256(
                json.dumps(
                    view_payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                ).encode("utf-8")
            ).hexdigest(),
        }
        self.calls: list[str] = []

    def dataset(self, dataset_id: str):
        self.calls.append(str(dataset_id))
        return self.rows[str(dataset_id)]


class PublicFeatures:
    def __init__(self, rows: dict[str, tuple[dict[str, Any], ...]]) -> None:
        self.rows = rows
        self.calls: list[str] = []

    def read(self, feature_set: str):
        self.calls.append(feature_set)
        return self.rows[feature_set]


@dataclass
class PublicSnapshot:
    facts: PublicFacts
    features: PublicFeatures
    analysis_date: date = FORMATION_DATE
    as_of: datetime = CUTOFF
    market_rows: int = 1
    sector_rows: int = 3
    stock_rows: int = 5
    limitations: tuple[str, ...] = ("fixture limitation",)
    cache_key: str = SHA256


def snapshot(
    *,
    omit: tuple[tuple[str, str], ...] = (),
) -> PublicSnapshot:
    facts = fact_rows()
    for dataset, partition in omit:
        facts[dataset] = tuple(
            row for row in facts[dataset] if _row_partition(dataset, row) != partition
        )
    return PublicSnapshot(
        PublicFacts(facts, input_manifest(facts, omit=omit)),
        PublicFeatures(feature_rows()),
    )


def manifest_for(manifests, route: DiscoveryRoute):
    return next(item for item in manifests if item.route is route)


def _plain_record(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain_record(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_plain_record(item) for item in value]
    return value


def test_scan_returns_opaque_verified_batch_with_security_scoped_lead_ledger():
    formation = snapshot()
    frozen = policy()

    batch = scan_routes(formation, frozen)
    manifests, hypotheses = batch
    verified = require_verified_route_scan_batch(batch)
    hypothesis = verified.hypothesis_for_security("000003.SZ")
    security_manifests = verified.manifests_for_security("000003.SZ")
    lead_members = verified.lead_members("000003.SZ")

    assert isinstance(batch, VerifiedRouteScanBatch)
    assert len(manifests) == 6
    assert len({item.security_id for item in hypotheses}) == len(hypotheses)
    assert verified is batch
    assert verified.snapshot is formation
    assert verified.window_policy is frozen
    assert hypothesis.security_id == "000003.SZ"
    assert len(security_manifests) == 6
    assert {item.route for item in security_manifests} == set(DiscoveryRoute)
    assert lead_members
    assert all(item.security_id == "000003.SZ" for item in lead_members)
    assert len(
        {
            (item.route, item.evidence_id, item.security_id)
            for item in lead_members
        }
    ) == len(lead_members)
    assert all(len(item.input_hash) == 64 for item in lead_members)
    assert all(
        item.input_hash == canonical_route_input_hash(item.route_input_record)
        for item in lead_members
    )
    assert all(
        item.route_manifest_input_hash
        == manifest_for(manifests, item.route).input_hash
        for item in lead_members
    )
    with pytest.raises(TypeError):
        lead_members[0].route_input_record["evidence"]["evidence_id"] = "altered"
    assert {
        (
            item.route,
            item.evidence_id,
            item.usable_for_decision,
            item.needs_deep_read,
        )
        for item in lead_members
    } == {
        (
            item.route,
            item.evidence_id,
            item.usable_for_decision,
            item.needs_deep_read,
        )
        for item in hypothesis.evidence
    }


def test_batch_exports_complete_frozen_recomputable_receipt_without_provenance():
    batch = scan_routes(snapshot(), policy())
    record = routes_module.batch_receipt_record(batch)

    assert record["receipt_version"] == "v3-route-scan-receipt-v1"
    assert len(record["snapshot_content_hash"]) == 64
    assert record["snapshot_scope"] == {
        "feature_sets": (
            "market_context",
            "sector_hotspot",
            "stock_trading_context",
        ),
        "limitations_bound": True,
    }
    assert len(record["manifests"]) == 6
    assert len(record["manifest_input_records"]) == 6
    assert record["hypotheses"]
    assert record["lead_ledger"]
    assert batch.receipt_hash == batch.batch_hash
    assert batch.receipt_hash == routes_module.canonical_batch_receipt_hash(record)
    json.dumps(_plain_record(record), ensure_ascii=False, sort_keys=True)
    with pytest.raises(TypeError):
        record["policy"]["policy_hash"] = "0" * 64
    with pytest.raises(ValueError, match="registered scan provenance"):
        require_verified_route_scan_batch(record)


def test_each_batch_receipt_section_changes_the_independent_canonical_hash():
    batch = scan_routes(snapshot(), policy())
    record = routes_module.batch_receipt_record(batch)
    expected_hash = batch.receipt_hash

    mutations = (
        lambda item: item.__setitem__("snapshot_content_hash", "0" * 64),
        lambda item: item["snapshot_scope"].__setitem__(
            "limitations_bound", False
        ),
        lambda item: item["policy"].__setitem__(
            "universe_catalog_hash", "0" * 64
        ),
        lambda item: item["manifests"][0].__setitem__(
            "triggered_records", item["manifests"][0]["triggered_records"] + 1
        ),
        lambda item: item["manifest_input_records"][0]["datasets"].__setitem__(
            0, "0" * 64
        ),
        lambda item: item["hypotheses"][0].__setitem__(
            "security_id", "ALTERED"
        ),
        lambda item: item["lead_ledger"][0].__setitem__(
            "input_hash", "0" * 64
        ),
    )
    for mutate in mutations:
        altered = _plain_record(record)
        mutate(altered)
        assert routes_module.canonical_batch_receipt_hash(altered) != expected_hash


def test_verified_batch_cannot_be_handcrafted_or_copied():
    manifests, hypotheses = scan_routes(snapshot(), policy())

    with pytest.raises(ValueError, match="scan_routes"):
        VerifiedRouteScanBatch(
            snapshot=snapshot(),
            window_policy=policy(),
            manifests=manifests,
            hypotheses=hypotheses,
            lead_members=(),
        )

    copied = copy.copy(scan_routes(snapshot(), policy()))
    with pytest.raises(ValueError, match="registered scan provenance"):
        require_verified_route_scan_batch(copied)


@pytest.mark.parametrize("mutation", ("route", "evidence", "count", "input_hash"))
def test_verified_batch_rejects_altered_manifest_hypothesis_or_receipt_fields(
    mutation: str,
):
    batch = scan_routes(snapshot(), policy())
    manifests, hypotheses = batch
    if mutation == "route":
        altered = manifests[0].model_copy(update={"route": DiscoveryRoute.EARNINGS})
        object.__setattr__(
            batch,
            "_VerifiedRouteScanBatch__manifests",
            (altered, *manifests[1:]),
        )
    elif mutation == "count":
        altered = manifests[0].model_copy(
            update={"triggered_records": manifests[0].triggered_records + 1}
        )
        object.__setattr__(
            batch,
            "_VerifiedRouteScanBatch__manifests",
            (altered, *manifests[1:]),
        )
    elif mutation == "input_hash":
        altered = manifests[0].model_copy(update={"input_hash": "0" * 64})
        object.__setattr__(
            batch,
            "_VerifiedRouteScanBatch__manifests",
            (altered, *manifests[1:]),
        )
    else:
        hypothesis = hypotheses[0]
        altered_evidence = replace(
            hypothesis.evidence[0],
            evidence_id=f"altered:{hypothesis.evidence[0].evidence_id}",
        )
        altered_hypothesis = replace(
            hypothesis,
            evidence=(altered_evidence, *hypothesis.evidence[1:]),
        )
        object.__setattr__(
            batch,
            "_VerifiedRouteScanBatch__hypotheses",
            (altered_hypothesis, *hypotheses[1:]),
        )

    with pytest.raises(ValueError, match="scan batch .* mismatch"):
        require_verified_route_scan_batch(batch)


def test_verified_batch_rejects_cross_scan_component_mixing_even_when_values_match():
    first = scan_routes(snapshot(), policy())
    second = scan_routes(snapshot(), policy())
    _, second_hypotheses = second

    object.__setattr__(
        first,
        "_VerifiedRouteScanBatch__hypotheses",
        second_hypotheses,
    )

    with pytest.raises(ValueError, match="scan batch component identity mismatch"):
        require_verified_route_scan_batch(first)


@pytest.mark.parametrize("mutation", ("market_context", "limitations"))
def test_verified_batch_binds_all_downstream_snapshot_content(mutation: str):
    formation = snapshot()
    batch = scan_routes(formation, policy())

    if mutation == "market_context":
        row = formation.features.rows["market_context"][0]
        formation.features.rows["market_context"] = (
            {**row, "market_regime": "altered-after-scan"},
        )
    else:
        formation.limitations = ("altered-after-scan",)

    with pytest.raises(ValueError, match="route scan batch snapshot hash mismatch"):
        require_verified_route_scan_batch(batch)


def test_each_route_manifest_exports_a_canonical_recomputable_input_record():
    batch = scan_routes(snapshot(), policy())
    manifests, _ = batch

    for manifest in manifests:
        record = batch.route_manifest_input_record(manifest)
        assert record["route"] == manifest.route.value
        assert record["cutoff"] == manifest.cutoff.isoformat()
        assert manifest.input_hash == (
            routes_module.canonical_route_manifest_input_hash(record)
        )
        assert record["datasets"]
        assert all(len(value) == 64 for value in record["datasets"])
        with pytest.raises(TypeError):
            record["policy"]["forged"] = ()


@pytest.mark.parametrize(
    ("security_id", "field_name", "altered"),
    (
        (
            "000103.SZ",
            "available_at",
            datetime(2020, 1, 1, tzinfo=SHANGHAI),
        ),
        (
            "000003.SZ",
            "fact_summary",
            "altered summary outside canonical record",
        ),
    ),
)
def test_verified_lead_rejects_public_field_divergence_from_canonical_record(
    security_id: str,
    field_name: str,
    altered: Any,
):
    batch = scan_routes(snapshot(), policy())
    member = batch.lead_members(security_id)[0]
    assert getattr(member, field_name) is None
    object.__setattr__(member, field_name, altered)

    with pytest.raises(ValueError, match="route scan lead canonical record mismatch"):
        require_verified_route_scan_batch(batch)


def test_plan_builder_freezes_real_datasets_and_derives_complete_month_windows():
    plan = route_plan()
    frozen = policy()

    assert frozen.route_partitions[DiscoveryRoute.HOTSPOT] == {
        "sector_hotspot": ("2026-07-15",),
        "industry_member": ("sw2021-v1",),
        "theme_member": ("controlled-theme-v1",),
    }
    assert frozen.route_partitions[DiscoveryRoute.EARNINGS] == {
        "earnings_forecast": (
            "2026-01",
            "2026-02",
            "2026-03",
            "2026-04",
            "2026-05",
            "2026-06",
            "2026-07",
        ),
        "earnings_express": (
            "2026-01",
            "2026-02",
            "2026-03",
            "2026-04",
            "2026-05",
            "2026-06",
            "2026-07",
        ),
        "income_statement": ("2026-06-30",),
    }
    assert frozen.route_partitions[DiscoveryRoute.COMPANY_EVENT] == {
        "announcement": ("2026-05", "2026-06", "2026-07")
    }
    assert frozen.route_partitions[DiscoveryRoute.PRICE_ANOMALY] == {
        "stock_trading_context": ("2026-07-15",)
    }
    assert set(plan) == {
        dataset
        for datasets in frozen.route_partitions.values()
        for dataset in datasets
    }.difference({"sector_hotspot", "stock_trading_context"})


def test_price_tail_fraction_is_required_and_strictly_bounded():
    with pytest.raises(TypeError):
        build_route_window_policy(
            formation_date=FORMATION_DATE,
            fact_plan=route_plan(),
            earnings_report_periods=(REPORT_PERIOD,),
            event_start=date(2026, 5, 20),
        )
    for invalid in (0, -0.1, 1.1):
        with pytest.raises(ValueError, match="tail fraction"):
            policy(tail_fraction=invalid)


def test_preregistered_window_inputs_derive_45_days_four_past_and_two_future_quarters():
    event_start, reports = derive_declared_route_windows(
        formation_date=FORMATION_DATE,
        event_lookback_calendar_days=45,
        completed_quarter_count=4,
        future_quarter_count=2,
    )

    assert event_start == date(2026, 6, 1)
    assert reports == (
        date(2025, 9, 30),
        date(2025, 12, 31),
        date(2026, 3, 31),
        date(2026, 6, 30),
        date(2026, 9, 30),
        date(2026, 12, 31),
    )
    assert policy(tail_fraction=0.05).price_absolute_tail_fraction == 0.05

    plan = build_route_fact_plan(
        formation_date=FORMATION_DATE,
        earnings_report_periods=reports,
        event_start=event_start,
        universe_catalog=universe_catalog(),
    )
    assert plan["income_statement"] == (
        "2025-09-30",
        "2025-12-31",
        "2026-03-31",
        "2026-06-30",
    )
    assert plan["balance_sheet"] == plan["income_statement"]
    assert plan["cash_flow"] == plan["income_statement"]
    assert plan["main_business"] == plan["income_statement"]


def test_public_snapshot_manifest_drives_requested_actual_expected_and_missing():
    missing_partition = ("announcement", "2026-06")
    formation = snapshot(omit=(missing_partition,))

    manifests, _ = scan_routes(formation, policy())
    event = manifest_for(manifests, DiscoveryRoute.COMPANY_EVENT)

    assert event.requested_partitions == (
        "announcement:2026-05",
        "announcement:2026-06",
        "announcement:2026-07",
    )
    assert event.actual_partitions == (
        "announcement:2026-05",
        "announcement:2026-07",
    )
    assert "announcement:2026-06" in event.missing
    assert event.expected_records == 2
    assert event.scanned_records == 2
    assert event.triggered_records == 0
    assert any("fail closed" in reason for reason in event.missing)


def test_effective_row_manifest_mismatch_is_an_explicit_coverage_gap():
    formation = snapshot()
    for item in formation.facts.manifest["effective_rows"]:
        if item["dataset"] == "announcement":
            item["row_count"] = 99
    _refresh_fact_manifest_hashes(formation)

    manifests, _ = scan_routes(formation, policy())
    event = manifest_for(manifests, DiscoveryRoute.COMPANY_EVENT)

    assert any("effective manifest" in item for item in event.missing)


def test_all_three_earnings_types_and_all_event_months_are_scanned():
    formation = snapshot()

    manifests, hypotheses = scan_routes(formation, policy())
    earnings = manifest_for(manifests, DiscoveryRoute.EARNINGS)
    events = manifest_for(manifests, DiscoveryRoute.COMPANY_EVENT)

    assert earnings.scanned_records == 3
    assert earnings.triggered_records == 3
    assert events.scanned_records == 3
    assert events.triggered_records == 3
    assert events.deep_read_required == 3
    assert events.deep_read_completed == 0
    assert {
        item.security_id
        for item in hypotheses
        if DiscoveryRoute.EARNINGS in item.discovery_routes
    } == {"000003.SZ", "000004.SZ", "000005.SZ"}
    assert "announcement" in formation.facts.calls


def test_price_scans_full_market_and_uses_preregistered_absolute_tail_fraction():
    formation = snapshot()

    manifests, hypotheses = scan_routes(formation, policy(tail_fraction=0.4))
    price = manifest_for(manifests, DiscoveryRoute.PRICE_ANOMALY)

    assert price.expected_records == 5
    assert price.scanned_records == 5
    assert price.triggered_records == 2
    assert {
        item.security_id
        for item in hypotheses
        if DiscoveryRoute.PRICE_ANOMALY in item.discovery_routes
    } == {"000103.SZ", "000104.SZ"}


def test_hotspot_requires_complete_6_2_inputs_and_enumerates_industry_and_theme():
    manifests, hypotheses = scan_routes(snapshot(), policy())
    hotspot = manifest_for(manifests, DiscoveryRoute.HOTSPOT)

    assert hotspot.scanned_records == 5
    assert hotspot.triggered_records == 2
    assert {
        item.security_id
        for item in hypotheses
        if DiscoveryRoute.HOTSPOT in item.discovery_routes
    } == {"000001.SZ", "000002.SZ"}
    assert any("retreat counterevidence" in item for item in hotspot.manual_boundaries)


def test_cycle_and_repair_are_explicitly_incomplete_and_never_use_injected_booleans():
    formation = snapshot()
    formation.facts.rows["industry_daily"] = (
        {
            "industry_code": "I1",
            "trade_date": FORMATION_DATE,
            "industry_fact_changed": True,
            "available_at": CUTOFF,
        },
    )
    formation.facts.rows["repurchase"] = (
        {
            "ts_code": "000009.SZ",
            "core_risk_mitigated": True,
            "improved_statements": ("income", "cash_flow"),
            "available_at": CUTOFF,
        },
    )

    manifests, hypotheses = scan_routes(formation, policy())
    cycle = manifest_for(manifests, DiscoveryRoute.INDUSTRY_CYCLE)
    repair = manifest_for(manifests, DiscoveryRoute.DISTRESS_REPAIR)

    assert cycle.triggered_records == 0
    assert repair.triggered_records == 0
    assert any("incomplete" in item for item in cycle.missing)
    assert any("incomplete" in item for item in repair.missing)
    assert all(
        DiscoveryRoute.INDUSTRY_CYCLE not in item.discovery_routes
        and DiscoveryRoute.DISTRESS_REPAIR not in item.discovery_routes
        for item in hypotheses
    )


def test_unread_event_is_disabled_and_shared_evidence_keeps_both_route_links():
    _, hypotheses = scan_routes(snapshot(), policy())
    merged = next(item for item in hypotheses if item.security_id == "000003.SZ")

    assert merged.eligible_for_ten is True
    assert merged.needs_deep_read is True
    assert {
        (item.route, item.evidence_id, item.usable_for_decision)
        for item in merged.evidence
        if item.evidence_id == "shared-disclosure"
    } == {
        (DiscoveryRoute.EARNINGS, "shared-disclosure", True),
        (DiscoveryRoute.COMPANY_EVENT, "shared-disclosure", False),
    }
    assert all(
        "formal, directly related event" not in text
        for text in merged.transmission_hypotheses
    )


def test_logic_flags_are_strict_booleans_not_nonzero_numbers():
    features = feature_rows()
    malformed = dict(hotspot_row("industry", "I1", complete=False))
    malformed["common_change_reproducible"] = -1
    malformed["traceable_business_relation"] = -1
    features["sector_hotspot"] = (malformed,)
    formation = snapshot()
    formation.features.rows = features
    formation.sector_rows = 1

    manifests, _ = scan_routes(formation, policy())

    assert manifest_for(manifests, DiscoveryRoute.HOTSPOT).triggered_records == 0


def test_policy_is_deeply_immutable_and_fact_plan_must_be_exact():
    frozen = policy()
    full_plan = route_plan()

    with pytest.raises(TypeError):
        full_plan["announcement"] = ("2026-07",)

    with pytest.raises(TypeError):
        frozen.route_partitions[DiscoveryRoute.COMPANY_EVENT]["announcement"] = (
            "2026-07",
        )
    with pytest.raises(TypeError):
        frozen.route_partitions[DiscoveryRoute.COMPANY_EVENT] = {}
    with pytest.raises(TypeError):
        frozen.coverage_gaps[DiscoveryRoute.INDUSTRY_CYCLE] = ()

    oversized = dict(route_plan())
    oversized["announcement"] = (*oversized["announcement"], "2026-08")
    with pytest.raises(TypeError, match="build_route_fact_plan"):
        build_route_window_policy(
            formation_date=FORMATION_DATE,
            fact_plan=oversized,
            earnings_report_periods=(REPORT_PERIOD,),
            event_start=date(2026, 5, 20),
            price_absolute_tail_fraction=0.05,
        )

    copied_with_extra_relation = dict(route_plan())
    copied_with_extra_relation["theme_member"] = (
        *copied_with_extra_relation["theme_member"],
        "unregistered-theme-v2",
    )
    with pytest.raises(TypeError, match="build_route_fact_plan"):
        build_route_window_policy(
            formation_date=FORMATION_DATE,
            fact_plan=copied_with_extra_relation,
            earnings_report_periods=(REPORT_PERIOD,),
            event_start=date(2026, 5, 20),
            price_absolute_tail_fraction=0.05,
        )


def test_scan_fails_closed_when_source_manifest_contains_unrequested_partition():
    formation = snapshot()
    formation.facts.manifest["source_snapshot"]["partitions"].append(
        {
            "dataset": "theme_member",
            "partition": "unrequested-theme-v2",
            "row_count": 0,
            "resolved_row_count": 0,
            "resolved_content_hash": SHA256,
        }
    )
    _refresh_fact_manifest_hashes(formation)

    with pytest.raises(ValueError, match="unrequested fact partition"):
        scan_routes(formation, policy())


def test_scan_revalidates_policy_integrity_hash():
    frozen = policy()
    object.__setattr__(frozen, "price_absolute_tail_fraction", 0.2)

    with pytest.raises(ValueError, match="policy integrity hash"):
        scan_routes(snapshot(), frozen)


def test_expected_records_use_as_of_resolved_rows_not_physical_source_rows():
    formation = snapshot()
    for item in formation.facts.manifest["source_snapshot"]["partitions"]:
        if item["dataset"] == "announcement" and item["partition"] == "2026-05":
            item["row_count"] = 12
            assert item["resolved_row_count"] == 1
    _refresh_fact_manifest_hashes(formation)
    manifests, _ = scan_routes(formation, policy())
    event = manifest_for(manifests, DiscoveryRoute.COMPANY_EVENT)

    assert event.expected_records == 3
    assert event.scanned_records == 3
    assert not any("resolved 1/12" in reason for reason in event.missing)


@pytest.mark.parametrize(
    ("field_name", "invalid_value", "reason"),
    (
        (
            "available_at",
            datetime(2026, 7, 16, 9, tzinfo=SHANGHAI),
            "available_at exceeds formation cutoff",
        ),
        (
            "available_at",
            datetime(2026, 7, 12, 18),
            "timezone-naive available_at",
        ),
        (
            "announcement_time",
            datetime(2026, 7, 12, 18),
            "timezone-naive announcement_time",
        ),
    ),
)
def test_event_rejects_nonvisible_or_timezone_naive_timestamps(
    field_name: str,
    invalid_value: datetime,
    reason: str,
):
    formation = snapshot()
    rows = list(formation.facts.rows["announcement"])
    rows[-1] = {**rows[-1], field_name: invalid_value}
    formation.facts.rows["announcement"] = tuple(rows)

    manifests, hypotheses = scan_routes(formation, policy())
    event = manifest_for(manifests, DiscoveryRoute.COMPANY_EVENT)

    assert event.triggered_records == 2
    assert any(reason in exclusion for exclusion in event.exclusions)
    assert all(item.security_id != "000007.SZ" for item in hypotheses)


def test_hotspot_marks_active_membership_group_without_observation_as_missing():
    formation = snapshot()
    rows = feature_rows()
    rows["sector_hotspot"] = tuple(
        row
        for row in rows["sector_hotspot"]
        if not (row["group_type"] == "theme" and row["group_code"] == "T1")
    )
    formation.features.rows = rows
    formation.sector_rows = 2

    manifests, hypotheses = scan_routes(formation, policy())
    hotspot = manifest_for(manifests, DiscoveryRoute.HOTSPOT)

    assert any("theme:T1" in reason for reason in hotspot.missing)
    assert hotspot.triggered_records == 1
    assert all(item.security_id != "000002.SZ" for item in hypotheses)


def test_forged_invalid_membership_rows_cannot_bypass_source_attestation():
    formation = snapshot()
    base = formation.facts.rows["industry_member"][0]
    formation.facts.rows["industry_member"] = (
        base,
        {**base, "ts_code": "000011.SZ", "valid_to": date(2025, 12, 31)},
        {**base, "ts_code": "", "industry_code": "I1"},
        {
            **base,
            "ts_code": "000012.SZ",
            "available_at": datetime(2026, 7, 16, 9, tzinfo=SHANGHAI),
        },
        {**base, "ts_code": "000013.SZ", "industry_code": ""},
    )
    for item in formation.facts.manifest["effective_rows"]:
        if item["dataset"] == "industry_member":
            item["row_count"] = 5
    for item in formation.facts.manifest["source_snapshot"]["partitions"]:
        if item["dataset"] == "industry_member":
            item["row_count"] = 5
            item["resolved_row_count"] = 5
    _refresh_fact_manifest_hashes(formation)
    with pytest.raises(ValueError, match="attested complete controlled inventory"):
        build_frozen_universe_catalog(
            _controlled_fact_view(rows=formation.facts.rows),
            source_attestation=_default_controlled_bundle(FORMATION_DATE)[0],
        )


def test_price_uses_real_five_percent_tail_with_ties_and_invalid_rows_excluded():
    valid_scores = (0.99, 0.98, 0.97, 0.96, 0.95, 0.95) + tuple(
        index / 1000 for index in range(94)
    )
    rows = tuple(
        {
            "analysis_date": FORMATION_DATE,
            "ts_code": f"TAIL{index:03d}",
            "relative_return_20d": value,
            "coverage_status": "complete",
        }
        for index, value in enumerate(valid_scores)
    ) + (
        {
            "analysis_date": FORMATION_DATE,
            "ts_code": "MISSING",
            "relative_return_20d": None,
            "coverage_status": "complete",
        },
        {
            "analysis_date": FORMATION_DATE,
            "ts_code": "HALTED",
            "relative_return_20d": 9.0,
            "coverage_status": "complete",
            "tradable": False,
        },
        {
            "analysis_date": FORMATION_DATE,
            "ts_code": "INCOMPLETE",
            "relative_return_20d": 8.0,
            "coverage_status": "waiting_upstream",
        },
    )
    formation = snapshot()
    features = feature_rows()
    features["stock_trading_context"] = rows
    formation.features.rows = features
    formation.stock_rows = len(rows)

    manifests, hypotheses = scan_routes(formation, policy(tail_fraction=0.05))
    price = manifest_for(manifests, DiscoveryRoute.PRICE_ANOMALY)

    assert price.expected_records == 103
    assert price.scanned_records == 103
    assert price.triggered_records == 6
    assert {
        item.security_id
        for item in hypotheses
        if DiscoveryRoute.PRICE_ANOMALY in item.discovery_routes
    } == {f"TAIL{index:03d}" for index in range(6)}


def test_task3_dataframe_backed_public_views_run_all_route_interfaces():
    facts = fact_rows()
    manifest = input_manifest(facts)
    effective_rows = [
        {"dataset": dataset, "row_count": len(rows)}
        for dataset, rows in sorted(facts.items())
    ]
    view_payload = {
        "source_snapshot": manifest,
        "effective_date": FORMATION_DATE.isoformat(),
        "effective_rows": effective_rows,
    }
    fact_view = FormationFactView(
        {
            ResearchDatasetId(dataset): pd.DataFrame(rows)
            for dataset, rows in facts.items()
        },
        {**view_payload, "view_manifest_hash": _json_hash(view_payload)},
    )
    feature_data = feature_rows()
    feature_view = FormationFeatureView(
        {feature_set: pd.DataFrame(rows) for feature_set, rows in feature_data.items()}
    )
    formation = FormationSnapshot(
        analysis_date=FORMATION_DATE,
        as_of=CUTOFF,
        facts=fact_view,
        features=feature_view,
        market_rows=1,
        sector_rows=3,
        stock_rows=5,
        limitations=(),
        cache_key=SHA256,
        fact_manifest_hashes=(),
        formula_versions=(),
    )

    manifests, hypotheses = scan_routes(formation, policy())

    assert len(manifests) == 6
    assert manifest_for(manifests, DiscoveryRoute.HOTSPOT).triggered_records == 2
    assert manifest_for(manifests, DiscoveryRoute.EARNINGS).triggered_records == 3
    assert manifest_for(manifests, DiscoveryRoute.COMPANY_EVENT).triggered_records == 3
    assert manifest_for(manifests, DiscoveryRoute.PRICE_ANOMALY).triggered_records == 2
    assert hypotheses


def _hashed_manifest(
    partitions: list[dict[str, Any]],
    *,
    cutoff: datetime = CUTOFF,
) -> dict[str, Any]:
    payload = {
        "as_of": cutoff.astimezone(ZoneInfo("UTC")).isoformat(),
        "partitions": partitions,
    }
    return {
        **payload,
        "input_manifest_hash": _json_hash(payload),
    }


def _json_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _canonical_fact_hash(rows: tuple[dict[str, Any], ...]) -> str:
    selected = sorted(
        (
            str(row["business_key_hash"]),
            str(row["payload_hash"]),
            int(row.get("revision_no", 1)),
        )
        for row in rows
    )
    return _json_hash(selected)


def _commit_controlled_partition(
    warehouse: ResearchWarehouse,
    dataset: ResearchDatasetId,
    partition: str,
    records: list[dict[str, Any]],
    *,
    formation_date: date = FORMATION_DATE,
) -> None:
    known_at = datetime(
        formation_date.year,
        formation_date.month,
        formation_date.day,
        8,
        tzinfo=SHANGHAI,
    )
    warehouse.commit_batch(
        FactBatch(
            dataset_id=dataset,
            partition_value=partition,
            source_name="test",
            source_endpoint=dataset.value,
            ingestion_run_id=f"test:{dataset.value}:{partition}",
            ingested_at=known_at,
            default_available_at=known_at,
            records=records,
        )
    )


def _real_controlled_warehouse(
    tmp_path,
    *,
    formation_date: date = FORMATION_DATE,
    multiple_versions: bool = False,
    industry_ts_code: str = "000001.SZ",
) -> ResearchWarehouse:
    warehouse = ResearchWarehouse(tmp_path / "isolated-warehouse")
    prior = formation_date - timedelta(days=1)
    _commit_controlled_partition(
        warehouse,
        ResearchDatasetId.INDUSTRY_MEMBER,
        "sw2021-v1",
        [
            {
                "ts_code": industry_ts_code,
                "industry_system": "SW2021",
                "level": "L1",
                "industry_code": "I1",
                "classification_version": "sw2021-v1",
                "valid_from": date(2025, 1, 1),
                "valid_to": None,
            },
        ],
        formation_date=formation_date,
    )
    if multiple_versions:
        _commit_controlled_partition(
            warehouse,
            ResearchDatasetId.INDUSTRY_MEMBER,
            "sw2021-v2",
            [
                {
                    "ts_code": "000011.SZ",
                    "industry_system": "SW2021",
                    "level": "L1",
                    "industry_code": "I2",
                    "classification_version": "sw2021-v2",
                    "valid_from": date(2025, 2, 1),
                    "valid_to": None,
                }
            ],
            formation_date=formation_date,
        )
    _commit_controlled_partition(
        warehouse,
        ResearchDatasetId.THEME_MEMBER,
        "controlled-theme-v1",
        [
            {
                "theme_code": "T1",
                "ts_code": "000002.SZ",
                "catalog_version": "controlled-theme-v1",
                "valid_from": date(2025, 1, 1),
                "valid_to": None,
            },
        ],
        formation_date=formation_date,
    )
    if multiple_versions:
        _commit_controlled_partition(
            warehouse,
            ResearchDatasetId.THEME_MEMBER,
            "controlled-theme-v2",
            [
                {
                    "theme_code": "T2",
                    "ts_code": "000012.SZ",
                    "catalog_version": "controlled-theme-v2",
                    "valid_from": date(2025, 2, 1),
                    "valid_to": None,
                }
            ],
            formation_date=formation_date,
        )
    for trade_date, code in ((prior, "I1"), (formation_date, "I2")):
        _commit_controlled_partition(
            warehouse,
            ResearchDatasetId.INDUSTRY_DAILY,
            trade_date.isoformat(),
            [
                {
                    "trade_date": trade_date,
                    "industry_code": code,
                    "close": 100.0,
                }
            ],
            formation_date=formation_date,
        )
    return warehouse


def _task3_controlled_view(
    warehouse: ResearchWarehouse,
    plan: dict[ResearchDatasetId, tuple[str, ...]],
    *,
    formation_date: date = FORMATION_DATE,
) -> FormationFactView:
    cutoff = datetime.combine(
        formation_date,
        datetime.min.time().replace(hour=23, minute=59, second=59),
        tzinfo=SHANGHAI,
    )
    materialized = ResearchQuery(warehouse).materialize_snapshot(plan, as_of=cutoff)
    frames: dict[ResearchDatasetId, pd.DataFrame] = {}
    for dataset in plan:
        frame = materialized.frame(dataset)
        if dataset in {
            ResearchDatasetId.INDUSTRY_MEMBER,
            ResearchDatasetId.THEME_MEMBER,
        }:
            valid_from = pd.to_datetime(frame["valid_from"], errors="raise")
            valid_to = pd.to_datetime(frame["valid_to"], errors="coerce")
            cutoff_day = pd.Timestamp(formation_date)
            frame = frame.loc[
                (valid_from <= cutoff_day)
                & (valid_to.isna() | (valid_to >= cutoff_day))
            ].reset_index(drop=True)
        frames[dataset] = frame
    effective_rows = [
        {"dataset": dataset.value, "row_count": len(frames[dataset])}
        for dataset in sorted(frames, key=lambda item: item.value)
    ]
    payload = {
        "source_snapshot": materialized.input_manifest,
        "effective_date": formation_date.isoformat(),
        "effective_rows": effective_rows,
    }
    return FormationFactView(
        frames,
        {**payload, "view_manifest_hash": _json_hash(payload)},
    )


@lru_cache(maxsize=None)
def _default_controlled_bundle(formation_date: date):
    temporary = tempfile.TemporaryDirectory(prefix="task4-source-attestation-")
    warehouse = _real_controlled_warehouse(
        Path(temporary.name),
        formation_date=formation_date,
    )
    attestation = routes_module.build_source_catalog_attestation(
        warehouse,
        formation_date=formation_date,
    )
    plan = {
        ResearchDatasetId(dataset): attestation.partitions(dataset)
        for dataset in (
            "industry_member",
            "theme_member",
            "industry_daily",
        )
    }
    view = _task3_controlled_view(
        warehouse,
        plan,
        formation_date=formation_date,
    )
    catalog = build_frozen_universe_catalog(
        view,
        source_attestation=attestation,
    )
    rows = {
        dataset: tuple(view.dataset(dataset).to_dict(orient="records"))
        for dataset in (
            "industry_member",
            "theme_member",
            "industry_daily",
        )
    }
    return attestation, view, catalog, rows, temporary


def _controlled_bundle_from_warehouse(
    warehouse: ResearchWarehouse,
    *,
    formation_date: date = FORMATION_DATE,
):
    attestation = routes_module.build_source_catalog_attestation(
        warehouse,
        formation_date=formation_date,
    )
    plan = {
        ResearchDatasetId(dataset): attestation.partitions(dataset)
        for dataset in (
            "industry_member",
            "theme_member",
            "industry_daily",
        )
    }
    view = _task3_controlled_view(
        warehouse,
        plan,
        formation_date=formation_date,
    )
    catalog = build_frozen_universe_catalog(
        view,
        source_attestation=attestation,
    )
    return attestation, view, catalog


def _apply_controlled_view(
    formation: PublicSnapshot,
    attestation,
    view: FormationFactView,
) -> None:
    controlled = {"industry_member", "theme_member", "industry_daily"}
    for dataset in controlled:
        formation.facts.rows[dataset] = tuple(
            view.dataset(dataset).to_dict(orient="records")
        )
    source = formation.facts.manifest["source_snapshot"]
    source["partitions"] = sorted(
        [
            item
            for item in source["partitions"]
            if item["dataset"] not in controlled
        ]
        + list(attestation.source_entries()),
        key=lambda item: (item["dataset"], item["partition"]),
    )
    source["input_manifest_hash"] = _json_hash(
        {"as_of": source["as_of"], "partitions": source["partitions"]}
    )
    counts = {
        dataset: len(formation.facts.rows[dataset])
        for dataset in controlled
    }
    for item in formation.facts.manifest["effective_rows"]:
        if item["dataset"] in controlled:
            item["row_count"] = counts[item["dataset"]]
    payload = {
        key: formation.facts.manifest[key]
        for key in ("source_snapshot", "effective_date", "effective_rows")
    }
    formation.facts.manifest["view_manifest_hash"] = _json_hash(payload)


def _seed_route_plan_facts(
    warehouse: ResearchWarehouse,
    plan,
    *,
    formation_date: date,
    reports: tuple[date, ...],
) -> None:
    controlled = {"industry_member", "theme_member", "industry_daily"}
    completed_reports = tuple(period for period in reports if period <= formation_date)
    for dataset, partitions in plan.items():
        if dataset in controlled:
            continue
        dataset_id = ResearchDatasetId(dataset)
        for index, partition in enumerate(partitions):
            code = f"{index + 1:06d}.SZ"
            month_day = date.fromisoformat(f"{partition}-01") if len(partition) == 7 else None
            if dataset == "earnings_forecast":
                records = [
                    {
                        "ts_code": code,
                        "report_period": reports[-1],
                        "announcement_type": "预增",
                        "ann_date": month_day,
                        "ann_month": partition,
                        "p_change_min": 10.0,
                    }
                ]
            elif dataset == "earnings_express":
                records = [
                    {
                        "ts_code": code,
                        "report_period": reports[-1],
                        "announcement_type": "业绩快报",
                        "ann_date": month_day,
                        "ann_month": partition,
                        "net_profit": 1.0,
                    }
                ]
            elif dataset in {"income_statement", "balance_sheet", "cash_flow"}:
                period = date.fromisoformat(partition)
                records = [
                    {
                        "ts_code": code,
                        "report_period": period,
                        "report_type": "1",
                        "statement_type": "consolidated",
                        "comp_type": "1",
                        "end_type": "1",
                        "ann_date": formation_date,
                        "f_ann_date": formation_date,
                        "update_flag": 0,
                        "net_profit": 1.0,
                    }
                ]
            elif dataset == "announcement":
                records = [
                    {
                        "announcement_id": f"A-{partition}",
                        "announcement_month": partition,
                        "announcement_time": datetime.combine(
                            month_day,
                            datetime.min.time().replace(hour=9),
                            tzinfo=SHANGHAI,
                        ),
                        "ts_code": code,
                        "title": "普通公告",
                    }
                ]
            elif dataset == "main_business":
                period = date.fromisoformat(partition)
                records = [
                    {
                        "ts_code": code,
                        "report_period": period,
                        "classification": "industry",
                        "item_name": "item",
                    }
                ]
            elif dataset == "repurchase":
                records = [
                    {
                        "provider_record_id": f"R-{partition}",
                        "announcement_month": partition,
                        "ann_date": month_day,
                        "ts_code": code,
                    }
                ]
            else:
                raise AssertionError(dataset)
            visible_at = datetime(
                formation_date.year,
                formation_date.month,
                formation_date.day,
                8,
                tzinfo=SHANGHAI,
            )
            records = [{**record, "available_at": visible_at} for record in records]
            _commit_controlled_partition(
                warehouse,
                dataset_id,
                partition,
                records,
                formation_date=formation_date,
            )
    assert completed_reports


def _real_feature_runner(warehouse, analysis_date, *, as_of):
    store = DerivedFeatureStore(warehouse.root)
    sector = pd.DataFrame(
        [
            {
                **hotspot_row("industry", "I1"),
                "analysis_date": analysis_date,
            },
            {
                **hotspot_row("theme", "T1"),
                "analysis_date": analysis_date,
            },
        ]
    )
    stock = pd.DataFrame(
        [
            {
                "analysis_date": analysis_date,
                "ts_code": "000001.SZ",
                "relative_return_20d": 0.1,
                "coverage_status": "complete_with_declared_gaps",
            }
        ]
    )
    definitions = (
        (
            "market_context",
            MARKET_CONTEXT_FORMULA_VERSION,
            "analysis_date",
            pd.DataFrame({"analysis_date": [analysis_date]}),
        ),
        (
            "sector_hotspot",
            HOTSPOT_FORMULA_VERSION,
            ("analysis_date", "group_type", "group_code"),
            sector,
        ),
        (
            "stock_trading_context",
            STOCK_CONTEXT_FORMULA_VERSION,
            ("analysis_date", "ts_code"),
            stock,
        ),
    )
    for feature_set, formula_version, entity_key, frame in definitions:
        store.commit(
            feature_set,
            analysis_date,
            formula_version,
            frame,
            input_manifest={
                "fact_snapshot": {
                    "as_of": as_of.astimezone(ZoneInfo("UTC")).isoformat(),
                    "input_manifest_hash": SHA256,
                }
            },
            entity_key=entity_key,
            quality_status="complete_with_declared_gaps",
            run_id=f"smoke:{feature_set}:{analysis_date.isoformat()}",
        )
    return SimpleNamespace(
        failed_feature_sets=(),
        errors=(),
        market_rows=1,
        sector_rows=2,
        stock_rows=1,
        limitations=("minimal Task 4 route smoke",),
    )


def _refresh_fact_manifest_hashes(formation: PublicSnapshot) -> None:
    source = formation.facts.manifest["source_snapshot"]
    for item in source["partitions"]:
        dataset = item["dataset"]
        partition_rows = tuple(
            row
            for row in formation.facts.rows[dataset]
            if _row_partition(dataset, row) == item["partition"]
        )
        item["resolved_row_count"] = len(partition_rows)
        item["resolved_content_hash"] = _canonical_fact_hash(partition_rows)
    source["input_manifest_hash"] = _json_hash(
        {"as_of": source["as_of"], "partitions": source["partitions"]}
    )
    view_payload = {
        "source_snapshot": source,
        "effective_date": formation.facts.manifest["effective_date"],
        "effective_rows": formation.facts.manifest["effective_rows"],
    }
    formation.facts.manifest["view_manifest_hash"] = _json_hash(view_payload)


def _controlled_catalog_manifest() -> dict[str, Any]:
    return _hashed_manifest(
        [
            {
                "dataset": dataset,
                "partition": partition,
                "row_count": 0,
                "resolved_row_count": 0,
                "resolved_content_hash": SHA256,
            }
            for dataset, partitions in {
                "industry_member": ("sw2021-v1",),
                "theme_member": ("controlled-theme-v1",),
                "industry_daily": ("2026-07-14", "2026-07-15"),
            }.items()
            for partition in partitions
        ]
    )


def _controlled_fact_view(
    *,
    formation_date: date = FORMATION_DATE,
    rows: dict[str, tuple[dict[str, Any], ...]] | None = None,
) -> FormationFactView:
    if rows is None:
        return _default_controlled_bundle(formation_date)[1]
    controlled_rows = rows or fact_rows()
    cutoff = datetime(
        formation_date.year,
        formation_date.month,
        formation_date.day,
        23,
        59,
        59,
        tzinfo=SHANGHAI,
    )
    plan = {
        "industry_member": ("sw2021-v1",),
        "theme_member": ("controlled-theme-v1",),
        "industry_daily": (
            (formation_date - timedelta(days=1)).isoformat(),
            formation_date.isoformat(),
        ),
    }
    items: list[dict[str, Any]] = []
    for dataset, partitions in plan.items():
        for partition in partitions:
            selected = tuple(
                row
                for row in controlled_rows[dataset]
                if _row_partition(dataset, row) == partition
            )
            items.append(
                {
                    "dataset": dataset,
                    "partition": partition,
                    "row_count": len(selected),
                    "resolved_row_count": len(selected),
                    "resolved_content_hash": _canonical_fact_hash(selected),
                }
            )
    source = _hashed_manifest(items, cutoff=cutoff)
    effective_rows = [
        {"dataset": dataset, "row_count": len(controlled_rows[dataset])}
        for dataset in sorted(plan)
    ]
    view_payload = {
        "source_snapshot": source,
        "effective_date": formation_date.isoformat(),
        "effective_rows": effective_rows,
    }
    return FormationFactView(
        {
            ResearchDatasetId(dataset): pd.DataFrame(controlled_rows[dataset])
            for dataset in plan
        },
        {**view_payload, "view_manifest_hash": _json_hash(view_payload)},
    )


def test_fact_plan_universe_comes_only_from_a_hashed_builder_catalog():
    catalog_builder = getattr(routes_module, "build_frozen_universe_catalog")
    attestation = _default_controlled_bundle(FORMATION_DATE)[0]
    with pytest.raises(TypeError, match="FormationFactView"):
        catalog_builder(
            _controlled_catalog_manifest(),
            source_attestation=attestation,
        )
    catalog = catalog_builder(
        _controlled_fact_view(),
        source_attestation=attestation,
    )

    plan = build_route_fact_plan(
        formation_date=FORMATION_DATE,
        earnings_report_periods=(REPORT_PERIOD,),
        event_start=date(2026, 5, 20),
        universe_catalog=catalog,
    )

    assert plan["industry_member"] == ("sw2021-v1",)
    assert plan["theme_member"] == ("controlled-theme-v1",)
    assert plan["industry_daily"] == ("2026-07-14", "2026-07-15")
    assert catalog.source_attestation_hash == attestation.attestation_hash
    assert catalog.source_view_manifest_hash == attestation.view_manifest_hash
    with pytest.raises(ValueError, match="builder"):
        type(plan)({"industry_member": ("sw2021-v1",)})


def test_universe_catalog_rejects_tampered_hash_or_incomplete_controlled_sets():
    catalog_builder = getattr(routes_module, "build_frozen_universe_catalog")
    attestation = _default_controlled_bundle(FORMATION_DATE)[0]
    tampered = _controlled_catalog_manifest()
    tampered["partitions"].pop()
    tampered["input_manifest_hash"] = _json_hash(
        {"as_of": tampered["as_of"], "partitions": tampered["partitions"]}
    )
    with pytest.raises(TypeError, match="FormationFactView"):
        catalog_builder(tampered, source_attestation=attestation)

    wrong_cutoff_view = _controlled_fact_view()
    wrong_manifest = wrong_cutoff_view.manifest
    wrong_manifest["source_snapshot"]["as_of"] = "2026-07-15T15:59:58+00:00"
    wrong_manifest["source_snapshot"]["input_manifest_hash"] = _json_hash(
        {
            "as_of": wrong_manifest["source_snapshot"]["as_of"],
            "partitions": wrong_manifest["source_snapshot"]["partitions"],
        }
    )
    wrong_payload = {
        key: wrong_manifest[key]
        for key in ("source_snapshot", "effective_date", "effective_rows")
    }
    wrong_manifest["view_manifest_hash"] = _json_hash(wrong_payload)
    wrong_cutoff_view = FormationFactView(
        {
            ResearchDatasetId(dataset): wrong_cutoff_view.dataset(dataset)
            for dataset in (
                "industry_member",
                "theme_member",
                "industry_daily",
            )
        },
        wrong_manifest,
    )
    with pytest.raises(ValueError, match="23:59:59"):
        catalog_builder(
            wrong_cutoff_view,
            source_attestation=attestation,
        )


def test_source_attestation_rejects_task3_view_with_one_real_partition_omitted(
    tmp_path,
):
    warehouse = _real_controlled_warehouse(tmp_path, multiple_versions=True)
    attestation = routes_module.build_source_catalog_attestation(
        warehouse,
        formation_date=FORMATION_DATE,
    )
    reduced_plan = {
        ResearchDatasetId.INDUSTRY_MEMBER: ("sw2021-v1",),
        ResearchDatasetId.THEME_MEMBER: (
            "controlled-theme-v1",
            "controlled-theme-v2",
        ),
        ResearchDatasetId.INDUSTRY_DAILY: (
            (FORMATION_DATE - timedelta(days=1)).isoformat(),
            FORMATION_DATE.isoformat(),
        ),
    }
    reduced_view = _task3_controlled_view(warehouse, reduced_plan)

    assert attestation.partitions("industry_member") == (
        "sw2021-v1",
        "sw2021-v2",
    )
    with pytest.raises(ValueError, match="attested complete controlled inventory"):
        build_frozen_universe_catalog(
            reduced_view,
            source_attestation=attestation,
        )


def test_source_attestation_rejects_forged_effective_relation_view(tmp_path):
    warehouse = _real_controlled_warehouse(tmp_path, multiple_versions=True)
    attestation = routes_module.build_source_catalog_attestation(
        warehouse,
        formation_date=FORMATION_DATE,
    )
    full_plan = {
        ResearchDatasetId(dataset): attestation.partitions(dataset)
        for dataset in (
            "industry_member",
            "theme_member",
            "industry_daily",
        )
    }
    real_view = _task3_controlled_view(warehouse, full_plan)
    forged_industry = real_view.dataset(ResearchDatasetId.INDUSTRY_MEMBER)
    forged_industry.loc[0, "ts_code"] = "FORGED.SZ"
    forged_industry.loc[0, "business_key_hash"] = _json_hash("forged-business")
    forged_industry.loc[0, "payload_hash"] = _json_hash("forged-payload")
    manifest = real_view.manifest
    payload = {
        key: manifest[key]
        for key in ("source_snapshot", "effective_date", "effective_rows")
    }
    forged_view = FormationFactView(
        {
            ResearchDatasetId.INDUSTRY_MEMBER: forged_industry,
            ResearchDatasetId.THEME_MEMBER: real_view.dataset("theme_member"),
            ResearchDatasetId.INDUSTRY_DAILY: real_view.dataset("industry_daily"),
        },
        {**payload, "view_manifest_hash": _json_hash(payload)},
    )

    with pytest.raises(ValueError, match="attested effective content"):
        build_frozen_universe_catalog(
            forged_view,
            source_attestation=attestation,
        )


def test_source_attestation_is_opaque_and_not_publicly_constructible(tmp_path):
    warehouse = _real_controlled_warehouse(tmp_path)
    real = routes_module.build_source_catalog_attestation(
        warehouse,
        formation_date=FORMATION_DATE,
    )

    assert "SourceCatalogAttestation" not in routes_module.__all__
    constructor = getattr(routes_module, "SourceCatalogAttestation", None)
    assert constructor is None
    assert real.attestation_hash


def test_copied_attestation_lacks_builder_registry_provenance(tmp_path):
    warehouse = _real_controlled_warehouse(tmp_path)
    attestation, view, _ = _controlled_bundle_from_warehouse(warehouse)
    copied = copy.copy(attestation)

    with pytest.raises(ValueError, match="registered warehouse builder"):
        build_frozen_universe_catalog(
            view,
            source_attestation=copied,
        )


def test_registered_attestation_freezes_builder_code_hash(tmp_path, monkeypatch):
    warehouse = _real_controlled_warehouse(tmp_path)
    attestation, view, _ = _controlled_bundle_from_warehouse(warehouse)
    monkeypatch.setattr(routes_module, "_module_code_hash", lambda: "f" * 64)

    with pytest.raises(ValueError, match="builder code hash changed"):
        build_frozen_universe_catalog(
            view,
            source_attestation=attestation,
        )


@pytest.mark.parametrize("mutation", ("add", "delete", "replace"))
def test_catalog_revalidates_attested_warehouse_tree_before_use(tmp_path, mutation):
    warehouse = _real_controlled_warehouse(tmp_path)
    attestation, view, _ = _controlled_bundle_from_warehouse(warehouse)
    if mutation == "add":
        added = FORMATION_DATE - timedelta(days=2)
        _commit_controlled_partition(
            warehouse,
            ResearchDatasetId.INDUSTRY_DAILY,
            added.isoformat(),
            [{"trade_date": added, "industry_code": "I3", "close": 100.0}],
        )
    elif mutation == "delete":
        warehouse.prune_partitions_before(
            ResearchDatasetId.INDUSTRY_DAILY,
            FORMATION_DATE.isoformat(),
        )
    else:
        _commit_controlled_partition(
            warehouse,
            ResearchDatasetId.INDUSTRY_DAILY,
            FORMATION_DATE.isoformat(),
            [
                {
                    "trade_date": FORMATION_DATE,
                    "industry_code": "I2",
                    "close": 200.0,
                }
            ],
        )

    with pytest.raises(ValueError, match="attested warehouse.*changed"):
        build_frozen_universe_catalog(
            view,
            source_attestation=attestation,
        )


def test_scan_revalidates_registered_warehouse_after_catalog_build(tmp_path):
    warehouse = _real_controlled_warehouse(tmp_path)
    attestation, view, catalog = _controlled_bundle_from_warehouse(warehouse)
    formation = snapshot()
    _apply_controlled_view(formation, attestation, view)
    added = FORMATION_DATE - timedelta(days=2)
    _commit_controlled_partition(
        warehouse,
        ResearchDatasetId.INDUSTRY_DAILY,
        added.isoformat(),
        [{"trade_date": added, "industry_code": "I3", "close": 100.0}],
    )

    with pytest.raises(ValueError, match="attested warehouse.*changed"):
        scan_routes(formation, policy(catalog=catalog))


def test_scan_rejects_self_consistent_intraday_snapshot_cutoff():
    formation = snapshot()
    intraday = datetime(2026, 7, 15, 12, tzinfo=SHANGHAI)
    formation.as_of = intraday
    source = formation.facts.manifest["source_snapshot"]
    source["as_of"] = intraday.astimezone(ZoneInfo("UTC")).isoformat()
    _refresh_fact_manifest_hashes(formation)

    with pytest.raises(ValueError, match="23:59:59"):
        scan_routes(formation, policy())


def test_scan_rejects_self_consistent_controlled_file_hash_not_in_attestation():
    formation = snapshot()
    source = formation.facts.manifest["source_snapshot"]
    controlled = next(
        item for item in source["partitions"] if item["dataset"] == "industry_member"
    )
    controlled["file_sha256"] = "f" * 64
    _refresh_fact_manifest_hashes(formation)

    with pytest.raises(ValueError, match="attested controlled source subset"):
        scan_routes(formation, policy())


@pytest.mark.parametrize(
    "formation_date",
    (date(2025, 10, 30), date(2026, 1, 8), date(2026, 6, 3)),
)
def test_four_plus_two_windows_build_across_year_boundaries(formation_date: date):
    event_start, reports = derive_declared_route_windows(
        formation_date=formation_date,
        event_lookback_calendar_days=45,
        completed_quarter_count=4,
        future_quarter_count=2,
    )
    catalog = _default_controlled_bundle(formation_date)[2]

    plan = build_route_fact_plan(
        formation_date=formation_date,
        earnings_report_periods=reports,
        event_start=event_start,
        universe_catalog=catalog,
    )
    frozen = build_route_window_policy(
        formation_date=formation_date,
        fact_plan=plan,
        earnings_report_periods=reports,
        event_start=event_start,
        price_absolute_tail_fraction=0.05,
    )

    assert plan["earnings_forecast"][-1] == formation_date.strftime("%Y-%m")
    assert plan["earnings_express"] == plan["earnings_forecast"]
    assert all(date.fromisoformat(value) <= formation_date for value in plan["income_statement"])
    assert frozen.earnings_report_periods == reports


@pytest.mark.parametrize(
    "formation_date",
    (date(2025, 10, 30), date(2026, 1, 8), date(2026, 6, 3)),
)
def test_real_task3_snapshot_scans_all_routes_across_four_plus_two_boundaries(
    tmp_path,
    formation_date: date,
):
    event_start, reports = derive_declared_route_windows(
        formation_date=formation_date,
        event_lookback_calendar_days=45,
        completed_quarter_count=4,
        future_quarter_count=2,
    )
    warehouse = _real_controlled_warehouse(
        tmp_path,
        formation_date=formation_date,
    )
    _, _, provisional_catalog = _controlled_bundle_from_warehouse(
        warehouse,
        formation_date=formation_date,
    )
    provisional_plan = build_route_fact_plan(
        formation_date=formation_date,
        earnings_report_periods=reports,
        event_start=event_start,
        universe_catalog=provisional_catalog,
    )
    _seed_route_plan_facts(
        warehouse,
        provisional_plan,
        formation_date=formation_date,
        reports=reports,
    )

    _, _, catalog = _controlled_bundle_from_warehouse(
        warehouse,
        formation_date=formation_date,
    )
    plan = build_route_fact_plan(
        formation_date=formation_date,
        earnings_report_periods=reports,
        event_start=event_start,
        universe_catalog=catalog,
    )
    frozen = build_route_window_policy(
        formation_date=formation_date,
        fact_plan=plan,
        earnings_report_periods=reports,
        event_start=event_start,
        price_absolute_tail_fraction=0.05,
    )
    temp_root = Path("/tmp") / f"v3-complete-backtest-{uuid4().hex}"
    try:
        formation = materialize_formation_snapshot(
            warehouse,
            formation_date,
            temp_root,
            fact_plan=plan,
            feature_runner=_real_feature_runner,
        )
        batch = scan_routes(formation, frozen)
        assert require_verified_route_scan_batch(batch) is batch
        manifests, _ = batch
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)

    assert len(manifests) == 6
    assert {manifest.route for manifest in manifests} == set(DiscoveryRoute)


@pytest.mark.parametrize(
    ("dataset", "route"),
    (
        ("earnings_forecast", DiscoveryRoute.EARNINGS),
        ("industry_member", DiscoveryRoute.HOTSPOT),
    ),
)
def test_equal_row_content_replacement_fails_closed_on_canonical_hash(
    dataset: str,
    route: DiscoveryRoute,
):
    formation = snapshot()
    original = formation.facts.rows[dataset][0]
    formation.facts.rows[dataset] = (
        {
            **original,
            "ts_code": "REPLACED",
            "business_key_hash": _json_hash((dataset, "replaced-business")),
            "payload_hash": _json_hash((dataset, "replaced-payload")),
        },
        *formation.facts.rows[dataset][1:],
    )

    manifests, hypotheses = scan_routes(formation, policy())
    affected = manifest_for(manifests, route)

    assert affected.triggered_records == 0
    assert any("content hash" in reason for reason in affected.missing)
    assert all(route not in item.discovery_routes for item in hypotheses)


@pytest.mark.parametrize(
    ("dataset", "mutation", "route"),
    (
        ("earnings_forecast", "extra_frame_row", DiscoveryRoute.EARNINGS),
        ("announcement", "missing_frame_row", DiscoveryRoute.COMPANY_EVENT),
        ("announcement", "missing_effective_entry", DiscoveryRoute.COMPANY_EVENT),
    ),
)
def test_fact_manifest_frame_mismatch_fails_closed_for_affected_route(
    dataset: str,
    mutation: str,
    route: DiscoveryRoute,
):
    formation = snapshot()
    if mutation == "extra_frame_row":
        formation.facts.rows[dataset] = (
            *formation.facts.rows[dataset],
            {**formation.facts.rows[dataset][0], "ts_code": "UNPROVEN"},
        )
    elif mutation == "missing_frame_row":
        formation.facts.rows[dataset] = formation.facts.rows[dataset][:-1]
    else:
        formation.facts.manifest["effective_rows"] = [
            row
            for row in formation.facts.manifest["effective_rows"]
            if row["dataset"] != dataset
        ]
        _refresh_fact_manifest_hashes(formation)

    manifests, hypotheses = scan_routes(formation, policy())
    affected = manifest_for(manifests, route)

    assert affected.triggered_records == 0
    assert any("fail closed" in reason for reason in affected.missing)
    assert all(route not in item.discovery_routes for item in hypotheses)


def test_manifest_hash_mismatch_fails_closed_fact_routes():
    formation = snapshot()
    item = next(
        row
        for row in formation.facts.manifest["source_snapshot"]["partitions"]
        if row["dataset"] == "announcement"
    )
    item["row_count"] += 1

    manifests, hypotheses = scan_routes(formation, policy())

    for route in (
        DiscoveryRoute.HOTSPOT,
        DiscoveryRoute.EARNINGS,
        DiscoveryRoute.COMPANY_EVENT,
        DiscoveryRoute.INDUSTRY_CYCLE,
        DiscoveryRoute.DISTRESS_REPAIR,
    ):
        item = manifest_for(manifests, route)
        assert item.triggered_records == 0
        assert any("manifest hash" in reason for reason in item.missing)
        assert all(route not in hypothesis.discovery_routes for hypothesis in hypotheses)


def test_feature_count_mismatch_fails_closed_instead_of_using_extra_row():
    formation = snapshot()
    formation.features.rows["sector_hotspot"] = (
        *formation.features.rows["sector_hotspot"],
        hotspot_row("industry", "I1"),
    )

    manifests, hypotheses = scan_routes(formation, policy())
    hotspot = manifest_for(manifests, DiscoveryRoute.HOTSPOT)

    assert hotspot.triggered_records == 0
    assert any("fail closed" in reason for reason in hotspot.missing)
    assert all(DiscoveryRoute.HOTSPOT not in item.discovery_routes for item in hypotheses)


def test_hotspot_and_price_only_hypotheses_are_internal_recall_not_ten_eligible():
    _, hypotheses = scan_routes(snapshot(), policy())

    for route in (DiscoveryRoute.HOTSPOT, DiscoveryRoute.PRICE_ANOMALY):
        route_only = [item for item in hypotheses if item.discovery_routes == (route,)]
        assert route_only
        assert all(not item.eligible_for_ten for item in route_only)
        assert all(item.internal_review_only for item in route_only)


def test_usable_company_evidence_can_upgrade_a_hotspot_recall(tmp_path):
    formation = snapshot()
    warehouse = _real_controlled_warehouse(
        tmp_path,
        industry_ts_code="000003.SZ",
    )
    attestation, view, catalog = _controlled_bundle_from_warehouse(warehouse)
    _apply_controlled_view(
        formation,
        attestation,
        view,
    )

    _, hypotheses = scan_routes(formation, policy(catalog=catalog))
    merged = next(item for item in hypotheses if item.security_id == "000003.SZ")

    assert DiscoveryRoute.HOTSPOT in merged.discovery_routes
    assert DiscoveryRoute.EARNINGS in merged.discovery_routes
    assert merged.eligible_for_ten is True
    assert merged.internal_review_only is False


def test_event_window_uses_shanghai_calendar_date_for_aware_utc_timestamp():
    formation = snapshot()
    first = formation.facts.rows["announcement"][0]
    formation.facts.rows["announcement"] = (
        {
            **first,
            "announcement_time": datetime.fromisoformat("2026-05-19T16:30:00+00:00"),
            "available_at": datetime.fromisoformat("2026-05-19T16:30:00+00:00"),
        },
        *formation.facts.rows["announcement"][1:],
    )

    manifests, _ = scan_routes(formation, policy())

    assert manifest_for(manifests, DiscoveryRoute.COMPANY_EVENT).triggered_records == 3


def test_duplicate_hotspot_observation_fails_closed_without_inflating_leads():
    formation = snapshot()
    formation.features.rows["sector_hotspot"] = (
        *formation.features.rows["sector_hotspot"],
        dict(formation.features.rows["sector_hotspot"][0]),
    )
    formation.sector_rows = 4

    manifests, hypotheses = scan_routes(formation, policy())
    hotspot = manifest_for(manifests, DiscoveryRoute.HOTSPOT)

    assert hotspot.triggered_records == 0
    assert any("duplicate observation" in reason for reason in hotspot.missing)
    assert all(DiscoveryRoute.HOTSPOT not in item.discovery_routes for item in hypotheses)
