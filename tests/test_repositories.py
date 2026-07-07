from datetime import date

import pytest

from stock_analyzer.config import AppConfig
from stock_analyzer.domain.models import (
    ActionLabel,
    EvaluationTask,
    EvidencePackage,
    FocusState,
    Recommendation,
)
from stock_analyzer.storage.supabase_client import create_supabase_client
from stock_analyzer.storage.repositories import InMemoryAnalysisRepository


def test_in_memory_repository_saves_daily_outputs():
    repo = InMemoryAnalysisRepository()
    recommendation = Recommendation(
        trade_date=date(2026, 7, 7),
        ts_code="600000.SH",
        name="浦发银行",
        action=ActionLabel.ENTER_OBSERVATION,
        score=80,
        reasons=["趋势改善"],
        risks=["需要确认"],
        evidence_id="2026-07-07-600000.SH",
    )
    focus = FocusState(
        trade_date=date(2026, 7, 7),
        ts_code="600000.SH",
        state=ActionLabel.ENTER_OBSERVATION,
    )
    evidence = EvidencePackage(
        evidence_id="2026-07-07-600000.SH",
        trade_date=date(2026, 7, 7),
        ts_code="600000.SH",
        thesis="观察",
        support=["趋势改善"],
        counter_evidence=["需要确认"],
        matched_rules=[],
        invalidation_conditions=[],
        source_versions={},
    )
    task = EvaluationTask(
        trade_date=date(2026, 7, 7),
        ts_code="600000.SH",
        evidence_id=evidence.evidence_id,
        checkpoint_days=5,
        evaluation_layer="result",
    )

    repo.save_recommendations([recommendation])
    repo.save_focus_states([focus])
    repo.save_evidence_packages([evidence])
    repo.save_evaluation_tasks([task])

    assert len(repo.recommendations) == 1
    assert len(repo.focus_states) == 1
    assert len(repo.evidence_packages) == 1
    assert len(repo.evaluation_tasks) == 1


@pytest.mark.parametrize(
    "env",
    [
        {},
        {"SUPABASE_SERVICE_ROLE_KEY": "svc_dummy"},
        {"SUPABASE_URL": "https://example.supabase.co"},
    ],
)
def test_create_supabase_client_requires_url_and_service_role_key(env):
    config = AppConfig.load(env=env)
    with pytest.raises(ValueError) as excinfo:
        create_supabase_client(config)
    assert "SUPABASE_URL" in str(excinfo.value)
    assert "SUPABASE_SERVICE_ROLE_KEY" in str(excinfo.value)
