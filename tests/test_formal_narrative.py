from __future__ import annotations

import hashlib

import pytest

from stock_analyzer.ops.formal_narrative import (
    FormalNarrative,
    MarketNarrative,
    NarrativePoint,
    StockNarrative,
    build_stock_analysis_requests,
    validate_formal_narrative,
)
from stock_analyzer.ops.formal_strategy_runtime import analyze_formal_inputs
from stock_analyzer.storage.repositories import InMemoryAnalysisRepository
from tests.test_formal_materializer import CODES
from tests.test_formal_strategy_runtime import (
    candidate_set,
    complete_payloads,
    ready_receipt,
)


def _payload():
    return analyze_formal_inputs(
        ready_receipt(),
        candidate_set(ordered=(CODES[-1],), active=(CODES[0],)),
        complete_payloads((CODES[-1], CODES[0])),
        InMemoryAnalysisRepository(),
    ).value


def _valid_narrative(payload) -> FormalNarrative:
    stocks = []
    for request in build_stock_analysis_requests(payload):
        lock = request.decision_lock
        point = NarrativePoint(
            text="现有证据支持继续按既定条件观察。",
            evidence_ids=[request.evidence_id],
        )
        stocks.append(
            StockNarrative(
                ts_code=request.ts_code,
                evidence_id=request.evidence_id,
                narrative_marker=(
                    "NARRATIVE-"
                    + hashlib.sha256(request.evidence_id.encode("utf-8"))
                    .hexdigest()[:12]
                    .upper()
                ),
                analysis_summary=point,
                core_reasons=[point, point, point],
                action=lock.action,
                position_min_pct=lock.position_min_pct,
                position_max_pct=lock.position_max_pct,
                risk_if_wrong=lock.risk_if_wrong,
                required_confirmation=lock.required_confirmation,
                observation_conditions=lock.observation_conditions,
                invalidation_conditions=lock.invalidation_conditions,
                exit_conditions=lock.exit_conditions,
                five_day_progress=[],
            )
        )
    return FormalNarrative(
        market=MarketNarrative(
            summary="市场结论只概括已验证的市场背景。",
            evidence_ids=sorted(item.evidence_id for item in stocks),
        ),
        stocks=stocks,
    )


def test_requests_are_deduplicated_and_contain_only_their_stock_evidence():
    payload = _payload()

    requests = build_stock_analysis_requests(payload)

    assert [item.ts_code for item in requests] == [CODES[-1], CODES[0]]
    first = requests[0].model_dump_json()
    second = requests[1].model_dump_json()
    assert CODES[0] not in first
    assert CODES[-1] not in second
    assert requests[0].is_daily_recommendation is True
    assert requests[1].is_focus_stock is True


def test_valid_narrative_requires_exactly_three_reasons_per_stock():
    payload = _payload()
    narrative = _valid_narrative(payload)

    assert validate_formal_narrative(payload, narrative) == narrative

    invalid = narrative.stocks[0].model_dump(mode="json")
    invalid["core_reasons"] = invalid["core_reasons"][:2]
    with pytest.raises(ValueError, match="at least 3 items"):
        StockNarrative.model_validate(invalid)


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("action", "小仓试探"),
        ("position_max_pct", 90.0),
        ("risk_if_wrong", "没有风险"),
        ("required_confirmation", ["无条件买入"]),
        ("invalidation_conditions", ["永不失效"]),
        ("exit_conditions", ["不退出"]),
    ],
)
def test_narrative_cannot_mutate_strategy_decision(field, replacement):
    payload = _payload()
    narrative = _valid_narrative(payload)
    changed_stock = narrative.stocks[0].model_copy(update={field: replacement})
    changed = narrative.model_copy(
        update={"stocks": [changed_stock, *narrative.stocks[1:]]}
    )

    with pytest.raises(ValueError, match="decision lock"):
        validate_formal_narrative(payload, changed)


def test_narrative_rejects_foreign_evidence_id():
    payload = _payload()
    narrative = _valid_narrative(payload)
    foreign_point = NarrativePoint(
        text="引用了另一只股票的证据。",
        evidence_ids=[narrative.stocks[1].evidence_id],
    )
    changed_stock = narrative.stocks[0].model_copy(
        update={"core_reasons": [foreign_point, *narrative.stocks[0].core_reasons[1:]]}
    )
    changed = narrative.model_copy(
        update={"stocks": [changed_stock, *narrative.stocks[1:]]}
    )

    with pytest.raises(ValueError, match="evidence whitelist"):
        validate_formal_narrative(payload, changed)


def test_narrative_rejects_new_numeric_fact_even_with_allowed_evidence():
    payload = _payload()
    narrative = _valid_narrative(payload)
    invented_price = NarrativePoint(
        text="目标价为 99.99 元。",
        evidence_ids=[narrative.stocks[0].evidence_id],
    )
    changed_stock = narrative.stocks[0].model_copy(
        update={
            "core_reasons": [
                invented_price,
                *narrative.stocks[0].core_reasons[1:],
            ]
        }
    )
    changed = narrative.model_copy(
        update={"stocks": [changed_stock, *narrative.stocks[1:]]}
    )

    with pytest.raises(ValueError, match="numeric whitelist"):
        validate_formal_narrative(payload, changed)
