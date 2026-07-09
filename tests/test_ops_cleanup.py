from __future__ import annotations

from datetime import date, datetime

import pytest

from stock_analyzer.data.models import (
    DailyBar,
    DailyBasicRow,
    DataStatus,
    SourceGrade,
    SourceRunRecord,
    SourceStatus,
    StockBasicRow,
)
from stock_analyzer.domain.models import (
    ActionLabel,
    EvaluationTask,
    EvidencePackage,
    FocusState,
    Recommendation,
)
from stock_analyzer.ops.cleanup import (
    APPROVED_SAME_DAY_CLEANUP_TABLES,
    cleanup_trade_date,
)
from stock_analyzer.storage.repositories import (
    InMemoryAnalysisRepository,
    SupabaseAnalysisRepository,
)


class RecordingCleanupRepository:
    def __init__(self):
        self.calls = []

    def cleanup_trade_date(self, trade_date):
        self.calls.append(trade_date)
        return {"recommendation_daily": 2}


class FailingCleanupRepository:
    def __init__(self):
        self.calls = []

    def cleanup_trade_date(self, trade_date):
        self.calls.append(trade_date)
        raise RuntimeError("database cleanup failed")


class FakeSupabaseResult:
    def __init__(self, data):
        self.data = data


class FakeDeleteTable:
    def __init__(self, name: str, client: "FakeDeleteClient") -> None:
        self.name = name
        self.client = client
        self.operation = None
        self.filters = []

    def delete(self):
        self.operation = "delete"
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def execute(self):
        self.client.delete_calls.append((self.name, self.operation, tuple(self.filters)))
        return FakeSupabaseResult(self.client.deleted_rows.get(self.name, []))


class FakeDeleteClient:
    def __init__(self) -> None:
        self.delete_calls = []
        self.deleted_rows = {
            table: [{"trade_date": "2026-07-09"}]
            for table in APPROVED_SAME_DAY_CLEANUP_TABLES
        }

    def table(self, name: str):
        return FakeDeleteTable(name, self)


def test_cleanup_calls_repository_for_target_date_and_removes_same_day_files(tmp_path):
    trade_date = date(2026, 7, 9)
    previous_date = date(2026, 7, 8)
    repository = RecordingCleanupRepository()

    same_day_paths = [
        tmp_path / "reports" / "daily" / trade_date.isoformat(),
        tmp_path / "local_archive" / "reports" / trade_date.isoformat(),
    ]
    previous_day_paths = [
        tmp_path / "reports" / "daily" / previous_date.isoformat(),
        tmp_path / "local_archive" / "reports" / previous_date.isoformat(),
    ]
    for path in same_day_paths + previous_day_paths:
        path.mkdir(parents=True)
        (path / "index.html").write_text("report", encoding="utf-8")

    same_day_manifest = (
        tmp_path / "local_archive" / "manifests" / f"{trade_date.isoformat()}.json"
    )
    previous_day_manifest = (
        tmp_path / "local_archive" / "manifests" / f"{previous_date.isoformat()}.json"
    )
    same_day_manifest.parent.mkdir(parents=True)
    same_day_manifest.write_text("{}", encoding="utf-8")
    previous_day_manifest.write_text("{}", encoding="utf-8")

    summary = cleanup_trade_date(tmp_path, repository, trade_date)

    assert repository.calls == [trade_date]
    assert not same_day_paths[0].exists()
    assert not same_day_paths[1].exists()
    assert not same_day_manifest.exists()
    assert previous_day_paths[0].exists()
    assert previous_day_paths[1].exists()
    assert previous_day_manifest.exists()
    assert summary.trade_date == trade_date
    assert summary.repository_deleted_counts == {"recommendation_daily": 2}
    assert summary.removed_paths == (
        f"reports/daily/{trade_date.isoformat()}",
        f"local_archive/manifests/{trade_date.isoformat()}.json",
        f"local_archive/reports/{trade_date.isoformat()}",
    )


@pytest.mark.parametrize("bad_trade_date", [None, "2026-07-09", datetime(2026, 7, 9)])
def test_cleanup_refuses_missing_or_malformed_trade_date(tmp_path, bad_trade_date):
    repository = RecordingCleanupRepository()

    with pytest.raises(ValueError, match="trade_date must be a date"):
        cleanup_trade_date(tmp_path, repository, bad_trade_date)

    assert repository.calls == []


def test_cleanup_failure_raises_before_local_cleanup(tmp_path):
    trade_date = date(2026, 7, 9)
    repository = FailingCleanupRepository()
    same_day_report = tmp_path / "reports" / "daily" / trade_date.isoformat()
    same_day_report.mkdir(parents=True)

    with pytest.raises(RuntimeError, match="database cleanup failed"):
        cleanup_trade_date(tmp_path, repository, trade_date)

    assert repository.calls == [trade_date]
    assert same_day_report.exists()


def test_in_memory_repository_cleanup_deletes_only_allowed_target_date_rows():
    trade_date = date(2026, 7, 9)
    previous_date = date(2026, 7, 8)
    repo = InMemoryAnalysisRepository(
        recommendations=[
            _recommendation(trade_date, "600000.SH"),
            _recommendation(previous_date, "600000.SH"),
        ],
        focus_states=[
            _focus_state(trade_date, "600000.SH"),
            _focus_state(previous_date, "600000.SH"),
        ],
        evidence_packages=[
            _evidence_package(trade_date, "600000.SH"),
            _evidence_package(previous_date, "600000.SH"),
        ],
        evaluation_tasks=[
            _evaluation_task(trade_date, "600000.SH"),
            _evaluation_task(previous_date, "600000.SH"),
        ],
        market_bars=[
            _daily_bar(trade_date, "600000.SH"),
            _daily_bar(previous_date, "600000.SH"),
        ],
        daily_basic_indicators=[
            _daily_basic(trade_date, "600000.SH"),
            _daily_basic(previous_date, "600000.SH"),
        ],
        data_source_runs=[
            _source_run(trade_date),
            _source_run(previous_date),
        ],
        stock_master=[
            StockBasicRow(
                ts_code="600000.SH",
                name="浦发银行",
                exchange="SSE",
                list_date=date(1999, 11, 10),
            )
        ],
    )

    summary = repo.cleanup_trade_date(trade_date)

    assert set(summary) == set(APPROVED_SAME_DAY_CLEANUP_TABLES)
    assert all(count == 1 for count in summary.values())
    assert [item.trade_date for item in repo.recommendations] == [previous_date]
    assert [item.trade_date for item in repo.focus_states] == [previous_date]
    assert [item.trade_date for item in repo.evidence_packages] == [previous_date]
    assert [item.trade_date for item in repo.evaluation_tasks] == [previous_date]
    assert [item.trade_date for item in repo.market_bars] == [previous_date]
    assert [item.trade_date for item in repo.daily_basic_indicators] == [previous_date]
    assert [item.trade_date for item in repo.data_source_runs] == [previous_date]
    assert [item.ts_code for item in repo.stock_master] == ["600000.SH"]


def test_supabase_repository_cleanup_deletes_only_allowlisted_target_date_rows():
    trade_date = date(2026, 7, 9)
    client = FakeDeleteClient()
    repo = SupabaseAnalysisRepository(client)

    summary = repo.cleanup_trade_date(trade_date)

    assert summary == {table: 1 for table in APPROVED_SAME_DAY_CLEANUP_TABLES}
    assert [name for name, _, _ in client.delete_calls] == list(
        APPROVED_SAME_DAY_CLEANUP_TABLES
    )
    assert "stock_master" not in [name for name, _, _ in client.delete_calls]
    assert all(operation == "delete" for _, operation, _ in client.delete_calls)
    assert all(
        filters == (("trade_date", trade_date.isoformat()),)
        for _, _, filters in client.delete_calls
    )


def _recommendation(trade_date: date, ts_code: str) -> Recommendation:
    return Recommendation(
        trade_date=trade_date,
        ts_code=ts_code,
        name="浦发银行",
        action=ActionLabel.ENTER_OBSERVATION,
        score=80,
        reasons=["趋势改善"],
        risks=["需要确认"],
        evidence_id=f"{trade_date.isoformat()}-{ts_code}",
    )


def _focus_state(trade_date: date, ts_code: str) -> FocusState:
    return FocusState(
        trade_date=trade_date,
        ts_code=ts_code,
        state=ActionLabel.ENTER_OBSERVATION,
    )


def _evidence_package(trade_date: date, ts_code: str) -> EvidencePackage:
    return EvidencePackage(
        evidence_id=f"{trade_date.isoformat()}-{ts_code}",
        trade_date=trade_date,
        ts_code=ts_code,
        thesis="观察",
        support=["趋势改善"],
        counter_evidence=["需要确认"],
        matched_rules=[],
        confidence_level="medium",
        expected_confirmation_path=["趋势延续"],
        invalidation_conditions=[],
        source_versions={},
    )


def _evaluation_task(trade_date: date, ts_code: str) -> EvaluationTask:
    return EvaluationTask(
        trade_date=trade_date,
        ts_code=ts_code,
        evidence_id=f"{trade_date.isoformat()}-{ts_code}",
        checkpoint_days=5,
        due_date=date(2026, 7, 14),
        evaluation_layer="result",
    )


def _daily_bar(trade_date: date, ts_code: str) -> DailyBar:
    return DailyBar(
        trade_date=trade_date,
        ts_code=ts_code,
        close=10.2,
        source_name="tushare",
        source_grade=SourceGrade.PRIMARY,
    )


def _daily_basic(trade_date: date, ts_code: str) -> DailyBasicRow:
    return DailyBasicRow(
        trade_date=trade_date,
        ts_code=ts_code,
        turnover_rate=1.2,
        source_name="tushare",
        source_grade=SourceGrade.PRIMARY,
    )


def _source_run(trade_date: date) -> SourceRunRecord:
    return SourceRunRecord(
        trade_date=trade_date,
        source_name="tushare",
        stage="daily",
        status=SourceStatus.SUCCESS,
        message="ok",
        source_grade=SourceGrade.PRIMARY,
        data_status=DataStatus.COMPLETE_PRIMARY,
        record_count=1,
    )
