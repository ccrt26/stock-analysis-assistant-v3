from __future__ import annotations

from collections.abc import Iterable
from datetime import date
import hashlib
import json
from pathlib import Path
from typing import Any, Literal

import pyarrow.parquet as pq
from pydantic import BaseModel, ConfigDict, Field

from stock_analyzer.analysis.hotspot_features import HOTSPOT_FORMULA_VERSION
from stock_analyzer.analysis.market_context_features import (
    MARKET_CONTEXT_FORMULA_VERSION,
)
from stock_analyzer.analysis.stock_context_features import (
    STOCK_CONTEXT_FORMULA_VERSION,
)
from stock_analyzer.storage.research_schema import connect_research_warehouse

from .governance_models import CapabilityStatus


_EXPECTED_DERIVED_FORMULAS = {
    "market_context": MARKET_CONTEXT_FORMULA_VERSION,
    "sector_hotspot": HOTSPOT_FORMULA_VERSION,
    "stock_trading_context": STOCK_CONTEXT_FORMULA_VERSION,
}
_READY_DERIVED_QUALITIES = {"complete", "complete_with_declared_gaps"}
_READY_FACT_QUALITIES = {"passed", "complete", "complete_with_declared_gaps"}


class CapabilityItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["fact", "derived"]
    name: str
    fields: tuple[str, ...]
    partition_count: int = Field(ge=0)
    row_count: int = Field(ge=0)
    formula_versions: tuple[str, ...] = ()
    quality_statuses: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    as_of_supported: bool
    structurally_ready: bool


class CapabilitySnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    analysis_date: date
    items: tuple[CapabilityItem, ...]
    snapshot_hash: str

    def lookup(self, kind: str, name: str) -> CapabilityItem | None:
        matches = [
            item for item in self.items if item.kind == kind and item.name == name
        ]
        if len(matches) > 1:
            raise ValueError(f"duplicate capability item: {kind}:{name}")
        return matches[0] if matches else None


class CapabilityAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    knowledge_id: str
    status: CapabilityStatus
    missing_requirements: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_manifest_path(root: Path, relative_path: Any) -> tuple[Path | None, str | None]:
    text = str(relative_path)
    candidate = (root / text).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None, f"manifest path escapes warehouse root: {text}"
    return candidate, None


def _inspect_parquet(
    root: Path,
    relative_path: Any,
    expected_sha256: Any,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    path, unsafe_reason = _safe_manifest_path(root, relative_path)
    if unsafe_reason is not None:
        return (), (unsafe_reason,)
    assert path is not None
    if not path.is_file():
        return (), (f"missing file: {relative_path}",)
    actual_sha256 = _sha256_file(path)
    if actual_sha256 != str(expected_sha256):
        return (), (f"sha256 mismatch: {relative_path}",)
    try:
        fields = tuple(sorted(pq.read_schema(path).names))
    except Exception as exc:
        return (), (f"unreadable parquet schema: {relative_path}: {exc}",)
    return fields, ()


def _field_intersection(field_sets: Iterable[tuple[str, ...]]) -> tuple[str, ...]:
    sets = [set(fields) for fields in field_sets]
    if not sets:
        return ()
    return tuple(sorted(set.intersection(*sets)))


def _json_text_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    decoded = value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            decoded = [value]
    if not isinstance(decoded, (list, tuple)):
        decoded = [decoded]
    return tuple(str(item).strip() for item in decoded if str(item).strip())


def _build_fact_items(warehouse_root: Path, facts: Any) -> list[CapabilityItem]:
    result: list[CapabilityItem] = []
    if facts.empty:
        return result
    for dataset_id, rows in facts.groupby("dataset_id", sort=True):
        schemas: list[tuple[str, ...]] = []
        limitations: list[str] = []
        qualities = tuple(sorted(set(rows["quality_status"].astype(str))))
        for _, row in rows.iterrows():
            fields, problems = _inspect_parquet(
                warehouse_root,
                row["relative_path"],
                row["file_sha256"],
            )
            if fields:
                schemas.append(fields)
            limitations.extend(problems)

        fields = _field_intersection(schemas)
        as_of_supported = bool(schemas) and "available_at" in fields
        if not as_of_supported:
            limitations.append("fact schema does not consistently contain available_at")
        unsupported_qualities = sorted(set(qualities) - _READY_FACT_QUALITIES)
        if unsupported_qualities:
            limitations.append(
                "fact quality is not ready: " + ", ".join(unsupported_qualities)
            )
        if "complete_with_declared_gaps" in qualities:
            limitations.append("fact data has declared coverage gaps")
        structurally_ready = (
            len(schemas) == len(rows)
            and as_of_supported
            and not unsupported_qualities
        )
        result.append(
            CapabilityItem(
                kind="fact",
                name=str(dataset_id),
                fields=fields,
                partition_count=len(rows),
                row_count=int(rows["row_count"].sum()),
                quality_statuses=qualities,
                limitations=tuple(dict.fromkeys(limitations)),
                as_of_supported=as_of_supported,
                structurally_ready=structurally_ready,
            )
        )
    return result


def _build_derived_items(
    warehouse_root: Path,
    derived: Any,
) -> list[CapabilityItem]:
    result: list[CapabilityItem] = []
    if derived.empty:
        return result
    for feature_set, candidates in derived.groupby("feature_set", sort=True):
        name = str(feature_set)
        expected_formula = _EXPECTED_DERIVED_FORMULAS.get(name)
        formula_versions = tuple(
            sorted(set(candidates["formula_version"].astype(str)))
        )
        selected = candidates
        limitations: list[str] = []
        if expected_formula is not None:
            selected = candidates[
                candidates["formula_version"].astype(str) == expected_formula
            ]
            if selected.empty:
                limitations.append(
                    f"expected formula {expected_formula} not found for {name}"
                )
                selected = candidates

        schemas: list[tuple[str, ...]] = []
        for _, row in selected.iterrows():
            fields, problems = _inspect_parquet(
                warehouse_root,
                row["relative_path"],
                row["file_sha256"],
            )
            if fields:
                schemas.append(fields)
            limitations.extend(problems)
            limitations.extend(_json_text_tuple(row["limitations_json"]))

        qualities = tuple(sorted(set(selected["quality_status"].astype(str))))
        unsupported_qualities = sorted(set(qualities) - _READY_DERIVED_QUALITIES)
        if unsupported_qualities:
            limitations.append(
                "derived quality is not ready: " + ", ".join(unsupported_qualities)
            )
        expected_present = expected_formula is None or expected_formula in formula_versions
        structurally_ready = (
            expected_present
            and len(schemas) == len(selected)
            and bool(schemas)
            and not unsupported_qualities
        )
        result.append(
            CapabilityItem(
                kind="derived",
                name=name,
                fields=_field_intersection(schemas),
                partition_count=len(selected),
                row_count=int(selected["row_count"].sum()),
                formula_versions=formula_versions,
                quality_statuses=qualities,
                limitations=tuple(dict.fromkeys(limitations)),
                as_of_supported=True,
                structurally_ready=structurally_ready,
            )
        )
    return result


def _snapshot_hash(analysis_date: date, items: tuple[CapabilityItem, ...]) -> str:
    payload = {
        "analysis_date": analysis_date.isoformat(),
        "items": [item.model_dump(mode="json") for item in items],
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _build_snapshot(
    warehouse_root: Path,
    analysis_date: date,
    facts: Any,
    derived: Any,
) -> CapabilitySnapshot:
    items = tuple(
        sorted(
            _build_fact_items(warehouse_root, facts)
            + _build_derived_items(warehouse_root, derived),
            key=lambda item: (item.kind, item.name),
        )
    )
    return CapabilitySnapshot(
        analysis_date=analysis_date,
        items=items,
        snapshot_hash=_snapshot_hash(analysis_date, items),
    )


def inspect_warehouse_capabilities(
    warehouse_root: Path,
    analysis_date: date,
) -> CapabilitySnapshot:
    root = Path(warehouse_root)
    db_path = root / "research.duckdb"
    with connect_research_warehouse(db_path, read_only=True) as connection:
        facts = connection.execute(
            "select * from research_fact_partitions "
            "order by dataset_id, partition_value"
        ).fetchdf()
        derived = connection.execute(
            """
            select * from research_derived_partitions
            where analysis_date = ?
            order by feature_set, formula_version
            """,
            [analysis_date],
        ).fetchdf()
    return _build_snapshot(root, analysis_date, facts, derived)


__all__ = [
    "CapabilityAssessment",
    "CapabilityItem",
    "CapabilitySnapshot",
    "inspect_warehouse_capabilities",
]
