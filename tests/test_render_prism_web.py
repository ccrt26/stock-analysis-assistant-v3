"""render_prism_web 的最小充分测试：成品源文件完整性、渲染合同、市场附加与 CLI 输出。"""

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

# 展示层成品必须原样入库的源文件（.gitignore 只豁免 data/、dist/、index.html）。
PRISM_SOURCES = [
    "src/shell.html",
    "src/base.css",
    "src/prism.css",
    "src/v3.css",
    "src/core.js",
    "src/rules.js",
    "src/app.js",
    "src/effects.js",
    "tools/build.py",
    "tools/adapt_snapshot.py",
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
    builder = _load_prism_builder()
    html = builder.render_html({"stocks": [], "dates": []})
    # 单文件版内联资源，不残留外链；CSS 必须保持 base → prism → v3 的加载顺序。
    for ref in ("base.css", "prism.css", "v3.css", "rules.js", "app.js"):
        assert f'src="{ref}"' not in html and f'href="{ref}"' not in html
    base_marker = '--sans:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC"'
    prism_marker = "--bg: #070910"
    v3_marker = ".market-grid {grid-template-columns:repeat(var(--market-count,4)"
    assert base_marker in html and prism_marker in html and v3_marker in html
    assert html.index(base_marker) < html.index(prism_marker) < html.index(v3_marker)
    # 规则模块先于应用脚本注入。
    assert html.index("PRISM V3 · Display policy") < html.index("PRISM V3 standalone presentation")


@pytest.mark.skipif(
    not SAMPLE_DATA.is_file(), reason="sample snapshot stays local (git-ignored)"
)
def test_render_html_embeds_payload_verbatim() -> None:
    builder = _load_prism_builder()
    snapshot = json.loads(SAMPLE_DATA.read_text(encoding="utf-8"))
    html = builder.render_html(snapshot)
    assert "观澜 · 光场 PRISM" in html
    assert '<script id="snapshot" type="application/json">' in html
    # V3 无演示分支：输入按原样内联，不注入 demoShowcase 之类的展示偏好。
    assert "demoShowcase" not in html.split('<script id="snapshot"')[1].split("</script>")[0]


def test_cli_renders_with_market_enrichment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """CLI 复用 build_payload 真实数据；无本地指数时如实缺失，不伪造行情。"""
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
    monkeypatch.setattr(renderer, "build_payload", lambda *args, **kwargs: payload)
    # 屏蔽本地事实仓读取：无数据时页面保持“快照未提供”。
    monkeypatch.setattr(renderer, "_read_day_frames", lambda root, name, day, cutoff: None)

    out = tmp_path / "prism-report-2026-01-05.html"
    rc = prism_cli.main(["--out", str(out)])
    assert rc == 0
    assert out.is_file()
    text = out.read_text(encoding="utf-8")
    embedded = json.loads(text.split('<script id="snapshot" type="application/json">')[1].split("</script>")[0])
    assert embedded["analysis_date"] == "2026-01-05"
    assert embedded["presentation"]["marketCodes"] == [
        "000001.SH", "399001.SZ", "399006.SZ", "000688.SH",
    ]
    assert embedded["presentation"]["deepLimit"] == 8
    # 无本地指数行时不得编造 marketIndices。
    assert "marketIndices" not in embedded
    printed = capsys.readouterr().out
    assert "market_rows_loaded=0" in printed
    assert "market_provided=0/4" in printed
    # 固定地址随渲染发布，与留档内容一致；重复运行幂等。
    fixed = tmp_path / "prism.html"
    assert fixed.is_file() and fixed.read_text(encoding="utf-8") == text
    first_fixed_mtime = fixed.stat().st_mtime_ns
    assert prism_cli.main(["--out", str(out)]) == 0
    capsys.readouterr()
    assert fixed.read_text(encoding="utf-8") == text
    assert fixed.stat().st_mtime_ns == first_fixed_mtime
