from __future__ import annotations

import ast
import json
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import pandas as pd

from stock_analyzer.analysis.focus import FormalFocusDay
from stock_analyzer.data.formal_contracts import FORMAL_CONTRACT_VERSION
from stock_analyzer.data.readiness import (
    AcquisitionGroupId,
    AcquisitionRequest,
    FormalRunState,
    validate_group_payload,
)
from stock_analyzer.ops.activation import ActivationError, hash_artifact_tree
from stock_analyzer.ops.job import _default_run_daily
from stock_analyzer.ops.production_dependencies import build_production_formal_dependencies
from stock_analyzer.pipeline import StoredAnalysisNotFound, render_report_for_date
from stock_analyzer.storage.evidence_store import LocalEvidenceStore
from stock_analyzer.storage.repositories import InMemoryAnalysisRepository
from tests.test_formal_materializer import TARGET
from tests.test_formal_strategy_runtime import _prior_snapshots
from tests.test_production_dependencies import recorded_external_runtime


def production_recorded_runtime(tmp_path):
    runtime = recorded_external_runtime(tmp_path)

    def liquid_tushare_daily(kwargs):
        frame = runtime.tushare_pro._default("daily", kwargs)
        frame["amount"] = 500_000.0
        return frame

    def liquid_akshare_history(kwargs):
        frame = runtime.akshare_module._default("stock_zh_a_hist", kwargs)
        frame["成交额"] = 500_000_000.0
        return frame

    runtime.tushare_pro.overrides["daily"] = liquid_tushare_daily
    runtime.akshare_module.overrides["stock_zh_a_hist"] = liquid_akshare_history
    return runtime


def test_default_recorded_july10_complete_path_generates_and_activates_formal_report(tmp_path):
    runtime = production_recorded_runtime(tmp_path)

    result = _default_run_daily(
        tmp_path,
        InMemoryAnalysisRepository(),
        TARGET,
        runtime=runtime,
    )

    assert result.receipt.state is FormalRunState.REPORT_GENERATED
    assert result.receipt.run_id == "formal-2026-07-10"
    assert result.receipt.input_set_id
    assert result.receipt.candidate_set_id
    assert result.receipt.evidence_hashes
    assert result.receipt.local_activation_id == result.receipt.ledger_activation_id
    latest = json.loads(
        (tmp_path / "reports/data/latest.json").read_text(encoding="utf-8")
    )
    manifest = json.loads(
        (tmp_path / "reports/data/formal-run.json").read_text(encoding="utf-8")
    )
    assert latest["report_mode"] == "production"
    assert latest["is_fixture"] is False
    assert manifest["run_id"] == result.receipt.run_id
    assert manifest["input_set_id"] == result.receipt.input_set_id
    assert manifest["evidence_hashes"] == result.receipt.evidence_hashes
    html = (tmp_path / "reports/index.html").read_text(encoding="utf-8")
    assert "Fixture/sample" not in html
    assert "总分" not in html


def test_default_recorded_july10_partial_primary_discards_it_and_uses_complete_backup_only(tmp_path):
    runtime = production_recorded_runtime(tmp_path)

    def incomplete_primary(kwargs):
        frame = runtime.tushare_pro._default("daily", kwargs)
        return frame.drop(columns=["amount"])

    runtime.tushare_pro.overrides["daily"] = incomplete_primary

    result = _default_run_daily(
        tmp_path,
        InMemoryAnalysisRepository(),
        TARGET,
        runtime=runtime,
    )

    assert result.receipt.state is FormalRunState.REPORT_GENERATED
    market_version = result.receipt.group_version_ids["market_decision"]
    payload = result.analysis.value
    assert all("tushare.market_decision" not in key for key in payload.source_versions)
    assert any("eastmoney.market_decision" in key for key in payload.source_versions)
    stored = result.receipt.group_version_ids.values()
    assert market_version in stored
    assert "primary-sentinel" not in json.dumps(payload.model_dump(mode="json"), ensure_ascii=False)


def test_default_recorded_july10_incomplete_primary_and_backup_blocks_before_strategy(tmp_path):
    runtime = production_recorded_runtime(tmp_path)

    def incomplete_primary(kwargs):
        return runtime.tushare_pro._default("daily", kwargs).drop(columns=["amount"])

    def incomplete_backup(kwargs):
        return runtime.akshare_module._default("stock_zh_a_hist", kwargs).drop(
            columns=["成交额"]
        )

    runtime.tushare_pro.overrides["daily"] = incomplete_primary
    runtime.akshare_module.overrides["stock_zh_a_hist"] = incomplete_backup

    result = _default_run_daily(
        tmp_path,
        InMemoryAnalysisRepository(),
        TARGET,
        runtime=runtime,
    )

    assert result.receipt.state is FormalRunState.BLOCKED_NEEDS_HUMAN
    assert result.receipt.blocked_group.value == "market_decision"
    assert result.candidate_set is None
    assert result.analysis is None
    assert not (tmp_path / "reports").exists()
    assert runtime.ledger.pending == {}


def test_market_request_excludes_suspended_hard_excluded_and_too_new_codes(tmp_path):
    runtime = production_recorded_runtime(tmp_path)
    suspended = "000001.SZ"
    too_new = "688999.SH"
    runtime.tushare_pro.overrides["stock_basic"] = pd.DataFrame(
        [
            {
                "ts_code": "600000.SH",
                "name": "浦发银行",
                "exchange": "SSE",
                "list_date": "19991110",
            },
            {
                "ts_code": suspended,
                "name": "平安银行",
                "exchange": "SZSE",
                "list_date": "19910403",
            },
            {
                "ts_code": too_new,
                "name": "新上市样本",
                "exchange": "SSE",
                "list_date": "20260601",
            },
        ]
    )
    runtime.tushare_pro.overrides["suspend_d"] = pd.DataFrame(
        [
            {
                "ts_code": suspended,
                "trade_date": "20260710",
                "suspend_type": "S",
                "name": "平安银行",
            }
        ]
    )

    def three_code_daily(kwargs):
        base = runtime.tushare_pro._default("daily", kwargs).iloc[0].to_dict()
        return pd.DataFrame(
            [
                {**base, "ts_code": code, "amount": 500_000.0}
                for code in ("600000.SH", suspended, too_new)
            ]
        )

    def three_code_basic(kwargs):
        base = runtime.tushare_pro._default("daily_basic", kwargs).iloc[0].to_dict()
        return pd.DataFrame(
            [{**base, "ts_code": code} for code in ("600000.SH", suspended, too_new)]
        )

    runtime.tushare_pro.overrides["daily"] = three_code_daily
    runtime.tushare_pro.overrides["daily_basic"] = three_code_basic

    result = _default_run_daily(
        tmp_path,
        InMemoryAnalysisRepository(),
        TARGET,
        runtime=runtime,
    )

    store = LocalEvidenceStore(tmp_path / "local_warehouse/formal_evidence")
    payload = store.read_group_version(
        result.receipt.group_version_ids[AcquisitionGroupId.MARKET_DECISION.value]
    )
    equity_codes = {
        row["ts_code"]
        for row in payload.records
        if row.get("record_type") == "equity_bar"
    }
    assert equity_codes == {"600000.SH"}


def test_default_recorded_reconciliation_keeps_frozen_report_and_promotes_primary_history(tmp_path):
    runtime = production_recorded_runtime(tmp_path)

    def incomplete_primary(kwargs):
        return runtime.tushare_pro._default("daily", kwargs).drop(columns=["amount"])

    runtime.tushare_pro.overrides["daily"] = incomplete_primary
    result = _default_run_daily(
        tmp_path,
        InMemoryAnalysisRepository(),
        TARGET,
        runtime=runtime,
    )
    store = LocalEvidenceStore(tmp_path / "local_warehouse/formal_evidence")
    report_hashes = hash_artifact_tree(tmp_path / "reports")
    frozen = store.frozen_report_reference(result.receipt.run_id)
    reconciliation_path = next((store.root / "reconciliation").glob("*.json"))
    task_id = reconciliation_path.stem
    backup_version = store.reconciliation_task(task_id).backup_version_id

    def complete_primary(kwargs):
        frame = runtime.tushare_pro._default("daily", kwargs)
        frame["amount"] = 500_000.0
        return frame

    runtime.tushare_pro.overrides["daily"] = complete_primary
    request = AcquisitionRequest(
        run_id="reconcile-formal-2026-07-10",
        trade_date=TARGET,
        report_cutoff=datetime(2026, 7, 10, 16, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        target_codes=("600000.SH",),
        contract_version=FORMAL_CONTRACT_VERSION,
    )
    dependencies = build_production_formal_dependencies(
        tmp_path,
        InMemoryAnalysisRepository(),
        TARGET,
        runtime=runtime,
    )
    market_group = next(
        group
        for group in dependencies.screening_routes
        if group.contract.group_id is AcquisitionGroupId.MARKET_DECISION
    )
    primary_route = market_group.routes.primary
    primary_payload = primary_route.fetch(request)
    validation = validate_group_payload(market_group.contract, request, primary_payload)
    primary = store.reconcile_primary(task_id, primary_payload, validation)

    assert primary.route_kind.value == "primary"
    assert store.version_path(backup_version).is_file()
    assert (
        store.canonical_manifest(AcquisitionGroupId.MARKET_DECISION, TARGET).version_id
        == primary.version_id
    )
    assert store.frozen_report_reference(result.receipt.run_id) == frozen
    assert hash_artifact_tree(tmp_path / "reports") == report_hashes


def test_default_recorded_focus_window_breaks_on_blocked_day(tmp_path):
    prior_days = [
        date(2026, 7, 3),
        date(2026, 7, 6),
        date(2026, 7, 7),
        date(2026, 7, 8),
        date(2026, 7, 9),
    ]
    repository = InMemoryAnalysisRepository(
        strategy_snapshots=_prior_snapshots("600000.SH", prior_days),
        formally_committed_run_dates=set(prior_days),
        formal_focus_days=[
            FormalFocusDay(
                trade_date=value,
                formally_committed=index != 2,
                blocked=index == 2,
            )
            for index, value in enumerate(prior_days)
        ],
    )

    result = _default_run_daily(
        tmp_path,
        repository,
        TARGET,
        runtime=production_recorded_runtime(tmp_path),
    )

    assert repository.formal_focus_day_calls == [(TARGET, prior_days)]
    assert result.receipt.state is FormalRunState.REPORT_GENERATED
    assert result.analysis.value.focus_states == []


def test_default_recorded_direct_render_requires_activated_receipt(tmp_path):
    with pytest.raises(StoredAnalysisNotFound, match="committed REPORT_GENERATED receipt"):
        render_report_for_date(
            TARGET,
            tmp_path / "reports",
            repository=InMemoryAnalysisRepository(),
            receipt_store=LocalEvidenceStore(tmp_path / "local_warehouse/formal_evidence"),
            expected_input_set_id="missing-input-set",
        )


@pytest.mark.parametrize(
    "failure_point",
    ["render", "verify", "ledger_prepare", "local_marker", "ledger_activate", "pointer"],
)
def test_default_recorded_atomic_failure_preserves_prior_consumers(tmp_path, failure_point):
    reports = tmp_path / "reports"
    (reports / "data").mkdir(parents=True)
    (reports / "index.html").write_text("<html>prior</html>", encoding="utf-8")
    (reports / "data/latest.json").write_text(
        '{"trade_date":"2026-07-09","report_mode":"production","is_fixture":false}',
        encoding="utf-8",
    )
    prior_index = (reports / "index.html").read_bytes()
    prior_latest = (reports / "data/latest.json").read_bytes()
    runtime = replace(
        production_recorded_runtime(tmp_path),
        activation_failure_point=failure_point,
    )

    with pytest.raises(ActivationError, match="injected activation failure"):
        _default_run_daily(
            tmp_path,
            InMemoryAnalysisRepository(),
            TARGET,
            runtime=runtime,
        )

    assert (reports / "index.html").read_bytes() == prior_index
    assert (reports / "data/latest.json").read_bytes() == prior_latest
    receipt = LocalEvidenceStore(
        tmp_path / "local_warehouse/formal_evidence"
    ).latest_run_receipt("formal-2026-07-10")
    assert receipt.state is FormalRunState.FAILED_RETRYABLE
    assert receipt.local_activation_id is None
    assert receipt.ledger_activation_id is None


def test_required_production_methods_have_no_empty_stub_or_unconditional_not_configured_raise():
    root = Path(__file__).resolve().parents[1]
    provider = (root / "src/stock_analyzer/data/provider.py").read_text(encoding="utf-8")
    job = (root / "src/stock_analyzer/ops/job.py").read_text(encoding="utf-8")
    assert "return []" not in provider
    assert "Production formal route clients and recorded capability evidence are not configured" not in job


def test_default_acceptance_does_not_use_sample_market_or_patch_dependency_factory():
    source = Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert not any(
        isinstance(node, ast.Name) and node.id == "_sample_market"
        for node in ast.walk(tree)
    )
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "monkeypatch"
        and node.func.attr == "setattr"
        for node in ast.walk(tree)
    )
