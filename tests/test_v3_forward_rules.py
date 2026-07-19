from __future__ import annotations

import pandas as pd
import pytest

from stock_analyzer.evaluation.v3_forward.rules import (
    add_action_confirmations,
    classify_entry,
    compute_window_snapshot,
    reject_future_fields,
    rule_manifest,
    rule_manifest_hash,
)
from stock_analyzer.evaluation.v3_selection_accuracy_pareto import (
    baseline_action_mask,
)


def _attention_rows() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "user_layer": ["关注", "关注", "关注"],
            "hard_invalid": [False, False, False],
            "return_5d": [0.01, -0.01, None],
            "relative_return_20d": [0.02, 0.02, 0.02],
            "current_amount_ratio_20d": [1.1, 1.1, 1.1],
        }
    )


def _prices(count: int) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "trade_date": pd.bdate_range("2026-01-06", periods=count),
            "open": [10.0] * count,
            "high": [10.2, 12.1, 12.3, 12.4, 12.5][:count],
            "low": [9.8, 9.9, 11.9, 12.0, 12.1][:count],
            "close": [10.1, 12.0, 12.2, 12.3, 12.4][:count],
            "adj_factor": [1.0] * count,
        }
    )


def test_rule_manifest_is_stable_and_frozen():
    manifest = rule_manifest()

    assert manifest["rule_version"] == "v3-forward-baseline-01"
    assert manifest["candidate_cap"] == 10
    assert manifest["target_return"] == 0.20
    assert manifest["observation_windows"] == [5, 10, 20, 30]
    assert rule_manifest_hash() == rule_manifest_hash()
    assert len(rule_manifest_hash()) == 64


def test_formation_rejects_any_known_future_field():
    with pytest.raises(ValueError, match="future field"):
        reject_future_fields(
            pd.DataFrame({"ts_code": ["000001.SZ"], "action_price": [10.0]})
        )


def test_confirmation_matches_frozen_baseline_and_missing_is_false():
    result = add_action_confirmations(_attention_rows())

    assert result["confirm_return_5d_positive"].tolist() == [True, False, False]
    assert result["confirm_relative_return_20d_positive"].tolist() == [True] * 3
    assert result["confirm_amount_ratio_20d"].tolist() == [True] * 3
    assert result["action_confirmed"].tolist() == [True, False, False]
    assert result["action_confirmed"].equals(baseline_action_mask(result))


@pytest.mark.parametrize(
    ("quote", "status", "executable"),
    [
        ({"open": None, "high": None, "low": None, "up_limit": None}, "no_quote_or_suspended", False),
        ({"open": 11.0, "high": 11.0, "low": 11.0, "up_limit": 11.0}, "one_price_limit_up", False),
        ({"open": 11.0, "high": 11.0, "low": 10.5, "up_limit": 11.0}, "open_at_limit_not_one_price", True),
        ({"open": 10.5, "high": 11.0, "low": 10.0, "up_limit": 11.0}, "executable_entry", True),
    ],
)
def test_entry_classification(quote, status, executable):
    result = classify_entry(pd.Series(quote))

    assert result["entry_status"] == status
    assert result["executable_entry"] is executable


def test_window_requires_exact_market_session_maturity():
    with pytest.raises(ValueError, match="not mature"):
        compute_window_snapshot(
            _prices(4),
            {"action_price": 10.0, "entry_date": "2026-01-06"},
            horizon=5,
        )


def test_window_metrics_use_entry_day_as_session_one_and_close_retention():
    result = compute_window_snapshot(
        _prices(5),
        {"action_price": 10.0, "entry_date": "2026-01-06"},
        horizon=5,
    )

    assert result["observed_market_sessions"] == 5
    assert result["target_touched"] is True
    assert result["first_touch_session"] == 2
    assert result["close_confirmed"] is True
    assert result["first_close_confirm_session"] == 2
    assert result["retain_3_observable"] is True
    assert result["retain_3"] is True
    assert result["window_min_return"] == pytest.approx(-0.02)
    assert result["complete_horizon"] is True
