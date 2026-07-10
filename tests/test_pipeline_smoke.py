import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from stock_analyzer.analysis.focus import FormalFocusDay
from stock_analyzer.data.readiness import FormalRunState
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
from stock_analyzer.data.provider import CurrentLiveDataUnavailable, TushareProvider
from stock_analyzer.domain.models import (
    ActionLabel,
    EvaluationTask,
    EvidencePackage,
    FocusState,
    Recommendation,
)
from stock_analyzer.pipeline import (
    ProductionDataSourceUnavailable,
    StoredAnalysisNotFound,
    _sample_market,
    render_report_for_date,
    run_daily_pipeline,
)
from stock_analyzer.ops.formal_run import RunReceipt
from stock_analyzer.storage.evidence_store import LocalEvidenceStore
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


def _committed_receipt_store(tmp_path, trade_date):
    store = LocalEvidenceStore(tmp_path / "formal-evidence")
    store.save_run_receipt(
        RunReceipt(
            run_id=f"committed-{trade_date.isoformat()}",
            target_date=trade_date,
            report_cutoff=datetime(
                trade_date.year,
                trade_date.month,
                trade_date.day,
                16,
                tzinfo=ZoneInfo("Asia/Shanghai"),
            ),
            acquisition_contract_version="formal-v1",
            screening_version="screen-v1",
            state=FormalRunState.REPORT_GENERATED,
            group_version_ids={"market_decision": "version-1"},
            input_set_id="input-1",
            candidate_set_id="candidate-1",
            evidence_hashes={"evidence": "hash"},
            artifact_hashes={"index.html": "hash"},
            local_activation_id="activation-1",
            ledger_activation_id="activation-1",
        )
    )
    return store


class PreflightRejectingRepository(InMemoryAnalysisRepository):
    def __init__(self):
        super().__init__()
        self.calls = []

    def preflight_market_window_writes(self, bars, daily_basic):
        self.calls.append(("preflight", len(bars), len(daily_basic)))
        raise RuntimeError("preflight stopped")

    def _reject_write(self, name):
        self.calls.append(name)
        raise AssertionError(f"{name} write reached after rejected preflight")

    def save_stock_master(self, stocks):
        self._reject_write("stock_master")

    def save_stock_statuses(self, stocks):
        self._reject_write("stock_statuses")

    def save_feature_snapshots(self, features):
        self._reject_write("feature_snapshots")

    def save_recommendations(self, recommendations):
        self._reject_write("recommendations")

    def save_focus_states(self, states):
        self._reject_write("focus_states")

    def save_evidence_packages(self, packages):
        self._reject_write("evidence_packages")

    def save_evaluation_tasks(self, tasks):
        self._reject_write("evaluation_tasks")

    def save_market_bars(self, bars):
        self._reject_write("market_bars")

    def save_daily_basic_indicators(self, rows):
        self._reject_write("daily_basic_indicators")

    def save_data_source_runs(self, rows):
        self._reject_write("data_source_runs")


class RecordingWarehouse:
    def __init__(self):
        self.saved_bundles = []

    def save_bundle(self, bundle):
        self.saved_bundles.append(bundle)


class RecordingArchive:
    def __init__(self):
        self.calls = []

    def archive_report_tree(self, reports_dir, trade_date):
        self.calls.append((reports_dir, trade_date))


def _raw_daily_bars(trade_date, ts_code="600000.SH", days=1, close_base=10.0):
    start = trade_date - timedelta(days=days - 1)
    return [
        DailyBar(
            trade_date=start + timedelta(days=offset),
            ts_code=ts_code,
            close=close_base + offset * 0.1,
            amount=200000000.0 + offset,
            source_name="fake-live",
            source_grade=SourceGrade.PRIMARY,
        )
        for offset in range(days)
    ]


def _raw_daily_basic(trade_date, ts_code="600000.SH"):
    return [
        DailyBasicRow(
            trade_date=trade_date,
            ts_code=ts_code,
            turnover_rate=1.2,
            total_mv=1000000.0,
            source_name="fake-live",
            source_grade=SourceGrade.PRIMARY,
        )
    ]


def _raw_source_runs(trade_date, count=1):
    return [
        SourceRunRecord(
            trade_date=trade_date,
            source_name="fake-live",
            stage="daily",
            status=SourceStatus.SUCCESS,
            message="ok",
            source_grade=SourceGrade.PRIMARY,
            data_status=DataStatus.COMPLETE_PRIMARY,
            record_count=count,
        )
    ]


def _raw_stock_basic(ts_code="600000.SH", name="浦发银行"):
    return [
        StockBasicRow(
            ts_code=ts_code,
            name=name,
            exchange="SSE",
            list_date=date(1999, 11, 10),
        )
    ]


class FakeProductionProvider:
    def load(self, trade_date):
        stocks, stock_names, feature_profiles = _sample_market(trade_date)
        daily_bars = _raw_daily_bars(trade_date)
        return MarketDataBundle(
            trade_date=trade_date,
            data_status=DataStatus.COMPLETE_PRIMARY,
            source_grade=SourceGrade.PRIMARY,
            source_versions={"fake-live": trade_date.isoformat()},
            stock_basic=_raw_stock_basic(),
            daily_bars=daily_bars,
            daily_basic=_raw_daily_basic(trade_date),
            stocks=stocks,
            stock_names=stock_names,
            feature_profiles=feature_profiles,
            source_runs=_raw_source_runs(trade_date, len(daily_bars)),
        )


class ProviderWithExtraRawCode:
    def load(self, trade_date):
        stocks, stock_names, feature_profiles = _sample_market(trade_date)
        stocks = stocks + [
            stocks[0].model_copy(
                update={
                    "ts_code": "000004.SZ",
                    "name": "国华网安",
                    "listing_days": 4_000,
                    "turnover_rate": 0.9,
                    "amount": 180_000_000,
                }
            )
        ]
        stock_names["000004.SZ"] = "国华网安"
        feature_profiles["000004.SZ"] = feature_profiles["600000.SH"].model_copy(
            update={
                "ts_code": "000004.SZ",
                "trend_20d": 0.0,
                "trend_60d": 0.0,
                "relative_strength": 0.1,
                "volatility_20d": 0.6,
                "liquidity_score": 0.1,
                "quality_score": 0.1,
            }
        )
        return MarketDataBundle(
            trade_date=trade_date,
            data_status=DataStatus.COMPLETE_PRIMARY,
            source_grade=SourceGrade.PRIMARY,
            source_versions={"fake-live": trade_date.isoformat()},
            stock_basic=_raw_stock_basic()
            + [StockBasicRow(ts_code="000004.SZ", name="国华网安", exchange="SZSE")],
            daily_bars=_raw_daily_bars(trade_date, "600000.SH")
            + _raw_daily_bars(trade_date, "600519.SH")
            + _raw_daily_bars(trade_date, "000004.SZ"),
            daily_basic=_raw_daily_basic(trade_date, "600000.SH")
            + _raw_daily_basic(trade_date, "600519.SH")
            + _raw_daily_basic(trade_date, "000004.SZ"),
            stocks=stocks,
            stock_names=stock_names,
            feature_profiles=feature_profiles,
            source_runs=_raw_source_runs(trade_date, 3),
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


class RaisingCurrentLiveDataProvider:
    def load(self, trade_date):
        raise CurrentLiveDataUnavailable(
            "Tushare returned no current trade date daily bars for "
            f"{trade_date.isoformat()}"
        )


class RawOnlyProductionProvider:
    def load(self, trade_date):
        daily_bars = _raw_daily_bars(trade_date)
        return MarketDataBundle(
            trade_date=trade_date,
            data_status=DataStatus.COMPLETE_PRIMARY,
            source_grade=SourceGrade.PRIMARY,
            source_versions={"fake-live": trade_date.isoformat()},
            stock_basic=_raw_stock_basic(),
            daily_bars=daily_bars,
            daily_basic=_raw_daily_basic(trade_date),
            source_runs=_raw_source_runs(trade_date, len(daily_bars)),
        )


class MissingDailyBasicProductionProvider:
    def load(self, trade_date):
        stocks, stock_names, feature_profiles = _sample_market(trade_date)
        degraded_features = {
            ts_code: feature.model_copy(update={"data_quality": "missing_daily_basic"})
            for ts_code, feature in feature_profiles.items()
        }
        daily_bars = _raw_daily_bars(trade_date)
        return MarketDataBundle(
            trade_date=trade_date,
            data_status=DataStatus.COMPLETE_PRIMARY,
            source_grade=SourceGrade.PRIMARY,
            source_versions={"fake-live": trade_date.isoformat()},
            stock_basic=_raw_stock_basic(),
            daily_bars=daily_bars,
            daily_basic=[],
            stocks=stocks,
            stock_names=stock_names,
            feature_profiles=degraded_features,
            source_runs=_raw_source_runs(trade_date, len(daily_bars)),
        )


class HardExcludedProductionProvider:
    def load(self, trade_date):
        stocks, stock_names, feature_profiles = _sample_market(trade_date)
        hard_excluded_stocks = [
            stock.model_copy(update={"is_st": True}) for stock in stocks
        ]
        daily_bars = _raw_daily_bars(trade_date)
        return MarketDataBundle(
            trade_date=trade_date,
            data_status=DataStatus.COMPLETE_PRIMARY,
            source_grade=SourceGrade.PRIMARY,
            source_versions={"fake-live": trade_date.isoformat()},
            stock_basic=_raw_stock_basic(),
            daily_bars=daily_bars,
            daily_basic=_raw_daily_basic(trade_date),
            stocks=hard_excluded_stocks,
            stock_names=stock_names,
            feature_profiles=feature_profiles,
            source_runs=_raw_source_runs(trade_date, len(daily_bars)),
        )


class FakeTushareSource:
    def __init__(self, trade_date, *, history_days=61, include_current=True):
        self.trade_date = trade_date
        self.fetch_daily_calls = []
        end_date = trade_date if include_current else trade_date - timedelta(days=1)
        self.available_dates = {
            end_date - timedelta(days=offset) for offset in range(history_days)
        }
        self.oldest_date = min(self.available_dates)

    def fetch_stock_basic(self):
        return _raw_stock_basic()

    def fetch_daily(self, trade_date):
        self.fetch_daily_calls.append(trade_date)
        if trade_date not in self.available_dates:
            return []
        close_base = 10.0 + (trade_date - self.oldest_date).days * 0.1
        return _raw_daily_bars(trade_date, close_base=close_base)

    def fetch_daily_basic(self, trade_date):
        return _raw_daily_basic(trade_date)


class StaleFakeTushareSource(FakeTushareSource):
    def __init__(self, trade_date):
        super().__init__(trade_date, include_current=False)


class SparseFakeTushareSource(FakeTushareSource):
    def __init__(self, trade_date):
        super().__init__(trade_date, history_days=1)


class MissingDailyBasicFakeTushareSource(FakeTushareSource):
    def fetch_daily_basic(self, trade_date):
        return []


class ExtraUnknownCodeFakeTushareSource(FakeTushareSource):
    def fetch_daily(self, trade_date):
        rows = super().fetch_daily(trade_date)
        if rows:
            rows.append(
                DailyBar(
                    trade_date=trade_date,
                    ts_code="000638.SZ",
                    close=12.3,
                    amount=100000000,
                    source_name="fake-live",
                    source_grade=SourceGrade.PRIMARY,
                )
            )
        return rows

    def fetch_daily_basic(self, trade_date):
        return super().fetch_daily_basic(trade_date) + [
            DailyBasicRow(
                trade_date=trade_date,
                ts_code="000638.SZ",
                turnover_rate=1.2,
                source_name="fake-live",
                source_grade=SourceGrade.PRIMARY,
            )
        ]


def test_tushare_provider_builds_decision_ready_bundle_from_fetched_rows():
    trade_date = date(2026, 7, 7)
    source = FakeTushareSource(trade_date)

    bundle = TushareProvider(source).load(trade_date)

    assert bundle.can_generate_decisions
    assert bundle.stocks
    assert bundle.stock_names["600000.SH"] == "浦发银行"
    assert bundle.feature_profiles["600000.SH"].trend_60d > 0
    assert len(bundle.daily_bars) >= 61
    assert bundle.daily_bars
    assert bundle.daily_basic
    assert bundle.source_runs
    assert trade_date in source.fetch_daily_calls
    assert len(source.fetch_daily_calls) > 1


def test_tushare_provider_filters_rows_outside_current_stock_basic():
    trade_date = date(2026, 7, 7)
    source = ExtraUnknownCodeFakeTushareSource(trade_date)

    bundle = TushareProvider(source).load(trade_date)

    assert "000638.SZ" not in {bar.ts_code for bar in bundle.daily_bars}
    assert "000638.SZ" not in {row.ts_code for row in bundle.daily_basic}
    assert "000638.SZ" not in bundle.stock_names


def test_tushare_provider_translates_insufficient_feature_coverage():
    trade_date = date(2026, 7, 7)

    with pytest.raises(CurrentLiveDataUnavailable) as excinfo:
        TushareProvider(StaleFakeTushareSource(trade_date)).load(trade_date)

    assert "current trade date" in str(excinfo.value)
    assert "token" not in str(excinfo.value).lower()


def test_tushare_provider_rejects_rows_without_feature_inputs():
    trade_date = date(2026, 7, 7)

    with pytest.raises(CurrentLiveDataUnavailable) as excinfo:
        TushareProvider(SparseFakeTushareSource(trade_date)).load(trade_date)

    assert "feature inputs" in str(excinfo.value)
    assert "token" not in str(excinfo.value).lower()


def test_tushare_provider_rejects_missing_current_daily_basic():
    trade_date = date(2026, 7, 7)

    with pytest.raises(CurrentLiveDataUnavailable) as excinfo:
        TushareProvider(MissingDailyBasicFakeTushareSource(trade_date)).load(trade_date)

    assert "daily basic" in str(excinfo.value).lower()
    assert "token" not in str(excinfo.value).lower()


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


def test_strategy_v2_fixture_pipeline_writes_v2_report_and_narrow_ledger_rows(
    tmp_path,
):
    repo = InMemoryAnalysisRepository()

    result = run_daily_pipeline(
        date(2026, 7, 7),
        tmp_path,
        dry_run=False,
        repository=repo,
        fixture_mode=True,
        strategy_v2=True,
        manual_entries=[("600000.SH", "人工跟踪")],
    )

    payload = json.loads(
        (tmp_path / "data" / "latest.json").read_text(encoding="utf-8")
    )
    html = (tmp_path / "index.html").read_text(encoding="utf-8")

    assert result.recommendations
    assert payload["recommendation_cards"]
    assert payload["strategy_snapshots"]
    assert "评分" not in html
    assert repo.strategy_snapshots
    assert repo.focus_entry_theses
    assert repo.focus_daily_updates
    assert repo.action_recommendation_summaries
    assert repo.operational_daily_statuses
    assert repo.recommendations
    assert repo.focus_states
    assert repo.evidence_packages
    assert repo.evaluation_tasks


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



def test_selected_decision_codes_include_recommendations_and_active_focus_only():
    from stock_analyzer.pipeline import _selected_decision_codes

    recommendation = Recommendation(
        trade_date=date(2026, 7, 7),
        ts_code="600000.SH",
        name="浦发银行",
        action=ActionLabel.ENTER_OBSERVATION,
        score=82,
        reasons=["趋势改善"],
        risks=["需要确认"],
    )
    active_focus = FocusState(
        trade_date=date(2026, 7, 7),
        ts_code="600519.SH",
        state=ActionLabel.CONTINUE_OBSERVATION,
    )
    exited_focus = FocusState(
        trade_date=date(2026, 7, 7),
        ts_code="000004.SZ",
        state=ActionLabel.EXIT_OBSERVATION,
    )
    insufficient_focus = FocusState(
        trade_date=date(2026, 7, 7),
        ts_code="000005.SZ",
        state=ActionLabel.INSUFFICIENT_DATA,
    )

    assert _selected_decision_codes(
        [recommendation],
        [active_focus, exited_focus, insufficient_focus],
    ) == {"600000.SH", "600519.SH"}



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
    receipt_store = _committed_receipt_store(tmp_path, date(2026, 7, 7))

    with pytest.raises(StoredAnalysisNotFound) as excinfo:
        render_report_for_date(
            date(2026, 7, 7),
            tmp_path,
            repository=repo,
            receipt_store=receipt_store,
            expected_input_set_id="input-1",
        )

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
    receipt_store = _committed_receipt_store(tmp_path, date(2026, 7, 7))

    with pytest.raises(StoredAnalysisNotFound) as excinfo:
        render_report_for_date(
            date(2026, 7, 7),
            tmp_path,
            repository=repo,
            receipt_store=receipt_store,
            expected_input_set_id="input-1",
        )

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
    receipt_store = _committed_receipt_store(tmp_path, date(2026, 7, 7))

    with pytest.raises(StoredAnalysisNotFound) as excinfo:
        render_report_for_date(
            date(2026, 7, 7),
            tmp_path,
            repository=repo,
            receipt_store=receipt_store,
            expected_input_set_id="input-1",
        )

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
    receipt_store = _committed_receipt_store(tmp_path, date(2026, 7, 7))

    result = render_report_for_date(
        date(2026, 7, 7),
        tmp_path,
        repository=repo,
        receipt_store=receipt_store,
        expected_input_set_id="input-1",
    )

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


def test_pipeline_loads_prior_formally_committed_focus_snapshots_before_update(
    tmp_path,
    monkeypatch,
):
    import stock_analyzer.pipeline as pipeline_module
    from tests.test_focus_strategy_v2 import _snapshot

    prior_date = date(2026, 7, 9)
    current_date = date(2026, 7, 10)
    prior = _snapshot(prior_date)
    repository = InMemoryAnalysisRepository(
        strategy_snapshots=[prior],
        formally_committed_run_dates={prior_date},
    )
    captured_dates = []
    original = pipeline_module.update_focus_watchlist_v2

    def capture_history(**kwargs):
        captured_dates.extend(
            snapshot.trade_date for snapshot in kwargs["recommendation_snapshots"]
        )
        return original(**kwargs)

    monkeypatch.setattr(pipeline_module, "update_focus_watchlist_v2", capture_history)

    run_daily_pipeline(
        current_date,
        tmp_path / "reports",
        dry_run=True,
        repository=repository,
        strategy_v2=True,
        eligible_focus_days=[
            FormalFocusDay(trade_date=prior_date, formally_committed=True)
        ],
    )

    assert prior_date in captured_dates
    assert current_date in captured_dates
