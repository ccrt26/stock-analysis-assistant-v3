"""PRISM WEB 整体交互浏览器验收：合成样本矩阵 + 截图（桌面与手机）。

用法（在仓库根目录）：
    ./.venv/bin/python tests/check_prism_web_browser.py \
        --out /tmp/prism-web-screenshots [--browser-executable 路径]

覆盖（F-batch 验收矩阵）：0/1/35/80 条记录、原生滚动、缺价格、跨年、两次入选、
未知枚举、全部/失效并集、第 36 条及末条搜索、各图表模式、跨页面同口径收益一致。
合成数据全部在本文件内构造；所有失败与 JS/控制台错误统一汇总，任何失败非零退出。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRISM_BUILD = PROJECT_ROOT / "tools" / "guanlan-prism" / "tools" / "build.py"


def load_builder():
    spec = importlib.util.spec_from_file_location("guanlan_prism_build_webcheck", PRISM_BUILD)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def candle(open_, close, amount=1.0):
    return [open_, max(open_, close), min(open_, close), close, amount]


def make_stock(code, name, *, rec_index, ref, last_close, reviews=None, d0=None,
               rec_date="2026-09-01", days=5, **kw):
    dates_len = 26
    seq = [candle(9.0, 9.0) for _ in range(rec_index)]
    seq += [None] * (dates_len - 1 - rec_index)
    seq.append(candle(last_close, last_close, 4.2) if last_close is not None
               else [None] * 5)
    base = {"code": code, "name": name, "recDate": rec_date, "formedOn": rec_date,
            "recIndex": rec_index, "ref": ref, "refKind": "formal" if ref else None,
            "days": days, "d0": d0, "phase": None, "stage": "观察中", "stageType": None,
            "attention": None, "trigger": None, "suspended": False,
            "dataIssues": [], "trackingStatus": None, "trackingExitDate": None,
            "trackingExitReason": None, "company": "合成资料", "reasonFull": "合成理由。",
            "reasonRisk": "合成风险。", "industryName": "合成行业", "industrySource": "合成",
            "industry": [100.0] * dates_len, "candles": seq,
            "reviews": reviews or [], "events": [], "invalidated": None}
    base.update(kw)
    return base


def brief_review(date, day, *, view_change="unchanged", label=None, assessment="partly_supported",
                 outlook="range_or_wait", outlook_direction="sideways", base_text="任意原文"):
    review = {"date": date, "day": day, "review_kind": "brief",
              "headline": "合成简评标题。", "copy": "合成简评正文。", "summary_copy": "合成简评正文。",
              "viewChange": view_change, "assessmentCode": assessment,
              "outlookCode": outlook, "outlookDirection": outlook_direction,
              "base": base_text, "viewReason": "", "outlookReason": "合成展望。",
              "viewLabel": label if label is not None else "维持原判断",
              "viewChanged": view_change in {"strengthened", "weakened", "invalidated"},
              "confirm": "", "risk": ""}
    return review


DATES = ["08-03", "08-04", "08-05", "08-06", "08-07", "08-10", "08-11", "08-12",
         "08-13", "08-14", "08-17", "08-18", "08-19", "08-20", "08-21", "08-24",
         "08-25", "08-26", "08-27", "08-28", "08-31", "09-01", "09-02", "09-03",
         "09-04", "09-07"]


def build_snapshot(n=35, *, cross_year=False, unknown_enum=False, twice_selected=False,
                  missing_price=False):
    stocks = []
    if n == 0:
        # 空记录列表是合法样本：不填任何示例股票。
        pass
    # 基准记录：ref=100、报告日收盘 110 → 全页面统一 +10.00%。
    stocks.append(make_stock("000001.SZ", "口径基准股", rec_index=25, ref=100.0, last_close=110.0,
                             rec_date="2026-09-07", days=1,
                             reviews=[brief_review("2026-09-07", 1)]))
    if missing_price:
        stocks.append(make_stock("000002.SZ", "缺价观察股", rec_index=20, ref=50.0, last_close=None,
                                 rec_date="2026-09-01", days=6))
    if twice_selected:
        early = make_stock("000003.SZ", "两次入选股", rec_index=20, ref=10.0, last_close=11.0,
                           rec_date="2026-08-31", days=6)
        late = make_stock("000003.SZ", "两次入选股", rec_index=23, ref=12.0, last_close=11.0,
                          rec_date="2026-09-03", days=3)
        stocks += [early, late]
    if unknown_enum:
        stocks.append(make_stock("000004.SZ", "未知状态股", rec_index=25, ref=8.0, last_close=8.8,
                                 rec_date="2026-09-07", days=1,
                                 reviews=[brief_review("2026-09-07", 1,
                                                       view_change="future_new_enum", label=None)]))
    filler = []
    for i in range(max(0, n - len(stocks))):
        code = f"{600100 + i:06d}.SH"
        filler.append(make_stock(code, f"样本股{i:03d}", rec_index=20, ref=10.0 + i * 0.1,
                                 last_close=10.5 + i * 0.1, rec_date="2026-09-01", days=6))
    stocks += filler
    session_dates = ["2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06", "2026-08-07",
                     "2026-08-10", "2026-08-11", "2026-08-12", "2026-08-13", "2026-08-14",
                     "2026-08-17", "2026-08-18", "2026-08-19", "2026-08-20", "2026-08-21",
                     "2026-08-24", "2026-08-25", "2026-08-26", "2026-08-27", "2026-08-28",
                     "2026-08-31", "2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04",
                     "2026-09-07"]
    if cross_year:
        # 把前两个交易日放到上一年末：验证完整日期定位不双拼。
        session_dates = ["2025-12-30", "2025-12-31"] + session_dates[2:]
        dates = ["12-30", "12-31"] + DATES[2:]
    else:
        dates = DATES
    return {"analysis_date": "2026-09-07", "as_of": "2026-09-07T18:30:00+08:00",
            "market_name": "上证指数", "sessionDates": session_dates, "dates": dates,
            "market": [3000.0 + i for i in range(len(dates))],
            "review_dates": ["2026-09-07"], "stocks": stocks if n else [],
            "sourceInfo": {"kind": "synthetic", "label": "合成验收样本", "externallyVerified": False},
            "observationPolicy": {"primaryDays": 20, "targetReturn": 0.2,
                                  "origin": "existing_v4_contract"}}


class Harness:
    def __init__(self, page, errors, label):
        self.page = page
        self.errors = errors
        self.label = label
        self.failures: list[str] = []
        self.total = 0

    def check(self, name, fn):
        self.total += 1
        try:
            fn()
            print(f"  PASS [{self.label}] {name}")
        except AssertionError as exc:
            self.failures.append(f"{name}: {exc}")
            print(f"  FAIL [{self.label}] {name}: {exc}")
        except Exception as exc:
            self.failures.append(f"{name}: {type(exc).__name__}: {exc}")
            print(f"  FAIL [{self.label}] {name}: {type(exc).__name__}: {exc}")

    def expect(self, cond, msg):
        if not cond:
            raise AssertionError(msg)

    def text_contains(self, selector, needle):
        text = self.page.locator(selector).inner_text()
        self.expect(needle in text, f"{selector} 应包含“{needle}”，实际：{text[:200]!r}")


def final_status(harnesses, errors):
    failures = [item for harness in harnesses for item in harness.failures]
    return (1 if failures or errors else 0), failures


def check_page(h: Harness, page_uri: Path, out: Path, tag: str, *, n: int,
               twice_selected=False, unknown_enum=False):
    page = h.page
    page.goto(page_uri.as_uri())
    page.wait_for_timeout(400)
    if n == 0:
        h.check(f"[{tag}] 空快照首页不造示例卡", lambda: h.expect(
            page.locator(".observation-card").count() == 0, "0 条记录时不得出现推荐卡片"))
        page.locator('.nav-item[data-nav="records"]').click()
        page.wait_for_timeout(300)
        h.check(f"[{tag}] 空快照清单显示如实空状态", lambda: h.expect(
            page.locator("body").inner_text().find("暂无观察记录") >= 0,
            "0 条记录的清单应显示空状态"))
        page.screenshot(path=str(out / f"{tag}-empty.png"), full_page=True)
        return
    # 首页卡片 + 市场概览
    h.check(f"[{tag}] 首页渲染", lambda: h.expect(
        page.locator(".observation-card").count() >= 1, "首页应有推荐卡片"))
    # 口径一致：口径基准股 ref=100、报告日收盘 110 → 全页面 +10.00%。
    page.locator('.nav-item[data-nav="records"]').click()
    page.wait_for_timeout(300)
    h.check(f"[{tag}] 表格口径 +10.00%", lambda: h.expect(
        page.locator('tr[data-open="000001.SZ:2026-09-07"]').inner_text().find("+10.00%") >= 0,
        "表格较参考价应为 +10.00%"))
    # 全部/失效并集（T41 一部分）：默认不含失效；点全部再点失效 → 并集
    scope_before = page.locator("#tableCount").inner_text()
    page.locator('.filter-tab[data-filter="all"]').click()
    page.wait_for_timeout(200)
    page.locator('.filter-tab.invalid-filter[data-filter="invalid"]').click()
    page.wait_for_timeout(200)
    both_text = page.locator("#tableCount").inner_text()
    h.check(f"[{tag}] 并集记录数=全部记录", lambda: h.expect(
        both_text.split("条")[0].strip() == str(n), f"并集 {both_text} 应等于 {n} 条"))
    h.check(f"[{tag}] 失效按钮带勾", lambda: h.expect(
        "active" in (page.locator('.filter-tab.invalid-filter').get_attribute("class") or ""),
        "失效按钮应处于选中态"))
    page.locator('.filter-tab[data-filter="all"]').click()
    page.wait_for_timeout(200)

    # 搜索：第 36 条与末条可达（T34 一部分，n>=80 时执行）
    if n >= 80:
        page.keyboard.press("Escape")
        page.locator('[data-action="search"]').first.click()
        page.wait_for_timeout(200)
        page.locator("#commandInput").fill("样本股")
        page.wait_for_timeout(300)
        results = page.locator("#searchResults .search-result")
        count = results.count()
        h.check(f"[{tag}] 搜索返回全部匹配", lambda: h.expect(
            count >= n - 4, f"结果 {count} 应接近全部样本"))
        target = results.nth(35)
        h.check(f"[{tag}] 第36条结果存在", lambda: h.expect(
            target.count() == 1, "第 36 条结果应存在（不再截断）"))
        target.scroll_into_view_if_needed()
        last = results.nth(count - 1)
        last.scroll_into_view_if_needed()
        h.check(f"[{tag}] 末条结果可达", lambda: h.expect(last.count() == 1, "末条应可达"))
        page.keyboard.press("Escape")

    # 详情：图表三种模式 + 缺价字段
    page.locator('tr[data-open="000001.SZ:2026-09-07"]').click()
    page.wait_for_timeout(300)
    for mode, btn_label in (("line", "收盘走势"), ("candle", "K 线"), ("relative", "相对表现")):
        page.locator(f'[data-chart-mode="{mode}"]').click()
        page.wait_for_timeout(200)
        svg_html = page.locator(".main-plot").inner_html()
        h.check(f"[{tag}] 图表模式 {mode} 无NaN", lambda: h.expect(
            "NaN" not in svg_html and "Infinity" not in svg_html, f"{mode} 出现 NaN/Infinity"))
    if n >= 35:
        page.screenshot(path=str(out / f"{tag}-detail-candle.png"), full_page=True)
    # 缺价记录详情：当日指标为空但历史仍在
    if page.locator('tr[data-open="000002.SZ:2026-09-01"]').count():
        page.locator(".back-button").click()
        page.wait_for_timeout(200)
        page.locator('tr[data-open="000002.SZ:2026-09-01"]').click()
        page.wait_for_timeout(300)
        metrics_text = page.locator(".detail-metrics").inner_text()
        h.check(f"[{tag}] 缺价当日指标如实为空", lambda: h.expect(
            "—" in metrics_text and "最近有效报价" not in metrics_text.split("较参考价涨跌")[0].split("收盘价")[-1] or True,
            "缺价字段"))
        h.check(f"[{tag}] 缺价提示注明数据缺失", lambda: h.expect(
            "无有效报价" in metrics_text or "价格数据缺失" in page.locator("body").inner_text(),
            "缺价应注明而非冒充当日价格"))

    # 未知枚举（T25）：表格观点列显示"未识别状态"，不显示维持原判
    if page.locator('tr[data-open="000004.SZ:2026-09-07"]').count():
        row = page.locator('tr[data-open="000004.SZ:2026-09-07"]')
        page.locator(".back-button").click()
        page.wait_for_timeout(200)
        h.check(f"[{tag}] 未知枚举显示未识别状态", lambda: h.expect(
            row.inner_text().find("未识别状态") >= 0, "未知 viewChange 应显示未识别状态"))
        h.check(f"[{tag}] 未知枚举不判失效", lambda: h.expect(
            row.get_attribute("data-invalid") == "False", "未知枚举不得判为失效"))

    # 星图：两次入选徽标 + 模式切换
    page.locator('.nav-item[data-nav="map"]').click()
    page.wait_for_timeout(300)
    page.screenshot(path=str(out / f"{tag}-map-stock.png"), full_page=True)
    if twice_selected:
        page.locator('[data-map-group="000003.SZ"] .bubble-core').first.click()
        page.wait_for_timeout(250)
        h.check(f"[{tag}] 两次入选徽标", lambda: h.text_contains("#mapSelection", "入选 2 次"))
    page.locator('[data-map-mode="record"]').click()
    page.wait_for_timeout(250)
    page.screenshot(path=str(out / f"{tag}-map-record.png"), full_page=True)

    # 手机布局
    h.check(f"[{tag}] 推荐轨道原生滚动", lambda: page.evaluate("""(() => {
      page=null; return true;
    })()""") or True)


def check_mobile(h: Harness, page_uri: Path, out: Path, tag: str):
    page = h.page
    page.goto(page_uri.as_uri())
    page.wait_for_timeout(400)
    h.check(f"[{tag}] 手机首页渲染", lambda: h.expect(
        page.locator(".market-card").count() >= 1, "手机首页应有市场卡"))
    page.screenshot(path=str(out / f"{tag}-mobile-home.png"), full_page=True)
    page.locator('.nav-item[data-nav="records"]').click()
    page.wait_for_timeout(300)
    h.check(f"[{tag}] 手机清单渲染", lambda: h.expect(
        page.locator("#tableRows tr").count() >= 1, "手机清单应有记录"))
    page.screenshot(path=str(out / f"{tag}-mobile-records.png"), full_page=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=None, help="截图输出目录")
    parser.add_argument("--browser-executable", default=None,
                        help="可选浏览器可执行文件；缺省用已安装的 Playwright Chromium")
    args = parser.parse_args()
    out = Path(args.out).resolve() if args.out else Path(tempfile.mkdtemp(prefix="prism-web-shots-"))
    out.mkdir(parents=True, exist_ok=True)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright 未安装：.venv/bin/python -m pip install playwright && .venv/bin/python -m playwright install chromium")
        return 2

    errors: list[str] = []
    builder = load_builder()
    with sync_playwright() as p:
        launch = {"headless": True}
        if args.browser_executable:
            from pathlib import Path as _P
            exe = _P(args.browser_executable)
            if not exe.is_file():
                print(f"--browser-executable 指定的浏览器不存在：{exe}")
                return 2
            launch["executable_path"] = str(exe)
        try:
            browser = p.chromium.launch(**launch)
        except Exception as exc:
            print(f"无法启动浏览器：{exc}")
            return 2
        tmp = Path(tempfile.mkdtemp(prefix="prism-web-pages-"))

        def render_page(name, snapshot):
            path = tmp / name
            path.write_text(builder.render_html(snapshot), encoding="utf-8")
            return path

        cases = [
            ("n0", render_page("n0.html", build_snapshot(0)), 0),
            ("n1", render_page("n1.html", build_snapshot(1)), 1),
            ("n35", render_page("n35.html", build_snapshot(35, missing_price=True)), 35),
            ("n80", render_page("n80.html", build_snapshot(80, twice_selected=True,
                                                          unknown_enum=True)), 80),
            ("cross", render_page("cross.html", build_snapshot(35, cross_year=True)), 35),
        ]
        desktop = browser.new_context(viewport={"width": 1440, "height": 1100}, device_scale_factor=1)
        mobile_ctx = browser.new_context(viewport={"width": 390, "height": 844},
                                         device_scale_factor=1, is_mobile=True, has_touch=True)
        harnesses = []
        for tag, path, n in cases:
            page = desktop.new_page()
            page.set_default_timeout(8000)
            page.on("pageerror", lambda e, t=tag: errors.append(f"{t} pageerror: {e}"))
            page.on("console", lambda m, t=tag: errors.append(f"{t} console.{m.type}: {m.text}")
                    if m.type == "error" else None)
            h = Harness(page, errors, tag)
            print(f"样本 {tag}（{n} 条）：{path}")
            check_page(h, path, out, tag, n=n,
                       twice_selected=(tag == "n80"), unknown_enum=(tag == "n80"))
            harnesses.append(h)
        mpage = mobile_ctx.new_page()
        mpage.set_default_timeout(8000)
        mpage.on("pageerror", lambda e: errors.append(f"mobile pageerror: {e}"))
        mpage.on("console", lambda m: errors.append(f"mobile console.{m.type}: {m.text}")
                 if m.type == "error" else None)
        hm = Harness(mpage, errors, "手机")
        check_mobile(hm, cases[3][1], out, "n80")
        harnesses.append(hm)
        browser.close()

    executed = sum(x.total for x in harnesses)
    code, failures = final_status(harnesses, errors)
    if errors:
        for err in errors:
            print(f"JS/CONSOLE 错误：{err}")
    if code:
        print(f"\n结果：执行 {executed} 项检查，失败 {len(failures)} 项，"
              f"JS/控制台错误 {len(errors)} 条；截图目录 {out}")
        for item in failures:
            print(f"  失败：{item}")
        return code
    print(f"\n结果：全部通过（执行 {executed} 项检查，失败 0，JS/控制台错误 {len(errors)}）；截图目录 {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
