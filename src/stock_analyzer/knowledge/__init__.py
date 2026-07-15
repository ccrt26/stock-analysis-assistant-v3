"""Knowledge rule models and seed configuration."""

from stock_analyzer.analysis.knowledge_map import (
    StrategyKnowledgeEntry,
    entries_for_module,
    load_strategy_knowledge_map,
)

from .rule_schema import KnowledgeRule, load_rules
from .capability import assess_entry_capability, inspect_warehouse_capabilities
from .registry import load_knowledge_registry, load_legacy_migration
from .selector import select_knowledge


def __getattr__(name: str):
    if name == "audit_knowledge_governance":
        from .governance_audit import audit_knowledge_governance

        return audit_knowledge_governance
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "KnowledgeRule",
    "StrategyKnowledgeEntry",
    "assess_entry_capability",
    "audit_knowledge_governance",
    "entries_for_module",
    "inspect_warehouse_capabilities",
    "load_rules",
    "load_knowledge_registry",
    "load_legacy_migration",
    "load_strategy_knowledge_map",
    "select_knowledge",
]
