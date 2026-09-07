"""把已冻结的每日走势复盘渲染成「观澜 · 光场 PRISM V3」展示页面。

复用 tools/render_monitor_web.build_payload 输出的同一份数据（字段合同见
tools/guanlan-prism/docs/03-数据接口与口径.md），并做两处展示层附加：
1. marketIndices：从本地事实仓 index_daily 读取已配置指数的日线（含前收），
   只取 trade_date ≤ analysis_date 且 available_at ≤ 报告 as_of 的事实；
   本地没有的指数保持缺失，不由展示层补数。
2. presentation：默认四个市场代码与 deepLimit=8（可用 --indices 调整三至五项）。

当日普通详评名单直接由页面规则从 regular_detail 标记推导（上游无显式排序
名单时不编造 dailyDeepReview）。不修改选股、复盘、V4 渲染器或定时任务。

输出两个文件：
1. prism-report-<date>.html —— 按日期留档，历史可回看；
2. prism.html —— 固定地址，内容不变时原子跳过，永远等于最新已渲染日报。
用户只需记住固定地址 prism.html。

用法：
    ./.venv/bin/python tools/render_prism_web.py                  # 最新一个 snapshot
    ./.venv/bin/python tools/render_prism_web.py --date 2026-09-02
    ./.venv/bin/python tools/render_prism_web.py --out 任意路径.html
    ./.venv/bin/python tools/render_prism_web.py --indices 000001.SH,399001.SZ
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
from datetime import date, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRISM_ROOT = PROJECT_ROOT / "tools" / "guanlan-prism"
MARKET_SOURCE = "本地事实仓 index_daily（available_at ≤ 报告 as_of）"


def load_modules():
    """与 tests/update_monitor_web 复用同一 render_monitor_web 模块实例。"""
    sys.path.insert(0, str(PROJECT_ROOT / "tools"))
    try:
        from tools import render_monitor_web
    except ImportError:  # 直接以脚本方式运行（python tools/render_prism_web.py）
        import render_monitor_web  # type: ignore[no-redef]

    modules = {}
    for name in ("build", "adapt_snapshot"):
        spec = importlib.util.spec_from_file_location(
            f"guanlan_prism_{name}", PRISM_ROOT / "tools" / f"{name}.py"
        )
        if spec is None or spec.loader is None:
            raise FileNotFoundError(f"missing PRISM module at {PRISM_ROOT / 'tools' / name}.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        modules[name] = module
    return render_monitor_web, modules["adapt_snapshot"], modules["build"]


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Render the frozen daily monitor review as the PRISM V3 display page"
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
    parser.add_argument(
        "--indices",
        default=None,
        help="comma-separated market codes (3-5), default 000001.SH,399001.SZ,399006.SZ,000688.SH",
    )
    parser.add_argument(
        "--no-publish",
        action="store_true",
        help="skip publishing the fixed prism.html entry (dated file is still written)",
    )
    args = parser.parse_args(argv)

    renderer, adapt, prism = load_modules()
    monitor_dir = Path(args.monitor_dir) if args.monitor_dir else renderer.MONITOR_DIR
    analysis_date: date = renderer.resolve_date(monitor_dir, args.date)
    report, snapshot, _report_path, _snapshot_path = renderer.load_artifacts(
        monitor_dir, analysis_date
    )
    payload = renderer.build_payload(
        PROJECT_ROOT, monitor_dir, analysis_date, report, snapshot
    )
    codes = [c.strip() for c in args.indices.split(",") if c.strip()] if args.indices else list(adapt.DEFAULT_CODES)
    if not 3 <= len(codes) <= 5:
        parser.error("--indices must contain 3 to 5 codes")
    year = payload["analysis_date"][:4]
    sessions = [date.fromisoformat(f"{year}-{d}") for d in payload["dates"]]
    as_of = datetime.fromisoformat(payload["as_of"])
    market_rows = local_index_rows(renderer, PROJECT_ROOT, codes, sessions, as_of)
    display_snapshot = adapt.enrich_snapshot(
        payload, market_rows=market_rows or None, market_codes=codes
    )
    html = prism.render_html(display_snapshot)
    out_path = (
        Path(args.out)
        if args.out
        else monitor_dir / f"prism-report-{analysis_date.isoformat()}.html"
    )
    # 幂等：同一输入重复运行不重写留档文件，也不触碰固定地址的修改时间。
    if out_path.exists() and out_path.read_text(encoding="utf-8") == html:
        print("status=unchanged")
    else:
        out_path.write_text(html, encoding="utf-8")
        print("status=rendered")
    if not args.no_publish:
        # 固定地址：原子替换，永远等于最新已渲染日报；失败不破坏旧页面。
        fixed_path = monitor_dir / "prism.html"
        if not fixed_path.exists() or fixed_path.read_text(encoding="utf-8") != html:
            tmp_path = fixed_path.with_name(f"{fixed_path.name}.tmp-{os.getpid()}")
            tmp_path.write_text(html, encoding="utf-8")
            os.replace(tmp_path, fixed_path)
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
