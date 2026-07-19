from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from stock_analyzer.evaluation.historical_framework_validation import (
    round_robin_union,
)
from stock_analyzer.evaluation.v3_layered_validation import (
    _active_memberships,
    limit_to_tradable_route,
)


@dataclass(frozen=True)
class V2RouteEvidence:
    route_rows: pd.DataFrame
    evidence: pd.DataFrame
    top_hotspot_groups: pd.DataFrame
    hotspot_overlap: pd.DataFrame


def round_robin_hotspot_codes(
    group_lists: Mapping[str, Sequence[str]], *, limit: int
) -> tuple[str, ...]:
    return round_robin_union(group_lists, limit=limit)


def hotspot_overlap_audit(
    groups: pd.DataFrame, memberships: pd.DataFrame
) -> pd.DataFrame:
    columns = [
        "left_group_type",
        "left_group_code",
        "left_group_name",
        "right_group_type",
        "right_group_code",
        "right_group_name",
        "intersection_count",
        "union_count",
        "jaccard_overlap",
    ]
    required_groups = {"group_type", "group_code", "group_name"}
    required_members = {"group_type", "group_code", "ts_code"}
    if groups.empty or memberships.empty:
        return pd.DataFrame(columns=columns)
    if not required_groups <= set(groups):
        raise ValueError("hotspot groups lack overlap fields")
    if not required_members <= set(memberships):
        raise ValueError("hotspot memberships lack overlap fields")
    prepared_groups = groups.drop_duplicates(
        ["group_type", "group_code"], keep="first"
    ).reset_index(drop=True)
    member_sets: dict[tuple[str, str], set[str]] = {}
    for row in memberships.to_dict(orient="records"):
        key = (str(row["group_type"]), str(row["group_code"]))
        member_sets.setdefault(key, set()).add(str(row["ts_code"]))
    rows: list[dict[str, Any]] = []
    for left_index in range(len(prepared_groups)):
        left = prepared_groups.iloc[left_index]
        left_key = (str(left["group_type"]), str(left["group_code"]))
        left_members = member_sets.get(left_key, set())
        for right_index in range(left_index + 1, len(prepared_groups)):
            right = prepared_groups.iloc[right_index]
            right_key = (str(right["group_type"]), str(right["group_code"]))
            right_members = member_sets.get(right_key, set())
            union = left_members | right_members
            if not union:
                continue
            intersection = left_members & right_members
            rows.append(
                {
                    "left_group_type": left_key[0],
                    "left_group_code": left_key[1],
                    "left_group_name": str(left["group_name"]),
                    "right_group_type": right_key[0],
                    "right_group_code": right_key[1],
                    "right_group_name": str(right["group_name"]),
                    "intersection_count": len(intersection),
                    "union_count": len(union),
                    "jaccard_overlap": len(intersection) / len(union),
                }
            )
    return pd.DataFrame(rows, columns=columns).sort_values(
        ["jaccard_overlap", "left_group_code", "right_group_code"],
        ascending=[False, True, True],
        ignore_index=True,
    )


def build_v2_route_evidence(
    *,
    formation_date: pd.Timestamp,
    market: pd.DataFrame,
    stocks: pd.DataFrame,
    hotspots: pd.DataFrame,
    memberships: pd.DataFrame,
    company_facts: pd.DataFrame,
    route_recall_cap: int = 30,
) -> V2RouteEvidence:
    stock = stocks.copy().set_index("ts_code", drop=False)
    tradable_codes = set(stock.index.astype(str))
    complete_groups = hotspots[
        hotspots["coverage_status"].astype(str).str.startswith("complete")
        & (pd.to_numeric(hotspots["breadth_5d"], errors="coerce") >= 0.50)
        & (pd.to_numeric(hotspots["relative_return_5d"], errors="coerce") > 0)
    ].copy()
    complete_groups = complete_groups.sort_values(
        ["relative_return_20d", "breadth_5d", "turnover_share_change_5d"],
        ascending=False,
        na_position="last",
    ).head(10).reset_index(drop=True)
    active = _active_memberships(memberships, formation_date)
    top_keys = set(
        zip(
            complete_groups["group_type"].astype(str),
            complete_groups["group_code"].astype(str),
        )
    )
    active["group_key"] = list(
        zip(active["group_type"].astype(str), active["group_code"].astype(str))
    )
    active_top = active[active["group_key"].isin(top_keys)].copy()
    group_rank = {
        (str(row.group_type), str(row.group_code)): rank
        for rank, row in enumerate(complete_groups.itertuples(index=False), start=1)
    }
    active_top["group_rank"] = active_top["group_key"].map(group_rank)
    group_lists: dict[str, list[str]] = {}
    for group in complete_groups.itertuples(index=False):
        key = (str(group.group_type), str(group.group_code))
        label = f"{key[0]}|{key[1]}"
        members = active_top[
            active_top["group_key"].map(lambda value: value == key)
        ].merge(
            stocks[["ts_code", "relative_return_20d", "current_amount_ratio_20d"]],
            on="ts_code",
            how="inner",
        ).sort_values(
            ["relative_return_20d", "current_amount_ratio_20d"],
            ascending=False,
            na_position="last",
        )
        group_lists[label] = limit_to_tradable_route(
            members["ts_code"].astype(str).tolist(),
            tradable_codes=tradable_codes,
            limit=len(members),
        )
    hotspot_codes = list(
        round_robin_hotspot_codes(group_lists, limit=route_recall_cap)
    )
    overlap = hotspot_overlap_audit(complete_groups, active_top)

    company = company_facts.copy()
    company["report_age_days"] = (
        formation_date - pd.to_datetime(company["report_period"]).dt.normalize()
    ).dt.days
    numeric_company = [
        "tr_yoy",
        "netprofit_yoy",
        "dt_netprofit_yoy",
        "ocf_yoy",
        "ocfps",
        "n_cashflow_act",
    ]
    for column in numeric_company:
        company[column] = pd.to_numeric(company[column], errors="coerce")
    company["company_evidence"] = (
        company["report_age_days"].between(0, 150)
        & (company["tr_yoy"] > 0)
        & (company["netprofit_yoy"] > 0)
        & (company["dt_netprofit_yoy"] > 0)
        & (company["n_cashflow_act"] > 0)
    )
    earnings = company[company["company_evidence"]].sort_values(
        ["dt_netprofit_yoy", "netprofit_yoy", "tr_yoy", "available_at"],
        ascending=[False, False, False, False],
        na_position="last",
    )
    earnings_codes = limit_to_tradable_route(
        earnings["ts_code"].astype(str).tolist(),
        tradable_codes=tradable_codes,
        limit=route_recall_cap,
    )
    price = stocks[
        (pd.to_numeric(stocks["relative_return_20d"], errors="coerce") > 0)
        & (pd.to_numeric(stocks["price_location_60d"], errors="coerce") >= 0.50)
        & (pd.to_numeric(stocks["current_amount_ratio_20d"], errors="coerce") >= 1.0)
        & (pd.to_numeric(stocks["average_amount_20d"], errors="coerce") >= 20000.0)
    ].sort_values(
        ["relative_return_20d", "current_amount_ratio_20d"],
        ascending=False,
        na_position="last",
    )
    price_codes = limit_to_tradable_route(
        price["ts_code"].astype(str).tolist(),
        tradable_codes=tradable_codes,
        limit=route_recall_cap,
    )
    route_lists = {
        "hotspot": hotspot_codes,
        "earnings": earnings_codes,
        "price": price_codes,
    }
    research_codes = round_robin_union(
        route_lists, limit=route_recall_cap * len(route_lists)
    )
    company_by_code = company.set_index("ts_code", drop=False)
    active_top_by_code = (
        active_top.sort_values("group_rank")
        .drop_duplicates("ts_code")
        .set_index("ts_code")
    )
    amounts = pd.to_numeric(stocks["average_amount_20d"], errors="coerce")
    q33, q67 = amounts.quantile([0.33, 0.67]).tolist()
    market_breadth = float(market.iloc[0].get("breadth_20d", np.nan))
    evidence_rows: list[dict[str, Any]] = []
    for code in research_codes:
        observation = stock.loc[code]
        if isinstance(observation, pd.DataFrame):
            raise ValueError("stock context has duplicate codes")
        financial = company_by_code.loc[code] if code in company_by_code.index else None
        if isinstance(financial, pd.DataFrame):
            financial = financial.iloc[-1]
        routes = [route for route, codes in route_lists.items() if code in codes]
        report_age = int(financial["report_age_days"]) if financial is not None else 9999
        freshness = 3 if report_age <= 60 else 2 if report_age <= 120 else 1
        if financial is None:
            consistency = 0
            company_evidence = False
        else:
            positives = sum(
                bool(pd.notna(financial[field]) and float(financial[field]) > 0)
                for field in ("tr_yoy", "netprofit_yoy", "dt_netprofit_yoy", "ocf_yoy")
            )
            consistency = 3 if positives == 4 else 2 if positives >= 3 else 1
            company_evidence = bool(financial["company_evidence"])
        hotspot_support = 0
        group_name = None
        if code in active_top_by_code.index:
            member = active_top_by_code.loc[code]
            rank = int(member["group_rank"])
            hotspot_support = 3 if rank <= 3 else 2
            group_name = next(
                (
                    str(row.group_name)
                    for row in complete_groups.itertuples(index=False)
                    if str(row.group_type) == str(member["group_type"])
                    and str(row.group_code) == str(member["group_code"])
                ),
                None,
            )
        return_20 = (
            float(observation["return_20d"])
            if pd.notna(observation["return_20d"])
            else np.nan
        )
        location = (
            float(observation["price_location_60d"])
            if pd.notna(observation["price_location_60d"])
            else np.nan
        )
        if np.isfinite(return_20) and np.isfinite(location) and 0 <= return_20 <= 0.20 and location <= 0.90:
            price_safety = 3
        elif np.isfinite(return_20) and np.isfinite(location) and return_20 <= 0.40 and location < 0.99:
            price_safety = 2
        else:
            price_safety = 1
        average_amount = (
            float(observation["average_amount_20d"])
            if pd.notna(observation["average_amount_20d"])
            else np.nan
        )
        liquidity = 3 if average_amount >= q67 else 2 if average_amount >= q33 else 1
        hard_invalid = (
            not np.isfinite(average_amount)
            or average_amount < 20000.0
            or (
                pd.notna(observation["return_5d"])
                and float(observation["return_5d"]) > 0.30
            )
            or (np.isfinite(location) and location >= 0.995)
            or (
                np.isfinite(market_breadth)
                and market_breadth < 0.45
                and price_safety < 2
            )
        )
        evidence_rows.append(
            {
                "formation_date": formation_date,
                "ts_code": code,
                "routes": "|".join(routes),
                "company_evidence": company_evidence,
                "hard_invalid": hard_invalid,
                "evidence_freshness": freshness,
                "earnings_cash_consistency": consistency,
                "hotspot_support": hotspot_support,
                "price_consumption_safety": price_safety,
                "liquidity": liquidity,
                "market_breadth_20d": market_breadth,
                "hotspot_group_name": group_name,
                "report_period": financial["report_period"] if financial is not None else pd.NaT,
                "report_available_at": financial["available_at"] if financial is not None else pd.NaT,
                "tr_yoy": financial["tr_yoy"] if financial is not None else np.nan,
                "netprofit_yoy": financial["netprofit_yoy"] if financial is not None else np.nan,
                "dt_netprofit_yoy": financial["dt_netprofit_yoy"] if financial is not None else np.nan,
                "ocf_yoy": financial["ocf_yoy"] if financial is not None else np.nan,
                "n_cashflow_act": financial["n_cashflow_act"] if financial is not None else np.nan,
                "return_5d": observation["return_5d"],
                "return_20d": observation["return_20d"],
                "relative_return_20d": observation["relative_return_20d"],
                "price_location_60d": observation["price_location_60d"],
                "current_amount_ratio_20d": observation["current_amount_ratio_20d"],
                "average_amount_20d": observation["average_amount_20d"],
                "pe_ttm": observation["pe_ttm"],
                "pb": observation["pb"],
            }
        )
    route_rows = [
        {
            "formation_date": formation_date,
            "route": route,
            "route_rank": rank,
            "ts_code": code,
        }
        for route, codes in route_lists.items()
        for rank, code in enumerate(codes, start=1)
    ]
    evidence = pd.DataFrame(evidence_rows)
    return V2RouteEvidence(
        route_rows=pd.DataFrame(route_rows),
        evidence=evidence,
        top_hotspot_groups=complete_groups,
        hotspot_overlap=overlap,
    )


__all__ = [
    "V2RouteEvidence",
    "build_v2_route_evidence",
    "hotspot_overlap_audit",
    "round_robin_hotspot_codes",
]
