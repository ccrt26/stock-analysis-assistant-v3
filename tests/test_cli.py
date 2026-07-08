from datetime import date

from typer.testing import CliRunner

from stock_analyzer.cli import app
from stock_analyzer.domain.models import (
    ActionLabel,
    EvidencePackage,
    FocusState,
    Recommendation,
)


class RecordingRepository:
    def __init__(self):
        self.load_calls = 0
        self.render_load_calls = []
        self.save_calls = []
        self.daily_recommendations = []
        self.daily_focus_states = []
        self.daily_evidence_packages = []

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

    def load_daily_recommendations(self, trade_date):
        self.render_load_calls.append(("recommendations", trade_date))
        return list(self.daily_recommendations)

    def load_focus_states_for_date(self, trade_date):
        self.render_load_calls.append(("focus_states", trade_date))
        return list(self.daily_focus_states)

    def load_evidence_packages(self, trade_date):
        self.render_load_calls.append(("evidence_packages", trade_date))
        return list(self.daily_evidence_packages)

    def save_stock_master(self, stocks):
        self.save_calls.append(("stock_master", stocks))

    def save_stock_statuses(self, stocks):
        self.save_calls.append(("stock_statuses", stocks))

    def save_feature_snapshots(self, features):
        self.save_calls.append(("feature_snapshots", features))

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


def test_run_daily_dry_run_does_not_persist_analysis_state(monkeypatch):
    repo = RecordingRepository()
    monkeypatch.setattr("stock_analyzer.cli._analysis_repository", lambda config: repo)

    result = CliRunner().invoke(
        app, ["run-daily", "--dry-run", "--trade-date", "2026-07-07"]
    )

    assert result.exit_code == 0
    assert repo.load_calls == 1
    assert repo.save_calls == []


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


def test_render_report_command_uses_stored_repository_data_when_available(tmp_path, monkeypatch):
    repo = RecordingRepository()
    repo.daily_recommendations = [
        Recommendation(
            trade_date=date(2026, 7, 7),
            ts_code="688999.SH",
            name="存量样本",
            action=ActionLabel.CONTINUE_OBSERVATION,
            score=88,
            reasons=["存储证据支持"],
            risks=["存储反证"],
            evidence_id="stored-evidence-688999",
        )
    ]
    repo.daily_evidence_packages = [
        EvidencePackage(
            evidence_id="stored-evidence-688999",
            trade_date=date(2026, 7, 7),
            ts_code="688999.SH",
            thesis="存量样本继续观察",
            support=["存储证据支持"],
            counter_evidence=["存储反证"],
            matched_rules=["RESEARCH_TREND_CONFIRMATION"],
            confidence_level="high",
            expected_confirmation_path=["存储确认信号"],
            invalidation_conditions=["存储失效信号"],
            source_versions={"repository": "stored"},
        )
    ]
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
    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    json_text = (tmp_path / "data" / "latest.json").read_text(encoding="utf-8")
    assert "存量样本" in html
    assert "stored-evidence-688999" in json_text
    assert "浦发银行" not in html
    assert repo.load_calls == 0
    assert repo.save_calls == []


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
