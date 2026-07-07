from __future__ import annotations

from stock_analyzer.domain.models import FeatureSnapshot


def score_feature(feature: FeatureSnapshot) -> float:
    trend_score = max(feature.trend_20d, 0) * 250 + max(feature.trend_60d, 0) * 180
    strength_score = feature.relative_strength * 30
    liquidity_score = feature.liquidity_score * 20
    quality_score = feature.quality_score * 20
    volatility_penalty = max(feature.volatility_20d - 0.35, 0) * 60
    return round(trend_score + strength_score + liquidity_score + quality_score - volatility_penalty, 2)
