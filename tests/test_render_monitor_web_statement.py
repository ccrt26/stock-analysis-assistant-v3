"""「当初为什么选它」日报原文提取的最小充分测试。

锁定三件事：小节提取口径（标题行不含、至下一任意级标题止、同名小节必须唯一）、
payload 的 statementFull 注入与 statement_missing 缺口标注、无日报时的回落语义。
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from tools import render_monitor_web as renderer
from tools.render_monitor_web import build_payload, extract_daily_statement


@pytest.fixture(autouse=True)
def _isolated_selection_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """隔离选股轨迹目录：真实 research-trace / 日报不得漏进测试。"""
    monkeypatch.setattr(
        renderer, "SELECTION_DIR", tmp_path / "local_archive" / "forward_selection"
    )


@pytest.fixture(autouse=True)
def _local_trade_calendar(tmp_path: Path) -> None:
    """临时交易日历：周一至周五开市。list_sessions 只以它推导交易日（F04/T13）。"""
    days = pd.date_range("2026-06-01", "2026-12-31", freq="D")
    frame = pd.DataFrame(
        {
            "exchange": "SSE",
            "cal_date": days.strftime("%Y-%m-%d"),
            "is_open": days.dayofweek < 5,
        }
    )
    day_dir = (
        tmp_path / "local_warehouse" / "facts" / "trade_calendar" / "cal_year=2026"
    )
    day_dir.mkdir(parents=True)
    frame.to_parquet(day_dir / "data.parquet")


def _write_report(selection_dir: Path, formed_on: str, body: str) -> None:
    selection_dir.mkdir(parents=True, exist_ok=True)
    (selection_dir / f"daily-research-{formed_on}.md").write_text(
        body, encoding="utf-8"
    )


class TestExtractDailyStatement:
    def test_extracts_body_without_heading_until_next_heading(self, tmp_path: Path) -> None:
        _write_report(
            tmp_path,
            "2026-09-08",
            "# 日报标题\n\n"
            "### 中国船舶（600150）\n"
            "**公司主要做什么**\n公司修船。\n\n"
            "**综合判断**\n仍选择它。\n\n"
            "## 下一节\n\n其他内容。\n",
        )
        statement, miss = extract_daily_statement(
            tmp_path, "2026-09-08", "中国船舶", "600150.SH"
        )
        assert miss == ""
        assert statement == "**公司主要做什么**\n公司修船。\n\n**综合判断**\n仍选择它。"

    def test_matches_code_with_exchange_suffix(self, tmp_path: Path) -> None:
        _write_report(
            tmp_path,
            "2026-09-07",
            "### 绿岛风（301043.SZ）\n正文一段。\n",
        )
        statement, miss = extract_daily_statement(
            tmp_path, "2026-09-07", "绿岛风", "301043.SZ"
        )
        assert (statement, miss) == ("正文一段。", "")

    def test_missing_report_file(self, tmp_path: Path) -> None:
        statement, miss = extract_daily_statement(
            tmp_path, "2026-08-20", "银龙股份", "603969.SH"
        )
        assert (statement, miss) == ("", "no_report")

    def test_section_not_found(self, tmp_path: Path) -> None:
        _write_report(tmp_path, "2026-09-08", "### 别的股票（600999）\n正文。\n")
        statement, miss = extract_daily_statement(
            tmp_path, "2026-09-08", "中国船舶", "600150.SH"
        )
        assert (statement, miss) == ("", "not_found")

    def test_ambiguous_sections_never_guess(self, tmp_path: Path) -> None:
        _write_report(
            tmp_path,
            "2026-09-08",
            "### 中国船舶（600150）\n第一处。\n\n### 中国船舶（600150）\n第二处。\n",
        )
        statement, miss = extract_daily_statement(
            tmp_path, "2026-09-08", "中国船舶", "600150.SH"
        )
        assert (statement, miss) == ("", "ambiguous")


def _episode(name: str, ts_code: str, formation_date: str) -> dict:
    return {
        "episode_id": f"e-{ts_code}",
        "ts_code": ts_code,
        "name": name,
        "role": "selected",
        "selection_output_class": "confirmed_active",
        "original_opportunity_type": "sector_diffusion",
        "original_engine_type": "sector_broad_diffusion",
        "original_engine_status": "active",
        "original_priority": 1,
        "action_date": "2026-09-02",
        "formation_date": formation_date,
        "analysis_date": "2026-09-02",
        "day_number": 2,
        "monitor_phase": "primary",
        "primary_days_remaining": 18,
        "tail_days_remaining": 28,
        "formal_return_started": True,
        "entry_open": 10.0,
        "first_observable_date": "2026-09-02",
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
        "attention_reasons": [],
        "new_announcements": [],
        "scenario_case_ids": [],
        "scenario_control_ids": [],
        "original_group_code": "801010.SI",
        "previous_monitor_state": "strengthening",
        "previous_episode_review": None,
        "original_research_thesis": {},
        "original_selection_reason": "当时存档的理由摘要。",
        "original_strongest_counterevidence": "当时存档的风险。",
        "frozen_twenty_day_review": None,
        "pair_context": None,
    }


def _build(tmp_path: Path, episodes: list[dict]) -> dict:
    report = {
        "report_version": "daily-forward-monitor-report-v2",
        "analysis_date": "2026-09-02",
        "as_of": "2026-09-03T09:00:00+08:00",
        "market_propagation_mode": "one_day_repair",
        "market_risk_overlays": [],
        "market_overview": {"what_changed": "市场回落。", "implication_for_monitored_stocks": "重点看相对表现。"},
        "pool_summary": {"selected_count": len(episodes)},
        "routine_summary": "",
        "unreported_attention_count": 0,
        "alerts": [],
    }
    snapshot = {
        "snapshot_version": "forward-monitor-snapshot-v1",
        "analysis_date": "2026-09-02",
        "as_of": "2026-09-03T09:00:00+08:00",
        "market_context": {},
        "summary": {"selected_count": len(episodes)},
        "episodes": episodes,
        "attention_stocks": [],
        "required_final_review_episode_ids": [],
    }
    (tmp_path / "snapshot-2026-09-02.json").write_text(
        json.dumps(snapshot, ensure_ascii=False), encoding="utf-8"
    )
    (tmp_path / "monitor-report-2026-09-02.json").write_text(
        json.dumps(report, ensure_ascii=False), encoding="utf-8"
    )
    return build_payload(tmp_path, tmp_path, date(2026, 9, 2), report, snapshot)


def test_payload_carries_statement_full(tmp_path: Path) -> None:
    selection_dir = tmp_path / "local_archive" / "forward_selection"
    original = "**为什么会选它**\n低位启动，多日连续。\n\n**综合判断**\n仍正式推荐。"
    _write_report(selection_dir, "2026-08-31", f"### 示例股份（600000.SH）\n{original}\n\n## 尾节\n占位。\n")
    payload = _build(tmp_path, [_episode("示例股份", "600000.SH", "2026-08-31")])
    stock = payload["stocks"][0]
    # 原封不动：正文与日报小节逐字一致，不含小节标题行
    assert stock["statementFull"] == original
    assert all(issue["code"] != "statement_missing" for issue in stock["dataIssues"])


def test_payload_silent_fallback_when_no_report_archived(tmp_path: Path) -> None:
    """形成日本无日报存档属正常历史事实：静默回落存档摘要，不虚构缺口标注（T32/T33）。"""
    payload = _build(tmp_path, [_episode("示例股份", "600000.SH", "2026-08-31")])
    stock = payload["stocks"][0]
    assert stock["statementFull"] == ""
    assert stock["reasonFull"] == "当时存档的理由摘要。"
    assert all(issue["code"] != "statement_missing" for issue in stock["dataIssues"])


def test_payload_marks_gap_when_report_exists_but_section_missing(tmp_path: Path) -> None:
    """日报存在却找不到唯一小节才是真实缺口：标注 statement_missing。"""
    selection_dir = tmp_path / "local_archive" / "forward_selection"
    _write_report(selection_dir, "2026-08-31", "### 别的股票（600999）\n占位。\n")
    payload = _build(tmp_path, [_episode("示例股份", "600000.SH", "2026-08-31")])
    stock = payload["stocks"][0]
    assert stock["statementFull"] == ""
    assert stock["reasonFull"] == "当时存档的理由摘要。"
    issues = [issue for issue in stock["dataIssues"] if issue["code"] == "statement_missing"]
    assert len(issues) == 1
    assert issues[0]["recordKey"] == "600000.SH:2026-08-31"
    assert issues[0]["origin"] == "display_data_adapter"
