from datetime import date

import pandas as pd

from stock_analyzer.analysis.hotspot_features import compute_hotspot_features


def test_hotspot_features_use_breadth_relative_return_and_unique_turnover():
    dates = pd.date_range("2026-06-10", periods=21, freq="B")
    rows = []
    for index, value in enumerate(dates):
        rows.extend([
            {"trade_date": value.date(), "ts_code": "A.SZ", "close": 10 + index * 0.2, "amount": 100.0},
            {"trade_date": value.date(), "ts_code": "B.SZ", "close": 20 + index * 0.1, "amount": 200.0},
            {"trade_date": value.date(), "ts_code": "C.SZ", "close": 30 - index * 0.1, "amount": 700.0},
        ])
    members = pd.DataFrame([
        {"ts_code": "A.SZ", "group_code": "HOT", "valid_from": date(2020, 1, 1), "valid_to": None},
        {"ts_code": "B.SZ", "group_code": "HOT", "valid_from": date(2020, 1, 1), "valid_to": None},
        {"ts_code": "C.SZ", "group_code": "COLD", "valid_from": date(2020, 1, 1), "valid_to": None},
    ])
    benchmark = pd.DataFrame([
        {"trade_date": value.date(), "close": 100 + index * 0.05}
        for index, value in enumerate(dates)
    ])

    result = compute_hotspot_features(
        pd.DataFrame(rows), members, benchmark, as_of=dates[-1].date()
    ).set_index("group_code")

    assert result.loc["HOT", "breadth_1d"] == 1.0
    assert result.loc["HOT", "relative_return_20d"] > result.loc["COLD", "relative_return_20d"]
    assert result.loc["HOT", "turnover_share"] == 0.3
    assert "institution" not in " ".join(result.columns).lower()


def test_duplicate_business_fact_is_rejected_before_hotspot_calculation():
    daily = pd.DataFrame([
        {"trade_date": date(2026, 7, 10), "ts_code": "A.SZ", "close": 10.0, "amount": 1.0},
        {"trade_date": date(2026, 7, 10), "ts_code": "A.SZ", "close": 10.0, "amount": 1.0},
    ])
    members = pd.DataFrame([
        {"ts_code": "A.SZ", "group_code": "HOT", "valid_from": date(2020, 1, 1), "valid_to": None}
    ])
    benchmark = pd.DataFrame([{"trade_date": date(2026, 7, 10), "close": 100.0}])
    try:
        compute_hotspot_features(daily, members, benchmark, as_of=date(2026, 7, 10))
    except ValueError as exc:
        assert "duplicate" in str(exc)
    else:
        raise AssertionError("duplicate fact should be rejected")
