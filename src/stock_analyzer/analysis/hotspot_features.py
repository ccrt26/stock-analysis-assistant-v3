from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd


HOTSPOT_FORMULA_VERSION = "hotspot-v1"


def compute_hotspot_features(
    equity_daily: pd.DataFrame,
    memberships: pd.DataFrame,
    benchmark_daily: pd.DataFrame,
    *,
    as_of: date,
) -> pd.DataFrame:
    required_daily = {"trade_date", "ts_code", "close", "amount"}
    required_members = {"ts_code", "group_code", "valid_from", "valid_to"}
    if not required_daily <= set(equity_daily):
        raise ValueError("equity daily data lacks hotspot fields")
    if not required_members <= set(memberships):
        raise ValueError("membership data lacks effective-date fields")
    daily = equity_daily.copy()
    daily["trade_date"] = pd.to_datetime(daily["trade_date"]).dt.date
    daily = daily[daily["trade_date"] <= as_of]
    if daily.duplicated(["trade_date", "ts_code"]).any():
        raise ValueError("duplicate business fact in equity daily input")
    members = memberships.copy()
    members["valid_from"] = pd.to_datetime(members["valid_from"])
    members["valid_to"] = pd.to_datetime(members["valid_to"], errors="coerce")
    membership_cutoff = pd.Timestamp(as_of)
    members = members[
        (members["valid_from"] <= membership_cutoff)
        & (
            members["valid_to"].isna()
            | (members["valid_to"] >= membership_cutoff)
        )
    ]
    members = members.drop_duplicates(["group_code", "ts_code"])
    dates = sorted(daily["trade_date"].unique())
    if not dates:
        return pd.DataFrame()
    latest = dates[-1]
    benchmark = benchmark_daily.copy()
    benchmark["trade_date"] = pd.to_datetime(benchmark["trade_date"]).dt.date
    benchmark = benchmark[benchmark["trade_date"] <= as_of].sort_values("trade_date")
    benchmark_returns = {
        horizon: _series_return(benchmark["close"], horizon)
        for horizon in (1, 3, 5, 20)
    }
    market_turnover = float(
        pd.to_numeric(
            daily.loc[daily["trade_date"] == latest, "amount"], errors="coerce"
        ).sum()
    )
    rows = []
    for group_code, group_members in members.groupby("group_code"):
        codes = set(group_members["ts_code"].astype(str))
        group = daily[daily["ts_code"].astype(str).isin(codes)]
        pivot = group.pivot(index="trade_date", columns="ts_code", values="close").sort_index()
        latest_amount = float(
            pd.to_numeric(
                group.loc[group["trade_date"] == latest, "amount"], errors="coerce"
            ).sum()
        )
        one_day = _cross_section_returns(pivot, 1)
        row = {
            "group_code": str(group_code),
            "formula_version": HOTSPOT_FORMULA_VERSION,
            "as_of": as_of,
            "member_count": len(codes),
            "observed_members": int(pivot.iloc[-1].notna().sum()) if not pivot.empty else 0,
            "breadth_1d": float((one_day > 0).mean()) if not one_day.empty else np.nan,
            "median_return_1d": float(one_day.median()) if not one_day.empty else np.nan,
            "turnover_share": latest_amount / market_turnover if market_turnover else np.nan,
            "return_dispersion_1d": float(one_day.std(ddof=0)) if not one_day.empty else np.nan,
            "top3_positive_contribution": _top_positive_contribution(one_day),
            "new_high_20d_share": _new_high_share(pivot, 20),
            "new_high_60d_share": _new_high_share(pivot, 60),
            "interpretation_limit": "observable price and turnover only; no trader identity",
        }
        for horizon in (1, 3, 5, 20):
            returns = _cross_section_returns(pivot, horizon)
            group_return = float(returns.median()) if not returns.empty else np.nan
            row[f"median_return_{horizon}d"] = group_return
            row[f"relative_return_{horizon}d"] = (
                group_return - benchmark_returns[horizon]
                if pd.notna(group_return) and pd.notna(benchmark_returns[horizon])
                else np.nan
            )
        rows.append(row)
    return pd.DataFrame(rows).sort_values(
        ["relative_return_5d", "breadth_1d"], ascending=False
    ).reset_index(drop=True)


def _cross_section_returns(pivot: pd.DataFrame, horizon: int) -> pd.Series:
    if len(pivot) <= horizon:
        return pd.Series(dtype=float)
    result = pivot.iloc[-1] / pivot.iloc[-horizon - 1] - 1.0
    return result.replace([np.inf, -np.inf], np.nan).dropna()


def _series_return(series: pd.Series, horizon: int) -> float:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if len(values) <= horizon:
        return np.nan
    return float(values.iloc[-1] / values.iloc[-horizon - 1] - 1.0)


def _new_high_share(pivot: pd.DataFrame, window: int) -> float:
    if pivot.empty:
        return np.nan
    sample = pivot.tail(window)
    latest = sample.iloc[-1]
    valid = latest.notna() & sample.max().notna()
    if not valid.any():
        return np.nan
    return float((latest[valid] >= sample.max()[valid]).mean())


def _top_positive_contribution(returns: pd.Series) -> float:
    positive = returns[returns > 0].sort_values(ascending=False)
    total = float(positive.sum())
    if not total:
        return np.nan
    return float(positive.head(3).sum() / total)


__all__ = ["HOTSPOT_FORMULA_VERSION", "compute_hotspot_features"]
