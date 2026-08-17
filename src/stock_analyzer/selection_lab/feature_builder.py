from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class FeatureGroup:
    name: str
    columns: tuple[str, ...]
    feature_type: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class FeatureDictionary:
    groups: tuple[FeatureGroup, ...]
    forbidden_columns: frozenset[str]
    raw: dict[str, Any]

    @property
    def preregistered_columns(self) -> tuple[str, ...]:
        return tuple(column for group in self.groups for column in group.columns)


@dataclass(frozen=True)
class ModelFrame:
    frame: pd.DataFrame
    numeric_columns: list[str]
    categorical_columns: list[str]


def load_feature_dictionary(path: str | Path) -> FeatureDictionary:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    groups = tuple(
        FeatureGroup(
            name=name,
            columns=tuple(value["columns"]),
            feature_type=str(value["type"]),
            metadata={key: item for key, item in value.items() if key != "columns"},
        )
        for name, value in payload["feature_groups"].items()
    )
    columns = [column for group in groups for column in group.columns]
    if len(columns) != len(set(columns)):
        raise ValueError("feature dictionary contains duplicate columns")
    if any("{" in column or "}" in column for column in columns):
        raise ValueError("feature dictionary wildcards must be expanded")
    return FeatureDictionary(
        groups=groups,
        forbidden_columns=frozenset(payload.get("forbidden_columns", [])),
        raw=payload,
    )


def build_model_frame(
    samples: pd.DataFrame,
    dictionary: FeatureDictionary,
    *,
    requested_columns: list[str] | None = None,
    include_opportunity_type: bool = False,
) -> ModelFrame:
    preregistered = set(dictionary.preregistered_columns)
    if requested_columns is not None:
        forbidden = set(requested_columns) & dictionary.forbidden_columns
        if forbidden:
            raise ValueError(f"forbidden model features: {sorted(forbidden)}")
        unknown = set(requested_columns) - preregistered
        if unknown:
            raise ValueError(f"features are not preregistered: {sorted(unknown)}")
        selected = requested_columns
    else:
        selected = [
            column
            for column in dictionary.preregistered_columns
            if column in samples.columns
        ]

    type_columns = {
        column
        for group in dictionary.groups
        if group.feature_type == "categorical_typed_model_only"
        for column in group.columns
    }
    if not include_opportunity_type:
        selected = [column for column in selected if column not in type_columns]
    elif "opportunity_type" in samples.columns and "opportunity_type" not in selected:
        selected.append("opportunity_type")

    missing = [column for column in selected if column not in samples.columns]
    if missing:
        raise ValueError(f"requested feature columns are missing: {missing}")
    numeric: list[str] = []
    categorical: list[str] = []
    for group in dictionary.groups:
        for column in group.columns:
            if column not in selected:
                continue
            if group.feature_type == "numeric":
                numeric.append(column)
            else:
                categorical.append(column)
    ordered = numeric + categorical
    return ModelFrame(
        frame=samples.loc[:, ordered].copy(),
        numeric_columns=numeric,
        categorical_columns=categorical,
    )
