from datetime import date

from stock_analyzer.domain.models import ActionLabel, FocusState
from stock_analyzer.pipeline import run_daily_pipeline
from stock_analyzer.storage.repositories import InMemoryAnalysisRepository


def test_run_daily_pipeline_creates_report_and_evaluation_tasks(tmp_path):
    result = run_daily_pipeline(date(2026, 7, 7), tmp_path, dry_run=False)

    assert result.trade_date.isoformat() == "2026-07-07"
    assert len(result.recommendations) <= 10
    assert len(result.evaluation_tasks) >= len(result.recommendations) * 3
    assert (tmp_path / "index.html").exists()
    assert (tmp_path / "data" / "latest.json").exists()
    assert (tmp_path / "daily" / "2026-07-07" / "index.html").exists()


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

    result = run_daily_pipeline(date(2026, 7, 7), tmp_path, repository=repo)

    preserved = [state for state in result.focus_states if state.ts_code == "688001.SH"]
    assert preserved
    assert preserved[0].trade_date == date(2026, 7, 7)
    assert preserved[0].state == ActionLabel.CONTINUE_OBSERVATION
    assert repo.recommendations
    assert len(repo.focus_states) > 1
