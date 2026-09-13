"""把已发布 PRISM 页内嵌的冻结快照，渲染成「A 黑白仪表台 · 总览工作台」样式预览稿。

只读已生成的 prism.html（或 --from 指定的既有报告），提取其中 <script id="snapshot">
的同一份 JSON，注入 concept-a/overview-shell.html 模板，产出独立的预览文件：

    local_archive/forward_monitor/style-preview/prism-a.html

边界：
- 不改动 prism.html 与任何正式归档；预览稿写在自己的 style-preview/ 子目录。
- 不重新取数、不补行情；数据与来源页逐字节同源（提取后原样回注）。
- 仅总览工作台参与本轮样式评审；其余页面未改版，预览稿内的导航指向正式页。
- 模板替换合同与 tools/guanlan-prism/tools/build.py 相同：占位符只替换一次，
  JSON 中 '<' 转义为 \\u003c，防止正文提前终止脚本标签。

用法：
    ./.venv/bin/python tools/guanlan-prism/tools/build_preview_a.py
    ./.venv/bin/python tools/guanlan-prism/tools/build_preview_a.py \
        --from local_archive/forward_monitor/prism-report-2026-09-10.html
    ./.venv/bin/python tools/guanlan-prism/tools/build_preview_a.py --out 任意路径.html
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TEMPLATE = ROOT / "tools" / "guanlan-prism" / "concept-a" / "overview-shell.html"
MARKER = "/*__DATA__*/"
SNAPSHOT_RE = re.compile(
    r'<script id="snapshot"[^>]*>(.*?)</script>', re.S)


def extract_snapshot(source: Path) -> dict:
    """从既有 PRISM 页面提取内嵌快照；缺失或重复时明确报错。"""
    html = source.read_text(encoding="utf-8")
    matches = SNAPSHOT_RE.findall(html)
    if len(matches) != 1:
        raise ValueError(f"{source} 内应恰好包含一个 snapshot 脚本，实际 {len(matches)} 个")
    snapshot = json.loads(matches[0])
    if not isinstance(snapshot, dict):
        raise ValueError("snapshot 必须是 JSON 对象")
    analysis = snapshot.get("analysis_date")
    if not isinstance(analysis, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", analysis):
        raise ValueError(f"analysis_date 必须是 YYYY-MM-DD：{analysis!r}")
    if not isinstance(snapshot.get("stocks"), list):
        raise ValueError("快照缺少 stocks 数组")
    return snapshot


def render(snapshot: dict) -> str:
    template = TEMPLATE.read_text(encoding="utf-8")
    if template.count(MARKER) != 1:
        raise ValueError(f"模板应恰好包含一个 {MARKER} 占位符")
    payload = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"),
                         allow_nan=False).replace("<", "\\u003c")
    return template.replace(MARKER, payload)


def write_atomic(path: Path, html: str) -> bool:
    """与 render_prism_web.write_html 相同：内容不变不触碰，替换走原子改名。"""
    if path.exists() and path.read_text(encoding="utf-8") == html:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=path.name + ".tmp-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(html)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--monitor-dir", default=None,
                        help="PRISM 归档目录（默认 local_archive/forward_monitor）")
    parser.add_argument("--from", dest="source", default=None,
                        help="来源 HTML（默认该目录下最新可用的 prism.html）")
    parser.add_argument("--out", default=None,
                        help="输出路径（默认 <monitor-dir>/style-preview/prism-a.html）")
    args = parser.parse_args(argv)

    monitor_dir = Path(args.monitor_dir) if args.monitor_dir else ROOT / "local_archive" / "forward_monitor"
    if args.source:
        source = Path(args.source)
    else:
        candidates = sorted(monitor_dir.glob("prism-report-*.html"))
        source = monitor_dir / "prism.html"
        if not source.exists() and not candidates:
            raise ValueError(f"{monitor_dir} 下没有 prism.html，也没有 prism-report-*.html")
        if not source.exists():
            source = candidates[-1]
    if not source.exists():
        raise ValueError(f"来源文件不存在：{source}")
    fixed = (monitor_dir / "prism.html").resolve()
    out_path = Path(args.out) if args.out else monitor_dir / "style-preview" / "prism-a.html"
    if out_path.resolve() == fixed:
        raise ValueError("--out 不得指向 prism.html；预览稿请写到独立路径")

    snapshot = extract_snapshot(source)
    html = render(snapshot)
    changed = write_atomic(out_path, html)
    print(f"source={source}")
    print(f"analysis_date={snapshot['analysis_date']}")
    print(f"stock_count={len(snapshot['stocks'])}")
    print(("written=" if changed else "unchanged=") + str(out_path))
    print(f"preview_url=http://127.0.0.1:8940/style-preview/prism-a.html")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"status=error error={error}", file=sys.stderr)
        sys.exit(1)
