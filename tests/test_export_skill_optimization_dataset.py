from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.export_skill_optimization_dataset import (
    build_candidate_outcome_records,
    build_candidate_outcome_subjects,
    build_conditional_event_outcomes,
    build_event_key,
    build_formal_selections,
    enrich_selections_with_outcomes,
    ensure_public_safe,
    extract_candidate_records,
    write_csv,
    write_jsonl,
)


def test_build_event_key_is_stable_for_duplicate_stock_selections() -> None:
    first = build_event_key("2026-08-20", "000703.SZ", "selected")
    second = build_event_key("2026-08-27", "000703.SZ", "selected")

    assert first == "formal:2026-08-20:000703.SZ:selected"
    assert first != second


def test_legacy_candidate_chain_is_normalized_without_inventing_thesis() -> None:
    trace = {
        "formation_date": "2026-08-19",
        "action_date": "2026-08-20",
        "as_of": "2026-08-20T09:05:00+08:00",
        "candidate_chain": [
            {
                "ts_code": "000703.SZ",
                "name": "恒逸石化",
                "origins": ["sector", "company", "price"],
                "fate": "selected",
                "reason": "原始理由",
            }
        ],
    }

    records = extract_candidate_records(trace, "legacy-selection-v1")

    assert records == [
        {
            "run_id": "formal:2026-08-19:2026-08-20",
            "formation_date": "2026-08-19",
            "action_date": "2026-08-20",
            "selection_as_of": "2026-08-20T09:05:00+08:00",
            "trace_version": "legacy-selection-v1",
            "ts_code": "000703.SZ",
            "name": "恒逸石化",
            "opportunity_type": None,
            "source_skills": ["sector", "company", "price"],
            "final_fate": "selected",
            "primary_reason": "原始理由",
            "research_thesis": None,
            "normalization_note": "legacy_candidate_chain; no V4 research_thesis was recorded",
        }
    ]


def test_public_safety_rejects_absolute_paths_and_credentials() -> None:
    with pytest.raises(ValueError, match="absolute path"):
        ensure_public_safe({"source": "/Users/person/private.json"})
    with pytest.raises(ValueError, match="credential-like"):
        ensure_public_safe({"api_key": "not-for-publication"})


def test_jsonl_writer_round_trips_unicode_and_null(tmp_path: Path) -> None:
    output = tmp_path / "records.jsonl"
    records = [{"name": "中国船舶", "unknown": None, "value": 1.25}]

    write_jsonl(output, records)

    parsed = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert parsed == records


def test_csv_writer_uses_lf_line_endings(tmp_path: Path) -> None:
    output = tmp_path / "records.csv"

    write_csv(output, [{"name": "中国船舶", "value": 1.25}], ["name", "value"])

    payload = output.read_bytes()
    assert b"\r\n" not in payload
    assert payload.count(b"\n") == 2


def test_outcome_summary_uses_latest_available_event_path() -> None:
    selections = [{"event_key": "formal:2026-08-28:600150.SH:selected"}]
    daily = [
        {
            "event_key": selections[0]["event_key"],
            "trade_date": "2026-08-31",
            "trading_day_number": 1,
            "data_status": "available",
            "close_return_since_entry": 0.02,
            "max_close_return_so_far": 0.02,
            "max_high_return_so_far": 0.04,
            "mae_since_entry": -0.01,
            "close_drawdown_from_peak": 0.0,
        }
    ]

    enrich_selections_with_outcomes(selections, daily, "2026-08-31")

    assert selections[0]["outcome_trading_day_count"] == 1
    assert selections[0]["outcome_close_return"] == 0.02
    assert selections[0]["outcome_mae"] == -0.01


def _selected_row(ts_code: str, name: str, priority: int) -> dict[str, object]:
    return {
        "ts_code": ts_code,
        "name": name,
        "priority": priority,
        "opportunity_type": "company_catalyst",
        "selection_reason": f"{name}理由",
        "strongest_counterevidence": f"{name}反证",
        "nearest_comparison": f"{name}近邻",
    }


def test_v4_formal_selections_exclude_conditional_event_leads() -> None:
    active = _selected_row("000001.SZ", "正式股", 1)
    conditional = _selected_row("000002.SZ", "条件股", 2)
    trace = {
        "trace_version": "daily-research-trace-v4",
        "formation_date": "2026-08-28",
        "action_date": "2026-08-31",
        "as_of": "2026-08-28T17:00:00+08:00",
        "candidate_ledger": [
            {
                **active,
                "final_fate": "selected",
                "research_thesis": {
                    "engine_type": "independent_demand_acceleration",
                    "engine_status": "active",
                    "market_recognition": {"status": "confirmed"},
                },
            },
            {
                **conditional,
                "final_fate": "selected",
                "research_thesis": {
                    "engine_type": "fresh_event_pending",
                    "engine_status": "conditional",
                    "market_recognition": {"status": "pending"},
                },
            },
        ],
        "research_result": {"selected_stocks": [active, conditional]},
    }
    log_rows = [
        {
            "action_date": "2026-08-31",
            "ts_code": row["ts_code"],
            "name": row["name"],
            "selection_reason": row["selection_reason"],
            "strongest_counterevidence": row["strongest_counterevidence"],
            "nearest_comparison": row["nearest_comparison"],
        }
        for row in (active, conditional)
    ]

    rows = build_formal_selections([("trace.json", trace)], log_rows)

    assert [row["name"] for row in rows] == ["正式股"]
    assert rows[0]["selection_output_class"] == "confirmed_active"


def test_candidate_outcomes_cover_selected_rejected_and_unresolved() -> None:
    candidates = [
        {
            "run_id": "formal:2026-08-28:2026-08-31",
            "formation_date": "2026-08-28",
            "action_date": "2026-08-31",
            "selection_as_of": "2026-08-28T17:00:00+08:00",
            "ts_code": f"00000{index}.SZ",
            "name": fate,
            "final_fate": fate,
            "opportunity_type": "independent_price_anomaly",
            "research_thesis": {
                "engine_type": "independent_demand_acceleration",
                "engine_status": "active",
            },
        }
        for index, fate in enumerate(("selected", "rejected", "unresolved"), start=1)
    ]
    subjects = build_candidate_outcome_subjects(candidates)
    daily = [
        {
            "event_key": subject["event_key"],
            "trade_date": "2026-08-31",
            "trading_day_number": 1,
            "data_status": "available",
            "close_return_since_entry": 0.01,
            "max_close_return_so_far": 0.01,
            "max_high_return_so_far": 0.02,
            "mae_since_entry": -0.01,
            "close_drawdown_from_peak": 0.0,
        }
        for subject in subjects
    ]

    rows = build_candidate_outcome_records(candidates, daily, "2026-08-31")

    assert {row["final_fate"] for row in rows} == {
        "selected",
        "rejected",
        "unresolved",
    }
    assert {row["engine_type"] for row in rows} == {
        "independent_demand_acceleration"
    }
    assert all(row["outcome_close_return"] == 0.01 for row in rows)
    assert all(row["relative_market_return_if_available"] is None for row in rows)
    assert all(row["relative_sector_return_if_available"] is None for row in rows)


def test_conditional_event_without_reviewed_entry_has_no_formal_return() -> None:
    candidate = {
        "run_id": "formal:2026-08-28:2026-08-31",
        "formation_date": "2026-08-28",
        "action_date": "2026-08-31",
        "selection_as_of": "2026-08-28T17:00:00+08:00",
        "trace_version": "daily-research-trace-v4",
        "ts_code": "600150.SH",
        "name": "中国船舶",
        "final_fate": "selected",
        "research_thesis": {
            "engine_type": "fresh_event_pending",
            "engine_status": "conditional",
            "action_condition_decision_id": "act-600150",
            "critical_unknown": "首日是否形成相对强势和有效收盘",
            "company_information": {
                "event_id": "event-1",
                "event_available_at": "2026-08-28T17:00:00+08:00",
            },
        },
    }
    decisions = [
        {
            "decision_id": "act-600150",
            "formation_values": {"reaction_start_date": "2026-08-31"},
        }
    ]
    matrix_rows = [
        {
            "event_key": "formal:2026-08-28:600150.SH:selected",
            "action_condition_effect": "not_met",
            "early_outcome_used_only_for_evaluation": "首日未确认",
        }
    ]

    rows = build_conditional_event_outcomes([candidate], decisions, matrix_rows)

    assert rows == [
        {
            "event_key": "formal:2026-08-28:600150.SH:selected",
            "formation_date": "2026-08-28",
            "action_date": "2026-08-31",
            "ts_code": "600150.SH",
            "name": "中国船舶",
            "event_id": "event-1",
            "event_available_at": "2026-08-28T17:00:00+08:00",
            "original_action_condition": "首日是否形成相对强势和有效收盘",
            "first_observable_session": "2026-08-31",
            "condition_result": "not_met",
            "reliable_entry_available": False,
            "reliable_entry_date": None,
            "reliable_entry_price": None,
            "formal_return_started": False,
            "outcome_data_status": "condition_not_met",
            "outcome_close_return": None,
            "outcome_max_close_return": None,
            "outcome_mae": None,
            "notes": "首日未确认",
        }
    ]
