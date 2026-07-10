import logging
from datetime import date

import pytest

from stock_analyzer.config import AppConfig
from stock_analyzer.data.models import (
    DailyBar,
    DailyBasicRow,
    DataStatus,
    MarketDataBundle,
    SourceGrade,
    SourceRunRecord,
    SourceStatus,
    StockBasicRow,
)
from stock_analyzer.domain.models import (
    ActionDecision,
    ActionLabel,
    ActionRecommendation,
    ActionRecommendationSummary,
    EvaluationTask,
    EvidencePackage,
    FocusDailyUpdate,
    FocusEntryThesis,
    FocusSource,
    FeatureSnapshot,
    FocusState,
    ManualHoldingSummary,
    OperationalDailyStatus,
    OperationalReportState,
    Recommendation,
    StockSnapshot,
    StrategyEvidenceSnapshot,
)
from stock_analyzer.storage.repositories import (
    InMemoryAnalysisRepository,
    SupabaseAnalysisRepository,
)
from stock_analyzer.storage.capacity_guard import SupabaseCapacityGuard
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
        self.table_calls = []
        self.table_data = {}
        self.rpc_calls = []

    def table(self, name: str) -> FakeSupabaseTable:
        self.table_calls.append(name)
        return FakeSupabaseTable(name, self)

    def rpc(self, name: str, params=None):
        self.rpc_calls.append((name, params or {}))
        return FakeSupabaseResult([{ "activated": True }])


class RejectingCapacityGuard:
    def __init__(self) -> None:
        self.calls = 0

    def ensure_large_writes_allowed(self) -> None:
        self.calls += 1
        raise RuntimeError("capacity stopped")


class FakeRpcResult:
    def __init__(self, data):
        self.data = data


class FakeCapacityClient:
    def __init__(self, size_mb):
        self.size_mb = size_mb

    def rpc(self, name):
        assert name == "database_size_mb"
        return self

    def execute(self):
        return FakeRpcResult(self.size_mb)


class RecordingWarehouse:
    def __init__(self):
        self.saved_bundles = []

    def save_bundle(self, bundle):
        self.saved_bundles.append(bundle)


def _strategy_v2_action() -> ActionRecommendation:
    return ActionRecommendation(
        decision=ActionDecision.WAIT_FOR_CONFIRMATION,
        position_min_pct=0.0,
        position_max_pct=3.0,
        reasoning=["趋势证据偏积极，但仍需确认。"],
        required_confirmation=["板块相对强度继续改善"],
        invalidation_conditions=["跌破 20 日均线且放量"],
        risk_if_wrong="若是假突破，短线回撤可能扩大。",
        staging_plan=["等待确认后再进入观察仓位。"],
    )


def _strategy_v2_snapshot() -> StrategyEvidenceSnapshot:
    return StrategyEvidenceSnapshot(
        evidence_id="2026-07-10-600000.SH",
        trade_date=date(2026, 7, 10),
        ts_code="600000.SH",
        name="浦发银行",
        action=_strategy_v2_action(),
        thesis="银行板块企稳下的 2-8 周修复观察。",
        expected_upside_pct=10.0,
        expected_downside_pct=6.0,
        risk_reward=1.67,
        focus_entry_progress="观察第 2/5 个交易日。",
        display_rank_bucket="重点观察",
        internal_score=86.0,
        source_versions={"market_daily": "2026-07-10"},
    )


def _focus_entry_thesis() -> FocusEntryThesis:
    snapshot = _strategy_v2_snapshot()
    return FocusEntryThesis(
        evidence_id=snapshot.evidence_id,
        trade_date=snapshot.trade_date,
        ts_code=snapshot.ts_code,
        name=snapshot.name,
        source=FocusSource.SYSTEM,
        thesis=snapshot.thesis,
        action=snapshot.action,
        required_confirmation=snapshot.action.required_confirmation,
        invalidation_conditions=snapshot.action.invalidation_conditions,
        supporting_evidence_ids=[snapshot.evidence_id],
        validation_result="通过",
        risk_notes=[snapshot.action.risk_if_wrong],
    )


def _focus_daily_update() -> FocusDailyUpdate:
    snapshot = _strategy_v2_snapshot()
    return FocusDailyUpdate(
        trade_date=snapshot.trade_date,
        ts_code=snapshot.ts_code,
        name=snapshot.name,
        evidence_id=snapshot.evidence_id,
        thesis=snapshot.thesis,
        action=snapshot.action,
        focus_entry_progress="观察第 2/5 个交易日，最近 5 日支持 2 日。",
        required_confirmation=snapshot.action.required_confirmation,
        invalidation_conditions=snapshot.action.invalidation_conditions,
    )


def _action_recommendation_summary() -> ActionRecommendationSummary:
    action = _strategy_v2_action()
    return ActionRecommendationSummary(
        trade_date=date(2026, 7, 10),
        ts_code="600000.SH",
        decision=action.decision,
        position_min_pct=action.position_min_pct,
        position_max_pct=action.position_max_pct,
        invalidation_conditions=action.invalidation_conditions,
    )


def _manual_holding_summary() -> ManualHoldingSummary:
    return ManualHoldingSummary(
        trade_date=date(2026, 7, 10),
        ts_code="600000.SH",
        held=True,
        position_band="0-3%",
        last_action_state="等待确认",
    )


def _operational_daily_status() -> OperationalDailyStatus:
    return OperationalDailyStatus(
        trade_date=date(2026, 7, 10),
        is_trading_day=True,
        recommendation_state=OperationalReportState.DATA_INSUFFICIENT,
        focus_state=OperationalReportState.DATA_INSUFFICIENT,
        recommendation_count=0,
        focus_count=0,
        blocking_missing_fields=["daily_basic.turnover_rate"],
        message="行情基础指标不足，保留阻塞状态。",
    )


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


def test_strategy_v2_repository_saves_operational_status_to_narrow_table():
    repo = InMemoryAnalysisRepository()
    status = _operational_daily_status()

    repo.save_operational_daily_status(status)

    assert repo.operational_daily_statuses[0] == status


def test_in_memory_repository_upserts_strategy_v2_ledger_by_stable_keys():
    repo = InMemoryAnalysisRepository()
    snapshot = _strategy_v2_snapshot()
    thesis = _focus_entry_thesis()
    update = _focus_daily_update()
    recommendation = _action_recommendation_summary()
    holding = _manual_holding_summary()
    status = _operational_daily_status()

    repo.save_strategy_snapshots([snapshot])
    repo.save_strategy_snapshots(
        [snapshot.model_copy(update={"display_rank_bucket": "强观察"})]
    )
    repo.save_focus_entry_theses([thesis])
    repo.save_focus_entry_theses(
        [thesis.model_copy(update={"validation_result": "复核通过"})]
    )
    repo.save_focus_daily_updates([update])
    repo.save_focus_daily_updates(
        [update.model_copy(update={"focus_entry_progress": "观察第 3/5 个交易日。"})]
    )
    repo.save_action_recommendations([recommendation])
    repo.save_action_recommendations(
        [recommendation.model_copy(update={"position_max_pct": 2.0})]
    )
    repo.save_manual_holding_summaries([holding])
    repo.save_manual_holding_summaries(
        [holding.model_copy(update={"position_band": "1-2%"})]
    )
    repo.save_operational_daily_status(status)
    repo.save_operational_daily_status(
        status.model_copy(update={"message": "二次运行仍然阻塞。"})
    )

    assert len(repo.strategy_snapshots) == 1
    assert repo.strategy_snapshots[0].display_rank_bucket == "强观察"
    assert len(repo.focus_entry_theses) == 1
    assert repo.focus_entry_theses[0].validation_result == "复核通过"
    assert len(repo.focus_daily_updates) == 1
    assert repo.focus_daily_updates[0].focus_entry_progress == "观察第 3/5 个交易日。"
    assert len(repo.action_recommendation_summaries) == 1
    assert repo.action_recommendation_summaries[0].position_max_pct == 2.0
    assert len(repo.manual_holding_summaries) == 1
    assert repo.manual_holding_summaries[0].position_band == "1-2%"
    assert len(repo.operational_daily_statuses) == 1
    assert repo.operational_daily_statuses[0].message == "二次运行仍然阻塞。"


def test_in_memory_repository_loads_only_formally_committed_strategy_snapshots():
    from tests.test_focus_strategy_v2 import _snapshot

    committed_date = date(2026, 7, 8)
    uncommitted_date = date(2026, 7, 9)
    current_date = date(2026, 7, 10)
    repo = InMemoryAnalysisRepository(
        strategy_snapshots=[
            _snapshot(committed_date),
            _snapshot(uncommitted_date),
            _snapshot(current_date),
        ],
        formally_committed_run_dates={committed_date},
    )

    loaded = repo.load_formally_committed_strategy_snapshots(
        before_date=current_date,
        eligible_dates=[committed_date, uncommitted_date, current_date],
    )

    assert [snapshot.trade_date for snapshot in loaded] == [committed_date]


def test_supabase_repository_loads_snapshots_only_through_active_formal_receipt_view():
    from tests.test_focus_strategy_v2 import _snapshot

    active_date = date(2026, 7, 8)
    inactive_date = date(2026, 7, 9)
    active = _snapshot(active_date)
    inactive = _snapshot(inactive_date)
    client = FakeSupabaseClient()
    client.table_data["active_formal_run_receipt"] = [
        {"target_date": active_date.isoformat()}
    ]
    client.table_data["strategy_v2_snapshot"] = [
        {
            "trade_date": active_date.isoformat(),
            "payload": active.model_dump(mode="json"),
        },
        {
            "trade_date": inactive_date.isoformat(),
            "payload": inactive.model_dump(mode="json"),
        },
    ]
    repo = SupabaseAnalysisRepository(client)

    loaded = repo.load_formally_committed_strategy_snapshots(
        before_date=date(2026, 7, 10),
        eligible_dates=[active_date, inactive_date],
    )

    assert [snapshot.trade_date for snapshot in loaded] == [active_date]
    assert client.table_calls[:2] == [
        "active_formal_run_receipt",
        "strategy_v2_snapshot",
    ]


def test_supabase_repository_prepares_pending_formal_rows_and_activates_through_rpc():
    from stock_analyzer.ops.activation import hash_ledger_rows

    client = FakeSupabaseClient()
    repo = SupabaseAnalysisRepository(client)
    rows = ({"kind": "focus", "ts_code": "600000.SH"},)

    pending_id = repo.prepare_formal_run("run-1", "receipt-hash", rows)

    assert pending_id.startswith("pending-")
    assert client.write_calls[0][0] == "formal_run_pending_batch"
    pending_row = client.write_calls[0][2][0]
    assert pending_row["status"] == "pending"
    assert pending_row["rows"] == list(rows)
    assert pending_row["rows_hash"] == hash_ledger_rows(rows)
    client.table_data["formal_run_pending_batch"] = [pending_row]
    assert repo.pending_hash(pending_id) == pending_row["rows_hash"]

    repo.activate_formal_run("run-1", pending_id, "activation-1")

    assert client.rpc_calls == [
        (
            "activate_formal_run_v1",
            {
                "p_run_id": "run-1",
                "p_pending_id": pending_id,
                "p_activation_id": "activation-1",
                "p_expected_receipt_hash": "receipt-hash",
                "p_expected_rows_hash": pending_row["rows_hash"],
            },
        )
    ]


def test_supabase_repository_active_marker_read_is_fail_closed():
    client = FakeSupabaseClient()
    repo = SupabaseAnalysisRepository(client)
    client.table_data["active_formal_run_receipt"] = [
        {"run_id": "run-1", "activation_id": "activation-1"}
    ]

    assert repo.is_formal_run_active("run-1", "activation-1") is True
    assert repo.is_formal_run_active("run-1", "other") is False


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


def test_supabase_repository_upserts_strategy_v2_ledger_without_network():
    client = FakeSupabaseClient()
    repo = SupabaseAnalysisRepository(client)
    snapshot = _strategy_v2_snapshot()
    thesis = _focus_entry_thesis()
    update = _focus_daily_update()
    recommendation = _action_recommendation_summary()
    holding = _manual_holding_summary()
    status = _operational_daily_status()

    repo.save_strategy_snapshots([snapshot])
    repo.save_focus_entry_theses([thesis])
    repo.save_focus_daily_updates([update])
    repo.save_action_recommendations([recommendation])
    repo.save_manual_holding_summaries([holding])
    repo.save_operational_daily_status(status)

    assert [name for name, _, _ in client.write_calls] == [
        "strategy_v2_snapshot",
        "focus_entry_thesis",
        "focus_daily_update",
        "action_recommendation_summary",
        "manual_holding_summary",
        "operational_daily_status",
    ]
    assert "market_price_daily" not in client.table_calls
    assert "daily_basic_indicator" not in client.table_calls

    conflict_targets = {
        name: options.get("on_conflict")
        for name, operation, options in client.write_options
        if operation == "upsert"
    }
    assert conflict_targets["strategy_v2_snapshot"] == "evidence_id"
    assert conflict_targets["focus_entry_thesis"] == "evidence_id"
    assert conflict_targets["focus_daily_update"] == "trade_date,ts_code"
    assert conflict_targets["action_recommendation_summary"] == "trade_date,ts_code"
    assert conflict_targets["manual_holding_summary"] == "trade_date,ts_code"
    assert conflict_targets["operational_daily_status"] == "trade_date"

    snapshot_row = client.write_calls[0][2][0]
    assert snapshot_row["payload"]["trade_date"] == "2026-07-10"
    assert snapshot_row["action_payload"]["reasoning"] == snapshot.action.reasoning
    assert snapshot_row["data_insufficient"] is False
    assert snapshot_row["source_versions"] == {"market_daily": "2026-07-10"}
    assert len(snapshot_row["sha256"]) == 64

    thesis_row = client.write_calls[1][2][0]
    assert thesis_row["source"] == "system"
    assert thesis_row["thesis_payload"]["action"]["decision"] == "等待确认"
    assert thesis_row["action_payload"]["required_confirmation"] == [
        "板块相对强度继续改善"
    ]

    update_row = client.write_calls[2][2][0]
    assert update_row["update_payload"]["focus_entry_progress"].startswith("观察第")
    assert update_row["action_payload"]["invalidation_conditions"] == [
        "跌破 20 日均线且放量"
    ]

    recommendation_row = client.write_calls[3][2][0]
    assert recommendation_row == {
        "trade_date": "2026-07-10",
        "ts_code": "600000.SH",
        "decision": "等待确认",
        "position_min_pct": 0.0,
        "position_max_pct": 3.0,
        "invalidation_conditions": ["跌破 20 日均线且放量"],
    }

    holding_row = client.write_calls[4][2][0]
    assert holding_row["held"] is True
    assert holding_row["position_band"] == "0-3%"
    assert holding_row["last_action_state"] == "等待确认"

    status_row = client.write_calls[5][2][0]
    assert status_row["recommendation_state"] == "data_insufficient"
    assert status_row["focus_state"] == "data_insufficient"
    assert status_row["blocking_missing_fields"] == ["daily_basic.turnover_rate"]


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


def test_supabase_repository_rejects_full_market_window_without_network():
    client = FakeSupabaseClient()
    repo = SupabaseAnalysisRepository(client)
    trade_date = date(2026, 7, 8)

    with pytest.raises(ValueError) as excinfo:
        repo.save_market_bars(
            [
                DailyBar(
                    trade_date=trade_date,
                    ts_code=f"600{i:03d}.SH",
                    close=10.0,
                    amount=100000000,
                    source_name="tushare",
                    source_grade=SourceGrade.PRIMARY,
                )
                for i in range(41)
            ]
        )

    assert "selected market window" in str(excinfo.value)
    assert client.write_calls == []


def test_supabase_repository_rejects_oversized_market_window_without_network():
    client = FakeSupabaseClient()
    repo = SupabaseAnalysisRepository(client)
    trade_date = date(2026, 7, 8)

    with pytest.raises(ValueError) as market_excinfo:
        repo.save_market_bars(
            [
                DailyBar(
                    trade_date=trade_date,
                    ts_code=f"600{i % 40:03d}.SH",
                    close=10.0,
                    amount=100000000,
                    source_name="tushare",
                    source_grade=SourceGrade.PRIMARY,
                )
                for i in range(5001)
            ]
        )
    with pytest.raises(ValueError) as basic_excinfo:
        repo.save_daily_basic_indicators(
            [
                DailyBasicRow(
                    trade_date=trade_date,
                    ts_code=f"600{i % 40:03d}.SH",
                    turnover_rate=1.2,
                    source_name="tushare",
                    source_grade=SourceGrade.PRIMARY,
                )
                for i in range(5001)
            ]
        )

    assert "selected market window" in str(market_excinfo.value)
    assert "selected market window" in str(basic_excinfo.value)
    assert client.write_calls == []


@pytest.mark.parametrize(
    ("method_name", "rows"),
    [
        (
            "save_market_bars",
            [
                DailyBar(
                    trade_date=date(2026, 7, 8),
                    ts_code="600000.SH",
                    close=10.0,
                    source_name="tushare",
                    source_grade=SourceGrade.PRIMARY,
                )
            ],
        ),
        (
            "save_daily_basic_indicators",
            [
                DailyBasicRow(
                    trade_date=date(2026, 7, 8),
                    ts_code="600000.SH",
                    turnover_rate=1.2,
                    source_name="tushare",
                    source_grade=SourceGrade.PRIMARY,
                )
            ],
        ),
    ],
)
def test_supabase_repository_capacity_rejection_prevents_ingestion_writes(
    method_name,
    rows,
):
    client = FakeSupabaseClient()
    guard = RejectingCapacityGuard()
    repo = SupabaseAnalysisRepository(client, capacity_guard=guard)

    with pytest.raises(RuntimeError, match="capacity stopped"):
        getattr(repo, method_name)(rows)

    assert guard.calls == 1
    assert client.write_calls == []


def test_supabase_repository_scope_guard_runs_before_capacity_guard_for_wide_writes():
    client = FakeSupabaseClient()
    guard = RejectingCapacityGuard()
    repo = SupabaseAnalysisRepository(client, capacity_guard=guard)
    trade_date = date(2026, 7, 8)

    with pytest.raises(ValueError, match="selected market window"):
        repo.save_market_bars(
            [
                DailyBar(
                    trade_date=trade_date,
                    ts_code=f"600{i:03d}.SH",
                    close=10.0,
                    amount=100000000,
                    source_name="tushare",
                    source_grade=SourceGrade.PRIMARY,
                )
                for i in range(41)
            ]
        )

    assert guard.calls == 0
    assert client.write_calls == []


def test_supabase_repository_preflight_checks_capacity_without_table_calls():
    client = FakeSupabaseClient()
    guard = RejectingCapacityGuard()
    repo = SupabaseAnalysisRepository(client, capacity_guard=guard)

    with pytest.raises(RuntimeError, match="capacity stopped"):
        repo.preflight_market_window_writes(
            [
                DailyBar(
                    trade_date=date(2026, 7, 8),
                    ts_code="600000.SH",
                    close=10.0,
                    source_name="tushare",
                    source_grade=SourceGrade.PRIMARY,
                )
            ],
            [
                DailyBasicRow(
                    trade_date=date(2026, 7, 8),
                    ts_code="600000.SH",
                    turnover_rate=1.2,
                    source_name="tushare",
                    source_grade=SourceGrade.PRIMARY,
                )
            ],
        )

    assert guard.calls == 1
    assert client.table_calls == []
    assert client.write_calls == []


def test_supabase_repository_logs_capacity_warning_without_blocking_preflight(caplog):
    client = FakeSupabaseClient()
    guard = SupabaseCapacityGuard(
        FakeCapacityClient(350),
        warn_mb=350,
        stop_mb=400,
    )
    repo = SupabaseAnalysisRepository(client, capacity_guard=guard)

    with caplog.at_level(logging.WARNING, logger="stock_analyzer.storage.repositories"):
        repo.preflight_market_window_writes(
            [
                DailyBar(
                    trade_date=date(2026, 7, 8),
                    ts_code="600000.SH",
                    close=10.0,
                    source_name="tushare",
                    source_grade=SourceGrade.PRIMARY,
                )
            ],
            [
                DailyBasicRow(
                    trade_date=date(2026, 7, 8),
                    ts_code="600000.SH",
                    turnover_rate=1.2,
                    source_name="tushare",
                    source_grade=SourceGrade.PRIMARY,
                )
            ],
        )

    assert "Supabase database size is 350.0 MB" in caplog.text
    assert "large writes stop at 400.0 MB" in caplog.text
    assert client.table_calls == []
    assert client.write_calls == []


def test_supabase_repository_logs_capacity_warning_without_blocking_ingestion_write(
    caplog,
):
    client = FakeSupabaseClient()
    guard = SupabaseCapacityGuard(
        FakeCapacityClient(350),
        warn_mb=350,
        stop_mb=400,
    )
    repo = SupabaseAnalysisRepository(client, capacity_guard=guard)

    with caplog.at_level(logging.WARNING, logger="stock_analyzer.storage.repositories"):
        repo.save_market_bars(
            [
                DailyBar(
                    trade_date=date(2026, 7, 8),
                    ts_code="600000.SH",
                    close=10.0,
                    source_name="tushare",
                    source_grade=SourceGrade.PRIMARY,
                )
            ],
        )

    assert "Supabase database size is 350.0 MB" in caplog.text
    assert "large writes stop at 400.0 MB" in caplog.text
    assert [name for name, _, _ in client.write_calls] == ["market_price_daily"]


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


def test_production_pipeline_writes_full_stock_master_before_market_bars(tmp_path):
    if run_daily_pipeline is None:
        pytest.skip("jinja2 is not installed in this local test environment")

    class ProviderWithRawBarsBeyondFeatureUniverse:
        def load(self, trade_date):
            stock = StockSnapshot(
                trade_date=trade_date,
                ts_code="600000.SH",
                name="浦发银行",
                listing_days=9000,
                turnover_rate=1.2,
                amount=200000000,
            )
            feature = FeatureSnapshot(
                trade_date=trade_date,
                ts_code="600000.SH",
                trend_20d=0.2,
                trend_60d=0.2,
                relative_strength=0.2,
                volatility_20d=0.1,
                liquidity_score=0.8,
                quality_score=0.7,
                market_regime="unknown",
                data_quality="ok",
            )
            return MarketDataBundle(
                trade_date=trade_date,
                data_status=DataStatus.COMPLETE_PRIMARY,
                source_grade=SourceGrade.PRIMARY,
                source_versions={"fake-live": trade_date.isoformat()},
                stock_basic=[
                    StockBasicRow(
                        ts_code="600000.SH",
                        name="浦发银行",
                        exchange="SSE",
                        list_date=date(1999, 11, 10),
                    ),
                    StockBasicRow(
                        ts_code="000004.SZ",
                        name="国华网安",
                        exchange="SZSE",
                        list_date=date(1991, 1, 14),
                    ),
                ],
                daily_bars=[
                    DailyBar(
                        trade_date=trade_date,
                        ts_code="600000.SH",
                        close=10.2,
                        amount=200000000,
                        source_name="fake-live",
                        source_grade=SourceGrade.PRIMARY,
                    ),
                    DailyBar(
                        trade_date=trade_date,
                        ts_code="000004.SZ",
                        close=12.3,
                        amount=80000000,
                        source_name="fake-live",
                        source_grade=SourceGrade.PRIMARY,
                    ),
                ],
                daily_basic=[
                    DailyBasicRow(
                        trade_date=trade_date,
                        ts_code="600000.SH",
                        turnover_rate=1.2,
                        source_name="fake-live",
                        source_grade=SourceGrade.PRIMARY,
                    )
                ],
                source_runs=[],
                stocks=[stock],
                stock_names={
                    "600000.SH": "浦发银行",
                    "000004.SZ": "国华网安",
                },
                feature_profiles={"600000.SH": feature},
            )

    client = FakeSupabaseClient()
    repo = SupabaseAnalysisRepository(client)
    warehouse = RecordingWarehouse()

    run_daily_pipeline(
        date(2026, 7, 8),
        tmp_path,
        repository=repo,
        fixture_mode=False,
        market_data_provider=ProviderWithRawBarsBeyondFeatureUniverse(),
        local_warehouse=warehouse,
    )

    assert len(warehouse.saved_bundles) == 1
    write_tables = [name for name, _, _ in client.write_calls]
    assert write_tables.index("stock_master") < write_tables.index("market_price_daily")
    first_stock_master_rows = client.write_calls[0][2]
    assert {
        "ts_code": "000004.SZ",
        "name": "国华网安",
        "exchange": "SZSE",
        "list_date": "1991-01-14",
    } in first_stock_master_rows


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
