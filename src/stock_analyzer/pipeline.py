from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from stock_analyzer.analysis.evidence import build_evidence_package
from stock_analyzer.analysis.focus import update_focus_watchlist
from stock_analyzer.analysis.pool import clean_stock_pool
from stock_analyzer.analysis.recommendation import generate_recommendations
from stock_analyzer.domain.models import (
    EvaluationTask,
    EvidencePackage,
    FeatureSnapshot,
    FocusState,
    Recommendation,
    StockSnapshot,
)
from stock_analyzer.evaluation.tasks import create_evaluation_tasks
from stock_analyzer.reports.generator import render_reports
from stock_analyzer.storage.repositories import AnalysisRepository, InMemoryAnalysisRepository


class DailyRunResult(BaseModel):
    trade_date: date
    recommendations: list[Recommendation]
    focus_states: list[FocusState]
    evaluation_tasks: list[EvaluationTask]


class StoredAnalysisNotFound(RuntimeError):
    pass


PRODUCTION_DATA_SOURCE_UNAVAILABLE_MESSAGE = (
    "Production run-daily requires real market data ingestion, but "
    "production ingestion is not implemented in this MVP. Use "
    "--fixture-mode or STOCK_ANALYZER_FIXTURE_MODE=1 only for local "
    "fixture/sample output."
)


class ProductionDataSourceUnavailable(RuntimeError):
    pass


def _sample_market(trade_date: date) -> tuple[list[StockSnapshot], dict[str, str], dict[str, FeatureSnapshot]]:
    stocks = [
        StockSnapshot(
            trade_date=trade_date,
            ts_code="600000.SH",
            name="浦发银行",
            listing_days=6_000,
            turnover_rate=1.2,
            amount=480_000_000,
        ),
        StockSnapshot(
            trade_date=trade_date,
            ts_code="600519.SH",
            name="贵州茅台",
            listing_days=9_000,
            turnover_rate=0.85,
            amount=1_800_000_000,
        ),
        StockSnapshot(
            trade_date=trade_date,
            ts_code="000001.SZ",
            name="*ST 风险样本",
            is_st=True,
            listing_days=4_000,
            turnover_rate=1.1,
            amount=420_000_000,
        ),
        StockSnapshot(
            trade_date=trade_date,
            ts_code="300001.SZ",
            name="次新低质样本",
            listing_days=60,
            turnover_rate=2.8,
            amount=530_000_000,
        ),
    ]
    stock_names = {stock.ts_code: stock.name for stock in stocks}
    feature_profiles = {
        "600000.SH": FeatureSnapshot(
            trade_date=trade_date,
            ts_code="600000.SH",
            trend_20d=0.08,
            trend_60d=0.12,
            relative_strength=0.75,
            volatility_20d=0.22,
            liquidity_score=0.9,
            quality_score=0.7,
            market_regime="sideways",
            industry="银行",
        ),
        "600519.SH": FeatureSnapshot(
            trade_date=trade_date,
            ts_code="600519.SH",
            trend_20d=0.05,
            trend_60d=0.10,
            relative_strength=0.70,
            volatility_20d=0.18,
            liquidity_score=0.85,
            quality_score=0.9,
            market_regime="sideways",
            industry="食品饮料",
        ),
    }
    return stocks, stock_names, feature_profiles


def run_daily_pipeline(
    trade_date: date,
    output_dir: Path,
    dry_run: bool = False,
    repository: Optional[AnalysisRepository] = None,
    existing_focus_states: Optional[list[FocusState]] = None,
    persist: bool = True,
    fixture_mode: bool = False,
) -> DailyRunResult:
    repository = repository or InMemoryAnalysisRepository()
    if not dry_run and not fixture_mode:
        raise ProductionDataSourceUnavailable(PRODUCTION_DATA_SOURCE_UNAVAILABLE_MESSAGE)
    persist = persist and not dry_run
    stocks, stock_names, feature_profiles = _sample_market(trade_date)
    included_stocks, _ = clean_stock_pool(stocks)
    features = [feature_profiles[stock.ts_code] for stock in included_stocks if stock.ts_code in feature_profiles]

    recommendation_result = generate_recommendations(features, stock_names)
    recommendations = recommendation_result.recommendations
    existing = (
        existing_focus_states
        if existing_focus_states is not None
        else repository.load_focus_states()
    )
    focus_states = update_focus_watchlist(
        existing=existing,
        recommendations=recommendations,
        invalidated_codes=set(),
        trade_date=trade_date,
    )
    evidence_packages = [
        build_evidence_package(
            recommendation,
            matched_rules=["RESEARCH_TREND_CONFIRMATION"],
        )
        for recommendation in recommendations
    ]
    recommendations = _assign_evidence_ids(recommendations, evidence_packages)
    evaluation_tasks = [
        task
        for package in evidence_packages
        for task in create_evaluation_tasks(package)
    ]

    if persist:
        repository.save_stock_master(stocks)
        repository.save_stock_statuses(stocks)
        repository.save_feature_snapshots(features)
        repository.save_recommendations(recommendations)
        repository.save_focus_states(focus_states)
        repository.save_evidence_packages(evidence_packages)
        repository.save_evaluation_tasks(evaluation_tasks)

    if not dry_run:
        render_reports(
            output_dir,
            recommendations,
            focus_states,
            evidence_packages=evidence_packages,
            trade_date=trade_date,
            fixture_mode=fixture_mode,
        )

    return DailyRunResult(
        trade_date=trade_date,
        recommendations=recommendations,
        focus_states=focus_states,
        evaluation_tasks=evaluation_tasks,
    )


def render_report_for_date(
    trade_date: date,
    output_dir: Path,
    repository: Optional[AnalysisRepository] = None,
    allow_fixture_fallback: bool = False,
) -> DailyRunResult:
    repository = repository or InMemoryAnalysisRepository()
    recommendations = repository.load_daily_recommendations(trade_date)
    focus_states = repository.load_focus_states_for_date(trade_date)
    evidence_packages = repository.load_evidence_packages(trade_date)
    evaluation_tasks = repository.load_evaluation_tasks(trade_date)
    if recommendations or focus_states or evidence_packages:
        _validate_stored_analysis_complete(
            trade_date,
            recommendations,
            evidence_packages,
            evaluation_tasks,
        )
        render_reports(
            output_dir,
            recommendations,
            focus_states,
            evidence_packages=evidence_packages,
            trade_date=trade_date,
        )
        return DailyRunResult(
            trade_date=trade_date,
            recommendations=recommendations,
            focus_states=focus_states,
            evaluation_tasks=evaluation_tasks,
        )

    if not allow_fixture_fallback:
        raise StoredAnalysisNotFound(
            f"No stored analysis rows found for {trade_date.isoformat()}. "
            "Run the daily pipeline with Supabase configured first, or use "
            "explicit fixture mode for local sample reports."
        )

    return run_daily_pipeline(
        trade_date,
        output_dir,
        dry_run=False,
        repository=repository,
        persist=False,
        fixture_mode=True,
    )


def _assign_evidence_ids(
    recommendations: list[Recommendation],
    evidence_packages: list[EvidencePackage],
) -> list[Recommendation]:
    evidence_by_code = {package.ts_code: package.evidence_id for package in evidence_packages}
    return [
        recommendation.model_copy(
            update={
                "evidence_id": evidence_by_code.get(
                    recommendation.ts_code,
                    recommendation.evidence_id,
                )
            }
        )
        for recommendation in recommendations
    ]


def _validate_stored_analysis_complete(
    trade_date: date,
    recommendations: list[Recommendation],
    evidence_packages: list[EvidencePackage],
    evaluation_tasks: list[EvaluationTask],
) -> None:
    if not recommendations:
        return

    evidence_by_id = {package.evidence_id: package for package in evidence_packages}
    missing_evidence = []
    mismatched_evidence = []
    matched_recommendations = []
    for recommendation in recommendations:
        evidence_id = recommendation.evidence_id
        if not evidence_id:
            missing_evidence.append(f"{recommendation.ts_code} (missing evidence_id)")
            continue
        package = evidence_by_id.get(evidence_id)
        if package is None:
            missing_evidence.append(f"{recommendation.ts_code} ({evidence_id})")
            continue
        if package.ts_code != recommendation.ts_code:
            mismatched_evidence.append(
                f"{recommendation.ts_code} ({evidence_id} belongs to {package.ts_code})"
            )
            continue
        matched_recommendations.append(recommendation)

    if missing_evidence or mismatched_evidence:
        detail = "; ".join(
            part
            for part in (
                _format_incomplete_refs(
                    "Missing evidence package",
                    missing_evidence,
                ),
                _format_incomplete_refs(
                    "Mismatched evidence package",
                    mismatched_evidence,
                ),
            )
            if part
        )
        raise StoredAnalysisNotFound(
            f"Stored analysis for {trade_date.isoformat()} is incomplete: {detail}. "
            "Production render-report refuses to publish without complete evidence."
        )

    task_keys = {
        (task.trade_date, task.ts_code, task.evidence_id)
        for task in evaluation_tasks
    }
    missing_tasks = [
        f"{recommendation.ts_code} ({recommendation.evidence_id})"
        for recommendation in matched_recommendations
        if (
            recommendation.trade_date,
            recommendation.ts_code,
            recommendation.evidence_id,
        )
        not in task_keys
    ]
    if missing_tasks:
        raise StoredAnalysisNotFound(
            f"Stored analysis for {trade_date.isoformat()} is incomplete: "
            f"{_format_incomplete_refs('Missing evaluation task', missing_tasks)}. "
            "Production render-report refuses to publish until evaluation tasks are registered."
        )


def _format_incomplete_refs(label: str, refs: list[str]) -> str:
    if not refs:
        return ""
    return f"{label} for recommendation(s): {', '.join(refs)}"
