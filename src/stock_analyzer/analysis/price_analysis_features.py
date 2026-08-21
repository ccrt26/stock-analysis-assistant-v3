"""Deterministic price observations for the price Skill.

The output combines the raw path/relative-strength surface with the technical
observations used by the current price research scenarios, formation-date
industry comparisons and mechanical scenario identities.  It never turns
those observations into scores, rankings across stocks, or selection rules.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from stock_analyzer.analysis.price_indicator_features import (
    PRICE_INDICATOR_FORMULA_VERSION,
    compute_price_indicator_features,
)
from stock_analyzer.analysis.price_indicator_validation import build_baseline_panel
from stock_analyzer.analysis.price_scenario_validation import (
    PRICE_SCENARIO_ASSIGNMENT_VERSION,
    SCENARIO_THRESHOLD_FIELDS,
    assign_price_scenarios,
    load_frozen_price_scenario_thresholds,
)


PRICE_ANALYSIS_FORMULA_VERSION = "price-analysis-context-v2"
INDUSTRY_RETURN_HORIZONS = (1, 3, 5, 20)
MINIMUM_INDUSTRY_MEMBER_COVERAGE = 0.80

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

INDUSTRY_CONTEXT_FIELDS = (
    "primary_industry_code",
    "primary_industry_name",
    "primary_industry_level",
    "industry_comparison_status",
    *(f"industry_equal_weight_return_{horizon}d" for horizon in INDUSTRY_RETURN_HORIZONS),
    *(f"relative_industry_return_{horizon}d" for horizon in INDUSTRY_RETURN_HORIZONS),
    "industry_return_rank_percentile_5d",
)

SCENARIO_IDENTITY_FIELDS = (
    "scenario_assignment_version",
    "scenario_threshold_version",
    "scenario_assignment_status",
    "scenario_case_ids",
    "scenario_control_ids",
)


def compute_price_analysis_features(
    equity_daily: pd.DataFrame,
    benchmark_daily: pd.DataFrame,
    *,
    analysis_date: date,
    industry_catalog: pd.DataFrame | None = None,
    industry_memberships: pd.DataFrame | None = None,
    sector_hotspot: pd.DataFrame | None = None,
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
    result = _add_industry_comparisons(
        result,
        analysis_date=analysis_date,
        industry_catalog=industry_catalog,
        industry_memberships=industry_memberships,
        sector_hotspot=sector_hotspot,
    )
    atr = pd.to_numeric(result["atr_ratio_20d"], errors="coerce")
    valid_atr = np.isfinite(atr) & (atr > 0.0)
    result["target_atr_distance_20pct"] = np.where(
        valid_atr,
        0.20 / atr,
        np.nan,
    )
    result = _add_scenario_identities(result, scenario_complete)
    return result.sort_values(["analysis_date", "ts_code"]).reset_index(drop=True)


def _add_industry_comparisons(
    result: pd.DataFrame,
    *,
    analysis_date: date,
    industry_catalog: pd.DataFrame | None,
    industry_memberships: pd.DataFrame | None,
    sector_hotspot: pd.DataFrame | None,
) -> pd.DataFrame:
    output = result.copy()
    for field in (
        "primary_industry_code",
        "primary_industry_name",
        "primary_industry_level",
    ):
        output[field] = pd.Series([None] * len(output), index=output.index, dtype=object)
    output["industry_comparison_status"] = pd.Series(
        ["limited"] * len(output),
        index=output.index,
        dtype=object,
    )
    for field in INDUSTRY_CONTEXT_FIELDS[4:]:
        output[field] = np.nan
    if (
        industry_catalog is None
        or industry_memberships is None
        or sector_hotspot is None
        or industry_catalog.empty
        or industry_memberships.empty
        or sector_hotspot.empty
    ):
        return output

    catalog = _active_sw_l2_catalog(industry_catalog, analysis_date)
    memberships = _active_sw_l2_memberships(
        industry_memberships,
        analysis_date,
    )
    if catalog.empty or memberships.empty:
        return output
    sectors = _current_l2_sector_rows(sector_hotspot, analysis_date)
    if sectors.empty:
        return output

    membership_counts = memberships.groupby("ts_code").size()
    unique_codes = set(membership_counts[membership_counts == 1].index.astype(str))
    membership_by_stock = (
        memberships[memberships["ts_code"].isin(unique_codes)]
        .set_index("ts_code")["industry_code"]
        .astype(str)
    )
    catalog_counts = catalog.groupby("industry_code").size()
    unique_catalog = catalog[
        catalog["industry_code"].map(catalog_counts).eq(1)
    ].set_index("industry_code")
    sector_counts = sectors.groupby("group_code").size()
    unique_sectors = sectors[
        sectors["group_code"].map(sector_counts).eq(1)
    ].set_index("group_code")
    output_codes = set(output["ts_code"].astype(str))

    for industry_code, group in memberships.groupby("industry_code", sort=True):
        code = str(industry_code)
        if code not in unique_catalog.index or code not in unique_sectors.index:
            continue
        sector = unique_sectors.loc[code]
        sector_returns = {
            horizon: _finite_number(
                sector.get(f"equal_weight_return_{horizon}d")
            )
            for horizon in INDUSTRY_RETURN_HORIZONS
        }
        if (
            str(sector.get("coverage_status", "")).startswith("limited")
            or any(value is None for value in sector_returns.values())
        ):
            continue
        member_codes = set(group["ts_code"].astype(str))
        comparable_codes = sorted(
            code_value
            for code_value in member_codes & output_codes & unique_codes
            if membership_by_stock.get(code_value) == code
            and _stock_horizons_complete(output, code_value)
        )
        coverage = len(comparable_codes) / len(member_codes) if member_codes else 0.0
        if coverage < MINIMUM_INDUSTRY_MEMBER_COVERAGE:
            continue
        positions = output["ts_code"].astype(str).isin(comparable_codes)
        catalog_row = unique_catalog.loc[code]
        output.loc[positions, "primary_industry_code"] = code
        output.loc[positions, "primary_industry_name"] = str(
            catalog_row["industry_name"]
        )
        output.loc[positions, "primary_industry_level"] = "L2"
        output.loc[positions, "industry_comparison_status"] = "complete"
        for horizon, industry_return in sector_returns.items():
            assert industry_return is not None
            output.loc[
                positions,
                f"industry_equal_weight_return_{horizon}d",
            ] = industry_return
            output.loc[
                positions,
                f"relative_industry_return_{horizon}d",
            ] = (
                pd.to_numeric(
                    output.loc[positions, f"return_{horizon}d"],
                    errors="coerce",
                )
                - industry_return
            )
        five_day = pd.to_numeric(
            output.loc[positions, "return_5d"],
            errors="coerce",
        )
        ranks = five_day.rank(method="average")
        percentiles = (
            pd.Series(0.5, index=ranks.index)
            if len(ranks) == 1
            else (ranks - 1.0) / (len(ranks) - 1.0)
        )
        output.loc[
            positions,
            "industry_return_rank_percentile_5d",
        ] = percentiles

    valid_membership = output["ts_code"].astype(str).isin(unique_codes)
    for index in output.index[valid_membership]:
        stock_code = str(output.at[index, "ts_code"])
        industry_code = str(membership_by_stock[stock_code])
        output.at[index, "primary_industry_code"] = industry_code
        output.at[index, "primary_industry_level"] = "L2"
        if industry_code in unique_catalog.index:
            output.at[index, "primary_industry_name"] = str(
                unique_catalog.loc[industry_code, "industry_name"]
            )
    return output


def _active_sw_l2_catalog(frame: pd.DataFrame, analysis_date: date) -> pd.DataFrame:
    required = {
        "industry_system",
        "level",
        "industry_code",
        "industry_name",
        "valid_from",
        "valid_to",
    }
    _require_fields(frame, required, "industry catalog")
    active = _effective_rows(frame, analysis_date)
    active = active.loc[
        active["industry_system"].astype(str).eq("SW2021")
        & active["level"].astype(str).str.upper().eq("L2")
    ].copy()
    if "is_published" in active:
        active = active.loc[active["is_published"].map(_truthy).astype(bool)]
    active["industry_code"] = active["industry_code"].astype(str)
    return active


def _active_sw_l2_memberships(
    frame: pd.DataFrame,
    analysis_date: date,
) -> pd.DataFrame:
    required = {
        "industry_system",
        "level",
        "industry_code",
        "ts_code",
        "valid_from",
        "valid_to",
    }
    _require_fields(frame, required, "industry membership")
    active = _effective_rows(frame, analysis_date)
    active = active.loc[
        active["industry_system"].astype(str).eq("SW2021")
        & active["level"].astype(str).str.upper().eq("L2")
    ].copy()
    active["industry_code"] = active["industry_code"].astype(str)
    active["ts_code"] = active["ts_code"].astype(str)
    return active


def _current_l2_sector_rows(
    frame: pd.DataFrame,
    analysis_date: date,
) -> pd.DataFrame:
    required = {
        "analysis_date",
        "group_type",
        "group_code",
        "level",
        "coverage_status",
        *(f"equal_weight_return_{horizon}d" for horizon in INDUSTRY_RETURN_HORIZONS),
    }
    _require_fields(frame, required, "sector hotspot")
    dates = pd.to_datetime(frame["analysis_date"], errors="raise").dt.date
    current = frame.loc[
        dates.eq(analysis_date)
        & frame["group_type"].astype(str).eq("industry")
        & frame["level"].astype(str).str.upper().eq("L2")
    ].copy()
    current["group_code"] = current["group_code"].astype(str)
    return current


def _effective_rows(frame: pd.DataFrame, analysis_date: date) -> pd.DataFrame:
    boundary = pd.Timestamp(analysis_date)
    valid_from = pd.to_datetime(frame["valid_from"], errors="raise")
    valid_to = pd.to_datetime(frame["valid_to"], errors="coerce")
    return frame.loc[
        (valid_from <= boundary)
        & (valid_to.isna() | (valid_to >= boundary))
    ].copy()


def _stock_horizons_complete(
    frame: pd.DataFrame,
    ts_code: str,
) -> bool:
    rows = frame[frame["ts_code"].astype(str).eq(ts_code)]
    if len(rows) != 1:
        return False
    return all(
        _finite_number(rows.iloc[0].get(f"return_{horizon}d")) is not None
        for horizon in INDUSTRY_RETURN_HORIZONS
    )


def _finite_number(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def _require_fields(frame: pd.DataFrame, required: set[str], label: str) -> None:
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"{label} lacks required fields: {', '.join(missing)}")


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "t", "y", "yes"}


def _add_scenario_identities(
    result: pd.DataFrame,
    scenario_complete: pd.Series,
) -> pd.DataFrame:
    output = result.copy()
    document = load_frozen_price_scenario_thresholds()
    thresholds = document["thresholds"]
    if not isinstance(thresholds, dict):
        raise ValueError("frozen price scenario thresholds are invalid")
    assignments = assign_price_scenarios(output, thresholds)
    case_ids = pd.Series("", index=output.index, dtype=object)
    control_ids = pd.Series("", index=output.index, dtype=object)
    for index in output.index:
        case_ids.at[index] = ",".join(
            sorted(
                scenario
                for scenario, groups in assignments.items()
                if bool(groups["case"].loc[index])
            )
        )
        control_ids.at[index] = ",".join(
            sorted(
                scenario
                for scenario, groups in assignments.items()
                if bool(groups["control"].loc[index])
            )
        )
    output["scenario_assignment_version"] = PRICE_SCENARIO_ASSIGNMENT_VERSION
    output["scenario_threshold_version"] = str(document["threshold_version"])
    output["scenario_assignment_status"] = scenario_complete.map(
        {True: "complete", False: "limited"}
    )
    output["scenario_case_ids"] = case_ids
    output["scenario_control_ids"] = control_ids
    return output


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
                *INDUSTRY_CONTEXT_FIELDS,
                "target_atr_distance_20pct",
                *SCENARIO_IDENTITY_FIELDS,
                "coverage_status",
                "limitation_notes",
            ]
        )
    )
    return pd.DataFrame(columns=columns)


__all__ = [
    "INDUSTRY_CONTEXT_FIELDS",
    "PRICE_ANALYSIS_FORMULA_VERSION",
    "PRICE_SCENARIO_EVENT_FIELDS",
    "PRICE_SCENARIO_REQUIRED_FIELDS",
    "compute_price_analysis_features",
]
