from __future__ import annotations

import argparse
import csv
import json
import math
import os
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from time import sleep as system_sleep
from typing import Any, Literal, Protocol
from zoneinfo import ZoneInfo

import duckdb
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from stock_analyzer.analysis.event_reaction_features import (
    EVENT_REACTION_EVIDENCE_ID,
)
from stock_analyzer.analysis.price_scenario_validation import SCENARIO_SPECS


SHANGHAI = ZoneInfo("Asia/Shanghai")
SELECTION_START = time(9, 5)
READINESS_POLL_SECONDS = 30
MARKET_OPEN = time(9, 30)
INDUSTRY_RESEARCH_LIMITATION = "申万一级行业代理不可用，本次不使用行业证据"
THEME_RESEARCH_LIMITATION = "主题原始日数据不可用，本次不使用主题证据"
STOCK_CONTEXT_LIMITATION = "个股交易背景不可用，不使用其独有字段"
PREOPEN_REFRESH_LIMITATION = (
    "行动日前公告补采未完成，不形成 fresh_event_pending"
)
REQUIRED_SKILLS = {
    "orchestrating-stock-research",
    "interpreting-market-macro",
    "researching-sectors-industries",
    "researching-company-events",
    "analyzing-price-trading",
}
MAX_RETURN_FIELD = "max_close_return_20d"
RESULT_FIELDS = (
    "hit_20pct_close_within_20d",
    "first_hit_day",
    MAX_RETURN_FIELD,
    "terminal_return_20d",
)
REQUIRED_LOG_FIELDS = {
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
    "hit_20pct_close_within_20d",
    "first_hit_day",
    "terminal_return_20d",
    "selection_as_of",
    "validation_mode",
}
CONFIRMED_ACTIVE_ENGINES = frozenset(
    {
        "event_repricing_confirmed",
        "sector_broad_diffusion",
        "sector_leader_cluster",
        "independent_demand_acceleration",
    }
)


OpportunityType = Literal[
    "company_catalyst",
    "sector_diffusion",
    "independent_price_anomaly",
]
SkillName = Literal[
    "orchestrating-stock-research",
    "interpreting-market-macro",
    "researching-sectors-industries",
    "researching-company-events",
    "analyzing-price-trading",
]
ProfessionalSkillName = Literal[
    "interpreting-market-macro",
    "researching-sectors-industries",
    "researching-company-events",
    "analyzing-price-trading",
]
DiscoverySkillName = Literal[
    "researching-sectors-industries",
    "researching-company-events",
    "analyzing-price-trading",
]
SelectionOutputClass = Literal[
    "confirmed_active",
    "conditional_event",
    "legacy_v1_not_rewritten",
    "not_formal_candidate",
]


def selection_output_class(
    *,
    trace_version: str,
    candidate: dict[str, Any],
    role: str = "selected",
) -> SelectionOutputClass:
    """Derive consumer semantics without rewriting the frozen trace."""

    if role != "selected" or candidate.get("final_fate") != "selected":
        return "not_formal_candidate"
    if trace_version != "daily-research-trace-v4":
        return "legacy_v1_not_rewritten"
    thesis = candidate.get("research_thesis")
    if not isinstance(thesis, dict):
        return "not_formal_candidate"
    recognition = thesis.get("market_recognition")
    recognition_status = (
        recognition.get("status") if isinstance(recognition, dict) else None
    )
    engine_type = thesis.get("engine_type")
    engine_status = thesis.get("engine_status")
    if (
        engine_type in CONFIRMED_ACTIVE_ENGINES
        and engine_status == "active"
        and recognition_status == "confirmed"
    ):
        return "confirmed_active"
    if (
        engine_type == "fresh_event_pending"
        and engine_status == "conditional"
        and recognition_status == "pending"
    ):
        return "conditional_event"
    return "not_formal_candidate"


class CandidateResult(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    ts_code: str = Field(min_length=9)
    name: str = Field(min_length=1)
    opportunity_type: OpportunityType
    selection_reason: str = Field(min_length=1)
    strongest_counterevidence: str = Field(min_length=1)
    nearest_comparison: str = Field(min_length=1)


class SelectedCandidateResult(CandidateResult):
    priority: int = Field(ge=1, le=5)


class ResearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    research_completed: bool
    point_in_time_evidence_verified: bool
    failure_reason: str
    skills_used: list[SkillName] = Field(min_length=5, max_length=5)
    selected_stocks: list[SelectedCandidateResult] = Field(max_length=5)
    nearest_nonselections: list[CandidateResult] = Field(max_length=3)
    empty_reason: str


class MarketPropagationEnvironment(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    environment_id: str = Field(min_length=1)
    propagation_state: Literal["supportive", "neutral", "adverse", "unknown"]
    breadth: str = Field(min_length=1)
    liquidity: str = Field(min_length=1)
    risk_appetite: str = Field(min_length=1)
    style: str = Field(min_length=1)
    concentration: str = Field(min_length=1)
    evidence_basis: list[str] = Field(min_length=1)


class MarketRecognition(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    status: Literal[
        "confirmed",
        "partial",
        "absent",
        "not_yet_observable",
        "unknown",
    ]
    market_environment_id: str = Field(min_length=1)
    basis: str = Field(min_length=1)


class CompanyInformationNovelty(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    disclosure_novelty: Literal[
        "first_disclosure",
        "incremental_update",
        "repeat_disclosure",
        "history_insufficient",
        "not_applicable",
    ]
    new_information_level: Literal[
        "major_new_information",
        "material_increment",
        "limited_increment",
        "no_new_information",
        "unknown",
        "not_applicable",
    ]
    basis: str = Field(min_length=1)
    event_id: str | None = Field(default=None, min_length=1)
    event_available_at: datetime | None = None


class SectorLeaderCluster(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    cluster_id: str = Field(min_length=1)
    group_code: str = Field(min_length=1)
    group_name: str = Field(min_length=1)
    members: list[str] = Field(min_length=2)
    candidate_role: Literal["leader", "core", "follower", "outside", "unknown"]
    propagation_evidence: str = Field(min_length=1)
    strongest_counterevidence: str = Field(min_length=1)
    unknowns: list[str]


class ResearchThesis(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    engine_type: Literal[
        "company_event",
        "sector_diffusion",
        "stock_specific_demand",
        "no_valid_engine",
    ]
    engine_status: Literal[
        "confirmed",
        "fresh_event_pending",
        "unconfirmed",
        "invalidated",
    ]
    market_recognition: MarketRecognition
    company_information_novelty: CompanyInformationNovelty
    sector_leader_cluster: SectorLeaderCluster | None = None
    action_condition_decision_id: str | None = Field(default=None, min_length=1)
    catalyst: str = Field(min_length=1)
    short_term_engine: str = Field(min_length=1)
    propagation: str = Field(min_length=1)
    price_confirmation: str = Field(min_length=1)
    remaining_path: str = Field(min_length=1)
    fundamental_anchor: str = Field(min_length=1)
    company_risk: str = Field(min_length=1)
    critical_unknown: str = Field(min_length=1)
    decision_ids: list[str] = Field(min_length=2)


class TraceCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    ts_code: str = Field(min_length=9)
    name: str = Field(min_length=1)
    opportunity_type: OpportunityType
    source_skills: list[DiscoverySkillName] = Field(min_length=1)
    final_fate: Literal["selected", "rejected", "unresolved"]
    primary_reason: str = Field(min_length=1)
    research_thesis: ResearchThesis | None = None


class TraceDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    decision_id: str = Field(min_length=1)
    ts_code: str = Field(min_length=9)
    source_skill: ProfessionalSkillName
    evidence_id: str = Field(min_length=1)
    evidence_version: str = Field(min_length=1)
    evidence_status_at_use: Literal[
        "supported_with_boundary",
        "provisional",
        "observation_only",
    ]
    decision_role: Literal[
        "discovery",
        "support",
        "counter",
        "comparison",
        "action_condition",
    ]
    decision_changed: Literal[
        "created_lead",
        "promoted",
        "demoted",
        "rejected",
        "no_change",
    ]
    formation_values: dict[str, bool | int | float | str]


class DailyResearchTrace(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    trace_version: Literal["daily-research-trace-v3"]
    formation_date: date
    action_date: date
    as_of: datetime
    market_search_context: str = Field(min_length=1)
    market_propagation_environment: MarketPropagationEnvironment
    candidate_ledger: list[TraceCandidate]
    decision_trace: list[TraceDecision]
    research_result: ResearchResult


# ---------------------------------------------------------------------------
# A-share short-horizon engine contract v4.
#
# Existing v3 traces remain readable. New daily research uses v4 so the exact
# engine taxonomy can be reviewed by D20 without changing Forward CSV or the
# data warehouse.
# ---------------------------------------------------------------------------

V4_EFFECTIVE_FORMATION_DATE = date(2026, 8, 21)

EngineTypeV4 = Literal[
    "fresh_event_pending",
    "event_repricing_confirmed",
    "sector_broad_diffusion",
    "sector_leader_cluster",
    "independent_demand_acceleration",
    "anchor_only",
    "unresolved",
]
EngineStatusV4 = Literal["active", "conditional", "inactive", "unresolved"]
MarketRecognitionStatusV4 = Literal[
    "pending",
    "confirmed",
    "mixed",
    "rejected",
    "not_applicable",
]
MarketPropagationModeV4 = Literal[
    "broad_sustained_participation",
    "one_day_repair",
    "sector_rotation",
    "concentrated_speculation",
    "weak_or_fragmented",
    "unclear",
]
MarketRiskOverlayV4 = Literal["high_dispersion_risk"]
NewInformationLevelV4 = Literal[
    "substantive_new",
    "incremental_detail",
    "confirmation_only",
    "repeat_or_no_new_information",
    "not_applicable",
    "unknown",
]


class MarketRecognitionV4(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    status: MarketRecognitionStatusV4
    basis: str = Field(min_length=1)


class DisclosureChainV4(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    prior_forecast: str | None = Field(default=None, min_length=1)
    forecast_revision: str | None = Field(default=None, min_length=1)
    earnings_express: str | None = Field(default=None, min_length=1)
    formal_report: str | None = Field(default=None, min_length=1)
    correction: str | None = Field(default=None, min_length=1)
    comparison_basis: str = Field(min_length=1)


class CompanyInformationV4(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    first_or_repeat: Literal["first", "repeat", "unknown", "not_applicable"]
    disclosure_chain: DisclosureChainV4
    new_information_level: NewInformationLevelV4
    event_id: str | None = Field(default=None, min_length=1)
    event_available_at: datetime | None = None
    event_stage: str = Field(min_length=1)
    business_link: Literal["direct", "indirect", "unknown", "not_applicable"]
    materiality: str = Field(min_length=1)
    tradable_sessions_since_event: int | None = Field(default=None, ge=0)
    basis: str = Field(min_length=1)


class SectorBroadDiffusionEvidenceV4(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    group_code: str = Field(min_length=1)
    group_name: str = Field(min_length=1)
    relative_return_3d: float
    relative_return_5d: float
    median_return_3d: float
    median_return_5d: float
    breadth_3d: float = Field(ge=0.0, le=1.0)
    breadth_5d: float = Field(ge=0.0, le=1.0)
    turnover_share_change_5d: float
    top3_positive_contribution: float = Field(ge=0.0, le=1.0)
    candidate_role: Literal[
        "leader_confirmed",
        "core_diffusion_member",
        "lagging_unverified",
        "label_only",
    ]
    strongest_counterevidence: str = Field(min_length=1)


class SectorLeaderMemberEvidenceV4(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    ts_code: str = Field(min_length=9)
    relative_market_3d: float
    relative_market_5d: float
    industry_percentile_5d: float = Field(ge=0.0, le=1.0)


class SectorLeaderClusterEvidenceV4(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    cluster_id: str = Field(min_length=1)
    group_code: str = Field(min_length=1)
    group_name: str = Field(min_length=1)
    members: list[SectorLeaderMemberEvidenceV4] = Field(min_length=3)
    effective_member_count: int = Field(ge=1)
    qualifying_leader_count: int = Field(ge=1)
    required_leader_count: int = Field(ge=3)
    relative_return_3d: float
    relative_return_5d: float
    turnover_share_change_5d: float
    top1_positive_contribution: float = Field(ge=0.0, le=1.0)
    candidate_industry_percentile_5d: float = Field(ge=0.0, le=1.0)
    candidate_role: Literal[
        "leader_confirmed",
        "core_diffusion_member",
        "lagging_unverified",
        "label_only",
    ]
    strongest_counterevidence: str = Field(min_length=1)
    unknowns: list[str] = Field(default_factory=list)


class ResearchThesisV4(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    engine_type: EngineTypeV4
    engine_status: EngineStatusV4
    market_recognition: MarketRecognitionV4
    company_information: CompanyInformationV4
    sector_broad_diffusion: SectorBroadDiffusionEvidenceV4 | None = None
    sector_leader_cluster: SectorLeaderClusterEvidenceV4 | None = None
    action_condition_decision_id: str | None = Field(default=None, min_length=1)
    catalyst: str = Field(min_length=1)
    short_term_engine: str = Field(min_length=1)
    propagation: str = Field(min_length=1)
    price_confirmation: str = Field(min_length=1)
    remaining_path: str = Field(min_length=1)
    fundamental_anchor: str = Field(min_length=1)
    company_risk: str = Field(min_length=1)
    critical_unknown: str = Field(min_length=1)
    decision_ids: list[str] = Field(min_length=2)


class TraceCandidateV4(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    ts_code: str = Field(min_length=9)
    name: str = Field(min_length=1)
    opportunity_type: OpportunityType
    source_skills: list[DiscoverySkillName] = Field(min_length=1)
    final_fate: Literal["selected", "rejected", "unresolved"]
    primary_reason: str = Field(min_length=1)
    research_thesis: ResearchThesisV4


class RuntimeCapabilitiesV4(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    market_research_available: bool
    price_research_available: bool
    industry_research_available: bool
    theme_research_available: bool
    stock_context_available: bool
    announcement_status: Literal[
        "cninfo_complete",
        "exchange_complete",
        "exchange_partial",
        "announcement_unavailable",
    ]
    announcement_exchanges: list[Literal["SSE", "SZSE"]]
    limitations: list[str]


class DailyResearchTraceV4(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    trace_version: Literal["daily-research-trace-v4"]
    formation_date: date
    action_date: date
    as_of: datetime
    market_search_context: str = Field(min_length=1)
    market_propagation_mode: MarketPropagationModeV4
    market_risk_overlays: list[MarketRiskOverlayV4]
    runtime_capabilities: RuntimeCapabilitiesV4 | None = None
    candidate_ledger: list[TraceCandidateV4]
    decision_trace: list[TraceDecision]
    research_result: ResearchResult


@dataclass(frozen=True)
class PricePoint:
    trade_date: date
    adjusted_open: float
    adjusted_close: float


@dataclass(frozen=True)
class RunSummary:
    status: str
    started_at: str
    run_mode: Literal["normal", "rerun"] = "normal"
    research_mode: Literal["full", "limited", ""] = ""
    market_research_available: bool = False
    price_research_available: bool = False
    industry_research_available: bool = False
    theme_research_available: bool = False
    sector_research_available: bool = False
    stock_context_available: bool = False
    preopen_event_refresh_complete: bool = False
    announcement_status: str = ""
    announcement_exchanges: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    formation_date: str = ""
    action_date: str = ""
    selection_as_of: str = ""
    data_ready: bool = False
    new_forward_rows: int = 0
    selected_count: int = 0
    settled_rows: int = 0
    error: str = ""


class ForwardData(Protocol):
    def trading_day_status(self, on_date: date) -> bool | None: ...

    def trading_dates(self, start: date, end: date) -> list[date]: ...

    def health_report(self, formation_date: date) -> dict[str, Any]: ...

    def eligible_securities(self, on_date: date) -> dict[str, str]: ...

    def adjusted_prices(
        self,
        ts_code: str,
        trading_dates: list[date],
    ) -> list[PricePoint] | None: ...


@dataclass(frozen=True)
class _SelectionContext:
    started_at: str
    run_mode: Literal["normal", "rerun"]
    research_mode: Literal["full", "limited"]
    market_research_available: bool
    price_research_available: bool
    industry_research_available: bool
    theme_research_available: bool
    sector_research_available: bool
    stock_context_available: bool
    preopen_event_refresh_complete: bool
    announcement_status: str
    announcement_exchanges: tuple[str, ...]
    limitations: tuple[str, ...]
    formation_date: date
    action_date: date
    selection_as_of: datetime
    fieldnames: list[str]
    rows: list[dict[str, str]]
    open_dates: list[date]
    settled_rows: int


class LocalForwardData:
    def __init__(self, warehouse_root: Path, archive_root: Path) -> None:
        self.warehouse_root = Path(warehouse_root)
        self.archive_root = Path(archive_root)

    def trading_day_status(self, on_date: date) -> bool | None:
        paths = sorted(
            (self.warehouse_root / "facts/trade_calendar").glob(
                "cal_year=*/data.parquet"
            )
        )
        if not paths:
            return None
        with duckdb.connect() as connection:
            row = connection.execute(
                """
                select is_open
                from read_parquet(?, union_by_name=true, hive_partitioning=false)
                where cal_date = ?
                limit 1
                """,
                [[str(path) for path in paths], on_date],
            ).fetchone()
        if row is None:
            return None
        return bool(row[0])

    def trading_dates(self, start: date, end: date) -> list[date]:
        paths = sorted(
            (self.warehouse_root / "facts/trade_calendar").glob(
                "cal_year=*/data.parquet"
            )
        )
        if not paths:
            raise FileNotFoundError("trade calendar facts are missing")
        with duckdb.connect() as connection:
            rows = connection.execute(
                """
                select distinct cal_date
                from read_parquet(?, union_by_name=true, hive_partitioning=false)
                where is_open = true and cal_date between ? and ?
                order by cal_date
                """,
                [[str(path) for path in paths], start, end],
            ).fetchall()
        return [row[0] for row in rows]

    def health_report(self, formation_date: date) -> dict[str, Any]:
        path = self.archive_root / "data_health" / f"{formation_date}.json"
        if not path.is_file():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def eligible_securities(self, on_date: date) -> dict[str, str]:
        paths = sorted(
            (self.warehouse_root / "facts/security_master").glob(
                "catalog_version=*/data.parquet"
            )
        )
        if not paths:
            return {}
        with duckdb.connect() as connection:
            rows = connection.execute(
                """
                select ts_code, name
                from read_parquet(?, union_by_name=true, hive_partitioning=false)
                where market in ('主板', '创业板')
                  and exchange in ('SSE', 'SZSE')
                  and list_status = 'L'
                  and valid_from <= ?
                  and (valid_to is null or valid_to > ?)
                  and upper(name) not like 'ST%'
                  and upper(name) not like '*ST%'
                qualify row_number() over (
                    partition by ts_code order by valid_from desc
                ) = 1
                order by ts_code
                """,
                [[str(path) for path in paths], on_date, on_date],
            ).fetchall()
        return {str(code): str(name) for code, name in rows}

    def adjusted_prices(
        self,
        ts_code: str,
        trading_dates: list[date],
    ) -> list[PricePoint] | None:
        equity_paths = [
            self.warehouse_root
            / "facts/equity_daily"
            / f"trade_date={day}"
            / "data.parquet"
            for day in trading_dates
        ]
        factor_paths = [
            self.warehouse_root
            / "facts/adj_factor"
            / f"trade_date={day}"
            / "data.parquet"
            for day in trading_dates
        ]
        if any(not path.is_file() for path in [*equity_paths, *factor_paths]):
            return None
        with duckdb.connect() as connection:
            rows = connection.execute(
                """
                select e.trade_date,
                       e.open * a.adj_factor as adjusted_open,
                       e.close * a.adj_factor as adjusted_close
                from read_parquet(?, union_by_name=true, hive_partitioning=false) e
                join read_parquet(?, union_by_name=true, hive_partitioning=false) a
                  on e.trade_date = a.trade_date and e.ts_code = a.ts_code
                where e.ts_code = ?
                order by e.trade_date
                """,
                [
                    [str(path) for path in equity_paths],
                    [str(path) for path in factor_paths],
                    ts_code,
                ],
            ).fetchall()
        return [
            PricePoint(
                trade_date=row[0],
                adjusted_open=float(row[1]),
                adjusted_close=float(row[2]),
            )
            for row in rows
        ]


def prepare_daily_selection(
    *,
    csv_path: Path,
    data: ForwardData,
    clock: Callable[[], datetime],
    sleep: Callable[[float], None] = system_sleep,
    formation_date: date | None = None,
    action_date: date | None = None,
    selection_as_of: datetime | None = None,
    rerun_date: date | None = None,
) -> RunSummary:
    """Freeze and validate a point-in-time selection context without starting AI."""

    context, failure = _prepare_selection_context(
        csv_path=csv_path,
        data=data,
        clock=clock,
        sleep=sleep,
        formation_date=formation_date,
        action_date=action_date,
        selection_as_of=selection_as_of,
        rerun_date=rerun_date,
    )
    if failure is not None:
        return failure
    assert context is not None
    formation_text = context.formation_date.isoformat()
    if _has_selection_decision(context.rows, formation_text):
        return _context_summary(context, status="already_selected")
    status = (
        "ready_for_research"
        if context.research_mode == "full"
        else "ready_for_research_limited"
    )
    return _context_summary(context, status=status)


def record_daily_selection(
    result: dict[str, Any],
    *,
    csv_path: Path,
    data: ForwardData,
    clock: Callable[[], datetime],
    formation_date: date,
    action_date: date,
    selection_as_of: datetime,
    sleep: Callable[[float], None] = system_sleep,
) -> RunSummary:
    """Validate and archive a result produced by the top-level Codex task."""

    context, failure = _prepare_selection_context(
        csv_path=csv_path,
        data=data,
        clock=clock,
        sleep=sleep,
        formation_date=formation_date,
        action_date=action_date,
        selection_as_of=selection_as_of,
        rerun_date=None,
    )
    if failure is not None:
        return failure
    assert context is not None
    return _record_daily_selection_with_context(
        result,
        context=context,
        csv_path=csv_path,
        data=data,
    )


def _record_daily_selection_with_context(
    result: dict[str, Any],
    *,
    context: _SelectionContext,
    csv_path: Path,
    data: ForwardData,
) -> RunSummary:
    formation_text = context.formation_date.isoformat()
    if _has_selection_decision(context.rows, formation_text):
        return _context_summary(context, status="already_selected")
    try:
        validated = _validate_result(
            result,
            data.eligible_securities(context.formation_date),
        )
        decision_rows = _decision_rows(
            validated,
            fieldnames=context.fieldnames,
            formation_date=context.formation_date,
            action_date=context.action_date,
            selection_as_of=context.selection_as_of,
        )
    except Exception as error:
        return _context_summary(
            context,
            status="invalid_result",
            error=_safe_error(error),
        )

    latest_fieldnames, latest_rows = _read_forward_log(csv_path)
    if _has_selection_decision(latest_rows, formation_text):
        return _context_summary(context, status="already_selected")
    if latest_fieldnames != context.fieldnames:
        decision_rows = [
            {field: row.get(field, "") for field in latest_fieldnames}
            for row in decision_rows
        ]
    _atomic_write_csv(
        csv_path,
        latest_fieldnames,
        [*latest_rows, *decision_rows],
    )
    return _context_summary(
        context,
        status="selection_frozen",
        new_forward_rows=len(decision_rows),
        selected_count=len(validated["selected_stocks"]),
    )


def record_daily_trace(
    trace: dict[str, Any],
    *,
    pending_path: Path,
    archive_dir: Path,
    csv_path: Path,
    data: ForwardData,
    clock: Callable[[], datetime],
    formation_date: date,
    action_date: date,
    selection_as_of: datetime,
    sleep: Callable[[float], None] = system_sleep,
) -> RunSummary:
    """Validate one complete trace, record its ResearchResult, and archive it."""

    context, failure = _prepare_selection_context(
        csv_path=csv_path,
        data=data,
        clock=clock,
        sleep=sleep,
        formation_date=formation_date,
        action_date=action_date,
        selection_as_of=selection_as_of,
        rerun_date=None,
    )
    if failure is not None:
        return failure
    assert context is not None
    try:
        validated = _validate_trace(
            trace,
            formation_date=formation_date,
            action_date=action_date,
            selection_as_of=selection_as_of,
            eligible=data.eligible_securities(formation_date),
        )
        _validate_trace_research_availability(
            validated,
            sector_research_available=context.sector_research_available,
            announcement_status=context.announcement_status,
            announcement_exchanges=context.announcement_exchanges,
        )
        _validate_trace_runtime_capabilities(validated, context)
    except Exception as error:
        return _context_summary(
            context,
            status="invalid_result",
            error=_safe_error(error),
        )

    forward_result = validated.research_result.model_dump()
    if isinstance(validated, DailyResearchTraceV4):
        forward_result = _confirmed_active_research_result(validated)
    summary = _record_daily_selection_with_context(
        forward_result,
        context=context,
        csv_path=csv_path,
        data=data,
    )
    if summary.status not in {"selection_frozen", "already_selected"}:
        return summary
    archive_dir = Path(archive_dir)
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_path = archive_dir / f"research-trace-{formation_date.isoformat()}.json"
    pending_path = Path(pending_path)
    if not archive_path.exists():
        os.replace(pending_path, archive_path)
        return summary
    try:
        pending_payload = json.loads(pending_path.read_text(encoding="utf-8"))
        archived_payload = json.loads(archive_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pending_payload = archived_payload = None
    if pending_payload is not None and pending_payload == archived_payload:
        pending_path.unlink()
        return summary
    return RunSummary(
        **{
            **asdict(summary),
            "status": "invalid_result",
            "error": "trace_conflict",
        }
    )


def _confirmed_active_research_result(
    trace: DailyResearchTraceV4,
) -> dict[str, Any]:
    """Build a Forward-only result while leaving the V4 trace untouched."""

    result = trace.research_result.model_dump()
    ledger = {
        item.ts_code: item.model_dump(mode="json")
        for item in trace.candidate_ledger
    }
    confirmed = [
        item.model_dump()
        for item in trace.research_result.selected_stocks
        if selection_output_class(
            trace_version=trace.trace_version,
            candidate=ledger.get(item.ts_code, {}),
        )
        == "confirmed_active"
    ]
    for priority, item in enumerate(confirmed, start=1):
        item["priority"] = priority
    result["selected_stocks"] = confirmed
    if confirmed:
        result["empty_reason"] = ""
    elif trace.research_result.selected_stocks:
        result["empty_reason"] = (
            "今天没有已确认正式推荐；等待首个交易日确认的事件线索不计入正式名单。"
        )
    return result


def _validate_trace_research_availability(
    trace: DailyResearchTrace | DailyResearchTraceV4,
    *,
    sector_research_available: bool,
    announcement_status: str,
    announcement_exchanges: tuple[str, ...],
) -> None:
    if not isinstance(trace, DailyResearchTraceV4):
        return
    if not sector_research_available:
        uses_sector_basis = any(
            candidate.opportunity_type == "sector_diffusion"
            or candidate.research_thesis.engine_type
            in {"sector_broad_diffusion", "sector_leader_cluster"}
            or "researching-sectors-industries" in candidate.source_skills
            for candidate in trace.candidate_ledger
        ) or any(
            decision.source_skill == "researching-sectors-industries"
            for decision in trace.decision_trace
        )
        if uses_sector_basis:
            raise ValueError("sector_research_unavailable")
    full_announcement_coverage = bool(
        announcement_status == "cninfo_complete"
        or (
            announcement_status == "exchange_complete"
            and announcement_exchanges == ("SSE", "SZSE")
        )
    )
    for candidate in trace.candidate_ledger:
        if candidate.research_thesis.engine_type != "fresh_event_pending":
            continue
        exchange = "SZSE" if candidate.ts_code.endswith(".SZ") else "SSE"
        if full_announcement_coverage:
            continue
        if (
            announcement_status == "exchange_partial"
            and exchange in announcement_exchanges
        ):
            continue
        raise ValueError("preopen_event_refresh_incomplete")


def _validate_trace_runtime_capabilities(
    trace: DailyResearchTrace | DailyResearchTraceV4,
    context: _SelectionContext,
) -> None:
    if not isinstance(trace, DailyResearchTraceV4):
        return
    declared = trace.runtime_capabilities
    if declared is None:
        raise ValueError("runtime_capabilities_missing")
    actual_flags = {
        "market_research_available": context.market_research_available,
        "price_research_available": context.price_research_available,
        "industry_research_available": context.industry_research_available,
        "theme_research_available": context.theme_research_available,
        "stock_context_available": context.stock_context_available,
    }
    for field, actual in actual_flags.items():
        if bool(getattr(declared, field)) and not actual:
            raise ValueError("runtime_capabilities_overclaim")
    declared_exchanges = set(declared.announcement_exchanges)
    if len(declared_exchanges) != len(declared.announcement_exchanges):
        raise ValueError("runtime_capabilities_invalid")
    if not declared_exchanges <= set(context.announcement_exchanges):
        raise ValueError("runtime_capabilities_overclaim")
    if declared.announcement_status in {
        "cninfo_complete",
        "exchange_complete",
    } and declared.announcement_status != context.announcement_status:
        raise ValueError("runtime_capabilities_overclaim")
    if (
        declared.announcement_status == "exchange_partial"
        and not declared_exchanges
    ):
        raise ValueError("runtime_capabilities_invalid")
    if (
        declared.announcement_status == "announcement_unavailable"
        and declared_exchanges
    ):
        raise ValueError("runtime_capabilities_invalid")
    if not set(context.limitations) <= set(declared.limitations):
        raise ValueError("runtime_capabilities_overclaim")


def _validate_trace_v3(
    trace: dict[str, Any],
    *,
    formation_date: date,
    action_date: date,
    selection_as_of: datetime,
    eligible: dict[str, str],
) -> DailyResearchTrace:
    try:
        payload = DailyResearchTrace.model_validate(trace)
    except ValidationError as error:
        raise ValueError("invalid_trace_structure") from error
    if payload.formation_date != formation_date:
        raise ValueError("trace_formation_date_mismatch")
    if payload.action_date != action_date:
        raise ValueError("trace_action_date_mismatch")
    if payload.as_of.tzinfo is None or payload.as_of.utcoffset() is None:
        raise ValueError("trace_as_of_timezone_missing")
    if _shanghai(payload.as_of) != _shanghai(selection_as_of):
        raise ValueError("trace_as_of_mismatch")

    ledger_codes = [item.ts_code for item in payload.candidate_ledger]
    if len(ledger_codes) != len(set(ledger_codes)):
        raise ValueError("duplicate_candidate_codes")
    ledger = {item.ts_code: item for item in payload.candidate_ledger}
    for item in payload.candidate_ledger:
        if eligible.get(item.ts_code) != item.name:
            raise ValueError("ineligible_trace_candidate")
        if len(item.source_skills) != len(set(item.source_skills)):
            raise ValueError("duplicate_candidate_source_skills")

    result = payload.research_result
    failed = (
        not result.research_completed
        or not result.point_in_time_evidence_verified
        or bool(result.failure_reason)
    )
    if failed and (result.selected_stocks or result.nearest_nonselections):
        raise ValueError("failed_research_candidates_present")
    for item in result.selected_stocks:
        ledger_item = ledger.get(item.ts_code)
        if ledger_item is not None and (
            item.name != ledger_item.name
            or item.opportunity_type != ledger_item.opportunity_type
        ):
            raise ValueError("selected_candidate_identity_mismatch")
    for item in result.nearest_nonselections:
        ledger_item = ledger.get(item.ts_code)
        if ledger_item is None or ledger_item.final_fate not in {
            "rejected",
            "unresolved",
        }:
            raise ValueError("nearest_candidate_fate_mismatch")
        if (
            item.name != ledger_item.name
            or item.opportunity_type != ledger_item.opportunity_type
        ):
            raise ValueError("nearest_candidate_identity_mismatch")
    validated_result = _validate_result(result.model_dump(), eligible)
    selected_codes = {
        str(item["ts_code"]) for item in validated_result["selected_stocks"]
    }
    ledger_selected = {
        code for code, item in ledger.items() if item.final_fate == "selected"
    }
    if selected_codes != ledger_selected:
        raise ValueError("selected_candidate_fate_mismatch")
    nearest_codes = {
        str(item["ts_code"])
        for item in validated_result["nearest_nonselections"]
    }
    allowed_price_ids = set(SCENARIO_SPECS) | {
        "raw_price",
        EVENT_REACTION_EVIDENCE_ID,
    }
    price_counts: dict[str, int] = {}
    decisions_by_id: dict[str, TraceDecision] = {}
    for decision in payload.decision_trace:
        if decision.decision_id in decisions_by_id:
            raise ValueError("duplicate_decision_ids")
        decisions_by_id[decision.decision_id] = decision
        if decision.ts_code not in ledger:
            raise ValueError("decision_trace_candidate_missing")
        for value in decision.formation_values.values():
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("formation_value_non_finite")
        if decision.source_skill == "analyzing-price-trading":
            if decision.evidence_id not in allowed_price_ids:
                raise ValueError("invalid_price_evidence_id")
            price_counts[decision.ts_code] = price_counts.get(decision.ts_code, 0) + 1
    for code in selected_codes | nearest_codes:
        if price_counts.get(code, 0) not in {1, 2}:
            raise ValueError("price_evidence_count_invalid")
    for code, candidate in ledger.items():
        thesis = candidate.research_thesis
        if thesis is None:
            raise ValueError("candidate_thesis_missing")
        expected_engine = {
            "company_catalyst": "company_event",
            "sector_diffusion": "sector_diffusion",
            "independent_price_anomaly": "stock_specific_demand",
        }[candidate.opportunity_type]
        if thesis.engine_type not in {expected_engine, "no_valid_engine"}:
            raise ValueError("engine_type_opportunity_mismatch")
        if (
            thesis.market_recognition.market_environment_id
            != payload.market_propagation_environment.environment_id
        ):
            raise ValueError("market_recognition_environment_mismatch")
        _validate_company_novelty_time(thesis, as_of=payload.as_of)
        cluster = thesis.sector_leader_cluster
        if thesis.engine_type == "sector_diffusion":
            if cluster is None:
                raise ValueError("sector_leader_cluster_missing")
            if len(cluster.members) != len(set(cluster.members)):
                raise ValueError("sector_cluster_duplicate_members")
            if code not in cluster.members:
                raise ValueError("sector_cluster_candidate_missing")
        elif cluster is not None:
            raise ValueError("sector_cluster_not_applicable")
        if len(thesis.decision_ids) != len(set(thesis.decision_ids)):
            raise ValueError("duplicate_thesis_decision_ids")
        referenced: list[TraceDecision] = []
        for decision_id in thesis.decision_ids:
            decision = decisions_by_id.get(decision_id)
            if decision is None:
                raise ValueError("thesis_decision_missing")
            if decision.ts_code != code:
                raise ValueError("thesis_decision_candidate_mismatch")
            referenced.append(decision)
        if candidate.final_fate != "selected":
            continue
        if thesis.engine_type == "no_valid_engine" or thesis.engine_status not in {
            "confirmed",
            "fresh_event_pending",
        }:
            raise ValueError("selected_engine_status_invalid")
        if not any(
            decision.source_skill == "researching-company-events"
            for decision in referenced
        ):
            raise ValueError("selected_thesis_company_evidence_missing")
        if thesis.engine_status == "confirmed":
            price_support = [
                decision
                for decision in referenced
                if decision.source_skill == "analyzing-price-trading"
                and decision.decision_role == "support"
            ]
            if not price_support:
                raise ValueError("selected_thesis_price_confirmation_missing")
            for decision in price_support:
                _validate_price_support_values(
                    decision,
                    formation_date=payload.formation_date,
                )
            if thesis.market_recognition.status not in {"confirmed", "partial"}:
                raise ValueError("confirmed_engine_market_recognition_invalid")
            if (
                thesis.engine_type == "sector_diffusion"
                and cluster is not None
                and cluster.candidate_role not in {"leader", "core", "follower"}
            ):
                raise ValueError("confirmed_sector_cluster_role_invalid")
        else:
            _validate_fresh_event_pending(
                thesis,
                referenced=referenced,
                formation_date=payload.formation_date,
                action_date=payload.action_date,
                as_of=payload.as_of,
            )
        if candidate.opportunity_type == "sector_diffusion" and not any(
            decision.source_skill == "researching-sectors-industries"
            for decision in referenced
        ):
            raise ValueError("sector_diffusion_thesis_evidence_missing")
    return payload


def _validate_price_support_values(
    decision: TraceDecision,
    *,
    formation_date: date,
) -> None:
    values = decision.formation_values
    observed = values.get("observation_date")
    try:
        observed_date = date.fromisoformat(str(observed))
    except (TypeError, ValueError):
        raise ValueError("price_support_observation_date_missing") from None
    if observed_date > formation_date:
        raise ValueError("price_support_observation_date_after_formation")
    numeric = {
        key: float(value)
        for key, value in values.items()
        if not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
    }
    price_keys = {
        key
        for key in numeric
        if key in {"close", "adjusted_close"}
        or key.startswith("return_")
        or key.startswith("event_return_")
    }
    if not price_keys:
        raise ValueError("price_support_price_value_missing")
    amount_keys = {
        key
        for key in numeric
        if key in {"amount", "liquidity_log10_amount"}
        or key.startswith("amount_ratio_")
    }
    if not amount_keys:
        raise ValueError("price_support_amount_value_missing")
    if not any(numeric[key] > 0.0 for key in amount_keys):
        raise ValueError("price_support_amount_value_invalid")
    relative_keys = {
        key
        for key in numeric
        if key.startswith("relative_market_")
        or key.startswith("relative_industry_")
    }
    if not relative_keys:
        raise ValueError("price_support_relative_value_missing")


def _validate_company_novelty_time(
    thesis: ResearchThesis,
    *,
    as_of: datetime,
) -> None:
    novelty = thesis.company_information_novelty
    if (novelty.event_id is None) != (novelty.event_available_at is None):
        raise ValueError("company_event_identity_incomplete")
    if novelty.event_available_at is None:
        return
    event_time = novelty.event_available_at
    if event_time.tzinfo is None or event_time.utcoffset() is None:
        raise ValueError("company_event_available_at_timezone_missing")
    if _shanghai(event_time) > _shanghai(as_of):
        raise ValueError("company_event_available_after_as_of")


def _validate_fresh_event_pending(
    thesis: ResearchThesis,
    *,
    referenced: list[TraceDecision],
    formation_date: date,
    action_date: date,
    as_of: datetime,
) -> None:
    novelty = thesis.company_information_novelty
    if thesis.engine_type != "company_event":
        raise ValueError("fresh_event_engine_type_invalid")
    if novelty.disclosure_novelty not in {
        "first_disclosure",
        "incremental_update",
    }:
        raise ValueError("fresh_event_novelty_invalid")
    if novelty.new_information_level not in {
        "major_new_information",
        "material_increment",
    }:
        raise ValueError("fresh_event_information_level_invalid")
    if thesis.market_recognition.status != "not_yet_observable":
        raise ValueError("fresh_event_market_recognition_invalid")
    if not novelty.event_id or novelty.event_available_at is None:
        raise ValueError("fresh_event_identity_missing")
    event_time = novelty.event_available_at
    if event_time.tzinfo is None or event_time.utcoffset() is None:
        raise ValueError("fresh_event_available_at_timezone_missing")
    local_event_time = _shanghai(event_time)
    if local_event_time > _shanghai(as_of):
        raise ValueError("fresh_event_available_after_as_of")
    if local_event_time.date() != formation_date or local_event_time.time() < time(15):
        raise ValueError("fresh_event_not_after_formation_close")
    action_id = thesis.action_condition_decision_id
    if not action_id or action_id not in thesis.decision_ids:
        raise ValueError("fresh_event_action_condition_missing")
    action = next(
        (decision for decision in referenced if decision.decision_id == action_id),
        None,
    )
    if (
        action is None
        or action.source_skill != "analyzing-price-trading"
        or action.evidence_id != EVENT_REACTION_EVIDENCE_ID
        or action.decision_role != "action_condition"
    ):
        raise ValueError("fresh_event_action_condition_invalid")
    values = action.formation_values
    if (
        str(values.get("event_id", "")) != novelty.event_id
        or str(values.get("reaction_window_status", ""))
        != "awaiting_first_session"
        or str(values.get("reaction_start_date", "")) != action_date.isoformat()
    ):
        raise ValueError("fresh_event_reaction_boundary_invalid")
    try:
        decision_event_time = datetime.fromisoformat(
            str(values.get("event_available_at", ""))
        )
    except ValueError:
        raise ValueError("fresh_event_reaction_boundary_invalid") from None
    if (
        decision_event_time.tzinfo is None
        or _shanghai(decision_event_time) != local_event_time
    ):
        raise ValueError("fresh_event_reaction_boundary_invalid")


_V4_PRICE_VALUE_KEYS = {
    "close", "adjusted_close",
    "return_1d", "return_3d", "return_5d", "return_20d",
    "event_return_1d", "event_return_3d", "event_return_5d",
}
_V4_AMOUNT_VALUE_KEYS = {
    "amount", "liquidity_log10_amount", "amount_ratio_last_20d",
    "amount_ratio_1d", "amount_ratio_3d", "amount_ratio_5d",
}
_V4_RELATIVE_VALUE_KEYS = {
    "relative_market_1d", "relative_market_3d", "relative_market_5d",
    "relative_market_20d", "relative_market_return_1d",
    "relative_market_return_3d", "relative_market_return_5d",
    "relative_industry_return_1d", "relative_industry_return_3d",
    "relative_industry_return_5d", "relative_industry_return_20d",
    "relative_return_1d", "relative_return_3d", "relative_return_5d",
    "relative_return_20d",
}
_V4_PATH_QUALITY_KEYS = {
    "volume_price_efficiency_5d", "price_amount_efficiency_20d",
    "mean_close_position_5d", "mean_close_location_1d",
    "mean_close_location_3d", "mean_close_location_5d",
    "mean_upper_shadow_ratio_1d", "mean_upper_shadow_ratio_3d",
    "mean_upper_shadow_ratio_5d", "high_to_close_pullback_1d",
    "high_to_close_pullback_3d", "high_to_close_pullback_5d",
    "breakout_vs_prior60", "breakout_prior_250d_high",
    "volume_amplification_days_5d", "upper_shadow_frequency_5d",
    "fade_frequency_5d", "limit_up_return_contribution_5d",
    "efficiency_ratio_20d", "adx_14d", "dmi_directional_spread_14d",
    "target_atr_distance_20pct", "relative_strength_consistency_5d",
}
_V4_PRE_EVENT_RELATIVE_KEYS = {
    "pre_event_relative_market_5d", "pre_event_relative_industry_5d",
}
_V4_PRE_EVENT_RISK_KEYS = {
    "pre_event_return_5d", "pre_event_return_20d",
    "target_atr_distance_20pct", "distance_to_prior_high_atr",
    "max_single_day_return_20d", "limit_up_return_contribution_5d",
}


def _validate_trace(
    trace: dict[str, Any],
    *,
    formation_date: date,
    action_date: date,
    selection_as_of: datetime,
    eligible: dict[str, str],
) -> DailyResearchTrace | DailyResearchTraceV4:
    version = str(trace.get("trace_version", ""))
    if formation_date >= V4_EFFECTIVE_FORMATION_DATE and version != "daily-research-trace-v4":
        raise ValueError("v4_trace_required_for_new_formation_date")
    if version == "daily-research-trace-v4":
        return _validate_trace_v4(
            trace,
            formation_date=formation_date,
            action_date=action_date,
            selection_as_of=selection_as_of,
            eligible=eligible,
        )
    if version == "daily-research-trace-v3":
        return _validate_trace_v3(
            trace,
            formation_date=formation_date,
            action_date=action_date,
            selection_as_of=selection_as_of,
            eligible=eligible,
        )
    raise ValueError("unsupported_trace_version")


def _validate_trace_v4(
    trace: dict[str, Any],
    *,
    formation_date: date,
    action_date: date,
    selection_as_of: datetime,
    eligible: dict[str, str],
) -> DailyResearchTraceV4:
    try:
        payload = DailyResearchTraceV4.model_validate(trace)
    except ValidationError as error:
        raise ValueError("invalid_trace_v4_structure") from error
    if payload.formation_date != formation_date:
        raise ValueError("trace_formation_date_mismatch")
    if payload.action_date != action_date:
        raise ValueError("trace_action_date_mismatch")
    if payload.as_of.tzinfo is None or payload.as_of.utcoffset() is None:
        raise ValueError("trace_as_of_timezone_missing")
    if _shanghai(payload.as_of) != _shanghai(selection_as_of):
        raise ValueError("trace_as_of_mismatch")
    if len(payload.market_risk_overlays) != len(set(payload.market_risk_overlays)):
        raise ValueError("duplicate_market_risk_overlays")

    ledger_codes = [item.ts_code for item in payload.candidate_ledger]
    if len(ledger_codes) != len(set(ledger_codes)):
        raise ValueError("duplicate_candidate_codes")
    ledger = {item.ts_code: item for item in payload.candidate_ledger}
    for item in payload.candidate_ledger:
        if eligible.get(item.ts_code) != item.name:
            raise ValueError("ineligible_trace_candidate")
        if len(item.source_skills) != len(set(item.source_skills)):
            raise ValueError("duplicate_candidate_source_skills")

    result = payload.research_result
    failed = (
        not result.research_completed
        or not result.point_in_time_evidence_verified
        or bool(result.failure_reason)
    )
    if failed and (result.selected_stocks or result.nearest_nonselections):
        raise ValueError("failed_research_candidates_present")
    for item in result.selected_stocks:
        ledger_item = ledger.get(item.ts_code)
        if ledger_item is None or (
            item.name != ledger_item.name
            or item.opportunity_type != ledger_item.opportunity_type
        ):
            raise ValueError("selected_candidate_identity_mismatch")
    for item in result.nearest_nonselections:
        ledger_item = ledger.get(item.ts_code)
        if ledger_item is None or ledger_item.final_fate not in {"rejected", "unresolved"}:
            raise ValueError("nearest_candidate_fate_mismatch")
        if (
            item.name != ledger_item.name
            or item.opportunity_type != ledger_item.opportunity_type
        ):
            raise ValueError("nearest_candidate_identity_mismatch")
    validated_result = _validate_result(result.model_dump(), eligible)
    selected_codes = {
        str(item["ts_code"]) for item in validated_result["selected_stocks"]
    }
    ledger_selected = {
        code for code, item in ledger.items() if item.final_fate == "selected"
    }
    if selected_codes != ledger_selected:
        raise ValueError("selected_candidate_fate_mismatch")
    nearest_codes = {
        str(item["ts_code"]) for item in validated_result["nearest_nonselections"]
    }

    allowed_price_ids = set(SCENARIO_SPECS) | {
        "raw_price", EVENT_REACTION_EVIDENCE_ID,
    }
    decisions_by_id: dict[str, TraceDecision] = {}
    price_counts: dict[str, int] = {}
    for decision in payload.decision_trace:
        if decision.decision_id in decisions_by_id:
            raise ValueError("duplicate_decision_ids")
        decisions_by_id[decision.decision_id] = decision
        if decision.ts_code not in ledger:
            raise ValueError("decision_trace_candidate_missing")
        for value in decision.formation_values.values():
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("formation_value_non_finite")
        if decision.source_skill == "analyzing-price-trading":
            if decision.evidence_id not in allowed_price_ids:
                raise ValueError("invalid_price_evidence_id")
            price_counts[decision.ts_code] = price_counts.get(decision.ts_code, 0) + 1
    for code in selected_codes | nearest_codes:
        if price_counts.get(code, 0) not in {1, 2}:
            raise ValueError("price_evidence_count_invalid")

    for code, candidate in ledger.items():
        thesis = candidate.research_thesis
        _validate_v4_engine_shape(candidate)
        _validate_v4_company_information(thesis.company_information, as_of=payload.as_of)
        _validate_v4_sector_evidence(code, thesis)
        referenced = _resolve_v4_decisions(
            code=code,
            decision_ids=thesis.decision_ids,
            decisions_by_id=decisions_by_id,
        )
        if candidate.final_fate != "selected":
            continue
        _validate_v4_selected_candidate(
            candidate,
            referenced=referenced,
            formation_date=payload.formation_date,
            action_date=payload.action_date,
            as_of=payload.as_of,
        )
    return payload


def _validate_v4_engine_shape(candidate: TraceCandidateV4) -> None:
    thesis = candidate.research_thesis
    expected_opportunity = {
        "fresh_event_pending": "company_catalyst",
        "event_repricing_confirmed": "company_catalyst",
        "sector_broad_diffusion": "sector_diffusion",
        "sector_leader_cluster": "sector_diffusion",
        "independent_demand_acceleration": "independent_price_anomaly",
    }.get(thesis.engine_type)
    if expected_opportunity and candidate.opportunity_type != expected_opportunity:
        raise ValueError("engine_type_opportunity_mismatch")
    expected_status = {
        "fresh_event_pending": "conditional",
        "event_repricing_confirmed": "active",
        "sector_broad_diffusion": "active",
        "sector_leader_cluster": "active",
        "independent_demand_acceleration": "active",
        "anchor_only": "inactive",
        "unresolved": "unresolved",
    }[thesis.engine_type]
    if thesis.engine_status != expected_status:
        raise ValueError("engine_type_status_mismatch")
    expected_recognition = {
        "fresh_event_pending": "pending",
        "event_repricing_confirmed": "confirmed",
        "sector_broad_diffusion": "confirmed",
        "sector_leader_cluster": "confirmed",
        "independent_demand_acceleration": "confirmed",
    }.get(thesis.engine_type)
    if expected_recognition and thesis.market_recognition.status != expected_recognition:
        raise ValueError("engine_market_recognition_mismatch")
    if candidate.final_fate == "selected" and thesis.engine_type in {"anchor_only", "unresolved"}:
        raise ValueError("selected_engine_type_invalid")


def _validate_v4_company_information(
    info: CompanyInformationV4,
    *,
    as_of: datetime,
) -> None:
    if (info.event_id is None) != (info.event_available_at is None):
        raise ValueError("company_event_identity_incomplete")
    if info.event_available_at is not None:
        if info.event_available_at.tzinfo is None or info.event_available_at.utcoffset() is None:
            raise ValueError("company_event_available_at_timezone_missing")
        if _shanghai(info.event_available_at) > _shanghai(as_of):
            raise ValueError("company_event_available_after_as_of")
    if info.first_or_repeat == "not_applicable" and info.new_information_level not in {"not_applicable", "unknown"}:
        raise ValueError("company_information_not_applicable_mismatch")


def _validate_v4_sector_evidence(code: str, thesis: ResearchThesisV4) -> None:
    broad = thesis.sector_broad_diffusion
    cluster = thesis.sector_leader_cluster
    if thesis.engine_type == "sector_broad_diffusion":
        if broad is None or cluster is not None:
            raise ValueError("sector_broad_diffusion_evidence_invalid")
        if not (
            broad.relative_return_3d > 0.0
            and broad.relative_return_5d > 0.0
            and broad.median_return_3d > 0.0
            and broad.median_return_5d > 0.0
            and broad.breadth_3d > 0.5
            and broad.breadth_5d > 0.5
            and broad.turnover_share_change_5d > 0.0
            and broad.top3_positive_contribution < 0.80
            and broad.candidate_role in {"leader_confirmed", "core_diffusion_member"}
        ):
            raise ValueError("sector_broad_diffusion_conditions_invalid")
    elif thesis.engine_type == "sector_leader_cluster":
        if cluster is None or broad is not None:
            raise ValueError("sector_leader_cluster_evidence_invalid")
        required = max(3, math.ceil(cluster.effective_member_count * 0.05))
        member_codes = [member.ts_code for member in cluster.members]
        if len(member_codes) != len(set(member_codes)):
            raise ValueError("sector_cluster_duplicate_members")
        if code not in member_codes:
            raise ValueError("sector_cluster_candidate_missing")
        member_conditions_hold = all(
            member.relative_market_3d > 0.0
            and member.relative_market_5d > 0.0
            and member.industry_percentile_5d >= 0.75
            for member in cluster.members
        )
        if not (
            cluster.required_leader_count == required
            and cluster.qualifying_leader_count >= required
            and len(cluster.members) == cluster.qualifying_leader_count
            and member_conditions_hold
            and cluster.relative_return_3d > 0.0
            and cluster.relative_return_5d > 0.0
            and cluster.turnover_share_change_5d > 0.0
            and cluster.top1_positive_contribution <= 0.60
            and cluster.candidate_industry_percentile_5d >= 0.75
            and cluster.candidate_role in {"leader_confirmed", "core_diffusion_member"}
        ):
            raise ValueError("sector_leader_cluster_conditions_invalid")
    elif broad is not None or cluster is not None:
        raise ValueError("sector_evidence_not_applicable")


def _resolve_v4_decisions(
    *,
    code: str,
    decision_ids: list[str],
    decisions_by_id: dict[str, TraceDecision],
) -> list[TraceDecision]:
    if len(decision_ids) != len(set(decision_ids)):
        raise ValueError("duplicate_thesis_decision_ids")
    referenced: list[TraceDecision] = []
    for decision_id in decision_ids:
        decision = decisions_by_id.get(decision_id)
        if decision is None:
            raise ValueError("thesis_decision_missing")
        if decision.ts_code != code:
            raise ValueError("thesis_decision_candidate_mismatch")
        referenced.append(decision)
    return referenced


def _validate_v4_selected_candidate(
    candidate: TraceCandidateV4,
    *,
    referenced: list[TraceDecision],
    formation_date: date,
    action_date: date,
    as_of: datetime,
) -> None:
    thesis = candidate.research_thesis
    if thesis.engine_status == "conditional":
        _validate_v4_fresh_event_pending(
            thesis,
            referenced=referenced,
            formation_date=formation_date,
            action_date=action_date,
            as_of=as_of,
        )
        return
    if thesis.engine_status != "active":
        raise ValueError("selected_engine_status_invalid")
    company_decisions = [
        item for item in referenced if item.source_skill == "researching-company-events"
    ]
    if not company_decisions:
        raise ValueError("selected_thesis_company_evidence_missing")
    price_support = [
        item for item in referenced
        if item.source_skill == "analyzing-price-trading" and item.decision_role == "support"
    ]
    if not price_support:
        raise ValueError("selected_thesis_price_confirmation_missing")
    for decision in price_support:
        _validate_v4_price_support_values(decision, formation_date=formation_date)
    if thesis.engine_type == "event_repricing_confirmed":
        info = thesis.company_information
        if info.new_information_level not in {"substantive_new", "incremental_detail"}:
            raise ValueError("confirmed_event_information_level_invalid")
        if not info.event_id or info.event_available_at is None:
            raise ValueError("confirmed_event_identity_missing")
        if info.tradable_sessions_since_event is None or info.tradable_sessions_since_event < 1:
            raise ValueError("confirmed_event_sessions_invalid")
        if not any(
            item.decision_role == "support"
            and str(item.formation_values.get("event_id", "")) == info.event_id
            for item in company_decisions
        ):
            raise ValueError("confirmed_event_company_support_missing")
        if not any(
            item.evidence_id == EVENT_REACTION_EVIDENCE_ID
            and str(item.formation_values.get("event_id", "")) == info.event_id
            for item in price_support
        ):
            raise ValueError("confirmed_event_price_reaction_missing")
    if thesis.engine_type in {"sector_broad_diffusion", "sector_leader_cluster"}:
        if not any(
            item.source_skill == "researching-sectors-industries"
            and item.decision_role == "support"
            and item.evidence_id == thesis.engine_type
            for item in referenced
        ):
            raise ValueError("sector_engine_support_missing")


def _finite_v4_values(values: dict[str, Any]) -> dict[str, float]:
    return {
        key: float(value)
        for key, value in values.items()
        if not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
    }


def _validate_v4_price_support_values(
    decision: TraceDecision,
    *,
    formation_date: date,
) -> None:
    values = decision.formation_values
    try:
        observed_date = date.fromisoformat(str(values.get("observation_date", "")))
    except ValueError:
        raise ValueError("price_support_observation_date_missing") from None
    if observed_date > formation_date:
        raise ValueError("price_support_observation_date_after_formation")
    numeric = _finite_v4_values(values)
    if not (_V4_PRICE_VALUE_KEYS & numeric.keys()):
        raise ValueError("price_support_price_value_missing")
    amount_keys = _V4_AMOUNT_VALUE_KEYS & numeric.keys()
    if not amount_keys:
        raise ValueError("price_support_amount_value_missing")
    if not any(numeric[key] > 0.0 for key in amount_keys):
        raise ValueError("price_support_amount_value_invalid")
    if not (_V4_RELATIVE_VALUE_KEYS & numeric.keys()):
        raise ValueError("price_support_relative_value_missing")
    if not (_V4_PATH_QUALITY_KEYS & numeric.keys()):
        raise ValueError("price_support_path_quality_missing")
    if decision.evidence_id == EVENT_REACTION_EVIDENCE_ID:
        if decision.evidence_version != "event-price-reaction-v3":
            raise ValueError("event_price_support_version_invalid")
        if str(values.get("reaction_window_status", "")) not in {"partial", "complete"}:
            raise ValueError("event_price_support_window_invalid")
        try:
            sessions = int(values.get("observed_reaction_sessions", 0))
        except (TypeError, ValueError):
            sessions = 0
        if sessions < 1:
            raise ValueError("event_price_support_sessions_invalid")
        if str(values.get("event_timing_status", "")) == "intraday_unresolved":
            raise ValueError("event_price_support_timing_invalid")


def _validate_v4_fresh_event_pending(
    thesis: ResearchThesisV4,
    *,
    referenced: list[TraceDecision],
    formation_date: date,
    action_date: date,
    as_of: datetime,
) -> None:
    if thesis.engine_type != "fresh_event_pending":
        raise ValueError("conditional_engine_type_invalid")
    info = thesis.company_information
    if info.first_or_repeat != "first":
        raise ValueError("fresh_event_first_disclosure_required")
    if info.new_information_level != "substantive_new":
        raise ValueError("fresh_event_information_level_invalid")
    if info.business_link != "direct":
        raise ValueError("fresh_event_business_link_invalid")
    if info.tradable_sessions_since_event != 0:
        raise ValueError("fresh_event_sessions_invalid")
    if not info.event_id or info.event_available_at is None:
        raise ValueError("fresh_event_identity_missing")
    event_time = _shanghai(info.event_available_at)
    if event_time > _shanghai(as_of):
        raise ValueError("fresh_event_available_after_as_of")
    formation_close = datetime.combine(formation_date, time(15), SHANGHAI)
    action_open = datetime.combine(action_date, MARKET_OPEN, SHANGHAI)
    if event_time < formation_close:
        raise ValueError("fresh_event_not_after_formation_close")
    if event_time >= action_open:
        raise ValueError("fresh_event_not_before_action_open")
    if event_time.date() == formation_date:
        expected_timing_status = "after_close"
    elif event_time.date() == action_date:
        expected_timing_status = "preopen"
    else:
        expected_timing_status = "nontrading_day"
    company_support = [
        item for item in referenced
        if item.source_skill == "researching-company-events"
        and item.decision_role == "support"
        and str(item.formation_values.get("event_id", "")) == info.event_id
    ]
    if not company_support:
        raise ValueError("fresh_event_company_support_missing")
    action_id = thesis.action_condition_decision_id
    if not action_id or action_id not in thesis.decision_ids:
        raise ValueError("fresh_event_action_condition_missing")
    action = next((item for item in referenced if item.decision_id == action_id), None)
    if (
        action is None
        or action.source_skill != "analyzing-price-trading"
        or action.evidence_id != EVENT_REACTION_EVIDENCE_ID
        or action.evidence_version != "event-price-reaction-v3"
        or action.decision_role != "action_condition"
    ):
        raise ValueError("fresh_event_action_condition_invalid")
    values = action.formation_values
    if (
        str(values.get("event_id", "")) != info.event_id
        or str(values.get("reaction_window_status", "")) != "awaiting_first_session"
        or int(values.get("observed_reaction_sessions", -1)) != 0
        or str(values.get("reaction_start_date", "")) != action_date.isoformat()
        or str(values.get("event_timing_status", "")) != expected_timing_status
    ):
        raise ValueError("fresh_event_reaction_boundary_invalid")
    try:
        decision_event_time = datetime.fromisoformat(str(values.get("event_available_at", "")))
    except ValueError:
        raise ValueError("fresh_event_reaction_boundary_invalid") from None
    if decision_event_time.tzinfo is None or _shanghai(decision_event_time) != event_time:
        raise ValueError("fresh_event_reaction_boundary_invalid")
    numeric = _finite_v4_values(values)
    if not (_V4_PRE_EVENT_RELATIVE_KEYS & numeric.keys()):
        raise ValueError("fresh_event_pre_event_relative_missing")
    if not (_V4_PRE_EVENT_RISK_KEYS & numeric.keys()):
        raise ValueError("fresh_event_pre_event_risk_missing")


def _prepare_selection_context(
    *,
    csv_path: Path,
    data: ForwardData,
    clock: Callable[[], datetime],
    sleep: Callable[[float], None],
    formation_date: date | None,
    action_date: date | None,
    selection_as_of: datetime | None,
    rerun_date: date | None,
) -> tuple[_SelectionContext | None, RunSummary | None]:
    started = _shanghai(clock())
    run_mode: Literal["normal", "rerun"] = (
        "rerun" if rerun_date is not None else "normal"
    )
    summary_base = {
        "started_at": started.isoformat(timespec="seconds"),
        "run_mode": run_mode,
    }
    explicit_context = any(
        value is not None
        for value in (formation_date, action_date, selection_as_of)
    )
    if rerun_date is not None and explicit_context:
        return None, RunSummary(
            status="invalid_selection_context",
            error="rerun_date_cannot_mix_with_explicit_context",
            **summary_base,
        )
    if explicit_context and not all(
        value is not None
        for value in (formation_date, action_date, selection_as_of)
    ):
        return None, RunSummary(
            status="invalid_selection_context",
            error="formation_date_action_date_and_as_of_are_required_together",
            **summary_base,
        )
    if rerun_date is not None:
        action_date = rerun_date
        selection_as_of = datetime.combine(
            rerun_date,
            SELECTION_START,
            SHANGHAI,
        )
        if rerun_date > started.date():
            return None, RunSummary(
                status="invalid_selection_context",
                action_date=rerun_date.isoformat(),
                selection_as_of=selection_as_of.isoformat(timespec="seconds"),
                error="rerun_date_must_not_be_future",
                **summary_base,
            )
    elif not explicit_context and (
        started.time() < SELECTION_START or started.time() >= MARKET_OPEN
    ):
        return None, RunSummary(status="outside_selection_window", **summary_base)

    if action_date is None:
        action_date = started.date()
    if selection_as_of is None:
        selection_as_of = started
    selection_as_of = _shanghai(selection_as_of)
    market_open = datetime.combine(action_date, MARKET_OPEN, SHANGHAI)
    if selection_as_of >= market_open:
        return None, RunSummary(
            status="invalid_selection_cutoff",
            action_date=action_date.isoformat(),
            selection_as_of=selection_as_of.isoformat(timespec="seconds"),
            error="selection_as_of_must_precede_action_open",
            **summary_base,
        )

    fieldnames, rows = _read_forward_log(csv_path)
    action_date_status = data.trading_day_status(action_date)
    if action_date_status is None:
        return None, RunSummary(
            status="data_not_ready",
            action_date=action_date.isoformat(),
            error="action_date_calendar_missing",
            **summary_base,
        )
    if not action_date_status:
        return None, RunSummary(
            status="non_trading_day",
            action_date=action_date.isoformat(),
            **summary_base,
        )

    calendar_start = action_date - timedelta(days=730)
    calendar_end = action_date + timedelta(days=60)
    open_dates = sorted(set(data.trading_dates(calendar_start, calendar_end)))
    prior_dates = [day for day in open_dates if day < action_date]
    if not prior_dates:
        return None, RunSummary(
            status="data_not_ready",
            action_date=action_date.isoformat(),
            error="no_prior_trading_date",
            **summary_base,
        )
    expected_formation_date = prior_dates[-1]
    if formation_date is None:
        formation_date = expected_formation_date
    elif formation_date != expected_formation_date:
        return None, RunSummary(
            status="invalid_selection_context",
            formation_date=formation_date.isoformat(),
            action_date=action_date.isoformat(),
            selection_as_of=selection_as_of.isoformat(timespec="seconds"),
            error="formation_date_is_not_prior_trading_date",
            **summary_base,
        )
    (
        research_mode,
        market_research_available,
        price_research_available,
        industry_research_available,
        theme_research_available,
        sector_research_available,
        stock_context_available,
        preopen_event_refresh_complete,
        announcement_status,
        announcement_exchanges,
        limitations,
        readiness_error,
    ) = _wait_until_data_ready(
        data=data,
        formation_date=formation_date,
        action_date=action_date,
        clock=clock,
        sleep=sleep,
        run_mode=run_mode,
        explicit_context=explicit_context,
    )
    if readiness_error:
        return None, RunSummary(
            status="data_not_ready",
            formation_date=formation_date.isoformat(),
            action_date=action_date.isoformat(),
            selection_as_of=selection_as_of.isoformat(timespec="seconds"),
            market_research_available=market_research_available,
            price_research_available=price_research_available,
            industry_research_available=industry_research_available,
            theme_research_available=theme_research_available,
            sector_research_available=sector_research_available,
            stock_context_available=stock_context_available,
            preopen_event_refresh_complete=(
                preopen_event_refresh_complete
            ),
            announcement_status=announcement_status,
            announcement_exchanges=announcement_exchanges,
            limitations=limitations,
            error=readiness_error,
            **summary_base,
        )

    updated_rows, settled = apply_mature_settlements(
        rows,
        open_dates=open_dates,
        price_loader=data.adjusted_prices,
        conditional_selection_keys=_archived_conditional_selection_keys(
            csv_path.parent
        ),
    )
    if settled:
        _atomic_write_csv(csv_path, fieldnames, updated_rows)
        rows = updated_rows

    return _SelectionContext(
        started_at=summary_base["started_at"],
        run_mode=run_mode,
        research_mode=research_mode,
        market_research_available=market_research_available,
        price_research_available=price_research_available,
        industry_research_available=industry_research_available,
        theme_research_available=theme_research_available,
        sector_research_available=sector_research_available,
        stock_context_available=stock_context_available,
        preopen_event_refresh_complete=preopen_event_refresh_complete,
        announcement_status=announcement_status,
        announcement_exchanges=announcement_exchanges,
        limitations=limitations,
        formation_date=formation_date,
        action_date=action_date,
        selection_as_of=selection_as_of,
        fieldnames=fieldnames,
        rows=rows,
        open_dates=open_dates,
        settled_rows=settled,
    ), None


def _context_summary(
    context: _SelectionContext,
    *,
    status: str,
    new_forward_rows: int = 0,
    selected_count: int = 0,
    error: str = "",
) -> RunSummary:
    return RunSummary(
        status=status,
        started_at=context.started_at,
        run_mode=context.run_mode,
        research_mode=context.research_mode,
        market_research_available=context.market_research_available,
        price_research_available=context.price_research_available,
        industry_research_available=context.industry_research_available,
        theme_research_available=context.theme_research_available,
        sector_research_available=context.sector_research_available,
        stock_context_available=context.stock_context_available,
        preopen_event_refresh_complete=context.preopen_event_refresh_complete,
        announcement_status=context.announcement_status,
        announcement_exchanges=context.announcement_exchanges,
        limitations=context.limitations,
        formation_date=context.formation_date.isoformat(),
        action_date=context.action_date.isoformat(),
        selection_as_of=context.selection_as_of.isoformat(timespec="seconds"),
        data_ready=True,
        new_forward_rows=new_forward_rows,
        selected_count=selected_count,
        settled_rows=context.settled_rows,
        error=error,
    )


def apply_mature_settlements(
    rows: list[dict[str, str]],
    *,
    open_dates: list[date],
    price_loader: Callable[[str, list[date]], list[PricePoint] | None],
    conditional_selection_keys: set[tuple[str, str]] | None = None,
) -> tuple[list[dict[str, str]], int]:
    updated = [dict(row) for row in rows]
    sessions = sorted(set(open_dates))
    excluded = conditional_selection_keys or set()
    settled = 0
    for row in updated:
        if not row.get("ts_code") or row.get("final_fate") == "empty_selection":
            continue
        key = (str(row.get("formation_date", "")), str(row["ts_code"]))
        if key in excluded:
            continue
        if _settlement_complete(row):
            continue
        try:
            action_date = date.fromisoformat(row.get("action_date", ""))
        except ValueError:
            continue
        window = [day for day in sessions if day >= action_date][:20]
        if len(window) != 20 or window[0] != action_date:
            continue
        points = price_loader(row["ts_code"], window)
        if not _valid_price_path(points, window):
            continue
        assert points is not None
        entry = points[0].adjusted_open
        close_returns = [point.adjusted_close / entry - 1.0 for point in points]
        hit_days = [
            index
            for index, value in enumerate(close_returns, start=1)
            if value >= 0.20 - 1e-12
        ]
        row["hit_20pct_close_within_20d"] = "true" if hit_days else "false"
        row["first_hit_day"] = str(hit_days[0]) if hit_days else ""
        row[MAX_RETURN_FIELD] = _format_percent(max(close_returns) * 100.0)
        row["terminal_return_20d"] = _format_percent(close_returns[-1] * 100.0)
        settled += 1
    return updated, settled


def _archived_conditional_selection_keys(
    archive_dir: Path,
) -> set[tuple[str, str]]:
    """Find frozen V4 conditional selections beside the Forward log."""

    keys: set[tuple[str, str]] = set()
    for path in sorted(Path(archive_dir).glob("research-trace-*.json")):
        try:
            trace = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if (
            not isinstance(trace, dict)
            or trace.get("trace_version") != "daily-research-trace-v4"
        ):
            continue
        formation_date = str(trace.get("formation_date", ""))
        result = trace.get("research_result")
        selected_codes = {
            str(item.get("ts_code", ""))
            for item in (
                result.get("selected_stocks", [])
                if isinstance(result, dict)
                else []
            )
            if isinstance(item, dict)
        }
        for candidate in trace.get("candidate_ledger", []):
            if not isinstance(candidate, dict):
                continue
            code = str(candidate.get("ts_code", ""))
            if code not in selected_codes:
                continue
            if selection_output_class(
                trace_version="daily-research-trace-v4",
                candidate=candidate,
            ) == "conditional_event":
                keys.add((formation_date, code))
    return keys


def _wait_until_data_ready(
    *,
    data: ForwardData,
    formation_date: date,
    action_date: date,
    clock: Callable[[], datetime],
    sleep: Callable[[float], None],
    run_mode: Literal["normal", "rerun"],
    explicit_context: bool,
) -> tuple[
    Literal["full", "limited", ""],
    bool,
    bool,
    bool,
    bool,
    bool,
    bool,
    bool,
    str,
    tuple[str, ...],
    tuple[str, ...],
    str,
]:
    market_open = datetime.combine(action_date, MARKET_OPEN, SHANGHAI)
    while True:
        checked_at = _shanghai(clock())
        report = data.health_report(formation_date)
        feature_ready = {
            str(item.get("feature_set", "")): bool(item.get("ready"))
            for item in report.get("derived_features", [])
            if isinstance(item, dict)
        }
        report_date_matches = (
            report.get("data_date") == formation_date.isoformat()
        )
        market_ready = feature_ready.get("market_context", False)
        price_ready = feature_ready.get("price_analysis_context", False)
        core_ready = bool(
            report_date_matches
            and market_ready
            and price_ready
        )
        dataset_ready = {
            str(item.get("dataset_id", "")): bool(
                item.get(
                    "data_date_partition_ready",
                    item.get("last_partition") == formation_date.isoformat()
                    and item.get("contract_valid")
                    and item.get("physical_valid"),
                )
            )
            for item in report.get("datasets", [])
            if isinstance(item, dict)
        }
        sector_feature_ready = feature_ready.get("sector_hotspot", False)
        industry_ready = bool(
            sector_feature_ready and dataset_ready.get("industry_daily_proxy", False)
        )
        theme_ready = bool(
            sector_feature_ready and dataset_ready.get("theme_daily", False)
        )
        sector_ready = industry_ready or theme_ready
        stock_ready = feature_ready.get("stock_trading_context", False)
        stage = _next_morning_stage(report, formation_date)
        stage_status = str(stage.get("status", ""))
        raw_capabilities = stage.get("capabilities", {})
        capabilities = (
            raw_capabilities if isinstance(raw_capabilities, dict) else {}
        )
        announcement_status = str(
            capabilities.get("announcement_status", "announcement_unavailable")
        )
        raw_exchanges = capabilities.get("announcement_exchanges", [])
        announcement_exchanges = tuple(
            source
            for source in ("SSE", "SZSE")
            if source in {str(item).upper() for item in raw_exchanges}
        ) if isinstance(raw_exchanges, list) else ()
        preopen_ready = bool(
            announcement_status == "cninfo_complete"
            or (
                announcement_status == "exchange_complete"
                and announcement_exchanges == ("SSE", "SZSE")
            )
        )
        limitation_items: list[str] = []
        if not industry_ready:
            limitation_items.append(INDUSTRY_RESEARCH_LIMITATION)
        if not theme_ready:
            limitation_items.append(THEME_RESEARCH_LIMITATION)
        if not stock_ready:
            limitation_items.append(STOCK_CONTEXT_LIMITATION)
        if announcement_status == "exchange_partial":
            covered = "、".join(announcement_exchanges) or "无交易所"
            limitation_items.append(
                f"行动日前公告仅完整覆盖{covered}，未覆盖交易所不得形成 fresh_event_pending"
            )
        elif not preopen_ready:
            limitation_items.append(PREOPEN_REFRESH_LIMITATION)
        if stage_status == "failed":
            limitation_items.append("次晨任务存在失败步骤，按已确认可用通道受限研究")
        limitations = tuple(dict.fromkeys(limitation_items))

        if core_ready and not limitations:
            return (
                "full",
                True,
                True,
                True,
                True,
                True,
                True,
                True,
                announcement_status,
                announcement_exchanges,
                (),
                "",
            )
        if stage_status == "failed":
            if core_ready:
                return (
                    "limited",
                    market_ready,
                    price_ready,
                    industry_ready,
                    theme_ready,
                    sector_ready,
                    stock_ready,
                    preopen_ready,
                    announcement_status,
                    announcement_exchanges,
                    limitations,
                    "",
                )
            return (
                "",
                market_ready,
                price_ready,
                industry_ready,
                theme_ready,
                sector_ready,
                stock_ready,
                preopen_ready,
                announcement_status,
                announcement_exchanges,
                limitations,
                "next_morning_stage_failed",
            )

        can_wait = run_mode == "normal" and checked_at < market_open
        if explicit_context and checked_at >= market_open:
            can_wait = False
        optional_stage_may_finish = stage_status in {
            "",
            "running",
            "waiting_upstream",
        }
        if core_ready and (not can_wait or not optional_stage_may_finish):
            return (
                "limited",
                market_ready,
                price_ready,
                industry_ready,
                theme_ready,
                sector_ready,
                stock_ready,
                preopen_ready,
                announcement_status,
                announcement_exchanges,
                limitations,
                "",
            )
        if not can_wait:
            return (
                "",
                market_ready,
                price_ready,
                industry_ready,
                theme_ready,
                sector_ready,
                stock_ready,
                preopen_ready,
                announcement_status,
                announcement_exchanges,
                limitations,
                "next_morning_data_not_ready_by_market_open",
            )
        remaining = (market_open - checked_at).total_seconds()
        sleep(min(float(READINESS_POLL_SECONDS), remaining))


def _next_morning_stage(
    report: dict[str, Any],
    formation_date: date,
) -> dict[str, Any]:
    rows = [
        row
        for row in report.get("latest_stage_runs", [])
        if row.get("stage") == "next-morning"
        and row.get("data_date") == formation_date.isoformat()
    ]
    if not rows:
        return {}
    return max(
        rows,
        key=lambda row: str(row.get("started_at", "")),
    )


def _validate_result(
    result: dict[str, Any],
    eligible: dict[str, str],
) -> dict[str, Any]:
    try:
        payload = ResearchResult.model_validate(result).model_dump()
    except ValidationError as error:
        raise ValueError("invalid_structured_output") from error
    if (
        not payload["research_completed"]
        or not payload["point_in_time_evidence_verified"]
        or payload["failure_reason"]
    ):
        raise ValueError("research_incomplete")
    if set(payload["skills_used"]) != REQUIRED_SKILLS:
        raise ValueError("skills_not_complete")
    selected = payload["selected_stocks"]
    nearest = payload["nearest_nonselections"]
    if not selected and not payload["empty_reason"]:
        raise ValueError("empty_selection_reason_missing")
    priorities = [item.get("priority") for item in selected]
    if priorities != list(range(1, len(selected) + 1)):
        raise ValueError("invalid_priorities")
    all_items = [*selected, *nearest]
    codes = [str(item.get("ts_code", "")).strip() for item in all_items]
    if len(set(codes)) != len(codes) or "" in codes:
        raise ValueError("duplicate_or_empty_codes")
    for item in all_items:
        code = str(item.get("ts_code", "")).strip()
        name = str(item.get("name", "")).strip()
        if eligible.get(code) != name:
            raise ValueError("ineligible_security")
    return payload


def _decision_rows(
    result: dict[str, Any],
    *,
    fieldnames: list[str],
    formation_date: date,
    action_date: date,
    selection_as_of: datetime,
) -> list[dict[str, str]]:
    base = {field: "" for field in fieldnames}
    selection_text = selection_as_of.isoformat(timespec="seconds")
    base.update(
        {
            "formation_date": formation_date.isoformat(),
            "action_date": action_date.isoformat(),
            "as_of": selection_text,
            "selection_as_of": selection_text,
            "validation_mode": "selection",
        }
    )
    rows: list[dict[str, str]] = []
    selected = result["selected_stocks"]
    if not selected:
        empty = dict(base)
        empty.update(
            {
                "final_fate": "empty_selection",
                "selection_reason": str(result["empty_reason"]).strip(),
            }
        )
        rows.append(empty)
    for item in selected:
        row = dict(base)
        row.update(_candidate_row(item, final_fate="selected"))
        row["priority"] = str(item["priority"])
        rows.append(row)
    for item in result["nearest_nonselections"]:
        row = dict(base)
        row.update(_candidate_row(item, final_fate="nearest_nonselection"))
        rows.append(row)
    return rows


def _candidate_row(item: dict[str, Any], *, final_fate: str) -> dict[str, str]:
    return {
        "ts_code": str(item["ts_code"]).strip(),
        "name": str(item["name"]).strip(),
        "final_fate": final_fate,
        "opportunity_type": str(item["opportunity_type"]),
        "selection_reason": str(item["selection_reason"]).strip(),
        "strongest_counterevidence": str(
            item["strongest_counterevidence"]
        ).strip(),
        "nearest_comparison": str(item["nearest_comparison"]).strip(),
    }


def _read_forward_log(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with Path(path).open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("forward log header is missing")
        fieldnames = list(reader.fieldnames)
        missing = sorted(REQUIRED_LOG_FIELDS - set(fieldnames))
        if missing:
            raise ValueError(f"forward log fields missing: {','.join(missing)}")
        if MAX_RETURN_FIELD not in fieldnames:
            fieldnames.append(MAX_RETURN_FIELD)
        rows = [
            {field: row.get(field, "") or "" for field in fieldnames}
            for row in reader
        ]
    return fieldnames, rows


def _atomic_write_csv(
    path: Path,
    fieldnames: list[str],
    rows: list[dict[str, str]],
) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_name = handle.name
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(
                {field: row.get(field, "") for field in fieldnames}
                for row in rows
            )
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except Exception:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)
        raise


def _has_selection_decision(
    rows: list[dict[str, str]], formation_date: str
) -> bool:
    return any(
        row.get("formation_date") == formation_date
        and row.get("final_fate")
        for row in rows
    )


def _settlement_complete(row: dict[str, str]) -> bool:
    if any(not str(row.get(field, "")).strip() for field in RESULT_FIELDS if field != "first_hit_day"):
        return False
    hit = row.get("hit_20pct_close_within_20d")
    return hit == "false" or (hit == "true" and bool(row.get("first_hit_day")))


def _valid_price_path(
    points: list[PricePoint] | None,
    expected_dates: list[date],
) -> bool:
    if points is None or len(points) != 20:
        return False
    if [point.trade_date for point in points] != expected_dates:
        return False
    values = [
        value
        for point in points
        for value in (point.adjusted_open, point.adjusted_close)
    ]
    return all(math.isfinite(value) and value > 0 for value in values)


def _format_percent(value: float) -> str:
    if abs(value) < 0.0000005:
        return "0"
    return f"{value:.6f}".rstrip("0").rstrip(".")


def _shanghai(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("clock must return a timezone-aware datetime")
    return value.astimezone(SHANGHAI)


def _safe_error(error: Exception) -> str:
    text = str(error).strip() or error.__class__.__name__
    return text[:160].replace("\n", " ")


def prepare_runtime_log(project_root: Path) -> Path:
    project_root = Path(project_root)
    runtime_log = (
        project_root
        / "local_archive/forward_selection/forward-selection-log.csv"
    )
    if runtime_log.is_file():
        return runtime_log
    source_log = project_root / "docs/forward-selection-log.csv"
    runtime_log.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_log, runtime_log)
    return runtime_log


def _parse_main_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare or record a top-level point-in-time stock selection."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--formation-date")
    prepare.add_argument("--action-date")
    prepare.add_argument("--as-of")
    prepare.add_argument("--rerun-date")
    record = commands.add_parser("record")
    record.add_argument("--result-file", required=True)
    record.add_argument("--formation-date", required=True)
    record.add_argument("--action-date", required=True)
    record.add_argument("--as-of", required=True)
    record_trace = commands.add_parser("record-trace")
    record_trace.add_argument("--trace-file", required=True)
    record_trace.add_argument("--formation-date", required=True)
    record_trace.add_argument("--action-date", required=True)
    record_trace.add_argument("--as-of", required=True)
    args = parser.parse_args(argv)
    supplied = [
        getattr(args, "formation_date", None),
        getattr(args, "action_date", None),
        getattr(args, "as_of", None),
    ]
    if args.command == "prepare" and any(supplied) and not all(supplied):
        parser.error(
            "--formation-date, --action-date, and --as-of must be provided together"
        )
    if (
        args.command == "prepare"
        and getattr(args, "rerun_date", None)
        and any(supplied)
    ):
        parser.error(
            "--rerun-date cannot be combined with --formation-date, "
            "--action-date, or --as-of"
        )
    return args


def main(argv: list[str] | None = None) -> int:
    args = _parse_main_args(argv)
    project_root = Path(__file__).resolve().parents[3]
    csv_path = prepare_runtime_log(project_root)
    data = LocalForwardData(
        project_root / "local_warehouse",
        project_root / "local_archive",
    )
    try:
        formation_date = (
            date.fromisoformat(args.formation_date)
            if args.formation_date
            else None
        )
        action_date = (
            date.fromisoformat(args.action_date) if args.action_date else None
        )
        selection_as_of = (
            datetime.fromisoformat(args.as_of) if args.as_of else None
        )
        rerun_date = (
            date.fromisoformat(args.rerun_date)
            if getattr(args, "rerun_date", None)
            else None
        )
        common = {
            "csv_path": csv_path,
            "data": data,
            "clock": lambda: datetime.now(SHANGHAI),
        }
        if args.command == "prepare":
            summary = prepare_daily_selection(
                **common,
                formation_date=formation_date,
                action_date=action_date,
                selection_as_of=selection_as_of,
                rerun_date=rerun_date,
            )
        elif args.command == "record":
            if formation_date is None or action_date is None or selection_as_of is None:
                raise ValueError("record requires a complete selection context")
            result_path = Path(args.result_file).expanduser().resolve()
            result = json.loads(result_path.read_text(encoding="utf-8"))
            if not isinstance(result, dict):
                raise ValueError("result file must contain one JSON object")
            summary = record_daily_selection(
                result,
                **common,
                formation_date=formation_date,
                action_date=action_date,
                selection_as_of=selection_as_of,
            )
        else:
            if formation_date is None or action_date is None or selection_as_of is None:
                raise ValueError("record-trace requires a complete selection context")
            trace_path = Path(args.trace_file).expanduser().resolve()
            trace = json.loads(trace_path.read_text(encoding="utf-8"))
            if not isinstance(trace, dict):
                raise ValueError("trace file must contain one JSON object")
            summary = record_daily_trace(
                trace,
                pending_path=trace_path,
                archive_dir=(
                    project_root / "local_archive" / "forward_selection"
                ),
                **common,
                formation_date=formation_date,
                action_date=action_date,
                selection_as_of=selection_as_of,
            )
    except Exception as error:
        now = datetime.now(SHANGHAI).isoformat(timespec="seconds")
        summary = RunSummary(
            status="error",
            started_at=now,
            error=_safe_error(error),
        )
    print(json.dumps(asdict(summary), ensure_ascii=False, sort_keys=True))
    return 2 if summary.status in {
        "error",
        "invalid_result",
        "invalid_selection_context",
        "invalid_selection_cutoff",
        "outside_selection_window",
        "data_not_ready",
    } else 0


if __name__ == "__main__":
    raise SystemExit(main())
