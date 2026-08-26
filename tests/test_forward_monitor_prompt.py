from pathlib import Path


SKILL_PATHS = {
    "总控": ".agents/skills/orchestrating-stock-research/SKILL.md",
    "市场": ".agents/skills/interpreting-market-macro/SKILL.md",
    "行业": ".agents/skills/researching-sectors-industries/SKILL.md",
    "公司": ".agents/skills/researching-company-events/SKILL.md",
    "价格": ".agents/skills/analyzing-price-trading/SKILL.md",
}


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
    assert (
        "这只股票在前20个交易日结束后才开始明显走强，因此不会改变前20天的原评价结果"
        in text
    )
    assert "DailyForwardMonitorReportV2" in text
    assert "ForwardEpisodeReviewV1" in text
    assert "FrozenTwentyDayReviewV1" in text
    priorities = [
        "pending_final_review", "data_problem", "invalidated", "new_event", "first_reaction",
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
    assert "今天的市场情况" in text
    assert "之前研究过的股票走势复盘" in text
    assert "目前还在跟踪多少只" in text
    assert "今天新推荐的股票" in text
    assert "已过原行动窗口" not in text
    assert "今天开盘前能够看到的信息" in text
    assert "当前价格" in text
    assert "09:30" in text
    assert "不得改变 `selection_as_of`" in text
    for question in (
        "为什么现在值得看",
        "股价和成交有没有认可",
        "推荐后的第一个交易日要看什么",
        "为什么选它而不是最接近的备选",
    ):
        assert question in text
    assert "- 发动机类型和状态" not in text
    assert text.count("09:05 Scheduled Task") == 1


def test_forward_monitor_prompt_uses_previous_state_and_strict_report_contract() -> None:
    text = Path("ops/forward-monitor-prompt.md").read_text(encoding="utf-8")

    assert "previous_monitor_state" in text
    assert "previous_episode_review" in text
    assert "required_final_review_episode_ids" in text
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
    assert "原始完整判断" in text
    assert "当时为什么看它" in text
    assert "实际怎么走" in text
    assert "原判断现在怎么看" in text
    assert "和当时最接近的备选相比" in text
    assert "接下来观察什么" in text
    assert "第20个交易日必须首次形成" in text
    assert "当前：D" not in text
    assert "roles" in text
    assert "该股票全部 attention episode" in text
    assert "每条记录分别复盘" in text
    assert "final_twenty_day_review" in text
    assert "第21至第30个交易日不得改写" in text
    assert "original_reason_plain_language" in text
    assert "original_key_risk_plain_language" in text
    assert "真实成对价格路径" in text
    assert "action_date" in text
    assert "这次推荐最后怎么看" in text
    assert "比较记录的 `final_twenty_day_review` 始终为空" in text


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
    assert "推荐后的前20个交易日内" in text
    assert "第21至第30个交易日" in text
    assert "前20个交易日结束后才开始明显走强" in text
    assert "不得改变前20个交易日的原评价结果" in text
    assert "data_problem" in text
    assert "previous_monitor_state" in text
    assert "snapshot 中已出现但日报漏报" in text
    assert "提醒很多但后续1—3个交易日没有对应事实" in text
    assert "按当时 snapshot 和最终日报的时间顺序" in text
    assert "禁止用未来结果倒填当天提醒理由" in text
    assert "不新增定时任务" in text
    assert "不增加自动评分" in text
    assert "前20个交易日结束后的集中研究复盘" in text
    assert "手动 D20 研究复盘提示" not in text
    assert "期间最高涨幅" in text
    assert "期间最深跌幅" in text
    assert "推荐股与当时最接近但未推荐股票的比较" in text
    assert "不自动修改 Skill" in text
    assert "成熟样本" in text


def test_all_five_stock_research_skills_define_a_review_phase() -> None:
    for label, path in SKILL_PATHS.items():
        text = Path(path).read_text(encoding="utf-8")
        assert "phase: review" in text, label
        assert "不重新推荐股票" in text, label

    company = Path(SKILL_PATHS["公司"]).read_text(encoding="utf-8")
    assert "公司事实现在怎么看" in company
    assert "股价对这件事有没有实际反应" in company

    price = Path(SKILL_PATHS["价格"]).read_text(encoding="utf-8")
    assert "从期间最高点又跌回来多少" in price

    orchestrator = Path(SKILL_PATHS["总控"]).read_text(encoding="utf-8")
    assert "第1至第19个交易日" in orchestrator
    assert "第20个交易日首次形成前20天最终结论" in orchestrator
    assert "之后可以更新当前走势评价" in orchestrator
    assert "比较记录的 `final_twenty_day_review` 始终为空" in orchestrator
    assert "用户标题使用 `action_date`" in orchestrator
    assert "为什么现在值得看" in orchestrator
