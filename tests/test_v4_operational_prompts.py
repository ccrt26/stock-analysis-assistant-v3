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
