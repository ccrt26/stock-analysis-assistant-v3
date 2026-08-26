from __future__ import annotations

import csv
import json
from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from stock_analyzer.ops.forward_selection import (
    PricePoint,
    RunSummary,
    _parse_main_args,
    apply_mature_settlements,
    main,
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
        stage_status: str | None = "limited",
        feature_ready: dict[str, bool] | None = None,
        stage_started_at: datetime | None = None,
        stage_finished_at: datetime | None = None,
        prices: dict[str, list[PricePoint] | None] | None = None,
    ) -> None:
        self._open_dates = open_dates
        self.action_date_status = action_date_status
        self.ready = ready
        self.ready_states = iter(ready_states) if ready_states is not None else None
        self.stage_status = stage_status
        self.feature_ready = feature_ready or {}
        self.stage_started_at = stage_started_at
        self.stage_finished_at = stage_finished_at
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
        finished = self.stage_finished_at or datetime.combine(
            formation_date + timedelta(days=1),
            datetime.min.time(),
            SHANGHAI,
        ).replace(hour=9, minute=2)
        started = self.stage_started_at or finished.replace(minute=0)
        feature_names = (
            "market_context",
            "sector_hotspot",
            "stock_trading_context",
            "price_analysis_context",
        )
        feature_states = {
            name: ready and self.feature_ready.get(name, True)
            for name in feature_names
        }
        return {
            "data_date": formation_date.isoformat(),
            "complete_core_date": ready,
            "derived_ready_for_research": all(feature_states.values()),
            "derived_features": [
                {
                    "feature_set": name,
                    "ready": available,
                    "limitations": [],
                }
                for name, available in feature_states.items()
            ],
            "latest_stage_runs": [] if self.stage_status is None else [
                {
                    "stage": "next-morning",
                    "data_date": formation_date.isoformat(),
                    "status": self.stage_status,
                    "started_at": started.isoformat(),
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
        "trace_version": "daily-research-trace-v3",
        "formation_date": "2026-08-18",
        "action_date": "2026-08-19",
        "as_of": "2026-08-19T09:10:00+08:00",
        "market_search_context": (
            "普通股票参与宽度与指数同步，继续比较个股增量。"
        ),
        "market_propagation_environment": {
            "environment_id": "market-2026-08-18",
            "propagation_state": "neutral",
            "breadth": "上涨宽度尚可，但多日连续性一般。",
            "liquidity": "成交额未显示全市场增量放大。",
            "risk_appetite": "风险偏好中性。",
            "style": "没有单一风格形成压倒性传播。",
            "concentration": "正收益并非只集中于极少数股票。",
            "evidence_basis": ["market-context-v3"],
        },
        "candidate_ledger": [
            {
                "ts_code": "000001.SZ",
                "name": "平安银行",
                "opportunity_type": "independent_price_anomaly",
                "source_skills": ["analyzing-price-trading"],
                "final_fate": "selected",
                "primary_reason": "相对市场和行业的连续增量仍在。",
                "research_thesis": {
                    "engine_type": "stock_specific_demand",
                    "engine_status": "confirmed",
                    "market_recognition": {
                        "status": "confirmed",
                        "market_environment_id": "market-2026-08-18",
                        "basis": "相对市场和行业的价格成交共同确认。",
                    },
                    "company_information_novelty": {
                        "disclosure_novelty": "not_applicable",
                        "new_information_level": "not_applicable",
                        "basis": "独立价格需求命题不依赖公司新事件。",
                    },
                    "sector_leader_cluster": None,
                    "action_condition_decision_id": None,
                    "catalyst": (
                        "没有独立公司公告催化，新增信息来自价格相对增量。"
                    ),
                    "short_term_engine": (
                        "相对市场和行业的连续价量推进显示股票需求增加。"
                    ),
                    "propagation": (
                        "个股需求独立增强，未把行业标签当作传播证据。"
                    ),
                    "price_confirmation": "多窗口相对收益和成交推进共同为正。",
                    "remaining_path": "累计涨幅和波动尚未消耗全部可参与路径。",
                    "fundamental_anchor": "主营和财务事实提供有限经营锚。",
                    "company_risk": "缺少新公司事件，经营锚不能替代价格确认。",
                    "critical_unknown": "相对增量能否在行动日继续仍未知。",
                    "decision_ids": ["company-anchor-risk", "price-confirmation"],
                },
            }
        ],
        "decision_trace": [
            {
                "decision_id": "company-anchor-risk",
                "ts_code": "000001.SZ",
                "source_skill": "researching-company-events",
                "evidence_id": "company_fundamentals",
                "evidence_version": "research-registry-2026-08-21",
                "evidence_status_at_use": "observation_only",
                "decision_role": "support",
                "decision_changed": "no_change",
                "formation_values": {"business_link_verified": True},
            },
            {
                "decision_id": "price-confirmation",
                "ts_code": "000001.SZ",
                "source_skill": "analyzing-price-trading",
                "evidence_id": "raw_price",
                "evidence_version": "price-analysis-context-v2",
                "evidence_status_at_use": "observation_only",
                "decision_role": "support",
                "decision_changed": "promoted",
                "formation_values": {
                    "observation_date": "2026-08-18",
                    "return_5d": 0.05,
                    "amount_ratio_last_20d": 1.2,
                    "relative_market_5d": 0.04,
                    "relative_industry_return_5d": 0.03,
                },
            }
        ],
        "research_result": _one_stock_result(),
    }


def _v4_trace() -> dict:
    formation = date(2026, 8, 25)
    action = date(2026, 8, 26)
    as_of = datetime(2026, 8, 26, 9, 5, tzinfo=SHANGHAI)
    return {
        "trace_version": "daily-research-trace-v4",
        "formation_date": formation.isoformat(),
        "action_date": action.isoformat(),
        "as_of": as_of.isoformat(),
        "market_search_context": "核对形成日的相对增量。",
        "market_propagation_mode": "one_day_repair",
        "market_risk_overlays": [],
        "candidate_ledger": [
            {
                "ts_code": "000001.SZ",
                "name": "平安银行",
                "opportunity_type": "independent_price_anomaly",
                "source_skills": ["analyzing-price-trading"],
                "final_fate": "selected",
                "primary_reason": "独立需求增强。",
                "research_thesis": {
                    "engine_type": "independent_demand_acceleration",
                    "engine_status": "active",
                    "market_recognition": {
                        "status": "confirmed",
                        "basis": "相对市场和路径已经确认。",
                    },
                    "company_information": {
                        "first_or_repeat": "not_applicable",
                        "disclosure_chain": {
                            "prior_forecast": None,
                            "forecast_revision": None,
                            "earnings_express": None,
                            "formal_report": None,
                            "correction": None,
                            "comparison_basis": "不适用",
                        },
                        "new_information_level": "not_applicable",
                        "event_id": None,
                        "event_available_at": None,
                        "event_stage": "not_applicable",
                        "business_link": "not_applicable",
                        "materiality": "not_applicable",
                        "tradable_sessions_since_event": None,
                        "basis": "不依赖公司新事件。",
                    },
                    "sector_broad_diffusion": None,
                    "sector_leader_cluster": None,
                    "action_condition_decision_id": None,
                    "catalyst": "没有公司新事件。",
                    "short_term_engine": "独立需求加速。",
                    "propagation": "个股自身推进。",
                    "price_confirmation": "价量已经确认。",
                    "remaining_path": "仍有剩余路径。",
                    "fundamental_anchor": "公司事实提供有限锚。",
                    "company_risk": "没有新催化。",
                    "critical_unknown": "需求能否延续。",
                    "decision_ids": ["company", "price"],
                },
            }
        ],
        "decision_trace": [
            {
                "decision_id": "company",
                "ts_code": "000001.SZ",
                "source_skill": "researching-company-events",
                "evidence_id": "company_fundamentals",
                "evidence_version": "v4",
                "evidence_status_at_use": "observation_only",
                "decision_role": "counter",
                "decision_changed": "no_change",
                "formation_values": {"business_link_verified": True},
            },
            {
                "decision_id": "price",
                "ts_code": "000001.SZ",
                "source_skill": "analyzing-price-trading",
                "evidence_id": "raw_price",
                "evidence_version": "price-analysis-context-v2",
                "evidence_status_at_use": "provisional",
                "decision_role": "support",
                "decision_changed": "promoted",
                "formation_values": {
                    "observation_date": formation.isoformat(),
                    "return_5d": 0.05,
                    "amount_ratio_last_20d": 1.2,
                    "relative_market_5d": 0.04,
                    "volume_price_efficiency_5d": 0.4,
                },
            },
        ],
        "research_result": _one_stock_result(),
    }


def _v4_sector_trace() -> dict:
    trace = _v4_trace()
    candidate = trace["candidate_ledger"][0]
    candidate["opportunity_type"] = "sector_diffusion"
    candidate["source_skills"] = ["researching-sectors-industries"]
    trace["research_result"]["selected_stocks"][0][
        "opportunity_type"
    ] = "sector_diffusion"
    thesis = candidate["research_thesis"]
    thesis["engine_type"] = "sector_leader_cluster"
    thesis["sector_leader_cluster"] = {
        "cluster_id": "bank-cluster",
        "group_code": "801780.SI",
        "group_name": "银行",
        "members": [
            {
                "ts_code": code,
                "relative_market_3d": value,
                "relative_market_5d": value + 0.02,
                "industry_percentile_5d": percentile,
            }
            for code, value, percentile in (
                ("000001.SZ", 0.03, 0.90),
                ("600000.SH", 0.02, 0.85),
                ("601398.SH", 0.01, 0.80),
            )
        ],
        "effective_member_count": 50,
        "qualifying_leader_count": 3,
        "required_leader_count": 3,
        "relative_return_3d": 0.02,
        "relative_return_5d": 0.04,
        "turnover_share_change_5d": 0.01,
        "top1_positive_contribution": 0.50,
        "candidate_industry_percentile_5d": 0.90,
        "candidate_role": "leader_confirmed",
        "strongest_counterevidence": "仍有集中风险。",
        "unknowns": [],
    }
    trace["decision_trace"].append(
        {
            "decision_id": "sector",
            "ts_code": "000001.SZ",
            "source_skill": "researching-sectors-industries",
            "evidence_id": "sector_leader_cluster",
            "evidence_version": "v4",
            "evidence_status_at_use": "provisional",
            "decision_role": "support",
            "decision_changed": "promoted",
            "formation_values": {"qualifying_leader_count": 3},
        }
    )
    thesis["decision_ids"].append("sector")
    return trace


def _v4_fresh_event_trace() -> dict:
    trace = _v4_trace()
    candidate = trace["candidate_ledger"][0]
    candidate["opportunity_type"] = "company_catalyst"
    candidate["source_skills"] = ["researching-company-events"]
    trace["research_result"]["selected_stocks"][0][
        "opportunity_type"
    ] = "company_catalyst"
    event_time = "2026-08-25T19:34:27+08:00"
    thesis = candidate["research_thesis"]
    thesis.update(
        engine_type="fresh_event_pending",
        engine_status="conditional",
        market_recognition={"status": "pending", "basis": "尚无首日。"},
        company_information={
            "first_or_repeat": "first",
            "disclosure_chain": {
                "prior_forecast": None,
                "forecast_revision": None,
                "earnings_express": None,
                "formal_report": "ANN",
                "correction": None,
                "comparison_basis": "首次披露",
            },
            "new_information_level": "substantive_new",
            "event_id": "ANN",
            "event_available_at": event_time,
            "event_stage": "signed",
            "business_link": "direct",
            "materiality": "重大",
            "tradable_sessions_since_event": 0,
            "basis": "形成日收盘后首次披露。",
        },
        action_condition_decision_id="price",
    )
    trace["decision_trace"][0].update(
        evidence_id="company_event",
        decision_role="support",
        formation_values={"event_id": "ANN", "materiality_verified": True},
    )
    trace["decision_trace"][1].update(
        evidence_id="event_price_reaction",
        evidence_version="event-price-reaction-v3",
        decision_role="action_condition",
        formation_values={
            "event_id": "ANN",
            "event_available_at": event_time,
            "reaction_start_date": "2026-08-26",
            "reaction_window_status": "awaiting_first_session",
            "observed_reaction_sessions": 0,
            "event_timing_status": "after_close",
            "pre_event_relative_market_5d": -0.02,
            "pre_event_return_20d": 0.08,
        },
    )
    return trace


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
            "research_thesis": {
                "engine_type": "company_event",
                "engine_status": "unconfirmed",
                "market_recognition": {
                    "status": "absent",
                    "market_environment_id": "market-2026-08-18",
                    "basis": "价格比较未显示独立识别。",
                },
                "company_information_novelty": {
                    "disclosure_novelty": "history_insufficient",
                    "new_information_level": "unknown",
                    "basis": "形成日历史披露不足以确认首次或增量。",
                },
                "sector_leader_cluster": None,
                "action_condition_decision_id": None,
                "catalyst": "存在公司线索，但材料性仍未确认。",
                "short_term_engine": "尚未建立可验证的短期需求发动机。",
                "propagation": "未观察到板块或股票自身需求传播。",
                "price_confirmation": "价格只用于落选比较，不构成支持。",
                "remaining_path": "因发动机未确认，剩余路径保持未知。",
                "fundamental_anchor": "可见公司事实只构成有限经营锚。",
                "company_risk": "披露历史与事件材料性不足。",
                "critical_unknown": "是否存在首次且重大的新增信息。",
                "decision_ids": ["nearest-price", "nearest-company"],
            },
        }
    )
    trace["decision_trace"].append(
        {
            "decision_id": "nearest-company",
            "ts_code": "600000.SH",
            "source_skill": "researching-company-events",
            "evidence_id": "company_fundamentals",
            "evidence_version": "research-registry-2026-08-21",
            "evidence_status_at_use": "provisional",
            "decision_role": "counter",
            "decision_changed": "rejected",
            "formation_values": {"novelty_status": "history_insufficient"},
        }
    )
    trace["decision_trace"].append(
        {
            "decision_id": "nearest-price",
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
    if prepared.status not in {
        "ready_for_research",
        "ready_for_research_limited",
    }:
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


def test_afternoon_rerun_freezes_the_original_preopen_context(
    tmp_path: Path,
) -> None:
    current = datetime(2026, 8, 26, 16, 24, tzinfo=SHANGHAI)
    csv_path = tmp_path / "forward.csv"
    _write_csv(csv_path, [])

    summary = prepare_daily_selection(
        csv_path=csv_path,
        data=FakeData(
            open_dates=[date(2026, 8, 25), date(2026, 8, 26)]
        ),
        clock=_clock(current, current),
        rerun_date=date(2026, 8, 26),
        sleep=lambda _seconds: pytest.fail("下午补跑不得等待"),
    )

    assert summary.status == "ready_for_research"
    assert summary.run_mode == "rerun"
    assert summary.research_mode == "full"
    assert summary.action_date == "2026-08-26"
    assert summary.formation_date == "2026-08-25"
    assert summary.selection_as_of == "2026-08-26T09:05:00+08:00"
    assert summary.selection_as_of != current.isoformat(timespec="seconds")


def test_afternoon_prepare_without_rerun_stays_outside_window(
    tmp_path: Path,
) -> None:
    current = datetime(2026, 8, 26, 16, 24, tzinfo=SHANGHAI)
    csv_path = tmp_path / "forward.csv"
    _write_csv(csv_path, [])

    summary = prepare_daily_selection(
        csv_path=csv_path,
        data=FakeData(
            open_dates=[date(2026, 8, 25), date(2026, 8, 26)]
        ),
        clock=_clock(current),
    )

    assert summary.status == "outside_selection_window"
    assert summary.research_mode == ""


@pytest.mark.parametrize(
    ("status", "expected_exit"),
    [
        ("ready_for_research", 0),
        ("ready_for_research_limited", 0),
        ("non_trading_day", 0),
        ("outside_selection_window", 2),
        ("data_not_ready", 2),
    ],
)
def test_forward_selection_main_exit_codes(
    tmp_path: Path,
    monkeypatch,
    status: str,
    expected_exit: int,
) -> None:
    import stock_analyzer.ops.forward_selection as module

    csv_path = tmp_path / "forward.csv"
    _write_csv(csv_path, [])
    monkeypatch.setattr(module, "prepare_runtime_log", lambda root: csv_path)
    monkeypatch.setattr(module, "LocalForwardData", lambda *args: object())
    monkeypatch.setattr(
        module,
        "prepare_daily_selection",
        lambda **kwargs: RunSummary(
            status=status,
            started_at="2026-08-26T16:24:00+08:00",
        ),
    )

    assert main(["prepare"]) == expected_exit


def test_rerun_date_cannot_mix_with_explicit_context() -> None:
    with pytest.raises(SystemExit) as error:
        _parse_main_args(
            [
                "prepare",
                "--rerun-date",
                "2026-08-26",
                "--formation-date",
                "2026-08-25",
                "--action-date",
                "2026-08-26",
                "--as-of",
                "2026-08-26T09:05:00+08:00",
            ]
        )

    assert error.value.code == 2


def test_future_rerun_date_is_rejected(tmp_path: Path) -> None:
    current = datetime(2026, 8, 26, 16, 24, tzinfo=SHANGHAI)
    csv_path = tmp_path / "forward.csv"
    _write_csv(csv_path, [])

    summary = prepare_daily_selection(
        csv_path=csv_path,
        data=FakeData(open_dates=[date(2026, 8, 26), date(2026, 8, 27)]),
        clock=_clock(current),
        rerun_date=date(2026, 8, 27),
    )

    assert summary.status == "invalid_selection_context"
    assert summary.error == "rerun_date_must_not_be_future"


def test_non_trading_rerun_date_returns_non_trading_day(
    tmp_path: Path,
) -> None:
    current = datetime(2026, 8, 26, 16, 24, tzinfo=SHANGHAI)
    csv_path = tmp_path / "forward.csv"
    _write_csv(csv_path, [])

    summary = prepare_daily_selection(
        csv_path=csv_path,
        data=FakeData(
            open_dates=[date(2026, 8, 25)],
            action_date_status=False,
        ),
        clock=_clock(current),
        rerun_date=date(2026, 8, 26),
    )

    assert summary.status == "non_trading_day"
    assert summary.run_mode == "rerun"
    assert summary.action_date == "2026-08-26"


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
    assert summary.selection_as_of == checks[0].isoformat(timespec="seconds")


def test_failed_next_morning_stage_with_missing_core_returns_without_sleeping(
    tmp_path: Path,
) -> None:
    start = datetime(2026, 8, 19, 9, 5, tzinfo=SHANGHAI)
    research = FakeResearch(_empty_result())

    summary, _ = _run(
        tmp_path,
        now=_clock(start, start),
        data=FakeData(
            open_dates=[date(2026, 8, 18), date(2026, 8, 19)],
            ready=False,
            stage_status="failed",
        ),
        research=research,
        sleep=lambda _seconds: pytest.fail("终态失败后不应继续等待"),
    )

    assert summary.status == "data_not_ready"
    assert summary.error == "next_morning_stage_failed"
    assert summary.selection_as_of == start.isoformat(timespec="seconds")
    assert research.calls == 0


def test_waiting_upstream_keeps_checking_until_0930_then_runs_limited(
    tmp_path: Path,
) -> None:
    start = datetime(2026, 8, 19, 9, 29, 30, tzinfo=SHANGHAI)
    market_open = start.replace(minute=30, second=0)
    csv_path = tmp_path / "forward.csv"
    _write_csv(csv_path, [])
    sleeps: list[float] = []

    summary = prepare_daily_selection(
        csv_path=csv_path,
        data=FakeData(
            open_dates=[date(2026, 8, 18), date(2026, 8, 19)],
            stage_status="waiting_upstream",
        ),
        clock=_clock(start, start, market_open),
        sleep=sleeps.append,
    )

    assert sleeps == [30]
    assert summary.status == "ready_for_research_limited"
    assert summary.research_mode == "limited"
    assert summary.preopen_event_refresh_complete is False
    assert "行动日前公告补采未完成" in "；".join(summary.limitations)


def test_failed_next_morning_with_core_ready_runs_limited_immediately(
    tmp_path: Path,
) -> None:
    start = datetime(2026, 8, 19, 9, 5, tzinfo=SHANGHAI)
    csv_path = tmp_path / "forward.csv"
    _write_csv(csv_path, [])

    summary = prepare_daily_selection(
        csv_path=csv_path,
        data=FakeData(
            open_dates=[date(2026, 8, 18), date(2026, 8, 19)],
            stage_status="failed",
        ),
        clock=_clock(start, start),
        sleep=lambda _seconds: pytest.fail("次晨任务失败后不得继续等待"),
    )

    assert summary.status == "ready_for_research_limited"
    assert summary.preopen_event_refresh_complete is False


@pytest.mark.parametrize(
    ("missing_feature", "available_field", "limitation_text"),
    [
        (
            "sector_hotspot",
            "sector_research_available",
            "行业研究数据不可用",
        ),
        (
            "stock_trading_context",
            "stock_context_available",
            "个股交易背景不可用",
        ),
    ],
)
def test_optional_derived_feature_missing_allows_limited_rerun(
    tmp_path: Path,
    missing_feature: str,
    available_field: str,
    limitation_text: str,
) -> None:
    current = datetime(2026, 8, 26, 16, 24, tzinfo=SHANGHAI)
    csv_path = tmp_path / "forward.csv"
    _write_csv(csv_path, [])

    summary = prepare_daily_selection(
        csv_path=csv_path,
        data=FakeData(
            open_dates=[date(2026, 8, 25), date(2026, 8, 26)],
            feature_ready={missing_feature: False},
        ),
        clock=_clock(current, current),
        rerun_date=date(2026, 8, 26),
        sleep=lambda _seconds: pytest.fail("下午补跑不得等待"),
    )

    assert summary.status == "ready_for_research_limited"
    assert summary.research_mode == "limited"
    assert getattr(summary, available_field) is False
    assert limitation_text in "；".join(summary.limitations)


@pytest.mark.parametrize(
    "missing_feature",
    ["market_context", "price_analysis_context"],
)
def test_missing_core_feature_blocks_rerun_without_waiting(
    tmp_path: Path,
    missing_feature: str,
) -> None:
    current = datetime(2026, 8, 26, 16, 24, tzinfo=SHANGHAI)
    csv_path = tmp_path / "forward.csv"
    _write_csv(csv_path, [])

    summary = prepare_daily_selection(
        csv_path=csv_path,
        data=FakeData(
            open_dates=[date(2026, 8, 25), date(2026, 8, 26)],
            feature_ready={missing_feature: False},
        ),
        clock=_clock(current, current),
        rerun_date=date(2026, 8, 26),
        sleep=lambda _seconds: pytest.fail("下午补跑不得等待"),
    )

    assert summary.status == "data_not_ready"
    assert summary.research_mode == ""
    assert summary.formation_date == "2026-08-25"
    assert summary.action_date == "2026-08-26"
    assert summary.selection_as_of == "2026-08-26T09:05:00+08:00"


def test_health_summary_for_another_date_cannot_enable_rerun(
    tmp_path: Path,
) -> None:
    current = datetime(2026, 8, 26, 16, 24, tzinfo=SHANGHAI)
    csv_path = tmp_path / "forward.csv"
    _write_csv(csv_path, [])
    data = FakeData(
        open_dates=[date(2026, 8, 25), date(2026, 8, 26)]
    )
    original_health_report = data.health_report

    def wrong_date_health(formation_date: date) -> dict:
        report = original_health_report(formation_date)
        report["data_date"] = "2026-08-24"
        return report

    data.health_report = wrong_date_health  # type: ignore[method-assign]
    summary = prepare_daily_selection(
        csv_path=csv_path,
        data=data,
        clock=_clock(current, current),
        rerun_date=date(2026, 8, 26),
        sleep=lambda _seconds: pytest.fail("下午补跑不得等待"),
    )

    assert summary.status == "data_not_ready"


def test_historical_rerun_accepts_afternoon_stage_completion_without_sleep(
    tmp_path: Path,
) -> None:
    current = datetime(2026, 8, 27, 16, 24, tzinfo=SHANGHAI)
    csv_path = tmp_path / "forward.csv"
    _write_csv(csv_path, [])

    summary = prepare_daily_selection(
        csv_path=csv_path,
        data=FakeData(
            open_dates=[date(2026, 8, 25), date(2026, 8, 26)],
            stage_started_at=datetime(
                2026, 8, 26, 16, 0, tzinfo=SHANGHAI
            ),
            stage_finished_at=datetime(
                2026, 8, 26, 16, 20, tzinfo=SHANGHAI
            ),
        ),
        clock=_clock(current, current),
        rerun_date=date(2026, 8, 26),
        sleep=lambda _seconds: pytest.fail("历史补跑不得等待"),
    )

    assert summary.status == "ready_for_research"
    assert summary.preopen_event_refresh_complete is True
    assert summary.selection_as_of == "2026-08-26T09:05:00+08:00"


def test_unready_next_morning_stage_stops_at_market_open(tmp_path: Path) -> None:
    start = datetime(2026, 8, 19, 9, 5, tzinfo=SHANGHAI)
    market_open = start.replace(hour=9, minute=30)
    sleeps: list[float] = []

    def finite_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) > 1:
            raise AssertionError("开盘时不得再 sleep")

    research = FakeResearch(_empty_result())
    summary, _ = _run(
        tmp_path,
        now=_clock(start, start, market_open),
        data=FakeData(
            open_dates=[date(2026, 8, 18), date(2026, 8, 19)],
            ready=False,
            stage_status="running",
        ),
        research=research,
        sleep=finite_sleep,
    )

    assert summary.status == "data_not_ready"
    assert summary.error == "next_morning_data_not_ready_by_market_open"
    assert summary.selection_as_of == start.isoformat(timespec="seconds")
    assert sleeps == [30]
    assert research.calls == 0


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


def test_limited_record_trace_rejects_sector_basis_when_sector_is_unavailable(
    tmp_path: Path,
) -> None:
    trace = _v4_sector_trace()
    pending = tmp_path / "pending-sector.json"
    pending.write_text(json.dumps(trace, ensure_ascii=False), encoding="utf-8")
    csv_path = tmp_path / "forward.csv"
    _write_csv(csv_path, [])
    current = datetime(2026, 8, 26, 16, 24, tzinfo=SHANGHAI)

    summary = record_daily_trace(
        trace,
        pending_path=pending,
        archive_dir=tmp_path / "archive",
        csv_path=csv_path,
        data=FakeData(
            open_dates=[date(2026, 8, 25), date(2026, 8, 26)],
            feature_ready={"sector_hotspot": False},
        ),
        clock=_clock(current, current),
        formation_date=date(2026, 8, 25),
        action_date=date(2026, 8, 26),
        selection_as_of=datetime(2026, 8, 26, 9, 5, tzinfo=SHANGHAI),
        sleep=lambda _seconds: pytest.fail("下午归档不得等待"),
    )

    assert summary.status == "invalid_result"
    assert summary.error == "sector_research_unavailable"
    assert _read_csv(csv_path) == []
    assert pending.exists()


def test_limited_record_trace_rejects_fresh_event_when_preopen_is_incomplete(
    tmp_path: Path,
) -> None:
    trace = _v4_fresh_event_trace()
    pending = tmp_path / "pending-event.json"
    pending.write_text(json.dumps(trace, ensure_ascii=False), encoding="utf-8")
    csv_path = tmp_path / "forward.csv"
    _write_csv(csv_path, [])
    current = datetime(2026, 8, 26, 16, 24, tzinfo=SHANGHAI)

    summary = record_daily_trace(
        trace,
        pending_path=pending,
        archive_dir=tmp_path / "archive",
        csv_path=csv_path,
        data=FakeData(
            open_dates=[date(2026, 8, 25), date(2026, 8, 26)],
            stage_status="failed",
        ),
        clock=_clock(current, current),
        formation_date=date(2026, 8, 25),
        action_date=date(2026, 8, 26),
        selection_as_of=datetime(2026, 8, 26, 9, 5, tzinfo=SHANGHAI),
        sleep=lambda _seconds: pytest.fail("下午归档不得等待"),
    )

    assert summary.status == "invalid_result"
    assert summary.error == "preopen_event_refresh_incomplete"
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


def test_selected_trace_requires_a_separate_short_term_engine_thesis(
    tmp_path: Path,
) -> None:
    trace = _one_stock_trace()
    trace["candidate_ledger"][0].pop("research_thesis")

    summary, _, _, _ = _record_trace_for_test(trace, tmp_path)

    assert summary.status == "invalid_result"
    assert summary.error == "candidate_thesis_missing"


def test_every_nearest_candidate_requires_a_structured_engine_thesis(
    tmp_path: Path,
) -> None:
    trace = _trace_with_nearest_nonselection()
    trace["candidate_ledger"][1].pop("research_thesis")

    summary, _, _, _ = _record_trace_for_test(trace, tmp_path)

    assert summary.status == "invalid_result"
    assert summary.error == "candidate_thesis_missing"


def test_candidate_market_recognition_must_reference_daily_environment(
    tmp_path: Path,
) -> None:
    trace = _one_stock_trace()
    trace["candidate_ledger"][0]["research_thesis"]["market_recognition"][
        "market_environment_id"
    ] = "another-market"

    summary, _, _, _ = _record_trace_for_test(trace, tmp_path)

    assert summary.status == "invalid_result"
    assert summary.error == "market_recognition_environment_mismatch"


def test_candidate_company_event_time_must_not_exceed_trace_as_of(
    tmp_path: Path,
) -> None:
    trace = _trace_with_nearest_nonselection()
    novelty = trace["candidate_ledger"][1]["research_thesis"][
        "company_information_novelty"
    ]
    novelty.update(
        event_id="FUTURE-EVENT",
        event_available_at="2026-08-19T10:00:00+08:00",
    )

    summary, _, _, _ = _record_trace_for_test(trace, tmp_path)

    assert summary.status == "invalid_result"
    assert summary.error == "company_event_available_after_as_of"


def test_selected_trace_rejects_price_action_condition_without_confirmation(
    tmp_path: Path,
) -> None:
    trace = _one_stock_trace()
    price = next(
        item
        for item in trace["decision_trace"]
        if item["decision_id"] == "price-confirmation"
    )
    price["decision_role"] = "action_condition"

    summary, _, _, _ = _record_trace_for_test(trace, tmp_path)

    assert summary.status == "invalid_result"
    assert summary.error == "selected_thesis_price_confirmation_missing"


def test_selected_trace_accepts_event_price_reaction_evidence(tmp_path: Path) -> None:
    trace = _one_stock_trace()
    price = trace["decision_trace"][1]
    price["evidence_id"] = "event_price_reaction"
    price["evidence_version"] = "event-price-reaction-v2"
    price["formation_values"] = {
        "observation_date": "2026-08-18",
        "reaction_window_status": "complete",
        "event_return_5d": 0.05,
        "relative_market_return_5d": 0.04,
        "relative_industry_return_5d": 0.03,
        "amount_ratio_5d": 1.4,
    }

    summary, _, _, _ = _record_trace_for_test(trace, tmp_path)

    assert summary.status == "selection_frozen"


@pytest.mark.parametrize(
    ("missing_field", "expected_error"),
    [
        ("observation_date", "price_support_observation_date_missing"),
        ("return_5d", "price_support_price_value_missing"),
        ("amount_ratio_last_20d", "price_support_amount_value_missing"),
        ("relative_market_5d", "price_support_relative_value_missing"),
    ],
)
def test_confirmed_engine_price_support_requires_minimum_raw_values(
    tmp_path: Path,
    missing_field: str,
    expected_error: str,
) -> None:
    trace = _one_stock_trace()
    price = trace["decision_trace"][1]
    values = price["formation_values"]
    values.pop(missing_field)
    if missing_field == "relative_market_5d":
        values.pop("relative_industry_return_5d")

    summary, _, _, _ = _record_trace_for_test(trace, tmp_path)

    assert summary.status == "invalid_result"
    assert summary.error == expected_error


def test_confirmed_engine_rejects_nonpositive_amount_support(
    tmp_path: Path,
) -> None:
    trace = _one_stock_trace()
    trace["decision_trace"][1]["formation_values"][
        "amount_ratio_last_20d"
    ] = 0.0

    summary, _, _, _ = _record_trace_for_test(trace, tmp_path)

    assert summary.status == "invalid_result"
    assert summary.error == "price_support_amount_value_invalid"


def test_selected_fresh_event_pending_accepts_material_after_close_event(
    tmp_path: Path,
) -> None:
    trace = _one_stock_trace()
    trace["candidate_ledger"][0]["opportunity_type"] = "company_catalyst"
    trace["research_result"]["selected_stocks"][0][
        "opportunity_type"
    ] = "company_catalyst"
    thesis = trace["candidate_ledger"][0]["research_thesis"]
    thesis.update(
        engine_type="company_event",
        engine_status="fresh_event_pending",
        market_recognition={
            "status": "not_yet_observable",
            "market_environment_id": "market-2026-08-18",
            "basis": "收盘后新事件尚无完整交易日可观察。",
        },
        company_information_novelty={
            "disclosure_novelty": "first_disclosure",
            "new_information_level": "major_new_information",
            "basis": "首次披露的重大资产收购形成新信息。",
            "event_id": "ANN-NEW",
            "event_available_at": "2026-08-18T19:34:27+08:00",
        },
        action_condition_decision_id="price-confirmation",
    )
    price = trace["decision_trace"][1]
    price.update(
        evidence_id="event_price_reaction",
        evidence_version="event-price-reaction-v2",
        decision_role="action_condition",
        evidence_status_at_use="provisional",
        formation_values={
            "event_id": "ANN-NEW",
            "event_available_at": "2026-08-18T19:34:27+08:00",
            "reaction_start_date": "2026-08-19",
            "reaction_window_status": "awaiting_first_session",
        },
    )

    summary, _, _, _ = _record_trace_for_test(trace, tmp_path)

    assert summary.status == "selection_frozen"


@pytest.mark.parametrize(
    ("field", "value", "expected_error"),
    [
        (
            "disclosure_novelty",
            "repeat_disclosure",
            "fresh_event_novelty_invalid",
        ),
        (
            "new_information_level",
            "no_new_information",
            "fresh_event_information_level_invalid",
        ),
    ],
)
def test_fresh_event_pending_rejects_repeat_or_nonincremental_disclosure(
    tmp_path: Path,
    field: str,
    value: str,
    expected_error: str,
) -> None:
    trace = _one_stock_trace()
    trace["candidate_ledger"][0]["opportunity_type"] = "company_catalyst"
    trace["research_result"]["selected_stocks"][0][
        "opportunity_type"
    ] = "company_catalyst"
    thesis = trace["candidate_ledger"][0]["research_thesis"]
    thesis.update(
        engine_type="company_event",
        engine_status="fresh_event_pending",
        market_recognition={
            "status": "not_yet_observable",
            "market_environment_id": "market-2026-08-18",
            "basis": "收盘后尚无完整反应交易日。",
        },
        company_information_novelty={
            "disclosure_novelty": "first_disclosure",
            "new_information_level": "major_new_information",
            "basis": "形成日收盘后事件。",
            "event_id": "ANN-NEW",
            "event_available_at": "2026-08-18T19:34:27+08:00",
        },
        action_condition_decision_id="price-confirmation",
    )
    thesis["company_information_novelty"][field] = value
    trace["decision_trace"][1].update(
        evidence_id="event_price_reaction",
        evidence_version="event-price-reaction-v2",
        decision_role="action_condition",
        evidence_status_at_use="provisional",
        formation_values={
            "event_id": "ANN-NEW",
            "event_available_at": "2026-08-18T19:34:27+08:00",
            "reaction_start_date": "2026-08-19",
            "reaction_window_status": "awaiting_first_session",
        },
    )

    summary, _, _, _ = _record_trace_for_test(trace, tmp_path)

    assert summary.status == "invalid_result"
    assert summary.error == expected_error


def test_fresh_event_pending_rejects_event_before_formation_close(
    tmp_path: Path,
) -> None:
    trace = _one_stock_trace()
    trace["candidate_ledger"][0]["opportunity_type"] = "company_catalyst"
    trace["research_result"]["selected_stocks"][0][
        "opportunity_type"
    ] = "company_catalyst"
    thesis = trace["candidate_ledger"][0]["research_thesis"]
    thesis.update(
        engine_type="company_event",
        engine_status="fresh_event_pending",
        market_recognition={
            "status": "not_yet_observable",
            "market_environment_id": "market-2026-08-18",
            "basis": "声称尚不可观察。",
        },
        company_information_novelty={
            "disclosure_novelty": "first_disclosure",
            "new_information_level": "major_new_information",
            "basis": "盘中已经可见的重大事件。",
            "event_id": "ANN-EARLY",
            "event_available_at": "2026-08-18T14:30:00+08:00",
        },
        action_condition_decision_id="price-confirmation",
    )
    trace["decision_trace"][1].update(
        evidence_id="event_price_reaction",
        evidence_version="event-price-reaction-v2",
        decision_role="action_condition",
        formation_values={
            "event_id": "ANN-EARLY",
            "event_available_at": "2026-08-18T14:30:00+08:00",
            "reaction_start_date": "2026-08-19",
            "reaction_window_status": "awaiting_first_session",
        },
    )

    summary, _, _, _ = _record_trace_for_test(trace, tmp_path)

    assert summary.status == "invalid_result"
    assert summary.error == "fresh_event_not_after_formation_close"


def test_sector_diffusion_requires_candidate_in_structured_leader_cluster(
    tmp_path: Path,
) -> None:
    trace = _one_stock_trace()
    trace["candidate_ledger"][0]["opportunity_type"] = "sector_diffusion"
    trace["research_result"]["selected_stocks"][0][
        "opportunity_type"
    ] = "sector_diffusion"
    thesis = trace["candidate_ledger"][0]["research_thesis"]
    thesis["engine_type"] = "sector_diffusion"
    thesis["sector_leader_cluster"] = {
        "cluster_id": "801780.SI-2026-08-18",
        "group_code": "801780.SI",
        "group_name": "银行",
        "members": ["600000.SH", "601398.SH"],
        "candidate_role": "core",
        "propagation_evidence": "板块多日宽度和成交份额共同增强。",
        "strongest_counterevidence": "龙头集中度有所上升。",
        "unknowns": ["次日扩散能否延续"],
    }
    trace["decision_trace"].append(
        {
            "decision_id": "sector-cluster",
            "ts_code": "000001.SZ",
            "source_skill": "researching-sectors-industries",
            "evidence_id": "sector_hotspot",
            "evidence_version": "sector-hotspot-v3",
            "evidence_status_at_use": "supported_with_boundary",
            "decision_role": "support",
            "decision_changed": "promoted",
            "formation_values": {"breadth_5d": 0.7},
        }
    )
    thesis["decision_ids"].append("sector-cluster")

    summary, _, _, _ = _record_trace_for_test(trace, tmp_path)

    assert summary.status == "invalid_result"
    assert summary.error == "sector_cluster_candidate_missing"


def test_confirmed_sector_candidate_cannot_be_outside_its_leader_cluster(
    tmp_path: Path,
) -> None:
    trace = _one_stock_trace()
    trace["candidate_ledger"][0]["opportunity_type"] = "sector_diffusion"
    trace["research_result"]["selected_stocks"][0][
        "opportunity_type"
    ] = "sector_diffusion"
    thesis = trace["candidate_ledger"][0]["research_thesis"]
    thesis["engine_type"] = "sector_diffusion"
    thesis["sector_leader_cluster"] = {
        "cluster_id": "801780.SI-2026-08-18",
        "group_code": "801780.SI",
        "group_name": "银行",
        "members": ["000001.SZ", "600000.SH"],
        "candidate_role": "outside",
        "propagation_evidence": "板块存在共同推进。",
        "strongest_counterevidence": "候选不属于实际传播核心。",
        "unknowns": [],
    }
    trace["decision_trace"].append(
        {
            "decision_id": "sector-cluster",
            "ts_code": "000001.SZ",
            "source_skill": "researching-sectors-industries",
            "evidence_id": "sector_hotspot",
            "evidence_version": "sector-hotspot-v3",
            "evidence_status_at_use": "supported_with_boundary",
            "decision_role": "support",
            "decision_changed": "promoted",
            "formation_values": {"breadth_5d": 0.7},
        }
    )
    thesis["decision_ids"].append("sector-cluster")

    summary, _, _, _ = _record_trace_for_test(trace, tmp_path)

    assert summary.status == "invalid_result"
    assert summary.error == "confirmed_sector_cluster_role_invalid"


def test_trace_thesis_references_must_resolve_to_the_same_candidate(
    tmp_path: Path,
) -> None:
    trace = _trace_with_nearest_nonselection()
    trace["candidate_ledger"][0]["research_thesis"]["decision_ids"].append(
        "nearest-price"
    )

    summary, _, _, _ = _record_trace_for_test(trace, tmp_path)

    assert summary.status == "invalid_result"
    assert summary.error == "thesis_decision_candidate_mismatch"


def test_trace_thesis_rejects_unknown_decision_reference(tmp_path: Path) -> None:
    trace = _one_stock_trace()
    trace["candidate_ledger"][0]["research_thesis"]["decision_ids"].append(
        "missing-decision"
    )

    summary, _, _, _ = _record_trace_for_test(trace, tmp_path)

    assert summary.status == "invalid_result"
    assert summary.error == "thesis_decision_missing"


def test_selected_thesis_requires_referenced_company_evidence(tmp_path: Path) -> None:
    trace = _one_stock_trace()
    trace["decision_trace"][0]["source_skill"] = "interpreting-market-macro"

    summary, _, _, _ = _record_trace_for_test(trace, tmp_path)

    assert summary.status == "invalid_result"
    assert summary.error == "selected_thesis_company_evidence_missing"


def test_sector_diffusion_thesis_requires_referenced_sector_evidence(
    tmp_path: Path,
) -> None:
    trace = _one_stock_trace()
    trace["candidate_ledger"][0]["opportunity_type"] = "sector_diffusion"
    trace["research_result"]["selected_stocks"][0][
        "opportunity_type"
    ] = "sector_diffusion"
    thesis = trace["candidate_ledger"][0]["research_thesis"]
    thesis["engine_type"] = "sector_diffusion"
    thesis["sector_leader_cluster"] = {
        "cluster_id": "801780.SI-2026-08-18",
        "group_code": "801780.SI",
        "group_name": "银行",
        "members": ["000001.SZ", "600000.SH"],
        "candidate_role": "leader",
        "propagation_evidence": "板块多日宽度和成交份额共同增强。",
        "strongest_counterevidence": "集中度偏高。",
        "unknowns": ["扩散能否延续"],
    }

    summary, _, _, _ = _record_trace_for_test(trace, tmp_path)

    assert summary.status == "invalid_result"
    assert summary.error == "sector_diffusion_thesis_evidence_missing"


def test_trace_rejects_duplicate_decision_ids(tmp_path: Path) -> None:
    trace = _one_stock_trace()
    trace["decision_trace"][1]["decision_id"] = "company-anchor-risk"

    summary, _, _, _ = _record_trace_for_test(trace, tmp_path)

    assert summary.status == "invalid_result"
    assert summary.error == "duplicate_decision_ids"


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
