from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class RankerFitResult:
    status: str
    pipeline: Any | None = None
    reason_code: str | None = None


@dataclass(frozen=True)
class ThresholdSelectionResult:
    status: str
    threshold: float | None
    nonempty_dates: int
    total_selections: int
    max_daily_selections: int
    average_precision: float | None = None
    conditional_precision: float | None = None
    reason_code: str | None = None


def fit_ranker(
    frame: pd.DataFrame,
    *,
    label_column: str,
    numeric_columns: list[str],
    categorical_columns: list[str],
    C: float,
    seed: int = 20260817,
) -> RankerFitResult:
    labels = frame[label_column].astype(bool)
    if labels.nunique(dropna=True) < 2:
        return RankerFitResult(
            status="not_trainable", reason_code="training_labels_have_one_class"
        )

    try:
        from sklearn.compose import ColumnTransformer
        from sklearn.impute import SimpleImputer
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import OneHotEncoder, StandardScaler
    except ImportError as exc:  # pragma: no cover - environment-specific guard
        return RankerFitResult(
            status="not_trainable",
            reason_code=f"missing_optional_dependency:{exc.name}",
        )

    numeric_pipeline = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median", add_indicator=True)),
            ("scaler", StandardScaler()),
        ]
    )
    categorical_pipeline = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="most_frequent")),
            ("onehot", OneHotEncoder(handle_unknown="ignore")),
        ]
    )
    transformers: list[tuple[str, Any, list[str]]] = []
    if numeric_columns:
        transformers.append(("numeric", numeric_pipeline, numeric_columns))
    if categorical_columns:
        transformers.append(("categorical", categorical_pipeline, categorical_columns))
    preprocess = ColumnTransformer(transformers, remainder="drop")
    pipeline = Pipeline(
        [
            ("preprocess", preprocess),
            (
                "model",
                LogisticRegression(
                    C=C,
                    solver="liblinear",
                    max_iter=2000,
                    tol=1e-6,
                    random_state=seed,
                ),
            ),
        ]
    )
    pipeline.fit(frame[numeric_columns + categorical_columns], labels)
    return RankerFitResult(status="fitted", pipeline=pipeline)


def choose_c(metrics: dict[float, dict[str, float]]) -> float:
    if not metrics:
        raise ValueError("metrics must not be empty")
    return min(
        metrics,
        key=lambda c: (
            -metrics[c]["policy_precision_at_5"],
            metrics[c]["brier"],
            c,
        ),
    )


def choose_model_variant(
    *, plain: dict[str, float], typed: dict[str, float]
) -> str:
    precision_gain = (
        typed["policy_precision_at_5"] - plain["policy_precision_at_5"]
    )
    if precision_gain >= 0.02 - 1e-12 and typed["brier"] <= plain["brier"]:
        return "with_opportunity_type"
    return "without_opportunity_type"


def select_probability_threshold(
    frame: pd.DataFrame,
    *,
    minimum_nonempty_dates: int = 7,
    minimum_total_selections: int = 20,
) -> ThresholdSelectionResult:
    if frame.empty:
        return ThresholdSelectionResult(
            status="not_supported",
            threshold=None,
            nonempty_dates=0,
            total_selections=0,
            max_daily_selections=0,
            reason_code="no_validation_predictions",
        )

    candidates: list[ThresholdSelectionResult] = []
    all_dates = tuple(sorted(frame["formation_date"].unique()))
    for threshold in np.round(np.arange(0.10, 0.901, 0.05), 2):
        daily_precisions: list[float] = []
        nonempty_precisions: list[float] = []
        daily_counts: list[int] = []
        for formation_date in all_dates:
            group = frame.loc[frame["formation_date"] == formation_date]
            selected = group.loc[group["probability"] >= threshold].sort_values(
                "probability", ascending=False, kind="mergesort"
            ).head(5)
            if selected.empty:
                daily_precisions.append(0.0)
                continue
            daily_counts.append(len(selected))
            precision = float(selected["hit"].astype(float).mean())
            daily_precisions.append(precision)
            nonempty_precisions.append(precision)
        nonempty_dates = len(daily_counts)
        total_selections = sum(daily_counts)
        if (
            nonempty_dates < minimum_nonempty_dates
            or total_selections < minimum_total_selections
        ):
            continue
        candidates.append(
            ThresholdSelectionResult(
                status="supported",
                threshold=float(threshold),
                nonempty_dates=nonempty_dates,
                total_selections=total_selections,
                max_daily_selections=max(daily_counts, default=0),
                average_precision=float(np.mean(daily_precisions)),
                conditional_precision=float(np.mean(nonempty_precisions)),
            )
        )

    if not candidates:
        return ThresholdSelectionResult(
            status="not_supported",
            threshold=None,
            nonempty_dates=0,
            total_selections=0,
            max_daily_selections=0,
            reason_code="minimum_validation_coverage_not_met",
        )
    return min(
        candidates,
        key=lambda candidate: (
            -float(candidate.average_precision),
            -float(candidate.conditional_precision),
            -candidate.nonempty_dates,
            -float(candidate.threshold),
        ),
    )
