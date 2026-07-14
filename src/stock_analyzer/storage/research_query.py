from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from stock_analyzer.data.research_contracts import ResearchDatasetId, research_contract
from stock_analyzer.storage.research_warehouse import ResearchWarehouse


_PARTITION_VALUE_COLUMN = "__research_partition_value"
_SELECTED_REVISION_COLUMN = "__research_selected_revision"


@dataclass(frozen=True)
class MaterializedResearchSnapshot:
    """Exact resolved fact frames and the manifest calculated from those frames."""

    _frames: Mapping[ResearchDatasetId, pd.DataFrame]
    input_manifest: dict[str, Any]

    def frame(self, dataset_id: ResearchDatasetId | str) -> pd.DataFrame:
        dataset = ResearchDatasetId(dataset_id)
        if dataset not in self._frames:
            raise KeyError(f"dataset is not part of materialized snapshot: {dataset.value}")
        return self._frames[dataset].copy()


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
        current = self.warehouse.read_current(dataset)
        return _resolve_as_of(
            dataset,
            current,
            self.warehouse.revision_rows(dataset),
            cutoff,
        )

    def dataset_partitions_as_of(
        self,
        dataset_id: ResearchDatasetId | str,
        partition_values: Iterable[str],
        as_of: datetime,
    ) -> pd.DataFrame:
        dataset = ResearchDatasetId(dataset_id)
        cutoff = _utc(as_of)
        partitions = _partitions_at_cutoff(dataset, partition_values, cutoff)
        resolved, _ = self._partition_snapshot(
            dataset, partitions, cutoff
        )
        return _public_fact_frame(resolved)

    def input_manifest(
        self,
        dataset_partitions: Mapping[
            ResearchDatasetId | str,
            Iterable[str] | str,
        ],
        *,
        as_of: datetime,
    ) -> dict[str, Any]:
        return self.materialize_snapshot(
            dataset_partitions,
            as_of=as_of,
        ).input_manifest

    def materialize_snapshot(
        self,
        dataset_partitions: Mapping[
            ResearchDatasetId | str,
            Iterable[str] | str,
        ],
        *,
        as_of: datetime,
    ) -> MaterializedResearchSnapshot:
        """Resolve each requested fact once and hash those exact returned rows."""

        if not isinstance(dataset_partitions, Mapping):
            raise TypeError("dataset_partitions must be a mapping")

        cutoff = _utc(as_of)
        items: list[dict[str, Any]] = []
        frames: dict[ResearchDatasetId, pd.DataFrame] = {}
        requested = sorted(
            (
                ResearchDatasetId(dataset_id),
                _partitions_at_cutoff(
                    ResearchDatasetId(dataset_id),
                    partition_values,
                    cutoff,
                ),
            )
            for dataset_id, partition_values in dataset_partitions.items()
        )
        for dataset, partitions in requested:
            resolved, metadata = self._partition_snapshot(
                dataset, partitions, cutoff
            )
            frames[dataset] = _public_fact_frame(resolved)
            rows = {
                str(row["partition_value"]): row
                for row in metadata.to_dict(orient="records")
            }
            missing = sorted(set(partitions) - set(rows))
            if missing:
                raise ValueError(
                    f"missing fact partitions for {dataset.value}: {missing}"
                )
            empty_partition = resolved.iloc[0:0]
            resolved_partitions = (
                {}
                if resolved.empty
                else {
                    str(partition): group
                    for partition, group in resolved.groupby(
                        _PARTITION_VALUE_COLUMN, sort=False
                    )
                }
            )
            for partition in partitions:
                row = rows[partition]
                partition_frame = resolved_partitions.get(
                    partition, empty_partition
                )
                public_frame = _public_fact_frame(partition_frame)
                items.append(
                    {
                        "dataset": dataset.value,
                        "partition": partition,
                        "row_count": int(row["row_count"]),
                        "content_hash": str(row["content_hash"]),
                        "file_sha256": str(row["file_sha256"]),
                        "quality_status": str(row["quality_status"]),
                        "resolved_row_count": len(public_frame),
                        "resolved_content_hash": _fact_content_hash(public_frame),
                        "selected_revision_count": (
                            0
                            if partition_frame.empty
                            else int(
                                partition_frame[_SELECTED_REVISION_COLUMN]
                                .astype(bool)
                                .sum()
                            )
                        ),
                    }
                )
        items.sort(key=lambda item: (item["dataset"], item["partition"]))
        canonical_as_of = cutoff.isoformat()
        canonical = {
            "as_of": canonical_as_of,
            "partitions": items,
        }
        return MaterializedResearchSnapshot(
            _frames=frames,
            input_manifest={
                "as_of": canonical_as_of,
                "partitions": items,
                "input_manifest_hash": _stable_hash(canonical),
            },
        )

    def _partition_snapshot(
        self,
        dataset: ResearchDatasetId,
        partitions: tuple[str, ...],
        cutoff: datetime,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        current, metadata = self.warehouse.read_current_partitions_with_manifest(
            dataset,
            partitions,
        )
        current = current.copy()
        if not current.empty:
            current[_SELECTED_REVISION_COLUMN] = False
        _assert_unique_current_hashes(dataset, current)

        revisions: list[dict[str, Any]] = []
        for revision in self.warehouse.revision_rows(
            dataset,
            partition_values=partitions,
        ):
            prepared = dict(revision)
            payload = dict(revision["row_payload"])
            payload[_PARTITION_VALUE_COLUMN] = str(revision["partition_value"])
            payload[_SELECTED_REVISION_COLUMN] = True
            prepared["row_payload"] = payload
            revisions.append(prepared)

        resolved = _resolve_as_of(dataset, current, revisions, cutoff)
        _assert_unique_business_keys(dataset, resolved)
        return resolved, metadata

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


def _resolve_as_of(
    dataset: ResearchDatasetId,
    current: pd.DataFrame,
    revisions: Iterable[Mapping[str, Any]],
    cutoff: datetime,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    cutoff_stamp = pd.Timestamp(_utc(cutoff))
    if not current.empty:
        current_known = pd.to_datetime(
            current["available_at"], utc=True, errors="raise"
        ) <= cutoff_stamp
        if current_known.any():
            frames.append(current.loc[current_known].copy())

    revision_payloads = [dict(revision["row_payload"]) for revision in revisions]
    if revision_payloads:
        revision_frame = pd.DataFrame.from_records(revision_payloads)
        revision_known = pd.to_datetime(
            revision_frame["available_at"], utc=True, errors="raise"
        ) <= cutoff_stamp
        if revision_known.any():
            frames.append(revision_frame.loc[revision_known].copy())

    if not frames:
        return pd.DataFrame()
    contract = research_contract(dataset)
    candidates = pd.concat(frames, ignore_index=True, sort=False)
    candidates["__available_rank"] = pd.to_datetime(
        candidates["available_at"], utc=True, errors="raise"
    )
    revision_values = (
        candidates["revision_no"]
        if "revision_no" in candidates
        else pd.Series(1, index=candidates.index)
    )
    candidates["__revision_rank"] = pd.to_numeric(
        revision_values, errors="coerce"
    ).fillna(1)
    candidates["__candidate_order"] = range(len(candidates))
    best = (
        candidates.sort_values(
            [
                "business_key_hash",
                "__available_rank",
                "__revision_rank",
                "__candidate_order",
            ],
            ascending=[True, False, False, True],
            kind="mergesort",
        )
        .drop_duplicates("business_key_hash", keep="first")
        .drop(
            columns=[
                "__available_rank",
                "__revision_rank",
                "__candidate_order",
            ]
        )
    )
    return best.sort_values(list(contract.business_key)).reset_index(drop=True)


def _assert_unique_current_hashes(
    dataset: ResearchDatasetId,
    current: pd.DataFrame,
) -> None:
    if current.empty or "business_key_hash" not in current:
        return
    duplicates = current["business_key_hash"].duplicated(keep=False)
    if duplicates.any():
        raise ValueError(
            f"duplicate business key across selected partitions in "
            f"{dataset.value}: {int(duplicates.sum())} rows"
        )


def _assert_unique_business_keys(
    dataset: ResearchDatasetId,
    resolved: pd.DataFrame,
) -> None:
    if resolved.empty:
        return
    duplicates = resolved.duplicated(
        subset=list(research_contract(dataset).business_key),
        keep=False,
    )
    if duplicates.any():
        raise ValueError(
            f"duplicate business key across selected partitions in "
            f"{dataset.value}: {int(duplicates.sum())} rows"
        )


def _partitions_at_cutoff(
    dataset: ResearchDatasetId,
    partition_values: Iterable[str],
    cutoff: datetime,
) -> tuple[str, ...]:
    partitions = _normalized_partition_values(partition_values)
    if research_contract(dataset).partition_field != "trade_date":
        return partitions
    cutoff_date = pd.Timestamp(cutoff).tz_convert(
        ZoneInfo("Asia/Shanghai")
    ).date()
    selected: list[str] = []
    for partition in partitions:
        try:
            partition_date = date.fromisoformat(partition)
        except ValueError as error:
            raise ValueError(
                f"invalid trade-date partition for {dataset.value}: {partition}"
            ) from error
        if partition_date <= cutoff_date:
            selected.append(partition)
    return tuple(selected)


def _normalized_partition_values(
    partition_values: Iterable[str] | str,
) -> tuple[str, ...]:
    if isinstance(partition_values, str):
        partition_values = (partition_values,)
    return tuple(sorted({str(value) for value in partition_values}))


def _stable_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _fact_content_hash(frame: pd.DataFrame) -> str:
    if frame.empty:
        return _stable_hash([])
    revision = (
        pd.to_numeric(frame["revision_no"], errors="coerce").fillna(1)
        if "revision_no" in frame
        else pd.Series(1, index=frame.index)
    )
    selected = pd.DataFrame(
        {
            "business_key_hash": frame["business_key_hash"].astype(str),
            "payload_hash": frame["payload_hash"].astype(str),
            "revision_no": revision.astype(int),
        }
    ).sort_values(
        ["business_key_hash", "payload_hash", "revision_no"],
        kind="mergesort",
    )
    rows = list(selected.itertuples(index=False, name=None))
    return _stable_hash(rows)


def _public_fact_frame(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.drop(
        columns=[_PARTITION_VALUE_COLUMN, _SELECTED_REVISION_COLUMN],
        errors="ignore",
    ).reset_index(drop=True)


def _utc(value: Any) -> datetime:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp.to_pydatetime()


__all__ = ["MaterializedResearchSnapshot", "ResearchQuery"]
