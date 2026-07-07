from __future__ import annotations

from datetime import date
from pathlib import Path

from pydantic import BaseModel

from stock_analyzer.analysis.evidence import build_evidence_package
from stock_analyzer.analysis.focus import update_focus_watchlist
from stock_analyzer.analysis.pool import clean_stock_pool
from stock_analyzer.analysis.recommendation import generate_recommendations
from stock_analyzer.domain.models import (
    EvaluationTask,
    FeatureSnapshot,
    FocusState,
    Recommendation,
    StockSnapshot,
)
from stock_analyzer.evaluation.tasks import create_evaluation_tasks
from stock_analyzer.reports.generator import render_reports
from stock_analyzer.storage.repositories import InMemoryAnalysisRepository


class DailyRunResult(BaseModel):
    trade_date: date
    recommendations: list[Recommendation]
    focus_states: list[FocusState]
    evaluation_tasks: list[EvaluationTask]


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
) -> DailyRunResult:
    stocks, stock_names, feature_profiles = _sample_market(trade_date)
    included_stocks, _ = clean_stock_pool(stocks)
    features = [feature_profiles[stock.ts_code] for stock in included_stocks if stock.ts_code in feature_profiles]

    recommendation_result = generate_recommendations(features, stock_names)
    recommendations = recommendation_result.recommendations
    focus_states = update_focus_watchlist(
        existing=[],
        recommendations=recommendations,
        invalidated_codes=set(),
    )
    evidence_packages = [
        build_evidence_package(
            recommendation,
            matched_rules=["RESEARCH_TREND_CONFIRMATION"],
        )
        for recommendation in recommendations
    ]
    evaluation_tasks = [
        task
        for package in evidence_packages
        for task in create_evaluation_tasks(package)
    ]

    repository = InMemoryAnalysisRepository()
    repository.save_recommendations(recommendations)
    repository.save_focus_states(focus_states)
    repository.save_evidence_packages(evidence_packages)
    repository.save_evaluation_tasks(evaluation_tasks)

    if not dry_run:
        render_reports(output_dir, recommendations, focus_states)

    return DailyRunResult(
        trade_date=trade_date,
        recommendations=recommendations,
        focus_states=focus_states,
        evaluation_tasks=evaluation_tasks,
    )
