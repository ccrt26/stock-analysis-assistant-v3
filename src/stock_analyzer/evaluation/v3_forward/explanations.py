from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from typing import Any, Mapping

import pandas as pd

from stock_analyzer.evaluation.v3_forward.inputs import FormationInputs


_RELEVANT_TITLE_KEYWORDS = (
    "业绩",
    "注册证",
    "批准",
    "目录",
    "临床",
    "合同",
    "中标",
    "减持",
    "处罚",
    "立案",
    "诉讼",
    "问询",
    "终止",
)
_COMPANY_DRIVER_KEYWORDS = (
    "业绩",
    "注册证",
    "批准",
    "目录",
    "临床",
    "合同",
    "中标",
)
_CARD_COLUMNS = (
    "formation_date",
    "rule_version",
    "ts_code",
    "stock_name",
    "company_name",
    "main_business",
    "company_introduction",
    "industry_l1_name",
    "routes",
    "hotspot_group_name",
    "company_driver_state",
    "selection_explanation",
    "return_5d",
    "return_20d",
    "relative_return_20d",
    "current_amount_ratio_20d",
    "price_location_60d",
    "confirm_return_5d_positive",
    "confirm_relative_return_20d_positive",
    "confirm_amount_ratio_20d",
    "market_breadth_20d",
    "report_period",
    "tr_yoy",
    "netprofit_yoy",
    "dt_netprofit_yoy",
    "ocf_yoy",
    "n_cashflow_act",
    "pe_ttm",
    "pb",
    "recent_announcements_json",
    "company_catalyst_status",
    "supporting_evidence",
    "opposition_evidence",
    "missing_confirmations",
    "conclusion_boundary",
)


def _clean_text(value: Any, *, limit: int | None = None) -> str:
    if value is None or value is pd.NA:
        return "本地严格时点数据缺失"
    try:
        if pd.isna(value):
            return "本地严格时点数据缺失"
    except (TypeError, ValueError):
        pass
    text = re.sub(r"\s+", " ", str(value)).strip()
    if not text:
        return "本地严格时点数据缺失"
    if limit is not None and len(text) > limit:
        return text[:limit].rstrip() + "……"
    return text


def _visible_cutoff(payload: Mapping[str, Any], inputs: FormationInputs) -> pd.Timestamp:
    value = payload.get("data_cutoff_at", inputs.cutoff)
    cutoff = pd.Timestamp(value)
    if cutoff.tzinfo is None:
        raise ValueError("decision-card cutoff must include timezone")
    return cutoff.tz_convert("UTC")


def _validate_visible(frame: pd.DataFrame, cutoff: pd.Timestamp, label: str) -> None:
    if frame.empty:
        return
    if "available_at" not in frame:
        raise ValueError(f"{label} lacks available_at")
    visible = pd.to_datetime(frame["available_at"], utc=True, errors="raise")
    if visible.isna().any() or (visible > cutoff).any():
        raise ValueError(f"{label} exceeds decision-card cutoff")


def _industry_map(inputs: FormationInputs) -> dict[str, str]:
    catalogs = inputs.sector_catalogs.copy()
    memberships = inputs.memberships.copy()
    if catalogs.empty or memberships.empty:
        return {}
    required_catalog = {"group_type", "group_code", "group_name", "level"}
    required_member = {"group_type", "group_code", "ts_code", "valid_from", "valid_to"}
    if not required_catalog <= set(catalogs) or not required_member <= set(memberships):
        return {}
    formation = pd.Timestamp(inputs.formation_date)
    memberships["valid_from"] = pd.to_datetime(memberships["valid_from"], errors="coerce")
    memberships["valid_to"] = pd.to_datetime(memberships["valid_to"], errors="coerce")
    active = memberships[
        memberships["group_type"].astype(str).eq("industry")
        & (memberships["valid_from"] <= formation)
        & (memberships["valid_to"].isna() | (memberships["valid_to"] >= formation))
    ].copy()
    l1 = catalogs[
        catalogs["group_type"].astype(str).eq("industry")
        & catalogs["level"].astype(str).str.upper().eq("L1")
    ][["group_code", "group_name"]].drop_duplicates("group_code")
    joined = active.merge(l1, on="group_code", how="inner")
    if joined.empty:
        return {}
    joined = joined.sort_values(["ts_code", "group_code"]).drop_duplicates("ts_code")
    return joined.set_index("ts_code")["group_name"].astype(str).to_dict()


def _latest_profiles(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "ts_code" not in frame:
        return pd.DataFrame()
    prepared = frame.copy()
    order = [
        column
        for column in ("ts_code", "valid_from", "available_at", "revision_no")
        if column in prepared
    ]
    return prepared.sort_values(order).drop_duplicates("ts_code", keep="last")


def _event_types(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if value is None or value is pd.NA:
        return []
    try:
        if pd.isna(value):
            return []
    except (TypeError, ValueError):
        pass
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return [value] if value.strip() else []
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
    return []


def _relevant_announcements(
    frame: pd.DataFrame,
    code: str,
    cutoff: pd.Timestamp,
) -> list[dict[str, Any]]:
    if frame.empty or "ts_code" not in frame:
        return []
    prepared = frame[frame["ts_code"].astype(str).eq(str(code))].copy()
    if prepared.empty:
        return []
    prepared["__available"] = pd.to_datetime(
        prepared["available_at"], utc=True, errors="raise"
    )
    lower = cutoff - pd.Timedelta(days=120)
    prepared = prepared[
        (prepared["__available"] >= lower) & (prepared["__available"] <= cutoff)
    ].copy()
    rows: list[dict[str, Any]] = []
    for row in prepared.to_dict(orient="records"):
        title = _clean_text(row.get("title"))
        event_types = _event_types(row.get("candidate_event_types"))
        keyword_match = any(keyword in title for keyword in _RELEVANT_TITLE_KEYWORDS)
        if not event_types and not keyword_match:
            continue
        rows.append(
            {
                "title": title,
                "url": _clean_text(row.get("url")),
                "available_at": pd.Timestamp(row["__available"]).isoformat(),
                "event_types": event_types,
                "__priority": 2 if event_types else 1,
            }
        )
    rows.sort(
        key=lambda row: (int(row["__priority"]), str(row["available_at"])),
        reverse=True,
    )
    for row in rows:
        row.pop("__priority", None)
    return rows[:5]


def _value(row: Mapping[str, Any], field: str) -> Any:
    value = row.get(field)
    if value is None or value is pd.NA:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _selection_explanation(row: Mapping[str, Any]) -> str:
    routes = [item for item in str(row.get("routes", "")).split("|") if item]
    parts: list[str] = []
    if "hotspot" in routes:
        parts.append(f"热点入口：{_clean_text(row.get('hotspot_group_name'))}")
    if "earnings" in routes:
        parts.append("业绩入口：形成日可见的收入、利润和现金证据进入公司比较路线")
    if "price" in routes:
        parts.append(
            "价格入口：20日相对市场走强、价格位置和成交活跃度达到召回条件"
        )
    return "；".join(parts) if parts else "形成入口缺失，不能解释入选原因"


def _supporting_evidence(row: Mapping[str, Any]) -> str:
    parts = [
        f"近5日收益 {_pct(row.get('return_5d'))}",
        f"20日相对收益 {_pct(row.get('relative_return_20d'))}",
        f"成交比率 {_number(row.get('current_amount_ratio_20d'))}",
    ]
    if _value(row, "tr_yoy") is not None:
        parts.append(f"营收同比 {_number(row.get('tr_yoy'))}%")
    if _value(row, "netprofit_yoy") is not None:
        parts.append(f"净利润同比 {_number(row.get('netprofit_yoy'))}%")
    return "；".join(parts)


def _opposition_evidence(
    row: Mapping[str, Any], announcements: list[dict[str, Any]]
) -> str:
    parts: list[str] = []
    risk = _clean_text(row.get("risk_notes"))
    if risk != "本地严格时点数据缺失":
        parts.append(risk)
    cash = _value(row, "n_cashflow_act")
    if cash is not None and float(cash) < 0 and "经营活动现金流为负" not in "；".join(parts):
        parts.append("经营活动现金流为负")
    if any(
        "shareholder_reduction" in item.get("event_types", [])
        for item in announcements
    ):
        parts.append("形成日前存在股东减持类公告，需核对供给压力和实施范围")
    return "；".join(dict.fromkeys(parts)) or "未发现可统一否决的形成日事实，仍存在市场与个股不确定性"


def _missing_confirmations(
    row: Mapping[str, Any], announcements: list[dict[str, Any]]
) -> tuple[str, str]:
    driver_announcements = [
        item
        for item in announcements
        if any(keyword in str(item.get("title", "")) for keyword in _COMPANY_DRIVER_KEYWORDS)
    ]
    missing: list[str] = []
    routes = str(row.get("routes", ""))
    if "hotspot" not in routes:
        missing.append("当前没有热点共同性入口支持")
    if str(row.get("company_driver_state", "")) != "confirmed":
        missing.append("公司财务一致性尚未完整确认")
    if not driver_announcements:
        missing.append("未发现形成日前可直接解释当前上涨的新公司级公告驱动")
    missing.append("下一交易日真实开盘可执行性和未来5/10/20/30日路径尚未到达")
    catalyst = (
        "存在形成日前的正式公司公告；自动卡片只确认公告存在，经济影响仍需阅读原文"
        if driver_announcements
        else "未发现形成日前的新公司级驱动，当前确认主要来自量价或热点"
    )
    return catalyst, "；".join(missing)


def build_decision_cards(
    payload: Mapping[str, Any],
    candidates: pd.DataFrame,
    inputs: FormationInputs,
) -> pd.DataFrame:
    cutoff = _visible_cutoff(payload, inputs)
    _validate_visible(inputs.company_profiles, cutoff, "company profiles")
    _validate_visible(inputs.announcements, cutoff, "announcements")
    confirmed = candidates[
        candidates.get("action_confirmed", pd.Series(False, index=candidates.index))
        .fillna(False)
        .astype(bool)
    ].copy()
    if confirmed.empty:
        return pd.DataFrame(columns=_CARD_COLUMNS)
    profiles = _latest_profiles(inputs.company_profiles)
    profile_by_code = (
        profiles.set_index("ts_code", drop=False)
        if not profiles.empty and "ts_code" in profiles
        else pd.DataFrame()
    )
    industries = _industry_map(inputs)
    rows: list[dict[str, Any]] = []
    for candidate in confirmed.to_dict(orient="records"):
        code = str(candidate["ts_code"])
        profile: Mapping[str, Any] = {}
        if not profile_by_code.empty and code in profile_by_code.index:
            value = profile_by_code.loc[code]
            profile = value.iloc[-1] if isinstance(value, pd.DataFrame) else value
        announcements = _relevant_announcements(inputs.announcements, code, cutoff)
        catalyst, missing = _missing_confirmations(candidate, announcements)
        rows.append(
            {
                "formation_date": str(payload["formation_date"]),
                "rule_version": str(payload["rule_version"]),
                "ts_code": code,
                "stock_name": _clean_text(candidate.get("stock_name")),
                "company_name": _clean_text(profile.get("com_name")),
                "main_business": _clean_text(profile.get("main_business")),
                "company_introduction": _clean_text(
                    profile.get("introduction"), limit=600
                ),
                "industry_l1_name": industries.get(
                    code, "本地严格时点数据缺失"
                ),
                "routes": _clean_text(candidate.get("routes")),
                "hotspot_group_name": _clean_text(
                    candidate.get("hotspot_group_name")
                ),
                "company_driver_state": _clean_text(
                    candidate.get("company_driver_state")
                ),
                "selection_explanation": _selection_explanation(candidate),
                "return_5d": _value(candidate, "return_5d"),
                "return_20d": _value(candidate, "return_20d"),
                "relative_return_20d": _value(candidate, "relative_return_20d"),
                "current_amount_ratio_20d": _value(
                    candidate, "current_amount_ratio_20d"
                ),
                "price_location_60d": _value(candidate, "price_location_60d"),
                "confirm_return_5d_positive": bool(
                    candidate.get("confirm_return_5d_positive", False)
                ),
                "confirm_relative_return_20d_positive": bool(
                    candidate.get("confirm_relative_return_20d_positive", False)
                ),
                "confirm_amount_ratio_20d": bool(
                    candidate.get("confirm_amount_ratio_20d", False)
                ),
                "market_breadth_20d": _value(candidate, "market_breadth_20d"),
                "report_period": _clean_text(candidate.get("report_period")),
                "tr_yoy": _value(candidate, "tr_yoy"),
                "netprofit_yoy": _value(candidate, "netprofit_yoy"),
                "dt_netprofit_yoy": _value(candidate, "dt_netprofit_yoy"),
                "ocf_yoy": _value(candidate, "ocf_yoy"),
                "n_cashflow_act": _value(candidate, "n_cashflow_act"),
                "pe_ttm": _value(candidate, "pe_ttm"),
                "pb": _value(candidate, "pb"),
                "recent_announcements_json": json.dumps(
                    announcements,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "company_catalyst_status": catalyst,
                "supporting_evidence": _supporting_evidence(candidate),
                "opposition_evidence": _opposition_evidence(
                    candidate, announcements
                ),
                "missing_confirmations": missing,
                "conclusion_boundary": (
                    "动作确认不是自动买入、收益承诺、仓位建议或自动交易指令"
                ),
            }
        )
    return pd.DataFrame(rows, columns=_CARD_COLUMNS)


def _number(value: Any) -> str:
    try:
        if value is None or pd.isna(value):
            return "缺失"
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return "缺失"


def _pct(value: Any) -> str:
    try:
        if value is None or pd.isna(value):
            return "缺失"
        return f"{float(value):.2%}"
    except (TypeError, ValueError):
        return "缺失"


def _passed(value: Any) -> str:
    return "满足" if bool(value) else "不满足"


def render_decision_cards(
    payload: Mapping[str, Any], cards: pd.DataFrame
) -> str:
    lines = [
        f"# V3 前瞻观察详细决策卡：{payload['formation_date']}",
        "",
        f"- 规则版本：{payload['rule_version']}",
        f"- 数据截止：{payload.get('data_cutoff_at', '缺失')}",
        f"- 动作确认对象：{len(cards)} 只",
        "- 本卡解释为什么现在值得重点研究，不构成买入建议。",
        "",
    ]
    if cards.empty:
        lines.extend(
            [
                "## 今日状态",
                "",
                "今日没有动作确认对象，因此没有生成个股详细卡。",
            ]
        )
        return "\n".join(lines).rstrip() + "\n"
    for card in cards.to_dict(orient="records"):
        lines.extend(
            [
                f"## {card['stock_name']}（{card['ts_code']}）",
                "",
                "### 这是什么公司",
                "",
                f"- 公司全称：{card['company_name']}",
                f"- 一级行业：{card['industry_l1_name']}",
                f"- 主营业务：{card['main_business']}",
                f"- 公司介绍：{card['company_introduction']}",
                "",
                "### 为什么进入关注名单",
                "",
                f"- 形成入口：{card['routes']}",
                f"- 入选解释：{card['selection_explanation']}",
                f"- 热点：{card['hotspot_group_name']}",
                f"- 公司证据状态：{card['company_driver_state']}",
                "",
                "### 为什么现在被动作确认",
                "",
                f"- 近5日收益大于0：{_pct(card['return_5d'])}，{_passed(card['confirm_return_5d_positive'])}",
                f"- 20日相对市场收益大于0：{_pct(card['relative_return_20d'])}，{_passed(card['confirm_relative_return_20d_positive'])}",
                f"- 成交比率不低于1：{_number(card['current_amount_ratio_20d'])}，{_passed(card['confirm_amount_ratio_20d'])}",
                f"- 支持证据：{card['supporting_evidence']}",
                "",
                "### 市场与风险簇",
                "",
                f"- 全市场20日上涨面：{_pct(card['market_breadth_20d'])}",
                f"- 一级行业：{card['industry_l1_name']}",
                f"- 热点共同性：{card['hotspot_group_name']}",
                "",
                "### 经营与财务",
                "",
                f"- 报告期：{card['report_period']}",
                f"- 营收同比：{_number(card['tr_yoy'])}%",
                f"- 净利润同比：{_number(card['netprofit_yoy'])}%",
                f"- 扣非净利润同比：{_number(card['dt_netprofit_yoy'])}%",
                f"- 经营现金流同比：{_number(card['ocf_yoy'])}%",
                f"- 经营活动现金流：{_number(card['n_cashflow_act'])} 元",
                "",
                "### 估值与交易阶段",
                "",
                f"- PE-TTM：{_number(card['pe_ttm'])}",
                f"- PB：{_number(card['pb'])}",
                f"- 60日价格位置：{_pct(card['price_location_60d'])}",
                f"- 近5日收益：{_pct(card['return_5d'])}",
                f"- 近20日收益：{_pct(card['return_20d'])}",
                f"- 20日相对市场收益：{_pct(card['relative_return_20d'])}",
                f"- 成交比率：{_number(card['current_amount_ratio_20d'])}",
                "",
                "### 形成日前正式公告",
                "",
                f"- 公司级驱动状态：{card['company_catalyst_status']}",
            ]
        )
        announcements = json.loads(card["recent_announcements_json"])
        if announcements:
            for item in announcements:
                event_types = "、".join(item.get("event_types", [])) or "未分类"
                lines.append(
                    f"- [{item['title']}]({item['url']})"
                    f"；可见时间 {item['available_at']}；事件类型 {event_types}"
                )
        else:
            lines.append("- 形成日前120日内未检出需要优先展示的正式公告。")
        lines.extend(
            [
                "",
                "### 反对证据与不确定性",
                "",
                f"- {card['opposition_evidence']}",
                "",
                "### 还缺什么确认",
                "",
                f"- {card['missing_confirmations']}",
                "",
                "### 结论边界",
                "",
                f"- {card['conclusion_boundary']}。",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


__all__ = ["build_decision_cards", "render_decision_cards"]

