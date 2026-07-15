from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from .capability import (
    CapabilityAssessment,
    CapabilitySnapshot,
    assess_entry_capability,
)
from .governance_models import (
    AnalysisContext,
    CapabilityStatus,
    KnowledgeEffect,
    KnowledgeRegistry,
    OpportunityType,
    SourceGrade,
)


class KnowledgeSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    knowledge_id: str
    source_grade: SourceGrade
    effect: KnowledgeEffect
    selection_reasons: tuple[str, ...]
    capability: CapabilityAssessment


def _effective_on(entry, analysis_date) -> bool:
    if entry.effective_from is not None and analysis_date < entry.effective_from:
        return False
    if entry.effective_to is not None and analysis_date > entry.effective_to:
        return False
    return True


def _horizon_contains_context(entry, context: AnalysisContext) -> bool:
    return (
        entry.horizon_min_sessions <= context.horizon_min_sessions
        and entry.horizon_min_sessions
        <= context.horizon_center_sessions
        <= entry.horizon_max_sessions
        and context.horizon_max_sessions <= entry.horizon_max_sessions
    )


def select_knowledge(
    registry: KnowledgeRegistry,
    context: AnalysisContext,
    capabilities: CapabilitySnapshot,
) -> tuple[KnowledgeSelection, ...]:
    selections: list[KnowledgeSelection] = []
    for entry in registry.entries:
        if not _effective_on(entry, context.analysis_date):
            continue
        if context.module not in entry.modules:
            continue
        opportunity_matches = (
            OpportunityType.GENERAL in entry.opportunity_types
            or context.opportunity_type in entry.opportunity_types
        )
        if not opportunity_matches:
            continue
        matched_topics = tuple(
            sorted(
                set(context.required_topics).intersection(entry.topics),
                key=lambda topic: topic.value,
            )
        )
        if context.required_topics and not matched_topics:
            continue
        if not _horizon_contains_context(entry, context):
            continue
        capability = assess_entry_capability(entry, capabilities)
        if capability.status is not CapabilityStatus.COMPLETE:
            continue

        opportunity_reason = (
            OpportunityType.GENERAL.value
            if OpportunityType.GENERAL in entry.opportunity_types
            else context.opportunity_type.value
        )
        selections.append(
            KnowledgeSelection(
                knowledge_id=entry.knowledge_id,
                source_grade=entry.source_grade,
                effect=entry.effect,
                selection_reasons=(
                    f"version effective on {context.analysis_date.isoformat()}",
                    f"module matched: {context.module.value}",
                    f"opportunity matched: {opportunity_reason}",
                    "topics matched: "
                    + ", ".join(topic.value for topic in matched_topics),
                    "horizon covered: "
                    f"{context.horizon_min_sessions}/"
                    f"{context.horizon_center_sessions}/"
                    f"{context.horizon_max_sessions} sessions",
                    "capability complete",
                ),
                capability=capability,
            )
        )
    return tuple(sorted(selections, key=lambda item: item.knowledge_id))


__all__ = ["KnowledgeSelection", "select_knowledge"]
