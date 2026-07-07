from pathlib import Path

from stock_analyzer.knowledge.rule_schema import load_rules


SEED_RULES_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "stock_analyzer"
    / "knowledge"
    / "rules.seed.yaml"
)


def test_seed_rules_have_required_fields():
    rules = load_rules(SEED_RULES_PATH)
    assert len(rules) >= 4
    for rule in rules:
        assert rule.rule_id
        assert rule.source_reference
        assert rule.source_grade in {"S", "A", "B"}
        assert rule.rule_type in {
            "hard_constraint",
            "explanation",
            "counter_evidence",
            "evaluation",
        }
        assert rule.data_requirements
        assert rule.evaluation_method


def test_official_s_rule_can_be_hard_constraint():
    rules = load_rules(SEED_RULES_PATH)
    official_rules = [
        rule for rule in rules if rule.source_grade == "S" and rule.rule_type == "hard_constraint"
    ]
    assert {rule.rule_id for rule in official_rules} >= {
        "OFFICIAL_ST_EXCLUDE",
        "OFFICIAL_DELISTING_RISK_EXCLUDE",
    }
