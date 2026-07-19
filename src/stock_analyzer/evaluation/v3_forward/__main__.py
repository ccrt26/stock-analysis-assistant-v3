from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Sequence

from stock_analyzer.evaluation.v3_forward.ledger import FROZEN_OUTPUT_ROOT
from stock_analyzer.evaluation.v3_forward.service import (
    form_observation,
    update_observations,
)


def build_parser() -> argparse.ArgumentParser:
    project_root = Path(__file__).resolve().parents[4]
    parser = argparse.ArgumentParser(
        description="V3 连续真实交易日前瞻观察（手工运行）"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    form = subparsers.add_parser("form", help="形成一个不可变真实交易日批次")
    form.add_argument("--formation-date", required=True)
    form.add_argument("--warehouse-root", type=Path, default=project_root / "local_warehouse")
    form.add_argument("--archive-root", type=Path, default=project_root / "local_archive")
    form.add_argument("--output-root", type=Path, default=FROZEN_OUTPUT_ROOT)
    update = subparsers.add_parser("update", help="追加真实开盘和成熟窗口")
    update.add_argument("--as-of-date", required=True)
    update.add_argument("--warehouse-root", type=Path, default=project_root / "local_warehouse")
    update.add_argument("--output-root", type=Path, default=FROZEN_OUTPUT_ROOT)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "form":
        result = form_observation(
            warehouse_root=args.warehouse_root,
            archive_root=args.archive_root,
            output_root=args.output_root,
            formation_date=date.fromisoformat(args.formation_date),
        )
        payload = {
            "status": "idempotent" if result.bundle.idempotent else "formed",
            "path": str(result.bundle.path),
            "attention_count": result.attention_count,
            "action_count": result.action_count,
        }
    else:
        result = update_observations(
            warehouse_root=args.warehouse_root,
            output_root=args.output_root,
            as_of_date=date.fromisoformat(args.as_of_date),
        )
        payload = {
            "status": "updated",
            "entry_bundles": [str(item.path) for item in result.entry_bundles],
            "snapshot_bundles": [str(item.path) for item in result.snapshot_bundles],
            "waiting_formations": [item.isoformat() for item in result.waiting_formations],
        }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
