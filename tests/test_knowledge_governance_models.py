from datetime import date

import pytest
from pydantic import ValidationError

from stock_analyzer.knowledge.governance_models import (
    AnalysisContext,
    AnalysisModule,
    DataRequirement,
    KnowledgeEffect,
    KnowledgeEntry,
    KnowledgeRegistry,
    KnowledgeTopic,
    KnowledgeUseRecord,
    KnowledgeUseStatus,
    LocalValidation,
    OpportunityType,
    ResearchDesign,
    SourceGrade,
    SourceKind,
    SourceRecord,
)


def valid_s_source() -> SourceRecord:
    return SourceRecord(
        source_id="official-program-trading",
        grade=SourceGrade.S,
        kind=SourceKind.OFFICIAL_RULE,
        title="证券市场程序化交易管理规定（试行）",
        publisher="中国证券监督管理委员会",
        url="https://www.csrc.gov.cn/csrc/c100028/c7480577/content.shtml",
        publication_date=date(2024, 5, 15),
        effective_from=date(2024, 10, 8),
        last_verified_on=date(2026, 7, 15),
        jurisdiction="中国大陆",
        market_scope=("A股",),
        method_summary="规定程序化交易报告、监测和风险管理边界。",
        limitations=("规则不能识别具体成交账户身份。",),
    )


def valid_a_source() -> SourceRecord:
    return SourceRecord(
        source_id="peer-reviewed-momentum",
        grade=SourceGrade.A,
        kind=SourceKind.PEER_REVIEWED_PAPER,
        title="A peer-reviewed A-share method",
        publisher="Journal publisher",
        authors=("Researcher One", "Researcher Two"),
        journal_or_series="Journal of Evidence",
        url="https://publisher.example.org/article/123",
        doi="10.1000/example-doi",
        publication_date=date(2024, 1, 1),
        last_verified_on=date(2026, 7, 15),
        jurisdiction="中国大陆",
        market_scope=("A股",),
        sample_start=date(2005, 1, 1),
        sample_end=date(2022, 12, 31),
        method_summary="Uses point-in-time portfolios to estimate price persistence.",
        limitations=("The published threshold has not been validated locally.",),
    )


def valid_requirement() -> DataRequirement:
    return DataRequirement(
        kind="fact",
        name="equity_daily",
        required_fields=("trade_date", "ts_code", "close", "available_at"),
    )


def valid_entry(**changes: object) -> KnowledgeEntry:
    payload = {
        "knowledge_id": "src-cn-program-trading-rules-2025",
        "title": "程序化交易表达边界",
        "primary_source_id": "official-program-trading",
        "source_grade": SourceGrade.S,
        "version_status": "current",
        "effective_from": date(2024, 10, 8),
        "effect": KnowledgeEffect.HARD_BOUNDARY,
        "modules": (AnalysisModule.PRICE_TRADING, AnalysisModule.RISK),
        "opportunity_types": (OpportunityType.GENERAL,),
        "topics": (KnowledgeTopic.TRADER_IDENTITY_BOUNDARY,),
        "horizon_min_sessions": 10,
        "horizon_center_sessions": 20,
        "horizon_max_sessions": 30,
        "claim_summary": "Daily price and volume do not identify a trading account.",
        "allowed_uses": ("Describe observable price and volume outcomes.",),
        "forbidden_uses": ("Infer institutions or major players from bars.",),
        "prerequisites": ("Use only time-valid market facts.",),
        "counter_evidence": ("Order-level account-labelled evidence.",),
        "data_requirements": (valid_requirement(),),
        "local_validation": LocalValidation(
            status="not_required",
            reason="This is an official expression boundary, not an empirical threshold.",
        ),
    }
    payload.update(changes)
    return KnowledgeEntry.model_validate(payload)


def valid_use_record(**changes: object) -> KnowledgeUseRecord:
    payload = {
        "knowledge_id": "src-cn-program-trading-rules-2025",
        "source_grade": SourceGrade.S,
        "registry_hash": "abc123",
        "analysis_date": date(2026, 7, 14),
        "status": KnowledgeUseStatus.CORRECT,
        "status_reason": "The boundary was fully applied.",
        "selection_reason": "Price and trading structure is being analysed.",
        "api_fact_refs": ("equity_daily:600000.SH:2026-07-14",),
        "local_observation_refs": (
            "stock_trading_context:600000.SH:2026-07-14",
        ),
        "model_judgment": "The observations do not establish trader identity.",
        "user_expression": "成交放大，但现有数据不能识别交易主体。",
    }
    payload.update(changes)
    return KnowledgeUseRecord.model_validate(payload)


def test_s_official_rule_requires_effective_date_and_official_host():
    payload = valid_s_source().model_dump()
    payload["effective_from"] = None
    with pytest.raises(ValidationError, match="effective_from"):
        SourceRecord.model_validate(payload)

    payload = valid_s_source().model_dump()
    payload["url"] = "https://example.com/repost"
    with pytest.raises(ValidationError, match="official host"):
        SourceRecord.model_validate(payload)


def test_s_official_accounting_standard_accepts_only_exact_mof_host():
    payload = valid_s_source().model_dump()
    payload.update(
        {
            "source_id": "official-mof-cas-35",
            "title": "企业会计准则第35号——分部报告",
            "publisher": "中华人民共和国财政部",
            "url": (
                "https://kjs.mof.gov.cn/zt/kjzzss/kuaijizhunzeshishi/"
                "200806/t20080618_46246.htm"
            ),
            "publication_date": date(2006, 2, 15),
            "effective_from": date(2007, 1, 1),
        }
    )

    source = SourceRecord.model_validate(payload)

    assert source.url.host == "kjs.mof.gov.cn"
    payload["url"] = "https://mof-gov.example.com/cas35"
    with pytest.raises(ValidationError, match="official host"):
        SourceRecord.model_validate(payload)


@pytest.mark.parametrize("effect", ["hard_boundary", "analysis_evidence"])
def test_b_source_cannot_create_hard_boundary_or_analysis_evidence(effect):
    with pytest.raises(ValidationError, match="B source"):
        valid_entry(
            knowledge_id="bad-b-rule",
            primary_source_id="working-paper",
            source_grade=SourceGrade.B,
            effect=effect,
        )


def test_a_paper_requires_authors_method_market_and_sample_metadata():
    for field, invalid in (
        ("authors", ()),
        ("method_summary", " "),
        ("market_scope", ()),
        ("sample_start", None),
        ("sample_end", None),
    ):
        payload = valid_a_source().model_dump()
        payload[field] = invalid
        with pytest.raises(ValidationError):
            SourceRecord.model_validate(payload)


def test_theoretical_a_source_does_not_fake_sample_dates():
    payload = valid_a_source().model_dump()
    payload.update(
        research_design="theoretical",
        sample_start=None,
        sample_end=None,
        limitations=(
            "This source is theoretical and claims no empirical A-share result.",
        ),
    )

    source = SourceRecord.model_validate(payload)

    assert source.research_design is ResearchDesign.THEORETICAL


def test_empirical_a_source_still_requires_sample_dates():
    payload = valid_a_source().model_dump()
    payload.update(sample_start=None, sample_end=None)

    with pytest.raises(ValidationError, match="sample"):
        SourceRecord.model_validate(payload)


def test_supplement_topics_are_available():
    expected = {
        "market_state_reliability",
        "return_dispersion",
        "liquidity_trading_activity",
        "profitability_quality",
        "risk_overextension",
        "earnings_disclosure_hierarchy",
        "margin_financing",
        "pledge_conditional_risk",
        "disclosed_holder_trade",
        "portfolio_relationship",
    }

    assert expected <= {topic.value for topic in KnowledgeTopic}


def test_empirical_threshold_requires_completed_local_validation():
    source = valid_a_source()
    with pytest.raises(ValidationError, match="local validation"):
        valid_entry(
            knowledge_id="unvalidated-empirical-threshold",
            title="Unvalidated empirical threshold",
            primary_source_id=source.source_id,
            source_grade=SourceGrade.A,
            effect=KnowledgeEffect.ANALYSIS_EVIDENCE,
            modules=(AnalysisModule.PRICE_TRADING,),
            opportunity_types=(OpportunityType.GENERAL,),
            topics=(KnowledgeTopic.MARKET_PRICE_PERSISTENCE,),
            data_requirements=(
                valid_requirement(),
                DataRequirement(
                    kind="derived",
                    name="stock_trading_context",
                    required_fields=("ts_code", "analysis_date", "return_20d"),
                ),
            ),
            local_validation=LocalValidation(
                status="required_before_threshold",
                reason="The published threshold has not been validated locally.",
            ),
        )


def test_approved_horizon_is_exactly_10_20_30_sessions():
    with pytest.raises(ValidationError, match="10/20/30"):
        valid_entry(horizon_center_sessions=21)

    with pytest.raises(ValidationError, match="10/20/30"):
        AnalysisContext(
            analysis_date=date(2026, 7, 14),
            module=AnalysisModule.PRICE_TRADING,
            opportunity_type=OpportunityType.GENERAL,
            required_topics=(KnowledgeTopic.MARKET_PRICE_PERSISTENCE,),
            question="未来二至六周的价格条件是什么？",
            horizon_min_sessions=10,
            horizon_center_sessions=20,
            horizon_max_sessions=31,
        )


def test_current_entry_requires_data_and_current_official_rule_has_open_end():
    with pytest.raises(ValidationError, match="data_requirements"):
        valid_entry(data_requirements=())

    historical_source = valid_s_source().model_copy(
        update={"effective_to": date(2025, 6, 30)}
    )
    with pytest.raises(ValidationError, match="current official rule"):
        KnowledgeRegistry(
            schema_version="v3-knowledge-governance-v1",
            generated_on=date(2026, 7, 15),
            sources=(historical_source,),
            entries=(valid_entry(),),
        )


def test_models_reject_blank_tuple_items_extra_fields_and_mutation():
    with pytest.raises(ValidationError, match="blank"):
        valid_entry(allowed_uses=(" ",))

    payload = valid_s_source().model_dump()
    payload["unexpected"] = "not allowed"
    with pytest.raises(ValidationError, match="Extra inputs"):
        SourceRecord.model_validate(payload)

    source = valid_s_source()
    with pytest.raises(ValidationError):
        source.title = "changed"


def test_knowledge_use_record_enforces_four_status_invariants():
    with pytest.raises(ValidationError, match="correct_execution"):
        valid_use_record(missing_data=("company disclosure",))
    with pytest.raises(ValidationError, match="correct_execution"):
        valid_use_record(omitted_steps=("counter-evidence review",))
    with pytest.raises(ValidationError, match="limited_execution"):
        valid_use_record(status=KnowledgeUseStatus.LIMITED)
    with pytest.raises(ValidationError, match="insufficient_execution"):
        valid_use_record(status=KnowledgeUseStatus.INSUFFICIENT)
    with pytest.raises(ValidationError, match="status_reason"):
        valid_use_record(
            status=KnowledgeUseStatus.DATA_INSUFFICIENT_OR_NOT_APPLICABLE,
            status_reason=" ",
        )


def test_conflict_is_independent_of_correct_execution_status():
    record = valid_use_record(conflicts_with=("second-rule",))
    assert record.status is KnowledgeUseStatus.CORRECT
    assert record.conflicts_with == ("second-rule",)
