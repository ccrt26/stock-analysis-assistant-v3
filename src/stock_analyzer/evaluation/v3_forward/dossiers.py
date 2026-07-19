from __future__ import annotations

import json
from typing import Any, Mapping

import pandas as pd

from stock_analyzer.evaluation.v3_forward.explanations import build_decision_cards
from stock_analyzer.evaluation.v3_forward.inputs import FormationInputs


DOSSIER_SCHEMA_VERSION = "v3-forward-research-dossier-02"

_FINANCIAL_FIELDS = (
    "tr_yoy",
    "netprofit_yoy",
    "dt_netprofit_yoy",
    "ocf_yoy",
    "eps",
    "grossprofit_margin",
    "netprofit_margin",
    "roe",
    "debt_to_assets",
    "current_ratio",
    "ocfps",
)
_TRADING_FIELDS = (
    "return_1d",
    "relative_return_1d",
    "return_5d",
    "relative_return_5d",
    "return_10d",
    "relative_return_10d",
    "return_20d",
    "relative_return_20d",
    "return_60d",
    "relative_return_60d",
    "realized_volatility_20d_annualized",
    "atr_ratio_20d",
    "price_location_60d",
    "average_amount_20d",
    "current_amount_ratio_20d",
    "recent_limit_up_count_5d",
    "pe_ttm",
    "pb",
    "pe_ttm_percentile_250d",
    "pb_percentile_250d",
    "valuation_observations_250d",
    "coverage_status",
    "valuation_data_status",
    "pe_percentile_status",
    "limitation_notes",
)
_DOSSIER_COLUMNS = (
    "formation_date",
    "rule_version",
    "schema_version",
    "ts_code",
    "stock_name",
    "company_name",
    "main_business",
    "company_introduction",
    "industry_l1_name",
    "routes",
    "hotspot_group_name",
    "business_composition_status",
    "summary_json",
    "industry_and_themes_json",
    "action_confirmation_json",
    "financial_history_json",
    "trading_metrics_json",
    "announcements_json",
    "evidence_matrix_json",
    "opposition_and_unknowns_json",
)

_GLOSSARY = (
    ("三项确认", "近5日收益为正、20日相对市场收益为正、成交比率不低于1三项同时满足；只确认当前量价状态。"),
    ("成交比率", "形成日成交额 ÷ 前20个交易日平均成交额；大于1表示当日成交比近期平均更活跃。"),
    ("相对收益", "个股同期收益减去市场基准同期收益，用于区分个股上涨与市场普涨。"),
    ("价格位置", "形成日价格在最近观察区间高低点之间的位置；接近1表示更靠近区间高位。"),
    ("波动率", "根据近期日收益计算并年化的价格波动程度；数值越高表示路径越不稳定。"),
    ("ATR", "平均真实波幅相对价格的比例，用来描述日常振幅，不直接预测方向。"),
    ("PE-TTM", "当前市值相对最近12个月盈利的倍数；亏损或利润波动大时解释力会下降。"),
    ("PB", "当前市值相对账面净资产的倍数；不同行业的合理区间不可直接类比。"),
    ("估值分位", "当前估值在自身历史样本中的位置；样本不足时只能作为有限参考。"),
    ("营收同比", "本报告期营业收入相对上年同期的变化率。"),
    ("扣非净利润", "剔除非经常性损益后的净利润，更接近持续经营结果，但仍需结合现金流。"),
    ("经营现金流", "经营活动带来的实际现金净额；单个季度可能受回款和付款节奏影响。"),
    ("毛利率", "营业收入扣除直接营业成本后的比例，反映产品或服务的基础盈利空间。"),
    ("净利率", "归属于利润相对收入的比例，受费用、税费和非经常项目共同影响。"),
    ("ROE", "净利润相对股东权益的收益水平；季度累计口径不能擅自当作全年水平。"),
    ("资产负债率", "总负债相对总资产的比例，只描述资本结构，不单独等同风险高低。"),
    ("流动比率", "流动资产相对流动负债的倍数，用于观察短期偿债覆盖；行业与经营模式不同，不能机械套统一阈值。"),
    ("每股经营现金流", "经营活动现金净额除以股本，用于把现金创造能力换算到每股口径。"),
)


def _value(value: Any) -> Any:
    if value is None or value is pd.NA:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return value


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _validate_visible(frame: pd.DataFrame, cutoff: pd.Timestamp, label: str) -> None:
    if frame.empty:
        return
    if "available_at" not in frame:
        raise ValueError(f"{label} lacks available_at")
    available = pd.to_datetime(frame["available_at"], utc=True, errors="raise")
    if available.isna().any() or (available > cutoff).any():
        raise ValueError(f"{label} exceeds dossier cutoff")


def _active_group_rows(inputs: FormationInputs, code: str) -> pd.DataFrame:
    memberships = inputs.memberships.copy()
    catalogs = inputs.sector_catalogs.copy()
    required_members = {
        "group_type",
        "group_code",
        "ts_code",
        "valid_from",
        "valid_to",
    }
    required_catalog = {"group_type", "group_code", "group_name", "level"}
    if not required_members <= set(memberships) or not required_catalog <= set(catalogs):
        return pd.DataFrame()
    formation = pd.Timestamp(inputs.formation_date)
    memberships["valid_from"] = pd.to_datetime(memberships["valid_from"], errors="coerce")
    memberships["valid_to"] = pd.to_datetime(memberships["valid_to"], errors="coerce")
    active = memberships[
        memberships["ts_code"].astype(str).eq(code)
        & (memberships["valid_from"] <= formation)
        & (memberships["valid_to"].isna() | (memberships["valid_to"] >= formation))
    ].copy()
    joined = active.merge(
        catalogs[["group_type", "group_code", "group_name", "level"]],
        on=["group_type", "group_code"],
        how="inner",
    )
    return joined.drop_duplicates(["group_type", "group_code", "ts_code"])


def _industry_and_themes(
    inputs: FormationInputs, code: str, industry: str, routes: str, hotspot: str | None
) -> dict[str, Any]:
    groups = _active_group_rows(inputs, code)
    themes = groups[groups.get("group_type", pd.Series(dtype=str)).astype(str).eq("theme")]
    hotspot_text = hotspot if hotspot and hotspot != "本地严格时点数据缺失" else None
    context = inputs.hotspots.copy()
    if not context.empty and "analysis_date" in context:
        context = context[
            pd.to_datetime(context["analysis_date"], errors="raise")
            .dt.date.eq(inputs.formation_date)
        ]
    eligibility = {"coverage_status", "breadth_5d", "relative_return_5d"}
    if not context.empty and eligibility <= set(context):
        context = context[
            context["coverage_status"].astype(str).str.startswith("complete")
            & (pd.to_numeric(context["breadth_5d"], errors="coerce") >= 0.50)
            & (pd.to_numeric(context["relative_return_5d"], errors="coerce") > 0)
        ].copy()
        sort_fields = [
            field
            for field in ("relative_return_20d", "breadth_5d", "turnover_share_change_5d")
            if field in context
        ]
        if sort_fields:
            context = context.sort_values(sort_fields, ascending=False, na_position="last")
        context = context.head(10)
    context_keys = set(
        zip(
            context.get("group_type", pd.Series(dtype=str)).astype(str),
            context.get("group_code", pd.Series(dtype=str)).astype(str),
        )
    )
    rows: list[dict[str, str]] = []
    for item in themes.to_dict(orient="records"):
        name = str(item["group_name"])
        group_key = (str(item["group_type"]), str(item["group_code"]))
        if hotspot_text and name == hotspot_text:
            evidence_role = "selection_relevant"
        elif group_key in context_keys:
            evidence_role = "same_day_hotspot_context"
        else:
            evidence_role = "index_membership_only"
        rows.append(
            {
                "code": str(item["group_code"]),
                "name": name,
                "level": str(item["level"]),
                "evidence_role": evidence_role,
            }
        )
    rows.sort(
        key=lambda row: (
            {
                "selection_relevant": 0,
                "same_day_hotspot_context": 1,
                "index_membership_only": 2,
            }[row["evidence_role"]],
            row["name"],
            row["code"],
        )
    )
    return {
        "industry_l1": industry,
        "routes": routes,
        "selection_hotspot": hotspot_text,
        "selection_hotspot_evidence": (
            "selection_relevant" if hotspot_text and "hotspot" in routes.split("|") else "not_applicable"
        ),
        "route_explanation": (
            "本次不是因热点入选；热点共同性不能作为本次入选理由。"
            if "hotspot" not in routes.split("|")
            else f"本次热点入口直接使用：{hotspot_text or '严格时点热点名称缺失'}。"
        ),
        "formal_theme_membership_count": len(rows),
        "formal_theme_memberships": rows[:6],
        "boundary": "正式指数或主题成员不等于业务收入证据；未结构化的市场叙事不写成公司事实。",
    }


def _latest_profiles(inputs: FormationInputs) -> dict[str, Mapping[str, Any]]:
    frame = inputs.company_profiles.copy()
    if frame.empty or "ts_code" not in frame:
        return {}
    order = [column for column in ("ts_code", "valid_from", "available_at", "revision_no") if column in frame]
    latest = frame.sort_values(order).drop_duplicates("ts_code", keep="last")
    return {str(row["ts_code"]): row for row in latest.to_dict(orient="records")}


def _normalized_history(
    frame: pd.DataFrame, code: str, cutoff: pd.Timestamp, label: str
) -> pd.DataFrame:
    _validate_visible(frame, cutoff, label)
    if frame.empty or not {"ts_code", "report_period"} <= set(frame):
        return pd.DataFrame()
    selected = frame[frame["ts_code"].astype(str).eq(code)].copy()
    if selected.empty:
        return selected
    selected["__period"] = pd.to_datetime(selected["report_period"], errors="raise")
    selected["__available"] = pd.to_datetime(selected["available_at"], utc=True, errors="raise")
    selected["__revision"] = pd.to_numeric(
        selected.get("revision_no", pd.Series(0, index=selected.index)), errors="coerce"
    ).fillna(0)
    return (
        selected.sort_values(["__period", "__available", "__revision"])
        .drop_duplicates("__period", keep="last")
        .sort_values("__period", ascending=False)
    )


def _financial_history(inputs: FormationInputs, code: str, cutoff: pd.Timestamp) -> list[dict[str, Any]]:
    financials = _normalized_history(inputs.financial_history, code, cutoff, "financial history")
    cashflows = _normalized_history(inputs.cashflow_history, code, cutoff, "cashflow history")
    cash_by_period = {
        pd.Timestamp(row["__period"]).date().isoformat(): _value(row.get("n_cashflow_act"))
        for row in cashflows.to_dict(orient="records")
    }
    rows: list[dict[str, Any]] = []
    for row in financials.head(5).to_dict(orient="records"):
        period = pd.Timestamp(row["__period"]).date().isoformat()
        item = {"report_period": period}
        for field in _FINANCIAL_FIELDS:
            item[field] = _value(row.get(field))
        item["n_cashflow_act"] = cash_by_period.get(period)
        rows.append(item)
    return rows


def _trading_metrics(inputs: FormationInputs, code: str) -> dict[str, Any]:
    frame = inputs.stocks.copy()
    if frame.empty or "ts_code" not in frame:
        return {field: None for field in _TRADING_FIELDS}
    selected = frame[frame["ts_code"].astype(str).eq(code)].copy()
    if "analysis_date" in selected:
        selected = selected[
            pd.to_datetime(selected["analysis_date"], errors="raise").dt.date.eq(inputs.formation_date)
        ]
    if selected.empty:
        return {field: None for field in _TRADING_FIELDS}
    if len(selected) != 1:
        raise ValueError(f"stock trading context is not unique for {code}")
    row = selected.iloc[0]
    return {field: _value(row.get(field)) for field in _TRADING_FIELDS}


def _action_confirmation(card: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "all_three_satisfied": bool(
            card.get("confirm_return_5d_positive")
            and card.get("confirm_relative_return_20d_positive")
            and card.get("confirm_amount_ratio_20d")
        ),
        "items": [
            {
                "name": "近5日收益为正",
                "raw_value": _value(card.get("return_5d")),
                "threshold": "> 0",
                "satisfied": bool(card.get("confirm_return_5d_positive")),
                "meaning": "近期价格方向为正。",
            },
            {
                "name": "20日相对市场收益为正",
                "raw_value": _value(card.get("relative_return_20d")),
                "threshold": "> 0",
                "satisfied": bool(card.get("confirm_relative_return_20d_positive")),
                "meaning": "同期表现强于市场基准。",
            },
            {
                "name": "成交比率不低于1",
                "raw_value": _value(card.get("current_amount_ratio_20d")),
                "threshold": ">= 1",
                "satisfied": bool(card.get("confirm_amount_ratio_20d")),
                "meaning": "形成日成交额不低于前20日平均成交额。",
            },
        ],
        "boundary": "三项只确认当前量价状态，不衡量公司长期质量，也不构成买卖指令。",
    }


def _summary(card: Mapping[str, Any], theme_info: Mapping[str, Any]) -> dict[str, Any]:
    opposition = str(card.get("opposition_evidence", ""))
    missing = str(card.get("missing_confirmations", ""))
    route_names = {
        "price": "价格路线",
        "hotspot": "热点路线",
        "earnings": "业绩路线",
    }
    routes = "、".join(
        route_names.get(item, item)
        for item in str(card["routes"]).split("|")
        if item
    )
    return {
        "30秒读懂": (
            f"{card['stock_name']}（{card['ts_code']}）属于{card['industry_l1_name']}，"
            f"主营{card['main_business']}；本次由{routes}进入观察并满足三项量价确认。"
        ),
        "why_research_now": str(card.get("selection_explanation", "")),
        "selection_hotspot": theme_info.get("selection_hotspot"),
        "largest_counterevidence": opposition,
        "largest_unknown": missing,
        "boundary": "档案解释为什么值得继续研究，不构成买卖指令或收益承诺。",
    }


def build_research_dossiers(
    payload: Mapping[str, Any], candidates: pd.DataFrame, inputs: FormationInputs
) -> pd.DataFrame:
    cutoff = pd.Timestamp(payload.get("data_cutoff_at", inputs.cutoff))
    if cutoff.tzinfo is None:
        raise ValueError("dossier cutoff must include timezone")
    cutoff = cutoff.tz_convert("UTC")
    cards = build_decision_cards(payload, candidates, inputs)
    if cards.empty:
        return pd.DataFrame(columns=_DOSSIER_COLUMNS)
    profiles = _latest_profiles(inputs)
    rows: list[dict[str, Any]] = []
    for card in cards.to_dict(orient="records"):
        code = str(card["ts_code"])
        routes = str(card.get("routes", ""))
        hotspot_raw = _value(card.get("hotspot_group_name"))
        hotspot = str(hotspot_raw) if hotspot_raw else None
        theme_info = _industry_and_themes(
            inputs,
            code,
            str(card.get("industry_l1_name", "本地严格时点数据缺失")),
            routes,
            hotspot,
        )
        profile = profiles.get(code, {})
        announcements = json.loads(str(card.get("recent_announcements_json", "[]")))
        history = _financial_history(inputs, code, cutoff)
        metrics = _trading_metrics(inputs, code)
        evidence = {
            "已确认事实": [
                f"公司主营：{card.get('main_business')}",
                f"一级行业：{card.get('industry_l1_name')}",
                f"发现路线：{routes}",
                "三项动作确认同时满足",
            ],
            "谨慎解释": [
                "相对收益与成交活跃同时为正，说明形成日量价关注度较高；不能据此推断后续收益。",
                "多期同比指标可用于观察方向；季度、半年度和年度累计口径不可直接当作等长周期比较。",
            ],
            "当前未知": [
                "分业务收入与毛利构成",
                "可复核的客户收入贡献和市场份额",
                "公告事项的最终收入、利润或订单影响",
                "严格同口径的同业估值比较",
            ],
        }
        opposition = {
            "opposition_evidence": str(card.get("opposition_evidence", "")),
            "missing_confirmations": str(card.get("missing_confirmations", "")),
            "next_facts_to_verify": [
                "下一真实交易日开盘可执行性",
                "后续5/10/20/30交易日真实路径",
                "新公告是否提供可结构化的公司级经济证据",
            ],
        }
        rows.append(
            {
                "formation_date": str(payload["formation_date"]),
                "rule_version": str(payload["rule_version"]),
                "schema_version": DOSSIER_SCHEMA_VERSION,
                "ts_code": code,
                "stock_name": str(card["stock_name"]),
                "company_name": str(card["company_name"]),
                "main_business": str(card["main_business"]),
                "company_introduction": str(
                    profile.get("introduction", card.get("company_introduction", "本地严格时点数据缺失"))
                ),
                "industry_l1_name": str(card["industry_l1_name"]),
                "routes": routes,
                "hotspot_group_name": hotspot,
                "business_composition_status": (
                    "本地严格时点快照没有可复核的分业务收入与毛利构成，因此不编写业务占比。"
                ),
                "summary_json": _stable_json(_summary(card, theme_info)),
                "industry_and_themes_json": _stable_json(theme_info),
                "action_confirmation_json": _stable_json(_action_confirmation(card)),
                "financial_history_json": _stable_json(history),
                "trading_metrics_json": _stable_json(metrics),
                "announcements_json": _stable_json(announcements),
                "evidence_matrix_json": _stable_json(evidence),
                "opposition_and_unknowns_json": _stable_json(opposition),
            }
        )
    result = pd.DataFrame(rows, columns=_DOSSIER_COLUMNS)
    if result.duplicated("ts_code").any():
        raise ValueError("dossier contains duplicate stock codes")
    return result


def _pct(value: Any, *, ratio: bool = True) -> str:
    raw = _value(value)
    if raw is None:
        return "本地严格时点数据缺失"
    number = float(raw) * (100.0 if ratio else 1.0)
    return f"{number:.2f}%"


def _num(value: Any, digits: int = 2) -> str:
    raw = _value(value)
    if raw is None:
        return "本地严格时点数据缺失"
    return f"{float(raw):,.{digits}f}"


def _financial_table(history: list[dict[str, Any]]) -> list[str]:
    lines = [
        "| 报告期 | 营收同比 | 净利润同比 | 扣非同比 | 经营现金流同比 | EPS | 毛利率 | 净利率 | ROE | 资产负债率 | 流动比率 | 每股经营现金流 | 经营现金流 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in history:
        lines.append(
            "| {period} | {tr} | {profit} | {deduct} | {ocf} | {eps} | {gross} | {net} | {roe} | {debt} | {current} | {ocfps} | {cash} |".format(
                period=row["report_period"],
                tr=_pct(row.get("tr_yoy"), ratio=False),
                profit=_pct(row.get("netprofit_yoy"), ratio=False),
                deduct=_pct(row.get("dt_netprofit_yoy"), ratio=False),
                ocf=_pct(row.get("ocf_yoy"), ratio=False),
                eps=_num(row.get("eps")),
                gross=_pct(row.get("grossprofit_margin"), ratio=False),
                net=_pct(row.get("netprofit_margin"), ratio=False),
                roe=_pct(row.get("roe"), ratio=False),
                debt=_pct(row.get("debt_to_assets"), ratio=False),
                current=_num(row.get("current_ratio")),
                ocfps=_num(row.get("ocfps")),
                cash=_num(row.get("n_cashflow_act"), 0),
            )
        )
    if not history:
        lines.append("| 本地严格时点数据缺失 | — | — | — | — | — | — | — | — | — | — | — | — |")
    return lines


def _render_one(row: Mapping[str, Any], payload: Mapping[str, Any]) -> str:
    summary = json.loads(str(row["summary_json"]))
    themes = json.loads(str(row["industry_and_themes_json"]))
    action = json.loads(str(row["action_confirmation_json"]))
    history = json.loads(str(row["financial_history_json"]))
    metrics = json.loads(str(row["trading_metrics_json"]))
    announcements = json.loads(str(row["announcements_json"]))
    evidence = json.loads(str(row["evidence_matrix_json"]))
    opposition = json.loads(str(row["opposition_and_unknowns_json"]))
    lines = [
        f"# {row['stock_name']}（{row['ts_code']}）研究档案",
        "",
        f"- 形成日：{payload['formation_date']}",
        f"- 数据截止：{payload.get('data_cutoff_at', '本地严格时点数据缺失')}",
        f"- 选股规则：{payload['rule_version']}",
        f"- 档案版本：{DOSSIER_SCHEMA_VERSION}",
        "- 用途：解释为何值得继续研究，不构成买卖指令或收益承诺。",
        "",
        "## 30秒读懂",
        "",
        summary["30秒读懂"],
        "",
        f"- 为什么现在看：{summary['why_research_now']}",
        f"- 当前主要反对证据：{summary['largest_counterevidence']}",
        f"- 当前最大缺口：{summary['largest_unknown']}",
        "",
        "## 一、公司与业务",
        "",
        f"- 公司全称：{row['company_name']}",
        f"- 一级行业：{row['industry_l1_name']}",
        f"- 主营业务：{row['main_business']}",
        f"- 公司介绍：{row['company_introduction']}",
        f"- 业务构成边界：{row['business_composition_status']}",
        "",
        "## 二、行业、板块与概念",
        "",
        f"- 一级行业：{themes['industry_l1']}",
        f"- 本次发现路线：{themes['routes']}",
        f"- 本次选择热点：{themes['selection_hotspot'] or '无'}",
        f"- 路线说明：{themes['route_explanation']}",
        f"- 正式主题成员总数：{themes['formal_theme_membership_count']}",
    ]
    for item in themes["formal_theme_memberships"]:
        role = {
            "selection_relevant": "本次选择直接相关",
            "same_day_hotspot_context": "同日热点背景，非本次直接入选组",
            "index_membership_only": "仅正式成员事实",
        }[item["evidence_role"]]
        lines.append(f"  - {item['name']}（{item['code']}）：{role}")
    lines.extend(["", f"> 证据边界：{themes['boundary']}", "", "## 三、为什么进入名单、为什么此刻确认", ""])
    lines.append(f"- 形成路线：{row['routes']}")
    for item in action["items"]:
        value = _pct(item["raw_value"]) if "收益" in item["name"] else _num(item["raw_value"])
        lines.append(
            f"- {item['name']}：原始值 {value}，阈值 {item['threshold']}，结果 {'满足' if item['satisfied'] else '不满足'}。{item['meaning']}"
        )
    lines.extend(["", f"> {action['boundary']}", "", "## 四、多报告期业绩与财务质量", ""])
    lines.extend(_financial_table(history))
    lines.extend(
        [
            "",
            "> 口径提醒：季度、半年度和年度累计指标不可擅自当作等长周期绝对值比较；同比增速还可能受低基数影响。",
            "",
            "## 五、交易、风险与估值指标",
            "",
            "| 指标 | 当前值 |",
            "| --- | ---: |",
            f"| 1日 / 5日 / 10日 / 20日 / 60日收益 | {_pct(metrics['return_1d'])} / {_pct(metrics['return_5d'])} / {_pct(metrics['return_10d'])} / {_pct(metrics['return_20d'])} / {_pct(metrics['return_60d'])} |",
            f"| 20日相对市场收益 | {_pct(metrics['relative_return_20d'])} |",
            f"| 20日年化实现波动率 | {_pct(metrics['realized_volatility_20d_annualized'])} |",
            f"| 20日 ATR 比率 | {_pct(metrics['atr_ratio_20d'])} |",
            f"| 60日价格位置 | {_pct(metrics['price_location_60d'])} |",
            f"| 20日平均成交额 | {_num(metrics['average_amount_20d'], 0)} 元 |",
            f"| 成交比率 | {_num(metrics['current_amount_ratio_20d'])} |",
            f"| 近5日涨停次数 | {_num(metrics['recent_limit_up_count_5d'], 0)} |",
            f"| PE-TTM / PB | {_num(metrics['pe_ttm'])} / {_num(metrics['pb'])} |",
            f"| PE / PB 250日历史分位 | {_pct(metrics['pe_ttm_percentile_250d'])} / {_pct(metrics['pb_percentile_250d'])} |",
            f"| 250日估值样本数 | {_num(metrics['valuation_observations_250d'], 0)} |",
            f"| 数据限制 | {metrics['limitation_notes'] or '未声明额外限制'} |",
            "",
            "## 六、形成日前正式公告",
            "",
        ]
    )
    if announcements:
        for item in announcements:
            event_types = "、".join(item.get("event_types", [])) or "未分类"
            lines.append(
                f"- [{item['title']}]({item['url']})；可见时间 {item['available_at']}；事件类型 {event_types}"
            )
    else:
        lines.append("- 本地严格时点数据没有筛选出近期决策相关公告。")
    lines.extend(
        [
            "",
            "> 公告标题只证明正式公告存在；原文经济影响未结构化时，不推断收入、利润、订单金额或成功概率。",
            "",
            "## 七、证据矩阵",
            "",
        ]
    )
    for heading in ("已确认事实", "谨慎解释", "当前未知"):
        lines.append(f"### {heading}")
        lines.append("")
        for item in evidence[heading]:
            lines.append(f"- {item}")
        lines.append("")
    lines.extend(
        [
            "## 八、反对证据与下一步验证",
            "",
            f"- 反对证据：{opposition['opposition_evidence']}",
            f"- 尚缺确认：{opposition['missing_confirmations']}",
            "- 下一步只验证以下事实：",
        ]
    )
    for item in opposition["next_facts_to_verify"]:
        lines.append(f"  - {item}")
    lines.extend(["", "## 九、术语词典", ""])
    for term, explanation in _GLOSSARY:
        lines.append(f"- {term}：{explanation}")
    lines.extend(["", "---", "", "本档案是严格时点研究材料，不是收益承诺或交易指令。", ""])
    return "\n".join(lines)


def render_research_dossiers(
    payload: Mapping[str, Any], dossiers: pd.DataFrame
) -> tuple[str, dict[str, str]]:
    if dossiers.empty:
        report = (
            f"# V3 动作确认研究档案：{payload['formation_date']}\n\n"
            "本形成日没有动作确认对象，因此没有单股研究档案。\n"
        )
        return report, {}
    per_stock = {
        str(row["ts_code"]): _render_one(row, payload)
        for row in dossiers.to_dict(orient="records")
    }
    header = [
        f"# V3 动作确认研究档案：{payload['formation_date']}",
        "",
        f"- 选股规则：{payload['rule_version']}",
        f"- 档案版本：{DOSSIER_SCHEMA_VERSION}",
        f"- 档案数量：{len(per_stock)}",
        "- 本报告只解释已有动作确认对象，不改变名单或确认结果。",
        "",
    ]
    combined = "\n".join(header) + "\n\n".join(per_stock.values())
    return combined, per_stock


__all__ = [
    "DOSSIER_SCHEMA_VERSION",
    "build_research_dossiers",
    "render_research_dossiers",
]
