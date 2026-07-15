from __future__ import annotations

from dataclasses import dataclass
from math import ceil
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
]
