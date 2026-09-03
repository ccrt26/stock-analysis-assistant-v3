from pathlib import Path


SKILL_PATHS = {
    "总控": ".agents/skills/orchestrating-stock-research/SKILL.md",
    "市场": ".agents/skills/interpreting-market-macro/SKILL.md",
    "行业": ".agents/skills/researching-sectors-industries/SKILL.md",
    "公司": ".agents/skills/researching-company-events/SKILL.md",
    "价格": ".agents/skills/analyzing-price-trading/SKILL.md",
}


def test_repository_rules_preserve_the_full_daily_user_report() -> None:
    text = Path("AGENTS.md").read_text(encoding="utf-8")

    assert "正式每日选股与复盘自动任务属于用户报告生产" in text


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
    assert "今天已确认的正式推荐" in text
    assert "等待首个交易日确认的事件线索" in text
    assert "今天新推荐的股票" not in text
    assert "已过原行动窗口" not in text
    assert "今天开盘前能够看到的信息" in text
    assert "当前价格" in text
    assert "09:30" in text
    assert "不得改变 `selection_as_of`" in text
    assert "- 发动机类型和状态" not in text
    assert text.count("09:05 Scheduled Task") == 1


def test_daily_prompts_separate_confirmed_recommendations_from_event_leads() -> None:
    selection = Path("ops/forward-selection-prompt.md").read_text(
        encoding="utf-8"
    )
    monitor = Path("ops/forward-monitor-prompt.md").read_text(
        encoding="utf-8"
    )

    assert "今天已确认的正式推荐" in selection
    assert "等待首个交易日确认的事件线索" in selection
    assert "conditional 不进入正式推荐数量" in selection
    assert "不得虚构收益" in selection
    assert "conditional_event" in monitor
    assert "不得出现在“正式推荐股票的走势复盘”中" in monitor
    assert "不得单列给用户凑内容" in monitor
    assert "fresh_event_pending 仍属于正式推荐" not in selection


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
    assert "推荐日期和当时判断" in text
    assert "到今天走到哪里" in text
    assert "我的分析" in text
    assert "接下来更可能怎样" in text
    assert "推荐后实际怎么走" not in text
    assert "为什么今天要说它" not in text
    assert "内部成对比较继续用于判断" in text
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
    assert "正式推荐股票的走势复盘" in text
    assert "`confirmed_active` 和 `legacy_v1_not_rewritten` 两类正式推荐记录" in text
    assert "正式推荐重点股票不超过8只时必须全部进入详细提醒" in text
    assert "不得由待确认事件或比较记录挤占" in text
    assert "比较记录的 `final_twenty_day_review` 始终为空" in text


def test_public_review_only_lists_explicit_formal_recommendations() -> None:
    text = Path("ops/forward-monitor-prompt.md").read_text(encoding="utf-8")

    assert "正式推荐股票的走势复盘" in text
    assert "confirmed_active" in text
    assert "legacy_v1_not_rewritten" in text
    assert "conditional_event" in text
    assert "不得出现在“正式推荐股票的走势复盘”中" in text
    assert "我的分析" in text
    assert "不得单列给用户凑内容" in text


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
    assert "为什么在这个时间选择它" in orchestrator
    assert "支持选择的独立原因" in orchestrator
    assert "什么情况会让我改变看法" in orchestrator
    assert "这次为什么会选它" not in orchestrator

def test_review_prompt_explains_why_actual_results_support_or_refute_original_reason() -> None:
    text = Path("ops/forward-monitor-prompt.md").read_text(encoding="utf-8")

    for phrase in (
        "当初期待看到什么",
        "最有证据的主要解释",
        "为什么这一解释比其他解释更有证据",
        "哪一项核心预期真正实现",
        "当前阶段",
        "未来1—3个交易日",
    ):
        assert phrase in text


def test_review_prompt_requests_an_analyst_style_view_update() -> None:
    text = Path("ops/forward-monitor-prompt.md").read_text(encoding="utf-8")

    for phrase in (
        "观点更新稿",
        "一个中心问题",
        "一句话观点更新",
        "与上一次复盘比较",
        "后续基准判断",
        "不平均复述市场、行业、公司和价格四路内容",
    ):
        assert phrase in text
    assert (
        "不以“最有证据的解释是、当前阶段是、核心预期目前得到支持”"
        "作为固定句式"
        in text
    )


def test_review_prompt_aligns_current_review_with_existing_renderer() -> None:
    prompt = Path(
        "ops/forward-monitor-prompt.md"
    ).read_text(encoding="utf-8")

    for phrase in (
        "current_review 只负责",
        "不再重复完整推荐日期",
        "不再重复距离20%目标的固定进度句",
        "不再重复未来1—3个交易日的完整展望",
        "日常复盘只写增量",
        "事件复盘",
        "D20 最终复盘",
        "字段和值",
    ):
        assert phrase in prompt


def test_review_prompt_uses_dated_review_skill_and_one_retry_for_missing_data() -> None:
    text = Path("ops/forward-monitor-prompt.md").read_text(encoding="utf-8")

    for phrase in (
        "reviewing-stock-recommendations",
        "具体推荐日期",
        "距离20%观察目标",
        "missing_price_path",
        "missing_current_price_context",
        "missing_market_context",
        "missing_sector_context",
        "重新运行一次 monitor prepare",
        "不得循环重试",
        "不新增定时任务",
    ):
        assert phrase in text
    for heading in (
        "推荐日期和当时判断",
        "到今天走到哪里",
        "我的分析",
        "接下来更可能怎样",
    ):
        assert heading in text


def test_review_prompt_separates_internal_facts_from_public_causal_analysis() -> None:
    text = Path("ops/forward-monitor-prompt.md").read_text(encoding="utf-8")

    for phrase in (
        "best_supported_explanation",
        "current_review 才是公开分析核心",
        "why_reported 只说明今天为什么复盘",
        "相对行业表现",
        "行业上涨面",
        "不得说行业数据全部不可用",
        "无法按计划执行",
        "未来1—3个交易日方向暂时无法判断",
        "D1—D4",
    ):
        assert phrase in text


def test_review_sample_uses_real_dates_target_progress_and_reasoning() -> None:
    sample = Path(
        "research/skill-optimization/entry-timing-review-skill-20260902/"
        "review-sample.md"
    ).read_text(encoding="utf-8")

    for phrase in (
        "2026年8月25日开盘前",
        "离20%的观察目标还差17.32个百分点",
        "跌回此前60日高点下方",
        "停牌前",
        "复牌后",
        "为什么支持或反对",
    ):
        assert phrase in sample
    for forbidden in ("冻结时点", "冻结结论", "正常双向成交", "农业样本"):
        assert forbidden not in sample
