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
    assert text.count("stock_analyzer.ops.forward_selection prepare") == 1
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
