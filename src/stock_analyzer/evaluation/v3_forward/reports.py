from __future__ import annotations

from typing import Any, Mapping

import pandas as pd


def _value(value: Any) -> str:
    if value is None or value is pd.NA or (isinstance(value, float) and pd.isna(value)):
        return "缺失"
    return str(value)


def _percent(value: Any) -> str:
    try:
        if pd.isna(value):
            return "缺失"
        return f"{float(value):.2%}"
    except (TypeError, ValueError):
        return "缺失"


def render_formation_report(
    payload: Mapping[str, Any], candidates: pd.DataFrame
) -> str:
    confirmed = (
        candidates[candidates["action_confirmed"].fillna(False).astype(bool)]
        if "action_confirmed" in candidates
        else candidates.iloc[0:0]
    )
    lines = [
        f"# V3 前瞻观察形成报告：{payload['formation_date']}",
        "",
        f"- 规则版本：`{payload['rule_version']}`",
        f"- 数据截止：{payload['data_cutoff_at']}",
        f"- 实际生成：{payload['generated_at']}",
        f"- 输入清单签名：`{payload['input_manifest_hash']}`",
        f"- 关注股票：{len(candidates)} 只",
        f"- 满足行动确认：{len(confirmed)} 只",
        "- 次日真实开盘：等待",
        "",
        "## 关注股票",
        "",
    ]
    if candidates.empty:
        lines.append("本形成日没有满足当前关注条件的股票；系统没有为了凑数补充名单。")
    else:
        lines.extend(
            [
                "| 股票 | 入口 | 近5日收益 | 20日相对收益 | 成交比率 | 三项确认 |",
                "| --- | --- | ---: | ---: | ---: | --- |",
            ]
        )
        for row in candidates.itertuples(index=False):
            lines.append(
                "| "
                + " | ".join(
                    [
                        f"{_value(getattr(row, 'stock_name', None))}（{row.ts_code}）",
                        _value(getattr(row, "routes", None)),
                        _percent(getattr(row, "return_5d", None)),
                        _percent(getattr(row, "relative_return_20d", None)),
                        _value(getattr(row, "current_amount_ratio_20d", None)),
                        "满足" if bool(getattr(row, "action_confirmed", False)) else "不满足",
                    ]
                )
                + " |"
            )
    lines.extend(["", "## 满足行动确认", ""])
    if confirmed.empty:
        lines.append("本形成日行动确认对象为零。")
    else:
        lines.append("以下股票同时满足价格启动、相对市场走强和成交确认：")
        for row in confirmed.itertuples(index=False):
            lines.append(f"- {_value(getattr(row, 'stock_name', None))}（{row.ts_code}）")
    lines.extend(["", "## 个股证据与主要风险", ""])
    for row in candidates.itertuples(index=False):
        lines.extend(
            [
                f"### {_value(getattr(row, 'stock_name', None))}（{row.ts_code}）",
                "",
                f"- 市场：20 日上涨面 {_value(getattr(row, 'market_breadth_20d', None))}",
                f"- 热点：{_value(getattr(row, 'hotspot_group_name', None))}",
                f"- 公司：营收同比 {_value(getattr(row, 'tr_yoy', None))}，净利润同比 {_value(getattr(row, 'netprofit_yoy', None))}，扣非同比 {_value(getattr(row, 'dt_netprofit_yoy', None))}，经营现金流 {_value(getattr(row, 'n_cashflow_act', None))}",
                f"- 价格：近 5 日 {_percent(getattr(row, 'return_5d', None))}，20 日相对市场 {_percent(getattr(row, 'relative_return_20d', None))}，成交比率 {_value(getattr(row, 'current_amount_ratio_20d', None))}",
                f"- 主要风险：{_value(getattr(row, 'risk_notes', None))}",
                "",
            ]
        )
    lines.extend(
        [
            "## 未来状态",
            "",
            "未来结果尚未到达。形成记录未读取形成日之后的行情、财务、公告、板块或其他证据；2026-07-20 的真实开盘价到达前不会回填模拟价格。",
            "",
            "本报告仅用于规则冻结后的前瞻观察，不构成买卖建议。",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def render_entry_report(
    formation_date: str, entry_date: str, entries: pd.DataFrame
) -> str:
    lines = [
        f"# V3 前瞻观察真实开盘记录：{entry_date}",
        "",
        f"- 形成日：{formation_date}",
        f"- 行动对象：{len(entries)} 只",
        "",
        "本记录只追加真实下一交易日开盘和可执行状态，不修改形成证据。",
    ]
    for row in entries.itertuples(index=False):
        lines.append(
            f"- {row.ts_code}：{row.entry_status}，行动价 {_value(getattr(row, 'action_price', None))}"
        )
    return "\n".join(lines).rstrip() + "\n"


def render_snapshot_report(
    formation_date: str, as_of_date: str, horizon: int, snapshots: pd.DataFrame
) -> str:
    stage = "阶段快照" if horizon in (5, 10) else "完整窗口结果"
    return (
        f"# V3 前瞻观察{stage}：第 {horizon} 个交易日\n\n"
        f"- 形成日：{formation_date}\n"
        f"- 截止日：{as_of_date}\n"
        f"- 可执行项目：{len(snapshots)} 个\n\n"
        + ("第 5/10 日仅为阶段快照，不能作为 20/30 日最终验证。\n" if horizon in (5, 10) else "本窗口已经完整成熟。\n")
    )


__all__ = [
    "render_entry_report",
    "render_formation_report",
    "render_snapshot_report",
]
