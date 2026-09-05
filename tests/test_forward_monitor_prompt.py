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
    assert "到达 D1/D3/D5/D10/D20 检查节点" in text
    assert "普通详评股（从非节点股票按优先级选最多8只）" in text
    assert "剩余股票只写简评" in text
    assert "不得为详评另配隐藏简评" in text
    assert "不创建新的 Scheduled Task" in text
    assert "不得把全部股票交给 AI" not in text
    assert "AI 只研究今天确实发生变化的股票" not in text
    assert "不得打分" in text
    assert (
        "这只股票在前20个交易日结束后才开始明显走强，因此不会改变前20天的原评价结果"
        in text
    )
    assert "DailyForwardMonitorReportV2" in text
    assert "ForwardEpisodeReviewV1" in text
    assert "FrozenTwentyDayReviewV1" in text
    priorities = [
        "1. 今日停止", "2. 观点明显变化", "3. 达到20%",
        "4. 重要公司事项", "5. 必要时按最长时间未详评轮换补足",
    ]
    priority_block = text.split(
        "普通详评（非节点股，最多8只）按以下顺序考虑：",
        maxsplit=1,
    )[1]
    positions = [priority_block.index(value) for value in priorities]
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
    user_output = text.split("### 唯一用户输出格式", maxsplit=1)[1]
    assert "正式推荐股票的今日复盘" in user_output
    assert "目前仍开放的正式推荐股票数量" in user_output
    assert "今天明确推荐的股票" in user_output
    assert "等待首个交易日确认的事件线索" not in user_output
    assert "今天新推荐的股票" not in text
    assert "已过原行动窗口" not in text
    assert "今天开盘前能够看到的信息" in text
    assert "当前价格" in text
    assert "09:30" in text
    assert "不得改变 `selection_as_of`" in text
    assert "- 发动机类型和状态" not in text
    assert text.count("18:45 Scheduled Task") == 1


def test_daily_prompts_separate_confirmed_recommendations_from_event_leads() -> None:
    selection = Path("ops/forward-selection-prompt.md").read_text(
        encoding="utf-8"
    )
    monitor = Path("ops/forward-monitor-prompt.md").read_text(
        encoding="utf-8"
    )

    user_output = selection.split("### 唯一用户输出格式", maxsplit=1)[1]
    assert "今天明确推荐的股票" in user_output
    assert "等待首个交易日确认的事件线索" not in user_output
    assert "fresh_event_pending" in selection
    assert "conditional_event" in selection
    assert "内部 V4 trace" in selection
    assert "conditional 不进入正式推荐数量" in selection
    assert "不得虚构收益" in selection
    assert "conditional_event" in monitor
    assert "不得出现在“正式推荐股票的今日复盘”中" in monitor
    assert "不得单列给用户凑内容" in monitor
    assert "fresh_event_pending 仍属于正式推荐" not in selection


def test_forward_monitor_prompt_uses_previous_state_and_strict_report_contract() -> None:
    text = Path("ops/forward-monitor-prompt.md").read_text(encoding="utf-8")

    assert "previous_monitor_state" in text
    assert "previous_episode_review" in text
    assert "previous_daily_formal_review" in text
    assert "daily_review_episode_ids" in text
    assert "daily-formal-reviews-v1" in text
    assert "record-daily-formal-reviews" in text
    assert "routine_detail" in text
    assert "不得借用同一股票另一 episode 的观点" in text
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
    assert "今天发生了什么" in text
    assert "相比上次判断" in text
    assert "接下来1—3个交易日" in text
    assert "推荐后实际怎么走" not in text
    assert "为什么今天要说它" not in text
    assert "内部成对比较继续用于判断" in text
    assert "第20个交易日必须首次形成" in text
    assert "当前：D" not in text
    assert "roles" in text
    assert "该股票当天全部需更新判断的正式 episode" in text
    assert "每条记录分别复盘" in text
    assert "final_twenty_day_review" in text
    assert "第21至第30个交易日不得改写" in text
    assert "original_reason_plain_language" in text
    assert "original_key_risk_plain_language" in text
    assert "真实成对价格路径" in text
    assert "正式推荐股票的今日复盘" in text
    assert "`confirmed_active` 和 `legacy_v1_not_rewritten` 两类正式推荐记录" in text
    assert "checkpoint_review_stock_count" in text
    assert "regular_detail_stock_limit" in text
    assert "最长时间未详评轮换补足" in text
    assert "比较记录的 `final_twenty_day_review` 始终为空" in text


def test_daily_review_prompt_defines_tracking_and_checkpoint_outputs() -> None:
    text = Path("ops/forward-monitor-prompt.md").read_text(encoding="utf-8")

    for phrase in (
        "keep_active_tracking",
        "stop_active_tracking",
        "complete_observation",
        "historical_not_applied",
        "weakening 不能单独",
        "单日下跌",
        "横盘",
        "数据暂缺",
        "未达到20%",
        "D1 当天原条件下是否可执行",
        "D3 早期反应是否延续",
        "D5 第一周路径与新增证据",
        "D10 前半程对账",
        "D20 前20日结果与最终结论",
        "不新增其他节点",
    ):
        assert phrase in text


def test_review_skill_requires_daily_briefs_and_cautious_tracking_exit() -> None:
    text = Path(
        ".agents/skills/reviewing-stock-recommendations/SKILL.md"
    ).read_text(encoding="utf-8")

    for phrase in (
        "每个已收盘交易日",
        "current_path",
        "是否仍在原推荐预期内",
        "未来1—3个交易日",
        "weakening 不能单独",
        "原推荐最重要的判断被事实否定",
        "无法执行",
        "停止主动跟踪后",
        "D20",
        "最多8只普通详评",
    ):
        assert phrase in text


def test_public_review_only_lists_explicit_formal_recommendations() -> None:
    text = Path("ops/forward-monitor-prompt.md").read_text(encoding="utf-8")

    assert "正式推荐股票的今日复盘" in text
    assert "confirmed_active" in text
    assert "legacy_v1_not_rewritten" in text
    assert "conditional_event" in text
    assert "不得出现在“正式推荐股票的今日复盘”中" in text
    assert "今天发生了什么" in text
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
    assert "用户当前状态和简短前缀使用 `action_date`" in orchestrator
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
        "简评只写当天重要增量",
        "事件详评",
        "D20 最终复盘",
        "字段和值",
        "outlook_reason_plain_language",
        "先作出方向判断",
        "当前最重要的1—3项事实",
        "条件只负责以后验证",
    ):
        assert phrase in prompt

    for direction in (
        "继续向上",
        "震荡偏上",
        "横盘整理",
        "震荡偏下",
        "继续偏弱",
        "没有足够的可交易事实判断方向",
    ):
        assert direction in prompt


def test_review_prompt_explains_twenty_day_target_feasibility_without_linear_projection() -> None:
    prompt = Path("ops/forward-monitor-prompt.md").read_text(encoding="utf-8")

    for phrase in (
        "20%目标仍有现实可能",
        "需要重新加速才有可能",
        "目前已明显变得困难",
        "已经不再以完成目标为主要判断",
        "无法计算",
        "不按每天1%线性推算",
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
        "今天发生了什么",
        "相比上次判断",
        "接下来1—3个交易日",
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
        "目前没有足够的可交易事实判断方向",
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


def test_review_skill_makes_future_direction_a_reasoned_judgment() -> None:
    skill = Path(
        ".agents/skills/reviewing-stock-recommendations/SKILL.md"
    ).read_text(encoding="utf-8")

    for phrase in (
        "未来方向不是条件清单",
        "outlook_reason_plain_language",
        "向上",
        "震荡偏上",
        "横盘",
        "震荡偏下",
        "向下",
        "暂时无法判断",
        "未来1—3个交易日",
        "条件只负责以后验证",
        "20%目标仍有现实可能",
        "需要重新加速才有可能",
        "目前已明显变得困难",
        "已经不再以完成目标为主要判断",
        "无法计算",
        "不按每天1%线性推算",
    ):
        assert phrase in skill


def test_prompts_keep_daily_body_and_expanded_detail_separate() -> None:
    paths = [
        "ops/forward-monitor-prompt.md", "ops/forward-selection-prompt.md",
        ".agents/skills/reviewing-stock-recommendations/SKILL.md",
        ".agents/skills/orchestrating-stock-research/SKILL.md",
    ]
    for path in paths:
        text = Path(path).read_text(encoding="utf-8")
        for phrase in ("DailyFormalReviewV1.current_review", "ForwardEpisodeReviewV1.current_review",
                       "view_change_reason",
                       "今天发生了什么", "相比上次判断", "接下来1—3个交易日",
                       "D1", "D20", "历史锚点"):
            assert phrase in text, (path, phrase)
        for old in ("推荐日期和当时判断", "到今天走到哪里", "我的分析", "接下来更可能怎样",
                    "必须逐字复制", "再逐字复制到"):
            assert old not in text, (path, old)


def test_outlook_conditions_are_defined_relative_to_current_direction() -> None:
    for path in ("ops/forward-monitor-prompt.md", ".agents/skills/reviewing-stock-recommendations/SKILL.md"):
        text = Path(path).read_text(encoding="utf-8")
        assert "支持当前 outlook_1_3d" in text
        rows = [line for line in text.splitlines() if line.startswith("| `")]
        expected = {
            "strengthening": ("提高收盘", "连续收低"),
            "weakening": ("降低收盘", "提高收盘"),
            "overheated": ("冲高回落", "更高收盘"),
            "range_or_wait": ("原区间", "突破区间"),
            "event_pending": ("仍缺少", "出现完整可交易价格"),
        }
        for state, (supports, changes) in expected.items():
            row = next(row for row in rows if f"`{state}`" in row)
            columns = row.split("|")
            assert supports in columns[2]
            assert changes in columns[3]
        assert "`continuation_possible`" in text and "`invalidated`" in text


def test_monitor_shares_evening_cutoff_with_selection():
    text = Path("ops/forward-monitor-prompt.md").read_text(encoding="utf-8")
    assert "18:45" in text
    assert "周日" in text and "周五" in text
    assert "--stage pre-research" in text
    assert "--as-of <selection_as_of>" in text
    assert "next-morning" not in text
    assert "09:05" not in text


def test_review_prompt_pins_plain_language_standard_and_style_anchor() -> None:
    monitor = Path("ops/forward-monitor-prompt.md").read_text(encoding="utf-8")
    skill = Path(
        ".agents/skills/reviewing-stock-recommendations/SKILL.md"
    ).read_text(encoding="utf-8")

    for phrase in ("直接说事，不表演通俗", "不打比方", "文风基准",
                   "缩量整理两天后今天放量再攻"):
        assert phrase in monitor
    for phrase in ("直接说事，不表演通俗", "人话优先"):
        assert phrase in skill
    # 软数量配额已被三路互斥方案删除，不得回潮。
    for legacy in ("最多4个", "60—140", "150—320", "180—350", "400—800"):
        assert legacy not in monitor
        assert legacy not in skill
