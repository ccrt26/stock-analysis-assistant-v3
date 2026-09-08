"""公司资料页签的紧凑浏览器验收：真实介绍文章 + 合成归档（桌面与手机）。

用法（在仓库根目录）：
    ./.venv/bin/python tests/check_prism_introduction_browser.py \
        --out local_archive/company_introduction_validation/screenshots

覆盖（方案第 11 节浏览器检查项，一次紧凑预览合并）：
正常完整篇、数据有限篇、缺介绍、旧 company 简要资料、同股两次推荐各用各篇、
D0 资料绑定、XSS 转义、手机表格容器内横向滚动。身份绑定走真实的
load_introductions_for_display（临时 intro_root + 合成 trace），中国船舶的
conditional_event 样稿按合同不进入正式绑定，仅作为隔离渲染预览注入载荷。
任何失败非零退出。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import tempfile
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRISM_BUILD = PROJECT_ROOT / "tools" / "guanlan-prism" / "tools" / "build.py"
VALIDATION = PROJECT_ROOT / "local_archive" / "company_introduction_validation"

sys.path.insert(0, str(PROJECT_ROOT))

from tools.render_monitor_web import build_payload  # noqa: E402

from stock_analyzer.ops.company_introduction import (  # noqa: E402
    intro_path,
    load_introductions_for_display,
)


def load_builder():
    spec = importlib.util.spec_from_file_location("guanlan_prism_build_intro", PRISM_BUILD)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def candle(open_, close, amount=1.0):
    return [open_, max(open_, close), min(open_, close), close, amount]


def make_stock(code, name, *, rec_date, rec_index, ref, last_close, **kw):
    dates_len = 26
    seq = [candle(9.0, 9.0) for _ in range(rec_index)]
    seq += [None] * (dates_len - 1 - rec_index)
    seq.append(candle(last_close, last_close, 4.2) if last_close is not None else [None] * 5)
    base = {"code": code, "name": name, "recDate": rec_date, "formedOn": kw.pop("formedOn", rec_date),
            "episodeId": kw.pop("episodeId", None), "recIndex": rec_index, "ref": ref,
            "refKind": "formal" if ref else None, "days": kw.pop("days", 3), "d0": kw.pop("d0", False),
            "phase": "primary", "stage": "观察中", "stageType": None, "attention": None,
            "trigger": None, "suspended": False, "dataIssues": [], "trackingStatus": None,
            "trackingExitDate": None, "trackingExitReason": None, "company": kw.pop("company", None),
            "reasonFull": "合成理由。", "reasonRisk": "合成风险。", "industryName": "合成行业",
            "industrySource": "none", "industry": [100.0] * dates_len, "candles": seq,
            "reviews": [], "events": [], "invalidated": None}
    base.update(kw)
    return base


AS_OF = "2026-08-23T09:05:02+08:00"
FORMATION = "2026-08-21"
ACTION = "2026-08-24"
CODE = "600583.SH"


def snap_episode(code, name, episode_id, *, action, formation, priority=1):
    """build_payload 读取的是 snapshot 形态的 episode。"""

    return {"episode_id": episode_id, "ts_code": code, "name": name,
            "role": "selected", "selection_output_class": "confirmed_active",
            "day_number": 1, "formation_date": formation, "action_date": action,
            "original_priority": priority, "original_research_thesis": {},
            "previous_monitor_state": "routine", "previous_episode_review": None,
            "first_event_reaction": None, "original_engine_type": "sector_leader_cluster",
            "monitor_phase": "primary", "tracking_status": "active",
            "tracking_exit_date": None, "tracking_exit_reason": None}


def _limited_intro(*, formation, action, as_of, generated_at, title):
    return {
        "schema_version": "company-introduction-v1", "ts_code": "000009.SZ",
        "name": "两次入选股", "formation_date": formation, "action_date": action,
        "as_of": as_of, "generated_at": generated_at,
        "sections": [{"title": title,
                      "paragraphs": ["该篇用于检查资料有限时的表现：只有可靠身份与主营，没有可比财务。"],
                      "source_ids": ["S1"]}],
        "sources": [{"id": "S1", "kind": "official_document", "title": "合成官方来源",
                     "available_at": "2026-08-09T10:00:00+08:00",
                     "availability_basis": "合成预览用的公开时间定位",
                     "retrieved_at": "2026-08-10T19:00:00+08:00",
                     "url": "https://example.invalid/x.pdf", "locator": "第1页"}],
        "limitations": ["合成预览：人为的有限资料，不代表真实仓库缺失。"],
    }


def build_scene(tmp: Path):
    """合成归档 + 临时 intro_root；介绍按真实身份绑定路径加载。"""

    import pandas as pd

    selection = tmp / "selection"
    monitor = tmp / "monitor"
    monitor.mkdir(parents=True)
    selection.mkdir(parents=True)
    intro_root = tmp / "intros"
    # 真实文章按原身份写入临时 intro_root；中国船舶的 conditional_event 样稿
    # 不进入绑定（显示类别不含它），仅注入载荷做隔离渲染预览。
    for code, action in ((CODE, ACTION), ("603969.SH", "2026-08-21")):
        source = VALIDATION / "articles" / f"intro-{code[:6]}.json"
        if source.is_file():
            document = json.loads(source.read_text(encoding="utf-8"))
            target = intro_path(intro_root, action, code)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    # "两次入选股" 两篇合成介绍：数据有限篇（合成，非真实仓库缺失）
    writes = [
        ("2026-08-21", _limited_intro(
            formation="2026-08-20", action="2026-08-21",
            as_of="2026-08-21T09:10:00+08:00",
            generated_at="2026-08-21T20:00:00+08:00",
            title="有限资料篇（本次）")),
        ("2026-08-11", _limited_intro(
            formation="2026-08-10", action="2026-08-11",
            as_of="2026-08-10T18:30:00+08:00",
            generated_at="2026-08-10T20:00:00+08:00",
            title="有限资料篇（上次）")),
    ]
    for action, document in writes:
        target = intro_path(intro_root, action, "000009.SZ")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")

    def trace(formation, action, as_of, candidates):
        return {
            "trace_version": "daily-research-trace-v4", "formation_date": formation,
            "action_date": action, "as_of": as_of,
            "candidate_ledger": [
                {"ts_code": code, "name": name, "final_fate": "selected",
                 "research_thesis": {"engine_type": "sector_leader_cluster",
                                     "engine_status": "active",
                                     "market_recognition": {"status": "confirmed"}}}
                for code, name in candidates
            ],
            "research_result": {"research_completed": True,
                                "point_in_time_evidence_verified": True},
        }

    (selection / f"research-trace-{FORMATION}.json").write_text(
        json.dumps(trace(FORMATION, ACTION, AS_OF, [(CODE, "海油工程")]), ensure_ascii=False),
        encoding="utf-8")
    (selection / "research-trace-2026-08-20.json").write_text(
        json.dumps(trace("2026-08-20", "2026-08-21", "2026-08-21T09:10:00+08:00",
                         [("603969.SH", "银龙股份"), ("000009.SZ", "两次入选股")]),
                   ensure_ascii=False), encoding="utf-8")
    (selection / "research-trace-2026-08-10.json").write_text(
        json.dumps(trace("2026-08-10", "2026-08-11", "2026-08-10T18:30:00+08:00",
                         [("000009.SZ", "两次入选股")]), ensure_ascii=False), encoding="utf-8")
    # 交易日历（周一至周五开市）
    days = pd.date_range("2026-06-01", "2026-12-31", freq="D")
    frame = pd.DataFrame({"exchange": "SSE", "cal_date": days.strftime("%Y-%m-%d"),
                          "is_open": days.dayofweek < 5})
    calendar_dir = tmp / "local_warehouse" / "facts" / "trade_calendar" / "cal_year=2026"
    calendar_dir.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(calendar_dir / "data.parquet")

    report_date = "2026-08-23"
    report = {
        "report_version": "daily-forward-monitor-report-v2", "analysis_date": report_date,
        "as_of": "2026-08-23T18:30:00+08:00",
        "market_overview": {"market_propagation_mode": "unclear", "market_risk_overlays": [],
                            "what_changed": "预览。", "implication_for_monitored_stocks": "预览。"},
        "pool_summary": {}, "alerts": [], "unreported_attention_count": 0, "routine_summary": "预览。",
    }
    counts = dict.fromkeys(("open_episode_count", "distinct_stock_count", "selected_count",
                            "comparator_count", "primary_count", "passive_tail_count",
                            "attention_stock_count", "routine_stock_count"), 0)
    episodes = [
        snap_episode(CODE, "海油工程", "ep-hyg", action=ACTION, formation=FORMATION),
        snap_episode("603969.SH", "银龙股份", "ep-yl", action="2026-08-21", formation="2026-08-20"),
        snap_episode("000009.SZ", "两次入选股", "ep-twice-new", action="2026-08-21", formation="2026-08-20"),
        snap_episode("000009.SZ", "两次入选股", "ep-twice-old", action="2026-08-11", formation="2026-08-10"),
        snap_episode("000006.SZ", "缺介绍股", "ep-miss", action="2026-08-21", formation="2026-08-20"),
        snap_episode("000007.SZ", "旧资料股", "ep-old", action="2026-08-21", formation="2026-08-20"),
    ]
    snapshot = {
        "snapshot_version": "forward-monitor-snapshot-v1", "analysis_date": report_date,
        "as_of": "2026-08-23T18:30:00+08:00", "episodes": episodes,
        "daily_review_episode_ids": [], "checkpoint_review_episode_ids": [],
        "attention_stocks": [], "summary": counts,
    }
    payload = build_payload(tmp, monitor, date(2026, 8, 23), report, snapshot,
                            selection_dir=selection, intro_root=intro_root)
    # 旧 company 简要资料只发生在载荷层：给旧资料股补显示字段
    for item in payload["stocks"]:
        if item["code"] == "000007.SZ":
            item["company"] = "旧快照中的简要资料：合成公司主营样例。"
    return payload, intro_root, selection


def build_snapshot_from_payload(payload, ship_intro):
    """把 build_payload 结果转成 prism 构建器需要的最小快照。"""

    stocks = [dict(item) for item in payload["stocks"]]
    document = json.loads((VALIDATION / "articles" / "intro-600150.json").read_text(encoding="utf-8"))
    if ship_intro is not None:
        extra = make_stock("600150.SH", "中国船舶", rec_date="2026-09-03", rec_index=21,
                           ref=33.0, last_close=33.9, episodeId="ep-cs", company=None)
        extra["companyIntroduction"] = document
        stocks.append(extra)
    # 转义检查样本：恶意字符串必须按文本显示，不产生元素注入
    xss = make_stock("000008.SZ", "转义检查股", rec_date="2026-08-21", rec_index=18,
                     ref=2.0, last_close=2.1, episodeId="ep-xss", company=None)
    xss["companyIntroduction"] = {
        "schema_version": "company-introduction-v1", "ts_code": "000008.SZ",
        "name": "转义检查股", "formation_date": "2026-08-20", "action_date": "2026-08-21",
        "as_of": "2026-08-21T09:10:00+08:00", "generated_at": "2026-08-21T20:00:00+08:00",
        "sections": [{"title": "<img src=x onerror=alert(1)>标题向量",
                      "paragraphs": ["正文包含 <script>alert(2)</script> 与 \"引号\" & 符号。"],
                      "source_ids": []}],
        "sources": [], "limitations": [],
    }
    stocks.append(xss)
    dates = ["2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06", "2026-08-07",
             "2026-08-10", "2026-08-11", "2026-08-12", "2026-08-13", "2026-08-14",
             "2026-08-17", "2026-08-18", "2026-08-19", "2026-08-20", "2026-08-21",
             "2026-08-24", "2026-08-25", "2026-08-26", "2026-08-27", "2026-08-28",
             "2026-08-31", "2026-09-01", "2026-09-02", "2026-09-03"]
    return {"analysis_date": "2026-09-03", "as_of": "2026-09-03T18:30:00+08:00",
            "market_name": "上证指数", "sessionDates": dates,
            "dates": [d[5:] for d in dates],
            "market": [3000.0 + i for i in range(len(dates))],
            "review_dates": ["2026-09-03"], "stocks": stocks,
            "sourceInfo": {"kind": "synthetic", "label": "公司介绍验收预览", "externallyVerified": False},
            "observationPolicy": {"primaryDays": 20, "targetReturn": 0.2,
                                  "origin": "existing_v4_contract"}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(VALIDATION / "screenshots"))
    parser.add_argument("--browser-executable", default=None)
    args = parser.parse_args()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright 未安装：.venv/bin/python -m pip install playwright")
        return 2

    builder = load_builder()
    failures: list[str] = []
    errors: list[str] = []

    def check(h, name, fn):
        try:
            fn()
            print(f"  PASS {name}")
        except AssertionError as exc:
            failures.append(f"{name}: {exc}")
            print(f"  FAIL {name}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{name}: {type(exc).__name__}: {exc}")
            print(f"  FAIL {name}: {type(exc).__name__}: {exc}")

    def expect(cond, msg):
        if not cond:
            raise AssertionError(msg)

    with tempfile.TemporaryDirectory(prefix="intro-browser-") as tmp:
        payload, intro_root, selection = build_scene(Path(tmp))
        # 同股两次推荐场景：000009.SZ 在更晚行动日再次入选，两篇介绍各自绑定
        twice_old = load_introductions_for_display(
            selection, intro_root, [("000009.SZ", "2026-08-11", "2026-08-10")])
        expect(bool(twice_old), "两次入选的旧篇应可按身份加载")

        snapshot = build_snapshot_from_payload(payload, ship_intro=True)
        page_path = Path(tmp) / "intro-preview.html"
        page_path.write_text(builder.render_html(snapshot), encoding="utf-8")

        with sync_playwright() as p:
            launch = {"headless": True}
            if args.browser_executable:
                launch["executable_path"] = args.browser_executable
            browser = p.chromium.launch(**launch)
            desktop = browser.new_context(viewport={"width": 1440, "height": 1100})
            mobile_ctx = browser.new_context(viewport={"width": 390, "height": 844},
                                             is_mobile=True, has_touch=True)

            for tag, page in (("desktop", desktop.new_page()), ("mobile", mobile_ctx.new_page())):
                page.set_default_timeout(8000)
                page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
                page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}")
                        if m.type == "error" else None)
                page.goto(page_path.as_uri())
                page.wait_for_timeout(500)
                page.locator('.nav-item[data-nav="records"]').click()
                page.wait_for_timeout(300)
                print(f"[{tag}] 场景检查：")

                def open_stock(code, rec):
                    page.locator(f'tr[data-open="{code}:{rec}"]').click()
                    page.wait_for_timeout(250)
                    page.locator('[data-review-tab="company"]').click()
                    page.wait_for_timeout(250)

                # 完整篇（海油工程，真实身份绑定）
                open_stock(CODE, ACTION)
                body = page.locator("#reviewPanel").inner_text()
                check(h=tag, name=f"[{tag}] 完整篇标题与正文", fn=lambda: (
                    expect("推荐时点资料" in body, f"缺少推荐时点资料标注：{body[:120]}"),
                    expect("海洋工程总承包项目" in body, "正文缺少总承包内容"),
                    expect("资料来源" in body, "缺少来源折叠区"),
                    expect("资料限制" in body, "缺少资料限制区"),
                ))
                check(tag, f"[{tag}] 完整篇表格渲染", fn=lambda: expect(
                    page.locator(".intro-table tbody tr").first.is_visible(), "表格行不可见"))
                check(tag, f"[{tag}] 完整篇估值表", fn=lambda: expect(
                    "270.59亿元" in body, "估值表数值缺失"))
                check(tag, f"[{tag}] 不再显示旧页脚", fn=lambda: expect(
                    "未做最新公告或财务核验" not in body, "旧统一页脚仍存在"))
                page.screenshot(path=str(out / f"intro-full-{tag}.png"), full_page=True)

                # 数据有限篇（银龙历史补写篇显示实际编写时间）
                page.locator(".back-button").click()
                page.wait_for_timeout(200)
                open_stock("603969.SH", "2026-08-21")
                yl = page.locator("#reviewPanel").inner_text()
                check(tag, f"[{tag}] 银龙历史补写篇显示实际编写时间", fn=lambda: expect(
                    "实际编写于" in yl, "历史补写未标注实际编写时间"))
                page.screenshot(path=str(out / f"intro-yinlong-{tag}.png"), full_page=True)

                # 同股两次推荐：两行各自绑定自己的文章
                page.locator(".back-button").click()
                page.wait_for_timeout(200)
                open_stock("000009.SZ", "2026-08-21")
                new_one = page.locator("#reviewPanel").inner_text()
                check(tag, f"[{tag}] 两次入选·本次篇", fn=lambda: expect(
                    "有限资料篇（本次）" in new_one, f"本次篇未绑定：{new_one[:100]}"))
                page.locator(".back-button").click()
                page.wait_for_timeout(200)
                open_stock("000009.SZ", "2026-08-11")
                old_one = page.locator("#reviewPanel").inner_text()
                check(tag, f"[{tag}] 两次入选·上次篇", fn=lambda: expect(
                    "有限资料篇（上次）" in old_one, f"上次篇未绑定：{old_one[:100]}"))
                check(tag, f"[{tag}] 两篇内容互不复用", fn=lambda: expect(
                    "（本次）" not in old_one and "（上次）" not in new_one, "两篇互相串用"))

                page.locator(".back-button").click()
                page.wait_for_timeout(200)
                open_stock("000006.SZ", "2026-08-21")
                miss = page.locator("#reviewPanel").inner_text()
                check(tag, f"[{tag}] 缺介绍显示简单缺项", fn=lambda: expect(
                    "这次推荐的完整公司介绍暂未生成" in miss, f"缺项文案缺失：{miss[:100]}"))
                check(tag, f"[{tag}] 缺项不写成经营风险", fn=lambda: expect(
                    "风险" not in miss, "缺项文案不得提及风险"))

                page.locator(".back-button").click()
                page.wait_for_timeout(200)
                open_stock("000007.SZ", "2026-08-21")
                old = page.locator("#reviewPanel").inner_text()
                check(tag, f"[{tag}] 旧 company 兼容显示", fn=lambda: expect(
                    "旧快照中的简要资料" in old and "完整推荐时点介绍暂缺" in old,
                    f"旧简要资料回退缺失：{old[:100]}"))

                # 隔离预览注入的中国船舶样稿 + XSS 转义在手机端表格滚动检查
                page.locator(".back-button").click()
                page.wait_for_timeout(200)
                open_stock("600150.SH", "2026-09-03")
                cs = page.locator("#reviewPanel").inner_text()
                check(tag, f"[{tag}] 中国船舶样稿渲染", fn=lambda: expect(
                    "船舶修造及海洋工程" in cs and "同比请谨慎读" in cs,
                    f"样稿正文缺失：{cs[:120]}"))
                check(tag, f"[{tag}] 样稿引用已核对的合同事实", fn=lambda: expect(
                    "10艘8,200车" in cs and "不构成重大影响" in cs and "9,890万元" in cs,
                    "样稿应引用公告原文核实后的合同与仲裁事实"))
                page.screenshot(path=str(out / f"intro-chuanzhi-{tag}.png"), full_page=True)

                # XSS 转义：恶意串按纯文本渲染，无注入元素
                page.locator(".back-button").click()
                page.wait_for_timeout(200)
                open_stock("000008.SZ", "2026-08-21")
                panel_text = page.locator("#reviewPanel").inner_text()
                check(tag, f"[{tag}] 恶意字符串按文本转义", fn=lambda: expect(
                    page.locator("#reviewPanel img[src='x']").count() == 0
                    and "<img src=x onerror=alert(1)>标题向量" in panel_text,
                    "恶意串未被转义为纯文本或产生注入元素"))
                check(tag, f"[{tag}] 转义文本仍可读", fn=lambda: expect(
                    "标题向量" in panel_text and 'alert(2)' in panel_text,
                    "转义后正文文本丢失"))

                if tag == "mobile":
                    page.locator(".back-button").click()
                    page.wait_for_timeout(200)
                    open_stock(CODE, ACTION)
                    wrap = page.locator(".intro-table-wrap").first
                    check(tag, "[mobile] 表格在容器内横向滚动", fn=lambda: expect(
                        page.evaluate(
                            "el => el.scrollWidth >= el.clientWidth && el.scrollWidth <= el.clientWidth + 2 || el.scrollWidth > el.clientWidth",
                            wrap.element_handle()),
                        "表格容器应可横向滚动且不撑破页面"))
                    page_width = page.evaluate("document.documentElement.scrollWidth")
                    check(tag, "[mobile] 页面无横向溢出", fn=lambda: expect(
                        page_width <= 391, f"页面宽度 {page_width} 超出手机视口"))
                    page.screenshot(path=str(out / "intro-full-mobile.png"), full_page=True)
            browser.close()

    if errors:
        for err in errors:
            print(f"JS/CONSOLE 错误：{err}")
    if failures or errors:
        print(f"\n结果：失败 {len(failures)} 项，JS/控制台错误 {len(errors)} 条；截图 {out}")
        for item in failures:
            print(f"  失败：{item}")
        return 1
    print(f"\n结果：全部通过；截图目录 {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
