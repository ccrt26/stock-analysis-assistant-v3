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
from stock_analyzer.storage.repositories import (
    InMemoryAnalysisRepository,
    SupabaseAnalysisRepository,
)
from stock_analyzer.storage.supabase_client import create_supabase_client


class FakeSupabaseResult:
    def __init__(self, data):
        self.data = data


class FakeSupabaseTable:
    def __init__(self, name: str, client: "FakeSupabaseClient") -> None:
        self.name = name
        self.client = client
        self.operation = ""
        self.payload = None

    def insert(self, rows):
        self.operation = "insert"
        self.payload = rows
        return self

    def select(self, columns: str):
        self.operation = "select"
        self.payload = columns
        return self

    def execute(self):
        if self.operation == "insert":
            self.client.insert_calls.append((self.name, self.payload))
            return FakeSupabaseResult(self.payload)
        return FakeSupabaseResult(self.client.table_data.get(self.name, []))


class FakeSupabaseClient:
    def __init__(self) -> None:
        self.insert_calls = []
        self.table_data = {}

    def table(self, name: str) -> FakeSupabaseTable:
        return FakeSupabaseTable(name, self)


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
        confidence_level="medium",
        expected_confirmation_path=["趋势延续"],
        invalidation_conditions=[],
        source_versions={},
    )
    task = EvaluationTask(
        trade_date=date(2026, 7, 7),
        ts_code="600000.SH",
        evidence_id=evidence.evidence_id,
        checkpoint_days=5,
        due_date=date(2026, 7, 12),
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
    assert repo.load_focus_states() == [focus]


def test_supabase_repository_maps_rows_without_network():
    client = FakeSupabaseClient()
    client.table_data["focus_watchlist_state"] = [
        {
            "trade_date": "2026-07-06",
            "ts_code": "600000.SH",
            "state": "进入观察",
            "entry_date": "2026-07-06",
            "entry_reason": "原始证据成立",
            "invalidation_conditions": ["跌破关键支撑"],
            "exit_reason": None,
        }
    ]
    repo = SupabaseAnalysisRepository(client)

    loaded = repo.load_focus_states()
    assert loaded[0].ts_code == "600000.SH"
    assert loaded[0].entry_date == date(2026, 7, 6)

    evidence = EvidencePackage(
        evidence_id="2026-07-07-600000.SH",
        trade_date=date(2026, 7, 7),
        ts_code="600000.SH",
        thesis="观察",
        support=["趋势改善"],
        counter_evidence=["需要确认"],
        matched_rules=["RESEARCH_TREND_CONFIRMATION"],
        confidence_level="medium",
        expected_confirmation_path=["趋势延续"],
        invalidation_conditions=["核心趋势证据消失"],
        source_versions={"recommendation": "2026-07-07-600000.SH"},
    )
    task = EvaluationTask(
        trade_date=date(2026, 7, 7),
        ts_code="600000.SH",
        evidence_id=evidence.evidence_id,
        checkpoint_days=5,
        due_date=date(2026, 7, 12),
        evaluation_layer="result",
    )

    repo.save_evidence_packages([evidence])
    repo.save_evaluation_tasks([task])

    assert client.insert_calls[0][0] == "evidence_package_index"
    evidence_row = client.insert_calls[0][1][0]
    assert evidence_row["confidence_level"] == "medium"
    assert evidence_row["expected_confirmation_path"] == ["趋势延续"]
    assert client.insert_calls[1][0] == "evaluation_task"
    assert client.insert_calls[1][1][0]["due_date"] == "2026-07-12"


def test_supabase_repository_loads_latest_active_focus_state_per_stock():
    client = FakeSupabaseClient()
    client.table_data["focus_watchlist_state"] = [
        {
            "trade_date": "2026-07-05",
            "ts_code": "600000.SH",
            "state": "进入观察",
            "entry_date": "2026-07-05",
            "entry_reason": "原始证据成立",
            "invalidation_conditions": ["跌破关键支撑"],
            "exit_reason": None,
        },
        {
            "trade_date": "2026-07-06",
            "ts_code": "600000.SH",
            "state": "继续观察",
            "entry_date": "2026-07-05",
            "entry_reason": "原始证据成立",
            "invalidation_conditions": ["跌破关键支撑"],
            "exit_reason": None,
        },
        {
            "trade_date": "2026-07-04",
            "ts_code": "600519.SH",
            "state": "进入观察",
            "entry_date": "2026-07-04",
            "entry_reason": "原始证据成立",
            "invalidation_conditions": ["跌破关键支撑"],
            "exit_reason": None,
        },
        {
            "trade_date": "2026-07-07",
            "ts_code": "600519.SH",
            "state": "剔除观察",
            "entry_date": "2026-07-04",
            "entry_reason": "原始证据成立",
            "invalidation_conditions": ["跌破关键支撑"],
            "exit_reason": "触发预设失效条件",
        },
    ]
    repo = SupabaseAnalysisRepository(client)

    loaded = repo.load_focus_states()

    assert [state.ts_code for state in loaded] == ["600000.SH"]
    assert loaded[0].trade_date == date(2026, 7, 6)
    assert loaded[0].state == ActionLabel.CONTINUE_OBSERVATION


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
