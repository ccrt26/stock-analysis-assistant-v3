from datetime import date, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import json

from typer.testing import CliRunner

from stock_analyzer.cli import _analysis_repository, app
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
from stock_analyzer.data.provider import CurrentLiveDataUnavailable
from stock_analyzer.domain.models import (
    ActionLabel,
    EvaluationTask,
    EvidencePackage,
    FocusState,
    Recommendation,
)
from stock_analyzer.data.readiness import FormalRunState
from stock_analyzer.ops.formal_run import RunReceipt
from stock_analyzer.storage.evidence_store import LocalEvidenceStore
from stock_analyzer.pipeline import _sample_market
from stock_analyzer.storage.capacity_guard import SupabaseCapacityGuard
from stock_analyzer.storage.repositories import SupabaseAnalysisRepository


class RecordingRepository:
    def __init__(self):
        self.load_calls = 0
        self.render_load_calls = []
        self.save_calls = []
        self.daily_recommendations = []
        self.daily_focus_states = []
        self.daily_evidence_packages = []
        self.daily_evaluation_tasks = []

    def load_focus_states(self):
        self.load_calls += 1
        return [
            FocusState(
                trade_date=date(2026, 7, 6),
                ts_code="688001.SH",
                state=ActionLabel.ENTER_OBSERVATION,
                entry_date=date(2026, 7, 6),
                entry_reason="原始证据成立",
            )
        ]

    def load_daily_recommendations(self, trade_date):
        self.render_load_calls.append(("recommendations", trade_date))
        return list(self.daily_recommendations)

    def load_focus_states_for_date(self, trade_date):
        self.render_load_calls.append(("focus_states", trade_date))
        return list(self.daily_focus_states)

    def load_evidence_packages(self, trade_date):
        self.render_load_calls.append(("evidence_packages", trade_date))
        return list(self.daily_evidence_packages)

    def load_evaluation_tasks(self, trade_date):
        self.render_load_calls.append(("evaluation_tasks", trade_date))
        return list(self.daily_evaluation_tasks)

    def save_stock_master(self, stocks):
        self.save_calls.append(("stock_master", stocks))

    def save_stock_statuses(self, stocks):
        self.save_calls.append(("stock_statuses", stocks))

    def save_feature_snapshots(self, features):
        self.save_calls.append(("feature_snapshots", features))

    def save_recommendations(self, recommendations):
        self.save_calls.append(("recommendations", recommendations))

    def save_focus_states(self, states):
        self.save_calls.append(("focus_states", states))

    def save_evidence_packages(self, packages):
        self.save_calls.append(("evidence_packages", packages))

    def save_evaluation_tasks(self, tasks):
        self.save_calls.append(("evaluation_tasks", tasks))

    def save_market_bars(self, bars):
        self.save_calls.append(("market_bars", bars))

    def save_daily_basic_indicators(self, rows):
        self.save_calls.append(("daily_basic_indicators", rows))

    def save_data_source_runs(self, rows):
        self.save_calls.append(("data_source_runs", rows))


def _raw_daily_bars(trade_date):
    return [
        DailyBar(
            trade_date=trade_date,
            ts_code="600000.SH",
            close=10.0,
            amount=200000000.0,
            source_name="fake-live",
            source_grade=SourceGrade.PRIMARY,
        )
    ]


def _raw_daily_basic(trade_date):
    return [
        DailyBasicRow(
            trade_date=trade_date,
            ts_code="600000.SH",
            turnover_rate=1.2,
            total_mv=1000000.0,
            source_name="fake-live",
            source_grade=SourceGrade.PRIMARY,
        )
    ]


def _raw_source_runs(trade_date, count):
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


class FakeProductionProvider:
    def load(self, trade_date):
        stocks, stock_names, feature_profiles = _sample_market(trade_date)
        daily_bars = _raw_daily_bars(trade_date)
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
                )
            ],
            daily_bars=daily_bars,
            daily_basic=_raw_daily_basic(trade_date),
            stocks=stocks,
            stock_names=stock_names,
            feature_profiles=feature_profiles,
            source_runs=_raw_source_runs(trade_date, len(daily_bars)),
        )


def _write_committed_receipt(root, trade_date):
    store = LocalEvidenceStore(root / "formal_evidence")
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


def test_health_check_command_prints_status(monkeypatch, tmp_path):
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    monkeypatch.setenv("TUSHARE_TOKEN_PATH", str(tmp_path / "missing-token"))

    result = CliRunner().invoke(app, ["health-check"])
    assert result.exit_code == 0
    assert "credential" in result.stdout
    assert "tushare_token: missing" in result.stdout
    assert "network" in result.stdout
    assert "api_response" in result.stdout
    assert "field_consumability" in result.stdout


def test_health_check_default_does_not_run_live_tushare_smoke(monkeypatch):
    monkeypatch.setenv("TUSHARE_TOKEN", "fake-live-token")

    def fail_if_called(token):
        raise AssertionError("default health-check must not run live Tushare smoke")

    monkeypatch.setattr(
        "stock_analyzer.cli._build_tushare_source",
        fail_if_called,
        raising=False,
    )

    result = CliRunner().invoke(app, ["health-check"])

    assert result.exit_code == 0
    assert "live_tushare_smoke" not in result.stdout
    assert "fake-live-token" not in result.output


def test_health_check_live_tushare_smoke_requires_token(monkeypatch, tmp_path):
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    monkeypatch.setenv("TUSHARE_TOKEN_PATH", str(tmp_path / "missing-token"))

    result = CliRunner().invoke(
        app,
        [
            "health-check",
            "--live-tushare-smoke",
            "--live-tushare-trade-date",
            "2026-07-08",
        ],
    )

    assert result.exit_code != 0
    assert "Tushare token missing" in result.output


def test_health_check_live_tushare_smoke_uses_fake_source_without_leaking_token(
    monkeypatch,
):
    monkeypatch.setenv("TUSHARE_TOKEN", "fake-live-token")
    smoke_calls = []

    class FakeTushareSmokeSource:
        def __init__(self, token):
            self.token = token

        def fetch_daily(self, trade_date):
            smoke_calls.append((self.token, trade_date))
            return [object(), object()]

    monkeypatch.setattr(
        "stock_analyzer.cli._build_tushare_source",
        lambda token: FakeTushareSmokeSource(token),
        raising=False,
    )

    result = CliRunner().invoke(
        app,
        [
            "health-check",
            "--live-tushare-smoke",
            "--live-tushare-trade-date",
            "2026-07-08",
        ],
    )

    assert result.exit_code == 0
    assert "live_tushare_smoke: rows=2" in result.stdout
    assert "fake-live-token" not in result.output
    assert smoke_calls == [("fake-live-token", date(2026, 7, 8))]


def test_health_check_live_tushare_smoke_masks_token_in_source_errors(monkeypatch):
    monkeypatch.setenv("TUSHARE_TOKEN", "fake-error-token")

    class FailingTushareSmokeSource:
        def fetch_daily(self, trade_date):
            raise RuntimeError(f"Tushare rejected token fake-error-token on {trade_date}")

    monkeypatch.setattr(
        "stock_analyzer.cli._build_tushare_source",
        lambda token: FailingTushareSmokeSource(),
        raising=False,
    )

    result = CliRunner().invoke(
        app,
        [
            "health-check",
            "--live-tushare-smoke",
            "--live-tushare-trade-date",
            "2026-07-08",
        ],
    )

    assert result.exit_code != 0
    assert "live Tushare smoke failed" in result.output
    assert "[masked]" in result.output
    assert "fake-error-token" not in result.output


def test_live_capability_cli_requires_explicit_confirmation(monkeypatch):
    calls = []

    def forbidden_loader(config):
        calls.append(config)
        raise AssertionError("provider runtime must not load without confirmation")

    monkeypatch.setattr(
        "stock_analyzer.cli.load_default_external_runtime",
        forbidden_loader,
    )

    result = CliRunner().invoke(
        app,
        [
            "ops",
            "verify-formal-capabilities",
            "--trade-date",
            "2026-07-10",
        ],
    )

    assert result.exit_code == 2
    assert "--confirm-live-read is required" in result.output
    assert calls == []


def test_run_daily_dry_run_completes():
    result = CliRunner().invoke(
        app, ["run-daily", "--dry-run", "--trade-date", "2026-07-07"]
    )
    assert result.exit_code == 0
    assert "daily run dry-run completed for 2026-07-07" in result.stdout


def test_run_daily_dry_run_does_not_persist_analysis_state(monkeypatch):
    repo = RecordingRepository()
    monkeypatch.setattr(
        "stock_analyzer.cli._analysis_repository",
        lambda config, **kwargs: repo,
    )

    result = CliRunner().invoke(
        app, ["run-daily", "--dry-run", "--trade-date", "2026-07-07"]
    )

    assert result.exit_code == 0
    assert repo.load_calls == 1
    assert repo.save_calls == []


def test_run_daily_requires_supabase_config_without_fixture_mode(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.delenv("STOCK_ANALYZER_FIXTURE_MODE", raising=False)

    result = CliRunner().invoke(
        app,
        ["run-daily", "--trade-date", "2026-07-07"],
    )

    assert result.exit_code != 0
    assert "SUPABASE_URL" in result.output
    assert "SUPABASE_SERVICE_ROLE_KEY" in result.output
    assert "--fixture-mode" in result.output


def test_analysis_repository_wires_supabase_capacity_guard_from_config(monkeypatch):
    fake_client = object()
    created_with = []

    def fake_create_supabase_client(config):
        created_with.append(config)
        return fake_client

    monkeypatch.setattr(
        "stock_analyzer.cli.create_supabase_client",
        fake_create_supabase_client,
    )
    config = AppConfig(
        supabase_url="https://supabase.example.test",
        supabase_service_role_key="fake-service-role-key",
        supabase_warn_mb=123.5,
        supabase_stop_mb=456.5,
    )

    repo = _analysis_repository(config)

    assert isinstance(repo, SupabaseAnalysisRepository)
    assert created_with == [config]
    assert repo.client is fake_client
    assert isinstance(repo.capacity_guard, SupabaseCapacityGuard)
    assert repo.capacity_guard.client is fake_client
    assert repo.capacity_guard.warn_mb == 123.5
    assert repo.capacity_guard.stop_mb == 456.5


def test_run_daily_with_supabase_config_fails_when_formal_dependencies_are_unavailable(monkeypatch):
    repo = RecordingRepository()
    monkeypatch.setenv("SUPABASE_URL", "https://supabase.example.test")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "fake-service-role-key")
    monkeypatch.delenv("STOCK_ANALYZER_FIXTURE_MODE", raising=False)
    monkeypatch.setattr(
        "stock_analyzer.cli._analysis_repository",
        lambda config, **kwargs: repo,
    )
    monkeypatch.setattr(
        "stock_analyzer.cli._default_run_daily",
        lambda *_args: (_ for _ in ()).throw(
            RuntimeError("formal capability evidence unavailable")
        ),
    )

    result = CliRunner().invoke(
        app,
        ["run-daily", "--trade-date", "2026-07-07"],
    )

    assert result.exit_code != 0
    assert "formal capability evidence unavailable" in result.output
    assert repo.save_calls == []


def test_run_daily_with_supabase_config_calls_formal_entry(tmp_path, monkeypatch):
    repo = RecordingRepository()
    captured = []

    monkeypatch.setenv("SUPABASE_URL", "https://supabase.example.test")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "fake-service-role-key")
    monkeypatch.delenv("STOCK_ANALYZER_FIXTURE_MODE", raising=False)
    monkeypatch.setattr(
        "stock_analyzer.cli._analysis_repository",
        lambda config, **kwargs: repo,
    )
    monkeypatch.setattr(
        "stock_analyzer.cli._default_run_daily",
        lambda project_root, repository, trade_date: captured.append(
            (project_root, repository, trade_date)
        )
        or SimpleNamespace(
            receipt=SimpleNamespace(state=FormalRunState.REPORT_GENERATED)
        ),
    )

    result = CliRunner().invoke(
        app,
        ["run-daily", "--trade-date", "2026-07-07"],
    )

    assert result.exit_code == 0
    assert "daily formal run completed for 2026-07-07" in result.stdout
    assert captured[0][1] is repo
    assert captured[0][2] == date(2026, 7, 7)
    assert repo.save_calls == []


def test_run_daily_allow_data_insufficient_cannot_bypass_formal_block(
    tmp_path,
    monkeypatch,
):
    repo = RecordingRepository()

    monkeypatch.setenv("SUPABASE_URL", "https://supabase.example.test")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "fake-service-role-key")
    monkeypatch.delenv("STOCK_ANALYZER_FIXTURE_MODE", raising=False)
    monkeypatch.setattr(
        "stock_analyzer.cli._analysis_repository",
        lambda config, **kwargs: repo,
    )
    monkeypatch.setattr(
        "stock_analyzer.cli._default_run_daily",
        lambda *_args: SimpleNamespace(
            receipt=SimpleNamespace(state=FormalRunState.BLOCKED_NEEDS_HUMAN)
        ),
    )

    result = CliRunner().invoke(
        app,
        [
            "run-daily",
            "--allow-data-insufficient-output",
            "--trade-date",
            "2026-07-07",
        ],
    )

    assert result.exit_code != 0
    assert "blocked_needs_human" in result.output
    assert not (tmp_path / "index.html").exists()


def test_run_daily_forwards_strategy_v2_and_data_insufficient_flags(monkeypatch):
    captured = {}

    def fake_run_daily_pipeline(trade_date, output_dir, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            trade_date=trade_date,
            recommendations=[],
            evaluation_tasks=[],
        )

    monkeypatch.setattr("stock_analyzer.cli.run_daily_pipeline", fake_run_daily_pipeline)

    result = CliRunner().invoke(
        app,
        [
            "run-daily",
            "--dry-run",
            "--strategy-v2",
            "--allow-data-insufficient-output",
            "--trade-date",
            "2026-07-07",
        ],
    )

    assert result.exit_code == 0
    assert captured["strategy_v2"] is True
    assert captured["allow_data_insufficient_output"] is True


def test_run_daily_fixture_mode_writes_local_sample_report(tmp_path, monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path))

    result = CliRunner().invoke(
        app,
        ["run-daily", "--fixture-mode", "--trade-date", "2026-07-07"],
    )

    assert result.exit_code == 0
    assert "fixture" in result.output
    assert (tmp_path / "index.html").exists()
    latest_payload = json.loads(
        (tmp_path / "data" / "latest.json").read_text(encoding="utf-8")
    )
    root_html = (tmp_path / "index.html").read_text(encoding="utf-8")
    daily_html = (tmp_path / "daily" / "2026-07-07" / "index.html").read_text(
        encoding="utf-8"
    )
    first_stock = latest_payload["recommendations"][0]["ts_code"]
    stock_html = (
        tmp_path / "daily" / "2026-07-07" / "stocks" / f"{first_stock}.html"
    ).read_text(encoding="utf-8")
    assert latest_payload["report_mode"] == "fixture"
    assert latest_payload["is_fixture"] is True
    assert "fixture" in latest_payload["warning"].lower()
    for html in (root_html, daily_html, stock_html):
        assert "Fixture/sample report" in html
        assert "not production data" in html


def test_run_daily_fixture_mode_env_writes_labeled_sample_report(tmp_path, monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.setenv("STOCK_ANALYZER_FIXTURE_MODE", "1")
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path))

    result = CliRunner().invoke(
        app,
        ["run-daily", "--trade-date", "2026-07-07"],
    )

    assert result.exit_code == 0
    latest_payload = json.loads(
        (tmp_path / "data" / "latest.json").read_text(encoding="utf-8")
    )
    assert latest_payload["report_mode"] == "fixture"
    assert latest_payload["is_fixture"] is True


def test_render_report_command_writes_requested_output_dir_in_fixture_mode(tmp_path):
    result = CliRunner().invoke(
        app,
        [
            "render-report",
            "--fixture-mode",
            "--trade-date",
            "2026-07-07",
            "--output-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0
    assert "report rendered for 2026-07-07" in result.stdout
    assert (tmp_path / "index.html").exists()
    assert (tmp_path / "daily" / "2026-07-07" / "index.html").exists()


def test_render_report_command_uses_stored_repository_data_when_available(tmp_path, monkeypatch):
    repo = RecordingRepository()
    warehouse_root = tmp_path / "warehouse"
    monkeypatch.setenv("LOCAL_WAREHOUSE_DIR", str(warehouse_root))
    _write_committed_receipt(warehouse_root, date(2026, 7, 7))
    repo.daily_recommendations = [
        Recommendation(
            trade_date=date(2026, 7, 7),
            ts_code="688999.SH",
            name="存量样本",
            action=ActionLabel.CONTINUE_OBSERVATION,
            score=88,
            reasons=["存储证据支持"],
            risks=["存储反证"],
            evidence_id="stored-evidence-688999",
        )
    ]
    repo.daily_evidence_packages = [
        EvidencePackage(
            evidence_id="stored-evidence-688999",
            trade_date=date(2026, 7, 7),
            ts_code="688999.SH",
            thesis="存量样本继续观察",
            support=["存储证据支持"],
            counter_evidence=["存储反证"],
            matched_rules=["RESEARCH_TREND_CONFIRMATION"],
            confidence_level="high",
            expected_confirmation_path=["存储确认信号"],
            invalidation_conditions=["存储失效信号"],
            source_versions={"repository": "stored"},
        )
    ]
    repo.daily_evaluation_tasks = [
        EvaluationTask(
            trade_date=date(2026, 7, 7),
            ts_code="688999.SH",
            evidence_id="stored-evidence-688999",
            checkpoint_days=5,
            due_date=date(2026, 7, 14),
            evaluation_layer="result",
        )
    ]
    monkeypatch.setattr(
        "stock_analyzer.cli._analysis_repository",
        lambda config, **kwargs: repo,
    )

    result = CliRunner().invoke(
        app,
        [
            "render-report",
            "--trade-date",
            "2026-07-07",
            "--output-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0
    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    json_text = (tmp_path / "data" / "latest.json").read_text(encoding="utf-8")
    assert "存量样本" in html
    assert "stored-evidence-688999" in json_text
    assert "浦发银行" not in html
    assert repo.load_calls == 0
    assert repo.save_calls == []


def test_render_report_command_fails_when_stored_evidence_is_incomplete(tmp_path, monkeypatch):
    repo = RecordingRepository()
    warehouse_root = tmp_path / "warehouse"
    monkeypatch.setenv("LOCAL_WAREHOUSE_DIR", str(warehouse_root))
    _write_committed_receipt(warehouse_root, date(2026, 7, 7))
    repo.daily_recommendations = [
        Recommendation(
            trade_date=date(2026, 7, 7),
            ts_code="688999.SH",
            name="存量样本",
            action=ActionLabel.CONTINUE_OBSERVATION,
            score=88,
            reasons=["存储证据支持"],
            risks=["存储反证"],
            evidence_id="missing-evidence-688999",
        )
    ]
    monkeypatch.setattr(
        "stock_analyzer.cli._analysis_repository",
        lambda config, **kwargs: repo,
    )

    result = CliRunner().invoke(
        app,
        [
            "render-report",
            "--trade-date",
            "2026-07-07",
            "--output-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code != 0
    assert "Missing evidence package" in result.output
    assert "missing-evidence-688999" in result.output
    assert repo.save_calls == []
    assert not (tmp_path / "index.html").exists()


def test_render_report_command_fails_without_stored_data_in_production(tmp_path, monkeypatch):
    repo = RecordingRepository()
    warehouse_root = tmp_path / "warehouse"
    monkeypatch.setenv("LOCAL_WAREHOUSE_DIR", str(warehouse_root))
    _write_committed_receipt(warehouse_root, date(2026, 7, 7))
    monkeypatch.setattr(
        "stock_analyzer.cli._analysis_repository",
        lambda config, **kwargs: repo,
    )

    result = CliRunner().invoke(
        app,
        [
            "render-report",
            "--trade-date",
            "2026-07-07",
            "--output-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code != 0
    assert "No stored analysis rows found for 2026-07-07" in result.output
    assert repo.save_calls == []
    assert not (tmp_path / "index.html").exists()


def test_render_report_requires_supabase_config_without_fixture_mode(tmp_path, monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.delenv("STOCK_ANALYZER_FIXTURE_MODE", raising=False)

    result = CliRunner().invoke(
        app,
        [
            "render-report",
            "--trade-date",
            "2026-07-07",
            "--output-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code != 0
    assert "SUPABASE_URL" in result.output
    assert "SUPABASE_SERVICE_ROLE_KEY" in result.output
    assert "--fixture-mode" in result.output
