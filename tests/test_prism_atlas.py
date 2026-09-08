"""观察星图同股合并的规则测试：通过 Node 调用 rules.js 星图纯函数。

覆盖《GLM5.3_星图同股合并执行指令.md》第六节中可在纯函数层验证的验收项：
同股不同基准、倒置输入、再次入选不重置、重复身份、状态独立、事件类型、
缺参考价、缺当日行情、同日价格副本复用、待首日、超20日跨度、轴范围与
“本报告最早记录”口径。原始 stocks 不被改写也在本层断言。
"""

from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RULES_JS = PROJECT_ROOT / "tools" / "guanlan-prism" / "src" / "rules.js"

DATES = [  # 与真实快照同构：同一自然年的 MM-DD 交易日序列（含周末跳过）
    "08-03", "08-04", "08-05", "08-06", "08-07", "08-10", "08-11", "08-12",
    "08-13", "08-14", "08-17", "08-18", "08-19", "08-20", "08-21", "08-24",
    "08-25", "08-26", "08-27", "08-28", "08-31", "09-01", "09-02", "09-03",
    "09-04", "09-07",
]


def candle(open_, close, amount=1.0):
    return [open_, max(open_, close), min(open_, close), close, amount]


def make_snapshot(stocks, last_close_by_code=None):
    """构造最小合法快照；默认给每只股票填一条到报告日的价格序列。"""
    filled = []
    for s in stocks:
        s = dict(s)
        if "candles" not in s:
            rec = s.get("recIndex", 0)
            close = last_close_by_code.get(s["code"], 84.0) if last_close_by_code else 84.0
            # 推荐日前只有历史价；报告日（最后一格）必须有真实收盘。
            seq = [candle(10 + i * 0.1, 10 + i * 0.1) for i in range(rec)]
            seq += [None] * (len(DATES) - 1 - rec)
            seq.append(candle(close, close, 4.2))
            s["candles"] = seq
        s.setdefault("reviews", [])
        s.setdefault("events", [])
        s.setdefault("d0", None)
        s.setdefault("refKind", "normal")
        s.setdefault("invalidated", None)
        s.setdefault("stage", "观察中")
        filled.append(s)
    return {
        "analysis_date": "2026-09-07",
        "as_of": "2026-09-07T18:30:00+08:00",
        "market_name": "上证指数",
        "dates": DATES,
        "market": [3000.0 + i for i in range(len(DATES))],
        "review_dates": ["2026-09-07"],
        "stocks": filled,
    }


def stock(code, name, rec_date, ref, rec_index, days, **kw):
    base = {"code": code, "name": name, "recDate": rec_date, "ref": ref,
            "recIndex": rec_index, "days": days}
    base.update(kw)
    return base


def run_node(snapshot, expr):
    """在 Node 里 require rules.js 后执行 expr(R, snapshot)，返回 JSON 结果。"""
    script = (
        "const R=require(process.argv[1]);const d=JSON.parse(process.argv[2]);"
        "const out=eval(process.argv[3])(R,d);"
        "process.stdout.write(JSON.stringify(out));"
    )
    proc = subprocess.run(
        ["node", "-e", script, str(RULES_JS), json.dumps(snapshot), expr],
        capture_output=True, text=True, timeout=60,
    )
    if proc.returncode != 0:
        raise AssertionError(f"node failed:\n{proc.stderr}")
    return json.loads(proc.stdout)


def atlas_of(snapshot):
    return run_node(snapshot, """(R,d)=>({
  groups:R.atlasGroups(d).map(g=>({code:g.code,name:g.name,
    records:g.records.map(s=>R.key(s)),
    badge:R.atlasBadge(g),
    basis:R.atlasBasis(g,d)})),
  record:R.atlasGroups(d).flatMap(g=>g.records.map(s=>({key:R.key(s),
    point:R.atlasRecordPoint(s,g,d)}))),
  range:R.atlasRange(
    R.atlasGroups(d).map(g=>R.atlasBasis(g,d)),
    R.atlasGroups(d).flatMap(g=>g.records.map(s=>R.atlasRecordPoint(s,g,d)))),
  stocksStill:JSON.stringify(d.stocks),
})""")


def test_atlas_rules_contract():
    """总合同：同股两次基准不同时的分组、锚点、次数与两种视图坐标。"""
    snap = make_snapshot(
        stocks=[
            # 输入顺序倒置：较晚的 09-03 在前，与 2026-09-07 真实快照一致。
            stock("600150.SH", "中国船舶", "2026-09-03", 34.1, 23, 3, refKind="event"),
            stock("600150.SH", "中国船舶", "2026-08-31", 34.8, 20, 6, refKind="event"),
        ],
        last_close_by_code={"600150.SH": 38.38},
    )
    a = atlas_of(snap)
    g = a["groups"][0]
    assert g["code"] == "600150.SH"
    # 分组按代码；组内按推荐日期升序，最早记录是锚点（不是输入顺序）。
    assert g["records"] == ["600150.SH:2026-08-31", "600150.SH:2026-09-03"]
    assert g["basis"]["anchor"]["recDate"] == "2026-08-31"
    assert g["basis"]["plottable"] is True
    # X=交易日序号 25-20+1=6（与该记录原 days=6 一致）；Y=38.38/34.8-1。
    assert g["basis"]["day"] == 6
    assert g["basis"]["ret"] == pytest.approx((38.38 / 34.8 - 1) * 100, abs=1e-9)
    # 徽标：两条都是事件条件 → 条件观察，不是两次正式推荐。
    assert g["badge"]["count"] == 2
    assert g["badge"]["short"] == "入选 2 次"
    assert g["badge"]["full"] == "入选 2 次 · 条件观察"
    # 记录视图：每个点用自己的参考价，同一报告日收盘。
    rets = {x["key"]: x["point"]["ret"] for x in a["record"]}
    assert rets["600150.SH:2026-08-31"] == pytest.approx((38.38 / 34.8 - 1) * 100, abs=1e-9)
    assert rets["600150.SH:2026-09-03"] == pytest.approx((38.38 / 34.1 - 1) * 100, abs=1e-9)
    assert {x["point"]["day"] for x in a["record"]} == {6, 3}
    # 原始 stocks 数组原样保留（顺序与内容）。
    assert json.loads(a["stocksStill"])[0]["recDate"] == "2026-09-03"
    # 两种模式共用轴范围，且明确“本报告最早记录”口径。
    assert a["range"]["basis"] == "本报告最早记录"


def test_first_and_latest_not_averaged():
    """首次100、第二次80、当日84：主点-16%，最新一轮+5%，两者不平均。"""
    snap = make_snapshot(
        stocks=[
            stock("000001.SZ", "甲", "2026-09-03", 80.0, 23, 3),
            stock("000001.SZ", "甲", "2026-09-01", 100.0, 21, 5),
        ],
        last_close_by_code={"000001.SZ": 84.0},
    )
    a = atlas_of(snap)
    g = a["groups"][0]
    assert g["basis"]["ret"] == pytest.approx(-16.0)
    rets = sorted(x["point"]["ret"] for x in a["record"])
    assert rets == pytest.approx([-16.0, 5.0])
    assert -5.5 not in rets  # 平均值不得出现
    assert g["badge"]["full"] == "入选 2 次"


def test_anchor_stable_under_reorder_and_third_selection():
    """倒置输入、切换排序、增加第三次入选：锚点 X/Y 不变，仅次数更新。"""
    two = make_snapshot(
        stocks=[
            stock("000002.SZ", "乙", "2026-09-03", 20.0, 23, 3),
            stock("000002.SZ", "乙", "2026-08-26", 25.0, 16, 12),
        ],
        last_close_by_code={"000002.SZ": 22.0},
    )
    three = make_snapshot(
        stocks=[
            stock("000002.SZ", "乙", "2026-09-07", 23.0, 25, 1),
            stock("000002.SZ", "乙", "2026-09-03", 20.0, 23, 3),
            stock("000002.SZ", "乙", "2026-08-26", 25.0, 16, 12),
        ],
        last_close_by_code={"000002.SZ": 22.0},
    )
    a2, a3 = atlas_of(two), atlas_of(three)
    b2, b3 = a2["groups"][0]["basis"], a3["groups"][0]["basis"]
    assert b2["ret"] == pytest.approx(b3["ret"])
    assert b2["day"] == b3["day"] == 25 - 16 + 1  # 跨记录观察跨度可以大于 20
    assert a3["groups"][0]["badge"]["count"] == 3


def test_duplicate_identity_not_counted_again():
    """同一独立记录重复载入不累计次数；每天复盘也不计次数。"""
    rec = stock("000003.SZ", "丙", "2026-09-01", 30.0, 21, 5,
                reviews=[{"date": "2026-09-0%d" % d, "day": d} for d in range(1, 6)])
    snap = make_snapshot(stocks=[rec, dict(rec)], last_close_by_code={"000003.SZ": 33.0})
    a = atlas_of(snap)
    assert a["groups"][0]["badge"] is None  # 单次入选不显示“1次”徽标
    assert len(a["groups"][0]["records"]) == 1
    assert len(a["record"]) == 1


def test_status_independence_first_invalid_second_valid():
    """第一轮失效、第二轮有效：两条状态独立保留，互不连带。"""
    snap = make_snapshot(
        stocks=[
            stock("000004.SZ", "丁", "2026-09-03", 15.0, 23, 3),
            stock("000004.SZ", "丁", "2026-08-27", 18.0, 17, 11, invalidated=True),
        ],
        last_close_by_code={"000004.SZ": 16.0},
    )
    a = atlas_of(snap)
    # 锚点仍是最早（失效）那条；展示层不做连带失效或复活。
    assert a["groups"][0]["basis"]["anchor"]["recDate"] == "2026-08-27"
    assert a["groups"][0]["basis"]["plottable"] is True
    assert a["groups"][0]["badge"]["full"] == "入选 2 次"


def test_event_and_normal_mix_badge():
    snap = make_snapshot(
        stocks=[
            stock("000005.SZ", "戊", "2026-09-03", 9.0, 23, 3),
            stock("000005.SZ", "戊", "2026-09-01", 10.0, 21, 5, refKind="event"),
        ],
        last_close_by_code={"000005.SZ": 10.5},
    )
    assert atlas_of(snap)["groups"][0]["badge"]["full"] == "入选 2 次 · 含条件观察"


def test_missing_anchor_ref_not_replaced_by_latest():
    """最早 ref 缺失：不悄悄换最新基准；记录视图最新一条仍可绘制。"""
    snap = make_snapshot(
        stocks=[
            stock("000006.SZ", "己", "2026-09-03", 12.0, 23, 3),
            stock("000006.SZ", "己", "2026-08-28", None, 17, 10),
        ],
        last_close_by_code={"000006.SZ": 13.0},
    )
    a = atlas_of(snap)
    g = a["groups"][0]
    assert g["basis"]["plottable"] is False
    assert g["basis"]["reason"] == "缺参考价"
    assert g["basis"]["ret"] is None
    rec = {x["key"]: x["point"] for x in a["record"]}
    assert rec["000006.SZ:2026-09-03"]["plottable"] is True
    assert rec["000006.SZ:2026-09-03"]["ret"] == pytest.approx((13.0 / 12.0 - 1) * 100)
    assert rec["000006.SZ:2026-08-28"]["plottable"] is False


def test_missing_report_day_close():
    """当日停牌/无行情：不画当日收益，也不借前一日价格。"""
    snap = make_snapshot(
        stocks=[stock("000007.SZ", "庚", "2026-08-27", 7.0, 17, 11)],
        last_close_by_code={"000007.SZ": 7.7},
    )
    snap["stocks"][0]["candles"][-1] = None  # 报告日无行情；前一交易日有价
    a = atlas_of(snap)
    assert a["groups"][0]["basis"]["plottable"] is False
    assert a["groups"][0]["basis"]["reason"] == "报告日无真实收盘"


def test_same_day_price_copy_fallback_within_group():
    """首次价格副本缺当日，同股另一副本同日同口径有价：可复用。"""
    snap = make_snapshot(
        stocks=[
            stock("000008.SZ", "辛", "2026-09-03", 5.0, 23, 3),
            stock("000008.SZ", "辛", "2026-09-01", 6.0, 21, 5),
        ],
        last_close_by_code={"000008.SZ": 6.6},
    )
    snap["stocks"][1]["candles"][-1] = None  # 最早记录的报告日副本缺失
    a = atlas_of(snap)
    b = a["groups"][0]["basis"]
    # 用同股同日的另一份副本收盘，锚点参考价不变。
    assert b["plottable"] is True
    assert b["close"] == pytest.approx(6.6)
    assert b["ret"] == pytest.approx((6.6 / 6.0 - 1) * 100)


def test_pending_first_day_record():
    """已发布但未到首日的计划记录：标待首日，不虚构参考价或涨跌。"""
    snap = make_snapshot(
        stocks=[stock("000009.SZ", "壬", "2026-09-08", None, 26, 0, d0=True)],
        last_close_by_code={},
    )
    a = atlas_of(snap)
    assert a["groups"][0]["basis"]["plottable"] is False
    assert a["groups"][0]["basis"]["reason"] == "待首日观察"
    assert a["record"][0]["point"]["plottable"] is False


def test_multi_selection_with_pending_first_day():
    """已观察一次 + 新计划一次：徽标标注“含1次待首日”，不重置旧基准。"""
    snap = make_snapshot(
        stocks=[
            stock("000010.SZ", "癸", "2026-09-08", None, 26, 0, d0=True),
            stock("000010.SZ", "癸", "2026-09-01", 11.0, 21, 5),
        ],
        last_close_by_code={"000010.SZ": 12.0},
    )
    a = atlas_of(snap)
    g = a["groups"][0]
    assert g["badge"]["full"] == "入选 2 次 · 含1次待首日"
    assert g["basis"]["anchor"]["recDate"] == "2026-09-01"
    assert g["basis"]["day"] == 25 - 21 + 1


def test_axis_range_adapts_and_never_clips():
    """-35%/+45% 仍在轴范围内且包含 0；空列表与单点不产生 NaN。"""
    extreme = make_snapshot(
        stocks=[
            stock("000011.SZ", "子", "2026-09-03", 100.0, 23, 3),
            stock("000012.SZ", "丑", "2026-09-03", 10.0, 23, 3),
        ],
        last_close_by_code={"000011.SZ": 65.0, "000012.SZ": 14.5},
    )
    a = atlas_of(extreme)
    assert a["range"]["lo"] <= -35.0 and a["range"]["hi"] >= 45.0
    assert a["range"]["lo"] < 0 < a["range"]["hi"]
    assert all(math.isfinite(v) for v in (a["range"]["lo"], a["range"]["hi"], a["range"]["maxDay"]))

    empty = atlas_of(make_snapshot(stocks=[]))
    assert empty["groups"] == [] and empty["record"] == [] and empty["range"] is None

    single = atlas_of(make_snapshot(
        stocks=[stock("000013.SZ", "寅", "2026-09-05", 8.0, 24, 2)],
        last_close_by_code={"000013.SZ": 8.8},
    ))
    assert single["range"]["maxDay"] == 2


def test_atlas_basis_label_never_claims_full_history():
    snap = make_snapshot(
        stocks=[stock("000014.SZ", "卯", "2026-09-01", 3.0, 21, 5)],
        last_close_by_code={"000014.SZ": 3.3},
    )
    out = run_node(snap, "(R,d)=>R.ATLAS_BASIS_LABEL")
    assert out == "本报告最早记录"
    assert "历史首次" not in out
