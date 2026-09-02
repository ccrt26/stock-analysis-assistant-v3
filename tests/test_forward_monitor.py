from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from pydantic import ValidationError

from stock_analyzer.ops.forward_monitor import (
    DailyForwardMonitorReportV1,
    DailyForwardMonitorReportV2,
    _human_trading_day,
    prepare_forward_monitor,
    record_forward_monitor,
    register_episodes,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")


def _trace(
    *,
    formation_date: str = "2026-08-20",
    action_date: str = "2026-08-21",
    selected_code: str = "603969.SH",
    comparator_code: str = "001301.SZ",
) -> dict:
    def candidate(code: str, name: str, fate: str) -> dict:
        return {
            "ts_code": code,
            "name": name,
            "opportunity_type": "independent_price_anomaly",
            "source_skills": ["analyzing-price-trading"],
            "final_fate": fate,
            "primary_reason": f"{name}的原始判断依据",
            "research_thesis": {
                "engine_type": "independent_demand_acceleration",
                "engine_status": "active",
                "market_recognition": {
                    "status": "confirmed",
                    "basis": "相对市场和行业均有增量",
                },
                "sector_broad_diffusion": None,
                "sector_leader_cluster": None,
                "action_condition_decision_id": None,
                "decision_ids": [f"co-{code}", f"px-{code}"],
            },
        }

    return {
        "trace_version": "daily-research-trace-v4",
        "formation_date": formation_date,
        "action_date": action_date,
        "as_of": f"{action_date}T09:10:00+08:00",
        "candidate_ledger": [
            candidate(selected_code, "银龙股份", "selected"),
            candidate(comparator_code, "尚太科技", "rejected"),
        ],
        "decision_trace": [
            {
                "decision_id": f"co-{code}",
                "ts_code": code,
                "source_skill": "researching-company-events",
                "evidence_id": "company-fact",
                "evidence_version": "v1",
                "decision_role": "support",
                "formation_values": {"fact": f"{name}的公司事实"},
            }
            for code, name in (
                (selected_code, "银龙股份"),
                (comparator_code, "尚太科技"),
            )
        ]
        + [
            {
                "decision_id": f"px-{code}",
                "ts_code": code,
                "source_skill": "analyzing-price-trading",
                "evidence_id": "raw_price",
                "evidence_version": "v1",
                "decision_role": "support",
                "formation_values": {"return_5d": 0.03},
            }
            for code in (selected_code, comparator_code)
        ]
        + [
            {
                "decision_id": "unrelated-decision",
                "ts_code": "000001.SZ",
                "source_skill": "analyzing-price-trading",
                "evidence_id": "raw_price",
                "evidence_version": "v1",
                "decision_role": "comparison",
                "formation_values": {"return_5d": -0.01},
            }
        ],
        "research_result": {
            "selected_stocks": [
                {
                    "ts_code": selected_code,
                    "name": "银龙股份",
                    "priority": 1,
                    "opportunity_type": "independent_price_anomaly",
                    "selection_reason": "推荐时保留的独立选择理由",
                    "strongest_counterevidence": "持续性仍待观察",
                    "nearest_comparison": (
                        f"相比尚太科技（{comparator_code}），银龙股份启动更早。"
                    ),
                }
            ],
            "nearest_nonselections": [
                {
                    "ts_code": comparator_code,
                    "name": "尚太科技",
                    "opportunity_type": "independent_price_anomaly",
                    "selection_reason": "对照股票当时接近入选",
                    "strongest_counterevidence": "短期涨幅偏大",
                    "nearest_comparison": "剩余空间弱于入选股票",
                }
            ],
        },
    }


def _write_trace(path: Path, payload: dict) -> bytes:
    raw = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    path.write_bytes(raw)
    return raw


def _write_parquet(root: Path, relative: str, rows: list[dict]) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(path, index=False)


def _single_selected_trace(
    *,
    formation_date: str,
    action_date: str,
    ts_code: str = "603969.SH",
) -> dict:
    payload = _trace(
        formation_date=formation_date,
        action_date=action_date,
        selected_code=ts_code,
        comparator_code="001301.SZ",
    )
    payload["candidate_ledger"] = payload["candidate_ledger"][:1]
    payload["research_result"]["nearest_nonselections"] = []
    return payload


def _seed_monitor_project(
    root: Path,
    *,
    trace: dict,
    session_count: int = 31,
    price_overrides: dict[int, dict[str, float]] | None = None,
    price_context_overrides: dict | None = None,
    announcements: list[dict] | None = None,
) -> list[date]:
    formation = date.fromisoformat(trace["formation_date"])
    action = date.fromisoformat(trace["action_date"])
    sessions = [
        stamp.date()
        for stamp in pd.bdate_range(action.isoformat(), periods=session_count)
    ]
    calendar_days = [formation, *sessions]
    _write_parquet(
        root,
        "local_warehouse/facts/trade_calendar/cal_year=2026/data.parquet",
        [
            {
                "exchange": "SSE",
                "cal_date": day,
                "is_open": True,
                "available_at": datetime(2026, 1, 1, tzinfo=SHANGHAI),
            }
            for day in calendar_days
        ],
    )
    overrides = price_overrides or {}
    codes = {
        item["ts_code"]
        for item in trace["research_result"]["selected_stocks"]
        + trace["research_result"].get("nearest_nonselections", [])
    }
    for index, day in enumerate(sessions, start=1):
        values = {
            "open": 10.0,
            "close": 10.0 + index * 0.1,
            "high": 10.5 + index * 0.1,
            "low": 9.5,
            "amount": 100.0 + index,
        }
        values.update(overrides.get(index, {}))
        _write_parquet(
            root,
            f"local_warehouse/facts/equity_daily/trade_date={day}/data.parquet",
            [
                {
                    "trade_date": day,
                    "ts_code": code,
                    **values,
                    "available_at": datetime.combine(
                        day,
                        datetime.min.time(),
                        SHANGHAI,
                    ).replace(hour=16),
                }
                for code in sorted(codes)
            ],
        )
        _write_parquet(
            root,
            f"local_warehouse/facts/adj_factor/trade_date={day}/data.parquet",
            [
                {
                    "trade_date": day,
                    "ts_code": code,
                    "adj_factor": 1.0,
                    "available_at": datetime.combine(
                        day,
                        datetime.min.time(),
                        SHANGHAI,
                    ).replace(hour=16),
                }
                for code in sorted(codes)
            ],
        )
    analysis_day = sessions[-1]
    price_row = {
        "analysis_date": analysis_day,
        "ts_code": next(iter(sorted(codes))),
        "formula_version": "price-analysis-context-v2",
        "relative_market_1d": 0.01,
        "relative_market_3d": 0.02,
        "relative_market_5d": 0.03,
        "relative_industry_return_1d": 0.005,
        "relative_industry_return_3d": 0.015,
        "relative_industry_return_5d": 0.025,
        "industry_comparison_status": "complete",
        "amount_ratio_last_20d": 1.2,
        "volume_price_efficiency_5d": 0.7,
        "mean_close_position_5d": 0.65,
        "upper_shadow_frequency_5d": 0.1,
        "fade_frequency_5d": 0.1,
        "breakout_vs_prior60": 0.0,
        "limit_up_return_contribution_5d": 0.0,
        "target_atr_distance_20pct": 4.0,
        "scenario_case_ids": "",
        "scenario_control_ids": "",
        "price_location_60d": 0.5,
        "coverage_status": "complete",
        "primary_industry_code": "801000.SI",
    }
    price_row.update(price_context_overrides or {})
    price_rows = [{**price_row, "ts_code": code} for code in sorted(codes)]
    _write_parquet(
        root,
        (
            "local_warehouse/derived/price_analysis_context/"
            f"analysis_date={analysis_day}/formula_version=price-analysis-context-v2/"
            "data.parquet"
        ),
        price_rows,
    )
    _write_parquet(
        root,
        (
            "local_warehouse/derived/market_context/"
            f"analysis_date={analysis_day}/formula_version=market-context-v3/"
            "data.parquet"
        ),
        [
            {
                "analysis_date": analysis_day,
                "formula_version": "market-context-v3",
                "equal_weight_return_1d": 0.01,
                "breadth_1d": 0.6,
                "coverage_status": "complete",
            }
        ],
    )
    _write_parquet(
        root,
        (
            "local_warehouse/derived/sector_hotspot/"
            f"analysis_date={analysis_day}/formula_version=sector-hotspot-v3/"
            "data.parquet"
        ),
        [
            {
                "analysis_date": analysis_day,
                "formula_version": "sector-hotspot-v3",
                "group_code": "801000.SI",
                "group_type": "industry",
                "relative_return_3d": 0.02,
                "relative_return_5d": 0.03,
                "median_return_3d": 0.01,
                "median_return_5d": 0.02,
                "breadth_3d": 0.6,
                "breadth_5d": 0.7,
                "turnover_share_change_5d": 0.01,
                "top3_positive_contribution_1d": 0.5,
                "return_dispersion_1d": 0.02,
                "coverage_status": "complete",
            }
        ],
    )
    if announcements:
        _write_parquet(
            root,
            "local_warehouse/facts/announcement/announcement_month=2026-08/data.parquet",
            announcements,
        )
    return sessions


def _prepare(root: Path, analysis_date: date) -> dict:
    as_of = datetime.combine(
        analysis_date,
        datetime.min.time(),
        SHANGHAI,
    ).replace(hour=18)
    summary = prepare_forward_monitor(
        analysis_date=analysis_date,
        as_of=as_of,
        project_root=root,
    )
    return json.loads(Path(summary.snapshot_file).read_text(encoding="utf-8"))


def test_register_only_accepts_v4_trace(tmp_path: Path) -> None:
    trace_file = tmp_path / "trace.json"
    trace_file.write_text(
        json.dumps({"trace_version": "daily-research-trace-v3"}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="daily-research-trace-v4"):
        register_episodes(
            trace_file=trace_file,
            label="legacy",
            project_root=tmp_path,
        )


def test_register_imports_selected_and_comparator_with_stable_ids(
    tmp_path: Path,
) -> None:
    trace_file = tmp_path / "trace.json"
    original = _write_trace(trace_file, _trace())

    summary = register_episodes(
        trace_file=trace_file,
        label="v4-replay-2026-08-20",
        project_root=tmp_path,
    )

    registry = json.loads(
        (
            tmp_path
            / "local_archive/forward_monitor/registered-episodes.json"
        ).read_text(encoding="utf-8")
    )
    episodes = {item["role"]: item for item in registry["episodes"]}
    assert summary.selected_registered == 1
    assert summary.comparators_registered == 1
    assert episodes["selected"]["episode_id"] == (
        "v4-replay-2026-08-20:2026-08-20:603969.SH:selected"
    )
    assert episodes["comparator"]["episode_id"] == (
        "v4-replay-2026-08-20:2026-08-20:001301.SZ:comparator"
    )
    assert episodes["selected"]["original_priority"] == 1
    assert episodes["comparator"]["original_priority"] is None
    assert episodes["selected"]["original_research_thesis"] == (
        _trace()["candidate_ledger"][0]["research_thesis"]
    )
    assert episodes["comparator"]["original_research_thesis"] == (
        _trace()["candidate_ledger"][1]["research_thesis"]
    )
    assert episodes["selected"]["original_selection_reason"] == (
        "推荐时保留的独立选择理由"
    )
    assert episodes["comparator"]["original_selection_reason"] == (
        "对照股票当时接近入选"
    )
    assert trace_file.read_bytes() == original


def test_register_is_idempotent(tmp_path: Path) -> None:
    trace_file = tmp_path / "trace.json"
    _write_trace(trace_file, _trace())

    first = register_episodes(
        trace_file=trace_file,
        label="replay",
        project_root=tmp_path,
    )
    registry_path = (
        tmp_path / "local_archive/forward_monitor/registered-episodes.json"
    )
    first_bytes = registry_path.read_bytes()
    repeated = register_episodes(
        trace_file=trace_file,
        label="replay",
        project_root=tmp_path,
    )

    assert first.selected_registered == 1
    assert first.comparators_registered == 1
    assert repeated.selected_registered == 0
    assert repeated.comparators_registered == 0
    assert registry_path.read_bytes() == first_bytes


def test_register_only_fills_missing_original_fields(tmp_path: Path) -> None:
    trace_file = tmp_path / "trace.json"
    trace = _trace()
    _write_trace(trace_file, trace)
    register_episodes(
        trace_file=trace_file,
        label="replay",
        project_root=tmp_path,
    )
    registry_path = (
        tmp_path / "local_archive/forward_monitor/registered-episodes.json"
    )
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    selected = next(
        item for item in registry["episodes"] if item["role"] == "selected"
    )
    selected.pop("original_research_thesis")
    selected["original_primary_reason"] = "已经保存的原始理由"
    registry_path.write_text(
        json.dumps(registry, ensure_ascii=False),
        encoding="utf-8",
    )

    repeated = register_episodes(
        trace_file=trace_file,
        label="replay",
        project_root=tmp_path,
    )

    refreshed = json.loads(registry_path.read_text(encoding="utf-8"))
    selected = next(
        item for item in refreshed["episodes"] if item["role"] == "selected"
    )
    assert repeated.selected_registered == 0
    assert repeated.comparators_registered == 0
    assert selected["original_research_thesis"] == (
        trace["candidate_ledger"][0]["research_thesis"]
    )
    assert selected["original_primary_reason"] == "已经保存的原始理由"


def test_prepare_auto_discovers_formal_v4_trace(tmp_path: Path) -> None:
    trace = _single_selected_trace(
        formation_date="2026-07-31",
        action_date="2026-08-03",
    )
    trace_path = (
        tmp_path
        / "local_archive/forward_selection/research-trace-2026-07-31.json"
    )
    trace_path.parent.mkdir(parents=True)
    _write_trace(trace_path, trace)
    sessions = _seed_monitor_project(tmp_path, trace=trace, session_count=1)

    snapshot = _prepare(tmp_path, sessions[0])

    assert snapshot["summary"]["open_episode_count"] == 1
    assert snapshot["episodes"][0]["episode_id"] == (
        "formal:2026-07-31:603969.SH:selected"
    )
    assert snapshot["episodes"][0]["source_type"] == "formal"
    assert snapshot["episodes"][0]["original_research_thesis"] == (
        trace["candidate_ledger"][0]["research_thesis"]
    )
    assert trace["candidate_ledger"][0]["research_thesis"] == (
        json.loads(trace_path.read_text(encoding="utf-8"))["candidate_ledger"][0][
            "research_thesis"
        ]
    )


def test_prepare_marks_old_episode_with_missing_original_thesis(
    tmp_path: Path,
) -> None:
    trace = _single_selected_trace(
        formation_date="2026-07-31",
        action_date="2026-08-03",
    )
    trace_file = tmp_path / "trace.json"
    _write_trace(trace_file, trace)
    register_episodes(
        trace_file=trace_file,
        label="legacy",
        project_root=tmp_path,
    )
    registry_path = (
        tmp_path / "local_archive/forward_monitor/registered-episodes.json"
    )
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["episodes"][0].pop("original_research_thesis")
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    sessions = _seed_monitor_project(tmp_path, trace=trace, session_count=1)

    episode = _prepare(tmp_path, sessions[0])["episodes"][0]

    assert episode["original_research_thesis"] is None
    assert "missing_original_research_thesis" in episode["data_limitations"]


def test_prepare_keeps_multiple_episodes_for_the_same_stock(tmp_path: Path) -> None:
    older = _single_selected_trace(
        formation_date="2026-07-30",
        action_date="2026-07-31",
    )
    newer = _single_selected_trace(
        formation_date="2026-07-31",
        action_date="2026-08-03",
    )
    archive = tmp_path / "local_archive/forward_selection"
    archive.mkdir(parents=True)
    _write_trace(archive / "research-trace-2026-07-30.json", older)
    _write_trace(archive / "research-trace-2026-07-31.json", newer)
    sessions = _seed_monitor_project(tmp_path, trace=newer, session_count=1)
    # Add the older action day to the same governed calendar and price facts.
    calendar_path = (
        tmp_path
        / "local_warehouse/facts/trade_calendar/cal_year=2026/data.parquet"
    )
    calendar = pd.read_parquet(calendar_path)
    calendar = pd.concat(
        [
            calendar,
            pd.DataFrame(
                [
                    {
                        "exchange": "SSE",
                        "cal_date": date(2026, 7, 31),
                        "is_open": True,
                        "available_at": datetime(2026, 1, 1, tzinfo=SHANGHAI),
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    calendar.to_parquet(calendar_path, index=False)
    _write_parquet(
        tmp_path,
        "local_warehouse/facts/equity_daily/trade_date=2026-07-31/data.parquet",
        [
            {
                "trade_date": date(2026, 7, 31),
                "ts_code": "603969.SH",
                "open": 9.5,
                "high": 10.0,
                "low": 9.0,
                "close": 9.8,
                "amount": 100.0,
                "available_at": datetime(2026, 7, 31, 16, tzinfo=SHANGHAI),
            }
        ],
    )
    _write_parquet(
        tmp_path,
        "local_warehouse/facts/adj_factor/trade_date=2026-07-31/data.parquet",
        [
            {
                "trade_date": date(2026, 7, 31),
                "ts_code": "603969.SH",
                "adj_factor": 1.0,
                "available_at": datetime(2026, 7, 31, 16, tzinfo=SHANGHAI),
            }
        ],
    )
    old_id = "formal:2026-07-30:603969.SH:selected"
    new_id = "formal:2026-07-31:603969.SH:selected"
    monitor_dir = tmp_path / "local_archive/forward_monitor"
    monitor_dir.mkdir(parents=True)
    (monitor_dir / "monitor-report-2026-08-02.json").write_text(
        json.dumps(
            {
                "report_version": "daily-forward-monitor-report-v2",
                "analysis_date": "2026-08-02",
                "alerts": [
                    {
                        "episode_reviews": [
                            {
                                "episode_id": old_id,
                                "current_assessment": "contradicted",
                                "best_supported_explanation": "market_common_move",
                                "current_weak_or_failed_link": "stock_selection",
                                "current_review": "旧记录已经受到反驳。",
                            },
                            {
                                "episode_id": new_id,
                                "current_assessment": "partly_supported",
                                "best_supported_explanation": "stock_specific_move",
                                "current_weak_or_failed_link": "none",
                                "current_review": "新记录只得到部分支持。",
                            },
                        ]
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    snapshot = _prepare(tmp_path, sessions[0])

    stock_episodes = [
        episode
        for episode in snapshot["episodes"]
        if episode["ts_code"] == "603969.SH"
    ]
    assert len(stock_episodes) == 2
    assert {episode["formation_date"] for episode in stock_episodes} == {
        "2026-07-30",
        "2026-07-31",
    }
    assert snapshot["summary"]["distinct_stock_count"] == 1
    by_id = {item["episode_id"]: item for item in stock_episodes}
    assert by_id[old_id]["previous_episode_review"]["current_assessment"] == (
        "contradicted"
    )
    assert by_id[new_id]["previous_episode_review"]["current_assessment"] == (
        "partly_supported"
    )


@pytest.mark.parametrize(
    ("day_number", "phase", "checkpoint"),
    [
        (1, "primary", "D1"),
        (3, "primary", "D3"),
        (5, "primary", "D5"),
        (10, "primary", "D10"),
        (20, "primary", "D20"),
        (21, "passive_tail", None),
        (25, "passive_tail", "D25"),
        (30, "passive_tail", "D30"),
        (31, "closed", None),
    ],
)
def test_prepare_uses_real_trading_days_for_phase_and_checkpoints(
    tmp_path: Path,
    day_number: int,
    phase: str,
    checkpoint: str | None,
) -> None:
    trace = _single_selected_trace(
        formation_date="2026-07-31",
        action_date="2026-08-03",
    )
    trace_path = (
        tmp_path
        / "local_archive/forward_selection/research-trace-2026-07-31.json"
    )
    trace_path.parent.mkdir(parents=True)
    _write_trace(trace_path, trace)
    sessions = _seed_monitor_project(
        tmp_path,
        trace=trace,
        session_count=day_number,
    )

    snapshot = _prepare(tmp_path, sessions[-1])
    episode = snapshot["episodes"][0]

    assert episode["day_number"] == day_number
    assert episode["monitor_phase"] == phase
    assert episode["checkpoint"] == checkpoint
    assert ("checkpoint" in episode["attention_reasons"]) is bool(checkpoint)
    if phase == "closed":
        assert snapshot["summary"]["closed_count"] == 1
        assert snapshot["summary"]["open_episode_count"] == 0


def test_prepare_calculates_adjusted_path_and_excludes_future_prices(tmp_path: Path) -> None:
    trace = _single_selected_trace(formation_date="2026-07-31", action_date="2026-08-03")
    archive = tmp_path / "local_archive/forward_selection"
    archive.mkdir(parents=True)
    _write_trace(archive / "research-trace-2026-07-31.json", trace)
    sessions = _seed_monitor_project(
        tmp_path,
        trace=trace,
        session_count=2,
        price_overrides={
            1: {"open": 10.0, "close": 11.0, "high": 12.1, "low": 9.0},
            2: {"open": 11.0, "close": 12.2, "high": 13.0, "low": 8.0},
        },
    )
    future = date(2026, 8, 5)
    _write_parquet(
        tmp_path,
        f"local_warehouse/facts/equity_daily/trade_date={future}/data.parquet",
        [{"trade_date": future, "ts_code": "603969.SH", "open": 50.0, "close": 60.0, "high": 70.0, "low": 1.0, "available_at": datetime(2026, 8, 5, 16, tzinfo=SHANGHAI)}],
    )
    _write_parquet(
        tmp_path,
        f"local_warehouse/facts/adj_factor/trade_date={future}/data.parquet",
        [{"trade_date": future, "ts_code": "603969.SH", "adj_factor": 1.0, "available_at": datetime(2026, 8, 5, 16, tzinfo=SHANGHAI)}],
    )

    episode = _prepare(tmp_path, sessions[-1])["episodes"][0]

    assert episode["entry_open"] == pytest.approx(10.0)
    for prefix in ("d20", "current"):
        assert episode[f"{prefix}_close_return_since_entry"] == pytest.approx(0.22)
        assert episode[f"{prefix}_max_close_return_since_entry"] == pytest.approx(0.22)
        assert episode[f"{prefix}_max_high_return_since_entry"] == pytest.approx(0.30)
        assert episode[f"{prefix}_mae_since_entry"] == pytest.approx(-0.20)
        assert episode[f"{prefix}_close_drawdown_from_peak"] == pytest.approx(0.0)
        assert episode[f"{prefix}_first_close_hit_20pct_date"] == sessions[1].isoformat()
        assert episode[f"{prefix}_first_high_hit_20pct_date"] == sessions[0].isoformat()
    assert episode["d20_hit_20pct_close_within_20d"] is True
    assert episode["current_hit_20pct_close"] is True


def test_public_markdown_hides_conditional_event_but_keeps_internal_json(
    tmp_path: Path,
) -> None:
    trace = _single_selected_trace(
        formation_date="2026-07-31",
        action_date="2026-08-03",
    )
    thesis = trace["candidate_ledger"][0]["research_thesis"]
    thesis.update(
        engine_type="fresh_event_pending",
        engine_status="conditional",
        market_recognition={"status": "pending", "basis": "等待首日确认"},
    )
    archive = tmp_path / "local_archive/forward_selection"
    archive.mkdir(parents=True)
    _write_trace(archive / "research-trace-2026-07-31.json", trace)
    sessions = _seed_monitor_project(
        tmp_path,
        trace=trace,
        session_count=1,
        price_overrides={
            1: {"open": 10.0, "close": 10.5, "high": 10.8, "low": 9.8},
        },
    )

    snapshot = _prepare(tmp_path, sessions[0])
    episode = snapshot["episodes"][0]

    assert episode["role"] == "selected"
    assert episode["selection_output_class"] == "conditional_event"
    assert episode["formal_return_started"] is False
    assert episode["entry_open"] is None
    assert episode["current_close_return_since_entry"] is None
    assert episode["d20_close_return_since_entry"] is None
    assert episode["first_event_reaction"]["open_to_close_return"] == pytest.approx(0.05)
    assert "first_event_reaction" in episode["attention_reasons"]
    assert snapshot["summary"]["selected_count"] == 0
    assert snapshot["required_final_review_episode_ids"] == []

    snapshot_path = (
        tmp_path
        / f"local_archive/forward_monitor/snapshot-{sessions[0]}.json"
    )
    alert = _alert("603969.SH", episode["episode_id"])
    alert["original_engine_types"] = ["fresh_event_pending"]
    pending = tmp_path / "pending-conditional.json"
    pending.write_text(
        json.dumps(
            _report_payload(snapshot, alerts=[alert]),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    summary = record_forward_monitor(
        snapshot_file=snapshot_path,
        report_file=pending,
        project_root=tmp_path,
    )
    markdown = Path(summary.markdown_file).read_text(encoding="utf-8")
    saved = json.loads(Path(summary.json_file).read_text(encoding="utf-8"))

    assert saved["alerts"]
    assert "银龙股份" not in markdown
    assert "等待首个交易日确认" not in markdown
    assert "今天没有被明确推荐过" in markdown


def test_conditional_event_never_requires_or_accepts_a_d20_final_review(
    tmp_path: Path,
) -> None:
    trace = _single_selected_trace(
        formation_date="2026-07-01",
        action_date="2026-07-02",
    )
    thesis = trace["candidate_ledger"][0]["research_thesis"]
    thesis.update(
        engine_type="fresh_event_pending",
        engine_status="conditional",
        market_recognition={"status": "pending", "basis": "等待首日确认"},
    )
    archive = tmp_path / "local_archive/forward_selection"
    archive.mkdir(parents=True)
    _write_trace(archive / "research-trace-2026-07-01.json", trace)
    sessions = _seed_monitor_project(tmp_path, trace=trace, session_count=20)

    snapshot = _prepare(tmp_path, sessions[-1])
    episode = snapshot["episodes"][0]

    assert episode["selection_output_class"] == "conditional_event"
    assert episode["entry_open"] is None
    assert episode["d20_close_return_since_entry"] is None
    assert "pending_final_review" not in episode["attention_reasons"]
    assert snapshot["required_final_review_episode_ids"] == []


def test_path_reports_close_drawdown_from_the_period_peak(tmp_path: Path) -> None:
    trace = _single_selected_trace(
        formation_date="2026-07-31",
        action_date="2026-08-03",
    )
    archive = tmp_path / "local_archive/forward_selection"
    archive.mkdir(parents=True)
    _write_trace(archive / "research-trace-2026-07-31.json", trace)
    sessions = _seed_monitor_project(
        tmp_path,
        trace=trace,
        session_count=2,
        price_overrides={
            1: {"open": 10.0, "close": 12.0, "high": 12.2, "low": 9.5},
            2: {"open": 11.5, "close": 11.0, "high": 11.8, "low": 10.8},
        },
    )

    episode = _prepare(tmp_path, sessions[-1])["episodes"][0]

    assert episode["current_close_drawdown_from_peak"] == pytest.approx(
        11.0 / 12.0 - 1.0
    )
    assert episode["d20_close_drawdown_from_peak"] == pytest.approx(
        11.0 / 12.0 - 1.0
    )


def test_path_distinguishes_max_close_drawdown_current_pullback_and_mae(
    tmp_path: Path,
) -> None:
    trace = _single_selected_trace(
        formation_date="2026-07-31",
        action_date="2026-08-03",
    )
    archive = tmp_path / "local_archive/forward_selection"
    archive.mkdir(parents=True)
    _write_trace(archive / "research-trace-2026-07-31.json", trace)
    sessions = _seed_monitor_project(
        tmp_path,
        trace=trace,
        session_count=4,
        price_overrides={
            1: {"open": 10.0, "close": 10.0, "high": 10.5, "low": 9.5},
            2: {"open": 10.0, "close": 12.0, "high": 12.5, "low": 9.8},
            3: {"open": 12.0, "close": 9.0, "high": 12.1, "low": 8.0},
            4: {"open": 9.0, "close": 11.0, "high": 11.2, "low": 8.8},
        },
    )

    episode = _prepare(tmp_path, sessions[-1])["episodes"][0]

    for prefix in ("current", "d20"):
        assert episode[f"{prefix}_max_close_drawdown"] == pytest.approx(
            9.0 / 12.0 - 1.0
        )
        assert episode[f"{prefix}_close_drawdown_from_peak"] == pytest.approx(
            11.0 / 12.0 - 1.0
        )
        assert episode[f"{prefix}_mae_since_entry"] == pytest.approx(-0.20)


def test_d20_close_hit_uses_forward_tolerance_at_twenty_percent(
    tmp_path: Path,
) -> None:
    trace = _single_selected_trace(
        formation_date="2026-07-31",
        action_date="2026-08-03",
    )
    archive = tmp_path / "local_archive/forward_selection"
    archive.mkdir(parents=True)
    _write_trace(archive / "research-trace-2026-07-31.json", trace)
    sessions = _seed_monitor_project(
        tmp_path,
        trace=trace,
        session_count=1,
        price_overrides={
            1: {"open": 10.0, "close": 12.0, "high": 11.0, "low": 9.5},
        },
    )

    episode = _prepare(tmp_path, sessions[0])["episodes"][0]

    assert episode["d20_first_close_hit_20pct_date"] == sessions[0].isoformat()
    assert episode["d20_hit_20pct_close_within_20d"] is True
    assert episode["current_first_close_hit_20pct_date"] is None
    assert episode["current_hit_20pct_close"] is False


def test_mature_d20_metrics_require_complete_exact_twenty_day_path(
    tmp_path: Path,
) -> None:
    incomplete_root = tmp_path / "incomplete"
    trace = _single_selected_trace(
        formation_date="2026-07-01",
        action_date="2026-07-02",
    )
    archive = incomplete_root / "local_archive/forward_selection"
    archive.mkdir(parents=True)
    _write_trace(archive / "research-trace-2026-07-01.json", trace)
    sessions = _seed_monitor_project(
        incomplete_root,
        trace=trace,
        session_count=20,
    )
    for dataset in ("equity_daily", "adj_factor"):
        (
            incomplete_root
            / f"local_warehouse/facts/{dataset}/trade_date={sessions[6]}/data.parquet"
        ).unlink()

    incomplete = _prepare(incomplete_root, sessions[-1])["episodes"][0]

    assert "incomplete_price_path" in incomplete["data_limitations"]
    for field in (
        "d20_close_return_since_entry",
        "d20_max_close_return_since_entry",
        "d20_max_high_return_since_entry",
        "d20_mae_since_entry",
        "d20_first_close_hit_20pct_date",
        "d20_first_high_hit_20pct_date",
        "d20_hit_20pct_close_within_20d",
    ):
        assert incomplete[field] is None

    complete_root = tmp_path / "complete"
    archive = complete_root / "local_archive/forward_selection"
    archive.mkdir(parents=True)
    _write_trace(archive / "research-trace-2026-07-01.json", trace)
    complete_sessions = _seed_monitor_project(
        complete_root,
        trace=trace,
        session_count=20,
    )

    complete = _prepare(complete_root, complete_sessions[-1])["episodes"][0]

    assert complete["d20_close_return_since_entry"] == pytest.approx(0.20)
    assert complete["d20_hit_20pct_close_within_20d"] is True


def test_legacy_target_hit_is_not_repeated_but_a_real_first_hit_is_alerted(
    tmp_path: Path,
) -> None:
    trace = _single_selected_trace(
        formation_date="2026-07-31",
        action_date="2026-08-03",
    )

    legacy_root = tmp_path / "legacy"
    archive = legacy_root / "local_archive/forward_selection"
    archive.mkdir(parents=True)
    _write_trace(archive / "research-trace-2026-07-31.json", trace)
    legacy_sessions = _seed_monitor_project(
        legacy_root,
        trace=trace,
        session_count=2,
        price_overrides={
            1: {"open": 10.0, "close": 12.1, "high": 12.2, "low": 9.5},
            2: {"open": 12.0, "close": 12.2, "high": 12.3, "low": 11.8},
        },
    )
    monitor_dir = legacy_root / "local_archive/forward_monitor"
    monitor_dir.mkdir(parents=True)
    (monitor_dir / f"snapshot-{legacy_sessions[0]}.json").write_text(
        json.dumps(
            {
                "snapshot_version": "forward-monitor-snapshot-v1",
                "analysis_date": legacy_sessions[0].isoformat(),
                "as_of": datetime.combine(
                    legacy_sessions[0],
                    datetime.min.time(),
                    SHANGHAI,
                ).replace(hour=18).isoformat(),
                "episodes": [
                    {
                        "episode_id": "formal:2026-07-31:603969.SH:selected",
                        "first_close_hit_20pct_date": legacy_sessions[0].isoformat(),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    repeated = _prepare(legacy_root, legacy_sessions[1])["episodes"][0]

    assert "target_hit_first_time" not in repeated["attention_reasons"]

    first_hit_root = tmp_path / "first-hit"
    archive = first_hit_root / "local_archive/forward_selection"
    archive.mkdir(parents=True)
    _write_trace(archive / "research-trace-2026-07-31.json", trace)
    first_hit_sessions = _seed_monitor_project(
        first_hit_root,
        trace=trace,
        session_count=2,
        price_overrides={
            1: {"open": 10.0, "close": 11.0, "high": 11.5, "low": 9.5},
            2: {"open": 11.0, "close": 12.1, "high": 12.2, "low": 10.8},
        },
    )
    monitor_dir = first_hit_root / "local_archive/forward_monitor"
    monitor_dir.mkdir(parents=True)
    (monitor_dir / f"snapshot-{first_hit_sessions[0]}.json").write_text(
        json.dumps(
            {
                "snapshot_version": "forward-monitor-snapshot-v1",
                "analysis_date": first_hit_sessions[0].isoformat(),
                "as_of": datetime.combine(
                    first_hit_sessions[0],
                    datetime.min.time(),
                    SHANGHAI,
                ).replace(hour=18).isoformat(),
                "episodes": [
                    {
                        "episode_id": "formal:2026-07-31:603969.SH:selected",
                        "d20_first_close_hit_20pct_date": None,
                        "first_close_hit_20pct_date": None,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    first_hit = _prepare(first_hit_root, first_hit_sessions[1])["episodes"][0]

    assert "target_hit_first_time" in first_hit["attention_reasons"]


def test_breakout_uses_positive_numeric_state_for_changes_tail_and_overheat(tmp_path: Path) -> None:
    trace = _single_selected_trace(formation_date="2026-07-01", action_date="2026-07-02")
    archive = tmp_path / "local_archive/forward_selection"
    archive.mkdir(parents=True)
    _write_trace(archive / "research-trace-2026-07-01.json", trace)
    sessions = _seed_monitor_project(
        tmp_path,
        trace=trace,
        session_count=21,
        price_context_overrides={
            "breakout_vs_prior60": -0.1,
            "relative_market_3d": 0.02,
            "relative_market_5d": 0.03,
            "relative_industry_return_3d": 0.02,
            "relative_industry_return_5d": 0.03,
            "amount_ratio_last_20d": 1.2,
            "fade_frequency_5d": 0.2,
        },
    )
    previous_day = sessions[-2]
    monitor_dir = tmp_path / "local_archive/forward_monitor"
    monitor_dir.mkdir(parents=True)
    previous_episode = {
        "episode_id": "formal:2026-07-01:603969.SH:selected",
        "breakout_vs_prior60": -0.2,
        "relative_market_3d": 0.01,
        "relative_market_5d": 0.01,
        "relative_industry_3d": 0.01,
        "relative_industry_5d": 0.01,
        "amount_ratio_last_20d": 1.1,
        "fade_frequency_5d": 0.1,
        "upper_shadow_frequency_5d": 0.1,
        "volume_price_efficiency_5d": 0.7,
        "scenario_case_ids": [],
        "d20_first_close_hit_20pct_date": None,
        "data_limitations": [],
    }
    (monitor_dir / f"snapshot-{previous_day}.json").write_text(
        json.dumps(
            {
                "snapshot_version": "forward-monitor-snapshot-v1",
                "analysis_date": str(previous_day),
                "as_of": datetime(2026, 7, 29, 18, tzinfo=SHANGHAI).isoformat(),
                "episodes": [previous_episode],
            }
        ),
        encoding="utf-8",
    )

    negative = _prepare(tmp_path, sessions[-1])["episodes"][0]

    assert "breakout_changed" not in negative["attention_reasons"]
    assert "late_activation_candidate" not in negative["attention_reasons"]
    assert "overheat_candidate" not in negative["attention_reasons"]

    price_path = (
        tmp_path
        / "local_warehouse/derived/price_analysis_context"
        / f"analysis_date={sessions[-1]}"
        / "formula_version=price-analysis-context-v2/data.parquet"
    )
    price_frame = pd.read_parquet(price_path)
    price_frame["breakout_vs_prior60"] = 0.1
    price_frame.to_parquet(price_path, index=False)

    positive = _prepare(tmp_path, sessions[-1])["episodes"][0]

    assert "breakout_changed" in positive["attention_reasons"]
    assert "late_activation_candidate" in positive["attention_reasons"]


def test_missing_action_day_price_never_uses_later_open_as_entry(tmp_path: Path) -> None:
    trace = _single_selected_trace(formation_date="2026-07-31", action_date="2026-08-03")
    archive = tmp_path / "local_archive/forward_selection"
    archive.mkdir(parents=True)
    _write_trace(archive / "research-trace-2026-07-31.json", trace)
    sessions = _seed_monitor_project(tmp_path, trace=trace, session_count=2)
    for dataset in ("equity_daily", "adj_factor"):
        (
            tmp_path
            / f"local_warehouse/facts/{dataset}/trade_date={sessions[0]}/data.parquet"
        ).unlink()

    episode = _prepare(tmp_path, sessions[1])["episodes"][0]

    assert episode["entry_open"] is None
    assert episode["d20_close_return_since_entry"] is None
    assert episode["current_close_return_since_entry"] is None
    assert episode["d20_hit_20pct_close_within_20d"] is None
    assert episode["current_hit_20pct_close"] is None


def test_d25_first_twenty_percent_hit_stays_out_of_fixed_d20_result(tmp_path: Path) -> None:
    trace = _single_selected_trace(formation_date="2026-07-01", action_date="2026-07-02")
    archive = tmp_path / "local_archive/forward_selection"
    archive.mkdir(parents=True)
    _write_trace(archive / "research-trace-2026-07-01.json", trace)
    price_overrides = {
        index: {"open": 10.0, "close": 11.5, "high": 11.9, "low": 9.5}
        for index in range(1, 25)
    }
    price_overrides[25] = {"open": 11.8, "close": 12.1, "high": 12.2, "low": 11.7}
    sessions = _seed_monitor_project(
        tmp_path,
        trace=trace,
        session_count=25,
        price_overrides=price_overrides,
        price_context_overrides={
            "breakout_vs_prior60": 0.1,
            "relative_market_3d": 0.02,
            "relative_market_5d": 0.03,
            "relative_industry_return_3d": 0.02,
            "relative_industry_return_5d": 0.03,
            "amount_ratio_last_20d": 1.2,
        },
    )
    monitor_dir = tmp_path / "local_archive/forward_monitor"
    monitor_dir.mkdir(parents=True)
    previous_day = sessions[-2]
    (monitor_dir / f"snapshot-{previous_day}.json").write_text(
        json.dumps(
            {
                "snapshot_version": "forward-monitor-snapshot-v1",
                "analysis_date": str(previous_day),
                "as_of": datetime.combine(previous_day, datetime.min.time(), SHANGHAI).replace(hour=18).isoformat(),
                "episodes": [
                    {
                        "episode_id": "formal:2026-07-01:603969.SH:selected",
                        "breakout_vs_prior60": -0.1,
                        "relative_market_5d": 0.01,
                        "relative_industry_5d": 0.01,
                        "scenario_case_ids": [],
                        "d20_first_close_hit_20pct_date": None,
                        "data_limitations": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    episode = _prepare(tmp_path, sessions[-1])["episodes"][0]

    assert episode["d20_hit_20pct_close_within_20d"] is False
    assert episode["d20_first_close_hit_20pct_date"] is None
    assert episode["current_hit_20pct_close"] is True
    assert episode["current_first_close_hit_20pct_date"] == sessions[-1].isoformat()
    assert "target_hit_first_time" not in episode["attention_reasons"]
    assert "late_activation_candidate" in episode["attention_reasons"]


def test_fresh_event_waits_for_first_complete_observable_bar_and_alerts_once(tmp_path: Path) -> None:
    trace = _single_selected_trace(formation_date="2026-07-31", action_date="2026-08-03")
    trace["candidate_ledger"][0]["research_thesis"]["engine_type"] = "fresh_event_pending"
    trace["candidate_ledger"][0]["research_thesis"]["engine_status"] = "conditional"
    archive = tmp_path / "local_archive/forward_selection"
    archive.mkdir(parents=True)
    _write_trace(archive / "research-trace-2026-07-31.json", trace)
    sessions = _seed_monitor_project(tmp_path, trace=trace, session_count=3)
    for dataset in ("equity_daily", "adj_factor"):
        (
            tmp_path
            / f"local_warehouse/facts/{dataset}/trade_date={sessions[0]}/data.parquet"
        ).unlink()

    d1 = _prepare(tmp_path, sessions[0])["episodes"][0]
    d2 = _prepare(tmp_path, sessions[1])["episodes"][0]
    d3 = _prepare(tmp_path, sessions[2])["episodes"][0]

    assert "first_event_reaction" not in d1["attention_reasons"]
    assert d2["day_number"] == 2
    assert "first_event_reaction" in d2["attention_reasons"]
    assert "first_event_reaction" not in d3["attention_reasons"]


def test_formation_industry_only_uses_point_in_time_sw2021_l2_membership(tmp_path: Path) -> None:
    trace = _single_selected_trace(formation_date="2026-07-31", action_date="2026-08-03")
    archive = tmp_path / "local_archive/forward_selection"
    archive.mkdir(parents=True)
    _write_trace(archive / "research-trace-2026-07-31.json", trace)
    sessions = _seed_monitor_project(tmp_path, trace=trace, session_count=1)
    common = {
        "ts_code": "603969.SH",
        "valid_to": None,
    }
    _write_parquet(
        tmp_path,
        "local_warehouse/facts/industry_member/member_month=2026-08/data.parquet",
        [
            {**common, "industry_code": "RIGHT.SI", "industry_system": "SW2021", "level": "L2", "valid_from": date(2020, 1, 1), "available_at": datetime(2026, 8, 3, 8, tzinfo=SHANGHAI)},
            {**common, "industry_code": "WRONG-SYSTEM.SI", "industry_system": "OTHER", "level": "L2", "valid_from": date(2025, 1, 1), "available_at": datetime(2026, 8, 3, 8, tzinfo=SHANGHAI)},
            {**common, "industry_code": "WRONG-LEVEL.SI", "industry_system": "SW2021", "level": "L1", "valid_from": date(2025, 2, 1), "available_at": datetime(2026, 8, 3, 8, tzinfo=SHANGHAI)},
            {**common, "industry_code": "FUTURE.SI", "industry_system": "SW2021", "level": "L2", "valid_from": date(2025, 3, 1), "available_at": datetime(2026, 8, 3, 10, tzinfo=SHANGHAI)},
            {**common, "industry_code": "MISSING-TIME.SI", "industry_system": "SW2021", "level": "L2", "valid_from": date(2025, 4, 1), "available_at": None},
        ],
    )

    episode = _prepare(tmp_path, sessions[0])["episodes"][0]

    assert episode["original_group_code"] == "RIGHT.SI"


def test_prepare_copies_relative_fields_and_filters_announcements_by_available_at(tmp_path: Path) -> None:
    trace = _single_selected_trace(formation_date="2026-07-31", action_date="2026-08-03")
    archive = tmp_path / "local_archive/forward_selection"
    archive.mkdir(parents=True)
    _write_trace(archive / "research-trace-2026-07-31.json", trace)
    announcements = [
        {"announcement_id": "A1", "ts_code": "603969.SH", "title": "已公开公告", "announcement_time": datetime(2026, 8, 3, 10, tzinfo=SHANGHAI), "available_at": datetime(2026, 8, 3, 10, tzinfo=SHANGHAI)},
        {"announcement_id": "A2", "ts_code": "603969.SH", "title": "未来公告", "announcement_time": datetime(2026, 8, 3, 19, tzinfo=SHANGHAI), "available_at": datetime(2026, 8, 3, 19, tzinfo=SHANGHAI)},
    ]
    sessions = _seed_monitor_project(tmp_path, trace=trace, session_count=1, announcements=announcements)

    episode = _prepare(tmp_path, sessions[0])["episodes"][0]

    assert episode["relative_market_5d"] == pytest.approx(0.03)
    assert episode["relative_industry_5d"] == pytest.approx(0.025)
    assert [item["announcement_id"] for item in episode["new_announcements"]] == ["A1"]
    assert "new_official_event" in episode["attention_reasons"]


def test_prepare_detects_snapshot_changes_and_tail_candidates(tmp_path: Path) -> None:
    trace = _single_selected_trace(formation_date="2026-07-01", action_date="2026-07-02")
    archive = tmp_path / "local_archive/forward_selection"
    archive.mkdir(parents=True)
    _write_trace(archive / "research-trace-2026-07-01.json", trace)
    sessions = _seed_monitor_project(
        tmp_path,
        trace=trace,
        session_count=21,
        price_context_overrides={
            "relative_market_5d": 0.03,
            "relative_industry_return_5d": 0.025,
            "breakout_vs_prior60": 1.0,
            "scenario_case_ids": "confirmed_breakout",
        },
    )
    previous_day = sessions[-2]
    previous_dir = tmp_path / "local_archive/forward_monitor"
    previous_dir.mkdir(parents=True)
    previous_episode = {
        "episode_id": "formal:2026-07-01:603969.SH:selected",
        "relative_market_5d": -0.01,
        "relative_industry_5d": -0.01,
        "scenario_case_ids": [],
        "breakout_vs_prior60": 0.0,
        "first_close_hit_20pct_date": None,
    }
    (previous_dir / f"snapshot-{previous_day}.json").write_text(
        json.dumps({"snapshot_version": "forward-monitor-snapshot-v1", "analysis_date": str(previous_day), "as_of": datetime(2026, 7, 29, 18, tzinfo=SHANGHAI).isoformat(), "episodes": [previous_episode]}),
        encoding="utf-8",
    )

    episode = _prepare(tmp_path, sessions[-1])["episodes"][0]

    assert {"relative_state_changed", "scenario_changed", "breakout_changed", "late_activation_candidate"}.issubset(episode["attention_reasons"])


def test_late_activation_never_triggers_before_tail_and_fresh_event_triggers_d1(tmp_path: Path) -> None:
    trace = _single_selected_trace(formation_date="2026-07-31", action_date="2026-08-03")
    trace["candidate_ledger"][0]["research_thesis"]["engine_type"] = "fresh_event_pending"
    trace["candidate_ledger"][0]["research_thesis"]["engine_status"] = "conditional"
    archive = tmp_path / "local_archive/forward_selection"
    archive.mkdir(parents=True)
    _write_trace(archive / "research-trace-2026-07-31.json", trace)
    sessions = _seed_monitor_project(tmp_path, trace=trace, session_count=1, price_context_overrides={"breakout_vs_prior60": 1.0, "scenario_case_ids": "confirmed_breakout"})

    episode = _prepare(tmp_path, sessions[0])["episodes"][0]

    assert "first_event_reaction" in episode["attention_reasons"]
    assert "late_activation_candidate" not in episode["attention_reasons"]


def test_prepare_reads_each_daily_price_partition_once_across_episodes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trace = _trace(formation_date="2026-07-31", action_date="2026-08-03")
    archive = tmp_path / "local_archive/forward_selection"
    archive.mkdir(parents=True)
    _write_trace(archive / "research-trace-2026-07-31.json", trace)
    sessions = _seed_monitor_project(tmp_path, trace=trace, session_count=3)
    original = pd.read_parquet
    reads: dict[str, int] = {}

    def spy(path: Path, *args: object, **kwargs: object) -> pd.DataFrame:
        key = str(path)
        if "/facts/equity_daily/trade_date=" in key or "/facts/adj_factor/trade_date=" in key:
            reads[key] = reads.get(key, 0) + 1
        return original(path, *args, **kwargs)

    monkeypatch.setattr(pd, "read_parquet", spy)

    _prepare(tmp_path, sessions[-1])

    assert len(reads) == 6
    assert max(reads.values()) == 1


def test_data_problem_only_repeats_for_change_or_checkpoint(tmp_path: Path) -> None:
    trace = _single_selected_trace(formation_date="2026-07-31", action_date="2026-08-03")
    archive = tmp_path / "local_archive/forward_selection"
    archive.mkdir(parents=True)
    _write_trace(archive / "research-trace-2026-07-31.json", trace)
    sessions = _seed_monitor_project(tmp_path, trace=trace, session_count=3)
    (
        tmp_path
        / "local_warehouse/derived/market_context"
        / f"analysis_date={sessions[-1]}"
        / "formula_version=market-context-v3/data.parquet"
    ).unlink()
    (
        tmp_path
        / "local_warehouse/derived/price_analysis_context"
        / f"analysis_date={sessions[-1]}"
        / "formula_version=price-analysis-context-v2/data.parquet"
    ).unlink()

    d1 = _prepare(tmp_path, sessions[0])["episodes"][0]
    d2 = _prepare(tmp_path, sessions[1])["episodes"][0]
    d3 = _prepare(tmp_path, sessions[2])["episodes"][0]

    assert "data_problem" in d1["attention_reasons"]
    assert "data_problem" not in d2["attention_reasons"]
    assert "data_problem" in d3["attention_reasons"]


def test_previous_monitor_state_uses_final_report_ignores_pending_and_carries_forward(
    tmp_path: Path,
) -> None:
    trace = _single_selected_trace(formation_date="2026-07-31", action_date="2026-08-03")
    archive = tmp_path / "local_archive/forward_selection"
    archive.mkdir(parents=True)
    _write_trace(archive / "research-trace-2026-07-31.json", trace)
    sessions = _seed_monitor_project(tmp_path, trace=trace, session_count=3)
    d1_snapshot = _prepare(tmp_path, sessions[0])
    episode_id = d1_snapshot["episodes"][0]["episode_id"]
    monitor_dir = tmp_path / "local_archive/forward_monitor"
    final_d1 = monitor_dir / f"monitor-report-{sessions[0]}.json"
    final_d1.write_text(
        json.dumps(
            {
                "report_version": "daily-forward-monitor-report-v1",
                "analysis_date": sessions[0].isoformat(),
                "alerts": [
                    {
                        "episode_ids": [episode_id],
                        "monitor_state": "strengthening",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (monitor_dir / f"pending-report-{sessions[0]}.json").write_text(
        json.dumps(
            {
                "alerts": [
                    {
                        "episode_ids": [episode_id],
                        "monitor_state": "invalidated",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    d2 = _prepare(tmp_path, sessions[1])["episodes"][0]

    assert d2["previous_monitor_state"] == "strengthening"

    final_d1.unlink()
    (monitor_dir / f"monitor-report-{sessions[1]}.json").write_text(
        json.dumps({"analysis_date": sessions[1].isoformat(), "alerts": []}),
        encoding="utf-8",
    )

    carried_d3 = _prepare(tmp_path, sessions[2])["episodes"][0]

    assert carried_d3["previous_monitor_state"] == "strengthening"

    (monitor_dir / f"monitor-report-{sessions[1]}.json").write_text(
        json.dumps(
            {
                "analysis_date": sessions[1].isoformat(),
                "alerts": [
                    {
                        "episode_ids": [episode_id],
                        "monitor_state": "invalidated",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    overridden_d3 = _prepare(tmp_path, sessions[2])["episodes"][0]

    assert overridden_d3["previous_monitor_state"] == "invalidated"


def test_prepare_is_idempotent_and_never_changes_forward_csv(tmp_path: Path) -> None:
    trace = _single_selected_trace(formation_date="2026-07-01", action_date="2026-07-02")
    archive = tmp_path / "local_archive/forward_selection"
    archive.mkdir(parents=True)
    _write_trace(archive / "research-trace-2026-07-01.json", trace)
    sessions = _seed_monitor_project(tmp_path, trace=trace, session_count=21)
    forward_csv = tmp_path / "local_archive/forward_selection/forward-selection.csv"
    forward_csv.write_bytes(b"existing,d20,result\n")

    first = _prepare(tmp_path, sessions[-1])
    snapshot_path = tmp_path / f"local_archive/forward_monitor/snapshot-{sessions[-1]}.json"
    first_bytes = snapshot_path.read_bytes()
    second = _prepare(tmp_path, sessions[-1])

    assert first == second
    assert snapshot_path.read_bytes() == first_bytes
    assert forward_csv.read_bytes() == b"existing,d20,result\n"


def _report_payload(
    snapshot: dict,
    *,
    alerts: list[dict] | None = None,
    unreported: int = 0,
    report_version: str = "daily-forward-monitor-report-v2",
) -> dict:
    return {
        "report_version": report_version,
        "analysis_date": snapshot["analysis_date"],
        "as_of": snapshot["as_of"],
        "market_overview": {
            "market_propagation_mode": "sector_rotation",
            "market_risk_overlays": [],
            "what_changed": "市场变化不大",
            "implication_for_monitored_stocks": "只看触发变化的股票",
        },
        "pool_summary": {
            **{
                key: snapshot["summary"][key]
                for key in (
                    "open_episode_count", "distinct_stock_count",
                    "selected_count", "comparator_count", "primary_count",
                    "passive_tail_count", "attention_stock_count",
                )
            },
            "routine_stock_count": max(snapshot["summary"]["distinct_stock_count"] - snapshot["summary"]["attention_stock_count"], 0),
        },
        "alerts": alerts or [],
        "unreported_attention_count": unreported,
        "routine_summary": "其余股票继续按程序记录。",
    }


def _episode_review(
    episode_id: str,
    *,
    final: dict | None = None,
) -> dict:
    return {
        "episode_id": episode_id,
        "original_reason_plain_language": "当时看好它自身的价格表现连续强于市场和同类。",
        "original_key_risk_plain_language": "当时最担心的是这股强势不能持续。",
        "current_assessment": "partly_supported",
        "best_supported_explanation": "stock_specific_move",
        "current_weak_or_failed_link": "none",
        "current_review": "原判断有一部分得到走势支持，但仍需继续观察。",
        "comparison_interpretation": "程序给出的两边价格路径支持这一比较。",
        "final_twenty_day_review": final,
    }


def _final_review(
    decision_review: str = "logic_and_stock_both_reasonable",
) -> dict:
    return {
        "decision_review": decision_review,
        "weak_or_failed_link": "none",
        "overall_review": "前20个交易日结束后，原判断和具体股票都基本合理。",
    }


def _alert(ts_code: str, episode_id: str) -> dict:
    return {
        "ts_code": ts_code,
        "name": "银龙股份",
        "episode_ids": [episode_id],
        "roles": ["selected"],
        "day_numbers": [1],
        "original_engine_types": ["independent_demand_acceleration"],
        "alert_type": "checkpoint",
        "monitor_state": "routine",
        "market_change": "无明显变化",
        "sector_change": "无明显变化",
        "stock_change": "到达固定检查日",
        "company_change": "无新公告",
        "outlook_1_3d": "range_or_wait",
        "confirmation_condition": "相对表现转强",
        "invalidation_condition": "相对表现继续走弱",
        "why_reported": "固定检查日",
        "episode_reviews": [_episode_review(episode_id)],
    }


def _mixed_role_snapshot() -> dict:
    selected_id = "daily:2026-07-31:603969.SH:selected"
    comparator_id = "daily:2026-07-20:603969.SH:comparator"
    episodes = [
        {
            "episode_id": selected_id,
            "formation_date": "2026-07-31",
            "action_date": "2026-08-03",
            "ts_code": "603969.SH",
            "name": "银龙股份",
            "role": "selected",
            "day_number": 1,
            "original_engine_type": "independent_demand_acceleration",
            "original_primary_reason": "入选时个股独立走强",
        },
        {
            "episode_id": comparator_id,
            "formation_date": "2026-07-20",
            "action_date": "2026-07-21",
            "ts_code": "603969.SH",
            "name": "银龙股份",
            "role": "comparator",
            "day_number": 10,
            "original_engine_type": "sector_leader_cluster",
            "original_primary_reason": "对照时用于比较板块龙头",
        },
    ]
    return {
        "snapshot_version": "forward-monitor-snapshot-v1",
        "analysis_date": "2026-08-03",
        "as_of": "2026-08-03T18:00:00+08:00",
        "summary": {
            "open_episode_count": 2,
            "distinct_stock_count": 1,
            "selected_count": 1,
            "comparator_count": 1,
            "primary_count": 2,
            "passive_tail_count": 0,
            "attention_stock_count": 1,
            "closed_count": 0,
        },
        "episodes": episodes,
        "attention_stocks": [
            {
                "ts_code": "603969.SH",
                "name": "银龙股份",
                "episode_ids": [selected_id, comparator_id],
                "roles": ["selected", "comparator"],
                "day_numbers": [1, 10],
                "original_engine_types": [
                    "independent_demand_acceleration",
                    "sector_leader_cluster",
                ],
                "attention_reasons": ["checkpoint"],
            }
        ],
    }


def test_public_markdown_hides_comparator_episode(tmp_path: Path) -> None:
    snapshot = _mixed_role_snapshot()
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    alert = _alert("603969.SH", snapshot["attention_stocks"][0]["episode_ids"][0])
    alert.update(
        episode_ids=snapshot["attention_stocks"][0]["episode_ids"],
        episode_reviews=[
            _episode_review(episode_id)
            for episode_id in snapshot["attention_stocks"][0]["episode_ids"]
        ],
        roles=["selected", "comparator"],
        day_numbers=[1, 10],
        original_engine_types=[
            "independent_demand_acceleration",
            "sector_leader_cluster",
        ],
    )
    pending = tmp_path / "pending.json"
    pending.write_text(
        json.dumps(_report_payload(snapshot, alerts=[alert]), ensure_ascii=False),
        encoding="utf-8",
    )

    summary = record_forward_monitor(
        snapshot_file=snapshot_path,
        report_file=pending,
        project_root=tmp_path,
    )

    saved = json.loads(Path(summary.json_file).read_text(encoding="utf-8"))
    markdown = Path(summary.markdown_file).read_text(encoding="utf-8")
    assert saved["alerts"][0]["roles"] == ["selected", "comparator"]
    assert markdown.count("### 银龙股份（603969.SH）") == 1
    assert "用于比较的股票" not in markdown
    assert "和当时最接近的备选相比" not in markdown
    assert "当时备选股" not in markdown
    assert "该次研究后的第十个交易日" not in markdown


def test_record_rejects_omitting_one_attention_episode_for_the_same_stock(
    tmp_path: Path,
) -> None:
    snapshot = _mixed_role_snapshot()
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    alert = _alert("603969.SH", snapshot["attention_stocks"][0]["episode_ids"][0])
    pending = tmp_path / "pending.json"
    pending.write_text(
        json.dumps(_report_payload(snapshot, alerts=[alert]), ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="all stock attention episodes"):
        record_forward_monitor(
            snapshot_file=snapshot_path,
            report_file=pending,
            project_root=tmp_path,
        )


def test_report_model_rejects_more_than_eight_or_duplicate_stocks() -> None:
    snapshot = {"analysis_date": "2026-08-03", "as_of": "2026-08-03T18:00:00+08:00", "summary": {"open_episode_count": 9, "distinct_stock_count": 9, "attention_stock_count": 9, "selected_count": 9, "comparator_count": 0, "primary_count": 9, "passive_tail_count": 0, "closed_count": 0}}
    nine = [_alert(f"00000{i}.SZ", f"e{i}") for i in range(9)]
    with pytest.raises(ValidationError):
        DailyForwardMonitorReportV2.model_validate(_report_payload(snapshot, alerts=nine))
    duplicate = [_alert("000001.SZ", "e1"), _alert("000001.SZ", "e2")]
    with pytest.raises(ValidationError):
        DailyForwardMonitorReportV2.model_validate(_report_payload(snapshot, alerts=duplicate))


def test_report_accepts_eight_alerts_and_counts_the_rest() -> None:
    snapshot = {"analysis_date": "2026-08-03", "as_of": "2026-08-03T18:00:00+08:00", "summary": {"open_episode_count": 9, "distinct_stock_count": 9, "attention_stock_count": 9, "selected_count": 9, "comparator_count": 0, "primary_count": 9, "passive_tail_count": 0, "closed_count": 0}}
    alerts = [_alert(f"00000{i}.SZ", f"e{i}") for i in range(8)]

    report = DailyForwardMonitorReportV2.model_validate(
        _report_payload(snapshot, alerts=alerts, unreported=1)
    )

    assert len(report.alerts) == 8
    assert report.unreported_attention_count == 1


def test_v1_report_model_remains_readable() -> None:
    snapshot = {
        "analysis_date": "2026-08-03",
        "as_of": "2026-08-03T18:00:00+08:00",
        "summary": {
            "open_episode_count": 0,
            "distinct_stock_count": 0,
            "attention_stock_count": 0,
            "selected_count": 0,
            "comparator_count": 0,
            "primary_count": 0,
            "passive_tail_count": 0,
        },
    }
    payload = _report_payload(
        snapshot,
        report_version="daily-forward-monitor-report-v1",
    )

    report = DailyForwardMonitorReportV1.model_validate(payload)

    assert report.report_version == "daily-forward-monitor-report-v1"


def test_v2_report_requires_one_review_per_episode() -> None:
    snapshot = {
        "analysis_date": "2026-08-03",
        "as_of": "2026-08-03T18:00:00+08:00",
        "summary": {
            "open_episode_count": 1,
            "distinct_stock_count": 1,
            "attention_stock_count": 1,
            "selected_count": 1,
            "comparator_count": 0,
            "primary_count": 1,
            "passive_tail_count": 0,
        },
    }
    alert = _alert("603969.SH", "e1")
    without_review = json.loads(json.dumps(alert))
    without_review.pop("episode_reviews")
    with pytest.raises(ValidationError):
        DailyForwardMonitorReportV2.model_validate(
            _report_payload(snapshot, alerts=[without_review])
        )

    duplicate = json.loads(json.dumps(alert))
    duplicate["episode_reviews"].append(_episode_review("e1"))
    with pytest.raises(ValidationError, match="exactly once"):
        DailyForwardMonitorReportV2.model_validate(
            _report_payload(snapshot, alerts=[duplicate])
        )

    extra = json.loads(json.dumps(alert))
    extra["episode_reviews"].append(_episode_review("e2"))
    with pytest.raises(ValidationError, match="exactly once"):
        DailyForwardMonitorReportV2.model_validate(
            _report_payload(snapshot, alerts=[extra])
        )

    report = DailyForwardMonitorReportV2.model_validate(
        _report_payload(snapshot, alerts=[alert])
    )
    assert report.alerts[0].episode_reviews[0].current_assessment == (
        "partly_supported"
    )


@pytest.mark.parametrize(
    ("day_number", "expected"),
    [
        (1, "推荐后的第一个交易日"),
        (2, "推荐后的第二个交易日"),
        (10, "推荐后的第十个交易日"),
        (11, "推荐后的第十一个交易日"),
        (20, "推荐后的第二十个交易日"),
        (21, "推荐后的第二十一个交易日"),
        (30, "推荐后的第三十个交易日"),
    ],
)
def test_human_trading_day(day_number: int, expected: str) -> None:
    assert _human_trading_day(day_number) == expected


@pytest.mark.parametrize(
    "mismatch",
    [
        "pool_summary",
        "name",
        "roles",
        "original_engine_types",
        "day_numbers",
        "unreported_attention_count",
        "market_propagation_mode",
    ],
)
def test_record_rejects_each_snapshot_contract_mismatch(
    tmp_path: Path,
    mismatch: str,
) -> None:
    trace = _single_selected_trace(formation_date="2026-07-31", action_date="2026-08-03")
    archive = tmp_path / "local_archive/forward_selection"
    archive.mkdir(parents=True)
    _write_trace(archive / "research-trace-2026-07-31.json", trace)
    sessions = _seed_monitor_project(tmp_path, trace=trace, session_count=1)
    snapshot = _prepare(tmp_path, sessions[0])
    snapshot_path = tmp_path / f"local_archive/forward_monitor/snapshot-{sessions[0]}.json"
    episode_id = snapshot["episodes"][0]["episode_id"]
    payload = _report_payload(
        snapshot,
        alerts=[_alert("603969.SH", episode_id)],
    )
    if mismatch == "pool_summary":
        payload["pool_summary"]["selected_count"] += 1
    elif mismatch == "name":
        payload["alerts"][0]["name"] = "错误名称"
    elif mismatch == "roles":
        payload["alerts"][0]["roles"] = ["comparator"]
    elif mismatch == "original_engine_types":
        payload["alerts"][0]["original_engine_types"] = ["anchor_only"]
    elif mismatch == "day_numbers":
        payload["alerts"][0]["day_numbers"] = [2]
    elif mismatch == "unreported_attention_count":
        payload["unreported_attention_count"] = 1
    else:
        payload["market_overview"]["market_propagation_mode"] = "not-a-v4-mode"
    pending = tmp_path / f"pending-{mismatch}.json"
    pending.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError):
        record_forward_monitor(
            snapshot_file=snapshot_path,
            report_file=pending,
            project_root=tmp_path,
        )


@pytest.mark.parametrize(
    "mode",
    [
        "broad_sustained_participation",
        "one_day_repair",
        "sector_rotation",
        "concentrated_speculation",
        "weak_or_fragmented",
        "unclear",
    ],
)
def test_report_accepts_each_v4_market_propagation_mode(mode: str) -> None:
    snapshot = {
        "analysis_date": "2026-08-03",
        "as_of": "2026-08-03T18:00:00+08:00",
        "summary": {
            "open_episode_count": 0,
            "distinct_stock_count": 0,
            "attention_stock_count": 0,
            "selected_count": 0,
            "comparator_count": 0,
            "primary_count": 0,
            "passive_tail_count": 0,
        },
    }
    payload = _report_payload(snapshot)
    payload["market_overview"]["market_propagation_mode"] = mode

    DailyForwardMonitorReportV2.model_validate(payload)


def test_record_is_idempotent_and_preserves_conflicting_pending_report(tmp_path: Path) -> None:
    trace = _single_selected_trace(formation_date="2026-07-31", action_date="2026-08-03")
    archive = tmp_path / "local_archive/forward_selection"
    archive.mkdir(parents=True)
    _write_trace(archive / "research-trace-2026-07-31.json", trace)
    sessions = _seed_monitor_project(tmp_path, trace=trace, session_count=1)
    snapshot = _prepare(tmp_path, sessions[0])
    snapshot_path = tmp_path / f"local_archive/forward_monitor/snapshot-{sessions[0]}.json"
    episode_id = snapshot["episodes"][0]["episode_id"]
    payload = _report_payload(
        snapshot,
        alerts=[_alert("603969.SH", episode_id)],
    )
    first_pending = tmp_path / "first-pending.json"
    first_pending.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    first = record_forward_monitor(
        snapshot_file=snapshot_path,
        report_file=first_pending,
        project_root=tmp_path,
    )
    final_json = Path(first.json_file)
    final_markdown = Path(first.markdown_file)
    original_json = final_json.read_bytes()
    original_markdown = final_markdown.read_bytes()

    same_pending = tmp_path / "same-pending.json"
    same_pending.write_text(
        json.dumps(payload, ensure_ascii=False, indent=4),
        encoding="utf-8",
    )
    repeated = record_forward_monitor(
        snapshot_file=snapshot_path,
        report_file=same_pending,
        project_root=tmp_path,
    )

    assert repeated.status == "already_recorded"
    assert not same_pending.exists()
    assert final_json.read_bytes() == original_json
    assert final_markdown.read_bytes() == original_markdown

    conflict_payload = json.loads(json.dumps(payload))
    conflict_payload["routine_summary"] = "这是一份不同内容的日报。"
    conflict_pending = tmp_path / "conflict-pending.json"
    conflict_pending.write_text(
        json.dumps(conflict_payload, ensure_ascii=False),
        encoding="utf-8",
    )
    conflict = record_forward_monitor(
        snapshot_file=snapshot_path,
        report_file=conflict_pending,
        project_root=tmp_path,
    )

    assert conflict.status == "report_conflict"
    assert conflict_pending.exists()
    assert final_json.read_bytes() == original_json
    assert final_markdown.read_bytes() == original_markdown


def test_record_recovers_missing_markdown_without_rewriting_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trace = _single_selected_trace(
        formation_date="2026-07-31",
        action_date="2026-08-03",
    )
    archive = tmp_path / "local_archive/forward_selection"
    archive.mkdir(parents=True)
    _write_trace(archive / "research-trace-2026-07-31.json", trace)
    sessions = _seed_monitor_project(tmp_path, trace=trace, session_count=1)
    snapshot = _prepare(tmp_path, sessions[0])
    snapshot_path = (
        tmp_path / f"local_archive/forward_monitor/snapshot-{sessions[0]}.json"
    )
    payload = _report_payload(
        snapshot,
        alerts=[_alert("603969.SH", snapshot["episodes"][0]["episode_id"])],
    )
    first_pending = tmp_path / "first-pending.json"
    first_pending.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    first = record_forward_monitor(
        snapshot_file=snapshot_path,
        report_file=first_pending,
        project_root=tmp_path,
    )
    final_json = Path(first.json_file)
    final_markdown = Path(first.markdown_file)
    original_json = final_json.read_bytes()
    original_markdown = final_markdown.read_bytes()
    final_markdown.unlink()

    recovery_pending = tmp_path / "recovery-pending.json"
    recovery_pending.write_text(
        json.dumps(payload, ensure_ascii=False, indent=4),
        encoding="utf-8",
    )
    recovered = record_forward_monitor(
        snapshot_file=snapshot_path,
        report_file=recovery_pending,
        project_root=tmp_path,
    )

    assert recovered.status == "already_recorded"
    assert not recovery_pending.exists()
    assert final_json.read_bytes() == original_json
    assert final_markdown.read_bytes() == original_markdown

    final_markdown.unlink()
    failed_pending = tmp_path / "failed-pending.json"
    failed_pending.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )

    def fail_markdown_write(path: Path, content: str) -> None:
        raise OSError("markdown recovery failed")

    monkeypatch.setattr(
        "stock_analyzer.ops.forward_monitor._atomic_write_text",
        fail_markdown_write,
    )

    with pytest.raises(OSError, match="markdown recovery failed"):
        record_forward_monitor(
            snapshot_file=snapshot_path,
            report_file=failed_pending,
            project_root=tmp_path,
        )

    assert final_json.read_bytes() == original_json
    assert not final_markdown.exists()
    assert failed_pending.exists()


def test_markdown_uses_plain_chinese_and_natural_review_sections(
    tmp_path: Path,
) -> None:
    trace = _single_selected_trace(formation_date="2026-07-31", action_date="2026-08-03")
    archive = tmp_path / "local_archive/forward_selection"
    archive.mkdir(parents=True)
    _write_trace(archive / "research-trace-2026-07-31.json", trace)
    sessions = _seed_monitor_project(tmp_path, trace=trace, session_count=1)
    snapshot = _prepare(tmp_path, sessions[0])
    snapshot_path = tmp_path / f"local_archive/forward_monitor/snapshot-{sessions[0]}.json"
    episode_id = snapshot["episodes"][0]["episode_id"]
    alert = _alert("603969.SH", episode_id)
    alert.update(
        {
            "alert_type": "checkpoint",
            "monitor_state": "strengthening",
            "market_change": "测试中的大盘变化",
            "sector_change": "测试中的板块变化",
            "stock_change": "测试中的个股变化",
            "company_change": "测试中的公司变化",
            "outlook_1_3d": "continuation_possible",
            "confirmation_condition": "测试中需要看到的继续走强事实",
            "invalidation_condition": "测试中说明原判断不再成立的事实",
            "why_reported": "测试提醒原因",
        }
    )
    pending = tmp_path / "markdown-pending.json"
    pending.write_text(
        json.dumps(
            _report_payload(snapshot, alerts=[alert]),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    summary = record_forward_monitor(
        snapshot_file=snapshot_path,
        report_file=pending,
        project_root=tmp_path,
    )
    markdown = Path(summary.markdown_file).read_text(encoding="utf-8")

    assert "今天的市场情况" in markdown
    assert "正式推荐股票的走势复盘" in markdown
    assert "推荐后的第一个交易日" in markdown
    headings = (
        "当初为什么推荐",
        "推荐后怎么走",
        "最近发生了什么，为什么今天提到它",
        "现在怎么看",
        "接下来关注什么",
    )
    positions = [markdown.index(heading) for heading in headings]
    assert positions == sorted(positions)
    assert "当时看好它自身的价格表现连续强于市场和同类" in markdown
    assert "测试提醒原因" in markdown
    assert "测试中的大盘变化" in markdown
    assert "测试中的板块变化" in markdown
    assert "测试中的个股变化" in markdown
    assert "测试中的公司变化" in markdown
    assert "市场方面" not in markdown
    assert "行业方面" not in markdown
    assert "公司方面" not in markdown
    assert "个股方面" not in markdown
    assert "当前收盘价较期间最高收盘价回落0.00%" in markdown
    assert "当前收盘价较期间最高收盘价回落+0.00%" not in markdown
    assert "测试中需要看到的继续走强事实" in markdown
    assert "测试中说明原判断不再成立的事实" in markdown
    for forbidden in (
        "D1", "D2", "D10", "D20", "发动机", "行动日", "行动窗口",
        "原角色", "MFE", "MAE", "selected", "comparator",
        "nearest_nonselection", "episode", "episode_ids", "engine_type",
        "engine_status", "确认条件", "失效条件", "基础情形",
        "原逻辑", "传播链", "价格确认", "弱环节", "状态",
        "和当时最接近的备选相比",
    ):
        assert forbidden not in markdown


def test_markdown_names_the_second_trading_day_without_d_label(
    tmp_path: Path,
) -> None:
    trace = _single_selected_trace(
        formation_date="2026-07-31",
        action_date="2026-08-03",
    )
    archive = tmp_path / "local_archive/forward_selection"
    archive.mkdir(parents=True)
    _write_trace(archive / "research-trace-2026-07-31.json", trace)
    sessions = _seed_monitor_project(
        tmp_path,
        trace=trace,
        session_count=2,
        announcements=[
            {
                "announcement_id": "A2",
                "ts_code": "603969.SH",
                "title": "测试公告",
                "announcement_time": datetime(2026, 8, 4, 17, tzinfo=SHANGHAI),
                "available_at": datetime(2026, 8, 4, 17, tzinfo=SHANGHAI),
            }
        ],
    )
    snapshot = _prepare(tmp_path, sessions[-1])
    snapshot_path = (
        tmp_path / f"local_archive/forward_monitor/snapshot-{sessions[-1]}.json"
    )
    alert = _alert("603969.SH", snapshot["episodes"][0]["episode_id"])
    alert["day_numbers"] = [2]
    alert["alert_type"] = "new_event"
    pending = tmp_path / "pending-d2.json"
    pending.write_text(
        json.dumps(_report_payload(snapshot, alerts=[alert]), ensure_ascii=False),
        encoding="utf-8",
    )

    summary = record_forward_monitor(
        snapshot_file=snapshot_path,
        report_file=pending,
        project_root=tmp_path,
    )
    markdown = Path(summary.markdown_file).read_text(encoding="utf-8")

    assert "推荐后的第二个交易日" in markdown
    assert "D2" not in markdown


def test_late_activation_markdown_uses_plain_tail_explanation(tmp_path: Path) -> None:
    trace = _single_selected_trace(
        formation_date="2026-07-01",
        action_date="2026-07-02",
    )
    archive = tmp_path / "local_archive/forward_selection"
    archive.mkdir(parents=True)
    _write_trace(archive / "research-trace-2026-07-01.json", trace)
    sessions = _seed_monitor_project(tmp_path, trace=trace, session_count=21)
    snapshot = _prepare(tmp_path, sessions[-1])
    snapshot_path = (
        tmp_path / f"local_archive/forward_monitor/snapshot-{sessions[-1]}.json"
    )
    episode = snapshot["episodes"][0]
    episode["attention_reasons"] = ["late_activation_candidate"]
    snapshot["attention_stocks"] = [
        {
            "ts_code": episode["ts_code"],
            "name": episode["name"],
            "episode_ids": [episode["episode_id"]],
            "roles": [episode["role"]],
            "day_numbers": [episode["day_number"]],
            "original_engine_types": [episode["original_engine_type"]],
            "attention_reasons": ["late_activation_candidate"],
        }
    ]
    snapshot["summary"]["attention_stock_count"] = 1
    snapshot_path.write_text(
        json.dumps(snapshot, ensure_ascii=False),
        encoding="utf-8",
    )
    alert = _alert("603969.SH", snapshot["episodes"][0]["episode_id"])
    alert["day_numbers"] = [21]
    alert["alert_type"] = "late_activation"
    alert["episode_reviews"][0]["final_twenty_day_review"] = _final_review(
        "unknown"
    )
    pending = tmp_path / "pending-late-activation.json"
    pending.write_text(
        json.dumps(_report_payload(snapshot, alerts=[alert]), ensure_ascii=False),
        encoding="utf-8",
    )

    summary = record_forward_monitor(
        snapshot_file=snapshot_path,
        report_file=pending,
        project_root=tmp_path,
    )
    markdown = Path(summary.markdown_file).read_text(encoding="utf-8")

    assert "推荐后的第二十一个交易日" in markdown
    assert (
        "这只股票在前20个交易日结束后才开始明显走强，因此不会改变前20天的原评价结果。"
        in markdown
    )
    assert "迟到启动" not in markdown
    assert "D21" not in markdown


def test_day_twenty_markdown_adds_final_review_section(tmp_path: Path) -> None:
    trace = _single_selected_trace(
        formation_date="2026-07-01",
        action_date="2026-07-02",
    )
    archive = tmp_path / "local_archive/forward_selection"
    archive.mkdir(parents=True)
    _write_trace(archive / "research-trace-2026-07-01.json", trace)
    sessions = _seed_monitor_project(tmp_path, trace=trace, session_count=20)
    snapshot = _prepare(tmp_path, sessions[-1])
    snapshot_path = (
        tmp_path / f"local_archive/forward_monitor/snapshot-{sessions[-1]}.json"
    )
    alert = _alert("603969.SH", snapshot["episodes"][0]["episode_id"])
    alert["day_numbers"] = [20]
    alert["episode_reviews"][0].update(
        current_assessment="supported",
        final_twenty_day_review=_final_review(),
    )
    pending = tmp_path / "pending-day-twenty.json"
    pending.write_text(
        json.dumps(_report_payload(snapshot, alerts=[alert]), ensure_ascii=False),
        encoding="utf-8",
    )

    summary = record_forward_monitor(
        snapshot_file=snapshot_path,
        report_file=pending,
        project_root=tmp_path,
    )
    markdown = Path(summary.markdown_file).read_text(encoding="utf-8")

    assert "推荐后的第二十个交易日" in markdown
    assert "现在怎么看" in markdown
    assert "目前涨跌为+20.00%" in markdown
    assert "期间最高收盘涨幅为+20.00%" in markdown
    assert "盘中最高涨幅为+25.00%" in markdown
    assert "期间最深跌幅为-5.00%" in markdown
    assert "期间最大收盘回撤为" in markdown
    assert "当前收盘价较期间最高收盘价回落" in markdown
    assert markdown.count("前20个交易日结束后，原判断和具体股票都基本合理。") == 1
    assert "前20天最终判断中，最薄弱的是" not in markdown
    assert "D20" not in markdown


def test_markdown_explains_missing_original_thesis_and_unmatched_alternative(
    tmp_path: Path,
) -> None:
    snapshot = _mixed_role_snapshot()
    for episode in snapshot["episodes"]:
        episode["original_research_thesis"] = None
        episode["data_limitations"] = ["missing_original_research_thesis"]
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    alert = _alert(
        "603969.SH",
        snapshot["attention_stocks"][0]["episode_ids"][0],
    )
    alert.update(
        episode_ids=snapshot["attention_stocks"][0]["episode_ids"],
        episode_reviews=[
            _episode_review(episode_id)
            for episode_id in snapshot["attention_stocks"][0]["episode_ids"]
        ],
        roles=["selected", "comparator"],
        day_numbers=[1, 10],
        original_engine_types=[
            "independent_demand_acceleration",
            "sector_leader_cluster",
        ],
    )
    pending = tmp_path / "pending-missing-thesis.json"
    pending.write_text(
        json.dumps(_report_payload(snapshot, alerts=[alert]), ensure_ascii=False),
        encoding="utf-8",
    )

    summary = record_forward_monitor(
        snapshot_file=snapshot_path,
        report_file=pending,
        project_root=tmp_path,
    )
    markdown = Path(summary.markdown_file).read_text(encoding="utf-8")

    assert (
        "当时留下的原始判断不完整，因此这次只能复盘价格表现，不能逐项审查当时的理由。"
        in markdown
    )
    assert "当时没有留下能够严格匹配的备选股票" not in markdown
    assert "和当时最接近的备选相比" not in markdown


def test_record_requires_attention_stock_and_writes_short_json_and_markdown(tmp_path: Path) -> None:
    trace = _single_selected_trace(formation_date="2026-07-31", action_date="2026-08-03")
    archive = tmp_path / "local_archive/forward_selection"
    archive.mkdir(parents=True)
    _write_trace(archive / "research-trace-2026-07-31.json", trace)
    sessions = _seed_monitor_project(tmp_path, trace=trace, session_count=1)
    snapshot = _prepare(tmp_path, sessions[0])
    snapshot_path = tmp_path / f"local_archive/forward_monitor/snapshot-{sessions[0]}.json"
    episode_id = snapshot["episodes"][0]["episode_id"]
    invalid_file = tmp_path / "invalid.json"
    invalid_file.write_text(json.dumps(_report_payload(snapshot, alerts=[_alert("999999.SZ", episode_id)])), encoding="utf-8")
    with pytest.raises(ValueError, match="attention"):
        record_forward_monitor(snapshot_file=snapshot_path, report_file=invalid_file, project_root=tmp_path)

    report_file = tmp_path / "pending-report.json"
    report_file.write_text(json.dumps(_report_payload(snapshot, alerts=[_alert("603969.SH", episode_id)], unreported=0)), encoding="utf-8")
    summary = record_forward_monitor(snapshot_file=snapshot_path, report_file=report_file, project_root=tmp_path)

    assert summary.alert_count == 1
    assert not report_file.exists()
    saved = json.loads(Path(summary.json_file).read_text(encoding="utf-8"))
    markdown = Path(summary.markdown_file).read_text(encoding="utf-8")
    assert saved["alerts"][0]["ts_code"] == "603969.SH"
    assert saved["report_version"] == "daily-forward-monitor-report-v2"
    assert "今天的市场情况" in markdown
    assert "正式推荐股票的走势复盘" in markdown
    assert "全部跟踪记录" not in markdown
    assert "range_or_wait" not in markdown


def _review_snapshot(
    *,
    day_number: int,
    frozen_review: dict | None = None,
    formation_date: str = "2026-07-31",
    role: str = "selected",
) -> dict:
    episode_id = f"formal:{formation_date}:603969.SH:{role}"
    episode = {
        "episode_id": episode_id,
        "formation_date": formation_date,
        "action_date": "2026-08-03",
        "ts_code": "603969.SH",
        "name": "银龙股份",
        "role": role,
        "day_number": day_number,
        "original_engine_type": "independent_demand_acceleration",
        "original_primary_reason": "原始理由",
        "original_selection_reason": "原始选择理由",
        "original_strongest_counterevidence": "原始风险",
        "current_close_return_since_entry": 0.08,
        "current_max_close_return_since_entry": 0.12,
        "current_max_high_return_since_entry": 0.15,
        "current_mae_since_entry": -0.04,
        "current_max_close_drawdown": -0.06,
        "current_close_drawdown_from_peak": -0.035,
        "d20_close_return_since_entry": 0.08 if day_number >= 20 else None,
        "d20_max_close_return_since_entry": 0.12 if day_number >= 20 else None,
        "d20_max_high_return_since_entry": 0.15 if day_number >= 20 else None,
        "d20_mae_since_entry": -0.04 if day_number >= 20 else None,
        "d20_max_close_drawdown": -0.06 if day_number >= 20 else None,
        "d20_close_drawdown_from_peak": -0.035 if day_number >= 20 else None,
        "relative_market_1d": 0.011,
        "relative_market_3d": 0.022,
        "relative_market_5d": 0.033,
        "relative_market_20d": 0.044,
        "relative_industry_1d": 0.005,
        "relative_industry_3d": 0.015,
        "relative_industry_5d": 0.025,
        "relative_industry_20d": 0.035,
        "frozen_twenty_day_review": frozen_review,
        "pair_context": {"pair_status": "unavailable"},
        "data_limitations": [],
    }
    return {
        "snapshot_version": "forward-monitor-snapshot-v1",
        "analysis_date": "2026-08-31",
        "as_of": "2026-08-31T18:00:00+08:00",
        "summary": {
            "open_episode_count": 1,
            "distinct_stock_count": 1,
            "selected_count": int(role == "selected"),
            "comparator_count": int(role == "comparator"),
            "primary_count": int(day_number <= 20),
            "passive_tail_count": int(day_number > 20),
            "attention_stock_count": 1,
            "closed_count": 0,
        },
        "episodes": [episode],
        "attention_stocks": [
            {
                "ts_code": "603969.SH",
                "name": "银龙股份",
                "episode_ids": [episode_id],
                "roles": [role],
                "day_numbers": [day_number],
                "original_engine_types": ["independent_demand_acceleration"],
                "attention_reasons": ["checkpoint"],
            }
        ],
    }


def _record_review_payload(
    tmp_path: Path,
    snapshot: dict,
    review: dict,
) -> tuple[Path, Path]:
    snapshot_path = tmp_path / "snapshot.json"
    pending_path = tmp_path / "pending.json"
    snapshot_path.write_text(
        json.dumps(snapshot, ensure_ascii=False),
        encoding="utf-8",
    )
    alert = _alert(
        "603969.SH",
        snapshot["attention_stocks"][0]["episode_ids"][0],
    )
    alert["day_numbers"] = snapshot["attention_stocks"][0]["day_numbers"]
    alert["roles"] = snapshot["attention_stocks"][0]["roles"]
    alert["episode_reviews"] = [review]
    pending_path.write_text(
        json.dumps(
            _report_payload(snapshot, alerts=[alert]),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return snapshot_path, pending_path


def test_each_episode_has_its_own_maturity_and_final_review(
    tmp_path: Path,
) -> None:
    old = _review_snapshot(day_number=20)
    old_episode = old["episodes"][0]
    new_episode = {
        **old_episode,
        "episode_id": "formal:2026-08-27:603969.SH:selected",
        "formation_date": "2026-08-27",
        "day_number": 2,
        "d20_close_return_since_entry": None,
        "d20_max_close_return_since_entry": None,
        "d20_max_high_return_since_entry": None,
        "d20_mae_since_entry": None,
        "d20_max_close_drawdown": None,
        "d20_close_drawdown_from_peak": None,
    }
    snapshot = old
    snapshot["episodes"].append(new_episode)
    snapshot["summary"]["open_episode_count"] = 2
    snapshot["summary"]["selected_count"] = 2
    snapshot["summary"]["primary_count"] = 2
    snapshot["attention_stocks"][0].update(
        episode_ids=[old_episode["episode_id"], new_episode["episode_id"]],
        day_numbers=[2, 20],
    )
    alert = _alert("603969.SH", old_episode["episode_id"])
    alert.update(
        episode_ids=[old_episode["episode_id"], new_episode["episode_id"]],
        day_numbers=[2, 20],
        episode_reviews=[
            _episode_review(
                old_episode["episode_id"],
                final=_final_review(),
            ),
            _episode_review(new_episode["episode_id"]),
        ],
    )
    snapshot_path = tmp_path / "snapshot.json"
    pending_path = tmp_path / "pending.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    pending_path.write_text(
        json.dumps(_report_payload(snapshot, alerts=[alert]), ensure_ascii=False),
        encoding="utf-8",
    )

    summary = record_forward_monitor(
        snapshot_file=snapshot_path,
        report_file=pending_path,
        project_root=tmp_path,
    )

    saved = json.loads(Path(summary.json_file).read_text(encoding="utf-8"))
    markdown = Path(summary.markdown_file).read_text(encoding="utf-8")
    reviews = {item["episode_id"]: item for item in saved["alerts"][0]["episode_reviews"]}
    assert reviews[old_episode["episode_id"]]["final_twenty_day_review"] == _final_review()
    assert reviews[new_episode["episode_id"]]["final_twenty_day_review"] is None
    assert markdown.count("### 银龙股份（603969.SH）") == 1
    assert "2026年8月3日那次推荐" in markdown
    assert markdown.count("前20个交易日结束后，原判断和具体股票都基本合理。") == 1
    for heading in (
        "当初为什么推荐",
        "推荐后怎么走",
        "最近发生了什么，为什么今天提到它",
        "现在怎么看",
        "接下来关注什么",
    ):
        assert markdown.count(heading) == 1
    assert "今天这只股票发生了什么" not in markdown
    assert "市场方面" not in markdown


def test_final_review_is_rejected_before_twentieth_day(tmp_path: Path) -> None:
    snapshot = _review_snapshot(day_number=19)
    episode_id = snapshot["episodes"][0]["episode_id"]
    snapshot_path, pending_path = _record_review_payload(
        tmp_path,
        snapshot,
        _episode_review(episode_id, final=_final_review()),
    )

    with pytest.raises(ValueError, match="before the twentieth"):
        record_forward_monitor(
            snapshot_file=snapshot_path,
            report_file=pending_path,
            project_root=tmp_path,
        )


def test_final_review_is_required_on_twentieth_day(tmp_path: Path) -> None:
    snapshot = _review_snapshot(day_number=20)
    episode_id = snapshot["episodes"][0]["episode_id"]
    snapshot_path, pending_path = _record_review_payload(
        tmp_path,
        snapshot,
        _episode_review(episode_id),
    )

    with pytest.raises(ValueError, match="at or after the twentieth"):
        record_forward_monitor(
            snapshot_file=snapshot_path,
            report_file=pending_path,
            project_root=tmp_path,
        )


def test_public_markdown_does_not_use_internal_attention_to_fill_content(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot_with_complete_pair()
    selected, comparator = snapshot["episodes"]
    selected["day_number"] = 20
    selected["pair_context"]["paired_day_number"] = 20
    comparator["day_number"] = 20
    comparator["pair_context"] = {
        "pair_status": "complete",
        "paired_episode_id": selected["episode_id"],
        "paired_name": selected["name"],
        "paired_day_number": 20,
        "selected_or_subject_return_since_entry": 0.03,
        "alternative_return_since_entry": 0.08,
        "return_difference": -0.05,
        "subject_mae_since_entry": -0.07,
        "alternative_mae_since_entry": -0.04,
        "subject_max_close_drawdown": -0.09,
        "alternative_max_close_drawdown": -0.06,
    }
    snapshot["attention_stocks"] = [
        {
            "ts_code": comparator["ts_code"],
            "name": comparator["name"],
            "episode_ids": [comparator["episode_id"]],
            "roles": ["comparator"],
            "day_numbers": [20],
            "original_engine_types": ["independent_demand_acceleration"],
            "attention_reasons": ["checkpoint"],
        }
    ]
    alert = _alert(comparator["ts_code"], comparator["episode_id"])
    alert.update(
        name=comparator["name"],
        roles=["comparator"],
        day_numbers=[20],
        episode_reviews=[_episode_review(comparator["episode_id"])],
    )
    snapshot_path = tmp_path / "snapshot.json"
    pending_path = tmp_path / "pending.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    pending_path.write_text(
        json.dumps(_report_payload(snapshot, alerts=[alert]), ensure_ascii=False),
        encoding="utf-8",
    )

    summary = record_forward_monitor(
        snapshot_file=snapshot_path,
        report_file=pending_path,
        project_root=tmp_path,
    )

    saved = json.loads(Path(summary.json_file).read_text(encoding="utf-8"))
    markdown = Path(summary.markdown_file).read_text(encoding="utf-8")
    assert saved["alerts"][0]["roles"] == ["comparator"]
    assert saved["alerts"][0]["episode_reviews"][0][
        "final_twenty_day_review"
    ] is None
    assert "尚太科技" not in markdown
    assert "用于比较的股票" not in markdown
    assert "和当时最接近的备选相比" not in markdown
    assert "今天没有被明确推荐过" in markdown


@pytest.mark.parametrize("day_number", [21, 25, 30])
def test_frozen_twenty_day_review_cannot_be_changed_later(
    tmp_path: Path,
    day_number: int,
) -> None:
    frozen = _final_review()
    snapshot = _review_snapshot(
        day_number=day_number,
        frozen_review=frozen,
    )
    episode_id = snapshot["episodes"][0]["episode_id"]
    changed = _final_review("logic_right_timing_wrong")
    snapshot_path, pending_path = _record_review_payload(
        tmp_path,
        snapshot,
        _episode_review(episode_id, final=changed),
    )

    with pytest.raises(ValueError, match="frozen"):
        record_forward_monitor(
            snapshot_file=snapshot_path,
            report_file=pending_path,
            project_root=tmp_path,
        )


def test_later_current_review_may_change_while_final_review_stays_frozen(
    tmp_path: Path,
) -> None:
    frozen = _final_review()
    snapshot = _review_snapshot(day_number=25, frozen_review=frozen)
    snapshot["episodes"][0]["current_close_return_since_entry"] = 0.50
    episode_id = snapshot["episodes"][0]["episode_id"]
    review = _episode_review(episode_id, final=frozen)
    review.update(
        current_assessment="weakening",
        current_weak_or_failed_link="price_and_volume_confirmation",
        current_review="第21个交易日后的走势已经转弱。",
    )
    snapshot_path, pending_path = _record_review_payload(
        tmp_path,
        snapshot,
        review,
    )

    summary = record_forward_monitor(
        snapshot_file=snapshot_path,
        report_file=pending_path,
        project_root=tmp_path,
    )

    saved = json.loads(Path(summary.json_file).read_text(encoding="utf-8"))
    markdown = Path(summary.markdown_file).read_text(encoding="utf-8")
    saved_review = saved["alerts"][0]["episode_reviews"][0]
    assert saved_review["current_assessment"] == "weakening"
    assert saved_review["final_twenty_day_review"] == frozen
    assert "目前涨跌为+50.00%" in markdown
    assert "第21个交易日后的走势已经转弱" in markdown
    assert "前20个交易日结束后，原判断和具体股票都基本合理" in markdown
    assert "前20天最终判断中，最薄弱的是" not in markdown
    assert "股价和成交没有继续支持原判断" not in markdown


def test_register_keeps_only_referenced_decisions_and_pair_episode_id(
    tmp_path: Path,
) -> None:
    trace = _trace()
    trace["candidate_ledger"][0]["research_thesis"][
        "action_condition_decision_id"
    ] = "action-603969.SH"
    trace["decision_trace"].append(
        {
            "decision_id": "action-603969.SH",
            "ts_code": "603969.SH",
            "evidence_type": "price",
            "conclusion": "第一个交易日只在原条件仍可用时继续观察",
        }
    )
    trace_file = tmp_path / "trace.json"
    _write_trace(trace_file, trace)

    register_episodes(
        trace_file=trace_file,
        label="replay",
        project_root=tmp_path,
    )

    registry = json.loads(
        (tmp_path / "local_archive/forward_monitor/registered-episodes.json").read_text(
            encoding="utf-8"
        )
    )
    selected = next(item for item in registry["episodes"] if item["role"] == "selected")
    assert [item["decision_id"] for item in selected["original_referenced_decisions"]] == [
        "co-603969.SH",
        "px-603969.SH",
        "action-603969.SH",
    ]
    assert all(
        item["decision_id"] != "unrelated-decision"
        for item in selected["original_referenced_decisions"]
    )
    assert selected["original_nearest_alternative_episode_id"] == (
        "replay:2026-08-20:001301.SZ:comparator"
    )


def test_prepare_builds_complete_pair_context_in_both_directions(
    tmp_path: Path,
) -> None:
    trace = _trace(formation_date="2026-07-31", action_date="2026-08-03")
    archive = tmp_path / "local_archive/forward_selection"
    archive.mkdir(parents=True)
    _write_trace(archive / "research-trace-2026-07-31.json", trace)
    sessions = _seed_monitor_project(tmp_path, trace=trace, session_count=3)

    snapshot = _prepare(tmp_path, sessions[-1])

    episodes = {item["role"]: item for item in snapshot["episodes"]}
    selected_pair = episodes["selected"]["pair_context"]
    comparator_pair = episodes["comparator"]["pair_context"]
    assert selected_pair["pair_status"] == "complete"
    assert selected_pair["paired_episode_id"] == episodes["comparator"]["episode_id"]
    assert selected_pair["return_difference"] == pytest.approx(0.0)
    assert comparator_pair["pair_status"] == "complete"
    assert comparator_pair["paired_episode_id"] == episodes["selected"]["episode_id"]


def test_pair_context_is_incomplete_when_one_price_path_is_incomplete(
    tmp_path: Path,
) -> None:
    trace = _trace(formation_date="2026-07-31", action_date="2026-08-03")
    archive = tmp_path / "local_archive/forward_selection"
    archive.mkdir(parents=True)
    _write_trace(archive / "research-trace-2026-07-31.json", trace)
    sessions = _seed_monitor_project(tmp_path, trace=trace, session_count=3)
    for dataset in ("equity_daily", "adj_factor"):
        path = tmp_path / f"local_warehouse/facts/{dataset}/trade_date={sessions[1]}/data.parquet"
        frame = pd.read_parquet(path)
        frame = frame.loc[~frame["ts_code"].astype(str).eq("001301.SZ")]
        frame.to_parquet(path, index=False)

    snapshot = _prepare(tmp_path, sessions[-1])

    assert {
        item["pair_context"]["pair_status"] for item in snapshot["episodes"]
    } == {"incomplete"}


def _snapshot_with_complete_pair(*, paired_day_number: int = 3) -> dict:
    snapshot = _review_snapshot(day_number=3)
    subject = snapshot["episodes"][0]
    subject["analysis_date"] = snapshot["analysis_date"]
    paired = {
        **subject,
        "episode_id": "formal:2026-07-31:001301.SZ:comparator",
        "ts_code": "001301.SZ",
        "name": "尚太科技",
        "role": "comparator",
        "day_number": paired_day_number,
        "pair_context": {"pair_status": "unavailable"},
    }
    subject["pair_context"] = {
        "pair_status": "complete",
        "paired_episode_id": paired["episode_id"],
        "paired_name": paired["name"],
        "paired_day_number": paired_day_number,
        "selected_or_subject_return_since_entry": 0.08,
        "alternative_return_since_entry": 0.03,
        "return_difference": 0.05,
        "subject_mae_since_entry": -0.04,
        "alternative_mae_since_entry": -0.07,
        "subject_max_close_drawdown": -0.06,
        "alternative_max_close_drawdown": -0.09,
    }
    snapshot["episodes"].append(paired)
    snapshot["summary"].update(
        open_episode_count=2,
        distinct_stock_count=2,
        comparator_count=1,
        primary_count=2,
    )
    return snapshot


def test_record_rejects_complete_pair_with_different_observation_windows(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot_with_complete_pair(paired_day_number=2)
    episode_id = snapshot["episodes"][0]["episode_id"]
    snapshot_path, pending_path = _record_review_payload(
        tmp_path,
        snapshot,
        _episode_review(episode_id),
    )

    with pytest.raises(ValueError, match="window mismatch"):
        record_forward_monitor(
            snapshot_file=snapshot_path,
            report_file=pending_path,
            project_root=tmp_path,
        )


def test_markdown_hides_comparison_text_about_a_different_stock(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot_with_complete_pair()
    subject = snapshot["episodes"][0]
    other = {
        **snapshot["episodes"][1],
        "episode_id": "formal:2026-07-31:002852.SZ:comparator",
        "ts_code": "002852.SZ",
        "name": "道道全",
    }
    snapshot["episodes"].append(other)
    snapshot["summary"].update(
        open_episode_count=3,
        distinct_stock_count=3,
        comparator_count=2,
        primary_count=3,
    )
    review = _episode_review(subject["episode_id"])
    review["comparison_interpretation"] = (
        "尚太科技和道道全相比，实际表现更强的是道道全。"
    )
    snapshot_path, pending_path = _record_review_payload(
        tmp_path,
        snapshot,
        review,
    )

    summary = record_forward_monitor(
        snapshot_file=snapshot_path,
        report_file=pending_path,
        project_root=tmp_path,
    )
    markdown = Path(summary.markdown_file).read_text(encoding="utf-8")

    assert "银龙股份" in markdown
    assert "尚太科技" not in markdown
    assert "道道全" not in markdown
    assert "和当时最接近的备选相比" not in markdown
    assert "当时备选股" not in markdown


@pytest.mark.parametrize(
    ("day_number", "window"),
    [(1, 1), (3, 3), (5, 5), (10, 5), (20, 20), (21, 20)],
)
def test_markdown_uses_deterministic_relative_window(
    tmp_path: Path,
    day_number: int,
    window: int,
) -> None:
    frozen = _final_review() if day_number > 20 else None
    snapshot = _review_snapshot(
        day_number=day_number,
        frozen_review=frozen,
    )
    episode_id = snapshot["episodes"][0]["episode_id"]
    final = _final_review() if day_number >= 20 else None
    snapshot_path, pending_path = _record_review_payload(
        tmp_path,
        snapshot,
        _episode_review(episode_id, final=final),
    )

    summary = record_forward_monitor(
        snapshot_file=snapshot_path,
        report_file=pending_path,
        project_root=tmp_path,
    )
    markdown = Path(summary.markdown_file).read_text(encoding="utf-8")

    assert f"最近{window}个交易日" in markdown
    if day_number == 10:
        assert "从推荐以来" not in markdown


def test_markdown_keeps_raw_jargon_only_in_snapshot_json(tmp_path: Path) -> None:
    jargon = "事件发动机进入条件性通道，行动日等待D1首次定价，量价共振后进入主升路径。"
    snapshot = _review_snapshot(day_number=1)
    snapshot["episodes"][0].update(
        original_primary_reason=jargon,
        original_selection_reason=jargon,
        original_strongest_counterevidence="D20后风险",
        original_referenced_decisions=[
            {"decision_id": "px", "formation_values": {"raw": jargon}}
        ],
    )
    episode_id = snapshot["episodes"][0]["episode_id"]
    review = _episode_review(episode_id)
    review.update(
        original_reason_plain_language="当时看好它是因为公司出现了新变化，但股价还需要后续验证。",
        original_key_risk_plain_language="当时最担心的是股价没有继续走强。",
    )
    snapshot_path, pending_path = _record_review_payload(
        tmp_path,
        snapshot,
        review,
    )

    summary = record_forward_monitor(
        snapshot_file=snapshot_path,
        report_file=pending_path,
        project_root=tmp_path,
    )
    markdown = Path(summary.markdown_file).read_text(encoding="utf-8")
    persisted_snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))

    assert persisted_snapshot["episodes"][0]["original_primary_reason"] == jargon
    assert "当时看好它是因为公司出现了新变化" in markdown
    for forbidden in (
        "发动机", "行动日", "D1", "D20", "首次定价",
        "条件性通道", "量价共振", "主升",
    ):
        assert forbidden not in markdown


@pytest.mark.parametrize(
    "comparison",
    ["相比 001301.SZ，原股票走势更连续。", "相比尚太科技，原股票走势更连续。"],
)
def test_pair_matching_accepts_unique_full_code_or_name(
    tmp_path: Path,
    comparison: str,
) -> None:
    trace = _trace()
    trace["research_result"]["selected_stocks"][0]["nearest_comparison"] = comparison
    trace_file = tmp_path / "trace.json"
    _write_trace(trace_file, trace)

    register_episodes(
        trace_file=trace_file,
        label="replay",
        project_root=tmp_path,
    )

    registry = json.loads(
        (tmp_path / "local_archive/forward_monitor/registered-episodes.json").read_text(
            encoding="utf-8"
        )
    )
    selected = next(item for item in registry["episodes"] if item["role"] == "selected")
    assert selected["original_nearest_alternative_episode_id"] == (
        "replay:2026-08-20:001301.SZ:comparator"
    )


@pytest.mark.parametrize(
    "comparison",
    ["相比尚太，原股票更强。", "尚太科技和道道全都很接近。"],
)
def test_pair_matching_stays_unknown_for_partial_or_ambiguous_names(
    tmp_path: Path,
    comparison: str,
) -> None:
    trace = _trace()
    trace["candidate_ledger"].append(
        {
            **trace["candidate_ledger"][1],
            "ts_code": "002852.SZ",
            "name": "道道全",
        }
    )
    trace["research_result"]["nearest_nonselections"].append(
        {
            **trace["research_result"]["nearest_nonselections"][0],
            "ts_code": "002852.SZ",
            "name": "道道全",
        }
    )
    trace["research_result"]["selected_stocks"][0]["nearest_comparison"] = comparison
    trace_file = tmp_path / "trace.json"
    _write_trace(trace_file, trace)

    register_episodes(
        trace_file=trace_file,
        label="replay",
        project_root=tmp_path,
    )

    registry = json.loads(
        (tmp_path / "local_archive/forward_monitor/registered-episodes.json").read_text(
            encoding="utf-8"
        )
    )
    selected = next(item for item in registry["episodes"] if item["role"] == "selected")
    assert selected["original_nearest_alternative_episode_id"] is None


def test_missing_referenced_decision_is_kept_as_data_limitation(
    tmp_path: Path,
) -> None:
    trace = _single_selected_trace(
        formation_date="2026-07-31",
        action_date="2026-08-03",
    )
    trace["decision_trace"] = [
        item
        for item in trace["decision_trace"]
        if item["decision_id"] != "px-603969.SH"
    ]
    archive = tmp_path / "local_archive/forward_selection"
    archive.mkdir(parents=True)
    _write_trace(archive / "research-trace-2026-07-31.json", trace)
    sessions = _seed_monitor_project(tmp_path, trace=trace, session_count=1)

    episode = _prepare(tmp_path, sessions[0])["episodes"][0]

    assert "missing_original_referenced_decisions" in episode["data_limitations"]
    assert [item["decision_id"] for item in episode["original_referenced_decisions"]] == [
        "co-603969.SH"
    ]


def test_repeated_register_fills_pair_and_referenced_decisions_without_overwrite(
    tmp_path: Path,
) -> None:
    trace = _trace()
    trace_file = tmp_path / "trace.json"
    _write_trace(trace_file, trace)
    register_episodes(trace_file=trace_file, label="replay", project_root=tmp_path)
    registry_path = tmp_path / "local_archive/forward_monitor/registered-episodes.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    selected = next(item for item in registry["episodes"] if item["role"] == "selected")
    selected.pop("original_nearest_alternative_episode_id")
    selected.pop("original_referenced_decisions")
    selected["original_selection_reason"] = "已经冻结的原选择理由"
    registry_path.write_text(json.dumps(registry, ensure_ascii=False), encoding="utf-8")

    register_episodes(trace_file=trace_file, label="replay", project_root=tmp_path)

    refreshed = json.loads(registry_path.read_text(encoding="utf-8"))
    selected = next(item for item in refreshed["episodes"] if item["role"] == "selected")
    assert selected["original_nearest_alternative_episode_id"].endswith(
        ":001301.SZ:comparator"
    )
    assert len(selected["original_referenced_decisions"]) == 2
    assert selected["original_selection_reason"] == "已经冻结的原选择理由"


def test_prepare_restores_earliest_frozen_twenty_day_review(
    tmp_path: Path,
) -> None:
    trace = _single_selected_trace(
        formation_date="2026-07-01",
        action_date="2026-07-02",
    )
    archive = tmp_path / "local_archive/forward_selection"
    archive.mkdir(parents=True)
    _write_trace(archive / "research-trace-2026-07-01.json", trace)
    sessions = _seed_monitor_project(tmp_path, trace=trace, session_count=21)
    episode_id = "formal:2026-07-01:603969.SH:selected"
    monitor_dir = tmp_path / "local_archive/forward_monitor"
    monitor_dir.mkdir(parents=True)
    (monitor_dir / f"monitor-report-{sessions[19]}.json").write_text(
        json.dumps(
            {
                "report_version": "daily-forward-monitor-report-v2",
                "analysis_date": sessions[19].isoformat(),
                "alerts": [
                    {
                        "episode_reviews": [
                            {
                                "episode_id": episode_id,
                                "final_twenty_day_review": _final_review(),
                            }
                        ]
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    episode = _prepare(tmp_path, sessions[20])["episodes"][0]

    assert episode["frozen_twenty_day_review"] == _final_review()


def test_markdown_explicitly_says_industry_comparison_is_unknown(
    tmp_path: Path,
) -> None:
    snapshot = _review_snapshot(day_number=10)
    snapshot["episodes"][0]["relative_industry_5d"] = None
    episode_id = snapshot["episodes"][0]["episode_id"]
    snapshot_path, pending_path = _record_review_payload(
        tmp_path,
        snapshot,
        _episode_review(episode_id),
    )

    summary = record_forward_monitor(
        snapshot_file=snapshot_path,
        report_file=pending_path,
        project_root=tmp_path,
    )
    markdown = Path(summary.markdown_file).read_text(encoding="utf-8")

    assert "最近5个交易日" in markdown
    assert "同一行业的对照数据不足" in markdown


def test_pending_final_review_persists_until_a_selected_episode_is_saved(
    tmp_path: Path,
) -> None:
    trace = _single_selected_trace(
        formation_date="2026-07-01",
        action_date="2026-07-02",
    )
    archive = tmp_path / "local_archive/forward_selection"
    archive.mkdir(parents=True)
    _write_trace(archive / "research-trace-2026-07-01.json", trace)
    sessions = _seed_monitor_project(tmp_path, trace=trace, session_count=22)

    d20 = _prepare(tmp_path, sessions[19])
    episode_id = d20["episodes"][0]["episode_id"]
    assert d20["episodes"][0]["attention_reasons"][0] == "pending_final_review"
    assert d20["required_final_review_episode_ids"] == [episode_id]

    d21 = _prepare(tmp_path, sessions[20])
    assert d21["episodes"][0]["attention_reasons"][0] == "pending_final_review"
    assert d21["required_final_review_episode_ids"] == [episode_id]

    snapshot_path, pending_path = _record_review_payload(
        tmp_path,
        d21,
        _episode_review(episode_id, final=_final_review()),
    )
    record_forward_monitor(
        snapshot_file=snapshot_path,
        report_file=pending_path,
        project_root=tmp_path,
    )

    d22 = _prepare(tmp_path, sessions[21])
    assert d22["episodes"][0]["frozen_twenty_day_review"] == _final_review()
    assert "pending_final_review" not in d22["episodes"][0]["attention_reasons"]
    assert d22["required_final_review_episode_ids"] == []


def test_record_requires_every_pending_final_review_episode_within_eight_stocks(
    tmp_path: Path,
) -> None:
    base = _review_snapshot(day_number=20)
    episodes: list[dict] = []
    attention: list[dict] = []
    required: list[str] = []
    for index in range(9):
        code = f"00000{index}.SZ"
        role = "selected" if index < 5 else "comparator"
        episode = {
            **base["episodes"][0],
            "episode_id": f"episode-{index}",
            "ts_code": code,
            "name": f"股票{index}",
            "role": role,
            "day_number": 20 if role == "selected" else 3,
            "frozen_twenty_day_review": None,
        }
        episodes.append(episode)
        attention.append(
            {
                "ts_code": code,
                "name": episode["name"],
                "episode_ids": [episode["episode_id"]],
                "roles": [role],
                "day_numbers": [episode["day_number"]],
                "original_engine_types": ["independent_demand_acceleration"],
                "attention_reasons": [
                    "pending_final_review" if role == "selected" else "checkpoint"
                ],
            }
        )
        if role == "selected":
            required.append(episode["episode_id"])
    snapshot = {
        **base,
        "episodes": episodes,
        "attention_stocks": attention,
        "required_final_review_episode_ids": required,
        "summary": {
            **base["summary"],
            "open_episode_count": 9,
            "distinct_stock_count": 9,
            "selected_count": 5,
            "comparator_count": 4,
            "primary_count": 9,
            "attention_stock_count": 9,
        },
    }
    alerts = []
    for episode in episodes[:8]:
        alert = _alert(episode["ts_code"], episode["episode_id"])
        alert.update(
            name=episode["name"],
            roles=[episode["role"]],
            day_numbers=[episode["day_number"]],
            episode_reviews=[
                _episode_review(
                    episode["episode_id"],
                    final=_final_review() if episode["role"] == "selected" else None,
                )
            ],
        )
        alerts.append(alert)
    snapshot_path = tmp_path / "snapshot.json"
    pending_path = tmp_path / "pending.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    pending_path.write_text(
        json.dumps(_report_payload(snapshot, alerts=alerts, unreported=1)),
        encoding="utf-8",
    )

    summary = record_forward_monitor(
        snapshot_file=snapshot_path,
        report_file=pending_path,
        project_root=tmp_path,
    )
    assert summary.alert_count == 8
    assert summary.unreported_attention_count == 1

    omitted = alerts[1:]
    omitted_alert = _alert(episodes[8]["ts_code"], episodes[8]["episode_id"])
    omitted_alert.update(
        name=episodes[8]["name"],
        roles=["comparator"],
        day_numbers=[3],
    )
    omitted.append(omitted_alert)
    second_pending = tmp_path / "pending-omitted.json"
    second_pending.write_text(
        json.dumps(_report_payload(snapshot, alerts=omitted, unreported=1)),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="required final review"):
        record_forward_monitor(
            snapshot_file=snapshot_path,
            report_file=second_pending,
            project_root=tmp_path,
        )


@pytest.mark.parametrize(
    ("difference", "expected"),
    [
        (0.032, "这条记录比尚太科技强3.20个百分点。"),
        (-0.032, "这条记录比尚太科技弱3.20个百分点。"),
        (0.0, "两只股票表现接近，相差0.00个百分点。"),
    ],
)
def test_pair_difference_stays_internal_and_is_hidden_from_public_markdown(
    tmp_path: Path,
    difference: float,
    expected: str,
) -> None:
    snapshot = _snapshot_with_complete_pair()
    snapshot["episodes"][0]["pair_context"]["return_difference"] = difference
    episode_id = snapshot["episodes"][0]["episode_id"]
    review = _episode_review(episode_id)
    review["comparison_interpretation"] = expected
    snapshot_path, pending_path = _record_review_payload(
        tmp_path,
        snapshot,
        review,
    )

    summary = record_forward_monitor(
        snapshot_file=snapshot_path,
        report_file=pending_path,
        project_root=tmp_path,
    )
    saved = json.loads(Path(summary.json_file).read_text(encoding="utf-8"))
    markdown = Path(summary.markdown_file).read_text(encoding="utf-8")

    assert saved["alerts"][0]["episode_reviews"][0][
        "comparison_interpretation"
    ] == expected
    assert expected not in markdown
    assert "尚太科技" not in markdown


def test_direction_right_stock_wrong_requires_a_complete_pair(
    tmp_path: Path,
) -> None:
    snapshot = _review_snapshot(day_number=20)
    episode_id = snapshot["episodes"][0]["episode_id"]
    snapshot_path, pending_path = _record_review_payload(
        tmp_path,
        snapshot,
        _episode_review(
            episode_id,
            final=_final_review("direction_right_stock_wrong"),
        ),
    )

    with pytest.raises(ValueError, match="complete pair"):
        record_forward_monitor(
            snapshot_file=snapshot_path,
            report_file=pending_path,
            project_root=tmp_path,
        )
