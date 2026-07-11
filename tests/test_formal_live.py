from __future__ import annotations

from dataclasses import replace

import pytest

from stock_analyzer.data.capability_store import LocalCapabilityStore
from stock_analyzer.data.readiness import CapabilityEvidenceKind, FormalRunState
from stock_analyzer.ops.formal_live import (
    LiveCapabilityVerificationError,
    verify_and_record_live_capabilities,
)
from stock_analyzer.ops.job import _default_run_daily
from stock_analyzer.storage.evidence_store import LocalEvidenceStore
from stock_analyzer.storage.repositories import InMemoryAnalysisRepository
from tests.test_formal_materializer import TARGET
from tests.test_production_dependencies import NOW, recorded_external_runtime


def bootstrap_runtime(tmp_path):
    runtime = recorded_external_runtime(tmp_path)
    return replace(
        runtime,
        capability_store=LocalCapabilityStore(
            tmp_path
            / "local_warehouse"
            / "formal_evidence"
            / "capabilities"
            / "formal-v2"
            / "latest.json"
        ),
    )


def test_live_capability_bootstrap_uses_real_clients_and_writes_no_ledger_or_report(
    tmp_path,
):
    runtime = bootstrap_runtime(tmp_path)

    result = verify_and_record_live_capabilities(
        runtime,
        TARGET,
        NOW,
        evidence_kind=CapabilityEvidenceKind.RECORDED,
        tested_at=NOW,
        tested_library_versions={"recorded": "2026-07-10"},
    )

    assert len(result.bundle.routes) == 10
    assert len(result.primary_screening_versions) == 2
    assert result.target_probe_codes == ("600000.SH",)
    assert runtime.capability_store.load(require_live=False)
    assert runtime.tushare_pro.calls
    assert runtime.akshare_module.calls
    assert runtime.ledger.pending == {}
    assert runtime.ledger.active == {}
    assert not (tmp_path / "reports").exists()
    store = LocalEvidenceStore(tmp_path / "local_warehouse/formal_evidence")
    for manifest in result.primary_screening_versions:
        assert store.version_path(manifest.version_id).is_file()
        assert store.canonical_manifest(manifest.group_id, TARGET) == manifest


def test_live_capability_bootstrap_requires_explicit_confirmation_before_provider_call(
    tmp_path,
):
    runtime = bootstrap_runtime(tmp_path)

    with pytest.raises(LiveCapabilityVerificationError, match="explicit confirmation"):
        verify_and_record_live_capabilities(
            runtime,
            TARGET,
            NOW,
            evidence_kind=CapabilityEvidenceKind.LIVE,
            tested_at=NOW,
            tested_library_versions={"recorded": "2026-07-10"},
        )

    assert runtime.tushare_pro.calls == []
    assert runtime.akshare_module.calls == []


def test_live_capability_bootstrap_accepts_complete_backup_when_primary_route_unavailable(
    tmp_path,
):
    runtime = bootstrap_runtime(tmp_path)
    runtime.tushare_pro.overrides["anns_d"] = RuntimeError("permission denied")

    result = verify_and_record_live_capabilities(
        runtime,
        TARGET,
        NOW,
        evidence_kind=CapabilityEvidenceKind.RECORDED,
        tested_at=NOW,
        tested_library_versions={"recorded": "2026-07-10"},
    )

    route_ids = {route.route_id for route in result.bundle.routes}
    assert "official.events_risk.v1" not in route_ids
    assert "cninfo.direct.events_risk.v2" in route_ids
    assert result.unavailable_route_ids == ("official.events_risk.v1",)
    event = next(
        route
        for route in result.bundle.routes
        if route.route_id == "cninfo.direct.events_risk.v2"
    )
    assert set(event.semantic_probe_hashes) == {
        "populated_precise_time",
        "empty_coverage",
    }
    assert len(set(event.semantic_probe_hashes.values())) == 2


def test_failed_reverification_replaces_stale_latest_capability_with_partial_bundle(
    tmp_path,
):
    runtime = bootstrap_runtime(tmp_path)
    initial = verify_and_record_live_capabilities(
        runtime,
        TARGET,
        NOW,
        evidence_kind=CapabilityEvidenceKind.RECORDED,
        tested_at=NOW,
        tested_library_versions={"recorded": "2026-07-10"},
    )
    assert any(
        route.group_id.value == "official_events_risk"
        for route in initial.bundle.routes
    )
    runtime.tushare_pro.overrides["anns_d"] = RuntimeError("permission denied")
    runtime.cninfo_http_client.invalid_timestamp = True

    with pytest.raises(
        LiveCapabilityVerificationError,
        match="official_events_risk",
    ):
        verify_and_record_live_capabilities(
            runtime,
            TARGET,
            NOW,
            evidence_kind=CapabilityEvidenceKind.RECORDED,
            tested_at=NOW,
            tested_library_versions={"recorded": "2026-07-11"},
        )

    latest = runtime.capability_store.load(require_live=False)
    assert latest
    assert all(
        route.group_id.value != "official_events_risk"
        for route in latest.values()
    )
    version_files = list(
        (runtime.capability_store.path.parent / "versions").glob("*.json")
    )
    assert len(version_files) == 2


def test_live_bootstrap_rejects_cninfo_date_only_event_semantics_and_saves_partial_bundle(
    tmp_path,
):
    runtime = bootstrap_runtime(tmp_path)
    runtime.tushare_pro.overrides["anns_d"] = RuntimeError("permission denied")
    runtime.cninfo_http_client.invalid_timestamp = True

    with pytest.raises(
        LiveCapabilityVerificationError,
        match="official_events_risk",
    ):
        verify_and_record_live_capabilities(
            runtime,
            TARGET,
            NOW,
            evidence_kind=CapabilityEvidenceKind.LIVE,
            confirm_live_read=True,
            tested_at=NOW,
            tested_library_versions={"recorded": "2026-07-10"},
        )

    route_ids = set(runtime.capability_store.load(require_live=True))
    assert "official_exchange.calendar_universe.v1" not in route_ids
    assert "eastmoney.market_decision.v1" not in route_ids
    assert "cninfo.direct.events_risk.v2" not in route_ids
    assert "stock_zh_a_hist" not in [
        name for name, _ in runtime.akshare_module.calls
    ]


def test_live_event_capability_requires_populated_and_empty_semantic_probes(tmp_path):
    runtime = bootstrap_runtime(tmp_path)
    runtime.tushare_pro.overrides["anns_d"] = RuntimeError("permission denied")
    runtime.cninfo_http_client.no_empty = True

    with pytest.raises(
        LiveCapabilityVerificationError,
        match="official_events_risk",
    ):
        verify_and_record_live_capabilities(
            runtime,
            TARGET,
            NOW,
            evidence_kind=CapabilityEvidenceKind.LIVE,
            confirm_live_read=True,
            tested_at=NOW,
            tested_library_versions={"recorded": "2026-07-10"},
        )

    assert all(
        capability.group_id.value != "official_events_risk"
        for capability in runtime.capability_store.load(require_live=True).values()
    )


def test_empty_contract_response_cannot_set_field_semantics_verified(tmp_path):
    runtime = bootstrap_runtime(tmp_path)
    runtime.tushare_pro.overrides["anns_d"] = RuntimeError("permission denied")
    runtime.cninfo_http_client.no_populated = True

    with pytest.raises(
        LiveCapabilityVerificationError,
        match="official_events_risk",
    ):
        verify_and_record_live_capabilities(
            runtime,
            TARGET,
            NOW,
            evidence_kind=CapabilityEvidenceKind.LIVE,
            confirm_live_read=True,
            tested_at=NOW,
            tested_library_versions={"recorded": "2026-07-10"},
        )

    assert all(
        not capability.field_semantics_verified
        for capability in runtime.capability_store.load(require_live=True).values()
        if capability.group_id.value == "official_events_risk"
    )


def test_default_run_reuses_exact_same_day_screening_backfill(tmp_path):
    runtime = bootstrap_runtime(tmp_path)
    verify_and_record_live_capabilities(
        runtime,
        TARGET,
        NOW,
        evidence_kind=CapabilityEvidenceKind.RECORDED,
        tested_at=NOW,
        tested_library_versions={"recorded": "2026-07-10"},
    )
    runtime.tushare_pro.calls.clear()
    runtime.akshare_module.calls.clear()

    result = _default_run_daily(
        tmp_path,
        InMemoryAnalysisRepository(),
        TARGET,
        runtime=runtime,
    )

    assert result.receipt.state in {
        FormalRunState.REPORT_GENERATED,
        FormalRunState.ANALYSIS_COMPLETE_NO_RECOMMENDATIONS,
    }
    called_methods = [name for name, _ in runtime.tushare_pro.calls]
    assert "daily" not in called_methods
    assert "daily_basic" not in called_methods
    screening_stock_basic_calls = [
        kwargs
        for name, kwargs in runtime.tushare_pro.calls
        if name == "stock_basic" and "list_date" in kwargs.get("fields", "")
    ]
    assert screening_stock_basic_calls == []
    assert runtime.akshare_module.calls == []
