"""把已冻结的每日走势复盘渲染成《推荐观察台 · 观察日报 V4》展示网页。

设计来源：Downloads/A股个人助手_复盘与UI设计评审包_V1.0/A股推荐观察台_UI_Demo_V4.html。
只读取已归档的 monitor-report / snapshot / research-trace 和本地价格事实，生成静态 HTML。
不改变复盘合同、record 流程或 markdown 渲染器，不新增定时任务。
价格、指数与行业路径只使用 available_at <= 报告 as_of 的事实，与 snapshot 时点边界一致。

用法：
    ./.venv/bin/python tools/render_monitor_web.py                # 最新一个 snapshot
    ./.venv/bin/python tools/render_monitor_web.py --date 2026-09-02
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from stock_analyzer.ops.forward_selection import selection_output_class

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MONITOR_DIR = PROJECT_ROOT / "local_archive" / "forward_monitor"
SELECTION_DIR = PROJECT_ROOT / "local_archive" / "forward_selection"
BENCHMARK_CODE = "000001.SH"
MARKET_NAME = "上证指数"
EMPTY_BAR = [None, None, None, None, None]


# ---------------------------------------------------------------------------
# 产物读取
# ---------------------------------------------------------------------------

def resolve_date(monitor_dir: Path, requested: str | None) -> date:
    if requested:
        return date.fromisoformat(requested)
    candidates = sorted(
        path.stem.removeprefix("snapshot-")
        for path in monitor_dir.glob("snapshot-*.json")
        if "pre-" not in path.stem
    )
    if not candidates:
        raise FileNotFoundError(f"no snapshot files under {monitor_dir}")
    return date.fromisoformat(candidates[-1])


def load_artifacts(
    monitor_dir: Path, analysis_date: date
) -> tuple[dict[str, Any], dict[str, Any], Path, Path]:
    report_path = monitor_dir / f"monitor-report-{analysis_date.isoformat()}.json"
    snapshot_path = monitor_dir / f"snapshot-{analysis_date.isoformat()}.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    if str(report.get("analysis_date")) != analysis_date.isoformat():
        raise ValueError("report analysis_date does not match requested date")
    if str(snapshot.get("analysis_date")) != analysis_date.isoformat():
        raise ValueError("snapshot analysis_date does not match requested date")
    return report, snapshot, report_path, snapshot_path


def archived_dates(monitor_dir: Path) -> list[date]:
    days = []
    for path in sorted(monitor_dir.glob("monitor-report-*.json")):
        if "pre-" in path.stem:
            continue
        raw = path.stem.removeprefix("monitor-report-")
        try:
            days.append(date.fromisoformat(raw))
        except ValueError:
            continue
    return days


# ---------------------------------------------------------------------------
# 时点安全的价格 / 指数 / 行业事实（展示用原始价，不做复权换算）
# ---------------------------------------------------------------------------

def _cutoff_frame(frame: pd.DataFrame, cutoff: pd.Timestamp) -> pd.DataFrame:
    if "available_at" not in frame.columns:
        return frame
    available = pd.to_datetime(frame["available_at"], utc=True, errors="coerce")
    return frame.loc[available.notna() & available.le(cutoff)]


def _read_day_frames(
    root: Path, dataset: str, day: date, cutoff: pd.Timestamp
) -> pd.DataFrame | None:
    path = (
        root / "local_warehouse" / "facts" / dataset
        / f"trade_date={day.isoformat()}" / "data.parquet"
    )
    if not path.is_file():
        return None
    frame = _cutoff_frame(pd.read_parquet(path), cutoff)
    return frame if not frame.empty else None


def _single_number(value: Any) -> float | None:
    number = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return None if pd.isna(number) else float(number)


def list_sessions(root: Path, start: date, end: date) -> list[date]:
    days: set[date] = set()
    for dataset in ("equity_daily", "index_daily"):
        base = root / "local_warehouse" / "facts" / dataset
        for path in base.glob("trade_date=*/data.parquet"):
            raw = path.parent.name.removeprefix("trade_date=")
            try:
                day = date.fromisoformat(raw)
            except ValueError:
                continue
            if start <= day <= end:
                days.add(day)
    return sorted(days)


def _chain_levels(daily_returns: list[float | None]) -> list[float | None]:
    """把日收益序列链接成水平序列（基期 100；缺口如实断线）。"""
    levels: list[float | None] = []
    level: float | None = None
    for ret in daily_returns:
        if ret is None:
            levels.append(None)
            continue
        level = (level if level is not None else 100.0) * (1.0 + ret)
        levels.append(level)
    return levels


def collect_market_facts(
    root: Path,
    as_of: datetime,
    sessions: list[date],
    group_codes: list[str],
    codes: list[str],
    group_members: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """按全局交易日窗口收集原始 K 线、基准指数与行业路径（未对齐的空位为 None）。

    行业路径优先用行业成分等权日收益链接（二级目录没有官方指数日行情）；
    成员覆盖不足（<max(5, 30%)）的交易日如实断线，成分缺失时回退行业指数收盘。
    """
    cutoff = _as_utc_cutoff(as_of)
    candles: dict[str, list[list[float | None]]] = {code: [] for code in codes}
    market: list[float | None] = []
    industry: dict[str, list[float | None]] = {code: [] for code in group_codes}
    group_returns: dict[str, list[float | None]] = {code: [] for code in group_codes}
    for day in sessions:
        equity = _read_day_frames(root, "equity_daily", day, cutoff)
        rows_by_code: dict[str, pd.Series] = {}
        if equity is not None:
            for _, row in equity.iterrows():
                rows_by_code[str(row["ts_code"])] = row
        for code in codes:
            row = rows_by_code.get(code)
            if row is None:
                candles[code].append(list(EMPTY_BAR))
                continue
            values = [
                _single_number(row.get(name))
                for name in ("open", "high", "low", "close")
            ]
            amount = _single_number(row.get("amount"))
            if any(value is None for value in values):
                candles[code].append(list(EMPTY_BAR))
            else:
                candles[code].append(
                    [*values, None if amount is None else round(amount / 1e8, 2)]
                )
        index_frame = _read_day_frames(root, "index_daily", day, cutoff)
        bench_close: float | None = None
        if index_frame is not None:
            bench = index_frame.loc[
                index_frame["index_code"].astype(str).eq(BENCHMARK_CODE)
            ]
            if not bench.empty:
                bench_close = _single_number(bench.iloc[-1].get("close"))
        market.append(bench_close)
        industry_frame = _read_day_frames(root, "industry_daily", day, cutoff)
        industry_close: dict[str, float] = {}
        if industry_frame is not None:
            for _, row in industry_frame.iterrows():
                code = str(row["industry_code"])
                if code in industry:
                    value = _single_number(row.get("close"))
                    if value is not None:
                        industry_close[code] = value
        for code in group_codes:
            industry[code].append(industry_close.get(code))
        for code, members in (group_members or {}).items():
            mean_ret: float | None = None
            if equity is not None and members:
                sub = equity.loc[equity["ts_code"].astype(str).isin(members)]
                if not sub.empty and "pre_close" in sub.columns:
                    close = pd.to_numeric(sub["close"], errors="coerce")
                    pre = pd.to_numeric(sub["pre_close"], errors="coerce")
                    ret = ((close - pre) / pre.where(pre > 0)).dropna()
                    if len(ret) >= max(5, round(len(members) * 0.3)):
                        mean_ret = float(ret.mean())
            group_returns[code].append(mean_ret)
    industry_levels: dict[str, list[float | None]] = {}
    industry_kind: dict[str, str] = {}
    for code in group_codes:
        member_levels = _chain_levels(group_returns[code])
        if any(value is not None for value in member_levels):
            industry_levels[code] = member_levels
            industry_kind[code] = "members"
        else:
            industry_levels[code] = industry[code]
            industry_kind[code] = (
                "index" if any(value is not None for value in industry[code]) else "none"
            )
    return {
        "candles": candles,
        "market": market,
        "industry": industry_levels,
        "industry_kind": industry_kind,
    }


# ---------------------------------------------------------------------------
# 观点变化判定（只比较结构化字段，与复盘 Skill 的口径一致）
# ---------------------------------------------------------------------------

_WEAK_TESTS = {"insufficient_evidence", "not_yet_tested"}


def compute_view_change(
    review: dict[str, Any] | None, previous: dict[str, Any] | None
) -> dict[str, Any]:
    if review is None or previous is None:
        return {"changed": False, "has_previous": previous is not None, "reasons": []}
    reasons: list[str] = []
    previous_assessment = str(previous.get("current_assessment"))
    current_assessment = str(review.get("current_assessment"))
    if current_assessment != previous_assessment:
        reasons.append("assessment")
    both_informative = (
        previous_assessment not in _WEAK_TESTS and current_assessment not in _WEAK_TESTS
    )
    if both_informative:
        if str(review.get("current_weak_or_failed_link")) != str(
            previous.get("current_weak_or_failed_link")
        ):
            reasons.append("weak_link")
        if str(review.get("best_supported_explanation")) != str(
            previous.get("best_supported_explanation")
        ):
            reasons.append("explanation")
    return {"changed": bool(reasons), "has_previous": True, "reasons": reasons}


def inferred_output_class(episode: dict[str, Any]) -> str:
    """与 forward_monitor 的口径一致：类别为空时按发动机类型推断。"""
    value = str(episode.get("selection_output_class") or "")
    if value:
        return value
    if episode.get("role") != "selected":
        return "not_formal_candidate"
    if (
        episode.get("original_engine_type") == "fresh_event_pending"
        and episode.get("original_engine_status") == "conditional"
    ):
        return "conditional_event"
    return "legacy_v1_not_rewritten"


# ---------------------------------------------------------------------------
# 中文文案映射
# ---------------------------------------------------------------------------

ASSESSMENT_TEXT = {
    "not_yet_tested": "推荐后的事实还不足以检验当初判断",
    "partly_supported": "部分预期已发生，关键部分仍在验证",
    "supported": "当初的核心预期目前得到支持",
    "weakening": "当初的核心判断已经明显减弱",
    "contradicted": "推荐后的事实与核心预期相反",
    "insufficient_evidence": "现有资料不足，暂时无法可靠评价当初判断",
}
MONITOR_STATE_TEXT = {
    "strengthening": "继续走强",
    "pending_confirmation": "等待确认",
    "invalidated": "原判断已不成立",
    "actionable_watch": "需要重点盯住",
    "overheated": "高位过热",
    "target_hit": "已达到约20%",
    "late_activation": "前20日后才明显走强",
    "first_reaction": "首次反应",
    "checkpoint": "固定检查日",
    "data_problem": "数据问题",
    "new_event": "新事件",
}
OUTLOOK_TEXT = {
    "strengthening": "未来1—3个交易日更可能继续走强",
    "continuation_possible": "未来1—3个交易日更可能震荡偏强",
    "range_or_wait": "未来1—3个交易日更可能横盘整理或等待新变化",
    "weakening": "未来1—3个交易日更可能震荡偏下",
    "overheated": "未来1—3个交易日更可能高位剧烈波动并出现回吐",
    "invalidated": "未来1—3个交易日更可能继续偏弱",
    "event_pending": "先等待事件或复牌后的实际交易反应，方向暂时无法判断",
}
STAGE_MAP = {
    "strengthening": ("继续走强", "strong"),
    "target_hit": ("已达标", "strong"),
    "continuation_possible": ("震荡偏强", "strong"),
    "supported": ("判断成立", "strong"),
    "overheated": ("高位过热", "sideways"),
    "actionable_watch": ("需要盯住", "sideways"),
    "pending_confirmation": ("等待确认", "sideways"),
    "range_or_wait": ("横盘整理", "sideways"),
    "partly_supported": ("部分成立", "sideways"),
    "weakening": ("判断减弱", "weak"),
    "invalidated": ("原判断失效", "weak"),
    "contradicted": ("原判断失效", "weak"),
    "event_pending": ("等待事件", "paused"),
    "not_yet_tested": ("资料不足", "paused"),
    "insufficient_evidence": ("资料不足", "paused"),
}
ATTENTION_TRIGGER_MAP = [
    ("new_official_event", "新公告"),
    ("breakout_changed", "突破状态变化"),
    ("relative_state_changed", "相对强弱变化"),
    ("sector_state_changed", "板块状态变化"),
    ("overheat_candidate", "过热迹象"),
    ("first_event_reaction", "事件首次定价"),
    ("scenario_changed", "价格场景变化"),
    ("data_problem", "数据问题"),
]
ALERT_TRIGGER_MAP = {
    "pending_final_review": "待20日总结",
    "data_problem": "数据问题",
    "invalidated": "判断失效",
    "new_event": "新事件",
    "first_reaction": "首次反应",
    "actionable_watch": "需要关注",
    "overheated": "过热",
    "target_hit": "达到约20%",
    "late_activation": "后段才走强",
    "strengthening": "继续走强",
}


def stage_of(state: str | None) -> tuple[str, str]:
    if state is None:
        return STAGE_MAP["insufficient_evidence"]
    return STAGE_MAP.get(state, ("资料不足", "paused"))


def trigger_of(alert: dict[str, Any], view_changed: bool) -> str:
    if view_changed:
        return "观点改变"
    checkpoint = alert.get("checkpoint_label")
    if alert.get("alert_type") == "checkpoint" and checkpoint:
        return f"{checkpoint} 检查日"
    for reason, text in ATTENTION_TRIGGER_MAP:
        if reason in (alert.get("attention_reasons") or []):
            return text
    return ALERT_TRIGGER_MAP.get(str(alert.get("alert_type")), "需要关注")


# ---------------------------------------------------------------------------
# 历史复盘扫描（交易日尺 / 事件时间线的数据来源）
# ---------------------------------------------------------------------------

def _first_sentence(text: str) -> str:
    match = re.match(r"^[^。！？!?]+[。！？!?]", text.strip())
    return match.group(0) if match else text.strip()


def _review_facts(episode: dict[str, Any]) -> list[str]:
    def pct(value: float) -> str:
        return f"{'+' if value > 0 else ''}{value * 100:.2f}%"

    if not episode.get("formal_return_started") or episode.get("entry_open") is None:
        limitations = episode.get("data_limitations") or []
        if "missing_price_path" in limitations:
            return ["停牌中", "无可参与价格"]
        return ["暂无可靠推荐参考价"]
    facts: list[str] = []
    current = episode.get("current_close_return_since_entry")
    highest = episode.get("current_max_close_return_since_entry")
    day = int(episode.get("day_number") or 0)
    window = 20 if day >= 20 else 5 if day >= 5 else 3 if day >= 3 else 1
    relative = episode.get(f"relative_market_{window}d")
    if current is not None:
        facts.append(f"收盘较参考{pct(float(current))}")
    if highest is not None:
        facts.append(f"最高收盘{pct(float(highest))}")
    if relative is not None:
        facts.append(f"近{window}日相对市场{pct(float(relative))}")
    else:
        deepest = episode.get("current_mae_since_entry")
        if deepest is not None:
            facts.append(f"期间最深{pct(float(deepest))}")
    return facts[:3]


VIEW_CHANGE_TEXT = {
    "first_review": "首次复盘",
    "unchanged": "维持原判断",
    "strengthened": "观点增强",
    "weakened": "观点减弱",
    "invalidated": "判断失效",
}


def ledger_dates(monitor_dir: Path) -> list[date]:
    days = []
    for path in sorted(monitor_dir.glob("daily-formal-reviews-*.json")):
        if "pre-" in path.stem:
            continue
        raw = path.stem.removeprefix("daily-formal-reviews-")
        try:
            days.append(date.fromisoformat(raw))
        except ValueError:
            continue
    return days


def _parse_as_of(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed


def scan_history(
    monitor_dir: Path, analysis_date: date
) -> dict[str, list[dict[str, Any]]]:
    """逐日读取已归档 snapshot + report + 每日复盘台账，汇总每条记录的复盘历史。

    三路新档：节点/普通详评正文取自 report（账本该类正文为空），简评取自台账；
    结构化观点以台账为准，合并仅限同分析日、同 as_of、同 episode。
    旧档（无 checkpoint 字段）：同日同episode两者都有时，结构化观点/方向/标题与
    summary_copy 以台账为准，长正文 copy 与正反条件保留报告详评。
    """
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for day in archived_dates(monitor_dir):
        if day > analysis_date:
            continue
        snapshot_path = monitor_dir / f"snapshot-{day.isoformat()}.json"
        report_path = monitor_dir / f"monitor-report-{day.isoformat()}.json"
        if not snapshot_path.is_file() or not report_path.is_file():
            continue
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        report = json.loads(report_path.read_text(encoding="utf-8"))
        episodes = {
            str(item.get("episode_id")): item
            for item in snapshot.get("episodes", [])
            if isinstance(item, dict)
        }
        for alert in report.get("alerts", []):
            alert_checkpoint = any(
                str(episode_id) in set(snapshot.get("checkpoint_review_episode_ids") or [])
                for episode_id in alert.get("episode_ids", [])
            )
            for review in alert.get("episode_reviews", []):
                episode_id = str(review.get("episode_id"))
                episode = episodes.get(episode_id)
                if episode is None:
                    continue
                view = compute_view_change(review, episode.get("previous_episode_review"))
                previous_state = episode.get("previous_monitor_state")
                current_state = alert.get("monitor_state")
                from_to = None
                if (
                    view["changed"]
                    and previous_state
                    and current_state
                    and previous_state != current_state
                ):
                    from_to = (
                        f"{MONITOR_STATE_TEXT.get(str(previous_state), previous_state)}"
                        f" → {MONITOR_STATE_TEXT.get(str(current_state), current_state)}"
                    )
                merged[(episode_id, day.isoformat())] = {
                    "date": day.isoformat(),
                    "as_of": str(snapshot.get("as_of") or ""),
                    "day": int(episode.get("day_number") or 0),
                    "checkpoint": episode.get("checkpoint"),
                    "headline": _first_sentence(str(review.get("current_review") or "")),
                    "copy": str(review.get("current_review") or ""),
                    "summary_copy": str(review.get("current_review") or ""),
                    "review_kind": (
                        "checkpoint_detail" if alert_checkpoint
                        else "regular_detail"
                    ),
                    "facts": _review_facts(episode),
                    "base": OUTLOOK_TEXT.get(str(alert.get("outlook_1_3d")), ""),
                    "outlookReason": str(alert.get("outlook_reason_plain_language") or ""),
                    "assessmentText": ASSESSMENT_TEXT.get(
                        str(review.get("current_assessment")), ""
                    ),
                    "viewLabel": "观点调整" if view["changed"] else "维持原判断",
                    "viewReason": "",
                    "confirm": str(alert.get("confirmation_condition") or ""),
                    "risk": str(alert.get("invalidation_condition") or ""),
                    "viewChanged": view["changed"],
                    "fromTo": from_to,
                }
    for day in ledger_dates(monitor_dir):
        if day > analysis_date:
            continue
        ledger_path = monitor_dir / f"daily-formal-reviews-{day.isoformat()}.json"
        if not ledger_path.is_file():
            continue
        snapshot_path = monitor_dir / f"snapshot-{day.isoformat()}.json"
        episodes: dict[str, dict[str, Any]] = {}
        day_three_route = False
        checkpoint_ids: set[str] = set()
        if snapshot_path.is_file():
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            day_three_route = "checkpoint_review_episode_ids" in snapshot
            checkpoint_ids = {
                str(value)
                for value in snapshot.get("checkpoint_review_episode_ids") or []
            }
            episodes = {
                str(item.get("episode_id")): item
                for item in snapshot.get("episodes", [])
                if isinstance(item, dict)
            }
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        ledger_as_of = _parse_as_of(ledger.get("as_of"))
        for review in ledger.get("reviews", []):
            episode_id = str(review.get("episode_id"))
            episode = episodes.get(episode_id, {})
            view_change = str(review.get("view_change") or "unchanged")
            view_changed = view_change in {"strengthened", "weakened", "invalidated"}
            label = VIEW_CHANGE_TEXT.get(view_change, "维持原判断")
            from_to = label if view_changed else None
            key = (episode_id, day.isoformat())
            structured = {
                "day": int(review.get("day_number") or 0),
                "checkpoint": review.get("checkpoint"),
                "facts": _review_facts(episode),
                "base": OUTLOOK_TEXT.get(str(review.get("outlook_1_3d")), ""),
                "outlookReason": str(review.get("outlook_reason_plain_language") or ""),
                "assessmentText": ASSESSMENT_TEXT.get(
                    str(review.get("current_assessment")), ""
                ),
                "viewLabel": label,
                "viewReason": str(review.get("view_change_reason") or ""),
                "viewChanged": view_changed,
                "fromTo": from_to,
            }
            detail_body_missing = (
                day_three_route and not review.get("current_review")
            )
            if detail_body_missing:
                existing = merged.get(key)
                same_as_of = (
                    existing is not None
                    and ledger_as_of is not None
                    and _parse_as_of(existing.get("as_of")) == ledger_as_of
                )
                structured["review_kind"] = str(
                    review.get("review_kind")
                    or (
                        "checkpoint_detail"
                        if episode_id in checkpoint_ids
                        else "regular_detail"
                    )
                )
                if existing is not None and same_as_of:
                    # 账本提供结构化观点；详评正文与条件保留自报告。
                    existing.update(structured)
                    continue
                if existing is None:
                    item = {
                        "date": day.isoformat(),
                        "as_of": str(ledger.get("as_of") or ""),
                        "headline": "详评正文未保存",
                        "copy": "详评正文未保存。",
                        "summary_copy": "详评正文未保存。",
                        "confirm": "",
                        "risk": "",
                        **structured,
                    }
                    merged[key] = item
                continue
            item = {
                "date": day.isoformat(),
                "day": int(review.get("day_number") or 0),
                "checkpoint": review.get("checkpoint"),
                "headline": _first_sentence(str(review.get("current_review") or "")),
                "copy": str(review.get("current_review") or ""),
                "summary_copy": str(review.get("current_review") or ""),
                "review_kind": str(review.get("review_kind") or "brief"),
                "facts": _review_facts(episode),
                "base": OUTLOOK_TEXT.get(str(review.get("outlook_1_3d")), ""),
                "outlookReason": str(review.get("outlook_reason_plain_language") or ""),
                "assessmentText": ASSESSMENT_TEXT.get(
                    str(review.get("current_assessment")), ""
                ),
                "viewLabel": label,
                "viewReason": str(review.get("view_change_reason") or ""),
                "confirm": "",
                "risk": "",
                "viewChanged": view_changed,
                "fromTo": from_to,
            }
            existing = merged.get(key)
            if existing is None:
                merged[key] = item
            else:
                # DailyFormalReviewV1 is the single source of today's view;
                # the detailed report keeps its own expanded body and conditions.
                merged[key] = {
                    **item,
                    "copy": existing["copy"],
                    "confirm": existing["confirm"],
                    "risk": existing["risk"],
                }
    history: dict[str, list[dict[str, Any]]] = {}
    for (episode_id, _day), item in merged.items():
        history.setdefault(episode_id, []).append(item)
    for items in history.values():
        items.sort(key=lambda item: item["date"])
    return history


def group_name_map(selection_dir: Path) -> dict[str, str]:
    names: dict[str, str] = {}
    for path in sorted(selection_dir.glob("research-trace-*.json")):
        try:
            trace = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(trace, dict):
            continue
        for decision in trace.get("decision_trace", []) or []:
            values = decision.get("formation_values") or {}
            code = values.get("group_code")
            name = values.get("group_name")
            if code and name:
                names[str(code)] = str(name)
    return names


def industry_catalog_names(root: Path) -> dict[str, str]:
    """行业目录代码 → 名称（研究轨迹缺名称时的兜底）。"""
    path = (
        root / "local_warehouse" / "facts" / "industry_catalog"
        / "classification_version=SW2021" / "data.parquet"
    )
    if not path.is_file():
        return {}
    frame = pd.read_parquet(path)
    return {
        str(code): str(name)
        for code, name in zip(frame["industry_code"], frame["industry_name"])
        if pd.notna(code) and pd.notna(name)
    }


def _as_utc_cutoff(as_of: datetime) -> pd.Timestamp:
    return (
        pd.Timestamp(as_of).tz_convert("UTC")
        if as_of.tzinfo
        else pd.Timestamp(as_of, tz="UTC")
    )


_BIZ_KEYWORDS = (
    "业务板块", "主营", "主要从事", "主要产品", "主要业务",
    "生产商", "提供商", "专注于", "致力于", "是一家",
)


def _normalize_main_business(main_business: str) -> str:
    biz = str(main_business or "").strip()
    if not biz or biz.lower() == "nan":
        return ""
    biz = biz.rstrip("。")
    if biz.startswith(("公司", "主营", "主要从事")):
        return biz + "。"
    return "公司主营" + biz + "。"


def _refine_boilerplate(sentence: str) -> str:
    """去掉"股票代码/全称"类样板前缀：从最后一个公司主语子句开始保留。"""
    if not any(marker in sentence for marker in ("股票代码", "全称", "证券简称")):
        return sentence
    clauses = [c for c in re.split(r"[，,]", sentence) if c]
    hit_idx = next(
        (i for i, c in enumerate(clauses) if any(k in c for k in _BIZ_KEYWORDS)),
        None,
    )
    if hit_idx is None or hit_idx == 0:
        return sentence
    start = 0
    for i in range(hit_idx):
        if clauses[i].startswith(("公司", "本公司", "本", "集团", "该")):
            start = i
    refined = "，".join(clauses[start:])
    return refined if refined else sentence


def _business_sentence(introduction: str, main_business: str, limit: int = 130) -> str:
    """从公司档案提取"这家公司是干什么的"一句话：介绍里的业务句 → 主业字段 → 首句。"""
    text = re.sub(r"\s+", "", str(introduction or ""))
    text = re.sub(r"\.(?=[一-龥])", "。", text)  # 半角句点后接中文视为句界
    if text:
        sentences = [s for s in re.split(r"(?<=[。！？])", text) if s]
        for sentence in sentences:
            if any(keyword in sentence for keyword in _BIZ_KEYWORDS):
                return _refine_boilerplate(sentence)[:limit] + (
                    "…" if len(sentence) > limit else ""
                )
        biz = _normalize_main_business(main_business)
        if biz:
            return biz
        first = sentences[0] if sentences else ""
        return first[:limit] + ("…" if len(first) > limit else "")
    return _normalize_main_business(main_business)


def _compose_company_line(
    biz: str | None, themes: list[str] | None, theme_stamp: str
) -> str | None:
    """个股介绍段落：做什么 + 主题指数（概念），全部来自本地事实。"""
    parts: list[str] = []
    if biz:
        parts.append(biz)
    if themes:
        parts.append(f"主题指数成分：{'、'.join(themes)}（最新记录{theme_stamp}）。")
    return "".join(parts) if parts else None


def company_profile_map(root: Path, as_of: datetime, codes: list[str]) -> dict[str, str]:
    """"是干什么的"业务句（company_profile，available_at <= as_of，每股取最新一份）。"""
    path = (
        root / "local_warehouse" / "facts" / "company_profile"
        / "catalog_version=company-profile" / "data.parquet"
    )
    if not path.is_file() or not codes:
        return {}
    frame = _cutoff_frame(pd.read_parquet(path), _as_utc_cutoff(as_of))
    frame = frame.loc[frame["ts_code"].astype(str).isin(codes)]
    profiles: dict[str, str] = {}
    for ts_code, group in frame.groupby(frame["ts_code"].astype(str)):
        row = group.iloc[-1]
        biz = _business_sentence(
            str(row.get("introduction") or ""), str(row.get("main_business") or "")
        )
        if biz:
            profiles[ts_code] = biz
    return profiles


def theme_names_map(
    root: Path, as_of: datetime, codes: list[str], limit: int = 4
) -> dict[str, list[str]]:
    """主题指数成分（概念来源：theme_member + theme_catalog，最新可用快照）。"""
    if not codes:
        return {}
    member_path = (
        root / "local_warehouse" / "facts" / "theme_member"
        / "catalog_version=official-theme-v1" / "data.parquet"
    )
    catalog_path = (
        root / "local_warehouse" / "facts" / "theme_catalog"
        / "catalog_version=official-theme-v1" / "data.parquet"
    )
    if not member_path.is_file() or not catalog_path.is_file():
        return {}
    catalog = pd.read_parquet(catalog_path)
    names = {
        str(code): str(name)
        for code, name in zip(catalog["theme_code"], catalog["theme_name"])
        if pd.notna(code) and pd.notna(name)
    }
    frame = _cutoff_frame(pd.read_parquet(member_path), _as_utc_cutoff(as_of))
    frame = frame.loc[frame["ts_code"].astype(str).isin(codes)]
    if frame.empty:
        return {}
    frame = frame.copy()
    frame["vf"] = pd.to_datetime(frame["valid_from"], errors="coerce")
    frame["sd"] = pd.to_datetime(frame["snapshot_date"], errors="coerce")
    as_of_day = _as_utc_cutoff(as_of).tz_localize(None).date()
    frame = frame.loc[frame["vf"].isna() | (frame["vf"].dt.date <= as_of_day)]
    frame = frame.sort_values("sd").drop_duplicates(["ts_code", "theme_code"], keep="last")
    result: dict[str, list[str]] = {}
    for row in frame.itertuples():
        theme = names.get(str(row.theme_code))
        if not theme:
            continue
        bucket = result.setdefault(str(row.ts_code), [])
        if theme not in bucket and len(bucket) < limit:
            bucket.append(theme)
    return result


def theme_snapshot_stamp(root: Path, as_of: datetime) -> str:
    """主题成员数据的最新快照月份标签（YYYY-MM），如实标注概念记录的时点。"""
    path = (
        root / "local_warehouse" / "facts" / "theme_member"
        / "catalog_version=official-theme-v1" / "data.parquet"
    )
    if not path.is_file():
        return ""
    frame = _cutoff_frame(pd.read_parquet(path), _as_utc_cutoff(as_of))
    if frame.empty:
        return ""
    latest = pd.to_datetime(frame["snapshot_date"], errors="coerce").max()
    return f"{latest.year}-{latest.month:02d}" if pd.notna(latest) else ""


def group_member_map(
    root: Path, as_of: datetime, group_codes: list[str]
) -> dict[str, list[str]]:
    """行业成分表（industry_member，时点有效成员），用于二级行业等权路径。"""
    if not group_codes:
        return {}
    path = (
        root / "local_warehouse" / "facts" / "industry_member"
        / "classification_version=SW2021" / "data.parquet"
    )
    if not path.is_file():
        return {}
    frame = _cutoff_frame(pd.read_parquet(path), _as_utc_cutoff(as_of))
    frame = frame.loc[frame["industry_code"].astype(str).isin(group_codes)]
    if frame.empty:
        return {}
    frame = frame.copy()
    frame["vf"] = pd.to_datetime(frame["valid_from"], errors="coerce")
    frame["vt"] = pd.to_datetime(frame["valid_to"], errors="coerce")
    as_of_day = _as_utc_cutoff(as_of).tz_localize(None).date()
    members: dict[str, set[str]] = {}
    for row in frame.itertuples():
        start_ok = pd.isna(row.vf) or row.vf.date() <= as_of_day
        end_ok = pd.isna(row.vt) or row.vt.date() >= as_of_day
        if start_ok and end_ok:
            members.setdefault(str(row.industry_code), set()).add(str(row.ts_code))
    return {code: sorted(values) for code, values in members.items() if values}


# ---------------------------------------------------------------------------
# 组装 V4 页面数据
# ---------------------------------------------------------------------------

def _short(text: str, limit: int) -> str:
    text = str(text or "").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _first_index_with_data(series: list[Any]) -> int | None:
    for index, value in enumerate(series):
        if value is not None:
            return index
    return None


def _first_bar_with_data(bars: list[list[Any]]) -> int | None:
    for index, bar in enumerate(bars):
        if bar[3] is not None:
            return index
    return None


def _events_for(
    action_iso: str,
    episode: dict[str, Any],
    review_items: list[dict[str, Any]],
) -> list[list[str]]:
    """公司与观察事件时间线：一天一条、公历日期、标题描述当天发生的事。

    D1 检查日与入选日必然同天，不重复收录（内容在正文交易日尺可看）；
    同日多个事件按 观点调整 > 里程碑 > 检查日 优先级保留一条。
    描述不截断，收起 / 展开由页面 CSS 处理。
    """
    events: list[list[str]] = [
        [
            action_iso[5:],
            "rec",
            "正式推荐",
            str(
                episode.get("original_selection_reason")
                or episode.get("original_primary_reason")
                or ""
            ),
        ]
    ]
    by_date: dict[str, tuple[int, list[str]]] = {}
    order: list[str] = []
    for item in review_items:
        date_key = item["date"][5:]
        summary = item.get("summary_copy") or item.get("copy", "")
        if item.get("viewChanged"):
            candidate = (
                2,
                [
                    date_key,
                    "view",
                    "观点调整",
                    item.get("fromTo") or item.get("viewReason") or summary,
                ],
            )
        elif item.get("checkpoint") in {"D3", "D5", "D10", "D20"}:
            candidate = (0, [date_key, "check", "", summary])
        else:
            continue
        if date_key in by_date:
            if candidate[0] > by_date[date_key][0]:
                by_date[date_key] = candidate
        else:
            by_date[date_key] = candidate
            order.append(date_key)
    first_close = episode.get("current_first_close_hit_20pct_date")
    if first_close:
        candidate = (
            1,
            [str(first_close)[5:], "milestone", "收盘达到20%", "推荐后收盘首次达到约20%涨幅"],
        )
        if candidate[1][0] in by_date:
            if candidate[0] > by_date[candidate[1][0]][0]:
                by_date[candidate[1][0]] = candidate
        else:
            by_date[candidate[1][0]] = candidate
            order.append(candidate[1][0])
    first_high = episode.get("current_first_high_hit_20pct_date")
    if first_high and not first_close:
        candidate = (
            1,
            [
                str(first_high)[5:],
                "milestone",
                "盘中触及20%",
                "盘中最高价涨幅一度达到约20%，收盘尚未达到",
            ],
        )
        if candidate[1][0] in by_date:
            if candidate[0] > by_date[candidate[1][0]][0]:
                by_date[candidate[1][0]] = candidate
        else:
            by_date[candidate[1][0]] = candidate
            order.append(candidate[1][0])
    frozen = episode.get("frozen_twenty_day_review")
    if frozen:
        candidate = (
            1,
            [
                str(episode.get("analysis_date"))[5:],
                "milestone",
                "20日观察结束",
                str(frozen.get("overall_review") or ""),
            ],
        )
        if candidate[1][0] in by_date:
            if candidate[0] > by_date[candidate[1][0]][0]:
                by_date[candidate[1][0]] = candidate
        else:
            by_date[candidate[1][0]] = candidate
            order.append(candidate[1][0])
    for date_key in sorted(order):
        events.append(by_date[date_key][1])
    return events


def sw_industry_code_map(
    root: Path, as_of: datetime, codes: list[str], level: str = "L2"
) -> dict[str, str]:
    """个股的申万行业代码（industry_member，时点有效），用于 D0 条目的行业兜底分组。"""
    if not codes:
        return {}
    path = (
        root / "local_warehouse" / "facts" / "industry_member"
        / "classification_version=SW2021" / "data.parquet"
    )
    if not path.is_file():
        return {}
    frame = _cutoff_frame(pd.read_parquet(path), _as_utc_cutoff(as_of))
    frame = frame.loc[
        frame["ts_code"].astype(str).isin(codes)
        & frame["level"].astype(str).eq(level)
    ]
    if frame.empty:
        return {}
    frame = frame.copy()
    frame["vf"] = pd.to_datetime(frame["valid_from"], errors="coerce")
    frame["vt"] = pd.to_datetime(frame["valid_to"], errors="coerce")
    as_of_day = _as_utc_cutoff(as_of).tz_localize(None).date()
    result: dict[str, str] = {}
    for row in frame.itertuples():
        current = str(getattr(row, "is_current")) in {"1", "1.0", "True", "true"}
        covers = (pd.isna(row.vf) or row.vf.date() <= as_of_day) and (
            pd.isna(row.vt) or row.vt.date() >= as_of_day
        )
        if not (current or covers):
            continue
        result.setdefault(str(row.ts_code), str(row.industry_code))
    return result


def load_d0_entries(
    selection_dir: Path, monitor_dir: Path, analysis_date: date
) -> tuple[list[dict[str, Any]], str]:
    """当晚定稿的最新报告才追加 D0：读取配对选股轨迹的 selected 候选。

    返回 (D0 条目列表, 轨迹 action_date)。历史日期（非最新候选报告）永不追加
    D0，保持历史页面语义不变；轨迹缺失 / 格式不符时返回空。
    """
    archived = archived_dates(monitor_dir)
    if not archived or max(archived) != analysis_date:
        return [], ""
    trace_path = selection_dir / f"research-trace-{analysis_date.isoformat()}.json"
    if not trace_path.is_file():
        return [], ""
    try:
        trace = json.loads(trace_path.read_text(encoding="utf-8"))
        trace_formation = str(trace.get("formation_date") or "")
        trace_action = str(trace.get("action_date") or "")
        if trace_formation != analysis_date.isoformat():
            return [], ""
        if not trace_action or trace_action <= analysis_date.isoformat():
            return [], ""
        risk_by_code: dict[str, str] = {}
        priority_by_code: dict[str, int] = {}
        research = trace.get("research_result") or {}
        for item in research.get("selected_stocks") or []:
            if not isinstance(item, dict):
                continue
            code = str(item.get("ts_code") or "")
            risk_by_code[code] = str(item.get("strongest_counterevidence") or "")
            priority = item.get("priority")
            if isinstance(priority, (int, float)):
                priority_by_code[code] = int(priority)
        entries: list[dict[str, Any]] = []
        for item in trace.get("candidate_ledger") or []:
            if not isinstance(item, dict) or str(item.get("final_fate")) != "selected":
                continue
            if selection_output_class(
                trace_version=str(trace.get("trace_version") or ""),
                candidate=item,
            ) not in {"confirmed_active", "legacy_v1_not_rewritten"}:
                continue
            code = str(item.get("ts_code") or "")
            if not code:
                continue
            entries.append(
                {
                    "ts_code": code,
                    "name": str(item.get("name") or code),
                    "reason": str(item.get("primary_reason") or ""),
                    "risk": risk_by_code.get(code, ""),
                    "priority": priority_by_code.get(code, 99),
                }
            )
        entries.sort(key=lambda item: item["priority"])
        return entries, trace_action
    except (OSError, json.JSONDecodeError, ValueError):
        return [], ""


def build_payload(
    root: Path,
    monitor_dir: Path,
    analysis_date: date,
    report: dict[str, Any],
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    as_of = str(report.get("as_of") or snapshot.get("as_of"))
    episodes = {
        str(item.get("episode_id")): item
        for item in snapshot.get("episodes", [])
        if isinstance(item, dict)
    }
    selected = [
        episode
        for episode in episodes.values()
        if episode.get("role") == "selected"
        and inferred_output_class(episode)
        in {"confirmed_active", "legacy_v1_not_rewritten", "conditional_event"}
    ]
    selected.sort(
        key=lambda item: (
            str(item.get("action_date")),
            int(item.get("original_priority") or 99),
        )
    )

    alert_by_episode: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    view_flags: dict[str, bool] = {}
    for alert in report.get("alerts", []):
        for review in alert.get("episode_reviews", []):
            episode_id = str(review.get("episode_id"))
            episode = episodes.get(episode_id, {})
            view = compute_view_change(review, episode.get("previous_episode_review"))
            alert_by_episode[episode_id] = (alert, review)
            view_flags[episode_id] = view["changed"]

    history = scan_history(monitor_dir, analysis_date)
    names = group_name_map(SELECTION_DIR)
    catalog = industry_catalog_names(root)

    # D0：最新报告页面把次日开盘前生效的新推荐以"待首日观察"列出（数据来自配对选股轨迹）
    d0_entries, d0_action_iso = load_d0_entries(
        SELECTION_DIR, monitor_dir, analysis_date
    )
    displayed_codes = {str(item["ts_code"]) for item in selected}
    d0_entries = [entry for entry in d0_entries if entry["ts_code"] not in displayed_codes]

    codes = sorted(
        {str(item["ts_code"]) for item in selected} | {entry["ts_code"] for entry in d0_entries}
    )
    group_codes = sorted(
        {
            str(item["original_group_code"])
            for item in selected
            if item.get("original_group_code")
        }
    )
    earliest_action = min(
        (str(item.get("action_date")) for item in selected if item.get("action_date")),
        default=analysis_date.isoformat(),
    )
    start = date.fromisoformat(earliest_action) - timedelta(days=20)
    sessions = list_sessions(root, start, analysis_date) or [analysis_date]

    as_of_dt = datetime.fromisoformat(as_of)
    # D0 条目无研究分组：用申万二级行业代码兜底，行业曲线与名称随之可得
    d0_group_map = sw_industry_code_map(
        root, as_of_dt, [entry["ts_code"] for entry in d0_entries]
    )
    for entry in d0_entries:
        entry["group_code"] = d0_group_map.get(entry["ts_code"], "")
    group_codes = sorted(set(group_codes) | {entry["group_code"] for entry in d0_entries if entry["group_code"]})
    group_members = group_member_map(root, as_of_dt, group_codes)
    profiles = company_profile_map(root, as_of_dt, codes)
    theme_map = theme_names_map(root, as_of_dt, codes)
    theme_stamp = theme_snapshot_stamp(root, as_of_dt)
    facts = collect_market_facts(
        root, as_of_dt, sessions, group_codes, codes, group_members=group_members
    )
    # 全局裁剪：从第一个有任何事实的交易日开始，保证 DATES / market / industry / candles 对齐
    candidates = [
        index
        for index in (_first_index_with_data(facts["market"]),
                      min(
                          (
                              value
                              for value in (
                                  _first_bar_with_data(facts["candles"][code])
                                  for code in codes
                              )
                              if value is not None
                          ),
                          default=None,
                      ),
                      *[
                          _first_index_with_data(facts["industry"][code])
                          for code in group_codes
                      ])
        if index is not None
    ]
    trim = min(candidates) if candidates else 0
    sessions = sessions[trim:]
    market_series = facts["market"][trim:]
    industry_series = {
        code: values[trim:] for code, values in facts["industry"].items()
    }
    candle_series = {code: values[trim:] for code, values in facts["candles"].items()}

    stocks_payload: list[dict[str, Any]] = []
    for episode in selected:
        episode_id = str(episode["episode_id"])
        ts_code = str(episode["ts_code"])
        action_iso = str(episode.get("action_date") or analysis_date.isoformat())
        rec_index = next(
            (i for i, day in enumerate(sessions) if day.isoformat() == action_iso), 0
        )
        raw_candles = candle_series.get(ts_code, [])
        # 与全局交易日窗口严格对齐（事件/推荐日之前仅作背景，图中淡化显示）
        bars = [list(bar) for bar in raw_candles]
        ref = None
        ref_kind = None
        formal = inferred_output_class(episode) in {
            "confirmed_active",
            "legacy_v1_not_rewritten",
        }
        if formal:
            action_bar = bars[rec_index] if rec_index < len(bars) else None
            if action_bar and action_bar[0] is not None:
                ref = action_bar[0]
                ref_kind = "formal"
        else:
            # 事件等待型：程序记录的事件首次定价日为观察起点，参考价取当日原始开盘价
            reaction = episode.get("first_event_reaction") or {}
            reaction_iso = str(reaction.get("trade_date") or "")
            reaction_index = next(
                (
                    i
                    for i, day in enumerate(sessions)
                    if day.isoformat() == reaction_iso
                ),
                None,
            )
            if (
                reaction_index is not None
                and reaction_index < len(bars)
                and bars[reaction_index][0] is not None
            ):
                ref = bars[reaction_index][0]
                rec_index = reaction_index
                ref_kind = "event"
        has_post = any(bar[3] is not None for bar in bars[rec_index:])
        suspended = not has_post

        alert = alert_by_episode[episode_id][0] if episode_id in alert_by_episode else None
        if alert:
            state = str(alert.get("monitor_state"))
            stage_label, stage_type = stage_of(state)
        elif episode.get("previous_monitor_state"):
            stage_label, stage_type = stage_of(str(episode["previous_monitor_state"]))
        elif episode.get("previous_episode_review"):
            stage_label, stage_type = stage_of(
                str(episode["previous_episode_review"].get("current_assessment"))
            )
        elif episode.get("original_engine_type") == "fresh_event_pending":
            stage_label, stage_type = "等待事件", "paused"
        else:
            stage_label, stage_type = "暂无复盘", "paused"
        if suspended:
            stage_label, stage_type = "无法执行", "paused"

        thesis = episode.get("original_research_thesis") or {}
        company_info = thesis.get("company_information") or {}
        review_items = history.get(episode_id, [])
        reviews = [item for item in review_items if not item.get("eventOnly")]
        group_code = str(episode.get("original_group_code") or "")
        industry_kind = facts.get("industry_kind", {}).get(group_code, "none")
        stocks_payload.append(
            {
                "code": ts_code,
                "name": str(episode.get("name") or ts_code),
                "recDate": action_iso,
                "recIndex": rec_index,
                "ref": ref,
                "refKind": ref_kind,
                "days": int(episode.get("day_number") or 0),
                "phase": str(episode.get("monitor_phase") or "primary"),
                "stage": stage_label,
                "stageType": stage_type,
                "attention": episode_id in alert_by_episode,
                "trigger": (
                    trigger_of(alert, view_flags.get(episode_id, False))
                    if alert
                    else ""
                ),
                "suspended": suspended,
                "company": _compose_company_line(
                    profiles.get(ts_code),
                    theme_map.get(ts_code),
                    theme_stamp,
                )
                or (company_info.get("basis") or thesis.get("fundamental_anchor") or None),
                "reasonFull": str(
                    episode.get("original_selection_reason")
                    or episode.get("original_primary_reason")
                    or ""
                ),
                "reasonRisk": str(episode.get("original_strongest_counterevidence") or ""),
                "industryName": names.get(group_code) or catalog.get(group_code)
                or (thesis.get("sector_broad_diffusion") or {}).get("group_name")
                or (thesis.get("sector_leader_cluster") or {}).get("group_name"),
                "industrySource": industry_kind,
                "industry": industry_series.get(group_code, []),
                "candles": bars,
                "reviews": reviews,
                "events": _events_for(action_iso, episode, review_items),
            }
        )
    # D0 条目：只有推荐结论与历史价格背景，参考价/收益/复盘一律留空待 D1 定价
    for entry in d0_entries:
        ts_code = entry["ts_code"]
        group_code = entry.get("group_code") or ""
        rec_index = max(0, len(sessions) - 1)
        stocks_payload.append(
            {
                "code": ts_code,
                "name": entry["name"],
                "recDate": d0_action_iso,
                "recIndex": rec_index,
                "ref": None,
                "refKind": None,
                "days": 0,
                "phase": "primary",
                "stage": "待首日观察",
                "stageType": "pending",
                "attention": False,
                "trigger": "",
                "suspended": False,
                "d0": True,
                "company": profiles.get(ts_code) or None,
                "reasonFull": entry["reason"],
                "reasonRisk": entry["risk"],
                "industryName": names.get(group_code) or catalog.get(group_code) or None,
                "industrySource": facts.get("industry_kind", {}).get(group_code, "none"),
                "industry": industry_series.get(group_code, []),
                "candles": candle_series.get(ts_code, []),
                "reviews": [],
                "events": [
                    [
                        d0_action_iso[5:],
                        "rec",
                        "正式推荐",
                        _short(entry["reason"], 48),
                    ]
                ],
            }
        )
    stocks_payload.sort(key=lambda item: (item["recDate"], item["code"]), reverse=True)

    date_files = [
        {"file": f"monitor-report-{day.isoformat()}.html", "label": day.isoformat()}
        for day in archived_dates(monitor_dir)
    ]
    review_dates = sorted(
        {
            day.isoformat()
            for day in ledger_dates(monitor_dir)
            if day <= analysis_date
        }
        | {analysis_date.isoformat()},
        reverse=True,
    )
    return {
        "analysis_date": analysis_date.isoformat(),
        "as_of": as_of,
        "market_name": MARKET_NAME,
        "dates": [day.isoformat()[5:] for day in sessions],
        "market": market_series,
        "date_files": date_files,
        "review_dates": review_dates,
        "stocks": stocks_payload,
    }


# ---------------------------------------------------------------------------
# HTML 模板（版式与交互严格对应 UI_Demo_V4，数据全部来自真实归档）
# ---------------------------------------------------------------------------

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>推荐观察台 · 观察日报 V4</title>
<style>
:root{
  color-scheme:light;
  --paper:#f7f6f2;--paper2:#efede6;--ink:#1c1a15;--ink2:#55524a;--ink3:#8f8b7f;
  --hair:rgba(28,26,21,.16);--hair2:rgba(28,26,21,.09);--rule:#26241d;
  --up:#c53220;--down:#0e7d4d;--blue:#2c5fe0;--amber:#a86a08;--violet:#6d4aa8;
  --warn-fg:#ffffff;
  --accent:var(--blue);--purple:var(--violet);--muted:var(--ink3);--soft:var(--ink2);--grid:var(--hair2);--panel:var(--paper);--panel2:var(--paper2);
  --warn:var(--amber);
  --serif:"Noto Serif SC","Source Han Serif SC","Songti SC","STSong","SimSun",serif;
  --sans:-apple-system,BlinkMacSystemFont,"SF Pro Text","PingFang SC","Hiragino Sans GB","Microsoft YaHei","Segoe UI",Arial,sans-serif;
}
body.dark{
  color-scheme:dark;
  --paper:#151519;--paper2:#1d1d23;--ink:#ece9df;--ink2:#b3afa2;--ink3:#7d7970;
  --hair:rgba(236,233,223,.17);--hair2:rgba(236,233,223,.09);--rule:#ece9df;
  --up:#ff6b57;--down:#3ecf8e;--blue:#7aa2ff;--amber:#e0a63e;--violet:#b79cff;
  --warn-fg:#151519;
  --accent:var(--blue);--purple:var(--violet);--muted:var(--ink3);--soft:var(--ink2);--grid:var(--hair2);--panel:var(--paper);--panel2:var(--paper2);
  --warn:var(--amber);
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
html,body{overflow-x:clip}
html,body{margin:0;background:var(--paper);color:var(--ink);
  font-family:var(--sans);-webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}
::selection{background:rgba(44,95,224,.18)}
body.dark ::selection{background:rgba(122,162,255,.3)}
::-webkit-scrollbar{width:10px;height:8px}
::-webkit-scrollbar-thumb{background:var(--hair);border-radius:8px;border:2px solid transparent;background-clip:content-box}
::-webkit-scrollbar-track{background:transparent}
button,input,select{font:inherit;color:inherit}
button{background:none;border:0;padding:0;cursor:pointer;text-align:inherit}
button:active{transform:translateY(1px)}
:focus-visible{outline:2px solid var(--blue);outline-offset:2px}
.sheet{max-width:1240px;margin:0 auto;padding:0 36px 70px}
/* ---------- 报头 ---------- */
.masthead{display:flex;align-items:flex-end;justify-content:space-between;gap:18px;padding:30px 0 16px;border-bottom:3px double var(--rule);flex-wrap:wrap}
.wordmark{font-family:var(--serif);font-size:27px;font-weight:900;letter-spacing:.14em;line-height:1;color:var(--ink);display:flex;align-items:baseline;gap:14px}
.wm-sub{font-family:var(--sans);font-size:10px;font-weight:500;letter-spacing:.22em;color:var(--ink3)}
.mast-right{display:flex;align-items:center;gap:16px}
.dateline{font-size:12.5px;color:var(--ink2);letter-spacing:.04em;font-variant-numeric:tabular-nums}
.iconlink{font-size:15px;color:var(--ink2);border:1px solid var(--hair);border-radius:999px;width:32px;height:32px;display:grid;place-items:center;transition:.25s}
.iconlink:hover{color:var(--ink);border-color:var(--ink)}
/* ---------- 页面切换 ---------- */
.page{display:none}.page.active{display:block;animation:pagein .45s ease}
@keyframes pagein{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}
.up{color:var(--up)!important}.down{color:var(--down)!important}.dim{color:var(--ink3)!important}
/* 统计行：数字即筛选 */
.statline{display:flex;gap:6px 30px;flex-wrap:wrap;align-items:baseline;padding:20px 0 18px;border-bottom:1px solid var(--hair);margin-bottom:4px}
.stat{display:flex;align-items:baseline;gap:8px;color:var(--ink2);padding:2px 2px 5px;border-bottom:2px solid transparent;transition:.2s}
.stat b{font-size:21px;font-weight:750;color:var(--ink);font-variant-numeric:tabular-nums;letter-spacing:-.01em}
.stat:hover{color:var(--ink)}
.stat.active{color:var(--ink);border-bottom-color:var(--up)}
.stat.active b{color:var(--up)}
/* 重点观察 */
.key-head{display:flex;align-items:baseline;justify-content:space-between;gap:14px;flex-wrap:wrap;margin-top:34px;padding-top:8px;border-top:2px solid var(--rule)}
.key-head h2{font-family:var(--serif);font-size:22px;font-weight:800;margin:0;letter-spacing:.02em}
.key-tools{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.key-tools .klabel{font-size:10.5px;letter-spacing:.18em;color:var(--ink3)}
.quietbtn{display:inline-flex;align-items:center;font-size:12.5px;color:var(--ink2);border:1px solid var(--hair);border-radius:8px;padding:5px 12px;background:transparent;transition:.2s;line-height:1.5}
.quietbtn:hover{color:var(--ink);border-color:var(--ink2)}
select.quietbtn{appearance:none;-webkit-appearance:none;cursor:pointer;color:var(--ink);padding:5px 26px 5px 12px;
 background-image:linear-gradient(45deg,transparent 50%,var(--ink3) 50%),linear-gradient(135deg,var(--ink3) 50%,transparent 50%);
 background-position:calc(100% - 15px) 55%,calc(100% - 10px) 55%;background-size:5px 5px,5px 5px;background-repeat:no-repeat}
select.quietbtn option{background:var(--panel);color:var(--ink);font-size:13px}
.key-note{font-size:12.5px;color:var(--ink2);margin:10px 0 0}
/* 头版要闻 */
.stories{border-top:2px solid var(--rule);margin-top:8px}
.stories.collapsed{display:none}
.story{display:grid;grid-template-columns:64px minmax(0,1fr) 210px;gap:4px 26px;align-items:start;
  padding:22px 10px 24px;border-bottom:1px solid var(--hair2);cursor:pointer;transition:background .25s}
.story:hover{background:var(--paper2)}
.story-no{font-family:var(--serif);font-size:24px;color:var(--ink3);font-style:italic;line-height:1.15;font-variant-numeric:tabular-nums}
.story-name{font-family:var(--serif);font-size:20px;font-weight:800;letter-spacing:.01em;line-height:1.2}
.story-name small{font-family:var(--sans);font-size:11.5px;font-weight:400;color:var(--ink3);margin-left:9px;letter-spacing:.03em}
.story-headline{font-family:var(--serif);font-size:18.5px;font-weight:650;line-height:1.55;margin-top:7px;color:var(--ink)}
.story-headline .hlmark{color:var(--amber);margin-right:6px}
.story-side{text-align:right;display:grid;gap:7px;justify-items:end;padding-top:2px}
.story-ret{font-size:23px;font-weight:750;font-variant-numeric:tabular-nums;letter-spacing:-.01em;line-height:1}
.story-tags{display:flex;gap:6px 12px;flex-wrap:wrap;justify-content:flex-end;font-size:11.5px;color:var(--ink2)}
.story-tags .stage{font-weight:600}
.story-tags .trigger{color:var(--ink3);letter-spacing:.03em}
.story-tags .before-after{color:var(--amber)}
/* 账目列表 */
.ledger-head{display:flex;align-items:baseline;justify-content:space-between;gap:14px;flex-wrap:wrap;margin-top:44px;padding-top:8px;border-top:2px solid var(--rule)}
.ledger-head h2{font-family:var(--serif);font-size:22px;font-weight:800;margin:0;letter-spacing:.02em}
.tabs{display:flex;gap:4px 20px;flex-wrap:wrap;align-items:baseline}
.tab{font-size:13px;color:var(--ink2);padding-bottom:5px;border-bottom:2px solid transparent;transition:.2s;display:flex;gap:5px;align-items:baseline}
.tab i{font-style:normal;font-size:12px;color:var(--ink3);font-variant-numeric:tabular-nums}
.tab:hover{color:var(--ink)}
.tab.active{color:var(--ink);border-bottom-color:var(--up);font-weight:600}
.tab.active i{color:var(--ink)}
.searchline{display:flex;justify-content:flex-end;padding:14px 0 4px;gap:18px;align-items:center}
.pickline{display:flex;gap:8px;align-items:center;font-size:12.5px;color:var(--ink2)}
.search,.stockpick{background:transparent;border:0;border-bottom:1px solid var(--hair);color:var(--ink);padding:6px 2px;width:220px;font-size:13px}
.stockpick{width:auto;max-width:300px}
.search:focus,.stockpick:focus{outline:none;border-bottom-color:var(--ink)}
.search::placeholder{color:var(--ink3)}
.ledger-wrap{overflow-x:auto}
.ledger{width:100%;min-width:660px;border-collapse:collapse;margin-top:6px}
.ledger th{font-size:10.5px;font-weight:600;letter-spacing:.16em;color:var(--ink3);text-align:left;padding:12px 14px 10px;border-bottom:1px solid var(--hair)}
.ledger th.sortable{cursor:pointer;user-select:none;white-space:nowrap;transition:.2s}
.ledger th.sortable:hover{color:var(--ink)}
.ledger th.sorted{color:var(--ink)}
.ledger th .arrs{font-size:9px;margin-left:3px;color:var(--up)}
.ledger td{padding:15px 14px;border-bottom:1px solid var(--hair2);font-size:13px;font-variant-numeric:tabular-nums;vertical-align:middle}
.ledger tbody tr{cursor:pointer;transition:background .2s}
.ledger tbody tr:hover{background:var(--paper2)}
.ledger .l-name{font-family:var(--serif);font-weight:700;font-size:15.5px}
.ledger .l-code{color:var(--ink3);font-size:11px;margin-left:7px;letter-spacing:.02em}
.ledger .l-ret{font-weight:700;font-size:14px}
.ledger .l-dim{color:var(--ink2)}
.ledger .stage{font-weight:600;font-size:12.5px}
.ledger .arr{color:var(--ink3);font-size:15px}
.tr:hover .arr{color:var(--ink)}
.stage::before{content:"";display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:7px;vertical-align:1px}
.stage-strong{color:var(--up)}.stage-strong::before{background:var(--up)}
.stage-sideways{color:var(--amber)}.stage-sideways::before{background:var(--amber)}
.stage-weak{color:var(--down)}.stage-weak::before{background:var(--down)}
.stage-paused{color:var(--ink3)}.stage-paused::before{background:var(--ink3)}
.stage-pending{color:var(--accent)}.stage-pending::before{background:var(--accent)}
.pbar{width:86px;height:3px;background:var(--hair2);border-radius:2px;overflow:hidden;margin-top:6px}
.pbar i{display:block;height:100%;background:var(--ink2)}
/* ---------- 个股：正文页 ---------- */
.backlink{display:inline-block;margin:26px 0 4px;font-size:13px;color:var(--ink2)}
.backlink:hover{color:var(--ink)}
.story-header{display:flex;justify-content:space-between;gap:18px;align-items:flex-end;flex-wrap:wrap;
  padding:6px 0 20px;border-bottom:2px solid var(--rule)}
.titleline{display:flex;align-items:baseline;gap:13px;flex-wrap:wrap}
.titleline h2{font-family:var(--serif);font-size:clamp(30px,3vw,44px);font-weight:800;margin:0;line-height:1.1}
.titleline .code{font-size:13px;color:var(--ink3);letter-spacing:.04em}
.titleline .state{font-size:11.5px;color:var(--ink2);border:1px solid var(--hair);border-radius:999px;padding:3px 11px;letter-spacing:.05em}
.companyline{margin:10px 0 0;font-size:13px;color:var(--ink2);line-height:1.7;max-width:62em}
/* 推荐理由（仅 D1 / 待首日观察显示） */
.reason-block{margin:16px 0 0;padding:13px 18px 12px;border:1px solid var(--hair);border-left:3px solid var(--accent);border-radius:0 10px 10px 0;background:var(--panel2)}
.reason-block p{margin:0;font-size:13px;line-height:1.9;color:var(--ink2);max-width:62em}
.reason-block .risk{margin-top:8px;padding-top:8px;border-top:1px dashed var(--hair2);font-size:12px;color:var(--ink3)}
.reason-block .risk b{color:var(--down);font-weight:650;margin-right:8px;font-size:11px;letter-spacing:.1em}
/* 数字行 */
.ticker-strip{display:flex;border-bottom:1px solid var(--hair);padding:18px 0;overflow-x:auto;scrollbar-width:none}
.quote-strip{padding:16px 0 10px;border-bottom:0}
.quote-strip + .ticker-strip{padding-top:6px}
.quote-strip .tv{font-variant-numeric:tabular-nums}
.ticker-strip::-webkit-scrollbar{display:none}
.tick{flex:1 1 0;min-width:118px;padding:2px 22px;border-left:1px solid var(--hair2)}
.tick:first-child{border-left:0;padding-left:0}
.tick .tl{font-size:10.5px;letter-spacing:.16em;color:var(--ink3);margin-bottom:8px}
.tick .tv{font-size:23px;font-weight:750;font-variant-numeric:tabular-nums;letter-spacing:-.01em}
.tick .ts{font-size:10.5px;color:var(--ink3);margin-top:6px}
/* 图表区 */
.chart-sec{margin-top:26px}
.sec-labelrow{display:flex;align-items:center;justify-content:space-between;gap:14px;flex-wrap:wrap;margin-bottom:12px}
.sec-label{font-size:11px;font-weight:650;letter-spacing:.2em;color:var(--ink3)}
.sec-right{display:flex;gap:16px;align-items:center;flex-wrap:wrap}
.seg{display:inline-flex;border:1px solid var(--hair);border-radius:999px;padding:2px}
.seg button{font-size:12px;color:var(--ink2);border-radius:999px;padding:5px 14px;transition:.2s}
.seg button.on{background:var(--ink);color:var(--paper)}
.legend{display:flex;gap:14px;font-size:11px;color:var(--ink2);align-items:center;flex-wrap:wrap}
.legend i{display:inline-block;width:14px;height:0;border-top:2px solid;margin-right:5px;vertical-align:middle;border-radius:2px}
.chart-wrap{position:relative;height:clamp(400px,50vh,620px)}
.chart-svg{width:100%;height:100%;display:block}
.chart-tip{position:absolute;display:none;pointer-events:none;background:var(--paper);border:1px solid var(--hair);border-radius:8px;padding:9px 12px;font-size:10.5px;color:var(--ink2);line-height:1.7;z-index:3;min-width:150px;box-shadow:0 10px 30px rgba(0,0,0,.12);font-variant-numeric:tabular-nums}
body.dark .chart-tip{box-shadow:0 14px 36px rgba(0,0,0,.5)}
/* 交易日尺 */
.dayruler{display:flex;gap:6px;overflow-x:auto;padding:16px 0 6px;border-top:1px solid var(--hair);margin-top:14px;scrollbar-width:none}
.dayruler::-webkit-scrollbar{display:none}
.day-btn{min-width:56px;flex:0 0 auto;text-align:center;padding:7px 6px 8px;border-radius:8px;color:var(--ink3);position:relative;transition:.2s}
.day-btn b{display:block;font-size:12px;font-weight:650;color:var(--ink2);margin-bottom:3px;font-variant-numeric:tabular-nums}
.day-btn span{display:block;font-size:10px;font-variant-numeric:tabular-nums}
.day-btn.observed:hover,.day-btn.preview{background:var(--paper2);color:var(--ink)}
.day-btn.active{background:var(--ink);color:var(--paper)}
.day-btn.active b,.day-btn.active span{color:var(--paper)}
.day-btn.future{opacity:.32;cursor:default}
.day-btn .vcdot{position:absolute;top:5px;right:7px;width:5px;height:5px;border-radius:50%;background:var(--amber)}
.day-btn .recdot{position:absolute;top:5px;right:7px;width:5px;height:5px;border-radius:50%;background:var(--blue)}
body.dark .day-btn .vcdot{box-shadow:0 0 0 3px rgba(224,166,62,.2)}
/* 正文 + 边栏 */
.article-grid{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:0 56px;margin-top:30px}
.article{border-top:2px solid var(--rule);padding-top:18px}
.article-top{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:14px}
.article-top .adate{font-size:11.5px;letter-spacing:.14em;color:var(--ink3);font-variant-numeric:tabular-nums}
.article-top .abadges{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.badge{font-size:10.5px;font-weight:650;letter-spacing:.06em;color:var(--amber)}
.badge::before{content:"▍";margin-right:2px}
.textlink{font-size:12px;color:var(--blue);border-bottom:1px solid rgba(44,95,224,.35);padding-bottom:1px}
.textlink:hover{border-bottom-color:var(--blue)}
.r-headline{font-family:var(--serif);font-size:clamp(22px,2vw,29px);font-weight:800;line-height:1.45;margin:0 0 16px;letter-spacing:.005em}
.r-copy{font-size:14.5px;line-height:2.05;color:var(--soft2,var(--ink2));margin:0;max-width:40em;white-space:pre-line}
body.dark .r-copy{color:var(--ink2)}
/* 复盘内容（按所选交易日填充） */
.rev-grid{margin-top:18px;border-top:1px solid var(--hair2);padding-top:12px}
.cap{display:block;font-size:10px;font-weight:650;letter-spacing:.22em;color:var(--ink3);margin-bottom:7px}
.rev-row{display:grid;grid-template-columns:92px 1fr;gap:14px;padding:10px 0;border-bottom:1px dashed var(--hair2);font-size:12.5px;line-height:1.85}
.rev-row:last-child{border-bottom:0}
.rev-row .rk{font-size:10px;font-weight:650;letter-spacing:.18em;color:var(--ink3);padding-top:4px}
.rev-row .rv{color:var(--ink2);font-variant-numeric:tabular-nums}
.rev-row .rv b{color:var(--ink);font-weight:650}
.rev-row .fx{color:var(--ink)}
.rail-note{font-size:12px;color:var(--ink3);line-height:1.8;margin:8px 0 0}
/* 边栏 */
.rail{display:grid;gap:30px;align-content:start;border-top:2px solid var(--rule);padding-top:18px}
.rail h4{margin:0 0 12px}
.thesis-row{padding:11px 0;border-bottom:1px solid var(--hair2);font-size:12.5px;line-height:1.75}
.thesis-row .tk{display:block;font-size:10px;letter-spacing:.18em;color:var(--ink3);margin-bottom:5px;font-weight:650}
.thesis-row .tv2{color:var(--ink2)}
.event-row{display:grid;grid-template-columns:44px 12px 1fr;gap:8px;padding:10px 0;border-bottom:1px solid var(--hair2);align-items:start}
.e-date{font-size:10.5px;color:var(--ink3);padding-top:3px;font-variant-numeric:tabular-nums}
.e-dot{width:7px;height:7px;border-radius:50%;background:var(--ink3);margin-top:5px;justify-self:center}
.e-dot.rec{background:var(--blue)}.e-dot.view{background:var(--amber)}.e-dot.milestone{background:var(--ink)}
.e-dot.check{background:var(--blue);opacity:.55}
.e-title{font-size:12px;font-weight:650;display:block;margin-bottom:3px}
.e-check{font-style:normal;font-size:9.5px;font-weight:500;color:var(--ink3);margin-left:6px;letter-spacing:.05em}
.e-desc{font-size:11px;color:var(--ink3);line-height:1.65;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.event-row.open .e-desc{display:block;-webkit-line-clamp:unset}
.event-row{cursor:pointer}
.event-row.open .e-dot{background:var(--accent)}
/* 页脚 */
.colophon{margin-top:64px;padding-top:16px;border-top:1px solid var(--hair);font-size:11px;color:var(--ink3);line-height:1.9;display:flex;justify-content:space-between;gap:14px;flex-wrap:wrap}
/* 提示 */
.toast{position:fixed;left:50%;bottom:30px;transform:translateX(-50%) translateY(12px);background:var(--ink);color:var(--paper);padding:11px 20px;border-radius:999px;font-size:12.5px;opacity:0;transition:.3s;z-index:60;pointer-events:none}
.toast.show{opacity:1;transform:translateX(-50%)}
/* 滚动显现 */
.reveal{opacity:0;transform:translateY(14px);transition:opacity .6s ease,transform .6s cubic-bezier(.22,1,.36,1)}
.reveal.in{opacity:1;transform:none}
@media (prefers-reduced-motion:reduce){
  html{scroll-behavior:auto}
  .reveal{opacity:1;transform:none;transition:none}
  .page.active{animation:none}
  *{transition:none!important;animation:none!important}
}
@media(min-width:1900px){
  .sheet{max-width:1480px;padding:0 56px 80px}
  .story-headline{font-size:21px}
  .story-name{font-size:23px}
  .story-ret{font-size:27px}
  .tick .tv{font-size:27px}
  .r-copy{font-size:15.5px}
  .r-headline{font-size:32px}
  .chart-wrap{height:clamp(460px,52vh,660px)}
  .ledger td{font-size:14px;padding:17px 18px}
  .ledger .l-name{font-size:17px}
}
@media(max-width:1080px){
  .sheet{padding:0 26px 60px}
  .article-grid{grid-template-columns:1fr;gap:34px}
  .rail{border-top-width:1px;padding-top:14px}
}
@media(max-width:720px){
  .sheet{padding:0 18px 50px}
  .masthead{padding:20px 0 12px}
  .wordmark{font-size:21px;letter-spacing:.1em}
  .story{grid-template-columns:1fr;gap:10px;padding:18px 2px}
  .story-no{display:none}
  .story-side{grid-auto-flow:column;justify-items:start;justify-content:space-between;text-align:left;width:100%;align-items:center}
  .story-tags{justify-content:flex-start}
  .tick{min-width:104px}
  .chart-wrap{height:min(88vw,400px)}
  .r-copy{font-size:14px}
  .companyline{display:none}
}
</style>
</head>
<body>
<div class="sheet">
  <header class="masthead">
    <button class="wordmark" id="homeBtn">推荐观察台<span class="wm-sub">A股正式推荐 · 观点跟踪</span></button>
    <div class="mast-right">
      <span class="dateline" id="dateline"></span>
      <button class="iconlink" id="themeBtn" title="切换明暗">◐</button>
    </div>
  </header>

  <main>
    <section id="overviewPage" class="page active">
      <div class="statline" id="statline"></div>

      <div class="key-head">
        <h2>重点观察</h2>
        <div class="key-tools">
          <span class="klabel">复盘日期</span>
          <select class="quietbtn" id="dateSelect" title="只切换重点观察栏的复盘日期，不改变本页日报"></select>
          <button class="quietbtn" id="collapseBtn">缩起</button>
        </div>
      </div>
      <p class="key-note" id="keyNote"></p>
      <div class="stories" id="stories"></div>
      <p class="key-note" id="collapsedNote" style="display:none"></p>

      <div class="ledger-head">
        <h2>全部观察</h2>
        <div class="tabs" id="tabs"></div>
      </div>
      <div class="searchline">
        <span class="pickline">选择股票 <select class="stockpick" id="stockPick"></select></span>
        <input class="search" id="searchInput" placeholder="检索股票或代码" />
      </div>
      <div class="ledger-wrap">
        <table class="ledger">
          <thead><tr><th>股票</th><th class="sortable" data-sort="progress">观察进度<span class="arrs" id="arrProgress"></span></th><th>当前 / 最高收盘</th><th class="sortable" data-sort="toT">距 20%<span class="arrs" id="arrToT"></span></th><th>阶段</th><th>下一检查日</th><th></th></tr></thead>
          <tbody id="ledgerRows"></tbody>
        </table>
      </div>
    </section>

    <section id="detailPage" class="page">
      <button class="backlink" id="backBtn">← 返回头版</button>
      <div class="story-header">
        <div>
          <div class="titleline"><h2 id="dName"></h2><span class="code" id="dCode"></span><span class="state" id="dStatus"></span></div>
          <p class="companyline" id="dCompany"></p>
        </div>
      </div>
      <div class="ticker-strip quote-strip" id="quoteStrip"></div>
      <div class="ticker-strip" id="tickerStrip"></div>

      <div class="chart-sec">
        <div class="sec-labelrow">
          <span class="sec-label">事实 · 价格与成交</span>
          <div class="sec-right">
            <div class="seg" id="chartSeg"><button data-m="candle" class="on">K线</button><button data-m="rel">相对表现</button></div>
            <div class="legend">
              <span id="refLegend"><i style="border-color:var(--blue);border-top-style:dashed"></i><span id="refLegendTxt">推荐参考价</span></span>
              <span id="targetLegend"><i style="border-color:var(--amber);border-top-style:dashed"></i>20%目标</span>
              <span id="maLegend" style="display:none"><i style="border-color:var(--violet)"></i>MA5</span>
              <span id="maLegend2" style="display:none"><i style="border-color:var(--ink3);border-top-style:dashed"></i>MA10</span>
              <span id="relLegend" style="display:none"><i style="border-color:var(--violet)"></i><span id="relLegendTxt">行业</span></span>
              <span id="relLegend2" style="display:none"><i style="border-color:var(--ink3);border-top-style:dashed"></i>市场</span>
              <span id="relLegend3" style="display:none"><i style="border-color:var(--amber);border-top-style:dashed"></i>20%目标(120)</span>
            </div>
          </div>
        </div>
        <div class="chart-wrap"><svg id="chartSvg" class="chart-svg"></svg><div id="chartTip" class="chart-tip"></div></div>
        <div class="dayruler" id="timeline"></div>
      </div>

      <div class="article-grid">
        <article class="article reveal">
          <div class="article-top"><span class="adate" id="rDate"></span><span class="abadges" id="rBadges"></span></div>
          <div class="reason-block" id="rReason" style="display:none"></div>
          <h3 class="r-headline" id="rHeadline" style="margin-top:20px"></h3>
          <p class="r-copy" id="rCopy"></p>
          <div class="rev-grid" id="rReview"></div>
        </article>
        <aside class="rail reveal">
          <div class="rail-sec">
            <h4 class="cap">公司与观察事件</h4>
            <p class="rail-note">只收录研究结论：正式推荐、检查日复盘、观点调整与目标里程碑。</p>
            <div id="events"></div>
          </div>
        </aside>
      </div>
    </section>
  </main>

  <footer class="colophon">
    <span>推荐观察台 · 观察日报 V4 —— 图表负责事实，正文只写观点。行情为交易所原始价格；行业路径为申万二级行业成分等权（数据不足时如实断线）。</span>
    <span>观察窗口 20 个交易日 · 观点变化以 ▍ 标注</span>
  </footer>
</div>
<div class="toast" id="toast"></div>
<script>
const DATA = __PAGE_DATA__;
const DATES = DATA.dates, MARKET = DATA.market, stocks = DATA.stocks;

/* ---------- 工具与状态 ---------- */
const $ = id => document.getElementById(id);
function storeGet(k){try{return localStorage.getItem(k)}catch(e){return null}}
function storeSet(k,v){try{return localStorage.setItem(k,v)}catch(e){}}
let cur = stocks[0], selDay = null, selReview = null, hoverI = -1, hoverY = 0, relMode = false, activeFilter = "all", keyCollapsed = false,
 keyDate = DATA.analysis_date, sortKey = null, sortDir = -1;
const pct = v => v == null ? "—" : (v > 0 ? "+" : "") + v.toFixed(2) + "%";
function dayLabel(n){return n > 20 ? `延长观察第${n - 20}天` : `D${n}`}
function progressText(s){
 if(s.d0)return"待首日观察";
 if(s.days > 20)return`延长观察第${s.days - 20}天`;
 return`D${s.days}/20`;
}
function latestQuote(s){
 for(let i = s.candles.length - 1;i >= 0;i--){const d = s.candles[i];
  if(d && d[3] != null)return{i,d,prev:i > 0 ? s.candles[i - 1] : null}}
 return null;
}
function renderQuoteStrip(s){
 const q = latestQuote(s),el = $("quoteStrip");
 if(!q){el.innerHTML = "";return}
 const {i,d,prev} = q;
 const dayChg = prev && prev[3] != null ? (d[3] / prev[3] - 1) * 100 : null;
 const haltNote = s.suspended ? `${DATES[i]}停牌前` : "";
 const cells = [
  ["开盘",d[0] == null ? "—" : d[0].toFixed(2),"dim",haltNote],
  ["收盘",d[3].toFixed(2),dayChg == null ? "dim" : cls(dayChg),
   s.suspended ? haltNote : (dayChg == null ? "无前收对照" : `当日 ${pct(dayChg)}`)],
  ["最高",d[1] == null ? "—" : d[1].toFixed(2),"dim",""],
  ["最低",d[2] == null ? "—" : d[2].toFixed(2),"dim",""],
  ["成交额",d[4] == null ? "—" : d[4] + "亿","dim",""],
 ];
 el.innerHTML = cells.map(c => `<div class="tick"><div class="tl">${c[0]}</div><div class="tv ${c[2]}">${c[1]}</div><div class="ts">${c[3]}</div></div>`).join("");
}
const cls = v => v == null ? "dim" : (v >= 0 ? "up" : "down");
function dayClose(s,i){return s.candles[i] ? s.candles[i][3] : null}
function candleIdxOfDay(s,day){return s.recIndex + day - 1}
function dayRet(s,day){const i = candleIdxOfDay(s,day);if(s.ref == null || !s.candles[i] || s.candles[i][3] == null)return null;return (s.candles[i][3] / s.ref - 1) * 100}
function lastIdx(s){return s.candles.length - 1}
function latestReview(s){return s.reviews.length ? s.reviews[s.reviews.length - 1] : null}
function metrics(s){
  if(s.ref == null)return{cur:null,max:null,high:null,mae:null,peakDd:null,toT:null};
  const post = s.candles.slice(s.recIndex).filter(x => x[3] != null);
  if(!post.length)return{cur:null,max:null,high:null,mae:null,peakDd:null,toT:null};
  const c = post[post.length - 1][3];
  const maxC = Math.max(...post.map(x => x[3])), maxH = Math.max(...post.map(x => x[1])), minL = Math.min(...post.map(x => x[2]));
  const curR = (c / s.ref - 1) * 100;
  return{cur:curR, max:(maxC / s.ref - 1) * 100, high:(maxH / s.ref - 1) * 100, mae:(minL / s.ref - 1) * 100,
    peakDd:(c / maxC - 1) * 100, toT:20 - curR};
}
function nearTarget(s){const m = metrics(s);return m.cur != null && m.toT < 10}
function nextCheck(s){
 if(s.d0)return"待首日观察";
 if(s.suspended)return"待复牌";
 for(const d of [5,10,20])if(s.days < d)return"D" + d;
 return"已结束";
}
function showToast(msg){const el = $("toast");el.textContent = msg;el.classList.add("show");setTimeout(() => el.classList.remove("show"),1800)}
function cssVar(n){return getComputedStyle(document.body).getPropertyValue(n).trim()}
function esc(t){return String(t == null ? "" : t).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")}

/* ---------- 事实层图表 ---------- */
let G = null, hoverI2 = -1;
const cjkW = t => [...String(t)].reduce((a,ch) => a + (ch.charCodeAt(0) > 255 ? 10.5 : 6.2), 0);
let PXS = 1;
function pill(x,y,txt,bg,fg,o = {}){
 const sc = o.s || PXS || 1,w = cjkW(txt) * sc + 14 * sc,h = 20 * sc,fs = Math.max(9,Math.round(10 * sc)),
  xx = o.anchor === "middle" ? x - w / 2 : (o.anchor === "end" ? x - w : x),ty = y + h / 2 - fs * 0.36;
 const rect = o.soft
  ? `<rect x="${xx.toFixed(1)}" y="${(y - h / 2).toFixed(1)}" width="${w.toFixed(1)}" height="${h.toFixed(1)}" rx="${(h / 2).toFixed(1)}" fill="${bg}" fill-opacity=".14" stroke="${bg}" stroke-opacity=".5"/>`
  : `<rect x="${xx.toFixed(1)}" y="${(y - h / 2).toFixed(1)}" width="${w.toFixed(1)}" height="${h.toFixed(1)}" rx="${(h / 2).toFixed(1)}" fill="${bg}"/>`;
 return `${rect}<text x="${(xx + 7 * sc).toFixed(1)}" y="${ty.toFixed(1)}" fill="${fg}" font-size="${fs}" font-weight="600">${txt}</text>`;
}
function chartColors(){const c = cssVar;return{muted:c("--muted"),soft:c("--soft"),text:c("--ink"),warnFg:c("--warn-fg"),
 up:c("--up"),down:c("--down"),accent:c("--accent"),warn:c("--warn"),purple:c("--purple"),
 grid:c("--grid"),panel:c("--panel"),panel2:c("--panel2")}}
function drawChart(){
 const s = cur,svg = $("chartSvg"),tip = $("chartTip"),wrap = svg.parentElement;
 tip.style.display = "none";
 const W = Math.max(320,Math.round(wrap.clientWidth)),H = Math.round(wrap.clientHeight || 420);
 svg.setAttribute("viewBox",`0 0 ${W} ${H}`);
 const L = chartColors();
 const padL = 10,padR = W < 620 ? 54 : 64,padT = 30,axH = 22;
 const volH = Math.max(46,Math.round((H - axH - padT) * .2)),volGap = 16;
 const pT = padT,pB = H - axH - volH - volGap,vT = pB + volGap,vB = vT + volH;
 const UX = Math.max(1,Math.min(2.6,W / 1400));PXS = UX;
 const n = DATES.length,slot = (W - padL - padR) / n,xi = i => padL + slot * (i + .5),bw = Math.max(3,Math.min(13 * UX,slot * .56));
 G = {padL,slot,W,H,pT,pB,vT,vB,padR,n};
 let out = "";
 const gridY = (y,lo,hi,fmt) => {
  let g = "";for(let j = 0;j < 5;j++){const v = lo + (hi - lo) * j / 4,yy = y(v);
   g += `<line x1="${padL}" x2="${W - padR}" y1="${yy.toFixed(1)}" y2="${yy.toFixed(1)}" stroke="${L.grid}" stroke-dasharray="2 5"/>`;
   g += `<text x="${W - padR + 8}" y="${(yy + 3.5).toFixed(1)}" fill="${L.muted}" font-size="${(10 * UX).toFixed(1)}">${fmt(v)}</text>`;}
  return g;};
 const vLine = (x,y1,y2,col,dash,op) => `<line x1="${x.toFixed(1)}" x2="${x.toFixed(1)}" y1="${y1}" y2="${y2}" stroke="${col}" stroke-width="${(1.1 * UX).toFixed(2)}" ${dash ? `stroke-dasharray="${dash}"` : ""} opacity="${op ?? 1}"/>`;
 const hLine = (yy,col,dash) => `<line x1="${padL}" x2="${W - padR}" y1="${yy.toFixed(1)}" y2="${yy.toFixed(1)}" stroke="${col}" stroke-width="${(1.2 * UX).toFixed(2)}" stroke-dasharray="${dash}" opacity=".9"/>`;
 const recMark = () => {if(s.d0)return"";const rx = xi(s.recIndex);
  const mark = s.refKind === "event" ? "事件首日" : "推荐日";
  return vLine(rx,pT,pB,L.accent,"4 4",.6) + pill(rx,pT + 11,mark,L.accent,"#fff",{anchor:"middle"});};
 if(!relMode){
  const refs = s.ref != null ? [s.ref,s.ref * 1.2] : [];
  const vals = s.candles.flatMap(d => d[1] != null && d[2] != null ? [d[1],d[2]] : []).concat(refs);
  if(!vals.length){svg.innerHTML = `<text x="20" y="60" fill="${L.muted}" font-size="13">没有推荐后可靠行情记录。</text>`;G = null;return}
  let hi = Math.max(...vals),lo = Math.min(...vals);const pd = (hi - lo) * .06 || 1;hi += pd;lo -= pd;
  const y = v => pT + (hi - v) / (hi - lo) * (pB - pT);
  G.yF = v => y(v);G.inv = py => hi - (py - pT) / (pB - pT) * (hi - lo);
  out += gridY(y,lo,hi,v => v.toFixed(2));
  const poly = (get,col,w,dash) => {const pts = [];for(let i = 0;i < n;i++){const v = get(i);if(v == null)continue;pts.push(`${xi(i).toFixed(1)},${y(v).toFixed(1)}`)}
   return pts.length > 1 ? `<polyline points="${pts.join(" ")}" fill="none" stroke="${col}" stroke-width="${w}" stroke-linejoin="round" stroke-linecap="round" ${dash ? `stroke-dasharray="${dash}"` : ""} opacity=".9"/>` : ""};
  const closes = s.candles.map(d => d[3]);
  const maOf = nn => closes.map((_,i) => {if(i < nn - 1)return null;let sum = 0;for(let j = i - nn + 1;j <= i;j++){if(closes[j] == null)return null;sum += closes[j]}return sum / nn});
  const ma5 = maOf(5),ma10 = maOf(10);
  if(s.suspended){const bx = xi(s.recIndex) - slot / 2;
   out += `<rect x="${bx.toFixed(1)}" y="${pT}" width="${(W - padR - bx).toFixed(1)}" height="${pB - pT}" fill="${L.muted}" opacity=".08"/>
         <text x="${(bx + 10).toFixed(1)}" y="${(pT + 18).toFixed(1)}" fill="${L.muted}" font-size="${(10 * UX).toFixed(1)}">${s.recDate.slice(5)} 起停牌 · 无行情</text>`;}
  const vmax = Math.max(...s.candles.map(d => d[4] || 0),1e-9);
  out += `<line x1="${padL}" x2="${W - padR}" y1="${(vT - 6).toFixed(1)}" y2="${(vT - 6).toFixed(1)}" stroke="${L.grid}"/>`;
  s.candles.forEach((d,i) => {
   if(d[3] == null || d[0] == null)return;
   const col = d[3] >= d[0] ? L.up : L.down,x = xi(i),dim = i < s.recIndex ? .42 : 1;
   if(d[1] != null && d[2] != null)out += vLine(x,y(d[1]),y(d[2]),col,null,dim);
   const yO = y(d[0]),yC = y(d[3]),top = Math.min(yO,yC),h = Math.max(1.8,Math.abs(yO - yC));
   out += `<rect x="${(x - bw / 2).toFixed(1)}" y="${top.toFixed(1)}" width="${bw.toFixed(1)}" height="${h.toFixed(1)}" rx="1.2" fill="${col}" opacity="${(dim * .95).toFixed(2)}"/>`;
   if(d[4] > 0){const vh = Math.max(2,d[4] / vmax * (vB - vT));
    out += `<rect x="${(x - bw / 2).toFixed(1)}" y="${(vB - vh).toFixed(1)}" width="${bw.toFixed(1)}" height="${vh.toFixed(1)}" rx="1" fill="${col}" opacity="${(dim * .45).toFixed(2)}"/>`;}
  });
  out += `<text x="${padL + 2}" y="${(vT + 10).toFixed(1)}" fill="${L.muted}" font-size="${(9 * UX).toFixed(1)}">成交量</text>`;
  out += poly(i => ma5[i],L.purple,1.5);
  out += poly(i => ma10[i],L.soft,1.4,"4 4");
  const tags = [];
  if(s.ref != null){
   out += hLine(y(s.ref),L.accent,"2 4");
   out += pill(padL + 4,y(s.ref) - 14,`推荐参考 ${s.ref.toFixed(2)}`,L.accent,L.accent,{soft:true});
   out += hLine(y(s.ref * 1.2),L.warn,"5 4");
   out += pill(padL + 4,y(s.ref * 1.2) - 14,`20%目标 ${(s.ref * 1.2).toFixed(2)}`,L.warn,L.warn,{soft:true});
   tags.push({y:y(s.ref),txt:s.ref.toFixed(2),bg:L.accent,fg:"#fff"});
   tags.push({y:y(s.ref * 1.2),txt:(s.ref * 1.2).toFixed(2),bg:L.warn,fg:L.warnFg});
  }
  let last = null;for(let i = s.candles.length - 1;i >= 0;i--)if(s.candles[i][3] != null){last = s.candles[i];break}
  if(last){const lc = last[3],lcCol = lc >= (last[0] ?? lc) ? L.up : L.down;
   out += hLine(y(lc),lcCol,"2 4");
   tags.push({y:y(lc),txt:lc.toFixed(2),bg:lcCol,fg:"#fff"});}
  tags.sort((a,b) => a.y - b.y);
  for(let i = 1;i < tags.length;i++)if(tags[i].y - tags[i - 1].y < 21)tags[i].y = tags[i - 1].y + 21;
  if(tags.length && tags[tags.length - 1].y > pB - 2){const sh = tags[tags.length - 1].y - (pB - 2);tags.forEach(t => t.y -= sh)}
  tags.forEach(t => out += pill(W - padR + 4,t.y,t.txt,t.bg,t.fg));
  if(selDay != null){const si = candleIdxOfDay(s,selDay);
   if(s.candles[si] && s.candles[si][3] != null){
    out += `<rect x="${(xi(si) - slot / 2 + 1).toFixed(1)}" y="${pT}" width="${(slot - 2).toFixed(1)}" height="${vB - pT}" fill="${L.accent}" opacity=".07"/>`;
    out += vLine(xi(si),pT,pB,L.warn,null,.8);
   }}
  if(!s.suspended)out += recMark();
 }else{
  const rb = Math.min(s.recIndex,s.candles.length - 1);
  const baseBar = s.candles[rb];
  if(!baseBar || baseBar[3] == null){svg.innerHTML = `<text x="20" y="60" fill="${L.muted}" font-size="13">没有推荐日基准，无法绘制相对表现。</text>`;G = null;return}
  const bS = baseBar[3],hasInd = s.industry && s.industry[rb] != null,bI = hasInd ? s.industry[rb] : null,bM = MARKET[rb] != null ? MARKET[rb] : null;
  const sv = i => (s.candles[i] && s.candles[i][3] != null) ? s.candles[i][3] / bS * 100 : null,
        iv2 = hasInd ? (i => (i < s.industry.length && s.industry[i] != null) ? s.industry[i] / bI * 100 : null) : () => null,
        mv2 = (bM != null) ? (i => (MARKET[i] != null ? MARKET[i] / bM * 100 : null)) : () => null;
  const all = [100];if(s.ref != null)all.push(120);for(let i = 0;i < n;i++){const a = iv2(i),b = mv2(i);if(a != null)all.push(a);if(b != null)all.push(b);const q = sv(i);if(q != null)all.push(q);}
  let hi = Math.max(...all),lo = Math.min(...all);const pd = (hi - lo) * .08 || 1;hi += pd;lo -= pd;
  const y = v => pT + (hi - v) / (hi - lo) * (pB - pT);
  G.yF = v => y(v);
  out += gridY(y,lo,hi,v => v.toFixed(0));
  out += `<line x1="${padL}" x2="${W - padR}" y1="${y(100).toFixed(1)}" y2="${y(100).toFixed(1)}" stroke="${L.muted}" stroke-dasharray="6 5" opacity=".5"/>`;
  out += `<text x="${padL + 4}" y="${(y(100) - 6).toFixed(1)}" fill="${L.muted}" font-size="${(9 * UX).toFixed(1)}">${s.refKind === "event" ? "事件首日 = 100" : "推荐日 = 100"}</text>`;
  if(s.ref != null){
   out += hLine(y(120),L.warn,"6 4");
   out += pill(padL + 4,y(120) - 14,"20%目标 120",L.warn,L.warn,{soft:true});}
  if(!hasInd)out += `<text x="${padL + 4}" y="${pT + 12}" fill="${L.muted}" font-size="${(10 * UX).toFixed(1)}">行业${s.industryName ? `（${s.industryName}）` : ""}路径数据不足，如实留空</text>`;
  const sPts = [];for(let i = 0;i < n;i++){const v = sv(i);if(v == null)continue;sPts.push([xi(i),y(v)])}
  if(sPts.length > 1){
   out += `<defs><linearGradient id="gRel" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${L.accent}" stop-opacity=".16"/><stop offset="1" stop-color="${L.accent}" stop-opacity="0"/></linearGradient></defs>`;
   const dPath = `M${sPts.map(p => p[0].toFixed(1) + "," + p[1].toFixed(1)).join(" L")} L${sPts[sPts.length - 1][0].toFixed(1)},${y(100).toFixed(1)} L${sPts[0][0].toFixed(1)},${y(100).toFixed(1)} Z`;
   out += `<path d="${dPath}" fill="url(#gRel)"/>`;}
  const poly = (f,col,w,dash) => {const pts = [];for(let i = 0;i < n;i++){const v = f(i);if(v == null)continue;pts.push([xi(i),y(v)])}
   if(pts.length < 2)return "";
   let d;
   if(pts.length === 2)d = `M${pts[0][0].toFixed(1)},${pts[0][1].toFixed(1)} L${pts[1][0].toFixed(1)},${pts[1][1].toFixed(1)}`;
   else{d = `M${pts[0][0].toFixed(1)},${pts[0][1].toFixed(1)}`;
    for(let i = 1;i < pts.length;i++){const p0 = pts[i - 1],p1 = pts[i],mx = (p0[0] + p1[0]) / 2;
     d += ` C${mx.toFixed(1)},${p0[1].toFixed(1)} ${mx.toFixed(1)},${p1[1].toFixed(1)} ${p1[0].toFixed(1)},${p1[1].toFixed(1)}`;}}
   return `<path d="${d}" fill="none" stroke="${col}" stroke-width="${w}" stroke-linejoin="round" stroke-linecap="round" ${dash ? `stroke-dasharray="${dash}"` : ""}/>`};
  out += poly(mv2,L.muted,1.5,"5 4");
  out += poly(iv2,L.purple,2.1);
  out += poly(sv,L.accent,2.5);
  const li = n - 1,endV = [[sv(li),`个股 ${sv(li) == null ? "—" : sv(li).toFixed(1)}`,L.accent,"#fff"]]
    .concat(hasInd ? [[iv2(li),`行业 ${iv2(li) == null ? "—" : iv2(li).toFixed(1)}`,L.purple,"#fff"]] : [])
    .concat(bM != null ? [[mv2(li),`市场 ${mv2(li) == null ? "—" : mv2(li).toFixed(1)}`,L.muted,"#fff"]] : [])
    .filter(x => x[0] != null)
    .map(x => ({y:y(x[0]),txt:x[1],bg:x[2],fg:x[3]})).sort((a,b) => a.y - b.y);
  for(let i = 1;i < endV.length;i++)if(endV[i].y - endV[i - 1].y < 22)endV[i].y = endV[i - 1].y + 22;
  endV.forEach(c => out += pill(W - padR + 4,c.y,c.txt,c.bg,c.fg));
  out += recMark();
  if(selDay != null){const si = candleIdxOfDay(s,selDay),v = sv(si);
   if(v != null)out += `<circle cx="${xi(si).toFixed(1)}" cy="${y(v).toFixed(1)}" r="4.5" fill="${L.warn}" stroke="${L.panel}" stroke-width="2"/>`;}
 }
 const every = Math.max(1,Math.ceil(88 / slot));let prevX = -1e9;
 DATES.forEach((d,i) => {if(i % every !== 0 && i !== n - 1)return;
  const xx = Math.min(Math.max(xi(i),padL + 20),W - padR - 24);if(xx - prevX < 44)return;prevX = xx;
  out += `<text x="${xx.toFixed(1)}" y="${H - 6}" fill="${L.muted}" font-size="${(10 * UX).toFixed(1)}" text-anchor="middle">${DATES[i]}</text>`;});
 out += `<g id="xhg"></g>`;
 const hits = s.candles.map((_,i) => `<rect class="hit" data-i="${i}" x="${(padL + slot * i).toFixed(1)}" y="${pT}" width="${slot.toFixed(1)}" height="${(vB - pT).toFixed(1)}" fill="transparent"/>`).join("");
 svg.innerHTML = out + hits;
 function chartSelect(i){
  if(s.d0){showToast("该股已入选，待首日观察");return}
  if(i < s.recIndex){showToast("推荐日之前，仅作背景参考");return}
  if(s.suspended){showToast("停牌期间无行情");return}
  const d = i - s.recIndex + 1,rev = s.reviews.find(r => r.day === d);
  selDay = d;selReview = rev || null;renderTimeline();renderReview();drawChart();
 }
 svg.onmousemove = ev => {const r = svg.getBoundingClientRect(),mx = ev.clientX - r.left;
  hoverI = Math.max(0,Math.min(s.candles.length - 1,Math.floor((mx - padL) / slot)));
  hoverY = ev.clientY - r.top;syncHover();};
 svg.onmouseleave = () => {hoverI = -1;syncHover()};
 svg.onclick = () => {if(hoverI >= 0)chartSelect(hoverI)};
 svg.ontouchstart = svg.ontouchmove = ev => {const t = ev.touches[0],r = svg.getBoundingClientRect();
  hoverI = Math.max(0,Math.min(s.candles.length - 1,Math.floor((t.clientX - r.left - padL) / slot)));
  hoverY = t.clientY - r.top;ev.preventDefault();syncHover();};
 svg.ontouchend = () => {if(hoverI >= 0)chartSelect(hoverI)};
}
function syncHover(){
 const s = cur,svg = $("chartSvg"),tip = $("chartTip");
 document.querySelectorAll(".day-btn").forEach(b => b.classList.remove("preview"));
 const g = svg.querySelector("#xhg");
 if(hoverI < 0 || !G || !s.candles[hoverI] || s.candles[hoverI][3] == null){if(g)g.innerHTML = "";tip.style.display = "none";return}
 const L = chartColors(),x = G.padL + G.slot * (hoverI + .5),d = s.candles[hoverI];
 const dn = hoverI - s.recIndex + 1;
 const day = (s.d0 || dn < 1) ? "推荐前" : (dn <= 20 ? `D${dn}` : `延长观察第${dn - 20}天`);
 let cross = `<line x1="${x.toFixed(1)}" x2="${x.toFixed(1)}" y1="${G.pT}" y2="${G.vB}" stroke="${L.soft}" stroke-width="1" stroke-dasharray="3 3" opacity=".7"/>`;
 if(!relMode){
  const yc = G.yF(d[3]);
  cross += `<circle cx="${x.toFixed(1)}" cy="${yc.toFixed(1)}" r="3.2" fill="${L.warn}" stroke="${L.panel}" stroke-width="1.5"/>`;
  const pv = G.inv(Math.min(Math.max(hoverY,G.pT + 10),G.pB - 10));
  cross += pill(G.W - G.padR + 4,Math.min(Math.max(hoverY,G.pT + 10),G.pB - 10),pv.toFixed(2),L.panel2,L.text);
 }
 cross += pill(x,G.H - 11,`${DATES[hoverI]} · ${day}`,L.panel2,L.text,{anchor:"middle"});
 g.innerHTML = cross;
 const btn = document.querySelector(`.day-btn[data-day="${hoverI - s.recIndex + 1}"]`);
 if(btn && !btn.disabled)btn.classList.add("preview");
 const rb = Math.min(s.recIndex,s.candles.length - 1),baseC = s.candles[rb] ? s.candles[rb][3] : null;
 const refPct = s.ref != null ? ` · 较参考 ${pct((d[3] / s.ref - 1) * 100)}` : "";
 tip.innerHTML = relMode ?
  `<b>${DATES[hoverI]}</b> · ${day}<br>个股 <b>${baseC ? (d[3] / baseC * 100).toFixed(1) : "—"}</b>` +
  ((s.industry && s.industry[hoverI] != null && s.industry[rb] != null) ? ` · 行业 ${(s.industry[hoverI] / s.industry[rb] * 100).toFixed(1)}` : "") +
  ((MARKET[hoverI] != null && MARKET[rb] != null) ? ` · ${(DATA.market_name)} ${(MARKET[hoverI] / MARKET[rb] * 100).toFixed(1)}` : "") :
  `<b>${DATES[hoverI]}</b> · ${day}<br>开 ${d[0] == null ? "—" : d[0].toFixed(2)}　高 ${d[1] == null ? "—" : d[1].toFixed(2)}　低 ${d[2] == null ? "—" : d[2].toFixed(2)}<br>收 <b style="color:${d[3] >= d[0] ? cssVar("--up") : cssVar("--down")}">${d[3].toFixed(2)}</b>${refPct}<br>量 ${d[4] == null ? "—" : d[4] + "亿"}`;
 tip.style.display = "block";
 const wr = tip.parentElement.getBoundingClientRect();
 tip.style.left = Math.min(wr.width - 175,Math.max(6,(x / G.W) * wr.width + 10)) + "px";
 tip.style.top = Math.max(6,Math.min(hoverY - 72,wr.height - 112)) + "px";
}
let rzT;addEventListener("resize",() => {clearTimeout(rzT);rzT = setTimeout(() => {if($("detailPage").classList.contains("active"))drawChart()},120)});


/* ---------- 总览：统计行 / 重点观察 / 账目列表 ---------- */
const FILTERS = [["all","全部"],["attention","今日重点"],["strong","继续走强"],["sideways","整理中"],["weak","判断减弱"],["paused","无法执行"]];
const KPIS = [
 ["attention","今日需复盘",() => stocks.filter(s => s.attention).length],
 ["near","近 20% 目标",() => stocks.filter(nearTarget).length],
 ["weak","判断减弱",() => stocks.filter(s => s.stageType === "weak").length],
 ["paused","无法执行",() => stocks.filter(s => s.stageType === "paused").length]
];
function renderStats(){
 const items = [["all","在观",() => stocks.length],...KPIS];
 $("statline").innerHTML = items.map(k => `<button class="stat ${activeFilter === k[0] ? "active" : ""}" data-k="${k[0]}"><b>${k[2]()}</b>${k[1]}</button>`).join("");
 document.querySelectorAll(".stat").forEach(b => b.onclick = () => setFilter(activeFilter === b.dataset.k ? "all" : b.dataset.k));
}
function renderTabs(){
 $("tabs").innerHTML = FILTERS.map(x => {
  const n = x[0] === "all" ? stocks.length : (x[0] === "attention" ? stocks.filter(s => s.attention).length : (x[0] === "near" ? stocks.filter(nearTarget).length : stocks.filter(s => s.stageType === x[0]).length));
  return `<button class="tab ${activeFilter === x[0] ? "active" : ""}" data-f="${x[0]}">${x[1]}<i>${n}</i></button>`}).join("");
 document.querySelectorAll(".tab").forEach(b => b.onclick = () => setFilter(b.dataset.f));
}
function filteredStocks(){
 const q = $("searchInput").value.trim().toLowerCase();
 return stocks.filter(s => {
  const m = !q || s.name.toLowerCase().includes(q) || s.code.toLowerCase().includes(q);
  const f = activeFilter === "all" || (activeFilter === "attention" && s.attention) || (activeFilter === "near" && nearTarget(s)) || (activeFilter === s.stageType);
  return m && f});
}
function setFilter(f){activeFilter = f;renderStats();renderTabs();renderLedger()}
function focusStocks(){
 if(keyDate === DATA.analysis_date)return stocks.filter(s => s.attention).slice()
   .sort((a,b) => (latestReview(b) && latestReview(b).viewChanged ? 1 : 0) - (latestReview(a) && latestReview(a).viewChanged ? 1 : 0));
 const rows = [];
 stocks.forEach(s => {const r = s.reviews.find(x => x.date === keyDate);if(r)rows.push(Object.assign({},s,{_r:r}))});
 const rank = x => x._r.viewChanged ? 0 : x._r.checkpoint ? 1 : 2;
 return rows.sort((a,b) => rank(a) - rank(b) || b._r.day - a._r.day);
}
function renderStories(){
 const isToday = keyDate === DATA.analysis_date,focus = focusStocks();
 $("stories").innerHTML = focus.map((s,i) => {
  const r = s._r || latestReview(s),m = metrics(s);
  const ret = isToday ? m.cur : dayRet(s,r.day);
  const trig = isToday ? s.trigger : (r.checkpoint ? `${r.checkpoint} 检查日` : (r.viewChanged ? (r.fromTo || "观点调整") : "每日复盘"));
  return `<div class="story" data-code="${s.code}">
   <div class="story-no">${String(i + 1).padStart(2,"0")}</div>
   <div><div class="story-name">${esc(s.name)}<small>${s.code} · ${isToday ? (s.d0 ? `${s.recDate.slice(5)}入选 · 待首日观察` : (s.days > 20 ? `延长观察第${s.days - 20}天` : `${s.recDate.slice(5)}入选 · 当前D${s.days}/20`)) : `${r.date.slice(5)} 复盘`}</small></div>
    <div class="story-headline">${r && r.viewChanged ? '<span class="hlmark">▍</span>' : ""}${r ? esc(r.headline) : "这天没有针对这条记录的复盘观点。"}</div></div>
   <div class="story-side"><span class="story-ret ${cls(ret)}">${pct(ret)}</span>
    <span class="story-tags"><span class="trigger">${esc(trig)}</span><span class="stage stage-${s.stageType}">${esc(s.stage)}</span>${r && r.viewChanged ? `<span class="before-after">${esc(r.fromTo || "观点调整")}</span>` : ""}</span></div>
  </div>`}).join("") || "";
 $("keyNote").textContent = isToday
  ? (focus.length ? "以下是当天复盘重点提示的股票，标题就是这只股票当天的复盘结论，观点发生变化的排在最前。点击进入个股观察页。" : "这一天没有被明确推荐过、同时又出现需要说明变化的股票。")
  : (focus.length ? `正在查看 ${keyDate} 的复盘重点（观点变化、检查日优先）；此选择只切换本栏，页面其余部分保持 ${DATA.analysis_date} 日报不变。` : `${keyDate} 没有复盘记录。`);
 $("collapsedNote").textContent = `已缩起 ${focus.length} 只${isToday ? "当天" : "该日"}重点复盘股票，点击“展开”恢复。`;
 document.querySelectorAll(".story").forEach(x => x.onclick = () => openStock(x.dataset.code));
}
function sortedRows(rows){
 if(!sortKey)return rows;
 const keyed = [],nulls = [];
 rows.forEach(s => {const m = metrics(s);
  const v = sortKey === "progress" ? s.days : m.toT;
  (v == null ? nulls : keyed).push([v,m.cur == null ? -1e9 : m.cur,s])});
 keyed.sort((a,b) => {
  if(a[0] !== b[0])return (a[0] - b[0]) * sortDir;
  if(a[1] !== b[1])return b[1] - a[1];
  return a[2].code < b[2].code ? -1 : 1});
 return keyed.map(x => x[2]).concat(nulls);
}
function renderSortHeads(){
 document.querySelectorAll(".ledger th.sortable").forEach(th => {
  const on = th.dataset.sort === sortKey;
  th.classList.toggle("sorted",on);
  th.querySelector(".arrs").textContent = on ? (sortDir > 0 ? "▲" : "▼") : "";});
}
document.querySelectorAll(".ledger th.sortable").forEach(th => th.onclick = () => {
 const k = th.dataset.sort,defDir = k === "toT" ? 1 : -1;
 if(sortKey !== k){sortKey = k;sortDir = defDir}
 else if(sortDir === defDir){sortDir = -defDir}
 else{sortKey = null}
 renderLedger();renderSortHeads();
});
function renderLedger(){
 const rows = sortedRows(filteredStocks());
 $("ledgerRows").innerHTML = rows.map(s => {
  const m = metrics(s);
  let progCell = progressText(s),progBar = "";
  if(!s.d0){const prog = s.ref == null ? 0 : Math.max(0,Math.min(100,m.cur / 20 * 100));
   progBar = `<div class="pbar"><i style="width:${s.days > 20 ? 100 : prog}%"></i></div>`;}
  return `<tr class="tr" data-code="${s.code}">
   <td><span class="l-name">${esc(s.name)}</span><span class="l-code">${s.code}</span></td>
   <td class="l-dim">${progCell}${progBar}</td>
   <td><span class="l-ret ${cls(m.cur)}">${pct(m.cur)}</span> <span class="l-dim">/ ${pct(m.max)}</span></td>
   <td class="${cls(m.cur)}">${m.toT == null ? "—" : m.toT.toFixed(1) + "pp"}</td>
   <td><span class="stage stage-${s.stageType}">${esc(s.stage)}</span></td>
   <td class="l-dim">${nextCheck(s)}</td>
   <td class="arr">→</td></tr>`}).join("") || `<tr><td colspan="7" style="color:var(--ink3);padding:26px 0">没有符合当前筛选的股票</td></tr>`;
 document.querySelectorAll("#ledgerRows tr[data-code]").forEach(r => r.onclick = () => openStock(r.dataset.code));
}
$("searchInput").addEventListener("input",renderLedger);
function renderStockPick(){
 const sel = $("stockPick");
 const groups = {};
 stocks.forEach(s => {(groups[s.recDate] = groups[s.recDate] || []).push(s)});
 const days = Object.keys(groups).sort((a,b) => b.localeCompare(a));
 sel.innerHTML = `<option value="">— 选择股票 —</option>` + days.map(d =>
  `<optgroup label="${d} 开盘前推荐">` + groups[d].map(s => `<option value="${s.code}">${s.name} ${s.code}</option>`).join("") + `</optgroup>`).join("");
 sel.onchange = () => {if(sel.value)openStock(sel.value)};
}
function renderDateSelect(){
 const sel = $("dateSelect");
 sel.innerHTML = (DATA.review_dates || []).map(d => `<option value="${d}" ${d === keyDate ? "selected" : ""}>${d}</option>`).join("");
 sel.onchange = () => {keyDate = sel.value;renderStories()};
}
$("collapseBtn").onclick = () => {
 keyCollapsed = !keyCollapsed;
 $("stories").classList.toggle("collapsed",keyCollapsed);
 $("collapseBtn").textContent = keyCollapsed ? "展开" : "缩起";
 $("collapsedNote").style.display = keyCollapsed ? "" : "none";
};

/* ---------- 个股：正文页 ---------- */
function openStock(code){
 cur = stocks.find(s => s.code === code) || stocks[0];
 const r = latestReview(cur);
 selDay = r ? r.day : null;selReview = r || null;
 renderDetail();switchPage("detail");
 try{history.replaceState(null,"","#"+encodeURIComponent(cur.code))}catch(e){}
}
function renderDetail(){
 const s = cur,m = metrics(s);
 $("dName").textContent = s.name;
 $("dCode").textContent = s.code;
 if(s.d0){
  $("dStatus").textContent = `入选日：${s.recDate} · 已入选，待首日观察`;
 }else{
  const core = s.days > 20 ? `20日核心观察已完成 · 延长观察第${s.days - 20}天`
   : `当前D${s.days}/20` + (s.days === 20 ? " · 20个交易日核心观察完成" : "");
  $("dStatus").textContent = (s.suspended ? "无法执行 · " : "") + `${s.recDate}入选 · ` + core +
   (s.ref == null ? " · 无推荐参考价" : (s.refKind === "event" ? " · 参考价=事件首日开盘" : ""));
 }
 $("dCompany").textContent = s.company || "";
 const rb = $("rReason");
 if(s.reasonFull){
  rb.dataset.has = "1";
  rb.innerHTML = `<span class="cap">推荐理由 · ${s.recDate} 入选</span><p>${esc(s.reasonFull)}</p>` +
   (s.reasonRisk ? `<p class="risk"><b>当时主要担心</b>${esc(s.reasonRisk)}</p>` : "");
 }else rb.dataset.has = "";
 rb.style.display = "none";
 document.querySelectorAll("#chartSeg button").forEach(b => b.classList.toggle("on",(b.dataset.m === "rel") === relMode));
 updateLegend(s);
 const cells = [
  ["当前涨跌",pct(m.cur),cls(m.cur),"相对推荐参考价"],
  ["最高收盘",pct(m.max),cls(m.max),"推荐后最高收盘"],
  ["盘中最高",pct(m.high),cls(m.high),"目标曾否触及"],
  ["期间最深",pct(m.mae),m.mae != null && m.mae < 0 ? "down" : "dim","观察回撤"],
  ["距 20% 目标",m.toT == null ? "—" : m.toT.toFixed(2) + "pp","dim",s.suspended ? "停牌，无推荐参考价" : "达 20% 即到目标"]];
 $("tickerStrip").innerHTML = cells.map(c => `<div class="tick"><div class="tl">${c[0]}</div><div class="tv ${c[2]}">${c[1]}</div><div class="ts">${c[3]}</div></div>`).join("");
 renderQuoteStrip(s);renderEvents();renderTimeline();renderReview();drawChart();
}
function updateLegend(s){
 $("refLegend").style.display = s.ref != null && !relMode ? "" : "none";
 $("refLegendTxt").textContent = s.refKind === "event" ? "参考价·事件首日开盘" : "推荐参考价";
 $("targetLegend").style.display = s.ref != null && !relMode ? "" : "none";
 $("maLegend").style.display = !relMode && !s.suspended ? "" : "none";
 $("maLegend2").style.display = !relMode && !s.suspended ? "" : "none";
 $("relLegend").style.display = relMode && s.industrySource !== "none" ? "" : "none";
 if(s.industryName)$("relLegendTxt").textContent = s.industrySource === "members" ? `行业·${s.industryName}（等权）` : `行业·${s.industryName}`;
 $("relLegend2").style.display = relMode ? "" : "none";
 $("relLegend3").style.display = relMode && s.ref != null ? "" : "none";
}

function renderTimeline(){
 const s = cur,rev = {};s.reviews.forEach(r => rev[r.day] = r);
 let html = "";
 for(let d = 1;d <= 20;d++){
  const ci = candleIdxOfDay(s,d),hasC = !!(s.candles[ci] && s.candles[ci][3] != null) && !s.suspended;
  const r = rev[d],future = d > s.days && !r;
  const label = r ? (dayRet(s,d) != null ? pct(dayRet(s,d)) : "事件") : (hasC ? pct(dayRet(s,d)) : "—");
  const canClick = (r || hasC) && !future;
  html += `<button class="day-btn ${r || hasC ? "observed" : ""} ${future ? "future" : ""} ${selDay === d ? "active" : ""}" data-day="${d}" ${canClick ? "" : "disabled"}>
   ${r && r.viewChanged ? '<i class="vcdot" title="观点调整"></i>' : ""}${d === 1 && r ? '<i class="recdot" title="推荐日复盘"></i>' : ""}
   <b>D${d}</b><span>${future ? "—" : label}</span></button>`;
 }
 $("timeline").innerHTML = html;
 document.querySelectorAll(".day-btn.observed").forEach(b => {
  b.onclick = () => {const d = +b.dataset.day;selDay = d;selReview = rev[d] || null;renderTimeline();renderReview();drawChart()};
  b.onmouseenter = () => drawXh(candleIdxOfDay(s,+b.dataset.day));
  b.onmouseleave = () => drawXh(-1);
 });
}
function renderReview(){
 const s = cur,r = selReview,latest = latestReview(s);
 let badges = "";
 if(r && latest && r.day !== latest.day)badges += `<button class="textlink" id="backLatest">回到最新（${dayLabel(latest.day)}）</button>`;
 if(r && r.viewChanged)badges += `<span class="badge">${esc(r.fromTo || r.viewLabel || "观点调整")}</span>`;
 $("rBadges").innerHTML = badges;
 if(!r){
  $("rDate").textContent = selDay != null ? `${s.recDate}入选 · 当前${dayLabel(selDay)}/20 · ${DATES[candleIdxOfDay(s,selDay)] || ""}` : `${s.recDate}入选`;
  $("rHeadline").textContent = latest ? "当日无复盘正文" : "这只股票还没有被复盘过";
  $("rCopy").textContent = "每个收盘日都会生成简短复盘；没有正文的日期通常是当日没有可评价的新事实。可在上方查看当日价格与成交" + (latest ? "，或回到最新观点。" : "。");
  $("rReview").innerHTML = "";
 }else{
  $("rDate").textContent = `${s.recDate}入选 · 当前${dayLabel(r.day)}/20 · ${DATES[candleIdxOfDay(s,r.day)] || ""}`;
  $("rHeadline").textContent = r.headline;
  $("rCopy").textContent = r.copy;
  const rows = [];
  if(r.assessmentText)rows.push(["当日结论",`<b>${esc(r.assessmentText)}</b>`]);
  if(r.facts && r.facts.length)rows.push(["关键变化",r.facts.map(f => `<span class="fx">${esc(f)}</span>`).join('<span style="color:var(--ink3)"> · </span>')]);
  if(r.viewLabel)rows.push(["观点变化",`${esc(r.viewLabel)}${r.viewReason ? ` — ${esc(r.viewReason)}` : ""}`]);
  if(r.base)rows.push(["未来1—3日",`${esc(r.base)}${r.outlookReason ? ` — ${esc(r.outlookReason)}` : ""}`]);
  $("rReview").innerHTML = rows.length
   ? `<span class="cap">每日复盘 · ${dayLabel(r.day)} · ${DATES[candleIdxOfDay(s,r.day)] || ""}</span>` + rows.map(x => `<div class="rev-row"><span class="rk">${x[0]}</span><span class="rv">${x[1]}</span></div>`).join("")
   : "";
 }
 const rb = $("rReason");
 const stageDay = r && ["D5","D10","D20"].includes(r.checkpoint);
 rb.style.display = rb.dataset.has && (s.d0 || selDay === 1 || stageDay) ? "" : "none";
 const bl = $("backLatest");
 if(bl)bl.onclick = () => {selDay = latest.day;selReview = latest;renderTimeline();renderReview();drawChart()};
}
function eventTitle(s,e){
 const i = DATES.indexOf(e[0]);
 const r = cur.reviews.find(x => x.date.slice(5) === e[0]);
 const cp = r && r.checkpoint ? `${r.checkpoint}检查` : null;
 if(e[1] === "rec")return{t:"正式推荐",d:e[3],cp:null};
 if(e[1] === "milestone")return{t:e[2],d:e[3],cp};
 if(e[1] === "view"){
  const t = r && r.viewLabel === "判断失效" ? "判断失效" : "观点调整";
  const lead = r && r.fromTo ? `从“${r.fromTo}”。` : "";
  return{t,d:lead + (r ? (r.summary_copy || r.copy) : e[3]),cp};
 }
 // check：按当日事实命名（阶段新高 / 冲高回落 / 阶段回落 / 阶段整理）
 const close = s.candles[i] ? s.candles[i][3] : null;
 const closes = [];for(let j = Math.max(0,s.recIndex);j <= i;j++)if(s.candles[j] && s.candles[j][3] != null)closes.push(s.candles[j][3]);
 const prevC = (() => {for(let j = i - 1;j >= 0;j--)if(s.candles[j] && s.candles[j][3] != null)return s.candles[j][3];return null})();
 const maxC = closes.length ? Math.max(...closes) : null;
 const dayChg = close != null && prevC ? close / prevC - 1 : null;
 let t = "阶段整理";
 if(close != null && maxC != null && close >= maxC)t = "阶段新高";
 else if(close != null && maxC && close / maxC - 1 <= -0.03)t = "冲高回落";
 else if(dayChg != null && dayChg <= -0.02)t = "阶段回落";
 return{t,d:r ? (r.summary_copy || r.copy) : e[3],cp};
}
function renderEvents(){
 $("events").innerHTML = cur.events.map((e,idx) => {
  const v = eventTitle(cur,e);
  const long = v.d && v.d.length > 60;
  return `<div class="event-row" data-ev="${idx}"><span class="e-date">${esc(e[0])}</span><span class="e-dot ${e[1] === "view" ? "view" : e[1] === "milestone" ? "milestone" : e[1] === "rec" ? "rec" : "check"}"></span><div><b class="e-title">${esc(v.t)}</b>${v.cp ? `<i class="e-check">${esc(v.cp)}</i>` : ""}<span class="e-desc">${esc(v.d)}</span></div></div>`;
 }).join("");
 document.querySelectorAll(".event-row").forEach(row => row.onclick = () => row.classList.toggle("open"));
}

/* ---------- 导航 / 主题 / 启动 ---------- */
function switchPage(name){
 const apply = () => {
  document.querySelectorAll(".page").forEach(x => x.classList.remove("active"));
  if(name === "overview"){$("overviewPage").classList.add("active")}
  else{$("detailPage").classList.add("active")}
  window.scrollTo({top:0,behavior:"instant"});
  if(name === "detail")drawChart();
 };
 if(document.startViewTransition && !matchMedia("(prefers-reduced-motion:reduce)").matches)document.startViewTransition(apply);
 else apply();
}
function setRel(on){if(cur.suspended && on){showToast("停牌股无推荐日基准，相对表现不可用");return}
 relMode = on;
 document.querySelectorAll("#chartSeg button").forEach(b => b.classList.toggle("on",(b.dataset.m === "rel") === relMode));
 updateLegend(cur);drawChart()}
$("homeBtn").onclick = () => {try{history.replaceState(null,"",location.pathname)}catch(e){} switchPage("overview")};
$("backBtn").onclick = () => switchPage("overview");
document.querySelectorAll("#chartSeg button").forEach(b => b.addEventListener("click",() => setRel(b.dataset.m === "rel")));
$("themeBtn").onclick = () => {document.body.classList.toggle("dark");storeSet("v4Theme",document.body.classList.contains("dark") ? "dark" : "light");drawChart()};
if(storeGet("v4Theme") === "dark")document.body.classList.add("dark");
if("IntersectionObserver" in window){
 const revIO = new IntersectionObserver(es => es.forEach(e => {if(e.isIntersecting){e.target.classList.add("in");revIO.unobserve(e.target)}}),{threshold:.06});
 document.querySelectorAll(".reveal").forEach(el => revIO.observe(el));
 setTimeout(() => document.querySelectorAll(".reveal:not(.in)").forEach(el => el.classList.add("in")),1200);
}else document.querySelectorAll(".reveal").forEach(el => el.classList.add("in"));

(function boot(){
 const wd = ["日","一","二","三","四","五","六"][new Date(DATA.analysis_date + "T12:00:00").getDay()];
 $("dateline").textContent = DATA.analysis_date.replace("-","年").replace("-","月") + "日 · 星期" + wd + " · 收盘后";
 renderDateSelect();renderStats();renderStories();renderTabs();renderStockPick();renderLedger();renderSortHeads();
 const code = decodeURIComponent(location.hash.slice(1));
 if(code && stocks.some(s => s.code === code))openStock(code);
})();
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def render(payload: dict[str, Any]) -> str:
    html = HTML_TEMPLATE
    page_json = json.dumps(payload, ensure_ascii=False, default=str)
    return html.replace("__PAGE_DATA__", page_json.replace("</", "<\\/"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Render the frozen daily monitor review as the V4 display web page"
    )
    parser.add_argument(
        "--date", default=None, help="analysis date (YYYY-MM-DD), default latest snapshot"
    )
    parser.add_argument("--monitor-dir", default=None, help="override monitor archive directory")
    parser.add_argument(
        "--out",
        default=None,
        help="override output HTML path (default monitor-report-<date>.html in monitor dir)",
    )
    args = parser.parse_args(argv)

    monitor_dir = Path(args.monitor_dir) if args.monitor_dir else MONITOR_DIR
    analysis_date = resolve_date(monitor_dir, args.date)
    report, snapshot, _report_path, _snapshot_path = load_artifacts(monitor_dir, analysis_date)
    payload = build_payload(PROJECT_ROOT, monitor_dir, analysis_date, report, snapshot)
    html = render(payload)
    out_path = (
        Path(args.out)
        if args.out
        else monitor_dir / f"monitor-report-{analysis_date.isoformat()}.html"
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

