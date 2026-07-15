from __future__ import annotations

from datetime import date

from .governance_models import (
    KnowledgeUseRecord,
    KnowledgeUseStatus,
    SourceGrade,
)
from .usage_policy import (
    PROGRAM_TRADING_KNOWLEDGE_ID,
    validate_market_microstructure_wording,
)


def build_program_trading_use_record(
    *,
    text: str,
    analysis_date: date,
    api_fact_refs: tuple[str, ...],
    local_observation_refs: tuple[str, ...],
    registry_hash: str = "standalone-program-trading-boundary",
) -> KnowledgeUseRecord:
    record = KnowledgeUseRecord(
        knowledge_id=PROGRAM_TRADING_KNOWLEDGE_ID,
        source_grade=SourceGrade.S,
        registry_hash=registry_hash,
        analysis_date=analysis_date,
        status=KnowledgeUseStatus.CORRECT,
        status_reason=(
            "The no-trader-identity inference boundary was fully applied."
        ),
        selection_reason=(
            "Daily or minute price-volume observations are being translated "
            "into a user-facing expression."
        ),
        api_fact_refs=api_fact_refs,
        local_observation_refs=local_observation_refs,
        model_judgment=(
            "The referenced market observations describe trading results but "
            "do not identify institutions, major players, hot money or accounts."
        ),
        user_expression=text,
        hard_boundary_triggered=True,
    )
    validate_market_microstructure_wording(
        record.user_expression,
        level2_available=False,
    )
    return record


__all__ = ["build_program_trading_use_record"]
