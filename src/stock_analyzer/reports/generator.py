from __future__ import annotations

import json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from stock_analyzer.domain.models import FocusState, Recommendation


def render_reports(
    output_dir: Path,
    recommendations: list[Recommendation],
    focus_states: list[FocusState],
) -> None:
    template_dir = Path(__file__).parent / "templates"
    env = Environment(
        loader=FileSystemLoader(template_dir),
        autoescape=select_autoescape(["html"]),
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    data_dir = output_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    payload = {
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
        recommendations=recommendations,
        focus_states=focus_states,
    )
    (output_dir / "index.html").write_text(index_html, encoding="utf-8")
