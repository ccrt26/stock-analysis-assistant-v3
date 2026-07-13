from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

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

    def controlled_themes_as_of(self, as_of: datetime) -> pd.DataFrame:
        catalog = self.dataset_as_of(ResearchDatasetId.THEME_CATALOG, as_of)
        members = self.dataset_as_of(ResearchDatasetId.THEME_MEMBER, as_of)
        daily = self.dataset_as_of(ResearchDatasetId.THEME_DAILY, as_of)
        if catalog.empty or members.empty or daily.empty:
            return catalog.iloc[0:0].copy()

        cutoff_date = pd.Timestamp(_utc(as_of)).tz_convert(
            ZoneInfo("Asia/Shanghai")
        ).tz_localize(None).normalize()
        members = members.copy()
        members["valid_from"] = pd.to_datetime(members["valid_from"])
        valid_to = pd.to_datetime(members["valid_to"], errors="coerce")
        members = members[
            (members["valid_from"] <= cutoff_date)
            & (valid_to.isna() | (valid_to >= cutoff_date))
        ]
        daily = daily.copy()
        daily["trade_date"] = pd.to_datetime(daily["trade_date"])
        daily = daily[daily["trade_date"] <= cutoff_date]

        member_counts = members.groupby("theme_code")["ts_code"].nunique()
        latest_dates = daily.groupby("theme_code")["trade_date"].max()
        usable_codes = set(member_counts.index.astype(str)) & set(
            latest_dates.index.astype(str)
        )
        result = catalog[
            catalog["theme_code"].astype(str).isin(usable_codes)
        ].copy()
        if result.empty:
            return result
        result["active_member_count"] = result["theme_code"].astype(str).map(
            member_counts
        )
        result["latest_trade_date"] = result["theme_code"].astype(str).map(
            latest_dates
        )
        return result.sort_values("theme_code").reset_index(drop=True)


def _utc(value: Any) -> datetime:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp.to_pydatetime()


__all__ = ["ResearchQuery"]
