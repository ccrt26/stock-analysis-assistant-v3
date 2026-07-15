import ast
from datetime import date
from pathlib import Path
import subprocess
import sys

import pytest

import stock_analyzer.knowledge as knowledge_package
from stock_analyzer.knowledge.capability import (
    CapabilityItem,
    CapabilitySnapshot,
    assess_entry_capability,
)
from stock_analyzer.knowledge.governance_models import (
    AnalysisContext,
    AnalysisModule,
    DataRequirement,
    KnowledgeEffect,
    KnowledgeEntry,
    KnowledgeTopic,
    KnowledgeUseRecord,
    KnowledgeUseStatus,
    LocalValidation,
    OpportunityType,
)
from stock_analyzer.knowledge.registry import load_knowledge_registry
from stock_analyzer.knowledge.selector import select_knowledge
from stock_analyzer.knowledge.use_audit import build_program_trading_use_record
from stock_analyzer.knowledge.usage_policy import MarketMicrostructureWordingError


REGISTRY_PATH = Path("src/stock_analyzer/knowledge/research_registry.yaml")
ANALYSIS_DATE = date(2026, 7, 14)
EXPECTED_SCENARIO_SELECTIONS = {
    "program_trading_boundary": ("src_cn_program_trading_rules_2025",),
    "market_environment": (
        "src_cn_factor_momentum_2023",
        "src_cn_price_limit_momentum_2025",
        "src_cn_t1_contrarian_2024",
    ),
    "sector_hotspot": (
        "src_cn_factor_momentum_2023",
        "src_moskowitz_grinblatt_1999",
    ),
    "company_business": ("src_csrc_disclosure_rules_2025",),
    "earnings_event": (
        "src_brown_warner_1985",
        "src_chan_2003",
        "src_sun_wen_earnings_car_2023",
    ),
    "unavailable_cycle_data": (),
}


def test_frozen_governance_interfaces_are_exported_without_activation():
    assert all(
        callable(getattr(knowledge_package, name, None))
        for name in (
            "inspect_warehouse_capabilities",
            "assess_entry_capability",
            "select_knowledge",
            "audit_knowledge_governance",
        )
    )


def test_governance_audit_module_is_not_preimported_by_package():
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "stock_analyzer.knowledge.governance_audit",
            "--help",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "found in sys.modules after import of package" not in result.stderr


def complete_capabilities(registry=None) -> CapabilitySnapshot:
    registry = registry or load_knowledge_registry(REGISTRY_PATH)
    requirements: dict[tuple[str, str], set[str]] = {}
    for entry in registry.entries:
        if entry.version_status != "current":
            continue
        for requirement in entry.data_requirements:
            requirements.setdefault((requirement.kind, requirement.name), set()).update(
                requirement.required_fields
            )
    return CapabilitySnapshot(
        analysis_date=ANALYSIS_DATE,
        items=tuple(
            CapabilityItem(
                kind=kind,
                name=name,
                fields=tuple(sorted(fields)),
                partition_count=1,
                row_count=1,
                formula_versions=(
                    ("sector-hotspot-v2",)
                    if name == "sector_hotspot"
                    else (("acceptance-fixture-v1",) if kind == "derived" else ())
                ),
                quality_statuses=("complete",),
                as_of_supported=True,
                structurally_ready=True,
            )
            for (kind, name), fields in sorted(requirements.items())
        ),
        snapshot_hash="governance-acceptance-capabilities",
    )


def context(
    module: AnalysisModule,
    opportunity_type: OpportunityType,
    topics: tuple[KnowledgeTopic, ...],
) -> AnalysisContext:
    return AnalysisContext(
        analysis_date=ANALYSIS_DATE,
        module=module,
        opportunity_type=opportunity_type,
        required_topics=topics,
        question="只选择当前场景适用且现有数据可执行的知识。",
    )


def selected_ids(registry, scene, capabilities=None) -> tuple[str, ...]:
    selected = select_knowledge(
        registry,
        scene,
        capabilities or complete_capabilities(registry),
    )
    return tuple(item.knowledge_id for item in selected)


def test_program_trading_boundary_selects_and_enforces_wording():
    registry = load_knowledge_registry(REGISTRY_PATH)
    scene = context(
        AnalysisModule.PRICE_TRADING,
        OpportunityType.GENERAL,
        (KnowledgeTopic.TRADER_IDENTITY_BOUNDARY,),
    )

    assert selected_ids(registry, scene) == EXPECTED_SCENARIO_SELECTIONS[
        "program_trading_boundary"
    ]
    with pytest.raises(MarketMicrostructureWordingError):
        build_program_trading_use_record(
            text="成交放大，说明机构买入。",
            analysis_date=ANALYSIS_DATE,
            api_fact_refs=("equity_daily:600000.SH:2026-07-14",),
            local_observation_refs=(
                "stock_trading_context:600000.SH:2026-07-14",
            ),
        )

    record = build_program_trading_use_record(
        text="当日成交放大并收在日内较高位置，但现有数据不能识别交易主体。",
        analysis_date=ANALYSIS_DATE,
        api_fact_refs=("equity_daily:600000.SH:2026-07-14",),
        local_observation_refs=(
            "stock_trading_context:600000.SH:2026-07-14",
        ),
    )
    assert record.status is KnowledgeUseStatus.CORRECT


def test_market_environment_returns_methods_without_score_rank_or_action():
    registry = load_knowledge_registry(REGISTRY_PATH)
    scene = context(
        AnalysisModule.MARKET_ENVIRONMENT,
        OpportunityType.GENERAL,
        (KnowledgeTopic.MARKET_PRICE_PERSISTENCE,),
    )

    selected = select_knowledge(registry, scene, complete_capabilities(registry))

    assert tuple(item.knowledge_id for item in selected) == (
        EXPECTED_SCENARIO_SELECTIONS["market_environment"]
    )
    assert all(
        item.effect in {KnowledgeEffect.METHOD_ONLY, KnowledgeEffect.ANALYSIS_EVIDENCE}
        for item in selected
    )
    assert all(
        not hasattr(item, forbidden)
        for item in selected
        for forbidden in ("score", "rank", "action")
    )
    assert all("10/20/30 sessions" in item.selection_reasons[-2] for item in selected)


def test_sector_hotspot_remains_evidence_not_ranking():
    registry = load_knowledge_registry(REGISTRY_PATH)
    scene = context(
        AnalysisModule.SECTOR_THEME,
        OpportunityType.INDUSTRY_TREND,
        (KnowledgeTopic.SECTOR_PRICE_PERSISTENCE,),
    )
    capabilities = complete_capabilities(registry)

    selected = select_knowledge(registry, scene, capabilities)
    hotspot = capabilities.lookup("derived", "sector_hotspot")

    assert tuple(item.knowledge_id for item in selected) == (
        EXPECTED_SCENARIO_SELECTIONS["sector_hotspot"]
    )
    assert hotspot is not None
    assert hotspot.formula_versions == ("sector-hotspot-v2",)
    assert all(
        item.effect in {KnowledgeEffect.METHOD_ONLY, KnowledgeEffect.ANALYSIS_EVIDENCE}
        for item in selected
    )
    assert all(not hasattr(item, "rank") for item in selected)
    factor_source = next(
        source
        for source in registry.sources
        if source.source_id == "paper-ma-liao-jiang-factor-momentum-2024"
    )
    assert any("不能直接生成热点排名" in text for text in factor_source.limitations)


def test_company_business_requires_main_business_evidence():
    registry = load_knowledge_registry(REGISTRY_PATH)
    scene = context(
        AnalysisModule.COMPANY_BUSINESS,
        OpportunityType.INDUSTRY_TREND,
        (KnowledgeTopic.BUSINESS_TRANSMISSION,),
    )
    complete = complete_capabilities(registry)

    assert selected_ids(registry, scene, complete) == EXPECTED_SCENARIO_SELECTIONS[
        "company_business"
    ]
    without_main_business = complete.model_copy(
        update={
            "items": tuple(
                item
                for item in complete.items
                if not (item.kind == "fact" and item.name == "main_business")
            )
        }
    )
    assert selected_ids(registry, scene, without_main_business) == ()


def test_earnings_event_preserves_four_trace_layers():
    registry = load_knowledge_registry(REGISTRY_PATH)
    scene = context(
        AnalysisModule.EVENTS,
        OpportunityType.EARNINGS_RERATING,
        (KnowledgeTopic.EVENT_PRICE_REACTION,),
    )

    assert selected_ids(registry, scene) == EXPECTED_SCENARIO_SELECTIONS[
        "earnings_event"
    ]
    record = KnowledgeUseRecord(
        knowledge_id="src_sun_wen_earnings_car_2023",
        source_grade="A",
        registry_hash=registry.registry_hash,
        analysis_date=ANALYSIS_DATE,
        status=KnowledgeUseStatus.CORRECT,
        status_reason="公告时点、行情和估值字段完整，所需步骤均已执行。",
        selection_reason="业绩重估场景与事件价格反应主题匹配。",
        api_fact_refs=("announcement:600000.SH:2026-07-12",),
        local_observation_refs=("event_return:600000.SH:2026-07-14",),
        model_judgment="公告后相对表现提供重估线索，但不保证继续上涨。",
        user_expression="业绩公告后表现强于市场，仍需等待后续价格和基本面确认。",
    )
    layers = (
        record.api_fact_refs,
        record.local_observation_refs,
        record.model_judgment,
        record.user_expression,
    )
    assert len({repr(layer) for layer in layers}) == 4


def test_unavailable_cycle_data_is_blocked_and_not_selected():
    registry = load_knowledge_registry(REGISTRY_PATH)
    source = next(
        item
        for item in registry.sources
        if item.source_id == "paper-ma-liao-jiang-factor-momentum-2024"
    )
    blocked_entry = KnowledgeEntry(
        knowledge_id="synthetic_cycle_inventory_method",
        title="Synthetic blocked cycle method",
        primary_source_id=source.source_id,
        source_grade=source.grade,
        version_status="current",
        effect=KnowledgeEffect.METHOD_ONLY,
        modules=(AnalysisModule.SECTOR_THEME,),
        opportunity_types=(OpportunityType.CYCLE_INFLECTION,),
        topics=(KnowledgeTopic.CYCLE_SUPPLY_DEMAND,),
        claim_summary="Only a test method for structurally missing cycle data.",
        allowed_uses=("Test capability admission only.",),
        forbidden_uses=("Do not produce a stock conclusion.",),
        prerequisites=("Require governed inventory observations.",),
        counter_evidence=("Inventory capability is unavailable.",),
        data_requirements=(
            DataRequirement(
                kind="derived",
                name="industry_inventory",
                required_fields=("analysis_date", "inventory_change"),
            ),
        ),
        local_validation=LocalValidation(
            status="required_before_threshold",
            reason="Synthetic method has no local validation.",
        ),
    )
    registry_with_blocked = registry.model_copy(
        update={"entries": (*registry.entries, blocked_entry)}
    )
    capabilities = complete_capabilities(registry)
    scene = context(
        AnalysisModule.SECTOR_THEME,
        OpportunityType.CYCLE_INFLECTION,
        (KnowledgeTopic.CYCLE_SUPPLY_DEMAND,),
    )

    assert assess_entry_capability(blocked_entry, capabilities).status.value == "blocked"
    assert selected_ids(registry_with_blocked, scene, capabilities) == (
        EXPECTED_SCENARIO_SELECTIONS["unavailable_cycle_data"]
    )


def test_governance_package_has_no_network_or_ingestion_dependency():
    module_paths = (
        Path("src/stock_analyzer/knowledge/governance_models.py"),
        Path("src/stock_analyzer/knowledge/registry.py"),
        Path("src/stock_analyzer/knowledge/capability.py"),
        Path("src/stock_analyzer/knowledge/selector.py"),
        Path("src/stock_analyzer/knowledge/use_audit.py"),
        Path("src/stock_analyzer/knowledge/governance_audit.py"),
    )
    forbidden_parts = {
        "httpx",
        "requests",
        "urllib",
        "socket",
        "acquisition",
        "backfill",
    }

    for path in module_paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        assert not {
            name
            for name in imported
            if forbidden_parts.intersection(name.split("."))
        }, (path, imported)


def test_governance_is_not_imported_by_production_paths():
    roots = (
        Path("src/stock_analyzer/analysis"),
        Path("src/stock_analyzer/ops"),
        Path("src/stock_analyzer/reports"),
    )
    paths = [Path("src/stock_analyzer/pipeline.py"), Path("src/stock_analyzer/cli.py")]
    for root in roots:
        paths.extend(sorted(root.rglob("*.py")))

    forbidden = ("research_registry", "select_knowledge", "governance_audit")
    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert not any(token in text for token in forbidden), path
