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

    assert len(result.bundle.routes) == 12
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
    assert "stock_basic" not in called_methods
    assert runtime.akshare_module.calls == []
