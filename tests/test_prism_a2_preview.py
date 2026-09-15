"""A2 主用渲染测试：使用独立样例，不读取或写入本地正式归档。"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
A2 = ROOT / "tools" / "guanlan-prism" / "concept-a" / "a2"
sys.path.insert(0, str(ROOT / "tools" / "guanlan-prism" / "tools"))
import build_preview_a2


@pytest.fixture
def snapshot():
    return {"analysis_date": "2026-09-10", "as_of": "2026-09-10T18:30:00+08:00",
            "sessionDates": ["2026-09-09", "2026-09-10"], "dates": ["09-09", "09-10"],
            "market": [3000., 3001.], "review_dates": [], "stocks": [
                {"code": "000001.SZ", "name": "测试股份", "recDate": "2026-09-09",
                 "candles": [[10., 12., 9., 11., .11], [11., 13., 10., 12., .12]], "reviews": []}],
            "presentation": {"marketCodes": ["000001.SH"]},
            "marketIndices": [{"code": "000001.SH", "trade_date": "2026-09-10",
                               "close": 3001., "series": [3000., 3001.]}]}


@pytest.fixture
def series(snapshot):
    return {"schemaVersion": 1, "analysis_date": snapshot["analysis_date"],
            "sessionDates": snapshot["sessionDates"],
            "stocks": {"000001.SZ": {"priceBasis": "raw_unadjusted", "rows": [
                {"date": d, "close": c, "volumeShares": 1000000., "amountYuan": c*1000000.}
                for d,c in zip(snapshot["sessionDates"],[11.,12.])]}},
            "indices": {"000001.SH": {"rows": [
                {"date": d, "close": c} for d,c in zip(snapshot["sessionDates"],[3000.,3001.])]}}}


def node_eval(script):
    proc = subprocess.run(["node", "-e", script], capture_output=True, text=True, cwd=ROOT)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return proc.stdout.strip()


def test_series_assembly_keeps_units_cutoff_and_unique_stock_rows(snapshot):
    calls = []
    def read(root, table, day, cutoff):
        calls.append((table, day, cutoff))
        close = (11. if table == "equity_daily" else 3000.) + (day.day-9)
        return pd.DataFrame([{("ts_code" if table == "equity_daily" else "index_code"):
                             "000001.SZ" if table == "equity_daily" else "000001.SH",
                             "open": close, "high": close, "low": close, "close": close,
                             "volume": 1000000., "amount": close*1000000.}])
    rmw = SimpleNamespace(list_sessions=lambda *a:[date(2026,9,9),date(2026,9,10)],
                          _as_utc_cutoff=lambda value:value, _read_day_frames=read)
    snapshot["stocks"].append(dict(snapshot["stocks"][0], recDate="2026-09-10"))
    out = build_preview_a2.assemble_series(Path("unused"), rmw, snapshot)
    assert len(out["stocks"]["000001.SZ"]["rows"]) == 2
    assert out["stocks"]["000001.SZ"]["rows"][-1]["volumeShares"] == 1000000.
    assert out["stocks"]["000001.SZ"]["rows"][-1]["amountYuan"] == 12000000.
    assert all(cutoff == datetime.fromisoformat(snapshot["as_of"]) for _,_,cutoff in calls)
    assert all(day <= date(2026,9,10) for _,day,_ in calls)


@pytest.mark.parametrize("kind,code", [("stocks","000001.SZ"),("indices","000001.SH")])
def test_series_conflict_raises(snapshot, series, kind, code):
    series[kind][code]["rows"][-1]["close"] += 1
    with pytest.raises(ValueError, match="冲突"):
        build_preview_a2.render_html(snapshot, series)


def test_render_embeds_snapshot_verbatim_and_replaces_template_only_once(snapshot, series):
    snapshot["stocks"][0]["reasonFull"] = '</script><b>原文</b> /*__MATH__*/ /*__SERIES__*/'
    html = build_preview_a2.render_html(snapshot, series)
    payload = json.loads(html.split('<script id="snapshot" type="application/json">')[1].split('</script>')[0])
    assert payload == snapshot
    assert '<b>原文</b>' not in html
    assert '/*__MATH__*/' in payload["stocks"][0]["reasonFull"]
    for token in ('atlasData','drawAtlas','side-nav','观察星图','GuanlanA2Rules','公司资料','完整复盘','主用展示','停更备用'):
        assert token in html
    for retired in ('非正式发布页','样式评审稿','样式预览页不含个股详情'):
        assert retired not in html


def test_invalid_calendar_or_nonfinite_input_cannot_render(snapshot):
    snapshot['sessionDates'].reverse()
    with pytest.raises(ValueError):
        build_preview_a2.render_html(snapshot)
    snapshot['sessionDates'].reverse()
    snapshot['market'][0] = float('nan')
    with pytest.raises(ValueError):
        build_preview_a2.render_html(snapshot)


def test_old_a2_command_delegates_to_formal_sync(monkeypatch):
    tools_dir = str(ROOT / "tools")
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    import render_prism_web
    calls=[]
    monkeypatch.setattr(render_prism_web,'main',lambda args:calls.append(args) or 0)
    args=['--date','2026-09-10','--action-date','2026-09-11','--as-of','2026-09-10T18:30:00+08:00']
    assert build_preview_a2.main(args)==0
    assert calls==[args]


def test_direction_mapping_up_and_unknown() -> None:
    """指令点名的修复验证：合法方向显示上涨；未知不猜成横盘。"""
    script = f"""
const R=require('{ROOT / "tools/guanlan-prism/src/rules.js"}');
const assert=require('assert');
assert.equal(R.direction({{outlookDirection:'up'}}),'up');
assert.equal(R.DIRECTION_LABELS.up,'上涨');
assert.equal(R.direction({{outlookDirection:'future_new_enum'}}),null);
assert.equal(R.direction({{outlookCode:'weird_code'}}),null);
const label=r=>{{const d=R.direction(r);return d?R.DIRECTION_LABELS[d]:'未识别状态'}};
assert.equal(label({{outlookDirection:'up'}}),'上涨');
assert.equal(label({{outlookDirection:'future_new_enum'}}),'未识别状态');
assert.notEqual(label({{outlookDirection:'future_new_enum'}}),'横盘');
console.log('ok');
"""
    assert node_eval(script) == "ok"


def test_activity_math_excludes_today() -> None:
    script = f"""
const M=require('{A2 / "display-math.js"}');
const assert=require('assert');
const rows=[
 {{date:'2026-09-01',volumeShares:100}},{{date:'2026-09-02',volumeShares:200}},
 {{date:'2026-09-03',volumeShares:300}},{{date:'2026-09-04',volumeShares:400}},
 {{date:'2026-09-07',volumeShares:500}},{{date:'2026-09-08',volumeShares:null}},
 {{date:'2026-09-09',volumeShares:600}},{{date:'2026-09-10',volumeShares:1200}}];
const a=M.activity(rows,5,'volumeShares');
assert.equal(a.today,1200);
assert.equal(a.previous,600);
assert.equal(a.base,(300+400+500+600)/4);   // 窗口=T-5..T-1，不含今天；null 不计入；有效 4/5
assert.equal(a.n,4);
assert.equal(a.ratio,1200/a.base);
const empty=M.activity([{{date:'2026-09-10'}}],5,'volumeShares');
assert.equal(empty.today,null);assert.equal(empty.base,null);assert.equal(empty.ratio,null);
// 量额不混用：amountYuan 独立读取
const b=M.activity(rows.slice(-2).map(r=>({{date:r.date,amountYuan:5e8}})),5,'amountYuan');
assert.equal(b.today,5e8);
// 保形插值：分段端点等于原始点
const seg=M.monotoneSegments([[0,0],[1,2],[2,1]]);
assert.deepEqual(seg[0][0],[0,0]);assert.deepEqual(seg[0][3],[1,2]);assert.deepEqual(seg.at(-1)[3],[2,1]);
console.log('ok');
"""
    assert node_eval(script) == "ok"


def test_original_body_separates_missing_summary_and_preserves_adopted_identity():
    source = (A2 / 'overview.js').read_text()
    functions = source[source.index('const paragraphs='):source.index('function fullReview')]
    script = "const esc=v=>String(v??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));\n" + functions
    result = json.loads(node_eval(script + '\nconsole.log(JSON.stringify(['
        'originalBody({reasonFull:"历史摘要",reasonRisk:"原风险"}),'
        'originalBody({statementFull:"**判断**\\n\\n正文<script>alert(1)</script>",statementSource:"adopted_rewrite",reasonFull:"不应混入正文的摘要"})]));'))
    missing, adopted = result
    assert '尚缺完整推荐正文' in missing
    assert '<summary>查看历史记录摘要（非完整正文）</summary>' in missing
    assert '历史摘要' in missing and '原风险' in missing
    assert '<strong>判断</strong>' in adopted
    assert '&lt;script&gt;' in adopted and '<script>' not in adopted
    assert '用户认可的表达范本' in adopted
    assert '不应混入正文的摘要' not in adopted


def test_assemble_series_builds_theme_comparisons() -> None:
    """携带 industryCode（非申万目录代码）的记录生成主题对照侧表；
    申万代码不进 comparisons；close 来自真实 theme_daily 且与 80 日窗对齐。"""
    from tools import render_monitor_web as rmw

    sessions = ["2026-09-07", "2026-09-08", "2026-09-09", "2026-09-10", "2026-09-11"]
    snap = {"analysis_date": "2026-09-11", "as_of": "2026-09-13T18:30:00+08:00",
            "sessionDates": sessions, "dates": [d[5:] for d in sessions],
            "market": [3000.] * len(sessions),
            "stocks": [
                {"code": "TEST1.SZ", "name": "主题对照样例", "recDate": "2026-09-10",
                 "industryCode": "399971.SZ", "industry": [None] * len(sessions),
                 "candles": [None] * len(sessions), "reviews": []},
                {"code": "TEST2.SH", "name": "申万对照样例", "recDate": "2026-09-10",
                 "industryCode": "801760.SI", "industry": [None] * len(sessions),
                 "candles": [None] * len(sessions), "reviews": []}],
            "presentation": {"marketCodes": ["000001.SH"]}}
    series = build_preview_a2.assemble_series(ROOT, rmw, snap)
    assert "399971.SZ" in series["comparisons"]
    assert "801760.SI" not in series["comparisons"]  # 申万代码走既有行业路径
    theme = series["comparisons"]["399971.SZ"]
    assert theme["source"].startswith("本地事实仓 theme_daily")
    dates = [r["date"] for r in theme["rows"]]
    assert len(dates) == 80 and dates[-1] == "2026-09-11"  # assemble 固定 80 日窗
    assert all(r["close"] is not None and r["close"] > 0 for r in theme["rows"])
    last40 = [r for r in theme["rows"] if r["date"] >= "2026-07-20"]
    assert len(last40) == 40 and all(r["close"] is not None for r in last40)


def test_series_theme_conflict_against_snapshot_industry_raises() -> None:
    from tools import render_monitor_web as rmw

    snap = {"analysis_date": "2026-09-11", "as_of": "2026-09-13T18:30:00+08:00",
            "sessionDates": [], "dates": [], "market": [],
            "stocks": [{"code": "TEST1.SZ", "name": "主题对照样例", "recDate": "2026-09-10",
                        "industryCode": "399971.SZ", "industry": [],
                        "candles": [], "reviews": []}],
            "presentation": {"marketCodes": []}}
    series = build_preview_a2.assemble_series(ROOT, rmw, snap)
    # 用真实主题收盘回填记录原窗口（一致 → 组装不报冲突）
    snap["sessionDates"] = series["sessionDates"][-2:]
    snap["stocks"][0]["industry"] = [
        r["close"] for r in series["comparisons"]["399971.SZ"]["rows"][-2:]]
    snap["candles"] = [[None] * 5 for _ in snap["sessionDates"]]
    series2 = build_preview_a2.assemble_series(ROOT, rmw, snap)  # 一致：不报冲突
    assert series2["comparisons"]["399971.SZ"]["rows"][-1]["close"] ==         snap["stocks"][0]["industry"][-1]
    series2["comparisons"]["399971.SZ"]["rows"][-1]["close"] += 5.0
    with pytest.raises(ValueError, match="冲突"):
        build_preview_a2.check_series_against_snapshot(snap, series2)


def test_comparison_merges_theme_supplement_by_industry_code() -> None:
    """H/E/F/G：comparison() 按 industryCode 取主题补充序列并按各自 recDate 归一；
    原快照窗口含 null 原样保留（不被补充覆盖）；基准缺失整条为空；
    旧对象缺 industryCode 时仍走原 extra.stocks 兜底。"""
    script = """
const M=require('%(math)s');
globalThis.PrismMath=M;
require('%(access)s');
const assert=require('assert');
const rules={key:s=>s.code+':'+s.recDate,direction:()=>null,dirLabels:{up:'上涨',sideways:'横盘',down:'下跌'},
 deepReviews:()=>({groups:[]}),orderedReviews:()=>[],latest:()=>null,opinionLabel:()=>'尚未复盘',
 isInvalid:()=>false,returnOnDate:()=>null,daysAt:()=>0,recommendations:(d)=>d.stocks,
 directionUpdates:()=>[]};
const orig=['2026-08-31','2026-09-01','2026-09-02','2026-09-03','2026-09-04'];
const mk=(code,name,recDate,industry,industryCode)=>({code,name,recDate,recIndex:orig.indexOf(recDate),
 ref:10,industry,industryCode,candles:[],reviews:[]});
const data={analysis_date:'2026-09-04',sessionDates:orig,
 dates:orig,market:[100,100,100,100,100],market_name:'上证指数',
 presentation:{marketCodes:['000001.SH']},
 stocks:[mk('A.SZ','甲','2026-09-02',[null,100,105,null,102],'399971.SZ'),
         mk('B.SH','乙','2026-09-02',[null,200,210,null,204],'000122.SH'),
         mk('C.SZ','丙','2026-09-02',[null,50,52,null,51],null),
         mk('D.SZ','丁','2026-08-31',[null,1,2,3,4],'399971.SZ')]};
const rows399971=[['2026-08-27',8],['2026-08-28',9],['2026-08-31',10],['2026-09-01',11],
 ['2026-09-02',20],['2026-09-03',21],['2026-09-04',19]].map(([date,close])=>({date,close}));
const rows000122=[['2026-08-27',80],['2026-08-28',90],['2026-08-31',100],['2026-09-01',110],
 ['2026-09-02',200],['2026-09-03',210],['2026-09-04',190]].map(([date,close])=>({date,close}));
const extra={sessionDates:['2026-08-27','2026-08-28'],
 comparisons:{'399971.SZ':{source:'t',rows:rows399971},'000122.SH':{source:'t',rows:rows000122}},
 stocks:{'C.SZ':{industry:[{date:'2026-08-27',close:5},{date:'2026-08-28',close:6}]}}};
const D=PrismData.create(data,extra,rules);
const A=D.comparison(data.stocks[0],'industry');
// 合并会话：08-27,08-28,08-31,09-01..09-04；基准=09-02 的 105
const expect=[8/105*100,9/105*100,null,100/105*100,100,null,102/105*100];
A.forEach((v,i)=>{ if(expect[i]===null)assert.equal(v,null);
  else assert.ok(Math.abs(v-expect[i])<1e-9, i+' '+v); });
assert.equal(A[2],null);      // 原窗口 null 不被补充覆盖
assert.ok(A[0]!==null);       // 原日历之外用主题补充序列
// E：另一记录用另一主题代码，各自归一，不串
const B=D.comparison(data.stocks[1],'industry');
assert.ok(Math.abs(B[0]-80/210*100)<1e-9 && Math.abs(B[6]-204/210*100)<1e-9);
// F：基准日（recDate）行业值为 null → 整条为空
const Dd=D.comparison(data.stocks[3],'industry');
assert.ok(Dd.every(v=>v===null));
// G：旧对象缺 industryCode → 原窗口外走 extra.stocks 兜底
const Cc=D.comparison(data.stocks[2],'industry');
assert.equal(Cc[0],5/52*100);assert.equal(Cc[1],6/52*100);assert.equal(Cc[2],null);
console.log('ok');
""".replace("%(math)s", str(A2 / "display-math.js")).replace("%(access)s", str(A2 / "data-access.js"))
    assert node_eval(script) == "ok"
