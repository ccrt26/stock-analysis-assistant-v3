from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import List, Optional, Protocol

from stock_analyzer.domain.models import (
    ActionLabel,
    EvaluationTask,
    EvidencePackage,
    FocusState,
    Recommendation,
)


class AnalysisRepository(Protocol):
    def load_focus_states(self) -> List[FocusState]: ...
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
    ) -> None:
        self.recommendations = list(recommendations or [])
        self.focus_states = list(focus_states or [])
        self.evidence_packages = list(evidence_packages or [])
        self.evaluation_tasks = list(evaluation_tasks or [])

    def load_focus_states(self) -> List[FocusState]:
        return list(self.focus_states)

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
        return [_focus_state_from_row(row) for row in result.data or []]

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


def _default_evidence_id(item: Recommendation) -> str:
    return f"{item.trade_date.isoformat()}-{item.ts_code}"


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
