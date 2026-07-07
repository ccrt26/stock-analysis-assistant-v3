from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape
from stock_analyzer.domain.models import FocusState, Recommendation


def render_reports(
    output_dir: Path,
    recommendations: list[Recommendation],
    focus_states: list[FocusState],
    trade_date: Optional[date] = None,
) -> None:
    report_date = _resolve_trade_date(trade_date, recommendations, focus_states)
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
        "recommendations": [
            item.model_dump(mode="json") for item in recommendations
        ],
        "focus_states": [item.model_dump(mode="json") for item in focus_states],
    }
    latest_path = data_dir / "latest.json"
    latest_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    index_html = env.get_template("index.html.j2").render(
        trade_date=report_date,
        recommendations=recommendations,
        focus_states=focus_states,
    )
    (output_dir / "index.html").write_text(index_html, encoding="utf-8")

    daily_dir = output_dir / "daily" / report_date.isoformat()
    daily_dir.mkdir(parents=True, exist_ok=True)
    (daily_dir / "index.html").write_text(index_html, encoding="utf-8")

    stocks_dir = daily_dir / "stocks"
    stocks_dir.mkdir(parents=True, exist_ok=True)
    stock_template = env.get_template("stock.html.j2")
    for recommendation in recommendations:
        stock_html = stock_template.render(
            stock_name=f"{recommendation.name} {recommendation.ts_code}",
            conclusion=_stock_conclusion(recommendation),
            recommendation=recommendation,
            focus_state=_focus_state_for(recommendation.ts_code, focus_states),
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
