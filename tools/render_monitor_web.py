"""Prism 共享展示数据整理：只读取冻结归档与截止前本地事实。

保留股票身份、正文、公司介绍、D20 与行情辅助函数；不创作研究或修改归档。
当前网页入口为 tools/render_prism_web.py，本模块不再生成退役旧网页。
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from stock_analyzer.ops.company_introduction import (
    default_intro_root,
    load_introductions_for_display,
)
from stock_analyzer.ops.forward_selection import selection_output_class

try:
    import web_display_contract
except ImportError:  # 支持 tools 包导入与 Prism 脚本导入
    from tools import web_display_contract  # type: ignore[no-redef]

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


# 交易日历中允许的最大连续无记录天数：正常周末 2 天、最长法定长假 8 天；
# 超过该缺口说明日历没有覆盖所需范围，必须明确失败而不是拿行情目录补日历。
MAX_CALENDAR_GAP_DAYS = 10


def read_trade_calendar(root: Path) -> dict[date, bool]:
    """本地 SSE 交易日历（cal_date → is_open），与数据管道同一数据源。"""
    calendar: dict[date, bool] = {}
    base = root / "local_warehouse" / "facts" / "trade_calendar"
    for path in base.glob("cal_year=*/data.parquet"):
        try:
            frame = pd.read_parquet(path)
        except Exception:
            continue
        for row in frame.itertuples():
            try:
                day = date.fromisoformat(str(row.cal_date)[:10])
            except ValueError:
                continue
            if str(row.exchange) == "SSE" and pd.notna(row.is_open):
                calendar[day] = bool(row.is_open)
    return calendar


def list_sessions(root: Path, start: date, end: date) -> list[date]:
    """用本地 SSE trade_calendar 推导 [start, end] 的交易日序列。

    不再以行情分区文件是否存在决定开市日；有交易日但缺行情时由调用方保留
    空位（null），保证观察天数不被数据缺口缩短。日历覆盖不足时明确失败。
    """
    calendar = read_trade_calendar(root)
    if not calendar:
        raise ValueError(
            f"本地交易日历为空（{root / 'local_warehouse' / 'facts' / 'trade_calendar'}），"
            f"无法推导 {start.isoformat()}—{end.isoformat()} 的交易日；请先补齐 trade_calendar，"
            "不得用行情目录或周历代替"
        )
    sessions: list[date] = []
    gap = 0
    gap_start: date | None = None
    day = start
    while day <= end:
        is_open = calendar.get(day)
        if is_open is True:
            sessions.append(day)
            gap = 0
        else:
            # is_open 为 False（明确休市）与日历无记录都算缺口；只有连续缺口过长
            # 才判定为覆盖不足（正常周末与法定长假不会超过 MAX_CALENDAR_GAP_DAYS）。
            if is_open is None:
                gap += 1
                if gap == 1:
                    gap_start = day
                if gap > MAX_CALENDAR_GAP_DAYS:
                    raise ValueError(
                        f"本地交易日历未覆盖 {gap_start.isoformat()} 起连续 {gap} 天"
                        f"（窗口 {start.isoformat()}—{end.isoformat()}），无法可靠推导交易日；"
                        "请先补齐 trade_calendar，不得猜测"
                    )
            else:
                gap = 0
        day += timedelta(days=1)
    if not sessions:
        raise ValueError(
            f"本地交易日历在 {start.isoformat()}—{end.isoformat()} 内没有任何开市日，"
            "无法生成展示时间轴"
        )
    return sessions


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


def _regular_review_title(text: str, name: str) -> str:
    """读取 AI 已写的标题首段，不推断或改写研究结论。"""
    title, separator, body = text.partition("\n\n")
    prefix = f"{name}｜"
    if (
        name and separator and body.strip() and "\n" not in title
        and title.startswith(prefix) and title[len(prefix):].strip()
    ):
        return title
    return ""


def _review_headline(review: dict[str, Any], episode: dict[str, Any]) -> str:
    """简评优先取 AI 标题首段，取不到（含旧稿）回退首句；详评路径不变。"""
    text = str(review.get("current_review") or "")
    if str(review.get("review_kind") or "brief") == "brief":
        title = _regular_review_title(text, str(episode.get("name") or ""))
        if title:
            return title
    return _first_sentence(text)


def _raw_code(value: Any) -> str | None:
    """原样透传枚举字符串；空值输出 None，不猜测默认值。"""
    if value in (None, ""):
        return None
    return str(value)


def _review_facts(episode: dict[str, Any]) -> list[str]:
    def pct(value: float) -> str:
        return f"{'+' if value > 0 else ''}{value * 100:.2f}%"

    if not episode.get("formal_return_started") or episode.get("entry_open") is None:
        limitations = episode.get("data_limitations") or []
        if "missing_price_path" in limitations:
            return ["价格数据缺失", "无可参与价格"]
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
                outlook_raw = alert.get("outlook_1_3d")
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
                    # 结构化枚举严格透传；报告路径没有 view_change 字段，保持 null，
                    # 由台账路径合并时补齐（F02/E4：缺值不默认 unchanged）。
                    "viewChange": None,
                    "assessmentCode": _raw_code(review.get("current_assessment")),
                    "outlookCode": _raw_code(outlook_raw),
                    "outlookDirection": web_display_contract.outlook_direction(outlook_raw),
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
            # 保留原始枚举：缺值/未知值不再默认成“维持原判断”（F02/E4）。
            raw_view_change = review.get("view_change")
            view_change = _raw_code(raw_view_change)
            view_changed = view_change in {"strengthened", "weakened", "invalidated"}
            label = VIEW_CHANGE_TEXT.get(view_change) if view_change else None
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
                **web_display_contract.review_enums(review),
                "currentOpportunity": web_display_contract.current_opportunity_for_display(review),
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
                    if structured["review_kind"] in {"regular_detail", "checkpoint_detail"}:
                        title = _regular_review_title(
                            existing["copy"], str(episode.get("name") or "")
                        )
                        if title:
                            existing["headline"] = title
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
                "as_of": str(ledger.get("as_of") or ""),
                "day": int(review.get("day_number") or 0),
                "checkpoint": review.get("checkpoint"),
                "headline": _review_headline(review, episode),
                "copy": str(review.get("current_review") or ""),
                "summary_copy": str(review.get("current_review") or ""),
                "review_kind": str(review.get("review_kind") or "brief"),
                "facts": _review_facts(episode),
                "base": OUTLOOK_TEXT.get(str(review.get("outlook_1_3d")), ""),
                "outlookReason": str(review.get("outlook_reason_plain_language") or ""),
                "assessmentText": ASSESSMENT_TEXT.get(
                    str(review.get("current_assessment")), ""
                ),
                **web_display_contract.review_enums(review),
                "currentOpportunity": web_display_contract.current_opportunity_for_display(review),
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
    from stock_analyzer.ops.forward_monitor import final_review_history

    finals = final_review_history(monitor_dir, analysis_date)
    history: dict[str, list[dict[str, Any]]] = {}
    for (episode_id, _day), item in merged.items():
        final = finals.get(episode_id)
        # 最早冻结日期之前的回看没有后来结案；同日还须核对截止。
        if final is not None and final["analysis_date"] <= _day:
            item_stamp = _parse_as_of(item.get("as_of"))
            final_stamp = _parse_as_of(final.get("as_of"))
            if final["analysis_date"] < _day or (
                item_stamp is not None and final_stamp is not None
                and final_stamp <= item_stamp
            ):
                source_snapshot = monitor_dir / f"snapshot-{final['analysis_date']}.json"
                metrics = {}
                if source_snapshot.is_file():
                    source = json.loads(source_snapshot.read_text(encoding="utf-8"))
                    original = next((row for row in source.get("episodes", [])
                                     if row.get("episode_id") == episode_id), {})
                    metrics = {key: original.get(key) for key in (
                        "d20_close_return_since_entry", "d20_max_close_return_since_entry",
                        "d20_mae_since_entry",
                    )}
                item["finalTwentyDayReview"] = {**final, "metrics": metrics}
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
            action_iso,
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
        date_key = item["date"]
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
            [str(first_close), "milestone", "收盘达到20%", "推荐后收盘首次达到约20%涨幅"],
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
                str(first_high),
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
    final_source = next((item["finalTwentyDayReview"] for item in review_items
                         if item.get("finalTwentyDayReview")), None)
    if final_source:
        frozen = final_source["final_twenty_day_review"]
        candidate = (
            1,
            [
                final_source["analysis_date"],
                "milestone",
                "20日固定结案",
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


def extract_daily_statement(
    selection_dir: Path, formed_on: str, name: str, ts_code: str
) -> tuple[str, str]:
    """从形成日日报中逐字提取该股「名称（代码）」小节正文。

    返回 (statement, miss_reason)。miss_reason 为 "" 表示提取成功；
    "no_report" 表示形成日无日报存档；"not_found" / "ambiguous" 表示
    小节未找到或不唯一（同日同名小节多于一个时宁缺毋滥，不猜第一个）。
    正文不含小节标题行，取标题行之后到下一个任意级 markdown 标题为止。
    """
    formed_on = str(formed_on or "").strip()
    name = str(name or "").strip()
    code6 = str(ts_code or "").split(".")[0].strip()
    if not formed_on or not name or not re.fullmatch(r"\d{6}", code6):
        return "", "no_report"
    report_path = selection_dir / f"daily-research-{formed_on}.md"
    if not report_path.is_file():
        return "", "no_report"
    title_re = re.compile(rf"{re.escape(name)}（{code6}(?:\.(?:SH|SZ|BJ))?）")
    try:
        lines = report_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return "", "no_report"
    hits: list[int] = []
    for index, line in enumerate(lines):
        heading = re.match(r"^(#{2,6})\s+(.+?)\s*$", line)
        if heading and title_re.fullmatch(heading.group(2)):
            hits.append(index)
    if not hits:
        return "", "not_found"
    if len(hits) > 1:
        return "", "ambiguous"
    start = hits[0] + 1
    end = len(lines)
    for index in range(start, len(lines)):
        if lines[index].lstrip().startswith("#"):
            end = index
            break
    body = "\n".join(lines[start:end]).strip()
    return (body, "") if body else ("", "not_found")


STATEMENT_OVERRIDES_NAME = "statement-overrides.json"


def load_statement_overrides(monitor_dir: Path) -> dict[str, dict[str, Any]]:
    """本机显示层替换表（local_archive 内，不入 Git）；键为 `ts_code:recDate`。

    正式归档不因替换改动；文件缺失或损坏时按无替换处理。
    """
    path = monitor_dir / STATEMENT_OVERRIDES_NAME
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {key: value for key, value in data.items() if isinstance(value, dict)}


def apply_statement_override(
    overrides: dict[str, dict[str, Any]], ts_code: str, rec_iso: str, statement: str
) -> tuple[str, str | None]:
    """命中替换表时返回（范本正文, "adopted_rewrite"），否则原样返回。"""
    entry = overrides.get(f"{ts_code}:{rec_iso}")
    if not isinstance(entry, dict):
        return statement, None
    text = str(entry.get("statement") or "").strip()
    if not text:
        return statement, None
    return text, "adopted_rewrite"


def _statement_missing_issue(
    ts_code: str, formed_on: str, name: str, miss_reason: str
) -> dict[str, Any] | None:
    """日报存在但小节缺失/不唯一才是真实缺口（T32/T33）；
    形成日本无日报存档属正常历史事实，静默回落，由页脚文案如实说明。"""
    if miss_reason == "no_report":
        return None
    message = (
        f"形成日 {formed_on} 日报中未找到唯一「{name}（{ts_code}）」小节，"
        "展示回落为存档理由摘要。"
    )
    return {
        "code": "statement_missing",
        "recordKey": f"{ts_code}:{formed_on}",
        "reviewDate": None,
        "message": message,
        "origin": "display_data_adapter",
    }


def build_payload(
    root: Path,
    monitor_dir: Path,
    analysis_date: date,
    report: dict[str, Any],
    snapshot: dict[str, Any],
    selection_dir: Path | None = None,
    intro_root: Path | None = None,
) -> dict[str, Any]:
    selection_dir = selection_dir or SELECTION_DIR
    intro_root = intro_root or default_intro_root(root)
    statement_overrides = load_statement_overrides(monitor_dir)
    as_of = str(report.get("as_of") or snapshot.get("as_of"))
    episodes = {
        str(item.get("episode_id")): item
        for item in snapshot.get("episodes", [])
        if isinstance(item, dict)
    }
    # 事件等待型条件记录（conditional_event）按复盘合同不进日报与台账、永不复盘，
    # 网页与日报同口径只展示正式推荐（含次日待首日）；记录本身仍留在 snapshot/trace。
    selected = [
        episode
        for episode in episodes.values()
        if episode.get("role") == "selected"
        and inferred_output_class(episode)
        in {"confirmed_active", "legacy_v1_not_rewritten"}
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
    names = group_name_map(selection_dir)
    catalog = industry_catalog_names(root)

    # D0：最新报告页面把次日开盘前生效的新推荐以"待首日观察"列出（数据来自配对选股轨迹）。
    # 去重身份是 (完整代码, action_date)：同股在更晚行动日的再次入选必须保留，不被旧记录滤掉（F05）。
    d0_entries, d0_action_iso = load_d0_entries(
        selection_dir, monitor_dir, analysis_date
    )
    displayed_ids = {
        (str(item["ts_code"]), str(item.get("action_date") or "")) for item in selected
    }
    d0_entries = [
        entry
        for entry in d0_entries
        if (entry["ts_code"], d0_action_iso) not in displayed_ids
    ]

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
    sessions = list_sessions(root, start, analysis_date)

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
    # 全局裁剪：从第一个有任何事实的交易日开始，保证 DATES / market / industry / candles 对齐；
    # 但任何正在展示记录的首日观察日期（含事件首定价日）不得被裁掉（F04）。
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
    session_isos = [day.isoformat() for day in sessions]
    required_indices = [
        session_isos.index(iso)
        for iso in {
            str(item.get("action_date") or "")
            for item in selected
            if item.get("action_date")
        }
        if iso in session_isos
    ]
    trim_candidates = candidates + required_indices
    trim = min(trim_candidates) if trim_candidates else 0
    sessions = sessions[trim:]
    market_series = facts["market"][trim:]
    industry_series = {
        code: values[trim:] for code, values in facts["industry"].items()
    }
    candle_series = {code: values[trim:] for code, values in facts["candles"].items()}

    stocks_payload: list[dict[str, Any]] = []
    identity_seen: dict[tuple[str, str], str] = {}
    for episode in selected:
        episode_id = str(episode["episode_id"])
        ts_code = str(episode["ts_code"])
        action_iso = str(episode.get("action_date") or analysis_date.isoformat())
        # 首日观察日期不在交易日序列时不得用数组第 0 日顶替（F04）：
        # recIndex/ref 保持缺失，并输出 dataIssues 说明具体缺口。
        rec_index: int | None = next(
            (i for i, day in enumerate(sessions) if day.isoformat() == action_iso), None
        )
        data_issues: list[dict[str, Any]] = []
        if rec_index is None:
            data_issues.append(
                {
                    "code": "missing_rec_session",
                    "recordKey": f"{ts_code}:{action_iso}",
                    "reviewDate": None,
                    "message": (
                        f"首日观察日期 {action_iso} 不在本地交易日历的交易日序列中，"
                        "参考价与推荐后表现未计算；请核对该记录的 action_date。"
                    ),
                    "origin": "display_data_adapter",
                }
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
            action_bar = (
                bars[rec_index] if rec_index is not None and rec_index < len(bars) else None
            )
            if action_bar and action_bar[0] is not None:
                ref = action_bar[0]
                ref_kind = "formal"
            elif rec_index is not None:
                data_issues.append(
                    {
                        "code": "missing_entry_quote",
                        "recordKey": f"{ts_code}:{action_iso}",
                        "reviewDate": None,
                        "message": "首日开盘价缺失，未计算较参考价表现；不改用其他日期的价格。",
                        "origin": "display_data_adapter",
                    }
                )
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
        # 有无推荐后价格不等于停牌（F04）：只有明确的停牌/执行状态才能标停牌；
        # 缺价格路径仅输出 dataIssues，不改变研究的阶段与失效状态。
        has_post = rec_index is not None and any(
            bar[3] is not None for bar in bars[rec_index:]
        )
        suspended = False
        if rec_index is not None and not has_post:
            data_issues.append(
                {
                    "code": "missing_price_path",
                    "recordKey": f"{ts_code}:{action_iso}",
                    "reviewDate": None,
                    "message": (
                        "推荐后暂无可用收盘数据，较参考价表现留空；"
                        "这是价格数据缺失，不等于停牌或无法执行。"
                    ),
                    "origin": "display_data_adapter",
                }
            )

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

        thesis = episode.get("original_research_thesis") or {}
        company_info = thesis.get("company_information") or {}
        review_items = history.get(episode_id, [])
        reviews = [item for item in review_items if not item.get("eventOnly")]
        group_code = str(episode.get("original_group_code") or "")
        industry_kind = facts.get("industry_kind", {}).get(group_code, "none")
        # UI 身份仍是 code:recDate；同一身份出现两个不同真实 episode 时明确报错，
        # 不取最后一条静默覆盖（F05/E3）。
        identity = (ts_code, action_iso)
        previous_episode = identity_seen.get(identity)
        if previous_episode is not None and previous_episode != episode_id:
            raise ValueError(
                f"同一记录身份 {ts_code}:{action_iso} 对应多个 episode"
                f"（{previous_episode} / {episode_id}），展示身份无法唯一对应；"
                "请先在上游解决冲突，不得静默覆盖"
            )
        identity_seen[identity] = episode_id
        formed_on_iso = (
            str(episode["formation_date"]) if episode.get("formation_date") else ""
        )
        statement_full, statement_miss = extract_daily_statement(
            selection_dir,
            formed_on_iso,
            str(episode.get("name") or ts_code),
            ts_code,
        )
        statement_full, statement_source = apply_statement_override(
            statement_overrides, ts_code, action_iso, statement_full
        )
        if statement_miss:
            issue = _statement_missing_issue(
                ts_code, formed_on_iso, str(episode.get("name") or ts_code), statement_miss
            )
            if issue:
                data_issues.append(issue)
        stocks_payload.append(
            {
                "code": ts_code,
                "name": str(episode.get("name") or ts_code),
                "recDate": action_iso,
                "formedOn": (
                    str(episode["formation_date"]) if episode.get("formation_date") else None
                ),
                "episodeId": episode_id,
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
                "dataIssues": data_issues,
                "statementFull": statement_full,
                "statementSource": statement_source,
                "trackingStatus": (
                    str(episode.get("tracking_status") or "") or None
                ),
                "trackingExitDate": (
                    str(episode["tracking_exit_date"])
                    if episode.get("tracking_exit_date")
                    else None
                ),
                "trackingExitReason": (
                    str(episode.get("tracking_exit_reason") or "") or None
                ),
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
        d0_formed = analysis_date.isoformat()
        d0_statement, d0_miss = extract_daily_statement(
            selection_dir, d0_formed, str(entry.get("name") or ts_code), ts_code
        )
        d0_statement, d0_statement_source = apply_statement_override(
            statement_overrides, ts_code, d0_action_iso, d0_statement
        )
        d0_issues: list[dict[str, Any]] = []
        if d0_miss:
            issue = _statement_missing_issue(
                ts_code, d0_formed, str(entry.get("name") or ts_code), d0_miss
            )
            if issue:
                d0_issues.append(issue)
        stocks_payload.append(
            {
                "code": ts_code,
                "name": entry["name"],
                "recDate": d0_action_iso,
                "formedOn": analysis_date.isoformat(),
                "episodeId": None,
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
                "dataIssues": d0_issues,
                "statementFull": d0_statement,
                "statementSource": d0_statement_source,
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
                        d0_action_iso,
                        "rec",
                        "正式推荐",
                        _short(entry["reason"], 48),
                    ]
                ],
            }
        )
    stocks_payload.sort(key=lambda item: (item["recDate"], item["code"]), reverse=True)

    # 公司介绍按原推荐身份 (ts_code, action_date) 绑定，D0 与后续 episode 同一
    # 只读加载路径；身份无法对照原 trace 证明时保持缺项，不取同代码最新一篇。
    if stocks_payload:
        intros = load_introductions_for_display(
            selection_dir,
            intro_root,
            [
                (
                    item["code"],
                    item["recDate"],
                    item.get("formedOn"),
                )
                for item in stocks_payload
            ],
        )
        for item in stocks_payload:
            intro = intros.get((item["code"], item["recDate"]))
            if intro is not None:
                item["companyIntroduction"] = intro

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
    session_dates = [day.isoformat() for day in sessions]
    return {
        # 展示数据合同版本 2：新增 sessionDates 完整交易日定位（E1）。
        "displaySchemaVersion": 2,
        "analysis_date": analysis_date.isoformat(),
        "as_of": as_of,
        "market_name": MARKET_NAME,
        # 完整 ISO 交易日序列：定位与比较一律用它（F03/E1）。
        "sessionDates": session_dates,
        # MM-DD 仅保留给旧 V4 布局显示，不参与年份比较或查找。
        "dates": [day[5:] for day in session_dates],
        "market": market_series,
        "date_files": date_files,
        "review_dates": review_dates,
        "sourceInfo": web_display_contract.source_info(),
        "observationPolicy": web_display_contract.observation_policy(),
        "stocks": stocks_payload,
    }
