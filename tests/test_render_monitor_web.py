"""render_monitor_web 的最小充分测试：观点变化判定、V4 数据组装与 HTML 输出。"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import pytest

from tools.render_monitor_web import (
    build_payload,
    compute_view_change,
    render,
    stage_of,
    scan_history,
    trigger_of,
)
from tools import render_monitor_web as renderer


@pytest.fixture(autouse=True)
def _isolated_selection_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """隔离选股轨迹目录：真实 research-trace 不得漏进测试。"""
    monkeypatch.setattr(
        renderer, "SELECTION_DIR", tmp_path / "local_archive" / "forward_selection"
    )


def _episode(
    episode_id: str,
    ts_code: str,
    name: str,
    *,
    role: str = "selected",
    output_class: str = "confirmed_active",
    action_date: str = "2026-09-01",
    entry_open: float | None = 10.0,
    priority: int | None = 1,
    day_number: int = 2,
) -> dict:
    return {
        "episode_id": episode_id,
        "ts_code": ts_code,
        "name": name,
        "role": role,
        "selection_output_class": output_class,
        "original_opportunity_type": "sector_diffusion",
        "original_engine_type": "sector_broad_diffusion",
        "original_engine_status": "active",
        "original_priority": priority,
        "action_date": action_date,
        "formation_date": "2026-08-31",
        "analysis_date": "2026-09-02",
        "day_number": day_number,
        "monitor_phase": "primary",
        "primary_days_remaining": 18,
        "tail_days_remaining": 28,
        "formal_return_started": entry_open is not None,
        "entry_open": entry_open,
        "first_observable_date": action_date,
        "current_close_return_since_entry": 0.03,
        "current_max_close_return_since_entry": 0.04,
        "current_max_high_return_since_entry": 0.05,
        "current_mae_since_entry": -0.01,
        "current_max_close_drawdown": -0.012,
        "current_close_drawdown_from_peak": -0.009,
        "current_hit_20pct_close": False,
        "current_first_close_hit_20pct_date": None,
        "relative_market_1d": 0.01,
        "relative_industry_1d": None,
        "data_limitations": [],
        "attention_reasons": ["checkpoint"],
        "new_announcements": [],
        "scenario_case_ids": [],
        "scenario_control_ids": ["trend_continuation"],
        "original_group_code": "801010.SI",
        "previous_monitor_state": "strengthening",
        "previous_episode_review": {
            "current_assessment": "supported",
            "best_supported_explanation": "stock_specific_move",
            "current_weak_or_failed_link": "none",
            "current_review": "之前判断得到支持。",
        },
        "original_research_thesis": {
            "engine_type": "sector_broad_diffusion",
            "engine_status": "active",
            "company_information": {"basis": "公司主营与板块直接相关。"},
            "fundamental_anchor": "经营稳定。",
        },
        "original_selection_reason": "板块扩散且个股领先。",
        "frozen_twenty_day_review": None,
        "pair_context": None,
    }


def _review(episode_id: str, assessment: str = "weakening") -> dict:
    return {
        "episode_id": episode_id,
        "original_reason_plain_language": "当时理由。",
        "original_key_risk_plain_language": "当时风险。",
        "current_assessment": assessment,
        "best_supported_explanation": "market_common_move",
        "current_weak_or_failed_link": "price_and_volume_confirmation",
        "current_review": "观点更新第一句。后续解释。",
        "comparison_interpretation": "",
        "final_twenty_day_review": None,
    }


def _report(alerts: list[dict]) -> dict:
    return {
        "report_version": "daily-forward-monitor-report-v2",
        "analysis_date": "2026-09-02",
        "as_of": "2026-09-03T09:00:00+08:00",
        "market_propagation_mode": "one_day_repair",
        "market_risk_overlays": [],
        "market_overview": {"what_changed": "市场回落。", "implication_for_monitored_stocks": "重点看相对表现。"},
        "pool_summary": {"selected_count": 2},
        "routine_summary": "",
        "unreported_attention_count": 0,
        "alerts": alerts,
    }


def _snapshot(episodes: list[dict]) -> dict:
    return {
        "snapshot_version": "forward-monitor-snapshot-v1",
        "analysis_date": "2026-09-02",
        "as_of": "2026-09-03T09:00:00+08:00",
        "market_context": {},
        "summary": {"selected_count": 2},
        "episodes": episodes,
        "attention_stocks": [],
        "required_final_review_episode_ids": [],
    }


def _alert(episode_id: str, name: str = "示例股份", ts_code: str = "600000.SH") -> dict:
    return {
        "alert_type": "checkpoint",
        "monitor_state": "actionable_watch",
        "outlook_1_3d": "range_or_wait",
        "confirmation_condition": "增强条件。",
        "invalidation_condition": "改变条件。",
        "market_change": None,
        "sector_change": None,
        "company_change": None,
        "stock_change": None,
        "why_reported": "需要关注。",
        "checkpoint_label": "D3",
        "attention_reasons": ["checkpoint"],
        "name": name,
        "ts_code": ts_code,
        "episode_ids": [episode_id],
        "roles": ["selected"],
        "day_numbers": [2],
        "original_engine_types": ["sector_broad_diffusion"],
        "episode_reviews": [_review(episode_id)],
    }


class TestComputeViewChange:
    def test_assessment_change_is_detected(self) -> None:
        previous = {
            "current_assessment": "supported",
            "best_supported_explanation": "stock_specific_move",
            "current_weak_or_failed_link": "none",
        }
        result = compute_view_change(_review("e1"), previous)
        assert result["changed"] is True
        assert "assessment" in result["reasons"]

    def test_wording_only_is_not_a_change(self) -> None:
        previous = {
            "current_assessment": "weakening",
            "best_supported_explanation": "market_common_move",
            "current_weak_or_failed_link": "price_and_volume_confirmation",
        }
        result = compute_view_change(_review("e1"), previous)
        assert result["changed"] is False

    def test_explanation_change_ignored_when_evidence_insufficient(self) -> None:
        previous = {
            "current_assessment": "insufficient_evidence",
            "best_supported_explanation": "unknown",
            "current_weak_or_failed_link": "none",
        }
        review = _review("e1", "insufficient_evidence")
        review["best_supported_explanation"] = "company_change"
        result = compute_view_change(review, previous)
        assert result["changed"] is False

    def test_first_review_has_no_previous(self) -> None:
        result = compute_view_change(_review("e1"), None)
        assert result["changed"] is False
        assert result["has_previous"] is False


class TestStageAndTrigger:
    def test_stage_mapping(self) -> None:
        assert stage_of("strengthening") == ("继续走强", "strong")
        assert stage_of("invalidated")[1] == "weak"
        assert stage_of("insufficient_evidence") == ("资料不足", "paused")
        assert stage_of(None) == ("资料不足", "paused")

    def test_trigger_prefers_view_change_then_reasons(self) -> None:
        alert = {"alert_type": "checkpoint", "checkpoint_label": "D3", "attention_reasons": []}
        assert trigger_of(alert, True) == "观点改变"
        assert trigger_of(alert, False) == "D3 检查日"
        alert2 = {"alert_type": "new_event", "attention_reasons": ["new_official_event"]}
        assert trigger_of(alert2, False) == "新公告"


class TestBuildPayload:
    def test_v4_payload_shape(self, tmp_path: Path) -> None:
        formal = _episode("e-formal", "600000.SH", "示例股份")
        formal["original_strongest_counterevidence"] = "涨幅集中在最近3日。"
        formal["new_announcements"] = [
            {"announcement_id": "ann-1", "available_at": "2026-09-02T08:00:00+08:00", "title": "临时公告"}
        ]
        conditional = _episode(
            "e-cond", "600001.SH", "条件股",
            output_class="conditional_event", entry_open=None, priority=2,
            action_date="2026-08-31",
        )
        comparator = _episode("e-comp", "600002.SH", "比较股", role="comparator")
        report = _report([_alert("e-formal")])
        snapshot = _snapshot([formal, conditional, comparator])
        # scan_history 从归档文件读取复盘历史：先落盘
        (tmp_path / "snapshot-2026-09-02.json").write_text(
            json.dumps(snapshot, ensure_ascii=False), encoding="utf-8"
        )
        (tmp_path / "monitor-report-2026-09-02.json").write_text(
            json.dumps(report, ensure_ascii=False), encoding="utf-8"
        )
        # 每日复盘台账：与报告同日同条记录合并，结构化观点字段以台账为准
        ledger = {
            "ledger_version": "daily-formal-reviews-v1",
            "analysis_date": "2026-09-02",
            "as_of": "2026-09-03T09:00:00+08:00",
            "reviews": [
                {
                    "episode_id": "e-formal",
                    "day_number": 2,
                    "checkpoint": None,
                    "current_assessment": "weakening",
                    "current_path": "down",
                    "best_supported_explanation": "market_common_move",
                    "current_weak_or_failed_link": "price_and_volume_confirmation",
                    "current_review": "台账简评正文。",
                    "view_change": "weakened",
                    "view_change_reason": "收盘连续两日回落。",
                    "outlook_1_3d": "weakening",
                    "outlook_reason_plain_language": "路径向下且相对优势消失。",
                    "tracking_decision": "keep_active_tracking",
                    "tracking_decision_reason": "仍在观察窗口内。",
                    "review_origin": "live",
                    "final_twenty_day_review": None,
                }
            ],
        }
        (tmp_path / "daily-formal-reviews-2026-09-02.json").write_text(
            json.dumps(ledger, ensure_ascii=False), encoding="utf-8"
        )
        payload = build_payload(
            tmp_path,
            tmp_path,
            date(2026, 9, 2),
            report,
            snapshot,
        )
        codes = [s["code"] for s in payload["stocks"]]
        assert codes == ["600000.SH", "600001.SH"]  # 比较股不进入，推荐日倒序
        formal_stock = payload["stocks"][0]
        conditional_stock = payload["stocks"][1]
        # V4 字段全部存在
        for key in (
            "code", "name", "recDate", "recIndex", "ref", "days", "stage", "stageType",
            "attention", "trigger", "suspended", "company", "industryName", "industry",
            "candles", "reasonFull", "reasonRisk", "industrySource", "reviews", "events",
        ):
            assert key in formal_stock
        assert formal_stock["attention"] is True
        assert conditional_stock["attention"] is False
        # 正式记录的推荐参考价来自推荐日原始开盘价（无行情时为 None）
        assert formal_stock["ref"] is None or isinstance(formal_stock["ref"], float)
        assert conditional_stock["ref"] is None
        assert formal_stock["reasonFull"] == "板块扩散且个股领先。"
        assert formal_stock["reasonRisk"] == "涨幅集中在最近3日。"
        # 复盘历史与事件时间线：结构化观点字段以台账为准，正文保留详评
        review = formal_stock["reviews"][-1]
        assert review["headline"] == "台账简评正文。"
        assert review["copy"] == "观点更新第一句。后续解释。"
        assert review["summary_copy"] == "台账简评正文。"
        assert review["base"] == "未来1—3个交易日更可能震荡偏下"
        assert review["outlookReason"] == "路径向下且相对优势消失。"
        assert review["viewChanged"] is True
        assert review["viewLabel"] == "观点减弱"  # 观点字段以台账为准
        assert review["viewReason"] == "收盘连续两日回落。"
        assert review["base"].startswith("未来1—3个交易日")
        assert any(event[2] == "正式推荐" for event in formal_stock["events"])
        # 时间线不收录公司公告等客观事实
        assert all(event[2] != "公司公告" for event in formal_stock["events"])
        # 交易日窗口与基准对齐
        assert len(payload["dates"]) == len(payload["market"])
        assert len(formal_stock["candles"]) == len(payload["dates"])
        assert payload["stocks"][0]["recIndex"] < len(payload["dates"])
        assert [f["file"] for f in payload["date_files"]] == [
            "monitor-report-2026-09-02.html"
        ]
        # 重点观察的页内复盘日期列表（含报告日）
        assert payload["review_dates"] == ["2026-09-02"]


def test_conditional_event_uses_first_reaction_reference(tmp_path: Path) -> None:
    """事件等待型：有事件首次定价且有当日行情时，参考价=事件日原始开盘价，观察起点对齐事件日。"""
    import pandas as pd

    from tools.render_monitor_web import build_payload

    eq_dir = tmp_path / "local_warehouse" / "facts" / "equity_daily" / "trade_date=2026-09-02"
    eq_dir.mkdir(parents=True)
    pd.DataFrame(
        [{"ts_code": "600001.SH", "open": 10.0, "high": 10.4, "low": 9.9, "close": 10.2,
          "amount": 1.0e8, "available_at": pd.Timestamp("2026-09-02T08:00:00Z")}]
    ).to_parquet(eq_dir / "data.parquet")
    episode = _episode(
        "e-cond", "600001.SH", "条件股",
        output_class="conditional_event", entry_open=None,
        action_date="2026-09-02",
    )
    episode["first_event_reaction"] = {"trade_date": "2026-09-02", "open": 10.0}
    payload = build_payload(
        tmp_path, tmp_path, date(2026, 9, 2), _report([]), _snapshot([episode])
    )
    stock = payload["stocks"][0]
    assert stock["ref"] == 10.0
    assert stock["refKind"] == "event"
    assert stock["recIndex"] == stock["candles"].index(
        next(bar for bar in stock["candles"] if bar[3] is not None)
    )
    # 无事件定价记录的事件型仍无参考价（如停牌股），不编造
    suspended = _episode(
        "e-cond2", "600002.SH", "停牌条件股",
        output_class="conditional_event", entry_open=None,
        action_date="2026-09-02",
    )
    payload2 = build_payload(
        tmp_path, tmp_path, date(2026, 9, 2), _report([]), _snapshot([suspended])
    )
    assert payload2["stocks"][0]["ref"] is None
    assert payload2["stocks"][0]["refKind"] is None


def test_d0_entries_from_latest_trace_only(tmp_path: Path) -> None:
    """D0：最新报告页面把次日生效的新推荐以"待定价"列出；历史页面永不追加。"""
    selection_dir = tmp_path / "local_archive" / "forward_selection"
    selection_dir.mkdir(parents=True)
    old_selection_dir = renderer.SELECTION_DIR
    renderer.SELECTION_DIR = selection_dir
    try:
        trace = {
            "trace_version": "forward-selection-trace-v1",
            "formation_date": "2026-09-02",
            "action_date": "2026-09-03",
            "as_of": "2026-09-03T09:00:00+08:00",
            "candidate_ledger": [
                {
                    "ts_code": "600003.SH",
                    "name": "新推荐股",
                    "final_fate": "selected",
                    "primary_reason": "连续跑赢市场且成交放大。",
                },
                {
                    "ts_code": "600004.SH",
                    "name": "落选股",
                    "final_fate": "rejected",
                    "primary_reason": "强度不足。",
                },
            ],
            "research_result": {
                "selected_stocks": [
                    {
                        "ts_code": "600003.SH",
                        "strongest_counterevidence": "涨幅集中在最近三日。",
                    }
                ]
            },
        }
        (selection_dir / "research-trace-2026-09-02.json").write_text(
            json.dumps(trace, ensure_ascii=False), encoding="utf-8"
        )
        # 非最新的 09-01 也有配对轨迹：历史页面不得追加 D0
        old_trace = dict(trace, formation_date="2026-09-01", action_date="2026-09-02")
        (selection_dir / "research-trace-2026-09-01.json").write_text(
            json.dumps(old_trace, ensure_ascii=False), encoding="utf-8"
        )
        formal = _episode("e-formal", "600000.SH", "示例股份")
        snapshot = _snapshot([formal])
        # 生产语义：最新报告/快照在盘上（否则"最新日期"闸门不成立）
        (tmp_path / "snapshot-2026-09-02.json").write_text(
            json.dumps(snapshot, ensure_ascii=False), encoding="utf-8"
        )
        (tmp_path / "monitor-report-2026-09-02.json").write_text(
            json.dumps(_report([_alert("e-formal")]), ensure_ascii=False),
            encoding="utf-8",
        )
        (tmp_path / "snapshot-2026-09-01.json").write_text(
            json.dumps(
                _snapshot([_episode("e-old", "600009.SH", "旧股")]),
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (tmp_path / "monitor-report-2026-09-01.json").write_text(
            json.dumps(_report([]), ensure_ascii=False), encoding="utf-8"
        )
        payload = build_payload(
            tmp_path, tmp_path, date(2026, 9, 2), _report([_alert("e-formal")]), snapshot
        )
        codes = [s["code"] for s in payload["stocks"]]
        assert "600003.SH" in codes and "600004.SH" not in codes
        d0 = next(s for s in payload["stocks"] if s["code"] == "600003.SH")
        assert d0["d0"] is True and d0["days"] == 0
        assert d0["stage"] == "待首日观察" and d0["stageType"] == "pending"
        assert d0["ref"] is None and d0["recDate"] == "2026-09-03"
        assert d0["reasonFull"] == "连续跑赢市场且成交放大。"
        assert d0["reasonRisk"] == "涨幅集中在最近三日。"
        assert d0["recIndex"] == len(payload["dates"]) - 1
        assert any(event[2] == "正式推荐" for event in d0["events"])
        # 历史日期不追加 D0
        old_payload = build_payload(
            tmp_path,
            tmp_path,
            date(2026, 9, 1),
            _report([]),
            _snapshot([_episode("e-old", "600009.SH", "旧股")]),
        )
        assert all(not s.get("d0") for s in old_payload["stocks"])
        assert "600003.SH" not in [s["code"] for s in old_payload["stocks"]]
    finally:
        renderer.SELECTION_DIR = old_selection_dir


@pytest.mark.parametrize("engine,status,recognition,expected", [
    ("independent_demand_acceleration", "active", "confirmed", 1),
    ("fresh_event_pending", "conditional", "pending", 0),
    ("anchor_only", "inactive", "not_applicable", 0),
])
def test_d0_v4_only_displays_confirmed_formal_recommendations(
    tmp_path, engine, status, recognition, expected,
):
    selection = renderer.SELECTION_DIR
    selection.mkdir(parents=True)
    trace = {
        "trace_version": "daily-research-trace-v4",
        "formation_date": "2026-09-02", "action_date": "2026-09-03",
        "as_of": "2026-09-02T18:30:00+08:00",
        "candidate_ledger": [{
            "ts_code": "600003.SH", "name": "新推荐股", "final_fate": "selected",
            "primary_reason": "已有研究判断",
            "research_thesis": {
                "engine_type": engine, "engine_status": status,
                "market_recognition": {"status": recognition},
            },
        }],
        "research_result": {"selected_stocks": []},
    }
    (selection / "research-trace-2026-09-02.json").write_text(json.dumps(trace), encoding="utf-8")
    (tmp_path / "monitor-report-2026-09-02.json").write_text(json.dumps(_report([])), encoding="utf-8")
    payload = build_payload(tmp_path, tmp_path, date(2026, 9, 2), _report([]), _snapshot([]))
    assert len(payload["stocks"]) == expected
    if expected:
        assert payload["stocks"][0]["d0"] is True
        assert payload["stocks"][0]["ref"] is None
        assert payload["stocks"][0]["events"][0][2] == "正式推荐"


class TestRender:
    def test_html_matches_v4_and_escapes(self, tmp_path: Path) -> None:
        formal = _episode("e-formal", "600000.SH", "示例股份")
        payload = build_payload(
            tmp_path, tmp_path, date(2026, 9, 2),
            _report([_alert("e-formal")]), _snapshot([formal]),
        )
        html = render(payload)
        # V4 版式标志
        for marker in (
            "推荐观察台", "重点观察", "全部观察", "观察进度", "距 20%",
            "下一检查日", "推荐理由", "每日复盘", "公司与观察事件",
            "交易日尺" if False else "dayruler",
            "K线", "相对表现", "缩起",
        ):
            assert marker in html
        # 用户要求：推荐理由对照并入入选理由块与公司与观察事件时间线
        assert "推荐理由对照" not in html
        assert "决定性事实" not in html and "基准判断" not in html
        # 用户要求：删除今天先看什么；不出现自行改状态的按钮
        assert "今天先看什么" not in html
        assert "标记已买入" not in html
        assert "延长到 30 日" not in html
        # 日期选择与个股选择器存在
        assert 'id="dateSelect"' in html
        assert 'id="stockPick"' in html
        # 公司简介不含申万行业链句子；详情页带最新行情条
        assert "按申万行业分类属于" not in html
        assert 'id="quoteStrip"' in html and "成交额" in html and "停牌前" in html
        # 用户展示口径：入选日 + D1—D20 + 延长观察；不再出现 D0 与旧 D 标记
        assert "待首日观察" in html and "延长观察第" in html
        assert "20个交易日核心观察完成" in html and "推荐日" in html and "事件首日" in html
        template_only = "\n".join(
            line for line in html.split("\n") if not line.lstrip().startswith("const DATA =")
        )
        for forbidden in ("D0", "推荐 D1", "事件定价 D1", "推荐 D0"):
            assert forbidden not in template_only
        # 无外部资源引用
        assert "<script src=" not in html and "<link " not in html and "<img" not in html
        page_json = html.split("DATA = ", 1)[1].split(";\nconst DATES", 1)[0]
        page = json.loads(page_json)
        assert page["stocks"][0]["name"] == "示例股份"


class TestWarehouseFacts:
    def test_collect_and_trim_use_raw_prices(self, tmp_path: Path) -> None:
        from tools.render_monitor_web import collect_market_facts

        root = tmp_path
        for day in (date(2026, 8, 31), date(2026, 9, 1)):
            for dataset, rows in {
                "equity_daily": [
                    {"ts_code": "600000.SH", "open": 10.0, "high": 10.5, "low": 9.8,
                     "close": 10.2, "amount": 2.0e8,
                     "available_at": pd.Timestamp("2026-09-03T01:00:00Z")}
                ],
                "index_daily": [
                    {"index_code": "000001.SH", "open": 3000.0, "close": 3010.0,
                     "available_at": pd.Timestamp("2026-09-03T01:00:00Z")}
                ],
                "industry_daily": [
                    {"industry_code": "801010.SI", "close": 2600.0,
                     "available_at": pd.Timestamp("2026-09-03T01:00:00Z")}
                ],
            }.items():
                day_dir = root / "local_warehouse" / "facts" / dataset / f"trade_date={day.isoformat()}"
                day_dir.mkdir(parents=True)
                pd.DataFrame(rows).to_parquet(day_dir / "data.parquet")
        facts = collect_market_facts(
            root,
            datetime.fromisoformat("2026-09-03T09:00:00+08:00"),
            [date(2026, 8, 31), date(2026, 9, 1)],
            ["801010.SI"],
            ["600000.SH"],
        )
        bar = facts["candles"]["600000.SH"][0]
        assert bar[:4] == [10.0, 10.5, 9.8, 10.2]  # 原始价，不做复权换算
        assert bar[4] == pytest.approx(2.0)  # 成交额（亿元）
        assert facts["market"][-1] == 3010.0
        assert facts["industry"]["801010.SI"][-1] == 2600.0

    def test_late_facts_are_excluded_by_as_of(self, tmp_path: Path) -> None:
        from tools.render_monitor_web import collect_market_facts

        day_dir = tmp_path / "local_warehouse" / "facts" / "equity_daily" / "trade_date=2026-09-02"
        day_dir.mkdir(parents=True)
        pd.DataFrame(
            [{"ts_code": "600000.SH", "open": 1, "high": 1, "low": 1, "close": 99.0,
              "amount": 1.0, "available_at": pd.Timestamp("2026-09-04T01:00:00Z")}]
        ).to_parquet(day_dir / "data.parquet")
        facts = collect_market_facts(
            tmp_path,
            datetime.fromisoformat("2026-09-03T09:00:00+08:00"),
            [date(2026, 9, 2)],
            [],
            ["600000.SH"],
        )
        assert facts["candles"]["600000.SH"][0][3] is None


def test_cli_renders(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    from tools.render_monitor_web import main

    monitor_dir = tmp_path / "forward_monitor"
    monitor_dir.mkdir()
    (monitor_dir / "snapshot-2026-09-02.json").write_text(
        json.dumps(_snapshot([_episode("e-formal", "600000.SH", "示例股份")])), encoding="utf-8"
    )
    (monitor_dir / "monitor-report-2026-09-02.json").write_text(
        json.dumps(_report([_alert("e-formal")])), encoding="utf-8"
    )
    exit_code = main(["--monitor-dir", str(monitor_dir)])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "status=rendered" in out and "stock_count=1" in out
    html = (monitor_dir / "monitor-report-2026-09-02.html").read_text(encoding="utf-8")
    assert "重点观察" in html and "全部观察" in html and "缩起" in html


def test_html_distinguishes_history_from_daily_update_without_losing_chart() -> None:
    html = render({"stocks": [], "dates": [], "market": []})
    detail = html.split("function renderDetail(){", 1)[1].split("function updateLegend", 1)[0]
    review = html.split("function renderReview(){", 1)[1].split("function renderEvents", 1)[0]
    assert "推荐理由" in detail and "当时主要担心" in detail
    assert "入选理由 ·" not in detail
    for label in ("每日复盘", "当日结论", "关键变化", "观点变化", "未来1—3日"):
        assert label in review
    for element in ("chartSvg", "timeline", "events"):
        assert f'id="{element}"' in html
    assert "reasonFull" not in review and "reasonRisk" not in review


def test_web_daily_unchanged_view_does_not_inherit_detail_change(tmp_path: Path) -> None:
    episode = _episode("e1", "600000.SH", "示例股份")
    report = _report([_alert("e1")])
    snapshot = _snapshot([episode])
    for name, value in (("snapshot", snapshot), ("monitor-report", report)):
        (tmp_path / f"{name}-2026-09-02.json").write_text(json.dumps(value), encoding="utf-8")
    (tmp_path / "daily-formal-reviews-2026-09-02.json").write_text(json.dumps({"reviews": [{
        "episode_id": "e1", "day_number": 2, "current_review": "今天变化仍未改变原判断。",
        "current_assessment": "partly_supported", "view_change": "unchanged",
        "view_change_reason": "没有新的决定性事实。", "outlook_1_3d": "range_or_wait",
        "outlook_reason_plain_language": "收盘仍在原区间。",
    }]}), encoding="utf-8")
    review = scan_history(tmp_path, date(2026, 9, 2))["e1"][0]
    # 正文保留报告详评；结构化观点仍以台账为准，不继承详评计算出的变化。
    assert review["copy"] == "观点更新第一句。后续解释。"
    assert review["summary_copy"] == "今天变化仍未改变原判断。"
    assert review["viewChanged"] is False and review["fromTo"] is None
    assert review["viewReason"] == "没有新的决定性事实。"


def _write_history_inputs(
    tmp_path: Path,
    *,
    report: dict | None,
    ledger: dict | None,
    snapshot: dict,
    day: str = "2026-09-02",
) -> None:
    (tmp_path / f"snapshot-{day}.json").write_text(json.dumps(snapshot), encoding="utf-8")
    if report is not None:
        (tmp_path / f"monitor-report-{day}.json").write_text(json.dumps(report), encoding="utf-8")
    if ledger is not None:
        (tmp_path / f"daily-formal-reviews-{day}.json").write_text(json.dumps(ledger), encoding="utf-8")


def _ledger_review(episode_id: str, text: str, view_change: str = "weakened") -> dict:
    return {
        "episode_id": episode_id, "day_number": 2, "checkpoint": None,
        "current_assessment": "weakening", "current_path": "down",
        "best_supported_explanation": "market_common_move",
        "current_weak_or_failed_link": "price_and_volume_confirmation",
        "current_review": text, "view_change": view_change,
        "view_change_reason": "收盘连续两日回落。", "outlook_1_3d": "weakening",
        "outlook_reason_plain_language": "路径向下且相对优势消失。",
        "tracking_decision": "keep_active_tracking",
        "tracking_decision_reason": "仍在观察窗口内。",
        "review_origin": "live", "final_twenty_day_review": None,
    }


def test_scan_history_keeps_detail_copy_with_daily_summary(tmp_path: Path) -> None:
    daily_text = "简评A：市场共同回落。"
    detail_text = "详评B：当初期待的板块扩散需要逐日检验，" + "目前仍有两个交易日未恢复。" * 30
    episode = _episode("e1", "600000.SH", "示例股份")
    snapshot = _snapshot([episode])
    report = _report([_alert("e1")])
    report["alerts"][0]["episode_reviews"][0]["current_review"] = detail_text
    ledger = {
        "ledger_version": "daily-formal-reviews-v1", "analysis_date": "2026-09-02",
        "as_of": "2026-09-03T09:00:00+08:00",
        "reviews": [_ledger_review("e1", daily_text)],
    }
    _write_history_inputs(tmp_path, report=report, ledger=ledger, snapshot=snapshot)
    review = scan_history(tmp_path, date(2026, 9, 2))["e1"][0]
    assert review["summary_copy"] == daily_text
    assert review["copy"] == detail_text
    assert review["headline"] == daily_text  # 今日标题仍来自日评
    assert review["viewLabel"] == "观点减弱"  # 观点变化仍来自日评
    assert review["viewReason"] == "收盘连续两日回落。"
    assert review["base"] == "未来1—3个交易日更可能震荡偏下"
    assert review["confirm"] == "增强条件。" and review["risk"] == "改变条件。"  # 条件保留report


def test_scan_history_ledger_only_input_still_readable(tmp_path: Path) -> None:
    episode = _episode("e1", "600000.SH", "示例股份")
    snapshot = _snapshot([episode])
    ledger = {
        "ledger_version": "daily-formal-reviews-v1", "analysis_date": "2026-09-02",
        "as_of": "2026-09-03T09:00:00+08:00",
        "reviews": [_ledger_review("e1", "只有日评的正文。")],
    }
    _write_history_inputs(tmp_path, report=None, ledger=ledger, snapshot=snapshot)
    review = scan_history(tmp_path, date(2026, 9, 2))["e1"][0]
    assert review["copy"] == "只有日评的正文。"
    assert review["summary_copy"] == "只有日评的正文。"


def test_scan_history_report_only_input_still_readable(tmp_path: Path) -> None:
    episode = _episode("e1", "600000.SH", "示例股份")
    snapshot = _snapshot([episode])
    report = _report([_alert("e1")])
    _write_history_inputs(tmp_path, report=report, ledger=None, snapshot=snapshot)
    review = scan_history(tmp_path, date(2026, 9, 2))["e1"][0]
    assert review["copy"] == "观点更新第一句。后续解释。"
    assert review["summary_copy"] == "观点更新第一句。后续解释。"


def test_scan_history_same_stock_two_episodes_do_not_swap_texts(tmp_path: Path) -> None:
    first = _episode("e-a", "600000.SH", "示例股份")
    second = _episode("e-b", "600000.SH", "示例股份二")
    second["action_date"] = "2026-08-24"
    snapshot = _snapshot([first, second])
    detail_a = "详评A：第一条记录的独立展开。"
    detail_b = "详评B：第二条记录的独立展开。"
    report = _report([
        _alert("e-a"), _alert("e-b", name="示例股份二", ts_code="600000.SH"),
    ])
    report["alerts"][0]["episode_reviews"][0]["current_review"] = detail_a
    report["alerts"][1]["episode_reviews"][0]["current_review"] = detail_b
    ledger = {
        "ledger_version": "daily-formal-reviews-v1", "analysis_date": "2026-09-02",
        "as_of": "2026-09-03T09:00:00+08:00",
        "reviews": [
            _ledger_review("e-a", "简评A。"),
            _ledger_review("e-b", "简评B。"),
        ],
    }
    _write_history_inputs(tmp_path, report=report, ledger=ledger, snapshot=snapshot)
    history = scan_history(tmp_path, date(2026, 9, 2))
    assert history["e-a"][0]["copy"] == detail_a
    assert history["e-a"][0]["summary_copy"] == "简评A。"
    assert history["e-b"][0]["copy"] == detail_b
    assert history["e-b"][0]["summary_copy"] == "简评B。"


def _write_three_route_day(
    tmp_path: Path,
    *,
    episode_id: str = "e1",
    code: str = "600000.SH",
    day: str = "2026-09-02",
    checkpoint_ids: list[str],
    ledger_review: dict,
    report_text: str = "详评正文：独立展开的唯一正文。",
) -> None:
    episode = _episode(episode_id, code, "示例股份")
    snapshot = _snapshot([episode])
    snapshot["checkpoint_review_episode_ids"] = checkpoint_ids
    report = _report([_alert(episode_id)])
    report["alerts"][0]["episode_reviews"][0]["current_review"] = report_text
    ledger = {
        "ledger_version": "daily-formal-reviews-v1",
        "analysis_date": day,
        "as_of": "2026-09-03T09:00:00+08:00",
        "reviews": [ledger_review],
    }
    _write_history_inputs(
        tmp_path, report=report, ledger=ledger, snapshot=snapshot, day=day
    )


def _three_route_ledger_review(
    episode_id: str,
    *,
    kind: str,
    text: str | None,
) -> dict:
    base = _ledger_review(episode_id, text or "")
    base["review_kind"] = kind
    base["current_review"] = text
    return base


def test_scan_history_merges_checkpoint_detail_from_report(tmp_path: Path) -> None:
    detail_text = "节点详评正文：唯一公开对账。" + "补充阶段事实。" * 10
    _write_three_route_day(
        tmp_path,
        checkpoint_ids=["e1"],
        ledger_review=_three_route_ledger_review(
            "e1", kind="checkpoint_detail", text=None
        ),
        report_text=detail_text,
    )
    history = scan_history(tmp_path, date(2026, 9, 2))
    review = history["e1"][0]
    assert review["copy"] == detail_text
    assert review["summary_copy"] == detail_text
    assert review["headline"].startswith("节点详评正文")
    assert review["review_kind"] == "checkpoint_detail"
    assert review["viewLabel"] == "观点减弱"
    assert review["confirm"] == "增强条件。"


def test_scan_history_merges_regular_detail_and_reads_brief(tmp_path: Path) -> None:
    _write_three_route_day(
        tmp_path,
        checkpoint_ids=[],
        ledger_review=_three_route_ledger_review(
            "e1", kind="regular_detail", text=None
        ),
        report_text="普通详评正文。",
    )
    review = scan_history(tmp_path, date(2026, 9, 2))["e1"][0]
    assert review["copy"] == "普通详评正文。"
    assert review["summary_copy"] == "普通详评正文。"
    assert review["review_kind"] == "regular_detail"

    # 简评股没有alert：仅账本即可读。
    tmp_brief = tmp_path / "brief"
    tmp_brief.mkdir()
    _write_history_inputs(
        tmp_brief,
        report=None,
        ledger={
            "ledger_version": "daily-formal-reviews-v1",
            "analysis_date": "2026-09-02",
            "as_of": "2026-09-03T09:00:00+08:00",
            "reviews": [_ledger_review("e1", "只有简评正文。")],
        },
        snapshot=_snapshot([_episode("e1", "600000.SH", "示例股份")]),
    )
    brief_review = scan_history(tmp_brief, date(2026, 9, 2))["e1"][0]
    assert brief_review["copy"] == "只有简评正文。"
    assert brief_review["review_kind"] == "brief"


def test_scan_history_detail_without_report_shows_placeholder(tmp_path: Path) -> None:
    _write_three_route_day(
        tmp_path,
        checkpoint_ids=["e1"],
        ledger_review=_three_route_ledger_review(
            "e1", kind="checkpoint_detail", text=None
        ),
        report_text="不会被读到的正文。",
    )
    (tmp_path / "monitor-report-2026-09-02.json").unlink()
    review = scan_history(tmp_path, date(2026, 9, 2))["e1"][0]
    assert review["copy"] == "详评正文未保存。"
    assert review["summary_copy"] == "详评正文未保存。"


def test_scan_history_does_not_merge_across_different_as_of(tmp_path: Path) -> None:
    detail_text = "详评正文保持不变。"
    _write_three_route_day(
        tmp_path,
        checkpoint_ids=["e1"],
        ledger_review=_three_route_ledger_review(
            "e1", kind="checkpoint_detail", text=None
        ),
        report_text=detail_text,
    )
    # 账本 as_of 与报告不同：不得用账本结构化观点覆盖报告条目。
    ledger_path = tmp_path / "daily-formal-reviews-2026-09-02.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["as_of"] = "2026-09-03T10:30:00+08:00"
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    review = scan_history(tmp_path, date(2026, 9, 2))["e1"][0]
    assert review["copy"] == detail_text
    # 账本未合并：观点标签保留报告自算结果，而非账本的“观点减弱”。
    assert review["viewLabel"] == "观点调整"
    assert review["viewReason"] == ""
