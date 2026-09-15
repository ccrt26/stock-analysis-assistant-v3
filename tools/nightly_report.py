"""从已保存的正式复盘装配交付稿；不生成研究文字，不改写源报告。"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

SECTIONS = ("今天的市场情况", "正式推荐股票的今日复盘", "目前仍开放的正式推荐股票数量", "今天明确推荐的股票")
GROUPS = ("关键节点复盘", "今日深入复盘", "今日简评")


def review_blocks(text: str) -> list[str]:
    headings = list(re.finditer(r"^## ([^\n]+)$", text, re.M))
    blocks, names = [], []
    for i, heading in enumerate(headings):
        name = next((g for g in GROUPS if heading.group(1).startswith(g)), None)
        if name is None:
            continue
        if name in names:
            raise ValueError(f"复盘源稿重复分区：{name}")
        names.append(name)
        end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        blocks.append(text[heading.start():end].strip())
    if names != sorted(names, key=GROUPS.index):
        raise ValueError("复盘源稿分组顺序不正确")
    return blocks


def source_sections(root: Path, formation: str) -> tuple[str, str]:
    from stock_analyzer.ops.forward_monitor import (
        DailyForwardMonitorReportV2, DailyFormalReviewLedgerV1, _render_markdown,
        _render_tracking_counts,
    )
    monitor = root / "local_archive/forward_monitor"
    report = DailyForwardMonitorReportV2.model_validate_json(
        (monitor / f"monitor-report-{formation}.json").read_text())
    ledger = DailyFormalReviewLedgerV1.model_validate_json(
        (monitor / f"daily-formal-reviews-{formation}.json").read_text())
    snapshot = json.loads((monitor / f"snapshot-{formation}.json").read_text())
    saved = (monitor / f"monitor-report-{formation}.md").read_text()
    expected = _render_markdown(report, snapshot, ledger)
    blocks = review_blocks(saved)
    if blocks != review_blocks(expected):
        raise ValueError("复盘源 Markdown 与正式 JSON/日评账本不一致；保留源稿，先核对冲突")
    episodes = {str(e.get("episode_id")): e for e in snapshot.get("episodes", [])}
    counts = _render_tracking_counts(snapshot, episodes, ledger)
    return "\n\n".join(blocks) or "今天没有需要复盘的正式推荐股票。", counts


def assemble_reply(draft: str, formation: str, action: str, as_of: str, *, root: Path) -> str:
    try:
        import stock_ai
    except ImportError:
        from tools import stock_ai
    for check in (stock_ai.strict_archive_check, stock_ai.forward_csv_matches_trace):
        ok, detail = check(formation, action, as_of, root=root)
        if not ok:
            raise ValueError(f"装配前正式归档核对失败：{detail}")
    text = draft.replace("\r\n", "\n")
    spans = []
    for title in SECTIONS:
        matches = list(re.finditer(rf"^## {re.escape(title)}[ \t]*$", text, re.M))
        if len(matches) != 1:
            raise ValueError(f"交付草稿总分区缺失或重复：{title}")
        spans.append(matches[0])
    if [m.start() for m in spans] != sorted(m.start() for m in spans):
        raise ValueError("交付草稿总分区顺序不正确")
    bodies = [text[m.end():spans[i+1].start() if i+1<len(spans) else len(text)].strip()
              for i, m in enumerate(spans)]
    bodies[1], bodies[2] = source_sections(root, formation)
    return "\n\n".join(f"## {title}\n\n{body}" for title, body in zip(SECTIONS, bodies)) + "\n"


def assemble_file(path: Path, formation: str, action: str, as_of: str, *, root: Path) -> bool:
    draft = path.read_text(encoding="utf-8")
    result = assemble_reply(draft, formation, action, as_of, root=root)
    if result == draft:
        return False
    original = path.with_name("model-reply.md")
    if not original.exists():
        original.write_bytes(path.read_bytes())
    # 与正文归档相同目录原子替换，原模型响应始终保留。
    import os
    import tempfile
    fd, temp = tempfile.mkstemp(prefix=".assembled-", suffix=".md", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(result)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return True


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--draft", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--formation-date", required=True)
    p.add_argument("--action-date", required=True)
    p.add_argument("--as-of", required=True)
    a = p.parse_args()
    root = Path(__file__).resolve().parents[1]
    result = assemble_reply(a.draft.read_text(), a.formation_date, a.action_date, a.as_of, root=root)
    if a.output.resolve() == a.draft.resolve():
        assemble_file(a.draft, a.formation_date, a.action_date, a.as_of, root=root)
    else:
        a.output.parent.mkdir(parents=True, exist_ok=True)
        a.output.write_text(result, encoding="utf-8")
    print(f"assembled={a.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
