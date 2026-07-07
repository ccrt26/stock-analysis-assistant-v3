from __future__ import annotations

from typing import List, Protocol

from stock_analyzer.domain.models import (
    EvaluationTask,
    EvidencePackage,
    FocusState,
    Recommendation,
)


class AnalysisRepository(Protocol):
    def save_recommendations(self, recommendations: List[Recommendation]) -> None: ...
    def save_focus_states(self, states: List[FocusState]) -> None: ...
    def save_evidence_packages(self, packages: List[EvidencePackage]) -> None: ...
    def save_evaluation_tasks(self, tasks: List[EvaluationTask]) -> None: ...


class InMemoryAnalysisRepository:
    def __init__(self) -> None:
        self.recommendations: List[Recommendation] = []
        self.focus_states: List[FocusState] = []
        self.evidence_packages: List[EvidencePackage] = []
        self.evaluation_tasks: List[EvaluationTask] = []

    def save_recommendations(self, recommendations: List[Recommendation]) -> None:
        self.recommendations.extend(recommendations)

    def save_focus_states(self, states: List[FocusState]) -> None:
        self.focus_states.extend(states)

    def save_evidence_packages(self, packages: List[EvidencePackage]) -> None:
        self.evidence_packages.extend(packages)

    def save_evaluation_tasks(self, tasks: List[EvaluationTask]) -> None:
        self.evaluation_tasks.extend(tasks)
