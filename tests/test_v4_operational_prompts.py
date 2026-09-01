from pathlib import Path


def test_daily_prompt_is_v4_only() -> None:
    text = Path("ops/forward-selection-prompt.md").read_text(encoding="utf-8")
    assert "daily-research-trace-v4" in text
    assert "DailyResearchTraceV4" in text
    assert "compute_event_reaction_features_v3" in text
    assert "daily-research-trace-v3" not in text
    assert "market_propagation_environment" not in text
    assert "engine_type: company_event" not in text
    assert "engine_status=fresh_event_pending" not in text
    assert text.count("stock_analyzer.ops.forward_selection prepare") == 3
    assert "用户要求补跑早晨失败任务时" in text
    assert text.count("--rerun-date <原计划推荐日期>") == 2
    assert "ready_for_research_limited" in text
    assert "受限模式必须把不可用通道交给总控，不得补猜" in text
    assert (
        "这是对<日期>早晨任务的补跑。研究只使用当日09:05前能够看到的信息；"
        "原开盘观察时点已经过去，当前价格不能替代当时的参与条件。"
        in text
    )
    for question in (
        "为什么现在值得看",
        "目前有什么实际推动",
        "股价和成交有没有认可",
        "推荐后的第一个交易日要看什么",
        "已经涨了多少，后面是否还有空间",
        "最不利的事实",
        "为什么选它而不是最接近的备选",
    ):
        assert question in text
    assert "已过原行动窗口" not in text
    assert (
        "不要把当前价格当成当时可以参与的价格，也不要用盘中走势重新改写开盘前的研究结论"
        in text
    )


def test_daily_prompt_and_v4_contract_define_runtime_data_capability_boundary() -> None:
    prompt = Path("ops/forward-selection-prompt.md").read_text(encoding="utf-8")
    contract = Path(
        "docs/architecture/a-share-short-horizon-engine-contract-v4.md"
    ).read_text(encoding="utf-8")
    skill = Path(
        ".agents/skills/orchestrating-stock-research/SKILL.md"
    ).read_text(encoding="utf-8")

    for text in (prompt, contract, skill):
        assert "runtime_capabilities" in text
        assert "industry_research_available" in text
        assert "theme_research_available" in text
        assert "announcement_status" in text
        assert "exchange_partial" in text
        assert "未覆盖交易所" in text
    assert "complete_core_date` 只作诊断" in prompt
    assert "不得因为行业或主题一项缺失而停止其他研究路径" in skill


def test_periodic_review_prompt_is_v4_only() -> None:
    text = Path("ops/periodic-research-review-prompt.md").read_text(encoding="utf-8")
    for engine in (
        "fresh_event_pending",
        "event_repricing_confirmed",
        "sector_broad_diffusion",
        "sector_leader_cluster",
        "independent_demand_acceleration",
        "anchor_only",
        "unresolved",
    ):
        assert engine in text
    assert "daily-research-trace-v3" not in text
    assert "engine_status=confirmed | fresh_event_pending | unconfirmed | invalidated" not in text
    assert text.startswith("# 前20个交易日结束后的集中研究复盘")
    assert "期间最高涨幅" in text
    assert "期间最深跌幅" in text
    assert "推荐股与当时最接近但未推荐股票的比较" in text
    assert "不自动修改 Skill" in text


def test_detailed_recommendation_explanation_is_required_after_selection_freeze() -> None:
    prompt = Path("ops/forward-selection-prompt.md").read_text(encoding="utf-8")
    orchestrator = Path(
        ".agents/skills/orchestrating-stock-research/SKILL.md"
    ).read_text(encoding="utf-8")
    company = Path(
        ".agents/skills/researching-company-events/SKILL.md"
    ).read_text(encoding="utf-8")

    for phrase in (
        "汇总表只能作为目录",
        "公司是做什么的",
        "为什么偏偏是现在",
        "为什么不是普通跟涨",
        "关键数字说明什么",
        "为什么还可能有路径",
        "已知的不利事实",
        "资料限制",
        "下一个交易日",
        "每只股票建议300—500个中文字",
    ):
        assert phrase in prompt

    for phrase in (
        "名单冻结后的用户解释",
        "不得新增、删除、替换、重新排序股票",
        "company_profile",
        "main_business",
        "汇总表不能代替逐只说明",
    ):
        assert phrase in orchestrator

    for phrase in (
        "最终名单的公司介绍补充",
        "只服务于用户理解",
        "公司主要卖什么产品或提供什么服务",
        "资料缺失和公司风险必须分开",
        "不能被总控当成新的入选理由",
    ):
        assert phrase in company
