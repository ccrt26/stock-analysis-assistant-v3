from __future__ import annotations

import pandas as pd
import pytest

from stock_analyzer.evaluation.v3_backtest.outcomes import evaluate_frozen_projects


def _market_prices() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "trade_date": pd.date_range("2026-01-05", periods=5, freq="B"),
            "adj_close": [100.0, 101.0, 102.0, 103.0, 104.0],
        }
    )


def _stock_prices() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "trade_date": pd.to_datetime(
                ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-09"]
            ),
            "ts_code": ["A"] * 4,
            "adj_close": [100.0, 95.0, 100.0, 125.0],
            "adj_high": [101.0, 97.0, 121.0, 126.0],
            "adj_low": [99.0, 94.0, 98.0, 120.0],
        }
    )


def _industry_prices() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "trade_date": pd.date_range("2026-01-05", periods=5, freq="B"),
            "industry": ["I"] * 5,
            "adj_close": [200.0, 201.0, 202.0, 204.0, 206.0],
        }
    )


def _projects() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "project_id": ["P1"],
            "ts_code": ["A"],
            "policy": ["rolling_competition"],
            "layer": ["focus"],
            "cohort": ["complete_mechanism"],
            "industry": ["I"],
            "listing_board": ["main"],
            "discovery_date": [pd.Timestamp("2026-01-05")],
            "action_date": [pd.Timestamp("2026-01-06")],
            "replacement_date": [pd.Timestamp("2026-01-07")],
        }
    )


def test_evaluate_frozen_projects_reveals_three_baselines_and_market_session_path():
    result = evaluate_frozen_projects(
        _stock_prices(),
        _projects(),
        market_prices=_market_prices(),
        industry_prices=_industry_prices(),
        horizons=(2, 3),
    )

    assert set(result["baseline_type"]) == {"discovery", "action", "replacement"}
    discovery = result.query("baseline_type == 'discovery' and horizon == 2").iloc[0]
    assert discovery["baseline_close"] == pytest.approx(100.0)
    assert discovery["first_target_session"] == 2
    assert discovery["first_target_date"] == pd.Timestamp("2026-01-07")
    assert discovery["max_favorable_return"] == pytest.approx(0.21)
    assert discovery["max_adverse_return"] == pytest.approx(-0.06)
    assert discovery["terminal_return"] == pytest.approx(0.0)
    assert bool(discovery["target_before_drawdown_5"]) is False
    assert bool(discovery["target_before_drawdown_10"]) is True
    assert discovery["market_relative_return"] == pytest.approx(-0.02)
    assert discovery["industry_relative_return"] == pytest.approx(-0.01)

    replacement = result.query(
        "baseline_type == 'replacement' and horizon == 2"
    ).iloc[0]
    assert replacement["observed_sessions"] == 2
    assert replacement["quoted_sessions"] == 1
    assert replacement["first_target_session"] == 2
    assert replacement["terminal_return"] == pytest.approx(0.25)


def test_endpoint_without_stock_quote_is_incomplete_and_has_no_terminal_metrics():
    result = evaluate_frozen_projects(
        _stock_prices(),
        _projects(),
        market_prices=_market_prices(),
        industry_prices=_industry_prices(),
        horizons=(3,),
    )

    discovery = result.query("baseline_type == 'discovery'").iloc[0]
    assert discovery["endpoint_date"] == pd.Timestamp("2026-01-08")
    assert bool(discovery["complete_horizon"]) is False
    assert pd.isna(discovery["terminal_return"])
    assert pd.isna(discovery["market_relative_return"])
    assert pd.isna(discovery["industry_relative_return"])


def test_frozen_matched_control_must_share_formation_date_and_listing_board():
    controls = pd.DataFrame(
        {
            "project_id": ["C1"],
            "ts_code": ["A"],
            "cohort": ["matched_market"],
            "listing_board": ["star"],
            "industry": ["I"],
            "discovery_date": [pd.Timestamp("2026-01-05")],
            "eligible": [True],
        }
    )

    with pytest.raises(ValueError, match="same-date and same-board"):
        evaluate_frozen_projects(
            _stock_prices(),
            _projects(),
            controls=controls,
            market_prices=_market_prices(),
            horizons=(2,),
        )


def test_frozen_controls_reject_future_outcome_fields_used_for_membership():
    controls = pd.DataFrame(
        {
            "project_id": ["C1"],
            "ts_code": ["A"],
            "cohort": ["price_baseline"],
            "listing_board": ["main"],
            "industry": ["I"],
            "discovery_date": [pd.Timestamp("2026-01-05")],
            "eligible": [True],
            "target_touched": [True],
        }
    )

    with pytest.raises(ValueError, match="future outcome fields"):
        evaluate_frozen_projects(
            _stock_prices(),
            _projects(),
            controls=controls,
            market_prices=_market_prices(),
            horizons=(2,),
        )


def test_frozen_controls_reject_generic_outcome_named_membership_fields():
    controls = pd.DataFrame(
        {
            "project_id": ["C1"],
            "ts_code": ["A"],
            "cohort": ["all_market"],
            "listing_board": ["main"],
            "industry": ["I"],
            "discovery_date": [pd.Timestamp("2026-01-05")],
            "eligible": [True],
            "outcome_rank": [1],
        }
    )

    with pytest.raises(ValueError, match="future outcome fields"):
        evaluate_frozen_projects(
            _stock_prices(),
            _projects(),
            controls=controls,
            market_prices=_market_prices(),
            horizons=(2,),
        )


def test_transparent_baseline_must_be_part_of_same_frozen_all_market_scope():
    controls = pd.DataFrame(
        {
            "project_id": ["H1"],
            "ts_code": ["A"],
            "cohort": ["hotspot_baseline"],
            "listing_board": ["main"],
            "industry": ["I"],
            "discovery_date": [pd.Timestamp("2026-01-05")],
            "eligible": [True],
        }
    )

    with pytest.raises(ValueError, match="eligible all-market scope"):
        evaluate_frozen_projects(
            _stock_prices(),
            _projects(),
            controls=controls,
            market_prices=_market_prices(),
            horizons=(2,),
        )


@pytest.mark.parametrize("eligible", ["False", float("nan")])
def test_control_eligibility_requires_literal_true_boolean(eligible: object):
    controls = pd.DataFrame(
        {
            "project_id": ["U1"],
            "ts_code": ["A"],
            "cohort": ["all_market"],
            "listing_board": ["main"],
            "industry": ["I"],
            "discovery_date": [pd.Timestamp("2026-01-05")],
            "eligible": [eligible],
        }
    )

    with pytest.raises(ValueError, match="literal boolean true"):
        evaluate_frozen_projects(
            _stock_prices(),
            _projects(),
            controls=controls,
            market_prices=_market_prices(),
            horizons=(2,),
        )
