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
        "research_result": {
            "selected_stocks": [
                {
                    "ts_code": selected_code,
                    "name": "银龙股份",
                    "priority": 1,
                    "opportunity_type": "independent_price_anomaly",
                    "strongest_counterevidence": "持续性仍待观察",
                    "nearest_comparison": "比对照股票启动更早",
                }
            ],
            "nearest_nonselections": [
                {
                    "ts_code": comparator_code,
                    "name": "尚太科技",
                    "opportunity_type": "independent_price_anomaly",
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
        assert episode[f"{prefix}_first_close_hit_20pct_date"] == sessions[1].isoformat()
        assert episode[f"{prefix}_first_high_hit_20pct_date"] == sessions[0].isoformat()
    assert episode["d20_hit_20pct_close_within_20d"] is True
    assert episode["current_hit_20pct_close"] is True


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


def _report_payload(snapshot: dict, *, alerts: list[dict] | None = None, unreported: int = 0) -> dict:
    return {
        "report_version": "daily-forward-monitor-report-v1",
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


def _alert(ts_code: str, episode_id: str) -> dict:
    return {
        "ts_code": ts_code,
        "name": "银龙股份",
        "episode_ids": [episode_id],
        "role": "selected",
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
    }


def test_report_model_rejects_more_than_eight_or_duplicate_stocks() -> None:
    snapshot = {"analysis_date": "2026-08-03", "as_of": "2026-08-03T18:00:00+08:00", "summary": {"open_episode_count": 9, "distinct_stock_count": 9, "attention_stock_count": 9, "selected_count": 9, "comparator_count": 0, "primary_count": 9, "passive_tail_count": 0, "closed_count": 0}}
    nine = [_alert(f"00000{i}.SZ", f"e{i}") for i in range(9)]
    with pytest.raises(ValidationError):
        DailyForwardMonitorReportV1.model_validate(_report_payload(snapshot, alerts=nine))
    duplicate = [_alert("000001.SZ", "e1"), _alert("000001.SZ", "e2")]
    with pytest.raises(ValidationError):
        DailyForwardMonitorReportV1.model_validate(_report_payload(snapshot, alerts=duplicate))


def test_report_accepts_eight_alerts_and_counts_the_rest() -> None:
    snapshot = {"analysis_date": "2026-08-03", "as_of": "2026-08-03T18:00:00+08:00", "summary": {"open_episode_count": 9, "distinct_stock_count": 9, "attention_stock_count": 9, "selected_count": 9, "comparator_count": 0, "primary_count": 9, "passive_tail_count": 0, "closed_count": 0}}
    alerts = [_alert(f"00000{i}.SZ", f"e{i}") for i in range(8)]

    report = DailyForwardMonitorReportV1.model_validate(
        _report_payload(snapshot, alerts=alerts, unreported=1)
    )

    assert len(report.alerts) == 8
    assert report.unreported_attention_count == 1


@pytest.mark.parametrize(
    "mismatch",
    [
        "pool_summary",
        "name",
        "role",
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
    elif mismatch == "role":
        payload["alerts"][0]["role"] = "comparator"
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

    DailyForwardMonitorReportV1.model_validate(payload)


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


def test_markdown_uses_plain_chinese_and_includes_all_alert_context(tmp_path: Path) -> None:
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
            "alert_type": "late_activation",
            "monitor_state": "strengthening",
            "market_change": "测试中的大盘变化",
            "sector_change": "测试中的板块变化",
            "stock_change": "测试中的个股变化",
            "company_change": "测试中的公司变化",
            "outlook_1_3d": "continuation_possible",
            "confirmation_condition": "测试确认条件",
            "invalidation_condition": "测试失效条件",
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

    assert "当前：D1" in markdown
    assert "原角色：入选" in markdown
    assert "最初入选依据：个股独立需求加速" in markdown
    assert "原始主要理由：银龙股份的原始判断依据" in markdown
    assert "当前状态：正在转强" in markdown
    assert "大盘：测试中的大盘变化" in markdown
    assert "板块：测试中的板块变化" in markdown
    assert "个股：测试中的个股变化" in markdown
    assert "公司：测试中的公司变化" in markdown
    assert "未来1—3个交易日基础情形：仍有延续可能" in markdown
    assert "确认条件：测试确认条件" in markdown
    assert "失效条件：测试失效条件" in markdown
    assert "提醒原因：测试提醒原因" in markdown
    assert "迟到启动，不改变原20个交易日结果" in markdown
    assert "independent_demand_acceleration" not in markdown
    assert "continuation_possible" not in markdown
    assert "strengthening" not in markdown


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
    assert "今日市场" in markdown
    assert "重点提醒" in markdown
    assert "全部跟踪记录" not in markdown
    assert "震荡或继续等待" in markdown
    assert "range_or_wait" not in markdown
