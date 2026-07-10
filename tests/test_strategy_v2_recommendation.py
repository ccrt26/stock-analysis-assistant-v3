from datetime import date
from pathlib import Path

import yaml

from stock_analyzer.analysis.strategy_v2 import (
    build_strategy_snapshot,
    generate_strategy_v2_recommendations,
)
from stock_analyzer.data.models import FundamentalSummaryRow, SourceGrade
from stock_analyzer.domain.models import ActionDecision, EvidenceModule, FeatureSnapshot


REPO_ROOT = Path(__file__).resolve().parents[1]
RULES_PATH = REPO_ROOT / "src" / "stock_analyzer" / "knowledge" / "rules.seed.yaml"
STRATEGY_MAP_PATH = (
    REPO_ROOT / "src" / "stock_analyzer" / "knowledge" / "strategy_v2_map.yaml"
)


def _feature(code: str, trend20: float = 0.08, trend60: float = 0.12) -> FeatureSnapshot:
    return FeatureSnapshot(
        trade_date=date(2026, 7, 10),
        ts_code=code,
        trend_20d=trend20,
        trend_60d=trend60,
        relative_strength=0.75,
        volatility_20d=0.24,
        liquidity_score=0.9,
        quality_score=0.7,
        market_regime="sideways",
        industry="测试行业",
        data_quality="ok",
    )


def test_strategy_v2_recommendations_hide_scores_and_build_evidence_cards():
    result = generate_strategy_v2_recommendations(
        features=[_feature(f"600{i:03d}.SH") for i in range(12)],
        stock_names={f"600{i:03d}.SH": f"样本{i}" for i in range(12)},
        trade_date=date(2026, 7, 10),
    )

    assert len(result.cards) == 10
    assert len(result.snapshots) == 10
    assert all("score" not in card.model_dump(mode="json") for card in result.cards)
    assert all(card.what_happened for card in result.cards)
    assert all(card.why_it_may_have_happened for card in result.cards)
    assert all(card.what_it_may_mean for card in result.cards)
    assert all(card.main_risk for card in result.cards)
    assert all(card.focus_entry_progress for card in result.cards)


def test_strategy_v2_cards_expose_action_policy_controls_without_scores():
    result = generate_strategy_v2_recommendations(
        features=[_feature("600000.SH")],
        stock_names={"600000.SH": "浦发银行"},
        trade_date=date(2026, 7, 10),
    )

    card = result.cards[0]
    action = result.snapshots[0].action
    payload = card.model_dump(mode="json")

    assert "score" not in payload
    assert "internal_score" not in payload
    assert payload["position_min_pct"] == action.position_min_pct
    assert payload["position_max_pct"] == action.position_max_pct
    assert payload["required_confirmation"] == action.required_confirmation
    assert payload["invalidation_conditions"] == action.invalidation_conditions
    assert payload["risk_if_wrong"] == action.risk_if_wrong
    assert payload["staging_plan"] == action.staging_plan
    assert payload["action_reasoning"] == action.reasoning


def test_strategy_v2_recommendation_marks_data_insufficient_instead_of_positive_claims():
    result = generate_strategy_v2_recommendations(
        features=[
            _feature("600000.SH").model_copy(
                update={"data_quality": "missing_daily_basic"}
            )
        ],
        stock_names={"600000.SH": "浦发银行"},
        trade_date=date(2026, 7, 10),
    )

    assert result.cards == []
    assert result.data_insufficient_snapshots
    assert result.data_insufficient_snapshots[0].data_insufficient is True
    assert "数据不足" in result.data_insufficient_snapshots[0].data_insufficient_reason


def test_fundamental_module_uses_structured_summary_and_never_claims_missing_values():
    summary = FundamentalSummaryRow(
        trade_date=date(2026, 7, 10),
        ts_code="600000.SH",
        period_end=date(2026, 3, 31),
        revenue_yoy=5.0,
        profit_yoy=None,
        gross_margin=None,
        operating_cashflow=None,
        source_name="tushare.fina_indicator",
        source_grade=SourceGrade.PRIMARY,
    )

    result = generate_strategy_v2_recommendations(
        features=[_feature("600000.SH")],
        stock_names={"600000.SH": "浦发银行"},
        trade_date=date(2026, 7, 10),
        fundamental_summaries={"600000.SH": summary},
    )

    module = next(
        item
        for item in result.snapshots[0].modules
        if item.module is EvidenceModule.FUNDAMENTALS_VALUATION
    )
    rendered = " ".join(
        atom.detail for atom in [*module.support, *module.counter]
    )
    assert "营业收入同比 5.00%" in rendered
    assert "2026-03-31" in rendered
    assert "tushare.fina_indicator" in rendered
    assert "利润同比" not in rendered
    assert "毛利率" not in rendered
    assert "经营现金流" not in rendered


def test_strategy_v2_no_participation_thesis_does_not_overclaim_positive_support():
    snapshot = build_strategy_snapshot(
        feature=_feature("600001.SH"),
        stock_name="硬风险样本",
        trade_date=date(2026, 7, 10),
        official_events=["收到监管处罚风险提示"],
    )

    assert snapshot.action.decision == ActionDecision.NO_PARTICIPATION
    assert "不支持参与" in snapshot.thesis
    assert "支持 2-8 周观察" not in snapshot.thesis


def test_strategy_v2_rule_ids_are_traceable_to_seed_rules_or_knowledge_map():
    snapshot = build_strategy_snapshot(
        feature=_feature("600002.SH"),
        stock_name="规则样本",
        trade_date=date(2026, 7, 10),
        company_profile="主营业务稳定",
        board_context="测试行业板块强势",
        official_events=["发布经营改善公告"],
        public_information=["市场讨论热度提升"],
    )
    rule_ids = {
        rule_id
        for module in snapshot.modules
        for atom in [*module.support, *module.counter]
        for rule_id in atom.knowledge_rule_ids
    }
    seeded_ids = {
        item["rule_id"]
        for item in yaml.safe_load(RULES_PATH.read_text(encoding="utf-8"))["rules"]
    }
    mapped_ids = {
        item["knowledge_id"]
        for item in yaml.safe_load(STRATEGY_MAP_PATH.read_text(encoding="utf-8"))[
            "entries"
        ]
    }

    assert rule_ids <= seeded_ids | mapped_ids
    assert "QUALITY_SCORE_SUPPORT" not in rule_ids
    assert "MARKET_BOARD_SUPPORT" not in rule_ids


def test_strategy_v2_display_bucket_comes_from_action_not_internal_score():
    lower_score_snapshot = build_strategy_snapshot(
        feature=_feature("600003.SH", trend20=0.02, trend60=0.05),
        stock_name="低分强设置",
        trade_date=date(2026, 7, 10),
    )
    higher_score_snapshot = build_strategy_snapshot(
        feature=_feature("600004.SH", trend20=0.15, trend60=0.18),
        stock_name="高分强设置",
        trade_date=date(2026, 7, 10),
    )

    assert lower_score_snapshot.action.decision == ActionDecision.SMALL_EXPLORATORY
    assert higher_score_snapshot.action.decision == ActionDecision.SMALL_EXPLORATORY
    assert lower_score_snapshot.internal_score < 75
    assert higher_score_snapshot.internal_score >= 90
    assert lower_score_snapshot.display_rank_bucket == higher_score_snapshot.display_rank_bucket
