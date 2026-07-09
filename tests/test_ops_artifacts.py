from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from stock_analyzer.ops import artifacts as artifacts_module
from stock_analyzer.ops.artifacts import DeployArtifactError, prepare_pages_artifact
from stock_analyzer.ops.calendar import TradingDayDecision
from stock_analyzer.ops.job import run_daily_job
from stock_analyzer.ops.status import RunStatus
from stock_analyzer.ops.verify import ProductionVerification


def test_prepare_pages_artifact_copies_reports_and_middleware_only(tmp_path):
    _write_report_tree(tmp_path)
    _write_middleware(tmp_path)
    _write_forbidden_source_paths(tmp_path)
    output_dir = tmp_path / "dist" / "pages"
    stale_env_path = output_dir / (".env" + ".local")
    stale_env_path.parent.mkdir(parents=True)
    stale_env_path.write_text("stale-secret", encoding="utf-8")

    artifact_dir = prepare_pages_artifact(tmp_path, output_dir)

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
    assert not (artifact_dir / ".superpowers").exists()
    assert not any(path.name.startswith(".env") for path in artifact_dir.rglob("*"))


def test_prepare_pages_artifact_requires_report_index(tmp_path):
    (tmp_path / "reports").mkdir()
    _write_middleware(tmp_path)

    with pytest.raises(DeployArtifactError, match="reports/index.html"):
        prepare_pages_artifact(tmp_path, tmp_path / "dist" / "pages")


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
        tmp_path / "artifact-pages",
    )

    assert (artifact_dir / "index.html").exists()
    assert (artifact_dir / "functions" / "_middleware.ts").exists()


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
        run_daily=lambda *_args: None,
        verifier=lambda *_args: _successful_verification(trade_date),
    )

    assert status.status == RunStatus.SUCCESS_NO_RECOMMENDATIONS
    assert status.deploy_artifact_prepared is True
    assert status.publish_skipped_reason is None
    assert (tmp_path / "dist" / "pages" / "index.html").exists()
    assert (tmp_path / "dist" / "pages" / "functions" / "_middleware.ts").exists()


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
