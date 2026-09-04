from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

import typer

from stock_analyzer.config import AppConfig


app = typer.Typer(no_args_is_help=True)
data_app = typer.Typer(no_args_is_help=True)
app.add_typer(data_app, name="data")


def _health_research_state(report: Any) -> tuple[bool, tuple[str, ...]]:
    features = {
        str(getattr(item, "feature_set", "")): bool(
            getattr(item, "ready", False)
        )
        for item in getattr(report, "derived_features", ())
    }
    core_ready = bool(
        features.get("market_context", False)
        and features.get("price_analysis_context", False)
    )
    limitations: list[str] = []
    if not features.get("sector_hotspot", False):
        limitations.append("行业研究数据不可用")
    if not features.get("stock_trading_context", False):
        limitations.append("个股交易背景不可用")
    next_morning = next(
        (
            item
            for item in getattr(report, "latest_stage_runs", ())
            if getattr(item, "stage", "") == "next-morning"
        ),
        None,
    )
    capabilities = (
        getattr(next_morning, "capabilities", {})
        if next_morning is not None
        else {}
    )
    announcement_status = (
        str(capabilities.get("announcement_status", ""))
        if isinstance(capabilities, dict)
        else ""
    )
    if announcement_status not in {"cninfo_complete", "exchange_complete"}:
        limitations.append("行动日前公告补采未完成")
    return core_ready, tuple(limitations)


def _print_limited_research(limitations: tuple[str, ...]) -> None:
    typer.echo("核心研究可用，部分研究通道受限")
    for limitation in limitations:
        typer.echo(f"- {limitation}")


@data_app.command("backfill")
def data_backfill(
    through: str = typer.Option(..., "--through"),
    start: Optional[str] = typer.Option(None, "--start"),
    scope: str = typer.Option("all", "--scope"),
    resume: bool = typer.Option(True, "--resume/--no-resume"),
) -> None:
    from stock_analyzer.ops.research_data_job import (
        build_research_data_runtime,
        run_research_backfill,
    )

    through_date = date.fromisoformat(through)
    start_date = (
        date.fromisoformat(start)
        if start is not None
        else through_date - timedelta(days=5 * 366)
    )
    runtime = build_research_data_runtime(AppConfig.load())
    summaries = run_research_backfill(
        runtime,
        start=start_date,
        through=through_date,
        scope=scope,
        resume=resume,
    )
    for item in summaries:
        typer.echo(
            f"{item.scope}: committed={item.committed} skipped={item.skipped} "
            f"waiting={item.waiting_upstream} limited={item.limited} "
            f"failed={item.failed}"
        )
    if any(item.failed for item in summaries):
        raise typer.Exit(code=2)


@data_app.command("run-stage")
def data_run_stage(
    stage: str = typer.Option(..., "--stage"),
    data_date: str = typer.Option(..., "--data-date"),
) -> None:
    from stock_analyzer.ops.research_data_job import (
        build_research_data_runtime,
        research_job_lock,
        run_research_stage,
    )

    config = AppConfig.load()
    warehouse_root = getattr(config, "local_warehouse_dir", None)
    if warehouse_root is None:
        _execute_data_stage(
            config,
            stage=stage,
            data_date=data_date,
            already_locked=False,
            build_runtime=build_research_data_runtime,
            run_stage=run_research_stage,
        )
        return
    with research_job_lock(warehouse_root):
        _execute_data_stage(
            config,
            stage=stage,
            data_date=data_date,
            already_locked=True,
            build_runtime=build_research_data_runtime,
            run_stage=run_research_stage,
        )


def _execute_data_stage(
    config,
    *,
    stage: str,
    data_date: str,
    already_locked: bool,
    build_runtime,
    run_stage,
) -> None:
    runtime = build_runtime(config)
    parsed = (
        _resolve_research_stage_date(
            runtime.tushare,
            stage,
            datetime.now(ZoneInfo("Asia/Shanghai")),
        )
        if data_date == "auto"
        else date.fromisoformat(data_date)
    )
    if already_locked:
        summaries = run_stage(
            runtime, stage=stage, data_date=parsed, already_locked=True
        )
    else:
        summaries = run_stage(runtime, stage=stage, data_date=parsed)
    for item in summaries:
        typer.echo(
            f"{stage}/{item.scope}: committed={item.committed} skipped={item.skipped} "
            f"waiting={item.waiting_upstream} limited={item.limited} "
            f"failed={item.failed}"
        )
        if item.scope == "derived-research-features" and item.issues:
            typer.echo(item.issues[0])

    from stock_analyzer.ops.research_health import (
        build_research_health_report,
        write_health_report,
    )

    health = build_research_health_report(
        runtime.warehouse, parsed, full_history=False
    )
    health_path, _ = write_health_report(
        health, runtime.config.local_archive_dir / "data_health"
    )
    typer.echo(
        f"stage health: core_complete={str(health.complete_core_date).lower()} "
        f"output={health_path}"
    )
    if stage == "close":
        core_ready = not any(
            item.failed or item.waiting_upstream for item in summaries
        )
        limitations = tuple(
            issue
            for item in summaries
            if item.limited
            for issue in (item.issues or [f"{item.scope} 受限"])
        )
    else:
        core_ready, limitations = _health_research_state(health)
    if not core_ready:
        raise typer.Exit(code=2)
    stage_limitations = tuple(
        (
            f"{item.scope}: {item.issues[0]}"
            if item.issues
            else f"{item.scope} 未完整完成"
        )
        for item in summaries
        if item.failed or item.waiting_upstream
    )
    combined = tuple(dict.fromkeys((*limitations, *stage_limitations)))
    if combined:
        _print_limited_research(combined)


@data_app.command("derive")
def data_derive(
    data_date: str = typer.Option(..., "--data-date"),
) -> None:
    """Recompute governed observations from facts already stored locally."""

    from stock_analyzer.ops.research_features import run_research_features
    from stock_analyzer.storage.research_warehouse import ResearchWarehouse

    config = AppConfig.load()
    summary = run_research_features(
        ResearchWarehouse(config.local_warehouse_dir),
        date.fromisoformat(data_date),
    )
    typer.echo(summary.plain_language_summary)
    failed = set(summary.failed_feature_sets)
    if failed & {"market_context", "price_analysis_context"}:
        raise typer.Exit(code=2)
    if failed:
        _print_limited_research(tuple(sorted(failed)))


@data_app.command("health")
def data_health(
    data_date: str = typer.Option(..., "--data-date"),
    full_history: bool = typer.Option(False, "--full-history/--latest-only"),
) -> None:
    from stock_analyzer.ops.research_health import (
        build_research_health_report,
        write_health_report,
    )
    from stock_analyzer.storage.research_warehouse import ResearchWarehouse

    config = AppConfig.load()
    parsed = date.fromisoformat(data_date)
    report = build_research_health_report(
        ResearchWarehouse(config.local_warehouse_dir),
        parsed,
        full_history=full_history,
    )
    json_path, _ = write_health_report(
        report,
        config.local_archive_dir / "data_health",
    )
    typer.echo(
        f"data health {parsed}: core_complete={str(report.complete_core_date).lower()} "
        f"datasets={len(report.datasets)} gaps={sum(report.gap_counts.values())} "
        f"output={json_path}"
    )


def _resolve_research_stage_date(client, stage: str, now: datetime) -> date:
    local_now = now.astimezone(ZoneInfo("Asia/Shanghai"))
    today = local_now.date()
    calendar = client.fetch_trade_calendar(today - timedelta(days=14), today)
    open_dates = sorted(
        value
        for value in calendar.loc[calendar["is_open"], "cal_date"].tolist()
        if value <= today
    )
    if not open_dates:
        _fail("cannot resolve a trading date for research data stage")

    cutoffs = {
        "close": time(18, 30),
        "evening": time(21, 30),
    }
    if stage == "next-morning":
        candidates = [value for value in open_dates if value < today]
    elif stage in cutoffs:
        today_is_open = today in open_dates
        if today_is_open and local_now.time() >= cutoffs[stage]:
            return today
        candidates = [value for value in open_dates if value < today]
    else:
        _fail(f"unknown research data stage: {stage}")
    if not candidates:
        _fail(f"cannot resolve prior trading date for {stage} stage")
    return candidates[-1]


def _fail(message: str) -> None:
    typer.echo(f"Error: {message}", err=True)
    raise typer.Exit(code=2)
