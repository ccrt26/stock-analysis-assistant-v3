from datetime import date
from contextlib import contextmanager
from types import SimpleNamespace

from typer.testing import CliRunner

from stock_analyzer.cli import _health_research_state, app
from stock_analyzer.data.research_backfill import BackfillSummary


runner = CliRunner()


def _health_report(
    *,
    complete_core_date: bool = True,
    market_ready: bool = True,
    sector_ready: bool = True,
    stock_ready: bool = True,
    price_ready: bool = True,
    next_morning_status: str = "succeeded",
    announcement_status: str | None = None,
):
    features = (
        SimpleNamespace(feature_set="market_context", ready=market_ready),
        SimpleNamespace(feature_set="sector_hotspot", ready=sector_ready),
        SimpleNamespace(feature_set="stock_trading_context", ready=stock_ready),
        SimpleNamespace(feature_set="price_analysis_context", ready=price_ready),
    )
    return SimpleNamespace(
        complete_core_date=complete_core_date,
        derived_features=features,
        latest_stage_runs=(
            SimpleNamespace(
                stage="next-morning",
                status=next_morning_status,
                capabilities={
                    "announcement_status": announcement_status
                    or (
                        "cninfo_complete"
                        if next_morning_status in {"succeeded", "limited"}
                        else "announcement_unavailable"
                    ),
                    "announcement_exchanges": ["SSE", "SZSE"],
                },
            ),
        ),
    )


def test_health_research_state_treats_complete_core_date_as_diagnostic_only():
    core_ready, limitations = _health_research_state(
        _health_report(complete_core_date=False)
    )

    assert core_ready is True
    assert limitations == ()


def test_root_cli_exposes_only_the_data_group():
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0, result.output
    assert "data" in result.output
    assert "ops" not in result.output
    for old_command in (
        "health-check",
        "run-daily",
        "render-report",
        "prepare-formal-report-candidate",
        "activate-formal-report-candidate",
    ):
        assert old_command not in result.output


def test_data_cli_exposes_only_current_warehouse_commands():
    result = runner.invoke(app, ["data", "--help"])

    assert result.exit_code == 0, result.output
    for current_command in (
        "backfill",
        "run-stage",
        "derive",
        "health",
    ):
        assert current_command in result.output
    for retired_command in (
        "inspect-legacy-market",
        "migrate-legacy-market",
        "audit-migration",
        "legacy-cleanup-manifest",
        "cleanup-legacy-market",
        "normalize-share-float",
        "audit-time-semantics",
        "migrate-time-semantics",
    ):
        assert retired_command not in result.output


def test_scheduled_stage_command_still_loads():
    result = runner.invoke(app, ["data", "run-stage", "--help"])

    assert result.exit_code == 0, result.output
    assert "--stage" in result.output
    assert "--data-date" in result.output


def test_health_command_still_loads():
    result = runner.invoke(app, ["data", "health", "--help"])

    assert result.exit_code == 0, result.output
    assert "--data-date" in result.output
    assert "--full-history" in result.output


def test_scheduled_stage_returns_nonzero_when_required_facts_are_incomplete(
    tmp_path, monkeypatch
):
    import stock_analyzer.ops.research_data_job as job
    import stock_analyzer.ops.research_health as health

    config = SimpleNamespace(local_archive_dir=tmp_path / "archive")
    runtime = SimpleNamespace(config=config, warehouse=object())
    monkeypatch.setattr(job, "build_research_data_runtime", lambda config: runtime)
    monkeypatch.setattr(
        job,
        "run_research_stage",
        lambda runtime, *, stage, data_date: (
            BackfillSummary(
                scope="market-core",
                start=date(2026, 8, 4),
                through=date(2026, 8, 4),
                waiting_upstream=1,
            ),
        ),
    )
    monkeypatch.setattr(
        "stock_analyzer.config.AppConfig.load", lambda: config
    )
    monkeypatch.setattr(
        health,
        "build_research_health_report",
        lambda warehouse, data_date, full_history: _health_report(
            complete_core_date=False,
            market_ready=False,
        ),
    )
    monkeypatch.setattr(
        health,
        "write_health_report",
        lambda report, output_dir: (output_dir / "health.json", None),
    )

    result = runner.invoke(
        app,
        [
            "data",
            "run-stage",
            "--stage",
            "close",
            "--data-date",
            "2026-08-04",
        ],
    )

    assert result.exit_code == 2, result.output
    assert "core_complete=false" in result.output


def test_close_stage_does_not_require_evening_derived_features(
    tmp_path, monkeypatch
):
    import stock_analyzer.ops.research_data_job as job
    import stock_analyzer.ops.research_health as health

    config = SimpleNamespace(local_archive_dir=tmp_path / "archive")
    runtime = SimpleNamespace(config=config, warehouse=object())
    monkeypatch.setattr(job, "build_research_data_runtime", lambda config: runtime)
    monkeypatch.setattr(
        job,
        "run_research_stage",
        lambda runtime, *, stage, data_date: (
            BackfillSummary(
                scope="market-core",
                start=date(2026, 8, 4),
                through=date(2026, 8, 4),
                committed=4,
            ),
        ),
    )
    monkeypatch.setattr("stock_analyzer.config.AppConfig.load", lambda: config)
    monkeypatch.setattr(
        health,
        "build_research_health_report",
        lambda warehouse, data_date, full_history: _health_report(
            market_ready=False, price_ready=False
        ),
    )
    monkeypatch.setattr(
        health,
        "write_health_report",
        lambda report, output_dir: (output_dir / "health.json", None),
    )

    result = runner.invoke(
        app,
        ["data", "run-stage", "--stage", "close", "--data-date", "2026-08-04"],
    )

    assert result.exit_code == 0, result.output


def test_scheduled_stage_acquires_global_lock_before_runtime_initialization(
    tmp_path, monkeypatch
):
    import stock_analyzer.ops.research_data_job as job
    import stock_analyzer.ops.research_health as health

    order = []
    config = SimpleNamespace(
        local_archive_dir=tmp_path / "archive",
        local_warehouse_dir=tmp_path / "warehouse",
    )
    runtime = SimpleNamespace(config=config, warehouse=object())

    @contextmanager
    def lock(root):
        order.append(("lock-enter", root))
        try:
            yield
        finally:
            order.append(("lock-exit", root))

    def build(config):
        assert order == [("lock-enter", config.local_warehouse_dir)]
        order.append(("runtime", config.local_warehouse_dir))
        return runtime

    def run(runtime, *, stage, data_date, already_locked):
        assert already_locked is True
        order.append(("stage", data_date))
        return (
            BackfillSummary(
                scope="market-core", start=data_date, through=data_date,
                committed=4,
            ),
        )

    monkeypatch.setattr(job, "research_job_lock", lock, raising=False)
    monkeypatch.setattr(job, "build_research_data_runtime", build)
    monkeypatch.setattr(job, "run_research_stage", run)
    monkeypatch.setattr("stock_analyzer.config.AppConfig.load", lambda: config)
    monkeypatch.setattr(
        health, "build_research_health_report",
        lambda *args, **kwargs: _health_report(),
    )
    monkeypatch.setattr(
        health, "write_health_report",
        lambda report, output_dir: (output_dir / "health.json", None),
    )

    result = runner.invoke(
        app,
        ["data", "run-stage", "--stage", "close", "--data-date", "2026-08-04"],
    )

    assert result.exit_code == 0, result.output
    assert order[:3] == [
        ("lock-enter", config.local_warehouse_dir),
        ("runtime", config.local_warehouse_dir),
        ("stage", date(2026, 8, 4)),
    ]
    assert order[-1] == ("lock-exit", config.local_warehouse_dir)


def test_scheduled_stage_optional_waiting_returns_zero_when_core_is_ready(
    tmp_path, monkeypatch
):
    import stock_analyzer.ops.research_data_job as job
    import stock_analyzer.ops.research_health as health

    config = SimpleNamespace(local_archive_dir=tmp_path / "archive")
    runtime = SimpleNamespace(config=config, warehouse=object())
    monkeypatch.setattr(job, "build_research_data_runtime", lambda config: runtime)
    monkeypatch.setattr(
        job,
        "run_research_stage",
        lambda runtime, *, stage, data_date: (
            BackfillSummary(
                scope="events",
                start=date(2026, 8, 4),
                through=date(2026, 8, 4),
                waiting_upstream=1,
                issues=["公告补采仍在等待上游"],
            ),
        ),
    )
    monkeypatch.setattr("stock_analyzer.config.AppConfig.load", lambda: config)
    monkeypatch.setattr(
        health,
        "build_research_health_report",
        lambda warehouse, data_date, full_history: _health_report(
            next_morning_status="waiting_upstream"
        ),
    )
    monkeypatch.setattr(
        health,
        "write_health_report",
        lambda report, output_dir: (output_dir / "health.json", None),
    )

    result = runner.invoke(
        app,
        [
            "data",
            "run-stage",
            "--stage",
            "next-morning",
            "--data-date",
            "2026-08-04",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "核心研究可用，部分研究通道受限" in result.output
    assert "公告补采" in result.output


def test_scheduled_stage_optional_feature_failure_returns_zero(
    tmp_path, monkeypatch
):
    import stock_analyzer.ops.research_data_job as job
    import stock_analyzer.ops.research_health as health

    config = SimpleNamespace(local_archive_dir=tmp_path / "archive")
    runtime = SimpleNamespace(config=config, warehouse=object())
    monkeypatch.setattr(job, "build_research_data_runtime", lambda config: runtime)
    monkeypatch.setattr(
        job,
        "run_research_stage",
        lambda runtime, *, stage, data_date: (
            BackfillSummary(
                scope="derived-research-features",
                start=date(2026, 8, 4),
                through=date(2026, 8, 4),
                failed=1,
                issues=["sector_hotspot: failed"],
            ),
        ),
    )
    monkeypatch.setattr("stock_analyzer.config.AppConfig.load", lambda: config)
    monkeypatch.setattr(
        health,
        "build_research_health_report",
        lambda warehouse, data_date, full_history: _health_report(
            sector_ready=False
        ),
    )
    monkeypatch.setattr(
        health,
        "write_health_report",
        lambda report, output_dir: (output_dir / "health.json", None),
    )

    result = runner.invoke(
        app,
        [
            "data",
            "run-stage",
            "--stage",
            "next-morning",
            "--data-date",
            "2026-08-04",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "核心研究可用，部分研究通道受限" in result.output
    assert "行业研究数据不可用" in result.output


def test_derive_optional_failure_returns_zero_and_names_limitation(
    tmp_path, monkeypatch
):
    import stock_analyzer.ops.research_features as features

    config = SimpleNamespace(local_warehouse_dir=tmp_path / "warehouse")
    monkeypatch.setattr("stock_analyzer.config.AppConfig.load", lambda: config)
    monkeypatch.setattr(
        features,
        "run_research_features",
        lambda warehouse, data_date: SimpleNamespace(
            failed_feature_sets=("sector_hotspot",),
            plain_language_summary="sector_hotspot: failed",
        ),
    )

    result = runner.invoke(
        app,
        ["data", "derive", "--data-date", "2026-08-04"],
    )

    assert result.exit_code == 0, result.output
    assert "核心研究可用，部分研究通道受限" in result.output
    assert "sector_hotspot" in result.output


def test_derive_core_failure_returns_two(tmp_path, monkeypatch):
    import stock_analyzer.ops.research_features as features

    config = SimpleNamespace(local_warehouse_dir=tmp_path / "warehouse")
    monkeypatch.setattr("stock_analyzer.config.AppConfig.load", lambda: config)
    monkeypatch.setattr(
        features,
        "run_research_features",
        lambda warehouse, data_date: SimpleNamespace(
            failed_feature_sets=("market_context",),
            plain_language_summary="market_context: failed",
        ),
    )

    result = runner.invoke(
        app,
        ["data", "derive", "--data-date", "2026-08-04"],
    )

    assert result.exit_code == 2, result.output
