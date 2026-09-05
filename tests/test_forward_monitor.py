from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from pydantic import ValidationError

from stock_analyzer.ops.forward_monitor import (
    DAILY_FORMAL_REVIEWS_VERSION,
    DailyFormalReviewLedgerV1,
    DailyFormalReviewV1,
    DailyForwardMonitorReportV1,
    DailyForwardMonitorReportV2,
    ForwardEpisodeReviewV1,
    ForwardMonitorAlertV2,
    _attention_reasons,
    _human_trading_day,
    _parse_args,
    _render_markdown,
    _render_public_outlook,
    _render_target_progress,
    prepare_forward_monitor,
    record_daily_formal_reviews,
    record_forward_monitor,
    register_episodes,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_causal_review_keeps_existing_report_model_fields() -> None:
    assert set(ForwardEpisodeReviewV1.model_fields) == {
        "episode_id",
        "original_reason_plain_language",
        "original_key_risk_plain_language",
        "current_assessment",
        "best_supported_explanation",
        "current_weak_or_failed_link",
        "current_review",
        "comparison_interpretation",
        "final_twenty_day_review",
    }
    assert set(ForwardMonitorAlertV2.model_fields) == {
        "ts_code",
        "name",
        "episode_ids",
        "roles",
        "day_numbers",
        "original_engine_types",
        "alert_type",
        "monitor_state",
        "market_change",
        "sector_change",
        "stock_change",
        "company_change",
        "outlook_1_3d",
        "confirmation_condition",
        "invalidation_condition",
        "why_reported",
        "outlook_reason_plain_language",
        "episode_reviews",
    }
    assert set(DailyForwardMonitorReportV2.model_fields) == {
        "report_version",
        "analysis_date",
        "as_of",
        "market_overview",
        "pool_summary",
        "alerts",
        "unreported_attention_count",
        "routine_summary",
    }


def _target_progress_episode(**overrides: object) -> dict:
    episode = {
        "action_date": "2026-08-25",
        "day_number": 6,
        "current_close_return_since_entry": 0.0268,
        "current_max_close_return_since_entry": 0.0466,
        "current_max_high_return_since_entry": 0.05,
        "current_mae_since_entry": -0.0163,
        "current_close_drawdown_from_peak": -0.019,
        "current_first_close_hit_20pct_date": None,
        "current_first_high_hit_20pct_date": None,
    }
    episode.update(overrides)
    return episode


def test_target_progress_uses_real_return_not_linear_daily_progress() -> None:
    text = _render_target_progress(_target_progress_episode())

    assert "2026年8月25日开盘前被正式推荐" in text
    assert "入选后第6个交易日" in text
    assert "离20%的观察目标还差17.32个百分点" in text
    assert "期间最高上涨4.66%" in text
    assert "最深下跌1.63%" in text


def test_target_progress_distinguishes_intraday_touch_from_close_hit() -> None:
    intraday = _render_target_progress(
        _target_progress_episode(
            current_close_return_since_entry=0.15,
            current_max_close_return_since_entry=0.18,
            current_max_high_return_since_entry=0.22,
            current_first_high_hit_20pct_date="2026-08-28",
        )
    )
    close = _render_target_progress(
        _target_progress_episode(
            current_close_return_since_entry=0.21,
            current_max_close_return_since_entry=0.23,
            current_max_high_return_since_entry=0.25,
            current_first_close_hit_20pct_date="2026-08-29",
            current_first_high_hit_20pct_date="2026-08-28",
        )
    )

    assert "盘中曾达到20%" in intraday
    assert "收盘没有保持" in intraday
    assert "收盘已经达到20%的观察目标" in close
    assert "继续记录到第20个交易日" in close


def test_target_progress_says_when_entry_reference_is_unavailable() -> None:
    text = _render_target_progress(
        _target_progress_episode(
            current_close_return_since_entry=None,
            current_max_close_return_since_entry=None,
            current_max_high_return_since_entry=None,
            current_mae_since_entry=None,
        )
    )

    assert "没有可靠的推荐参考价" in text
    assert "不能计算距离20%目标的进展" in text


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
        "return_1d": 0.011,
        "return_3d": 0.022,
        "return_5d": 0.033,
        "up_days_5d": 4.0,
        "relative_continuity_5d": 0.8,
        "largest_positive_day_contribution_5d": 0.4,
        "sessions_since_largest_positive_day_5d": 2.0,
        "return_ex_largest_positive_day_5d": 0.012,
        "return_after_largest_positive_day_5d": 0.008,
        "relative_market_after_largest_positive_day_5d": 0.006,
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
    saved = json.loads(Path(summary.json_file).read_text(encoding="utf-8"))
    markdown = Path(summary.markdown_file).read_text(encoding="utf-8")

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
    assert episode["return_1d"] == pytest.approx(0.011)
    assert episode["return_3d"] == pytest.approx(0.022)
    assert episode["return_5d"] == pytest.approx(0.033)
    assert episode["up_days_5d"] == pytest.approx(4.0)
    assert episode["relative_continuity_5d"] == pytest.approx(0.8)
    assert episode["largest_positive_day_contribution_5d"] == pytest.approx(0.4)
    assert episode["sessions_since_largest_positive_day_5d"] == pytest.approx(2.0)
    assert episode["return_ex_largest_positive_day_5d"] == pytest.approx(0.012)
    assert episode["return_after_largest_positive_day_5d"] == pytest.approx(0.008)
    assert episode["relative_market_after_largest_positive_day_5d"] == pytest.approx(0.006)
    assert episode["price_location_60d"] == pytest.approx(0.5)
    assert [item["announcement_id"] for item in episode["new_announcements"]] == ["A1"]
    assert "new_official_event" in episode["attention_reasons"]


def test_prepare_keeps_missing_causal_price_fields_as_none(tmp_path: Path) -> None:
    trace = _single_selected_trace(
        formation_date="2026-07-31",
        action_date="2026-08-03",
    )
    archive = tmp_path / "local_archive/forward_selection"
    archive.mkdir(parents=True)
    _write_trace(archive / "research-trace-2026-07-31.json", trace)
    fields = (
        "return_1d",
        "return_3d",
        "return_5d",
        "up_days_5d",
        "relative_continuity_5d",
        "largest_positive_day_contribution_5d",
        "sessions_since_largest_positive_day_5d",
        "return_ex_largest_positive_day_5d",
        "return_after_largest_positive_day_5d",
        "relative_market_after_largest_positive_day_5d",
        "price_location_60d",
    )
    sessions = _seed_monitor_project(
        tmp_path,
        trace=trace,
        session_count=1,
        price_context_overrides={field: None for field in fields},
    )

    episode = _prepare(tmp_path, sessions[0])["episodes"][0]

    assert {field: episode[field] for field in fields} == {
        field: None for field in fields
    }


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


def _non_executable_attention_episode(
    *,
    day_number: int,
    checkpoint: str | None,
    limitations: list[str] | None = None,
    entry_open: float | None = None,
    new_announcements: list[dict] | None = None,
) -> dict:
    return {
        "selection_output_class": "confirmed_active",
        "entry_open": entry_open,
        "day_number": day_number,
        "frozen_twenty_day_review": (
            {"overall_review": "已冻结"} if day_number > 20 else None
        ),
        "checkpoint": checkpoint,
        "new_announcements": new_announcements or [],
        "original_engine_type": "independent_demand_acceleration",
        "first_observable_date": None,
        "analysis_date": "2026-09-03",
        "d20_first_close_hit_20pct_date": None,
        "monitor_phase": "primary" if day_number <= 20 else "passive_tail",
        "relative_market_3d": None,
        "relative_market_5d": None,
        "relative_industry_3d": None,
        "relative_industry_5d": None,
        "amount_ratio_last_20d": None,
        "scenario_case_ids": [],
        "breakout_vs_prior60": None,
        "limit_up_return_contribution_5d": None,
        "data_limitations": limitations or [],
    }


def test_non_executable_formal_without_new_fact_has_no_attention_reason() -> None:
    current = _non_executable_attention_episode(
        day_number=2,
        checkpoint=None,
        limitations=["incomplete_price_path", "price_context_incomplete"],
    )
    previous = {
        **current,
        "analysis_date": "2026-09-02",
    }

    assert _attention_reasons(current, previous) == []


@pytest.mark.parametrize(
    ("day_number", "checkpoint"),
    [(3, "D3"), (5, "D5"), (10, "D10"), (25, "D25"), (30, "D30")],
)
def test_non_executable_formal_does_not_repeat_ordinary_checkpoint_or_data_problem(
    day_number: int,
    checkpoint: str,
) -> None:
    current = _non_executable_attention_episode(
        day_number=day_number,
        checkpoint=checkpoint,
        limitations=["incomplete_price_path", "price_context_incomplete"],
    )
    previous = {
        **current,
        "day_number": day_number - 1,
        "checkpoint": None,
        "analysis_date": "2026-09-02",
    }

    assert _attention_reasons(current, previous) == []


def test_non_executable_formal_reports_data_problem_once() -> None:
    current = _non_executable_attention_episode(
        day_number=1,
        checkpoint="D1",
        limitations=["incomplete_price_path", "price_context_incomplete"],
    )

    assert _attention_reasons(current, None) == ["data_problem"]


def test_non_executable_formal_still_requires_day_twenty_review() -> None:
    current = _non_executable_attention_episode(
        day_number=20,
        checkpoint="D20",
        limitations=["incomplete_price_path", "price_context_incomplete"],
    )
    previous = {
        **current,
        "day_number": 19,
        "checkpoint": None,
        "analysis_date": "2026-09-02",
    }

    assert _attention_reasons(current, previous) == ["pending_final_review"]


def test_non_executable_formal_keeps_new_event_as_optional_attention() -> None:
    current = _non_executable_attention_episode(
        day_number=3,
        checkpoint="D3",
        limitations=["incomplete_price_path", "price_context_incomplete"],
        new_announcements=[{"announcement_id": "A1"}],
    )
    previous = {
        **current,
        "day_number": 2,
        "checkpoint": None,
        "new_announcements": [],
        "analysis_date": "2026-09-02",
    }

    assert _attention_reasons(current, previous) == ["new_official_event"]


def test_first_observable_trading_change_returns_to_attention() -> None:
    previous = _non_executable_attention_episode(
        day_number=2,
        checkpoint=None,
        limitations=["incomplete_price_path", "price_context_incomplete"],
    )
    current = _non_executable_attention_episode(
        day_number=3,
        checkpoint="D3",
        limitations=["price_context_incomplete"],
        entry_open=10.0,
    )

    assert "data_problem" in _attention_reasons(current, previous)


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
        "confirmation_condition": "继续在原区间内波动，成交和收盘都没有形成明确方向。",
        "invalidation_condition": "连续突破区间上沿或下沿，并有多个收盘保持。",
        "why_reported": "固定检查日",
        "outlook_reason_plain_language": (
            "相对表现没有继续扩大，最近收盘也没有形成新的方向。"
        ),
        "episode_reviews": [_episode_review(episode_id)],
    }


def test_public_outlook_states_direction_reason_then_validation_conditions() -> None:
    payload = _alert("603969.SH", "episode-1")
    payload.update(
        outlook_1_3d="range_or_wait",
        outlook_reason_plain_language=(
            "当前仍保留大部分推荐后涨幅，但最近两日冲高回落增多。"
        ),
        confirmation_condition="回落时成交缩小，收盘仍守在近期高位。",
        invalidation_condition="成交明显增加并连续收低，或跌破主要涨幅区间。",
    )
    rendered = _render_public_outlook(ForwardMonitorAlertV2.model_validate(payload))

    direction = "未来1—3个交易日更可能横盘整理。"
    reason = "主要原因是：当前仍保留大部分推荐后涨幅，但最近两日冲高回落增多。"
    support = "会继续支持横盘判断的表现：回落时成交缩小，收盘仍守在近期高位。"
    change = "会让我改变当前判断的表现：成交明显增加并连续收低，或跌破主要涨幅区间。"
    assert rendered.index(direction) < rendered.index(reason)
    assert rendered.index(reason) < rendered.index(support)
    assert rendered.index(support) < rendered.index(change)
    assert "判断增强条件" not in rendered
    assert "判断改变条件" not in rendered
    assert "如果若" not in rendered
    assert "。。" not in rendered


@pytest.mark.parametrize(
    ("outlook", "direction"),
    [
        ("strengthening", "未来1—3个交易日更可能继续向上"),
        ("continuation_possible", "未来1—3个交易日更可能震荡偏上"),
        ("range_or_wait", "未来1—3个交易日更可能横盘整理"),
        ("weakening", "未来1—3个交易日更可能震荡偏下"),
        ("overheated", "未来1—3个交易日更可能高位震荡，短线偏下"),
        ("invalidated", "未来1—3个交易日更可能继续偏弱"),
        ("event_pending", "目前没有足够的可交易事实判断方向"),
    ],
)
def test_public_outlook_maps_each_internal_state_to_clear_direction(
    outlook: str,
    direction: str,
) -> None:
    payload = _alert("603969.SH", "episode-1")
    payload["outlook_1_3d"] = outlook

    assert _render_public_outlook(
        ForwardMonitorAlertV2.model_validate(payload)
    ).startswith(f"{direction}。")


def test_historical_v2_alert_without_outlook_reason_still_renders() -> None:
    payload = _alert("603969.SH", "episode-1")
    payload.pop("outlook_reason_plain_language")
    alert = ForwardMonitorAlertV2.model_validate(payload)

    rendered = _render_public_outlook(alert)

    assert rendered.startswith("未来1—3个交易日更可能横盘整理。")
    assert "主要原因是" not in rendered
    assert "会继续支持横盘判断的表现" in rendered
    assert "会让我改变当前判断的表现" in rendered


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
        (1, "D1"),
        (2, "D2"),
        (10, "D10"),
        (11, "D11"),
        (20, "D20"),
        (21, "延长观察第1天"),
        (30, "延长观察第10天"),
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
    alert["episode_reviews"][0]["current_review"] = (
        "这段上涨最有证据的解释是股票自身持续强于市场和行业，因为多个收盘推进，"
        "而不是只随大盘或行业同步上涨，也没有新的公司事项足以解释。推荐时期待的"
        "持续强势已经实现，目前更接近上涨后整理；未来一至三个交易日更可能震荡偏强。"
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
    saved = json.loads(Path(summary.json_file).read_text(encoding="utf-8"))
    markdown = Path(summary.markdown_file).read_text(encoding="utf-8")

    assert "今天的市场情况" in markdown
    assert "正式推荐股票的今日复盘" in markdown
    assert "当前D1/20" in markdown
    headings = (
        "今天发生了什么",
        "相比上次判断",
        "接下来1—3个交易日",
    )
    positions = [markdown.index(heading) for heading in headings]
    assert positions == sorted(positions)
    assert "当时看好它自身的价格表现连续强于市场和同类" in markdown
    assert "这段上涨最有证据的解释是股票自身持续强于市场和行业" in markdown
    assert "部分预期已经发生，但仍有关键部分需要验证。" not in markdown
    assert "推荐后怎么走" not in markdown
    assert "测试提醒原因" not in markdown
    assert "测试中的大盘变化" not in markdown
    assert "测试中的板块变化" not in markdown
    assert "测试中的个股变化" not in markdown
    assert "测试中的公司变化" not in markdown
    saved_alert = saved["alerts"][0]
    assert saved_alert["market_change"] == "测试中的大盘变化"
    assert saved_alert["sector_change"] == "测试中的板块变化"
    assert saved_alert["stock_change"] == "测试中的个股变化"
    assert saved_alert["company_change"] == "测试中的公司变化"
    assert saved_alert["why_reported"] == "测试提醒原因"
    assert "市场方面" not in markdown
    assert "行业方面" not in markdown
    assert "公司方面" not in markdown
    assert "个股方面" not in markdown
    assert "当前收盘较期间最高收盘回落+0.00%" not in markdown
    assert "测试中需要看到的继续走强事实" in markdown
    assert "测试中说明原判断不再成立的事实" in markdown
    assert "未来1—3个交易日更可能震荡偏上" in markdown
    assert "主要原因是：" in markdown
    assert "会进一步支持震荡偏上判断的表现：" in markdown
    assert "会让我改变当前判断的表现：" in markdown
    assert "判断增强条件：" not in markdown
    assert "判断改变条件：" not in markdown
    assert "。。" not in markdown
    assert "如果若" not in markdown
    assert "2026年8月3日入选" in markdown
    assert "当初看中它" not in markdown
    assert "冻结结论" not in markdown
    for forbidden in (
        "推荐后的第", "发动机", "行动日", "行动窗口",
        "原角色", "MFE", "MAE", "selected", "comparator",
        "nearest_nonselection", "episode", "episode_ids", "engine_type",
        "engine_status", "确认条件", "失效条件", "基础情形",
        "原逻辑", "传播链", "价格确认", "弱环节",
        "和当时最接近的备选相比",
        "后来发生了什么",
        "这些变化为什么支持或反对当时判断",
        "现在怎么看",
        "接下来关注什么",
    ):
        assert forbidden not in markdown


# Each direction has its own supporting and reversing facts; an upward recovery
# supports an upward outlook but reverses a weak one.
OUTLOOK_CASES = [
    ("strengthening", "未来1—3个交易日更可能继续向上", "会进一步支持向上判断的表现",
     "收盘继续提高，并继续跑赢市场。", "连续收低，并重新落后市场。"),
    ("continuation_possible", "未来1—3个交易日更可能震荡偏上", "会进一步支持震荡偏上判断的表现",
     "成交增加后仍能收稳，收盘继续提高。", "连续收低，跌回关键区域。"),
    ("weakening", "未来1—3个交易日更可能震荡偏下", "会进一步支持偏弱判断的表现",
     "收盘继续降低，反弹不能收稳。", "连续几个交易日提高收盘，并重新跑赢市场。"),
    ("invalidated", "未来1—3个交易日更可能继续偏弱", "会进一步支持偏弱判断的表现",
     "收盘继续降低，并继续落后市场。", "连续几个交易日提高收盘，并重新跑赢市场。"),
    ("overheated", "未来1—3个交易日更可能高位震荡，短线偏下", "会进一步支持高位震荡偏下判断的表现",
     "高位不能继续提高收盘，冲高回落增多。", "重新形成多个更高收盘并保持，且回落明显减轻。"),
    ("range_or_wait", "未来1—3个交易日更可能横盘整理", "会继续支持横盘判断的表现",
     "继续在原区间内波动，成交和收盘都没有形成明确方向。", "连续突破区间上沿或下沿，并有多个收盘保持。"),
    ("event_pending", "目前没有足够的可交易事实判断方向", "会继续维持暂时无法判断的事实",
     "仍缺少可靠可交易价格，关键事实仍未公开。", "出现完整可交易价格和足以作出方向判断的新事实。"),
]


@pytest.mark.parametrize(
    ("outlook", "expected", "label", "confirmation", "invalidation"),
    OUTLOOK_CASES,
)
def test_markdown_renders_direction_specific_conditions(
    tmp_path: Path, outlook: str, expected: str, label: str,
    confirmation: str, invalidation: str,
) -> None:
    snapshot = _review_snapshot(day_number=3)
    episode_id = snapshot["episodes"][0]["episode_id"]
    review = _episode_review(episode_id)
    snapshot_path, pending_path = _record_review_payload(tmp_path, snapshot, review)
    payload = json.loads(pending_path.read_text(encoding="utf-8"))
    reason = {
        "strengthening": "多个收盘继续提高，并持续强于市场。",
        "continuation_possible": "整理中仍保持相对优势，回落幅度有限。",
        "weakening": "最近收盘逐步降低，反弹没有保持。",
        "invalidated": "收盘连续降低，相对市场的弱势仍在扩大。",
        "overheated": "高位成交增加，收盘却接连降低。",
        "range_or_wait": "成交和收盘都没有形成明确方向。",
        "event_pending": "当前没有可靠的可交易价格，关键事项也尚未公开。",
    }[outlook]
    payload["alerts"][0].update(
        outlook_1_3d=outlook,
        outlook_reason_plain_language=reason,
        confirmation_condition=confirmation,
        invalidation_condition=invalidation,
    )
    pending_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    result = record_forward_monitor(
        snapshot_file=snapshot_path, report_file=pending_path, project_root=tmp_path,
    )
    markdown = Path(result.markdown_file).read_text(encoding="utf-8")
    outlook_text = markdown.split("**接下来1—3个交易日**\n\n", 1)[1].split("\n\n## ", 1)[0]
    assert outlook_text.split("\n\n") == [
        expected + "。",
        f"主要原因是：{reason}",
        f"{label}：{confirmation}",
        f"会让我改变当前判断的表现：{invalidation}",
    ]
    if outlook in {"weakening", "invalidated"}:
        support = outlook_text.split(label + "：", 1)[1].split("\n\n", 1)[0]
        assert "提高收盘" not in support and "跑赢" not in support
    assert "。。" not in markdown


def test_markdown_names_the_second_trading_day_with_d_label(
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

    assert "当前D2/20" in markdown
    assert "推荐后的第" not in markdown


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

    assert "延长观察第1天" in markdown
    assert "收盘较推荐参考价上涨21.00%" in markdown
    assert "前20个交易日收盘上涨20.00%" in markdown
    assert markdown.count("前20个交易日结束后，原判断和具体股票都基本合理。") == 1
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

    assert "当前D20/20" in markdown
    assert "收盘较推荐参考价上涨20.00%" in markdown
    assert "期间最高收盘上涨20.00%" in markdown
    assert "盘中最高上涨25.00%" not in markdown
    assert "最深下跌5.00%" in markdown
    assert "前20个交易日收盘上涨20.00%" in markdown
    assert "期间最高收盘上涨20.00%" in markdown
    assert "期间最深下跌5.00%" in markdown
    assert markdown.count("前20个交易日结束后，原判断和具体股票都基本合理。") == 1
    assert "**20个交易日最终复盘**" in markdown
    for heading in (
        "今天发生了什么",
        "相比上次判断",
        "接下来1—3个交易日",
    ):
        assert markdown.count(heading) == 1
    assert "前20天最终判断中，最薄弱的是" not in markdown
    assert "当前D20/20" in markdown
    assert "推荐后的第" not in markdown


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

    assert "只能复盘价格表现" not in markdown
    assert "原推荐背景（原始完整判断未保存，以下为当时留存的摘要）：" in markdown
    assert "当时看好它自身的价格表现连续强于市场和同类" in markdown
    assert "当时最担心的是这股强势不能持续" in markdown
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
    assert "正式推荐股票的今日复盘" in markdown
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
        "attention_reasons": ["checkpoint"],
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


def test_record_requires_outlook_reason_for_each_new_alert(tmp_path: Path) -> None:
    snapshot = _review_snapshot(day_number=3)
    episode_id = snapshot["episodes"][0]["episode_id"]
    alert = _alert("603969.SH", episode_id)
    alert["day_numbers"] = [3]
    alert.pop("outlook_reason_plain_language")
    snapshot_path = tmp_path / "snapshot.json"
    pending_path = tmp_path / "pending.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    pending_path.write_text(
        json.dumps(_report_payload(snapshot, alerts=[alert]), ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="outlook reason"):
        record_forward_monitor(
            snapshot_file=snapshot_path,
            report_file=pending_path,
            project_root=tmp_path,
        )


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
    assert "2026年8月3日推荐（当前D20/20）" in markdown
    assert markdown.count("前20个交易日结束后，原判断和具体股票都基本合理。") == 1
    for heading in (
        "今天发生了什么",
        "相比上次判断",
        "接下来1—3个交易日",
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
    selected["attention_reasons"] = []
    selected["day_number"] = 20
    selected["pair_context"]["paired_day_number"] = 20
    comparator["day_number"] = 20
    comparator["attention_reasons"] = ["checkpoint"]
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
    assert "收盘较推荐参考价上涨50.00%" in markdown
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


@pytest.mark.parametrize("day_number", [1, 3, 5, 10, 20, 21])
def test_markdown_does_not_repeat_internal_relative_fact_block(
    tmp_path: Path,
    day_number: int,
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

    assert "这只股票比全市场" not in markdown
    assert "比同一行业" not in markdown
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
        "发动机", "行动日", "推荐后的第", "首次定价",
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
    review = _episode_review(episode_id)
    review["current_review"] = (
        "这段变化更可能来自股票自身，但相对行业数据缺失，无法比较这一解释与行业共同上涨；"
        "推荐时最重要的预期只得到部分验证，目前方向暂时无法判断。"
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

    assert "相对行业数据缺失" in markdown
    assert "同一行业的对照数据不足" not in markdown


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

def test_register_counts_inferred_legacy_formal_selection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trace_file = tmp_path / "trace.json"
    _write_trace(
        trace_file,
        _single_selected_trace(
            formation_date="2026-07-31",
            action_date="2026-08-03",
        ),
    )
    monkeypatch.setattr(
        "stock_analyzer.ops.forward_monitor.selection_output_class",
        lambda **_kwargs: "legacy_v1_not_rewritten",
    )

    summary = register_episodes(
        trace_file=trace_file,
        label="legacy",
        project_root=tmp_path,
    )

    assert summary.selected_registered == 1
    assert summary.comparators_registered == 0


def _registered_legacy_project(
    tmp_path: Path,
    *,
    session_count: int,
) -> tuple[list[date], str]:
    trace = _single_selected_trace(
        formation_date="2026-07-01",
        action_date="2026-07-02",
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
    selected = next(
        item for item in registry["episodes"] if item["role"] == "selected"
    )
    selected.pop("selection_output_class")
    registry_path.write_text(
        json.dumps(registry, ensure_ascii=False),
        encoding="utf-8",
    )
    sessions = _seed_monitor_project(
        tmp_path,
        trace=trace,
        session_count=session_count,
    )
    return sessions, str(selected["episode_id"])


def test_legacy_formal_selection_counts_and_starts_formal_return(
    tmp_path: Path,
) -> None:
    sessions, episode_id = _registered_legacy_project(
        tmp_path,
        session_count=1,
    )

    snapshot = _prepare(tmp_path, sessions[0])
    episode = snapshot["episodes"][0]

    assert episode["episode_id"] == episode_id
    assert "selection_output_class" not in episode
    assert episode["formal_return_started"] is True
    assert snapshot["summary"]["selected_count"] == 1


def test_legacy_formal_selection_requires_and_persists_day_twenty_review(
    tmp_path: Path,
) -> None:
    sessions, episode_id = _registered_legacy_project(
        tmp_path,
        session_count=21,
    )

    d20 = _prepare(tmp_path, sessions[19])
    assert d20["required_final_review_episode_ids"] == [episode_id]
    assert d20["episodes"][0]["attention_reasons"][0] == "pending_final_review"

    d21 = _prepare(tmp_path, sessions[20])
    assert d21["required_final_review_episode_ids"] == [episode_id]
    assert d21["episodes"][0]["attention_reasons"][0] == "pending_final_review"


def test_formal_attention_stock_cannot_be_displaced_by_eight_nonformal_stocks(
    tmp_path: Path,
) -> None:
    base = _review_snapshot(day_number=3)
    episodes: list[dict] = []
    attention: list[dict] = []
    for index in range(9):
        formal = index == 8
        comparator = 4 <= index < 8
        code = f"00000{index}.SZ"
        role = "comparator" if comparator else "selected"
        output_class = (
            "confirmed_active"
            if formal
            else "not_formal_candidate"
            if comparator
            else "conditional_event"
        )
        episode = {
            **base["episodes"][0],
            "episode_id": f"priority-{index}",
            "ts_code": code,
            "name": f"股票{index}",
            "role": role,
            "selection_output_class": output_class,
            "day_number": 3,
        }
        episodes.append(episode)
        attention.append(
            {
                "ts_code": code,
                "name": episode["name"],
                "episode_ids": [episode["episode_id"]],
                "roles": [role],
                "day_numbers": [3],
                "original_engine_types": [
                    "independent_demand_acceleration"
                ],
                "attention_reasons": ["checkpoint"],
            }
        )
    snapshot = {
        **base,
        "episodes": episodes,
        "attention_stocks": attention,
        "required_final_review_episode_ids": [],
        "summary": {
            **base["summary"],
            "open_episode_count": 9,
            "distinct_stock_count": 9,
            "selected_count": 1,
            "comparator_count": 4,
            "primary_count": 9,
            "attention_stock_count": 9,
        },
    }

    def make_alert(episode: dict) -> dict:
        alert = _alert(episode["ts_code"], episode["episode_id"])
        alert.update(
            name=episode["name"],
            roles=[episode["role"]],
            day_numbers=[3],
        )
        return alert

    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    displaced_path = tmp_path / "displaced.json"
    displaced_path.write_text(
        json.dumps(
            _report_payload(
                snapshot,
                alerts=[make_alert(item) for item in episodes[:8]],
                unreported=1,
            ),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="formal attention stocks"):
        record_forward_monitor(
            snapshot_file=snapshot_path,
            report_file=displaced_path,
            project_root=tmp_path,
        )

    included_path = tmp_path / "included.json"
    included_alerts = [
        make_alert(episodes[8]),
        *[make_alert(item) for item in episodes[:7]],
    ]
    included_path.write_text(
        json.dumps(
            _report_payload(
                snapshot,
                alerts=included_alerts,
                unreported=1,
            ),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    summary = record_forward_monitor(
        snapshot_file=snapshot_path,
        report_file=included_path,
        project_root=tmp_path,
    )
    saved = json.loads(Path(summary.json_file).read_text(encoding="utf-8"))
    markdown = Path(summary.markdown_file).read_text(encoding="utf-8")

    assert len(saved["alerts"]) == 8
    assert episodes[8]["name"] in markdown
    for episode in episodes[:8]:
        assert episode["name"] not in markdown


@pytest.mark.parametrize("include_alert", [False, True])
def test_formal_stock_triggered_only_by_new_event_is_optional_for_public_report(
    tmp_path: Path,
    include_alert: bool,
) -> None:
    snapshot = _review_snapshot(day_number=3)
    episode = snapshot["episodes"][0]
    episode.update(
        selection_output_class="confirmed_active",
        attention_reasons=["new_official_event"],
        new_announcements=[{"announcement_id": "A1", "title": "配套文件"}],
    )
    snapshot["attention_stocks"][0]["attention_reasons"] = [
        "new_official_event"
    ]
    snapshot["required_final_review_episode_ids"] = []
    alerts = [_alert(episode["ts_code"], episode["episode_id"])] if include_alert else []
    if alerts:
        alerts[0]["day_numbers"] = [3]
    snapshot_path = tmp_path / "snapshot.json"
    pending_path = tmp_path / "pending.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    pending_path.write_text(
        json.dumps(
            _report_payload(
                snapshot,
                alerts=alerts,
                unreported=0 if include_alert else 1,
            ),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    summary = record_forward_monitor(
        snapshot_file=snapshot_path,
        report_file=pending_path,
        project_root=tmp_path,
    )

    saved = json.loads(Path(summary.json_file).read_text(encoding="utf-8"))
    unchanged_snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert len(saved["alerts"]) == int(include_alert)
    assert saved["unreported_attention_count"] == (0 if include_alert else 1)
    assert unchanged_snapshot["episodes"][0]["new_announcements"][0][
        "announcement_id"
    ] == "A1"
    assert unchanged_snapshot["attention_stocks"][0]["attention_reasons"] == [
        "new_official_event"
    ]


def test_same_stock_comparator_checkpoint_does_not_make_optional_formal_event_mandatory(
    tmp_path: Path,
) -> None:
    snapshot = _review_snapshot(day_number=3)
    formal = snapshot["episodes"][0]
    formal.update(
        selection_output_class="confirmed_active",
        attention_reasons=["new_official_event"],
    )
    comparator = {
        **formal,
        "episode_id": "comparator-episode",
        "role": "comparator",
        "selection_output_class": "not_formal_candidate",
        "attention_reasons": ["checkpoint"],
    }
    snapshot["episodes"] = [formal, comparator]
    snapshot["attention_stocks"][0].update(
        episode_ids=[formal["episode_id"], comparator["episode_id"]],
        roles=["selected", "comparator"],
        attention_reasons=["new_official_event", "checkpoint"],
    )
    snapshot["summary"].update(
        open_episode_count=2,
        selected_count=1,
        comparator_count=1,
        primary_count=2,
    )
    snapshot["required_final_review_episode_ids"] = []
    snapshot_path = tmp_path / "snapshot.json"
    pending_path = tmp_path / "pending.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    pending_path.write_text(
        json.dumps(_report_payload(snapshot, unreported=1)),
        encoding="utf-8",
    )

    summary = record_forward_monitor(
        snapshot_file=snapshot_path,
        report_file=pending_path,
        project_root=tmp_path,
    )

    assert summary.alert_count == 0
    assert summary.unreported_attention_count == 1


def test_eight_optional_formal_events_cannot_displace_one_mandatory_formal_review(
    tmp_path: Path,
) -> None:
    base = _review_snapshot(day_number=3)
    episodes: list[dict] = []
    attention: list[dict] = []
    for index in range(9):
        code = f"00000{index}.SZ"
        reasons = ["checkpoint"] if index == 8 else ["new_official_event"]
        episode = {
            **base["episodes"][0],
            "episode_id": f"formal-event-{index}",
            "ts_code": code,
            "name": f"股票{index}",
            "selection_output_class": "confirmed_active",
            "attention_reasons": reasons,
        }
        episodes.append(episode)
        attention.append(
            {
                "ts_code": code,
                "name": episode["name"],
                "episode_ids": [episode["episode_id"]],
                "roles": ["selected"],
                "day_numbers": [3],
                "original_engine_types": [
                    "independent_demand_acceleration"
                ],
                "attention_reasons": reasons,
            }
        )
    snapshot = {
        **base,
        "episodes": episodes,
        "attention_stocks": attention,
        "required_final_review_episode_ids": [],
        "summary": {
            **base["summary"],
            "open_episode_count": 9,
            "distinct_stock_count": 9,
            "selected_count": 9,
            "comparator_count": 0,
            "primary_count": 9,
            "attention_stock_count": 9,
        },
    }

    def make_alert(episode: dict) -> dict:
        alert = _alert(episode["ts_code"], episode["episode_id"])
        alert.update(name=episode["name"], day_numbers=[3])
        return alert

    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    displaced_path = tmp_path / "displaced.json"
    displaced_path.write_text(
        json.dumps(
            _report_payload(
                snapshot,
                alerts=[make_alert(item) for item in episodes[:8]],
                unreported=1,
            ),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="mandatory formal attention stocks"):
        record_forward_monitor(
            snapshot_file=snapshot_path,
            report_file=displaced_path,
            project_root=tmp_path,
        )

    included_path = tmp_path / "included.json"
    included_path.write_text(
        json.dumps(
            _report_payload(
                snapshot,
                alerts=[
                    make_alert(episodes[8]),
                    *[make_alert(item) for item in episodes[:7]],
                ],
                unreported=1,
            ),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    summary = record_forward_monitor(
        snapshot_file=snapshot_path,
        report_file=included_path,
        project_root=tmp_path,
    )
    saved = json.loads(Path(summary.json_file).read_text(encoding="utf-8"))

    assert len(saved["alerts"]) == 8
    assert {item["ts_code"] for item in saved["alerts"]} == {
        episodes[8]["ts_code"],
        *(item["ts_code"] for item in episodes[:7]),
    }


def _daily_formal_review(
    episode_id: str,
    *,
    day_number: int = 3,
    checkpoint: str | None = "D3",
    current_assessment: str = "partly_supported",
    current_path: str = "sideways",
    current_weak_or_failed_link: str = "none",
    view_change: str = "unchanged",
    tracking_decision: str = "keep_active_tracking",
    review_origin: str = "live",
    final: dict | None = None,
) -> dict:
    return {
        "episode_id": episode_id,
        "day_number": day_number,
        "checkpoint": checkpoint,
        "current_assessment": current_assessment,
        "current_path": current_path,
        "best_supported_explanation": "stock_specific_move",
        "current_weak_or_failed_link": current_weak_or_failed_link,
        "current_review": "当前走势横盘，原判断没有出现实质变化。",
        "view_change": view_change,
        "view_change_reason": "与上一交易日相比，决定判断的事实没有变化。",
        "outlook_1_3d": "range_or_wait",
        "outlook_reason_plain_language": "最近收盘没有形成新的方向。",
        "tracking_decision": tracking_decision,
        "tracking_decision_reason": "原推荐最重要的判断仍未被事实否定。",
        "review_origin": review_origin,
        "final_twenty_day_review": final,
    }


def _daily_formal_snapshot(*, day_number: int = 3) -> dict:
    snapshot = _review_snapshot(day_number=day_number)
    episode = snapshot["episodes"][0]
    episode.update(
        selection_output_class="confirmed_active",
        checkpoint=CHECKPOINTS_FOR_TESTS.get(day_number),
        entry_open=10.0,
        tracking_status="active",
        frozen_twenty_day_review=(
            _final_review() if day_number > 20 else None
        ),
    )
    snapshot["daily_review_episode_ids"] = [episode["episode_id"]]
    snapshot["evaluation_only_episode_ids"] = []
    snapshot["detailed_review_candidate_codes"] = [episode["ts_code"]]
    return snapshot


CHECKPOINTS_FOR_TESTS = {
    1: "D1",
    3: "D3",
    5: "D5",
    10: "D10",
    20: "D20",
    25: "D25",
    30: "D30",
}


def test_daily_formal_review_models_define_the_v1_contract() -> None:
    episode_id = "formal:2026-08-20:603969.SH:selected"
    payload = {
        "ledger_version": DAILY_FORMAL_REVIEWS_VERSION,
        "analysis_date": "2026-08-25",
        "as_of": "2026-08-25T18:00:00+08:00",
        "reviews": [_daily_formal_review(episode_id)],
    }

    ledger = DailyFormalReviewLedgerV1.model_validate(payload)

    assert ledger.reviews[0].current_path == "sideways"
    assert set(DailyFormalReviewV1.model_fields) == {
        "episode_id", "day_number", "checkpoint", "current_assessment",
        "current_path", "best_supported_explanation",
        "current_weak_or_failed_link", "current_review", "view_change",
        "view_change_reason", "outlook_1_3d",
        "outlook_reason_plain_language", "tracking_decision",
        "tracking_decision_reason", "review_origin",
        "final_twenty_day_review",
    }
    invalid = json.loads(json.dumps(payload))
    invalid["reviews"][0]["current_path"] = "震荡偏上"
    with pytest.raises(ValidationError):
        DailyFormalReviewLedgerV1.model_validate(invalid)


def test_record_daily_formal_reviews_is_idempotent_and_preserves_conflicts(
    tmp_path: Path,
) -> None:
    snapshot = _daily_formal_snapshot()
    episode_id = snapshot["daily_review_episode_ids"][0]
    payload = {
        "ledger_version": DAILY_FORMAL_REVIEWS_VERSION,
        "analysis_date": snapshot["analysis_date"],
        "as_of": snapshot["as_of"],
        "reviews": [_daily_formal_review(episode_id)],
    }
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    pending = tmp_path / "pending-daily-formal-reviews.json"
    pending.write_text(json.dumps(payload), encoding="utf-8")

    first = record_daily_formal_reviews(
        snapshot_file=snapshot_path,
        review_file=pending,
        project_root=tmp_path,
    )

    assert first.status == "recorded"
    assert first.review_count == 1
    assert not pending.exists()
    saved_path = Path(first.json_file)
    original = saved_path.read_bytes()

    same = tmp_path / "same.json"
    same.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    repeated = record_daily_formal_reviews(
        snapshot_file=snapshot_path,
        review_file=same,
        project_root=tmp_path,
    )
    assert repeated.status == "already_recorded"
    assert not same.exists()
    assert saved_path.read_bytes() == original

    conflict_payload = json.loads(json.dumps(payload))
    conflict_payload["reviews"][0]["current_review"] = "另一份不同的复盘。"
    conflict = tmp_path / "conflict.json"
    conflict.write_text(json.dumps(conflict_payload), encoding="utf-8")
    rejected = record_daily_formal_reviews(
        snapshot_file=snapshot_path,
        review_file=conflict,
        project_root=tmp_path,
    )
    assert rejected.status == "review_conflict"
    assert conflict.exists()
    assert saved_path.read_bytes() == original


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (
            {"tracking_decision": "stop_active_tracking"},
            "stop_active_tracking",
        ),
        (
            {
                "review_origin": "backfill",
                "tracking_decision": "keep_active_tracking",
            },
            "historical_not_applied",
        ),
    ],
)
def test_record_daily_formal_reviews_rejects_invalid_tracking_decisions(
    tmp_path: Path,
    change: dict,
    message: str,
) -> None:
    snapshot = _daily_formal_snapshot()
    review = _daily_formal_review(snapshot["daily_review_episode_ids"][0])
    review.update(change)
    snapshot_path = tmp_path / "snapshot.json"
    pending = tmp_path / "pending.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    pending.write_text(
        json.dumps(
            {
                "ledger_version": DAILY_FORMAL_REVIEWS_VERSION,
                "analysis_date": snapshot["analysis_date"],
                "as_of": snapshot["as_of"],
                "reviews": [review],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=message):
        record_daily_formal_reviews(
            snapshot_file=snapshot_path,
            review_file=pending,
            project_root=tmp_path,
        )


def test_daily_formal_review_requires_and_freezes_the_d20_conclusion(
    tmp_path: Path,
) -> None:
    snapshot = _daily_formal_snapshot(day_number=20)
    episode_id = snapshot["daily_review_episode_ids"][0]
    review = _daily_formal_review(
        episode_id,
        day_number=20,
        checkpoint="D20",
        tracking_decision="complete_observation",
        final=_final_review(),
    )
    snapshot_path = tmp_path / "snapshot.json"
    pending = tmp_path / "pending.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    pending.write_text(
        json.dumps(
            {
                "ledger_version": DAILY_FORMAL_REVIEWS_VERSION,
                "analysis_date": snapshot["analysis_date"],
                "as_of": snapshot["as_of"],
                "reviews": [review],
            }
        ),
        encoding="utf-8",
    )

    recorded = record_daily_formal_reviews(
        snapshot_file=snapshot_path,
        review_file=pending,
        project_root=tmp_path,
    )
    assert recorded.status == "recorded"

    d21 = _daily_formal_snapshot(day_number=21)
    d21["episodes"][0]["frozen_twenty_day_review"] = _final_review()
    later = _daily_formal_review(
        episode_id,
        day_number=21,
        checkpoint=None,
        final=_final_review("logic_right_timing_wrong"),
    )
    d21_path = tmp_path / "d21.json"
    d21_pending = tmp_path / "d21-pending.json"
    d21_path.write_text(json.dumps(d21), encoding="utf-8")
    d21_pending.write_text(
        json.dumps(
            {
                "ledger_version": DAILY_FORMAL_REVIEWS_VERSION,
                "analysis_date": d21["analysis_date"],
                "as_of": d21["as_of"],
                "reviews": [later],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="frozen"):
        record_daily_formal_reviews(
            snapshot_file=d21_path,
            review_file=d21_pending,
            project_root=tmp_path,
        )


def _record_daily_review_for_snapshot(
    root: Path,
    snapshot: dict,
    review: dict,
) -> None:
    monitor_dir = root / "local_archive/forward_monitor"
    monitor_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = monitor_dir / f"snapshot-{snapshot['analysis_date']}.json"
    pending_path = root / f"pending-daily-{snapshot['analysis_date']}.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    pending_path.write_text(
        json.dumps(
            {
                "ledger_version": DAILY_FORMAL_REVIEWS_VERSION,
                "analysis_date": snapshot["analysis_date"],
                "as_of": snapshot["as_of"],
                "reviews": [review],
            }
        ),
        encoding="utf-8",
    )
    record_daily_formal_reviews(
        snapshot_file=snapshot_path,
        review_file=pending_path,
        project_root=root,
    )


def test_prepare_includes_every_active_formal_episode_in_daily_reviews(
    tmp_path: Path,
) -> None:
    trace = _single_selected_trace(
        formation_date="2026-07-31",
        action_date="2026-08-03",
    )
    archive = tmp_path / "local_archive/forward_selection"
    archive.mkdir(parents=True)
    _write_trace(archive / "research-trace-2026-07-31.json", trace)
    sessions = _seed_monitor_project(tmp_path, trace=trace, session_count=2)

    d1 = _prepare(tmp_path, sessions[0])
    d2 = _prepare(tmp_path, sessions[1])
    episode_id = d1["episodes"][0]["episode_id"]

    assert d1["daily_review_episode_ids"] == [episode_id]
    assert d2["daily_review_episode_ids"] == [episode_id]
    assert d2["episodes"][0]["tracking_status"] == "active"
    assert d2["summary"]["active_tracking_count"] == 1
    assert d2["summary"]["daily_review_episode_count"] == 1
    assert d2["summary"]["detailed_review_stock_count"] == 1
    assert d2["detailed_review_candidate_codes"] == ["603969.SH"]


def test_stop_tracking_skips_ordinary_days_but_returns_for_d20(
    tmp_path: Path,
) -> None:
    trace = _single_selected_trace(
        formation_date="2026-07-31",
        action_date="2026-08-03",
    )
    archive = tmp_path / "local_archive/forward_selection"
    archive.mkdir(parents=True)
    _write_trace(archive / "research-trace-2026-07-31.json", trace)
    sessions = _seed_monitor_project(tmp_path, trace=trace, session_count=21)
    d1 = _prepare(tmp_path, sessions[0])
    episode_id = d1["daily_review_episode_ids"][0]
    _record_daily_review_for_snapshot(
        tmp_path,
        d1,
        _daily_formal_review(
            episode_id,
            day_number=1,
            checkpoint="D1",
            current_assessment="contradicted",
            current_path="down",
            view_change="invalidated",
            tracking_decision="stop_active_tracking",
        ),
    )

    d2 = _prepare(tmp_path, sessions[1])
    d20 = _prepare(tmp_path, sessions[19])

    assert d2["daily_review_episode_ids"] == []
    assert d2["evaluation_only_episode_ids"] == [episode_id]
    assert d2["episodes"][0]["tracking_status"] == "evaluation_only"
    assert d2["episodes"][0]["tracking_exit_date"] == str(sessions[0])
    assert d2["episodes"][0]["current_close_return_since_entry"] is not None
    assert d20["daily_review_episode_ids"] == [episode_id]
    assert d20["episodes"][0]["tracking_status"] == "evaluation_only"
    assert d20["summary"]["evaluation_only_count"] == 1

    _record_daily_review_for_snapshot(
        tmp_path,
        d20,
        _daily_formal_review(
            episode_id,
            day_number=20,
            checkpoint="D20",
            tracking_decision="complete_observation",
            final=_final_review(),
        ),
    )
    d21 = _prepare(tmp_path, sessions[20])
    assert d21["episodes"][0]["tracking_status"] == "completed"
    assert d21["episodes"][0]["tracking_exit_date"] == str(sessions[0])
    assert "原推荐" in d21["episodes"][0]["tracking_exit_reason"]


def test_backfill_review_never_changes_current_tracking_status(
    tmp_path: Path,
) -> None:
    trace = _single_selected_trace(
        formation_date="2026-07-31",
        action_date="2026-08-03",
    )
    archive = tmp_path / "local_archive/forward_selection"
    archive.mkdir(parents=True)
    _write_trace(archive / "research-trace-2026-07-31.json", trace)
    sessions = _seed_monitor_project(tmp_path, trace=trace, session_count=2)
    d1 = _prepare(tmp_path, sessions[0])
    episode_id = d1["daily_review_episode_ids"][0]
    _record_daily_review_for_snapshot(
        tmp_path,
        d1,
        _daily_formal_review(
            episode_id,
            day_number=1,
            checkpoint="D1",
            review_origin="backfill",
            tracking_decision="historical_not_applied",
        ),
    )

    d2 = _prepare(tmp_path, sessions[1])

    assert d2["episodes"][0]["tracking_status"] == "active"
    assert d2["daily_review_episode_ids"] == [episode_id]
    assert d2["episodes"][0]["previous_daily_formal_review"][
        "review_origin"
    ] == "backfill"


def _multi_daily_formal_snapshot(count: int) -> tuple[dict, list[dict]]:
    base = _daily_formal_snapshot(day_number=2)
    episodes: list[dict] = []
    reviews: list[dict] = []
    for index in range(count):
        code = f"{index + 1:06d}.SZ"
        episode_id = f"formal:2026-08-20:{code}:selected"
        episode = {
            **base["episodes"][0],
            "episode_id": episode_id,
            "ts_code": code,
            "name": f"股票{index + 1}",
            "day_number": 2,
            "checkpoint": None,
            "attention_reasons": [],
            "last_detailed_review_date": (
                f"2026-08-{20 + index:02d}" if index < 8 else None
            ),
            "days_since_last_detailed_review": (
                count - index if index < 8 else None
            ),
        }
        episodes.append(episode)
        reviews.append(
            _daily_formal_review(
                episode_id,
                day_number=2,
                checkpoint=None,
            )
        )
    codes = [episode["ts_code"] for episode in episodes]
    snapshot = {
        **base,
        "episodes": episodes,
        "attention_stocks": [],
        "required_final_review_episode_ids": [],
        "daily_review_episode_ids": [
            episode["episode_id"] for episode in episodes
        ],
        "evaluation_only_episode_ids": [],
        "detailed_review_candidate_codes": codes,
        "summary": {
            **base["summary"],
            "open_episode_count": count,
            "distinct_stock_count": count,
            "selected_count": count,
            "comparator_count": 0,
            "primary_count": count,
            "attention_stock_count": 0,
            "active_tracking_count": count,
            "evaluation_only_count": 0,
            "completed_formal_count": 0,
            "daily_review_episode_count": count,
            "detailed_review_stock_count": min(8, count),
        },
    }
    return snapshot, reviews


def _daily_detail_alert(episode: dict, daily_review: dict) -> dict:
    alert = _alert(episode["ts_code"], episode["episode_id"])
    alert.update(
        name=episode["name"],
        day_numbers=[episode["day_number"]],
        alert_type="routine_detail",
        outlook_1_3d=daily_review["outlook_1_3d"],
        outlook_reason_plain_language=(
            daily_review["outlook_reason_plain_language"]
        ),
        episode_reviews=[
            {
                **_episode_review(episode["episode_id"]),
                "current_review": daily_review["current_review"],
                "current_assessment": daily_review["current_assessment"],
                "best_supported_explanation": (
                    daily_review["best_supported_explanation"]
                ),
                "current_weak_or_failed_link": (
                    daily_review["current_weak_or_failed_link"]
                ),
                "final_twenty_day_review": (
                    daily_review["final_twenty_day_review"]
                ),
            }
        ],
    )
    case = next(case for case in OUTLOOK_CASES if case[0] == daily_review["outlook_1_3d"])
    alert["confirmation_condition"], alert["invalidation_condition"] = case[3:]
    return alert


def _write_daily_ledger(root: Path, snapshot: dict, reviews: list[dict]) -> None:
    monitor_dir = root / "local_archive/forward_monitor"
    monitor_dir.mkdir(parents=True, exist_ok=True)
    (monitor_dir / f"daily-formal-reviews-{snapshot['analysis_date']}.json").write_text(
        json.dumps(
            {
                "ledger_version": DAILY_FORMAL_REVIEWS_VERSION,
                "analysis_date": snapshot["analysis_date"],
                "as_of": snapshot["as_of"],
                "reviews": reviews,
            }
        ),
        encoding="utf-8",
    )


@pytest.mark.parametrize("count", [5, 12])
def test_new_monitor_report_details_all_or_exactly_eight_active_stocks(
    tmp_path: Path,
    count: int,
) -> None:
    snapshot, reviews = _multi_daily_formal_snapshot(count)
    snapshot_path = tmp_path / "snapshot.json"
    pending = tmp_path / "pending.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    _write_daily_ledger(tmp_path, snapshot, reviews)
    expected = min(8, count)
    selected_indices = (
        list(range(count))
        if count <= 8
        else [8, 9, 10, 11, 0, 1, 2, 3]
    )
    alerts = [
        _daily_detail_alert(snapshot["episodes"][index], reviews[index])
        for index in selected_indices
    ]
    pending.write_text(
        json.dumps(_report_payload(snapshot, alerts=alerts, unreported=0)),
        encoding="utf-8",
    )

    summary = record_forward_monitor(
        snapshot_file=snapshot_path,
        report_file=pending,
        project_root=tmp_path,
    )

    assert summary.alert_count == expected


def test_detail_report_rejects_inconsistent_daily_review(
    tmp_path: Path,
) -> None:
    snapshot, reviews = _multi_daily_formal_snapshot(1)
    snapshot_path = tmp_path / "snapshot.json"
    pending = tmp_path / "pending.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    _write_daily_ledger(tmp_path, snapshot, reviews)
    alert = _daily_detail_alert(snapshot["episodes"][0], reviews[0])
    alert["episode_reviews"][0]["current_assessment"] = "supported"
    pending.write_text(
        json.dumps(_report_payload(snapshot, alerts=[alert], unreported=0)),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="daily formal review"):
        record_forward_monitor(
            snapshot_file=snapshot_path,
            report_file=pending,
            project_root=tmp_path,
        )


def test_detail_report_requires_stop_d20_and_key_view_changes(
    tmp_path: Path,
) -> None:
    snapshot, reviews = _multi_daily_formal_snapshot(10)
    stop, d20, changed = 9, 8, 7
    reviews[stop].update(
        current_assessment="contradicted",
        current_path="down",
        view_change="invalidated",
        tracking_decision="stop_active_tracking",
    )
    snapshot["episodes"][d20].update(
        day_number=20,
        checkpoint="D20",
        frozen_twenty_day_review=None,
    )
    reviews[d20].update(
        day_number=20,
        checkpoint="D20",
        tracking_decision="complete_observation",
        final_twenty_day_review=_final_review(),
    )
    reviews[changed]["view_change"] = "strengthened"
    _write_daily_ledger(tmp_path, snapshot, reviews)
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")

    selected = [stop, d20, changed, 0, 1, 2, 3, 4]
    accepted = tmp_path / "accepted.json"
    accepted.write_text(
        json.dumps(
            _report_payload(
                snapshot,
                alerts=[
                    _daily_detail_alert(snapshot["episodes"][i], reviews[i])
                    for i in selected
                ],
                unreported=0,
            )
        ),
        encoding="utf-8",
    )
    recorded = record_forward_monitor(
        snapshot_file=snapshot_path,
        report_file=accepted,
        project_root=tmp_path,
    )
    assert recorded.alert_count == 8

    Path(recorded.json_file).unlink()
    Path(recorded.markdown_file).unlink()
    omitted_stop = tmp_path / "omitted-stop.json"
    omitted_stop.write_text(
        json.dumps(
            _report_payload(
                snapshot,
                alerts=[
                    _daily_detail_alert(snapshot["episodes"][i], reviews[i])
                    for i in [d20, changed, 0, 1, 2, 3, 4, 5]
                ],
                unreported=0,
            )
        ),
        encoding="utf-8",
    )
    with pytest.raises(
        ValueError,
        match="omits a stop, D20, or key view change",
    ):
        record_forward_monitor(
            snapshot_file=snapshot_path,
            report_file=omitted_stop,
            project_root=tmp_path,
        )


def test_new_markdown_lists_every_active_review_then_only_the_detailed_stocks(
    tmp_path: Path,
) -> None:
    snapshot, reviews = _multi_daily_formal_snapshot(5)
    reviews[1].update(
        current_assessment="weakening",
        current_path="down",
        outlook_1_3d="weakening",
        outlook_reason_plain_language="最近两个收盘逐步降低。",
    )
    reviews[2].update(
        current_assessment="contradicted",
        current_path="down",
        view_change="invalidated",
        tracking_decision="stop_active_tracking",
    )
    snapshot_path = tmp_path / "snapshot.json"
    pending = tmp_path / "pending.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    _write_daily_ledger(tmp_path, snapshot, reviews)
    alerts = [
        _daily_detail_alert(episode, review)
        for episode, review in zip(
            snapshot["episodes"], reviews, strict=True
        )
    ]
    pending.write_text(
        json.dumps(_report_payload(snapshot, alerts=alerts, unreported=0)),
        encoding="utf-8",
    )

    result = record_forward_monitor(
        snapshot_file=snapshot_path,
        report_file=pending,
        project_root=tmp_path,
    )
    markdown = Path(result.markdown_file).read_text(encoding="utf-8")

    assert "## 所有主动推荐的今日结论" in markdown
    assert (
        "| 股票 | 当前观察日 | 当前涨跌 | 当前走势 | 是否仍在预期内 | "
        "未来1—3日 | 主动跟踪 |"
    ) in markdown
    assert "股票2" in markdown
    assert "预期正在减弱但尚未被否定" in markdown
    assert "股票3" in markdown
    assert "今日停止" in markdown
    assert "## 今天重点复盘的5只股票" in markdown
    assert markdown.count("## 正式推荐股票的今日复盘") == 0
    assert "主动跟踪：4只" in markdown
    assert "仅保留评价：1条" in markdown
    assert "已完成：0条" in markdown


def test_cli_parses_record_daily_formal_reviews_command() -> None:
    parsed = _parse_args(
        [
            "record-daily-formal-reviews",
            "--snapshot-file",
            "snapshot.json",
            "--review-file",
            "pending-daily-formal-reviews.json",
        ]
    )

    assert parsed.command == "record-daily-formal-reviews"
    assert parsed.snapshot_file == "snapshot.json"
    assert parsed.review_file == "pending-daily-formal-reviews.json"


def test_d30_daily_review_must_complete_extended_observation(
    tmp_path: Path,
) -> None:
    snapshot = _daily_formal_snapshot(day_number=30)
    episode_id = snapshot["daily_review_episode_ids"][0]
    pending = tmp_path / "pending.json"
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    pending.write_text(
        json.dumps(
            {
                "ledger_version": DAILY_FORMAL_REVIEWS_VERSION,
                "analysis_date": snapshot["analysis_date"],
                "as_of": snapshot["as_of"],
                "reviews": [
                    _daily_formal_review(
                        episode_id,
                        day_number=30,
                        checkpoint="D30",
                        tracking_decision="keep_active_tracking",
                        final=_final_review(),
                    )
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="D30"):
        record_daily_formal_reviews(
            snapshot_file=snapshot_path,
            review_file=pending,
            project_root=tmp_path,
        )


def _daily_render_case(day_number: int = 3) -> tuple[dict, dict, dict]:
    snapshot = _daily_formal_snapshot(day_number=day_number)
    snapshot["summary"].update(
        active_tracking_count=1, evaluation_only_count=0,
        completed_formal_count=0, detailed_review_stock_count=1,
    )
    episode = snapshot["episodes"][0]
    daily = _daily_formal_review(
        episode["episode_id"], day_number=day_number,
        checkpoint=episode["checkpoint"],
        final=_final_review() if day_number >= 20 else None,
        tracking_decision="complete_observation" if day_number == 20 else "keep_active_tracking",
    )
    alert = _daily_detail_alert(episode, daily)
    return snapshot, daily, alert


def _render_daily_case(snapshot: dict, daily: dict, alert: dict) -> str:
    ledger = DailyFormalReviewLedgerV1.model_validate({
        "ledger_version": DAILY_FORMAL_REVIEWS_VERSION,
        "analysis_date": snapshot["analysis_date"], "as_of": snapshot["as_of"],
        "reviews": [daily],
    })
    return _render_markdown(
        DailyForwardMonitorReportV2.model_validate(_report_payload(snapshot, alerts=[alert])),
        snapshot, ledger,
    )


@pytest.mark.parametrize("day_number", [2, 3, 5, 10])
def test_daily_markdown_updates_the_view_without_repeating_original_recommendation(day_number: int) -> None:
    snapshot, daily, alert = _daily_render_case(day_number)
    markdown = _render_daily_case(snapshot, daily, alert)
    detail = markdown.split("### 银龙股份（603969.SH）\n\n", 1)[1].split("\n\n## ", 1)[0]
    assert re.findall(r"^\*\*(.+)\*\*$", detail, re.M) == [
        "今天发生了什么", "相比上次判断", "接下来1—3个交易日",
    ]
    expected_day = (
        f"当前D{day_number}/20"
        if day_number <= 20
        else f"20日核心观察已完成 · 延长观察第{day_number - 20}天"
    )
    assert detail.startswith(f"当前状态：2026年8月3日入选 · {expected_day}；")
    for value in ("推荐日期和当时判断", "到今天走到哪里", "我的分析", "综合判断", "什么情况会让我改变看法",
                  alert["episode_reviews"][0]["original_reason_plain_language"],
                  alert["episode_reviews"][0]["original_key_risk_plain_language"]):
        assert value not in detail
    assert detail.count(daily["current_review"]) == 1
    assert detail.count(daily["view_change_reason"]) == 1


def test_d1_background_is_at_most_two_sentences_and_appears_once() -> None:
    snapshot, daily, alert = _daily_render_case(1)
    review = alert["episode_reviews"][0]
    review.update(
        original_reason_plain_language="当时主要看中它连续强于市场。更多历史论证不必重放。",
        original_key_risk_plain_language="主要担心强势不能持续。完整风险细节留在历史记录。",
    )
    markdown = _render_daily_case(snapshot, daily, alert)
    background = markdown.split("原推荐背景：", 1)[1].split("\n", 1)[0]
    assert markdown.count("原推荐背景：") == 1
    assert markdown.count("当时主要看中它连续强于市场") == 1
    assert markdown.count("主要担心强势不能持续") == 1
    assert len(re.findall(r"[。！？!?]", background)) <= 2
    assert "更多历史论证" not in markdown
    assert "完整风险细节" not in markdown
    assert markdown.index("当前状态：") < markdown.index("原推荐背景：") < markdown.index("**今天发生了什么**")


def test_daily_d20_has_one_separate_final_review() -> None:
    snapshot, daily, alert = _daily_render_case(20)
    markdown = _render_daily_case(snapshot, daily, alert)
    assert markdown.count("**20个交易日最终复盘**") == 1
    assert markdown.count(daily["final_twenty_day_review"]["overall_review"]) == 1
    current, final = markdown.split("**20个交易日最终复盘**", 1)
    assert daily["current_review"] in current
    assert daily["final_twenty_day_review"]["overall_review"] not in current
    assert "前20个交易日收盘上涨8.00%" in final
    assert "期间最高收盘上涨12.00%" in final
    assert "期间最深下跌4.00%" in final
    assert "推荐日期和当时判断" not in markdown


@pytest.mark.parametrize("change,label", [
    ("first_review", ""), ("unchanged", "判断没有实质变化"),
    ("strengthened", "判断增强"), ("weakened", "判断减弱"),
    ("invalidated", "原判断已被事实否定"),
])
def test_daily_view_change_comes_directly_from_ledger(change: str, label: str) -> None:
    snapshot, daily, alert = _daily_render_case()
    daily.update(view_change=change, view_change_reason="今天决定判断的事实说明。")
    # 正文与观点变化来源不同：正文读详评，观点变化读台账。
    alert["episode_reviews"][0]["current_review"] = "另一份独立展开的详评正文。"
    markdown = _render_daily_case(snapshot, daily, alert)
    assert alert["episode_reviews"][0]["current_review"] in markdown
    paragraph = markdown.split("**相比上次判断**\n\n", 1)[1].split("\n\n", 1)[0]
    assert label in paragraph
    assert paragraph.endswith(daily["view_change_reason"])
    assert "first_review" not in paragraph
    if change == "first_review":
        assert "第一次" not in paragraph and "首次" not in paragraph


@pytest.mark.parametrize("entry,current,highest,lowest,expected", [
    (None, None, None, None, "没有可靠的推荐参考价"),
    (10.0, None, 0.12, -0.04, "期间最高收盘上涨12.00%"),
    (10.0, -0.08, -0.02, -0.10, "期间最高收盘下跌2.00%"),
])
def test_compact_status_only_shows_available_price_facts(entry, current, highest, lowest, expected) -> None:
    snapshot, daily, alert = _daily_render_case()
    snapshot["episodes"][0].update(
        entry_open=entry, current_close_return_since_entry=current,
        current_max_close_return_since_entry=highest, current_mae_since_entry=lowest,
    )
    status = _render_daily_case(snapshot, daily, alert).split("当前状态：", 1)[1].split("\n", 1)[0]
    assert "当前D3/20" in status and expected in status
    assert "None" not in status and "nan" not in status
    if current is None:
        assert "收盘较推荐参考价" not in status


def test_daily_and_detail_text_may_differ(tmp_path: Path) -> None:
    snapshot, daily, alert = _daily_render_case(10)
    daily["current_review"] = "日评：整理尚未结束。"
    detail = "详评：原来期待的相对强势仍需逐日检验。" * 40
    assert len(detail) > 600
    alert["episode_reviews"][0]["current_review"] = detail
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    _record_daily_review_for_snapshot(tmp_path, snapshot, daily)
    pending = tmp_path / "pending.json"
    pending.write_text(json.dumps(_report_payload(snapshot, alerts=[alert])),
                       encoding="utf-8")
    result = record_forward_monitor(
        snapshot_file=snapshot_path, report_file=pending, project_root=tmp_path
    )
    assert result.status == "recorded"
    markdown = Path(result.markdown_file).read_text(encoding="utf-8")
    assert detail in markdown
    assert daily["view_change_reason"] in markdown


def test_daily_and_detail_text_may_be_identical(tmp_path: Path) -> None:
    snapshot, daily, alert = _daily_render_case()
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    _record_daily_review_for_snapshot(tmp_path, snapshot, daily)
    pending = tmp_path / "pending.json"
    pending.write_text(json.dumps(_report_payload(snapshot, alerts=[alert])), encoding="utf-8")
    result = record_forward_monitor(snapshot_file=snapshot_path, report_file=pending, project_root=tmp_path)
    assert result.status == "recorded"
    markdown = Path(result.markdown_file).read_text(encoding="utf-8")
    assert markdown.count(daily["current_review"]) == 1
    assert markdown.count(daily["view_change_reason"]) == 1


@pytest.mark.parametrize("conflict", ["assessment", "explanation", "outlook"])
def test_detail_conflicting_structured_fields_still_rejected(
    tmp_path: Path, conflict: str
) -> None:
    snapshot, daily, alert = _daily_render_case()
    alert["episode_reviews"][0]["current_review"] = "另一份合法的独立详评正文。"
    review = alert["episode_reviews"][0]
    if conflict == "assessment":
        review["current_assessment"] = "contradicted"
    elif conflict == "explanation":
        review["best_supported_explanation"] = "market_common_move"
    else:
        alert["outlook_1_3d"] = "invalidated"
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    _record_daily_review_for_snapshot(tmp_path, snapshot, daily)
    pending = tmp_path / "pending.json"
    pending.write_text(json.dumps(_report_payload(snapshot, alerts=[alert])), encoding="utf-8")
    with pytest.raises(ValueError, match=daily["episode_id"]):
        record_forward_monitor(snapshot_file=snapshot_path, report_file=pending, project_root=tmp_path)


def test_detail_conflicting_d20_final_review_still_rejected(tmp_path: Path) -> None:
    snapshot, daily, alert = _daily_render_case(20)
    alert["episode_reviews"][0]["current_review"] = "D20详评正文，与日评允许不同。"
    final = json.loads(json.dumps(daily["final_twenty_day_review"]))
    final["overall_review"] += "详评阶段改写的结论不应被接受。"
    alert["episode_reviews"][0]["final_twenty_day_review"] = final
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    _record_daily_review_for_snapshot(tmp_path, snapshot, daily)
    pending = tmp_path / "pending.json"
    pending.write_text(json.dumps(_report_payload(snapshot, alerts=[alert])), encoding="utf-8")
    with pytest.raises(ValueError, match=daily["episode_id"]):
        record_forward_monitor(snapshot_file=snapshot_path, report_file=pending, project_root=tmp_path)


def test_combined_report_separates_weak_daily_update_from_new_recommendation(tmp_path: Path) -> None:
    snapshot, daily, alert = _daily_render_case()
    snapshot["episodes"][0].update(
        current_close_return_since_entry=-0.06,
        current_max_close_return_since_entry=0.02,
        current_mae_since_entry=-0.08,
    )
    daily.update(
        current_assessment="contradicted", current_path="down", view_change="invalidated",
        current_review="今天收盘继续降低，先前期待的持续强势已经被打断。股票也继续落后市场，原先的上涨判断已不成立。",
        view_change_reason="此前只是回落，今天继续落后市场，原先预期的持续强势没有恢复。",
        outlook_1_3d="invalidated",
        outlook_reason_plain_language="收盘连续降低，相对市场的弱势仍在扩大。",
        tracking_decision="stop_active_tracking",
        tracking_decision_reason="原先持续强于市场的判断已被事实否定。",
    )
    alert = _daily_detail_alert(snapshot["episodes"][0], daily)
    _record_daily_review_for_snapshot(tmp_path, snapshot, daily)
    pending = tmp_path / "pending.json"
    pending.write_text(json.dumps(_report_payload(snapshot, alerts=[alert])), encoding="utf-8")
    result = record_forward_monitor(
        snapshot_file=tmp_path / "local_archive/forward_monitor/snapshot-2026-08-31.json",
        report_file=pending, project_root=tmp_path,
    )
    monitor = Path(result.markdown_file).read_text(encoding="utf-8")
    # New recommendations are authored by the selection prompt, not the monitor
    # renderer. This frozen test-only explanation exercises that composition boundary.
    new_recommendation = """## 今天明确推荐的股票

### 示例制造（600001.SH）

**公司主要做什么**

公司生产工业设备，客户主要是制造企业。

**为什么会选它**

今天选择它，是因为新订单增加后，股票连续多个交易日强于同行，开始得到实际表现支持。

**行业或外部变化**

下游扩产带来设备需求，新订单与公司的产品直接相关。

**股票自身表现**

成交增加后仍有多个更高收盘，说明上涨持续到了不同交易日。

**公司经营**

订单增加支持后续交付，但收入仍需等实际交货确认。

**主要不利因素**

最近已经上涨，若交付推迟，当前价格可能难以保持。

**综合判断**

订单变化与持续强于同行的表现相互支持，暂时超过交付时间不确定的不利影响，因此今天选择它。

**什么情况会让我改变看法**

若订单取消，或多个交易日放量收低并落后同行，就需要改变判断。
"""
    combined = monitor + "\n" + new_recommendation
    (tmp_path / "combined-review-example.md").write_text(combined, encoding="utf-8")
    detail = monitor.split("### 银龙股份（603969.SH）\n\n", 1)[1].split("\n\n## ", 1)[0]
    assert detail.strip().split("\n\n") == [
        "当前状态：2026年8月3日入选 · 当前D3/20；收盘较推荐参考价下跌6.00%；期间最高收盘上涨2.00%；期间最深下跌8.00%。",
        "**今天发生了什么**", daily["current_review"],
        "**相比上次判断**", "原判断已被事实否定：" + daily["view_change_reason"],
        "**接下来1—3个交易日**", "未来1—3个交易日更可能继续偏弱。",
        "主要原因是：收盘连续降低，相对市场的弱势仍在扩大。",
        "会进一步支持偏弱判断的表现：收盘继续降低，并继续落后市场。",
        "会让我改变当前判断的表现：连续几个交易日提高收盘，并重新跑赢市场。",
    ]
    assert "原推荐背景" not in detail
    assert "为什么会选它" not in detail
    assert "今天发生了什么" not in new_recommendation
    assert re.findall(r"^\*\*(.+)\*\*$", new_recommendation, re.M) == [
        "公司主要做什么", "为什么会选它", "行业或外部变化", "股票自身表现",
        "公司经营", "主要不利因素", "综合判断", "什么情况会让我改变看法",
    ]
    assert combined.index("### 银龙股份") < combined.index("## 今天明确推荐的股票")
    for internal in ("invalidated", "current_review", "episode", "推荐后的第", "系统检测到"):
        assert internal not in combined


def test_multiple_daily_episodes_keep_their_own_dates_updates_and_view_changes() -> None:
    snapshot, daily, alert = _daily_render_case(3)
    newer = {
        **snapshot["episodes"][0], "episode_id": "formal:newer:603969.SH:selected",
        "action_date": "2026-08-04", "day_number": 2, "checkpoint": None,
    }
    snapshot["episodes"].append(newer)
    second_daily = {
        **daily, "episode_id": newer["episode_id"], "day_number": 2, "checkpoint": None,
        "current_review": "较晚推荐的这条记录仍在整理。",
        "view_change": "weakened", "view_change_reason": "最新收盘未能继续提高。",
    }
    alert["episode_ids"].append(newer["episode_id"])
    alert["day_numbers"] = [2, 3]
    alert["episode_reviews"].append({
        **_episode_review(newer["episode_id"]),
        "current_review": "较晚推荐的详评：仍在整理，成交未恢复。",
    })
    ledger = DailyFormalReviewLedgerV1.model_validate({
        "ledger_version": DAILY_FORMAL_REVIEWS_VERSION,
        "analysis_date": snapshot["analysis_date"], "as_of": snapshot["as_of"],
        "reviews": [daily, second_daily],
    })
    markdown = _render_markdown(
        DailyForwardMonitorReportV2.model_validate(_report_payload(snapshot, alerts=[alert])), snapshot, ledger,
    )
    assert markdown.count("### 银龙股份（603969.SH）") == 1
    for heading in ("今天发生了什么", "相比上次判断", "接下来1—3个交易日"):
        assert markdown.count(f"**{heading}**") == 1
    assert "2026年8月3日推荐（当前D3/20）：" + daily["current_review"] in markdown
    assert "2026年8月4日推荐（当前D2/20）：较晚推荐的详评：仍在整理，成交未恢复。" in markdown
    assert "2026年8月4日推荐（当前D2/20）：判断减弱：最新收盘未能继续提高。" in markdown
    assert "原推荐背景" not in markdown



def _seed_full_context_project(
    tmp_path: Path,
    *,
    index_rows: dict[date, list[dict]] | None = None,
) -> list[date]:
    """30个持仓内会话 + 45个推荐前会话，保证61日复盘上下文窗口完整。"""
    trace = _single_selected_trace(
        formation_date="2026-07-30",
        action_date="2026-07-31",
    )
    archive = tmp_path / "local_archive/forward_selection"
    archive.mkdir(parents=True)
    _write_trace(archive / "research-trace-2026-07-31.json", trace)
    sessions = _seed_monitor_project(tmp_path, trace=trace, session_count=30)
    action = date.fromisoformat(trace["action_date"])
    pre_days = [
        stamp.date()
        for stamp in pd.bdate_range(end=action - timedelta(days=1), periods=45)
    ]
    calendar_path = (
        tmp_path
        / "local_warehouse/facts/trade_calendar/cal_year=2026/data.parquet"
    )
    calendar = pd.read_parquet(calendar_path)
    extra_calendar = pd.DataFrame(
        [
            {
                "exchange": "SSE",
                "cal_date": day,
                "is_open": True,
                "available_at": datetime(2026, 1, 1, tzinfo=SHANGHAI),
            }
            for day in pre_days
        ]
    )
    pd.concat([calendar, extra_calendar], ignore_index=True).to_parquet(
        calendar_path, index=False
    )
    codes = ["001301.SZ", "603969.SH"]
    for day in pre_days:
        for name in ("equity_daily", "adj_factor"):
            row = {
                "trade_date": day,
                "ts_code": None,
                "available_at": datetime.combine(
                    day, datetime.min.time(), SHANGHAI
                ).replace(hour=16),
            }
            if name == "equity_daily":
                row.update(open=10.0, close=10.0, high=10.5, low=9.5, amount=100.0)
            else:
                row.update(adj_factor=1.0)
            frames = []
            for code in codes:
                frames.append({**row, "ts_code": code})
            _write_parquet(
                tmp_path,
                f"local_warehouse/facts/{name}/trade_date={day}/data.parquet",
                frames,
            )
    for day, rows in (index_rows or {}).items():
        _write_parquet(
            tmp_path,
            f"local_warehouse/facts/index_daily/trade_date={day}/data.parquet",
            rows,
        )
    return sessions


def _index_rows(day: date, code: str, *, open_: float, close: float) -> dict:
    return {
        "trade_date": day,
        "index_code": code,
        "open": open_,
        "close": close,
        "available_at": datetime.combine(
            day, datetime.min.time(), SHANGHAI
        ).replace(hour=16),
    }


def test_prepare_review_context_excludes_sessions_after_analysis_date(
    tmp_path: Path,
) -> None:
    sessions = _seed_full_context_project(tmp_path)
    analysis_date = sessions[28]
    as_of = datetime.combine(
        sessions[29], datetime.min.time(), SHANGHAI
    ).replace(hour=9)
    summary = prepare_forward_monitor(
        analysis_date=analysis_date,
        as_of=as_of,
        project_root=tmp_path,
    )
    snapshot = json.loads(Path(summary.snapshot_file).read_text(encoding="utf-8"))
    assert snapshot["daily_review_episode_ids"]
    for episode in snapshot["episodes"]:
        if "review_context" not in episode:
            continue
        context = episode["review_context"]
        dates = [item["date"] for item in context["post_entry_sessions"]]
        dates += [item["date"] for item in context["recent_sessions"]]
        assert sessions[29].isoformat() not in dates
        assert context["recent_sessions"][-1]["date"] == analysis_date.isoformat()
        assert context["basis"]["analysis_date"] == analysis_date.isoformat()


def test_prepare_review_context_ignores_available_at_overflow_rows(
    tmp_path: Path,
) -> None:
    sessions = _seed_full_context_project(tmp_path)
    analysis_date = sessions[29]
    as_of = datetime.combine(
        analysis_date, datetime.min.time(), SHANGHAI
    ).replace(hour=18)
    poison_time = as_of.replace(hour=23)
    equity_dir = (
        tmp_path
        / "local_warehouse/facts/equity_daily"
        / f"trade_date={analysis_date}/data.parquet"
    )
    poisoned = pd.read_parquet(equity_dir)
    late = poisoned.iloc[[0]].copy()
    late["close"] = 99.0
    late["available_at"] = poison_time
    pd.concat([poisoned, late], ignore_index=True).to_parquet(equity_dir, index=False)
    factor_dir = (
        tmp_path
        / "local_warehouse/facts/adj_factor"
        / f"trade_date={analysis_date}/data.parquet"
    )
    poisoned_factor = pd.read_parquet(factor_dir)
    late_factor = poisoned_factor.iloc[[0]].copy()
    late_factor["adj_factor"] = 9.9
    late_factor["available_at"] = poison_time
    pd.concat([poisoned_factor, late_factor], ignore_index=True).to_parquet(
        factor_dir, index=False
    )
    summary = prepare_forward_monitor(
        analysis_date=analysis_date,
        as_of=as_of,
        project_root=tmp_path,
    )
    snapshot = json.loads(Path(summary.snapshot_file).read_text(encoding="utf-8"))
    episode = next(
        item
        for item in snapshot["episodes"]
        if item["episode_id"] in snapshot["daily_review_episode_ids"]
    )
    context = episode["review_context"]
    levels = context["price_levels"]
    # 越界行不参与：分析日收盘仍为 10+0.1*30=13.0，因子仍为 1.0。
    assert levels["current_close"] == pytest.approx(13.0)
    assert episode["current_close_return_since_entry"] == pytest.approx(0.30)
    assert episode["target_atr_distance_20pct"] == pytest.approx(4.0)
    assert context["recent_sessions"][-1]["close"] == pytest.approx(13.0)


def test_prepare_review_context_uses_only_hs300_in_mixed_index_partitions(
    tmp_path: Path,
) -> None:
    action_day = date(2026, 7, 31)
    sessions = _seed_full_context_project(
        tmp_path,
        index_rows={
            action_day: [
                _index_rows(action_day, "000300.SH", open_=4000.0, close=4001.0),
                _index_rows(action_day, "000001.SH", open_=3000.0, close=3001.0),
            ],
        },
    )
    analysis_date = sessions[29]
    last_day_rows = [
        _index_rows(analysis_date, "000300.SH", open_=4080.0, close=4080.0),
        _index_rows(analysis_date, "000001.SH", open_=3300.0, close=3300.0),
    ]
    _write_parquet(
        tmp_path,
        f"local_warehouse/facts/index_daily/trade_date={analysis_date}/data.parquet",
        last_day_rows,
    )
    summary = _prepare(tmp_path, analysis_date)
    episode = next(
        item
        for item in summary["episodes"]
        if item["episode_id"] in summary["daily_review_episode_ids"]
    )
    context = episode["review_context"]
    # 沪深300：4000→4080 即 +2%；上证行（+10%）不得混入。
    assert context["benchmark_return_since_entry"] == pytest.approx(0.02)
    assert context["stock_excess_since_entry"] == pytest.approx(0.30 - 0.02)
    assert context["basis"]["benchmark_code"] == "000300.SH"
    assert context["basis"]["benchmark_name"] == "沪深300"
    windows = {item["days"]: item for item in context["benchmark_windows"]}
    assert windows[20]["return"] is None  # 起点收盘缺失时窗口为空
    assert windows[20]["end_date"] == analysis_date.isoformat()


def test_prepare_review_context_keeps_legacy_metrics_and_pair_shapes(
    tmp_path: Path,
) -> None:
    sessions = _seed_full_context_project(tmp_path)
    analysis_date = sessions[29]
    summary = _prepare(tmp_path, analysis_date)
    episode = next(
        item
        for item in summary["episodes"]
        if item["episode_id"] in summary["daily_review_episode_ids"]
    )
    context = episode["review_context"]
    # 旧指标不变：入口收益、D20、目标ATR距离与配对形状全部保持既有含义。
    assert episode["current_close_return_since_entry"] == pytest.approx(0.30)
    assert episode["d20_close_return_since_entry"] == pytest.approx(0.20)
    assert episode["target_atr_distance_20pct"] == pytest.approx(4.0)
    assert episode["pair_context"]["pair_status"] == "unavailable"
    # 新字段口径：basis 与既有相对行业字段边界清晰。
    assert context["basis"]["price_basis"] == "raw_times_factor_div_analysis_factor"
    assert context["basis"]["primary_industry_code"] == "801000.SI"
    assert context["basis"]["source_as_of"] == "2026-07-31T09:10:00+08:00"
    post = context["post_entry_sessions"]
    assert post[0]["date"] == sessions[0].isoformat()
    assert post[-1]["close_return"] == pytest.approx(0.30)
    assert len(post) == 30  # 行动日至分析日最多30个市场会话
    levels = context["price_levels"]
    assert levels["prior60_high"] is not None  # 61日窗口完整时前高可算
    assert levels["atr20"] is not None
    assert levels["target_price"] == pytest.approx(12.0)  # 入口10 × 1.2
    assert "review_context_missing_action_day_open" not in context["limitations"]
    # 快照中只有当日需日评的episode获得review_context。
    with_context = {
        item["episode_id"] for item in summary["episodes"] if "review_context" in item
    }
    assert with_context == set(summary["daily_review_episode_ids"])
