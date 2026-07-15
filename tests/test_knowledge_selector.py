from datetime import date
from pathlib import Path

from stock_analyzer.knowledge.capability import CapabilityItem, CapabilitySnapshot
from stock_analyzer.knowledge.governance_models import (
    AnalysisContext,
    AnalysisModule,
    DataRequirement,
    KnowledgeEffect,
    KnowledgeEntry,
    KnowledgeRegistry,
    KnowledgeTopic,
    LocalValidation,
    OpportunityType,
    SourceGrade,
    SourceKind,
    SourceRecord,
)
from stock_analyzer.knowledge.selector import select_knowledge
from stock_analyzer.knowledge.registry import load_knowledge_registry


ANALYSIS_DATE = date(2026, 7, 14)


def source() -> SourceRecord:
    return SourceRecord(
        source_id="official-disclosure-source",
        grade=SourceGrade.S,
        kind=SourceKind.OFFICIAL_DISCLOSURE,
        title="Official disclosure source",
        publisher="上海证券交易所",
        url="https://www.sse.com.cn/lawandrules/sselawsrules/",
        publication_date=date(2024, 1, 1),
        last_verified_on=date(2026, 7, 15),
        jurisdiction="中国大陆",
        market_scope=("A股",),
        method_summary="Provides time-valid official facts and disclosure boundaries.",
        limitations=("Company-specific facts still require a dated disclosure.",),
    )


def requirement(
    name: str = "equity_daily", *, kind: str = "fact"
) -> tuple[DataRequirement, ...]:
    return (
        DataRequirement(
            kind=kind,
            name=name,
            required_fields=(
                ("analysis_date", "value")
                if kind == "derived"
                else ("available_at", "close")
            ),
        ),
    )


def entry(
    knowledge_id: str,
    module: AnalysisModule,
    opportunity_type: OpportunityType,
    topic: KnowledgeTopic,
    *,
    effect: KnowledgeEffect = KnowledgeEffect.OBSERVATION_ONLY,
    requirements: tuple[DataRequirement, ...] | None = None,
    version_status: str = "current",
    effective_from: date | None = None,
    effective_to: date | None = None,
) -> KnowledgeEntry:
    return KnowledgeEntry(
        knowledge_id=knowledge_id,
        title=knowledge_id,
        primary_source_id="official-disclosure-source",
        source_grade=SourceGrade.S,
        version_status=version_status,
        effective_from=effective_from,
        effective_to=effective_to,
        effect=effect,
        modules=(module,),
        opportunity_types=(opportunity_type,),
        topics=(topic,),
        claim_summary=f"Governed claim for {knowledge_id}.",
        allowed_uses=("Use only in the matched analysis scene.",),
        forbidden_uses=("Do not turn it into a score or rank.",),
        prerequisites=("The required local capability is complete.",),
        counter_evidence=("Time-valid contradictory evidence.",),
        data_requirements=requirements or requirement(),
        local_validation=LocalValidation(
            status="not_required",
            reason="Fixture contains no empirical threshold.",
        ),
    )


def registry() -> KnowledgeRegistry:
    entries = (
        entry(
            "market-method",
            AnalysisModule.MARKET_ENVIRONMENT,
            OpportunityType.GENERAL,
            KnowledgeTopic.MARKET_PRICE_PERSISTENCE,
            effect=KnowledgeEffect.METHOD_ONLY,
        ),
        entry(
            "hotspot-method",
            AnalysisModule.SECTOR_THEME,
            OpportunityType.INDUSTRY_TREND,
            KnowledgeTopic.SECTOR_PRICE_PERSISTENCE,
            effect=KnowledgeEffect.METHOD_ONLY,
        ),
        entry(
            "company-business-transmission",
            AnalysisModule.COMPANY_BUSINESS,
            OpportunityType.INDUSTRY_TREND,
            KnowledgeTopic.BUSINESS_TRANSMISSION,
        ),
        entry(
            "earnings-method",
            AnalysisModule.EVENTS,
            OpportunityType.EARNINGS_RERATING,
            KnowledgeTopic.EARNINGS_DRIFT,
            effect=KnowledgeEffect.METHOD_ONLY,
        ),
        entry(
            "blocked-cycle-method",
            AnalysisModule.FUNDAMENTALS,
            OpportunityType.CYCLE_INFLECTION,
            KnowledgeTopic.CYCLE_SUPPLY_DEMAND,
            effect=KnowledgeEffect.METHOD_ONLY,
            requirements=requirement("industry_inventory", kind="derived"),
        ),
        entry(
            "exchange-risk-boundary",
            AnalysisModule.RISK,
            OpportunityType.GENERAL,
            KnowledgeTopic.EXCHANGE_CONSTRAINTS,
            effect=KnowledgeEffect.HARD_BOUNDARY,
        ),
    )
    return KnowledgeRegistry(
        schema_version="v3-knowledge-governance-v1",
        generated_on=date(2026, 7, 15),
        sources=(source(),),
        entries=entries,
        registry_hash="registry-hash",
    )


def capabilities() -> CapabilitySnapshot:
    return CapabilitySnapshot(
        analysis_date=ANALYSIS_DATE,
        items=(
            CapabilityItem(
                kind="fact",
                name="equity_daily",
                fields=("available_at", "close"),
                partition_count=100,
                row_count=1000,
                quality_statuses=("passed",),
                as_of_supported=True,
                structurally_ready=True,
            ),
        ),
        snapshot_hash="snapshot-hash",
    )


def context(
    module: AnalysisModule,
    opportunity_type: OpportunityType,
    topic: KnowledgeTopic,
    *,
    analysis_date: date = ANALYSIS_DATE,
) -> AnalysisContext:
    return AnalysisContext(
        analysis_date=analysis_date,
        module=module,
        opportunity_type=opportunity_type,
        required_topics=(topic,),
        question="Which governed knowledge is applicable to this scene?",
    )


def selected_ids(selections) -> tuple[str, ...]:
    return tuple(selection.knowledge_id for selection in selections)


def test_selector_filters_by_module_opportunity_topic_and_10_30_session_horizon():
    matched = entry(
        "matched-company-business",
        AnalysisModule.COMPANY_BUSINESS,
        OpportunityType.INDUSTRY_TREND,
        KnowledgeTopic.BUSINESS_TRANSMISSION,
    )
    wrong_horizon = entry(
        "wrong-horizon",
        AnalysisModule.COMPANY_BUSINESS,
        OpportunityType.INDUSTRY_TREND,
        KnowledgeTopic.BUSINESS_TRANSMISSION,
    ).model_copy(
        update={"horizon_min_sessions": 20, "horizon_center_sessions": 20}
    )
    fixture = registry().model_copy(
        update={"entries": registry().entries + (matched, wrong_horizon,)}
    )

    selections = select_knowledge(
        fixture,
        context(
            AnalysisModule.COMPANY_BUSINESS,
            OpportunityType.INDUSTRY_TREND,
            KnowledgeTopic.BUSINESS_TRANSMISSION,
        ),
        capabilities(),
    )

    assert selected_ids(selections) == (
        "company-business-transmission",
        "matched-company-business",
    )


def test_selector_uses_rule_version_valid_on_analysis_date():
    old = entry(
        "exchange-rule-old",
        AnalysisModule.RISK,
        OpportunityType.GENERAL,
        KnowledgeTopic.EXCHANGE_CONSTRAINTS,
        effect=KnowledgeEffect.HARD_BOUNDARY,
        version_status="superseded",
        effective_from=date(2024, 1, 1),
        effective_to=date(2025, 12, 31),
    )
    new = entry(
        "exchange-rule-new",
        AnalysisModule.RISK,
        OpportunityType.GENERAL,
        KnowledgeTopic.EXCHANGE_CONSTRAINTS,
        effect=KnowledgeEffect.HARD_BOUNDARY,
        effective_from=date(2026, 1, 1),
    )
    fixture = registry().model_copy(update={"entries": (new, old)})

    before = select_knowledge(
        fixture,
        context(
            AnalysisModule.RISK,
            OpportunityType.GENERAL,
            KnowledgeTopic.EXCHANGE_CONSTRAINTS,
            analysis_date=date(2025, 12, 1),
        ),
        capabilities(),
    )
    after = select_knowledge(
        fixture,
        context(
            AnalysisModule.RISK,
            OpportunityType.GENERAL,
            KnowledgeTopic.EXCHANGE_CONSTRAINTS,
            analysis_date=date(2026, 7, 1),
        ),
        capabilities(),
    )

    assert selected_ids(before) == ("exchange-rule-old",)
    assert selected_ids(after) == ("exchange-rule-new",)


def test_selector_never_returns_historical_only_entry():
    historical = entry(
        "retired-company-business",
        AnalysisModule.COMPANY_BUSINESS,
        OpportunityType.INDUSTRY_TREND,
        KnowledgeTopic.BUSINESS_TRANSMISSION,
        version_status="historical_only",
    )
    fixture = registry().model_copy(update={"entries": (historical,)})

    selections = select_knowledge(
        fixture,
        context(
            AnalysisModule.COMPANY_BUSINESS,
            OpportunityType.INDUSTRY_TREND,
            KnowledgeTopic.BUSINESS_TRANSMISSION,
        ),
        capabilities(),
    )

    assert selections == ()


def test_selector_excludes_blocked_knowledge_instead_of_returning_all_entries():
    selections = select_knowledge(
        registry(),
        context(
            AnalysisModule.FUNDAMENTALS,
            OpportunityType.CYCLE_INFLECTION,
            KnowledgeTopic.CYCLE_SUPPLY_DEMAND,
        ),
        capabilities(),
    )

    assert selections == ()


def test_selector_returns_method_only_empirical_research_without_promoting_it():
    selections = select_knowledge(
        registry(),
        context(
            AnalysisModule.EVENTS,
            OpportunityType.EARNINGS_RERATING,
            KnowledgeTopic.EARNINGS_DRIFT,
        ),
        capabilities(),
    )

    assert selected_ids(selections) == ("earnings-method",)
    assert selections[0].effect is KnowledgeEffect.METHOD_ONLY


def test_selector_is_deterministic_and_has_no_score_or_weight_field():
    fixture = registry()
    reversed_fixture = fixture.model_copy(
        update={"entries": tuple(reversed(fixture.entries))}
    )
    scene = context(
        AnalysisModule.COMPANY_BUSINESS,
        OpportunityType.INDUSTRY_TREND,
        KnowledgeTopic.BUSINESS_TRANSMISSION,
    )

    first = select_knowledge(fixture, scene, capabilities())
    second = select_knowledge(reversed_fixture, scene, capabilities())

    assert [item.model_dump() for item in first] == [
        item.model_dump() for item in second
    ]
    for item in first:
        assert "score" not in type(item).model_fields
        assert "weight" not in type(item).model_fields


def test_no_matching_knowledge_returns_empty_tuple_with_no_fallback():
    selections = select_knowledge(
        registry(),
        context(
            AnalysisModule.VALUATION,
            OpportunityType.TURNAROUND,
            KnowledgeTopic.VALUATION_METHOD,
        ),
        capabilities(),
    )

    assert selections == ()


def test_real_empirical_selection_keeps_method_only_effect_and_exact_ids():
    fixture = load_knowledge_registry(
        Path("src/stock_analyzer/knowledge/research_registry.yaml")
    )
    requirements: dict[tuple[str, str], set[str]] = {}
    for entry_item in fixture.entries:
        for required in entry_item.data_requirements:
            requirements.setdefault((required.kind, required.name), set()).update(
                required.required_fields
            )
    snapshot = CapabilitySnapshot(
        analysis_date=ANALYSIS_DATE,
        items=tuple(
            CapabilityItem(
                kind=kind,
                name=name,
                fields=tuple(sorted(fields)),
                partition_count=1,
                row_count=1,
                quality_statuses=("complete",),
                as_of_supported=True,
                structurally_ready=True,
            )
            for (kind, name), fields in sorted(requirements.items())
        ),
        snapshot_hash="real-registry-selector-fixture",
    )
    scene = context(
        AnalysisModule.EVENTS,
        OpportunityType.EARNINGS_RERATING,
        KnowledgeTopic.EVENT_PRICE_REACTION,
    )

    selections = select_knowledge(fixture, scene, snapshot)

    assert selected_ids(selections) == (
        "src_brown_warner_1985",
        "src_sun_wen_earnings_car_2023",
    )
    assert all(item.effect is KnowledgeEffect.METHOD_ONLY for item in selections)
