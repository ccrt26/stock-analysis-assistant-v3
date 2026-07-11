from datetime import date

import json

import pytest

from stock_analyzer.analysis.strategy_v2 import generate_strategy_v2_recommendations
from stock_analyzer.data.models import DataUnavailableNotice, SourceStatus
from stock_analyzer.domain.models import (
    ActionLabel,
    DataRecoveryAttempt,
    EvidencePackage,
    FeatureSnapshot,
    FocusState,
    OperationalDailyStatus,
    OperationalReportState,
    Recommendation,
)
from stock_analyzer.reports.generator import (
    render_data_unavailable_notice,
    render_reports,
    render_strategy_v2_data_insufficient_report,
)


def test_render_reports_creates_fixed_entry_and_hides_secrets(tmp_path):
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
    focus = FocusState(
        trade_date=date(2026, 7, 7),
        ts_code="600000.SH",
        state=ActionLabel.ENTER_OBSERVATION,
    )
    render_reports(
        tmp_path,
        [rec],
        [focus],
        evidence_packages=[_evidence_package()],
        trade_date=date(2026, 7, 7),
    )
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


def test_render_reports_requires_matching_evidence_for_production_recommendations(tmp_path):
    rec = Recommendation(
        trade_date=date(2026, 7, 7),
        ts_code="600000.SH",
        name="浦发银行",
        action=ActionLabel.ENTER_OBSERVATION,
        score=81,
        reasons=["趋势改善"],
        risks=["需要确认"],
        evidence_id="missing-evidence-600000",
    )

    with pytest.raises(ValueError) as excinfo:
        render_reports(tmp_path, [rec], [], trade_date=date(2026, 7, 7))

    assert "matching evidence package" in str(excinfo.value)
    assert "missing-evidence-600000" in str(excinfo.value)
    assert not (tmp_path / "index.html").exists()


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


def test_render_reports_daily_archive_links_to_local_stock_pages(tmp_path):
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

    render_reports(
        tmp_path,
        [rec],
        [],
        evidence_packages=[_evidence_package()],
        trade_date=date(2026, 7, 7),
    )

    root_html = (tmp_path / "index.html").read_text(encoding="utf-8")
    daily_html = (tmp_path / "daily" / "2026-07-07" / "index.html").read_text(
        encoding="utf-8"
    )

    assert 'href="daily/2026-07-07/stocks/600000.SH.html"' in root_html
    assert 'href="stocks/600000.SH.html"' in daily_html
    assert 'href="daily/2026-07-07/stocks/600000.SH.html"' not in daily_html


def test_render_reports_marks_fixture_outputs_in_html_and_json(tmp_path):
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

    render_reports(
        tmp_path,
        [rec],
        [],
        evidence_packages=[_evidence_package()],
        trade_date=date(2026, 7, 7),
        fixture_mode=True,
    )

    payload = json.loads((tmp_path / "data" / "latest.json").read_text(encoding="utf-8"))
    root_html = (tmp_path / "index.html").read_text(encoding="utf-8")
    daily_html = (tmp_path / "daily" / "2026-07-07" / "index.html").read_text(
        encoding="utf-8"
    )
    stock_html = (
        tmp_path / "daily" / "2026-07-07" / "stocks" / "600000.SH.html"
    ).read_text(encoding="utf-8")

    assert payload["report_mode"] == "fixture"
    assert payload["is_fixture"] is True
    assert payload["warning"] == (
        "Fixture/sample report: generated from local sample data; not production data."
    )
    for html in (root_html, daily_html, stock_html):
        assert "Fixture/sample report" in html
        assert "not production data" in html


def test_strategy_v2_report_hides_scores_and_shows_action_position(tmp_path):
    result = generate_strategy_v2_recommendations(
        features=[_strategy_feature("600000.SH")],
        stock_names={"600000.SH": "浦发银行"},
        trade_date=date(2026, 7, 10),
    )

    render_reports(
        tmp_path,
        [],
        [],
        trade_date=date(2026, 7, 10),
        strategy_v2_cards=result.cards,
        strategy_v2_snapshots=result.snapshots,
        operational_status=_generated_status(
            date(2026, 7, 10), recommendation_count=1, focus_count=0
        ),
    )

    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    stock_html = (
        tmp_path / "daily" / "2026-07-10" / "stocks" / "600000.SH.html"
    ).read_text(encoding="utf-8")
    payload = json.loads((tmp_path / "data" / "latest.json").read_text(encoding="utf-8"))

    assert "评分" not in html
    assert "评分" not in stock_html
    assert "internal_score" in payload["strategy_snapshots"][0]
    assert "internal_score" not in payload["recommendation_cards"][0]
    assert "操作建议" in html
    assert "仓位" in html
    assert "失效" in html
    assert "操作建议" in stock_html
    assert "确认条件" in stock_html
    assert "看错风险" in stock_html
    for label in [
        "公司业务",
        "基本面与估值",
        "市场与板块",
        "趋势与成交",
        "事件与催化",
        "风险与反证",
    ]:
        assert label in stock_html


def test_data_insufficient_report_lists_recovery_attempts_and_impact(tmp_path):
    status = OperationalDailyStatus(
        trade_date=date(2026, 7, 10),
        is_trading_day=True,
        recommendation_state=OperationalReportState.DATA_INSUFFICIENT,
        focus_state=OperationalReportState.DATA_INSUFFICIENT,
        recommendation_count=0,
        focus_count=0,
        data_recovery_attempts=[
            DataRecoveryAttempt(
                trade_date=date(2026, 7, 10),
                family="daily_ohlcv",
                source_name="tushare.daily",
                status=SourceStatus.FAILED,
                message="no current rows",
            )
        ],
        blocking_missing_fields=["daily_ohlcv.close"],
        message="核心行情缺失，不能形成完整结论。",
    )

    render_strategy_v2_data_insufficient_report(tmp_path, status)

    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    payload = json.loads((tmp_path / "data" / "latest.json").read_text(encoding="utf-8"))

    assert payload["report_mode"] == "data_insufficient"
    assert "核心行情缺失" in html
    assert "daily_ohlcv.close" in html
    assert "tushare.daily" in html
    assert "影响" in html


def test_data_unavailable_notice_does_not_create_stock_analysis_pages(tmp_path):
    notice = DataUnavailableNotice(
        trade_date=date(2026, 7, 8),
        reason="current live data unavailable",
        last_successful_trade_date=date(2026, 7, 7),
    )

    render_data_unavailable_notice(tmp_path, notice)

    latest = json.loads((tmp_path / "data" / "latest.json").read_text(encoding="utf-8"))
    html = (tmp_path / "index.html").read_text(encoding="utf-8")

    assert latest["report_mode"] == "data_unavailable"
    assert latest["is_fixture"] is False
    assert latest["recommendations"] == []
    assert latest["focus_states"] == []
    assert latest["evidence_packages"] == []
    assert latest["recommendation_details"] == []
    assert "不生成新的股票分析结论" in html
    assert "Fixture/sample report" not in html
    assert "今日推荐" not in html
    assert "重点关注" not in html
    assert not (tmp_path / "daily" / "2026-07-08" / "stocks").exists()


def _evidence_package() -> EvidencePackage:
    return EvidencePackage(
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


def _strategy_feature(ts_code: str) -> FeatureSnapshot:
    return FeatureSnapshot(
        trade_date=date(2026, 7, 10),
        ts_code=ts_code,
        trend_20d=0.08,
        trend_60d=0.12,
        relative_strength=0.75,
        volatility_20d=0.24,
        liquidity_score=0.9,
        quality_score=0.7,
        market_regime="sideways",
        industry="测试行业",
        data_quality="ok",
    )


def _generated_status(
    trade_date: date,
    recommendation_count: int,
    focus_count: int,
) -> OperationalDailyStatus:
    return OperationalDailyStatus(
        trade_date=trade_date,
        is_trading_day=True,
        recommendation_state=OperationalReportState.GENERATED,
        focus_state=OperationalReportState.GENERATED,
        recommendation_count=recommendation_count,
        focus_count=focus_count,
        message="Daily recommendations and focus watchlist generated.",
    )
