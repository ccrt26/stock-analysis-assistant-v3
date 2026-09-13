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
