from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict

from stock_analyzer.domain.models import EvidenceModule


UsageStatus = Literal[
    "v1_used",
    "hard_constraint",
    "partial",
    "future_enhancement",
    "observation_only",
]
RuleType = Literal[
    "hard_constraint",
    "explanation",
    "counter_evidence",
    "method_guard",
    "observation",
]
NextAction = Literal[
    "use_now",
    "add_data_source",
    "keep_for_future",
    "downgrade",
    "consider_removal",
]


class StrategyKnowledgeEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    knowledge_id: str
    title: str
    usage_status: UsageStatus
    module: EvidenceModule
    rule_type: RuleType
    data_exists: bool
    affects_core_analysis: bool
    unused_reason: str | None = None
    next_action: NextAction


def load_strategy_knowledge_map(path: Path) -> list[StrategyKnowledgeEntry]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [StrategyKnowledgeEntry.model_validate(item) for item in payload["entries"]]


def entries_for_module(
    entries: list[StrategyKnowledgeEntry],
    module: EvidenceModule,
) -> list[StrategyKnowledgeEntry]:
    return [entry for entry in entries if entry.module == module]
