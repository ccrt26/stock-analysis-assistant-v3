from collections import Counter
from pathlib import Path
import re

import yaml

from stock_analyzer.analysis.knowledge_map import (
    entries_for_module,
    load_strategy_knowledge_map,
)
from stock_analyzer.domain.models import EvidenceModule
from stock_analyzer.knowledge import StrategyKnowledgeEntry


REPO_ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = REPO_ROOT / "src" / "stock_analyzer" / "knowledge" / "strategy_v2_map.yaml"
ARCH_PATH = (
    REPO_ROOT
    / "docs"
    / "superpowers"
    / "specs"
    / "2026-07-10-v3-phase-3-strategy-v2-architecture.html"
)


def _architecture_source_ids() -> list[str]:
    html = ARCH_PATH.read_text(encoding="utf-8")
    return re.findall(r"\bsrc_[a-z0-9_]+\b", html)


def _raw_map_ids() -> list[str]:
    payload = yaml.safe_load(MAP_PATH.read_text(encoding="utf-8"))
    return [item["knowledge_id"] for item in payload["entries"]]


def test_strategy_knowledge_map_loads_required_core_entries():
    entries = load_strategy_knowledge_map(MAP_PATH)
    by_id = {entry.knowledge_id: entry for entry in entries}

    assert isinstance(entries[0], StrategyKnowledgeEntry)
    assert by_id["src_sse_rules_portal"].rule_type == "hard_constraint"
    assert by_id["src_jegadeesh_titman_1993"].module == EvidenceModule.TREND_VOLUME
    assert by_id["src_markowitz_1952"].module == EvidenceModule.RISK_COUNTER
    assert by_id["src_brown_warner_1985"].rule_type == "method_guard"
    assert by_id["src_piotroski_2000"].usage_status == "future_enhancement"
    assert by_id["src_short_disclose_distort_2024"].usage_status == "observation_only"


def test_each_six_module_has_at_least_one_v1_used_or_hard_constraint_entry():
    entries = load_strategy_knowledge_map(MAP_PATH)

    for module in EvidenceModule:
        module_entries = entries_for_module(entries, module)
        assert any(
            item.usage_status in {"v1_used", "hard_constraint", "partial"}
            for item in module_entries
        ), module.value


def test_entries_for_module_returns_only_matching_entries_in_map_order():
    entries = load_strategy_knowledge_map(MAP_PATH)

    trend_entries = entries_for_module(entries, EvidenceModule.TREND_VOLUME)

    assert trend_entries
    assert all(entry.module == EvidenceModule.TREND_VOLUME for entry in trend_entries)
    assert [entry.knowledge_id for entry in trend_entries] == [
        entry.knowledge_id
        for entry in entries
        if entry.module == EvidenceModule.TREND_VOLUME
    ]


def test_architecture_ids_are_represented_exactly_once_in_machine_readable_map():
    architecture_ids = _architecture_source_ids()
    mapped_ids = _raw_map_ids()

    assert len(architecture_ids) == len(set(architecture_ids))
    assert Counter(mapped_ids) == Counter(architecture_ids)
    assert load_strategy_knowledge_map(MAP_PATH)


def test_deferred_entries_are_intentionally_labeled_with_reason_and_next_action():
    entries = load_strategy_knowledge_map(MAP_PATH)
    deferred_entries = [
        entry
        for entry in entries
        if entry.usage_status in {"future_enhancement", "observation_only"}
    ]

    assert deferred_entries
    assert all(entry.unused_reason for entry in deferred_entries)
    assert all(
        entry.next_action in {"add_data_source", "keep_for_future", "consider_removal"}
        for entry in deferred_entries
    )
