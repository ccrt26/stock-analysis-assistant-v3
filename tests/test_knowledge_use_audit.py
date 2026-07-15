from datetime import date

import pytest
from pydantic import ValidationError

from stock_analyzer.knowledge.governance_models import (
    KnowledgeUseRecord,
    KnowledgeUseStatus,
    SourceGrade,
)
from stock_analyzer.knowledge.use_audit import build_program_trading_use_record
from stock_analyzer.knowledge.usage_policy import MarketMicrostructureWordingError


def record_payload() -> dict:
    return {
        "knowledge_id": "governed-knowledge",
        "source_grade": SourceGrade.S,
        "registry_hash": "registry-hash",
        "analysis_date": date(2026, 7, 14),
        "status": KnowledgeUseStatus.CORRECT,
        "status_reason": "All required steps and data were present.",
        "selection_reason": "The knowledge matched this analysis scene.",
        "api_fact_refs": ("equity_daily:600000.SH:2026-07-14",),
        "local_observation_refs": (
            "stock_trading_context:600000.SH:2026-07-14",
        ),
        "model_judgment": "The observable evidence supports only this bounded view.",
        "user_expression": "可观察事实支持该有限结论。",
    }


def test_correct_execution_cannot_have_missing_data_or_omitted_steps():
    for field, value in (
        ("missing_data", ("company disclosure",)),
        ("omitted_steps", ("counter-evidence review",)),
    ):
        payload = record_payload()
        payload[field] = value
        with pytest.raises(ValidationError, match="correct_execution"):
            KnowledgeUseRecord.model_validate(payload)


def test_limited_execution_requires_entity_or_date_specific_limitation():
    payload = record_payload()
    payload["status"] = KnowledgeUseStatus.LIMITED
    with pytest.raises(ValidationError, match="limited_execution"):
        KnowledgeUseRecord.model_validate(payload)

    payload["limitations"] = (
        "该公司在分析日尚未披露本期主营业务分部数据。",
    )
    record = KnowledgeUseRecord.model_validate(payload)
    assert record.status is KnowledgeUseStatus.LIMITED


def test_insufficient_execution_requires_an_omitted_required_step():
    payload = record_payload()
    payload["status"] = KnowledgeUseStatus.INSUFFICIENT
    with pytest.raises(ValidationError, match="insufficient_execution"):
        KnowledgeUseRecord.model_validate(payload)

    payload["omitted_steps"] = ("Counter-evidence review was skipped.",)
    record = KnowledgeUseRecord.model_validate(payload)
    assert record.status is KnowledgeUseStatus.INSUFFICIENT


def test_data_insufficient_or_not_applicable_requires_a_reason():
    payload = record_payload()
    payload["status"] = KnowledgeUseStatus.DATA_INSUFFICIENT_OR_NOT_APPLICABLE
    payload["status_reason"] = " "
    with pytest.raises(ValidationError, match="status_reason"):
        KnowledgeUseRecord.model_validate(payload)


def test_conflict_can_coexist_with_correct_execution():
    payload = record_payload()
    payload["conflicts_with"] = ("second-rule",)
    record = KnowledgeUseRecord.model_validate(payload)

    assert record.status is KnowledgeUseStatus.CORRECT
    assert record.conflicts_with == ("second-rule",)


def test_all_four_trace_layers_are_separate_required_fields():
    for field in (
        "api_fact_refs",
        "local_observation_refs",
        "model_judgment",
        "user_expression",
    ):
        payload = record_payload()
        del payload[field]
        with pytest.raises(ValidationError, match=field):
            KnowledgeUseRecord.model_validate(payload)


@pytest.mark.parametrize(
    "text",
    [
        "上涨放量，说明机构买入。",
        "成交放大，主力没有出货。",
        "收在高位，游资正在拉升。",
    ],
)
def test_daily_or_minute_facts_cannot_claim_trader_identity(text):
    with pytest.raises(MarketMicrostructureWordingError):
        build_program_trading_use_record(
            text=text,
            analysis_date=date(2026, 7, 14),
            api_fact_refs=("equity_daily:600000.SH:2026-07-14",),
            local_observation_refs=(
                "stock_trading_context:600000.SH:2026-07-14",
            ),
        )


def test_observable_result_wording_is_allowed():
    record = build_program_trading_use_record(
        text="当日成交放大并收在日内较高位置，但现有数据不能识别交易主体。",
        analysis_date=date(2026, 7, 14),
        api_fact_refs=("equity_daily:600000.SH:2026-07-14",),
        local_observation_refs=("stock_trading_context:600000.SH:2026-07-14",),
    )
    assert record.status is KnowledgeUseStatus.CORRECT
    assert record.hard_boundary_triggered is True
