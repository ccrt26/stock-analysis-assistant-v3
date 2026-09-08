"""观察星图同股合并的浏览器验收：真实报告页 + 合成数据页，含截图。

用法（在仓库根目录）：
    ./.venv/bin/python tests/check_prism_atlas_browser.py \
        --html local_archive/forward_monitor/prism-report-2026-09-07.html \
        --out /tmp/prism-atlas-screenshots

脚本会额外用 tools/guanlan-prism/tools/build.py 渲染两份合成页面
（重复身份/缺数据/极端收益 与 空列表）一并检查。任何断言失败、
页面 JS 错误或控制台错误都以非零码退出；依赖缺失不静默跳过。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRISM_BUILD = PROJECT_ROOT / "tools" / "guanlan-prism" / "tools" / "build.py"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

DATES = ["08-03", "08-04", "08-05", "08-06", "08-07", "08-10", "08-11", "08-12",
         "08-13", "08-14", "08-17", "08-18", "08-19", "08-20", "08-21", "08-24",
         "08-25", "08-26", "08-27", "08-28", "08-31", "09-01", "09-02", "09-03",
         "09-04", "09-07"]


def candle(open_, close, amount=1.0):
    return [open_, max(open_, close), min(open_, close), close, amount]


def base_stock(**kw):
    base = {"refKind": "normal", "d0": None, "invalidated": None, "reviews": [],
            "events": [], "industry": [], "industryName": "合成行业",
            "industrySource": "合成", "company": "合成资料", "stage": "观察中",
            "stageType": None, "attention": None, "trigger": None,
            "suspended": False, "reasonFull": "合成观察记录，仅用于验收。",
            "reasonRisk": "合成风险提示。", "phase": None}
    base.update(kw)
    return base


def synth_snapshot(stocks):
    for s in stocks:
        if "candles" not in s:
            rec = s.get("recIndex", 0)
            seq = [candle(9.0, 9.0) for _ in range(rec)]
            seq += [None] * (len(DATES) - 1 - rec)
            close = s.pop("last_close", 10.0)
            seq.append(candle(close, close, 4.2))
            s["candles"] = seq
    return {"analysis_date": "2026-09-07", "as_of": "2026-09-07T18:30:00+08:00",
            "market_name": "上证指数", "dates": DATES,
            "market": [3000.0 + i for i in range(len(DATES))],
            "review_dates": ["2026-09-07"], "stocks": stocks}


def synth_main():
    """重复身份、缺数据、状态独立、事件混合与 -35%/+45% 极端收益。"""
    def two(code, name, early_date, early_ref, late_date, late_ref, close, **kw):
        early = base_stock(code=code, name=name, recDate=early_date, ref=early_ref,
                           recIndex=21, days=5, last_close=close, **kw)
        late = base_stock(code=code, name=name, recDate=late_date, ref=late_ref,
                          recIndex=23, days=3, last_close=close, **kw)
        return early, late

    a1, a2 = two("000001.SZ", "甲一", "2026-09-01", 100.0, "2026-09-03", 80.0, 84.0)
    dup = json.loads(json.dumps(a1))  # 同一身份重复载入，不得计为第三次
    b1 = base_stock(code="000002.SZ", name="乙二", recDate="2026-08-28", ref=None,
                    recIndex=17, days=10, last_close=13.0)
    b2 = base_stock(code="000002.SZ", name="乙二", recDate="2026-09-03", ref=12.0,
                    recIndex=23, days=3, last_close=13.0)
    c1 = base_stock(code="000003.SZ", name="丙三", recDate="2026-08-27", ref=7.0,
                    recIndex=17, days=11, last_close=7.7)
    c1["candles"] = [candle(7.0, 7.2) for _ in range(20)] + [None] * 6  # 报告日无行情
    d1 = base_stock(code="000004.SZ", name="丁四", recDate="2026-09-08", ref=None,
                    recIndex=26, days=0, d0=True)
    e1, e2 = two("000005.SZ", "戊五", "2026-09-01", 10.0, "2026-09-03", 9.0, 10.5)
    e2["refKind"] = "event"  # 正式+条件混合
    f1, f2 = two("000006.SZ", "己六", "2026-08-27", 18.0, "2026-09-03", 15.0, 16.0)
    f1["invalidated"] = True  # 第一轮失效、第二轮有效
    x1 = base_stock(code="000007.SZ", name="极下", recDate="2026-09-03", ref=100.0,
                    recIndex=23, days=3, last_close=65.0)   # -35%
    x2 = base_stock(code="000008.SZ", name="极上", recDate="2026-09-03", ref=10.0,
                    recIndex=23, days=3, last_close=14.5)   # +45%
    # 输入顺序故意倒置：每组的较晚记录排前面，并混入重复身份。
    return synth_snapshot([a2, a1, dup, b2, b1, c1, d1, e2, e1, f2, f1, x1, x2])


def load_builder():
    spec = importlib.util.spec_from_file_location("guanlan_prism_build_checker", PRISM_BUILD)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Harness:
    def __init__(self, page, errors):
        self.page = page
        self.errors = errors  # list[str]; JS/console errors land here
        self.failures = []

    def check(self, name, fn):
        try:
            fn()
            print(f"  PASS {name}")
        except AssertionError as exc:
            self.failures.append(f"{name}: {exc}")
            print(f"  FAIL {name}: {exc}")

    def expect(self, cond, msg):
        if not cond:
            raise AssertionError(msg)

    def text_contains(self, selector, needle):
        text = self.page.locator(selector).inner_text()
        self.expect(needle in text, f"{selector} 应包含“{needle}”，实际：{text[:200]!r}")


def snap_from_html(path: Path):
    text = path.read_text(encoding="utf-8")
    return json.loads(re.search(
        r'<script id="snapshot" type="application/json">(.*?)</script>', text, re.S).group(1))


def check_real_report(h: Harness, out: Path):
    page = h.page
    # —— 股票视图（默认） ——
    page.locator('.nav-item[data-nav="map"]').click()
    page.wait_for_timeout(250)
    stats = page.locator("#mapStats").inner_text()
    h.check("股票视图统计行", lambda: h.expect(
        stats == "36只股票 · 37条入选记录 · 33只有坐标 · 3只暂未绘制", f"实际：{stats!r}"))
    h.check("股票视图点数=33", lambda: h.expect(
        page.locator('#atlas [data-map-group]').count() == 33,
        f"实际 {page.locator('#atlas [data-map-group]').count()}"))
    h.check("徽标常驻图内", lambda: h.expect(
        "入选 2 次" in page.evaluate("document.getElementById('atlas').textContent"), "图内未见“入选 2 次”徽标"))
    pending = page.locator(".map-pending-item").all_inner_texts()
    h.check("暂未绘制列表3条", lambda: h.expect(len(pending) == 3, f"实际：{pending}"))
    h.check("暂未绘制原因", lambda: h.expect(
        any("缺参考价" in t for t in pending) and sum("待首日观察" in t for t in pending) == 2,
        f"原因缺失：{pending}"))
    def _labels_anchor_to_dots():
        res = page.evaluate("""(() => {
          const texts=[...document.querySelectorAll('#atlas g.map-dot text:not(.map-badge text)')];
          const rects=[...document.querySelectorAll('#atlas g.map-dot > text, #atlas g.map-badge rect')]
            .map(el=>el.getBoundingClientRect());
          let overlap=0;
          for(let i=0;i<rects.length;i++)for(let j=i+1;j<rects.length;j++){
            const a=rects[i],b=rects[j];
            if(a.left<b.right&&a.right>b.left&&a.top<b.bottom&&a.bottom>b.top)overlap++;
          }
          const dots=[...document.querySelectorAll('#atlas g.map-dot')].map(g=>{
            const c=g.querySelector('circle.bubble-core'),t=g.querySelector('text:not(.map-badge text)');
            return {cy:c.cy.baseVal.value, ty:t?+t.getAttribute('y'):null};
          });
          const shown=dots.filter(d=>d.ty!==null);
          return {dots:dots.length, labels:shown.length,
                  maxDrift:Math.max(0,...shown.map(d=>Math.abs(d.ty-(d.cy-8)))), overlap};
        })()""")
        h.expect(res["labels"] > 0, f"没有显示任何标签：{res}")
        h.expect(res["maxDrift"] <= 12.5, f"标签偏离自己的点超过一格：{res}")
        h.expect(res["overlap"] == 0, f"标签互相重叠 {res['overlap']} 处")
    h.check("标签贴自己的点且互不重叠", _labels_anchor_to_dots)

    def _badges_always_labelled():
        n = page.evaluate("[...document.querySelectorAll('#atlas g.map-dot')].filter(g=>g.querySelector('.map-badge')).length")
        ok = page.evaluate("[...document.querySelectorAll('#atlas g.map-dot')].filter(g=>g.querySelector('.map-badge')&&g.querySelector('text:not(.map-badge text)')).length")
        h.expect(n > 0 and n == ok, f"多次入选点缺标签 {ok}/{n}")
        h.expect(page.evaluate(
            "[...document.querySelectorAll('#atlas g.map-dot')].some(g=>g.querySelector('text:not(.map-badge text)')?.textContent.includes('中国船舶'))"),
            "中国船舶标签未显示")
    h.check("多次入选徽标常驻标签", _badges_always_labelled)
    page.screenshot(path=str(out / "atlas-stock.png"), full_page=True)

    # —— 选中中国船舶：面板展开两次明细 ——
    page.locator('[data-map-group="600150.SH"] .bubble-core').first.click()
    page.wait_for_timeout(250)
    panel = "#mapSelection"
    h.check("面板徽标·条件观察", lambda: h.text_contains(panel, "入选 2 次 · 条件观察"))
    h.check("首次基准收益+10.29%", lambda: h.text_contains(panel, "+10.29%"))
    h.check("锚点为最早记录08-31", lambda: h.text_contains(panel, "2026.08.31"))
    h.check("交易日序号第6", lambda: h.text_contains(panel, "第 6 个交易日"))
    h.check("报告日收盘38.38", lambda: h.text_contains(panel, "38.38"))
    h.check("最新一轮单列+12.55%", lambda: h.expect(
        "+12.55%" in page.locator(".map-latest-block").inner_text(),
        "最新一轮块未含 +12.55%"))
    h.check("两条入选明细", lambda: h.expect(
        page.locator(".map-episode").count() == 2, "明细应有两轮"))
    h.check("明细各自原参考价", lambda: h.expect(
        "34.80" in page.locator(panel).inner_text() and "34.10" in page.locator(panel).inner_text(),
        "两次参考价都应可见"))
    page.screenshot(path=str(out / "atlas-panel.png"), full_page=True)

    # —— 第二次的复盘按原键打开，返回后恢复视图与选择 ——
    page.locator('.map-episode [data-open="600150.SH:2026-09-03"]').click()
    page.wait_for_timeout(300)
    st = page.evaluate("window.GUANLAN.getState()")
    h.check("打开的是09-03那次", lambda: h.expect(
        st["current"] == "600150.SH:2026-09-03" and st["page"] == "detail", f"实际 {st['current']}"))
    h.check("详情页保留该次参考价34.10", lambda: h.text_contains(
        ".detail-metrics", "34.10"))
    page.locator(".back-button").click()
    page.wait_for_timeout(300)
    st = page.evaluate("window.GUANLAN.getState()")
    h.check("返回恢复星图与选择", lambda: h.expect(
        st["page"] == "map" and st["mapMode"] == "stock"
        and st["mapGroup"] == "600150.SH", f"实际 {st}"))

    # —— 记录视图：同股两点、标签带日期 ——
    page.locator('[data-map-mode="record"]').click()
    page.wait_for_timeout(250)
    stats = page.locator("#mapStats").inner_text()
    h.check("记录视图统计行", lambda: h.expect(
        stats == "36只股票 · 37条入选记录 · 34条有坐标 · 3条暂未绘制", f"实际：{stats!r}"))
    h.check("记录视图点数=34", lambda: h.expect(
        page.locator('#atlas [data-map-id]').count() == 34,
        f"实际 {page.locator('#atlas [data-map-id]').count()}"))
    labels = page.evaluate("document.getElementById('atlas').textContent")
    h.check("同股两点标签带日期", lambda: h.expect(
        "中国船舶 · 08/31" in labels and "中国船舶 · 09/03" in labels, f"标签缺失：{labels[:300]!r}"))
    page.screenshot(path=str(out / "atlas-record.png"), full_page=True)
    page.locator('[data-map-id="600150.SH:2026-08-31"] .bubble-core').first.click()
    page.wait_for_timeout(250)
    h.check("记录视图选中08-31", lambda: h.expect(
        page.evaluate("window.GUANLAN.getState()")["mapCurrent"] == "600150.SH:2026-08-31",
        "记录视图选择键不正确"))
    h.check("记录视图面板含阅读按钮", lambda: h.expect(
        page.locator(f'{panel} [data-open="600150.SH:2026-08-31"]').count() == 1,
        "面板缺少该次的复盘入口"))

    # —— 快照未被改写 ——
    def canon(text):
        # 两侧数字统一按 float 归一，消除 JS/Python 的 43 与 43.0 文本差异。
        return json.dumps(json.loads(text, parse_int=float), ensure_ascii=False, sort_keys=True)
    live_text = page.evaluate("JSON.stringify(window.GUANLAN.snapshot)")
    h.check("内嵌快照与原始一致", lambda: h.expect(
        canon(live_text) == canon(h.snapshot_raw), "快照被前端改写"))


def check_mobile(h: Harness, out: Path):
    page = h.page
    page.goto(h.url)
    page.locator('.nav-item[data-nav="map"]').click()
    page.wait_for_timeout(300)
    sel_box = page.locator("#mapSelection").bounding_box()
    svg_box = page.locator("#atlas").bounding_box()
    h.check("移动端面板显示在图下", lambda: h.expect(
        sel_box is not None and svg_box is not None and sel_box["y"] >= svg_box["y"] + svg_box["height"] - 5,
        f"面板 box={sel_box} 图 box={svg_box}"))
    dot = page.locator('[data-map-group="600150.SH"] .bubble-core').first.bounding_box()
    page.touchscreen.tap(dot["x"] + dot["width"] / 2, dot["y"] + dot["height"] / 2)
    page.wait_for_timeout(300)
    h.check("手机点按固定选中", lambda: h.text_contains("#mapSelection", "入选 2 次 · 条件观察"))
    page.screenshot(path=str(out / "atlas-mobile.png"), full_page=True)


def check_synthetic(h: Harness, builder, out: Path):
    page = h.page
    tmp = Path(tempfile.mkdtemp(prefix="prism-atlas-synth-"))
    main = tmp / "synthetic.html"
    main.write_text(builder.render_html(synth_main()), encoding="utf-8")
    page.goto(main.as_uri())
    page.locator('.nav-item[data-nav="map"]').click()
    page.wait_for_timeout(250)
    h.check("合成页重复身份不计次", lambda: h.text_contains("#mapStats", "8只股票 · 13条入选记录"))

    def _select_first(code):
        page.locator(f'[data-map-group="{code}"] .bubble-core').first.click()
        page.wait_for_timeout(200)

    def _check_group_a():
        _select_first("000001.SZ")
        h.text_contains("#mapSelection", "-16.00%")
    h.check("合成页甲一主点-16%", _check_group_a)
    h.check("合成页甲一最新+5%", lambda: h.text_contains(".map-latest-block", "+5.00%"))
    h.check("合成页极端收益在轴内", lambda: h.expect(
        "极下" in page.evaluate("document.getElementById('atlas').textContent") and "极上" in page.evaluate("document.getElementById('atlas').textContent"),
        "极端收益点未绘制"))
    svg_html = page.locator("#atlas").inner_html()
    h.check("图内无NaN/Infinity", lambda: h.expect(
        "NaN" not in svg_html and "Infinity" not in svg_html, "坐标出现 NaN/Infinity"))
    in_box = page.evaluate("""(() => {
      const svg=document.querySelector('#atlas');
      const H=svg.viewBox.baseVal.height;
      const dots=[...svg.querySelectorAll('g.map-dot circle.bubble-core')];
      return dots.length>0 && dots.every(c=>c.cy.baseVal.value>0 && c.cy.baseVal.value<H);
    })()""")
    h.check("所有点在画布内", lambda: h.expect(in_box, "存在超出画布的点"))
    pending = page.locator(".map-pending-item").all_inner_texts()
    h.check("合成页缺参考价入列", lambda: h.expect(any("缺参考价" in t for t in pending), f"{pending}"))
    h.check("合成页缺当日行情入列", lambda: h.expect(any("报告日无真实收盘" in t for t in pending), f"{pending}"))
    h.check("合成页待首日入列", lambda: h.expect(any("待首日观察" in t for t in pending), f"{pending}"))
    page.locator('[data-map-group="000005.SZ"] .bubble-core').first.click()
    page.wait_for_timeout(200)
    h.check("混合类型徽标", lambda: h.text_contains("#mapSelection", "入选 2 次 · 含条件观察"))
    page.locator('[data-map-group="000006.SZ"] .bubble-core').first.click()
    page.wait_for_timeout(200)
    h.check("失效轮仍独立保留", lambda: h.text_contains("#mapSelection", "判断失效"))
    h.check("失效轮基准仍在最早", lambda: h.text_contains("#mapSelection", "2026.08.27"))
    page.screenshot(path=str(out / "synthetic-stock.png"), full_page=True)
    page.locator('[data-map-mode="record"]').click()
    page.wait_for_timeout(250)
    page.screenshot(path=str(out / "synthetic-record.png"), full_page=True)

    empty = tmp / "empty.html"
    empty.write_text(builder.render_html(synth_snapshot([])), encoding="utf-8")
    page.goto(empty.as_uri())
    page.locator('.nav-item[data-nav="map"]').click()
    page.wait_for_timeout(250)
    h.check("空列表不崩溃", lambda: h.expect(
        page.locator("body").inner_text().find("暂无观察记录") >= 0, "空快照应显示如实空状态"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--html", required=True, help="真实报告 HTML 路径")
    parser.add_argument("--out", default=None, help="截图输出目录")
    args = parser.parse_args()
    html_path = Path(args.html).resolve()
    if not html_path.is_file():
        print(f"报告不存在：{html_path}")
        return 2
    out = Path(args.out).resolve() if args.out else Path(tempfile.mkdtemp(prefix="prism-atlas-shots-"))
    out.mkdir(parents=True, exist_ok=True)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright 未安装：/.venv/bin/python -m pip install playwright")
        return 2
    if not Path(CHROME).exists():
        print(f"未找到 Chrome：{CHROME}")
        return 2

    failures: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME, headless=True)
        errors: list[str] = []
        desktop = browser.new_context(viewport={"width": 1440, "height": 1100}, device_scale_factor=1)
        page = desktop.new_page()
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}") if m.type == "error" else None)
        h = Harness(page, errors)
        h.url = html_path.as_uri()
        h.snapshot_raw = re.search(r'<script id="snapshot" type="application/json">(.*?)</script>',
                                   html_path.read_text(encoding="utf-8"), re.S).group(1)
        print(f"报告：{html_path}")
        print("真实报告页检查：")
        page.goto(h.url)
        page.wait_for_timeout(400)
        check_real_report(h, out)
        print("移动端检查：")
        mobile = browser.new_context(viewport={"width": 390, "height": 844},
                                     device_scale_factor=1, is_mobile=True, has_touch=True)
        mpage = mobile.new_page()
        mpage.on("pageerror", lambda e: errors.append(f"mobile pageerror: {e}"))
        mpage.on("console", lambda m: errors.append(f"mobile console.{m.type}: {m.text}") if m.type == "error" else None)
        hm = Harness(mpage, errors)
        hm.url = h.url
        check_mobile(hm, out)
        print("合成数据页检查：")
        spage = desktop.new_page()
        spage.on("pageerror", lambda e: errors.append(f"synth pageerror: {e}"))
        spage.on("console", lambda m: errors.append(f"synth console.{m.type}: {m.text}") if m.type == "error" else None)
        hs = Harness(spage, errors)
        hs.url = h.url
        check_synthetic(hs, load_builder(), out)
        browser.close()

    if errors:
        for err in errors:
            print(f"JS/CONSOLE 错误：{err}")
    if failures or errors:
        print(f"\n结果：失败 {len(failures)} 项，JS/控制台错误 {len(errors)} 条；截图目录 {out}")
        return 1
    print(f"\n结果：全部通过；截图目录 {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
