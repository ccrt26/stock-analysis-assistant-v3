import csv
from pathlib import Path
import yaml
def _payload(): return yaml.safe_load(Path("src/stock_analyzer/knowledge/research_registry.yaml").read_text(encoding="utf-8"))
def test_v4_knowledge_entries_exist():
 ids={x["knowledge_id"] for x in _payload()["entries"]}; assert {"src_cn_disclosure_novelty_chain","src_cn_market_propagation_modes","src_cn_sector_leader_cluster","src_cn_attention_proxy_boundary"} <= ids
def test_v4_sources_have_no_duplicate_id_or_doi():
 sources=_payload()["sources"]; ids=[x["source_id"] for x in sources]; assert len(ids)==len(set(ids)); dois=[str(x.get("doi","")).lower() for x in sources if x.get("doi")]; assert len(dois)==len(set(dois))
def test_v4_daily_prompt_and_contract_use_exact_taxonomy():
 prompt=Path("ops/forward-selection-prompt.md").read_text(encoding="utf-8"); contract=Path("docs/architecture/a-share-short-horizon-engine-contract-v4.md").read_text(encoding="utf-8")
 for term in ("daily-research-trace-v4","fresh_event_pending","event_repricing_confirmed","sector_broad_diffusion","sector_leader_cluster","independent_demand_acceleration","one_day_repair","sector_rotation","concentrated_speculation"): assert term in prompt+contract


def test_five_skills_have_unique_selection_responsibilities_and_v4_output() -> None:
    paths = {
        "orchestrator": ".agents/skills/orchestrating-stock-research/SKILL.md",
        "market": ".agents/skills/interpreting-market-macro/SKILL.md",
        "sector": ".agents/skills/researching-sectors-industries/SKILL.md",
        "company": ".agents/skills/researching-company-events/SKILL.md",
        "price": ".agents/skills/analyzing-price-trading/SKILL.md",
        "contract": "docs/architecture/a-share-short-horizon-engine-contract-v4.md",
    }
    text = {
        name: Path(path).read_text(encoding="utf-8")
        for name, path in paths.items()
    }

    assert "trace_version: daily-research-trace-v4" in text["orchestrator"]
    assert "trace_version: daily-research-trace-v3" not in text["orchestrator"]
    assert "engine_status: confirmed" not in text["orchestrator"]
    assert "engine_status: fresh_event_pending" not in text["orchestrator"]
    assert "同发动机组内比较 → 跨发动机比较 → 逐只绝对质量判断" in text["orchestrator"]
    assert "不能因为它是剩余候选中最好的一只而补位" in text["orchestrator"]
    assert "conditional 只允许用于 `fresh_event_pending`" in text["orchestrator"]

    assert "市场模式只改变下一步搜索重点和市场反证强度" in text["market"]
    assert "普涨仍须证明候选的相对增量" in text["market"]
    assert "未知不自动选择，也不自动淘汰" in text["market"]

    assert "共同动力 → leader/core 角色 → 同板块近邻" in text["sector"]
    assert "不判断候选完整的个股连续性、剩余路径或最终淘汰" in text["sector"]

    assert "新增性 → 阶段 → 主营联系 → 材料性 → 财务传导 → 兑现时间 → 失败条款" in text["company"]
    assert "不宣布价格接受、可靠入口或最终推荐" in text["company"]

    assert "1/3/5 日连续性 → 单日贡献 → 有效收盘 → 成交推进 → 回落 → 组合余量" in text["price"]
    assert "不证明公司业务或板块传播，也不作最终选择" in text["price"]

    assert "selection_output_class" in text["contract"]
    assert "conditional_event" in text["contract"]
    assert "原 conditional trace 永不原地晋升" in text["contract"]


def test_entry_timing_and_review_skills_keep_selection_and_review_separate() -> None:
    price = Path(
        ".agents/skills/analyzing-price-trading/SKILL.md"
    ).read_text(encoding="utf-8")
    orchestrator = Path(
        ".agents/skills/orchestrating-stock-research/SKILL.md"
    ).read_text(encoding="utf-8")
    review = Path(
        ".agents/skills/reviewing-stock-recommendations/SKILL.md"
    ).read_text(encoding="utf-8")
    interface = yaml.safe_load(
        Path(
            ".agents/skills/reviewing-stock-recommendations/agents/openai.yaml"
        ).read_text(encoding="utf-8")
    )

    for phrase in (
        "获得的确认",
        "已经付出的涨幅",
        "去掉最大上涨日",
        "最大上涨日之后",
        "确认仍大于追高风险",
        "追高风险已经大于确认",
        "现有事实还无法判断",
    ):
        assert phrase in price
    assert "不能一边说核心持续性没有验证一边正式推荐" in orchestrator
    assert "reviewing-stock-recommendations" in review
    assert "具体推荐日期" in review
    assert "当前收盘相对推荐参考价、期间最高收盘和最深下跌" in review
    assert "## 20日目标的可实现性" in review
    assert "不新增定时任务" in review
    assert interface["interface"]["display_name"] == "正式推荐复盘"


def test_review_skill_requires_causal_comparison_expectation_phase_and_outlook() -> None:
    review = Path(
        ".agents/skills/reviewing-stock-recommendations/SKILL.md"
    ).read_text(encoding="utf-8")
    price = Path(
        ".agents/skills/analyzing-price-trading/SKILL.md"
    ).read_text(encoding="utf-8")
    orchestrator = Path(
        ".agents/skills/orchestrating-stock-research/SKILL.md"
    ).read_text(encoding="utf-8")

    for phrase in (
        "最有证据的主要解释",
        "为什么这一解释比其他解释更有证据",
        "推荐日最重要的预期",
        "上涨后整理",
        "无法执行",
        "未来1—3个交易日",
        "相对行业表现",
        "行业上涨面",
    ):
        assert phrase in review
    for phrase in (
        "推荐后实际路径",
        "最大上涨日贡献",
        "突破位置",
        "最接近的价格阶段",
    ):
        assert phrase in price
    assert (
        "今天发生了什么、相比上次判断、接下来1—3个交易日"
        in orchestrator
    )


def test_review_skill_requires_an_analyst_style_view_update() -> None:
    review = Path(
        ".agents/skills/reviewing-stock-recommendations/SKILL.md"
    ).read_text(encoding="utf-8")
    interface = yaml.safe_load(
        Path(
            ".agents/skills/reviewing-stock-recommendations/agents/openai.yaml"
        ).read_text(encoding="utf-8")
    )["interface"]

    for phrase in (
        "一个中心问题",
        "一句话观点更新",
        "与上一次复盘的比较填写当天 `view_change` 和 `view_change_reason`",
        "后续基准判断",
        "观点更新稿",
        "事实与观点分开",
        "不平均复述市场、行业、公司和价格四路内容",
    ):
        assert phrase in review
    assert (
        "不得把“最有证据的解释是”“当前阶段是”“核心预期目前得到支持”"
        "当作固定开头"
        in review
    )
    assert "只用最少且可追溯的决定性事实" in interface["default_prompt"]
    assert "D20才串起完整过程" in interface["default_prompt"]


def test_review_skill_avoids_new_template_and_uses_traceable_minimum_facts() -> None:
    review = Path(
        ".agents/skills/reviewing-stock-recommendations/SKILL.md"
    ).read_text(encoding="utf-8")

    for phrase in (
        "最多4个，不设最低数量",
        "不得为了满足数量凑事实",
        "可以是一段，也可以是两三段",
        "通常不必写“这是首次复盘”",
        "每一项具体",
        "能够追溯到",
        "previous_episode_review.current_assessment",
        "previous_episode_review.best_supported_explanation",
        "仅仅换了一种措辞，不叫观点改变",
        "D20 是唯一形成完整最终结论的复盘",
        "第21—30日",
    ):
        assert phrase in review

    for old in (
        "只使用2—4个决定性事实",
        "D10：250—450个中文字",
        "写成2—3个自然段",
    ):
        assert old not in review


def test_selection_impact_matrix_is_complete_and_keeps_future_outcomes_separate() -> None:
    path = Path(
        "research/skill-optimization/"
        "five-skill-selection-logic-optimization-20260901/"
        "selection-impact-matrix.csv"
    )
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    expected_columns = [
        "event_key",
        "formation_date",
        "action_date",
        "ts_code",
        "name",
        "trace_version",
        "original_engine_type",
        "original_engine_status",
        "original_output_class",
        "revised_output_class",
        "primary_selection_logic_issue",
        "revised_formation_day_decision",
        "same_engine_comparator",
        "decisive_support",
        "decisive_counterevidence",
        "action_condition_effect",
        "early_outcome_used_only_for_evaluation",
        "notes",
    ]
    assert list(rows[0]) == expected_columns
    assert len(rows) == 29
    assert len({row["event_key"] for row in rows}) == 29

    allowed_revised_classes = {
        "confirmed_active",
        "conditional_event",
        "rejected_by_revised_logic",
        "unresolved_by_revised_logic",
        "legacy_v1_not_rewritten",
    }
    assert {row["revised_output_class"] for row in rows} <= allowed_revised_classes
    legacy_rows = [row for row in rows if row["trace_version"] != "daily-research-trace-v4"]
    assert len(legacy_rows) == 8
    assert {row["revised_output_class"] for row in legacy_rows} == {
        "legacy_v1_not_rewritten"
    }

    conditional_rows = [
        row for row in rows if row["revised_output_class"] == "conditional_event"
    ]
    assert len(conditional_rows) == 4
    assert {row["original_engine_type"] for row in conditional_rows} == {
        "fresh_event_pending"
    }
    assert {row["action_condition_effect"] for row in conditional_rows} <= {
        "met",
        "not_met",
        "unknown",
    }
    assert all(row["action_condition_effect"] for row in conditional_rows)
    assert all(row["early_outcome_used_only_for_evaluation"] for row in rows)
    assert all(
        not row["action_condition_effect"]
        for row in rows
        if row["revised_output_class"] != "conditional_event"
    )


def test_entry_stage_impact_uses_complete_v4_windows_and_allowed_effects() -> None:
    path = Path(
        "research/skill-optimization/entry-timing-review-skill-20260902/"
        "entry-stage-impact.csv"
    )
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert list(rows[0]) == [
        "event_key",
        "formation_date",
        "action_date",
        "ts_code",
        "name",
        "engine_type",
        "return_5d",
        "return_20d",
        "price_location_60d",
        "limit_up_return_contribution_5d",
        "largest_positive_day_contribution_5d",
        "sessions_since_largest_positive_day_5d",
        "return_ex_largest_positive_day_5d",
        "return_after_largest_positive_day_5d",
        "relative_market_after_largest_positive_day_5d",
        "original_decision",
        "revised_price_conclusion",
        "revised_selection_effect",
        "plain_reason",
    ]
    assert len(rows) == 29
    assert len({row["event_key"] for row in rows}) == 29
    assert {row["revised_selection_effect"] for row in rows} <= {
        "keep",
        "lower_priority",
        "not_yet_formal",
        "insufficient_data",
        "legacy_not_rebuilt",
    }
    rebuilt = [
        row for row in rows
        if row["revised_selection_effect"] != "legacy_not_rebuilt"
    ]
    assert len(rebuilt) == 21
    assert all(row["largest_positive_day_contribution_5d"] for row in rebuilt)
    assert sum(
        float(row["largest_positive_day_contribution_5d"]) >= 0.50
        or float(row["limit_up_return_contribution_5d"]) >= 0.50
        for row in rebuilt
    ) == 10
    assert sum(
        float(row["sessions_since_largest_positive_day_5d"]) == 0
        for row in rebuilt
    ) == 10
    assert sum(
        float(row["return_ex_largest_positive_day_5d"]) <= 0
        for row in rebuilt
    ) == 4


def test_forward_review_methods_are_registered_without_duplicate_existing_sources():
 payload=_payload(); source_ids={x["source_id"] for x in payload["sources"]}; entry_ids={x["knowledge_id"] for x in payload["entries"]}
 assert {"cfa-performance-attribution-2019","paper-perold-implementation-shortfall-1988","paper-chen-gao-he-jiang-xiong-price-limits-2019","paper-pan-tang-xu-speculative-trading-2016"} <= source_ids
 assert {"src_forward_review_benchmark_execution","src_cn_forward_review_trading_boundaries"} <= entry_ids
 assert sum(x["source_id"] == "paper-mackinlay-event-study-1997" for x in payload["sources"]) == 1
 assert sum(x["source_id"] == "paper-liu-stambaugh-yuan-2019" for x in payload["sources"]) == 1
 review_ids={"src_forward_review_benchmark_execution","src_cn_forward_review_trading_boundaries"}
 for entry in (x for x in payload["entries"] if x["knowledge_id"] in review_ids):
  assert entry["primary_source_id"] in source_ids
  assert set(entry["supporting_source_ids"]) <= source_ids


def test_forward_review_paper_dates_follow_official_pages_without_guessing_a_day():
 sources={x["source_id"]: x for x in _payload()["sources"]}
 pan=sources["paper-pan-tang-xu-speculative-trading-2016"]
 assert str(pan["publication_date"]) == "2015-12-14"
 assert pan["issue_date"] == "2016-08"
 chen=sources["paper-chen-gao-he-jiang-xiong-price-limits-2019"]
 assert "publication_date" not in chen
 assert "2019年1月卷期" in chen["publication_date_status"]


def test_sector_skill_and_current_knowledge_require_labeled_industry_proxy() -> None:
    skill = Path(
        ".agents/skills/researching-sectors-industries/SKILL.md"
    ).read_text(encoding="utf-8")
    assert "industry_daily_proxy" in skill
    assert "本地可回放代理，不是官方申万指数" in skill
    assert "旧 `industry_daily` 补位" in skill

    entries = {
        item["knowledge_id"]: item for item in _payload()["entries"]
    }
    for knowledge_id in (
        "src_cn_factor_momentum_2023",
        "src_moskowitz_grinblatt_1999",
    ):
        requirements = entries[knowledge_id]["data_requirements"]
        names = {item["name"] for item in requirements}
        assert "industry_daily_proxy" in names
        assert "industry_daily" not in names
