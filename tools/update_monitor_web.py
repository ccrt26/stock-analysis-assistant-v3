"""检查 codex 日报产出并把最新复盘观察更新到统一地址 index.html。

幂等脚本：只渲染"snapshot + report 成对出现且输入有变化"的日期；页面只维护一个
固定地址 `local_archive/forward_monitor/index.html`（永远等于最新一天的日报），
不再每天生成按日期命名的页面。休市日或 codex 未产出时安静退出（exit 0），与手动
兜底是同一条命令。休市口径与数据管道一致：读本地交易日历（SSE trade_calendar）
的 is_open，非交易日默认不启动（对齐 research_data_job 的 close 阶段约定）。

用法：
    ./.venv/bin/python tools/update_monitor_web.py                    # 自动 / 手动共用
    ./.venv/bin/python tools/update_monitor_web.py --force            # 忽略状态全量重渲染
    ./.venv/bin/python tools/update_monitor_web.py --today 2026-10-01 # 模拟休市日
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
try:
    from tools import render_monitor_web as renderer  # 与测试/其他工具同一模块实例
except ImportError:  # 直接以脚本方式运行（python tools/update_monitor_web.py）
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import render_monitor_web as renderer

BEIJING = timezone(timedelta(hours=8))
STATE_NAME = ".web-publish-state.json"
LOG_NAME = "web-update.log"
INDEX_NAME = "index.html"
SNAPSHOT_RE = re.compile(r"^snapshot-(\d{4}-\d{2}-\d{2})\.json$")
LEDGER_PLACEHOLDER = "ledger:missing"


def beijing_today() -> date:
    return datetime.now(BEIJING).date()


def read_trade_calendar(root: Path) -> dict[date, bool]:
    """本地 SSE 交易日历（cal_date → is_open），与数据管道同一数据源。"""
    import pandas as pd

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


def scan_candidate_dates(monitor_dir: Path) -> list[date]:
    """snapshot + report 成对（文件名严格匹配日期、排除 pre-* 备份）的日期，升序。"""
    dates: list[date] = []
    for path in monitor_dir.glob("snapshot-*.json"):
        matched = SNAPSHOT_RE.match(path.name)
        if not matched:
            continue
        try:
            day = date.fromisoformat(matched.group(1))
        except ValueError:
            continue
        if (monitor_dir / f"monitor-report-{day.isoformat()}.json").is_file():
            dates.append(day)
    return sorted(dates)


def scan_incomplete_dates(monitor_dir: Path, complete: set[date]) -> list[date]:
    """只有快照、没有报告的日期（codex 可能写到一半），升序。"""
    dates: list[date] = []
    for path in monitor_dir.glob("snapshot-*.json"):
        matched = SNAPSHOT_RE.match(path.name)
        if not matched:
            continue
        try:
            day = date.fromisoformat(matched.group(1))
        except ValueError:
            continue
        if day not in complete:
            dates.append(day)
    return sorted(dates)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def input_digest(monitor_dir: Path, day: date) -> tuple[str, bool]:
    """report + snapshot + 当日台账的字节哈希；台账缺失以固定占位参与哈希。"""
    iso = day.isoformat()
    ledger_path = monitor_dir / f"daily-formal-reviews-{iso}.json"
    ledger_exists = ledger_path.is_file()
    parts = [
        f"monitor-report:{_sha256_file(monitor_dir / f'monitor-report-{iso}.json')}",
        f"snapshot:{_sha256_file(monitor_dir / f'snapshot-{iso}.json')}",
        f"ledger:{_sha256_file(ledger_path)}" if ledger_exists else LEDGER_PLACEHOLDER,
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest(), ledger_exists


def load_state(state_path: Path) -> dict:
    """状态文件损坏 / 不可读时视为空，全量重渲染重建。"""
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if not isinstance(state, dict) or not isinstance(state.get("published"), dict):
            raise ValueError("state shape invalid")
        return state
    except FileNotFoundError:
        return {"version": 1, "published": {}}
    except Exception:
        return {"version": 1, "published": {}}


def save_state(state_path: Path, state: dict) -> None:
    tmp = state_path.with_name(state_path.name + ".tmp")
    tmp.write_text(
        json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(tmp, state_path)


def validate_rendered(html_path: Path, day: date) -> tuple[bool, int]:
    if not html_path.is_file():
        return False, 0
    try:
        html = html_path.read_text(encoding="utf-8")
        payload = json.loads(
            html.split("DATA = ", 1)[1].split(";\nconst DATES", 1)[0].replace("<\\/", "</")
        )
    except Exception:
        return False, 0
    if str(payload.get("analysis_date")) != day.isoformat():
        return False, 0
    return True, len(payload.get("stocks") or [])


def log_line(monitor_dir: Path, message: str) -> None:
    stamp = datetime.now(BEIJING).isoformat(timespec="seconds")
    with (monitor_dir / LOG_NAME).open("a", encoding="utf-8") as fh:
        fh.write(f"[{stamp}] {message}\n")


def render_date(day: date, monitor_dir: Path, out_path: Path) -> None:
    renderer.main(["--date", day.isoformat(), "--monitor-dir", str(monitor_dir), "--out", str(out_path)])


def _tmp_index_path(monitor_dir: Path) -> Path:
    return monitor_dir / f"{INDEX_NAME}.{os.getpid()}.tmp"


def index_is_healthy(monitor_dir: Path, latest: date | None) -> bool:
    if latest is None:
        return True
    return validate_rendered(monitor_dir / INDEX_NAME, latest)[0]


def rebuild_index(monitor_dir: Path, latest: date) -> None:
    """把最新候选日期重渲染并原子重建统一地址 index.html。"""
    tmp = _tmp_index_path(monitor_dir)
    try:
        render_date(latest, monitor_dir, tmp)
        ok, stocks = validate_rendered(tmp, latest)
        if not ok:
            raise RuntimeError("index.html 重建产物校验失败")
        os.replace(tmp, monitor_dir / INDEX_NAME)
        log_line(monitor_dir, f"rebuilt index.html -> {latest.isoformat()} stocks={stocks}")
    finally:
        if tmp.exists():
            tmp.unlink()


def run_update(
    project_root: Path,
    monitor_dir: Path,
    today: date,
    *,
    force: bool = False,
) -> int:
    calendar = read_trade_calendar(project_root)
    candidates = scan_candidate_dates(monitor_dir)
    latest = candidates[-1] if candidates else None
    state = load_state(monitor_dir / STATE_NAME)
    published = state.setdefault("published", {})

    pending: list[tuple[date, str]] = []
    ledger_warnings: list[date] = []
    for day in candidates:
        digest, ledger_exists = input_digest(monitor_dir, day)
        if not ledger_exists:
            ledger_warnings.append(day)
        record = published.get(day.isoformat())
        if force or not isinstance(record, dict) or record.get("input_sha256") != digest:
            pending.append((day, digest))

    gate = "open" if calendar.get(today) else ("closed" if today in calendar else "uncovered")

    if not pending:
        # 自愈：在一切早退之前检查统一地址（缺失 / 落后 / 不可解析则重建最新日期）
        if latest is not None and not index_is_healthy(monitor_dir, latest):
            try:
                rebuild_index(monitor_dir, latest)
            except Exception as exc:
                log_line(monitor_dir, f"index.html 重建失败：{exc} status=error")
                return 1
        if gate == "closed":
            log_line(monitor_dir, f"today={today} gate=closed pending=0 休市，不启动")
            return 0
        if gate == "uncovered" and today.weekday() >= 5:
            log_line(monitor_dir, f"today={today} gate=uncovered weekend pending=0 休市（日历未覆盖，按周末跳过）")
            return 0
    if gate == "uncovered" and today.weekday() < 5:
        log_line(monitor_dir, f"today={today} gate=uncovered weekday=按周一至周五候选继续，日历未覆盖请尽快补齐")

    if not pending:
        complete = set(candidates)
        incomplete = [
            day
            for day in scan_incomplete_dates(monitor_dir, complete)
            if not complete or day > max(complete)
        ]
        if incomplete:
            log_line(
                monitor_dir,
                f"today={today} 检测到报告未完成：{[d.isoformat() for d in incomplete]}，等待人工或下个检查点",
            )
        else:
            log_line(monitor_dir, f"today={today} gate={gate} pending=0 无新增日报，等待 codex 或手动处理")
        return 0

    gate_label = {"open": "trade_day", "closed": "closed_defensive", "uncovered": "uncovered"}[gate]
    log_line(monitor_dir, f"today={today} gate={gate_label} pending={len(pending)}")
    pending_days = {day for day, _ in pending}
    for day in [d for d in ledger_warnings if d in pending_days]:
        log_line(monitor_dir, f"{day.isoformat()} 台账缺失，仅渲染报告与快照（警告）")

    failures: list[date] = []
    for day, digest in pending:
        iso = day.isoformat()
        tmp = _tmp_index_path(monitor_dir)
        try:
            render_date(day, monitor_dir, tmp)
            ok, stocks = validate_rendered(tmp, day)
            if not ok:
                raise RuntimeError("渲染产物校验失败（HTML 缺失 / payload 不可解析 / 日期不一致）")
            if latest is not None and day == latest:
                os.replace(tmp, monitor_dir / INDEX_NAME)
            published[iso] = {
                "input_sha256": digest,
                "rendered_at": datetime.now(BEIJING).isoformat(timespec="seconds"),
                "stocks": stocks,
            }
            save_state(monitor_dir / STATE_NAME, state)
            log_line(monitor_dir, f"rendered={iso} stocks={stocks} status=ok")
        except Exception as exc:
            failures.append(day)
            log_line(monitor_dir, f"rendered={iso} status=error error={exc}")
        finally:
            if tmp.exists():
                tmp.unlink()

    if failures:
        log_line(
            monitor_dir,
            f"失败 {len(failures)} 个日期：{[d.isoformat() for d in failures]}，等待下个检查点或手动重跑",
        )
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check codex output and update the local monitor review web pages"
    )
    parser.add_argument("--today", default=None, help="override today (YYYY-MM-DD), for tests and drills")
    parser.add_argument("--project-root", default=None, help="override project root (derives warehouse and defaults)")
    parser.add_argument("--monitor-dir", default=None, help="override monitor archive directory (passed through to renderer)")
    parser.add_argument("--force", action="store_true", help="ignore published state and re-render all candidate dates")
    args = parser.parse_args(argv)

    project_root = Path(args.project_root).resolve() if args.project_root else PROJECT_ROOT
    monitor_dir = (
        Path(args.monitor_dir).resolve()
        if args.monitor_dir
        else project_root / "local_archive" / "forward_monitor"
    )
    today = date.fromisoformat(args.today) if args.today else beijing_today()
    return run_update(project_root, monitor_dir, today, force=args.force)


if __name__ == "__main__":
    sys.exit(main())
