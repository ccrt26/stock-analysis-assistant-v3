from pathlib import Path


def test_forward_monitor_prompt_limits_ai_work_and_report_size() -> None:
    text = Path("ops/forward-monitor-prompt.md").read_text(encoding="utf-8")

    assert "每天只运行一次" in text
    assert "市场 Skill 每天只分析一次" in text
    assert "程序处理全部 episode" in text
    assert "价格 Skill 只解释" in text
    assert "详细提醒最多8只不同股票" in text
    assert "不创建新的 Scheduled Task" in text
    assert "不得把全部股票交给 AI" in text
    assert "不得打分" in text
    assert "迟到启动，不改变原20个交易日结果" in text
    assert "DailyForwardMonitorReportV1" in text
    priorities = [
        "data_problem", "invalidated", "new_event", "first_reaction",
        "actionable_watch", "strengthening", "overheated", "target_hit",
        "late_activation", "checkpoint",
    ]
    positions = [text.index(f"`{value}`") for value in priorities]
    assert positions == sorted(positions)


def test_existing_daily_prompt_stays_v4_and_adds_monitor_in_same_task() -> None:
    text = Path("ops/forward-selection-prompt.md").read_text(encoding="utf-8")

    assert "daily-research-trace-v4" in text
    assert "DailyResearchTraceV4" in text
    assert "daily-research-trace-v3" not in text
    assert "forward_monitor prepare" in text
    assert "市场 Skill 每天只分析一次" in text
    assert "already_selected" in text
    assert "不得重复执行新选股" in text
    assert "今日市场" in text
    assert "已有股票重点提醒" in text
    assert "跟踪数量概览" in text
    assert "今日新选股" in text
    assert text.count("09:05 Scheduled Task") == 1
