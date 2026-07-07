from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel


class KnowledgeRule(BaseModel):
    rule_id: str
    source_reference: str
    source_grade: Literal["S", "A", "B"]
    rule_type: Literal["hard_constraint", "explanation", "counter_evidence", "evaluation"]
    applicable_scenarios: list[str]
    forbidden_scenarios: list[str]
    data_requirements: list[str]
    report_phrasing: str
    evaluation_method: str
    downgrade_conditions: list[str]


def load_rules(path: Path) -> list[KnowledgeRule]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [KnowledgeRule.model_validate(item) for item in payload["rules"]]
