"""买入决策的纯数值计算：距离、窗口、波幅与价格口径。

只计算明确假设价位之间的算术关系，不选择价位、不输出买卖结论。
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any


def compute_buy_geometry(
    *,
    entry_price: float,
    upside_levels: Mapping[str, float],
    invalidation_price: float | None,
    atr: float | None = None,
    round_trip_cost_bps: float | None = None,
) -> dict[str, Any]:
    """计算明确假设价位之间的距离，不选择价位、不输出买卖结论。

    gross_return_fraction = level / entry - 1；指定双边合计成本基点后，
    approx_net_return_fraction = gross - cost_bps / 10000。这是以买入金额
    为基准的成本近似，不是按券商最低佣金、实际股数和税费精确结算。
    """

    _require_positive_finite(entry_price, "entry_price")
    if atr is not None:
        _require_positive_finite(atr, "atr")
    if round_trip_cost_bps is not None:
        if (
            isinstance(round_trip_cost_bps, bool)
            or not isinstance(round_trip_cost_bps, (int, float))
            or not math.isfinite(float(round_trip_cost_bps))
            or float(round_trip_cost_bps) < 0
        ):
            raise ValueError(
                "round_trip_cost_bps must be a finite non-negative number"
            )
    levels: dict[str, Any] = {}
    for level_id, level_price in upside_levels.items():
        if not str(level_id).strip():
            raise ValueError("upside_levels level id must be non-empty")
        _require_positive_finite(level_price, f"upside_levels[{level_id!r}]")
        gross = float(level_price) / float(entry_price) - 1.0
        levels[str(level_id)] = {
            "price": float(level_price),
            "gross_return_fraction": gross,
            "approx_net_return_fraction": (
                None
                if round_trip_cost_bps is None
                else gross - float(round_trip_cost_bps) / 10000.0
            ),
        }
    invalidation: dict[str, Any] | None = None
    if invalidation_price is not None:
        _require_positive_finite(invalidation_price, "invalidation_price")
        invalidation_gross = float(invalidation_price) / float(entry_price) - 1.0
        invalidation = {
            "price": float(invalidation_price),
            "gross_return_fraction": invalidation_gross,
            "approx_net_return_fraction": (
                None
                if round_trip_cost_bps is None
                else invalidation_gross - float(round_trip_cost_bps) / 10000.0
            ),
            "distance_in_atr": (
                None
                if atr is None
                else (float(entry_price) - float(invalidation_price)) / float(atr)
            ),
            "below_entry": float(invalidation_price) < float(entry_price),
        }
    return {
        "entry_price": float(entry_price),
        "levels": levels,
        "invalidation": invalidation,
        "round_trip_cost_bps": (
            None if round_trip_cost_bps is None else float(round_trip_cost_bps)
        ),
    }


def holding_window_end(
    *,
    entry_session: date,
    horizon_sessions: int,
    trading_sessions: Sequence[date],
) -> date:
    """买入交易日计为第一天；交易日历不足或起点非交易日则明确报错。"""

    if horizon_sessions < 1:
        raise ValueError("horizon_sessions must be a positive integer")
    sessions = list(trading_sessions)
    try:
        entry_index = sessions.index(entry_session)
    except ValueError:
        raise ValueError(
            f"entry session {entry_session.isoformat()} is not in the "
            "trading session list"
        ) from None
    end_index = entry_index + int(horizon_sessions) - 1
    if end_index >= len(sessions):
        raise ValueError(
            f"trading sessions are insufficient: need {int(horizon_sessions)} "
            f"sessions from {entry_session.isoformat()}, "
            f"only {len(sessions) - entry_index} available"
        )
    return sessions[end_index]


def atr20_from_sessions(rows: Sequence[Mapping[str, Any]]) -> float | None:
    """20 个会话真实波幅的简单平均；需 21 行（首行提供前收盘）。

    与 forward_monitor 复盘价格上下文、stock_context_features 的 ATR
    同一定义：TR = max(high-low, |high-前收|, |low-前收|)。
    """

    if len(rows) < 21:
        return None
    true_ranges: list[float] = []
    for index in range(1, len(rows)):
        row = rows[index]
        previous_close = rows[index - 1].get("close")
        high = row.get("high")
        low = row.get("low")
        if any(
            value is None or not math.isfinite(float(value))
            for value in (high, low, previous_close)
        ):
            return None
        high_f = float(high)
        low_f = float(low)
        previous_f = float(previous_close)
        true_ranges.append(
            max(
                high_f - low_f,
                abs(high_f - previous_f),
                abs(low_f - previous_f),
            )
        )
    sample = true_ranges[-20:]
    if len(sample) != 20:
        return None
    return sum(sample) / len(sample)


def normalize_price_history(
    rows: Sequence[Mapping[str, Any]],
    *,
    normalization_factor: float | None,
) -> list[dict[str, Any]]:
    """把原始价统一到「原始价 × 当日复权因子 ÷ 基准日因子」口径。

    与 forward_monitor 的 _adjusted_path / _analysis_day_factor 同一口径。
    基准日因子缺失或非正时不输出价格序列（调用方记为口径缺口），
    不退回未复权的原始价。
    """

    if normalization_factor is None or float(normalization_factor) <= 0:
        return []
    factor = float(normalization_factor)
    normalized: list[dict[str, Any]] = []
    for row in rows:
        row_factor = row.get("factor")
        if row_factor is None or float(row_factor) <= 0:
            continue
        scale = float(row_factor) / factor
        entry: dict[str, Any] = {"date": row.get("date")}
        for name in ("open", "high", "low", "close"):
            value = row.get(name)
            entry[name] = None if value is None else float(value) * scale
        entry["amount"] = row.get("amount")
        entry["raw_close"] = row.get("close")
        entry["factor"] = float(row_factor)
        normalized.append(entry)
    return normalized


def _require_positive_finite(value: Any, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite positive number")
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{label} must be a finite positive number")


__all__ = [
    "atr20_from_sessions",
    "compute_buy_geometry",
    "holding_window_end",
    "normalize_price_history",
]
