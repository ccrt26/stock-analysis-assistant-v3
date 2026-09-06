"""把已冻结的每日走势复盘渲染成「观澜 · 光场 PRISM」展示页面。

复用 tools/render_monitor_web.build_payload 输出的同一份数据（其字段合同即
tools/guanlan-prism/docs/03-数据接口与口径.md），调用成品包 render_html()
生成单文件离线 HTML。不修改选股、复盘、V4 渲染器或定时任务；不覆盖
monitor-report-*.html 与 index.html，新页面写入 prism-report-<date>.html。

用法：
    ./.venv/bin/python tools/render_prism_web.py                  # 最新一个 snapshot
    ./.venv/bin/python tools/render_prism_web.py --date 2026-09-02
    ./.venv/bin/python tools/render_prism_web.py --out 任意路径.html
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRISM_ROOT = PROJECT_ROOT / "tools" / "guanlan-prism"


def load_renderers():
    """与 tests/update_monitor_web 复用同一 render_monitor_web 模块实例。"""
    sys.path.insert(0, str(PROJECT_ROOT / "tools"))
    try:
        from tools import render_monitor_web as renderer
    except ImportError:  # 直接以脚本方式运行（python tools/render_prism_web.py）
        import render_monitor_web as renderer

    spec = importlib.util.spec_from_file_location(
        "guanlan_prism_build", PRISM_ROOT / "tools" / "build.py"
    )
    if spec is None or spec.loader is None:
        raise FileNotFoundError(f"missing PRISM builder at {PRISM_ROOT / 'tools' / 'build.py'}")
    prism = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prism)
    return renderer, prism


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Render the frozen daily monitor review as the PRISM display page"
    )
    parser.add_argument(
        "--date", default=None, help="analysis date (YYYY-MM-DD), default latest snapshot"
    )
    parser.add_argument("--monitor-dir", default=None, help="override monitor archive directory")
    parser.add_argument(
        "--out",
        default=None,
        help="override output HTML path (default prism-report-<date>.html in monitor dir)",
    )
    args = parser.parse_args(argv)

    renderer, prism = load_renderers()
    monitor_dir = Path(args.monitor_dir) if args.monitor_dir else renderer.MONITOR_DIR
    analysis_date: date = renderer.resolve_date(monitor_dir, args.date)
    report, snapshot, _report_path, _snapshot_path = renderer.load_artifacts(
        monitor_dir, analysis_date
    )
    payload = renderer.build_payload(
        PROJECT_ROOT, monitor_dir, analysis_date, report, snapshot
    )
    # 正式页面固定走输入记录顺序；演示聚焦仅用于同数据视觉核对，不在本入口提供。
    html = prism.render_html(payload, demo_showcase=False)
    out_path = (
        Path(args.out)
        if args.out
        else monitor_dir / f"prism-report-{analysis_date.isoformat()}.html"
    )
    out_path.write_text(html, encoding="utf-8")
    print("status=rendered")
    print(f"analysis_date={analysis_date.isoformat()}")
    print(f"html_file={out_path}")
    print(f"stock_count={len(payload['stocks'])}")
    attention = sum(1 for stock in payload["stocks"] if stock["attention"])
    print(f"attention_count={attention}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
