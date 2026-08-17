from datetime import date
from types import SimpleNamespace

from typer.testing import CliRunner

from stock_analyzer.cli import app
from stock_analyzer.data.research_backfill import BackfillSummary


runner = CliRunner()


def test_root_cli_exposes_current_groups():
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0, result.output
    assert "data" in result.output
    assert "selection-lab" in result.output
    assert "ops" not in result.output
    for old_command in (
        "health-check",
        "run-daily",
        "render-report",
        "prepare-formal-report-candidate",
        "activate-formal-report-candidate",
    ):
        assert old_command not in result.output


def test_data_cli_exposes_only_current_warehouse_commands():
    result = runner.invoke(app, ["data", "--help"])

    assert result.exit_code == 0, result.output
    for current_command in (
        "backfill",
        "run-stage",
        "derive",
        "health",
    ):
        assert current_command in result.output
    for retired_command in (
        "inspect-legacy-market",
        "migrate-legacy-market",
        "audit-migration",
        "legacy-cleanup-manifest",
        "cleanup-legacy-market",
        "normalize-share-float",
        "audit-time-semantics",
        "migrate-time-semantics",
    ):
        assert retired_command not in result.output


def test_scheduled_stage_command_still_loads():
    result = runner.invoke(app, ["data", "run-stage", "--help"])

    assert result.exit_code == 0, result.output
    assert "--stage" in result.output
    assert "--data-date" in result.output


def test_health_command_still_loads():
    result = runner.invoke(app, ["data", "health", "--help"])

    assert result.exit_code == 0, result.output
    assert "--data-date" in result.output
    assert "--full-history" in result.output


def test_scheduled_stage_returns_nonzero_when_required_facts_are_incomplete(
    tmp_path, monkeypatch
):
    import stock_analyzer.ops.research_data_job as job
    import stock_analyzer.ops.research_health as health

    config = SimpleNamespace(local_archive_dir=tmp_path / "archive")
    runtime = SimpleNamespace(config=config, warehouse=object())
    monkeypatch.setattr(job, "build_research_data_runtime", lambda config: runtime)
    monkeypatch.setattr(
        job,
        "run_research_stage",
        lambda runtime, *, stage, data_date: (
            BackfillSummary(
                scope="market-core",
                start=date(2026, 8, 4),
                through=date(2026, 8, 4),
                waiting_upstream=1,
            ),
        ),
    )
    monkeypatch.setattr(
        "stock_analyzer.config.AppConfig.load", lambda: config
    )
    monkeypatch.setattr(
        health,
        "build_research_health_report",
        lambda warehouse, data_date, full_history: SimpleNamespace(
            complete_core_date=True
        ),
    )
    monkeypatch.setattr(
        health,
        "write_health_report",
        lambda report, output_dir: (output_dir / "health.json", None),
    )

    result = runner.invoke(
        app,
        [
            "data",
            "run-stage",
            "--stage",
            "close",
            "--data-date",
            "2026-08-04",
        ],
    )

    assert result.exit_code == 2, result.output
    assert "core_complete=true" in result.output
