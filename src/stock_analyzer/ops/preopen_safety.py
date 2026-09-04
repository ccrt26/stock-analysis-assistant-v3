"""Observe overnight changes to a frozen V4 list; never run selection."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, time, timedelta
from typing import Callable
from zoneinfo import ZoneInfo

import pandas as pd

from stock_analyzer.config import AppConfig
from stock_analyzer.data.event_backfill import EventBackfillService
from stock_analyzer.data.research_contracts import ResearchDatasetId
from stock_analyzer.ops.forward_monitor import _atomic_write_json
from stock_analyzer.ops.forward_selection import LocalForwardData, selection_output_class
from stock_analyzer.ops.research_data_job import build_research_data_runtime, research_job_lock

SHANGHAI = ZoneInfo("Asia/Shanghai")


def prepare_preopen_safety(
    config: AppConfig, *, clock: Callable[[], datetime],
    build_runtime=build_research_data_runtime,
) -> dict:
    checked_at = clock()
    if checked_at.utcoffset() is None:
        raise ValueError("checked_at requires timezone")
    checked_at = checked_at.astimezone(SHANGHAI)
    today = checked_at.date()
    output = config.local_archive_dir / "preopen_safety" / f"preopen-safety-{today}.json"
    result = dict(
        status="data_limited", action_date=today.isoformat(), selection_as_of=None,
        checked_at=checked_at.isoformat(timespec="seconds"), watched_stocks=[],
        new_announcements=[], suspended_stocks=[], limitations=[], output_path=str(output),
    )
    try:
        is_open = LocalForwardData(config.local_warehouse_dir, config.local_archive_dir).trading_day_status(today)
        if is_open is None:
            raise ValueError("action day calendar missing")
        if not is_open:
            result["status"] = "no_action_day"
        elif checked_at >= datetime.combine(today, time(9, 30), SHANGHAI):
            result["limitations"].append("安全检查启动时已经开盘，不能作为开盘前提醒")
        else:
            traces = []
            for path in sorted((config.local_archive_dir / "forward_selection").glob("research-trace-*.json")):
                trace = json.loads(path.read_text(encoding="utf-8"))
                if trace.get("trace_version") == "daily-research-trace-v4" and trace.get("action_date") == today.isoformat():
                    traces.append(trace)
            if not traces:
                result["status"] = "no_formal_trace"
            elif len(traces) != 1:
                raise ValueError("multiple formal traces for action day")
            else:
                trace = traces[0]
                cutoff = datetime.fromisoformat(trace["as_of"])
                expected = datetime.combine(today - timedelta(days=1), time(18, 30), SHANGHAI)
                if cutoff.utcoffset() is None or cutoff != expected or cutoff >= checked_at:
                    raise ValueError("formal trace has no valid prior-evening cutoff")
                result["selection_as_of"] = cutoff.astimezone(SHANGHAI).isoformat(timespec="seconds")
                ledger = {item["ts_code"]: item for item in trace["candidate_ledger"]}
                for stock in trace["research_result"]["selected_stocks"]:
                    code = stock["ts_code"]
                    output_class = selection_output_class(
                        trace_version=trace["trace_version"], candidate=ledger[code],
                    )
                    if output_class not in {"confirmed_active", "conditional_event"}:
                        raise ValueError(f"unresolved watched classification: {code}")
                    result["watched_stocks"].append({
                        "ts_code": code, "name": stock["name"],
                        "selection_output_class": output_class,
                        "is_formal_recommendation": output_class == "confirmed_active",
                    })
                if result["watched_stocks"]:
                    with research_job_lock(config.local_warehouse_dir):
                        runtime = build_runtime(config)
                        try:
                            _observe(runtime, result, cutoff, checked_at)
                        finally:
                            client = getattr(runtime, "http_client", None)
                            if client is not None:
                                client.close()
                result["status"] = (
                    "data_limited" if result["limitations"] else
                    "changes_found" if result["new_announcements"] or result["suspended_stocks"]
                    else "no_new_changes"
                )
    except Exception as exc:
        result["limitations"].append(f"{type(exc).__name__}: {exc}")
        result["status"] = "data_limited"
    _atomic_write_json(output, result)
    return result


def _observe(runtime, result: dict, cutoff: datetime, checked_at: datetime) -> None:
    codes = {item["ts_code"] for item in result["watched_stocks"]}
    required_exchanges = {"SSE" if code.endswith(".SH") else "SZSE" for code in codes}
    try:
        summary = EventBackfillService(
            runtime.tushare, runtime.cninfo, runtime.warehouse,
            exchange_announcements=runtime.exchange_announcements,
        ).backfill_announcements(
            start=cutoff.date(), through=checked_at.date(), resume=False,
            fallback_to_exchanges=True,
        )
        capabilities = summary.capabilities
        status = capabilities.get("announcement_status")
        covered = set(capabilities.get("announcement_exchanges", []))
        if status != "cninfo_complete" and not (
            status in {"exchange_complete", "exchange_partial"} and required_exchanges <= covered
        ):
            result["limitations"].append("announcement coverage incomplete for watched stocks")
    except Exception as exc:
        result["limitations"].append(f"announcement refresh: {type(exc).__name__}: {exc}")
    try:
        frame = runtime.warehouse.read_current(ResearchDatasetId.ANNOUNCEMENT)
        if not frame.empty:
            watched = frame.loc[frame["ts_code"].isin(codes)]
            available = pd.to_datetime(watched["available_at"], utc=True, errors="coerce")
            if available.isna().any():
                result["limitations"].append("watched announcement available_at missing")
            selected = watched.loc[(available > cutoff) & (available <= checked_at)]
            fields = [key for key in ("ts_code", "title", "announcement_time", "available_at",
                                      "url", "source_url", "source_name", "source_endpoint")
                      if key in selected]
            result["new_announcements"] = json.loads(selected[fields].to_json(orient="records", date_format="iso"))
    except Exception as exc:
        result["limitations"].append(f"announcement query: {type(exc).__name__}: {exc}")
    try:
        # This is a current observation, NOT a post-close suspension FactBatch.
        frame = runtime.tushare.call("suspend_d", trade_date=checked_at.strftime("%Y%m%d"))
        if not isinstance(frame, pd.DataFrame):
            raise ValueError("invalid suspension response")
        if not frame.empty:
            if not {"ts_code", "suspend_type"} <= set(frame):
                raise ValueError("suspension response missing columns")
            selected = frame.loc[frame["ts_code"].isin(codes) & frame["suspend_type"].eq("S")]
            fields = [key for key in ("ts_code", "trade_date", "suspend_type", "suspend_timing") if key in selected]
            result["suspended_stocks"] = json.loads(selected[fields].to_json(orient="records", date_format="iso"))
    except Exception as exc:
        result["limitations"].append(f"suspension query: {type(exc).__name__}: {exc}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare"])
    parser.parse_args(argv)
    result = prepare_preopen_safety(AppConfig.load(), clock=lambda: datetime.now(SHANGHAI))
    print(json.dumps(result, ensure_ascii=False))
    return 2 if result["status"] == "data_limited" else 0


if __name__ == "__main__":
    raise SystemExit(main())
