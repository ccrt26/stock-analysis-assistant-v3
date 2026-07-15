from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any

import yaml

from stock_analyzer.data.research_contracts import ResearchDatasetId
from stock_analyzer.knowledge_validation.models import ValidationRegistry, ValidationSpec


STUDY_IDS = (
    "a_share_size_value",
    "a_share_momentum_reversal",
    "price_limit_t_plus_one",
    "a_share_factor_industry_momentum",
    "overseas_industry_momentum_method",
    "daily_event_study",
    "a_share_earnings_announcement_drift",
    "formal_announcement_price_reaction",
    "financial_quality_turnaround",
)

MIGRATION_IDS = frozenset(
    {
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
)

_FORBIDDEN_FIELD_PARTS = ("score", "weight", "buy", "recommend")


def _reject_forbidden_fields(value: Any, path: str = "root") -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = str(key).casefold()
            if any(part in normalized for part in _FORBIDDEN_FIELD_PARTS):
                raise ValueError(f"forbidden field at {path}.{key}")
            _reject_forbidden_fields(nested, f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_forbidden_fields(nested, f"{path}[{index}]")


def _canonical_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def load_validation_registry(path: Path) -> ValidationRegistry:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("validation registry must be a YAML mapping")
    _reject_forbidden_fields(payload)

    if set(payload) != {"schema_version", "studies"}:
        raise ValueError("validation registry must contain only schema_version and studies")
    raw_studies = payload.get("studies")
    if not isinstance(raw_studies, list) or not raw_studies:
        raise ValueError("validation registry studies must be a non-empty list")

    raw_study_ids = [
        raw.get("study_id") if isinstance(raw, dict) else None for raw in raw_studies
    ]
    duplicate_ids = sorted(
        {
            study_id
            for study_id in raw_study_ids
            if study_id is not None and raw_study_ids.count(study_id) > 1
        }
    )
    if duplicate_ids:
        raise ValueError(f"duplicate study_id: {', '.join(duplicate_ids)}")
    if tuple(raw_study_ids) != STUDY_IDS:
        raise ValueError("validation registry must contain the exact ordered nine studies")

    studies: list[ValidationSpec] = []
    for raw in raw_studies:
        if not isinstance(raw, dict):
            raise ValueError("each validation study must be a YAML mapping")
        for dataset_id in raw.get("required_datasets", []):
            try:
                ResearchDatasetId(dataset_id)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"unknown ResearchDatasetId {dataset_id!r} in {raw.get('study_id')!r}"
                ) from exc
        studies.append(ValidationSpec.model_validate(raw))

    knowledge_ids = [item for study in studies for item in study.knowledge_ids]
    if len(knowledge_ids) != 9 or len(set(knowledge_ids)) != len(knowledge_ids):
        raise ValueError("the nine studies must reference nine unique knowledge_ids")

    migration_ids = [item for study in studies for item in study.migration_ids]
    if len(migration_ids) != 13 or len(set(migration_ids)) != len(migration_ids):
        raise ValueError("the nine studies must reference thirteen unique migration_ids")
    if set(migration_ids) != MIGRATION_IDS:
        raise ValueError("migration_ids must match the thirteen revalidate records")

    canonical_payload = {
        "schema_version": payload["schema_version"],
        "studies": [study.model_dump(mode="json") for study in studies],
    }
    return ValidationRegistry(
        schema_version=payload["schema_version"],
        studies=tuple(studies),
        registry_hash=_canonical_hash(canonical_payload),
    )


__all__ = ["MIGRATION_IDS", "STUDY_IDS", "load_validation_registry"]
