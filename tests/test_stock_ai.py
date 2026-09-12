"""tools/stock_ai.py 针对性测试（手册 §5.2、§9）。

使用临时目录、假执行器与模拟时钟；全部测试拦截真实 Mac 通知，凭据只走
临时环境变量/临时配置（DEFAULT_KEY_SOURCES 在夹具内替换，不访问真实
钥匙串、实际 API Key 配置或用户级 ZCode 设置）。
覆盖：无时限执行、旧配置不恢复时限、接替仅限额度/不可用（取消/超时优先
不接替）、本地错误不接替、两家失败先落盘再一次 Mac 通知、异常/取消/SIGTERM
落真实终态并清理子进程组、完成判定反例（缺标题/CSV 错行 + 同步成功不放行）、
推荐分区与正式名单逐只对应、复盘分组覆盖、同身份复用与跨身份拒绝复用、
次晨晚启/休市晚启/缺轨迹/prepare 异常、锁占用记录、模型证据三元组核对、
dry-run 无写入、launchd 模板与文档。
"""
from __future__ import annotations

import csv as _csv
import datetime as dt
import json
import plistlib
import sys
from pathlib import Path

import pytest

TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS_DIR))

import stock_ai  # noqa: E402

now_shanghai = stock_ai.now_shanghai


def at(day: str, hour: int, minute: int) -> dt.datetime:
    return dt.datetime.fromisoformat(f"{day}T{hour:02d}:{minute:02d}:00+08:00")


@pytest.fixture()
def mac_log():
    """收集被测代码提交的 Mac 通知文本（替身，不真实发送）。"""
    return []


@pytest.fixture()
def isolated(tmp_path, monkeypatch, mac_log):
    monkeypatch.setattr(stock_ai, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(stock_ai, "LOCAL_CONFIG_PATH", tmp_path / ".stock-ai.local.json")
    monkeypatch.setattr(stock_ai, "AI_ARCHIVE_DIR", tmp_path / "local_archive" / "ai_tasks")
    monkeypatch.setattr(stock_ai, "STATE_DIR", tmp_path / "local_archive" / "ai_tasks" / "state")
    monkeypatch.setattr(stock_ai, "INDEX_PATH", tmp_path / "local_archive" / "ai_tasks" / "index.jsonl")
    monkeypatch.setattr(stock_ai, "LOG_DIR", tmp_path / "logs" / "ai_tasks")
    monkeypatch.setattr(stock_ai, "LOCK_PATH", tmp_path / "local_archive" / "ai_tasks" / "task.lock")
    stock_ai.EvidenceBox.store.clear()  # 模型证据不跨测试残留
    # 凭据隔离：默认来源替换为临时环境变量，真实钥匙串/凭据文件不可达。
    monkeypatch.setattr(stock_ai, "DEFAULT_KEY_SOURCES", {
        "glm": [{"kind": "env", "name": "STOCK_AI_TEST_GLM_KEY"}],
        "deepseek": [{"kind": "env", "name": "STOCK_AI_TEST_DS_KEY"}],
        })
    monkeypatch.setenv("STOCK_AI_TEST_GLM_KEY", "test-key")
    monkeypatch.setenv("STOCK_AI_TEST_DS_KEY", "test-key")
    # Mac 通知替身：返回与真实函数相同的二元组。
    monkeypatch.setattr(
        stock_ai, "notify_macos",
        lambda message: (mac_log.append(message), (True, "测试接收器，未真实发送"))[1])
    monkeypatch.setattr(stock_ai, "_LAST_STATE_PATH", None)
    return tmp_path


def write_config(isolated, **data):
    stock_ai.LOCAL_CONFIG_PATH.write_text(json.dumps(data), encoding="utf-8")


class Args:
    def __init__(self, **kwargs):
        self.scheduled = kwargs.get("scheduled", False)
        self.provider = kwargs.get("provider", None)
        self.rerun_date = kwargs.get("rerun_date", None)
        self.dry_run = kwargs.get("dry_run", False)


@pytest.fixture()
def fake_keys(isolated, monkeypatch):
    monkeypatch.setenv("FAKE_GLM_KEY", "test-key")
    monkeypatch.setenv("FAKE_DS_KEY", "test-key")
    write_config(
        isolated,
        key_sources={
            "glm": [{"kind": "env", "name": "FAKE_GLM_KEY"}],
            "deepseek": [{"kind": "env", "name": "FAKE_DS_KEY"}],
        },
    )


@pytest.fixture()
def fake_forward_selection(monkeypatch):
    """替换 forward_selection 的轨迹解析与 confirmed_active 推导（报告核对用）。"""
    import stock_analyzer.ops.forward_selection as fs

    monkeypatch.setattr(fs, "DailyResearchTraceV4",
                        type("T", (), {"model_validate": staticmethod(lambda x: x)}))

    def confirmed(trace):
        stocks = [
            {**s, "opportunity_type": "x", "selection_reason": "r",
             "strongest_counterevidence": "c", "nearest_comparison": "n"}
            for s in (trace.get("research_result") or {}).get("selected_stocks", [])
        ]
        return {"selected_stocks": stocks, "nearest_nonselections": [],
                "empty_reason": "今日无合规确认机会"}

    monkeypatch.setattr(fs, "_confirmed_active_research_result", confirmed)


def write_report_archives(root, formation, action, as_of, *,
                          selected=(), alerts=(), reviews=()):
    """写入最小 trace / monitor-report / 日评账本，供真实报告核对使用。"""
    fs_dir = root / "local_archive" / "forward_selection"
    mon_dir = root / "local_archive" / "forward_monitor"
    fs_dir.mkdir(parents=True, exist_ok=True)
    mon_dir.mkdir(parents=True, exist_ok=True)
    trace = {
        "trace_version": "daily-research-trace-v4",
        "formation_date": formation,
        "action_date": action,
        "as_of": as_of,
        "research_result": {"selected_stocks": list(selected)},
        "candidate_ledger": [],
    }
    (fs_dir / f"research-trace-{formation}.json").write_text(
        json.dumps(trace, ensure_ascii=False), encoding="utf-8")
    (mon_dir / f"monitor-report-{formation}.json").write_text(
        json.dumps({"alerts": list(alerts)}, ensure_ascii=False), encoding="utf-8")
    (mon_dir / f"daily-formal-reviews-{formation}.json").write_text(
        json.dumps({"reviews": list(reviews)}, ensure_ascii=False), encoding="utf-8")


def make_report(*, market="市场普跌，成交清淡。", review="无需要复盘的正式推荐。",
                lifecycle="主动跟踪：0只\n仅保留评价：0条\n已完成：0条",
                reco="今天没有正式推荐：候选都未满足确认条件。"):
    return ("## 今天的市场情况\n\n" + market + "\n\n"
            "## 正式推荐股票的今日复盘\n\n" + review + "\n\n"
            "## 目前仍开放的正式推荐股票数量\n\n" + lifecycle + "\n\n"
            "## 今天明确推荐的股票\n\n" + reco + "\n")


def single_stock_report(name, code, *, review_body="复盘正文XYZ"):
    reco = ("| 顺序 | 股票 | 为什么会选它 | 最需要担心什么 |\n"
            "|---:|---|---|---|\n"
            f"| 1 | {name}（{code}） | 理由 | 担心 |\n\n"
            f"### {name}（{code}）\n\n**公司主要做什么**\n\n主营说明。\n\n"
            "**为什么会选它**\n\n选择说明。\n\n"
            "**什么情况会让我改变看法**\n\n改变说明。\n")
    review = f"### 关键节点复盘（1只）\n\n**{name}（{code}）**\n{review_body}\n"
    lifecycle = "主动跟踪：1只\n仅保留评价：0条\n已完成：0条"
    return make_report(review=review, lifecycle=lifecycle, reco=reco)


def prepared_run(isolated, monkeypatch, now=None, rerun=None,
                 prepare_status="ready_for_research",
                 agent_script=None, agent_side=None, artifacts=None,
                 sync_result=(True, "published=x"),
                 real_report_check=False, reply_text="完整报告"):
    """构造一次带假执行器的晚间运行；状态路径由 nightly_prepare_plan 决定。

    real_report_check=False：合并报告核对替换为桩；True：只替换归档/CSV
    外部边界，合并报告核对走真实函数（测试需自备归档文件与报告文本）。
    """
    now = now or at("2026-09-11", 19, 30)
    args = Args(rerun_date=rerun)
    prepare_args, slot, rerun_date, _mode = stock_ai.nightly_prepare_plan(now, args)
    path = stock_ai.state_path("nightly", slot, rerun_date)
    state = {
        "task": "nightly",
        "slot_date": slot.isoformat(),
        "rerun_date": rerun_date.isoformat() if rerun_date else None,
        "status": "running",
        "attempts": [],
    }
    stock_ai.save_state(path, state)
    calls, prompts = [], []
    timeouts: dict = {}
    if rerun_date:
        action = rerun_date.isoformat()
        formation = (rerun_date - dt.timedelta(days=1)).isoformat()
    else:
        action, formation = "2026-09-14", "2026-09-11"
    as_of = f"{formation}T18:30:00+08:00"

    def fake_run_prepare(pargs, timeout):
        calls.append(("prepare", list(pargs), timeout))
        assert pargs == prepare_args
        if prepare_status in stock_ai.READY_STATUSES:
            return 0, {"status": prepare_status,
                       "formation_date": formation, "action_date": action,
                       "selection_as_of": as_of}, ""
        return 2, {"status": prepare_status, "error": "x",
                   "formation_date": formation, "action_date": action,
                   "selection_as_of": as_of}, ""

    monkeypatch.setattr(stock_ai, "run_prepare", fake_run_prepare)

    def fake_agent(provider, prompt, final, jsonl, timeout, config, extra=None):
        calls.append(("model", provider))
        timeouts[provider] = timeout
        prompts.append(Path(prompt).read_text(encoding="utf-8"))
        if agent_side:
            agent_side(provider)
        script = agent_script or {}
        if provider in script:
            return script[provider]
        final.write_text(reply_text, encoding="utf-8")
        return 0, ""

    monkeypatch.setattr(stock_ai, "run_agent", fake_agent)

    artifacts = {"trace_ok": True, "csv_ok": True, "ledger_ok": True,
                 "report_ok": True} if artifacts is None else dict(artifacts)
    trace_flag = artifacts.get("trace_ok", False)
    csv_flag = artifacts.get("csv_ok", False)
    merged_issues = list(artifacts.get("merged_issues", []))

    def fake_frozen(formation_arg, action_arg, as_of_arg):
        return (trace_flag, "" if trace_flag else "缺少正式轨迹")

    monkeypatch.setattr(stock_ai, "frozen_trace_ok", fake_frozen)
    monkeypatch.setattr(
        stock_ai, "forward_csv_matches_trace",
        lambda f, a, s: (csv_flag, "" if csv_flag else "Forward CSV 中没有与轨迹匹配的行"),
    )
    monkeypatch.setattr(
        stock_ai, "strict_archive_check",
        lambda f, a, s: (trace_flag, "alerts=15" if trace_flag else "缺少正式轨迹"),
    )
    if not real_report_check:
        monkeypatch.setattr(
            stock_ai, "merged_report_issues",
            lambda r, f, a, s: list(merged_issues),
        )
    monkeypatch.setattr(
        stock_ai, "monitor_artifacts_status",
        lambda f: (artifacts.get("ledger_ok", False), artifacts.get("report_ok", False)),
    )
    monkeypatch.setattr(
        stock_ai, "prism_page_present",
        lambda f: artifacts.get("prism_ok", False),
    )
    monkeypatch.setattr(stock_ai, "retry_prism_sync", lambda *a, **k: sync_result)
    return path, calls, timeouts, prompts


# ---------------------------------------------------------------- 无时限语义


def test_no_time_limit_model_receives_none_and_completes(isolated, monkeypatch):
    """模拟时间远超旧 53/110 分钟：不杀进程、不切模型，任务成功且 timeout=None。"""
    path, calls, timeouts, _prompts = prepared_run(isolated, monkeypatch)
    assert stock_ai.run_nightly(Args(), {}, None, now=at("2026-09-11", 19, 30)) == stock_ai.EXIT_OK
    state = json.loads(path.read_text(encoding="utf-8"))
    assert state["result"]["status"] == "完整完成"
    assert timeouts["glm"] is None  # 无时限


def test_no_budget_minutes_attribute(isolated):
    assert not hasattr(stock_ai, "budget_minutes")
    assert not hasattr(stock_ai, "DEFAULT_BUDGET_MINUTES")
    assert not hasattr(stock_ai, "TAIL_RESERVE_SECONDS")


def test_legacy_budget_config_cannot_restore_time_limit(isolated, monkeypatch):
    """旧本机配置仍包含 110：不得恢复晚间时限。"""
    write_config(isolated,
                 budget_minutes={"nightly": 110, "preopen": 30},
                 key_sources={
                     "glm": [{"kind": "env", "name": "STOCK_AI_TEST_GLM_KEY"}],
                     "deepseek": [{"kind": "env", "name": "STOCK_AI_TEST_DS_KEY"}],
                 })
    path, _calls, timeouts, _prompts = prepared_run(isolated, monkeypatch)
    assert stock_ai.run_nightly(Args(), stock_ai.load_local_config(), None,
                                now=at("2026-09-11", 19, 30)) == stock_ai.EXIT_OK
    assert timeouts["glm"] is None


def test_prepare_keeps_technical_bound(isolated, monkeypatch):
    def fake_run_bounded(cmd, timeout, cwd=None, env=None):
        assert timeout == 15 * 60  # 资料准备窗口的技术性上限仍存在
        return 0, json.dumps({"status": "non_trading_day", "action_date": "2026-09-12"}), ""

    monkeypatch.setattr(stock_ai, "run_bounded", fake_run_bounded)
    monkeypatch.setattr(stock_ai, "run_agent", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    assert stock_ai.run_nightly(Args(), {}, None, now=at("2026-09-11", 19, 30)) == stock_ai.EXIT_OK


# ---------------------------------------------------------------- 路由


def test_default_order_is_glm_deepseek_without_astra(isolated):
    order, _ = stock_ai.resolve_provider_order("nightly", None, {}, dt.date(2026, 9, 11))
    assert order == ["glm", "deepseek"]


def test_astra_is_never_attempted_automatically(isolated):
    config = {"default_preference": "astra"}
    order, source = stock_ai.resolve_provider_order("nightly", None, config, dt.date(2026, 9, 11))
    assert order == ["glm", "deepseek"]
    config2 = {"tonight": {"date": "2026-09-11", "preference": "astra"}}
    order2, source2 = stock_ai.resolve_provider_order("nightly", None, config2, dt.date(2026, 9, 11))
    assert order2 == ["glm", "deepseek"]


def test_tonight_override_only_binds_same_day_evening_task(isolated):
    config = {"tonight": {"date": "2026-09-11", "preference": "deepseek"}}
    assert stock_ai.tonight_override(config, dt.date(2026, 9, 11)) == "deepseek"
    assert stock_ai.tonight_override(config, dt.date(2026, 9, 12)) is None
    nightly, _ = stock_ai.resolve_provider_order("nightly", None, config, dt.date(2026, 9, 11))
    preopen, _ = stock_ai.resolve_provider_order("preopen", None, config, dt.date(2026, 9, 11))
    assert nightly[0] == "deepseek" and preopen[0] == "glm"



# ---------------------------------------------------------------- 日期/prepare 形态


def test_explicit_rerun_date_uses_user_action_day():
    args = Args(rerun_date="2026-09-11")
    prepare_args, slot, rerun, mode = stock_ai.nightly_prepare_plan(at("2026-09-11", 20, 0), args)
    assert prepare_args == ["--rerun-date", "2026-09-11"]
    assert slot == dt.date(2026, 9, 10) and rerun == dt.date(2026, 9, 11) and mode


def test_window_inside_uses_no_arg_prepare():
    for day in ("2026-09-08", "2026-09-13"):
        prepare_args, slot, rerun, mode = stock_ai.nightly_prepare_plan(at(day, 18, 50), Args())
        assert prepare_args == [] and rerun is None and not mode
        assert slot == dt.date.fromisoformat(day)


def test_late_start_uses_rerun_date_of_next_natural_day():
    args_list, _s, rerun, mode = stock_ai.nightly_prepare_plan(at("2026-09-11", 19, 30), Args())
    assert args_list == ["--rerun-date", "2026-09-12"] and rerun == dt.date(2026, 9, 12) and mode
    args_list, _s, rerun, _m = stock_ai.nightly_prepare_plan(at("2026-09-12", 19, 30), Args())
    assert args_list == ["--rerun-date", "2026-09-13"]
    args_list, _s, rerun, _m = stock_ai.nightly_prepare_plan(at("2026-09-13", 19, 30), Args())
    assert args_list == ["--rerun-date", "2026-09-14"]


def test_early_start_keeps_original_window_restriction():
    args_list, _s, rerun, mode = stock_ai.nightly_prepare_plan(at("2026-09-11", 18, 30), Args())
    assert args_list == [] and rerun is None and not mode


# ---------------------------------------------------------------- 晚间主流程


def test_nightly_scheduled_before_window_skips(isolated, capsys, monkeypatch):
    monkeypatch.setattr(stock_ai, "run_prepare", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    assert stock_ai.run_nightly(Args(scheduled=True), {}, None, now=at("2026-09-14", 8, 0)) == stock_ai.EXIT_OK
    assert "启动窗口" in capsys.readouterr().out


def test_nightly_friday_evening_reports_non_trading_day(isolated, capsys, monkeypatch):
    calls = []

    def fake_run_prepare(args, timeout):
        calls.append(args)
        return 0, {"status": "non_trading_day", "action_date": "2026-09-12"}, ""

    monkeypatch.setattr(stock_ai, "run_prepare", fake_run_prepare)
    monkeypatch.setattr(stock_ai, "run_agent", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    assert stock_ai.run_nightly(Args(), {}, None, now=at("2026-09-11", 19, 30)) == stock_ai.EXIT_OK
    assert calls == [["--rerun-date", "2026-09-12"]]
    out = capsys.readouterr().out
    assert "不是交易日" in out
    assert "完整完成" not in out  # 正常跳过不得声称生成研究报告


def test_nightly_sunday_evening_uses_sunday_cutoff_for_monday(isolated, monkeypatch, capsys):
    seen = []

    def fake_run_prepare(args, timeout):
        seen.append(args)
        return 0, {"status": "ready_for_research", "formation_date": "2026-09-11",
                   "action_date": "2026-09-14", "selection_as_of": "2026-09-13T18:30:00+08:00"}, ""

    monkeypatch.setattr(stock_ai, "run_prepare", fake_run_prepare)

    def fake_agent(provider, prompt, final, jsonl, timeout, config, extra=None):
        assert timeout is None  # 无时限
        final.write_text("报告", encoding="utf-8")
        return 0, ""

    monkeypatch.setattr(stock_ai, "run_agent", fake_agent)
    monkeypatch.setattr(stock_ai, "retry_prism_sync", lambda *a, **k: (True, "published=unchanged"))
    # 收尾完成检查的外部边界桩（报告核对已被夹具/本测试替换为可过）
    monkeypatch.setattr(stock_ai, "strict_archive_check", lambda f, a, s: (True, "alerts=3"))
    monkeypatch.setattr(stock_ai, "forward_csv_matches_trace", lambda f, a, s: (True, ""))
    monkeypatch.setattr(stock_ai, "merged_report_issues", lambda r, f, a, s: [])
    assert stock_ai.run_nightly(Args(), {}, None, now=at("2026-09-13", 19, 30)) == stock_ai.EXIT_OK
    assert seen == [["--rerun-date", "2026-09-14"]]
    state = stock_ai.load_state("nightly", dt.date(2026, 9, 13), dt.date(2026, 9, 14))
    assert state["formation_date"] == "2026-09-11"
    assert state["selection_as_of"] == "2026-09-13T18:30:00+08:00"


def test_nightly_early_manual_run_fails_honestly(isolated, monkeypatch, capsys):
    monkeypatch.setattr(
        stock_ai, "run_prepare",
        lambda args, timeout: (2, {"status": "outside_selection_window"}, ""),
    )
    monkeypatch.setattr(stock_ai, "run_agent", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    assert stock_ai.run_nightly(Args(), {}, None, now=at("2026-09-11", 18, 30)) == stock_ai.EXIT_FAIL
    assert "outside_selection_window" in capsys.readouterr().out


def test_nightly_success_records_complete_result(isolated, monkeypatch, capsys):
    path, calls, timeouts, _p = prepared_run(isolated, monkeypatch)
    assert stock_ai.run_nightly(Args(), {}, None, now=at("2026-09-11", 19, 30)) == stock_ai.EXIT_OK
    state = json.loads(path.read_text(encoding="utf-8"))
    assert state["result"]["status"] == "完整完成"
    assert [c for c in calls if c[0] == "model"] == [("model", "glm")]
    assert timeouts["glm"] is None


def test_nightly_quota_failure_falls_back_no_budget_split(isolated, monkeypatch, fake_keys):
    """额度失败接替备用；使用本测试临时配置，不回落真实凭据来源。"""
    path, calls, timeouts, _p = prepared_run(
        isolated, monkeypatch,
        agent_script={"glm": (1, "Error: HTTP 402: provider quota exhausted")},
    )
    assert stock_ai.run_nightly(Args(), stock_ai.load_local_config(), None,
                                now=at("2026-09-11", 19, 30)) == stock_ai.EXIT_OK
    models = [c[1] for c in calls if c[0] == "model"]
    assert models == ["glm", "deepseek"]  # 额度不足 → 接替
    assert timeouts["deepseek"] is None  # 备用同样无时限
    state = json.loads(path.read_text(encoding="utf-8"))
    outcomes = {a["provider"]: a["outcome"] for a in state["attempts"]}
    assert outcomes == {"glm": "failed", "deepseek": "success"}


def test_nightly_local_error_does_not_fallback(isolated, monkeypatch):
    path, calls, _t, _p = prepared_run(
        isolated, monkeypatch,
        agent_script={"glm": (1, "Traceback (most recent call last):\nFileNotFoundError: snapshot does not exist")},
    )
    assert stock_ai.run_nightly(Args(), {}, None, now=at("2026-09-11", 19, 30)) == stock_ai.EXIT_FAIL
    models = [c[1] for c in calls if c[0] == "model"]
    assert models == ["glm"]  # 本地错误不接替
    state = json.loads(path.read_text(encoding="utf-8"))
    assert "本地/数据" in state["attempts"][-1]["reason"]


def test_nightly_context_breaker_is_config_error_not_quota(isolated, monkeypatch):
    path, calls, _t, _p = prepared_run(
        isolated, monkeypatch,
        agent_script={"glm": (1, "Error: Autocompact stopped because the context refilled within fewer than 3 tool turns")},
    )
    assert stock_ai.run_nightly(Args(), {}, None, now=at("2026-09-11", 19, 30)) == stock_ai.EXIT_FAIL
    models = [c[1] for c in calls if c[0] == "model"]
    assert models == ["glm"]  # 上下文配置/执行错误不当作额度问题接替
    state = json.loads(path.read_text(encoding="utf-8"))
    assert "上下文" in state["attempts"][-1]["reason"]


def test_nightly_both_unavailable_saves_then_notifies_once(isolated, monkeypatch, mac_log):
    """模拟两路不可用：失败先落盘，再一次 Mac 通知；通知不参与模型链路。"""
    path, calls, _t, _p = prepared_run(
        isolated, monkeypatch,
        agent_script={"glm": (1, "Error: HTTP 402: provider quota exhausted"),
                      "deepseek": (1, "Error: HTTP 502 bad gateway")},
    )
    assert stock_ai.run_nightly(Args(), {}, None, now=at("2026-09-11", 19, 30)) == stock_ai.EXIT_FAIL
    models = [c[1] for c in calls if c[0] == "model"]
    assert models == ["glm", "deepseek"]  # Astra 为 0
    entries = [json.loads(l) for l in stock_ai.INDEX_PATH.read_text(encoding="utf-8").splitlines()
               if l.strip()]
    failure = next(e for e in entries if e.get("result_status") == "失败")
    assert [a["provider"] for a in failure["attempts"]] == ["glm", "deepseek"]
    assert failure["mac_notification"]["ok"] is True
    assert failure["stage"] == "模型执行"
    assert len(mac_log) == 1
    assert "nightly" in mac_log[0] and ("额度" in mac_log[0] or "失败" in mac_log[0])
    state = json.loads(path.read_text(encoding="utf-8"))
    assert state["result"]["status"] == "失败"


def test_nightly_missing_key_skips_and_falls_back(isolated, monkeypatch):
    monkeypatch.delenv("STOCK_AI_TEST_GLM_KEY", raising=False)
    monkeypatch.delenv("STOCK_AI_TEST_DS_KEY", raising=False)
    seen = []

    def fake_agent(provider, prompt, final, jsonl, timeout, config, extra=None):
        seen.append(provider)
        return 1, "401 unauthorized"

    monkeypatch.setattr(stock_ai, "run_agent", fake_agent)
    path, _c, _t, _p = prepared_run(isolated, monkeypatch)
    assert stock_ai.run_nightly(Args(), {}, None, now=at("2026-09-11", 19, 30)) == stock_ai.EXIT_FAIL
    assert seen == []
    state = json.loads(path.read_text(encoding="utf-8"))
    skipped = {a["provider"] for a in state["attempts"] if a["outcome"] == "skipped"}
    assert skipped == {"glm", "deepseek"}
    assert all("未启动" in a["reason"] for a in state["attempts"] if a["outcome"] == "skipped")


def _completed_state(isolated, path, *, rerun="2026-09-14", identity=True):
    reply_rel = f"local_archive/ai_tasks/nightly/rerun-{rerun}/final-reply.md"
    reply_abs = isolated / reply_rel
    reply_abs.parent.mkdir(parents=True, exist_ok=True)
    reply_abs.write_text("完整报告", encoding="utf-8")
    state = {"task": "nightly", "slot_date": rerun and "2026-09-13",
             "rerun_date": rerun, "status": "completed",
             "result": {"status": "完整完成", "detail": "已归档"}, "attempts": []}
    if identity:
        state.update({
            "formation_date": "2026-09-11", "action_date": rerun,
            "selection_as_of": "2026-09-13T18:30:00+08:00", "final_reply": reply_rel,
        })
    stock_ai.save_state(path, state)
    return state


def test_nightly_completed_normal_state_blocks_same_evening(isolated, monkeypatch, capsys):
    now = at("2026-09-13", 19, 30)
    path = stock_ai.state_path("nightly", dt.date(2026, 9, 13), dt.date(2026, 9, 14))
    _completed_state(isolated, path)
    monkeypatch.setattr(stock_ai, "strict_archive_check", lambda f, a, s: (True, "alerts=3"))
    monkeypatch.setattr(stock_ai, "forward_csv_matches_trace", lambda f, a, s: (True, ""))
    monkeypatch.setattr(stock_ai, "merged_report_issues", lambda r, f, a, s: [])
    monkeypatch.setattr(stock_ai, "run_prepare", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    monkeypatch.setattr(stock_ai, "run_agent", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    assert stock_ai.run_nightly(Args(), {}, None, now=now) == stock_ai.EXIT_OK
    assert "不会重新研究" in capsys.readouterr().out


def test_nightly_completed_rerun_blocks_identical_rerun_only(isolated, monkeypatch, capsys):
    rerun = dt.date(2026, 9, 11)
    path = stock_ai.state_path("nightly", dt.date(2026, 9, 10), rerun)
    reply_rel = "local_archive/ai_tasks/nightly/rerun-2026-09-11/final-reply.md"
    reply_abs = isolated / reply_rel
    reply_abs.parent.mkdir(parents=True, exist_ok=True)
    reply_abs.write_text("补跑完整报告", encoding="utf-8")
    stock_ai.save_state(path, {
        "task": "nightly", "slot_date": "2026-09-10", "rerun_date": "2026-09-11",
        "status": "completed", "result": {"status": "完整完成", "detail": "补跑已完成"},
        "attempts": [], "formation_date": "2026-09-10", "action_date": "2026-09-11",
        "selection_as_of": "2026-09-10T18:30:00+08:00", "final_reply": reply_rel})
    other = stock_ai.state_path("nightly", dt.date(2026, 9, 11), dt.date(2026, 9, 12))
    assert other != path and not other.exists()
    monkeypatch.setattr(stock_ai, "strict_archive_check", lambda f, a, s: (True, "alerts=3"))
    monkeypatch.setattr(stock_ai, "forward_csv_matches_trace", lambda f, a, s: (True, ""))
    monkeypatch.setattr(stock_ai, "merged_report_issues", lambda r, f, a, s: [])
    monkeypatch.setattr(stock_ai, "run_prepare", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    monkeypatch.setattr(stock_ai, "run_agent", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    assert stock_ai.run_nightly(Args(rerun_date="2026-09-11"), {}, None,
                                now=at("2026-09-11", 20, 0)) == stock_ai.EXIT_OK
    assert "不会重新研究" in capsys.readouterr().out


def test_nightly_completed_without_identity_is_not_success(isolated, monkeypatch, capsys):
    """已标完整完成却缺时间身份/报告路径：不能直接返回成功。"""
    now = at("2026-09-13", 19, 30)
    path = stock_ai.state_path("nightly", dt.date(2026, 9, 13), dt.date(2026, 9, 14))
    stock_ai.save_state(path, {
        "task": "nightly", "slot_date": "2026-09-13", "rerun_date": "2026-09-14",
        "status": "completed", "result": {"status": "完整完成", "detail": "旧完成"},
        "attempts": []})
    monkeypatch.setattr(stock_ai, "run_prepare", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    monkeypatch.setattr(stock_ai, "run_agent", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    assert stock_ai.run_nightly(Args(), {}, None, now=now) == stock_ai.EXIT_FAIL
    out = capsys.readouterr().out
    assert "缺少时间身份" in out
    state = json.loads(path.read_text(encoding="utf-8"))
    assert state["result"]["status"] == "失败"


def test_nightly_valid_prepare_reused(isolated, monkeypatch):
    now = at("2026-09-11", 20, 0)
    path = stock_ai.state_path("nightly", dt.date(2026, 9, 10), dt.date(2026, 9, 11))
    state = {"task": "nightly", "slot_date": "2026-09-10", "rerun_date": "2026-09-11",
             "status": "running", "attempts": [],
             "prepare": {"status": "ready_for_research", "formation_date": "2026-09-10",
                         "action_date": "2026-09-11", "selection_as_of": "2026-09-10T18:30:00+08:00"},
             "formation_date": "2026-09-10", "action_date": "2026-09-11",
             "selection_as_of": "2026-09-10T18:30:00+08:00", "rerun_mode": True}
    stock_ai.save_state(path, state)

    def fail_prepare(args, timeout):
        raise AssertionError("合法 prepare 不应重复运行")

    monkeypatch.setattr(stock_ai, "run_prepare", fail_prepare)

    def fake_agent(provider, prompt, final, jsonl, timeout, config, extra=None):
        assert timeout is None
        final.write_text("报告", encoding="utf-8")
        return 0, ""

    monkeypatch.setattr(stock_ai, "run_agent", fake_agent)
    monkeypatch.setattr(stock_ai, "retry_prism_sync", lambda *a, **k: (True, "published=unchanged"))
    monkeypatch.setattr(stock_ai, "strict_archive_check", lambda f, a, s: (True, "alerts=3"))
    monkeypatch.setattr(stock_ai, "forward_csv_matches_trace", lambda f, a, s: (True, ""))
    monkeypatch.setattr(stock_ai, "merged_report_issues", lambda r, f, a, s: [])
    assert stock_ai.run_nightly(Args(rerun_date="2026-09-11"), {}, None, now=now) == stock_ai.EXIT_OK


def test_nightly_broken_prepare_is_rerun_not_reused(isolated, monkeypatch):
    """失败/字段不全的 prepare 不得复用，应重新准备。"""
    now = at("2026-09-11", 19, 30)
    path = stock_ai.state_path("nightly", dt.date(2026, 9, 11), dt.date(2026, 9, 12))
    state = {"task": "nightly", "slot_date": "2026-09-11", "rerun_date": "2026-09-12",
             "status": "running", "attempts": [],
             "prepare": {"status": "error", "error": "上一次失败"}}
    stock_ai.save_state(path, state)
    calls = []

    def fake_run_prepare(args, timeout):
        calls.append(args)
        return 0, {"status": "ready_for_research", "formation_date": "2026-09-11",
                   "action_date": "2026-09-12", "selection_as_of": "2026-09-11T18:30:00+08:00"}, ""

    monkeypatch.setattr(stock_ai, "run_prepare", fake_run_prepare)

    def fake_agent(provider, prompt, final, jsonl, timeout, config, extra=None):
        final.write_text("报告", encoding="utf-8")
        return 0, ""

    monkeypatch.setattr(stock_ai, "run_agent", fake_agent)
    monkeypatch.setattr(stock_ai, "retry_prism_sync", lambda *a, **k: (True, "published=unchanged"))
    monkeypatch.setattr(stock_ai, "strict_archive_check", lambda f, a, s: (True, "alerts=3"))
    monkeypatch.setattr(stock_ai, "forward_csv_matches_trace", lambda f, a, s: (True, ""))
    monkeypatch.setattr(stock_ai, "merged_report_issues", lambda r, f, a, s: [])
    assert stock_ai.run_nightly(Args(), {}, None, now=now) == stock_ai.EXIT_OK
    assert calls == [["--rerun-date", "2026-09-12"]]
    state = json.loads(path.read_text(encoding="utf-8"))
    assert state["prepare"]["status"] == "ready_for_research"


def test_nightly_rerun_data_not_ready_supplements_once(isolated, monkeypatch):
    now = at("2026-09-11", 20, 0)
    path = stock_ai.state_path("nightly", dt.date(2026, 9, 10), dt.date(2026, 9, 11))
    stock_ai.save_state(path, {"task": "nightly", "slot_date": "2026-09-10",
                               "rerun_date": "2026-09-11", "status": "running", "attempts": []})
    stages = []

    def fake_run_prepare(args, timeout):
        if not stages:
            return 2, {"status": "data_not_ready", "formation_date": "2026-09-10",
                       "action_date": "2026-09-11", "selection_as_of": "2026-09-10T18:30:00+08:00"}, ""
        return 0, {"status": "ready_for_research_limited", "formation_date": "2026-09-10",
                   "action_date": "2026-09-11", "selection_as_of": "2026-09-10T18:30:00+08:00"}, ""

    monkeypatch.setattr(stock_ai, "run_prepare", fake_run_prepare)
    monkeypatch.setattr(
        stock_ai, "run_pre_research_stage",
        lambda f, a, t: (stages.append((f, a, t)), (True, ""))[1],
    )

    def fake_agent(provider, prompt, final, jsonl, timeout, config, extra=None):
        assert timeout is None
        final.write_text("报告", encoding="utf-8")
        return 0, ""

    monkeypatch.setattr(stock_ai, "run_agent", fake_agent)
    monkeypatch.setattr(stock_ai, "retry_prism_sync", lambda *a, **k: (True, "published=unchanged"))
    monkeypatch.setattr(stock_ai, "strict_archive_check", lambda f, a, s: (True, "alerts=3"))
    monkeypatch.setattr(stock_ai, "forward_csv_matches_trace", lambda f, a, s: (True, ""))
    monkeypatch.setattr(stock_ai, "merged_report_issues", lambda r, f, a, s: [])
    assert stock_ai.run_nightly(Args(rerun_date="2026-09-11"), {}, None, now=now) == stock_ai.EXIT_OK
    assert stages == [("2026-09-10", "2026-09-10T18:30:00+08:00", stages[0][2])]


def test_nightly_rerun_still_data_not_ready_ends_without_loop(isolated, monkeypatch):
    now = at("2026-09-11", 20, 0)
    path = stock_ai.state_path("nightly", dt.date(2026, 9, 10), dt.date(2026, 9, 11))
    stock_ai.save_state(path, {"task": "nightly", "slot_date": "2026-09-10",
                               "rerun_date": "2026-09-11", "status": "running", "attempts": []})
    stage_calls = []

    def fake_run_prepare(args, timeout):
        return 2, {"status": "data_not_ready", "formation_date": "2026-09-10",
                   "action_date": "2026-09-11", "selection_as_of": "2026-09-10T18:30:00+08:00"}, ""

    monkeypatch.setattr(stock_ai, "run_prepare", fake_run_prepare)
    monkeypatch.setattr(
        stock_ai, "run_pre_research_stage",
        lambda f, a, t: (stage_calls.append((f, a)), (True, ""))[1],
    )
    monkeypatch.setattr(stock_ai, "run_agent", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    assert stock_ai.run_nightly(Args(rerun_date="2026-09-11"), {}, None, now=now) == stock_ai.EXIT_FAIL
    assert len(stage_calls) == 1


def test_nightly_rerun_data_not_ready_without_dates_fails_without_guess(isolated, monkeypatch):
    now = at("2026-09-11", 20, 0)
    path = stock_ai.state_path("nightly", dt.date(2026, 9, 10), dt.date(2026, 9, 11))
    stock_ai.save_state(path, {"task": "nightly", "slot_date": "2026-09-10",
                               "rerun_date": "2026-09-11", "status": "running", "attempts": []})
    monkeypatch.setattr(
        stock_ai, "run_prepare",
        lambda args, timeout: (2, {"status": "data_not_ready", "error": "calendar missing"}, ""),
    )
    monkeypatch.setattr(
        stock_ai, "run_pre_research_stage",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("日历缺失不得补猜日期")),
    )
    assert stock_ai.run_nightly(Args(rerun_date="2026-09-11"), {}, None, now=now) == stock_ai.EXIT_FAIL


# ---------------------------------------------------------------- 恢复与完成判定


def test_nightly_csv_trace_mismatch_fails_honestly(isolated, monkeypatch, capsys):
    path, _calls, _t, _p = prepared_run(
        isolated, monkeypatch, now=at("2026-09-11", 20, 0), rerun="2026-09-11",
        prepare_status="already_selected",
        artifacts={"trace_ok": True, "csv_ok": False},
    )
    monkeypatch.setattr(stock_ai, "run_agent", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    assert stock_ai.run_nightly(Args(rerun_date="2026-09-11"), {}, None,
                                now=at("2026-09-11", 20, 0)) == stock_ai.EXIT_FAIL
    assert "不一致" in capsys.readouterr().out
    state = json.loads(path.read_text(encoding="utf-8"))
    assert [a for a in state["attempts"] if a.get("outcome") == "failed"] == []


def test_nightly_frozen_trace_forces_already_selected_preamble(isolated, monkeypatch):
    _path, _calls, _t, prompts = prepared_run(isolated, monkeypatch)
    monkeypatch.setattr(stock_ai, "retry_prism_sync", lambda *a, **k: (True, "published=unchanged"))
    assert stock_ai.run_nightly(Args(), {}, None, now=at("2026-09-11", 19, 30)) == stock_ai.EXIT_OK
    assert prompts and "已经冻结" in prompts[0] and "不得重新选股" in prompts[0]


def test_nightly_archives_complete_but_web_missing_runs_sync_only(isolated, monkeypatch, capsys):
    """已归档、缺合并回复与网页：模型为 0 时仅同步不可行；有回复时仅同步。"""
    path, calls, _t, _p = prepared_run(
        isolated, monkeypatch,
        artifacts={"trace_ok": True, "csv_ok": True, "ledger_ok": True,
                   "report_ok": True, "prism_ok": True},
    )
    sync_calls = []

    def fake_sync(*a, **k):
        sync_calls.append(a)
        return True, "published=unchanged"

    monkeypatch.setattr(stock_ai, "retry_prism_sync", fake_sync)
    archive_dir = isolated / "local_archive" / "ai_tasks" / "nightly" / "rerun-2026-09-12"
    archive_dir.mkdir(parents=True)
    (archive_dir / "final-reply.md").write_text("合并报告", encoding="utf-8")
    monkeypatch.setattr(stock_ai, "run_agent", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    assert stock_ai.run_nightly(Args(), {}, None, now=at("2026-09-11", 19, 30)) == stock_ai.EXIT_OK
    assert [c for c in calls if c[0] == "model"] == []
    assert len(sync_calls) == 1
    assert "直接收尾" in capsys.readouterr().out


def test_nightly_sync_failure_after_full_archive_marks_display_pending(isolated, monkeypatch):
    path, _calls, _t, _p = prepared_run(
        isolated, monkeypatch,
        sync_result=(False, "render error"),
    )
    assert stock_ai.run_nightly(Args(), {}, None, now=at("2026-09-11", 19, 30)) == stock_ai.EXIT_FAIL
    state = json.loads(path.read_text(encoding="utf-8"))
    assert state["result"]["status"] == "研究已归档但展示待更新"


def test_nightly_skipped_newer_reported_as_homepage_not_switched(isolated, monkeypatch):
    path, _calls, _t, _p = prepared_run(
        isolated, monkeypatch,
        sync_result=(True, "published=skipped_newer /x/prism.html"),
    )
    assert stock_ai.run_nightly(Args(), {}, None, now=at("2026-09-11", 19, 30)) == stock_ai.EXIT_OK
    state = json.loads(path.read_text(encoding="utf-8"))
    assert "首页未切" in state["result"]["detail"]


def test_missing_heading_with_sync_success_still_fails(isolated, monkeypatch, fake_forward_selection):
    """反例（真实收尾函数）：缺总标题 + 网页同步成功 → 仍非零，不放行、不同步。"""
    formation, action, as_of = "2026-09-11", "2026-09-12", "2026-09-11T18:30:00+08:00"
    write_report_archives(isolated, formation, action, as_of)
    path, calls, _t, _p = prepared_run(
        isolated, monkeypatch, real_report_check=True,
        reply_text="这份文本没有任何必需标题。")
    sync_calls = []
    monkeypatch.setattr(
        stock_ai, "retry_prism_sync",
        lambda *a, **k: sync_calls.append(a) or (True, "published=x"))
    assert stock_ai.run_nightly(Args(), {}, None, now=at("2026-09-11", 19, 30)) == stock_ai.EXIT_FAIL
    state = json.loads(path.read_text(encoding="utf-8"))
    assert state["result"]["status"] == "合并报告待修复"
    assert "缺少必需总标题" in state["result"]["detail"]
    assert [c for c in calls if c[0] == "model"] == [("model", "glm")]
    assert sync_calls == []  # 检查未通过不得用网页同步放行


def test_csv_mismatch_after_model_with_sync_success_still_fails(isolated, monkeypatch, fake_forward_selection):
    """反例（真实收尾函数）：CSV 不一致 + 网页同步成功 → 失败，不是完整完成。"""
    formation, action, as_of = "2026-09-11", "2026-09-12", "2026-09-11T18:30:00+08:00"
    write_report_archives(isolated, formation, action, as_of)
    model_started = [False]

    def csv_after_model(f, a, s):
        # 模型执行后 CSV 变为不一致（模拟接替前核对与收尾核对之间被破坏）。
        return (not model_started[0], "" if not model_started[0] else "行数不一致：CSV 0 行，应为 1 行")

    path, calls, _t, _p = prepared_run(
        isolated, monkeypatch, real_report_check=True,
        reply_text=make_report(),
        agent_side=lambda provider: model_started.__setitem__(0, True),
    )
    monkeypatch.setattr(stock_ai, "forward_csv_matches_trace", csv_after_model)
    sync_calls = []
    monkeypatch.setattr(
        stock_ai, "retry_prism_sync",
        lambda *a, **k: sync_calls.append(a) or (True, "published=x"))
    assert stock_ai.run_nightly(Args(), {}, None, now=at("2026-09-11", 19, 30)) == stock_ai.EXIT_FAIL
    state = json.loads(path.read_text(encoding="utf-8"))
    assert state["result"]["status"] == "失败"
    assert "行数不一致" in state["result"]["detail"]
    assert [c for c in calls if c[0] == "model"] == [("model", "glm")]
    assert sync_calls == []


def test_completed_recheck_csv_mismatch_with_sync_success_still_fails(isolated, monkeypatch, mac_log):
    """反例（旧 completed 复核真实路径）：CSV 不一致 + 同步成功 → 非零、非完整完成、零模型。"""
    now = at("2026-09-13", 19, 30)
    path = stock_ai.state_path("nightly", dt.date(2026, 9, 13), dt.date(2026, 9, 14))
    _completed_state(isolated, path)
    monkeypatch.setattr(stock_ai, "strict_archive_check", lambda f, a, s: (True, "alerts=3"))
    monkeypatch.setattr(stock_ai, "forward_csv_matches_trace",
                        lambda f, a, s: (False, "行数不一致：CSV 0 行，应为 2 行"))
    monkeypatch.setattr(stock_ai, "merged_report_issues", lambda r, f, a, s: [])
    sync_calls = []
    monkeypatch.setattr(
        stock_ai, "retry_prism_sync",
        lambda *a, **k: sync_calls.append(a) or (True, "published=x"))
    monkeypatch.setattr(stock_ai, "run_agent", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    assert stock_ai.run_nightly(Args(), {}, None, now=now) == stock_ai.EXIT_FAIL
    state = json.loads(path.read_text(encoding="utf-8"))
    assert state["result"]["status"] == "失败"
    assert "行数不一致" in state["result"]["detail"]
    assert sync_calls == []
    assert mac_log  # 需处理 → 提示一次
    assert len(mac_log) == 1


def test_completed_state_with_bad_report_is_not_success(isolated, monkeypatch, capsys):
    now = at("2026-09-13", 19, 30)
    path = stock_ai.state_path("nightly", dt.date(2026, 9, 13), dt.date(2026, 9, 14))
    _completed_state(isolated, path)
    monkeypatch.setattr(
        stock_ai, "strict_archive_check", lambda f, a, s: (True, "alerts=15"))
    monkeypatch.setattr(stock_ai, "forward_csv_matches_trace", lambda f, a, s: (True, ""))
    monkeypatch.setattr(
        stock_ai, "merged_report_issues",
        lambda r, f, a, s: ["缺少必需总标题：## 正式推荐股票的今日复盘"])
    monkeypatch.setattr(stock_ai, "run_agent",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    assert stock_ai.run_nightly(Args(), {}, None, now=now) == stock_ai.EXIT_FAIL
    state = json.loads(path.read_text(encoding="utf-8"))
    assert state["result"]["status"] == "合并报告待修复"  # 旧 completed 不无条件成功


def test_same_identity_reply_reuse_from_other_slot(isolated, monkeypatch):
    """同身份不同目录的有效回复可复用，不开模型。"""
    now = at("2026-09-13", 19, 30)
    path, calls, _t, _p = prepared_run(isolated, monkeypatch, now=now)
    other_rel = "local_archive/ai_tasks/nightly/nightly-2026-09-13/final-reply.md"
    other_abs = isolated / other_rel
    other_abs.parent.mkdir(parents=True)
    other_abs.write_text("同身份完整报告", encoding="utf-8")
    stock_ai.save_state(stock_ai.state_path("nightly", dt.date(2026, 9, 13)), {
        "task": "nightly", "slot_date": "2026-09-13", "status": "completed",
        "formation_date": "2026-09-13", "action_date": "2026-09-14",
        "selection_as_of": "2026-09-13T18:30:00+08:00", "final_reply": other_rel,
        "result": {"status": "完整完成", "finished_at": "2026-09-13T20:00:00"},
        "attempts": []})
    assert stock_ai.run_nightly(Args(), {}, None, now=now) == stock_ai.EXIT_OK
    assert [c for c in calls if c[0] == "model"] == []  # 复用，不再开模型
    assert (isolated / "local_archive/ai_tasks/nightly/rerun-2026-09-14/final-reply.md").exists()
    state = json.loads(path.read_text(encoding="utf-8"))
    assert state["result"]["status"] == "完整完成"


def test_reply_with_other_identity_not_reused(isolated, monkeypatch):
    """没有本身份详评时，其他日期外观合格的报告不得复用（走模型按 already_selected 补全）。"""
    now = at("2026-09-13", 19, 30)
    path, calls, _t, _p = prepared_run(isolated, monkeypatch, now=now)
    other_rel = "local_archive/ai_tasks/nightly/nightly-2026-08-10/final-reply.md"
    other_abs = isolated / other_rel
    other_abs.parent.mkdir(parents=True)
    other_abs.write_text("别的日期的外观合格报告", encoding="utf-8")
    stock_ai.save_state(stock_ai.state_path("nightly", dt.date(2026, 8, 10)), {
        "task": "nightly", "slot_date": "2026-08-10", "status": "completed",
        "formation_date": "2026-08-07", "action_date": "2026-08-10",
        "selection_as_of": "2026-08-09T18:30:00+08:00", "final_reply": other_rel,
        "result": {"status": "完整完成", "finished_at": "2026-08-10T20:00:00"},
        "attempts": []})
    assert stock_ai.run_nightly(Args(), {}, None, now=now) == stock_ai.EXIT_OK
    assert [c for c in calls if c[0] == "model"] == [("model", "glm")]  # 未复用，走模型补全


def test_find_existing_reply_requires_matching_as_of(isolated, monkeypatch):
    monkeypatch.setattr(stock_ai, "merged_report_issues", lambda r, f, a, s: [])
    formation, action, as_of = "2026-09-10", "2026-09-11", "2026-09-10T18:30:00+08:00"
    for slot, record_as_of in (("nightly-2026-09-10", "2026-09-10T18:00:00+08:00"),
                               ("nightly-rerun-2026-09-11", as_of)):
        rel = f"local_archive/ai_tasks/nightly/{slot}/final-reply.md"
        abs_path = isolated / rel
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text("报告", encoding="utf-8")
        stock_ai.save_state(stock_ai.STATE_DIR / f"{slot}.json", {
            "task": "nightly", "slot_date": slot, "status": "completed",
            "formation_date": formation, "action_date": action,
            "selection_as_of": record_as_of, "final_reply": rel, "attempts": []})
    found = stock_ai.find_existing_reply(formation, action, as_of)
    assert found is not None
    assert "nightly-rerun-2026-09-11" in str(found)  # as_of 不一致的记录不被认领


# ---------------------------------------------------------------- 次晨任务


def test_preopen_scheduled_before_window_skips(isolated, capsys, monkeypatch):
    def fail_prepare(timeout):
        raise AssertionError("窗口前不得运行 prepare")

    monkeypatch.setattr(stock_ai, "run_preopen_prepare", fail_prepare)
    assert stock_ai.run_preopen(Args(scheduled=True), {}, None, now=at("2026-09-12", 8, 0)) == stock_ai.EXIT_OK
    assert "08:45" in capsys.readouterr().out


def test_preopen_scheduled_after_0930_runs_prepare_and_reports_limited(isolated, monkeypatch, capsys, mac_log):
    """交易日晚启：由原 prepare 判定错过窗口，记受限结果并提示，不请求公告/停牌。"""
    monkeypatch.setattr(
        stock_ai, "run_preopen_prepare",
        lambda timeout: (0, {"status": "data_limited", "action_date": "2026-09-14",
                             "new_announcements": [], "suspended_stocks": [],
                             "limitations": ["安全检查启动时已经开盘，不能作为开盘前提醒"]}, ""))
    assert stock_ai.run_preopen(Args(scheduled=True), {}, None,
                                now=at("2026-09-14", 9, 31)) == stock_ai.EXIT_FAIL
    out = capsys.readouterr().out
    assert "已经开盘" in out and "部分完成" in out
    assert len(mac_log) == 1
    entries = [json.loads(l) for l in stock_ai.INDEX_PATH.read_text(encoding="utf-8").splitlines()
               if l.strip()]
    assert entries[-1]["stage"] == "prepare"


def test_preopen_late_start_on_closed_day_skips_normally(isolated, monkeypatch, capsys, mac_log):
    """休市日晚启：原 prepare 判休市 → 正常跳过，不误报、不弹通知。"""
    monkeypatch.setattr(
        stock_ai, "run_preopen_prepare",
        lambda timeout: (0, {"status": "no_action_day", "new_announcements": [],
                             "suspended_stocks": []}, ""))
    assert stock_ai.run_preopen(Args(scheduled=True), {}, None,
                                now=at("2026-09-12", 9, 31)) == stock_ai.EXIT_OK
    out = capsys.readouterr().out
    assert "休市" in out
    assert mac_log == []


def test_preopen_no_new_changes_needs_no_model(isolated, capsys, monkeypatch, mac_log):
    monkeypatch.setattr(
        stock_ai, "run_preopen_prepare",
        lambda timeout: (0, {"status": "no_new_changes", "new_announcements": [], "suspended_stocks": []}, ""),
    )
    monkeypatch.setattr(stock_ai, "run_agent", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    assert stock_ai.run_preopen(Args(), {}, None, now=at("2026-09-14", 8, 50)) == stock_ai.EXIT_OK
    assert "没有发现需要改变昨晚参与条件的新情况" in capsys.readouterr().out
    assert mac_log == []


def test_preopen_no_formal_trace_is_partial_not_no_change(isolated, monkeypatch, capsys, mac_log):
    """交易日缺昨晚轨迹：说清检查未完成，不等同“没有新变化”，需处理并提示。"""
    monkeypatch.setattr(
        stock_ai, "run_preopen_prepare",
        lambda timeout: (0, {"status": "no_formal_trace", "new_announcements": [],
                             "suspended_stocks": []}, ""))
    assert stock_ai.run_preopen(Args(), {}, None, now=at("2026-09-14", 8, 50)) == stock_ai.EXIT_FAIL
    out = capsys.readouterr().out
    assert "轨迹" in out and "未完成" in out
    assert "没有发现需要改变昨晚参与条件的新情况" not in out
    assert len(mac_log) == 1


def test_preopen_prepare_none_records_failure_and_notifies(isolated, monkeypatch, mac_log):
    """prepare 未返回 JSON：统一失败收尾（状态+索引+日志+通知），不能只 print。"""
    monkeypatch.setattr(stock_ai, "run_preopen_prepare", lambda timeout: (3, None, "boom"))
    now = at("2026-09-14", 8, 50)
    assert stock_ai.run_preopen(Args(), {}, None, now=now) == stock_ai.EXIT_FAIL
    state_path = stock_ai.STATE_DIR / f"preopen-{now.date().isoformat()}.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["status"] == "failed" and state["result"]["status"] == "失败"
    entries = [json.loads(l) for l in stock_ai.INDEX_PATH.read_text(encoding="utf-8").splitlines()
               if l.strip()]
    assert entries[-1]["stage"] == "prepare"
    assert entries[-1]["mac_notification"]["ok"] is True
    assert len(mac_log) == 1
    assert (stock_ai.LOG_DIR / f"preopen-{now.date().isoformat()}" / "prepare.log").exists()


def test_preopen_data_limited_without_findings_is_fixed_reply(isolated, capsys, monkeypatch):
    monkeypatch.setattr(
        stock_ai, "run_preopen_prepare",
        lambda timeout: (2, {"status": "data_limited", "new_announcements": [],
                             "suspended_stocks": [], "limitations": ["公告检查未完成"]}, ""),
    )
    monkeypatch.setattr(stock_ai, "run_agent", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    assert stock_ai.run_preopen(Args(), {}, None, now=at("2026-09-14", 8, 50)) == stock_ai.EXIT_FAIL
    out = capsys.readouterr().out
    assert "公告检查未完成" in out
    assert "没有发现需要改变昨晚参与条件的新情况" not in out


def test_preopen_changes_found_calls_model(isolated, capsys, monkeypatch):
    monkeypatch.setattr(
        stock_ai, "run_preopen_prepare",
        lambda timeout: (0, {"status": "changes_found",
                             "new_announcements": [{"ts_code": "000001.SZ"}],
                             "suspended_stocks": [], "limitations": []}, ""),
    )

    def fake_agent(provider, prompt, final, jsonl, timeout, config, extra=None):
        assert timeout is None  # 次晨模型同样无新增倒计时
        final.write_text("安全结论", encoding="utf-8")
        return 0, ""

    monkeypatch.setattr(stock_ai, "run_agent", fake_agent)
    assert stock_ai.run_preopen(Args(), {}, None, now=at("2026-09-14", 8, 50)) == stock_ai.EXIT_OK
    assert "完整完成" in capsys.readouterr().out


# ---------------------------------------------------------------- 异常/取消/SIGTERM 终态与通知


def test_nightly_cli_crash_leaves_failed_state_and_notifies(isolated, monkeypatch, mac_log, fake_keys):
    path, _c, _t, _p = prepared_run(isolated, monkeypatch, now=stock_ai.now_shanghai(),
                                    rerun="2026-09-11")

    def fake_agent(provider, prompt, final, jsonl, timeout, config, extra=None):
        raise RuntimeError("CLI 异常崩溃")

    monkeypatch.setattr(stock_ai, "run_agent", fake_agent)
    # 走 main 层派发：异常退出由 main 落真实终态
    assert stock_ai.main(["run", "nightly", "--rerun-date", "2026-09-11", "--provider", "glm"]) \
        == stock_ai.EXIT_FAIL
    state = json.loads(path.read_text(encoding="utf-8"))
    assert state["status"] == "failed"  # 不留 running
    assert "RuntimeError" in state["result"]["detail"]
    assert len(mac_log) == 1 and "CLI 异常崩溃" in mac_log[0]
    entries = [json.loads(l) for l in stock_ai.INDEX_PATH.read_text(encoding="utf-8").splitlines()
               if l.strip()]
    assert entries[-1]["mac_notification"]["ok"] is True


def test_nightly_cancellation_saves_cancelled_without_fallback(isolated, monkeypatch, mac_log, fake_keys):
    path, _c, _t, _p = prepared_run(isolated, monkeypatch, now=stock_ai.now_shanghai(),
                                    rerun="2026-09-11")

    def fake_agent(provider, prompt, final, jsonl, timeout, config, extra=None):
        raise KeyboardInterrupt()

    monkeypatch.setattr(stock_ai, "run_agent", fake_agent)
    # 取消经 main 落 cancelled 终态；不自动接替继续（模型只被调用一次）
    assert stock_ai.main(["run", "nightly", "--rerun-date", "2026-09-11", "--provider", "glm"]) == 130
    state = json.loads(path.read_text(encoding="utf-8"))
    assert state["status"] == "cancelled"
    assert state["result"]["status"] == "已取消"
    models = [a for a in state["attempts"] if a.get("provider")]
    assert len(models) <= 1
    assert len(mac_log) == 1 and ("中断" in mac_log[0] or "取消" in mac_log[0])


def test_notify_failure_keeps_original_error(isolated, monkeypatch, mac_log):
    """Mac 通知提交失败：原研究失败保留并附提交失败原因，不循环发送、不改成功。"""
    path, _c, _t, _p = prepared_run(
        isolated, monkeypatch,
        agent_script={"glm": (1, "Error: HTTP 402: provider quota exhausted"),
                      "deepseek": (1, "Error: HTTP 502 bad gateway")},
    )

    def failing_macos(message):
        mac_log.append(message)
        return (False, "Mac 通知提交失败（退出码 1）：模拟")

    monkeypatch.setattr(stock_ai, "notify_macos", failing_macos)
    assert stock_ai.run_nightly(Args(), {}, None, now=at("2026-09-11", 19, 30)) == stock_ai.EXIT_FAIL
    entries = [json.loads(l) for l in stock_ai.INDEX_PATH.read_text(encoding="utf-8").splitlines()
               if l.strip()]
    failure = next(e for e in entries if e.get("result_status") == "失败")
    assert failure["mac_notification"]["ok"] is False
    assert "模拟" in failure["mac_notification"]["note"]
    assert "额度" in failure["detail"] or "502" in failure["detail"]
    assert len(mac_log) == 1  # 不循环发送
    state = json.loads(path.read_text(encoding="utf-8"))
    assert state["result"]["status"] == "失败"  # 通知失败不改变业务结论


def test_success_does_not_send_mac_notification(isolated, monkeypatch, mac_log):
    path, _c, _t, _p = prepared_run(isolated, monkeypatch)
    assert stock_ai.run_nightly(Args(), {}, None, now=at("2026-09-11", 19, 30)) == stock_ai.EXIT_OK
    assert mac_log == []  # 成功不弹通知
    entries = [json.loads(l) for l in stock_ai.INDEX_PATH.read_text(encoding="utf-8").splitlines()
               if l.strip()]
    final = entries[-1]
    assert final["result_status"] == "完整完成"
    assert final["mac_notification"]["notified"] is False


def test_lock_busy_records_and_notifies_without_touching_holder(isolated, mac_log, capsys, monkeypatch):
    """锁占用：原运行状态不变，本次未执行原因已记录并通知，不夺锁。"""
    holder_state_path = stock_ai.state_path("nightly", dt.date(2026, 9, 10), dt.date(2026, 9, 11))
    stock_ai.save_state(holder_state_path, {
        "task": "nightly", "slot_date": "2026-09-10", "rerun_date": "2026-09-11",
        "status": "running", "attempts": [{"provider": "glm", "outcome": "success"}]})
    lock = stock_ai.TaskLock()
    ok, _ = lock.acquire()
    assert ok
    def receiver(message):
        entries = [json.loads(line) for line in stock_ai.INDEX_PATH.read_text().splitlines()]
        assert entries[-1]["result_status"] == "未执行（任务锁被占用）"
        assert entries[-1]["mac_notification"]["notified"] is False
        mac_log.append(message)
        return True, "测试接收器，未发送"
    monkeypatch.setattr(stock_ai, "notify_macos", receiver)
    try:
        code = stock_ai.main(["run", "nightly", "--rerun-date", "2026-09-11"])
        assert code == stock_ai.EXIT_LOCKED
    finally:
        lock.release()
    holder = json.loads(holder_state_path.read_text(encoding="utf-8"))
    assert holder["status"] == "running"  # 持锁任务状态未被覆盖
    assert holder["attempts"] == [{"provider": "glm", "outcome": "success"}]
    entries = [json.loads(l) for l in stock_ai.INDEX_PATH.read_text(encoding="utf-8").splitlines()
               if l.strip()]
    last = entries[-1]
    assert last["result_status"] == "未执行（任务锁被占用）"
    assert last["stage"] == "启动"
    assert last["mac_notification"]["ok"] is True
    assert len(mac_log) == 1 and "运行" in mac_log[0]
    assert "未执行" in capsys.readouterr().out
    monkeypatch.setattr(stock_ai, "launchctl_labels", lambda: set())
    monkeypatch.setattr(Path, "home", lambda: isolated)
    stock_ai.cmd_status(Args())
    result_list = capsys.readouterr().out.split("最近任务结果：", 1)[1].split("最近一次失败", 1)[0]
    assert result_list.count("未执行（任务锁被占用）") == 1  # 通知追加结果不重复显示任务


def test_zcode_stderr_full_classification_and_retry_history(isolated, monkeypatch):
    """真实本地子进程输出长错误；无模型/网络，第二次本地错误不得借用旧402。"""
    import os
    prompt, final, events = (isolated / name for name in ("prompt.md", "final.md", "events-glm.jsonl"))
    prompt.write_text("offline")
    monkeypatch.setattr(stock_ai, "ensure_model_catalog_config", lambda: None)
    monkeypatch.setattr(stock_ai, "child_env", lambda *a: {**os.environ, "BIGMODEL_API_KEY": "fake-secret-value"})
    path = stock_ai.STATE_DIR / "nightly-test.json"
    state = {"task": "nightly", "status": "running", "attempts": []}
    errors = ["HTTP 402: quota exhausted fake-secret-value\n" + "\n".join(f"at runtime_{i}" for i in range(25)),
              "ValueError: local data is invalid"]
    for index, error in enumerate(errors):
        script = f"import sys; sys.stderr.write({error!r}); sys.exit(1)"
        monkeypatch.setattr(stock_ai, "zcode_command", lambda config, script=script: [sys.executable, "-c", script])
        code, diagnostic = stock_ai.run_task_agent("glm", prompt, final, events, {}, state, path)
        assert code == 1
        assert stock_ai.classify_failure(code, diagnostic)[1] is (index == 0)
    saved = events.with_suffix(".stderr.log").read_text()
    assert "quota exhausted" in saved and "runtime_24" in saved and errors[1] in saved
    assert "fake-secret-value" not in saved and "[REDACTED]" in saved
    assert saved.count("exit_code=1") == 2
    recorded = json.loads(path.read_text())["attempts"]
    assert len(recorded) == 2 and all(a["exit_code"] == 1 for a in recorded)
    assert all(Path(a["stderr_log"]).is_file() for a in recorded)


@pytest.mark.parametrize("interruption", ["timeout", "sigint", "sigterm"])
def test_zcode_interruption_preserves_stderr_and_exit_code(isolated, monkeypatch, interruption):
    prompt = isolated / "prompt.md"
    prompt.write_text("offline")
    events = isolated / "events-glm.jsonl"
    stopped = []
    monkeypatch.setattr(stock_ai, "ensure_model_catalog_config", lambda: None)
    monkeypatch.setattr(stock_ai, "child_env", lambda *a: {})
    monkeypatch.setattr(stock_ai, "zcode_command", lambda *a: ["unused"])
    class Process:
        def __init__(self, *args, **kwargs):
            kwargs["stderr"].write(b"HTTP 402 before interruption\n")
            kwargs["stderr"].flush()
        def communicate(self, **kwargs):
            if interruption == "timeout":
                raise stock_ai.subprocess.TimeoutExpired("unused", 1)
            if interruption == "sigterm":
                raise SystemExit(143)
            raise KeyboardInterrupt()
    monkeypatch.setattr(stock_ai.subprocess, "Popen", Process)
    monkeypatch.setattr(stock_ai, "terminate_process_group", lambda proc: stopped.append(proc))
    state = {"task": "nightly", "status": "running", "attempts": []}
    path = stock_ai.STATE_DIR / "nightly-test.json"
    call = lambda: stock_ai.run_task_agent("glm", prompt, isolated / "final.md", events, {}, state, path)
    expected = {"timeout": 124, "sigint": 130, "sigterm": 143}[interruption]
    if interruption == "timeout":
        code, diag = call()
        assert code == 124 and stock_ai.classify_failure(code, diag)[1] is False
    else:
        with pytest.raises(SystemExit if interruption == "sigterm" else KeyboardInterrupt):
            call()
    assert len(stopped) == 1
    log = events.with_suffix(".stderr.log").read_text()
    assert "HTTP 402" in log and f"exit_code={expected}" in log
    assert json.loads(path.read_text())["attempts"][-1]["exit_code"] == expected


def wrong_model_evidence():
    return {"verified": True, "consistent": True, "provider": "bigmodel",
            "model": "different-model", "request_model": "different-model"}


@pytest.mark.parametrize("existing", [False, True])
def test_preopen_known_model_mismatch_never_completes(isolated, monkeypatch, existing):
    path = stock_ai.state_path("preopen", dt.date(2026, 9, 14))
    if existing:
        stock_ai.save_state(path, {"task": "preopen", "slot_date": "2026-09-14",
            "status": "completed", "result": {"status": "完整完成"}, "attempts": [],
            "model_provider": "glm", "model_evidence": wrong_model_evidence()})
        monkeypatch.setattr(stock_ai, "run_preopen_prepare", lambda *a: pytest.fail("不可重新prepare"))
    else:
        monkeypatch.setattr(stock_ai, "run_preopen_prepare", lambda *a: (0, {"status": "changes_found", "new_announcements": [{}]}, ""))
    def fake_agent(provider, prompt, final, events, *a):
        assert not existing
        final.write_text("模拟提醒")
        stock_ai.EvidenceBox.record(provider, wrong_model_evidence())
        return 0, ""
    monkeypatch.setattr(stock_ai, "run_agent", fake_agent)
    assert stock_ai.run_preopen(Args(), {}, None, now=at("2026-09-14", 8, 45)) == stock_ai.EXIT_FAIL
    assert json.loads(path.read_text())["result"]["status"] == "完成但模型身份待核对"


@pytest.mark.parametrize("mode", ["resume", "completed", "reuse"])
def test_nightly_known_model_mismatch_survives_all_closeouts(isolated, monkeypatch, mode):
    now = at("2026-09-13", 19, 30)
    path, calls, *_ = prepared_run(isolated, monkeypatch, now=now)
    reply = isolated / "local_archive/ai_tasks/nightly/rerun-2026-09-14/final-reply.md"
    reply.parent.mkdir(parents=True)
    reply.write_text("合并报告")
    state = json.loads(path.read_text())
    state.update(model_provider="glm", model_evidence=wrong_model_evidence(),
                 formation_date="2026-09-13", action_date="2026-09-14",
                 selection_as_of="2026-09-13T18:30:00+08:00",
                 final_reply=str(reply.relative_to(isolated)),
                 status="completed" if mode == "completed" else "failed",
                 result={"status": "完成但模型身份待核对"})
    if mode == "reuse":
        other = reply.parent.parent / "other/final-reply.md"
        other.parent.mkdir()
        reply.rename(other)
        state["final_reply"] = str(other.relative_to(isolated))
        stock_ai.save_state(stock_ai.STATE_DIR / "nightly-other.json", state)
    else:
        stock_ai.save_state(path, state)
    assert stock_ai.run_nightly(Args(), {}, None, now=now) == stock_ai.EXIT_FAIL
    assert [c for c in calls if c[0] == "model"] == []
    saved = json.loads(path.read_text())
    assert saved["result"]["status"] == "完成但模型身份待核对"
    assert saved["model_evidence"] == wrong_model_evidence()


def test_sigterm_to_real_main_stops_child_and_saves_cancelled(tmp_path):
    """给运行真实 main＋真实 run_bounded 的模拟父进程发 SIGTERM：
    子进程组消失、cancelled 落盘、锁可再取、只有测试替身通知。"""
    import fcntl
    import os
    import signal
    import subprocess as sp
    import time as _time

    child_script = tmp_path / "sigterm-child.py"
    child_script.write_text(
        "import os, sys\n"
        "from pathlib import Path\n"
        "root = Path(os.environ['STOCK_AI_PROJECT_ROOT']).resolve()\n"
        "sys.path.insert(0, os.environ['STOCK_AI_TOOLS_DIR'])\n"
        "import stock_ai\n"
        "stock_ai.run_prepare = lambda args, timeout: (\n"
        "    0, {'status': 'ready_for_research', 'formation_date': '2026-09-10',\n"
        "        'action_date': '2026-09-11',\n"
        "        'selection_as_of': '2026-09-10T18:30:00+08:00'}, '')\n"
        "real_popen = stock_ai.subprocess.Popen\n"
        "def recording_popen(*a, **k):\n"
        "    proc = real_popen(*a, **k)\n"
        "    (root / 'sleep-pid.txt').write_text(str(proc.pid), encoding='utf-8')\n"
        "    return proc\n"
        "stock_ai.subprocess.Popen = recording_popen\n"
        "def fake_agent(provider, prompt, final, jsonl, timeout, config, extra=None):\n"
        "    code, _out, err = stock_ai.run_bounded(['/bin/sleep', '30'], None)\n"
        "    final.write_text('x', encoding='utf-8')\n"
        "    return code, err\n"
        "stock_ai.run_agent = fake_agent\n"
        "def fake_mac(message):\n"
        "    (root / 'mac-notify.txt').write_text(message, encoding='utf-8')\n"
        "    return (True, '测试接收器，未真实发送')\n"
        "stock_ai.notify_macos = fake_mac\n"
        "sys.exit(stock_ai.main(['run', 'nightly', '--rerun-date', '2026-09-11']))\n",
        encoding="utf-8")
    (tmp_path / ".stock-ai.local.json").write_text(json.dumps({
        "key_sources": {
            "glm": [{"kind": "env", "name": "SIGTERM_TEST_KEY"}],
            "deepseek": [{"kind": "env", "name": "SIGTERM_TEST_KEY"}],
        }}), encoding="utf-8")
    env = dict(os.environ)
    env.update({
        "STOCK_AI_PROJECT_ROOT": str(tmp_path),
        "STOCK_AI_TOOLS_DIR": str(TOOLS_DIR),
        "PROJECT_ROOT": str(tmp_path),
        "PYTHONPATH": str(tmp_path / "src"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "SIGTERM_TEST_KEY": "test-key",
    })
    proc = sp.Popen([sys.executable, "-u", str(child_script)], env=env,
                    cwd=str(tmp_path), stdout=sp.DEVNULL, stderr=sp.DEVNULL)
    sleep_pid_file = tmp_path / "sleep-pid.txt"
    deadline = _time.time() + 30
    while not sleep_pid_file.exists() and _time.time() < deadline:
        assert proc.poll() is None, "子进程提前退出"
        _time.sleep(0.2)
    assert sleep_pid_file.exists(), "模拟模型子进程未启动"
    sleep_pid = int(sleep_pid_file.read_text().strip())
    _time.sleep(0.5)  # 等真实 run_bounded 进入等待
    os.kill(proc.pid, signal.SIGTERM)
    rc = proc.wait(timeout=30)
    assert rc == 143, f"SIGTERM 退出码应为 143，实际 {rc}"
    _time.sleep(0.3)
    with pytest.raises(ProcessLookupError):
        os.killpg(sleep_pid, 0)  # 模拟子进程组已停止
    state = json.loads(
        (tmp_path / "local_archive/ai_tasks/state/nightly-rerun-2026-09-11.json").read_text())
    assert state["status"] == "cancelled"
    assert state["result"]["status"] == "已取消"
    assert all(a.get("outcome") != "success" for a in state.get("attempts", []))
    assert (tmp_path / "mac-notify.txt").exists()  # 测试替身，非真实通知
    # 锁已释放：父进程可直接取得该 flock
    lock_handle = open(tmp_path / "local_archive/ai_tasks/task.lock", "a+")
    try:
        fcntl.flock(lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(lock_handle, fcntl.LOCK_UN)
    finally:
        lock_handle.close()


def test_finish_task_records_mac_notification_result(isolated, mac_log):
    state = {"task": "preopen", "status": "running",
             "attempts": [{"provider": "glm", "outcome": "failed"}]}
    stock_ai.save_state(stock_ai.state_path("preopen", dt.date(2026, 9, 14)), state)
    code = stock_ai.finish_task("preopen", "preopen-2026-09-14.json", state, "失败",
                                "模拟两路不可用", stock_ai.EXIT_FAIL, stage="模型执行")
    assert code == stock_ai.EXIT_FAIL
    entries = [json.loads(l) for l in stock_ai.INDEX_PATH.read_text().splitlines() if l.strip()]
    entry = entries[-1]
    assert entry["result_status"] == "失败" and entry["stage"] == "模型执行"
    assert entry["mac_notification"]["notified"] is True and entry["mac_notification"]["ok"] is True
    assert len(mac_log) == 1 and "失败" in mac_log[0]


# ---------------------------------------------------------------- 锁/辅助/证据


def test_task_lock_is_exclusive_and_recoverable(isolated):
    lock1 = stock_ai.TaskLock()
    ok, _ = lock1.acquire()
    assert ok
    lock2 = stock_ai.TaskLock()
    ok2, holder = lock2.acquire()
    assert not ok2
    assert "仍在运行" in stock_ai.describe_lock_holder(holder)
    lock1.release()
    ok3, _ = lock2.acquire()
    assert ok3
    lock2.release()


def test_classify_failure_categories():
    # 终端 API 错误：即使带 Traceback 也接替
    assert stock_ai.classify_failure(1, "Traceback: provider HTTP 402 quota exhausted")[1] is True
    assert stock_ai.classify_failure(1, "Error: HTTP 429 rate limit")[1] is True
    assert stock_ai.classify_failure(1, "invalid api key")[1] is True
    assert stock_ai.classify_failure(1, "error: model not found")[1] is True
    assert stock_ai.classify_failure(1, "Error: HTTP 502 bad gateway")[1] is True
    assert stock_ai.classify_failure(1, "Error: HTTP 503 service unavailable")[1] is True
    # 取消/中断/整轮超时优先于一切文本证据（含旧 HTTP 401/402/quota 字样）
    assert stock_ai.classify_failure(124, "Error: HTTP 402: provider quota exhausted")[1] is False
    assert stock_ai.classify_failure(130, "provider quota exhausted")[1] is False
    assert stock_ai.classify_failure(143, "HTTP 401 unauthorized")[1] is False
    assert stock_ai.classify_failure(-15, "HTTP 401 unauthorized")[1] is False
    assert stock_ai.classify_failure(1, "KeyboardInterrupt during request")[1] is False
    # 具体本地/上下文错误：不接替
    assert stock_ai.classify_failure(1, "FileNotFoundError: snapshot does not exist")[1] is False
    assert stock_ai.classify_failure(1, "Autocompact stopped, context refilled")[1] is False
    assert stock_ai.classify_failure(1, "insufficient local data for window")[1] is False
    # 裸数字与泛词组合不构成供应商证据
    assert stock_ai.classify_failure(1, "processed 500 rows")[1] is False
    assert stock_ai.classify_failure(1, "error: model deepseek-flash does not exist")[1] is False
    assert stock_ai.classify_failure(124, "process exceeded 500 seconds")[1] is False
    assert stock_ai.classify_failure(1, "Traceback: FileNotFoundError snapshot missing")[1] is False
    # 未知原因如实失败，不猜成供应商故障
    assert stock_ai.classify_failure(3, "signal abort")[1] is False


def test_extract_json_object_takes_last_status_line():
    text = "warning line\n{\"status\": \"ready_for_research\", \"x\": 1}\nnoise"
    assert stock_ai.extract_json_object(text)["status"] == "ready_for_research"
    assert stock_ai.extract_json_object("no json") is None


def test_local_config_atomic_write_roundtrip(isolated):
    write_config(isolated, default_preference="deepseek")
    assert stock_ai.load_local_config()["default_preference"] == "deepseek"
    assert list(isolated.glob(".stock-ai.local.*.tmp")) == []


def test_module_env_pins_project_root_and_src(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", "/existing")
    monkeypatch.setattr(stock_ai, "PROJECT_ROOT", tmp_path)
    env = stock_ai.module_child_env()
    assert env["PROJECT_ROOT"] == str(tmp_path)
    assert env["PYTHONPATH"].startswith(str(tmp_path / "src"))
    cenv = stock_ai.child_env("glm", {})
    assert cenv["PROJECT_ROOT"] == str(tmp_path)
    assert cenv["PYTHONPATH"].startswith(str(tmp_path / "src"))


def test_rollout_evidence_structured_and_consistency(tmp_path, monkeypatch):
    roll = tmp_path / "rollout"
    roll.mkdir()
    monkeypatch.setattr(stock_ai, "ZCODE_ROLLOUT_DIR", roll)
    path = roll / "model-io-sess_probe.jsonl"
    path.write_text(
        json.dumps({"model": {"role": "main", "providerId": "deepseek", "modelId": "deepseek-flash"},
                    "request": {"body": {"model": "deepseek-flash"}}}) + "\n"
        + json.dumps({"model": {"role": "assistant", "providerId": "x", "modelId": "y"},
                      "request": {"body": {"model": "y"}}}) + "\n",
        encoding="utf-8")
    ev = stock_ai.rollout_model_evidence("sess_probe")
    assert ev["verified"] is True and ev["provider"] == "deepseek" and ev["model"] == "deepseek-flash"
    assert ev["consistent"] is True

    # 两种主请求 → 不一致标记
    path.write_text(
        json.dumps({"model": {"role": "main", "providerId": "deepseek", "modelId": "deepseek-flash"},
                    "request": {"body": {"model": "deepseek-flash"}}}) + "\n"
        + json.dumps({"model": {"role": "main", "providerId": "deepseek", "modelId": "deepseek-chat"},
                      "request": {"body": {"model": "deepseek-chat"}}}) + "\n",
        encoding="utf-8")
    ev2 = stock_ai.rollout_model_evidence("sess_probe")
    assert ev2["consistent"] is False and "|" in ev2["model"]


def test_rollout_evidence_missing_optional_fields_reported_not_fabricated(tmp_path, monkeypatch):
    roll = tmp_path / "rollout"
    roll.mkdir()
    monkeypatch.setattr(stock_ai, "ZCODE_ROLLOUT_DIR", roll)
    path = roll / "model-io-sess_probe.jsonl"
    path.write_text(
        json.dumps({"model": {"role": "main", "providerId": "bigmodel", "modelId": "glm-5.3-flash"},
                    "request": {"body": {"model": "glm-5.3-flash"}}}) + "\n",
        encoding="utf-8")
    ev = stock_ai.rollout_model_evidence("sess_probe")
    assert ev["verified"] is True
    assert ev["response_model"] == ""  # 响应侧缺字段如实为空，不虚构
    assert ev["effort"] == ""


def test_route_evidence_matches_triples():
    ok_glm = {"verified": True, "provider": "bigmodel", "model": "glm-5.3-flash",
              "request_model": "glm-5.3-flash", "consistent": True}
    assert stock_ai.route_evidence_matches("glm", ok_glm) is True
    # 完整值相等比较：混合型号/子串不算一致
    assert stock_ai.route_evidence_matches("glm", {**ok_glm, "model": "bigmodel|other"}) is False
    assert stock_ai.route_evidence_matches("glm", {**ok_glm, "model": "glm-5.3"}) is False
    assert stock_ai.route_evidence_matches("glm", {**ok_glm, "request_model": "other"}) is False
    assert stock_ai.route_evidence_matches("glm", {**ok_glm, "consistent": False}) is False
    assert stock_ai.route_evidence_matches("glm", {"verified": False, "provider": "bigmodel"}) is None
    ok_ds = {"verified": True, "provider": "deepseek", "model": "deepseek-flash",
             "request_model": "deepseek-flash", "consistent": True}
    assert stock_ai.route_evidence_matches("deepseek", ok_ds) is True
    assert stock_ai.route_evidence_matches("deepseek", ok_glm) is False


def test_inconsistent_model_evidence_blocks_clean_success(isolated, monkeypatch, mac_log):
    """混合型号/consistent=false：不得标一致；保留研究并记录待核对。"""
    evidence = {
        "verified": True, "provider": "bigmodel", "model": "glm-5.3-flash|other",
        "request_model": "glm-5.3-flash", "response_model": "", "effort": "",
        "consistent": False, "note": "模拟混合型号"}
    path, _calls, _t, _p = prepared_run(
        isolated, monkeypatch,
        agent_side=lambda provider: stock_ai.EvidenceBox.record(provider, evidence))
    assert stock_ai.run_nightly(Args(), {}, None, now=at("2026-09-11", 19, 30)) == stock_ai.EXIT_FAIL
    state = json.loads(path.read_text(encoding="utf-8"))
    assert state["result"]["status"] == "完成但模型身份待核对"
    assert "模型身份待核对" in state["result"]["detail"]
    assert "响应型号 未提供" in state["result"]["detail"]  # 缺响应型号如实写未提供
    assert len(mac_log) == 1  # 需人工核对 → 提示


def test_ensure_model_catalog_config_writes_overrides(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    monkeypatch.setattr(stock_ai, "ZCODE_USER_CONFIG_PATH", cfg)
    stock_ai.ensure_model_catalog_config()
    data = json.loads(cfg.read_text(encoding="utf-8"))
    overrides = data["modelCatalog"]["overrides"]
    assert overrides["deepseek/deepseek-flash"]["contextWindow"] == 1000000
    assert overrides["deepseek/deepseek-flash"]["maxOutputTokens"] == 384000
    assert overrides["bigmodel/glm-5.3-flash"]["contextWindow"] == 1000000
    # 幂等：再次调用不变化
    before = cfg.read_text(encoding="utf-8")
    stock_ai.ensure_model_catalog_config()
    assert cfg.read_text(encoding="utf-8") == before


def test_ensure_model_catalog_preserves_other_keys(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    original = {
        "model": {"main": "bigmodel/glm-5.3-flash"},
        "modelCatalog": {"overrides": {
            "deepseek/deepseek-flash": {"id": "deepseek-flash", "kinds": ["anthropic"],
                                        "modalities": {"input": ["text"], "output": ["text"]},
                                        "contextWindow": 200000,
                                        "note": "keep-me"},
            "other/model": {"id": "other", "kinds": ["anthropic"],
                            "modalities": {"input": ["text"], "output": ["text"]},
                            "contextWindow": 5}},
        },
        "misc": {"keep": True},
    }
    cfg.write_text(json.dumps(original), encoding="utf-8")
    monkeypatch.setattr(stock_ai, "ZCODE_USER_CONFIG_PATH", cfg)
    stock_ai.ensure_model_catalog_config()
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["model"]["main"] == "bigmodel/glm-5.3-flash"  # 顶层其他键保留
    assert data["misc"] == {"keep": True}
    ds = data["modelCatalog"]["overrides"]["deepseek/deepseek-flash"]
    assert ds["contextWindow"] == 1000000 and ds["note"] == "keep-me"  # 非容量键保留
    assert data["modelCatalog"]["overrides"]["other/model"]["contextWindow"] == 5  # 其他覆盖不动


def test_ensure_model_catalog_corrupt_file_raises_without_overwrite(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    cfg.write_text("{broken json", encoding="utf-8")
    monkeypatch.setattr(stock_ai, "ZCODE_USER_CONFIG_PATH", cfg)
    with pytest.raises(RuntimeError, match="拒绝修改"):
        stock_ai.ensure_model_catalog_config()
    assert cfg.read_text(encoding="utf-8") == "{broken json"  # 原文件未被改写


def test_status_shows_stale_running_and_last_failure(isolated, monkeypatch, capsys):
    stock_ai.save_state(stock_ai.state_path("nightly", dt.date(2026, 9, 10), dt.date(2026, 9, 11)),
                        {"task": "nightly", "slot_date": "2026-09-10", "rerun_date": "2026-09-11",
                         "status": "running", "attempts": []})
    stock_ai.append_index({
        "task": "nightly", "slot": "nightly-rerun-2026-09-11",
        "recorded_at": "2026-09-11T20:00:00", "result_status": "失败",
        "detail": "GLM 与 DeepSeek 均失败", "stage": "模型执行",
        "final_reply": "", "log_dir": "logs/ai_tasks/nightly-2026-09-10",
        "mac_notification": {"notified": True, "ok": True, "note": "已提交", "at": "x"},
    })
    assert stock_ai.cmd_status(Args()) == stock_ai.EXIT_OK
    out = capsys.readouterr().out
    assert "不会自动重跑" in out and "nightly-rerun-2026-09-11" in out
    assert "最近一次失败/需处理记录" in out
    assert "模型执行" in out and "GLM 与 DeepSeek 均失败" in out


# ---------------------------------------------------------------- dry-run


def test_dry_run_writes_nothing(isolated, monkeypatch, capsys):
    monkeypatch.setattr(
        stock_ai, "run_prepare", lambda *a, **k: (_ for _ in ()).throw(AssertionError("dry-run 不得 prepare"))
    )
    monkeypatch.setattr(
        stock_ai, "run_agent", lambda *a, **k: (_ for _ in ()).throw(AssertionError("dry-run 不得调模型"))
    )
    code = stock_ai.main(["run", "nightly", "--dry-run"])
    assert code == stock_ai.EXIT_OK
    out = capsys.readouterr().out
    assert "预览" in out and "无（执行到完成或明确失败" in out
    assert not (isolated / "local_archive").exists()
    assert not (isolated / "logs").exists()


# ---------------------------------------------------------------- launchd 模板与文档


def test_ai_launchd_templates_are_valid_and_fixed():
    expected = {
        "nightly": {"Hour": 18, "Minute": 45},
        "preopen": {"Hour": 8, "Minute": 45},
    }
    paths = sorted(Path("ops/launchd").glob("com.ccrt.stock-analysis-assistant.ai-*.plist.example"))
    assert len(paths) == 2
    for path in paths:
        data = plistlib.loads(path.read_bytes())
        task = path.name.removeprefix(
            "com.ccrt.stock-analysis-assistant.ai-"
        ).removesuffix(".plist.example")
        command = " ".join(data["ProgramArguments"])
        assert data["Label"] == f"com.ccrt.stock-analysis-assistant.ai-{task}"
        assert data["StartCalendarInterval"] == expected[task]
        assert data["RunAtLoad"] is False
        assert data["KeepAlive"] is False
        assert "tools/stock_ai.py" in command
        assert f"run {task} --scheduled" in command
        assert "__PROJECT_ROOT__" in path.read_text(encoding="utf-8")
        assert "/Users/" not in path.read_text(encoding="utf-8")


def test_example_config_has_no_real_values_no_budget_no_session_key():
    sample = Path("ops/stock-ai.example.json").read_text(encoding="utf-8")
    data = json.loads(sample)
    assert data["default_preference"] == "auto" and data["tonight"] is None
    assert "budget_minutes" not in data
    assert "prepare_timeout_minutes" in data
    assert "sk-" not in sample
    assert "notify_session_id" not in data  # 旧 ZCode 通知键已删除（手册 §5.1）


def test_usage_doc_maps_voice_commands_and_no_time_limit():
    doc = Path("ops/stock-ai-usage.md").read_text(encoding="utf-8")
    for phrase, command in [
        ("以后用深度求索", "use deepseek"),
        ("今晚用 DeepSeek", "tonight deepseek"),
        ("恢复默认", "use auto"),
        ("现在用哪个", "status"),
    ]:
        assert phrase in doc
        assert command in doc
    assert "不设总时限" in doc
    assert "归档" in doc


def test_usage_doc_describes_mac_notification_not_zcode_session():
    doc = Path("ops/stock-ai-usage.md").read_text(encoding="utf-8")
    assert "osascript" in doc
    assert "notify_session" not in doc  # 以下字符串仅用于验证旧键已清除（手册 §10.3）


# ---------------------------------------------------------------- CSV/合并报告/复用（§4）


@pytest.fixture()
def trace_env(tmp_path, monkeypatch):
    """构造最小 trace + 假 forward_selection 推导，驱动 forward_csv_matches_trace。"""
    import stock_analyzer.ops.forward_selection as fs
    root = tmp_path
    monkeypatch.setattr(stock_ai, "PROJECT_ROOT", root)
    (root / "local_archive" / "forward_selection").mkdir(parents=True)
    (root / "local_archive" / "forward_monitor").mkdir(parents=True)
    trace = {
        "trace_version": "daily-research-trace-v4",
        "formation_date": "2026-09-10",
        "action_date": "2026-09-11",
        "as_of": "2026-09-10T18:30:00+08:00",
        "research_result": {"selected_stocks": [
            {"ts_code": "605006.SH", "name": "山东玻纤", "priority": 1},
            {"ts_code": "000823.SZ", "name": "超声电子", "priority": 2},
        ]},
        "candidate_ledger": [],
    }
    monkeypatch.setattr(fs, "DailyResearchTraceV4",
                        type("T", (), {"model_validate": staticmethod(lambda x: x)}))
    monkeypatch.setattr(fs, "_confirmed_active_research_result",
                        lambda t: {"selected_stocks": [
                                       {**s, "opportunity_type": "x",
                                        "selection_reason": "r",
                                        "strongest_counterevidence": "c",
                                        "nearest_comparison": "n"}
                                       for s in t["research_result"]["selected_stocks"]],
                                   "nearest_nonselections": [],
                                   "empty_reason": "今日无合规确认机会"})
    (root / "local_archive" / "forward_selection" / f"research-trace-2026-09-10.json").write_text(
        json.dumps(trace), encoding="utf-8")
    fields = ["formation_date", "action_date", "as_of", "selection_as_of",
              "validation_mode", "ts_code", "name", "final_fate", "priority",
              "opportunity_type", "selection_reason", "strongest_counterevidence",
              "nearest_comparison", "current_day", "current_close_return",
              "max_close_return_so_far", "hit_20pct_close_within_20d",
              "first_hit_day", "terminal_return_20d", "max_close_return_20d"]

    def write_csv(rows):
        with open(root / "local_archive/forward_selection/forward-selection-log.csv",
                  "w", encoding="utf-8", newline="") as h:
            w = _csv.DictWriter(h, fieldnames=fields)
            w.writeheader()
            for r in rows:
                w.writerow(r)

    def row(ts_code, name, fate, priority="", selection_reason="r"):
        return {"formation_date": "2026-09-10", "action_date": "2026-09-11",
                "as_of": "2026-09-10T18:30:00+08:00",
                "selection_as_of": "2026-09-10T18:30:00+08:00",
                "validation_mode": "selection", "ts_code": ts_code, "name": name,
                "final_fate": fate, "priority": priority, "opportunity_type": "x",
                "selection_reason": selection_reason, "strongest_counterevidence": "c",
                "nearest_comparison": "n"}
    return write_csv, row


def test_csv_matches_trace_accepts_correct_rows(tmp_path, monkeypatch, trace_env):
    write_csv, row = trace_env
    write_csv([row("605006.SH", "山东玻纤", "selected", "1"),
               row("000823.SZ", "超声电子", "selected", "2")])
    ok, reason = stock_ai.forward_csv_matches_trace(
        "2026-09-10", "2026-09-11", "2026-09-10T18:30:00+08:00")
    assert ok, reason


def test_csv_missing_row_or_wrong_code_fails(tmp_path, monkeypatch, trace_env):
    write_csv, row = trace_env
    write_csv([row("605006.SH", "山东玻纤", "selected", "1")])  # 缺一行
    ok, reason = stock_ai.forward_csv_matches_trace(
        "2026-09-10", "2026-09-11", "2026-09-10T18:30:00+08:00")
    assert not ok and "行数不一致" in reason
    # 错代码：行数一致但代码不符
    write_csv([row("605006.SH", "山东玻纤", "selected", "1"),
               row("999999.SZ", "冒名", "selected", "2")])
    ok, reason = stock_ai.forward_csv_matches_trace(
        "2026-09-10", "2026-09-11", "2026-09-10T18:30:00+08:00")
    assert not ok


def test_csv_empty_selection_contract(tmp_path, monkeypatch, trace_env):
    write_csv, row = trace_env
    import stock_analyzer.ops.forward_selection as fs
    monkeypatch.setattr(fs, "_confirmed_active_research_result",
                        lambda t: {"selected_stocks": [], "nearest_nonselections": [],
                                   "empty_reason": "今日无合规确认机会"})
    empty_row = row("", "", "empty_selection", selection_reason="今日无合规确认机会")
    empty_row["opportunity_type"] = ""
    empty_row["strongest_counterevidence"] = ""
    empty_row["nearest_comparison"] = ""
    write_csv([empty_row])
    ok, reason = stock_ai.forward_csv_matches_trace(
        "2026-09-10", "2026-09-11", "2026-09-10T18:30:00+08:00")
    assert ok, reason  # 合法空选：恰一行 empty_selection
    write_csv([])  # 空 CSV 不等于空选
    ok, reason = stock_ai.forward_csv_matches_trace(
        "2026-09-10", "2026-09-11", "2026-09-10T18:30:00+08:00")
    assert not ok


def test_csv_parse_error_is_explicit_failure_not_empty(tmp_path, monkeypatch, trace_env):
    write_csv, _row = trace_env
    csv_path = tmp_path / "local_archive/forward_selection/forward-selection-log.csv"
    csv_path.write_text("not,a,valid\nbroken", encoding="utf-8")
    ok, reason = stock_ai.forward_csv_matches_trace(
        "2026-09-10", "2026-09-11", "2026-09-10T18:30:00+08:00")
    assert not ok and reason  # 解析异常转成明确的核对失败


def _report_env(tmp_path, monkeypatch, fake_forward_selection):
    monkeypatch.setattr(stock_ai, "PROJECT_ROOT", tmp_path)
    formation, action, as_of = "2026-09-10", "2026-09-11", "2026-09-10T18:30:00+08:00"
    selected = [{"ts_code": "605006.SH", "name": "山东玻纤", "priority": 1}]
    alerts = [{"ts_code": "605006.SH", "name": "山东玻纤",
               "episode_reviews": [{"episode_id": "formal:2026-09-09:605006.SH:selected",
                                    "current_review": "玻纤正文ABC"}]}]
    reviews = [{"episode_id": "formal:2026-09-09:605006.SH:selected",
                "review_kind": "checkpoint_detail"}]
    write_report_archives(tmp_path, formation, action, as_of,
                          selected=selected, alerts=alerts, reviews=reviews)
    return formation, action, as_of


def test_merged_report_missing_heading_and_review_attribution(tmp_path, monkeypatch, fake_forward_selection):
    formation, action, as_of = _report_env(tmp_path, monkeypatch, fake_forward_selection)
    good = single_stock_report("山东玻纤", "605006.SH", review_body="玻纤正文ABC")
    assert stock_ai.merged_report_issues(good, formation, action, as_of) == []
    issues = stock_ai.merged_report_issues(
        good.replace("## 正式推荐股票的今日复盘", "正式推荐股票的今日复盘"),
        formation, action, as_of)
    assert any("缺少必需总标题" in i for i in issues)
    issues = stock_ai.merged_report_issues(
        good.replace("玻纤正文ABC", "被改写的正文"), formation, action, as_of)
    assert any("未完整对应" in i for i in issues)


def test_merged_report_recommendation_section_contract(tmp_path, monkeypatch, fake_forward_selection):
    formation, action, as_of = _report_env(tmp_path, monkeypatch, fake_forward_selection)
    good = single_stock_report("山东玻纤", "605006.SH", review_body="玻纤正文ABC")
    reco = good.split("## 今天明确推荐的股票\n\n", 1)[1]

    def reco_issues(text):
        return [i for i in stock_ai.merged_report_issues(
            make_report(review="### 关键节点复盘（1只）\n\n**山东玻纤（605006.SH）**\n玻纤正文ABC\n",
                        lifecycle="主动跟踪：1只\n仅保留评价：0条\n已完成：0条", reco=text),
            formation, action, as_of)]

    # 只有目录表没有逐只说明 → 失败
    table_only = reco.split("### 山东玻纤", 1)[0]
    assert any("没有逐只股票正文" in i for i in reco_issues(table_only))
    # 缺股（正文标题被删）→ 失败
    assert any("缺少正式推荐股票正文" in i for i in reco_issues(table_only))
    # 多股（混入非正式推荐）→ 失败
    extra = reco + "### 比较股（000001.SZ）\n\n**公司主要做什么**\n\nx\n\n**为什么会选它**\n\ny\n\n**什么情况会让我改变看法**\n\nz\n"
    assert any("非正式推荐股票" in i for i in reco_issues(extra))
    # 重复标题 → 失败
    dup = reco + "### 山东玻纤（605006.SH）\n\n重复正文\n"
    assert any("重复的股票标题" in i for i in reco_issues(dup))
    # 缺加粗小标题 → 失败
    missing_sub = reco.replace("**为什么会选它**\n\n选择说明。\n\n", "")
    assert any("缺少小标题" in i for i in reco_issues(missing_sub))
    # 正文标题降级为四级 → 不符合推荐节合同
    demoted = reco.replace("### 山东玻纤（605006.SH）", "#### 山东玻纤（605006.SH）")
    assert any("没有逐只股票正文" in i for i in reco_issues(demoted))


def test_merged_report_empty_selection_contract(tmp_path, monkeypatch, fake_forward_selection):
    formation, action, as_of = _report_env(tmp_path, monkeypatch, fake_forward_selection)
    import stock_analyzer.ops.forward_selection as fs
    # 空名单日：无详评、无简评；合法空选说明 → 通过
    monkeypatch.setattr(fs, "_confirmed_active_research_result",
                        lambda t: {"selected_stocks": [], "nearest_nonselections": [],
                                   "empty_reason": "今日无合规确认机会"})
    write_report_archives(tmp_path, formation, action, as_of)
    assert stock_ai.merged_report_issues(make_report(), formation, action, as_of) == []
    # 空名单但出现股票标题 → 失败
    bad = make_report(reco="### 某股（605006.SH）\n\n**公司主要做什么**\n\nx\n\n"
                           "**为什么会选它**\n\ny\n\n**什么情况会让我改变看法**\n\nz\n")
    issues = stock_ai.merged_report_issues(bad, formation, action, as_of)
    assert any("正式名单为空" in i for i in issues)
    # 空名单但缺少明确说明 → 失败
    issues = stock_ai.merged_report_issues(make_report(reco="今天情况复杂。"), formation, action, as_of)
    assert any("缺少明确空名单说明" in i for i in issues)


def test_merged_report_review_grouping_and_scoping(tmp_path, monkeypatch, fake_forward_selection):
    formation, action, as_of = _report_env(tmp_path, monkeypatch, fake_forward_selection)
    good = single_stock_report("山东玻纤", "605006.SH", review_body="玻纤正文ABC")
    # 分组标题缺失而该组有详评 → 失败
    no_group = good.replace("### 关键节点复盘（1只）\n\n", "")
    issues = stock_ai.merged_report_issues(no_group, formation, action, as_of)
    assert any("关键节点复盘" in i and "子分区" in i for i in issues)
    # 正文只出现在推荐分区（复盘分区缺失）→ 复盘归属失败，不能让后一分区顶替
    scoped = make_report(
        review="### 关键节点复盘（1只）\n\n**山东玻纤（605006.SH）**\n别的文字\n",
        lifecycle="主动跟踪：1只\n仅保留评价：0条\n已完成：0条",
        reco=("### 山东玻纤（605006.SH）\n\n玻纤正文ABC\n\n**公司主要做什么**\n\n主营。\n\n"
              "**为什么会选它**\n\n理由。\n\n**什么情况会让我改变看法**\n\n改变。\n"))
    issues = stock_ai.merged_report_issues(scoped, formation, action, as_of)
    assert any("未完整对应" in i for i in issues)


def test_merged_report_brief_row_and_lifecycle_checks(tmp_path, monkeypatch, fake_forward_selection):
    monkeypatch.setattr(stock_ai, "PROJECT_ROOT", tmp_path)
    formation, action, as_of = "2026-09-10", "2026-09-11", "2026-09-10T18:30:00+08:00"
    brief = [{"episode_id": "formal:2026-08-01:600583.SH:selected", "review_kind": "brief"}]
    write_report_archives(tmp_path, formation, action, as_of, selected=[], alerts=[],
                          reviews=brief)
    table = ("### 今日简评（1只）\n\n| 股票 | 当前观察日 | 当前涨跌 | 今日简评 | 未来1—3日 | 主动跟踪 |\n"
             "|---|---:|---:|---|---|---|\n| 海油工程（600583.SH） | 14 | +2.50% | 摘要正文 | 横盘 | 继续 |\n")
    report = make_report(review=table, reco="今天没有正式推荐：候选都未满足确认条件。")
    assert stock_ai.merged_report_issues(report, formation, action, as_of) == []
    # 简评表漏行 → 失败
    report_missing = make_report(review="### 今日简评（1只）\n\n（空表）\n",
                                 reco="今天没有正式推荐：候选都未满足确认条件。")
    issues = stock_ai.merged_report_issues(report_missing, formation, action, as_of)
    assert any("简评表缺少股票行" in i for i in issues)
    # 生命周期三类统计缺失 → 失败
    bad_lifecycle = make_report(review=table, lifecycle="主动跟踪：1只",
                                reco="今天没有正式推荐：候选都未满足确认条件。")
    issues = stock_ai.merged_report_issues(bad_lifecycle, formation, action, as_of)
    assert any("仅保留评价" in i and "统计" in i for i in issues)
    # 市场说明只有空标题 → 失败
    empty_market = make_report(market="", review=table,
                               reco="今天没有正式推荐：候选都未满足确认条件。")
    issues = stock_ai.merged_report_issues(empty_market, formation, action, as_of)
    assert any("市场说明分区为空" in i for i in issues)


@pytest.mark.parametrize("command", [["use", "random"], ["use", "astra"],
                                     ["tonight", "astra"],
                                     ["run", "nightly", "--provider", "astra"]])
def test_removed_preferences_cannot_start_a_task(command, isolated, monkeypatch):
    monkeypatch.setattr(stock_ai, "run_agent", lambda *a, **k: pytest.fail("模型不得启动"))
    with pytest.raises(SystemExit) as error:
        stock_ai.main(command)
    assert error.value.code == 2
    assert not stock_ai.LOCAL_CONFIG_PATH.exists()
    assert not stock_ai.STATE_DIR.exists()


@pytest.mark.parametrize("evidence_change, expected_ok", [
    ({}, True),
    ({"provider": "other"}, False),
    ({"model": "glm-5.3"}, False),
    ({"request_model": "glm-5.3-flash-other"}, False),
    ({"verified": False}, False),
])
def test_verify_uses_the_same_exact_identity_as_real_tasks(
        isolated, monkeypatch, evidence_change, expected_ok):
    workspace = isolated / "verify"
    workspace.mkdir()
    monkeypatch.setattr(stock_ai.tempfile, "mkdtemp", lambda **kwargs: str(workspace))
    evidence = {"verified": True, "consistent": True, "provider": "bigmodel",
                "model": "glm-5.3-flash", "request_model": "glm-5.3-flash"}
    evidence.update(evidence_change)
    monkeypatch.setattr(stock_ai, "rollout_model_evidence", lambda session: evidence)
    def fake_run(provider, prompt, final, events, timeout_seconds, config):
        (workspace / "result.txt").write_text("结果: 121\n")
        final.write_text("测试已完成")
        events.write_text('{"sessionId":"sess_fake"}')
        return 0, ""
    monkeypatch.setattr(stock_ai, "run_agent", fake_run)
    args = stock_ai.build_parser().parse_args(["verify", "--provider", "glm"])
    assert stock_ai.cmd_verify(args) == (stock_ai.EXIT_OK if expected_ok else stock_ai.EXIT_FAIL)
    assert stock_ai.load_local_config()["verify"]["glm"]["ok"] is expected_ok
