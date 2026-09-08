"""PRISM WEB 本轮整改回归入口（tests/test_prism_web_contract.py）。

按审核包《03-验收矩阵》组织：T01—T08（验收自身）、T09—T30（日期/日历/枚举/身份）、
T31—T41（展示/搜索/来源/目标）、T42—T51（构建/更新/目录）。
合成数据一律在测试内构造或来自 tests/fixtures/prism_web/*.json；不改真实归档。
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRISM_BUILD = PROJECT_ROOT / "tools" / "guanlan-prism" / "tools" / "build.py"
ATLAS_CHECKER = PROJECT_ROOT / "tests" / "check_prism_atlas_browser.py"
CONTRACT = PROJECT_ROOT / "tools" / "web_display_contract.py"
FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "prism_web"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _builder():
    return _load(PRISM_BUILD, "prism_build_test")


def _checker():
    return _load(ATLAS_CHECKER, "prism_atlas_checker_test")


# ---------------------------------------------------------------------------
# 一、先验证测试本身（F10：T01—T08）
# ---------------------------------------------------------------------------

class _FakeHarness:
    def __init__(self, failures):
        self.failures = list(failures)
        self.total = 3


def test_final_status_aggregates_all_harnesses_and_errors():
    checker = _checker()
    # T01：仅桌面一条失败、无 JS 错误 → 非零，失败条目保留。
    code, failures = checker.final_status([_FakeHarness(["a: x"]), _FakeHarness([]), _FakeHarness([])], [])
    assert code == 1 and failures == ["a: x"]
    # T02：桌面全过，只有手机失败 → 非零。
    code, failures = checker.final_status([_FakeHarness([]), _FakeHarness(["m: y"]), _FakeHarness([])], [])
    assert code == 1 and failures == ["m: y"]
    # T03：只有合成页失败 → 非零。
    code, failures = checker.final_status([_FakeHarness([]), _FakeHarness([]), _FakeHarness(["s: z"])], [])
    assert code == 1 and failures == ["s: z"]
    # T04：断言全过但有 JS error → 非零。
    code, _ = checker.final_status([_FakeHarness([]), _FakeHarness([]), _FakeHarness([])],
                                   ["pageerror: boom"])
    assert code == 1
    # T05：全部通过 → 零；数量来自实际执行，不使用写死总数。
    code, failures = checker.final_status([_FakeHarness([])] * 3, [])
    assert code == 0 and failures == []


def _render_check_page(tmp_path: Path, snapshot, *, corrupt_js: bool = False) -> Path:
    html = _builder().render_html(snapshot)
    if corrupt_js:
        html = html.replace("</body>", "<script>throw new Error('negative control');</script></body>")
    page = tmp_path / "page.html"
    page.write_text(html, encoding="utf-8")
    return page


def _run_checker(page: Path, out: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ATLAS_CHECKER), "--html", str(page), "--out", str(out), *extra],
        capture_output=True, text=True, timeout=600, cwd=PROJECT_ROOT,
    )


def test_negative_control_broken_session_dates_exit_nonzero(tmp_path):
    """负对照：sessionDates 长度冲突的页面必须被检查抓出，命令真实非零（T01/T02 层）。"""
    page = _render_check_page(tmp_path, _checker().synth_broken_dates())
    proc = _run_checker(page, tmp_path / "shots")
    assert proc.returncode == 1, proc.stdout[-2000:] + proc.stderr[-2000:]
    assert "全部通过" not in proc.stdout
    assert "失败" in proc.stdout and "0 项" not in proc.stdout.split("结果：")[-1]


def test_negative_control_js_error_exit_nonzero(tmp_path):
    """负对照：断言可全过但注入 JS error → 必须非零（T04，子进程真实退出码）。"""
    page = _render_check_page(tmp_path, _checker().synth_snapshot([]), corrupt_js=True)
    proc = _run_checker(page, tmp_path / "shots")
    assert proc.returncode == 1, proc.stdout[-2000:] + proc.stderr[-2000:]
    assert "JS/控制台错误 0 条" not in proc.stdout


def test_missing_browser_executable_exit_2(tmp_path):
    """T06：指定的可执行文件不存在 → 清楚提示退出码 2，不能跳过浏览器后报全过。"""
    page = _render_check_page(tmp_path, _checker().synth_snapshot([]))
    proc = _run_checker(page, tmp_path / "shots",
                        "--browser-executable", "/nonexistent/browser")
    assert proc.returncode == 2
    assert "不存在" in proc.stdout + proc.stderr
    assert "全部通过" not in proc.stdout


def test_atlas_expectations_recompute_from_input():
    """T07：任意报告增删记录、改名改价，期望值按新输入独立计算，不依赖历史样本。"""
    checker = _checker()
    base = checker.synth_main()
    first = checker.atlas_expectations(base)
    assert first["stock_stats"] == "8只股票 · 13条入选记录 · 5只有坐标 · 3只暂未绘制"
    # 换名字、换价格、删除一条记录：期望随之改变。
    renamed = json.loads(json.dumps(base))
    for s in renamed["stocks"]:
        if s["code"] == "000001.SZ":
            s["name"] = "完全不同的名字"
            if s.get("ref") == 100.0:
                s["ref"] = 50.0
                s["candles"][-1][3] = 60.0  # +20%
    renamed["stocks"] = [s for s in renamed["stocks"] if s.get("recDate") != "2026-08-28"]
    second = checker.atlas_expectations(renamed)
    # 删除一条后：记录 13→12；乙二锚点变为有参考价的记录 → 可绘制 5→6。
    assert second["stock_stats"] == "8只股票 · 12条入选记录 · 6只有坐标 · 2只暂未绘制"
    group = next(g for g in second["groups"] if g["code"] == "000001.SZ")
    assert group["name"] == "完全不同的名字"
    assert group["anchor_ret"] == pytest.approx((60.0 / 50.0 - 1) * 100)


def test_synthetic_fixture_numbers_are_bound_to_the_fixture():
    """T08：固定样本的期望数字只与 synth_main() 绑定，检查名注明 fixture。"""
    checker = _checker()
    snapshot = checker.synth_main()
    keys = [f"{s['code']}:{s['recDate']}" for s in snapshot["stocks"]]
    assert len(keys) == 13 and len(set(keys)) == 12  # 含一个重复身份
    stats = checker.atlas_expectations(snapshot)["stock_stats"]
    assert stats == "8只股票 · 13条入选记录 · 5只有坐标 · 3只暂未绘制"


# ---------------------------------------------------------------------------
# 二、日期、日历、行情与起点（F03/F04/F07：T09—T20）
# ---------------------------------------------------------------------------

@pytest.fixture
def contract():
    return _load(CONTRACT, "web_display_contract_test")


def _run_js(src_dir, expr):
    script = (
        "const C=require(process.argv[1]);const R=require(process.argv[2]);"
        "const out=eval(process.argv[3])(C,R);"
        "process.stdout.write(JSON.stringify(out));"
    )
    proc = subprocess.run(
        ["node", "-e", script, str(src_dir / "core.js"), str(src_dir / "rules.js"), expr],
        capture_output=True, text=True, timeout=60,
    )
    if proc.returncode != 0:
        raise AssertionError(f"node failed:\n{proc.stderr}")
    return json.loads(proc.stdout)


@pytest.fixture
def js_src():
    return PROJECT_ROOT / "tools" / "guanlan-prism" / "src"


def test_session_dates_cross_year_never_double_stitched(contract):
    """T09：sessionDates 2026-12-31→2027-01-04；MM-DD 只作显示。"""
    resolved = contract.resolve_session_dates(
        ["12-31", "01-04"], "2027-01-04", ["2026-12-31", "2027-01-04"]
    )
    assert resolved == ["2026-12-31", "2027-01-04"]
    assert contract.display_dates(resolved) == ["12-31", "01-04"]


def test_session_dates_legacy_same_year_ok_cross_year_rejected(contract):
    """T12：只有旧 MM-DD 时同年自洽可用；跨年/倒序明确拒绝，不猜年份。"""
    assert contract.resolve_session_dates(["12-30", "12-31"], "2026-12-31") == [
        "2026-12-30", "2026-12-31",
    ]
    with pytest.raises(contract.DateContractError, match="重新生成"):
        contract.resolve_session_dates(["12-31", "01-04"], "2027-01-04")  # 跨年无法证明
    with pytest.raises(contract.DateContractError, match="严格递增"):
        contract.resolve_session_dates(["09-04", "09-03"], "2026-09-04")  # 倒序
    with pytest.raises(contract.DateContractError, match="不一致"):
        contract.resolve_session_dates(["09-03", "09-04"], "2026-09-05")  # 末日不符
    with pytest.raises(contract.DateContractError, match="长度"):
        contract.resolve_session_dates(
            ["12-31", "01-04"], "2027-01-04", ["2026-12-31"]
        )


def test_js_core_dates_match_python_contract(js_src):
    """T09/T11（页面端）：core.dateAt/indexOfDate 与 Python 合同行为一致。"""
    out = _run_js(js_src, """(C,R)=>({
      crossYear:C.dateAt(0,{analysis_date:'2027-01-04',dates:['12-31','01-04'],
        sessionDates:['2026-12-31','2027-01-04']}),
      isoOf:C.indexOfDate({analysis_date:'2027-01-04',dates:['12-31','01-04'],
        sessionDates:['2026-12-31','2027-01-04']},'2026-12-31'),
      legacySameYear:C.dateAt(0,{analysis_date:'2026-12-31',dates:['12-30','12-31']}),
      rulesIndexOf:R.indexOfDate({analysis_date:'2026-12-31',dates:['12-30','12-31']},'2026-12-31'),
    })""")
    assert out["crossYear"] == "2026-12-31"          # 不把 12 月拼成 2027
    assert out["isoOf"] == 0
    assert out["legacySameYear"] == "2026-12-30"
    assert out["rulesIndexOf"] == 1


def test_js_core_rejects_unprovable_cross_year(js_src):
    """T12（页面端）：旧 MM-DD 跨年 → 页面合同抛错，不猜年份。"""
    out = _run_js(js_src, """(C,R)=>{
      let error=null;
      try{C.dateAt(0,{analysis_date:'2027-01-04',dates:['12-31','01-04']})}
      catch(e){error=e.message}
      return {error: error||''};
    }""")
    assert "跨年" in out["error"] and "重新生成" in out["error"]


def test_js_core_exact_vs_last_available_quote(js_src):
    """T17：报告日缺价 → 当日指标为空；最近有效价可取但必须带真实序号。"""
    out = _run_js(js_src, """(C,R)=>{
      const d={analysis_date:'2027-01-04',dates:['12-31','01-02','01-04'],
        sessionDates:['2026-12-31','2027-01-02','2027-01-04']};
      const s={code:'X.SZ',recDate:'2026-12-31',recIndex:0,ref:100,days:3,d0:null,
        candles:[[100,102,99,101,1],[101,120,101,120,2],[null,null,null,null,null]],
        reviews:[]};
      const exact=C.quoteOnIndex(s,2), last=C.lastAvailableQuote(s,2);
      return {exact:!!exact, last_i:last?last.i:null, last_close:last?last.c[3]:null,
        m:C.metrics(s,2)};
    }""")
    assert out["exact"] is False                 # 报告日 bar 为空 → 无当日价
    assert out["last_i"] == 1 and out["last_close"] == 120  # 最近有效价带真实序号
    assert out["m"]["ret"] is None and out["m"]["close"] is None
    assert out["m"]["drawdown"] is None and out["m"]["remaining"] is None
    assert out["m"]["max"] == pytest.approx(20.0)           # 历史峰值仍为 +20%
    # 有效日上的当日指标按 exact 口径
    out2 = _run_js(js_src, """(C)=>{
      const s={code:'X.SZ',recDate:'2026-12-31',recIndex:0,ref:100,days:2,d0:null,
        candles:[[100,102,99,101,1],[101,120,101,120,2]],reviews:[]};
      return C.metrics(s,1);
    }""")
    assert out2["ret"] == pytest.approx(20.0) and out2["close"] == 120


def test_list_sessions_keeps_missing_quote_days(tmp_path):
    """T13：日历开市但行情分区缺失 → 该日仍保留在交易日序列，不缩短观察窗口。"""
    sys.path.insert(0, str(PROJECT_ROOT / "tools"))
    import pandas as pd
    from tools import render_monitor_web as renderer

    days = pd.date_range("2026-06-01", "2026-12-31", freq="D")
    frame = pd.DataFrame({"exchange": "SSE", "cal_date": days.strftime("%Y-%m-%d"),
                          "is_open": days.dayofweek < 5})
    cal_dir = tmp_path / "local_warehouse" / "facts" / "trade_calendar" / "cal_year=2026"
    cal_dir.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(cal_dir / "data.parquet")
    sessions = renderer.list_sessions(tmp_path, date(2026, 9, 1), date(2026, 9, 8))
    # 09-05/06 为周末休市；行情分区是否存在不影响交易日序列
    assert [d.isoformat() for d in sessions] == [
        "2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04",
        "2026-09-07", "2026-09-08",
    ]


def test_list_sessions_requires_calendar_coverage(tmp_path):
    """T14：日历缺失/覆盖不足 → 明确失败，不回退周历或行情目录。"""
    sys.path.insert(0, str(PROJECT_ROOT / "tools"))
    from tools import render_monitor_web as renderer

    with pytest.raises(ValueError, match="交易日历为空"):
        renderer.list_sessions(tmp_path, date(2026, 9, 1), date(2026, 9, 8))
    import pandas as pd
    frame = pd.DataFrame([{"exchange": "SSE", "cal_date": "2026-06-01", "is_open": True}])
    cal_dir = tmp_path / "local_warehouse" / "facts" / "trade_calendar" / "cal_year=2026"
    cal_dir.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(cal_dir / "data.parquet")
    with pytest.raises(ValueError, match="未覆盖"):
        renderer.list_sessions(tmp_path, date(2026, 9, 1), date(2026, 9, 30))


# ---------------------------------------------------------------------------
# 三、重复推荐与语义字段（F02/F05：T21—T30）
# ---------------------------------------------------------------------------

def _episode_payload(episode_id, ts_code, action_date, **kw):
    base = {
        "episode_id": episode_id, "ts_code": ts_code, "name": f"股{ts_code[:4]}",
        "role": "selected", "selection_output_class": "confirmed_active",
        "original_engine_type": "sector_broad_diffusion", "original_engine_status": "active",
        "original_priority": 1, "action_date": action_date, "formation_date": action_date,
        "analysis_date": "2026-09-07", "day_number": 2, "monitor_phase": "primary",
        "formal_return_started": False, "entry_open": None, "data_limitations": [],
        "new_announcements": [], "original_group_code": "", "previous_monitor_state": None,
        "previous_episode_review": None, "original_research_thesis": {},
        "original_selection_reason": "合成理由。", "frozen_twenty_day_review": None,
        "pair_context": None,
    }
    base.update(kw)
    return base


def _minimal_build_payload(tmp_path, episodes, *, selection_trace=None, ledger_reviews=None):
    sys.path.insert(0, str(PROJECT_ROOT / "tools"))
    import pandas as pd
    from tools import render_monitor_web as renderer

    days = pd.date_range("2026-06-01", "2026-12-31", freq="D")
    frame = pd.DataFrame({"exchange": "SSE", "cal_date": days.strftime("%Y-%m-%d"),
                          "is_open": days.dayofweek < 5})
    cal_dir = tmp_path / "local_warehouse" / "facts" / "trade_calendar" / "cal_year=2026"
    cal_dir.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(cal_dir / "data.parquet")
    monitor = tmp_path / "monitor"
    monitor.mkdir(exist_ok=True)
    day = "2026-09-07"
    snapshot = {
        "snapshot_version": "forward-monitor-snapshot-v1", "analysis_date": day,
        "as_of": f"{day}T21:00:00+08:00", "episodes": episodes,
        "daily_review_episode_ids": [], "checkpoint_review_episode_ids": [],
        "attention_stocks": [], "summary": {},
    }
    report = {
        "report_version": "daily-forward-monitor-report-v2", "analysis_date": day,
        "as_of": f"{day}T21:00:00+08:00", "alerts": [],
    }
    (monitor / f"snapshot-{day}.json").write_text(json.dumps(snapshot), encoding="utf-8")
    (monitor / f"monitor-report-{day}.json").write_text(json.dumps(report), encoding="utf-8")
    if ledger_reviews is not None:
        ledger = {"ledger_version": "daily-formal-reviews-v1", "analysis_date": day,
                  "as_of": f"{day}T21:00:00+08:00", "reviews": ledger_reviews}
        (monitor / f"daily-formal-reviews-{day}.json").write_text(
            json.dumps(ledger, ensure_ascii=False), encoding="utf-8")
    selection = tmp_path / "selection"
    selection.mkdir(exist_ok=True)
    if selection_trace is not None:
        (selection / f"research-trace-{day}.json").write_text(
            json.dumps(selection_trace), encoding="utf-8")
    # selection_dir 显式贯穿（T48）：不读真实仓库轨迹。
    return renderer.build_payload(tmp_path, monitor, date.fromisoformat(day), report, snapshot,
                                  selection_dir=selection)


def test_d0_same_stock_next_day_is_kept(tmp_path):
    """T21：旧推荐 + 同股次日再次入选 D0 → 两次都在；旧 ref 保留、新 ref 为空。"""
    old = _episode_payload("e-old", "600001.SH", "2026-09-01", day_number=5)
    trace = {
        "trace_version": "forward-selection-trace-v1", "formation_date": "2026-09-07",
        "action_date": "2026-09-08", "as_of": "2026-09-07T21:00:00+08:00",
        "candidate_ledger": [
            {"ts_code": "600001.SH", "name": "股6000", "final_fate": "selected",
             "primary_reason": "再次入选。"},
        ],
        "research_result": {"selected_stocks": []},
    }
    payload = _minimal_build_payload(tmp_path, [old], selection_trace=trace)
    records = [s for s in payload["stocks"] if s["code"] == "600001.SH"]
    assert len(records) == 2  # 旧记录 + 新 D0 都在（不再按代码整体滤掉）
    old_rec = next(s for s in records if s["recDate"] == "2026-09-01")
    d0 = next(s for s in records if s["recDate"] == "2026-09-08")
    assert not old_rec.get("d0")
    assert d0["d0"] is True and d0["ref"] is None and d0["days"] == 0
    assert old_rec["formedOn"] == "2026-09-01" and d0["formedOn"] == "2026-09-07"


def test_d0_same_action_date_dedup(tmp_path):
    """T22：同一 D0（同代码同 action_date）不重复追加。"""
    old = _episode_payload("e-old", "600001.SH", "2026-09-08", day_number=1)
    old["analysis_date"] = "2026-09-08"
    trace = {
        "trace_version": "forward-selection-trace-v1", "formation_date": "2026-09-07",
        "action_date": "2026-09-08", "as_of": "2026-09-07T21:00:00+08:00",
        "candidate_ledger": [
            {"ts_code": "600001.SH", "name": "股6000", "final_fate": "selected",
             "primary_reason": "重复载入同一推荐。"},
        ],
        "research_result": {"selected_stocks": []},
    }
    payload = _minimal_build_payload(tmp_path, [old], selection_trace=trace)
    records = [s for s in payload["stocks"] if s["code"] == "600001.SH"]
    assert len(records) == 1


def test_duplicate_identity_conflicts_are_rejected(tmp_path):
    """E3：同一 code:recDate 对应两个不同 episode → 明确报错，不静默覆盖。"""
    a = _episode_payload("e-a", "600002.SH", "2026-09-01")
    b = _episode_payload("e-b", "600002.SH", "2026-09-01")  # 不同 episode 同一身份
    with pytest.raises(ValueError, match="多个 episode"):
        _minimal_build_payload(tmp_path, [a, b])


def test_rec_session_missing_not_index_zero(tmp_path):
    """T15/T16：首日观察日期不在交易日序列 → recIndex/ref 为空 + dataIssues，绝不用第 0 日顶替。"""
    episode = _episode_payload("e-x", "600003.SH", "2026-09-06")  # 周日：日历明确休市
    payload = _minimal_build_payload(tmp_path, [episode])
    stock = payload["stocks"][0]
    assert stock["recIndex"] is None and stock["ref"] is None
    assert stock["refKind"] is None
    assert any(i["code"] == "missing_rec_session" for i in stock["dataIssues"])
    assert stock["suspended"] is False  # 缺首日不是停牌


def test_review_enums_passthrough_and_direction_map(contract):
    """T24/T25/E4：枚举严格透传；未知值不猜测；方向归并按固定表。"""
    enums = contract.review_enums({
        "view_change": "strengthened", "current_assessment": "supported",
        "outlook_1_3d": "continuation_possible",
    })
    assert enums == {"viewChange": "strengthened", "assessmentCode": "supported",
                     "outlookCode": "continuation_possible", "outlookDirection": "up"}
    assert contract.outlook_direction("range_or_wait") == "sideways"
    assert contract.outlook_direction("invalidated") == "down"
    assert contract.outlook_direction("event_pending") is None
    assert contract.outlook_direction(None) is None
    unknown = contract.review_enums({
        "view_change": "future_new_enum", "current_assessment": None,
        "outlook_1_3d": "brand_new_code",
    })
    assert unknown == {"viewChange": "future_new_enum", "assessmentCode": None,
                       "outlookCode": "brand_new_code", "outlookDirection": None}
    missing = contract.review_enums({})
    assert missing == {"viewChange": None, "assessmentCode": None,
                       "outlookCode": None, "outlookDirection": None}


def test_js_rules_enum_first_not_chinese_guessing(js_src):
    """T24/T25/T26（页面端）：筛选/失效归类跟随枚举；未知枚举→未识别；旧中文精确兼容。"""
    out = _run_js(js_src, """(C,R)=>{
      const mk=(code,name,reviews)=>({code,name,recDate:'2026-09-01',ref:10,recIndex:0,
        days:5,d0:null,candles:[[10,10,10,11,1]],invalidated:null,reviews});
      const d={analysis_date:'2026-09-07',dates:['09-07'],market:[1],stocks:[
        mk('1.SZ','甲',[{date:'2026-09-07',day:5,viewChange:'weakened',viewLabel:'另一种等义表述',
                   assessmentCode:'weakening',base:'任意原文'}]),
        mk('2.SZ','乙',[{date:'2026-09-07',day:5,viewChange:'future_new_enum',
                   assessmentCode:'weakening',base:'任意原文'}]),
        mk('3.SZ','丙',[{date:'2026-09-07',day:5,viewLabel:'观点增强',base:'任意原文'}]),
        mk('4.SZ','丁',[{date:'2026-09-07',day:5,viewChange:'invalidated',viewLabel:'判断失效',
                   assessmentCode:'contradicted',base:'任意原文'}]),
      ]};
      const [a,b,c,e]=d.stocks;
      return {
        a_opinion:R.opinionCode(a,d), a_invalid:R.isInvalid(a,d),
        b_opinion:R.opinionCode(b,d), b_invalid:R.isInvalid(b,d),
        c_opinion:R.opinionCode(c,d),
        e_opinion:R.opinionCode(e,d), e_invalid:R.isInvalid(e,d),
        b_label:R.opinionLabel(b,d),
      };
    }""")
    assert out["a_opinion"] == "weakened" and out["a_invalid"] is False      # T24
    assert out["b_opinion"] == "unrecognized" and out["b_invalid"] is False  # T25
    assert out["b_label"] == "未识别状态"
    assert out["c_opinion"] == "strengthened"                                # T26
    assert out["e_opinion"] == "invalidated" and out["e_invalid"] is True


def test_js_direction_enum_priority(js_src):
    """T27/T28/T29：方向更新走枚举；信心变化不算方向；首次复盘无前值。"""
    out = _run_js(js_src, """(C,R)=>{
      const mk=(code,name,reviews)=>({code,name,recDate:'2026-09-01',ref:10,recIndex:0,
        days:5,d0:null,candles:[[10,10,10,11,1]],invalidated:null,reviews});
      const d={analysis_date:'2026-09-07',dates:['09-07'],market:[1],stocks:[
        mk('1.SZ','甲',[{date:'2026-09-06',day:4,outlookDirection:'up',viewChange:'strengthened'},
                        {date:'2026-09-07',day:5,outlookDirection:'up',viewChange:'strengthened'}]),
        mk('2.SZ','乙',[{date:'2026-09-06',day:4,outlookDirection:'up',viewChange:'unchanged'},
                        {date:'2026-09-07',day:5,outlookDirection:'sideways',viewChange:'unchanged'}]),
        mk('3.SZ','丙',[{date:'2026-09-07',day:5,outlookDirection:'down'}]),
        mk('4.SZ','丁',[{date:'2026-09-06',day:4,base:'未来1—3个交易日更可能继续走强'},
                        {date:'2026-09-07',day:5,outlookCode:'weakening'}]),
      ]};
      return R.directionUpdates(d).map(x=>({name:x.s.name,from:x.from,to:x.to}));
    }""")
    by_name = {x["name"]: x for x in out}
    assert "甲" not in by_name       # T27：方向仍 up，信心 strengthened → 不进入方向更新
    assert by_name["乙"]["from"] == "up" and by_name["乙"]["to"] == "sideways"  # T28
    assert "丙" not in by_name       # T29：首次复盘无 previous
    assert by_name["丁"]["to"] == "down"  # outlookCode 兜底归并可用


# ---------------------------------------------------------------------------
# 五、构建、更新、目录（F11/F12：T42—T47）
# ---------------------------------------------------------------------------

def test_builder_keeps_literal_markers_and_script_closers_in_text():
    """T42/T43：正文含模板标记、</script>、引号、反斜线 → 原样保留且不破坏页面。"""
    builder = _builder()
    snapshot = {
        "analysis_date": "2026-09-07", "as_of": "2026-09-07T18:30:00+08:00",
        "dates": ["09-05", "09-07"], "market": [3000.0, 3001.0],
        "sessionDates": ["2026-09-05", "2026-09-07"],
        "stocks": [{
            "code": "600000.SH", "name": "标记公司", "recDate": "2026-09-07",
            "recIndex": 1, "ref": 10.0, "refKind": "formal", "days": 1, "d0": None,
            "candles": [[10.0, 11.0, 9.0, 10.5, 1.0], [10.5, 11.5, 10.2, 11.0, 2.0]],
            "reviews": [{"date": "2026-09-07", "day": 1,
                         "copy": "正文含 /*__CORE__*/、/*__DATA__*/ 与 </script>、\"引号\"、\\反斜线、\n换行。",
                         "summary_copy": "同上 /*__APP__*/",
                         "viewChange": "unchanged", "assessmentCode": "supported",
                         "outlookCode": "range_or_wait", "outlookDirection": "sideways"}],
            "events": [["2026-09-07", "rec", "正式推荐", "含 /*__CSS__*/ 的理由"]],
        }],
    }
    html = builder.render_html(snapshot)
    embedded = json.loads(html.split('<script id="snapshot" type="application/json">')[1].split("</script>")[0])
    body = embedded["stocks"][0]["reviews"][0]["copy"]
    assert "/*__CORE__*/" in body and "</script>" in body and "\\反斜线" in body
    # 页面脚本不被正文终止：注入的脚本数量与模板一致（core/rules/app/effects + data）
    assert html.count("<script>") == 4
    # 再次替换不会把正文里的标记当指令：标记只在模板层计数
    assert html.count("/*__RULES__*/") == 0  # 已被真模板替换掉


def test_builder_rejects_nonfinite_numbers():
    """T44：NaN/Infinity → 标准 JSON 序列化明确失败，不输出浏览器读不了的 JSON。"""
    builder = _builder()
    snapshot = {"analysis_date": "2026-09-07", "dates": ["09-07"], "market": [3000.0],
                "stocks": [{"code": "X", "ref": float("nan")}]}
    with pytest.raises(ValueError, match="Out of range|nonfinite|NaN"):
        builder.render_html(snapshot)


def test_builder_validates_metadata_and_lengths():
    """G1：必需元数据缺失、数组长度冲突 → 明确错误，不生成一页假成功；空列表合法。"""
    builder = _builder()
    with pytest.raises(ValueError, match="analysis_date"):
        builder.render_html({"dates": ["09-07"], "market": [1.0], "stocks": []})
    with pytest.raises(ValueError, match="dates"):
        builder.render_html({"analysis_date": "2026-09-07", "dates": [], "market": [], "stocks": []})
    with pytest.raises(ValueError, match="不一致"):
        builder.render_html({"analysis_date": "2026-09-07", "dates": ["09-07"],
                             "market": [1.0, 2.0], "stocks": []})
    with pytest.raises(ValueError, match="不一致"):
        builder.render_html({"analysis_date": "2026-09-07", "dates": ["09-07"],
                             "market": [1.0], "sessionDates": ["2026-09-05", "2026-09-06"],
                             "stocks": []})
    # 空记录列表合法
    html = builder.render_html({"analysis_date": "2026-09-07", "dates": ["09-07"],
                                "market": [1.0], "stocks": []})
    assert html.lstrip().lower().startswith("<!doctype html>")


def test_single_and_modular_share_template_and_order(tmp_path, monkeypatch):
    """T45：单文件与拆分形式来自同一模板与清单，加载顺序一致。"""
    builder = _builder()
    snapshot = {"analysis_date": "2026-09-07", "dates": ["09-07"], "market": [1.0], "stocks": []}
    single = builder.render_html(snapshot)
    # CSS 顺序 base→prism→v3，脚本顺序 rules 先于 app
    css_order = [single.index(m) for m in (
        "--sans", "--bg: #070910", ".market-grid")]
    assert css_order == sorted(css_order)
    assert single.index("PRISM V3 · Display policy") < single.index("PRISM V3 standalone presentation")
    # 拆分预览：临时 ROOT（复制真实 src），output=None 时生成 dist 单文件 + index 拆分页
    import shutil
    prism_root = PROJECT_ROOT / "tools" / "guanlan-prism"
    tmp_root = tmp_path / "prism"
    (tmp_root).mkdir()
    shutil.copytree(prism_root / "src", tmp_root / "src")
    (tmp_root / "data").mkdir()
    (tmp_root / "data" / "snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")
    monkeypatch.setattr(builder, "ROOT", tmp_root)
    dist_path, index_path = builder.build()
    modular = index_path.read_text(encoding="utf-8")
    assert dist_path.is_file() and dist_path == tmp_root / "dist" / "guanlan-prism.html"
    for ref in ("src/base.css", "src/prism.css", "src/v3.css"):
        assert f'href="{ref}"' in modular
    script_refs = [name for name in ("core", "rules", "app", "effects")
                   if f'<script src="src/{name}.js">' in modular]
    assert script_refs == ["core", "rules", "app", "effects"]
    # 两者嵌入同一份数据（同一清单、同一模板）
    single_data = single.split('<script id="snapshot" type="application/json">')[1].split("</script>")[0]
    modular_data = modular.split('<script id="snapshot" type="application/json">')[1].split("</script>")[0]
    assert single_data == modular_data


# ---------------------------------------------------------------------------
# 四、展示、来源与目标（F01/F03/F08：T31—T38 的数据层部分）
# ---------------------------------------------------------------------------

def test_payload_carries_readonly_policy_and_source(tmp_path):
    """T37/T38：正式生成器输出 sourceInfo 与 observationPolicy；20/0.2 只读集中。"""
    episode = _episode_payload("e-p", "600005.SH", "2026-09-04")
    payload = _minimal_build_payload(tmp_path, [episode])
    assert payload["sourceInfo"] == {"kind": "frozen_archive", "label": "本地冻结复盘归档",
                                     "externallyVerified": False}
    assert payload["observationPolicy"] == {"primaryDays": 20, "targetReturn": 0.2,
                                            "origin": "existing_v4_contract"}
    assert payload["sessionDates"][-1] == "2026-09-07"
    assert payload["dates"][-1] == "09-07"  # MM-DD 仅作显示


def test_data_issues_only_from_real_gaps(tmp_path):
    """T32/T33：dataIssues 只来自实际检测到的缺口；结构完整；无缺口时为空。"""
    ok = _episode_payload("e-ok", "600006.SH", "2026-09-04")
    # 提供首日行情事实：参考价可算、有推荐后价格 → 不应有任何 dataIssues。
    import pandas as pd
    quote_dir = (tmp_path / "local_warehouse" / "facts" / "equity_daily"
                 / "trade_date=2026-09-04")
    quote_dir.mkdir(parents=True)
    pd.DataFrame([{"ts_code": "600006.SH", "open": 10.0, "high": 10.5, "low": 9.8,
                   "close": 10.2, "amount": 2.0e8,
                   "available_at": pd.Timestamp("2026-09-06T01:00:00Z")}]).to_parquet(
        quote_dir / "data.parquet")
    payload = _minimal_build_payload(tmp_path, [ok])
    stock = payload["stocks"][0]
    assert stock["dataIssues"] == []  # 无编造冲突
    assert stock["ref"] == 10.0 and stock["refKind"] == "formal"
    entry = {"code": "x", "recordKey": "k", "reviewDate": None,
             "message": "m", "origin": "display_data_adapter"}
    # 缺口样本（首日不在交易日序列）应有结构完整的 dataIssues
    bad = _episode_payload("e-bad", "600007.SH", "2026-09-06")  # 周日休市
    payload2 = _minimal_build_payload(tmp_path, [bad])
    issues = payload2["stocks"][0]["dataIssues"]
    assert issues and set(issues[0]) == set(entry)
    assert issues[0]["code"] == "missing_rec_session"
