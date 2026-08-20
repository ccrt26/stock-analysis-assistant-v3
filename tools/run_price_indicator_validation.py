"""Run the frozen 2026-08-19 price-indicator validation once.

The script writes only Git-ignored research artifacts under ``local_archive``.
Its probabilities are comparison instruments, never production selection scores.
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
from stock_analyzer.analysis.price_indicator_validation import (
    admission_decision,
    build_baseline_panel,
    build_outcome_panel,
    cross_sectional_transform,
    evaluate_predictions,
    fit_ridge_logistic,
    predict_logistic,
)
from stock_analyzer.config import AppConfig


RUN_ID = "2026-08-19-price-indicator-validation-v1"
FIRST_FORMATION_DATE = date(2022, 7, 26)
DEVELOPMENT_END = date(2024, 12, 31)
VALIDATION_START = date(2025, 1, 2)
LAST_FORMATION_DATE = date(2026, 7, 21)
DATA_THROUGH = date(2026, 8, 18)
FORMATION_STEP = 5
TOP_COUNT = 20
BOOTSTRAP_REPETITIONS = 500
BOOTSTRAP_SEED = 20260819
CODE_CHUNK_SIZE = 250


FAMILIES: dict[str, list[str]] = {
    "trend_direction_acceleration": [
        "ema_distance_20d",
        "macd_dif_12_26",
        "macd_dea_9",
        "macd_histogram_12_26_9",
    ],
    "path_efficiency_strength": ["efficiency_ratio_20d", "adx_14d"],
    "range_oscillation": [
        "rsi_14d",
        "stochastic_k_9_3",
        "stochastic_d_9_3",
    ],
    "volatility_standardized_location": [
        "bollinger_percent_b_20_2",
        "bollinger_bandwidth_20_2",
    ],
    "long_horizon_anchor": [
        "distance_to_prior_250d_high",
        "breakout_prior_250d_high",
    ],
    "price_volume_direction": [
        "signed_amount_balance_20d",
        "price_amount_efficiency_20d",
    ],
}


BASELINE_FEATURES = [
    *[
        field
        for horizon in (1, 3, 5, 10, 20, 60)
        for field in (f"return_{horizon}d", f"relative_market_{horizon}d")
    ],
    "relative_continuity_5d",
    "relative_strength_slope_5d",
    "up_days_5d",
    "mean_close_position_5d",
    "upper_shadow_frequency_5d",
    "fade_frequency_5d",
    "volume_amplification_days_5d",
    "volume_price_efficiency_5d",
    "limit_up_return_contribution_5d",
    "breakout_vs_prior60",
    "price_location_60d",
    "price_location_82d",
    "realized_volatility_20d_annualized",
    "atr_ratio_20d",
    "liquidity_log10_amount",
    "amount_ratio_last_20d",
    "vol_adjusted_relative_strength_5d",
]


def main() -> None:
    config = AppConfig.load()
    warehouse_root = config.local_warehouse_dir
    archive_root = config.local_archive_dir / "price_indicator_validation" / RUN_ID
    if archive_root.exists():
        raise FileExistsError(
            f"frozen output already exists; choose a new RUN_ID instead of overwriting: {archive_root}"
        )
    chunk_root = archive_root / "chunks"
    chunk_root.mkdir(parents=True)
    facts_root = warehouse_root / "facts"
    connection = duckdb.connect()
    try:
        formation_dates = _formation_dates(connection, facts_root)
        benchmark = _benchmark(connection, facts_root)
        securities = _eligible_security_catalog(connection, facts_root)
        codes = securities["ts_code"].astype(str).sort_values().tolist()
        print(
            f"formation_dates={len(formation_dates)} codes={len(codes)} "
            f"development={sum(day <= DEVELOPMENT_END for day in formation_dates)} "
            f"validation={sum(day >= VALIDATION_START for day in formation_dates)}",
            flush=True,
        )
        for chunk_number, start in enumerate(range(0, len(codes), CODE_CHUNK_SIZE), 1):
            chunk_codes = codes[start : start + CODE_CHUNK_SIZE]
            equity = _equity_chunk(connection, facts_root, chunk_codes)
            indicators = compute_price_indicator_panel(
                equity,
                formation_dates=formation_dates,
            )
            baseline = build_baseline_panel(
                equity,
                benchmark,
                formation_dates=formation_dates,
            )
            outcomes = build_outcome_panel(
                equity,
                formation_dates=formation_dates,
            )
            sample = indicators.merge(
                baseline,
                on=["analysis_date", "ts_code"],
                how="inner",
                validate="one_to_one",
            ).merge(
                outcomes,
                on=["analysis_date", "ts_code"],
                how="inner",
                validate="one_to_one",
            )
            sample = _apply_universe_filters(sample, equity, securities)
            chunk_path = chunk_root / f"sample-{chunk_number:03d}.parquet"
            sample.to_parquet(chunk_path, index=False)
            print(
                f"chunk={chunk_number:02d} codes={len(chunk_codes)} "
                f"raw_rows={len(equity)} sample_rows={len(sample)}",
                flush=True,
            )
    finally:
        connection.close()

    sample = pd.read_parquet(chunk_root)
    sample = sample.sort_values(["analysis_date", "ts_code"]).reset_index(drop=True)
    sample["analysis_date"] = pd.to_datetime(sample["analysis_date"]).dt.date
    sample["action_date"] = pd.to_datetime(sample["action_date"]).dt.date
    sample_path = archive_root / "frozen-sample.parquet"
    sample.to_parquet(sample_path, index=False)
    metrics, predictions = _evaluate_families(sample)
    predictions.to_parquet(archive_root / "validation-predictions.parquet", index=False)
    pd.DataFrame(metrics["family_rows"]).to_csv(
        archive_root / "family-results.csv",
        index=False,
    )
    manifest = _input_manifest(warehouse_root)
    (archive_root / "input-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    result = {
        "run_id": RUN_ID,
        "formula_version": PRICE_INDICATOR_FORMULA_VERSION,
        "validation_label": "time-forward-but-exposed exploratory validation",
        "sample": {
            "row_count": int(len(sample)),
            "stock_count": int(sample["ts_code"].nunique()),
            "formation_date_count": int(sample["analysis_date"].nunique()),
            "first_formation_date": min(sample["analysis_date"]).isoformat(),
            "last_formation_date": max(sample["analysis_date"]).isoformat(),
            "development_rows": int((sample["analysis_date"] <= DEVELOPMENT_END).sum()),
            "validation_rows": int((sample["analysis_date"] >= VALIDATION_START).sum()),
            "hit_rate": float(sample["hit_20pct_d20"].mean()),
            "known_historical_special_treatment_filter": (
                "applied at formation and action dates using observable 5% limit bands; "
                "v1 does not retain the excluded-row count"
            ),
            "historical_st_name_snapshot_status": "incomplete; limit-band inference only",
            "industry_excess_status": (
                "not used for admission: point-in-time industry daily coverage starts "
                "2025-07-02 and is incomplete for the frozen sample"
            ),
        },
        "baseline": metrics["baseline"],
        "families": metrics["families"],
        "admitted_families": [
            family
            for family, values in metrics["families"].items()
            if values["admission"]["passed"]
        ],
        "input_manifest_sha256": manifest["manifest_sha256"],
    }
    (archive_root / "results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=_json_default) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=_json_default), flush=True)


def _formation_dates(connection: duckdb.DuckDBPyConnection, facts_root: Path) -> list[date]:
    calendar_glob = str(facts_root / "trade_calendar" / "**" / "*.parquet")
    dates = connection.execute(
        """
        SELECT DISTINCT cal_date
        FROM read_parquet(?)
        WHERE exchange = 'SSE'
          AND is_open
          AND cal_date BETWEEN ? AND ?
        ORDER BY cal_date
        """,
        [calendar_glob, FIRST_FORMATION_DATE, LAST_FORMATION_DATE],
    ).fetchdf()["cal_date"]
    values = [pd.Timestamp(value).date() for value in dates]
    if not values or values[0] != FIRST_FORMATION_DATE:
        raise ValueError("frozen first formation date is absent from the SSE calendar")
    return values[::FORMATION_STEP]


def _benchmark(connection: duckdb.DuckDBPyConnection, facts_root: Path) -> pd.DataFrame:
    index_glob = str(facts_root / "index_daily" / "**" / "*.parquet")
    return connection.execute(
        """
        SELECT trade_date, close
        FROM read_parquet(?)
        WHERE index_code = '000300.SH'
          AND trade_date <= ?
        ORDER BY trade_date
        """,
        [index_glob, DATA_THROUGH],
    ).fetchdf()


def _eligible_security_catalog(
    connection: duckdb.DuckDBPyConnection,
    facts_root: Path,
) -> pd.DataFrame:
    security_glob = str(facts_root / "security_master" / "**" / "*.parquet")
    frame = connection.execute(
        """
        SELECT ts_code, market, exchange, list_date, delist_date
        FROM read_parquet(?)
        WHERE (market = '主板' AND exchange IN ('SSE', 'SZSE'))
           OR (market = '创业板' AND exchange = 'SZSE')
        ORDER BY ts_code
        """,
        [security_glob],
    ).fetchdf()
    frame["list_date"] = pd.to_datetime(frame["list_date"], format="%Y%m%d", errors="coerce").dt.date
    frame["delist_date"] = pd.to_datetime(
        frame["delist_date"], format="%Y%m%d", errors="coerce"
    ).dt.date
    if frame["ts_code"].duplicated().any():
        raise ValueError("security catalog has duplicate codes")
    return frame


def _equity_chunk(
    connection: duckdb.DuckDBPyConnection,
    facts_root: Path,
    codes: list[str],
) -> pd.DataFrame:
    code_frame = pd.DataFrame({"ts_code": codes})
    connection.register("selected_codes", code_frame)
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
                e.pre_close,
                e.volume,
                e.amount,
                a.adj_factor,
                l.up_limit,
                l.down_limit
            FROM read_parquet(?) e
            JOIN selected_codes c USING (ts_code)
            JOIN read_parquet(?) a USING (trade_date, ts_code)
            LEFT JOIN read_parquet(?) l USING (trade_date, ts_code)
            WHERE e.trade_date <= ?
            ORDER BY e.ts_code, e.trade_date
            """,
            [
                str(facts_root / "equity_daily" / "**" / "*.parquet"),
                str(facts_root / "adj_factor" / "**" / "*.parquet"),
                str(facts_root / "stock_limit" / "**" / "*.parquet"),
                DATA_THROUGH,
            ],
        ).fetchdf()
    finally:
        connection.unregister("selected_codes")


def _apply_universe_filters(
    sample: pd.DataFrame,
    equity: pd.DataFrame,
    securities: pd.DataFrame,
) -> pd.DataFrame:
    if sample.empty:
        return sample
    output = sample.merge(
        securities[["ts_code", "list_date", "delist_date"]],
        on="ts_code",
        how="left",
        validate="many_to_one",
    )
    limits = equity[
        ["trade_date", "ts_code", "pre_close", "up_limit", "down_limit"]
    ].copy()
    limits["trade_date"] = pd.to_datetime(limits["trade_date"], errors="raise").dt.date
    limits["known_special_treatment"] = _known_five_percent_limit(limits)
    formation_limits = limits[["trade_date", "ts_code", "known_special_treatment"]].rename(
        columns={
            "trade_date": "analysis_date",
            "known_special_treatment": "formation_known_special_treatment",
        }
    )
    action_limits = limits[["trade_date", "ts_code", "known_special_treatment"]].rename(
        columns={
            "trade_date": "action_date",
            "known_special_treatment": "action_known_special_treatment",
        }
    )
    output = output.merge(
        formation_limits,
        on=["analysis_date", "ts_code"],
        how="left",
        validate="one_to_one",
    ).merge(
        action_limits,
        on=["action_date", "ts_code"],
        how="left",
        validate="one_to_one",
    )
    listed = output["list_date"].notna() & (output["list_date"] <= output["analysis_date"])
    not_delisted = output["delist_date"].isna() | (
        output["action_date"] < output["delist_date"]
    )
    enough_history = output["available_price_sessions"] >= 82
    known_special = output[
        ["formation_known_special_treatment", "action_known_special_treatment"]
    ].fillna(False).any(axis=1)
    output["known_special_treatment_excluded"] = known_special
    output = output[listed & not_delisted & enough_history & ~known_special].copy()
    return output.drop(columns=["list_date", "delist_date"])


def _known_five_percent_limit(limits: pd.DataFrame) -> pd.Series:
    pre_close = pd.to_numeric(limits["pre_close"], errors="coerce")
    up_limit = pd.to_numeric(limits["up_limit"], errors="coerce")
    down_limit = pd.to_numeric(limits["down_limit"], errors="coerce")
    valid = (pre_close > 0.0) & (up_limit > 0.0) & (down_limit > 0.0)
    up_band = up_limit / pre_close - 1.0
    down_band = 1.0 - down_limit / pre_close
    return (valid & (up_band <= 0.06) & (down_band <= 0.06)).astype(bool)


def _evaluate_families(sample: pd.DataFrame) -> tuple[dict[str, Any], pd.DataFrame]:
    development = sample["analysis_date"] <= DEVELOPMENT_END
    validation = sample["analysis_date"] >= VALIDATION_START
    transformed_baseline, baseline_columns = cross_sectional_transform(
        sample,
        BASELINE_FEATURES,
    )
    baseline_matrix = transformed_baseline[baseline_columns].to_numpy(dtype=np.float32)
    target = sample["hit_20pct_d20"].to_numpy(dtype=float)
    training_indices = _fixed_training_indices(sample.loc[development], target[development])
    development_positions = np.flatnonzero(development.to_numpy())
    selected_training_positions = development_positions[training_indices]
    baseline_coefficients = fit_ridge_logistic(
        baseline_matrix[selected_training_positions].astype(float),
        target[selected_training_positions],
        penalty=1.0,
        max_passes=20,
    )
    baseline_coefficients[0] += _prevalence_intercept_correction(
        target[development],
        target[selected_training_positions],
    )
    predictions = sample[
        [
            "analysis_date",
            "ts_code",
            "hit_20pct_d20",
            "mfe_20d",
            "mae_20d",
            "time_to_hit_20pct",
        ]
    ].copy()
    predictions["baseline_probability"] = predict_logistic(
        baseline_matrix,
        baseline_coefficients,
    )
    baseline_development = evaluate_predictions(
        predictions.loc[development],
        probability_column="baseline_probability",
        top_count=TOP_COUNT,
    )
    baseline_validation = evaluate_predictions(
        predictions.loc[validation],
        probability_column="baseline_probability",
        top_count=TOP_COUNT,
    )
    family_intermediate: dict[str, dict[str, Any]] = {}
    bootstrap_distributions: dict[str, np.ndarray] = {}
    for family, fields in FAMILIES.items():
        transformed_family, family_columns = cross_sectional_transform(sample, fields)
        family_matrix = np.column_stack(
            [
                baseline_matrix,
                transformed_family[family_columns].to_numpy(dtype=np.float32),
            ]
        )
        coefficients = fit_ridge_logistic(
            family_matrix[selected_training_positions].astype(float),
            target[selected_training_positions],
            penalty=1.0,
            max_passes=20,
        )
        coefficients[0] += _prevalence_intercept_correction(
            target[development],
            target[selected_training_positions],
        )
        probability_column = f"{family}_probability"
        predictions[probability_column] = predict_logistic(family_matrix, coefficients)
        development_metrics = evaluate_predictions(
            predictions.loc[development],
            probability_column=probability_column,
            top_count=TOP_COUNT,
        )
        validation_metrics = evaluate_predictions(
            predictions.loc[validation],
            probability_column=probability_column,
            top_count=TOP_COUNT,
        )
        stability = _stability_differences(
            predictions.loc[validation],
            probability_column,
        )
        distribution = _two_way_bootstrap_top_difference(
            predictions.loc[validation],
            family_probability=probability_column,
        )
        bootstrap_distributions[family] = distribution
        coverage = float(sample.loc[validation, fields].notna().all(axis=1).mean())
        family_intermediate[family] = {
            "fields": fields,
            "coverage": coverage,
            "development": development_metrics,
            "validation": validation_metrics,
            "stability_top_hit_rate_differences": stability,
            "positive_stability_periods": int(sum(value > 0.0 for value in stability.values())),
            "bootstrap_ci_low": float(np.quantile(distribution, 0.025)),
            "bootstrap_ci_high": float(np.quantile(distribution, 0.975)),
            "raw_p_value": float((1 + np.sum(distribution <= 0.0)) / (len(distribution) + 1)),
        }
        del family_matrix, transformed_family
    adjusted_p = _holm_adjust(
        {family: values["raw_p_value"] for family, values in family_intermediate.items()}
    )
    family_results: dict[str, dict[str, Any]] = {}
    family_rows: list[dict[str, Any]] = []
    for family, values in family_intermediate.items():
        validation_metrics = values["validation"]
        auc_increment = float(validation_metrics["auc"] - baseline_validation["auc"])
        relative_log_loss_improvement = float(
            (baseline_validation["log_loss"] - validation_metrics["log_loss"])
            / baseline_validation["log_loss"]
        )
        top_hit_increment = float(
            validation_metrics["top_date_equal_hit_rate"]
            - baseline_validation["top_date_equal_hit_rate"]
        )
        top_mae_change = float(
            validation_metrics["top_date_equal_mae"]
            - baseline_validation["top_date_equal_mae"]
        )
        admission_inputs = {
            "auc_increment": auc_increment,
            "relative_log_loss_improvement": relative_log_loss_improvement,
            "top_hit_rate_increment": top_hit_increment,
            "bootstrap_ci_low": values["bootstrap_ci_low"],
            "holm_p_value": adjusted_p[family],
            "positive_stability_periods": values["positive_stability_periods"],
            "top_mae_change": top_mae_change,
            "coverage": values["coverage"],
        }
        result = {
            **values,
            "auc_increment": auc_increment,
            "relative_log_loss_improvement": relative_log_loss_improvement,
            "top_hit_rate_increment": top_hit_increment,
            "top_mae_change": top_mae_change,
            "holm_p_value": adjusted_p[family],
            "admission": admission_decision(admission_inputs),
        }
        family_results[family] = result
        family_rows.append(
            {
                "family": family,
                "coverage": values["coverage"],
                "development_auc": values["development"]["auc"],
                "validation_auc": validation_metrics["auc"],
                "auc_increment": auc_increment,
                "validation_log_loss": validation_metrics["log_loss"],
                "relative_log_loss_improvement": relative_log_loss_improvement,
                "validation_top_hit_rate": validation_metrics[
                    "top_date_equal_hit_rate"
                ],
                "top_hit_rate_increment": top_hit_increment,
                "bootstrap_ci_low": values["bootstrap_ci_low"],
                "bootstrap_ci_high": values["bootstrap_ci_high"],
                "holm_p_value": adjusted_p[family],
                "positive_stability_periods": values["positive_stability_periods"],
                "top_mae_change": top_mae_change,
                "passed": result["admission"]["passed"],
                "failed_conditions": "|".join(result["admission"]["failed_conditions"]),
            }
        )
    return (
        {
            "baseline": {
                "features": BASELINE_FEATURES,
                "development": baseline_development,
                "validation": baseline_validation,
                "training_row_count": int(len(selected_training_positions)),
            },
            "families": family_results,
            "family_rows": family_rows,
        },
        predictions,
    )


def _fixed_training_indices(development: pd.DataFrame, target: np.ndarray) -> np.ndarray:
    positive = np.flatnonzero(target == 1.0)
    negative = np.flatnonzero(target == 0.0)
    negative_limit = min(len(negative), 2 * len(positive))
    keys = development["analysis_date"].astype(str) + "|" + development["ts_code"].astype(str)
    hashes = pd.util.hash_pandas_object(keys, index=False).to_numpy(dtype=np.uint64)
    selected_negative = negative[np.argsort(hashes[negative], kind="stable")[:negative_limit]]
    return np.sort(np.concatenate([positive, selected_negative]))


def _prevalence_intercept_correction(full_target: np.ndarray, sample_target: np.ndarray) -> float:
    full = float(np.clip(np.mean(full_target), 1e-8, 1.0 - 1e-8))
    sampled = float(np.clip(np.mean(sample_target), 1e-8, 1.0 - 1e-8))
    return float(np.log(full / (1.0 - full)) - np.log(sampled / (1.0 - sampled)))


def _stability_differences(
    validation: pd.DataFrame,
    family_probability: str,
) -> dict[str, float]:
    periods = {
        "2025H1": (date(2025, 1, 1), date(2025, 6, 30)),
        "2025H2": (date(2025, 7, 1), date(2025, 12, 31)),
        "2026H1": (date(2026, 1, 1), date(2026, 6, 30)),
        "2026H2_partial_to_07_21": (date(2026, 7, 1), LAST_FORMATION_DATE),
    }
    differences: dict[str, float] = {}
    for label, (start, end) in periods.items():
        subset = validation[
            (validation["analysis_date"] >= start) & (validation["analysis_date"] <= end)
        ]
        if subset.empty:
            differences[label] = np.nan
            continue
        baseline = evaluate_predictions(
            subset,
            probability_column="baseline_probability",
            top_count=TOP_COUNT,
        )
        family = evaluate_predictions(
            subset,
            probability_column=family_probability,
            top_count=TOP_COUNT,
        )
        differences[label] = float(
            family["top_date_equal_hit_rate"] - baseline["top_date_equal_hit_rate"]
        )
    return differences


def _two_way_bootstrap_top_difference(
    validation: pd.DataFrame,
    *,
    family_probability: str,
) -> np.ndarray:
    dates = sorted(validation["analysis_date"].unique())
    codes = sorted(validation["ts_code"].unique())
    code_position = {code: offset for offset, code in enumerate(codes)}
    selected: list[tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]] = []
    for formation_date in dates:
        day = validation[validation["analysis_date"] == formation_date]
        baseline = day.sort_values(
            ["baseline_probability", "ts_code"], ascending=[False, True]
        ).head(TOP_COUNT)
        family = day.sort_values(
            [family_probability, "ts_code"], ascending=[False, True]
        ).head(TOP_COUNT)
        selected.append(
            (
                np.asarray([code_position[value] for value in baseline["ts_code"]], dtype=int),
                baseline["hit_20pct_d20"].to_numpy(dtype=float),
                np.asarray([code_position[value] for value in family["ts_code"]], dtype=int),
                family["hit_20pct_d20"].to_numpy(dtype=float),
            )
        )
    block_starts = list(range(0, len(dates), 4))
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    distribution = np.empty(BOOTSTRAP_REPETITIONS, dtype=float)
    for repetition in range(BOOTSTRAP_REPETITIONS):
        sampled_starts = rng.choice(block_starts, size=len(block_starts), replace=True)
        sampled_dates = [
            offset
            for start in sampled_starts
            for offset in range(start, min(start + 4, len(dates)))
        ][: len(dates)]
        stock_weights = np.bincount(
            rng.integers(0, len(codes), size=len(codes)),
            minlength=len(codes),
        ).astype(float)
        differences: list[float] = []
        for date_position in sampled_dates:
            base_codes, base_hits, family_codes, family_hits = selected[date_position]
            base_weights = stock_weights[base_codes]
            family_weights = stock_weights[family_codes]
            if base_weights.sum() == 0.0 or family_weights.sum() == 0.0:
                continue
            differences.append(
                float(
                    np.average(family_hits, weights=family_weights)
                    - np.average(base_hits, weights=base_weights)
                )
            )
        distribution[repetition] = float(np.mean(differences)) if differences else np.nan
    return distribution[np.isfinite(distribution)]


def _holm_adjust(raw: dict[str, float]) -> dict[str, float]:
    ordered = sorted(raw, key=raw.get)
    adjusted: dict[str, float] = {}
    running = 0.0
    total = len(ordered)
    for position, family in enumerate(ordered):
        running = max(running, min(1.0, (total - position) * raw[family]))
        adjusted[family] = running
    return adjusted


def _input_manifest(warehouse_root: Path) -> dict[str, Any]:
    datasets = [
        "equity_daily",
        "adj_factor",
        "stock_limit",
        "trade_calendar",
        "security_master",
        "index_daily",
    ]
    connection = duckdb.connect(str(warehouse_root / "research.duckdb"), read_only=True)
    try:
        rows = connection.execute(
            """
            SELECT dataset_id, partition_value, row_count, content_hash, file_sha256, quality_status
            FROM research_fact_partitions
            WHERE dataset_id IN (SELECT * FROM unnest(?))
            ORDER BY dataset_id, partition_value
            """,
            [datasets],
        ).fetchdf().to_dict("records")
    finally:
        connection.close()
    canonical = json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str)
    return {
        "datasets": datasets,
        "partition_count": len(rows),
        "partitions": rows,
        "manifest_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    }


def _json_default(value: object) -> object:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (date, pd.Timestamp)):
        return value.isoformat()
    raise TypeError(f"cannot serialize {type(value).__name__}")


if __name__ == "__main__":
    main()
