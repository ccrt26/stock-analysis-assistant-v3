from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from stock_analyzer.data.capability_store import (
    CapabilityBundle,
    CapabilityEvidenceError,
    LocalCapabilityStore,
)
from stock_analyzer.data.readiness import (
    AcquisitionGroupId,
    CapabilityEvidenceKind,
    RouteCapabilityEvidence,
)


NOW = datetime(2026, 7, 10, 16, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
ROUTE_ID = "tushare.market_decision.v1"


def capability(
    *,
    kind: CapabilityEvidenceKind = CapabilityEvidenceKind.RECORDED,
    contract_version: str = "formal-v2",
    group_id: AcquisitionGroupId = AcquisitionGroupId.MARKET_DECISION,
    route_id: str = ROUTE_ID,
    semantic_probe_hashes: dict[str, str] | None = None,
) -> RouteCapabilityEvidence:
    return RouteCapabilityEvidence(
        route_id=route_id,
        group_id=group_id,
        contract_version=contract_version,
        full_contract_tested=True,
        field_semantics_verified=True,
        full_universe_verified=True,
        post_close_verified=True,
        tested_at=NOW,
        evidence_kind=kind,
        response_hash="a" * 64,
        tested_library_versions={"tushare": "1.4.19", "pandas": "2.2.3"},
        semantic_probe_hashes=semantic_probe_hashes or {},
    )


def bundle(
    *,
    kind: CapabilityEvidenceKind = CapabilityEvidenceKind.RECORDED,
    contract_version: str = "formal-v2",
    routes: tuple[RouteCapabilityEvidence, ...] | None = None,
) -> CapabilityBundle:
    return CapabilityBundle(
        contract_version=contract_version,
        generated_at=NOW,
        routes=routes or (capability(kind=kind, contract_version=contract_version),),
    )


def test_recorded_capability_supports_offline_factory_but_not_live_factory(tmp_path):
    store = LocalCapabilityStore(tmp_path / "capabilities.json")
    store.save(bundle(kind=CapabilityEvidenceKind.RECORDED))

    loaded = store.load(require_live=False)

    assert loaded[ROUTE_ID].approved is True
    assert loaded[ROUTE_ID].approved_for_live is False
    with pytest.raises(CapabilityEvidenceError, match="live capability evidence required"):
        store.load(require_live=True)


def test_capability_bundle_rejects_wrong_contract_route_group_and_tampering(tmp_path):
    wrong_contract = LocalCapabilityStore(tmp_path / "wrong-contract.json")
    with pytest.raises(CapabilityEvidenceError, match="contract version mismatch"):
        wrong_contract.save(
            bundle(routes=(capability(contract_version="formal-v1"),))
        )

    wrong_group = LocalCapabilityStore(tmp_path / "wrong-group.json")
    with pytest.raises(CapabilityEvidenceError, match="route group mismatch"):
        wrong_group.save(
            bundle(routes=(capability(group_id=AcquisitionGroupId.CALENDAR_UNIVERSE),))
        )

    duplicate = LocalCapabilityStore(tmp_path / "duplicate.json")
    with pytest.raises(CapabilityEvidenceError, match="duplicate route evidence"):
        duplicate.save(bundle(routes=(capability(), capability())))

    path = tmp_path / "capabilities.json"
    LocalCapabilityStore(path).save(bundle())
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["routes"][0]["response_hash"] = "tampered"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(CapabilityEvidenceError, match="bundle hash mismatch"):
        LocalCapabilityStore(path).load(require_live=False)


def test_persisted_capability_requires_real_response_hash_and_library_versions(tmp_path):
    store = LocalCapabilityStore(tmp_path / "capabilities.json")

    with pytest.raises(CapabilityEvidenceError, match="response hash is required"):
        store.save(
            bundle(
                routes=(capability().model_copy(update={"response_hash": "0" * 64}),)
            )
        )

    with pytest.raises(CapabilityEvidenceError, match="library versions are required"):
        store.save(
            bundle(
                routes=(capability().model_copy(update={"tested_library_versions": {}}),)
            )
        )


def test_event_capability_requires_distinct_populated_and_empty_probe_hashes():
    base = capability(
        route_id="official.events_risk.v1",
        group_id=AcquisitionGroupId.OFFICIAL_EVENTS_RISK,
    )

    assert base.approved is False
    assert base.model_copy(
        update={"semantic_probe_hashes": {"populated_precise_time": "b" * 64}}
    ).approved is False
    assert base.model_copy(
        update={
            "semantic_probe_hashes": {
                "populated_precise_time": "b" * 64,
                "empty_coverage": "b" * 64,
            }
        }
    ).approved is False
    assert base.model_copy(
        update={
            "semantic_probe_hashes": {
                "populated_precise_time": "b" * 64,
                "empty_coverage": "c" * 64,
            }
        }
    ).approved is True


def test_non_event_capability_does_not_require_event_probe_hashes():
    assert capability().approved is True


@pytest.mark.parametrize("invalid_hash", ["not-a-hash", "0" * 64])
def test_capability_store_rejects_malformed_semantic_probe_hash(
    tmp_path,
    invalid_hash,
):
    store = LocalCapabilityStore(tmp_path / "capabilities.json")
    event = capability(
        route_id="official.events_risk.v1",
        group_id=AcquisitionGroupId.OFFICIAL_EVENTS_RISK,
        semantic_probe_hashes={
            "populated_precise_time": invalid_hash,
            "empty_coverage": "c" * 64,
        },
    )

    with pytest.raises(CapabilityEvidenceError, match="semantic probe hash"):
        store.save(bundle(routes=(event,)))
