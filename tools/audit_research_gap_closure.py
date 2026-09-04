from __future__ import annotations

import argparse
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from stock_analyzer.analysis.hotspot_features import HOTSPOT_FORMULA_VERSION
from stock_analyzer.analysis.industry_proxy import FORMULA_VERSION, PROXY_METHOD
from stock_analyzer.config import AppConfig
from stock_analyzer.data.research_contracts import ResearchDatasetId
from stock_analyzer.ops.research_data_repair import (
    AFFECTED_DERIVED_DATES,
    DAILY_REPAIR_TARGETS,
    extract_financial_indicator_conflict_targets,
    missing_financial_indicator_targets,
)
from stock_analyzer.storage.research_derived import DerivedFeatureStore
from stock_analyzer.storage.research_query import ResearchQuery
from stock_analyzer.storage.research_schema import connect_research_warehouse
from stock_analyzer.storage.research_warehouse import ResearchWarehouse


THROUGH = date(2026, 9, 2)
SHANGHAI = ZoneInfo("Asia/Shanghai")


def _default_scope_codes(warehouse: ResearchWarehouse) -> set[str]:
    frame = warehouse.read_current(ResearchDatasetId.SECURITY_MASTER)
    boundary = pd.Timestamp(THROUGH)
    valid_from = pd.to_datetime(frame["valid_from"], errors="raise")
    valid_to = pd.to_datetime(frame["valid_to"], errors="coerce")
    active = (valid_from <= boundary) & (valid_to.isna() | (valid_to > boundary))
    active &= frame["list_status"].astype(str).eq("L")
    board = (
        frame["market"].astype(str).isin(("主板", "创业板"))
        & frame["exchange"].astype(str).isin(("SSE", "SZSE"))
    )
    names = frame["name"].fillna("").astype(str).str.upper()
    excluded = names.str.match(r"^\*?ST") | names.str.contains("退")
    return set(frame.loc[active & board & ~excluded, "ts_code"].astype(str))


def _target_partition_stats(warehouse: ResearchWarehouse) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for dataset, values in DAILY_REPAIR_TARGETS.items():
        dataset_id = ResearchDatasetId(dataset)
        for value in values:
            frame = warehouse.read_current(
                dataset_id, partition_value=value.isoformat()
            )
            result.append({
                "dataset_id": dataset,
                "partition_value": value.isoformat(),
                "rows": len(frame),
                "source_names": sorted(
                    frame.get("source_name", pd.Series(dtype=str)).astype(str).unique()
                ),
                "source_endpoints": sorted(
                    frame.get("source_endpoint", pd.Series(dtype=str)).astype(str).unique()
                ),
            })
    return result


def _open_trading_dates(
    warehouse: ResearchWarehouse,
    *,
    count: int,
) -> tuple[date, ...]:
    calendar = warehouse.read_current(ResearchDatasetId.TRADE_CALENDAR)
    values = pd.to_datetime(
        calendar.loc[calendar["is_open"].astype(bool), "cal_date"]
    ).dt.date
    return tuple(sorted({value for value in values if value <= THROUGH})[-count:])


def _proxy_audit(warehouse: ResearchWarehouse) -> dict[str, Any]:
    expected_dates = _open_trading_dates(warehouse, count=250)
    problems: dict[str, list[str]] = {}
    row_counts: list[int] = []
    previous_by_date = {
        value: expected_dates[index - 1] if index else None
        for index, value in enumerate(expected_dates)
    }
    if expected_dates:
        calendar = warehouse.read_current(ResearchDatasetId.TRADE_CALENDAR)
        prior = pd.to_datetime(
            calendar.loc[
                calendar["is_open"].astype(bool)
                & (pd.to_datetime(calendar["cal_date"]) < pd.Timestamp(expected_dates[0])),
                "cal_date",
            ]
        ).dt.date
        if not prior.empty:
            previous_by_date[expected_dates[0]] = max(prior)
    proxy_all = warehouse.read_current(ResearchDatasetId.INDUSTRY_DAILY_PROXY)
    proxy_by_date = {
        pd.Timestamp(trading_date).date(): group.copy()
        for trading_date, group in proxy_all.groupby("trade_date", sort=False)
    } if not proxy_all.empty else {}
    for trading_date in expected_dates:
        frame = proxy_by_date.get(trading_date, pd.DataFrame())
        issues: list[str] = []
        if frame.empty:
            issues.append("missing_partition")
        else:
            row_counts.append(len(frame))
            if frame["industry_code"].astype(str).duplicated().any():
                issues.append("duplicate_industry_code")
            if set(frame["source_name"].astype(str)) != {"local_derived"}:
                issues.append("wrong_source_name")
            if set(frame["source_endpoint"].astype(str)) != {PROXY_METHOD}:
                issues.append("wrong_source_endpoint")
            if set(frame["proxy_method"].astype(str)) != {PROXY_METHOD}:
                issues.append("wrong_proxy_method")
            if set(frame["formula_version"].astype(str)) != {FORMULA_VERSION}:
                issues.append("wrong_formula_version")
            if not frame["coverage_status"].astype(str).eq("complete").all():
                issues.append("limited_coverage")
            if pd.to_numeric(frame["proxy_return"], errors="coerce").isna().any():
                issues.append("null_proxy_return")
            expected_weight = previous_by_date[trading_date]
            actual_weights = set(pd.to_datetime(frame["weight_date"]).dt.date)
            if expected_weight is None or actual_weights != {expected_weight}:
                issues.append("wrong_weight_date")
        if issues:
            problems[trading_date.isoformat()] = issues

    expected_strings = {value.isoformat() for value in expected_dates}
    with connect_research_warehouse(
        warehouse.duckdb_path, read_only=True
    ) as connection:
        active_proxy_gaps = connection.execute(
            "select partition_value, reason_category from research_data_gaps "
            "where dataset_id = 'industry_daily_proxy' "
            "and status <> 'resolved' order by partition_value"
        ).fetchall()
    scoped_active_gaps = [
        {"partition": str(partition), "reason": str(reason)}
        for partition, reason in active_proxy_gaps
        if str(partition) in expected_strings
    ]

    comparison: dict[str, Any] = {
        "pairs": 0,
        "pearson": None,
        "spearman": None,
        "mae_percentage_points": None,
        "direction_agreement": None,
        "mean_top5_overlap": None,
    }
    legacy = warehouse.read_current(ResearchDatasetId.INDUSTRY_DAILY)
    if not proxy_all.empty and not legacy.empty:
        paired = proxy_all[["trade_date", "industry_code", "proxy_return"]].merge(
            legacy[["trade_date", "industry_code", "pct_chg"]],
            on=["trade_date", "industry_code"],
            how="inner",
        )
        paired["proxy_pp"] = pd.to_numeric(
            paired["proxy_return"], errors="coerce"
        ) * 100.0
        paired["official_pp"] = pd.to_numeric(
            paired["pct_chg"], errors="coerce"
        )
        paired = paired[
            np.isfinite(paired["proxy_pp"])
            & np.isfinite(paired["official_pp"])
        ].copy()
        if not paired.empty:
            top5: list[float] = []
            for _, group in paired.groupby("trade_date"):
                if len(group) < 5:
                    continue
                proxy_top = set(group.nlargest(5, "proxy_pp")["industry_code"])
                official_top = set(group.nlargest(5, "official_pp")["industry_code"])
                top5.append(len(proxy_top & official_top) / 5.0)
            comparison = {
                "pairs": len(paired),
                "pearson": paired["proxy_pp"].corr(paired["official_pp"]),
                "spearman": paired["proxy_pp"].rank().corr(
                    paired["official_pp"].rank()
                ),
                "mae_percentage_points": float(
                    (paired["proxy_pp"] - paired["official_pp"]).abs().mean()
                ),
                "direction_agreement": float(
                    (np.sign(paired["proxy_pp"]) == np.sign(paired["official_pp"])).mean()
                ),
                "mean_top5_overlap": float(np.mean(top5)) if top5 else None,
            }

    return {
        "expected_sessions": len(expected_dates),
        "start": expected_dates[0].isoformat() if expected_dates else None,
        "through": expected_dates[-1].isoformat() if expected_dates else None,
        "present_sessions": len(expected_dates) - len(problems),
        "row_count_min": min(row_counts) if row_counts else 0,
        "row_count_max": max(row_counts) if row_counts else 0,
        "problem_count": len(problems),
        "problem_samples": dict(list(problems.items())[:20]),
        "active_gap_count": len(scoped_active_gaps),
        "active_gap_samples": scoped_active_gaps[:20],
        "historical_official_comparison": comparison,
        "passed": bool(
            len(expected_dates) == 250
            and not problems
            and not scoped_active_gaps
        ),
    }


def _derived_audit(warehouse: ResearchWarehouse) -> dict[str, Any]:
    store = DerivedFeatureStore(warehouse.root)
    problems: dict[str, list[str]] = {}
    for analysis_date in AFFECTED_DERIVED_DATES:
        issues: list[str] = []
        manifest = store.partition_manifest(
            "sector_hotspot",
            analysis_date=analysis_date,
            formula_version=HOTSPOT_FORMULA_VERSION,
        )
        if len(manifest) != 1:
            issues.append("missing_or_duplicate_sector_hotspot_v4")
        else:
            raw = manifest.iloc[0]["input_manifest_json"]
            stored = json.loads(raw) if isinstance(raw, str) else raw
            fact_snapshot = stored.get("fact_snapshot", {})
            datasets = {
                str(item.get("dataset"))
                for item in fact_snapshot.get("partitions", [])
            }
            if "industry_daily_proxy" not in datasets:
                issues.append("input_manifest_missing_industry_daily_proxy")
            frame = store.read(
                "sector_hotspot", analysis_date, HOTSPOT_FORMULA_VERSION
            )
            sw_l1 = frame[
                frame["group_type"].astype(str).eq("industry")
                & frame["level"].astype(str).eq("L1")
            ] if not frame.empty else frame
            if sw_l1.empty:
                issues.append("missing_sw_l1_rows")
            elif not sw_l1["proxy_index_status"].astype(str).eq("complete").all():
                issues.append("incomplete_sw_l1_proxy_horizons")
        if issues:
            problems[analysis_date.isoformat()] = issues
    return {
        "formula_version": HOTSPOT_FORMULA_VERSION,
        "expected_dates": [value.isoformat() for value in AFFECTED_DERIVED_DATES],
        "problem_count": len(problems),
        "problems": problems,
        "passed": not problems,
    }


def _all_financial_conflict_targets(
    warehouse: ResearchWarehouse,
) -> tuple[tuple[str, date], ...]:
    with connect_research_warehouse(
        warehouse.duckdb_path, read_only=True
    ) as connection:
        rows = connection.execute(
            "select distinct cast(business_key_json as varchar) "
            "from research_fact_conflicts "
            "where dataset_id = 'financial_indicator'"
        ).fetchall()
    result = set()
    for (raw_key,) in rows:
        key = json.loads(str(raw_key))
        result.add((str(key["ts_code"]), date.fromisoformat(str(key["report_period"]))))
    return tuple(sorted(result))


def _membership_overlaps(
    query: ResearchQuery,
    dataset: ResearchDatasetId,
    code_field: str,
    analysis_date: date,
) -> list[dict[str, Any]]:
    cutoff = datetime(
        analysis_date.year, analysis_date.month, analysis_date.day,
        23, 59, 59, tzinfo=SHANGHAI,
    )
    frame = query.dataset_as_of(dataset, cutoff)
    if frame.empty:
        return []
    frame = frame[
        pd.to_datetime(frame["valid_from"], errors="raise")
        <= pd.Timestamp(analysis_date)
    ].copy()
    frame["valid_from"] = pd.to_datetime(frame["valid_from"]).dt.date
    frame["valid_to"] = pd.to_datetime(frame["valid_to"], errors="coerce").dt.date
    key = [code_field, "ts_code"]
    ordered = frame.sort_values([*key, "valid_from"]).copy()
    grouped = ordered.groupby(key, sort=False)
    ordered["_prior_valid_from"] = grouped["valid_from"].shift(1)
    ordered["_prior_valid_to"] = grouped["valid_to"].shift(1)
    ordered["_prior_available_at"] = grouped["available_at"].shift(1)
    has_prior = grouped.cumcount() > 0
    overlap = has_prior & (
        ordered["_prior_valid_to"].isna()
        | (ordered["valid_from"] <= ordered["_prior_valid_to"])
    )
    issues: list[dict[str, Any]] = []
    for row in ordered.loc[overlap].head(20).to_dict(orient="records"):
        issues.append({
            "dataset_id": dataset.value,
            "group_code": str(row[code_field]),
            "ts_code": str(row["ts_code"]),
            "prior_valid_from": str(row["_prior_valid_from"]),
            "prior_valid_to": (
                None if pd.isna(row["_prior_valid_to"])
                else str(row["_prior_valid_to"])
            ),
            "current_valid_from": str(row["valid_from"]),
            "current_valid_to": (
                None if pd.isna(row["valid_to"]) else str(row["valid_to"])
            ),
            "prior_available_at": str(row["_prior_available_at"]),
            "current_available_at": str(row.get("available_at")),
        })
    return issues


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output")
    args = parser.parse_args()
    config = AppConfig.load()
    warehouse = ResearchWarehouse(config.local_warehouse_dir)
    targets = extract_financial_indicator_conflict_targets(
        warehouse.duckdb_path
    )
    all_financial_targets = _all_financial_conflict_targets(warehouse)
    missing = missing_financial_indicator_targets(
        warehouse, all_financial_targets
    )
    default_codes = _default_scope_codes(warehouse)
    proxy_audit = _proxy_audit(warehouse)
    derived_audit = _derived_audit(warehouse)
    with connect_research_warehouse(
        warehouse.duckdb_path, read_only=True
    ) as connection:
        schema = connection.execute(
            "select value from research_metadata "
            "where key = 'research_schema_version'"
        ).fetchone()[0]
        gap_rows = connection.execute(
            "select status, reason_category, source_endpoint, count(*) "
            "from research_data_gaps where status <> 'resolved' "
            "group by all order by all"
        ).fetchall()
        conflict_rows = connection.execute(
            "select status, count(distinct business_key_hash), count(*) "
            "from research_fact_conflicts group by status order by status"
        ).fetchall()
        invalid_revisions = connection.execute(
            "select count(*) from research_fact_revisions "
            "where valid_to <= valid_from"
        ).fetchone()[0]
        running = connection.execute(
            "select run_id from research_ingestion_runs "
            "where status = 'running' order by run_id"
        ).fetchall()
        gaps = connection.execute(
            "select dataset_id, partition_value, scope_key, status, "
            "reason_category, source_endpoint from research_data_gaps "
            "where status <> 'resolved' order by dataset_id, partition_value, scope_key"
        ).fetchall()

    # business keys live in the conflict ledger; read them separately so the
    # gap detail format does not become part of this audit contract.
    with connect_research_warehouse(
        warehouse.duckdb_path, read_only=True
    ) as connection:
        conflict_key_payloads = connection.execute(
            "select distinct cast(business_key_json as varchar) "
            "from research_fact_conflicts where status = 'unresolved'"
        ).fetchall()
    conflict_codes = {
        str(json.loads(str(payload))["ts_code"])
        for (payload,) in conflict_key_payloads
    }

    query = ResearchQuery(warehouse)
    theme_current = warehouse.read_current(ResearchDatasetId.THEME_MEMBER)
    sample_current = theme_current[
        theme_current["theme_code"].astype(str).eq("000019.SH")
        & theme_current["ts_code"].astype(str).eq("600004.SH")
    ][
        [
            "theme_code", "ts_code", "valid_from", "valid_to",
            "available_at", "ingestion_run_id", "business_key_hash",
        ]
    ].to_dict(orient="records")
    sample_revisions = [
        {
            "revision_no": row["revision_no"],
            "valid_from": row["valid_from"],
            "valid_to": row["valid_to"],
            "superseded_by_run_id": row.get("superseded_by_run_id"),
            "row_payload": row["row_payload"],
        }
        for row in warehouse.revision_rows(ResearchDatasetId.THEME_MEMBER)
        if str(row["row_payload"].get("theme_code")) == "000019.SH"
        and str(row["row_payload"].get("ts_code")) == "600004.SH"
    ]
    overlaps_by_date = {}
    for value in AFFECTED_DERIVED_DATES:
        industry = _membership_overlaps(
            query, ResearchDatasetId.INDUSTRY_MEMBER, "industry_code", value
        )
        theme = _membership_overlaps(
            query, ResearchDatasetId.THEME_MEMBER, "theme_code", value
        )
        overlaps_by_date[value.isoformat()] = {
            "industry_count": len(industry),
            "theme_count": len(theme),
            "samples": (industry + theme)[:20],
        }

    output = {
        "through": THROUGH.isoformat(),
        "schema_version": str(schema),
        "target_partitions": _target_partition_stats(warehouse),
        "industry_daily_proxy": proxy_audit,
        "derived_recomputation": derived_audit,
        "financial_indicator": {
            "historically_ambiguous_targets": len(all_financial_targets),
            "unresolved_targets": len(targets),
            "currently_missing_targets": len(missing),
            "currently_present_targets": len(all_financial_targets) - len(missing),
            "missing_in_default_scope": sum(
                code in default_codes for code, _ in missing
            ),
            "unresolved_conflicts_in_default_scope": sum(
                code in default_codes for code in conflict_codes
            ),
            "default_scope_size": len(default_codes),
            "conflict_ledger": [
                {"status": str(status), "business_keys": int(keys), "variants": int(rows)}
                for status, keys, rows in conflict_rows
            ],
        },
        "active_gap_groups": [
            {
                "status": str(status),
                "reason_category": str(reason),
                "source_endpoint": None if endpoint is None else str(endpoint),
                "count": int(count),
            }
            for status, reason, endpoint, count in gap_rows
        ],
        "active_gap_count": len(gaps),
        "invalid_revision_intervals": int(invalid_revisions),
        "running_runs": [str(row[0]) for row in running],
        "membership_overlaps_by_date": overlaps_by_date,
        "theme_member_sample": {
            "current": sample_current,
            "revisions": sample_revisions,
        },
    }
    indicator = warehouse.read_current(ResearchDatasetId.FINANCIAL_INDICATOR)
    forbidden_indicator_columns = sorted(
        column for column in indicator.columns
        if column == "update_flag" or column.startswith("_provider_")
    )
    output["financial_indicator"]["forbidden_stored_columns"] = (
        forbidden_indicator_columns
    )
    financial_passed = bool(
        not targets
        and not missing
        and not forbidden_indicator_columns
        and int(invalid_revisions) == 0
    )
    output["financial_indicator"]["passed"] = financial_passed
    membership_passed = all(
        details["industry_count"] == 0 and details["theme_count"] == 0
        for details in overlaps_by_date.values()
    )
    output["acceptance"] = {
        "industry_proxy_passed": bool(proxy_audit["passed"]),
        "financial_indicator_passed": financial_passed,
        "derived_recomputation_passed": bool(derived_audit["passed"]),
        "membership_intervals_passed": membership_passed,
        "no_running_runs": not running,
    }
    output["acceptance"]["passed"] = all(output["acceptance"].values())
    rendered = json.dumps(output, ensure_ascii=False, indent=2, default=str)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered + "\n", encoding="utf-8")
        print(json.dumps({
            "output": str(output_path),
            "passed": output["acceptance"]["passed"],
            "active_gap_count": output["active_gap_count"],
            "proxy_problem_count": output["industry_daily_proxy"][
                "problem_count"
            ],
            "financial_missing": output["financial_indicator"][
                "currently_missing_targets"
            ],
            "financial_unresolved": output["financial_indicator"][
                "unresolved_targets"
            ],
            "running_runs": output["running_runs"],
            "membership_overlap_counts": {
                value: {
                    "industry": details["industry_count"],
                    "theme": details["theme_count"],
                }
                for value, details in output[
                    "membership_overlaps_by_date"
                ].items()
            },
        }, ensure_ascii=False, indent=2))
    else:
        print(rendered)
    return 0 if output["acceptance"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
