from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta

from stock_analyzer.analysis.focus import FormalFocusDay
from stock_analyzer.analysis.strategy_v2 import generate_strategy_v2_recommendations
from stock_analyzer.data.formal_materializer import materialize_market_inputs
from stock_analyzer.data.readiness import FormalRunState
from stock_analyzer.domain.models import ActionDecision, ActionLabel, FocusState
from stock_analyzer.ops.formal_run import CandidateSet
from stock_analyzer.ops.formal_strategy_runtime import (
    _prior_five_sessions,
    analyze_formal_inputs,
)
from stock_analyzer.storage.repositories import InMemoryAnalysisRepository
from tests.test_formal_materializer import (
    CODES,
    TARGET,
    receipt,
    screening_payloads,
    target_payloads,
)


def candidate_set(ordered=(CODES[-1],), active=(CODES[0],)) -> CandidateSet:
    return CandidateSet(
        candidate_set_id="candidate-set-1",
        run_id="formal-2026-07-10",
        ordered_codes=tuple(ordered),
        active_focus_codes=tuple(active),
        screening_version="strategy-v2-screen-v1",
        upstream_input_set_id="input-set-1",
        content_hash="candidate-content-hash",
    )


def ready_receipt():
    return receipt().model_copy(
        update={
            "state": FormalRunState.ANALYZING,
            "candidate_set_id": "candidate-set-1",
        }
    )


def complete_payloads(codes=(CODES[-1], CODES[0])):
    return {**screening_payloads(), **target_payloads(tuple(codes))}


def _prior_snapshots(code: str, days: list[date]):
    current_inputs = materialize_market_inputs(TARGET, screening_payloads())
    feature = current_inputs.feature_profiles[code]
    snapshots = []
    for day in days:
        snapshots.append(
            generate_strategy_v2_recommendations(
                features=[
                    feature.model_copy(
                        update={"trade_date": day, "liquidity_score": 1.0}
                    )
                ],
                stock_names={code: code},
                trade_date=day,
            ).snapshots[0]
        )
    return snapshots


def test_formal_analysis_uses_only_frozen_candidates_and_active_focus_codes():
    output = analyze_formal_inputs(
        ready_receipt(),
        candidate_set(),
        complete_payloads(),
        InMemoryAnalysisRepository(),
    )

    payload = output.value
    allowed = {CODES[-1], CODES[0]}
    assert {item.ts_code for item in payload.strategy_snapshots} == allowed
    assert {item.ts_code for item in payload.recommendations} == {CODES[-1]}
    assert all(row["ts_code"] in allowed for row in output.ledger_rows if "ts_code" in row)


def test_formal_analysis_loads_exact_five_formal_days_and_breaks_on_blocked_day():
    prior_days = [TARGET - timedelta(days=value) for value in (7, 4, 3, 2, 1)]
    formal_days = [
        FormalFocusDay(
            trade_date=value,
            formally_committed=True,
            blocked=index == 2,
        )
        for index, value in enumerate(prior_days)
    ]
    repository = InMemoryAnalysisRepository(
        strategy_snapshots=_prior_snapshots(CODES[-1], prior_days),
        formally_committed_run_dates=set(prior_days),
        formal_focus_days=formal_days,
    )

    output = analyze_formal_inputs(
        ready_receipt(),
        candidate_set(ordered=(CODES[-1],), active=()),
        complete_payloads((CODES[-1],)),
        repository,
    )

    assert repository.formal_focus_day_calls == [(TARGET, prior_days)]
    assert output.value.focus_states == []


def test_formal_analysis_carries_exact_five_session_history_for_focus_stock():
    prior_days = [TARGET - timedelta(days=value) for value in (7, 4, 3, 2, 1)]
    repository = InMemoryAnalysisRepository(
        strategy_snapshots=_prior_snapshots(CODES[0], prior_days),
        formally_committed_run_dates=set(prior_days),
        formal_focus_days=[
            FormalFocusDay(trade_date=value, formally_committed=True)
            for value in prior_days
        ],
        focus_states=[
            FocusState(
                trade_date=prior_days[-1],
                ts_code=CODES[0],
                state=ActionLabel.CONTINUE_OBSERVATION,
            )
        ],
    )

    output = analyze_formal_inputs(
        ready_receipt(),
        candidate_set(ordered=(CODES[-1],), active=(CODES[0],)),
        complete_payloads((CODES[-1], CODES[0])),
        repository,
    )

    history = output.value.focus_history_by_code[CODES[0]]
    assert [item.trade_date for item in history] == prior_days
    assert all(item.ts_code == CODES[0] for item in history)


def test_formal_focus_sessions_come_from_current_market_payload():
    current = date(2026, 7, 14)
    covered_sessions = (
        date(2026, 7, 7),
        date(2026, 7, 8),
        date(2026, 7, 9),
        date(2026, 7, 10),
        date(2026, 7, 13),
        current,
    )

    assert _prior_five_sessions(current, covered_sessions) == [
        date(2026, 7, 7),
        date(2026, 7, 8),
        date(2026, 7, 9),
        date(2026, 7, 10),
        date(2026, 7, 13),
    ]


def test_formal_analysis_builds_complete_evidence_hashes_and_narrow_ledger_rows():
    prior_days = [TARGET - timedelta(days=value) for value in (7, 4, 3, 2, 1)]
    repository = InMemoryAnalysisRepository(
        strategy_snapshots=_prior_snapshots(CODES[-1], prior_days),
        formally_committed_run_dates=set(prior_days),
        formal_focus_days=[
            FormalFocusDay(trade_date=value, formally_committed=True)
            for value in prior_days
        ],
        focus_states=[
            FocusState(
                trade_date=TARGET - timedelta(days=1),
                ts_code=CODES[0],
                state=ActionLabel.CONTINUE_OBSERVATION,
            )
        ],
    )
    payloads = complete_payloads((CODES[-1], CODES[0]))
    market = payloads[next(key for key in payloads if key.value == "market_decision")]
    payloads[market.group_id] = market.model_copy(
        update={
            "records": tuple(
                dict(row, amount=500_000_000.0)
                if row.get("record_type") == "equity_bar"
                and row.get("ts_code") == CODES[-1]
                else row
                for row in market.records
            )
        }
    )
    holdings = payloads[next(key for key in payloads if key.value == "manual_holdings")]
    payloads[holdings.group_id] = holdings.model_copy(
        update={
            "records": (
                {
                    "record_type": "manual_holding",
                    "trade_date": TARGET,
                    "ts_code": CODES[0],
                    "name": "手工持仓",
                    "position_pct": 1.0,
                    "source_name": "local.manual_holdings",
                },
            )
        }
    )
    output = analyze_formal_inputs(
        ready_receipt(),
        candidate_set(ordered=(CODES[-1],), active=(CODES[0],)),
        payloads,
        repository,
    )

    assert {row["kind"] for row in output.ledger_rows} == {
        "recommendation",
        "focus_state",
        "evidence_package",
        "evaluation_task",
        "strategy_snapshot",
        "focus_entry_thesis",
        "focus_daily_update",
        "action_recommendation",
        "manual_holding_summary",
        "operational_status",
    }
    for package in output.value.evidence_packages:
        canonical = json.dumps(
            package.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        assert output.evidence_hashes[package.evidence_id] == hashlib.sha256(
            canonical.encode("utf-8")
        ).hexdigest()


def test_zero_recommendations_with_focus_output_commits_rows_without_publishable_pointer():
    existing = FocusState(
        trade_date=TARGET - timedelta(days=1),
        ts_code=CODES[0],
        state=ActionLabel.CONTINUE_OBSERVATION,
    )
    output = analyze_formal_inputs(
        ready_receipt(),
        candidate_set(ordered=(), active=(CODES[0],)),
        complete_payloads((CODES[0],)),
        InMemoryAnalysisRepository(focus_states=[existing]),
    )

    assert output.value.recommendations == []
    assert output.value.focus_states
    assert any(row["kind"] == "focus_state" for row in output.ledger_rows)
    assert output.has_publishable_output is False
    assert output.pointer_payloads == {}


def test_structured_hard_risk_blocks_participation_without_title_keyword_inference():
    payloads = complete_payloads((CODES[-1],))
    market = payloads[next(key for key in payloads if key.value == "market_decision")]
    payloads[market.group_id] = market.model_copy(
        update={
            "records": tuple(
                dict(row, amount=500_000_000.0)
                if row.get("record_type") == "equity_bar"
                and row.get("ts_code") == CODES[-1]
                else row
                for row in market.records
            )
        }
    )
    events = payloads[next(key for key in payloads if key.value == "official_events_risk")]
    payloads[events.group_id] = events.model_copy(
        update={
            "records": (
                {
                    "record_type": "official_event",
                    "trade_date": TARGET,
                    "ts_code": CODES[-1],
                    "event_id": "event-1",
                    "event_type": "suspension",
                    "title": "停牌事项",
                    "publication_time": ready_receipt().report_cutoff,
                    "source_reliability": "official_provider",
                    "is_new_information": True,
                    "hard_risk": True,
                    "source_name": "recorded.official",
                },
            )
        }
    )

    output = analyze_formal_inputs(
        ready_receipt(),
        candidate_set(ordered=(CODES[-1],), active=()),
        payloads,
        InMemoryAnalysisRepository(),
    )

    assert output.value.strategy_snapshots[0].action.decision is ActionDecision.NO_PARTICIPATION
