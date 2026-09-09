from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from tools.export_skill_optimization_dataset import export_dataset
from tools.validate_skill_optimization_dataset import validate_package


def _write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path)


def _build_v3_package(root: Path) -> tuple[Path, Path]:
    """One formal selection, two open days, no workbook: a minimal valid v3 package."""
    trace = {
        "trace_version": "daily-research-trace-v4",
        "formation_date": "2026-08-19",
        "action_date": "2026-08-20",
        "as_of": "2026-08-19T18:30:00+08:00",
        "candidate_ledger": [
            {
                "ts_code": "600150.SH",
                "name": "中国船舶",
                "opportunity_type": "independent_price_anomaly",
                "source_skills": ["price"],
                "final_fate": "selected",
                "primary_reason": "理由",
                "selection_reason": "理由",
                "strongest_counterevidence": "反证",
                "research_thesis": {
                    "engine_type": "independent_demand_acceleration",
                    "engine_status": "active",
                    "market_recognition": {"status": "confirmed"},
                },
            }
        ],
        "decision_trace": [],
        "research_result": {
            "selected_stocks": [
                {
                    "ts_code": "600150.SH",
                    "name": "中国船舶",
                    "priority": 1,
                    "opportunity_type": "independent_price_anomaly",
                    "selection_reason": "理由",
                    "strongest_counterevidence": "反证",
                    "nearest_comparison": None,
                }
            ]
        },
    }
    selection_dir = root / "local_archive/forward_selection"
    selection_dir.mkdir(parents=True, exist_ok=True)
    (selection_dir / "research-trace-2026-08-19.json").write_text(
        json.dumps(trace, ensure_ascii=False), encoding="utf-8"
    )
    import csv as csv_module

    with (selection_dir / "forward-selection-log.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv_module.DictWriter(
            handle,
            fieldnames=[
                "formation_date",
                "action_date",
                "as_of",
                "ts_code",
                "name",
                "final_fate",
                "selection_reason",
                "strongest_counterevidence",
                "nearest_comparison",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "formation_date": "2026-08-19",
                "action_date": "2026-08-20",
                "as_of": "2026-08-19T18:30:00+08:00",
                "ts_code": "600150.SH",
                "name": "中国船舶",
                "final_fate": "selected",
                "selection_reason": "理由",
                "strongest_counterevidence": "反证",
                "nearest_comparison": "",
            }
        )
    _write_parquet(
        pd.DataFrame([{"exchange": "SSE", "cal_date": "2026-08-20", "is_open": True}]),
        root / "local_warehouse/facts/trade_calendar/cal_year=2026/data.parquet",
    )
    _write_parquet(
        pd.DataFrame(
            [
                {
                    "trade_date": "2026-08-20",
                    "ts_code": "600150.SH",
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 100.5,
                    "pre_close": 100.0,
                    "pct_chg": 1.0,
                    "volume": 1000.0,
                    "amount": 10000.0,
                }
            ]
        ),
        root / "local_warehouse/facts/equity_daily/trade_date=2026-08-20/data.parquet",
    )
    _write_parquet(
        pd.DataFrame(
            [{"trade_date": "2026-08-20", "ts_code": "600150.SH", "adj_factor": 1.0}]
        ),
        root / "local_warehouse/facts/adj_factor/trade_date=2026-08-20/data.parquet",
    )
    out = root / "package"
    export_dataset(
        root,
        out,
        start_action_date="2026-08-20",
        end_action_date="2026-08-20",
        outcome_through_date="2026-08-20",
        exported_at="2026-09-09T12:00:00+08:00",
    )
    return root, out


def test_v3_package_passes_with_only_active_records_and_no_workbook(tmp_path: Path) -> None:
    _, package = _build_v3_package(tmp_path)

    result = validate_package(package)

    assert result["status"] == "PASS"
    assert result["record_counts"]["formal_selections"] == 1
    assert result["record_counts"]["daily_formal_reviews"] == 0
    assert result["workbook_checked"] == 0


def test_declared_count_mismatch_fails(tmp_path: Path) -> None:
    _, package = _build_v3_package(tmp_path)
    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    manifest["record_counts"]["formal_selections"] = 99
    (package / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="manifest count mismatch"):
        validate_package(package)


def test_record_outside_declared_boundary_fails(tmp_path: Path) -> None:
    _, package = _build_v3_package(tmp_path)
    daily_path = package / "data/daily_price_volume.csv"
    rows = daily_path.read_text(encoding="utf-8-sig").splitlines()
    rows[-1] = rows[-1].replace("2026-08-20", "2026-09-30")
    daily_path.write_text("\n".join(rows) + "\n", encoding="utf-8-sig")

    with pytest.raises(ValueError, match="exceeds declared boundary|outside declared"):
        validate_package(package)


def test_v2_style_package_without_workbook_still_validates(tmp_path: Path) -> None:
    _, package = _build_v3_package(tmp_path)
    # Strip v3-only files and mark the package as v2: legacy packages stay readable.
    (package / "data/candidate_daily_price_volume.csv").unlink()
    (package / "data/daily_formal_reviews.jsonl").unlink()
    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    manifest["package_version"] = "a-share-skill-optimization-sample-v2"
    manifest["record_counts"].pop("candidate_daily_price_volume")
    manifest["record_counts"].pop("daily_formal_reviews")
    (package / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    # Manifest hashes must match the file set; regenerate checksums for the mutation.
    from tools.export_skill_optimization_dataset import finalize_manifest

    finalize_manifest(
        package,
        start_action_date=manifest["action_date_start"],
        end_action_date=manifest["action_date_end"],
        outcome_through_date=manifest["outcome_through_date"],
        exported_at="2026-09-09T12:00:00+08:00",
        record_counts=manifest["record_counts"],
        selected_codes=manifest["selected_stock_codes"],
        selected_action_dates=manifest["action_dates"],
        research_action_dates=manifest["research_action_dates"],
        maturity_counts=manifest["fixed_d20_maturity"],
        known_limitations=manifest["known_limitations"],
    )
    # Re-apply the v2 downgrade after regeneration (finalize writes v3).
    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    manifest["package_version"] = "a-share-skill-optimization-sample-v2"
    (package / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    entries = json.loads((package / "manifest.json").read_text(encoding="utf-8"))["files"]
    for entry in entries:
        if entry["path"] == "manifest.json":
            continue
    # checksums.sha256 was regenerated before the final manifest edit; the manifest
    # no longer matches its own hash entry for manifest.json is not listed, so OK.

    result = validate_package(package)

    assert result["status"] == "PASS"
    assert result["package_version"].endswith("-v2")
