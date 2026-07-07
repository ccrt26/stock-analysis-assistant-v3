from datetime import date

from typer.testing import CliRunner

from stock_analyzer.cli import app
from stock_analyzer.domain.models import ActionLabel, FocusState


class RecordingRepository:
    def __init__(self):
        self.load_calls = 0
        self.save_calls = []

    def load_focus_states(self):
        self.load_calls += 1
        return [
            FocusState(
                trade_date=date(2026, 7, 6),
                ts_code="688001.SH",
                state=ActionLabel.ENTER_OBSERVATION,
                entry_date=date(2026, 7, 6),
                entry_reason="原始证据成立",
            )
        ]

    def save_recommendations(self, recommendations):
        self.save_calls.append(("recommendations", recommendations))

    def save_focus_states(self, states):
        self.save_calls.append(("focus_states", states))

    def save_evidence_packages(self, packages):
        self.save_calls.append(("evidence_packages", packages))

    def save_evaluation_tasks(self, tasks):
        self.save_calls.append(("evaluation_tasks", tasks))


def test_health_check_command_prints_status():
    result = CliRunner().invoke(app, ["health-check"])
    assert result.exit_code == 0
    assert "credential" in result.stdout
    assert "network" in result.stdout
    assert "api_response" in result.stdout
    assert "field_consumability" in result.stdout


def test_run_daily_dry_run_completes():
    result = CliRunner().invoke(
        app, ["run-daily", "--dry-run", "--trade-date", "2026-07-07"]
    )
    assert result.exit_code == 0
    assert "daily run dry-run completed for 2026-07-07" in result.stdout


def test_render_report_command_writes_requested_output_dir(tmp_path):
    result = CliRunner().invoke(
        app,
        [
            "render-report",
            "--trade-date",
            "2026-07-07",
            "--output-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0
    assert "report rendered for 2026-07-07" in result.stdout
    assert (tmp_path / "index.html").exists()
    assert (tmp_path / "daily" / "2026-07-07" / "index.html").exists()


def test_render_report_command_does_not_persist_analysis_state(tmp_path, monkeypatch):
    repo = RecordingRepository()
    monkeypatch.setattr("stock_analyzer.cli._analysis_repository", lambda config: repo)

    result = CliRunner().invoke(
        app,
        [
            "render-report",
            "--trade-date",
            "2026-07-07",
            "--output-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0
    assert repo.load_calls == 1
    assert repo.save_calls == []
    assert (tmp_path / "index.html").exists()
