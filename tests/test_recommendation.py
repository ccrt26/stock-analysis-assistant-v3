from datetime import date

from stock_analyzer.analysis.recommendation import generate_recommendations
from stock_analyzer.domain.models import ActionLabel, FeatureSnapshot


def feature(ts_code: str, trend20: float, trend60: float, rs: float, liquidity: float, quality: float) -> FeatureSnapshot:
    return FeatureSnapshot(
        trade_date=date(2026, 7, 7),
        ts_code=ts_code,
        trend_20d=trend20,
        trend_60d=trend60,
        relative_strength=rs,
        volatility_20d=0.25,
        liquidity_score=liquidity,
        quality_score=quality,
        market_regime="sideways",
        industry="测试行业",
        data_quality="ok",
    )


def test_generate_recommendations_caps_at_10_and_records_near_misses():
    features = [feature(f"600{i:03d}.SH", 0.08, 0.12, 0.7, 0.8, 0.7) for i in range(15)]
    names = {item.ts_code: f"样本{i}" for i, item in enumerate(features)}
    result = generate_recommendations(features, names, limit=10)
    assert len(result.recommendations) == 10
    assert len(result.near_misses) == 5
    assert all(item.action == ActionLabel.ENTER_OBSERVATION for item in result.recommendations)


def test_generate_recommendations_hard_cap_enforced_when_limit_exceeds_10():
    features = [feature(f"600{i:03d}.SH", 0.08, 0.12, 0.7, 0.8, 0.7) for i in range(15)]
    names = {item.ts_code: f"样本{i}" for i, item in enumerate(features)}
    result = generate_recommendations(features, names, limit=12)
    assert len(result.recommendations) == 10
    assert len(result.near_misses) == 5


def test_generate_recommendations_does_not_fill_quota_with_weak_scores():
    features = [feature("600000.SH", 0.01, -0.01, 0.2, 0.8, 0.7)]
    result = generate_recommendations(features, {"600000.SH": "弱样本"}, limit=10)
    assert result.recommendations == []
    assert result.near_misses == []


def test_generate_recommendations_non_positive_limit_yields_no_recommendations():
    features = [feature(f"600{i:03d}.SH", 0.08, 0.12, 0.7, 0.8, 0.7) for i in range(3)]
    names = {item.ts_code: f"样本{i}" for i, item in enumerate(features)}
    zero_limit = generate_recommendations(features, names, limit=0)
    negative_limit = generate_recommendations(features, names, limit=-3)
    assert len(zero_limit.recommendations) == 0
    assert len(zero_limit.near_misses) == 3
    assert len(negative_limit.recommendations) == 0
    assert len(negative_limit.near_misses) == 3
