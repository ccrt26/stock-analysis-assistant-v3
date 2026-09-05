from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator

from stock_analyzer.ops.forward_selection import (
    MarketPropagationModeV4,
    selection_output_class,
)


REGISTER_VERSION = "registered-forward-monitor-episodes-v1"
TRACE_VERSION = "daily-research-trace-v4"
SNAPSHOT_VERSION = "forward-monitor-snapshot-v1"
DAILY_FORMAL_REVIEWS_VERSION = "daily-formal-reviews-v1"
CHECKPOINTS = {1: "D1", 3: "D3", 5: "D5", 10: "D10", 20: "D20", 25: "D25", 30: "D30"}
POSITIVE_SCENARIOS = {"initial_activation", "confirmed_breakout", "trend_continuation", "reversal_attempt"}
NEGATIVE_SCENARIOS = {"failed_breakout", "single_day_impulse", "range_cross_noise"}
OVERHEAT_SCENARIOS = {"single_day_impulse", "trend_exhaustion", "failed_breakout"}
PUBLIC_FORMAL_OUTPUT_CLASSES = frozenset(
    {"confirmed_active", "legacy_v1_not_rewritten"}
)
MANDATORY_FORMAL_REVIEW_REASONS = frozenset(
    {
        "pending_final_review",
        "checkpoint",
        "target_hit_first_time",
        "relative_state_changed",
        "scenario_changed",
        "breakout_changed",
        "sector_state_changed",
        "late_activation_candidate",
        "overheat_candidate",
        "data_problem",
    }
)


@dataclass(frozen=True)
class RegisterSummary:
    status: str
    registry_file: str
    selected_registered: int
    comparators_registered: int


@dataclass(frozen=True)
class PrepareSummary:
    status: str
    analysis_date: str
    snapshot_file: str
    open_episode_count: int
    distinct_stock_count: int
    attention_stock_count: int
    selected_count: int
    comparator_count: int
    primary_count: int
    passive_tail_count: int
    closed_count: int
    active_tracking_count: int
    evaluation_only_count: int
    completed_formal_count: int
    daily_review_episode_count: int
    detailed_review_stock_count: int


class MarketOverviewV1(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    market_propagation_mode: MarketPropagationModeV4
    market_risk_overlays: list[str]
    what_changed: str = Field(min_length=1)
    implication_for_monitored_stocks: str = Field(min_length=1)


class MonitorPoolSummaryV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    open_episode_count: int = Field(ge=0)
    distinct_stock_count: int = Field(ge=0)
    selected_count: int = Field(ge=0)
    comparator_count: int = Field(ge=0)
    primary_count: int = Field(ge=0)
    passive_tail_count: int = Field(ge=0)
    attention_stock_count: int = Field(ge=0)
    routine_stock_count: int = Field(ge=0)


class ForwardMonitorAlertV1(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    ts_code: str = Field(min_length=9)
    name: str = Field(min_length=1)
    episode_ids: list[str] = Field(min_length=1)
    roles: list[Literal["selected", "comparator"]] = Field(
        min_length=1,
        max_length=2,
    )
    day_numbers: list[int] = Field(min_length=1)
    original_engine_types: list[str]
    alert_type: Literal[
        "new_event", "first_reaction", "strengthening", "actionable_watch",
        "overheated", "invalidated", "target_hit", "late_activation",
        "checkpoint", "data_problem", "routine_detail",
    ]
    monitor_state: Literal[
        "pending_confirmation", "routine", "strengthening", "actionable_watch",
        "overheated", "invalidated", "target_hit", "passive_tail",
    ]
    market_change: str = Field(min_length=1)
    sector_change: str = Field(min_length=1)
    stock_change: str = Field(min_length=1)
    company_change: str = Field(min_length=1)
    outlook_1_3d: Literal[
        "event_pending", "strengthening", "continuation_possible", "range_or_wait",
        "weakening", "overheated", "invalidated",
    ]
    confirmation_condition: str = Field(min_length=1)
    invalidation_condition: str = Field(min_length=1)
    why_reported: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_roles(self) -> "ForwardMonitorAlertV1":
        fixed_order = [
            role
            for role in ("selected", "comparator")
            if role in self.roles
        ]
        if self.roles != fixed_order:
            raise ValueError("roles must be unique and ordered selected, comparator")
        return self


class DailyForwardMonitorReportV1(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    report_version: Literal["daily-forward-monitor-report-v1"]
    analysis_date: date
    as_of: datetime
    market_overview: MarketOverviewV1
    pool_summary: MonitorPoolSummaryV1
    alerts: list[ForwardMonitorAlertV1] = Field(max_length=8)
    unreported_attention_count: int = Field(ge=0)
    routine_summary: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_report(self) -> "DailyForwardMonitorReportV1":
        codes = [alert.ts_code for alert in self.alerts]
        if len(codes) != len(set(codes)):
            raise ValueError("the same stock may appear only once")
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("as_of must include a timezone")
        if self.analysis_date > self.as_of.date():
            raise ValueError("report contains a future analysis date")
        return self


class FrozenTwentyDayReviewV1(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    weak_or_failed_link: Literal[
        "none",
        "market_conditions",
        "new_information",
        "industry_follow_through",
        "price_and_volume_confirmation",
        "remaining_room",
        "company_risk",
        "timing",
        "execution",
        "stock_selection",
        "unknown",
    ]
    decision_review: Literal[
        "logic_and_stock_both_reasonable",
        "direction_right_stock_wrong",
        "logic_right_timing_wrong",
        "not_executable",
        "short_term_reason_wrong",
        "selection_evidence_insufficient",
        "unknown",
    ]
    overall_review: str = Field(min_length=1)


class DailyFormalReviewV1(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    episode_id: str = Field(min_length=1)
    day_number: int = Field(ge=1, le=30)
    checkpoint: Literal[
        "D1", "D3", "D5", "D10", "D20", "D25", "D30",
    ] | None = None
    current_assessment: Literal[
        "not_yet_tested", "partly_supported", "supported", "weakening",
        "contradicted", "insufficient_evidence",
    ]
    current_path: Literal["up", "sideways", "down", "not_evaluable"]
    best_supported_explanation: Literal[
        "market_common_move", "industry_common_move", "company_change",
        "stock_specific_move", "mixed", "unknown",
    ]
    current_weak_or_failed_link: Literal[
        "none", "market_conditions", "new_information",
        "industry_follow_through", "price_and_volume_confirmation",
        "remaining_room", "company_risk", "timing", "execution",
        "stock_selection", "unknown",
    ]
    current_review: str = Field(min_length=1, max_length=600)
    view_change: Literal[
        "first_review", "unchanged", "strengthened", "weakened",
        "invalidated",
    ]
    view_change_reason: str = Field(min_length=1, max_length=300)
    outlook_1_3d: Literal[
        "event_pending", "strengthening", "continuation_possible",
        "range_or_wait", "weakening", "overheated", "invalidated",
    ]
    outlook_reason_plain_language: str = Field(min_length=1, max_length=300)
    tracking_decision: Literal[
        "keep_active_tracking", "stop_active_tracking",
        "complete_observation", "historical_not_applied",
    ]
    tracking_decision_reason: str = Field(min_length=1, max_length=300)
    review_origin: Literal["live", "copied_live_archive", "backfill"]
    final_twenty_day_review: FrozenTwentyDayReviewV1 | None = None


class DailyFormalReviewLedgerV1(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    ledger_version: Literal["daily-formal-reviews-v1"]
    analysis_date: date
    as_of: datetime
    reviews: list[DailyFormalReviewV1]

    @model_validator(mode="after")
    def validate_ledger(self) -> "DailyFormalReviewLedgerV1":
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("as_of must include a timezone")
        if self.analysis_date > self.as_of.date():
            raise ValueError("ledger contains a future analysis date")
        review_ids = [review.episode_id for review in self.reviews]
        if len(review_ids) != len(set(review_ids)):
            raise ValueError("each episode may be reviewed only once")
        return self


class ForwardEpisodeReviewV1(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    episode_id: str = Field(min_length=1)
    original_reason_plain_language: str = Field(min_length=1)
    original_key_risk_plain_language: str = Field(min_length=1)
    current_assessment: Literal[
        "not_yet_tested",
        "partly_supported",
        "supported",
        "weakening",
        "contradicted",
        "insufficient_evidence",
    ]
    best_supported_explanation: Literal[
        "market_common_move",
        "industry_common_move",
        "company_change",
        "stock_specific_move",
        "mixed",
        "unknown",
    ]
    current_weak_or_failed_link: Literal[
        "none",
        "market_conditions",
        "new_information",
        "industry_follow_through",
        "price_and_volume_confirmation",
        "remaining_room",
        "company_risk",
        "timing",
        "execution",
        "stock_selection",
        "unknown",
    ]
    current_review: str = Field(min_length=1)
    comparison_interpretation: str = Field(min_length=1)
    final_twenty_day_review: FrozenTwentyDayReviewV1 | None = None


class ForwardMonitorAlertV2(ForwardMonitorAlertV1):
    outlook_reason_plain_language: str | None = Field(
        default=None,
        min_length=1,
        max_length=300,
    )
    episode_reviews: list[ForwardEpisodeReviewV1] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_episode_reviews(self) -> "ForwardMonitorAlertV2":
        review_ids = [review.episode_id for review in self.episode_reviews]
        if (
            len(review_ids) != len(set(review_ids))
            or set(review_ids) != set(self.episode_ids)
        ):
            raise ValueError("each alert episode must be reviewed exactly once")
        return self


class DailyForwardMonitorReportV2(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    report_version: Literal["daily-forward-monitor-report-v2"]
    analysis_date: date
    as_of: datetime
    market_overview: MarketOverviewV1
    pool_summary: MonitorPoolSummaryV1
    alerts: list[ForwardMonitorAlertV2] = Field(max_length=8)
    unreported_attention_count: int = Field(ge=0)
    routine_summary: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_report(self) -> "DailyForwardMonitorReportV2":
        codes = [alert.ts_code for alert in self.alerts]
        if len(codes) != len(set(codes)):
            raise ValueError("the same stock may appear only once")
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("as_of must include a timezone")
        if self.analysis_date > self.as_of.date():
            raise ValueError("report contains a future analysis date")
        return self


@dataclass(frozen=True)
class RecordSummary:
    status: str
    analysis_date: str
    json_file: str
    markdown_file: str
    alert_count: int
    unreported_attention_count: int


@dataclass(frozen=True)
class DailyFormalReviewRecordSummary:
    status: str
    analysis_date: str
    json_file: str
    review_count: int


def register_episodes(
    *,
    trace_file: Path,
    label: str,
    project_root: Path,
) -> RegisterSummary:
    trace_path = Path(trace_file)
    payload = json.loads(trace_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("trace_version") != TRACE_VERSION:
        raise ValueError("register requires daily-research-trace-v4")
    clean_label = str(label).strip()
    if not clean_label:
        raise ValueError("label is required")

    registry_path = (
        Path(project_root)
        / "local_archive"
        / "forward_monitor"
        / "registered-episodes.json"
    )
    document = _read_registry(registry_path)
    existing = {
        str(episode["episode_id"]): episode
        for episode in document["episodes"]
    }
    additions = _trace_episodes(
        payload,
        label=clean_label,
        source_type="registered_replay",
    )
    selected_registered = 0
    comparators_registered = 0
    for episode in additions:
        episode_id = str(episode["episode_id"])
        if episode_id in existing:
            _fill_missing_original_fields(existing[episode_id], episode)
            continue
        existing[episode_id] = episode
        if (
            _episode_selection_output_class(episode)
            in PUBLIC_FORMAL_OUTPUT_CLASSES
        ):
            selected_registered += 1
        else:
            comparators_registered += 1
    output = {
        "registry_version": REGISTER_VERSION,
        "episodes": [existing[key] for key in sorted(existing)],
    }
    _atomic_write_json(registry_path, output)
    return RegisterSummary(
        status="registered",
        registry_file=str(registry_path),
        selected_registered=selected_registered,
        comparators_registered=comparators_registered,
    )


def _fill_missing_original_fields(
    existing: dict[str, Any],
    source: dict[str, Any],
) -> None:
    for field in (
        "original_research_thesis",
        "original_selection_reason",
        "original_referenced_decisions",
        "original_nearest_alternative_episode_id",
        "data_limitations",
    ):
        if (field not in existing or existing[field] is None) and source.get(
            field
        ) is not None:
            existing[field] = _json_value(source[field])


def prepare_forward_monitor(
    *,
    analysis_date: date,
    as_of: datetime,
    project_root: Path,
) -> PrepareSummary:
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must include a timezone")
    if analysis_date > as_of.date():
        raise ValueError("analysis_date cannot be after as_of")
    if analysis_date == as_of.date() and as_of.hour < 15:
        raise ValueError("analysis_date has not closed at as_of")

    root = Path(project_root)
    monitor_dir = root / "local_archive" / "forward_monitor"
    sessions = _trading_sessions(root, as_of)
    if analysis_date not in sessions:
        raise ValueError("analysis_date is not an available open trading day")

    episodes_by_id: dict[str, dict[str, Any]] = {}
    registered_path = monitor_dir / "registered-episodes.json"
    if registered_path.is_file():
        episodes_by_id.update(
            {
                str(item["episode_id"]): dict(item)
                for item in _read_registry(registered_path)["episodes"]
            }
        )
    formal_dir = root / "local_archive" / "forward_selection"
    for trace_path in sorted(formal_dir.glob("research-trace-*.json")):
        try:
            trace = json.loads(trace_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(trace, dict) or trace.get("trace_version") != TRACE_VERSION:
            continue
        for episode in _trace_episodes(trace, label="formal", source_type="formal"):
            episodes_by_id.setdefault(str(episode["episode_id"]), episode)

    previous = _previous_snapshot(monitor_dir, analysis_date)
    previous_by_id = {
        str(item.get("episode_id")): item
        for item in (previous or {}).get("episodes", [])
    }
    previous_monitor_states = _previous_monitor_states(
        monitor_dir,
        analysis_date,
        previous,
    )
    previous_episode_reviews = _previous_episode_reviews(
        monitor_dir,
        analysis_date,
    )
    previous_daily_reviews, previous_live_reviews, daily_frozen_reviews = (
        _daily_review_history(monitor_dir, analysis_date)
    )
    last_detailed_reviews = _last_detailed_review_dates(
        monitor_dir,
        analysis_date,
    )
    frozen_reviews = _earliest_frozen_reviews(
        monitor_dir,
        analysis_date,
    )
    frozen_reviews = {**frozen_reviews, **daily_frozen_reviews}
    price_by_code = {
        str(row.get("ts_code")): row
        for row in _derived_rows(
            root,
            "price_analysis_context",
            analysis_date,
            "price-analysis-context-v2",
            as_of,
        )
    }
    market_rows = _derived_rows(
        root,
        "market_context",
        analysis_date,
        "market-context-v3",
        as_of,
    )
    sector_by_code = {
        str(row.get("group_code")): row
        for row in _derived_rows(
            root,
            "sector_hotspot",
            analysis_date,
            "sector-hotspot-v3",
            as_of,
        )
    }
    announcement_rows = _fact_rows(root, "announcement", as_of)
    industry_rows = _fact_rows(root, "industry_member", as_of)

    episode_windows: dict[
        str,
        tuple[dict[str, Any], datetime | None, int, str, list[date]],
    ] = {}
    all_path_days: set[date] = set()
    for episode_id in sorted(episodes_by_id):
        base = episodes_by_id[episode_id]
        source_as_of = _as_datetime(base.get("source_as_of"))
        if source_as_of is not None and source_as_of > as_of:
            continue
        action_date = date.fromisoformat(str(base["action_date"]))
        elapsed = [day for day in sessions if action_date <= day <= analysis_date]
        if not elapsed:
            continue
        day_number = len(elapsed)
        if day_number > 31:
            continue
        phase = (
            "primary"
            if day_number <= 20
            else "passive_tail"
            if day_number <= 30
            else "closed"
        )
        path_days = elapsed[: min(day_number, 30)]
        episode_windows[episode_id] = (
            base,
            source_as_of,
            day_number,
            phase,
            path_days,
        )
        all_path_days.update(path_days)

    price_path_cache = _daily_price_cache(
        root,
        sorted(all_path_days),
        as_of,
    )
    observations: list[dict[str, Any]] = []
    for episode_id in sorted(episode_windows):
        base, source_as_of, day_number, phase, path_days = episode_windows[
            episode_id
        ]
        group_code = base.get("original_group_code") or _formation_industry(
            industry_rows,
            str(base["ts_code"]),
            date.fromisoformat(str(base["formation_date"])),
            source_as_of,
        )
        observation = _episode_observation(
            price_path_cache=price_path_cache,
            base=base,
            analysis_date=analysis_date,
            as_of=as_of,
            day_number=day_number,
            phase=phase,
            path_days=path_days,
            price_row=(price_by_code.get(str(base["ts_code"])) if phase != "closed" else None),
            sector_row=(sector_by_code.get(str(group_code)) if group_code else None),
            group_code=group_code,
            announcements=announcement_rows,
            previous_episode=previous_by_id.get(episode_id),
            previous_as_of=(previous or {}).get("as_of"),
            previous_monitor_state=previous_monitor_states.get(episode_id),
            previous_episode_review=previous_episode_reviews.get(episode_id),
            market_context_available=bool(market_rows),
            frozen_twenty_day_review=frozen_reviews.get(episode_id),
        )
        if (
            _episode_selection_output_class(observation)
            in PUBLIC_FORMAL_OUTPUT_CLASSES
            and str(observation.get("role")) == "selected"
        ):
            latest_live = previous_live_reviews.get(episode_id)
            tracking_status = _tracking_status(
                observation,
                latest_live,
            )
            last_detailed = last_detailed_reviews.get(episode_id)
            observation.update(
                tracking_status=tracking_status,
                tracking_exit_date=(
                    latest_live.get("_tracking_exit_date")
                    if latest_live is not None
                    else None
                ),
                tracking_exit_reason=(
                    latest_live.get("_tracking_exit_reason")
                    if latest_live is not None
                    else None
                ),
                previous_daily_formal_review=(
                    previous_daily_reviews.get(episode_id)
                ),
                last_detailed_review_date=(
                    last_detailed.isoformat() if last_detailed else None
                ),
                days_since_last_detailed_review=(
                    sum(
                        last_detailed < session <= analysis_date
                        for session in sessions
                    )
                    if last_detailed is not None
                    else None
                ),
            )
        observations.append(observation)

    _attach_pair_contexts(observations)
    attention_stocks = _aggregate_attention(observations)
    required_final_review_episode_ids = sorted(
        str(item["episode_id"])
        for item in observations
        if item["monitor_phase"] != "closed"
        and _episode_selection_output_class(item)
        in PUBLIC_FORMAL_OUTPUT_CLASSES
        and int(item["day_number"]) >= 20
        and item.get("frozen_twenty_day_review") is None
    )
    open_episodes = [item for item in observations if item["monitor_phase"] != "closed"]
    formal_episodes = [
        item
        for item in observations
        if _episode_selection_output_class(item)
        in PUBLIC_FORMAL_OUTPUT_CLASSES
        and str(item.get("role")) == "selected"
    ]
    daily_review_episode_ids = sorted(
        str(item["episode_id"])
        for item in formal_episodes
        if _needs_daily_formal_review(item, previous_live_reviews.get(str(item["episode_id"])))
    )
    daily_review_id_set = set(daily_review_episode_ids)
    evaluation_only_episode_ids = sorted(
        str(item["episode_id"])
        for item in formal_episodes
        if item.get("tracking_status") == "evaluation_only"
    )
    detailed_review_candidate_codes = sorted(
        {
            str(item["ts_code"])
            for item in formal_episodes
            if str(item["episode_id"]) in daily_review_id_set
        }
    )
    summary_payload = {
        "open_episode_count": len(open_episodes),
        "distinct_stock_count": len({item["ts_code"] for item in open_episodes}),
        "attention_stock_count": len(attention_stocks),
        "selected_count": len(
            {
                str(item["ts_code"])
                for item in open_episodes
                if _episode_selection_output_class(item)
                in PUBLIC_FORMAL_OUTPUT_CLASSES
            }
        ),
        "comparator_count": sum(item["role"] == "comparator" for item in open_episodes),
        "primary_count": sum(item["monitor_phase"] == "primary" for item in observations),
        "passive_tail_count": sum(item["monitor_phase"] == "passive_tail" for item in observations),
        "closed_count": sum(item["monitor_phase"] == "closed" for item in observations),
        "active_tracking_count": sum(
            item.get("tracking_status") == "active"
            for item in formal_episodes
        ),
        "evaluation_only_count": sum(
            item.get("tracking_status") == "evaluation_only"
            for item in formal_episodes
        ),
        "completed_formal_count": sum(
            item.get("tracking_status") == "completed"
            for item in formal_episodes
        ),
        "daily_review_episode_count": len(daily_review_episode_ids),
        "detailed_review_stock_count": min(
            8,
            len(detailed_review_candidate_codes),
        ),
    }
    snapshot_path = monitor_dir / f"snapshot-{analysis_date.isoformat()}.json"
    _atomic_write_json(
        snapshot_path,
        {
            "snapshot_version": SNAPSHOT_VERSION,
            "analysis_date": analysis_date.isoformat(),
            "as_of": as_of.isoformat(),
            "market_context": market_rows[0] if market_rows else None,
            "summary": summary_payload,
            "episodes": observations,
            "attention_stocks": attention_stocks,
            "required_final_review_episode_ids": (
                required_final_review_episode_ids
            ),
            "daily_review_episode_ids": daily_review_episode_ids,
            "evaluation_only_episode_ids": evaluation_only_episode_ids,
            "detailed_review_candidate_codes": (
                detailed_review_candidate_codes
            ),
        },
    )
    return PrepareSummary(
        status="prepared",
        analysis_date=analysis_date.isoformat(),
        snapshot_file=str(snapshot_path),
        **summary_payload,
    )


def record_daily_formal_reviews(
    *,
    snapshot_file: Path,
    review_file: Path,
    project_root: Path,
) -> DailyFormalReviewRecordSummary:
    snapshot_path = Path(snapshot_file)
    pending_path = Path(review_file)
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    if (
        not isinstance(snapshot, dict)
        or snapshot.get("snapshot_version") != SNAPSHOT_VERSION
    ):
        raise ValueError("snapshot must be forward-monitor-snapshot-v1")

    ledger = DailyFormalReviewLedgerV1.model_validate_json(
        pending_path.read_text(encoding="utf-8")
    )
    if ledger.analysis_date.isoformat() != str(snapshot.get("analysis_date")):
        raise ValueError("daily reviews analysis_date does not match snapshot")
    snapshot_as_of = _as_datetime(snapshot.get("as_of"))
    if snapshot_as_of is None or ledger.as_of != snapshot_as_of:
        raise ValueError("daily reviews as_of does not match snapshot")

    expected_ids = [
        str(value) for value in snapshot.get("daily_review_episode_ids", [])
    ]
    review_ids = [review.episode_id for review in ledger.reviews]
    if set(review_ids) != set(expected_ids) or len(review_ids) != len(expected_ids):
        raise ValueError(
            "daily review episode ids must exactly match snapshot"
        )
    episodes = {
        str(item.get("episode_id")): item
        for item in snapshot.get("episodes", [])
        if isinstance(item, dict) and item.get("episode_id")
    }
    for review in ledger.reviews:
        episode = episodes.get(review.episode_id)
        if episode is None:
            raise ValueError(f"daily review episode does not exist: {review.episode_id}")
        if (
            _episode_selection_output_class(episode)
            not in PUBLIC_FORMAL_OUTPUT_CLASSES
            or str(episode.get("role")) != "selected"
        ):
            raise ValueError("daily reviews only accept formal selections")
        day_number = int(episode.get("day_number", 0))
        if review.day_number != day_number:
            raise ValueError("daily review day_number does not match snapshot")
        if review.checkpoint != episode.get("checkpoint"):
            raise ValueError("daily review checkpoint does not match snapshot")

        historical = review.review_origin in {
            "copied_live_archive", "backfill",
        }
        if historical and review.tracking_decision != "historical_not_applied":
            raise ValueError(
                "copied and backfill reviews must use historical_not_applied"
            )
        if not historical and review.tracking_decision == "historical_not_applied":
            raise ValueError("live reviews cannot use historical_not_applied")
        if review.tracking_decision == "stop_active_tracking" and not (
            review.current_assessment == "contradicted"
            or (
                review.current_weak_or_failed_link == "execution"
                and _number(episode.get("entry_open")) is None
            )
        ):
            raise ValueError(
                "stop_active_tracking requires contradiction or non-execution"
            )
        if (
            review.tracking_decision == "complete_observation"
            and day_number not in {20, 25, 30}
        ):
            raise ValueError(
                "complete_observation is allowed only at an observation endpoint"
            )
        if day_number == 30 and review.tracking_decision not in {
            "complete_observation", "historical_not_applied",
        }:
            raise ValueError("D30 must complete an extended observation")

        final_review = (
            review.final_twenty_day_review.model_dump(mode="json")
            if review.final_twenty_day_review is not None
            else None
        )
        frozen_raw = episode.get("frozen_twenty_day_review")
        if day_number < 20 and final_review is not None:
            raise ValueError("a final review is not allowed before D20")
        if day_number >= 20 and final_review is None:
            raise ValueError("a final review is required at and after D20")
        if frozen_raw is not None:
            frozen = FrozenTwentyDayReviewV1.model_validate(
                frozen_raw
            ).model_dump(mode="json")
            if final_review != frozen:
                raise ValueError(
                    f"final twenty day review is frozen: {review.episode_id}"
                )

    output = ledger.model_dump(mode="json")
    monitor_dir = Path(project_root) / "local_archive" / "forward_monitor"
    final_path = (
        monitor_dir
        / f"daily-formal-reviews-{ledger.analysis_date.isoformat()}.json"
    )
    if final_path.is_file():
        try:
            existing = DailyFormalReviewLedgerV1.model_validate_json(
                final_path.read_text(encoding="utf-8")
            ).model_dump(mode="json")
        except (OSError, ValueError):
            existing = None
        if existing == output:
            pending_path.unlink()
            return DailyFormalReviewRecordSummary(
                status="already_recorded",
                analysis_date=ledger.analysis_date.isoformat(),
                json_file=str(final_path),
                review_count=len(ledger.reviews),
            )
        return DailyFormalReviewRecordSummary(
            status="review_conflict",
            analysis_date=ledger.analysis_date.isoformat(),
            json_file=str(final_path),
            review_count=len(ledger.reviews),
        )

    _atomic_write_json(final_path, output)
    pending_path.unlink()
    return DailyFormalReviewRecordSummary(
        status="recorded",
        analysis_date=ledger.analysis_date.isoformat(),
        json_file=str(final_path),
        review_count=len(ledger.reviews),
    )


def record_forward_monitor(
    *,
    snapshot_file: Path,
    report_file: Path,
    project_root: Path,
) -> RecordSummary:
    snapshot_path = Path(snapshot_file)
    pending_path = Path(report_file)
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    if not isinstance(snapshot, dict) or snapshot.get("snapshot_version") != SNAPSHOT_VERSION:
        raise ValueError("snapshot must be forward-monitor-snapshot-v1")
    raw_report = json.loads(pending_path.read_text(encoding="utf-8"))
    report = DailyForwardMonitorReportV2.model_validate(raw_report)
    if any(
        alert.outlook_reason_plain_language is None
        for alert in report.alerts
    ):
        raise ValueError("each new alert must include an outlook reason")
    if report.analysis_date.isoformat() != str(snapshot.get("analysis_date")):
        raise ValueError("report analysis_date does not match snapshot")
    snapshot_as_of = _as_datetime(snapshot.get("as_of"))
    if snapshot_as_of is None or report.as_of != snapshot_as_of:
        raise ValueError("report as_of does not match snapshot")

    snapshot_summary = snapshot.get("summary", {})
    expected_pool_summary = {
        key: int(snapshot_summary.get(key, 0))
        for key in (
            "open_episode_count",
            "distinct_stock_count",
            "selected_count",
            "comparator_count",
            "primary_count",
            "passive_tail_count",
            "attention_stock_count",
        )
    }
    expected_pool_summary["routine_stock_count"] = (
        expected_pool_summary["distinct_stock_count"]
        - expected_pool_summary["attention_stock_count"]
    )
    if report.pool_summary.model_dump() != expected_pool_summary:
        raise ValueError("report pool_summary does not match snapshot")

    attention = {
        str(item.get("ts_code")): item
        for item in snapshot.get("attention_stocks", [])
        if isinstance(item, dict)
    }
    episodes = {
        str(item.get("episode_id")): item
        for item in snapshot.get("episodes", [])
        if isinstance(item, dict)
    }
    daily_ledger_path = (
        Path(project_root)
        / "local_archive"
        / "forward_monitor"
        / f"daily-formal-reviews-{report.analysis_date.isoformat()}.json"
    )
    new_daily_workflow = (
        "daily_review_episode_ids" in snapshot
        and daily_ledger_path.is_file()
    )
    daily_reviews: dict[str, DailyFormalReviewV1] = {}
    daily_ledger: DailyFormalReviewLedgerV1 | None = None
    if new_daily_workflow:
        daily_ledger = DailyFormalReviewLedgerV1.model_validate_json(
            daily_ledger_path.read_text(encoding="utf-8")
        )
        if (
            daily_ledger.analysis_date != report.analysis_date
            or daily_ledger.as_of != report.as_of
        ):
            raise ValueError("daily formal review ledger does not match report")
        daily_reviews = {
            review.episode_id: review for review in daily_ledger.reviews
        }
        expected_daily_ids = {
            str(value)
            for value in snapshot.get("daily_review_episode_ids", [])
        }
        if set(daily_reviews) != expected_daily_ids:
            raise ValueError("daily formal review ledger does not match snapshot")
        expected_detail_count = int(
            snapshot_summary.get("detailed_review_stock_count", 0)
        )
        if len(report.alerts) != expected_detail_count:
            raise ValueError(
                "detailed review stock count does not match snapshot"
            )
    reported_episode_ids: set[str] = set()
    for alert in report.alerts:
        attention_item = attention.get(alert.ts_code)
        if new_daily_workflow:
            expected_code_ids = {
                episode_id
                for episode_id in daily_reviews
                if str(episodes.get(episode_id, {}).get("ts_code"))
                == alert.ts_code
            }
            if not expected_code_ids:
                raise ValueError(
                    f"detail stock is not a daily formal review: {alert.ts_code}"
                )
            expected_name = next(
                str(episodes[episode_id].get("name", ""))
                for episode_id in expected_code_ids
            )
            if alert.name != expected_name:
                raise ValueError(
                    f"alert stock name does not match snapshot: {alert.ts_code}"
                )
        else:
            if attention_item is None:
                raise ValueError(f"alert stock is not in snapshot attention set: {alert.ts_code}")
            if alert.name != str(attention_item.get("name", "")):
                raise ValueError(f"alert stock name does not match snapshot: {alert.ts_code}")
        if len(alert.episode_ids) != len(set(alert.episode_ids)):
            raise ValueError(f"alert contains duplicate episode ids: {alert.ts_code}")
        if new_daily_workflow:
            if set(alert.episode_ids) != expected_code_ids:
                raise ValueError(
                    f"alert must include all stock daily review episodes: {alert.ts_code}"
                )
        else:
            attention_episode_ids = {
                str(value)
                for value in attention_item.get("episode_ids", [])
            }
            if set(alert.episode_ids) != attention_episode_ids:
                raise ValueError(
                    f"alert must include all stock attention episodes: {alert.ts_code}"
                )
        referenced: list[dict[str, Any]] = []
        reviews_by_id = {
            review.episode_id: review
            for review in alert.episode_reviews
        }
        reported_episode_ids.update(reviews_by_id)
        for episode_id in alert.episode_ids:
            episode = episodes.get(episode_id)
            if episode is None:
                raise ValueError(f"alert episode does not exist: {episode_id}")
            if str(episode.get("ts_code")) != alert.ts_code:
                raise ValueError(f"alert episode stock mismatch: {episode_id}")
            referenced.append(episode)
            review = reviews_by_id[episode_id]
            final_review = (
                review.final_twenty_day_review.model_dump(mode="json")
                if review.final_twenty_day_review is not None
                else None
            )
            day_number = int(episode["day_number"])
            role = str(episode.get("role"))
            output_class = _episode_selection_output_class(episode)
            is_formal_selection = (
                output_class in PUBLIC_FORMAL_OUTPUT_CLASSES
            )
            if not is_formal_selection and final_review is not None:
                raise ValueError(
                    "only a confirmed active selection may have a final recommendation review"
                )
            if is_formal_selection and day_number < 20 and final_review is not None:
                raise ValueError(
                    "a final decision review is not allowed before the twentieth trading day"
                )
            if is_formal_selection and day_number >= 20 and final_review is None:
                raise ValueError(
                    "a final decision review is required at or after the twentieth trading day"
                )
            frozen_raw = episode.get("frozen_twenty_day_review")
            if frozen_raw is not None:
                frozen = FrozenTwentyDayReviewV1.model_validate(
                    frozen_raw
                ).model_dump(mode="json")
                if final_review != frozen:
                    raise ValueError(
                        f"final twenty day review is frozen: {episode_id}"
                    )
            _validate_pair_context(episode, episodes)
            if (
                is_formal_selection
                and final_review is not None
                and final_review["decision_review"]
                == "direction_right_stock_wrong"
                and (episode.get("pair_context") or {}).get("pair_status")
                != "complete"
            ):
                raise ValueError(
                    "direction_right_stock_wrong requires a complete pair"
                )
            if new_daily_workflow:
                daily = daily_reviews[episode_id]
                detailed_values = {
                    "current_review": review.current_review,
                    "current_assessment": review.current_assessment,
                    "best_supported_explanation": (
                        review.best_supported_explanation
                    ),
                    "current_weak_or_failed_link": (
                        review.current_weak_or_failed_link
                    ),
                    "final_twenty_day_review": final_review,
                }
                daily_values = {
                    "current_review": daily.current_review,
                    "current_assessment": daily.current_assessment,
                    "best_supported_explanation": (
                        daily.best_supported_explanation
                    ),
                    "current_weak_or_failed_link": (
                        daily.current_weak_or_failed_link
                    ),
                    "final_twenty_day_review": (
                        daily.final_twenty_day_review.model_dump(mode="json")
                        if daily.final_twenty_day_review is not None
                        else None
                    ),
                }
                if detailed_values != daily_values or (
                    alert.outlook_1_3d != daily.outlook_1_3d
                    or alert.outlook_reason_plain_language
                    != daily.outlook_reason_plain_language
                ):
                    raise ValueError(
                        f"detail contradicts daily formal review: {episode_id}"
                    )
        referenced_roles = {str(item.get("role")) for item in referenced}
        valid_roles = [
            role
            for role in ("selected", "comparator")
            if role in referenced_roles
        ]
        if alert.roles != valid_roles:
            raise ValueError(f"alert roles do not match referenced episodes: {alert.ts_code}")
        valid_days = sorted({int(item["day_number"]) for item in referenced})
        if alert.day_numbers != valid_days:
            raise ValueError(f"alert day numbers do not match referenced episodes: {alert.ts_code}")
        valid_engines = sorted(
            {
                str(item["original_engine_type"])
                for item in referenced
                if item.get("original_engine_type")
            }
        )
        if alert.original_engine_types != valid_engines:
            raise ValueError(f"alert original engines do not match referenced episodes: {alert.ts_code}")

    required_final_review_episode_ids = {
        str(value)
        for value in snapshot.get("required_final_review_episode_ids", [])
    }
    missing_required = required_final_review_episode_ids - reported_episode_ids
    if missing_required and not new_daily_workflow:
        raise ValueError(
            "report is missing required final review episodes: "
            + ",".join(sorted(missing_required))
        )
    mandatory_formal_codes = {
        str(episode.get("ts_code"))
        for episode in episodes.values()
        if (
            _episode_selection_output_class(episode)
            in PUBLIC_FORMAL_OUTPUT_CLASSES
            and set(episode.get("attention_reasons") or [])
            & MANDATORY_FORMAL_REVIEW_REASONS
        )
    }
    reported_codes = {alert.ts_code for alert in report.alerts}
    if new_daily_workflow:
        _validate_detailed_review_priority(
            snapshot=snapshot,
            daily_reviews=daily_reviews,
            reported_codes=reported_codes,
        )
    elif len(mandatory_formal_codes) <= 8:
        missing_formal = mandatory_formal_codes - reported_codes
        if missing_formal:
            raise ValueError(
                "report is missing mandatory formal attention stocks: "
                + ",".join(sorted(missing_formal))
            )
    elif reported_codes - mandatory_formal_codes:
        raise ValueError(
            "report contains optional alerts while more than eight "
            "mandatory formal attention stocks require priority"
        )


    expected_unreported = len(set(attention) - reported_codes)
    if report.unreported_attention_count != expected_unreported:
        raise ValueError(
            "report unreported_attention_count does not match snapshot"
        )

    output = report.model_dump(mode="json")
    monitor_dir = Path(project_root) / "local_archive" / "forward_monitor"
    json_path = monitor_dir / f"monitor-report-{report.analysis_date.isoformat()}.json"
    markdown_path = monitor_dir / f"monitor-report-{report.analysis_date.isoformat()}.md"
    if json_path.is_file():
        try:
            existing_raw = json.loads(json_path.read_text(encoding="utf-8"))

            if existing_raw.get("report_version") == (
                "daily-forward-monitor-report-v2"
            ):
                existing = DailyForwardMonitorReportV2.model_validate(
                    existing_raw
                ).model_dump(mode="json")
            elif existing_raw.get("report_version") == (
                "daily-forward-monitor-report-v1"
            ):
                existing = DailyForwardMonitorReportV1.model_validate(
                    existing_raw
                ).model_dump(mode="json")
            else:
                existing = None
        except (OSError, json.JSONDecodeError, ValueError):
            existing = None
        if existing == output:
            if not markdown_path.is_file():
                _atomic_write_text(
                    markdown_path,
                    _render_markdown(report, snapshot, daily_ledger),
                )
            pending_path.unlink()
            return RecordSummary(
                status="already_recorded",
                analysis_date=report.analysis_date.isoformat(),
                json_file=str(json_path),
                markdown_file=str(markdown_path),
                alert_count=len(report.alerts),
                unreported_attention_count=report.unreported_attention_count,
            )
        return RecordSummary(
            status="report_conflict",
            analysis_date=report.analysis_date.isoformat(),
            json_file=str(json_path),
            markdown_file=str(markdown_path),
            alert_count=len(report.alerts),
            unreported_attention_count=report.unreported_attention_count,
        )

    _atomic_write_json(json_path, output)
    _atomic_write_text(
        markdown_path,
        _render_markdown(report, snapshot, daily_ledger),
    )
    pending_path.unlink()
    return RecordSummary(
        status="recorded",
        analysis_date=report.analysis_date.isoformat(),
        json_file=str(json_path),
        markdown_file=str(markdown_path),
        alert_count=len(report.alerts),
        unreported_attention_count=report.unreported_attention_count,
    )


def _validate_pair_context(
    episode: dict[str, Any],
    episodes: dict[str, dict[str, Any]],
) -> None:
    context = episode.get("pair_context")
    if not isinstance(context, dict) or context.get("pair_status") != "complete":
        return
    paired_id = str(context.get("paired_episode_id", ""))
    paired = episodes.get(paired_id)
    if paired is None:
        raise ValueError(f"paired episode does not exist: {paired_id}")
    if (
        str(context.get("paired_name", "")) != str(paired.get("name", ""))
        or int(context.get("paired_day_number", -1))
        != int(paired.get("day_number", -2))
        or episode.get("formation_date") != paired.get("formation_date")
        or episode.get("action_date") != paired.get("action_date")
        or episode.get("analysis_date") != paired.get("analysis_date")
        or episode.get("day_number") != paired.get("day_number")
        or episode.get("ts_code") == paired.get("ts_code")
    ):
        raise ValueError(
            f"paired episode identity or window mismatch: {paired_id}"
        )


def _validate_detailed_review_priority(
    *,
    snapshot: dict[str, Any],
    daily_reviews: dict[str, DailyFormalReviewV1],
    reported_codes: set[str],
) -> None:
    episodes = {
        str(item.get("episode_id")): item
        for item in snapshot.get("episodes", [])
        if isinstance(item, dict) and item.get("episode_id")
    }
    candidates: dict[str, list[tuple[dict[str, Any], DailyFormalReviewV1]]] = {}
    for episode_id, review in daily_reviews.items():
        episode = episodes.get(episode_id)
        if episode is None:
            continue
        candidates.setdefault(str(episode.get("ts_code")), []).append(
            (episode, review)
        )
    if reported_codes - set(candidates):
        raise ValueError("detail report contains a non-candidate stock")
    omitted_codes = set(candidates) - reported_codes
    if not omitted_codes:
        return

    mandatory_codes = {
        code
        for code, items in candidates.items()
        if any(
            review.tracking_decision == "stop_active_tracking"
            or review.day_number == 20
            or review.view_change
            in {"strengthened", "weakened", "invalidated"}
            for _, review in items
        )
    }
    if len(mandatory_codes) <= len(reported_codes) and not (
        mandatory_codes <= reported_codes
    ):
        raise ValueError(
            "detail report omits a stop, D20, or key view change"
        )


def _public_formal_episode_ids(
    alert: ForwardMonitorAlertV2,
    episodes: dict[str, dict[str, Any]],
) -> list[str]:
    return [
        episode_id
        for episode_id in alert.episode_ids
        if episode_id in episodes
        and _episode_selection_output_class(episodes[episode_id])
        in PUBLIC_FORMAL_OUTPUT_CLASSES
    ]


def _render_markdown(
    report: DailyForwardMonitorReportV2,
    snapshot: dict[str, Any],
    daily_ledger: DailyFormalReviewLedgerV1 | None = None,
) -> str:
    overview = report.market_overview
    pool = report.pool_summary
    episodes = {
        str(item.get("episode_id")): item
        for item in snapshot.get("episodes", [])
        if isinstance(item, dict)
    }
    public_alerts = [
        (alert, _public_formal_episode_ids(alert, episodes))
        for alert in report.alerts
    ]
    public_alerts = [
        (alert, episode_ids)
        for alert, episode_ids in public_alerts
        if episode_ids
    ]
    lines = [
        f"# {report.analysis_date.isoformat()} 正式推荐股票的今日复盘",
        "",
        "## 今天的市场情况",
        "",
        f"{overview.what_changed.rstrip('。！？!? ；; ')}。{overview.implication_for_monitored_stocks}",
        "",
    ]
    daily_by_id = (
        {review.episode_id: review for review in daily_ledger.reviews}
        if daily_ledger is not None
        else {}
    )
    if daily_ledger is None:
        lines.extend(["## 正式推荐股票的今日复盘", ""])
    if daily_ledger is not None:
        active_items = [
            (episode, daily_by_id[str(episode["episode_id"])])
            for episode in episodes.values()
            if episode.get("tracking_status") == "active"
            and str(episode.get("episode_id")) in daily_by_id
        ]
        active_items.sort(
            key=lambda item: (
                str(item[0].get("action_date", "")),
                str(item[0].get("ts_code", "")),
                str(item[0].get("episode_id", "")),
            )
        )
        lines.extend(
            [
                "## 所有主动推荐的今日结论",
                "",
                "| 股票 | 当前观察日 | 当前涨跌 | 当前走势 | 是否仍在预期内 | 未来1—3日 | 主动跟踪 |",
                "|---|---:|---:|---|---|---|---|",
            ]
        )
        for episode, review in active_items:
            current = _number(
                episode.get("current_close_return_since_entry")
            )
            current_text = (
                _format_return(current)
                if current is not None
                else "无法计算"
            )
            tracking_text = (
                "继续"
                if review.tracking_decision == "keep_active_tracking"
                else "今日停止"
            )
            lines.append(
                "| "
                f"{episode.get('name')}（{episode.get('ts_code')}） | "
                f"{review.day_number} | {current_text} | "
                f"{_daily_path_label(review.current_path)} | "
                f"{_daily_assessment_label(review.current_assessment)} | "
                f"{_daily_outlook_label(review.outlook_1_3d)} | "
                f"{tracking_text} |"
            )
        if not active_items:
            lines.append("| 今日没有仍在主动跟踪的正式推荐 | — | — | — | — | — | — |")
        lines.extend(
            [
                "",
                f"## 今天重点复盘的{len(public_alerts)}只股票",
                "",
            ]
        )
    formal_primary_count = sum(
        _episode_selection_output_class(item) in PUBLIC_FORMAL_OUTPUT_CLASSES
        and item.get("monitor_phase") == "primary"
        for item in episodes.values()
    )
    formal_tail_count = sum(
        _episode_selection_output_class(item) in PUBLIC_FORMAL_OUTPUT_CLASSES
        and item.get("monitor_phase") == "passive_tail"
        for item in episodes.values()
    )
    if not public_alerts:
        lines.extend(
            [
                "今天没有被明确推荐过、同时又出现需要说明变化的股票。",
                "",
            ]
        )
    for alert, episode_ids in public_alerts:
        reviews = {item.episode_id: item for item in alert.episode_reviews}
        status_paragraphs: list[str] = []
        update_paragraphs: list[str] = []
        change_paragraphs: list[str] = []
        final_paragraphs: list[str] = []
        multiple = len(episode_ids) > 1
        for episode_id in episode_ids:
            episode = episodes[episode_id]
            review = reviews[episode_id]
            daily = daily_by_id[episode_id] if daily_ledger is not None else None
            day_number = int(episode["day_number"])
            action = date.fromisoformat(str(episode["action_date"]))
            action_text = f"{action.year}年{action.month}月{action.day}日"
            day_text = (
                f"当前D{day_number}/20"
                if day_number <= 20
                else f"延长观察第{day_number - 20}天"
            )
            prefix = (
                f"{action_text}推荐（{day_text}）："
                if multiple else ""
            )
            status_paragraphs.append(_render_compact_review_status(episode))
            if day_number == 1:
                status_paragraphs.append(_render_first_day_background(episode, review))

            update_paragraphs.append(
                f"{prefix}{daily.current_review if daily is not None else review.current_review}"
            )
            if alert.alert_type == "late_activation" and day_number > 20:
                update_paragraphs.append(
                    f"{prefix}这只股票在前20个交易日结束后才开始明显走强，"
                    "因此不会改变前20天的原评价结果。"
                )
            change_paragraphs.append(f"{prefix}{_render_view_change(daily)}")
            final = (
                daily.final_twenty_day_review
                if daily is not None else review.final_twenty_day_review
            )
            if final is not None:
                final_paragraphs.append(
                    f"{prefix}{_render_final_twenty_day_review(episode, final)}"
                )

        lines.extend(
            [
                f"### {alert.name}（{alert.ts_code}）",
                "",
                "\n\n".join(status_paragraphs),
                "",
                "**今天发生了什么**",
                "",
                "\n\n".join(update_paragraphs),
                "",
                "**相比上次判断**",
                "",
                "\n\n".join(change_paragraphs),
                "",
                "**接下来1—3个交易日**",
                "",
                _render_public_outlook(alert),
                "",
            ]
        )
        if final_paragraphs:
            lines.extend(
                ["**20个交易日最终复盘**", "", "\n\n".join(final_paragraphs), ""]
            )
    lines.extend(
        [
            "## 目前还在跟踪多少只",
            "",
            (
                _render_tracking_counts(snapshot, episodes, daily_ledger)
                if daily_ledger is not None
                else f"仍开放 {pool.selected_count} 只已确认正式推荐股票；入选后的前20个交易日有 {formal_primary_count} 条正式记录，之后继续低成本观察的有 {formal_tail_count} 条正式记录。"
            ),
            "",
        ]
    )
    return "\n".join(lines)


def _render_compact_review_status(episode: dict[str, Any]) -> str:
    action = date.fromisoformat(str(episode["action_date"]))
    review_day = int(episode["day_number"])
    day_text = (
        f"当前D{review_day}/20"
        if review_day <= 20
        else f"20日核心观察已完成 · 延长观察第{review_day - 20}天"
    )
    parts = [
        f"当前状态：{action.year}年{action.month}月{action.day}日入选 · {day_text}"
    ]
    if "entry_open" in episode and _number(episode.get("entry_open")) is None:
        parts.append("没有可靠的推荐参考价，暂时无法计算涨跌")
    else:
        current = _number(episode.get("current_close_return_since_entry"))
        highest = _number(episode.get("current_max_close_return_since_entry"))
        lowest = _number(episode.get("current_mae_since_entry"))
        if current is not None:
            parts.append(f"收盘较推荐参考价{_plain_movement(current)}")
        if highest is not None:
            parts.append(f"期间最高收盘{_plain_movement(highest)}")
        if lowest is not None:
            parts.append(_plain_low_point(lowest))
    return "；".join(parts) + "。"


def _render_first_day_background(
    episode: dict[str, Any], review: ForwardEpisodeReviewV1,
) -> str:
    if "missing_original_research_thesis" in (episode.get("data_limitations") or []):
        return (
            "原推荐背景：当时留下的原始判断不完整，因此这次只能复盘价格表现，"
            "不能逐项审查当时的理由。"
        )
    # Presentation-only sentence clipping; the frozen source fields stay intact.
    reason = re.split(r"[。！？!?\n]", review.original_reason_plain_language, maxsplit=1)[0]
    risk = re.split(r"[。！？!?\n]", review.original_key_risk_plain_language, maxsplit=1)[0]
    return f"原推荐背景：{reason.rstrip('；; ')}；{risk.rstrip('；; ')}。"


def _render_view_change(daily: DailyFormalReviewV1 | None) -> str:
    if daily is None:
        return "历史记录未保存与上次判断的比较。"
    label = {
        "first_review": "",
        "unchanged": "判断没有实质变化",
        "strengthened": "判断增强",
        "weakened": "判断减弱",
        "invalidated": "原判断已被事实否定",
    }[daily.view_change]
    return f"{label}：{daily.view_change_reason}" if label else daily.view_change_reason


def _render_tracking_counts(
    snapshot: dict[str, Any],
    episodes: dict[str, dict[str, Any]],
    daily_ledger: DailyFormalReviewLedgerV1,
) -> str:
    summary = snapshot.get("summary", {})
    active = int(summary.get("active_tracking_count", 0))
    evaluation = int(summary.get("evaluation_only_count", 0))
    completed = int(summary.get("completed_formal_count", 0))
    for review in daily_ledger.reviews:
        if review.tracking_decision == "historical_not_applied":
            continue
        status = str(episodes.get(review.episode_id, {}).get("tracking_status"))
        if review.tracking_decision == "stop_active_tracking" and status == "active":
            active -= 1
            evaluation += 1
        elif review.tracking_decision == "complete_observation":
            if status == "active":
                active -= 1
            elif status == "evaluation_only":
                evaluation -= 1
            completed += 1
    return (
        f"主动跟踪：{active}只  "
        f"\n仅保留评价：{evaluation}条  "
        f"\n已完成：{completed}条"
    )


def _daily_path_label(value: str) -> str:
    return {
        "up": "向上",
        "sideways": "横盘",
        "down": "向下",
        "not_evaluable": "无法评价",
    }[value]


def _daily_assessment_label(value: str) -> str:
    return {
        "not_yet_tested": "尚未充分检验",
        "partly_supported": "仍在原推荐预期内",
        "supported": "仍在原推荐预期内",
        "weakening": "预期正在减弱但尚未被否定",
        "contradicted": "已超出原推荐预期",
        "insufficient_evidence": "现有事实不足以判断",
    }[value]


def _daily_outlook_label(value: str) -> str:
    return {
        "event_pending": "暂时无法判断",
        "strengthening": "向上",
        "continuation_possible": "震荡偏上",
        "range_or_wait": "横盘",
        "weakening": "震荡偏下",
        "overheated": "高位震荡偏下",
        "invalidated": "向下",
    }[value]


def _render_current_assessment(value: str) -> str:
    labels = {
        "not_yet_tested": "推荐后的事实还不足以检验当初判断。",
        "partly_supported": "部分预期已经发生，但仍有关键部分需要验证。",
        "supported": "当初的核心预期目前得到支持。",
        "weakening": "当初的核心判断已经明显减弱。",
        "contradicted": "推荐后的事实与当初核心预期相反，原判断已经不成立。",
        "insufficient_evidence": "现有资料不足，暂时无法可靠评价当初判断。",
    }
    return labels[value]


def _outlook_confirmation_label(outlook: str) -> str:
    return {
        "strengthening": "会进一步支持向上判断的表现",
        "continuation_possible": "会进一步支持震荡偏上判断的表现",
        "range_or_wait": "会继续支持横盘判断的表现",
        "weakening": "会进一步支持偏弱判断的表现",
        "overheated": "会进一步支持高位震荡偏下判断的表现",
        "invalidated": "会进一步支持偏弱判断的表现",
        "event_pending": "会继续维持暂时无法判断的事实",
    }[outlook]


def _render_public_outlook(alert: ForwardMonitorAlertV2) -> str:
    baselines = {
        "event_pending": "目前没有足够的可交易事实判断方向",
        "strengthening": "未来1—3个交易日更可能继续向上",
        "continuation_possible": "未来1—3个交易日更可能震荡偏上",
        "range_or_wait": "未来1—3个交易日更可能横盘整理",
        "weakening": "未来1—3个交易日更可能震荡偏下",
        "overheated": "未来1—3个交易日更可能高位震荡，短线偏下",
        "invalidated": "未来1—3个交易日更可能继续偏弱",
    }
    confirmation = alert.confirmation_condition.rstrip("。！？!? ；; ")
    invalidation = alert.invalidation_condition.rstrip("。！？!? ；; ")
    paragraphs = [f"{baselines[alert.outlook_1_3d]}。"]
    if alert.outlook_reason_plain_language is not None:
        reason = alert.outlook_reason_plain_language.rstrip(
            "。！？!? ；; "
        )
        paragraphs.append(f"主要原因是：{reason}。")
    paragraphs.extend(
        [
            f"{_outlook_confirmation_label(alert.outlook_1_3d)}：{confirmation}。",
            f"会让我改变当前判断的表现：{invalidation}。",
        ]
    )
    return "\n\n".join(paragraphs)


def _render_final_twenty_day_review(
    episode: dict[str, Any],
    final: FrozenTwentyDayReviewV1,
) -> str:
    close_return = _number(episode.get("d20_close_return_since_entry"))
    max_close = _number(episode.get("d20_max_close_return_since_entry"))
    mae = _number(episode.get("d20_mae_since_entry"))
    facts = [
        (
            "前20个交易日收盘数据不足"
            if close_return is None
            else f"前20个交易日收盘{_plain_movement(close_return)}"
        ),
        (
            "期间最高收盘数据不足"
            if max_close is None
            else f"期间最高收盘{_plain_movement(max_close)}"
        ),
        (
            "期间最低价格数据不足"
            if mae is None
            else _plain_low_point(mae)
        ),
    ]
    return f"{'，'.join(facts)}。{final.overall_review}"


def _plain_movement(value: float) -> str:
    if value > 0:
        return f"上涨{value:.2%}"
    if value < 0:
        return f"下跌{abs(value):.2%}"
    return "持平0.00%"


def _plain_low_point(value: float) -> str:
    if value < 0:
        return f"期间最深下跌{abs(value):.2%}"
    if value > 0:
        return f"期间最低仍上涨{value:.2%}"
    return "期间最低持平0.00%"


def _render_relative_performance(episode: dict[str, Any]) -> str:
    day_number = int(episode["day_number"])
    window = 20 if day_number >= 20 else 5 if day_number >= 5 else 3 if day_number >= 3 else 1
    market = _number(episode.get(f"relative_market_{window}d"))
    industry = _number(episode.get(f"relative_industry_{window}d"))
    market_text = "全市场的对照数据不足" if market is None else f"这只股票比全市场{_relative_words(market)}"
    industry_text = "同一行业的对照数据不足" if industry is None else f"比同一行业{_relative_words(industry)}"
    return f"最近{window}个交易日，{market_text}，{industry_text}。"


def _relative_words(value: float) -> str:
    return f"{'强' if value >= 0 else '弱'}{abs(value) * 100:.2f}个百分点"


def _render_pair_comparison(
    episode: dict[str, Any],
    review: ForwardEpisodeReviewV1,
    all_episodes: list[dict[str, Any]],
) -> str:
    context = episode.get("pair_context") or {}
    if context.get("pair_status") == "incomplete":
        return "这次研究中两只股票的价格路径或观察窗口不完整，因此不能做可靠比较。"
    if context.get("pair_status") != "complete":
        return "当时没有留下能够严格匹配的备选股票，因此这次不能做可靠的逐只比较。"
    paired_name = str(context["paired_name"])
    paired_label = f"这次研究中的推荐股{paired_name}" if episode.get("role") == "comparator" else f"当时备选股{paired_name}"
    difference = float(context["return_difference"])
    if round(difference * 100.0, 2) == 0.0:
        difference_text = "两只股票表现接近，相差0.00个百分点。"
    elif difference > 0:
        difference_text = (
            f"这条记录比{paired_name}强{abs(difference) * 100:.2f}个百分点。"
        )
    else:
        difference_text = (
            f"这条记录比{paired_name}弱{abs(difference) * 100:.2f}个百分点。"
        )
    text = (
        f"这条记录目前涨跌为{_format_return(float(context['selected_or_subject_return_since_entry']))}，"
        f"{paired_label}为{_format_return(float(context['alternative_return_since_entry']))}，"
        f"{difference_text}"
        f"这条记录期间最深跌幅为{_format_return(float(context['subject_mae_since_entry']))}，"
        f"期间最大收盘回撤为{abs(float(context['subject_max_close_drawdown'])):.2%}；"
        f"{paired_name}期间最深跌幅为{_format_return(float(context['alternative_mae_since_entry']))}，"
        f"期间最大收盘回撤为{abs(float(context['alternative_max_close_drawdown'])):.2%}。"
    )
    allowed_names = {str(episode.get("name", "")), paired_name}
    other_names = {str(item.get("name", "")) for item in all_episodes if str(item.get("name", "")) and str(item.get("name", "")) not in allowed_names}
    interpretation = review.comparison_interpretation
    if (
        paired_name not in interpretation
        or any(name in interpretation for name in other_names)
    ):
        interpretation = ""
    return text + (f" {interpretation}" if interpretation else "")


def _human_trading_day(day_number: int) -> str:
    if not 1 <= day_number <= 30:
        raise ValueError("day_number must be between 1 and 30")
    if day_number <= 20:
        return f"D{day_number}"
    return f"延长观察第{day_number - 20}天"


def _recommendation_date_sentence(episode: dict[str, Any]) -> str:
    action = date.fromisoformat(str(episode["action_date"]))
    return (
        f"这只股票在{action.year}年{action.month}月{action.day}日"
        "开盘前被正式推荐。"
    )


def _render_target_progress(episode: dict[str, Any]) -> str:
    """Render deterministic progress toward the 20% observation target."""

    recommendation_date = _recommendation_date_sentence(episode)
    current = _number(episode.get("current_close_return_since_entry"))
    if current is None or (
        "entry_open" in episode and _number(episode.get("entry_open")) is None
    ):
        return (
            f"{recommendation_date} "
            "没有可靠的推荐参考价，因此不能计算距离20%目标的进展。"
        )

    day_number = int(episode["day_number"])
    movement = (
        f"上涨{current:.2%}"
        if current > 0.0
        else f"下跌{abs(current):.2%}"
        if current < 0.0
        else "持平0.00%"
    )
    parts = [
        f"{recommendation_date} 到今天是入选后第{day_number}个交易日，"
        f"收盘较参考价{movement}"
    ]
    current_reached_target = current >= 0.20 - 1e-12
    if not current_reached_target:
        parts[-1] += f"，离20%的观察目标还差{(0.20 - current) * 100:.2f}个百分点。"
    else:
        parts[-1] += "。"

    max_close = _number(episode.get("current_max_close_return_since_entry"))
    max_high = _number(episode.get("current_max_high_return_since_entry"))
    lowest = _number(episode.get("current_mae_since_entry"))
    drawdown = _number(episode.get("current_close_drawdown_from_peak"))
    path_facts: list[str] = []
    if max_close is not None:
        path_facts.append(
            f"期间最高上涨{max_close:.2%}"
            if max_close >= 0.0
            else f"期间最高收盘仍下跌{abs(max_close):.2%}"
        )
    if max_high is not None and (
        max_close is None or not np.isclose(max_high, max_close)
    ):
        path_facts.append(f"盘中最高上涨{max_high:.2%}")
    if lowest is not None:
        path_facts.append(
            f"最深下跌{abs(lowest):.2%}"
            if lowest < 0.0
            else f"期间最低仍上涨{lowest:.2%}"
        )
    if drawdown is not None and drawdown < 0.0:
        path_facts.append(f"当前收盘较期间最高收盘回落{abs(drawdown):.2%}")
    if path_facts:
        parts.append(f"{'，'.join(path_facts)}。")

    close_hit = (
        bool(episode.get("current_first_close_hit_20pct_date"))
        or current_reached_target
        or (max_close is not None and max_close >= 0.20 - 1e-12)
    )
    high_hit = (
        bool(episode.get("current_first_high_hit_20pct_date"))
        or (max_high is not None and max_high >= 0.20)
    )
    if close_hit:
        parts.append(
            "收盘已经达到20%的观察目标，继续记录到第20个交易日，"
            "判断达到后是否明显回吐。"
        )
    elif high_hit:
        parts.append(
            "盘中曾达到20%，但收盘没有保持在该位置，"
            "说明目标曾被触及但没有站稳。"
        )
    return " ".join(parts)


def _render_price_summary(episodes: list[dict[str, Any]]) -> str:
    summaries: list[str] = []
    for episode in episodes:
        day = _human_trading_day(int(episode["day_number"]))
        if episode.get("role") == "comparator":
            day = f"该次研究后{day}"
        current = _number(episode.get("current_close_return_since_entry"))
        if current is None:
            summaries.append(f"{day}这条记录的价格路径不完整，暂时无法可靠计算涨跌。")
            continue
        max_close = _number(episode.get("current_max_close_return_since_entry"))
        max_high = _number(episode.get("current_max_high_return_since_entry"))
        lowest = _number(episode.get("current_mae_since_entry"))
        max_drawdown = _number(episode.get("current_max_close_drawdown"))
        drawdown = _number(episode.get("current_close_drawdown_from_peak"))
        details = [f"目前涨跌为{_format_return(current)}"]
        if max_close is not None:
            details.append(f"期间最高收盘涨幅为{_format_return(max_close)}")
        if max_high is not None:
            details.append(f"盘中最高涨幅为{_format_return(max_high)}")
        if lowest is not None:
            details.append(f"期间最深跌幅为{_format_return(lowest)}")
        if max_drawdown is not None:
            details.append(f"期间最大收盘回撤为{abs(max_drawdown):.2%}")
        if drawdown is not None:
            details.append(f"当前收盘价较期间最高收盘价回落{abs(drawdown):.2%}")
        summaries.append(f"{day}这条记录，" + "；".join(details) + "。")
    return " ".join(summaries)


def _render_conditional_event_reaction(episode: dict[str, Any]) -> str:
    reaction = episode.get("first_event_reaction")
    if not isinstance(reaction, dict):
        return "首个完整交易日的价格事实不完整，不能判断原观察条件，也不得补写参与收益。"
    movement = _number(reaction.get("open_to_close_return"))
    amount = _number(reaction.get("amount"))
    movement_text = (
        "开盘到收盘变化无法可靠计算"
        if movement is None
        else f"开盘到收盘{_plain_movement(movement)}"
    )
    amount_text = (
        "成交额数据不足"
        if amount is None
        else f"成交额为{amount:,.0f}"
    )
    return (
        f"首个完整交易日为{reaction.get('trade_date')}，{movement_text}，"
        f"{amount_text}。这是事件反应事实，不是正式推荐收益。 "
        f"{_render_relative_performance(episode)}"
    )


def _format_return(value: float) -> str:
    return f"{value:+.2%}"


def _episode_observation(
    *,
    price_path_cache: dict[
        date,
        tuple[pd.DataFrame, pd.DataFrame],
    ],
    base: dict[str, Any],
    analysis_date: date,
    as_of: datetime,
    day_number: int,
    phase: str,
    path_days: list[date],
    price_row: dict[str, Any] | None,
    sector_row: dict[str, Any] | None,
    group_code: str | None,
    announcements: list[dict[str, Any]],
    previous_episode: dict[str, Any] | None,
    previous_as_of: str | None,
    previous_monitor_state: str | None,
    previous_episode_review: dict[str, Any] | None,
    market_context_available: bool,
    frozen_twenty_day_review: dict[str, Any] | None,
) -> dict[str, Any]:
    ts_code = str(base["ts_code"])
    limitations = [
        str(value)
        for value in base.get("data_limitations", [])
        if str(value)
    ]
    original_thesis = base.get("original_research_thesis")
    if not isinstance(original_thesis, dict) or not original_thesis:
        original_thesis = None
        limitations.append("missing_original_research_thesis")
    path = _adjusted_path(
        price_path_cache,
        ts_code,
        path_days,
    )
    if not path:
        limitations.append("missing_price_path")
    elif len(path) != len(path_days):
        limitations.append("incomplete_price_path")
    action_date = date.fromisoformat(str(base["action_date"]))
    output_class = str(base.get("selection_output_class", ""))
    if not output_class:
        output_class = _episode_selection_output_class(base)
    if output_class == "conditional_event":
        frozen_twenty_day_review = None
    entry = (
        None
        if output_class == "conditional_event"
        else next(
            (item["open"] for item in path if item["date"] == action_date),
            None,
        )
    )
    d20_dates = set(path_days[:20])
    d20_path = [item for item in path if item["date"] in d20_dates]
    d20_metrics_path = d20_path
    if day_number >= 20 and not (
        len(d20_path) == 20
        and [item["date"] for item in d20_path] == path_days[:20]
    ):
        d20_metrics_path = []
        if "incomplete_price_path" not in limitations:
            limitations.append("incomplete_price_path")
    current_fields = _price_fields(price_row)
    if phase != "closed" and price_row is None:
        limitations.append("missing_current_price_context")
    elif phase != "closed" and str((price_row or {}).get("coverage_status", "complete")) != "complete":
        limitations.append("price_context_incomplete")
    if phase != "closed" and base.get("original_engine_type") in {"sector_broad_diffusion", "sector_leader_cluster"} and sector_row is None:
        limitations.append("missing_sector_context")
    if phase != "closed" and not market_context_available:
        limitations.append("missing_market_context")
    if phase == "closed":
        current_fields = {
            key: ([] if key in {"scenario_case_ids", "scenario_control_ids"} else None)
            for key in current_fields
        }

    new_announcements = _new_announcements(
        announcements,
        ts_code=ts_code,
        after=_as_datetime(previous_as_of) or _as_datetime(base.get("source_as_of")),
        as_of=as_of,
    )
    checkpoint = CHECKPOINTS.get(day_number) if phase != "closed" else None
    observation: dict[str, Any] = {
        **{key: value for key, value in base.items() if key != "source_as_of"},
        "original_research_thesis": original_thesis,
        "analysis_date": analysis_date.isoformat(),
        "day_number": day_number,
        "monitor_phase": phase,
        "primary_days_remaining": max(20 - day_number, 0) if phase == "primary" else 0,
        "tail_days_remaining": 10 if phase == "primary" else max(30 - day_number, 0),
        "entry_open": entry,
        "formal_return_started": bool(
            output_class in PUBLIC_FORMAL_OUTPUT_CLASSES
            and entry is not None
        ),
        "first_event_reaction": (
            _first_event_reaction(path)
            if output_class == "conditional_event"
            else None
        ),
        "first_observable_date": (
            path[0]["date"].isoformat() if path else None
        ),
        **_path_metrics(d20_metrics_path, entry, prefix="d20"),
        **_path_metrics(path, entry, prefix="current"),
        **current_fields,
        "original_group_code": group_code,
        **_sector_fields(sector_row),
        "new_announcements": new_announcements,
        "checkpoint": checkpoint,
        "previous_monitor_state": previous_monitor_state,
        "previous_episode_review": previous_episode_review,
        "frozen_twenty_day_review": frozen_twenty_day_review,
        "attention_reasons": [],
        "data_limitations": limitations,
    }
    if phase != "closed":
        observation["attention_reasons"] = _attention_reasons(
            observation,
            previous_episode,
        )
    return _json_value(observation)


def _attention_reasons(
    current: dict[str, Any],
    previous: dict[str, Any] | None,
) -> list[str]:
    reasons: list[str] = []
    is_non_executable_formal = (
        _episode_selection_output_class(current)
        in PUBLIC_FORMAL_OUTPUT_CLASSES
        and current.get("entry_open") is None
    )
    if (
        _episode_selection_output_class(current)
        in PUBLIC_FORMAL_OUTPUT_CLASSES
        and int(current["day_number"]) >= 20
        and current.get("frozen_twenty_day_review") is None
    ):
        reasons.append("pending_final_review")
    if current["checkpoint"] and not is_non_executable_formal:
        reasons.append("checkpoint")
    if current["new_announcements"]:
        reasons.append("new_official_event")
    if (
        current["original_engine_type"] == "fresh_event_pending"
        and current.get("first_observable_date") == current["analysis_date"]
    ):
        reasons.append("first_event_reaction")
    first_hit = current["d20_first_close_hit_20pct_date"]
    previous_first_hit = None
    if previous is not None:
        if "d20_first_close_hit_20pct_date" in previous:
            previous_first_hit = previous.get(
                "d20_first_close_hit_20pct_date"
            )
        else:
            previous_first_hit = previous.get("first_close_hit_20pct_date")
    if first_hit and (
        (previous is not None and not previous_first_hit)
        or (previous is None and first_hit == current["analysis_date"])
    ):
        reasons.append("target_hit_first_time")
    if previous:
        if any(
            _sign_flip(previous.get(key), current.get(key))
            for key in ("relative_market_5d", "relative_industry_5d")
        ):
            reasons.append("relative_state_changed")
        if set(previous.get("scenario_case_ids") or []) != set(current.get("scenario_case_ids") or []):
            reasons.append("scenario_changed")
        if _breakout_state(previous.get("breakout_vs_prior60")) != _breakout_state(current.get("breakout_vs_prior60")):
            reasons.append("breakout_changed")
        if current.get("original_engine_type") in {"sector_broad_diffusion", "sector_leader_cluster"} and _sector_holds(previous) != _sector_holds(current):
            reasons.append("sector_state_changed")
    if _late_activation(current, previous):
        reasons.append("late_activation_candidate")
    if _overheat(current, previous):
        reasons.append("overheat_candidate")
    current_limitations = set(current["data_limitations"])
    previous_limitations = set((previous or {}).get("data_limitations") or [])
    if current_limitations and (
        previous is None
        or current_limitations != previous_limitations
        or (current["checkpoint"] and not is_non_executable_formal)
    ):
        reasons.append("data_problem")
    allowed_order = [
        "pending_final_review", "checkpoint", "new_official_event", "first_event_reaction",
        "target_hit_first_time", "relative_state_changed", "scenario_changed",
        "breakout_changed", "sector_state_changed", "late_activation_candidate",
        "overheat_candidate", "data_problem",
    ]
    return [reason for reason in allowed_order if reason in reasons]


def _late_activation(current: dict[str, Any], previous: dict[str, Any] | None) -> bool:
    if current["monitor_phase"] != "passive_tail" or previous is None:
        return False
    if not all(_positive(current.get(key)) for key in ("relative_market_3d", "relative_market_5d")):
        return False
    industry_reliable = current.get("relative_industry_3d") is not None and current.get("relative_industry_5d") is not None
    if industry_reliable and not all(_positive(current.get(key)) for key in ("relative_industry_3d", "relative_industry_5d")):
        return False
    if not _greater(current.get("amount_ratio_last_20d"), 1.0):
        return False
    current_cases = set(current.get("scenario_case_ids") or [])
    previous_cases = set((previous or {}).get("scenario_case_ids") or [])
    new_cases = current_cases - previous_cases
    breakout_new = _breakout_state(current.get("breakout_vs_prior60")) and not _breakout_state((previous or {}).get("breakout_vs_prior60"))
    if not (breakout_new or bool(new_cases & POSITIVE_SCENARIOS)):
        return False
    return not bool(new_cases & NEGATIVE_SCENARIOS)


def _overheat(current: dict[str, Any], previous: dict[str, Any] | None) -> bool:
    if previous is None:
        return False
    current_cases = set(current.get("scenario_case_ids") or [])
    previous_cases = set(previous.get("scenario_case_ids") or [])
    if (current_cases - previous_cases) & OVERHEAT_SCENARIOS:
        return True
    if _greater(current.get("limit_up_return_contribution_5d"), 0.5) and not _greater(previous.get("limit_up_return_contribution_5d"), 0.5):
        return True
    high_state = _breakout_state(current.get("breakout_vs_prior60"))
    fade_worse = _greater(current.get("fade_frequency_5d"), previous.get("fade_frequency_5d"))
    shadow_worse = _greater(current.get("upper_shadow_frequency_5d"), previous.get("upper_shadow_frequency_5d"))
    efficiency_worse = _less(current.get("volume_price_efficiency_5d"), previous.get("volume_price_efficiency_5d"))
    return high_state and (fade_worse or shadow_worse or efficiency_worse)


def _trading_sessions(root: Path, as_of: datetime) -> list[date]:
    rows = _fact_rows(root, "trade_calendar", as_of)
    dates = {
        _as_date(row.get("cal_date"))
        for row in rows
        if _truth(row.get("is_open")) and _as_date(row.get("cal_date")) is not None
    }
    return sorted(day for day in dates if day is not None and day <= as_of.date())


def _fact_rows(root: Path, dataset: str, as_of: datetime) -> list[dict[str, Any]]:
    base = root / "local_warehouse" / "facts" / dataset
    frames: list[pd.DataFrame] = []
    for path in sorted(base.glob("**/*.parquet")):
        try:
            frame = pd.read_parquet(path)
        except (OSError, ValueError):
            continue
        if "available_at" in frame.columns:
            available = pd.to_datetime(frame["available_at"], utc=True, errors="coerce")
            cutoff = pd.Timestamp(as_of).tz_convert("UTC")
            frame = frame.loc[available.notna() & available.le(cutoff)]
        if not frame.empty:
            frames.append(frame)
    if not frames:
        return []
    return [_json_value(row) for row in pd.concat(frames, ignore_index=True).to_dict("records")]


def _derived_rows(
    root: Path,
    dataset: str,
    analysis_date: date,
    formula_version: str,
    as_of: datetime,
) -> list[dict[str, Any]]:
    path = (
        root
        / "local_warehouse"
        / "derived"
        / dataset
        / f"analysis_date={analysis_date.isoformat()}"
        / f"formula_version={formula_version}"
        / "data.parquet"
    )
    if not path.is_file():
        return []
    frame = pd.read_parquet(path)
    if "available_at" in frame.columns:
        available = pd.to_datetime(frame["available_at"], utc=True, errors="coerce")
        frame = frame.loc[available.notna() & available.le(pd.Timestamp(as_of).tz_convert("UTC"))]
    return [_json_value(row) for row in frame.to_dict("records")]


def _daily_price_cache(
    root: Path,
    path_days: list[date],
    as_of: datetime,
) -> dict[date, tuple[pd.DataFrame, pd.DataFrame]]:
    cache: dict[date, tuple[pd.DataFrame, pd.DataFrame]] = {}
    cutoff = pd.Timestamp(as_of).tz_convert("UTC")
    for day in path_days:
        equity_path = root / "local_warehouse" / "facts" / "equity_daily" / f"trade_date={day.isoformat()}" / "data.parquet"
        factor_path = root / "local_warehouse" / "facts" / "adj_factor" / f"trade_date={day.isoformat()}" / "data.parquet"
        if not equity_path.is_file() or not factor_path.is_file():
            continue
        equity = pd.read_parquet(equity_path)
        factors = pd.read_parquet(factor_path)
        if "available_at" in equity.columns:
            available = pd.to_datetime(
                equity["available_at"],
                utc=True,
                errors="coerce",
            )
            equity = equity.loc[
                available.notna() & available.le(cutoff)
            ]
        if "available_at" in factors.columns:
            available = pd.to_datetime(
                factors["available_at"],
                utc=True,
                errors="coerce",
            )
            factors = factors.loc[
                available.notna() & available.le(cutoff)
            ]
        cache[day] = (equity, factors)
    return cache


def _adjusted_path(
    cache: dict[date, tuple[pd.DataFrame, pd.DataFrame]],
    ts_code: str,
    path_days: list[date],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for day in path_days:
        frames = cache.get(day)
        if frames is None:
            continue
        equity, factors = frames
        equity = equity.loc[equity["ts_code"].astype(str).eq(ts_code)]
        factors = factors.loc[factors["ts_code"].astype(str).eq(ts_code)]
        if equity.empty or factors.empty:
            continue
        row = equity.iloc[-1]
        factor = _number(factors.iloc[-1].get("adj_factor"))
        if factor is None:
            continue
        values = {name: _number(row.get(name)) for name in ("open", "close", "high", "low")}
        if any(value is None for value in values.values()):
            continue
        result.append(
            {
                "date": day,
                **{name: float(value) * factor for name, value in values.items()},
                "amount": _number(row.get("amount")),
            }
        )
    return result


def _first_event_reaction(path: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not path:
        return None
    first = path[0]
    opening = _number(first.get("open"))
    close = _number(first.get("close"))
    return {
        "trade_date": first["date"].isoformat(),
        "open": opening,
        "close": close,
        "high": _number(first.get("high")),
        "low": _number(first.get("low")),
        "amount": _number(first.get("amount")),
        "open_to_close_return": (
            close / opening - 1.0
            if opening is not None and opening > 0 and close is not None
            else None
        ),
    }


def _episode_selection_output_class(episode: dict[str, Any]) -> str:
    value = str(episode.get("selection_output_class", ""))
    if value:
        return value
    if episode.get("role") != "selected":
        return "not_formal_candidate"
    if (
        episode.get("original_engine_type") == "fresh_event_pending"
        and episode.get("original_engine_status") == "conditional"
    ):
        return "conditional_event"
    return "legacy_v1_not_rewritten"


def _path_metrics(
    path: list[dict[str, Any]],
    entry: float | None,
    *,
    prefix: Literal["d20", "current"],
) -> dict[str, Any]:
    hit_key = (
        "d20_hit_20pct_close_within_20d"
        if prefix == "d20"
        else "current_hit_20pct_close"
    )
    empty = {
        f"{prefix}_close_return_since_entry": None,
        f"{prefix}_max_close_return_since_entry": None,
        f"{prefix}_close_drawdown_from_peak": None,
        f"{prefix}_max_close_drawdown": None,
        f"{prefix}_max_high_return_since_entry": None,
        f"{prefix}_mae_since_entry": None,
        f"{prefix}_first_close_hit_20pct_date": None,
        f"{prefix}_first_high_hit_20pct_date": None,
        hit_key: None,
    }
    if not path or entry is None or entry <= 0:
        return empty
    close_returns = [(item["close"] / entry) - 1.0 for item in path]
    high_returns = [(item["high"] / entry) - 1.0 for item in path]
    low_returns = [(item["low"] / entry) - 1.0 for item in path]
    close_hit_threshold = 0.20 - 1e-12 if prefix == "d20" else 0.20
    first_close_hit = next(
        (
            item["date"].isoformat()
            for item, value in zip(path, close_returns, strict=True)
            if value >= close_hit_threshold
        ),
        None,
    )
    peak_close = max(item["close"] for item in path)
    running_peak = path[0]["close"]
    max_close_drawdown = 0.0
    for item in path:
        running_peak = max(running_peak, item["close"])
        max_close_drawdown = min(
            max_close_drawdown,
            item["close"] / running_peak - 1.0,
        )
    return {
        f"{prefix}_close_return_since_entry": close_returns[-1],
        f"{prefix}_max_close_return_since_entry": max(close_returns),
        f"{prefix}_close_drawdown_from_peak": (
            path[-1]["close"] / peak_close - 1.0
        ),
        f"{prefix}_max_close_drawdown": max_close_drawdown,
        f"{prefix}_max_high_return_since_entry": max(high_returns),
        f"{prefix}_mae_since_entry": min(low_returns),
        f"{prefix}_first_close_hit_20pct_date": first_close_hit,
        f"{prefix}_first_high_hit_20pct_date": next(
            (
                item["date"].isoformat()
                for item, value in zip(path, high_returns, strict=True)
                if value >= 0.2
            ),
            None,
        ),
        hit_key: first_close_hit is not None,
    }


def _price_fields(row: dict[str, Any] | None) -> dict[str, Any]:
    row = row or {}
    mapping = {
        "relative_market_1d": "relative_market_1d",
        "relative_market_3d": "relative_market_3d",
        "relative_market_5d": "relative_market_5d",
        "relative_market_20d": "relative_market_20d",
        "relative_industry_1d": "relative_industry_return_1d",
        "relative_industry_3d": "relative_industry_return_3d",
        "relative_industry_5d": "relative_industry_return_5d",
        "relative_industry_20d": "relative_industry_return_20d",
        "amount_ratio_last_20d": "amount_ratio_last_20d",
        "volume_price_efficiency_5d": "volume_price_efficiency_5d",
        "mean_close_position_5d": "mean_close_position_5d",
        "upper_shadow_frequency_5d": "upper_shadow_frequency_5d",
        "fade_frequency_5d": "fade_frequency_5d",
        "breakout_vs_prior60": "breakout_vs_prior60",
        "limit_up_return_contribution_5d": "limit_up_return_contribution_5d",
        "target_atr_distance_20pct": "target_atr_distance_20pct",
        "return_1d": "return_1d",
        "return_3d": "return_3d",
        "return_5d": "return_5d",
        "up_days_5d": "up_days_5d",
        "relative_continuity_5d": "relative_continuity_5d",
        "largest_positive_day_contribution_5d": (
            "largest_positive_day_contribution_5d"
        ),
        "sessions_since_largest_positive_day_5d": (
            "sessions_since_largest_positive_day_5d"
        ),
        "return_ex_largest_positive_day_5d": (
            "return_ex_largest_positive_day_5d"
        ),
        "return_after_largest_positive_day_5d": (
            "return_after_largest_positive_day_5d"
        ),
        "relative_market_after_largest_positive_day_5d": (
            "relative_market_after_largest_positive_day_5d"
        ),
        "price_location_60d": "price_location_60d",
    }
    fields = {target: _number(row.get(source)) for target, source in mapping.items()}
    fields["scenario_case_ids"] = _ids(row.get("scenario_case_ids"))
    fields["scenario_control_ids"] = _ids(row.get("scenario_control_ids"))
    return fields


def _sector_fields(row: dict[str, Any] | None) -> dict[str, Any]:
    row = row or {}
    mapping = {
        "sector_relative_return_3d": "relative_return_3d",
        "sector_relative_return_5d": "relative_return_5d",
        "sector_median_return_3d": "median_return_3d",
        "sector_median_return_5d": "median_return_5d",
        "sector_breadth_3d": "breadth_3d",
        "sector_breadth_5d": "breadth_5d",
        "sector_turnover_share_change_5d": "turnover_share_change_5d",
        "sector_top_contribution": "top3_positive_contribution_1d",
        "sector_dispersion": "return_dispersion_1d",
    }
    return {target: _number(row.get(source)) for target, source in mapping.items()}


def _new_announcements(
    rows: list[dict[str, Any]],
    *,
    ts_code: str,
    after: datetime | None,
    as_of: datetime,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get("ts_code")) != ts_code:
            continue
        available = _as_datetime(row.get("available_at"))
        if available is None or available > as_of:
            continue
        if after is not None and available <= after:
            continue
        result.append(
            {
                "announcement_id": row.get("announcement_id"),
                "announcement_time": row.get("announcement_time"),
                "available_at": available.isoformat(),
                "title": row.get("title"),
            }
        )
    return sorted(result, key=lambda item: (str(item["available_at"]), str(item["announcement_id"])))


def _formation_industry(
    rows: list[dict[str, Any]],
    ts_code: str,
    formation_date: date,
    source_as_of: datetime | None,
) -> str | None:
    if source_as_of is None:
        return None
    matches: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get("ts_code")) != ts_code:
            continue
        if row.get("industry_system") != "SW2021" or row.get("level") != "L2":
            continue
        available = _as_datetime(row.get("available_at"))
        if available is None or available > source_as_of:
            continue
        valid_from = _as_date(row.get("valid_from"))
        valid_to = _as_date(row.get("valid_to"))
        if valid_from and valid_from <= formation_date and (valid_to is None or formation_date <= valid_to):
            matches.append(row)
    if not matches:
        return None
    matches.sort(
        key=lambda row: (
            _as_date(row.get("valid_from")) or date.min,
            _as_datetime(row.get("available_at")) or datetime.min,
        )
    )
    return str(matches[-1].get("industry_code") or "") or None


def _aggregate_attention(episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for episode in episodes:
        if episode["monitor_phase"] == "closed" or not episode["attention_reasons"]:
            continue
        grouped.setdefault(str(episode["ts_code"]), []).append(episode)
    result: list[dict[str, Any]] = []
    allowed = [
        "pending_final_review", "checkpoint", "new_official_event", "first_event_reaction",
        "target_hit_first_time", "relative_state_changed", "scenario_changed",
        "breakout_changed", "sector_state_changed", "late_activation_candidate",
        "overheat_candidate", "data_problem",
    ]
    for ts_code in sorted(grouped):
        items = grouped[ts_code]
        reasons = {reason for item in items for reason in item["attention_reasons"]}
        result.append(
            {
                "ts_code": ts_code,
                "name": next((str(item["name"]) for item in items if item.get("name")), ""),
                "episode_ids": sorted(str(item["episode_id"]) for item in items),
                "roles": [
                    role
                    for role in ("selected", "comparator")
                    if any(str(item["role"]) == role for item in items)
                ],
                "day_numbers": sorted({int(item["day_number"]) for item in items}),
                "original_engine_types": sorted({str(item["original_engine_type"]) for item in items if item.get("original_engine_type")}),
                "attention_reasons": [reason for reason in allowed if reason in reasons],
            }
        )
    return result


def _previous_snapshot(monitor_dir: Path, analysis_date: date) -> dict[str, Any] | None:
    candidates: list[tuple[date, Path]] = []
    for path in monitor_dir.glob("snapshot-*.json"):
        try:
            snapshot_date = date.fromisoformat(path.stem.removeprefix("snapshot-"))
        except ValueError:
            continue
        if snapshot_date < analysis_date:
            candidates.append((snapshot_date, path))
    if not candidates:
        return None
    path = max(candidates, key=lambda item: item[0])[1]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) and payload.get("snapshot_version") == SNAPSHOT_VERSION else None


def _daily_review_history(
    monitor_dir: Path,
    analysis_date: date,
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
]:
    ledgers: list[tuple[date, Path]] = []
    for path in monitor_dir.glob("daily-formal-reviews-*.json"):
        try:
            ledger_date = date.fromisoformat(
                path.stem.removeprefix("daily-formal-reviews-")
            )
        except ValueError:
            continue
        if ledger_date < analysis_date:
            ledgers.append((ledger_date, path))

    latest: dict[str, dict[str, Any]] = {}
    latest_live: dict[str, dict[str, Any]] = {}
    frozen: dict[str, dict[str, Any]] = {}
    for ledger_date, path in sorted(ledgers):
        try:
            ledger = DailyFormalReviewLedgerV1.model_validate_json(
                path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            continue
        for review in ledger.reviews:
            payload = review.model_dump(mode="json")
            latest[review.episode_id] = payload
            if review.review_origin == "live":
                previous_live = latest_live.get(review.episode_id, {})
                exit_date = previous_live.get("_tracking_exit_date")
                exit_reason = previous_live.get("_tracking_exit_reason")
                if review.tracking_decision == "stop_active_tracking":
                    exit_date = ledger_date.isoformat()
                    exit_reason = review.tracking_decision_reason
                latest_live[review.episode_id] = {
                    **payload,
                    "_analysis_date": ledger_date.isoformat(),
                    "_tracking_exit_date": exit_date,
                    "_tracking_exit_reason": exit_reason,
                }
            if review.final_twenty_day_review is not None:
                frozen.setdefault(
                    review.episode_id,
                    review.final_twenty_day_review.model_dump(mode="json"),
                )
    return latest, latest_live, frozen


def _last_detailed_review_dates(
    monitor_dir: Path,
    analysis_date: date,
) -> dict[str, date]:
    latest: dict[str, date] = {}
    for path in monitor_dir.glob("monitor-report-*.json"):
        try:
            report_date = date.fromisoformat(
                path.stem.removeprefix("monitor-report-")
            )
        except ValueError:
            continue
        if report_date >= analysis_date:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        for alert in payload.get("alerts", []):
            if not isinstance(alert, dict):
                continue
            for episode_id in alert.get("episode_ids", []):
                latest[str(episode_id)] = report_date
    return latest


def _tracking_status(
    episode: dict[str, Any],
    latest_live_review: dict[str, Any] | None,
) -> Literal["active", "evaluation_only", "completed"]:
    if episode.get("monitor_phase") == "closed":
        return "completed"
    decision = (
        str(latest_live_review.get("tracking_decision"))
        if latest_live_review is not None
        else ""
    )
    if decision == "stop_active_tracking":
        if episode.get("frozen_twenty_day_review") is not None:
            return "completed"
        return "evaluation_only"
    if decision == "complete_observation":
        return "completed"
    if decision == "keep_active_tracking":
        return "active"
    if episode.get("frozen_twenty_day_review") is not None:
        return "completed"
    return "active"


def _needs_daily_formal_review(
    episode: dict[str, Any],
    latest_live_review: dict[str, Any] | None,
) -> bool:
    status = episode.get("tracking_status")
    day_number = int(episode.get("day_number", 0))
    if status == "evaluation_only":
        return day_number >= 20 and episode.get("frozen_twenty_day_review") is None
    if status != "active" or not 1 <= day_number <= 30:
        return False
    if day_number <= 20 or episode.get("frozen_twenty_day_review") is None:
        return True
    return bool(
        latest_live_review is not None
        and latest_live_review.get("tracking_decision")
        == "keep_active_tracking"
        and int(latest_live_review.get("day_number", 0)) >= 20
    )


def _previous_monitor_states(
    monitor_dir: Path,
    analysis_date: date,
    previous_snapshot: dict[str, Any] | None,
) -> dict[str, str]:
    carried = {
        str(item.get("episode_id")): str(item["previous_monitor_state"])
        for item in (previous_snapshot or {}).get("episodes", [])
        if item.get("episode_id") and item.get("previous_monitor_state")
    }
    reports: list[tuple[date, Path]] = []
    for path in monitor_dir.glob("monitor-report-*.json"):
        try:
            report_date = date.fromisoformat(
                path.stem.removeprefix("monitor-report-")
            )
        except ValueError:
            continue
        if report_date < analysis_date:
            reports.append((report_date, path))
    found: dict[str, str] = {}
    for _, path in sorted(reports):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        for alert in payload.get("alerts", []):
            if not isinstance(alert, dict) or not alert.get("monitor_state"):
                continue
            for episode_id in alert.get("episode_ids", []):
                found[str(episode_id)] = str(alert["monitor_state"])
    return {**carried, **found}


def _previous_episode_reviews(
    monitor_dir: Path,
    analysis_date: date,
) -> dict[str, dict[str, Any]]:
    reports: list[tuple[date, Path]] = []
    for path in monitor_dir.glob("monitor-report-*.json"):
        try:
            report_date = date.fromisoformat(
                path.stem.removeprefix("monitor-report-")
            )
        except ValueError:
            continue
        if report_date < analysis_date:
            reports.append((report_date, path))
    for _, path in sorted(reports, reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict) or payload.get("report_version") not in {
            "daily-forward-monitor-report-v2",
            "daily-forward-monitor-report-v3",
        }:
            continue
        found: dict[str, dict[str, Any]] = {}
        for alert in payload.get("alerts", []):
            if not isinstance(alert, dict):
                continue
            for review in alert.get("episode_reviews", []):
                if not isinstance(review, dict):
                    continue
                episode_id = str(review.get("episode_id", ""))
                compact = {
                    key: review[key]
                    for key in (
                        "current_assessment",
                        "best_supported_explanation",
                        "current_weak_or_failed_link",
                        "current_review",
                    )
                    if key in review
                }
                if episode_id and len(compact) == 4:
                    found[episode_id] = _json_value(compact)
        return found
    return {}


def _earliest_frozen_reviews(
    monitor_dir: Path,
    analysis_date: date,
) -> dict[str, dict[str, Any]]:
    reports: list[tuple[date, Path]] = []
    for path in monitor_dir.glob("monitor-report-*.json"):
        try:
            report_date = date.fromisoformat(
                path.stem.removeprefix("monitor-report-")
            )
        except ValueError:
            continue
        if report_date <= analysis_date:
            reports.append((report_date, path))
    frozen: dict[str, dict[str, Any]] = {}
    for _, path in sorted(reports):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if (
            not isinstance(payload, dict)
            or payload.get("report_version")
            != "daily-forward-monitor-report-v2"
        ):
            continue
        for alert in payload.get("alerts", []):
            if not isinstance(alert, dict):
                continue
            for review in alert.get("episode_reviews", []):
                if not isinstance(review, dict):
                    continue
                episode_id = str(review.get("episode_id", ""))
                final_review = review.get("final_twenty_day_review")
                if episode_id and isinstance(final_review, dict):
                    frozen.setdefault(episode_id, _json_value(final_review))
    return frozen


def _attach_pair_contexts(observations: list[dict[str, Any]]) -> None:
    by_id = {
        str(item.get("episode_id")): item
        for item in observations
        if item.get("episode_id")
    }
    reverse: dict[str, list[str]] = {}
    for item in observations:
        paired_id = item.get("original_nearest_alternative_episode_id")
        if paired_id:
            reverse.setdefault(str(paired_id), []).append(
                str(item["episode_id"])
            )
    for item in observations:
        paired_id = item.get("original_nearest_alternative_episode_id")
        if not paired_id:
            reverse_ids = reverse.get(str(item["episode_id"]), [])
            paired_id = reverse_ids[0] if len(reverse_ids) == 1 else None
        paired = by_id.get(str(paired_id)) if paired_id else None
        if paired is None:
            item["pair_context"] = {"pair_status": "unavailable"}
            continue
        context: dict[str, Any] = {
            "pair_status": "incomplete",
            "paired_episode_id": str(paired["episode_id"]),
            "paired_name": str(paired.get("name", "")),
            "paired_day_number": int(paired["day_number"]),
        }
        same_window = (
            item.get("formation_date") == paired.get("formation_date")
            and item.get("action_date") == paired.get("action_date")
            and item.get("analysis_date") == paired.get("analysis_date")
            and item.get("day_number") == paired.get("day_number")
        )
        incomplete_flags = {
            "missing_price_path",
            "incomplete_price_path",
        }
        paths_complete = not (
            incomplete_flags & set(item.get("data_limitations") or [])
            or incomplete_flags & set(paired.get("data_limitations") or [])
        )
        metric_fields = (
            "current_close_return_since_entry",
            "current_mae_since_entry",
            "current_max_close_drawdown",
        )
        metrics_complete = all(
            _number(value.get(field)) is not None
            for value in (item, paired)
            for field in metric_fields
        )
        if same_window and paths_complete and metrics_complete:
            subject_return = float(item["current_close_return_since_entry"])
            alternative_return = float(
                paired["current_close_return_since_entry"]
            )
            context.update(
                pair_status="complete",
                selected_or_subject_return_since_entry=subject_return,
                alternative_return_since_entry=alternative_return,
                return_difference=subject_return - alternative_return,
                subject_mae_since_entry=float(
                    item["current_mae_since_entry"]
                ),
                alternative_mae_since_entry=float(
                    paired["current_mae_since_entry"]
                ),
                subject_max_close_drawdown=float(
                    item["current_max_close_drawdown"]
                ),
                alternative_max_close_drawdown=float(
                    paired["current_max_close_drawdown"]
                ),
            )
        item["pair_context"] = _json_value(context)


def _sector_holds(item: dict[str, Any]) -> bool:
    engine = item.get("original_engine_type")
    common = (
        _positive(item.get("sector_relative_return_3d"))
        and _positive(item.get("sector_relative_return_5d"))
        and _positive(item.get("sector_turnover_share_change_5d"))
    )
    if engine == "sector_broad_diffusion":
        return bool(
            common
            and _positive(item.get("sector_median_return_3d"))
            and _positive(item.get("sector_median_return_5d"))
            and _greater(item.get("sector_breadth_3d"), 0.5)
            and _greater(item.get("sector_breadth_5d"), 0.5)
            and _less(item.get("sector_top_contribution"), 0.8)
        )
    if engine == "sector_leader_cluster":
        return bool(common and not _greater(item.get("sector_top_contribution"), 0.6))
    return False


def _ids(value: Any) -> list[str]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    if isinstance(value, list):
        return sorted({str(item).strip() for item in value if str(item).strip()})
    text = str(value).strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            return sorted({str(item).strip() for item in parsed if str(item).strip()})
    return sorted({part.strip() for part in text.replace(";", ",").split(",") if part.strip()})


def _number(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _positive(value: Any) -> bool:
    return _greater(value, 0.0)


def _greater(left: Any, right: Any) -> bool:
    left_number = _number(left)
    right_number = _number(right)
    return left_number is not None and right_number is not None and left_number > right_number


def _less(left: Any, right: Any) -> bool:
    left_number = _number(left)
    right_number = _number(right)
    return left_number is not None and right_number is not None and left_number < right_number


def _truth(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return bool(value) if value is not None and not pd.isna(value) else False


def _breakout_state(value: Any) -> bool:
    return _greater(value, 0.0)


def _sign_flip(before: Any, after: Any) -> bool:
    left = _number(before)
    right = _number(after)
    return left is not None and right is not None and ((left > 0 > right) or (left < 0 < right))


def _as_date(value: Any) -> date | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _as_datetime(value: Any) -> datetime | None:
    if value is None or pd.isna(value):
        return None
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None:
        return None
    return stamp.to_pydatetime()


def _json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_value(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if value is None or value is pd.NA:
        return None
    if hasattr(value, "item"):
        try:
            value = value.item()
        except (TypeError, ValueError):
            pass
    if isinstance(value, float) and pd.isna(value):
        return None
    return value


def _trace_episodes(
    trace: dict[str, Any],
    *,
    label: str,
    source_type: str,
) -> list[dict[str, Any]]:
    formation_date = str(trace.get("formation_date", ""))
    action_date = str(trace.get("action_date", ""))
    source_as_of = str(trace.get("as_of", ""))
    ledger = {
        str(item.get("ts_code", "")): item
        for item in trace.get("candidate_ledger", [])
        if isinstance(item, dict)
    }
    decisions_by_id = {
        str(item.get("decision_id", "")): item
        for item in trace.get("decision_trace", [])
        if isinstance(item, dict) and item.get("decision_id")
    }
    result = trace.get("research_result", {})
    nearest_items = [
        item
        for item in result.get("nearest_nonselections", [])
        if isinstance(item, dict)
    ]
    groups = (
        ("selected", result.get("selected_stocks", [])),
        ("comparator", nearest_items),
    )
    episodes: list[dict[str, Any]] = []
    for role, items in groups:
        for item in items:
            ts_code = str(item.get("ts_code", "")).strip()
            candidate = ledger.get(ts_code, {})
            thesis = candidate.get("research_thesis", {})
            output_class = selection_output_class(
                trace_version=str(trace.get("trace_version", "")),
                candidate=candidate,
                role=role,
            )
            recognition = thesis.get("market_recognition")
            broad = thesis.get("sector_broad_diffusion") or {}
            cluster = thesis.get("sector_leader_cluster") or {}
            nearest_alternative = (
                _reliable_nearest_alternative(item, nearest_items)
                if role == "selected"
                else None
            )
            decision_ids = [
                str(value)
                for value in thesis.get("decision_ids", [])
                if str(value)
            ]
            action_decision_id = str(
                thesis.get("action_condition_decision_id") or ""
            )
            if action_decision_id and action_decision_id not in decision_ids:
                decision_ids.append(action_decision_id)
            referenced_decisions = [
                _json_value(decisions_by_id[decision_id])
                for decision_id in decision_ids
                if decision_id in decisions_by_id
            ]
            missing_decisions = [
                decision_id
                for decision_id in decision_ids
                if decision_id not in decisions_by_id
            ]
            data_limitations = (
                ["missing_original_referenced_decisions"]
                if missing_decisions
                else []
            )
            episodes.append(
                {
                    "episode_id": f"{label}:{formation_date}:{ts_code}:{role}",
                    "source_type": source_type,
                    "source_as_of": source_as_of,
                    "role": role,
                    "selection_output_class": output_class,
                    "formation_date": formation_date,
                    "action_date": action_date,
                    "ts_code": ts_code,
                    "name": str(item.get("name", "")).strip(),
                    "original_priority": item.get("priority"),
                    "original_opportunity_type": item.get("opportunity_type"),
                    "original_engine_type": thesis.get("engine_type"),
                    "original_engine_status": thesis.get("engine_status"),
                    "original_market_recognition": recognition,
                    "original_primary_reason": candidate.get("primary_reason"),
                    "original_selection_reason": item.get("selection_reason"),
                    "original_research_thesis": _json_value(thesis)
                    if isinstance(thesis, dict) and thesis
                    else None,
                    "original_strongest_counterevidence": item.get(
                        "strongest_counterevidence"
                    ),
                    "original_nearest_comparison": item.get("nearest_comparison"),
                    "original_nearest_alternative": nearest_alternative,
                    "original_nearest_alternative_episode_id": (
                        f"{label}:{formation_date}:"
                        f"{nearest_alternative['ts_code']}:comparator"
                        if nearest_alternative is not None
                        else None
                    ),
                    "original_referenced_decisions": referenced_decisions,
                    "data_limitations": data_limitations,
                    "original_group_code": broad.get("group_code")
                    or cluster.get("group_code"),
                }
            )
    return episodes


def _reliable_nearest_alternative(
    selected: dict[str, Any],
    nearest_items: list[dict[str, Any]],
) -> dict[str, str] | None:
    comparison = str(selected.get("nearest_comparison", ""))
    if not comparison:
        return None
    matches_by_code = {
        str(item.get("ts_code", "")).strip(): item
        for item in nearest_items
        if (
            str(item.get("ts_code", "")).strip() in comparison
            or (
                bool(str(item.get("name", "")).strip())
                and str(item.get("name", "")).strip() in comparison
            )
        )
    }
    matches = list(matches_by_code.values())
    if len(matches) != 1:
        return None
    match = matches[0]
    code = str(match.get("ts_code", "")).strip()
    name = str(match.get("name", "")).strip()
    if not code or not name:
        return None
    return {"ts_code": code, "name": name}


def _read_registry(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"registry_version": REGISTER_VERSION, "episodes": []}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(payload, dict)
        or payload.get("registry_version") != REGISTER_VERSION
        or not isinstance(payload.get("episodes"), list)
    ):
        raise ValueError("registered episode file is invalid")
    return payload


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_name = handle.name
            json.dump(
                payload,
                handle,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except Exception:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)
        raise


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_name = handle.name
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except Exception:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)
        raise


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Track V4 selections after they are chosen")
    commands = parser.add_subparsers(dest="command", required=True)
    register = commands.add_parser("register")
    register.add_argument("--trace-file", required=True)
    register.add_argument("--label", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--analysis-date", required=True)
    prepare.add_argument("--as-of", required=True)
    record = commands.add_parser("record")
    record.add_argument("--snapshot-file", required=True)
    record.add_argument("--report-file", required=True)
    daily = commands.add_parser("record-daily-formal-reviews")
    daily.add_argument("--snapshot-file", required=True)
    daily.add_argument("--review-file", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    project_root = Path(__file__).resolve().parents[3]
    try:
        if args.command == "register":
            summary: Any = register_episodes(
                trace_file=Path(args.trace_file).expanduser().resolve(),
                label=args.label,
                project_root=project_root,
            )
        elif args.command == "prepare":
            summary = prepare_forward_monitor(
                analysis_date=date.fromisoformat(args.analysis_date),
                as_of=datetime.fromisoformat(args.as_of),
                project_root=project_root,
            )
        elif args.command == "record-daily-formal-reviews":
            summary = record_daily_formal_reviews(
                snapshot_file=Path(args.snapshot_file).expanduser().resolve(),
                review_file=Path(args.review_file).expanduser().resolve(),
                project_root=project_root,
            )
        else:
            summary = record_forward_monitor(
                snapshot_file=Path(args.snapshot_file).expanduser().resolve(),
                report_file=Path(args.report_file).expanduser().resolve(),
                project_root=project_root,
            )
    except Exception as error:
        print("status=error")
        print(f"error={type(error).__name__}: {error}")
        return 2
    for key, value in asdict(summary).items():
        print(f"{key}={value}")
    return 0


__all__ = [
    "DAILY_FORMAL_REVIEWS_VERSION",
    "DailyFormalReviewLedgerV1",
    "DailyFormalReviewRecordSummary",
    "DailyFormalReviewV1",
    "DailyForwardMonitorReportV1",
    "DailyForwardMonitorReportV2",
    "ForwardEpisodeReviewV1",
    "FrozenTwentyDayReviewV1",
    "PrepareSummary",
    "RecordSummary",
    "RegisterSummary",
    "prepare_forward_monitor",
    "record_daily_formal_reviews",
    "record_forward_monitor",
    "register_episodes",
]


if __name__ == "__main__":
    raise SystemExit(main())
