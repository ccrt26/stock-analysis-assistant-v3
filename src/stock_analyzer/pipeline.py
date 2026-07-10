from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from stock_analyzer.analysis.evidence import (
    build_evidence_package,
    build_evidence_package_from_strategy_snapshot,
)
from stock_analyzer.analysis.focus import (
    FormalFocusDay,
    update_focus_watchlist,
    update_focus_watchlist_v2,
)
from stock_analyzer.analysis.pool import clean_stock_pool
from stock_analyzer.analysis.recommendation import generate_recommendations
from stock_analyzer.analysis.strategy_v2 import generate_strategy_v2_recommendations
from stock_analyzer.data.models import (
    DailyBar,
    DailyBasicRow,
    MarketDataBundle,
    SourceRunRecord,
)
from stock_analyzer.data.provider import CurrentLiveDataUnavailable, MarketDataProvider
from stock_analyzer.domain.models import (
    ActionDecision,
    ActionLabel,
    ActionRecommendationSummary,
    DataRecoveryAttempt,
    EvaluationTask,
    EvidencePackage,
    FeatureSnapshot,
    FocusState,
    ManualHoldingSummary,
    ManualHolding,
    OperationalDailyStatus,
    OperationalReportState,
    Recommendation,
    StockSnapshot,
    StrategyEvidenceSnapshot,
)
from stock_analyzer.evaluation.tasks import create_evaluation_tasks
from stock_analyzer.reports.generator import (
    render_data_insufficient_report,
    render_reports,
)
from stock_analyzer.storage.repositories import AnalysisRepository, InMemoryAnalysisRepository


class DailyRunResult(BaseModel):
    trade_date: date
    recommendations: list[Recommendation]
    focus_states: list[FocusState]
    evaluation_tasks: list[EvaluationTask]
    operational_status: OperationalDailyStatus


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
    market_data_provider: Optional[MarketDataProvider] = None,
    local_warehouse=None,
    local_archive=None,
    strategy_v2: bool = False,
    allow_data_insufficient_output: bool = False,
    manual_entries: Optional[list[tuple[str, str | None]]] = None,
    manual_holdings: Optional[list[ManualHolding]] = None,
    eligible_focus_days: Optional[list[FormalFocusDay]] = None,
) -> DailyRunResult:
    repository = repository or InMemoryAnalysisRepository()
    persist = persist and not dry_run
    production_bundle = None
    if fixture_mode or dry_run:
        stocks, stock_names, feature_profiles = _sample_market(trade_date)
    else:
        if market_data_provider is None:
            return _handle_data_insufficient_output_or_raise(
                trade_date=trade_date,
                output_dir=output_dir,
                message=PRODUCTION_DATA_SOURCE_UNAVAILABLE_MESSAGE,
                allow_data_insufficient_output=allow_data_insufficient_output,
                bundle=None,
                local_archive=local_archive,
                dry_run=dry_run,
                recovery_attempts=[
                    _provider_unavailable_recovery_attempt(
                        trade_date,
                        PRODUCTION_DATA_SOURCE_UNAVAILABLE_MESSAGE,
                        source_name="market_data_provider",
                    )
                ],
            )
        try:
            bundle = market_data_provider.load(trade_date)
        except CurrentLiveDataUnavailable as exc:
            return _handle_data_insufficient_output_or_raise(
                trade_date=trade_date,
                output_dir=output_dir,
                message=str(exc),
                allow_data_insufficient_output=allow_data_insufficient_output,
                bundle=None,
                local_archive=local_archive,
                dry_run=dry_run,
                recovery_attempts=[
                    _provider_unavailable_recovery_attempt(
                        trade_date,
                        str(exc),
                        source_name=_provider_source_name(market_data_provider),
                    )
                ],
            )
        if not bundle.can_generate_decisions:
            return _handle_data_insufficient_output_or_raise(
                trade_date=trade_date,
                output_dir=output_dir,
                message="Current live data is unavailable; no production decisions were generated.",
                allow_data_insufficient_output=allow_data_insufficient_output,
                bundle=bundle,
                local_archive=local_archive,
                dry_run=dry_run,
            )
        stocks, stock_names, feature_profiles = bundle.to_pipeline_inputs()
        if not stocks or not feature_profiles:
            return _handle_data_insufficient_output_or_raise(
                trade_date=trade_date,
                output_dir=output_dir,
                message="Current live data is unavailable; no production decisions were generated.",
                allow_data_insufficient_output=allow_data_insufficient_output,
                bundle=bundle,
                local_archive=local_archive,
                dry_run=dry_run,
            )
        production_bundle = bundle
    included_stocks, _ = clean_stock_pool(stocks)
    if not fixture_mode and not dry_run:
        if not _has_recommendation_eligible_features(included_stocks, feature_profiles):
            return _handle_data_insufficient_output_or_raise(
                trade_date=trade_date,
                output_dir=output_dir,
                message="Current live data is unavailable; no production decisions were generated.",
                allow_data_insufficient_output=allow_data_insufficient_output,
                bundle=production_bundle,
                local_archive=local_archive,
                dry_run=dry_run,
                extra_blocking_missing_fields=_eligible_feature_blocking_fields(
                    included_stocks,
                    feature_profiles,
                ),
            )
        if persist and production_bundle is not None:
            if local_warehouse is None:
                raise ProductionDataSourceUnavailable(
                    "Production persistence requires local warehouse before Supabase writes."
                )
            local_warehouse.save_bundle(production_bundle)
    features = [
        feature_profiles[stock.ts_code]
        for stock in included_stocks
        if stock.ts_code in feature_profiles
    ]

    existing = (
        existing_focus_states
        if existing_focus_states is not None
        else repository.load_focus_states()
    )
    strategy_v2_cards = []
    strategy_v2_snapshots = []
    focus_entry_theses = []
    focus_daily_updates = []
    action_recommendation_summaries = []
    manual_holding_summaries = []
    if strategy_v2:
        strategy_result = generate_strategy_v2_recommendations(
            features,
            stock_names,
            trade_date=trade_date,
            current_holdings=_manual_holdings_by_code(manual_holdings or []),
        )
        strategy_v2_cards = list(strategy_result.cards)
        strategy_snapshots = list(strategy_result.snapshots)
        strategy_v2_snapshots = [
            *strategy_snapshots,
            *strategy_result.data_insufficient_snapshots,
        ]
        recommendations = _recommendations_from_strategy_snapshots(
            strategy_snapshots,
        )
        prior_focus_snapshots: list[StrategyEvidenceSnapshot] = []
        if eligible_focus_days is not None:
            prior_focus_snapshots = (
                repository.load_formally_committed_strategy_snapshots(
                    before_date=trade_date,
                    eligible_dates=[day.trade_date for day in eligible_focus_days],
                )
            )
        focus_result = update_focus_watchlist_v2(
            existing=existing,
            recommendation_snapshots=[
                *prior_focus_snapshots,
                *strategy_v2_snapshots,
            ],
            manual_entries=list(manual_entries or []),
            trade_date=trade_date,
            eligible_focus_days=eligible_focus_days,
        )
        focus_states = focus_result.focus_states
        focus_entry_theses = list(focus_result.entry_theses)
        focus_daily_updates = list(focus_result.daily_updates)
        action_recommendation_summaries = (
            _action_recommendation_summaries_from_snapshots(strategy_v2_snapshots)
        )
        manual_holding_summaries = _manual_holding_summaries_from_holdings(
            trade_date,
            manual_holdings or [],
            strategy_v2_snapshots,
        )
        evidence_packages = [
            build_evidence_package_from_strategy_snapshot(snapshot)
            for snapshot in strategy_snapshots
        ]
    else:
        recommendation_result = generate_recommendations(features, stock_names)
        recommendations = recommendation_result.recommendations
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
    operational_status = _generated_operational_status(
        trade_date,
        recommendations,
        focus_states,
    )

    if persist:
        selected_codes = _selected_decision_codes(recommendations, focus_states)
        if production_bundle is not None:
            selected_market_bars, selected_daily_basic = _filter_market_window(
                production_bundle,
                selected_codes,
            )
            preflight_market_window_writes = getattr(
                repository,
                "preflight_market_window_writes",
                None,
            )
            if preflight_market_window_writes is not None:
                preflight_market_window_writes(
                    selected_market_bars,
                    selected_daily_basic,
                )
            repository.save_stock_master(production_bundle.stock_basic)
            repository.save_data_source_runs(production_bundle.source_runs)
            repository.save_market_bars(selected_market_bars)
            repository.save_daily_basic_indicators(selected_daily_basic)
            stock_statuses_to_save = [
                stock for stock in stocks if stock.ts_code in selected_codes
            ]
            features_to_save = [
                feature for feature in features if feature.ts_code in selected_codes
            ]
        else:
            stock_statuses_to_save = stocks
            features_to_save = features
        if production_bundle is None:
            repository.save_stock_master(stock_statuses_to_save)
        repository.save_stock_statuses(stock_statuses_to_save)
        repository.save_feature_snapshots(features_to_save)
        repository.save_recommendations(recommendations)
        repository.save_focus_states(focus_states)
        repository.save_evidence_packages(evidence_packages)
        repository.save_evaluation_tasks(evaluation_tasks)
        if strategy_v2:
            _save_strategy_v2_ledger_rows(
                repository=repository,
                strategy_snapshots=strategy_v2_snapshots,
                focus_entry_theses=focus_entry_theses,
                focus_daily_updates=focus_daily_updates,
                action_recommendations=action_recommendation_summaries,
                manual_holding_summaries=manual_holding_summaries,
                operational_status=operational_status,
            )

    if not dry_run:
        strategy_v2_report_kwargs = (
            {
                "strategy_v2_cards": strategy_v2_cards,
                "strategy_v2_snapshots": strategy_v2_snapshots,
                "focus_entry_theses": focus_entry_theses,
                "focus_daily_updates": focus_daily_updates,
            }
            if strategy_v2
            else {}
        )
        render_reports(
            output_dir,
            recommendations,
            focus_states,
            evidence_packages=evidence_packages,
            trade_date=trade_date,
            fixture_mode=fixture_mode,
            data_status=production_bundle.data_status if production_bundle else None,
            source_versions=(
                production_bundle.source_versions if production_bundle else None
            ),
            operational_status=operational_status,
            **strategy_v2_report_kwargs,
        )
        if local_archive is not None and not fixture_mode:
            local_archive.archive_report_tree(output_dir, trade_date)

    return DailyRunResult(
        trade_date=trade_date,
        recommendations=recommendations,
        focus_states=focus_states,
        evaluation_tasks=evaluation_tasks,
        operational_status=operational_status,
    )


def _handle_data_insufficient_output_or_raise(
    *,
    trade_date: date,
    output_dir: Path,
    message: str,
    allow_data_insufficient_output: bool,
    bundle: Optional[MarketDataBundle],
    local_archive,
    dry_run: bool,
    extra_blocking_missing_fields: Optional[list[str]] = None,
    recovery_attempts: Optional[list[DataRecoveryAttempt]] = None,
) -> DailyRunResult:
    if not allow_data_insufficient_output:
        raise ProductionDataSourceUnavailable(message)

    operational_status = _data_insufficient_operational_status(
        trade_date=trade_date,
        message=message,
        bundle=bundle,
        extra_blocking_missing_fields=extra_blocking_missing_fields,
        recovery_attempts=recovery_attempts,
    )
    if not dry_run:
        render_data_insufficient_report(
            output_dir,
            operational_status,
            source_versions=bundle.source_versions if bundle else None,
        )
        if local_archive is not None:
            local_archive.archive_report_tree(output_dir, trade_date)
    return DailyRunResult(
        trade_date=trade_date,
        recommendations=[],
        focus_states=[],
        evaluation_tasks=[],
        operational_status=operational_status,
    )


def _generated_operational_status(
    trade_date: date,
    recommendations: list[Recommendation],
    focus_states: list[FocusState],
) -> OperationalDailyStatus:
    return OperationalDailyStatus(
        trade_date=trade_date,
        is_trading_day=True,
        recommendation_state=OperationalReportState.GENERATED,
        focus_state=OperationalReportState.GENERATED,
        recommendation_count=len(recommendations),
        focus_count=len(focus_states),
        message="Daily recommendations and focus watchlist generated.",
    )


def _data_insufficient_operational_status(
    *,
    trade_date: date,
    message: str,
    bundle: Optional[MarketDataBundle],
    extra_blocking_missing_fields: Optional[list[str]] = None,
    recovery_attempts: Optional[list[DataRecoveryAttempt]] = None,
) -> OperationalDailyStatus:
    blocking_missing_fields = _dedupe(
        [
            *_blocking_missing_fields_for_bundle(bundle),
            *(extra_blocking_missing_fields or []),
        ]
    )
    data_recovery_attempts = _data_recovery_attempts_from_source_runs(
        bundle.source_runs if bundle else []
    )
    if recovery_attempts:
        data_recovery_attempts.extend(recovery_attempts)
    if not data_recovery_attempts:
        data_recovery_attempts.append(
            _provider_unavailable_recovery_attempt(
                trade_date,
                message,
                source_name="market_data_provider",
            )
        )

    return OperationalDailyStatus(
        trade_date=trade_date,
        is_trading_day=True,
        recommendation_state=OperationalReportState.DATA_INSUFFICIENT,
        focus_state=OperationalReportState.DATA_INSUFFICIENT,
        recommendation_count=0,
        focus_count=0,
        data_recovery_attempts=data_recovery_attempts,
        blocking_missing_fields=blocking_missing_fields,
        message=message,
    )


def _blocking_missing_fields_for_bundle(
    bundle: Optional[MarketDataBundle],
) -> list[str]:
    if bundle is None:
        return ["market_data_provider"]

    fields: list[str] = []
    if not bundle.can_generate_decisions:
        fields.append(f"data_status.{bundle.data_status.value}")
    if not bundle.stock_basic:
        fields.append("stock_basic")
    if not bundle.daily_bars:
        fields.append("daily_bars")
    if not bundle.daily_basic:
        fields.append("daily_basic")
    if not bundle.stocks:
        fields.append("stock_statuses")
    if not bundle.feature_profiles:
        fields.append("feature_snapshots")
    return _dedupe(fields or ["decision_inputs"])


def _eligible_feature_blocking_fields(
    stocks: list[StockSnapshot],
    feature_profiles: dict[str, FeatureSnapshot],
) -> list[str]:
    if not stocks:
        return ["stock_statuses.eligible_stock_pool"]
    if any(
        feature_profiles.get(stock.ts_code) is not None
        and feature_profiles[stock.ts_code].data_quality != "ok"
        for stock in stocks
    ):
        return ["feature_snapshots.data_quality"]
    return ["feature_snapshots.recommendation_eligible"]


def _data_recovery_attempts_from_source_runs(
    source_runs: list[SourceRunRecord],
) -> list[DataRecoveryAttempt]:
    attempts: list[DataRecoveryAttempt] = []
    for source_run in source_runs:
        recovered_fields = [
            field for field, is_available in source_run.field_coverage.items()
            if is_available
        ]
        attempts.append(
            DataRecoveryAttempt(
                source_name=source_run.source_name,
                family=source_run.stage,
                status=source_run.status.value,
                message=source_run.message,
                trade_date=source_run.trade_date,
                succeeded=source_run.status.value == "success",
                recovered_fields=recovered_fields,
                error=(
                    source_run.message
                    if source_run.status.value == "failed"
                    else None
                ),
            )
        )
    return attempts


def _provider_unavailable_recovery_attempt(
    trade_date: date,
    message: str,
    *,
    source_name: str,
) -> DataRecoveryAttempt:
    return DataRecoveryAttempt(
        family="market_data_provider",
        source_name=source_name,
        source=source_name,
        status="failed",
        message=message,
        trade_date=trade_date,
        succeeded=False,
        error=message,
    )


def _provider_source_name(provider: MarketDataProvider) -> str:
    configured_name = getattr(provider, "source_name", None)
    if isinstance(configured_name, str) and configured_name.strip():
        return configured_name.strip()
    return provider.__class__.__name__ or "market_data_provider"


def _action_recommendation_summaries_from_snapshots(
    snapshots: list[StrategyEvidenceSnapshot],
) -> list[ActionRecommendationSummary]:
    return [
        ActionRecommendationSummary(
            trade_date=snapshot.trade_date,
            ts_code=snapshot.ts_code,
            decision=snapshot.action.decision,
            position_min_pct=snapshot.action.position_min_pct,
            position_max_pct=snapshot.action.position_max_pct,
            invalidation_conditions=list(snapshot.action.invalidation_conditions),
        )
        for snapshot in snapshots
    ]


def _manual_holding_summaries_from_holdings(
    trade_date: date,
    manual_holdings: list[ManualHolding],
    snapshots: list[StrategyEvidenceSnapshot],
) -> list[ManualHoldingSummary]:
    snapshots_by_code = {snapshot.ts_code: snapshot for snapshot in snapshots}
    return [
        ManualHoldingSummary(
            trade_date=trade_date,
            ts_code=holding.ts_code,
            held=True,
            position_band=_manual_position_band(holding.position_pct),
            last_action_state=_manual_holding_action_state(
                snapshots_by_code.get(holding.ts_code)
            ),
        )
        for holding in manual_holdings
    ]


def _manual_position_band(position_pct: float) -> str:
    if position_pct <= 0:
        return "empty"
    if position_pct < 2:
        return "tracking"
    if position_pct < 5:
        return "small"
    if position_pct < 10:
        return "medium"
    return "large"


def _manual_holding_action_state(
    snapshot: StrategyEvidenceSnapshot | None,
) -> str:
    if snapshot is None:
        return "manual_holding_without_strategy_snapshot"
    return snapshot.action.decision.value


def _save_strategy_v2_ledger_rows(
    *,
    repository: AnalysisRepository,
    strategy_snapshots: list[StrategyEvidenceSnapshot],
    focus_entry_theses: list,
    focus_daily_updates: list,
    action_recommendations: list[ActionRecommendationSummary],
    manual_holding_summaries: list[ManualHoldingSummary],
    operational_status: OperationalDailyStatus,
) -> None:
    _call_repository_save(repository, "save_strategy_snapshots", strategy_snapshots)
    _call_repository_save(repository, "save_focus_entry_theses", focus_entry_theses)
    _call_repository_save(repository, "save_focus_daily_updates", focus_daily_updates)
    _call_repository_save(
        repository,
        "save_action_recommendations",
        action_recommendations,
    )
    _call_repository_save(
        repository,
        "save_manual_holding_summaries",
        manual_holding_summaries,
    )
    _call_repository_save(
        repository,
        "save_operational_daily_status",
        operational_status,
    )


def _call_repository_save(
    repository: AnalysisRepository,
    method_name: str,
    value,
) -> None:
    save = getattr(repository, method_name, None)
    if save is not None:
        save(value)


def _recommendations_from_strategy_snapshots(
    snapshots: list[StrategyEvidenceSnapshot],
) -> list[Recommendation]:
    return [
        Recommendation(
            trade_date=snapshot.trade_date,
            ts_code=snapshot.ts_code,
            name=snapshot.name,
            action=_legacy_action_label_from_strategy_decision(
                snapshot.action.decision
            ),
            score=round(snapshot.internal_score, 4),
            reasons=_strategy_recommendation_reasons(snapshot),
            risks=_strategy_recommendation_risks(snapshot),
            evidence_id=snapshot.evidence_id,
        )
        for snapshot in snapshots
    ]


def _legacy_action_label_from_strategy_decision(
    decision: ActionDecision,
) -> ActionLabel:
    if decision in {
        ActionDecision.CONTINUE_WATCHING,
        ActionDecision.SMALL_EXPLORATORY,
        ActionDecision.INCREASE_ATTENTION,
        ActionDecision.CONDITIONAL_ADD,
    }:
        return ActionLabel.ENTER_OBSERVATION
    if decision in {ActionDecision.WAIT_FOR_CONFIRMATION, ActionDecision.AVOID_CHASING}:
        return ActionLabel.CONTINUE_OBSERVATION
    if decision == ActionDecision.CONFIRM_REMOVAL:
        return ActionLabel.EXIT_OBSERVATION
    if decision == ActionDecision.REDUCE_OR_AVOID:
        return ActionLabel.DOWNGRADE_OBSERVATION
    return ActionLabel.HIGH_RISK_OBSERVATION


def _strategy_recommendation_reasons(
    snapshot: StrategyEvidenceSnapshot,
) -> list[str]:
    reasons = [snapshot.thesis, *snapshot.action.reasoning]
    return _dedupe(reasons)


def _strategy_recommendation_risks(
    snapshot: StrategyEvidenceSnapshot,
) -> list[str]:
    risks = [snapshot.action.risk_if_wrong, *snapshot.action.invalidation_conditions]
    return _dedupe(risks)


def _manual_holdings_by_code(
    manual_holdings: list[ManualHolding],
) -> dict[str, ManualHolding]:
    return {holding.ts_code: holding for holding in manual_holdings}


def _has_recommendation_eligible_features(
    stocks: list[StockSnapshot],
    feature_profiles: dict[str, FeatureSnapshot],
) -> bool:
    return any(
        (feature := feature_profiles.get(stock.ts_code)) is not None
        and feature.data_quality == "ok"
        for stock in stocks
    )


def _selected_decision_codes(
    recommendations: list[Recommendation],
    focus_states: list[FocusState],
) -> set[str]:
    excluded_states = {ActionLabel.EXIT_OBSERVATION, ActionLabel.INSUFFICIENT_DATA}
    return {item.ts_code for item in recommendations} | {
        item.ts_code for item in focus_states if item.state not in excluded_states
    }


def _filter_market_window(
    bundle: MarketDataBundle,
    selected_codes: set[str],
) -> tuple[list[DailyBar], list[DailyBasicRow]]:
    if not selected_codes:
        return [], []
    return (
        [bar for bar in bundle.daily_bars if bar.ts_code in selected_codes],
        [row for row in bundle.daily_basic if row.ts_code in selected_codes],
    )


def _dedupe(items: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for item in items:
        normalized = item.strip()
        if normalized and normalized not in seen:
            output.append(normalized)
            seen.add(normalized)
    return output


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
        operational_status = _generated_operational_status(
            trade_date,
            recommendations,
            focus_states,
        )
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
            operational_status=operational_status,
        )
        return DailyRunResult(
            trade_date=trade_date,
            recommendations=recommendations,
            focus_states=focus_states,
            evaluation_tasks=evaluation_tasks,
            operational_status=operational_status,
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
