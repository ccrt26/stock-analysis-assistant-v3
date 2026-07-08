from datetime import date

import pytest

from stock_analyzer.config import AppConfig
from stock_analyzer.data.models import (
    DailyBar,
    DailyBasicRow,
    DataStatus,
    SourceGrade,
    SourceRunRecord,
    SourceStatus,
)
from stock_analyzer.domain.models import (
    ActionLabel,
    EvaluationTask,
    EvidencePackage,
    FeatureSnapshot,
    FocusState,
    Recommendation,
    StockSnapshot,
)
from stock_analyzer.storage.repositories import (
    InMemoryAnalysisRepository,
    SupabaseAnalysisRepository,
)
from stock_analyzer.storage.supabase_client import create_supabase_client

try:
    from stock_analyzer.pipeline import run_daily_pipeline
except ModuleNotFoundError as exc:
    if exc.name != "jinja2":
        raise
    run_daily_pipeline = None


class FakeSupabaseResult:
    def __init__(self, data):
        self.data = data


class FakeSupabaseTable:
    def __init__(self, name: str, client: "FakeSupabaseClient") -> None:
        self.name = name
        self.client = client
        self.operation = ""
        self.payload = None
        self.options = {}
        self.filters = []

    def insert(self, rows):
        self.operation = "insert"
        self.payload = rows
        return self

    def upsert(self, rows, **options):
        self.operation = "upsert"
        self.payload = rows
        self.options = options
        return self

    def select(self, columns: str):
        self.operation = "select"
        self.payload = columns
        return self

    def eq(self, column: str, value):
        self.filters.append((column, value))
        return self

    def execute(self):
        if self.operation in {"insert", "upsert"}:
            self.client.write_calls.append((self.name, self.operation, self.payload))
            self.client.write_options.append((self.name, self.operation, self.options))
            if self.operation == "insert":
                self.client.insert_calls.append((self.name, self.payload))
            else:
                self.client.upsert_calls.append((self.name, self.payload))
            return FakeSupabaseResult(self.payload)
        rows = list(self.client.table_data.get(self.name, []))
        for column, value in self.filters:
            rows = [row for row in rows if row.get(column) == value]
        return FakeSupabaseResult(rows)


class FakeSupabaseClient:
    def __init__(self) -> None:
        self.write_calls = []
        self.write_options = []
        self.insert_calls = []
        self.upsert_calls = []
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
    repo.save_stock_master(
        [
            StockSnapshot(
                trade_date=date(2026, 7, 7),
                ts_code="600000.SH",
                name="浦发银行",
                listing_days=6000,
            )
        ]
    )
    repo.save_stock_statuses(
        [
            StockSnapshot(
                trade_date=date(2026, 7, 7),
                ts_code="600000.SH",
                name="浦发银行",
                listing_days=6000,
            )
        ]
    )
    repo.save_feature_snapshots(
        [
            FeatureSnapshot(
                trade_date=date(2026, 7, 7),
                ts_code="600000.SH",
                trend_20d=0.08,
                trend_60d=0.12,
                relative_strength=0.75,
                volatility_20d=0.22,
                liquidity_score=0.9,
                quality_score=0.7,
                market_regime="sideways",
            )
        ]
    )

    assert len(repo.recommendations) == 1
    assert len(repo.focus_states) == 1
    assert len(repo.evidence_packages) == 1
    assert len(repo.evaluation_tasks) == 1
    assert len(repo.stock_master) == 1
    assert len(repo.stock_statuses) == 1
    assert len(repo.feature_snapshots) == 1
    assert repo.load_focus_states() == [focus]
    assert repo.load_evaluation_tasks(date(2026, 7, 7)) == [task]


def test_in_memory_repository_upserts_core_daily_outputs_by_stable_keys():
    repo = InMemoryAnalysisRepository()
    original = Recommendation(
        trade_date=date(2026, 7, 7),
        ts_code="600000.SH",
        name="浦发银行",
        action=ActionLabel.ENTER_OBSERVATION,
        score=80,
        reasons=["趋势改善"],
        risks=["需要确认"],
        evidence_id="2026-07-07-600000.SH",
    )
    updated = original.model_copy(update={"score": 82, "reasons": ["二次运行更新"]})
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
        due_date=date(2026, 7, 14),
        evaluation_layer="result",
    )

    repo.save_recommendations([original])
    repo.save_recommendations([updated])
    repo.save_focus_states([focus])
    repo.save_focus_states(
        [focus.model_copy(update={"state": ActionLabel.CONTINUE_OBSERVATION})]
    )
    repo.save_evidence_packages([evidence])
    repo.save_evidence_packages([evidence.model_copy(update={"confidence_level": "high"})])
    repo.save_evaluation_tasks([task])
    repo.save_evaluation_tasks(
        [task.model_copy(update={"due_date": date(2026, 7, 15)})]
    )

    assert len(repo.recommendations) == 1
    assert repo.recommendations[0].score == 82
    assert repo.recommendations[0].reasons == ["二次运行更新"]
    assert len(repo.focus_states) == 1
    assert repo.focus_states[0].state == ActionLabel.CONTINUE_OBSERVATION
    assert len(repo.evidence_packages) == 1
    assert repo.evidence_packages[0].confidence_level == "high"
    assert len(repo.evaluation_tasks) == 1
    assert repo.evaluation_tasks[0].due_date == date(2026, 7, 15)


def test_in_memory_repository_upserts_ingestion_rows():
    repo = InMemoryAnalysisRepository()
    bar = DailyBar(
        trade_date=date(2026, 7, 8),
        ts_code="600000.SH",
        close=10.2,
        amount=100000000,
        source_name="tushare",
        source_grade=SourceGrade.PRIMARY,
    )
    updated_bar = bar.model_copy(update={"close": 10.4})
    basic = DailyBasicRow(
        trade_date=date(2026, 7, 8),
        ts_code="600000.SH",
        turnover_rate=1.2,
        source_name="tushare",
        source_grade=SourceGrade.PRIMARY,
    )
    updated_basic = basic.model_copy(update={"turnover_rate": 1.4})
    run = SourceRunRecord(
        trade_date=date(2026, 7, 8),
        source_name="tushare",
        stage="daily",
        status=SourceStatus.SUCCESS,
        message="ok",
        source_grade=SourceGrade.PRIMARY,
        data_status=DataStatus.COMPLETE_PRIMARY,
        record_count=1,
    )

    repo.save_market_bars([bar])
    repo.save_market_bars([updated_bar])
    repo.save_daily_basic_indicators([basic])
    repo.save_daily_basic_indicators([updated_basic])
    repo.save_data_source_runs([run])

    assert repo.market_bars == [updated_bar]
    assert repo.daily_basic_indicators == [updated_basic]
    assert repo.data_source_runs == [run]


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

    assert client.upsert_calls[0][0] == "evidence_package_index"
    evidence_row = client.upsert_calls[0][1][0]
    assert evidence_row["confidence_level"] == "medium"
    assert evidence_row["expected_confirmation_path"] == ["趋势延续"]
    assert client.upsert_calls[1][0] == "evaluation_task"
    assert client.upsert_calls[1][1][0]["due_date"] == "2026-07-12"


def test_supabase_repository_persists_ingestion_rows_without_network():
    client = FakeSupabaseClient()
    repo = SupabaseAnalysisRepository(client)

    repo.save_market_bars(
        [
            DailyBar(
                trade_date=date(2026, 7, 8),
                ts_code="600000.SH",
                open=10.0,
                high=10.5,
                low=9.9,
                close=10.2,
                pre_close=10.1,
                pct_chg=0.99,
                vol=12345,
                amount=100000000,
                source_name="tushare",
                source_grade=SourceGrade.PRIMARY,
            )
        ]
    )
    repo.save_daily_basic_indicators(
        [
            DailyBasicRow(
                trade_date=date(2026, 7, 8),
                ts_code="600000.SH",
                turnover_rate=1.2,
                total_mv=250000000,
                circ_mv=200000000,
                pe_ttm=8.5,
                pb=0.9,
                source_name="tushare",
                source_grade=SourceGrade.PRIMARY,
            )
        ]
    )
    repo.save_data_source_runs(
        [
            SourceRunRecord(
                trade_date=date(2026, 7, 8),
                source_name="tushare",
                stage="daily",
                status=SourceStatus.SUCCESS,
                message="ok",
                attempt=2,
                source_grade=SourceGrade.PRIMARY,
                data_status=DataStatus.COMPLETE_PRIMARY,
                record_count=1,
                field_coverage={"close": True},
                payload={"batch": "20260708"},
            )
        ]
    )

    assert [name for name, _, _ in client.write_calls] == [
        "market_price_daily",
        "daily_basic_indicator",
        "data_source_run",
    ]
    assert [operation for _, operation, _ in client.write_calls] == [
        "upsert",
        "upsert",
        "insert",
    ]
    conflict_targets = {
        name: options.get("on_conflict")
        for name, operation, options in client.write_options
        if operation == "upsert"
    }
    assert conflict_targets["market_price_daily"] == "trade_date,ts_code"
    assert conflict_targets["daily_basic_indicator"] == "trade_date,ts_code"
    assert client.write_calls[0][2][0]["source_grade"] == "primary"
    assert client.write_calls[1][2][0]["turnover_rate"] == 1.2
    run_row = client.write_calls[2][2][0]
    assert run_row["trade_date"] == "2026-07-08"
    assert run_row["status"] == "success"
    assert run_row["field_coverage"] == {"close": True}
    assert run_row["payload"] == {"batch": "20260708"}


def test_supabase_repository_upserts_prerequisites_before_dependent_pipeline_rows(tmp_path):
    if run_daily_pipeline is None:
        pytest.skip("jinja2 is not installed in this local test environment")

    client = FakeSupabaseClient()
    repo = SupabaseAnalysisRepository(client)

    result = run_daily_pipeline(
        date(2026, 7, 7),
        tmp_path,
        repository=repo,
        fixture_mode=True,
    )

    write_tables = [name for name, _, _ in client.write_calls]
    assert write_tables == [
        "stock_master",
        "stock_status_daily",
        "daily_feature_snapshot",
        "recommendation_daily",
        "focus_watchlist_state",
        "evidence_package_index",
        "evaluation_task",
    ]
    assert [operation for _, operation, _ in client.write_calls[:3]] == [
        "upsert",
        "upsert",
        "upsert",
    ]
    stock_master_rows = client.write_calls[0][2]
    assert {
        "ts_code": "600000.SH",
        "name": "浦发银行",
        "exchange": "SH",
        "list_date": None,
    } in stock_master_rows
    status_rows = client.write_calls[1][2]
    assert status_rows[0]["trade_date"] == "2026-07-07"
    assert "official_risk_events" in status_rows[0]
    feature_rows = client.write_calls[2][2]
    assert feature_rows[0]["features"]["trend_20d"] == 0.08
    recommendation_rows = client.write_calls[3][2]
    assert all(row["evidence_id"] for row in recommendation_rows)
    assert all(item.evidence_id for item in result.recommendations)


def test_supabase_repository_upserts_core_daily_rows_with_conflict_targets(tmp_path):
    if run_daily_pipeline is None:
        pytest.skip("jinja2 is not installed in this local test environment")

    client = FakeSupabaseClient()
    repo = SupabaseAnalysisRepository(client)

    run_daily_pipeline(
        date(2026, 7, 7),
        tmp_path,
        repository=repo,
        fixture_mode=True,
    )

    assert [name for name, _, _ in client.write_calls] == [
        "stock_master",
        "stock_status_daily",
        "daily_feature_snapshot",
        "recommendation_daily",
        "focus_watchlist_state",
        "evidence_package_index",
        "evaluation_task",
    ]
    assert [operation for _, operation, _ in client.write_calls] == [
        "upsert",
        "upsert",
        "upsert",
        "upsert",
        "upsert",
        "upsert",
        "upsert",
    ]
    conflict_targets = {
        name: options.get("on_conflict")
        for name, operation, options in client.write_options
        if operation == "upsert"
    }
    assert conflict_targets["recommendation_daily"] == "trade_date,ts_code"
    assert conflict_targets["focus_watchlist_state"] == "trade_date,ts_code"
    assert conflict_targets["evidence_package_index"] == "evidence_id"
    assert (
        conflict_targets["evaluation_task"]
        == "trade_date,ts_code,evidence_id,checkpoint_days,evaluation_layer"
    )


def test_supabase_repository_loads_daily_analysis_rows_for_report_rendering():
    client = FakeSupabaseClient()
    client.table_data["recommendation_daily"] = [
        {
            "trade_date": "2026-07-07",
            "ts_code": "600000.SH",
            "name": "浦发银行",
            "action": "进入观察",
            "score": 88,
            "reasons": ["趋势改善"],
            "risks": ["需要确认"],
            "evidence_id": "2026-07-07-600000.SH",
        },
        {
            "trade_date": "2026-07-08",
            "ts_code": "600519.SH",
            "name": "贵州茅台",
            "action": "进入观察",
            "score": 84,
            "reasons": ["趋势改善"],
            "risks": ["需要确认"],
            "evidence_id": "2026-07-08-600519.SH",
        },
    ]
    client.table_data["focus_watchlist_state"] = [
        {
            "trade_date": "2026-07-07",
            "ts_code": "600000.SH",
            "state": "进入观察",
            "entry_date": "2026-07-07",
            "entry_reason": "原始证据成立",
            "invalidation_conditions": ["跌破关键支撑"],
            "exit_reason": None,
        }
    ]
    client.table_data["evidence_package_index"] = [
        {
            "evidence_id": "2026-07-07-600000.SH",
            "trade_date": "2026-07-07",
            "ts_code": "600000.SH",
            "thesis": "观察",
            "support": ["趋势改善"],
            "counter_evidence": ["需要确认"],
            "matched_rules": ["RESEARCH_TREND_CONFIRMATION"],
            "confidence_level": "medium",
            "expected_confirmation_path": ["趋势延续"],
            "invalidation_conditions": ["核心趋势证据消失"],
            "source_versions": {"recommendation": "2026-07-07-600000.SH"},
        }
    ]
    client.table_data["evaluation_task"] = [
        {
            "trade_date": "2026-07-07",
            "ts_code": "600000.SH",
            "evidence_id": "2026-07-07-600000.SH",
            "checkpoint_days": 5,
            "due_date": "2026-07-14",
            "evaluation_layer": "result",
        },
        {
            "trade_date": "2026-07-08",
            "ts_code": "600519.SH",
            "evidence_id": "2026-07-08-600519.SH",
            "checkpoint_days": 5,
            "due_date": "2026-07-15",
            "evaluation_layer": "result",
        },
    ]
    repo = SupabaseAnalysisRepository(client)

    recommendations = repo.load_daily_recommendations(date(2026, 7, 7))
    focus_states = repo.load_focus_states_for_date(date(2026, 7, 7))
    evidence_packages = repo.load_evidence_packages(date(2026, 7, 7))
    evaluation_tasks = repo.load_evaluation_tasks(date(2026, 7, 7))

    assert [item.ts_code for item in recommendations] == ["600000.SH"]
    assert recommendations[0].name == "浦发银行"
    assert [item.ts_code for item in focus_states] == ["600000.SH"]
    assert evidence_packages[0].matched_rules == ["RESEARCH_TREND_CONFIRMATION"]
    assert [item.evidence_id for item in evaluation_tasks] == ["2026-07-07-600000.SH"]
    assert evaluation_tasks[0].due_date == date(2026, 7, 14)


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
