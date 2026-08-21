from __future__ import annotations

import csv
import json
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from stock_analyzer.ops.forward_selection import (
    PricePoint,
    RunSummary,
    apply_mature_settlements,
    prepare_daily_selection,
    prepare_runtime_log,
    record_daily_trace,
    record_daily_selection,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")
SKILLS = {
    "orchestrating-stock-research",
    "interpreting-market-macro",
    "researching-sectors-industries",
    "researching-company-events",
    "analyzing-price-trading",
}
FIELDS = [
    "formation_date",
    "action_date",
    "as_of",
    "ts_code",
    "name",
    "final_fate",
    "priority",
    "opportunity_type",
    "selection_reason",
    "strongest_counterevidence",
    "nearest_comparison",
    "current_day",
    "current_close_return",
    "max_close_return_so_far",
    "hit_20pct_close_within_20d",
    "first_hit_day",
    "terminal_return_20d",
    "selection_as_of",
    "validation_mode",
    "max_close_return_20d",
]


class FakeData:
    def __init__(
        self,
        *,
        open_dates: list[date],
        action_date_status: bool | None = True,
        ready: bool = True,
        ready_states: list[bool] | None = None,
        prices: dict[str, list[PricePoint] | None] | None = None,
    ) -> None:
        self._open_dates = open_dates
        self.action_date_status = action_date_status
        self.ready = ready
        self.ready_states = iter(ready_states) if ready_states is not None else None
        self.health_calls = 0
        self.prices = prices or {}

    def trading_dates(self, start: date, end: date) -> list[date]:
        return [day for day in self._open_dates if start <= day <= end]

    def trading_day_status(self, on_date: date) -> bool | None:
        return self.action_date_status

    def health_report(self, formation_date: date) -> dict:
        self.health_calls += 1
        ready = self.ready
        if self.ready_states is not None:
            try:
                ready = next(self.ready_states)
            except StopIteration:
                pass
        finished = datetime.combine(
            formation_date.replace(day=formation_date.day + 1),
            datetime.min.time(),
            SHANGHAI,
        ).replace(hour=9, minute=2)
        return {
            "complete_core_date": ready,
            "derived_ready_for_research": ready,
            "latest_stage_runs": [
                {
                    "stage": "next-morning",
                    "data_date": formation_date.isoformat(),
                    "status": "limited",
                    "started_at": finished.replace(minute=0).isoformat(),
                    "finished_at": finished.isoformat(),
                }
            ],
        }

    def eligible_securities(self, on_date: date) -> dict[str, str]:
        return {
            "000001.SZ": "平安银行",
            "300548.SZ": "长芯博创",
            "600000.SH": "浦发银行",
        }

    def adjusted_prices(
        self,
        ts_code: str,
        trading_dates: list[date],
    ) -> list[PricePoint] | None:
        return self.prices.get(ts_code)


class FakeResearch:
    def __init__(self, result: dict | Exception) -> None:
        self.result = result
        self.calls = 0
        self.prompt = ""

    def execute(self, *, prompt: str) -> dict:
        self.calls += 1
        self.prompt = prompt
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _clock(*values: datetime):
    remaining = iter(values)
    last = values[-1]

    def now() -> datetime:
        nonlocal remaining
        try:
            return next(remaining)
        except StopIteration:
            return last

    return now


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _row(**overrides: str) -> dict[str, str]:
    row = {field: "" for field in FIELDS}
    row.update(overrides)
    return row


def _empty_result() -> dict:
    return {
        "research_completed": True,
        "point_in_time_evidence_verified": True,
        "failure_reason": "",
        "skills_used": sorted(SKILLS),
        "selected_stocks": [],
        "nearest_nonselections": [],
        "empty_reason": "未发现达到绝对机会质量的股票。",
    }


def _one_stock_result() -> dict:
    result = _empty_result()
    result["selected_stocks"] = [
        {
            "ts_code": "000001.SZ",
            "name": "平安银行",
            "priority": 1,
            "opportunity_type": "independent_price_anomaly",
            "selection_reason": "相对增量仍在继续产生。",
            "strongest_counterevidence": "短期成交推进可能衰减。",
            "nearest_comparison": "绝对机会质量高于最接近替代股。",
        }
    ]
    result["empty_reason"] = ""
    return result


def _one_stock_trace() -> dict:
    return {
        "trace_version": "daily-research-trace-v1",
        "formation_date": "2026-08-18",
        "action_date": "2026-08-19",
        "as_of": "2026-08-19T09:10:00+08:00",
        "market_search_context": "普通股票参与宽度与指数同步，继续比较个股增量。",
        "candidate_ledger": [
            {
                "ts_code": "000001.SZ",
                "name": "平安银行",
                "opportunity_type": "independent_price_anomaly",
                "source_skills": ["analyzing-price-trading"],
                "final_fate": "selected",
                "primary_reason": "相对市场和行业的连续增量仍在。",
            }
        ],
        "decision_trace": [
            {
                "ts_code": "000001.SZ",
                "source_skill": "analyzing-price-trading",
                "evidence_id": "raw_price",
                "evidence_version": "price-analysis-context-v2",
                "evidence_status_at_use": "observation_only",
                "decision_role": "support",
                "decision_changed": "promoted",
                "formation_values": {
                    "return_5d": 0.05,
                    "relative_industry_return_5d": 0.03,
                },
            }
        ],
        "research_result": _one_stock_result(),
    }


def _trace_with_nearest_nonselection() -> dict:
    trace = _one_stock_trace()
    trace["candidate_ledger"].append(
        {
            "ts_code": "600000.SH",
            "name": "浦发银行",
            "opportunity_type": "company_catalyst",
            "source_skills": ["researching-company-events"],
            "final_fate": "rejected",
            "primary_reason": "催化证据仍不足。",
        }
    )
    trace["decision_trace"].append(
        {
            "ts_code": "600000.SH",
            "source_skill": "analyzing-price-trading",
            "evidence_id": "raw_price",
            "evidence_version": "price-analysis-context-v2",
            "evidence_status_at_use": "observation_only",
            "decision_role": "comparison",
            "decision_changed": "rejected",
            "formation_values": {"return_5d": 0.01},
        }
    )
    trace["research_result"]["nearest_nonselections"].append(
        {
            "ts_code": "600000.SH",
            "name": "浦发银行",
            "opportunity_type": "company_catalyst",
            "selection_reason": "公司催化存在。",
            "strongest_counterevidence": "证据强度仍不足。",
            "nearest_comparison": "与入选股相比剩余路径较弱。",
        }
    )
    return trace


def _record_trace_for_test(
    trace: dict,
    tmp_path: Path,
    *,
    csv_path: Path | None = None,
    archive_dir: Path | None = None,
    data: FakeData | None = None,
    pending_text: str | None = None,
) -> tuple[RunSummary, Path, Path, Path]:
    pending = tmp_path / "pending.json"
    pending.write_text(
        pending_text or json.dumps(trace, ensure_ascii=False),
        encoding="utf-8",
    )
    if csv_path is None:
        csv_path = tmp_path / "forward.csv"
        _write_csv(csv_path, [])
    archive_dir = archive_dir or tmp_path / "archive"
    data = data or FakeData(
        open_dates=[date(2026, 8, 18), date(2026, 8, 19)]
    )
    moment = datetime(2026, 8, 19, 9, 10, tzinfo=SHANGHAI)
    summary = record_daily_trace(
        trace,
        pending_path=pending,
        archive_dir=archive_dir,
        csv_path=csv_path,
        data=data,
        clock=_clock(moment),
        formation_date=date(2026, 8, 18),
        action_date=date(2026, 8, 19),
        selection_as_of=moment,
    )
    archive = archive_dir / "research-trace-2026-08-18.json"
    return summary, pending, archive, csv_path


def _run(
    tmp_path: Path,
    *,
    now: callable,
    data: FakeData,
    research: FakeResearch,
    rows: list[dict[str, str]] | None = None,
    sleep: callable = lambda _seconds: None,
    formation_date: date | None = None,
    action_date: date | None = None,
    selection_as_of: datetime | None = None,
):
    csv_path = tmp_path / "forward.csv"
    _write_csv(csv_path, rows or [])
    request = {}
    if formation_date is not None:
        request["formation_date"] = formation_date
    if action_date is not None:
        request["action_date"] = action_date
    if selection_as_of is not None:
        request["selection_as_of"] = selection_as_of
    prepared = prepare_daily_selection(
        csv_path=csv_path,
        data=data,
        clock=now,
        sleep=sleep,
        **request,
    )
    if prepared.status != "ready_for_research":
        return prepared, csv_path
    try:
        result = research.execute(prompt="top-level Codex result")
    except Exception as error:
        return RunSummary(
            status="external_research_failed",
            started_at=prepared.started_at,
            formation_date=prepared.formation_date,
            action_date=prepared.action_date,
            selection_as_of=prepared.selection_as_of,
            data_ready=True,
            error=str(error),
        ), csv_path
    summary = record_daily_selection(
        result,
        csv_path=csv_path,
        data=data,
        clock=now,
        sleep=sleep,
        formation_date=date.fromisoformat(prepared.formation_date),
        action_date=date.fromisoformat(prepared.action_date),
        selection_as_of=datetime.fromisoformat(prepared.selection_as_of),
    )
    return summary, csv_path


def test_non_trading_day_does_not_call_codex_or_write(tmp_path: Path) -> None:
    original = [_row(formation_date="2026-08-14", validation_mode="reconstructed")]
    research = FakeResearch(_empty_result())
    summary, csv_path = _run(
        tmp_path,
        now=_clock(datetime(2026, 8, 22, 9, 10, tzinfo=SHANGHAI)),
        data=FakeData(
            open_dates=[date(2026, 8, 21)],
            action_date_status=False,
        ),
        research=research,
        rows=original,
    )

    assert summary.status == "non_trading_day"
    assert research.calls == 0
    assert _read_csv(csv_path) == original


def test_missing_action_date_calendar_is_data_not_ready_not_non_trading(
    tmp_path: Path,
) -> None:
    original = [_row(formation_date="2026-08-14", validation_mode="reconstructed")]
    research = FakeResearch(_empty_result())
    summary, csv_path = _run(
        tmp_path,
        now=_clock(datetime(2026, 8, 19, 9, 5, tzinfo=SHANGHAI)),
        data=FakeData(
            open_dates=[date(2026, 8, 18)],
            action_date_status=None,
        ),
        research=research,
        rows=original,
    )

    assert summary.status == "data_not_ready"
    assert summary.error == "action_date_calendar_missing"
    assert research.calls == 0
    assert _read_csv(csv_path) == original


def test_next_morning_data_becoming_ready_during_wait_continues(
    tmp_path: Path,
) -> None:
    research = FakeResearch(_empty_result())
    data = FakeData(
        open_dates=[date(2026, 8, 18), date(2026, 8, 19)],
        ready_states=[False, True],
    )
    start = datetime(2026, 8, 19, 9, 5, tzinfo=SHANGHAI)
    later = start.replace(second=30)
    sleeps: list[float] = []

    summary, csv_path = _run(
        tmp_path,
        now=_clock(start, start, later, later, later, later),
        data=data,
        research=research,
        sleep=sleeps.append,
    )

    assert summary.status == "selection_frozen"
    assert data.health_calls == 3
    assert sleeps == [30]
    assert research.calls == 1
    assert len(_read_csv(csv_path)) == 1


def test_unready_next_morning_data_keeps_waiting_past_0915(tmp_path: Path) -> None:
    research = FakeResearch(_empty_result())
    checks = [
        datetime(2026, 8, 19, 9, 5 + second // 60, second % 60, tzinfo=SHANGHAI)
        for second in range(0, 11 * 60 + 1, 30)
    ]
    sleeps: list[float] = []
    data = FakeData(
        open_dates=[date(2026, 8, 18), date(2026, 8, 19)],
        ready_states=[False] * 21 + [True],
    )
    summary, csv_path = _run(
        tmp_path,
        now=_clock(checks[0], *checks),
        data=data,
        research=research,
        sleep=sleeps.append,
    )

    assert summary.status == "selection_frozen"
    assert data.health_calls == 23
    assert sleeps == [30] * 21
    assert research.calls == 1
    assert len(_read_csv(csv_path)) == 1


def test_existing_forward_empty_decision_is_idempotent(tmp_path: Path) -> None:
    existing = _row(
        formation_date="2026-08-18",
        action_date="2026-08-19",
        final_fate="empty_selection",
        validation_mode="forward",
    )
    research = FakeResearch(_one_stock_result())
    summary, csv_path = _run(
        tmp_path,
        now=_clock(datetime(2026, 8, 19, 9, 10, tzinfo=SHANGHAI)),
        data=FakeData(open_dates=[date(2026, 8, 18), date(2026, 8, 19)]),
        research=research,
        rows=[existing],
    )

    assert summary.status == "already_selected"
    assert research.calls == 0
    assert _read_csv(csv_path) == [existing]


def test_existing_reconstructed_decision_blocks_duplicate_selection(
    tmp_path: Path,
) -> None:
    reconstructed = _row(
        formation_date="2026-08-18",
        action_date="2026-08-19",
        ts_code="300548.SZ",
        name="长芯博创",
        final_fate="selected",
        priority="1",
        validation_mode="reconstructed",
    )
    research = FakeResearch(_one_stock_result())
    moment = datetime(2026, 8, 19, 9, 10, tzinfo=SHANGHAI)
    summary, csv_path = _run(
        tmp_path,
        now=_clock(moment, moment, moment),
        data=FakeData(open_dates=[date(2026, 8, 18), date(2026, 8, 19)]),
        research=research,
        rows=[reconstructed],
    )

    assert summary.status == "already_selected"
    assert research.calls == 0
    assert _read_csv(csv_path) == [reconstructed]


def test_top_level_result_uses_selection_semantics_and_frozen_context(
    tmp_path: Path,
) -> None:
    research = FakeResearch(_one_stock_result())
    moment = datetime(2026, 8, 19, 9, 10, tzinfo=SHANGHAI)

    summary, csv_path = _run(
        tmp_path,
        now=_clock(moment, moment, moment),
        data=FakeData(open_dates=[date(2026, 8, 18), date(2026, 8, 19)]),
        research=research,
    )

    rows = _read_csv(csv_path)
    assert summary.status == "selection_frozen"
    assert research.calls == 1
    assert {row["validation_mode"] for row in rows} == {"selection"}
    assert rows[-1]["final_fate"] == "selected"
    assert rows[-1]["priority"] == "1"
    assert rows[-1]["selection_as_of"] == "2026-08-19T09:10:00+08:00"
    assert research.prompt == "top-level Codex result"


def test_complete_trace_records_the_same_forward_rows_and_is_archived(
    tmp_path: Path,
) -> None:
    trace = _one_stock_trace()
    pending = tmp_path / "pending-trace-2026-08-18.json"
    pending.write_text(json.dumps(trace, ensure_ascii=False), encoding="utf-8")
    direct_csv = tmp_path / "direct.csv"
    trace_csv = tmp_path / "trace.csv"
    _write_csv(direct_csv, [])
    _write_csv(trace_csv, [])
    archive_dir = tmp_path / "archive"
    moment = datetime(2026, 8, 19, 9, 10, tzinfo=SHANGHAI)
    data = FakeData(open_dates=[date(2026, 8, 18), date(2026, 8, 19)])

    direct = record_daily_selection(
        trace["research_result"],
        csv_path=direct_csv,
        data=data,
        clock=_clock(moment, moment),
        formation_date=date(2026, 8, 18),
        action_date=date(2026, 8, 19),
        selection_as_of=moment,
    )
    recorded = record_daily_trace(
        trace,
        pending_path=pending,
        archive_dir=archive_dir,
        csv_path=trace_csv,
        data=data,
        clock=_clock(moment, moment),
        formation_date=date(2026, 8, 18),
        action_date=date(2026, 8, 19),
        selection_as_of=moment,
    )

    archive = archive_dir / "research-trace-2026-08-18.json"
    assert direct.status == recorded.status == "selection_frozen"
    assert _read_csv(trace_csv) == _read_csv(direct_csv)
    assert not pending.exists()
    assert json.loads(archive.read_text(encoding="utf-8")) == trace


def test_already_selected_recovers_when_trace_archive_is_missing(
    tmp_path: Path,
) -> None:
    trace = _one_stock_trace()
    csv_path = tmp_path / "forward.csv"
    _write_csv(csv_path, [])
    archive_dir = tmp_path / "archive"
    moment = datetime(2026, 8, 19, 9, 10, tzinfo=SHANGHAI)
    data = FakeData(open_dates=[date(2026, 8, 18), date(2026, 8, 19)])

    first = record_daily_selection(
        trace["research_result"],
        csv_path=csv_path,
        data=data,
        clock=_clock(moment),
        formation_date=date(2026, 8, 18),
        action_date=date(2026, 8, 19),
        selection_as_of=moment,
    )
    recovered, pending, archive, _ = _record_trace_for_test(
        trace,
        tmp_path,
        csv_path=csv_path,
        archive_dir=archive_dir,
        data=data,
    )

    assert first.status == "selection_frozen"
    assert recovered.status == "already_selected"
    assert not pending.exists()
    assert json.loads(archive.read_text(encoding="utf-8")) == trace


def test_already_selected_with_same_trace_is_idempotent_without_overwrite(
    tmp_path: Path,
) -> None:
    trace = _one_stock_trace()
    archive_dir = tmp_path / "archive"
    data = FakeData(open_dates=[date(2026, 8, 18), date(2026, 8, 19)])

    first, pending, archive, csv_path = _record_trace_for_test(
        trace,
        tmp_path,
        archive_dir=archive_dir,
        data=data,
    )
    archived_bytes = archive.read_bytes()
    reordered = dict(reversed(list(trace.items())))
    pending_text = json.dumps(reordered, ensure_ascii=False, indent=2)
    repeated, _, _, _ = _record_trace_for_test(
        reordered,
        tmp_path,
        csv_path=csv_path,
        archive_dir=archive_dir,
        data=data,
        pending_text=pending_text,
    )

    assert first.status == "selection_frozen"
    assert repeated.status == "already_selected"
    assert archive.read_bytes() == archived_bytes


def test_trace_conflict_preserves_archive_and_pending(tmp_path: Path) -> None:
    trace = _one_stock_trace()
    archive_dir = tmp_path / "archive"
    data = FakeData(open_dates=[date(2026, 8, 18), date(2026, 8, 19)])

    first, _, archive, csv_path = _record_trace_for_test(
        trace,
        tmp_path,
        archive_dir=archive_dir,
        data=data,
    )
    archived_bytes = archive.read_bytes()
    conflicting = json.loads(json.dumps(trace, ensure_ascii=False))
    conflicting["market_search_context"] = "冲突的市场搜索上下文。"
    pending_text = json.dumps(conflicting, ensure_ascii=False)
    repeated, pending, _, _ = _record_trace_for_test(
        conflicting,
        tmp_path,
        csv_path=csv_path,
        archive_dir=archive_dir,
        data=data,
        pending_text=pending_text,
    )

    assert first.status == "selection_frozen"
    assert repeated.status == "invalid_result"
    assert repeated.error == "trace_conflict"
    assert archive.read_bytes() == archived_bytes
    assert pending.read_text(encoding="utf-8") == pending_text


def test_trace_date_mismatch_is_rejected_without_writing_or_moving(
    tmp_path: Path,
) -> None:
    trace = _one_stock_trace()
    trace["formation_date"] = "2026-08-17"
    pending = tmp_path / "pending.json"
    pending.write_text(json.dumps(trace, ensure_ascii=False), encoding="utf-8")
    csv_path = tmp_path / "forward.csv"
    _write_csv(csv_path, [])
    moment = datetime(2026, 8, 19, 9, 10, tzinfo=SHANGHAI)

    summary = record_daily_trace(
        trace,
        pending_path=pending,
        archive_dir=tmp_path / "archive",
        csv_path=csv_path,
        data=FakeData(open_dates=[date(2026, 8, 18), date(2026, 8, 19)]),
        clock=_clock(moment),
        formation_date=date(2026, 8, 18),
        action_date=date(2026, 8, 19),
        selection_as_of=moment,
    )

    assert summary.status == "invalid_result"
    assert summary.error == "trace_formation_date_mismatch"
    assert _read_csv(csv_path) == []
    assert pending.exists()


@pytest.mark.parametrize(
    ("mutate", "expected_error"),
    [
        (
            lambda trace: trace["candidate_ledger"].append(
                dict(trace["candidate_ledger"][0])
            ),
            "duplicate_candidate_codes",
        ),
        (
            lambda trace: trace["decision_trace"][0].update(
                ts_code="600000.SH"
            ),
            "decision_trace_candidate_missing",
        ),
        (
            lambda trace: trace["candidate_ledger"][0].update(
                final_fate="rejected"
            ),
            "selected_candidate_fate_mismatch",
        ),
        (
            lambda trace: trace.update(decision_trace=[]),
            "price_evidence_count_invalid",
        ),
    ],
)
def test_trace_candidate_conservation_and_price_references_are_enforced(
    tmp_path: Path,
    mutate: Callable[[dict], None],
    expected_error: str,
) -> None:
    trace = _one_stock_trace()
    mutate(trace)
    pending = tmp_path / "pending.json"
    pending.write_text(json.dumps(trace, ensure_ascii=False), encoding="utf-8")
    csv_path = tmp_path / "forward.csv"
    _write_csv(csv_path, [])
    moment = datetime(2026, 8, 19, 9, 10, tzinfo=SHANGHAI)

    summary = record_daily_trace(
        trace,
        pending_path=pending,
        archive_dir=tmp_path / "archive",
        csv_path=csv_path,
        data=FakeData(open_dates=[date(2026, 8, 18), date(2026, 8, 19)]),
        clock=_clock(moment),
        formation_date=date(2026, 8, 18),
        action_date=date(2026, 8, 19),
        selection_as_of=moment,
    )

    assert summary.status == "invalid_result"
    assert summary.error == expected_error
    assert _read_csv(csv_path) == []
    assert pending.exists()


@pytest.mark.parametrize(
    "source_skill",
    ["interpreting-market-macro", "orchestrating-stock-research"],
)
def test_trace_rejects_non_discovery_candidate_source_skills(
    tmp_path: Path,
    source_skill: str,
) -> None:
    trace = _one_stock_trace()
    trace["candidate_ledger"][0]["source_skills"] = [source_skill]
    summary, _, _, _ = _record_trace_for_test(trace, tmp_path)

    assert summary.status == "invalid_result"
    assert summary.error == "invalid_trace_structure"


@pytest.mark.parametrize(
    ("field", "value"),
    [("name", "浦发银行"), ("opportunity_type", "company_catalyst")],
)
def test_trace_rejects_selected_candidate_identity_mismatch(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    trace = _one_stock_trace()
    trace["research_result"]["selected_stocks"][0][field] = value
    summary, _, _, _ = _record_trace_for_test(trace, tmp_path)

    assert summary.status == "invalid_result"
    assert summary.error == "selected_candidate_identity_mismatch"


@pytest.mark.parametrize(
    ("field", "value"),
    [("name", "上海银行"), ("opportunity_type", "sector_diffusion")],
)
def test_trace_rejects_nearest_candidate_identity_mismatch(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    trace = _trace_with_nearest_nonselection()
    trace["research_result"]["nearest_nonselections"][0][field] = value
    summary, _, _, _ = _record_trace_for_test(trace, tmp_path)

    assert summary.status == "invalid_result"
    assert summary.error == "nearest_candidate_identity_mismatch"


def test_trace_rejects_selected_fate_for_nearest_nonselection(
    tmp_path: Path,
) -> None:
    trace = _trace_with_nearest_nonselection()
    trace["candidate_ledger"][1]["final_fate"] = "selected"
    summary, _, _, _ = _record_trace_for_test(trace, tmp_path)

    assert summary.status == "invalid_result"
    assert summary.error == "nearest_candidate_fate_mismatch"


def test_trace_with_consistent_nearest_nonselection_continues(tmp_path: Path) -> None:
    trace = _trace_with_nearest_nonselection()
    summary, _, _, _ = _record_trace_for_test(trace, tmp_path)

    assert summary.status == "selection_frozen"


@pytest.mark.parametrize("result", [{"research_complete": True}])
def test_invalid_top_level_output_never_writes(
    tmp_path: Path,
    result: dict | Exception,
) -> None:
    research = FakeResearch(result)
    moment = datetime(2026, 8, 19, 9, 10, tzinfo=SHANGHAI)
    summary, csv_path = _run(
        tmp_path,
        now=_clock(moment, moment, moment),
        data=FakeData(open_dates=[date(2026, 8, 18), date(2026, 8, 19)]),
        research=research,
    )

    assert summary.status == "invalid_result"
    assert _read_csv(csv_path) == []


def test_incomplete_research_is_not_frozen_as_an_empty_selection(
    tmp_path: Path,
) -> None:
    result = _empty_result()
    result.update(
        research_completed=False,
        point_in_time_evidence_verified=False,
        failure_reason="本地事实仓查询失败",
    )
    moment = datetime(2026, 8, 19, 9, 10, tzinfo=SHANGHAI)

    summary, csv_path = _run(
        tmp_path,
        now=_clock(moment, moment, moment),
        data=FakeData(open_dates=[date(2026, 8, 18), date(2026, 8, 19)]),
        research=FakeResearch(result),
    )

    assert summary.status == "invalid_result"
    assert summary.error == "research_incomplete"
    assert _read_csv(csv_path) == []


def test_result_finishing_after_open_is_still_written(tmp_path: Path) -> None:
    start = datetime(2026, 8, 19, 9, 10, tzinfo=SHANGHAI)
    summary, csv_path = _run(
        tmp_path,
        now=_clock(start, start, start.replace(hour=10, minute=30)),
        data=FakeData(open_dates=[date(2026, 8, 18), date(2026, 8, 19)]),
        research=FakeResearch(_one_stock_result()),
    )

    assert summary.status == "selection_frozen"
    assert len(_read_csv(csv_path)) == 1


def test_retry_after_open_uses_explicit_preopen_selection_context(
    tmp_path: Path,
) -> None:
    current = datetime(2026, 8, 20, 11, 0, tzinfo=SHANGHAI)
    frozen = datetime(2026, 8, 20, 9, 5, 2, tzinfo=SHANGHAI)
    summary, csv_path = _run(
        tmp_path,
        now=_clock(current, current, current),
        data=FakeData(open_dates=[date(2026, 8, 19), date(2026, 8, 20)]),
        research=FakeResearch(_one_stock_result()),
        formation_date=date(2026, 8, 19),
        action_date=date(2026, 8, 20),
        selection_as_of=frozen,
    )

    rows = _read_csv(csv_path)
    assert summary.status == "selection_frozen"
    assert summary.formation_date == "2026-08-19"
    assert summary.selection_as_of == "2026-08-20T09:05:02+08:00"
    assert rows[0]["action_date"] == "2026-08-20"
    assert rows[0]["as_of"] == "2026-08-20T09:05:02+08:00"
    assert rows[0]["validation_mode"] == "selection"


def test_retry_rejects_selection_cutoff_at_market_open(tmp_path: Path) -> None:
    current = datetime(2026, 8, 20, 11, 0, tzinfo=SHANGHAI)
    research = FakeResearch(_one_stock_result())
    summary, csv_path = _run(
        tmp_path,
        now=_clock(current),
        data=FakeData(open_dates=[date(2026, 8, 19), date(2026, 8, 20)]),
        research=research,
        formation_date=date(2026, 8, 19),
        action_date=date(2026, 8, 20),
        selection_as_of=datetime(2026, 8, 20, 9, 30, tzinfo=SHANGHAI),
    )

    assert summary.status == "invalid_selection_cutoff"
    assert summary.error == "selection_as_of_must_precede_action_open"
    assert research.calls == 0
    assert _read_csv(csv_path) == []


def test_empty_selection_is_explicitly_frozen(tmp_path: Path) -> None:
    moment = datetime(2026, 8, 19, 9, 10, tzinfo=SHANGHAI)
    summary, csv_path = _run(
        tmp_path,
        now=_clock(moment, moment, moment),
        data=FakeData(open_dates=[date(2026, 8, 18), date(2026, 8, 19)]),
        research=FakeResearch(_empty_result()),
    )

    rows = _read_csv(csv_path)
    assert summary.new_forward_rows == 1
    assert rows[0]["final_fate"] == "empty_selection"
    assert rows[0]["ts_code"] == ""
    assert rows[0]["validation_mode"] == "selection"


def test_d20_is_unchanged_until_all_twenty_prices_exist() -> None:
    days = [date(2026, 7, day) for day in range(1, 21)]
    row = _row(
        formation_date="2026-06-30",
        action_date="2026-07-01",
        ts_code="000001.SZ",
        final_fate="selected",
        hit_20pct_close_within_20d="false",
    )

    updated, count = apply_mature_settlements(
        [row],
        open_dates=days,
        price_loader=lambda _code, _days: [
            PricePoint(day, 10.0, 10.0) for day in days[:19]
        ],
    )

    assert count == 0
    assert updated == [row]


def test_d20_settles_once_from_adjusted_open_and_closes() -> None:
    days = [date(2026, 7, day) for day in range(1, 21)]
    closes = [10.0, 10.5, 11.0, 11.5, 12.0, 12.5] + [10.5] * 14
    row = _row(
        formation_date="2026-06-30",
        action_date="2026-07-01",
        ts_code="000001.SZ",
        final_fate="selected",
        validation_mode="forward",
    )
    prices = [
        PricePoint(day, adjusted_open=10.0, adjusted_close=close)
        for day, close in zip(days, closes, strict=True)
    ]

    updated, count = apply_mature_settlements(
        [row],
        open_dates=days,
        price_loader=lambda _code, _days: prices,
    )
    repeated, repeated_count = apply_mature_settlements(
        updated,
        open_dates=days,
        price_loader=lambda _code, _days: prices,
    )

    assert count == 1
    assert updated[0]["hit_20pct_close_within_20d"] == "true"
    assert updated[0]["first_hit_day"] == "5"
    assert updated[0]["max_close_return_20d"] == "25"
    assert updated[0]["terminal_return_20d"] == "5"
    assert repeated_count == 0
    assert repeated == updated


def test_runtime_log_is_initialized_once_from_docs_history(tmp_path: Path) -> None:
    docs_log = tmp_path / "docs/forward-selection-log.csv"
    docs_log.parent.mkdir()
    _write_csv(
        docs_log,
        [
            _row(
                formation_date="2026-08-17",
                ts_code="300548.SZ",
                name="长芯博创",
                validation_mode="reconstructed",
            )
        ],
    )

    runtime_log = prepare_runtime_log(tmp_path)

    assert runtime_log == (
        tmp_path / "local_archive/forward_selection/forward-selection-log.csv"
    )
    assert _read_csv(runtime_log) == _read_csv(docs_log)

    _write_csv(runtime_log, [_row(formation_date="keep-local")])
    prepare_runtime_log(tmp_path)
    assert _read_csv(runtime_log) == [_row(formation_date="keep-local")]


def test_repository_keeps_only_the_three_data_launchd_templates() -> None:
    root = Path(__file__).resolve().parents[1]
    expected = {"close", "evening", "next-morning"}
    actual = {
        path.name.removesuffix(".plist.example").removeprefix(
            "com.ccrt.stock-analysis-assistant.research-data-"
        )
        for path in (root / "ops/launchd").glob("*.plist.example")
        if "research-data" in path.name
    }
    assert actual == expected
    assert not (
        root
        / "ops/launchd/com.ccrt.stock-analysis-assistant.forward-selection.plist.example"
    ).exists()
