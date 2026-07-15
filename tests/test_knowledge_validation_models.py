from datetime import date
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from stock_analyzer.data.research_contracts import ResearchDatasetId
from stock_analyzer.knowledge_validation.models import (
    LayerResult,
    MethodStatus,
    RelevanceStatus,
    SampleSufficiency,
    ValidationResult,
    ValidationSpec,
)
from stock_analyzer.knowledge_validation.spec_registry import (
    STUDY_IDS,
    load_validation_registry,
)


REAL_SPEC_PATH = (
    Path(__file__).parents[1]
    / "src"
    / "stock_analyzer"
    / "knowledge_validation"
    / "studies.yaml"
)


def valid_spec_payload() -> dict:
    return {
        "study_id": "a_share_size_value",
        "specification_version": "v1",
        "knowledge_ids": ["src_liu_stambaugh_yuan_2019"],
        "migration_ids": ["legacy-a-share-size-value"],
        "theory_claim": "A股估值比较必须控制规模和不可比盈利状态。",
        "signal_definition": "在同日市值组内比较正盈利公司的E/P。",
        "primary_hypothesis": "高E/P组未来相对收益高于低E/P组。",
        "primary_statistic": "top_minus_bottom_20d_excess_return",
        "horizons": [10, 20, 30],
        "required_datasets": ["equity_daily", "adj_factor", "daily_basic"],
        "sufficiency": {
            "minimum_overall_units": 720,
            "minimum_confirmation_units": 180,
            "minimum_time_blocks": 24,
            "minimum_companies": 0,
            "minimum_confirmation_companies": 0,
            "minimum_calendar_quarters": 0,
            "minimum_year_over_year_comparisons": 0,
        },
        "robustness_checks": ["size_neutral", "confirmation_split"],
    }


def layer_payload(status: str = "neutral") -> dict:
    return {
        "status": status,
        "metrics": {"estimate": 0.01},
        "limitations": [],
    }


def valid_result_payload(method_status: str = "not_validated") -> dict:
    return {
        "study_id": "a_share_size_value",
        "specification_version": "v1",
        "spec_hash": "a" * 64,
        "code_commit": "b" * 40,
        "input_manifest_hashes": ["c" * 64],
        "sample_counts": {"overall_units": 800, "confirmation_units": 200},
        "exclusion_counts": {"non_positive_pe": 10},
        "method": layer_payload(method_status),
        "trend": layer_payload("weak_support"),
        "target": layer_payload("neutral"),
        "confirmation": ({"primary_estimate": 0.01} if method_status.startswith("validated_") else None),
        "limitations": [],
        "manual_review": "pending_review",
        "run_date": date(2026, 7, 15),
        "runtime_seconds": 1.25,
    }


def test_validation_spec_requires_exact_horizons_and_is_frozen():
    spec = ValidationSpec.model_validate(valid_spec_payload())

    assert spec.horizons == (10, 20, 30)
    with pytest.raises(ValidationError, match="frozen"):
        spec.study_id = "changed"

    wrong = valid_spec_payload()
    wrong["horizons"] = [5, 10, 20, 30]
    with pytest.raises(ValidationError, match="10/20/30"):
        ValidationSpec.model_validate(wrong)


def test_validation_spec_rejects_unknown_fields_and_blank_identifiers():
    extra = {**valid_spec_payload(), "score_weight": 0.5}
    with pytest.raises(ValidationError, match="extra_forbidden"):
        ValidationSpec.model_validate(extra)

    blank = {**valid_spec_payload(), "study_id": "  "}
    with pytest.raises(ValidationError, match="study_id"):
        ValidationSpec.model_validate(blank)


def test_positive_method_status_requires_confirmation_metrics():
    payload = valid_result_payload("validated_general")
    payload["confirmation"] = None

    with pytest.raises(ValidationError, match="confirmation"):
        ValidationResult.model_validate(payload)


def test_result_keeps_method_trend_and_target_statuses_independent():
    payload = valid_result_payload("not_validated")
    payload["target"] = layer_payload("strong_support")

    result = ValidationResult.model_validate(payload)

    assert result.method.status is MethodStatus.NOT_VALIDATED
    assert result.trend.status is RelevanceStatus.WEAK_SUPPORT
    assert result.target.status is RelevanceStatus.STRONG_SUPPORT


def test_result_hash_excludes_runtime_and_manual_review():
    first = ValidationResult.model_validate(valid_result_payload())
    changed = valid_result_payload()
    changed["runtime_seconds"] = 99.0
    changed["manual_review"] = "人工复核完成。"
    second = ValidationResult.model_validate(changed)

    assert first.result_hash == second.result_hash


def test_sample_sufficiency_rejects_negative_counts():
    with pytest.raises(ValidationError):
        SampleSufficiency(
            minimum_overall_units=-1,
            minimum_confirmation_units=0,
            minimum_time_blocks=0,
            minimum_companies=0,
            minimum_confirmation_companies=0,
            minimum_calendar_quarters=0,
            minimum_year_over_year_comparisons=0,
        )


def test_layer_result_requires_metrics_and_correct_status_axis():
    with pytest.raises(ValidationError, match="metrics"):
        LayerResult[RelevanceStatus](
            status=RelevanceStatus.NEUTRAL,
            metrics={},
            limitations=(),
        )


def test_real_registry_has_exact_ordered_studies_and_thirteen_migrations():
    registry = load_validation_registry(REAL_SPEC_PATH)

    assert tuple(study.study_id for study in registry.studies) == STUDY_IDS
    migration_ids = [
        migration_id
        for study in registry.studies
        for migration_id in study.migration_ids
    ]
    assert len(migration_ids) == 13
    assert len(set(migration_ids)) == 13
    assert set(migration_ids) == {
        "src_fama_french_1992",
        "src_liu_stambaugh_yuan_2019",
        "src_jegadeesh_titman_1993",
        "src_ball_brown_1968",
        "src_dechow_ge_schrand_2010",
        "src_sloan_1996",
        "src_piotroski_2000",
        "src_novy_marx_2013",
        "src_fama_fisher_jensen_roll_1969",
        "src_brown_warner_1985",
        "src_mackinlay_1997",
        "src_bernard_thomas_1989",
        "src_chan_2003",
    }


def test_real_registry_has_unique_knowledge_ids_and_known_datasets():
    registry = load_validation_registry(REAL_SPEC_PATH)

    knowledge_ids = [
        knowledge_id
        for study in registry.studies
        for knowledge_id in study.knowledge_ids
    ]
    assert len(knowledge_ids) == 9
    assert len(set(knowledge_ids)) == 9
    for study in registry.studies:
        assert all(ResearchDatasetId(value) for value in study.required_datasets)


def test_financial_study_preserves_both_company_and_yoy_sample_floors():
    registry = load_validation_registry(REAL_SPEC_PATH)
    study = next(
        item for item in registry.studies if item.study_id == "financial_quality_turnaround"
    )

    assert study.sufficiency.minimum_companies == 200
    assert study.sufficiency.minimum_confirmation_companies == 60
    assert study.sufficiency.minimum_year_over_year_comparisons == 2


def test_registry_hash_is_deterministic():
    first = load_validation_registry(REAL_SPEC_PATH)
    second = load_validation_registry(REAL_SPEC_PATH)

    assert len(first.registry_hash) == 64
    assert first.registry_hash == second.registry_hash


def test_registry_rejects_duplicate_study_id(tmp_path: Path):
    payload = yaml.safe_load(REAL_SPEC_PATH.read_text(encoding="utf-8"))
    payload["studies"][-1] = payload["studies"][0]
    path = tmp_path / "duplicate.yaml"
    path.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate study_id"):
        load_validation_registry(path)


def test_registry_rejects_unknown_dataset(tmp_path: Path):
    payload = yaml.safe_load(REAL_SPEC_PATH.read_text(encoding="utf-8"))
    payload["studies"][0]["required_datasets"].append("unknown_daily")
    path = tmp_path / "unknown-dataset.yaml"
    path.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")

    with pytest.raises(ValueError, match="unknown ResearchDatasetId"):
        load_validation_registry(path)


@pytest.mark.parametrize("forbidden_key", ["score", "weight", "buy", "recommend"])
def test_registry_rejects_scoring_or_recommendation_fields(
    tmp_path: Path,
    forbidden_key: str,
):
    payload = yaml.safe_load(REAL_SPEC_PATH.read_text(encoding="utf-8"))
    payload["studies"][0][forbidden_key] = True
    path = tmp_path / f"forbidden-{forbidden_key}.yaml"
    path.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")

    with pytest.raises(ValueError, match="forbidden field"):
        load_validation_registry(path)
