from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from stock_analyzer.analysis.price_scenario_validation import (
    SCENARIO_THRESHOLD_FIELDS,
)


ANALYSIS_DATE = date(2026, 8, 19)


def _facts(*, periods: int = 260) -> tuple[pd.DataFrame, pd.DataFrame]:
    dates = pd.bdate_range(end=ANALYSIS_DATE, periods=periods)
    closes = 20.0 + np.arange(periods, dtype=float) * 0.08
    equity = pd.DataFrame(
        {
            "trade_date": dates.date,
            "ts_code": "000001.SZ",
            "open": closes - 0.03,
            "high": closes + 0.12,
            "low": closes - 0.10,
            "close": closes,
            "adj_factor": 1.0,
            "amount": 1_000_000.0 + np.arange(periods) * 10_000.0,
            "up_limit": closes * 1.10,
        }
    )
    benchmark = pd.DataFrame(
        {
            "trade_date": dates.date,
            "close": 3_000.0 + np.arange(periods, dtype=float) * 2.0,
        }
    )
    return equity, benchmark


def test_daily_price_context_covers_every_declared_scenario_input() -> None:
    from stock_analyzer.analysis.price_analysis_features import (
        PRICE_ANALYSIS_FORMULA_VERSION,
        PRICE_SCENARIO_EVENT_FIELDS,
        compute_price_analysis_features,
    )

    equity, benchmark = _facts()

    result = compute_price_analysis_features(
        equity,
        benchmark,
        analysis_date=ANALYSIS_DATE,
    )

    assert len(result) == 1
    row = result.iloc[0]
    assert set(SCENARIO_THRESHOLD_FIELDS).issubset(result.columns)
    assert set(PRICE_SCENARIO_EVENT_FIELDS).issubset(result.columns)
    assert row["price_analysis_formula_version"] == PRICE_ANALYSIS_FORMULA_VERSION
    assert row["price_indicator_formula_version"] == (
        "price-indicator-conditional-states-v2"
    )
    assert row["coverage_status"] == "complete"
    assert row["scenario_assignment_status"] == "complete"
    assert row["scenario_case_ids"] == ""
    assert row["scenario_control_ids"] == ""
    assert row["scenario_assignment_version"]
    assert row["scenario_threshold_version"] == (
        "price-scenario-thresholds-2026-08-19-v3"
    )
    assert row["target_atr_distance_20pct"] == pytest.approx(
        0.20 / row["atr_ratio_20d"]
    )


def test_price_context_keeps_multiple_scenario_ids_in_stable_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import stock_analyzer.analysis.price_analysis_features as price_features

    equity, benchmark = _facts()

    def multiple_assignments(frame, thresholds):
        del thresholds
        yes = pd.Series(True, index=frame.index)
        no = pd.Series(False, index=frame.index)
        return {
            "trend_continuation": {"case": yes, "control": no},
            "confirmed_breakout": {"case": yes, "control": no},
        }

    monkeypatch.setattr(
        price_features,
        "assign_price_scenarios",
        multiple_assignments,
    )

    result = price_features.compute_price_analysis_features(
        equity,
        benchmark,
        analysis_date=ANALYSIS_DATE,
    )

    assert result.iloc[0]["scenario_case_ids"] == (
        "confirmed_breakout,trend_continuation"
    )


def test_daily_price_context_is_formation_date_safe() -> None:
    from stock_analyzer.analysis.price_analysis_features import (
        compute_price_analysis_features,
    )

    equity, benchmark = _facts()
    expected = compute_price_analysis_features(
        equity,
        benchmark,
        analysis_date=ANALYSIS_DATE,
    )
    future_dates = pd.bdate_range(start="2026-08-20", periods=2)
    future_equity = pd.DataFrame(
        {
            "trade_date": future_dates.date,
            "ts_code": "000001.SZ",
            "open": [1_000.0, 2_000.0],
            "high": [1_100.0, 2_200.0],
            "low": [900.0, 1_800.0],
            "close": [1_050.0, 2_100.0],
            "adj_factor": [1.0, 1.0],
            "amount": [1e10, 2e10],
            "up_limit": [1_100.0, 2_200.0],
        }
    )
    future_benchmark = pd.DataFrame(
        {"trade_date": future_dates.date, "close": [9_000.0, 10_000.0]}
    )

    observed = compute_price_analysis_features(
        pd.concat([equity, future_equity], ignore_index=True),
        pd.concat([benchmark, future_benchmark], ignore_index=True),
        analysis_date=ANALYSIS_DATE,
    )

    pd.testing.assert_frame_equal(observed, expected)


def test_short_history_remains_limited_without_filling_long_anchor() -> None:
    from stock_analyzer.analysis.price_analysis_features import (
        compute_price_analysis_features,
    )

    equity, benchmark = _facts(periods=40)

    row = compute_price_analysis_features(
        equity,
        benchmark,
        analysis_date=ANALYSIS_DATE,
    ).iloc[0]

    assert row["coverage_status"] == "limited"
    assert pd.isna(row["distance_to_prior_250d_high"])
    assert pd.isna(row["breakout_prior_250d_high"])
    assert row["scenario_assignment_status"] == "limited"
    assert row["scenario_case_ids"] == ""
    assert row["scenario_control_ids"] == ""
    assert "short history" in row["limitation_notes"]


def test_price_context_reuses_effective_sw_l2_sector_returns_and_ranks() -> None:
    from stock_analyzer.analysis.price_analysis_features import (
        compute_price_analysis_features,
    )

    equity, benchmark = _industry_facts()
    catalog = pd.DataFrame(
        [
            {
                "industry_system": "SW2021",
                "level": "L2",
                "industry_code": "801012.SI",
                "industry_name": "种植业",
                "valid_from": date(2020, 1, 1),
                "valid_to": None,
            },
            {
                "industry_system": "SW2021",
                "level": "L2",
                "industry_code": "801011.SI",
                "industry_name": "旧农业",
                "valid_from": date(2020, 1, 1),
                "valid_to": date(2026, 1, 1),
            },
        ]
    )
    memberships = pd.DataFrame(
        [
            {
                "industry_system": "SW2021",
                "level": "L2",
                "industry_code": "801012.SI",
                "ts_code": code,
                "valid_from": date(2026, 1, 2),
                "valid_to": None,
            }
            for code in ("000001.SZ", "000002.SZ", "000003.SZ")
        ]
        + [
            {
                "industry_system": "SW2021",
                "level": "L2",
                "industry_code": "801011.SI",
                "ts_code": "000001.SZ",
                "valid_from": date(2020, 1, 1),
                "valid_to": date(2026, 1, 1),
            }
        ]
    )
    sector = _sector_row()

    result = compute_price_analysis_features(
        equity,
        benchmark,
        analysis_date=ANALYSIS_DATE,
        industry_catalog=catalog,
        industry_memberships=memberships,
        sector_hotspot=sector,
    ).set_index("ts_code")

    assert set(result["primary_industry_code"]) == {"801012.SI"}
    assert set(result["primary_industry_name"]) == {"种植业"}
    assert set(result["primary_industry_level"]) == {"L2"}
    assert set(result["industry_comparison_status"]) == {"complete"}
    assert result.loc["000001.SZ", "relative_industry_return_5d"] == pytest.approx(0.05)
    assert result.loc["000002.SZ", "relative_industry_return_5d"] == pytest.approx(0.0)
    assert result.loc["000003.SZ", "relative_industry_return_5d"] == pytest.approx(-0.05)
    assert result.loc["000001.SZ", "industry_return_rank_percentile_5d"] == 1.0
    assert result.loc["000002.SZ", "industry_return_rank_percentile_5d"] == 0.5
    assert result.loc["000003.SZ", "industry_return_rank_percentile_5d"] == 0.0


@pytest.mark.parametrize("case", ["missing", "duplicate", "coverage"])
def test_industry_comparison_is_limited_for_unreliable_membership_or_coverage(
    case: str,
) -> None:
    from stock_analyzer.analysis.price_analysis_features import (
        compute_price_analysis_features,
    )

    equity, benchmark = _industry_facts()
    catalog = pd.DataFrame(
        [
            {
                "industry_system": "SW2021",
                "level": "L2",
                "industry_code": code,
                "industry_name": name,
                "valid_from": date(2020, 1, 1),
                "valid_to": None,
            }
            for code, name in (("801012.SI", "种植业"), ("801013.SI", "养殖业"))
        ]
    )
    codes = ["000002.SZ", "000003.SZ"] if case == "missing" else [
        "000001.SZ",
        "000002.SZ",
        "000003.SZ",
    ]
    memberships = [
        {
            "industry_system": "SW2021",
            "level": "L2",
            "industry_code": "801012.SI",
            "ts_code": code,
            "valid_from": date(2020, 1, 1),
            "valid_to": None,
        }
        for code in codes
    ]
    if case == "duplicate":
        memberships.append(
            {
                "industry_system": "SW2021",
                "level": "L2",
                "industry_code": "801013.SI",
                "ts_code": "000001.SZ",
                "valid_from": date(2020, 1, 1),
                "valid_to": None,
            }
        )
    if case == "coverage":
        memberships.append(
            {
                "industry_system": "SW2021",
                "level": "L2",
                "industry_code": "801012.SI",
                "ts_code": "000004.SZ",
                "valid_from": date(2020, 1, 1),
                "valid_to": None,
            }
        )

    result = compute_price_analysis_features(
        equity,
        benchmark,
        analysis_date=ANALYSIS_DATE,
        industry_catalog=catalog,
        industry_memberships=pd.DataFrame(memberships),
        sector_hotspot=_sector_row(),
    ).set_index("ts_code")

    assert result.loc["000001.SZ", "industry_comparison_status"] == "limited"
    assert pd.isna(result.loc["000001.SZ", "relative_industry_return_5d"])
    assert pd.isna(result.loc["000001.SZ", "industry_return_rank_percentile_5d"])


def _sector_row() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "analysis_date": ANALYSIS_DATE,
                "group_type": "industry",
                "group_code": "801012.SI",
                "level": "L2",
                "coverage_status": "complete_with_declared_gaps",
                "equal_weight_return_1d": 0.01,
                "equal_weight_return_3d": 0.03,
                "equal_weight_return_5d": 0.05,
                "equal_weight_return_20d": 0.05,
            }
        ]
    )


def _industry_facts() -> tuple[pd.DataFrame, pd.DataFrame]:
    dates = pd.bdate_range(end=ANALYSIS_DATE, periods=260)
    paths = {
        "000001.SZ": [10.0, 10.2, 10.4, 10.6, 10.8, 11.0],
        "000002.SZ": [10.0, 10.1, 10.2, 10.3, 10.4, 10.5],
        "000003.SZ": [10.0, 10.0, 10.0, 10.0, 10.0, 10.0],
    }
    rows: list[dict[str, object]] = []
    for code, ending in paths.items():
        closes = np.full(len(dates), 10.0)
        closes[-6:] = ending
        rows.extend(
            {
                "trade_date": day.date(),
                "ts_code": code,
                "open": close - 0.02,
                "high": close + 0.10,
                "low": close - 0.10,
                "close": close,
                "adj_factor": 1.0,
                "amount": 1_000_000.0,
                "up_limit": close * 1.10,
            }
            for day, close in zip(dates, closes, strict=True)
        )
    benchmark = pd.DataFrame(
        {"trade_date": dates.date, "close": np.full(len(dates), 3_000.0)}
    )
    return pd.DataFrame(rows), benchmark
