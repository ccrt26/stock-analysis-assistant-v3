from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from zoneinfo import ZoneInfo

import pandas as pd

from stock_analyzer.analysis.hotspot_features import HOTSPOT_FORMULA_VERSION
from stock_analyzer.analysis.market_context_features import (
    MARKET_CONTEXT_FORMULA_VERSION,
)
from stock_analyzer.analysis.stock_context_features import STOCK_CONTEXT_FORMULA_VERSION
from stock_analyzer.data.research_contracts import ResearchDatasetId
from stock_analyzer.storage.research_derived import DerivedFeatureStore
from stock_analyzer.storage.research_query import ResearchQuery
from stock_analyzer.storage.research_schema import connect_research_warehouse
from stock_analyzer.storage.research_warehouse import ResearchWarehouse


_SHANGHAI = ZoneInfo("Asia/Shanghai")
_UTC = ZoneInfo("UTC")
_TEMP_PREFIX = "v3-complete-backtest-"
_ROOT_MARKER = ".v3-formation-snapshot-root.json"
_ROOT_LAYOUT_VERSION = 2
_ALLOWED_ROOT_ENTRIES = {
    _ROOT_MARKER,
    ".derived-promotions",
    ".derived.lock",
    ".staging",
    "derived",
    "facts",
    "research.duckdb",
}
_FEATURE_VERSIONS = (
    ("market_context", MARKET_CONTEXT_FORMULA_VERSION),
    ("sector_hotspot", HOTSPOT_FORMULA_VERSION),
    ("stock_trading_context", STOCK_CONTEXT_FORMULA_VERSION),
)


class FormationFactView:
    """Pure, detached as-of fact frames and their audited manifest."""

    __slots__ = ("__frames", "__manifest")

    def __init__(
        self,
        frames: Mapping[ResearchDatasetId, pd.DataFrame],
        manifest: Mapping[str, object],
    ) -> None:
        self.__frames = {
            dataset: frame.copy(deep=True) for dataset, frame in frames.items()
        }
        self.__manifest = _json_copy(manifest)

    def dataset(self, dataset_id: ResearchDatasetId | str):
        dataset = ResearchDatasetId(dataset_id)
        if dataset not in self.__frames:
            raise KeyError(f"dataset is not part of formation fact plan: {dataset.value}")
        return self.__frames[dataset].copy(deep=True)

    @property
    def manifest(self) -> dict[str, object]:
        return _json_copy(self.__manifest)


class FormationFeatureView:
    """Pure, detached copies of the three exact derived frames."""

    __slots__ = ("__frames",)

    def __init__(
        self,
        frames: Mapping[str, pd.DataFrame],
    ) -> None:
        self.__frames = {
            feature_set: frame.copy(deep=True)
            for feature_set, frame in frames.items()
        }

    def read(self, feature_set: str):
        if feature_set not in self.__frames:
            raise KeyError(f"feature set is not part of formation snapshot: {feature_set}")
        return self.__frames[feature_set].copy(deep=True)


@dataclass(frozen=True, slots=True)
class FormationSnapshot:
    analysis_date: date
    as_of: datetime
    facts: FormationFactView
    features: FormationFeatureView
    market_rows: int
    sector_rows: int
    stock_rows: int
    limitations: tuple[str, ...]
    cache_key: str
    fact_manifest_hashes: tuple[tuple[str, str], ...]
    formula_versions: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class _OriginState:
    partition_keys: tuple[tuple[str, str], ...]
    run_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _StoredFeatureSummary:
    failed_feature_sets: tuple[str, ...]
    errors: tuple[str, ...]
    market_rows: int
    sector_rows: int
    stock_rows: int
    limitations: tuple[str, ...]


class _ReadOnlyWarehouse:
    """The minimum warehouse surface required by ResearchQuery/feature replay."""

    __slots__ = ("root", "__warehouse")

    def __init__(self, warehouse: ResearchWarehouse) -> None:
        self.root = Path(warehouse.root)
        self.__warehouse = warehouse

    def partition_manifest(self, *args: Any, **kwargs: Any):
        return self.__warehouse.partition_manifest(*args, **kwargs)

    def read_current(self, *args: Any, **kwargs: Any):
        return self.__warehouse.read_current(*args, **kwargs)

    def read_current_partitions_with_manifest(self, *args: Any, **kwargs: Any):
        return self.__warehouse.read_current_partitions_with_manifest(*args, **kwargs)

    def revision_rows(self, *args: Any, **kwargs: Any):
        return self.__warehouse.revision_rows(*args, **kwargs)


def formation_cutoff(origin: date) -> datetime:
    return datetime.combine(origin, time(23, 59, 59), tzinfo=_SHANGHAI)


def tree_fingerprint(root: Path) -> str:
    root = Path(root)
    digest = hashlib.sha256()
    if not root.exists() and not root.is_symlink():
        return digest.hexdigest()
    if root.is_symlink():
        digest.update(b"L")
        digest.update(os.readlink(root).encode("utf-8"))
        return digest.hexdigest()
    if root.is_file():
        digest.update(b"F")
        _update_file_hash(digest, root)
        return digest.hexdigest()
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        if path.is_symlink():
            digest.update(b"L")
            digest.update(os.readlink(path).encode("utf-8"))
        elif path.is_file():
            digest.update(b"F")
            _update_file_hash(digest, path)
        elif path.is_dir():
            digest.update(b"D")
    return digest.hexdigest()


def materialize_formation_snapshot(
    warehouse: ResearchWarehouse,
    origin: date,
    temp_root: Path,
    *,
    fact_plan: Mapping[
        ResearchDatasetId | str,
        Iterable[str] | str,
    ],
    feature_runner: Callable[..., Any] | None = None,
) -> FormationSnapshot:
    if feature_runner is None:
        from stock_analyzer.ops.research_features import run_research_features

        feature_runner = run_research_features

    source = Path(warehouse.root).resolve()
    isolated = _validated_temp_root(source, temp_root)
    created = False
    origin_state: _OriginState | None = None
    try:
        created = _prepare_isolated_root(source, isolated)
        isolated_warehouse = ResearchWarehouse(isolated)
        read_only_warehouse = _ReadOnlyWarehouse(isolated_warehouse)
        cutoff = formation_cutoff(origin)
        fact_view = _materialize_fact_view(
            ResearchQuery(read_only_warehouse),
            fact_plan,
            origin=origin,
            cutoff=cutoff,
        )
        origin_state = _capture_origin_state(isolated, origin)
        store = DerivedFeatureStore(isolated)
        if origin_state.partition_keys:
            summary = _existing_feature_summary(store, origin)
        else:
            summary = feature_runner(read_only_warehouse, origin, as_of=cutoff)
        _validate_feature_summary(summary)

        expected_rows = {
            "market_context": int(summary.market_rows),
            "sector_hotspot": int(summary.sector_rows),
            "stock_trading_context": int(summary.stock_rows),
        }
        fact_hashes, formula_versions, cache_key = _cache_identity(
            store,
            origin=origin,
            cutoff=cutoff,
            expected_rows=expected_rows,
        )
        feature_view = _materialize_feature_view(
            store,
            origin=origin,
            expected_rows=expected_rows,
        )
        return FormationSnapshot(
            analysis_date=origin,
            as_of=cutoff,
            facts=fact_view,
            features=feature_view,
            market_rows=expected_rows["market_context"],
            sector_rows=expected_rows["sector_hotspot"],
            stock_rows=expected_rows["stock_trading_context"],
            limitations=tuple(str(value) for value in getattr(summary, "limitations", ())),
            cache_key=cache_key,
            fact_manifest_hashes=fact_hashes,
            formula_versions=formula_versions,
        )
    except Exception:
        if created:
            _remove_partial_root(isolated)
        elif origin_state is not None:
            _rollback_origin(isolated, origin, origin_state)
        raise


def _validated_temp_root(source: Path, temp_root: Path) -> Path:
    isolated = Path(temp_root).expanduser().resolve(strict=False)
    if (
        isolated == source
        or isolated.is_relative_to(source)
        or source.is_relative_to(isolated)
    ):
        raise ValueError("temporary root must be separate from source warehouse")

    tmp_root = Path("/tmp").resolve()
    try:
        relative = isolated.relative_to(tmp_root)
    except ValueError as exc:
        raise ValueError(
            "temporary root must be under /tmp/v3-complete-backtest-*"
        ) from exc
    if not relative.parts or not relative.parts[0].startswith(_TEMP_PREFIX):
        raise ValueError("temporary root must be under /tmp/v3-complete-backtest-*")
    return isolated


def _prepare_isolated_root(source: Path, isolated: Path) -> bool:
    identity = _source_identity(source)
    if isolated.exists():
        if not isolated.is_dir():
            raise ValueError("temporary root is not initialized by v3 snapshot module")
        if any(isolated.iterdir()):
            _validate_reusable_root(isolated, source, identity)
            return False
    try:
        isolated.mkdir(parents=True, exist_ok=True)
        _clone_path(source / "research.duckdb", isolated / "research.duckdb")
        derived = source / "derived"
        if derived.exists():
            _clone_path(derived, isolated / "derived")
        facts = source / "facts"
        if not facts.is_dir():
            raise FileNotFoundError(f"facts directory is missing: {facts}")
        _clone_path(facts, isolated / "facts")
        _write_root_marker(isolated, identity)
    except Exception:
        _remove_partial_root(isolated)
        raise
    return True


def _materialize_fact_view(
    query: ResearchQuery,
    fact_plan: Mapping[
        ResearchDatasetId | str,
        Iterable[str] | str,
    ],
    *,
    origin: date,
    cutoff: datetime,
) -> FormationFactView:
    if not isinstance(fact_plan, Mapping):
        raise TypeError("fact_plan must be a mapping")
    normalized: dict[ResearchDatasetId, Iterable[str] | str] = {}
    for raw_dataset, partitions in fact_plan.items():
        dataset = ResearchDatasetId(raw_dataset)
        if dataset in normalized:
            raise ValueError(f"fact_plan contains duplicate dataset: {dataset.value}")
        normalized[dataset] = partitions
    materialized = query.materialize_snapshot(normalized, as_of=cutoff)
    frames = {
        dataset: _filter_effective_relationships(
            dataset,
            materialized.frame(dataset),
            origin,
        )
        for dataset in normalized
    }
    source_manifest = _json_copy(materialized.input_manifest)
    effective_rows = [
        {"dataset": dataset.value, "row_count": len(frames[dataset])}
        for dataset in sorted(frames, key=lambda item: item.value)
    ]
    view_payload = {
        "source_snapshot": source_manifest,
        "effective_date": origin.isoformat(),
        "effective_rows": effective_rows,
    }
    manifest = {
        **view_payload,
        "view_manifest_hash": hashlib.sha256(
            json.dumps(
                view_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
    }
    return FormationFactView(frames, manifest)


def _filter_effective_relationships(
    dataset: ResearchDatasetId,
    frame: pd.DataFrame,
    origin: date,
) -> pd.DataFrame:
    membership_datasets = {
        ResearchDatasetId.INDUSTRY_MEMBER,
        ResearchDatasetId.THEME_MEMBER,
    }
    if dataset not in membership_datasets or frame.empty:
        return frame.reset_index(drop=True)
    if "valid_from" not in frame or "valid_to" not in frame:
        raise ValueError(f"classification relationship lacks validity fields: {dataset.value}")
    valid_from = pd.to_datetime(frame["valid_from"], errors="raise").dt.date
    valid_to = pd.to_datetime(frame["valid_to"], errors="coerce").dt.date
    active = (valid_from <= origin) & (valid_to.isna() | (valid_to >= origin))
    return frame.loc[active].reset_index(drop=True)


def _existing_feature_summary(
    store: DerivedFeatureStore,
    origin: date,
) -> _StoredFeatureSummary:
    rows: dict[str, int] = {}
    limitations: list[str] = []
    for feature_set, formula_version in _FEATURE_VERSIONS:
        manifest = store.partition_manifest(
            feature_set,
            analysis_date=origin,
            formula_version=formula_version,
        )
        if len(manifest) != 1:
            raise RuntimeError(
                f"existing formation feature manifest is not unique: {feature_set}"
            )
        row = manifest.iloc[0]
        rows[feature_set] = int(row["row_count"])
        raw_limitations = row["limitations_json"]
        values = (
            json.loads(raw_limitations)
            if isinstance(raw_limitations, str)
            else raw_limitations
        )
        limitations.extend(str(value) for value in (values or ()))
    return _StoredFeatureSummary(
        failed_feature_sets=(),
        errors=(),
        market_rows=rows["market_context"],
        sector_rows=rows["sector_hotspot"],
        stock_rows=rows["stock_trading_context"],
        limitations=tuple(dict.fromkeys(limitations)),
    )


def _materialize_feature_view(
    store: DerivedFeatureStore,
    *,
    origin: date,
    expected_rows: Mapping[str, int],
) -> FormationFeatureView:
    frames: dict[str, pd.DataFrame] = {}
    for feature_set, formula_version in _FEATURE_VERSIONS:
        frame = store.read(feature_set, origin, formula_version)
        if len(frame) != int(expected_rows[feature_set]):
            raise RuntimeError(f"formation feature frame row count mismatch: {feature_set}")
        frames[feature_set] = frame
    return FormationFeatureView(frames)


def _source_identity(source: Path) -> dict[str, object]:
    database = source / "research.duckdb"
    facts = source / "facts"
    if not database.is_file():
        raise FileNotFoundError(database)
    if not facts.is_dir():
        raise FileNotFoundError(facts)
    return {
        "layout_version": _ROOT_LAYOUT_VERSION,
        "source_root": str(source),
        "database": _stat_identity(database),
        "facts": _stat_identity(facts),
    }


def _stat_identity(path: Path) -> dict[str, int | str]:
    resolved = path.resolve()
    stat = resolved.stat()
    return {
        "path": str(resolved),
        "device": int(stat.st_dev),
        "inode": int(stat.st_ino),
        "size": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
    }


def _write_root_marker(isolated: Path, identity: Mapping[str, object]) -> None:
    marker = isolated / _ROOT_MARKER
    staged = isolated / f"{_ROOT_MARKER}.tmp"
    staged.write_text(
        json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    os.replace(staged, marker)


def _validate_reusable_root(
    isolated: Path,
    source: Path,
    expected_identity: Mapping[str, object],
) -> None:
    marker = isolated / _ROOT_MARKER
    if not marker.is_file() or marker.is_symlink():
        raise ValueError("temporary root is not initialized by v3 snapshot module")
    try:
        recorded = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("temporary root has an invalid snapshot marker") from exc
    if recorded != expected_identity:
        raise ValueError("temporary root source identity mismatch")

    unknown = {path.name for path in isolated.iterdir()}.difference(
        _ALLOWED_ROOT_ENTRIES
    )
    if unknown:
        raise ValueError(
            "temporary root contains unrecognized entries: "
            + ", ".join(sorted(unknown))
        )
    database = isolated / "research.duckdb"
    if not database.is_file() or database.is_symlink():
        raise ValueError("temporary root has an invalid isolated database")
    facts = isolated / "facts"
    if not facts.is_dir() or facts.is_symlink():
        raise ValueError("temporary root has an invalid isolated facts directory")
    derived = isolated / "derived"
    if derived.exists() and (not derived.is_dir() or derived.is_symlink()):
        raise ValueError("temporary root has an invalid derived directory")


def _capture_origin_state(isolated: Path, origin: date) -> _OriginState:
    with connect_research_warehouse(
        isolated / "research.duckdb",
        read_only=True,
    ) as connection:
        partitions = connection.execute(
            """
            select feature_set, formula_version
            from research_derived_partitions
            where analysis_date = ?
            order by feature_set, formula_version
            """,
            [origin],
        ).fetchall()
        runs = connection.execute(
            """
            select run_id from research_derived_runs
            where analysis_date = ?
            order by run_id
            """,
            [origin],
        ).fetchall()
    partition_keys = tuple((str(row[0]), str(row[1])) for row in partitions)
    expected = tuple(sorted(_FEATURE_VERSIONS))
    if partition_keys and tuple(sorted(partition_keys)) != expected:
        raise RuntimeError(
            f"temporary root contains a partial formation date: {origin.isoformat()}"
        )
    return _OriginState(
        partition_keys=partition_keys,
        run_ids=tuple(str(row[0]) for row in runs),
    )


def _rollback_origin(
    isolated: Path,
    origin: date,
    previous: _OriginState,
) -> None:
    database = isolated / "research.duckdb"
    with connect_research_warehouse(database) as connection:
        connection.begin()
        try:
            current_runs = {
                str(row[0])
                for row in connection.execute(
                    "select run_id from research_derived_runs where analysis_date = ?",
                    [origin],
                ).fetchall()
            }
            for run_id in sorted(current_runs.difference(previous.run_ids)):
                connection.execute(
                    "delete from research_derived_runs where run_id = ?",
                    [run_id],
                )
            if not previous.partition_keys:
                connection.execute(
                    "delete from research_derived_partitions where analysis_date = ?",
                    [origin],
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    if not previous.partition_keys:
        for feature_set, _ in _FEATURE_VERSIONS:
            path = isolated / "derived" / feature_set / f"analysis_date={origin.isoformat()}"
            shutil.rmtree(path, ignore_errors=True)


def _validate_feature_summary(summary: Any) -> None:
    failed = tuple(summary.failed_feature_sets)
    errors = tuple(summary.errors)
    if failed or errors:
        detail = "; ".join((*failed, *errors))
        raise RuntimeError(f"historical formation snapshot failed: {detail}")
    row_counts = {
        "market_context": int(summary.market_rows),
        "sector_hotspot": int(summary.sector_rows),
        "stock_trading_context": int(summary.stock_rows),
    }
    empty = [feature for feature, count in row_counts.items() if count <= 0]
    if empty:
        raise RuntimeError(
            "core feature output is empty: " + ", ".join(sorted(empty))
        )


def _cache_identity(
    store: DerivedFeatureStore,
    *,
    origin: date,
    cutoff: datetime,
    expected_rows: Mapping[str, int],
) -> tuple[tuple[tuple[str, str], ...], tuple[tuple[str, str], ...], str]:
    fact_hashes: list[tuple[str, str]] = []
    versions: list[tuple[str, str]] = []
    expected_as_of = cutoff.astimezone(_UTC).isoformat()
    for feature_set, formula_version in _FEATURE_VERSIONS:
        manifest = store.partition_manifest(
            feature_set,
            analysis_date=origin,
            formula_version=formula_version,
        )
        if len(manifest) != 1:
            raise RuntimeError(
                f"formation feature manifest is not unique: {feature_set}"
            )
        row = manifest.iloc[0]
        if int(row["row_count"]) != int(expected_rows[feature_set]):
            raise RuntimeError(
                f"formation feature row count mismatch: {feature_set}"
            )
        raw_input = row["input_manifest_json"]
        input_manifest = json.loads(raw_input) if isinstance(raw_input, str) else raw_input
        if not isinstance(input_manifest, Mapping):
            raise RuntimeError(f"invalid input manifest: {feature_set}")
        fact_snapshot = input_manifest.get("fact_snapshot")
        if not isinstance(fact_snapshot, Mapping):
            raise RuntimeError(f"missing fact snapshot manifest: {feature_set}")
        fact_hash = str(fact_snapshot.get("input_manifest_hash", ""))
        if len(fact_hash) != 64 or any(value not in "0123456789abcdef" for value in fact_hash):
            raise RuntimeError(f"invalid fact manifest hash: {feature_set}")
        if str(fact_snapshot.get("as_of")) != expected_as_of:
            raise RuntimeError(f"fact snapshot cutoff mismatch: {feature_set}")
        fact_hashes.append((feature_set, fact_hash))
        versions.append((feature_set, formula_version))

    cache_payload = {
        "origin": origin.isoformat(),
        "as_of": cutoff.isoformat(),
        "fact_manifest_hashes": fact_hashes,
        "formula_versions": versions,
    }
    encoded = json.dumps(
        cache_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return tuple(fact_hashes), tuple(versions), hashlib.sha256(encoded).hexdigest()


def _clone_path(source: Path, destination: Path) -> None:
    if not source.exists():
        raise FileNotFoundError(source)
    command = ["cp", "-cR" if source.is_dir() else "-c", str(source), str(destination)]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode == 0:
        return
    if source.is_dir():
        shutil.copytree(source, destination)
    else:
        shutil.copy2(source, destination)


def _remove_partial_root(root: Path) -> None:
    if root.is_symlink() or root.is_file():
        root.unlink(missing_ok=True)
    elif root.exists():
        shutil.rmtree(root)


def _update_file_hash(digest: Any, path: Path) -> None:
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)


def _json_copy(value: Mapping[str, object]) -> dict[str, object]:
    return json.loads(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )


__all__ = [
    "FormationFactView",
    "FormationFeatureView",
    "FormationSnapshot",
    "formation_cutoff",
    "materialize_formation_snapshot",
    "tree_fingerprint",
]
