from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from stock_analyzer.analysis.knowledge_map import load_strategy_knowledge_map
from stock_analyzer.knowledge.rule_schema import load_rules


class DecisionLock(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    action: str
    position_min_pct: float
    position_max_pct: float
    risk_if_wrong: str
    required_confirmation: list[str]
    observation_conditions: list[str]
    invalidation_conditions: list[str]
    exit_conditions: list[str]


class FocusProgressDay(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    trade_date: str
    evidence_id: str
    thesis: str
    action: str
    supportive: bool


class StockAnalysisRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    ts_code: str
    name: str
    evidence_id: str
    is_daily_recommendation: bool
    is_focus_stock: bool
    evidence: dict[str, Any]
    allowed_evidence_ids: list[str]
    knowledge_refs: list[str]
    knowledge_context: list[dict[str, Any]]
    explicit_gaps: list[str]
    focus_history: list[FocusProgressDay]
    decision_lock: DecisionLock


class NarrativePoint(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str = Field(min_length=1, max_length=600)
    evidence_ids: list[str] = Field(min_length=1)


class StockNarrative(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    ts_code: str
    evidence_id: str
    narrative_marker: str = Field(pattern=r"^NARRATIVE-[A-F0-9]{12}$")
    analysis_summary: NarrativePoint
    core_reasons: list[NarrativePoint] = Field(min_length=3, max_length=3)
    action: str
    position_min_pct: float
    position_max_pct: float
    risk_if_wrong: str
    required_confirmation: list[str]
    observation_conditions: list[str]
    invalidation_conditions: list[str]
    exit_conditions: list[str]
    five_day_progress: list[NarrativePoint]


class MarketNarrative(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    summary: str = Field(min_length=1, max_length=1200)
    evidence_ids: list[str] = Field(min_length=1)


class FormalNarrative(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    market: MarketNarrative
    stocks: list[StockNarrative]


def build_stock_analysis_requests(payload: Any) -> tuple[StockAnalysisRequest, ...]:
    cards = {item.ts_code: item for item in payload.recommendation_cards}
    focus_codes = {
        item.ts_code
        for item in (
            *payload.focus_states,
            *payload.focus_entry_theses,
            *payload.focus_daily_updates,
        )
    }
    focus_codes.update(
        item.ts_code
        for item in payload.strategy_snapshots
        if item.ts_code not in cards
    )
    snapshot_by_code = {item.ts_code: item for item in payload.strategy_snapshots}
    packages_by_code = {item.ts_code: item for item in payload.evidence_packages}
    ordered_codes = list(cards)
    ordered_codes.extend(
        item.ts_code
        for item in payload.strategy_snapshots
        if item.ts_code in focus_codes and item.ts_code not in cards
    )
    requests: list[StockAnalysisRequest] = []
    for code in ordered_codes:
        snapshot = snapshot_by_code[code]
        package = packages_by_code[code]
        card = cards.get(code)
        action = snapshot.action
        atom_ids = [
            atom.id
            for module in snapshot.modules
            for atom in (*module.support, *module.counter)
        ]
        knowledge_refs = sorted(
            {
                knowledge_id
                for module in snapshot.modules
                for atom in (*module.support, *module.counter)
                for knowledge_id in atom.knowledge_rule_ids
            }
        )
        explicit_gaps = sorted(
            {
                field
                for module in snapshot.modules
                for requirement in module.data_requirements
                for field in requirement.missing_fields
            }
        )
        observation_conditions = list(
            card.needed_before_focus_entry
            if card is not None and card.needed_before_focus_entry
            else action.required_confirmation
        )
        focus_history = [
            FocusProgressDay(
                trade_date=item.trade_date.isoformat(),
                evidence_id=item.evidence_id,
                thesis=item.thesis,
                action=item.action.decision.value,
                supportive=(
                    not item.data_insufficient
                    and item.action.position_max_pct > 0
                ),
            )
            for item in payload.focus_history_by_code.get(code, [])
        ]
        requests.append(
            StockAnalysisRequest(
                ts_code=code,
                name=snapshot.name,
                evidence_id=package.evidence_id,
                is_daily_recommendation=code in cards,
                is_focus_stock=code in focus_codes,
                evidence={
                    "thesis": snapshot.thesis,
                    "modules": [
                        module.model_dump(mode="json") for module in snapshot.modules
                    ],
                },
                allowed_evidence_ids=[
                    package.evidence_id,
                    *atom_ids,
                    *(item.evidence_id for item in focus_history),
                ],
                knowledge_refs=knowledge_refs,
                knowledge_context=[
                    _knowledge_catalog().get(
                        knowledge_id,
                        {
                            "knowledge_id": knowledge_id,
                            "coverage": "reference_only",
                        },
                    )
                    for knowledge_id in knowledge_refs
                ],
                explicit_gaps=explicit_gaps,
                focus_history=focus_history,
                decision_lock=DecisionLock(
                    action=action.decision.value,
                    position_min_pct=action.position_min_pct,
                    position_max_pct=action.position_max_pct,
                    risk_if_wrong=action.risk_if_wrong,
                    required_confirmation=list(action.required_confirmation),
                    observation_conditions=observation_conditions,
                    invalidation_conditions=list(action.invalidation_conditions),
                    exit_conditions=list(action.invalidation_conditions),
                ),
            )
        )
    return tuple(requests)


def validate_formal_narrative(payload: Any, narrative: FormalNarrative) -> FormalNarrative:
    requests = build_stock_analysis_requests(payload)
    expected_codes = [item.ts_code for item in requests]
    actual_codes = [item.ts_code for item in narrative.stocks]
    if actual_codes != expected_codes:
        raise ValueError("formal narrative stock set does not match formal payload")
    request_by_code = {item.ts_code: item for item in requests}
    for stock in narrative.stocks:
        request = request_by_code[stock.ts_code]
        if stock.evidence_id != request.evidence_id:
            raise ValueError("formal narrative evidence whitelist mismatch")
        lock = request.decision_lock
        locked_fields = (
            "action",
            "position_min_pct",
            "position_max_pct",
            "risk_if_wrong",
            "required_confirmation",
            "observation_conditions",
            "invalidation_conditions",
            "exit_conditions",
        )
        if any(getattr(stock, field) != getattr(lock, field) for field in locked_fields):
            raise ValueError("formal narrative violates the Strategy V2 decision lock")
        allowed = set(request.allowed_evidence_ids)
        points = [stock.analysis_summary, *stock.core_reasons, *stock.five_day_progress]
        if any(set(point.evidence_ids) - allowed for point in points):
            raise ValueError("formal narrative evidence whitelist mismatch")
        allowed_numbers = _numeric_tokens(
            request.model_dump_json(exclude={"knowledge_context"})
        )
        for point in points:
            if _numeric_tokens(point.text) - allowed_numbers:
                raise ValueError("formal narrative numeric whitelist mismatch")
    all_package_ids = {item.evidence_id for item in requests}
    if set(narrative.market.evidence_ids) - all_package_ids:
        raise ValueError("market narrative evidence whitelist mismatch")
    return narrative


def _numeric_tokens(value: str) -> set[str]:
    return set(re.findall(r"(?<![A-Za-z0-9_.])\d+(?:\.\d+)?%?", value))


@lru_cache(maxsize=1)
def _knowledge_catalog() -> dict[str, dict[str, Any]]:
    knowledge_root = Path(__file__).resolve().parents[1] / "knowledge"
    catalog = {
        entry.knowledge_id: entry.model_dump(mode="json")
        for entry in load_strategy_knowledge_map(
            knowledge_root / "strategy_v2_map.yaml"
        )
    }
    for rule in load_rules(knowledge_root / "rules.seed.yaml"):
        catalog[rule.rule_id] = {
            "knowledge_id": rule.rule_id,
            **rule.model_dump(mode="json", exclude={"rule_id"}),
        }
    return catalog


__all__ = [
    "DecisionLock",
    "FocusProgressDay",
    "FormalNarrative",
    "MarketNarrative",
    "NarrativePoint",
    "StockAnalysisRequest",
    "StockNarrative",
    "build_stock_analysis_requests",
    "validate_formal_narrative",
]
