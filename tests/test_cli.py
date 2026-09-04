from datetime import date, datetime
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from typer.testing import CliRunner

from stock_analyzer.cli import _health_research_state, app
from stock_analyzer.data.research_backfill import BackfillSummary


runner = CliRunner()


def _freeze_cli_clock(monkeypatch, value):
    calls = []
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            calls.append(tz)
            return value.astimezone(tz)
    monkeypatch.setattr("stock_analyzer.cli.datetime", Clock)
    return calls


@pytest.fixture(autouse=True)
def _fixed_cli_time(monkeypatch):
    _freeze_cli_clock(monkeypatch, datetime.fromisoformat("2026-09-07T18:45:00+08:00"))


def _health_report(
    *,
    complete_core_date: bool = True,
    market_ready: bool = True,
    sector_ready: bool = True,
    stock_ready: bool = True,
    price_ready: bool = True,
    pre_research_status: str = "succeeded",
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
                stage="pre-research",
                status=pre_research_status,
                capabilities={
                    "announcement_status": announcement_status
                    or (
                        "cninfo_complete"
                        if pre_research_status in {"succeeded", "limited"}
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
        lambda runtime, *, stage, data_date, **kwargs: (
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
        lambda runtime, *, stage, data_date, **kwargs: (
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
        lambda runtime, *, stage, data_date, **kwargs: (
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
            pre_research_status="waiting_upstream"
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
            "pre-research",
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
        lambda runtime, *, stage, data_date, **kwargs: (
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
            "pre-research",
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


def test_stage_cutoff_option_and_validation_before_runtime():
    help_result = runner.invoke(app, ["data", "run-stage", "--help"])
    assert "--as-of" in help_result.output
    for stage, cutoff in (("close", "auto"), ("evening", "auto"),
                          ("pre-research", "2026-09-06T18:30:00")):
        result = runner.invoke(app, ["data", "run-stage", "--stage", stage,
                                    "--data-date", "auto", "--as-of", cutoff])
        assert result.exit_code == 2
        assert "as-of" in result.output


@pytest.mark.parametrize("stage", ["evening", "close"])
@pytest.mark.parametrize("case", [
    "valid", "same_instant", "json_missing", "json_broken", "json_string",
    "wrong_date", "missing_pre", "old_run", "latest_snapshot_run", "latest_current_run",
    "wrong_cutoff", "empty_cutoff", "naive_cutoff", "invalid_cutoff",
    "current_empty_cutoff", "current_naive_cutoff", "current_missing_pre",
    "market_not_ready", "price_not_ready",
    "md_missing", "md_empty", "md_broken", "md_wrong_date",
])
def test_maintenance_preserves_only_validated_formal_health(tmp_path, monkeypatch, stage, case):
    import stock_analyzer.ops.research_data_job as job
    import stock_analyzer.ops.research_health as health
    from stock_analyzer.storage.research_warehouse import ResearchWarehouse
    from stock_analyzer.storage.research_schema import connect_research_warehouse

    formation = date(2026, 9, 4)
    config = SimpleNamespace(local_archive_dir=tmp_path / "archive")
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    runtime = SimpleNamespace(config=config, warehouse=warehouse)
    frozen = health.build_research_health_report(warehouse, formation)
    frozen.latest_stage_runs = (health.StageRunHealth(
        stage="pre-research", data_date=formation, run_id="formal", status="limited",
        started_at=datetime.fromisoformat("2026-09-06T18:32:00+08:00"),
        finished_at=datetime.fromisoformat("2026-09-06T18:40:00+08:00"),
        issues=(), capabilities={"research_as_of": "2026-09-06T18:30:00+08:00"},
    ),)
    for feature in frozen.derived_features:
        feature.ready = True
    current = frozen.model_copy(deep=True)
    current.derived_features[1].ready = False  # 维护状态不得混入有效正式快照。
    pre = frozen.latest_stage_runs[0]
    if case == "same_instant":
        pre.capabilities["research_as_of"] = "2026-09-06T10:30:00Z"
    elif case == "wrong_date":
        frozen.data_date = date(2026, 9, 3)
    elif case == "missing_pre":
        pre.data_date = date(2026, 9, 3)
    elif case == "old_run":
        pre.run_id = "old"
    elif case in {"latest_snapshot_run", "latest_current_run"}:
        newer = pre.model_copy(deep=True)
        newer.run_id = "newer"
        newer.started_at = newer.started_at.replace(minute=33)
        target = frozen if case == "latest_snapshot_run" else current
        target.latest_stage_runs = (newer, *target.latest_stage_runs)
    elif case in {"wrong_cutoff", "empty_cutoff", "naive_cutoff", "invalid_cutoff"}:
        pre.capabilities["research_as_of"] = {
            "wrong_cutoff": "2026-09-04T18:30:00+08:00",
            "empty_cutoff": "", "naive_cutoff": "2026-09-06T18:30:00",
            "invalid_cutoff": "not-a-time",
        }[case]
    elif case == "current_empty_cutoff":
        current.latest_stage_runs[0].capabilities["research_as_of"] = ""
    elif case == "current_naive_cutoff":
        current.latest_stage_runs[0].capabilities["research_as_of"] = "2026-09-06T18:30:00"
    elif case == "current_missing_pre":
        current.latest_stage_runs = ()
    elif case in {"market_not_ready", "price_not_ready"}:
        feature_set = "market_context" if case == "market_not_ready" else "price_analysis_context"
        next(f for f in frozen.derived_features if f.feature_set == feature_set).ready = False
    output = config.local_archive_dir / "data_health"
    output.mkdir(parents=True)
    json_path, md_path = output / f"{formation}.json", output / f"{formation}.md"
    json_path.write_text(frozen.model_dump_json(), encoding="utf-8")
    md_path.write_text(f"# {formation} 数据健康摘要\n正式内容", encoding="utf-8")
    if case == "json_missing":
        json_path.unlink()
    elif case == "json_broken":
        json_path.write_text("{broken", encoding="utf-8")
    elif case == "json_string":
        json_path.write_text('"frozen"', encoding="utf-8")
    elif case == "md_missing":
        md_path.unlink()
    elif case.startswith("md_"):
        md_path.write_text({"md_empty": "", "md_broken": "broken",
                           "md_wrong_date": "# 2026-09-03 数据健康摘要"}[case], encoding="utf-8")
    before = (json_path.read_bytes() if json_path.exists() else None,
              md_path.read_bytes() if md_path.exists() else None)
    fact_calls = []
    def collect(*args, **kwargs):
        fact_calls.append(kwargs["stage"])
        return (BackfillSummary(scope="events", start=formation, through=formation, committed=1),)
    monkeypatch.setattr(job, "_run_research_stage_impl", collect)
    monkeypatch.setattr(job, "build_research_data_runtime", lambda _: runtime)
    monkeypatch.setattr("stock_analyzer.config.AppConfig.load", lambda: config)
    monkeypatch.setattr(health, "build_research_health_report", lambda *a, **k: current)

    result = runner.invoke(app, ["data", "run-stage", "--stage", stage,
                                 "--data-date", formation.isoformat()])

    assert result.exit_code == 0, result.output
    assert fact_calls == [stage]
    with connect_research_warehouse(warehouse.duckdb_path, read_only=True) as connection:
        assert connection.execute(
            "select stage, status from research_ingestion_runs"
        ).fetchall() == [(stage, "succeeded")]
    valid = case in {"valid", "same_instant", "md_missing", "md_empty", "md_broken", "md_wrong_date"}
    saved = health.ResearchHealthReport.model_validate_json(json_path.read_text())
    assert saved == (frozen if valid else current)
    assert f"# {formation} 数据健康摘要" in md_path.read_text()
    if case in {"valid", "same_instant"}:
        assert (json_path.read_bytes(), md_path.read_bytes()) == before
    if not valid:
        assert "保留18:30正式健康快照" not in result.output


def test_pre_research_always_writes_both_formal_health_files(tmp_path, monkeypatch):
    import stock_analyzer.ops.research_data_job as job
    import stock_analyzer.ops.research_health as health
    from stock_analyzer.storage.research_warehouse import ResearchWarehouse

    formation = date(2026, 9, 4)
    config = SimpleNamespace(local_archive_dir=tmp_path / "archive")
    warehouse = ResearchWarehouse(tmp_path / "warehouse")
    runtime = SimpleNamespace(config=config, warehouse=warehouse)
    report = health.build_research_health_report(warehouse, formation)
    report.latest_stage_runs = (health.StageRunHealth(
        stage="pre-research", data_date=formation, run_id="formal", status="limited",
        started_at=datetime.fromisoformat("2026-09-06T18:32:00+08:00"),
        finished_at=datetime.fromisoformat("2026-09-06T18:40:00+08:00"),
        issues=(), capabilities={"research_as_of": "2026-09-06T18:30:00+08:00"},
    ),)
    for feature in report.derived_features:
        feature.ready = True
    monkeypatch.setattr(job, "build_research_data_runtime", lambda _: runtime)
    monkeypatch.setattr(job, "_run_research_stage_impl", lambda *a, **k: ())
    monkeypatch.setattr("stock_analyzer.config.AppConfig.load", lambda: config)
    monkeypatch.setattr(health, "build_research_health_report", lambda *a, **k: report)
    output = config.local_archive_dir / "data_health"
    for _ in range(2):
        result = runner.invoke(app, ["data", "run-stage", "--stage", "pre-research",
            "--data-date", formation.isoformat(), "--as-of", "2026-09-06T18:30:00+08:00"])
        assert result.exit_code == 0, result.output
        for suffix in ("json", "md"):
            path = output / f"{formation}.{suffix}"
            assert path.is_file() and path.read_text(encoding="utf-8") != "old"
            path.write_text("old", encoding="utf-8")


@pytest.mark.parametrize("at", ["2026-09-05T18:00:00+08:00",
                              "2026-09-05T21:30:00+08:00",
                              "2026-10-03T18:00:00+08:00",
                              "2026-10-03T21:30:00+08:00"])
def test_evening_no_action_day_exits_zero_without_fact_collection(tmp_path, monkeypatch, at):
    import pandas as pd
    import stock_analyzer.cli as cli
    import stock_analyzer.ops.research_data_job as job
    now = datetime.fromisoformat(at)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz)
    class Calendar:
        def fetch_trade_calendar(self, start, through):
            days = list(pd.date_range(start, through).date)
            return pd.DataFrame({
                "cal_date": days,
                "is_open": [day in {date(2026, 9, 4), date(2026, 9, 30)} for day in days],
            })
    config = SimpleNamespace(local_archive_dir=tmp_path / "archive")
    monkeypatch.setattr(cli, "datetime", Clock)
    monkeypatch.setattr("stock_analyzer.config.AppConfig.load", lambda: config)
    monkeypatch.setattr(job, "build_research_data_runtime", lambda _: SimpleNamespace(tushare=Calendar()))
    monkeypatch.setattr(job, "run_research_stage", lambda *a, **k: pytest.fail("休市中间日不得补事实"))
    result = runner.invoke(app, ["data", "run-stage", "--stage", "evening", "--data-date", "auto"])
    assert result.exit_code == 0, result.output
    assert "no_action_day" in result.output
    assert not config.local_archive_dir.exists()


@pytest.mark.parametrize("moment", [
    "2026-09-07T08:00:00+08:00", "2026-09-07T18:29:59+08:00",
    "2026-09-06T08:00:00+08:00", "2026-10-08T08:00:00+08:00",
])
@pytest.mark.parametrize("data_date", ["auto", "2026-09-04"])
@pytest.mark.parametrize("as_of_args", [[], ["--as-of", "auto"]])
def test_auto_pre_research_before_cutoff_has_no_side_effects(
    tmp_path, monkeypatch, moment, data_date, as_of_args,
):
    import stock_analyzer.ops.research_data_job as job
    clock_calls = _freeze_cli_clock(monkeypatch, datetime.fromisoformat(moment))
    monkeypatch.setattr("stock_analyzer.config.AppConfig.load", lambda: pytest.fail("must not load config"))
    monkeypatch.setattr(job, "research_job_lock", lambda *a: pytest.fail("must not lock"))
    monkeypatch.setattr(job, "build_research_data_runtime", lambda *a: pytest.fail("must not initialize data"))
    monkeypatch.setattr(job, "run_research_stage", lambda *a, **k: pytest.fail("must not collect"))
    result = runner.invoke(app, ["data", "run-stage", "--stage", "pre-research",
                                "--data-date", data_date, *as_of_args])
    assert result.exit_code == 0, result.output
    assert "no_action_day" in result.output or "cutoff has not occurred" in result.output
    assert len(clock_calls) == 1
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("cutoff", [
    "2026-09-07T18:30:00+08:00", "2026-09-07T10:30:00Z",
    "2026-09-06T18:30:00+08:00", "2026-09-06T10:30:00+00:00",
])
def test_explicit_future_pre_research_cutoff_fails_before_any_data_access(monkeypatch, cutoff):
    import stock_analyzer.ops.research_data_job as job
    clock_calls = _freeze_cli_clock(monkeypatch, datetime.fromisoformat("2026-09-06T08:00:00+08:00"))
    monkeypatch.setattr("stock_analyzer.config.AppConfig.load", lambda: pytest.fail("must not load config"))
    monkeypatch.setattr(job, "research_job_lock", lambda *a: pytest.fail("must not lock"))
    monkeypatch.setattr(job, "build_research_data_runtime", lambda *a: pytest.fail("must not initialize"))
    result = runner.invoke(app, ["data", "run-stage", "--stage", "pre-research",
                                "--data-date", "auto", "--as-of", cutoff])
    assert result.exit_code == 2, result.output
    assert "cutoff has not occurred" in result.output
    assert len(clock_calls) == 1


@pytest.mark.parametrize("moment,cutoff", [
    ("2026-09-06T18:30:00+08:00", None),
    ("2026-09-06T18:32:00+08:00", "auto"),
    ("2026-09-06T10:32:00Z", "auto"),
    ("2026-09-07T08:00:00+08:00", "2026-09-06T18:30:00+08:00"),
    ("2026-09-07T08:00:00+08:00", "2026-09-06T10:30:00Z"),
])
def test_elapsed_auto_or_explicit_historical_cutoff_uses_original_calendar(
    tmp_path, monkeypatch, moment, cutoff,
):
    import pandas as pd
    import stock_analyzer.ops.research_data_job as job
    import stock_analyzer.ops.research_health as health
    calls = []
    clock_calls = _freeze_cli_clock(monkeypatch, datetime.fromisoformat(moment))
    class Calendar:
        def fetch_trade_calendar(self, start, through):
            calls.append(("calendar", through))
            days = list(pd.date_range(start, through).date)
            return pd.DataFrame({"cal_date": days, "is_open": [
                day in {date(2026, 9, 4), date(2026, 9, 7)} for day in days]})
    config = SimpleNamespace(local_archive_dir=tmp_path / "archive",
                             local_warehouse_dir=tmp_path / "warehouse")
    @contextmanager
    def lock(path):
        calls.append(("lock", path))
        yield
    def collect(runtime, **kwargs):
        calls.append(("stage", kwargs))
        return ()
    runtime = SimpleNamespace(config=config, tushare=Calendar(), warehouse=object())
    monkeypatch.setattr("stock_analyzer.config.AppConfig.load", lambda: config)
    monkeypatch.setattr(job, "research_job_lock", lock)
    monkeypatch.setattr(job, "build_research_data_runtime", lambda _: runtime)
    monkeypatch.setattr(job, "run_research_stage", collect)
    monkeypatch.setattr(health, "build_research_health_report", lambda *a, **k: _health_report())
    monkeypatch.setattr(health, "write_health_report", lambda report, output: (output / "health.json", None))
    arguments = ["data", "run-stage", "--stage", "pre-research", "--data-date", "auto"]
    if cutoff is not None:
        arguments.extend(["--as-of", cutoff])
    result = runner.invoke(app, arguments)
    assert result.exit_code == 0, result.output
    assert len(clock_calls) == 1
    assert calls == [
        ("lock", config.local_warehouse_dir), ("calendar", date(2026, 9, 7)),
        ("stage", {"stage": "pre-research", "data_date": date(2026, 9, 4),
                   "as_of": datetime.fromisoformat("2026-09-06T18:30:00+08:00"),
                   "already_locked": True}),
    ]
