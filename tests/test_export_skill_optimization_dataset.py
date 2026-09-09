from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from tools.export_skill_optimization_dataset import (
    _apply_formal_result_consistency,
    build_candidate_outcome_records,
    build_candidate_outcome_subjects,
    build_conditional_event_outcomes,
    build_daily_price_volume_records,
    build_event_key,
    build_formal_selections,
    canonical_archive_paths,
    enrich_selections_with_outcomes,
    ensure_public_safe,
    export_dataset,
    extract_candidate_records,
    fixed_d20_fields,
    load_benchmark_daily,
    load_daily_formal_review_records,
    load_trading_dates,
    write_csv,
    write_jsonl,
)
from tools.validate_skill_optimization_dataset import validate_package


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
            "run_id": "formal:2026-08-28:2026-08-31",
            "ts_code": "600150.SH",
            "decision_id": "act-600150",
            "formation_values": {"reaction_start_date": "2026-08-31"},
        }
    ]
    condition_records = [
        {
            "run_id": "formal:2026-08-28:2026-08-31",
            "ts_code": "600150.SH",
            "condition_result": "not_met",
            "observed_through_date": "2026-09-02",
            "source_refs": ["monitor-report-2026-09-02.json"],
            "note": "首日未确认",
        }
    ]

    rows = build_conditional_event_outcomes(
        [candidate], decisions, condition_records, "2026-09-02"
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["event_key"] == "formal:2026-08-28:600150.SH:selected"
    assert row["first_observable_session"] == "2026-08-31"
    assert row["condition_result"] == "not_met"
    assert row["condition_review_status"] == "reviewed"
    assert row["reliable_entry_available"] is False
    assert row["reliable_entry_price"] is None
    assert row["formal_return_started"] is False
    assert row["outcome_data_status"] == "condition_not_met"
    assert row["outcome_close_return"] is None
    assert row["outcome_max_close_return"] is None
    assert row["outcome_mae"] is None
    assert row["notes"] == "首日未确认"


# ---------------------------------------------------------------------------
# Shared synthetic fixtures for T01—T19
# ---------------------------------------------------------------------------


def _write_parquet(frame: "pd.DataFrame", path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path)


def _make_warehouse(
    root: Path,
    open_days: list[str],
    equity: dict[str, list[dict]] | None = None,
    adj: dict[str, dict[str, float]] | None = None,
    index: dict[str, tuple[float, float]] | None = None,
    equity_skip_days: set[str] | None = None,
    closed_days: list[str] | None = None,
) -> Path:
    equity = equity or {}
    adj = adj or {}
    index = index or {}
    equity_skip_days = equity_skip_days or set()
    calendar_rows = [
        {"exchange": "SSE", "cal_date": day, "is_open": True} for day in open_days
    ] + [
        {"exchange": "SSE", "cal_date": day, "is_open": False} for day in (closed_days or [])
    ]
    _write_parquet(
        pd.DataFrame(calendar_rows),
        root / "facts/trade_calendar/cal_year=2026/data.parquet",
    )
    for day in open_days:
        if day not in equity_skip_days:
            rows = [
                {
                    "trade_date": day,
                    "ts_code": row.get("ts_code", "600150.SH"),
                    "open": row.get("open", 10.0),
                    "high": row.get("high", 11.0),
                    "low": row.get("low", 9.0),
                    "close": row.get("close", 10.5),
                    "pre_close": row.get("pre_close", 10.0),
                    "pct_chg": row.get("pct_chg", 1.0),
                    "volume": row.get("volume", 1000.0),
                    "amount": row.get("amount", 10500.0),
                }
                for row in equity.get(day, [])
            ]
            if rows:
                _write_parquet(
                    pd.DataFrame(rows),
                    root / f"facts/equity_daily/trade_date={day}/data.parquet",
                )
        factors = adj.get(day, {})
        if factors:
            _write_parquet(
                pd.DataFrame(
                    [
                        {"trade_date": day, "ts_code": code, "adj_factor": value}
                        for code, value in factors.items()
                    ]
                ),
                root / f"facts/adj_factor/trade_date={day}/data.parquet",
            )
        benchmark = index.get(day)
        if benchmark:
            _write_parquet(
                pd.DataFrame(
                    [
                        {
                            "trade_date": day,
                            "index_code": "000300.SH",
                            "open": benchmark[0],
                            "close": benchmark[1],
                        }
                    ]
                ),
                root / f"facts/index_daily/trade_date={day}/data.parquet",
            )
    return root


def _subject(
    event_key: str,
    code: str = "600150.SH",
    action_date: str = "2026-08-20",
    formation: str = "2026-08-19",
) -> dict:
    return {
        "event_key": event_key,
        "formation_date": formation,
        "action_date": action_date,
        "selection_as_of": "2026-08-19T18:30:00+08:00",
        "ts_code": code,
        "name": "测试股",
    }


def _run_t01_to_t03_warehouse(root: Path) -> tuple[Path, list[str]]:
    return _make_warehouse(
        root,
        open_days=["2026-08-20", "2026-08-21", "2026-08-24"],
        equity={
            "2026-08-20": [{"ts_code": "600150.SH", "open": 100.0, "close": 101.0, "high": 102.0, "low": 99.0}],
            "2026-08-24": [{"ts_code": "600150.SH", "open": 101.0, "close": 103.0, "high": 104.0, "low": 100.0}],
        },
        adj={"2026-08-20": {"600150.SH": 1.0}, "2026-08-24": {"600150.SH": 1.0}},
    ), ["2026-08-20", "2026-08-21", "2026-08-24"]


def test_T01_missing_whole_day_partition_keeps_calendar_day_number(tmp_path: Path) -> None:
    root, trading_days = _run_t01_to_t03_warehouse(tmp_path)
    subjects = [_subject("formal:2026-08-19:600150.SH:selected")]

    rows = build_daily_price_volume_records(
        root, subjects, "2026-08-24", load_trading_dates(root, "2026-08-20", "2026-08-24")
    )

    numbers = [(row["trade_date"], row["trading_day_number"]) for row in rows]
    assert numbers == [
        ("2026-08-20", 1),
        ("2026-08-21", 2),
        ("2026-08-24", 3),
    ]
    missing = [row for row in rows if row["data_status"] != "available"]
    assert [row["trade_date"] for row in missing] == ["2026-08-21"]
    assert missing[0]["trading_day_number"] == 2


def test_T02_missing_first_day_open_is_no_reliable_entry(tmp_path: Path) -> None:
    root = _make_warehouse(
        tmp_path,
        open_days=["2026-08-20", "2026-08-21", "2026-08-24"],
        equity={
            # Day 1 partition only carries another stock: no reliable entry for ours.
            "2026-08-20": [{"ts_code": "000001.SZ", "open": 5.0, "close": 5.1}],
            "2026-08-21": [{"ts_code": "600150.SH", "open": 101.0, "close": 102.0}],
            "2026-08-24": [{"ts_code": "600150.SH", "open": 101.0, "close": 103.0}],
        },
        adj={
            "2026-08-21": {"600150.SH": 1.0},
            "2026-08-24": {"600150.SH": 1.0},
        },
    )
    trading_days = ["2026-08-20", "2026-08-21", "2026-08-24"]
    subjects = [_subject("formal:2026-08-19:600150.SH:selected")]
    rows = build_daily_price_volume_records(root, subjects, "2026-08-24", trading_days)
    fields = fixed_d20_fields(subjects[0], rows, trading_days)
    assert fields["fixed_d20_status"] == "no_reliable_entry"
    later = [row for row in rows if row["trade_date"] == "2026-08-24"][0]
    assert later["entry_open_adjusted"] is None


def test_T03_equity_row_without_adj_factor_is_not_complete(tmp_path: Path) -> None:
    root = _make_warehouse(
        tmp_path,
        open_days=["2026-08-20", "2026-08-21"],
        equity={
            "2026-08-20": [{"ts_code": "600150.SH", "open": 100.0, "close": 101.0}],
            "2026-08-21": [{"ts_code": "600150.SH", "open": 101.0, "close": 102.0}],
        },
        adj={"2026-08-20": {"600150.SH": 1.0}},
    )
    subjects = [_subject("formal:2026-08-19:600150.SH:selected")]
    trading_days = load_trading_dates(root, "2026-08-20", "2026-08-21")

    rows = build_daily_price_volume_records(root, subjects, "2026-08-21", trading_days)

    day2 = [row for row in rows if row["trade_date"] == "2026-08-21"][0]
    assert day2["data_status"] == "available"
    assert day2["close_return_since_entry"] is None
    fields = fixed_d20_fields(subjects[0], rows, trading_days)
    assert fields["fixed_d20_status"] == "not_mature"


def _flat_path_rows(root: Path, days: int, closes: dict[int, float], highs: dict[int, float] | None = None, lows: dict[int, float] | None = None, skip_close_days: set[int] | None = None):
    from datetime import date as _date, timedelta as _timedelta

    highs = highs or {}
    lows = lows or {}
    skip_close_days = skip_close_days or set()
    open_days = [
        (_date(2026, 8, 20) + _timedelta(days=offset)).isoformat()
        for offset in range(days)
    ]
    equity: dict[str, list[dict]] = {}
    adj: dict[str, dict[str, float]] = {}
    for number, day in enumerate(open_days, start=1):
        row: dict = {"ts_code": "600150.SH", "open": 100.0, "high": highs.get(number, 101.0), "low": lows.get(number, 99.0), "close": closes.get(number, 100.0)}
        if number in skip_close_days:
            row["close"] = None
        equity[day] = [row]
        adj[day] = {"600150.SH": 1.0}
    return _make_warehouse(root, open_days=open_days, equity=equity, adj=adj), open_days


def test_T04_day21_surge_does_not_change_fixed_d20(tmp_path: Path) -> None:
    closes = {number: 100.0 for number in range(1, 21)}
    closes.update({number: 105.0 for number in (4, 20)})
    closes[21] = 130.0
    root, open_days = _flat_path_rows(tmp_path, 21, closes)
    trading_days = load_trading_dates(root, "2026-08-20", "2026-09-09")
    subject = _subject("formal:2026-08-19:600150.SH:selected")
    rows = build_daily_price_volume_records(root, [subject], "2026-09-09", trading_days)
    fields = fixed_d20_fields(subject, rows, trading_days)
    assert fields["fixed_d20_status"] == "complete"
    assert fields["fixed_d20_hit_20pct_close"] is False
    assert fields["fixed_d20_first_hit_day"] is None


def test_T05_intraday_high_25pct_is_not_close_hit(tmp_path: Path) -> None:
    closes = {number: 110.0 for number in range(1, 21)}
    highs = {20: 125.0}
    root, open_days = _flat_path_rows(tmp_path, 20, closes, highs=highs)
    trading_days = load_trading_dates(root, "2026-08-20", "2026-09-08")
    subject = _subject("formal:2026-08-19:600150.SH:selected")
    rows = build_daily_price_volume_records(root, [subject], "2026-09-08", trading_days)
    fields = fixed_d20_fields(subject, rows, trading_days)
    assert fields["fixed_d20_status"] == "complete"
    assert fields["fixed_d20_mfe"] == pytest.approx(0.25)
    assert fields["fixed_d20_hit_20pct_close"] is False


def test_T06_drawdown_mae_and_end_drawdown_are_distinct(tmp_path: Path) -> None:
    closes = {1: 110.0, 2: 90.0}
    closes.update({number: 120.0 for number in range(3, 21)})
    lows = {2: 89.0}
    root, open_days = _flat_path_rows(tmp_path, 20, closes, lows=lows)
    trading_days = load_trading_dates(root, "2026-08-20", "2026-09-08")
    subject = _subject("formal:2026-08-19:600150.SH:selected")
    rows = build_daily_price_volume_records(root, [subject], "2026-09-08", trading_days)
    fields = fixed_d20_fields(subject, rows, trading_days)
    assert fields["fixed_d20_max_close_drawdown"] == pytest.approx(0.90 / 1.10 - 1.0)
    assert fields["fixed_d20_close_drawdown_at_end"] == pytest.approx(0.0)
    assert fields["fixed_d20_mae"] == pytest.approx(0.89 / 1.00 - 1.0)
    assert fields["fixed_d20_mae"] != pytest.approx(fields["fixed_d20_max_close_drawdown"])


def test_T07_same_stock_two_recommendations_stay_independent(tmp_path: Path) -> None:
    root = _make_warehouse(
        tmp_path,
        open_days=["2026-08-20", "2026-08-27"],
        equity={
            "2026-08-20": [{"ts_code": "600150.SH", "open": 100.0, "close": 105.0}],
            "2026-08-27": [{"ts_code": "600150.SH", "open": 200.0, "close": 202.0}],
        },
        adj={"2026-08-20": {"600150.SH": 1.0}, "2026-08-27": {"600150.SH": 1.0}},
    )
    trading_days = load_trading_dates(root, "2026-08-20", "2026-08-27")
    subjects = [
        _subject("formal:2026-08-19:600150.SH:selected", action_date="2026-08-20"),
        _subject("formal:2026-08-26:600150.SH:selected", action_date="2026-08-27"),
    ]
    rows = build_daily_price_volume_records(root, subjects, "2026-08-27", trading_days)
    first = [row for row in rows if row["event_key"] == "formal:2026-08-19:600150.SH:selected"]
    second = [row for row in rows if row["event_key"] == "formal:2026-08-26:600150.SH:selected"]
    assert first[0]["entry_open_adjusted"] == pytest.approx(100.0)
    assert second[0]["entry_open_adjusted"] == pytest.approx(200.0)
    assert first[0]["close_return_since_entry"] == pytest.approx(0.05)
    assert second[0]["close_return_since_entry"] == pytest.approx(0.01)


def test_T08_new_conditional_without_condition_file_exports_unknown(tmp_path: Path) -> None:
    candidate = {
        "run_id": "formal:2026-08-28:2026-08-31",
        "formation_date": "2026-08-28",
        "action_date": "2026-08-31",
        "selection_as_of": None,
        "trace_version": "daily-research-trace-v4",
        "ts_code": "600150.SH",
        "name": "中国船舶",
        "final_fate": "selected",
        "opportunity_type": "company_catalyst",
        "research_thesis": {
            "engine_type": "fresh_event_pending",
            "engine_status": "conditional",
            "market_recognition": {"status": "pending"},
        },
    }

    rows = build_conditional_event_outcomes([candidate], [], [], "2026-08-31")

    assert rows[0]["condition_result"] == "unknown"
    assert rows[0]["condition_unknown_reason"] == "no_condition_review_file_provided"
    assert rows[0]["formal_return_started"] is False
    assert rows[0]["outcome_close_return"] is None
    outcome_rows = build_candidate_outcome_records([candidate], [], "2026-08-31")
    assert outcome_rows[0]["fixed_d20_status"] == "not_applicable"
    assert outcome_rows[0]["selection_output_class"] == "conditional_event"


def test_T09_same_decision_id_in_two_runs_does_not_cross_match(tmp_path: Path) -> None:
    candidate_a = {
        "run_id": "formal:2026-08-19:2026-08-20",
        "formation_date": "2026-08-19",
        "action_date": "2026-08-20",
        "selection_as_of": None,
        "trace_version": "daily-research-trace-v4",
        "ts_code": "600150.SH",
        "name": "甲",
        "final_fate": "selected",
        "research_thesis": {
            "engine_type": "fresh_event_pending",
            "engine_status": "conditional",
            "action_condition_decision_id": "shared-decision",
        },
    }
    candidate_b = dict(candidate_a)
    candidate_b.update(
        {
            "run_id": "formal:2026-08-26:2026-08-27",
            "formation_date": "2026-08-26",
            "action_date": "2026-08-27",
            "ts_code": "600150.SH",
            "name": "乙",
        }
    )
    decisions = [
        {
            "run_id": "formal:2026-08-19:2026-08-20",
            "ts_code": "600150.SH",
            "decision_id": "shared-decision",
            "formation_values": {"reaction_start_date": "2026-08-20"},
        },
        {
            "run_id": "formal:2026-08-26:2026-08-27",
            "ts_code": "600150.SH",
            "decision_id": "shared-decision",
            "formation_values": {"reaction_start_date": "2026-08-27"},
        },
    ]
    conditions = [
        {"run_id": "formal:2026-08-19:2026-08-20", "ts_code": "600150.SH", "condition_result": "met", "observed_through_date": "2026-08-21"},
        {"run_id": "formal:2026-08-26:2026-08-27", "ts_code": "600150.SH", "condition_result": "not_met", "observed_through_date": "2026-08-28"},
    ]

    rows = build_conditional_event_outcomes(
        [candidate_a, candidate_b], decisions, conditions
    )

    by_name = {row["name"]: row for row in rows}
    assert by_name["甲"]["condition_result"] == "met"
    assert by_name["甲"]["first_observable_session"] == "2026-08-20"
    assert by_name["乙"]["condition_result"] == "not_met"
    assert by_name["乙"]["first_observable_session"] == "2026-08-27"


def _make_monitor_dir(
    monitor_dir: Path,
    *,
    ledger_rows: list[dict],
    report_rows: list[dict],
    analysis_date: str = "2026-08-31",
) -> None:
    monitor_dir.mkdir(parents=True, exist_ok=True)
    ledger = {
        "analysis_date": analysis_date,
        "as_of": f"{analysis_date}T18:30:00+08:00",
        "ledger_version": "daily-formal-reviews-v1",
        "reviews": ledger_rows,
    }
    (monitor_dir / f"daily-formal-reviews-{analysis_date}.json").write_text(
        json.dumps(ledger, ensure_ascii=False), encoding="utf-8"
    )
    backup = dict(ledger)
    backup["reviews"] = [dict(row, view_change="stale") for row in ledger_rows]
    (monitor_dir / f"daily-formal-reviews-{analysis_date}.json.pre-check-2026-09-01.json").write_text(
        json.dumps(backup, ensure_ascii=False), encoding="utf-8"
    )
    report = {
        "analysis_date": analysis_date,
        "as_of": f"{analysis_date}T18:30:00+08:00",
        "alerts": [
            {
                "alert_type": "checkpoint_detail",
                "episode_ids": [row["episode_id"] for row in report_rows],
                "episode_reviews": report_rows,
            }
        ],
    }
    (monitor_dir / f"monitor-report-{analysis_date}.json").write_text(
        json.dumps(report, ensure_ascii=False), encoding="utf-8"
    )


def test_T10_brief_and_detail_bodies_keep_their_single_home(tmp_path: Path) -> None:
    monitor_dir = tmp_path / "monitor"
    ledger_rows = [
        {
            "episode_id": "formal:2026-08-20:600150.SH:selected",
            "review_kind": "brief",
            "review_origin": "live",
            "current_review": "股票｜简评正文",
            "view_change": "unchanged",
        },
        {
            "episode_id": "formal:2026-08-20:000001.SZ:selected",
            "review_kind": "regular_detail",
            "review_origin": "live",
            "current_review": "",
            "view_change": "strengthened",
        },
    ]
    report_rows = [
        {
            "episode_id": "formal:2026-08-20:000001.SZ:selected",
            "current_review": "详评唯一正文",
        }
    ]
    _make_monitor_dir(monitor_dir, ledger_rows=ledger_rows, report_rows=report_rows)

    records, conflicts = load_daily_formal_review_records(
        monitor_dir,
        {row["episode_id"] for row in ledger_rows},
        "2026-08-31",
    )

    assert len(records) == 2
    brief = [row for row in records if row["review_kind"] == "brief"][0]
    detail = [row for row in records if row["review_kind"] == "regular_detail"][0]
    assert brief["current_review"] == "股票｜简评正文"
    assert detail["current_review"] == ""
    assert detail["review_origin"] == "live"
    assert detail["analysis_date"] == "2026-08-31"
    assert conflicts == []


def test_T11_market_relative_uses_same_action_open_window(tmp_path: Path) -> None:
    root = _make_warehouse(
        tmp_path,
        open_days=["2026-08-20", "2026-08-21"],
        equity={
            "2026-08-20": [{"ts_code": "600150.SH", "open": 100.0, "close": 104.0}],
            "2026-08-21": [{"ts_code": "600150.SH", "open": 104.0, "close": 112.0}],
        },
        adj={"2026-08-20": {"600150.SH": 1.0}, "2026-08-21": {"600150.SH": 1.0}},
        index={"2026-08-20": (1000.0, 1010.0), "2026-08-21": (1010.0, 1050.0)},
    )
    trading_days = load_trading_dates(root, "2026-08-20", "2026-08-21")
    benchmark = load_benchmark_daily(root, trading_days)
    subject = _subject("formal:2026-08-19:600150.SH:selected")
    rows = build_daily_price_volume_records(
        root, [subject], "2026-08-21", trading_days, benchmark
    )
    last = rows[-1]
    assert last["relative_market_return"] == pytest.approx(0.12 - 0.05)
    assert last["relative_market_basis"] == "action_open_to_same_close"

    partial = load_benchmark_daily(
        _make_warehouse(
            tmp_path / "partial",
            open_days=["2026-08-20", "2026-08-21"],
            index={"2026-08-21": (1010.0, 1050.0)},
        ),
        ["2026-08-20", "2026-08-21"],
    )
    rows_partial = build_daily_price_volume_records(
        tmp_path / "partial", [subject], "2026-08-21", trading_days, partial
    )
    assert rows_partial[-1]["relative_market_return"] is None
    assert rows_partial[-1]["relative_market_basis"] is None


def test_T16_frozen_value_mismatch_is_reported_not_overwritten(tmp_path: Path) -> None:
    selections = [
        dict(
            _subject("formal:2026-08-19:600150.SH:selected"),
            fixed_d20_status="complete",
            fixed_d20_terminal_return=0.10,
        )
    ]
    episodes = [
        {
            "ts_code": "600150.SH",
            "action_date": "2026-08-20",
            "episode_id": "formal:2026-08-19:600150.SH:selected",
            "d20_close_return_since_entry": 0.246,
        }
    ]

    _apply_formal_result_consistency(selections, episodes)

    assert selections[0]["formal_result_consistency"] == "mismatch"
    assert selections[0]["formal_result_diff_fields"]


def test_T17_condition_observed_after_cutoff_is_unknown(tmp_path: Path) -> None:
    candidate = {
        "run_id": "formal:2026-08-28:2026-08-31",
        "formation_date": "2026-08-28",
        "action_date": "2026-08-31",
        "selection_as_of": None,
        "trace_version": "daily-research-trace-v4",
        "ts_code": "600150.SH",
        "name": "中国船舶",
        "final_fate": "selected",
        "research_thesis": {
            "engine_type": "fresh_event_pending",
            "engine_status": "conditional",
        },
    }
    conditions = [
        {
            "run_id": "formal:2026-08-28:2026-08-31",
            "ts_code": "600150.SH",
            "condition_result": "met",
            "observed_through_date": "2026-09-30",
        }
    ]

    rows = build_conditional_event_outcomes(
        [candidate], [], conditions, "2026-08-31"
    )

    assert rows[0]["condition_result"] == "unknown"
    assert rows[0]["condition_unknown_reason"] == "observation_after_export_cutoff"


def test_T19_backup_files_are_ignored_and_canonical_files_are_kept(tmp_path: Path) -> None:
    monitor_dir = tmp_path / "monitor"
    ledger_rows = [
        {
            "episode_id": "formal:2026-08-20:600150.SH:selected",
            "review_kind": "brief",
            "review_origin": "live",
            "current_review": "股票｜正文",
            "view_change": "unchanged",
        }
    ]
    _make_monitor_dir(monitor_dir, ledger_rows=ledger_rows, report_rows=[])

    canonical = canonical_archive_paths(monitor_dir, "daily-formal-reviews")

    assert [path.name for path in canonical] == ["daily-formal-reviews-2026-08-31.json"]
    records, _ = load_daily_formal_review_records(
        monitor_dir, {ledger_rows[0]["episode_id"]}, "2026-08-31"
    )
    assert len(records) == 1
    assert records[0]["source_file"] == "daily-formal-reviews-2026-08-31.json"
    assert records[0]["view_change"] == "unchanged"


# ---------------------------------------------------------------------------
# End-to-end export + validation on synthetic local archives (T12/T13/T14/T15/T18)
# ---------------------------------------------------------------------------


def _v4_trace(action_date: str, formation_date: str, candidates: list[dict]) -> dict:
    return {
        "trace_version": "daily-research-trace-v4",
        "formation_date": formation_date,
        "action_date": action_date,
        "as_of": f"{formation_date}T18:30:00+08:00",
        "candidate_ledger": candidates,
        "decision_trace": [],
        "research_result": {"selected_stocks": [row for row in candidates if row.get("final_fate") == "selected"]},
    }


def _active_candidate(code: str, name: str, fate: str) -> dict:
    return {
        "ts_code": code,
        "name": name,
        "opportunity_type": "independent_price_anomaly",
        "source_skills": ["price"],
        "final_fate": fate,
        "primary_reason": "理由",
        "selection_reason": "理由",
        "strongest_counterevidence": "反证",
        "research_thesis": {
            "engine_type": "independent_demand_acceleration",
            "engine_status": "active",
            "market_recognition": {"status": "confirmed"},
        },
    }


def _write_source_root(
    root: Path,
    *,
    traces: list[dict],
    log_rows: list[dict[str, str]],
    open_days: list[str],
    equity: dict[str, list[dict]] | None = None,
    adj: dict[str, dict[str, float]] | None = None,
    with_monitor: bool = True,
) -> Path:
    selection_dir = root / "local_archive/forward_selection"
    selection_dir.mkdir(parents=True, exist_ok=True)
    for trace in traces:
        name = f"research-trace-{trace['formation_date']}.json"
        (selection_dir / name).write_text(json.dumps(trace, ensure_ascii=False), encoding="utf-8")
        backup_name = name.replace(".json", ".json.pre-check-2026-09-01.json")
        (selection_dir / backup_name).write_text("{}", encoding="utf-8")
    import csv as _csv

    fields = ["formation_date", "action_date", "as_of", "ts_code", "name", "final_fate", "priority", "opportunity_type", "selection_reason", "strongest_counterevidence", "nearest_comparison", "validation_mode"]
    with (selection_dir / "forward-selection-log.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = _csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(log_rows)
    if with_monitor:
        _make_monitor_dir(
            root / "local_archive/forward_monitor",
            ledger_rows=[
                {
                    "episode_id": "formal:2026-08-20:600150.SH:selected",
                    "review_kind": "brief",
                    "review_origin": "live",
                    "current_review": "股票｜正文",
                    "view_change": "unchanged",
                }
            ],
            report_rows=[],
        )
    days = open_days
    equity = equity or {}
    adj = adj or {}
    calendar_rows = [{"exchange": "SSE", "cal_date": day, "is_open": True} for day in days]
    _write_parquet(
        pd.DataFrame(calendar_rows),
        root / "local_warehouse/facts/trade_calendar/cal_year=2026/data.parquet",
    )
    for day in days:
        rows = [
            {
                "trade_date": day,
                "ts_code": row.get("ts_code", "600150.SH"),
                "open": row.get("open", 100.0),
                "high": row.get("high", 101.0),
                "low": row.get("low", 99.0),
                "close": row.get("close", 100.5),
                "pre_close": 100.0,
                "pct_chg": 1.0,
                "volume": 1000.0,
                "amount": 10000.0,
            }
            for row in equity.get(day, [{"ts_code": "600150.SH"}])
        ]
        _write_parquet(
            pd.DataFrame(rows),
            root / f"local_warehouse/facts/equity_daily/trade_date={day}/data.parquet",
        )
        factors = adj.get(day, {"600150.SH": 1.0})
        _write_parquet(
            pd.DataFrame(
                [
                    {"trade_date": day, "ts_code": code, "adj_factor": value}
                    for code, value in factors.items()
                ]
            ),
            root / f"local_warehouse/facts/adj_factor/trade_date={day}/data.parquet",
        )
    return root


def test_T12_active_only_batch_exports_and_validates_without_workbook(tmp_path: Path) -> None:
    trace = _v4_trace("2026-08-20", "2026-08-19", [_active_candidate("600150.SH", "中国船舶", "selected")])
    log_rows = [
        {
            "formation_date": "2026-08-19",
            "action_date": "2026-08-20",
            "as_of": "2026-08-19T18:30:00+08:00",
            "ts_code": "600150.SH",
            "name": "中国船舶",
            "final_fate": "selected",
            "priority": "1",
            "opportunity_type": "independent_price_anomaly",
            "selection_reason": "理由",
            "strongest_counterevidence": "反证",
            "nearest_comparison": "",
            "validation_mode": "selection",
        }
    ]
    source = _write_source_root(
        tmp_path / "source",
        traces=[trace],
        log_rows=log_rows,
        open_days=["2026-08-20", "2026-08-21"],
    )
    out = tmp_path / "package"

    counts = export_dataset(
        source,
        out,
        start_action_date="2026-08-20",
        end_action_date="2026-08-20",
        outcome_through_date="2026-08-21",
        exported_at="2026-09-09T12:00:00+08:00",
    )

    assert counts["formal_selections"] == 1
    assert not list(out.glob("*.xlsx"))
    result = validate_package(out)
    assert result["status"] == "PASS"
    assert result["package_version"] == "a-share-skill-optimization-sample-v3"
    selections = (out / "data/formal_selections.csv").read_text(encoding="utf-8-sig").splitlines()
    assert "fixed_d20_status" in selections[0]
    assert "not_mature" in selections[1]


def test_T13_zero_selection_research_day_and_missing_trace_handling(tmp_path: Path) -> None:
    trace = _v4_trace("2026-08-20", "2026-08-19", [])
    source = _write_source_root(
        tmp_path / "source",
        traces=[trace],
        log_rows=[],
        open_days=["2026-08-20"],
    )
    out = tmp_path / "package"

    counts = export_dataset(
        source,
        out,
        start_action_date="2026-08-20",
        end_action_date="2026-08-20",
        outcome_through_date="2026-08-20",
        exported_at="2026-09-09T12:00:00+08:00",
    )

    assert counts["formal_selections"] == 0
    header = (out / "data/formal_selections.csv").read_text(encoding="utf-8-sig").strip()
    assert header.startswith("event_key")
    result = validate_package(out)
    assert result["status"] == "PASS"

    empty_root = tmp_path / "empty"
    (empty_root / "local_archive/forward_selection").mkdir(parents=True)
    with pytest.raises(ValueError):
        export_dataset(
            empty_root,
            tmp_path / "none",
            start_action_date="2026-08-20",
            end_action_date="2026-08-20",
            outcome_through_date="2026-08-20",
        )


def test_T14_latest_formula_file_without_reference_is_reconstruction(tmp_path: Path) -> None:
    from tools.export_skill_optimization_dataset import build_derived_context_records

    warehouse = tmp_path / "wh"
    for version in ("fv-1", "fv-2"):
        path = warehouse / f"derived/market_context/analysis_date=2026-08-19/formula_version={version}/data.parquet"
        _write_parquet(pd.DataFrame([{"breadth": 0.5}]), path)
    trace = {
        "formation_date": "2026-08-19",
        "action_date": "2026-08-20",
    }
    decisions = [
        {
            "run_id": "formal:2026-08-19:2026-08-20",
            "formation_date": "2026-08-19",
            "decision_id": "d1",
            "formation_values": {"formula_version": "fv-1"},
        }
    ]

    market_records, _, _ = build_derived_context_records(warehouse, [("t.json", trace)], [], decisions)

    assert market_records, "expected market context slice"
    assert {row["formula_version"] for row in market_records} == {"fv-2"}
    assert market_records[0]["context_origin"] == "retrospective_reconstruction"


def test_T15_missing_middle_close_blocks_fixed_d20_but_high_only_gap_keeps_close_result(tmp_path: Path) -> None:
    closes = {number: 1.02 for number in range(1, 21)}
    root, open_days = _flat_path_rows(tmp_path, 20, closes, skip_close_days={10})
    trading_days = load_trading_dates(root, "2026-08-20", "2026-09-08")
    subject = _subject("formal:2026-08-19:600150.SH:selected")
    rows = build_daily_price_volume_records(root, [subject], "2026-09-08", trading_days)
    fields = fixed_d20_fields(subject, rows, trading_days)
    assert fields["fixed_d20_status"] == "missing_path"
    assert "2026-08-29" in fields["fixed_d20_missing_dates"]
    assert fields["fixed_d20_terminal_return"] is None

    root2, open_days2 = _flat_path_rows(
        tmp_path / "high-gap",
        20,
        {number: 1.02 for number in range(1, 21)},
    )
    # Remove only the day-5 high by rebuilding that day's partition without it.
    day5 = "2026-08-24"
    _write_parquet(
        pd.DataFrame(
            [
                {
                    "trade_date": day5,
                    "ts_code": "600150.SH",
                    "open": 100.0,
                    "high": None,
                    "low": 99.0,
                    "close": 102.0,
                    "pre_close": 100.0,
                    "pct_chg": 2.0,
                    "volume": 1000.0,
                    "amount": 10000.0,
                }
            ]
        ),
        root2 / f"facts/equity_daily/trade_date={day5}/data.parquet",
    )
    rows2 = build_daily_price_volume_records(root2, [subject], "2026-09-08", open_days2)
    fields2 = fixed_d20_fields(subject, rows2, open_days2)
    assert fields2["fixed_d20_status"] == "complete"
    assert fields2["fixed_d20_terminal_return"] is not None
    assert fields2["fixed_d20_mfe"] is None
    assert fields2["fixed_d20_mae"] is not None
    assert fields2["fixed_d20_range_missing_dates"] == [day5]
