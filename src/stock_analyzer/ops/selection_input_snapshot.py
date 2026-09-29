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
    calendar_years = [str(year) for year in range(formation_year - 1, formation_year + 2)]

    datasets: dict[str, dict] = {}

    def _normalize_mixed_columns(frame: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
        """Real warehouses carry mixed int/str in some object columns (e.g.
        report_period across providers); parquet needs one type per column.
        Only columns with genuinely mixed python types are cast to str — the
        lossless superset — and the cast is recorded in the manifest."""
        normalized = []
        for column in frame.columns:
            series = frame[column]
            if series.dtype != object:
                continue
            values = series.dropna()
            if not len(values):
                continue
            kinds = {type(value).__name__ for value in values.tolist()}
            if len(kinds) > 1:
                frame[column] = series.astype(str)
                normalized.append(column)
        return frame, normalized

    def store(dataset: str, frame: pd.DataFrame, *, method: str, partitions=None) -> None:
        entry = {'query_method': method, 'requested_partitions': list(partitions or [])}
        if frame is None:
            datasets[dataset] = entry
            return
        path = facts_dir / f'{dataset}.parquet'
        frame, normalized_columns = _normalize_mixed_columns(frame)
        try:
            frame.to_parquet(path, index=False)
        except Exception:
            # last-resort superset cast: real provider frames can defeat the
            # per-column heuristic (extension dtypes, decimal mixes); every
            # object column becomes str so the sealed file is still lossless
            # for the string-oriented readers and the cast is recorded
            for column in frame.columns:
                if frame[column].dtype == object:
                    frame[column] = frame[column].astype(str)
                    if column not in normalized_columns:
                        normalized_columns.append(column)
            frame.to_parquet(path, index=False)
        if normalized_columns:
            entry['mixed_type_columns_cast_to_str'] = normalized_columns
        entry.update({'status': 'available' if not frame.empty else 'no_available_rows',
                      'path': f'{FACTS_SUBDIR}/{dataset}.parquet',
                      'row_count': int(len(frame)),
                      'columns': list(frame.columns),
                      'sha256': _sha256_file(path)})
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
