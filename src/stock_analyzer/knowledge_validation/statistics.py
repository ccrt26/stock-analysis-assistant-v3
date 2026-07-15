from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from statistics import NormalDist
from typing import Mapping, Sequence

import numpy as np
import pandas as pd

from stock_analyzer.knowledge_validation.models import (
    LayerResult,
    MethodStatus,
    RelevanceStatus,
)


_BOOTSTRAP_SEED = 20260715
_BOOTSTRAP_REPETITIONS = 2_000
_BOOTSTRAP_BLOCK_LENGTH = 30


def moving_block_bootstrap(
    values: Sequence[float] | np.ndarray,
    *,
    block_length: int = _BOOTSTRAP_BLOCK_LENGTH,
    repetitions: int = _BOOTSTRAP_REPETITIONS,
    seed: int = _BOOTSTRAP_SEED,
) -> dict[str, float | int]:
    array = np.asarray(values, dtype=float)
    array = array[np.isfinite(array)]
    if array.size == 0:
        raise ValueError("moving-block bootstrap requires at least one finite value")
    if block_length <= 0 or repetitions <= 0:
        raise ValueError("block length and repetitions must be positive")

    rng = np.random.default_rng(seed)
    sample_size = int(array.size)
    effective_block = min(block_length, sample_size)
    block_count = ceil(sample_size / effective_block)
    maximum_start = sample_size - effective_block
    estimates = np.empty(repetitions, dtype=float)
    for repetition in range(repetitions):
        starts = rng.integers(0, maximum_start + 1, size=block_count)
        sample = np.concatenate(
            [array[start : start + effective_block] for start in starts]
        )[:sample_size]
        estimates[repetition] = float(np.mean(sample))

    estimate = float(np.mean(array))
    nonpositive = (int(np.count_nonzero(estimates <= 0)) + 1) / (repetitions + 1)
    nonnegative = (int(np.count_nonzero(estimates >= 0)) + 1) / (repetitions + 1)
    return {
        "estimate": estimate,
        "lower_95": float(np.quantile(estimates, 0.025)),
        "upper_95": float(np.quantile(estimates, 0.975)),
        "p_value_two_sided": float(min(1.0, 2 * min(nonpositive, nonnegative))),
        "sample_size": sample_size,
        "block_length": block_length,
        "repetitions": repetitions,
        "seed": seed,
    }


def benjamini_hochberg(p_values: Mapping[str, float]) -> dict[str, float]:
    if not p_values:
        return {}
    checked: list[tuple[str, float]] = []
    for key, value in p_values.items():
        number = float(value)
        if not np.isfinite(number) or number < 0 or number > 1:
            raise ValueError(f"invalid p-value for {key}: {value}")
        checked.append((key, number))
    ordered = sorted(checked, key=lambda item: (item[1], item[0]))
    count = len(ordered)
    adjusted = [0.0] * count
    running = 1.0
    for index in range(count - 1, -1, -1):
        rank = index + 1
        running = min(running, ordered[index][1] * count / rank)
        adjusted[index] = min(1.0, running)
    return {key: adjusted[index] for index, (key, _) in enumerate(ordered)}


def aggregate_independent_units(
    frame: pd.DataFrame,
    *,
    value_column: str,
    unit_columns: tuple[str, ...],
    observation_columns: tuple[str, ...],
) -> pd.DataFrame:
    required = set(unit_columns) | set(observation_columns) | {value_column}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"aggregation input missing columns: {sorted(missing)}")
    deduplicated = frame.drop_duplicates(list(observation_columns), keep="first")
    result = (
        deduplicated.groupby(list(unit_columns), dropna=False, sort=True)[value_column]
        .mean()
        .reset_index()
    )
    return result.sort_values(list(unit_columns), kind="mergesort").reset_index(drop=True)


def _top_minus_bottom(
    panel: pd.DataFrame,
    *,
    unit: str,
    group: str,
    value: str,
    top: int = 5,
    bottom: int = 1,
) -> pd.DataFrame:
    required = {unit, group, value}
    missing = required - set(panel.columns)
    if missing:
        raise ValueError(f"primary study panel missing columns: {sorted(missing)}")
    grouped = (
        panel.groupby([unit, group], dropna=False, sort=True)[value]
        .mean()
        .unstack(group)
    )
    if top not in grouped or bottom not in grouped:
        return pd.DataFrame(columns=[unit, "primary_value"])
    result = (grouped[top] - grouped[bottom]).dropna().rename("primary_value")
    return result.reset_index()


def primary_study_series(study_id: str, panel: pd.DataFrame) -> pd.DataFrame:
    if study_id == "a_share_size_value":
        return _top_minus_bottom(
            panel,
            unit="analysis_date",
            group="signal_quintile",
            value="market_excess_return_20d",
        )
    if study_id == "a_share_momentum_reversal":
        spread = _top_minus_bottom(
            panel,
            unit="analysis_date",
            group="signal_quintile",
            value="market_excess_return_5d",
        )
        spread["primary_value"] = -spread["primary_value"]
        return spread
    if study_id == "price_limit_t_plus_one":
        required = {
            "analysis_date",
            "limit_touched",
            "cap_tercile",
            "prior_return_quintile",
            "market_excess_return_1d",
        }
        missing = required - set(panel.columns)
        if missing:
            raise ValueError(f"primary study panel missing columns: {sorted(missing)}")
        strata = (
            panel.groupby(
                [
                    "analysis_date",
                    "cap_tercile",
                    "prior_return_quintile",
                    "limit_touched",
                ],
                sort=True,
            )["market_excess_return_1d"]
            .mean()
            .unstack("limit_touched")
        )
        if True not in strata or False not in strata:
            return pd.DataFrame(columns=["analysis_date", "primary_value"])
        differences = (strata[True] - strata[False]).dropna()
        return (
            differences.groupby(level="analysis_date")
            .mean()
            .rename("primary_value")
            .reset_index()
        )
    if study_id == "a_share_factor_industry_momentum":
        return _top_minus_bottom(
            panel,
            unit="analysis_date",
            group="signal_quintile",
            value="close_return_20d",
        )
    if study_id == "overseas_industry_momentum_method":
        raw = _top_minus_bottom(
            panel,
            unit="analysis_date",
            group="individual_return_quintile",
            value="market_excess_return_20d",
        ).rename(columns={"primary_value": "raw_spread"})
        residual = _top_minus_bottom(
            panel,
            unit="analysis_date",
            group="industry_subtracted_quintile",
            value="market_excess_return_20d",
        ).rename(columns={"primary_value": "residual_spread"})
        result = raw.merge(residual, on="analysis_date", how="inner")
        result["primary_value"] = result["raw_spread"].abs() - result[
            "residual_spread"
        ].abs()
        return result[["analysis_date", "primary_value"]]
    if study_id == "daily_event_study":
        required = {"event_date", "car_0_1", "is_pseudo_event"}
        missing = required - set(panel.columns)
        if missing:
            raise ValueError(f"primary study panel missing columns: {sorted(missing)}")
        return panel.loc[panel["is_pseudo_event"].astype(bool), ["event_date", "car_0_1"]].rename(
            columns={"car_0_1": "primary_value"}
        )
    if study_id == "a_share_earnings_announcement_drift":
        return _top_minus_bottom(
            panel,
            unit="event_date",
            group="car_quintile",
            value="market_excess_return_20d",
        )
    if study_id == "formal_announcement_price_reaction":
        required = {
            "analysis_date",
            "is_extreme_move",
            "local_formal_announcement_match",
            "cap_tercile",
            "move_magnitude_quintile",
            "market_excess_return_20d",
        }
        missing = required - set(panel.columns)
        if missing:
            raise ValueError(f"primary study panel missing columns: {sorted(missing)}")
        extreme = panel[panel["is_extreme_move"].astype(bool)]
        grouped = (
            extreme.groupby(
                [
                    "analysis_date",
                    "cap_tercile",
                    "move_magnitude_quintile",
                    "local_formal_announcement_match",
                ],
                sort=True,
            )["market_excess_return_20d"]
            .mean()
            .unstack("local_formal_announcement_match")
        )
        if True not in grouped or False not in grouped:
            return pd.DataFrame(columns=["analysis_date", "primary_value"])
        differences = (grouped[True] - grouped[False]).dropna()
        return (
            differences.groupby(level="analysis_date")
            .mean()
            .rename("primary_value")
            .reset_index()
        )
    if study_id == "financial_quality_turnaround":
        required = {
            "report_period",
            "improvement_count",
            "market_excess_return_20d",
        }
        missing = required - set(panel.columns)
        if missing:
            raise ValueError(f"primary study panel missing columns: {sorted(missing)}")
        rows: list[dict[str, object]] = []
        for report_period, group in panel.groupby("report_period", sort=True):
            usable = group[["improvement_count", "market_excess_return_20d"]].dropna()
            correlation = (
                np.nan
                if len(usable) < 2
                else usable["improvement_count"].rank().corr(
                    usable["market_excess_return_20d"].rank()
                )
            )
            if pd.notna(correlation):
                rows.append(
                    {"report_period": report_period, "primary_value": float(correlation)}
                )
        return pd.DataFrame(rows, columns=["report_period", "primary_value"])
    raise ValueError(f"unsupported validation study: {study_id}")


def tost_equivalence(
    values: Sequence[float] | np.ndarray,
    *,
    lower: float,
    upper: float,
) -> dict[str, float | int | bool]:
    if not lower < upper:
        raise ValueError("equivalence lower bound must be below upper bound")
    array = np.asarray(values, dtype=float)
    array = array[np.isfinite(array)]
    if array.size < 2:
        raise ValueError("TOST requires at least two finite observations")
    mean = float(np.mean(array))
    standard_error = float(np.std(array, ddof=1) / np.sqrt(array.size))
    if standard_error == 0:
        p_lower = 0.0 if mean > lower else 1.0
        p_upper = 0.0 if mean < upper else 1.0
    else:
        normal = NormalDist()
        p_lower = 1 - normal.cdf((mean - lower) / standard_error)
        p_upper = 1 - normal.cdf((upper - mean) / standard_error)
    p_value = float(max(p_lower, p_upper))
    return {
        "mean": mean,
        "standard_error": standard_error,
        "lower_bound": float(lower),
        "upper_bound": float(upper),
        "p_value_lower": float(p_lower),
        "p_value_upper": float(p_upper),
        "p_value": p_value,
        "equivalent": bool(p_value <= 0.05),
        "sample_size": int(array.size),
    }


@dataclass(frozen=True)
class ClassifiedLayers:
    method: LayerResult[MethodStatus]
    trend: LayerResult[RelevanceStatus]
    target: LayerResult[RelevanceStatus]


def classify_layers(
    *,
    sufficient: bool,
    direction_ok: bool,
    confirmation_direction_ok: bool,
    q_value: float,
    stable_blocks_ratio: float,
    trend_supported: bool,
    target_supported: bool,
    predeclared_condition_only: bool = False,
    conditional_q_value: float = 1.0,
    conditional_stable_blocks_ratio: float = 0.0,
) -> ClassifiedLayers:
    metrics = {
        "sufficient": sufficient,
        "direction_ok": direction_ok,
        "confirmation_direction_ok": confirmation_direction_ok,
        "q_value": float(q_value),
        "stable_blocks_ratio": float(stable_blocks_ratio),
    }
    if not sufficient:
        method_status = MethodStatus.INSUFFICIENT_SAMPLE
        relevance_status = RelevanceStatus.INSUFFICIENT_SAMPLE
        return ClassifiedLayers(
            method=LayerResult[MethodStatus](status=method_status, metrics=metrics),
            trend=LayerResult[RelevanceStatus](
                status=relevance_status,
                metrics={"sufficient": False, "supported": trend_supported},
            ),
            target=LayerResult[RelevanceStatus](
                status=relevance_status,
                metrics={"sufficient": False, "supported": target_supported},
            ),
        )

    general = (
        direction_ok
        and confirmation_direction_ok
        and float(q_value) <= 0.05
        and float(stable_blocks_ratio) >= 0.75
    )
    conditional = (
        not general
        and predeclared_condition_only
        and float(conditional_q_value) <= 0.05
        and float(conditional_stable_blocks_ratio) >= 0.75
    )
    if general:
        method_status = MethodStatus.VALIDATED_GENERAL
    elif conditional:
        method_status = MethodStatus.VALIDATED_CONDITIONAL
    else:
        method_status = MethodStatus.NOT_VALIDATED

    method_metrics = {
        **metrics,
        "predeclared_condition_only": predeclared_condition_only,
        "conditional_q_value": float(conditional_q_value),
        "conditional_stable_blocks_ratio": float(conditional_stable_blocks_ratio),
    }
    return ClassifiedLayers(
        method=LayerResult[MethodStatus](status=method_status, metrics=method_metrics),
        trend=LayerResult[RelevanceStatus](
            status=(
                RelevanceStatus.STRONG_SUPPORT
                if trend_supported
                else RelevanceStatus.NEUTRAL
            ),
            metrics={"sufficient": True, "supported": trend_supported},
        ),
        target=LayerResult[RelevanceStatus](
            status=(
                RelevanceStatus.STRONG_SUPPORT
                if target_supported
                else RelevanceStatus.NEUTRAL
            ),
            metrics={"sufficient": True, "supported": target_supported},
        ),
    )


__all__ = [
    "ClassifiedLayers",
    "aggregate_independent_units",
    "benjamini_hochberg",
    "classify_layers",
    "moving_block_bootstrap",
    "primary_study_series",
    "tost_equivalence",
]
