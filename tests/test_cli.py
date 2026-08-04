from typer.testing import CliRunner

from stock_analyzer.cli import app


runner = CliRunner()


def test_root_cli_exposes_only_the_data_group():
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0, result.output
    assert "data" in result.output
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
        "repair-gaps",
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
