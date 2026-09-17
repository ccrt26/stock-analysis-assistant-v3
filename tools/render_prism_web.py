"""把已冻结的每日走势复盘渲染成「观澜 · A2」主用展示页面。

复用 tools/render_monitor_web.build_payload 输出的同一份数据（字段合同见
tools/guanlan-prism/docs/03-数据接口与口径.md），并做两处展示层附加：
1. marketIndices：从本地事实仓 index_daily 读取已配置指数的日线（含前收），
   只取 trade_date ≤ analysis_date 且 available_at ≤ 报告 as_of 的事实；
   本地没有的指数保持缺失，不由展示层补数。
2. presentation：默认四个市场代码与 deepLimit=8（可用 --indices 调整三至五项）。

当日普通详评名单直接由页面规则从 regular_detail 标记推导（上游无显式排序
名单时不编造 dailyDeepReview）。不修改选股、复盘、V4 渲染器或定时任务。

主用 A2（2026-09-13 用户批准）：
1. prism-a2-report-<date>.html —— 新版按日期留档；
2. style-preview/prism-a2.html —— 保留现有主用地址，旧日期不覆盖较新页面。
prism.html 及 prism-report-* 保留为停更备用，不作为数据来源，不再写入。
价量补充日线随 HTML 一起内嵌，使用同一报告截止，不需要外部侧表文件。

用法：
    ./.venv/bin/python tools/render_prism_web.py                  # 最新一个 snapshot
    ./.venv/bin/python tools/render_prism_web.py --date 2026-09-02
    ./.venv/bin/python tools/render_prism_web.py --date 2026-09-07 --action-date 2026-09-08 --as-of 2026-09-07T18:30:00+08:00
    ./.venv/bin/python tools/render_prism_web.py --out 任意路径.html
    ./.venv/bin/python tools/render_prism_web.py --indices 000001.SH,399001.SZ
"""

from __future__ import annotations

import argparse
import fcntl
import importlib.util
import json
import os
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRISM_ROOT = PROJECT_ROOT / "tools" / "guanlan-prism"
MARKET_SOURCE = "本地事实仓 index_daily（available_at ≤ 报告 as_of）"

try:
    import web_display_contract
except ImportError:  # 兼容 `python tools/render_prism_web.py` 直接运行
    sys.path.insert(0, str(PROJECT_ROOT / "tools"))
    import web_display_contract  # type: ignore[no-redef]


def load_modules():
    """与测试复用同一 render_monitor_web 模块实例（共享 payload 组装）。"""
    sys.path.insert(0, str(PROJECT_ROOT / "tools"))
    try:
        from tools import render_monitor_web
    except ImportError:  # 直接以脚本方式运行（python tools/render_prism_web.py）
        import render_monitor_web  # type: ignore[no-redef]

    modules = {}
    for name in ("build_preview_a2", "adapt_snapshot"):
        spec = importlib.util.spec_from_file_location(
            f"guanlan_prism_{name}", PRISM_ROOT / "tools" / f"{name}.py"
        )
        if spec is None or spec.loader is None:
            raise FileNotFoundError(f"missing PRISM module at {PRISM_ROOT / 'tools' / name}.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        modules[name] = module
    return render_monitor_web, modules["adapt_snapshot"], modules["build_preview_a2"]


def local_index_rows(
    renderer,
    root: Path,
    codes: list[str],
    sessions: list[date],
    as_of: datetime,
) -> list[dict]:
    """已存在的本地指数日线行；缺日、缺指数如实空缺，不补数。"""
    cutoff = renderer._as_utc_cutoff(as_of)
    rows: list[dict] = []
    for day in sessions:
        frame = renderer._read_day_frames(root, "index_daily", day, cutoff)
        if frame is None:
            continue
        frame = frame[frame["index_code"].astype(str).isin(codes)]
        frame = frame.sort_values("available_at").drop_duplicates(["index_code"], keep="last")
        for _, row in frame.iterrows():
            close = renderer._single_number(row.get("close"))
            if close is None:
                continue
            rows.append(
                {
                    "ts_code": str(row["index_code"]),
                    "trade_date": day.isoformat(),
                    "close": close,
                    "pre_close": renderer._single_number(row.get("pre_close")),
                    "source": MARKET_SOURCE,
                }
            )
    return rows


def checked_cutoff(value: str) -> datetime:
    cutoff = datetime.fromisoformat(value)
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise ValueError("as_of must include a timezone")
    return cutoff


def load_completed_archives(renderer, monitor_dir, analysis_date, action_date, as_of, *, selection_dir=None):
    """只读核对正式归档；不调用 prepare/record，不重新判断研究结论。"""
    from stock_analyzer.ops import forward_monitor as monitor
    from stock_analyzer.ops.forward_selection import DailyResearchTraceV4

    iso = analysis_date.isoformat()
    paths = {
        "trace": (selection_dir or renderer.SELECTION_DIR) / f"research-trace-{iso}.json",
        "snapshot": monitor_dir / f"snapshot-{iso}.json",
        "ledger": monitor_dir / f"daily-formal-reviews-{iso}.json",
        "report": monitor_dir / f"monitor-report-{iso}.json",
        "markdown": monitor_dir / f"monitor-report-{iso}.md",
    }
    inputs = {path: path.read_bytes() for path in paths.values()}
    if any(not content.strip() for content in inputs.values()):
        raise ValueError("formal archive contains an empty file")
    raw = {key: json.loads(inputs[path]) for key, path in paths.items() if key != "markdown"}
    trace = DailyResearchTraceV4.model_validate(raw["trace"])
    ledger = monitor.DailyFormalReviewLedgerV1.model_validate(raw["ledger"])
    report = monitor.DailyForwardMonitorReportV2.model_validate(raw["report"])
    snapshot = raw["snapshot"]
    if not isinstance(snapshot, dict) or snapshot.get("snapshot_version") != monitor.SNAPSHOT_VERSION:
        raise ValueError("formal snapshot version is invalid")
    if (trace.formation_date != analysis_date or trace.action_date != action_date
            or report.analysis_date != analysis_date or ledger.analysis_date != analysis_date
            or snapshot.get("analysis_date") != iso):
        raise ValueError("formal archive dates do not match the requested dates")
    if action_date <= analysis_date or as_of >= datetime.combine(action_date, datetime.min.time(), tzinfo=as_of.tzinfo):
        raise ValueError("requested cutoff must precede action_date")
    cutoffs = [raw[key].get("as_of", "") for key in ("trace", "snapshot", "ledger", "report")]
    if any(checked_cutoff(value) != as_of for value in cutoffs):
        raise ValueError("formal archive as_of does not match the requested cutoff")
    if not trace.research_result.research_completed or not trace.research_result.point_in_time_evidence_verified:
        raise ValueError("formal selection research is not complete")

    expected_ids = snapshot.get("daily_review_episode_ids")
    episode_rows = snapshot.get("episodes")
    if not isinstance(expected_ids, list) or not isinstance(episode_rows, list):
        raise ValueError("formal snapshot is missing its daily review scope")
    episodes = {row["episode_id"]: row for row in episode_rows}
    daily = {review.episode_id: review for review in ledger.reviews}
    if (len(episodes) != len(episode_rows) or len(expected_ids) != len(set(expected_ids))
            or set(daily) != set(expected_ids) or set(daily) - set(episodes)):
        raise ValueError("daily ledger must exactly cover snapshot episodes")
    for episode_id, review in daily.items():
        episode = episodes[episode_id]
        if (episode.get("role") != "selected"
                or monitor._episode_selection_output_class(episode) not in monitor.PUBLIC_FORMAL_OUTPUT_CLASSES
                or review.day_number != episode.get("day_number")):
            raise ValueError(f"daily review episode identity mismatch: {episode_id}")
    _, _, report_codes = monitor._three_route_grouping(
        snapshot=snapshot, daily_reviews=daily, episodes=episodes,
    )
    if {alert.ts_code for alert in report.alerts} != report_codes:
        raise ValueError("report must exactly cover checkpoint and regular detail stocks")
    for alert in report.alerts:
        ids = {episode_id for episode_id in daily if episodes[episode_id].get("ts_code") == alert.ts_code}
        if (set(alert.episode_ids) != ids or len(alert.episode_ids) != len(ids)
                or any(episodes[episode_id].get("name") != alert.name for episode_id in ids)):
            raise ValueError(f"report episode identity mismatch: {alert.ts_code}")
        for review in alert.episode_reviews:
            original = daily[review.episode_id]
            for field in ("current_assessment", "best_supported_explanation", "current_weak_or_failed_link", "final_twenty_day_review"):
                if getattr(review, field) != getattr(original, field):
                    raise ValueError(f"report contradicts daily ledger: {review.episode_id}")
    counts = report.pool_summary.model_dump()
    summary = snapshot.get("summary", {})
    expected_counts = {key: summary.get(key) for key in counts if key != "routine_stock_count"}
    expected_counts["routine_stock_count"] = (
        summary.get("distinct_stock_count", 0) - summary.get("attention_stock_count", 0)
    )
    attention_codes = {row["ts_code"] for row in snapshot.get("attention_stocks", [])}
    if counts != expected_counts or report.unreported_attention_count != len(attention_codes - report_codes):
        raise ValueError("report summary does not match snapshot")
    return raw["report"], snapshot, inputs


def write_html(path: Path, html: str) -> bool:
    """每个文件独立原子替换；相同内容不触碰修改时间。"""
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


def adopted_revision_payload(renderer, monitor_dir, analysis_date, report, snapshot):
    """显式采用已保存修订；临时读取视图不改变原正式记录及后续真实名单。"""
    config_path = monitor_dir / "display-revisions.json"
    if not config_path.exists():
        return None, {}
    config_bytes = config_path.read_bytes()
    config = json.loads(config_bytes)
    if not isinstance(config, dict):
        raise ValueError("display-revisions must be a date mapping")
    inputs = {config_path: config_bytes}
    revisions = []
    for iso, entry in sorted(config.items()):
        day = date.fromisoformat(iso)
        if day.isoformat() != iso or not isinstance(entry, dict):
            raise ValueError("invalid display revision identity")
        if day > analysis_date:
            continue
        archive = (PROJECT_ROOT / entry["archive"]).resolve()
        if not archive.is_relative_to((PROJECT_ROOT / "local_archive").resolve()):
            raise ValueError("display revision must be a local archive")
        adopted_at = checked_cutoff(entry["adopted_at"])
        source_monitor = archive / "local_archive/forward_monitor"
        source_selection = archive / "local_archive/forward_selection"
        original_trace = renderer.SELECTION_DIR / f"research-trace-{iso}.json"
        inputs[original_trace] = original_trace.read_bytes()
        identity = json.loads(inputs[original_trace])
        action = date.fromisoformat(identity["action_date"])
        cutoff = checked_cutoff(identity["as_of"])
        if adopted_at < cutoff:
            raise ValueError("display adoption cannot precede research cutoff")
        revised_report, revised_snapshot, revised_inputs = load_completed_archives(
            renderer, source_monitor, day, action, cutoff, selection_dir=source_selection,
        )
        inputs.update(revised_inputs)
        original_snapshot = monitor_dir / f"snapshot-{iso}.json"
        inputs[original_snapshot] = original_snapshot.read_bytes()
        original = json.loads(inputs[original_snapshot])
        if (checked_cutoff(original["as_of"]) != cutoff
                or set(original["daily_review_episode_ids"])
                != set(revised_snapshot["daily_review_episode_ids"])):
            raise ValueError("display revision must preserve original review scope and cutoff")
        old_episodes = {item["episode_id"]: item for item in original["episodes"]}
        new_episodes = {item["episode_id"]: item for item in revised_snapshot["episodes"]}
        for episode_id in original["daily_review_episode_ids"]:
            if any(old_episodes[episode_id].get(field) != new_episodes[episode_id].get(field)
                   for field in ("ts_code", "formation_date", "action_date", "day_number")):
                raise ValueError("display revision changes a historical episode identity")
        daily = source_selection / f"daily-research-{iso}.md"
        inputs[daily] = daily.read_bytes()
        if not inputs[daily].strip():
            raise ValueError("display revision is missing its complete daily report")
        revisions.append((day, adopted_at, source_monitor, source_selection,
                          revised_report, revised_snapshot, action))
    if not revisions:
        return None, inputs

    with tempfile.TemporaryDirectory(prefix="prism-adopted-") as directory:
        view = Path(directory)
        view_monitor, view_selection = view / "monitor", view / "selection"
        # 只复制展示会读取的文本归档，不复制事实仓、HTML 或正式 CSV。
        for source, target, patterns in (
            (monitor_dir, view_monitor, ("snapshot-*.json", "monitor-report-*.json",
                                         "daily-formal-reviews-*.json", "statement-overrides.json")),
            (renderer.SELECTION_DIR, view_selection, ("research-trace-*.json", "daily-research-*.md")),
        ):
            target.mkdir()
            for pattern in patterns:
                for path in source.glob(pattern):
                    stamp = path.stem[-10:]
                    if len(stamp) == 10 and stamp[:4].isdigit() and stamp > analysis_date.isoformat():
                        continue
                    inputs[path] = path.read_bytes()
                    (target / path.name).write_bytes(inputs[path])
        current = None
        for day, adopted_at, source_monitor, source_selection, revised_report, revised_snapshot, action in revisions:
            iso = day.isoformat()
            for stem in ("snapshot", "monitor-report", "daily-formal-reviews"):
                source = source_monitor / f"{stem}-{iso}.json"
                (view_monitor / source.name).write_bytes(inputs[source])
            if day == analysis_date:
                current = (adopted_at, action)
                report, snapshot = revised_report, revised_snapshot
                for name in (f"research-trace-{iso}.json", f"daily-research-{iso}.md"):
                    source = source_selection / name
                    (view_selection / name).write_bytes(inputs[source])
                # 已认可整份修订优先于更早的逐股文字覆盖。
                overrides = view_monitor / "statement-overrides.json"
                if overrides.exists():
                    items = json.loads(overrides.read_bytes())
                    overrides.write_text(json.dumps({key: value for key, value in items.items()
                        if not key.endswith(":" + action.isoformat())}, ensure_ascii=False))
        payload = renderer.build_payload(
            PROJECT_ROOT, view_monitor, analysis_date, report, snapshot,
            selection_dir=view_selection,
        )
    notes = [f"{day.isoformat()}复盘采用{adopted_at.date().isoformat()}修订版"
             for day, adopted_at, *_ in revisions]
    source_info = payload.setdefault("sourceInfo", {})
    source_info["label"] = "本地归档 · " + "；".join(notes)
    if current:
        adopted_at, action = current
        label = f"{analysis_date.isoformat()}修订版 · {adopted_at.date().isoformat()}采用"
        source_info["label"] = label
        stocks = [stock for stock in payload["stocks"] if stock.get("d0")]
        for stock in stocks:
            if not stock.get("statementFull"):
                raise ValueError("adopted recommendation is missing its complete statement")
            stock["statementSource"] = "adopted_rewrite"
        payload["delivery"] = {
            "status": "completed", "formationDate": analysis_date.isoformat(),
            "message": label + f"。已采用完整修订归档，推荐正文 {len(stocks)}/{len(stocks)}。",
            "recommendations": len(stocks), "total": len(stocks),
            "introductions": sum(bool(stock.get("companyIntroduction")) for stock in stocks),
        }
    return payload, inputs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Render the frozen daily monitor review as the A2 primary display page"
    )
    parser.add_argument(
        "--date", default=None, help="analysis date (YYYY-MM-DD), default latest snapshot"
    )
    parser.add_argument("--monitor-dir", default=None, help="override monitor archive directory")
    parser.add_argument("--action-date", help="expected action date; enables completed-archive checks")
    parser.add_argument("--as-of", help="expected frozen cutoff with timezone; requires --date and --action-date")
    parser.add_argument(
        "--out",
        default=None,
        help="override output HTML path (default prism-a2-report-<date>.html); backup paths are forbidden",
    )
    parser.add_argument(
        "--indices",
        default=None,
        help="comma-separated market codes (3-5), default 000001.SH,399001.SZ,399006.SZ,000688.SH",
    )
    parser.add_argument(
        "--no-publish",
        action="store_true",
        help="skip publishing style-preview/prism-a2.html (dated A2 file is still written)",
    )
    args = parser.parse_args(argv)
    if (args.action_date is not None or args.as_of is not None) and not all(
        (args.date, args.action_date, args.as_of)
    ):
        parser.error("automatic sync requires --date, --action-date and --as-of together")

    renderer, adapt, prism = load_modules()
    monitor_dir = Path(args.monitor_dir) if args.monitor_dir else renderer.MONITOR_DIR
    try:
        # 锁只串行本脚本，不锁住研究；研究归档变化在发布前另外核对。
        with (monitor_dir / ".prism-render.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return render(args, renderer, adapt, prism, monitor_dir)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"status=error error={error}", file=sys.stderr)
        return 1


def render(args, renderer, adapt, prism, monitor_dir: Path) -> int:
    analysis_date: date = renderer.resolve_date(monitor_dir, args.date)
    inputs = {}
    if args.action_date is not None:
        report, snapshot, inputs = load_completed_archives(
            renderer, monitor_dir, analysis_date, date.fromisoformat(args.action_date),
            checked_cutoff(args.as_of),
        )
    else:
        report, snapshot, _, _ = renderer.load_artifacts(monitor_dir, analysis_date)
    payload, revision_inputs = adopted_revision_payload(
        renderer, monitor_dir, analysis_date, report, snapshot,
    )
    inputs.update(revision_inputs)
    if payload is None:
        payload = renderer.build_payload(
            PROJECT_ROOT, monitor_dir, analysis_date, report, snapshot
        )
    codes = [c.strip() for c in args.indices.split(",") if c.strip()] if args.indices else list(adapt.DEFAULT_CODES)
    if not 3 <= len(codes) <= 5:
        raise ValueError("--indices must contain 3 to 5 codes")
    # 日期定位一律用完整 ISO sessionDates（E1）；无 sessionDates 的旧载荷走
    # web_display_contract 的受约束兼容转换，跨年无法证明年份时明确失败。
    session_isos = payload.get("sessionDates")
    sessions = [
        date.fromisoformat(value)
        for value in web_display_contract.resolve_session_dates(
            payload["dates"], payload["analysis_date"], session_isos
        )
    ]
    as_of = datetime.fromisoformat(payload["as_of"])
    market_rows = local_index_rows(renderer, PROJECT_ROOT, codes, sessions, as_of)
    display_snapshot = adapt.enrich_snapshot(
        payload, market_rows=market_rows or None, market_codes=codes
    )
    series = prism.assemble_series(PROJECT_ROOT, renderer, display_snapshot)
    html = prism.render_html(display_snapshot, series)
    if adapt.read_snapshot_text(html) != display_snapshot:
        raise ValueError("rendered HTML does not contain the expected snapshot")
    out_path = (
        Path(args.out)
        if args.out
        else monitor_dir / f"prism-a2-report-{analysis_date.isoformat()}.html"
    )
    fixed_path = monitor_dir / "style-preview" / "prism-a2.html"
    if out_path.resolve() == fixed_path.resolve():
        raise ValueError("--out must not target the fixed A2 entry; use the default dated output")
    for path in (out_path, out_path.resolve()):
        if (path.suffix != ".html" or path.name in ("prism.html", "index.html")
                or path.name.startswith(("prism-report-", "monitor-report-"))):
            raise ValueError("--out must be an HTML file outside retired/backup page paths")
    newer_fixed = False
    if not args.no_publish and fixed_path.exists():
        current = adapt.read_snapshot_text(fixed_path.read_text(encoding="utf-8"))
        newer_fixed = date.fromisoformat(current["analysis_date"]) > analysis_date
    if any(path.read_bytes() != content for path, content in inputs.items()):
        raise ValueError("formal archives changed during rendering; retry sync only")
    print("status=rendered" if write_html(out_path, html) else "status=unchanged")
    if not args.no_publish:
        if newer_fixed:
            print(f"published=skipped_newer {fixed_path}")
        elif write_html(fixed_path, html):
            print(f"published={fixed_path}")
        else:
            print(f"published=unchanged {fixed_path}")
    provided = [row for row in display_snapshot.get("marketIndices", []) if row.get("close") is not None]
    print(f"analysis_date={analysis_date.isoformat()}")
    print(f"html_file={out_path}")
    print(f"stock_count={len(payload['stocks'])}")
    attention = sum(1 for stock in payload["stocks"] if stock["attention"])
    print(f"attention_count={attention}")
    print(f"market_codes={','.join(codes)}")
    print(f"market_rows_loaded={len(market_rows)}")
    print(
        "market_fresh="
        + ",".join(f"{row['code']}:{'yes' if row.get('trade_date') == analysis_date.isoformat() and row.get('close') is not None else 'no'}" for row in display_snapshot.get("marketIndices", []))
    )
    print(f"market_provided={len(provided)}/{len(codes)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
