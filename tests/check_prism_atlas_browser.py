"""观察星图浏览器验收：任意真实报告通用检查 + 固定合成回归样本 + 截图。

用法（在仓库根目录）：
    ./.venv/bin/python tests/check_prism_atlas_browser.py \
        --html local_archive/forward_monitor/prism-report-2026-09-07.html \
        --out /tmp/prism-atlas-screenshots

验收合同（F10 整改）：
1. 桌面 / 手机 / 合成页三个 Harness 的全部断言失败与所有 JS/控制台错误统一由
   final_status() 汇总；任何失败都以非零码退出，摘要报告实际执行数与失败数。
2. 真实报告的期望值全部由 Python 从页面内嵌快照独立计算（与页面 JS 同一合同、
   两套实现）；不存在绑定某份历史报告的写死数量、股票名或价格。固定样本断言
   只出现在下方明确标注的合成回归样本中。
3. --browser-executable 可显式指定浏览器；缺省使用已安装的 Playwright Chromium。
   浏览器依赖缺失或路径无效时明确退出码 2，不静默跳过。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRISM_BUILD = PROJECT_ROOT / "tools" / "guanlan-prism" / "tools" / "build.py"
CONTRACT = PROJECT_ROOT / "tools" / "web_display_contract.py"


def _load_contract():
    spec = importlib.util.spec_from_file_location("web_display_contract", CONTRACT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


SYNTH_DATES = ["08-03", "08-04", "08-05", "08-06", "08-07", "08-10", "08-11", "08-12",
               "08-13", "08-14", "08-17", "08-18", "08-19", "08-20", "08-21", "08-24",
               "08-25", "08-26", "08-27", "08-28", "08-31", "09-01", "09-02", "09-03",
               "09-04", "09-07"]


def synth_snapshot(stocks):
    for s in stocks:
        if "candles" not in s:
            rec = s.get("recIndex", 0)
            seq = [candle(9.0, 9.0) for _ in range(rec)]
            seq += [None] * (len(SYNTH_DATES) - 1 - rec)
            close = s.pop("last_close", 10.0)
            seq.append(candle(close, close, 4.2))
            s["candles"] = seq
    return {"analysis_date": "2026-09-07", "as_of": "2026-09-07T18:30:00+08:00",
            "market_name": "上证指数", "dates": SYNTH_DATES,
            "market": [3000.0 + i for i in range(len(SYNTH_DATES))],
            "review_dates": ["2026-09-07"], "stocks": stocks}


def synth_main():
    """固定回归样本：重复身份、缺数据、状态独立、事件混合与 -35%/+45% 极端收益。

    本样本的数字（-16%/+5%、两次入选等）只与该 fixture 绑定，不用于任何
    真实生产报告的验收（T08）。
    """
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


def synth_broken_dates():
    """负对照样本：sessionDates 末日与 analysis_date 不一致（长度相同、内容错误），
    页面与独立期望计算都必须拒绝，而不是假装成功。"""
    snapshot = synth_snapshot([])
    session = ["2026-08-03"] * (len(SYNTH_DATES) - 1) + ["2026-09-06"]
    snapshot["sessionDates"] = session
    return snapshot


def load_builder():
    spec = importlib.util.spec_from_file_location("guanlan_prism_build_checker", PRISM_BUILD)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# 与 rules.js 同一合同的独立 Python 期望计算（不调用页面 JS）
# ---------------------------------------------------------------------------

def _valid(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def atlas_expectations(snapshot: dict) -> dict:
    contract = _load_contract()
    dates = contract.resolve_session_dates(
        snapshot.get("dates"), snapshot["analysis_date"], snapshot.get("sessionDates")
    )
    report_index = dates.index(snapshot["analysis_date"])
    groups: dict[str, list[dict]] = {}
    order: list[str] = []
    for s in snapshot.get("stocks", []):
        bucket = groups.setdefault(s["code"], [])
        if not any(x["recDate"] == s["recDate"] for x in bucket):
            bucket.append(s)
        if s["code"] not in order:
            order.append(s["code"])
    parsed = []
    for code in order:
        records = sorted(groups[code], key=lambda s: s["recDate"])
        parsed.append({"code": code, "name": records[0]["name"], "records": records})
    parsed.sort(key=lambda g: g["records"][0]["recDate"])

    def reason(s, close) -> str | None:
        if s.get("d0"):
            return "待首日观察"
        if not _valid(s.get("ref")) or s["ref"] <= 0:
            return "缺参考价"
        i = s.get("recIndex")
        if not _valid(i) or i < 0 or i > report_index:
            return "交易日历不足"
        if not _valid(close):
            return "报告日无真实收盘"
        return None

    for group in parsed:
        close = None
        for s in group["records"]:
            candles = s.get("candles") or []
            row = candles[report_index] if report_index < len(candles) else None
            if _valid(row and row[3]):
                close = row[3]
                break
        anchor = group["records"][0]
        group["close"] = close
        group["anchor_reason"] = reason(anchor, close)
        group["anchor_ret"] = (
            (close / anchor["ref"] - 1) * 100
            if group["anchor_reason"] is None else None
        )
        group["anchor_day"] = report_index - anchor["recIndex"] + 1 \
            if group["anchor_reason"] is None else None
        group["points"] = [
            {"key": f"{s['code']}:{s['recDate']}", "reason": reason(s, close),
             "ret": (close / s["ref"] - 1) * 100 if reason(s, close) is None else None}
            for s in group["records"]
        ]

    def badge(group) -> str | None:
        n = len(group["records"])
        if n < 2:
            return None
        pending = sum(1 for s in group["records"] if s.get("d0"))
        events = sum(1 for s in group["records"] if s.get("refKind") == "event")
        tags = []
        if events == n:
            tags.append("条件观察")
        elif events:
            tags.append("含条件观察")
        if pending:
            tags.append(f"含{pending}次待首日")
        label = f"入选 {n} 次"
        return label + (f" · {' · '.join(tags)}" if tags else "")

    stock_plottable = [g for g in parsed if g["anchor_reason"] is None]
    record_plottable = [p for g in parsed for p in g["points"] if p["reason"] is None]
    total_records = len(snapshot.get("stocks", []))
    return {
        "report_index": report_index,
        "groups": parsed,
        "badge": badge,
        "stock_stats": (
            f"{len(parsed)}只股票 · {total_records}条入选记录 · "
            f"{len(stock_plottable)}只有坐标 · {len(parsed) - len(stock_plottable)}只暂未绘制"
        ),
        "record_stats": (
            f"{len(parsed)}只股票 · {total_records}条入选记录 · "
            f"{len(record_plottable)}条有坐标 · {total_records - len(record_plottable)}条暂未绘制"
        ),
        "multi_groups": [g for g in parsed if len(g["records"]) >= 2],
    }


def pct_text(value) -> str:
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.2f}%"


class Harness:
    def __init__(self, page, errors, label):
        self.page = page
        self.errors = errors  # list[str]; JS/console errors land here
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
        except Exception as exc:  # 元素缺失超时等运行错误同样计入失败，不让 main 崩溃。
            self.failures.append(f"{name}: {type(exc).__name__}: {exc}")
            print(f"  FAIL [{self.label}] {name}: {type(exc).__name__}: {exc}")

    def expect(self, cond, msg):
        if not cond:
            raise AssertionError(msg)

    def text_contains(self, selector, needle):
        text = self.page.locator(selector).inner_text()
        self.expect(needle in text, f"{selector} 应包含“{needle}”，实际：{text[:200]!r}")


def final_status(harnesses, errors):
    """汇总所有 Harness 失败与 JS/控制台错误；任何失败都必须非零。"""
    failures = [item for harness in harnesses for item in harness.failures]
    return (1 if failures or errors else 0), failures


def snap_from_html(path: Path):
    text = path.read_text(encoding="utf-8")
    return json.loads(re.search(
        r'<script id="snapshot" type="application/json">(.*?)</script>', text, re.S).group(1))


def _labels_anchor_to_dots(h: Harness):
    page = h.page
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


def _mode_axis_captions(h: Harness):
    """F13 模式文案：轴说明必须随股票/记录模式变化，不得都写“首次”。"""
    page = h.page
    res = page.evaluate("""(() => {
      const t=[...document.querySelectorAll('#atlas text.chart-label')].map(e=>e.textContent);
      return {all:t.join('|'), zero:t.find(x=>x.startsWith('零线＝'))||''};
    })()""")
    stock_view = page.evaluate("window.GUANLAN.getState().mapMode") == "stock"
    if stock_view:
        h.expect("较最早记录参考价涨跌" in res["all"], f"股票视图纵轴说明缺失：{res}")
        h.expect(res["zero"] == "零线＝该记录原参考价", f"股票视图零线说明：{res}")
        h.expect("自本报告最早记录的首个观察日起的交易日" in res["all"], f"股票视图横轴说明：{res}")
    else:
        h.expect("较该次入选参考价涨跌" in res["all"], f"记录视图纵轴说明缺失：{res}")
        h.expect(res["zero"] == "零线＝该次原参考价", f"记录视图零线说明：{res}")
        h.expect("自该次入选的首个观察日起的交易日" in res["all"], f"记录视图横轴说明：{res}")
    h.expect("较首次参考价涨跌" not in res["all"] and "零线＝首次参考价" not in res["all"],
             f"仍残留固定“首次”轴说明：{res}")


def check_real_report(h: Harness, expect: dict, out: Path):
    """任意真实报告的通用检查：期望值来自 atlas_expectations(snapshot)。"""
    page = h.page
    page.locator('.nav-item[data-nav="map"]').click()
    page.wait_for_timeout(250)
    # —— 股票视图（默认） ——
    stats = page.locator("#mapStats").inner_text()
    h.check("股票视图统计行=独立计算", lambda: h.expect(
        stats == expect["stock_stats"], f"实际：{stats!r} 期望：{expect['stock_stats']!r}"))
    expected_groups = sum(1 for g in expect["groups"] if g["anchor_reason"] is None)
    h.check("股票视图点数=可绘制组数", lambda: h.expect(
        page.locator('#atlas [data-map-group]').count() == expected_groups,
        f"实际 {page.locator('#atlas [data-map-group]').count()} 期望 {expected_groups}"))
    badge_groups = [g for g in expect["groups"] if expect["badge"](g)]
    page_html = page.evaluate("document.getElementById('atlas').textContent")
    for g in badge_groups:
        h.check(f"徽标常驻图内 {g['code']}", lambda g=g: h.expect(
            expect["badge"](g) in page_html, f"图内未见“{expect['badge'](g)}”徽标"))
    pending = page.locator(".map-pending-item").all_inner_texts()
    expected_pending = len(expect["groups"]) - expected_groups
    h.check("暂未绘制条数=独立计算", lambda: h.expect(
        len(pending) == expected_pending, f"实际：{pending}（期望 {expected_pending} 条）"))
    h.check("暂未绘制列表为空时不应出现", lambda: h.expect(
        expected_pending > 0 or not pending, f"期望 0 条但出现：{pending}"))
    h.check("标签贴自己的点且互不重叠", lambda: _labels_anchor_to_dots(h))
    h.check("股票视图轴说明", lambda: _mode_axis_captions(h))
    page.screenshot(path=str(out / "atlas-stock.png"), full_page=True)

    # —— 多次入选组：面板按最早记录展开（无多次入选的真实报告自动跳过该分支） ——
    if expect["multi_groups"]:
        group = expect["multi_groups"][0]
        code = group["code"]
        page.locator(f'[data-map-group="{code}"] .bubble-core').first.click()
        page.wait_for_timeout(250)
        panel = "#mapSelection"
        badge_text = expect["badge"](group)
        h.check("面板徽标文案", lambda: h.text_contains(panel, badge_text))
        anchor = group["records"][0]
        h.check("锚点为最早记录日期", lambda: h.text_contains(
            panel, anchor["recDate"].replace("-", ".")))
        if group["anchor_reason"] is None:
            h.check("最早基准收益=独立计算", lambda: h.text_contains(
                panel, pct_text(group["anchor_ret"])))
            h.check("交易日序号=独立计算", lambda: h.text_contains(
                panel, f"第 {group['anchor_day']} 个交易日"))
            h.check("报告日收盘=独立计算", lambda: h.text_contains(panel, str(group["close"])))
        latest = group["records"][-1]
        latest_point = group["points"][-1]
        if latest_point["reason"] is None and len(group["records"]) > 1:
            h.check("最新一轮单列收益=独立计算", lambda: h.expect(
                pct_text(latest_point["ret"]) in page.locator(".map-latest-block").inner_text(),
                "最新一轮块未含独立计算的收益"))
        h.check("入选明细条数", lambda: h.expect(
            page.locator(".map-episode").count() == len(group["records"]), "明细条数不一致"))
        h.check("各次原参考价可见", lambda: h.expect(
            all(str(s["ref"]) in page.locator(panel).inner_text() for s in group["records"]),
            "两次参考价都应可见"))
        # 第二次记录按原键打开详情，返回后恢复视图与选择
        episode_key = f"{code}:{latest['recDate']}"
        page.locator(f'.map-episode [data-open="{episode_key}"]').click()
        page.wait_for_timeout(300)
        st = page.evaluate("window.GUANLAN.getState()")
        h.check("打开的是该次记录键", lambda: h.expect(
            st["current"] == episode_key and st["page"] == "detail", f"实际 {st['current']}"))
        page.locator(".back-button").click()
        page.wait_for_timeout(300)
        st = page.evaluate("window.GUANLAN.getState()")
        h.check("返回恢复星图与选择", lambda: h.expect(
            st["page"] == "map" and st["mapMode"] == "stock" and st["mapGroup"] == code,
            f"实际 {st}"))
        page.screenshot(path=str(out / "atlas-panel.png"), full_page=True)

        # —— 记录视图：同股两点、标签带日期 ——
        page.locator('[data-map-mode="record"]').click()
        page.wait_for_timeout(250)
        stats = page.locator("#mapStats").inner_text()
        h.check("记录视图统计行=独立计算", lambda: h.expect(
            stats == expect["record_stats"], f"实际：{stats!r} 期望：{expect['record_stats']!r}"))
        expected_record_dots = sum(1 for g in expect["groups"] for p in g["points"]
                                   if p["reason"] is None)
        h.check("记录视图点数=可绘制记录数", lambda: h.expect(
            page.locator('#atlas [data-map-id]').count() == expected_record_dots,
            f"实际 {page.locator('#atlas [data-map-id]').count()} 期望 {expected_record_dots}"))
        labels = page.evaluate("document.getElementById('atlas').textContent")
        same_year = latest["recDate"][:4] == h.snapshot_analysis_date[:4]
        label_text = (latest["recDate"][5:].replace("-", "/") if same_year
                      else latest["recDate"].replace("-", "/"))
        h.check("同股两点标签带日期", lambda: h.expect(
            f"{group['name']} · " in labels and label_text in labels, f"标签缺失：{labels[:300]!r}"))
        h.check("记录视图轴说明", lambda: _mode_axis_captions(h))
        page.screenshot(path=str(out / "atlas-record.png"), full_page=True)
        page.locator(f'[data-map-id="{episode_key}"] .bubble-core').first.click()
        page.wait_for_timeout(250)
        h.check("记录视图选中该记录", lambda: h.expect(
            page.evaluate("window.GUANLAN.getState()")["mapCurrent"] == episode_key,
            "记录视图选择键不正确"))
        h.check("记录视图面板含阅读按钮", lambda: h.expect(
            page.locator(f'#mapSelection [data-open="{episode_key}"]').count() == 1,
            "面板缺少该次的复盘入口"))
        page.locator('[data-map-mode="stock"]').click()
        page.wait_for_timeout(250)
    else:
        print("  SKIP 多次入选面板检查（本报告无多次入选组；该场景由固定合成样本保证）")

    # —— 快照未被改写 ——
    def canon(text):
        # 两侧数字统一按 float 归一，消除 JS/Python 的 43 与 43.0 文本差异。
        return json.dumps(json.loads(text, parse_int=float), ensure_ascii=False, sort_keys=True)
    live_text = page.evaluate("JSON.stringify(window.GUANLAN.snapshot)")
    h.check("内嵌快照与原始一致", lambda: h.expect(
        canon(live_text) == canon(h.snapshot_raw), "快照被前端改写"))


def check_mobile(h: Harness, expect: dict, out: Path):
    page = h.page
    page.goto(h.url)
    page.locator('.nav-item[data-nav="map"]').click()
    page.wait_for_timeout(300)
    sel_box = page.locator("#mapSelection").bounding_box()
    svg_box = page.locator("#atlas").bounding_box()
    h.check("移动端面板显示在图下", lambda: h.expect(
        sel_box is not None and svg_box is not None and sel_box["y"] >= svg_box["y"] + svg_box["height"] - 5,
        f"面板 box={sel_box} 图 box={svg_box}"))
    dot = page.locator('[data-map-group] .bubble-core').first
    if dot.count():
        box = dot.bounding_box()
        page.touchscreen.tap(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        page.wait_for_timeout(300)
        plottable = [g for g in expect["groups"] if g["anchor_reason"] is None]
        if plottable:
            h.check("手机点按固定选中", lambda: h.text_contains(
                "#mapSelection", plottable[0]["name"]))
    else:
        print("  SKIP 手机点按（本报告没有可绘制点）")
    page.screenshot(path=str(out / "atlas-mobile.png"), full_page=True)


def check_synthetic(h: Harness, builder, out: Path):
    """固定合成回归样本（T08）：以下数字只与 synth_main() fixture 绑定。"""
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
    h.check("合成页股票视图轴说明", lambda: _mode_axis_captions(h))
    page.screenshot(path=str(out / "synthetic-stock.png"), full_page=True)
    page.locator('[data-map-mode="record"]').click()
    page.wait_for_timeout(250)
    h.check("合成页记录视图轴说明", lambda: _mode_axis_captions(h))
    page.screenshot(path=str(out / "synthetic-record.png"), full_page=True)

    empty = tmp / "empty.html"
    empty.write_text(builder.render_html(synth_snapshot([])), encoding="utf-8")
    page.goto(empty.as_uri())
    page.locator('.nav-item[data-nav="map"]').click()
    page.wait_for_timeout(250)
    h.check("空列表不崩溃", lambda: h.expect(
        page.locator("body").inner_text().find("暂无观察记录") >= 0, "空快照应显示如实空状态"))


def resolve_browser(playwright, explicit: str | None):
    """显式路径必须存在；缺省使用已安装的 Playwright Chromium。"""
    if explicit:
        path = Path(explicit)
        if not path.is_file():
            raise FileNotFoundError(f"--browser-executable 指定的浏览器不存在：{path}")
        return str(path)
    return None  # Playwright 自带的已安装 Chromium


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--html", required=True, help="真实报告 HTML 路径")
    parser.add_argument("--out", default=None, help="截图输出目录")
    parser.add_argument("--browser-executable", default=None,
                        help="可选浏览器可执行文件；缺省用已安装的 Playwright Chromium")
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
        print("playwright 未安装：.venv/bin/python -m pip install playwright && .venv/bin/python -m playwright install chromium")
        return 2

    errors: list[str] = []
    with sync_playwright() as p:
        try:
            executable = resolve_browser(p, args.browser_executable)
        except FileNotFoundError as exc:
            print(str(exc))
            return 2
        launch = {"headless": True}
        if executable:
            launch["executable_path"] = executable
        try:
            browser = p.chromium.launch(**launch)
        except Exception as exc:
            print(f"无法启动浏览器（executable={executable or 'playwright 内置 Chromium'}）：{exc}")
            return 2
        snapshot_raw = re.search(r'<script id="snapshot" type="application/json">(.*?)</script>',
                                 html_path.read_text(encoding="utf-8"), re.S).group(1)
        try:
            expect = atlas_expectations(json.loads(snapshot_raw))
        except Exception as exc:
            print(f"检查失败：无法从内嵌快照独立计算期望值（页面输入违反日期/数据合同）：{exc}")
            return 1
        desktop = browser.new_context(viewport={"width": 1440, "height": 1100}, device_scale_factor=1)
        page = desktop.new_page()
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}") if m.type == "error" else None)
        h = Harness(page, errors, "桌面")
        h.url = html_path.as_uri()
        h.snapshot_raw = snapshot_raw
        h.snapshot_analysis_date = json.loads(snapshot_raw)["analysis_date"]
        page.set_default_timeout(8000)
        print(f"报告：{html_path}")
        print("真实报告页检查：")
        page.goto(h.url)
        page.wait_for_timeout(400)
        check_real_report(h, expect, out)
        print("移动端检查：")
        mobile = browser.new_context(viewport={"width": 390, "height": 844},
                                     device_scale_factor=1, is_mobile=True, has_touch=True)
        mpage = mobile.new_page()
        mpage.on("pageerror", lambda e: errors.append(f"mobile pageerror: {e}"))
        mpage.on("console", lambda m: errors.append(f"mobile console.{m.type}: {m.text}") if m.type == "error" else None)
        hm = Harness(mpage, errors, "手机")
        hm.url = h.url
        check_mobile(hm, expect, out)
        print("合成数据页检查（固定回归样本）：")
        spage = desktop.new_page()
        spage.on("pageerror", lambda e: errors.append(f"synth pageerror: {e}"))
        spage.on("console", lambda m: errors.append(f"synth console.{m.type}: {m.text}") if m.type == "error" else None)
        hs = Harness(spage, errors, "合成")
        hs.url = h.url
        check_synthetic(hs, load_builder(), out)
        browser.close()

    if errors:
        for err in errors:
            print(f"JS/CONSOLE 错误：{err}")
    executed = sum(x.total for x in (h, hm, hs))
    code, failures = final_status([h, hm, hs], errors)
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
