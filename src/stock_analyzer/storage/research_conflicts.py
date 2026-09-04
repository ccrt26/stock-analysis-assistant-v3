from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from stock_analyzer.data.research_contracts import ResearchDatasetId, research_contract
from stock_analyzer.storage.research_gap_registry import ResearchGapRegistry
from stock_analyzer.storage.research_schema import connect_research_warehouse


_GOVERNANCE_FIELDS = {
    "source_name", "source_endpoint", "source_record_id", "source_updated_at",
    "available_at", "availability_precision", "ingested_at",
    "ingestion_run_id", "payload_hash", "business_key_hash",
    "quality_status", "revision_no",
}


class ResearchConflictRegistry:
    def __init__(self, duckdb_path: Path) -> None:
        self.duckdb_path = Path(duckdb_path)
        self.gaps = ResearchGapRegistry(self.duckdb_path)

    def record_variants(
        self,
        dataset: ResearchDatasetId | str,
        partition: date | str,
        *,
        business_key: tuple[str, ...],
        rows: Iterable[dict[str, Any]],
        source_name: str,
        source_endpoint: str,
        observed_at: datetime | None = None,
    ) -> str:
        dataset_id = ResearchDatasetId(dataset)
        partition_value = (
            partition.isoformat() if isinstance(partition, date) else str(partition)
        )
        fields = research_contract(dataset_id).business_key
        if len(fields) != len(business_key):
            raise ValueError("business key value count does not match contract")
        key_payload = {
            field: _json_safe(value)
            for field, value in zip(fields, business_key, strict=True)
        }
        key_hash = _stable_hash(key_payload)
        seen_at = _optional_timestamp(observed_at or datetime.now(timezone.utc))
        candidates = {_payload_hash(row): row for row in rows}
        if len(candidates) < 2:
            raise ValueError("a provider conflict requires at least two payloads")
        with connect_research_warehouse(self.duckdb_path) as connection:
            history = [
                (conflict_id, payload, _optional_timestamp(first),
                 _optional_timestamp(resolved), status)
                for conflict_id, payload, first, resolved, status in connection.execute(
                    "select conflict_id, payload_hash, first_seen_at::varchar, "
                    "resolved_at::varchar, status from research_fact_conflicts "
                    "where dataset_id = ? and business_key_hash = ?",
                    [dataset_id.value, key_hash],
                ).fetchall()
            ]
            closed_payloads = {
                payload for _, payload, first, resolved, _ in history
                if resolved is not None and first <= seen_at < resolved
            }
            if closed_payloads:
                if set(candidates) <= closed_payloads:
                    return key_hash  # Replay of an already closed observation.
                raise ValueError("outdated conflict observation has unknown payloads")
            last_resolution = max(
                (resolved for _, _, _, resolved, _ in history if resolved is not None),
                default=None,
            )
            active = {
                payload: (conflict_id, first)
                for conflict_id, payload, first, _, status in history
                if status == "unresolved"
            }
            if (
                last_resolution is not None and seen_at <= last_resolution
            ) or (active and seen_at < min(first for _, first in active.values())):
                raise ValueError("outdated conflict observation cannot open a new interval")
            for payload_hash, row in candidates.items():
                if payload_hash in active:
                    connection.execute(
                        "update research_fact_conflicts "
                        "set last_seen_at = greatest(last_seen_at, ?) "
                        "where conflict_id = ?",
                        [seen_at, active[payload_hash][0]],
                    )
                    continue
                conflict_id = _stable_hash(
                    {
                        "dataset_id": dataset_id.value,
                        "business_key_hash": key_hash,
                        "payload_hash": payload_hash,
                        "first_seen_at": seen_at.isoformat(),
                    }
                )
                connection.execute(
                    """
                    insert into research_fact_conflicts
                    (conflict_id, dataset_id, partition_value,
                     business_key_hash, business_key_json, payload_hash,
                     row_payload, source_name, source_endpoint, available_at,
                     first_seen_at, last_seen_at, status, resolved_at,
                     resolution_basis)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'unresolved',
                            null, null)
                    """,
                    [
                        conflict_id,
                        dataset_id.value,
                        partition_value,
                        key_hash,
                        json.dumps(key_payload, ensure_ascii=False, sort_keys=True),
                        payload_hash,
                        json.dumps(_json_safe(row), ensure_ascii=False, sort_keys=True),
                        source_name,
                        source_endpoint,
                        _optional_timestamp(row.get("available_at")),
                        seen_at,
                        seen_at,
                    ],
                )
        self.gaps.record(
            dataset_id,
            partition_value,
            scope_key=key_hash,
            status="provider_conflict",
            reason_category="same_available_at_multiple_payloads",
            source_name=source_name,
            source_endpoint=source_endpoint,
            impact_text="该财务业务键在冲突解决前不能作为确定事实使用。",
            detail={"business_key": key_payload, "variant_count": len(candidates)},
        )
        return key_hash

    def resolve(
        self,
        dataset: ResearchDatasetId | str,
        *,
        business_key: tuple[str, ...],
        resolved_at: datetime,
        resolution_basis: dict[str, Any],
    ) -> int:
        dataset_id = ResearchDatasetId(dataset)
        fields = research_contract(dataset_id).business_key
        key_hash = _stable_hash(
            {
                field: _json_safe(value)
                for field, value in zip(fields, business_key, strict=True)
            }
        )
        basis_json = json.dumps(
            _json_safe(resolution_basis), ensure_ascii=False, sort_keys=True
        )
        with connect_research_warehouse(self.duckdb_path) as connection:
            count, last_seen = connection.execute(
                """
                select count(*), max(last_seen_at)::varchar
                from research_fact_conflicts
                where dataset_id = ? and business_key_hash = ?
                  and status = 'unresolved'
                """,
                [dataset_id.value, key_hash],
            ).fetchone()
            if count:
                resolved_at = _optional_timestamp(resolved_at)
                if resolved_at < _optional_timestamp(last_seen):
                    raise ValueError("conflict resolution precedes the latest observation")
                connection.execute(
                    """
                    update research_fact_conflicts
                    set status = 'resolved', resolved_at = ?,
                        resolution_basis = ?
                    where dataset_id = ? and business_key_hash = ?
                      and status = 'unresolved'
                    """,
                    [resolved_at, basis_json, dataset_id.value, key_hash],
                )
                connection.execute(
                    """
                    update research_data_gaps
                    set status = 'resolved', resolved_at = ?,
                        last_checked_at = ?, next_retry_at = null,
                        detail_json = ?
                    where dataset_id = ? and scope_key = ?
                      and status = 'provider_conflict'
                    """,
                    [
                        resolved_at, resolved_at, basis_json,
                        dataset_id.value, key_hash,
                    ],
                )
        return int(count)


def blocked_conflict_hashes(
    duckdb_path: Path,
    dataset: ResearchDatasetId | str,
    as_of: datetime,
) -> set[str]:
    with connect_research_warehouse(duckdb_path, read_only=True) as connection:
        rows = connection.execute(
            """
            select distinct business_key_hash
            from research_fact_conflicts
            where dataset_id = ? and first_seen_at <= ?
              and (resolved_at is null or resolved_at > ?)
            """,
            [ResearchDatasetId(dataset).value, as_of, as_of],
        ).fetchall()
    return {str(row[0]) for row in rows}


def _payload_hash(row: dict[str, Any]) -> str:
    return _stable_hash(
        {
            key: _json_safe(value)
            for key, value in row.items()
            if key not in _GOVERNANCE_FIELDS
        }
    )


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def _optional_timestamp(value: Any) -> datetime | None:
    if value is None or pd.isna(value):
        return None
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize("UTC")
    return stamp.tz_convert("UTC").to_pydatetime()


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (date, datetime, pd.Timestamp)):
        return pd.Timestamp(value).isoformat()
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return _json_safe(value.item())
    return str(value)


__all__ = ["ResearchConflictRegistry", "blocked_conflict_hashes"]
