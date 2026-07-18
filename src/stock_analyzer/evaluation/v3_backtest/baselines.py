"""Freeze transparent, formation-only controls for the V3 backtest."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd


_COHORT_ORDER = {
    "all_market": 0,
    "matched_market": 1,
    "hotspot_baseline": 2,
    "earnings_baseline": 3,
    "price_baseline": 4,
}
_PRICE_ROLE_ORDER = {
    "other_tradable": 0,
    "balanced_start": 1,
    "strong_leader": 2,
}
_FORBIDDEN_COLUMN = re.compile(
    r"(?:^|_)(?:future|outcome|target_touched|terminal_return|"
    r"max_favorable|max_adverse|first_target|forward|post_formation)(?:_|$)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class MatchingAudit:
    project_id: str
    requested: int
    matched: int
    status: str


@dataclass(frozen=True, slots=True)
class ControlMembershipReceipt:
    formation_date: date
    memberships: pd.DataFrame
    matching_audit: tuple[MatchingAudit, ...]
    receipt_hash: str


def freeze_daily_controls(
    universe: pd.DataFrame,
    route_batch: pd.DataFrame,
    candidates: pd.DataFrame,
) -> ControlMembershipReceipt:
    """Freeze all control membership without looking at future outcomes."""

    frames = {
        "universe": _copy_frame(universe, "universe"),
        "route_batch": _copy_frame(route_batch, "route batch"),
        "candidates": _copy_frame(candidates, "candidates"),
    }
    for label, frame in frames.items():
        _reject_result_columns(frame, label)

    prepared = _prepare_universe(frames["universe"])
    formation_date = _one_formation_date(
        prepared, frames["route_batch"], frames["candidates"]
    )
    all_market = _all_market_members(prepared, formation_date)
    matched, audits = _matched_members(
        prepared,
        frames["candidates"],
        formation_date,
    )
    transparent = _transparent_baselines(
        prepared,
        frames["route_batch"],
        formation_date,
    )
    memberships = _normalise_output(
        pd.concat((all_market, matched, transparent), ignore_index=True, sort=False)
    )
    receipt_hash = _stable_hash(
        {
            "formation_date": formation_date,
            "memberships": memberships.to_dict("records"),
            "matching_audit": audits,
        }
    )
    return ControlMembershipReceipt(
        formation_date=formation_date,
        memberships=memberships,
        matching_audit=audits,
        receipt_hash=receipt_hash,
    )


def _copy_frame(value: pd.DataFrame, label: str) -> pd.DataFrame:
    if not isinstance(value, pd.DataFrame):
        raise TypeError(f"{label} must be a pandas DataFrame")
    return value.copy(deep=True)


def _reject_result_columns(frame: pd.DataFrame, label: str) -> None:
    forbidden = sorted(str(column) for column in frame if _FORBIDDEN_COLUMN.search(str(column)))
    if forbidden:
        raise ValueError(
            f"{label} contains future or outcome fields: {', '.join(forbidden)}"
        )


def _prepare_universe(frame: pd.DataFrame) -> pd.DataFrame:
    required = {
        "formation_date",
        "security_id",
        "listing_board",
        "industry",
        "tradable",
        "history_20d_complete",
        "return_20d",
        "return_5d",
        "amount_20d",
        "relative_return_20d",
        "current_amount_ratio_20d",
    }
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"universe lacks required columns: {', '.join(missing)}")
    prepared = frame.copy()
    prepared["formation_date"] = pd.to_datetime(
        prepared["formation_date"], errors="raise"
    ).dt.date
    prepared["security_id"] = prepared["security_id"].astype(str)
    if prepared.duplicated(["formation_date", "security_id"]).any():
        raise ValueError("universe contains duplicate formation-date security rows")
    if not prepared["tradable"].map(lambda value: type(value) is bool).all():
        raise ValueError("tradable must contain literal booleans")
    eligible = prepared["tradable"] & prepared["history_20d_complete"].map(
        lambda value: type(value) is bool and value
    )
    prepared["price_role"] = pd.NA
    prepared["liquidity_quintile"] = pd.NA

    for _, indexes in prepared[eligible].groupby("formation_date", sort=True).groups.items():
        group = prepared.loc[indexes]
        pct = pd.to_numeric(group["return_20d"], errors="coerce").rank(
            method="average", pct=True
        )
        return_5d = pd.to_numeric(group["return_5d"], errors="coerce")
        roles = pd.Series("other_tradable", index=group.index, dtype="object")
        roles[(pct >= 0.20) & (pct < 0.80) & (return_5d > 0)] = "balanced_start"
        roles[pct >= 0.80] = "strong_leader"
        roles[pct.isna()] = pd.NA
        prepared.loc[group.index, "price_role"] = roles

    for _, indexes in prepared[eligible].groupby(
        ["formation_date", "listing_board"], sort=True
    ).groups.items():
        group = prepared.loc[indexes]
        pct = pd.to_numeric(group["amount_20d"], errors="coerce").rank(
            method="average", pct=True
        )
        quintile = pct.map(
            lambda value: pd.NA
            if pd.isna(value)
            else min(5, max(1, int(math.ceil(float(value) * 5))))
        )
        prepared.loc[group.index, "liquidity_quintile"] = quintile
    return prepared.sort_values(["formation_date", "security_id"]).reset_index(drop=True)


def _one_formation_date(*frames: pd.DataFrame) -> date:
    dates: set[date] = set()
    for frame in frames:
        if "formation_date" not in frame:
            raise ValueError("every formation input requires formation_date")
        parsed = pd.to_datetime(frame["formation_date"], errors="raise").dt.date
        dates.update(parsed.tolist())
    if len(dates) != 1:
        raise ValueError("daily control freeze requires exactly one formation date")
    return next(iter(dates))


def _all_market_members(universe: pd.DataFrame, formation_date: date) -> pd.DataFrame:
    rows = universe[universe["tradable"]].copy()
    rows["project_id"] = rows["security_id"].map(
        lambda value: f"all_market:{formation_date.isoformat()}:{value}"
    )
    rows["cohort"] = "all_market"
    rows["eligible"] = True
    rows["discovery_date"] = formation_date
    rows["matched_project_id"] = pd.NA
    rows["baseline_rank"] = pd.NA
    return rows


def _matched_members(
    universe: pd.DataFrame,
    candidates: pd.DataFrame,
    formation_date: date,
) -> tuple[pd.DataFrame, tuple[MatchingAudit, ...]]:
    required = {"formation_date", "project_id", "security_id"}
    missing = sorted(required.difference(candidates.columns))
    if missing:
        raise ValueError(f"candidates lack required columns: {', '.join(missing)}")
    selected = candidates.copy()
    selected["formation_date"] = pd.to_datetime(
        selected["formation_date"], errors="raise"
    ).dt.date
    if selected.duplicated(["formation_date", "project_id"]).any():
        raise ValueError("candidate project ids must be unique within a day")
    selected = selected.sort_values(["project_id", "security_id"])
    lookup = universe.set_index("security_id", drop=False)
    used: set[str] = set(selected["security_id"].astype(str))
    rows: list[dict[str, Any]] = []
    audits: list[MatchingAudit] = []
    for candidate in selected.to_dict("records"):
        security_id = str(candidate["security_id"])
        project_id = str(candidate["project_id"])
        if security_id not in lookup.index:
            matches: list[str] = []
        else:
            anchor = lookup.loc[security_id]
            if isinstance(anchor, pd.DataFrame):
                raise ValueError("universe security lookup is not unique")
            matches = _select_matches(universe, anchor, used)
        for rank, control_id in enumerate(matches, start=1):
            used.add(control_id)
            source = lookup.loc[control_id].to_dict()
            source.update(
                {
                    "project_id": f"matched:{project_id}:{control_id}",
                    "cohort": "matched_market",
                    "eligible": True,
                    "discovery_date": formation_date,
                    "matched_project_id": project_id,
                    "baseline_rank": rank,
                }
            )
            rows.append(source)
        audits.append(
            MatchingAudit(
                project_id=project_id,
                requested=5,
                matched=len(matches),
                status="complete" if len(matches) == 5 else "insufficient_matches",
            )
        )
    return pd.DataFrame(rows), tuple(audits)


def _select_matches(
    universe: pd.DataFrame,
    anchor: pd.Series,
    used: set[str],
) -> list[str]:
    if pd.isna(anchor["price_role"]) or pd.isna(anchor["liquidity_quintile"]):
        return []
    base = universe[
        universe["tradable"]
        & universe["history_20d_complete"].map(lambda value: type(value) is bool and value)
        & (universe["listing_board"] == anchor["listing_board"])
        & (universe["industry"] == anchor["industry"])
        & ~universe["security_id"].isin(used)
        & universe["price_role"].notna()
        & universe["liquidity_quintile"].notna()
    ].copy()
    anchor_role = _PRICE_ROLE_ORDER[str(anchor["price_role"])]
    anchor_quintile = int(anchor["liquidity_quintile"])
    base["_role_distance"] = base["price_role"].map(_PRICE_ROLE_ORDER).map(
        lambda value: abs(int(value) - anchor_role)
    )
    base["_liquidity_distance"] = base["liquidity_quintile"].map(
        lambda value: abs(int(value) - anchor_quintile)
    )
    exact = base[
        (base["_role_distance"] == 0) & (base["_liquidity_distance"] == 0)
    ].sort_values("security_id")
    selected = exact["security_id"].astype(str).tolist()[:5]
    if len(selected) < 3:
        adjacent_liquidity = base[
            (base["_role_distance"] == 0)
            & (base["_liquidity_distance"] == 1)
            & ~base["security_id"].isin(selected)
        ].sort_values(["_liquidity_distance", "security_id"])
        selected.extend(
            adjacent_liquidity["security_id"].astype(str).tolist()[: 5 - len(selected)]
        )
    if len(selected) < 3:
        adjacent_role = base[
            (base["_role_distance"] == 1)
            & (base["_liquidity_distance"] <= 1)
            & ~base["security_id"].isin(selected)
        ].sort_values(["_role_distance", "_liquidity_distance", "security_id"])
        selected.extend(adjacent_role["security_id"].astype(str).tolist()[: 5 - len(selected)])
    return selected[:5]


def _transparent_baselines(
    universe: pd.DataFrame,
    routes: pd.DataFrame,
    formation_date: date,
) -> pd.DataFrame:
    required = {"formation_date", "security_id", "route", "usable_for_decision"}
    missing = sorted(required.difference(routes.columns))
    if missing:
        raise ValueError(f"route batch lacks required columns: {', '.join(missing)}")
    values = routes.copy()
    values["formation_date"] = pd.to_datetime(
        values["formation_date"], errors="raise"
    ).dt.date
    if not values["usable_for_decision"].map(lambda value: type(value) is bool).all():
        raise ValueError("route usable_for_decision must contain literal booleans")
    lookup_columns = ["security_id", "listing_board", "industry", "price_role", "liquidity_quintile"]
    lookup = universe[lookup_columns].drop_duplicates("security_id")

    hotspot = values[values["route"].astype(str) == "hotspot"].copy()
    hotspot = _require_sort_columns(
        hotspot,
        (
            "relative_return_20d",
            "breadth_20d",
            "median_return_20d",
            "turnover_share_average_20d",
        ),
        "hotspot baseline",
    )
    hotspot = hotspot.sort_values(
        [
            "relative_return_20d",
            "breadth_20d",
            "median_return_20d",
            "turnover_share_average_20d",
            "security_id",
        ],
        ascending=[False, False, False, False, True],
        na_position="last",
    ).drop_duplicates("security_id").head(10)

    earnings = values[values["route"].astype(str) == "earnings"].copy()
    earnings = _require_sort_columns(
        earnings,
        ("available_at", "tr_yoy", "netprofit_yoy", "dt_netprofit_yoy", "ocf_yoy"),
        "earnings baseline",
    )
    change_columns = ["tr_yoy", "netprofit_yoy", "dt_netprofit_yoy", "ocf_yoy"]
    changes = earnings[change_columns].apply(pd.to_numeric, errors="coerce").abs()
    earnings["operating_change_magnitude"] = changes.max(axis=1, skipna=True)
    earnings.loc[changes.notna().sum(axis=1) == 0, "operating_change_magnitude"] = np.nan
    earnings["available_at"] = pd.to_datetime(earnings["available_at"], errors="raise", utc=True)
    earnings = earnings.sort_values(
        ["available_at", "operating_change_magnitude", "security_id"],
        ascending=[False, False, True],
        na_position="last",
    ).drop_duplicates("security_id").head(10)

    price = universe[
        universe["tradable"]
        & universe["history_20d_complete"].map(lambda value: type(value) is bool and value)
        & pd.to_numeric(universe["relative_return_20d"], errors="coerce").ge(0)
        & pd.to_numeric(universe["current_amount_ratio_20d"], errors="coerce").notna()
    ].copy()
    price = price.sort_values(
        ["relative_return_20d", "current_amount_ratio_20d", "security_id"],
        ascending=[False, False, True],
    ).head(10)

    outputs = (
        _baseline_rows(hotspot, lookup, formation_date, "hotspot_baseline"),
        _baseline_rows(earnings, lookup, formation_date, "earnings_baseline"),
        _baseline_rows(price, lookup, formation_date, "price_baseline"),
    )
    return pd.concat(outputs, ignore_index=True, sort=False)


def _require_sort_columns(frame: pd.DataFrame, columns: tuple[str, ...], label: str) -> pd.DataFrame:
    missing = sorted(set(columns).difference(frame.columns))
    if missing and not frame.empty:
        raise ValueError(f"{label} lacks sort columns: {', '.join(missing)}")
    for column in missing:
        frame[column] = pd.NA
    return frame


def _baseline_rows(
    values: pd.DataFrame,
    lookup: pd.DataFrame,
    formation_date: date,
    cohort: str,
) -> pd.DataFrame:
    if values.empty:
        return pd.DataFrame()
    rows = values.merge(lookup, on="security_id", how="left", suffixes=("", "_universe"))
    rows["project_id"] = rows["security_id"].map(
        lambda value: f"{cohort}:{formation_date.isoformat()}:{value}"
    )
    rows["cohort"] = cohort
    rows["eligible"] = True
    rows["discovery_date"] = formation_date
    rows["matched_project_id"] = pd.NA
    rows["baseline_rank"] = range(1, len(rows) + 1)
    return rows


def _normalise_output(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    frame = frame.copy()
    frame["_cohort_order"] = frame["cohort"].map(_COHORT_ORDER)
    frame["baseline_rank"] = pd.to_numeric(frame["baseline_rank"], errors="coerce").astype("Int64")
    frame["liquidity_quintile"] = pd.to_numeric(
        frame["liquidity_quintile"], errors="coerce"
    ).astype("Int64")
    frame = frame.sort_values(
        ["_cohort_order", "matched_project_id", "baseline_rank", "security_id"],
        na_position="last",
        kind="mergesort",
    ).drop(columns="_cohort_order")
    preferred = [
        "project_id",
        "security_id",
        "cohort",
        "eligible",
        "formation_date",
        "discovery_date",
        "listing_board",
        "industry",
        "price_role",
        "liquidity_quintile",
        "matched_project_id",
        "baseline_rank",
    ]
    remaining = sorted(column for column in frame if column not in preferred)
    return frame[[*preferred, *remaining]].reset_index(drop=True)


def _stable_hash(value: Any) -> str:
    payload = json.dumps(
        _jsonable(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _jsonable(value: Any) -> Any:
    if isinstance(value, MatchingAudit):
        return {
            "project_id": value.project_id,
            "requested": value.requested,
            "matched": value.matched,
            "status": value.status,
        }
    if isinstance(value, (date, datetime, pd.Timestamp)):
        return value.isoformat()
    if value is pd.NA or value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value
