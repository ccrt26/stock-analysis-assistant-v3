from datetime import date, timedelta

import pandas as pd

from stock_analyzer.selection_lab.labels import build_future_labels


def _prices(close_returns=None, *, factors=None, action_overrides=None):
    sessions = [date(2026, 1, 1) + timedelta(days=i) for i in range(22)]
    close_returns = close_returns or {}
    factors = factors or {}
    rows = []
    for index, trade_date in enumerate(sessions):
        factor = factors.get(index, 1.0)
        raw_close = (100.0 * (1 + close_returns.get(index, 0.0))) / factor
        row = {
            "trade_date": trade_date,
            "open": 100.0 / factor,
            "high": raw_close,
            "low": min(100.0 / factor, raw_close),
            "close": raw_close,
            "adj_factor": factor,
            "suspended": False,
            "reliable_quote": True,
            "one_price_limit": False,
        }
        if index == 1 and action_overrides:
            row.update(action_overrides)
        rows.append(row)
    return pd.DataFrame(rows), sessions


def test_third_action_day_close_hit_returns_first_hit_day_three():
    prices, sessions = _prices({3: 0.20})

    labels = build_future_labels(prices, sessions, date(2026, 1, 1))

    assert labels.hit_20pct_close_within_20d is True
    assert labels.first_hit_day == 3


def test_day_twenty_one_hit_is_not_a_hit():
    prices, sessions = _prices({21: 0.25})

    labels = build_future_labels(prices, sessions, date(2026, 1, 1))

    assert labels.hit_20pct_close_within_20d is False
    assert labels.first_hit_day is None


def test_intraday_high_without_close_hit_is_false():
    prices, sessions = _prices()
    prices.loc[3, "high"] = 125.0

    labels = build_future_labels(prices, sessions, date(2026, 1, 1))

    assert labels.hit_20pct_close_within_20d is False


def test_adjusted_prices_use_one_consistent_factor_basis():
    prices, sessions = _prices({3: 0.20}, factors={3: 2.0})

    labels = build_future_labels(prices, sessions, date(2026, 1, 1))

    assert labels.hit_20pct_close_within_20d is True
    assert labels.max_close_return_20d == 0.20


def test_one_price_limit_on_action_day_is_non_executable_and_not_replaced():
    prices, sessions = _prices({2: 0.30}, action_overrides={"one_price_limit": True})

    labels = build_future_labels(prices, sessions, date(2026, 1, 1))

    assert labels.executable_on_action_date is False
    assert labels.hit_20pct_close_within_20d is False


def test_suspended_or_unreliable_action_day_is_non_executable():
    for overrides in ({"suspended": True}, {"reliable_quote": False}):
        prices, sessions = _prices(action_overrides=overrides)

        labels = build_future_labels(prices, sessions, date(2026, 1, 1))

        assert labels.executable_on_action_date is False


def test_incomplete_twenty_day_window_returns_null_label():
    prices, sessions = _prices()

    labels = build_future_labels(prices.iloc[:10], sessions[:10], date(2026, 1, 1))

    assert labels.executable_on_action_date is True
    assert labels.hit_20pct_close_within_20d is None


def test_path_metrics_preserve_hit_and_terminal_giveback():
    prices, sessions = _prices({2: -0.10, 3: 0.25, 20: 0.05})

    labels = build_future_labels(prices, sessions, date(2026, 1, 1))

    assert labels.first_hit_day == 3
    assert labels.terminal_return_20d == 0.05
    assert labels.max_adverse_move_before_hit_or_end == -0.10
    assert labels.giveback_from_max_close_to_terminal == 0.20
