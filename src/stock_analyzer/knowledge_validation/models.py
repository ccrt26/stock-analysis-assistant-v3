from __future__ import annotations

from datetime import date
from enum import Enum
from hashlib import sha256
import json
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator


class MethodStatus(str, Enum):
    VALIDATED_GENERAL = "validated_general"
    VALIDATED_CONDITIONAL = "validated_conditional"
    NOT_VALIDATED = "not_validated"
    INSUFFICIENT_SAMPLE = "insufficient_sample"
    EXECUTION_FAILED = "execution_failed"


class RelevanceStatus(str, Enum):
    STRONG_SUPPORT = "strong_support"
    WEAK_SUPPORT = "weak_support"
    NEUTRAL = "neutral"
    ADVERSE = "adverse"
    INSUFFICIENT_SAMPLE = "insufficient_sample"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)

    @field_validator("*", mode="before")
    @classmethod
    def _reject_blank_strings(cls, value: Any, info) -> Any:
        if isinstance(value, str):
            cleaned = value.strip()
            if not cleaned:
                raise ValueError(f"{info.field_name} must not be blank")
            return cleaned
        if isinstance(value, (list, tuple)):
            for item in value:
                if isinstance(item, str) and not item.strip():
                    raise ValueError(f"{info.field_name} contains a blank item")
        return value


class SampleSufficiency(_FrozenModel):
    minimum_overall_units: int = Field(ge=0)
    minimum_confirmation_units: int = Field(ge=0)
    minimum_time_blocks: int = Field(ge=0)
    minimum_companies: int = Field(ge=0)
    minimum_confirmation_companies: int = Field(ge=0)
    minimum_calendar_quarters: int = Field(ge=0)
    minimum_year_over_year_comparisons: int = Field(ge=0)


class ValidationSpec(_FrozenModel):
    study_id: str
    specification_version: str
    knowledge_ids: tuple[str, ...]
    migration_ids: tuple[str, ...]
    theory_claim: str
    signal_definition: str
    primary_hypothesis: str
    primary_statistic: str
    horizons: tuple[int, ...]
    required_datasets: tuple[str, ...]
    sufficiency: SampleSufficiency
    robustness_checks: tuple[str, ...]

    @model_validator(mode="after")
    def _validate_spec(self) -> ValidationSpec:
        if self.horizons != (10, 20, 30):
            raise ValueError("validation horizons must be exactly 10/20/30")
        if not self.knowledge_ids:
            raise ValueError("knowledge_ids must not be empty")
        if not self.required_datasets:
            raise ValueError("required_datasets must not be empty")
        if not self.robustness_checks:
            raise ValueError("robustness_checks must not be empty")
        return self


StatusT = TypeVar("StatusT", bound=Enum)


class LayerResult(_FrozenModel, Generic[StatusT]):
    status: StatusT
    metrics: dict[str, float | int | str | bool | None]
    limitations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _require_metrics(self) -> LayerResult[StatusT]:
        if not self.metrics:
            raise ValueError("metrics must not be empty")
        return self


def _canonical_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


class ValidationResult(_FrozenModel):
    study_id: str
    specification_version: str
    spec_hash: str
    code_commit: str
    input_manifest_hashes: tuple[str, ...]
    sample_counts: dict[str, int]
    exclusion_counts: dict[str, int]
    method: LayerResult[MethodStatus]
    trend: LayerResult[RelevanceStatus]
    target: LayerResult[RelevanceStatus]
    confirmation: dict[str, float | int | str | bool | None] | None = None
    limitations: tuple[str, ...] = ()
    manual_review: str
    run_date: date
    runtime_seconds: float = Field(ge=0)

    @model_validator(mode="after")
    def _validate_positive_method_status(self) -> ValidationResult:
        if self.method.status in {
            MethodStatus.VALIDATED_GENERAL,
            MethodStatus.VALIDATED_CONDITIONAL,
        } and not self.confirmation:
            raise ValueError("validated method status requires confirmation metrics")
        return self

    @computed_field(return_type=str)
    @property
    def result_hash(self) -> str:
        payload = self.model_dump(
            mode="json",
            exclude={"manual_review", "runtime_seconds", "result_hash"},
        )
        return _canonical_hash(payload)


class StudySample(_FrozenModel):
    study_id: str
    input_manifest_hashes: tuple[str, ...]
    panel_row_count: int = Field(ge=0)
    exclusion_counts: dict[str, int] = Field(default_factory=dict)


class ValidationRegistry(_FrozenModel):
    schema_version: str
    studies: tuple[ValidationSpec, ...]
    registry_hash: str = ""


class ValidationRun(_FrozenModel):
    specification_registry_hash: str
    code_commit: str
    results: tuple[ValidationResult, ...]


__all__ = [
    "LayerResult",
    "MethodStatus",
    "RelevanceStatus",
    "SampleSufficiency",
    "StudySample",
    "ValidationRegistry",
    "ValidationResult",
    "ValidationRun",
    "ValidationSpec",
]
