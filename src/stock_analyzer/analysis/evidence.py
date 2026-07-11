from __future__ import annotations

from stock_analyzer.domain.models import (
    EvidenceAtom,
    EvidencePackage,
    Recommendation,
    StrategyEvidenceSnapshot,
)


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


def build_evidence_package_from_strategy_snapshot(
    snapshot: StrategyEvidenceSnapshot,
) -> EvidencePackage:
    source_versions = dict(snapshot.source_versions)
    source_versions.setdefault("strategy_snapshot", snapshot.evidence_id)
    return EvidencePackage(
        evidence_id=snapshot.evidence_id,
        trade_date=snapshot.trade_date,
        ts_code=snapshot.ts_code,
        thesis=snapshot.thesis,
        support=_flatten_atoms(
            atom for module in snapshot.modules for atom in module.support
        ),
        counter_evidence=_flatten_atoms(
            atom for module in snapshot.modules for atom in module.counter
        ),
        matched_rules=sorted(
            {
                rule
                for module in snapshot.modules
                for atom in [*module.support, *module.counter]
                for rule in atom.knowledge_rule_ids
            }
        ),
        confidence_level=_confidence_level(snapshot),
        expected_confirmation_path=list(snapshot.action.required_confirmation),
        invalidation_conditions=list(snapshot.action.invalidation_conditions),
        source_versions=source_versions,
    )


def _flatten_atoms(atoms) -> list[str]:
    return [_atom_text(atom) for atom in atoms]


def _atom_text(atom: EvidenceAtom) -> str:
    return f"{atom.headline}：{atom.detail}" if atom.detail else atom.headline


def _confidence_level(snapshot: StrategyEvidenceSnapshot) -> str:
    if snapshot.data_insufficient:
        return "low"
    if snapshot.risk_reward is not None and snapshot.risk_reward >= 1.5:
        return "medium"
    return "low"
