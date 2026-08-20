from __future__ import annotations

import hashlib
from pathlib import Path

import yaml


ROOT = Path(__file__).parents[1]
KNOWLEDGE = ROOT / "src" / "stock_analyzer" / "knowledge"


def test_market_hypotheses_match_the_frozen_checksum() -> None:
    hypothesis = KNOWLEDGE / "market_skill_hypotheses.yaml"
    expected = (KNOWLEDGE / "market_skill_hypotheses.sha256").read_text().split()[0]

    assert hashlib.sha256(hypothesis.read_bytes()).hexdigest() == expected


def test_every_adopted_market_source_is_persisted_with_audit_metadata() -> None:
    registry = yaml.safe_load((KNOWLEDGE / "research_registry.yaml").read_text())
    evidence = yaml.safe_load((KNOWLEDGE / "market_skill_evidence.yaml").read_text())
    sources = {item["source_id"]: item for item in registry["sources"]}

    for decision in evidence["adopted_sources"]:
        source = sources[decision["source_id"]]
        assert {
            "source_id",
            "grade",
            "kind",
            "title",
            "publisher",
            "authors",
            "url",
            "last_verified_on",
            "market_scope",
            "method_summary",
        } <= set(source)
        assert decision["allowed_uses"]
        assert decision["forbidden_uses"]
        assert decision["data_needs"]
        assert decision["local_validation"]


def test_only_dispersion_is_level_two_among_empirical_market_hypotheses() -> None:
    results = yaml.safe_load(
        (KNOWLEDGE / "market_skill_validation_results.yaml").read_text()
    )
    maturity = {
        item["hypothesis_id"]: item["maturity"] for item in results["results"]
    }

    assert maturity == {
        "market_h1_breadth_index_alignment": "validation_capability",
        "market_h2_turnover_price_progress": "validation_capability",
        "market_h3_dispersion_future_volatility": "level_2_direct",
        "market_h4_state_changes_trend_reliability": "validation_capability",
    }


def test_market_skill_requires_candidate_specific_dependency_reviews() -> None:
    skill = (
        ROOT / ".agents" / "skills" / "interpreting-market-macro" / "SKILL.md"
    ).read_text()

    assert "market-context-v3" in skill
    assert "candidate_reviews" in skill
    assert "dependency_type" in skill
    assert "raises_path_risk" in skill
    assert "未登记来源只能列为待核材料" in skill
