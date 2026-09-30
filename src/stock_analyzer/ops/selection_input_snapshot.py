"""Sealed point-in-time trial inputs (sealed-v1).

One preparation per trial day resolves every fact table at the ORIGINAL
as_of through the existing ResearchQuery interfaces and writes plain
Parquet files plus a manifest under the day's inputs directory. Research
then reads only this local snapshot: discovery, detailed facts and the
historical industry series never fall back to the live warehouse.

This module is deliberately NOT a database: no DuckDB server, no network,
no persistent cache service and no link into the active warehouse. It only
reads files that live inside the trial inputs directory.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

SNAPSHOT_SCHEMA = 'selection-trial-facts-snapshot-v1'
FACTS_SUBDIR = 'facts'
SLOTS_SUBDIR = 'sector-slots'
MANIFEST_NAME = 'facts-snapshot.json'
FINANCIAL_DATASETS = ('income_statement', 'balance_sheet', 'cash_flow', 'financial_indicator')
# partitioned datasets the sealed reader supports for subset requests
PARTITIONED_DATASETS = {'trade_calendar', 'equity_daily', 'daily_basic'}


class SnapshotIntegrityError(Exception):
    """A sealed file that should exist is missing or corrupted.

    This is an ENGINEERING failure of the local snapshot, never a business
    gap: it must surface before any model launch and must not be swallowed
    by the ValueError/OSError/RuntimeError handlers that express optional
    data gaps.
    """


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def _same_instant(left: datetime, right: datetime) -> bool:
    return left == right  # both tz-aware; equality across zones compares instants


# These helpers belong in the existing selection_input_snapshot.py module.
# They are NOT a new storage layer or a general-purpose serializer.
_SNAPSHOT_INSTANT_FIELDS = frozenset({'available_at', 'announcement_time'})
_SNAPSHOT_METADATA_TIME_FIELDS = frozenset({'source_updated_at', 'ingested_at'})
# 'hard_risk_candidate' merely ends with the letters 'date'; the announcement
# clients emit it as a boolean flag and records() never date-projects it (the
# announcement field list excludes it), so it stays a boolean passthrough.
_SNAPSHOT_NON_DATE_FIELDS = frozenset({'hard_risk_candidate'})


def _snapshot_date_field(column: str) -> bool:
    # Same business-date interpretation as recommendation_context.records.
    if column in _SNAPSHOT_NON_DATE_FIELDS:
        return False
    return column.endswith('date') or column in {'report_period', 'valid_from', 'valid_to'}


def _snapshot_dates(series: pd.Series) -> pd.Series:
    from stock_analyzer.ops.recommendation_context import date_text
    # Object + None keeps null usable by existing `value or fallback` consumers.
    return pd.Series([date_text(v) for v in series.tolist()],
                     index=series.index, name=series.name, dtype=object)


def _snapshot_instants(series: pd.Series) -> pd.Series:
    from stock_analyzer.storage.research_query import _parse_available_at
    # Reuse the CURRENT warehouse's mixed-format/timezone interpretation.
    # No new timezone or cutoff rule is invented by serialization.
    result = _parse_available_at(series)
    if not result.isna().equals(series.isna()):
        raise SnapshotIntegrityError(f'{series.name}: non-null time became null')
    return result


def _snapshot_metadata_times(series: pd.Series) -> pd.Series:
    # Provenance-only timestamps retain an absent timezone rather than inventing
    # one. Aware values use UTC ISO text; naive values remain explicitly naive.
    from numpy import datetime64
    # Stringified-missing renderings from an ingestion path: main_business
    # carries literal 'NaT' text beside real NaT in the same provenance column.
    # A timestamp column holds no other textual meaning; business text fields
    # are never routed through this helper.
    missing_text = frozenset({'nat', 'nan', 'none', ''})
    def text(value):
        if pd.isna(value):
            return None
        if isinstance(value, str) and value.strip().lower() in missing_text:
            return None
        if not isinstance(value, (str, date, datetime, pd.Timestamp, datetime64)):
            raise SnapshotIntegrityError(f'{series.name}: unsupported timestamp type {type(value).__name__}')
        stamp = pd.Timestamp(value)
        if pd.isna(stamp):
            raise SnapshotIntegrityError(f'{series.name}: non-null timestamp became null')
        if stamp.tzinfo is not None:
            stamp = stamp.tz_convert('UTC')
        return stamp.isoformat()
    return pd.Series([text(v) for v in series.tolist()], index=series.index,
                     name=series.name, dtype=object)


def _normalize_snapshot_frame(frame: pd.DataFrame, *, dataset: str) -> tuple[pd.DataFrame, dict]:
    """Normalize only documented temporal representations; never blanket-cast.

    The caller's original frame stays untouched for an independent roundtrip
    comparison. All non-temporal business values retain their original values.
    """
    normalized = frame.copy(deep=True)
    representations = {}
    for column in frame.columns:
        try:
            if column in _SNAPSHOT_INSTANT_FIELDS:
                normalized[column] = _snapshot_instants(frame[column])
                representations[column] = 'warehouse_mixed_parse_utc_timestamp'
            elif column in _SNAPSHOT_METADATA_TIME_FIELDS:
                normalized[column] = _snapshot_metadata_times(frame[column])
                representations[column] = 'nullable_iso_provenance_timestamp'
            elif _snapshot_date_field(column):
                normalized[column] = _snapshot_dates(frame[column])
                representations[column] = 'existing_date_text_nullable_iso_date'
        except Exception as error:
            raise SnapshotIntegrityError(f'{dataset}.{column}: temporal representation failed: {error}') from error
    return normalized, representations


def _assert_snapshot_roundtrip(before: pd.DataFrame, after: pd.DataFrame, *, dataset: str) -> dict:
    """Compare the ACTUAL read-back file to the original query frame.

    Time/date spelling may change, but instants/dates, null locations, business
    values, column order and row order may not. Expected data is not generated
    from a discovery query against the just-written snapshot.
    """
    if list(before.columns) != list(after.columns) or len(before) != len(after):
        raise SnapshotIntegrityError(f'{dataset}: roundtrip columns/order/row-count mismatch')
    null_counts = {}
    for column in before.columns:
        left = before[column].reset_index(drop=True)
        right = after[column].reset_index(drop=True)
        try:
            if column in _SNAPSHOT_INSTANT_FIELDS:
                left, right = _snapshot_instants(left), _snapshot_instants(right)
            elif column in _SNAPSHOT_METADATA_TIME_FIELDS:
                left, right = _snapshot_metadata_times(left), _snapshot_metadata_times(right)
            elif _snapshot_date_field(column):
                left, right = _snapshot_dates(left), _snapshot_dates(right)
        except Exception as error:
            raise SnapshotIntegrityError(f'{dataset}.{column}: roundtrip value/order mismatch: {error}') from error
        # Null positions are compared on the normalized representation for
        # temporal columns (a stringified missing artifact reads as null on
        # both sides) and verbatim for every other column.
        if not left.isna().equals(right.isna()):
            raise SnapshotIntegrityError(f'{dataset}.{column}: roundtrip null locations changed')
        null_counts[column] = int(left.isna().sum())
        # Null FLAVOR (None vs pd.NA vs NaN vs NaT) is not a business value;
        # null positions were already verified above. Canonicalize both
        # sides so only a real value or position change can fail here.
        left = left.where(left.notna(), None)
        right = right.where(right.notna(), None)
        try:
            pd.testing.assert_series_equal(left, right, check_dtype=False,
                                           check_names=False, check_exact=True,
                                           check_categorical=False)
        except Exception as error:
            raise SnapshotIntegrityError(f'{dataset}.{column}: roundtrip value/order mismatch: {error}') from error
    return {'status': 'equal', 'source_rows': int(len(before)), 'restored_rows': int(len(after)),
            'columns_compared': int(len(before.columns)), 'null_counts': null_counts,
            'expected_source': 'original_query_frame_before_serialization'}


def save_facts_snapshot(query, inputs_dir: Path, *, formation_date: str, action_date: str,
                        as_of: datetime, price_sessions: list[str],
                        provenance: dict | None = None) -> dict:
    """Resolve and write every fact table at the ORIGINAL as_of.

    Uses only the existing ResearchQuery interfaces (dataset_as_of,
    dataset_partitions_as_of, comparable_financials_as_of) so revision and
    provider-conflict semantics stay in their original implementation. The
    manifest records per-dataset status (available / no_available_rows /
    query_failed with the original error) so the sealed reader can reproduce
    the same distinction later.
    """
    inputs_dir = Path(inputs_dir)
    facts_dir = inputs_dir / FACTS_SUBDIR
    facts_dir.mkdir(parents=True, exist_ok=True)
    cutoff = as_of
    from stock_analyzer.ops.selection_parallel import COMPANY_DATASETS
    formation_year = date.fromisoformat(formation_date).year
    # exactly the years the runtime context requests; a wider lookahead would
    # turn a legitimately absent future-year partition into a query failure
    calendar_years = [str(year) for year in (formation_year - 1, formation_year)]

    datasets: dict[str, dict] = {}

    def store(dataset: str, frame: pd.DataFrame, *, method: str, partitions=None) -> None:
        entry = {'query_method': method, 'requested_partitions': list(partitions or [])}
        if frame is None:
            datasets[dataset] = entry
            return
        path = facts_dir / f'{dataset}.parquet'
        # Keep the original query result as the reference, not the encoder output.
        serialized, representations = _normalize_snapshot_frame(frame, dataset=dataset)
        try:
            serialized.to_parquet(path, index=False)
            restored = pd.read_parquet(path)
        except Exception as error:
            raise SnapshotIntegrityError(
                f'{dataset}: snapshot Parquet write/read failed; no string-cast fallback: {error}'
            ) from error
        roundtrip = _assert_snapshot_roundtrip(frame, restored, dataset=dataset)
        entry.update({'status': 'available' if not frame.empty else 'no_available_rows',
                      'path': f'{FACTS_SUBDIR}/{dataset}.parquet',
                      'row_count': int(len(frame)), 'columns': list(frame.columns),
                      'sha256': _sha256_file(path),
                      'representation_normalization': representations,
                      'semantic_roundtrip': roundtrip})
        datasets[dataset] = entry

    def resolve(dataset: str, *, method: str, partitions=None) -> None:
        try:
            if method == 'partitions':
                frame = query.dataset_partitions_as_of(dataset, partitions, cutoff)
            elif method == 'comparable':
                frame = query.comparable_financials_as_of(dataset, cutoff)
            else:
                frame = query.dataset_as_of(dataset, cutoff)
        except (ValueError, OSError, RuntimeError) as error:
            datasets[dataset] = {'query_method': method, 'status': 'query_failed',
                                 'requested_partitions': list(partitions or []),
                                 'error_type': type(error).__name__,
                                 'error_detail': str(error)[:500]}
            return
        store(dataset, frame, method=method, partitions=partitions)

    for dataset in COMPANY_DATASETS:
        if dataset in FINANCIAL_DATASETS:
            resolve(dataset, method='comparable')
        else:
            resolve(dataset, method='as_of')
    resolve('security_master', method='as_of')
    resolve('industry_member', method='as_of')
    resolve('trade_calendar', method='partitions', partitions=calendar_years)
    resolve('equity_daily', method='partitions', partitions=list(price_sessions))
    resolve('daily_basic', method='partitions', partitions=[formation_date])

    manifest = {'schema': SNAPSHOT_SCHEMA, 'input_storage': 'sealed-v1',
                'formation_date': formation_date, 'action_date': action_date,
                'as_of': cutoff.isoformat(), 'provenance': provenance or {},
                'datasets': datasets,
                'sector_slots': [],
                'note': '按原as_of解析后保存的完整时点事实；研究期只读本目录，不回活跃仓；'
                        'query_failed保留原错误，no_available_rows不是工程失败'}
    return manifest


def register_sector_slot(inputs_dir: Path, manifest: dict, analysis_date: str,
                         slot_as_of: datetime, frame: pd.DataFrame, source: dict) -> dict:
    """Attach one historical sector_hotspot slot computed by the original
    run_research_features entry with its OWN (analysis_date, as_of)."""
    inputs_dir = Path(inputs_dir)
    slots_dir = inputs_dir / SLOTS_SUBDIR
    slots_dir.mkdir(parents=True, exist_ok=True)
    stamp = slot_as_of.isoformat().replace(':', '').replace('+', '_')
    name = f'{analysis_date}__{stamp}.parquet'
    path = slots_dir / name
    frame.to_parquet(path, index=False)
    slot = {'analysis_date': analysis_date, 'as_of': slot_as_of.isoformat(),
            'path': f'{SLOTS_SUBDIR}/{name}', 'row_count': int(len(frame)),
            'sha256': _sha256_file(path), 'source': source}
    manifest.setdefault('sector_slots', []).append(slot)
    return slot


def finalize_manifest(inputs_dir: Path, manifest: dict) -> dict:
    path = Path(inputs_dir) / MANIFEST_NAME
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str) + '\n',
                    encoding='utf-8')
    return manifest


class FrozenTrialQuery:
    """Read-only query over the sealed local snapshot.

    Not a ResearchWarehouse subclass and not a service: it loads Parquet
    files from the trial inputs directory, verifies each file's content hash
    on first use (per process) and reproduces the original as_of semantics
    for the three fact methods. read_sector is the historical-slot entry and
    matches the manifest by the EXACT (analysis_date, slot_as_of).
    """

    def __init__(self, inputs_dir: Path, manifest: dict):
        self.inputs_dir = Path(inputs_dir).resolve()
        self.manifest = manifest
        if manifest.get('schema') != SNAPSHOT_SCHEMA:
            raise SnapshotIntegrityError(f'封存manifest架构不符：{manifest.get("schema")!r}')
        if manifest.get('input_storage') != 'sealed-v1':
            raise SnapshotIntegrityError('manifest未声明sealed-v1')
        self.as_of = datetime.fromisoformat(manifest['as_of'])
        self._frames: dict[str, pd.DataFrame] = {}
        self._slot_frames: dict[tuple[str, str], pd.DataFrame] = {}

    # ---------------------------------------------------------- integrity

    def _verified_path(self, relative: str) -> Path:
        path = (self.inputs_dir / relative).resolve()
        if not path.is_relative_to(self.inputs_dir):
            raise SnapshotIntegrityError(f'封存文件路径越界：{relative}')
        if not path.is_file():
            raise SnapshotIntegrityError(f'封存文件缺失：{relative}')
        return path

    def _load_dataset(self, dataset: str) -> pd.DataFrame | None:
        if dataset in self._frames:
            return self._frames[dataset]
        entry = self.manifest['datasets'].get(dataset)
        if entry is None:
            raise SnapshotIntegrityError(f'封存manifest缺少数据集：{dataset}')
        if entry.get('status') == 'query_failed':
            error_type = entry.get('error_type') or 'RuntimeError'
            error_cls = {'ValueError': ValueError, 'OSError': OSError}.get(error_type, RuntimeError)
            raise error_cls(entry.get('error_detail') or f'{dataset} 原查询失败')
        if 'path' not in entry:
            raise SnapshotIntegrityError(f'封存数据集无文件记录：{dataset}')
        path = self._verified_path(entry['path'])
        digest = _sha256_file(path)
        if digest != entry.get('sha256'):
            raise SnapshotIntegrityError(f'封存文件内容与manifest哈希不符：{dataset}')
        frame = pd.read_parquet(path)
        if len(frame) != entry.get('row_count'):
            raise SnapshotIntegrityError(
                f'封存文件行数与manifest不符：{dataset} {len(frame)}!={entry.get("row_count")}')
        self._frames[dataset] = frame
        return frame

    def _check_cutoff(self, as_of: datetime, *, what: str) -> None:
        if as_of.tzinfo is None:
            raise ValueError('请求截止必须带时区')
        if not _same_instant(as_of, self.as_of):
            raise SnapshotIntegrityError(
                f'{what}请求截止与封存主截止不是同一时刻：{as_of.isoformat()} vs '
                f'{self.as_of.isoformat()}；封存输入不按其它时点重解析')

    # ------------------------------------------------------------ queries

    def dataset_as_of(self, dataset_id, as_of: datetime) -> pd.DataFrame:
        dataset = str(getattr(dataset_id, 'value', dataset_id))
        self._check_cutoff(as_of, what=f'{dataset} dataset_as_of ')
        frame = self._load_dataset(dataset)
        return frame.copy() if frame is not None else pd.DataFrame()

    def dataset_partitions_as_of(self, dataset_id, partition_values, as_of: datetime) -> pd.DataFrame:
        dataset = str(getattr(dataset_id, 'value', dataset_id))
        self._check_cutoff(as_of, what=f'{dataset} dataset_partitions_as_of ')
        frame = self._load_dataset(dataset)
        if frame is None or frame.empty:
            return pd.DataFrame()
        if dataset not in PARTITIONED_DATASETS:
            raise SnapshotIntegrityError(f'封存读取不支持按分区子集的数据集：{dataset}')
        requested = {str(value) for value in partition_values}
        sealed = set(self.manifest['datasets'][dataset].get('requested_partitions') or [])
        missing = sorted(requested - sealed)
        if missing:
            raise SnapshotIntegrityError(
                f'请求分区超出已封存范围（不回活跃仓）：{dataset} {missing[:8]}')
        column = 'cal_date' if dataset == 'trade_calendar' else 'trade_date'
        if column not in frame.columns:
            raise SnapshotIntegrityError(f'封存表缺少分区列：{dataset}.{column}')
        values = frame[column].astype(str).str[:10] if dataset != 'trade_calendar' \
            else frame[column].astype(str).str[:4]
        return frame[values.isin(requested)].copy()

    def comparable_financials_as_of(self, dataset_id, as_of: datetime) -> pd.DataFrame:
        dataset = str(getattr(dataset_id, 'value', dataset_id))
        self._check_cutoff(as_of, what=f'{dataset} comparable_financials_as_of ')
        frame = self._load_dataset(dataset)
        return frame.copy() if frame is not None else pd.DataFrame()

    def read_sector(self, feature: str, analysis_date: str, as_of: datetime) -> pd.DataFrame:
        if feature != 'sector_hotspot':
            raise SnapshotIntegrityError(f'封存行业读取只支持sector_hotspot：{feature}')
        if as_of.tzinfo is None:
            raise ValueError('行业槽位截止必须带时区')
        if as_of > self.as_of:
            raise ValueError('行业槽位截止晚于封存主截止，不能用该槽位')
        key = (analysis_date, as_of.isoformat())
        if key in self._slot_frames:
            return self._slot_frames[key].copy()
        slot = next((entry for entry in self.manifest.get('sector_slots', [])
                     if entry.get('analysis_date') == analysis_date
                     and entry.get('as_of') == as_of.isoformat()), None)
        if slot is None:
            raise ValueError(
                f'封存输入没有与该槽位精确匹配的本封存行业结果：sector_hotspot/'
                f'{analysis_date}@{as_of.isoformat()}；不能取邻近日替代')
        path = self._verified_path(slot['path'])
        if _sha256_file(path) != slot.get('sha256'):
            raise SnapshotIntegrityError(f'行业槽位文件哈希不符：{slot["path"]}')
        frame = pd.read_parquet(path)
        self._slot_frames[key] = frame
        return frame.copy()


def load_frozen_query(catalog_path: Path, catalog: dict) -> FrozenTrialQuery:
    """Build the sealed reader for a catalog that declares sealed-v1."""
    if catalog.get('input_storage') != 'sealed-v1':
        raise ValueError('catalog未声明sealed-v1输入')
    manifest_path = Path(catalog_path).parent / catalog.get('facts_snapshot', MANIFEST_NAME)
    if not manifest_path.is_file():
        raise SnapshotIntegrityError(f'缺少封存manifest：{manifest_path}')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    identity = ((manifest.get('formation_date'), manifest.get('action_date'), manifest.get('as_of')))
    expected = ((catalog.get('formation_date'), catalog.get('action_date'), catalog.get('as_of')))
    if identity != expected:
        raise SnapshotIntegrityError(f'封存manifest身份与catalog不一致：{identity} vs {expected}')
    return FrozenTrialQuery(Path(catalog_path).parent, manifest)
