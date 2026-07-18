from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from stock_analyzer.evaluation.v3_backtest.baselines import (
    freeze_daily_controls,
)


_DAY = date(2026, 2, 11)
_TZ = ZoneInfo("Asia/Shanghai")


def _universe() -> pd.DataFrame:
    rows = []
    for index in range(12):
        rows.append(
            {
                "formation_date": _DAY,
                "security_id": f"S{index:02d}",
                "listing_board": "main",
                "industry": "I1",
                "tradable": True,
                "history_20d_complete": True,
                "return_20d": index / 100,
                "return_5d": 0.01 if index >= 2 else -0.01,
                "amount_20d": float((index + 1) * 10),
                "relative_return_20d": (index - 2) / 100,
                "current_amount_ratio_20d": 1 + index / 10,
            }
        )
    return pd.DataFrame(rows)


def _routes() -> pd.DataFrame:
    available = datetime(2026, 2, 11, 18, tzinfo=_TZ)
    return pd.DataFrame(
        [
            {
                "formation_date": _DAY,
                "security_id": "S01",
                "route": "hotspot",
                "usable_for_decision": False,
                "relative_return_20d": 0.08,
                "breadth_20d": 0.65,
                "median_return_20d": 0.03,
                "turnover_share_average_20d": 0.02,
            },
            {
                "formation_date": _DAY,
                "security_id": "S02",
                "route": "hotspot",
                "usable_for_decision": False,
                "relative_return_20d": 0.10,
                "breadth_20d": 0.60,
                "median_return_20d": 0.02,
                "turnover_share_average_20d": 0.01,
            },
            {
                "formation_date": _DAY,
                "security_id": "S03",
                "route": "earnings",
                "usable_for_decision": True,
                "available_at": available,
                "tr_yoy": 20.0,
                "netprofit_yoy": 30.0,
                "dt_netprofit_yoy": None,
                "ocf_yoy": -40.0,
            },
            {
                "formation_date": _DAY,
                "security_id": "S04",
                "route": "earnings",
                "usable_for_decision": True,
                "available_at": available.replace(hour=19),
                "tr_yoy": None,
                "netprofit_yoy": None,
                "dt_netprofit_yoy": None,
                "ocf_yoy": None,
            },
        ]
    )


def _candidates() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "formation_date": [_DAY, _DAY],
            "project_id": ["P11", "P08"],
            "security_id": ["S11", "S08"],
        }
    )


def test_freezes_price_roles_liquidity_and_all_five_control_cohorts():
    receipt = freeze_daily_controls(_universe(), _routes(), _candidates())
    controls = receipt.memberships

    assert set(controls["cohort"]) == {
        "all_market",
        "matched_market",
        "hotspot_baseline",
        "earnings_baseline",
        "price_baseline",
    }
    all_market = controls[controls["cohort"] == "all_market"]
    roles = all_market.set_index("security_id")["price_role"]
    assert roles["S11"] == "strong_leader"
    assert roles["S08"] == "balanced_start"
    assert roles["S00"] == "other_tradable"
    assert all_market["liquidity_quintile"].between(1, 5).all()

    hotspot = controls[controls["cohort"] == "hotspot_baseline"]
    assert hotspot["security_id"].tolist() == ["S02", "S01"]
    earnings = controls[controls["cohort"] == "earnings_baseline"]
    assert earnings["security_id"].tolist() == ["S04", "S03"]
    assert earnings.set_index("security_id").loc["S03", "operating_change_magnitude"] == 40.0
    assert pd.isna(
        earnings.set_index("security_id").loc["S04", "operating_change_magnitude"]
    )
    price = controls[controls["cohort"] == "price_baseline"]
    assert price["relative_return_20d"].ge(0).all()
    assert len(price) == 10


def test_matching_is_same_industry_without_replacement_and_records_shortfall():
    universe = pd.concat(
        [
            _universe(),
            pd.DataFrame(
                [
                    {
                        **_universe().iloc[0].to_dict(),
                        "security_id": "OTHER",
                        "industry": "I2",
                        "return_20d": 0.50,
                        "amount_20d": 999.0,
                    }
                ]
            ),
        ],
        ignore_index=True,
    )

    receipt = freeze_daily_controls(universe, _routes(), _candidates())
    matched = receipt.memberships.query("cohort == 'matched_market'")

    assert len(matched) <= 10
    assert matched["security_id"].is_unique
    assert "OTHER" not in set(matched["security_id"])
    assert not set(matched["security_id"]).intersection({"S11", "S08"})
    assert set(matched["matched_project_id"]) == {"P11", "P08"}
    assert all(item.requested == 5 for item in receipt.matching_audit)
    assert all(item.matched <= 5 for item in receipt.matching_audit)


def test_incomplete_history_is_not_assigned_a_role_or_used_as_match():
    universe = _universe()
    universe.loc[universe["security_id"] == "S10", "history_20d_complete"] = False

    receipt = freeze_daily_controls(universe, _routes(), _candidates())
    all_market = receipt.memberships.query("cohort == 'all_market'")
    row = all_market.set_index("security_id").loc["S10"]

    assert pd.isna(row["price_role"])
    assert pd.isna(row["liquidity_quintile"])
    assert "S10" not in set(
        receipt.memberships.query("cohort == 'matched_market'")["security_id"]
    )


@pytest.mark.parametrize("where", ["universe", "routes", "candidates"])
def test_formation_membership_rejects_future_or_outcome_fields(where: str):
    values = {
        "universe": _universe(),
        "routes": _routes(),
        "candidates": _candidates(),
    }
    values[where]["future_return"] = 0.99

    with pytest.raises(ValueError, match="future or outcome"):
        freeze_daily_controls(
            values["universe"], values["routes"], values["candidates"]
        )


def test_deterministic_membership_hash_is_order_independent():
    first = freeze_daily_controls(_universe(), _routes(), _candidates())
    second = freeze_daily_controls(
        _universe().sample(frac=1, random_state=4),
        _routes().sample(frac=1, random_state=5),
        _candidates().sample(frac=1, random_state=6),
    )

    assert first.receipt_hash == second.receipt_hash
    pd.testing.assert_frame_equal(first.memberships, second.memberships)
