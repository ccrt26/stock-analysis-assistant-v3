"""A2 主用页面的纯渲染和冻结截止内价量补充。

正式更新统一运行 tools/render_prism_web.py。保留本文件命令入口，参数转交
同一同步命令；不再从停更备用 prism.html 提取数据，也不独立覆写主用页。
"""
from __future__ import annotations

import importlib.util
import json
import math
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CONCEPT_A = ROOT / "tools" / "guanlan-prism" / "concept-a"
A2_DIR = CONCEPT_A / "a2"
TEMPLATE = CONCEPT_A / "overview-a2-shell.html"
MARKERS = ("/*__DATA__*/", "/*__SERIES__*/", "/*__A2CSS__*/",
           "/*__MATH__*/", "/*__DATAACCESS__*/", "/*__CHARTS__*/", "/*__OVERVIEW__*/")
STOCK_SOURCE = "本地事实仓 equity_daily（available_at ≤ 报告 as_of）"
INDEX_SOURCE = "本地事实仓 index_daily（available_at ≤ 报告 as_of）"
THEME_SOURCE = "本地事实仓 theme_daily（available_at ≤ 报告 as_of）"
SERIES_SESSIONS = 80


def _load_monitor_module():
    """与 render_prism_web 相同的加载方式；仅用其日历/分区读取工具。"""
    tools_dir = str(ROOT / "tools")
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    try:
        from tools import render_monitor_web  # type: ignore[no-redef]
        return render_monitor_web
    except ImportError:
        spec = importlib.util.spec_from_file_location(
            "render_monitor_web", ROOT / "tools" / "render_monitor_web.py")
        if spec is None or spec.loader is None:
            raise ValueError("找不到 tools/render_monitor_web.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


def _number(value):
    if value is None or (isinstance(value, float) and value != value):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _read_day(root, rmw, table: str, day: date, cutoff, key: str | None = None):
    frame = rmw._read_day_frames(root, table, day, cutoff)
    if frame is None:
        return {}
    if key is None:
        key = "ts_code" if table == "equity_daily" else "index_code"
    rows = {}
    for _, row in frame.iterrows():
        rows[str(row[key])] = row
    return rows


def assemble_series(root: Path, rmw, snapshot: dict) -> dict:
    """最近 N 个交易日（≤ 报告日）的个股/指数日线；单位：股、元、点位。"""
    analysis = date.fromisoformat(snapshot["analysis_date"])
    as_of = datetime.fromisoformat(snapshot["as_of"])
    cutoff = rmw._as_utc_cutoff(as_of)
    sessions = rmw.list_sessions(root, analysis - timedelta(days=200), analysis)[-SERIES_SESSIONS:]
    codes = list(dict.fromkeys(str(s["code"]) for s in snapshot.get("stocks", [])))
    index_codes = list((snapshot.get("presentation") or {}).get("marketCodes") or [])

    def bar_row(row) -> dict:
        return {"date": None, "open": _number(row.get("open")), "high": _number(row.get("high")),
                "low": _number(row.get("low")), "close": _number(row.get("close")),
                "volumeShares": _number(row.get("volume")), "amountYuan": _number(row.get("amount"))}

    stocks = {code: {"priceBasis": "raw_unadjusted", "source": STOCK_SOURCE, "rows": [], "industry": []}
              for code in codes}
    indices = {code: {"source": INDEX_SOURCE, "rows": []} for code in index_codes}
    for day in sessions:
        iso = day.isoformat()
        equity = _read_day(root, rmw, "equity_daily", day, cutoff)
        for code in codes:
            row = equity.get(code)
            if row is None:
                continue
            item = bar_row(row)
            if item["close"] is None and item["open"] is None:
                continue
            item["date"] = iso
            stocks[code]["rows"].append(item)
        if index_codes:
            index_frame = _read_day(root, rmw, "index_daily", day, cutoff)
            for code in index_codes:
                row = index_frame.get(code)
                if row is None:
                    continue
                item = bar_row(row)
                if item["close"] is None and item["open"] is None:
                    continue
                item["date"] = iso
                indices[code]["rows"].append(item)
    # 主题指数对照（如中证传媒 399971.SZ）：仅当展示记录携带 industryCode 且该
    # 代码不属于申万目录时读取 theme_daily 官方收盘；同主题一次读取多处共享。
    comparison_codes = sorted(
        {str(s["industryCode"]) for s in snapshot.get("stocks", []) if s.get("industryCode")}
    )
    comparisons: dict = {}
    theme_needed: list[str] = []
    if comparison_codes:
        catalog_codes = set(rmw.industry_catalog_names(root).keys())
        theme_needed = [code for code in comparison_codes if code not in catalog_codes]
    if theme_needed:
        for day in sessions:
            iso = day.isoformat()
            theme = _read_day(root, rmw, "theme_daily", day, cutoff, key="theme_code")
            for code in theme_needed:
                row = theme.get(code)
                if row is None:
                    continue
                close = _number(row.get("close"))
                if close is None or close <= 0:
                    continue
                comparisons.setdefault(
                    code, {"source": THEME_SOURCE, "rows": []})["rows"].append(
                    {"date": iso, "close": close})
    series = {"schemaVersion": 1, "analysis_date": analysis.isoformat(),
              "sessionDates": [d.isoformat() for d in sessions],
              "stocks": stocks, "indices": indices}
    if comparisons:
        series["comparisons"] = comparisons
    check_series_against_snapshot(snapshot, series)
    return series


def check_series_against_snapshot(snapshot: dict, series: dict) -> None:
    """同股同日补充收盘与冻结值冲突时明确报错，不静默取用。"""
    analysis = snapshot["analysis_date"]
    if series.get("analysis_date") != analysis:
        raise ValueError(f"侧表 analysis_date {series.get('analysis_date')!r} 与快照 {analysis!r} 不一致")
    sessions = series.get("sessionDates") or []
    if (not sessions or sessions != sorted(set(sessions)) or sessions[-1] != analysis):
        raise ValueError("侧表 sessionDates 必须严格递增且末日等于报告日")
    if series.get("schemaVersion") != 1:
        raise ValueError("侧表 schemaVersion 必须为 1")
    conflicts = []
    for stock in snapshot.get("stocks", []):
        addition = (series.get("stocks") or {}).get(stock["code"]) or {}
        if addition.get("priceBasis") not in (None, "raw_unadjusted"):
            raise ValueError(f"{stock['code']} 侧表 priceBasis 必须为 raw_unadjusted")
        by_date = {r.get("date"): r for r in addition.get("rows", []) if r.get("date")}
        for i, iso in enumerate(snapshot.get("sessionDates", [])):
            row = by_date.get(iso)
            if not row:
                continue
            candle = (stock.get("candles") or [None] * len(snapshot["sessionDates"]))[i]
            frozen_close = candle[3] if isinstance(candle, list) and len(candle) > 3 else None
            if (isinstance(frozen_close, (int, float)) and isinstance(row.get("close"), (int, float))
                    and abs(float(frozen_close) - float(row["close"])) > 0.005):
                conflicts.append(f"{stock['code']} {iso} 补充收盘 {row['close']} 与冻结 {frozen_close} 不一致")
    for index in snapshot.get("marketIndices", []):
        by_date = {r.get("date"): r for r in
                   (series.get("indices", {}).get(index["code"], {}).get("rows") or [])}
        frozen = dict(zip(snapshot.get("sessionDates", []), index.get("series", [])))
        if index.get("trade_date"):
            frozen[index["trade_date"]] = index.get("close")
        for iso, close in frozen.items():
            extra_close = by_date.get(iso, {}).get("close")
            if (isinstance(close, (int, float)) and isinstance(extra_close, (int, float))
                    and abs(float(close) - float(extra_close)) > 0.005):
                conflicts.append(f"{index['code']} {iso} 指数补充收盘 {extra_close} 与冻结 {close} 不一致")
    for code, entry in (series.get("comparisons") or {}).items():
        by_date = {r.get("date"): r.get("close") for r in entry.get("rows", []) if r.get("date")}
        for stock in snapshot.get("stocks", []):
            if stock.get("industryCode") != code:
                continue
            ind = stock.get("industry") or []
            for i, iso in enumerate(stock.get("sessionDates") or snapshot.get("sessionDates", [])):
                frozen = ind[i] if isinstance(ind, list) and i < len(ind) else None
                extra_close = by_date.get(iso)
                if (isinstance(frozen, (int, float)) and isinstance(extra_close, (int, float))
                        and abs(float(frozen) - float(extra_close)) > 0.005):
                    conflicts.append(
                        f"{code} {iso} 主题对照补充收盘 {extra_close} 与冻结 {frozen} 不一致")
    if conflicts:
        raise ValueError("侧表与冻结快照冲突：" + "；".join(conflicts[:5]))


def render_html(snapshot: dict, series: dict | None = None) -> str:
    sessions = snapshot.get("sessionDates")
    if (not isinstance(sessions, list) or not sessions
            or sessions != sorted(set(sessions))
            or any(not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d) for d in sessions)
            or sessions[-1] != snapshot.get("analysis_date")):
        raise ValueError("A2 需要严格递增、末日为报告日的完整 ISO 交易日历")
    if (len(snapshot.get("dates", [])) != len(sessions)
            or len(snapshot.get("market", [])) != len(sessions)
            or not isinstance(snapshot.get("stocks"), list)):
        raise ValueError("A2 快照数组与交易日历不一致")
    if series is not None:
        check_series_against_snapshot(snapshot, series)
    template = TEMPLATE.read_text(encoding="utf-8")
    for marker in MARKERS:
        if template.count(marker) != 1:
            raise ValueError(f"模板应恰好包含一个 {marker} 占位符")
    payload = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"),
                         allow_nan=False).replace("<", "\\u003c")
    series_payload = (json.dumps(series, ensure_ascii=False, separators=(",", ":"),
                                 allow_nan=False).replace("<", "\\u003c") if series is not None else "null")
    replacements = {
        "/*__DATA__*/": payload,
        "/*__SERIES__*/": series_payload,
        "/*__A2CSS__*/": (A2_DIR / "preview.css").read_text(encoding="utf-8"),
        "/*__MATH__*/": (A2_DIR / "display-math.js").read_text(encoding="utf-8"),
        "/*__DATAACCESS__*/": (A2_DIR / "data-access.js").read_text(encoding="utf-8"),
        "/*__CHARTS__*/": (A2_DIR / "charts.js").read_text(encoding="utf-8"),
        "/*__OVERVIEW__*/": (A2_DIR / "overview.js").read_text(encoding="utf-8"),
    }
    # 只扫描原始模板一次，正文中相同标记按原文保留。
    pattern = re.compile("(" + "|".join(re.escape(marker) for marker in MARKERS) + ")")
    return "".join(replacements.get(chunk, chunk) for chunk in pattern.split(template))


def main(argv: list[str] | None = None) -> int:
    sys.path.insert(0, str(ROOT / "tools"))
    from render_prism_web import main as sync_main
    return sync_main(argv)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"status=error error={error}", file=sys.stderr)
        sys.exit(1)
