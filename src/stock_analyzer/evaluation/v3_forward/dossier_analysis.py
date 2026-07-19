from __future__ import annotations

from typing import Any, Mapping, Sequence


def _number(value: Any, digits: int = 2) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def _pct(value: Any) -> str:
    number = _number(value, 6)
    return "无法确认" if number is None else f"{abs(number) * 100:.2f}%"


def _multiple(value: Any) -> str:
    number = _number(value, 4)
    return "无法确认" if number is None else f"{number:.2f}倍"


def _section(
    *,
    headline: str,
    meaning: str,
    selection_link: str,
    counterpoint: str,
    boundary: str,
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "headline": headline,
        "meaning": meaning,
        "selection_link": selection_link,
        "counterpoint": counterpoint,
        "boundary": boundary,
        "evidence": dict(evidence),
    }


def _company_analysis(
    card: Mapping[str, Any], supplements: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    business = str(card.get("main_business") or "主营业务尚未确认")
    if "临床试验现场管理" in business:
        headline = "这是一家临床试验执行服务商，不是药品生产商。"
        meaning = (
            "公司主要替药企、医疗器械企业等申办方组织和执行临床试验现场工作；"
            "其经营更依赖临床项目数量、执行进度和客户研发活动，而不是某一种药品销量。"
        )
    elif "药品" in business and any(word in business for word in ("研发", "生产", "销售")):
        headline = "这是一家直接从事药品研发、生产和销售的医药企业。"
        meaning = "公司经营结果与产品销售、研发成果、注册进展及渠道需求直接相关。"
    else:
        headline = f"公司的严格主营事实是：{business}。"
        meaning = "当前只能依据公司正式画像理解其经营活动，不扩写未结构化的业务模式。"
    categories = {
        str(item.get("fact_category")) for item in supplements if item.get("fact_category")
    }
    supplemented = [
        str(item.get("fact_text")).rstrip("。；; ")
        for item in supplements
        if item.get("fact_text")
    ]
    if supplemented:
        meaning += " 官方资料补充确认：" + "；".join(supplemented) + "。"
    if "revenue_composition" in categories and "customer_structure" in categories:
        counterpoint = "收入构成和前五大客户占比已经补足；主要矛盾转为业务集中度与客户集中度是否会放大经营波动。"
    elif "revenue_composition" in categories:
        counterpoint = "主要收入构成已经补足，但客户贡献结构仍不完整，尚不能判断客户变化对收入的影响。"
    elif "customer_structure" in categories:
        counterpoint = "前五大客户占比已经补足，但主要收入构成仍不完整，尚不能判断增长来自哪项业务。"
    else:
        counterpoint = "当前缺少可复核的分业务收入和客户贡献时，不能判断哪项业务是主要增长来源。"
    if "临床试验现场管理" in business:
        boundary = "公司属于医药服务行业，不等于药品制造商，也不能据主营描述推断未来订单。"
    elif "药品" in business:
        boundary = "业务和产品结构只说明公司如何经营，不能据此推断产品销量、研发成功或未来增长。"
    else:
        boundary = "主营描述只说明公司如何经营，不能据此推断未来订单或利润。"
    return _section(
        headline=headline,
        meaning=meaning,
        selection_link="公司做什么用于判断量价异动是否有业务事实支撑，但不直接决定本次入选。",
        counterpoint=counterpoint,
        boundary=boundary,
        evidence={"main_business": business, "official_supplement_count": len(supplemented)},
    )


def _industry_analysis(
    card: Mapping[str, Any], theme_info: Mapping[str, Any]
) -> dict[str, Any]:
    routes = set(str(card.get("routes") or "").split("|"))
    hotspot = theme_info.get("selection_hotspot")
    if "hotspot" in routes and hotspot:
        headline = f"本次入选得到“{hotspot}”热点共同性支持。"
        meaning = "个股强势并非完全孤立，它与同日一组相近股票的共同表现同时出现。"
        link = "热点共同性是本次发现路线的直接组成部分。"
        counter = "同属热点只能证明市场共振，不能证明公司自身业绩或公告已经改善。"
    else:
        headline = "行业标签不能解释本次入选，本次主要是个股量价异动。"
        meaning = "虽然公司属于医药生物，但本次没有热点路线支持，不能把行业近期活跃当作它被选中的原因。"
        link = "本次入选与行业或概念共同性无直接关系，选择依据来自个股价格和成交。"
        counter = "缺少热点共同性意味着个股表现更孤立，后续需要确认这种强势能否延续。"
    return _section(
        headline=headline,
        meaning=meaning,
        selection_link=link,
        counterpoint=counter,
        boundary="正式指数或主题成员只证明成员关系，不等于相关业务已经贡献收入。",
        evidence={
            "industry_l1": card.get("industry_l1_name"),
            "routes": card.get("routes"),
            "selection_hotspot": hotspot,
        },
    )


def _selection_analysis(
    card: Mapping[str, Any], metrics: Mapping[str, Any]
) -> dict[str, Any]:
    return_5d = metrics.get("return_5d", card.get("return_5d"))
    relative_20d = metrics.get(
        "relative_return_20d", card.get("relative_return_20d")
    )
    amount_ratio = metrics.get(
        "current_amount_ratio_20d", card.get("current_amount_ratio_20d")
    )
    return_1d = metrics.get("return_1d")
    why = (
        f"近5个交易日上涨{_pct(return_5d)}，过去20个交易日跑赢市场{_pct(relative_20d)}，"
        f"形成日成交额约为近期平均的{_multiple(amount_ratio)}，说明近期表现强于市场且关注度明显提高。"
    )
    if (
        _number(return_1d) is not None
        and float(return_1d) < 0
        and _number(amount_ratio) is not None
        and float(amount_ratio) >= 1
    ):
        conflict = (
            f"形成日单日下跌{_pct(return_1d)}，同时成交额仍高于近期平均，构成放量下跌；"
            "这说明中期相对强势并不平稳，资金关注和兑现压力同时存在。"
        )
        headline = "中期相对强势触发关注，但形成日放量下跌形成明显冲突。"
    else:
        conflict = "当前三项量价条件方向一致，但仍需后续真实路径确认是否延续。"
        headline = "近期价格、相对市场表现和成交关注度同时转强。"
    return _section(
        headline=headline,
        meaning=why,
        selection_link="这三项量价事实是动作确认的直接原因，而不是公司知名度或主观推荐。",
        counterpoint=conflict,
        boundary="三项确认只说明当前量价状态值得继续观察，不能推断后续必然上涨。",
        evidence={
            "return_1d": return_1d,
            "return_5d": return_5d,
            "relative_return_20d": relative_20d,
            "current_amount_ratio_20d": amount_ratio,
        },
    )


def _financial_analysis(history: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    latest = dict(history[0]) if history else {}
    tr_yoy = _number(latest.get("tr_yoy"), 4)
    profit_yoy = _number(latest.get("netprofit_yoy"), 4)
    deduct_yoy = _number(latest.get("dt_netprofit_yoy"), 4)
    cash = _number(latest.get("n_cashflow_act"), 2)
    earlier = dict(history[-1]) if history else {}
    earlier_tr = _number(earlier.get("tr_yoy"), 4)
    earlier_profit = _number(earlier.get("netprofit_yoy"), 4)
    repair = (
        tr_yoy is not None
        and 0 < tr_yoy <= 10
        and profit_yoy is not None
        and profit_yoy >= 20
    )
    if repair:
        headline = "利润修复快于收入，当前更像经营修复而不是已经确认的高速增长。"
        meaning = (
            f"最新营收同比增长{abs(tr_yoy):.2f}%，净利润同比增长{abs(profit_yoy):.2f}%，"
            f"扣非净利润同比增长{abs(deduct_yoy or 0):.2f}%。"
        )
        if earlier_tr is not None and earlier_tr < 0 and earlier_profit is not None and earlier_profit < 0:
            meaning += "此前同类指标曾为负，当前高利润增速更接近修复，而不是已经进入稳定高增长。"
    elif tr_yoy is not None and tr_yoy > 0 and profit_yoy is not None and profit_yoy > 0:
        headline = "收入和利润同时改善，财务方向对公司观察形成支持。"
        meaning = (
            f"最新营收同比增长{abs(tr_yoy):.2f}%，净利润同比增长{abs(profit_yoy):.2f}%，"
            "收入与利润方向一致。"
        )
    else:
        headline = "当前财务数据没有形成清晰的收入与利润共同改善。"
        meaning = "最新收入或利润至少一项未确认正增长，财务支持有限。"
    if cash is not None and cash < 0:
        counterpoint = "最新经营现金流仍为负，利润改善尚未得到当期现金流支持，这会削弱财务确认强度。"
    else:
        counterpoint = "经营现金流为正时提供现金支持，但单个季度仍可能受回款节奏影响。"
    return _section(
        headline=headline,
        meaning=meaning,
        selection_link="财务表现用于判断量价强势是否有经营基础；它不是本次价格路线触发的直接条件。",
        counterpoint=counterpoint,
        boundary="不能只凭高利润同比判断为稳定高成长，也不能把累计季度指标直接年化。",
        evidence={
            "latest_report_period": latest.get("report_period"),
            "latest_tr_yoy": latest.get("tr_yoy"),
            "latest_netprofit_yoy": latest.get("netprofit_yoy"),
            "latest_dt_netprofit_yoy": latest.get("dt_netprofit_yoy"),
            "latest_n_cashflow_act": latest.get("n_cashflow_act"),
        },
    )


def _trading_valuation_analysis(metrics: Mapping[str, Any]) -> dict[str, Any]:
    return_1d = _number(metrics.get("return_1d"), 6)
    return_20d = _number(metrics.get("return_20d"), 6)
    volatility = _number(metrics.get("realized_volatility_20d_annualized"), 6)
    atr = _number(metrics.get("atr_ratio_20d"), 6)
    pe_pct = _number(metrics.get("pe_ttm_percentile_250d"), 6)
    pb_pct = _number(metrics.get("pb_percentile_250d"), 6)
    sample = _number(metrics.get("valuation_observations_250d"), 0)
    if return_20d is not None and return_20d > 0 and return_1d is not None and return_1d < 0:
        headline = "中期强、形成日明显转弱，价格信号内部存在冲突。"
    else:
        headline = "近期价格路径与中期方向大体一致。"
    risk_parts: list[str] = []
    if (volatility is not None and volatility >= 0.60) or (atr is not None and atr >= 0.06):
        risk_parts.append(
            f"20日年化波动率约{_pct(volatility)}、ATR比率约{_pct(atr)}，说明波动路径很不稳定"
        )
    if (pe_pct is not None and pe_pct >= 0.70) or (pb_pct is not None and pb_pct >= 0.70):
        risk_parts.append("PE或PB分位超过自身近年样本的70%，估值处于自身历史偏高位置")
    elif (pe_pct is not None and pe_pct <= 0.30) and (pb_pct is not None and pb_pct <= 0.30):
        risk_parts.append("PE和PB均处于自身历史较低位置")
    meaning = "；".join(risk_parts) + "。" if risk_parts else "现有指标未形成统一的高波动或高估值结论。"
    if sample is not None and sample < 200:
        meaning += f"估值分位只有{int(sample)}个观察值，结论强度需要降低。"
    return _section(
        headline=headline,
        meaning=meaning,
        selection_link="相对收益和成交放大解释了为何被选中；波动与估值决定这种强势应如何谨慎理解。",
        counterpoint="形成日下跌且成交放大时，这不是低波动的连续上涨确认，而是强势背景下的明显分歧。",
        boundary="历史分位只与公司自身历史比较，不能代替同行估值，也不能预测价格方向。",
        evidence={key: metrics.get(key) for key in (
            "return_1d",
            "return_20d",
            "realized_volatility_20d_annualized",
            "atr_ratio_20d",
            "pe_ttm",
            "pb",
            "pe_ttm_percentile_250d",
            "pb_percentile_250d",
            "valuation_observations_250d",
        )},
    )


def _announcement_analysis(
    announcements: Sequence[Mapping[str, Any]], card: Mapping[str, Any]
) -> dict[str, Any]:
    titles = [str(item.get("title") or "") for item in announcements]
    event_types = {
        str(event)
        for item in announcements
        for event in item.get("event_types", [])
    }
    reductions = "shareholder_reduction" in event_types or any("减持" in title for title in titles)
    driver_keywords = ("注册证", "批准", "目录", "合同", "中标", "业绩")
    drivers = [title for title in titles if any(word in title for word in driver_keywords)]
    if drivers:
        headline = "近期正式公告为公司产品或经营逻辑提供方向支持，但经济影响仍未知。"
        meaning = "形成日前存在产品、批准、目录、合同或业绩相关公告，说明公司级事实并非完全缺席。"
        counterpoint = "公告标题没有结构化收入、利润或订单金额，不能判断影响大小和兑现时间。"
        boundary = "只能确认公告存在和方向相关，不能把它扩写成确定的业绩贡献。"
    else:
        headline = "近期公告没有提供支持本次上涨的公司催化。"
        meaning = "本次量价异动缺少新产品、业绩、合同或其他公司级正式公告解释。"
        counterpoint = (
            "近期主要可见的是股东减持事项，意味着潜在供给压力，反而会削弱量价确认的基本面解释。"
            if reductions
            else "没有公司催化时，本次关注更依赖价格和成交本身。"
        )
        boundary = "不能用这些公告解释为基本面利好，也不能仅凭公告缺席否定公司的长期经营。"
    return _section(
        headline=headline,
        meaning=meaning,
        selection_link="公司级公告用于判断当前异动是否有可验证催化；没有催化时，选择原因仍是量价或热点。",
        counterpoint=counterpoint,
        boundary=boundary,
        evidence={"titles": titles, "event_types": sorted(event_types)},
    )


def analyze_dossier_facts(
    card: Mapping[str, Any],
    theme_info: Mapping[str, Any],
    history: Sequence[Mapping[str, Any]],
    metrics: Mapping[str, Any],
    announcements: Sequence[Mapping[str, Any]],
    supplements: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    company = _company_analysis(card, supplements)
    industry = _industry_analysis(card, theme_info)
    selection = _selection_analysis(card, metrics)
    financial = _financial_analysis(history)
    trading = _trading_valuation_analysis(metrics)
    announcement = _announcement_analysis(announcements, card)
    routes = set(str(card.get("routes") or "").split("|"))
    if "price" in routes and "hotspot" not in routes:
        top_headline = "这是量价驱动的短期观察对象，不是热点或新公司利好驱动。"
    elif "hotspot" in routes:
        top_headline = "这是热点共同性与个股量价同时支持的观察对象。"
    else:
        top_headline = "这是由形成日结构化证据触发的观察对象。"
    top_conflict = selection["counterpoint"]
    if _number(card.get("n_cashflow_act")) is not None and float(card["n_cashflow_act"]) < 0:
        top_conflict += " 最新经营现金流为负，削弱了量价强势背后的财务支持。"
    top = _section(
        headline=top_headline,
        meaning=selection["meaning"],
        selection_link=selection["selection_link"],
        counterpoint=top_conflict,
        boundary="当前结论只是持续观察理由，不是买卖指令或收益承诺。",
        evidence={**selection["evidence"], "routes": card.get("routes")},
    )
    supplement_categories = {
        str(item.get("fact_category")) for item in supplements if item.get("fact_category")
    }
    missing = ["可复核的市场份额", "严格同口径的同业估值比较"]
    if "revenue_composition" not in supplement_categories:
        missing.append("分业务收入与毛利构成")
    if "customer_structure" not in supplement_categories:
        missing.append("可复核的客户收入贡献")
    return {
        "top_conclusion": top,
        "company_analysis": company,
        "industry_theme_analysis": industry,
        "selection_analysis": selection,
        "financial_analysis": financial,
        "trading_valuation_analysis": trading,
        "announcement_analysis": announcement,
        "data_gaps": {
            "official_supplement_count": len(supplements),
            "local_and_official_missing": "；".join(missing) or "未发现关键静态公司事实缺口",
            "future_validations": "下一真实交易日开盘；后续5/10/20/30交易日真实路径；新的公司级正式公告",
        },
    }


__all__ = ["analyze_dossier_facts"]
