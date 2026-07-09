from __future__ import annotations

import json
from datetime import date, timedelta

from stock_analyzer.data.models import DailyBar, DailyBasicRow, SourceGrade
from stock_analyzer.domain.models import (
    ActionLabel,
    EvaluationTask,
    EvidencePackage,
    Recommendation,
)
from stock_analyzer.ops.status import RunStatus
from stock_analyzer.ops.verify import verify_production_result
from stock_analyzer.storage.capacity_guard import (
    MAX_SELECTED_WINDOW_CODES,
    MAX_SELECTED_WINDOW_ROWS,
)


def test_verify_accepts_zero_recommendations_as_success_no_recommendations(tmp_path):
    trade_date = date(2026, 7, 9)
    repository = FakeVerificationRepository()
    _write_production_report(tmp_path, trade_date)

    verification = verify_production_result(tmp_path, repository, trade_date)

    assert verification.passed is True
    assert verification.status == RunStatus.SUCCESS_NO_RECOMMENDATIONS
    assert verification.recommendations == 0
    assert verification.evidence_packages == 0
    assert verification.evaluation_tasks == 0
    assert verification.failures == ()


def test_verify_accepts_recommendations_when_counts_and_artifacts_match(tmp_path):
    trade_date = date(2026, 7, 9)
    recommendations = [
        _recommendation(trade_date, "600000.SH"),
        _recommendation(trade_date, "600519.SH"),
    ]
    repository = FakeVerificationRepository(
        recommendations=recommendations,
        evidence_packages=[
            _evidence_package(trade_date, "600000.SH"),
            _evidence_package(trade_date, "600519.SH"),
        ],
        evaluation_tasks=[
            task
            for recommendation in recommendations
            for task in _evaluation_tasks(recommendation)
        ],
        market_bars=[_daily_bar(trade_date, "600000.SH")],
        daily_basic_indicators=[_daily_basic(trade_date, "600000.SH")],
    )
    _write_production_report(tmp_path, trade_date)

    verification = verify_production_result(tmp_path, repository, trade_date)

    assert verification.passed is True
    assert verification.status == RunStatus.SUCCESS_WITH_RECOMMENDATIONS
    assert verification.recommendations == 2
    assert verification.evidence_packages == 2
    assert verification.evaluation_tasks == 12
    assert verification.market_price_daily_current_day_rows == 1
    assert verification.daily_basic_indicator_current_day_rows == 1


def test_verify_fails_when_recommendations_exceed_daily_limit(tmp_path):
    trade_date = date(2026, 7, 9)
    recommendations = [
        _recommendation(trade_date, f"600{i:03d}.SH")
        for i in range(11)
    ]
    repository = FakeVerificationRepository(
        recommendations=recommendations,
        evidence_packages=[
            _evidence_package(trade_date, recommendation.ts_code)
            for recommendation in recommendations
        ],
        evaluation_tasks=[
            task
            for recommendation in recommendations
            for task in _evaluation_tasks(recommendation)
        ],
    )
    _write_production_report(tmp_path, trade_date)

    verification = verify_production_result(tmp_path, repository, trade_date)

    assert verification.passed is False
    assert verification.status == RunStatus.FAILED_NEEDS_HUMAN
    assert _failure(verification, "recommendation_count_out_of_range").fix_suggestion


def test_verify_fails_when_evidence_count_does_not_match_recommendations(tmp_path):
    trade_date = date(2026, 7, 9)
    recommendation = _recommendation(trade_date, "600000.SH")
    repository = FakeVerificationRepository(
        recommendations=[recommendation],
        evidence_packages=[],
        evaluation_tasks=_evaluation_tasks(recommendation),
    )
    _write_production_report(tmp_path, trade_date)

    verification = verify_production_result(tmp_path, repository, trade_date)

    assert verification.passed is False
    assert _failure(verification, "evidence_count_mismatch").fix_suggestion


def test_verify_fails_when_evaluation_task_count_is_not_six_per_recommendation(
    tmp_path,
):
    trade_date = date(2026, 7, 9)
    recommendation = _recommendation(trade_date, "600000.SH")
    repository = FakeVerificationRepository(
        recommendations=[recommendation],
        evidence_packages=[_evidence_package(trade_date, "600000.SH")],
        evaluation_tasks=_evaluation_tasks(recommendation)[:-1],
    )
    _write_production_report(tmp_path, trade_date)

    verification = verify_production_result(tmp_path, repository, trade_date)

    assert verification.passed is False
    assert _failure(verification, "evaluation_task_count_mismatch").fix_suggestion


def test_verify_fails_when_selected_market_rows_reach_full_market_scale(tmp_path):
    trade_date = date(2026, 7, 9)
    repository = FakeVerificationRepository(
        market_bars=[
            _daily_bar(trade_date, f"600{i % 40:03d}.SH")
            for i in range(MAX_SELECTED_WINDOW_ROWS + 1)
        ],
    )
    _write_production_report(tmp_path, trade_date)

    verification = verify_production_result(tmp_path, repository, trade_date)

    assert verification.passed is False
    assert _failure(verification, "selected_market_rows_too_large").fix_suggestion


def test_verify_fails_when_supabase_selected_market_codes_exceed_limit(tmp_path):
    trade_date = date(2026, 7, 9)
    client = FakeVerificationSupabaseClient(
        {
            "market_price_daily": [
                {
                    "trade_date": trade_date.isoformat(),
                    "ts_code": f"600{i:03d}.SH",
                }
                for i in range(MAX_SELECTED_WINDOW_CODES + 1)
            ],
            "daily_basic_indicator": [],
        }
    )
    repository = FakeSupabaseVerificationRepository(client)
    _write_production_report(tmp_path, trade_date)

    verification = verify_production_result(tmp_path, repository, trade_date)

    assert verification.passed is False
    assert _failure(verification, "selected_market_codes_too_large").fix_suggestion


def test_verify_fails_when_report_date_differs_from_trade_date(tmp_path):
    trade_date = date(2026, 7, 9)
    _write_production_report(tmp_path, date(2026, 7, 8))

    verification = verify_production_result(
        tmp_path,
        FakeVerificationRepository(),
        trade_date,
    )

    assert verification.passed is False
    assert _failure(verification, "report_date_mismatch").fix_suggestion


def test_verify_fails_when_fixture_or_sample_strings_leak_into_reports(tmp_path):
    trade_date = date(2026, 7, 9)
    _write_production_report(
        tmp_path,
        trade_date,
        index_html="<html>Fixture/sample report: generated from local sample data</html>",
    )

    verification = verify_production_result(
        tmp_path,
        FakeVerificationRepository(),
        trade_date,
    )

    assert verification.passed is False
    assert _failure(verification, "fixture_sample_leak").fix_suggestion


def test_verify_fails_when_fixture_or_sample_strings_leak_into_report_json(tmp_path):
    trade_date = date(2026, 7, 9)
    _write_production_report(
        tmp_path,
        trade_date,
        report_json_payload={
            "trade_date": trade_date.isoformat(),
            "report_mode": "production",
            "is_fixture": False,
            "sections": [
                {
                    "title": "Signals",
                    "note": "generated from local sample data",
                }
            ],
            "recommendations": [],
        },
    )

    verification = verify_production_result(
        tmp_path,
        FakeVerificationRepository(),
        trade_date,
    )

    assert verification.passed is False
    assert _failure(verification, "fixture_sample_leak").fix_suggestion


def test_verify_ignores_false_fixture_flags_in_report_json(tmp_path):
    trade_date = date(2026, 7, 9)
    _write_production_report(
        tmp_path,
        trade_date,
        report_json_payload={
            "trade_date": trade_date.isoformat(),
            "report_mode": "production",
            "is_fixture": False,
            "quality_flags": {
                "fixture": False,
                "sample": False,
            },
            "recommendations": [],
        },
    )

    verification = verify_production_result(
        tmp_path,
        FakeVerificationRepository(),
        trade_date,
    )

    assert verification.passed is True


def test_verify_fails_when_report_index_is_missing(tmp_path):
    trade_date = date(2026, 7, 9)
    _write_production_report(tmp_path, trade_date, include_root_index=False)

    verification = verify_production_result(
        tmp_path,
        FakeVerificationRepository(),
        trade_date,
    )

    assert verification.passed is False
    assert _failure(verification, "report_index_missing").fix_suggestion


class FakeVerificationRepository:
    def __init__(
        self,
        recommendations=None,
        evidence_packages=None,
        evaluation_tasks=None,
        market_bars=None,
        daily_basic_indicators=None,
    ) -> None:
        self.recommendations = list(recommendations or [])
        self.evidence_packages = list(evidence_packages or [])
        self.evaluation_tasks = list(evaluation_tasks or [])
        self.market_bars = list(market_bars or [])
        self.daily_basic_indicators = list(daily_basic_indicators or [])

    def load_daily_recommendations(self, trade_date):
        return [item for item in self.recommendations if item.trade_date == trade_date]

    def load_evidence_packages(self, trade_date):
        return [item for item in self.evidence_packages if item.trade_date == trade_date]

    def load_evaluation_tasks(self, trade_date):
        return [item for item in self.evaluation_tasks if item.trade_date == trade_date]


class FakeSupabaseVerificationRepository:
    def __init__(self, client) -> None:
        self.client = client

    def load_daily_recommendations(self, trade_date):
        return []

    def load_evidence_packages(self, trade_date):
        return []

    def load_evaluation_tasks(self, trade_date):
        return []


class FakeVerificationSupabaseResult:
    def __init__(self, data) -> None:
        self.data = data
        self.count = len(data)


class FakeVerificationSupabaseTable:
    def __init__(self, name: str, client: "FakeVerificationSupabaseClient") -> None:
        self.name = name
        self.client = client
        self.filters = []

    def select(self, columns: str, **options):
        return self

    def eq(self, column: str, value):
        self.filters.append((column, value))
        return self

    def execute(self):
        rows = list(self.client.table_data.get(self.name, []))
        for column, value in self.filters:
            rows = [row for row in rows if row.get(column) == value]
        return FakeVerificationSupabaseResult(rows)


class FakeVerificationSupabaseClient:
    def __init__(self, table_data) -> None:
        self.table_data = table_data

    def table(self, name: str) -> FakeVerificationSupabaseTable:
        return FakeVerificationSupabaseTable(name, self)


def _write_production_report(
    project_root,
    trade_date: date,
    *,
    index_html: str | None = None,
    include_root_index: bool = True,
    report_json_payload=None,
) -> None:
    reports = project_root / "reports"
    daily = reports / "daily" / trade_date.isoformat()
    data = reports / "data"
    daily.mkdir(parents=True)
    data.mkdir(parents=True)

    if include_root_index:
        (reports / "index.html").write_text(
            index_html or f"<html>生产报告 {trade_date.isoformat()}</html>",
            encoding="utf-8",
        )
    (daily / "index.html").write_text(
        f"<html>生产日报 {trade_date.isoformat()}</html>",
        encoding="utf-8",
    )
    payload = report_json_payload or {
        "trade_date": trade_date.isoformat(),
        "report_mode": "production",
        "is_fixture": False,
        "recommendations": [],
    }
    (data / "latest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
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
        invalidation_conditions=["趋势失效"],
        source_versions={"recommendation": f"{trade_date.isoformat()}-{ts_code}"},
    )


def _evaluation_tasks(recommendation: Recommendation) -> list[EvaluationTask]:
    return [
        EvaluationTask(
            trade_date=recommendation.trade_date,
            ts_code=recommendation.ts_code,
            evidence_id=recommendation.evidence_id or "",
            checkpoint_days=checkpoint_days,
            due_date=recommendation.trade_date + timedelta(days=checkpoint_days),
            evaluation_layer=layer,
        )
        for checkpoint_days, layer in [
            (5, "result"),
            (20, "result"),
            (40, "result"),
            (20, "method"),
            (40, "method"),
            (40, "knowledge"),
        ]
    ]


def _daily_bar(trade_date: date, ts_code: str) -> DailyBar:
    return DailyBar(
        trade_date=trade_date,
        ts_code=ts_code,
        close=10.0,
        source_name="tushare",
        source_grade=SourceGrade.PRIMARY,
    )


def _daily_basic(trade_date: date, ts_code: str) -> DailyBasicRow:
    return DailyBasicRow(
        trade_date=trade_date,
        ts_code=ts_code,
        turnover_rate=1.5,
        source_name="tushare",
        source_grade=SourceGrade.PRIMARY,
    )


def _failure(verification, code):
    return next(failure for failure in verification.failures if failure.code == code)
