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


SHANGHAI = ZoneInfo("Asia/Shanghai")
SELECTION_START = time(9, 5)
READINESS_POLL_SECONDS = 30
MARKET_OPEN = time(9, 30)
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


@dataclass(frozen=True)
class PricePoint:
    trade_date: date
    adjusted_open: float
    adjusted_close: float


@dataclass(frozen=True)
class RunSummary:
    status: str
    started_at: str
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
    )
    if failure is not None:
        return failure
    assert context is not None
    formation_text = context.formation_date.isoformat()
    if _has_selection_decision(context.rows, formation_text):
        return _context_summary(context, status="already_selected")
    return _context_summary(context, status="ready_for_research")


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
    )
    if failure is not None:
        return failure
    assert context is not None
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


def _prepare_selection_context(
    *,
    csv_path: Path,
    data: ForwardData,
    clock: Callable[[], datetime],
    sleep: Callable[[float], None],
    formation_date: date | None,
    action_date: date | None,
    selection_as_of: datetime | None,
) -> tuple[_SelectionContext | None, RunSummary | None]:
    started = _shanghai(clock())
    summary_base = {"started_at": started.isoformat(timespec="seconds")}
    explicit_context = any(
        value is not None
        for value in (formation_date, action_date, selection_as_of)
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
    if not explicit_context and (
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
    _wait_until_data_ready(
        data=data,
        formation_date=formation_date,
        clock=clock,
        sleep=sleep,
    )

    updated_rows, settled = apply_mature_settlements(
        rows,
        open_dates=open_dates,
        price_loader=data.adjusted_prices,
    )
    if settled:
        _atomic_write_csv(csv_path, fieldnames, updated_rows)
        rows = updated_rows

    return _SelectionContext(
        started_at=summary_base["started_at"],
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
) -> tuple[list[dict[str, str]], int]:
    updated = [dict(row) for row in rows]
    sessions = sorted(set(open_dates))
    settled = 0
    for row in updated:
        if not row.get("ts_code") or row.get("final_fate") == "empty_selection":
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


def _wait_until_data_ready(
    *,
    data: ForwardData,
    formation_date: date,
    clock: Callable[[], datetime],
    sleep: Callable[[float], None],
) -> None:
    while True:
        checked_at = _shanghai(clock())
        report = data.health_report(formation_date)
        if _data_ready(report, formation_date, checked_at):
            return
        sleep(float(READINESS_POLL_SECONDS))


def _data_ready(
    report: dict[str, Any],
    formation_date: date,
    cutoff: datetime,
) -> bool:
    if not report.get("complete_core_date"):
        return False
    if not report.get("derived_ready_for_research"):
        return False
    next_morning = [
        row
        for row in report.get("latest_stage_runs", [])
        if row.get("stage") == "next-morning"
        and row.get("data_date") == formation_date.isoformat()
    ]
    if len(next_morning) != 1:
        return False
    row = next_morning[0]
    if row.get("status") not in {"succeeded", "limited"}:
        return False
    try:
        started_at = _shanghai(datetime.fromisoformat(row["started_at"]))
        finished_at = _shanghai(datetime.fromisoformat(row["finished_at"]))
    except (KeyError, TypeError, ValueError):
        return False
    return (
        started_at.date() == cutoff.date()
        and started_at.time() >= time(9, 0)
        and finished_at <= cutoff
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
    record = commands.add_parser("record")
    record.add_argument("--result-file", required=True)
    record.add_argument("--formation-date", required=True)
    record.add_argument("--action-date", required=True)
    record.add_argument("--as-of", required=True)
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
            )
        else:
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
    } else 0


if __name__ == "__main__":
    raise SystemExit(main())
