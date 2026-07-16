from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, time, timezone
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from pydantic import ValidationError
import stock_analyzer.evaluation.v3_backtest.evidence as evidence_module

from stock_analyzer.evaluation.v3_backtest.contracts import (
    DiscoveryRoute,
    EvidenceKind,
    OpportunityType,
    RouteScanManifest,
)
from stock_analyzer.evaluation.v3_backtest.evidence import (
    CandidateEvidencePacket,
    EvidenceFactPlan,
    EvidenceCardStatus,
    EvidenceAvailability,
    EvidenceDatum,
    EvidenceInputStatus,
    EvidenceSectionName,
    EvidenceText,
    KnowledgeRoutingStatus,
    ModelJudgment,
    _build_candidate_packet_from_verified_parts,
    build_candidate_packet,
    build_evidence_fact_plan,
    build_evidence_source_catalog,
    build_verified_evidence_snapshot_bundle,
    evidence_input_contract,
    project_route_snapshot,
)
from stock_analyzer.evaluation.v3_backtest.routes import (
    ResearchHypothesis,
    RouteEvidence,
    build_frozen_universe_catalog,
    build_source_catalog_attestation,
    build_route_fact_plan,
    build_route_window_policy,
    scan_routes,
)
from stock_analyzer.evaluation.v3_backtest.snapshots import (
    FormationFactView,
    FormationFeatureView,
    FormationSnapshot,
    materialize_formation_snapshot,
)
from stock_analyzer.storage.research_derived import DerivedFeatureStore
from stock_analyzer.storage.research_warehouse import ResearchWarehouse
from stock_analyzer.analysis.hotspot_features import HOTSPOT_FORMULA_VERSION
from stock_analyzer.analysis.market_context_features import MARKET_CONTEXT_FORMULA_VERSION
from stock_analyzer.analysis.stock_context_features import STOCK_CONTEXT_FORMULA_VERSION
from stock_analyzer.data.research_contracts import FactBatch, ResearchDatasetId
from stock_analyzer.knowledge.registry import load_knowledge_registry


SHANGHAI = ZoneInfo("Asia/Shanghai")
FORMATION_DATE = date(2026, 7, 15)
CUTOFF = datetime(2026, 7, 15, 23, 59, 59, tzinfo=SHANGHAI)
REGISTRY = load_knowledge_registry(
    Path("src/stock_analyzer/knowledge/research_registry.yaml")
)
_TASK4_FIXTURE = None


def _task4_fixture_module():
    global _TASK4_FIXTURE
    if _TASK4_FIXTURE is None:
        path = Path("tests/evaluation/v3_backtest/test_routes.py")
        spec = importlib.util.spec_from_file_location("task4_current_fixture", path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        _TASK4_FIXTURE = module
    return _TASK4_FIXTURE


def _task4_catalog():
    return _task4_fixture_module()._default_controlled_bundle(FORMATION_DATE)[2]


def _task4_attestation():
    return _task4_fixture_module()._default_controlled_bundle(FORMATION_DATE)[0]


def _fixture_source_manifest(frames: dict[str, pd.DataFrame]):
    base = {
        "industry_member": ("sw2021-v1",),
        "theme_member": ("controlled-theme-v1",),
        "industry_daily": ("2026-07-14", "2026-07-15"),
        "earnings_forecast": tuple(f"2026-{month:02d}" for month in range(1, 8)),
        "earnings_express": tuple(f"2026-{month:02d}" for month in range(1, 8)),
        "income_statement": ("2026-06-30",),
        "main_business": ("2026-06-30",),
        "balance_sheet": ("2026-06-30",),
        "cash_flow": ("2026-06-30",),
        "announcement": ("2026-06", "2026-07"),
        "repurchase": ("2026-06", "2026-07"),
    }
    extra_partition = {
        "company_profile": "controlled-v1",
        "security_master": "controlled-v1",
        "financial_indicator": "2026-06-30",
        "holder_trade": "2026-06",
        "pledge": "2026-06",
        "share_float": "2026-07",
        "daily_basic": "2026-07-15",
        "equity_daily": "2026-07-15",
        "index_daily": "2026-07-15",
        "stock_limit": "2026-07-15",
        "suspension": "2026-07-15",
        "adj_factor": "2026-07-15",
        "margin_detail": "2026-07-15",
    }
    partitions = []
    for dataset, values in base.items():
        for partition in values:
            count = len(frames.get(dataset, ()))
            partitions.append(
                {
                    "dataset": dataset,
                    "partition": partition,
                    "row_count": count,
                    "resolved_row_count": count,
                    "resolved_content_hash": "a" * 64,
                }
            )
    for dataset in frames:
        if dataset not in base and dataset in extra_partition:
            partitions.append(
                {
                    "dataset": dataset,
                    "partition": extra_partition[dataset],
                    "row_count": len(frames[dataset]),
                    "resolved_row_count": len(frames[dataset]),
                    "resolved_content_hash": "a" * 64,
                }
            )
    return _hashed_source_manifest(partitions)


class _Facts:
    def __init__(self, frames: dict[str, pd.DataFrame]) -> None:
        self._frames = frames
    @property
    def manifest(self):
        source = _fixture_source_manifest(self._frames)
        datasets = sorted({item["dataset"] for item in source["partitions"]})
        effective_rows = [
            {"dataset": name, "row_count": len(self._frames.get(name, ())) }
            for name in datasets
        ]
        view_payload = {
            "source_snapshot": source,
            "effective_date": FORMATION_DATE.isoformat(),
            "effective_rows": effective_rows,
        }
        return {
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

    def dataset(self, dataset_id):
        key = getattr(dataset_id, "value", str(dataset_id))
        return self._frames.get(key, pd.DataFrame()).copy(deep=True)


class _Features:
    def __init__(self, frames: dict[str, pd.DataFrame]) -> None:
        self._frames = frames

    def read(self, feature_set: str):
        if feature_set not in self._frames:
            raise KeyError(feature_set)
        return self._frames[feature_set].copy(deep=True)


def _snapshot(
    *,
    facts: dict[str, pd.DataFrame] | None = None,
    features: dict[str, pd.DataFrame] | None = None,
):
    feature_frames = features or {}
    return SimpleNamespace(
        analysis_date=FORMATION_DATE,
        as_of=CUTOFF,
        facts=_Facts(facts or {}),
        features=_Features(feature_frames),
        cache_key="b" * 64,
        market_rows=len(feature_frames.get("market_context", ())),
        sector_rows=len(feature_frames.get("sector_hotspot", ())),
        stock_rows=len(feature_frames.get("stock_trading_context", ())),
    )


def _hypothesis(*, available_at: datetime | None = None) -> ResearchHypothesis:
    visible = available_at or datetime(2026, 7, 14, 18, tzinfo=SHANGHAI)
    return ResearchHypothesis(
        security_id="600000.SH",
        formation_date=FORMATION_DATE,
        cutoff=CUTOFF,
        discovery_routes=(DiscoveryRoute.EARNINGS, DiscoveryRoute.PRICE_ANOMALY),
        evidence=(
            RouteEvidence(
                evidence_id="route-earnings",
                route=DiscoveryRoute.EARNINGS,
                dataset="income_statement",
                available_at=visible,
                fact_summary="正式经营信息在形成日前可见",
            ),
            RouteEvidence(
                evidence_id="route-price",
                route=DiscoveryRoute.PRICE_ANOMALY,
                dataset="stock_trading_context",
                available_at=visible,
                fact_summary="相对价格变化触发原因核查",
            ),
        ),
        transmission_hypotheses=("核对盈利变化是否传导到持续经营质量",),
        questions_to_verify=("核对下一份正式披露是否继续支持当前经营变化",),
        needs_deep_read=False,
        eligible_for_ten=True,
        internal_review_only=False,
        preliminary_opportunity=OpportunityType.EARNINGS_REVALUATION,
    )


def _route_manifests(hypothesis: ResearchHypothesis, policy):
    return tuple(
        RouteScanManifest(
            route=route,
            formation_date=FORMATION_DATE,
            cutoff=CUTOFF,
            requested_partitions=tuple(
                f"{dataset}:{partition}"
                for dataset, partitions in policy.route_partitions[route].items()
                for partition in partitions
            ),
            actual_partitions=tuple(
                f"{dataset}:{partition}"
                for dataset, partitions in policy.route_partitions[route].items()
                for partition in partitions
            ),
            expected_records=1,
            scanned_records=1,
            triggered_records=int(route in hypothesis.discovery_routes),
            deduplicated_records=int(route in hypothesis.discovery_routes),
            input_hash={route: chr(97 + index) * 64 for index, route in enumerate(DiscoveryRoute)}[route],
        )
        for route in DiscoveryRoute
    )


def _hashed_source_manifest(partitions):
    ordered = sorted(
        (dict(item) for item in partitions),
        key=lambda item: (str(item.get("dataset")), str(item.get("partition"))),
    )
    payload = {
        "as_of": CUTOFF.isoformat(),
        "partitions": ordered,
    }
    return {
        **payload,
        "input_manifest_hash": hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest(),
    }


def _empty_controlled_view(source_manifest):
    empty_hash = hashlib.sha256(b"[]").hexdigest()
    partitions = []
    for item in source_manifest["partitions"]:
        if item["dataset"] not in {
            "industry_member",
            "theme_member",
            "industry_daily",
        }:
            continue
        copied = dict(item)
        copied["row_count"] = 0
        copied["resolved_row_count"] = 0
        copied["resolved_content_hash"] = empty_hash
        partitions.append(copied)
    source = _hashed_source_manifest(partitions)
    effective_rows = [
        {"dataset": dataset, "row_count": 0}
        for dataset in ("industry_daily", "industry_member", "theme_member")
    ]
    view_payload = {
        "source_snapshot": source,
        "effective_date": FORMATION_DATE.isoformat(),
        "effective_rows": effective_rows,
    }
    return FormationFactView(
        {
            ResearchDatasetId(dataset): pd.DataFrame()
            for dataset in ("industry_daily", "industry_member", "theme_member")
        },
        {
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
        },
    )


def _catalog_and_route_plan(*, extra_partitions=()):
    controlled = tuple(
        {
            "dataset": dataset,
            "partition": partition,
            "row_count": 0,
            "resolved_row_count": 0,
            "resolved_content_hash": "a" * 64,
        }
        for dataset, partitions in {
            "industry_member": ("sw2021-v1",),
            "theme_member": ("controlled-theme-v1",),
            "industry_daily": ("2026-07-14", "2026-07-15"),
        }.items()
        for partition in partitions
    )
    source = _hashed_source_manifest((*controlled, *extra_partitions))
    catalog = _task4_catalog()
    route_plan = build_route_fact_plan(
        formation_date=FORMATION_DATE,
        earnings_report_periods=(date(2026, 6, 30),),
        event_start=date(2026, 6, 1),
        universe_catalog=catalog,
    )
    return source, _task4_attestation(), catalog, route_plan


def _audit_inputs(snapshot, hypothesis):
    source = snapshot.facts.manifest["source_snapshot"]
    catalog = _task4_catalog()
    route_plan = build_route_fact_plan(
        formation_date=FORMATION_DATE,
        earnings_report_periods=(date(2026, 6, 30),),
        event_start=date(2026, 6, 1),
        universe_catalog=catalog,
    )
    policy = build_route_window_policy(
        formation_date=FORMATION_DATE,
        fact_plan=route_plan,
        earnings_report_periods=(date(2026, 6, 30),),
        event_start=date(2026, 6, 1),
        price_absolute_tail_fraction=0.1,
    )
    evidence_plan = EvidenceFactPlan(
        {
            dataset: tuple(
                str(item["partition"])
                for item in source["partitions"]
                if item["dataset"] == dataset
            )
            for dataset in dict.fromkeys(
                str(item["dataset"]) for item in source["partitions"]
            )
        },
        route_plan=route_plan,
        catalog_hash=catalog.catalog_hash,
        source_manifest_hash=source["input_manifest_hash"],
        source_attestation_hash=catalog.source_attestation_hash,
        source_as_of=source["as_of"],
        source_entries=source["partitions"],
        _token=evidence_module._EVIDENCE_PLAN_TOKEN,
    )
    return evidence_plan, policy, _route_manifests(hypothesis, policy)


def _build(snapshot, hypothesis, registry=REGISTRY, **kwargs):
    evidence_plan, policy, manifests = _audit_inputs(snapshot, hypothesis)
    return _build_candidate_packet_from_verified_parts(
        snapshot,
        hypothesis,
        registry,
        evidence_plan=evidence_plan,
        route_policy=policy,
        route_manifests=manifests,
        verified_batch_receipt_hash="d" * 64,
        raw_lead_ledger_hash="e" * 64,
        **kwargs,
    )


def _unresolved_hypothesis() -> ResearchHypothesis:
    return ResearchHypothesis(
        security_id="600000.SH",
        formation_date=FORMATION_DATE,
        cutoff=CUTOFF,
        discovery_routes=(DiscoveryRoute.PRICE_ANOMALY,),
        evidence=(
            RouteEvidence(
                evidence_id="unresolved-route",
                route=DiscoveryRoute.PRICE_ANOMALY,
                dataset="stock_trading_context",
                available_at=None,
                fact_summary=None,
                usable_for_decision=False,
            ),
        ),
        transmission_hypotheses=(),
        questions_to_verify=("等待可复算价格观察",),
        needs_deep_read=False,
        eligible_for_ten=False,
        internal_review_only=True,
        preliminary_opportunity=None,
    )


def _earnings_snapshot():
    available_at = datetime(2026, 7, 14, 18, tzinfo=SHANGHAI)
    facts = {
        "earnings_forecast": pd.DataFrame(
            [
                {
                    "ts_code": "600000.SH",
                    "report_period": date(2026, 6, 30),
                    "ann_date": date(2026, 7, 14),
                    "type": "预增",
                    "p_change_min": Decimal("20.0"),
                    "p_change_max": Decimal("30.0"),
                    "available_at": available_at,
                }
            ]
        ),
        "earnings_express": pd.DataFrame(
            [
                {
                    "ts_code": "600000.SH",
                    "report_period": date(2026, 6, 30),
                    "ann_date": date(2026, 7, 14),
                    "announcement_type": "业绩快报",
                    "yoy_net_profit": Decimal("25.0"),
                    "available_at": available_at,
                }
            ]
        ),
        "income_statement": pd.DataFrame(
            [
                {
                    "ts_code": "600000.SH",
                    "report_type": "一季报",
                    "ann_date": date(2026, 7, 14),
                    "report_period": date(2026, 6, 30),
                    "revenue": Decimal("120.5"),
                    "n_income_attr_p": Decimal("18.2"),
                    "available_at": available_at,
                }
            ]
        ),
        "cash_flow": pd.DataFrame(
            [
                {
                    "ts_code": "600000.SH",
                    "report_period": date(2026, 6, 30),
                    "n_cashflow_act": Decimal("20.1"),
                    "available_at": available_at,
                }
            ]
        ),
    }
    features = {
        "stock_trading_context": pd.DataFrame(
            [
                {
                    "analysis_date": FORMATION_DATE,
                    "ts_code": "600000.SH",
                    "return_20d": Decimal("0.126"),
                    "available_at": CUTOFF,
                }
            ]
        )
    }
    return _snapshot(facts=facts, features=features)


def test_routes_only_current_scene_knowledge_and_audits_non_applicable_entries():
    packet = _build(_earnings_snapshot(), _hypothesis())

    current_ids = {
        entry.knowledge_id
        for entry in REGISTRY.entries
        if entry.version_status == "current"
    }
    historical_ids = {
        entry.knowledge_id
        for entry in REGISTRY.entries
        if entry.version_status == "historical_only"
    }
    routed_ids = {record.knowledge_id for record in packet.knowledge_routing}
    prepared_ids = {
        record.knowledge_id
        for record in packet.knowledge_routing
        if record.status is KnowledgeRoutingStatus.PREPARED_FOR_JUDGMENT
    }

    assert routed_ids == current_ids
    assert not routed_ids.intersection(historical_ids)
    assert prepared_ids
    assert "src_cn_earnings_disclosure_hierarchy" in prepared_ids
    assert prepared_ids < current_ids
    assert any(
        record.status is KnowledgeRoutingStatus.NOT_APPLICABLE
        and record.reason
        for record in packet.knowledge_routing
    )
    assert all(
        record.evidence_ids
        for record in packet.knowledge_routing
        if record.status is KnowledgeRoutingStatus.PREPARED_FOR_JUDGMENT
    )


def test_explicit_historical_only_reference_fails_closed():
    with pytest.raises(ValueError, match="historical_only"):
        _build(
            _earnings_snapshot(),
            _hypothesis(),
            requested_knowledge_ids=("src_liu_stambaugh_yuan_2019",),
        )


def test_unknown_or_non_selected_explicit_knowledge_reference_fails_closed():
    with pytest.raises(ValueError, match="unknown knowledge"):
        _build(
            _earnings_snapshot(),
            _hypothesis(),
            requested_knowledge_ids=("not-registered",),
        )
    with pytest.raises(ValueError, match="not applicable"):
        _build(
            _earnings_snapshot(),
            _hypothesis(),
            requested_knowledge_ids=("src_cn_delisting_enforcement_2024",),
        )


def test_evidence_is_structurally_separated_and_every_numeric_value_has_an_id():
    packet = _build(_earnings_snapshot(), _hypothesis())

    assert packet.api_facts
    assert packet.local_observations
    assert packet.model_judgments == ()
    assert "user_expression" not in CandidateEvidencePacket.model_fields
    assert all(item.kind is EvidenceKind.API_FACT for item in packet.api_facts)
    assert all(
        item.kind is EvidenceKind.LOCAL_OBSERVATION
        for item in packet.local_observations
    )
    assert all(
        item.kind is EvidenceKind.LOCAL_OBSERVATION
        for item in packet.local_observations
        if item.source_evidence_id is not None
    )
    numeric = [
        item
        for item in (*packet.api_facts, *packet.local_observations)
        if isinstance(item.value, (int, float, Decimal))
        and not isinstance(item.value, bool)
    ]
    assert numeric
    assert all(item.evidence_id and item.input_hash for item in numeric)
    assert len({item.evidence_id for item in numeric}) == len(numeric)

    with pytest.raises(ValidationError):
        ModelJudgment.model_validate(
            {
                "judgment_id": "judge-1",
                "text": "模型不得改写收入事实",
                "evidence_ids": (packet.api_facts[0].evidence_id,),
                "value": 999,
            }
        )


def test_knowledge_is_not_prepared_when_required_fields_exist_only_across_split_rows():
    snapshot = _earnings_snapshot()
    split = pd.DataFrame(
        [
            {
                "ts_code": "600000.SH",
                "report_period": date(2026, 6, 30),
                "ann_date": date(2026, 7, 14),
                "type": "预增",
                "p_change_min": Decimal("20"),
                "p_change_max": pd.NA,
                "available_at": datetime(2026, 7, 14, 18, tzinfo=SHANGHAI),
            },
            {
                "ts_code": "600000.SH",
                "report_period": date(2026, 6, 30),
                "ann_date": date(2026, 7, 14),
                "type": "预增",
                "p_change_min": pd.NA,
                "p_change_max": Decimal("30"),
                "available_at": datetime(2026, 7, 14, 18, tzinfo=SHANGHAI),
            },
        ]
    )
    snapshot.facts._frames["earnings_forecast"] = split
    packet = _build(snapshot, _hypothesis())
    record = next(
        item
        for item in packet.knowledge_routing
        if item.knowledge_id == "src_cn_earnings_disclosure_hierarchy"
    )

    assert record.status is KnowledgeRoutingStatus.NOT_APPLICABLE
    assert "not_available_as_of" in record.reason
    assert "earnings_forecast" in record.reason


def test_packet_has_every_required_section_and_does_not_claim_missing_completeness():
    packet = _build(_snapshot(), _unresolved_hypothesis())

    assert packet.api_facts == ()
    assert packet.model_judgments == ()
    assert {section.name for section in packet.sections} == set(EvidenceSectionName)
    unavailable = [
        section
        for section in packet.sections
        if section.availability is EvidenceAvailability.NOT_AVAILABLE_AS_OF
    ]
    assert unavailable
    assert all(not section.evidence_ids for section in unavailable)
    assert all(
        any(
            reason in section.note
            for reason in (
                "not_materialized",
                "coverage_gap",
                "not_available_as_of",
                "candidate_has_no_row",
                "invalid_schema",
                "incomplete",
            )
        )
        for section in unavailable
    )
    assert packet.unknowns
    assert all(value.text for value in packet.unknowns)


def test_task5_statuses_only_claim_input_readiness_not_opportunity_semantics():
    assert "COMPLETE" not in EvidenceCardStatus.__members__
    assert "AVAILABLE" not in EvidenceAvailability.__members__
    assert (
        EvidenceCardStatus.EVIDENCE_READY_FOR_JUDGMENT.value
        == "evidence_ready_for_judgment"
    )


def test_event_and_target_inputs_are_recomputed_locally_from_formation_facts():
    event_time = datetime(2026, 7, 14, 18, tzinfo=SHANGHAI)
    available = event_time
    facts = {
        "announcement": pd.DataFrame(
            [{
                "ts_code": "600000.SH",
                "announcement_id": "A-1",
                "announcement_time": event_time,
                "title": "formation-visible event",
                "available_at": available,
            }]
        ),
        "equity_daily": pd.DataFrame(
            [
                {"ts_code": "600000.SH", "trade_date": date(2026, 7, 14), "close": Decimal("10")},
                {"ts_code": "600000.SH", "trade_date": date(2026, 7, 15), "close": Decimal("11")},
            ]
        ),
        "index_daily": pd.DataFrame(
            [
                {"index_code": "000905.SH", "trade_date": date(2026, 7, 14), "close": Decimal("5000")},
                {"index_code": "000300.SH", "trade_date": date(2026, 7, 14), "close": Decimal("4000")},
                {"index_code": "000300.SH", "trade_date": date(2026, 7, 15), "close": Decimal("4040")},
                {"index_code": "000905.SH", "trade_date": date(2026, 7, 15), "close": Decimal("6000")},
            ]
        ),
        "industry_daily": pd.DataFrame(
            [
                {"industry_code": "I1", "trade_date": date(2026, 7, 14), "close": Decimal("100")},
                {"industry_code": "I1", "trade_date": date(2026, 7, 15), "close": Decimal("102")},
            ]
        ),
    }
    response = evidence_module._compute_event_price_response(
        _snapshot(), "600000.SH", facts
    )

    assert response is not None
    assert response["pre_event_trade_date"] == date(2026, 7, 14)
    assert response["formation_trade_date"] == FORMATION_DATE
    assert response["market_benchmark_code"] == "000300.SH"
    assert response["stock_return_to_formation"] == Decimal("0.1")
    assert response["market_return_to_formation"] == Decimal("0.01")
    assert response["stock_market_relative_return"] == Decimal("0.09")
    assert response["formula_version"] == "event-price-response-v2"
    assert len(response["event_record_id"]) == 64
    assert len(response["input_hash"]) == 64

    features = {
        "stock_trading_context": pd.DataFrame(
            [{
                "return_20d": Decimal("0.12"),
                "relative_return_20d": Decimal("0.08"),
                "realized_volatility_20d_annualized": Decimal("0.30"),
                "atr_ratio_20d": Decimal("0.025"),
                "price_location_60d": Decimal("0.70"),
            }]
        )
    }
    target = evidence_module._compute_target_path_inputs(
        _snapshot(),
        "600000.SH",
        facts,
        features,
        {"announcement": {"e1"}, "balance_sheet": {"e2"}},
    )

    assert target is not None
    assert target["current_baseline"] == Decimal("11")
    assert target["target_return"] == Decimal("0.20")
    assert target["target_price"] == Decimal("13.20")
    assert (target["horizon_days_10"], target["horizon_days_20"], target["horizon_days_30"]) == (10, 20, 30)
    assert target["candidate_driver_evidence_ids"] == ("e1",)
    assert target["counterevidence_input_ids"] == ("e2",)
    assert target["formula_version"] == "target-path-inputs-v2"
    assert len(target["input_hash"]) == 64


def test_public_packet_builder_rejects_handcrafted_components():
    with pytest.raises(ValueError, match="registered scan provenance"):
        build_candidate_packet(_snapshot(), object(), "600000.SH")  # type: ignore[arg-type]


def test_input_sufficiency_does_not_decide_direction_or_valuation_meaning():
    facts = {
        "main_business": pd.DataFrame(
            [{
                "report_period": date(2026, 6, 30),
                "item_name": "segment",
                "bz_sales": Decimal("0"),
                "bz_profit": Decimal("-1"),
            }]
        ),
        "income_statement": pd.DataFrame(
            [{"report_period": date(2026, 6, 30), "revenue": Decimal("100")}]
        ),
    }
    industry = pd.DataFrame(
        [
            {"trade_date": date(2026, 7, 14), "demand_change": Decimal("-2")},
            {"trade_date": date(2026, 7, 15), "demand_change": Decimal("0")},
        ]
    )
    valuation = pd.DataFrame(
        [
            {"ts_code": "600000.SH", "trade_date": date(2026, 7, 14), "pe_ttm": 999, "pb": 99, "ps_ttm": 88, "total_mv": 100},
            {"ts_code": "600000.SH", "trade_date": date(2026, 7, 15), "pe_ttm": 1000, "pb": 100, "ps_ttm": 89, "total_mv": 101},
            {"ts_code": "600001.SH", "trade_date": date(2026, 7, 15), "pe_ttm": 500, "pb": 50, "ps_ttm": 40, "total_mv": 90},
        ]
    )

    assert evidence_module._has_business_contribution_inputs(facts)
    assert evidence_module._has_optional_measure_periods(
        industry,
        ("demand_change", "shipment_change", "adoption_change"),
        minimum_periods=2,
    )
    assert evidence_module._has_valuation_context_inputs(
        valuation, "600000.SH"
    )
    assert (
        EvidenceAvailability.EVIDENCE_READY_FOR_JUDGMENT.value
        == "evidence_ready_for_judgment"
    )
    assert "policy_fact" not in evidence_module._OPTIONAL_API_FIELDS["industry_daily"]
    assert "risk_mitigation_fact" not in evidence_module._OPTIONAL_API_FIELDS["announcement"]


def test_valuation_readiness_requires_candidate_history_and_same_day_peer():
    peer_history_cannot_replace_candidate_history = pd.DataFrame(
        [
            {"ts_code": "600000.SH", "trade_date": date(2026, 7, 15), "pe_ttm": 50, "pb": 5, "ps_ttm": 4, "total_mv": 100},
            {"ts_code": "600001.SH", "trade_date": date(2026, 7, 14), "pe_ttm": 10, "pb": 1, "ps_ttm": 1, "total_mv": 80},
            {"ts_code": "600001.SH", "trade_date": date(2026, 7, 15), "pe_ttm": 11, "pb": 1, "ps_ttm": 1, "total_mv": 81},
        ]
    )
    peer_on_another_day_cannot_replace_same_day_peer = pd.DataFrame(
        [
            {"ts_code": "600000.SH", "trade_date": date(2026, 7, 14), "pe_ttm": 49, "pb": 5, "ps_ttm": 4, "total_mv": 99},
            {"ts_code": "600000.SH", "trade_date": date(2026, 7, 15), "pe_ttm": 50, "pb": 5, "ps_ttm": 4, "total_mv": 100},
            {"ts_code": "600001.SH", "trade_date": date(2026, 7, 14), "pe_ttm": 10, "pb": 1, "ps_ttm": 1, "total_mv": 80},
        ]
    )

    assert not evidence_module._has_valuation_context_inputs(
        peer_history_cannot_replace_candidate_history, "600000.SH"
    )
    assert not evidence_module._has_valuation_context_inputs(
        peer_on_another_day_cannot_replace_same_day_peer, "600000.SH"
    )


def test_event_readiness_rejects_another_record_or_report_period_response():
    event_time = datetime(2026, 7, 14, 18, tzinfo=SHANGHAI)
    announcement = pd.DataFrame(
        [{
            "ts_code": "600000.SH",
            "announcement_id": "A-deep",
            "announcement_time": event_time,
            "title": "terminated contract",
            "available_at": event_time,
            "body": "terminated",
            "amount": 0,
            "subject": "contract",
            "execution_conditions": "failed",
            "event_stage": "terminated",
            "failure_conditions": "triggered",
            "deep_read_completed": True,
            "deep_read_input_hash": "f" * 64,
        }]
    )
    response = pd.DataFrame(
        [{
            "event_time": event_time,
            "event_dataset": "announcement",
            "event_record_id": "1" * 64,
            "source_event_row_key": "2" * 64,
            "source_event_evidence_id": "3" * 64,
            "source_record_id": "A-other",
            "source_report_period": "not_applicable",
            "source_deep_read_status": "complete",
            "source_deep_read_input_hash": "f" * 64,
            "market_benchmark_code": "000300.SH",
            "industry_code": "I1",
            "stock_return_to_formation": -0.10,
            "market_return_to_formation": -0.01,
            "industry_return_to_formation": -0.05,
            "stock_market_relative_return": -0.09,
            "stock_industry_relative_return": -0.05,
            "formula_version": "event-price-response-v2",
            "input_hash": "4" * 64,
        }]
    )
    earnings = pd.DataFrame(
        [{
            "ts_code": "600000.SH",
            "report_period": date(2026, 6, 30),
            "announcement_type": "forecast",
            "ann_date": date(2026, 7, 14),
            "type": "loss_warning",
            "p_change_min": -60,
            "p_change_max": -40,
            "available_at": event_time,
        }]
    )
    facts = {
        "earnings_forecast": earnings,
        "income_statement": pd.DataFrame([{
            "report_period": date(2026, 6, 30),
            "revenue": 80,
            "n_income_attr_p": -10,
        }]),
        "cash_flow": pd.DataFrame([{
            "report_period": date(2026, 6, 30),
            "n_cashflow_act": -20,
        }]),
    }
    earnings_response = response.assign(
        event_dataset="earnings_forecast",
        source_report_period="2026-03-31",
    )

    assert not evidence_module._has_aligned_company_event_inputs(
        announcement, response, CUTOFF, "600000.SH"
    )
    assert not evidence_module._has_aligned_earnings_event_inputs(
        facts, earnings_response, CUTOFF, "600000.SH"
    )


@pytest.mark.parametrize("invalid_completed", ["false", 1])
def test_deep_read_completed_requires_literal_python_true(invalid_completed):
    event_time = datetime(2026, 7, 14, 18, tzinfo=SHANGHAI)
    announcement = pd.DataFrame(
        [{
            "ts_code": "600000.SH",
            "announcement_id": "A-strict-bool",
            "announcement_time": event_time,
            "title": "terminated contract",
            "available_at": event_time,
            "body": "terminated",
            "amount": 0,
            "subject": "contract",
            "execution_conditions": "failed",
            "event_stage": "terminated",
            "failure_conditions": "triggered",
            "deep_read_completed": invalid_completed,
            "deep_read_input_hash": "f" * 64,
        }]
    )
    facts = {
        "announcement": announcement,
        "equity_daily": pd.DataFrame([
            {"ts_code": "600000.SH", "trade_date": date(2026, 7, 14), "close": 10},
            {"ts_code": "600000.SH", "trade_date": date(2026, 7, 15), "close": 9},
        ]),
        "index_daily": pd.DataFrame([
            {"index_code": "000300.SH", "trade_date": date(2026, 7, 14), "close": 4000},
            {"index_code": "000300.SH", "trade_date": date(2026, 7, 15), "close": 3960},
        ]),
        "industry_daily": pd.DataFrame([
            {"industry_code": "I1", "trade_date": date(2026, 7, 14), "close": 100},
            {"industry_code": "I1", "trade_date": date(2026, 7, 15), "close": 95},
        ]),
    }

    response = evidence_module._compute_event_price_response(
        _snapshot(), "600000.SH", facts
    )

    assert response is not None
    assert response["source_deep_read_status"] == "not_complete"
    assert not evidence_module._has_aligned_company_event_inputs(
        announcement, pd.DataFrame([response]), CUTOFF, "600000.SH"
    )


def test_distress_ready_card_cites_each_requirement_and_aligned_risk_event():
    event_time = datetime(2026, 7, 14, 18, tzinfo=SHANGHAI)
    periods = (date(2026, 3, 31), date(2026, 6, 30))
    facts = {
        "security_master": pd.DataFrame([{"ts_code": "600000.SH"}]),
        "holder_trade": pd.DataFrame([{
            "ts_code": "600000.SH",
            "provider_record_id": "H-1",
            "ann_date": date(2026, 7, 14),
            "holder_name": "holder",
            "in_de": "DE",
            "change_vol": 100,
            "available_at": event_time,
        }]),
        "income_statement": pd.DataFrame([
            {"report_period": period, "revenue": 100 - index * 20, "n_income_attr_p": -5 - index * 5}
            for index, period in enumerate(periods)
        ]),
        "balance_sheet": pd.DataFrame([
            {
                "report_period": period,
                "total_assets": 100,
                "total_liab": 90,
                "money_cap": 5,
                "st_borr": 40,
                "non_cur_liab_due_1y": 20,
            }
            for period in periods
        ]),
        "cash_flow": pd.DataFrame([
            {"report_period": period, "n_cashflow_act": -10 - index * 10}
            for index, period in enumerate(periods)
        ]),
        "financial_indicator": pd.DataFrame([
            {"report_period": period, "roe": -5 - index * 2}
            for index, period in enumerate(periods)
        ]),
        "daily_basic": pd.DataFrame([
            {"ts_code": "600000.SH", "trade_date": date(2026, 7, 14), "pe_ttm": -50, "pb": 10, "ps_ttm": 20, "total_mv": 100},
            {"ts_code": "600000.SH", "trade_date": date(2026, 7, 15), "pe_ttm": -60, "pb": 12, "ps_ttm": 25, "total_mv": 90},
            {"ts_code": "600001.SH", "trade_date": date(2026, 7, 15), "pe_ttm": 5, "pb": 1, "ps_ttm": 1, "total_mv": 80},
        ]),
        "equity_daily": pd.DataFrame([
            {"ts_code": "600000.SH", "trade_date": date(2026, 7, 14), "close": 10},
            {"ts_code": "600000.SH", "trade_date": date(2026, 7, 15), "close": 9},
        ]),
        "index_daily": pd.DataFrame([
            {"index_code": "000300.SH", "trade_date": date(2026, 7, 14), "close": 4000},
            {"index_code": "000300.SH", "trade_date": date(2026, 7, 15), "close": 3960},
        ]),
        "industry_daily": pd.DataFrame([
            {"industry_code": "I1", "trade_date": date(2026, 7, 14), "close": 100},
            {"industry_code": "I1", "trade_date": date(2026, 7, 15), "close": 95},
        ]),
    }
    event_response = evidence_module._compute_event_price_response(
        _snapshot(), "600000.SH", facts
    )
    assert event_response is not None
    ready_datasets = (
        "security_master",
        "holder_trade",
        "income_statement",
        "balance_sheet",
        "cash_flow",
        "financial_indicator",
        "daily_basic",
        "event_price_response",
    )
    coverage = tuple(
        evidence_module.EvidenceInputCoverage(
            dataset=dataset,
            kind="local" if dataset == "event_price_response" else "fact",
            scope="candidate",
            status=EvidenceInputStatus.READY,
            required_fields=("formation_visible",),
            observed_rows=1,
            detail="controlled ready input",
        )
        for dataset in ready_datasets
    )
    dataset_ids = {
        dataset: {f"{dataset}-evidence"} for dataset in ready_datasets
    }
    dataset_ids["holder_trade"].add(
        str(event_response["source_event_evidence_id"])
    )

    cards = evidence_module._build_opportunity_cards(
        coverage,
        facts,
        {"event_price_response": pd.DataFrame([event_response])},
        dataset_ids,
        CUTOFF,
        "600000.SH",
    )
    card = next(
        item
        for item in cards
        if item.opportunity.value == "distress_reversal"
    )

    assert card.status is EvidenceCardStatus.EVIDENCE_READY_FOR_JUDGMENT
    assert {
        "security_master-evidence",
        "holder_trade-evidence",
        "income_statement-evidence",
        "balance_sheet-evidence",
        "cash_flow-evidence",
        "financial_indicator-evidence",
        "daily_basic-evidence",
        "event_price_response-evidence",
    }.issubset(card.evidence_ids)
    requirement_bindings = dict(card.requirement_evidence_ids)
    assert set(requirement_bindings) == set(card.required_requirements)
    assert all(requirement_bindings[requirement] for requirement in card.required_requirements)
    assert "holder_trade-evidence" in requirement_bindings[
        "raw distress and financing-risk inputs"
    ]
    assert {
        "holder_trade-evidence",
        "event_price_response-evidence",
    }.issubset(
        requirement_bindings["event-aligned relative price response input"]
    )

    missing_aligned_source = {
        dataset: set(evidence_ids)
        for dataset, evidence_ids in dataset_ids.items()
    }
    missing_aligned_source["holder_trade"].remove(
        str(event_response["source_event_evidence_id"])
    )
    incomplete = next(
        item
        for item in evidence_module._build_opportunity_cards(
            coverage,
            facts,
            {"event_price_response": pd.DataFrame([event_response])},
            missing_aligned_source,
            CUTOFF,
            "600000.SH",
        )
        if item.opportunity.value == "distress_reversal"
    )
    assert incomplete.status is EvidenceCardStatus.INCOMPLETE
    assert incomplete.missing_requirements == (
        "event-aligned relative price response input",
    )


def test_future_dated_source_row_is_rejected_instead_of_silently_omitted():
    future = datetime(2026, 7, 16, 9, tzinfo=SHANGHAI)
    snapshot = _snapshot(
        facts={
            "earnings_forecast": pd.DataFrame(
                [
                    {
                        "ts_code": "600000.SH",
                        "type": "预增",
                        "p_change_min": Decimal("20"),
                        "p_change_max": Decimal("30"),
                        "available_at": future,
                    }
                ]
            )
        }
    )

    with pytest.raises(ValueError, match="after formation cutoff"):
        _build(snapshot, _hypothesis())


def test_derived_row_for_another_analysis_date_is_rejected():
    market = pd.DataFrame(
        [
            {
                "analysis_date": date(2026, 7, 16),
                "median_return_1d": Decimal("0.004"),
                "breadth_1d": Decimal("0.61"),
                "market_turnover_amount": Decimal("900000000000"),
                "realized_volatility_20d_annualized": Decimal("0.22"),
                "return_dispersion_1d": Decimal("0.018"),
                "coverage_status": "complete",
            }
        ]
    )

    with pytest.raises(ValueError, match="derived analysis_date"):
        _build(
            _snapshot(features={"market_context": market}),
            _unresolved_hypothesis(),
        )


def test_packet_contract_rejects_judgment_or_section_references_to_unknown_evidence():
    datum = EvidenceDatum(
        evidence_id="fact-1",
        kind=EvidenceKind.API_FACT,
        dataset="income_statement",
        field="revenue",
        row_key="row-1",
        value=Decimal("120.5"),
        business_time=datetime(2026, 6, 30, tzinfo=SHANGHAI),
        available_at=datetime(2026, 7, 14, 18, tzinfo=SHANGHAI),
        input_hash="c" * 64,
    )
    packet = _build(_earnings_snapshot(), _hypothesis())
    payload = packet.model_dump()
    payload["api_facts"] = (datum.model_dump(),)
    payload["model_judgments"] = (
        {
            "judgment_id": "judge-1",
            "text": "引用不存在的证据",
            "evidence_ids": ("absent",),
        },
    )

    with pytest.raises(ValidationError, match="unknown evidence"):
        CandidateEvidencePacket.model_validate(payload)


def test_fixed_framework_evidence_need_materializes_market_context_without_knowledge_requirement():
    market = pd.DataFrame(
        [
            {
                "analysis_date": FORMATION_DATE,
                "median_return_1d": Decimal("0.004"),
                "breadth_1d": Decimal("0.61"),
                "market_turnover_amount": Decimal("900000000000"),
                "realized_volatility_20d_annualized": Decimal("0.22"),
                "return_dispersion_1d": Decimal("0.018"),
                "coverage_status": "complete",
            }
        ]
    )
    packet = _build(
        _snapshot(features={"market_context": market}),
        _unresolved_hypothesis(),
    )

    assert any(
        item.dataset == "market_context" and item.field == "median_return_1d"
        for item in packet.local_observations
    )
    coverage = next(item for item in packet.input_coverage if item.dataset == "market_context")
    assert coverage.status is EvidenceInputStatus.READY
    section = next(item for item in packet.sections if item.name is EvidenceSectionName.MARKET_CONSTRAINTS)
    assert section.availability is EvidenceAvailability.NOT_AVAILABLE_AS_OF
    assert not section.evidence_ids
    assert "security_master=not_materialized" in section.note


def test_evidence_input_contract_covers_every_task4_route_fact_and_task5_input():
    _, _, _, route_plan = _catalog_and_route_plan()
    contract = {item.dataset: item for item in evidence_input_contract()}

    assert set(route_plan).issubset(contract)
    assert {
        "market_context",
        "sector_hotspot",
        "stock_trading_context",
        "company_profile",
        "financial_indicator",
        "daily_basic",
        "equity_daily",
        "index_daily",
        "security_master",
        "stock_limit",
        "suspension",
        "event_price_response",
        "target_path_context",
    }.issubset(contract)
    assert all(item.required_fields and item.scope for item in contract.values())


def test_evidence_fact_plan_rejects_unattested_manifest_injection():
    extras = (
        {
            "dataset": "company_profile",
            "partition": "company-profile",
            "row_count": 1,
            "resolved_row_count": 1,
            "resolved_content_hash": "b" * 64,
        },
        *(
            {
                "dataset": dataset,
                "partition": "2026-07-15",
                "row_count": 1,
                "resolved_row_count": 1,
                "resolved_content_hash": "c" * 64,
            }
            for dataset in (
                "daily_basic",
                "equity_daily",
                "index_daily",
                "security_master",
                "stock_limit",
                "suspension",
                "adj_factor",
            )
        ),
    )
    source, _, _, route_plan = _catalog_and_route_plan(
        extra_partitions=extras
    )

    with pytest.raises(TypeError, match="source_catalog"):
        build_evidence_fact_plan(
            route_fact_plan=route_plan,
            source_catalog=source,  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="builder"):
        EvidenceFactPlan({"equity_daily": ("2026-07-15",)})


def test_registry_must_exactly_match_frozen_official_file_and_is_fully_audited():
    packet = _build(_earnings_snapshot(), _hypothesis())

    assert packet.registry_audit.registry_hash == REGISTRY.registry_hash
    assert packet.registry_audit.registry_file_sha256 == "40762d5736b15d05e616a70279f7586c3e4da5562ba819393c4dbda96cdaafeb"
    assert packet.registry_audit.current_count == 27
    assert packet.registry_audit.historical_only_count == 3
    assert packet.registry_audit.current_ids_hash == "d189d87d8c19510e1b5d9c25b5cebb1df72c89c8f2133f3c9c2cdd14f71b7fae"
    assert packet.registry_audit.historical_only_ids_hash == "b87cf04aba6b094510f776d386761fc91a5a2b51ca384e4dfa280bb900a052fe"
    assert all(
        item.version_status == "current" and item.entry_content_hash
        for item in packet.registry_audit.prepared_entries
    )

    mutated = REGISTRY.model_copy(update={"entries": REGISTRY.entries[:-1]})
    with pytest.raises(ValueError, match="frozen official registry"):
        _build(_earnings_snapshot(), _hypothesis(), mutated)


def test_candidate_scoped_dataset_without_security_key_fails_closed():
    snapshot = _earnings_snapshot()
    snapshot.facts._frames["earnings_forecast"] = snapshot.facts._frames[
        "earnings_forecast"
    ].drop(columns=["ts_code"])

    with pytest.raises(ValueError, match="candidate dataset.*security key"):
        _build(snapshot, _hypothesis())


def test_fact_field_whitelist_separates_local_announcement_classification():
    snapshot = _earnings_snapshot()
    announced = datetime(2026, 7, 14, 18, tzinfo=SHANGHAI)
    snapshot.facts._frames["announcement"] = pd.DataFrame(
        [
            {
                "ts_code": "600000.SH",
                "announcement_id": "A1",
                "announcement_time": announced,
                "title": "正式公告",
                "available_at": announced,
                "candidate_event_types": ("contract",),
                "classification_is_fact": False,
                "classification_version": "title-classifier-v1",
                "hard_risk_candidate": True,
                "risk_mitigation_fact": True,
                "secret_future_return": Decimal("9.99"),
            }
        ]
    )
    packet = _build(snapshot, _hypothesis())
    announcement_api = [item for item in packet.api_facts if item.dataset == "announcement"]
    announcement_local = [
        item for item in packet.local_observations if item.dataset == "announcement"
    ]

    assert {item.field for item in announcement_api} == {
        "ts_code",
        "announcement_id",
        "announcement_time",
        "title",
        "available_at",
    }
    assert {
        "candidate_event_types",
        "classification_is_fact",
        "classification_version",
        "hard_risk_candidate",
    }.issubset({item.field for item in announcement_local})
    assert not any(item.field == "secret_future_return" for item in (*announcement_api, *announcement_local))
    assert not any(
        item.field == "risk_mitigation_fact"
        for item in (*announcement_api, *announcement_local)
    )


def test_composite_sections_and_cards_stay_missing_without_dedicated_semantic_observation():
    packet = _build(_earnings_snapshot(), _hypothesis())
    by_name = {section.name: section for section in packet.sections}
    cards = {card.opportunity: card for card in packet.opportunity_cards}

    assert by_name[EvidenceSectionName.POST_FACT_PRICE_RESPONSE].availability is EvidenceAvailability.NOT_AVAILABLE_AS_OF
    assert by_name[EvidenceSectionName.CURRENT_PRICE_TO_TARGET_CONDITIONS].availability is EvidenceAvailability.NOT_AVAILABLE_AS_OF
    assert cards[OpportunityType.EARNINGS_REVALUATION].status is EvidenceCardStatus.INCOMPLETE
    assert cards[OpportunityType.EARNINGS_REVALUATION].missing_requirements
    assert not cards[OpportunityType.EARNINGS_REVALUATION].evidence_ids


def test_input_coverage_distinguishes_not_materialized_from_candidate_without_row():
    snapshot = _earnings_snapshot()
    snapshot.facts._frames["balance_sheet"] = pd.DataFrame(
        [
            {
                "ts_code": "000001.SZ",
                "report_period": date(2026, 6, 30),
                "total_assets": Decimal("100"),
                "total_liab": Decimal("20"),
                "available_at": datetime(2026, 7, 14, 18, tzinfo=SHANGHAI),
            }
        ]
    )
    packet = _build(snapshot, _hypothesis())
    coverage = {item.dataset: item for item in packet.input_coverage}

    assert coverage["daily_basic"].status is EvidenceInputStatus.NOT_MATERIALIZED
    assert coverage["earnings_forecast"].status is EvidenceInputStatus.READY
    assert any(item.status is EvidenceInputStatus.CANDIDATE_HAS_NO_ROW for item in packet.input_coverage)
    assert "not_materialized" in next(
        section.note
        for section in packet.sections
        if section.name is EvidenceSectionName.VALUATION_CONTEXT
    )


def test_cutoff_must_be_exact_shanghai_end_of_formation_day():
    hypothesis = _hypothesis()
    wrong = datetime(2026, 7, 15, 0, 0, 0, tzinfo=SHANGHAI)
    snapshot = _earnings_snapshot()
    snapshot.as_of = wrong
    hypothesis = replace(hypothesis, cutoff=wrong)

    with pytest.raises(ValueError, match="23:59:59"):
        _build(snapshot, hypothesis)

    equivalent_utc = datetime(2026, 7, 15, 15, 59, 59, tzinfo=timezone.utc)
    snapshot = _earnings_snapshot()
    snapshot.as_of = equivalent_utc
    hypothesis = replace(_hypothesis(), cutoff=equivalent_utc)
    with pytest.raises(ValueError, match="Asia/Shanghai"):
        _build(snapshot, hypothesis)


def test_numeric_free_text_is_forbidden_even_with_an_unverified_marker():
    with pytest.raises(ValidationError, match="numeric free text"):
        ModelJudgment(
            judgment_id="j1",
            text="收入增长999%",
            evidence_ids=("fact-1",),
        )
    with pytest.raises(ValidationError, match="numeric free text"):
        EvidenceText(text="未来20日验证", evidence_ids=())

    with pytest.raises(ValidationError, match="numeric free text"):
        ModelJudgment(
            judgment_id="j1",
            text="收入增长999% [evidence:fact-1]",
            evidence_ids=("fact-1",),
        )


def test_route_observation_is_bound_to_route_manifest_and_snapshot_input_hash():
    hypothesis = _hypothesis()
    snapshot = _earnings_snapshot()
    evidence_plan, route_policy, original = _audit_inputs(snapshot, hypothesis)
    first = _build(snapshot, hypothesis)
    manifests = list(original)
    earnings_index = next(
        index
        for index, manifest in enumerate(manifests)
        if manifest.route is DiscoveryRoute.EARNINGS
    )
    manifests[earnings_index] = manifests[earnings_index].model_copy(
        update={"input_hash": "f" * 64}
    )
    second = _build_candidate_packet_from_verified_parts(
        snapshot,
        hypothesis,
        REGISTRY,
        evidence_plan=evidence_plan,
        route_policy=route_policy,
        route_manifests=tuple(manifests),
        verified_batch_receipt_hash="d" * 64,
        raw_lead_ledger_hash="e" * 64,
    )
    first_route = next(item for item in first.local_observations if item.source_evidence_id == "route-earnings")
    second_route = next(item for item in second.local_observations if item.source_evidence_id == "route-earnings")

    first_earnings = next(
        item
        for item in first.route_manifest_audit
        if item.route is DiscoveryRoute.EARNINGS
    )
    assert first_earnings.input_hash != "f" * 64
    assert first_route.input_hash != second_route.input_hash


def test_real_task3_snapshot_to_task4_scan_to_task5_packet_integration():
    path = Path("tests/evaluation/v3_backtest/test_routes.py")
    spec = importlib.util.spec_from_file_location("task4_test_fixture", path)
    assert spec is not None and spec.loader is not None
    route_fixture = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = route_fixture
    spec.loader.exec_module(route_fixture)
    feature_rows = route_fixture.feature_rows
    route_fixture_snapshot = route_fixture.snapshot

    source = route_fixture_snapshot()
    fact_frames = {
        ResearchDatasetId(dataset): pd.DataFrame(rows)
        for dataset, rows in source.facts.rows.items()
    }
    facts = FormationFactView(fact_frames, source.facts.manifest)
    route_features = feature_rows()
    market = pd.DataFrame(
        [
            {
                "analysis_date": FORMATION_DATE,
                "median_return_1d": 0.001,
                "breadth_1d": 0.55,
                "market_turnover_amount": 800_000_000_000,
                "realized_volatility_20d_annualized": 0.2,
                "return_dispersion_1d": 0.01,
                "coverage_status": "complete",
            }
        ]
    )
    features = FormationFeatureView(
        {
            "market_context": market,
            "sector_hotspot": pd.DataFrame(route_features["sector_hotspot"]),
            "stock_trading_context": pd.DataFrame(route_features["stock_trading_context"]),
        }
    )
    formation = FormationSnapshot(
        analysis_date=FORMATION_DATE,
        as_of=CUTOFF,
        facts=facts,
        features=features,
        market_rows=1,
        sector_rows=3,
        stock_rows=5,
        limitations=(),
        cache_key="9" * 64,
        fact_manifest_hashes=(),
        formula_versions=(
            ("market_context", "market-context-v2"),
            ("sector_hotspot", "sector-hotspot-v3"),
            ("stock_trading_context", "stock-trading-context-v2"),
        ),
    )
    route_plan = route_fixture.route_plan()
    route_policy = build_route_window_policy(
        formation_date=FORMATION_DATE,
        fact_plan=route_plan,
        earnings_report_periods=(date(2026, 6, 30),),
        event_start=date(2026, 5, 20),
        price_absolute_tail_fraction=0.4,
    )
    batch = scan_routes(formation, route_policy)
    manifests, hypotheses = batch
    hypothesis = next(
        item
        for item in hypotheses
        if item.security_id == "000104.SZ"
        and DiscoveryRoute.PRICE_ANOMALY in item.discovery_routes
    )
    source = formation.facts.manifest["source_snapshot"]
    evidence_plan = EvidenceFactPlan(
        {
            dataset: tuple(
                str(item["partition"])
                for item in source["partitions"]
                if item["dataset"] == dataset
            )
            for dataset in dict.fromkeys(
                str(item["dataset"]) for item in source["partitions"]
            )
        },
        route_plan=route_plan,
        catalog_hash=route_plan.universe_catalog.catalog_hash,
        source_manifest_hash=source["input_manifest_hash"],
        source_attestation_hash=route_plan.universe_catalog.source_attestation_hash,
        source_as_of=source["as_of"],
        source_entries=source["partitions"],
        _token=evidence_module._EVIDENCE_PLAN_TOKEN,
    )
    packet = _build_candidate_packet_from_verified_parts(
        formation,
        hypothesis,
        REGISTRY,
        evidence_plan=evidence_plan,
        route_policy=route_policy,
        route_manifests=manifests,
        verified_batch_receipt_hash=batch.batch_hash,
        raw_lead_ledger_hash=evidence_module._verified_lead_ledger_hash(
            batch.lead_members(hypothesis.security_id)
        ),
    )

    assert packet.security_id == hypothesis.security_id
    assert any(item.route is DiscoveryRoute.PRICE_ANOMALY for item in packet.route_manifest_audit)
    assert any(item.source_evidence_id for item in packet.local_observations)
    assert any(item.status is EvidenceInputStatus.NOT_MATERIALIZED for item in packet.input_coverage)
    assert all(
        section.evidence_ids
        for section in packet.sections
        if section.availability
        is EvidenceAvailability.EVIDENCE_READY_FOR_JUDGMENT
    )


def test_actual_task3_materialization_can_feed_current_task4_and_task5(tmp_path):
    route_fixture = _task4_fixture_module()
    warehouse = ResearchWarehouse(tmp_path / "source")
    for dataset, partition, records in (
        (
            ResearchDatasetId.INDUSTRY_MEMBER,
            "sw2021-v1",
            [{
                "ts_code": "000001.SZ",
                "industry_system": "SW2021",
                "level": "L1",
                "industry_code": "I1",
                "classification_version": "sw2021-v1",
                "valid_from": date(2025, 1, 1),
                "valid_to": date(2099, 12, 31),
            }, {
                "ts_code": "600000.SH",
                "industry_system": "SW2021",
                "level": "L1",
                "industry_code": "I1",
                "classification_version": "sw2021-v1",
                "valid_from": date(2025, 1, 1),
                "valid_to": date(2099, 12, 31),
            }, {
                "ts_code": "600001.SH",
                "industry_system": "SW2021",
                "level": "L1",
                "industry_code": "I1",
                "classification_version": "sw2021-v1",
                "valid_from": date(2025, 1, 1),
                "valid_to": date(2099, 12, 31),
            }],
        ),
        (
            ResearchDatasetId.THEME_MEMBER,
            "controlled-theme-v1",
            [{
                "theme_code": "T1",
                "ts_code": "000002.SZ",
                "catalog_version": "controlled-theme-v1",
                "valid_from": date(2025, 1, 1),
                "valid_to": date(2099, 12, 31),
            }],
        ),
        (
            ResearchDatasetId.INDUSTRY_DAILY,
            "2026-07-14",
            [{
                "trade_date": date(2026, 7, 14),
                "industry_code": "I1",
                "close": 100.0,
                "demand_change": -2.0,
                "supply_change": 3.0,
                "price_change": -4.0,
                "inventory_change": 5.0,
            }],
        ),
        (
            ResearchDatasetId.INDUSTRY_DAILY,
            "2026-07-15",
            [{
                "trade_date": date(2026, 7, 15),
                "industry_code": "I1",
                "close": 95.0,
                "demand_change": -3.0,
                "supply_change": 4.0,
                "price_change": -5.0,
                "inventory_change": 6.0,
            }],
        ),
    ):
        if dataset in {
            ResearchDatasetId.INDUSTRY_MEMBER,
            ResearchDatasetId.THEME_MEMBER,
        }:
            future = datetime(2026, 7, 16, 8, tzinfo=SHANGHAI)
            warehouse.commit_batch(
                FactBatch(
                    dataset_id=dataset,
                    partition_value=partition,
                    source_name="actual-task3-fixture",
                    source_endpoint=dataset.value,
                    ingestion_run_id=f"future:{dataset.value}",
                    ingested_at=future,
                    default_available_at=future,
                    records=records,
                )
            )
        else:
            route_fixture._commit_controlled_partition(
                warehouse,
                dataset,
                partition,
                records,
            )
    isolation_id = hashlib.sha256(str(tmp_path).encode("utf-8")).hexdigest()[:12]
    isolation = Path("/tmp") / f"v3-complete-backtest-evidence-{isolation_id}"

    def feature_runner(read_only_warehouse, analysis_date, *, as_of):
        store = DerivedFeatureStore(read_only_warehouse.root)
        frames = {
            "market_context": pd.DataFrame(
                [{
                    "analysis_date": analysis_date,
                    "median_return_1d": 0.001,
                    "breadth_1d": 0.55,
                    "market_turnover_amount": 1.0,
                    "realized_volatility_20d_annualized": 0.2,
                    "return_dispersion_1d": 0.01,
                    "coverage_status": "complete",
                }]
            ),
            "sector_hotspot": pd.DataFrame(
                [{
                    "analysis_date": analysis_date,
                    "group_type": "industry",
                    "group_code": "I1",
                    "relative_return_20d": 0.08,
                    "median_return_20d": 0.06,
                    "breadth_20d": 0.7,
                    "turnover_share_average_20d": 0.02,
                    "top3_positive_contribution_1d": 0.4,
                    "high_volume_low_progress_flag": False,
                    "upper_wick_reversal_flag": False,
                    "narrow_participation_flag": False,
                    "turnover_return_divergence_flag": False,
                    "coverage_status": "complete",
                }]
            ),
            "stock_trading_context": pd.DataFrame(
                [
                    {
                        "analysis_date": analysis_date,
                        "ts_code": "600000.SH",
                        "return_20d": -0.25,
                        "relative_return_20d": -0.20,
                        "current_amount_ratio_20d": 1.0,
                        "price_location_60d": 0.1,
                        "realized_volatility_20d_annualized": 0.4,
                        "atr_ratio_20d": 0.05,
                        "coverage_status": "complete",
                    },
                    {
                        "analysis_date": analysis_date,
                        "ts_code": "600001.SH",
                        "return_20d": -0.10,
                        "relative_return_20d": -0.05,
                        "current_amount_ratio_20d": 1.0,
                        "price_location_60d": 0.2,
                        "realized_volatility_20d_annualized": 0.3,
                        "atr_ratio_20d": 0.04,
                        "coverage_status": "complete",
                    },
                    *[
                        {
                            "analysis_date": analysis_date,
                            "ts_code": f"00010{index}.SZ",
                            "return_20d": relative,
                            "relative_return_20d": relative,
                            "current_amount_ratio_20d": 1.0,
                            "price_location_60d": 0.5,
                            "realized_volatility_20d_annualized": 0.2,
                            "atr_ratio_20d": 0.02,
                            "coverage_status": "complete",
                        }
                        for index, relative in enumerate(
                            (0.01, -0.02, 0.03, 0.2, -0.5)
                        )
                    ],
                ]
            ),
        }
        versions = {
            "market_context": MARKET_CONTEXT_FORMULA_VERSION,
            "sector_hotspot": HOTSPOT_FORMULA_VERSION,
            "stock_trading_context": STOCK_CONTEXT_FORMULA_VERSION,
        }
        entity_keys = {
            "market_context": "analysis_date",
            "sector_hotspot": ("analysis_date", "group_type", "group_code"),
            "stock_trading_context": ("analysis_date", "ts_code"),
        }
        for feature_set, frame in frames.items():
            store.commit(
                feature_set,
                analysis_date,
                versions[feature_set],
                frame,
                input_manifest={
                    "fact_snapshot": {
                        "as_of": as_of.astimezone(timezone.utc).isoformat(),
                        "input_manifest_hash": "a" * 64,
                    }
                },
                entity_key=entity_keys[feature_set],
                quality_status="complete",
                run_id=f"actual:{feature_set}",
            )
        return SimpleNamespace(
            failed_feature_sets=(),
            errors=(),
            market_rows=1,
            sector_rows=1,
            stock_rows=7,
            limitations=(),
        )

    controlled_plan = {
        "industry_member": ("sw2021-v1",),
        "theme_member": ("controlled-theme-v1",),
        "industry_daily": ("2026-07-14", "2026-07-15"),
    }
    route_partition_seed = {
        "earnings_forecast": tuple(f"2026-{month:02d}" for month in range(1, 8)),
        "earnings_express": tuple(f"2026-{month:02d}" for month in range(1, 8)),
        "income_statement": ("2026-03-31", "2026-06-30"),
        "announcement": ("2026-06", "2026-07"),
        "main_business": ("2026-06-30",),
        "repurchase": ("2026-06", "2026-07"),
        "balance_sheet": ("2026-03-31", "2026-06-30"),
        "cash_flow": ("2026-03-31", "2026-06-30"),
        "company_profile": ("company-profile",),
    }
    report_period = date(2026, 6, 30)
    for dataset, partitions in route_partition_seed.items():
        for partition in partitions:
            if len(partition) == 7:
                known = (
                    date(2026, 7, 14)
                    if partition == "2026-07"
                    else date.fromisoformat(f"{partition}-01")
                )
            else:
                known = (
                    date(2026, 4, 30)
                    if partition == "2026-03-31"
                    else date(2026, 7, 1)
                )
            row_report_period = (
                date.fromisoformat(partition)
                if len(partition) == 10
                else report_period
            )
            common = {
                "ts_code": "600000.SH",
                "available_at": datetime.combine(
                    known,
                    time(18) if partition == "2026-07" else time(12),
                    tzinfo=SHANGHAI,
                ),
            }
            records = {
                "earnings_forecast": [{
                    **common,
                    "report_period": report_period,
                    "announcement_type": "forecast",
                    "ann_date": known,
                    "type": "loss_warning",
                    "p_change_min": -60.0,
                    "p_change_max": -40.0,
                }],
                "earnings_express": [{
                    **common,
                    "report_period": report_period,
                    "announcement_type": "express",
                    "ann_date": known,
                    "yoy_net_profit": -55.0,
                }],
                "income_statement": [{
                    **common,
                    "report_period": row_report_period,
                    "report_type": "quarterly",
                    "statement_type": "consolidated",
                    "revenue": 100.0 if partition == "2026-03-31" else 80.0,
                    "n_income_attr_p": -5.0 if partition == "2026-03-31" else -10.0,
                }],
                "announcement": [{
                    **common,
                    "announcement_id": f"A-{partition}",
                    "announcement_time": datetime.combine(
                        known,
                        time(18) if partition == "2026-07" else time(12),
                        tzinfo=SHANGHAI,
                    ),
                    "title": "contract terminated after failure condition",
                    "url": f"https://example.invalid/{partition}",
                    "candidate_event_types": ["contract"],
                    "deep_read_completed": partition == "2026-07",
                    "deep_read_input_hash": "f" * 64,
                    "body": "customer terminated the contract",
                    "amount": 0.0,
                    "subject": "terminated contract",
                    "execution_conditions": "not satisfied",
                    "event_stage": "terminated",
                    "failure_conditions": "triggered",
                }],
                "main_business": [{
                    **common,
                    "report_period": report_period,
                    "classification": "industry",
                    "item_name": "declining segment",
                    "bz_sales": 0.0,
                    "bz_profit": -1.0,
                }],
                "repurchase": [{
                    **common,
                    "provider_record_id": f"R-{partition}",
                    "ann_date": known,
                    "announcement_date": known,
                    "process": "terminated",
                    "amount": 0.0,
                    "vol": 0.0,
                }],
                "balance_sheet": [{
                    **common,
                    "report_period": row_report_period,
                    "report_type": "quarterly",
                    "statement_type": "consolidated",
                    "total_assets": 100.0,
                    "total_liab": 90.0,
                }],
                "cash_flow": [{
                    **common,
                    "report_period": row_report_period,
                    "report_type": "quarterly",
                    "statement_type": "consolidated",
                    "comp_type": "1",
                    "end_type": "1",
                    "ann_date": known,
                    "f_ann_date": known,
                    "update_flag": "0",
                    "n_cashflow_act": -5.0 if partition == "2026-03-31" else -20.0,
                }],
                "company_profile": [{
                    "ts_code": "600000.SH",
                    "valid_from": date(2020, 1, 1),
                    "main_business": "declining industrial service",
                    "business_scope": "industrial service",
                    "available_at": datetime(2020, 1, 1, 12, tzinfo=SHANGHAI),
                }],
            }[dataset]
            route_fixture._commit_controlled_partition(
                warehouse,
                ResearchDatasetId(dataset),
                partition,
                records,
            )
    for trade_date, candidate_close, market_close in (
        (date(2026, 7, 14), 10.0, 4000.0),
        (date(2026, 7, 15), 9.0, 3960.0),
    ):
        partition = trade_date.isoformat()
        route_fixture._commit_controlled_partition(
            warehouse,
            ResearchDatasetId.EQUITY_DAILY,
            partition,
            [{
                "trade_date": trade_date,
                "ts_code": "600000.SH",
                "open": candidate_close,
                "high": candidate_close,
                "low": candidate_close,
                "close": candidate_close,
                "pre_close": candidate_close,
                "change": 0.0,
                "pct_chg": 0.0,
                "volume": 100.0,
                "amount": 1_000.0,
            }],
        )
        route_fixture._commit_controlled_partition(
            warehouse,
            ResearchDatasetId.INDEX_DAILY,
            partition,
            [{
                "trade_date": trade_date,
                "index_code": "000300.SH",
                "close": market_close,
            }],
        )
        valuation_rows = [{
            "trade_date": trade_date,
            "ts_code": "600000.SH",
            "pe_ttm": -100.0,
            "pb": 20.0,
            "ps_ttm": 30.0,
            "total_mv": 100_000.0,
        }]
        if trade_date == FORMATION_DATE:
            valuation_rows.append({
                "trade_date": trade_date,
                "ts_code": "600001.SH",
                "pe_ttm": 5.0,
                "pb": 1.0,
                "ps_ttm": 0.5,
                "total_mv": 50_000.0,
            })
        route_fixture._commit_controlled_partition(
            warehouse,
            ResearchDatasetId.DAILY_BASIC,
            partition,
            valuation_rows,
        )
    controlled = materialize_formation_snapshot(
        warehouse,
        FORMATION_DATE,
        isolation / "controlled",
        fact_plan=controlled_plan,
        feature_runner=feature_runner,
    )
    attestation = build_source_catalog_attestation(
        warehouse, formation_date=FORMATION_DATE
    )
    catalog = build_frozen_universe_catalog(
        controlled.facts, source_attestation=attestation
    )
    route_plan = build_route_fact_plan(
        formation_date=FORMATION_DATE,
        earnings_report_periods=(date(2026, 6, 30),),
        event_start=date(2026, 6, 1),
        universe_catalog=catalog,
    )
    evidence_catalog = build_evidence_source_catalog(
        warehouse,
        formation_date=FORMATION_DATE,
        route_fact_plan=route_plan,
    )
    evidence_plan = build_evidence_fact_plan(
        route_fact_plan=route_plan,
        source_catalog=evidence_catalog,
    )
    formation = materialize_formation_snapshot(
        warehouse,
        FORMATION_DATE,
        isolation / "formation",
        fact_plan=evidence_plan,
        feature_runner=feature_runner,
    )
    route_policy = build_route_window_policy(
        formation_date=FORMATION_DATE,
        fact_plan=route_plan,
        earnings_report_periods=(date(2026, 6, 30),),
        event_start=date(2026, 6, 1),
        price_absolute_tail_fraction=0.4,
    )
    materialized_route = materialize_formation_snapshot(
        warehouse,
        FORMATION_DATE,
        isolation / "route",
        fact_plan=route_plan,
        feature_runner=feature_runner,
    )
    route_snapshot = project_route_snapshot(materialized_route, evidence_plan)
    batch = scan_routes(route_snapshot, route_policy)
    _, hypotheses = batch
    hypothesis = next(
        item for item in hypotheses if item.security_id == "600000.SH"
    )
    mismatched_formula_snapshot = replace(
        formation,
        formula_versions=(
            *formation.formula_versions[:-1],
            ("stock_trading_context", "stock-trading-context-v999"),
        ),
    )
    with pytest.raises(ValueError, match="different formula versions"):
        build_verified_evidence_snapshot_bundle(
            batch,
            warehouse,
            evidence_catalog,
            evidence_plan,
            mismatched_formula_snapshot,
        )
    mismatched_feature_input_snapshot = replace(
        formation,
        fact_manifest_hashes=("b" * 64,),
    )
    with pytest.raises(ValueError, match="feature input manifests differ"):
        build_verified_evidence_snapshot_bundle(
            batch,
            warehouse,
            evidence_catalog,
            evidence_plan,
            mismatched_feature_input_snapshot,
        )
    bundle = build_verified_evidence_snapshot_bundle(
        batch,
        warehouse,
        evidence_catalog,
        evidence_plan,
        formation,
    )
    packet = build_candidate_packet(batch, bundle, hypothesis.security_id)

    assert len(packet.route_manifest_audit) == 6
    assert packet.evidence_plan_audit.evidence_plan_hash == evidence_plan.plan_hash
    assert any(
        item.dataset == "stock_trading_context"
        for item in packet.local_observations
    )
    cards = {card.opportunity.value: card for card in packet.opportunity_cards}
    for opportunity in (
        "earnings_revaluation",
        "supply_demand_cycle",
        "company_event_revaluation",
    ):
        assert cards[opportunity].status is EvidenceCardStatus.EVIDENCE_READY_FOR_JUDGMENT
    assert packet.model_judgments == ()
    assert packet.evidence_plan_audit.verified_batch_receipt_hash == batch.batch_hash
    assert packet.evidence_plan_audit.raw_lead_ledger_hash == (
        evidence_module._verified_lead_ledger_hash(
            batch.lead_members(hypothesis.security_id)
        )
    )
    ready_sections = [
        section
        for section in packet.sections
        if section.availability
        is EvidenceAvailability.EVIDENCE_READY_FOR_JUDGMENT
    ]
    assert ready_sections
    assert all("does not assert" in section.note for section in ready_sections)
    negative_earnings_ids = {
        item.evidence_id
        for item in packet.api_facts
        if (
        item.dataset == "earnings_forecast"
        and item.field == "p_change_min"
        and Decimal(str(item.value)) < 0
        )
    }
    negative_cycle_ids = {
        item.evidence_id
        for item in packet.api_facts
        if (
        item.dataset == "industry_daily"
        and item.field in {"demand_change", "price_change"}
        and Decimal(str(item.value)) < 0
        )
    }
    terminated_event_ids = {
        item.evidence_id
        for item in packet.api_facts
        if item.dataset == "announcement"
        and item.field in {"title", "event_stage", "failure_conditions"}
        and any(
            marker in str(item.value).lower()
            for marker in ("terminated", "triggered")
        )
    }
    assert negative_earnings_ids
    assert negative_cycle_ids
    assert terminated_event_ids
    event_responses = [
        item
        for item in packet.local_observations
        if item.dataset == "event_price_response"
    ]
    packet_evidence_ids = {
        item.evidence_id
        for item in (*packet.api_facts, *packet.local_observations)
    }
    assert event_responses
    assert all(
        item.source_evidence_id in packet_evidence_ids
        for item in event_responses
    )
    assert all(
        item.value == item.source_evidence_id
        for item in event_responses
        if item.field == "source_event_evidence_id"
    )
    assert negative_earnings_ids.issubset(
        cards["earnings_revaluation"].evidence_ids
    )
    assert negative_cycle_ids.issubset(
        cards["supply_demand_cycle"].evidence_ids
    )
    assert terminated_event_ids.issubset(
        cards["company_event_revaluation"].evidence_ids
    )
    assert {
        item.evidence_id
        for item in event_responses
        if item.source_evidence_id
        in {
            source.evidence_id
            for source in packet.api_facts
            if source.dataset == "announcement"
        }
    }.issubset(cards["company_event_revaluation"].evidence_ids)
    assert evidence_catalog.source_attestation_hash == catalog.source_attestation_hash
    assert evidence_plan.source_entries == tuple(
        formation.facts.manifest["source_snapshot"]["partitions"]
    )

    same_content_other_batch = scan_routes(route_snapshot, route_policy)
    with pytest.raises(ValueError, match="another route batch"):
        build_candidate_packet(
            same_content_other_batch,
            bundle,
            hypothesis.security_id,
        )
