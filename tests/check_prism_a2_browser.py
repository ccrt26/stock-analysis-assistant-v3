"""A.02 真实页面浏览器验收（验收表逐项实测）。

用法：
    ./.venv/bin/python tests/check_prism_a2_browser.py \
      --url http://127.0.0.1:8940/style-preview/prism-a2.html \
      --out /tmp/prism-a2-shots

覆盖：40/20/50 日窗口与每5日刻度、成交指标手工核对（量/额）、动效只随记录
切换播放、方向标签（up→上涨、未知→未识别状态）、原文对照弹窗、指数弹窗四
入口各自数据、缺失空态、320—1920 无页面级横向溢出、减少动效。备用页零写入由 tests/test_render_prism_web.py 负责；本脚本另验完整复盘、
公司资料、历史日期与收藏/搜索/星图，所有数量从本次快照读取。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILURES.append(name)


def expected_updates(snapshot):
    mapping = {"strengthening":"up", "continuation_possible":"up", "range_or_wait":"sideways",
               "weakening":"down", "overheated":"down", "invalidated":"down"}
    def direction(r):
        if "outlookDirection" in r:
            return r["outlookDirection"] if r["outlookDirection"] in ("up","down","sideways") else None
        return mapping.get(r.get("outlookCode"))
    count=0
    for stock in snapshot["stocks"]:
        rows=sorted((r for r in stock.get("reviews",[]) if r["date"]<=snapshot["analysis_date"]), key=lambda r:(r["date"],r.get("as_of","")))
        if not rows or rows[-1]["date"]!=snapshot["analysis_date"]:continue
        older=[r for r in rows if r["date"]<rows[-1]["date"]]
        if older and direction(older[-1]) and direction(rows[-1]) and direction(older[-1])!=direction(rows[-1]):count+=1
    return count


def original_paragraphs(value):
    return [p for p in re.split(r"\n\s*\n", value or "") if p]


def check_primary_details(pg, snapshot, out):
    check("主用身份已替换预览提示", "主用展示" in pg.locator("body").inner_text()
          and "非正式发布页" not in pg.locator("body").inner_text())
    stock=next(s for s in snapshot["stocks"] if s.get("companyIntroduction") and len(s.get("reviews",[]))>=2)
    key=stock["code"]+":"+stock["recDate"]
    pg.click('[data-nav="records"]')
    pg.click('[data-filter="all"]');pg.click('[data-filter="invalid"]')
    check("全部观察完整并集", pg.locator('tbody tr').count()==len(snapshot["stocks"]))
    pg.fill('#recordSearch',stock["code"])
    check("按代码搜索只显示对应股票", all(stock["code"] in t for t in pg.locator('tbody tr').all_text_contents()))
    pg.locator(f'tr[data-stock="{key}"]').click()
    pg.wait_for_timeout(400)
    check("清单点击打开新版个股详情", pg.locator('#detailDialog').evaluate('el=>el.open') and pg.locator('[data-detail-tab]').count()==5)
    last=sorted(stock['reviews'],key=lambda r:r['date'])[-1]
    pg.select_option('#detailDate',last['date']);pg.click('.stock-detail-nav [data-detail-tab="review"]')
    text=pg.locator('.full-review').text_content()
    check("完整复盘各段原文可读", all(p in text for p in original_paragraphs(last.get('copy') or last.get('summary_copy'))))
    if last.get('currentOpportunity'):
        op=last['currentOpportunity']
        check("当前机会按已保存对象展示",op['participationText'] in text and op['changeCondition'] in text)
    pg.screenshot(path=str(out/'a2-full-review.png'))
    pg.click('[data-detail-tab="original"]')
    text=pg.locator('.reading-body').text_content()
    expected=stock.get('statementFull') or stock.get('reasonFull')
    # Markdown 加粗是格式；实际文字、标点和数字仍逐段核对。
    check("原推荐理由完整保留", all(p.replace('**','') in text for p in original_paragraphs(expected)))
    if not stock.get('statementFull'):
        check("完整正文缺项明确可见",'尚缺完整推荐正文' in pg.locator('.reading-body').inner_text()
              and '非完整正文' in pg.locator('.original-summary summary').inner_text())
    pg.click('[data-detail-tab="company"]')
    intro=stock['companyIntroduction'];company_text=pg.locator('.reading-body').text_content()
    check("公司介绍完整段落及原截止可读",all(p in company_text for sec in intro['sections'] for p in sec['paragraphs'])
          and intro['as_of'][:16].replace('T',' ') in company_text)
    check("公司来源链接仅HTTP且新窗口隔离", pg.locator('.intro-sources a').evaluate_all("els=>els.every(e=>/^https?:/.test(e.href)&&e.rel.includes('noopener'))"))
    pg.screenshot(path=str(out/'a2-company.png'))
    historical=next(r for r in stock['reviews'] if r['date']<last['date'] and r['date'] in snapshot['sessionDates'])
    pg.select_option('#detailDate',historical['date'])
    check("切换历史日期不改变推荐时点公司资料",pg.locator('.reading-body').text_content()==company_text)
    pg.click('[data-detail-tab="review"]')
    check("历史复盘严格对应所选日期",pg.locator('.full-review').get_attribute('data-review-date-text')==historical['date']
          and all(p in pg.locator('.full-review').text_content() for p in original_paragraphs(historical.get('copy') or historical.get('summary_copy'))))
    pg.click('[data-detail-tab="chart"]')
    dates=pg.locator('#modalChart .candle').evaluate_all('els=>els.map(e=>e.dataset.date)')
    check("历史图表不展示所选日期之后价格",bool(dates) and max(dates)<=historical['date'])
    missing=next((d for d in snapshot['sessionDates'] if d>=stock['recDate'] and not any(r['date']==d for r in stock['reviews'])),None)
    if missing:
        pg.select_option('#detailDate',missing);pg.click('.stock-detail-nav [data-detail-tab="review"]')
        check("无当日复盘不冒用旧结论",'所选日期没有保存复盘正文' in pg.locator('.reading-body').text_content())
    pg.keyboard.press('Escape');pg.wait_for_timeout(400)
    check("详情关闭恢复滚动",pg.evaluate("document.body.style.overflow!=='hidden'"))
    # 收藏操作保持当前页，刷新后仍使用原来的 A2 存储键。
    star=pg.locator(f'[data-star="{key}"]');star.click()
    pg.click('[data-nav="favorites"]')
    check("收藏页显示该次入选",pg.locator(f'tr[data-stock="{key}"]').count()==1)
    pg.click('[data-sort="close"]')
    check("收藏页排序后仍留在收藏页",'我的收藏' in pg.locator('h1').inner_text())
    pg.reload(wait_until='networkidle');pg.click('[data-nav="favorites"]')
    check("页面刷新不丢失收藏",pg.locator(f'tr[data-stock="{key}"]').count()==1)
    pg.locator(f'[data-star="{key}"]').click()
    check("取消收藏即时移除且不跳出收藏页",pg.locator(f'tr[data-stock="{key}"]').count()==0 and '我的收藏' in pg.locator('h1').inner_text())
    pg.click('[data-nav="journal"]');pg.click('[data-journal-mode="all"]')
    pg.select_option('#journalDate',historical['date'])
    entry=pg.locator(f'.journal-entry [data-stock="{key}"]')
    entry.click();pg.wait_for_timeout(400)
    check("时间线回到这一天打开对应日期原文",pg.locator('#detailDate').input_value()==historical['date']
          and pg.locator('.full-review').get_attribute('data-review-date-text')==historical['date'])
    pg.keyboard.press('Escape');pg.wait_for_timeout(400)
    pg.click('[data-nav="map"]');pg.locator('.map-dot circle').first.click()
    pg.locator('[data-open]').first.click();pg.wait_for_timeout(400)
    check("星图阅读入口留在主用详情",pg.locator('#detailDialog').evaluate('el=>el.open') and pg.locator('.stock-detail-nav').count()==1)
    pg.keyboard.press('Escape');pg.wait_for_timeout(400)
    # Mobile long-form reading and table scrolling stay within the dialog.
    pg.set_viewport_size({'width':390,'height':850})
    pg.click('[data-nav="records"]');pg.click('[data-filter="all"]');pg.click('[data-filter="invalid"]')
    pg.fill('#recordSearch',stock['code']);pg.locator(f'tr[data-stock="{key}"]').click();pg.wait_for_timeout(400)
    pg.click('.stock-detail-nav [data-detail-tab="company"]')
    check("手机公司资料无页面横向溢出",pg.evaluate('document.documentElement.scrollWidth<=391'))
    pg.screenshot(path=str(out/'a2-company-mobile.png'))
    pg.keyboard.press('Escape');pg.wait_for_timeout(400);pg.set_viewport_size({'width':1440,'height':950})


def check_empty_snapshot(ctx, url, snapshot):
    pg=ctx.new_page();errors=[];pg.on('pageerror',lambda e:errors.append(str(e)))
    pg.goto(url,wait_until='networkidle');html=pg.content()
    empty={**snapshot,'stocks':[],'review_dates':[]}
    payload=json.dumps(empty,ensure_ascii=False).replace('<','\\u003c')
    html=re.sub(r'(<script[^>]+id="snapshot"[^>]*>).*?(</script>)',lambda m:m[1]+payload+m[2],html,count=1,flags=re.S)
    pg.goto('about:blank')
    pg.set_content(html,wait_until='load')
    for page in ('overview','records','journal','favorites','map'):
        pg.click(f'[data-nav="{page}"]')
    check("合法空名单所有导航可用",not errors,'; '.join(errors))
    pg.close()


def run(url: str, out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        pg = browser.new_page(viewport={"width": 1440, "height": 950}, device_scale_factor=2)
        errors: list[str] = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        pg.goto(url, wait_until="networkidle")
        pg.wait_for_timeout(900)

        snapshot = json.loads(pg.locator("#snapshot").text_content())

        # 1) 无脚本报错
        check("页面无脚本报错", not errors, "; ".join(errors[:3]))

        # 2) 窗口：主图40、卡片小图20、每5个交易日一个刻度（8个）
        slots = pg.eval_on_selector("#heroPlot", "el=>el.dataset.slots")
        check("主图窗口=40个交易日", slots == "40", f"slots={slots}")
        ticks = pg.eval_on_selector_all("#heroPlot .date-tick", "els=>els.length")
        check("主图每5日一标（8个刻度）", ticks == 8, f"ticks={ticks}")
        card_slots = pg.eval_on_selector(".stock-card .mini-chart", "el=>el.dataset.slots")
        check("清单小图窗口=20个交易日", card_slots == "20", f"slots={card_slots}")

        # 3) 短观察记录：待首日/新记录小图仍是最近20日且有可画历史
        short = pg.evaluate("""()=>{
          const cards=[...document.querySelectorAll('.stock-card')];
          const c=cards.find(x=>x.textContent.includes('待首日观察')||x.textContent.includes('已观察 1 天')||x.textContent.includes('已观察 2 天'));
          if(!c)return null;const s=c.querySelector('.mini-chart');
          return {label:c.querySelector('.card-foot span')?.textContent,slots:s?.dataset.slots,path:c.querySelectorAll('.mini-chart path').length};
        }""")
        check("短观察记录小图仍显示最近20日", bool(short and short["slots"] == "20" and short["path"] >= 1), json.dumps(short, ensure_ascii=False))

        # 4) 成交指标手工核对（2只股票 × 量/额），数据源=页面内嵌侧表
        series = json.loads(pg.eval_on_selector("#preview-series", "el=>el.textContent"))
        debug_data = pg.evaluate("(()=>{const d=window.PrismA2Debug.data();return d.focusKeys.flat()})()")
        checked = 0
        focus_keys = pg.evaluate("window.PrismA2Debug.data().focusKeys")
        for code in [keys[0].split(":")[0] for keys in focus_keys[:2]]:
            idx = next(i for i, keys in enumerate(
                pg.evaluate("window.PrismA2Debug.data().focusKeys")) if any(k.startswith(code) for k in keys))
            pg.select_option("#stockSelect", str(idx))
            pg.wait_for_timeout(500)
            rows = series["stocks"][code]["rows"]
            today, prev = rows[-1], rows[-2]
            base_rows = [r for r in rows[-6:-1] if r["volumeShares"] is not None]
            expect = {"today": today["volumeShares"] / 1e6, "prev": prev["volumeShares"] / 1e6,
                      "base": sum(r["volumeShares"] for r in base_rows) / len(base_rows) / 1e6}
            got = pg.evaluate("""()=>{
              const v=[...document.querySelectorAll('.activity-legend .value-line strong')].map(x=>parseFloat(x.textContent));
              return {today:v[0],prev:v[1],base:v[2]};
            }""")
            ok = all(abs(got[k] - expect[k]) < 0.02 for k in expect)
            check(f"{code} 成交量仪表读数（万手）", ok, f"got={got} expect={ {k: round(v,2) for k,v in expect.items()} }")
            pg.click('[data-metric="amountYuan"]')
            pg.wait_for_timeout(300)
            got_amt = pg.evaluate("()=>parseFloat(document.querySelectorAll('.activity-legend .value-line strong')[0].textContent)")
            ok_amt = abs(got_amt - today["amountYuan"] / 1e8) < 0.02
            check(f"{code} 成交额仪表读数（亿元）", ok_amt, f"got={got_amt} expect={today['amountYuan']/1e8:.2f}")
            pg.click('[data-metric="volumeShares"]')
            pg.wait_for_timeout(300)
            checked += 1
        check("成交指标核对≥2只股票", checked >= 2, f"checked={checked}")

        # 5) 方向口径：合法方向显示上涨；未知不猜成横盘
        dir_check = pg.evaluate("""(()=>{
          const D=window.PrismA2Debug.viewModel;
          const label=r=>{const d=D.direction(r);return d?D.dirLabels[d]:'未识别状态'};
          return {up:label({outlookDirection:'up'}),unknown:label({outlookDirection:'future_new_enum'}),
                  current:document.querySelector('.chart-note .note-tags .tag:last-of-type')?.textContent};
        })()""")
        check("up→上涨、未知→未识别状态", dir_check["up"] == "上涨" and dir_check["unknown"] == "未识别状态"
              and "横盘" not in dir_check["unknown"], json.dumps(dir_check, ensure_ascii=False))

        # 6) 判断节点 → 原文弹窗（相邻对照）
        pg.click(".review-node >> nth=0")
        pg.wait_for_timeout(500)
        reading = pg.evaluate("""()=>{const d=document.getElementById('detailDialog');
          return {open:d.open,text:d.textContent.includes('这一次'),hasDate:!!d.querySelector('.reading-body h3')};}""")
        check("判断节点打开原复盘弹窗", reading["open"] and reading["text"] and reading["hasDate"])
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(400)

        # 7) 动效规则：每次换记录恰好 +1；同记录/缩放/切模式 +0
        anim0 = pg.evaluate("window.PrismA2Debug.state().focusAnimations")
        pg.click("#nextFocus"); pg.wait_for_timeout(500)
        anim1 = pg.evaluate("window.PrismA2Debug.state().focusAnimations")
        pg.click("#prevFocus"); pg.wait_for_timeout(500)
        anim2 = pg.evaluate("window.PrismA2Debug.state().focusAnimations")
        pg.select_option("#stockSelect", str(pg.evaluate("document.getElementById('stockSelect').selectedIndex")))
        pg.wait_for_timeout(300)
        anim3 = pg.evaluate("window.PrismA2Debug.state().focusAnimations")
        pg.set_viewport_size({"width": 1500, "height": 950}); pg.wait_for_timeout(400)
        pg.click('[data-chart-mode="candle"]'); pg.wait_for_timeout(400)
        anim4 = pg.evaluate("window.PrismA2Debug.state().focusAnimations")
        check("动效：换记录恰好+1（A→B→A）", anim1 - anim0 == 1 and anim2 - anim1 == 1, f"{anim0}→{anim1}→{anim2}")
        check("动效：同记录/缩放/切模式不重播", anim3 == anim2 and anim4 == anim3, f"{anim2},{anim3},{anim4}")
        pg.click('[data-chart-mode="line"]'); pg.wait_for_timeout(300)

        # 8) K线读数：40根蜡烛、3条均线、OHLC 栏收盘与侧表一致
        pg.click('[data-chart-mode="candle"]'); pg.wait_for_timeout(400)
        candles = pg.evaluate("document.querySelectorAll('#heroPlot .candle').length")
        mas = pg.evaluate("document.querySelectorAll('#heroPlot .price-trace').length")
        last_close = pg.evaluate("""()=>{
          const D=window.PrismA2Debug.viewModel,S=window.PrismA2Debug.state();
          const item=D.deep[S.focus].records[S.record]||D.deep[S.focus].records[0];
          return D.history(item).at(-1).close;
        }""")
        readout_close = pg.evaluate("""()=>{
          const ems=[...document.querySelectorAll('#heroPlot .ohlc-readout em')].map(x=>parseFloat(x.textContent));
          return ems[3]??null;
        }""")
        check("K线：40根蜡烛+MA5/10/20", candles == 40 and mas == 3, f"candles={candles} ma={mas}")
        check("K线：OHLC 栏最新收盘与侧表一致", readout_close is not None and abs(readout_close - last_close) < 0.005,
              f"readout={readout_close} close={last_close}")
        pg.click('[data-chart-mode="line"]'); pg.wait_for_timeout(300)

        # 9) 清单与观点更新：纵向两排、更新桌面3卡/横滚可到末尾
        order_ok = pg.evaluate("""()=>{
          const a=document.getElementById('stockRail').getBoundingClientRect().top;
          const b=document.getElementById('updatesRail').getBoundingClientRect().top;
          return b>a;
        }""")
        cols = pg.evaluate("""()=>{
          const rail=document.getElementById('updatesRail'),card=rail.querySelector('.update-card');
          const visible=Math.round(rail.clientWidth/(card.getBoundingClientRect().width+14));
          return visible;
        }""")
        upd_count = pg.eval_on_selector_all(".update-card", "els=>els.length")
        check("观点更新位于清单下一排", order_ok)
        check("观点更新桌面3卡", cols == 3, f"visible={cols}")
        check("观点更新条数=源数据（不截断）", upd_count == expected_updates(snapshot), f"{upd_count}")
        pg.eval_on_selector("#updatesRail", "el=>el.scrollLeft=el.scrollWidth")
        pg.wait_for_timeout(300)
        readout = pg.eval_on_selector("#updatesPosition", "el=>el.textContent")
        check("观点更新可滚到末尾", f"{upd_count} / {upd_count}" in readout, readout)

        # 10) 指数弹窗：四入口各自数据；打开/关闭/焦点恢复
        names = pg.evaluate("[...document.querySelectorAll('.market-card .market-name')].map(x=>x.textContent.trim())")
        ok_all = True
        detail = ""
        for i in range(4):
            pg.focus(f".market-card >> nth={i}")
            pg.click(f".market-card >> nth={i}")
            pg.wait_for_timeout(700)
            info = pg.evaluate("""()=>{
              const d=document.getElementById('detailDialog');
              return {open:d.open,title:d.querySelector('h2')?.textContent,code:d.querySelector('h2 small')?.textContent,
                      slots:document.getElementById('modalChart').dataset.slots,
                      candles:document.querySelectorAll('#modalChart .candle').length};
            }""")
            expected_code = ["000001.SH", "399001.SZ", "399006.SZ", "000688.SH"][i]
            ok = (info["open"] and expected_code in info["code"] and info["slots"] == "50"
                  and info["candles"] == 50)
            ok_all = ok_all and ok
            detail += f"{names[i]}:{'ok' if ok else json.dumps(info, ensure_ascii=False)} "
            if i == 0:
                pg.screenshot(path=str(out / "a2-index-modal.png"))
            pg.keyboard.press("Escape")
            pg.wait_for_timeout(400)
        check("指数弹窗：四入口各自50日K线", ok_all, detail)
        focus_back = pg.evaluate("document.activeElement?.classList?.contains('market-card')")
        check("弹窗关闭后焦点回到指数卡", focus_back)

        # 11) 缺失空态：退出交互后 tooltip 归位、无演示填充
        demo_label = pg.eval_on_selector("#demoLabel", "el=>el.textContent")
        check("真实数据标注（非演示）", "合成" not in demo_label and "冻结快照" in demo_label, demo_label)

        check_primary_details(pg, snapshot, out)
        check("全部交互后无脚本报错", not errors, "; ".join(errors[:5]))
        pg.click('[data-nav="overview"]')
        pg.screenshot(path=str(out / "a2-desktop-top.png"))
        pg.screenshot(path=str(out / "a2-desktop-full.png"), full_page=True)
        browser.close()

    # 12) 响应式：320/390/768/1440/1920 无页面级横向溢出
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for w in (320, 390, 768, 1440, 1920):
            pg = browser.new_page(viewport={"width": w, "height": 900})
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.goto(url, wait_until="networkidle")
            pg.wait_for_timeout(600)
            sw = pg.evaluate("document.documentElement.scrollWidth")
            check(f"{w}px 无页面级横向溢出", sw <= w + 1, f"scrollWidth={sw}")
            if w == 390:
                pg.screenshot(path=str(out / "a2-mobile-390.png"), full_page=True)
            pg.close()
        # 13) 减少动效：系统设置生效且不影响读图
        ctx = browser.new_context(viewport={"width": 1440, "height": 950}, reduced_motion="reduce")
        pg = ctx.new_page()
        pg.goto(url, wait_until="networkidle")
        pg.wait_for_timeout(600)
        state = pg.evaluate("window.PrismA2Debug.state()")
        btn = pg.eval_on_selector("#motionToggle", "el=>el.textContent")
        hero = pg.eval_on_selector("#heroPlot", "el=>el.dataset.slots")
        check("减少动效：开关禁用+图表终态可用", state["motion"] is False and "系统" in btn and hero == "40",
              f"btn={btn} slots={hero}")
        check_empty_snapshot(ctx, url, snapshot)
        check("手机与减少动效检查无脚本报错", not errors, "; ".join(errors[:5]))
        ctx.close()
        browser.close()

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} 项：{FAILURES}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8940/style-preview/prism-a2.html")
    parser.add_argument("--out", default="/tmp/prism-a2-shots")
    args = parser.parse_args()
    sys.exit(run(args.url, Path(args.out)))
