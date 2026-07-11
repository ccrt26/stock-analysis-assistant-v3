from __future__ import annotations

import hashlib
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from stock_analyzer.ops import artifacts as artifacts_module
from stock_analyzer.ops.artifacts import DeployArtifactError, prepare_pages_artifact
from stock_analyzer.ops.calendar import TradingDayDecision
from stock_analyzer.ops.job import run_daily_job
from stock_analyzer.ops.status import RunStatus
from stock_analyzer.ops.verify import ProductionVerification
from stock_analyzer.data.readiness import FormalRunState
from stock_analyzer.ops.formal_run import RunReceipt


def test_prepare_pages_artifact_copies_reports_and_middleware_only(tmp_path):
    _write_report_tree(tmp_path)
    _write_middleware(tmp_path)
    _write_forbidden_source_paths(tmp_path)
    output_dir = tmp_path / "dist" / "pages"
    stale_env_path = output_dir / (".env" + ".local")
    stale_env_path.parent.mkdir(parents=True)
    stale_env_path.write_text("stale-secret", encoding="utf-8")

    artifact_dir = prepare_pages_artifact(
        tmp_path,
        output_dir,
        receipt=_activated_receipt(tmp_path, date(2026, 7, 9)),
    )

    assert artifact_dir == output_dir
    assert (artifact_dir / "index.html").read_text(encoding="utf-8") == (
        "<html>生产报告 2026-07-09</html>"
    )
    assert (artifact_dir / "data" / "latest.json").exists()
    assert (artifact_dir / "daily" / "2026-07-09" / "index.html").exists()
    assert (artifact_dir / "functions" / "_middleware.ts").read_text(
        encoding="utf-8"
    ) == "export const onRequest = async () => new Response('ok');\n"

    assert not (artifact_dir / (".env" + ".local")).exists()
    assert not (artifact_dir / ".env.production").exists()
    assert not (artifact_dir / ".git").exists()
    assert not (artifact_dir / ".venv").exists()
    assert not (artifact_dir / "local_warehouse").exists()
    assert not (artifact_dir / "local_archive").exists()
    assert not (artifact_dir / "logs").exists()
    assert not (artifact_dir / "data" / "cache").exists()
    assert not (artifact_dir / "data" / "raw").exists()
    assert not (artifact_dir / ".staging").exists()
    assert not (artifact_dir / ".activation").exists()
    assert not (artifact_dir / ".superpowers").exists()
    assert not any(path.name.startswith(".env") for path in artifact_dir.rglob("*"))


def test_prepare_pages_artifact_requires_report_index(tmp_path):
    (tmp_path / "reports").mkdir()
    _write_middleware(tmp_path)

    with pytest.raises(DeployArtifactError, match="reports/index.html"):
        prepare_pages_artifact(
            tmp_path,
            tmp_path / "dist" / "pages",
            receipt=_activated_receipt(tmp_path, date(2026, 7, 9)),
        )


def test_prepare_pages_artifact_can_use_source_root_for_middleware(
    monkeypatch,
    tmp_path,
):
    production_root = tmp_path / "production-root"
    source_root = tmp_path / "source-root"
    _write_report_tree(production_root)
    _write_middleware(source_root)
    monkeypatch.setattr(artifacts_module, "_DEFAULT_SOURCE_ROOT", source_root)

    artifact_dir = prepare_pages_artifact(
        production_root,
        tmp_path / "stock-analysis-pages",
        receipt=_activated_receipt(production_root, date(2026, 7, 9)),
    )

    assert (artifact_dir / "index.html").exists()
    assert (artifact_dir / "functions" / "_middleware.ts").exists()


def test_prepare_pages_artifact_rejects_existing_absolute_dir_outside_safe_roots(
    monkeypatch,
    tmp_path,
):
    project_root = tmp_path / "project"
    allowed_temp_root = tmp_path / "allowed-temp"
    output_dir = tmp_path / "important-existing-dir"
    output_dir.mkdir()
    marker = output_dir / "do-not-delete.txt"
    marker.write_text("keep me", encoding="utf-8")
    _write_report_tree(project_root)
    _write_middleware(project_root)
    monkeypatch.setenv("TMPDIR", str(allowed_temp_root))

    with pytest.raises(DeployArtifactError, match="Output directory"):
        prepare_pages_artifact(
            project_root,
            output_dir,
            receipt=_activated_receipt(project_root, date(2026, 7, 9)),
        )

    assert marker.read_text(encoding="utf-8") == "keep me"


def test_prepare_pages_artifact_allows_existing_configured_temp_artifact_dir(
    monkeypatch,
    tmp_path,
):
    project_root = tmp_path / "project"
    allowed_temp_root = tmp_path / "allowed-temp"
    output_dir = allowed_temp_root / "stock-analysis-pages"
    output_dir.mkdir(parents=True)
    (output_dir / "stale.txt").write_text("stale", encoding="utf-8")
    _write_report_tree(project_root)
    _write_middleware(project_root)
    monkeypatch.setenv("TMPDIR", str(allowed_temp_root))

    artifact_dir = prepare_pages_artifact(
        project_root,
        output_dir,
        receipt=_activated_receipt(project_root, date(2026, 7, 9)),
    )

    assert artifact_dir == output_dir.resolve()
    assert (artifact_dir / "index.html").exists()
    assert not (artifact_dir / "stale.txt").exists()


def test_run_daily_job_default_prepare_deploy_builds_pages_artifact(tmp_path):
    trade_date = date(2026, 7, 9)
    _write_report_tree(tmp_path)
    _write_middleware(tmp_path)

    status = run_daily_job(
        tmp_path,
        trade_date,
        "18:30",
        1,
        prepare_deploy=True,
        repository=FakeJobRepository(),
        calendar_decider=lambda *_args, **_kwargs: TradingDayDecision(
            status="trading_day",
            source="supabase",
            message="market open",
        ),
        health_check=lambda *_args: None,
        run_daily=lambda *_args: SimpleNamespace(
            receipt=_activated_receipt(tmp_path, trade_date)
        ),
        verifier=lambda *_args: _successful_verification(trade_date),
    )

    assert status.status == RunStatus.SUCCESS_NO_RECOMMENDATIONS
    assert status.deploy_artifact_prepared is True
    assert status.publish_skipped_reason is None
    assert (tmp_path / "dist" / "pages" / "index.html").exists()
    assert (tmp_path / "dist" / "pages" / "functions" / "_middleware.ts").exists()


def test_prepare_pages_artifact_requires_activated_report_generated_receipt(tmp_path):
    _write_report_tree(tmp_path)
    _write_middleware(tmp_path)

    with pytest.raises(DeployArtifactError, match="activated REPORT_GENERATED receipt"):
        prepare_pages_artifact(tmp_path, tmp_path / "dist" / "pages")


def test_prepare_pages_artifact_rejects_report_changed_after_activation(tmp_path):
    _write_report_tree(tmp_path)
    _write_middleware(tmp_path)
    receipt = _activated_receipt(tmp_path, date(2026, 7, 9))
    (tmp_path / "reports" / "index.html").write_text(
        "<html>tampered after activation</html>",
        encoding="utf-8",
    )

    with pytest.raises(DeployArtifactError, match="artifact hash mismatch"):
        prepare_pages_artifact(
            tmp_path,
            tmp_path / "dist" / "pages",
            receipt=receipt,
        )


def test_prepare_pages_artifact_excludes_unactivated_historical_reports(tmp_path):
    _write_report_tree(tmp_path)
    _write_middleware(tmp_path)
    receipt = _activated_receipt(tmp_path, date(2026, 7, 9))
    historical = tmp_path / "reports" / "daily" / "2026-07-07" / "index.html"
    historical.parent.mkdir(parents=True)
    historical.write_text(
        "<html>Fixture/sample report 总评分：83.2</html>",
        encoding="utf-8",
    )

    artifact_dir = prepare_pages_artifact(
        tmp_path,
        tmp_path / "dist" / "pages",
        receipt=receipt,
    )

    assert (artifact_dir / "daily" / "2026-07-09" / "index.html").is_file()
    assert not (artifact_dir / "daily" / "2026-07-07").exists()


def _activated_receipt(project_root: Path, trade_date: date) -> RunReceipt:
    reports = project_root / "reports"
    artifact_hashes = {
        path.relative_to(reports).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(reports.rglob("*"))
        if path.is_file()
        and not artifacts_module._is_forbidden_relative_path(
            path.relative_to(reports)
        )
    }
    if not artifact_hashes:
        artifact_hashes = {"index.html": hashlib.sha256(b"").hexdigest()}
    return RunReceipt(
        run_id=f"activated-{trade_date.isoformat()}",
        target_date=trade_date,
        report_cutoff=datetime(
            trade_date.year,
            trade_date.month,
            trade_date.day,
            16,
            tzinfo=ZoneInfo("Asia/Shanghai"),
        ),
        acquisition_contract_version="formal-v1",
        screening_version="screen-v1",
        state=FormalRunState.REPORT_GENERATED,
        group_version_ids={"market_decision": "version-1"},
        input_set_id="input-1",
        candidate_set_id="candidate-1",
        evidence_hashes={"evidence": "hash"},
        artifact_hashes=artifact_hashes,
        local_activation_id="activation-1",
        ledger_activation_id="activation-1",
    )


class FakeJobRepository:
    def load_market_calendar_day(self, trade_date):
        return True

    def save_market_calendar_day(self, trade_date, is_trading_day, market="CN_A"):
        return None


def _write_report_tree(project_root: Path) -> None:
    reports = project_root / "reports"
    (reports / "daily" / "2026-07-09").mkdir(parents=True)
    (reports / "data").mkdir(parents=True)
    (reports / "index.html").write_text(
        "<html>生产报告 2026-07-09</html>",
        encoding="utf-8",
    )
    (reports / "daily" / "2026-07-09" / "index.html").write_text(
        "<html>生产日报 2026-07-09</html>",
        encoding="utf-8",
    )
    (reports / "data" / "latest.json").write_text(
        '{"trade_date":"2026-07-09","report_mode":"production"}\n',
        encoding="utf-8",
    )


def _write_middleware(project_root: Path) -> None:
    (project_root / "functions").mkdir(parents=True)
    (project_root / "functions" / "_middleware.ts").write_text(
        "export const onRequest = async () => new Response('ok');\n",
        encoding="utf-8",
    )


def _write_forbidden_source_paths(project_root: Path) -> None:
    forbidden_files = [
        ".env" + ".local",
        ".git/config",
        ".venv/pyvenv.cfg",
        "local_warehouse/current.parquet",
        "local_archive/manifests/2026-07-09.json",
        "logs/run-daily/latest-status.json",
        ".superpowers/sdd/task.md",
        "reports/.env.production",
        "reports/data/cache/leak.json",
        "reports/data/raw/leak.json",
        "reports/.staging/pending-run/index.html",
        "reports/.activation/pending-run.pending.json",
    ]
    for relative_path in forbidden_files:
        path = project_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("must not be copied", encoding="utf-8")


def _successful_verification(trade_date: date) -> ProductionVerification:
    return ProductionVerification(
        trade_date=trade_date,
        status=RunStatus.SUCCESS_NO_RECOMMENDATIONS,
        passed=True,
        recommendations=0,
        evidence_packages=0,
        evaluation_tasks=0,
        market_price_daily_current_day_rows=0,
        daily_basic_indicator_current_day_rows=0,
        report_index_exists=True,
        daily_report_index_exists=True,
        report_json_exists=True,
        failures=(),
    )
