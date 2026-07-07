from __future__ import annotations

from stock_analyzer.domain.models import EvidencePackage, Recommendation


def build_evidence_package(
    recommendation: Recommendation, matched_rules: list[str]
) -> EvidencePackage:
    evidence_id = f"{recommendation.trade_date.isoformat()}-{recommendation.ts_code}"
    return EvidencePackage(
        evidence_id=evidence_id,
        trade_date=recommendation.trade_date,
        ts_code=recommendation.ts_code,
        thesis=f"{recommendation.name}进入 2-8 周观察，原始分数 {recommendation.score}",
        support=list(recommendation.reasons),
        counter_evidence=list(recommendation.risks),
        matched_rules=list(matched_rules),
        confidence_level="medium",
        expected_confirmation_path=["趋势延续", "成交量维持", "反证未增强"],
        invalidation_conditions=["核心趋势证据消失", "出现官方重大风险", "反证强于支持证据"],
        source_versions={"recommendation": evidence_id},
    )
