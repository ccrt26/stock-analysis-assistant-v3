from __future__ import annotations

from stock_analyzer.evaluation.v3_forward.dossier_analysis import (
    analyze_dossier_facts,
)


def _puruisi_analysis():
    card = {
        "ts_code": "301257.SZ",
        "stock_name": "普蕊斯",
        "main_business": "临床试验现场管理服务",
        "industry_l1_name": "医药生物",
        "routes": "price",
        "hotspot_group_name": None,
        "company_driver_state": "partial",
        "return_5d": 0.085094,
        "relative_return_20d": 0.434262,
        "current_amount_ratio_20d": 1.819694,
        "n_cashflow_act": -31_587_210.93,
        "company_catalyst_status": "未发现形成日前的新公司级驱动，当前确认主要来自量价或热点",
        "opposition_evidence": "经营活动现金流为负；存在股东减持",
        "missing_confirmations": "下一交易日路径尚未到达",
    }
    theme_info = {
        "selection_hotspot": None,
        "formal_theme_memberships": [],
    }
    history = [
        {
            "report_period": "2026-03-31",
            "tr_yoy": 9.9524,
            "netprofit_yoy": 61.7978,
            "dt_netprofit_yoy": 110.15,
            "ocf_yoy": 12.4078,
            "grossprofit_margin": 16.35,
            "netprofit_margin": 6.20,
            "roe": 0.94,
            "n_cashflow_act": -31_587_210.93,
        },
        {
            "report_period": "2025-12-31",
            "tr_yoy": 4.8244,
            "netprofit_yoy": 3.0149,
            "dt_netprofit_yoy": 6.26,
            "ocf_yoy": 3437.77,
            "grossprofit_margin": 25.87,
            "netprofit_margin": 13.01,
            "roe": 8.98,
            "n_cashflow_act": 35_693_336.0,
        },
        {
            "report_period": "2025-03-31",
            "tr_yoy": -4.37,
            "netprofit_yoy": -67.32,
            "dt_netprofit_yoy": -75.34,
            "ocf_yoy": -321.73,
            "grossprofit_margin": 16.23,
            "netprofit_margin": 4.21,
            "roe": 0.63,
            "n_cashflow_act": -36_061_658.0,
        },
    ]
    metrics = {
        "return_1d": -0.107377,
        "return_5d": 0.085094,
        "return_20d": 0.350786,
        "return_60d": -0.063127,
        "relative_return_20d": 0.434262,
        "realized_volatility_20d_annualized": 1.037228,
        "atr_ratio_20d": 0.103379,
        "price_location_60d": 0.691463,
        "current_amount_ratio_20d": 1.819694,
        "pe_ttm": 37.659,
        "pb": 3.3568,
        "pe_ttm_percentile_250d": 0.764,
        "pb_percentile_250d": 0.704,
        "valuation_observations_250d": 250,
    }
    announcements = [
        {
            "title": "关于公司股东减持计划实施完成的公告",
            "event_types": ["shareholder_reduction"],
            "available_at": "2026-06-26T13:04:26+00:00",
        }
    ]
    return analyze_dossier_facts(
        card, theme_info, history, metrics, announcements, supplements=[]
    )


def test_price_route_becomes_plain_numeric_why_now_conclusion():
    analysis = _puruisi_analysis()
    top = analysis["top_conclusion"]

    assert "量价驱动" in top["headline"]
    assert "不是热点" in top["headline"]
    assert "近5个交易日上涨8.51%" in top["meaning"]
    assert "过去20个交易日跑赢市场43.43%" in top["meaning"]
    assert "近期平均的1.82倍" in top["meaning"]
    assert "召回条件" not in str(analysis)
    assert "价格位置和成交活跃度" not in str(analysis)


def test_counterevidence_is_synthesized_into_impact_on_judgment():
    analysis = _puruisi_analysis()
    conflict = analysis["top_conclusion"]["counterpoint"]

    assert "形成日单日下跌10.74%" in conflict
    assert "放量下跌" in conflict
    assert "中期相对强势并不平稳" in conflict
    assert "经营现金流为负" in conflict
    assert "削弱" in conflict


def test_financial_analysis_explains_repair_and_cashflow_weakness():
    section = _puruisi_analysis()["financial_analysis"]

    assert "利润修复快于收入" in section["headline"]
    assert "更接近修复" in section["meaning"]
    assert "经营现金流仍为负" in section["counterpoint"]
    assert "不能只凭高利润同比判断为稳定高成长" in section["boundary"]
    assert section["evidence"]["latest_tr_yoy"] == 9.9524


def test_trading_and_valuation_analysis_explains_conflicting_signals():
    section = _puruisi_analysis()["trading_valuation_analysis"]

    assert "中期强、形成日明显转弱" in section["headline"]
    assert "波动路径很不稳定" in section["meaning"]
    assert "估值处于自身历史偏高位置" in section["meaning"]
    assert "不是低波动的连续上涨确认" in section["counterpoint"]


def test_announcement_analysis_says_what_reductions_mean():
    section = _puruisi_analysis()["announcement_analysis"]

    assert "没有提供支持本次上涨的公司催化" in section["headline"]
    assert "股东减持" in section["counterpoint"]
    assert "潜在供给压力" in section["counterpoint"]
    assert "不能用这些公告解释为基本面利好" in section["boundary"]


def test_every_core_section_has_conclusion_relationship_conflict_and_boundary():
    analysis = _puruisi_analysis()
    for name in (
        "company_analysis",
        "industry_theme_analysis",
        "selection_analysis",
        "financial_analysis",
        "trading_valuation_analysis",
        "announcement_analysis",
    ):
        assert set(analysis[name]) == {
            "headline",
            "meaning",
            "selection_link",
            "counterpoint",
            "boundary",
            "evidence",
        }
        assert analysis[name]["headline"]
        assert analysis[name]["selection_link"]
        assert analysis[name]["boundary"]


def test_data_gaps_are_separate_from_top_conclusion():
    analysis = _puruisi_analysis()

    assert "数据缺失" not in str(analysis["top_conclusion"])
    assert "下一交易日" not in str(analysis["top_conclusion"])
    assert "分业务收入" in analysis["data_gaps"]["local_and_official_missing"]
    assert "下一真实交易日开盘" in analysis["data_gaps"]["future_validations"]

