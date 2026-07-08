from datetime import date

import pytest

from stock_analyzer.domain.models import (
    ActionLabel,
    EvaluationTask,
    EvidencePackage,
    FocusState,
    Recommendation,
)
from stock_analyzer.data.models import DataStatus, MarketDataBundle, SourceGrade
from stock_analyzer.pipeline import (
    StoredAnalysisNotFound,
    _sample_market,
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

    def save_market_bars(self, bars):
        self.save_attempts.append("market_bars")
        raise AssertionError("dry-run must not save market bars")

    def save_daily_basic_indicators(self, rows):
        self.save_attempts.append("daily_basic_indicators")
        raise AssertionError("dry-run must not save daily basic indicators")

    def save_data_source_runs(self, rows):
        self.save_attempts.append("data_source_runs")
        raise AssertionError("dry-run must not save data source runs")


class FakeProductionProvider:
    def load(self, trade_date):
        stocks, stock_names, feature_profiles = _sample_market(trade_date)
        return MarketDataBundle(
            trade_date=trade_date,
            data_status=DataStatus.COMPLETE_PRIMARY,
            source_grade=SourceGrade.PRIMARY,
            source_versions={"fake-live": trade_date.isoformat()},
            stock_basic=[],
            daily_bars=[],
            daily_basic=[],
            stocks=stocks,
            stock_names=stock_names,
            feature_profiles=feature_profiles,
            source_runs=[],
        )


class InsufficientProductionProvider:
    def load(self, trade_date):
        stocks, stock_names, feature_profiles = _sample_market(trade_date)
        return MarketDataBundle(
            trade_date=trade_date,
            data_status=DataStatus.INSUFFICIENT_LIVE_DATA,
            source_grade=SourceGrade.PRIMARY,
            source_versions={"fake-live": trade_date.isoformat()},
            stock_basic=[],
            daily_bars=[],
            daily_basic=[],
            stocks=stocks,
            stock_names=stock_names,
            feature_profiles=feature_profiles,
            source_runs=[],
        )


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


def test_run_daily_pipeline_production_uses_provider_and_persists_real_bundle(tmp_path):
    repo = InMemoryAnalysisRepository()

    result = run_daily_pipeline(
        date(2026, 7, 7),
        tmp_path,
        repository=repo,
        fixture_mode=False,
        market_data_provider=FakeProductionProvider(),
    )

    assert result.recommendations
    assert repo.recommendations
    assert repo.stock_master
    assert (tmp_path / "index.html").exists()


def test_run_daily_pipeline_production_fails_when_provider_cannot_generate_decisions(tmp_path):
    repo = FailingSaveRepository()

    with pytest.raises(RuntimeError) as excinfo:
        run_daily_pipeline(
            date(2026, 7, 7),
            tmp_path,
            repository=repo,
            fixture_mode=False,
            market_data_provider=InsufficientProductionProvider(),
        )

    assert "no production decisions were generated" in str(excinfo.value)
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


def test_render_report_for_date_fails_when_recommendation_lacks_matching_evidence(tmp_path):
    repo = InMemoryAnalysisRepository(
        recommendations=[
            Recommendation(
                trade_date=date(2026, 7, 7),
                ts_code="600000.SH",
                name="浦发银行",
                action=ActionLabel.ENTER_OBSERVATION,
                score=81,
                reasons=["趋势改善"],
                risks=["需要确认"],
                evidence_id="missing-evidence-600000",
            )
        ]
    )

    with pytest.raises(StoredAnalysisNotFound) as excinfo:
        render_report_for_date(date(2026, 7, 7), tmp_path, repository=repo)

    assert "Missing evidence package" in str(excinfo.value)
    assert "missing-evidence-600000" in str(excinfo.value)
    assert not (tmp_path / "index.html").exists()


def test_render_report_for_date_fails_when_evaluation_tasks_are_missing(tmp_path):
    recommendation = Recommendation(
        trade_date=date(2026, 7, 7),
        ts_code="600000.SH",
        name="浦发银行",
        action=ActionLabel.ENTER_OBSERVATION,
        score=81,
        reasons=["趋势改善"],
        risks=["需要确认"],
        evidence_id="2026-07-07-600000.SH",
    )
    repo = InMemoryAnalysisRepository(
        recommendations=[recommendation],
        evidence_packages=[
            EvidencePackage(
                evidence_id="2026-07-07-600000.SH",
                trade_date=date(2026, 7, 7),
                ts_code="600000.SH",
                thesis="浦发银行进入观察，趋势改善",
                support=["趋势改善"],
                counter_evidence=["需要确认"],
                matched_rules=["RESEARCH_TREND_CONFIRMATION"],
                confidence_level="medium",
                expected_confirmation_path=["趋势延续"],
                invalidation_conditions=["趋势证据消失"],
                source_versions={"recommendation": "2026-07-07-600000.SH"},
            )
        ],
    )

    with pytest.raises(StoredAnalysisNotFound) as excinfo:
        render_report_for_date(date(2026, 7, 7), tmp_path, repository=repo)

    assert "Missing evaluation task" in str(excinfo.value)
    assert "2026-07-07-600000.SH" in str(excinfo.value)
    assert not (tmp_path / "index.html").exists()


def test_render_report_for_date_renders_complete_stored_analysis(tmp_path):
    recommendation = Recommendation(
        trade_date=date(2026, 7, 7),
        ts_code="600000.SH",
        name="浦发银行",
        action=ActionLabel.ENTER_OBSERVATION,
        score=81,
        reasons=["趋势改善"],
        risks=["需要确认"],
        evidence_id="2026-07-07-600000.SH",
    )
    repo = InMemoryAnalysisRepository(
        recommendations=[recommendation],
        evidence_packages=[
            EvidencePackage(
                evidence_id="2026-07-07-600000.SH",
                trade_date=date(2026, 7, 7),
                ts_code="600000.SH",
                thesis="浦发银行进入观察，趋势改善",
                support=["趋势改善"],
                counter_evidence=["需要确认"],
                matched_rules=["RESEARCH_TREND_CONFIRMATION"],
                confidence_level="medium",
                expected_confirmation_path=["趋势延续"],
                invalidation_conditions=["趋势证据消失"],
                source_versions={"recommendation": "2026-07-07-600000.SH"},
            )
        ],
        evaluation_tasks=[
            EvaluationTask(
                trade_date=date(2026, 7, 7),
                ts_code="600000.SH",
                evidence_id="2026-07-07-600000.SH",
                checkpoint_days=5,
                due_date=date(2026, 7, 14),
                evaluation_layer="result",
            )
        ],
    )

    result = render_report_for_date(date(2026, 7, 7), tmp_path, repository=repo)

    assert result.recommendations == [recommendation]
    assert len(result.evaluation_tasks) == 1
    assert (tmp_path / "index.html").exists()


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
