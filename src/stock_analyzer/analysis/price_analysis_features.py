"""Deterministic, scenario-ready price observations for the price Skill.

The output combines the raw path/relative-strength surface with the technical
observations used by the current price research scenarios.  It deliberately
does not assign scenario labels or turn observations into selection rules.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from stock_analyzer.analysis.price_indicator_features import (
    PRICE_INDICATOR_FORMULA_VERSION,
    compute_price_indicator_features,
)
from stock_analyzer.analysis.price_indicator_validation import build_baseline_panel
from stock_analyzer.analysis.price_scenario_validation import (
    SCENARIO_THRESHOLD_FIELDS,
)


PRICE_ANALYSIS_FORMULA_VERSION = "price-analysis-context-v1"

# These event fields are read directly by ``assign_price_scenarios`` in
# addition to the numeric threshold surface.
PRICE_SCENARIO_EVENT_FIELDS = (
    "breakout_prior_250d_high",
    "macd_bullish_cross_last_5d",
    "macd_bearish_cross_last_5d",
    "stochastic_bullish_cross_last_5d",
)

PRICE_SCENARIO_REQUIRED_FIELDS = (
    *SCENARIO_THRESHOLD_FIELDS,
    *PRICE_SCENARIO_EVENT_FIELDS,
)


def compute_price_analysis_features(
    equity_daily: pd.DataFrame,
    benchmark_daily: pd.DataFrame,
    *,
    analysis_date: date,
) -> pd.DataFrame:
    """Return one formation-date-safe, scenario-ready row per observed stock."""

    baseline = build_baseline_panel(
        equity_daily,
        benchmark_daily,
        formation_dates=(analysis_date,),
    )
    indicators = compute_price_indicator_features(
        equity_daily,
        analysis_date=analysis_date,
    ).rename(
        columns={
            "formula_version": "price_indicator_formula_version",
            "coverage_status": "indicator_coverage_status",
            "limitation_notes": "indicator_limitation_notes",
        }
    )
    if baseline.empty or indicators.empty:
        return _empty_result(baseline, indicators)
    result = baseline.merge(
        indicators,
        on=["analysis_date", "ts_code"],
        how="inner",
        validate="one_to_one",
    )
    if len(result) != len(baseline) or len(result) != len(indicators):
        raise ValueError("price baseline and indicator entities do not match")

    missing_contract = sorted(
        set(PRICE_SCENARIO_REQUIRED_FIELDS) - set(result.columns)
    )
    if missing_contract:
        raise ValueError(
            "price scenario contract lacks fields: " + ", ".join(missing_contract)
        )
    result.insert(2, "formula_version", PRICE_ANALYSIS_FORMULA_VERSION)
    result.insert(
        3,
        "price_analysis_formula_version",
        PRICE_ANALYSIS_FORMULA_VERSION,
    )
    missing_by_row = result[list(PRICE_SCENARIO_REQUIRED_FIELDS)].isna()
    scenario_complete = ~missing_by_row.any(axis=1)
    indicator_complete = result["indicator_coverage_status"].eq("complete")
    result["coverage_status"] = (
        scenario_complete & indicator_complete
    ).map({True: "complete", False: "limited"})
    result["limitation_notes"] = result.apply(
        lambda row: _limitation_notes(row, missing_by_row.loc[row.name]),
        axis=1,
    )
    return result.sort_values(["analysis_date", "ts_code"]).reset_index(drop=True)


def _limitation_notes(row: pd.Series, missing: pd.Series) -> str:
    notes: list[str] = []
    indicator_note = str(row.get("indicator_limitation_notes", "")).strip()
    if indicator_note and indicator_note.lower() != "nan":
        notes.append(indicator_note)
    missing_fields = [str(field) for field, value in missing.items() if bool(value)]
    if missing_fields:
        notes.append("scenario inputs unavailable: " + ", ".join(missing_fields))
    return "; ".join(dict.fromkeys(notes))


def _empty_result(
    baseline: pd.DataFrame,
    indicators: pd.DataFrame,
) -> pd.DataFrame:
    columns = list(
        dict.fromkeys(
            [
                "analysis_date",
                "ts_code",
                "formula_version",
                "price_analysis_formula_version",
                *baseline.columns,
                *indicators.columns,
                *PRICE_SCENARIO_REQUIRED_FIELDS,
                "coverage_status",
                "limitation_notes",
            ]
        )
    )
    return pd.DataFrame(columns=columns)


__all__ = [
    "PRICE_ANALYSIS_FORMULA_VERSION",
    "PRICE_SCENARIO_EVENT_FIELDS",
    "PRICE_SCENARIO_REQUIRED_FIELDS",
    "compute_price_analysis_features",
]
