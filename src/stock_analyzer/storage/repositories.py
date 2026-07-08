from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import List, Optional, Protocol

from stock_analyzer.domain.models import (
    ActionLabel,
    EvaluationTask,
    EvidencePackage,
    FeatureSnapshot,
    FocusState,
    Recommendation,
    StockSnapshot,
)


class AnalysisRepository(Protocol):
    def load_focus_states(self) -> List[FocusState]: ...
    def load_daily_recommendations(self, trade_date: date) -> List[Recommendation]: ...
    def load_focus_states_for_date(self, trade_date: date) -> List[FocusState]: ...
    def load_evidence_packages(self, trade_date: date) -> List[EvidencePackage]: ...
    def save_stock_master(self, stocks: List[StockSnapshot]) -> None: ...
    def save_stock_statuses(self, stocks: List[StockSnapshot]) -> None: ...
    def save_feature_snapshots(self, features: List[FeatureSnapshot]) -> None: ...
    def save_recommendations(self, recommendations: List[Recommendation]) -> None: ...
    def save_focus_states(self, states: List[FocusState]) -> None: ...
    def save_evidence_packages(self, packages: List[EvidencePackage]) -> None: ...
    def save_evaluation_tasks(self, tasks: List[EvaluationTask]) -> None: ...


class InMemoryAnalysisRepository:
    def __init__(
        self,
        recommendations: Optional[List[Recommendation]] = None,
        focus_states: Optional[List[FocusState]] = None,
        evidence_packages: Optional[List[EvidencePackage]] = None,
        evaluation_tasks: Optional[List[EvaluationTask]] = None,
        stock_master: Optional[List[StockSnapshot]] = None,
        stock_statuses: Optional[List[StockSnapshot]] = None,
        feature_snapshots: Optional[List[FeatureSnapshot]] = None,
    ) -> None:
        self.recommendations = list(recommendations or [])
        self.focus_states = list(focus_states or [])
        self.evidence_packages = list(evidence_packages or [])
        self.evaluation_tasks = list(evaluation_tasks or [])
        self.stock_master = list(stock_master or [])
        self.stock_statuses = list(stock_statuses or [])
        self.feature_snapshots = list(feature_snapshots or [])

    def load_focus_states(self) -> List[FocusState]:
        return _latest_active_focus_states(self.focus_states)

    def load_daily_recommendations(self, trade_date: date) -> List[Recommendation]:
        return [item for item in self.recommendations if item.trade_date == trade_date]

    def load_focus_states_for_date(self, trade_date: date) -> List[FocusState]:
        return [item for item in self.focus_states if item.trade_date == trade_date]

    def load_evidence_packages(self, trade_date: date) -> List[EvidencePackage]:
        return [item for item in self.evidence_packages if item.trade_date == trade_date]

    def save_stock_master(self, stocks: List[StockSnapshot]) -> None:
        self.stock_master = _upsert_model_list(
            self.stock_master,
            stocks,
            key=lambda item: item.ts_code,
        )

    def save_stock_statuses(self, stocks: List[StockSnapshot]) -> None:
        self.stock_statuses = _upsert_model_list(
            self.stock_statuses,
            stocks,
            key=lambda item: (item.trade_date, item.ts_code),
        )

    def save_feature_snapshots(self, features: List[FeatureSnapshot]) -> None:
        self.feature_snapshots = _upsert_model_list(
            self.feature_snapshots,
            features,
            key=lambda item: (item.trade_date, item.ts_code),
        )

    def save_recommendations(self, recommendations: List[Recommendation]) -> None:
        self.recommendations.extend(recommendations)

    def save_focus_states(self, states: List[FocusState]) -> None:
        self.focus_states.extend(states)

    def save_evidence_packages(self, packages: List[EvidencePackage]) -> None:
        self.evidence_packages.extend(packages)

    def save_evaluation_tasks(self, tasks: List[EvaluationTask]) -> None:
        self.evaluation_tasks.extend(tasks)


class SupabaseAnalysisRepository:
    def __init__(self, client) -> None:
        self.client = client

    def load_focus_states(self) -> List[FocusState]:
        result = self.client.table("focus_watchlist_state").select("*").execute()
        states = [_focus_state_from_row(row) for row in result.data or []]
        return _latest_active_focus_states(states)

    def load_daily_recommendations(self, trade_date: date) -> List[Recommendation]:
        result = (
            self.client.table("recommendation_daily")
            .select("*, stock_master(name)")
            .eq("trade_date", trade_date.isoformat())
            .execute()
        )
        return [_recommendation_from_row(row) for row in result.data or []]

    def load_focus_states_for_date(self, trade_date: date) -> List[FocusState]:
        result = (
            self.client.table("focus_watchlist_state")
            .select("*")
            .eq("trade_date", trade_date.isoformat())
            .execute()
        )
        return [_focus_state_from_row(row) for row in result.data or []]

    def load_evidence_packages(self, trade_date: date) -> List[EvidencePackage]:
        result = (
            self.client.table("evidence_package_index")
            .select("*")
            .eq("trade_date", trade_date.isoformat())
            .execute()
        )
        return [_evidence_package_from_row(row) for row in result.data or []]

    def save_stock_master(self, stocks: List[StockSnapshot]) -> None:
        rows_by_code = {
            item.ts_code: {
                "ts_code": item.ts_code,
                "name": item.name,
                "exchange": _exchange_from_ts_code(item.ts_code),
                "list_date": None,
            }
            for item in stocks
        }
        rows = list(rows_by_code.values())
        if rows:
            self.client.table("stock_master").upsert(rows).execute()

    def save_stock_statuses(self, stocks: List[StockSnapshot]) -> None:
        rows = [
            {
                "trade_date": item.trade_date.isoformat(),
                "ts_code": item.ts_code,
                "is_st": item.is_st,
                "is_suspended": item.is_suspended,
                "has_delisting_risk": item.has_delisting_risk,
                "listing_days": item.listing_days,
                "turnover_rate": item.turnover_rate,
                "amount": item.amount,
                "official_risk_events": item.official_risk_events,
            }
            for item in stocks
        ]
        if rows:
            self.client.table("stock_status_daily").upsert(rows).execute()

    def save_feature_snapshots(self, features: List[FeatureSnapshot]) -> None:
        rows = [
            {
                "trade_date": item.trade_date.isoformat(),
                "ts_code": item.ts_code,
                "features": item.model_dump(
                    mode="json",
                    exclude={"trade_date", "ts_code"},
                ),
                "rule_hits": [],
                "data_quality": item.data_quality,
            }
            for item in features
        ]
        if rows:
            self.client.table("daily_feature_snapshot").upsert(rows).execute()

    def save_recommendations(self, recommendations: List[Recommendation]) -> None:
        if not recommendations:
            return
        rows = [
            {
                "trade_date": item.trade_date.isoformat(),
                "ts_code": item.ts_code,
                "action": item.action.value,
                "score": item.score,
                "reasons": item.reasons,
                "risks": item.risks,
                "evidence_id": item.evidence_id or _default_evidence_id(item),
            }
            for item in recommendations
        ]
        self.client.table("recommendation_daily").insert(rows).execute()

    def save_focus_states(self, states: List[FocusState]) -> None:
        if not states:
            return
        rows = [
            {
                "trade_date": item.trade_date.isoformat(),
                "ts_code": item.ts_code,
                "state": item.state.value,
                "entry_date": _date_to_text(item.entry_date),
                "entry_reason": item.entry_reason,
                "invalidation_conditions": item.invalidation_conditions,
                "exit_reason": item.exit_reason,
            }
            for item in states
        ]
        self.client.table("focus_watchlist_state").insert(rows).execute()

    def save_evidence_packages(self, packages: List[EvidencePackage]) -> None:
        if not packages:
            return
        rows = [_evidence_package_to_row(package) for package in packages]
        self.client.table("evidence_package_index").insert(rows).execute()

    def save_evaluation_tasks(self, tasks: List[EvaluationTask]) -> None:
        if not tasks:
            return
        rows = [
            {
                "trade_date": item.trade_date.isoformat(),
                "ts_code": item.ts_code,
                "evidence_id": item.evidence_id,
                "checkpoint_days": item.checkpoint_days,
                "due_date": item.due_date.isoformat(),
                "evaluation_layer": item.evaluation_layer,
            }
            for item in tasks
        ]
        self.client.table("evaluation_task").insert(rows).execute()


def _date_from_row(value) -> Optional[date]:
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(value)


def _date_to_text(value: Optional[date]) -> Optional[str]:
    return value.isoformat() if value else None


def _focus_state_from_row(row: dict) -> FocusState:
    return FocusState(
        trade_date=_date_from_row(row["trade_date"]),
        ts_code=row["ts_code"],
        state=ActionLabel(row["state"]),
        entry_date=_date_from_row(row.get("entry_date")),
        entry_reason=row.get("entry_reason"),
        invalidation_conditions=list(row.get("invalidation_conditions") or []),
        exit_reason=row.get("exit_reason"),
    )


def _recommendation_from_row(row: dict) -> Recommendation:
    stock_master = row.get("stock_master") or {}
    return Recommendation(
        trade_date=_date_from_row(row["trade_date"]),
        ts_code=row["ts_code"],
        name=row.get("name") or stock_master.get("name") or row["ts_code"],
        action=ActionLabel(row["action"]),
        score=float(row["score"]),
        reasons=list(row.get("reasons") or []),
        risks=list(row.get("risks") or []),
        evidence_id=row.get("evidence_id"),
    )


def _evidence_package_from_row(row: dict) -> EvidencePackage:
    return EvidencePackage(
        evidence_id=row["evidence_id"],
        trade_date=_date_from_row(row["trade_date"]),
        ts_code=row["ts_code"],
        thesis=row["thesis"],
        support=list(row.get("support") or []),
        counter_evidence=list(row.get("counter_evidence") or []),
        matched_rules=list(row.get("matched_rules") or []),
        confidence_level=row["confidence_level"],
        expected_confirmation_path=list(row.get("expected_confirmation_path") or []),
        invalidation_conditions=list(row.get("invalidation_conditions") or []),
        source_versions=dict(row.get("source_versions") or {}),
    )


def _latest_active_focus_states(states: List[FocusState]) -> List[FocusState]:
    latest_by_code: dict[str, FocusState] = {}
    for state in states:
        current = latest_by_code.get(state.ts_code)
        if current is None or state.trade_date >= current.trade_date:
            latest_by_code[state.ts_code] = state
    return [
        state
        for state in sorted(latest_by_code.values(), key=lambda item: item.ts_code)
        if state.state
        not in {ActionLabel.EXIT_OBSERVATION, ActionLabel.INSUFFICIENT_DATA}
    ]


def _default_evidence_id(item: Recommendation) -> str:
    return f"{item.trade_date.isoformat()}-{item.ts_code}"


def _exchange_from_ts_code(ts_code: str) -> str:
    if "." not in ts_code:
        return ""
    return ts_code.rsplit(".", 1)[1]


def _upsert_model_list(existing: List, incoming: List, key) -> List:
    by_key = {key(item): item for item in existing}
    for item in incoming:
        by_key[key(item)] = item
    return list(by_key.values())


def _evidence_package_to_row(package: EvidencePackage) -> dict:
    payload = package.model_dump(mode="json")
    payload_text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return {
        "evidence_id": package.evidence_id,
        "trade_date": package.trade_date.isoformat(),
        "ts_code": package.ts_code,
        "storage_path": f"evidence/{package.trade_date.isoformat()}/{package.evidence_id}.json",
        "sha256": hashlib.sha256(payload_text.encode("utf-8")).hexdigest(),
        "thesis": package.thesis,
        "support": package.support,
        "counter_evidence": package.counter_evidence,
        "matched_rules": package.matched_rules,
        "confidence_level": package.confidence_level,
        "expected_confirmation_path": package.expected_confirmation_path,
        "invalidation_conditions": package.invalidation_conditions,
        "source_versions": package.source_versions,
    }
