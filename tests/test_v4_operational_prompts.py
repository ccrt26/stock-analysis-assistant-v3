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
        "公司主要做什么",
        "为什么在这个时间选择它",
        "支持选择的独立原因",
        "最需要担心什么，以及为什么仍然选择",
        "什么情况会让我改变看法",
        "每只约300—500字",
    ):
        assert phrase in prompt

    for phrase in (
        "名单冻结后的用户说明",
        "不得重新选择股票",
        "公司简介只帮助用户理解公司",
        "内部选择理由和对外推荐说明都不能只是事实清单",
        "股票未来继续走强主要依靠什么",
        "最不利事实怎样削弱判断",
        "为什么仍然入选",
    ):
        assert phrase in orchestrator

    for phrase in (
        "最终名单的公司介绍补充",
        "只服务于用户理解",
        "公司主要卖什么产品或提供什么服务",
        "资料不全时只说哪份资料暂时没有取得",
        "不能被总控当成新的入选理由",
        "公司事实在推荐理由中的作用必须说清",
        "不能自动证明短期股价会涨",
        "减少了纯题材炒作的可能性",
    ):
        assert phrase in company


def test_recommendation_prompt_uses_fact_first_plain_language() -> None:
    prompt = Path("ops/forward-selection-prompt.md").read_text(encoding="utf-8")

    for phrase in (
        "公司主要做什么",
        "为什么在这个时间选择它",
        "支持选择的独立原因",
        "最需要担心什么，以及为什么仍然选择",
        "什么情况会让我改变看法",
        "32只农业相关股票中",
        "事实本身不是推荐理由",
    ):
        assert phrase in prompt

    for old_heading in (
        "为什么偏偏是现在",
        "为什么不是普通跟涨",
        "关键数字说明什么",
        "为什么还可能有路径",
        "这次为什么会选它",
        "股价已经怎么走",
    ):
        assert old_heading not in prompt


def test_selection_prompt_requires_reasoning_not_a_fact_list() -> None:
    prompt = Path("ops/forward-selection-prompt.md").read_text(encoding="utf-8")

    for phrase in (
        "事实本身不是推荐理由",
        "为什么这些事实让继续上涨更有可能",
        "哪些事实支持，哪些事实反对",
        "为什么最不利的事实暂时没有推翻推荐",
        "为什么是这只股票，而不是同行里另一只",
        "五日多数涨幅来自一个涨停日时",
    ):
        assert phrase in prompt

    assert "推荐理由必须是一个完整论证" in prompt
    assert "不得把涨幅、成交额和涨停贡献并排后直接得出推荐" in prompt


def test_selection_prompt_separates_confirmation_from_price_already_paid() -> None:
    prompt = Path("ops/forward-selection-prompt.md").read_text(encoding="utf-8")

    for phrase in (
        "获得的确认",
        "已经付出的涨幅",
        "去掉最大上涨日",
        "最大上涨日之后",
        "不能一边说核心持续性没有验证一边正式推荐",
        "为什么在这个时间选择它",
        "支持选择的独立原因",
        "为什么不是追在短期高点之后",
    ):
        assert phrase in prompt

    assert "我们在<action_date>开盘前选择这只股票" in prompt
    user_output = prompt.split("### 唯一用户输出格式", maxsplit=1)[1]
    for forbidden in ("冻结时点", "冻结结论", "正常双向成交", "农业样本"):
        assert forbidden not in user_output
