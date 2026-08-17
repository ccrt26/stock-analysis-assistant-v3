from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np
import pandas as pd


def bootstrap_date_mean(
    values: Mapping[object, float],
    *,
    iterations: int = 10_000,
    seed: int = 20260817,
) -> tuple[float, float]:
    """Return a deterministic 95% interval by resampling formation dates."""
    observations = np.asarray(list(values.values()), dtype=float)
    if observations.size == 0:
        return (float("nan"), float("nan"))
    generator = np.random.default_rng(seed)
    indices = generator.integers(
        0, observations.size, size=(iterations, observations.size)
    )
    means = observations[indices].mean(axis=1)
    low, high = np.quantile(means, [0.025, 0.975])
    return (float(low), float(high))


def _mean_or_none(values: Sequence[float]) -> float | None:
    return float(np.mean(values)) if values else None


def evaluate_rankings(
    frame: pd.DataFrame,
    *,
    ks: tuple[int, ...] = (1, 3, 5),
) -> dict[str, object]:
    """Evaluate a frozen policy ranking with equal weight per formation date.

    Executable precision is measured on the already selected policy candidates;
    a non-executable candidate is never replaced by a lower-ranked candidate.
    """
    result: dict[str, object] = {}
    if frame.empty:
        for k in ks:
            result[f"policy_precision_at_{k}"] = None
            result[f"executable_precision_at_{k}"] = None
        result["reason_code"] = "no_evaluable_rows"
        return result

    ranked = frame.copy()
    ranked["_row_key"] = np.arange(len(ranked))
    ranked = ranked.sort_values(
        ["formation_date", "score", "_row_key"],
        ascending=[True, False, True],
        kind="mergesort",
    )
    for k in ks:
        policy_by_date: list[float] = []
        executable_by_date: list[float] = []
        for _, group in ranked.groupby("formation_date", sort=True):
            selected = group.head(min(k, len(group)))
            policy_hits = (
                selected["hit"].fillna(False).astype(bool)
                & selected["executable"].fillna(False).astype(bool)
            )
            policy_by_date.append(float(policy_hits.astype(float).mean()))
            executable = selected.loc[selected["executable"].fillna(False).astype(bool)]
            if not executable.empty:
                executable_by_date.append(
                    float(executable["hit"].astype(float).mean())
                )
        result[f"policy_precision_at_{k}"] = _mean_or_none(policy_by_date)
        result[f"executable_precision_at_{k}"] = _mean_or_none(executable_by_date)
    result["reason_code"] = None
    return result
