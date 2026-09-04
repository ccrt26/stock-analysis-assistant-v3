from __future__ import annotations

import argparse
import json
from datetime import date

from stock_analyzer.config import AppConfig
from stock_analyzer.ops.research_data_job import research_job_lock
from stock_analyzer.ops.research_features import run_research_features
from stock_analyzer.ops.research_health import (
    build_research_health_report,
    write_health_report,
)
from stock_analyzer.storage.research_warehouse import ResearchWarehouse


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-date", required=True)
    parser.add_argument("--full-history", action="store_true")
    parser.add_argument("--health-only", action="store_true")
    args = parser.parse_args()
    analysis_date = date.fromisoformat(args.data_date)
    config = AppConfig.load()
    with research_job_lock(config.local_warehouse_dir):
        warehouse = ResearchWarehouse(config.local_warehouse_dir)
        summary = (
            None
            if args.health_only
            else run_research_features(warehouse, analysis_date)
        )
        health = build_research_health_report(
            warehouse, analysis_date, full_history=args.full_history
        )
        json_path, markdown_path = write_health_report(
            health, config.local_archive_dir / "data_health"
        )
    print(json.dumps({
        "summary": None if summary is None else summary.__dict__,
        "health": {
            "json": str(json_path),
            "markdown": str(markdown_path),
            "complete_core_date": health.complete_core_date,
            "derived_ready_for_research": health.derived_ready_for_research,
            "gap_counts": health.gap_counts,
        },
    }, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
