from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from stock_analyzer.data.research_contracts import ResearchDatasetId
from stock_analyzer.storage.research_schema import connect_research_warehouse


CURRENT_GAP_STATUSES = {
    "legitimate_empty",
    "waiting_upstream",
    "permission_denied",
    "unsupported_optional",
    "provider_conflict",
    "failed",
    "unclassified_missing",
}


class ResearchGapRegistry:
    def __init__(self, duckdb_path: Path) -> None:
        self.duckdb_path = Path(duckdb_path)

    def record(
        self,
        dataset: ResearchDatasetId | str,
        partition: date | str,
        *,
        status: str,
        reason_category: str,
        source_name: str | None,
        source_endpoint: str | None,
        scope_key: str = "",
        impact_text: str = "",
        detail: dict[str, Any] | str | None = None,
        next_retry_at: datetime | None = None,
    ) -> str:
        if status not in CURRENT_GAP_STATUSES:
            raise ValueError(f"unsupported current gap status: {status}")
        dataset_id = ResearchDatasetId(dataset).value
        partition_value = (
            partition.isoformat() if isinstance(partition, date) else str(partition)
        )
        normalized_scope = str(scope_key or "")
        identity = f"{dataset_id}|{partition_value}|{normalized_scope}"
        gap_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        now = datetime.now(timezone.utc)
        detail_json = json.dumps(
            detail if isinstance(detail, dict) else {"message": detail},
            ensure_ascii=False,
            sort_keys=True,
        )
        with connect_research_warehouse(self.duckdb_path) as connection:
            connection.execute(
                """
                insert into research_data_gaps
                (gap_id, dataset_id, partition_value, scope_key, status,
                 reason_category, source_name, source_endpoint, first_seen_at,
                 last_checked_at, next_retry_at, resolved_at, impact_text,
                 detail_json)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, null, ?, ?)
                on conflict(dataset_id, partition_value, scope_key)
                do update set status = excluded.status,
                              reason_category = excluded.reason_category,
                              source_name = excluded.source_name,
                              source_endpoint = excluded.source_endpoint,
                              last_checked_at = excluded.last_checked_at,
                              next_retry_at = excluded.next_retry_at,
                              resolved_at = null,
                              impact_text = excluded.impact_text,
                              detail_json = excluded.detail_json
                """,
                [
                    gap_id,
                    dataset_id,
                    partition_value,
                    normalized_scope,
                    status,
                    reason_category,
                    source_name,
                    source_endpoint,
                    now,
                    now,
                    next_retry_at,
                    impact_text,
                    detail_json,
                ],
            )
        return gap_id

    def resolve_from_success(
        self,
        dataset: ResearchDatasetId | str,
        partition: date | str,
        *,
        source_name: str,
        source_endpoint: str,
        scope_key: str = "",
    ) -> int:
        dataset_id = ResearchDatasetId(dataset).value
        partition_value = (
            partition.isoformat() if isinstance(partition, date) else str(partition)
        )
        with connect_research_warehouse(self.duckdb_path) as connection:
            before = connection.execute(
                """
                select count(*) from research_data_gaps
                where dataset_id = ? and partition_value = ? and scope_key = ?
                  and source_name = ? and source_endpoint = ?
                  and status not in ('resolved', 'provider_conflict',
                                     'unsupported_optional')
                """,
                [
                    dataset_id,
                    partition_value,
                    str(scope_key or ""),
                    source_name,
                    source_endpoint,
                ],
            ).fetchone()[0]
            if before:
                connection.execute(
                    """
                    update research_data_gaps
                    set status = 'resolved', last_checked_at = now(),
                        next_retry_at = null, resolved_at = now()
                    where dataset_id = ? and partition_value = ? and scope_key = ?
                      and source_name = ? and source_endpoint = ?
                      and status not in ('resolved', 'provider_conflict',
                                         'unsupported_optional')
                    """,
                    [
                        dataset_id,
                        partition_value,
                        str(scope_key or ""),
                        source_name,
                        source_endpoint,
                    ],
                )
        return int(before)


    def has_active_gap(
        self,
        dataset: ResearchDatasetId | str,
        partition: date | str,
        *,
        scope_key: str = "",
    ) -> bool:
        dataset_id = ResearchDatasetId(dataset).value
        partition_value = (
            partition.isoformat() if isinstance(partition, date) else str(partition)
        )
        with connect_research_warehouse(
            self.duckdb_path, read_only=True
        ) as connection:
            row = connection.execute(
                """
                select 1 from research_data_gaps
                where dataset_id = ? and partition_value = ? and scope_key = ?
                  and status != 'resolved'
                limit 1
                """,
                [dataset_id, partition_value, str(scope_key or "")],
            ).fetchone()
        return row is not None

    def resolve_legacy_industry_gap_with_proxy(
        self,
        partition: date | str,
    ) -> int:
        """Close only legacy SW daily gaps replaced by the governed proxy."""

        partition_value = (
            partition.isoformat() if isinstance(partition, date) else str(partition)
        )
        resolved_at = datetime.now(timezone.utc)
        with connect_research_warehouse(self.duckdb_path) as connection:
            rows = connection.execute(
                """
                select gap_id, detail_json
                from research_data_gaps
                where dataset_id = 'industry_daily'
                  and partition_value = ? and scope_key = ''
                  and status in ('permission_denied', 'waiting_upstream',
                                 'failed', 'unclassified_missing')
                """,
                [partition_value],
            ).fetchall()
            for gap_id, raw_detail in rows:
                try:
                    detail = json.loads(str(raw_detail or "{}"))
                except json.JSONDecodeError:
                    detail = {"previous_detail": str(raw_detail)}
                detail.update(
                    {
                        "resolution_basis": "replacement_capability_ready",
                        "replacement_dataset_id": "industry_daily_proxy",
                        "replacement_source_name": "local_derived",
                        "replacement_source_endpoint": (
                            "sw_l1_free_float_proxy_v1"
                        ),
                        "replacement_resolved_at": resolved_at.isoformat(),
                    }
                )
                connection.execute(
                    """
                    update research_data_gaps
                    set status = 'resolved', last_checked_at = ?,
                        next_retry_at = null, resolved_at = ?, detail_json = ?
                    where gap_id = ?
                    """,
                    [
                        resolved_at,
                        resolved_at,
                        json.dumps(detail, ensure_ascii=False, sort_keys=True),
                        gap_id,
                    ],
                )
        return len(rows)


__all__ = ["CURRENT_GAP_STATUSES", "ResearchGapRegistry"]
