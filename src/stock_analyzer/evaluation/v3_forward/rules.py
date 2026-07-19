from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from stock_analyzer.evaluation.v3_selection_accuracy_pareto import (
    baseline_action_mask,
)


RULE_VERSION = "v3-forward-baseline-01"
TARGET_RETURN = 0.20
OBSERVATION_WINDOWS = (5, 10, 20, 30)
CANDIDATE_CAP = 10
FOCUS_CAP = 5
ROUTE_RECALL_CAP = 30
SUPPORTED_ROUTES = ("hotspot", "earnings", "price")

FUTURE_FIELDS = frozenset(
    {
        "entry_date",
        "entry_status",
        "executable_entry",
        "raw_entry_open",
        "action_price",
        "target_price",
        "formation_to_entry_gap",
        "complete_horizon",
        "observed_market_sessions",
        "target_touched",
        "close_confirmed",
        "mechanical_target_touched",
        "mechanical_close_confirmed",
        "first_touch_session",
        "first_touch_date",
        "first_close_confirm_session",
        "first_close_confirm_date",
        "retain_1",
        "retain_3",
        "retain_5",
        "window_min_return",
        "pre_touch_min_return",
        "terminal_return",
        "max_drawdown",
    }
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rule_manifest() -> dict[str, Any]:
    evaluation_root = Path(__file__).resolve().parents[1]
    source_paths = {
        "forward_rules": Path(__file__).resolve(),
        "formation": evaluation_root / "v3_layered_validation.py",
        "compression": evaluation_root / "v3_compression_revalidation.py",
        "action_confirmation": evaluation_root / "v3_selection_accuracy_pareto.py",
        "entry_semantics": evaluation_root / "v3_next_day_entry_validation.py",
    }
    return {
        "rule_version": RULE_VERSION,
        "supported_routes": list(SUPPORTED_ROUTES),
        "candidate_cap": CANDIDATE_CAP,
        "focus_cap": FOCUS_CAP,
        "route_recall_cap": ROUTE_RECALL_CAP,
        "action_confirmations": [
            "return_5d > 0",
            "relative_return_20d > 0",
            "current_amount_ratio_20d >= 1",
        ],
        "target_return": TARGET_RETURN,
        "observation_windows": list(OBSERVATION_WINDOWS),
        "entry_day_counts_as_session_one": True,
        "source_sha256": {
            name: _sha256_file(path) for name, path in sorted(source_paths.items())
        },
    }


def rule_manifest_hash() -> str:
    encoded = json.dumps(
        rule_manifest(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def reject_future_fields(frame: pd.DataFrame) -> None:
    forbidden = sorted(set(frame.columns) & FUTURE_FIELDS)
    if forbidden:
        raise ValueError(f"formation contains future field(s): {', '.join(forbidden)}")


def add_action_confirmations(frame: pd.DataFrame) -> pd.DataFrame:
    required = {
        "user_layer",
        "hard_invalid",
        "return_5d",
        "relative_return_20d",
        "current_amount_ratio_20d",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"action confirmation lacks fields: {', '.join(missing)}")
    result = frame.copy()
    result["confirm_return_5d_positive"] = pd.to_numeric(
        result["return_5d"], errors="coerce"
    ).gt(0)
    result["confirm_relative_return_20d_positive"] = pd.to_numeric(
        result["relative_return_20d"], errors="coerce"
    ).gt(0)
    result["confirm_amount_ratio_20d"] = pd.to_numeric(
        result["current_amount_ratio_20d"], errors="coerce"
    ).ge(1)
    result["action_confirmed"] = baseline_action_mask(result).astype(bool)
    return result


def _finite(value: Any) -> bool:
    try:
        return bool(np.isfinite(float(value)))
    except (TypeError, ValueError):
        return False


def _is_close(left: Any, right: Any) -> bool:
    return bool(
        _finite(left)
        and _finite(right)
        and np.isclose(float(left), float(right), rtol=1e-6, atol=1e-8)
    )


def classify_entry(quote: pd.Series | Mapping[str, Any]) -> dict[str, Any]:
    values = quote if isinstance(quote, Mapping) else quote.to_dict()
    raw_open = values.get("open")
    quote_valid = _finite(raw_open) and float(raw_open) > 0
    open_at_limit = quote_valid and _is_close(raw_open, values.get("up_limit"))
    one_price_limit_up = bool(
        open_at_limit
        and _is_close(values.get("high"), values.get("up_limit"))
        and _is_close(values.get("low"), values.get("up_limit"))
    )
    if not quote_valid:
        status = "no_quote_or_suspended"
    elif one_price_limit_up:
        status = "one_price_limit_up"
    elif open_at_limit:
        status = "open_at_limit_not_one_price"
    else:
        status = "executable_entry"
    return {
        "entry_status": status,
        "executable_entry": bool(quote_valid and not one_price_limit_up),
        "raw_entry_open": float(raw_open) if quote_valid else None,
    }


def compute_window_snapshot(
    prices: pd.DataFrame,
    entry: Mapping[str, Any],
    *,
    horizon: int,
) -> dict[str, Any]:
    if horizon not in OBSERVATION_WINDOWS:
        raise ValueError(f"unsupported observation horizon: {horizon}")
    if len(prices) < horizon:
        raise ValueError(f"window is not mature: {len(prices)}/{horizon}")
    action_price = float(entry["action_price"])
    if not np.isfinite(action_price) or action_price <= 0:
        raise ValueError("action_price must be a positive finite number")
    window = prices.iloc[:horizon].copy()
    required = {"trade_date", "high", "low", "close", "adj_factor"}
    missing = sorted(required - set(window.columns))
    if missing:
        raise ValueError(f"window prices lack fields: {', '.join(missing)}")
    window["trade_date"] = pd.to_datetime(window["trade_date"], errors="raise").dt.normalize()
    expected_entry = pd.Timestamp(entry["entry_date"]).normalize()
    if window.iloc[0]["trade_date"] != expected_entry:
        raise ValueError("window does not start on the entry date")
    for field in ("high", "low", "close", "adj_factor"):
        window[field] = pd.to_numeric(window[field], errors="coerce")
    window["adj_high"] = window["high"] * window["adj_factor"]
    window["adj_low"] = window["low"] * window["adj_factor"]
    window["adj_close"] = window["close"] * window["adj_factor"]
    target_price = action_price * (1.0 + TARGET_RETURN)
    touch_positions = np.flatnonzero(window["adj_high"].ge(target_price).fillna(False).to_numpy())
    close_positions = np.flatnonzero(window["adj_close"].ge(target_price).fillna(False).to_numpy())
    first_touch = int(touch_positions[0]) if len(touch_positions) else None
    first_close = int(close_positions[0]) if len(close_positions) else None
    post = (
        window.iloc[first_close + 1 : first_close + 4]
        if first_close is not None
        else window.iloc[0:0]
    )
    retain_observable = bool(
        first_close is not None
        and len(post) == 3
        and post["adj_close"].notna().all()
    )
    retain_3 = bool(post["adj_close"].ge(target_price).all()) if retain_observable else None
    lows = window["adj_low"].dropna()
    window_min_return = (
        float(lows.min() / action_price - 1.0) if not lows.empty else None
    )
    close_path = pd.Series(
        [action_price, *window["adj_close"].dropna().astype(float).tolist()],
        dtype=float,
    )
    running_peak = close_path.cummax()
    max_drawdown = float((close_path / running_peak - 1.0).min())
    return {
        "horizon": horizon,
        "complete_horizon": True,
        "observed_market_sessions": horizon,
        "quoted_stock_sessions": int(window["adj_close"].notna().sum()),
        "target_touched": bool(first_touch is not None),
        "close_confirmed": bool(first_close is not None),
        "first_touch_session": first_touch + 1 if first_touch is not None else None,
        "first_touch_date": (
            window.iloc[first_touch]["trade_date"].date().isoformat()
            if first_touch is not None
            else None
        ),
        "first_close_confirm_session": first_close + 1 if first_close is not None else None,
        "first_close_confirm_date": (
            window.iloc[first_close]["trade_date"].date().isoformat()
            if first_close is not None
            else None
        ),
        "retain_3_observable": retain_observable,
        "retain_3": retain_3,
        "window_min_return": window_min_return,
        "max_drawdown": max_drawdown,
        "as_of_date": window.iloc[-1]["trade_date"].date().isoformat(),
    }


__all__ = [
    "CANDIDATE_CAP",
    "OBSERVATION_WINDOWS",
    "RULE_VERSION",
    "SUPPORTED_ROUTES",
    "TARGET_RETURN",
    "add_action_confirmations",
    "classify_entry",
    "compute_window_snapshot",
    "reject_future_fields",
    "rule_manifest",
    "rule_manifest_hash",
]
