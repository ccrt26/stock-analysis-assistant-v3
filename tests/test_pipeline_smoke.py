from datetime import date

from stock_analyzer.domain.models import ActionLabel, FocusState
import pytest

from stock_analyzer.pipeline import (
    StoredAnalysisNotFound,
    render_report_for_date,
    run_daily_pipeline,
)
from stock_analyzer.storage.repositories import InMemoryAnalysisRepository


class FailingSaveRepository(InMemoryAnalysisRepository):
    def __init__(self):
        super().__init__()
        self.save_attempts = []

    def save_stock_master(self, stocks):
        self.save_attempts.append("stock_master")
        raise AssertionError("dry-run must not save stock master")

    def save_stock_statuses(self, stocks):
        self.save_attempts.append("stock_statuses")
        raise AssertionError("dry-run must not save stock statuses")

    def save_feature_snapshots(self, features):
        self.save_attempts.append("feature_snapshots")
        raise AssertionError("dry-run must not save feature snapshots")

    def save_recommendations(self, recommendations):
        self.save_attempts.append("recommendations")
        raise AssertionError("dry-run must not save recommendations")

    def save_focus_states(self, states):
        self.save_attempts.append("focus_states")
        raise AssertionError("dry-run must not save focus states")

    def save_evidence_packages(self, packages):
        self.save_attempts.append("evidence_packages")
        raise AssertionError("dry-run must not save evidence packages")

    def save_evaluation_tasks(self, tasks):
        self.save_attempts.append("evaluation_tasks")
        raise AssertionError("dry-run must not save evaluation tasks")


def test_run_daily_pipeline_creates_report_and_evaluation_tasks(tmp_path):
    result = run_daily_pipeline(
        date(2026, 7, 7),
        tmp_path,
        dry_run=False,
        fixture_mode=True,
    )

    assert result.trade_date.isoformat() == "2026-07-07"
    assert len(result.recommendations) <= 10
    assert len(result.evaluation_tasks) >= len(result.recommendations) * 3
    assert (tmp_path / "index.html").exists()
    assert (tmp_path / "data" / "latest.json").exists()
    assert (tmp_path / "daily" / "2026-07-07" / "index.html").exists()


def test_run_daily_pipeline_dry_run_does_not_persist_any_analysis_state(tmp_path):
    repo = FailingSaveRepository()

    result = run_daily_pipeline(
        date(2026, 7, 7),
        tmp_path,
        dry_run=True,
        repository=repo,
    )

    assert result.recommendations
    assert repo.save_attempts == []
    assert not (tmp_path / "index.html").exists()


def test_run_daily_pipeline_production_without_data_source_fails_before_persisting(tmp_path):
    repo = FailingSaveRepository()

    with pytest.raises(RuntimeError) as excinfo:
        run_daily_pipeline(
            date(2026, 7, 7),
            tmp_path,
            dry_run=False,
            repository=repo,
        )

    assert "real market data ingestion" in str(excinfo.value)
    assert "--fixture-mode" in str(excinfo.value)
    assert repo.save_attempts == []
    assert not (tmp_path / "index.html").exists()


def test_run_daily_pipeline_assigns_evidence_ids_before_return_and_save(tmp_path):
    repo = InMemoryAnalysisRepository()

    result = run_daily_pipeline(
        date(2026, 7, 7),
        tmp_path,
        repository=repo,
        fixture_mode=True,
    )

    assert {item.evidence_id for item in result.recommendations} == {
        package.evidence_id for package in repo.evidence_packages
    }
    assert all(item.evidence_id for item in repo.recommendations)


def test_run_daily_pipeline_preserves_existing_focus_from_repository(tmp_path):
    existing = FocusState(
        trade_date=date(2026, 7, 6),
        ts_code="688001.SH",
        state=ActionLabel.ENTER_OBSERVATION,
        entry_date=date(2026, 7, 6),
        entry_reason="原始证据成立",
        invalidation_conditions=["跌破关键支撑"],
    )
    repo = InMemoryAnalysisRepository(focus_states=[existing])

    result = run_daily_pipeline(
        date(2026, 7, 7),
        tmp_path,
        repository=repo,
        fixture_mode=True,
    )

    preserved = [state for state in result.focus_states if state.ts_code == "688001.SH"]
    assert preserved
    assert preserved[0].trade_date == date(2026, 7, 7)
    assert preserved[0].state == ActionLabel.CONTINUE_OBSERVATION
    assert repo.recommendations
    assert len(repo.focus_states) > 1


def test_render_report_for_date_fails_when_repository_has_no_stored_rows(tmp_path):
    repo = InMemoryAnalysisRepository()

    with pytest.raises(StoredAnalysisNotFound) as excinfo:
        render_report_for_date(date(2026, 7, 7), tmp_path, repository=repo)

    assert "No stored analysis rows found for 2026-07-07" in str(excinfo.value)
    assert not (tmp_path / "index.html").exists()


def test_render_report_for_date_allows_explicit_fixture_fallback(tmp_path):
    repo = InMemoryAnalysisRepository()

    result = render_report_for_date(
        date(2026, 7, 7),
        tmp_path,
        repository=repo,
        allow_fixture_fallback=True,
    )

    assert result.recommendations
    assert (tmp_path / "index.html").exists()
    assert repo.recommendations == []
