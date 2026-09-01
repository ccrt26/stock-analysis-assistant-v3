from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.export_skill_optimization_dataset import (
    build_event_key,
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
