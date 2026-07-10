from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict

from stock_analyzer.analysis.evidence import (
    build_evidence_package_from_strategy_snapshot,
)
from stock_analyzer.analysis.focus import update_focus_watchlist_v2
from stock_analyzer.analysis.strategy_v2 import (
    build_strategy_snapshot,
    generate_strategy_v2_recommendations,
)
from stock_analyzer.data.formal_materializer import (
    FormalMaterializationError,
    materialize_market_inputs,
    materialize_target_context,
)
from stock_analyzer.data.readiness import (
    JULY_10_OFFICIAL_SESSIONS,
    AcquisitionGroupId,
    AcquisitionPayload,
    FormalRunState,
)
from stock_analyzer.domain.models import (
    ActionRecommendationSummary,
    EvaluationTask,
    EvidencePackage,
    FocusDailyUpdate,
    FocusEntryThesis,
    FocusState,
    ManualHoldingSummary,
    OperationalDailyStatus,
    Recommendation,
    RecommendationCard,
    StrategyEvidenceSnapshot,
)
from stock_analyzer.evaluation.tasks import create_evaluation_tasks
from stock_analyzer.ops.formal_run import (
    CandidateSet,
    FormalAnalysisOutput,
    RunReceipt,
)
from stock_analyzer.pipeline import (
    _action_recommendation_summaries_from_snapshots,
    _generated_operational_status,
    _manual_holding_summaries_from_holdings,
    _recommendations_from_strategy_snapshots,
)


class FormalReportPayload(BaseModel):
    model_config = ConfigDict(frozen=True)

    trade_date: date
    run_id: str
    input_set_id: str
    candidate_set_id: str
    recommendations: list[Recommendation]
    focus_states: list[FocusState]
    evidence_packages: list[EvidencePackage]
    evaluation_tasks: list[EvaluationTask]
    recommendation_cards: list[RecommendationCard]
    strategy_snapshots: list[StrategyEvidenceSnapshot]
    focus_entry_theses: list[FocusEntryThesis]
    focus_daily_updates: list[FocusDailyUpdate]
    action_recommendations: list[ActionRecommendationSummary]
    manual_holding_summaries: list[ManualHoldingSummary]
    operational_status: OperationalDailyStatus
    source_versions: dict[str, str]


def analyze_formal_inputs(
    receipt: RunReceipt,
    candidate_set: CandidateSet,
    payloads: dict[AcquisitionGroupId, AcquisitionPayload],
    repository: Any,
) -> FormalAnalysisOutput:
    if receipt.state is not FormalRunState.READY_TO_ANALYZE:
        raise FormalMaterializationError("analysis requires READY_TO_ANALYZE")
    if receipt.input_set_id is None or receipt.candidate_set_id != candidate_set.candidate_set_id:
        raise FormalMaterializationError("analysis receipt and candidate set do not match")
    if candidate_set.upstream_input_set_id != receipt.input_set_id:
        raise FormalMaterializationError("candidate set does not match frozen input set")

    market = materialize_market_inputs(receipt.target_date, payloads)
    target_codes = tuple(
        dict.fromkeys((*candidate_set.ordered_codes, *candidate_set.active_focus_codes))
    )
    context = materialize_target_context(receipt.target_date, target_codes, payloads)
    unavailable = sorted(set(target_codes) - set(market.feature_profiles))
    if unavailable:
        raise FormalMaterializationError(
            "frozen target lacks current feature snapshot: " + ", ".join(unavailable)
        )

    company_profiles = {
        code: row.business_summary or ""
        for code, row in context.company_profiles.items()
    }
    board_context = {
        code: _board_context_text(row)
        for code, row in context.board_contexts.items()
    }
    official_events = {
        code: [f"{row.event_type}: {row.title}" for row in rows]
        for code, rows in context.official_events.items()
    }
    official_hard_risks = {
        code: any(row.hard_risk for row in rows)
        for code, rows in context.official_events.items()
    }
    public_information = {
        code: [row.concept_name for row in rows]
        for code, rows in context.concept_tags.items()
    }
    candidate_features = [
        market.feature_profiles[code] for code in candidate_set.ordered_codes
    ]
    result = generate_strategy_v2_recommendations(
        features=candidate_features,
        stock_names=market.bundle.stock_names,
        trade_date=receipt.target_date,
        limit=len(candidate_set.ordered_codes),
        company_profiles=company_profiles,
        board_context=board_context,
        official_events=official_events,
        public_information=public_information,
        current_holdings=context.manual_holdings,
        fundamental_summaries=context.fundamental_summaries,
        official_hard_risks=official_hard_risks,
    )
    candidate_snapshots = [*result.snapshots, *result.data_insufficient_snapshots]
    candidate_snapshot_codes = {item.ts_code for item in candidate_snapshots}
    focus_snapshots = [
        _build_focus_snapshot(
            code,
            receipt,
            market,
            context,
            company_profiles,
            board_context,
            official_events,
            public_information,
            official_hard_risks,
        )
        for code in candidate_set.active_focus_codes
        if code not in candidate_snapshot_codes
    ]
    current_snapshots = [*candidate_snapshots, *focus_snapshots]

    eligible_dates = _prior_five_sessions(receipt.target_date)
    focus_days = repository.load_formal_focus_days(
        before_date=receipt.target_date,
        eligible_dates=eligible_dates,
    )
    if [item.trade_date for item in focus_days] != eligible_dates:
        raise FormalMaterializationError("formal focus history does not cover exact five sessions")
    prior_snapshots = repository.load_formally_committed_strategy_snapshots(
        before_date=receipt.target_date,
        eligible_dates=eligible_dates,
    )
    focus_result = update_focus_watchlist_v2(
        existing=repository.load_focus_states(),
        recommendation_snapshots=[*prior_snapshots, *current_snapshots],
        manual_entries=[],
        trade_date=receipt.target_date,
        eligible_focus_days=focus_days,
    )

    recommendations = _recommendations_from_strategy_snapshots(result.snapshots)
    evidence_packages = [
        build_evidence_package_from_strategy_snapshot(snapshot)
        for snapshot in current_snapshots
    ]
    evaluation_tasks = [
        task
        for package in evidence_packages
        for task in create_evaluation_tasks(package)
    ]
    action_recommendations = _action_recommendation_summaries_from_snapshots(
        current_snapshots
    )
    manual_holding_summaries = _manual_holding_summaries_from_holdings(
        receipt.target_date,
        list(context.manual_holdings.values()),
        current_snapshots,
    )
    operational_status = _generated_operational_status(
        receipt.target_date,
        recommendations,
        focus_result.focus_states,
    )
    report_payload = FormalReportPayload(
        trade_date=receipt.target_date,
        run_id=receipt.run_id,
        input_set_id=receipt.input_set_id,
        candidate_set_id=candidate_set.candidate_set_id,
        recommendations=recommendations,
        focus_states=list(focus_result.focus_states),
        evidence_packages=evidence_packages,
        evaluation_tasks=evaluation_tasks,
        recommendation_cards=list(result.cards),
        strategy_snapshots=current_snapshots,
        focus_entry_theses=list(focus_result.entry_theses),
        focus_daily_updates=list(focus_result.daily_updates),
        action_recommendations=action_recommendations,
        manual_holding_summaries=manual_holding_summaries,
        operational_status=operational_status,
        source_versions=dict(sorted(market.bundle.source_versions.items())),
    )
    evidence_hashes = {
        package.evidence_id: _model_hash(package)
        for package in evidence_packages
    }
    ledger_rows = _ledger_rows(report_payload)
    return FormalAnalysisOutput(
        value=report_payload,
        ledger_rows=ledger_rows,
        evidence_hashes=evidence_hashes,
        pointer_payloads={},
        has_publishable_output=bool(recommendations),
    )


def _build_focus_snapshot(
    code: str,
    receipt: RunReceipt,
    market: Any,
    context: Any,
    company_profiles: dict[str, str],
    board_context: dict[str, str],
    official_events: dict[str, list[str]],
    public_information: dict[str, list[str]],
    official_hard_risks: dict[str, bool],
) -> StrategyEvidenceSnapshot:
    return build_strategy_snapshot(
        feature=market.feature_profiles[code],
        stock_name=market.bundle.stock_names.get(code, code),
        trade_date=receipt.target_date,
        company_profile=company_profiles.get(code),
        board_context=board_context.get(code),
        official_events=official_events.get(code, []),
        public_information=public_information.get(code, []),
        current_holding=context.manual_holdings.get(code),
        fundamental_summary=context.fundamental_summaries.get(code),
        official_hard_risk=official_hard_risks.get(code, False),
    )


def _prior_five_sessions(trade_date: date) -> list[date]:
    prior = [value for value in JULY_10_OFFICIAL_SESSIONS if value < trade_date]
    selected = prior[-5:]
    if len(selected) != 5:
        raise FormalMaterializationError("five prior official sessions are unavailable")
    return selected


def _board_context_text(row: Any) -> str:
    strength = (
        f"20日相对强度 {row.relative_strength_20d:.2%}"
        if row.relative_strength_20d is not None
        else "20日相对强度未形成"
    )
    return f"{row.board_name}；{strength}"


def _ledger_rows(payload: FormalReportPayload) -> tuple[dict[str, Any], ...]:
    groups = (
        ("recommendation", payload.recommendations),
        ("focus_state", payload.focus_states),
        ("evidence_package", payload.evidence_packages),
        ("evaluation_task", payload.evaluation_tasks),
        ("strategy_snapshot", payload.strategy_snapshots),
        ("focus_entry_thesis", payload.focus_entry_theses),
        ("focus_daily_update", payload.focus_daily_updates),
        ("action_recommendation", payload.action_recommendations),
        ("manual_holding_summary", payload.manual_holding_summaries),
        ("operational_status", [payload.operational_status]),
    )
    return tuple(
        {"kind": kind, **model.model_dump(mode="json")}
        for kind, models in groups
        for model in models
    )


def _model_hash(model: BaseModel) -> str:
    canonical = json.dumps(
        model.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "FormalReportPayload",
    "analyze_formal_inputs",
]
