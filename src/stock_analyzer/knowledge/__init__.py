"""Knowledge registry, selection, and capability interfaces."""

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
    "assess_entry_capability",
    "audit_knowledge_governance",
    "inspect_warehouse_capabilities",
    "load_rules",
    "load_knowledge_registry",
    "load_legacy_migration",
    "select_knowledge",
]
