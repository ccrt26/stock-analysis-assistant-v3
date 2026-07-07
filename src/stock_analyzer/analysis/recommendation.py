from __future__ import annotations

from pydantic import BaseModel

from stock_analyzer.analysis.scoring import score_feature
from stock_analyzer.domain.models import ActionLabel, FeatureSnapshot, Recommendation


class RecommendationResult(BaseModel):
    recommendations: list[Recommendation]
    near_misses: list[Recommendation]


def generate_recommendations(
    features: list[FeatureSnapshot],
    stock_names: dict[str, str],
    limit: int = 10,
    threshold: float = 70.0,
    near_miss_threshold: float = 60.0,
) -> RecommendationResult:
    effective_limit = max(min(limit, 10), 0)
    scored = sorted(
        ((score_feature(item), item) for item in features if item.data_quality == "ok"),
        reverse=True,
        key=lambda pair: pair[0],
    )
    recommendations: list[Recommendation] = []
    near_misses: list[Recommendation] = []
    for score, feature in scored:
        rec = Recommendation(
            trade_date=feature.trade_date,
            ts_code=feature.ts_code,
            name=stock_names.get(feature.ts_code, feature.ts_code),
            action=ActionLabel.ENTER_OBSERVATION,
            score=score,
            reasons=["20 日与 60 日趋势改善", "相对强度和流动性满足观察要求"],
            risks=["需要后续确认趋势不是一日噪声"],
        )
        if score >= threshold and len(recommendations) < effective_limit:
            recommendations.append(rec)
        elif score >= near_miss_threshold:
            near_misses.append(rec)
    return RecommendationResult(recommendations=recommendations, near_misses=near_misses)
