from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from stock_analyzer.evaluation.historical_framework_validation import (
    round_robin_union,
)
from stock_analyzer.evaluation.v3_compression_revalidation import (
    FINANCIAL_FIELDS,
    LANE_DIMENSIONS,
    _pareto_front,
    derive_company_driver_state,
)
from stock_analyzer.evaluation.v3_forward.explanations import _industry_map
from stock_analyzer.evaluation.v3_forward.inputs import FormationInputs, _risk_notes
from stock_analyzer.evaluation.v3_forward.rules import (
    add_action_confirmations,
    reject_future_fields,
)
from stock_analyzer.evaluation.v3_forward.v2_routes import (
    build_v2_route_evidence,
)


V2_RULE_VERSION = "v3-forward-baseline-02"
V2_MINIMUM_FORMATION_DATE = pd.Timestamp("2026-07-20")
V2_SUPPORTED_ROUTES = ("hotspot", "earnings", "price")
V2_CANDIDATE_CAP = 10
V2_ROUTE_RECALL_CAP = 30


@dataclass(frozen=True)
class V2FormationEvidence:
    candidates: pd.DataFrame
    route_audit: pd.DataFrame
    top_hotspot_groups: pd.DataFrame
    hotspot_overlap: pd.DataFrame
    industry_concentration: pd.DataFrame


def _route_names(value: Any) -> tuple[str, ...]:
    return tuple(
        item
        for item in str(value).split("|")
        if item in V2_SUPPORTED_ROUTES
    )


def compress_v2_attention(
    evidence: pd.DataFrame,
    *,
    candidate_cap: int = V2_CANDIDATE_CAP,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if candidate_cap <= 0:
        raise ValueError("V02 candidate cap must be positive")
    required = {
        "formation_date",
        "ts_code",
        "routes",
        "company_evidence",
        "hard_invalid",
        "report_period",
        *FINANCIAL_FIELDS,
        *{
            column
            for dimensions in LANE_DIMENSIONS.values()
            for column in dimensions
        },
    }
    missing = sorted(required - set(evidence.columns))
    if missing:
        raise ValueError(f"V02 evidence lacks fields: {', '.join(missing)}")
    prepared = evidence.copy().reset_index(drop=True)
    if prepared.duplicated(["formation_date", "ts_code"]).any():
        raise ValueError("V02 evidence contains duplicate stock-date rows")
    dimensions = {
        item for values in LANE_DIMENSIONS.values() for item in values
    }
    for column in dimensions:
        prepared[column] = pd.to_numeric(prepared[column], errors="raise")
    prepared["company_driver_state"] = prepared.apply(
        derive_company_driver_state, axis=1
    )
    prepared["internal_lane"] = np.select(
        [
            prepared["company_driver_state"].eq("confirmed"),
            prepared["company_driver_state"].eq("partial"),
        ],
        ["focus_candidate", "company_observation"],
        default="elasticity_observation",
    )
    prepared["user_layer"] = "不展示"
    prepared["decision_reason"] = "route_local_pareto_dominated"
    prepared.loc[
        prepared["hard_invalid"].astype(bool), "decision_reason"
    ] = "hard_invalidation"
    parsed_routes = prepared["routes"].map(_route_names)
    front_by_route: dict[str, list[int]] = {}
    audit_rows: list[dict[str, Any]] = []
    for route in V2_SUPPORTED_ROUTES:
        route_mask = parsed_routes.map(lambda values: route in values)
        eligible = prepared[
            route_mask & ~prepared["hard_invalid"].astype(bool)
        ]
        front: list[int] = []
        for lane, lane_dimensions in LANE_DIMENSIONS.items():
            lane_frame = eligible[eligible["internal_lane"].eq(lane)]
            if lane == "elasticity_observation":
                overconsumed = lane_frame["price_consumption_safety"].lt(2)
                prepared.loc[
                    lane_frame.index[overconsumed], "decision_reason"
                ] = "insufficient_current_action_value"
                lane_frame = lane_frame[~overconsumed]
            front.extend(_pareto_front(lane_frame, lane_dimensions))
        front_by_route[route] = sorted(set(front))
        audit_rows.append(
            {
                "route": route,
                "recalled_count": int(route_mask.sum()),
                "eligible_count": len(eligible),
                "frontier_count": len(front_by_route[route]),
                "selected_count": 0,
            }
        )
    code_lists = {
        route: prepared.loc[indexes, "ts_code"].astype(str).tolist()
        for route, indexes in front_by_route.items()
    }
    selected_codes = list(
        round_robin_union(code_lists, limit=candidate_cap)
    )
    code_to_index = {
        str(row["ts_code"]): int(index)
        for index, row in prepared.iterrows()
    }
    selected_indexes = [code_to_index[code] for code in selected_codes]
    all_front_indexes = {
        index for indexes in front_by_route.values() for index in indexes
    }
    prepared.loc[list(all_front_indexes), "decision_reason"] = (
        "route_round_robin_capacity"
    )
    prepared.loc[selected_indexes, "user_layer"] = "关注"
    prepared.loc[selected_indexes, "decision_reason"] = (
        "route_local_non_dominated_attention"
    )
    selected_set = set(selected_codes)
    for row in audit_rows:
        route = str(row["route"])
        row["selected_count"] = sum(
            code in selected_set for code in code_lists[route]
        )
    return prepared, pd.DataFrame(audit_rows)


def _industry_concentration(candidates: pd.DataFrame) -> pd.DataFrame:
    columns = ["scope", "industry_l1_name", "count", "ratio"]
    rows: list[dict[str, Any]] = []
    scopes = {
        "attention": candidates,
        "action_confirmed": candidates[
            candidates.get(
                "action_confirmed", pd.Series(False, index=candidates.index)
            )
            .fillna(False)
            .astype(bool)
        ],
    }
    for scope, frame in scopes.items():
        if frame.empty:
            continue
        counts = (
            frame["industry_l1_name"]
            .fillna("本地严格时点数据缺失")
            .astype(str)
            .value_counts()
        )
        for industry, count in counts.items():
            rows.append(
                {
                    "scope": scope,
                    "industry_l1_name": str(industry),
                    "count": int(count),
                    "ratio": float(count / len(frame)),
                }
            )
    return pd.DataFrame(rows, columns=columns)


def form_attention_list_v2(inputs: FormationInputs) -> V2FormationEvidence:
    route_evidence = build_v2_route_evidence(
        formation_date=pd.Timestamp(inputs.formation_date),
        market=inputs.market,
        stocks=inputs.stocks,
        hotspots=inputs.hotspots,
        memberships=inputs.memberships,
        company_facts=inputs.company_facts,
        route_recall_cap=V2_ROUTE_RECALL_CAP,
    )
    reject_future_fields(route_evidence.evidence)
    decisions, route_audit = compress_v2_attention(
        route_evidence.evidence, candidate_cap=V2_CANDIDATE_CAP
    )
    selected = decisions[decisions["user_layer"].eq("关注")].copy()
    if len(selected) > V2_CANDIDATE_CAP:
        raise ValueError("V02 attention list exceeds candidate cap")
    if selected.duplicated(["formation_date", "ts_code"]).any():
        raise ValueError("V02 attention list contains duplicate stock-date rows")
    selected = add_action_confirmations(selected)
    selected["entry_state"] = "waiting"
    selected["risk_notes"] = selected.apply(_risk_notes, axis=1)
    selected["stock_name"] = selected["ts_code"].astype(str).map(
        inputs.names
    ).fillna(selected["ts_code"].astype(str))
    industries = _industry_map(inputs)
    selected["industry_l1_name"] = selected["ts_code"].astype(str).map(
        industries
    ).fillna("本地严格时点数据缺失")
    selected["formation_item_id"] = (
        V2_RULE_VERSION
        + "|"
        + inputs.formation_date.isoformat()
        + "|"
        + selected["ts_code"].astype(str)
    )
    selected = selected.reset_index(drop=True)
    return V2FormationEvidence(
        candidates=selected,
        route_audit=route_audit,
        top_hotspot_groups=route_evidence.top_hotspot_groups,
        hotspot_overlap=route_evidence.hotspot_overlap,
        industry_concentration=_industry_concentration(selected),
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def v2_rule_manifest() -> dict[str, Any]:
    evaluation_root = Path(__file__).resolve().parents[1]
    sources = {
        "v2_selection": Path(__file__).resolve(),
        "v2_routes": Path(__file__).resolve().with_name("v2_routes.py"),
        "action_confirmation": evaluation_root / "v3_selection_accuracy_pareto.py",
        "entry_semantics": evaluation_root / "v3_next_day_entry_validation.py",
    }
    return {
        "rule_version": V2_RULE_VERSION,
        "minimum_formation_date": V2_MINIMUM_FORMATION_DATE.date().isoformat(),
        "supported_routes": list(V2_SUPPORTED_ROUTES),
        "route_recall_cap": V2_ROUTE_RECALL_CAP,
        "candidate_cap": V2_CANDIDATE_CAP,
        "hotspot_recall": "round_robin_across_ordered_top_groups",
        "pareto_scope": "same_route_and_internal_lane",
        "capacity_handling": "round_robin_across_routes_without_padding",
        "industry_quota": None,
        "action_confirmations": [
            "return_5d > 0",
            "relative_return_20d > 0",
            "current_amount_ratio_20d >= 1",
        ],
        "source_sha256": {
            name: _sha256_file(path) for name, path in sorted(sources.items())
        },
    }


def v2_rule_manifest_hash() -> str:
    encoded = json.dumps(
        v2_rule_manifest(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "V2_CANDIDATE_CAP",
    "V2_MINIMUM_FORMATION_DATE",
    "V2_ROUTE_RECALL_CAP",
    "V2_RULE_VERSION",
    "V2_SUPPORTED_ROUTES",
    "V2FormationEvidence",
    "compress_v2_attention",
    "form_attention_list_v2",
    "v2_rule_manifest",
    "v2_rule_manifest_hash",
]
