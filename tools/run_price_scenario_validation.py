"""Run the predeclared 2026-08-19 price-scenario validation once.

All outputs are research artifacts under the Git-ignored local archive.  The
script never writes production selections, scores, gates, or trading actions.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

from stock_analyzer.analysis.price_indicator_features import (
    PRICE_INDICATOR_FORMULA_VERSION,
    compute_price_indicator_panel,
)
from stock_analyzer.analysis.price_scenario_validation import (
    SCENARIO_SPECS,
    SCENARIO_THRESHOLD_FIELDS,
    assign_price_scenarios,
    evaluate_price_scenarios,
    fit_scenario_thresholds,
)
from stock_analyzer.config import AppConfig


RUN_ID = "2026-08-19-price-scenario-validation-v3"
SOURCE_RUN_ID = "2026-08-19-price-indicator-validation-v1"
DEVELOPMENT_END = date(2024, 12, 31)
VALIDATION_START = date(2025, 1, 2)
LAST_FORMATION_DATE = date(2026, 7, 21)
CODE_CHUNK_SIZE = 250
BOOTSTRAP_REPETITIONS = 1_000
BOOTSTRAP_SEED = 20260819
KEYS = ["analysis_date", "ts_code"]


def main() -> None:
    config = AppConfig.load()
    source_root = (
        config.local_archive_dir / "price_indicator_validation" / SOURCE_RUN_ID
    )
    source_sample_path = source_root / "frozen-sample.parquet"
    archive_root = config.local_archive_dir / "price_indicator_validation" / RUN_ID
    if not source_sample_path.exists():
        raise FileNotFoundError(f"frozen source sample is absent: {source_sample_path}")
    if archive_root.exists():
        raise FileExistsError(
            f"frozen output already exists; choose a new RUN_ID instead of overwriting: {archive_root}"
        )
    feature_chunks = archive_root / "feature-chunks"
    feature_chunks.mkdir(parents=True)

    source = pd.read_parquet(source_sample_path)
    source["analysis_date"] = pd.to_datetime(source["analysis_date"], errors="raise").dt.date
    source["action_date"] = pd.to_datetime(source["action_date"], errors="raise").dt.date
    if source.duplicated(KEYS).any():
        raise ValueError("frozen source sample contains duplicate analysis-date/code rows")
    formation_dates = sorted(source["analysis_date"].unique())
    codes = sorted(source["ts_code"].astype(str).unique())
    facts_root = config.local_warehouse_dir / "facts"
    connection = duckdb.connect()
    try:
        for chunk_number, start in enumerate(range(0, len(codes), CODE_CHUNK_SIZE), 1):
            chunk_codes = codes[start : start + CODE_CHUNK_SIZE]
            equity = _equity_chunk(connection, facts_root, chunk_codes)
            features = compute_price_indicator_panel(
                equity,
                formation_dates=formation_dates,
            )
            expected_keys = source[source["ts_code"].isin(chunk_codes)][KEYS]
            features = expected_keys.merge(
                features,
                on=KEYS,
                how="left",
                validate="one_to_one",
            )
            if len(features) != len(expected_keys):
                raise ValueError("v2 feature merge changed the frozen sample row count")
            features.to_parquet(
                feature_chunks / f"features-{chunk_number:03d}.parquet",
                index=False,
            )
            print(
                f"chunk={chunk_number:02d} codes={len(chunk_codes)} "
                f"raw_rows={len(equity)} feature_rows={len(features)}",
                flush=True,
            )
    finally:
        connection.close()

    features = pd.read_parquet(feature_chunks)
    features["analysis_date"] = pd.to_datetime(
        features["analysis_date"], errors="raise"
    ).dt.date
    features = features.sort_values(KEYS).reset_index(drop=True)
    if len(features) != len(source) or features.duplicated(KEYS).any():
        raise ValueError("v2 features do not match the frozen sample identity")
    features_path = archive_root / "v2-features.parquet"
    features.to_parquet(features_path, index=False)
    sample = _merge_v2_features(source, features)

    thresholds = fit_scenario_thresholds(
        sample,
        development_end=DEVELOPMENT_END,
    )
    validation = sample[
        (sample["analysis_date"] >= VALIDATION_START)
        & (sample["analysis_date"] <= LAST_FORMATION_DATE)
    ].copy()
    scenario_results = evaluate_price_scenarios(
        validation,
        thresholds,
        bootstrap_repetitions=BOOTSTRAP_REPETITIONS,
        random_seed=BOOTSTRAP_SEED,
    )
    assignments = assign_price_scenarios(sample, thresholds)
    membership = sample[KEYS].copy()
    for scenario, groups in assignments.items():
        membership[f"{scenario}__case"] = groups["case"].to_numpy(dtype=bool)
        membership[f"{scenario}__control"] = groups["control"].to_numpy(dtype=bool)
    membership.to_parquet(archive_root / "scenario-membership.parquet", index=False)

    (archive_root / "development-thresholds.json").write_text(
        json.dumps(thresholds, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    rows = _flatten_results(scenario_results)
    pd.DataFrame(rows).to_csv(archive_root / "scenario-results.csv", index=False)
    result = {
        "run_id": RUN_ID,
        "source_run_id": SOURCE_RUN_ID,
        "formula_version": PRICE_INDICATOR_FORMULA_VERSION,
        "validation_label": "time-forward-but-exposed exploratory validation",
        "sample": {
            "source_sha256": _sha256(source_sample_path),
            "row_count": int(len(sample)),
            "stock_count": int(sample["ts_code"].nunique()),
            "formation_date_count": int(sample["analysis_date"].nunique()),
            "first_formation_date": min(sample["analysis_date"]).isoformat(),
            "last_formation_date": max(sample["analysis_date"]).isoformat(),
            "development_rows": int((sample["analysis_date"] <= DEVELOPMENT_END).sum()),
            "validation_rows": int(len(validation)),
            "validation_first_date": min(validation["analysis_date"]).isoformat(),
            "validation_last_date": max(validation["analysis_date"]).isoformat(),
            "future_window_exclusions": (
                "already excluded by source V1; V1 did not retain a separate excluded-row count"
            ),
            "historical_special_treatment": (
                "observable 5% limit-band exclusions retained; complete historical name snapshots unavailable"
            ),
            "action_day_participation": (
                "valid action-day price/amount/volume required by V1; locked-limit executability is not fully replayable"
            ),
            "industry_relative_coverage": (
                "not used because point-in-time industry daily history is incomplete; market-relative fields used"
            ),
        },
        "feature_coverage": {
            field: {
                "finite_rows": int(pd.to_numeric(sample[field], errors="coerce").notna().sum()),
                "finite_rate": float(pd.to_numeric(sample[field], errors="coerce").notna().mean()),
            }
            for field in SCENARIO_THRESHOLD_FIELDS
        },
        "thresholds": thresholds,
        "scenarios": scenario_results,
        "evidence_direction_counts": {
            direction: int(
                sum(
                    values["evidence_profile"]["effect_direction"] == direction
                    for values in scenario_results.values()
                )
            )
            for direction in ("expected", "opposite", "flat_or_unavailable")
        },
    }
    (archive_root / "results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=_json_default) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result["evidence_direction_counts"], ensure_ascii=False), flush=True)
    print(pd.DataFrame(rows).to_string(index=False), flush=True)


def _equity_chunk(
    connection: duckdb.DuckDBPyConnection,
    facts_root: Path,
    codes: list[str],
) -> pd.DataFrame:
    selected = pd.DataFrame({"ts_code": codes})
    connection.register("selected_scenario_codes", selected)
    try:
        return connection.execute(
            """
            SELECT
                e.trade_date,
                e.ts_code,
                e.open,
                e.high,
                e.low,
                e.close,
                e.amount,
                a.adj_factor
            FROM read_parquet(?) e
            JOIN selected_scenario_codes c USING (ts_code)
            JOIN read_parquet(?) a USING (trade_date, ts_code)
            WHERE e.trade_date <= ?
            ORDER BY e.ts_code, e.trade_date
            """,
            [
                str(facts_root / "equity_daily" / "**" / "*.parquet"),
                str(facts_root / "adj_factor" / "**" / "*.parquet"),
                LAST_FORMATION_DATE,
            ],
        ).fetchdf()
    finally:
        connection.unregister("selected_scenario_codes")


def _merge_v2_features(source: pd.DataFrame, features: pd.DataFrame) -> pd.DataFrame:
    """Replace overlapping V1 indicator columns while preserving frozen labels."""

    if source.duplicated(KEYS).any() or features.duplicated(KEYS).any():
        raise ValueError("source and v2 features must be unique by analysis-date/code")
    replacement = [
        column for column in features.columns if column in source.columns and column not in KEYS
    ]
    retained = source.drop(columns=replacement)
    merged = retained.merge(features, on=KEYS, how="inner", validate="one_to_one")
    if len(merged) != len(source) or len(merged) != len(features):
        raise ValueError("source and v2 features have different identity sets")
    return merged.sort_values(KEYS).reset_index(drop=True)


def _flatten_results(results: dict[str, dict[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for scenario, values in results.items():
        spec = SCENARIO_SPECS[scenario]
        year_primary = values["year_primary_deltas"]
        rows.append(
            {
                "scenario": scenario,
                "label_cn": spec["label_cn"],
                "family": spec["family"],
                "expected": spec["expected"],
                "effect_direction": values["evidence_profile"]["effect_direction"],
                "interval_relation": values["evidence_profile"]["interval_relation"],
                "case_rows": values["case_row_count"],
                "control_rows": values["control_row_count"],
                "common_dates": values["common_date_count"],
                "case_hit_rate": values["case_hit_rate"],
                "control_hit_rate": values["control_hit_rate"],
                "hit_delta_date_equal": values["hit_rate_delta_date_equal"],
                "case_mfe_median": values["case_mfe"],
                "control_mfe_median": values["control_mfe"],
                "mfe_delta_date_equal": values["mfe_delta_date_equal"],
                "case_mae_median": values["case_mae"],
                "control_mae_median": values["control_mae"],
                "mae_delta_date_equal": values["mae_delta_date_equal"],
                "case_d20_median": values["case_d20"],
                "control_d20_median": values["control_d20"],
                "d20_delta_date_equal": values["d20_delta_date_equal"],
                "primary_delta": values["primary_delta"],
                "primary_ci_low": values["primary_ci_low"],
                "primary_ci_high": values["primary_ci_high"],
                "expected_holm_p": values["expected_holm_p"],
                "opposite_holm_p": values["opposite_holm_p"],
                "primary_delta_2025": year_primary["2025"],
                "primary_delta_2026": year_primary["2026"],
            }
        )
    return rows


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_default(value: object) -> object:
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, (date, pd.Timestamp)):
        return value.isoformat()
    raise TypeError(f"cannot serialize {type(value).__name__}")


if __name__ == "__main__":
    main()
