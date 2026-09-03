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
    trigger_of,
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
            "candles", "thesisOriginal", "thesisState", "reviews", "events",
        ):
            assert key in formal_stock
        assert formal_stock["attention"] is True
        assert conditional_stock["attention"] is False
        # 正式记录的推荐参考价来自推荐日原始开盘价（无行情时为 None）
        assert formal_stock["ref"] is None or isinstance(formal_stock["ref"], float)
        assert conditional_stock["ref"] is None
        # 复盘历史与事件时间线
        review = formal_stock["reviews"][-1]
        assert review["headline"] == "观点更新第一句。"
        assert review["viewChanged"] is True
        assert review["base"].startswith("未来1—3个交易日")
        assert any(event[2] == "正式推荐" for event in formal_stock["events"])
        # 交易日窗口与基准对齐
        assert len(payload["dates"]) == len(payload["market"])
        assert len(formal_stock["candles"]) == len(payload["dates"])
        assert payload["stocks"][0]["recIndex"] < len(payload["dates"])
        assert [f["file"] for f in payload["date_files"]] == [
            "monitor-report-2026-09-02.html"
        ]


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
            "下一检查日", "推荐理由对照", "公司与观察事件", "交易日尺" if False else "dayruler",
            "K线", "相对表现", "缩起",
        ):
            assert marker in html
        # 用户要求：删除今天先看什么；不出现自行改状态的按钮
        assert "今天先看什么" not in html
        assert "标记已买入" not in html
        assert "延长到 30 日" not in html
        # 日期选择与个股选择器存在
        assert 'id="dateSelect"' in html
        assert 'id="stockPick"' in html
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
