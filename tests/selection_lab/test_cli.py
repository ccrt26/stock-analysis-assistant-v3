from typer.testing import CliRunner

from stock_analyzer.cli import app


runner = CliRunner()


def test_selection_lab_exposes_six_lazy_commands():
    result = runner.invoke(app, ["selection-lab", "--help"])

    assert result.exit_code == 0, result.output
    for command in (
        "build-dataset",
        "audit-opportunity-types",
        "evaluate-baselines",
        "train-ranker",
        "walk-forward",
        "build-review-bundle",
    ):
        assert command in result.output


def test_each_selection_lab_help_loads_without_running_workflow(monkeypatch):
    monkeypatch.setattr(
        "stock_analyzer.config.AppConfig.load",
        lambda: (_ for _ in ()).throw(AssertionError("help executed workflow")),
    )
    for command in (
        "build-dataset",
        "audit-opportunity-types",
        "evaluate-baselines",
        "train-ranker",
        "walk-forward",
        "build-review-bundle",
    ):
        result = runner.invoke(app, ["selection-lab", command, "--help"])
        assert result.exit_code == 0, f"{command}: {result.output}"


def test_blocked_workflow_returns_structured_nonzero(tmp_path, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(
        "stock_analyzer.config.AppConfig.load",
        lambda: SimpleNamespace(
            project_root=tmp_path,
            local_archive_dir=tmp_path / "archive",
            local_warehouse_dir=tmp_path / "warehouse",
        ),
    )

    result = runner.invoke(app, ["selection-lab", "build-dataset"])

    assert result.exit_code == 2, result.output
    assert "no_frozen_candidate_chain" in result.output
    assert "status.json" in result.output
