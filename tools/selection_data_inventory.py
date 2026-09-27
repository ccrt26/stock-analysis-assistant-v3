#!/usr/bin/env python3
"""Read-only project data inventory; writes only the explicit trial maintenance output."""
from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path

from stock_analyzer.storage.research_schema import connect_research_warehouse

FIELDS = ('relative_path','bytes','category','producer','consumer','registered','rebuild','disposition')
CLEANUP_FIELDS = ('relative_path','bytes','reason','rebuild','still_referenced','rebuild_verified')


def _classification(rel: str, registered: bool) -> tuple[str,str,str,str,str]:
    if rel == 'local_warehouse/research.duckdb' or rel.startswith('local_warehouse/facts/'):
        return ('基础事实','data ingest / ResearchWarehouse','ResearchQuery / formal research / trial facts',
                '保留原件；不能仅因可下载而清理','保留')
    if rel.startswith('local_warehouse/derived/'):
        return ('可再生派生','data derive','formal research / trial neutral inputs',
                '需以原输入与公式做局部重建核对；本次未验证','保留待核')
    if rel.startswith(('local_archive/forward_selection/','local_archive/forward_monitor/',
                       'local_archive/company_introductions/')):
        return ('正式记录','formal AI tasks / record functions','formal follow-up / WEB / audit',
                '不可作为试验缓存重建','保留')
    if rel.startswith(('local_archive/data_repairs/','local_archive/repairs/',
                       'local_archive/change_backups/','local_archive/migrations/')):
        return ('修复备份与证据','data repair / migration','recovery / audit',
                '保留原始备份；须逐项核对恢复依赖','保留')
    if rel.startswith(('local_archive/ai_tasks/','local_archive/price_indicator_validation/',
                       'local_archive/research_clarifications/','local_archive/audits/')):
        return ('决策或验证证据','research / AI tasks','research audit / follow-up',
                '原输入、模型输出或验证结果不能凭文件名判为临时','保留')
    if rel.startswith('local_archive/publish/'):
        return ('展示与回退产物','formal publishing','current WEB / last-known-good fallback',
                '本次未验证重建和回退关系','保留待核')
    if rel.startswith('local_archive/selection_trials/'):
        return ('试验决策证据','selection_parallel','trial batch review / audit',
                '原短决定与原始模型输出不可重算替代','保留')
    if rel.startswith('local_archive/skill_optimization/'):
        return ('人工方法研究证据','manual method review','selection_method_review / WEB',
                '不可作为新试验缓存重建','保留')
    if rel.startswith('logs/'):
        return ('用途待核日志','scheduled tasks / CLI','incident review; exact consumers unverified',
                '未核清引用和保留期','保留待核')
    if rel.startswith('local_warehouse/.staging/') or rel.startswith('local_warehouse/.backfill_staging/'):
        return ('用途待核暂存','ResearchWarehouse recovery / data backfill','recovery check unverified',
                '未核清中断恢复依赖','保留待核')
    if registered:
        return ('仓库登记对象','ResearchWarehouse','ResearchQuery', '核对登记与依赖后方能处理','保留')
    return ('未知','未确认','未确认','未验证可重建','保留待核')


def inventory(source_root: Path, output_dir: Path) -> tuple[Path,Path]:
    source_root = source_root.resolve()
    output_dir = output_dir.resolve()
    if output_dir.name != 'maintenance' or output_dir.parent.name != 'confirmation-cost-v3' or output_dir.parent.parent.name != 'selection_trials':
        raise ValueError('output must be the isolated selection_trials/confirmation-cost-v3/maintenance directory')
    warehouse = source_root / 'local_warehouse'
    archive = source_root / 'local_archive'
    if not warehouse.is_dir() or not archive.is_dir():
        raise ValueError('source warehouse/archive missing')
    registered: set[str] = set()
    db = warehouse / 'research.duckdb'
    with connect_research_warehouse(db, read_only=True) as con:
        for table in ('research_fact_partitions','research_derived_partitions'):
            for (path,) in con.execute(f'select relative_path from {table}').fetchall():
                registered.add('local_warehouse/' + str(path).lstrip('/'))
    rows = []
    for base in (warehouse, archive, source_root / 'logs'):
        if not base.exists():
            continue
        for here, dirs, files in os.walk(base, followlinks=False):
            dirs[:] = [d for d in dirs if not (Path(here)/d).is_symlink()]
            for name in files:
                path = Path(here) / name
                if path.is_symlink() or not path.is_file():
                    continue
                rel = path.relative_to(source_root).as_posix()
                if output_dir.is_relative_to(path) or path.is_relative_to(output_dir):
                    continue
                flag = rel in registered
                category, producer, consumer, rebuild, disposition = _classification(rel, flag)
                rows.append(dict(relative_path=rel, bytes=path.stat().st_size,
                                 category=category, producer=producer, consumer=consumer,
                                 registered=flag, rebuild=rebuild, disposition=disposition))
    rows.sort(key=lambda x: x['relative_path'])
    output_dir.mkdir(parents=True, exist_ok=True)
    listing = output_dir / 'inventory.csv'
    with listing.open('w',encoding='utf-8-sig',newline='') as f:
        writer = csv.DictWriter(f,fieldnames=FIELDS)
        writer.writeheader();writer.writerows(rows)
    # No item is recommended for deletion until a specific consumer and rebuild
    # check has passed. The empty proposal is an explicit result, not cleanup.
    proposal = output_dir / 'cleanup-proposal.csv'
    with proposal.open('w',encoding='utf-8-sig',newline='') as f:
        csv.DictWriter(f,fieldnames=CLEANUP_FIELDS).writeheader()
    return listing, proposal


def main() -> int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-root',type=Path,required=True)
    p.add_argument('--output-dir',type=Path,required=True)
    a=p.parse_args()
    listing,proposal=inventory(a.source_root,a.output_dir)
    print(f'inventory={listing}\ncleanup_proposal={proposal}\nno files were deleted')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
