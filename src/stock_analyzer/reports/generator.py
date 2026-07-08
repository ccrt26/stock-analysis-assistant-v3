from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape
from stock_analyzer.domain.models import EvidencePackage, FocusState, Recommendation


FIXTURE_REPORT_WARNING = (
    "Fixture/sample report: generated from local sample data; not production data."
)


def render_reports(
    output_dir: Path,
    recommendations: list[Recommendation],
    focus_states: list[FocusState],
    evidence_packages: Optional[list[EvidencePackage]] = None,
    trade_date: Optional[date] = None,
    fixture_mode: bool = False,
) -> None:
    report_date = _resolve_trade_date(trade_date, recommendations, focus_states)
    evidence_packages = evidence_packages or []
    if not fixture_mode:
        _require_matching_evidence(recommendations, evidence_packages)
    recommendation_details = _recommendation_details(
        recommendations,
        report_date,
        evidence_packages,
        stock_page_prefix=f"daily/{report_date.isoformat()}/stocks",
    )
    daily_recommendation_details = _recommendation_details(
        recommendations,
        report_date,
        evidence_packages,
        stock_page_prefix="stocks",
    )
    template_dir = Path(__file__).parent / "templates"
    env = Environment(
        loader=FileSystemLoader(template_dir),
        autoescape=select_autoescape(["html"]),
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    data_dir = output_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "trade_date": report_date.isoformat(),
        "report_mode": "fixture" if fixture_mode else "production",
        "is_fixture": fixture_mode,
        "warning": FIXTURE_REPORT_WARNING if fixture_mode else None,
        "recommendations": [
            item.model_dump(mode="json") for item in recommendations
        ],
        "focus_states": [item.model_dump(mode="json") for item in focus_states],
        "evidence_packages": [
            item.model_dump(mode="json") for item in evidence_packages
        ],
        "recommendation_details": recommendation_details,
    }
    latest_path = data_dir / "latest.json"
    latest_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    index_html = env.get_template("index.html.j2").render(
        trade_date=report_date,
        recommendation_details=recommendation_details,
        focus_states=focus_states,
        is_fixture=fixture_mode,
        fixture_warning=FIXTURE_REPORT_WARNING,
    )
    (output_dir / "index.html").write_text(index_html, encoding="utf-8")

    daily_dir = output_dir / "daily" / report_date.isoformat()
    daily_dir.mkdir(parents=True, exist_ok=True)
    daily_index_html = env.get_template("index.html.j2").render(
        trade_date=report_date,
        recommendation_details=daily_recommendation_details,
        focus_states=focus_states,
        is_fixture=fixture_mode,
        fixture_warning=FIXTURE_REPORT_WARNING,
    )
    (daily_dir / "index.html").write_text(daily_index_html, encoding="utf-8")

    stocks_dir = daily_dir / "stocks"
    stocks_dir.mkdir(parents=True, exist_ok=True)
    stock_template = env.get_template("stock.html.j2")
    for recommendation, detail in zip(recommendations, recommendation_details):
        stock_html = stock_template.render(
            stock_name=f"{recommendation.name} {recommendation.ts_code}",
            conclusion=_stock_conclusion(recommendation),
            recommendation=recommendation,
            detail=detail,
            focus_state=_focus_state_for(recommendation.ts_code, focus_states),
            is_fixture=fixture_mode,
            fixture_warning=FIXTURE_REPORT_WARNING,
        )
        (stocks_dir / f"{recommendation.ts_code}.html").write_text(
            stock_html,
            encoding="utf-8",
        )


def _focus_state_for(
    ts_code: str,
    focus_states: list[FocusState],
) -> Optional[FocusState]:
    for state in focus_states:
        if state.ts_code == ts_code:
            return state
    return None


def _resolve_trade_date(
    trade_date: Optional[date],
    recommendations: list[Recommendation],
    focus_states: list[FocusState],
) -> date:
    if trade_date is not None:
        return trade_date
    if recommendations:
        return recommendations[0].trade_date
    if focus_states:
        return focus_states[0].trade_date
    return date.today()


def _stock_conclusion(recommendation: Recommendation) -> str:
    reasons = "；".join(recommendation.reasons)
    risks = "；".join(recommendation.risks)
    return (
        f"{recommendation.action.value}，评分 {recommendation.score}。"
        f"主要依据：{reasons}。主要风险：{risks}。"
    )


def _recommendation_details(
    recommendations: list[Recommendation],
    report_date: date,
    evidence_packages: list[EvidencePackage],
    stock_page_prefix: str,
) -> list[dict]:
    return [
        _recommendation_detail(
            recommendation,
            report_date,
            evidence_packages,
            stock_page=f"{stock_page_prefix}/{recommendation.ts_code}.html",
        )
        for recommendation in recommendations
    ]


def _require_matching_evidence(
    recommendations: list[Recommendation],
    evidence_packages: list[EvidencePackage],
) -> None:
    evidence_by_id = {package.evidence_id: package for package in evidence_packages}
    missing = []
    mismatched = []
    for recommendation in recommendations:
        evidence_id = recommendation.evidence_id
        if not evidence_id:
            missing.append(f"{recommendation.ts_code} (missing evidence_id)")
            continue
        package = evidence_by_id.get(evidence_id)
        if package is None:
            missing.append(f"{recommendation.ts_code} ({evidence_id})")
            continue
        if package.ts_code != recommendation.ts_code:
            mismatched.append(
                f"{recommendation.ts_code} ({evidence_id} belongs to {package.ts_code})"
            )
    if missing or mismatched:
        details = "; ".join(
            part
            for part in (
                _format_evidence_validation_detail(
                    "missing matching evidence package",
                    missing,
                ),
                _format_evidence_validation_detail(
                    "mismatched evidence package",
                    mismatched,
                ),
            )
            if part
        )
        raise ValueError(
            "Production reports require a matching evidence package for every "
            f"recommendation: {details}."
        )


def _format_evidence_validation_detail(label: str, refs: list[str]) -> str:
    if not refs:
        return ""
    return f"{label}: {', '.join(refs)}"


def _recommendation_detail(
    recommendation: Recommendation,
    report_date: date,
    evidence_packages: list[EvidencePackage],
    stock_page: str,
) -> dict:
    evidence = _evidence_for(recommendation, evidence_packages)
    support = evidence.support if evidence else list(recommendation.reasons)
    counter_evidence = evidence.counter_evidence if evidence else list(recommendation.risks)
    confirmation_signals = (
        evidence.expected_confirmation_path
        if evidence
        else ["等待趋势、成交量和反证强度在后续交易日继续确认"]
    )
    invalidation_signals = (
        evidence.invalidation_conditions
        if evidence
        else list(recommendation.risks)
    )
    evidence_id = evidence.evidence_id if evidence else recommendation.evidence_id
    rule_references = evidence.matched_rules if evidence else []
    source_versions = evidence.source_versions if evidence else {}
    data_credibility = evidence.confidence_level if evidence else "unknown"
    what_happened = (
        evidence.thesis
        if evidence
        else f"{recommendation.name}触发观察评分 {recommendation.score}"
    )
    return {
        "trade_date": report_date.isoformat(),
        "ts_code": recommendation.ts_code,
        "name": recommendation.name,
        "action": recommendation.action.value,
        "score": recommendation.score,
        "stock_page": stock_page,
        "what_happened": what_happened,
        "why_observe": list(recommendation.reasons),
        "biggest_risk": recommendation.risks[0] if recommendation.risks else "暂无明确反证",
        "observation_plan": [
            "跟踪 5/20/40 个交易日检查点",
            "确认信号增强时继续观察",
            "失效信号触发时降级或剔除观察",
        ],
        "evidence": {
            "evidence_id": evidence_id,
            "support": list(support),
            "counter_evidence": list(counter_evidence),
            "confirmation_signals": list(confirmation_signals),
            "invalidation_signals": list(invalidation_signals),
            "rule_references": list(rule_references),
            "source_versions": dict(source_versions),
            "data_credibility": data_credibility,
        },
    }


def _evidence_for(
    recommendation: Recommendation,
    evidence_packages: list[EvidencePackage],
) -> Optional[EvidencePackage]:
    for package in evidence_packages:
        if recommendation.evidence_id and package.evidence_id == recommendation.evidence_id:
            return package
    for package in evidence_packages:
        if package.ts_code == recommendation.ts_code:
            return package
    return None
