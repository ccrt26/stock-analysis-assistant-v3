from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from stock_analyzer.config import AppConfig
from stock_analyzer.data.classification_backfill import ClassificationBackfillService
from stock_analyzer.data.event_backfill import EventBackfillService
from stock_analyzer.data.fundamental_backfill import FundamentalBackfillService
from stock_analyzer.data.research_contracts import ResearchDatasetId
from stock_analyzer.data.trading_structure_backfill import (
    TradingStructureBackfillService,
)
from stock_analyzer.ops.research_data_job import (
    build_research_data_runtime,
    interrupt_orphan_runs,
    reconcile_research_gaps,
    research_job_lock,
)
from stock_analyzer.ops.research_data_repair import (
    AFFECTED_DERIVED_DATES,
    DAILY_REPAIR_TARGETS,
    create_repair_backup,
    extract_financial_indicator_conflict_targets,
    missing_financial_indicator_targets,
    missing_financial_indicator_targets_from_files,
    repair_known_zero_length_financial_revision,
)
from stock_analyzer.ops.research_features import run_research_features
from stock_analyzer.ops.research_health import (
    build_research_health_report,
    write_health_report,
)


THROUGH = date(2026, 9, 2)


def _summary_payload(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "__dict__"):
        return dict(value.__dict__)
    return value


def _run_step(
    results: dict[str, Any],
    name: str,
    operation: Callable[[], Any],
) -> Any | None:
    print(f"START {name}", flush=True)
    try:
        value = operation()
    except Exception as exc:
        results[name] = {
            "status": "failed",
            "error_type": type(exc).__name__,
            "message": " ".join(str(exc).split())[:1000],
        }
        print(f"FAILED {name}: {type(exc).__name__}: {exc}", flush=True)
        return None
    results[name] = {"status": "completed", "result": _summary_payload(value)}
    print(f"DONE {name}", flush=True)
    return value


def _trading_dates(warehouse, through: date, count: int) -> tuple[date, ...]:
    calendar = warehouse.read_current(ResearchDatasetId.TRADE_CALENDAR)
    values = pd.to_datetime(
        calendar.loc[calendar["is_open"].astype(bool), "cal_date"]
    ).dt.date
    return tuple(sorted({value for value in values if value <= through})[-count:])


def _repair_industry_proxy_history(
    classification: ClassificationBackfillService,
    trading_dates: tuple[date, ...],
) -> dict[str, Any]:
    failures: dict[str, list[str]] = {}
    committed = 0
    skipped = 0
    for trading_date in trading_dates:
        summary = classification.refresh_daily(
            trading_date,
            datasets=(ResearchDatasetId.INDUSTRY_DAILY_PROXY,),
            refresh_memberships=False,
        )
        committed += summary.committed
        skipped += summary.skipped
        if summary.failed or summary.waiting_upstream or summary.limited:
            failures[trading_date.isoformat()] = list(summary.issues)
    if failures:
        sample = dict(list(failures.items())[:10])
        raise RuntimeError(
            "industry proxy repair incomplete: "
            + json.dumps(sample, ensure_ascii=False)
        )
    return {
        "trading_dates": len(trading_dates),
        "committed": committed,
        "skipped": skipped,
    }


def _dry_run_payload(config: AppConfig) -> tuple[dict[str, Any], tuple[tuple[str, date], ...]]:
    targets = extract_financial_indicator_conflict_targets(
        config.research_warehouse_path
    )
    missing = missing_financial_indicator_targets_from_files(
        config.local_warehouse_dir, targets
    )
    payload = {
        "mode": "dry-run",
        "through": THROUGH.isoformat(),
        "daily_targets": {
            key: [value.isoformat() for value in values]
            for key, values in DAILY_REPAIR_TARGETS.items()
        },
        "financial_indicator": {
            "historically_ambiguous_targets": len(targets),
            "currently_missing_targets": len(missing),
            "currently_existing_targets": len(targets) - len(missing),
            "report_periods": sorted({period.isoformat() for _, period in targets}),
        },
        "affected_derived_dates": [
            value.isoformat() for value in AFFECTED_DERIVED_DATES
        ],
        "writes_before_backup": 0,
    }
    return payload, targets


def run(*, execute: bool) -> int:
    config = AppConfig.load()
    with research_job_lock(config.local_warehouse_dir):
        dry_run, targets = _dry_run_payload(config)
        print(json.dumps(dry_run, ensure_ascii=False, indent=2), flush=True)
        if not execute:
            return 0

        backup = create_repair_backup(
            warehouse_root=config.local_warehouse_dir,
            archive_root=config.local_archive_dir,
            financial_targets=targets,
        )
        print(f"BACKUP {backup.backup_root}", flush=True)
        runtime = build_research_data_runtime(config)
        results: dict[str, Any] = {
            "started_at": datetime.now(timezone.utc).isoformat(),
            "through": THROUGH.isoformat(),
            "backup_root": str(backup.backup_root),
            "dry_run": dry_run,
        }
        try:
            results["interrupted_orphan_runs"] = interrupt_orphan_runs(
                runtime.warehouse
            )
            classification = ClassificationBackfillService(
                runtime.tushare, runtime.warehouse
            )
            proxy_dates = _trading_dates(runtime.warehouse, THROUGH, 250)
            results["industry_proxy_scope"] = {
                "sessions": len(proxy_dates),
                "start": proxy_dates[0].isoformat() if proxy_dates else None,
                "through": proxy_dates[-1].isoformat() if proxy_dates else None,
            }
            _run_step(
                results,
                "industry_daily_proxy:last_250_sessions",
                lambda: _repair_industry_proxy_history(
                    classification, proxy_dates
                ),
            )
            for target_date in DAILY_REPAIR_TARGETS["theme_daily"]:
                _run_step(
                    results,
                    f"theme_daily:{target_date.isoformat()}",
                    lambda value=target_date: classification.refresh_daily(
                        value,
                        datasets=(ResearchDatasetId.THEME_DAILY,),
                        refresh_memberships=False,
                    ),
                )

            events = EventBackfillService(
                runtime.tushare,
                runtime.cninfo,
                runtime.warehouse,
                exchange_announcements=runtime.exchange_announcements,
            )
            _run_step(
                results,
                "suspension:2026-08-26",
                lambda: events.backfill_suspensions(
                    trading_dates=DAILY_REPAIR_TARGETS["suspension"],
                    through=THROUGH,
                    resume=False,
                ),
            )

            trading = TradingStructureBackfillService(
                runtime.tushare,
                runtime.warehouse,
                minute_fetcher=runtime.minute_fetcher,
            )
            _run_step(
                results,
                "margin_detail:2026-08-11",
                lambda: trading.backfill_margin_details(
                    trading_dates=DAILY_REPAIR_TARGETS["margin_detail"],
                    through=THROUGH,
                    resume=False,
                ),
            )

            zero_revision = _run_step(
                results,
                "known_zero_length_financial_revision",
                lambda: repair_known_zero_length_financial_revision(
                    runtime.warehouse, dry_run=False
                ),
            )
            results["zero_revision_result"] = zero_revision
            missing_before = missing_financial_indicator_targets(
                runtime.warehouse, targets
            )
            results["financial_missing_before_retry"] = len(missing_before)
            _run_step(
                results,
                "financial_indicator_exact_retry",
                lambda: FundamentalBackfillService(
                    runtime.tushare, runtime.warehouse
                ).backfill_financial_indicator_business_keys(
                    business_keys=targets,
                    through=THROUGH,
                ),
            )
            results["financial_missing_after_retry"] = len(
                missing_financial_indicator_targets(runtime.warehouse, targets)
            )
            results["financial_unresolved_after_retry"] = len(
                extract_financial_indicator_conflict_targets(
                    runtime.warehouse.duckdb_path
                )
            )

            results["resolved_gaps"] = reconcile_research_gaps(
                runtime.warehouse
            )

            for analysis_date in AFFECTED_DERIVED_DATES:
                _run_step(
                    results,
                    f"derived:{analysis_date.isoformat()}",
                    lambda value=analysis_date: run_research_features(
                        runtime.warehouse, value
                    ),
                )

            health = build_research_health_report(
                runtime.warehouse, THROUGH, full_history=True
            )
            health_json, health_md = write_health_report(
                health, backup.backup_root / "post_repair_health"
            )
            write_health_report(
                health, config.local_archive_dir / "data_health"
            )
            results["health"] = {
                "json": str(health_json),
                "markdown": str(health_md),
                "gap_counts": health.gap_counts,
                "complete_core_date": health.complete_core_date,
                "derived_ready_for_research": health.derived_ready_for_research,
            }
        finally:
            runtime.http_client.close()

        results["finished_at"] = datetime.now(timezone.utc).isoformat()
        result_path = backup.backup_root / "repair-results.json"
        result_path.write_text(
            json.dumps(results, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        print(f"RESULT {result_path}", flush=True)
        failed_steps = [
            name for name, value in results.items()
            if isinstance(value, dict) and value.get("status") == "failed"
        ]
        unmet = bool(
            failed_steps
            or results.get("financial_missing_after_retry")
            or results.get("financial_unresolved_after_retry")
        )
        return 1 if unmet else 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Dry-run or execute the reviewed 2026-09-02 data-gap repair."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="inspect exact targets without writing or fetching external data",
    )
    mode.add_argument(
        "--execute",
        action="store_true",
        help="create the mandatory backup, then execute exact repairs",
    )
    return run(execute=parser.parse_args().execute)


if __name__ == "__main__":
    raise SystemExit(main())
