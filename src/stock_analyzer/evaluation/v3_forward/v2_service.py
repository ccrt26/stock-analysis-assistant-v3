from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from stock_analyzer.evaluation.v3_forward.explanation_service import (
    DecisionCardRunResult,
    explain_observation,
)
from stock_analyzer.evaluation.v3_forward.explanations import (
    build_decision_cards,
    render_decision_cards,
)
from stock_analyzer.evaluation.v3_forward.inputs import load_formation_inputs
from stock_analyzer.evaluation.v3_forward.ledger import (
    BundleWriteResult,
    ForwardLedger,
)
from stock_analyzer.evaluation.v3_forward.rules import FUTURE_FIELDS
from stock_analyzer.evaluation.v3_forward.service import _stable_hash
from stock_analyzer.evaluation.v3_forward.v2_selection import (
    V2_MINIMUM_FORMATION_DATE,
    V2_RULE_VERSION,
    form_attention_list_v2,
    v2_rule_manifest,
    v2_rule_manifest_hash,
)


@dataclass(frozen=True)
class V2FormationRunResult:
    bundle: BundleWriteResult
    cards: DecisionCardRunResult
    attention_count: int
    action_count: int


def _number(value: Any) -> str:
    try:
        if value is None or pd.isna(value):
            return "缺失"
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "缺失"


def _pct(value: Any) -> str:
    try:
        if value is None or pd.isna(value):
            return "缺失"
        return f"{float(value):.2%}"
    except (TypeError, ValueError):
        return "缺失"


def render_v2_formation_report(
    payload: dict[str, Any],
    candidates: pd.DataFrame,
    route_audit: pd.DataFrame,
    top_hotspot_groups: pd.DataFrame,
    hotspot_overlap: pd.DataFrame,
    industry_concentration: pd.DataFrame,
    cards: pd.DataFrame,
) -> str:
    lines = [
        f"# V3 前瞻观察 V02 形成报告：{payload['formation_date']}",
        "",
        f"- 规则版本：{payload['rule_version']}",
        f"- 数据截止：{payload['data_cutoff_at']}",
        f"- 关注股票：{len(candidates)} 只",
        f"- 动作确认：{int(payload['action_count'])} 只",
        "- 名单不排名、不补位、不使用行业配额。",
        "",
        "## 市场与热点摘要",
        "",
        f"- 全市场20日上涨面：{_pct(payload.get('market_breadth_20d'))}",
    ]
    if top_hotspot_groups.empty:
        lines.append("- 当前没有符合冻结条件的热点组。")
    else:
        for row in top_hotspot_groups.head(10).to_dict(orient="records"):
            lines.append(
                f"- {row.get('group_name', '缺失')}：5日上涨面"
                f" {_pct(row.get('breadth_5d'))}，20日相对收益"
                f" {_pct(row.get('relative_return_20d'))}"
            )
    lines.extend(["", "## 路线召回与压缩审计", ""])
    if route_audit.empty:
        lines.append("- 路线审计缺失。")
    else:
        lines.extend(
            [
                "| 路线 | 召回 | 合格 | 非支配前沿 | 最终入选 |",
                "| --- | ---: | ---: | ---: | ---: |",
            ]
        )
        for row in route_audit.to_dict(orient="records"):
            lines.append(
                f"| {row['route']} | {row['recalled_count']} |"
                f" {row['eligible_count']} | {row['frontier_count']} |"
                f" {row['selected_count']} |"
            )
    lines.extend(["", "## 行业集中审计", ""])
    attention_industry = industry_concentration[
        industry_concentration["scope"].eq("attention")
    ] if not industry_concentration.empty else industry_concentration
    if attention_industry.empty:
        lines.append("- 没有可统计的一级行业。")
    else:
        for row in attention_industry.to_dict(orient="records"):
            lines.append(
                f"- {row['industry_l1_name']}：{row['count']} 只，"
                f"占关注名单 {_pct(row['ratio'])}"
            )
        if float(attention_industry["ratio"].max()) > 0.5:
            lines.append(
                "- **行业风险簇集中：同一一级行业超过名单半数。"
                "这是风险披露，不触发自动删除。**"
            )
    lines.extend(["", "## 热点成员重叠", ""])
    if hotspot_overlap.empty:
        lines.append("- 没有可比较的热点成员重叠。")
    else:
        for row in hotspot_overlap.head(5).to_dict(orient="records"):
            lines.append(
                f"- {row['left_group_name']} / {row['right_group_name']}："
                f"Jaccard {_pct(row['jaccard_overlap'])}"
                f"（交集 {row['intersection_count']}，并集 {row['union_count']}）"
            )
    lines.extend(["", "## 完整关注名单与三项确认", ""])
    if candidates.empty:
        lines.append("- 今日没有关注对象，系统没有补位。")
    else:
        lines.extend(
            [
                "| 股票 | 路线 | 近5日>0 | 20日相对>0 | 成交比率>=1 | 动作确认 | 一级行业 |",
                "| --- | --- | --- | --- | --- | --- | --- |",
            ]
        )
        for row in candidates.to_dict(orient="records"):
            yes = lambda value: "满足" if bool(value) else "不满足"
            lines.append(
                f"| {row.get('stock_name')}（{row['ts_code']}） | {row.get('routes')} |"
                f" {yes(row.get('confirm_return_5d_positive'))} |"
                f" {yes(row.get('confirm_relative_return_20d_positive'))} |"
                f" {yes(row.get('confirm_amount_ratio_20d'))} |"
                f" {yes(row.get('action_confirmed'))} |"
                f" {row.get('industry_l1_name', '缺失')} |"
            )
    lines.extend(["", "## 动作确认对象详细决策卡", ""])
    card_report = render_decision_cards(payload, cards)
    lines.append(card_report)
    lines.extend(
        [
            "",
            "## 结论边界",
            "",
            "- 本报告只用于冻结规则后的前瞻观察，不构成买卖、仓位或收益承诺。",
            "- 真实下一交易日开盘和未来窗口尚未到达时，不填入模拟结果。",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def form_observation_v2(
    *,
    warehouse_root: Path,
    archive_root: Path,
    output_root: Path,
    formation_date: date,
    now: datetime | None = None,
    enforce_real_root: bool = True,
) -> V2FormationRunResult:
    if pd.Timestamp(formation_date) < V2_MINIMUM_FORMATION_DATE:
        raise ValueError("V02 authority formation starts on or after 2026-07-20")
    ledger = ForwardLedger(output_root, enforce_real_root=enforce_real_root)
    existing = next(
        (
            bundle
            for bundle in ledger.load_formations()
            if str(bundle.payload.get("formation_date"))
            == formation_date.isoformat()
        ),
        None,
    )
    if existing is not None and str(existing.payload.get("rule_version")) != V2_RULE_VERSION:
        raise ValueError("formation date already belongs to another rule version")
    inputs = load_formation_inputs(
        Path(warehouse_root), Path(archive_root), formation_date
    )
    evidence = form_attention_list_v2(inputs)
    candidates = evidence.candidates
    generated_at = (
        str(existing.payload["generated_at"])
        if existing is not None
        else (now or datetime.now(timezone.utc)).isoformat()
    )
    action_count = int(
        candidates.get("action_confirmed", pd.Series(dtype=bool))
        .fillna(False)
        .astype(bool)
        .sum()
    )
    market_breadth = (
        float(inputs.market.iloc[0].get("breadth_20d"))
        if not inputs.market.empty
        and pd.notna(inputs.market.iloc[0].get("breadth_20d"))
        else None
    )
    payload: dict[str, Any] = {
        "schema_version": "v3-forward-formation-02",
        "formation_batch_id": f"{V2_RULE_VERSION}|{formation_date.isoformat()}",
        "rule_version": V2_RULE_VERSION,
        "rule_manifest_hash": v2_rule_manifest_hash(),
        "rule_manifest": v2_rule_manifest(),
        "formation_date": formation_date.isoformat(),
        "data_cutoff_at": inputs.cutoff.isoformat(),
        "generated_at": generated_at,
        "input_manifest_hash": _stable_hash(dict(inputs.input_manifest)),
        "input_manifest": dict(inputs.input_manifest),
        "attention_count": len(candidates),
        "action_count": action_count,
        "entry_state": "waiting",
        "market_breadth_20d": market_breadth,
        "route_audit": evidence.route_audit.to_dict(orient="records"),
        "hotspot_overlap_audit": evidence.hotspot_overlap.to_dict(
            orient="records"
        ),
        "industry_concentration": evidence.industry_concentration.to_dict(
            orient="records"
        ),
        "future_visibility_statement": (
            "formation uses no facts after the formation cutoff"
        ),
        "advice_statement": "forward observation only; not trading advice",
    }
    cards = build_decision_cards(payload, candidates, inputs)
    report = render_v2_formation_report(
        payload,
        candidates,
        evidence.route_audit,
        evidence.top_hotspot_groups,
        evidence.hotspot_overlap,
        evidence.industry_concentration,
        cards,
    )
    bundle = ledger.write_formation_bundle(payload, candidates, report)
    ledger.write_report_projection(
        Path(f"formation_date={formation_date.isoformat()}")
        / "formation-v3-forward-baseline-02.md",
        report,
    )
    audit = {
        "schema_version": "v3-forward-formation-audit-02",
        "status": "passed",
        "formation_date": formation_date.isoformat(),
        "rule_version": V2_RULE_VERSION,
        "candidate_rows": len(candidates),
        "action_rows": action_count,
        "duplicate_stock_dates": int(
            candidates.duplicated(["formation_date", "ts_code"]).sum()
            if not candidates.empty
            else 0
        ),
        "future_fields": sorted(set(candidates.columns) & FUTURE_FIELDS),
        "route_audit": payload["route_audit"],
        "industry_concentration": payload["industry_concentration"],
    }
    ledger.write_text_projection(
        "manifests",
        Path(f"formation_date={formation_date.isoformat()}")
        / "audit-v3-forward-baseline-02.json",
        json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
    )
    cards_result = explain_observation(
        warehouse_root=warehouse_root,
        archive_root=archive_root,
        output_root=output_root,
        formation_date=formation_date,
        now=now,
        enforce_real_root=enforce_real_root,
    )
    return V2FormationRunResult(
        bundle=bundle,
        cards=cards_result,
        attention_count=len(candidates),
        action_count=action_count,
    )


__all__ = [
    "V2FormationRunResult",
    "form_observation_v2",
    "render_v2_formation_report",
]

