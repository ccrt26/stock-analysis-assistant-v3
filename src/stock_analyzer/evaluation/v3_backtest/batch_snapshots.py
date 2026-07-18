"""Exact multi-origin, read-only formation snapshots for the V3 backtest.

The source warehouse is scanned into detached in-memory tables once per fact
dataset.  Per-origin resolution still goes through :class:`ResearchQuery`, so
availability, revision and partition-cutoff semantics remain identical to the
strict single-origin path.  Only immutable snapshot artifacts are written,
and they are written below the explicitly frozen external backtest root.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime
from numbers import Integral, Real
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd
import pyarrow as pa
import pyarrow.ipc as pa_ipc
import pyarrow.parquet as pa_parquet

from stock_analyzer.analysis.hotspot_features import (
    HOTSPOT_FORMULA_VERSION,
    compute_hotspot_features,
)
from stock_analyzer.analysis.market_context_features import (
    MARKET_CONTEXT_FORMULA_VERSION,
    compute_market_context_features,
)
from stock_analyzer.analysis.stock_context_features import (
    STOCK_CONTEXT_FORMULA_VERSION,
    compute_stock_context_features,
)
from stock_analyzer.data.research_contracts import (
    ResearchDatasetId,
    research_contract,
)
from stock_analyzer.evaluation.v3_backtest.snapshots import (
    FormationFactView,
    FormationFeatureView,
    FormationSnapshot,
    _materialize_fact_view,
    formation_cutoff,
)
from stock_analyzer.ops import research_features as production_features
from stock_analyzer.storage.research_query import ResearchQuery
from stock_analyzer.storage.research_warehouse import ResearchWarehouse


MAX_CACHE_FILE_BYTES = int(3.5 * 1024**3)
_PARTITION_COLUMN = "__research_partition_value"
_FEATURE_ORDER = (
    "market_context",
    "sector_hotspot",
    "stock_trading_context",
)
_FEATURE_KEYS = {
    "market_context": ("analysis_date",),
    "sector_hotspot": ("analysis_date", "group_type", "group_code"),
    "stock_trading_context": ("analysis_date", "ts_code"),
}
_FORMULA_VERSIONS = {
    "market_context": MARKET_CONTEXT_FORMULA_VERSION,
    "sector_hotspot": HOTSPOT_FORMULA_VERSION,
    "stock_trading_context": STOCK_CONTEXT_FORMULA_VERSION,
}
_SNAPSHOT_IDENTITY_FIELDS = (
    "analysis_date",
    "as_of",
    "facts_manifest",
    "fact_manifest_hashes",
    "formula_versions",
    "limitations",
    "cache_key",
    "tables",
)
_PRODUCTION_DATASETS = (
    ResearchDatasetId.TRADE_CALENDAR,
    ResearchDatasetId.SECURITY_MASTER,
    ResearchDatasetId.EQUITY_DAILY,
    ResearchDatasetId.ADJ_FACTOR,
    ResearchDatasetId.DAILY_BASIC,
    ResearchDatasetId.STOCK_LIMIT,
    ResearchDatasetId.INDEX_DAILY,
    ResearchDatasetId.INDUSTRY_CATALOG,
    ResearchDatasetId.INDUSTRY_MEMBER,
    ResearchDatasetId.INDUSTRY_DAILY,
    ResearchDatasetId.THEME_CATALOG,
    ResearchDatasetId.THEME_MEMBER,
    ResearchDatasetId.THEME_DAILY,
    ResearchDatasetId.MINUTE_BAR,
)


FactPlan = Mapping[ResearchDatasetId | str, Iterable[str] | str]
FactPlanFactory = Callable[[date], FactPlan]
FeatureBuilder = Callable[[ResearchQuery, date, datetime], "BatchFeatureResult"]


@dataclass(frozen=True, slots=True)
class BatchFeatureResult:
    """Detached output of the three governed production formula calls."""

    frames: Mapping[str, pd.DataFrame]
    fact_manifest_hashes: Mapping[str, str]
    formula_versions: Mapping[str, str]
    limitations: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BatchSnapshotReceipt:
    operational_dates: tuple[date, ...]
    root: Path
    content_hashes: tuple[tuple[str, str], ...]
    source_fact_reads: tuple[tuple[str, int], ...]
    cache_bytes: int


@dataclass(frozen=True, slots=True)
class ExactTableReceipt:
    table: str
    reference_rows: int
    candidate_rows: int
    reference_columns: tuple[str, ...]
    candidate_columns: tuple[str, ...]
    reference_schema: str
    candidate_schema: str
    reference_business_key_hash: str
    candidate_business_key_hash: str
    reference_content_hash: str
    candidate_content_hash: str
    exact_equal: bool


@dataclass(frozen=True, slots=True)
class ExactParityReceipt:
    origin: date
    exact_equal: bool
    mismatches: tuple[str, ...]
    tables: tuple[ExactTableReceipt, ...]
    reference_cache_key: str
    candidate_cache_key: str


@dataclass(frozen=True, slots=True)
class _FeaturePlans:
    price_dates: tuple[str, ...]
    context_dates: tuple[str, ...]
    market: Mapping[ResearchDatasetId, tuple[str, ...]]
    sector: Mapping[ResearchDatasetId, tuple[str, ...]]
    stock: Mapping[ResearchDatasetId, tuple[str, ...]]
    industry_daily_gap: bool
    theme_daily_gap: bool


class _InMemoryWarehouse:
    """ResearchQuery warehouse surface backed only by detached memory tables."""

    def __init__(
        self,
        source_root: Path,
        manifests: Mapping[ResearchDatasetId, pd.DataFrame],
        current: Mapping[ResearchDatasetId, pd.DataFrame],
        revisions: Mapping[ResearchDatasetId, Sequence[Mapping[str, Any]]],
        partition_columns: Mapping[
            ResearchDatasetId, Mapping[str, tuple[str, ...]]
        ],
    ) -> None:
        self.root = Path(source_root)
        # Loaders already return detached frames.  Keep those sole in-memory
        # owners and copy only at the ResearchQuery call boundary; otherwise a
        # five-year valuation preload is needlessly doubled at peak memory.
        self._manifests = dict(manifests)
        self._current = dict(current)
        self._revisions = {
            dataset: tuple(_copy_revision(row) for row in rows)
            for dataset, rows in revisions.items()
        }
        self._partition_columns = {
            dataset: dict(columns) for dataset, columns in partition_columns.items()
        }

    def partition_manifest(
        self,
        dataset_id: ResearchDatasetId | str,
        *,
        partition_values: Iterable[str] | None = None,
    ) -> pd.DataFrame:
        dataset = ResearchDatasetId(dataset_id)
        frame = self._manifests.get(dataset, pd.DataFrame()).copy(deep=True)
        if partition_values is None or frame.empty:
            return frame.reset_index(drop=True)
        requested = {str(value) for value in partition_values}
        return frame.loc[
            frame["partition_value"].astype(str).isin(requested)
        ].reset_index(drop=True)

    def read_current_partitions_with_manifest(
        self,
        dataset_id: ResearchDatasetId | str,
        partition_values: Iterable[str],
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        dataset = ResearchDatasetId(dataset_id)
        partitions = tuple(sorted({str(value) for value in partition_values}))
        metadata = self.partition_manifest(dataset, partition_values=partitions)
        if not partitions:
            return pd.DataFrame(), metadata
        present = set(metadata.get("partition_value", pd.Series(dtype=str)).astype(str))
        missing = sorted(set(partitions) - present)
        if missing:
            raise ValueError(f"missing fact partitions for {dataset.value}: {missing}")
        frame = self._current.get(dataset, pd.DataFrame())
        if frame.empty:
            return frame, metadata
        selected = frame[_PARTITION_COLUMN].astype(str).isin(partitions)
        requested_columns: list[str] = []
        physical = self._partition_columns.get(dataset, {})
        for partition in partitions:
            if partition not in physical:
                raise ValueError(
                    f"physical fact schema is missing for "
                    f"{dataset.value}:{partition}"
                )
            for column in physical[partition]:
                if column not in requested_columns:
                    requested_columns.append(column)
        return frame.loc[
            selected, [*requested_columns, _PARTITION_COLUMN]
        ].reset_index(drop=True), metadata

    def revision_rows(
        self,
        dataset_id: ResearchDatasetId | str,
        *,
        partition_values: Iterable[str] | None = None,
    ) -> list[dict[str, Any]]:
        dataset = ResearchDatasetId(dataset_id)
        rows = self._revisions.get(dataset, ())
        selected = None if partition_values is None else {
            str(value) for value in partition_values
        }
        return [
            _copy_revision(row)
            for row in rows
            if selected is None or str(row["partition_value"]) in selected
        ]


class BatchSnapshotStore:
    """Prepare exact multi-origin snapshots from one read-only fact preload."""

    def __init__(
        self,
        warehouse: ResearchWarehouse,
        *,
        fact_plan: FactPlan | FactPlanFactory,
        feature_builder: FeatureBuilder | None = None,
    ) -> None:
        if not hasattr(warehouse, "read_current_partitions_with_manifest"):
            raise TypeError("warehouse must expose the read-only research fact API")
        if not isinstance(fact_plan, Mapping) and not callable(fact_plan):
            raise TypeError("fact_plan must be a mapping or an origin factory")
        self._warehouse = warehouse
        self._fact_plan = fact_plan
        self._feature_builder = feature_builder
        self._snapshots: dict[date, FormationSnapshot] = {}
        self._content_hashes: dict[date, str] = {}
        self._output_root: Path | None = None
        self._receipt: BatchSnapshotReceipt | None = None
        self._prepared_identity: tuple[tuple[date, ...], Path] | None = None

    def prepare(
        self,
        operational_dates: Iterable[date],
        root: Path,
    ) -> BatchSnapshotReceipt:
        origins = _normalize_origins(operational_dates)
        output_root = _validated_output_root(root)
        _validate_source_separation(Path(self._warehouse.root), output_root)
        identity = (origins, output_root)
        if self._prepared_identity == identity and self._receipt is not None:
            for origin in origins:
                _load_snapshot(
                    output_root,
                    self._content_hashes[origin],
                    expected_origin=origin,
                )
            return self._receipt

        output_root.mkdir(parents=True, exist_ok=True)
        snapshots_root = output_root / "cache" / "snapshots"
        snapshots_root.mkdir(parents=True, exist_ok=True)
        (snapshots_root / "by-date").mkdir(parents=True, exist_ok=True)

        fact_plans = {
            origin: _normalize_fact_plan(
                self._fact_plan(origin) if callable(self._fact_plan) else self._fact_plan
            )
            for origin in origins
        }
        inventory = _load_manifest_inventory(
            self._warehouse,
            fact_plans,
            include_production=self._feature_builder is None,
        )
        union = _union_fact_plans(fact_plans.values())
        feature_plans: dict[date, _FeaturePlans] = {}
        preloaded: _InMemoryWarehouse | None = None
        read_counts: dict[ResearchDatasetId, int] = {}

        if self._feature_builder is None:
            calendar_union = _calendar_partitions_from_inventory(
                inventory,
                max(origins),
            )
            preloaded = _preload_union(
                self._warehouse,
                inventory,
                {ResearchDatasetId.TRADE_CALENDAR: calendar_union},
                read_counts,
            )
            calendar_query = ResearchQuery(preloaded)
            for origin in origins:
                feature_plan = _build_feature_plans(
                    preloaded,
                    calendar_query,
                    origin,
                    inventory,
                )
                feature_plans[origin] = feature_plan
                _merge_union(union, feature_plan.market)
                _merge_union(union, feature_plan.sector)
                _merge_union(union, feature_plan.stock)

        memory = _preload_union(
            self._warehouse,
            inventory,
            union,
            read_counts,
            existing=preloaded,
        )
        query = ResearchQuery(memory)
        prepared_hashes: dict[date, str] = {}
        content_hashes: list[tuple[str, str]] = []
        cache_bytes = 0
        for origin in origins:
            cutoff = formation_cutoff(origin)
            facts = _materialize_fact_view(
                query,
                fact_plans[origin],
                origin=origin,
                cutoff=cutoff,
            )
            result = (
                self._feature_builder(query, origin, cutoff)
                if self._feature_builder is not None
                else _compute_production_features(
                    query,
                    origin,
                    feature_plans[origin],
                )
            )
            snapshot = _assemble_snapshot(origin, cutoff, facts, result)
            content_hash, written = _persist_snapshot(snapshot, output_root)
            prepared_hashes[origin] = content_hash
            content_hashes.append((origin.isoformat(), content_hash))
            cache_bytes += written

        receipt = BatchSnapshotReceipt(
            operational_dates=origins,
            root=output_root,
            content_hashes=tuple(content_hashes),
            source_fact_reads=tuple(
                (dataset.value, count)
                for dataset, count in sorted(
                    read_counts.items(), key=lambda item: item[0].value
                )
            ),
            cache_bytes=cache_bytes,
        )
        _atomic_write_json(
            snapshots_root / "batch-receipt.json",
            _jsonable(receipt),
        )
        self._snapshots = {}
        self._content_hashes = prepared_hashes
        self._output_root = output_root
        self._receipt = receipt
        self._prepared_identity = identity
        return receipt

    def snapshot(self, origin: date) -> FormationSnapshot:
        if self._receipt is None:
            raise RuntimeError("prepare must complete before requesting a snapshot")
        normalized = _as_origin(origin)
        if normalized not in self._content_hashes or self._output_root is None:
            raise KeyError(f"origin was not prepared: {normalized.isoformat()}")
        return _load_snapshot(
            self._output_root,
            self._content_hashes[normalized],
            expected_origin=normalized,
        )


def materialize_readonly_reference_snapshot(
    warehouse: ResearchWarehouse,
    origin: date,
    *,
    fact_plan: FactPlan,
) -> FormationSnapshot:
    """Run one strict origin directly against the source without any writes.

    This is the parity reference path.  It intentionally performs independent
    ResearchQuery scans for the origin and invokes the same production formula
    functions, but never constructs a writable warehouse or derived store.
    """

    normalized_origin = _as_origin(origin)
    normalized_plan = _normalize_fact_plan(fact_plan)
    inventory = _load_manifest_inventory(
        warehouse,
        {normalized_origin: normalized_plan},
        include_production=True,
    )
    query = ResearchQuery(warehouse)
    plans = _build_feature_plans(warehouse, query, normalized_origin, inventory)
    cutoff = formation_cutoff(normalized_origin)
    facts = _materialize_fact_view(
        query,
        normalized_plan,
        origin=normalized_origin,
        cutoff=cutoff,
    )
    features = _compute_production_features(query, normalized_origin, plans)
    return _assemble_snapshot(normalized_origin, cutoff, facts, features)


def compare_snapshot_exact(
    reference: FormationSnapshot,
    candidate: FormationSnapshot,
) -> ExactParityReceipt:
    """Compare every public snapshot value through canonical Arrow IPC bytes."""

    if not isinstance(reference, FormationSnapshot) or not isinstance(
        candidate, FormationSnapshot
    ):
        raise TypeError("reference and candidate must be FormationSnapshot values")
    mismatches: list[str] = []
    scalar_checks = (
        ("analysis_date", reference.analysis_date, candidate.analysis_date),
        ("as_of", reference.as_of, candidate.as_of),
        ("facts_manifest", reference.facts.manifest, candidate.facts.manifest),
        (
            "fact_manifest_hashes",
            reference.fact_manifest_hashes,
            candidate.fact_manifest_hashes,
        ),
        ("formula_versions", reference.formula_versions, candidate.formula_versions),
        ("market_rows", reference.market_rows, candidate.market_rows),
        ("sector_rows", reference.sector_rows, candidate.sector_rows),
        ("stock_rows", reference.stock_rows, candidate.stock_rows),
        ("limitations", reference.limitations, candidate.limitations),
        ("cache_key", reference.cache_key, candidate.cache_key),
    )
    for label, left, right in scalar_checks:
        if left != right:
            mismatches.append(label)

    tables: list[ExactTableReceipt] = []
    reference_datasets = _snapshot_fact_datasets(reference)
    candidate_datasets = _snapshot_fact_datasets(candidate)
    if reference_datasets != candidate_datasets:
        mismatches.append("fact_datasets")
    for dataset in sorted(
        set(reference_datasets) | set(candidate_datasets), key=lambda item: item.value
    ):
        left = _fact_frame_or_empty(reference, dataset, reference_datasets)
        right = _fact_frame_or_empty(candidate, dataset, candidate_datasets)
        receipt, table_mismatches = _compare_frame_exact(
            f"fact:{dataset.value}",
            left,
            right,
            research_contract(dataset).business_key,
        )
        tables.append(receipt)
        mismatches.extend(table_mismatches)
    for feature_set in _FEATURE_ORDER:
        receipt, table_mismatches = _compare_frame_exact(
            f"feature:{feature_set}",
            reference.features.read(feature_set),
            candidate.features.read(feature_set),
            _FEATURE_KEYS[feature_set],
        )
        tables.append(receipt)
        mismatches.extend(table_mismatches)
    unique = tuple(dict.fromkeys(mismatches))
    return ExactParityReceipt(
        origin=reference.analysis_date,
        exact_equal=not unique,
        mismatches=unique,
        tables=tuple(tables),
        reference_cache_key=reference.cache_key,
        candidate_cache_key=candidate.cache_key,
    )


def persist_equivalence_gate(
    receipts: Iterable[ExactParityReceipt],
    root: Path,
) -> Path:
    """Persist an all-or-nothing exact parity gate below ``preflight``."""

    output_root = _validated_output_root(root)
    values = tuple(receipts)
    if not values:
        raise ValueError("at least one exact parity receipt is required")
    preflight = output_root / "preflight"
    diff_root = preflight / "equivalence-diff"
    final = preflight / "equivalence-receipt.json"
    final.unlink(missing_ok=True)
    failed = tuple(value for value in values if not value.exact_equal)
    if failed:
        diff_root.mkdir(parents=True, exist_ok=True)
        for receipt in failed:
            _atomic_write_json(
                diff_root / f"{receipt.origin.isoformat()}.json",
                _jsonable(receipt),
            )
        raise RuntimeError("exact snapshot equivalence gate failed")
    if len({value.origin for value in values}) != len(values):
        raise ValueError("equivalence receipts contain duplicate origins")
    shutil.rmtree(diff_root, ignore_errors=True)
    payload = {
        "exact_equal": True,
        "origins": [value.origin.isoformat() for value in values],
        "receipts": [_jsonable(value) for value in values],
    }
    _atomic_write_json(final, payload)
    return final


def _load_manifest_inventory(
    warehouse: ResearchWarehouse,
    plans: Mapping[date, Mapping[ResearchDatasetId, tuple[str, ...]]],
    *,
    include_production: bool,
) -> dict[ResearchDatasetId, pd.DataFrame]:
    datasets = {dataset for plan in plans.values() for dataset in plan}
    if include_production:
        datasets.update(_PRODUCTION_DATASETS)
    return {
        dataset: warehouse.partition_manifest(dataset).copy(deep=True)
        for dataset in sorted(datasets, key=lambda item: item.value)
    }


def _preload_union(
    warehouse: ResearchWarehouse,
    inventory: Mapping[ResearchDatasetId, pd.DataFrame],
    union: Mapping[ResearchDatasetId, Iterable[str]],
    read_counts: dict[ResearchDatasetId, int],
    *,
    existing: _InMemoryWarehouse | None = None,
) -> _InMemoryWarehouse:
    manifests = {} if existing is None else dict(existing._manifests)
    current = {} if existing is None else dict(existing._current)
    revisions = {} if existing is None else dict(existing._revisions)
    partition_columns = (
        {} if existing is None else {
            dataset: dict(columns)
            for dataset, columns in existing._partition_columns.items()
        }
    )
    for dataset, raw_partitions in sorted(union.items(), key=lambda item: item[0].value):
        partitions = tuple(sorted({str(value) for value in raw_partitions}))
        if not partitions:
            continue
        already = set()
        if dataset in current and not current[dataset].empty:
            already = set(current[dataset][_PARTITION_COLUMN].astype(str))
        missing = tuple(value for value in partitions if value not in already)
        if dataset in manifests and current.get(dataset, pd.DataFrame()).empty:
            manifest_values = set(
                manifests[dataset].get("partition_value", pd.Series(dtype=str)).astype(str)
            )
            if set(partitions).issubset(manifest_values):
                missing = ()
        if not missing:
            continue
        frame, metadata = warehouse.read_current_partitions_with_manifest(
            dataset, missing
        )
        rows = warehouse.revision_rows(dataset, partition_values=missing)
        read_counts[dataset] = read_counts.get(dataset, 0) + 1
        declared = inventory.get(dataset, pd.DataFrame())
        if declared.empty:
            raise ValueError(f"required fact dataset has no partition: {dataset.value}")
        selected_manifest = declared.loc[
            declared["partition_value"].astype(str).isin(partitions)
        ].copy()
        manifests[dataset] = selected_manifest.reset_index(drop=True)
        schema_by_partition = partition_columns.setdefault(dataset, {})
        metadata_by_partition = {
            str(row["partition_value"]): row
            for row in metadata.to_dict(orient="records")
        }
        for partition in missing:
            row = metadata_by_partition[partition]
            path = Path(warehouse.root) / str(row["relative_path"])
            schema_by_partition[partition] = tuple(
                pa_parquet.read_schema(path).names
            )
        current[dataset] = _concat_frames(current.get(dataset), frame)
        revisions[dataset] = tuple(revisions.get(dataset, ())) + tuple(
            _copy_revision(row) for row in rows
        )
    return _InMemoryWarehouse(
        Path(warehouse.root),
        manifests,
        current,
        revisions,
        partition_columns,
    )


def _build_feature_plans(
    warehouse: Any,
    query: ResearchQuery,
    origin: date,
    inventory: Mapping[ResearchDatasetId, pd.DataFrame],
) -> _FeaturePlans:
    calendar_partitions = _calendar_partitions_from_inventory(inventory, origin)
    calendar_snapshot = query.materialize_snapshot(
        {ResearchDatasetId.TRADE_CALENDAR: calendar_partitions},
        as_of=formation_cutoff(origin),
    )
    sessions = production_features._open_sessions(
        calendar_snapshot.frame(ResearchDatasetId.TRADE_CALENDAR), origin
    )
    if origin not in sessions:
        raise ValueError(
            f"analysis date is not an open session in the fact calendar: {origin}"
        )
    price_dates = tuple(value.isoformat() for value in sessions[-82:])
    context_dates = tuple(value.isoformat() for value in sessions[-250:])
    recent_limit_dates = tuple(value.isoformat() for value in sessions[-5:])
    five_year_start = (pd.Timestamp(origin) - pd.DateOffset(years=5)).date()
    valuation_dates = tuple(
        value.isoformat() for value in sessions if value >= five_year_start
    )

    def required(dataset: ResearchDatasetId) -> tuple[str, ...]:
        return _required_inventory_partitions(inventory, dataset)

    def optional(
        dataset: ResearchDatasetId, requested: Iterable[str]
    ) -> tuple[str, ...]:
        available = set(_inventory_values(inventory, dataset))
        return tuple(value for value in requested if value in available)

    minute = optional(ResearchDatasetId.MINUTE_BAR, (origin.isoformat(),))
    industry_daily = optional(ResearchDatasetId.INDUSTRY_DAILY, price_dates)
    theme_daily = optional(ResearchDatasetId.THEME_DAILY, price_dates)
    calendar_input = {ResearchDatasetId.TRADE_CALENDAR: calendar_partitions}
    market = {
        **calendar_input,
        ResearchDatasetId.SECURITY_MASTER: required(ResearchDatasetId.SECURITY_MASTER),
        ResearchDatasetId.EQUITY_DAILY: price_dates,
        ResearchDatasetId.ADJ_FACTOR: price_dates,
        ResearchDatasetId.INDEX_DAILY: context_dates,
        ResearchDatasetId.STOCK_LIMIT: (origin.isoformat(),),
    }
    sector = {
        **calendar_input,
        ResearchDatasetId.EQUITY_DAILY: price_dates,
        ResearchDatasetId.ADJ_FACTOR: price_dates,
        ResearchDatasetId.INDEX_DAILY: price_dates,
        ResearchDatasetId.STOCK_LIMIT: (origin.isoformat(),),
        ResearchDatasetId.INDUSTRY_CATALOG: required(
            ResearchDatasetId.INDUSTRY_CATALOG
        ),
        ResearchDatasetId.INDUSTRY_MEMBER: required(
            ResearchDatasetId.INDUSTRY_MEMBER
        ),
        ResearchDatasetId.INDUSTRY_DAILY: industry_daily,
        ResearchDatasetId.THEME_CATALOG: required(ResearchDatasetId.THEME_CATALOG),
        ResearchDatasetId.THEME_MEMBER: required(ResearchDatasetId.THEME_MEMBER),
        ResearchDatasetId.THEME_DAILY: theme_daily,
    }
    if minute:
        sector[ResearchDatasetId.MINUTE_BAR] = minute
    stock = {
        **calendar_input,
        ResearchDatasetId.EQUITY_DAILY: price_dates,
        ResearchDatasetId.ADJ_FACTOR: price_dates,
        ResearchDatasetId.INDEX_DAILY: context_dates,
        ResearchDatasetId.STOCK_LIMIT: recent_limit_dates,
        ResearchDatasetId.DAILY_BASIC: valuation_dates,
    }
    return _FeaturePlans(
        price_dates=price_dates,
        context_dates=context_dates,
        market=market,
        sector=sector,
        stock=stock,
        industry_daily_gap=len(industry_daily) < len(price_dates),
        theme_daily_gap=len(theme_daily) < len(price_dates),
    )


def _compute_production_features(
    query: ResearchQuery,
    origin: date,
    plans: _FeaturePlans,
) -> BatchFeatureResult:
    limitations: list[str] = []
    cutoff = formation_cutoff(origin)

    market_snapshot = query.materialize_snapshot(plans.market, as_of=cutoff)
    production_features._assert_calendar_window(
        market_snapshot,
        origin,
        price_dates=plans.price_dates,
        context_dates=plans.context_dates,
    )
    equity = market_snapshot.frame(ResearchDatasetId.EQUITY_DAILY)
    securities = market_snapshot.frame(ResearchDatasetId.SECURITY_MASTER)
    if securities.empty:
        limitations.append(
            "历史证券主数据不可严格回放，市场覆盖分母使用当日已可见行情证券集合"
        )
    market = compute_market_context_features(
        production_features._equity_with_adjustment(
            equity, market_snapshot.frame(ResearchDatasetId.ADJ_FACTOR)
        ),
        market_snapshot.frame(ResearchDatasetId.INDEX_DAILY),
        market_snapshot.frame(ResearchDatasetId.STOCK_LIMIT),
        analysis_date=origin,
        expected_current_rows=production_features._expected_current_rows(
            securities, equity, origin
        ),
    )
    limitations.extend(
        production_features._partition_quality(
            "market_context", market, minute_state="not_requested"
        )[1]
    )
    if plans.industry_daily_gap:
        limitations.append("行业指数日线历史短于价格窗口，仅使用截止时点已存在分区")
    if plans.theme_daily_gap:
        limitations.append("主题指数日线历史短于价格窗口，仅使用截止时点已存在分区")

    sector_snapshot = query.materialize_snapshot(plans.sector, as_of=cutoff)
    production_features._assert_calendar_window(
        sector_snapshot,
        origin,
        price_dates=plans.price_dates,
        context_dates=plans.context_dates,
    )
    minute_requested = ResearchDatasetId.MINUTE_BAR in plans.sector
    minutes = (
        sector_snapshot.frame(ResearchDatasetId.MINUTE_BAR)
        if minute_requested
        else production_features._empty_minutes()
    )
    sector = compute_hotspot_features(
        production_features._equity_with_adjustment(
            sector_snapshot.frame(ResearchDatasetId.EQUITY_DAILY),
            sector_snapshot.frame(ResearchDatasetId.ADJ_FACTOR),
        ),
        production_features._sector_catalog(
            sector_snapshot.frame(ResearchDatasetId.INDUSTRY_CATALOG),
            sector_snapshot.frame(ResearchDatasetId.THEME_CATALOG),
            origin,
        ),
        production_features._sector_memberships(
            sector_snapshot.frame(ResearchDatasetId.INDUSTRY_MEMBER),
            sector_snapshot.frame(ResearchDatasetId.THEME_MEMBER),
            origin,
        ),
        production_features._benchmark(
            sector_snapshot.frame(ResearchDatasetId.INDEX_DAILY)
        ),
        sector_snapshot.frame(ResearchDatasetId.STOCK_LIMIT),
        production_features._official_sector_daily(
            sector_snapshot.frame(ResearchDatasetId.INDUSTRY_DAILY),
            sector_snapshot.frame(ResearchDatasetId.THEME_DAILY),
        ),
        production_features._minute_bars(minutes),
        analysis_date=origin,
    )
    minute_state = (
        "not_requested"
        if not minute_requested
        else "unavailable_at_cutoff"
        if minutes.empty
        else "resolved"
    )
    limitations.extend(
        production_features._partition_quality(
            "sector_hotspot", sector, minute_state=minute_state
        )[1]
    )

    stock_snapshot = query.materialize_snapshot(plans.stock, as_of=cutoff)
    production_features._assert_calendar_window(
        stock_snapshot,
        origin,
        price_dates=plans.price_dates,
        context_dates=plans.context_dates,
    )
    stock = compute_stock_context_features(
        production_features._equity_with_adjustment(
            stock_snapshot.frame(ResearchDatasetId.EQUITY_DAILY),
            stock_snapshot.frame(ResearchDatasetId.ADJ_FACTOR),
        ),
        production_features._benchmark(
            stock_snapshot.frame(ResearchDatasetId.INDEX_DAILY)
        ),
        stock_snapshot.frame(ResearchDatasetId.STOCK_LIMIT),
        stock_snapshot.frame(ResearchDatasetId.DAILY_BASIC),
        analysis_date=origin,
    )
    limitations.extend(
        production_features._partition_quality(
            "stock_trading_context", stock, minute_state="not_requested"
        )[1]
    )
    frames = {
        "market_context": market,
        "sector_hotspot": sector,
        "stock_trading_context": stock,
    }
    hashes = {
        "market_context": str(market_snapshot.input_manifest["input_manifest_hash"]),
        "sector_hotspot": str(sector_snapshot.input_manifest["input_manifest_hash"]),
        "stock_trading_context": str(stock_snapshot.input_manifest["input_manifest_hash"]),
    }
    return BatchFeatureResult(
        frames=frames,
        fact_manifest_hashes=hashes,
        formula_versions=_FORMULA_VERSIONS,
        limitations=tuple(dict.fromkeys(limitations)),
    )


def _assemble_snapshot(
    origin: date,
    cutoff: datetime,
    facts: FormationFactView,
    result: BatchFeatureResult,
) -> FormationSnapshot:
    if not isinstance(result, BatchFeatureResult):
        raise TypeError("feature builder must return BatchFeatureResult")
    if set(result.frames) != set(_FEATURE_ORDER):
        raise ValueError("feature builder must return exactly the three feature frames")
    if set(result.fact_manifest_hashes) != set(_FEATURE_ORDER):
        raise ValueError("feature builder fact manifests are incomplete")
    if set(result.formula_versions) != set(_FEATURE_ORDER):
        raise ValueError("feature builder formula versions are incomplete")
    frames = {
        feature_set: result.frames[feature_set].copy(deep=True)
        for feature_set in _FEATURE_ORDER
    }
    for feature_set, frame in frames.items():
        if frame.empty:
            raise RuntimeError(f"core feature output is empty: {feature_set}")
        _validate_business_keys(
            f"feature:{feature_set}", frame, _FEATURE_KEYS[feature_set]
        )
        if "analysis_date" not in frame:
            raise ValueError(f"feature frame lacks analysis_date: {feature_set}")
        observed_dates = {
            value.date() if isinstance(value, datetime) else value
            for value in pd.to_datetime(frame["analysis_date"], errors="raise")
        }
        if observed_dates != {origin}:
            raise ValueError(f"feature frame contains another origin: {feature_set}")
    fact_hashes = tuple(
        (feature_set, _sha256_value(result.fact_manifest_hashes[feature_set]))
        for feature_set in _FEATURE_ORDER
    )
    formula_versions = tuple(
        (feature_set, str(result.formula_versions[feature_set]))
        for feature_set in _FEATURE_ORDER
    )
    cache_payload = {
        "origin": origin.isoformat(),
        "as_of": cutoff.isoformat(),
        "fact_manifest_hashes": list(fact_hashes),
        "formula_versions": list(formula_versions),
    }
    cache_key = _stable_hash(cache_payload)
    return FormationSnapshot(
        analysis_date=origin,
        as_of=cutoff,
        facts=facts,
        features=FormationFeatureView(frames),
        market_rows=len(frames["market_context"]),
        sector_rows=len(frames["sector_hotspot"]),
        stock_rows=len(frames["stock_trading_context"]),
        limitations=tuple(str(value) for value in result.limitations),
        cache_key=cache_key,
        fact_manifest_hashes=fact_hashes,
        formula_versions=formula_versions,
    )


def _persist_snapshot(snapshot: FormationSnapshot, root: Path) -> tuple[str, int]:
    tables = _snapshot_tables(snapshot)
    encoded: list[tuple[str, bytes, str, int]] = []
    for label, frame, business_key in tables:
        _validate_business_keys(label, frame, business_key)
        data = _arrow_ipc_bytes(frame)
        if len(data) > MAX_CACHE_FILE_BYTES:
            raise ValueError(f"cache file exceeds 3.5GB: {label}")
        encoded.append((label, data, hashlib.sha256(data).hexdigest(), len(frame)))
    identity = {
        "analysis_date": snapshot.analysis_date.isoformat(),
        "as_of": snapshot.as_of.isoformat(),
        "facts_manifest": snapshot.facts.manifest,
        "fact_manifest_hashes": list(snapshot.fact_manifest_hashes),
        "formula_versions": list(snapshot.formula_versions),
        "limitations": list(snapshot.limitations),
        "cache_key": snapshot.cache_key,
        "tables": [
            {"table": label, "sha256": digest, "row_count": rows}
            for label, _, digest, rows in encoded
        ],
    }
    content_hash = _stable_hash(identity)
    snapshots_root = root / "cache" / "snapshots"
    destination = snapshots_root / content_hash
    written = 0
    if destination.exists():
        _validate_existing_content(destination, content_hash, encoded)
    else:
        partial = snapshots_root / f".partial-{uuid4().hex}"
        try:
            partial.mkdir(parents=False, exist_ok=False)
            files: list[dict[str, Any]] = []
            for label, data, digest, rows in encoded:
                name = label.replace(":", "__") + ".arrow"
                path = partial / name
                path.write_bytes(data)
                files.append(
                    {
                        "name": name,
                        "table": label,
                        "sha256": digest,
                        "size": len(data),
                        "row_count": rows,
                    }
                )
                written += len(data)
            manifest = {**identity, "content_hash": content_hash, "files": files}
            _atomic_write_json(partial / "manifest.json", manifest)
            _validate_existing_content(partial, content_hash, encoded)
            try:
                partial.rename(destination)
            except FileExistsError:
                _validate_existing_content(destination, content_hash, encoded)
                shutil.rmtree(partial)
        except Exception:
            shutil.rmtree(partial, ignore_errors=True)
            raise
    _atomic_write_json(
        snapshots_root / "by-date" / f"{snapshot.analysis_date.isoformat()}.json",
        {
            "analysis_date": snapshot.analysis_date.isoformat(),
            "as_of": snapshot.as_of.isoformat(),
            "content_hash": content_hash,
            "cache_key": snapshot.cache_key,
        },
    )
    return content_hash, written


def _validate_existing_content(
    root: Path,
    expected_hash: str,
    encoded: Sequence[tuple[str, bytes, str, int]],
) -> None:
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError(f"content-addressed snapshot lacks manifest: {root}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid content-addressed snapshot manifest: {root}") from exc
    if manifest.get("content_hash") != expected_hash:
        raise ValueError("content-addressed snapshot hash mismatch")
    if any(field not in manifest for field in _SNAPSHOT_IDENTITY_FIELDS):
        raise ValueError("content-addressed snapshot identity is incomplete")
    identity = {field: manifest[field] for field in _SNAPSHOT_IDENTITY_FIELDS}
    if _stable_hash(identity) != expected_hash:
        raise ValueError("content-addressed snapshot identity hash mismatch")
    expected = {label: (digest, len(data), rows) for label, data, digest, rows in encoded}
    files = manifest.get("files")
    if not isinstance(files, list) or len(files) != len(expected):
        raise ValueError("content-addressed snapshot file manifest is incomplete")
    for item in files:
        label = str(item.get("table"))
        if label not in expected:
            raise ValueError("content-addressed snapshot has an unknown table")
        digest, size, rows = expected[label]
        path = root / str(item.get("name"))
        if not path.is_file() or path.stat().st_size != size:
            raise ValueError(f"content-addressed snapshot file size mismatch: {label}")
        if size > MAX_CACHE_FILE_BYTES:
            raise ValueError(f"cache file exceeds 3.5GB: {label}")
        if (
            item.get("sha256") != digest
            or int(item.get("row_count", -1)) != rows
            or _sha256_file(path) != digest
        ):
            raise ValueError(f"content-addressed snapshot file mismatch: {label}")


def _load_snapshot(
    output_root: Path,
    content_hash: str,
    *,
    expected_origin: date,
) -> FormationSnapshot:
    content_root = output_root / "cache" / "snapshots" / content_hash
    manifest_path = content_root / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError("content-addressed snapshot lacks manifest")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("invalid content-addressed snapshot manifest") from exc
    if manifest.get("content_hash") != content_hash:
        raise ValueError("content-addressed snapshot hash mismatch")
    if any(field not in manifest for field in _SNAPSHOT_IDENTITY_FIELDS):
        raise ValueError("content-addressed snapshot identity is incomplete")
    identity = {field: manifest[field] for field in _SNAPSHOT_IDENTITY_FIELDS}
    if _stable_hash(identity) != content_hash:
        raise ValueError("content-addressed snapshot identity hash mismatch")
    try:
        analysis_date = date.fromisoformat(str(manifest["analysis_date"]))
        as_of = datetime.fromisoformat(str(manifest["as_of"]))
    except ValueError as exc:
        raise ValueError("content-addressed snapshot has invalid time fields") from exc
    if analysis_date != expected_origin or as_of != formation_cutoff(expected_origin):
        raise ValueError("content-addressed snapshot origin or cutoff mismatch")

    declared_tables = manifest.get("tables")
    files = manifest.get("files")
    if not isinstance(declared_tables, list) or not isinstance(files, list):
        raise ValueError("content-addressed snapshot table manifest is incomplete")
    declared = {
        str(item["table"]): (str(item["sha256"]), int(item["row_count"]))
        for item in declared_tables
        if isinstance(item, Mapping)
        and {"table", "sha256", "row_count"}.issubset(item)
    }
    if len(declared) != len(declared_tables):
        raise ValueError("content-addressed snapshot has duplicate table identities")
    frames: dict[str, pd.DataFrame] = {}
    for item in files:
        if not isinstance(item, Mapping):
            raise ValueError("content-addressed snapshot file entry is invalid")
        label = str(item.get("table"))
        if label not in declared or label in frames:
            raise ValueError("content-addressed snapshot has an unknown table")
        expected_digest, expected_rows = declared[label]
        path = content_root / str(item.get("name"))
        if not path.is_file():
            raise ValueError(f"content-addressed snapshot file is missing: {label}")
        size = path.stat().st_size
        if size > MAX_CACHE_FILE_BYTES:
            raise ValueError(f"cache file exceeds 3.5GB: {label}")
        if size != int(item.get("size", -1)):
            raise ValueError(f"content-addressed snapshot file size mismatch: {label}")
        digest = _sha256_file(path)
        if digest != expected_digest or digest != str(item.get("sha256")):
            raise ValueError(f"content-addressed snapshot file mismatch: {label}")
        try:
            with pa.memory_map(str(path), "r") as source:
                frame = pa_ipc.open_file(source).read_all().to_pandas(
                    types_mapper=pd.ArrowDtype
                )
        except (OSError, pa.ArrowException) as exc:
            raise ValueError(
                f"content-addressed snapshot file cannot be read: {label}"
            ) from exc
        if len(frame) != expected_rows or len(frame) != int(item.get("row_count", -1)):
            raise ValueError(f"content-addressed snapshot row count mismatch: {label}")
        frames[label] = frame
    if set(frames) != set(declared):
        raise ValueError("content-addressed snapshot files are incomplete")

    facts_manifest = manifest["facts_manifest"]
    if not isinstance(facts_manifest, Mapping):
        raise ValueError("content-addressed snapshot fact manifest is invalid")
    fact_frames: dict[ResearchDatasetId, pd.DataFrame] = {}
    for row in facts_manifest.get("effective_rows", ()):
        if not isinstance(row, Mapping) or "dataset" not in row:
            raise ValueError("content-addressed snapshot effective rows are invalid")
        dataset = ResearchDatasetId(str(row["dataset"]))
        label = f"fact:{dataset.value}"
        if label not in frames:
            raise ValueError(f"content-addressed snapshot fact table is missing: {label}")
        frame = frames[label]
        if len(frame) != int(row.get("row_count", -1)):
            raise ValueError(f"content-addressed snapshot fact row count mismatch: {label}")
        _validate_business_keys(label, frame, research_contract(dataset).business_key)
        fact_frames[dataset] = frame
    feature_frames: dict[str, pd.DataFrame] = {}
    for feature_set in _FEATURE_ORDER:
        label = f"feature:{feature_set}"
        if label not in frames:
            raise ValueError(f"content-addressed snapshot feature is missing: {label}")
        frame = frames[label]
        _validate_business_keys(label, frame, _FEATURE_KEYS[feature_set])
        feature_frames[feature_set] = frame

    fact_hashes = tuple(
        (str(item[0]), _sha256_value(item[1]))
        for item in manifest["fact_manifest_hashes"]
    )
    formula_versions = tuple(
        (str(item[0]), str(item[1])) for item in manifest["formula_versions"]
    )
    cache_payload = {
        "origin": analysis_date.isoformat(),
        "as_of": as_of.isoformat(),
        "fact_manifest_hashes": list(fact_hashes),
        "formula_versions": list(formula_versions),
    }
    if _stable_hash(cache_payload) != str(manifest["cache_key"]):
        raise ValueError("content-addressed snapshot cache key mismatch")
    return FormationSnapshot(
        analysis_date=analysis_date,
        as_of=as_of,
        facts=FormationFactView(fact_frames, facts_manifest),
        features=FormationFeatureView(feature_frames),
        market_rows=len(feature_frames["market_context"]),
        sector_rows=len(feature_frames["sector_hotspot"]),
        stock_rows=len(feature_frames["stock_trading_context"]),
        limitations=tuple(str(value) for value in manifest["limitations"]),
        cache_key=str(manifest["cache_key"]),
        fact_manifest_hashes=fact_hashes,
        formula_versions=formula_versions,
    )


def _snapshot_tables(
    snapshot: FormationSnapshot,
) -> list[tuple[str, pd.DataFrame, tuple[str, ...]]]:
    tables = [
        (
            f"fact:{dataset.value}",
            snapshot.facts.dataset(dataset),
            research_contract(dataset).business_key,
        )
        for dataset in _snapshot_fact_datasets(snapshot)
    ]
    tables.extend(
        (
            f"feature:{feature_set}",
            snapshot.features.read(feature_set),
            _FEATURE_KEYS[feature_set],
        )
        for feature_set in _FEATURE_ORDER
    )
    return tables


def _snapshot_fact_datasets(snapshot: FormationSnapshot) -> tuple[ResearchDatasetId, ...]:
    rows = snapshot.facts.manifest.get("effective_rows")
    if not isinstance(rows, list):
        raise ValueError("fact view manifest lacks effective_rows")
    datasets: list[ResearchDatasetId] = []
    for row in rows:
        if not isinstance(row, Mapping) or "dataset" not in row:
            raise ValueError("invalid effective fact row manifest")
        datasets.append(ResearchDatasetId(str(row["dataset"])))
    if len(datasets) != len(set(datasets)):
        raise ValueError("fact view manifest contains duplicate datasets")
    return tuple(sorted(datasets, key=lambda item: item.value))


def _compare_frame_exact(
    label: str,
    reference: pd.DataFrame,
    candidate: pd.DataFrame,
    business_key: Sequence[str],
) -> tuple[ExactTableReceipt, tuple[str, ...]]:
    left_table = _canonical_arrow_table(reference)
    right_table = _canonical_arrow_table(candidate)
    left_bytes = _arrow_table_bytes(left_table)
    right_bytes = _arrow_table_bytes(right_table)
    left_key = _business_key_hash(reference, business_key)
    right_key = _business_key_hash(candidate, business_key)
    mismatches: list[str] = []
    if tuple(reference.columns.astype(str)) != tuple(candidate.columns.astype(str)):
        mismatches.append(f"{label}:column_order")
    if left_table.schema != right_table.schema:
        mismatches.append(f"{label}:schema")
    if len(reference) != len(candidate):
        mismatches.append(f"{label}:row_count")
    if left_key != right_key:
        mismatches.append(f"{label}:business_keys")
    left_hash = hashlib.sha256(left_bytes).hexdigest()
    right_hash = hashlib.sha256(right_bytes).hexdigest()
    if left_hash != right_hash:
        mismatches.append(f"{label}:content_hash")
    receipt = ExactTableReceipt(
        table=label,
        reference_rows=len(reference),
        candidate_rows=len(candidate),
        reference_columns=tuple(reference.columns.astype(str)),
        candidate_columns=tuple(candidate.columns.astype(str)),
        reference_schema=str(left_table.schema),
        candidate_schema=str(right_table.schema),
        reference_business_key_hash=left_key,
        candidate_business_key_hash=right_key,
        reference_content_hash=left_hash,
        candidate_content_hash=right_hash,
        exact_equal=not mismatches,
    )
    return receipt, tuple(mismatches)


def _canonical_arrow_table(frame: pd.DataFrame) -> pa.Table:
    normalized = pd.DataFrame(index=frame.index)
    for column in frame.columns:
        normalized[str(column)] = _normalize_series(frame[column])
    table = pa.Table.from_pandas(normalized, preserve_index=False, safe=True)
    return table.replace_schema_metadata(None).combine_chunks()


def _normalize_series(values: pd.Series) -> pd.Series:
    if isinstance(values.dtype, pd.CategoricalDtype):
        return values.astype("string")
    if pd.api.types.is_datetime64_any_dtype(values.dtype):
        converted = pd.to_datetime(values, errors="raise")
        if getattr(converted.dt, "tz", None) is not None:
            converted = converted.dt.tz_convert("UTC")
        return converted.astype("datetime64[ns, UTC]") if getattr(
            converted.dt, "tz", None
        ) is not None else converted.astype("datetime64[ns]")
    if pd.api.types.is_timedelta64_dtype(values.dtype):
        return values.astype("timedelta64[ns]")
    if pd.api.types.is_bool_dtype(values.dtype):
        return values.astype("boolean")
    if pd.api.types.is_integer_dtype(values.dtype):
        converted = values.astype("Int64")
        mask = converted.isna().to_numpy(dtype=bool)
        data = converted.fillna(0).to_numpy(dtype="int64", na_value=0)
        return pd.Series(
            pd.arrays.IntegerArray(data, mask),
            index=values.index,
            name=values.name,
        )
    if pd.api.types.is_float_dtype(values.dtype):
        return values.astype("Float64")
    if pd.api.types.is_string_dtype(values.dtype) and values.dtype != object:
        return values.astype("string")
    non_null = [value for value in values.tolist() if not _is_null(value)]
    if not non_null:
        return values.astype("string")
    if all(isinstance(value, (datetime, date, pd.Timestamp)) for value in non_null):
        converted = pd.to_datetime(values, errors="raise")
        if getattr(converted.dt, "tz", None) is not None:
            return converted.dt.tz_convert("UTC").astype("datetime64[ns, UTC]")
        return converted.astype("datetime64[ns]")
    if all(isinstance(value, bool) for value in non_null):
        return _normalize_series(values.astype("boolean"))
    if all(isinstance(value, Integral) and not isinstance(value, bool) for value in non_null):
        return _normalize_series(
            pd.to_numeric(values, errors="raise").astype("Int64")
        )
    if all(isinstance(value, Real) and not isinstance(value, bool) for value in non_null):
        return _normalize_series(
            pd.to_numeric(values, errors="raise").astype("Float64")
        )
    if all(isinstance(value, str) for value in non_null):
        return values.astype("string")
    return values.map(
        lambda value: pd.NA
        if _is_null(value)
        else json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    ).astype("string")


def _business_key_hash(frame: pd.DataFrame, key: Sequence[str]) -> str:
    if frame.empty:
        return _stable_hash([])
    _validate_business_keys("comparison table", frame, key)
    keys = frame.loc[:, list(key)].copy()
    try:
        keys = keys.sort_values(list(key), kind="mergesort").reset_index(drop=True)
    except TypeError:
        keys = keys.assign(
            __sort=keys.astype("string").agg("\x1f".join, axis=1)
        ).sort_values("__sort", kind="mergesort").drop(columns="__sort")
    return hashlib.sha256(_arrow_ipc_bytes(keys)).hexdigest()


def _validate_business_keys(
    label: str,
    frame: pd.DataFrame,
    business_key: Sequence[str],
) -> None:
    if frame.empty:
        return
    missing = [column for column in business_key if column not in frame]
    if missing:
        raise ValueError(f"{label} lacks business key columns: {missing}")
    if frame[list(business_key)].isna().any(axis=None):
        raise ValueError(f"{label} has a null business key")
    duplicates = frame.duplicated(list(business_key), keep=False)
    if duplicates.any():
        raise ValueError(
            f"{label} has duplicate business key: {int(duplicates.sum())} rows"
        )


def _arrow_ipc_bytes(frame: pd.DataFrame) -> bytes:
    return _arrow_table_bytes(_canonical_arrow_table(frame))


def _arrow_table_bytes(table: pa.Table) -> bytes:
    sink = pa.BufferOutputStream()
    with pa_ipc.new_file(sink, table.schema) as writer:
        writer.write_table(table)
    return sink.getvalue().to_pybytes()


def _normalize_origins(values: Iterable[date]) -> tuple[date, ...]:
    origins = tuple(_as_origin(value) for value in values)
    if not origins:
        raise ValueError("operational_dates must not be empty")
    if len(origins) != len(set(origins)):
        raise ValueError("operational_dates must not contain duplicates")
    if origins != tuple(sorted(origins)):
        raise ValueError("operational_dates must be strictly increasing")
    return origins


def _as_origin(value: date) -> date:
    if isinstance(value, datetime) or not isinstance(value, date):
        raise TypeError("origin must be a date without a time component")
    return value


def _normalize_fact_plan(plan: FactPlan) -> dict[ResearchDatasetId, tuple[str, ...]]:
    if not isinstance(plan, Mapping):
        raise TypeError("fact plan factory must return a mapping")
    normalized: dict[ResearchDatasetId, tuple[str, ...]] = {}
    for raw_dataset, raw_partitions in plan.items():
        dataset = ResearchDatasetId(raw_dataset)
        if dataset in normalized:
            raise ValueError(f"fact plan contains duplicate dataset: {dataset.value}")
        values = (raw_partitions,) if isinstance(raw_partitions, str) else raw_partitions
        partitions = tuple(sorted({str(value) for value in values}))
        if not partitions:
            raise ValueError(f"fact plan has no partition: {dataset.value}")
        normalized[dataset] = partitions
    return normalized


def _union_fact_plans(
    plans: Iterable[Mapping[ResearchDatasetId, tuple[str, ...]]],
) -> dict[ResearchDatasetId, set[str]]:
    union: dict[ResearchDatasetId, set[str]] = {}
    for plan in plans:
        _merge_union(union, plan)
    return union


def _merge_union(
    union: dict[ResearchDatasetId, set[str]],
    plan: Mapping[ResearchDatasetId, Iterable[str]],
) -> None:
    for dataset, values in plan.items():
        union.setdefault(dataset, set()).update(str(value) for value in values)


def _calendar_partitions_from_inventory(
    inventory: Mapping[ResearchDatasetId, pd.DataFrame],
    through: date,
) -> tuple[str, ...]:
    selected = tuple(
        value
        for value in _required_inventory_partitions(
            inventory, ResearchDatasetId.TRADE_CALENDAR
        )
        if value.isdigit() and int(value) <= through.year
    )
    if not selected:
        raise ValueError("fact trading calendar has no usable partition")
    return selected


def _required_inventory_partitions(
    inventory: Mapping[ResearchDatasetId, pd.DataFrame],
    dataset: ResearchDatasetId,
) -> tuple[str, ...]:
    values = _inventory_values(inventory, dataset)
    if not values:
        raise ValueError(f"required fact dataset has no partition: {dataset.value}")
    return values


def _inventory_values(
    inventory: Mapping[ResearchDatasetId, pd.DataFrame],
    dataset: ResearchDatasetId,
) -> tuple[str, ...]:
    manifest = inventory.get(dataset, pd.DataFrame())
    if manifest.empty or "partition_value" not in manifest:
        return ()
    return tuple(sorted(manifest["partition_value"].astype(str).unique()))


def _validated_output_root(root: Path) -> Path:
    configured = os.environ.get("V3_BACKTEST_ROOT")
    if not configured:
        raise RuntimeError("V3_BACKTEST_ROOT must be set")
    expected = Path(configured).expanduser().resolve(strict=False)
    candidate = Path(root).expanduser().resolve(strict=False)
    if candidate != expected:
        raise ValueError("root must exactly match V3_BACKTEST_ROOT")
    return candidate


def _validate_source_separation(source: Path, output: Path) -> None:
    resolved_source = Path(source).resolve()
    if (
        resolved_source == output
        or resolved_source.is_relative_to(output)
        or output.is_relative_to(resolved_source)
    ):
        raise ValueError("V3_BACKTEST_ROOT must be separate from the source warehouse")


def _fact_frame_or_empty(
    snapshot: FormationSnapshot,
    dataset: ResearchDatasetId,
    available: Sequence[ResearchDatasetId],
) -> pd.DataFrame:
    return (
        snapshot.facts.dataset(dataset)
        if dataset in available
        else pd.DataFrame()
    )


def _concat_frames(
    existing: pd.DataFrame | None,
    incoming: pd.DataFrame,
) -> pd.DataFrame:
    if existing is None or existing.empty:
        return incoming
    if incoming.empty:
        return existing.copy(deep=True)
    return pd.concat((existing, incoming), ignore_index=True, sort=False)


def _copy_revision(value: Mapping[str, Any]) -> dict[str, Any]:
    copied = dict(value)
    copied["row_payload"] = dict(value["row_payload"])
    return copied


def _sha256_value(value: Any) -> str:
    text = str(value)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise ValueError("feature fact manifest hash must be lowercase SHA-256")
    return text


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = path.parent / f".{path.name}.partial-{uuid4().hex}"
    try:
        staged.write_text(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        if staged.stat().st_size > MAX_CACHE_FILE_BYTES:
            raise ValueError(f"cache file exceeds 3.5GB: {path.name}")
        os.replace(staged, path)
    finally:
        staged.unlink(missing_ok=True)


def _jsonable(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return _jsonable(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    return value


def _is_null(value: Any) -> bool:
    try:
        result = pd.isna(value)
    except (TypeError, ValueError):
        return False
    return bool(result) if isinstance(result, bool) else False


__all__ = [
    "BatchFeatureResult",
    "BatchSnapshotReceipt",
    "BatchSnapshotStore",
    "ExactParityReceipt",
    "ExactTableReceipt",
    "MAX_CACHE_FILE_BYTES",
    "compare_snapshot_exact",
    "materialize_readonly_reference_snapshot",
    "persist_equivalence_gate",
]
