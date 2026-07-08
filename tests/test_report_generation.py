from datetime import date

import json

from stock_analyzer.domain.models import (
    ActionLabel,
    EvidencePackage,
    FocusState,
    Recommendation,
)
from stock_analyzer.reports.generator import render_reports


def test_render_reports_creates_fixed_entry_and_hides_secrets(tmp_path):
    rec = Recommendation(
        trade_date=date(2026, 7, 7),
        ts_code="600000.SH",
        name="浦发银行",
        action=ActionLabel.ENTER_OBSERVATION,
        score=81,
        reasons=["趋势改善"],
        risks=["需要确认"],
    )
    focus = FocusState(
        trade_date=date(2026, 7, 7),
        ts_code="600000.SH",
        state=ActionLabel.ENTER_OBSERVATION,
    )
    render_reports(tmp_path, [rec], [focus], trade_date=date(2026, 7, 7))
    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    json_text = (tmp_path / "data" / "latest.json").read_text(encoding="utf-8")
    daily_html = (tmp_path / "daily" / "2026-07-07" / "index.html").read_text(
        encoding="utf-8"
    )
    stock_html = (
        tmp_path / "daily" / "2026-07-07" / "stocks" / "600000.SH.html"
    ).read_text(encoding="utf-8")
    assert "浦发银行" in html
    assert "浦发银行" in daily_html
    assert "浦发银行" in stock_html
    assert "进入观察" in html
    assert "SUPABASE_SERVICE_ROLE_KEY" not in html
    assert "SUPABASE_SERVICE_ROLE_KEY" not in json_text
    assert "TUSHARE_TOKEN" not in html
    assert "TUSHARE_TOKEN" not in json_text
    assert "浦发银行" in json_text


def test_render_reports_exposes_evidence_backed_sections_and_links(tmp_path):
    rec = Recommendation(
        trade_date=date(2026, 7, 7),
        ts_code="600000.SH",
        name="浦发银行",
        action=ActionLabel.ENTER_OBSERVATION,
        score=81,
        reasons=["趋势改善"],
        risks=["需要确认"],
        evidence_id="2026-07-07-600000.SH",
    )
    evidence = EvidencePackage(
        evidence_id="2026-07-07-600000.SH",
        trade_date=date(2026, 7, 7),
        ts_code="600000.SH",
        thesis="浦发银行进入观察，趋势和流动性同步改善",
        support=["20 日趋势改善", "流动性满足观察要求"],
        counter_evidence=["需要确认不是一日噪声"],
        matched_rules=["RESEARCH_TREND_CONFIRMATION"],
        confidence_level="medium",
        expected_confirmation_path=["趋势延续", "成交量维持"],
        invalidation_conditions=["核心趋势证据消失", "反证强于支持证据"],
        source_versions={"recommendation": "2026-07-07-600000.SH"},
    )

    render_reports(
        tmp_path,
        [rec],
        [],
        evidence_packages=[evidence],
        trade_date=date(2026, 7, 7),
    )

    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    stock_html = (
        tmp_path / "daily" / "2026-07-07" / "stocks" / "600000.SH.html"
    ).read_text(encoding="utf-8")
    payload = json.loads((tmp_path / "data" / "latest.json").read_text(encoding="utf-8"))
    detail = payload["recommendation_details"][0]

    for label in [
        "发生了什么",
        "支撑证据",
        "反证与风险",
        "确认信号",
        "失效信号",
        "观察计划",
        "证据与规则引用",
        "数据可信度",
    ]:
        assert label in html
        assert label in stock_html

    assert detail["stock_page"] == "daily/2026-07-07/stocks/600000.SH.html"
    assert detail["evidence"]["evidence_id"] == "2026-07-07-600000.SH"
    assert detail["evidence"]["support"] == ["20 日趋势改善", "流动性满足观察要求"]
    assert detail["evidence"]["counter_evidence"] == ["需要确认不是一日噪声"]
    assert detail["evidence"]["confirmation_signals"] == ["趋势延续", "成交量维持"]
    assert detail["evidence"]["invalidation_signals"] == [
        "核心趋势证据消失",
        "反证强于支持证据",
    ]
    assert detail["evidence"]["rule_references"] == ["RESEARCH_TREND_CONFIRMATION"]
    assert detail["evidence"]["data_credibility"] == "medium"
