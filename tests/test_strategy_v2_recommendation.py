from datetime import date

from stock_analyzer.analysis.strategy_v2 import generate_strategy_v2_recommendations
from stock_analyzer.domain.models import FeatureSnapshot


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
