from __future__ import annotations

from collections.abc import Mapping
from datetime import date
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from .governance_models import (
    KnowledgeEntry,
    KnowledgeRegistry,
    LegacyMigrationRegistry,
)


def _read_yaml_mapping(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"registry root must be a nonempty mapping: {path}")
    return dict(payload)


def _reject_duplicate_raw_ids(
    records: Any,
    *,
    field: str,
    record_type: str,
) -> None:
    if not isinstance(records, list):
        return
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, Mapping):
            continue
        value = record.get(field)
        if not isinstance(value, str):
            continue
        if value in seen:
            raise ValueError(f"duplicate {record_type} ID: {value}")
        seen.add(value)


def _validate_source_references(registry: KnowledgeRegistry) -> None:
    sources = {source.source_id: source for source in registry.sources}
    entries = {entry.knowledge_id: entry for entry in registry.entries}
    for entry in registry.entries:
        primary = sources.get(entry.primary_source_id)
        if primary is None:
            raise ValueError(
                f"unknown primary source {entry.primary_source_id} "
                f"for {entry.knowledge_id}"
            )
        if primary.grade is not entry.source_grade:
            raise ValueError(
                f"source grade mismatch for {entry.knowledge_id}: "
                f"entry={entry.source_grade.value}, source={primary.grade.value}"
            )
        for source_id in entry.supporting_source_ids:
            if source_id not in sources:
                raise ValueError(
                    f"unknown supporting source {source_id} for {entry.knowledge_id}"
                )
        for superseded_id in entry.supersedes:
            if superseded_id == entry.knowledge_id:
                raise ValueError(f"self-supersession: {entry.knowledge_id}")
            if superseded_id not in entries:
                raise ValueError(
                    f"unknown superseded knowledge ID {superseded_id} "
                    f"for {entry.knowledge_id}"
                )


def _reject_version_cycles(entries: dict[str, KnowledgeEntry]) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(knowledge_id: str) -> None:
        if knowledge_id in visiting:
            raise ValueError(f"version cycle includes {knowledge_id}")
        if knowledge_id in visited:
            return
        visiting.add(knowledge_id)
        for prior_id in entries[knowledge_id].supersedes:
            visit(prior_id)
        visiting.remove(knowledge_id)
        visited.add(knowledge_id)

    for knowledge_id in entries:
        visit(knowledge_id)


def _intervals_overlap(first: KnowledgeEntry, second: KnowledgeEntry) -> bool:
    first_start = first.effective_from or date.min
    first_end = first.effective_to or date.max
    second_start = second.effective_from or date.min
    second_end = second.effective_to or date.max
    return first_start <= second_end and second_start <= first_end


def _reject_overlapping_current_versions(
    entries: dict[str, KnowledgeEntry],
) -> None:
    neighbours: dict[str, set[str]] = {knowledge_id: set() for knowledge_id in entries}
    for entry in entries.values():
        for prior_id in entry.supersedes:
            neighbours[entry.knowledge_id].add(prior_id)
            neighbours[prior_id].add(entry.knowledge_id)

    remaining = set(entries)
    while remaining:
        start = remaining.pop()
        component = {start}
        frontier = [start]
        while frontier:
            current = frontier.pop()
            for neighbour in neighbours[current]:
                if neighbour not in component:
                    component.add(neighbour)
                    remaining.discard(neighbour)
                    frontier.append(neighbour)

        current_entries = sorted(
            (
                entries[knowledge_id]
                for knowledge_id in component
                if entries[knowledge_id].version_status == "current"
            ),
            key=lambda entry: entry.knowledge_id,
        )
        for index, first in enumerate(current_entries):
            for second in current_entries[index + 1 :]:
                if _intervals_overlap(first, second):
                    raise ValueError(
                        "overlapping effective intervals for current versions: "
                        f"{first.knowledge_id}, {second.knowledge_id}"
                    )


def _validate_version_graph(registry: KnowledgeRegistry) -> None:
    entries = {entry.knowledge_id: entry for entry in registry.entries}
    _reject_version_cycles(entries)
    _reject_overlapping_current_versions(entries)


def _registry_hash(registry: KnowledgeRegistry) -> str:
    payload = registry.model_dump(mode="json", exclude={"registry_hash"})
    payload["sources"] = sorted(
        payload["sources"], key=lambda source: source["source_id"]
    )
    payload["entries"] = sorted(
        payload["entries"], key=lambda entry: entry["knowledge_id"]
    )
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def load_knowledge_registry(path: Path) -> KnowledgeRegistry:
    payload = _read_yaml_mapping(path)
    _reject_duplicate_raw_ids(
        payload.get("sources"), field="source_id", record_type="source"
    )
    _reject_duplicate_raw_ids(
        payload.get("entries"), field="knowledge_id", record_type="knowledge"
    )
    registry = KnowledgeRegistry.model_validate(payload)
    _validate_source_references(registry)
    _validate_version_graph(registry)
    return registry.model_copy(update={"registry_hash": _registry_hash(registry)})


def load_legacy_migration(path: Path) -> LegacyMigrationRegistry:
    payload = _read_yaml_mapping(path)
    _reject_duplicate_raw_ids(
        payload.get("entries"),
        field="legacy_knowledge_id",
        record_type="legacy knowledge",
    )
    return LegacyMigrationRegistry.model_validate(payload)


__all__ = ["load_knowledge_registry", "load_legacy_migration"]
