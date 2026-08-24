from pathlib import Path


def test_forward_monitor_prompt_limits_ai_work_and_report_size() -> None:
    text = Path("ops/forward-monitor-prompt.md").read_text(encoding="utf-8")

    assert "每天只运行一次" in text
    assert "市场 Skill 每天只分析一次" in text
    assert "程序处理全部跟踪记录" in text
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
    assert "开盘前冻结信息" in text
    assert "已过原行动窗口" in text
    assert "当前价格" in text
    assert "09:30" in text
    assert "不得改变 `selection_as_of`" in text
    assert "当前短期推动因素" in text
    assert "- 发动机类型和状态" not in text
    assert text.count("09:05 Scheduled Task") == 1


def test_forward_monitor_prompt_uses_previous_state_and_strict_report_contract() -> None:
    text = Path("ops/forward-monitor-prompt.md").read_text(encoding="utf-8")

    assert "previous_monitor_state" in text
    assert "状态延续" in text
    assert "不得机械维持" in text
    for mode in (
        "broad_sustained_participation",
        "one_day_repair",
        "sector_rotation",
        "concentrated_speculation",
        "weak_or_fragmented",
        "unclear",
    ):
        assert mode in text
    assert "pool_summary" in text
    assert "必须与 snapshot 完全一致" in text
    assert "最初入选依据" in text
    assert "原始主要理由" in text
    assert "当前：D" in text
    assert "roles" in text
    assert "该股票全部 attention episode" in text


def test_periodic_review_reads_monitor_history_and_checks_reminder_timing() -> None:
    text = Path("ops/periodic-research-review-prompt.md").read_text(
        encoding="utf-8"
    )

    assert "local_archive/forward_monitor/snapshot-*.json" in text
    assert "local_archive/forward_monitor/monitor-report-*.json" in text
    assert "首个完整可观察交易日" in text
    assert "后续1—3个交易日" in text
    assert "失效" in text
    assert "过热" in text
    assert "D1—D20" in text
    assert "D21—D30" in text
    assert "迟到启动" in text
    assert "不得改变原20个交易日结果" in text
    assert "data_problem" in text
    assert "previous_monitor_state" in text
    assert "snapshot 中已出现但日报漏报" in text
    assert "提醒很多但后续1—3个交易日没有对应事实" in text
    assert "按当时 snapshot 和最终日报的时间顺序" in text
    assert "禁止用未来结果倒填当天提醒理由" in text
    assert "不新增定时任务" in text
    assert "不增加自动评分" in text
