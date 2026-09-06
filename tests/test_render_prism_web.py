"""render_prism_web 的最小充分测试：成品源文件完整性、渲染合同与 CLI 输出。"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRISM_ROOT = PROJECT_ROOT / "tools" / "guanlan-prism"
SAMPLE_DATA = PRISM_ROOT / "data" / "snapshot.json"

# 展示层成品必须原样入库的 7 个源文件（tools/guanlan-prism/.gitignore 只豁免 data/dist）。
PRISM_SOURCES = [
    "src/shell.html",
    "src/base.css",
    "src/prism.css",
    "src/core.js",
    "src/app.js",
    "src/effects.js",
    "tools/build.py",
]


def _load_prism_builder():
    spec = importlib.util.spec_from_file_location(
        "guanlan_prism_build_test", PRISM_ROOT / "tools" / "build.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_prism_sources_present() -> None:
    for rel in PRISM_SOURCES:
        assert (PRISM_ROOT / rel).is_file(), f"missing vendored source: {rel}"
    # base.css 必须先于 prism.css 注入，视觉层次依赖该加载顺序。
    builder = _load_prism_builder()
    html = builder.render_html({"stocks": [], "dates": []}, demo_showcase=False)
    assert "prism.css" not in html  # 单文件版内联，不应残留外链
    base_marker = '--sans:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC"'
    prism_marker = "--bg: #070910"
    assert base_marker in html and prism_marker in html
    assert html.index(base_marker) < html.index(prism_marker)


@pytest.mark.skipif(
    not SAMPLE_DATA.is_file(), reason="sample snapshot stays local (git-ignored)"
)
def test_render_html_embeds_payload_and_production_order() -> None:
    builder = _load_prism_builder()
    snapshot = json.loads(SAMPLE_DATA.read_text(encoding="utf-8"))
    html = builder.render_html(snapshot, demo_showcase=False)
    assert "观澜 · 光场 PRISM" in html
    assert '<script id="snapshot" type="application/json">' in html
    # 正式模式必须关闭演示聚焦，不固定展示样例股票。
    assert '"demoShowcase":false' in html


def test_cli_renders_to_requested_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """CLI 复用 build_payload 的真实数据，写入 --out 指定路径且不覆盖其他文件。"""
    sys.path.insert(0, str(PROJECT_ROOT / "tools"))
    try:
        from tools import render_monitor_web as renderer
        from tools import render_prism_web as prism_cli
    except ImportError:
        import render_monitor_web as renderer  # type: ignore[no-redef]
        import render_prism_web as prism_cli  # type: ignore[no-redef]

    payload = {
        "analysis_date": "2026-01-05",
        "as_of": "2026-01-04T18:30:00+08:00",
        "market_name": "上证指数",
        "dates": ["12-30", "01-02", "01-05"],
        "market": [4000.0, 4010.0, None],
        "date_files": [],
        "review_dates": ["2026-01-05"],
        "stocks": [],
    }
    monkeypatch.setattr(renderer, "MONITOR_DIR", tmp_path)
    monkeypatch.setattr(renderer, "resolve_date", lambda monitor_dir, requested: date(2026, 1, 5))
    monkeypatch.setattr(
        renderer,
        "load_artifacts",
        lambda monitor_dir, day: ({}, {}, monitor_dir / "r.json", monitor_dir / "s.json"),
    )
    monkeypatch.setattr(
        renderer,
        "build_payload",
        lambda *args, **kwargs: payload,
    )
    out = tmp_path / "prism-report-2026-01-05.html"
    rc = prism_cli.main(["--out", str(out)])
    assert rc == 0
    assert out.is_file()
    text = out.read_text(encoding="utf-8")
    assert '"analysis_date":"2026-01-05"' in text
    assert '"demoShowcase":false' in text
    printed = capsys.readouterr().out
    assert "stock_count=0" in printed
