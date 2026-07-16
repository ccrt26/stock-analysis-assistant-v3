from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from stock_analyzer.analysis.hotspot_features import (
    HOTSPOT_FORMULA_VERSION,
    _daily_group_series,
    compute_hotspot_features,
)


ANALYSIS_DATE = date(2026, 7, 10)


def _daily(dates: pd.DatetimeIndex, specs: dict[str, tuple[float, float]]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for code, (start, step) in specs.items():
        for offset, trading_day in enumerate(dates):
            close = start + step * offset
            rows.append(
                {
                    "trade_date": trading_day.date(),
                    "ts_code": code,
                    "open": close - step / 2,
                    "high": close + 0.5,
                    "low": close - 0.5,
                    "close": close,
                    "adj_factor": 1.0,
                    "amount": 100.0,
                }
            )
    return pd.DataFrame(rows)


def _catalog() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"group_type": "industry", "group_code": "L1", "group_name": "一级", "level": "L1", "official_index_code": "IDX1"},
            {"group_type": "industry", "group_code": "L2", "group_name": "二级", "level": "L2", "official_index_code": None},
            {"group_type": "industry", "group_code": "L3", "group_name": "三级", "level": "L3", "official_index_code": None},
            {"group_type": "theme", "group_code": "T1", "group_name": "主题一", "level": "theme", "official_index_code": None},
            {"group_type": "theme", "group_code": "EMPTY", "group_name": "无成分主题", "level": "theme", "official_index_code": None},
        ]
    )


def _members(dates: pd.DatetimeIndex) -> pd.DataFrame:
    start = dates[0].date()
    return pd.DataFrame(
        [
            {"group_type": "industry", "group_code": level, "ts_code": code, "valid_from": start, "valid_to": None}
            for level in ("L1", "L2", "L3")
            for code in ("A.SZ", "B.SZ")
        ]
        + [
            {"group_type": "theme", "group_code": "T1", "ts_code": "A.SZ", "valid_from": start, "valid_to": None},
            {"group_type": "theme", "group_code": "T1", "ts_code": "B.SZ", "valid_from": start, "valid_to": None},
        ]
    )


def _benchmark(dates: pd.DatetimeIndex) -> pd.DataFrame:
    return pd.DataFrame({"trade_date": dates.date, "close": [100.0] * len(dates)})


def _official(dates: pd.DatetimeIndex) -> pd.DataFrame:
    return pd.DataFrame(
        {"trade_date": dates.date, "index_code": ["IDX1"] * len(dates), "close": [100.0] * len(dates)}
    )


def _limits(equity: pd.DataFrame) -> pd.DataFrame:
    return equity[["trade_date", "ts_code", "close"]].assign(
        up_limit=lambda frame: frame["close"] + 10.0,
        down_limit=lambda frame: np.maximum(frame["close"] - 10.0, 0.01),
    )[["trade_date", "ts_code", "up_limit", "down_limit"]]


def _compute(
    equity: pd.DataFrame,
    dates: pd.DatetimeIndex,
    *,
    catalog: pd.DataFrame | None = None,
    members: pd.DataFrame | None = None,
    limits: pd.DataFrame | None = None,
    official: pd.DataFrame | None = None,
    minutes: pd.DataFrame | None = None,
) -> pd.DataFrame:
    return compute_hotspot_features(
        equity,
        _catalog() if catalog is None else catalog,
        _members(dates) if members is None else members,
        _benchmark(dates),
        _limits(equity) if limits is None else limits,
        _official(dates) if official is None else official,
        pd.DataFrame(columns=["trade_date", "ts_code", "minute", "close", "amount"])
        if minutes is None
        else minutes,
        analysis_date=ANALYSIS_DATE,
    )


def test_core_returns_breadth_turnover_new_high_and_identity_are_reproducible() -> None:
    dates = pd.bdate_range(end=ANALYSIS_DATE, periods=61)
    equity = _daily(dates, {"A.SZ": (10.0, 0.2), "B.SZ": (20.0, -0.1), "C.SZ": (30.0, 0.0)})
    result = _compute(equity, dates).set_index("group_code")
    row = result.loc["L1"]

    assert row["formula_version"] == HOTSPOT_FORMULA_VERSION
    assert row["group_type"] == "industry"
    assert row["level"] == "L1"
    assert row["member_count"] == 2
    assert row["observed_member_count"] == 2
    assert row["member_coverage_ratio"] == 1.0
    assert row["coverage_status"] == "complete_with_declared_gaps"
    for horizon in (1, 3, 5, 20):
        assert row[f"equal_weight_return_{horizon}d"] > 0
        assert row[f"median_return_{horizon}d"] == pytest.approx(
            row[f"equal_weight_return_{horizon}d"]
        )
        assert row[f"breadth_{horizon}d"] == pytest.approx(0.5)
        assert row[f"relative_return_{horizon}d"] == pytest.approx(
            row[f"equal_weight_return_{horizon}d"]
        )
        assert row[f"turnover_share_average_{horizon}d"] == pytest.approx(2 / 3)
    assert row["new_high_20d_share"] == pytest.approx(0.5)
    assert row["new_high_60d_share"] == pytest.approx(0.5)
    assert row["return_dispersion_1d"] > 0
    assert row["top3_positive_contribution_1d"] == pytest.approx(1.0)
    assert row["intraday_status"] == "limited"
    assert np.isnan(row["intraday_up_minute_share"])


def test_effective_membership_is_applied_on_each_historical_session() -> None:
    dates = pd.bdate_range(end=ANALYSIS_DATE, periods=6)
    equity = _daily(dates, {"A.SZ": (10.0, 1.0), "B.SZ": (20.0, -1.0), "C.SZ": (30.0, 0.0)})
    split = dates[-3].date()
    members = pd.DataFrame(
        [
            {"group_type": "theme", "group_code": "T1", "ts_code": "A.SZ", "valid_from": dates[0].date(), "valid_to": dates[-4].date()},
            {"group_type": "theme", "group_code": "T1", "ts_code": "B.SZ", "valid_from": split, "valid_to": None},
        ]
    )
    catalog = _catalog().query("group_code == 'T1'").reset_index(drop=True)

    row = _compute(equity, dates, catalog=catalog, members=members).iloc[0]

    # Daily turnover uses the member effective on each day.  No stock was a
    # continuous member for the whole 5-session return window, so that horizon
    # is unavailable instead of backfilling today's B into A's history.
    assert row["member_count"] == 1
    assert np.isnan(row["breadth_5d"])
    assert row["horizon_observed_member_count_5d"] == 0
    assert row["turnover_share_average_5d"] == pytest.approx(1 / 3)
    assert row["turnover_share_change_3d"] == pytest.approx(0.0)


def test_sector_returns_use_adjusted_member_prices() -> None:
    dates = pd.bdate_range(end=ANALYSIS_DATE, periods=2)
    equity = _daily(dates, {"A.SZ": (10.0, -5.0)})
    equity.loc[:, "adj_factor"] = [1.0, 2.0]
    catalog = pd.DataFrame(
        [{"group_type": "theme", "group_code": "T", "group_name": "T", "level": "theme", "official_index_code": None}]
    )
    members = pd.DataFrame(
        [{"group_type": "theme", "group_code": "T", "ts_code": "A.SZ", "valid_from": dates[0].date(), "valid_to": None}]
    )

    row = _compute(equity, dates, catalog=catalog, members=members).iloc[0]

    assert row["equal_weight_return_1d"] == pytest.approx(0.0)
    assert row["relative_return_1d"] == pytest.approx(0.0)
    assert row["equity_return_price_basis"] == "close_times_adj_factor"


def test_horizon_median_and_breadth_use_each_stocks_endpoint_return() -> None:
    dates = pd.bdate_range(end=ANALYSIS_DATE, periods=4)
    equity = _daily(dates, {"A.SZ": (100.0, 0.0), "B.SZ": (100.0, 0.0)})
    equity.loc[equity["ts_code"] == "A.SZ", "close"] = [100.0, 100.0, 200.0, 100.0]
    equity.loc[equity["ts_code"] == "B.SZ", "close"] = [100.0, 100.0, 50.0, 100.0]
    catalog = _catalog().query("group_code == 'T1'").reset_index(drop=True)
    members = _members(dates).query("group_code == 'T1'").reset_index(drop=True)

    row = _compute(equity, dates, catalog=catalog, members=members).iloc[0]

    assert row["equal_weight_return_3d"] == pytest.approx(0.0)
    assert row["median_return_3d"] == pytest.approx(0.0)
    assert row["breadth_3d"] == pytest.approx(0.0)


def test_catalog_keeps_no_member_themes_and_partial_coverage_is_not_comparable() -> None:
    dates = pd.bdate_range(end=ANALYSIS_DATE, periods=21)
    equity = _daily(dates, {"A.SZ": (10.0, 0.1), "B.SZ": (20.0, 0.1)})
    current_mask = (equity["trade_date"] == ANALYSIS_DATE) & (equity["ts_code"] == "B.SZ")
    equity.loc[current_mask, "amount"] = np.nan
    result = _compute(equity, dates).set_index("group_code")

    assert result.loc["EMPTY", "coverage_status"] == "limited_no_membership"
    assert result.loc["EMPTY", "member_count"] == 0
    assert np.isnan(result.loc["EMPTY", "equal_weight_return_1d"])
    assert result.loc["L1", "member_coverage_ratio"] == pytest.approx(0.5)
    assert result.loc["L1", "coverage_status"] == "limited"
    assert "80%" in result.loc["L1", "limitation_notes"]


def test_actual_limits_official_index_and_observable_crowding_flags() -> None:
    dates = pd.bdate_range(end=ANALYSIS_DATE, periods=21)
    equity = _daily(dates, {"A.SZ": (10.0, 0.0), "B.SZ": (10.0, 0.0), "C.SZ": (10.0, 0.0)})
    today = equity["trade_date"] == ANALYSIS_DATE
    equity.loc[today & (equity["ts_code"] == "A.SZ"), ["open", "high", "low", "close", "amount"]] = [10.0, 12.0, 9.9, 10.1, 1000.0]
    equity.loc[today & (equity["ts_code"] == "B.SZ"), ["open", "high", "low", "close", "amount"]] = [10.0, 10.2, 9.9, 10.0, 1000.0]
    limits = _limits(equity)
    limits.loc[today & (limits["ts_code"] == "A.SZ"), "up_limit"] = 10.1
    official = pd.DataFrame(
        {
            "trade_date": dates.date,
            "index_code": ["IDX1"] * len(dates),
            "close": np.linspace(100.0, 110.0, len(dates)),
        }
    )
    row = _compute(equity, dates, limits=limits, official=official).set_index("group_code").loc["L1"]

    assert row["limit_up_count"] == 1
    assert row["limit_up_share"] == pytest.approx(0.5)
    assert row["official_index_return_20d"] == pytest.approx(0.10)
    assert row["official_bottom_up_discrepancy_20d"] == pytest.approx(
        row["official_index_return_20d"] - row["equal_weight_return_20d"]
    )
    assert bool(row["high_volume_low_progress_flag"])
    assert bool(row["upper_wick_reversal_flag"])
    assert isinstance(row["narrow_participation_flag"], (bool, np.bool_))
    assert isinstance(row["turnover_return_divergence_flag"], (bool, np.bool_))


def test_four_equal_advancers_are_broad_participation_not_narrow() -> None:
    dates = pd.bdate_range(end=ANALYSIS_DATE, periods=21)
    codes = ["A.SZ", "B.SZ", "C.SZ", "D.SZ"]
    equity = _daily(dates, {code: (10.0, 0.1) for code in codes})
    catalog = pd.DataFrame([
        {"group_type": "theme", "group_code": "T1", "group_name": "主题一", "level": "theme", "official_index_code": None}
    ])
    members = pd.DataFrame([
        {"group_type": "theme", "group_code": "T1", "ts_code": code, "valid_from": dates[0].date(), "valid_to": None}
        for code in codes
    ])

    row = _compute(equity, dates, catalog=catalog, members=members).iloc[0]

    assert row["breadth_1d"] == pytest.approx(1.0)
    assert row["top3_positive_contribution_1d"] == pytest.approx(0.75)
    assert not bool(row["narrow_participation_flag"])


def test_historical_and_new_high_coverage_cannot_be_carried_by_one_stock() -> None:
    dates = pd.bdate_range(end=ANALYSIS_DATE, periods=61)
    equity = _daily(dates, {"A.SZ": (10.0, 0.1)})
    for code in ("B.SZ", "C.SZ", "D.SZ", "E.SZ"):
        equity = pd.concat(
            [equity, _daily(pd.DatetimeIndex([dates[-1]]), {code: (10.0, 0.0)})],
            ignore_index=True,
        )
    catalog = pd.DataFrame([
        {"group_type": "theme", "group_code": "T1", "group_name": "主题一", "level": "theme", "official_index_code": None}
    ])
    members = pd.DataFrame([
        {"group_type": "theme", "group_code": "T1", "ts_code": code, "valid_from": dates[0].date(), "valid_to": None}
        for code in ("A.SZ", "B.SZ", "C.SZ", "D.SZ", "E.SZ")
    ])

    row = _compute(equity, dates, catalog=catalog, members=members).iloc[0]

    assert row["horizon_observed_member_count_20d"] == 1
    assert row["horizon_member_coverage_ratio_20d"] == pytest.approx(0.2)
    assert np.isnan(row["equal_weight_return_20d"])
    assert row["new_high_observed_member_count_20d"] == 1
    assert row["new_high_member_coverage_ratio_20d"] == pytest.approx(0.2)
    assert np.isnan(row["new_high_20d_share"])
    assert row["coverage_status"] == "limited"


def test_limit_share_uses_observed_denominator_and_missing_flags_are_unknown() -> None:
    dates = pd.bdate_range(end=ANALYSIS_DATE, periods=5)
    codes = ["A.SZ", "B.SZ", "C.SZ", "D.SZ", "E.SZ"]
    equity = _daily(dates, {code: (10.0, 0.0) for code in codes})
    catalog = pd.DataFrame([
        {"group_type": "theme", "group_code": "T1", "group_name": "主题一", "level": "theme", "official_index_code": None}
    ])
    members = pd.DataFrame([
        {"group_type": "theme", "group_code": "T1", "ts_code": code, "valid_from": dates[0].date(), "valid_to": None}
        for code in codes
    ])
    limits = _limits(equity)
    limits = limits[~((limits["trade_date"] == ANALYSIS_DATE) & (limits["ts_code"] == "E.SZ"))]
    limits.loc[(limits["trade_date"] == ANALYSIS_DATE) & (limits["ts_code"] == "A.SZ"), "up_limit"] = 10.0

    row = _compute(equity, dates, catalog=catalog, members=members, limits=limits).iloc[0]

    assert row["limit_coverage_ratio"] == pytest.approx(0.8)
    assert row["limit_up_count"] == 1
    assert row["limit_up_share"] == pytest.approx(0.25)
    assert pd.isna(row["high_volume_low_progress_flag"])
    assert pd.isna(row["turnover_return_divergence_flag"])


def test_minute_path_is_optional_and_never_fabricated() -> None:
    dates = pd.bdate_range(end=ANALYSIS_DATE, periods=61)
    equity = _daily(dates, {"A.SZ": (10.0, 0.1), "B.SZ": (20.0, 0.1)})
    minute_values = np.linspace(10.0, 12.0, 240)
    minute_values[120] = minute_values[119] - 0.2
    local_minutes = pd.DatetimeIndex(
        list(pd.date_range("2026-07-10 09:31", "2026-07-10 11:30", freq="min", tz="Asia/Shanghai"))
        + list(pd.date_range("2026-07-10 13:01", "2026-07-10 15:00", freq="min", tz="Asia/Shanghai"))
    ).tz_convert("UTC")
    minutes = pd.DataFrame(
        [
            {"trade_date": ANALYSIS_DATE, "ts_code": code, "minute": local_minutes[i], "close": value, "amount": 10.0}
            for code in ("A.SZ", "B.SZ")
            for i, value in enumerate(minute_values)
        ]
    )
    row = _compute(equity, dates, minutes=minutes).set_index("group_code").loc["L1"]

    assert row["intraday_status"] == "complete"
    assert row["intraday_time_coverage_ratio"] == pytest.approx(1.0)
    assert row["intraday_up_minute_share"] > 0.95
    assert row["intraday_max_drawdown"] < 0
    assert row["intraday_high_to_close_pullback"] == pytest.approx(0.0)
    assert row["coverage_status"] == "complete"

    two_points = minutes[minutes["minute"].isin([local_minutes[0], local_minutes[-1]])]
    limited = _compute(equity, dates, minutes=two_points).set_index("group_code").loc["L1"]
    assert limited["intraday_status"] == "limited"
    assert limited["intraday_time_coverage_ratio"] < 0.95
    assert np.isnan(limited["intraday_open_phase_contribution"])


def test_minute_member_threshold_uses_only_members_with_valid_full_paths() -> None:
    dates = pd.bdate_range(end=ANALYSIS_DATE, periods=61)
    codes = ["A.SZ", "B.SZ", "C.SZ", "D.SZ", "E.SZ"]
    equity = _daily(dates, {code: (10.0, 0.1) for code in codes})
    catalog = pd.DataFrame([
        {"group_type": "theme", "group_code": "T1", "group_name": "主题一", "level": "theme", "official_index_code": None}
    ])
    members = pd.DataFrame([
        {"group_type": "theme", "group_code": "T1", "ts_code": code, "valid_from": dates[0].date(), "valid_to": None}
        for code in codes
    ])
    full = pd.DataFrame([
        {"trade_date": ANALYSIS_DATE, "ts_code": code, "minute": f"m{i:03d}", "close": 10 + i / 1000, "amount": 1.0}
        for code in codes[:4]
        for i in range(240)
    ])

    complete = _compute(
        equity, dates, catalog=catalog, members=members, minutes=full
    ).iloc[0]
    assert complete["intraday_status"] == "complete"
    assert complete["intraday_member_coverage_ratio"] == pytest.approx(0.8)

    no_close_anchor = pd.DataFrame([
        {"trade_date": ANALYSIS_DATE, "ts_code": code, "minute": f"m{i:03d}", "close": 10 + i / 1000, "amount": 1.0}
        for code in codes
        for i in range(228)
    ])
    missing_close = _compute(
        equity, dates, catalog=catalog, members=members, minutes=no_close_anchor
    ).iloc[0]
    assert missing_close["intraday_status"] == "limited"
    assert np.isnan(missing_close["intraday_up_minute_share"])

    invalid_open = full.copy()
    invalid_open.loc[invalid_open["minute"] == "m000", "close"] = 0.0
    invalid = _compute(
        equity, dates, catalog=catalog, members=members, minutes=invalid_open
    ).iloc[0]
    assert invalid["intraday_status"] == "limited"
    assert np.isnan(invalid["intraday_max_drawdown"])


def test_duplicate_facts_fail_and_output_contains_no_hidden_score_or_trader_claim() -> None:
    dates = pd.bdate_range(end=ANALYSIS_DATE, periods=3)
    equity = _daily(dates, {"A.SZ": (10.0, 0.1), "B.SZ": (20.0, 0.1)})
    duplicate = pd.concat([equity, equity.iloc[[-1]]], ignore_index=True)
    with pytest.raises(ValueError, match="duplicate business fact"):
        _compute(duplicate, dates)

    result = _compute(equity, dates)
    rendered = " ".join(map(str, result.columns)).lower()
    for prohibited in (
        "institution",
        "main_force",
        "accumulation",
        "distribution",
        "manipulation",
        "score",
        "ranking",
        "recommend",
        "机构",
        "主力",
        "吸筹",
        "出货",
    ):
        assert prohibited not in rendered


def test_missing_official_index_is_declared_and_overlapping_membership_fails() -> None:
    dates = pd.bdate_range(end=ANALYSIS_DATE, periods=61)
    equity = _daily(dates, {"A.SZ": (10.0, 0.1), "B.SZ": (20.0, 0.1)})
    empty_official = pd.DataFrame(columns=["trade_date", "index_code", "close"])
    row = _compute(equity, dates, official=empty_official).set_index("group_code").loc["L1"]
    assert row["official_index_status"] == "limited"
    assert row["coverage_status"] == "limited"
    assert "official index" in row["limitation_notes"]

    members = _members(dates)
    overlap = members.iloc[[0]].copy()
    overlap["valid_from"] = dates[1].date()
    members = pd.concat([members, overlap], ignore_index=True)
    with pytest.raises(ValueError, match="overlapping"):
        _compute(equity, dates, members=members)


def test_daily_turnover_uses_preindexed_sessions_without_rescanning_full_market() -> None:
    dates = pd.bdate_range(end=ANALYSIS_DATE, periods=3)
    members = pd.DataFrame(
        [
            {
                "group_type": "theme",
                "group_code": "T1",
                "ts_code": code,
                "valid_from": dates[0].date(),
                "valid_to": None,
            }
            for code in ("A.SZ", "B.SZ")
        ]
    )
    indexed = {
        trading_day.date(): pd.DataFrame(
            {
                "ts_code": ["A.SZ", "B.SZ", "OTHER.SZ"],
                "amount": [100.0, 200.0, 700.0],
            }
        ).set_index("ts_code", drop=False)
        for trading_day in dates
    }
    sessions = pd.Index(dates.date, name="trade_date")
    market_amount = pd.Series(1000.0, index=sessions)

    result = _daily_group_series(members, indexed, market_amount, sessions)

    assert result["group_amount"].tolist() == [300.0, 300.0, 300.0]
    assert result["turnover_share"].tolist() == pytest.approx([0.3, 0.3, 0.3])
