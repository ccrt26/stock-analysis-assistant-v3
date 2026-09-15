"""推荐正文的只读来源关联。复用正式核对，不写归档或生成研究文字。"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

try:
    import stock_ai
except ImportError:
    from tools import stock_ai


MESSAGES = {
    "generating": "本轮仍在生成，完整推荐正文尚未交付；当前可查看已保存摘要。",
    "report_failed": "本轮已经结束，但推荐正文尚未通过验收；需要修复后再交付。",
    "no_report": "原推荐的完整正文尚未归档，暂显示历史摘要。",
    "not_found": "已找到形成日日报，但没有找到这只股票的推荐正文，需核对原文归属。",
    "ambiguous": "原文中存在重复的推荐小节，尚不能确定应展示哪一段。",
    "read_error": "推荐原文读取失败，暂不能展示。",
    "identity_invalid": "原回复的日期或资料截止不能与正式推荐对应，需核对来源。",
    "source_conflict": "同一次推荐关联了不同的原回复，需先确认采用哪一份。",
    "archive_invalid": "正式研究归档或推荐记录核对未通过，暂不能接入原回复。",
    "recommendation_invalid": "原回复的推荐分区尚未通过核对，需修复后再展示。",
    "legacy_unverified": "找到一篇按行动日命名的旧文章，但缺少明确的资料截止对应依据，需核对后接入。",
}


def aware(value: object) -> datetime | None:
    try:
        result = datetime.fromisoformat(str(value))
        return result if result.tzinfo is not None and result.utcoffset() is not None else None
    except ValueError:
        return None


def fallback_report(selection_dir: Path, formation: str, action: str) -> tuple[str, str, str]:
    """返回原报告文本、来源类型、失败原因。调用方仅在形成日日报不存在时使用。"""
    root = selection_dir.parent.parent
    try:
        trace = json.loads((selection_dir / f"research-trace-{formation}.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return "", "", "no_report"
    except (OSError, ValueError):
        return "", "", "read_error"
    cutoff = aware(trace.get("as_of"))
    if trace.get("formation_date") != formation or trace.get("action_date") != action or cutoff is None:
        return "", "", "identity_invalid"
    cutoff_text = str(trace["as_of"])
    # 历史兼容仅查看当前身份的行动日文件；不能仅凭日期/股票猜配。
    legacy = selection_dir / f"daily-research-{action}.md"
    legacy_unverified = False
    if action != formation and legacy.is_file():
        try:
            text = legacy.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return "", "", "read_error"
        # 必须在文章内明确声明两个日期和精确截止，历史文章不套用新正文格式。
        stamps = (f"formation_date: {formation}", f"action_date: {action}", f"as_of: {cutoff_text}")
        if all(stamp in text.splitlines() for stamp in stamps):
            ok, _ = stock_ai.forward_csv_matches_trace(formation, action, cutoff_text, root=root)
            if ok:
                return text, "legacy_daily_report", ""
        legacy_unverified = True
    replies: set[str] = set()
    problem = ""
    nightly = (root / "local_archive" / "ai_tasks" / "nightly").resolve()
    for path in sorted((root / "local_archive" / "ai_tasks" / "state").glob("nightly-*.json")):
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            problem = problem or "read_error"
            continue
        if state.get("formation_date") != formation or state.get("action_date") != action:
            continue
        if aware(state.get("selection_as_of")) != cutoff:
            problem = "identity_invalid"
            continue
        if not state.get("final_reply"):
            continue
        reply = (root / str(state["final_reply"])).resolve()
        if not reply.is_relative_to(nightly) or reply.name != "final-reply.md":
            problem = "identity_invalid"
            continue
        try:
            replies.add(reply.read_text(encoding="utf-8"))
        except (OSError, UnicodeError):
            problem = "read_error"
    if len(replies) > 1:
        return "", "", "source_conflict"
    if problem:
        return "", "", problem
    if not replies:
        task = task_for_identity(root, formation, action, cutoff_text)
        state = (task or {}).get("status")
        missing = "generating" if state == "running" else "report_failed" if state in ("failed", "cancelled", "canceled") else "no_report"
        return "", "", "legacy_unverified" if legacy_unverified else missing
    archive_ok, _ = stock_ai.strict_archive_check(formation, action, cutoff_text, root=root)
    csv_ok, _ = stock_ai.forward_csv_matches_trace(formation, action, cutoff_text, root=root)
    if not archive_ok or not csv_ok:
        return "", "", "archive_invalid"
    section, issues = stock_ai.accepted_recommendation_section(replies.pop(), formation, root=root)
    if issues:
        return "", "", "recommendation_invalid"
    return section, "verified_recommendation", ""


def task_for_identity(root: Path, formation: str, action: str, cutoff: str) -> dict | None:
    """只读关联该次研究的最近任务；不把其他日期或截止的状态带入。"""
    wanted = aware(cutoff)
    if wanted is None:
        return None
    states = []
    for path in (root / "local_archive/ai_tasks/state").glob("nightly-*.json"):
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if (state.get("formation_date") == formation and state.get("action_date") == action
                and aware(state.get("selection_as_of")) == wanted):
            states.append((path.stat().st_mtime_ns, state))
    return max(states, key=lambda item: item[0])[1] if states else None


def delivery_summary(root: Path, formation: str, cutoff: str, stocks: list[dict]) -> dict:
    trace = root / "local_archive/forward_selection" / f"research-trace-{formation}.json"
    try:
        action = json.loads(trace.read_text(encoding="utf-8"))["action_date"]
    except (OSError, ValueError, KeyError):
        return {}
    task = task_for_identity(root, formation, action, cutoff)
    current = [s for s in stocks if s.get("formedOn") == formation and s.get("recDate") == action]
    status = (task or {}).get("status", "unknown")
    result = (task or {}).get("result") or {}
    if status == "running":
        message = "本轮仍在生成，已保存新名单；完整报告尚未交付。"
    elif status == "completed":
        message = "本轮报告已交付。"
    elif status in ("failed", "cancelled", "canceled"):
        stage = result.get("stage")
        message = f"本轮{stage or '任务'}未完成，已保存内容保留；缺项不会继续自动补写。"
    else:
        message = "当前显示已保存内容；没有关联的完整任务交付状态。"
    complete = sum(bool(s.get("statementFull")) for s in current)
    intros = sum(bool(s.get("companyIntroduction")) for s in current)
    message += f" 今日推荐正文 {complete}/{len(current)}，公司介绍 {intros}/{len(current)}。"
    historical = sum(not s.get("statementFull") for s in stocks if s not in current)
    if historical:
        message += f" 另有 {historical} 条历史推荐正文待补。"
    return {"status": status, "message": message, "formationDate": formation,
            "recommendations": complete, "introductions": intros, "total": len(current)}
