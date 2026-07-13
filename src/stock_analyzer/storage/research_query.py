from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd

from stock_analyzer.data.research_contracts import ResearchDatasetId, research_contract
from stock_analyzer.storage.research_warehouse import ResearchWarehouse


class ResearchQuery:
    def __init__(self, warehouse: ResearchWarehouse) -> None:
        self.warehouse = warehouse

    def dataset_as_of(
        self,
        dataset_id: ResearchDatasetId | str,
        as_of: datetime,
    ) -> pd.DataFrame:
        dataset = ResearchDatasetId(dataset_id)
        cutoff = _utc(as_of)
        candidates: list[dict[str, Any]] = []

        current = self.warehouse.read_current(dataset)
        if not current.empty:
            for row in current.to_dict(orient="records"):
                if _utc(row["available_at"]) <= cutoff:
                    candidates.append(row)

        for revision in self.warehouse.revision_rows(dataset):
            row = dict(revision["row_payload"])
            if _utc(row["available_at"]) <= cutoff:
                candidates.append(row)

        if not candidates:
            return pd.DataFrame()
        contract = research_contract(dataset)
        best: dict[str, dict[str, Any]] = {}
        for row in candidates:
            key_hash = str(row["business_key_hash"])
            previous = best.get(key_hash)
            rank = (_utc(row["available_at"]), int(row.get("revision_no", 1)))
            if previous is None:
                best[key_hash] = row
                continue
            previous_rank = (
                _utc(previous["available_at"]),
                int(previous.get("revision_no", 1)),
            )
            if rank > previous_rank:
                best[key_hash] = row
        return pd.DataFrame(best.values()).sort_values(
            list(contract.business_key)
        ).reset_index(drop=True)


def _utc(value: Any) -> datetime:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp.to_pydatetime()


__all__ = ["ResearchQuery"]
