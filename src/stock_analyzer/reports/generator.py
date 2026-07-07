from __future__ import annotations

import html
import json
from pathlib import Path

from stock_analyzer.domain.models import FocusState, Recommendation


def _render_index_html_fallback(recommendations: list[Recommendation], focus_states: list[FocusState]) -> str:
    blocks = [
        "<!doctype html>",
        '<html lang="zh-CN">',
        "<head>",
        "  <meta charset=\"utf-8\">",
        '  <meta name="viewport" content="width=device-width, initial-scale=1">',
        "  <title>股票观察报告</title>",
        "</head>",
        "<body>",
        "  <main>",
        "    <h1>股票观察报告</h1>",
        "    <section>",
        "      <h2>今日推荐</h2>",
    ]

    if recommendations:
        for item in recommendations:
            name = html.escape(item.name)
            code = html.escape(item.ts_code)
            action = html.escape(item.action.value)
            reasons = html.escape("；".join(item.reasons))
            risks = html.escape("；".join(item.risks))
            score = html.escape(str(item.score))
            blocks.extend(
                [
                    "      <article>",
                    f"        <h3>{name} {code}</h3>",
                    f"        <p>{action}，评分 {score}</p>",
                    f"        <p>理由：{reasons}</p>",
                    f"        <p>风险：{risks}</p>",
                    "      </article>",
                ]
            )
    else:
        blocks.append("      <p>今日没有符合标准的推荐。</p>")

    blocks.extend(
        [
            "    </section>",
            "    <section>",
            "      <h2>重点关注</h2>",
        ]
    )

    if focus_states:
        for item in focus_states:
            code = html.escape(item.ts_code)
            state = html.escape(item.state.value)
            blocks.extend(
                [
                    "      <article>",
                    f"        <h3>{code}</h3>",
                    f"        <p>{state}</p>",
                    "      </article>",
                ]
            )
    else:
        blocks.append("      <p>当前没有重点关注股票。</p>")

    blocks.extend(
        [
            "    </section>",
            "  </main>",
            "</body>",
            "</html>",
        ]
    )
    return "\n".join(blocks) + "\n"


def render_reports(
    output_dir: Path,
    recommendations: list[Recommendation],
    focus_states: list[FocusState],
) -> None:
    try:
        from jinja2 import Environment, FileSystemLoader, select_autoescape
    except ModuleNotFoundError:
        index_html = _render_index_html_fallback(recommendations, focus_states)
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
        (output_dir / "index.html").write_text(index_html, encoding="utf-8")
        return

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
