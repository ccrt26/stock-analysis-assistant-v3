from pathlib import Path
import re


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
    assert "用户要求补跑晚间失败任务时" in text
    assert text.count("--rerun-date <原计划推荐日期>") == 2
    assert "ready_for_research_limited" in text
    assert "受限模式必须把不可用通道交给总控，不得补猜" in text
    assert (
        "这是对<日期>交易日前晚任务的补跑。研究仍使用原计划交易日前一自然日18:30的固定截止；"
        "当前价格不能替代当时的参与条件。"
        in text
    )
    assert "已过原行动窗口" not in text
    assert (
        "不要把当前价格当成当时可以参与的价格，也不要用盘中走势重新改写开盘前的研究结论"
        in text
    )


def test_daily_prompt_declares_the_only_final_response_source() -> None:
    text = Path("ops/forward-selection-prompt.md").read_text(encoding="utf-8")

    for phrase in (
        "最终回复唯一来源",
        "不得在生成归档后另写执行摘要",
        "复盘部分直接采用本次已记录的正式复盘Markdown",
        "不得追加Git、工作区、测试和文件清理汇报",
    ):
        assert phrase in text


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
        "为什么会选它",
        "行业或外部变化",
        "股票自身表现",
        "公司经营",
        "主要不利因素",
        "综合判断",
        "什么情况会让我改变看法",
        "每只约350—650字",
        "没有某个维度的可靠支持，就不写该小标题",
        "每段最多2—4句话",
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
        "为什么会选它",
        "行业或外部变化",
        "股票自身表现",
        "主要不利因素",
        "综合判断",
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
        "为什么会选它",
        "股票自身表现",
        "较早确认、正常启动还是已经偏晚",
    ):
        assert phrase in prompt

    assert "供<action_date>交易日参考" in prompt
    user_output = prompt.split("### 唯一用户输出格式", maxsplit=1)[1]
    for forbidden in ("冻结时点", "冻结结论", "正常双向成交", "农业样本"):
        assert forbidden not in user_output


def test_unique_user_output_hides_event_leads_and_uses_four_sections() -> None:
    prompt = Path("ops/forward-selection-prompt.md").read_text(encoding="utf-8")
    user_output = prompt.split("### 唯一用户输出格式", maxsplit=1)[1]

    headings = (
        "今天的市场情况",
        "正式推荐股票的今日复盘",
        "目前仍开放的正式推荐股票数量",
        "今天明确推荐的股票",
    )
    for heading in headings:
        assert heading in user_output
    for forbidden in (
        "等待首个交易日确认的事件线索",
        "conditional名单",
        "conditional数量",
        "最近未选",
        "比较股",
    ):
        assert forbidden not in user_output
    assert re.findall(r"^## (.+)$", user_output, re.M) == list(headings)

    for phrase in (
        "关键节点复盘、今日深入复盘 与 今日简评",
        "今天重点复盘的8只股票" if False else "今日简评为六列简表",
        "主动跟踪：X只",
        "仅保留评价：Y条",
        "已完成：Z条",
        "record-daily-formal-reviews",
        "daily-formal-reviews-<analysis_date>.json",
    ):
        assert phrase in prompt


def test_internal_event_contract_remains_after_public_event_section_is_removed() -> None:
    prompt = Path("ops/forward-selection-prompt.md").read_text(encoding="utf-8")

    for phrase in (
        "fresh_event_pending",
        "conditional_event",
        "首个完整交易日",
        "内部 V4 trace",
        "事件公司证据",
    ):
        assert phrase in prompt


def test_review_priority_delivery_documents_match_the_new_public_contract() -> None:
    root = Path(
        "research/skill-optimization/review-priority-outlook-format-20260903"
    )
    diagnosis = (root / "current-production-diagnosis.md").read_text(
        encoding="utf-8"
    )
    implementation = (root / "implementation-diagnosis.md").read_text(
        encoding="utf-8"
    )
    sample = (root / "expected-user-report-v5.md").read_text(
        encoding="utf-8"
    )

    for phrase in (
        "formal:2026-08-25:002274.SZ:selected",
        "new_official_event",
        "data_problem",
        "entry_open",
        "formal_return_started",
        "previous_episode_review",
        "没有改变控制权安排的核心条款",
    ):
        assert phrase in diagnosis

    for phrase in (
        "outlook_reason_plain_language",
        "不用公告标题关键词过滤",
        "内部记录仍完整",
        "没有重做选股或复盘系统",
        "目前没有足够的可交易事实判断方向",
    ):
        assert phrase in implementation

    for heading in (
        "今天的市场情况",
        "正式推荐股票的走势复盘",
        "目前仍开放的正式推荐股票数量",
        "今天明确推荐的股票",
    ):
        assert heading in sample
    for phrase in (
        "未来1—3个交易日更可能继续向上",
        "未来1—3个交易日更可能横盘整理",
        "未来1—3个交易日更可能震荡偏下",
        "主要原因是：",
        "支持这个判断的后续表现：",
        "需要改变判断的后续表现：",
        "中航西飞",
        "万兴科技",
        "行业或外部变化",
        "股票自身表现",
        "公司经营",
        "主要不利因素",
        "综合判断",
    ):
        assert phrase in sample
    for forbidden in (
        "华昌化工",
        "等待首个交易日确认的事件线索",
        "中国船舶",
        "北京科锐",
        "最近未选",
        "比较股",
        "Git状态",
        "工作区状态",
    ):
        assert forbidden not in sample


def test_archived_execution_instruction_is_a_verbatim_copy() -> None:
    source = Path(
        "/Users/ccrt/Downloads/"
        "Codex执行指令_重点复盘未来判断与荐股展示优化_V1.0.md"
    )
    archived = Path(
        "docs/2026-09-03-review-priority-outlook-format-prompt.md"
    )

    assert archived.read_bytes() == source.read_bytes()


def test_unique_output_assigns_disjoint_headings_to_reviews_and_new_recommendations() -> None:
    text = Path("ops/forward-selection-prompt.md").read_text(encoding="utf-8")
    output = text.split("### 唯一用户输出格式", 1)[1]
    review = output.split("## 正式推荐股票的今日复盘", 1)[1].split("## 目前仍开放", 1)[0]
    recommendation = output.split("## 今天明确推荐的股票", 1)[1]
    review_headings = re.findall(r"^\*\*(.+)\*\*$", review, re.M)
    recommendation_headings = re.findall(r"^\*\*(.+)\*\*$", recommendation, re.M)
    assert review_headings == ["今天发生了什么", "相比上次判断", "接下来1—3个交易日"]
    assert recommendation_headings == [
        "公司主要做什么", "为什么会选它", "行业或外部变化", "股票自身表现",
        "公司经营", "主要不利因素", "综合判断", "什么情况会让我改变看法",
    ]
    assert set(review_headings).isdisjoint(recommendation_headings)
    assert "复盘部分直接采用本次已记录的正式复盘Markdown，不重新摘要" in text


def test_evening_prompt_freezes_cutoff_and_skips_preholiday_reports():
    text = Path("ops/forward-selection-prompt.md").read_text(encoding="utf-8")
    for phrase in ("18:45", "18:55", "次日前一自然日", "--stage pre-research",
                   "--as-of <selection_as_of>", "明天不是交易日", "本报告使用截至<selection_as_of>"):
        assert phrase in text
    assert "next-morning" not in text
    assert "09:05" not in text
    assert "截止时间以后至开盘前的新公告不属于本次正式研究范围" in text
    safety = Path("ops/preopen-safety-prompt.md").read_text(encoding="utf-8")
    for phrase in ("preopen_safety prepare", "暂缓参与", "不得重新选股", "不得增加或替换股票"):
        assert phrase in safety
