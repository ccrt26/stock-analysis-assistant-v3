from __future__ import annotations

import csv
import json
import math
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Literal, Protocol
from zoneinfo import ZoneInfo

import duckdb
from pydantic import BaseModel, ConfigDict, Field, ValidationError


SHANGHAI = ZoneInfo("Asia/Shanghai")
MARKET_OPEN = time(9, 30)
DEFAULT_CODEX_TIMEOUT_SECONDS = 18 * 60
FINALIZE_BUFFER_SECONDS = 30
OPPORTUNITY_TYPES = {
    "company_catalyst",
    "sector_diffusion",
    "independent_price_anomaly",
}
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


class CandidateConservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deduped_candidates: int = Field(ge=0)
    selected: int = Field(ge=0)
    rejected: int = Field(ge=0)
    unresolved: int = Field(ge=0)


class ResearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    research_complete: Literal[True]
    skills_used: list[SkillName] = Field(min_length=5, max_length=5)
    market_context: str = Field(min_length=1)
    candidate_conservation: CandidateConservation
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
    selection_as_of: str = ""
    data_ready: bool = False
    new_forward_rows: int = 0
    selected_count: int = 0
    settled_rows: int = 0
    error: str = ""


class ForwardData(Protocol):
    def trading_dates(self, start: date, end: date) -> list[date]: ...

    def health_report(self, formation_date: date) -> dict[str, Any]: ...

    def eligible_securities(self, on_date: date) -> dict[str, str]: ...

    def adjusted_prices(
        self,
        ts_code: str,
        trading_dates: list[date],
    ) -> list[PricePoint] | None: ...


class ResearchExecutor(Protocol):
    def execute(self, *, prompt: str, timeout_seconds: int) -> dict[str, Any]: ...


class LocalForwardData:
    def __init__(self, warehouse_root: Path, archive_root: Path) -> None:
        self.warehouse_root = Path(warehouse_root)
        self.archive_root = Path(archive_root)

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


class CodexResearch:
    def __init__(self, project_root: Path, codex_bin: Path | None = None) -> None:
        self.project_root = Path(project_root)
        self.codex_bin = codex_bin or _resolve_codex_bin()

    def execute(self, *, prompt: str, timeout_seconds: int) -> dict[str, Any]:
        with tempfile.TemporaryDirectory(prefix="forward-selection-") as temp_dir:
            temp_root = Path(temp_dir)
            schema_path = temp_root / "schema.json"
            output_path = temp_root / "result.json"
            schema_path.write_text(
                json.dumps(ResearchResult.model_json_schema(), ensure_ascii=False),
                encoding="utf-8",
            )
            command = [
                str(self.codex_bin),
                "exec",
                "--ephemeral",
                "--sandbox",
                "read-only",
                "-C",
                str(self.project_root),
                "--output-schema",
                str(schema_path),
                "-o",
                str(output_path),
                "-",
            ]
            environment = dict(os.environ)
            environment["TZ"] = "Asia/Shanghai"
            try:
                completed = subprocess.run(
                    command,
                    input=prompt,
                    text=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    env=environment,
                    timeout=timeout_seconds,
                    check=False,
                )
            except subprocess.TimeoutExpired as error:
                raise RuntimeError("codex_timeout") from error
            if completed.returncode != 0:
                raise RuntimeError(f"codex_exit_{completed.returncode}")
            if not output_path.is_file():
                raise RuntimeError("codex_missing_output")
            try:
                return json.loads(output_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as error:
                raise RuntimeError("codex_invalid_json") from error


def run_daily_forward(
    *,
    project_root: Path,
    csv_path: Path,
    prompt_path: Path,
    data: ForwardData,
    research: ResearchExecutor,
    clock: Callable[[], datetime],
) -> RunSummary:
    started = _shanghai(clock())
    summary_base = {"started_at": started.isoformat(timespec="seconds")}
    if started.time() < time(9, 0) or started.time() >= MARKET_OPEN:
        return RunSummary(status="outside_selection_window", **summary_base)

    fieldnames, rows = _read_forward_log(csv_path)
    calendar_start = started.date() - timedelta(days=730)
    calendar_end = started.date() + timedelta(days=60)
    open_dates = sorted(set(data.trading_dates(calendar_start, calendar_end)))
    if started.date() not in open_dates:
        return RunSummary(status="non_trading_day", **summary_base)
    prior_dates = [day for day in open_dates if day < started.date()]
    if not prior_dates:
        return RunSummary(
            status="data_not_ready",
            error="no_prior_trading_date",
            **summary_base,
        )
    formation_date = prior_dates[-1]
    formation_text = formation_date.isoformat()

    readiness_cutoff = _shanghai(clock())
    report = data.health_report(formation_date)
    if not _data_ready(report, formation_date, readiness_cutoff):
        return RunSummary(
            status="data_not_ready",
            formation_date=formation_text,
            **summary_base,
        )

    updated_rows, settled = apply_mature_settlements(
        rows,
        open_dates=open_dates,
        price_loader=data.adjusted_prices,
    )
    if settled:
        _atomic_write_csv(csv_path, fieldnames, updated_rows)
        rows = updated_rows

    if _has_forward_decision(rows, formation_text):
        return RunSummary(
            status="already_frozen",
            formation_date=formation_text,
            data_ready=True,
            settled_rows=settled,
            **summary_base,
        )

    selection_as_of = _shanghai(clock())
    market_open = datetime.combine(started.date(), MARKET_OPEN, SHANGHAI)
    remaining = int((market_open - selection_as_of).total_seconds())
    timeout_seconds = min(
        DEFAULT_CODEX_TIMEOUT_SECONDS,
        remaining - FINALIZE_BUFFER_SECONDS,
    )
    if timeout_seconds <= 0:
        return RunSummary(
            status="missed_freeze_deadline",
            formation_date=formation_text,
            selection_as_of=selection_as_of.isoformat(timespec="seconds"),
            data_ready=True,
            settled_rows=settled,
            **summary_base,
        )

    action_date = started.date()
    selection_text = selection_as_of.isoformat(timespec="seconds")
    try:
        prompt = _render_prompt(
            prompt_path,
            formation_date=formation_date,
            action_date=action_date,
            selection_as_of=selection_as_of,
        )
        result = research.execute(prompt=prompt, timeout_seconds=timeout_seconds)
        completed_at = _shanghai(clock())
        if completed_at >= market_open:
            return RunSummary(
                status="missed_freeze_deadline",
                formation_date=formation_text,
                selection_as_of=selection_text,
                data_ready=True,
                settled_rows=settled,
                **summary_base,
            )
        eligible = data.eligible_securities(formation_date)
        result = _validate_result(result, eligible)
        decision_rows = _decision_rows(
            result,
            fieldnames=fieldnames,
            formation_date=formation_date,
            action_date=action_date,
            selection_as_of=selection_as_of,
        )
    except Exception as error:
        return RunSummary(
            status="research_failed",
            formation_date=formation_text,
            selection_as_of=selection_text,
            data_ready=True,
            settled_rows=settled,
            error=_safe_error(error),
            **summary_base,
        )

    latest_fieldnames, latest_rows = _read_forward_log(csv_path)
    if _has_forward_decision(latest_rows, formation_text):
        return RunSummary(
            status="already_frozen",
            formation_date=formation_text,
            selection_as_of=selection_text,
            data_ready=True,
            settled_rows=settled,
            **summary_base,
        )
    if latest_fieldnames != fieldnames:
        decision_rows = [
            {field: row.get(field, "") for field in latest_fieldnames}
            for row in decision_rows
        ]
        fieldnames = latest_fieldnames
    finalization_time = _shanghai(clock())
    if (market_open - finalization_time).total_seconds() <= 5:
        return RunSummary(
            status="missed_freeze_deadline",
            formation_date=formation_text,
            selection_as_of=selection_text,
            data_ready=True,
            settled_rows=settled,
            **summary_base,
        )
    _atomic_write_csv(csv_path, fieldnames, [*latest_rows, *decision_rows])
    return RunSummary(
        status="forward_frozen",
        formation_date=formation_text,
        selection_as_of=selection_text,
        data_ready=True,
        new_forward_rows=len(decision_rows),
        selected_count=len(result["selected_stocks"]),
        settled_rows=settled,
        **summary_base,
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
        if item.get("opportunity_type") not in OPPORTUNITY_TYPES:
            raise ValueError("invalid_opportunity_type")
        for field in (
            "selection_reason",
            "strongest_counterevidence",
            "nearest_comparison",
        ):
            if not str(item.get(field, "")).strip():
                raise ValueError(f"missing_{field}")
    conservation = payload["candidate_conservation"]
    deduped = conservation["deduped_candidates"]
    selected_count = conservation["selected"]
    rejected = conservation["rejected"]
    unresolved = conservation["unresolved"]
    if deduped != selected_count + rejected + unresolved:
        raise ValueError("candidate_conservation_failed")
    if selected_count != len(selected) or rejected < len(nearest):
        raise ValueError("candidate_counts_do_not_match_output")
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
            "validation_mode": "forward",
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


def _render_prompt(
    path: Path,
    *,
    formation_date: date,
    action_date: date,
    selection_as_of: datetime,
) -> str:
    template = Path(path).read_text(encoding="utf-8")
    return template.format(
        formation_date=formation_date.isoformat(),
        action_date=action_date.isoformat(),
        selection_as_of=selection_as_of.isoformat(timespec="seconds"),
    )


def _has_forward_decision(rows: list[dict[str, str]], formation_date: str) -> bool:
    return any(
        row.get("formation_date") == formation_date
        and row.get("validation_mode") == "forward"
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


def _resolve_codex_bin() -> Path:
    configured = os.environ.get("FORWARD_CODEX_BIN", "").strip()
    candidates = [
        Path(configured) if configured else None,
        Path(shutil.which("codex")) if shutil.which("codex") else None,
        Path("/Applications/ChatGPT.app/Contents/Resources/codex"),
    ]
    for candidate in candidates:
        if candidate is not None and candidate.is_file():
            return candidate
    raise FileNotFoundError("Codex CLI is not available")


def main() -> int:
    project_root = Path(__file__).resolve().parents[3]
    csv_path = project_root / "docs/forward-selection-log.csv"
    prompt_path = project_root / "ops/forward-selection-prompt.md"
    data = LocalForwardData(
        project_root / "local_warehouse",
        project_root / "local_archive",
    )
    try:
        summary = run_daily_forward(
            project_root=project_root,
            csv_path=csv_path,
            prompt_path=prompt_path,
            data=data,
            research=CodexResearch(project_root),
            clock=lambda: datetime.now(SHANGHAI),
        )
    except Exception as error:
        now = datetime.now(SHANGHAI).isoformat(timespec="seconds")
        summary = RunSummary(
            status="error",
            started_at=now,
            error=_safe_error(error),
        )
    print(json.dumps(asdict(summary), ensure_ascii=False, sort_keys=True))
    return 2 if summary.status in {"error", "research_failed"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
